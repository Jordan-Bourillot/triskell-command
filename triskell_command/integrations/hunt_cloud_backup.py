"""Copie de secours des chasses vers la base partagée (best-effort).

Le problème : les chasses (Chasseur, Chasseur Créateur, Prospecteur Google)
vivent dans des fichiers locaux du serveur. Si le disque/volume meurt, tout
est perdu — et Thomas ne voit pas les chasses lancées par Jordan.

La solution douce (sans tout migrer d'un coup) : à CHAQUE sauvegarde de la
chasse, on en pousse une copie dans la table `hunts_backup` de Supabase
(légèrement espacée pour ne pas marteler la base ; toujours immédiate quand
la chasse atteint un état final done / error). La source de vérité reste le
fichier local ; la base sert de filet de sécurité ET de visibilité partagée.

⚠️ Depuis la séparation site/robots (03/07), cette copie est VITALE pour les
missions : la chasse tourne dans le conteneur du site (c'est lui qui a les
clés API et les écrans), mais le chef de gare (mission_runner) tourne dans le
conteneur robots — sans la copie cloud, il ne voit pas la chasse et la
mission meurt en « chasse introuvable » (vécu le 08/07 : 2 missions
Prospecteur Google tuées ainsi). D'où : copie EN CONTINU (pas juste à la
fin) + repli de lecture `load_hunt` quand le fichier local n'existe pas.

Best-effort intégral : si la table n'existe pas encore (migration 45 pas
appliquée) ou si la base est injoignable, on ne casse RIEN — la chasse se
déroule exactement comme avant.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

FINAL_STATUSES = ("done", "error")

# Espacement minimal entre deux copies d'une même chasse EN COURS (les états
# finaux, eux, partent toujours immédiatement). Évite un upsert Supabase à
# chaque prospect traité.
LIVE_MIRROR_MIN_SECONDS = 10.0
_LAST_LIVE_MIRROR: dict[str, float] = {}


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
    """Pousse une copie de la chasse en base. True si écrite.

    Toutes les chasses sont copiées, quel que soit leur état : une chasse EN
    COURS est copiée au plus toutes les LIVE_MIRROR_MIN_SECONDS (throttle),
    une chasse en état final part toujours immédiatement. C'est ce qui permet
    au chef de gare (conteneur robots) de suivre une chasse qui tourne dans
    le conteneur du site."""
    if not isinstance(data, dict):
        return False
    status = (data.get("status") or "").strip()
    hunt_id = (data.get("id") or "").strip()
    if not hunt_id:
        return False
    if status not in FINAL_STATUSES:
        now = time.monotonic()
        last = _LAST_LIVE_MIRROR.get(hunt_id, 0.0)
        if now - last < LIVE_MIRROR_MIN_SECONDS:
            return False
        _LAST_LIVE_MIRROR[hunt_id] = now
        # Purge naturelle du throttle (les vieilles entrées ne servent plus).
        if len(_LAST_LIVE_MIRROR) > 200:
            for k in sorted(_LAST_LIVE_MIRROR,
                            key=_LAST_LIVE_MIRROR.get)[:100]:
                _LAST_LIVE_MIRROR.pop(k, None)
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


def load_hunt(tool: str, hunt_id: str) -> dict | None:
    """Relit la copie cloud d'une chasse (payload complet), ou None.

    Repli de lecture pour les conteneurs qui n'ont PAS le fichier local de
    la chasse (ex. : le chef de gare côté robots suit une chasse lancée côté
    site). Best-effort : toute panne renvoie None, jamais d'exception."""
    tool = (tool or "").strip()
    hunt_id = (hunt_id or "").strip()
    if not tool or not hunt_id:
        return None
    c = _client()
    if c is None:
        return None
    try:
        rows = (c.raw.table("hunts_backup").select("payload")
                .eq("tool", tool).eq("hunt_id", hunt_id)
                .limit(1).execute().data) or []
        payload = rows[0].get("payload") if rows else None
        return payload if isinstance(payload, dict) else None
    except Exception as exc:
        logger.debug("hunts_backup load KO (%s)", exc)
        return None
