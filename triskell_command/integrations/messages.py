"""Chat 1-à-1 Jordan ↔ Thomas via la table Supabase `messages`.

API minimale, conçue pour être appelée depuis le widget de chat :
- `list_messages()`      — historique chronologique entre les 2 users
- `send_message(body)`   — envoie un message à l'autre user
- `mark_all_read()`      — marque comme lus tous les messages reçus
- `count_unread()`       — combien de messages non lus pour pastille FAB
- `other_user()`         — métadonnées de l'autre user (display_name)
- `last_message_preview()` — dernier message pour tooltip / aperçu
- `set_typing()` / `peer_is_typing()` — indicateur « X écrit »

Identité — IMPORTANT :
    Jordan & Thomas partagent un MÊME compte Supabase. L'identification
    "qui parle" se fait donc via le **cookie de session local** posé par
    web/auth.py (`jordan` ou `thomas`). Le middleware HTTP pose cette
    valeur dans un contextvar avant chaque appel API ; on la relit via
    `web.auth.get_current_local_user()`.

Stockage — la table Supabase `messages` sert juste de bus partagé entre
les 2 PC. Ses colonnes sender_id / recipient_id sont du `text`
('jordan' / 'thomas') depuis la migration 29_chat_local_users.sql.

Si Supabase est indispo OU si on n'a pas d'identité locale, tout renvoie
des structures vides sans lever — l'UI affiche un état "indisponible".
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Participant virtuel : Claude poste dans le chat depuis le mode vocal
# (Allo Claude). Il n'a pas de session, ses messages sont insérés
# server-side via send_from_claude().
CLAUDE_USER_ID = "claude"
_HUMAN_USERS = ("jordan", "thomas")


def _supabase():
    """Retourne le client Supabase brut si dispo + loggé, sinon None."""
    try:
        from triskell_core.db import get_client
    except ImportError:
        return None
    try:
        c = get_client()
    except Exception:
        return None
    if not c.is_authenticated:
        return None
    return c


def _me() -> Optional[str]:
    """Identité locale (jordan/thomas) de la requête HTTP en cours."""
    try:
        from ..web.auth import get_current_local_user
        return get_current_local_user()
    except Exception:
        return None


def _opposite(user_id: Optional[str]) -> Optional[str]:
    """L'autre membre du binôme (jordan ↔ thomas)."""
    if user_id == "jordan":
        return "thomas"
    if user_id == "thomas":
        return "jordan"
    return None


def other_user() -> Optional[dict[str, Any]]:
    """Profil de l'autre user (Jordan voit Thomas, Thomas voit Jordan).
    Renvoie None si on n'a pas d'identité locale (pas loggé)."""
    me = _me()
    other = _opposite(me)
    if not other:
        return None
    try:
        from ..web.auth import get_display_name
        display = get_display_name(other)
    except Exception:
        display = other.capitalize()
    return {
        "user_id": other,
        "display_name": display,
        "color": None,
    }


# Colonnes de base toujours présentes. `delivered_at` (statut « distribué »)
# est ajouté dynamiquement SI la colonne existe — c'est la migration
# 44_chat_delivered.sql qui la crée. Tant qu'elle n'est pas appliquée, on ne
# la sélectionne pas (sinon Supabase renverrait une erreur et le chat
# resterait vide) : on dégrade alors proprement vers « envoyé / lu ».
_MSG_COLUMNS_BASE = ("id, sender_id, recipient_id, body, created_at, read_at, "
                     "attachment_url, attachment_name, attachment_type, attachment_size, "
                     "reply_to_id, edited_at, deleted_at")

# Cache de disponibilité de la colonne delivered_at :
#   True       → confirmée présente, on ne re-teste plus.
#   None/False → pas (encore) confirmée → on re-teste au prochain appel, ce
#                qui permet à la fonctionnalité de s'activer dès que la
#                migration est appliquée, sans redémarrer le serveur.
_delivered_col_ok: Optional[bool] = None


