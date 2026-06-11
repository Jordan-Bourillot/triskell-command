"""Le guetteur du copilote — l'initiative branchée sur le réel (étape 3).

Un robot LÉGER qui regarde l'état de l'app toutes les 90 s (les mêmes
compteurs que la barre-guide, via le cache de guide_snapshot) et compare
au passage précédent. Quand quelque chose mérite l'attention :

  - un message d'évènement est déposé dans le fil du copilote de chaque
    utilisateur (selon son niveau d'initiative : off / discret / normal /
    bavard) → pastille 💬 sur la barre-guide ;
  - si c'est CHAUD (réponse de prospect, mission en erreur) et que le
    niveau le permet : notification push sur le téléphone.

Les textes sont rédigés par des RÈGLES (français, zéro appel IA, zéro
coût). Les pannes de robots ne déclenchent PAS de push ici : le chien de
garde existant s'en charge déjà (on dépose seulement au fil).

Le « déjà signalé » survit aux redémarrages : l'instantané précédent est
persisté (shared_settings copilot_watch_state, secours fichier local).
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Any, Callable, Optional

from . import copilot

logger = logging.getLogger(__name__)

CYCLE_SECONDS = 90
INITIAL_DELAY_SECONDS = 120
WATCH_STATE_KEY = "copilot_watch_state"
WATCH_USER = "_watch"            # « utilisateur » du doc d'état global
USERS = ("jordan", "thomas")
DAILY_REMINDER_HOUR = 9          # pas de rappel quotidien avant cette heure
PUSH_CAP_PER_HOUR = 6            # ceinture anti-rafale

_WORKER_THREAD: Optional[threading.Thread] = None
_WORKER_STOP = threading.Event()
_WORKER_LOCK = threading.Lock()
_LAST_RUN_AT: str = ""
_LAST_RUN_RESULT: dict = {}


def get_status() -> dict:
    return {
        "running": _WORKER_THREAD is not None and _WORKER_THREAD.is_alive(),
        "last_run_at": _LAST_RUN_AT,
        "last_run_result": _LAST_RUN_RESULT,
    }


# ---------------------------------------------------------------------------
# État persistant (instantané précédent + rappels du jour + pushes récents)
# ---------------------------------------------------------------------------
def _load_state() -> dict:
    raw = copilot._doc_read(WATCH_STATE_KEY, copilot._LOCAL_STATE_FILE,
                            WATCH_USER) or {}
    return {
        "prev": raw.get("prev") if isinstance(raw.get("prev"), dict) else None,
        "daily": raw.get("daily") if isinstance(raw.get("daily"), dict) else {},
        "pushes": raw.get("pushes") if isinstance(raw.get("pushes"), list) else [],
    }


def _save_state(state: dict) -> None:
    copilot._doc_write(WATCH_STATE_KEY, copilot._LOCAL_STATE_FILE,
                       WATCH_USER, state)


# ---------------------------------------------------------------------------
# Collecte : un instantané minuscule, depuis la sonde de la barre-guide
# ---------------------------------------------------------------------------
def collect_snapshot() -> Optional[dict]:
    """Compteurs du moment. None si le serveur n'est pas prêt."""
    try:
        from ..web.api import get_api_instance
        api = get_api_instance()
        if api is None:
            return None
        snap = api.guide_snapshot() or {}
        if not snap.get("ok"):
            return None
    except Exception as exc:
        logger.debug("copilot_watch collect: %s", exc)
        return None
    missions = {}
    for m in (snap.get("missions") or []):
        mid = str(m.get("id") or "")
        if mid:
            missions[mid] = {
                "status": str(m.get("status") or ""),
                "label": str(m.get("label") or "")[:120],
                "counts": m.get("counts") or {},
            }
    return {
        "replies_unhandled": snap.get("replies_unhandled"),
        "drafts_pending": snap.get("drafts_pending"),
        "prospects_total": snap.get("prospects_total"),
        "prospects_new": snap.get("prospects_new"),
        "autopilot_enabled": bool(snap.get("autopilot_enabled")),
        "workers_error": int((snap.get("workers") or {}).get("error") or 0),
        "missions": missions,
    }


