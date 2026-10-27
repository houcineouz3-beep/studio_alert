#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fac-habitat-watcher
===================
Surveille des pages de residences sur logement.smerra.fr (Fac-Habitat / Logifac)
et previent par Telegram et/ou e-mail des qu'une residence n'est plus "Complet"
(= le bouton de reservation / depot de demande redevient accessible).

Utilisation :
    python check.py                 # une seule verification (mode GitHub Actions / cron)
    python check.py --loop 10       # boucle infinie, une verif toutes les 10 minutes
    python check.py --test          # envoie une notification de test et quitte
    python check.py --force         # notifie l'etat actuel meme s'il n'a pas change
    python check.py --debug         # affiche le detail de l'analyse de chaque page
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import smtplib
import ssl
import sys
import time
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

ROOT = Path(__file__).resolve().parent
RESIDENCES_FILE = Path(os.getenv("RESIDENCES_FILE") or (ROOT / "residences.json"))
STATE_FILE = Path(os.getenv("STATE_FILE") or (ROOT / "state.json"))

TELEGRAM_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
TELEGRAM_CHAT_ID = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()

SMTP_HOST = (os.getenv("SMTP_HOST") or "smtp.gmail.com").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT") or 465)
SMTP_USER = (os.getenv("SMTP_USER") or "").strip()
SMTP_PASSWORD = (os.getenv("SMTP_PASSWORD") or "").strip()
MAIL_TO = (os.getenv("MAIL_TO") or SMTP_USER).strip()

# 1 = prevenir aussi quand le contenu du module de reservation change
# (utile si le site change ses libelles, mais peut generer des faux positifs)
ALERT_ON_FINGERPRINT = (os.getenv("ALERT_ON_FINGERPRINT") or "0").strip() == "1"
# 1 = prevenir a chaque changement d'etat (y compris DISPONIBLE -> COMPLET)
ALERT_ON_ANY_CHANGE = (os.getenv("ALERT_ON_ANY_CHANGE") or "0").strip() == "1"

TIMEOUT = 25
RETRIES = 3
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# --------------------------------------------------------------------------- #
# Petits utilitaires texte
# --------------------------------------------------------------------------- #

# Table 1 caractere -> 1 caractere : les index restent valides sur la chaine d'origine.
_ACCENTS_SRC = "àâäáãåçéèêëíìîïñóòôöõúùûüýÿÀÂÄÁÃÅÇÉÈÊËÍÌÎÏÑÓÒÔÖÕÚÙÛÜÝ"
_ACCENTS_DST = "aaaaaaceeeeiiiinooooouuuuyyAAAAAACEEEEIIIINOOOOOUUUUY"
_ACCENT_TABLE = str.maketrans(_ACCENTS_SRC, _ACCENTS_DST)


def fold(text: str) -> str:
    """Minuscules sans accents, en conservant la longueur (index utilisables)."""
    return text.translate(_ACCENT_TABLE).lower()


def flat(text: str) -> str:
    """Version 'aplatie' pour les recherches de mots-cles."""
    return re.sub(r"\s+", " ", fold(text)).strip()


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# --------------------------------------------------------------------------- #
# Analyse d'une page residence
# --------------------------------------------------------------------------- #

# Le bas de page liste d'AUTRES residences avec leurs propres badges "Complet".
# On coupe le HTML avant ce bloc pour ne pas melanger les etats.
CUT_MARKERS = (
    "plus de residences a proximite",
    "residences a proximite",
    "nos autres residences",
    "d'autres residences",
)

STATUS_BADGES = (
    ("DISPONIBLE", ("dispo immediate", "disponible immediatement", "dispo immediatement")),
    ("BIENTOT", ("dispo a venir", "disponible prochainement", "prochainement")),
    ("COMPLET", ("complet",)),
)

