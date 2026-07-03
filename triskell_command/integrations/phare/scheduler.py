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
- Bulletin PDF interne : 1er du mois 10h
- Envoi rapports clients SEO : 1er du mois 11h

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


def _global_ran_today(mission_key: str) -> bool:
    """Dédup pour une mission globale (pas de site). Lit dans shared_settings."""
    today_iso = date.today().isoformat()
    if _LAST_RUNS_BY_MISSION.get(mission_key) == today_iso:
        return True
    try:
        log = repo.get_config().get("scheduler_log") or {}
        return log.get(mission_key) == today_iso
    except Exception:
        return False


def _mark_ran(mission_key: str) -> None:
    """Marque une mission comme exécutée aujourd'hui (mémoire + DB)."""
    today_iso = date.today().isoformat()
    _LAST_RUNS_BY_MISSION[mission_key] = today_iso
    try:
        cfg = repo.get_config()
        log = cfg.get("scheduler_log") or {}
        if log.get(mission_key) != today_iso:
            log[mission_key] = today_iso
            # Garde uniquement les 200 dernières entrées (purge naturelle)
            if len(log) > 200:
                log = dict(sorted(log.items(), key=lambda kv: kv[1])[-200:])
            repo.update_config({"scheduler_log": log})
    except Exception as exc:
        logger.debug("_mark_ran(%s): %s", mission_key, exc)


