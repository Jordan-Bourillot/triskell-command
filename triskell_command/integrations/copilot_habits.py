"""Étape 5 du copilote omniprésent — les habitudes deviennent des raccourcis.

La version HONNÊTE, par règles, zéro IA :

  - on COMPTE ce qui se répète : les actions exécutées avec succès (même
    commande, mêmes paramètres) et les questions posées telles quelles ;
  - au seuil (3 fois en 30 jours), le copilote PROPOSE — une seule fois,
    à l'ouverture du volet, jamais plus d'une proposition par jour ; un
    refus est définitif pour ce motif ;
  - un raccourci accepté devient un BOUTON d'un clic dans le volet, et/ou
    un RENDEZ-VOUS planifié (jour + heure). Décision de Jordan
    (11/06/2026) : un rendez-vous PRÉPARE l'action et tend la carte
    Confirmer/Annuler — rien ne se lance jamais sans son clic.

Comme le reste du copilote : best-effort partout, messages en français,
stockage shared_settings avec secours fichier local.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Réglages
# ---------------------------------------------------------------------------
HABITS_SETTING_PREFIX = "copilot_habits_"        # + user_id
SHORTCUTS_SETTING_PREFIX = "copilot_shortcuts_"  # + user_id
_LOCAL_HABITS_FILE = Path.home() / ".triskell-command" / "copilot_habits.json"
_LOCAL_SHORTCUTS_FILE = (Path.home() / ".triskell-command"
                         / "copilot_shortcuts.json")

HABIT_THRESHOLD = 3        # répétitions avant de proposer
HABIT_WINDOW_DAYS = 30     # fenêtre de comptage glissante
MAX_MOTIFS = 50            # motifs gardés (les plus récents)
MAX_TIMES_KEPT = 10        # horodatages gardés par motif
PROPOSAL_GAP_HOURS = 24    # au plus une proposition d'habitude par jour
QUESTION_MAX_CHARS = 80    # au-delà, ce n'est pas une « question type »

MAX_SHORTCUTS = 12         # raccourcis max (l'écran reste lisible)
MAX_LABEL_CHARS = 40
MAX_QUESTION_CHARS = 200
SCHEDULE_GRACE_MINUTES = 30  # un rendez-vous reste « dû » 30 min

# Les seules actions qui ont un sens rejouées à l'identique. Les actions
# à cible unique (approuver TEL brouillon, répondre à TELLE réponse…)
# ne seront jamais des raccourcis.
SHORTCUTTABLE_DOS = ("start_prospection", "toggle_autopilot",
                     "view_prospect", "navigate")

DAY_NAMES = ("lundi", "mardi", "mercredi", "jeudi", "vendredi",
             "samedi", "dimanche")

_HABITS_LOCK = threading.Lock()
_SHORTCUTS_LOCK = threading.Lock()


def _now() -> datetime:
    return datetime.now()


def _now_iso() -> str:
    return _now().isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Stockage (réutilise la tuyauterie du copilote)
# ---------------------------------------------------------------------------
def _doc_read(prefix: str, local_file: Path, user_id: str) -> dict:
    try:
        from . import copilot
        safe = "".join(c for c in (user_id or "jordan")
                       if c.isalnum() or c in "-_") or "jordan"
        raw = copilot._doc_read(prefix + safe, local_file, safe)
        return raw if isinstance(raw, dict) else {}
    except Exception as exc:
        logger.debug("copilot_habits read %s: %s", prefix, exc)
        return {}


def _doc_write(prefix: str, local_file: Path, user_id: str,
               payload: dict) -> None:
    try:
        from . import copilot
        safe = "".join(c for c in (user_id or "jordan")
                       if c.isalnum() or c in "-_") or "jordan"
        copilot._doc_write(prefix + safe, local_file, safe, payload)
    except Exception as exc:
        logger.debug("copilot_habits write %s: %s", prefix, exc)


# ---------------------------------------------------------------------------
# Normalisation des motifs
# ---------------------------------------------------------------------------
def action_key(action: dict) -> Optional[str]:
    """La clé d'un motif d'action : commande + paramètres normalisés.
    None si l'action n'est pas « raccourcissable » (cible unique)."""
    do = str((action or {}).get("do") or "")
    if do not in SHORTCUTTABLE_DOS:
        return None

    def _norm(v: Any) -> Any:
        if isinstance(v, str):
            return " ".join(v.split()).lower()
        if isinstance(v, dict):
            return {k: _norm(x) for k, x in sorted(v.items()) if x not in
                    ("", None, [], {})}
        if isinstance(v, list):
            return [_norm(x) for x in v]
        return v

    keep = {}
    for field in ("source", "params", "view", "query", "email", "name",
                  "enabled", "dry_run"):
        val = (action or {}).get(field)
        if val in ("", None, [], {}):
            continue
        keep[field] = _norm(val)
    try:
        return do + "|" + json.dumps(keep, ensure_ascii=False,
                                     sort_keys=True, separators=(",", ":"))
    except Exception:
        return None


def normalize_question(text: str) -> Optional[str]:
    """La forme canonique d'une question (pour compter les répétitions
    exactes). None si trop longue ou vide."""
    q = " ".join(str(text or "").split()).strip().lower()
    q = q.rstrip("?!. ").strip()
    if not q or len(q) > QUESTION_MAX_CHARS:
        return None
    return q


def auto_label(action: dict) -> str:
    """Un libellé court et parlant pour un motif d'action."""
    do = str((action or {}).get("do") or "")
    if do == "start_prospection":
        p = (action.get("params") or {})
        who = p.get("metier") or p.get("niche") or "?"
        where = (p.get("departement") or p.get("code_postal")
                 or p.get("zone") or "")
        label = f"Prospection {who}" + (f" ({where})" if where else "")
        if action.get("dry_run"):
            label += " — test à blanc"
        return label[:MAX_LABEL_CHARS]
    if do == "toggle_autopilot":
        return ("Allumer l'Auto-pilote" if action.get("enabled")
                else "Éteindre l'Auto-pilote")
    if do == "view_prospect":
        q = action.get("query") or action.get("email") or action.get("name")
        return f"Fiche {q}"[:MAX_LABEL_CHARS]
    if do == "navigate":
        return f"Ouvrir {action.get('view') or '?'}"[:MAX_LABEL_CHARS]
    return do[:MAX_LABEL_CHARS]


