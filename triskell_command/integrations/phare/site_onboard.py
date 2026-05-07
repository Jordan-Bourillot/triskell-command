"""Auto-détection des champs d'un site à partir d'un dossier local.

Lit `.git/config`, `.git/HEAD`, `.netlify/state.json`, `package.json` pour
pré-remplir un formulaire d'ajout de site dans Le Phare. Tout est best-effort :
chaque détection peut échouer silencieusement, on retourne ce qu'on a trouvé
plus un dict `_status` qui dit ce qui a été détecté vs. manquant.
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


_GIT_REMOTE_RE = re.compile(
    r'\[remote\s+"origin"\]\s*\n(?:[ \t]+\S+\s*=\s*[^\n]+\n)*?'
    r'[ \t]+url\s*=\s*([^\n]+)',
    re.MULTILINE,
)


def _parse_github_owner_repo(remote_url: str) -> Optional[str]:
    """`git@github.com:Owner/repo.git` ou `https://github.com/Owner/repo.git`
    → `Owner/repo`. Retourne None si ce n'est pas GitHub.
    """
    url = remote_url.strip()
    m = re.search(r'github\.com[:/]+([^/\s]+)/([^/\s]+?)(?:\.git)?/?\s*$', url)
    if not m:
        return None
    return f"{m.group(1)}/{m.group(2)}"


def _read_git_remote(folder: Path) -> Optional[str]:
    """Retourne `owner/repo` GitHub depuis `.git/config`."""
    cfg = folder / ".git" / "config"
    if not cfg.exists():
        return None
    try:
        text = cfg.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        logger.debug("site_onboard: read .git/config failed: %s", exc)
        return None
    m = _GIT_REMOTE_RE.search(text)
    if not m:
        return None
    return _parse_github_owner_repo(m.group(1))


def _read_git_branch(folder: Path) -> Optional[str]:
    """Retourne le nom de la branche courante depuis `.git/HEAD`."""
    head = folder / ".git" / "HEAD"
    if not head.exists():
        return None
    try:
        text = head.read_text(encoding="utf-8", errors="replace").strip()
    except Exception:
        return None
    if text.startswith("ref: refs/heads/"):
        return text[len("ref: refs/heads/"):].strip() or None
    return None


def _read_netlify_site_id(folder: Path) -> Optional[str]:
    """Retourne `siteId` depuis `.netlify/state.json`."""
    state = folder / ".netlify" / "state.json"
    if not state.exists():
        return None
    try:
        data = json.loads(state.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:
        logger.debug("site_onboard: parse .netlify/state.json failed: %s", exc)
        return None
    sid = data.get("siteId") or data.get("site_id")
    return str(sid).strip() if sid else None


def _detect_stack_from_package_json(folder: Path) -> Optional[str]:
    """Devine la stack depuis `package.json` :
    - `astro` dans deps → "astro"
    - `next` → "next"
    - `vite` ou `react` (sans next) → "vite"
    - sinon None
    """
    pkg = folder / "package.json"
    if not pkg.exists():
        return None
    try:
        data = json.loads(pkg.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None
    deps = {}
    for key in ("dependencies", "devDependencies", "peerDependencies"):
        deps.update(data.get(key) or {})
    if "astro" in deps:
        return "astro"
    if "next" in deps:
        return "next"
    if "vite" in deps or "react" in deps:
        return "vite"
    return None


def _detect_stack_fallback(folder: Path) -> Optional[str]:
    """Si pas de `package.json`, on regarde la structure du dossier."""
    if (folder / "astro.config.mjs").exists() or (folder / "astro.config.ts").exists():
        return "astro"
    if (folder / "next.config.js").exists() or (folder / "next.config.mjs").exists():
        return "next"
    # HTML pur : présence d'un index.html et pas de package.json
    if (folder / "index.html").exists():
        return "html"
    # Sous-dossier `public/` ou `landing/public/` typique des sites Triskell
    for sub in ("public", "landing/public", "landing-pack/public"):
        if (folder / sub / "index.html").exists():
            return "html"
    return None


def _read_netlify_domain(site_id: str, netlify_token: Optional[str]) -> Optional[str]:
    """Appel API Netlify pour récupérer le `custom_domain` ou `default_domain`.
    Silencieux si pas de token ou si l'appel échoue.
    """
    if not site_id or not netlify_token:
        return None
    try:
        import urllib.request

        req = urllib.request.Request(
            f"https://api.netlify.com/api/v1/sites/{site_id}",
            headers={"Authorization": f"Bearer {netlify_token}"},
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        logger.debug("site_onboard: netlify api failed: %s", exc)
        return None
    return (data.get("custom_domain") or data.get("default_domain") or "").strip() or None


def detect_from_folder(
    folder_path: str,
    *,
    netlify_token: Optional[str] = None,
) -> dict:
    """Inspecte un dossier local et retourne un dict prêt à pré-remplir le
    formulaire d'ajout de site, plus une clé `_status` qui dit ce qui a été
    trouvé vs. manquant.

    Retourne toujours un dict (jamais None). Champs absents = clés manquantes
    ou valeurs `None`.
    """
    folder = Path(folder_path).expanduser().resolve()
    status: dict[str, str] = {}
    out: dict = {}

    if not folder.is_dir():
        status["folder"] = "not_a_directory"
        return {"_status": status}
    status["folder"] = "ok"

    # Repo GitHub + branche
    repo = _read_git_remote(folder)
    if repo:
        out["repo_github"] = repo
        status["repo_github"] = "detected"
    else:
        status["repo_github"] = "missing"

    branch = _read_git_branch(folder)
    if branch:
        out["repo_branch_main"] = branch
        status["repo_branch_main"] = "detected"
    else:
        status["repo_branch_main"] = "missing"

    # Netlify site id
    nid = _read_netlify_site_id(folder)
    if nid:
        out["netlify_site_id"] = nid
        status["netlify_site_id"] = "detected"
    else:
        status["netlify_site_id"] = "missing"

    # Stack
    stack = _detect_stack_from_package_json(folder) or _detect_stack_fallback(folder)
    if stack:
        out["stack"] = stack
        status["stack"] = "detected"
    else:
        status["stack"] = "missing"

    # Nom suggéré (= nom du dossier, capitalisé)
    out["name"] = folder.name.replace("-", " ").replace("_", " ").strip().title()

    # Domaine via Netlify (optionnel, silencieux si pas de token)
    if nid and netlify_token:
        domain = _read_netlify_domain(nid, netlify_token)
        if domain:
            out["domain"] = domain
            status["domain"] = "detected_via_netlify"
        else:
            status["domain"] = "missing"
    else:
        status["domain"] = "missing"

    out["_status"] = status
    out["_folder_path"] = str(folder)
    return out
