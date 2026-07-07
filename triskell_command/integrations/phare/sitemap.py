"""Sitemap.xml + IndexNow.

Génère le sitemap.xml d'un site Triskell à partir de l'inventaire de pages
crawlées, et envoie les URLs nouvelles ou modifiées via le protocole
IndexNow (Bing, Yandex, Seznam, Naver). Google n'utilise pas IndexNow
mais le sitemap reste pertinent pour Google Search Console.

Usage : appel via orchestrator, ou bouton manuel dans la vue.
"""

from __future__ import annotations

import logging
import re
import xml.sax.saxutils as saxutils
from datetime import datetime, timezone
from typing import Optional

import requests

from . import repo

logger = logging.getLogger(__name__)


INDEXNOW_ENDPOINTS = {
    "bing":   "https://www.bing.com/indexnow",
    "yandex": "https://yandex.com/indexnow",
    "seznam": "https://search.seznam.cz/indexnow",
    "naver":  "https://searchadvisor.naver.com/indexnow",
}


def generate_sitemap_xml(site: dict, pages: list[dict]) -> str:
    """Génère le contenu sitemap.xml standard pour un site donné."""
    domain = site.get("domain", "")
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for p in pages:
        url = p.get("url") or f"https://{domain}{p.get('path', '/')}"
        last = p.get("last_crawled_at") or datetime.now(timezone.utc).isoformat()
        lines.append("  <url>")
        lines.append(f"    <loc>{saxutils.escape(url)}</loc>")
        lines.append(f"    <lastmod>{last[:10]}</lastmod>")
        lines.append("    <changefreq>weekly</changefreq>")
        lines.append("  </url>")
    lines.append("</urlset>")
    return "\n".join(lines)


def submit_indexnow(site: dict, urls: list[str], *,
                    target: str = "bing") -> dict:
    """Envoie une liste d'URLs via IndexNow.

    Pré-requis : `phare_config.indexnow_key` doit être posé ET le fichier
    `<key>.txt` contenant la clé doit être hébergé à la racine du site.

    Renvoie {ok, target, urls_pinged, response_code, response_body}.
    """
    cfg = repo.get_config()
    key = cfg.get("indexnow_key", "")
    if not key:
        return {"ok": False, "error": "indexnow_key absent"}
    domain = site.get("domain", "")
    endpoint = INDEXNOW_ENDPOINTS.get(target, INDEXNOW_ENDPOINTS["bing"])
    payload = {
        "host": domain,
        "key": key,
        "keyLocation": f"https://{domain}/{key}.txt",
        "urlList": urls[:10000],
    }
    try:
        r = requests.post(endpoint, json=payload, timeout=30)
    except requests.RequestException as exc:
        return {"ok": False, "error": str(exc)}
    log_row = {
        "site_id": site.get("id"),
        "target": target,
        "urls_pinged": urls[:10000],
        "response_code": r.status_code,
        "response_body": r.text[:500],
    }
    sb = repo._sb()
    if sb is not None:
        try:
            sb.table("phare_sitemap_pings").insert(log_row).execute()
        except Exception as exc:
            logger.debug("sitemap_pings insert: %s", exc)
    return {"ok": r.status_code < 400, "target": target,
            "urls_pinged": len(urls), "response_code": r.status_code,
            "response_body": r.text[:300]}


def _sitemap_unchanged(site_id: str, xml: str, url_count: int) -> bool:
    """Le sitemap est-il identique à la dernière carte sitemap de ce site ?

    Compare le nombre d'URLs ET le fragment XML tel qu'il serait ré-inséré
    (mêmes bornes que insert_action : `xml[:1500]`). Vrai seulement si les
    deux collent → on saute la création d'une carte jumelle. Pas de carte
    précédente, ou lecture impossible → False (on insère : on ne rate jamais
    une vraie mise à jour à cause d'un doute)."""
    sb = repo._sb()
    if sb is None:
        return False
    try:
        rows = (sb.table("phare_actions").select("title,detail_md")
                .eq("site_id", site_id)
                .eq("agent", "sitemap_builder")
                .eq("kind", "recommandation")
                .order("created_at", desc=True)
                .limit(1).execute().data) or []
    except Exception as exc:
        logger.debug("_sitemap_unchanged lecture: %s", exc)
        return False
    if not rows:
        return False
    last = rows[0]
    # Nombre d'URLs de la dernière carte (dans le titre « … (N URLs) »).
    title = last.get("title") or ""
    m = re.search(r"\((\d+)\s*URLs?\)", title)
    if not m or int(m.group(1)) != url_count:
        return False
    # Même contenu XML (fragment stocké dans la carte).
    detail = last.get("detail_md") or ""
    return ("```xml\n" + xml[:1500] + "\n…\n```") in detail


def run_sitemap(site_id: str, *, ping: bool = True,
                ping_targets: Optional[list[str]] = None,
                app_state=None) -> dict:
    site = repo.get_site(site_id)
    if not site:
        return {"ok": False, "error": "site introuvable"}
    pages = repo.list_pages(site_id, limit=5000)
    if not pages:
        return {"ok": False, "error": "aucune page indexée"}

    xml = generate_sitemap_xml(site, pages)

    # Anti-bruit hebdomadaire : si le sitemap est IDENTIQUE à celui de la
    # dernière carte (même nombre d'URLs + même contenu XML), on ne recrée pas
    # de carte chaque lundi pour rien. Une carte ne réapparaît que quand le
    # sitemap change vraiment (page ajoutée/retirée). En cas de doute (lecture
    # impossible), on insère quand même — on ne perd jamais une vraie mise à jour.
    if _sitemap_unchanged(site_id, xml, len(pages)):
        return {"ok": True, "skipped": "sitemap inchangé",
                "urls": len(pages), "xml_size": len(xml)}

    # On ne pousse PAS le sitemap.xml directement sur le site (ça touche au
    # CSS/HTML public via Git → on délègue au git_pipeline). Pour l'instant,
    # on l'attache à une recommandation.
    repo.insert_action({
        "site_id": site_id,
        "agent": "sitemap_builder",
        "kind": "recommandation",
        "title": f"Sitemap.xml généré ({len(pages)} URLs)",
        "detail_md": (f"Sitemap.xml prêt à publier dans `/public/sitemap.xml` "
                      f"({len(xml)} caractères, {len(pages)} URLs).\n\n"
                      "```xml\n" + xml[:1500] + "\n…\n```"),
        "status": "draft",
        "impact": 3, "effort": 1,
    })

    pings = []
    if ping:
        targets = ping_targets or ["bing", "yandex"]
        urls_to_ping = [p.get("url") for p in pages if p.get("url")]
        for target in targets:
            res = submit_indexnow(site, urls_to_ping, target=target)
            pings.append(res)

    return {"ok": True, "urls": len(pages),
            "xml_size": len(xml), "pings": pings}
