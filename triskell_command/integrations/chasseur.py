"""Le Chasseur — découvre des PME françaises et récupère leurs mails publics.

Pipeline :
  1. Filtre par secteur (libellé ou code NAF) + zone (département / code postal
     / commune) via l'API publique `recherche-entreprises.api.gouv.fr`
     (officiel data.gouv, gratuit, sans clé). Cette API ne renvoie ni site ni
     mail, juste les infos administratives. Quand une zone est précisée, on
     préfère l'établissement local plutôt que le siège (qui peut être à Paris
     pour une chaîne ayant un resto dans le 22).
  2. Pour chaque boîte, tente de découvrir son site web dans cet ordre :
       a. Devinage à partir du nom + ville : on construit `nom-boite.fr`,
          `nom-boite-ville.fr` etc., on teste le DNS puis on charge le site
          et on calcule un score de pertinence (le nom et la ville doivent
          apparaître dans le HTML).
       b. Mojeek HTML (moteur indépendant gratuit, sans clé) en backup.
       c. DuckDuckGo HTML en dernier recours (souvent KO en environnement
          serveur à cause de leur anti-bot — gardé "au cas où").
  3. Crawle le site validé (home + /contact + /mentions-legales + /a-propos)
     et extrait les adresses mail publiques par regex, en filtrant le bruit
     (no-reply, exemples génériques, plateformes tierces…).
  4. Persiste en local (JSON par chasse) et exporte en CSV importable par Le
     Convoi.

Pourquoi c'est légal en B2B FR : on contacte uniquement des mails génériques
de personnes morales publiés volontairement par l'entreprise sur son propre
site, pour une offre pro pertinente. Position CNIL B2B + art. 47 loi
Informatique et Libertés. On exclut volontairement les mails nominatifs
trouvables sur des annuaires tiers (LinkedIn etc.) — ceux-là passent par
Obelisk avec son propre cadre.
"""
from __future__ import annotations

import csv
import json
import logging
import re
import socket
import threading
import time
import unicodedata
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote_plus, urljoin, urlparse

import requests

logger = logging.getLogger(__name__)


CHASSEUR_DIR = Path.home() / ".triskell-command" / "chasseur"
HUNTS_DIR = CHASSEUR_DIR / "hunts"
EXPORTS_DIR = CHASSEUR_DIR / "exports"


def ensure_dirs() -> None:
    HUNTS_DIR.mkdir(parents=True, exist_ok=True)
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Modèles
# ---------------------------------------------------------------------------
@dataclass
class Prospect:
    siren: str
    nom: str
    naf: str = ""
    naf_libelle: str = ""
    adresse: str = ""
    code_postal: str = ""
    ville: str = ""
    site_web: str = ""
    email: str = ""
    emails_extra: list[str] = field(default_factory=list)
    telephone: str = ""
    source_mail: str = ""   # "site_contact" / "site_home" / "annuaire" / ""
    # Évaluation du site web :
    #   "ok"      → site correct, ce n'est pas une cible "upgrade"
    #   "poor"    → site visiblement amateur / obsolète / cassé
    #   "unknown" → impossible d'évaluer (site inaccessible)
    site_quality: str = ""
    site_quality_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Hunt:
    id: str
    label: str
    created_at: str
    status: str = "pending"   # pending / searching / enriching / done / error
    progress: int = 0          # 0-100
    log: list[str] = field(default_factory=list)
    filters: dict = field(default_factory=dict)
    stats: dict = field(default_factory=dict)
    prospects: list[dict] = field(default_factory=list)
    error: str = ""

    @property
    def path(self) -> Path:
        return HUNTS_DIR / f"{self.id}.json"

    def save(self) -> None:
        ensure_dirs()
        self.path.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, hunt_id: str) -> "Hunt | None":
        p = HUNTS_DIR / f"{hunt_id}.json"
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return cls(**data)
        except Exception as exc:
            logger.warning("hunt.load failed %s: %s", hunt_id, exc)
            return None


# ---------------------------------------------------------------------------
# Source 1 — recherche-entreprises.api.gouv.fr (officiel data.gouv)
# ---------------------------------------------------------------------------
SEARCH_API = "https://recherche-entreprises.api.gouv.fr/search"

# Métiers raccourcis → mots-clés que l'API gère bien en `q`. C'est volontairement
# flou — l'API officielle indexe en plein texte sur la dénomination, l'activité,
# les dirigeants et la NAF. Pour cibler très finement, l'utilisateur peut entrer
# directement un code NAF (ex : 56.10A pour les restos).
SECTOR_PRESETS: dict[str, dict] = {
    "restaurant":        {"activite_principale": "56.10A"},
    "boulangerie":       {"activite_principale": "10.71C"},
    "coiffeur":          {"activite_principale": "96.02A"},
    "garage":            {"activite_principale": "45.20A"},
    "plombier":          {"activite_principale": "43.22A"},
    "electricien":       {"activite_principale": "43.21A"},
    "maconnerie":        {"activite_principale": "43.99C"},
    "menuiserie":        {"activite_principale": "43.32A"},
    "fleuriste":         {"activite_principale": "47.76Z"},
    "opticien":          {"activite_principale": "47.78A"},
    "pharmacie":         {"activite_principale": "47.73Z"},
    "hotel":             {"activite_principale": "55.10Z"},
    "agence_immo":       {"activite_principale": "68.31Z"},
    "architecte":        {"activite_principale": "71.11Z"},
    "comptable":         {"activite_principale": "69.20Z"},
    "avocat":            {"activite_principale": "69.10Z"},
    "auto_ecole":        {"activite_principale": "85.53Z"},
    "salle_sport":       {"activite_principale": "93.13Z"},
    "esthetique":        {"activite_principale": "96.02B"},
    "taxi":              {"activite_principale": "49.32Z"},
    "menage":            {"activite_principale": "81.21Z"},
    "paysagiste":        {"activite_principale": "81.30Z"},
}