# ---------------------------------------------------------------------------
# Le compteur d'habitudes
# ---------------------------------------------------------------------------
def _load_motifs(user_id: str) -> list[dict]:
    doc = _doc_read(HABITS_SETTING_PREFIX, _LOCAL_HABITS_FILE, user_id)
    items = doc.get("motifs")
    return list(items) if isinstance(items, list) else []


def _save_motifs(user_id: str, motifs: list[dict],
                 last_proposed_at: Optional[str] = None) -> None:
    # Cap : les plus récents (par dernier passage) survivent. La date de
    # dernière proposition (garde anti-lassitude) est PRÉSERVÉE — sinon
    # chaque nouveau comptage la remettrait à zéro.
    if last_proposed_at is None:
        doc = _doc_read(HABITS_SETTING_PREFIX, _LOCAL_HABITS_FILE, user_id)
        last_proposed_at = str(doc.get("last_proposed_at") or "")
    motifs = sorted(motifs, key=lambda m: m.get("last_at") or "")
    _doc_write(HABITS_SETTING_PREFIX, _LOCAL_HABITS_FILE, user_id,
               {"motifs": motifs[-MAX_MOTIFS:],
                "last_proposed_at": last_proposed_at})


def _fresh_times(times: list, now: Optional[datetime] = None) -> list[str]:
    """Garde les horodatages dans la fenêtre de comptage."""
    now = now or _now()
    cutoff = (now - timedelta(days=HABIT_WINDOW_DAYS)).isoformat(
        timespec="seconds")
    out = [str(t) for t in (times or []) if str(t) >= cutoff]
    return out[-MAX_TIMES_KEPT:]


