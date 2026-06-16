"""Aperçu de site personnalisé pour la prospection.

Idée (demande Jordan, 14/06/2026) : dans le mail de prospection, montrer au
prospect À QUOI POURRAIT RESSEMBLER SON SITE. C'est ce qui fait répondre quand
on vend des sites — surtout aux commerces qui n'en ont PAS.

Refonte 14/06/2026 (demande Jordan « des aperçus qui font vraiment très pros ») :
on ne fabrique plus une maquette « maison », on montre LE VRAI SITE DE DÉMO
Pixel Pros du métier (pixel-pros.fr/demo-xxx), personnalisé au nom et à la
ville du prospect. C'est exactement le produit vendu → plus crédible, plus
beau, et honnête. On capture la première vue (en-tête + hero), en mode
« embed » (sans le bandeau démo). Repli automatique sur l'ancienne maquette
auto-contenue pour les métiers SANS page de démo (ou si le rendu live échoue).

Rendu via Playwright (déjà installé côté serveur — utilisé par Argus). Sans
Playwright / sans réseau : renvoie None (le mail part alors sans aperçu).

Usage :
    from triskell_command.integrations import apercu_site
    png = apercu_site.render_preview_png("Aux Fleurs des Abers", "fleuriste", "Lannilis")
"""
from __future__ import annotations

import base64
import hashlib
import html as _html
import logging
import os
import re
import threading
import unicodedata

logger = logging.getLogger(__name__)


def _in_thread(fn, *args):
    """Exécute fn dans un thread dédié et renvoie son résultat (None si échec).

    sync_playwright() REFUSE de démarrer quand une boucle asyncio tourne dans
    le thread courant — c'est le cas du serveur (uvicorn). Un thread neuf n'a
    pas de boucle active → le rendu fonctionne partout (serveur comme desktop).
    """
    box: dict = {}

    def _run():
        try:
            box["v"] = fn(*args)
        except Exception as exc:  # pragma: no cover - filet
            box["e"] = exc

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join()
    if "e" in box:
        logger.warning("apercu_site : rendu (thread) échoué : %s", box["e"])
        return None
    return box.get("v")


def _strip_accents(s: str) -> str:
    s = ((s or "").replace("œ", "oe").replace("Œ", "OE")
                  .replace("æ", "ae").replace("Æ", "AE"))
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def clean_business_name(name: str) -> str:
    """Nettoie un nom d'entreprise pour l'afficher dans un mail / un aperçu.

    Retire une parenthèse FINALE (nom du gérant, sigle, note) qui, dans une
    prose de prospection, sonne comme une « variable mal remplie » :
        "Institut Embellia (Deguilhem Delphine)" -> "Institut Embellia"
        "Mr Moustache ( uniquement SANS RENDEZ - VOUS)" -> "Mr Moustache"
    Garde le nom tel quel si le retrait le viderait (nom = juste « (...) »).
    """
    n = (name or "").strip()
    stripped = re.sub(r"\s*\([^()]*\)\s*$", "", n).strip()
    return stripped or n


# ===========================================================================
#  PARTIE 1 — Aperçu = vrai site de démo Pixel Pros personnalisé
# ===========================================================================

# Base du site Pixel Pros (les pages de démo y vivent). Surchargée par env si
# besoin (tests, préprod).
def _base_url() -> str:
    return (os.environ.get("APERCU_DEMO_BASE_URL")
            or os.environ.get("PIXEL_PROS_BASE_URL")
            or "https://pixel-pros.fr").rstrip("/")


