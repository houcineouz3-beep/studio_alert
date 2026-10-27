# Surveillance des logements Fac-Habitat / Logifac

Bot qui surveille des pages de résidences sur `logement.smerra.fr` et t'envoie un
message **Telegram** (et/ou un **e-mail**) dès qu'une résidence passe de *Complet*
à *disponible*, c'est-à-dire dès que le bouton de dépôt de demande redevient accessible.

## Comment il détecte la disponibilité

Deux signaux sont combinés pour chaque résidence :

1. **Le badge d'état** affiché en haut de la page : `Complet`, `Dispo à venir` ou
   `Dispo immédiate`. Le script lit le **premier** badge de la page, ce qui évite de
   confondre avec les résidences suggérées en bas de page.
2. **Le module de réservation** : la page contient une iframe vers
   `w2.fac-habitat.com/<Résidence>/p/.../version=iframe_reservation`. Le script la
   récupère et regarde l'**état du bouton** *« Déposer une demande »* de chaque type
   de logement (T1, Duo…) : `<button disabled>` quand c'est complet, lien
   `btn_reserver` / `DO_ADD_TO_CART` quand c'est ouvert. Le libellé est le même dans
   les deux cas, il ne suffit donc pas de chercher le texte.

Quand le module a pu être lu, c'est lui qui fait foi (c'est lui qui porte le
bouton) ; sinon on se rabat sur le badge. Tu es prévenu lors du **passage** à
`DISPONIBLE`, ou quand un **nouveau type** de logement se libère — pas à chaque
exécution. L'état précédent est mémorisé dans `state.json`.

---

## Étape 1 — Créer le bot Telegram (2 minutes)

1. Dans Telegram, ouvre une discussion avec **@BotFather**.
2. Envoie `/newbot`, choisis un nom (`Mon veilleur logement`) puis un identifiant
   se terminant par `bot` (`veilleur_logement_bot`).
3. BotFather te renvoie un **token** du type `8123456789:AAH...`. C'est ton
   `TELEGRAM_BOT_TOKEN`, ne le partage jamais.
4. **Envoie `/start` à ton propre bot** — sans ça, il n'a pas le droit de t'écrire.
5. Récupère ton `TELEGRAM_CHAT_ID` : ouvre dans un navigateur
   `https://api.telegram.org/bot<TON_TOKEN>/getUpdates` et lis le champ
   `"chat":{"id":123456789}`. (Autre méthode : écrire à **@userinfobot**.)

> Pour recevoir les alertes dans un groupe : ajoute le bot au groupe, écris-y un
> message, puis relis `getUpdates` — l'id de groupe est négatif (`-100...`).

## Étape 2 — Configurer l'e-mail (optionnel)

Avec Gmail, un mot de passe normal ne marche pas :

1. Active la validation en deux étapes sur ton compte Google.
2. Va dans **Sécurité → Mots de passe des applications**, crée-en un.
3. Utilise ce mot de passe de 16 caractères comme `SMTP_PASSWORD`.

Réglages : `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=465`, `SMTP_USER=ton@gmail.com`,
`MAIL_TO=ton@gmail.com`.
Autres fournisseurs : Outlook `smtp-mail.outlook.com:587`, Yahoo `smtp.mail.yahoo.com:465`.

> **Mon conseil : mets Telegram en priorité.** La notification arrive en 1–2 secondes
> avec un son, alors qu'un e-mail peut traîner plusieurs minutes ou finir en spam —
> et sur ce genre d'annonce, quelques minutes font la différence. Garde l'e-mail en
> filet de sécurité.

## Étape 3 — Tester en local

```bash
pip install -r requirements.txt

export TELEGRAM_BOT_TOKEN="8123456789:AAH..."
export TELEGRAM_CHAT_ID="123456789"

python check.py --test     # doit faire arriver un message dans Telegram
python check.py --debug    # première vraie vérification
```

Sous Windows PowerShell, remplace `export X="y"` par `$env:X="y"`.

Commandes utiles :

| Commande | Effet |
|---|---|
| `python check.py` | une vérification puis sortie (mode cron) |
| `python check.py --loop 10` | tourne en continu, une vérif toutes les 10 min |
| `python check.py --force` | notifie l'état actuel même sans changement |
| `python check.py --debug` | affiche badge, module et iframe détectés |
| `python check.py --test` | notification de test |

## Étape 4 — Choisir les résidences

Édite `residences.json` : le fichier contient déjà une douzaine de résidences
d'Île-de-France, y compris Philosophia. Ajoute ou retire des blocs :

```json
{ "name": "Fac-Habitat Philosophia - Aubervilliers",
  "url": "https://logement.smerra.fr/residence-etudiante/fac-habitat-philosophia/" }
```

L'`url` est simplement celle de la page résidence dans ton navigateur.

