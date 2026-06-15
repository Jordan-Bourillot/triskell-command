"""Analyseur « site à refaire » — note le site web d'un prospect.

Idée (levier 1 qualité→conversion, demande Jordan 15/06/2026) : nos
meilleurs clients sont les commerces dont le site est VIEUX / pas adapté
au mobile / pas sécurisé. On peut le détecter automatiquement à partir du
HTML de la page d'accueil — qu'on a DÉJÀ sous la main quand le Prospecteur
Google lit le site pour trouver le mail (donc zéro coût réseau en plus).

⚠️ RÈGLE ABSOLUE (demande Jordan : « on n'a pas le droit à l'erreur ») :
PRÉCISION D'ABORD. Un faux positif — dire « à refaire » à un commerçant
fier de son site — nous ridiculise et nous fait perdre le prospect. C'est
bien pire que rater un vrai vieux site. Donc :

  → On ne flague JAMAIS un site sans au moins UN signal FORT.

Signaux FORTS (chacun suffit, quasi zéro faux positif — défauts qu'un
propriétaire reconnaîtrait lui-même) :
  - pas de balise mobile (viewport)   → ne s'affiche pas sur mobile
  - cadres (frameset/frame)           → techno des années 2000
  - Flash                             → techno abandonnée depuis 2020
  - générateur mort (FrontPage,       → outil de création disparu
    Dreamweaver, GoLive, Joomla 1/2…)

Signaux FAIBLES (NE flaguent JAMAIS seuls — ils ne font qu'alourdir le
score d'un site DÉJÀ flagué par un signal fort) :
  - site en http (pas https)
  - doctype XHTML/HTML4 déclaré
  - vieilles balises <font>/<center> EN GRAND NOMBRE (≥6) seulement
  - copyright vieux de 5 ans et plus

Ce qu'on NE fait PAS (sources de faux positifs écartées volontairement) :
  - flaguer pour 1-2 balises <font>/<center> (les thèmes/builders modernes
    en laissent traîner — c'est ce qui avait flagué à tort hk-maconnerie.fr)
  - flaguer un site juste parce qu'il est en http (un certificat suffit)
  - juger « moche » (indétectable de façon fiable depuis le HTML)
  - pénaliser Wix / Squarespace / WordPress récent (outils modernes)
"""

from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urlparse

# Tag posé sur la fiche prospect quand le site mérite vraiment d'être refait.
REDO_TAG = "site_a_refaire"
# Indicatif (le vrai verrou = présence d'au moins un signal FORT).
REDO_THRESHOLD = 35

# Générateurs de site DÉPASSÉS (et eux seuls — pas Wix/Squarespace/WP récent).
_OLD_GENERATORS = (
    "frontpage", "dreamweaver", "adobe golive", "golive", "namo",
    "publisher 20", "joomla! 1", "joomla! 2", "mambo",
    "iweb", "netobjects", "wordpress 2", "wordpress 3",
)

# ---------------------------------------------------------------------------
# Type d'adresse (sans rien télécharger) — le gros gisement de cibles fiables
# ---------------------------------------------------------------------------
# « Site » = page sociale / annuaire → PAS de vrai site (comparé sur le VRAI
# domaine, pas en sous-chaîne, sinon « leroux.com » matcherait « x.com »).
SOCIAL_DOMAINS = {
    "facebook.com", "fb.com", "fb.me", "instagram.com", "linktr.ee",
    "twitter.com", "x.com", "tiktok.com", "youtube.com", "youtu.be",
    "g.page", "pagesjaunes.fr", "business.google.com",
}
# Hébergeurs gratuits / sous-domaines bricolés → site amateur (suffixe d'hôte).
FREE_HOSTS = (
    "free.fr", "pagesperso-orange.fr", "monsite.orange.fr", "wixsite.com",
    "e-monsite.com", "wordpress.com", "blogspot.com", "blogspot.fr",
    "jimdofree.com", "jimdo.com", "sitew.com", "sitew.fr", "wifeo.com",
    "over-blog.com", "over-blog.fr", "weebly.com", "business.site",
    "godaddysites.com", "webnode.fr", "webnode.com", "000webhostapp.com",
    "strikingly.com", "mystrikingly.com", "site123.me", "yolasite.com",
    "webself.net", "systeme.io", "webador.fr", "webador.com",
)


def _host(url: str) -> str:
    u = (url or "").strip().lower()
    host = urlparse(u if u.startswith("http") else "http://" + u).netloc
    host = host.split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    return host


