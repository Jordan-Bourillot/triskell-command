"""Pixel Pros — Relances des commandes « payées mais à compléter ».

Depuis le passage en « payer d'abord » (13/06/2026), un client paie puis doit
décrire son activité (formulaire détaillé). Tant qu'il ne l'a pas fait, sa
commande reste en statut 'awaiting_content'. Ce worker la relance par mail
jusqu'à ce qu'elle soit complétée — pour que PERSONNE ne paie sans obtenir son
site.

Relances envoyées (si toujours 'awaiting_content', et si l'envoi auto du mail
« paiement reçu » est activé) :
  - ~20 h après le paiement   (J+1)
  - ~72 h après le paiement   (J+3)
  - ~168 h après le paiement  (J+7)

Le mail de paiement contient déjà le lien pour compléter (configurer.html?draft=…) ;
on réutilise donc send_paid_mail pour les relances. Une fois le formulaire rempli,
la commande passe en 'paid' et sort de la liste : plus aucune relance.

Modèle aligné sur auto_builder.py (cycle horaire, état persistant cross-redémarrage).
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 60 * 60          # un passage par heure
RELANCE_HOURS = [20, 72, 168]            # J+1, J+3, J+7
STATE_RETENTION_DAYS = 45
SETTING_STATE = "pixelpros_content_chaser_state"

_worker_thread: threading.Thread | None = None
_LAST_RUN_AT: str = ""
_LAST_RUN_RESULT: dict = {}


def _get_client():
    try:
        from triskell_core.db import get_client
    except ImportError:
        return None
    try:
        c = get_client()
    except Exception:
        return None
    if not getattr(c, "is_authenticated", False):
        return None
    return c


def _load_state(c) -> dict:
    try:
        st = c.get_shared_setting(SETTING_STATE, default={}) or {}
        return st if isinstance(st, dict) else {}
    except Exception:
        return {}


def _save_state(c, state: dict, now: datetime) -> None:
    # Purge naturelle : on oublie les commandes traitées il y a longtemps.
    try:
        cutoff = now.timestamp() - STATE_RETENTION_DAYS * 86400
        cleaned = {}
        for iid, rec in state.items():
            ts = rec.get("at") if isinstance(rec, dict) else None
            try:
                t = datetime.fromisoformat(str(ts).replace("Z", "+00:00")) if ts else now
                if t.timestamp() >= cutoff:
                    cleaned[iid] = rec
            except Exception:
                cleaned[iid] = rec
        c.set_shared_setting(SETTING_STATE, cleaned)
    except Exception as exc:
        logger.debug("content_chaser._save_state: %s", exc)


def _hours_since(iso_ts: str, now: datetime) -> float | None:
    if not iso_ts:
        return None
    try:
        t = datetime.fromisoformat(str(iso_ts).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return (now - t).total_seconds() / 3600.0
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Le cycle (séparé du thread → testable)
# ---------------------------------------------------------------------------
def tick(now: datetime | None = None) -> dict:
    """Un passage : relance les commandes payées encore à compléter."""
    from . import repo, mailer

    now = now or datetime.now(timezone.utc)
    c = _get_client()
    if c is None:
        return {"skipped_reason": "supabase_indispo"}

    # On respecte le réglage d'envoi auto du mail « paiement reçu » : si Jordan
    # l'a passé en manuel, on ne relance pas tout seul (il chasse depuis l'UI).
    try:
        if not mailer.is_auto("paid"):
            return {"skipped_reason": "mail_paid_manuel"}
    except Exception:
        pass

    waiting = repo.list_intakes(status="awaiting_content", limit=50)
    out = {"checked": len(waiting), "relances": [], "errors": []}
    if not waiting:
        return out

    state = _load_state(c)
    changed = False
    for intake in waiting:
        iid = str(intake.get("id") or "")
        if not iid:
            continue
        age_h = _hours_since(
            intake.get("stripe_paid_at") or intake.get("updated_at")
            or intake.get("created_at") or "", now)
        if age_h is None:
            continue

        rec = state.get(iid) or {"sent": [], "at": now.isoformat(timespec="seconds")}
        sent = rec.get("sent") or []

        # Premier palier atteint mais pas encore envoyé.
        due = None
        for milestone in RELANCE_HOURS:
            if age_h >= milestone and milestone not in sent:
                due = milestone
                break
        if due is None:
            continue

        try:
            ok, msg = mailer.send_paid_mail(intake)
        except Exception as exc:
            ok, msg = False, str(exc)

        if ok:
            sent.append(due)
            rec["sent"] = sent
            rec["at"] = now.isoformat(timespec="seconds")
            state[iid] = rec
            changed = True
            out["relances"].append({"id": iid, "palier_h": due})
            logger.info("content_chaser: relance J palier %dh envoyée pour %s",
                        due, iid[:8])
        else:
            out["errors"].append({"id": iid, "error": msg})
            logger.warning("content_chaser: relance KO pour %s : %s", iid, msg)

    if changed:
        _save_state(c, state, now)
    return out


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------
def start_worker(app_state=None) -> bool:
    global _worker_thread
    if _worker_thread is not None and _worker_thread.is_alive():
        return True

    def loop():
        global _LAST_RUN_AT, _LAST_RUN_RESULT
        logger.info("pixelpros.content_chaser: thread démarré (cycle %d min)",
                    POLL_INTERVAL_SECONDS // 60)
        time.sleep(120)  # laisse le serveur finir son boot
        while True:
            try:
                _LAST_RUN_RESULT = tick()
                _LAST_RUN_AT = datetime.now(timezone.utc).isoformat(timespec="seconds")
            except Exception as exc:
                logger.exception("pixelpros.content_chaser tick: %s", exc)
                _LAST_RUN_RESULT = {"error": str(exc)}
            time.sleep(POLL_INTERVAL_SECONDS)

    _worker_thread = threading.Thread(
        target=loop, name="pixelpros_content_chaser", daemon=True)
    _worker_thread.start()
    return True


def get_status() -> dict:
    """Format attendu par system_health / worker_watchdog."""
    return {
        "running": _worker_thread is not None and _worker_thread.is_alive(),
        "last_run_at": _LAST_RUN_AT,
        "last_run_result": dict(_LAST_RUN_RESULT),
    }
