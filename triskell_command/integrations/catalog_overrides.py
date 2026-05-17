"""Overrides utilisateur sur le catalogue principal (apps.json + sites hardcodes).

Le catalogue Triskell (apps.json + sites Lagriffe/RankUs/WoW hardcodes dans
catalogue.js) est en lecture seule cote code. Pour permettre a Jordan
d'activer/desactiver chaque produit sans toucher au code, on stocke a part
une liste d'overrides en Supabase.

Persistance :
- Supabase `shared_settings.catalog_overrides` (partage Jordan/Thomas).
- Format : {"disabled_ids": ["bobeez", "alphapitch", ...]}

Effet :
- Vue Catalogue : les tuiles desactivees sont grisees + toggle off.
- Picker mails (Catalogue.pickProduct) : les desactivees sont filtrees.
- Prospection IA / Convoi (catalog_repo.get_catalog) : les entrees dont le
  nom matche un produit desactive sont filtrees aussi (best-effort par nom,
  car convoy_catalog n'a pas d'IDs).
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

SHARED_KEY = "catalog_overrides"


def _client():
    """Renvoie le client Supabase si auth, sinon None."""
    try:
        from triskell_core.db import get_client, SupabaseNotConfigured
        try:
            c = get_client()
        except SupabaseNotConfigured:
            return None
        return c if c.is_authenticated else None
    except ImportError:
        return None
    except Exception:
        return None


def _read() -> dict:
    c = _client()
    if c is None:
        return {}
    try:
        raw = c.get_shared_setting(SHARED_KEY, {}) or {}
        return raw if isinstance(raw, dict) else {}
    except Exception as exc:
        logger.debug("catalog_overrides _read: %s", exc)
        return {}


def _write(data: dict) -> bool:
    c = _client()
    if c is None:
        return False
    try:
        c.set_shared_setting(SHARED_KEY, data)
        return True
    except Exception as exc:
        logger.warning("catalog_overrides _write: %s", exc)
        return False


def get_disabled_ids() -> set[str]:
    """Renvoie l'ensemble des IDs de produits desactives."""
    data = _read()
    raw = data.get("disabled_ids") or []
    return {str(i) for i in raw if i}


def set_disabled(product_id: str, disabled: bool) -> bool:
    """Active ou desactive un produit. Renvoie True si la persistance a reussi."""
    pid = (product_id or "").strip()
    if not pid:
        return False
    data = _read()
    current = set(str(i) for i in (data.get("disabled_ids") or []) if i)
    if disabled:
        current.add(pid)
    else:
        current.discard(pid)
    data["disabled_ids"] = sorted(current)
    return _write(data)
