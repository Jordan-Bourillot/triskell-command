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
# (Les 8 « pisciniste → architecte-interieur » + les 15 « cuisiniste →
#  food-truck » datent du 16/06/2026 : 40 pages métier au total.)
KNOWN_SLUGS = (
    "animalier", "beaute", "bien-etre", "carreleur", "coach",
    "electricien", "fleuriste", "macon", "menuisier", "patisserie",
    "paysagiste", "peintre", "photographe", "plaquiste", "plombier",
    "restaurant", "tatoueur",
    "pisciniste", "chambres-hotes", "garagiste", "osteopathe",
    "auto-ecole", "traiteur", "couvreur", "architecte-interieur",
    "cuisiniste", "salle-reception", "wedding-planner", "serrurier",
    "facadier", "salle-sport", "agent-immobilier", "chauffage-energies",
    "dj", "vitrier", "portail-cloture", "caviste", "dieteticien",
    "lavage-auto", "food-truck",
)

# Règles « préfixe contenu dans le secteur » (ordre = priorité, premier
# match gagne). Préfixes volontairement longs pour éviter les faux amis.
_PREFIX_RULES: tuple[tuple[str, str], ...] = (
    ("plomb",      "plombier"),       # plombier-chauffagiste : « plomb » d'abord
    # Chauffage nouvelle génération (poêle granulés, pompe à chaleur) a sa page
    # depuis le 16/06/2026. Le plombier-chauffagiste reste sur plombier (capté
    # par « plomb » juste au-dessus) ; le reste du chauffage va sur la page dédiée.
    ("poele",      "chauffage-energies"),   # poêle à granulés / à bois
    ("granul",     "chauffage-energies"),   # granulés / pellets
    ("pellet",     "chauffage-energies"),
    ("pompe a chaleur", "chauffage-energies"),
    ("aerotherm",  "chauffage-energies"),
    ("geotherm",   "chauffage-energies"),
    ("climatis",   "chauffage-energies"),    # clim réversible = PAC air/air
    ("photovolta", "chauffage-energies"),
    ("panneau solaire", "chauffage-energies"),
    ("energies renouvelab", "chauffage-energies"),
    ("chauffag",   "chauffage-energies"),    # chauffagiste / chauffage
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
    # Food truck AVANT restaurant : « camion restaurant », « street food »,
    # « camion pizza »… doivent partir sur la page food truck, pas restaurant.
    ("food truck", "food-truck"),
    ("food-truck", "food-truck"),
    ("foodtruck",  "food-truck"),
    ("food trailer", "food-truck"),
    ("camion pizza", "food-truck"),
    ("camion a pizza", "food-truck"),
    ("camion restaurant", "food-truck"),
    ("camion a burger", "food-truck"),
    ("camion-restaurant", "food-truck"),
    ("street food", "food-truck"),
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
    # Lavage auto / detailing AVANT garage : « lavage automobile » contient
    # « automobile » (qui partirait sinon sur garagiste).
    ("lavage auto", "lavage-auto"),
    ("lavage automobile", "lavage-auto"),
    ("lavage-auto", "lavage-auto"),
    ("detailing",  "lavage-auto"),
    ("detailer",   "lavage-auto"),
    ("car wash",   "lavage-auto"),
    ("nettoyage auto", "lavage-auto"),
    ("nettoyage automobile", "lavage-auto"),
    ("station de lavage", "lavage-auto"),
    ("lustrage",   "lavage-auto"),
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
    # — 15 nouveaux métiers (16/06/2026) —
    ("cuisinist",  "cuisiniste"),     # cuisiniste (PAS « cuisine » seul : trop large)
    ("amenagement de cuisine", "cuisiniste"),
    ("cuisine equip", "cuisiniste"),
    ("cuisine amenag", "cuisiniste"),
    # Serrurier AVANT portail (un serrurier-métallier qui pose des portails
    # reste serrurier).
    ("serrur",     "serrurier"),      # serrurier / serrurerie
    ("metall",     "serrurier"),      # métallier / métallerie / métallique
    ("ferronn",    "serrurier"),      # ferronnier / ferronnerie d'art
    ("facad",      "facadier"),       # façadier / façade
    ("ravalement", "facadier"),
    ("crepi",      "facadier"),       # crépi
    ("enduit",     "facadier"),       # enduit de façade
    ("isolation ext", "facadier"),    # ITE — isolation extérieure
    ("vitrier",    "vitrier"),
    ("vitrerie",   "vitrier"),
    ("vitrag",     "vitrier"),        # vitrage / survitrage / double vitrage
    ("miroit",     "vitrier"),        # miroitier / miroiterie
    ("portail",    "portail-cloture"),
    ("cloture",    "portail-cloture"),
    ("pergola",    "portail-cloture"),
    ("brise-vue",  "portail-cloture"),
    ("brise vue",  "portail-cloture"),
    ("portillon",  "portail-cloture"),
    ("store banne", "portail-cloture"),
    # Salle de sport ≠ salle de réception : on n'utilise JAMAIS « salle » seul.
    ("salle de sport", "salle-sport"),
    ("salle de fitness", "salle-sport"),
    ("fitness",    "salle-sport"),
    ("crossfit",   "salle-sport"),
    ("cross-fit",  "salle-sport"),
    ("musculation", "salle-sport"),
    ("club de sport", "salle-sport"),
    ("salle de reception", "salle-reception"),
    ("salle des fetes", "salle-reception"),
    ("salle de fete", "salle-reception"),
    ("domaine de mariage", "salle-reception"),
    ("domaine de reception", "salle-reception"),
    ("lieu de reception", "salle-reception"),
    ("location de salle", "salle-reception"),
    # Wedding planner = l'organisateur (≠ le lieu).
    ("wedding",    "wedding-planner"),
    ("organisateur de mariage", "wedding-planner"),
    ("organisation de mariage", "wedding-planner"),
    # « événement » : on couvre apostrophe droite, apostrophe avalée par le
    # nettoyage (d'→d), et espace — pour ne pas dépendre de la ponctuation.
    ("organisateur d'evenement", "wedding-planner"),
    ("organisation d'evenement", "wedding-planner"),
    ("organisateur d evenement", "wedding-planner"),
    ("organisation d evenement", "wedding-planner"),
    ("organisateur devenement", "wedding-planner"),
    ("organisation devenement", "wedding-planner"),
    ("agent immobilier", "agent-immobilier"),
    ("agence immobiliere", "agent-immobilier"),
    ("mandataire immo", "agent-immobilier"),
    ("negociateur immo", "agent-immobilier"),
    ("immobilier", "agent-immobilier"),
    ("immobiliere", "agent-immobilier"),
    # Caviste : surtout PAS le bout « vin » (vintage, vinaigre, ravin…).
    ("caviste",    "caviste"),
    ("cave a vin", "caviste"),
    ("vins et spiritueux", "caviste"),
    ("marchand de vin", "caviste"),
    ("oenolog",    "caviste"),         # œnologue / œnothèque
    ("dieteti",    "dieteticien"),     # diététicien / diététique
    ("nutrition",  "dieteticien"),     # nutritionniste
    # DJ : prefixes longs seulement (« dj » seul = règle mot entier plus bas,
    # sinon « adjoint » matcherait).
    ("disc jockey", "dj"),
    ("disc-jockey", "dj"),
    ("deejay",     "dj"),
    ("sonorisation", "dj"),
    ("animation de soiree", "dj"),
    ("animation musicale", "dj"),
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
    "dj":     "dj",          # « dj » seul (sous-chaîne de « adjoint » sinon)
    "deejay": "dj",
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
