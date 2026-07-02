"""Garde-fous centraux du systeme de mail.

Source de verite pour repondre a la question : a-t-on le droit d'envoyer un
mail a ce prospect maintenant ?

Centralise :
- les statuts "definitivement plus de mails" (RGPD) : refused, unsubscribed,
  bounced (en plus de won/lost qui sont des fin de cycle business).
- le marquage "unsubscribe" et "bounced" + miroir dans email_history pour
  audit.
- l'anti-doublon : a-t-on deja mail le prospect dans les N dernieres heures
  depuis n'importe quel runner ?
- la verification de variables non remplacees (du style {name}, {{name}})
  dans subject + body avant envoi.

TOUS les runners (convoy, drip, dormant_recycler, multichannel, morning_mailer,
reply_responder) DOIVENT passer par should_contact() avant chaque envoi.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from .multi_tenant import with_workspace

logger = logging.getLogger(__name__)


# --- Statuts qui interdisent definitivement de remailer ---
# - won/lost : cycle business termine
# - refused : prospect a dit "non" ou "stop" explicitement
# - unsubscribed : prospect a demande la desinscription (legal RGPD)
# - bounced : adresse morte, on degrade notre reputation si on continue
NO_CONTACT_STATUSES = frozenset({
    "won", "lost", "refused", "unsubscribed", "bounced",
})

# --- Statuts "a en parle bientot mais pas tout de suite" ---
# 'replied' = a repondu mais on n'a pas encore traite. Les runners
# automatiques NE DOIVENT PAS mailer un prospect "replied" (laisser l'humain
# repondre d'abord). Mais ce n'est pas un statut definitif.
SOFT_PAUSE_STATUSES = frozenset({"replied"})


# Helpers d'auto-detection des bounces (sender + sujet typique de DSN)
BOUNCE_SENDERS = (
    "mailer-daemon@", "postmaster@", "mail-daemon@", "noreply-",
    "bounce@", "bounces@", "delivery@",
)
BOUNCE_SUBJECTS = (
    "delivery status notification",
    "delivery failure",
    "delivery failed",
    "delivery has failed",
    "mail delivery failed",
    "mail delivery failure",
    "mail delivery problem",
    "undelivered mail",
    "undeliverable",
    "returned mail",
    "could not be delivered",
    "ne peut etre delivre",
    "n'a pas pu etre livre",
    "n'a pas pu etre delivre",
    "echec de livraison",
    "echec de remise",
    "echec de la remise",
    "non remis",
    "non distribue",
)
# Regex emails dans le body d'un DSN — on extrait l'adresse de la victime
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


# =============================================================================
# Detection des mails automatiques (newsletters, notifications, no-reply)
# =============================================================================
# Pourquoi : la vue "Reponses" doit afficher UNIQUEMENT les vraies reponses
# humaines de prospects. Les newsletters, notifications de plateformes
# (Instagram, Google, Meta, banque, etc.), confirmations automatiques et
# accuses de reception polluent la vue et bruitent la classification IA.
# On filtre AVANT le match prospect : un mail auto va dans inbox_received
# pour audit, mais jamais dans reply_received.

# Patterns de senders typiques d'envois automatiques.
# Match : exact local-part au debut (noreply@x), ou contient le pattern.
AUTOMATED_SENDER_PREFIXES = (
    "noreply@", "no-reply@", "no_reply@", "donotreply@", "do-not-reply@",
    "notification@", "notifications@", "notify@",
    "newsletter@", "news@", "newsletters@",
    "security@", "alerts@", "alert@", "alerting@",
    "info@meta.com", "info@facebookmail.com",
    "automated@", "auto@", "robot@", "bot@",
    "support-noreply@", "noreply-",
    "system@", "sys@",
    "billing@", "invoice@", "invoices@", "facturation@",
    "newsletter-", "noreply.",
)
# Patterns de domaines reconnus comme envoyeurs auto
AUTOMATED_SENDER_DOMAINS = (
    "@mail.instagram.com", "@facebookmail.com", "@mail.notion.so",
    "@notify.bsky.social", "@reply.github.com", "@noreply.github.com",
    "@accounts.google.com", "@e.linkedin.com", "@linkedin.com",
    "@mail.tiktok.com", "@bnc.lt", "@stripe.com",
)
# Mots-cles dans le sujet typiques de notifications
AUTOMATED_SUBJECT_HINTS = (
    "new login", "nouvelle connexion", "security alert", "alerte de securite",
    "verify your email", "confirm your email", "verifiez votre",
    "confirm your account", "your verification code", "code de verification",
    "your receipt", "votre recu", "your invoice", "votre facture",
    "newsletter", "bulletin",
)


def looks_like_automated(headers: dict, from_addr: str,
                          subject: str = "") -> bool:
    """Heuristique : ce mail entrant est-il un envoi automatique ?

    Retourne True si :
    - headers indiquent envoi auto (List-Unsubscribe, Auto-Submitted,
      Precedence: bulk/list/auto_reply)
    - sender matche un pattern noreply/notification/newsletter/security/etc
    - sender appartient a un domaine connu d'envois auto
    - sujet contient un mot-cle typique de notification

    Conservatif : en cas de doute, retourne False (mieux vaut un faux negatif
    qu'un faux positif qui ferait disparaitre une vraie reponse prospect).
    """
    h = {k.lower(): (v or "") for k, v in (headers or {}).items()}

    # 1. Headers techniques : signature universelle des envois bulk/auto
    # List-Unsubscribe present = newsletter ou liste de diffusion
    if h.get("list-unsubscribe"):
        return True
    # Auto-Submitted != "no" signale un envoi auto (RFC 3834)
    auto_sub = h.get("auto-submitted", "").lower().strip()
    if auto_sub and auto_sub != "no":
        return True
    # Precedence: bulk / list / auto_reply / junk
    prec = h.get("precedence", "").lower().strip()
    if prec in ("bulk", "list", "auto_reply", "junk"):
        return True
    # X-Auto-Response-Suppress = signe d'auto-responder
    if h.get("x-auto-response-suppress"):
        return True
    # Feedback-ID = utilise par Google/Gmail pour le tracking d'envois bulk
    if h.get("feedback-id"):
        return True

    # 2. Patterns d'expediteurs
    f = (from_addr or "").lower().strip()
    if f:
        for p in AUTOMATED_SENDER_PREFIXES:
            if f.startswith(p) or f"<{p}" in f:
                return True
        for d in AUTOMATED_SENDER_DOMAINS:
            if d in f:
                return True

    # 3. Sujets typiques de notifs (dernier recours, plus risque)
    s = (subject or "").lower()
    for hint in AUTOMATED_SUBJECT_HINTS:
        if hint in s:
            return True

    return False

# Regex variables non remplacees a refuser dans un mail final
# - {name} ou {{name}} : python format / mustache
# - %name% : encore d'autres systemes
# On exclut les caracteres d'espace dans le nom pour eviter de matcher du
# code source ou des accolades JSON valides en HTML.
_UNRENDERED_VAR_RE = re.compile(
    r"(?<!\\)(\{\{?[A-Za-z_][A-Za-z0-9_.]*\}?\}|%[A-Za-z_][A-Za-z0-9_]*%)"
)


# =============================================================================
# Statut prospect : lecture + transitions
# =============================================================================
def get_status(client, prospect_id: str) -> str:
    """Renvoie le statut courant du prospect (lower), ou '' si introuvable."""
    if not prospect_id:
        return ""
    try:
        res = (client.raw.table("prospects").select("status")
               .eq("id", prospect_id).limit(1).execute())
        return ((res.data or [{}])[0].get("status") or "").lower()
    except Exception as exc:
        logger.debug("get_status: %s", exc)
        return ""


def is_no_contact(status: str) -> bool:
    """Faut-il refuser tout nouvel envoi a ce prospect ?"""
    return (status or "").lower() in NO_CONTACT_STATUSES


def mark_unsubscribed(client, prospect_id: str, reason: str = "") -> None:
    """Passe un prospect en 'unsubscribed' definitivement. RGPD."""
    if not prospect_id:
        return
    try:
        client.raw.table("prospects").update({
            "status": "unsubscribed",
            "last_contact_at": datetime.now().isoformat(timespec="seconds"),
            "updated_by": client.user_id,
        }).eq("id", prospect_id).execute()
        _audit("unsubscribed", client, prospect_id, reason)
    except Exception as exc:
        logger.warning("mark_unsubscribed KO: %s", exc)


def mark_unsubscribed_by_email(client, email: str, reason: str = "") -> int:
    """Passe en 'unsubscribed' TOUTES les fiches portant cette adresse.

    Sert au clic sur le lien de désinscription : on n'a que l'adresse, pas
    forcément l'id de fiche. Renvoie le nombre de fiches passées en
    désinscrit (0 si l'adresse n'est dans aucune fiche — la signature du
    lien a déjà été vérifiée en amont, donc on ne se base que sur elle).
    """
    addr = (email or "").strip().lower()
    if not addr:
        return 0
    try:
        rows = (client.raw.table("prospects")
                .select("id")
                .contains("emails", [addr])
                .execute().data or [])
    except Exception as exc:
        logger.warning("mark_unsubscribed_by_email lookup KO: %s", exc)
        rows = []
    n = 0
    for r in rows:
        pid = r.get("id")
        if not pid:
            continue
        try:
            client.raw.table("prospects").update({
                "status": "unsubscribed",
                "last_contact_at": datetime.now().isoformat(timespec="seconds"),
                "updated_by": client.user_id,
            }).eq("id", pid).execute()
            _audit("unsubscribed", client, pid, reason)
            n += 1
        except Exception as exc:
            logger.warning("mark_unsubscribed_by_email update KO: %s", exc)
    return n


def mark_refused(client, prospect_id: str, reason: str = "") -> None:
    """Passe en 'refused' (prospect a dit non clairement)."""
    if not prospect_id:
        return
    try:
        client.raw.table("prospects").update({
            "status": "refused",
            "last_contact_at": datetime.now().isoformat(timespec="seconds"),
            "updated_by": client.user_id,
        }).eq("id", prospect_id).execute()
        _audit("refused", client, prospect_id, reason)
    except Exception as exc:
        logger.warning("mark_refused KO: %s", exc)


def extract_bounce_reason(body: str) -> str:
    """Devine une raison LISIBLE (français simple) du rebond à partir du
    corps de l'avis de non-délivrance (DSN). Renvoie "" si rien de
    reconnaissable — l'appelant met alors un libellé générique. Heuristique
    volontairement tolérante : un nouveau motif → on enrichit ICI."""
    b = (body or "").lower()
    if not b:
        return ""

    def has(*keys: str) -> bool:
        return any(k in b for k in keys)

    if has("user unknown", "no such user", "does not exist", "doesn't exist",
           "recipient address rejected", "unknown recipient", "no mailbox",
           "mailbox unavailable", "address not found", "recipient not found",
           "user not found", "550 5.1.1", "utilisateur inconnu",
           "adresse inconnue", "n'existe pas", "destinataire inconnu"):
        return "Adresse qui n'existe pas (boîte introuvable)"
    if has("mailbox full", "over quota", "insufficient storage", "552 5.2.2",
           "boîte pleine", "quota exceeded", "mailbox is full"):
        return "Boîte pleine (saturée)"
    if has("domain not found", "no such domain", "host not found", "nxdomain",
           "5.4.4", "domain does not exist", "domaine introuvable", "no mx"):
        return "Domaine introuvable (le serveur mail n'existe plus)"
    if has("blocked", "blacklist", "spam", "reputation", "policy reasons",
           "rejected due to", "554 5.7", "5.7.1", "access denied",
           "bloqué", "refusé", "spamhaus", "barracuda"):
        return "Bloqué par leur serveur (filtre anti-spam / réputation)"
    if has("disabled", "inactive", "suspended", "no longer", "account closed",
           "désactivé", "compte fermé", "compte désactivé"):
        return "Compte fermé ou désactivé"

    m = re.search(r"diagnostic-code:\s*(.+)", body, re.IGNORECASE)
    if m:
        return "Erreur du serveur : " + m.group(1).strip()[:160]
    m = re.search(r"\b5\d\d[ \-]\d\.\d\.\d.*", body)
    if m:
        return "Erreur du serveur : " + m.group(0).strip()[:160]
    return ""


def mark_bounced(client, prospect_id: str, bounced_address: str = "",
                  reason: str = "", account_id: str = "") -> None:
    """Passe en 'bounced' : adresse morte, on ne tape plus dedans.

    account_id (optionnel) = la boîte d'ENVOI dont le mail a rebondi (le
    DSN arrive dans la boîte de l'expéditeur). Tracé dans email_history
    pour que la rampe de montée auto puisse freiner la bonne boîte.
    """
    if not prospect_id:
        return
    try:
        patch = {
            "status": "bounced",
            "last_contact_at": datetime.now().isoformat(timespec="seconds"),
            "updated_by": client.user_id,
        }
        # Garde la raison LISIBLE sur la fiche (visible direct dans la liste
        # « Adresses mortes »), sans jamais écraser la note existante ni la
        # dupliquer si la fiche a déjà rebondi.
        if reason:
            try:
                cur = (client.raw.table("prospects").select("notes")
                       .eq("id", prospect_id).limit(1).execute().data or [{}])[0]
                old = (cur.get("notes") or "").strip()
                if "Adresse morte" not in old:
                    tag = f"📭 Adresse morte : {reason}"
                    patch["notes"] = ((old + "\n" if old else "") + tag)[:2000]
            except Exception:
                pass
        client.raw.table("prospects").update(patch).eq(
            "id", prospect_id).execute()
        _audit("bounced", client, prospect_id,
               (reason or "") + (f" addr={bounced_address}" if bounced_address else ""),
               extra_fields={"account_id": account_id},
               body=reason or "")
    except Exception as exc:
        logger.warning("mark_bounced KO: %s", exc)


def _audit(kind: str, client, prospect_id: str, reason: str,
           extra_fields: dict | None = None, body: str = "") -> None:
    """Trace l'evenement dans email_history (best-effort). `body` =
    texte lisible affiché dans la timeline de la fiche (ex. la raison
    d'un rebond)."""
    try:
        extra = {"reason": (reason or "")[:500], "auto": True}
        if extra_fields:
            extra.update({k: v for k, v in extra_fields.items() if v})
        client.raw.table("email_history").insert(with_workspace(client, {
            "prospect_id": prospect_id,
            "kind": f"status_{kind}",
            "ts": datetime.now().isoformat(timespec="seconds"),
            "subject": f"[auto] prospect marque {kind}",
            "body": (body or "")[:1000],
            "extra": extra,
            "created_by": client.user_id,
        })).execute()
    except Exception as exc:
        logger.warning("audit %s KO: %s", kind, exc)


# =============================================================================
# Detection des bounces (DSN) dans la boite de reception
# =============================================================================
def looks_like_bounce(from_addr: str, subject: str) -> bool:
    """Heuristique : ce mail entrant est-il un avis de non-delivrance ?"""
    f = (from_addr or "").lower()
    s = (subject or "").lower()
    # Rapports DMARC agrégés (sujet normalisé « Report Domain: … ») :
    # des statistiques d'authentification envoyées par Google/Yahoo/etc.,
    # souvent depuis noreply-dmarc-*/postmaster@ — PAS des rebonds.
    if "report domain:" in s or "dmarc" in f:
        return False
    if any(f.startswith(sender) or f"<{sender}" in f
           for sender in BOUNCE_SENDERS):
        return True
    return any(needle in s for needle in BOUNCE_SUBJECTS)


def extract_bounced_address(body: str, exclude: str = "") -> str:
    """Cherche dans le body du DSN une adresse mail (autre que l'expediteur
    du DSN, generalement nous-meme) qui est la victime du bounce."""
    if not body:
        return ""
    excl = (exclude or "").lower()
    for m in _EMAIL_RE.finditer(body):
        addr = m.group(0).lower()
        if excl and addr == excl:
            continue
        # Skip noreply/postmaster/mailer-daemon dans le body aussi
        if any(addr.startswith(p.replace("@", "")) or p in addr
               for p in BOUNCE_SENDERS):
            continue
        return addr
    return ""


# =============================================================================
# Anti-doublon : a-t-on deja mail ce prospect recemment ?
# =============================================================================
# Cooldown par défaut entre 2 envois automatiques au même prospect.
# 72h = 3 jours, valeur saine pour éviter de paraître insistant tout en
# laissant la place aux relances drip planifiées (qui ont leurs propres
# delais J+7 / J+30). Lecture optionnelle depuis shared_settings.
DEFAULT_COOLDOWN_HOURS = 72


def _read_cooldown_hours(client) -> int:
    """Renvoie le cooldown configuré (Réglages) ou DEFAULT_COOLDOWN_HOURS."""
    try:
        v = client.get_shared_setting("email_cooldown_hours", None)
        n = int(v) if v not in (None, "", 0) else DEFAULT_COOLDOWN_HOURS
        return max(1, min(n, 30 * 24))   # borne [1h, 30 jours]
    except Exception:
        return DEFAULT_COOLDOWN_HOURS


def has_recent_send(client, *, prospect_id: str = "", email: str = "",
                     hours: int | None = None,
                     forever: bool = False,
                     check_clients: bool = False) -> dict:
    """Renvoie {"recent": bool, "last_ts": str, "last_kind": str}.

    Considere TOUS les envois (campagnes, drip, dormant, manuels, reponses
    auto) — si un mail est parti vers ce prospect/email dans les `hours`
    dernieres heures, on bloque tout nouvel envoi automatique.

    forever=True : ignore le param `hours` et cherche dans TOUT l'historique
        (memoire a vie). Usage : prospection automatique stricte (Auto-pilote
        v2, convoy_runner, drip_runner) — jamais 2x le meme mail, quelle que
        soit la date du premier envoi.

    check_clients=True : verifie en plus que l'email n'est pas deja dans la
        table `clients`. Si trouve, renvoie recent=True avec last_kind="client".
        Filet applicatif en complement du trigger BDD #40.
    """
    if not (prospect_id or email):
        return {"recent": False, "last_ts": "", "last_kind": ""}
    sb = client.raw

    # Check croise clients (court-circuit rapide via clients_email_lower_idx)
    if check_clients and email:
        _e = email.lower().strip()
        if _e:
            try:
                r = (sb.table("clients").select("id, email")
                     .ilike("email", _e).limit(1).execute())
                if r.data:
                    return {"recent": True, "last_ts": "",
                            "last_kind": "client"}
            except Exception as exc:
                logger.debug("has_recent_send: client check KO (%s)", exc)

    if forever:
        # Pas de fenetre : on considere tout l'historique
        threshold = "1970-01-01T00:00:00+00:00"
    else:
        if hours is None:
            hours = _read_cooldown_hours(client)
        threshold = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    try:
        if prospect_id:
            # Query rapide quand on a l'id : on peut limiter à 1.
            q = (sb.table("email_history").select("ts,kind,extra,subject")
                 .eq("kind", "email_sent")
                 .gte("ts", threshold)
                 .eq("prospect_id", prospect_id)
                 .order("ts", desc=True).limit(1))
            res = q.execute()
            rows = res.data or []
            if rows:
                r = rows[0]
                return {"recent": True, "last_ts": r.get("ts", ""),
                        "last_kind": r.get("kind", "")}
            return {"recent": False, "last_ts": "", "last_kind": ""}

        # Pas d'id : on cherche par email dans extra->>to.
        # Bug historique : on limitait à 1 row, ce qui ramenait le DERNIER
        # mail envoyé toutes destinations confondues et passait toujours à
        # côté quand ce dernier mail n'était pas pour ce prospect-ci.
        # Fix : on tente une requête côté serveur sur extra->>to (cas
        # mono-destinataire, qui est notre standard) ; en fallback, on
        # ramène une fenêtre raisonnable puis on filtre côté Python.
        email_low = (email or "").lower().strip()
        if not email_low:
            return {"recent": False, "last_ts": "", "last_kind": ""}
        # 1) Tentative serveur : ultra-rapide, exploite l'index JSONB.
        try:
            q = (sb.table("email_history").select("ts,kind,extra,subject")
                 .eq("kind", "email_sent")
                 .gte("ts", threshold)
                 .eq("extra->>to", email_low)
                 .order("ts", desc=True).limit(1))
            res = q.execute()
            rows = res.data or []
            if rows:
                r = rows[0]
                return {"recent": True, "last_ts": r.get("ts", ""),
                        "last_kind": r.get("kind", "")}
        except Exception as exc:
            logger.debug("has_recent_send: server-side filter KO (%s) — "
                         "fallback client-side", exc)
        # 2) Fallback client-side : ramène les 500 derniers sends dans la
        # fenêtre et filtre par email. Coûteux mais correct.
        q = (sb.table("email_history").select("ts,kind,extra,subject")
             .eq("kind", "email_sent")
             .gte("ts", threshold)
             .order("ts", desc=True).limit(500))
        res = q.execute()
        rows = res.data or []
        for r in rows:
            extra = r.get("extra") or {}
            if isinstance(extra, str):
                try:
                    import json as _json
                    extra = _json.loads(extra)
                except Exception:
                    extra = {}
            tos = extra.get("to") or extra.get("recipients") or []
            if isinstance(tos, str):
                tos = [tos]
            if any((t or "").lower() == email_low for t in tos):
                return {"recent": True, "last_ts": r.get("ts", ""),
                        "last_kind": r.get("kind", "")}
    except Exception as exc:
        logger.debug("has_recent_send: %s", exc)
    return {"recent": False, "last_ts": "", "last_kind": ""}


# =============================================================================
# Decision globale : peut-on contacter ce prospect maintenant ?
# =============================================================================
def should_contact(client, prospect_id: str, *, email: str = "",
                    min_hours_between: int | None = None,
                    allow_replied: bool = False) -> dict:
    """Decision centrale : OK ou KO pour envoyer un mail ?

    Renvoie : {"ok": bool, "reason": str}.
    - KO si status in NO_CONTACT (refused/unsubscribed/bounced/won/lost)
    - KO si status='replied' et allow_replied=False (sauf reponse manuelle
      qu'on autorise via allow_replied)
    - KO si un envoi vers ce prospect a deja eu lieu dans les min_hours
      dernieres heures
    - OK sinon
    """
    status = get_status(client, prospect_id) if prospect_id else ""
    if is_no_contact(status):
        return {"ok": False, "reason": f"status:{status}"}
    if status in SOFT_PAUSE_STATUSES and not allow_replied:
        return {"ok": False, "reason": f"status:{status}"}
    if min_hours_between is None:
        min_hours_between = _read_cooldown_hours(client)
    recent = has_recent_send(client, prospect_id=prospect_id, email=email,
                              hours=min_hours_between)
    if recent.get("recent"):
        return {"ok": False, "reason": f"recent_send:{recent.get('last_ts')}"}
    return {"ok": True, "reason": ""}


# =============================================================================
# Validation d'un brouillon : peut-il encore partir AUJOURD'HUI ?
# =============================================================================
# Un brouillon peut dormir des jours dans « Brouillons à valider ». Entre sa
# création et le clic « Envoyer », le prospect a pu se désinscrire, rebondir,
# répondre, devenir client, ou être contacté par un autre canal. La décision
# se rejoue donc au moment de l'envoi, pas seulement à la création.
#
# Les relances (kind=follow_up_*) ont par nature un envoi antérieur : pour
# elles, seul un envoi APRÈS la création du brouillon bloque.
# ⚠️ Ces kinds doivent matcher ce que les producteurs écrivent VRAIMENT :
# dormant_recycler écrit « dormant_recycle », post_sale_runner écrit ses
# stages (« welcome_at_paid », « cross_sell_30d », « nps_90d »,
# « delivery_followup_N »). Avant l'alignement du 02/07/2026, aucun ne
# matchait → tous ces brouillons étaient invalidables (« déjà contacté »).
FOLLOW_UP_DRAFT_KINDS = frozenset({
    "follow_up_7d", "follow_up_30d", "post_sale", "dormant",
    "dormant_recycle",
    "welcome_at_paid", "cross_sell_30d", "nps_90d",
})

# Préfixes de kinds de relance à numéro variable (delivery_followup_1, _2…).
_FOLLOW_UP_KIND_PREFIXES = ("follow_up_", "delivery_followup_")

# Kinds APRÈS-VENTE : ils s'adressent VOLONTAIREMENT à des clients — le
# statut « won » ne doit pas les bloquer (désinscrit/rebond/refus, si).
POST_SALE_DRAFT_KINDS = frozenset({
    "post_sale", "welcome_at_paid", "cross_sell_30d", "nps_90d",
})


def _is_follow_up_kind(kind: str) -> bool:
    return (kind in FOLLOW_UP_DRAFT_KINDS
            or kind.startswith(_FOLLOW_UP_KIND_PREFIXES))


def _is_post_sale_kind(kind: str) -> bool:
    return (kind in POST_SALE_DRAFT_KINDS
            or kind.startswith("delivery_followup_"))

# Libellés humains des statuts bloquants (affichés tels quels dans l'UI).
_NO_CONTACT_LABELS = {
    "unsubscribed": "ce prospect s'est désinscrit — envoi interdit",
    "bounced":      "l'adresse de ce prospect est morte (rebond)",
    "refused":      "ce prospect a refusé — on ne le recontacte pas",
    "won":          "ce prospect est déjà client (gagné)",
    "lost":         "cycle clos avec ce prospect (perdu)",
}


def draft_approval_check(*, status: str, draft_kind: str = "",
                          last_send_ts: str = "",
                          draft_created_ts: str = "") -> dict:
    """Décision PURE (sans réseau) : ce brouillon a-t-il le droit de partir ?

    Args:
        status          : statut actuel du prospect (lu en base juste avant).
        draft_kind      : kind du brouillon (first_contact, follow_up_7d...).
        last_send_ts    : ts ISO du dernier email_sent vers ce prospect
                          ("" si jamais contacté).
        draft_created_ts: ts ISO de création du brouillon ("" si inconnu).

    Renvoie {"ok": bool, "reason": str} — reason en français, montrable
    à l'utilisateur tel quel.
    """
    st = (status or "").lower().strip()
    kind = (draft_kind or "").lower().strip()
    if st in NO_CONTACT_STATUSES:
        # Exception : un mail APRÈS-VENTE s'adresse par définition à un
        # client — « won » ne le bloque pas. Les autres statuts (désinscrit,
        # rebond, refus, perdu) restent bloquants même en après-vente.
        if not (st == "won" and _is_post_sale_kind(kind)):
            return {"ok": False,
                    "reason": _NO_CONTACT_LABELS.get(
                        st, f"statut bloquant : {st}")}
    if not last_send_ts:
        return {"ok": True, "reason": ""}
    if _is_follow_up_kind(kind):
        # Relance : un envoi antérieur est attendu. On ne bloque que si un
        # envoi est parti APRÈS la création de cette relance (quelqu'un est
        # déjà repassé derrière).
        if draft_created_ts and last_send_ts > draft_created_ts:
            return {"ok": False,
                    "reason": ("un mail est déjà parti vers ce prospect "
                               f"après la création de cette relance "
                               f"({last_send_ts[:10]})")}
        return {"ok": True, "reason": ""}
    # Premier contact : tout envoi déjà parti = doublon assuré.
    return {"ok": False,
            "reason": ("ce prospect a déjà été contacté le "
                       f"{last_send_ts[:10]} — valider ce brouillon "
                       "ferait un doublon")}


# =============================================================================
# Variables non remplacees dans un mail
# =============================================================================
def find_unrendered_vars(*texts: str) -> list[str]:
    """Detecte les marqueurs non remplaces dans subject/body. Renvoie la
    liste des fragments {x}/{{x}}/%x% trouves. Vide = mail propre."""
    found: list[str] = []
    for t in texts:
        if not t:
            continue
        for m in _UNRENDERED_VAR_RE.finditer(t):
            found.append(m.group(0))
    return found


def mail_is_safe_to_send(subject: str, body: str) -> dict:
    """Renvoie {"ok": bool, "unrendered": [...]}.
    Ne PAS envoyer si unrendered non vide."""
    bad = find_unrendered_vars(subject or "", body or "")
    return {"ok": not bad, "unrendered": bad}


# =============================================================================
# Warnings doux pour les envois MANUELS
# =============================================================================
# Pourquoi : la prospection automatique (autopilote v2, convoy, drip) bloque
# DUR ces deux cas via should_contact() + has_recent_send(check_clients=True).
# Les envois manuels (composer, programmé, reply_send_now depuis l'UI Réponses)
# eux ne doivent PAS bloquer — Jordan veut juste être prévenu pour ne pas faire
# d'erreur, mais reste libre de forcer.
def check_manual_send_warnings(client, *emails: str) -> list[dict]:
    """Renvoie une liste de warnings pour les destinataires donnés :
    - {"code": "already_contacted", "email": "x@y.fr",
       "message": "...", "last_sent_at": "YYYY-MM-DDTHH:MM:SS"}
    - {"code": "in_clients", "email": "x@y.fr",
       "message": "...", "client_name": "Prénom Nom"}

    Liste vide = rien à signaler.
    Best-effort : si la BDD répond mal, on renvoie [] (on ne bloque jamais
    un envoi pour une erreur de check).
    """
    if client is None:
        return []
    out: list[dict] = []
    sb = client.raw
    # Dédoublonne et nettoie
    clean: list[str] = []
    seen: set[str] = set()
    for e in emails:
        if not e:
            continue
        v = (e or "").strip().lower()
        if not v or "@" not in v or v in seen:
            continue
        seen.add(v)
        clean.append(v)
    if not clean:
        return out

    for email_low in clean:
        # 1) Présent dans clients ? (court-circuit : c'est le warning
        # le plus fort, on saute le check email_history pour cette adresse)
        try:
            r = (sb.table("clients")
                 .select("id, email, first_name, last_name, company_name")
                 .ilike("email", email_low).limit(1).execute())
            row = (r.data or [None])[0]
            if row:
                name = " ".join(filter(None, [
                    (row.get("first_name") or "").strip(),
                    (row.get("last_name") or "").strip(),
                ])).strip()
                if not name:
                    name = (row.get("company_name") or "").strip()
                if not name:
                    name = row.get("email") or email_low
                out.append({
                    "code": "in_clients",
                    "email": email_low,
                    "client_name": name,
                    "message": f"Cette adresse est dans ta base clients ({name}).",
                })
                continue
        except Exception as exc:
            logger.debug("check_manual_send_warnings: clients KO (%s)", exc)

        # 2) A déjà reçu un mail (n'importe quand) ?
        try:
            # Tentative serveur-side via index JSONB sur extra->>to
            q = (sb.table("email_history").select("ts,extra")
                 .eq("kind", "email_sent")
                 .eq("extra->>to", email_low)
                 .order("ts", desc=True).limit(1))
            res = q.execute()
            rows = res.data or []
            last_ts = ""
            if rows:
                last_ts = rows[0].get("ts") or ""
            else:
                # Fallback client-side (ramène les 500 derniers, filtre py)
                q2 = (sb.table("email_history").select("ts,extra")
                      .eq("kind", "email_sent")
                      .order("ts", desc=True).limit(500))
                res2 = q2.execute()
                for r2 in (res2.data or []):
                    extra = r2.get("extra") or {}
                    if isinstance(extra, str):
                        try:
                            import json as _json
                            extra = _json.loads(extra)
                        except Exception:
                            extra = {}
                    tos = extra.get("to") or extra.get("recipients") or []
                    if isinstance(tos, str):
                        tos = [tos]
                    if any((t or "").lower() == email_low for t in tos):
                        last_ts = r2.get("ts") or ""
                        break
            if last_ts:
                pretty = last_ts[:10] if len(last_ts) >= 10 else last_ts
                out.append({
                    "code": "already_contacted",
                    "email": email_low,
                    "last_sent_at": last_ts,
                    "message": f"Cette adresse a déjà été contactée le {pretty}.",
                })
        except Exception as exc:
            logger.debug("check_manual_send_warnings: history KO (%s)", exc)

    return out
