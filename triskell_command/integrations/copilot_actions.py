"""Étape 4 du copilote omniprésent — les pouvoirs élargis, sous contrôle.

Ce module est LA source de vérité des actions de l'assistant (écrit + vocal) :

  - un REGISTRE central : chaque action déclare sa famille, son niveau de
    risque (lecture / réversible / sensible), si elle envoie un mail, son
    libellé français et son exécuteur ;
  - un CURSEUR DE CONFIANCE par famille et par utilisateur
    (« il fait seul » / « il me demande d'abord » / « jamais »), avec un
    PLAFOND non négociable côté serveur : une action qui envoie un mail ne
    peut JAMAIS être en « il fait seul », quelles que soient les prefs ;
  - des PROPOSITIONS persistées : quand le curseur dit « demande d'abord »,
    l'action n'est PAS exécutée — elle est rangée côté serveur et une carte
    Confirmer/Annuler apparaît dans le fil. La confirmation exécute LA
    version stockée (le navigateur n'envoie qu'un identifiant) ;
  - un JOURNAL des actes : tout ce que l'assistant exécute (ou que Jordan
    confirme/annule) est tracé et consultable dans le volet.

Comme le reste du copilote : aucune exception ne remonte à l'appelant,
tout sort en {ok, summary, ...} avec des messages en français.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Familles, niveaux de confiance, défauts
# ---------------------------------------------------------------------------
FAMILIES = ("prospection", "notes", "mails")
FAMILY_LABELS = {
    "prospection": "Prospection & machines",
    "notes": "Notes & fiches",
    "mails": "Envois de mails",
}
TRUST_LEVELS = ("solo", "ask", "never")
TRUST_LABELS = {
    "solo": "il fait seul",
    "ask": "il me demande d'abord",
    "never": "jamais",
}
# Réglage « équilibré » validé par Jordan le 11/06/2026 : tout ce qui est
# rattrapable se fait seul, tout ce qui touche aux envois demande d'abord.
DEFAULT_TRUST = {"prospection": "solo", "notes": "solo", "mails": "ask"}

PROPS_SETTING_PREFIX = "copilot_props_"      # + user_id
JOURNAL_SETTING_PREFIX = "copilot_journal_"  # + user_id
_LOCAL_PROPS_FILE = Path.home() / ".triskell-command" / "copilot_props.json"
_LOCAL_JOURNAL_FILE = Path.home() / ".triskell-command" / "copilot_journal.json"

PROPOSAL_TTL_HOURS = 24   # une proposition non confirmée expire
MAX_PROPOSALS = 30        # propositions conservées (toutes confondues)
MAX_JOURNAL = 200         # entrées du journal conservées
MAX_PREVIEW_BODY = 6000   # corps de mail affiché dans la carte

_PROPS_LOCK = threading.Lock()
_JOURNAL_LOCK = threading.Lock()


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _safe_user(user_id: str) -> str:
    safe = "".join(c for c in (user_id or "jordan") if c.isalnum() or c in "-_")
    return safe or "jordan"


def _api():
    try:
        from ..web.api import get_api_instance
        return get_api_instance()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Le curseur de confiance (stocké dans les prefs du copilote)
# ---------------------------------------------------------------------------
def clean_trust(raw: Any) -> dict:
    """Normalise un dict de confiance : familles connues, niveaux connus,
    plafond mails (jamais « solo » même si les données stockées le disent)."""
    out = dict(DEFAULT_TRUST)
    if isinstance(raw, dict):
        for fam in FAMILIES:
            lvl = str(raw.get(fam) or "").strip().lower()
            if lvl in TRUST_LEVELS:
                out[fam] = lvl
    if out["mails"] == "solo":   # ceinture : le plafond tient même si la
        out["mails"] = "ask"     # base a été modifiée à la main
    return out


def get_trust(user_id: str) -> dict:
    """Le curseur famille → niveau pour cet utilisateur (toujours valide)."""
    try:
        from . import copilot
        return clean_trust((copilot.get_prefs(user_id) or {}).get("trust"))
    except Exception:
        return dict(DEFAULT_TRUST)


def effective_trust(user_id: str, do: str) -> str:
    """Le niveau effectif pour UNE action : curseur de sa famille + plafond
    serveur (sends_mail → au mieux « ask »). Lecture/navigation → solo."""
    spec = ACTIONS.get(do)
    if not spec:
        return "never"
    fam = spec.get("family")
    if not fam or spec.get("risk") == "lecture":
        return "solo"
    lvl = get_trust(user_id).get(fam, "ask")
    if spec.get("sends_mail") and lvl == "solo":
        lvl = "ask"
    return lvl


# ---------------------------------------------------------------------------
# Stockage générique (réutilise la tuyauterie du copilote : Supabase
# shared_settings, secours fichier local)
# ---------------------------------------------------------------------------
def _doc_read(prefix: str, local_file: Path, user_id: str) -> dict:
    try:
        from . import copilot
        raw = copilot._doc_read(prefix + _safe_user(user_id), local_file,
                                _safe_user(user_id))
        return raw if isinstance(raw, dict) else {}
    except Exception as exc:
        logger.debug("copilot_actions read %s: %s", prefix, exc)
        return {}


def _doc_write(prefix: str, local_file: Path, user_id: str,
               payload: dict) -> None:
    try:
        from . import copilot
        copilot._doc_write(prefix + _safe_user(user_id), local_file,
                           _safe_user(user_id), payload)
    except Exception as exc:
        logger.debug("copilot_actions write %s: %s", prefix, exc)


# ---------------------------------------------------------------------------
# Le journal des actes
# ---------------------------------------------------------------------------
def add_journal_entry(user_id: str, *, do: str, label: str, origin: str,
                      ok: Optional[bool], summary: str) -> None:
    """Trace un acte (exécuté, confirmé, échoué, annulé). Jamais d'exception.
    origin : direct (le copilote a fait seul sur demande écrite), vocal
    (idem à la voix), confirme (Jordan a cliqué Confirmer), annule
    (Jordan a cliqué Annuler)."""
    try:
        spec = ACTIONS.get(do) or {}
        entry = {
            "at": _now_iso(),
            "do": str(do or "")[:40],
            "label": str(label or spec.get("label") or do)[:160],
            "family": spec.get("family") or "",
            "risk": spec.get("risk") or "",
            "origin": str(origin or "")[:20],
            "ok": ok,
            "summary": str(summary or "")[:400],
        }
        with _JOURNAL_LOCK:
            doc = _doc_read(JOURNAL_SETTING_PREFIX, _LOCAL_JOURNAL_FILE,
                            user_id)
            items = doc.get("items")
            items = list(items) if isinstance(items, list) else []
            items.append(entry)
            _doc_write(JOURNAL_SETTING_PREFIX, _LOCAL_JOURNAL_FILE, user_id,
                       {"items": items[-MAX_JOURNAL:]})
    except Exception as exc:
        logger.debug("copilot journal: %s", exc)


def journal_for_ui(user_id: str, limit: int = 60) -> dict:
    """Le journal, du plus récent au plus ancien, prêt pour l'onglet 📜."""
    try:
        limit = max(1, min(int(limit or 60), MAX_JOURNAL))
    except Exception:
        limit = 60
    doc = _doc_read(JOURNAL_SETTING_PREFIX, _LOCAL_JOURNAL_FILE, user_id)
    items = doc.get("items")
    items = list(items) if isinstance(items, list) else []
    out = []
    for e in items[-limit:][::-1]:
        if isinstance(e, dict):
            out.append({
                "at": str(e.get("at") or ""),
                "label": str(e.get("label") or ""),
                "family": str(e.get("family") or ""),
                "risk": str(e.get("risk") or ""),
                "origin": str(e.get("origin") or ""),
                "ok": e.get("ok"),
                "summary": str(e.get("summary") or ""),
            })
    return {"ok": True, "entries": out, "total": len(items)}


