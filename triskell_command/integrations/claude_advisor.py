"""Claude Advisor — collecte le contexte courant de l'app et demande à
Claude la prochaine action à faire.

Deux modes :
- "interactive" : appelé via le bouton « Allô Claude » (Jordan demande).
  Renvoie un conseil + niveau d'urgence + vue suggérée.
- "proactive"   : appelé par le worker périodique. Si la situation justifie
  une interruption, retourne urgency=high + un message court à pousser
  en notification.

Système Claude :
- Rôle : assistant bizdev de Jordan B. (Triskell Studio).
- Style : direct, français parlant, pas de flatterie.
- Format : JSON strict.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """Tu es l'assistant bizdev intégré dans Triskell Command,
l'app interne de Jordan Bourillot (Triskell Studio, Bretagne).

Ton rôle : analyser l'état actuel de l'app et donner UNE seule prochaine
action concrète à faire MAINTENANT.

Règles de style :
- Français parlant, jamais d'anglais inutile, jamais de jargon technique.
- Direct, sans flatterie. Pas de "excellente question", pas de "permets-moi".
- Si la situation est calme : propose une amélioration produit, un chantier
  pour développer Triskell, ou un sujet de réflexion business.
- Si la situation est tendue : priorise (réponses positives non traitées,
  échecs d'envoi répétés, paramètres incomplets).
- Si la situation est moyenne : 1 conseil concret + 1 phrase de vision.
- Adapte le ton à l'urgence (calme et taquin si tout va bien, sec et pressé
  si l'incendie démarre).

Niveaux d'urgence :
- "low"    : tout va bien, c'est une suggestion d'évolution.
- "medium" : il y a quelque chose à faire dans la journée.
- "high"   : à traiter tout de suite.

Format de sortie : UN SEUL bloc JSON valide, rien avant ni après.

{
  "urgency": "low" | "medium" | "high",
  "headline": "phrase courte ≤80 caractères, sans ponctuation finale",
  "advice": "ton conseil en 1 à 3 paragraphes, ton parlant",
  "suggested_view": "morning" | "replies" | "drafts" | "clients" | "funnel" | "config" | null,
  "suggested_action_label": "texte court du bouton (≤30 chars)"
}
"""


def _client():
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


def _resolve_ai(app_state) -> dict:
    """Renvoie {provider, model, api_key} pour appeler Claude.
    Cherche dans l'ordre : env vars (ANTHROPIC_API_KEY), Supabase, local."""
    out = {"provider": "", "model": "", "api_key": ""}
    # Récupère les clés via shared_secrets qui gère env > Supabase > local
    try:
        from . import shared_secrets
        keys = shared_secrets.get_ai_keys(client=_client(), app_state=app_state)
    except Exception:
        keys = {}
    # Fallback : config locale brute (au cas où shared_secrets pète)
    if not keys:
        ai = app_state.get("ai", default={}) or {}
        keys = ai.get("api_keys") or {}

    ai = app_state.get("ai", default={}) or {}
    # On force Anthropic pour le conseiller (modèle plus apte à raisonner)
    anth = keys.get("anthropic") or ""
    if anth:
        out["provider"] = "anthropic"
        out["api_key"] = anth
        out["model"] = ai.get("selected_model") or "claude-sonnet-4-5"
        if not str(out["model"]).startswith("claude"):
            out["model"] = "claude-sonnet-4-5"
        return out
    # Fallback : provider configuré (peut être google/openai/etc.)
    sel = ai.get("selected_provider") or ""
    if sel and keys.get(sel):
        out["provider"] = sel
        out["api_key"] = keys[sel]
        out["model"] = ai.get("selected_model") or ""
    return out


# ---------------------------------------------------------------------------
# Collecte de contexte
# ---------------------------------------------------------------------------
def gather_context(app_state) -> dict[str, Any]:
    """Assemble un dict décrivant l'état courant de l'app pour Claude."""
    ctx: dict[str, Any] = {
        "moment": datetime.now().isoformat(timespec="seconds"),
        "user": {"display_name": "Jordan"},
        "supabase_connected": False,
        "today": {},
        "yesterday": {},
        "queue": {},
        "alerts": {},
        "totals": {},
        "client_projects_summary": {},
        "active_view": app_state.get("active_view", default=""),
    }

    # Identité user (depuis Supabase si connecté)
    client = _client()
    if client is not None:
        ctx["supabase_connected"] = True
        ctx["user"]["display_name"] = (
            client.user_display_name or "Jordan"
        )

    # Digest Matinale
    try:
        from . import morning_digest
        d = morning_digest.compute_digest()
        if d.get("ok"):
            ctx["today"] = {
                "date": d.get("today", ""),
                "sent": d["sent"]["today"],
                "replies": d["replies"]["today_total"],
                "replies_breakdown": d["replies"]["today_breakdown"] or {},
            }
            ctx["yesterday"] = {
                "date": d.get("yesterday", ""),
                "sent": d["sent"]["yesterday"],
                "replies": d["replies"]["yesterday_total"],
                "replies_breakdown": d["replies"]["yesterday_breakdown"] or {},
            }
            ctx["queue"] = d.get("queue", {})
            ctx["alerts"] = d.get("alerts", {})
            ctx["totals"] = d.get("totals", {})
    except Exception as exc:
        logger.debug("digest: %s", exc)

    # Projets clients par statut
    try:
        from . import clients_repo
        groups = clients_repo.list_grouped()
        ctx["client_projects_summary"] = {
            status: len(items) for status, items in groups.items()
        }
        # Un échantillon des cartes "delivered" sans NPS encore
        delivered = groups.get("delivered", []) or []
        ctx["delivered_without_followup"] = sum(
            1 for p in delivered if not p.get("nps_sent_at")
        )
    except Exception as exc:
        logger.debug("clients: %s", exc)

    # État configuration mini
    # IMPORTANT : on lit la config SMTP/IMAP depuis Supabase shared_settings
    # en priorité (config partagée Jordan/Thomas), pas le settings.json local.
    # Sur le serveur Docker, le fichier local est souvent vide alors que la
    # vraie config est en BDD. Sinon Claude croit que tout est cassé et
    # affole l'utilisateur ("Ton SMTP est mort").
    smtp_ok = False
    imap_ok = False
    try:
        from . import shared_secrets
        client = _client()
        cfg = shared_secrets.get_smtp_config(client=client, app_state=app_state) or {}
        smtp_ok = bool(cfg.get("smtp_host") and cfg.get("smtp_user") and cfg.get("smtp_password"))
        imap_ok = bool(cfg.get("imap_host") and cfg.get("imap_user") and cfg.get("imap_password"))
        # Si on a au moins un compte mail dans Supabase (multi-comptes), c'est bon
        if not smtp_ok:
            accounts = shared_secrets.get_all_mail_accounts(client=client, app_state=app_state) or []
            for acc in accounts:
                if acc.get("smtp_host") and acc.get("from_email"):
                    smtp_ok = True
                    break
    except Exception as exc:
        logger.debug("config_status from shared_secrets: %s", exc)
        # Fallback : ancien comportement (lecture locale)
        out = app_state.get("outreach", default={}) or {}
        smtp_ok = bool(out.get("smtp_host") and out.get("smtp_user")
                         and out.get("smtp_password"))
        imap_ok = bool(out.get("imap_host") and out.get("imap_user")
                         and out.get("imap_password"))
    ctx["config_status"] = {
        "smtp_ok": smtp_ok,
        "imap_ok": imap_ok,
        "ai_configured": bool(_resolve_ai(app_state).get("api_key")),
    }

    # État des tâches autonomes (pour signaler les workers en panne)
    try:
        from . import (replies_poller, reply_responder,
                        drip_runner, post_sale_runner)
        ctx["workers"] = {
            "imap_replies": replies_poller.get_status(),
            "auto_responder": reply_responder.get_status(),
            "drip": drip_runner.get_status(),
            "post_sale": post_sale_runner.get_status(),
        }
    except Exception as exc:
        logger.debug("workers status: %s", exc)

    return ctx


# ---------------------------------------------------------------------------
# Appel Claude
# ---------------------------------------------------------------------------
def ask_claude(app_state, *, mode: str = "interactive",
                user_question: Optional[str] = None) -> dict[str, Any]:
    """Appelle Claude avec le contexte courant. Renvoie le dict de conseil.

    `mode`  : "interactive" (Jordan a cliqué) ou "proactive" (worker).
    `user_question` : question libre si Jordan veut creuser un sujet.
    """
    out = {
        "ok": False,
        "urgency": "low",
        "headline": "",
        "advice": "",
        "suggested_view": None,
        "suggested_action_label": "",
        "error": "",
    }

    ai = _resolve_ai(app_state)
    if not ai.get("api_key"):
        out["error"] = "ai_not_configured"
        return out

    context = gather_context(app_state)

    user_msg_parts: list[str] = []
    if mode == "proactive":
        user_msg_parts.append(
            "Mode : VEILLE AUTOMATIQUE. Tu n'interviens que si c'est "
            "vraiment utile. Si tout est calme et que rien ne mérite une "
            "interruption, renvoie urgency='low' et un conseil court "
            "d'amélioration produit."
        )
    else:
        user_msg_parts.append(
            "Mode : Jordan a cliqué « Allô Claude ». Donne-lui sa "
            "prochaine action concrète."
        )

    if user_question:
        user_msg_parts.append(
            f"Question libre de Jordan :\n« {user_question} »"
        )

    user_msg_parts.append("État courant de l'app (JSON) :")
    user_msg_parts.append(json.dumps(context, ensure_ascii=False, indent=2,
                                      default=str))

    user_msg = "\n\n".join(user_msg_parts)

    try:
        from triskell_core.ai.providers import send_to_provider, ProviderError
    except ImportError:
        out["error"] = "core_unavailable"
        return out

    try:
        # send_to_provider attend (provider_id, model, prompt, api_keys-dict)
        prompt = SYSTEM_PROMPT + "\n\n---\n\n" + user_msg
        api_keys = {ai["provider"]: ai["api_key"]}
        text = send_to_provider(
            ai["provider"],
            ai.get("model") or "",
            prompt,
            api_keys,
        )
        text = (text or "").strip()
    except ProviderError as exc:
        out["error"] = f"ai_error: {exc}"
        return out
    except Exception as exc:
        out["error"] = f"ai_exception: {exc}"
        return out

    # Extraction du JSON
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        out["error"] = f"no_json_in_response: {text[:200]}"
        return out
    try:
        data = json.loads(m.group(0))
    except Exception as exc:
        out["error"] = f"invalid_json: {exc}"
        return out

    out["ok"] = True
    out["urgency"] = (data.get("urgency") or "low").lower()
    if out["urgency"] not in ("low", "medium", "high"):
        out["urgency"] = "low"
    out["headline"] = (data.get("headline") or "").strip()
    out["advice"] = (data.get("advice") or "").strip()
    sv = data.get("suggested_view")
    if sv in ("morning", "replies", "drafts", "clients", "funnel", "config"):
        out["suggested_view"] = sv
    out["suggested_action_label"] = (
        data.get("suggested_action_label") or "").strip()
    return out