def _registrable(host: str) -> str:
    parts = [p for p in host.split(".") if p]
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def classify_url(url: str) -> str:
    """Type d'adresse, sans téléchargement :
    'social' (page FB/Insta… = pas de vrai site), 'free_host' (adresse
    gratuite/bricolée), 'normal' (domaine propre), 'empty'."""
    u = (url or "").strip().lower()
    if not u:
        return "empty"
    host = _host(u)
    if _registrable(host) in SOCIAL_DOMAINS or "/maps" in u:
        return "social"
    for h in FREE_HOSTS:
        if host == h or host.endswith("." + h):
            return "free_host"
    return "normal"


def _error_kind(err: str) -> str:
    """Classe une erreur réseau pour décider si un site est VRAIMENT en panne."""
    e = (err or "").lower()
    if ("nameresolution" in e or "getaddrinfo" in e or "name or service" in e
            or "nodename nor servname" in e or "no address associated" in e
            or "failed to resolve" in e):
        return "dns"
    if ("refused" in e or "10061" in e or "10054" in e
            or "connection reset" in e or "actively refused" in e):
        return "refused"
    if "timed out" in e or "timeout" in e:
        return "timeout"
    if "ssl" in e or "certificate" in e:
        return "ssl"
    return "other"


def score_site_html(html: str, final_url: str,
                    now_year: int | None = None) -> dict:
    """Note le HTML d'une page d'accueil + l'URL finale (après redirections).

    Renvoie :
      {
        "score": int 0-100,      # 0 si pas de signal fort ; sinon gravité
        "to_redo": bool,         # VRAI seulement si >=1 signal FORT
        "label": str,            # "Site à refaire" si flagué, sinon ""
        "reasons": [str, ...],   # raisons en français (vide si non flagué)
        "signals": {...},        # détail technique (debug/contrôle)
      }
    """
    html = html or ""
    year = now_year or datetime.now().year

    # Page illisible / quasi vide → on ne juge pas (ambigu, pas de risque).
    if len(html.strip()) < 200:
        return {"score": 0, "to_redo": False, "label": "",
                "reasons": [], "signals": {"empty": True}}

    low = html.lower()
    # On RETIRE le contenu des <script> et <style> avant d'analyser : du code
    # de bibliothèque JS mentionne souvent de vieilles balises (Flash, frames,
    # <font>…) en simple capacité de repli, SANS que le site les affiche. Les
    # scanner créait des faux positifs (ex. un e-commerce moderne flagué
    # « Flash » à cause d'un plugin média). Précision d'abord.
    low = re.sub(r'<script\b[^>]*>.*?</script>', ' ', low, flags=re.S)
    low = re.sub(r'<style\b[^>]*>.*?</style>', ' ', low, flags=re.S)
    signals: dict = {}
    strong: list[tuple[str, int, str]] = []   # (clé, poids, raison)
    weak: list[tuple[str, int, str]] = []

    # ============ SIGNAUX FORTS (chacun peut flaguer seul) ============

    # 1. Mobile : absence de balise viewport = ne s'adapte pas au mobile.
    #    La balise viewport est TOUJOURS en clair dans le HTML quand elle
    #    existe ; son absence est donc fiable (rendu « bureau » sur mobile,
    #    texte minuscule — défaut visible par le propriétaire lui-même).
    has_viewport = bool(re.search(
        r'<meta[^>]+name\s*=\s*["\']?viewport', low))
    signals["mobile"] = has_viewport
    if not has_viewport:
        strong.append(("no_viewport", 45,
                       "ne s'affiche pas correctement sur mobile"))

    # 2. Cadres (frameset/frame).
    has_frames = bool(re.search(r'<frameset\b|<frame\b', low))
    signals["frames"] = has_frames
    if has_frames:
        strong.append(("frames", 60,
                       "construit avec des cadres (frames), très daté"))

    # 3. Flash — UNIQUEMENT un vrai bloc Flash affiché (embed/object/param
    #    qui charge un .swf, ou l'ActiveX Flash). On NE matche PAS la simple
    #    mention « shockwave-flash » : elle traîne dans des bibliothèques JS
    #    modernes (capacité de repli) → ce qui flaguait à tort un e-commerce
    #    récent (fleuriste-lannilis.fr, 15/06/2026).
    has_flash = bool(re.search(
        r'<(?:embed|object|param)\b[^>]*(?:\.swf|clsid:d27cdb6e)', low))
    signals["flash"] = has_flash
    if has_flash:
        strong.append(("flash", 60,
                       "utilise Flash, une technologie abandonnée"))

    # 4. Générateur mort.
    old_gen = ""
    m_gen = re.search(
        r'<meta[^>]+name\s*=\s*["\']?generator["\']?[^>]*content\s*=\s*["\']([^"\']+)',
        low)
    if m_gen:
        gen = m_gen.group(1)
        for og in _OLD_GENERATORS:
            if og in gen:
                old_gen = og
                break
    signals["old_generator"] = old_gen
    if old_gen:
        strong.append(("old_generator", 50,
                       f"créé avec un outil dépassé ({old_gen})"))

    # ============ SIGNAUX FAIBLES (jamais seuls — corroborent) ============

    # a. http (pas de cadenas). Seul = pas suffisant (un certificat suffit).
    is_https = (final_url or "").lower().startswith("https://")
    signals["https"] = is_https
    if not is_https:
        weak.append(("no_https", 15, "pas sécurisé (pas de cadenas HTTPS)"))

    # b. doctype XHTML / HTML4 déclaré.
    old_doctype = False
    m_doc = re.search(r'<!doctype\s+([^>]+)>', low)
    if m_doc:
        doc = m_doc.group(1).strip()
        if doc != "html" and ("xhtml" in doc or "html 4" in doc
                              or "html4" in doc or "//w3c//dtd" in doc):
            old_doctype = True
    signals["old_doctype"] = old_doctype
    if old_doctype:
        weak.append(("old_doctype", 15, "norme HTML dépassée"))

    # c. (supprimé) On NE compte PLUS les balises <font>/<center> : même en
    #    grand nombre, elles apparaissent dans des sites MODERNES (éditeurs
    #    WYSIWYG, fiches produit e-commerce, contenu collé). Signal trop
    #    bruité → faux positifs (fleuriste-lannilis.fr avait 9 <font> sur un
    #    site e-commerce récent). Précision d'abord.

    # d. Copyright vieux de 5 ans et plus (footer abandonné). Bruité (on
    #    oublie souvent de l'actualiser) → faible et seuil prudent (5 ans).
    years = [int(y) for y in re.findall(
        r'(?:©|&copy;|copyright|tous droits)[^0-9]{0,20}(20\d{2})', low)]
    last_year = max(years) if years else None
    signals["copyright_year"] = last_year
    if last_year and last_year <= year - 5:
        weak.append(("old_copyright", min(15, (year - last_year - 4) * 5),
                     f"pas mis à jour depuis {last_year}"))

    # ============ DÉCISION ============
    strong_score = sum(w for _, w, _ in strong)
    weak_score = sum(w for _, w, _ in weak)
    to_redo = strong_score > 0          # ⚠️ il FAUT un signal fort

    if to_redo:
        score = min(100, strong_score + weak_score)
        reasons = [r for _, _, r in strong] + [r for _, _, r in weak]
        label = "Site à refaire"
    else:
        # Pas de signal fort → on ne flague pas. Le score reste bas et
        # informatif (les signaux faibles seuls ne valent pas un chantier).
        score = min(REDO_THRESHOLD - 1, weak_score)
        reasons = []
        label = ""

    signals["strong"] = [k for k, _, _ in strong]
    signals["weak"] = [k for k, _, _ in weak]
    return {
        "score": score,
        "to_redo": to_redo,
        "label": label,
        "reasons": reasons,
        "signals": signals,
    }


