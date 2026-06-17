"""Crawler web léger pour Le Phare.

Crawle un sous-domaine Triskell (limité au même host), extrait :
- Title / meta description
- H1 + outline Hn
- Word count + nombre de liens internes
- Schema.org types détectés (JSON-LD)
- Liens cassés (200 vs 4xx/5xx)

Utilise `requests` + `BeautifulSoup` (déjà dans requirements). Pas de rendu
JavaScript par défaut — la majorité des sites Triskell sont statiques (Astro
build SSG). Pour les rares pages JS-lourdes, on peut ajouter Playwright plus
tard sans changer l'API.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections import deque
from typing import Iterable, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

USER_AGENT = "TriskellLePhare/0.1 (+https://triskell-studio.fr)"
DEFAULT_TIMEOUT = 15
DEFAULT_MAX_PAGES = 80
DEFAULT_DELAY = 0.6
LINK_TIMEOUT = 8


def _normalize(url: str) -> str:
    """Strip fragment et trailing slash sur path != '/'."""
    p = urlparse(url)
    path = p.path or "/"
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    return f"{p.scheme}://{p.netloc}{path}{('?' + p.query) if p.query else ''}"


def _redirect_is_actionable(src: str, final: str) -> bool:
    """Une redirection vaut-elle une correction côté code ?

    On ignore les normalisations gérées par l'hébergeur (http→https, www,
    barre de fin) — ce n'est PAS un défaut à corriger dans le site. On ne
    garde que les vrais changements de chemin (ex: /ancienne → /nouvelle),
    qui viennent souvent d'un lien interne pointant vers une vieille adresse."""
    try:
        a, b = urlparse(src), urlparse(final)
    except ValueError:
        return False

    def _norm(u) -> tuple[str, str]:
        return (u.netloc.replace("www.", "").lower(),
                (u.path or "/").rstrip("/").lower())

    return _norm(a) != _norm(b)


def _same_host(url: str, host: str) -> bool:
    try:
        return urlparse(url).netloc.lower() == host.lower()
    except Exception:
        return False


def _fetch(url: str, session: requests.Session) -> Optional[requests.Response]:
    try:
        r = session.get(url, timeout=DEFAULT_TIMEOUT, allow_redirects=True)
        return r
    except requests.RequestException as exc:
        logger.debug("crawler fetch %s: %s", url, exc)
        return None


def _extract_page(url: str, html: str, host: str) -> dict:
    """Extrait les infos SEO d'une page HTML."""
    soup = BeautifulSoup(html, "html.parser")

    title = (soup.title.string or "").strip() if soup.title else ""
    meta_desc = ""
    md = soup.find("meta", attrs={"name": "description"})
    if md and md.get("content"):
        meta_desc = md["content"].strip()

    h1_tag = soup.find("h1")
    h1 = (h1_tag.get_text(" ", strip=True) if h1_tag else "")[:300]

    outline = []
    for h in soup.find_all(re.compile(r"^h[2-6]$")):
        outline.append({"level": int(h.name[1]),
                        "text": h.get_text(" ", strip=True)[:200]})

    text = soup.get_text(" ", strip=True)
    word_count = len(text.split())

    # Liens internes
    internal_links = 0
    found_links: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("mailto:", "tel:", "javascript:")):
            continue
        absolute = urljoin(url, href)
        if _same_host(absolute, host):
            internal_links += 1
            found_links.append(_normalize(absolute))

    # Schema.org JSON-LD
    schema_types: list[str] = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "{}")
        except (ValueError, TypeError):
            continue
        items = data if isinstance(data, list) else [data]
        for it in items:
            t = it.get("@type") if isinstance(it, dict) else None
            if isinstance(t, list):
                schema_types.extend([str(x) for x in t])
            elif isinstance(t, str):
                schema_types.append(t)

    parsed = urlparse(url)
    return {
        "url": url,
        "path": parsed.path or "/",
        "title": title,
        "meta_description": meta_desc,
        "h1": h1,
        "h_outline": outline,
        "word_count": word_count,
        "internal_links": internal_links,
        "schema_types": list(set(schema_types)),
        "outgoing_internal_urls": list(set(found_links)),
    }


