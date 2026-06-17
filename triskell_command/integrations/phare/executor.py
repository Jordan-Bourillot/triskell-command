"""Exécuteur Le Phare — le bouton « OK, fais-le ».

Avant (jusqu'au 12/06/2026) : les recommandations des robots étaient des
conseils que Jordan devait appliquer lui-même. Maintenant : un clic sur la
carte met l'action en file, et un worker la transforme en vraie modification
de code (PR → vérifications → publication), puis la marque « fait ».

Cycle de vie (colonne `apply_state`, migration 48) :
    ""       rien demandé
    queued   Jordan a cliqué — en attente de traitement
    running  un worker s'en occupe
    done     publié (l'action passe en status='merged')
    manual   l'IA a conclu qu'un humain doit le faire (raison dans apply_error)
    failed   erreur technique (raison dans apply_error) — bouton Réessayer

Qui traite la file ?  Triple filet, dans l'ordre :
    1. le serveur web lui-même, en thread, si `git` est installé dessus ;
    2. sinon on réveille le tick GitHub Actions (workflow_dispatch) qui
       appelle process_apply_queue() en tête de cycle (~2 min d'attente) ;
    3. sinon le tick horaire planifié finit toujours par passer.

Garde-fous :
    - seul un clic humain met une action en file (pas d'auto-enrôlement) ;
    - patches minimaux et ciblés (cf. agents.Executeur + patcher) ;
    - vérifications verify_pr quand le site a un preview Netlify ; sans
      preview, le clic de Jordan vaut validation (et rollback_watch
      surveille le trafic 14 j après, comme pour tout merge) ;
    - une action `running` depuis plus de 2 h est marquée failed
      (redémarrage en plein traitement) — jamais de file bloquée.
"""

from __future__ import annotations

import logging
import re
import shutil
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests

from . import agents, git_pipeline, patcher, plain_language, repo

logger = logging.getLogger(__name__)

# Dépôt qui porte le workflow phare_scheduler.yml (tick horaire)
COMMAND_REPO = "Jordan-Bourillot/triskell-command"
TICK_WORKFLOW = "phare_scheduler.yml"

RUNNING_TIMEOUT_HOURS = 2
QUEUE_BATCH = 5

_MIGRATION_HINT = ("La base n'a pas encore la migration 48 "
                   "(supabase/48_apply_queue.sql) — à appliquer dans "
                   "l'éditeur SQL Supabase.")


# ---------------------------------------------------------------------------
# Helpers base
# ---------------------------------------------------------------------------
def _get_action(action_id: str) -> Optional[dict]:
    sb = repo._sb()
    if sb is None:
        return None
    try:
        rows = (sb.table("phare_actions").select("*")
                .eq("id", action_id).limit(1).execute().data)
        return rows[0] if rows else None
    except Exception as exc:
        logger.warning("executor._get_action: %s", exc)
        return None


def _update(action_id: str, patch: dict) -> bool:
    """update_action avec filet : si les colonnes 48 manquent, retente sans
    elles (le changement de status passe au moins)."""
    if repo.update_action(action_id, patch):
        return True
    slim = {k: v for k, v in patch.items()
            if k not in repo._ACTION_OPTIONAL_COLS}
    if slim and len(slim) != len(patch):
        return repo.update_action(action_id, slim)
    return False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Cas déterministes (pas de devinette IA) : images + plan du site
# ---------------------------------------------------------------------------
_IMG_ALT_RE = re.compile(
    r"Page\s*`([^`]+)`[^\n`]*`([^`]+)`\s*\r?\n\s*(?:→|->)\s*`?alt\s*=\s*"
    r"\"([^\"]*)\"",
    re.IGNORECASE)