def analyze_url(url: str, timeout: int = 6) -> dict:
    """Récupère la page d'accueil d'un site et la note. Tolérant aux pannes.

    Essaie https EN PREMIER (pour ne pas crier « pas sécurisé » sur un site
    qui a un certificat valide mais dont la fiche Google pointe en http),
    puis http en repli.

    Renvoie le dict de `score_site_html` + clés réseau :
      {"ok": bool, "error": str, "fetched_url": str, ...score...}
    """
    base = {"score": 0, "to_redo": False, "label": "", "reasons": [],
            "signals": {}, "ok": False, "error": "", "error_kind": "",
            "fetched_url": ""}
    raw = (url or "").strip()
    if not raw:
        base["error"] = "pas de site"
        return base

    host = raw.split("//")[-1].strip("/")
    candidates = []
    if raw.startswith("http"):
        candidates.append(raw)
        # si on nous donne http://, on tente quand même https d'abord
        if raw.startswith("http://"):
            candidates.insert(0, "https://" + host)
    else:
        candidates = ["https://" + host, "http://" + host]

    import requests
    headers = {"User-Agent":
               "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
               "AppleWebKit/537.36 (KHTML, like Gecko) "
               "Chrome/124.0 Safari/537.36"}
    last_err = ""
    for cand in candidates:
        try:
            r = requests.get(cand, headers=headers, timeout=timeout,
                             allow_redirects=True)
            if r.status_code != 200:
                last_err = f"HTTP {r.status_code}"
                continue
            res = score_site_html(r.text, str(r.url))
            res.update({"ok": True, "error": "", "fetched_url": str(r.url)})
            return res
        except Exception as exc:
            last_err = str(exc)[:200]
            continue
    base["error"] = last_err or "injoignable"
    base["error_kind"] = _error_kind(last_err)
    return base


