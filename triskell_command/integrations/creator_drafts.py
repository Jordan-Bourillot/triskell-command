"""Brouillons de mails pour les créateurs du carnet (`contacted_creators`).

Permet de faire apparaître les créateurs dans l'écran « Brouillons à valider »
(source = `creator`) et de les envoyer en 1 clic, comme les prospects — SANS
toucher au flux de prospection PME (purement additif).

Stockés dans `shared_settings['creator_drafts']` (liste de dicts) : PAS de
nouvelle table, donc RIEN à migrer côté Supabase. Le CORPS du mail n'est pas
dupliqué — il vient du champ `message` de la fiche créateur, lu au moment de
l'affichage et de l'envoi (un seul endroit de vérité). On ne stocke ici que
l'état du brouillon : id, créateur lié, sujet, adresse d'expéditeur exigée,
statut (pending / sent / rejected).
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from .shared_settings_db import upsert_setting

logger = logging.getLogger(__name__)
KEY = "creator_drafts"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read(sb) -> list:
    """Liste brute des brouillons créateurs (jamais lève)."""
    if sb is None:
        return []
    try:
        rows = (sb.table("shared_settings").select("value")
                .eq("key", KEY).limit(1).execute().data) or []
        if rows:
            v = rows[0].get("value")
            if isinstance(v, list):
                return v
    except Exception as exc:
        logger.warning("creator_drafts._read: %s", exc)
    return []


def _write(sb, items: list) -> bool:
    return upsert_setting(sb, KEY, items)


def list_all(sb, status: str | None = None) -> list:
    items = _read(sb)
    if status:
        items = [d for d in items if (d.get("status") or "pending") == status]
    return items


def get(sb, draft_id: str) -> dict | None:
    for d in _read(sb):
        if d.get("id") == draft_id:
            return d
    return None


def queue(sb, creator_id: str, subject: str, sender_address: str = "") -> dict | None:
    """Met (ou remplace) un brouillon `pending` pour ce créateur."""
    if sb is None or not creator_id:
        return None
    items = _read(sb)
    # Un seul brouillon en attente par créateur : on écarte l'ancien pending.
    items = [d for d in items
             if not (d.get("creator_id") == creator_id
                     and (d.get("status") or "pending") == "pending")]
    draft = {
        "id": uuid.uuid4().hex,
        "creator_id": creator_id,
        "subject": (subject or "").strip(),
        "sender_address": (sender_address or "").strip(),
        "status": "pending",
        "created_at": _now(),
    }
    items.append(draft)
    return draft if _write(sb, items) else None


def set_status(sb, draft_id: str, status: str) -> bool:
    items = _read(sb)
    found = False
    for d in items:
        if d.get("id") == draft_id:
            d["status"] = status
            if status == "sent":
                d["sent_at"] = _now()
            found = True
    if found:
        _write(sb, items)
    return found