def _tick(app_state) -> dict:
    """Un cycle : lit la config, décide quoi lancer, persiste.

    Stratégie post-fix : on utilise `hour >= X` (au lieu de `hour == X`)
    pour les fenêtres de déclenchement, et on dédoublonne via la base
    (phare_actions pour les missions par site, shared_settings.phare_config
    .scheduler_log pour les missions globales). Ça permet :
      1. de résister aux retards de GitHub Actions (cron pas garanti à l'heure)
      2. d'empêcher les doublons même quand le process redémarre
    """
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

    # « Le robot agit seul » : si l'interrupteur est allumé, on met en file les
    # corrections SÛRES en attente AVANT de vider la file, pour qu'elles soient
    # publiées dans ce même passage (Jordan n'a rien à cliquer).
    try:
        aa = orchestrator.auto_apply_safe(app_state=app_state)
        if aa.get("enqueued"):
            actions_done.append({"mission": "auto_apply",
                                 "enqueued": len(aa["enqueued"])})
    except Exception as exc:
        logger.warning("phare auto_apply: %s", exc)

    # File « OK, fais-le » : toujours en tête de cycle — un clic de Jordan
    # passe avant les missions planifiées. Le clic web déclenche aussi un
    # workflow_dispatch, donc ce passage arrive en général ~2 min après.
    try:
        from . import executor
        q = executor.process_apply_queue(app_state=app_state)
        if q.get("processed"):
            actions_done.append({"mission": "apply_queue",
                                 "site": "", **{"ok": q.get("ok", False),
                                                "processed": q["processed"]}})
    except Exception as exc:
        logger.warning("phare apply_queue: %s", exc)

    # Audit hebdo : 1 site/heure le lundi 6-22h (rotation par ancienneté)
    if weekday == 0 and 6 <= hour <= 22:
        target = _pick_next_for_audit(sites)
        if target:
            r = orchestrator.run_audit(target["id"], app_state=app_state)
            actions_done.append({"mission": "audit", "site": target["domain"], **r})
            _LAST_RUNS_BY_MISSION[f"audit:{target['id']}"] = today.isoformat()

    # Veille mots-clés : lundi & jeudi à partir de 7h
    if weekday in (0, 3) and hour >= 7:
        target = _pick_next_for_mission("keywords", sites)
        if target:
            r = orchestrator.run_keywords(target["id"], app_state=app_state)
            actions_done.append({"mission": "keywords", "site": target["domain"], **r})
            _LAST_RUNS_BY_MISSION[f"keywords:{target['id']}"] = today.isoformat()

    # Maillage : lundi à partir de 9h
    if weekday == 0 and hour >= 9:
        target = _pick_next_for_mission("tisseur", sites)
        if target:
            r = orchestrator.run_tisseur(target["id"], app_state=app_state)
            actions_done.append({"mission": "tisseur", "site": target["domain"], **r})
            _LAST_RUNS_BY_MISSION[f"tisseur:{target['id']}"] = today.isoformat()

    # Bulletin Analyste : tous les jours à partir de 8h, top 3 sites
    if hour >= 8:
        for s in sites[:3]:
            if _ran_today_in_db("analyst", s["id"]):
                continue
            if _LAST_RUNS_BY_MISSION.get(f"analyst:{s['id']}") == today.isoformat():
                continue
            r = orchestrator.run_analyst(s["id"], app_state=app_state)
            actions_done.append({"mission": "analyst", "site": s["domain"], **r})
            _LAST_RUNS_BY_MISSION[f"analyst:{s['id']}"] = today.isoformat()

    # Optimisation on-page : mardi/mercredi/vendredi à partir de 10h
    if weekday in (1, 2, 4) and hour >= 10:
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

    # Plan stratégique Opus : 1er du mois à partir de 9h
    if today.day == 1 and hour >= 9 and not _global_ran_today("strategy:"):
        r = orchestrator.run_strategy(app_state=app_state)
        actions_done.append({"mission": "strategy", **r})
        _mark_ran("strategy:")

    # ---- Missions avancées v0.5 ----
    # CTR optim : mardi à partir de 11h
    if weekday == 1 and hour >= 11:
        target = _pick_next_for_mission("ctr_optim", sites)
        if target:
            r = run_now("ctr_optim", target["id"], app_state=app_state)
            actions_done.append({"mission": "ctr_optim",
                                  "site": target["domain"], **r})
            _LAST_RUNS_BY_MISSION[f"ctr_optim:{target['id']}"] = today.isoformat()

    # Snippet hunt : mercredi à partir de 11h
    if weekday == 2 and hour >= 11:
        target = _pick_next_for_mission("snippet_hunt", sites)
        if target:
            r = run_now("snippet_hunt", target["id"], app_state=app_state)
            actions_done.append({"mission": "snippet_hunt",
                                  "site": target["domain"], **r})
            _LAST_RUNS_BY_MISSION[f"snippet_hunt:{target['id']}"] = today.isoformat()

    # GEO check (mentions LLM) : RETIRÉ le 03/07/2026. C'était une mesure
    # FANTÔME : geo_surveillant écrivait dans phare_geo_mentions, une table
    # que RIEN ne lit (aucun écran, aucun rapport — vérifié), et ses cartes
    # avaient déjà été supprimées le 18/06 à la demande de Jordan. La mesure
    # « les IA citent-elles mes sites ? » vit dans l'écran GEO (8 IA,
    # résultats affichés, auto-pilote) — mesure unique désormais. Le module
    # geo_surveillant reste importable (lancement manuel possible) mais plus
    # aucun passage automatique ne dépense d'appels IA pour un tiroir mort.

    # Cannibalisation + zombies : vendredi à partir de 11h, 1 site (les deux d'affilée)
    if weekday == 4 and hour >= 11:
        target = _pick_next_for_mission("cannibalization", sites)
        if target:
            r1 = run_now("cannibalization", target["id"], app_state=app_state)
            r2 = run_now("zombies", target["id"], app_state=app_state)
            actions_done.append({"mission": "cannib+zombies",
                                  "site": target["domain"],
                                  "cannib": r1, "zombies": r2})
            _LAST_RUNS_BY_MISSION[f"cannibalization:{target['id']}"] = today.isoformat()

    # Image SEO : samedi à partir de 9h
    if weekday == 5 and hour >= 9:
        target = _pick_next_for_mission("image_seo", sites)
        if target:
            r = run_now("image_seo", target["id"], app_state=app_state)
            actions_done.append({"mission": "image_seo",
                                  "site": target["domain"], **r})
            _LAST_RUNS_BY_MISSION[f"image_seo:{target['id']}"] = today.isoformat()

    # Étiquettes invisibles (données structurées) : samedi à partir de 10h
    if weekday == 5 and hour >= 10:
        target = _pick_next_for_mission("schema", sites)
        if target:
            r = run_now("schema", target["id"], app_state=app_state)
            actions_done.append({"mission": "schema",
                                  "site": target["domain"], **r})
            _LAST_RUNS_BY_MISSION[f"schema:{target['id']}"] = today.isoformat()

    # Refresh content : dimanche à partir de 9h
    if weekday == 6 and hour >= 9:
        target = _pick_next_for_mission("refresh", sites)
        if target:
            r = run_now("refresh", target["id"], app_state=app_state)
            actions_done.append({"mission": "refresh",
                                  "site": target["domain"], **r})
            _LAST_RUNS_BY_MISSION[f"refresh:{target['id']}"] = today.isoformat()

    # Suivi concurrents : tous les jours à partir de 12h, top 3 sites
    if hour >= 12:
        for s in sites[:3]:
            if _ran_today_in_db("competitors", s["id"]):
                continue
            if _LAST_RUNS_BY_MISSION.get(f"competitors:{s['id']}") == today.isoformat():
                continue
            r = run_now("competitors", s["id"], app_state=app_state)
            actions_done.append({"mission": "competitors",
                                  "site": s["domain"], **r})
            _LAST_RUNS_BY_MISSION[f"competitors:{s['id']}"] = today.isoformat()

    # Rollback check : tous les jours à partir de 13h (global, 1 fois/jour)
    if hour >= 13 and not _global_ran_today("rollback_check:"):
        r = run_now("rollback_check", None, app_state=app_state)
        actions_done.append({"mission": "rollback_check", **r})
        _mark_ran("rollback_check:")

    # Auto-merge des PRs vérifiées : tous les jours à partir de 15h (global).
    # Après les optims du matin (10-11h) → ~4-5 h de fenêtre de veto pour
    # Jordan, qui reçoit une push à chaque ouverture de PR. Opt-in via
    # phare_config.auto_merge_enabled (la mission sort en skipped sinon).
    if hour >= 15 and not _global_ran_today("auto_merge:"):
        r = run_now("auto_merge", None, app_state=app_state)
        actions_done.append({"mission": "auto_merge", **r})
        _mark_ran("auto_merge:")

    # Sitemap + IndexNow : lundi à partir de 14h, top 3 sites
    if weekday == 0 and hour >= 14:
        for s in sites[:3]:
            if _ran_today_in_db("sitemap", s["id"]):
                continue
            if _LAST_RUNS_BY_MISSION.get(f"sitemap:{s['id']}") == today.isoformat():
                continue
            r = run_now("sitemap", s["id"], app_state=app_state)
            actions_done.append({"mission": "sitemap",
                                  "site": s["domain"], **r})
            _LAST_RUNS_BY_MISSION[f"sitemap:{s['id']}"] = today.isoformat()

    # ---- Missions pro v0.6 ----
    # Veille algo Google : tous les jours à partir de 6h (global, 1 fois/jour)
    if hour >= 6 and not _global_ran_today("algo_watch:"):
        r = run_now("algo_watch", None, app_state=app_state)
        actions_done.append({"mission": "algo_watch", **r})
        _mark_ran("algo_watch:")

    # A/B test measurements : tous les jours à partir de 7h (global, 1 fois/jour)
    if hour >= 7 and not _global_ran_today("ab_record:"):
        r = run_now("ab_record", None, app_state=app_state)
        actions_done.append({"mission": "ab_record", **r})
        _mark_ran("ab_record:")

    # Brand monitoring : mardi à partir de 9h
    if weekday == 1 and hour >= 9:
        target = _pick_next_for_mission("brand_scan", sites)
        if target:
            r = run_now("brand_scan", target["id"], app_state=app_state)
            actions_done.append({"mission": "brand_scan",
                                  "site": target["domain"], **r})
            _LAST_RUNS_BY_MISSION[f"brand_scan:{target['id']}"] = today.isoformat()

    # Outreach drafts : mercredi à partir de 9h
    if weekday == 2 and hour >= 9:
        target = _pick_next_for_mission("outreach_drafts", sites)
        if target:
            r = run_now("outreach_drafts", target["id"], app_state=app_state)
            actions_done.append({"mission": "outreach_drafts",
                                  "site": target["domain"], **r})
            _LAST_RUNS_BY_MISSION[f"outreach_drafts:{target['id']}"] = today.isoformat()

    # Outreach follow-ups : tous les jours à partir de 10h (global, 1 fois/jour)
    if hour >= 10 and not _global_ran_today("outreach_followups:"):
        r = run_now("outreach_followups", None, app_state=app_state)
        actions_done.append({"mission": "outreach_followups", **r})
        _mark_ran("outreach_followups:")

    # Local SEO : jeudi à partir de 9h, 1 site (s'il a un place_id)
    if weekday == 3 and hour >= 9:
        cfg2 = repo.get_config()
        gbp_map = cfg2.get("gbp_place_ids", {}) or {}
        for s in sites:
            if s["id"] not in gbp_map:
                continue
            if _ran_today_in_db("local_seo", s["id"]):
                continue
            if _LAST_RUNS_BY_MISSION.get(f"local_seo:{s['id']}") == today.isoformat():
                continue
            r = run_now("local_seo", s["id"], app_state=app_state)
            actions_done.append({"mission": "local_seo",
                                  "site": s["domain"], **r})
            _LAST_RUNS_BY_MISSION[f"local_seo:{s['id']}"] = today.isoformat()
            break

    # CRO check (Clarity) : vendredi à partir de 9h
    if weekday == 4 and hour >= 9:
        target = _pick_next_for_mission("cro_check", sites)
        if target:
            r = run_now("cro_check", target["id"], app_state=app_state)
            actions_done.append({"mission": "cro_check",
                                  "site": target["domain"], **r})
            _LAST_RUNS_BY_MISSION[f"cro_check:{target['id']}"] = today.isoformat()

    # Bulletin PDF : 1er du mois à partir de 10h (global)
    if today.day == 1 and hour >= 10 and not _global_ran_today("bulletin_pdf:"):
        r = run_now("bulletin_pdf", None, app_state=app_state)
        actions_done.append({"mission": "bulletin_pdf", **r})
        _mark_ran("bulletin_pdf:")

    # Envoi rapports clients SEO : 1er du mois à partir de 11h (global)
    if today.day == 1 and hour >= 11 and not _global_ran_today("client_reports_send:"):
        r = run_now("client_reports_send", None, app_state=app_state)
        actions_done.append({"mission": "client_reports_send", **r})
        _mark_ran("client_reports_send:")

    # Récap quotidien des publications automatiques (« publié tout seul ») :
    # UN seul mail en fin de journée au lieu d'un par correction. À partir de
    # 19h (heure FR), global, 1 fois/jour. Buffer vide → aucun mail envoyé.
    if hour >= 19 and not _global_ran_today("automerge_digest:"):
        try:
            from . import notifications
            r = notifications.flush_auto_merged_digest()
            if r.get("sent"):
                actions_done.append({"mission": "automerge_digest",
                                     "count": r.get("count", 0)})
        except Exception as exc:
            logger.warning("phare automerge_digest: %s", exc)
        _mark_ran("automerge_digest:")

    # Battement de cœur : prouve que le tick a tourné même sans mission
    # lancée (sinon une panne GitHub Actions est invisible depuis le serveur).
    try:
        from . import heartbeat
        heartbeat.beat(len(actions_done))
    except Exception:
        pass

    return {"actions_done": actions_done,
            "sites_count": len(sites),
            "weekday": weekday, "hour": hour}