# ---------------------------------------------------------------------------
# Verdict combiné (type d'adresse + état + vétusté) — 4 familles
# ---------------------------------------------------------------------------
def assess_from_signals(url: str, html_quality: dict | None) -> dict:
    """Décision finale en combinant le TYPE d'adresse et la note du HTML.
    Pour les chasses, qui ont déjà téléchargé la page d'accueil.

    Familles : no_site (page sociale) / free_host (adresse gratuite) /
    old (site vieux) / ok.
    """
    cat = classify_url(url)
    host = _host(url)
    if cat == "social":
        return {"to_redo": True, "category": "no_site",
                "label": "Pas de vrai site",
                "reasons": ["pas de vrai site — seulement une page sur un "
                            "réseau social"],
                "score": 80}
    if cat == "free_host":
        return {"to_redo": True, "category": "free_host",
                "label": "Site bricolé (adresse gratuite)",
                "reasons": [f"site sur une adresse gratuite ({host}) — pas "
                            "son propre nom de domaine"],
                "score": 70}
    hq = html_quality or {}
    if hq.get("to_redo"):
        return {"to_redo": True, "category": "old", "label": "Site à refaire",
                "reasons": hq.get("reasons") or [], "score": hq.get("score") or 60}
    return {"to_redo": False, "category": "ok", "label": "",
            "reasons": [], "score": hq.get("score") or 0}


def assess_site(url: str, timeout: int = 6) -> dict:
    """Verdict complet pour UNE adresse (télécharge si besoin) — pour la passe
    sur la base existante. Familles : no_site / free_host / down / old / ok.

    'down' est CONSERVATEUR : uniquement DNS injoignable ou connexion refusée
    (après les 2 tentatives de analyze_url), JAMAIS un simple timeout, un
    certificat, un 403 anti-robot… (zéro erreur : ne pas dire « en panne » à
    un site qui marche).
    """
    cat = classify_url(url)
    host = _host(url)
    if cat == "empty":
        return {"to_redo": False, "category": "ok", "label": "",
                "reasons": [], "score": 0, "ok": False, "fetched_url": ""}
    if cat == "social":
        return {"to_redo": True, "category": "no_site", "label": "Pas de vrai site",
                "reasons": ["pas de vrai site — seulement une page sur un "
                            "réseau social"], "score": 80, "ok": True,
                "fetched_url": url}

    res = analyze_url(url, timeout=timeout)

    if cat == "free_host":
        reasons = [f"site sur une adresse gratuite ({host}) — pas son propre "
                   "nom de domaine"]
        if res.get("ok") and res.get("reasons"):
            reasons += res["reasons"]
        return {"to_redo": True, "category": "free_host",
                "label": "Site bricolé (adresse gratuite)", "reasons": reasons,
                "score": max(70, res.get("score") or 0), "ok": bool(res.get("ok")),
                "fetched_url": res.get("fetched_url") or url}

    # domaine propre
    if res.get("ok"):
        if res.get("to_redo"):
            return {**res, "category": "old", "label": "Site à refaire"}
        return {**res, "category": "ok"}
    # injoignable : seulement DNS / connexion refusée = vraiment en panne
    if res.get("error_kind") in ("dns", "refused"):
        return {"to_redo": True, "category": "down", "label": "Site en panne",
                "reasons": [f"site injoignable ({res.get('error_kind')})"],
                "score": 75, "ok": False,
                "fetched_url": res.get("fetched_url") or ""}
    # timeout / ssl / 403 / autre → incertain → on NE flague PAS
    return {"to_redo": False, "category": "unknown", "label": "",
            "reasons": [], "score": 0, "ok": False,
            "fetched_url": res.get("fetched_url") or ""}