def crawl_site(domain: str,
               *,
               start_paths: Iterable[str] = ("/",),
               max_pages: int = DEFAULT_MAX_PAGES,
               delay: float = DEFAULT_DELAY,
               check_broken_links: bool = True) -> dict:
    """Crawle `domain` (host nu, ex: pack-elec.triskell-studio.fr).

    Retourne :
        {
          "domain": str,
          "started_at": iso,
          "duration_s": float,
          "pages": [page_dict, ...],
          "broken_links": [{"from": url, "to": url, "status": int}],
          "redirects": int,
          "fetched": int,
          "skipped": int,
        }
    """
    host = domain.lower()
    base = f"https://{host}"
    seen: set[str] = set()
    queue = deque()
    for sp in start_paths:
        url = _normalize(urljoin(base, sp))
        if url not in seen:
            seen.add(url)
            queue.append(url)

    pages: list[dict] = []
    broken: list[dict] = []
    redirects_count = 0
    redirect_chains: list[dict] = []
    started = time.time()
    started_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started))

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT,
                            "Accept": "text/html,application/xhtml+xml"})

    fetched = 0
    skipped = 0

    while queue and len(pages) < max_pages:
        url = queue.popleft()
        r = _fetch(url, session)
        if r is None:
            skipped += 1
            continue
        if r.history:
            redirects_count += len(r.history)
            src = r.history[0].url
            final = r.url
            if (_redirect_is_actionable(src, final)
                    and not any(c["source"] == src for c in redirect_chains)):
                redirect_chains.append({
                    "source": src, "final": final,
                    "status": r.history[0].status_code,
                    "hops": len(r.history),
                })
        if r.status_code >= 400:
            broken.append({"from": url, "to": url, "status": r.status_code})
            continue
        ctype = r.headers.get("content-type", "")
        if "html" not in ctype.lower():
            continue
        try:
            page = _extract_page(r.url, r.text, host)
        except Exception as exc:
            logger.debug("extract %s: %s", url, exc)
            continue
        pages.append(page)
        fetched += 1
        # Découverte
        for link in page.pop("outgoing_internal_urls", []):
            if link not in seen and len(seen) < max_pages * 2:
                seen.add(link)
                queue.append(link)
        time.sleep(delay)

    # Vérification ciblée des liens cassés (échantillon : 1er lien externe par page,
    # tous les internes déjà vus). Pour ne pas exploser le temps, on plafonne.
    if check_broken_links:
        sample = list(seen)[:max(20, max_pages // 2)]
        for url in sample:
            if any(b["to"] == url for b in broken):
                continue
            try:
                r = session.head(url, timeout=LINK_TIMEOUT, allow_redirects=True)
                if r.status_code == 405:  # certains servers refusent HEAD
                    r = session.get(url, timeout=LINK_TIMEOUT, allow_redirects=True)
                if r.status_code >= 400:
                    broken.append({"from": "(crawl)", "to": url, "status": r.status_code})
            except requests.RequestException:
                continue

    duration = time.time() - started
    return {
        "domain": domain,
        "started_at": started_iso,
        "duration_s": round(duration, 2),
        "pages": pages,
        "broken_links": broken,
        "redirects": redirects_count,
        "redirect_chains": redirect_chains[:20],
        "fetched": fetched,
        "skipped": skipped,
        "discovered_total": len(seen),
    }


def quick_check(url: str) -> dict:
    """Check rapide d'une URL : status code, taille, content-type."""
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    try:
        r = session.get(url, timeout=DEFAULT_TIMEOUT, allow_redirects=True)
        return {
            "url": url,
            "status": r.status_code,
            "final_url": r.url,
            "size_bytes": len(r.content),
            "content_type": r.headers.get("content-type", ""),
            "redirects": len(r.history),
        }
    except requests.RequestException as exc:
        return {"url": url, "status": 0, "error": str(exc)}
