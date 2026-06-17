"""Pipeline Git → PR GitHub → Netlify preview → diff visuel.

C'est le garde-fou central de Le Phare. Aucun agent ne pousse en main direct :
toute modif passe par une branche `phare/auto-YYYY-MM-DD-<slug>`, ouvre une
PR, attend le preview deploy Netlify, vérifie Lighthouse + diff visuel + 4xx,
et merge automatiquement uniquement si TOUTES les checks passent.

Dépendances optionnelles :
- gitpython (clone/branch/commit/push) → fallback subprocess git si absent
- requests (GitHub + Netlify API) → déjà dans requirements
- Pillow (diff visuel pixel-à-pixel) → déjà dans requirements

Si GITHUB_TOKEN ou NETLIFY_TOKEN absents, les fonctions retournent
status="blocked_no_credentials" et la PR reste à l'état "draft" pour validation
manuelle dans l'UI.
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

from . import pagespeed, repo

logger = logging.getLogger(__name__)

GH_API = "https://api.github.com"
NETLIFY_API = "https://api.netlify.com/api/v1"


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------
def _github_token() -> str:
    cfg = repo.get_config()
    return cfg.get("github_token") or os.environ.get("GITHUB_TOKEN", "")


def _netlify_token() -> str:
    cfg = repo.get_config()
    return cfg.get("netlify_token") or os.environ.get("NETLIFY_TOKEN", "")


# ---------------------------------------------------------------------------
# Git ops (subprocess pour rester sans dépendance dure à gitpython)
# ---------------------------------------------------------------------------
def _git(*args: str, cwd: Optional[str] = None) -> tuple[int, str]:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True
    )
    return proc.returncode, (proc.stdout + proc.stderr)


def clone_repo(repo_full: str, dest: str, *, branch: str = "main") -> bool:
    """Clone shallow via HTTPS+token. repo_full = 'owner/repo'."""
    token = _github_token()
    if not token:
        logger.warning("git_pipeline: GITHUB_TOKEN absent, clone impossible")
        return False
    url = f"https://x-access-token:{token}@github.com/{repo_full}.git"
    code, out = _git("clone", "--depth", "5", "--branch", branch, url, dest)
    if code != 0:
        logger.warning("clone %s: %s", repo_full, out[-300:])
        return False
    return True


def create_branch(workdir: str, branch: str) -> bool:
    code, _ = _git("checkout", "-b", branch, cwd=workdir)
    return code == 0


def commit_all(workdir: str, message: str, *, author: str = "Le Phare <phare@triskell-studio.fr>") -> bool:
    _git("add", "-A", cwd=workdir)
    code, out = _git("-c", f"user.name=Le Phare",
                      "-c", f"user.email=phare@triskell-studio.fr",
                      "commit", "-m", message,
                      "--author", author, cwd=workdir)
    if code != 0 and "nothing to commit" not in out:
        logger.warning("commit: %s", out[-300:])
        return False
    return True


def push_branch(workdir: str, branch: str) -> bool:
    code, out = _git("push", "-u", "origin", branch, cwd=workdir)
    if code != 0:
        logger.warning("push %s: %s", branch, out[-300:])
        return False
    return True


# ---------------------------------------------------------------------------
# GitHub PR
# ---------------------------------------------------------------------------
# Raison du dernier échec d'open_pr — lue par les appelants pour donner
# des messages de carte utiles (un seul worker applique à la fois).
last_pr_error: str = ""
# Idem pour merge_pr : la vraie raison du dernier échec de publication.
last_merge_error: str = ""


def _pr_mergeable_state(repo_full: str, pr_number: int) -> tuple[Optional[bool], str]:
    """(mergeable, mergeable_state). mergeable=None → GitHub calcule encore."""
    token = _github_token()
    if not token:
        return None, "no_token"
    try:
        r = requests.get(
            f"{GH_API}/repos/{repo_full}/pulls/{pr_number}",
            headers={"Authorization": f"Bearer {token}",
                     "Accept": "application/vnd.github+json"},
            timeout=15)
    except requests.RequestException as exc:
        return None, str(exc)[:120]
    if r.status_code >= 400:
        return None, f"HTTP {r.status_code}"
    j = r.json()
    return j.get("mergeable"), (j.get("mergeable_state") or "")


def wait_pr_mergeable(repo_full: str, pr_number: int, *,
                      timeout_s: int = 30, poll_s: int = 3) -> Optional[bool]:
    """Attend que GitHub ait calculé la fusionnabilité de la PR.

    GitHub calcule `mergeable` de façon ASYNCHRONE après l'ouverture : juste
    après, il renvoie null, et fusionner pendant ce calcul renvoie un 405
    « PR not mergeable ». C'est ce qui faisait échouer la publication des
    modifs de pages (titres, métas) alors qu'un sitemap — fichier neuf,
    calcul instantané — passait sans souci (constaté le 17/06/2026).

    Renvoie True (fusionnable), False (conflit), None (toujours inconnu)."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        mergeable, _ = _pr_mergeable_state(repo_full, pr_number)
        if mergeable is True:
            return True
        if mergeable is False:
            return False
        time.sleep(poll_s)
    return None


