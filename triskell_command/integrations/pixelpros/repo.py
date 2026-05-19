"""DAO Supabase pour les demandes client Pixel Pros.

Pattern aligné sur `integrations/lagriffe/repo.py` mais adapté à la table
`pp_client_drafts` (schéma défini dans pixel-studio/supabase/schema.sql).

Workflow Pixel Pros (plus court que Lagriffe — pas de validation manuelle) :

    draft  →  paid  →  building  →  live   (succès)
                                  →  failed (à relancer)

Étapes :
  - draft     : le client a rempli le formulaire mais pas (encore) payé
  - paid      : Stripe a confirmé le paiement (webhook stripe-webhook.ts)
  - building  : le builder Python tourne sur le draft
  - live      : le site est en ligne sur {slug}.pixel-pros.fr
  - failed    : le build a échoué — Jordan peut relancer
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_SERVICE_CLIENT = None
_SERVICE_CLIENT_TRIED = False

TABLE = "pp_client_drafts"


# ---------------------------------------------------------------------------
# Connexion Supabase (même pattern que lagriffe)
# ---------------------------------------------------------------------------
def _load_service_config() -> Optional[dict]:
    """Renvoie {url, service_role_key} ou None.

    Cherche d'abord dans les variables d'env (utilisé en CI / serveur), puis
    dans ~/.triskell-command/settings.json (config locale du desktop).
    """
    url = os.environ.get("PIXEL_PROS_SUPABASE_URL") or os.environ.get("SUPABASE_URL")
    key = (
        os.environ.get("PIXEL_PROS_SUPABASE_SERVICE_KEY")
        or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        or os.environ.get("SUPABASE_SERVICE_KEY")
    )
    if url and key:
        return {"url": url, "service_role_key": key}

    settings_path = Path.home() / ".triskell-command" / "settings.json"
    if settings_path.exists():
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
            # On accepte une sous-section "pixel_pros" dédiée pour bien
            # isoler la connexion (le projet Supabase Pixel Pros peut être
            # différent de celui des autres studios).
            pp = data.get("pixel_pros") or {}
            url = pp.get("supabase_url") or pp.get("url") or ""
            key = pp.get("supabase_service_key") or pp.get("service_role_key") or ""
            if url and key:
                return {"url": url, "service_role_key": key}

            # Fallback : la conf Supabase générique
            sb = data.get("supabase") or {}
            url = sb.get("url") or ""
            key = sb.get("service_role_key") or sb.get("service_key") or ""
            if url and key:
                return {"url": url, "service_role_key": key}
        except Exception as exc:
            logger.debug("pixelpros._load_service_config: %s", exc)
    return None


def _service_sb():
    global _SERVICE_CLIENT, _SERVICE_CLIENT_TRIED
    if _SERVICE_CLIENT is not None:
        return _SERVICE_CLIENT
    if _SERVICE_CLIENT_TRIED:
        return None
    _SERVICE_CLIENT_TRIED = True

    cfg = _load_service_config()
    if cfg is None:
        return None
    try:
        from supabase import create_client
    except ImportError:
        logger.warning("supabase-py introuvable — pip install supabase")
        return None
    try:
        _SERVICE_CLIENT = create_client(cfg["url"], cfg["service_role_key"])
    except Exception as exc:
        logger.warning("pixelpros._service_sb: %s", exc)
        return None
    return _SERVICE_CLIENT


def _user_sb():
    try:
        from triskell_core.db import get_client, SupabaseNotConfigured
    except ImportError:
        return None
    try:
        c = get_client()
    except SupabaseNotConfigured:
        return None
    if not c.is_authenticated:
        return None
    return getattr(c, "client", None) or getattr(c, "_client", None)


def _sb():
    return _service_sb() or _user_sb()


# ---------------------------------------------------------------------------
# Lecture
# ---------------------------------------------------------------------------
# Alias 'intake' = 'draft' pour rester aligné sur le vocabulaire Triskell.

def list_intakes(*, status: Optional[str] = None, limit: int = 50) -> list[dict]:
    """Liste les drafts Pixel Pros, optionnellement filtrés par status."""
    sb = _sb()
    if sb is None:
        return []
    try:
        q = sb.table(TABLE).select("*").order("created_at", desc=True).limit(limit)
        if status:
            q = q.eq("status", status)
        return q.execute().data or []
    except Exception as exc:
        logger.warning("pixelpros.list_intakes: %s", exc)
        return []


def get_intake(intake_id: str) -> Optional[dict]:
    sb = _sb()
    if sb is None:
        return None
    try:
        rows = (sb.table(TABLE).select("*")
                .eq("id", intake_id).limit(1).execute().data)
        return rows[0] if rows else None
    except Exception as exc:
        logger.warning("pixelpros.get_intake: %s", exc)
        return None


def count_by_status() -> dict[str, int]:
    """Renvoie le nombre de drafts pour chaque status connu."""
    keys = ["draft", "paid", "building", "live", "failed"]
    out = {k: 0 for k in keys}
    sb = _sb()
    if sb is None:
        return out
    try:
        for k in keys:
            r = (sb.table(TABLE).select("id", count="exact", head=True)
                 .eq("status", k).execute())
            out[k] = int(getattr(r, "count", 0) or 0)
    except Exception as exc:
        logger.warning("pixelpros.count_by_status: %s", exc)
    return out


# ---------------------------------------------------------------------------
# Écriture (status, error_message)
# ---------------------------------------------------------------------------
def update_intake_status(intake_id: str, new_status: str, *, error_message: str = "") -> bool:
    """Bascule un draft vers un nouveau status (building | live | failed)."""
    sb = _sb()
    if sb is None:
        return False
    patch: dict[str, Any] = {
        "status": new_status,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    # Le schéma pp_client_drafts a un trigger qui maintient updated_at, mais
    # on l'envoie explicitement au cas où.
    if error_message:
        # Pas de colonne error_message sur pp_client_drafts pour l'instant :
        # on l'enregistre dans le champ data.error pour ne pas perdre l'info.
        patch_data = (get_intake(intake_id) or {}).get("data") or {}
        if not isinstance(patch_data, dict):
            patch_data = {}
        patch_data["error"] = error_message
        patch["data"] = patch_data

    try:
        sb.table(TABLE).update(patch).eq("id", intake_id).execute()
        return True
    except Exception as exc:
        logger.warning("pixelpros.update_intake_status: %s", exc)
        return False


def mark_building(intake_id: str) -> bool:
    """Marque le draft comme en cours de construction (avant de lancer le builder)."""
    return update_intake_status(intake_id, "building")


def mark_live(intake_id: str, *, site_url: str) -> bool:
    """Marque le draft comme live, enregistre l'URL finale du site."""
    sb = _sb()
    if sb is None:
        return False
    patch = {
        "status": "live",
        "site_url": site_url,
        "site_built_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        sb.table(TABLE).update(patch).eq("id", intake_id).execute()
        return True
    except Exception as exc:
        logger.warning("pixelpros.mark_live: %s", exc)
        return False


def mark_failed(intake_id: str, *, error_message: str = "") -> bool:
    """Marque le draft comme failed (le build a échoué)."""
    return update_intake_status(intake_id, "failed",
                                 error_message=error_message or "Build échoué")


# ---------------------------------------------------------------------------
# Déclenchement du build
# ---------------------------------------------------------------------------
def dispatch_build(intake_id: str) -> tuple[bool, str]:
    """Déclenche immédiatement le builder Python pour un draft 'paid'.

    Approche locale (privilégiée) : exécute `python builder/build_site.py
    --draft-id <id>` en subprocess dans le dossier pixel-studio. Suppose
    qu'on tourne sur la machine de Jordan (Triskell Command desktop).

    Approche distante (fallback) : si une URL `PP_TRIGGER_BUILD_URL` est
    configurée (variable d'env), POST le draft_id à cette URL — utile si
    le builder tourne sur Coolify ou un autre serveur.

    Renvoie (success, message).
    """
    # 1) Tentative locale via subprocess
    pixel_studio = _find_pixel_studio_dir()
    if pixel_studio is not None:
        return _dispatch_local(pixel_studio, intake_id)

    # 2) Fallback HTTP
    trigger_url = os.environ.get("PP_TRIGGER_BUILD_URL")
    trigger_token = os.environ.get("PP_TRIGGER_BUILD_TOKEN")
    if trigger_url:
        return _dispatch_remote(trigger_url, trigger_token, intake_id)

    return False, (
        "Builder introuvable : ni le dossier pixel-studio local, "
        "ni PP_TRIGGER_BUILD_URL ne sont configurés."
    )


def _find_pixel_studio_dir() -> Optional[Path]:
    """Cherche le dossier pixel-studio dans les emplacements habituels."""
    candidates = [
        Path.home() / "Triskell" / "pixel-studio",
        Path.home() / "triskell" / "pixel-studio",
        Path("/Users/jorda/Triskell/pixel-studio"),
        Path("/c/Users/jorda/Triskell/pixel-studio"),
        Path(r"C:\Users\jorda\Triskell\pixel-studio"),
    ]
    # Variable d'env explicite si Jordan veut surcharger
    env_path = os.environ.get("PIXEL_PROS_REPO_PATH")
    if env_path:
        candidates.insert(0, Path(env_path))

    for p in candidates:
        if p.exists() and (p / "builder" / "build_site.py").exists():
            return p
    return None


def _dispatch_local(pixel_studio: Path, intake_id: str) -> tuple[bool, str]:
    import subprocess
    import sys
    builder = pixel_studio / "builder" / "build_site.py"
    try:
        proc = subprocess.Popen(
            [sys.executable, str(builder), "--draft-id", intake_id],
            cwd=str(pixel_studio),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        # On NE bloque pas : le build peut prendre 1-2 minutes. On marque
        # juste comme 'building' et on laisse tourner. La vue UI rafraîchira
        # le status quand le builder finira et écrira 'live' ou 'failed' lui-même.
        mark_building(intake_id)
        return True, f"Build lancé localement (PID {proc.pid}). Le builder mettra le status à 'live' ou 'failed' à la fin."
    except Exception as exc:
        return False, f"Échec lancement subprocess : {exc}"


def _dispatch_remote(url: str, token: Optional[str], intake_id: str) -> tuple[bool, str]:
    import requests
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        r = requests.post(url, json={"draftId": intake_id}, headers=headers, timeout=30)
        if r.ok:
            mark_building(intake_id)
            return True, "Build déclenché côté serveur."
        return False, f"HTTP {r.status_code}: {r.text[:200]}"
    except Exception as exc:
        return False, str(exc)


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------
def intake_timeline(intake_id: str) -> list[dict]:
    """Chronologie d'un draft à partir des colonnes horodatées."""
    intake = get_intake(intake_id)
    if intake is None:
        return []
    events: list[dict] = []

    def _push(kind: str, ts: Optional[str], label: str):
        if ts:
            events.append({"kind": kind, "ts": ts, "label": label})

    _push("submitted", intake.get("created_at"), "Formulaire soumis (draft)")
    _push("paid",      intake.get("stripe_paid_at"),
          f"Paiement Stripe reçu · session {intake.get('stripe_session_id') or '?'}")
    _push("built",     intake.get("site_built_at"),
          f"Site construit → {intake.get('site_url') or '(URL absente)'}")
    if intake.get("status") == "failed":
        err = (intake.get("data") or {}).get("error", "(sans message)")
        _push("error", intake.get("updated_at"), f"Build échoué : {err}")

    events.sort(key=lambda e: e["ts"] or "")
    events.append({
        "kind": "current",
        "ts": intake.get("updated_at") or intake.get("created_at"),
        "label": f"Status courant : {intake.get('status')}",
    })
    return events
