# -*- coding: utf-8 -*-
"""Smoke test : design des pages en série (validé par Jordan le 22/06/2026).

Protège la mise en page éditoriale des pages en série (RankUs) contre les
régressions : hero plein écran, piliers, bandes, images, citation, encart
erreurs, sommaire, animations, étiquettes invisibles. Sans réseau.

Usage :  python scripts/smoke_phare_prog_design.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
CORE = HERE.parent / "triskell-core"
if CORE.exists():
    sys.path.insert(0, str(CORE))

PASS, FAIL = [], []


def check(label, cond, detail=""):
    (PASS if cond else FAIL).append(label)
    print(f"  {'OK  ' if cond else 'FAIL'}- {label} {detail if not cond else ''}")


from triskell_command.web.api import Api  # noqa: E402
from triskell_command.integrations.phare.programmatic import (  # noqa: E402
    _slugify_url)

api = Api()

# Contenu réaliste : intro + 6 sections (dont fiche/avis/erreurs).
CONTENT = (
    "<p>Le secteur est disputé sur Google partout en France aujourd'hui.</p>"
    "<h2>Ce qui change quand on est électricien</h2>"
    "<p>En 2025, les pages bien faites sortent deux fois plus souvent.</p>"
    "<ul><li>un point</li><li>un autre</li></ul>"
    "<h2>Les recherches que font vraiment vos clients</h2><p>Texte normal.</p>"
    "<h2>Votre fiche Google Business Profile</h2><p>La fiche compte beaucoup.</p>"
    "<h2>Le contenu qui vous fait sortir</h2><p>Du contenu utile.</p>"
    "<h2>Les avis clients, votre meilleur atout</h2><p>Les avis pèsent lourd.</p>"
    "<h2>Les erreurs fréquentes chez les électriciens</h2>"
    "<p>À éviter absolument.</p><ul><li>faux horaires</li></ul>")

print("1) Adresses propres pour métiers accentués…")
check("électricien → /referencement-electricien (sans accent)",
      _slugify_url("/referencement-électricien") == "/referencement-electricien")
check("kinésithérapeute slugifié",
      _slugify_url("/x-kinésithérapeute") == "/x-kinesitherapeute")
check("URL déjà propre inchangée",
      _slugify_url("/referencement-restaurant") == "/referencement-restaurant")

print("2) Images (en-tête métier + concept réutilisables)…")
check("électricien → photo d'en-tête", "photo-1682345262055" in api._prog_hero_image("électricien"))
check("métier inconnu → pas de photo", api._prog_hero_image("notaire") == "")
check("image concept fiche (Maps)", "photo-1548345680" in api._prog_concept_image("gbp"))
check("image concept avis (étoiles)", "photo-1633613286991" in api._prog_concept_image("avis"))

print("3) Citation mise en avant (uniquement depuis les paragraphes)…")
pull = api._prog_pick_pullquote(CONTENT)
check("une phrase à chiffre est choisie", bool(pull) and any(c.isdigit() for c in pull))
check("la citation ne contient pas de titre de section",
      "Ce qui change" not in pull)

print("4) Décorateur → structure en bandes…")
toc, intro, bands = api._prog_decorate_article(CONTENT)
check("renvoie 3 morceaux (sommaire, intro, bandes)", bool(toc) and bool(intro) and bool(bands))
check("sommaire cliquable", "geo-toc" in toc and "Au sommaire" in toc)
check("chaque section devient une bande", bands.count('class="geo-band') >= 6)
check("bandes alternées (--alt)", "geo-band--alt" in bands)
check("citation en bande verte (--quote)", "geo-band--quote" in bands)
check("erreurs en bande d'alerte (--warn)", "geo-band--warn" in bands)
check("image Maps dans la section fiche", "photo-1548345680" in bands)
check("image avis dans la section avis", "photo-1633613286991" in bands)
check("bandes animées à l'apparition (.reveal)", "geo-band reveal" in bands)

print("5) Page complète…")
page = api._prog_build_native_page(
    title='Référencement pour électricien <"piégé">', content_html=CONTENT,
    shell={"head": "<link rel=stylesheet href=style.css>",
           "header": "<header>MENU</header>", "footer": "<footer>PIED</footer>",
           "scripts": "<script src=x.js></script>"},
    site_name="RankUs Studio", meta_description="La stratégie qui marche.",
    canonical="https://rankus-studio.fr/referencement-electricien",
    jsonld_html='<script type="application/ld+json">{}</script>',
    hero_img_url=api._prog_hero_image("électricien"),
    cta_html=api._prog_cta_html("électricien", "RankUs Studio"))
check("hero PLEIN ÉCRAN (photo en fond + dégradé)",
      'class="geo-hero"' in page and "linear-gradient" in page and "photo-1682345262055" in page)
check("3 piliers en cartes", page.count('geo-pillar"') == 3)
check("en-tête + menu + pied du site", "MENU" in page and "PIED" in page)
check("charte du site (CSS + scripts)", "style.css" in page and "x.js" in page)
check("étiquettes invisibles (JSON-LD)", "application/ld+json" in page)
check("animations (apparition au défilement)",
      "IntersectionObserver" in page and "geo-anim" in page and "prefers-reduced-motion" in page)
check("zoom photo au survol + scroll doux",
      ":hover img" in page and "scroll-behavior: smooth" in page)
check("titre piégé échappé (pas de <\"piégé\"> brut)",
      '<"piégé">' not in page and "&lt;" in page)
check("encart d'action vers l'offre", "geo-cta" in page and "Découvrir RankUs Studio" in page)

print("6) Habillage repris du site (index.html cloné)…")
wd = tempfile.mkdtemp()
with open(os.path.join(wd, "index.html"), "w", encoding="utf-8") as fh:
    fh.write('<!doctype html><html><head>'
             '<link rel="stylesheet" href="style.css">'
             '<link rel="preconnect" href="https://fonts.googleapis.com"></head>'
             '<body><header class="nav">RankUs</header><main>x</main>'
             '<footer class="footer">pied</footer>'
             '<script src="script.js"></script></body></html>')
shell = api._extract_site_shell(wd)
check("CSS + police extraits", "style.css" in shell["head"] and "fonts.google" in shell["head"])
check("en-tête extrait", 'class="nav"' in shell["header"])
check("pied de page extrait", "footer" in shell["footer"])
check("scripts extraits", "script.js" in shell["scripts"])

print("7) Plan du site (sitemap) tenu à jour…")


class _FakeSB:
    def table(self, *a):
        return self

    def select(self, *a):
        return self

    def eq(self, *a):
        return self

    def execute(self):
        class R:
            data = [{"generated_url": "/referencement-restaurant"}]
        return R()


sm_dir = tempfile.mkdtemp()
with open(os.path.join(sm_dir, "sitemap.xml"), "w", encoding="utf-8") as fh:
    fh.write('<?xml version="1.0" encoding="UTF-8"?>\n'
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
             '  <url><loc>https://rankus-studio.fr/</loc></url>\n</urlset>\n')
api._prog_sync_sitemap(sm_dir, "rankus-studio.fr", _FakeSB(), "s1",
                       ["https://rankus-studio.fr/referencement-avocat",
                        "https://rankus-studio.fr/referencement-restaurant"])
sm = open(os.path.join(sm_dir, "sitemap.xml"), encoding="utf-8").read()
check("accueil préservé", "rankus-studio.fr/</loc>" in sm)
check("nouvelle page ajoutée", sm.count("referencement-avocat") == 1)
check("pas de doublon", sm.count("referencement-restaurant") == 1)
check("XML refermé proprement", sm.strip().endswith("</urlset>"))

print()
print(f"{len(PASS)} OK / {len(FAIL)} échec(s)")
sys.exit(1 if FAIL else 0)
