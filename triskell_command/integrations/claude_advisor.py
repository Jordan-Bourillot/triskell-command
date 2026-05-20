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


def _safe_pick(d: Any, keys: list[str]) -> dict:
    """Ne garde que les clés listées (et ignore les valeurs nulles/vides)."""
    if not isinstance(d, dict):
        return {}
    out = {}
    for k in keys:
        v = d.get(k)
        if v not in (None, "", [], {}):
            out[k] = v
    return out


def gather_voice_context(app_state) -> dict[str, Any]:
    """Snapshot ÉLARGI pour le mode conversation vocale.

    Contrairement à gather_context (qui se concentre sur le cockpit
    prospection), cette version balaye tous les modules de l'app
    (catalogue, clients, projets, Pixel Pros, Lagriffe, Obélisk, Phare,
    Convoi, Forge, factures, funnel) afin que le mode vocal puisse
    répondre à n'importe quelle question sur l'état de Triskell Command.

    Chaque bloc est wrappé dans try/except pour qu'un module en panne
    (Supabase déconnecté, table manquante…) ne casse pas la collecte.
    """
    ctx = gather_context(app_state)

    # Catalogue produits
    try:
        from . import catalog_central
        full = catalog_central.get_full() or {}
        prods = full.get("products") or []
        bundles = full.get("bundles") or []
        ctx["catalog"] = {
            "products_total": len(prods),
            "products_active": sum(
                1 for p in prods if p.get("active") is not False
            ),
            "bundles_total": len(bundles),
            "products": [
                _safe_pick(p, ["id", "name", "category", "price",
                                 "price_monthly", "active", "tagline"])
                for p in prods[:40]
            ],
            "bundles": [
                _safe_pick(b, ["id", "name", "price", "items", "active"])
                for b in bundles[:20]
            ],
        }
    except Exception as exc:
        logger.debug("voice ctx catalog: %s", exc)

    # Clients (master)
    try:
        from . import clients_master_repo
        clients = clients_master_repo.list_clients(limit=200) or []
        by_status: dict[str, int] = {}
        for c in clients:
            s = (c.get("status") or "unknown")
            by_status[s] = by_status.get(s, 0) + 1
        ctx["clients_master"] = {
            "total": len(clients),
            "by_status": by_status,
            "recent": [
                _safe_pick(c, ["display_name", "company", "email",
                                 "status", "tags", "created_at",
                                 "last_contacted_at"])
                for c in clients[:20]
            ],
        }
    except Exception as exc:
        logger.debug("voice ctx clients_master: %s", exc)

    # Projets clients (détail par statut)
    try:
        from . import clients_repo
        grouped = clients_repo.list_grouped() or {}
        ctx["client_projects_detail"] = {
            status: [
                _safe_pick(p, ["id", "display_name", "client_name",
                                 "product_type", "amount", "price",
                                 "status", "updated_at", "nps_sent_at",
                                 "site_url"])
                for p in (items or [])[:10]
            ]
            for status, items in grouped.items()
        }
    except Exception as exc:
        logger.debug("voice ctx client_projects: %s", exc)

    # Pixel Pros (intakes + affiliés)
    try:
        from .pixelpros import repo as pp_repo
        pp = {
            "intakes_by_status": pp_repo.count_by_status() or {},
            "recent_intakes": [
                _safe_pick(i, ["id", "company", "email", "status",
                                 "site_url", "domain", "created_at",
                                 "paid_at"])
                for i in (pp_repo.list_intakes(limit=15) or [])
            ],
        }
        try:
            from .pixelpros import affiliates as pp_aff
            pp["affiliates_by_status"] = pp_aff.count_by_status() or {}
        except Exception:
            pass
        ctx["pixel_pros"] = pp
    except Exception as exc:
        logger.debug("voice ctx pixel_pros: %s", exc)

    # Lagriffe
    try:
        from .lagriffe import repo as lg_repo
        ctx["lagriffe"] = {
            "intakes_by_status": lg_repo.count_by_status() or {},
            "recent_intakes": [
                _safe_pick(i, ["id", "company", "name", "email",
                                 "status", "created_at"])
                for i in (lg_repo.list_intakes(limit=15) or [])
            ],
        }
    except Exception as exc:
        logger.debug("voice ctx lagriffe: %s", exc)

    # Obélisk (créateurs)
    try:
        from .obelisk import repo as ob_repo
        ob_stats = ob_repo.stats() or {}
        creators = ob_repo.list_creators(limit=15) or []
        if isinstance(creators, dict):
            creators = creators.get("creators") or []
        ctx["obelisk"] = {
            "stats": ob_stats,
            "recent_creators": [
                _safe_pick(c, ["name", "handle", "platform", "followers",
                                 "status", "niche", "contacted_at"])
                for c in creators
            ],
        }
    except Exception as exc:
        logger.debug("voice ctx obelisk: %s", exc)

    # Phare (SEO)
    try:
        from .phare import repo as ph_repo
        sites = ph_repo.list_sites(active_only=True) or []
        ctx["phare"] = {
            "active_sites": len(sites),
            "sites": [
                _safe_pick(s, ["id", "name", "domain", "client_id",
                                 "cadence"])
                for s in sites[:30]
            ],
            "pending_actions": ph_repo.pending_actions_count() or 0,
        }
    except Exception as exc:
        logger.debug("voice ctx phare: %s", exc)

    # Convoi (campagnes de prospection)
    try:
        from . import convoy_runner
        camps = convoy_runner.list_campaigns() or []
        ctx["convoy"] = {
            "campaigns_total": len(camps),
            "campaigns": [
                {
                    "id": getattr(c, "id", ""),
                    "name": getattr(c, "name", ""),
                    "status": getattr(c, "status", ""),
                    "drafts_total": len(getattr(c, "drafts", []) or []),
                    "drafts_pending": sum(
                        1 for d in (getattr(c, "drafts", []) or [])
                        if (getattr(d, "status", "") or "") == "pending"
                    ),
                    "drafts_sent": sum(
                        1 for d in (getattr(c, "drafts", []) or [])
                        if (getattr(d, "status", "") or "") == "sent"
                    ),
                }
                for c in camps[:20]
            ],
        }
    except Exception as exc:
        logger.debug("voice ctx convoy: %s", exc)

    # Forge (briefs entrants Lagriffe / WoW)
    try:
        from .forge import repo as fg_repo
        ctx["forge"] = {
            "new_briefs": fg_repo.count_briefs("new") or 0,
            "queued_projects": fg_repo.count_projects("queued") or 0,
            "recent_briefs": [
                _safe_pick(b, ["id", "subject", "from_addr", "status",
                                 "created_at"])
                for b in (fg_repo.list_briefs(limit=10) or [])
            ],
            "recent_projects": [
                _safe_pick(p, ["id", "name", "status", "created_at"])
                for p in (fg_repo.list_projects(limit=10) or [])
            ],
        }
    except Exception as exc:
        logger.debug("voice ctx forge: %s", exc)

    # Facturation (Carnet — devis & factures)
    try:
        from .billing import repo as bl_repo
        invoices = bl_repo.list_invoices(limit=20) or []
        ctx["billing"] = {
            "recent_invoices": [
                _safe_pick(inv, ["invoice_number", "client_name",
                                   "total_ht", "total_ttc", "status",
                                   "issued_at", "paid_at", "due_at"])
                for inv in invoices
            ],
        }
    except Exception as exc:
        logger.debug("voice ctx billing: %s", exc)

    # Tunnel de conversion (30 derniers jours)
    try:
        from . import funnel_metrics
        ctx["funnel_30d"] = funnel_metrics.compute_funnel("30d", "all") or {}
    except Exception as exc:
        logger.debug("voice ctx funnel: %s", exc)

    return ctx