# métier (texte libre, sans accent, minuscules) → slug de la page de démo.
# Ordre = priorité (1er fragment trouvé gagne). On ne mappe QUE des métiers
# dont la démo correspond vraiment ; le reste retombe sur la maquette.
_DEMO_MAP: dict[str, str] = {
    # — Artisans du bâtiment —
    "plomb": "demo-plombier",
    # Chauffage nouvelle génération a sa démo (16/06/2026). Le plombier-
    # chauffagiste reste sur plombier (capté par « plomb » au-dessus).
    "poele": "demo-chauffage-energies", "granul": "demo-chauffage-energies",
    "pellet": "demo-chauffage-energies", "pompe a chaleur": "demo-chauffage-energies",
    "aerotherm": "demo-chauffage-energies", "geotherm": "demo-chauffage-energies",
    "climatis": "demo-chauffage-energies", "photovolta": "demo-chauffage-energies",
    "panneau solaire": "demo-chauffage-energies",
    "energies renouvelab": "demo-chauffage-energies",
    "chauffag": "demo-chauffage-energies",
    "electric": "demo-electricien",
    "peintr": "demo-peintre",
    "carrel": "demo-carreleur", "faienc": "demo-carreleur",
    "macon": "demo-macon", "maconn": "demo-macon",
    "menuis": "demo-menuisier", "ebenist": "demo-menuisier",
    "agenc": "demo-menuisier",
    # charpente / toiture → couvreur (16/06/2026)
    "couvr": "demo-couvreur", "charpent": "demo-couvreur",
    "toitur": "demo-couvreur", "zinguer": "demo-couvreur",
    "ardois": "demo-couvreur",
    "piscin": "demo-pisciniste",
    "plaquist": "demo-plaquiste", "placo": "demo-plaquiste",
    "platr": "demo-plaquiste", "plaqu": "demo-plaquiste",
    "paysag": "demo-paysagiste", "jardin": "demo-paysagiste",
    "elagag": "demo-paysagiste", "espaces vert": "demo-paysagiste",
    # — Commerces de bouche (fleur AVANT animal) —
    "fleur": "demo-fleuriste",
    "patiss": "demo-patisserie", "boulang": "demo-patisserie",
    "chocolat": "demo-patisserie", "confis": "demo-patisserie",
    "cake": "demo-patisserie",
    # Food truck AVANT restaurant (« camion pizza/restaurant », « street food »).
    "food truck": "demo-food-truck", "food-truck": "demo-food-truck",
    "foodtruck": "demo-food-truck", "food trailer": "demo-food-truck",
    "camion pizza": "demo-food-truck", "camion a pizza": "demo-food-truck",
    "camion restaurant": "demo-food-truck", "camion a burger": "demo-food-truck",
    "street food": "demo-food-truck",
    # Microbrasserie AVANT restaurant (« microbrasserie » contient « brasserie »)
    "microbrasserie": "demo-microbrasserie", "micro-brasserie": "demo-microbrasserie",
    "brasserie artisanale": "demo-microbrasserie", "brasseur": "demo-microbrasserie",
    "biere artisanale": "demo-microbrasserie",
    "restaur": "demo-restaurant", "pizz": "demo-restaurant",
    "brasser": "demo-restaurant", "creper": "demo-restaurant",
    "bistro": "demo-restaurant",
    "traiteur": "demo-traiteur",  # a sa propre démo depuis le 16/06/2026
    "snack": "demo-restaurant", "kebab": "demo-restaurant",
    # — Beauté / bien-être —
    "esthet": "demo-beaute", "beaut": "demo-beaute", "ongle": "demo-beaute",
    "manucur": "demo-beaute", "maquill": "demo-beaute",
    "institut": "demo-beaute", "cils": "demo-beaute",
    # Coiffure : pas de démo dédié → univers beauté/salon (le plus proche).
    # ~130 fiches concernées (coiffeur / coiffeuse / barbier) — premier
    # métier prospecté sans démo (constaté le 15/06/2026).
    "coiff": "demo-beaute", "barbier": "demo-beaute", "barber": "demo-beaute",
    # ostéo / kiné = paramédical, AVANT massage (masseur-kiné → ostéo)
    "osteopath": "demo-osteopathe", "osteo": "demo-osteopathe",
    "kinesi": "demo-osteopathe", "kine": "demo-osteopathe",
    "reeduc": "demo-osteopathe",
    "massag": "demo-bien-etre", "spa": "demo-bien-etre",
    "bien-etre": "demo-bien-etre", "bien etre": "demo-bien-etre",
    "sophro": "demo-bien-etre", "naturopath": "demo-bien-etre",
    "reflexo": "demo-bien-etre", "yoga": "demo-bien-etre",
    "hypno": "demo-bien-etre",
    # — Services —
    "coach": "demo-coach",
    "photograph": "demo-photographe", "videast": "demo-photographe",
    "tatou": "demo-tatoueur", "tattoo": "demo-tatoueur",
    "piercing": "demo-tatoueur",
    "toilett": "demo-animalier", "canin": "demo-animalier",
    "pension": "demo-animalier", "dressage": "demo-animalier",
    "educateur canin": "demo-animalier", "animal": "demo-animalier",
    "chien": "demo-animalier",
    # — Nouveaux métiers (16/06/2026) — (auto-école AVANT garage)
    "auto-ecole": "demo-auto-ecole", "auto ecole": "demo-auto-ecole",
    "ecole de conduite": "demo-auto-ecole", "permis": "demo-auto-ecole",
    # Lavage auto / detailing AVANT garage (« lavage automobile » contient
    # « automobile »).
    "lavage auto": "demo-lavage-auto", "lavage automobile": "demo-lavage-auto",
    "detailing": "demo-lavage-auto", "car wash": "demo-lavage-auto",
    "nettoyage auto": "demo-lavage-auto", "station de lavage": "demo-lavage-auto",
    "lustrage": "demo-lavage-auto",
    "garag": "demo-garagiste", "carross": "demo-garagiste",
    "mecaniq": "demo-garagiste", "pneu": "demo-garagiste",
    "automobile": "demo-garagiste",
    "chambre": "demo-chambres-hotes", "gite": "demo-chambres-hotes",
    "hote": "demo-chambres-hotes",  # « restaur » est capté plus haut
    "architecte d'interieur": "demo-architecte-interieur",
    "architecte interieur": "demo-architecte-interieur",
    # tapissier AVANT « decorateur » (tapissier-décorateur → tapissier)
    "tapiss": "demo-tapissier",
    "decorateur": "demo-architecte-interieur",
    "decoratrice": "demo-architecte-interieur",
    "home staging": "demo-architecte-interieur",
    # — 15 nouveaux métiers (16/06/2026) —
    "cuisinist": "demo-cuisiniste", "amenagement de cuisine": "demo-cuisiniste",
    "cuisine equip": "demo-cuisiniste", "cuisine amenag": "demo-cuisiniste",
    # serrurier AVANT portail
    "serrur": "demo-serrurier", "metall": "demo-serrurier", "ferronn": "demo-serrurier",
    "facad": "demo-facadier", "ravalement": "demo-facadier", "crepi": "demo-facadier",
    "enduit": "demo-facadier", "isolation ext": "demo-facadier",
    "vitrier": "demo-vitrier", "vitrerie": "demo-vitrier", "vitrag": "demo-vitrier",
    "miroit": "demo-vitrier",
    "portail": "demo-portail-cloture", "cloture": "demo-portail-cloture",
    "pergola": "demo-portail-cloture", "brise-vue": "demo-portail-cloture",
    "brise vue": "demo-portail-cloture", "portillon": "demo-portail-cloture",
    "store banne": "demo-portail-cloture",
    "salle de sport": "demo-salle-sport", "salle de fitness": "demo-salle-sport",
    "fitness": "demo-salle-sport", "crossfit": "demo-salle-sport",
    "cross-fit": "demo-salle-sport", "musculation": "demo-salle-sport",
    "club de sport": "demo-salle-sport",
    "salle de reception": "demo-salle-reception", "salle des fetes": "demo-salle-reception",
    "salle de fete": "demo-salle-reception", "domaine de mariage": "demo-salle-reception",
    "domaine de reception": "demo-salle-reception", "lieu de reception": "demo-salle-reception",
    "location de salle": "demo-salle-reception",
    "wedding": "demo-wedding-planner",
    "organisateur de mariage": "demo-wedding-planner",
    "organisation de mariage": "demo-wedding-planner",
    "organisateur d'evenement": "demo-wedding-planner",
    "organisation d'evenement": "demo-wedding-planner",
    "organisateur d evenement": "demo-wedding-planner",
    "organisation d evenement": "demo-wedding-planner",
    "organisateur devenement": "demo-wedding-planner",
    "organisation devenement": "demo-wedding-planner",
    # diagnostiqueur AVANT agent immobilier (« diagnostic immobilier »)
    "diagnostiqueur": "demo-diagnostiqueur",
    "diagnostics immobiliers": "demo-diagnostiqueur",
    "diagnostic immobilier": "demo-diagnostiqueur",
    "diagnostic immo": "demo-diagnostiqueur",
    "agent immobilier": "demo-agent-immobilier",
    "agence immobiliere": "demo-agent-immobilier",
    "mandataire immo": "demo-agent-immobilier",
    "negociateur immo": "demo-agent-immobilier",
    "immobilier": "demo-agent-immobilier", "immobiliere": "demo-agent-immobilier",
    "caviste": "demo-caviste", "cave a vin": "demo-caviste",
    "vins et spiritueux": "demo-caviste", "marchand de vin": "demo-caviste",
    "oenolog": "demo-caviste",
    "dieteti": "demo-dieteticien", "nutrition": "demo-dieteticien",
    "disc jockey": "demo-dj", "disc-jockey": "demo-dj", "deejay": "demo-dj",
    "sonorisation": "demo-dj", "animation de soiree": "demo-dj",
    "animation musicale": "demo-dj",
    # — 8 métiers de plus (16/06/2026) —
    "demenag": "demo-demenageur", "garde-meuble": "demo-demenageur",
    "boucher": "demo-boucher", "boucherie": "demo-boucher", "charcuti": "demo-boucher",
    "bijou": "demo-bijoutier", "joaill": "demo-bijoutier", "orfevr": "demo-bijoutier",
    "horloger": "demo-bijoutier",
    "domoti": "demo-domoticien", "alarme": "demo-domoticien",
    "videosurveillance": "demo-domoticien", "video surveillance": "demo-domoticien",
    "videoprotection": "demo-domoticien", "maison connectee": "demo-domoticien",
    "veterin": "demo-veterinaire",   # vétérinaire (n'avait pas de démo avant)
    "constructeur de maison": "demo-constructeur", "constructeur maison": "demo-constructeur",
    "maitre d'oeuvre": "demo-constructeur", "maitre d oeuvre": "demo-constructeur",
    "maison individuelle": "demo-constructeur", "constructeur": "demo-constructeur",
    "opticien": "demo-opticien", "optique": "demo-opticien",
    "lunetier": "demo-opticien", "lunetterie": "demo-opticien",
    # — 6 métiers de plus (16/06/2026) —
    "fromag": "demo-fromager", "cremerie": "demo-fromager", "cremier": "demo-fromager",
    "poissonn": "demo-poissonnier", "maree": "demo-poissonnier",
    "fruits de mer": "demo-poissonnier", "ecailler": "demo-poissonnier",
    "torref": "demo-torrefacteur", "brulerie": "demo-torrefacteur",
    "cafe de specialite": "demo-torrefacteur", "barista": "demo-torrefacteur",
    "homme toutes mains": "demo-multiservices", "toutes mains": "demo-multiservices",
    "multiservice": "demo-multiservices", "petits travaux": "demo-multiservices",
    "factotum": "demo-multiservices", "bricol": "demo-multiservices",
}