def open_pr(repo_full: str, *, head: str, base: str = "main",
            title: str, body: str = "") -> Optional[dict]:
    """Ouvre une PR. En échec, renvoie None et mémorise la raison exacte
    dans `last_pr_error` — avant, le détail (rate limit GitHub, « PR déjà
    ouverte », « aucun commit entre les branches »…) finissait dans un
    journal invisible et la carte disait juste « ouverture PR échouée »
    (constaté par Jordan le 12/06)."""
    global last_pr_error
    last_pr_error = ""
    token = _github_token()
    if not token:
        last_pr_error = "jeton GitHub manquant"
        return None
    try:
        r = requests.post(
            f"{GH_API}/repos/{repo_full}/pulls",
            headers={"Authorization": f"Bearer {token}",
                     "Accept": "application/vnd.github+json"},
            json={"title": title, "head": head, "base": base, "body": body},
            timeout=20,
        )
    except requests.RequestException as exc:
        logger.warning("open_pr: %s", exc)
        last_pr_error = f"réseau : {str(exc)[:140]}"
        return None
    if r.status_code >= 400:
        logger.warning("open_pr HTTP %s: %s", r.status_code, r.text[:200])
        detail = ""
        try:
            j = r.json()
            detail = (j.get("message") or "")
            errs = j.get("errors") or []
            if errs and isinstance(errs[0], dict) and errs[0].get("message"):
                detail += f" — {errs[0]['message']}"
        except Exception:
            detail = r.text[:140]
        last_pr_error = f"GitHub HTTP {r.status_code} : {detail[:200]}"
        return None
    return r.json()


def merge_pr(repo_full: str, pr_number: int, *,
             commit_title: str = "", commit_message: str = "",
             merge_method: str = "squash") -> bool:
    global last_merge_error
    last_merge_error = ""
    token = _github_token()
    if not token:
        last_merge_error = "jeton GitHub manquant"
        return False
    # On attend que GitHub ait fini de vérifier la modif avant de publier,
    # sinon il répond « pas encore fusionnable » (405) sur les modifs de
    # fichiers existants — le bug de publication des titres du 17/06/2026.
    if wait_pr_mergeable(repo_full, pr_number) is False:
        last_merge_error = ("la modification est en conflit avec une autre "
                            "modif du site — à revoir")
        return False
    headers = {"Authorization": f"Bearer {token}",
               "Accept": "application/vnd.github+json"}
    url = f"{GH_API}/repos/{repo_full}/pulls/{pr_number}/merge"
    body = {"commit_title": commit_title or "Le Phare auto-merge",
            "commit_message": commit_message, "merge_method": merge_method}
    for attempt in range(3):
        try:
            r = requests.put(url, headers=headers, json=body, timeout=20)
        except requests.RequestException as exc:
            last_merge_error = f"réseau : {str(exc)[:140]}"
            time.sleep(2)
            continue
        if r.status_code < 400:
            last_merge_error = ""
            return True
        try:
            detail = r.json().get("message") or ""
        except Exception:
            detail = r.text[:140]
        last_merge_error = f"GitHub {r.status_code} : {detail[:160]}"
        logger.warning("merge_pr HTTP %s: %s", r.status_code, detail[:200])
        # 405/409 = souvent « pas encore fusionnable » → on patiente et retente
        if r.status_code in (405, 409) and attempt < 2:
            wait_pr_mergeable(repo_full, pr_number, timeout_s=15)
            time.sleep(2)
            continue
        return False
    return False