# Mission → nom d'agent stocké dans phare_actions.agent.
# Sert au dédoublonnage "mission déjà passée aujourd'hui sur ce site" via DB,
# pour résister aux redémarrages du worker (GitHub Actions = nouveau process
# à chaque tick, donc _LAST_RUNS_BY_MISSION en mémoire est inutile).
_MISSION_TO_AGENT: dict[str, str] = {
    "audit":              "auditeur",
    "keywords":           "veilleur",
    "tisseur":            "tisseur",
    "analyst":            "analyste",
    "optim_onpage":       "optimiseur_onpage",
    "ctr_optim":          "ctr_hacker",
    "snippet_hunt":       "snippet_hunter",
    "geo_check":          "geo_surveillant",
    "cannibalization":    "cannibalization",
    "zombies":            "zombies_hunter",
    "image_seo":          "image_seo",
    "schema":             "schema_architect",
    "refresh":            "refresh",
    "competitors":        "competitors",
    "sitemap":            "sitemap_builder",
    "brand_scan":         "brand_monitoring",
    "outreach_drafts":    "outreach",
    "local_seo":          "local_seo",
    "cro_check":          "cro",
    "rollback_check":     "rollback_watch",
    "programmatic":       "programmatic",
}


def _ran_today_in_db(mission: str, site_id: str) -> bool:
    """Vérifie en base si la mission a déjà tourné aujourd'hui sur ce site.

    Utilisé pour le dédoublonnage cross-process (GH Actions tick = nouveau
    process Python à chaque heure). On lit phare_actions filtré par agent +
    site + created_at >= aujourd'hui à 00:00.
    """
    agent = _MISSION_TO_AGENT.get(mission)
    if not agent or not site_id:
        return False
    try:
        sb = repo._sb()
        if sb is None:
            return False
        today_start = datetime.combine(date.today(), datetime.min.time()).isoformat()
        r = (sb.table("phare_actions")
             .select("id", count="exact")
             .eq("site_id", site_id)
             .eq("agent", agent)
             .gte("created_at", today_start)
             .limit(1).execute())
        return (r.count or 0) > 0
    except Exception as exc:
        logger.debug("_ran_today_in_db(%s, %s): %s", mission, site_id, exc)
        return False