def _search_page(filters: dict, page: int) -> dict:
    """Un appel paginé à l'API officielle. 25 résultats max par page.

    NB : on n'utilise PAS `minimal=true` car ce flag supprime les champs
    `siege.site_internet` / `siege.courriel` qui sont notre meilleure source
    pour récupérer le site et le mail sans avoir à passer par DuckDuckGo
    (souvent bloqué par CAPTCHA en environnement serveur).
    """
    params: dict = {"page": page, "per_page": 25,
                    "etat_administratif": "A"}
    # On veut surtout les sociétés actives, mais l'API renvoie aussi les
    # entreprises individuelles utiles (artisans). Pas de filtre `est_societe`
    # par défaut — on prend tout ce qui est administrativement actif.
    if filters.get("activite_principale"):
        params["activite_principale"] = filters["activite_principale"]
    if filters.get("q"):
        params["q"] = filters["q"]
    if filters.get("departement"):
        params["departement"] = filters["departement"]
    if filters.get("code_postal"):
        params["code_postal"] = filters["code_postal"]
    if filters.get("commune"):
        params["code_commune"] = filters["commune"]
    # Borne raisonnable sur la taille — par défaut on cible PME (< 250 salariés)
    if filters.get("tranche_effectif_salarie"):
        params["tranche_effectif_salarie"] = filters["tranche_effectif_salarie"]
    try:
        r = requests.get(SEARCH_API, params=params, timeout=20)
        r.raise_for_status()
        return r.json() or {}
    except Exception as exc:
        logger.warning("search api fail page=%s: %s", page, exc)
        return {}


def _prospect_from_api(result: dict, zone_filter: dict | None = None) -> Prospect:
    """Mappe un résultat de recherche-entreprises vers notre modèle Prospect.

    Important : quand l'utilisateur filtre par département / code postal /
    commune, l'API renvoie quand même le SIÈGE de l'entreprise — qui peut
    être à Paris alors que l'établissement ciblé est dans le 22. Donc on
    privilégie un `matching_etablissements` qui colle à la zone filtrée,
    et on ne retombe sur le siège que si rien ne match.

    L'API recherche-entreprises ne renvoie ni le site web ni le mail — ces
    champs sont remplis dans une étape ultérieure (devinage de domaine,
    Mojeek, crawl).
    """
    siege = result.get("siege") or {}
    matching = result.get("matching_etablissements") or []
    nom = (result.get("nom_complet")
           or result.get("nom_raison_sociale")
           or result.get("denomination")
           or "")

    # Choix de l'établissement à utiliser : on préfère un matching_etablissements
    # qui colle à la zone, sinon le siège.
    etab = _pick_local_etab(matching, siege, zone_filter or {})

    return Prospect(
        siren=str(result.get("siren") or ""),
        nom=nom.strip(),
        naf=str(result.get("activite_principale") or ""),
        naf_libelle=str(result.get("section_activite_principale") or ""),
        adresse=(etab.get("adresse") or "").strip(),
        code_postal=(etab.get("code_postal") or "").strip(),
        ville=(etab.get("libelle_commune") or "").strip(),
        site_web="",
        email="",
        telephone="",
    )


def _pick_local_etab(matching: list[dict], siege: dict, zone: dict) -> dict:
    """Sélectionne l'établissement de l'entreprise le plus pertinent pour
    la zone demandée. Renvoie un dict compatible siege (adresse / code_postal
    / libelle_commune).

    Stratégie :
      - Si la zone précise une commune ou un CP : on cherche un matching_etab
        qui colle exactement.
      - Si la zone précise un département : on prend le premier matching_etab
        actif dans ce département.
      - Sinon : on retombe sur le siège.
    """
    dept = (zone.get("departement") or "").strip()
    cp = (zone.get("code_postal") or "").strip()
    commune = (zone.get("commune") or "").strip()
    actifs = [e for e in matching if (e.get("etat_administratif") == "A")]

    if cp:
        for e in actifs:
            if (e.get("code_postal") or "").strip() == cp:
                return e
    if commune:
        for e in actifs:
            if (e.get("commune") or "").strip() == commune:
                return e
    if dept:
        for e in actifs:
            ecp = (e.get("code_postal") or "").strip()
            if ecp.startswith(dept[:2]) and len(ecp) == 5:
                # match dept (ex : "22" → CP commence par 22)
                # Note : pour les CP < 10 (Corse...) il faudrait gérer le zéro
                if dept in ("2A", "2B"):
                    # Corse : CP 20xxx — pas de filtre fin ici
                    return e
                if ecp[:2] == dept.zfill(2):
                    return e
    # Aucun match : retour au siège (peut être hors-zone, on signale en aval)
    return siege or {}


# ---------------------------------------------------------------------------
# Source 2 — découverte du site web via DuckDuckGo HTML
# ---------------------------------------------------------------------------
DDG_HTML = "https://html.duckduckgo.com/html/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# Domaines à exclure quand on cherche le site officiel d'une boîte — ce sont
# des annuaires tiers, pas des sites d'entreprise.
BLACKLIST_DOMAINS = {
    "pagesjaunes.fr", "societe.com", "verif.com", "infogreffe.fr",
    "indeed.fr", "indeed.com", "linkedin.com", "facebook.com",
    "instagram.com", "youtube.com", "twitter.com", "x.com", "tiktok.com",
    "tripadvisor.fr", "tripadvisor.com", "yelp.fr", "yelp.com",
    "google.com", "google.fr", "maps.google.com",
    "pappers.fr", "kompass.com", "manageo.fr", "annuaire-entreprises.data.gouv.fr",
    "bing.com", "duckduckgo.com",
}


def _ddg_first_real_result(query: str) -> str:
    """Lance une recherche DDG (HTML) et retourne la 1re URL hors blacklist.

    DuckDuckGo HTML est public et n'exige pas de clé. On parse la liste de
    résultats avec une regex sur les liens d'évasion `uddg=`.
    """
    try:
        r = requests.post(
            DDG_HTML,
            data={"q": query},
            headers={"User-Agent": UA, "Accept-Language": "fr-FR,fr;q=0.9"},
            timeout=15,
        )
        r.raise_for_status()
    except Exception as exc:
        logger.debug("ddg fail q=%r: %s", query, exc)
        return ""
    html = r.text or ""
    # Les liens DDG passent par /l/?uddg=<encoded>
    for m in re.finditer(r'href="(?:[^"]*?uddg=)([^"&]+)', html):
        try:
            from urllib.parse import unquote
            url = unquote(m.group(1))
        except Exception:
            continue
        host = (urlparse(url).hostname or "").lower()
        if not host:
            continue
        # Strip www. pour la comparaison blacklist
        host_clean = host[4:] if host.startswith("www.") else host
        if any(host_clean == bad or host_clean.endswith("." + bad)
               for bad in BLACKLIST_DOMAINS):
            continue
        return url
    return ""


