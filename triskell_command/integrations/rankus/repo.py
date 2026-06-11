"""DAO Supabase pour les intakes RankUs Studio.

Pattern aligné sur `integrations/billing/repo.py` : connexion Supabase
service-role en priorité (lecture/écriture sans avoir besoin d'un user
authentifié), fallback sur le client user-authed via triskell_core.db.

Tables :
  - rankus_intakes : voir rankus-studio/db/01_init.sql

Workflow :
  pending_validation → approved (validation manuelle) → processing → sent | failed
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_SERVICE_CLIENT = None
_SERVICE_CLIENT_TRIED = False


# ---------------------------------------------------------------------------
# Connexion Supabase
# ---------------------------------------------------------------------------
def _load_service_config() -> Optional[dict]:
    """Renvoie {url, service_role_key} ou None."""
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
            logger.debug("rankus._load_service_config: %s", exc)
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
        logger.warning("rankus._service_sb: %s", exc)
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
    # c.raw force l'init du SDK ; le getattr "_client" restait None en
    # mode service_role tant que rien d'autre n'avait touché le client.
    try:
        return c.raw
    except Exception:
        return None


def _sb():
    return _service_sb() or _user_sb()


# ---------------------------------------------------------------------------
# Intakes
# ---------------------------------------------------------------------------
def list_intakes(*, status: Optional[str] = None, limit: int = 50) -> list[dict]:
    sb = _sb()
    if sb is None:
        return []
    try:
        q = sb.table("rankus_intakes").select("*").order("created_at", desc=True).limit(limit)
        if status:
            q = q.eq("status", status)
        return q.execute().data or []
    except Exception as exc:
        logger.warning("rankus.list_intakes: %s", exc)
        return []


def get_intake(intake_id: str) -> Optional[dict]:
    sb = _sb()
    if sb is None:
        return None
    try:
        rows = (sb.table("rankus_intakes").select("*")
                .eq("id", intake_id).limit(1).execute().data)
        return rows[0] if rows else None
    except Exception as exc:
        logger.warning("rankus.get_intake: %s", exc)
        return None


def mark_contact_handled(intake_id: str, *, handled: bool = True) -> tuple[bool, str]:
    """Marque un message de contact / une demande de rappel (status
    'contact' ou 'recall', venus du site public) comme « traité » — ou
    l'inverse avec handled=False. Posé dans payload.handled_at, même
    convention que Pixel Pros : pas de colonne dédiée, partagé entre
    appareils."""
    sb = _sb()
    if sb is None:
        return False, "Supabase non configuré."
    intake = get_intake(intake_id)
    if intake is None:
        return False, "Message introuvable."
    if (intake.get("status") or "") not in ("contact", "recall"):
        return False, "Cette fiche n'est pas un message de contact."
    payload = intake.get("payload") or {}
    if not isinstance(payload, dict):
        payload = {}
    if handled:
        payload["handled_at"] = datetime.now(timezone.utc).isoformat()
    else:
        payload.pop("handled_at", None)
    try:
        sb.table("rankus_intakes").update({"payload": payload}) \
            .eq("id", intake_id).execute()
        return True, ("Marqué traité." if handled else "Remis à traiter.")
    except Exception as exc:
        logger.warning("rankus.mark_contact_handled: %s", exc)
        return False, str(exc)


def update_intake_status(intake_id: str, new_status: str, *, error_message: str = "") -> bool:
    """Bascule un intake vers un nouveau status (approved | rejected | etc.)."""
    sb = _sb()
    if sb is None:
        return False
    patch: dict[str, Any] = {
        "status": new_status,
        "last_attempt_at": datetime.now(timezone.utc).isoformat(),
    }
    if error_message:
        patch["error_message"] = error_message
    try:
        sb.table("rankus_intakes").update(patch).eq("id", intake_id).execute()
        return True
    except Exception as exc:
        logger.warning("rankus.update_intake_status: %s", exc)
        return False


def approve_intake(intake_id: str) -> bool:
    """Marque l'intake comme approved : le cron Netlify le ramassera et
    déclenchera la génération Claude Code dans les 5 minutes.
    """
    return update_intake_status(intake_id, "approved")


def reject_intake(intake_id: str, reason: str = "") -> bool:
    """Refuse l'intake. Aucune génération ne sera déclenchée."""
    return update_intake_status(intake_id, "rejected",
                                 error_message=reason or "Refusé manuellement")


