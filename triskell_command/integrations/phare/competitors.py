"""Competitors — détecte les concurrents directs et suit leurs positions
sur les mots-clés ciblés.

Méthodologie :
1. Détection : pour chaque KW suivi, prend les domaines en top 10 SERP qui
   reviennent le plus souvent. Top 5 = concurrents principaux.
2. Suivi : enregistre la position de chaque concurrent par KW chaque semaine.
3. Détection des évolutions : si un concurrent gagne 5+ positions sur un de
   nos KW prioritaires en 7 jours, alerte.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import date, timedelta
from typing import Optional

from . import dataforseo, repo

logger = logging.getLogger(__name__)


def discover_competitors(site_id: str, *, top_n: int = 5) -> list[str]:
    """Détecte les domaines concurrents qui rankent le plus sur nos KW."""
    site = repo.get_site(site_id)
    if not site:
        return []
    if not dataforseo.is_configured():
        return []
    own_domain = site.get("domain", "")
    keywords = repo.list_keywords(site_id, limit=20)
    domain_counter: Counter[str] = Counter()
    for kw in keywords:
        serp = dataforseo.serp_top10(kw["keyword"])
        for item in serp:
            d = item.get("domain", "")
            if d and own_domain not in d:
                domain_counter[d] += 1
    return [d for d, _ in domain_counter.most_common(top_n)]


def track_positions(site_id: str, *, app_state=None) -> dict:
    """Pour chaque KW × concurrent connu, enregistre la position du jour."""
    site = repo.get_site(site_id)
    if not site:
        return {"ok": False, "error": "site introuvable"}
    if not dataforseo.is_configured():
        return {"ok": False, "error": "DataForSEO non configuré"}

    sb = repo._sb()
    competitors = []
    if sb is not None:
        try:
            rows = (sb.table("phare_competitors").select("competitor_domain")
                    .eq("site_id", site_id).eq("is_active", True).execute().data)
            competitors = [r["competitor_domain"] for r in (rows or [])]
        except Exception:
            pass

    if not competitors:
        # Auto-discover
        discovered = discover_competitors(site_id)
        if sb is not None:
            for d in discovered:
                try:
                    sb.table("phare_competitors").upsert({
                        "site_id": site_id,
                        "competitor_domain": d,
                        "discovered_via": "serp_overlap",
                    }, on_conflict="site_id,competitor_domain").execute()
                except Exception as exc:
                    logger.debug("phare_competitors upsert: %s", exc)
        competitors = discovered

    if not competitors:
        return {"ok": True, "tracked": 0,
                "message": "aucun concurrent détecté (lance d'abord la veille KW)"}

    keywords = repo.list_keywords(site_id, limit=15)
    today = date.today()
    tracked = 0
    alerts = []

    for kw in keywords:
        serp = dataforseo.serp_top10(kw["keyword"])
        positions_by_domain = {it.get("domain"): it.get("rank")
                                 for it in serp}
        for comp in competitors:
            pos = positions_by_domain.get(comp)
            if pos is None:
                continue
            if sb is not None:
                try:
                    sb.table("phare_competitor_positions").insert({
                        "site_id": site_id,
                        "competitor_domain": comp,
                        "keyword": kw["keyword"],
                        "position": pos,
                        "url": next((it.get("url") for it in serp
                                      if it.get("domain") == comp), ""),
                        "snapshot_date": today.isoformat(),
                    }).execute()
                except Exception as exc:
                    logger.debug("competitor_positions insert: %s", exc)
            tracked += 1
            # Alerte si gain > 5 positions vs la semaine dernière
            prev = _previous_position(sb, site_id, comp, kw["keyword"], today)
            if prev and prev - pos >= 5:
                alerts.append({
                    "competitor": comp, "keyword": kw["keyword"],
                    "from": prev, "to": pos,
                })

    if alerts:
        repo.insert_action({
            "site_id": site_id,
            "agent": "competitors",
            "kind": "alerte",
            "title": f"{len(alerts)} concurrents progressent vite",
            "detail_md": _format_alerts_md(alerts),
            "status": "draft",
            "impact": 3, "effort": 2,
        })

    return {"ok": True, "tracked": tracked,
            "alerts": len(alerts),
            "competitors_count": len(competitors)}


def _previous_position(sb, site_id: str, comp: str, kw: str,
                       today: date) -> Optional[int]:
    if sb is None:
        return None
    try:
        rows = (sb.table("phare_competitor_positions").select("position")
                .eq("site_id", site_id)
                .eq("competitor_domain", comp)
                .eq("keyword", kw)
                .lt("snapshot_date", today.isoformat())
                .order("snapshot_date", desc=True).limit(1).execute().data)
        if rows:
            return rows[0].get("position")
    except Exception:
        pass
    return None


def _format_alerts_md(alerts: list[dict]) -> str:
    lines = ["**Concurrents qui ont gagné 5+ positions cette semaine** :", ""]
    for a in alerts:
        lines.append(f"- `{a['competitor']}` — « {a['keyword']} » : "
                     f"position {a['from']} → {a['to']}")
    return "\n".join(lines)
