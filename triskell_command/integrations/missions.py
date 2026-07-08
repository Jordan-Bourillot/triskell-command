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

# ---------------------------------------------------------------------------
# Reprise automatique (demande Jordan 13/06/2026) : un redéploiement du
# serveur tue les threads de chasse — la mission ne doit PAS finir en
# erreur pour autant. Quand la chasse meurt pour une cause « technique »
# (interruption serveur, fichier de chasse disparu avec le conteneur),
# la mission RELANCE la même recherche toute seule et continue. Le
# versement final dédoublonne : repartir de zéro ne crée jamais de
# doublon. Plafonné pour qu'une vraie panne ne tourne pas en boucle.
# ---------------------------------------------------------------------------
MAX_AUTO_RELAUNCHES = 2
RESCUE_WINDOW_HOURS = 24    # repêchage des missions tuées AVANT ce déploiement

# Messages d'erreur de chasse qui signifient « interruption technique »
# (jamais une vraie panne métier type clé API manquante).
_RESUMABLE_MARKERS = (
    "interrompue par un redémarrage",   # hunt_zombies.ZOMBIE_ERROR_MESSAGE
    "recherche interrompue",            # obelisk.repo._ZOMBIE_JOB_MSG
    "chasse introuvable",               # fichier parti avec l'ancien conteneur
    "job introuvable",                  # équivalent Obélisk
)


def _is_resumable_hunt_error(err: str) -> bool:
    e = (err or "").lower()
    return any(marker in e for marker in _RESUMABLE_MARKERS)