def _parse_image_seo_alts(detail_md: str) -> list[dict]:
    """Lit la liste « Page `/x` — `img.jpg` → alt="…" » d'une carte Image SEO
    et la transforme en patches alt prêts pour le patcher. Déterministe :
    l'alt a déjà été écrit par l'AltGenerator au moment de l'audit."""
    patches: list[dict] = []
    for m in _IMG_ALT_RE.finditer(detail_md or ""):
        page_path, image, alt = (m.group(1).strip(), m.group(2).strip(),
                                 m.group(3).strip())
        if image and alt:
            patches.append({"field": "alt", "page_path": page_path,
                            "image": image, "new": alt})
    return patches


def _sitemap_equivalent(a: str, b: str) -> bool:
    """Deux sitemaps couvrent-ils les mêmes URLs ? (on ignore les <lastmod>,
    qui changent chaque jour — sinon on republierait pour rien)."""
    def _locs(s: str) -> set:
        return set(re.findall(r"<loc>\s*(.*?)\s*</loc>", s or "",
                              re.IGNORECASE | re.DOTALL))
    return _locs(a) == _locs(b)


def _apply_sitemap(action_id: str, action: dict, site: dict, *,
                   app_state=None) -> dict:
    """« OK, fais-le » sur une carte « plan du site » : on régénère le
    sitemap.xml à partir des pages connues (la source de vérité) et on le
    crée ou le met à jour. Si le fichier existe déjà et couvre les mêmes
    pages → rien à faire (fini la boucle « Réessayer » qui échouait toujours)."""
    from . import sitemap as sitemap_mod
    pages = repo.list_pages(site["id"], limit=5000)
    if not pages:
        return _manual(action_id,
                       "Le robot n'a pas encore la liste de tes pages — "
                       "relance d'abord un audit du site.")
    xml = sitemap_mod.generate_sitemap_xml(site, pages)

    workdir_root = tempfile.mkdtemp(prefix="phare_sitemap_")
    try:
        workdir = str(Path(workdir_root) / site["repo_github"].split("/")[-1])
        if not git_pipeline.clone_repo(
                site["repo_github"], workdir,
                branch=site.get("repo_branch_main") or "main"):
            return _fail(action_id, "Impossible de récupérer le code du site.")

        rel, existing = patcher.resolve_sitemap_target(workdir)
        if existing is not None and _sitemap_equivalent(existing, xml):
            _update(action_id, {
                "status": "merged", "merged_at": _now_iso(),
                "auto_merged": False, "apply_state": "done", "apply_error": "",
                "simple_md": "Ton plan de site est déjà à jour — rien à changer.",
            })
            return {"ok": True, "action_id": action_id, "done": True,
                    "noop": True}

        if existing is None:
            patch = {"file": rel, "old": "", "new": xml, "create": True}
        else:
            patch = {"file": rel, "old": existing, "new": xml}

        pr = git_pipeline.apply_and_open_pr(
            site=site, patches=[patch],
            pr_title=action.get("title") or "Plan du site (sitemap.xml)",
            pr_body=("Mise à jour du plan du site avec toutes les pages "
                     "connues.\n\n---\nDemandé par Jordan via « OK, fais-le » "
                     "(Le Phare)."),
            workdir_root=workdir_root)
        if not pr.get("ok"):
            return _fail(action_id, "La préparation de la modification a "
                         f"échoué : {pr.get('error') or '?'}")
        return _verify_and_merge(
            action_id, action, site,
            pr_number=pr["pr_number"], branch=pr.get("branch") or "",
            pr_url=pr.get("pr_url") or "",
            simple_md=("J'ai mis à jour le plan de ton site — la liste de "
                       "toutes tes pages pour Google."),
            files=[rel])
    finally:
        shutil.rmtree(workdir_root, ignore_errors=True)


