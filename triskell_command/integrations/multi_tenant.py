"""Helper multi-tenant : injecter workspace_id sur les inserts/upserts.

Contexte
--------
Depuis la migration Supabase 20, toutes les tables metier ont une colonne
``workspace_id`` NOT NULL plus une policy RLS qui exige
``workspace_id = public.current_workspace_id()`` sur insert/update.

Avant cette migration, le code inserait des lignes sans workspace_id et
ca passait. Maintenant ca echoue silencieusement (try/except debug) et
les compteurs du cockpit restent a zero.

Plutot que de dupliquer 3 lignes ``ws = client._current_workspace_id();
if ws: row["workspace_id"] = ws`` partout, on centralise ici.

Usage
-----
    from .multi_tenant import with_workspace
    row = {...}
    sb.table("email_history").insert(with_workspace(client, row)).execute()

Sur les upserts batch (liste de dicts) :
    rows = [...]
    sb.table("convoy_drafts").upsert(with_workspace(client, rows)).execute()
"""

from __future__ import annotations

import logging
from typing import Any, Union

logger = logging.getLogger(__name__)

Row = dict[str, Any]


def _get_ws(client) -> str | None:
    """Recupere l'uuid du workspace courant, ou None en cas d'echec.

    Robuste : si client est None, mal forme, ou si l'RPC echoue, retourne
    None sans lever — le caller decidera si l'insert peut tenter sa
    chance sans (en pratique il ne pourra pas, mais on n'aggrave rien).
    """
    if client is None:
        return None
    try:
        getter = getattr(client, "_current_workspace_id", None)
        if not callable(getter):
            return None
        return getter()
    except Exception as exc:
        logger.debug("workspace_id introuvable: %s", exc)
        return None


def with_workspace(client, row_or_rows: Union[Row, list[Row]]) -> Union[Row, list[Row]]:
    """Retourne le(s) dict(s) enrichi(s) de ``workspace_id``.

    - dict simple -> dict avec workspace_id ajoute (si dispo)
    - liste de dicts -> liste avec workspace_id sur chaque entree

    Ne modifie pas l'objet original : retourne une copie. Si le workspace
    est introuvable, retourne le(s) dict(s) inchange(s) — l'insert echouera
    cote DB mais on log_warning chez le caller pour visibilite.
    """
    ws = _get_ws(client)
    if not ws:
        # On retourne tel quel ; l'insert echouera mais explicitement
        return row_or_rows

    if isinstance(row_or_rows, list):
        return [{**r, "workspace_id": ws} for r in row_or_rows]
    if isinstance(row_or_rows, dict):
        return {**row_or_rows, "workspace_id": ws}
    return row_or_rows
