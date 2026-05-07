"""Outreach — démarchage backlinks automatisé.

Pipeline :
1. Lit les opportunités de backlinks depuis phare_backlinks (kind='opportunity')
2. Pour chacune, génère un email personnalisé via LLM (template + variables :
   nom du contact si trouvé, contexte du site cible, anchor proposé)
3. Stocke dans phare_outreach_messages (status='draft')
4. Si phare_config.outreach_auto_send = false (défaut) → bac à valider
   dans Triskell Command
5. Si auto_send = true → envoi via SMTP partagé (Triskell shared_settings)
6. Suivi via IMAP (le RepliesPoller existant peut être étendu, mais on fait
   simple : on poll les messages avec status='sent' toutes les 6h et on
   regarde dans la boîte si une réponse contient l'anchor proposé)
7. Relance auto à J+7 et J+14 si pas de réponse, jusqu'à 2 max
"""

from __future__ import annotations

import logging
import re
import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from email.utils import formataddr, make_msgid
from typing import Optional

import requests

from . import agents, repo

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Templates par type d'opportunité
# ---------------------------------------------------------------------------
DEFAULT_TEMPLATES = {
    "broken_link": {
        "subject": "Lien cassé sur votre page « {target_page_title} »",
        "body": (
            "Bonjour{contact_name_clause},\n\n"
            "En lisant votre article « {target_page_title} » sur {target_domain}, "
            "j'ai remarqué que le lien vers {broken_url} ne fonctionne plus "
            "(erreur 404).\n\n"
            "Si ça vous intéresse, j'ai un contenu équivalent à jour sur "
            "{our_url} qui pourrait servir de remplaçant naturel pour vos "
            "lecteurs.\n\n"
            "Bonne journée,\n"
            "{sender_name}\n"
            "{sender_signature}"
        ),
    },
    "unlinked_mention": {
        "subject": "Petit oubli : « {brand_term} » mentionné sans lien",
        "body": (
            "Bonjour{contact_name_clause},\n\n"
            "Merci d'avoir mentionné {brand_term} dans votre article "
            "« {target_page_title} » — j'ai apprécié le contexte dans "
            "lequel vous en parlez.\n\n"
            "Petit détail : la mention n'est pas liée. Si vous voulez "
            "permettre à vos lecteurs d'aller voir directement, l'URL est "
            "{our_url}. Aucune obligation évidemment.\n\n"
            "Bonne journée,\n"
            "{sender_name}\n"
            "{sender_signature}"
        ),
    },
    "gap_concurrent": {
        "subject": "Ressource complémentaire pour « {target_page_title} »",
        "body": (
            "Bonjour{contact_name_clause},\n\n"
            "J'ai lu votre article « {target_page_title } » et l'ai trouvé "
            "très utile sur {topic}.\n\n"
            "Si vous cherchez une ressource pour compléter, j'ai écrit "
            "{our_url} qui couvre l'angle {our_angle} — pas redondant avec "
            "le vôtre, complémentaire.\n\n"
            "À votre disposition,\n"
            "{sender_name}\n"
            "{sender_signature}"
        ),
    },
    "haro": {
        "subject": "Réponse expert : {haro_topic}",
        "body": (
            "Bonjour,\n\n"
            "En réponse à votre demande sur {haro_topic} :\n\n"
            "{expert_quote}\n\n"
            "Pour me citer : {sender_name}, {sender_role} chez Triskell "
            "Studio. Notre site : {our_url}.\n\n"
            "Si vous avez besoin de précisions ou d'une visio, je suis "
            "dispo sur {sender_email}.\n\n"
            "Cordialement,\n"
            "{sender_name}"
        ),
    },
}


# ---------------------------------------------------------------------------
# Agent personnaliseur
# ---------------------------------------------------------------------------
class OutreachPersonalizer(agents.Agent):
    name = "outreach_personalizer"
    role = """Tu es l'OutreachPersonalizer de Le Phare.

Mission : à partir d'un template d'email + données sur la cible (site, page,
contact), produire une version finale chaleureuse, courte, qui sonne comme
un humain qui a vraiment lu la page.

Règles :
- Garder le ton du template (poli, concret)
- Personnaliser la 1ère phrase (référence à la page cible)
- Pas de flatterie creuse ("super article")
- 80-120 mots max
- Voix Triskell (préambule)

Format JSON strict : {"subject": str, "body": str}"""

    def run(self, *, template_subject: str, template_body: str,
            target_page_title: str, target_domain: str,
            target_excerpt: str = "", contact_name: str = "",
            our_url: str = "", brand_term: str = "",
            sender_name: str = "Jordan Bourillot",
            sender_signature: str = "Triskell Studio · triskell-studio.fr",
            extras: Optional[dict] = None,
            app_state=None) -> dict:
        prompt = f"""TEMPLATE SUJET : {template_subject}

TEMPLATE CORPS :
{template_body}

DONNÉES :
- Contact : {contact_name or 'inconnu'}
- Page cible : {target_page_title} ({target_domain})
- Extrait page cible : {target_excerpt[:300]}
- Notre URL : {our_url}
- Marque : {brand_term}
- Extras : {extras or {}}
- Expéditeur : {sender_name}

Produis l'email final au format JSON."""
        out = self.call(prompt, app_state=app_state)
        return out if isinstance(out, dict) else {}