# ---------------------------------------------------------------------------
# Entrée : le clic de Jordan
# ---------------------------------------------------------------------------
def request_apply(action_id: str, *, app_state=None) -> dict:
    """Met une action en file et tente de la traiter tout de suite.

    Renvoie {ok, mode: 'server'|'github_actions'|'next_tick'} — l'UI
    adapte son message d'attente au mode.
    """
    action = _get_action(action_id)
    if not action:
        return {"ok": False, "error": "Action introuvable."}
    status = (action.get("status") or "").lower()
    has_pr = bool((action.get("github_pr_url") or "").strip())
    if has_pr and (action.get("apply_state") or "") != "failed":
        return {"ok": False,
                "error": "La modification est déjà préparée — utilise « Publier sur le site »."}
    if status not in ("draft", "pending_review") and not has_pr:
        return {"ok": False, "error": "Cette carte n'est plus en attente."}
    if (action.get("apply_state") or "") in ("queued", "running"):
        return {"ok": True, "mode": "already", "already": True}

    site = repo.get_site(action.get("site_id") or "")
    if not has_pr:
        # Reprise d'une PR existante : pas de classification — on sait déjà
        # quoi faire (re-vérifier et publier).
        verdict = plain_language.classify_for_apply(action, site)
        if not verdict.get("can"):
            return {"ok": False, "error": verdict.get("why") or
                    "Cette proposition ne peut pas être faite par le robot."}

    # Mise en file — c'est ici qu'on détecte l'absence de migration 48
    sb = repo._sb()
    if sb is None:
        return {"ok": False, "error": "Connexion à la base impossible."}
    try:
        sb.table("phare_actions").update({
            "apply_state": "queued",
            "apply_error": "",
            "apply_requested_at": _now_iso(),
        }).eq("id", action_id).execute()
    except Exception as exc:
        msg = str(exc)
        if "column" in msg.lower() or "PGRST204" in msg:
            return {"ok": False, "error": _MIGRATION_HINT}
        return {"ok": False, "error": f"Mise en file impossible : {msg[:200]}"}

    # Traitement immédiat si possible
    if shutil.which("git") and git_pipeline._github_token():
        threading.Thread(
            target=lambda: _process_safely(action_id, app_state=app_state),
            daemon=True, name=f"PhareApply-{action_id[:8]}",
        ).start()
        return {"ok": True, "mode": "server"}
    if _dispatch_tick_workflow():
        return {"ok": True, "mode": "github_actions"}
    return {"ok": True, "mode": "next_tick"}


def retry_apply(action_id: str, *, app_state=None) -> dict:
    """Remet en file une action `failed` (bouton Réessayer)."""
    action = _get_action(action_id)
    if not action:
        return {"ok": False, "error": "Action introuvable."}
    if (action.get("apply_state") or "") not in ("failed", "manual"):
        return {"ok": False, "error": "Cette carte n'est pas en échec."}
    _update(action_id, {"apply_state": "", "apply_error": ""})
    return request_apply(action_id, app_state=app_state)