# ---------------------------------------------------------------------------
# Source 2bis — devinage de domaine + Mojeek HTML
# ---------------------------------------------------------------------------
# DuckDuckGo HTML renvoie status 202 + page vide en environnement serveur
# (anti-bot). On garde l'appel DDG comme fallback "au cas où" mais on s'appuie
# en priorité sur :
#   a. Devinage du domaine à partir du nom de la boîte + ville (le pattern
#      très courant chez les PME locales : `nom-boite.fr`)
#   b. Mojeek (moteur indépendant qui répond encore aux scrapers HTTP)
#
# Pour chaque candidat trouvé, on calcule un score de pertinence en mesurant
# si le nom + la ville apparaissent dans le HTML du site. Ça évite de garder
# le site d'une chaîne nationale ou d'un homonyme.

_JURIDICAL_WORDS = re.compile(
    r"\b(sarl|sas|sasu|sa|eurl|ei|eirl|sci|scp|snc|scop|scea|gie|ets|ge)\b\.?",
    re.IGNORECASE,
)
_FRENCH_STOPWORDS = re.compile(
    r"\b(le|la|les|de|du|des|et|aux|au|d|l|en|sur|sous|pour|chez)\b",
    re.IGNORECASE,
)
# Mots-clés génériques de métier qui à eux seuls ne valident pas le match
# (sinon "Boulangerie X" → site `boulangerie.fr` validerait à tort).
_GENERIC_TRADE_WORDS = {
    "restaurant", "restaurants", "garage", "boulangerie", "patisserie",
    "coiffeur", "coiffure", "pharmacie", "hotel", "hotels", "salon",
    "auto", "ecole", "optique", "opticien", "pizzeria", "magasin",
    "boutique", "centre", "agence", "cabinet", "societe", "entreprise",
    "atelier", "maison", "service", "services", "studio", "fleuriste",
    "menuiserie", "plomberie", "electricite", "elec", "transport",
    "taxi", "bar", "cafe", "brasserie",
}


def _deaccent(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "")
    return "".join(c for c in s if unicodedata.category(c) != "Mn").lower()


def _slug_company(s: str) -> str:
    """Slugifie un nom d'entreprise pour deviner son domaine.

    - Retire les formes juridiques (SARL, SAS, EURL…)
    - Retire les mots vides (le, la, de…)
    - Décomposes les accents
    - Garde uniquement [a-z0-9-]
    """
    s = (s or "").lower()
    s = _JURIDICAL_WORDS.sub(" ", s)
    s = _FRENCH_STOPWORDS.sub(" ", s)
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"['`’]", "", s)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s


def _domain_candidates(nom: str, ville: str) -> list[str]:
    """Génère une liste ordonnée de domaines à tester pour cette boîte."""
    n = _slug_company(nom)
    v = _slug_company(ville)
    if not n:
        return []
    n_compact = n.replace("-", "")
    cands: list[str] = [
        f"{n}.fr", f"{n}.com",
        f"{n_compact}.fr", f"{n_compact}.com",
    ]
    if v:
        v_compact = v.replace("-", "")
        cands += [f"{n}-{v}.fr", f"{n_compact}{v_compact}.fr"]
    # Deux premiers mots (cas où le nom officiel a un suffixe parasite)
    parts = n.split("-")
    if len(parts) >= 2:
        two = "-".join(parts[:2])
        if two != n:
            cands += [f"{two}.fr", f"{two}.com"]
    # Dédup en gardant l'ordre
    seen: set[str] = set()
    out: list[str] = []
    for c in cands:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _dns_resolves(domain: str) -> bool:
    try:
        socket.gethostbyname(domain)
        return True
    except Exception:
        return False


def _score_site_relevance(html: str, nom: str, ville: str) -> tuple[int, list[str]]:
    """Note (0-100) la pertinence d'un site pour la boîte (nom, ville)."""
    if not html:
        return 0, ["no html"]
    text = _deaccent(re.sub(r"<[^>]+>", " ", html))
    text = re.sub(r"\s+", " ", text)

    nom_l = _deaccent(nom)
    ville_l = _deaccent(ville)
    # Tokens significatifs du nom : > 3 caractères et hors métier générique
    tokens = [t for t in re.split(r"\W+", nom_l)
              if len(t) >= 4 and t not in _GENERIC_TRADE_WORDS]
    if not tokens:
        # Le nom est uniquement composé de mots génériques — on ne peut
        # quasiment rien dire de fiable.
        tokens = [t for t in re.split(r"\W+", nom_l) if len(t) >= 4]

    score = 0
    reasons: list[str] = []
    has_city = bool(ville_l and ville_l in text)

    if has_city:
        score += 40
        reasons.append(f"ville '{ville_l}'")

    found_tokens = [t for t in tokens if t in text]
    if found_tokens:
        per = 40 // max(1, len(tokens))
        score += per * len(found_tokens)
        reasons.append(f"nom {found_tokens}")

    # Pénalité multi-CP (signe d'une chaîne nationale qui liste ses 200 magasins)
    cps = set(re.findall(r"\b(\d{5})\b", text))
    if len(cps) > 8:
        score -= 30
        reasons.append(f"chaîne ? ({len(cps)} CP)")

    # Garde-fou contre les homonymes : si la ville n'apparaît pas, on
    # ne peut être confiant que si on a AU MOINS 2 tokens distinctifs du
    # nom matchés. Sinon on plafonne le score sous le seuil de validation.
    # Exemple : "SNC MICHEL" trouvant `michel.com` (un nom random) — le
    # nom n'a qu'un seul token, sans ville on ne valide pas.
    if not has_city and len(found_tokens) < 2:
        score = min(score, 30)
        reasons.append("ville absente + nom peu distinctif → non fiable")

    return max(0, min(100, score)), reasons


