"""Web Push notifications — Triskell Command.

Stocke les subscriptions des utilisateurs dans Supabase
(table `triskell_command_push_subscriptions`) et envoie des
notifications via le protocole Web Push (VAPID).

Variables d'environnement requises :
- VAPID_PUBLIC_KEY  : clé publique VAPID (base64url)
- VAPID_PRIVATE_KEY : clé privée VAPID (base64url)
- VAPID_SUBJECT     : mailto: ou URL du contact (RFC 8292)

Côté front : enregistrement Service Worker + subscribe à PushManager,
puis POST /api/push/subscribe avec le JSON renvoyé par le navigateur.

Schéma table Supabase :
    create table triskell_command_push_subscriptions (
      id          uuid primary key default gen_random_uuid(),
      user_id     text not null,         -- 'jordan' ou 'thomas'
      endpoint    text unique not null,
      p256dh      text not null,
      auth_token  text not null,
      created_at  timestamptz default now(),
      last_used   timestamptz default now()
    );
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _vapid_configured() -> bool:
    return bool(os.environ.get("VAPID_PUBLIC_KEY") and os.environ.get("VAPID_PRIVATE_KEY"))


def get_public_key() -> Optional[str]:
    """Renvoie la clé publique VAPID pour que le client puisse souscrire."""
    return os.environ.get("VAPID_PUBLIC_KEY") or None


def _supabase_client():
    """Récupère le client Supabase si configuré, None sinon."""
    try:
        from triskell_core.db import get_client, SupabaseNotConfigured
        try:
            return get_client()
        except SupabaseNotConfigured:
            return None
    except Exception as exc:
        logger.debug("supabase client: %s", exc)
        return None


def save_subscription(user_id: str, subscription: dict) -> dict:
    """Enregistre une subscription côté Supabase. Idempotent (upsert sur endpoint)."""
    if not user_id:
        return {"ok": False, "error": "user_id manquant"}
    if not subscription or not isinstance(subscription, dict):
        return {"ok": False, "error": "subscription invalide"}
    endpoint = subscription.get("endpoint")
    keys = subscription.get("keys") or {}
    p256dh = keys.get("p256dh")
    auth_token = keys.get("auth")
    if not (endpoint and p256dh and auth_token):
        return {"ok": False, "error": "subscription incomplete"}

    sb = _supabase_client()
    if sb is None:
        return {"ok": False, "error": "supabase_not_configured"}
    try:
        row = {
            "user_id": user_id,
            "endpoint": endpoint,
            "p256dh": p256dh,
            "auth_token": auth_token,
        }
        sb.table("triskell_command_push_subscriptions") \
          .upsert(row, on_conflict="endpoint") \
          .execute()
        return {"ok": True}
    except Exception as exc:
        logger.warning("save_subscription failed: %s", exc)
        return {"ok": False, "error": str(exc)}


def remove_subscription(endpoint: str) -> dict:
    if not endpoint:
        return {"ok": False, "error": "endpoint manquant"}
    sb = _supabase_client()
    if sb is None:
        return {"ok": False, "error": "supabase_not_configured"}
    try:
        sb.table("triskell_command_push_subscriptions") \
          .delete().eq("endpoint", endpoint).execute()
        return {"ok": True}
    except Exception as exc:
        logger.warning("remove_subscription failed: %s", exc)
        return {"ok": False, "error": str(exc)}


def list_subscriptions(user_id: Optional[str] = None) -> list[dict]:
    """Liste toutes les subscriptions actives, ou seulement celles d'un user."""
    sb = _supabase_client()
    if sb is None:
        return []
    try:
        q = sb.table("triskell_command_push_subscriptions").select("*")
        if user_id:
            q = q.eq("user_id", user_id)
        res = q.execute()
        return res.data or []
    except Exception as exc:
        logger.debug("list_subscriptions: %s", exc)
        return []


def send_push(title: str, body: str, *,
              user_id: Optional[str] = None,
              tag: Optional[str] = None,
              tag_group: Optional[str] = None,
              url: Optional[str] = None,
              priority: str = "normal",
              actions: Optional[list] = None,
              extra_data: Optional[dict] = None) -> dict:
    """Envoie une notification push à toutes les subscriptions d'un user
    (ou à toutes si user_id est None).

    priority : 'urgent' / 'normal' / 'low'.
      - urgent : vibration forte, reste affichée jusqu'au clic, préfixe 🔴
      - normal : comportement par défaut
      - low    : silencieux, pas de vibration (utile pour les digests)

    tag_group : si plusieurs notifs avec le même tag_group arrivent dans
      les 5 min, le Service Worker les agrège en "X événements".
      Tags suggérés : 'replies', 'sales', 'clients', 'system'.

    actions : liste de {action, title, icon?} pour boutons d'action dans
      la notif (max 2, supporté seulement par Chrome).

    Renvoie {"sent": n, "failed": k, "removed": m} (les subs invalides
    sont nettoyées automatiquement).
    """
    if not _vapid_configured():
        return {"sent": 0, "failed": 0, "removed": 0, "error": "vapid_not_configured"}

    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        return {"sent": 0, "failed": 0, "removed": 0, "error": "pywebpush_not_installed"}

    subs = list_subscriptions(user_id)
    if not subs:
        return {"sent": 0, "failed": 0, "removed": 0}

    pub = os.environ["VAPID_PUBLIC_KEY"]
    priv = os.environ["VAPID_PRIVATE_KEY"]
    subject = os.environ.get("VAPID_SUBJECT") or "mailto:contact@triskell-studio.fr"

    # Validation priorité
    if priority not in ("urgent", "normal", "low"):
        priority = "normal"

    payload = json.dumps({
        "title": title,
        "body": body[:300],
        "tag": tag or "triskell-command",
        "tag_group": tag_group or tag or "triskell-command",
        "priority": priority,
        "actions": actions or [],
        "data": {**(extra_data or {}), **({"url": url} if url else {})},
    })

    sent = failed = removed = 0
    for s in subs:
        sub_info = {
            "endpoint": s.get("endpoint"),
            "keys": {"p256dh": s.get("p256dh"), "auth": s.get("auth_token")},
        }
        try:
            webpush(
                subscription_info=sub_info,
                data=payload,
                vapid_private_key=priv,
                vapid_claims={"sub": subject},
            )
            sent += 1
        except Exception as exc:
            failed += 1
            # Si 404/410 → subscription expirée, on la retire
            status = getattr(exc, "response", None)
            code = getattr(status, "status_code", None) if status is not None else None
            if code in (404, 410):
                remove_subscription(s.get("endpoint"))
                removed += 1
            else:
                logger.debug("push to %s failed: %s", (s.get("endpoint") or "")[:60], exc)

    # Mute le warning unused
    _ = WebPushException
    _ = pub

    return {"sent": sent, "failed": failed, "removed": removed}