# Dans l'iframe, chaque type de logement (T1, Duo...) a son bouton "Deposer une demande" :
#   - complet    -> <button disabled ...>Deposer une demande</button>
#   - disponible -> <a class="btn_reserver" href=".../DO_ADD_TO_CART/.../TYPE_LOGEMENT=T1/...">
# Le texte est le meme dans les deux cas : seul l'etat du bouton compte.
BOOKING_LINK_MARKERS = ("do_add_to_cart", "btn_reserver")
BOOKING_LABEL = "deposer une demande"
TYPE_RE = re.compile(r"TYPE_LOGEMENT=([^/&?]+)", re.I)
# Signes explicites qu'il n'y a rien
BOOKING_NO = (
    "aucun logement disponible",
    "aucune disponibilite",
    "aucun logement ne correspond",
    "plus de logement disponible",
    "pas de disponibilite",
    "residence complete",
    "liste d'attente",
)

URL_RE = re.compile(r"""https?://[^\s"'<>\\]+""", re.I)


MAX_BADGE_LEN = 40  # un badge est une etiquette courte, pas une phrase


def page_strings(html: str):
    """Rend les textes de la page dans l'ordre, en s'arretant au bloc
    'Plus de residences a proximite' (qui liste d'AUTRES residences)."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    for raw in soup.stripped_strings:
        piece = flat(raw)
        if any(marker in piece for marker in CUT_MARKERS):
            return
        yield piece


def extract_badge(html: str) -> str:
    """Premier badge d'etat rencontre = celui de la residence surveillee."""
    for piece in page_strings(html):
        if len(piece) > MAX_BADGE_LEN:
            continue
        for label, needles in STATUS_BADGES:
            if any(n in piece for n in needles):
                return label
    return "INCONNU"


def find_booking_widget(html: str, base_url: str) -> str | None:
    """Retrouve l'URL de l'iframe de reservation (w2.fac-habitat.com / w2.logifac.fr).

    Attention : l'en-tete de chaque page contient aussi un lien "Mon compte"
    vers w2.logifac.fr/account/... (identique pour toutes les residences) : on
    cherche donc d'abord l'URL 'version=iframe_reservation'."""
    urls = URL_RE.findall(html)
    for raw in urls:
        if "iframe_reservation" in raw.lower():
            return urljoin(base_url, raw)
    for raw in urls:
        low = raw.lower()
        if ("w2.fac-habitat.com" in low or "w2.logifac.fr" in low) and "/account/" not in low:
            return urljoin(base_url, raw)
    return None


def parse_widget(widget_html: str) -> tuple[str, list[str]]:
    """Lit les boutons de l'iframe : renvoie (OUVERT|FERME|INDETERMINE, types dispo)."""
    soup = BeautifulSoup(widget_html, "html.parser")
    open_types: list[str] = []
    open_count = closed_count = 0

    for tag in soup.find_all(["a", "button"]):
        label = flat(tag.get_text(" ", strip=True) or tag.get("title", ""))
        href = tag.get("href", "")
        classes = " ".join(tag.get("class", []))
        is_link = any(m in (href + " " + classes).lower() for m in BOOKING_LINK_MARKERS)
        if not is_link and BOOKING_LABEL not in label:
            continue
        if is_link and href and not tag.has_attr("disabled"):
            open_count += 1
            m = TYPE_RE.search(href)
            kind = m.group(1).replace("+", " ") if m else "?"
            if kind not in open_types:
                open_types.append(kind)
        else:
            closed_count += 1

    text = flat(soup.get_text(" ", strip=True))
    if open_count:
        return "OUVERT", open_types
    if closed_count or any(n in text for n in BOOKING_NO):
        return "FERME", []
    return "INDETERMINE", []


def fetch(url: str, session: requests.Session) -> str | None:
    """GET avec quelques tentatives ; renvoie None en cas d'echec definitif."""
    for attempt in range(1, RETRIES + 1):
        try:
            resp = session.get(url, headers=HEADERS, timeout=TIMEOUT)
            if resp.status_code == 200:
                resp.encoding = resp.encoding or "utf-8"
                return resp.text
            log(f"  ! HTTP {resp.status_code} sur {url}")
        except requests.RequestException as exc:
            log(f"  ! erreur reseau ({attempt}/{RETRIES}) : {exc}")
        time.sleep(2 * attempt)
    return None


