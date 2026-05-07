"""Lead-to-client runner — bascule auto des prospects intéressés en projets clients.

Quand un prospect répond positivement (classification.category == "interested"),
ce worker peut automatiquement créer une carte dans le kanban "Briefing" de la
vue Clients, prête à être traitée. La livraison automatique (via post_sale_runner)
ne se déclenchera qu'au moment où Jordan marquera le projet comme "payé"
(remplissage de paid_at, soit manuellement soit via webhook Stripe à venir).

Trois modes possibles, configurables par Jordan :
  - "off"        : bascule désactivée, tout reste manuel.
  - "strong"     : ne bascule QUE les réponses qui contiennent un signal fort
                   d'achat (demande prix/devis, "j'achète", "où je paie", etc.).
  - "all"        : bascule TOUTES les réponses interested (Jordan triera après).

Idempotent : on marque chaque email_history.extra avec lead_converted_at une
fois la bascule faite, pour ne jamais recréer le même projet.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)


MODES = ("off", "strong", "all")

DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": True,           # global on/off
    "mode": "strong",          # off | strong | all
    "default_product_key": "custom-dev",
    "default_product_name": "Service Triskell",
    "min_confidence": 0.6,     # ignore les classifications peu confiantes
}


# Regex de détection des signaux d'achat (insensible à la casse, multilingue FR/EN)
_PURCHASE_SIGNALS_RE = re.compile(
    r"\b("
    # Demande de prix / devis
    r"prix|devis|tarifs?|combien|coût|cout|coute|combien ça coute|how much|"
    r"quote|pricing|cost|estimate|"
    # Acceptation / engagement
    r"j'?ach(?:è|e)te|j'?en veux|on y va|c'?est parti|let'?s go|deal|signé|"
    r"signed|ok pour|d'?accord pour|j'?accepte|ready to (?:buy|purchase)|"
    r"i'?ll (?:take|buy)|"
    # Questions de paiement / facture
    r"paiement|facture|cb|carte bleue|virement|sepa|stripe|paypal|invoice|"
    r"payment method|how (?:do i pay|to pay)|wire transfer"
    r")\b",
    re.IGNORECASE,
)


CYCLE_INTERVAL_SECONDS = 5 * 60          # passe toutes les 5 min
INITIAL_DELAY_SECONDS = 90

_WORKER_THREAD: Optional[threading.Thread] = None
_WORKER_STOP = threading.Event()
_WORKER_LOCK = threading.Lock()
_LAST_RUN_AT: str = ""
_LAST_RUN_RESULT: dict = {}


def start_worker(app_state) -> bool:
    global _WORKER_THREAD
    with _WORKER_LOCK:
        if _WORKER_THREAD is not None and _WORKER_THREAD.is_alive():
            return True
        _WORKER_STOP.clear()
        t = threading.Thread(target=_loop, args=(app_state,),
                              name="LeadToClientWorker", daemon=True)
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
    }


def load_config(client) -> dict:
    raw = client.get_shared_setting("lead_to_client", {}) or {}
    if isinstance(raw, str):
        try: raw = json.loads(raw)
        except Exception: raw = {}
    return {**DEFAULT_CONFIG, **raw}


def save_config(client, config: dict) -> None:
    client.set_shared_setting("lead_to_client", config)


def run_now(app_state) -> dict:
    return _do_one_cycle(app_state)


# ---------------------------------------------------------------------------
def _loop(app_state) -> None:
    if _WORKER_STOP.wait(INITIAL_DELAY_SECONDS):
        return
    while not _WORKER_STOP.is_set():
        try:
            _do_one_cycle(app_state)
        except Exception as exc:
            logger.warning("LeadToClient cycle: %s", exc)
        for _ in range(CYCLE_INTERVAL_SECONDS // 5):
            if _WORKER_STOP.is_set():
                return
            time.sleep(5)


def _do_one_cycle(app_state) -> dict:
    global _LAST_RUN_AT, _LAST_RUN_RESULT
    counters = {"scanned": 0, "converted": 0, "skipped": 0,
                "weak_signal": 0, "errors": 0}

    client = _get_client()
    if client is None:
        counters["error"] = "supabase_unavailable"
        _set_run(counters)
        return counters

    config = load_config(client)
    if not config.get("enabled", True):
        _set_run(counters)
        return counters
    mode = config.get("mode", "strong")
    if mode == "off":
        _set_run(counters)
        return counters
    min_conf = float(config.get("min_confidence") or 0.0)
    default_pk = config.get("default_product_key") or "custom-dev"
    default_pn = config.get("default_product_name") or "Service Triskell"

    sb = client.raw

    # On ne récupère que les réponses non encore basculées
    try:
        res = (sb.table("email_history").select("*")
               .eq("kind", "reply_received")
               .order("ts", desc=True).limit(500).execute())
        rows = res.data or []
    except Exception as exc:
        counters["error"] = f"fetch: {exc}"
        _set_run(counters)
        return counters

    from . import task_lock
    me_uid = client.user_id or ""

    for row in rows:
        counters["scanned"] += 1
        try:
            extra = row.get("extra") or {}
            if isinstance(extra, str):
                try: extra = json.loads(extra)
                except Exception: extra = {}

            # Déjà basculé ?
            if extra.get("lead_converted_at"):
                continue

            cls = (extra.get("classification") or {})
            cat = (cls.get("category") or "").lower()
            conf = float(cls.get("confidence") or 0.0)

            if cat != "interested":
                continue
            if conf < min_conf:
                counters["skipped"] += 1
                continue

            # Mode "strong" : exige un signal d'achat dans le corps
            body_excerpt = (extra.get("body_excerpt") or "")[:5000]
            has_strong = bool(_PURCHASE_SIGNALS_RE.search(body_excerpt))
            if mode == "strong" and not has_strong:
                counters["weak_signal"] += 1
                continue

            # Verrou doux pour éviter double conversion (Jordan + Thomas)
            if task_lock.is_locked_by_other(client, "email_history",
                                              row.get("id"), user_id=me_uid):
                counters["skipped"] += 1
                continue
            if not task_lock.try_acquire_lock(client, "email_history",
                                                row.get("id"), user_id=me_uid):
                counters["skipped"] += 1
                continue
            try:
                ok = _convert_to_client_project(
                    client, sb, row, extra, default_pk, default_pn,
                    has_strong=has_strong,
                )
                if ok:
                    counters["converted"] += 1
                else:
                    counters["errors"] += 1
            finally:
                task_lock.release_lock(client, "email_history",
                                        row.get("id"), user_id=me_uid)
        except Exception as exc:
            logger.warning("lead_to_client row %s: %s", row.get("id"), exc)
            counters["errors"] += 1

    _set_run(counters)
    return counters


def _convert_to_client_project(client, sb, row: dict, extra: dict,
                                default_pk: str, default_pn: str,
                                *, has_strong: bool) -> bool:
    """Crée le projet client depuis la réponse + marque l'extra comme convertie."""
    try:
        from . import clients_repo
    except Exception as exc:
        logger.warning("clients_repo import: %s", exc)
        return False

    # Hydrate prospect (nom + email)
    pid = row.get("prospect_id")
    client_name = ""
    client_email = (extra.get("from") or row.get("from_addr") or "").strip()
    if pid:
        try:
            r = (sb.table("prospects").select("name,legal_name,emails")
                 .eq("id", pid).limit(1).execute())
            data = (r.data or [{}])[0]
            client_name = data.get("name") or data.get("legal_name") or ""
            if not client_email and data.get("emails"):
                client_email = data["emails"][0]
        except Exception:
            pass

    if not client_email:
        return False

    # Tente d'inférer le produit pitché depuis email_history (kind=email_sent
    # plus récent pour ce prospect avec un extra.pitched_product_key)
    product_key, product_name = default_pk, default_pn
    if pid:
        try:
            sent = (sb.table("email_history").select("extra")
                    .eq("prospect_id", pid).eq("kind", "email_sent")
                    .order("ts", desc=True).limit(5).execute())
            for s in (sent.data or []):
                sx = s.get("extra") or {}
                if isinstance(sx, str):
                    try: sx = json.loads(sx)
                    except Exception: continue
                if sx.get("pitched_product_key"):
                    product_key = sx["pitched_product_key"]
                    product_name = sx.get("pitched_product_name") or product_key
                    break
        except Exception:
            pass

    # Création du projet en statut "briefing" (pas payé → pas de livraison auto)
    payload = {
        "title": f"Lead — {client_name or client_email}",
        "client_name": client_name,
        "client_email": client_email,
        "product_key": product_key,
        "product_name": product_name,
        "status": "briefing",
        "prospect_id": pid,
        "currency": "EUR",
        "notes": _build_notes(row, extra, has_strong=has_strong),
    }
    proj = clients_repo.create_project(payload)
    if not proj:
        return False

    # Marque l'email_history pour ne jamais reconvertir
    try:
        extra["lead_converted_at"] = datetime.now().isoformat(timespec="seconds")
        extra["lead_converted_to"] = proj.get("id")
        extra["lead_strong_signal"] = bool(has_strong)
        sb.table("email_history").update({"extra": extra}).eq(
            "id", row.get("id")).execute()
    except Exception as exc:
        logger.debug("mark_converted: %s", exc)

    return True


