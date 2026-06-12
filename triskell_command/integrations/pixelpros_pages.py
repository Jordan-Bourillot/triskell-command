# -*- coding: utf-8 -*-
"""Pages métier Pixel Pros : secteur du prospect → page de pub ciblée.

pixel-pros.fr a 17 pages de pub métier, chacune avec sa page démo
(« voilà ce que donnerait VOTRE site ») :

    animalier, beaute, bien-etre, carreleur, coach, electricien,
    fleuriste, macon, menuisier, patisserie, paysagiste, peintre,
    photographe, plaquiste, plombier, restaurant, tatoueur

(Les 5 du bâtiment/restauration datent du 12/06/2026 — taillées sur
les plus gros gisements de la base prospects : 37 plaquistes,
26 peintres, 24 carreleurs, 22 maçons, 22 restaurants.)

Ce module fait UNE chose : deviner, depuis le secteur en texte libre
d'une fiche prospect (« coiffeuse », « boulangerie », « Artisanat —
esthétique »...), laquelle de ces 12 pages lui parlera le plus.

Branché dans les modèles de prospection via les variables
{{page_metier}} / {{page_demo}} (cf. convoy_ai._apply_placeholders).
Secteur inconnu → accueil + démo générique : le lien du mail n'est
JAMAIS cassé, juste moins ciblé. On ne devine que ce qui est sûr —
un maçon ne doit pas recevoir « votre site de pâtisserie ».
"""
from __future__ import annotations

import re
import unicodedata

BASE_URL = "https://pixel-pros.fr"

# Les 12 slugs réellement en ligne (une page <slug>.html + une page
# demo-<slug>.html chacune). Si une 13e page de pub naît, l'ajouter ici
# ET dans les règles de correspondance plus bas.
KNOWN_SLUGS = (
    "animalier", "beaute", "bien-etre", "carreleur", "coach",
    "electricien", "fleuriste", "macon", "menuisier", "patisserie",
    "paysagiste", "peintre", "photographe", "plaquiste", "plombier",
    "restaurant", "tatoueur",
)

# Règles « préfixe contenu dans le secteur » (ordre = priorité, premier
# match gagne). Préfixes volontairement longs pour éviter les faux amis.
_PREFIX_RULES: tuple[tuple[str, str], ...] = (
    ("plomb",      "plombier"),
    ("chauffag",   "plombier"),      # plombier-chauffagiste
    ("electric",   "electricien"),
    ("menuis",     "menuisier"),
    ("ebenist",    "menuisier"),
    ("charpent",   "menuisier"),     # métier du bois le plus proche
    ("plaquist",   "plaquiste"),
    ("platr",      "plaquiste"),     # plâtrier / plâtrerie
    ("placo",      "plaquiste"),
    ("peintr",     "peintre"),       # peintre(s) en bâtiment
    ("carrel",     "carreleur"),     # carreleur / carrelage
    ("macon",      "macon"),         # maçon / maçonnerie (sans accents)
    ("paysag",     "paysagiste"),
    ("jardin",     "paysagiste"),
    ("fleurist",   "fleuriste"),
    ("patiss",     "patisserie"),
    ("boulang",    "patisserie"),    # commerce de bouche le plus proche
    ("chocolat",   "patisserie"),
    ("confis",     "patisserie"),    # confiserie / confiseur
    ("restaurant", "restaurant"),
    ("pizzer",     "restaurant"),    # pizzeria / pizzeriste
    ("creper",     "restaurant"),    # crêperie / crêpier
    ("brasserie",  "restaurant"),
    ("bistro",     "restaurant"),    # bistro(t)
    ("coiff",      "beaute"),
    ("barbier",    "beaute"),
    ("beaut",      "beaute"),        # beauté / institut de beauté
    ("esthet",     "beaute"),        # esthéticienne / esthétique
    ("ongler",     "beaute"),        # onglerie
    ("manucur",    "beaute"),
    ("maquill",    "beaute"),
    ("massag",     "bien-etre"),
    ("masseur",    "bien-etre"),
    ("masseus",    "bien-etre"),
    ("sophro",     "bien-etre"),
    ("naturopath", "bien-etre"),
    ("reflexo",    "bien-etre"),
    ("hypnoth",    "bien-etre"),
    ("coach",      "coach"),         # couvre aussi « coaching »
    ("photograph", "photographe"),
    ("tatou",      "tatoueur"),
    ("tattoo",     "tatoueur"),
    ("piercing",   "tatoueur"),
    ("toilettag",  "animalier"),     # toilettage canin
    ("toiletteu",  "animalier"),
    ("canin",      "animalier"),
    ("veterin",    "animalier"),
    ("animal",     "animalier"),
)

# Mots trop courts ou trop ambigus pour la sous-chaîne (« chat » est
# dans « achat ») : on ne les accepte que comme MOT ENTIER du secteur.
_WORD_RULES: dict[str, str] = {
    "spa":    "bien-etre",
    "yoga":   "bien-etre",
    "chien":  "animalier",
    "chat":   "animalier",
    "ongle":  "beaute",
    "ongles": "beaute",
    "photo":  "photographe",
    "resto":  "restaurant",
}


def _normalize(text: str) -> str:
    """minuscules + accents retirés : « Esthétique » → « esthetique »."""
    if not text:
        return ""
    flat = unicodedata.normalize("NFKD", text)
    flat = flat.encode("ascii", "ignore").decode("ascii")
    return flat.lower()


def slug_for_sector(secteur: str) -> str:
    """Renvoie le slug de la page métier qui correspond au secteur,
    ou "" si on n'est sûr de rien (le mail gardera le lien générique)."""
    s = _normalize(secteur)
    if not s:
        return ""
    for prefix, slug in _PREFIX_RULES:
        if prefix in s:
            return slug
    words = set(re.findall(r"[a-z]+", s))
    for word, slug in _WORD_RULES.items():
        if word in words:
            return slug
    return ""


def pages_for_sector(secteur: str) -> tuple[str, str]:
    """(URL page de pub, URL page démo) pour un secteur en texte libre.

    Toujours deux URLs valides : pages métier si le secteur est reconnu,
    sinon accueil + démo générique (/demo)."""
    slug = slug_for_sector(secteur)
    if slug and slug in KNOWN_SLUGS:
        return (f"{BASE_URL}/{slug}", f"{BASE_URL}/demo-{slug}")
    return (BASE_URL, f"{BASE_URL}/demo")
