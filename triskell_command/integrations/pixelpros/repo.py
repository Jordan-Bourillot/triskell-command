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
import mimetypes
import os
import secrets
import time
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


def update_intake_contact(intake_id: str, *, email: str | None = None,
                          phone: str | None = None) -> tuple[bool, str]:
    """Met à jour les champs contact (email / phone) dans data.

    Passer None pour un champ = on n'y touche pas. Passer une chaîne vide
    = on retire le champ (revient à la valeur par défaut "—").
    """
    sb = _sb()
    if sb is None:
        return False, "Supabase non configuré."
    intake = get_intake(intake_id)
    if intake is None:
        return False, "Intake introuvable."
    data = intake.get("data") or {}
    if not isinstance(data, dict):
        data = {}
    if email is not None:
        clean = email.strip()
        if clean:
            data["email"] = clean
        else:
            data.pop("email", None)
    if phone is not None:
        clean = phone.strip()
        if clean:
            data["phone"] = clean
        else:
            data.pop("phone", None)
    patch = {
        "data": data,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        sb.table(TABLE).update(patch).eq("id", intake_id).execute()
        return True, "Contact mis à jour."
    except Exception as exc:
        logger.warning("pixelpros.update_intake_contact: %s", exc)
        return False, str(exc)


def mark_paid_manual(intake_id: str) -> tuple[bool, str]:
    """Override manuel : passe un draft directement au statut 'paid' sans
    attendre le webhook Stripe.

    Utile pour :
      - tester le pipeline sans payer
      - encaisser un paiement hors-Stripe (virement, chèque, espèces)
      - réparer un draft où le webhook Stripe a échoué
      - faire un geste commercial

    Pose stripe_paid_at = maintenant pour que la timeline reste cohérente.
    Ne déclenche PAS le mail "paiement reçu" automatiquement — Jordan peut
    le renvoyer manuellement depuis le détail si besoin.
    """
    sb = _sb()
    if sb is None:
        return False, "Supabase non configuré."
    now_iso = datetime.now(timezone.utc).isoformat()
    patch = {
        "status": "paid",
        "stripe_paid_at": now_iso,
        "updated_at": now_iso,
    }
    try:
        sb.table(TABLE).update(patch).eq("id", intake_id).execute()
        return True, "Marqué comme payé manuellement."
    except Exception as exc:
        logger.warning("pixelpros.mark_paid_manual: %s", exc)
        return False, str(exc)


def delete_intake(intake_id: str) -> tuple[bool, str]:
    """Supprime définitivement un draft Pixel Pros.

    Utile pour nettoyer les formulaires de test ou les commandes
    abandonnées (status='draft' qui n'ont jamais été payées).

    Appelle la RPC pp_delete_draft côté Supabase. Nécessite que le secret
    PP_WEBHOOK_SECRET soit configuré dans les variables d'env (même secret
    que celui en DB dans pp_secrets).
    """
    sb = _sb()
    if sb is None:
        return False, "Supabase non configuré côté Triskell Command."
    secret = os.environ.get("PP_WEBHOOK_SECRET") or ""
    if not secret:
        # Fallback : peut-être que c'est dans settings.json sous pixel_pros
        try:
            settings_path = Path.home() / ".triskell-command" / "settings.json"
            if settings_path.exists():
                data = json.loads(settings_path.read_text(encoding="utf-8"))
                pp = data.get("pixel_pros") or {}
                secret = pp.get("webhook_secret") or pp.get("pp_webhook_secret") or ""
        except Exception:
            secret = ""
    if not secret:
        return False, (
            "PP_WEBHOOK_SECRET introuvable (ni en env var, ni dans "
            "settings.json[pixel_pros].webhook_secret)."
        )
    try:
        result = sb.rpc("pp_delete_draft", {
            "p_draft_id": intake_id,
            "p_webhook_secret": secret,
        }).execute()
        # La RPC retourne true si supprimé, false sinon
        ok = bool(result.data)
        if ok:
            return True, "Brouillon supprimé."
        return False, "Brouillon introuvable (déjà supprimé ?)."
    except Exception as exc:
        logger.warning("pixelpros.delete_intake: %s", exc)
        return False, str(exc)


# ---------------------------------------------------------------------------
# Édition des données du formulaire + gestion des photos
# ---------------------------------------------------------------------------
PHOTO_BUCKET = "pp-client-photos"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def update_intake_data(intake_id: str, patch: dict) -> tuple[bool, str]:
    """Met à jour des champs du formulaire (colonne data) d'un intake.

    `patch` = dict {clé: valeur}. Les clés fournies remplacent celles de
    data ; une valeur None retire la clé. Les colonnes dédiées email /
    business_name sont resynchronisées si elles changent (cohérence des
    listes et des cartes Kanban qui lisent ces colonnes).
    """
    sb = _sb()
    if sb is None:
        return False, "Supabase non configuré."
    if not isinstance(patch, dict) or not patch:
        return False, "Rien à modifier."
    intake = get_intake(intake_id)
    if intake is None:
        return False, "Intake introuvable."
    data = intake.get("data") or {}
    if not isinstance(data, dict):
        data = {}
    for key, value in patch.items():
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value
    row: dict[str, Any] = {"data": data, "updated_at": _now_iso()}
    bn = patch.get("business-name") or patch.get("business_name")
    if bn:
        row["business_name"] = bn
    if patch.get("email"):
        row["email"] = patch["email"]
    try:
        sb.table(TABLE).update(row).eq("id", intake_id).execute()
        return True, "Modifications enregistrées."
    except Exception as exc:
        logger.warning("pixelpros.update_intake_data: %s", exc)
        return False, str(exc)


def _photo_public_url(path: str) -> str:
    """URL publique d'un objet du bucket pp-client-photos (bucket public)."""
    cfg = _load_service_config() or {}
    base = (cfg.get("url") or os.environ.get("PIXEL_PROS_SUPABASE_URL")
            or os.environ.get("SUPABASE_URL") or "").rstrip("/")
    if base:
        return f"{base}/storage/v1/object/public/{PHOTO_BUCKET}/{path}"
    return ""


def add_photo(intake_id: str, kind: str, *, filename: str,
              content: bytes) -> tuple[bool, str, Optional[dict]]:
    """Envoie une image dans le bucket et l'ajoute à la colonne photos.

    kind : hero-photo | about-photo | gallery | logo (le « type » de photo).
    Renvoie (ok, message, objet_photo).
    """
    sb = _sb()
    if sb is None:
        return False, "Supabase non configuré.", None
    if not content:
        return False, "Fichier vide.", None
    kind = (kind or "photo").strip() or "photo"
    ext = ""
    if filename and "." in filename:
        ext = filename.rsplit(".", 1)[-1].lower()
    if not ext or len(ext) > 5 or not ext.isalnum():
        ext = "jpg"
    ts = int(time.time() * 1000)
    rand = secrets.token_hex(3)
    path = f"{intake_id}/{kind}-{ts}-{rand}.{ext}"
    mime = mimetypes.guess_type(filename or f"x.{ext}")[0] or "image/jpeg"
    try:
        sb.storage.from_(PHOTO_BUCKET).upload(
            path=path,
            file=content,
            file_options={"content-type": mime, "upsert": "false"},
        )
    except Exception as exc:
        logger.warning("pixelpros.add_photo upload: %s", exc)
        return False, f"Envoi de l'image échoué : {exc}", None

    photo = {
        "url": _photo_public_url(path),
        "kind": kind,
        "path": path,
        "original_name": filename or "",
    }
    intake = get_intake(intake_id) or {}
    photos = intake.get("photos") or []
    if not isinstance(photos, list):
        photos = []
    photos.append(photo)
    try:
        sb.table(TABLE).update(
            {"photos": photos, "updated_at": _now_iso()}
        ).eq("id", intake_id).execute()
    except Exception as exc:
        logger.warning("pixelpros.add_photo db: %s", exc)
        return False, f"Image envoyée mais non enregistrée : {exc}", None
    return True, "Photo ajoutée.", photo


def delete_photo(intake_id: str, path: str) -> tuple[bool, str]:
    """Retire une photo : du bucket (best-effort) et de la colonne photos."""
    sb = _sb()
    if sb is None:
        return False, "Supabase non configuré."
    if not path:
        return False, "Chemin de photo manquant."
    intake = get_intake(intake_id)
    if intake is None:
        return False, "Intake introuvable."
    photos = intake.get("photos") or []
    if not isinstance(photos, list):
        photos = []
    new_photos = [p for p in photos if (p or {}).get("path") != path]
    try:
        sb.storage.from_(PHOTO_BUCKET).remove([path])
    except Exception as exc:
        # Le fichier a pu déjà disparaître : on n'échoue pas la requête.
        logger.warning("pixelpros.delete_photo storage: %s", exc)
    try:
        sb.table(TABLE).update(
            {"photos": new_photos, "updated_at": _now_iso()}
        ).eq("id", intake_id).execute()
        return True, "Photo supprimée."
    except Exception as exc:
        logger.warning("pixelpros.delete_photo db: %s", exc)
        return False, str(exc)


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
    """Cherche le dossier pixel-studio (local), ou le clone si introuvable.

    Sur Coolify (volume /data), le repo n'est pas baked dans l'image (privé).
    On le clone à la demande en utilisant GITHUB_TOKEN ; les appels suivants
    feront juste un git pull pour rester à jour.

    Renvoie None si :
      - pas de dossier local ET pas de GITHUB_TOKEN pour cloner.
    """
    candidates = [
        Path.home() / "Triskell" / "pixel-studio",
        Path.home() / "triskell" / "pixel-studio",
        Path("/Users/jorda/Triskell/pixel-studio"),
        Path("/c/Users/jorda/Triskell/pixel-studio"),
        Path(r"C:\Users\jorda\Triskell\pixel-studio"),
    ]
    # Variable d'env explicite (sert aussi de cible pour le clone runtime)
    env_path = os.environ.get("PIXEL_PROS_REPO_PATH")
    if env_path:
        candidates.insert(0, Path(env_path))

    # 1) Si on a déjà un clone valide quelque part, on l'utilise (+ git pull)
    for p in candidates:
        if p.exists() and (p / "builder" / "build_site.py").exists():
            _git_pull(p)
            return p

    # 2) Sinon, on tente de cloner dans PIXEL_PROS_REPO_PATH (env) avec le token
    target = Path(env_path) if env_path else Path("/data/pixel-studio")
    if _git_clone_pixel_studio(target):
        return target
    return None


def _git_clone_pixel_studio(target: Path) -> bool:
    """Clone pixel-studio dans `target` en utilisant GITHUB_TOKEN."""
    token = (os.environ.get("GITHUB_TOKEN") or "").strip()
    if not token:
        logger.warning("pixelpros: GITHUB_TOKEN absent, impossible de cloner pixel-studio")
        return False
    import subprocess
    url = f"https://x-access-token:{token}@github.com/Jordan-Bourillot/pixel-studio.git"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(
            ["git", "clone", "--branch", "main", url, str(target)],
            capture_output=True, text=True, timeout=120,
        )
        if r.returncode != 0:
            err = (r.stderr or r.stdout or "").replace(token, "***")
            logger.warning("pixelpros: git clone KO : %s", err[:300])
            return False
        return True
    except Exception as exc:
        logger.warning("pixelpros: git clone exception : %s", exc)
        return False


def _git_pull(repo: Path) -> None:
    """Met à jour un clone existant. Silencieux en cas d'erreur (le build
    continue avec ce qu'on a en local)."""
    token = (os.environ.get("GITHUB_TOKEN") or "").strip()
    if not token:
        return  # pas de token = pas de pull, on garde ce qu'on a
    import subprocess
    url = f"https://x-access-token:{token}@github.com/Jordan-Bourillot/pixel-studio.git"
    try:
        subprocess.run(
            ["git", "-C", str(repo), "fetch", url, "main"],
            capture_output=True, text=True, timeout=60,
        )
        subprocess.run(
            ["git", "-C", str(repo), "reset", "--hard", "FETCH_HEAD"],
            capture_output=True, text=True, timeout=30,
        )
    except Exception as exc:
        logger.debug("pixelpros: git pull silencieux: %s", exc)


def analytics_summary(since_iso: str) -> dict:
    """Agrège les stats de fréquentation depuis une date donnée.

    Appelle la fonction Supabase pp_analytics_summary (cf
    pixel-studio/supabase/pp_analytics.sql) qui renvoie un dict avec :
    visiteurs_uniques, pages_vues, scroll_moyen, temps_moyen_session_s,
    formulaires_commences, top_pages[].
    """
    sb = _sb()
    if sb is None:
        return {}
    try:
        res = sb.rpc("pp_analytics_summary", {"p_since": since_iso}).execute()
        return res.data or {}
    except Exception as exc:
        logger.warning("pixelpros.analytics_summary: %s", exc)
        return {}


def _resolve_anthropic_key() -> str:
    """Clé Anthropic à transmettre au builder.

    Même logique multi-source que le reste de Triskell Command : on regarde
    d'abord la variable d'env ANTHROPIC_API_KEY, puis Supabase
    (shared_settings.ai_keys.anthropic).

    Indispensable parce que le builder (pixel-studio/builder/claude_adapter.py)
    ne sait lire QUE la variable d'env ANTHROPIC_API_KEY. Sur Coolify, la clé
    vit dans Supabase et n'est PAS exposée en variable d'env : sans cette
    résolution, l'adaptateur Claude lève RuntimeError, le builder retombe sur
    les données brutes du formulaire et le site client sort VIDE.
    """
    key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    if key:
        return key
    sb = _sb()
    if sb is None:
        return ""
    try:
        rows = (sb.table("shared_settings").select("value")
                .eq("key", "ai_keys").limit(1).execute().data)
        if rows:
            value = rows[0].get("value") or {}
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except Exception:
                    value = {}
            if isinstance(value, dict):
                return (value.get("anthropic") or "").strip()
    except Exception as exc:
        logger.warning("pixelpros._resolve_anthropic_key: %s", exc)
    return ""


def _dispatch_local(pixel_studio: Path, intake_id: str) -> tuple[bool, str]:
    """Lance le builder en subprocess + draine ses logs vers le logger Python
    (qui finit dans les logs Coolify, visibles en debug). Non bloquant."""
    import subprocess
    import sys
    import threading

    builder = pixel_studio / "builder" / "build_site.py"

    # Environnement du subprocess. Le builder hérite de tout l'env du serveur
    # (SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, GITHUB_TOKEN, NETLIFY_AUTH_TOKEN…
    # déjà présents sur Coolify). MAIS la clé Anthropic, elle, n'est pas une
    # variable d'env sur Coolify (elle est rangée dans Supabase) : on la résout
    # et on l'injecte explicitement, sinon l'adaptateur Claude échoue et le
    # site client sort VIDE.
    child_env = dict(os.environ)
    if not (child_env.get("ANTHROPIC_API_KEY") or "").strip():
        anthropic_key = _resolve_anthropic_key()
        if anthropic_key:
            child_env["ANTHROPIC_API_KEY"] = anthropic_key
            logger.info("[builder %s] clé Anthropic injectée (source Supabase)", intake_id[:8])
        else:
            logger.warning(
                "[builder %s] ANTHROPIC_API_KEY introuvable (ni env, ni Supabase) "
                "— le site risque de sortir vide.", intake_id[:8]
            )
    try:
        proc = subprocess.Popen(
            [sys.executable, "-u", str(builder), "--draft-id", intake_id],
            cwd=str(pixel_studio),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=child_env,
        )

        # Thread qui draine stdout au fur et à mesure → logger Python.
        # Sans ça, les prints du builder sont perdus dans le buffer subprocess.
        def _drain(p, iid):
            short = iid[:8] if iid else "?"
            try:
                for line in iter(p.stdout.readline, ''):
                    if not line:
                        break
                    logger.info("[builder %s] %s", short, line.rstrip())
                p.stdout.close()
                rc = p.wait(timeout=300)
                logger.info("[builder %s] === fin du build, exit code=%s ===", short, rc)
                if rc != 0:
                    # Marque le draft 'failed' SI le builder n'a pas déjà mis 'live'
                    cur = get_intake(iid)
                    if cur and cur.get("status") not in ("live",):
                        mark_failed(iid, error_message=f"Builder exit code {rc} (voir logs)")
            except Exception as exc:
                logger.warning("[builder %s] drain exception: %s", short, exc)

        threading.Thread(target=_drain, args=(proc, intake_id), daemon=True).start()

        mark_building(intake_id)
        return True, (
            f"Build lancé localement (PID {proc.pid}). Logs en temps réel dans "
            f"les logs Coolify, status final 'live' ou 'failed' dans 1-2 min."
        )
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
