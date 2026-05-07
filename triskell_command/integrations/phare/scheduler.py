"""Scheduler Le Phare — worker thread daemon qui orchestre les missions.

Pattern aligné sur drip_runner.py et reply_responder.py existants : un thread
daemon, un cycle d'1h, lecture de la config dans shared_settings.phare_config
pour décider quelles missions lancer.

Cron logique simplifié (vu qu'on tourne toutes les heures) :
- Audit hebdo : 1 site par heure le lundi 6h-22h, sinon en arrière-plan
  (max 1/jour/site)
- Veille mots-clés : lundi+jeudi 7h
- Maillage : lundi 9h
- Bulletin Analyste : tous les jours 8h
- Plan stratégique Opus : 1er du mois 9h

Ne tourne PAS quand l'utilisateur n'est pas authentifié à Supabase
(sinon rien à persister). Auto-restart si plante.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import date, datetime
from typing import Optional

from . import orchestrator, repo

logger = logging.getLogger(__name__)


CYCLE_INTERVAL_SECONDS = 60 * 60        # 1 h
INITIAL_DELAY_SECONDS = 120              # 2 min après boot

_WORKER_THREAD: Optional[threading.Thread] = None
_WORKER_STOP = threading.Event()
_WORKER_LOCK = threading.Lock()
_LAST_RUN_AT: str = ""
_LAST_RUN_RESULT: dict = {}
_LAST_RUNS_BY_MISSION: dict[str, str] = {}   # mission_key → ISO date


def start_worker(app_state) -> bool:
    """Démarre le worker en thread daemon (idempotent)."""
    global _WORKER_THREAD
    with _WORKER_LOCK:
        if _WORKER_THREAD is not None and _WORKER_THREAD.is_alive():
            return True
        _WORKER_STOP.clear()
        t = threading.Thread(target=_loop, args=(app_state,),
                              name="PhareScheduler", daemon=True)
        t.start()
        _WORKER_THREAD = t
    return True


def stop_worker() -> None:
    _WORKER_STOP.set()


def get_status() -> dict:
    return {
        "running": _WORKER_THREAD is not None and _WORKER_THREAD.is_alive(),
        "last_run_at": _LAST_RUN_AT,
        "last_run_result": dict(_LAST_RUN_RESULT),
        "last_runs_by_mission": dict(_LAST_RUNS_BY_MISSION),
    }


# ---------------------------------------------------------------------------
def _loop(app_state) -> None:
    global _LAST_RUN_AT, _LAST_RUN_RESULT
    if _WORKER_STOP.wait(INITIAL_DELAY_SECONDS):
        return
    while not _WORKER_STOP.is_set():
        try:
            result = _tick(app_state)
            _LAST_RUN_AT = datetime.now().isoformat(timespec="seconds")
            _LAST_RUN_RESULT = result
            try:
                from .. import pulse_bus
                actions = (result.get("actions_done") or []
                           if isinstance(result, dict) else [])
                if actions:
                    n = len(actions)
                    last = actions[-1]
                    mission = last.get("mission", "?")
                    site = last.get("site", "")
                    suffix = f" sur {site}" if site else ""
                    if n == 1:
                        text = f"{mission}{suffix}"
                    else:
                        text = f"{n} missions ({mission}{suffix} en dernière)"
                    pulse_bus.report(
                        "phare", "active",
                        text=text,
                        relative_time="à l'instant",
                    )
            except Exception:
                pass
        except Exception as exc:
            logger.exception("phare scheduler tick: %s", exc)
            _LAST_RUN_RESULT = {"error": str(exc)}
            try:
                from .. import pulse_bus
                pulse_bus.report("phare", "error", error=str(exc))
            except Exception:
                pass
        if _WORKER_STOP.wait(CYCLE_INTERVAL_SECONDS):
            return


def _tick(app_state) -> dict:
    """Un cycle : lit la config, décide quoi lancer, persiste."""
    cfg = repo.get_config()
    if not cfg:
        return {"skipped": "supabase_or_config_missing"}

    enabled = cfg.get("enabled", True)
    if not enabled:
        return {"skipped": "scheduler_disabled"}

    today = date.today()
    now = datetime.now()
    weekday = today.weekday()   # 0 = lundi
    hour = now.hour

    sites = repo.list_sites()
    if not sites:
        return {"skipped": "no_sites"}

    actions_done: list[dict] = []

    # Audit hebdo : 1 site / heure le lundi 6-22h
    if weekday == 0 and 6 <= hour <= 22:
        target = _pick_next_for_mission("audit", sites)
        if target:
            r = orchestrator.run_audit(target["id"], app_state=app_state)
            actions_done.append({"mission": "audit", "site": target["domain"], **r})
            _LAST_RUNS_BY_MISSION[f"audit:{target['id']}"] = today.isoformat()

    # Veille mots-clés : lundi & jeudi 7h
    if weekday in (0, 3) and hour == 7:
        target = _pick_next_for_mission("keywords", sites)
        if target:
            r = orchestrator.run_keywords(target["id"], app_state=app_state)
            actions_done.append({"mission": "keywords", "site": target["domain"], **r})
            _LAST_RUNS_BY_MISSION[f"keywords:{target['id']}"] = today.isoformat()

    # Maillage : lundi 9h
    if weekday == 0 and hour == 9:
        target = _pick_next_for_mission("tisseur", sites)
        if target:
            r = orchestrator.run_tisseur(target["id"], app_state=app_state)
            actions_done.append({"mission": "tisseur", "site": target["domain"], **r})
            _LAST_RUNS_BY_MISSION[f"tisseur:{target['id']}"] = today.isoformat()

    # Bulletin Analyste : tous les jours 8h sur le top 3
    if hour == 8:
        for s in sites[:3]:
            r = orchestrator.run_analyst(s["id"], app_state=app_state)
            actions_done.append({"mission": "analyst", "site": s["domain"], **r})
            _LAST_RUNS_BY_MISSION[f"analyst:{s['id']}"] = today.isoformat()

    # Optimisation on-page : mardi/mercredi/vendredi 10h, 1 page par site
    # prioritaire (la home par défaut, ou la page la moins optimisée si on
    # a un score). 1 site/cycle pour ne pas saturer.
    if weekday in (1, 2, 4) and hour == 10:
        target = _pick_next_for_mission("optim_onpage", sites)
        if target:
            page_path = _pick_page_to_optimize(target["id"])
            r = orchestrator.run_onpage_optim(
                target["id"], page_path=page_path,
                auto_open_pr=True, app_state=app_state,
            )
            actions_done.append({"mission": "optim_onpage",
                                  "site": target["domain"],
                                  "page": page_path, **r})
            _LAST_RUNS_BY_MISSION[f"optim_onpage:{target['id']}"] = today.isoformat()

    # Plan stratégique Opus : 1er du mois 9h
    if today.day == 1 and hour == 9:
        last = _LAST_RUNS_BY_MISSION.get("strategy:")
        if last != today.isoformat():
            r = orchestrator.run_strategy(app_state=app_state)
            actions_done.append({"mission": "strategy", **r})
            _LAST_RUNS_BY_MISSION["strategy:"] = today.isoformat()

    # ---- Missions avancées v0.5 ----
    # CTR optim : mardi 11h, 1 site
    if weekday == 1 and hour == 11:
        target = _pick_next_for_mission("ctr_optim", sites)
        if target:
            r = run_now("ctr_optim", target["id"], app_state=app_state)
            actions_done.append({"mission": "ctr_optim",
                                  "site": target["domain"], **r})
            _LAST_RUNS_BY_MISSION[f"ctr_optim:{target['id']}"] = today.isoformat()

    # Snippet hunt : mercredi 11h, 1 site
    if weekday == 2 and hour == 11:
        target = _pick_next_for_mission("snippet_hunt", sites)
        if target:
            r = run_now("snippet_hunt", target["id"], app_state=app_state)
            actions_done.append({"mission": "snippet_hunt",
                                  "site": target["domain"], **r})
            _LAST_RUNS_BY_MISSION[f"snippet_hunt:{target['id']}"] = today.isoformat()

    # GEO check (LLM mentions) : jeudi 11h, 1 site
    if weekday == 3 and hour == 11:
        target = _pick_next_for_mission("geo_check", sites)
        if target:
            r = run_now("geo_check", target["id"], app_state=app_state)
            actions_done.append({"mission": "geo_check",
                                  "site": target["domain"], **r})
            _LAST_RUNS_BY_MISSION[f"geo_check:{target['id']}"] = today.isoformat()

    # Cannibalisation + zombies : vendredi 11h, 1 site (les deux d'affilée)
    if weekday == 4 and hour == 11:
        target = _pick_next_for_mission("cannibalization", sites)
        if target:
            r1 = run_now("cannibalization", target["id"], app_state=app_state)
            r2 = run_now("zombies", target["id"], app_state=app_state)
            actions_done.append({"mission": "cannib+zombies",
                                  "site": target["domain"],
                                  "cannib": r1, "zombies": r2})
            _LAST_RUNS_BY_MISSION[f"cannibalization:{target['id']}"] = today.isoformat()

    # Image SEO : samedi 9h, 1 site
    if weekday == 5 and hour == 9:
        target = _pick_next_for_mission("image_seo", sites)
        if target:
            r = run_now("image_seo", target["id"], app_state=app_state)
            actions_done.append({"mission": "image_seo",
                                  "site": target["domain"], **r})
            _LAST_RUNS_BY_MISSION[f"image_seo:{target['id']}"] = today.isoformat()

    # Refresh content : dimanche 9h, 1 site (top priorité)
    if weekday == 6 and hour == 9:
        target = _pick_next_for_mission("refresh", sites)
        if target:
            r = run_now("refresh", target["id"], app_state=app_state)
            actions_done.append({"mission": "refresh",
                                  "site": target["domain"], **r})
            _LAST_RUNS_BY_MISSION[f"refresh:{target['id']}"] = today.isoformat()

    # Suivi concurrents : tous les jours à 12h, top 3 sites
    if hour == 12:
        for s in sites[:3]:
            r = run_now("competitors", s["id"], app_state=app_state)
            actions_done.append({"mission": "competitors",
                                  "site": s["domain"], **r})

    # Rollback check : tous les jours à 13h
    if hour == 13:
        r = run_now("rollback_check", None, app_state=app_state)
        actions_done.append({"mission": "rollback_check", **r})

    # Sitemap + IndexNow : lundi 14h, top 3 sites
    if weekday == 0 and hour == 14:
        for s in sites[:3]:
            r = run_now("sitemap", s["id"], app_state=app_state)
            actions_done.append({"mission": "sitemap",
                                  "site": s["domain"], **r})

    # ---- Missions pro v0.6 ----
    # Veille algo Google : tous les jours 6h
    if hour == 6:
        r = run_now("algo_watch", None, app_state=app_state)
        actions_done.append({"mission": "algo_watch", **r})

    # A/B test measurements : tous les jours 7h
    if hour == 7:
        r = run_now("ab_record", None, app_state=app_state)
        actions_done.append({"mission": "ab_record", **r})

    # Brand monitoring : mardi 9h, 1 site
    if weekday == 1 and hour == 9:
        target = _pick_next_for_mission("brand_scan", sites)
        if target:
            r = run_now("brand_scan", target["id"], app_state=app_state)
            actions_done.append({"mission": "brand_scan",
                                  "site": target["domain"], **r})
            _LAST_RUNS_BY_MISSION[f"brand_scan:{target['id']}"] = today.isoformat()

    # Outreach drafts : mercredi 9h, 1 site
    if weekday == 2 and hour == 9:
        target = _pick_next_for_mission("outreach_drafts", sites)
        if target:
            r = run_now("outreach_drafts", target["id"], app_state=app_state)
            actions_done.append({"mission": "outreach_drafts",
                                  "site": target["domain"], **r})
            _LAST_RUNS_BY_MISSION[f"outreach_drafts:{target['id']}"] = today.isoformat()

    # Outreach follow-ups : tous les jours 10h
    if hour == 10:
        r = run_now("outreach_followups", None, app_state=app_state)
        actions_done.append({"mission": "outreach_followups", **r})

    # Local SEO : jeudi 9h, 1 site (s'il a un place_id)
    if weekday == 3 and hour == 9:
        cfg = repo.get_config()
        gbp_map = cfg.get("gbp_place_ids", {}) or {}
        for s in sites:
            if s["id"] in gbp_map:
                r = run_now("local_seo", s["id"], app_state=app_state)
                actions_done.append({"mission": "local_seo",
                                      "site": s["domain"], **r})
                break

    # CRO check (Clarity) : vendredi 9h, 1 site
    if weekday == 4 and hour == 9:
        target = _pick_next_for_mission("cro_check", sites)
        if target:
            r = run_now("cro_check", target["id"], app_state=app_state)
            actions_done.append({"mission": "cro_check",
                                  "site": target["domain"], **r})
            _LAST_RUNS_BY_MISSION[f"cro_check:{target['id']}"] = today.isoformat()

    # Bulletin PDF : 1er du mois 10h (après le plan stratégique)
    if today.day == 1 and hour == 10:
        last = _LAST_RUNS_BY_MISSION.get("bulletin_pdf:")
        if last != today.isoformat():
            r = run_now("bulletin_pdf", None, app_state=app_state)
            actions_done.append({"mission": "bulletin_pdf", **r})
            _LAST_RUNS_BY_MISSION["bulletin_pdf:"] = today.isoformat()

    return {"actions_done": actions_done,
            "sites_count": len(sites),
            "weekday": weekday, "hour": hour}


def _pick_next_for_mission(mission: str, sites: list[dict]) -> Optional[dict]:
    """Choisit le site le plus prioritaire qui n'a pas eu cette mission aujourd'hui."""
    today_iso = date.today().isoformat()
    sorted_sites = sorted(sites, key=lambda s: -(s.get("priority") or 0))
    for s in sorted_sites:
        last = _LAST_RUNS_BY_MISSION.get(f"{mission}:{s['id']}")
        if last != today_iso:
            return s
    return None


def _pick_page_to_optimize(site_id: str) -> str:
    """Choisit la page la moins optimisée d'un site, ou '/' par défaut."""
    pages = repo.list_pages(site_id, limit=200)
    if not pages:
        return "/"
    # Page avec le plus petit optim_score (None = pas encore évaluée → priorité)
    pages_sorted = sorted(
        pages,
        key=lambda p: (p.get("optim_score") if p.get("optim_score") is not None
                       else -1, p.get("path") or "")
    )
    return pages_sorted[0].get("path") or "/"