def _pick_next_for_audit(sites: list[dict]) -> Optional[dict]:
    """Choisit le prochain site à auditer : jamais audité d'abord, puis le
    plus vieux dernier audit (priorité en cas d'égalité).

    Deux défauts vécus avec l'ancien tirage par priorité + dédup phare_actions :
    1. le dédup regardait phare_actions (agent=auditeur), or un audit qui ne
       produit que des doublons n'insère AUCUNE carte → le même site était
       ré-audité à chaque tick du lundi (pixel-pros ×3 le 29/06) ;
    2. avec 3 passages/jour, la priorité seule aurait re-servi les 3 mêmes
       sites chaque lundi et affamé les autres (Ingrid : rien depuis le 12/06).
    La vérité vit dans phare_audits (un audit y écrit TOUJOURS sa trace)."""
    today_iso = date.today().isoformat()
    candidates: list[tuple[str, float, dict]] = []
    for s in sites:
        if _LAST_RUNS_BY_MISSION.get(f"audit:{s['id']}") == today_iso:
            continue
        last = ""
        try:
            row = repo.latest_audit(s["id"])
            last = str((row or {}).get("ran_at") or "")
        except Exception as exc:
            logger.debug("_pick_next_for_audit(%s): %s", s.get("domain"), exc)
        if last[:10] == today_iso:
            continue  # déjà audité aujourd'hui (dédup cross-process GH Actions)
        candidates.append((last, -(s.get("priority") or 0), s))
    if not candidates:
        return None
    candidates.sort(key=lambda t: (t[0], t[1]))
    return candidates[0][2]