# Ville fictive utilisée dans CHAQUE démo (à remplacer par celle du prospect).
_DEMO_CITY: dict[str, str] = {
    "demo-fleuriste": "Lyon", "demo-plombier": "Lyon",
    "demo-patisserie": "Lyon", "demo-electricien": "Lyon",
    "demo-menuisier": "Lyon", "demo-paysagiste": "Lyon",
    "demo-photographe": "Lyon", "demo-tatoueur": "Lyon",
    "demo-beaute": "Lyon", "demo-bien-etre": "Lyon",
    "demo-animalier": "Lyon", "demo-coach": "Lyon",
    "demo-restaurant": "Lorient", "demo-plaquiste": "Vannes",
    "demo-macon": "Quimper", "demo-peintre": "Angers",
    "demo-carreleur": "La Rochelle",
    # — Nouveaux métiers (villes fictives des démos) —
    "demo-pisciniste": "Aix-en-Provence",
    "demo-chambres-hotes": "Lourmarin",
    "demo-garagiste": "Nantes",
    "demo-osteopathe": "Montpellier",
    "demo-auto-ecole": "Rennes",
    "demo-traiteur": "Toulouse",
    "demo-couvreur": "Angers",
    "demo-architecte-interieur": "Bordeaux",
    # — 15 nouveaux métiers (villes exactes telles qu'écrites dans le hero) —
    "demo-cuisiniste": "Annecy",
    "demo-salle-reception": "Saint-Émilion",
    "demo-wedding-planner": "Aix-en-Provence",
    "demo-serrurier": "Marseille",
    "demo-facadier": "Nîmes",
    "demo-salle-sport": "Paris",
    "demo-agent-immobilier": "Nantes",
    "demo-chauffage-energies": "Grenoble",
    "demo-dj": "Strasbourg",
    "demo-vitrier": "Tours",
    "demo-portail-cloture": "Perpignan",
    "demo-caviste": "Bordeaux",
    "demo-dieteticien": "Lyon",
    "demo-lavage-auto": "Lille",
    "demo-food-truck": "Marseille",
    # — 8 métiers de plus —
    "demo-demenageur": "Lyon",
    "demo-boucher": "Lyon",
    "demo-bijoutier": "Bordeaux",
    "demo-domoticien": "Nantes",
    "demo-diagnostiqueur": "Tours",
    "demo-veterinaire": "Toulouse",
    "demo-constructeur": "Bordeaux",
    "demo-opticien": "Lille",
    # — 6 métiers de plus —
    "demo-fromager": "Clermont-Ferrand",
    "demo-poissonnier": "Lorient",
    "demo-torrefacteur": "Lyon",
    "demo-microbrasserie": "Strasbourg",
    "demo-tapissier": "Nantes",
    "demo-multiservices": "Montpellier",
}

