"""Missions de prospection — UNE commande pour TOUTE la chaîne.

Le problème : lancer une prospection complète demandait 3 outils et des
clics manuels (lancer une chasse → attendre → cliquer « Ajouter à mes
prospects » → vérifier l'Auto-pilote). Chaque maillon marchait, mais
l'enchaînement reposait sur l'humain.

Une MISSION, c'est : « démarche-moi des plombiers du 71 » en un clic.
Derrière, le chef de gare (mission_runner) fait avancer la chaîne :

   1. CHERCHE  — lance la chasse adaptée (Chasseur / Prospecteur Google /
                 Obélisk selon la cible)
   2. VERSE    — à la fin de la chasse, pousse AUTOMATIQUEMENT les
                 prospects avec mail dans la base partagée (dédoublonnés,
                 jamais un client, jamais un désinscrit)
   3. TRANSMET — donne un coup d'épaule à l'Auto-pilote s'il est allumé
                 (sinon : les prospects attendent sagement dans la base)
   4. (la suite — rédaction, relecture, envoi, réponses — est l'affaire
      de l'Auto-pilote et des robots existants)

Les missions sont stockées dans `shared_settings` (clé
"prospection_missions") → visibles par Jordan ET Thomas, et elles
survivent aux redémarrages. La machine à états est PURE (avance_mission)
pour être testable sans réseau.
"""
from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

SHARED_KEY = "prospection_missions"
MAX_MISSIONS = 50

# Cibles possibles d'une mission → quel outil fait la recherche
SOURCES = ("pme", "local", "createurs")
SOURCE_LABELS = {
    "pme": "PME françaises (registre officiel)",
    "local": "Commerces locaux (Google Maps)",
    "createurs": "Créateurs (YouTube, Twitch…)",
}

# Statuts d'une mission (cycle de vie)
ST_HUNTING = "hunting"      # la chasse tourne
ST_HANDING = "handing"      # chasse finie → versement dans la base
ST_HANDED = "handed"        # prospects dans la base, Auto-pilote prévenu
ST_ERROR = "error"
ST_CANCELLED = "cancelled"
ACTIVE_STATUSES = (ST_HUNTING, ST_HANDING)

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
# Stockage (shared_settings) — lecture/écriture de la liste
# ---------------------------------------------------------------------------
def load_missions(client=None) -> list[dict]:
    c = client or _client()
    if c is None:
        return []
    try:
        raw = c.get_shared_setting(SHARED_KEY, []) or []
        return raw if isinstance(raw, list) else []
    except Exception as exc:
        logger.debug("load_missions: %s", exc)
        return []