# Moteurs additionnels — par ordre de tentative
_MOJEEK_BLACKLIST_EXTRA = {
    # En plus de BLACKLIST_DOMAINS — sites qui pourrissent souvent les
    # premiers résultats de Mojeek pour des boîtes locales.
    "annuaire-mairie.fr", "cylex-france.fr", "118712.fr", "118000.fr",
    "118218.fr", "mappy.com", "leparisien.fr", "ouest-france.fr",
    "actulegales.fr", "meilleurscoiffeurs.fr", "citymalin.com",
    "chambresdhotes.org", "winamax.fr", "marchesonline.com",
    "lannion-emplois.com", "uacb.athle.fr", "dinard.com",
    "importation-auto.fr", "mojeek.com",
}


def _mojeek_first_results(query: str, limit: int = 5) -> list[str]:
    """Lance une recherche Mojeek HTML (gratuit, sans clé) et retourne les
    premières URL hors blacklist. Renvoie [] si rate-limit ou erreur."""
    try:
        r = requests.get(
            "https://www.mojeek.com/search",
            params={"q": query},
            headers={"User-Agent": UA, "Accept-Language": "fr-FR,fr;q=0.9"},
            timeout=15,
        )
        if r.status_code != 200:
            return []
        text = r.text or ""
    except Exception:
        return []
    # Pattern principal : <a class="ob" href="...">
    links = re.findall(r'<a[^>]+class="ob"[^>]+href="(https?://[^"]+)"', text)
    if not links:
        links = re.findall(r'<h2[^>]*>\s*<a[^>]+href="(https?://[^"]+)"', text)
    blacklist = BLACKLIST_DOMAINS | _MOJEEK_BLACKLIST_EXTRA
    out: list[str] = []
    for url in links:
        host = (urlparse(url).hostname or "").lower()
        host = host[4:] if host.startswith("www.") else host
        if any(host == bad or host.endswith("." + bad) for bad in blacklist):
            continue
        if url not in out:
            out.append(url)
        if len(out) >= limit:
            break
    return out


def _discover_site(nom: str, ville: str) -> tuple[str, int, str, str]:
    """Trouve le meilleur site pour cette boîte.

    Renvoie (site_root, score, source, html_home).
      source ∈ {"guess", "mojeek", "ddg", ""}.
      score < 40 = pas de match validé (le site_root sera "" dans ce cas).
    """
    best_url = ""
    best_score = -1
    best_source = ""
    best_html = ""

    # ─── Voie 1 : devinage de domaine + DNS + fetch ───
    for domain in _domain_candidates(nom, ville):
        if not _dns_resolves(domain):
            continue
        for scheme in ("https", "http"):
            html = _fetch(f"{scheme}://{domain}")
            if not html:
                continue
            if not _looks_french(html):
                # On veut UNIQUEMENT du francophone. Un site anglais
                # appartenant peut-être à la bonne boîte mais on ne sait
                # pas le démarcher en FR — skip.
                break
            score, _ = _score_site_relevance(html, nom, ville)
            if score > best_score:
                best_score = score
                best_url = f"{scheme}://{domain}"
                best_source = "guess"
                best_html = html
            break   # passe au candidat suivant

    if best_score >= 60:
        # Match fort par devinage — pas besoin d'appeler un moteur
        return _normalize_site(best_url), best_score, best_source, best_html

    # ─── Voie 2 : Mojeek HTML ───
    query = f"{nom} {ville}".strip()
    for url in _mojeek_first_results(query, limit=3):
        site_root = _normalize_site(url)
        if not site_root:
            continue
        html = _fetch(site_root)
        if not html:
            continue
        if not _looks_french(html):
            continue
        score, _ = _score_site_relevance(html, nom, ville)
        if score > best_score:
            best_score = score
            best_url = site_root
            best_source = "mojeek"
            best_html = html
        if best_score >= 60:
            break
        time.sleep(0.3)

    if best_score >= 60:
        return _normalize_site(best_url), best_score, best_source, best_html

    # ─── Voie 3 : DDG en dernier recours (souvent KO en serveur) ───
    ddg_url = _ddg_first_real_result(f"{nom} {ville} site officiel")
    if ddg_url:
        site_root = _normalize_site(ddg_url)
        if site_root:
            html = _fetch(site_root)
            if html and _looks_french(html):
                score, _ = _score_site_relevance(html, nom, ville)
                if score > best_score:
                    best_score = score
                    best_url = site_root
                    best_source = "ddg"
                    best_html = html

    if best_score >= 50:
        return _normalize_site(best_url), best_score, best_source, best_html
    return "", best_score if best_score >= 0 else 0, "", best_html


# ---------------------------------------------------------------------------
# Source 3 — extraction d'emails depuis le site
# ---------------------------------------------------------------------------
EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
)

# Patterns d'emails clairement génériques / inutiles
EMAIL_NOISE = re.compile(
    r"(no[-_.]?reply|noreply|donot[-_.]?reply|example\.com|domain\.com|"
    r"votre[-_.]?email|sample\.|test@|email@example|sentry\.io|wixpress|"
    r"u003e|u003c)",
    re.IGNORECASE,
)

CONTACT_PATHS = (
    "", "/contact", "/mentions-legales", "/nous-contacter",
)


def _fetch(url: str, timeout: int = 6) -> str:
    try:
        r = requests.get(
            url,
            headers={"User-Agent": UA, "Accept-Language": "fr-FR,fr;q=0.9"},
            timeout=timeout,
            allow_redirects=True,
        )
        if r.status_code >= 400:
            return ""
        # Décodage best-effort
        ctype = (r.headers.get("Content-Type") or "").lower()
        if "html" not in ctype and "text" not in ctype:
            return ""
        return r.text or ""
    except Exception:
        return ""


def _normalize_site(url: str) -> str:
    if not url:
        return ""
    u = url.strip()
    if not u.startswith(("http://", "https://")):
        u = "https://" + u
    p = urlparse(u)
    if not p.hostname:
        return ""
    return f"{p.scheme}://{p.hostname}"


