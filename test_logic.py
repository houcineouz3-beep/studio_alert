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
    <h1>R&eacute;sidence Philosophia</h1>
    <span class="tag">PMR</span><span class="tag">{badge}</span>
    <a href="#reservation">Voir les disponibilit&eacute;s</a>
    <h2>Choisir mon logement et r&eacute;server</h2>
    <iframe src="https://w2.Fac-Habitat.com/Philosophia/p/4/21/7614/version=iframe_reservation"></iframe>
    {VOISINES}</body></html>"""

WIDGET_FERME = "<html><body><p>Aucun logement disponible pour cette p&eacute;riode.</p></body></html>"
WIDGET_OUVERT = "<html><body><h3>T1 meubl&eacute; 491&euro;</h3><button>D&eacute;poser une demande</button></body></html>"

cas = [
    ("Complet + module ferme",          page("Complet"),          WIDGET_FERME,  "COMPLET"),
    ("Complet mais module ouvert",      page("Complet"),          WIDGET_OUVERT, "DISPONIBLE"),
    ("Dispo immediate",                 page("Dispo imm&eacute;diate"), WIDGET_OUVERT, "DISPONIBLE"),
    ("Dispo a venir",                   page("Dispo &agrave; venir"),   WIDGET_FERME,  "BIENTOT"),
    ("Complet sans iframe accessible",  page("Complet"),          None,          "COMPLET"),
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
print(f"{'OK ' if url else 'ECHEC'} | iframe detectee -> {url}")
ok &= bool(url)

# verification que le bloc des residences voisines est bien coupe
voisines = list(check.page_strings(page("Complet")))
sans_voisines = not any("saint-jacques" in p for p in voisines)
print(f"{'OK ' if sans_voisines else 'ECHEC'} | bloc 'residences a proximite' ignore")
ok &= sans_voisines

print("\nRESULTAT :", "tous les tests passent" if ok else "il reste des echecs")