def _build_notes(row: dict, extra: dict, *, has_strong: bool) -> str:
    """Construit le bloc de notes du projet (résumé + extrait + lien)."""
    cls = (extra.get("classification") or {})
    cat = cls.get("category", "?")
    conf = cls.get("confidence", 0)
    excerpt = (extra.get("body_excerpt") or "")[:600]
    signal = "🟢 Signal d'achat fort" if has_strong else "🟡 Intéressé sans signal d'achat clair"
    return (
        f"Bascule auto depuis Réponses (catégorie : {cat}, confiance : "
        f"{int(conf*100)}%).\n"
        f"{signal}\n\n"
        f"Sujet : {row.get('subject', '(sans objet)')}\n"
        f"Date  : {row.get('ts', '?')}\n\n"
        f"Extrait :\n{excerpt}\n"
    )


# ---------------------------------------------------------------------------
def _get_client():
    try:
        from triskell_core.db import get_client, SupabaseNotConfigured
    except ImportError:
        return None
    try:
        c = get_client()
    except SupabaseNotConfigured:
        return None
    if not c.is_authenticated:
        return None
    return c


def _set_run(counters: dict) -> None:
    global _LAST_RUN_AT, _LAST_RUN_RESULT
    _LAST_RUN_AT = datetime.now().isoformat(timespec="seconds")
    _LAST_RUN_RESULT = counters
