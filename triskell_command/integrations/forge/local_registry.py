"""Mirror local du registre de l'app standalone La Forge du Web.

L'app autonome (Tauri 2 — identifier `studio.triskell.laforge`) stocke ses
projets dans :
    Windows : %APPDATA%\\studio.triskell.laforge\\projects\\<uuid>.json
    macOS   : ~/Library/Application Support/studio.triskell.laforge/projects/
    Linux   : ~/.local/share/studio.triskell.laforge/projects/

Format du fichier (cf. core/src/registry.rs) :
    {
      "id": "<uuid>",
      "name": "<nom projet>",
      "data": "<JSON stringifié de la struct Project frontend>",
      "created_at": <epoch seconds>,
      "updated_at": <epoch seconds>
    }

Le bridge teddy_to_forge écrit dans Supabase ET ici, pour que le projet
issu d'un brief client apparaisse immédiatement dans l'app standalone
quand l'utilisateur l'ouvre.

Best-effort : si le data dir est inaccessible ou que l'app n'est pas
installée, on log un warning et on continue (Supabase reste la source
canonique).
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


TAURI_IDENTIFIER = "studio.triskell.laforge"


def _data_dir() -> Optional[Path]:
    """Résout le data dir Tauri pour l'app La Forge du Web (cross-OS).

    Renvoie None si on ne peut pas le construire (var d'env manquante).
    """
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if not appdata:
            return None
        return Path(appdata) / TAURI_IDENTIFIER
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / TAURI_IDENTIFIER
    # Linux + autres
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / TAURI_IDENTIFIER


def _projects_dir() -> Optional[Path]:
    base = _data_dir()
    if base is None:
        return None
    return base / "projects"


def is_available() -> bool:
    """True si on peut écrire dans le data dir (créé si besoin)."""
    d = _projects_dir()
    if d is None:
        return False
    try:
        d.mkdir(parents=True, exist_ok=True)
        return d.is_dir() and os.access(d, os.W_OK)
    except OSError as exc:
        logger.debug("local_registry: data dir inaccessible: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Construction du payload Project frontend depuis un brief
# ---------------------------------------------------------------------------
def _build_project_data(*, name: str, description: str, audience: str,
                        tone: str, intake: Optional[dict] = None) -> dict:
    """Construit la struct Project compatible avec le frontend React.

    Schéma calqué sur les projets existants : ce sont les défauts de
    l'app au step 0 (brief) avec les champs du brief client pré-remplis.
    L'utilisateur valide les autres étapes dans l'app autonome.

    `intake` : métadonnées d'origine (site source, email client, …) que
    le frontend lit pour afficher un badge « 📩 importé » + « ✨ Nouveau »
    sur la Home tant que le projet n'a pas été ouvert.
    """
    project = {
        "name": name,
        "brief": {
            "prompt":   description,
            "audience": audience,
            "ton":      tone,
            "objectif": "",
            "forged":   "",   # rempli par l'IA quand l'utilisateur lance l'étape
        },
        "identite": {
            "nom": name, "slogan": "", "logoSource": "ia",
            "logoModel": "ideogram", "logoUrl": "",
            "palette": "neutre", "paletteCustom": [],
            "typo": "", "darkMode": "auto",
        },
        "structure": {
            "pages": ["accueil", "apropos", "contact"],
            "pagesCustom": [], "navigation": "topbar",
        },
        "contenu": {
            "source": "ia", "longueur": "moyen",
            "cta": True, "importedFiles": [],
        },
        "medias": {
            "photos": "upload", "photoFiles": [], "videos": "aucune",
            "videoLinks": [], "videoFiles": [],
            "webp": True, "lazy": True, "altIa": True, "compression": True,
        },
        "typeSite": "vitrine",
        "reseauxSociaux": {
            "reseaux": [], "handles": {}, "boutonsPartage": True,
            "autoPublication": False, "autoPubMatrix": {},
        },
        "options": {
            "espaceMembre": False, "commentaires": False, "avis": False,
            "newsletter": False, "popups": False, "liveChat": False,
            "fidelite": False, "multiVendeurs": False, "abTest": False,
            "pwa": False, "notifications": False,
        },
        "responsive": "mobile-first",
        "multilingue": {"active": False, "langues": ["fr"], "defaut": "fr"},
        "technique": {
            "stack": "nextjs", "auth": False, "db": False,
            "contact": True, "newsletter": False,
        },
        "seo": {
            "motsCles": [], "title": "", "description": "",
            "hookLePhare": True, "sitemapAuto": True,
        },
        "ecosysteme": {
            "registreCentral": False, "liensCroises": [],
            "analyticsCommun": False,
        },
        "legal": {
            "mentions": True, "confidentialite": True,
            "cookies": True, "rgpd": True,
        },
        "apercu": {"lance": False},
        "deploiement": {
            "domaine": "", "hebergeur": "netlify", "repo": "nouveau",
            "ciAuto": True, "deployedUrl": "", "deployedAt": 0,
        },
        "suivi": {
            "monitoring": True, "alimentationPhare": True,
            "recapHebdo": False,
        },
    }
    out: dict = {
        "project": project,
        "stepIndex": 0,           # premier écran : Brief, déjà rempli
        "visitedSteps": [0],
    }
    if intake is not None:
        out["intake"] = intake
    return out


# ---------------------------------------------------------------------------
# API publique
# ---------------------------------------------------------------------------
def write_project_from_brief(*, project_id: str, brief: dict) -> bool:
    """Crée le fichier <project_id>.json dans le data dir local.

    `project_id` doit être un UUID (le même que celui de forge_projects
    Supabase pour garder une correspondance 1:1 entre les deux fronts).

    Renvoie True si écrit avec succès, False si data dir indispo ou erreur.
    """
    if not is_available():
        return False
    d = _projects_dir()
    if d is None:
        return False

    first = (brief.get("first_name") or "").strip()
    last = (brief.get("last_name") or "").strip()
    full_name = f"{first} {last}".strip() or brief.get("email") or "Sans nom"

    now = int(time.time())
    # Métadonnées d'import affichées comme badges « 📩 + ✨ Nouveau »
    # par la Home de l'app standalone tant que `opened: false`.
    received_at = brief.get("received_at")
    if isinstance(received_at, str):
        # ISO string → epoch
        try:
            from datetime import datetime as _dt
            received_at = int(_dt.fromisoformat(
                received_at.replace("Z", "+00:00")
            ).timestamp())
        except (ValueError, TypeError):
            received_at = now
    if not isinstance(received_at, int):
        received_at = now

    intake = {
        "source": "form-import",
        "site": brief.get("source") or "unknown",
        "received_at": received_at,
        "client_email": brief.get("email") or "",
        "client_phone": brief.get("phone") or "",
        "opened": False,
        # `analyzed` reste False jusqu'à ce que l'app standalone fasse passer
        # le brief par analyzeBriefText (Claude Sonnet + AlphaBeast) pour
        # remplir toutes les étapes du wizard. Au 1er ouvre, l'app détecte
        # ce flag et déclenche l'analyse automatiquement.
        "analyzed": False,
    }

    project_data = _build_project_data(
        name=full_name,
        description=brief.get("description") or "",
        audience=brief.get("audience") or "",
        tone=brief.get("tone") or "",
        intake=intake,
    )
    record = {
        "id": project_id,
        "name": full_name,
        "data": json.dumps(project_data, ensure_ascii=False),
        "created_at": now,
        "updated_at": now,
    }

    target = d / f"{project_id}.json"
    try:
        target.write_text(
            json.dumps(record, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info(
            "local_registry: projet '%s' écrit dans %s", full_name, target,
        )
        return True
    except OSError as exc:
        logger.warning("local_registry: échec écriture %s: %s", target, exc)
        return False


def delete_project(project_id: str) -> bool:
    """Supprime le fichier local d'un projet (best-effort)."""
    d = _projects_dir()
    if d is None:
        return False
    target = d / f"{project_id}.json"
    if not target.exists():
        return True
    try:
        target.unlink()
        return True
    except OSError as exc:
        logger.debug("local_registry: échec delete %s: %s", target, exc)
        return False
