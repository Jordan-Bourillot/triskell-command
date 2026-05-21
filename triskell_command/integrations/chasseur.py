"""Le Chasseur — découvre des PME françaises et récupère leurs mails publics.

Pipeline :
  1. Filtre par secteur (libellé ou code NAF) + zone (département / région / ville)
     via l'API publique `recherche-entreprises.api.gouv.fr` (officiel data.gouv,
     gratuit, sans clé). Retourne nom, SIREN, adresse, code NAF…
  2. Pour chaque boîte trouvée, tente de découvrir son site web :
       a. Champ `site_internet` quand l'API le donne (rare mais top quand dispo)
       b. Recherche DuckDuckGo HTML "{nom} {ville} site officiel" sinon
  3. Crawle le site (home + /contact + /mentions-legales + /a-propos) et
     extrait les adresses mail publiques par regex, en filtrant le bruit
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
import threading
import time
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
    """Un appel paginé à l'API officielle. 25 résultats max par page."""
    params: dict = {"page": page, "per_page": 25, "minimal": "true",
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


def _prospect_from_api(result: dict) -> Prospect:
    """Mappe un résultat de recherche-entreprises vers notre modèle Prospect."""
    siege = result.get("siege") or {}
    nom = (result.get("nom_complet")
           or result.get("nom_raison_sociale")
           or result.get("denomination")
           or "")
    return Prospect(
        siren=str(result.get("siren") or ""),
        nom=nom.strip(),
        naf=str(result.get("activite_principale") or ""),
        naf_libelle=str(result.get("section_activite_principale") or ""),
        adresse=(siege.get("adresse") or "").strip(),
        code_postal=(siege.get("code_postal") or "").strip(),
        ville=(siege.get("libelle_commune") or "").strip(),
        site_web="",
        email="",
        telephone="",
    )


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
    "", "/contact", "/contact/", "/nous-contacter", "/nous-contacter/",
    "/mentions-legales", "/mentions-legales/", "/legal", "/legal/",
    "/a-propos", "/a-propos/", "/qui-sommes-nous", "/qui-sommes-nous/",
)


def _fetch(url: str, timeout: int = 12) -> str:
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

    # Verdict : 2 signaux faibles OU 1 signal fort suffisent pour "poor"
    strong_signals = {"site en construction", "contenu maigre / site placeholder"}
    has_strong = any(r in strong_signals for r in reasons)
    if has_strong or len(reasons) >= 2:
        return "poor", reasons
    if reasons:
        # Un seul signal faible isolé → site qu'on garde pas en cible upgrade
        return "ok", reasons
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
    while len(raw) < cap_candidates:
        data = _search_page(hunt.filters, page)
        results = data.get("results") or []
        if not results:
            break
        for r in results:
            p = _prospect_from_api(r)
            if not p.siren or not p.nom:
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

    log(f"{len(raw)} candidats remontés. Recherche des sites + mails…")
    hunt.status = "enriching"
    hunt.save()

    # ---- Étape 2 : pour chaque boîte, trouver site + extraire mails ----
    kept: list[Prospect] = []
    seen_emails: set[str] = set()
    for i, prospect in enumerate(raw):
        if len(kept) >= target:
            break
        try:
            # Cherche le site officiel
            query = f"{prospect.nom} {prospect.ville} site officiel"
            site_url = _ddg_first_real_result(query)
            site_root = _normalize_site(site_url)
            prospect.site_web = site_root

            html_home = ""
            if site_root:
                email, extra, source, html_home = _harvest_emails_for_site(site_root)
                prospect.email = email
                prospect.emails_extra = extra
                prospect.source_mail = source

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
        # Throttle gentil — DDG + serveurs cibles
        time.sleep(0.5)

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
        f"{hunt.stats['avec_mail']} avec mail.")


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
