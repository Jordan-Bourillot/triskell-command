"""Cannibalisation — détecte les requêtes pour lesquelles plusieurs pages
du même site rankent simultanément, ce qui se sabote mutuellement.

Logique :
1. Lit les top requêtes GSC
2. Pour chaque requête, identifie les pages qui rankent (top 50)
3. Si ≥2 pages du même site sont dans le top 30, c'est suspect
4. Calcule la sévérité (impressions cumulées + écart de position)
5. Propose une action :
   - merge : fusionner les 2 pages en 1
   - redirect_301 : rediriger la moins forte vers la plus forte
   - differentiate : ré-axer les contenus sur des intent différentes
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Optional

from . import gsc, repo

logger = logging.getLogger(__name__)


def detect(site_id: str, *, min_pages: int = 2,
           top_n: int = 30) -> list[dict]:
    """Renvoie les cas de cannibalisation détectés.

    Format :
        [{"keyword": str, "competing_paths": [{path, position, clicks, impressions}],
          "severity": int 0-100, "proposed_action": str,
          "proposed_canonical_path": str}]
    """
    site = repo.get_site(site_id)
    if not site:
        return []
    domain = site.get("domain") or ""

    # Pour chaque mot-clé, on a besoin de connaître toutes les pages qui rankent.
    # GSC ne donne pas cette dimension via fetch_top_queries — il faudrait
    # query="x" + dimensions=["query","page"]. On le fait ici.
    sb_query = _gsc_query_x_page(domain, top_n=top_n)
    if not sb_query:
        return []

    by_query: dict[str, list[dict]] = defaultdict(list)
    for row in sb_query:
        by_query[row["query"]].append(row)

    out = []
    for query, rows in by_query.items():
        if len(rows) < min_pages:
            continue
        rows.sort(key=lambda r: r["position"])
        impressions_total = sum(r["impressions"] for r in rows)
        position_spread = rows[-1]["position"] - rows[0]["position"]
        # Sévérité : impressions hautes + écart faible (= les deux pages sont
        # vraiment en compétition) → +pénalisant
        severity = min(100, int(
            (impressions_total / 10) +
            (50 if position_spread < 5 else 20)
        ))
        # Page canonique = celle qui ranke le mieux
        canonical = rows[0]
        # Action recommandée
        if len(rows) == 2 and position_spread < 3:
            action = "merge"
        elif rows[-1]["clicks"] < rows[0]["clicks"] * 0.1:
            action = "redirect_301"
        else:
            action = "differentiate"
        out.append({
            "keyword": query,
            "competing_paths": [
                {"path": r["path"], "position": r["position"],
                 "clicks": r["clicks"], "impressions": r["impressions"]}
                for r in rows
            ],
            "severity": severity,
            "proposed_action": action,
            "proposed_canonical_path": canonical["path"],
        })
    out.sort(key=lambda x: -x["severity"])
    return out


def _gsc_query_x_page(domain: str, *, top_n: int = 30) -> list[dict]:
    """Query GSC avec dimensions [query, page] sur 28 jours."""
    svc = gsc._service()
    if svc is None:
        return []
    from datetime import date, timedelta
    end = date.today() - timedelta(days=2)
    start = end - timedelta(days=27)
    body = {
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "dimensions": ["query", "page"],
        "rowLimit": 1000,
    }
    site_url = f"sc-domain:{domain}"
    try:
        resp = svc.searchanalytics().query(siteUrl=site_url, body=body).execute()
    except Exception:
        try:
            site_url = f"https://{domain}/"
            resp = svc.searchanalytics().query(siteUrl=site_url, body=body).execute()
        except Exception as exc:
            logger.warning("gsc query+page: %s", exc)
            return []
    out = []
    for row in resp.get("rows", []) or []:
        keys = row.get("keys", [])
        if len(keys) < 2:
            continue
        position = float(row.get("position", 0))
        if position > top_n:
            continue
        page_url = keys[1]
        path = "/" + page_url.split(domain, 1)[-1].lstrip("/") if domain in page_url else page_url
        out.append({
            "query": keys[0],
            "page": page_url,
            "path": path,
            "position": position,
            "clicks": int(row.get("clicks", 0)),
            "impressions": int(row.get("impressions", 0)),
        })
    return out


def run_cannibalization(site_id: str, *, app_state=None) -> dict:
    """Détection + persistance + création d'actions."""
    cases = detect(site_id)
    if not cases:
        return {"ok": True, "cases": 0, "message": "aucun cas détecté"}
    sb = repo._sb()
    created = 0
    for c in cases[:20]:
        if sb is not None:
            try:
                sb.table("phare_cannibalization").insert({
                    "site_id": site_id,
                    "keyword": c["keyword"],
                    "competing_paths": c["competing_paths"],
                    "severity": c["severity"],
                    "proposed_action": c["proposed_action"],
                    "proposed_canonical_path": c["proposed_canonical_path"],
                }).execute()
            except Exception as exc:
                logger.warning("cannibalization insert: %s", exc)
        repo.insert_action({
            "site_id": site_id,
            "agent": "cannibalization",
            "kind": "recommandation",
            "title": (f"Cannibalisation « {c['keyword']} » "
                      f"({len(c['competing_paths'])} pages, "
                      f"action: {c['proposed_action']})"),
            "detail_md": _format_case_md(c),
            "status": "draft",
            "impact": 4, "effort": 2,
        })
        created += 1
    return {"ok": True, "cases": len(cases), "actions_created": created}


def _format_case_md(c: dict) -> str:
    lines = [f"**Pages en compétition sur « {c['keyword']} »** :"]
    for p in c["competing_paths"]:
        lines.append(f"- `{p['path']}` — position {p['position']:.1f}, "
                     f"{p['clicks']} clics, {p['impressions']} impressions")
    lines.append("")
    lines.append(f"**Action proposée** : `{c['proposed_action']}`")
    lines.append(f"**Page canonique** : `{c['proposed_canonical_path']}`")
    if c["proposed_action"] == "merge":
        lines.append("\nFusionne le contenu des pages secondaires dans la "
                     "canonique, puis pose un 301 depuis les autres.")
    elif c["proposed_action"] == "redirect_301":
        lines.append("\nLa page secondaire fait < 10% des clics de la "
                     "principale. Pose un 301.")
    else:
        lines.append("\nLes deux pages couvrent réellement des intents "
                     "différents. Différencie les titles+H1 pour clarifier.")
    return "\n".join(lines)