# ---------------------------------------------------------------------------
# Les propositions (actions en attente de confirmation)
# ---------------------------------------------------------------------------
def _load_props(user_id: str) -> list[dict]:
    doc = _doc_read(PROPS_SETTING_PREFIX, _LOCAL_PROPS_FILE, user_id)
    items = doc.get("items")
    return list(items) if isinstance(items, list) else []


def _save_props(user_id: str, items: list[dict]) -> None:
    _doc_write(PROPS_SETTING_PREFIX, _LOCAL_PROPS_FILE, user_id,
               {"items": items[-MAX_PROPOSALS:]})


def _expire_in_place(items: list[dict]) -> bool:
    """Marque expirées les pending trop vieilles. True si modifié."""
    changed = False
    now = datetime.now()
    for p in items:
        if not isinstance(p, dict) or p.get("status") != "pending":
            continue
        try:
            exp = datetime.fromisoformat(str(p.get("expires_at") or ""))
        except Exception:
            exp = now - timedelta(seconds=1)
        if exp < now:
            p["status"] = "expired"
            changed = True
    return changed


def create_proposal(user_id: str, action: dict, *, title: str,
                    preview: Optional[dict]) -> dict:
    """Range une proposition côté serveur et la renvoie (status pending)."""
    prop = {
        "id": uuid.uuid4().hex[:10],
        "do": str((action or {}).get("do") or ""),
        "action": action or {},
        "title": str(title or "")[:240],
        "preview": preview if isinstance(preview, dict) else None,
        "status": "pending",
        "created_at": _now_iso(),
        "expires_at": (datetime.now()
                       + timedelta(hours=PROPOSAL_TTL_HOURS)
                       ).isoformat(timespec="seconds"),
        "result_summary": "",
    }
    with _PROPS_LOCK:
        items = _load_props(user_id)
        _expire_in_place(items)
        items.append(prop)
        _save_props(user_id, items)
    return prop


def list_proposals(user_id: str) -> dict:
    """Les propositions (récentes), avec expiration appliquée — pour que le
    volet peigne l'état réel des cartes. Renvoie {pid: {...}}."""
    with _PROPS_LOCK:
        items = _load_props(user_id)
        if _expire_in_place(items):
            _save_props(user_id, items)
    out = {}
    for p in items:
        if isinstance(p, dict) and p.get("id"):
            out[p["id"]] = {
                "id": p["id"],
                "do": p.get("do") or "",
                "title": p.get("title") or "",
                "preview": p.get("preview"),
                "status": p.get("status") or "pending",
                "created_at": p.get("created_at") or "",
                "result_summary": p.get("result_summary") or "",
            }
    return out


def _set_prop_status(user_id: str, pid: str, status: str,
                     result_summary: str = "") -> Optional[dict]:
    """Change le statut d'une proposition (sous verrou). Renvoie la
    proposition à jour, ou None si introuvable."""
    with _PROPS_LOCK:
        items = _load_props(user_id)
        _expire_in_place(items)
        target = None
        for p in items:
            if isinstance(p, dict) and p.get("id") == pid:
                target = p
                break
        if target is None:
            return None
        target["status"] = status
        if result_summary:
            target["result_summary"] = str(result_summary)[:400]
        _save_props(user_id, items)
        return dict(target)


def confirm_proposal(user_id: str, pid: str) -> dict:
    """Jordan a cliqué Confirmer : exécute LA proposition stockée serveur.
    Re-vérifie tout (statut, expiration, curseur) au moment du clic."""
    pid = str(pid or "").strip()
    if not pid:
        return {"ok": False, "summary": "Proposition inconnue."}

    with _PROPS_LOCK:
        items = _load_props(user_id)
        if _expire_in_place(items):
            _save_props(user_id, items)
        prop = next((p for p in items
                     if isinstance(p, dict) and p.get("id") == pid), None)

    if prop is None:
        return {"ok": False, "summary": "Cette proposition n'existe plus."}
    status = prop.get("status") or "pending"
    if status == "expired":
        return {"ok": False, "status": "expired",
                "summary": "Cette proposition a expiré — redemande-moi et "
                           "je t'en prépare une fraîche."}
    if status != "pending":
        return {"ok": False, "status": status,
                "summary": "Cette proposition a déjà été traitée."}

    action = prop.get("action") or {}
    do = str(action.get("do") or "")
    spec = ACTIONS.get(do)
    if spec is None:
        _set_prop_status(user_id, pid, "failed", "action inconnue")
        return {"ok": False, "summary": "(action inconnue, rien fait)"}

    # Le curseur a pu changer entre la proposition et le clic.
    if effective_trust(user_id, do) == "never":
        _set_prop_status(user_id, pid, "dismissed",
                         "bloquée par tes réglages")
        return {"ok": False,
                "summary": "Tes réglages interdisent maintenant cette "
                           "action — rien fait. (Curseur dans l'écran 📌.)"}

    result = _run_action(spec, action)
    ok = bool(result.get("ok"))
    summary = (result.get("summary") or "").strip()
    _set_prop_status(user_id, pid, "done" if ok else "failed", summary)
    add_journal_entry(user_id, do=do, label=prop.get("title") or "",
                      origin="confirme", ok=ok, summary=summary)
    if ok:
        try:
            from . import copilot_habits
            copilot_habits.record_action(user_id, action)
        except Exception as exc:
            logger.debug("copilot habit record (confirm): %s", exc)
    out = {"ok": ok, "status": "done" if ok else "failed",
           "summary": summary}
    if result.get("navigate"):
        out["navigate"] = result["navigate"]
    return out