def _record(user_id: str, *, kind: str, key: str, label: str,
            action: Optional[dict] = None,
            question: Optional[str] = None) -> None:
    with _HABITS_LOCK:
        motifs = _load_motifs(user_id)
        motif = next((m for m in motifs if m.get("key") == key), None)
        now_iso = _now_iso()
        if motif is None:
            motif = {
                "id": uuid.uuid4().hex[:8],
                "kind": kind, "key": key,
                "label": str(label or "")[:MAX_LABEL_CHARS],
                "times": [], "proposed": "", "dismissed": "",
            }
            if action is not None:
                motif["action"] = action
            if question is not None:
                motif["question"] = question
            motifs.append(motif)
        motif["times"] = _fresh_times(motif.get("times")) + [now_iso]
        motif["times"] = motif["times"][-MAX_TIMES_KEPT:]
        motif["last_at"] = now_iso
        _save_motifs(user_id, motifs)


def record_action(user_id: str, action: dict) -> None:
    """À appeler quand une action a été RÉELLEMENT exécutée avec succès.
    Jamais d'exception."""
    try:
        key = action_key(action)
        if not key:
            return
        # Les champs internes posés par le routeur (_user…) ne sont ni
        # comptés ni stockés.
        clean = {k: v for k, v in (action or {}).items()
                 if not str(k).startswith("_")}
        _record(user_id, kind="action", key=key,
                label=auto_label(clean), action=clean)
    except Exception as exc:
        logger.debug("copilot_habits record_action: %s", exc)


def record_question(user_id: str, text: str) -> None:
    """À appeler pour une question qui n'a PAS déclenché d'action.
    Jamais d'exception."""
    try:
        q = normalize_question(text)
        if not q:
            return
        _record(user_id, kind="question", key="q|" + q,
                label=q[:MAX_LABEL_CHARS], question=q)
    except Exception as exc:
        logger.debug("copilot_habits record_question: %s", exc)