def analyse(page_html: str, widget_html: str | None) -> dict:
    """Renvoie l'etat de la residence : status, dispo booleen, empreinte, indices."""
    badge = extract_badge(page_html)

    widget_status = "ABSENT"
    fingerprint = ""
    types: list[str] = []
    if widget_html:
        widget_text = flat(BeautifulSoup(widget_html, "html.parser").get_text(" ", strip=True))
        fingerprint = hashlib.sha256(widget_text.encode("utf-8")).hexdigest()[:16]
        widget_status, types = parse_widget(widget_html)

    # Le module de reservation fait foi quand il a pu etre lu : c'est lui qui
    # porte le bouton. Le badge de la page ne sert que s'il est illisible.
    if widget_status == "OUVERT":
        available = True
    elif widget_status == "FERME":
        available = False
    else:
        available = badge == "DISPONIBLE"

    if available:
        status = "DISPONIBLE"
    elif badge == "BIENTOT":
        status = "BIENTOT"
    elif badge == "COMPLET" or widget_status == "FERME":
        status = "COMPLET"
    else:
        status = "INCONNU"

    return {
        "status": status,
        "available": available,
        "badge": badge,
        "widget": widget_status,
        "types": types,
        "fingerprint": fingerprint,
    }


def check_residence(res: dict, session: requests.Session, debug: bool = False) -> dict | None:
    url = res["url"]
    page = fetch(url, session)
    if page is None:
        return None

    widget_url = find_booking_widget(page, url)
    widget_html = fetch(widget_url, session) if widget_url else None

    result = analyse(page, widget_html)
    result["widget_url"] = widget_url or ""

    if debug:
        log(f"  debug -> badge={result['badge']} widget={result['widget']} "
            f"types={','.join(result['types']) or '-'} iframe={widget_url or 'aucune'}")
    return result


# --------------------------------------------------------------------------- #
# Notifications
# --------------------------------------------------------------------------- #

def send_telegram(text: str) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": False,
            },
            timeout=20,
        )
        if r.status_code != 200:
            log(f"  ! Telegram a repondu {r.status_code} : {r.text[:200]}")
            return False
        return True
    except requests.RequestException as exc:
        log(f"  ! Telegram injoignable : {exc}")
        return False


def send_email(subject: str, body_html: str) -> bool:
    if not (SMTP_USER and SMTP_PASSWORD and MAIL_TO):
        return False
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = MAIL_TO
    msg.set_content(re.sub(r"<[^>]+>", "", body_html))
    msg.add_alternative(body_html, subtype="html")
    try:
        context = ssl.create_default_context()
        if SMTP_PORT == 465:
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context, timeout=30) as s:
                s.login(SMTP_USER, SMTP_PASSWORD)
                s.send_message(msg)
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as s:
                s.starttls(context=context)
                s.login(SMTP_USER, SMTP_PASSWORD)
                s.send_message(msg)
        return True
    except Exception as exc:  # smtplib leve des exceptions tres variees
        log(f"  ! E-mail non envoye : {exc}")
        return False


def notify(title: str, lines: list[str], url: str = "") -> None:
    body = "\n".join(lines)
    tg = f"<b>{title}</b>\n\n{body}"
    if url:
        tg += f"\n\n{url}"
    ok_tg = send_telegram(tg)

    html = f"<h2>{title}</h2><p>" + "<br>".join(lines) + "</p>"
    if url:
        html += f'<p><a href="{url}">Ouvrir la page de la residence</a></p>'
    ok_mail = send_email(title, html)

    log(f"  -> notification : telegram={'OK' if ok_tg else 'non'} "
        f"mail={'OK' if ok_mail else 'non'}")


# --------------------------------------------------------------------------- #
# Etat persistant
# --------------------------------------------------------------------------- #

def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_state(state: dict) -> None:
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


# --------------------------------------------------------------------------- #
# Boucle principale
# --------------------------------------------------------------------------- #