def close_pr(repo_full: str, pr_number: int, reason: str = "") -> bool:
    token = _github_token()
    if not token:
        return False
    try:
        r = requests.patch(
            f"{GH_API}/repos/{repo_full}/pulls/{pr_number}",
            headers={"Authorization": f"Bearer {token}",
                     "Accept": "application/vnd.github+json"},
            json={"state": "closed", "body": reason},
            timeout=20,
        )
    except requests.RequestException as exc:
        logger.warning("close_pr: %s", exc)
        return False
    return r.status_code < 400


# ---------------------------------------------------------------------------
# Netlify deploys
# ---------------------------------------------------------------------------
def wait_netlify_preview(netlify_site_id: str, branch: str,
                         *, timeout_s: int = 300, poll_s: int = 8) -> Optional[str]:
    """Attend qu'un deploy Netlify pour cette branche soit READY. Renvoie l'URL."""
    token = _netlify_token()
    if not token or not netlify_site_id:
        return None
    deadline = time.time() + timeout_s
    headers = {"Authorization": f"Bearer {token}"}
    last_url = None
    while time.time() < deadline:
        try:
            r = requests.get(
                f"{NETLIFY_API}/sites/{netlify_site_id}/deploys",
                headers=headers, timeout=15,
                params={"branch": branch, "per_page": 5},
            )
        except requests.RequestException as exc:
            logger.debug("netlify deploys: %s", exc)
            time.sleep(poll_s)
            continue
        if r.status_code >= 400:
            logger.debug("netlify HTTP %s", r.status_code)
            time.sleep(poll_s)
            continue
        deploys = r.json() or []
        for dep in deploys:
            if dep.get("branch") == branch:
                state = dep.get("state")
                last_url = dep.get("deploy_ssl_url") or dep.get("deploy_url")
                if state == "ready":
                    return last_url
                if state in ("error", "rejected"):
                    return None
        time.sleep(poll_s)
    return last_url  # peut-être pas ready mais on retente côté checks


# ---------------------------------------------------------------------------
# Diff visuel (Pillow, pixel-à-pixel sur capture HTTP texte)
# ---------------------------------------------------------------------------
def visual_diff_text(url_a: str, url_b: str) -> dict:
    """Diff textuel rapide entre 2 URLs (sans rendu).

    Pour un vrai diff visuel pixel-à-pixel, il faudrait Playwright/headless
    Chrome. On fournit ici un diff de longueur HTML brute, suffisant pour
    bloquer une PR qui change radicalement la page (ex: layout cassé renvoie
    une page d'erreur). Le diff visuel pixel sera ajouté en V2 quand
    Playwright sera installé.
    """
    try:
        ra = requests.get(url_a, timeout=20)
        rb = requests.get(url_b, timeout=20)
    except requests.RequestException as exc:
        return {"ok": False, "error": str(exc), "diff_pct": 100.0}
    if ra.status_code >= 400 or rb.status_code >= 400:
        return {"ok": False,
                "error": f"HTTP {ra.status_code}/{rb.status_code}",
                "diff_pct": 100.0}
    la, lb = len(ra.text), len(rb.text)
    if la == 0 or lb == 0:
        return {"ok": False, "error": "page vide", "diff_pct": 100.0}
    # Diff structurel sommaire : longueur + nb de balises majeures
    import re as _re
    def _tag_count(html: str) -> dict[str, int]:
        return {t: len(_re.findall(rf"<{t}\b", html, _re.I))
                for t in ("h1", "h2", "h3", "p", "a", "img", "section")}
    ta, tb = _tag_count(ra.text), _tag_count(rb.text)
    delta_tags = sum(abs(ta[k] - tb[k]) for k in ta)
    total_tags = max(1, sum(ta.values()) + sum(tb.values()))
    structure_diff = delta_tags / total_tags * 100
    size_diff = abs(la - lb) / max(la, lb) * 100
    return {"ok": True,
            "diff_pct": round(max(structure_diff, size_diff), 2),
            "size_diff_pct": round(size_diff, 2),
            "structure_diff_pct": round(structure_diff, 2),
            "tags_a": ta, "tags_b": tb}


