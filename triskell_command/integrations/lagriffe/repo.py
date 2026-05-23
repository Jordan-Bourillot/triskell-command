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


def count_by_status() -> dict[str, int]:
    """Renvoie le nombre d'intakes pour chaque status connu.
    Lagriffe a un status supplémentaire 'final_ready_review' (validation
    humaine du site final avant envoi du mail).
    """
    keys = [
        "pending_validation", "approved", "processing", "sent",
        "paid", "finalizing", "final_ready_review", "live",
        "rejected", "failed", "final_failed",
    ]
    out = {k: 0 for k in keys}
    sb = _sb()
    if sb is None:
        return out
    try:
        for k in keys:
            r = (sb.table("lagriffe_intakes").select("id", count="exact", head=True)
                 .eq("status", k).execute())
            out[k] = int(getattr(r, "count", 0) or 0)
    except Exception as exc:
        logger.warning("lagriffe.count_by_status: %s", exc)
    return out


def intake_timeline(intake_id: str) -> list[dict]:
    """Reconstruit la chronologie d'un intake à partir des colonnes
    horodatées de lagriffe_intakes. Ordre : du plus ancien au plus récent.
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


def trigger_finalize(intake_id: str) -> tuple[bool, str]:
    """Déclenche manuellement la fabrication finale pour un intake 'paid'
    (utilisé quand le toggle 'paid' est en mode MANUEL).
    """
    import requests
    url = "https://lagriffe-studio.fr/.netlify/functions/finalize-site-build"
    try:
        r = requests.post(url, json={"intake_id": intake_id}, timeout=30)
        if r.ok:
            return True, "Fabrication finale lancée."
        return False, f"HTTP {r.status_code}: {r.text[:200]}"
    except Exception as exc:
        return False, str(exc)


# ---------------------------------------------------------------------------
# Pipeline settings (toggles AUTO/MANUEL par produit × étape)
# ---------------------------------------------------------------------------
def pipeline_settings_read(product: str) -> dict:
    """Lit les modes auto/manuel pour un produit depuis Supabase
    (triskell_pipeline_settings). Retourne {ok, product, settings: {stage: mode}}.
    """
    defaults = {"approved": "auto", "paid": "auto", "final_ready_review": "manual"}
    sb = _sb()
    if sb is None:
        return {"ok": True, "product": product, "settings": defaults, "fallback": True}
    try:
        rows = (sb.table("triskell_pipeline_settings")
                  .select("stage, mode")
                  .eq("product", product)
                  .execute().data or [])
        settings = dict(defaults)
        for r in rows:
            stage = r.get("stage")
            mode = r.get("mode")
            if stage in defaults and mode in ("auto", "manual"):
                settings[stage] = mode
        return {"ok": True, "product": product, "settings": settings}
    except Exception as exc:
        logger.warning("pipeline_settings_read: %s", exc)
        return {"ok": False, "error": str(exc), "settings": defaults}


def pipeline_settings_write(product: str, stage: str, mode: str, updated_by: str = "") -> dict:
    """Upsert (product, stage) → mode dans triskell_pipeline_settings."""
    sb = _sb()
    if sb is None:
        return {"ok": False, "error": "Supabase non configuré"}
    try:
        sb.table("triskell_pipeline_settings").upsert({
            "product": product,
            "stage": stage,
            "mode": mode,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "updated_by": (updated_by or "")[:200],
        }, on_conflict="product,stage").execute()
        return {"ok": True, "product": product, "stage": stage, "mode": mode}
    except Exception as exc:
        logger.warning("pipeline_settings_write: %s", exc)
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Modèles mails éditables (table triskell_email_templates)
# ---------------------------------------------------------------------------
# Liste les expéditeurs reconnus + leur libellé Triskell Command. Si on ajoute
# un nouveau produit/expéditeur, c'est ici qu'on le déclare.
MAIL_TEMPLATE_PRODUCTS = {
    "lagriffe": "Lagriffe Studio",
    "rankus":   "RankUs Studio",
    "wow":      "Studio WoW",
    "shared":   "Triskell (transversal)",
}


def mail_templates_list() -> dict:
    """Retourne tous les templates groupés par product (pour l'écran Triskell
    Command). Chaque template renvoie aussi sa liste de placeholders, ainsi
    que sa catégorie ('transactionnel' ou 'prospection') et son label libre."""
    sb = _sb()
    if sb is None:
        return {"ok": False, "error": "Supabase non configuré", "products": {}}
    try:
        rows = (sb.table("triskell_email_templates")
                  .select("product, key, from_address, from_name, subject, "
                          "description, placeholders, enabled, category, label, "
                          "audience, updated_at, updated_by")
                  .order("product")
                  .order("key")
                  .execute().data or [])
        # Group by product
        products: dict[str, dict] = {}
        for p, label in MAIL_TEMPLATE_PRODUCTS.items():
            products[p] = {"label": label, "templates": []}
        for r in rows:
            p = r.get("product") or "shared"
            if p not in products:
                products[p] = {"label": p, "templates": []}
            # Garantit que les anciennes lignes (avant migration 28) remontent
            # bien avec category='transactionnel' côté front même si la colonne
            # n'a pas encore été appliquée en base.
            if not r.get("category"):
                r["category"] = "transactionnel"
            products[p]["templates"].append(r)
        return {"ok": True, "products": products}
    except Exception as exc:
        logger.warning("mail_templates_list: %s", exc)
        return {"ok": False, "error": str(exc), "products": {}}


def mail_templates_get(product: str, key: str) -> dict:
    """Retourne le template complet (avec body_html / body_text)."""
    sb = _sb()
    if sb is None:
        return {"ok": False, "error": "Supabase non configuré"}
    try:
        rows = (sb.table("triskell_email_templates")
                  .select("*")
                  .eq("product", product)
                  .eq("key", key)
                  .limit(1)
                  .execute().data or [])
        if not rows:
            return {"ok": False, "error": "introuvable"}
        return {"ok": True, "template": rows[0]}
    except Exception as exc:
        logger.warning("mail_templates_get: %s", exc)
        return {"ok": False, "error": str(exc)}


def mail_templates_save(product: str, key: str, fields: dict, updated_by: str = "") -> dict:
    """Upsert d'un template. Les champs autorisés sont filtrés ici pour
    éviter qu'un client malveillant n'écrive n'importe quoi en base."""
    sb = _sb()
    if sb is None:
        return {"ok": False, "error": "Supabase non configuré"}
    if not product or not key:
        return {"ok": False, "error": "product/key manquants"}

    ALLOWED = ("from_address", "from_name", "subject",
               "body_html", "body_text", "description",
               "placeholders", "enabled", "category", "label",
               "audience")
    payload = {"product": product, "key": key}
    for k in ALLOWED:
        if k in fields:
            payload[k] = fields[k]
    # Limites raisonnables
    if "subject" in payload and isinstance(payload["subject"], str):
        payload["subject"] = payload["subject"][:300]
    if "from_name" in payload and isinstance(payload["from_name"], str):
        payload["from_name"] = payload["from_name"][:120]
    if "from_address" in payload and isinstance(payload["from_address"], str):
        payload["from_address"] = payload["from_address"][:200]
    if "description" in payload and isinstance(payload["description"], str):
        payload["description"] = payload["description"][:1000]
    if "body_html" in payload and isinstance(payload["body_html"], str):
        payload["body_html"] = payload["body_html"][:200_000]
    if "body_text" in payload and isinstance(payload["body_text"], str):
        payload["body_text"] = payload["body_text"][:200_000]
    if "enabled" in payload:
        payload["enabled"] = bool(payload["enabled"])
    # Catégorie : on n'accepte que 'transactionnel' ou 'prospection'.
    # Tout autre valeur (vide, inconnue) retombe sur 'transactionnel' pour
    # ne pas casser l'affichage à l'écran.
    if "category" in payload:
        cat = str(payload["category"] or "").strip().lower()
        payload["category"] = cat if cat in ("transactionnel", "prospection") else "transactionnel"
    if "label" in payload and isinstance(payload["label"], str):
        payload["label"] = payload["label"][:200]
    # Catégorie de prospect ciblée par le modèle (créateurs/influenceurs vs
    # pros/entreprises). Valeurs autorisées : 'creator', 'pro', ou None
    # (None = non précisé, dans ce cas le modèle est traité comme 'creator'
    # par convention historique — les 5 templates Pixel Pros d'origine).
    if "audience" in payload:
        aud = str(payload["audience"] or "").strip().lower()
        payload["audience"] = aud if aud in ("creator", "pro") else None

    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    payload["updated_by"] = (updated_by or "")[:200]

    try:
        sb.table("triskell_email_templates").upsert(
            payload, on_conflict="product,key").execute()
        return {"ok": True, "product": product, "key": key}
    except Exception as exc:
        logger.warning("mail_templates_save: %s", exc)
        return {"ok": False, "error": str(exc)}


def mail_templates_delete(product: str, key: str) -> dict:
    """Supprime un template (la function Netlify retombe alors sur son
    fallback hardcodé)."""
    sb = _sb()
    if sb is None:
        return {"ok": False, "error": "Supabase non configuré"}
    try:
        sb.table("triskell_email_templates").delete().eq("product", product).eq("key", key).execute()
        return {"ok": True}
    except Exception as exc:
        logger.warning("mail_templates_delete: %s", exc)
        return {"ok": False, "error": str(exc)}