# ---------------------------------------------------------------------------
# Pipeline principal
# ---------------------------------------------------------------------------
def queue_drafts(site_id: str, *, max_drafts: int = 5,
                 app_state=None) -> dict:
    """Pour chaque opportunité backlink, crée un draft d'email."""
    site = repo.get_site(site_id)
    if not site:
        return {"ok": False, "error": "site introuvable"}
    sb = repo._sb()
    if sb is None:
        return {"ok": False, "error": "Supabase indispo"}

    # Lit les opportunités de backlinks pas encore démarchées
    opps = repo.list_backlinks(site_id, kind="opportunity", limit=50)
    if not opps:
        return {"ok": True, "drafts_created": 0,
                "message": "aucune opportunité backlink à démarcher"}

    # Charge ou crée la campagne par défaut
    campaign_id = _ensure_default_campaign(sb, site_id)
    if not campaign_id:
        return {"ok": False, "error": "création campagne échouée"}

    personalizer = OutreachPersonalizer()
    created = 0
    for opp in opps[:max_drafts]:
        target_domain = opp.get("source_domain") or ""
        # Détection : a-t-on déjà un draft pour ce target ?
        existing = (sb.table("phare_outreach_messages").select("id")
                    .eq("site_id", site_id)
                    .eq("target_domain", target_domain).limit(1).execute().data)
        if existing:
            continue
        # Choix du template
        kind_hint = opp.get("notes", "").split(":", 1)[0] or "unlinked_mention"
        kind = kind_hint if kind_hint in DEFAULT_TEMPLATES else "unlinked_mention"
        template = DEFAULT_TEMPLATES[kind]
        try:
            email = personalizer.run(
                template_subject=template["subject"],
                template_body=template["body"],
                target_page_title=target_domain,
                target_domain=target_domain,
                target_excerpt=opp.get("notes", ""),
                contact_name="",
                our_url=f"https://{site.get('domain', '')}/",
                brand_term=site.get("name", "Triskell Studio"),
                app_state=app_state,
            )
        except Exception as exc:
            logger.warning("outreach LLM: %s", exc)
            continue
        if not email or not email.get("subject"):
            continue
        try:
            sb.table("phare_outreach_messages").insert({
                "campaign_id": campaign_id,
                "site_id": site_id,
                "target_domain": target_domain,
                "target_email": "",
                "proposed_subject": email["subject"][:200],
                "proposed_body": email.get("body", ""),
                "variables": {"opp_kind": kind,
                               "source_url": opp.get("source_url", "")},
                "status": "draft",
            }).execute()
            created += 1
        except Exception as exc:
            logger.warning("outreach insert: %s", exc)

    if created:
        repo.insert_action({
            "site_id": site_id,
            "agent": "outreach",
            "kind": "recommandation",
            "title": f"{created} mails de démarchage backlinks à valider",
            "detail_md": (f"Va dans Outreach → Bac pour relire chaque mail "
                          f"avant envoi. Auto-envoi : "
                          f"{repo.get_config().get('outreach_auto_send', False)}"),
            "status": "draft",
            "impact": 4, "effort": 2,
        })

    return {"ok": True, "drafts_created": created,
            "campaign_id": campaign_id}


def _ensure_default_campaign(sb, site_id: str) -> Optional[str]:
    rows = (sb.table("phare_outreach_campaigns").select("id")
            .eq("site_id", site_id).eq("name", "default").limit(1).execute().data)
    if rows:
        return rows[0]["id"]
    res = sb.table("phare_outreach_campaigns").insert({
        "site_id": site_id,
        "name": "default",
        "kind": "mixed",
        "template_subject": "{subject}",
        "template_body": "{body}",
    }).execute()
    if res.data:
        return res.data[0]["id"]
    return None


