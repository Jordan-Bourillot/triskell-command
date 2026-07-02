"""Concierge disque + filet de sauvegarde GEO — passage quotidien.

Deux missions, nées de l'audit du 01/07/2026 :

1. NETTOYER LE DISQUE. Rien ne purgait jamais le volume persistant du
   serveur : fichiers de chasses (réécrits en entier tous les 5 prospects),
   exports CSV/XLSX jamais supprimés, sessions Argus… C'est le terreau des
   pannes « site qui ne répond plus » (disque plein → 503). On ne touche
   QUE des dossiers connus, avec des règles conservatrices :
     - exports (chasseur / prospecteur / créateurs / argus) : > 30 jours ;
     - fichiers de chasse TERMINÉS (done/error/stopped) : > 60 jours — les
       chasses finies sont déjà recopiées dans la base cloud (hunts_backup),
       on ne perd rien ; une chasse au statut actif n'est JAMAIS touchée ;
     - sessions Argus : > 30 jours.

2. METTRE LES DONNÉES GEO À L'ABRI. Tout le module GEO (sites, audits,
   suggestions, pages générées, réglages) vit dans le settings.json du
   volume serveur — en UN SEUL exemplaire. La procédure standard « disque
   plein » (docker system prune --volumes) peut détruire ce volume : sans
   copie cloud, tout le GEO disparaissait. On recopie donc la clé « geo »
   dans shared_settings (clé « geo_backup ») une fois par jour, et on la
   RESTAURE au boot si le volume est reparti de zéro.

Jamais bloquant : chaque étape est best-effort, une panne du concierge ne
doit gêner ni le serveur ni les chasses.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

APP_DIR = Path.home() / ".triskell-command"

# (dossier, âge minimum en jours) — UNIQUEMENT des dossiers d'artefacts
# régénérables. Ne jamais ajouter ici un dossier qui contient un état vivant.
_EXPORT_DIRS: tuple[tuple[str, int], ...] = (
    ("chasseur/exports", 30),
    ("prospecteur_google/exports", 30),
    ("chasseur_createurs/exports", 30),
    ("argus/exports", 30),
    ("argus/sessions", 30),
)

# Dossiers de fichiers de chasse : purge > 60 j, seulement si TERMINÉE.
_HUNT_DIRS: tuple[str, ...] = (
    "chasseur/hunts",
    "prospecteur_google/hunts",
    "chasseur_createurs/hunts",
)
_HUNT_TERMINAL_STATUSES = frozenset({"done", "error", "stopped", "cancelled"})

EXPORT_MAX_AGE_DAYS_DEFAULT = 30
HUNT_MAX_AGE_DAYS = 60
CYCLE_SECONDS = 24 * 3600
INITIAL_DELAY_SECONDS = 300          # laisse le boot respirer

GEO_BACKUP_KEY = "geo_backup"

_WORKER_STOP = threading.Event()
_WORKER_THREAD: threading.Thread | None = None
_LAST_RUN_AT = ""
_LAST_RUN_RESULT: dict = {}


# ---------------------------------------------------------------------------
# Nettoyage disque
# ---------------------------------------------------------------------------
def _delete_path(p: Path) -> int:
    """Supprime fichier ou dossier. Renvoie les octets libérés (estimés)."""
    freed = 0
    try:
        if p.is_dir():
            import shutil
            freed = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
            shutil.rmtree(p, ignore_errors=True)
        else:
            freed = p.stat().st_size
            p.unlink()
    except OSError as exc:
        logger.debug("disk_janitor delete %s: %s", p, exc)
        return 0
    return freed


def _older_than(p: Path, days: int, now: float) -> bool:
    try:
        return (now - p.stat().st_mtime) > days * 86400
    except OSError:
        return False


def _hunt_purgeable_data(path: Path) -> dict | None:
    """Renvoie les données de la chasse si elle est dans un état TERMINAL
    connu, None sinon. Illisible ou statut actif/inconnu → on ne touche
    pas (prudence)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if str(data.get("status") or "").lower() in _HUNT_TERMINAL_STATUSES:
            return data
    except Exception:
        pass
    return None