# ---------------------------------------------------------------------------
# Détection : comparer deux instantanés → évènements
# ---------------------------------------------------------------------------
def _delta(prev: dict, cur: dict, key: str) -> Optional[int]:
    a, b = prev.get(key), cur.get(key)
    if a is None or b is None:
        return None
    try:
        return int(b) - int(a)
    except Exception:
        return None


def detect_events(prev: Optional[dict], cur: dict) -> list[dict]:
    """Évènements entre deux passages. Chaque évènement :
    {key, text, nav, hot (→ push possible), minor (→ mode bavard only)}."""
    if not prev:
        return []  # premier passage : on pose la base, on ne signale rien
    events: list[dict] = []

    d = _delta(prev, cur, "replies_unhandled")
    if d and d > 0:
        s = "s" if d > 1 else ""
        events.append({
            "key": "replies",
            "text": (f"🔔 {d} prospect{s} viennent de répondre — "
                     f"c'est là que ça se joue. Je t'ouvre l'écran ?"
                     if d > 1 else
                     "🔔 Un prospect vient de répondre — c'est là que ça "
                     "se joue. Je t'ouvre l'écran ?"),
            "nav": "replies", "hot": True, "minor": False,
        })

    prev_missions = prev.get("missions") or {}
    cur_missions = cur.get("missions") or {}
    for mid, pm in prev_missions.items():
        if pm.get("status") not in ("hunting", "handing"):
            continue
        cm = cur_missions.get(mid)
        if not cm:
            continue
        label = cm.get("label") or pm.get("label") or "mission"
        if cm.get("status") == "handed":
            counts = cm.get("counts") or {}
            n = counts.get("pushed") or counts.get("found") or 0
            events.append({
                "key": f"mission_done:{mid}",
                "text": (f"✅ Chasse terminée : « {label} » — "
                         f"{n} prospect(s) versés dans ta base."),
                "nav": "prospection", "hot": False, "minor": False,
            })
        elif cm.get("status") == "error":
            events.append({
                "key": f"mission_error:{mid}",
                "text": (f"⚠️ La mission « {label} » s'est arrêtée en "
                         "erreur — le détail est sur l'écran Prospection."),
                "nav": "prospection", "hot": True, "minor": False,
            })

    pe, ce = int(prev.get("workers_error") or 0), int(cur.get("workers_error") or 0)
    if pe == 0 and ce > 0:
        s = "s" if ce > 1 else ""
        # Pas de push ici : le chien de garde s'en occupe déjà.
        events.append({
            "key": "workers_down",
            "text": f"🔧 {ce} robot{s} en panne — un œil sur Santé ?",
            "nav": "health", "hot": False, "minor": False,
        })

    d = _delta(prev, cur, "drafts_pending")
    if d and d > 0:
        events.append({
            "key": "drafts",
            "text": f"✍️ {d} nouveau(x) brouillon(s) attendent ton OK.",
            "nav": "drafts", "hot": False, "minor": True,
        })

    d = _delta(prev, cur, "prospects_total")
    if d and d > 0:
        events.append({
            "key": "prospects",
            "text": f"📈 +{d} prospect(s) dans ta base.",
            "nav": "prospects_crm", "hot": False, "minor": True,
        })

    return events


