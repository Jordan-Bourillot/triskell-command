"""Repo client_projects — CRUD léger pour la vue Clients.

API minimale pour la vue kanban :
- list_projects(status?) → list[dict]
- create_project(payload) → dict|None
- update_project(id, patch) → bool
- transition(id, new_status) → bool
- record_payment(stripe_session_id, ...) → dict (idempotent)

Toutes les fonctions retombent à no-op si Supabase non auth.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)


STATUSES = ("briefing", "in_progress", "delivered", "closed")
PRIORITIES = ("low", "normal", "high")


def _client():
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


def list_projects(status: Optional[str] = None) -> list[dict]:
    c = _client()
    if c is None:
        return []
    try:
        q = c.raw.table("client_projects").select("*")
        if status and status in STATUSES:
            q = q.eq("status", status)
        res = q.order("created_at", desc=True).limit(500).execute()
        return list(res.data or [])
    except Exception as exc:
        logger.warning("list_projects: %s", exc)
        return []


def list_grouped() -> dict[str, list[dict]]:
    """Renvoie {status: [projects...]} pour le rendu kanban."""
    out: dict[str, list[dict]] = {s: [] for s in STATUSES}
    for p in list_projects():
        s = p.get("status") or "briefing"
        out.setdefault(s, []).append(p)
    return out


def get_project(project_id: str) -> Optional[dict]:
    c = _client()
    if c is None:
        return None
    try:
        res = (c.raw.table("client_projects").select("*")
               .eq("id", project_id).limit(1).execute())
        return (res.data or [None])[0]
    except Exception as exc:
        logger.warning("get_project: %s", exc)
        return None


def create_project(payload: dict) -> Optional[dict]:
    c = _client()
    if c is None:
        return None
    p = dict(payload or {})
    p.setdefault("status", "briefing")
    p["created_by"] = c.user_id
    p["updated_by"] = c.user_id
    try:
        res = c.raw.table("client_projects").insert(p).execute()
        return (res.data or [None])[0]
    except Exception as exc:
        logger.warning("create_project: %s", exc)
        return None


def update_project(project_id: str, patch: dict) -> bool:
    c = _client()
    if c is None:
        return False
    p = dict(patch or {})
    p["updated_by"] = c.user_id
    try:
        c.raw.table("client_projects").update(p).eq("id", project_id).execute()
        return True
    except Exception as exc:
        logger.warning("update_project: %s", exc)
        return False


def transition(project_id: str, new_status: str) -> bool:
    if new_status not in STATUSES:
        return False
    return update_project(project_id, {"status": new_status})


def record_payment(stripe_session_id: str, *, prospect_id: str = "",
                    product_key: str = "", product_name: str = "",
                    client_email: str = "", client_name: str = "",
                    amount_cents: int = 0, currency: str = "EUR") -> Optional[dict]:
    """Crée un projet client à partir d'un événement de paiement.

    Idempotent : si un projet existe déjà avec ce stripe_session_id, on le
    renvoie sans en créer un nouveau. Conçu pour être appelé par un futur
    webhook Stripe → Supabase, ou manuellement depuis la vue Clients.
    """
    c = _client()
    if c is None:
        return None
    if stripe_session_id:
        try:
            res = (c.raw.table("client_projects").select("*")
                   .eq("stripe_session_id", stripe_session_id)
                   .limit(1).execute())
            if res.data:
                return res.data[0]
        except Exception as exc:
            logger.debug("record_payment lookup: %s", exc)
    payload = {
        "prospect_id": prospect_id or None,
        "title": (product_name or product_key or "Nouveau projet").title(),
        "product_key": product_key,
        "product_name": product_name or product_key,
        "status": "briefing",
        "client_email": client_email,
        "client_name": client_name,
        "amount_cents": int(amount_cents or 0),
        "currency": currency or "EUR",
        "paid_at": datetime.now().isoformat(timespec="seconds"),
        "stripe_session_id": stripe_session_id,
    }
    return create_project(payload)