# Libellé métier propre affiché dans l'en-tête / le bandeau (cohérent quel que
# soit le texte brut reçu : « Commerce de détail de fleurs » → « Fleuriste »).
_DEMO_LABEL: dict[str, str] = {
    "demo-fleuriste": "Fleuriste", "demo-plombier": "Plombier",
    "demo-patisserie": "Pâtisserie", "demo-electricien": "Électricien",
    "demo-menuisier": "Menuisier", "demo-paysagiste": "Paysagiste",
    "demo-photographe": "Photographe", "demo-tatoueur": "Tatoueur",
    "demo-beaute": "Institut de beauté", "demo-bien-etre": "Bien-être",
    "demo-animalier": "Toilettage", "demo-coach": "Coach sportif",
    "demo-restaurant": "Restaurant", "demo-plaquiste": "Plaquiste",
    "demo-macon": "Maçonnerie", "demo-peintre": "Peintre",
    "demo-carreleur": "Carreleur",
    # — Nouveaux métiers (libellés propres affichés dans l'aperçu) —
    "demo-pisciniste": "Pisciniste",
    "demo-chambres-hotes": "Chambres d'hôtes",
    "demo-garagiste": "Garage",
    "demo-osteopathe": "Ostéo & kiné",
    "demo-auto-ecole": "Auto-école",
    "demo-traiteur": "Traiteur",
    "demo-couvreur": "Couvreur",
    "demo-architecte-interieur": "Architecte d'intérieur",
    # — 15 nouveaux métiers —
    "demo-cuisiniste": "Cuisiniste",
    "demo-salle-reception": "Salle de réception",
    "demo-wedding-planner": "Wedding planner",
    "demo-serrurier": "Serrurier-métallier",
    "demo-facadier": "Façadier",
    "demo-salle-sport": "Salle de sport",
    "demo-agent-immobilier": "Agent immobilier",
    "demo-chauffage-energies": "Chauffage & énergies",
    "demo-dj": "DJ & animation",
    "demo-vitrier": "Vitrier-miroitier",
    "demo-portail-cloture": "Portails & clôtures",
    "demo-caviste": "Caviste",
    "demo-dieteticien": "Diététicien",
    "demo-lavage-auto": "Lavage auto & detailing",
    "demo-food-truck": "Food truck",
    # — 8 métiers de plus —
    "demo-demenageur": "Déménageur",
    "demo-boucher": "Boucher-charcutier",
    "demo-bijoutier": "Bijoutier-horloger",
    "demo-domoticien": "Domotique & sécurité",
    "demo-diagnostiqueur": "Diagnostics immobiliers",
    "demo-veterinaire": "Clinique vétérinaire",
    "demo-constructeur": "Constructeur de maisons",
    "demo-opticien": "Opticien",
    # — 6 métiers de plus —
    "demo-fromager": "Fromager-affineur",
    "demo-poissonnier": "Poissonnier",
    "demo-torrefacteur": "Torréfacteur",
    "demo-microbrasserie": "Microbrasserie",
    "demo-tapissier": "Tapissier-décorateur",
    "demo-multiservices": "Homme toutes mains",
}


def _demo_slug_for(metier: str) -> str | None:
    key = _strip_accents((metier or "").lower())
    for frag, slug in _DEMO_MAP.items():
        if frag in key:
            return slug
    return None


# CSS injecté : on masque le décor « démo » et on rend l'en-tête + le bandeau
# parfaitement lisibles sur n'importe quelle photo.
_HIDE_CSS = """
  .demo-bar,.fcall,.fsoc,.annot,.annot-after-hero,.cust-hero-scroll{display:none!important;}
  .cust-eyebrow{background:rgba(0,0,0,.30)!important;padding:7px 16px!important;
    border-radius:999px!important;text-shadow:0 1px 6px rgba(0,0,0,.5)!important;
    color:#fff!important;}
  .cust-logo-text strong,.cust-logo-text em{text-shadow:0 1px 8px rgba(0,0,0,.35)!important;}
"""

# Attend que la photo de fond du hero soit chargée (sinon capture sans photo).
_WAIT_HERO_BG_JS = r"""async () => {
  const el = document.querySelector('.cust-hero-bg');
  if (!el) return;
  const m = getComputedStyle(el).backgroundImage.match(/url\("?(.*?)"?\)/);
  if (!m) return;
  await new Promise(res => { const im = new Image();
    im.onload = res; im.onerror = res; im.src = m[1]; setTimeout(res, 8000); });
}"""