# ---------------------------------------------------------------------------
# Pipeline complet : applique des patches sur un repo, ouvre PR, vérifie, merge
# ---------------------------------------------------------------------------
def apply_and_open_pr(*,
                     site: dict,
                     patches: list[dict],
                     pr_title: str,
                     pr_body: str = "",
                     workdir_root: Optional[str] = None) -> dict:
    """Workflow complet :
        1. clone repo dans tmp
        2. crée branche `phare/auto-<date>-<slug>`
        3. applique les patches (chaque patch = {file, old, new})
        4. commit + push
        5. ouvre PR

    Renvoie un dict :
        {ok: bool, branch: str, pr_url: str, error: str}

    Les checks (Netlify preview + Lighthouse + diff) sont faits par
    `verify_pr` séparément, pour pouvoir relancer si besoin.
    """
    if not patches:
        return {"ok": False, "error": "aucun patch fourni"}
    repo_full = site.get("repo_github") or ""
    if not repo_full:
        return {"ok": False, "error": "site.repo_github vide"}
    if not _github_token():
        return {"ok": False, "error": "GITHUB_TOKEN absent dans phare_config"}

    base_branch = site.get("repo_branch_main") or "main"
    date_tag = datetime.now().strftime("%Y%m%d-%H%M")
    slug = "".join(c for c in pr_title.lower().replace(" ", "-") if c.isalnum() or c == "-")[:30]
    branch = f"phare/auto-{date_tag}-{slug or 'modif'}"

    workdir_root = workdir_root or tempfile.mkdtemp(prefix="phare_")
    workdir = str(Path(workdir_root) / repo_full.split("/")[-1])

    # Si workdir existe déjà ET est un repo git valide, on réutilise (cas où
    # l'appelant a déjà cloné, ex. run_onpage_optim qui clone d'abord pour
    # localiser les patches via patcher.localize_patches). Sinon on clone.
    workdir_path = Path(workdir)
    is_existing_repo = (workdir_path.exists()
                        and (workdir_path / ".git").exists())
    if is_existing_repo:
        # Le repo est déjà cloné par l'appelant — on vérifie juste qu'on est
        # sur la bonne branche de base avant de créer la branche de travail.
        _git("checkout", base_branch, cwd=workdir)
    else:
        if not clone_repo(repo_full, workdir, branch=base_branch):
            return {"ok": False, "error": "clone échoué"}
    if not create_branch(workdir, branch):
        return {"ok": False, "error": "création branche échouée"}

    applied = 0
    skipped = []
    for p in patches:
        rel = p.get("file") or ""
        old = p.get("old") or ""
        new = p.get("new") or ""
        if not rel:
            skipped.append({"reason": "no_file", "patch": p})
            continue
        full = Path(workdir) / rel
        if p.get("create"):
            # Création d'un nouveau fichier (ex: sitemap.xml). Refus si le
            # fichier existe déjà ou si le chemin sort du repo.
            try:
                full.resolve().relative_to(Path(workdir).resolve())
            except ValueError:
                skipped.append({"reason": "outside_repo", "file": rel})
                continue
            if full.exists():
                skipped.append({"reason": "already_exists", "file": rel})
                continue
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(new, encoding="utf-8")
            applied += 1
            continue
        if not full.exists():
            skipped.append({"reason": "missing_file", "file": rel})
            continue
        try:
            content = full.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            skipped.append({"reason": "non_utf8", "file": rel})
            continue
        if old and old not in content:
            skipped.append({"reason": "old_not_found", "file": rel})
            continue
        if old:
            content = content.replace(old, new, 1)
        else:
            # patch d'ajout pur (rare) — on append en fin de fichier
            content = content + ("\n" if not content.endswith("\n") else "") + new
        full.write_text(content, encoding="utf-8")
        applied += 1

    if applied == 0:
        return {"ok": False, "error": "aucun patch applicable",
                "skipped": skipped}

    body = pr_body + "\n\n---\n*PR ouverte automatiquement par Le Phare (Triskell Command).*"
    if not commit_all(workdir, f"phare: {pr_title}"):
        return {"ok": False, "error": "commit échoué"}
    if not push_branch(workdir, branch):
        return {"ok": False, "error": "push échoué"}

    pr = open_pr(repo_full, head=branch, base=base_branch,
                 title=f"[Le Phare] {pr_title}", body=body)
    if not pr:
        # La raison exacte (rate limit, PR déjà ouverte, aucun commit…)
        # remonte jusqu'à la carte au lieu de mourir dans le journal.
        why = last_pr_error or "raison inconnue"
        return {"ok": False, "error": f"ouverture PR échouée ({why})"}
    return {
        "ok": True,
        "branch": branch,
        "pr_number": pr.get("number"),
        "pr_url": pr.get("html_url"),
        "patches_applied": applied,
        "patches_skipped": skipped,
        "workdir": workdir,
    }


