"""Test hors-ligne de la detection (aucun acces reseau)."""
import check

VOISINES = """
<section><h2>Plus de r&eacute;sidences &agrave; proximit&eacute;</h2>
  <div class="card"><span>Dispo imm&eacute;diate</span><h3>Logifac Saint-Jacques</h3></div>
  <div class="card"><span>Dispo &agrave; venir</span><h3>Fac-Habitat H&eacute;rodote</h3></div>
</section>
"""

def page(badge):
    return f"""<html><body>
    <header><a href="https://w2.logifac.fr/account/p/FORM_ACCESS/0/0/">Mon compte</a></header>
    <h1>R&eacute;sidence Philosophia</h1>
    <span class="tag">PMR</span><span class="tag">{badge}</span>
    <a href="#reservation">Voir les disponibilit&eacute;s</a>
    <h2>Choisir mon logement et r&eacute;server</h2>
    <iframe src="https://w2.Fac-Habitat.com/Philosophia/p/4/21/7614/version=iframe_reservation"></iframe>
    {VOISINES}</body></html>"""

WIDGET_FERME = "<html><body><p>Aucun logement disponible pour cette p&eacute;riode.</p></body></html>"
# Structure reelle de l'iframe w2.fac-habitat.com : le libelle est le meme,
# seul l'etat du bouton change (button disabled vs lien btn_reserver).
LIGNE_COMPLETE = """<div><span class="fw-bold">{t}</span> <span class="badge">Complet</span></div>
  <button disabled type="button" class="btn btn-secondary" title="D&eacute;poser une demande">D&eacute;poser une demande</button>"""
LIGNE_DISPO = """<div><span class="fw-bold">{t}</span> <span class="badge">Disponible</span></div>
  <a target="_blank" class="btn btn-dark btn_reserver" href="/account/p/DO_ADD_TO_CART/0/0/ID_RESIDENCE=31/TYPE_LOGEMENT={t}/ID_SESSION=x">D&eacute;poser une demande</a>"""
WIDGET_COMPLET = f"<html><body>{LIGNE_COMPLETE.format(t='Duo')}{LIGNE_COMPLETE.format(t='T1')}</body></html>"
WIDGET_OUVERT = f"<html><body>{LIGNE_COMPLETE.format(t='Duo')}{LIGNE_DISPO.format(t='T1')}</body></html>"

cas = [
    ("Complet + module ferme",          page("Complet"),          WIDGET_FERME,   "COMPLET"),
    ("Complet + boutons desactives",    page("Complet"),          WIDGET_COMPLET, "COMPLET"),
    ("Complet mais module ouvert",      page("Complet"),          WIDGET_OUVERT,  "DISPONIBLE"),
    ("Dispo immediate",                 page("Dispo imm&eacute;diate"), WIDGET_OUVERT, "DISPONIBLE"),
    ("Dispo a venir",                   page("Dispo &agrave; venir"),   WIDGET_FERME,  "BIENTOT"),
    ("Complet sans iframe accessible",  page("Complet"),          None,           "COMPLET"),
]

ok = True
for titre, html, widget, attendu in cas:
    r = check.analyse(html, widget)
    verdict = "OK " if r["status"] == attendu else "ECHEC"
    ok &= r["status"] == attendu
    print(f"{verdict} | {titre:34s} -> {r['status']:11s} "
          f"(badge={r['badge']}, module={r['widget']})")

# verification que l'iframe est bien retrouvee, meme avec une casse bizarre
url = check.find_booking_widget(page("Complet"), "https://logement.smerra.fr/x/")
bonne_iframe = bool(url) and "iframe_reservation" in url
print(f"{'OK ' if bonne_iframe else 'ECHEC'} | iframe detectee (pas le lien 'Mon compte') -> {url}")
ok &= bonne_iframe

# le type de logement libere est bien remonte
types = check.analyse(page("Complet"), WIDGET_OUVERT)["types"]
print(f"{'OK ' if types == ['T1'] else 'ECHEC'} | type dispo detecte -> {types}")
ok &= types == ["T1"]

# verification que le bloc des residences voisines est bien coupe
voisines = list(check.page_strings(page("Complet")))
sans_voisines = not any("saint-jacques" in p for p in voisines)
print(f"{'OK ' if sans_voisines else 'ECHEC'} | bloc 'residences a proximite' ignore")
ok &= sans_voisines

print("\nRESULTAT :", "tous les tests passent" if ok else "il reste des echecs")
