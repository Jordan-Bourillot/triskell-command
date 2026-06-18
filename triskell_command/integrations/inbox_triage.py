"""Inbox Triage — décide si un mail entrant mérite l'attention de Jordan.

Pourquoi ce module
------------------
Avant, l'IA ne lisait QUE les réponses des prospects déjà connus
(replies_poller → _classify_reply). Un mail d'un inconnu (nouveau contact,
client existant, partenaire, fournisseur…) était simplement rangé dans la
boîte de réception, SANS analyse et SANS alerte → on pouvait passer à côté
d'un mail important.

Ce module comble ce trou. Deux entrées, une seule responsabilité (décider
« est-ce que ça mérite l'œil de Jordan, et à quel point ? ») :

1. `triage_stranger_mail(...)`  — pour les mails HORS prospects : une IA
   lit le mail et renvoie {attention, priority, category, summary, reason}.
   Sans IA configurée → repli prudent (on alerte quand même, mieux vaut
   un mail de trop qu'un mail raté).

2. `attention_for_reply(...)`   — pour les réponses de prospects DÉJÀ
   classées (interested / not_now / no / unsubscribe / unknown) : on en
   déduit l'attention SANS appel IA supplémentaire (déterministe, gratuit).

Le module est PUR : aucune écriture base, aucun envoi push. L'orchestration
(écrire la fiche, envoyer l'alerte téléphone) reste dans replies_poller, qui
a déjà le client Supabase et la boucle IMAP. → testable sans réseau.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config (shared_settings 'inbox_triage')
# ---------------------------------------------------------------------------
# Activé PAR DÉFAUT : Jordan a demandé explicitement « être prévenu à chaque
# fois qu'un mail mérite mon attention ». On ne le met donc pas en opt-in.
DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": True,
    # Alerter sur les mails d'inconnus (hors base prospects) ?
    "notify_strangers": True,
    # Alerter sur les réponses de prospects qui méritent attention ?
    "notify_prospect_replies": True,
    # Faire analyser les inconnus par l'IA (sinon repli sur le sujet) ?
    "analyze_strangers_with_ai": True,
    # Seuil de notification : on n'alerte que si la priorité du mail est
    # >= ce seuil. 'low' = tout, 'normal' = tout sauf le pour-info,
    # 'high' = uniquement l'urgent.
    "min_priority": "normal",
    # À qui envoyer l'alerte. 'jordan' (défaut, cohérent avec le chien de
    # garde) ; "" ou "all" = à tous les associés inscrits.
    "notify_user_id": "jordan",
}


def load_config(client) -> dict:
    """Lit shared_settings 'inbox_triage' fusionné sur les valeurs par défaut.

    Ne lève jamais : en cas de souci on renvoie les valeurs par défaut (le
    tri ne doit JAMAIS bloquer la lecture des mails)."""
    try:
        raw = client.get_shared_setting("inbox_triage", {}) or {}
    except Exception:
        raw = {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = {}
    out = dict(DEFAULT_CONFIG)
    if isinstance(raw, dict):
        out.update({k: v for k, v in raw.items() if v is not None})
    # Garde-fous de valeurs
    if out.get("min_priority") not in ("low", "normal", "high"):
        out["min_priority"] = "normal"
    return out


def save_config(client, config: dict) -> None:
    client.set_shared_setting("inbox_triage", config)


# ---------------------------------------------------------------------------
# Priorités
# ---------------------------------------------------------------------------
_PRIORITY_RANK = {"low": 0, "normal": 1, "high": 2}


def priority_rank(p: str) -> int:
    return _PRIORITY_RANK.get((p or "").lower(), 1)


def passes_threshold(priority: str, min_priority: str) -> bool:
    """True si la priorité du mail atteint le seuil configuré."""
    return priority_rank(priority) >= priority_rank(min_priority)


def push_priority(internal_priority: str) -> str:
    """Traduit notre priorité interne vers la priorité du moteur push.

    high → 'urgent' (reste affichée jusqu'au clic, vibration forte, 🔴)
    normal → 'normal'
    low → 'low' (silencieux)
    """
    return {"high": "urgent", "normal": "normal", "low": "low"}.get(
        (internal_priority or "").lower(), "normal")


# ---------------------------------------------------------------------------
# Réponses de prospects : attention déterministe (zéro coût IA)
# ---------------------------------------------------------------------------
def attention_for_reply(category: str, confidence: float = 0.0) -> dict:
    """Déduit {attention, priority} de la catégorie déjà calculée.

    - interested   → 🔥 urgent (Jordan doit sauter dessus)
    - not_now      → à savoir, normal
    - unknown      → un humain a écrit un truc qu'on n'a pas su classer :
                     ça mérite un coup d'œil (normal)
    - no           → refus net, déjà traité tout seul (marqué refusé) : pas
                     d'alerte (on ne veut pas notifier les « non merci »)
    - unsubscribe  → désinscription, traitée tout seule : pas d'alerte
    """
    cat = (category or "").lower().strip()
    if cat == "interested":
        return {"attention": True, "priority": "high"}
    if cat in ("not_now", "unknown"):
        return {"attention": True, "priority": "normal"}
    # no / unsubscribe / autre → géré automatiquement, pas d'alerte
    return {"attention": False, "priority": "low"}


# ---------------------------------------------------------------------------
# Mails d'inconnus : analyse IA
# ---------------------------------------------------------------------------
# Catégories proposées à l'IA — libellés en français normal (pas de jargon),
# cohérents avec ce que Jordan lira sur sa pastille.
_STRANGER_CATEGORIES = (
    "client", "prospect entrant", "partenaire", "fournisseur",
    "facture / administratif", "candidature", "question",
    "notification", "spam", "autre",
)

TRIAGE_PROMPT = (
    "Tu tries la boîte mail d'un patron de petite agence web. Pour le mail "
    "ci-dessous (envoyé par quelqu'un qui n'est PAS encore dans son fichier "
    "de prospection), décide s'il mérite SON attention.\n"
    "\n"
    "Réponds par un JSON valide UNIQUEMENT, sans aucun texte autour :\n"
    '{"attention": true, "priority": "high", '
    '"category": "question", "summary": "...", "reason": "..."}\n'
    "\n"
    "- attention = true si un vrai humain attend quelque chose de lui "
    "(une question, une demande, une opportunité, un client mécontent, une "
    "proposition de partenariat, un devis entrant, un message personnel). "
    "false pour une pub, une newsletter, une notification automatique, un "
    "reçu, un accusé de réception ou un message sans intérêt.\n"
    "- priority : \"high\" = urgent ou opportunité chaude ou client fâché ; "
    "\"normal\" = à traiter mais sans urgence ; \"low\" = simple information.\n"
    "- category : un mot parmi " + ", ".join(_STRANGER_CATEGORIES) + ".\n"
    "- summary : UNE phrase courte en français simple qui dit de quoi il "
    "s'agit (12 mots max). Pas de deux-points d'annonce, pas de tiret "
    "cadratin, pas de tournure ampoulée.\n"
    "- reason : en quelques mots, pourquoi cette décision.\n"
)


def _fallback_triage(subject: str, body: str) -> dict:
    """Repli sans IA : on alerte quand même (mieux vaut un mail de trop).

    On reste prudent sur la priorité (normal) et on résume par le sujet, ou
    à défaut la première ligne du corps."""
    summary = (subject or "").strip()
    if not summary:
        first_line = ((body or "").strip().splitlines() or [""])[0]
        summary = first_line.strip()
    summary = summary[:140] or "Nouveau mail à regarder"
    return {
        "attention": True,
        "priority": "normal",
        "category": "à voir",
        "summary": summary,
        "reason": "pas d'IA configurée — alerte par précaution",
    }


def _normalize_triage(data: dict, *, subject: str, body: str) -> dict:
    """Valide/nettoie la sortie IA. Tout champ douteux → valeur sûre."""
    out = _fallback_triage(subject, body)
    if not isinstance(data, dict):
        return out
    # attention : accepte bool, "true"/"false", 0/1
    att = data.get("attention")
    if isinstance(att, str):
        att = att.strip().lower() in ("true", "1", "oui", "yes")
    out["attention"] = bool(att)
    # priority
    pr = (str(data.get("priority") or "")).strip().lower()
    out["priority"] = pr if pr in _PRIORITY_RANK else "normal"
    # category (libre mais bornée à une longueur raisonnable)
    cat = (str(data.get("category") or "")).strip()
    out["category"] = (cat[:40] or "à voir")
    # summary
    summ = (str(data.get("summary") or "")).strip()
    if summ:
        out["summary"] = summ[:200]
    # reason
    reason = (str(data.get("reason") or "")).strip()
    if reason:
        out["reason"] = reason[:300]
    return out


def triage_stranger_mail(ai: dict, *, from_addr: str, subject: str,
                          body: str) -> dict:
    """Analyse un mail d'inconnu. Renvoie
    {attention, priority, category, summary, reason}.

    Ne lève jamais. Sans IA / sur erreur → repli prudent (_fallback_triage).
    """
    provider = ((ai or {}).get("provider") or "").strip()
    api_key = ((ai or {}).get("api_key") or "").strip()
    model = ((ai or {}).get("model") or "").strip()
    if not provider or not api_key:
        return _fallback_triage(subject, body)
    try:
        from triskell_core.ai.providers import send_to_provider, ProviderError
    except ImportError:
        return _fallback_triage(subject, body)

    user_msg = (
        f"De : {from_addr}\nObjet : {subject}\n\n"
        f"Corps :\n{(body or '')[:3000]}"
    )
    try:
        prompt = TRIAGE_PROMPT + "\n\n---\n\n" + user_msg
        text = send_to_provider(provider, model or "", prompt, {provider: api_key})
        text = (text or "").strip()
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(0))
                return _normalize_triage(data, subject=subject, body=body)
            except Exception:
                pass
        # IA a répondu mais pas en JSON exploitable → repli prudent
        return _fallback_triage(subject, body)
    except ProviderError as exc:
        logger.debug("triage IA indisponible: %s", exc)
        return _fallback_triage(subject, body)
    except Exception as exc:
        logger.debug("triage IA erreur: %s", exc)
        return _fallback_triage(subject, body)


# ---------------------------------------------------------------------------
# Construction du texte de l'alerte téléphone
# ---------------------------------------------------------------------------
_REPLY_CATEGORY_LABELS = {
    "interested": "Intéressé",
    "not_now": "Pas tout de suite",
    "unknown": "Réponse à lire",
    "no": "Refus",
    "unsubscribe": "Désinscription",
}


def build_reply_push(*, display_name: str, category: str,
                      subject: str) -> tuple[str, str]:
    """(titre, corps) de l'alerte pour une réponse de prospect."""
    name = (display_name or "").strip() or "Un prospect"
    subj = (subject or "").strip() or "(sans objet)"
    cat = (category or "").lower()
    if cat == "interested":
        return ("🔥 Un prospect intéressé", f"{name} a répondu : {subj}")
    label = _REPLY_CATEGORY_LABELS.get(cat, "Nouvelle réponse")
    return (f"📨 {label}", f"{name} : {subj}")


def _sender_label(from_addr: str) -> str:
    """Nom lisible depuis une adresse mail (avant l'arobase, sinon brut)."""
    a = (from_addr or "").strip()
    if "@" in a:
        return a.split("@", 1)[0].replace(".", " ").replace("_", " ").strip() or a
    return a or "Inconnu"


def build_stranger_push(*, from_addr: str, triage: dict) -> tuple[str, str]:
    """(titre, corps) de l'alerte pour un mail d'inconnu."""
    summary = (triage or {}).get("summary") or "Mail à regarder"
    category = (triage or {}).get("category") or ""
    sender = _sender_label(from_addr)
    title = "📥 Mail à regarder"
    if category and category.lower() not in ("autre", "à voir"):
        title = f"📥 {category[:1].upper()}{category[1:]}"
    body = f"{sender} — {summary}"
    return (title, body[:300])


def should_notify(config: dict, *, is_stranger: bool, attention: bool,
                   priority: str) -> bool:
    """Règle unique de décision d'alerte (centralisée pour être testable)."""
    if not config.get("enabled", True):
        return False
    if not attention:
        return False
    if is_stranger and not config.get("notify_strangers", True):
        return False
    if (not is_stranger) and not config.get("notify_prospect_replies", True):
        return False
    return passes_threshold(priority, config.get("min_priority", "normal"))