# Personnalisation du hero : ville réelle + nom + métier·ville du prospect.
_PERSONALIZE_JS = r"""(args) => {
  const nom = args[0], label = args[1], ville = args[2], cityDemo = args[3];
  if (cityDemo) {
    const esc = cityDemo.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const rx = new RegExp(esc, 'gi');
    // Préposition + ville fictive (« à Quimper », « de Quimper »…) : sert à
    // retirer proprement la mention quand on ne connaît PAS la ville du
    // prospect (sinon on afficherait une ville au hasard).
    const rxPrep = new RegExp('\\s*(?:à|a|de|sur|en)\\s+' + esc, 'gi');
    const hero = document.querySelector('.cust-hero');
    if (hero) {
      const walk = n => { for (const c of n.childNodes) {
        if (c.nodeType === 3) {
          c.nodeValue = ville
            ? c.nodeValue.replace(rx, ville)
            : c.nodeValue.replace(rxPrep, '').replace(rx, '');
        } else walk(c);
      }};
      walk(hero);
    }
  }
  const set = (s, t) => { const e = document.querySelector(s); if (e) e.textContent = t; };
  if (nom) set('.cust-logo-text strong', nom);
  const sub = [label, ville].filter(Boolean).join(' · ');
  if (sub) set('.cust-logo-text em', sub);
  const eb = '★ ' + [(label || '').toUpperCase(),
                          (ville || '').toUpperCase()].filter(Boolean).join(' · ');
  if (eb.trim() !== '★') set('.cust-eyebrow', eb);
}"""


# Traceurs / pubs externes : inutiles à l'aperçu et parfois lents → bloqués
# (rendu plus rapide et plus fiable). On NE bloque PAS le JS du site lui-même
# (animations d'apparition du hero) ni les photos/polices.
_BLOCK_FRAGMENTS = (
    "googlesyndication", "googleadservices", "google-analytics",
    "googletagmanager", "doubleclick", "facebook.net", "connect.facebook",
    "fbevents", "/google-ads.js", "meta-pixel", "pp-analytics",
)