def sweep_disk() -> dict:
    """Un passage de ménage. Renvoie {deleted, freed_mb, details}."""
    now = time.time()
    deleted = 0
    freed = 0
    details: dict[str, int] = {}

    for rel, max_days in _EXPORT_DIRS:
        d = APP_DIR / rel
        if not d.is_dir():
            continue
        n = 0
        for p in d.iterdir():
            if _older_than(p, max_days, now):
                freed += _delete_path(p)
                n += 1
        if n:
            details[rel] = n
            deleted += n

    for rel in _HUNT_DIRS:
        d = APP_DIR / rel
        if not d.is_dir():
            continue
        tool = rel.split("/", 1)[0]
        n = 0
        for p in d.glob("*.json"):
            if not _older_than(p, HUNT_MAX_AGE_DAYS, now):
                continue
            data = _hunt_purgeable_data(p)
            if data is None:
                continue
            # On ne supprime qu'après CONFIRMATION de la copie cloud :
            # mirror_hunt est idempotent (upsert) et renvoie True seulement
            # si la ligne hunts_backup est écrite. Base injoignable ou
            # migration absente → la chasse attend le prochain passage.
            try:
                from .hunt_cloud_backup import mirror_hunt
                if not mirror_hunt(tool, data):
                    continue
            except Exception as exc:
                logger.debug("disk_janitor mirror avant purge %s: %s", p, exc)
                continue
            freed += _delete_path(p)
            n += 1
        if n:
            details[rel] = n
            deleted += n

    out = {"deleted": deleted, "freed_mb": round(freed / 1_048_576, 1),
           "details": details}
    if deleted:
        logger.info("disk_janitor : %d élément(s) purgé(s), %.1f Mo libérés (%s)",
                    deleted, out["freed_mb"], details)
    return out


# ---------------------------------------------------------------------------
# Filet GEO (copie cloud + restauration)
# ---------------------------------------------------------------------------
def _sb():
    try:
        from triskell_core.db import get_client, SupabaseNotConfigured
        try:
            c = get_client()
        except SupabaseNotConfigured:
            return None
        # Leçon smoke_sb_service_mode : toujours c.raw, jamais c._client.
        return c.raw if (c.service_mode or c.is_authenticated) else None
    except Exception as exc:
        logger.debug("disk_janitor _sb: %s", exc)
        return None


def _read_setting(sb, key: str) -> dict | None:
    try:
        rows = (sb.table("shared_settings").select("value")
                .eq("key", key).limit(1).execute().data) or []
        if not rows:
            return None
        value = rows[0].get("value")
        if isinstance(value, str):
            value = json.loads(value)
        return value if isinstance(value, dict) else None
    except Exception as exc:
        logger.debug("disk_janitor _read_setting(%s): %s", key, exc)
        return None


def mirror_geo(app_state) -> bool:
    """Recopie la clé « geo » de l'état serveur vers shared_settings.

    Deux générations sont gardées (geo_backup + geo_backup_prev) : si le
    volume serveur est reparti presque à vide et que la copie du jour
    écrase la bonne, celle de la veille reste récupérable."""
    try:
        geo = app_state.get("geo")
        if not isinstance(geo, dict) or not geo.get("sites"):
            return False        # rien à sauver (module GEO vide)
        sb = _sb()
        if sb is None:
            return False
        from .shared_settings_db import upsert_setting
        current = _read_setting(sb, GEO_BACKUP_KEY)
        if current and (current.get("geo") or {}).get("sites"):
            upsert_setting(sb, GEO_BACKUP_KEY + "_prev", current)
        payload = {
            "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "geo": geo,
        }
        ok = upsert_setting(sb, GEO_BACKUP_KEY, payload)
        if ok:
            logger.info("disk_janitor : copie cloud GEO à jour (%d site(s)).",
                        len(geo.get("sites") or []))
        return ok
    except Exception as exc:
        logger.warning("disk_janitor mirror_geo: %s", exc)
        return False


