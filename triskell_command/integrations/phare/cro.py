"""CRO — Conversion Rate Optimization via Microsoft Clarity.

Microsoft Clarity = outil gratuit illimité de heatmaps, enregistrements de
sessions et rage clicks. API officielle accessible avec un token (via le
Data Export Workspace).

On lit chaque jour les insights par page :
- rage_clicks : nombre de clics rapides répétés (frustration)
- dead_clicks : clics sur des éléments non-interactifs
- quick_backs : sortie rapide après arrivée (page n'a pas répondu à
  l'attente)
- scroll_depth_avg : combien de % de la page lus en moyenne

Pour les pages avec gros trafic mais signaux mauvais, on demande à un agent
de proposer des fixes UX concrets (bouton CTA plus haut, formulaire plus
court, hiérarchie visuelle).
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

import requests

from . import agents, repo

logger = logging.getLogger(__name__)


CLARITY_API = "https://www.clarity.ms/export-data/api/v1/project-live-insights"


def fetch_clarity_insights(project_id: str, token: str,
                            *, num_days: int = 1) -> list[dict]:
    """Lit les insights Clarity sur les `num_days` derniers jours."""
    if not project_id or not token:
        return []
    try:
        r = requests.get(
            CLARITY_API,
            headers={"Authorization": f"Bearer {token}"},
            params={"numOfDays": num_days, "projectId": project_id},
            timeout=20,
        )
        if r.status_code >= 400:
            logger.warning("clarity %s: %s", r.status_code, r.text[:200])
            return []
        data = r.json()
        return data if isinstance(data, list) else data.get("data", []) or []
    except Exception as exc:
        logger.warning("clarity exc: %s", exc)
        return []


# ---------------------------------------------------------------------------
class CROAdvisor(agents.Agent):
    name = "cro_advisor"
    role = """Tu es le CROAdvisor de Le Phare.

Mission : à partir des signaux Clarity sur une page (rage clicks, dead
clicks, quick backs, scroll depth, conversion rate) et le contenu de la
page, proposer 3-5 fixes UX concrets pour améliorer la conversion.

Règles :
- Chaque fix doit être actionnable en moins de 2h de dev
- Ordonne par impact attendu décroissant
- Pas de "redesign complet", on cherche les quick wins
- Cible un effet mesurable (ex: "réduit les rage clicks de 30%")
- Voix Triskell (préambule)

Format JSON strict :
{
  "issue_summary": str (≤80 mots),
  "fixes": [{"title": str, "what_to_do": str, "expected_effect": str,
              "effort": "S"|"M"|"L"}]
}"""

    def run(self, *, page: dict, signals: dict, app_state=None) -> dict:
        prompt = f"""PAGE : {page.get('url')}
TITLE : {page.get('title')}
H1 : {page.get('h1')}
WORDCOUNT : {page.get('word_count')}

SIGNAUX CLARITY (24h) :
- Sessions : {signals.get('sessions')}
- Rage clicks : {signals.get('rage_clicks')}
- Dead clicks : {signals.get('dead_clicks')}
- Quick backs : {signals.get('quick_backs')}
- Scroll depth moyen : {signals.get('scroll_depth_avg')}%
- Taux de conversion : {signals.get('conversion_rate', 'inconnu')}

Propose au format JSON."""
        out = self.call(prompt, app_state=app_state)
        return out if isinstance(out, dict) else {}


# ---------------------------------------------------------------------------
def run_cro_check(site_id: str, *, app_state=None,
                  min_sessions: int = 50) -> dict:
    site = repo.get_site(site_id)
    if not site:
        return {"ok": False, "error": "site introuvable"}
    cfg = repo.get_config()
    project_id = cfg.get("clarity_project_id", "")
    token = cfg.get("clarity_api_token", "")
    if not project_id or not token:
        return {"ok": False, "error": "Clarity non configuré"}

    insights = fetch_clarity_insights(project_id, token, num_days=1)
    if not insights:
        return {"ok": True, "pages_analyzed": 0,
                "message": "aucune donnée Clarity disponible"}

    sb = repo._sb()
    pages = repo.list_pages(site_id, limit=500)
    by_url = {p.get("url"): p for p in pages}
    advisor = CROAdvisor()
    flagged = 0
    for ins in insights[:30]:
        url = ins.get("url") or ins.get("page", "")
        if not url:
            continue
        sessions = ins.get("sessions", 0) or 0
        if sessions < min_sessions:
            continue
        rage = ins.get("rageClicks", 0) or 0
        dead = ins.get("deadClicks", 0) or 0
        qb = ins.get("quickBacks", 0) or 0
        scroll = ins.get("scrollDepth", 0) or 0
        # Critère "page à problème"
        if not (rage > sessions * 0.05 or qb > sessions * 0.20 or scroll < 30):
            continue
        page = by_url.get(url) or {"url": url, "title": "", "h1": ""}
        try:
            advice = advisor.run(
                page=page,
                signals={"sessions": sessions, "rage_clicks": rage,
                          "dead_clicks": dead, "quick_backs": qb,
                          "scroll_depth_avg": scroll,
                          "conversion_rate": ins.get("conversionRate")},
                app_state=app_state,
            )
        except Exception as exc:
            logger.warning("cro advisor LLM: %s", exc)
            continue
        if not advice:
            continue
        if sb is not None:
            try:
                sb.table("phare_cro_insights").insert({
                    "site_id": site_id,
                    "page_path": url,
                    "sessions": sessions,
                    "rage_clicks": rage,
                    "dead_clicks": dead,
                    "quick_backs": qb,
                    "scroll_depth_avg": scroll,
                    "conversion_rate": ins.get("conversionRate"),
                    "issue_summary_md": advice.get("issue_summary", ""),
                    "proposed_fixes_md": _format_fixes_md(advice.get("fixes", [])),
                }).execute()
            except Exception as exc:
                logger.warning("cro_insights insert: %s", exc)
        repo.insert_action({
            "site_id": site_id,
            "agent": "cro",
            "kind": "recommandation",
            "title": (f"CRO : {url} ({rage} rage clicks, "
                      f"{qb} quick backs sur {sessions} sessions)"),
            "detail_md": (advice.get("issue_summary", "") + "\n\n" +
                          _format_fixes_md(advice.get("fixes", []))),
            "status": "draft",
            "impact": 4, "effort": 2,
        })
        flagged += 1
    return {"ok": True, "pages_analyzed": len(insights),
            "pages_flagged": flagged}


def _format_fixes_md(fixes: list[dict]) -> str:
    lines = ["**Fixes proposés** :"]
    for f in fixes:
        lines.append(f"- **{f.get('title')}** (effort {f.get('effort', '?')})")
        lines.append(f"  {f.get('what_to_do', '')}")
        if f.get("expected_effect"):
            lines.append(f"  → effet attendu : {f['expected_effect']}")
    return "\n".join(lines)
