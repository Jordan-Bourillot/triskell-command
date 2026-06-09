"""Chien de garde des robots — alerte push quand un robot est en panne.

Le déclencheur de ce module : en juin 2026, 6 robots sur 10 sont restés en
panne PENDANT DES SEMAINES (« JWT expired ») sans que personne ne le voie.
La page Santé l'affichait… mais encore fallait-il aller la regarder.

Désormais, le serveur s'auto-surveille : toutes les 30 minutes, il passe
en revue l'état de chaque robot (la même source que la page Santé) et
envoie une notification push sur le téléphone quand quelque chose cloche :

  - robot en avertissement ou en erreur (dernier passage raté),
  - robot arrêté alors qu'il devrait tourner,
  - robot muet depuis plus de STALE_AFTER_HOURS heures.

Anti-harcèlement : une seule alerte par robot par tranche de 12 h
(cooldown persisté sur disque), et une notification de rétablissement
quand le robot re-fonctionne.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

STATE_FILE = Path.home() / ".triskell-command" / "watchdog_state.json"
COOLDOWN_HOURS = 12
STALE_AFTER_HOURS = 3.0
CHECK_INTERVAL_SEC = 1800  # 30 min
BOOT_DELAY_SEC = 600       # laisse les robots faire leur 1er passage

# Robots qui peuvent légitimement être à l'arrêt (désactivés par réglage).
# Pour eux, "running: False" n'est pas une panne ; seuls health=error/warning
# déclenchent une alerte.
OPTIONAL_WORKERS = {"autopilot_runner"}


def _load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    except Exception as exc:
        logger.debug("watchdog save state : %s", exc)


def _hours_since(iso_ts: str) -> float | None:
    if not iso_ts:
        return None
    try:
        ts = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            # Les last_run_at sont écrits naïfs avec l'heure du serveur
            # (UTC dans le conteneur) → on les interprète comme de l'UTC.
            ts = ts.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - ts).total_seconds() / 3600.0
    except Exception:
        return None


def diagnose_workers(workers: list[dict],
                     *, stale_after_hours: float = STALE_AFTER_HOURS) -> list[dict]:
    """Analyse la liste des robots (format system_health) et renvoie les
    problèmes détectés : [{name, label, problem}]. Fonction pure → testable.
    """
    problems: list[dict] = []
    for w in workers or []:
        name = w.get("name") or "?"
        label = w.get("label") or name
        health = (w.get("health") or "").lower()
        running = bool(w.get("running"))
        result = w.get("last_run_result") or {}
        skipped = (result.get("skipped_reason") or "").lower()

        # Robot volontairement désactivé / en retrait → pas une panne
        if skipped in ("disabled", "server_active"):
            continue

        if health in ("error", "warning"):
            err = ""
            if isinstance(result, dict):
                err = str(result.get("error") or "")[:140]
            problems.append({
                "name": name, "label": label,
                "problem": ("dernier passage en échec"
                            + (f" — {err}" if err else "")),
            })
            continue
        if not running and name not in OPTIONAL_WORKERS:
            problems.append({
                "name": name, "label": label,
                "problem": "robot arrêté (il devrait tourner)",
            })
            continue
        age_h = _hours_since(w.get("last_run_at") or "")
        if running and age_h is not None and age_h > stale_after_hours:
            problems.append({
                "name": name, "label": label,
                "problem": f"muet depuis {age_h:.0f} h",
            })
    return problems


def _send_push(title: str, body: str) -> bool:
    try:
        from ..web.push import send_push
        send_push(title, body, user_id="jordan", priority="high",
                  tag="watchdog", tag_group="watchdog", url="/#health")
        return True
    except Exception as exc:
        logger.warning("watchdog push KO : %s", exc)
        return False


def check_and_alert(api, *, now: datetime | None = None) -> dict:
    """Un passage de surveillance. Renvoie un résumé (pour log/tests)."""
    out = {"checked": 0, "problems": 0, "alerted": 0, "recovered": 0}
    try:
        health = api.system_health()
    except Exception as exc:
        logger.warning("watchdog: system_health KO : %s", exc)
        return out
    workers = (health or {}).get("workers") or []
    out["checked"] = len(workers)

    problems = diagnose_workers(workers)
    out["problems"] = len(problems)
    problem_names = {p["name"] for p in problems}

    state = _load_state()
    alerts = state.get("alerts", {})
    now_dt = now or datetime.now(timezone.utc)
    now_iso = now_dt.isoformat(timespec="seconds")

    # Alertes (avec cooldown 12 h par robot)
    for p in problems:
        last = alerts.get(p["name"], {}).get("at") or ""
        age_h = _hours_since(last)
        if age_h is not None and age_h < COOLDOWN_HOURS:
            continue
        ok = _send_push(
            f"⚠️ Robot en panne : {p['label']}",
            f"{p['problem']}. Détails dans Système → Santé.",
        )
        if ok:
            alerts[p["name"]] = {"at": now_iso, "problem": p["problem"]}
            out["alerted"] += 1

    # Rétablissements : un robot alerté qui ne pose plus problème
    for name in list(alerts.keys()):
        if name not in problem_names:
            label = next((w.get("label") or name for w in workers
                          if w.get("name") == name), name)
            _send_push(f"✅ Robot rétabli : {label}",
                       "Il a refait un passage sans erreur.")
            alerts.pop(name, None)
            out["recovered"] += 1

    state["alerts"] = alerts
    state["last_check_at"] = now_iso
    _save_state(state)
    return out
