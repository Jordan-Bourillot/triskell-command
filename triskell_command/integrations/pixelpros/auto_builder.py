"""Pixel Pros — Auto-construction des sites payés.

Avant ce worker : un client payait, puis son site attendait que Jordan
clique « Lancer la construction » (la carte passait même en URGENT après
6 h d'attente). Désormais, quand l'interrupteur est sur AUTO, le serveur
scanne les commandes payées toutes les 5 minutes et lance le builder
tout seul — quel que soit le chemin par lequel le paiement est arrivé
(webhook Stripe, passage manuel en payé, poller).

Garde-fous :
  - opt-in : shared_settings.pixelpros_auto_build (défaut OFF, comme les
    interrupteurs AUTO/MANUEL des mails Pixel Pros) ;
  - UNE tentative automatique par commande, persistée cross-redémarrage
    dans shared_settings.pixelpros_auto_build_state (relance = geste
    humain depuis l'UI, comme avant) ;
  - délai de grâce de 3 min après le paiement (laisse le webhook finir
    et le mail « paiement reçu » partir) ;
  - 2 constructions max par cycle (le builder est lourd : Claude +
    Netlify) ;
  - échec de lancement → la commande passe en « failed » + push haute
    priorité à Jordan (le bouton relancer de l'UI reste le filet) ;
  - chaque lancement auto envoie une push d'information.

Le suivi du build lui-même (live/failed + mail « ton site est en
ligne ») est déjà géré par le circuit existant (drain du subprocess
dans repo._dispatch_local + le builder qui marque live).
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 5 * 60      # scan toutes les 5 min
MIN_AGE_MINUTES = 3.0               # grâce post-paiement
MAX_BUILDS_PER_CYCLE = 2
STATE_RETENTION_DAYS = 45           # purge des tentatives anciennes

SETTING_ENABLED = "pixelpros_auto_build"
SETTING_STATE = "pixelpros_auto_build_state"

_worker_thread: threading.Thread | None = None
_LAST_RUN_AT: str = ""
_LAST_RUN_RESULT: dict = {}


# ---------------------------------------------------------------------------
# Accès Supabase (wrapper triskell-core : get/set_shared_setting)
# ---------------------------------------------------------------------------
def _get_client():
    try:
        from triskell_core.db import get_client, SupabaseNotConfigured
    except ImportError:
        return None
    try:
        c = get_client()
    except Exception:
        return None
    if not getattr(c, "is_authenticated", False):
        return None
    return c


def is_enabled() -> bool:
    """True si l'auto-construction est activée (défaut : False, opt-in)."""
    c = _get_client()
    if c is None:
        return False
    try:
        return bool(c.get_shared_setting(SETTING_ENABLED, default=False))
    except Exception as exc:
        logger.debug("pixelpros.auto_builder.is_enabled: %s", exc)
        return False


def set_enabled(value: bool) -> tuple[bool, str]:
    """Bascule AUTO/MANUEL. Relit pour confirmer l'écriture."""
    c = _get_client()
    if c is None:
        return False, "Base partagée non connectée."
    try:
        c.set_shared_setting(SETTING_ENABLED, bool(value))
        real = bool(c.get_shared_setting(SETTING_ENABLED, default=False))
        if real != bool(value):
            return False, "Le réglage n'a pas pu être enregistré."
        return True, "Mode mis à jour."
    except Exception as exc:
        return False, str(exc)


def _load_state(c) -> dict:
    try:
        st = c.get_shared_setting(SETTING_STATE, default={}) or {}
        return st if isinstance(st, dict) else {}
    except Exception:
        return {}


def _save_state(c, state: dict, now: datetime) -> None:
    # Purge naturelle : on ne garde que les tentatives récentes.
    try:
        cutoff = now.timestamp() - STATE_RETENTION_DAYS * 86400
        cleaned = {}
        for iid, ts in state.items():
            try:
                t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                if t.timestamp() >= cutoff:
                    cleaned[iid] = ts
            except Exception:
                continue
        c.set_shared_setting(SETTING_STATE, cleaned)
    except Exception as exc:
        logger.debug("pixelpros.auto_builder._save_state: %s", exc)


def _notify(title: str, body: str, priority: str = "normal") -> None:
    try:
        from ...web.push import send_push
        send_push(title=title, body=body, user_id="jordan",
                  priority=priority, tag_group="pixelpros-autobuild",
                  url="/#pixelpros")
    except Exception as exc:
        logger.debug("pixelpros.auto_builder._notify: %s", exc)