def run_once(force: bool = False, debug: bool = False) -> int:
    residences = load_json(RESIDENCES_FILE, [])
    if not residences:
        log(f"Aucune residence dans {RESIDENCES_FILE}. Rien a faire.")
        return 1

    state = load_json(STATE_FILE, {})
    session = requests.Session()
    alerts = 0

    for res in residences:
        name, url = res.get("name") or res["url"], res["url"]
        log(f"Verification : {name}")

        result = check_residence(res, session, debug=debug)
        if result is None:
            log("  -> page inaccessible, on ignore ce tour (pas d'alerte)")
            continue

        prev = state.get(url, {})
        prev_status = prev.get("status")
        status = result["status"]
        types = result["types"]
        log(f"  -> etat : {status} (badge={result['badge']}, module={result['widget']}"
            f"{', dispo : ' + ', '.join(types) if types else ''})")

        new_types = [t for t in types if t not in prev.get("types", [])]
        became_available = status == "DISPONIBLE" and (
            prev_status != "DISPONIBLE" or bool(new_types)
        )
        changed = prev_status is not None and status != prev_status
        fp_changed = (
            ALERT_ON_FINGERPRINT
            and result["fingerprint"]
            and prev.get("fingerprint")
            and result["fingerprint"] != prev["fingerprint"]
        )

        must_alert = force or became_available or (ALERT_ON_ANY_CHANGE and changed) or fp_changed

        if must_alert:
            if became_available or force and status == "DISPONIBLE":
                title = f"🏠 {name} : des logements sont dispo !"
            elif fp_changed and not changed:
                title = f"👀 {name} : le module de reservation a change"
            else:
                title = f"ℹ️ {name} : {prev_status or 'inconnu'} → {status}"

            lines = [f"Etat : <b>{status}</b>"]
            if types:
                lines.append(f"Logements dispo : <b>{', '.join(types)}</b>")
            lines += [
                f"Badge du site : {result['badge']}",
                f"Module de reservation : {result['widget']}",
                f"Verifie le {datetime.now().strftime('%d/%m/%Y a %H:%M')}",
                "",
                "Va deposer ta demande tout de suite, ca part vite.",
            ]
            notify(title, lines, url)
            alerts += 1

        state[url] = {
            "name": name,
            "status": status,
            "badge": result["badge"],
            "widget": result["widget"],
            "types": types,
            "fingerprint": result["fingerprint"],
            "last_check": now_iso(),
            "last_alert": now_iso() if must_alert else prev.get("last_alert", ""),
        }

        time.sleep(random.uniform(1.5, 3.5))  # on reste poli avec le serveur

    save_state(state)
    log(f"Termine. {len(residences)} residence(s) verifiee(s), {alerts} alerte(s).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Surveillance des logements Fac-Habitat / Logifac")
    parser.add_argument("--loop", type=float, metavar="MINUTES",
                        help="tourner en continu, avec cet intervalle en minutes")
    parser.add_argument("--test", action="store_true",
                        help="envoyer une notification de test puis quitter")
    parser.add_argument("--force", action="store_true",
                        help="notifier l'etat actuel meme sans changement")
    parser.add_argument("--debug", action="store_true",
                        help="afficher le detail de l'analyse")
    args = parser.parse_args()

    if args.test:
        notify(
            "✅ Test du watcher Fac-Habitat",
            ["Si tu lis ce message, Telegram et/ou l'e-mail sont bien configures."],
            "https://logement.smerra.fr/",
        )
        return 0

    if args.loop:
        log(f"Mode boucle : une verification toutes les {args.loop} minutes. Ctrl+C pour arreter.")
        while True:
            try:
                run_once(force=args.force, debug=args.debug)
            except KeyboardInterrupt:
                log("Arret demande.")
                return 0
            except Exception as exc:
                log(f"Erreur inattendue : {exc}")
            # petit decalage aleatoire pour ne pas taper toujours a la meme seconde
            time.sleep(args.loop * 60 + random.uniform(0, 30))

    return run_once(force=args.force, debug=args.debug)


if __name__ == "__main__":
    sys.exit(main())
