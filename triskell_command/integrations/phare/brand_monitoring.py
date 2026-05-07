"""Brand monitoring — surveille les nouvelles mentions de la marque
Triskell et de ses produits sur le web.

Méthode :
1. Pour chaque terme de marque (config phare_config.brand_monitor_terms),
   query DataForSEO SERP avec opérateurs : "Triskell Studio" -site:triskell-studio.fr
   sur les 7 derniers jours
2. Ou fallback : Google Custom Search JSON API (100 req/jour gratuites)
3. Pour chaque résultat nouveau (pas dans phare_brand_mentions) :
   - Crawl rapide pour vérifier si le mot est cité, dans quel contexte,
     avec ou sans lien
4. Si mention sans lien → opportunité backlink
5. Si mention négative → alerte
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Optional

import requests
from bs4 import BeautifulSoup

from . import dataforseo, repo

logger = logging.getLogger(__name__)


def _google_cse_search(term: str, *, api_key: str, cx: str,
                       num: int = 10) -> list[dict]:
    """Google Custom Search JSON API. 100 req/jour gratuites."""
    if not api_key or not cx:
        return []
    try:
        r = requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params={"key": api_key, "cx": cx, "q": term, "num": num,
                     "dateRestrict": "w1"},
            timeout=15,
        )
        if r.status_code >= 400:
            logger.warning("CSE %s: %s", r.status_code, r.text[:200])
            return []
        items = r.json().get("items", []) or []
        return [{"url": i["link"], "title": i.get("title", ""),
                  "snippet": i.get("snippet", "")} for i in items]
    except Exception as exc:
        logger.warning("CSE exc: %s", exc)
        return []


def _detect_link_to_us(html: str, our_domain: str) -> bool:
    """Vérifie si la page contient un lien vers notre domaine."""
    if not html:
        return False
    return bool(re.search(rf'href=["\'][^"\']*{re.escape(our_domain)}',
                           html, re.IGNORECASE))


def _extract_excerpt(html: str, term: str, *, around: int = 200) -> str:
    """Extrait un extrait de texte autour du terme cherché."""
    if not html:
        return ""
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    idx = text.lower().find(term.lower())
    if idx < 0:
        return ""
    start = max(0, idx - around // 2)
    end = min(len(text), idx + len(term) + around // 2)
    return text[start:end].strip()


def scan(site_id: str, *, app_state=None) -> dict:
    """Scan complet : pour chaque terme de marque, cherche sur le web et
    enregistre les nouvelles mentions."""
    site = repo.get_site(site_id)
    if not site:
        return {"ok": False, "error": "site introuvable"}
    sb = repo._sb()
    if sb is None:
        return {"ok": False, "error": "Supabase indispo"}
    cfg = repo.get_config()
    terms = cfg.get("brand_monitor_terms", [])
    if not terms:
        return {"ok": True, "found": 0, "message": "aucun terme configuré"}

    domain = site.get("domain", "")
    own_domain_low = domain.lower()
    cse_key = cfg.get("google_cse_api_key", "") or cfg.get("pagespeed_api_key", "")
    cse_cx = cfg.get("google_cse_cx", "")

    new_mentions = 0
    new_unlinked = 0

    for term in terms:
        # Préférence : DataForSEO SERP (cohérent avec le reste)
        results: list[dict] = []
        if dataforseo.is_configured():
            for r in dataforseo.serp_top10(f'"{term}" -site:{own_domain_low}'):
                results.append({"url": r.get("url", ""),
                                  "title": r.get("title", ""),
                                  "snippet": r.get("snippet", "")})
        else:
            results = _google_cse_search(f'"{term}" -site:{own_domain_low}',
                                          api_key=cse_key, cx=cse_cx)

        for res in results[:15]:
            url = res.get("url", "")
            if not url:
                continue
            source_domain = url.split("/")[2] if "://" in url else url.split("/")[0]
            if own_domain_low in source_domain.lower():
                continue
            # Déjà connu ?
            existing = (sb.table("phare_brand_mentions").select("id")
                        .eq("site_id", site_id)
                        .eq("source_url", url)
                        .eq("brand_term", term).limit(1).execute().data)
            if existing:
                continue
            # Crawl rapide pour vérifier le lien
            html = ""
            try:
                resp = requests.get(url, timeout=10,
                                     headers={"User-Agent": "TriskellLePhare/0.1"})
                if resp.status_code < 400:
                    html = resp.text
            except requests.RequestException:
                pass
            has_link = _detect_link_to_us(html, own_domain_low)
            excerpt = _extract_excerpt(html, term) or res.get("snippet", "")
            try:
                sb.table("phare_brand_mentions").insert({
                    "site_id": site_id,
                    "brand_term": term,
                    "source_url": url,
                    "source_domain": source_domain,
                    "excerpt": excerpt[:1000],
                    "has_link": has_link,
                }).execute()
                new_mentions += 1
                if not has_link:
                    new_unlinked += 1
                    # Alimente phare_backlinks comme opportunité unlinked_mention
                    repo.insert_backlinks(site_id, [{
                        "source_domain": source_domain,
                        "source_url": url,
                        "kind": "opportunity",
                        "opportunity_score": 70,
                        "notes": f"unlinked_mention: {term} cité sans lien",
                    }])
            except Exception as exc:
                logger.warning("brand_mention insert: %s", exc)

    if new_mentions:
        repo.insert_action({
            "site_id": site_id,
            "agent": "brand_monitoring",
            "kind": "recommandation",
            "title": (f"{new_mentions} nouvelles mentions Triskell sur le web "
                      f"({new_unlinked} sans lien à activer)"),
            "detail_md": (f"Le Phare a trouvé {new_mentions} pages qui parlent "
                          f"de toi cette semaine. {new_unlinked} ne pointent "
                          f"pas vers toi → opportunités backlink envoyées au "
                          f"module Outreach."),
            "status": "draft",
            "impact": 4, "effort": 2,
        })

    return {"ok": True, "new_mentions": new_mentions,
            "new_unlinked": new_unlinked}