def restore_geo_if_missing(app_state) -> bool:
    """Au boot : si le volume est reparti de zéro (clé geo absente/vide)
    mais qu'une copie cloud existe, on restaure. Ne remplace JAMAIS des
    données locales existantes."""
    try:
        local = app_state.get("geo")
        if isinstance(local, dict) and local.get("sites"):
            return False        # données locales présentes → on n'y touche pas
        sb = _sb()
        if sb is None:
            return False
        value = _read_setting(sb, GEO_BACKUP_KEY)
        geo = (value or {}).get("geo")
        if not isinstance(geo, dict) or not geo.get("sites"):
            # Copie du jour absente/vide → on tente la génération d'avant.
            value = _read_setting(sb, GEO_BACKUP_KEY + "_prev")
            geo = (value or {}).get("geo")
        if not isinstance(geo, dict) or not geo.get("sites"):
            return False
        app_state.set("geo", value=geo)
        app_state.save()
        logger.warning("disk_janitor : données GEO RESTAURÉES depuis la copie "
                       "cloud du %s (%d site(s)) — le volume local était vide.",
                       value.get("saved_at", "?"), len(geo.get("sites") or []))
        return True
    except Exception as exc:
        logger.warning("disk_janitor restore_geo: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------
def _set_run(result: dict) -> None:
    global _LAST_RUN_AT, _LAST_RUN_RESULT
    _LAST_RUN_AT = datetime.now().isoformat(timespec="seconds")
    _LAST_RUN_RESULT = result


def get_status() -> dict:
    """Même forme que les autres robots (prêt pour la page Santé)."""
    return {
        "name": "disk_janitor",
        "label": "Concierge disque + filet GEO",
        "running": bool(_WORKER_THREAD and _WORKER_THREAD.is_alive()),
        "last_run_at": _LAST_RUN_AT,
        "last_run_result": _LAST_RUN_RESULT,
        # Un passage par jour : muet à partir de 30 h seulement.
        "stale_after_hours": 30.0,
    }


def _loop(app_state) -> None:
    # Restauration éventuelle dès le boot (avant le 1er versement GEO),
    # puis une copie cloud immédiate pour couvrir la journée en cours.
    try:
        restore_geo_if_missing(app_state)
        mirror_geo(app_state)
    except Exception as exc:
        logger.debug("disk_janitor boot: %s", exc)
    if _WORKER_STOP.wait(INITIAL_DELAY_SECONDS):
        return
    while not _WORKER_STOP.is_set():
        result: dict = {}
        try:
            result["sweep"] = sweep_disk()
        except Exception as exc:
            result["sweep_error"] = str(exc)[:200]
            logger.warning("disk_janitor sweep: %s", exc)
        try:
            # Retente la restauration tant que le local est vide (le boot a
            # pu passer avant que la base soit joignable), puis le miroir.
            result["geo_restored"] = restore_geo_if_missing(app_state)
            result["geo_mirror"] = mirror_geo(app_state)
        except Exception as exc:
            result["geo_error"] = str(exc)[:200]
        _set_run(result)
        if _WORKER_STOP.wait(CYCLE_SECONDS):
            return


def start_worker(app_state) -> None:
    """Démarre le concierge (idempotent, thread daemon)."""
    global _WORKER_THREAD
    if _WORKER_THREAD and _WORKER_THREAD.is_alive():
        return
    _WORKER_STOP.clear()
    _WORKER_THREAD = threading.Thread(
        target=_loop, args=(app_state,), name="disk-janitor", daemon=True)
    _WORKER_THREAD.start()
    logger.info("Concierge disque démarré (passage quotidien).")


def stop_worker() -> None:
    _WORKER_STOP.set()
