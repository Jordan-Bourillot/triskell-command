"""Backup automatique des données critiques de l'app.

Tourne dans un thread background. Tous les 7 jours, exporte vers
~/.triskell-command/backups/YYYY-WNN.json un dump des données critiques :
- Modèles d'emails (mail_templates)
- Signatures
- Comptes mail (sans mots de passe)
- Notes Brain
- Projets clients (snapshot)
- Mails programmés en file
- Settings utilisateur (display_names, theme)

But : si Supabase tombe ou si on fait une fausse manip, on a TOUJOURS
une copie locale récente. Le serveur Docker monte /data en volume
persistant → les backups survivent aux redéploiements.

API : get_backups_list(), restore_backup(filename), run_backup_now().
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 6 * 60 * 60   # check toutes les 6h
BACKUP_INTERVAL_DAYS = 7               # rotation hebdo
MAX_BACKUPS_KEPT = 12                  # ~3 mois d'historique

_worker_thread: threading.Thread | None = None


def _backups_dir() -> Path:
    base = Path.home() / ".triskell-command" / "backups"
    try:
        base.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        logger.warning("backups dir: %s", exc)
    return base


def _last_backup_at() -> float:
    """Timestamp UNIX du dernier backup, ou 0 si jamais fait."""
    d = _backups_dir()
    if not d.exists():
        return 0.0
    latest = 0.0
    for f in d.glob("*.json"):
        try:
            mtime = f.stat().st_mtime
            if mtime > latest:
                latest = mtime
        except Exception:
            continue
    return latest


def _filename_for_now() -> str:
    """Nom de fichier basé sur l'année + numéro de semaine ISO."""
    now = datetime.now()
    iso_year, iso_week, _ = now.isocalendar()
    return f"backup-{iso_year}-W{iso_week:02d}.json"


def collect_snapshot(app_state) -> dict:
    """Assemble les données critiques en un seul dict."""
    snap = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "version": "v1",
    }

    # Settings locaux (theme, ai keys masked, outreach config sans mdp)
    try:
        from pathlib import Path
        settings_path = Path.home() / ".triskell-command" / "settings.json"
        if settings_path.exists():
            cfg = json.loads(settings_path.read_text(encoding="utf-8"))
            # Masque les secrets
            ai = cfg.get("ai") or {}
            keys = ai.get("api_keys") or {}
            ai["api_keys"] = {k: (v[:8] + "***" if v else "") for k, v in keys.items()}
            cfg["ai"] = ai
            outreach = cfg.get("outreach") or {}
            for secret_key in ("smtp_password", "imap_password"):
                if secret_key in outreach:
                    outreach[secret_key] = "***"
            cfg["outreach"] = outreach
            snap["settings"] = cfg
    except Exception as exc:
        logger.debug("backup settings: %s", exc)

    # Display names personnels (Jordan/Thomas)
    try:
        names_file = Path.home() / ".triskell-command" / "user_display_names.json"
        if names_file.exists():
            snap["display_names"] = json.loads(names_file.read_text(encoding="utf-8"))
    except Exception:
        pass

    # Mails programmés
    try:
        scheduled = Path.home() / ".triskell-command" / "scheduled_mails.json"
        if scheduled.exists():
            data = json.loads(scheduled.read_text(encoding="utf-8"))
            # Retire les attachments (lourds, pas critiques pour restauration)
            if isinstance(data, list):
                for entry in data:
                    if isinstance(entry, dict):
                        entry["attachments"] = f"({len(entry.get('attachments') or [])} attachments stripped from backup)"
            snap["scheduled_mails"] = data
    except Exception:
        pass

    # Données Supabase (best-effort)
    try:
        from . import shared_secrets
        from .. web.api import Api

        api = Api()
        api._app_state = app_state
        client = api._supabase()
        if client is not None:
            # Templates mail
            try:
                r = api.user_mail_templates_list()
                if r and r.get("ok"):
                    snap["mail_templates"] = r.get("templates") or []
            except Exception:
                pass
            # Signatures
            try:
                r = api.signatures_list()
                if r and r.get("ok"):
                    # Retire les body_html lourds pour rester compact
                    sigs = r.get("signatures") or []
                    snap["signatures"] = [
                        {**s, "body_html_size": len(s.get("body_html") or "")}
                        for s in sigs
                    ]
                    # Backup complet des signatures (avec HTML)
                    snap["signatures_full"] = sigs
            except Exception:
                pass
            # Comptes mail (sans mots de passe)
            try:
                r = api.mail_accounts_list()
                if r and r.get("ok"):
                    snap["mail_accounts"] = [
                        {k: v for k, v in (acc.items() if isinstance(acc, dict) else [])
                         if "password" not in k.lower()}
                        for acc in (r.get("accounts") or [])
                    ]
            except Exception:
                pass
            # Brain notes
            try:
                from . import brain
                notes = brain.list_notes(status="all", limit=500, client=client) or []
                snap["brain_notes"] = notes
            except Exception:
                pass
            # Clients (snapshot)
            try:
                from . import clients_repo
                groups = clients_repo.list_grouped()
                snap["client_projects"] = groups
            except Exception:
                pass
            # PROSPECTS (refonte 2026-06) : c'est le capital commercial —
            # il n'était PAS sauvegardé (uniquement chez Supabase). Dump
            # complet hebdo pour pouvoir tout reconstruire en cas de pépin.
            try:
                rows = (client.raw.table("prospects").select("*")
                        .limit(20000).execute().data or [])
                snap["prospects"] = rows
                snap["prospects_count"] = len(rows)
            except Exception as exc:
                logger.debug("backup prospects: %s", exc)
    except Exception as exc:
        logger.debug("backup supabase: %s", exc)

    return snap