# ---------------------------------------------------------------------------
# Appel Claude
# ---------------------------------------------------------------------------
CONVO_SYSTEM_PROMPT = """Tu es Claude, l'assistant vocal de Jordan, cofondateur de Studio Triskell (agence web bretonne, fondée avec Thomas).

Tu es en MODE CONVERSATION VOCALE. Jordan te parle à l'oral via un micro, tu lui réponds à l'oral.

═══════════════════════════════════════════════════════════════
TU AS ACCÈS À TOUTE L'APP TRISKELL COMMAND EN DIRECT
═══════════════════════════════════════════════════════════════
À chaque tour, tu reçois en bas de ce prompt un bloc JSON intitulé « ÉTAT DE TOUTE L'APP TRISKELL COMMAND EN DIRECT ». C'est un snapshot LIVE pris à l'instant où Jordan parle. Il contient :
- Cockpit prospection : envois du jour, réponses entrantes par catégorie, alertes, totaux, file de travail, workers, état config (SMTP/IMAP/IA).
- Catalogue : produits actifs avec prix, bundles.
- Clients (clients_master) : liste, statuts, derniers contacts.
- Projets clients (client_projects_detail) : groupés par statut (proposed, in_progress, delivered…), montants, NPS, URL du site.
- Pixel Pros : intakes par statut, derniers sites publiés ou en cours, programme d'affiliation.
- Lagriffe : intakes (sites 49 €/mois) par statut.
- Obélisk : créateurs prospectés, stats.
- Phare (SEO) : sites suivis, actions en attente.
- Convoi : campagnes de prospection, brouillons (pending / sent par campagne).
- Forge : briefs entrants et projets en queue.
- Carnet (billing) : factures récentes avec montants et statut de paiement.
- Tunnel de conversion sur 30 jours (funnel_30d).

⇒ Quand Jordan te demande quelque chose qui touche son business ou son app — « comment se porte le business », « combien de réponses positives j'ai aujourd'hui », « où en est le client X », « combien de sites Pixel Pros ce mois-ci », « est-ce que ma config tient la route », « donne-moi un point de situation »… — tu DOIS aller piocher dans ce JSON et répondre avec les VRAIS chiffres et les VRAIS noms. Tu n'as PAS le droit de dire « je n'ai pas accès » : tu as le JSON, sers-t'en.

Si tu cherches une donnée précise et qu'elle n'est PAS dans le JSON (ex : un détail super pointu de facture, un mail particulier), alors là tu dis honnêtement que tu ne l'as pas et tu suggères à Jordan la vue de l'app où la trouver.

═══════════════════════════════════════════════════════════════
QUAND NE PAS DÉROULER LE JSON DE TOI-MÊME
═══════════════════════════════════════════════════════════════
Si Jordan te parle d'autre chose que son app (météo, recette, question tech, définition, papote, etc.), réponds normalement sans ramener la conversation à son business. Et ne lui balance pas un bilan business à chaque salutation : tu utilises le JSON quand il pose une question dessus, pas spontanément.

EXCEPTION : si tu vois dans le JSON un truc VRAIMENT critique en cours (envoi cassé en boucle, beaucoup de réponses positives non traitées depuis longtemps, config IA absente, deadline brûlante…) ET que c'est pertinent par rapport au sujet en cours, tu peux le mentionner brièvement en fin de réponse.

═══════════════════════════════════════════════════════════════
TON ET FORMAT
═══════════════════════════════════════════════════════════════
- Réponds comme un ami au café. Phrases courtes, naturelles, détendues. Comme à l'oral.
- Pas de titre, pas de liste à puces, pas d'émoji, pas de markdown. Du texte brut qu'on prononce bien à voix haute.
- En général : 1 à 3 phrases. Plus seulement si Jordan demande clairement plus de détail (« donne-moi le détail », « explique-moi », « fais le tour »).
- Tutoiement obligatoire.
- N'ajoute jamais d'annotation type « Réponse : » ou « Claude : » — donne directement la réponse, point.
- Si tu ne comprends pas, pose UNE question de clarification, courte.

═══════════════════════════════════════════════════════════════
CONTEXTE STATIQUE
═══════════════════════════════════════════════════════════════
Studio Triskell est la maison-mère. Jordan & Thomas opèrent : Pixel Pros (sites pros à 24,90 €/mois), Lagriffe Studio (sites sur mesure à 49 €/mois quand le client aime), WoW Studio (sites très haut de gamme), Rankus Studio (SEO autonome). Carnet est leur outil devis/factures pour micro-entrepreneurs. Triskell Command est l'app que tu es en train d'animer.

N'invente jamais un chiffre ou un fait. Tout ce que tu donnes comme chiffre doit venir du JSON ou de l'historique de la conversation.
"""