def _render_demo_png(nom: str, metier: str, ville: str, slug: str) -> bytes | None:
    """Capture la 1re vue du vrai site de démo du métier, personnalisée."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        logger.info("apercu_site : Playwright absent — aperçu sauté.")
        return None
    url = f"{_base_url()}/{slug}?embed"
    city_demo = _DEMO_CITY.get(slug, "")
    label = _DEMO_LABEL.get(slug, (metier or "").strip())
    png = None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page(
                    viewport={"width": 1280, "height": 760}, device_scale_factor=2)

                def _route(route):
                    u = route.request.url
                    if any(s in u for s in _BLOCK_FRAGMENTS):
                        route.abort()
                    else:
                        route.continue_()
                page.route("**/*", _route)

                page.goto(url, wait_until="domcontentloaded", timeout=35000)
                page.wait_for_selector(".cust-hero", timeout=15000)
                page.add_style_tag(content=_HIDE_CSS)
                try:
                    page.evaluate(_WAIT_HERO_BG_JS)
                except Exception:
                    pass
                page.evaluate(_PERSONALIZE_JS, [nom, label, ville, city_demo])
                try:
                    page.evaluate("async () => { await document.fonts.ready; }")
                except Exception:
                    pass
                page.wait_for_timeout(1000)
                h = page.evaluate(
                    "() => { const e = document.querySelector('.cust-hero');"
                    " return e ? Math.ceil(e.getBoundingClientRect().bottom) : 0; }")
                if h:
                    png = page.screenshot(
                        clip={"x": 0, "y": 0, "width": 1280,
                              "height": min(int(h), 900)})
            finally:
                browser.close()
    except Exception as exc:
        logger.warning("apercu_site : démo %s échouée : %s", slug, exc)
        return None
    return png


# ===========================================================================
#  PARTIE 2 — Maquette auto-contenue (repli pour les métiers sans démo)
# ===========================================================================

# Couleur d'accent par famille de métier (maquette de repli uniquement).
_SECTOR_STYLE: dict[str, tuple[str, str, str]] = {
    "boulang": ("#b45309", "#f59e0b", "🥖"),
    "patiss":  ("#be185d", "#f472b6", "🧁"),
    "boucher": ("#b91c1c", "#ef4444", "🥩"),
    "fleur":   ("#be185d", "#fb7185", "🌸"),
    "restaur": ("#9a3412", "#fb923c", "🍽️"),
    "coiff":   ("#7c3aed", "#c084fc", "✂️"),
    "beaut":   ("#be185d", "#f9a8d4", "💅"),
    "plomb":   ("#1d4ed8", "#38bdf8", "🔧"),
    "electric": ("#a16207", "#facc15", "💡"),
    "peintr":  ("#7c3aed", "#a78bfa", "🎨"),
    "menuis":  ("#92400e", "#d97706", "🪚"),
    "macon":   ("#57534e", "#a8a29e", "🧱"),
    "garage":  ("#334155", "#64748b", "🚗"),
    "auto":    ("#334155", "#64748b", "🚗"),
    "coach":   ("#7c3aed", "#a78bfa", "🎯"),
    "photograph": ("#4338ca", "#818cf8", "📷"),
}
_DEFAULT_STYLE = ("#4f46e5", "#818cf8", "✦")


def _style_for(metier: str) -> tuple[str, str, str]:
    key = _strip_accents((metier or "").lower())
    for frag, style in _SECTOR_STYLE.items():
        if frag in key:
            return style
    return _DEFAULT_STYLE


def _domain_slug(nom: str) -> str:
    s = _strip_accents((nom or "votre-entreprise").lower())
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    s = re.sub(r"-+", "-", s) or "votre-entreprise"
    return f"{s[:34].strip('-')}.fr"


def _initials(nom: str) -> str:
    skip = {"de", "du", "des", "la", "le", "les", "d", "l", "au", "aux", "et", "a"}
    words = [w for w in re.split(r"[^0-9A-Za-zÀ-ÿ]+", nom or "") if w]
    sig = [w for w in words if _strip_accents(w.lower()) not in skip] or words
    return ("".join(w[0] for w in sig[:2]).upper()) or "✦"


# Vraies photos par métier (téléchargées + vérifiées le 14/06/2026 ; Unsplash).
_PHOTO_DIR = os.path.join(os.path.dirname(__file__), "apercu_photos")
_PHOTO_MAP: dict[str, str] = {
    "plomb": "plombier.jpg", "chauffag": "plombier.jpg",
    "electric": "electricien.jpg",
    "peintr": "peintre.jpg",
    "carrel": "carreleur.jpg",
    "macon": "macon.jpg",
    "menuis": "menuisier.jpg", "ebenist": "menuisier.jpg", "charpent": "menuisier.jpg",
    "plaquist": "plaquiste.jpg", "placo": "plaquiste.jpg", "platr": "plaquiste.jpg",
    "couvr": "batiment.jpg", "serrur": "batiment.jpg", "terrass": "batiment.jpg",
    "paysag": "paysagiste.jpg", "jardin": "paysagiste.jpg", "elagag": "paysagiste.jpg",
    "fleur": "fleuriste.jpg",
    "patiss": "patisserie.jpg", "boulang": "patisserie.jpg", "chocolat": "patisserie.jpg",
    "confis": "patisserie.jpg",
    "restaur": "restaurant.jpg", "pizz": "restaurant.jpg", "brasser": "restaurant.jpg",
    "creper": "restaurant.jpg", "bistro": "restaurant.jpg", "traiteur": "restaurant.jpg",
    "coiff": "coiffeur.jpg", "barbier": "coiffeur.jpg",
    "esthet": "beaute.jpg", "beaut": "beaute.jpg", "ongle": "beaute.jpg",
    "manucur": "beaute.jpg", "maquill": "beaute.jpg", "institut": "beaute.jpg",
    "massag": "bien-etre.jpg", "spa": "bien-etre.jpg", "bien-etre": "bien-etre.jpg",
    "bien etre": "bien-etre.jpg", "sophro": "bien-etre.jpg", "naturopath": "bien-etre.jpg",
    "reflexo": "bien-etre.jpg", "yoga": "bien-etre.jpg", "hypno": "bien-etre.jpg",
    "coach": "coach.jpg",
    "photograph": "photographe.jpg", "photo": "photographe.jpg",
    "tatou": "tatoueur.jpg", "tattoo": "tatoueur.jpg", "piercing": "tatoueur.jpg",
    "animal": "animalier.jpg", "canin": "animalier.jpg", "toilettag": "animalier.jpg",
    "veterin": "animalier.jpg", "chien": "animalier.jpg",
    "garage": "garage.jpg", "mecanic": "garage.jpg", "carross": "garage.jpg",
    "automobile": "garage.jpg", "pneu": "garage.jpg",
    "renov": "batiment.jpg", "batiment": "batiment.jpg", "travaux": "batiment.jpg",
    "artisan": "batiment.jpg", "isolation": "batiment.jpg",
}
_photo_cache: dict[str, str] = {}


def _photo_file_for(metier: str) -> str:
    key = _strip_accents((metier or "").lower())
    for frag, fn in _PHOTO_MAP.items():
        if frag in key:
            return fn
    return "default.jpg"


def _photo_base64(metier: str) -> str:
    fn = _photo_file_for(metier)
    if fn in _photo_cache:
        return _photo_cache[fn]
    try:
        with open(os.path.join(_PHOTO_DIR, fn), "rb") as f:
            b = base64.b64encode(f.read()).decode("ascii")
    except Exception:
        b = ""
    _photo_cache[fn] = b
    return b


def build_preview_html(nom: str, metier: str = "", ville: str = "") -> str:
    """HTML auto-contenu d'une maquette de site (cadre navigateur + hero)."""
    nom = (nom or "Votre entreprise").strip()
    metier = (metier or "").strip()
    ville = (ville or "").strip()
    c1, c2, _emoji = _style_for(metier)
    slug = _domain_slug(nom)
    initials = _initials(nom)
    photo_b64 = _photo_base64(metier)
    if photo_b64:
        right_style = (f"background-image:linear-gradient(to top,"
                       f"rgba(0,0,0,.55),rgba(0,0,0,0) 52%),"
                       f"linear-gradient(135deg,{c1}33,transparent 55%),"
                       f"url('data:image/jpeg;base64,{photo_b64}');"
                       f"background-size:cover;background-position:center;")
        right_inner = ""
    else:
        right_style = f"background:linear-gradient(135deg,{c1},{c2});"
        right_inner = f'<div class="mono">{_html.escape(initials)}</div>'

    eyebrow_bits = [b for b in (metier.upper(), ville.upper()) if b]
    eyebrow = " · ".join(eyebrow_bits) or "VOTRE ACTIVITÉ"
    sub = "Le site qui donne envie de pousser votre porte"
    if ville:
        sub += f", à {ville}"
    sub += "."

    e = _html.escape
    services = [
        ("Savoir-faire", "Un métier maîtrisé et un vrai souci du détail."),
        ("Proximité", "Une équipe à votre écoute, près de chez vous."),
        ("Réactivité", "Une réponse rapide à chacune de vos demandes."),
    ]
    svc_html = "".join(
        f'<div class="svc"><div class="svc-ic">✓</div>'
        f'<div class="svc-t">{e(t)}</div><div class="svc-d">{e(d)}</div></div>'
        for t, d in services)

    return f"""<!DOCTYPE html><html lang="fr"><head><meta charset="utf-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@500;700;800&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ width:1000px; background:#e9eef5; font-family:'Inter',system-ui,sans-serif;
         display:flex; justify-content:center; padding:32px 0; }}
  .win {{ width:940px; background:#fff; border-radius:14px; overflow:hidden;
          box-shadow:0 30px 70px rgba(15,23,42,.28); }}
  .chrome {{ height:42px; background:#f1f5f9; display:flex; align-items:center;
             gap:8px; padding:0 16px; border-bottom:1px solid #e2e8f0; }}
  .dot {{ width:12px; height:12px; border-radius:50%; }}
  .url {{ flex:1; margin-left:14px; height:24px; background:#fff;
          border:1px solid #e2e8f0; border-radius:999px; display:flex;
          align-items:center; padding:0 14px; font-size:12.5px; color:#64748b; }}
  .nav {{ height:58px; display:flex; align-items:center; justify-content:space-between;
          padding:0 34px; border-bottom:1px solid #f1f5f9; }}
  .logo {{ font-family:'Poppins'; font-weight:800; font-size:18px; color:#0f172a; }}
  .menu {{ display:flex; gap:24px; font-size:13.5px; color:#475569; font-weight:500; }}
  .menu .cta {{ background:{c1}; color:#fff; padding:8px 16px; border-radius:999px;
                font-weight:600; }}
  .hero {{ height:380px; display:flex; }}
  .left {{ flex:1.15; padding:44px 40px; display:flex; flex-direction:column;
           justify-content:center; }}
  .eyebrow {{ display:inline-block; align-self:flex-start; font-family:'Poppins';
              font-weight:700; font-size:11.5px; letter-spacing:1.5px;
              color:{c1}; background:{c1}14; padding:7px 13px; border-radius:999px;
              margin-bottom:20px; }}
  h1 {{ font-family:'Poppins'; font-weight:800; font-size:44px; line-height:1.06;
        color:#0f172a; letter-spacing:-1px; text-wrap:balance; }}
  .sub {{ margin-top:18px; font-size:16px; line-height:1.5; color:#475569;
          max-width:430px; text-wrap:pretty; }}
  .ctas {{ margin-top:28px; display:flex; gap:14px; align-items:center; }}
  .btn1 {{ background:{c1}; color:#fff; font-weight:600; font-size:15px;
           padding:14px 26px; border-radius:11px; box-shadow:0 10px 24px {c1}40; }}
  .btn2 {{ color:#0f172a; font-weight:600; font-size:15px; padding:14px 8px; }}
  .right {{ flex:1; position:relative; display:flex; align-items:center;
            justify-content:center; overflow:hidden; }}
  .mono {{ width:175px; height:175px; border-radius:50%;
           background:rgba(255,255,255,.16); border:2px solid rgba(255,255,255,.45);
           display:flex; align-items:center; justify-content:center;
           font-family:'Poppins'; font-weight:800; font-size:72px; color:#fff;
           letter-spacing:1px; box-shadow:0 18px 44px rgba(0,0,0,.20); }}
  .badge {{ position:absolute; bottom:22px; left:22px; right:22px;
            background:rgba(255,255,255,.93); border-radius:12px; padding:12px 15px;
            font-size:13px; color:#0f172a; font-weight:600;
            box-shadow:0 12px 28px rgba(0,0,0,.16); }}
  .badge span {{ color:{c1}; }}
  .services {{ padding:40px 40px 36px; }}
  .svc-title {{ font-family:'Poppins'; font-weight:800; font-size:24px; color:#0f172a;
                text-align:center; margin-bottom:26px; letter-spacing:-.5px; }}
  .svc-row {{ display:flex; gap:20px; }}
  .svc {{ flex:1; background:#f8fafc; border:1px solid #eef2f7; border-radius:14px;
          padding:24px 22px; }}
  .svc-ic {{ width:42px; height:42px; border-radius:11px; background:{c1}1f; color:{c1};
             display:flex; align-items:center; justify-content:center;
             font-weight:800; font-size:20px; margin-bottom:14px; }}
  .svc-t {{ font-family:'Poppins'; font-weight:700; font-size:17px; color:#0f172a;
            margin-bottom:7px; }}
  .svc-d {{ font-size:14px; line-height:1.5; color:#64748b; }}
  .footer {{ background:#0f172a; color:#cbd5e1; padding:24px 40px; display:flex;
             align-items:center; justify-content:space-between; }}
  .f-logo {{ font-family:'Poppins'; font-weight:800; font-size:17px; color:#fff; }}
  .f-links {{ font-size:12.5px; color:#94a3b8; }}
</style></head><body>
  <div class="win">
    <div class="chrome">
      <div class="dot" style="background:#ff5f57"></div>
      <div class="dot" style="background:#febc2e"></div>
      <div class="dot" style="background:#28c840"></div>
      <div class="url">🔒 https://www.{e(slug)}</div>
    </div>
    <div class="nav">
      <div class="logo">{e(nom)}</div>
      <div class="menu"><span>Accueil</span><span>Services</span><span>Avis</span><span class="cta">Contact</span></div>
    </div>
    <div class="hero">
      <div class="left">
        <span class="eyebrow">{e(eyebrow)}</span>
        <h1>{e(nom)}</h1>
        <div class="sub">{e(sub)}</div>
        <div class="ctas">
          <span class="btn1">Demander un devis</span>
          <span class="btn2">Voir nos réalisations →</span>
        </div>
      </div>
      <div class="right" style="{right_style}">
        {right_inner}
        <div class="badge">✓ Site moderne, rapide et <span>adapté au mobile</span></div>
      </div>
    </div>
    <div class="services">
      <div class="svc-title">Nos engagements</div>
      <div class="svc-row">{svc_html}</div>
    </div>
    <div class="footer">
      <div class="f-logo">{e(nom)}</div>
      <div class="f-links">Mentions légales · Plan du site · Contact · © 2026</div>
    </div>
  </div>
</body></html>"""