def _pick_next_for_mission(mission: str, sites: list[dict]) -> Optional[dict]:
    """Choisit le site le plus prioritaire qui n'a pas eu cette mission aujourd'hui.

    Combine deux sources :
      - _LAST_RUNS_BY_MISSION (mémoire process — gratuit, sert tant que le
        worker tourne en continu, ex. Triskell Command desktop)
      - phare_actions (DB) via _ran_today_in_db — survit aux redémarrages
        de process, indispensable pour GitHub Actions où chaque tick =
        nouveau process Python.
    """
    today_iso = date.today().isoformat()
    sorted_sites = sorted(sites, key=lambda s: -(s.get("priority") or 0))
    for s in sorted_sites:
        last = _LAST_RUNS_BY_MISSION.get(f"{mission}:{s['id']}")
        if last == today_iso:
            continue
        if _ran_today_in_db(mission, s["id"]):
            continue
        return s
    return None


def _pick_page_to_optimize(site_id: str) -> str:
    """Choisit la page la moins optimisée d'un site — JAMAIS l'accueil.

    Le robot ne publie jamais l'accueil tout seul (vitrine = décision de
    Jordan) : une optim d'accueil ouvre donc une PR qui ne se fusionne jamais,
    s'accumule et consomme une prévisualisation Netlify pour rien (constat
    22/06 : 18 PR « Optim on-page / » fantômes sur pixel-studio/studio-wow).
    Renvoie "" s'il n'y a aucune page hors accueil à optimiser → on saute.
    """
    pages = [p for p in repo.list_pages(site_id, limit=200)
             if (p.get("path") or "/") not in ("/", "")]
    if not pages:
        return ""
    # Page avec le plus petit optim_score (None = pas encore évaluée → priorité)
    pages_sorted = sorted(
        pages,
        key=lambda p: (p.get("optim_score") if p.get("optim_score") is not None
                       else -1, p.get("path") or "")
    )
    return pages_sorted[0].get("path") or ""


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
        if not page_path:           # que l'accueil → on ne crée pas de PR fantôme
            return {"ok": True, "skipped": "aucune page hors accueil à optimiser"}
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
    if mission == "schema":
        return orchestrator.run_schema_pass(site_id, app_state=app_state)
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
    if mission == "auto_merge":
        return orchestrator.auto_merge_verified()
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
    if mission == "client_reports_send":
        from . import client_report_sender
        return client_report_sender.send_pending_reports(app_state=app_state)
    if mission == "automerge_digest":
        from . import notifications
        return notifications.flush_auto_merged_digest()
    return {"ok": False, "error": f"mission inconnue: {mission}"}
