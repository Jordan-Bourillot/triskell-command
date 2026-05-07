"""Stripe poller — détecte les nouveaux paiements et crée le projet client.

Pourquoi par polling et pas par webhook ?
  Le webhook nécessite un serveur public exposé sur internet (avec
  HTTPS valide), un tunnel ngrok/cloudflare, et de la maintenance. Le
  polling fait la même chose côté Stripe (qui supporte la pagination
  incrémentale via `created[gte]`), c'est plus robuste, et ça marche
  même quand Triskell Command tourne en local sur ta machine.

Flow :
  1. Toutes les N minutes, on liste les `checkout.session` Stripe avec
     status='complete' depuis le dernier check (curseur sauvegardé en
     local dans ~/.triskell-command/stripe_cursor.json).
  2. Pour chaque nouvelle session, on crée un `client_projects` row
     avec paid_at rempli et product_key mappé.
  3. Le `post_sale_runner` (qui tourne déjà toutes les heures) détecte
     ce projet payé et déclenche automatiquement le kit de livraison
     du produit (mail welcome + livrables + relances suivies).

Idempotent : on stocke le `session.id` dans `client_projects.stripe_session_id`
+ on filtre les déjà-traités, donc même si le poller redémarre on ne
double pas.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


CURSOR_FILE = Path.home() / ".triskell-command" / "stripe_cursor.json"
SHARED_KEY = "stripe_poller"
SHARED_CURSOR_KEY = "stripe_cursor"   # curseur partagé entre Jordan et Thomas


DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": False,           # désactivé par défaut tant que Jordan n'a pas mis sa clé
    "secret_key": "",           # clé secrète Stripe (sk_live_… ou sk_test_…)
    "poll_minutes": 5,          # poll toutes les 5 min
    # Mapping Stripe product/price_id → product_key Triskell
    # Ex : { "prod_NXxxx": "pack-electricien-pro", "price_xxx": "studio-pdf" }
    "product_mapping": {},
    # Si un product_id n'est pas dans le mapping, on tombe sur ce kit
    "default_product_key": "_default",
    "default_product_name": "Commande Stripe",
}


CYCLE_INTERVAL_DEFAULT = 5 * 60       # rechargé depuis config à chaque cycle
INITIAL_DELAY_SECONDS = 60

_WORKER_THREAD: Optional[threading.Thread] = None
_WORKER_STOP = threading.Event()
_WORKER_LOCK = threading.Lock()
_LAST_RUN_AT: str = ""
_LAST_RUN_RESULT: dict = {}


# ---------------------------------------------------------------------------
def start_worker(app_state) -> bool:
    global _WORKER_THREAD
    with _WORKER_LOCK:
        if _WORKER_THREAD is not None and _WORKER_THREAD.is_alive():
            return True
        _WORKER_STOP.clear()
        t = threading.Thread(target=_loop, args=(app_state,),
                              name="StripePollerWorker", daemon=True)
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
    if client:
        try:
            raw = client.get_shared_setting(SHARED_KEY, {}) or {}
            if isinstance(raw, str):
                try: raw = json.loads(raw)
                except Exception: raw = {}
            if isinstance(raw, dict) and raw:
                return {**DEFAULT_CONFIG, **raw}
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)


def save_config(client, config: dict) -> None:
    if client:
        client.set_shared_setting(SHARED_KEY, config)


def run_now(app_state) -> dict:
    return _do_one_cycle(app_state)


# ---------------------------------------------------------------------------
def _load_cursor(client=None) -> int:
    """Renvoie le timestamp Unix du dernier paiement traité (0 si jamais).
    Lecture prioritaire depuis Supabase (partagé Jordan ↔ Thomas) avec
    fallback sur fichier local."""
    if client is not None:
        try:
            raw = client.get_shared_setting(SHARED_CURSOR_KEY, {}) or {}
            if isinstance(raw, str):
                try: raw = json.loads(raw)
                except Exception: raw = {}
            if isinstance(raw, dict) and raw.get("last_payment_ts"):
                return int(raw["last_payment_ts"])
        except Exception as exc:
            logger.debug("load_cursor supabase: %s", exc)
    if not CURSOR_FILE.exists():
        return 0
    try:
        data = json.loads(CURSOR_FILE.read_text(encoding="utf-8"))
        return int(data.get("last_payment_ts") or 0)
    except Exception:
        return 0


def _save_cursor(ts: int, client=None) -> None:
    """Sauve le curseur en local + miroir Supabase (partagé)."""
    CURSOR_FILE.parent.mkdir(parents=True, exist_ok=True)
    CURSOR_FILE.write_text(
        json.dumps({"last_payment_ts": int(ts)}, indent=2),
        encoding="utf-8",
    )
    if client is not None:
        try:
            client.set_shared_setting(SHARED_CURSOR_KEY,
                                       {"last_payment_ts": int(ts)})
        except Exception as exc:
            logger.debug("save_cursor supabase: %s", exc)


# ---------------------------------------------------------------------------
def _loop(app_state) -> None:
    if _WORKER_STOP.wait(INITIAL_DELAY_SECONDS):
        return
    while not _WORKER_STOP.is_set():
        try:
            _do_one_cycle(app_state)
        except Exception as exc:
            logger.warning("StripePoller cycle: %s", exc)
        # Le délai entre cycles est lu depuis la config à chaque tour
        client = _get_client()
        cfg = load_config(client) if client else DEFAULT_CONFIG
        wait_s = max(60, int(cfg.get("poll_minutes") or 5) * 60)
        for _ in range(wait_s // 5):
            if _WORKER_STOP.is_set():
                return
            time.sleep(5)


def _do_one_cycle(app_state) -> dict:
    global _LAST_RUN_AT, _LAST_RUN_RESULT
    counters = {"polled": 0, "new_payments": 0, "projects_created": 0,
                "skipped": 0, "errors": 0}

    client = _get_client()
    if client is None:
        counters["error"] = "supabase_unavailable"
        _set_run(counters)
        return counters

    config = load_config(client)
    if not config.get("enabled", False):
        _set_run(counters)
        return counters

    sk = (config.get("secret_key") or "").strip()
    if not sk or not (sk.startswith("sk_live_") or sk.startswith("sk_test_")):
        counters["error"] = "secret_key invalide"
        _set_run(counters)
        return counters

    cursor = _load_cursor(client=client)
    sessions, max_ts = _list_completed_sessions_since(sk, cursor)
    counters["polled"] = len(sessions)

    if not sessions:
        if max_ts > cursor:
            _save_cursor(max_ts)
        _set_run(counters)
        return counters

    # Pour chaque session payée → créer le client_project
    sb = client.raw
    for sess in sessions:
        sid = sess.get("id")
        if not sid:
            continue
        try:
            # Idempotence : déjà créé ?
            res = (sb.table("client_projects")
                   .select("id")
                   .eq("stripe_session_id", sid)
                   .limit(1).execute())
            if res.data:
                counters["skipped"] += 1
                continue

            # Construit le payload
            payload = _build_payment_payload(sess, config)
            if not payload:
                counters["skipped"] += 1
                continue

            try:
                from . import clients_repo
            except Exception as exc:
                counters["error"] = f"clients_repo: {exc}"
                continue

            proj = clients_repo.create_project(payload)
            if proj:
                counters["projects_created"] += 1
                logger.info("Stripe → projet client créé: %s (%s)",
                             proj.get("id"), payload.get("product_key"))
            else:
                counters["errors"] += 1
        except Exception as exc:
            logger.warning("stripe session %s: %s", sid, exc)
            counters["errors"] += 1

    counters["new_payments"] = len(sessions) - counters["skipped"]
    if max_ts > cursor:
        _save_cursor(max_ts, client=client)

    _set_run(counters)
    return counters


# ---------------------------------------------------------------------------
def _list_completed_sessions_since(secret_key: str, since_ts: int):
    """Liste les checkout.session payées depuis `since_ts` (Unix).
    Retourne (liste, max_ts vu)."""
    import requests

    headers = {"Authorization": f"Bearer {secret_key}"}
    params: dict[str, Any] = {
        "limit": 100,
        "expand[]": "data.line_items",
    }
    if since_ts > 0:
        # Stripe accepte created[gte] = unix timestamp
        params["created[gte]"] = since_ts + 1   # strict > pour pas re-piocher

    r = requests.get(
        "https://api.stripe.com/v1/checkout/sessions",
        headers=headers, params=params, timeout=15,
    )
    if r.status_code >= 400:
        try:
            err = r.json().get("error", {}).get("message", r.text)
        except Exception:
            err = r.text
        raise RuntimeError(f"Stripe API HTTP {r.status_code}: {err}")

    data = r.json().get("data", []) or []
    # Garde uniquement les sessions complétées et payées
    completed = [s for s in data
                  if s.get("status") == "complete"
                  and s.get("payment_status") == "paid"]
    max_ts = since_ts
    for s in completed:
        ts = int(s.get("created") or 0)
        if ts > max_ts:
            max_ts = ts
    return completed, max_ts


def _build_payment_payload(sess: dict, config: dict) -> Optional[dict]:
    """Convertit une session Stripe en payload pour clients_repo.create_project."""
    customer_email = (sess.get("customer_details") or {}).get("email") or sess.get("customer_email") or ""
    customer_name = (sess.get("customer_details") or {}).get("name") or ""
    if not customer_email:
        return None

    # Détecte product_id / price_id depuis line_items (si expand a marché)
    product_id = ""
    price_id = ""
    line_items = ((sess.get("line_items") or {}).get("data") or [])
    if line_items:
        first = line_items[0]
        price = first.get("price") or {}
        product_id = price.get("product") or ""
        price_id   = price.get("id") or ""

    # Mapping product_id → product_key Triskell
    mapping = config.get("product_mapping") or {}
    product_key = (mapping.get(product_id) or mapping.get(price_id)
                   or config.get("default_product_key") or "_default")

    # Nom du produit affiché
    product_name = (mapping.get(f"{product_id}_name")
                    or sess.get("metadata", {}).get("product_name")
                    or config.get("default_product_name")
                    or product_key)

    amount_cents = int(sess.get("amount_total") or 0)
    currency = (sess.get("currency") or "eur").upper()

    paid_at = datetime.fromtimestamp(int(sess.get("created") or time.time())).isoformat(
        timespec="seconds")

    return {
        "title": f"{product_name} — {customer_name or customer_email}",
        "client_name":  customer_name,
        "client_email": customer_email,
        "product_key":  product_key,
        "product_name": product_name,
        "status":       "briefing",      # le post_sale_runner ne dépend que de paid_at
        "amount_cents": amount_cents,
        "currency":     currency,
        "paid_at":      paid_at,         # ⚡ déclenche le kit de livraison
        "stripe_session_id": sess.get("id"),
        "notes": _build_notes(sess, product_key, product_name),
    }


def _build_notes(sess: dict, product_key: str, product_name: str) -> str:
    cust = (sess.get("customer_details") or {})
    addr = (cust.get("address") or {})
    addr_str = ", ".join(filter(None, [
        addr.get("line1"), addr.get("line2"), addr.get("postal_code"),
        addr.get("city"), addr.get("country"),
    ]))
    return (
        f"Paiement Stripe automatique.\n\n"
        f"Produit  : {product_name} ({product_key})\n"
        f"Montant  : {sess.get('amount_total', 0)/100:.2f} {sess.get('currency', '?').upper()}\n"
        f"Mode     : {sess.get('mode', '?')}\n"
        f"Adresse  : {addr_str or '—'}\n"
        f"Téléphone: {cust.get('phone') or '—'}\n"
        f"Session  : {sess.get('id')}\n"
        f"URL      : {sess.get('url') or '—'}\n"
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
