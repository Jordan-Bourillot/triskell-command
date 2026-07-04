"""Autopilot Runner — déclencheur nocturne du pipeline de prospection.

Worker thread daemon qui dort la nuit et lance `run_full_pipeline()` à
l'heure programmée si `PipelineConfig.enabled` est vrai. Conçu pour
tourner côté serveur (Coolify), pour que la prospection nocturne marche
même quand Triskell Command desktop n'est pas allumé.

Approche : un cycle de 5 min qui vérifie si on est dans la fenêtre
[3h, 4h] heure Europe/Paris (par défaut) ET que le dernier run de
prospection n'a pas eu lieu aujourd'hui (Paris). Si oui, lance le
pipeline complet et trace la date du run dans shared_settings.

État partagé `shared_settings.autopilot_nightly` :
    {"last_run_date": "YYYY-MM-DD", "last_run_at": "...iso..."}

Pour désactiver la programmation, il suffit de mettre `enabled=False`
dans la config de l'autopilote (Réglages ou bouton mode du cockpit).
"""

from __future__ import annotations

import logging
import threading
import time
from collections import namedtuple
from datetime import datetime, timedelta
from typing import Any, Optional

logger = logging.getLogger(__name__)


SHARED_KEY = "autopilot_nightly"
STAGE_MODES_KEY = "autopilot_stage_modes"  # poses par l'UI (etape 4 du chantier)
# Config de l'auto-pilote qui DOIT traverser site<->robots (depuis la
# separation TRISKELL_ROLE) : elle vit sinon dans pipeline.json local, absent
# du volume neuf de la boite robots -> auto-pilote muet. On la relit donc en
# base partagee et on l'applique par-dessus le pipeline.json local.
PIPELINE_CFG_KEY = "pipeline_config"
_SHARED_CFG_FIELDS = ("enabled", "autopilot_sender_pool", "autopilot_product",
                      "mode")
STAGE_MODES_DEFAULTS = {
    "search": "auto",
    "sort":   "auto",
    "write":  "auto",
    "review": "manual",
    "send":   "manual",
}
DEFAULT_HOUR_PARIS = 3                    # déclenchement à 3h du matin
WINDOW_MINUTES = 60                       # fenêtre [3h, 4h]
# Filet de securite (rattrapage) : si le creneau nocturne a ete manque
# (serveur redemarre/occupe a l'heure cible, Supabase ko...), on rattrape
# UNE fois jusqu'a cette heure (Paris), au lieu d'attendre la nuit suivante.
# Borne haute pour ne jamais envoyer en pleine apres-midi / soiree (mauvais
# pour la delivrabilite). Ne s'applique qu'aux creneaux nocturnes/matinaux.
CATCHUP_UNTIL_HOUR = 11
CYCLE_INTERVAL_SECONDS = 5 * 60           # check toutes les 5 min
INITIAL_DELAY_SECONDS = 120
# Au-dela de ce delai, un run reste a status="started" est considere comme
# orphelin (le processus a crashe sans rien finir, ou Supabase ko apres le
# write "started"). On l'ignore et on retombe sur le flow normal.
ORPHAN_STARTED_TIMEOUT_HOURS = 6

_WORKER_THREAD: Optional[threading.Thread] = None
_WORKER_STOP = threading.Event()
_WORKER_LOCK = threading.Lock()
_LAST_RUN_AT: str = ""
_LAST_RUN_RESULT: dict = {}

# Lock partage entre le worker nocturne et le bouton "Lancer maintenant" de
# l'API. Empeche les deux runs simultanes. Acquis en non-bloquant : si un run
# est deja en cours, l'autre refuse de partir.
_PIPELINE_RUN_LOCK = threading.Lock()
# Flag d'arret partage : set par autopilot_stop() cote API, lu en boucle par
# le callback _progress du worker nocturne (et de l'API). Quand True, le
# pipeline leve _AutopilotStopped a la prochaine emission de log (~1s).
_STOP_REQUESTED = threading.Event()