def _extract_emails_from_html(html: str) -> list[str]:
    if not html:
        return []
    # Décode les entités HTML (&commat; etc.) avant de regex
    text = unescape(html)
    # Décode aussi quelques obfuscations basiques (mailto, [at], (a))
    text = text.replace("&#64;", "@")
    text = re.sub(r"\s+(?:\[|\(|\{)\s*(?:at|arobase|@)\s*(?:\]|\)|\})\s+",
                  "@", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+(?:\[|\(|\{)\s*(?:dot|point|\.)\s*(?:\]|\)|\})\s+",
                  ".", text, flags=re.IGNORECASE)
    found = []
    for m in EMAIL_RE.finditer(text):
        e = m.group(0).lower().rstrip(".,;:)")
        if EMAIL_NOISE.search(e):
            continue
        # Filtre extensions binaires qui matchent par erreur
        if any(e.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".gif",
                                            ".webp", ".svg", ".css", ".js")):
            continue
        if e not in found:
            found.append(e)
    return found


# Sous-domaines de plateformes gratuites = signature site amateur / abandonné.
# On match sur le hostname brut (sans www.).
FREE_PLATFORM_HOSTS = (
    ".wix.com", ".wixsite.com", ".sitew.com", ".sitew.fr",
    ".jimdo.com", ".jimdofree.com", ".jimdosite.com",
    ".weebly.com", ".webnode.fr", ".webnode.com",
    ".e-monsite.com", ".eklablog.com", ".eklablog.fr",
    ".over-blog.com", ".over-blog.fr",
    ".blogspot.com", ".blogspot.fr",
    ".wordpress.com",   # le .com gratuit, pas un WP auto-hébergé
    ".free.fr", ".pagesperso-orange.fr", ".perso.wanadoo.fr",
    ".monsite-orange.fr", ".monsite.wanadoo.fr",
    ".strikingly.com", ".tilda.ws", ".carrd.co",
    ".myshopify.com",   # ok pour shopify mais c'est rarement notre cible
)


def _looks_french(html: str) -> bool:
    """Vérifie qu'un site est principalement en français.

    On part de `<html lang>` quand c'est renseigné, sinon on compte les
    mots français vs anglais les plus communs dans le texte visible.
    Tolérant : en cas de doute on accepte (on rejette uniquement quand
    le site est clairement anglais).
    """
    if not html:
        return True
    m = re.search(r'<html[^>]+lang=["\']([^"\'\s>]+)', html, re.IGNORECASE)
    if m:
        lang = m.group(1).lower()
        if lang.startswith("fr"):
            return True
        # Liste blanche des codes proches du FR (multilingue)
        if lang in ("c", ""):
            pass  # ambiguë → on continue avec le texte
        else:
            # Toute autre langue déclarée explicitement → reject
            return False
    text = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.IGNORECASE)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text).lower()
    fr_markers = ("contact", "accueil", "horaires", "mentions",
                  "boutique", "réservation", "à propos", "nos services",
                  "notre équipe", "bienvenue", "actualités")
    en_markers = ("about us", "contact us", "opening hours", "home page",
                  "our services", "our team", "welcome to", "news")
    fr_hits = sum(1 for w in fr_markers if w in text)
    en_hits = sum(1 for w in en_markers if w in text)
    if fr_hits + en_hits == 0:
        return True   # tolérant
    return fr_hits >= en_hits


def _evaluate_site_quality(site_root: str, html_home: str) -> tuple[str, list[str]]:
    """Évalue la qualité visible d'un site.

    Renvoie (quality, reasons) où quality ∈ {"ok", "poor", "unknown"}.
    Heuristique simple et déterministe (pas d'appel IA), tournée vers les
    signaux qui indiquent qu'une PME aurait clairement intérêt à refaire
    son site : plateforme gratuite, pas de HTTPS, pas mobile-friendly,
    copyright vieux, contenu maigre.
    """
    reasons: list[str] = []
    if not site_root:
        return "unknown", ["pas de site trouvé"]
    if not html_home:
        return "unknown", ["site injoignable"]

    parsed = urlparse(site_root)
    host = (parsed.hostname or "").lower()
    host_no_www = host[4:] if host.startswith("www.") else host
    scheme = (parsed.scheme or "").lower()

    # 1. Plateforme gratuite → toujours poor, signal très fort
    for suffix in FREE_PLATFORM_HOSTS:
        if host_no_www.endswith(suffix):
            reasons.append(f"hébergé sur plateforme gratuite ({suffix.lstrip('.')})")
            # Une plateforme gratuite suffit à classer poor sans cumul
            return "poor", reasons

    # 2. Pas de HTTPS (le site n'a même pas migré en https en 2026 = signal)
    if scheme != "https":
        reasons.append("pas de HTTPS")

    # 3. Pas mobile-friendly (absence de meta viewport)
    if not re.search(r'<meta[^>]+name=["\']viewport["\']', html_home, re.IGNORECASE):
        reasons.append("pas mobile-friendly")

    # 4. Copyright vieux dans le footer (cherche les 4 chiffres d'une année
    #    après © ou Copyright). Si la plus récente trouvée est < 2022, c'est
    #    un signal d'abandon.
    years = [int(y) for y in re.findall(r"(?:©|&copy;|copyright)[^0-9]{0,40}(20\d{2})",
                                          html_home, re.IGNORECASE)]
    if years:
        last = max(years)
        if last < 2022:
            reasons.append(f"copyright {last}")

    # 5. Contenu visible très maigre (= site placeholder / "site en construction")
    text_only = re.sub(r"<script[\s\S]*?</script>", " ", html_home, flags=re.IGNORECASE)
    text_only = re.sub(r"<style[\s\S]*?</style>", " ", text_only, flags=re.IGNORECASE)
    text_only = re.sub(r"<[^>]+>", " ", text_only)
    text_only = re.sub(r"\s+", " ", text_only).strip()
    if len(text_only) < 400:
        reasons.append("contenu maigre / site placeholder")

    # 6. Mentions "site en construction" / "coming soon" très explicites
    if re.search(r"(?:site\s+en\s+construction|coming\s+soon|under\s+construction|"
                 r"page\s+en\s+travaux)", html_home, re.IGNORECASE):
        reasons.append("site en construction")

    # Verdict permissif : 1 seul signal suffit pour "poor". Les sites
    # anglais corporate sont déjà filtrés en amont par _looks_french,
    # donc un footer "copyright 2018" sur un site FR signale bien une
    # PME qui ne touche plus à son site = cible légitime pour une refonte.
    if reasons:
        return "poor", reasons
    return "ok", []


