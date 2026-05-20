"""Auto-configuration d'un site dans Le Phare à partir d'une simple URL.

Objectif : Jordan ne saisit QUE l'URL ; Claude + un fetch léger remplissent
tout le reste (nom, stack, pages clés à surveiller, notes, externe/interne).

Pipeline :
  1. Normaliser l'URL → domaine propre + URL canonique
  2. Fetch homepage (HTTP GET, timeout court, follow redirects)
  3. Extraire signaux HTML : title, meta desc, generator, h1, liens nav
  4. Détecter la stack (Astro/Next/Vite/HTML) via signatures
  5. Appeler Claude pour obtenir : name, notes (secteur/spécialité), key_paths
  6. Renvoyer un payload prêt pour `repo.upsert_site`

Best-effort : si le fetch échoue ou Claude n'est pas joignable, on retombe
sur des défauts raisonnables (name = domaine capitalisé, key_paths = ['/']).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional
from urllib.parse import urljoin, urlparse

logger = logging.getLogger(__name__)

INTERNAL_HOST_SUFFIXES = (
    "triskell-studio.fr",
    "pixel-pros.fr",
)

USER_AGENT = "TriskellLePhare/AutoConfig (+https://triskell-studio.fr)"
FETCH_TIMEOUT = 12


def normalize_url(raw: str) -> tuple[str, str]:
    """`Cabinet-Dupont.fr/contact ` → (`https://cabinet-dupont.fr`, `cabinet-dupont.fr`).

    Retourne (url_canonique, domaine_nu). Lève ValueError si invalide.
    """
    s = (raw or "").strip()
    if not s:
        raise ValueError("URL vide")
    if not re.match(r"^https?://", s, re.IGNORECASE):
        s = "https://" + s
    p = urlparse(s)
    host = (p.netloc or "").lower().strip()
    if host.startswith("www."):
        host = host[4:]
    if not host or "." not in host:
        raise ValueError(f"Domaine invalide : {raw}")
    return f"https://{host}", host


def is_internal(domain: str) -> bool:
    d = (domain or "").lower()
    return any(d == suf or d.endswith("." + suf) for suf in INTERNAL_HOST_SUFFIXES)


def _fetch_html(url: str) -> Optional[str]:
    try:
        import requests
    except ImportError:
        return None
    try:
        r = requests.get(url, timeout=FETCH_TIMEOUT, allow_redirects=True,
                         headers={"User-Agent": USER_AGENT})
        if r.status_code >= 400:
            return None
        ctype = (r.headers.get("Content-Type") or "").lower()
        if "html" not in ctype and "text" not in ctype:
            return None
        return r.text
    except Exception as exc:
        logger.debug("autoconfig fetch %s: %s", url, exc)
        return None


def _extract_signals(html: str, base_url: str) -> dict:
    """Extrait les signaux utiles d'une homepage."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return {}
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        return {}

    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()[:200]

    meta_desc = ""
    md = soup.find("meta", attrs={"name": "description"})
    if md and md.get("content"):
        meta_desc = md["content"].strip()[:400]

    generator = ""
    gm = soup.find("meta", attrs={"name": "generator"})
    if gm and gm.get("content"):
        generator = gm["content"].strip()[:100]

    h1 = ""
    h1_tag = soup.find("h1")
    if h1_tag:
        h1 = h1_tag.get_text(" ", strip=True)[:200]

    base_host = urlparse(base_url).netloc.lower()
    nav_links: list[dict] = []
    seen_paths: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        full = urljoin(base_url + "/", href)
        p = urlparse(full)
        if p.netloc.lower().lstrip("www.") != base_host.lstrip("www."):
            continue
        path = p.path or "/"
        if path != "/" and path.endswith("/"):
            path = path[:-1]
        if path in seen_paths or path == "/":
            continue
        seen_paths.add(path)
        label = a.get_text(" ", strip=True)[:80]
        if not label:
            continue
        nav_links.append({"path": path, "label": label})
        if len(nav_links) >= 30:
            break

    body_text = ""
    body = soup.find("body")
    if body:
        for tag in body.find_all(["script", "style", "noscript", "svg"]):
            tag.decompose()
        body_text = body.get_text(" ", strip=True)[:1200]

    return {
        "title": title,
        "meta_description": meta_desc,
        "generator": generator,
        "h1": h1,
        "nav_links": nav_links,
        "body_excerpt": body_text,
    }


def _detect_stack(signals: dict, html: str) -> str:
    """Devine la techno depuis les signaux HTML."""
    gen = (signals.get("generator") or "").lower()
    if "astro" in gen:
        return "astro"
    if "next" in gen:
        return "next"
    if "vite" in gen:
        return "vite"
    h = html.lower() if html else ""
    if "data-astro-cid" in h or "/_astro/" in h:
        return "astro"
    if "__next_data__" in h or "/_next/static/" in h:
        return "next"
    if "/@vite/" in h or "type=\"module\"" in h and "vite" in h:
        return "vite"
    return "html"