def dismiss_proposal(user_id: str, pid: str) -> dict:
    """Jordan a cliqué Annuler : la proposition est close, rien n'est fait."""
    pid = str(pid or "").strip()
    prop = _set_prop_status(user_id, pid, "dismissed") if pid else None
    if prop is None:
        return {"ok": False, "summary": "Cette proposition n'existe plus."}
    add_journal_entry(user_id, do=prop.get("do") or "",
                      label=prop.get("title") or "", origin="annule",
                      ok=None, summary="Annulée par toi — rien n'est parti.")
    return {"ok": True, "status": "dismissed"}


# ---------------------------------------------------------------------------
# Petites mains : lectures Supabase pour les aperçus et la fiche prospect
# ---------------------------------------------------------------------------
def _supabase():
    try:
        from . import claude_advisor
        return claude_advisor._client()
    except Exception:
        return None


def _excerpt(text: Any, cap: int) -> str:
    s = " ".join(str(text or "").split())
    return s[:cap] + ("…" if len(s) > cap else "")


def _load_draft_preview(draft_id: str, source: str) -> Optional[dict]:
    """L'aperçu d'un brouillon (destinataire, objet, corps) pour la carte.
    None si la lecture échoue : la proposition reste possible, juste
    moins détaillée."""
    client = _supabase()
    if client is None or not draft_id:
        return None
    try:
        sb = client.raw
        if source == "convoy":
            res = (sb.table("convoy_drafts")
                   .select("id, subject, body, prospect, status")
                   .eq("id", draft_id).limit(1).execute())
            d = (res.data or [None])[0]
            if not d:
                return None
            pr = d.get("prospect") or {}
            if isinstance(pr, str):
                try:
                    pr = json.loads(pr)
                except Exception:
                    pr = {}
            return {
                "to": (pr.get("email") or "").strip(),
                "to_name": (pr.get("name") or "").strip(),
                "subject": d.get("subject") or "",
                "body": str(d.get("body") or "")[:MAX_PREVIEW_BODY],
                "status": d.get("status") or "",
            }
        res = (sb.table("prospect_drafts")
               .select("id, subject, body, status, "
                       "prospects:prospect_id(name, emails)")
               .eq("id", draft_id).limit(1).execute())
        d = (res.data or [None])[0]
        if not d:
            return None
        pr = d.get("prospects") or {}
        return {
            "to": ((pr.get("emails") or [""])[0] or "").strip(),
            "to_name": (pr.get("name") or "").strip(),
            "subject": d.get("subject") or "",
            "body": str(d.get("body") or "")[:MAX_PREVIEW_BODY],
            "status": d.get("status") or "",
        }
    except Exception as exc:
        logger.debug("copilot draft preview: %s", exc)
        return None


def _load_reply_row(reply_id: str) -> Optional[dict]:
    """La ligne email_history d'une réponse reçue (avec extra décodé)."""
    client = _supabase()
    if client is None or not reply_id:
        return None
    try:
        sb = client.raw
        res = (sb.table("email_history").select("id, subject, extra")
               .eq("id", reply_id).limit(1).execute())
        row = (res.data or [None])[0]
        if not row:
            return None
        extra = row.get("extra") or {}
        if isinstance(extra, str):
            try:
                extra = json.loads(extra)
            except Exception:
                extra = {}
        row["extra"] = extra
        return row
    except Exception as exc:
        logger.debug("copilot reply row: %s", exc)
        return None


_STATUS_FR = {
    "new": "nouveau", "contacted": "contacté", "replied": "a répondu",
    "interested": "intéressé", "not_now": "pas maintenant", "no": "refus",
    "won": "client", "unsubscribed": "désinscrit", "bounced": "adresse morte",
}


def _find_prospects(query: str) -> list[dict]:
    """Cherche des prospects par email exact, sinon par nom (contient)."""
    client = _supabase()
    if client is None or not query:
        return []
    q = query.strip()
    try:
        sb = client.raw
        if "@" in q:
            res = (sb.table("prospects")
                   .select("id, name, legal_name, emails, status, tags, "
                           "notes, city, industry, last_contact_at")
                   .contains("emails", [q.lower()]).limit(3).execute())
            return res.data or []
        res = (sb.table("prospects")
               .select("id, name, legal_name, emails, status, tags, notes, "
                       "city, industry, last_contact_at")
               .ilike("name", f"%{q}%").limit(5).execute())
        return res.data or []
    except Exception as exc:
        logger.debug("copilot find prospect: %s", exc)
        return []


def _format_prospect_card(p: dict) -> str:
    """La fiche d'un prospect en texte lisible (markdown léger du volet)."""
    name = p.get("name") or p.get("legal_name") or "(sans nom)"
    emails = [e for e in (p.get("emails") or []) if e]
    status = _STATUS_FR.get(str(p.get("status") or ""),
                            str(p.get("status") or "?"))
    lines = [f"**{name}** — statut : **{status}**"]
    if emails:
        lines.append("Mail : " + ", ".join(emails[:3]))
    extras = []
    if p.get("city"):
        extras.append(str(p["city"]))
    if p.get("industry"):
        extras.append(str(p["industry"]))
    if extras:
        lines.append(" · ".join(extras))
    tags = p.get("tags") or []
    if isinstance(tags, list) and tags:
        lines.append("Étiquettes : " + ", ".join(str(t) for t in tags[:8]))
    if p.get("last_contact_at"):
        lines.append("Dernier contact : "
                     + str(p["last_contact_at"])[:10])
    notes = str(p.get("notes") or "").strip()
    if notes:
        tail = notes.splitlines()[-3:]
        lines.append("Notes :\n" + "\n".join("- " + _excerpt(n, 140)
                                             for n in tail if n.strip()))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Les exécuteurs — chacun renvoie {ok, summary, navigate?}
