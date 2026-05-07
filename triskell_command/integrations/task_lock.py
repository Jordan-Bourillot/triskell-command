"""Verrou doux multi-utilisateur pour les workers Triskell Command.

Problème : Jordan et Thomas ont chacun leur Triskell Command qui tourne.
Sans verrou, les deux risquent d'envoyer la même relance / la même
réponse / la même livraison en même temps.

Solution : verrou applicatif optimiste basé sur `extra._lock` (champ
JSONB déjà présent dans `email_history`, `prospect_drafts`,
`client_projects`). Pas besoin de migration SQL.

Cycle d'un worker :
  1. SELECT toutes les tâches éligibles
  2. Pour chaque tâche :
     a. try_acquire_lock(table, id, ttl_seconds=300)
        → si False (déjà locked par quelqu'un d'autre, lock pas expiré)
          → SKIP, l'autre user s'en occupe
        → si True (lock posé sur cette ligne pour les 5 prochaines min)
          → continue le traitement
     b. À la fin (succès OU échec), release_lock(table, id)

Le lock se compose de :
  extra._lock = {
    by:    "<user_id>",       # qui détient
    until: "<iso datetime>",  # quand il expire (TTL)
    pid:   "<hostname:pid>",  # debug : qui tourne ce worker
  }

Si une machine crashe en plein traitement, le lock expire après TTL
(5 min par défaut), et un autre worker peut reprendre. Pas de deadlock.
"""

from __future__ import annotations

import json
import logging
import os
import socket
from datetime import datetime, timedelta
from typing import Any, Optional

logger = logging.getLogger(__name__)


LOCK_KEY = "_lock"
DEFAULT_TTL_SECONDS = 300   # 5 min — assez pour un envoi SMTP, pas trop


def _hostname_pid() -> str:
    try:
        return f"{socket.gethostname()}:{os.getpid()}"
    except Exception:
        return f"unknown:{os.getpid()}"


def _now() -> datetime:
    return datetime.now()


def _parse_iso(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def _read_extra(client_supabase, table: str, row_id: Any) -> Optional[dict]:
    """Renvoie l'extra courant de la ligne, ou None si introuvable."""
    try:
        r = (client_supabase.table(table).select("extra")
             .eq("id", row_id).limit(1).execute())
        rows = r.data or []
        if not rows:
            return None
        extra = rows[0].get("extra") or {}
        if isinstance(extra, str):
            try: extra = json.loads(extra)
            except Exception: extra = {}
        return extra if isinstance(extra, dict) else {}
    except Exception as exc:
        logger.debug("read_extra %s/%s: %s", table, row_id, exc)
        return None


def _write_extra(client_supabase, table: str, row_id: Any,
                  extra: dict) -> bool:
    try:
        (client_supabase.table(table).update({"extra": extra})
         .eq("id", row_id).execute())
        return True
    except Exception as exc:
        logger.debug("write_extra %s/%s: %s", table, row_id, exc)
        return False


def try_acquire_lock(client, table: str, row_id: Any,
                      *, user_id: str = "",
                      ttl_seconds: int = DEFAULT_TTL_SECONDS) -> bool:
    """Tente de poser un verrou sur cette ligne.

    Retourne True si on a pris le verrou (libre OU expiré OU déjà à nous),
    False si quelqu'un d'autre le détient et que ce n'est pas expiré.

    Note : ce n'est PAS atomique au niveau base (Supabase ne le permet pas
    via PostgREST). Mais comme la fenêtre est ~50 ms et que les workers
    tournent à 5 min d'intervalle minimum, le risque de collision est
    négligeable. En pire cas : un mail part 2 fois — Supabase aura une
    duplication de log dans email_history que tu peux déduper.
    """
    if not client or not row_id:
        return False
    sb = client.raw if hasattr(client, "raw") else client
    extra = _read_extra(sb, table, row_id)
    if extra is None:
        return False  # ligne introuvable

    me = user_id or (getattr(client, "user_id", None) or "")
    pid = _hostname_pid()
    now = _now()

    cur_lock = extra.get(LOCK_KEY) or {}
    cur_by = cur_lock.get("by") or ""
    cur_until = _parse_iso(cur_lock.get("until") or "")

    if cur_by and cur_until and cur_until > now and cur_by != me:
        # Verrou détenu par quelqu'un d'autre, encore valide
        return False

    # Sinon : libre, expiré, ou déjà à nous → on (re)pose
    extra[LOCK_KEY] = {
        "by":    me,
        "until": (now + timedelta(seconds=ttl_seconds)).isoformat(timespec="seconds"),
        "pid":   pid,
    }
    return _write_extra(sb, table, row_id, extra)


def release_lock(client, table: str, row_id: Any,
                  *, user_id: str = "") -> bool:
    """Libère le verrou si c'est nous qui le détenons.
    À appeler en `finally:` après le traitement."""
    if not client or not row_id:
        return False
    sb = client.raw if hasattr(client, "raw") else client
    extra = _read_extra(sb, table, row_id)
    if extra is None:
        return False

    me = user_id or (getattr(client, "user_id", None) or "")
    cur_lock = extra.get(LOCK_KEY) or {}
    if cur_lock and cur_lock.get("by") and cur_lock.get("by") != me:
        # Pas notre lock, on ne touche pas
        return False
    if LOCK_KEY in extra:
        del extra[LOCK_KEY]
        return _write_extra(sb, table, row_id, extra)
    return True


def is_locked_by_other(client, table: str, row_id: Any,
                        *, user_id: str = "") -> bool:
    """Lecture seule : vrai si quelqu'un d'autre détient le verrou
    (et qu'il n'est pas expiré). Utile pour filtrer une liste sans
    déclencher d'écritures."""
    if not client or not row_id:
        return False
    sb = client.raw if hasattr(client, "raw") else client
    extra = _read_extra(sb, table, row_id)
    if extra is None:
        return False
    me = user_id or (getattr(client, "user_id", None) or "")
    cur_lock = extra.get(LOCK_KEY) or {}
    cur_by = cur_lock.get("by") or ""
    cur_until = _parse_iso(cur_lock.get("until") or "")
    if not cur_by or not cur_until:
        return False
    return cur_until > _now() and cur_by != me


def _filter_unlocked(rows: list[dict], me: str) -> list[dict]:
    """Filtre une liste de rows pour garder ceux qui ne sont pas locked
    par quelqu'un d'autre (lecture en mémoire, pas de round-trip).
    Utile quand on a déjà SELECT * et qu'on veut éviter de re-fetch."""
    now = _now()
    out = []
    for r in rows:
        extra = r.get("extra") or {}
        if isinstance(extra, str):
            try: extra = json.loads(extra)
            except Exception: extra = {}
        cur = (extra.get(LOCK_KEY) or {})
        cur_by = cur.get("by") or ""
        cur_until = _parse_iso(cur.get("until") or "")
        if cur_by and cur_until and cur_until > now and cur_by != me:
            continue
        out.append(r)
    return out