def _dispatch_tick_workflow() -> bool:
    """Réveille le workflow GitHub Actions tout de suite (workflow_dispatch)."""
    token = git_pipeline._github_token()
    if not token:
        return False
    try:
        r = requests.post(
            f"{git_pipeline.GH_API}/repos/{COMMAND_REPO}/actions/workflows/"
            f"{TICK_WORKFLOW}/dispatches",
            headers={"Authorization": f"Bearer {token}",
                     "Accept": "application/vnd.github+json"},
            json={"ref": "main"}, timeout=15,
        )
        return r.status_code == 204
    except requests.RequestException as exc:
        logger.debug("executor dispatch workflow: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Worker : traite la file
# ---------------------------------------------------------------------------
def process_apply_queue(*, app_state=None, max_items: int = QUEUE_BATCH) -> dict:
    """Traite jusqu'à `max_items` actions en file. Appelé en tête du tick
    du scheduler (GitHub Actions et serveur) + en direct après un clic."""
    sb = repo._sb()
    if sb is None:
        return {"ok": False, "error": "supabase indisponible", "processed": 0}

    # Répare les zombies (running trop vieux = process mort en route)
    try:
        cutoff = (datetime.now(timezone.utc)
                  - timedelta(hours=RUNNING_TIMEOUT_HOURS)).isoformat()
        zombies = (sb.table("phare_actions").select("id,apply_requested_at")
                   .eq("apply_state", "running")
                   .lt("apply_requested_at", cutoff)
                   .execute().data) or []
        for z in zombies:
            _update(z["id"], {
                "apply_state": "failed",
                "apply_error": ("Le traitement a été interrompu par un "
                                "redémarrage — clique sur Réessayer."),
            })
    except Exception as exc:
        logger.debug("executor zombies: %s", exc)

    try:
        queued = (sb.table("phare_actions").select("*")
                  .eq("apply_state", "queued")
                  .order("apply_requested_at", desc=False)
                  .limit(max_items).execute().data) or []
    except Exception as exc:
        msg = str(exc)
        if "column" in msg.lower() or "PGRST204" in msg:
            return {"ok": True, "processed": 0, "skipped": "migration_48_absente"}
        return {"ok": False, "error": msg[:200], "processed": 0}

    results = []
    for action in queued:
        results.append(_process_safely(action["id"], app_state=app_state))
    return {"ok": True, "processed": len(results), "results": results}


def _process_safely(action_id: str, *, app_state=None) -> dict:
    """_apply_one blindé : toute exception finit en apply_state='failed'."""
    try:
        return _apply_one(action_id, app_state=app_state)
    except Exception as exc:
        logger.exception("executor._apply_one(%s): %s", action_id, exc)
        _update(action_id, {"apply_state": "failed",
                            "apply_error": str(exc)[:400]})
        return {"ok": False, "action_id": action_id, "error": str(exc)[:200]}


def _apply_one(action_id: str, *, app_state=None) -> dict:
    action = _get_action(action_id)
    if not action:
        return {"ok": False, "error": "action introuvable"}
    if (action.get("apply_state") or "") not in ("queued", "running"):
        return {"ok": True, "skipped": "plus en file", "action_id": action_id}
    status = (action.get("status") or "").lower()
    has_pr = bool((action.get("github_pr_url") or "").strip())
    if status not in ("draft", "pending_review") and not (has_pr and status == "preview"):
        _update(action_id, {"apply_state": ""})
        return {"ok": True, "skipped": "déjà traitée", "action_id": action_id}

    _update(action_id, {"apply_state": "running"})
    site = repo.get_site(action.get("site_id") or "")
    if not site:
        return _fail(action_id, "Site introuvable.")

    if has_pr:
        # Reprise : la modification a déjà été préparée lors d'un essai
        # précédent — on ne refabrique rien, on re-vérifie et on publie.
        try:
            pr_number = int((action.get("github_pr_url") or "")
                            .rstrip("/").split("/")[-1])
        except ValueError:
            return _fail(action_id, "Lien de la modification préparée illisible.")
        return _verify_and_merge(
            action_id, action, site,
            pr_number=pr_number,
            branch=action.get("branch") or "",
            pr_url=action.get("github_pr_url") or "",
            simple_md=(action.get("simple_md") or "").strip(),
            files=action.get("files_touched") or [])

    verdict = plain_language.classify_for_apply(action, site)
    mode = verdict.get("mode")

    if mode == "tool":
        # « Mesurer la vitesse » & co : on relance un audit complet, qui
        # remplit Lighthouse/CWV. Import local pour éviter le cycle.
        from . import orchestrator
        r = orchestrator.run_audit(site["id"], app_state=app_state)
        if not r.get("ok"):
            return _fail(action_id,
                         f"La mesure n'a pas pu être lancée : {r.get('error') or '?'}")
        return _done(action_id, action, site,
                     simple_md=("J'ai relancé la mesure complète du site "
                                "(vitesse comprise). Les chiffres arrivent "
                                "dans l'audit d'ici quelques minutes."))

    if mode in ("info", "manual") or not verdict.get("can"):
        return _manual(action_id, verdict.get("why") or
                       "À faire à la main — le robot ne peut pas s'en charger.")

    # --- mode "code" : recommandation → patches → PR → publication -------
    if not (site.get("repo_github") or "").strip():
        return _manual(action_id,
                       "Le site n'est pas encore relié à son code — "
                       "à brancher dans « Réglages du site ».")
    if not git_pipeline._github_token():
        return _fail(action_id, "Jeton GitHub manquant dans la configuration.")
    if not shutil.which("git"):
        return _fail(action_id,
                     "git n'est pas installé ici — le tick GitHub Actions "
                     "prendra le relais au prochain passage.")

    agent_name = (action.get("agent") or "").lower()
    # Plan du site : régénération déterministe (jamais via l'IA, qui ne
    # connaît pas toutes les URLs et bloquait quand le fichier existait déjà).
    if agent_name == "sitemap_builder":
        return _apply_sitemap(action_id, action, site, app_state=app_state)

    pages = repo.list_pages(site["id"], limit=200)
    if agent_name == "image_seo":
        # Les textes des images ont déjà été écrits à l'audit : on les pose
        # directement, sans repasser par l'IA.
        patches = _parse_image_seo_alts(action.get("detail_md") or "")
        if not patches:
            return _manual(action_id,
                           "Aucune image à décrire ici — rien à faire "
                           "automatiquement.")
        out = {"mode": "patches", "patches": patches,
               "simple_md": ("J'ajoute le petit texte qui décrit tes images "
                             "(ce que Google lit à la place de l'image).")}
    else:
        try:
            ag = agents.Executeur()
            out = ag.run(site=site, action=action, pages=pages,
                         app_state=app_state)
        except Exception as exc:
            return _fail(action_id,
                         f"L'IA exécutrice n'a pas répondu : {str(exc)[:200]}")

    if (out.get("mode") or "") == "manual" or not (out.get("patches") or []):
        why = (out.get("manual_reason") or out.get("simple_md")
               or "Le robot a regardé : c'est à faire à la main.")
        return _manual(action_id, why)

    simple_md = (out.get("simple_md") or "").strip()

    workdir_root = tempfile.mkdtemp(prefix="phare_exec_")
    try:
        workdir = str(Path(workdir_root) / site["repo_github"].split("/")[-1])
        if not git_pipeline.clone_repo(site["repo_github"], workdir,
                                       branch=site.get("repo_branch_main") or "main"):
            return _fail(action_id, "Impossible de récupérer le code du site.")

        loc = patcher.localize_executor_patches(
            workdir, (site.get("stack") or "any").lower(),
            out.get("patches") or [], pages)
        if not loc["applicable"]:
            reasons = "; ".join(r.get("reason") or "?" for r in loc["needs_review"][:3])
            if agent_name == "image_seo":
                # Images décoratives / introuvables : ce n'est pas un échec,
                # juste rien à faire — message clair, pas de « Réessayer ».
                return _manual(action_id,
                               "Ces images n'ont pas besoin qu'on y touche "
                               f"({reasons or 'rien à corriger'}).")
            return _fail(action_id,
                         "Le robot n'a pas retrouvé l'endroit exact à modifier "
                         f"dans le code ({reasons or 'aucun patch'}). "
                         "Rien n'a été changé.")

        pr_body = (simple_md or action.get("title") or "")
        pr_body += "\n\n---\nDemandé par Jordan via « OK, fais-le » (Le Phare)."
        detail = (action.get("detail_md") or "").strip()
        if detail:
            pr_body += f"\n\nRecommandation d'origine :\n{detail[:1500]}"
        pr = git_pipeline.apply_and_open_pr(
            site=site, patches=loc["applicable"],
            pr_title=action.get("title") or "Modification Le Phare",
            pr_body=pr_body, workdir_root=workdir_root)
        if not pr.get("ok"):
            return _fail(action_id,
                         f"La préparation de la modification a échoué : "
                         f"{pr.get('error') or '?'}")

        return _verify_and_merge(
            action_id, action, site,
            pr_number=pr["pr_number"], branch=pr.get("branch") or "",
            pr_url=pr.get("pr_url") or "", simple_md=simple_md,
            files=[p.get("file") for p in loc["applicable"] if p.get("file")])
    finally:
        shutil.rmtree(workdir_root, ignore_errors=True)


def _verify_and_merge(action_id: str, action: dict, site: dict, *,
                      pr_number: int, branch: str, pr_url: str,
                      simple_md: str = "", files: Optional[list] = None) -> dict:
    """Vérifie puis publie une modification préparée (PR ouverte).

    Le clic de Jordan vaut validation humaine : un contrôle IMPOSSIBLE
    (pas de preview Netlify, pas de clé de mesure de vitesse) ne bloque
    pas la publication — seule une RÉGRESSION mesurée bloque (page
    cassée, gros changement visuel, vitesse qui chute). rollback_watch
    surveille le trafic 14 jours derrière, comme pour tout merge.
    """
    blockers: list[str] = []
    if (site.get("netlify_site_id") or "").strip():
        v = git_pipeline.verify_pr(site=site, pr_number=pr_number,
                                   branch=branch)
        checks = v.get("checks") or {}
        blockers = [b for b in (checks.get("blockers") or [])
                    if "Netlify non configuré" not in b
                    and "PSI indisponible" not in b]
    if blockers:
        _update(action_id, {
            "status": "preview",
            "kind": "pr_modif",
            "branch": branch,
            "github_pr_url": pr_url,
            "apply_state": "failed",
            "apply_error": ("Les vérifications automatiques bloquent la "
                            "publication : " + " · ".join(blockers[:3])),
            "simple_md": simple_md,
            "files_touched": files or [],
        })
        return {"ok": False, "action_id": action_id,
                "error": "vérifications bloquantes", "pr_url": pr_url}

    if not git_pipeline.merge_pr(site["repo_github"], pr_number,
                                 commit_title=f"phare: {action.get('title') or ''}"):
        _update(action_id, {
            "status": "preview", "kind": "pr_modif",
            "branch": branch,
            "github_pr_url": pr_url,
            "apply_state": "failed",
            "apply_error": ("La modification est prête mais la publication "
                            "a échoué — réessaie, ou publie-la depuis la carte."),
            "simple_md": simple_md,
        })
        return {"ok": False, "action_id": action_id, "error": "merge KO"}

    return _done(action_id, action, site, simple_md=simple_md,
                 extra={"kind": "pr_modif",
                        "branch": branch,
                        "github_pr_url": pr_url,
                        "files_touched": files or []})


# ---------------------------------------------------------------------------
# Fins de traitement
# ---------------------------------------------------------------------------
def _done(action_id: str, action: dict, site: dict, *,
          simple_md: str = "", extra: Optional[dict] = None) -> dict:
    patch = {
        "status": "merged",
        "merged_at": _now_iso(),
        "auto_merged": False,      # un humain a cliqué — pas l'auto-merge
        "apply_state": "done",
        "apply_error": "",
    }
    if simple_md:
        patch["simple_md"] = simple_md
    patch.update(extra or {})
    _update(action_id, patch)
    try:
        from . import notifications
        notifications.notify_auto_merged(site=site,
                                         action={**action, **patch})
    except Exception as exc:
        logger.debug("executor notify: %s", exc)
    return {"ok": True, "action_id": action_id, "done": True}


def _manual(action_id: str, why: str) -> dict:
    _update(action_id, {"apply_state": "manual", "apply_error": why[:400]})
    return {"ok": True, "action_id": action_id, "manual": True, "why": why}


def _fail(action_id: str, why: str) -> dict:
    _update(action_id, {"apply_state": "failed", "apply_error": why[:400]})
    return {"ok": False, "action_id": action_id, "error": why}