## Étape 5 — Déployer gratuitement sur GitHub Actions

C'est l'option gratuite la plus simple : aucun serveur, aucune carte bancaire, et
le dépôt public bénéficie de minutes illimitées.

1. Crée un dépôt GitHub (privé si tu préfères) et pousse ces fichiers :

   ```bash
   git init
   git add .
   git commit -m "Watcher logements Fac-Habitat"
   git branch -M main
   git remote add origin https://github.com/<ton-pseudo>/<ton-repo>.git
   git push -u origin main
   ```

2. Dans le dépôt : **Settings → Secrets and variables → Actions →
   New repository secret**. Ajoute :

   | Nom | Valeur |
   |---|---|
   | `TELEGRAM_BOT_TOKEN` | le token de BotFather |
   | `TELEGRAM_CHAT_ID` | ton identifiant de discussion |
   | `SMTP_HOST` | `smtp.gmail.com` *(facultatif)* |
   | `SMTP_PORT` | `465` *(facultatif)* |
   | `SMTP_USER` | ton adresse *(facultatif)* |
   | `SMTP_PASSWORD` | mot de passe d'application *(facultatif)* |
   | `MAIL_TO` | l'adresse destinataire *(facultatif)* |

3. Onglet **Actions** → autorise les workflows → sélectionne
   *Surveillance logements Fac-Habitat* → **Run workflow** pour un premier essai
   manuel. Vérifie les logs.

4. Ensuite, la planification `*/10 * * * *` fait tourner le job toutes les
   10 minutes. Le fichier `state.json` est réécrit et committé automatiquement pour
   garder la mémoire entre deux exécutions.

### Trois pièges à connaître sur GitHub Actions

- **Le cron n'est pas ponctuel.** GitHub met les tâches planifiées en file d'attente ;
  un `*/10` s'exécute parfois avec 5 à 20 minutes de retard aux heures de pointe. Si tu
  veux une réactivité à la minute près, passe à l'hébergement permanent ci-dessous.
- **Désactivation après 60 jours.** GitHub coupe les workflows planifiés d'un dépôt
  sans activité pendant 60 jours, et les commits du bot ne comptent pas. Fais un vrai
  commit de temps en temps, ou remets le workflow en route depuis l'onglet Actions.
- **Ne mets jamais tes jetons dans le code.** Uniquement dans les *Secrets*.

## Alternative — hébergement permanent

Si tu veux une vérification vraiment toutes les 5 minutes :

- **Oracle Cloud Always Free** : machine virtuelle gratuite en permanence. Installe
  le projet, puis `crontab -e` :
  `*/5 * * * * cd /home/ubuntu/fh && /usr/bin/python3 check.py >> watcher.log 2>&1`
- **Ton propre PC ou un Raspberry Pi** : `python check.py --loop 5` dans un `screen`
  ou un service `systemd`. Gratuit, mais il faut que la machine reste allumée.
- **Fly.io / Railway / Render** : possible, mais les offres gratuites changent
  souvent et les services s'endorment.

## Réglages avancés

Variables d'environnement facultatives :

| Variable | Défaut | Rôle |
|---|---|---|
| `ALERT_ON_ANY_CHANGE` | `0` | `1` = prévenir aussi quand ça repasse à Complet |
| `ALERT_ON_FINGERPRINT` | `0` | `1` = prévenir dès que le module de réservation change (plus sensible, mais quelques fausses alertes) |
| `RESIDENCES_FILE` | `residences.json` | autre liste de résidences |
| `STATE_FILE` | `state.json` | autre emplacement pour la mémoire |

## Si le site change

Les libellés sont regroupés en haut de `check.py` (`STATUS_BADGES`,
`BOOKING_LINK_MARKERS`, `BOOKING_NO`). Si Smerra modifie ses textes, il suffit d'ajouter la nouvelle
formulation dans ces listes. `python check.py --debug` affiche le badge et l'état du
module détectés : c'est le moyen le plus rapide de voir ce qui coince. Et
`test_logic.py` vérifie la logique sans toucher au réseau (`python test_logic.py`).

## Bon usage

Le script consulte des pages publiques, comme un navigateur, et attend 1,5 à 3,5 s
entre deux résidences. Garde un intervalle d'au moins 5 minutes et une liste
raisonnable de résidences : c'est suffisant pour être prévenu avant tout le monde,
sans surcharger le serveur. Pense aussi à jeter un œil aux conditions d'utilisation
du site.

**Le bot prévient, il ne réserve pas à ta place** : il ne remplit aucun formulaire et
ne se connecte à aucun compte. Quand l'alerte tombe, c'est à toi d'ouvrir le lien et
de déposer ta demande — prépare tes pièces justificatives à l'avance pour aller vite.
