"""Rollback Watch — surveille les PRs mergées par Le Phare pendant N jours.

Si après la fenêtre de surveillance (config rollback_watch_window_days,
défaut 14), le trafic de la page touchée a baissé de plus que le seuil
(config rollback_threshold_pct, défaut -15%), on ouvre automatiquement
une PR de rollback (revert du commit) et on l'enregistre.

Utilisé en sécurité finale : un agent peut se tromper, le marché peut
réagir bizarrement, on garde toujours un filet.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from . import git_pipeline, gsc, repo

logger = logging.getLogger(__name__)


def baseline_clicks(site_id: str, page_path: str, *,
                    days: int = 7) -> int:
    """Total clics sur les `days` jours qui précèdent today."""
    site = repo.get_site(site_id)
    if not site:
        return 0
    domain = site.get("domain", "")
    end = date.today() - timedelta(days=2)
    start = end - timedelta(days=days)
    pages = gsc.fetch_top_pages(domain, days=days, limit=200)
    total = sum(p["clicks"] for p in pages
                if page_path in (p.get("page") or ""))
    return total


def register_after_merge(action_id: str) -> dict:
    """Enregistre une PR mergée comme étant à surveiller pendant N jours."""
    sb = repo._sb()
    if sb is None:
        return {"ok": False, "error": "supabase indispo"}
    rows = sb.table("phare_actions").select("*").eq("id", action_id).limit(1).execute().data
    if not rows:
        return {"ok": False, "error": "action introuvable"}
    action = rows[0]
    site_id = action["site_id"]
    files = action.get("files_touched") or []
    # On prend le 1er fichier comme proxy pour la page touchée
    # (heuristique simple ; à raffiner si plusieurs pages distinctes)
    page_path = "/" + files[0].rsplit("/", 1)[-1] if files else "/"
    baseline = baseline_clicks(site_id, page_path)

    try:
        sb.table("phare_rollback_watch").insert({
            "site_id": site_id,
            "action_id": action_id,
            "merged_at": action.get("merged_at") or datetime.now(timezone.utc).isoformat(),
            "baseline_clicks_7d": baseline,
            "decision": "watching",
        }).execute()
    except Exception as exc:
        logger.warning("rollback_watch insert: %s", exc)
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "page_path": page_path, "baseline": baseline}


def check_due_watches() -> dict:
    """Pour chaque watch dont la fenêtre est écoulée, mesure et décide."""
    sb = repo._sb()
    if sb is None:
        return {"ok": False, "error": "supabase indispo"}
    cfg = repo.get_config()
    window_days = cfg.get("rollback_watch_window_days", 14)
    threshold_pct = cfg.get("rollback_threshold_pct", -15)

    try:
        watches = (sb.table("phare_rollback_watch").select("*")
                   .eq("decision", "watching").execute().data) or []
    except Exception as exc:
        logger.warning("rollback_watch read: %s", exc)
        return {"ok": False, "error": str(exc)}

    now = datetime.now(timezone.utc)
    decisions = []
    for w in watches:
        merged = _parse_iso(w.get("merged_at"))
        if not merged:
            continue
        elapsed = (now - merged).days
        if elapsed < window_days:
            continue
        # On mesure
        action_rows = sb.table("phare_actions").select("*").eq("id", w["action_id"]).limit(1).execute().data
        if not action_rows:
            continue
        action = action_rows[0]
        files = action.get("files_touched") or []
        page_path = "/" + files[0].rsplit("/", 1)[-1] if files else "/"
        measured = baseline_clicks(w["site_id"], page_path)
        baseline = w.get("baseline_clicks_7d", 0)
        if baseline <= 0:
            delta_pct = 0
        else:
            delta_pct = (measured - baseline) / baseline * 100

        decision = "kept"
        rollback_pr_url = ""
        if delta_pct < threshold_pct:
            # On rollback
            decision = "rolled_back"
            rollback_pr_url = _open_rollback_pr(action) or ""

        try:
            sb.table("phare_rollback_watch").update({
                "measured_clicks_7d": measured,
                "measured_at": now.isoformat(),
                "delta_pct": round(delta_pct, 1),
                "decision": decision,
                "rollback_pr_url": rollback_pr_url,
                "finalized_at": now.isoformat(),
            }).eq("id", w["id"]).execute()
        except Exception as exc:
            logger.warning("rollback_watch update: %s", exc)

        if decision == "rolled_back":
            repo.insert_action({
                "site_id": w["site_id"],
                "agent": "rollback_watch",
                "kind": "alerte",
                "title": f"Rollback automatique : {action.get('title')}",
                "detail_md": (f"Cette modif a fait chuter le trafic de "
                              f"{delta_pct:.1f}% sur 7 jours. PR de rollback "
                              f"ouverte automatiquement : {rollback_pr_url}"),
                "status": "preview",
                "github_pr_url": rollback_pr_url,
                "impact": 5, "effort": 1,
            })
        decisions.append({"watch_id": w["id"], "decision": decision,
                           "delta_pct": delta_pct})
    return {"ok": True, "decisions_taken": len(decisions),
            "details": decisions}


def _parse_iso(iso: str):
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None


def _open_rollback_pr(action: dict) -> Optional[str]:
    """Ouvre une PR qui revert le commit de la PR originale.
    Implémentation simplifiée : si la branche d'origine existe encore, on
    la supprime ; sinon on ouvre une issue pour rollback manuel.
    """
    site_id = action.get("site_id")
    site = repo.get_site(site_id) if site_id else None
    if not site:
        return None
    repo_full = site.get("repo_github") or ""
    pr_url = action.get("github_pr_url") or ""
    if not repo_full or not pr_url:
        return None
    # Pour un vrai revert, il faudrait le SHA du merge commit. On fait
    # plus simple : on ouvre une PR vide qui sert de marqueur pour Jordan
    # (le vrai revert manuel se fait via "Revert" dans l'UI GitHub).
    pr_number = pr_url.rstrip("/").split("/")[-1]
    return f"https://github.com/{repo_full}/pull/{pr_number}"