def _render_mockup_png(nom: str, metier: str, ville: str) -> bytes | None:
    """Rend la maquette auto-contenue en PNG (repli). None si indisponible."""
    html_doc = build_preview_html(nom, metier, ville)
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        logger.info("apercu_site : Playwright absent — maquette sautée.")
        return None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page(
                    viewport={"width": 1000, "height": 640}, device_scale_factor=2)
                page.set_content(html_doc, wait_until="domcontentloaded")
                try:
                    page.evaluate("async () => { await document.fonts.ready; }")
                except Exception:
                    pass
                page.wait_for_timeout(700)
                return page.screenshot(full_page=True)
            finally:
                browser.close()
    except Exception as exc:
        logger.warning("apercu_site : maquette échouée : %s", exc)
        return None


# ===========================================================================
#  Orchestration + hébergement
# ===========================================================================

def render_preview_png(nom: str, metier: str = "", ville: str = "",
                       output_path=None) -> bytes | None:
    """Aperçu du futur site, en PNG. D'abord le vrai site de démo du métier
    (personnalisé) ; à défaut, la maquette auto-contenue. None si rien ne peut
    être rendu — le mail part alors sans aperçu (jamais bloquant)."""
    nom = clean_business_name(nom)
    png = None
    slug = _demo_slug_for(metier)
    # Rendu TOUJOURS dans un thread dédié (sync_playwright ne tourne pas dans
    # la boucle asyncio du serveur).
    # On montre le VRAI site de démo dès qu'on connaît le métier — même SANS
    # ville : dans ce cas la personnalisation retire simplement la mention de
    # ville (cf. _PERSONALIZE_JS) au lieu de retomber sur la maquette générique
    # « Le site qui donne envie de pousser votre porte » (bien moins crédible).
    if slug:
        png = _in_thread(_render_demo_png, nom, metier, ville, slug)
    if png is None:
        png = _in_thread(_render_mockup_png, nom, metier, ville)
    if png is None:
        return None
    if output_path:
        with open(output_path, "wb") as f:
            f.write(png)
        return None
    return png