def chat_with_claude(app_state, *, question: str,
                     history: Optional[list] = None) -> dict[str, Any]:
    """Conversation libre avec Claude (mode vocal).

    Renvoie {ok, text, error}. Pas de format structuré — juste du texte brut
    qu'on peut lire à voix haute.
    """
    out: dict[str, Any] = {"ok": False, "text": "", "error": ""}

    ai = _resolve_ai(app_state)
    if not ai.get("api_key"):
        out["error"] = "ai_not_configured"
        return out

    history = history or []
    # Limite l'historique aux 10 derniers tours pour éviter d'exploser les tokens
    convo_parts: list[str] = []
    for turn in history[-10:]:
        role = (turn.get("role") or "user").lower()
        content = (turn.get("content") or "").strip()
        if not content:
            continue
        speaker = "Jordan" if role == "user" else "Claude"
        convo_parts.append(f"{speaker} : {content}")
    convo_parts.append(f"Jordan : {question.strip()}")
    convo_parts.append("Claude :")

    # Snapshot LIVE de toute l'app (cockpit + catalogue + clients +
    # projets + Pixel Pros + Lagriffe + Obélisk + Phare + Convoi + Forge
    # + factures + funnel), pour que le mode vocal puisse répondre à
    # n'importe quelle question sur Triskell Command. On le sérialise en
    # JSON et on l'injecte juste avant l'historique de la conversation.
    try:
        context = gather_voice_context(app_state)
        context_block = (
            "ÉTAT DE TOUTE L'APP TRISKELL COMMAND EN DIRECT "
            "(JSON, snapshot pris à l'instant) :\n"
            + json.dumps(context, ensure_ascii=False, indent=2, default=str)
        )
    except Exception as exc:
        logger.debug("convo gather_voice_context: %s", exc)
        context_block = "ÉTAT DE L'APP EN DIRECT : (indisponible)"

    full_prompt = (CONVO_SYSTEM_PROMPT + "\n\n---\n\n"
                   + context_block + "\n\n---\n\n"
                   + "\n\n".join(convo_parts))

    try:
        from triskell_core.ai.providers import send_to_provider, ProviderError
    except ImportError:
        out["error"] = "core_unavailable"
        return out

    try:
        api_keys = {ai["provider"]: ai["api_key"]}
        text = send_to_provider(
            ai["provider"],
            ai.get("model") or "",
            full_prompt,
            api_keys,
        )
        out["text"] = (text or "").strip()
        out["ok"] = bool(out["text"])
    except ProviderError as exc:
        out["error"] = f"ai_error: {exc}"
    except Exception as exc:
        out["error"] = f"ai_exception: {exc}"

    return out


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
