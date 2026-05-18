"""Le Convoi — orchestration : campagnes, drafts, envoi SMTP, planification.

Une "campagne Convoi" = un import de fichier + une liste de prospects extraits
+ un template / brief IA + un mode (auto / validation).

Persistance — choisie automatiquement :
- Si Supabase est configuré + l'utilisateur est loggé → tables Supabase
  (`convoy_campaigns` + `convoy_drafts`). Sync auto entre Jordan et Thomas.
- Sinon (offline ou setup non terminé) → fichiers JSON dans
  `~/.triskell-command/convoy/`.

Le module `_backend()` détermine le mode au moment de chaque appel, donc
si l'utilisateur se connecte en cours de session, les nouveaux appels
basculent sur Supabase sans redémarrage.

Statuts d'un draft :
    "pending"   : message généré, en attente de validation utilisateur
    "approved"  : approuvé mais pas encore envoyé (file d'attente)
    "sent"      : envoyé avec succès (Message-ID stocké)
    "failed"    : échec d'envoi (raison stockée)
    "rejected"  : explicitement rejeté par l'utilisateur

Mode auto : tous les drafts passent direct en "approved" puis "sent" un par un.
Mode validation : les drafts restent "pending", l'utilisateur valide à la main.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .multi_tenant import with_workspace

logger = logging.getLogger(__name__)


CONVOY_DIR = Path.home() / ".triskell-command" / "convoy"
CAMPAIGNS_DIR = CONVOY_DIR / "campaigns"
SEND_LOG = CONVOY_DIR / "send_log.json"


def ensure_dirs() -> None:
    CAMPAIGNS_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Détection du backend (Supabase vs local) — réévaluée à chaque appel
# ---------------------------------------------------------------------------
def _supabase_client():
    """Renvoie le client Supabase si auth, sinon None (pour fallback local)."""
    try:
        from triskell_core.db import get_client, SupabaseNotConfigured
        try:
            client = get_client()
        except SupabaseNotConfigured:
            return None
        if client.is_authenticated:
            return client
        return None
    except ImportError:
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Modèles
# ---------------------------------------------------------------------------
@dataclass
class ConvoyDraft:
    id: str
    prospect: dict[str, str]
    subject: str = ""
    body: str = ""              # version texte (fallback clients mail anciens)
    body_html: str = ""         # version HTML (boutons cliquables, mise en page)
    offer_name: str = ""
    status: str = "pending"           # pending | approved | sent | failed | rejected
    sent_at: str = ""
    error: str = ""
    message_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ConvoyDraft":
        return cls(
            id=d.get("id") or uuid.uuid4().hex,
            prospect=dict(d.get("prospect") or {}),
            subject=d.get("subject", ""),
            body=d.get("body", ""),
            body_html=d.get("body_html", ""),
            offer_name=d.get("offer_name", ""),
            status=d.get("status", "pending"),
            sent_at=d.get("sent_at", ""),
            error=d.get("error", ""),
            message_id=d.get("message_id", ""),
        )


@dataclass
class ConvoyCampaign:
    id: str
    name: str
    created_at: str
    source_file: str
    mode: str                          # "auto" | "validation"
    user_brief: str
    catalog: list[dict[str, str]]
    drafts: list[ConvoyDraft] = field(default_factory=list)
    daily_cap: int = 40
    delay_seconds: int = 60            # délai mini entre 2 envois
    schedule_at: str = ""              # ISO datetime pour démarrer plus tard, "" = maintenant
    sender_account_id: str = "primary" # id du compte mail expéditeur
                                       # ("primary" = compte principal,
                                       # sinon id d'un compte secondaire)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["drafts"] = [x.to_dict() for x in self.drafts]
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ConvoyCampaign":
        return cls(
            id=d.get("id") or uuid.uuid4().hex,
            name=d.get("name", ""),
            created_at=d.get("created_at", _now_iso()),
            source_file=d.get("source_file", ""),
            mode=d.get("mode", "validation"),
            user_brief=d.get("user_brief", ""),
            catalog=list(d.get("catalog") or []),
            drafts=[ConvoyDraft.from_dict(x) for x in (d.get("drafts") or [])],
            daily_cap=int(d.get("daily_cap", 40)),
            delay_seconds=int(d.get("delay_seconds", 60)),
            schedule_at=d.get("schedule_at", ""),
            sender_account_id=(d.get("sender_account_id") or "primary"),
        )

    @property
    def filepath(self) -> Path:
        ensure_dirs()
        slug = re.sub(r"[^a-z0-9_-]+", "-", (self.name or self.id).lower())[:40] or self.id
        ts = self.created_at.replace(":", "").replace("-", "")[:15] or _now_compact()
        return CAMPAIGNS_DIR / f"{ts}_{slug}.json"

    def save(self) -> Path | None:
        """Persiste la campagne (Supabase ou local). Renvoie le path local
        si on est en local, None en mode Supabase."""
        client = _supabase_client()
        if client is not None:
            _save_to_supabase(self, client)
            return None
        return self._save_local()

    def _save_local(self) -> Path:
        path = self.filepath
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(path)
        return path

    # Stats utiles pour le tableau de bord
    def counts(self) -> dict[str, int]:
        c = {"total": len(self.drafts),
             "pending": 0, "approved": 0, "sent": 0,
             "failed": 0, "rejected": 0}
        for d in self.drafts:
            if d.status in c:
                c[d.status] += 1
        return c


# ---------------------------------------------------------------------------
# I/O des campagnes — dispatch automatique Supabase / local
# ---------------------------------------------------------------------------
def list_campaigns() -> list[ConvoyCampaign]:
    client = _supabase_client()
    if client is not None:
        return _list_from_supabase(client)
    return _list_local()


def _list_local() -> list[ConvoyCampaign]:
    ensure_dirs()
    out: list[ConvoyCampaign] = []
    for p in sorted(CAMPAIGNS_DIR.glob("*.json"), reverse=True):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            out.append(ConvoyCampaign.from_dict(data))
        except Exception as exc:
            logger.warning("Campagne illisible %s : %s", p, exc)
    return out


def _list_from_supabase(client) -> list[ConvoyCampaign]:
    """Charge campagnes + drafts en 2 requêtes."""
    try:
        c_res = (client.raw.table("convoy_campaigns").select("*")
                 .order("created_at", desc=True).execute())
        camp_rows = c_res.data or []
        if not camp_rows:
            return []
        ids = [r["id"] for r in camp_rows]
        d_res = (client.raw.table("convoy_drafts").select("*")
                 .in_("campaign_id", ids).execute())
        drafts_rows = d_res.data or []
        drafts_by_camp: dict[str, list[ConvoyDraft]] = {}
        for dr in drafts_rows:
            cid = dr.get("campaign_id")
            if not cid:
                continue
            drafts_by_camp.setdefault(cid, []).append(_row_to_draft(dr))
        out: list[ConvoyCampaign] = []
        for r in camp_rows:
            camp = _row_to_campaign(r)
            camp.drafts = drafts_by_camp.get(r["id"], [])
            out.append(camp)
        return out
    except Exception as exc:
        logger.warning("Supabase list_campaigns a échoué : %s — fallback local",
                       exc)
        return _list_local()


def load_campaign(campaign_id: str) -> ConvoyCampaign | None:
    client = _supabase_client()
    if client is not None:
        try:
            c_res = (client.raw.table("convoy_campaigns").select("*")
                     .eq("id", campaign_id).limit(1).execute())
            data = c_res.data or []
            if not data:
                return None
            camp = _row_to_campaign(data[0])
            d_res = (client.raw.table("convoy_drafts").select("*")
                     .eq("campaign_id", campaign_id).execute())
            camp.drafts = [_row_to_draft(d) for d in (d_res.data or [])]
            return camp
        except Exception as exc:
            logger.warning("Supabase load_campaign : %s — fallback local", exc)
    for c in _list_local():
        if c.id == campaign_id:
            return c
    return None


# ---------------------------------------------------------------------------
# Conversions ConvoyCampaign / ConvoyDraft ↔ row Supabase
# ---------------------------------------------------------------------------
def _campaign_to_row(camp: ConvoyCampaign) -> dict[str, Any]:
    return {
        "id": camp.id,
        "name": camp.name,
        "source_file": camp.source_file,
        "mode": camp.mode,
        "user_brief": camp.user_brief,
        "catalog": camp.catalog,
        "daily_cap": camp.daily_cap,
        "delay_seconds": camp.delay_seconds,
        "schedule_at": camp.schedule_at or None,
        "sender_account_id": camp.sender_account_id or "primary",
    }


# Champs récemment ajoutés à la table convoy_campaigns. Si la colonne
# n'existe pas encore sur Supabase (migration pas encore jouée), on
# retire ces champs du payload et on retente — la campagne reste
# synchronisée, juste sans la nouvelle info, jusqu'à ce que la
# migration soit jouée.
_OPTIONAL_CAMPAIGN_COLUMNS = ("sender_account_id",)


def _row_to_campaign(row: dict[str, Any]) -> ConvoyCampaign:
    return ConvoyCampaign(
        id=row["id"],
        name=row.get("name", ""),
        created_at=str(row.get("created_at", "")),
        source_file=row.get("source_file", "") or "",
        mode=row.get("mode", "validation"),
        user_brief=row.get("user_brief", "") or "",
        catalog=list(row.get("catalog") or []),
        drafts=[],
        daily_cap=int(row.get("daily_cap") or 40),
        delay_seconds=int(row.get("delay_seconds") or 60),
        schedule_at=str(row.get("schedule_at") or ""),
        sender_account_id=(row.get("sender_account_id") or "primary"),
    )


def _draft_to_row(d: ConvoyDraft, campaign_id: str) -> dict[str, Any]:
    return {
        "id": d.id,
        "campaign_id": campaign_id,
        "prospect": d.prospect,
        "subject": d.subject,
        "body": d.body,
        "offer_name": d.offer_name,
        "status": d.status,
        "sent_at": d.sent_at or None,
        "error": d.error,
        "message_id": d.message_id,
    }


def _row_to_draft(row: dict[str, Any]) -> ConvoyDraft:
    return ConvoyDraft(
        id=row["id"],
        prospect=dict(row.get("prospect") or {}),
        subject=row.get("subject", "") or "",
        body=row.get("body", "") or "",
        offer_name=row.get("offer_name", "") or "",
        status=row.get("status", "pending"),
        sent_at=str(row.get("sent_at") or ""),
        error=row.get("error", "") or "",
        message_id=row.get("message_id", "") or "",
    )


def _save_to_supabase(camp: ConvoyCampaign, client) -> None:
    """Upsert la campagne + tous ses drafts en bulk."""
    try:
        camp_row = _campaign_to_row(camp)
        camp_row["created_by"] = client.user_id
        try:
            client.raw.table("convoy_campaigns").upsert(
                with_workspace(client, camp_row)
            ).execute()
        except Exception as exc:
            # Si une colonne ajoutée récemment n'existe pas encore sur
            # Supabase (migration pas jouée), on retire ces champs et
            # on retente — la campagne reste synchronisée.
            msg = str(exc).lower()
            stripped = []
            for col in _OPTIONAL_CAMPAIGN_COLUMNS:
                if col in msg and "column" in msg and col in camp_row:
                    camp_row.pop(col, None)
                    stripped.append(col)
            if not stripped:
                raise
            logger.warning(
                "Colonnes Supabase manquantes %s — upsert sans ces champs. "
                "Joue la migration SQL pour activer la fonctionnalité.",
                stripped,
            )
            client.raw.table("convoy_campaigns").upsert(
                with_workspace(client, camp_row)
            ).execute()
        if camp.drafts:
            drafts_rows = [_draft_to_row(d, camp.id) for d in camp.drafts]
            client.raw.table("convoy_drafts").upsert(
                with_workspace(client, drafts_rows)
            ).execute()
    except Exception as exc:
        logger.warning("Supabase save_campaign : %s — fallback local", exc)
        camp._save_local()


# ---------------------------------------------------------------------------
# Quota quotidien (séparé du Dénicheur — propre au Convoi)
# ---------------------------------------------------------------------------
def _load_today_count() -> int:
    today = datetime.now().date().isoformat()
    if not SEND_LOG.exists():
        return 0
    try:
        data = json.loads(SEND_LOG.read_text(encoding="utf-8"))
    except Exception:
        return 0
    return int(data.get("count", 0)) if data.get("date") == today else 0


def _bump_today_count(by: int = 1) -> int:
    ensure_dirs()
    today = datetime.now().date().isoformat()
    data: dict[str, Any] = {}
    if SEND_LOG.exists():
        try:
            data = json.loads(SEND_LOG.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    if data.get("date") != today:
        data = {"date": today, "count": 0}
    data["count"] = int(data.get("count", 0)) + by
    SEND_LOG.write_text(json.dumps(data), encoding="utf-8")
    return data["count"]


# ---------------------------------------------------------------------------
# Envoi d'un draft (un seul mail) — réutilise smtp_sender de Triskell Core
# ---------------------------------------------------------------------------
def send_draft(
    draft: ConvoyDraft,
    *,
    smtp_cfg: dict[str, Any],
) -> ConvoyDraft:
    """Envoie un draft via SMTP. Met à jour son statut (sent / failed).

    Effet de bord : à chaque envoi réussi, le destinataire est upsert
    automatiquement dans la fiche client master (`clients_master_repo.
    ensure_client`). C'est ce qui garantit que tout contact démarché
    devient un client trackable, sans saisie manuelle.
    """
    from triskell_core.prospect.outreach.smtp_sender import send_email
    from . import prospect_status as PS
    to = (draft.prospect or {}).get("email", "")
    if not to:
        draft.status = "failed"
        draft.error = "email manquant"
        return draft
    # Fix 5 : refus si variables non remplacees (genre "Bonjour {name}")
    safety = PS.mail_is_safe_to_send(draft.subject or "", draft.body or "")
    if not safety.get("ok"):
        draft.status = "needs_review"
        draft.error = (
            "variables non remplies dans le mail : "
            + ", ".join(safety.get("unrendered") or [])
        )
        logger.warning("convoy send_draft blocked — %s (%s)", draft.error, to)
        return draft
    # Fix 4 : anti-doublon — pas 2 envois automatiques au meme destinataire
    # dans les 48h, quel que soit le runner d'origine.
    cli = _supabase_client()
    if cli is not None:
        try:
            # hours=None → lit le cooldown depuis shared_settings (72h par défaut)
            recent = PS.has_recent_send(cli, email=to, hours=None)
            if recent.get("recent"):
                draft.status = "skipped_duplicate"
                draft.error = (
                    f"deja mail dans les 48h vers {to} "
                    f"(last: {recent.get('last_ts')})"
                )
                return draft
        except Exception:
            pass
    try:
        msg_id = send_email(
            smtp_cfg,
            to=to,
            subject=draft.subject or "(sans objet)",
            body=draft.body or "",
            body_html=draft.body_html or "",
        )
        draft.status = "sent"
        draft.sent_at = _now_iso()
        draft.message_id = msg_id
        draft.error = ""
        _bump_today_count(1)
        # Best-effort : crée/met à jour la fiche client master.
        # On NE bloque PAS l'envoi si ça échoue (Supabase down, etc.).
        _upsert_client_from_draft(draft)
        # Log dans email_history pour que les envois Convoi remontent dans
        # le compteur "Envoyés aujourd'hui" du cockpit (avant ce fix, les
        # mails partaient mais étaient invisibles côté KPI).
        if cli is not None:
            try:
                row = {
                    "kind": "email_sent",
                    "ts": draft.sent_at,
                    "subject": (draft.subject or "")[:200],
                    "body": (draft.body or "")[:5000],
                    "message_id": msg_id,
                    "extra": {
                        "convoy_campaign_id": getattr(draft, "campaign_id", "")
                                              or "",
                        "convoy_draft_id": draft.id,
                        "offer_name": draft.offer_name,
                        "to": to,
                    },
                    "created_by": cli.user_id,
                }
                cli.raw.table("email_history").insert(
                    with_workspace(cli, row)
                ).execute()
            except Exception as exc:
                logger.warning("convoy log email_sent KO: %s", exc)
            # Cherche le prospect par son email pour passer son statut
            # à "contacted" → permet à Jordan de suivre dans le fichier
            # Prospects qui a déjà été contacté ou pas.
            try:
                pid_rows = (cli.raw.table("prospects").select("id")
                            .contains("emails", [to])
                            .limit(1).execute().data or [])
                if pid_rows:
                    from .obelisk import repo as ob_repo
                    ob_repo.mark_contacted(pid_rows[0]["id"])
            except Exception as exc:
                logger.debug("convoy mark_contacted KO: %s", exc)
    except Exception as exc:
        draft.status = "failed"
        draft.error = str(exc)
    return draft


def _upsert_client_from_draft(draft: ConvoyDraft) -> None:
    """Crée ou met à jour la fiche client master à partir du prospect Convoi.

    Mappe les champs du prospect Convoi vers la signature de
    `clients_master_repo.ensure_client`. Marque la source comme "convoy".

    Idempotent : si le client existe déjà (même email), seuls les champs
    vides côté master seront remplis — aucune donnée existante n'est écrasée.
    """
    try:
        from . import clients_master_repo
    except ImportError as exc:
        logger.debug("clients_master_repo indisponible : %s", exc)
        return
    p = draft.prospect or {}
    email = (p.get("email") or "").strip()
    if not email:
        return
    try:
        clients_master_repo.ensure_client(
            email,
            first_name=p.get("prenom", "") or "",
            last_name=p.get("nom", "") or "",
            phone=p.get("telephone", "") or "",
            company_name=p.get("raison_sociale", "") or "",
            source="convoy",
        )
    except Exception as exc:
        # Best-effort : on logge, on ne propage pas.
        logger.warning(
            "ensure_client depuis convoy a échoué pour %s : %s", email, exc,
        )


# ---------------------------------------------------------------------------
# Envoi d'une campagne (boucle, respecte cap + délai)
# ---------------------------------------------------------------------------
def run_campaign_send(
    campaign: ConvoyCampaign,
    *,
    smtp_cfg: dict[str, Any],
    progress: Callable[[str], None] | None = None,
    stop_flag: Callable[[], bool] | None = None,
) -> dict[str, int]:
    """Envoie tous les drafts approuvés (en mode auto, on aura déjà passé
    tous les pending → approved en amont).

    Renvoie les counts finaux.
    """
    log = progress or (lambda m: None)
    sent = 0
    failed = 0
    cap_today = max(0, int(campaign.daily_cap) - _load_today_count())
    if cap_today <= 0:
        log("⚠ Cap quotidien atteint avant de commencer — rien envoyé.")
        return campaign.counts()

    for i, draft in enumerate(campaign.drafts):
        if stop_flag and stop_flag():
            log("⏹ Arrêt demandé.")
            break
        if draft.status != "approved":
            continue
        if sent >= cap_today:
            log(f"⚠ Cap quotidien atteint ({campaign.daily_cap}) — pause.")
            break

        log(f"→ [{i + 1}/{len(campaign.drafts)}] envoi à "
            f"{draft.prospect.get('email', '?')}…")
        send_draft(draft, smtp_cfg=smtp_cfg)
        if draft.status == "sent":
            sent += 1
            log(f"  ✓ envoyé ({draft.subject})")
        else:
            failed += 1
            log(f"  ✗ {draft.error}")
        campaign.save()

        # Délai aléatoire entre 2 envois (anti-spam-throttle)
        if sent + failed < len(campaign.drafts):
            wait = max(5, int(campaign.delay_seconds))
            for _ in range(wait):
                if stop_flag and stop_flag():
                    break
                time.sleep(1)

    counts = campaign.counts()
    log(f"=== Fin : {counts['sent']} envoyés, {counts['failed']} échoués, "
        f"{counts['pending']} en attente, {counts['rejected']} rejetés.")
    return counts


# ---------------------------------------------------------------------------
# Helpers d'API publique pour la vue
# ---------------------------------------------------------------------------
def approve_all_pending(campaign: ConvoyCampaign) -> int:
    """Mode auto : passe tous les pending → approved. Renvoie le nb."""
    n = 0
    for d in campaign.drafts:
        if d.status == "pending":
            d.status = "approved"
            n += 1
    campaign.save()
    return n


def approve_draft(campaign: ConvoyCampaign, draft_id: str) -> bool:
    for d in campaign.drafts:
        if d.id == draft_id:
            d.status = "approved"
            campaign.save()
            return True
    return False


def reject_draft(campaign: ConvoyCampaign, draft_id: str) -> bool:
    for d in campaign.drafts:
        if d.id == draft_id:
            d.status = "rejected"
            campaign.save()
            return True
    return False


def update_draft(
    campaign: ConvoyCampaign,
    draft_id: str,
    *,
    subject: str | None = None,
    body: str | None = None,
) -> bool:
    for d in campaign.drafts:
        if d.id == draft_id:
            if subject is not None:
                d.subject = subject
            if body is not None:
                d.body = body
            campaign.save()
            return True
    return False


def delete_campaign(campaign: ConvoyCampaign) -> bool:
    """Supprime la campagne (Supabase ou disque). Renvoie True si OK."""
    client = _supabase_client()
    if client is not None:
        try:
            client.raw.table("convoy_campaigns").delete().eq(
                "id", campaign.id).execute()
            # Les drafts partent en cascade (FK on delete cascade)
            return True
        except Exception as exc:
            logger.warning("Supabase delete_campaign : %s — fallback local",
                           exc)
    try:
        p = campaign.filepath
        if p.exists():
            p.unlink()
            return True
    except Exception as exc:
        logger.warning("Suppression campagne %s a échoué : %s", campaign.id, exc)
    return False


# ---------------------------------------------------------------------------
# Démarrage en thread (utilisé par la vue)
# ---------------------------------------------------------------------------
def start_send_thread(
    campaign: ConvoyCampaign,
    *,
    smtp_cfg: dict[str, Any],
    progress: Callable[[str], None] | None = None,
) -> tuple[threading.Thread, Callable[[], None]]:
    """Lance run_campaign_send dans un thread, renvoie (thread, stop_fn).

    L'appelant doit afficher le `progress` callback au fil de l'eau.
    """
    stop_event = threading.Event()

    def worker():
        run_campaign_send(
            campaign,
            smtp_cfg=smtp_cfg,
            progress=progress,
            stop_flag=stop_event.is_set,
        )

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    return t, stop_event.set


# ---------------------------------------------------------------------------
# Helpers temps
# ---------------------------------------------------------------------------
def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _now_compact() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")
