# -*- coding: utf-8 -*-
"""Smoke test des « étiquettes invisibles » GEO + du plan pour les IA (22/06/2026).

Les pages GEO publiées sur les sites clients partaient en HTML nu : aucune
donnée structurée (JSON-LD) que les IA et Google lisent, et aucun fichier
llms.txt (le plan du site pour les robots IA). Ce test vérifie SANS réseau :

  1. _geo_parse_faq_pairs : repère bien les couples question/réponse.
  2. _geo_build_jsonld : Article + FAQPage + BreadcrumbList, JSON valide,
     impossible de casser le <script>, dates + auteur présents, et PAS de
     FAQPage hors d'une vraie FAQ.
  3. _geo_build_html_page : la page contient les étiquettes et échappe un
     titre piégé (guillemet, <).
  4. _geo_build_llms_txt : format llms.txt correct, page en cours incluse,
     dédoublonnage des URLs.
  5. Le prompt du générateur pousse à écrire pour être cité.

Usage :  python scripts/smoke_geo_structured.py
"""
from __future__ import annotations

import json
import re
import sys
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

api = Api()

SITE = {
    "id": "s1", "name": "Pixel Pros", "brand": "Pixel Pros",
    "url": "https://pixel-pros.fr", "domain": "pixel-pros.fr",
}

FAQ_MD = (
    "La réponse courte : oui, en structurant la page pour les IA.\n\n"
    "## Comment optimiser une page pour ChatGPT ?\n"
    "Mets une réponse directe en tête, des titres clairs et des chiffres. "
    "En 2025, les pages structurées sont citées deux fois plus souvent.\n\n"
    "## Faut-il un blog pour être cité ?\n"
    "Non. Une page de référence bien faite suffit. L'important est la "
    "clarté et des faits vérifiables.\n\n"
    "## Combien de temps avant d'être cité ?\n"
    "Comptez deux à six semaines selon la fraîcheur d'indexation des IA.\n"
)

GUIDE_MD = (
    "Voici la marche à suivre en trois étapes.\n\n"
    "## Choisir le sujet\n"
    "Prends une question fréquente de tes clients.\n\n"
    "## Rédiger la réponse\n"
    "Sois direct et factuel.\n"
)


def extract_jsonld(html: str) -> list:
    out = []
    for m in re.finditer(
        r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL
    ):
        out.append(json.loads(m.group(1)))  # json.loads décode < etc.
    return out


print("1) Repérage des questions/réponses…")
pairs = api._geo_parse_faq_pairs(FAQ_MD)
check("3 couples Q/R détectés", len(pairs) == 3, f"(trouvé {len(pairs)})")
check("la 1re question est bien la bonne",
      pairs and pairs[0][0].startswith("Comment optimiser"))
check("la réponse est rattachée à sa question",
      pairs and "réponse directe" in pairs[0][1])
check("un guide (titres sans ?) ne produit pas de Q/R",
      len(api._geo_parse_faq_pairs(GUIDE_MD)) == 0)

print("2) Étiquettes invisibles (JSON-LD)…")
jl = api._geo_build_jsonld(
    kind="faq", title="Être cité par les IA", meta_description="Réponse claire.",
    canonical="https://pixel-pros.fr/geo/etre-cite-par-les-ia", site=SITE,
    content_md=FAQ_MD, published_at="2026-06-01T10:00:00",
    modified_at="2026-06-22T09:00:00",
)
blocks = extract_jsonld(f"<head>{jl}</head>")
types = [b.get("@type") for b in blocks]
check("3 blocs : Article + FAQPage + BreadcrumbList",
      types == ["Article", "FAQPage", "BreadcrumbList"], f"({types})")
art = next(b for b in blocks if b["@type"] == "Article")
check("Article : date de publi conservée",
      art.get("datePublished") == "2026-06-01T10:00:00")
check("Article : date de modif = aujourd'hui (fraîcheur)",
      art.get("dateModified") == "2026-06-22T09:00:00")
check("Article : auteur = la marque",
      art.get("author", {}).get("name") == "Pixel Pros")
check("Article : pointe sur l'URL canonique",
      art.get("mainEntityOfPage", {}).get("@id", "").endswith("etre-cite-par-les-ia"))
faq = next(b for b in blocks if b["@type"] == "FAQPage")
check("FAQPage : 3 questions", len(faq.get("mainEntity", [])) == 3)
check("FAQPage : 1re question correcte",
      faq["mainEntity"][0]["name"].startswith("Comment optimiser"))