# ---------------------------------------------------------------------------
def _need_api():
    api = _api()
    if api is None:
        return None, {"ok": False,
                      "summary": "Le serveur démarre encore — redemande "
                                 "dans une minute."}
    return api, None


def _run_navigate(action: dict) -> dict:
    from . import claude_advisor
    view = (action.get("view") or "").strip()
    if view in claude_advisor._ALLOWED_NAV_VIEWS:
        return {"ok": True, "summary": "", "navigate": view}
    return {"ok": False, "summary": "(écran inconnu)"}


def _run_start_prospection(action: dict) -> dict:
    api, err = _need_api()
    if err:
        return err
    r = api.prospection_start({
        "source": action.get("source") or "",
        "params": action.get("params") or {},
        "dry_run": bool(action.get("dry_run")),
        "force": bool(action.get("force")),
    })
    if r.get("ok"):
        label = ((r.get("mission") or {}).get("label") or "")
        mode = ("Test à blanc lancé" if action.get("dry_run")
                else "Mission lancée")
        return {"ok": True,
                "summary": f"{mode} : {label}. Je suivrai l'avancée — tu "
                           f"verras tout sur l'écran Prospection.",
                "navigate": "prospection"}
    if r.get("needs_confirm"):
        # Carnet de chasse : recherche déjà faite. Rien n'est lancé — on
        # le dit, et l'utilisateur peut insister (l'IA remettra force).
        return {"ok": False,
                "summary": (r.get("warning") or "Cette recherche a déjà "
                            "été faite.") + " Si tu veux vraiment la "
                            "refaire, redemande-la-moi en précisant "
                            "« relance quand même »."}
    return {"ok": False, "summary": f"Impossible de lancer : {r.get('error')}"}


def _run_toggle_autopilot(action: dict) -> dict:
    api, err = _need_api()
    if err:
        return err
    enabled = bool(action.get("enabled"))
    from triskell_core.prospect.pipeline import PipelineConfig
    cfg = PipelineConfig.load()
    if enabled:
        modes = (api.autopilot_get_stage_modes() or {}).get("modes") or {}
        if modes.get("send") == "auto":
            # Garde-fou historique (NON NÉGOCIABLE) : quand l'envoi est
            # réglé sur AUTOMATIQUE, l'allumage ne passe jamais par
            # l'assistant — confirmation écrite sur l'écran obligatoire.
            return {"ok": False,
                    "summary": "L'envoi est réglé sur AUTOMATIQUE — par "
                               "sécurité je ne l'allume pas d'ici. Va sur "
                               "l'écran Prospection, le bouton te demandera "
                               "confirmation.",
                    "navigate": "prospection"}
    cfg.enabled = enabled
    cfg.save()
    return {"ok": True,
            "summary": ("Auto-pilote allumé — il préparera des brouillons "
                        "à valider." if enabled else "Auto-pilote éteint.")}


def _run_cancel_mission(action: dict) -> dict:
    api, err = _need_api()
    if err:
        return err
    r = api.prospection_mission_cancel({"id": action.get("id") or ""})
    return {"ok": bool(r.get("ok")),
            "summary": ("Mission abandonnée." if r.get("ok")
                        else f"Échec : {r.get('error')}")}


def _run_approve_draft(action: dict) -> dict:
    api, err = _need_api()
    if err:
        return err
    src = (action.get("source") or "prospect").strip() or "prospect"
    r = api.draft_approve({"id": action.get("id") or "", "source": src})
    if r.get("ok"):
        if src == "convoy":
            return {"ok": True,
                    "summary": "Brouillon approuvé — il partira avec le "
                               "prochain départ du convoi."}
        return {"ok": True, "summary": "C'est parti : le mail est envoyé."}
    return {"ok": False,
            "summary": f"Le mail n'est PAS parti : {r.get('error')}",
            "navigate": "drafts"}


def _run_reject_draft(action: dict) -> dict:
    api, err = _need_api()
    if err:
        return err
    src = (action.get("source") or "prospect").strip() or "prospect"
    r = api.draft_reject({"id": action.get("id") or "", "source": src})
    return {"ok": bool(r.get("ok")),
            "summary": ("Brouillon refusé — rien ne partira."
                        if r.get("ok")
                        else f"Échec du refus : {r.get('error')}")}


def _run_reply_prospect(action: dict) -> dict:
    """Répondre à une réponse de prospect : pose le texte (si fourni) puis
    envoie. Les garde-fous de l'app (déjà client, déjà contacté) restent
    actifs : en cas d'alerte, rien ne part et on l'explique."""
    api, err = _need_api()
    if err:
        return err
    rid = (action.get("id") or "").strip()
    if not rid:
        return {"ok": False, "summary": "Il me manque la réponse visée."}
    body = str(action.get("body") or "").strip()
    subject = str(action.get("subject") or "").strip()
    if body:
        if not subject:
            row = _load_reply_row(rid) or {}
            sug = ((row.get("extra") or {}).get("suggested_reply") or {})
            subject = (sug.get("subject")
                       or ("Re: " + str(row.get("subject") or "")).strip())
        u = api.reply_update({"id": rid, "subject": subject, "body": body})
        if not (u.get("ok") or u.get("success")):
            return {"ok": False,
                    "summary": "Je n'ai pas pu poser le texte de la "
                               f"réponse : {u.get('error')}",
                    "navigate": "replies"}
    r = api.reply_send_now({"id": rid, "force": False})
    if r.get("ok") or r.get("success"):
        return {"ok": True, "summary": "Réponse envoyée au prospect."}
    warns = r.get("warnings") or []
    if warns:
        return {"ok": False,
                "summary": "L'envoi a été retenu par prudence : "
                           + " ; ".join(str(w) for w in warns[:3])
                           + ". Si tu veux quand même l'envoyer, passe par "
                             "l'écran Réponses.",
                "navigate": "replies"}
    return {"ok": False,
            "summary": f"La réponse n'est pas partie : {r.get('error')}",
            "navigate": "replies"}