def _try_relaunch(mission: dict, relaunch) -> bool:
    """Relance la chasse d'une mission interrompue. Mute la mission et
    renvoie True si la reprise est partie, False sinon (cap atteint ou
    relance impossible). Ne lève jamais."""
    m = mission
    relaunches = int(m.get("relaunches") or 0)
    if relaunches >= MAX_AUTO_RELAUNCHES or relaunch is None:
        return False
    try:
        r = relaunch(m.get("source") or "", m.get("params") or {})
    except Exception as exc:
        logger.warning("relaunch mission %s: %s", m.get("id"), exc)
        r = {"ok": False, "error": str(exc)}
    if not (r or {}).get("ok"):
        return False
    m["hunt_ref"] = r["hunt_ref"]
    m["relaunches"] = relaunches + 1
    m["status"] = ST_HUNTING
    m["error"] = ""
    m["resume_note"] = (f"↻ Chasse reprise automatiquement après une "
                        f"interruption du serveur "
                        f"({m['relaunches']}/{MAX_AUTO_RELAUNCHES})")
    m["updated_at"] = _now()
    return True

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
        ordered = sorted(missions, key=lambda m: m.get("created_at") or "",
                         reverse=True)
        if len(ordered) > MAX_MISSIONS:
            # On garde TOUJOURS les missions encore actives (chasse en cours
            # ou versement en attente) : sans ça, une mission active mais
            # ancienne était éjectée en silence et ses prospects n'étaient
            # jamais versés. Le plafond ne rogne que les missions terminées.
            active = [m for m in ordered if m.get("status") in ACTIVE_STATUSES]
            finished = [m for m in ordered if m.get("status") not in ACTIVE_STATUSES]
            keep_finished = finished[:max(0, MAX_MISSIONS - len(active))]
            dropped = len(finished) - len(keep_finished)
            if dropped:
                logger.info("save_missions : %d mission(s) terminée(s) "
                            "écartée(s) du plafond (%d actives conservées).",
                            dropped, len(active))
            kept = active + keep_finished
            # Recompose dans l'ordre récent-d'abord.
            missions = sorted(kept, key=lambda m: m.get("created_at") or "",
                              reverse=True)
        else:
            missions = ordered
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
            # Garde-fou : sans métier NI zone, la chasse ratisserait toute
            # la France — refus clair plutôt qu'une mission monstre.
            if not ((params.get("metier") or "").strip()
                    or (params.get("departement") or "").strip()
                    or (params.get("code_postal") or "").strip()):
                return {"ok": False, "error":
                        "Précise au moins un métier OU un département "
                        "(sinon je chasserais toute la France)."}
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
                   dry_run: bool = False, force: bool = False,
                   client=None) -> dict:
    """Crée + démarre une mission. Renvoie {ok, mission} ou {ok:False,error}.

    dry_run (test à blanc) : la recherche tourne pour de vrai (c'est le
    but — vérifier la qualité de ce qu'elle ramène), mais RIEN n'est
    écrit dans la base et l'Auto-pilote n'est pas prévenu. À la place,
    la mission produit un rapport : combien seraient versés, combien de
    nouveaux/fusions, quels écarts qualité, avec un échantillon.

    Carnet de chasse (demande Jordan 13/06/2026) : si la MÊME recherche
    (mêmes critères, accents/majuscules ignorés) a déjà été lancée en
    réel, on ne relance pas en silence → {ok:False, needs_confirm:True,
    warning} avec la date et la récolte de la fois d'avant. force=True
    (l'utilisateur a confirmé) passe outre. Les tests à blanc ne sont
    ni avertis ni notés. Une panne du carnet ne bloque JAMAIS la chasse.
    """
    params = dict(params or {})
    # Tolérance : certains appelants glissent force dans params.
    force = bool(force or params.pop("force", False))
    if source not in SOURCES:
        return {"ok": False, "error": f"cible inconnue : {source}"}
    if dry_run and source == "createurs":
        return {"ok": False, "error":
                "Le test à blanc n'existe pas pour les créateurs : Obélisk "
                "écrit directement dans la base pendant sa recherche. "
                "Lance plutôt une vraie mission avec un petit volume (10)."}
    if not dry_run and not force:
        try:
            from . import hunt_log
            prev = hunt_log.find(source, params, client=client)
        except Exception as exc:
            logger.debug("create_mission carnet: %s", exc)
            prev = None
        if prev:
            warning = ""
            try:
                from . import hunt_log
                warning = hunt_log.warning_for(prev)
            except Exception:
                warning = "Cette recherche a déjà été faite."
            return {"ok": False, "needs_confirm": True,
                    # error AUSSI : les anciens fronts affichent r.error →
                    # message lisible partout, même sans gestion dédiée.
                    "error": warning, "warning": warning,
                    "previous": {"label": prev.get("label") or "",
                                  "last_at": prev.get("last_at") or "",
                                  "runs": int(prev.get("runs") or 1),
                                  "status": prev.get("status") or "",
                                  "result": prev.get("result")}}
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
    if not dry_run:
        # Trace durable dans le carnet de chasse (best-effort).
        try:
            from . import hunt_log
            hunt_log.record_launch(source, params, mission["id"],
                                   client=client)
        except Exception as exc:
            logger.debug("create_mission record_launch: %s", exc)
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
            # Normalise les statuts obélisk → vocabulaire mission.
            # ⚠️ Obélisk dit « failed » (jamais « error ») pour un job mort :
            # sans cette traduction, la mission restait « en chasse » pour
            # toujours après un redéploiement (audit du 01/07/2026).
            if status in ("pending", "running"):
                status = "searching"
            elif status == "failed":
                status = "error"
            found = int(stats.get("found") or stats.get("created")
                        or stats.get("total") or 0)
            # ⚠️ Chez Obélisk, `progress` est une LISTE de lignes de journal,
            # pas un pourcentage. int(liste) levait TypeError → attrapée par
            # le except global → statut « unknown » → la mission restait
            # « en chasse » POUR TOUJOURS, même chasse finie (vécu 08/07 :
            # job done en 28 s, mission figée 40 min sans erreur visible).
            prog_raw = job.get("progress")
            if isinstance(prog_raw, (int, float)):
                prog = int(prog_raw)
            elif status == "done":
                prog = 100
            elif isinstance(prog_raw, list):
                # Heuristique douce : le journal grossit avec l'avancement.
                prog = min(95, 5 * len(prog_raw))
            else:
                prog = 0
            return {"status": status, "progress": prog,
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
                    relaunch: Callable[[str, dict], dict] | None = None,
                    ) -> tuple[dict, bool]:
    """Fait avancer UNE mission d'un cran si possible.

    relaunch (optionnel) : appelé (source, params) quand la chasse meurt
    pour une cause technique (serveur redémarré, fichier disparu) — la
    mission repart en chasse au lieu de finir en erreur (plafonné).

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
                err = (st.get("error")
                       or "la recherche s'est arrêtée en erreur")
                # Interruption technique → on relance la même recherche
                # au lieu d'abandonner (le versement final dédoublonne).
                if _is_resumable_hunt_error(err) and _try_relaunch(m, relaunch):
                    return m, True
                m["status"] = ST_ERROR
                m["error"] = err
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
    per_run = 0
    try:
        from triskell_core.prospect.pipeline import PipelineConfig
        cfg = PipelineConfig.load()
        if not cfg.enabled:
            return False, ("Auto-pilote éteint — les prospects attendent "
                           "dans la base (allume-le pour qu'il écrive)")
        per_run = int(getattr(cfg, "nightly_target", 0) or 0)
    except Exception:
        return False, "état de l'Auto-pilote inconnu"
    try:
        from ..web.api import get_api_instance
        api = get_api_instance()
        if api is None:
            return False, "serveur en cours de démarrage"
        r = api.autopilot_run(None)
        if r.get("ok"):
            # Le rythme dans la note — pas de surprise « j'ai versé 100
            # prospects, pourquoi 5 brouillons ? » (parce que 5 par passage).
            if per_run > 0:
                return True, (f"Auto-pilote lancé — il écrit par paquets de "
                              f"{per_run} mails, à valider dans Brouillons")
            return True, "Auto-pilote lancé sur la base"
        err = (r.get("error") or "").strip()
        if "déjà en cours" in err or "nocturne" in err:
            return True, "Auto-pilote déjà au travail"
        return False, err or "lancement refusé"
    except Exception as exc:
        logger.debug("kick autopilot: %s", exc)
        return False, str(exc)


def rescue_interrupted(missions: list[dict], *, relaunch,
                       now: Optional[datetime] = None) -> tuple[list[dict], int]:
    """Repêche les missions tuées par un redémarrage AVANT que la reprise
    automatique n'existe (ou pendant que le serveur était éteint) :
    statut erreur + cause technique + récentes → on relance leur chasse.

    Pure (relaunch injecté, horloge injectable) pour être testable.
    Renvoie (missions_mises_à_jour, nb_repêchées).
    """
    now = now or datetime.now(timezone.utc)
    rescued = 0
    out = []
    for m in missions:
        m = dict(m)
        if (m.get("status") == ST_ERROR
                and _is_resumable_hunt_error(m.get("error") or "")):
            ts_raw = m.get("updated_at") or m.get("created_at") or ""
            recent = False
            try:
                ts = datetime.fromisoformat(ts_raw)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                recent = (now - ts).total_seconds() < RESCUE_WINDOW_HOURS * 3600
            except Exception:
                recent = False
            if recent and _try_relaunch(m, relaunch):
                rescued += 1
        out.append(m)
    return out, rescued


def tick(client=None) -> dict:
    """Un passage du chef de gare : avance toutes les missions actives."""
    out = {"scanned": 0, "advanced": 0, "errors": 0, "rescued": 0}
    with _LOCK:
        missions = load_missions(client)
        if not missions:
            return out
        # Repêchage : les missions interrompues par un redémarrage
        # repartent en chasse au lieu de rester « en erreur ».
        missions, rescued = rescue_interrupted(missions,
                                               relaunch=start_hunt_for)
        if rescued:
            out["rescued"] = rescued
            save_missions(missions, client)
            missions = load_missions(client)
        new_list = []
        any_change = False
        done_for_log = []
        for m in missions:
            if m.get("status") in ACTIVE_STATUSES:
                out["scanned"] += 1
                m2, changed = advance_mission(
                    m,
                    hunt_state=hunt_state_for,
                    push=push_for,
                    kick_autopilot=default_kick_autopilot,
                    dry_push=lambda s, r: dry_push_for(s, r, client=client),
                    relaunch=start_hunt_for,
                )
                if changed:
                    any_change = True
                    out["advanced"] += 1
                    if m2.get("status") == ST_ERROR:
                        out["errors"] += 1
                    # Mission réelle arrivée au bout (versée ou en erreur)
                    # → récolte notée dans le carnet de chasse.
                    if (not m2.get("dry_run")
                            and m2.get("status") in (ST_HANDED, ST_ERROR)):
                        done_for_log.append(m2)
                new_list.append(m2)
            else:
                new_list.append(m)
        if any_change:
            save_missions(new_list, client)
    for m2 in done_for_log:  # hors verrou : le carnet a le sien
        try:
            from . import hunt_log
            hunt_log.record_result(m2, client=client)
        except Exception as exc:
            logger.debug("tick record_result: %s", exc)
    return out


def cancel_mission(mission_id: str, client=None) -> dict:
    cancelled = None
    with _LOCK:
        missions = load_missions(client)
        found = False
        for m in missions:
            if m.get("id") == mission_id:
                if m.get("status") in ACTIVE_STATUSES:
                    m["status"] = ST_CANCELLED
                    m["updated_at"] = _now()
                    cancelled = m
                found = True
                break
        if not found:
            return {"ok": False, "error": "mission introuvable"}
        save_missions(missions, client)
    if cancelled is not None and not cancelled.get("dry_run"):
        try:
            from . import hunt_log
            hunt_log.record_result(cancelled, client=client)
        except Exception as exc:
            logger.debug("cancel record_result: %s", exc)
    return {"ok": True}