def _harvest_emails_for_site(site_root: str) -> tuple[str, list[str], str, str]:
    """Renvoie (email_principal, autres_emails, source, html_home).

    Le html_home est conservé pour permettre une évaluation qualité du site
    en aval sans refetcher la page d'accueil.
    """
    if not site_root:
        return "", [], "", ""
    collected_home: list[str] = []
    collected_contact: list[str] = []
    html_home = ""
    for path in CONTACT_PATHS:
        url = urljoin(site_root + "/", path.lstrip("/"))
        html = _fetch(url)
        if path == "":
            html_home = html or ""
        emails = _extract_emails_from_html(html)
        if not emails:
            continue
        # On privilégie ce qui sent le mail de la boîte (pas un mail externe
        # de webmaster). Si le mail termine par le domaine racine du site,
        # priorité forte.
        host = (urlparse(site_root).hostname or "").lower()
        host_no_www = host[4:] if host.startswith("www.") else host
        domain_parts = host_no_www.split(".")
        domain_root = ".".join(domain_parts[-2:]) if len(domain_parts) >= 2 else host_no_www
        ranked = sorted(
            emails,
            key=lambda e: (0 if e.endswith("@" + domain_root) else
                           1 if domain_root in e else 2,
                           # Préfère les mails génériques pros aux nominatifs
                           # pour rester carré côté RGPD B2B
                           0 if e.split("@", 1)[0] in {
                               "contact", "info", "hello", "bonjour", "accueil",
                               "commercial", "secretariat", "studio", "agence",
                               "boutique", "magasin", "resto", "restaurant",
                           } else 1, e))
        if path == "":
            collected_home = ranked
        else:
            collected_contact = ranked
            break  # une page contact qui donne quelque chose suffit
        # Mini-throttle pour rester poli
        time.sleep(0.2)
    if collected_contact:
        return collected_contact[0], collected_contact[1:5], "site_contact", html_home
    if collected_home:
        return collected_home[0], collected_home[1:5], "site_home", html_home
    return "", [], "", html_home


# ---------------------------------------------------------------------------
# Orchestration de la chasse (thread background)
# ---------------------------------------------------------------------------
_RUNNING: dict[str, threading.Thread] = {}


def is_running(hunt_id: str) -> bool:
    t = _RUNNING.get(hunt_id)
    return bool(t and t.is_alive())


def list_hunts(limit: int = 20) -> list[dict]:
    """Liste les chasses connues localement, plus récentes en premier."""
    ensure_dirs()
    items: list[dict] = []
    for p in HUNTS_DIR.glob("*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            items.append({
                "id": data.get("id"),
                "label": data.get("label"),
                "created_at": data.get("created_at"),
                "status": data.get("status"),
                "progress": data.get("progress"),
                "stats": data.get("stats") or {},
                "filters": data.get("filters") or {},
                "running": is_running(data.get("id") or ""),
            })
        except Exception:
            continue
    items.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return items[:limit]


def start_hunt(sector: str, zone: dict, target: int = 200,
               with_email_only: bool = True,
               mode: str = "all",
               progress_cb: Callable[[Hunt], None] | None = None) -> Hunt:
    """Crée une chasse, la lance dans un thread daemon, renvoie l'objet Hunt.

    sector : clé d'un preset (cf SECTOR_PRESETS) OU code NAF brut (ex "56.10A")
             OU mot-clé plein-texte.
    zone   : dict avec {departement | code_postal | commune}.
    target : nombre maximum de prospects à ramener (cap dur).
    with_email_only : si True, on n'inclut dans la sortie que les boîtes
                      dont on a trouvé un mail.
    mode   : "all"        → toutes les boîtes avec mail trouvé (mode large)
             "poor_sites" → uniquement les boîtes dont le site est jugé
                            obsolète / amateur (cible "vendre une refonte").
    """
    ensure_dirs()
    hunt_id = uuid.uuid4().hex[:12]
    if mode not in ("all", "poor_sites"):
        mode = "all"
    label = _build_label(sector, zone, mode=mode)
    filters = _build_filters(sector, zone)
    hunt = Hunt(
        id=hunt_id,
        label=label,
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        status="pending",
        progress=0,
        filters={**filters, "sector_input": sector, "zone_input": zone,
                 "target": target, "with_email_only": with_email_only,
                 "mode": mode},
    )
    hunt.save()

    def _thread():
        try:
            _run_hunt(hunt, target=target, with_email_only=with_email_only,
                      mode=mode, progress_cb=progress_cb)
        except Exception as exc:
            logger.exception("hunt %s crashed", hunt.id)
            hunt.status = "error"
            hunt.error = str(exc)
            hunt.save()

    t = threading.Thread(target=_thread, daemon=True,
                          name=f"chasseur-{hunt_id}")
    _RUNNING[hunt_id] = t
    t.start()
    return hunt


def _build_label(sector: str, zone: dict, mode: str = "all") -> str:
    s = (sector or "").strip() or "tous secteurs"
    zparts = []
    if zone.get("commune"):
        zparts.append(zone["commune"])
    if zone.get("code_postal"):
        zparts.append(zone["code_postal"])
    if zone.get("departement"):
        zparts.append(f"dept {zone['departement']}")
    zlabel = " · ".join(zparts) or "France"
    suffix = "  ·  sites pourris" if mode == "poor_sites" else ""
    return f"{s} — {zlabel}{suffix}"


def _build_filters(sector: str, zone: dict) -> dict:
    f: dict = {}
    s = (sector or "").strip().lower()
    if s in SECTOR_PRESETS:
        f.update(SECTOR_PRESETS[s])
    elif re.match(r"^\d{2}\.\d{2}[A-Z]$", (sector or "").strip()):
        f["activite_principale"] = sector.strip()
    elif sector:
        f["q"] = sector
    z = zone or {}
    if z.get("departement"):
        f["departement"] = str(z["departement"]).strip()
    if z.get("code_postal"):
        f["code_postal"] = str(z["code_postal"]).strip()
    if z.get("commune"):
        f["commune"] = str(z["commune"]).strip()
    return f


