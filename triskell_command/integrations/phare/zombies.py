"""Zombies — détecte les pages sans trafic ni backlink ni conversion sur
N mois et propose une action (boost / redirect / delete / noindex).

Pages zombies = boulet pour le crawl budget et le score d'autorité du site.
Pour chaque page :
- Si jamais cliquée + pas de backlink + word_count < 200 → delete ou noindex
- Si jamais cliquée + word_count > 500 → boost (rafraîchir + maillage)
- Si jamais cliquée + une page proche existe → redirect 301 vers elle
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from . import gsc, repo

logger = logging.getLogger(__name__)


def detect(site_id: str, *, no_click_months: int = 6) -> list[dict]:
    site = repo.get_site(site_id)
    if not site:
        return []
    domain = site.get("domain") or ""
    pages = repo.list_pages(site_id, limit=1000)
    if not pages:
        return []

    # Récupère les pages cliquées au moins 1 fois sur les `no_click_months`
    cutoff = date.today() - timedelta(days=30 * no_click_months)
    clicked_paths = set()
    try:
        rows = gsc._service() and _gsc_pages_with_clicks(domain, cutoff)
        clicked_paths = {r["path"] for r in (rows or [])}
    except Exception as exc:
        logger.debug("gsc click history: %s", exc)

    out = []
    backlinks_by_path: dict[str, int] = {}
    for bl in repo.list_backlinks(site_id, limit=1000):
        target = bl.get("target_url") or ""
        if domain in target:
            path = "/" + target.split(domain, 1)[-1].lstrip("/")
            backlinks_by_path[path] = backlinks_by_path.get(path, 0) + 1

    paths = [p.get("path") for p in pages]

    for p in pages:
        path = p.get("path") or ""
        if path in clicked_paths:
            continue
        wc = p.get("word_count", 0) or 0
        bl_count = backlinks_by_path.get(path, 0)
        if bl_count > 0:
            # Page sans clic mais avec backlink : ne pas tuer, à booster
            action = "boost"
            target = ""
        elif wc < 200:
            # Page maigre + pas de clic + pas de backlink → suppression OK
            action = "delete"
            target = _find_close_page(path, paths)
            if target:
                action = "redirect"
        elif wc < 500:
            action = "noindex"
            target = ""
        else:
            action = "boost"
            target = ""
        out.append({
            "path": path,
            "word_count": wc,
            "backlinks_count": bl_count,
            "proposed_action": action,
            "proposed_target_path": target or "",
        })
    return out


def _find_close_page(path: str, all_paths: list[str]) -> str:
    """Trouve un chemin proche par overlap de tokens."""
    parts = set(p for p in path.replace("-", "/").split("/") if p)
    best = ""
    best_score = 0
    for p in all_paths:
        if p == path:
            continue
        other_parts = set(x for x in p.replace("-", "/").split("/") if x)
        score = len(parts & other_parts)
        if score > best_score:
            best_score = score
            best = p
    return best if best_score >= 2 else ""


def _gsc_pages_with_clicks(domain: str, since: date) -> list[dict]:
    """Liste des pages ayant cliqué au moins 1 fois depuis `since`."""
    svc = gsc._service()
    if svc is None:
        return []
    body = {
        "startDate": since.isoformat(),
        "endDate": date.today().isoformat(),
        "dimensions": ["page"],
        "rowLimit": 5000,
    }
    site_url = f"sc-domain:{domain}"
    try:
        resp = svc.searchanalytics().query(siteUrl=site_url, body=body).execute()
    except Exception:
        try:
            site_url = f"https://{domain}/"
            resp = svc.searchanalytics().query(siteUrl=site_url, body=body).execute()
        except Exception as exc:
            logger.warning("gsc pages clicks: %s", exc)
            return []
    out = []
    for row in resp.get("rows", []) or []:
        if (row.get("clicks") or 0) <= 0:
            continue
        url = (row.get("keys") or [""])[0]
        path = "/" + url.split(domain, 1)[-1].lstrip("/") if domain in url else url
        out.append({"path": path, "clicks": int(row.get("clicks", 0))})
    return out


def run_zombies(site_id: str, *, app_state=None) -> dict:
    site = repo.get_site(site_id)
    if not site:
        return {"ok": False, "error": "site introuvable"}
    cases = detect(site_id)
    if not cases:
        return {"ok": True, "zombies": 0,
                "message": "aucune page zombie détectée"}
    sb = repo._sb()
    for c in cases:
        if sb is not None:
            try:
                sb.table("phare_zombies").upsert({
                    "site_id": site_id,
                    "page_path": c["path"],
                    "word_count": c["word_count"],
                    "backlinks_count": c["backlinks_count"],
                    "proposed_action": c["proposed_action"],
                    "proposed_target_path": c["proposed_target_path"],
                }, on_conflict="site_id,page_path").execute()
            except Exception as exc:
                logger.warning("zombies upsert: %s", exc)
    repo.insert_action({
        "site_id": site_id,
        "agent": "zombies_hunter",
        "kind": "recommandation",
        "title": f"{len(cases)} pages zombies détectées",
        "detail_md": _format_zombies_md(cases),
        "status": "draft",
        "impact": 3, "effort": 3,
    })
    return {"ok": True, "zombies": len(cases)}


def _format_zombies_md(cases: list[dict]) -> str:
    by_action: dict[str, list[dict]] = {}
    for c in cases:
        by_action.setdefault(c["proposed_action"], []).append(c)
    lines = []
    for action, items in by_action.items():
        lines.append(f"**{action.upper()}** ({len(items)} pages)")
        for c in items[:10]:
            tgt = f" → `{c['proposed_target_path']}`" if c["proposed_target_path"] else ""
            lines.append(f"- `{c['path']}` ({c['word_count']} mots, "
                         f"{c['backlinks_count']} backlinks){tgt}")
        if len(items) > 10:
            lines.append(f"_…et {len(items) - 10} autres._")
        lines.append("")
    return "\n".join(lines)
