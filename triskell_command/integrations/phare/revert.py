"""Annulation d'une modification publiée par Le Phare (décision Jordan 12/06).

Le « vrai bouton Annuler » : pour une action 'merged' liée à une PR GitHub,
on fabrique le commit INVERSE (git revert) sur une branche dédiée, on ouvre
une PR d'annulation et on la merge directement — l'utilisateur vient de
confirmer l'annulation dans l'app, pas besoin d'un second tour au bac.

Garde-fous :
- action sans PR (simple conseil) → rien n'a été publié, rien à annuler ;
- déjà annulée (status != merged) → refus ;
- revert en conflit (le fichier a été modifié depuis cette publication)
  → on s'arrête proprement, RIEN n'est poussé, message en français ;
- la PR d'annulation qui ne peut pas être mergée → on renvoie son URL pour
  finir à la main sur GitHub.

Module volontairement SÉPARÉ de l'exécuteur (chantier parallèle) : il ne
réutilise que git_pipeline (clone, push, open_pr, merge_pr) et repo.

Marquage en base : status → 'reverted' (+ reverted_at / revert_pr_url si la
migration 49 est appliquée ; sans elle, le code retombe sur le status seul —
mode dégradé propre, comme les migrations 45/46).
"""

from __future__ import annotations

import logging
import tempfile
from datetime import datetime

import requests

from . import git_pipeline, repo

logger = logging.getLogger(__name__)


def revert_action(action_id: str) -> dict:
    action_id = (action_id or "").strip()
    if not action_id:
        return {"ok": False, "error": "id manquant"}
    sb = repo._sb()
    if sb is None:
        return {"ok": False, "error": "Supabase non configuré"}
    rows = (sb.table("phare_actions").select("*")
            .eq("id", action_id).limit(1).execute().data)
    if not rows:
        return {"ok": False, "error": "action introuvable"}
    action = rows[0]
    if (action.get("status") or "") != "merged":
        return {"ok": False,
                "error": "seule une modification publiée (et pas déjà "
                         "annulée) peut être annulée"}
    pr_url = action.get("github_pr_url") or ""
    if not pr_url:
        return {"ok": False,
                "error": "ce conseil n'a rien publié sur le site — il n'y a "
                         "rien à annuler techniquement"}
    site = repo.get_site(action.get("site_id") or "")
    if not site:
        return {"ok": False, "error": "site introuvable"}
    repo_full = site.get("repo_github") or ""
    if not repo_full:
        return {"ok": False, "error": "dépôt GitHub du site inconnu"}
    token = git_pipeline._github_token()
    if not token:
        return {"ok": False, "error": "GITHUB_TOKEN absent dans phare_config"}

    # 1. Retrouve le commit de publication de la PR d'origine.
    try:
        pr_number = int(pr_url.rstrip("/").split("/")[-1])
    except ValueError:
        return {"ok": False, "error": "lien de PR illisible sur cette action"}
    try:
        r = requests.get(
            f"{git_pipeline.GH_API}/repos/{repo_full}/pulls/{pr_number}",
            headers={"Authorization": f"Bearer {token}",
                     "Accept": "application/vnd.github+json"},
            timeout=30)
        r.raise_for_status()
        pr = r.json()
    except Exception as exc:
        return {"ok": False, "error": f"PR d'origine illisible : {exc}"}
    merge_sha = pr.get("merge_commit_sha") or ""
    if not pr.get("merged_at") or not merge_sha:
        return {"ok": False, "error": "la PR d'origine n'a jamais été publiée"}

    # 2. Clone → revert → push. Les PRs Phare sont mergées en squash
    #    (un seul parent) → revert simple d'abord ; merge classique → -m 1.
    branch = (f"phare/revert-{action_id[:8]}-"
              f"{datetime.now().strftime('%Y%m%d%H%M%S')}")
    with tempfile.TemporaryDirectory(prefix="phare-revert-") as workdir:
        if not git_pipeline.clone_repo(repo_full, workdir):
            return {"ok": False, "error": "clone du dépôt impossible"}
        if not git_pipeline.create_branch(workdir, branch):
            return {"ok": False, "error": "création de la branche impossible"}
        code, out = git_pipeline._git("revert", "--no-edit", merge_sha,
                                      cwd=workdir)
        if code != 0 and "mainline" in (out or "").lower():
            code, out = git_pipeline._git("revert", "--no-edit", "-m", "1",
                                          merge_sha, cwd=workdir)
        if code != 0:
            git_pipeline._git("revert", "--abort", cwd=workdir)
            logger.warning("phare revert %s : conflit — %s",
                           action_id, (out or "")[:300])
            return {"ok": False, "conflict": True,
                    "error": "le site a été modifié depuis cette publication "
                             "— l'annulation automatique toucherait d'autres "
                             "changements. À voir à la main (ou avec Claude)."}
        if not git_pipeline.push_branch(workdir, branch):
            return {"ok": False, "error": "envoi de la branche impossible"}

    # 3. PR d'annulation + publication immédiate (l'utilisateur a confirmé).
    title = f"Annulation : {action.get('title') or action_id}"
    pr_revert = git_pipeline.open_pr(
        repo_full, head=branch, title=title,
        body=(f"Annulation demandée depuis Le Phare (action {action_id}).\n"
              f"Revert du commit {merge_sha} (PR #{pr_number})."))
    if not pr_revert or not pr_revert.get("number"):
        return {"ok": False,
                "error": "ouverture de la PR d'annulation impossible"}
    revert_url = pr_revert.get("html_url") or ""
    if not git_pipeline.merge_pr(repo_full, int(pr_revert["number"]),
                                 commit_title=title):
        return {"ok": False, "pr_url": revert_url,
                "error": "GitHub a refusé la publication de l'annulation — "
                         "elle attend sur la PR (lien fourni)"}

    # 4. Marquage : sort l'action de « Ce qui a été fait » et interdit une
    #    seconde annulation. Mode dégradé si la migration 49 manque.
    marked = repo.update_action(action_id, {
        "status": "reverted",
        "reverted_at": datetime.now().isoformat(),
        "revert_pr_url": revert_url,
    })
    if not marked:
        repo.update_action(action_id, {"status": "reverted"})
    return {"ok": True, "pr_url": revert_url}
