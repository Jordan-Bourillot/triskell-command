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

# Les slugs réellement en ligne (une page <slug>.html + une page
# demo-<slug>.html chacune). Si une nouvelle page de pub naît, l'ajouter ici
# ET dans les règles de correspondance plus bas.
# (Les 8 derniers — pisciniste → architecte-interieur — datent du 16/06/2026.)
KNOWN_SLUGS = (
    "animalier", "beaute", "bien-etre", "carreleur", "coach",
    "electricien", "fleuriste", "macon", "menuisier", "patisserie",
    "paysagiste", "peintre", "photographe", "plaquiste", "plombier",
    "restaurant", "tatoueur",
    "pisciniste", "chambres-hotes", "garagiste", "osteopathe",
    "auto-ecole", "traiteur", "couvreur", "architecte-interieur",
)

# Règles « préfixe contenu dans le secteur » (ordre = priorité, premier
# match gagne). Préfixes volontairement longs pour éviter les faux amis.
_PREFIX_RULES: tuple[tuple[str, str], ...] = (
    ("plomb",      "plombier"),
    ("chauffag",   "plombier"),      # plombier-chauffagiste
    ("electric",   "electricien"),
    ("menuis",     "menuisier"),
    ("ebenist",    "menuisier"),
    # « charpent » bascule sur couvreur depuis le 16/06/2026 : la page
    # couvreur couvre charpente + toiture. Un menuisier-charpentier tombe
    # quand même sur « menuis », placé juste au-dessus.
    ("couvr",      "couvreur"),       # couvreur / couverture
    ("charpent",   "couvreur"),       # charpente / charpentier
    ("toitur",     "couvreur"),       # toiture
    ("zinguer",    "couvreur"),       # zinguerie
    ("ardois",     "couvreur"),       # ardoise = couverture
    ("piscin",     "pisciniste"),     # pisciniste / piscine
    ("plaquist",   "plaquiste"),
    ("placo",      "plaquiste"),
    # PAS de règle « plâtrier » → plaquiste : deux métiers distincts
    # (plaques sèches vs plâtre humide — rappel de Jordan, 12/06/2026).
    # Un « plâtrier-plaquiste » est couvert par « plaquist ».
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
    # Ostéo / kiné = paramédical (placé AVANT « massag »/« masseur » :
    # un « masseur-kinésithérapeute » doit tomber sur ostéo, pas bien-être).
    ("osteopath",  "osteopathe"),
    ("osteo",      "osteopathe"),
    ("kinesi",     "osteopathe"),     # kinésithérapeute
    ("kine",       "osteopathe"),     # masseur-kiné, masso-kiné
    ("reeduc",     "osteopathe"),     # rééducation (accents déjà retirés)
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
    # — Nouveaux métiers (16/06/2026) —
    # Auto-école AVANT garage (« école de conduite automobile » → auto-école).
    ("auto-ecole", "auto-ecole"),
    ("auto ecole", "auto-ecole"),
    ("ecole de conduite", "auto-ecole"),
    ("permis",     "auto-ecole"),     # permis de conduire / B / moto
    ("garag",      "garagiste"),
    ("carross",    "garagiste"),      # carrosserie
    ("mecaniq",    "garagiste"),      # mécanique auto
    ("pneu",       "garagiste"),
    ("automobile", "garagiste"),
    ("traiteur",   "traiteur"),
    ("chambre",    "chambres-hotes"), # chambre(s) d'hôtes
    ("gite",       "chambres-hotes"),
    ("hote",       "chambres-hotes"), # maison d'hôtes (restaurant capté plus haut)
    ("architecte d'interieur", "architecte-interieur"),
    ("architecte interieur",   "architecte-interieur"),
    ("decorateur", "architecte-interieur"),
    ("decoratrice", "architecte-interieur"),
    ("home staging", "architecte-interieur"),
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
