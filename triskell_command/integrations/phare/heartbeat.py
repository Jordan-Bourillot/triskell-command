"""Battement de cœur du Phare — rend la panne du scheduler VISIBLE.

Le scheduler du Phare tourne sur GitHub Actions (un process neuf par heure),
pas sur le serveur. Conséquence avant ce module : quand les ticks échouaient
(ex. panne d'accès base du 09-10/06/2026), AUCUN robot serveur n'était en
panne, la page Santé restait verte, et personne n'alertait Jordan.

Désormais :
  - chaque tick réussi écrit `last_tick_at` (+ un mini-résumé) dans
    shared_settings.phare_config — voir scheduler._tick ;
  - le serveur expose un « robot virtuel » construit par virtual_worker(),
    intégré à system_health() donc surveillé par worker_watchdog comme
    n'importe quel robot (alerte push si silence trop long).

Seuils : le cron ne passe plus que 3 fois par jour (08:23/14:23/18:23 UTC,
trou nocturne ~14 h) et GitHub Actions est très élastique (retards de
plusieurs heures observés) → 20 h de silence sur le battement fin avant
alerte. Tant que le
battement n'a jamais été posé (vieux scheduler pas encore déployé), on
retombe sur les dates jour du scheduler_log avec un seuil de 54 h
(= la dernière mission globale date d'avant-hier ou plus → panne sûre).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Silence toléré avant alerte (voir docstring pour la justification).
# Depuis le 22/06/2026 le cron est réduit à 3 passages/jour (08:23, 14:23,
# 18:23 UTC) : le trou nocturne fait ~14 h → un seuil sous 14 h déclenchait
# une fausse alerte « en panne » chaque nuit + un « rétabli » chaque matin.
# On ajoute la vraie élasticité des crons GitHub (départs vus 4-5 h en
# retard) + la durée du tick : 14 + 5 + marge ≈ 20 h. La panne multi-jours
# reste couverte par le fallback daylog (54 h).
STALE_HOURS_FINE = 20.0     # battement fin (trou nocturne 14 h + retards GitHub)
STALE_HOURS_DAYLOG = 54.0   # fallback sur les dates jour de scheduler_log

WORKER_NAME = "phare_scheduler"
WORKER_LABEL = "Le Phare — SEO (tick GitHub horaire)"


def beat(actions_count: int = 0) -> None:
    """Écrit le battement du tick dans phare_config. Best-effort, jamais bloquant."""
    try:
        from . import repo
        now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
        repo.update_config({
            "last_tick_at": now_iso,
            "last_tick_actions": int(actions_count),
        })
    except Exception as exc:
        logger.debug("phare heartbeat beat: %s", exc)


def _hours_since(iso_ts: str, now: datetime) -> float | None:
    if not iso_ts:
        return None
    try:
        ts = datetime.fromisoformat(str(iso_ts).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (now - ts).total_seconds() / 3600.0
    except Exception:
        return None


def evaluate(cfg: dict, now: datetime | None = None) -> dict | None:
    """Construit le pseudo-robot à partir d'une config DÉJÀ chargée.

    Fonction pure (testable sans réseau). Renvoie None si le Phare ne doit
    pas apparaître dans la santé (config absente = base inaccessible :
    d'autres signaux couvrent déjà ce cas, on évite la double alerte).
    """
    if not isinstance(cfg, dict) or not cfg:
        return None
    now = now or datetime.now(timezone.utc)

    if not cfg.get("enabled", True):
        # Désactivé volontairement → visible mais jamais alerté
        # (skipped_reason "disabled" est ignoré par worker_watchdog).
        return {
            "name": WORKER_NAME, "label": WORKER_LABEL,
            "running": False, "last_run_at": str(cfg.get("last_tick_at") or ""),
            "last_run_result": {"skipped_reason": "disabled"},
            "health": "healthy",
        }

    last_tick = str(cfg.get("last_tick_at") or "")
    age_h = _hours_since(last_tick, now)
    if age_h is not None:
        stale_after = STALE_HOURS_FINE
        last_signal = last_tick
    else:
        # Battement jamais posé → fallback : la plus récente date jour
        # des missions globales (algo_watch/ab_record tournent chaque jour).
        log = cfg.get("scheduler_log") or {}
        days = [str(v) for v in log.values() if v]
        last_day = max(days) if days else ""
        last_signal = last_day
        age_h = _hours_since(f"{last_day}T00:00:00+00:00", now) if last_day else None
        stale_after = STALE_HOURS_DAYLOG

    if age_h is None:
        # Aucun signal du tout : Phare jamais lancé → information, pas panne.
        return {
            "name": WORKER_NAME, "label": WORKER_LABEL,
            "running": False, "last_run_at": "",
            "last_run_result": {"skipped_reason": "disabled"},
            "health": "healthy",
        }

    silent = age_h > stale_after
    result: dict = {"actions": cfg.get("last_tick_actions", 0)}
    if silent:
        result["error"] = (
            f"aucun tick GitHub Actions depuis {age_h:.0f} h "
            "(vérifier l'onglet Actions du dépôt triskell-command)"
        )
    return {
        "name": WORKER_NAME, "label": WORKER_LABEL,
        "running": not silent,
        "last_run_at": last_signal,
        "last_run_result": result,
        "health": "healthy" if not silent else "error",
        # Lu par worker_watchdog.diagnose_workers : silence toléré avant
        # « muet depuis X h » (le cron GitHub saute des heures la nuit).
        "stale_after_hours": stale_after,
    }


def virtual_worker(now: datetime | None = None) -> dict | None:
    """Charge la config Phare et renvoie le pseudo-robot (ou None)."""
    try:
        from . import repo
        cfg = repo.get_config()
    except Exception as exc:
        logger.debug("phare heartbeat virtual_worker: %s", exc)
        return None
    return evaluate(cfg, now=now)