def acquire_run_lock() -> bool:
    """Tente d'acquerir le lock global de pipeline. Renvoie True si on a pris
    le lock (l'appelant doit relacher via release_run_lock() en fin de run),
    False si un autre run tourne deja."""
    return _PIPELINE_RUN_LOCK.acquire(blocking=False)


def release_run_lock() -> None:
    """Relache le lock acquis par acquire_run_lock()."""
    try:
        _PIPELINE_RUN_LOCK.release()
    except RuntimeError:
        # Deja relache, on ignore.
        pass


def is_pipeline_running() -> bool:
    """True si un pipeline (nocturne ou bouton) tourne actuellement."""
    # acquire non-bloquant : si on n'arrive pas a prendre = c'est qu'il
    # tourne ailleurs. Si on arrive a prendre, on relache aussitot.
    acquired = _PIPELINE_RUN_LOCK.acquire(blocking=False)
    if acquired:
        _PIPELINE_RUN_LOCK.release()
        return False
    return True


def request_stop() -> None:
    """Demande l'arret du pipeline en cours (nocturne ou via API). Le callback
    _progress leve _AutopilotStopped a la prochaine emission de log."""
    _STOP_REQUESTED.set()


def clear_stop() -> None:
    """Reset du flag stop (a appeler avant chaque debut de run)."""
    _STOP_REQUESTED.clear()


def is_stop_requested() -> bool:
    return _STOP_REQUESTED.is_set()


class NightlyStopped(Exception):
    """Levee par le callback _progress du worker nocturne quand un stop a
    ete demande via request_stop(). Interrompt run_full_pipeline proprement."""
    pass


