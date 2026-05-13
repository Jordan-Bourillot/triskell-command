"""DAO Supabase pour la facturation Triskell.

DESTINATION FINALE :
    Triskell\\triskell-command\\triskell_command\\integrations\\billing\\repo.py

Wrapper minimal sur le client Supabase partagé. Pattern aligné sur
`integrations/phare/repo.py`.

Aucune logique métier ici : c'est juste l'accès aux tables `invoices`,
`invoice_counters`, `invoice_archive`, `shared_settings` et au bucket
Storage `invoices-archive`.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Connexion Supabase
# ---------------------------------------------------------------------------
# La facturation est une opération **backend** : elle doit fonctionner
# sans utilisateur authentifié (orchestrateur post-paiement, scripts,
# vue Command). On préfère donc un client service-role qui bypass RLS.
#
# Ordre de résolution :
#   1. Variables d'environnement SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY
#   2. ~/.triskell-command/settings.json → supabase.service_role_key
#   3. Fallback sur triskell_core.db.get_client() (mode user authentifié)

_SERVICE_CLIENT = None
_SERVICE_CLIENT_TRIED = False


def _load_service_config() -> Optional[dict]:
    """Renvoie {url, service_role_key} ou None."""
    import json
    import os
    from pathlib import Path

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if url and key:
        return {"url": url, "service_role_key": key}

    settings_path = Path.home() / ".triskell-command" / "settings.json"
    if settings_path.exists():
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
            sb = data.get("supabase") or {}
            url = sb.get("url") or ""
            key = sb.get("service_role_key") or ""
            if url and key:
                return {"url": url, "service_role_key": key}
        except Exception as exc:
            logger.debug("billing._load_service_config: %s", exc)
    return None


def _service_sb():
    """Crée (une fois) un client Supabase brut avec service-role."""
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
        logger.warning("supabase-py introuvable — pip install supabase")
        return None

    try:
        _SERVICE_CLIENT = create_client(cfg["url"], cfg["service_role_key"])
    except Exception as exc:
        logger.warning("billing._service_sb: %s", exc)
        return None
    return _SERVICE_CLIENT


def _client():
    """Client user-authentifié, en fallback si pas de service-role."""
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
    return c


def _sb():
    """Instance supabase-py brute. Préfère service-role (backend),
    sinon retombe sur le client user-authentifié."""
    sb = _service_sb()
    if sb is not None:
        return sb
    c = _client()
    if c is None:
        return None
    return getattr(c, "client", None) or getattr(c, "_client", None)


# ---------------------------------------------------------------------------
# invoices
# ---------------------------------------------------------------------------
def insert_invoice(row: dict) -> Optional[dict]:
    sb = _sb()
    if sb is None:
        return None
    try:
        rows = sb.table("invoices").insert(row).execute().data
        return rows[0] if rows else None
    except Exception as exc:
        logger.warning("billing.insert_invoice: %s", exc)
        return None


def update_invoice(invoice_id: str, patch: dict) -> bool:
    sb = _sb()
    if sb is None:
        return False
    try:
        sb.table("invoices").update(patch).eq("id", invoice_id).execute()
        return True
    except Exception as exc:
        logger.warning("billing.update_invoice: %s", exc)
        return False


def get_invoice(invoice_id: str) -> Optional[dict]:
    sb = _sb()
    if sb is None:
        return None
    try:
        rows = (sb.table("invoices").select("*")
                .eq("id", invoice_id).limit(1).execute().data)
        return rows[0] if rows else None
    except Exception as exc:
        logger.warning("billing.get_invoice: %s", exc)
        return None


def get_invoice_by_number(invoice_number: str) -> Optional[dict]:
    sb = _sb()
    if sb is None:
        return None
    try:
        rows = (sb.table("invoices").select("*")
                .eq("invoice_number", invoice_number).limit(1).execute().data)
        return rows[0] if rows else None
    except Exception as exc:
        logger.warning("billing.get_invoice_by_number: %s", exc)
        return None


def list_invoices(
    *,
    client_id: Optional[str] = None,
    client_email: Optional[str] = None,
    year: Optional[int] = None,
    limit: int = 100,
) -> list[dict]:
    sb = _sb()
    if sb is None:
        return []
    try:
        q = sb.table("invoices").select("*").order("issued_at", desc=True).limit(limit)
        if client_id:
            q = q.eq("client_id", client_id)
        if year:
            q = q.eq("year", year)
        if client_email:
            # filtre sur la valeur figée du snapshot
            q = q.filter("client_snapshot->>email", "eq", client_email)
        return q.execute().data or []
    except Exception as exc:
        logger.warning("billing.list_invoices: %s", exc)
        return []


def list_invoices_for_fec(year: int) -> list[dict]:
    """Renvoie toutes les factures d'une année, triées par numéro de
    séquence, série confondue (FA puis AV mélangées par date). Pour
    le FEC.
    """
    sb = _sb()
    if sb is None:
        return []
    try:
        return (sb.table("invoices").select("*")
                .eq("year", year)
                .order("issued_at", desc=False)
                .order("sequence", desc=False)
                .execute().data) or []
    except Exception as exc:
        logger.warning("billing.list_invoices_for_fec: %s", exc)
        return []


# ---------------------------------------------------------------------------
# invoice_archive
# ---------------------------------------------------------------------------
def archive_invoice(invoice_row: dict, pdf_sha256: str) -> Optional[dict]:
    sb = _sb()
    if sb is None:
        return None
    try:
        rows = sb.table("invoice_archive").insert({
            "invoice_id": invoice_row["id"],
            "invoice_number": invoice_row["invoice_number"],
            "snapshot": invoice_row,
            "pdf_sha256": pdf_sha256,
        }).execute().data
        return rows[0] if rows else None
    except Exception as exc:
        logger.warning("billing.archive_invoice: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Storage : bucket invoices-archive
# ---------------------------------------------------------------------------
def upload_invoice_pdf(invoice_number: str, year: int, pdf_bytes: bytes) -> str:
    """Upload le PDF dans le bucket Supabase Storage et renvoie le path.

    Format chemin : "{year}/{invoice_number}.pdf"
    """
    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase non connecté — impossible d'uploader le PDF.")
    bucket = (get_config().get("storage_bucket") or "invoices-archive")
    path = f"{year}/{invoice_number}.pdf"
    try:
        sb.storage.from_(bucket).upload(
            path=path,
            file=pdf_bytes,
            file_options={"content-type": "application/pdf",
                          "upsert": "false"},  # interdit d'écraser un PDF émis
        )
    except Exception as exc:
        # Si déjà présent et qu'on n'en veut surtout pas un autre : lever.
        # Sinon on retombe sur l'erreur Supabase native.
        raise RuntimeError(f"Échec upload PDF {path} : {exc}") from exc
    return path


def get_invoice_pdf_signed_url(path: str, *, ttl_seconds: int = 3600) -> str:
    """Renvoie une URL signée temporaire pour télécharger le PDF."""
    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase non connecté.")
    bucket = (get_config().get("storage_bucket") or "invoices-archive")
    resp = sb.storage.from_(bucket).create_signed_url(path, ttl_seconds)
    return (resp.get("signedURL") or resp.get("signed_url")
            or resp.get("signedUrl") or "")


def download_invoice_pdf(path: str) -> bytes:
    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase non connecté.")
    bucket = (get_config().get("storage_bucket") or "invoices-archive")
    return sb.storage.from_(bucket).download(path)


# ---------------------------------------------------------------------------
# shared_settings.billing_config
# ---------------------------------------------------------------------------
def get_config() -> dict:
    """Renvoie billing_config (issuer info + numérotation + défauts)."""
    sb = _sb()
    if sb is None:
        return {}
    try:
        rows = (sb.table("shared_settings").select("value")
                .eq("key", "billing_config").limit(1).execute().data)
        if not rows:
            return {}
        return rows[0].get("value") or {}
    except Exception as exc:
        logger.warning("billing.get_config: %s", exc)
        return {}


def update_config(patch: dict) -> bool:
    sb = _sb()
    if sb is None:
        return False
    cur = get_config()
    # merge profond pour issuer
    if "issuer" in patch and isinstance(patch["issuer"], dict):
        merged_issuer = (cur.get("issuer") or {}).copy()
        merged_issuer.update(patch["issuer"])
        patch = {**patch, "issuer": merged_issuer}
    cur.update(patch)
    try:
        sb.table("shared_settings").upsert({
            "key": "billing_config",
            "value": cur,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="key").execute()
        return True
    except Exception as exc:
        logger.warning("billing.update_config: %s", exc)
        return False