def _run_convoy_send(action: dict) -> dict:
    api, err = _need_api()
    if err:
        return err
    r = api.convoy_start_send({"campaign_id": action.get("id") or ""})
    if r.get("ok"):
        n = r.get("approved")
        return {"ok": True,
                "summary": (f"Départ du convoi lancé — {n} mails approuvés "
                            "vont partir au rythme réglé."
                            if isinstance(n, int)
                            else "Départ du convoi lancé."),
                "navigate": "convoy"}
    return {"ok": False,
            "summary": f"Le convoi n'est pas parti : {r.get('error')}",
            "navigate": "convoy"}


def _run_convoy_stop(action: dict) -> dict:
    api, err = _need_api()
    if err:
        return err
    r = api.convoy_stop_send({"campaign_id": action.get("id") or ""})
    return {"ok": bool(r.get("ok")),
            "summary": ("Envoi du convoi arrêté."
                        if r.get("ok")
                        else f"Échec de l'arrêt : {r.get('error')}")}


def _run_add_brain_note(action: dict) -> dict:
    api, err = _need_api()
    if err:
        return err
    content = str(action.get("content") or "").strip()
    if not content:
        return {"ok": False, "summary": "La note est vide."}
    r = api.brain_add({"content": content})
    if r.get("ok"):
        cat = ((r.get("note") or {}).get("category") or "").strip()
        return {"ok": True,
                "summary": ("Note rangée dans le Cerveau"
                            + (f" ({cat})" if cat else "") + ".")}
    return {"ok": False, "summary": f"Note non enregistrée : {r.get('error')}"}


def _run_update_prospect(action: dict) -> dict:
    """Complète une fiche prospect : note datée, étiquettes, statut —
    SANS toucher au reste (ni au « dernier contact », réservé aux envois).
    Si l'email est inconnu, crée la fiche."""
    email = str(action.get("email") or "").strip().lower()
    name = str(action.get("name") or "").strip()
    note = str(action.get("note") or "").strip()
    status = str(action.get("status") or "").strip().lower()
    tags = action.get("tags") if isinstance(action.get("tags"), list) else []
    tags = [str(t).strip() for t in tags if str(t).strip()][:8]
    if not email or "@" not in email:
        return {"ok": False,
                "summary": "Il me faut l'adresse mail du prospect pour "
                           "retrouver (ou créer) sa fiche."}
    if status and status not in _STATUS_FR:
        return {"ok": False,
                "summary": "Statut inconnu — je connais : "
                           + ", ".join(sorted(_STATUS_FR)) + "."}
    if not (note or tags or status):
        return {"ok": False,
                "summary": "Rien à changer sur la fiche (ni note, ni "
                           "étiquette, ni statut)."}
    client = _supabase()
    if client is None:
        return {"ok": False, "summary": "Base partagée non connectée."}
    try:
        sb = client.raw
        found = _find_prospects(email)
        if found:
            p = found[0]
            update_row: dict[str, Any] = {}
            if note:
                old = str(p.get("notes") or "").strip()
                stamp = _now_iso()[:10]
                update_row["notes"] = (old + ("\n" if old else "")
                                       + f"[{stamp}] {note}").strip()
            if tags:
                old_tags = p.get("tags") or []
                if isinstance(old_tags, str):
                    try:
                        old_tags = json.loads(old_tags)
                    except Exception:
                        old_tags = []
                update_row["tags"] = sorted({*(old_tags or []), *tags})
            if status:
                update_row["status"] = status
            sb.table("prospects").update(update_row).eq(
                "id", p["id"]).execute()
            label = p.get("name") or email
            return {"ok": True,
                    "summary": f"Fiche de {label} mise à jour."}
        if not name:
            return {"ok": False,
                    "summary": "Cette adresse n'est pas dans la base — "
                               "donne-moi aussi le nom et je crée la fiche."}
        row = {
            "name": name,
            "emails": [email],
            "status": status or "new",
            "notes": (f"[{_now_iso()[:10]}] {note}" if note else ""),
            "tags": tags,
        }
        try:
            ws_id = client._current_workspace_id()
            if ws_id:
                row["workspace_id"] = ws_id
        except Exception:
            pass
        sb.table("prospects").insert(row).execute()
        return {"ok": True,
                "summary": f"Fiche créée pour {name} ({email})."}
    except Exception as exc:
        logger.debug("copilot update_prospect: %s", exc)
        return {"ok": False,
                "summary": f"La fiche n'a pas pu être modifiée : {exc}"}


def _run_create_shortcut(action: dict) -> dict:
    """Crée un raccourci (bouton du volet, planifiable) — étape 5.
    L'utilisateur visé est posé par le routeur (champ interne _user)."""
    from . import copilot_habits
    user_id = str(action.get("_user") or "jordan")
    inner = action.get("action") if isinstance(action.get("action"),
                                               dict) else None
    res = copilot_habits.create_shortcut(
        user_id,
        label=str(action.get("label") or ""),
        action=inner,
        question=str(action.get("question") or "") or None,
        schedule=action.get("schedule"),
        source="copilote",
    )
    if not res.get("ok"):
        return {"ok": False, "summary": res.get("error") or "Échec."}
    sc = res.get("shortcut") or {}
    when = sc.get("schedule_label") or ""
    if when:
        return {"ok": True,
                "summary": f"Raccourci « {sc.get('label')} » créé — et je "
                           f"te le préparerai {when} (carte à confirmer, "
                           "rien ne part sans toi)."}
    return {"ok": True,
            "summary": f"Raccourci « {sc.get('label')} » créé — tu le "
                       "trouveras au-dessus du champ de discussion."}