def _minutes_since(iso_ts: str, now: datetime) -> float | None:
    if not iso_ts:
        return None
    try:
        t = datetime.fromisoformat(str(iso_ts).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return (now - t).total_seconds() / 60.0
    except Exception:
        return None


def _business_label(intake: dict) -> str:
    data = intake.get("data") or {}
    if not isinstance(data, dict):
        data = {}
    return (intake.get("business_name") or data.get("business_name")
            or data.get("business") or intake.get("email") or "un client")


# ---------------------------------------------------------------------------
# Le cycle (fonction séparée → testable sans thread)
# ---------------------------------------------------------------------------
def tick(now: datetime | None = None) -> dict:
    """Un passage : scanne les payés, lance les constructions dues."""
    from . import repo

    now = now or datetime.now(timezone.utc)
    c = _get_client()
    if c is None:
        return {"skipped_reason": "supabase_indispo"}
    if not is_enabled():
        return {"skipped_reason": "disabled"}

    paid = repo.list_intakes(status="paid", limit=20)
    out = {"checked": len(paid), "launched": [], "failed": [],
           "waiting_grace": 0, "already_tried": 0}
    if not paid:
        return out

    state = _load_state(c)
    for intake in paid:
        if len(out["launched"]) >= MAX_BUILDS_PER_CYCLE:
            break
        iid = str(intake.get("id") or "")
        if not iid:
            continue
        if iid in state:
            out["already_tried"] += 1
            continue
        age_min = _minutes_since(
            intake.get("stripe_paid_at") or intake.get("created_at") or "",
            now)
        if age_min is not None and age_min < MIN_AGE_MINUTES:
            out["waiting_grace"] += 1
            continue

        # Marque la tentative AVANT le dispatch : si le process meurt en
        # plein lancement, on ne relancera pas en boucle au prochain cycle.
        state[iid] = now.isoformat(timespec="seconds")
        _save_state(c, state, now)

        label = _business_label(intake)
        ok, msg = repo.dispatch_build(iid)
        if ok:
            out["launched"].append(iid)
            logger.info("auto_builder: construction lancée pour %s (%s)",
                        label, iid[:8])
            _notify("🏗️ Site en construction",
                    f"{label} : paiement reçu, construction lancée toute "
                    "seule. Tu seras prévenu à la mise en ligne.",
                    priority="low")
        else:
            out["failed"].append({"id": iid, "error": msg})
            logger.warning("auto_builder: lancement KO pour %s : %s", iid, msg)
            repo.mark_failed(iid, error_message=f"Auto-construction : {msg}")
            _notify("⚠️ Construction automatique échouée",
                    f"{label} : {msg} — à relancer depuis l'écran Pixel Pros.",
                    priority="high")
    return out


# ---------------------------------------------------------------------------
# Worker (pattern aligné sur les autres runners)
# ---------------------------------------------------------------------------
def start_worker(app_state=None) -> bool:
    """Lance le thread de fond. Idempotent. Le thread tourne même si la
    base est indisponible au boot (il réessaie à chaque cycle)."""
    global _worker_thread
    if _worker_thread is not None and _worker_thread.is_alive():
        return True

    def loop():
        global _LAST_RUN_AT, _LAST_RUN_RESULT
        logger.info("pixelpros.auto_builder: thread démarré (cycle %d min)",
                    POLL_INTERVAL_SECONDS // 60)
        time.sleep(90)   # laisse le serveur finir son boot
        while True:
            try:
                _LAST_RUN_RESULT = tick()
                _LAST_RUN_AT = datetime.now(timezone.utc).isoformat(
                    timespec="seconds")
            except Exception as exc:
                logger.exception("pixelpros.auto_builder tick: %s", exc)
                _LAST_RUN_RESULT = {"error": str(exc)}
            time.sleep(POLL_INTERVAL_SECONDS)

    _worker_thread = threading.Thread(
        target=loop, name="pixelpros_auto_builder", daemon=True)
    _worker_thread.start()
    return True


def get_status() -> dict:
    """Format attendu par system_health / worker_watchdog."""
    return {
        "running": _worker_thread is not None and _worker_thread.is_alive(),
        "last_run_at": _LAST_RUN_AT,
        "last_run_result": dict(_LAST_RUN_RESULT),
    }
