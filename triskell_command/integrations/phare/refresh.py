"""Refresh — détecte les articles vieux qui perdent du trafic et propose
un brief de rafraîchissement.

Logique :
1. Pour chaque page article (Article schema, /blog/, /guide/, etc.),
   compare le trafic des 30 derniers jours au pic des 12 derniers mois
2. Si décrochage > seuil (config refresh_decline_threshold, défaut -25%)
   ET âge > seuil (config refresh_min_age_months, défaut 12)
3. Crée un brief de refresh : nouveaux chiffres, nouveaux exemples,
   liens internes à ajouter, sections à compléter
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from . import agents, gsc, repo

logger = logging.getLogger(__name__)


def detect(site_id: str, *,
           min_age_months: int = 12,
           decline_threshold: float = -25.0) -> list[dict]:
    site = repo.get_site(site_id)
    if not site:
        return []
    domain = site.get("domain") or ""
    pages = repo.list_pages(site_id, limit=1000)
    article_paths = [p for p in pages
                     if any(seg in (p.get("path") or "")
                            for seg in ("/blog", "/article", "/guide", "/tuto"))]
    if not article_paths:
        return []

    # Trafic actuel (30j) vs pic (12 mois)
    current = _gsc_clicks_window(domain, days=30)
    full_year = _gsc_clicks_window(domain, days=365, by_month=True)

    out = []
    for p in article_paths:
        path = p.get("path") or ""
        cur = sum(c for url, c in current.items() if path in url)
        peaks = []
        for month, mp in full_year.items():
            peaks.append(sum(c for url, c in mp.items() if path in url))
        peak = max(peaks) if peaks else 0
        if peak == 0:
            continue
        decline = (cur - peak) / peak * 100
        if decline > decline_threshold:
            continue
        out.append({
            "path": path,
            "clicks_now": cur,
            "clicks_peak": peak,
            "decline_pct": round(decline, 1),
            "refresh_score": int(min(100, abs(decline))),
        })
    out.sort(key=lambda x: x["refresh_score"], reverse=True)
    return out


def _gsc_clicks_window(domain: str, *, days: int,
                       by_month: bool = False) -> dict:
    svc = gsc._service()
    if svc is None:
        return {}
    end = date.today() - timedelta(days=2)
    start = end - timedelta(days=days)
    body = {
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "dimensions": ["date", "page"] if by_month else ["page"],
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
            logger.warning("gsc clicks window: %s", exc)
            return {}
    if by_month:
        out: dict[str, dict[str, int]] = {}
        for row in resp.get("rows", []) or []:
            keys = row.get("keys") or ["", ""]
            d = keys[0]
            month = d[:7] if len(d) >= 7 else d
            url = keys[1] if len(keys) > 1 else ""
            out.setdefault(month, {}).setdefault(url, 0)
            out[month][url] += int(row.get("clicks", 0))
        return out
    out2 = {}
    for row in resp.get("rows", []) or []:
        url = (row.get("keys") or [""])[0]
        out2[url] = int(row.get("clicks", 0))
    return out2


# ---------------------------------------------------------------------------
class RefreshBriefer(agents.Agent):
    name = "refresh_briefer"
    role = """Tu es le RefreshBriefer de Le Phare.

Mission : à partir d'un article qui a perdu du trafic SEO, produire un
brief de rafraîchissement actionnable :
- 3 sections à enrichir (avec idées précises)
- 5 statistiques/chiffres à mettre à jour si présents dans l'article
- 3 liens internes à ajouter
- 1 nouvelle section H2 à créer

Format JSON strict :
{
  "sections_to_enrich": [{"h2": str, "what_to_add": str}],
  "stats_to_refresh": [str],
  "internal_links_to_add": [str],
  "new_h2_section": {"title": str, "outline": str}
}"""

    def run(self, *, page: dict, decline_pct: float, app_state=None) -> dict:
        prompt = f"""ARTICLE : {page.get('url')}
TITLE : {page.get('title')}
H1 : {page.get('h1')}
HN OUTLINE : {page.get('h_outline', [])}
WORDCOUNT : {page.get('word_count')}

DÉCLIN MESURÉ : {decline_pct}% par rapport au pic des 12 derniers mois.

Produis le brief au format JSON."""
        out = self.call(prompt, app_state=app_state)
        return out if isinstance(out, dict) else {}


def run_refresh(site_id: str, *, max_articles: int = 5,
                app_state=None) -> dict:
    site = repo.get_site(site_id)
    if not site:
        return {"ok": False, "error": "site introuvable"}
    cfg = repo.get_config()
    decline_threshold = cfg.get("refresh_decline_threshold", -25)
    min_age = cfg.get("refresh_min_age_months", 12)

    cases = detect(site_id, decline_threshold=decline_threshold,
                    min_age_months=min_age)
    if not cases:
        return {"ok": True, "candidates": 0,
                "message": "aucun article à rafraîchir détecté"}

    pages = repo.list_pages(site_id, limit=1000)
    by_path = {p.get("path"): p for p in pages}
    sb = repo._sb()
    briefer = RefreshBriefer()
    created = 0

    for c in cases[:max_articles]:
        page = by_path.get(c["path"])
        if not page:
            continue
        try:
            brief = briefer.run(
                page=page, decline_pct=c["decline_pct"],
                app_state=app_state,
            )
        except Exception as exc:
            logger.warning("refresh brief LLM: %s", exc)
            continue
        if sb is not None:
            try:
                sb.table("phare_content_refresh").insert({
                    "site_id": site_id,
                    "page_path": c["path"],
                    "clicks_now": c["clicks_now"],
                    "clicks_peak": c["clicks_peak"],
                    "decline_pct": c["decline_pct"],
                    "refresh_score": c["refresh_score"],
                    "proposed_changes_md": _format_brief_md(brief),
                }).execute()
            except Exception as exc:
                logger.warning("content_refresh insert: %s", exc)
        repo.insert_action({
            "site_id": site_id,
            "agent": "refresh",
            "kind": "recommandation",
            "title": (f"Refresh : {c['path']} "
                      f"({c['decline_pct']:.0f}% vs pic)"),
            "detail_md": _format_brief_md(brief),
            "status": "draft",
            "impact": 4, "effort": 3,
        })
        created += 1
    return {"ok": True, "candidates": len(cases),
            "actions_created": created}


def _format_brief_md(brief: dict) -> str:
    lines = []
    if brief.get("sections_to_enrich"):
        lines.append("**Sections à enrichir** :")
        for s in brief["sections_to_enrich"]:
            lines.append(f"- *{s.get('h2')}* — {s.get('what_to_add')}")
        lines.append("")
    if brief.get("stats_to_refresh"):
        lines.append("**Stats à mettre à jour** :")
        for s in brief["stats_to_refresh"]:
            lines.append(f"- {s}")
        lines.append("")
    if brief.get("internal_links_to_add"):
        lines.append("**Liens internes à ajouter** :")
        for l in brief["internal_links_to_add"]:
            lines.append(f"- {l}")
        lines.append("")
    if brief.get("new_h2_section"):
        nh = brief["new_h2_section"]
        lines.append(f"**Nouvelle section H2** : {nh.get('title')}")
        lines.append(f"  {nh.get('outline')}")
    return "\n".join(lines)