def weekly_rhythm(times: list) -> Optional[dict]:
    """Si au moins HABIT_THRESHOLD occurrences tombent le même jour de la
    semaine, propose un rendez-vous hebdo (heure = médiane arrondie)."""
    stamps = []
    for t in (times or []):
        try:
            stamps.append(datetime.fromisoformat(str(t)))
        except Exception:
            continue
    by_day: dict[int, list[datetime]] = {}
    for s in stamps:
        by_day.setdefault(s.weekday(), []).append(s)
    for day, group in by_day.items():
        if len(group) >= HABIT_THRESHOLD:
            hours = sorted(s.hour for s in group)
            hour = hours[len(hours) // 2]
            return {"days": [day], "hour": int(hour), "minute": 0}
    return None


def schedule_label(schedule: Optional[dict]) -> str:
    """« chaque lundi à 9 h » — pour les cartes et l'écran."""
    if not isinstance(schedule, dict):
        return ""
    try:
        days = [DAY_NAMES[int(d)] for d in (schedule.get("days") or [])
                if 0 <= int(d) <= 6]
        if not days:
            return ""
        h = int(schedule.get("hour") or 0)
        m = int(schedule.get("minute") or 0)
        when = f"{h} h" + (f" {m:02d}" if m else "")
        return "chaque " + " et ".join(days) + f" à {when}"
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# La proposition d'habitude (carte 💡 à l'ouverture du volet)
# ---------------------------------------------------------------------------
def _last_proposed_at(user_id: str) -> str:
    doc = _doc_read(HABITS_SETTING_PREFIX, _LOCAL_HABITS_FILE, user_id)
    return str(doc.get("last_proposed_at") or "") if isinstance(doc, dict) \
        else ""


def _set_last_proposed_at(user_id: str, iso: str) -> None:
    with _HABITS_LOCK:
        _save_motifs(user_id, _load_motifs(user_id), last_proposed_at=iso)


def ripe_motif(user_id: str) -> Optional[dict]:
    """Le motif mûr pour une proposition — ou None. Règles de sobriété :
    seuil atteint dans la fenêtre, jamais proposé ni refusé, pas déjà
    couvert par un raccourci, au plus une proposition par 24 h, et de la
    place dans les raccourcis."""
    try:
        last = _last_proposed_at(user_id)
        if last:
            try:
                if (_now() - datetime.fromisoformat(last)
                        < timedelta(hours=PROPOSAL_GAP_HOURS)):
                    return None
            except Exception:
                pass
        shortcuts = list_shortcuts(user_id)
        if len(shortcuts) >= MAX_SHORTCUTS:
            return None
        covered = {s.get("key") for s in shortcuts if s.get("key")}
        for m in _load_motifs(user_id):
            if m.get("proposed") or m.get("dismissed"):
                continue
            if m.get("key") in covered:
                continue
            times = _fresh_times(m.get("times"))
            if len(times) < HABIT_THRESHOLD:
                continue
            out = {
                "id": m.get("id") or "",
                "kind": m.get("kind") or "action",
                "label": m.get("label") or "",
                "count": len(times),
            }
            if m.get("kind") == "action":
                rhythm = weekly_rhythm(times)
                if rhythm:
                    out["schedule_suggestion"] = rhythm
                    out["schedule_label"] = schedule_label(rhythm)
            return out
        return None
    except Exception as exc:
        logger.debug("copilot_habits ripe: %s", exc)
        return None


def mark_proposed(user_id: str, hid: str) -> None:
    """Le motif a eu sa carte 💡 : il ne sera plus jamais re-proposé."""
    try:
        now_iso = _now_iso()
        with _HABITS_LOCK:
            motifs = _load_motifs(user_id)
            for m in motifs:
                if m.get("id") == hid:
                    m["proposed"] = now_iso
            _save_motifs(user_id, motifs)
        _set_last_proposed_at(user_id, now_iso)
    except Exception as exc:
        logger.debug("copilot_habits mark_proposed: %s", exc)


def habit_card_state(user_id: str, hid: str) -> dict:
    """L'état d'une carte 💡 pour le rendu (pending / accepted / dismissed
    / gone)."""
    for m in _load_motifs(user_id):
        if m.get("id") != hid:
            continue
        if m.get("dismissed"):
            status = "dismissed"
        elif m.get("accepted"):
            status = "accepted"
        else:
            status = "pending"
        out = {
            "id": hid, "status": status,
            "kind": m.get("kind") or "action",
            "label": m.get("label") or "",
            "count": len(_fresh_times(m.get("times"))),
        }
        if status == "pending" and m.get("kind") == "action":
            rhythm = weekly_rhythm(_fresh_times(m.get("times")))
            if rhythm:
                out["schedule_suggestion"] = rhythm
                out["schedule_label"] = schedule_label(rhythm)
        return out
    return {"id": hid, "status": "gone"}


def accept_habit(user_id: str, hid: str,
                 with_schedule: bool = False) -> dict:
    """Jordan a dit oui : le motif devient un raccourci (bouton, et
    rendez-vous si demandé et qu'un rythme a été détecté)."""
    with _HABITS_LOCK:
        motifs = _load_motifs(user_id)
        motif = next((m for m in motifs if m.get("id") == hid), None)
        if motif is None:
            return {"ok": False, "error": "Cette suggestion n'existe plus."}
        if motif.get("dismissed"):
            return {"ok": False, "error": "Suggestion déjà refusée."}
        schedule = None
        if with_schedule and motif.get("kind") == "action":
            schedule = weekly_rhythm(_fresh_times(motif.get("times")))
        res = create_shortcut(
            user_id,
            label=motif.get("label") or "",
            action=motif.get("action") if motif.get("kind") == "action"
            else None,
            question=motif.get("question") if motif.get("kind") == "question"
            else None,
            schedule=schedule,
            source="propose",
        )
        if res.get("ok"):
            motif["accepted"] = _now_iso()
            _save_motifs(user_id, motifs)
        return res


def dismiss_habit(user_id: str, hid: str) -> dict:
    """Jordan a dit non : silence définitif sur ce motif."""
    with _HABITS_LOCK:
        motifs = _load_motifs(user_id)
        for m in motifs:
            if m.get("id") == hid:
                m["dismissed"] = _now_iso()
                _save_motifs(user_id, motifs)
                return {"ok": True}
    return {"ok": False, "error": "Cette suggestion n'existe plus."}


# ---------------------------------------------------------------------------
# Les raccourcis
# ---------------------------------------------------------------------------
def _load_shortcuts(user_id: str) -> list[dict]:
    doc = _doc_read(SHORTCUTS_SETTING_PREFIX, _LOCAL_SHORTCUTS_FILE, user_id)
    items = doc.get("items")
    return list(items) if isinstance(items, list) else []


def _save_shortcuts(user_id: str, items: list[dict]) -> None:
    _doc_write(SHORTCUTS_SETTING_PREFIX, _LOCAL_SHORTCUTS_FILE, user_id,
               {"items": items[:MAX_SHORTCUTS]})


def list_shortcuts(user_id: str) -> list[dict]:
    """Les raccourcis, nettoyés pour l'UI (l'action complète reste côté
    serveur mais voyage aussi — elle n'est JAMAIS exécutée depuis le
    client : le run se fait par id)."""
    out = []
    for s in _load_shortcuts(user_id):
        if not isinstance(s, dict) or not s.get("id"):
            continue
        out.append({
            "id": s.get("id"),
            "label": s.get("label") or "",
            "kind": s.get("kind") or "action",
            "question": s.get("question") or "",
            "schedule": s.get("schedule"),
            "schedule_label": schedule_label(s.get("schedule")),
            "paused": bool(s.get("paused")),
            "runs": int(s.get("runs") or 0),
            "last_run_at": s.get("last_run_at") or "",
            "source": s.get("source") or "",
            "key": s.get("key") or "",
        })
    return out


def _clean_schedule(schedule: Any) -> Optional[dict]:
    """Valide {days:[0..6], hour, minute}. None si invalide/absent."""
    if not isinstance(schedule, dict):
        return None
    try:
        days = sorted({int(d) for d in (schedule.get("days") or [])
                       if 0 <= int(d) <= 6})
        hour = int(schedule.get("hour"))
        minute = int(schedule.get("minute") or 0)
        if not days or not (0 <= hour <= 23) or not (0 <= minute <= 59):
            return None
        return {"days": days, "hour": hour, "minute": minute}
    except Exception:
        return None


def create_shortcut(user_id: str, *, label: str,
                    action: Optional[dict] = None,
                    question: Optional[str] = None,
                    schedule: Any = None,
                    source: str = "manuel") -> dict:
    """Crée un raccourci (bouton, et rendez-vous si planifié). Renvoie
    {ok, shortcut} ou {ok: False, error: <français>}."""
    label = " ".join(str(label or "").split())[:MAX_LABEL_CHARS]
    if not label:
        return {"ok": False, "error": "Il faut un nom au raccourci."}

    sched = _clean_schedule(schedule)
    if schedule and not sched:
        return {"ok": False,
                "error": "Rendez-vous invalide (jours 0 à 6, heure 0 à 23)."}

    if action is not None and question:
        return {"ok": False,
                "error": "Un raccourci est SOIT une action SOIT une "
                         "question, pas les deux."}

    item: dict[str, Any] = {
        "id": uuid.uuid4().hex[:8],
        "label": label,
        "created_at": _now_iso(),
        "source": (source or "manuel")[:12],
        "paused": False,
        "runs": 0,
        "last_run_at": "",
        "last_scheduled_date": "",
    }

    if action is not None:
        do = str((action or {}).get("do") or "")
        if do not in SHORTCUTTABLE_DOS:
            return {"ok": False,
                    "error": "Cette action ne peut pas devenir un "
                             "raccourci (elle vise une cible unique). "
                             "Raccourcissables : prospection, Auto-pilote, "
                             "fiche prospect, ouvrir un écran."}
        item["kind"] = "action"
        item["action"] = dict(action)
        item["key"] = action_key(action) or ""
        if sched:
            item["schedule"] = sched
    else:
        q = " ".join(str(question or "").split())[:MAX_QUESTION_CHARS]
        if not q:
            return {"ok": False,
                    "error": "Il faut l'action ou la question du raccourci."}
        if sched:
            return {"ok": False,
                    "error": "Un rendez-vous planifié ne marche qu'avec "
                             "une action (pas une question)."}
        item["kind"] = "question"
        item["question"] = q
        item["key"] = "q|" + (normalize_question(q) or q.lower())

    with _SHORTCUTS_LOCK:
        items = _load_shortcuts(user_id)
        if len(items) >= MAX_SHORTCUTS:
            return {"ok": False,
                    "error": f"Tu as déjà {MAX_SHORTCUTS} raccourcis — "
                             "supprime-en un dans l'écran 📌 pour faire "
                             "de la place."}
        if item["key"] and any(s.get("key") == item["key"] for s in items):
            return {"ok": False,
                    "error": "Un raccourci équivalent existe déjà."}
        items.append(item)
        _save_shortcuts(user_id, items)

    ui = [s for s in list_shortcuts(user_id) if s["id"] == item["id"]]
    return {"ok": True, "shortcut": ui[0] if ui else item}


def get_shortcut(user_id: str, sid: str) -> Optional[dict]:
    """Le raccourci COMPLET (action incluse) — usage serveur uniquement."""
    for s in _load_shortcuts(user_id):
        if isinstance(s, dict) and s.get("id") == str(sid or ""):
            return s
    return None


def delete_shortcut(user_id: str, sid: str) -> dict:
    with _SHORTCUTS_LOCK:
        items = _load_shortcuts(user_id)
        kept = [s for s in items if s.get("id") != str(sid or "")]
        if len(kept) == len(items):
            return {"ok": False, "error": "Raccourci introuvable."}
        _save_shortcuts(user_id, kept)
    return {"ok": True}


def set_paused(user_id: str, sid: str, paused: bool) -> dict:
    with _SHORTCUTS_LOCK:
        items = _load_shortcuts(user_id)
        for s in items:
            if s.get("id") == str(sid or ""):
                s["paused"] = bool(paused)
                _save_shortcuts(user_id, items)
                return {"ok": True, "paused": bool(paused)}
    return {"ok": False, "error": "Raccourci introuvable."}


def record_run(user_id: str, sid: str) -> None:
    """Trace l'usage d'un raccourci (tri de la barre par utilité réelle)."""
    try:
        with _SHORTCUTS_LOCK:
            items = _load_shortcuts(user_id)
            for s in items:
                if s.get("id") == str(sid or ""):
                    s["runs"] = int(s.get("runs") or 0) + 1
                    s["last_run_at"] = _now_iso()
            _save_shortcuts(user_id, items)
    except Exception as exc:
        logger.debug("copilot_habits record_run: %s", exc)


# ---------------------------------------------------------------------------
# Les rendez-vous : qu'est-ce qui est dû ? (appelé par le guetteur)
# ---------------------------------------------------------------------------
def due_scheduled(user_id: str,
                  now: Optional[datetime] = None) -> list[dict]:
    """Les raccourcis planifiés dus MAINTENANT (jour + heure dans la
    fenêtre de grâce, pas en pause, pas déjà déclenchés aujourd'hui).
    Renvoie les raccourcis COMPLETS (action incluse)."""
    now = now or _now()
    today = now.strftime("%Y-%m-%d")
    out = []
    for s in _load_shortcuts(user_id):
        if not isinstance(s, dict) or s.get("paused"):
            continue
        sched = _clean_schedule(s.get("schedule"))
        if not sched or s.get("kind") != "action":
            continue
        if s.get("last_scheduled_date") == today:
            continue
        if now.weekday() not in sched["days"]:
            continue
        start = now.replace(hour=sched["hour"], minute=sched["minute"],
                            second=0, microsecond=0)
        if start <= now < start + timedelta(minutes=SCHEDULE_GRACE_MINUTES):
            out.append(dict(s))
    return out


def mark_scheduled_fired(user_id: str, sid: str,
                         now: Optional[datetime] = None) -> None:
    """À poser AVANT de déposer la carte (anti-double déclenchement)."""
    now = now or _now()
    try:
        with _SHORTCUTS_LOCK:
            items = _load_shortcuts(user_id)
            for s in items:
                if s.get("id") == str(sid or ""):
                    s["last_scheduled_date"] = now.strftime("%Y-%m-%d")
            _save_shortcuts(user_id, items)
    except Exception as exc:
        logger.debug("copilot_habits mark_fired: %s", exc)
