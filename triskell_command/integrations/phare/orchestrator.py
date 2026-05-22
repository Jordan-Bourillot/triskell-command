"""Chef d'orchestre Le Phare — coordonne les missions sur l'écosystème.

Couche au-dessus des agents et du pipeline Git. Orchestre :
- les audits techniques (crawler + PSI + Auditeur)
- la veille mots-clés (GSC + DataForSEO + Veilleur)
- l'optimisation on-page (page → Optimiseur → patches → PR)
- le maillage (Tisseur intra + inter-sites)
- la chasse backlinks (DataForSEO + Chasseur)
- le bulletin Analyste
- le plan stratégique mensuel (Chef d'Orchestre Opus)

Toutes les missions sont synchrones et idempotentes : si Supabase ou Anthropic
indisponibles, retourne un dict {ok: False, error: ...} sans planter.
"""

from __future__ import annotations

import logging
import os
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from . import (
    agents, crawler, dataforseo, git_pipeline, gsc, pagespeed, patcher, repo
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Mission 1 — Audit technique d'un site
# ---------------------------------------------------------------------------
def run_audit(site_id: str, *, app_state=None) -> dict:
    site = repo.get_site(site_id)
    if not site:
        return {"ok": False, "error": "site introuvable"}
    domain = site.get("domain") or ""
    logger.info("phare.audit %s", domain)

    # Crawl
    key_paths = site.get("key_paths") or ["/"]
    if isinstance(key_paths, str):
        key_paths = [key_paths]
    crawl = crawler.crawl_site(domain, start_paths=key_paths, max_pages=50)
    pages = crawl.get("pages", [])
    repo.upsert_pages(site_id, pages)

    # PageSpeed sur la home
    home_url = f"https://{domain}{key_paths[0]}"
    psi = pagespeed.audit_url(home_url)

    # Agent Auditeur
    try:
        ag = agents.AuditeurTechnique()
        analysis = ag.run(site=site, crawl=crawl, psi=psi, app_state=app_state)
    except Exception as exc:
        logger.warning("Auditeur LLM: %s", exc)
        analysis = {}

    # Persistance
    audit_row = {
        "site_id": site_id,
        "lighthouse_perf": (psi.get("lighthouse") or {}).get("perf"),
        "lighthouse_seo": (psi.get("lighthouse") or {}).get("seo"),
        "lighthouse_a11y": (psi.get("lighthouse") or {}).get("a11y"),
        "lighthouse_bp": (psi.get("lighthouse") or {}).get("bp"),
        "cwv_lcp": (psi.get("cwv") or {}).get("lcp"),
        "cwv_inp": (psi.get("cwv") or {}).get("inp"),
        "cwv_cls": (psi.get("cwv") or {}).get("cls"),
        "pages_crawled": len(pages),
        "broken_links": len(crawl.get("broken_links", [])),
        "redirects_chain": crawl.get("redirects", 0),
        "schema_score": analysis.get("health_score"),
        "issues": analysis.get("critical_issues") or [],
        "summary_md": analysis.get("summary_md") or "",
    }
    audit = repo.insert_audit(audit_row)

    # Quick wins → actions de type "recommandation"
    for qw in (analysis.get("quick_wins") or [])[:5]:
        repo.insert_action({
            "site_id": site_id,
            "agent": "auditeur",
            "kind": "recommandation",
            "title": qw.get("title", "Quick win"),
            "detail_md": (qw.get("fix_hint") or "") + "\n\nPage: " + (qw.get("page_or_global") or ""),
            "status": "draft",
            "impact": 3, "effort": 2,
        })

    return {"ok": True, "audit_id": (audit or {}).get("id"),
            "summary": analysis, "crawled_pages": len(pages)}


# ---------------------------------------------------------------------------
# Mission 2 — Veille mots-clés d'un site
# ---------------------------------------------------------------------------
def run_keywords(site_id: str, *, app_state=None) -> dict:
    site = repo.get_site(site_id)
    if not site:
        return {"ok": False, "error": "site introuvable"}
    domain = site.get("domain") or ""

    top_q = gsc.fetch_top_queries(domain, days=28, limit=50)
    top_p = gsc.fetch_top_pages(domain, days=28, limit=30)
    serp_examples: list[dict] = []
    for q in [r["query"] for r in top_q[:5] if r.get("query")]:
        serp_examples.extend(dataforseo.serp_top10(q)[:5])

    try:
        ag = agents.VeilleurMotsCles()
        plan = ag.run(site=site, top_queries=top_q, top_pages=top_p,
                      serp_examples=serp_examples, app_state=app_state)
    except Exception as exc:
        logger.warning("Veilleur LLM: %s", exc)
        plan = {}

    primary = plan.get("primary_keywords") or []
    long_tail = plan.get("long_tail") or []
    # Enrichit avec volumes DataForSEO si dispo
    kws_to_check = [k.get("keyword") for k in primary + long_tail if k.get("keyword")]
    volumes = {v["keyword"].lower(): v for v in dataforseo.search_volume(kws_to_check)}
    persisted = []
    for k in primary + long_tail:
        kw = k.get("keyword", "")
        v = volumes.get(kw.lower(), {})
        persisted.append({
            "keyword": kw,
            "volume": v.get("volume", k.get("estimated_volume", 0)),
            "difficulty": 0,
            "intent": k.get("intent") or "informational",
            "target_url": k.get("target_url_hint") or "",
        })
    inserted = repo.upsert_keywords(site_id, persisted)

    # Recommandation cluster
    if plan.get("cluster_pivot"):
        repo.insert_action({
            "site_id": site_id, "agent": "veilleur", "kind": "recommandation",
            "title": f"Cluster sémantique : {plan['cluster_pivot']}",
            "detail_md": "Sous-thèmes proposés : " + ", ".join(plan.get("cluster_subthemes") or []),
            "status": "draft", "impact": 4, "effort": 4,
        })

    return {"ok": True, "keywords_persisted": inserted, "plan": plan}


# ---------------------------------------------------------------------------
# Mission 3 — Optimisation on-page d'une page
# ---------------------------------------------------------------------------
def run_onpage_optim(site_id: str, page_path: str = "/",
                     target_keyword: str = "",
                     *, auto_open_pr: bool = True,
                     app_state=None) -> dict:
    """Optimise une page : Optimiseur On-Page → patches → (optionnel) PR."""
    site = repo.get_site(site_id)
    if not site:
        return {"ok": False, "error": "site introuvable"}
    pages = repo.list_pages(site_id, limit=500)
    page = next((p for p in pages if p.get("path") == page_path), None)
    if not page:
        return {"ok": False, "error": f"page {page_path} pas dans phare_pages"}

    try:
        ag = agents.OptimiseurOnPage()
        out = ag.run(site=site, page=page, target_keyword=target_keyword,
                     app_state=app_state)
    except Exception as exc:
        logger.warning("OptimiseurOnPage LLM: %s", exc)
        out = {}

    abstract_patches = out.get("patches") or []
    if not abstract_patches:
        return {"ok": False, "error": "aucun patch proposé", "agent_output": out}

    # Si auto_open_pr ET repo configuré ET token GitHub posé : on tente
    # la conversion patches abstraits → patches fichier via patcher,
    # puis on ouvre une vraie PR. Sinon on stocke en recommandation.
    pr_result = None
    needs_review: list[dict] = []
    file_patches: list[dict] = []

    can_open_pr = (
        auto_open_pr
        and site.get("repo_github")
        and (repo.get_config().get("github_token")
             or os.environ.get("GITHUB_TOKEN", ""))
    )

    if can_open_pr:
        # 1. Clone temporaire
        workdir_root = tempfile.mkdtemp(prefix="phare_patcher_")
        workdir = str(Path(workdir_root) / site["repo_github"].split("/")[-1])
        if git_pipeline.clone_repo(site["repo_github"], workdir,
                                    branch=site.get("repo_branch_main") or "main"):
            # 2. Localisation des patches
            stack = (site.get("stack") or "any").lower()
            loc = patcher.localize_patches(workdir, stack, abstract_patches)
            file_patches = loc["applicable"]
            needs_review = loc["needs_review"]
            # 3. Si au moins 1 patch applicable, on ouvre une vraie PR
            if file_patches:
                pr_result = git_pipeline.apply_and_open_pr(
                    site=site,
                    patches=file_patches,
                    pr_title=f"Optim on-page {page_path}",
                    pr_body=(out.get("summary_md") or "")
                    + (f"\n\nPatches appliqués: {len(file_patches)}.")
                    + (f"\nNeeds review (non poussé) : {len(needs_review)}."
                       if needs_review else ""),
                    workdir_root=workdir_root,
                )

    detail_lines = [out.get("summary_md") or ""]
    if file_patches:
        detail_lines.append(f"\n**{len(file_patches)} patches fichier** "
                             "appliqués (cf. PR liée).")
    if needs_review:
        detail_lines.append(f"\n**{len(needs_review)} patches en review** "
                             "(localisation ambiguë) :")
        for r in needs_review[:6]:
            detail_lines.append(
                f"- `{r['field']}` — {r['reason']} — "
                f"candidates: {r.get('candidates') or ['aucun']}"
            )

    action = repo.insert_action({
        "site_id": site_id,
        "agent": "optimiseur_onpage",
        "kind": "pr_modif" if (pr_result and pr_result.get("ok"))
                            else "recommandation",
        "title": f"Optim on-page {page_path}",
        "detail_md": "\n".join(detail_lines),
        "status": "preview" if (pr_result and pr_result.get("ok"))
                            else "draft",
        "branch": (pr_result or {}).get("branch", ""),
        "github_pr_url": (pr_result or {}).get("pr_url", ""),
        "impact": 4, "effort": 1,
        "files_touched": [p.get("file") for p in file_patches if p.get("file")],
    })

    # Notif : si la PR a été ouverte avec succès → modif à valider (priorité normale)
    if action and pr_result and pr_result.get("ok"):
        try:
            from . import notifications
            notifications.notify_pending_action(site=site, action=action)
        except Exception as exc:
            logger.debug("notify_pending_action failed: %s", exc)

    return {"ok": True, "action_id": (action or {}).get("id"),
            "patches_abstract": abstract_patches,
            "patches_file": file_patches,
            "needs_review": needs_review,
            "agent_output": out, "pr": pr_result}


# ---------------------------------------------------------------------------
# Mission 4 — Maillage interne et inter-sites
# ---------------------------------------------------------------------------
def run_tisseur(site_id: str, *, app_state=None) -> dict:
    site = repo.get_site(site_id)
    if not site:
        return {"ok": False, "error": "site introuvable"}
    pages = repo.list_pages(site_id, limit=500)
    ecosystem = repo.list_sites()

    try:
        ag = agents.Tisseur()
        out = ag.run(site=site, pages=pages, ecosystem=ecosystem, app_state=app_state)
    except Exception as exc:
        logger.warning("Tisseur LLM: %s", exc)
        out = {}

    intra = out.get("intra_site_links") or []
    inter = out.get("inter_site_links") or []
    if intra or inter:
        repo.insert_action({
            "site_id": site_id, "agent": "tisseur", "kind": "recommandation",
            "title": f"Maillage : {len(intra)} intra + {len(inter)} inter-sites",
            "detail_md": (out.get("summary_md") or "") +
                         "\n\nIntra:\n" + "\n".join(
                             f"- {l.get('from_path')} → {l.get('to_path')} "
                             f"(« {l.get('anchor')} »)" for l in intra[:20]) +
                         "\n\nInter:\n" + "\n".join(
                             f"- {l.get('from_path')} → "
                             f"{l.get('to_site_domain')}{l.get('to_path')} "
                             f"(« {l.get('anchor')} »)" for l in inter[:20]),
            "status": "draft", "impact": 4, "effort": 3,
        })

    return {"ok": True, "intra": len(intra), "inter": len(inter),
            "orphans": len(out.get("orphan_pages") or [])}


# ---------------------------------------------------------------------------
# Mission 5 — Chasse backlinks
# ---------------------------------------------------------------------------
def run_backlinks(site_id: str, *, competitor_domains: Optional[list[str]] = None,
                  app_state=None) -> dict:
    site = repo.get_site(site_id)
    if not site:
        return {"ok": False, "error": "site introuvable"}
    domain = site.get("domain") or ""

    summary = dataforseo.backlinks_summary(domain) if dataforseo.is_configured() else {}
    competitor_domains = competitor_domains or []

    try:
        ag = agents.ChasseurBacklinks()
        out = ag.run(site=site, our_backlinks_summary=summary,
                     competitor_domains=competitor_domains, app_state=app_state)
    except Exception as exc:
        logger.warning("ChasseurBacklinks LLM: %s", exc)
        out = {}

    opps = out.get("opportunities") or []
    if opps:
        repo.insert_backlinks(site_id, [
            {"source_domain": o.get("source_domain", ""),
             "kind": "opportunity",
             "opportunity_score": o.get("score"),
             "notes": f"{o.get('kind', '')}: {o.get('approach_hint', '')}"}
            for o in opps[:30]
        ])
        repo.insert_action({
            "site_id": site_id, "agent": "chasseur_backlinks", "kind": "recommandation",
            "title": f"Backlinks : {len(opps)} opportunités",
            "detail_md": out.get("summary_md") or "",
            "status": "draft", "impact": 3, "effort": 4,
        })
    return {"ok": True, "opportunities": len(opps), "summary": summary}


# ---------------------------------------------------------------------------
# Mission 6 — Bulletin Analyste hebdo
# ---------------------------------------------------------------------------
def run_analyst(site_id: str, *, app_state=None) -> dict:
    site = repo.get_site(site_id)
    if not site:
        return {"ok": False, "error": "site introuvable"}
    domain = site.get("domain") or ""

    metrics = gsc.fetch_daily_metrics(domain)
    # Persiste les métriques jour par jour
    for m in metrics:
        if not m.get("date"):
            continue
        try:
            d = date.fromisoformat(m["date"])
        except ValueError:
            continue
        repo.upsert_metrics(site_id, d, {
            "organic_clicks": m.get("clicks", 0),
            "impressions": m.get("impressions", 0),
            "avg_position": m.get("position"),
            "avg_ctr": m.get("ctr"),
        })
    recent_actions = repo.list_actions(site_id=site_id, limit=30)

    try:
        ag = agents.Analyste()
        out = ag.run(site=site, metrics_30d=metrics,
                     recent_actions=recent_actions, app_state=app_state)
    except Exception as exc:
        logger.warning("Analyste LLM: %s", exc)
        out = {}

    if out:
        # next_week_recommendation peut être str (ancien format) OU dict
        # (nouveau format boosté : {action, owner_agent, expected_impact})
        reco = out.get("next_week_recommendation") or ""
        if isinstance(reco, dict):
            action = reco.get("action") or ""
            owner = reco.get("owner_agent") or ""
            impact = reco.get("expected_impact") or ""
            reco_str = action
            if owner:
                reco_str += f" (agent : {owner})"
            if impact:
                reco_str += f" — impact attendu : {impact}"
        else:
            reco_str = str(reco)
        repo.insert_action({
            "site_id": site_id, "agent": "analyste", "kind": "recommandation",
            "title": f"Bulletin {date.today().isoformat()} — {out.get('trend', '')}",
            "detail_md": (out.get("trend_summary_md") or "") + f"\n\nReco : {reco_str}",
            "status": "draft", "impact": 2, "effort": 1,
        })
        # Notif : bulletin matinal, priorité basse (informationnel)
        try:
            from . import notifications
            notifications.notify_bulletin(site=site, bulletin=out)
        except Exception as exc:
            logger.debug("notify_bulletin failed: %s", exc)

    return {"ok": True, "bulletin": out, "metrics_days": len(metrics)}


# ---------------------------------------------------------------------------
# Mission 7 — Plan stratégique mensuel (Opus)
# ---------------------------------------------------------------------------
def run_strategy(*, app_state=None) -> dict:
    snapshot = ecosystem_overview()
    try:
        ag = agents.ChefOrchestre()
        out = ag.run(ecosystem_snapshot=snapshot, app_state=app_state)
    except Exception as exc:
        logger.warning("ChefOrchestre LLM: %s", exc)
        out = {}
    if out:
        for site in snapshot.get("sites", []):
            repo.insert_action({
                "site_id": site["id"], "agent": "chef_orchestre",
                "kind": "recommandation",
                "title": f"Plan du mois : {out.get('month_label', '')}",
                "detail_md": "Voir Bulletin > Plan mensuel",
                "status": "draft", "impact": 5, "effort": 5,
            })
    return {"ok": True, "plan": out}


# ---------------------------------------------------------------------------
# Mission 8 — Pipeline complet sur un site (audit + KW + analyse)
# ---------------------------------------------------------------------------
def run_full_cycle(site_id: str, *, app_state=None) -> dict:
    out: dict = {"site_id": site_id, "steps": {}}
    out["steps"]["audit"] = run_audit(site_id, app_state=app_state)
    out["steps"]["keywords"] = run_keywords(site_id, app_state=app_state)
    out["steps"]["tisseur"] = run_tisseur(site_id, app_state=app_state)
    out["steps"]["analyst"] = run_analyst(site_id, app_state=app_state)
    out["ok"] = all(s.get("ok") for s in out["steps"].values())
    return out


# ---------------------------------------------------------------------------
# Vue agrégée — Tableau de bord écosystème
# ---------------------------------------------------------------------------
def ecosystem_overview() -> dict:
    """Snapshot agrégé pour la vue UI."""
    sites = repo.list_sites()
    out_sites: list[dict] = []
    totals = {"organic_clicks_30d": 0, "impressions_30d": 0,
              "actions_pending": 0, "audits_count": 0}
    for s in sites:
        latest = repo.latest_audit(s["id"])
        metrics = repo.metrics_window(s["id"], days=30)
        clicks = sum(m.get("organic_clicks", 0) or 0 for m in metrics)
        imps = sum(m.get("impressions", 0) or 0 for m in metrics)
        actions_pending = len([a for a in repo.list_actions(site_id=s["id"], limit=200)
                               if a.get("status") in ("draft", "preview")])
        out_sites.append({
            "id": s["id"], "name": s["name"], "domain": s["domain"],
            "priority": s.get("priority", 50),
            "lighthouse_perf": (latest or {}).get("lighthouse_perf"),
            "lighthouse_seo": (latest or {}).get("lighthouse_seo"),
            "broken_links": (latest or {}).get("broken_links", 0),
            "pages_crawled": (latest or {}).get("pages_crawled", 0),
            "organic_clicks_30d": clicks,
            "impressions_30d": imps,
            "actions_pending": actions_pending,
            "last_audit_at": (latest or {}).get("ran_at"),
        })
        totals["organic_clicks_30d"] += clicks
        totals["impressions_30d"] += imps
        totals["actions_pending"] += actions_pending
        if latest:
            totals["audits_count"] += 1
    return {"generated_at": datetime.now().isoformat(timespec="seconds"),
            "sites": out_sites, "totals": totals,
            "config_status": {
                "gsc": gsc.is_configured(),
                "dataforseo": dataforseo.is_configured(),
                "github_token": bool(repo.get_config().get("github_token")),
                "netlify_token": bool(repo.get_config().get("netlify_token")),
            }}


# ---------------------------------------------------------------------------
# Validation manuelle d'une PR en attente (depuis l'UI)
# ---------------------------------------------------------------------------
def merge_action(action_id: str, *, force: bool = False) -> dict:
    """Valide une action.

    Deux cas :
    - Action liée à une PR GitHub (kind='pr_modif', github_pr_url renseignée) :
      vérifie les checks et merge la PR pour de vrai.
    - Action sans PR (recommandation textuelle, bulletin, cluster sémantique…) :
      marque simplement comme 'merged' pour la sortir de la liste « à regarder ».
      C'est l'utilisateur qui actionne le conseil hors du Phare.
    """
    sb = repo._sb()
    if sb is None:
        return {"ok": False, "error": "Supabase non configuré"}
    rows = sb.table("phare_actions").select("*").eq("id", action_id).limit(1).execute().data
    if not rows:
        return {"ok": False, "error": "action introuvable"}
    action = rows[0]
    pr_url = action.get("github_pr_url") or ""
    if not pr_url:
        # Validation simple : pas de modif technique, on note juste « accepté »
        repo.update_action(action_id, {
            "status": "merged", "auto_merged": False,
            "merged_at": datetime.now().isoformat(),
        })
        return {"ok": True, "kind": "note_only"}
    site = repo.get_site(action["site_id"])
    if not site:
        return {"ok": False, "error": "site introuvable"}
    pr_number = int(pr_url.rstrip("/").split("/")[-1])
    if not force:
        v = git_pipeline.verify_pr(site=site, pr_number=pr_number,
                                    branch=action.get("branch", ""))
        if v["decision"] != "merge":
            return {"ok": False, "checks": v["checks"], "decision": v["decision"]}
    ok = git_pipeline.merge_pr(site["repo_github"], pr_number,
                                commit_title=action.get("title", ""))
    if ok:
        repo.update_action(action_id, {"status": "merged", "auto_merged": False,
                                        "merged_at": datetime.now().isoformat()})
    return {"ok": ok}


def reject_action(action_id: str, reason: str = "") -> dict:
    repo.update_action(action_id, {
        "status": "rejected",
        "rejected_at": datetime.now().isoformat(),
        "rejected_reason": reason or "Rejet manuel",
    })
    return {"ok": True}


def archive_action(action_id: str) -> dict:
    """Cache une action déjà validée ('merged') de la liste 'Ce qui a été fait'."""
    repo.update_action(action_id, {"status": "archived"})
    return {"ok": True}
