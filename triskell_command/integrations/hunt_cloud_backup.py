"""Copie de secours des chasses vers la base partagée (best-effort).

Le problème : les chasses (Chasseur, Chasseur Créateur, Prospecteur Google)
vivent dans des fichiers locaux du serveur. Si le disque/volume meurt, tout
est perdu — et Thomas ne voit pas les chasses lancées par Jordan.

La solution douce (sans tout migrer d'un coup) : à chaque fois qu'une chasse
atteint un état FINAL (done / error), on en pousse une copie dans la table
`hunts_backup` de Supabase. La source de vérité reste le fichier local
(zéro changement de comportement) ; la base ne sert que de filet de
sécurité et de visibilité partagée.

Best-effort intégral : si la table n'existe pas encore (migration 45 pas
appliquée) ou si la base est injoignable, on ne casse RIEN — la chasse se
termine exactement comme avant.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

FINAL_STATUSES = ("done", "error")


def _client():
    try:
        from triskell_core.db import get_client, SupabaseNotConfigured
        try:
            c = get_client()
        except SupabaseNotConfigured:
            return None
        return c if c.is_authenticated else None
    except Exception:
        return None


def mirror_hunt(tool: str, data: dict) -> bool:
    """Pousse une copie de la chasse en base. True si écrite."""
    if not isinstance(data, dict):
        return False
    status = (data.get("status") or "").strip()
    hunt_id = (data.get("id") or "").strip()
    if not hunt_id or status not in FINAL_STATUSES:
        return False
    c = _client()
    if c is None:
        return False
    row = {
        "tool": tool,
        "hunt_id": hunt_id,
        "label": (data.get("label") or "")[:200],
        "status": status,
        "filters": data.get("filters") or {},
        "stats": data.get("stats") or {},
        "payload": data,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    try:
        ws = c._current_workspace_id()  # noqa: SLF001
        if ws:
            row["workspace_id"] = ws
    except Exception:
        pass
    try:
        (c.raw.table("hunts_backup")
          .upsert(row, on_conflict="tool,hunt_id").execute())
        return True
    except Exception as exc:
        # Table absente (migration 45 pas passée) ou base injoignable :
        # on ne perturbe jamais la fin de chasse pour une copie de secours.
        logger.debug("hunts_backup KO (%s) — copie cloud sautée", exc)
        return False