def daily_checks(cur: dict, daily: dict,
                 now: Optional[datetime] = None) -> list[dict]:
    """Rappels « angles morts » : au plus un par type et par jour, jamais
    avant DAILY_REMINDER_HOUR. `daily` (muté) mémorise {type: 'YYYY-MM-DD'}."""
    now = now or datetime.now()
    if now.hour < DAILY_REMINDER_HOUR:
        return []
    today = now.strftime("%Y-%m-%d")
    events: list[dict] = []

    def due(key: str) -> bool:
        if daily.get(key) == today:
            return False
        daily[key] = today
        return True

    r = cur.get("replies_unhandled")
    if r and int(r) > 0 and due("replies_wait"):
        s = "s" if int(r) > 1 else ""
        events.append({
            "key": "daily_replies",
            "text": (f"📥 Rappel : {r} réponse{s} de prospects "
                     f"attend{'ent' if int(r) > 1 else ''} toujours d'être "
                     "traitée(s). Un prospect chaud refroidit vite."),
            "nav": "replies", "hot": False, "minor": False,
        })

    pn = cur.get("prospects_new")
    if (not cur.get("autopilot_enabled")) and pn and int(pn) >= 5 \
            and due("autopilot_off"):
        events.append({
            "key": "daily_autopilot",
            "text": (f"💤 L'Auto-pilote est éteint et {pn} prospects "
                     "attendent qu'on leur écrive. Je peux te préparer ça "
                     "— dis-moi de l'allumer."),
            "nav": "prospection", "hot": False, "minor": False,
        })

    we = int(cur.get("workers_error") or 0)
    if we > 0 and due("workers_still_down"):
        s = "s" if we > 1 else ""
        events.append({
            "key": "daily_workers",
            "text": f"🔧 Toujours {we} robot{s} en panne aujourd'hui.",
            "nav": "health", "hot": False, "minor": False,
        })

    return events


# ---------------------------------------------------------------------------
# Dépôt : fil de chaque utilisateur (selon son niveau) + push si chaud
# ---------------------------------------------------------------------------
def _send_push_default(user_id: str, text: str, nav: str) -> bool:
    try:
        from ..web.push import send_push
        res = send_push(
            "Ton copilote", text[:240], user_id=user_id, tag="copilot",
            tag_group="copilot", priority="normal",
            url=f"/?view={nav}" if nav else "/",
        )
        return bool(res)
    except Exception as exc:
        logger.debug("copilot_watch push: %s", exc)
        return False


def _push_allowed(state: dict, now_ts: Optional[float] = None) -> bool:
    now_ts = now_ts if now_ts is not None else time.time()
    cutoff = now_ts - 3600
    state["pushes"] = [t for t in state.get("pushes") or [] if t > cutoff]
    return len(state["pushes"]) < PUSH_CAP_PER_HOUR


def deposit(events: list[dict], state: dict, *,
            users: tuple = USERS,
            deposit_fn: Optional[Callable] = None,
            push_fn: Optional[Callable] = None,
            now_ts: Optional[float] = None) -> dict:
    """Distribue les évènements. Renvoie {deposited, pushed}."""
    if not events:
        return {"deposited": 0, "pushed": 0}
    deposit_fn = deposit_fn or copilot.deposit_event_message
    push_fn = push_fn or _send_push_default
    deposited = pushed = 0
    for user in users:
        try:
            level = copilot.get_prefs(user)["initiative"]
        except Exception:
            level = copilot.DEFAULT_INITIATIVE
        if level == "off":
            continue
        for e in events:
            if e.get("minor") and level != "bavard":
                continue
            if deposit_fn(user, e["text"], e.get("nav") or ""):
                deposited += 1
            if (e.get("hot") and level in ("normal", "bavard")
                    and _push_allowed(state, now_ts)):
                if push_fn(user, e["text"], e.get("nav") or ""):
                    pushed += 1
                    state["pushes"].append(
                        now_ts if now_ts is not None else time.time())
    return {"deposited": deposited, "pushed": pushed}


