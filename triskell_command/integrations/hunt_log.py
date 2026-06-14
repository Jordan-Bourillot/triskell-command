# -*- coding: utf-8 -*-
"""Carnet de chasse permanent — la mémoire des recherches de prospection.

Demande de Jordan (13/06/2026) : « qu'on ne cherche pas les mêmes choses
aux mêmes endroits lors des prochaines prospections ». Avant ce module,
les missions gardaient leurs critères mais rien ne les RELISAIT : on
pouvait relancer la même recherche sans le savoir (et la liste des
missions est plafonnée à 50 — la mémoire s'effaçait).

Ce module fait deux choses :

1. **Le carnet** : chaque mission RÉELLE (pas les tests à blanc) laisse
   une trace durable — critères normalisés (accents/majuscules/espaces
   ignorés), date, nombre de lancements, récolte. Stocké dans
   shared_settings["prospection_hunt_log"], indépendant de la liste des
   missions et de son plafond de 50.

2. **Le garde-fou** : au lancement, missions.create_mission consulte le
   carnet ; recherche identique déjà faite → réponse `needs_confirm`
   avec un avertissement en français (date + récolte) au lieu d'un
   lancement silencieux. `force=True` passe outre.

Règle d'or : le carnet ne doit JAMAIS empêcher une chasse de partir.
Toutes les écritures sont best-effort (panne → on logge, on continue).
Tout est injectable (client factice) pour les smoke tests.
"""
from __future__ import annotations

import logging
import threading
import unicodedata
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

SHARED_KEY = "prospection_hunt_log"
# Plafond LARGE (≈ des années d'usage) — on écarte d'abord les recherches
# les plus anciennes jamais relancées, pour borner la taille du réglage.
MAX_ENTRIES = 400

# Statuts d'une entrée (vocabulaire des missions, en français)
ST_LANCEE = "lancée"
ST_TERMINEE = "terminée"
ST_ABANDONNEE = "abandonnée"
ST_ERREUR = "erreur"

_LOCK = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _client():
    try:
        from triskell_core.db import get_client, SupabaseNotConfigured
        try:
            c = get_client()
        except SupabaseNotConfigured:
            return None
        return c if c.is_authenticated else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Normalisation des critères — « Électricien  / 22 » == « electricien / 22 »
# ---------------------------------------------------------------------------
def _norm(text) -> str:
    """Minuscules, sans accents, ponctuation/espaces réduits à un espace."""
    s = str(text or "")
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.casefold()
    out = []
    prev_space = True
    for ch in s:
        if ch.isalnum():
            out.append(ch)
            prev_space = False
        elif not prev_space:
            out.append(" ")
            prev_space = True
    return "".join(out).strip()


def criteria_key(source: str, params: dict | None) -> str:
    """Clé d'identité d'une recherche. Même clé = « déjà cherché ».

    Le volume n'en fait PAS partie : chercher 30 ou 100 plombiers dans
    le 35, c'est chercher au même endroit. Les options qui changent la
    POPULATION visée (sans site, sites pauvres, plateformes) en font
    partie.
    """
    p = params or {}
    src = _norm(source)
    if src == "pme":
        mode = "pauvres" if p.get("sites_pourris") else "tous"
        return "|".join(["pme", _norm(p.get("metier")),
                         _norm(p.get("departement")),
                         _norm(p.get("code_postal")), mode])
    if src == "local":
        mode = "sans site" if p.get("sans_site") else "tous"
        pays = _norm(p.get("pays")) or "fr"
        return "|".join(["local", _norm(p.get("metier")),
                         _norm(p.get("zone")), mode, pays])
    if src == "createurs":
        plats = p.get("plateformes") or ["youtube"]
        if not isinstance(plats, list):
            plats = [plats]
        plats_n = sorted({_norm(x) for x in plats if _norm(x)}) or ["youtube"]
        return "|".join(["createurs", _norm(p.get("niche")),
                         ",".join(plats_n)])
    return "|".join([src or "?", _norm(p.get("metier") or p.get("niche")),
                     _norm(p.get("zone") or p.get("departement"))])