def _run_view_prospect(action: dict) -> dict:
    """Lecture : montre la fiche d'un prospect (par mail ou par nom)."""
    query = str(action.get("query") or action.get("email")
                or action.get("name") or "").strip()
    if not query:
        return {"ok": False, "summary": "Dis-moi quel prospect regarder "
                                        "(nom ou adresse mail)."}
    found = _find_prospects(query)
    if not found:
        return {"ok": False,
                "summary": f"Aucune fiche trouvée pour « {query} » dans la "
                           "base des prospects.",
                "navigate": "prospects_crm"}
    if len(found) > 1 and "@" not in query:
        names = [f"{p.get('name') or '?'}"
                 + (f" ({(p.get('emails') or [''])[0]})"
                    if (p.get("emails") or [""])[0] else "")
                 for p in found[:5]]
        return {"ok": True,
                "summary": "Plusieurs fiches correspondent — laquelle ?\n"
                           + "\n".join("- " + n for n in names)}
    return {"ok": True, "summary": _format_prospect_card(found[0])}


# ---------------------------------------------------------------------------
# Les aperçus de proposition (ce que la carte Confirmer/Annuler montre)
# ---------------------------------------------------------------------------
def _preview_approve_draft(action: dict) -> Optional[dict]:
    return _load_draft_preview(str(action.get("id") or ""),
                               (action.get("source") or "prospect").strip())


def _preview_reply(action: dict) -> Optional[dict]:
    row = _load_reply_row(str(action.get("id") or ""))
    extra = (row or {}).get("extra") or {}
    sug = extra.get("suggested_reply") or {}
    body = str(action.get("body") or "").strip() or str(sug.get("body") or "")
    subject = (str(action.get("subject") or "").strip()
               or str(sug.get("subject") or "")
               or ("Re: " + str((row or {}).get("subject") or "")).strip())
    if not body:
        return None
    return {
        "to": str(extra.get("from") or ""),
        "to_name": "",
        "subject": subject,
        "body": body[:MAX_PREVIEW_BODY],
        "context": _excerpt(extra.get("body_excerpt"), 220),
    }


def _preview_convoy_send(action: dict) -> Optional[dict]:
    api = _api()
    if api is None:
        return None
    try:
        from . import convoy_runner
        camp = convoy_runner.load_campaign(str(action.get("id") or ""))
        if camp is None:
            return None
        counts = camp.counts() or {}
        note = (f"{counts.get('approved', 0)} mails prêts à partir"
                f" · {counts.get('pending', 0)} encore en attente")
        if getattr(camp, "mode", "") == "auto":
            note += (" (mode auto : les mails en attente seront approuvés "
                     "d'office au départ)")
        return {"info": f"Convoi « {getattr(camp, 'name', '')} » — {note}."}
    except Exception as exc:
        logger.debug("copilot convoy preview: %s", exc)
        return None


# ---------------------------------------------------------------------------
# LE REGISTRE — la liste blanche, avec famille et niveau de risque déclarés
# ---------------------------------------------------------------------------
ACTIONS: dict[str, dict[str, Any]] = {
    # --- hors curseur : naviguer, regarder -------------------------------
    "navigate": {
        "family": None, "risk": "lecture", "sends_mail": False,
        "label": "Ouvrir un écran",
        "run": _run_navigate, "preview": None,
        "title": lambda a, pv: "Ouvrir un écran",
    },
    "view_prospect": {
        "family": "notes", "risk": "lecture", "sends_mail": False,
        "label": "Consulter une fiche prospect",
        "run": _run_view_prospect, "preview": None,
        "title": lambda a, pv: "Consulter la fiche "
                               + str(a.get("query") or a.get("email")
                                     or a.get("name") or ""),
    },
    # --- famille prospection & machines ----------------------------------
    "start_prospection": {
        "family": "prospection", "risk": "sensible", "sends_mail": False,
        "label": "Lancer une prospection",
        "run": _run_start_prospection, "preview": None,
        "title": lambda a, pv: ("Tester à blanc une prospection"
                                if a.get("dry_run")
                                else "Lancer une prospection")
                               + f" ({a.get('source') or '?'})",
    },
    "toggle_autopilot": {
        "family": "prospection", "risk": "sensible", "sends_mail": False,
        "label": "Auto-pilote on/off",
        "run": _run_toggle_autopilot, "preview": None,
        "title": lambda a, pv: ("Allumer l'Auto-pilote"
                                if a.get("enabled")
                                else "Éteindre l'Auto-pilote"),
    },
    "cancel_mission": {
        "family": "prospection", "risk": "reversible", "sends_mail": False,
        "label": "Abandonner une mission",
        "run": _run_cancel_mission, "preview": None,
        "title": lambda a, pv: "Abandonner une mission",
    },
    "convoy_stop": {
        "family": "prospection", "risk": "reversible", "sends_mail": False,
        "label": "Arrêter l'envoi d'un convoi",
        "run": _run_convoy_stop, "preview": None,
        "title": lambda a, pv: "Arrêter l'envoi du convoi",
    },
    # --- famille notes & fiches ------------------------------------------
    "add_brain_note": {
        "family": "notes", "risk": "reversible", "sends_mail": False,
        "label": "Ajouter une note au Cerveau",
        "run": _run_add_brain_note, "preview": None,
        "title": lambda a, pv: "Noter dans le Cerveau : "
                               + _excerpt(a.get("content"), 80),
    },
    "update_prospect": {
        "family": "notes", "risk": "reversible", "sends_mail": False,
        "label": "Compléter une fiche prospect",
        "run": _run_update_prospect, "preview": None,
        "title": lambda a, pv: "Compléter la fiche de "
                               + str(a.get("name") or a.get("email") or "?"),
    },
    "create_shortcut": {
        "family": "notes", "risk": "reversible", "sends_mail": False,
        "label": "Créer un raccourci",
        "run": _run_create_shortcut, "preview": None,
        "title": lambda a, pv: "Créer le raccourci « "
                               + str(a.get("label") or "?") + " »",
    },
    # --- famille mails (PLAFONNÉE : jamais « il fait seul ») --------------
    "approve_draft": {
        "family": "mails", "risk": "sensible", "sends_mail": True,
        "label": "Approuver un brouillon (= il part)",
        "run": _run_approve_draft, "preview": _preview_approve_draft,
        "title": lambda a, pv: "Envoyer le brouillon à "
                               + str((pv or {}).get("to_name")
                                     or (pv or {}).get("to") or "?"),
    },
    "reject_draft": {
        "family": "mails", "risk": "reversible", "sends_mail": False,
        "label": "Refuser un brouillon",
        "run": _run_reject_draft, "preview": _preview_approve_draft,
        "title": lambda a, pv: "Refuser le brouillon pour "
                               + str((pv or {}).get("to_name")
                                     or (pv or {}).get("to") or "?"),
    },
    "reply_prospect": {
        "family": "mails", "risk": "sensible", "sends_mail": True,
        "label": "Répondre à un prospect",
        "run": _run_reply_prospect, "preview": _preview_reply,
        "title": lambda a, pv: "Envoyer la réponse à "
                               + str((pv or {}).get("to") or "?"),
    },
    "convoy_send": {
        "family": "mails", "risk": "sensible", "sends_mail": True,
        "label": "Lancer l'envoi d'un convoi",
        "run": _run_convoy_send, "preview": _preview_convoy_send,
        "title": lambda a, pv: "Lancer l'envoi du convoi",
    },
}