def dispatch_now(intake_id: str) -> tuple[bool, str]:
    """Déclenche immédiatement le pipeline preview pour un intake approved
    (sans attendre le cron 5 min). Appelle directement la Netlify Function
    dispatch-site-build.

    Renvoie (success, message).
    """
    import requests
    url = "https://rankus-studio.fr/.netlify/functions/dispatch-site-build"
    try:
        r = requests.post(url, json={"intake_id": intake_id}, timeout=30)
        if r.ok:
            return True, "Pipeline preview déclenché."
        return False, f"HTTP {r.status_code}: {r.text[:200]}"
    except Exception as exc:
        return False, str(exc)


def save_client_feedback(
    intake_id: str, *, feedback: str, assets_url: str = ""
) -> bool:
    """Enregistre les retours du client (texte) et l'URL des visuels qu'il
    a transmis (Dropbox, Drive, GoFile, etc.). Données utilisées par le
    pipeline finalisation pour intégrer les retours et les photos.
    """
    sb = _sb()
    if sb is None:
        return False
    patch: dict[str, Any] = {
        "client_feedback": (feedback or "").strip() or None,
        "client_assets_url": (assets_url or "").strip() or None,
    }
    try:
        sb.table("rankus_intakes").update(patch).eq("id", intake_id).execute()
        return True
    except Exception as exc:
        logger.warning("rankus.save_client_feedback: %s", exc)
        return False


def count_by_status() -> dict[str, int]:
    """Renvoie le nombre d'intakes pour chaque status connu.
    Utilisé par la vue Plomberie pour allumer les étages du pipeline.
    """
    keys = [
        "pending_validation", "approved", "processing", "sent",
        "paid", "finalizing", "live", "rejected", "failed", "final_failed",
    ]
    out = {k: 0 for k in keys}
    sb = _sb()
    if sb is None:
        return out
    try:
        for k in keys:
            r = (sb.table("rankus_intakes").select("id", count="exact", head=True)
                 .eq("status", k).execute())
            out[k] = int(getattr(r, "count", 0) or 0)
    except Exception as exc:
        logger.warning("rankus.count_by_status: %s", exc)
    return out


def intake_timeline(intake_id: str) -> list[dict]:
    """Reconstruit la chronologie d'un intake à partir des colonnes
    horodatées de rankus_intakes. Ordre : du plus ancien au plus récent.
    """
    intake = get_intake(intake_id)
    if intake is None:
        return []
    events: list[dict] = []
    def _push(kind: str, ts: Optional[str], label: str):
        if ts:
            events.append({"kind": kind, "ts": ts, "label": label})
    _push("submitted", intake.get("created_at"), "Brief soumis (pending_validation)")
    _push("attempt",   intake.get("last_attempt_at"), "Dernière tentative pipeline")
    _push("generated", intake.get("mockup_generated_at"),
          f"Preview générée → {intake.get('mockup_url') or '(URL absente)'}")
    _push("sent",      intake.get("mockup_sent_at"), "Mail preview envoyé au client")
    if intake.get("status") in ("rejected", "failed", "final_failed"):
        _push("error", intake.get("last_attempt_at"),
              intake.get("error_message") or "Erreur (sans message)")
    events.sort(key=lambda e: e["ts"] or "")
    events.append({
        "kind": "current",
        "ts": intake.get("last_attempt_at") or intake.get("created_at"),
        "label": f"Status courant : {intake.get('status')}",
    })
    return events


def launch_finalization(intake_id: str) -> tuple[bool, str]:
    """Déclenche le workflow de finalisation pour un intake en status 'paid'.
    Code TOUTES les pages, intègre les retours + visuels du client, déploie.

    Renvoie (success, message).
    """
    import requests
    url = "https://rankus-studio.fr/.netlify/functions/finalize-site-build"
    try:
        r = requests.post(url, json={"intake_id": intake_id}, timeout=30)
        if r.ok:
            return True, "Pipeline finalisation déclenché."
        return False, f"HTTP {r.status_code}: {r.text[:200]}"
    except Exception as exc:
        return False, str(exc)