def save_missions(missions: list[dict], client=None) -> bool:
    c = client or _client()
    if c is None:
        return False
    try:
        # Les plus récentes d'abord, liste plafonnée
        missions = sorted(missions, key=lambda m: m.get("created_at") or "",
                          reverse=True)[:MAX_MISSIONS]
        c.set_shared_setting(SHARED_KEY, missions)
        return True
    except Exception as exc:
        logger.warning("save_missions: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Démarrage d'une mission — lance la chasse du bon outil
# ---------------------------------------------------------------------------
def start_hunt_for(source: str, params: dict) -> dict:
    """Lance la recherche adaptée. Renvoie {ok, hunt_ref, label} ou {ok:False,error}."""
    params = params or {}
    try:
        if source == "pme":
            from . import chasseur
            target = int(params.get("volume") or 100)
            hunt = chasseur.start_hunt(
                sector=(params.get("metier") or "").strip(),
                zone={k: v for k, v in {
                    "departement": (params.get("departement") or "").strip(),
                    "code_postal": (params.get("code_postal") or "").strip(),
                }.items() if v},
                target=max(10, min(target, 500)),
                with_email_only=True,
                mode=("poor_sites" if params.get("sites_pourris") else "all"),
            )
            return {"ok": True, "hunt_ref": hunt.id, "label": hunt.label}

        if source == "local":
            from . import prospecteur_google
            target = int(params.get("volume") or 60)
            hunt = prospecteur_google.start_hunt(
                metier=(params.get("metier") or "").strip(),
                zone=(params.get("zone") or "").strip(),
                num_results=max(10, min(target, 200)),
                only_no_site=bool(params.get("sans_site")),
                pays=(params.get("pays") or "FR").strip() or "FR",
            )
            return {"ok": True, "hunt_ref": hunt.id, "label": hunt.label}

        if source == "createurs":
            from .obelisk import runner as obelisk_runner
            niche = (params.get("niche") or "").strip()
            platforms = params.get("plateformes") or ["youtube"]
            if not isinstance(platforms, list):
                platforms = [str(platforms)]
            target = int(params.get("volume") or 30)
            r = obelisk_runner.start_search(
                user_email=(params.get("user_email") or "").strip(),
                niche=niche,
                platforms=[str(p).strip().lower() for p in platforms if p],
                max_per_platform=max(5, min(target, 100)),
            )
            if not r.get("ok"):
                return r
            label = f"Créateurs · {niche} · {', '.join(platforms)}"
            return {"ok": True, "hunt_ref": r["job_id"], "label": label}

        return {"ok": False, "error": f"cible inconnue : {source}"}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        logger.exception("start_hunt_for %s", source)
        return {"ok": False, "error": str(exc)}


def create_mission(source: str, params: dict, *, created_by: str = "",
                   dry_run: bool = False, client=None) -> dict:
    """Crée + démarre une mission. Renvoie {ok, mission} ou {ok:False,error}.

    dry_run (test à blanc) : la recherche tourne pour de vrai (c'est le
    but — vérifier la qualité de ce qu'elle ramène), mais RIEN n'est
    écrit dans la base et l'Auto-pilote n'est pas prévenu. À la place,
    la mission produit un rapport : combien seraient versés, combien de
    nouveaux/fusions, quels écarts qualité, avec un échantillon.
    """
    if source not in SOURCES:
        return {"ok": False, "error": f"cible inconnue : {source}"}
    if dry_run and source == "createurs":
        return {"ok": False, "error":
                "Le test à blanc n'existe pas pour les créateurs : Obélisk "
                "écrit directement dans la base pendant sa recherche. "
                "Lance plutôt une vraie mission avec un petit volume (10)."}
    started = start_hunt_for(source, params)
    if not started.get("ok"):
        return started
    mission = {
        "id": uuid.uuid4().hex[:12],
        "created_at": _now(),
        "updated_at": _now(),
        "created_by": created_by or "",
        "source": source,
        "label": (("🧪 " if dry_run else "")
                  + (started.get("label") or SOURCE_LABELS.get(source, source))),
        "params": params or {},
        "dry_run": bool(dry_run),
        "hunt_ref": started["hunt_ref"],
        "status": ST_HUNTING,
        "error": "",
        "counts": {"found": 0, "with_email": 0, "pushed": 0,
                   "created": 0, "merged": 0},
        "autopilot": {"kicked": False, "note": ""},
    }
    with _LOCK:
        missions = load_missions(client)
        missions.append(mission)
        if not save_missions(missions, client):
            return {"ok": False,
                    "error": "mission lancée mais impossible de l'enregistrer "
                             "(base injoignable) — la chasse tourne quand même"}
    return {"ok": True, "mission": mission}


# ---------------------------------------------------------------------------
# Lecture de l'état d'une chasse (adaptateurs par outil)
# ---------------------------------------------------------------------------
def hunt_state_for(source: str, hunt_ref: str) -> dict:
    """État normalisé : {status, progress, found, with_email, error}."""
    try:
        if source == "pme":
            from . import chasseur
            h = chasseur.Hunt.load(hunt_ref)
            if not h:
                return {"status": "error", "error": "chasse introuvable"}
            stats = h.stats or {}
            return {"status": h.status, "progress": h.progress or 0,
                    "found": int(stats.get("retenus") or len(h.prospects or [])),
                    "with_email": int(stats.get("avec_mail") or 0),
                    "error": h.error or ""}
        if source == "local":
            from . import prospecteur_google
            h = prospecteur_google.ProspectHunt.load(hunt_ref)
            if not h:
                return {"status": "error", "error": "chasse introuvable"}
            stats = h.stats or {}
            return {"status": h.status, "progress": h.progress or 0,
                    "found": int(stats.get("retenus") or len(h.prospects or [])),
                    "with_email": int(stats.get("avec_mail") or 0),
                    "error": h.error or ""}
        if source == "createurs":
            from .obelisk import repo as obelisk_repo
            r = obelisk_repo.get_search_job(hunt_ref)
            if not r.get("ok"):
                return {"status": "error",
                        "error": r.get("error") or "job introuvable"}
            job = r.get("job") or {}
            stats = job.get("stats") or {}
            status = (job.get("status") or "").lower()
            # Normalise les statuts obélisk → vocabulaire mission
            if status in ("pending", "running"):
                status = "searching"
            found = int(stats.get("found") or stats.get("created")
                        or stats.get("total") or 0)
            return {"status": status, "progress": int(job.get("progress") or 0),
                    "found": found,
                    "with_email": int(stats.get("with_email") or 0),
                    "error": job.get("error") or ""}
    except Exception as exc:
        logger.debug("hunt_state_for %s/%s : %s", source, hunt_ref, exc)
        return {"status": "unknown", "error": str(exc)}
    return {"status": "error", "error": f"cible inconnue : {source}"}


def push_for(source: str, hunt_ref: str) -> Optional[dict]:
    """Verse les prospects de la chasse dans la base partagée.

    Renvoie le résultat {ok, pushed, created, merged, quality} — ou None
    si la source écrit déjà directement dans la base (Obélisk).
    L'upsert est dédoublonné → rejouable sans risque.
    """
    if source == "createurs":
        return None  # Obélisk écrit directement dans la base partagée
    if source == "pme":
        from . import chasseur
        return chasseur.push_to_autopilot(hunt_ref)
    if source == "local":
        from . import prospecteur_google
        return prospecteur_google.push_to_prospects(hunt_ref)
    return {"ok": False, "error": f"cible inconnue : {source}"}


def _load_hunt_prospects(source: str, hunt_ref: str) -> tuple[list[dict], str]:
    """Charge les prospects bruts d'une chasse. Renvoie (liste, clé_nom)."""
    if source == "pme":
        from . import chasseur
        h = chasseur.Hunt.load(hunt_ref)
        return (h.prospects if h else []), "nom"
    if source == "local":
        from . import prospecteur_google
        h = prospecteur_google.ProspectHunt.load(hunt_ref)
        return (h.prospects if h else []), "name"
    return [], "nom"


def dry_push_for(source: str, hunt_ref: str, client=None) -> dict:
    """SIMULATION de versement — n'écrit RIEN, dit ce qui se passerait.

    1. Passe la fournée au contrôle qualité (mêmes règles que le réel).
    2. Pour chaque fiche valide (100 max), regarde si l'email existe déjà
       dans la base → « fusion » sinon « nouveau ».
    3. Renvoie {ok, would_push, would_create, would_merge, quality,
       sample: [..5 fiches..]}.
    """
    prospects, name_key = _load_hunt_prospects(source, hunt_ref)
    if not prospects:
        return {"ok": True, "would_push": 0, "would_create": 0,
                "would_merge": 0, "quality": {"total": 0, "kept": 0,
                                               "dropped": {}}, "sample": []}
    from .data_quality import filter_for_push
    kept, quality = filter_for_push(prospects, email_key="email",
                                     name_key=name_key)
    c = client or _client()
    would_create = would_merge = 0
    sample: list[dict] = []
    capped = kept[:100]
    for p in capped:
        email = (p.get("email") or "").strip().lower()
        exists = False
        if c is not None and email:
            try:
                res = (c.raw.table("prospects").select("id", count="exact")
                       .contains("emails", [email]).limit(1).execute())
                exists = bool(res.count)
            except Exception:
                pass
        if exists:
            would_merge += 1
        else:
            would_create += 1
        if len(sample) < 5:
            sample.append({
                "nom": (p.get(name_key) or p.get("name") or "")[:60],
                "email": email[:80],
                "sort": "fusion avec une fiche existante" if exists
                        else "nouvelle fiche",
            })
    # Au-delà du plafond d'analyse, on compte le reste en « nouveaux »
    # estimés (annoncé tel quel dans la note).
    rest = max(0, len(kept) - len(capped))
    return {"ok": True,
            "would_push": len(kept),
            "would_create": would_create + rest,
            "would_merge": would_merge,
            "analyzed": len(capped), "estimated_rest": rest,
            "quality": quality, "sample": sample}


# ---------------------------------------------------------------------------
# Machine à états — PURE (providers injectés) pour être testable
# ---------------------------------------------------------------------------
def advance_mission(mission: dict, *,
                    hunt_state: Callable[[str, str], dict],
                    push: Callable[[str, str], Optional[dict]],
                    kick_autopilot: Callable[[], tuple[bool, str]],
                    dry_push: Callable[[str, str], dict] | None = None,
                    ) -> tuple[dict, bool]:
    """Fait avancer UNE mission d'un cran si possible.

    Renvoie (mission_mise_à_jour, a_changé). Ne lève jamais.
    """
    m = dict(mission)
    changed = False
    try:
        if m.get("status") == ST_HUNTING:
            st = hunt_state(m.get("source") or "", m.get("hunt_ref") or "")
            status = (st.get("status") or "").lower()
            counts = dict(m.get("counts") or {})
            new_found = int(st.get("found") or 0)
            new_mail = int(st.get("with_email") or 0)
            if (new_found != counts.get("found")
                    or new_mail != counts.get("with_email")):
                counts["found"] = new_found
                counts["with_email"] = new_mail
                m["counts"] = counts
                changed = True
            m["progress"] = int(st.get("progress") or 0)
            if status == "done":
                m["status"] = ST_HANDING
                changed = True
            elif status == "error":
                m["status"] = ST_ERROR
                m["error"] = (st.get("error")
                              or "la recherche s'est arrêtée en erreur")
                changed = True

        if m.get("status") == ST_HANDING and m.get("dry_run"):
            # TEST À BLANC : on simule le versement, on n'écrit RIEN,
            # et l'Auto-pilote n'est pas prévenu.
            fn = dry_push or (lambda s, r: {"ok": False,
                                             "error": "simulation indisponible"})
            res = fn(m.get("source") or "", m.get("hunt_ref") or "")
            counts = dict(m.get("counts") or {})
            if res.get("ok"):
                counts["pushed"] = 0
                counts["would_push"] = int(res.get("would_push") or 0)
                counts["would_create"] = int(res.get("would_create") or 0)
                counts["would_merge"] = int(res.get("would_merge") or 0)
                m["quality"] = res.get("quality") or {}
                m["preview"] = res.get("sample") or []
                m["autopilot"] = {"kicked": False,
                                  "note": "simulation — rien n'est entré "
                                          "dans la base, rien n'a été envoyé"}
                m["status"] = ST_HANDED
            else:
                m["status"] = ST_ERROR
                m["error"] = (f"simulation impossible : "
                              f"{res.get('error') or '?'}")
            m["counts"] = counts
            m["updated_at"] = _now()
            return m, True

        if m.get("status") == ST_HANDING:
            res = push(m.get("source") or "", m.get("hunt_ref") or "")
            counts = dict(m.get("counts") or {})
            if res is None:
                # Source qui écrit directement dans la base (Obélisk)
                counts["pushed"] = counts.get("found") or 0
            elif res.get("ok"):
                counts["pushed"] = int(res.get("pushed") or 0)
                counts["created"] = int(res.get("created") or 0)
                counts["merged"] = int(res.get("merged") or 0)
                if res.get("quality"):
                    m["quality"] = res["quality"]
            else:
                err = (res.get("error") or "").strip()
                # « aucun prospect avec mail » n'est pas une panne : la
                # chasse n'a juste rien ramené d'exploitable.
                if "aucun" in err.lower():
                    counts["pushed"] = 0
                else:
                    m["status"] = ST_ERROR
                    m["error"] = f"versement dans la base impossible : {err}"
                    m["counts"] = counts
                    return m, True
            m["counts"] = counts
            kicked, note = kick_autopilot()
            m["autopilot"] = {"kicked": bool(kicked), "note": note or ""}
            m["status"] = ST_HANDED
            changed = True
    except Exception as exc:
        logger.exception("advance_mission %s", m.get("id"))
        m["status"] = ST_ERROR
        m["error"] = str(exc)
        changed = True
    if changed:
        m["updated_at"] = _now()
    return m, changed


def default_kick_autopilot() -> tuple[bool, str]:
    """Donne un coup d'épaule à l'Auto-pilote (même chemin que le bouton
    « Lancer maintenant » → respecte les interrupteurs et le verrou)."""
    try:
        from triskell_core.prospect.pipeline import PipelineConfig
        if not PipelineConfig.load().enabled:
            return False, ("Auto-pilote éteint — les prospects attendent "
                           "dans la base (allume-le pour qu'il écrive)")
    except Exception:
        return False, "état de l'Auto-pilote inconnu"
    try:
        from ..web.api import get_api_instance
        api = get_api_instance()
        if api is None:
            return False, "serveur en cours de démarrage"
        r = api.autopilot_run(None)
        if r.get("ok"):
            return True, "Auto-pilote lancé sur la base"
        err = (r.get("error") or "").strip()
        if "déjà en cours" in err or "nocturne" in err:
            return True, "Auto-pilote déjà au travail"
        return False, err or "lancement refusé"
    except Exception as exc:
        logger.debug("kick autopilot: %s", exc)
        return False, str(exc)


def tick(client=None) -> dict:
    """Un passage du chef de gare : avance toutes les missions actives."""
    out = {"scanned": 0, "advanced": 0, "errors": 0}
    with _LOCK:
        missions = load_missions(client)
        if not missions:
            return out
        new_list = []
        any_change = False
        for m in missions:
            if m.get("status") in ACTIVE_STATUSES:
                out["scanned"] += 1
                m2, changed = advance_mission(
                    m,
                    hunt_state=hunt_state_for,
                    push=push_for,
                    kick_autopilot=default_kick_autopilot,
                    dry_push=lambda s, r: dry_push_for(s, r, client=client),
                )
                if changed:
                    any_change = True
                    out["advanced"] += 1
                    if m2.get("status") == ST_ERROR:
                        out["errors"] += 1
                new_list.append(m2)
            else:
                new_list.append(m)
        if any_change:
            save_missions(new_list, client)
    return out


def cancel_mission(mission_id: str, client=None) -> dict:
    with _LOCK:
        missions = load_missions(client)
        found = False
        for m in missions:
            if m.get("id") == mission_id:
                if m.get("status") in ACTIVE_STATUSES:
                    m["status"] = ST_CANCELLED
                    m["updated_at"] = _now()
                found = True
                break
        if not found:
            return {"ok": False, "error": "mission introuvable"}
        save_missions(missions, client)
    return {"ok": True}