def criteria_label(source: str, params: dict | None) -> str:
    """Libellé humain de la recherche (pour les messages et le carnet)."""
    p = params or {}
    src = (source or "").strip().lower()

    def _v(key):
        return str(p.get(key) or "").strip()

    if src == "pme":
        bits = [_v("metier") or "PME"]
        if _v("departement"):
            bits.append(f"dept {_v('departement')}")
        if _v("code_postal"):
            bits.append(f"CP {_v('code_postal')}")
        label = " — ".join(bits)
        if p.get("sites_pourris"):
            label += " · sites à refaire"
        return label
    if src == "local":
        label = " — ".join(x for x in (_v("metier"), _v("zone")) if x) \
                or "commerces locaux"
        if p.get("sans_site"):
            label += " · sans site"
        return label
    if src == "createurs":
        plats = p.get("plateformes") or ["youtube"]
        if not isinstance(plats, list):
            plats = [plats]
        plats_s = ", ".join(str(x) for x in plats if str(x).strip())
        return "Créateurs · " + (_v("niche") or "?") \
               + (f" · {plats_s}" if plats_s else "")
    return _v("metier") or _v("niche") or src or "recherche"


def _date_fr(iso: str) -> str:
    """« 2026-06-13T00:42:00+00:00 » → « 13/06/2026 ». Tolérant."""
    try:
        return datetime.fromisoformat(str(iso)).strftime("%d/%m/%Y")
    except Exception:
        return str(iso or "?")[:10]


def warning_for(entry: dict) -> str:
    """L'avertissement « déjà chassé », en français normal."""
    e = entry or {}
    label = e.get("label") or "cette recherche"
    quand = _date_fr(e.get("last_at"))
    runs = int(e.get("runs") or 1)
    res = e.get("result") or {}
    status = e.get("status") or ""
    if status == ST_TERMINEE and res:
        bilan = (f"{int(res.get('pushed') or 0)} fiche(s) versée(s) "
                 f"sur {int(res.get('found') or 0)} trouvée(s)")
    elif status == ST_LANCEE:
        bilan = "résultat pas encore connu"
    elif status == ST_ABANDONNEE:
        bilan = "suivi abandonné en cours de route"
    elif status == ST_ERREUR:
        bilan = "terminée en erreur"
    else:
        bilan = "résultat inconnu"
    fois = f"déjà faite {runs} fois, la dernière" if runs > 1 else "déjà faite"
    return (f"Recherche {fois} le {quand} : {label} ({bilan}). "
            f"Relancer ne créera aucun doublon — la base fusionne — mais "
            f"la chasse risque de tourner pour peu de neuf.")


# ---------------------------------------------------------------------------
# Stockage — lecture/écriture du carnet (shared_settings)
# ---------------------------------------------------------------------------
def _load_raw(client=None) -> dict | None:
    c = client or _client()
    if c is None:
        return None
    try:
        raw = c.get_shared_setting(SHARED_KEY, None)
    except Exception as exc:
        logger.debug("hunt_log load: %s", exc)
        return None
    if isinstance(raw, dict) and isinstance(raw.get("entries"), list):
        return raw
    return None


def _save_raw(data: dict, client=None) -> bool:
    c = client or _client()
    if c is None:
        return False
    entries = sorted(data.get("entries") or [],
                     key=lambda e: e.get("last_at") or "", reverse=True)
    data = dict(data)
    data["entries"] = entries[:MAX_ENTRIES]
    try:
        c.set_shared_setting(SHARED_KEY, data)
        return True
    except Exception as exc:
        logger.warning("hunt_log save: %s", exc)
        return False


def load(client=None) -> dict:
    """Le carnet. S'il n'existe pas encore : reconstruit depuis la liste
    des missions (rattrapage des recherches faites avant le carnet)."""
    data = _load_raw(client)
    if data is not None:
        return data
    # Première fois → rattrapage depuis les missions existantes
    try:
        from . import missions as _mi
        past = _mi.load_missions(client)
    except Exception:
        past = []
    data = {"v": 1, "backfilled_at": _now(),
            "entries": backfill_from_missions(past)}
    _save_raw(data, client)
    return data