def _delivered_supported(c) -> bool:
    """True si la colonne messages.delivered_at existe (migration 44)."""
    global _delivered_col_ok
    if _delivered_col_ok is True:
        return True
    try:
        c.raw.table("messages").select("delivered_at").limit(1).execute()
        _delivered_col_ok = True
    except Exception:
        _delivered_col_ok = False
    return bool(_delivered_col_ok)


def _msg_columns(c) -> str:
    """Colonnes à sélectionner, avec delivered_at si la colonne existe."""
    if _delivered_supported(c):
        return _MSG_COLUMNS_BASE + ", delivered_at"
    return _MSG_COLUMNS_BASE


def list_messages(limit: int = 100) -> list[dict[str, Any]]:
    """Renvoie les `limit` derniers messages échangés avec l'autre user,
    ordre chronologique ascendant (plus ancien d'abord).

    Chaque message est enrichi d'un champ `reactions` (liste de
    {user_id, emoji}) — vide s'il n'y en a pas. Les réactions sont
    chargées en UNE seule requête pour tous les messages affichés."""
    me = _me()
    other = _opposite(me)
    c = _supabase()
    if c is None or not me or not other:
        return []
    try:
        cols = _msg_columns(c)
        # supabase-py n'a pas d'OR sur 2 paires (sender,recipient) — on fait
        # 2 requêtes (sens aller + retour) et on merge côté client.
        sent = (c.raw.table("messages")
                .select(cols)
                .eq("sender_id", me).eq("recipient_id", other)
                .order("created_at", desc=True).limit(limit).execute())
        recv = (c.raw.table("messages")
                .select(cols)
                .eq("sender_id", other).eq("recipient_id", me)
                .order("created_at", desc=True).limit(limit).execute())
        # 3e requête : messages postés par Claude (mode vocal Allo Claude).
        # On les affiche aux deux humains, peu importe le destinataire
        # initial — le chat fonctionne comme un fil partagé où Claude
        # est un participant visible des deux côtés.
        claude_q = (c.raw.table("messages")
                    .select(cols)
                    .eq("sender_id", CLAUDE_USER_ID)
                    .in_("recipient_id", list(_HUMAN_USERS))
                    .order("created_at", desc=True).limit(limit).execute())
        merged = (sent.data or []) + (recv.data or []) + (claude_q.data or [])
        merged.sort(key=lambda m: m.get("created_at") or "")
        if len(merged) > limit:
            merged = merged[-limit:]
        # Enrichit avec les réactions (1 requête pour tous les messages).
        ids = [m.get("id") for m in merged if m.get("id")]
        if ids:
            try:
                rx = (c.raw.table("message_reactions")
                      .select("message_id, user_id, emoji")
                      .in_("message_id", ids).execute())
                by_msg: dict[str, list[dict]] = {}
                for r in (rx.data or []):
                    by_msg.setdefault(r["message_id"], []).append({
                        "user_id": r.get("user_id"),
                        "emoji":   r.get("emoji"),
                    })
                for m in merged:
                    m["reactions"] = by_msg.get(m.get("id"), [])
            except Exception as exc:
                logger.debug("list_messages reactions: %s", exc)
                for m in merged:
                    m.setdefault("reactions", [])
        else:
            for m in merged:
                m["reactions"] = []
        return merged
    except Exception as exc:
        logger.debug("list_messages: %s", exc)
        return []


def toggle_reaction(message_id: str, emoji: str) -> Optional[dict[str, Any]]:
    """Pose ou retire une réaction sur un message.

    Logique "toggle" : si l'utilisateur courant a déjà ce même emoji sur
    ce message, on le retire ; sinon on l'ajoute.
    Renvoie {action: 'added'|'removed', emoji: '…'} ou None en erreur."""
    me = _me()
    c = _supabase()
    emoji = (emoji or "").strip()
    if c is None or not me or not message_id or not emoji:
        return None
    try:
        existing = (c.raw.table("message_reactions")
                    .select("id")
                    .eq("message_id", message_id)
                    .eq("user_id", me)
                    .eq("emoji", emoji)
                    .limit(1).execute())
        if existing.data:
            # Déjà posée → on retire (toggle off)
            (c.raw.table("message_reactions")
             .delete().eq("id", existing.data[0]["id"]).execute())
            return {"action": "removed", "emoji": emoji}
        # Pas encore posée → on ajoute
        (c.raw.table("message_reactions")
         .insert({"message_id": message_id, "user_id": me, "emoji": emoji})
         .execute())
        return {"action": "added", "emoji": emoji}
    except Exception as exc:
        logger.warning("toggle_reaction: %s", exc)
        return None