def _run_hunt(hunt: Hunt, target: int, with_email_only: bool,
              mode: str = "all",
              progress_cb: Callable[[Hunt], None] | None = None) -> None:
    def log(msg: str) -> None:
        hunt.log.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
        # Garde les 200 dernières lignes
        if len(hunt.log) > 200:
            hunt.log = hunt.log[-200:]
        hunt.save()
        if progress_cb:
            try: progress_cb(hunt)
            except Exception: pass

    hunt.status = "searching"
    hunt.save()
    log(f"Chasse démarrée : {hunt.label}")

    # ---- Étape 1 : récupérer les entreprises via l'API officielle ----
    raw: list[Prospect] = []
    page = 1
    # On charge un large pool de candidats pour compenser ceux dont on ne
    # trouvera pas le mail. En mode "poor_sites", on multiplie encore car
    # une grande partie des sites trouvés seront "ok" (donc rejetés).
    overshoot = 6 if mode == "poor_sites" else 3
    cap_candidates = max(target * overshoot, 50)
    zone_filter = {k: hunt.filters.get(k) for k in
                   ("departement", "code_postal", "commune")
                   if hunt.filters.get(k)}
    while len(raw) < cap_candidates:
        data = _search_page(hunt.filters, page)
        results = data.get("results") or []
        if not results:
            break
        for r in results:
            p = _prospect_from_api(r, zone_filter=zone_filter)
            if not p.siren or not p.nom:
                continue
            # Si l'utilisateur a précisé une zone, on rejette les boîtes
            # dont aucun établissement n'est dans cette zone (ça arrive quand
            # le seul matching est fermé ou hors-zone). On détecte ça si
            # le code postal final ne colle pas du tout au département demandé.
            if zone_filter.get("departement"):
                dept = zone_filter["departement"]
                if p.code_postal and not p.code_postal.startswith(dept[:2]):
                    continue
            raw.append(p)
            if len(raw) >= cap_candidates:
                break
        total = data.get("total_results") or len(raw)
        hunt.progress = min(25, int(15 * len(raw) / max(cap_candidates, 1)))
        hunt.stats = {"candidats": len(raw), "total_api": total}
        log(f"Page {page} → {len(results)} entreprises ({len(raw)} cumulés)")
        page += 1
        # L'API officielle gère sans souci ce rythme, mais on reste poli
        time.sleep(0.4)
        # Arrêt si on a tout aspiré
        if data.get("page", page - 1) >= (data.get("total_pages") or 0):
            break

    if not raw:
        hunt.status = "done"
        hunt.error = "Aucune entreprise trouvée avec ces critères."
        hunt.save()
        log("Aucun résultat — élargis les filtres.")
        return

    log(f"{len(raw)} candidats remontés. Recherche du site web "
        f"(devinage de domaine + Mojeek) puis extraction du mail…")
    hunt.status = "enriching"
    hunt.save()

    # ---- Étape 2 : pour chaque boîte, trouver site + extraire mails ----
    kept: list[Prospect] = []
    seen_emails: set[str] = set()
    sources_count = {"guess": 0, "mojeek": 0, "ddg": 0}
    for i, prospect in enumerate(raw):
        if len(kept) >= target:
            break
        try:
            # 1) Découverte du site : devinage de domaine → Mojeek → DDG
            site_root, score, source, html_home = _discover_site(
                prospect.nom, prospect.ville,
            )
            prospect.site_web = site_root
            if source:
                sources_count[source] = sources_count.get(source, 0) + 1

            # 2) Crawl des pages contact pour récupérer un mail public.
            #    On garde le html_home (page d'accueil) déjà chargé pour
            #    éviter une 2e requête sur la home pendant l'évaluation.
            if site_root:
                email, extra, source_mail, html_contact = (
                    _harvest_emails_for_site(site_root)
                )
                prospect.email = email
                prospect.emails_extra = extra
                prospect.source_mail = source_mail
                # Si _harvest a rechargé la home (cas où elle a renvoyé un
                # html), on garde celui-là (plus complet). Sinon on garde
                # celui obtenu lors de la découverte.
                if html_contact:
                    html_home = html_contact

            # Évaluation qualité du site (déterministe, pas d'IA)
            quality, reasons = _evaluate_site_quality(site_root, html_home)
            prospect.site_quality = quality
            prospect.site_quality_reasons = reasons

            if prospect.email and prospect.email in seen_emails:
                # Dédoublonnage cross-boîtes (cas franchises etc.)
                prospect.email = ""
                prospect.source_mail = ""

            # Filtrage selon le mode :
            #   - "all"        → on garde (avec mail si with_email_only)
            #   - "poor_sites" → on ne garde QUE les sites jugés "poor"
            mode_keep = True
            if mode == "poor_sites":
                mode_keep = (quality == "poor")

            include = mode_keep and (bool(prospect.email) or not with_email_only)
            if include:
                kept.append(prospect)
                if prospect.email:
                    seen_emails.add(prospect.email)
        except Exception as exc:
            logger.warning("enrich fail %s: %s", prospect.nom, exc)

        # Progression & persistance régulière
        hunt.progress = 25 + int(70 * (i + 1) / len(raw))
        hunt.stats = {
            "candidats":   len(raw),
            "traites":     i + 1,
            "retenus":     len(kept),
            "avec_mail":   sum(1 for x in kept if x.email),
            "sites_poor":  sum(1 for x in kept if x.site_quality == "poor"),
        }
        # Snapshot toutes les 5 boîtes ou à chaque retenu (pour que l'UI suive)
        if (i % 5 == 0) or prospect.email:
            hunt.prospects = [p.to_dict() for p in kept]
            hunt.save()
            if progress_cb:
                try: progress_cb(hunt)
                except Exception: pass
        # Throttle gentil — on est poli avec les serveurs cibles
        time.sleep(0.2)

    # ---- Finalisation ----
    hunt.prospects = [p.to_dict() for p in kept]
    hunt.progress = 100
    hunt.status = "done"
    hunt.stats = {
        "candidats":   len(raw),
        "traites":     len(raw),
        "retenus":     len(kept),
        "avec_mail":   sum(1 for x in kept if x.email),
        "sites_poor":  sum(1 for x in kept if x.site_quality == "poor"),
    }
    hunt.save()
    log(f"Chasse terminée : {len(kept)} retenus, "
        f"{hunt.stats['avec_mail']} avec mail. "
        f"Sites trouvés via : devinage={sources_count.get('guess', 0)}, "
        f"mojeek={sources_count.get('mojeek', 0)}, "
        f"ddg={sources_count.get('ddg', 0)}.")