# ---------------------------------------------------------------------------
# Helpers de déclenchement manuel (utilisés par l'UI)
# ---------------------------------------------------------------------------
def run_now(mission: str, site_id: Optional[str] = None,
            *, app_state=None) -> dict:
    """Déclenche immédiatement une mission donnée (ou audit complet d'un site)."""
    if mission == "full_cycle":
        if not site_id:
            return {"ok": False, "error": "site_id requis"}
        return orchestrator.run_full_cycle(site_id, app_state=app_state)
    if mission == "audit":
        return orchestrator.run_audit(site_id, app_state=app_state)
    if mission == "keywords":
        return orchestrator.run_keywords(site_id, app_state=app_state)
    if mission == "tisseur":
        return orchestrator.run_tisseur(site_id, app_state=app_state)
    if mission == "analyst":
        return orchestrator.run_analyst(site_id, app_state=app_state)
    if mission == "backlinks":
        return orchestrator.run_backlinks(site_id, app_state=app_state)
    if mission == "strategy":
        return orchestrator.run_strategy(app_state=app_state)
    if mission == "optim_onpage":
        if not site_id:
            return {"ok": False, "error": "site_id requis"}
        page_path = _pick_page_to_optimize(site_id)
        return orchestrator.run_onpage_optim(
            site_id, page_path=page_path, auto_open_pr=True,
            app_state=app_state,
        )
    # ---- Missions avancées (v0.5) ----
    if mission == "ctr_optim":
        from . import ctr_hacker
        return ctr_hacker.run_ctr_optim(site_id, app_state=app_state)
    if mission == "snippet_hunt":
        from . import snippet_hunter
        return snippet_hunter.hunt_snippets(site_id, app_state=app_state)
    if mission == "geo_check":
        from . import geo_surveillant
        return geo_surveillant.run_geo_check(site_id, app_state=app_state)
    if mission == "cannibalization":
        from . import cannibalization
        return cannibalization.run_cannibalization(site_id, app_state=app_state)
    if mission == "zombies":
        from . import zombies
        return zombies.run_zombies(site_id, app_state=app_state)
    if mission == "image_seo":
        from . import image_seo
        return image_seo.run_image_seo(site_id, app_state=app_state)
    if mission == "refresh":
        from . import refresh
        return refresh.run_refresh(site_id, app_state=app_state)
    if mission == "sitemap":
        from . import sitemap
        return sitemap.run_sitemap(site_id, app_state=app_state)
    if mission == "competitors":
        from . import competitors
        return competitors.track_positions(site_id, app_state=app_state)
    if mission == "rollback_check":
        from . import rollback_watch
        return rollback_watch.check_due_watches()
    # ---- Missions pro (v0.6) ----
    if mission == "outreach_drafts":
        from . import outreach
        return outreach.queue_drafts(site_id, app_state=app_state)
    if mission == "outreach_followups":
        from . import outreach
        return outreach.process_due_follow_ups(app_state=app_state)
    if mission == "ab_record":
        from . import ab_test
        return ab_test.record_measurements(app_state=app_state)
    if mission == "brand_scan":
        from . import brand_monitoring
        return brand_monitoring.scan(site_id, app_state=app_state)
    if mission == "local_seo":
        from . import local_seo
        return local_seo.run_local_check(site_id, app_state=app_state)
    if mission == "cro_check":
        from . import cro
        return cro.run_cro_check(site_id, app_state=app_state)
    if mission == "algo_watch":
        from . import algo_watch
        return algo_watch.run_algo_watch(app_state=app_state)
    if mission == "bulletin_pdf":
        from . import bulletin_pdf
        return bulletin_pdf.render_pdf()
    return {"ok": False, "error": f"mission inconnue: {mission}"}