def run_now(app_state) -> dict:
    """Force un backup immédiat. Renvoie {ok, path, size_bytes}."""
    try:
        snap = collect_snapshot(app_state)
        path = _backups_dir() / _filename_for_now()
        payload = json.dumps(snap, ensure_ascii=False, indent=2, default=str)
        path.write_text(payload, encoding="utf-8")
        # Rotation : garde les N plus récents
        _rotate_backups()
        logger.info("Backup écrit : %s (%d ko)", path.name, len(payload) // 1024)
        return {"ok": True, "path": str(path), "size_bytes": len(payload),
                "filename": path.name}
    except Exception as exc:
        logger.exception("backup_runner.run_now")
        return {"ok": False, "error": str(exc)}


def _rotate_backups():
    """Garde les MAX_BACKUPS_KEPT plus récents, supprime les autres."""
    try:
        d = _backups_dir()
        files = sorted(d.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
        for old in files[MAX_BACKUPS_KEPT:]:
            try:
                old.unlink()
                logger.info("Backup rotated out : %s", old.name)
            except Exception:
                pass
    except Exception as exc:
        logger.debug("rotate: %s", exc)


def list_backups() -> list[dict]:
    """Liste les backups disponibles, triés du plus récent au plus ancien."""
    out = []
    d = _backups_dir()
    if not d.exists():
        return out
    for f in sorted(d.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            st = f.stat()
            out.append({
                "filename": f.name,
                "size_bytes": st.st_size,
                "ts": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(timespec="seconds"),
            })
        except Exception:
            continue
    return out


def read_backup(filename: str) -> dict | None:
    """Lit le contenu d'un backup par nom de fichier (pour aperçu / restauration)."""
    if not filename or "/" in filename or ".." in filename or "\\" in filename:
        return None   # paranoïa path traversal
    p = _backups_dir() / filename
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("read_backup: %s", exc)
        return None


def start_worker(app_state):
    """Lance le thread background. Idempotent."""
    global _worker_thread
    if _worker_thread is not None and _worker_thread.is_alive():
        return

    def loop():
        logger.info("backup_runner: démarré (check %dh)", CHECK_INTERVAL_SECONDS // 3600)
        # Délai initial : 5 min après le boot pour pas perturber le démarrage
        time.sleep(300)
        while True:
            try:
                last = _last_backup_at()
                age_days = (time.time() - last) / 86400 if last else 999
                if age_days >= BACKUP_INTERVAL_DAYS:
                    result = run_now(app_state)
                    if result.get("ok"):
                        logger.info("Backup hebdo OK : %s", result.get("filename"))
                    else:
                        logger.warning("Backup hebdo KO : %s", result.get("error"))
            except Exception as exc:
                logger.exception("backup_runner loop: %s", exc)
            time.sleep(CHECK_INTERVAL_SECONDS)

    _worker_thread = threading.Thread(target=loop, name="backup_runner", daemon=True)
    _worker_thread.start()
