"""DAO Supabase pour la table `clients` master (fiche client unifiée).

Différent de `clients_repo.py` qui gère `client_projects` (kanban
livraison). Ce module-ci gère la table master `clients` créée par
la migration 09_clients_master.sql.

Pattern aligné sur `integrations/wow/repo.py` :
service-role en priorité (lecture/écriture sans user authentifié),
fallback sur le client user-authed via triskell_core.db.

Méthodes principales :
  - ensure_client(email, **defaults) → uuid du client (upsert idempotent)
  - get_client(client_id) → dict
  - get_client_by_email(email) → dict
  - list_clients(status?, search?, limit) → list[dict]
  - get_client_360(client_id) → dict avec compteurs agrégés
  - get_client_timeline(client_id) → list d'événements (intakes, factures, mails)
  - update_client(client_id, **patch) → bool
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_SERVICE_CLIENT = None
_SERVICE_CLIENT_TRIED = False


# ---------------------------------------------------------------------------
# Connexion Supabase
# ---------------------------------------------------------------------------
def _load_service_config() -> Optional[dict]:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_SERVICE_KEY")
    if url and key:
        return {"url": url, "service_role_key": key}
    settings_path = Path.home() / ".triskell-command" / "settings.json"
    if settings_path.exists():
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
            sb = data.get("supabase") or {}
            url = sb.get("url") or ""
            key = sb.get("service_role_key") or sb.get("service_key") or ""
            if url and key:
                return {"url": url, "service_role_key": key}
        except Exception as exc:
            logger.debug("clients_master._load_service_config: %s", exc)
    return None


def _service_sb():
    global _SERVICE_CLIENT, _SERVICE_CLIENT_TRIED
    if _SERVICE_CLIENT is not None:
        return _SERVICE_CLIENT
    if _SERVICE_CLIENT_TRIED:
        return None
    _SERVICE_CLIENT_TRIED = True
    cfg = _load_service_config()
    if cfg is None:
        return None
    try:
        from supabase import create_client
    except ImportError:
        return None
    try:
        _SERVICE_CLIENT = create_client(cfg["url"], cfg["service_role_key"])
    except Exception as exc:
        logger.warning("clients_master._service_sb: %s", exc)
        return None
    return _SERVICE_CLIENT


def _user_sb():
    try:
        from triskell_core.db import get_client, SupabaseNotConfigured
    except ImportError:
        return None
    try:
        c = get_client()
    except SupabaseNotConfigured:
        return None
    if not c.is_authenticated:
        return None
    return getattr(c, "client", None) or getattr(c, "_client", None)


def _sb():
    return _service_sb() or _user_sb()


# ---------------------------------------------------------------------------
# CORE — ensure_client : upsert idempotent
# ---------------------------------------------------------------------------
def ensure_client(
    email: str,
    *,
    first_name: str = "",
    last_name: str = "",
    phone: str = "",
    company_name: str = "",
    siret: str = "",
    source: str = "",
) -> Optional[str]:
    """Upsert idempotent d'un client par email. Renvoie l'UUID du client
    (créé ou existant). Met à jour les champs vides UNIQUEMENT — aucune
    valeur existante n'est jamais écrasée.

    Appelle la fonction Postgres `ensure_client` côté Supabase (atomic).

    Renvoie None si Supabase non joignable OU email invalide.
    """
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        return None

    sb = _sb()
    if sb is None:
        return None

    try:
        # Appelle la fonction Postgres via RPC
        res = sb.rpc(
            "ensure_client",
            {
                "p_email": email,
                "p_first_name": first_name or None,
                "p_last_name": last_name or None,
                "p_phone": phone or None,
                "p_company_name": company_name or None,
                "p_siret": siret or None,
                "p_source": source or None,
            },
        ).execute()
        # PostgREST renvoie l'UUID directement comme data
        if res.data:
            return str(res.data)
    except Exception as exc:
        logger.warning("ensure_client RPC failed: %s", exc)

    # Fallback : upsert direct si RPC non disponible (ex: si la fonction
    # Postgres n'est pas encore migrée, on essaie quand même côté Python)
    try:
        existing = (sb.table("clients").select("id")
                    .ilike("email", email).limit(1).execute().data)
        if existing:
            return str(existing[0]["id"])

        row = {
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "phone": phone,
            "company_name": company_name,
            "siret": siret,
            "is_pro": bool(company_name or siret),
            "sources": [source] if source else [],
            "first_contact_at": datetime.utcnow().isoformat() + "Z",
            "last_contact_at": datetime.utcnow().isoformat() + "Z",
        }
        ins = sb.table("clients").insert(row).execute()
        if ins.data:
            return str(ins.data[0]["id"])
    except Exception as exc:
        logger.warning("ensure_client fallback failed: %s", exc)

    return None


# ---------------------------------------------------------------------------
# Lectures
# ---------------------------------------------------------------------------
def get_client(client_id: str) -> Optional[dict]:
    sb = _sb()
    if sb is None:
        return None
    try:
        rows = (sb.table("clients").select("*")
                .eq("id", client_id).limit(1).execute().data)
        return rows[0] if rows else None
    except Exception as exc:
        logger.warning("get_client: %s", exc)
        return None


def get_client_by_email(email: str) -> Optional[dict]:
    email = (email or "").strip().lower()
    if not email:
        return None
    sb = _sb()
    if sb is None:
        return None
    try:
        rows = (sb.table("clients").select("*")
                .ilike("email", email).limit(1).execute().data)
        return rows[0] if rows else None
    except Exception as exc:
        logger.warning("get_client_by_email: %s", exc)
        return None


def list_clients(
    *,
    status: Optional[str] = None,
    search: str = "",
    limit: int = 200,
) -> list[dict]:
    """Liste des clients avec compteurs (depuis la vue clients_360).
    `search` filtre sur email ou full_name (case-insensitive)."""
    sb = _sb()
    if sb is None:
        return []
    try:
        q = sb.table("clients_360").select("*").order("last_contact_at", desc=True).limit(limit)
        if status:
            q = q.eq("status", status)
        rows = q.execute().data or []
        if search:
            s = search.strip().lower()
            rows = [
                r for r in rows
                if s in (r.get("email") or "").lower()
                or s in (r.get("full_name") or "").lower()
                or s in (r.get("company_name") or "").lower()
            ]
        return rows
    except Exception as exc:
        logger.warning("list_clients: %s", exc)
        return []


def get_client_360(client_id: str) -> Optional[dict]:
    """Renvoie la ligne de la vue clients_360 (avec compteurs agrégés)."""
    sb = _sb()
    if sb is None:
        return None
    try:
        rows = (sb.table("clients_360").select("*")
                .eq("id", client_id).limit(1).execute().data)
        return rows[0] if rows else None
    except Exception as exc:
        logger.warning("get_client_360: %s", exc)
        return None


def get_client_timeline(client_id: str, *, limit: int = 100) -> list[dict]:
    """Timeline chronologique (récente → ancienne) des événements d'un client :
    intakes Lagriffe/RankUs/WoW, factures, emails envoyés, projets.

    Renvoie une liste de dicts uniformes :
      { type, created_at, label, status, link?, raw }
    """
    sb = _sb()
    if sb is None:
        return []

    events: list[dict] = []

    def _safe_fetch(table: str, type_label: str, label_field: str = "status") -> None:
        try:
            rows = (sb.table(table).select("*")
                    .eq("client_id", client_id)
                    .order("created_at", desc=True).limit(50)
                    .execute().data) or []
            for r in rows:
                events.append({
                    "type": type_label,
                    "created_at": r.get("created_at"),
                    "label": r.get(label_field) or "",
                    "status": r.get("status") or "",
                    "raw": r,
                })
        except Exception as exc:
            logger.debug("timeline %s: %s", table, exc)

    _safe_fetch("lagriffe_intakes", "Demande Lagriffe")
    _safe_fetch("rankus_intakes", "Demande RankUs")
    _safe_fetch("wow_intakes", "Demande Studio WoW")
    _safe_fetch("invoices", "Facture", label_field="invoice_number")
    _safe_fetch("email_history", "Email envoyé", label_field="subject")
    _safe_fetch("client_projects", "Projet livraison", label_field="title")

    # Trie chronologique inversé (plus récent en haut)
    events.sort(key=lambda e: e.get("created_at") or "", reverse=True)
    return events[:limit]


# ---------------------------------------------------------------------------
# Modifications
# ---------------------------------------------------------------------------
def update_client(client_id: str, **patch: Any) -> bool:
    """Met à jour les champs fournis (whitelisting des colonnes autorisées)."""
    allowed = {
        "first_name", "last_name", "phone",
        "is_pro", "company_name", "siret", "vat_number",
        "address_line1", "address_line2", "address_zip", "address_city",
        "address_country", "tags", "status", "notes",
        "stripe_customer_id",
    }
    clean = {k: v for k, v in patch.items() if k in allowed}
    if not clean:
        return False

    sb = _sb()
    if sb is None:
        return False
    try:
        sb.table("clients").update(clean).eq("id", client_id).execute()
        return True
    except Exception as exc:
        logger.warning("update_client: %s", exc)
        return False


def add_tag(client_id: str, tag: str) -> bool:
    """Ajoute un tag à la liste (idempotent)."""
    client = get_client(client_id)
    if not client:
        return False
    tags = client.get("tags") or []
    if tag in tags:
        return True
    tags = list(tags) + [tag]
    return update_client(client_id, tags=tags)
