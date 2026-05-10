"""Le Phare — Audit des sous-modules git cassés.

Pour chaque site dans `phare_sites` (avec `repo_github` renseigné) :
  1. Récupère la liste des fichiers à la racine de la branche par défaut
     via l'API GitHub.
  2. Détecte les entrées de type "commit" — ce sont des gitlinks
     (sous-modules).
  3. Vérifie si un `.gitmodules` existe à la racine et qu'il mappe chaque
     gitlink détecté.
  4. Pour chaque gitlink mal mappé → signale comme « cassé » avec une
     proposition d'action.

Pourquoi c'est important : si un repo a un gitlink sans `.gitmodules` valide,
le pipeline auto-PR de Le Phare ne peut pas patcher le code source réel
(le dossier reste vide après clone). C'est le bloquant n°1 pour passer du
mode « audit » au mode « optimisation auto » sur 100% des sites.

Lancement :
    cd "Triskell Command"
    py -3 scripts/phare_check_submodules.py
"""

from __future__ import annotations

import configparser
import io
import json
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# UTF-8 sur stdout (Windows cp1252 sinon)
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

# Permet d'importer triskell_core et triskell_command depuis n'importe où
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CORE = ROOT.parent / "Triskell Core"
for p in (str(CORE), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from triskell_command.integrations.phare import repo  # noqa: E402


GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"


def _ok(label: str, detail: str = "") -> None:
    print(f"  {GREEN}OK{RESET}  {label}" + (f"  {DIM}{detail}{RESET}" if detail else ""))


def _warn(label: str, detail: str = "") -> None:
    print(f"  {YELLOW}!!{RESET}  {label}" + (f"  {detail}" if detail else ""))


def _ko(label: str, detail: str = "") -> None:
    print(f"  {RED}KO{RESET}  {label}" + (f"  {detail}" if detail else ""))


def _gh_api(url: str, token: str) -> Any:
    req = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "le-phare-submodule-checker",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _gh_raw(owner: str, name: str, branch: str, path: str, token: str) -> str | None:
    """Récupère un fichier brut via l'API GitHub (renvoie None si 404)."""
    url = f"https://api.github.com/repos/{owner}/{name}/contents/{path}?ref={branch}"
    try:
        data = _gh_api(url, token)
    except HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    import base64
    return base64.b64decode(data["content"]).decode("utf-8", errors="replace")


def _split_repo(repo_github: str) -> tuple[str, str] | None:
    """`Jordan-Bourillot/pack-electricien-pro` → (owner, name)."""
    repo_github = repo_github.strip()
    if not repo_github or "/" not in repo_github:
        return None
    parts = repo_github.split("/")
    if len(parts) != 2:
        return None
    return parts[0], parts[1]


def _parse_gitmodules(text: str) -> dict[str, dict[str, str]]:
    """Parse un .gitmodules → {path: {url, branch?, ...}}."""
    cp = configparser.ConfigParser()
    cp.read_file(io.StringIO(text))
    out: dict[str, dict[str, str]] = {}
    for section in cp.sections():
        if not section.startswith("submodule"):
            continue
        items = dict(cp.items(section))
        path = items.get("path")
        if path:
            out[path] = items
    return out


def _check_site(site: dict, github_token: str) -> dict:
    """Renvoie {site, status: ok|warn|ko, gitlinks, missing, message}."""
    name = site.get("name") or site.get("domain") or "?"
    repo_github = site.get("repo_github") or ""
    result = {
        "site": name,
        "domain": site.get("domain"),
        "repo": repo_github,
        "status": "ok",
        "gitlinks": [],
        "missing": [],
        "message": "",
    }

    if not repo_github:
        result["status"] = "warn"
        result["message"] = "repo_github vide — site non patchable"
        return result

    parsed = _split_repo(repo_github)
    if parsed is None:
        result["status"] = "ko"
        result["message"] = f"repo_github invalide : {repo_github!r}"
        return result
    owner, name_repo = parsed

    # 1. Métadonnées du repo (branche par défaut)
    try:
        meta = _gh_api(f"https://api.github.com/repos/{owner}/{name_repo}", github_token)
    except HTTPError as exc:
        result["status"] = "ko"
        result["message"] = f"repo inaccessible (HTTP {exc.code})"
        return result
    except URLError as exc:
        result["status"] = "ko"
        result["message"] = f"erreur réseau : {exc.reason}"
        return result

    branch = meta.get("default_branch") or "main"

    # 2. Tree de la racine — détecte les entrées de type "commit" (gitlinks)
    try:
        tree = _gh_api(
            f"https://api.github.com/repos/{owner}/{name_repo}/git/trees/{branch}",
            github_token,
        )
    except HTTPError as exc:
        result["status"] = "ko"
        result["message"] = f"impossible de lire l'arbre racine (HTTP {exc.code})"
        return result

    # Mode "160000" = gitlink (sous-module)
    gitlinks = [
        e["path"] for e in tree.get("tree", [])
        if e.get("type") == "commit" or e.get("mode") == "160000"
    ]
    result["gitlinks"] = gitlinks

    if not gitlinks:
        result["message"] = "pas de sous-module — patchable directement"
        return result

    # 3. Lis .gitmodules
    gm = _gh_raw(owner, name_repo, branch, ".gitmodules", github_token)
    if gm is None:
        result["status"] = "ko"
        result["missing"] = gitlinks
        result["message"] = (
            f"{len(gitlinks)} sous-module(s) sans .gitmodules — "
            f"clone retournera des dossier(s) vide(s) : {', '.join(gitlinks)}"
        )
        return result

    mapped = _parse_gitmodules(gm)
    missing = [g for g in gitlinks if g not in mapped]
    if missing:
        result["status"] = "ko"
        result["missing"] = missing
        result["message"] = (
            f"{len(missing)}/{len(gitlinks)} sous-module(s) non mappé(s) "
            f"dans .gitmodules : {', '.join(missing)}"
        )
        return result

    result["message"] = (
        f"{len(gitlinks)} sous-module(s) correctement mappé(s) — OK"
    )
    return result


def main() -> int:
    print(f"{BOLD}Le Phare — audit sous-modules git{RESET}")
    print()

    # 1. Charge la config
    cfg = repo.get_config()
    if not cfg:
        print(f"{RED}Erreur :{RESET} phare_config introuvable. Configure")
        print("Supabase + phare_config avant de lancer ce script.")
        return 1

    github_token = cfg.get("github_token")
    if not github_token:
        print(f"{RED}Erreur :{RESET} github_token absent de phare_config.")
        print("Pose un fine-grained PAT (lecture des 9 repos Triskell) dans")
        print("Réglages → Le Phare avant de relancer.")
        return 1

    # 2. Liste des sites
    try:
        sites = repo.list_sites()
    except Exception as exc:
        print(f"{RED}Erreur :{RESET} impossible de lire phare_sites : {exc}")
        return 1

    sites = [s for s in sites if s.get("active") is not False]
    if not sites:
        print(f"{YELLOW}Aucun site actif dans phare_sites.{RESET}")
        return 0

    print(f"Audit de {len(sites)} site(s) actif(s)…")
    print()

    results = []
    for site in sites:
        r = _check_site(site, github_token)
        results.append(r)
        label = f"{r['site']}  ({r.get('repo') or '?'})"
        if r["status"] == "ok":
            _ok(label, r["message"])
        elif r["status"] == "warn":
            _warn(label, r["message"])
        else:
            _ko(label, r["message"])

    print()

    # 3. Résumé + actions
    ko = [r for r in results if r["status"] == "ko"]
    warn = [r for r in results if r["status"] == "warn"]
    ok = [r for r in results if r["status"] == "ok"]
    print(f"{BOLD}Résumé :{RESET}  "
          f"{GREEN}{len(ok)} OK{RESET}  "
          f"{YELLOW}{len(warn)} warn{RESET}  "
          f"{RED}{len(ko)} cassés{RESET}")

    if ko:
        print()
        print(f"{BOLD}Actions à faire :{RESET}")
        for r in ko:
            print(f"  • {BOLD}{r['site']}{RESET}  ({r['repo']})")
            print(f"    {r['message']}")
            if r["missing"]:
                print(f"    Options :")
                print(f"      a) cloner le vrai code, commit + push un .gitmodules valide")
                print(f"      b) changer phare_sites.repo_github pour pointer vers le repo")
                print(f"         qui contient le vrai code patchable")
                print(f"      c) marquer le site comme `active = false` si plus maintenu")
        return 1

    print(f"\n{GREEN}Tous les sites actifs sont patchables.{RESET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