def backfill_from_missions(missions_list: list[dict]) -> list[dict]:
    """Reconstruit des entrées de carnet depuis des missions (réelles
    uniquement — un test à blanc n'a rien versé, il ne « compte » pas)."""
    entries: dict[str, dict] = {}
    real = [m for m in (missions_list or []) if not m.get("dry_run")]
    real.sort(key=lambda m: m.get("created_at") or "")
    for m in real:
        key = criteria_key(m.get("source") or "", m.get("params") or {})
        e = entries.get(key)
        if e is None:
            e = {"key": key,
                 "label": criteria_label(m.get("source") or "",
                                          m.get("params") or {}),
                 "source": m.get("source") or "",
                 "first_at": m.get("created_at") or _now(),
                 "last_at": m.get("created_at") or _now(),
                 "runs": 0, "status": ST_LANCEE, "result": None,
                 "mission_id": ""}
            entries[key] = e
        e["runs"] = int(e.get("runs") or 0) + 1
        e["last_at"] = m.get("created_at") or e["last_at"]
        e["mission_id"] = m.get("id") or ""
        e["status"], e["result"] = _status_result_of(m)
    return list(entries.values())


def _status_result_of(mission: dict) -> tuple[str, dict | None]:
    """Statut + récolte d'une entrée, depuis une mission. Importe les
    statuts missions localement (pas d'import circulaire au chargement)."""
    from . import missions as _mi
    st = mission.get("status") or ""
    counts = mission.get("counts") or {}
    result = {"found": int(counts.get("found") or 0),
              "with_email": int(counts.get("with_email") or 0),
              "pushed": int(counts.get("pushed") or 0)}
    if st == _mi.ST_HANDED:
        return ST_TERMINEE, result
    if st == _mi.ST_ERROR:
        return ST_ERREUR, result
    if st == _mi.ST_CANCELLED:
        return ST_ABANDONNEE, result
    return ST_LANCEE, None


# ---------------------------------------------------------------------------
# Les 3 gestes : consulter / noter un lancement / noter le résultat
# ---------------------------------------------------------------------------
def find(source: str, params: dict | None, client=None) -> dict | None:
    """L'entrée du carnet pour ces critères, ou None si jamais cherché."""
    key = criteria_key(source, params)
    for e in load(client).get("entries") or []:
        if e.get("key") == key:
            return e
    return None


def record_launch(source: str, params: dict | None, mission_id: str,
                  client=None) -> None:
    """Note un lancement RÉEL dans le carnet (appelé par create_mission).
    Best-effort : ne lève jamais."""
    try:
        with _LOCK:
            data = load(client)
            entries = data.get("entries") or []
            key = criteria_key(source, params)
            now = _now()
            for e in entries:
                if e.get("key") == key:
                    if (e.get("mission_id") or "") == (mission_id or ""):
                        # Carnet né À L'INSTANT (rattrapage depuis les
                        # missions, qui contenait déjà CETTE mission) :
                        # ne pas compter ce lancement deux fois.
                        e["status"] = ST_LANCEE
                        break
                    e["runs"] = int(e.get("runs") or 0) + 1
                    e["last_at"] = now
                    e["status"] = ST_LANCEE
                    e["mission_id"] = mission_id or ""
                    e["label"] = criteria_label(source, params)
                    break
            else:
                entries.append({
                    "key": key, "label": criteria_label(source, params),
                    "source": (source or "").strip().lower(),
                    "first_at": now, "last_at": now, "runs": 1,
                    "status": ST_LANCEE, "result": None,
                    "mission_id": mission_id or "",
                })
            data["entries"] = entries
            _save_raw(data, client)
    except Exception as exc:
        logger.debug("hunt_log record_launch: %s", exc)


