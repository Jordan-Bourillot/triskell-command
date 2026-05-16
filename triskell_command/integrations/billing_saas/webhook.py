"""Traite les évènements Stripe (webhook).

Branché côté FastAPI sur la route POST /api/billing/webhook.

Stripe envoie les évènements suivants qu'on doit gérer :
- checkout.session.completed         → fin de paiement initial, on active la subscription
- customer.subscription.updated      → plan changé, modules ajoutés/retirés
- customer.subscription.deleted      → résiliation effective (fin de période)
- invoice.payment_failed             → carte refusée → status='past_due'
- invoice.payment_succeeded          → mois suivant payé → status='active'

Sécurité : on vérifie la signature Stripe (header `Stripe-Signature`)
contre le webhook_secret pour s'assurer que la requête vient bien de Stripe.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from . import config
from .checkout import _stripe

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Vérification de signature
# ---------------------------------------------------------------------------
def parse_event(payload: bytes, sig_header: str) -> dict[str, Any]:
    """Vérifie la signature et renvoie l'event Stripe en dict.

    Lève ValueError si la signature est invalide.
    """
    keys = config.stripe_keys()
    secret = keys["webhook_secret"]
    if not secret:
        raise RuntimeError("STRIPE_WEBHOOK_SECRET manquante.")

    stripe = _stripe()
    try:
        return stripe.Webhook.construct_event(payload, sig_header, secret)
    except stripe.error.SignatureVerificationError as exc:
        raise ValueError(f"Signature Stripe invalide : {exc}") from exc


# ---------------------------------------------------------------------------
# Dispatch principal
# ---------------------------------------------------------------------------
def handle_event(event: dict[str, Any]) -> dict[str, Any]:
    """Traite l'event Stripe.

    Route entre :
    - SaaS workspaces (cette table : `saas_subscriptions`)
    - Clients finaux (table : `client_subscriptions`)

    Le routage se fait par metadata :
    - metadata.workspace_id → SaaS
    - metadata.client_subscription_id → Client final
    Les deux peuvent coexister dans un même flux Stripe sans interférence.
    """
    et = event.get("type", "")
    obj = (event.get("data") or {}).get("object") or {}

    # 1. Persiste l'event brut dans stripe_events (audit + anti-replay)
    _log_event(event)

    # 2. Tentative branche CLIENTS finaux (filtre par metadata interne)
    clients_result: dict[str, Any] = {"processed": False}
    try:
        from ..billing_clients import webhook as clients_webhook
        clients_result = clients_webhook.maybe_handle_event(event) or {}
    except Exception as exc:
        logger.exception("billing_clients dispatch a planté")
        clients_result = {"processed": False, "error": f"clients: {exc}"}

    # 3. Branche SaaS workspaces (gestion par défaut historique)
    handler = _HANDLERS.get(et)
    saas_processed = False
    saas_payload: dict[str, Any] = {}
    if handler is not None:
        try:
            saas_payload = handler(obj) or {}
            saas_processed = True
        except Exception as exc:
            logger.exception("Handler SaaS %s a échoué", et)
            _mark_error(event.get("id"), str(exc))
            return {"ok": False, "processed": False, "type": et,
                    "error": str(exc),
                    "clients_result": clients_result}

    # 4. Si aucun des deux n'a traité, on log et on renvoie no-op
    if not saas_processed and not clients_result.get("processed"):
        logger.info("Stripe event '%s' reçu (aucune branche n'a matché).", et)
        return {"ok": True, "processed": False, "type": et,
                "clients_result": clients_result}

    _mark_processed(event.get("id"))
    return {"ok": True, "processed": True, "type": et,
            "saas": saas_payload,
            "clients_result": clients_result}


# ---------------------------------------------------------------------------
# Handlers individuels
# ---------------------------------------------------------------------------
def _handle_checkout_completed(session: dict) -> dict:
    """Fin de la session de checkout = paiement initial OK."""
    ws_id = (session.get("client_reference_id")
             or (session.get("metadata") or {}).get("workspace_id"))
    if not ws_id:
        return {"warning": "checkout.session sans workspace_id"}

    customer_id = session.get("customer")
    subscription_id = session.get("subscription")
    modules_csv = (session.get("metadata") or {}).get("modules", "essential")
    modules = [m.strip() for m in modules_csv.split(",") if m.strip()]

    _upsert_subscription(
        workspace_id=ws_id,
        stripe_customer_id=customer_id,
        stripe_subscription_id=subscription_id,
        modules=modules,
        status="trialing",
    )
    return {"workspace_id": ws_id, "subscription_id": subscription_id}


def _handle_subscription_updated(sub: dict) -> dict:
    """Plan changé, ou modules ajoutés/retirés."""
    ws_id = ((sub.get("metadata") or {}).get("workspace_id")
             or _workspace_from_subscription_id(sub.get("id")))
    if not ws_id:
        return {"warning": "subscription sans workspace_id résolvable"}

    # Récupère les modules à partir des items de la subscription
    items = (sub.get("items") or {}).get("data") or []
    modules = _modules_from_items(items)

    _upsert_subscription(
        workspace_id=ws_id,
        stripe_customer_id=sub.get("customer"),
        stripe_subscription_id=sub.get("id"),
        modules=modules,
        status=sub.get("status", "active"),
        current_period_start=sub.get("current_period_start"),
        current_period_end=sub.get("current_period_end"),
        cancel_at_period_end=sub.get("cancel_at_period_end", False),
    )
    return {"workspace_id": ws_id, "modules": modules}


def _handle_subscription_deleted(sub: dict) -> dict:
    """Résiliation effective : on marque la subscription canceled."""
    ws_id = ((sub.get("metadata") or {}).get("workspace_id")
             or _workspace_from_subscription_id(sub.get("id")))
    if not ws_id:
        return {"warning": "subscription sans workspace_id résolvable"}
    _patch_subscription(
        workspace_id=ws_id,
        patch={"status": "canceled",
               "has_essential": False, "has_pro": False, "has_phare": False},
    )
    return {"workspace_id": ws_id}


def _handle_payment_failed(invoice: dict) -> dict:
    sub_id = invoice.get("subscription")
    if not sub_id:
        return {}
    ws_id = _workspace_from_subscription_id(sub_id)
    if ws_id:
        _patch_subscription(workspace_id=ws_id, patch={"status": "past_due"})
    return {"workspace_id": ws_id}


def _handle_payment_succeeded(invoice: dict) -> dict:
    sub_id = invoice.get("subscription")
    if not sub_id:
        return {}
    ws_id = _workspace_from_subscription_id(sub_id)
    if ws_id:
        _patch_subscription(workspace_id=ws_id, patch={"status": "active"})

    # Émet la facture Triskell FR-conforme + envoi mail au workspace.
    # Non bloquant : si la facturation échoue, la subscription reste active.
    result = {"workspace_id": ws_id}
    try:
        from .invoice_emit import emit_from_stripe_invoice
        emit_result = emit_from_stripe_invoice(invoice)
        result["billing"] = emit_result
    except Exception as exc:
        logger.exception("emit_from_stripe_invoice a planté")
        result["billing"] = {"ok": False, "error": f"emit crash: {exc}"}
    return result


_HANDLERS = {
    "checkout.session.completed":     _handle_checkout_completed,
    "customer.subscription.updated":  _handle_subscription_updated,
    "customer.subscription.created":  _handle_subscription_updated,
    "customer.subscription.deleted":  _handle_subscription_deleted,
    "invoice.payment_failed":         _handle_payment_failed,
    "invoice.payment_succeeded":      _handle_payment_succeeded,
}


# ---------------------------------------------------------------------------
# Helpers DB — Supabase (service_role)
# ---------------------------------------------------------------------------
def _service_sb():
    """Renvoie un client Supabase service_role pour écrire malgré la RLS."""
    try:
        from .. import clients_master_repo
        return clients_master_repo._service_sb()  # même config que celui-là
    except Exception:
        return None


def _upsert_subscription(
    *,
    workspace_id: str,
    stripe_customer_id: Optional[str],
    stripe_subscription_id: Optional[str],
    modules: list[str],
    status: str,
    current_period_start: Optional[int] = None,
    current_period_end: Optional[int] = None,
    cancel_at_period_end: bool = False,
) -> None:
    sb = _service_sb()
    if sb is None:
        logger.warning("_upsert_subscription : Supabase service_role indisponible")
        return

    from datetime import datetime, timezone
    def _ts(v):
        if v is None: return None
        try: return datetime.fromtimestamp(int(v), tz=timezone.utc).isoformat()
        except Exception: return None

    from .plans import plan_for_modules, PLANS
    plan_code = plan_for_modules(modules)
    amount = sum(PLANS[m].monthly_cents for m in modules if m in PLANS)

    row = {
        "workspace_id":           workspace_id,
        "stripe_customer_id":     stripe_customer_id,
        "stripe_subscription_id": stripe_subscription_id,
        "status":                 status,
        "plan_code":              plan_code,
        "has_essential":          "essential" in modules,
        "has_pro":                "pro" in modules,
        "has_phare":              "phare" in modules,
        "amount_monthly_cents":   amount,
        "current_period_start":   _ts(current_period_start),
        "current_period_end":     _ts(current_period_end),
        "cancel_at_period_end":   cancel_at_period_end,
    }
    sb.table("saas_subscriptions").upsert(
        row, on_conflict="workspace_id"
    ).execute()


def _patch_subscription(*, workspace_id: str, patch: dict) -> None:
    sb = _service_sb()
    if sb is None:
        return
    sb.table("saas_subscriptions").update(patch).eq(
        "workspace_id", workspace_id
    ).execute()


def _workspace_from_subscription_id(subscription_id: Optional[str]) -> Optional[str]:
    if not subscription_id:
        return None
    sb = _service_sb()
    if sb is None:
        return None
    try:
        rows = (sb.table("saas_subscriptions").select("workspace_id")
                .eq("stripe_subscription_id", subscription_id)
                .limit(1).execute().data) or []
        return rows[0]["workspace_id"] if rows else None
    except Exception:
        return None


def _modules_from_items(items: list[dict]) -> list[str]:
    """Reconstitue la liste de modules depuis les items de la subscription
    en matchant chaque price_id avec notre config."""
    keys = config.stripe_keys()
    price_to_module = {
        keys["price_essential"]: "essential",
        keys["price_pro"]:       "pro",
        keys["price_phare"]:     "phare",
    }
    out = []
    for it in items:
        price = (it.get("price") or {}).get("id")
        m = price_to_module.get(price)
        if m and m not in out:
            out.append(m)
    return out or ["essential"]


def _log_event(event: dict) -> None:
    sb = _service_sb()
    if sb is None:
        return
    try:
        sb.table("stripe_events").upsert({
            "event_id": event.get("id"),
            "type":     event.get("type"),
            "payload":  event,
        }, on_conflict="event_id").execute()
    except Exception as exc:
        logger.debug("_log_event a échoué : %s", exc)


def _mark_processed(event_id: Optional[str]) -> None:
    if not event_id:
        return
    sb = _service_sb()
    if sb is None:
        return
    try:
        sb.table("stripe_events").update({"processed": True}).eq(
            "event_id", event_id
        ).execute()
    except Exception:
        pass


def _mark_error(event_id: Optional[str], err: str) -> None:
    if not event_id:
        return
    sb = _service_sb()
    if sb is None:
        return
    try:
        sb.table("stripe_events").update({"error": err}).eq(
            "event_id", event_id
        ).execute()
    except Exception:
        pass