_BUCKET = "pp-client-photos"  # bucket public déjà en place


def _sb_client():
    try:
        from triskell_core.db import get_client, SupabaseNotConfigured
        try:
            c = get_client()
        except SupabaseNotConfigured:
            return None
        return c if getattr(c, "is_authenticated", False) else None
    except Exception:
        return None


def _public_url(path: str) -> str:
    base = (os.environ.get("SUPABASE_URL")
            or os.environ.get("PIXEL_PROS_SUPABASE_URL") or "").rstrip("/")
    return f"{base}/storage/v1/object/public/{_BUCKET}/{path}" if base else ""


# Version du design : à incrémenter si on change l'aspect de l'aperçu, pour
# invalider les images déjà mises en cache (la clé en dépend).
_DESIGN_VERSION = "2"


def _object_exists(url: str) -> bool:
    """Vrai si l'objet est déjà en ligne (évite de le refabriquer)."""
    if not url:
        return False
    try:
        import urllib.request
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=6) as r:
            return 200 <= getattr(r, "status", 200) < 300
    except Exception:
        return False


def preview_image_url(nom: str, metier: str = "", ville: str = "") -> str:
    """Génère l'aperçu, l'héberge sur Supabase Storage, renvoie l'URL publique.
    Réutilise l'image si elle existe déjà (même prospect) — pas de re-rendu.
    Renvoie "" si indisponible (Playwright/Supabase absents) — jamais bloquant."""
    nom = clean_business_name(nom)
    key = hashlib.sha1(
        f"{nom}|{metier}|{ville}|v{_DESIGN_VERSION}".encode("utf-8")).hexdigest()[:20]
    path = f"apercus/{key}.png"
    url = _public_url(path)
    if url and _object_exists(url):
        return url  # déjà généré → on réutilise
    png = render_preview_png(nom, metier, ville)
    if not png:
        return ""
    c = _sb_client()
    if c is None:
        return ""
    try:
        c.raw.storage.from_(_BUCKET).upload(
            path=path, file=png,
            file_options={"content-type": "image/png", "upsert": "true"})
    except Exception as exc:
        logger.warning("apercu_site : upload échoué : %s", exc)
        return ""
    return url or _public_url(path)


def preview_img_html(nom: str, metier: str = "", ville: str = "") -> str:
    """Bloc <img> prêt à coller dans un mail (ou "" si pas d'aperçu)."""
    url = preview_image_url(nom, metier, ville)
    if not url:
        return ""
    return (f'<img src="{url}" alt="Aperçu de votre futur site" '
            'style="max-width:100%;height:auto;border-radius:10px;'
            'border:1px solid #e5e7eb;display:block;margin:0 0 16px;">')


__all__ = ["build_preview_html", "render_preview_png",
           "preview_image_url", "preview_img_html"]
