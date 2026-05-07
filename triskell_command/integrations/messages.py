"""Chat 1-à-1 Jordan ↔ Thomas via la table Supabase `messages`.

API minimale, conçue pour être appelée depuis le widget de chat :
- `list_messages()`     — historique chronologique entre les 2 users
- `send_message(body)`  — envoie un message à l'autre user
- `mark_all_read()`     — marque comme lus tous les messages reçus
- `count_unread()`      — combien de messages non lus pour pastille FAB
- `other_user()`        — métadonnées de l'autre user (display_name, color)

Tout fonctionne uniquement quand Supabase est configuré + l'user loggé.
Sinon les fonctions renvoient des structures vides sans lever — l'UI doit
juste afficher un état "indisponible". Pas de fallback local : un chat
hors-ligne n'a pas de sens (Thomas est sur l'autre machine).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _client():
    """Retourne (client, user_id) si Supabase est dispo + loggé, sinon (None, None)."""
    try:
        from triskell_core.db import get_client, SupabaseNotConfigured
    except ImportError:
        return None, None
    try:
        c = get_client()
    except Exception:
        return None, None
    if not c.is_authenticated:
        return None, None
    return c, c.user_id


def other_user() -> dict[str, Any] | None:
    """Renvoie le profil de l'autre user (Jordan voit Thomas, Thomas voit Jordan).

    Renvoie None si pas loggé, ou si on est seul dans la table users."""
    c, me = _client()
    if c is None or me is None:
        return None
    try:
        res = (c.raw.table("users")
               .select("user_id, display_name, color")
               .neq("user_id", me).limit(1).execute())
        data = res.data or []
        return data[0] if data else None
    except Exception as exc:
        logger.debug("other_user: %s", exc)
        return None


def list_messages(limit: int = 100) -> list[dict[str, Any]]:
    """Renvoie les `limit` derniers messages échangés avec l'autre user,
    ordre chronologique ascendant (plus ancien d'abord)."""
    c, me = _client()
    if c is None or me is None:
        return []
    other = other_user()
    if other is None:
        return []
    other_id = other["user_id"]
    try:
        # On veut (sender=me, recipient=other) UNION (sender=other, recipient=me).
        # supabase-py n'a pas d'OR sur 2 paires, donc 2 requêtes + merge côté client.
        sent = (c.raw.table("messages")
                .select("id, sender_id, recipient_id, body, created_at, read_at")
                .eq("sender_id", me).eq("recipient_id", other_id)
                .order("created_at", desc=True).limit(limit).execute())
        recv = (c.raw.table("messages")
                .select("id, sender_id, recipient_id, body, created_at, read_at")
                .eq("sender_id", other_id).eq("recipient_id", me)
                .order("created_at", desc=True).limit(limit).execute())
        merged = (sent.data or []) + (recv.data or [])
        merged.sort(key=lambda m: m.get("created_at") or "")
        # Garde les `limit` plus récents si l'union dépasse
        if len(merged) > limit:
            merged = merged[-limit:]
        return merged
    except Exception as exc:
        logger.debug("list_messages: %s", exc)
        return []


def send_message(body: str) -> dict[str, Any] | None:
    """Envoie un message à l'autre user. Renvoie la ligne insérée ou None."""
    body = (body or "").strip()
    if not body:
        return None
    c, me = _client()
    if c is None or me is None:
        return None
    other = other_user()
    if other is None:
        return None
    try:
        res = (c.raw.table("messages")
               .insert({
                   "sender_id": me,
                   "recipient_id": other["user_id"],
                   "body": body,
               }).execute())
        data = res.data or []
        return data[0] if data else None
    except Exception as exc:
        logger.warning("send_message: %s", exc)
        return None


def mark_all_read() -> int:
    """Marque comme lus tous les messages reçus encore non lus.
    Renvoie le nombre de messages mis à jour (ou 0 si erreur)."""
    c, me = _client()
    if c is None or me is None:
        return 0
    from datetime import datetime, timezone
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        res = (c.raw.table("messages")
               .update({"read_at": now_iso})
               .eq("recipient_id", me).is_("read_at", "null").execute())
        return len(res.data or [])
    except Exception as exc:
        logger.debug("mark_all_read: %s", exc)
        return 0


def count_unread() -> int:
    """Nombre de messages reçus non lus. 0 si pas loggé / erreur."""
    c, me = _client()
    if c is None or me is None:
        return 0
    try:
        res = (c.raw.table("messages")
               .select("id", count="exact")
               .eq("recipient_id", me).is_("read_at", "null").execute())
        return int(getattr(res, "count", 0) or 0)
    except Exception as exc:
        logger.debug("count_unread: %s", exc)
        return 0


def last_message_preview() -> dict | None:
    """Renvoie le dernier message échangé avec l'autre user, sous la forme
    {body, created_at, is_from_me}. None si pas dispo."""
    c, me = _client()
    if c is None or me is None:
        return None
    other = other_user()
    if other is None:
        return None
    other_id = other["user_id"]
    try:
        # 2 requêtes (une dans chaque sens), on prend la plus récente.
        sent = (c.raw.table("messages")
                .select("body, created_at, sender_id")
                .eq("sender_id", me).eq("recipient_id", other_id)
                .order("created_at", desc=True).limit(1).execute())
        recv = (c.raw.table("messages")
                .select("body, created_at, sender_id")
                .eq("sender_id", other_id).eq("recipient_id", me)
                .order("created_at", desc=True).limit(1).execute())
        candidates = (sent.data or []) + (recv.data or [])
        if not candidates:
            return None
        candidates.sort(key=lambda m: m.get("created_at") or "", reverse=True)
        m = candidates[0]
        return {
            "body": m.get("body") or "",
            "created_at": m.get("created_at") or "",
            "is_from_me": m.get("sender_id") == me,
        }
    except Exception as exc:
        logger.debug("last_message_preview: %s", exc)
        return None


# ---------------------------------------------------------------------
# Indicateur « X est en train d'écrire »
# ---------------------------------------------------------------------
TYPING_TTL_SECONDS = 5      # combien de temps un "il écrit" reste valide


def set_typing(active: bool = True) -> bool:
    """Marque que l'utilisateur courant tape. UPSERT sur typing_status :
    `until_ts = now() + TYPING_TTL_SECONDS` si active, sinon now() (expiré).

    À throttler côté caller (ex: 1 appel max toutes les 2 s).
    Renvoie True si l'écriture a réussi.
    """
    c, me = _client()
    if c is None or me is None:
        return False
    from datetime import datetime, timezone, timedelta
    if active:
        ts = datetime.now(timezone.utc) + timedelta(seconds=TYPING_TTL_SECONDS)
    else:
        ts = datetime.now(timezone.utc)
    try:
        (c.raw.table("typing_status")
         .upsert({"user_id": me, "until_ts": ts.isoformat()},
                  on_conflict="user_id").execute())
        return True
    except Exception as exc:
        logger.debug("set_typing: %s", exc)
        return False


def peer_is_typing() -> bool:
    """True si l'autre user a un until_ts > now() dans typing_status."""
    c, me = _client()
    if c is None or me is None:
        return False
    other = other_user()
    if other is None:
        return False
    try:
        from datetime import datetime, timezone
        now_iso = datetime.now(timezone.utc).isoformat()
        res = (c.raw.table("typing_status")
               .select("until_ts")
               .eq("user_id", other["user_id"])
               .gt("until_ts", now_iso).limit(1).execute())
        return bool(res.data)
    except Exception as exc:
        logger.debug("peer_is_typing: %s", exc)
        return False
