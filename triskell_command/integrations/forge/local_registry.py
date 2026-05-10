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
def _build_project_data(
    *,
    name: str,
    description: str,
    audience: str,
    tone: str,
    intake: Optional[dict] = None,
    v2_payload: Optional[dict] = None,
) -> dict:
    """Construit la struct Project compatible avec le frontend React.

    Schéma calqué sur les projets existants : ce sont les défauts de
    l'app au step 0 (brief) avec les champs du brief client pré-remplis.

    Si `v2_payload` est fourni (mode wizard détaillé : le client a
    rempli toutes les étapes lui-même), on utilise ses choix exacts
    pour identité, structure, contenu, médias, réseaux, multilingue
    et type de site. Les étapes 9/10/11 (Technique, Options, SEO)
    restent aux défauts car elles ne sont pas exposées au client.

    `intake` : métadonnées d'origine (site source, email client, …) que
    le frontend lit pour afficher un badge « 📩 importé » + « ✓ rempli
    par le client » + « ✨ Nouveau » sur la Home.
    """
    # Helpers de pick avec fallback
    # Le payload V2 peut arriver sous deux formes :
    #   (a) imbriquée  → { site: { typeSite, identite, structure, ... } }
    #       (forme générée par le wizard React La Forge ou ImportFiche)
    #   (b) aplatie    → { typeSite, identite, structure, ... } à la racine
    #       (forme de la Netlify function request-site-detailed.js)
    # On cherche `site.X` en priorité, fallback sur la racine.
    v2 = v2_payload or {}
    inner = v2.get("site") if isinstance(v2.get("site"), dict) else None

    def take(key: str) -> dict:
        if inner and isinstance(inner.get(key), dict):
            return inner[key]
        if isinstance(v2.get(key), dict):
            return v2[key]
        return {}

    v2_brief    = take("brief")
    v2_identite = take("identite")
    v2_structure = take("structure")
    v2_contenu  = take("contenu")
    v2_medias   = take("medias")
    v2_reseaux  = take("reseauxSociaux")
    v2_multi    = take("multilingue")

    def s(d: dict, k: str, default=""):
        v = d.get(k) if isinstance(d, dict) else None
        return v if v is not None and v != "" else default

    def lst(d: dict, k: str, default):
        v = d.get(k) if isinstance(d, dict) else None
        return v if isinstance(v, list) and v else default

    def dct(d: dict, k: str, default):
        v = d.get(k) if isinstance(d, dict) else None
        return v if isinstance(v, dict) and v else default

    def boo(d: dict, k: str, default):
        v = d.get(k) if isinstance(d, dict) else None
        return v if isinstance(v, bool) else default

    # Type de site : V2 explicite (sous site.typeSite OU à la racine), sinon "vitrine"
    type_site = (inner or {}).get("typeSite") if inner else None
    if not type_site:
        type_site = v2.get("typeSite")
    if not type_site or type_site not in ("vitrine", "blog", "portfolio", "onepage"):
        type_site = "vitrine"

    # Brand name : priorité au nom de marque V2, sinon le full name client
    brand_name = s(v2_identite, "nom", name)
    project = {
        "name": brand_name,
        "brief": {
            "prompt":   description,
            "audience": audience,
            "ton":      tone,
            "objectif": s(v2_brief, "objectif", "") or s(v2, "objectif", ""),
            "forged":   "",   # rempli par AlphaBeast quand l'utilisateur lance l'étape
        },
        "identite": {
            "nom": brand_name,
            "slogan": s(v2_identite, "slogan", ""),
            "logoSource": "ia",
            "logoModel": "ideogram",
            "logoUrl": "",
            "palette": s(v2_identite, "palette", "neutre"),
            "paletteCustom": [],
            "typo": "",
            "darkMode": s(v2_identite, "darkMode", "auto"),
        },
        "structure": {
            "pages": lst(v2_structure, "pages", ["accueil", "apropos", "contact"]),
            "pagesCustom": lst(v2_structure, "pagesCustom", []),
            "navigation": s(v2_structure, "navigation", "topbar"),
        },
        "contenu": {
            "source": s(v2_contenu, "source", "ia"),
            "longueur": s(v2_contenu, "longueur", "moyen"),
            "cta": boo(v2_contenu, "cta", True),
            "importedFiles": [],
        },
        "medias": {
            "photos": s(v2_medias, "photos", "upload"),
            "photoFiles": [],
            "videos": s(v2_medias, "videos", "aucune"),
            "videoLinks": lst(v2_medias, "videoLinks", []),
            "videoFiles": [],
            "webp": True, "lazy": True, "altIa": True, "compression": True,
        },
        "typeSite": type_site,
        "reseauxSociaux": {
            "reseaux": lst(v2_reseaux, "reseaux", []),
            "handles": dct(v2_reseaux, "handles", {}),
            "boutonsPartage": boo(v2_reseaux, "boutonsPartage", True),
            "autoPublication": boo(v2_reseaux, "autoPublication", False),
            "autoPubMatrix": {},
        },
        "options": {
            "espaceMembre": False, "commentaires": False, "avis": False,
            "newsletter": False, "popups": False, "liveChat": False,
            "fidelite": False, "multiVendeurs": False, "abTest": False,
            "pwa": False, "notifications": False,
        },
        "responsive": "mobile-first",
        "multilingue": {
            "active": boo(v2_multi, "active", False),
            "langues": lst(v2_multi, "langues", ["fr"]),
            "defaut": s(v2_multi, "defaut", "fr"),
        },
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
    # Mode V2 : on marque les étapes 1-8 comme visitées (le client a tout
    #          rempli, pas d'IA à invoquer pour pré-remplir).
    # Mode V1 : seule l'étape 0 (Brief) est visitée — l'IA Claude prendra
    #          la suite au 1er ouvre via analyzeBriefText.
    is_v2 = bool(v2_payload)
    visited_count = 8 if is_v2 else 1
    out: dict = {
        "project": project,
        "stepIndex": 0,
        "visitedSteps": list(range(visited_count)),
    }
    if intake is not None:
        out["intake"] = intake
    return out


# ---------------------------------------------------------------------------
# API publique
# ---------------------------------------------------------------------------
def write_project_from_brief(
    *,
    project_id: str,
    brief: dict,
    v2_payload: Optional[dict] = None,
    client_filled_steps: bool = False,
) -> bool:
    """Crée le fichier <project_id>.json dans le data dir local.

    `project_id` doit être un UUID (le même que celui de forge_projects
    Supabase pour garder une correspondance 1:1 entre les deux fronts).

    Mode V2 (`client_filled_steps=True` + `v2_payload` non vide) :
    on pré-remplit toutes les étapes 1-8 du wizard avec les choix exacts
    du client (typeSite, identite, structure, contenu, medias, reseaux,
    multilingue) — pas d'analyse Claude requise.

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
        # V1 (brief libre) → `analyzed: False` : l'app standalone déclenche
        #     analyzeBriefText au 1er ouvre.
        # V2 (wizard détaillé) → `analyzed: True` car le client a tout
        #     rempli. AlphaBeast peut tourner pour enrichir le brief
        #     stratégique mais Claude Extract est sauté.
        "analyzed": bool(client_filled_steps),
        "client_filled_steps": bool(client_filled_steps),
        # Type de client + facturation (V2 seulement, dispo pour devis)
        "client_type":  brief.get("client_type") or "particulier",
        "company_name": brief.get("company_name") or "",
        "siret":        brief.get("siret") or "",
        "vat_number":   brief.get("vat_number") or "",
        # Demande spéciale du client (V1 et V2). Si non vide, La Forge
        # affichera un avertissement ⚠️ persistant sur la Home + en haut
        # du wizard tant que le projet n'est pas livré.
        "special_request": (brief.get("special_request") or "").strip(),
    }

    project_data = _build_project_data(
        name=full_name,
        description=brief.get("description") or "",
        audience=brief.get("audience") or "",
        tone=brief.get("tone") or "",
        intake=intake,
        v2_payload=v2_payload if client_filled_steps else None,
    )
    # Si V2 : le nom du projet privilégie le nom de marque (depuis
    # site.identite.nom) plutôt que le nom du client.
    if client_filled_steps and isinstance(project_data.get("project"), dict):
        brand = (project_data["project"].get("identite") or {}).get("nom")
        if brand:
            full_name = brand
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


# ---------------------------------------------------------------------------
# Heartbeat : signal de vie du bridge teddy_to_forge → consommé par La Forge
# ---------------------------------------------------------------------------
# Fichier : %APPDATA%\studio.triskell.laforge\bridge_heartbeat.json
#
# Schéma :
#   {
#     "schema_version": 1,
#     "bridge_module": "teddy_to_forge",
#     "cycle_seconds": 300,                    # période du poller
#     "last_scan_started_at":   "2026-05-09T10:29:55Z",
#     "last_scan_completed_at": "2026-05-09T10:30:00Z",
#     "last_scan_duration_seconds": 5,
#     "last_scan_result": {                    # cf. counters de _do_one_poll
#         "scanned": 0, "matched": 0, "written": 0,
#         "skipped": 0, "errors": 0, "error": null
#     }
#   }
#
# La Forge lit ce fichier toutes les 30 s et affiche un voyant. Si
# `last_scan_completed_at` est plus vieux que ~2× cycle_seconds → bridge
# considéré comme inactif. Si le fichier n'existe pas du tout → bridge
# jamais lancé depuis l'install.
def _heartbeat_path() -> Optional[Path]:
    base = _data_dir()
    if base is None:
        return None
    return base / "bridge_heartbeat.json"


def write_bridge_heartbeat(
    *,
    bridge_module: str,
    cycle_seconds: int,
    started_at_iso: str,
    completed_at_iso: str,
    duration_seconds: float,
    result: dict,
) -> bool:
    """Écrit/écrase le heartbeat du bridge à chaque fin de cycle.

    Best-effort : si le data dir n'est pas accessible (l'app La Forge n'est
    pas installée chez l'utilisateur), on log debug et on continue. Le
    bridge ne doit JAMAIS planter à cause d'un heartbeat qui ne s'écrit pas.
    """
    target = _heartbeat_path()
    if target is None:
        return False
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "bridge_module": bridge_module,
            "cycle_seconds": int(cycle_seconds),
            "last_scan_started_at": started_at_iso,
            "last_scan_completed_at": completed_at_iso,
            "last_scan_duration_seconds": round(float(duration_seconds), 3),
            "last_scan_result": result,
        }
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return True
    except OSError as exc:
        logger.debug("local_registry: heartbeat write KO: %s", exc)
        return False