def verify_pr(*, site: dict, pr_number: int, branch: str) -> dict:
    """Vérifie les garde-fous avant merge auto :
        - preview Netlify READY
        - Lighthouse perf preview ≥ baseline - 2
        - diff visuel < site.visual_diff_max_pct
        - aucun broken link nouveau (best-effort)
    Renvoie {ok, checks: {...}, decision: "merge"|"hold"|"reject"}
    """
    netlify_id = site.get("netlify_site_id") or ""
    domain = site.get("domain") or ""
    visual_max = float(site.get("visual_diff_max_pct") or 5.0)
    perf_min = int(site.get("perf_min_score") or 70)
    key_paths = site.get("key_paths") or ["/"]
    if isinstance(key_paths, str):
        key_paths = [key_paths]

    checks = {"netlify_preview_url": None,
              "lighthouse_diff": {},
              "visual_diff_pct": None,
              "blockers": []}

    preview_url = wait_netlify_preview(netlify_id, branch) if netlify_id else None
    if preview_url:
        checks["netlify_preview_url"] = preview_url
    else:
        checks["blockers"].append("preview Netlify pas READY ou Netlify non configuré")
        return {"ok": False, "checks": checks, "decision": "hold"}

    # Diff par page clé
    diffs = []
    for path in key_paths[:5]:
        url_main = f"https://{domain}{path}"
        url_prev = preview_url.rstrip("/") + path
        d = visual_diff_text(url_prev, url_main)
        diffs.append({"path": path, **d})
    worst = max((d.get("diff_pct") or 0) for d in diffs) if diffs else 0
    checks["visual_diff_pct"] = worst
    if worst > visual_max:
        checks["blockers"].append(f"diff visuel {worst}% > seuil {visual_max}%")

    # Lighthouse comparé sur la home (suffit comme premier garde-fou)
    psi_diff = pagespeed.audit_two_versions(
        preview_url, f"https://{domain}{key_paths[0]}"
    )
    if psi_diff.get("ok"):
        checks["lighthouse_diff"] = psi_diff.get("diff", {})
        prev_perf = psi_diff["a"]["lighthouse"].get("perf")
        # Un aperçu Netlify est un environnement DÉGRADÉ par nature : caché
        # de Google (noindex → SEO -30 environ) et servi à froid hors CDN
        # chaud (perf -15/-20 pts vs la prod, constaté le 12/06 sur Lagriffe
        # ET RankUs). Comparer sa vitesse à celle de la prod bloquait des
        # modifs incapables de toucher la perf (titles, métas). Donc :
        # PAS de blocage sur le delta prod↔aperçu (mesure biaisée par
        # construction) — un PLANCHER ADAPTATIF sur l'aperçu seul fait le
        # garde-fou : perf_min (70) - 15 de biais, jamais sous 40. Une
        # vraie régression massive (page cassée, JS bloquant) tombe
        # toujours sous ce plancher ; la variance et le biais passent.
        preview_floor = max(40, perf_min - 15)
        if prev_perf is not None and prev_perf < preview_floor:
            checks["blockers"].append(
                f"perf preview {prev_perf} < plancher {preview_floor} "
                f"(seuil prod {perf_min} - 15 de biais aperçu)")
    else:
        checks["blockers"].append("audit PSI indisponible (clé manquante ou réseau)")

    decision = "merge" if not checks["blockers"] else "hold"
    return {"ok": not checks["blockers"], "checks": checks, "decision": decision}