# ---------------------------------------------------------------------------
def _now_paris() -> datetime:
    """Retourne l'heure actuelle dans le fuseau Europe/Paris."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Europe/Paris"))
    except Exception:
        # Fallback : heure locale (peut être UTC sur Coolify, on assume +0h
        # d'écart c'est acceptable, le run partira juste à 3h UTC = 5h Paris
        # en été, mais Jordan le sait via les logs).
        return datetime.now()


def _supabase_client():
    try:
        from triskell_core.db import get_client, SupabaseNotConfigured
        try:
            c = get_client()
        except SupabaseNotConfigured:
            return None
        return c if c.is_authenticated else None
    except Exception:
        return None


def _read_state() -> dict:
    sb = _supabase_client()
    if sb is None:
        return {}
    try:
        raw = sb.get_shared_setting(SHARED_KEY, {}) or {}
        return raw if isinstance(raw, dict) else {}
    except Exception as exc:
        logger.debug("autopilot_runner read_state: %s", exc)
        return {}


def _write_state(data: dict) -> None:
    sb = _supabase_client()
    if sb is None:
        return
    try:
        sb.set_shared_setting(SHARED_KEY, data)
    except Exception as exc:
        logger.debug("autopilot_runner write_state: %s", exc)


def _apply_shared_pipeline_overrides(cfg) -> list:
    """Applique la config auto-pilote de la BASE PARTAGEE par-dessus le cfg
    local (pipeline.json). Indispensable cote boite robots (volume neuf sans
    pipeline.json). Ne touche QUE les champs connus ; base injoignable ou clef
    absente -> cfg local inchange. Renvoie la liste des champs surchargés."""
    sb = _supabase_client()
    if sb is None:
        return []
    try:
        raw = sb.get_shared_setting(PIPELINE_CFG_KEY, {}) or {}
    except Exception as exc:
        logger.debug("autopilot_runner shared pipeline cfg: %s", exc)
        return []
    if not isinstance(raw, dict):
        return []
    applied = []
    for f in _SHARED_CFG_FIELDS:
        if f in raw and hasattr(cfg, f):
            try:
                setattr(cfg, f, raw[f])
                applied.append(f)
            except Exception:
                pass
    return applied


def _read_stage_modes() -> dict:
    """Lit les modes UI Auto/Manuel par maillon poses par le tableau de
    commande (etape 4 du chantier). Defauts si vide ou indisponible.
    """
    sb = _supabase_client()
    if sb is None:
        return dict(STAGE_MODES_DEFAULTS)
    try:
        raw = sb.get_shared_setting(STAGE_MODES_KEY, {}) or {}
    except Exception as exc:
        logger.debug("autopilot_runner read_stage_modes: %s", exc)
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    out = {}
    for k, default in STAGE_MODES_DEFAULTS.items():
        v = raw.get(k)
        out[k] = v if v in ("auto", "manual") else default
    return out


# ---------------------------------------------------------------------------
def _resolve_sender_pool_smtp(cfg, progress) -> dict:
    """Pour chaque entree du pool (autopilot_sender_pool), resout le dict
    SMTP via shared_secrets. Renvoie {account_id: smtp_cfg}.

    Les comptes sans config SMTP complete sont logges en WARN et exclus
    silencieusement (le pipeline les passera en draft pour ces tirages).
    """
    pool = list(getattr(cfg, "autopilot_sender_pool", None) or [])
    if not pool:
        return {}
    try:
        from triskell_command.integrations import shared_secrets
    except Exception as exc:
        progress(f"[WARN] shared_secrets indispo ({exc}) -> pool ignore.")
        return {}
    # Client Supabase optionnel (les helpers fonctionnent aussi avec
    # app_state local).
    client = _supabase_client()
    out: dict[str, dict] = {}
    missing: list[str] = []
    for entry in pool:
        if not isinstance(entry, dict):
            continue
        aid = str(entry.get("account_id") or "").strip()
        if not aid:
            continue
        try:
            acc = shared_secrets.get_account_by_id(aid, client=client)
        except Exception as exc:
            logger.debug("get_account_by_id(%s): %s", aid, exc)
            acc = None
        if not acc:
            missing.append(aid)
            continue
        required = ("smtp_host", "smtp_port", "smtp_user",
                    "smtp_password", "from_email")
        if any(not acc.get(k) for k in required):
            missing.append(aid)
            continue
        out[aid] = {
            "smtp_host":     acc.get("smtp_host"),
            "smtp_port":     int(acc.get("smtp_port") or 587),
            "smtp_user":     acc.get("smtp_user"),
            "smtp_password": acc.get("smtp_password"),
            "from_email":    acc.get("from_email"),
            "from_name":     acc.get("from_name", ""),
        }
    if missing:
        progress(
            f"[WARN] config SMTP manquante pour : {', '.join(missing)} "
            f"-> ces adresses seront ignorees pendant le run."
        )
    return out


# ---------------------------------------------------------------------------
def run_pipeline_with_ui_modes(cfg, progress):
    """Lance la chaine complete en respectant les interrupteurs UI.

    Logique commune entre le worker horaire (_do_one_tick) et le bouton
    'Lancer maintenant' (autopilot_run cote api.py), pour que les deux
    declenchements fassent exactement la meme chose.
    """
    from triskell_core.prospect.pipeline import run_full_pipeline

    # Config auto-pilote de la base partagée par-dessus le local (le pool
    # d'envoi surtout, sinon vide côté boîte robots au volume neuf).
    _ov = _apply_shared_pipeline_overrides(cfg)
    if _ov:
        progress(f"Config auto-pilote lue en base partagée ({', '.join(_ov)}).")

    # === Auto-detection des produits ACTIFS dans le catalogue ===
    # Jordan veut que l'autopilote pioche dans les produits actifs sans
    # qu'il ait a les selectionner un par un. On lit catalog_central et on
    # batit la liste combinee des templates de prospection de TOUS les
    # produits actifs. L'IA picker pourra alors choisir le bon template
    # (pro / creator / par produit) pour chaque prospect.
    templates_override: list[dict] | None = None
    try:
        from . import catalog_central
        from .prospection_templates import list_prospection_templates
        full = catalog_central.get_full() or {}
        active = [p for p in (full.get("products") or [])
                  if p.get("is_active") and p.get("id")]
        if active:
            combined: list[dict] = []
            active_labels: list[str] = []
            for prod in active:
                pid = str(prod.get("id") or "").strip()
                if not pid:
                    continue
                tmpls_creator = list_prospection_templates(pid, "creator") or []
                tmpls_pro     = list_prospection_templates(pid, "pro") or []
                tmpls_any     = []
                if not tmpls_creator and not tmpls_pro:
                    tmpls_any = list_prospection_templates(pid, "") or []
                tmpls = tmpls_creator + tmpls_pro + tmpls_any
                # Etiquete chaque template avec son produit pour aider l'IA
                for t in tmpls:
                    t = dict(t)
                    t["product"] = pid
                    t["product_label"] = prod.get("label") or pid
                    combined.append(t)
                if tmpls:
                    active_labels.append(f"{prod.get('label') or pid} ({len(tmpls)})")
            if combined:
                templates_override = combined
                progress(
                    f"Catalogue : {len(active)} produit(s) actif(s), "
                    f"{len(combined)} template(s) total ({', '.join(active_labels)})."
                )
            else:
                progress(
                    f"Catalogue : {len(active)} produit(s) actif(s) mais aucun "
                    f"template prospection trouve -> generation libre IA."
                )
    except Exception as exc:
        logger.debug("catalog auto-detect KO: %s", exc)
        progress(f"[WARN] auto-detection produits actifs KO ({exc}) -> "
                 f"fallback sur cfg.autopilot_product manuel.")

    # Lit les modes UI Auto/Manuel par maillon (poses par le tableau de
    # commande) et applique-les au pipeline.
    stage_modes = _read_stage_modes()
    # IMPORTANT : l'autopilote ne cherche JAMAIS de nouveaux prospects sur
    # internet ET n'enrichit JAMAIS les fiches existantes (= ne visite pas
    # leurs sites web). Il se contente d'utiliser les emails deja presents
    # dans le CRM. Pour chercher / enrichir, l'utilisateur passe par les
    # outils dedies : Chasseur / Eclaireur / Obelisk.
    do_search = False
    do_enrich = False
    # write=manual -> on ne genere pas de mails (donc do_send pipeline=False)
    do_send_stage = stage_modes["write"] == "auto"
    # send=manual -> on force mode validation (drafts au lieu d'envoi)
    if stage_modes["send"] == "manual" and cfg.mode == "auto":
        cfg.mode = "validation"
        progress(
            "Interrupteur Envoie=Manuel : mode pipeline force a "
            "'validation' (drafts au lieu d'envoi direct)."
        )
    # Relit=manual -> on desactive la 2e IA de relecture. Sentinelle -1 :
    # le pipeline traite 0/absent comme "vieille config" et restaure le
    # defaut 7 (filet anti-config-corrompue) -- avec 0, l'interrupteur
    # etait donc annule en silence et la relecture tournait quand meme.
    if stage_modes["review"] == "manual":
        cfg.autopilot_review_min_score = -1
        progress("Interrupteur Relit=Manuel : 2e IA de relecture desactivee.")

    progress(
        f"Lancement -- Cherche={stage_modes['search']} "
        f"Trie={stage_modes['sort']} Redige={stage_modes['write']} "
        f"Relit={stage_modes['review']} Envoie={stage_modes['send']} "
        f"(mode pipeline {cfg.mode}, produit "
        f"'{cfg.autopilot_product or '(libre)'}')..."
    )

    # === Montée automatique du volume (rampe par boîte) ===
    # Les boîtes marquées "ramp" dans le pool voient leur plafond 24h DU
    # JOUR calculé sur leur historique réel (sender_pool_tracker.apply_ramp) :
    # montée progressive palier par palier, frein automatique si pic de
    # rebonds. cfg est ajusté EN MÉMOIRE uniquement — la config stockée
    # garde les plafonds max et les réglages de rampe intacts.
    try:
        from . import sender_pool_tracker as _spt
        _ramp = _spt.apply_ramp(
            list(getattr(cfg, "autopilot_sender_pool", None) or []))
        if _ramp["details"]:
            cfg.autopilot_sender_pool = _ramp["pool"]
            for _d in _ramp["details"]:
                _brake_txt = (" -- FREIN rebonds actif" if _d["braked"] else "")
                progress(
                    f"Montee auto [{_d['account_id']}] : "
                    f"{_d['effective_cap']}/24h aujourd'hui "
                    f"(volume 30 j : {_d['sent_30d']}, palier {_d['step_cap']}, "
                    f"max regle {_d['max_cap']}){_brake_txt}"
                )
        elif not _ramp["ok"]:
            progress(f"[WARN] montee auto indisponible ({_ramp['reason']}) "
                     "-> plafonds manuels appliques tels quels.")
    except Exception as exc:
        logger.debug("apply_ramp KO: %s", exc)
        progress(f"[WARN] montee auto KO ({exc}) -> plafonds manuels.")

    # Resout les SMTP du pool (vide si pas de pool configure).
    sender_pool_smtp = _resolve_sender_pool_smtp(cfg, progress)

    return run_full_pipeline(
        cfg, progress=progress,
        do_search=do_search,
        do_enrich=do_enrich,
        do_send=do_send_stage,
        # Pas de relance automatique pour le moment : le seul mail de relance
        # codé en dur (tpe_relance_j5) parle d'un site et ne s'adapte pas aux
        # autres produits du catalogue. On rebranche plus tard avec un vrai
        # modèle de relance par produit.
        do_follow_up=False,
        sender_pool_smtp=sender_pool_smtp,
        templates_override=templates_override,
    )


# ---------------------------------------------------------------------------
def start_worker(app_state) -> bool:
    global _WORKER_THREAD
    with _WORKER_LOCK:
        if _WORKER_THREAD is not None and _WORKER_THREAD.is_alive():
            return True
        _WORKER_STOP.clear()
        t = threading.Thread(target=_loop, args=(app_state,),
                              name="AutopilotRunnerWorker", daemon=True)
        t.start()
        _WORKER_THREAD = t
    return True


def stop_worker() -> None:
    _WORKER_STOP.set()


def get_status() -> dict:
    return {
        "running":         _WORKER_THREAD is not None and _WORKER_THREAD.is_alive(),
        "last_run_at":     _LAST_RUN_AT,
        "last_run_result": dict(_LAST_RUN_RESULT),
    }


# ---------------------------------------------------------------------------
def _loop(app_state) -> None:
    if _WORKER_STOP.wait(INITIAL_DELAY_SECONDS):
        return
    while not _WORKER_STOP.is_set():
        try:
            _do_one_tick(app_state)
        except Exception as exc:
            logger.exception("autopilot_runner tick a planté")
            _LAST_RUN_RESULT.clear()
            _LAST_RUN_RESULT["error"] = str(exc)
        finally:
            globals()["_LAST_RUN_AT"] = datetime.now().isoformat(timespec="seconds")
        if _WORKER_STOP.wait(CYCLE_INTERVAL_SECONDS):
            return


_WindowDecision = namedtuple("_WindowDecision",
                             ["skip_reason", "catchup", "target_hour"])


def _window_decision(now_hour: int, target_hour: int,
                     already_today: bool) -> "_WindowDecision":
    """Decide si le run nocturne peut partir maintenant (fonction pure, testee
    par scripts/smoke_autopilot_catchup.py).

    Renvoie un _WindowDecision :
      - skip_reason : None si on peut lancer, sinon la raison du skip
        ('outside_window:...' ou 'already_ran_today') ;
      - catchup : True si c'est un rattrapage (creneau de la nuit manque,
        on repart en matinee au lieu d'attendre la nuit suivante) ;
      - target_hour : l'heure cible clampee dans [0..23].

    Regles :
      - Fenetre normale : l'heure pile configuree (ex 3h => 3h00..3h59).
      - Rattrapage : pas deja tourne aujourd'hui, creneau cible nocturne/
        matinal (avant CATCHUP_UNTIL_HOUR), et on est apres l'heure cible
        mais au plus tard a CATCHUP_UNTIL_HOUR. Borne haute = jamais d'envoi
        en pleine apres-midi / soiree (mauvais pour la delivrabilite).
    """
    target_hour = max(0, min(23, int(target_hour)))
    in_window = now_hour == target_hour
    in_catchup = (
        not already_today
        and target_hour < CATCHUP_UNTIL_HOUR
        and target_hour < now_hour <= CATCHUP_UNTIL_HOUR
    )
    if not (in_window or in_catchup):
        return _WindowDecision(
            f"outside_window:hour={now_hour} (target={target_hour}h)",
            False, target_hour)
    if already_today:
        return _WindowDecision("already_ran_today", False, target_hour)
    return _WindowDecision(None, in_catchup, target_hour)


def _do_one_tick(app_state) -> None:
    """Un seul cycle : décide si on doit lancer le pipeline."""
    # Charge la config de l'autopilote
    try:
        from triskell_core.prospect.pipeline import (
            PipelineConfig, run_full_pipeline,
        )
        cfg = PipelineConfig.load()
    except Exception as exc:
        logger.debug("autopilot_runner load config: %s", exc)
        _LAST_RUN_RESULT.clear()
        _LAST_RUN_RESULT["skipped_reason"] = f"config_unavailable:{exc}"
        return

    # Base partagée par-dessus le local (traverse site<->robots).
    _apply_shared_pipeline_overrides(cfg)

    if not getattr(cfg, "enabled", False):
        _LAST_RUN_RESULT.clear()
        _LAST_RUN_RESULT["skipped_reason"] = "disabled"
        return

    # Anti-double-traitement : si CE process n'est pas le serveur (app
    # desktop) et que le serveur bat encore, le run nocturne lui revient.
    try:
        from triskell_core.db import get_client, SupabaseNotConfigured
        from .server_presence import should_defer_to_server
        try:
            _presence_client = get_client()
        except SupabaseNotConfigured:
            _presence_client = None
        if should_defer_to_server(_presence_client):
            _LAST_RUN_RESULT.clear()
            _LAST_RUN_RESULT["skipped_reason"] = "server_active"
            return
    except Exception as exc:
        logger.debug("presence check: %s", exc)

    now = _now_paris()
    today_iso = now.date().isoformat()
    state = _read_state()

    # === Reprise automatique d'un run interrompu (ex: Coolify a redemarre
    # pendant le run nocturne suite a un push GitHub). Le pipeline est
    # idempotent (filet anti-doublon Supabase, etape 8.A) -- on peut le
    # relancer sans risque de double envoi. On detecte un run interrompu
    # par : status='started' qui n'a recu ni 'ok' ni 'failed', pour
    # AUJOURD'HUI. Si la date est plus ancienne, c'etait pour une autre
    # journee : on n'essaie pas de la rattraper.
    #
    # Garde-fou contre les "started" orphelins : si Supabase a ecrit
    # "started" mais que rien n'a jamais ecrit "ok" ou "failed" depuis plus
    # de ORPHAN_STARTED_TIMEOUT_HOURS, on considere le marqueur perime et
    # on l'ignore (sinon, en cas de panne Supabase repetee, on relancerait
    # en boucle "en reprise").
    started_at_raw = state.get("last_run_at") or ""
    started_too_old = False
    if started_at_raw:
        try:
            started_dt = datetime.fromisoformat(started_at_raw)
            # Si tz-naive, on compare en local (best-effort, pas grave)
            if started_dt.tzinfo is None:
                ref_now = datetime.now()
            else:
                ref_now = _now_paris()
            if ref_now - started_dt > timedelta(hours=ORPHAN_STARTED_TIMEOUT_HOURS):
                started_too_old = True
        except Exception:
            started_too_old = True
    interrupted = (
        state.get("last_run_status") == "started"
        and state.get("last_run_date") == today_iso
        and not started_too_old
    )

    if not interrupted:
        # Run normal (heure pile configuree) OU rattrapage matinal si le
        # creneau de la nuit a ete manque (serveur redemarre/occupe a 3h,
        # Supabase ko...). La decision est isolee dans _window_decision()
        # pour rester testable (scripts/smoke_autopilot_catchup.py).
        target_hour = int(getattr(cfg, "nightly_hour", DEFAULT_HOUR_PARIS)
                          or DEFAULT_HOUR_PARIS)
        already_today = state.get("last_run_date") == today_iso
        decision = _window_decision(now.hour, target_hour, already_today)
        if decision.skip_reason is not None:
            _LAST_RUN_RESULT.clear()
            _LAST_RUN_RESULT["skipped_reason"] = decision.skip_reason
            return
        if decision.catchup:
            logger.info(
                "[autopilot_nightly] RATTRAPAGE : creneau de %dh manque cette "
                "nuit, rattrapage a %dh (Paris) au lieu d'attendre demain.",
                decision.target_hour, now.hour,
            )

    # Anti-double-run : si un pipeline tourne deja (bouton "Lancer
    # maintenant" actif), on skip ce tick. Le pipeline reprendra au tick
    # suivant si on est encore dans la fenetre horaire.
    if not acquire_run_lock():
        _LAST_RUN_RESULT.clear()
        _LAST_RUN_RESULT["skipped_reason"] = "another_run_in_progress"
        return

    # Reset du flag stop avant de demarrer (au cas ou un ancien set traîne).
    clear_stop()

    # On y va : trace la tentative AVANT de lancer (anti-double si
    # redemarrage pendant l'execution).
    _write_state({
        "last_run_date":  today_iso,
        "last_run_at":    now.isoformat(timespec="seconds"),
        "last_run_status": "started",
        "last_run_resumed": interrupted,
    })

    log_lines: list[str] = []

    def _progress(msg) -> None:
        # Stop demande via API -> on coupe court. Le pipeline rattrapera
        # l'exception et terminera proprement (idempotent : ce qui a deja
        # ete envoye reste envoye, le reste est mis en draft ou perdu).
        if is_stop_requested():
            raise NightlyStopped("Arret demande pendant le run nocturne.")
        if isinstance(msg, dict):
            txt = msg.get("message") or ""
            if txt:
                log_lines.append(txt)
                logger.info("[autopilot_nightly] %s", txt)
            return
        log_lines.append(str(msg))
        logger.info("[autopilot_nightly] %s", msg)

    try:
        if interrupted:
            _progress(
                "REPRISE d'un run interrompu (Coolify redemarre pendant le "
                "run ?). Le pipeline est idempotent : pas de double envoi "
                "grace au filet anti-doublon Supabase."
            )

        stats = run_pipeline_with_ui_modes(cfg, _progress)
        _LAST_RUN_RESULT.clear()
        _LAST_RUN_RESULT.update({
            "searched":         getattr(stats, "searched", 0),
            "enriched":         getattr(stats, "enriched", 0),
            "drafts_sent":      getattr(stats, "drafts_sent", 0),
            "drafts_pending":   getattr(stats, "drafts_pending", 0),
            "replies_detected": getattr(stats, "replies_detected", 0),
            "errors":           list(getattr(stats, "errors", []) or []),
            "log_tail":         log_lines[-20:],
        })
        _write_state({
            "last_run_date":   today_iso,
            "last_run_at":     now.isoformat(timespec="seconds"),
            "last_run_status": "ok",
            "last_run_stats":  dict(_LAST_RUN_RESULT),
        })
    except NightlyStopped as exc:
        # Arret demande par l'utilisateur via le bouton Stop. On marque le
        # run comme termine (status=stopped) pour ne pas declencher la
        # logique de "reprise" au prochain tick.
        logger.info("autopilot_nightly run stoppe par l'utilisateur")
        _LAST_RUN_RESULT.clear()
        _LAST_RUN_RESULT["stopped"] = True
        _LAST_RUN_RESULT["log_tail"] = log_lines[-20:]
        _write_state({
            "last_run_date":   today_iso,
            "last_run_at":     now.isoformat(timespec="seconds"),
            "last_run_status": "stopped",
        })
    except Exception as exc:
        logger.exception("autopilot_nightly run a échoué")
        _LAST_RUN_RESULT.clear()
        _LAST_RUN_RESULT["error"] = str(exc)
        _LAST_RUN_RESULT["log_tail"] = log_lines[-20:]
        _write_state({
            "last_run_date":   today_iso,
            "last_run_at":     now.isoformat(timespec="seconds"),
            "last_run_status": "failed",
            "last_run_error":  str(exc),
        })
    finally:
        # Libere le lock global et reset le flag stop, quoi qu'il arrive.
        release_run_lock()
        clear_stop()
