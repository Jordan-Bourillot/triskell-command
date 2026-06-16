# -*- coding: utf-8 -*-
"""Smoke test : mise en forme HTML des mails + liens pages métier
(correctifs du 2026-06-12, bug remonté par Jordan : « pas de mise en
forme HTML et même pas de lien dans le mail »).

Vérifie SANS réseau et SANS toucher à la base :
  1. pixelpros_pages : secteur en texte libre → bonne page de pub +
     bonne démo parmi les 12 ; secteur inconnu → accueil + démo
     générique (jamais un lien cassé, jamais un mauvais métier).
  2. _apply_placeholders : {{page_metier}} / {{page_demo}} (et la
     syntaxe {page_metier}) sont TOUJOURS remplis — aucun risque de
     blocage par le garde-fou anti-placeholder.
  3. Api._resolve_draft_html : le HTML d'un brouillon survit à
     l'approbation quand le texte est intact (même renvoyé par le
     textarea avec des \\r\\n), et est régénéré si le texte a été
     retouché — plus JAMAIS de mail envoyé en texte brut par l'UI.
  4. text_to_email_html : les URLs du texte deviennent des liens
     cliquables dans le HTML généré.

Usage :  python scripts/smoke_mails_html_liens.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Console Windows en cp1252 : on force l'UTF-8 pour les flèches/accents
# des libellés (sinon UnicodeEncodeError avant même le premier test).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
CORE = HERE.parent / "triskell-core"
if CORE.exists():
    sys.path.insert(0, str(CORE))

PASS = []
FAIL = []


def check(label: str, cond: bool, detail: str = "") -> None:
    if cond:
        PASS.append(label)
        print(f"  OK  - {label}")
    else:
        FAIL.append(label)
        print(f"  FAIL- {label} {detail}")


# ---------------------------------------------------------------------------
# 1. Mapping secteur → pages métier
# ---------------------------------------------------------------------------
print("\n[1] pixelpros_pages : secteur → page de pub + démo")
from triskell_command.integrations.pixelpros_pages import (  # noqa: E402
    BASE_URL, KNOWN_SLUGS, pages_for_sector, slug_for_sector,
)

check("40 pages métier connues", len(KNOWN_SLUGS) == 40,
      f"-> {len(KNOWN_SLUGS)}")

# Secteurs RÉELS observés dans la base prospects (inventaire 2026-06-12)
cas_reconnus = {
    "coiffeuse":            "beaute",
    "Coiffeur":             "beaute",
    "barbier":              "beaute",
    "Artisanat — esthétique": "beaute",
    "institut de beauté":   "beaute",
    "onglerie":             "beaute",
    "plombier":             "plombier",
    "plombier-chauffagiste": "plombier",
    "électricien":          "electricien",
    "electricien":          "electricien",
    "menuisier":            "menuisier",
    "boulangerie":          "patisserie",
    "pâtisserie":           "patisserie",
    "fleuriste":            "fleuriste",
    "Artisanat — fleuristerie": "fleuriste",
    "paysagiste":           "paysagiste",
    "jardinier paysagiste": "paysagiste",
    "coach":                "coach",
    "coaching":             "coach",
    "coach sportif":        "coach",
    "photographe":          "photographe",
    "Artisanat — photographie": "photographe",
    "studio photo":         "photographe",
    "tatoueur":             "tatoueur",
    "salon de tatouage":    "tatoueur",
    "toilettage canin":     "animalier",
    "Artisanat — métiers du chien et du chat": "animalier",
    "vétérinaire":          "animalier",
    "massage bien-être":    "bien-etre",
    "sophrologue":          "bien-etre",
    "spa":                  "bien-etre",
    # Les 5 pages du 12/06/2026 (plus gros gisements de la base)
    "plaquiste":            "plaquiste",
    "plâtrier-plaquiste":   "plaquiste",   # via « plaquist », pas « plâtr »
    "pose de placo":        "plaquiste",
    "peintre":              "peintre",
    "peintre en bâtiment":  "peintre",
    "carreleur":            "carreleur",
    "carrelage et faïence": "carreleur",
    "maçon":                "macon",
    "maçonnerie générale":  "macon",
    "restaurant":           "restaurant",
    "pizzeria":             "restaurant",
    "crêperie":             "restaurant",
    "brasserie":            "restaurant",
    "bistrot":              "restaurant",
    "resto":                "restaurant",
    # — Les 8 métiers du 16/06 (matin) —
    "pisciniste":           "pisciniste",
    "construction de piscine": "pisciniste",
    "chambres d'hôtes":     "chambres-hotes",
    "gîte rural":           "chambres-hotes",
    "garagiste":            "garagiste",
    "garage automobile":    "garagiste",
    "carrosserie":          "garagiste",
    "ostéopathe":           "osteopathe",
    "masseur-kinésithérapeute": "osteopathe",   # paramédical → ostéo, pas bien-être
    "kinésithérapeute":     "osteopathe",
    "auto-école":           "auto-ecole",
    "école de conduite":    "auto-ecole",
    "traiteur":             "traiteur",          # a sa page depuis le 16/06
    "couvreur":             "couvreur",
    "charpentier":          "couvreur",          # charpente → couvreur
    "couvreur-zingueur":    "couvreur",
    "architecte d'intérieur": "architecte-interieur",
    "décorateur d'intérieur": "architecte-interieur",
    "home staging":         "architecte-interieur",
    # — Les 15 métiers du 16/06 (après-midi) —
    "cuisiniste":           "cuisiniste",
    "aménagement de cuisine": "cuisiniste",
    "salle de réception":   "salle-reception",
    "salle des fêtes":      "salle-reception",
    "domaine de mariage":   "salle-reception",
    "wedding planner":      "wedding-planner",
    "organisateur de mariage": "wedding-planner",
    "organisation d'événements": "wedding-planner",
    "serrurier":            "serrurier",
    "serrurier-métallier":  "serrurier",
    "métallier":            "serrurier",
    "ferronnier d'art":     "serrurier",
    "façadier":             "facadier",
    "ravalement de façade": "facadier",
    "isolation extérieure": "facadier",
    "salle de sport":       "salle-sport",
    "fitness":              "salle-sport",
    "crossfit":             "salle-sport",
    "salle de musculation": "salle-sport",
    "agent immobilier":     "agent-immobilier",
    "agence immobilière":   "agent-immobilier",
    "Immobilier":           "agent-immobilier",   # avant : tombait en générique
    "chauffagiste":         "chauffage-energies",  # plombier-chauffagiste reste plombier
    "poêle à granulés":     "chauffage-energies",
    "pompe à chaleur":      "chauffage-energies",
    "DJ":                   "dj",
    "dj":                   "dj",
    "disc-jockey":          "dj",
    "sonorisation":         "dj",
    "vitrier":              "vitrier",
    "vitrier-miroitier":    "vitrier",
    "miroitier":            "vitrier",
    "double vitrage":       "vitrier",
    "portail":              "portail-cloture",
    "clôtures et portails": "portail-cloture",
    "pergola bioclimatique": "portail-cloture",
    "caviste":              "caviste",
    "cave à vin":           "caviste",
    "marchand de vin":      "caviste",
    "diététicien":          "dieteticien",
    "nutritionniste":       "dieteticien",
    "lavage auto":          "lavage-auto",
    "lavage automobile":    "lavage-auto",         # « automobile » ne va PAS sur garage
    "detailing automobile": "lavage-auto",
    "station de lavage":    "lavage-auto",
    "food truck":           "food-truck",
    "camion pizza":         "food-truck",          # « pizza » ne va PAS sur restaurant
    "camion restaurant":    "food-truck",          # « restaurant » non plus
    "street food":          "food-truck",
}
for secteur, attendu in cas_reconnus.items():
    got = slug_for_sector(secteur)
    check(f"'{secteur}' → {attendu}", got == attendu, f"-> '{got}'")

# Secteurs qu'on ne doit PAS mapper (pas de page dédiée → générique).
# « achat » contient « chat » : le mot court ne doit matcher qu'entier.
# « restauration de meubles » ne doit PAS tomber sur la page restaurant.
cas_generiques = ["formation",
                  "restauration de meubles anciens",  # « restaur » ≠ « restaurant »
                  "plâtrier",   # métier distinct du plaquiste (Jordan 12/06)
                  "achat-revente de maisons", "", "   "]
for secteur in cas_generiques:
    got = slug_for_sector(secteur)
    check(f"'{secteur}' → générique", got == "", f"-> '{got}'")

# Les URLs produites sont toujours valides et complètes
for secteur, attendu in (("coiffeuse", "beaute"), ("formation", None)):
    page, demo = pages_for_sector(secteur)
    if attendu:
        check(f"URLs '{secteur}' ciblées",
              page == f"{BASE_URL}/{attendu}"
              and demo == f"{BASE_URL}/demo-{attendu}",
              f"-> {page} / {demo}")
    else:
        check(f"URLs '{secteur}' génériques",
              page == BASE_URL and demo == f"{BASE_URL}/demo",
              f"-> {page} / {demo}")

# Chaque slug du mapping pointe vers une page qui existe vraiment
slugs_du_mapping = set(
    s for _, s in __import__(
        "triskell_command.integrations.pixelpros_pages",
        fromlist=["_PREFIX_RULES"])._PREFIX_RULES
)
check("le mapping ne cite que des pages existantes",
      slugs_du_mapping <= set(KNOWN_SLUGS),
      f"-> inconnus : {slugs_du_mapping - set(KNOWN_SLUGS)}")

# ---------------------------------------------------------------------------
# 2. Placeholders {{page_metier}} / {{page_demo}} toujours remplis
# ---------------------------------------------------------------------------
print("\n[2] _apply_placeholders : variables pages métier")
from triskell_command.integrations.convoy_ai import (  # noqa: E402
    _apply_placeholders, text_to_email_html,
)

tpl = ("Bonjour {{name}}, votre page : {{page_metier}} et un exemple "
       "concret : {{page_demo}} (alias : {page_metier} / {page_demo})")
prospect_coiffeuse = {"raison_sociale": "De mèche avec Sandy",
                      "secteur": "coiffeuse"}
out = _apply_placeholders(tpl, prospect_coiffeuse, "Jordan")
check("{{page_metier}} rempli (coiffeuse → /beaute)",
      f"{BASE_URL}/beaute" in out, f"-> {out[:160]}")
check("{{page_demo}} rempli (coiffeuse → /demo-beaute)",
      f"{BASE_URL}/demo-beaute" in out)
check("aucun placeholder pages restant",
      "page_metier" not in out and "page_demo" not in out, f"-> {out[:160]}")
# Piège des syntaxes jumelles : {page_demo} se substituait À L'INTÉRIEUR
# de {{page_demo}} et laissait "{https://...}" dans le mail envoyé.
check("aucune accolade orpheline autour des liens",
      "{" not in out and "}" not in out, f"-> {out[:200]}")
check('href propre en HTML (pas de href="{url}")',
      'href="https://pixel-pros.fr/demo-beaute"' in _apply_placeholders(
          '<a href="{{page_demo}}">Voir</a>', prospect_coiffeuse, "Jordan"))

prospect_macon = {"raison_sociale": "Maçonnerie Le Goff", "secteur": "maçon"}
out2 = _apply_placeholders(tpl, prospect_macon, "Jordan")
check("secteur inconnu → liens génériques, jamais un trou",
      BASE_URL in out2 and f"{BASE_URL}/demo" in out2
      and "page_metier" not in out2 and "page_demo" not in out2)

prospect_vide = {"raison_sociale": "X"}
out3 = _apply_placeholders(tpl, prospect_vide, "Jordan")
check("fiche sans secteur → liens génériques quand même",
      "page_metier" not in out3 and "page_demo" not in out3)

# Garde-fou anti-placeholder du pipeline : le mail rendu ne doit pas
# être bloqué (sinon brouillon muet au lieu d'un envoi).
try:
    from triskell_command.integrations.prospect_status import (
        mail_is_safe_to_send,
    )
    safe = mail_is_safe_to_send("Sujet propre", out)
    check("le mail rendu passe le garde-fou anti-placeholder",
          bool(safe.get("ok")), f"-> {safe}")
except Exception as exc:  # module optionnel selon l'environnement
    check("garde-fou anti-placeholder importable", False, f"-> {exc}")

# ---------------------------------------------------------------------------
# 3. Le HTML survit à l'approbation (Api._resolve_draft_html)
# ---------------------------------------------------------------------------
print("\n[3] approbation : le HTML du brouillon survit")
from triskell_command.web.api import Api  # noqa: E402

STORED_BODY = "Bonjour,\n\nVoici la proposition.\n\nJordan"
STORED_HTML = '<div><p>Bonjour,</p><a href="https://pixel-pros.fr/beaute">Découvrir</a></div>'

# corps non transmis (envoi groupé) → HTML stocké conservé
fb, fh, regen = Api._resolve_draft_html(STORED_BODY, STORED_HTML, None)
check("corps absent → HTML du modèle conservé",
      fb == STORED_BODY and fh == STORED_HTML and not regen)

# corps renvoyé intact par le textarea (avec \r\n) → HTML conservé
fb, fh, regen = Api._resolve_draft_html(
    STORED_BODY, STORED_HTML, STORED_BODY.replace("\n", "\r\n"))
check("corps intact (\\r\\n du navigateur) → HTML conservé",
      fh == STORED_HTML and not regen)

# corps retouché → HTML régénéré depuis le texte final (avec son lien)
edited = STORED_BODY + "\n\nPS : un exemple : https://pixel-pros.fr/demo-beaute"
fb, fh, regen = Api._resolve_draft_html(STORED_BODY, STORED_HTML, edited)
check("corps retouché → HTML régénéré (plus l'ancien)",
      regen and fh and fh != STORED_HTML)
check("le HTML régénéré garde le lien cliquable",
      'href="https://pixel-pros.fr/demo-beaute"' in fh, f"-> {fh[:200]}")
check("le corps final est bien le texte retouché", fb == edited)

# brouillon d'avant la migration 45 (pas de HTML stocké) : pas de plantage
fb, fh, regen = Api._resolve_draft_html(STORED_BODY, "", None)
check("brouillon sans HTML → comportement inchangé (texte seul)",
      fb == STORED_BODY and fh == "" and not regen)

# ---------------------------------------------------------------------------
# 4. text_to_email_html : les URLs deviennent des liens cliquables
# ---------------------------------------------------------------------------
print("\n[4] text_to_email_html : liens cliquables")
html = text_to_email_html(
    "Bonjour,\n\nUn exemple pour votre métier : "
    "https://pixel-pros.fr/demo-beaute\n\nJordan",
    sender_name="Jordan",
    primary_url="https://pixel-pros.fr/beaute",
    primary_label="Découvrir",
)
check("URL du texte → lien cliquable",
      'href="https://pixel-pros.fr/demo-beaute"' in html)
check("bouton CTA présent", 'href="https://pixel-pros.fr/beaute"' in html)

# ---------------------------------------------------------------------------
print(f"\n=== Bilan : {len(PASS)} OK / {len(FAIL)} KO ===")
if FAIL:
    print("Échecs :")
    for f in FAIL:
        print(f"  - {f}")
    sys.exit(1)
print("Tout est bon.")