# ---------------------------------------------------------------------------
# Les rendez-vous planifiés (étape 5) : préparer, jamais lancer
# ---------------------------------------------------------------------------
def fire_scheduled(state: dict, *, users: tuple = USERS,
                   now: Optional[datetime] = None,
                   push_fn: Optional[Callable] = None,
                   now_ts: Optional[float] = None) -> dict:
    """Les raccourcis planifiés dus PRÉPARENT leur action : une carte
    Confirmer/Annuler dans le fil (+ pastille), et une notification si le
    niveau d'initiative le permet. RIEN n'est exécuté ici — décision de
    Jordan (11/06/2026) : un rendez-vous attend toujours son clic."""
    from . import copilot_actions, copilot_habits
    push_fn = push_fn or _send_push_default
    now = now or datetime.now()
    fired = pushed = 0
    for user in users:
        try:
            due = copilot_habits.due_scheduled(user, now)
        except Exception as exc:
            logger.debug("copilot_watch due: %s", exc)
            continue
        for sc in due:
            try:
                # L'anti-double se pose AVANT tout dépôt : même si la
                # suite échoue, pas de seconde carte aujourd'hui.
                copilot_habits.mark_scheduled_fired(user, sc.get("id"), now)
                when = copilot_habits.schedule_label(sc.get("schedule"))
                label = sc.get("label") or "Rendez-vous"
                prop = copilot_actions.create_proposal(
                    user, sc.get("action") or {},
                    title="📅 " + label,
                    preview={"info": ("Ton rendez-vous"
                                      + (f" ({when})" if when else "")
                                      + " — tout est prêt : confirme et "
                                        "je lance.")},
                )
                copilot.deposit_proposal_message(user, prop, bump=True)
                fired += 1
                try:
                    level = copilot.get_prefs(user)["initiative"]
                except Exception:
                    level = copilot.DEFAULT_INITIATIVE
                if (level in ("normal", "bavard")
                        and _push_allowed(state, now_ts)):
                    if push_fn(user, f"📅 C'est l'heure : « {label} » est "
                                     "prêt — confirme dans le volet.", ""):
                        pushed += 1
                        state["pushes"].append(
                            now_ts if now_ts is not None else time.time())
            except Exception as exc:
                logger.warning("copilot_watch rendez-vous: %s", exc)
    return {"fired": fired, "pushed": pushed}


# ---------------------------------------------------------------------------
# Le cycle
# ---------------------------------------------------------------------------
def run_cycle_once() -> dict:
    global _LAST_RUN_AT, _LAST_RUN_RESULT
    _LAST_RUN_AT = datetime.now().isoformat(timespec="seconds")
    cur = collect_snapshot()
    if cur is None:
        _LAST_RUN_RESULT = {"skipped": "état indisponible"}
        return _LAST_RUN_RESULT
    state = _load_state()
    events = detect_events(state.get("prev"), cur)
    events += daily_checks(cur, state["daily"])
    res = deposit(events, state)
    rdv = fire_scheduled(state)
    state["prev"] = cur
    _save_state(state)
    _LAST_RUN_RESULT = {"events": len(events), **res}
    if rdv.get("fired"):
        _LAST_RUN_RESULT["rdv"] = rdv["fired"]
    return _LAST_RUN_RESULT


def _loop() -> None:
    if _WORKER_STOP.wait(INITIAL_DELAY_SECONDS):
        return
    while not _WORKER_STOP.is_set():
        try:
            run_cycle_once()
        except Exception as exc:
            logger.warning("copilot_watch cycle: %s", exc)
        for _ in range(CYCLE_SECONDS // 5):
            if _WORKER_STOP.is_set():
                return
            time.sleep(5)


def start_worker() -> bool:
    """Démarre le guetteur (idempotent)."""
    global _WORKER_THREAD
    with _WORKER_LOCK:
        if _WORKER_THREAD is not None and _WORKER_THREAD.is_alive():
            return True
        _WORKER_STOP.clear()
        t = threading.Thread(target=_loop, name="CopilotWatch", daemon=True)
        t.start()
        _WORKER_THREAD = t
    return True


def stop_worker() -> None:
    _WORKER_STOP.set()
