"""Lagriffe Studio — éditeur de templates de mail.

Source de vérité dans la table Supabase `lagriffe_mail_templates`. Les
Netlify functions lisent cette table avant chaque envoi (avec fallback
hardcodé si Supabase est en panne).

4 templates en jeu :
  - brief_received     → étape `pending_validation` : confirmation reçu
  - preview_ready      → étape `sent`              : maquette disponible
  - payment_confirmed  → étape `paid`              : paiement validé
  - site_delivered     → étape `live`              : site livré

Variables disponibles dans les templates (remplacées par chaque function) :
  - {first_name}     : prénom du client
  - {customize_url}  : lien vers la personnalisation (preview_ready)
  - {site_url}       : URL du site final (site_delivered)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Métadonnées humaines des 4 templates (pour l'UI de Triskell Command)
# ---------------------------------------------------------------------------
TEMPLATE_META = {
    "brief_received": {
        "label": "Confirmation de brief reçu",
        "trigger": "Quand le client soumet sa demande de site",
        "stage_key": "pending_validation",
        "stage_label": "Brief reçu",
    },
    "preview_ready": {
        "label": "Maquette prête à personnaliser",
        "trigger": "Quand Claude Code a fini de générer la preview",
        "stage_key": "sent",
        "stage_label": "Preview envoyée",
    },
    "payment_confirmed": {
        "label": "Confirmation de paiement",
        "trigger": "Quand Stripe a confirmé le paiement",
        "stage_key": "paid",
        "stage_label": "Payé",
    },
    "site_delivered": {
        "label": "Site final livré",
        "trigger": "Quand le site final est mis en ligne",
        "stage_key": "live",
        "stage_label": "En ligne",
    },
}

# Variables disponibles par template (info UI uniquement)
TEMPLATE_VARIABLES = {
    "brief_received":    ["{first_name}"],
    "preview_ready":     ["{first_name}", "{customize_url}"],
    "payment_confirmed": ["{first_name}"],
    "site_delivered":    ["{first_name}", "{site_url}"],
}

# Fallback hardcodé (utilisé par les Netlify functions et l'UI si Supabase indispo)
DEFAULT_TEMPLATES = {
    "brief_received": {
        "subject":   "📥 On a bien reçu votre demande, {first_name}",
        "preheader": "On commence la fabrication de votre maquette dans les heures qui viennent.",
        "eyebrow":   "Configuration reçue",
        "title":     "Bien reçu,<br>{first_name}.",
        "cta_label": "",
        "cta_url":   "",
    },
    "preview_ready": {
        "subject":   "Votre maquette Lagriffe est prête, {first_name}",
        "preheader": "Votre maquette est en ligne. Cliquez pour la personnaliser et finaliser votre site.",
        "eyebrow":   "Aperçu de votre site",
        "title":     "Votre maquette est prête,<br>{first_name}.",
        "cta_label": "Personnaliser mon site →",
        "cta_url":   "{customize_url}",
    },
    "payment_confirmed": {
        "subject":   "Bienvenue chez Lagriffe, {first_name}",
        "preheader": "Paiement reçu. Votre site est en cours de fabrication finale.",
        "eyebrow":   "Paiement validé",
        "title":     "Bienvenue chez Lagriffe,<br>{first_name}.",
        "cta_label": "",
        "cta_url":   "",
    },
    "site_delivered": {
        "subject":   "Votre site Lagriffe est en ligne, {first_name}",
        "preheader": "Toutes vos pages, vos contenus, vos fonctionnalités. C'est en ligne.",
        "eyebrow":   "Mise en ligne",
        "title":     "Votre site est en ligne,<br>{first_name}.",
        "cta_label": "Voir mon site →",
        "cta_url":   "{site_url}",
    },
}


def _sb():
    """Renvoie le client Supabase brut (avec fallback service_role en CI)."""
    try:
        from ..phare import repo as phare_repo
        return phare_repo._sb()
    except Exception as exc:
        logger.debug("lagriffe.mail_templates._sb: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Lecture
# ---------------------------------------------------------------------------
def list_templates() -> list[dict]:
    """Renvoie les 4 templates, fusionnés avec les overrides Supabase et
    enrichis des métadonnées (label, trigger, variables disponibles).
    """
    sb = _sb()
    overrides = {}
    if sb is not None:
        try:
            rows = sb.table("lagriffe_mail_templates").select("*").execute().data or []
            for r in rows:
                overrides[r["template_key"]] = r
        except Exception as exc:
            logger.debug("list_templates fetch: %s", exc)

    out = []
    for key, meta in TEMPLATE_META.items():
        base = dict(DEFAULT_TEMPLATES[key])
        override = overrides.get(key) or {}
        for field in ("subject", "preheader", "eyebrow", "title", "cta_label", "cta_url"):
            if override.get(field) is not None and override.get(field) != "":
                base[field] = override[field]
        out.append({
            "key": key,
            "label": meta["label"],
            "trigger": meta["trigger"],
            "stage_key": meta["stage_key"],
            "stage_label": meta["stage_label"],
            "variables": TEMPLATE_VARIABLES.get(key, []),
            "updated_at": override.get("updated_at"),
            "updated_by": override.get("updated_by") or "",
            **base,
        })
    return out


def get_template(key: str) -> Optional[dict]:
    """Renvoie un template par clé, fusionné avec l'override Supabase.

    Renvoie None si la clé n'est pas connue. Utilisé par les Netlify
    functions pour récupérer le template au moment de l'envoi.
    """
    if key not in TEMPLATE_META:
        return None
    base = dict(DEFAULT_TEMPLATES[key])
    sb = _sb()
    if sb is not None:
        try:
            rows = (sb.table("lagriffe_mail_templates").select("*")
                    .eq("template_key", key).limit(1).execute().data) or []
            if rows:
                override = rows[0]
                for field in ("subject", "preheader", "eyebrow", "title", "cta_label", "cta_url"):
                    if override.get(field):
                        base[field] = override[field]
        except Exception as exc:
            logger.debug("get_template fetch: %s", exc)
    return {"key": key, **base}


# ---------------------------------------------------------------------------
# Écriture
# ---------------------------------------------------------------------------
def save_template(key: str, fields: dict, *, updated_by: str = "") -> Optional[dict]:
    """Crée ou met à jour le template `key`. Retourne la ligne enregistrée."""
    if key not in TEMPLATE_META:
        return None
    sb = _sb()
    if sb is None:
        return None
    row = {
        "template_key": key,
        "subject":   (fields.get("subject") or "").strip(),
        "preheader": (fields.get("preheader") or "").strip(),
        "eyebrow":   (fields.get("eyebrow") or "").strip(),
        "title":     (fields.get("title") or "").strip(),
        "cta_label": (fields.get("cta_label") or "").strip(),
        "cta_url":   (fields.get("cta_url") or "").strip(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "updated_by": updated_by or "",
    }
    # Validation minimale
    if not row["subject"] or not row["title"]:
        return None
    try:
        res = sb.table("lagriffe_mail_templates").upsert(row, on_conflict="template_key").execute()
        return (res.data or [{}])[0]
    except Exception as exc:
        logger.warning("save_template upsert: %s", exc)
        return None