def _run_action(spec: dict, action: dict) -> dict:
    """Exécute un exécuteur du registre sans jamais laisser fuir d'exception."""
    try:
        return spec["run"](action) or {}
    except Exception as exc:
        logger.warning("copilot action %s: %s", action.get("do"), exc)
        return {"ok": False, "summary": f"L'action a échoué : {exc}"}


# ---------------------------------------------------------------------------
# LE routeur : exécuter / proposer / refuser, selon le curseur
# ---------------------------------------------------------------------------
def execute_action(action: dict, *, user_id: str = "jordan",
                   channel: str = "copilot") -> dict:
    """Le point d'entrée unique des actions de l'assistant.

    Renvoie :
      {ok, summary, navigate?}                — exécutée (ou refusée)
      {ok: True, proposed: {...}, summary}    — rangée en proposition :
        l'appelant dépose la carte dans le fil (le serveur n'a RIEN exécuté).
    """
    do = str((action or {}).get("do") or "")
    spec = ACTIONS.get(do)
    if spec is None:
        return {"ok": False, "summary": "(action inconnue, rien fait)"}

    user_id = _safe_user(user_id)
    # L'utilisateur visé voyage avec l'action (toujours posé par le
    # serveur — jamais par l'IA ni le navigateur).
    action = dict(action or {})
    action["_user"] = user_id
    trust = effective_trust(user_id, do)

    if trust == "never":
        fam = FAMILY_LABELS.get(spec.get("family") or "", "cette famille")
        return {"ok": False,
                "summary": f"Tes réglages me l'interdisent ({fam} : "
                           f"« jamais »). Tu peux changer ça dans "
                           f"l'écran 📌 du volet, ou le faire toi-même "
                           f"dans l'app."}

    if trust == "ask":
        preview = None
        if spec.get("preview"):
            try:
                preview = spec["preview"](action)
            except Exception as exc:
                logger.debug("copilot preview %s: %s", do, exc)
        # Un envoi de mail sans aperçu fiable = pas de carte aveugle :
        # on refuse proprement plutôt que de faire confirmer à l'aveugle.
        if spec.get("sends_mail") and do != "convoy_send" and not (
                preview and (preview.get("body") or "").strip()):
            return {"ok": False,
                    "summary": "Je n'ai pas réussi à retrouver le contenu "
                               "exact de ce mail — je ne te ferai pas "
                               "confirmer à l'aveugle. Regarde sur l'écran "
                               "concerné, ou redemande-moi dans un instant.",
                    "navigate": ("replies" if do == "reply_prospect"
                                 else "drafts")}
        try:
            title = spec["title"](action or {}, preview)
        except Exception:
            title = spec.get("label") or do
        prop = create_proposal(user_id, action, title=title, preview=preview)
        return {"ok": True, "proposed": prop,
                "summary": ""}

    result = _run_action(spec, action)
    # Le journal ne trace que les vrais actes (pas les lectures/navigation).
    if spec.get("risk") != "lecture":
        add_journal_entry(
            user_id, do=do,
            label=(spec.get("label") or do),
            origin=("vocal" if channel == "vocal" else "direct"),
            ok=bool(result.get("ok")),
            summary=(result.get("summary") or "")[:300])
    if result.get("ok"):
        # Étape 5 : les exécutions réussies nourrissent le compteur
        # d'habitudes (seules les actions rejouables comptent).
        try:
            from . import copilot_habits
            copilot_habits.record_action(user_id, action)
        except Exception as exc:
            logger.debug("copilot habit record: %s", exc)
    return result


# ---------------------------------------------------------------------------
# Le bloc « TU PEUX AGIR » du prompt — généré depuis le registre
# ---------------------------------------------------------------------------
def _trust_marker(user_id: str, do: str) -> str:
    lvl = effective_trust(user_id, do)
    if lvl == "ask":
        return " ✋(confirmation : une carte Confirmer/Annuler apparaîtra)"
    if lvl == "never":
        return " 🚫(interdit par ses réglages : n'utilise PAS ce tag, "\
               "explique et propose l'écran)"
    return ""