def record_result(mission: dict, client=None) -> None:
    """Met à jour le carnet quand une mission réelle se termine (versée,
    en erreur ou abandonnée). Best-effort : ne lève jamais."""
    try:
        m = mission or {}
        if m.get("dry_run"):
            return
        with _LOCK:
            data = load(client)
            entries = data.get("entries") or []
            key = criteria_key(m.get("source") or "", m.get("params") or {})
            status, result = _status_result_of(m)
            for e in entries:
                if e.get("key") == key:
                    e["status"] = status
                    if result is not None:
                        e["result"] = result
                    e["mission_id"] = m.get("id") or e.get("mission_id") or ""
                    break
            else:
                # Mission née avant le carnet : on crée l'entrée au passage.
                entries.append({
                    "key": key,
                    "label": criteria_label(m.get("source") or "",
                                             m.get("params") or {}),
                    "source": (m.get("source") or "").strip().lower(),
                    "first_at": m.get("created_at") or _now(),
                    "last_at": m.get("created_at") or _now(),
                    "runs": 1, "status": status, "result": result,
                    "mission_id": m.get("id") or "",
                })
            data["entries"] = entries
            _save_raw(data, client)
    except Exception as exc:
        logger.debug("hunt_log record_result: %s", exc)


def estimate_for(source: str, params: dict | None, client=None) -> dict:
    """Estime, AVANT de lancer, ce qu'une recherche va donner — d'après la
    récolte réelle des fois précédentes (carnet). Lecture seule, best-effort.

    Renvoie {ok, has_history, estimate|None, label, runs?, last_at?, message}.
    estimate = {found_last, with_email_last, pushed_last, est_with_email}.
    """
    try:
        p = params or {}
        src = (source or "").strip().lower()
        try:
            volume = int(p.get("volume") or 0)
        except (TypeError, ValueError):
            volume = 0
        if volume <= 0:
            volume = {"pme": 100, "local": 60, "createurs": 30}.get(src, 60)
        label = criteria_label(source, p)
        e = find(source, params, client)
        if not e:
            return {"ok": True, "has_history": False, "estimate": None,
                    "label": label,
                    "message": "Nouvelle recherche — aucun historique pour estimer."}
        runs = int(e.get("runs") or 1)
        last = e.get("last_at")
        res = e.get("result") or {}
        found = int(res.get("found") or 0)
        with_email = int(res.get("with_email") or 0)
        pushed = int(res.get("pushed") or 0)
        fois = f"déjà cherchée {runs} fois" if runs > 1 else "déjà cherchée une fois"
        if not found:
            return {"ok": True, "has_history": True, "estimate": None,
                    "label": label, "runs": runs, "last_at": last,
                    "message": f"{label} : {fois} (dernière le {_date_fr(last)}), "
                               f"récolte précédente inconnue."}
        rate = (with_email / found) if found else 0.0
        est_with_email = round(min(found, volume) * rate)
        return {
            "ok": True, "has_history": True, "label": label,
            "runs": runs, "last_at": last,
            "estimate": {"found_last": found, "with_email_last": with_email,
                         "pushed_last": pushed, "est_with_email": est_with_email},
            "message": (f"{label} : {fois} (dernière le {_date_fr(last)}) — "
                        f"{found} trouvés dont {with_email} avec mail. "
                        f"Pour {volume}, compte ~{est_with_email} avec mail."),
        }
    except Exception as exc:
        logger.debug("hunt_log estimate_for: %s", exc)
        return {"ok": False, "error": str(exc), "has_history": False,
                "estimate": None, "message": ""}


def list_entries(client=None, limit: int = 100) -> dict:
    """Pour l'écran : {ok, entries (récentes d'abord), total}."""
    try:
        data = load(client)
        entries = sorted(data.get("entries") or [],
                         key=lambda e: e.get("last_at") or "", reverse=True)
        limit = max(1, min(int(limit or 100), MAX_ENTRIES))
        return {"ok": True, "entries": entries[:limit],
                "total": len(data.get("entries") or [])}
    except Exception as exc:
        logger.debug("hunt_log list_entries: %s", exc)
        return {"ok": False, "error": str(exc), "entries": [], "total": 0}