bc = next(b for b in blocks if b["@type"] == "BreadcrumbList")
check("Fil d'Ariane : Accueil -> page", len(bc.get("itemListElement", [])) == 2)

# Pas de FAQPage quand ce n'est pas une FAQ
jl_guide = api._geo_build_jsonld(
    kind="guide", title="Guide", meta_description="d", canonical="https://x.fr/geo/g",
    site=SITE, content_md=GUIDE_MD, published_at="", modified_at="2026-06-22T09:00:00",
)
gtypes = [b.get("@type") for b in extract_jsonld(f"<head>{jl_guide}</head>")]
check("un guide n'a PAS de FAQPage", "FAQPage" not in gtypes, f"({gtypes})")

# Sécurité : impossible de sortir du <script>
jl_evil = api._geo_build_jsonld(
    kind="faq", title='</script><script>alert(1)</script>',
    meta_description="x", canonical="https://x.fr/geo/p", site=SITE,
    content_md=FAQ_MD, published_at="", modified_at="2026-06-22T09:00:00",
)
check("aucun </script> brut dans les étiquettes (pas d'évasion)",
      "</script><script>alert" not in jl_evil)
check("les étiquettes restent du JSON valide malgré le titre piégé",
      len(extract_jsonld(f"<head>{jl_evil}</head>")) >= 1)

print("3) Page HTML complète…")
page = api._geo_build_html_page(
    title='Titre "piégé" <x>', content_html="<p>corps</p>", css_href="style.css",
    site_name="Pixel Pros", meta_description="desc",
    canonical="https://pixel-pros.fr/geo/p", jsonld_html=jl,
    published_at="2026-06-01T10:00:00",
)
check("la page embarque les étiquettes invisibles",
      'application/ld+json' in page)
check("titre piégé échappé (pas de <x> brut dans le <title>)",
      "<x>" not in page and "&lt;x&gt;" in page)
check("date de publi affichée en pied de page", "2026-06-01" in page)

print("4) Plan du site pour les IA (llms.txt)…")
root = {
    "generated": [
        {"topic": "Ancienne page", "content": "Réponse ancienne très utile ici.",
         "publications": [{"site_id": "s1",
                           "url": "https://pixel-pros.fr/geo/ancienne-page"}]},
        {"topic": "Page d'un autre site", "content": "x",
         "publications": [{"site_id": "autre",
                           "url": "https://autre.fr/geo/z"}]},
    ]
}
llms = api._geo_build_llms_txt(
    SITE, root,
    extra=[("Être cité par les IA", "https://pixel-pros.fr/geo/etre-cite-par-les-ia",
            "Réponse claire et structurée.")],
)
check("titre = la marque", llms.startswith("# Pixel Pros"))
check("section des pages de référence", "## Pages de référence" in llms)
check("la page en cours est listée", "etre-cite-par-les-ia" in llms)
check("l'ancienne page est listée aussi", "ancienne-page" in llms)
check("les pages d'un AUTRE site sont exclues", "autre.fr" not in llms)
check("section À propos avec le site officiel",
      "## À propos" in llms and "https://pixel-pros.fr/" in llms)

# Dédoublonnage : la même URL passée en extra ET déjà publiée n'apparaît qu'une fois
root2 = {"generated": [
    {"topic": "Doublon", "content": "c",
     "publications": [{"site_id": "s1", "url": "https://pixel-pros.fr/geo/d"}]},
]}
llms2 = api._geo_build_llms_txt(
    SITE, root2, extra=[("Doublon", "https://pixel-pros.fr/geo/d", "c")])
check("une URL en double n'apparaît qu'une fois",
      llms2.count("https://pixel-pros.fr/geo/d") == 1)

print("5) Le générateur écrit pour être cité…")
src = (HERE / "triskell_command" / "web" / "api.py").read_text(encoding="utf-8")
check("le prompt impose la réponse directe en tête",
      "réponse directe et autonome" in src)
check("le prompt impose des chiffres avec leur origine",
      "au moins 2 chiffres" in src and "selon" in src)
check("le prompt impose des sections autoportantes",
      "se comprendre seule" in src)

print()
print(f"{len(PASS)} OK / {len(FAIL)} échec(s)")
sys.exit(1 if FAIL else 0)