def build_actions_prompt(user_id: str = "jordan") -> str:
    """Le mode d'emploi des actions pour l'IA, fidèle au curseur ACTUEL de
    l'utilisateur. Remplace l'ancien bloc statique."""
    u = _safe_user(user_id)
    m = lambda do: _trust_marker(u, do)  # noqa: E731
    # La liste des écrans ouvrables vient de la liste blanche réelle :
    # le prompt ne peut plus diverger de ce que _run_navigate accepte.
    from . import claude_advisor as _ca
    nav_views = ", ".join(sorted(_ca._ALLOWED_NAV_VIEWS))
    return f"""TU PEUX AGIR SUR L'APP (pas seulement répondre).

Quand {'{PRENOM}'} te demande de FAIRE quelque chose, tu termines ta réponse par
UNE seule ligne de commande, invisible pour lui :
[ACTION:{{"do":"...", ...}}]

Certaines actions sont marquées ✋ : le système les transforme en carte
Confirmer/Annuler dans le fil (RIEN ne part sans son clic). Émets le tag
normalement, et annonce naturellement qu'une confirmation l'attend
(« Je te prépare ça, tu n'as plus qu'à confirmer »). Ne promets JAMAIS
qu'une action ✋ est déjà faite.

ACTIONS DISPONIBLES :

1. Lancer une prospection complète (recherche → base → Auto-pilote){m('start_prospection')} :
   [ACTION:{{"do":"start_prospection","source":"pme","params":{{"metier":"plombier","departement":"71","volume":30}},"dry_run":false}}]
   - source "pme" (PME françaises) → params {{metier, departement?, code_postal?, volume}}
   - source "local" (commerces Google Maps) → params {{metier, zone, volume}}
   - source "createurs" (YouTube/Twitch) → params {{niche, plateformes:["youtube"], volume}}
   - "dry_run":true = TEST À BLANC (rien n'est enregistré, juste un rapport).
   - Réponse « recherche déjà faite » (carnet de chasse) = rien n'a été
     lancé. Tu relances avec "force":true UNIQUEMENT si {'{PRENOM}'} insiste
     explicitement après avoir entendu la date et la récolte d'avant.
2. Allumer / éteindre l'Auto-pilote{m('toggle_autopilot')} :
   [ACTION:{{"do":"toggle_autopilot","enabled":true}}]
3. Abandonner une mission{m('cancel_mission')} : [ACTION:{{"do":"cancel_mission","id":"abc123"}}]
4. Ouvrir un écran pour {'{PRENOM}'} :
   [ACTION:{{"do":"navigate","view":"prospection"}}]
   Écrans ouvrables : {nav_views}.
   (Les moins évidents : morning = la Matinale, brain = le Cerveau/notes,
    geo = être cité par les IA, phare = SEO, delivery = délivrabilité des
    mails, abtest = tests A/B des mails, eclaireur = Compléter les fiches,
    chasseur = Le Chasseur PME, convoy = Le Convoi, health = Santé.)
5. Approuver un brouillon de l'Auto-pilote = LE MAIL PART{m('approve_draft')} :
   [ACTION:{{"do":"approve_draft","id":"<uuid du brouillon>","source":"prospect"}}]
   Les brouillons en attente sont dans le JSON (pending_drafts), avec leur id
   et leur source ("prospect" ou "convoy"). Recopie l'id EXACTEMENT — jamais
   d'id inventé. Brouillon introuvable dans le JSON → dis-le et propose
   l'écran Brouillons.
6. Refuser un brouillon (rien ne part){m('reject_draft')} :
   [ACTION:{{"do":"reject_draft","id":"<uuid>","source":"prospect"}}]
7. Répondre à la réponse d'un prospect{m('reply_prospect')} :
   [ACTION:{{"do":"reply_prospect","id":"<uuid de la réponse>","subject":"Re: ...","body":"<ta réponse complète>"}}]
   Les réponses reçues sont dans le JSON (recent_replies) avec leur id.
   C'est TOI qui rédiges body : français chaleureux, ton de Jordan, JAMAIS
   d'impératif pressant, signature sobre « Jordan — Studio Triskell ».
   Sans body, la réponse déjà suggérée par l'app partira telle quelle.
8. Lancer l'envoi d'un convoi (campagne préparée){m('convoy_send')} :
   [ACTION:{{"do":"convoy_send","id":"<uuid de la campagne>"}}]
9. Arrêter l'envoi d'un convoi en cours{m('convoy_stop')} :
   [ACTION:{{"do":"convoy_stop","id":"<uuid de la campagne>"}}]
10. Ajouter une note dans le Cerveau de l'app (les notes de {'{PRENOM}'},
    pas ton carnet à toi){m('add_brain_note')} :
    [ACTION:{{"do":"add_brain_note","content":"<la note>"}}]
11. Compléter une fiche prospect (note datée, étiquettes, statut){m('update_prospect')} :
    [ACTION:{{"do":"update_prospect","email":"x@y.fr","name":"Nom","note":"...","tags":["..."],"status":"interested"}}]
    (statuts : new, contacted, replied, interested, not_now, no, won,
     unsubscribed, bounced — n'envoie que ce qui change)
12. Consulter une fiche prospect (lecture seule) :
    [ACTION:{{"do":"view_prospect","query":"nom ou email"}}]
13. Créer un raccourci (bouton d'un clic au-dessus du champ de discussion,
    avec rendez-vous planifié possible){m('create_shortcut')} :
    [ACTION:{{"do":"create_shortcut","label":"Prospection plombiers 56","action":{{"do":"start_prospection","source":"pme","params":{{"metier":"plombier","departement":"56","volume":30}},"dry_run":false}},"schedule":{{"days":[0],"hour":9,"minute":0}}}}]
    ou pour une question d'information :
    [ACTION:{{"do":"create_shortcut","label":"Le point chasse","question":"Où en est ma prospection ?"}}]
    - UNIQUEMENT quand {'{PRENOM}'} demande un raccourci / bouton /
      rendez-vous récurrent. Jamais de ta propre initiative.
    - Actions raccourcissables : start_prospection, toggle_autopilot,
      view_prospect, navigate. Une question marche aussi (sans schedule).
    - schedule (optionnel, actions seulement) : jours 0=lundi … 6=dimanche.
      Un rendez-vous PRÉPARE l'action à l'heure dite et dépose une carte
      à confirmer — rien ne se lance jamais tout seul.
    - Pour modifier ou supprimer un raccourci : renvoie {'{PRENOM}'} vers
      l'écran 📌 du volet (toi tu ne peux que créer).

RÈGLES DE PRUDENCE (non négociables) :
- Une action RÉELLE qui écrit ou lance des machines : tu l'exécutes
  UNIQUEMENT si {'{PRENOM}'} l'a demandée clairement. S'il est vague
  (« on devrait prospecter »), tu proposes d'abord — et tu peux suggérer
  le test à blanc.
- En cas de doute sur les paramètres (quel métier ? quelle zone ? quel
  brouillon ?), tu POSES LA QUESTION au lieu d'inventer.
- Les id viennent du JSON (pending_drafts, recent_replies, missions,
  convoy) — recopiés à l'identique. Un id que tu n'as pas vu n'existe pas.
- JAMAIS plus d'une action par tour. Le tag en DERNIÈRE ligne, JSON valide.
- Après le tag, rien. Le système exécute et colle la confirmation à ta voix.
- Tu n'annonces jamais le tag ni son contenu technique : tu parles
  naturellement (« C'est parti, je lance ça » + le tag)."""
