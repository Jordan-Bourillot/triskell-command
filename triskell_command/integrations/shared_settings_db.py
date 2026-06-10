"""Écriture robuste d'une clé de shared_settings (PK composite).

Depuis la migration 20 (multi-tenant), la clé primaire de shared_settings
est (workspace_id, key). L'ancien idiome
    sb.table("shared_settings").upsert({...}, on_conflict="key")
échoue alors en Postgres 42P10 (« no unique constraint matching ON
CONFLICT ») — et comme tous les écrivains avalaient l'erreur en simple
warning, les configs ne s'écrivaient PLUS DU TOUT côté serveur/CI.
Dégât principal constaté le 10/06/2026 : le scheduler_log du Phare était
figé, donc les missions globales (veille algo, A/B, bulletins…) n'avaient
plus de dédup persistante et repartaient à chaque tick horaire.

Idiome unique, à utiliser partout où on écrit shared_settings avec un
client supabase-py BRUT (les wrappers triskell-core ont déjà leur propre
gestion du workspace) :
  1. UPDATE filtré sur key — pas besoin de connaître le workspace, la
     ligne existe déjà dans la quasi-totalité des cas ;
  2. si aucune ligne touchée : INSERT avec le workspace courant
     (RPC current_workspace_id, sinon premier workspace créé).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _resolve_workspace_id(sb) -> str | None:
    """Workspace de la session courante, ou 1er workspace (mode service)."""
    try:
        res = sb.rpc("current_workspace_id").execute()
        if isinstance(res.data, str) and res.data:
            return res.data
    except Exception as exc:
        logger.debug("shared_settings_db: rpc current_workspace_id: %s", exc)
    try:
        rows = (sb.table("workspaces").select("id, created_at")
                .order("created_at").limit(1).execute().data) or []
        if rows and rows[0].get("id"):
            return rows[0]["id"]
    except Exception as exc:
        logger.debug("shared_settings_db: fallback workspaces: %s", exc)
    return None


def upsert_setting(sb, key: str, value) -> bool:
    """Écrit shared_settings[key] = value. Renvoie False sans lever."""
    if sb is None or not key:
        return False
    now_iso = datetime.now(timezone.utc).isoformat()
    # 1) UPDATE simple — fonctionne quel que soit le mode (user/service)
    try:
        r = (sb.table("shared_settings")
             .update({"value": value, "updated_at": now_iso})
             .eq("key", key).execute())
        if r.data:
            return True
    except Exception as exc:
        logger.warning("shared_settings_db.update(%s): %s", key, exc)
    # 2) Ligne absente (base neuve) : INSERT avec workspace
    try:
        row = {"key": key, "value": value, "updated_at": now_iso}
        ws = _resolve_workspace_id(sb)
        if ws:
            row["workspace_id"] = ws
        sb.table("shared_settings").insert(row).execute()
        return True
    except Exception as exc:
        logger.warning("shared_settings_db.insert(%s): %s", key, exc)
        return False
