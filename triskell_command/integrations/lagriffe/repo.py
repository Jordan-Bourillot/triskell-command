"""DAO Supabase pour les intakes Lagriffe Studio.

Pattern aligné sur `integrations/billing/repo.py` : connexion Supabase
service-role en priorité (lecture/écriture sans avoir besoin d'un user
authentifié), fallback sur le client user-authed via triskell_core.db.

Tables :
  - lagriffe_intakes : voir lagriffe-studio/db/01_init.sql

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
            logger.debug("lagriffe._load_service_config: %s", exc)
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
        logger.warning("lagriffe._service_sb: %s", exc)
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
# Intakes
# ---------------------------------------------------------------------------
def list_intakes(*, status: Optional[str] = None, limit: int = 50) -> list[dict]:
    sb = _sb()
    if sb is None:
        return []
    try:
        q = sb.table("lagriffe_intakes").select("*").order("created_at", desc=True).limit(limit)
        if status:
            q = q.eq("status", status)
        return q.execute().data or []
    except Exception as exc:
        logger.warning("lagriffe.list_intakes: %s", exc)
        return []


def get_intake(intake_id: str) -> Optional[dict]:
    sb = _sb()
    if sb is None:
        return None
    try:
        rows = (sb.table("lagriffe_intakes").select("*")
                .eq("id", intake_id).limit(1).execute().data)
        return rows[0] if rows else None
    except Exception as exc:
        logger.warning("lagriffe.get_intake: %s", exc)
        return None


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
        sb.table("lagriffe_intakes").update(patch).eq("id", intake_id).execute()
        return True
    except Exception as exc:
        logger.warning("lagriffe.update_intake_status: %s", exc)
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
    url = "https://lagriffe-studio.fr/.netlify/functions/dispatch-site-build"
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
        sb.table("lagriffe_intakes").update(patch).eq("id", intake_id).execute()
        return True
    except Exception as exc:
        logger.warning("lagriffe.save_client_feedback: %s", exc)
        return False


def mark_feedback_received(intake_id: str, *, feedback_text: str = "") -> tuple[bool, str]:
    """Marque qu'on a reçu le retour mail du client. Si paiement déjà
    encaissé, déclenche immédiatement la fabrication finale. Sinon,
    attend Stripe.

    Renvoie (success, message).
    """
    import requests
    url = "https://lagriffe-studio.fr/.netlify/functions/mark-feedback-received"
    try:
        r = requests.post(url, json={
            "intake_id": intake_id,
            "feedback_text": feedback_text or "OK reçu manuellement via Triskell Command",
        }, timeout=30)
        if not r.ok:
            return False, f"HTTP {r.status_code}: {r.text[:200]}"
        data = r.json()
        if data.get("will_finalize"):
            return True, "Feedback enregistré. Paiement déjà reçu → fabrication finale lancée."
        if data.get("waiting_for") == "payment":
            return True, "Feedback enregistré. En attente du paiement Stripe."
        if data.get("already_marked"):
            return True, "Feedback déjà enregistré précédemment."
        return True, "Feedback enregistré."
    except Exception as exc:
        return False, str(exc)


def launch_finalization(intake_id: str) -> tuple[bool, str]:
    """Déclenche le workflow de finalisation pour un intake en status 'paid'.
    Code TOUTES les pages, intègre les retours + visuels du client, déploie.

    À la fin du workflow, l'intake passe en status 'final_ready_review'
    (PAS 'live') — le mail final ne sera envoyé au client qu'après
    validation humaine via approve_final_and_send().

    Renvoie (success, message).
    """
    import requests
    url = "https://lagriffe-studio.fr/.netlify/functions/finalize-site-build"
    try:
        r = requests.post(url, json={"intake_id": intake_id}, timeout=30)
        if r.ok:
            return True, "Pipeline finalisation déclenché."
        return False, f"HTTP {r.status_code}: {r.text[:200]}"
    except Exception as exc:
        return False, str(exc)


def approve_final_and_send(intake_id: str) -> tuple[bool, str]:
    """Validation humaine du site final avant envoi au client.

    Appelle la Netlify Function approve-and-send-final qui :
      1. Vérifie status == 'final_ready_review'
      2. Envoie le mail final au client (URL définitive + politique)
      3. Bascule le status en 'live'

    Renvoie (success, message).
    """
    import requests
    url = "https://lagriffe-studio.fr/.netlify/functions/approve-and-send-final"
    try:
        r = requests.post(url, json={"intake_id": intake_id}, timeout=30)
        if r.ok:
            return True, "Mail final envoyé au client. Site officiellement live."
        return False, f"HTTP {r.status_code}: {r.text[:200]}"
    except Exception as exc:
        return False, str(exc)