def send_message(
    body: str,
    attachment: Optional[dict[str, Any]] = None,
    reply_to_id: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Envoie un message à l'autre user. Renvoie la ligne insérée ou None.

    `attachment`, si fourni, est un dict {url, name, type, size} produit
    par l'endpoint d'upload (POST /api/chat_attachment).
    `reply_to_id`, si fourni, référence l'ID du message auquel on répond.
    Le message doit avoir AU MOINS un body OU une pièce jointe."""
    body = (body or "").strip()
    has_attachment = bool(attachment and attachment.get("url"))
    if not body and not has_attachment:
        return None
    me = _me()
    other = _opposite(me)
    c = _supabase()
    if c is None or not me or not other:
        return None
    row: dict[str, Any] = {
        "sender_id": me,
        "recipient_id": other,
        "body": body if body else None,
    }
    if has_attachment:
        row["attachment_url"]  = attachment.get("url")
        row["attachment_name"] = attachment.get("name") or None
        row["attachment_type"] = attachment.get("type") or None
        size = attachment.get("size")
        if isinstance(size, int) and size > 0:
            row["attachment_size"] = size
    if reply_to_id:
        row["reply_to_id"] = str(reply_to_id)
    try:
        res = c.raw.table("messages").insert(row).execute()
        data = res.data or []
        return data[0] if data else None
    except Exception as exc:
        logger.warning("send_message: %s", exc)
        return None


def send_from_claude(body: str, recipient: str) -> Optional[dict[str, Any]]:
    """Poste un message dans le chat **de la part de Claude** (mode vocal
    Allo Claude). sender_id = 'claude', recipient = 'jordan' ou 'thomas'.

    Utilisé quand Jordan dicte « dis à Thomas que… » via le mode vocal :
    Claude rédige le message, le serveur l'insère ici. Les deux humains
    voient ce message dans leur chat grâce au 3e filtre de list_messages().
    Renvoie la ligne insérée ou None en erreur.
    """
    body = (body or "").strip()
    recipient = (recipient or "").strip().lower()
    if not body:
        return None
    if recipient not in _HUMAN_USERS:
        logger.warning("send_from_claude: destinataire invalide %r", recipient)
        return None
    c = _supabase()
    if c is None:
        return None
    row = {
        "sender_id": CLAUDE_USER_ID,
        "recipient_id": recipient,
        "body": body,
    }
    try:
        res = c.raw.table("messages").insert(row).execute()
        data = res.data or []
        return data[0] if data else None
    except Exception as exc:
        logger.warning("send_from_claude: %s", exc)
        return None


def edit_message(message_id: str, new_body: str) -> Optional[dict[str, Any]]:
    """Modifie le texte d'un message DÉJÀ envoyé.

    Sécurité : on ne peut éditer QUE ses propres messages (filtré côté
    serveur via `sender_id == _me()`).
    Renvoie la ligne mise à jour, ou None si rien n'a changé (pas
    autorisé, message introuvable, body vide…)."""
    me = _me()
    c = _supabase()
    if c is None or not me or not message_id:
        return None
    new_body = (new_body or "").strip()
    if not new_body:
        return None
    from datetime import datetime, timezone
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        res = (c.raw.table("messages")
               .update({"body": new_body, "edited_at": now_iso})
               .eq("id", message_id).eq("sender_id", me)
               .execute())
        data = res.data or []
        return data[0] if data else None
    except Exception as exc:
        logger.warning("edit_message: %s", exc)
        return None


def delete_message(message_id: str) -> Optional[dict[str, Any]]:
    """Soft-delete : pose `deleted_at = now()` sur un message.

    Sécurité : seul l'expéditeur peut supprimer son propre message.
    On garde la ligne en base (les réactions et réponses qui pointent
    dessus restent cohérentes) — l'UI affichera "Message supprimé".
    Renvoie la ligne mise à jour, ou None si pas autorisé."""
    me = _me()
    c = _supabase()
    if c is None or not me or not message_id:
        return None
    from datetime import datetime, timezone
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        res = (c.raw.table("messages")
               .update({"deleted_at": now_iso})
               .eq("id", message_id).eq("sender_id", me)
               .execute())
        data = res.data or []
        return data[0] if data else None
    except Exception as exc:
        logger.warning("delete_message: %s", exc)
        return None


def mark_all_read() -> int:
    """Marque comme lus tous les messages reçus encore non lus.
    Renvoie le nombre de messages mis à jour (ou 0 si erreur)."""
    me = _me()
    c = _supabase()
    if c is None or not me:
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


def mark_all_delivered() -> int:
    """Marque comme « distribués » tous les messages reçus pas encore
    distribués (poste qui reçoit → signale à l'expéditeur que le message
    est bien arrivé chez lui, même chat fermé). Renvoie le nombre de lignes
    mises à jour. No-op (0) si la colonne delivered_at n'existe pas encore
    (migration 44 non appliquée)."""
    me = _me()
    c = _supabase()
    if c is None or not me:
        return 0
    if not _delivered_supported(c):
        return 0
    from datetime import datetime, timezone
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        res = (c.raw.table("messages")
               .update({"delivered_at": now_iso})
               .eq("recipient_id", me).is_("delivered_at", "null").execute())
        return len(res.data or [])
    except Exception as exc:
        logger.debug("mark_all_delivered: %s", exc)
        return 0


def count_unread() -> int:
    """Nombre de messages reçus non lus. 0 si pas loggé / erreur."""
    me = _me()
    c = _supabase()
    if c is None or not me:
        return 0
    try:
        res = (c.raw.table("messages")
               .select("id", count="exact")
               .eq("recipient_id", me).is_("read_at", "null").execute())
        return int(getattr(res, "count", 0) or 0)
    except Exception as exc:
        logger.debug("count_unread: %s", exc)
        return 0


def last_message_preview() -> Optional[dict]:
    """Renvoie le dernier message échangé avec l'autre user, sous la forme
    {body, created_at, is_from_me}. Si le message est une pièce jointe
    seule (pas de texte), on remplace par un libellé "📎 …" lisible.
    None si pas dispo."""
    me = _me()
    other = _opposite(me)
    c = _supabase()
    if c is None or not me or not other:
        return None
    try:
        sent = (c.raw.table("messages")
                .select("body, created_at, sender_id, attachment_url, attachment_type")
                .eq("sender_id", me).eq("recipient_id", other)
                .order("created_at", desc=True).limit(1).execute())
        recv = (c.raw.table("messages")
                .select("body, created_at, sender_id, attachment_url, attachment_type")
                .eq("sender_id", other).eq("recipient_id", me)
                .order("created_at", desc=True).limit(1).execute())
        candidates = (sent.data or []) + (recv.data or [])
        if not candidates:
            return None
        candidates.sort(key=lambda m: m.get("created_at") or "", reverse=True)
        m = candidates[0]
        body = (m.get("body") or "").strip()
        if not body and m.get("attachment_url"):
            mime = (m.get("attachment_type") or "").lower()
            body = "📎 Photo" if mime.startswith("image/") else "📎 Fichier"
        return {
            "body": body,
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
    me = _me()
    c = _supabase()
    if c is None or not me:
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
    me = _me()
    other = _opposite(me)
    c = _supabase()
    if c is None or not me or not other:
        return False
    try:
        from datetime import datetime, timezone
        now_iso = datetime.now(timezone.utc).isoformat()
        res = (c.raw.table("typing_status")
               .select("until_ts")
               .eq("user_id", other)
               .gt("until_ts", now_iso).limit(1).execute())
        return bool(res.data)
    except Exception as exc:
        logger.debug("peer_is_typing: %s", exc)
        return False
