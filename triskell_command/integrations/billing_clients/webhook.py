"""Handlers Stripe pour les abonnements des CLIENTS FINAUX de Triskell.

Ce module reçoit les mêmes évènements Stripe que `billing_saas/webhook.py`
mais les filtre par metadata (`client_subscription_id` présent dans la
subscription metadata). Sans cette metadata, le handler ne fait rien et
laisse `billing_saas` gérer.

Évènements pris en charge :
- customer.subscription.created / updated → upsert client_subscriptions
- customer.subscription.deleted           → status=canceled
- invoice.payment_succeeded               → status=active + émission facture FR
- invoice.payment_failed                  → status=past_due

L'envoi de la facture par mail est géré par `invoice_emit.py`.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------
def maybe_handle_event(event: dict[str, Any]) -> dict[str, Any]:
    """Si l'event est lié à un client_subscription Triskell, on traite.
    Sinon, on renvoie {processed: False}.
    """
    et = event.get("type", "")
    obj = (event.get("data") or {}).get("object") or {}

    # On ne route que les évènements potentiellement liés à un abonnement
    if et not in _HANDLERS:
        return {"ok": True, "processed": False, "type": et}

    # Filtre par metadata : c'est NOTRE event si client_subscription_id présent
    metadata = _gather_metadata_from_event(obj, et)
    if not metadata.get("client_subscription_id"):
        return {"ok": True, "processed": False, "type": et,
                "skipped_reason": "no client_subscription_id"}

    handler = _HANDLERS[et]
    try:
        result = handler(obj, metadata) or {}
        return {"ok": True, "processed": True, "type": et, **result}
    except Exception as exc:
        logger.exception("billing_clients handler %s a échoué", et)
        return {"ok": False, "processed": False, "type": et,
                "error": str(exc)}


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------
def _handle_subscription_upsert(sub: dict, metadata: dict) -> dict:
    """Stripe `customer.subscription.created` ou `.updated`."""
    sub_row_id = metadata.get("client_subscription_id")
    if not sub_row_id:
        return {}

    patch: dict[str, Any] = {
        "stripe_subscription_id": sub.get("id"),
        "stripe_customer_id":     sub.get("customer"),
        "status":                 sub.get("status") or "incomplete",
        "current_period_start":   _ts_iso(sub.get("current_period_start")),
        "current_period_end":     _ts_iso(sub.get("current_period_end")),
        "cancel_at_period_end":   bool(sub.get("cancel_at_period_end")),
    }
    if sub.get("status") == "active" and not _has_started_at(sub_row_id):
        patch["started_at"] = datetime.now(timezone.utc).isoformat()

    _patch(sub_row_id, patch)
    return {"client_subscription_id": sub_row_id,
            "status": patch["status"]}


def _handle_subscription_deleted(sub: dict, metadata: dict) -> dict:
    sub_row_id = metadata.get("client_subscription_id")
    if not sub_row_id:
        return {}
    _patch(sub_row_id, {
        "status": "canceled",
        "canceled_at": datetime.now(timezone.utc).isoformat(),
        "cancel_at_period_end": False,
    })
    return {"client_subscription_id": sub_row_id}


def _handle_payment_succeeded(invoice: dict, metadata: dict) -> dict:
    sub_row_id = metadata.get("client_subscription_id")
    if sub_row_id:
        _patch(sub_row_id, {"status": "active"})

    # Émet la facture FR conforme + envoi mail (non bloquant)
    try:
        from .invoice_emit import emit_from_stripe_invoice
        emit_result = emit_from_stripe_invoice(invoice)
        return {"client_subscription_id": sub_row_id, "billing": emit_result}
    except Exception as exc:
        logger.exception("emit_from_stripe_invoice (client) a planté")
        return {"client_subscription_id": sub_row_id,
                "billing": {"ok": False, "error": f"emit crash: {exc}"}}


def _handle_payment_failed(invoice: dict, metadata: dict) -> dict:
    sub_row_id = metadata.get("client_subscription_id")
    if not sub_row_id:
        return {}
    _patch(sub_row_id, {"status": "past_due"})
    return {"client_subscription_id": sub_row_id}


_HANDLERS = {
    "customer.subscription.created": _handle_subscription_upsert,
    "customer.subscription.updated": _handle_subscription_upsert,
    "customer.subscription.deleted": _handle_subscription_deleted,
    "invoice.payment_succeeded":     _handle_payment_succeeded,
    "invoice.payment_failed":        _handle_payment_failed,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _gather_metadata_from_event(obj: dict, event_type: str) -> dict:
    """Cherche la metadata dans plusieurs endroits selon le type d'event."""
    metadata = dict(obj.get("metadata") or {})

    # Pour les events invoice.*, la metadata utile est dans
    # `subscription_details.metadata` (et parfois copiée sur l'invoice).
    if event_type.startswith("invoice."):
        sd = obj.get("subscription_details") or {}
        if isinstance(sd.get("metadata"), dict):
            for k, v in sd["metadata"].items():
                metadata.setdefault(k, v)
        # Fallback : 1ère ligne
        sline = (((obj.get("lines") or {}).get("data") or [{}])[0])
        for k, v in (sline.get("metadata") or {}).items():
            metadata.setdefault(k, v)

    return metadata


def _ts_iso(ts) -> Optional[str]:
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(int(ts),
                                       tz=timezone.utc).isoformat()
    except Exception:
        return None


def _sb():
    try:
        from ..billing import repo as billing_repo
        return billing_repo._sb()
    except Exception:
        return None


def _has_started_at(sub_row_id: str) -> bool:
    sb = _sb()
    if sb is None:
        return False
    try:
        rows = (sb.table("client_subscriptions").select("started_at")
                .eq("id", sub_row_id).limit(1).execute().data) or []
        return bool(rows and rows[0].get("started_at"))
    except Exception:
        return False


def _patch(sub_row_id: str, patch: dict) -> None:
    if not sub_row_id:
        return
    sb = _sb()
    if sb is None:
        return
    try:
        sb.table("client_subscriptions").update(patch).eq(
            "id", sub_row_id
        ).execute()
    except Exception as exc:
        logger.debug("_patch: %s", exc)