def export_csv(hunt_id: str) -> dict:
    """Sort un CSV importable par Le Convoi. Retourne {ok, path}."""
    h = Hunt.load(hunt_id)
    if not h:
        return {"ok": False, "error": "chasse introuvable"}
    ensure_dirs()
    path = EXPORTS_DIR / f"{h.id}_{_slug(h.label)}.csv"
    rows = h.prospects or []
    # Champs alignés sur ce que Le Convoi sait extraire (nom + email + contexte).
    # On ajoute en queue les colonnes "qualité du site" — pertinentes en mode
    # "poor_sites" pour personnaliser le pitch.
    fields = ["entreprise", "email", "site_web", "telephone", "adresse",
              "code_postal", "ville", "secteur", "siren", "source_mail",
              "site_quality", "site_quality_reasons"]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            if not r.get("email"):
                continue
            reasons = r.get("site_quality_reasons") or []
            w.writerow({
                "entreprise":  r.get("nom") or "",
                "email":       r.get("email") or "",
                "site_web":    r.get("site_web") or "",
                "telephone":   r.get("telephone") or "",
                "adresse":     r.get("adresse") or "",
                "code_postal": r.get("code_postal") or "",
                "ville":       r.get("ville") or "",
                "secteur":     r.get("naf") or "",
                "siren":       r.get("siren") or "",
                "source_mail": r.get("source_mail") or "",
                "site_quality": r.get("site_quality") or "",
                "site_quality_reasons": "; ".join(reasons) if isinstance(reasons, list) else "",
            })
    return {"ok": True, "path": str(path), "rows": sum(1 for r in rows if r.get("email"))}


def push_to_autopilot(hunt_id: str) -> dict:
    """Convertit les prospects d'une chasse en `Prospect` cœur et les pousse
    dans la base partagée — d'où l'Auto-Pilote viendra les ramasser la nuit
    pour enrichir + rédiger + envoyer.

    Renvoie {ok, created, merged, total, error, backend}.
      - backend = "remote" → Supabase (partagé Jordan/Thomas, auto-pilote nocturne)
      - backend = "local"  → fallback JSON (l'Auto-Pilote local pourra le voir
                              s'il tourne sur la même machine)
    """
    h = Hunt.load(hunt_id)
    if not h:
        return {"ok": False, "error": "chasse introuvable"}
    if not h.prospects:
        return {"ok": False, "error": "aucun prospect à pousser"}

    # Lazy imports — triskell_core n'est pas forcément dispo en dev sans le pkg
    try:
        from triskell_core.prospect.core.crm import get_crm
        from triskell_core.prospect.core.prospect import Prospect as CoreProspect, Source
    except ImportError as exc:
        return {"ok": False, "error":
                f"triskell_core absent — impossible de pousser ({exc})"}

    # Détecte le backend (Supabase si auth, sinon JSON local)
    try:
        crm = get_crm()
    except Exception as exc:
        return {"ok": False, "error": f"connexion CRM impossible : {exc}"}
    backend = "remote" if crm.__class__.__name__ == "RemoteCRM" else "local"

    mode = (h.filters or {}).get("mode") or "all"
    sector = (h.filters or {}).get("sector_input") or ""

    core_prospects: list[CoreProspect] = []
    for p in h.prospects:
        email = (p.get("email") or "").strip()
        if not email:
            continue   # Auto-Pilote ne peut rien faire sans mail
        # Tag spécifique au mode pour reconnaître la cohorte côté CRM
        tag_mode = "chasseur:sites_pourris" if mode == "poor_sites" else "chasseur:large"
        reasons = p.get("site_quality_reasons") or []
        cp = CoreProspect(
            name=(p.get("nom") or "").strip(),
            legal_name=(p.get("nom") or "").strip(),
            siren=(p.get("siren") or "").strip(),
            emails=[email] + [e for e in (p.get("emails_extra") or []) if e],
            website=(p.get("site_web") or "").strip(),
            address=(p.get("adresse") or "").strip(),
            city=(p.get("ville") or "").strip(),
            postal_code=(p.get("code_postal") or "").strip(),
            country="FR",
            naf_code=(p.get("naf") or "").strip(),
            industry=sector,
            language="fr",
            tags=[tag_mode] + (["site_pourri"] if p.get("site_quality") == "poor" else []),
            notes=" · ".join(reasons) if reasons else "",
            sources=[Source(
                name="chasseur",
                source_id=(p.get("siren") or "").strip(),
                url=(p.get("site_web") or "").strip(),
            )],
            status="new",
        )
        core_prospects.append(cp)

    if not core_prospects:
        return {"ok": False, "error":
                "aucun prospect avec mail à pousser (cible auto-pilote = mail requis)"}

    try:
        result = crm.upsert_many(core_prospects)
        if hasattr(crm, "save"):
            try: crm.save()
            except Exception: pass
        return {
            "ok": True,
            "backend":  backend,
            "created":  int(result.get("created") or 0),
            "merged":   int(result.get("merged") or 0),
            "total":    int(result.get("total") or 0),
            "pushed":   len(core_prospects),
        }
    except Exception as exc:
        return {"ok": False, "error": f"upsert échoué : {exc}"}


def delete_hunt(hunt_id: str) -> dict:
    p = HUNTS_DIR / f"{hunt_id}.json"
    if p.exists():
        try:
            p.unlink()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
    return {"ok": True}


def _slug(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s.lower()).strip("-")
    return s[:40] or "chasse"