def _claude_extract(signals: dict, domain: str, app_state=None) -> dict:
    """Demande à Claude : nom métier, secteur (notes), 3-5 pages clés.

    Renvoie {} si Claude n'est pas joignable. Le caller a déjà ses défauts.
    """
    try:
        from . import agents
    except Exception as exc:
        logger.debug("autoconfig: import agents KO: %s", exc)
        return {}

    nav_sample = signals.get("nav_links") or []
    prompt = f"""Tu reçois la homepage d'un site qu'on va surveiller pour son SEO.
Tu dois en extraire UNIQUEMENT ce qui sert à pré-remplir une fiche site :
1. le nom commercial propre (sans slogan, sans " - Accueil", sans ville)
2. une note interne ULTRA courte : secteur + spécialité ou particularité (1 phrase, 100 chars max)
3. les 3 à 5 pages les plus importantes à surveiller (chemins relatifs, ex : "/", "/contact", "/services")

DOMAINE : {domain}
TITLE : {signals.get("title") or "(vide)"}
META DESCRIPTION : {signals.get("meta_description") or "(vide)"}
H1 : {signals.get("h1") or "(vide)"}
DÉBUT DU TEXTE : {signals.get("body_excerpt") or "(vide)"}

LIENS DE NAVIGATION DÉTECTÉS (chemin → texte du lien) :
{json.dumps([{"path": x["path"], "label": x["label"]} for x in nav_sample[:20]], ensure_ascii=False, indent=2)}

RÈGLES STRICTES :
- "name" : le nom du business, pas le slogan. Ex : "Cabinet Dupont" pas "Cabinet Dupont - Avocat à Brest"
- "notes" : 1 phrase factuelle. Ex : "Avocat droit du travail à Brest." Pas de blabla.
- "key_paths" : commence TOUJOURS par "/". Ajoute les pages business clés (contact, services/prestations, tarifs, à propos, blog). Évite les pages légales (mentions, cgv, politique). Max 5 chemins.
- Si tu manques d'infos, fais au mieux avec le domaine seul.

Réponds en JSON STRICT, rien d'autre :
{{
  "name": str,
  "notes": str,
  "key_paths": [str, ...]
}}"""
    try:
        raw = agents.call_llm(prompt, model=agents.DEFAULT_MODEL, app_state=app_state,
                              max_tokens=600)
    except Exception as exc:
        logger.info("autoconfig: Claude indisponible (%s) — fallback défauts", exc)
        return {}
    out = agents._parse_json(raw)
    if not isinstance(out, dict):
        return {}
    cleaned: dict = {}
    name = (out.get("name") or "").strip()
    if name and len(name) <= 120:
        cleaned["name"] = name
    notes = (out.get("notes") or "").strip()
    if notes and len(notes) <= 200:
        cleaned["notes"] = notes
    paths = out.get("key_paths") or []
    if isinstance(paths, list):
        clean_paths = []
        for p in paths:
            if not isinstance(p, str):
                continue
            p = p.strip()
            if not p.startswith("/"):
                p = "/" + p
            if p != "/" and p.endswith("/"):
                p = p[:-1]
            if p not in clean_paths:
                clean_paths.append(p)
            if len(clean_paths) >= 5:
                break
        if clean_paths:
            if "/" not in clean_paths:
                clean_paths.insert(0, "/")
            cleaned["key_paths"] = clean_paths[:5]
    return cleaned


def _fallback_name_from_domain(domain: str) -> str:
    base = domain.split(".")[0]
    base = re.sub(r"[-_]+", " ", base).strip()
    return base.title() if base else domain


def build_site_payload(raw_url: str, *, app_state=None) -> dict:
    """Construit un payload prêt pour `repo.upsert_site` à partir d'une URL.

    Renvoie un dict avec en plus une clé `_autoconfig` qui résume ce qui
    a été détecté vs. mis par défaut — l'UI peut l'afficher pour rassurer
    l'utilisateur ("voilà ce que j'ai trouvé").
    """
    url, domain = normalize_url(raw_url)
    html = _fetch_html(url)
    signals = _extract_signals(html, url) if html else {}
    stack = _detect_stack(signals, html or "")
    claude_out = _claude_extract(signals, domain, app_state=app_state) if signals else {}

    name = (claude_out.get("name") or signals.get("title") or "").strip()
    if not name or len(name) > 120:
        name = _fallback_name_from_domain(domain)

    notes = claude_out.get("notes") or ""
    key_paths = claude_out.get("key_paths") or ["/"]

    payload = {
        "name": name,
        "domain": domain,
        "repo_github": None,
        "repo_branch_main": "main",
        "netlify_site_id": None,
        "stack": stack,
        "priority": 50,
        "key_paths": key_paths,
        "notes": notes,
        "is_external_client": not is_internal(domain),
        "is_active": True,
    }
    payload["_autoconfig"] = {
        "fetched": bool(html),
        "claude_used": bool(claude_out),
        "detected": {
            "stack": stack,
            "title": signals.get("title", ""),
            "h1": signals.get("h1", ""),
            "nav_links_count": len(signals.get("nav_links") or []),
        },
    }
    return payload