# ---------------------------------------------------------------------------
# Envoi SMTP
# ---------------------------------------------------------------------------
def send_message(message_id: str, *, app_state=None) -> dict:
    """Envoie un message via SMTP partagé Triskell. Met à jour le statut."""
    sb = repo._sb()
    if sb is None:
        return {"ok": False, "error": "Supabase indispo"}
    rows = sb.table("phare_outreach_messages").select("*").eq("id", message_id).limit(1).execute().data
    if not rows:
        return {"ok": False, "error": "message introuvable"}
    msg = rows[0]
    if msg["status"] != "draft" and msg["status"] != "approved":
        return {"ok": False, "error": f"statut {msg['status']} non envoyable"}
    if not msg.get("target_email"):
        return {"ok": False, "error": "target_email vide"}

    # Récupère les credentials SMTP partagés (cohérent avec ReplyResponder)
    smtp_cfg = _get_smtp_config(sb)
    if not smtp_cfg:
        return {"ok": False, "error": "SMTP partagé non configuré"}

    try:
        mime = MIMEText(msg["proposed_body"], "plain", "utf-8")
        mime["Subject"] = msg["proposed_subject"]
        mime["From"] = formataddr((smtp_cfg["from_name"], smtp_cfg["from_email"]))
        mime["To"] = msg["target_email"]
        mime["Message-ID"] = make_msgid(domain="triskell-studio.fr")
        with smtplib.SMTP(smtp_cfg["host"], smtp_cfg["port"], timeout=20) as s:
            s.starttls()
            s.login(smtp_cfg["user"], smtp_cfg["password"])
            s.send_message(mime)
    except Exception as exc:
        logger.warning("outreach SMTP: %s", exc)
        return {"ok": False, "error": str(exc)}

    sb.table("phare_outreach_messages").update({
        "status": "sent",
        "sent_at": datetime.now(timezone.utc).isoformat(),
        "next_follow_up_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
    }).eq("id", message_id).execute()
    return {"ok": True, "sent_to": msg["target_email"]}


def _get_smtp_config(sb) -> Optional[dict]:
    try:
        rows = (sb.table("shared_settings").select("value")
                .eq("key", "outreach").limit(1).execute().data)
        if not rows:
            return None
        v = rows[0].get("value") or {}
        if not v.get("smtp_host") or not v.get("smtp_user"):
            return None
        return {
            "host": v["smtp_host"],
            "port": int(v.get("smtp_port", 587)),
            "user": v["smtp_user"],
            "password": v.get("smtp_password", ""),
            "from_email": v.get("from_email") or v["smtp_user"],
            "from_name": v.get("from_name") or "Jordan Bourillot",
        }
    except Exception:
        return None


def process_due_follow_ups(*, app_state=None) -> dict:
    """Lance les relances dues. Appelé par le scheduler."""
    sb = repo._sb()
    if sb is None:
        return {"ok": False}
    cfg = repo.get_config()
    delays = cfg.get("outreach_follow_up_days", [7, 14])
    now = datetime.now(timezone.utc).isoformat()
    rows = (sb.table("phare_outreach_messages").select("*")
            .eq("status", "sent")
            .lte("next_follow_up_at", now).execute().data) or []
    sent = 0
    for m in rows:
        count = m.get("follow_up_count", 0)
        if count >= len(delays):
            continue
        # Génère un mail de relance court
        relance_body = (
            f"Bonjour,\n\nPetite relance sur mon précédent message au sujet "
            f"de {m['proposed_subject']}. Si le timing n'est pas bon, "
            f"aucun souci, fais-moi signe.\n\n"
            f"À tout hasard, voici l'idée en une ligne : "
            f"{m['proposed_subject']}.\n\nJordan"
        )
        relance_subject = f"Re: {m['proposed_subject']}"
        msg_id = sb.table("phare_outreach_messages").insert({
            "campaign_id": m["campaign_id"],
            "site_id": m["site_id"],
            "target_domain": m["target_domain"],
            "target_email": m["target_email"],
            "proposed_subject": relance_subject,
            "proposed_body": relance_body,
            "variables": {"follow_up_of": m["id"]},
            "status": "draft",
        }).execute()
        if msg_id.data:
            sb.table("phare_outreach_messages").update({
                "follow_up_count": count + 1,
                "next_follow_up_at": (datetime.now(timezone.utc)
                                       + timedelta(days=delays[min(count + 1, len(delays) - 1)])).isoformat()
                                       if count + 1 < len(delays) else None,
            }).eq("id", m["id"]).execute()
            sent += 1
    return {"ok": True, "follow_ups_drafted": sent}
