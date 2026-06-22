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
from urllib.parse import urlparse

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
    if not psi.get("ok"):
        logger.warning("phare.audit %s: PageSpeed indisponible — %s",
                       domain, psi.get("error"))

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

    # Quick wins → actions de type "recommandation".
    # insert_action dédoublonne tout seul (un audit qui retombe sur le même
    # conseil ne crée plus de deuxième carte) ; "simple" = l'explication
    # sans jargon écrite par l'agent, affichée en avant sur la carte.
    for qw in (analysis.get("quick_wins") or [])[:5]:
        repo.insert_action({
            "site_id": site_id,
            "agent": "auditeur",
            "kind": "recommandation",
            "title": qw.get("title", "Quick win"),
            "detail_md": (qw.get("fix_hint") or "") + "\n\nPage: " + (qw.get("page_or_global") or ""),
            "simple_md": (qw.get("simple") or "").strip(),
            "status": "draft",
            "impact": 3, "effort": 2,
        })

    # Chaînes de redirection réelles repérées au crawl → cartes déterministes
    # (vraies adresses, pas un conseil vague) que l'Exécuteur sait corriger en
    # rendant le lien interne direct. Les normalisations gérées par l'hébergeur
    # (http→https, www, barre de fin) sont déjà écartées par le crawler.
    for chain in (crawl.get("redirect_chains") or [])[:5]:
        src, final = chain.get("source") or "", chain.get("final") or ""
        if not src or not final:
            continue
        label = urlparse(src).path or src
        repo.insert_action({
            "site_id": site_id,
            "agent": "redirect_fixer",
            "kind": "recommandation",
            "title": f"Lien qui passe par une étape inutile : {label}",
            "detail_md": (f"Source : {src}\nDestination finale : {final}\n\n"
                          f"Un lien interne pointe vers une adresse qui en "
                          f"renvoie vers une autre ({chain.get('hops', 1)} "
                          f"étape(s)). On fait pointer le lien directement vers "
                          f"la bonne adresse."),
            "simple_md": ("Un lien de ton site passe par une page "
                          "intermédiaire avant d'arriver à la bonne — on le "
                          "fait pointer directement au bon endroit, c'est plus "
                          "rapide et Google préfère."),
            "status": "draft", "impact": 2, "effort": 1,
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
    kws_to_check = [k.get("keyword") for k in primary + long_tail if k.get("keyword")]

    # Volumes ET difficulté RÉELS via DataForSEO (un appel groupé chacun) ; si
    # l'API est muette pour un mot, on retombe sur l'estimation de l'agent —
    # jamais sur un 0 trompeur.
    volumes = {v["keyword"].lower(): v for v in dataforseo.search_volume(kws_to_check)}
    difficulty = dataforseo.keyword_difficulty(kws_to_check)

    # Position RÉELLE depuis Google Search Console : la position moyenne que
    # Google nous donne déjà pour chaque requête où le site apparaît. Gratuit,
    # fiable. Un mot ciblé que Google ne connaît pas encore → position None
    # (« pas encore positionné »), ce qui est une info en soi.
    gsc_pos: dict[str, float] = {}
    try:
        for q in gsc.fetch_top_queries(domain, days=28, limit=250):
            qk = (q.get("query") or "").lower().strip()
            if qk and isinstance(q.get("position"), (int, float)):
                gsc_pos[qk] = q["position"]
    except Exception as exc:
        logger.debug("run_keywords positions GSC: %s", exc)

    # Meilleure position jamais atteinte : on lit l'existant pour garder la
    # trace (colonne best_position prévue mais jamais remplie jusqu'ici).
    prev_best: dict[str, int] = {}
    try:
        for row in repo.list_keywords(site_id, limit=500):
            kwl = (row.get("keyword") or "").lower()
            bp = row.get("best_position")
            if kwl and isinstance(bp, int):
                prev_best[kwl] = bp
    except Exception as exc:
        logger.debug("run_keywords best_position: %s", exc)

    persisted = []
    for k in primary + long_tail:
        kw = k.get("keyword", "")
        kwl = kw.lower()
        v = volumes.get(kwl, {})
        pos = gsc_pos.get(kwl)
        cur_pos = int(round(pos)) if isinstance(pos, (int, float)) else None
        best = prev_best.get(kwl)
        if cur_pos is not None:
            best = cur_pos if best is None else min(best, cur_pos)
        persisted.append({
            "keyword": kw,
            "volume": v.get("volume", k.get("estimated_volume", 0)),
            "difficulty": difficulty.get(kwl, k.get("estimated_difficulty", 0) or 0),
            "intent": k.get("intent") or "informational",
            "target_url": k.get("target_url_hint") or "",
            "current_position": cur_pos,
            "best_position": best,
        })
    inserted = repo.upsert_keywords(site_id, persisted)

    # Recommandation cluster — périssable : le veilleur en repropose un à
    # chaque passage avec un pivot reformulé (vécu : 5 cartes « Cluster
    # sémantique » ouvertes sur Triskell Studio pour la même idée). Le
    # nouveau remplace les anciens encore ouverts.
    if plan.get("cluster_pivot"):
        repo.expire_open_actions(site_id, agent="veilleur",
                                 title_prefix="Cluster sémantique",
                                 reason="Remplacé par le cluster le plus récent")
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

    # Schema-architecte : si la page n'a AUCUNE donnée structurée au crawl,
    # on ajoute le bloc JSON-LD déterministe (pas de LLM, fiable). Passe par
    # le même circuit PR + vérifications que les autres patches — et rend la
    # mission utile même quand l'agent LLM n'a rien proposé.
    if not (page.get("schema_types") or []):
        try:
            from . import schema_architect
            jsonld_patches = schema_architect.patches_for_page(page, site)
            if jsonld_patches:
                abstract_patches = abstract_patches + jsonld_patches
        except Exception as exc:
            logger.debug("schema_architect: %s", exc)

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
        n = len(file_patches)
        detail_lines.append(f"\nJ'ai préparé {n} amélioration"
                            f"{'s' if n > 1 else ''} sur cette page.")
    if needs_review:
        # Détail technique (endroits ambigus) : gardé pour le JOURNAL, jamais
        # écrit sur la carte — on n'inflige pas de charabia de débogage à Jordan.
        logger.info("run_onpage_optim %s : %d à revoir (%s)", page_path,
                    len(needs_review),
                    ", ".join(str(r.get("field")) for r in needs_review[:6]))

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
# Mission « Étiquettes invisibles » — données structurées sur tout le site
# ---------------------------------------------------------------------------
def run_schema_pass(site_id: str, *, app_state=None) -> dict:
    """Repère les pages SANS étiquette invisible (données structurées) et crée
    UNE carte par site. L'Exécuteur pose ensuite le balisage déterministe
    (schema_architect) — jamais la page d'accueil (décision de Jordan).
    Idempotent : si tout est déjà balisé, ne crée rien ; dedup empêche les
    cartes en double."""
    site = repo.get_site(site_id)
    if not site:
        return {"ok": False, "error": "site introuvable"}
    pages = repo.list_pages(site_id, limit=500)
    targets = [p for p in pages
               if not (p.get("schema_types") or [])
               and (p.get("path") or "/") != "/"]
    if not targets:
        return {"ok": True, "skipped": "déjà balisé", "pages": 0}
    n = len(targets)
    sample = ", ".join((p.get("path") or "/") for p in targets[:8])
    action = repo.insert_action({
        "site_id": site_id,
        "agent": "schema_architect",
        "kind": "recommandation",
        "title": (f"Étiquettes pour les IA : {n} page"
                  f"{'s' if n > 1 else ''} à équiper"),
        "detail_md": (f"**{n} page{'s' if n > 1 else ''}** n'ont pas encore "
                      "leur étiquette invisible (données structurées) que "
                      "Google et les IA lisent.\n\n"
                      f"Pages concernées : {sample}" + (" …" if n > 8 else "")
                      + "."),
        "simple_md": ("J'ajoute sur chaque page une étiquette invisible qui "
                      "explique à Google et aux IA (ChatGPT, Perplexité) de "
                      "quoi parle la page — sans rien changer à ce que voient "
                      "tes visiteurs."),
        "status": "draft",
        "impact": 4, "effort": 1,
    })
    return {"ok": True, "action_id": (action or {}).get("id"), "pages": n}


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
        # Un bulletin est périssable : celui du jour remplace les précédents
        # encore ouverts (fini les piles de bulletins dans « À toi de jouer »).
        repo.expire_open_actions(site_id, agent="analyste",
                                 title_prefix="Bulletin",
                                 reason="Remplacé par le bulletin du jour")
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
        # Le plan complet vit DANS la carte. Avant : « Voir Bulletin > Plan
        # mensuel » — un écran qui n'a jamais existé, le plan était perdu
        # sitôt généré (constaté le 12/06/2026 sur le plan de juin).
        detail = _strategy_detail_md(out)
        for site in snapshot.get("sites", []):
            # Le plan du mois remplace celui d'avant (périssable) ; la dédup
            # d'insert_action évite en plus le double du même mois.
            repo.expire_open_actions(site["id"], agent="chef_orchestre",
                                     title_prefix="Plan du mois",
                                     reason="Remplacé par le plan le plus récent")
            repo.insert_action({
                "site_id": site["id"], "agent": "chef_orchestre",
                "kind": "recommandation",
                "title": f"Plan du mois : {out.get('month_label', '')}",
                "detail_md": detail,
                "simple_md": ("Le programme du mois : où les robots vont "
                              "concentrer leurs efforts, et les objectifs "
                              "chiffrés. À lire — rien à publier sur le site."),
                "status": "draft", "impact": 5, "effort": 5,
            })
    return {"ok": True, "plan": out}


def _strategy_detail_md(out: dict) -> str:
    """Met en page le plan du Chef d'Orchestre pour la carte (markdown)."""
    lines: list[str] = []
    vision = (out.get("vision_summary_md") or "").strip()
    if vision:
        lines.append(vision)
    prio = out.get("priority_sites") or []
    if prio:
        lines.append("\n**Les 3 sites prioritaires du mois :**")
        for p in prio:
            row = f"- **{p.get('domain', '?')}** — {p.get('rationale', '')}"
            if p.get("target_delta_30d"):
                row += f" (objectif 30 j : {p['target_delta_30d']})"
            lines.append(row)
    ti = out.get("transverse_initiative") or {}
    if ti.get("title"):
        lines.append(f"\n**Chantier transverse :** {ti['title']}"
                     + (f" — {ti.get('scope', '')}" if ti.get("scope") else ""))
    crit = out.get("success_criteria") or []
    if crit:
        lines.append("\n**Critères de succès :**")
        for c in crit:
            lines.append(f"- {c.get('metric', '?')} → {c.get('target', '?')}")
    depri = out.get("deprioritized_sites") or []
    if depri:
        lines.append("\n**Mis en pause ce mois-ci :** "
                     + ", ".join(d.get("domain", "?") for d in depri))
    return "\n".join(lines).strip() or "Plan généré sans détail exploitable."


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
def merge_action(action_id: str, *, force: bool = False,
                 auto: bool = False) -> dict:
    """Valide une action.

    Deux cas :
    - Action liée à une PR GitHub (kind='pr_modif', github_pr_url renseignée) :
      vérifie les checks et merge la PR pour de vrai.
    - Action sans PR (recommandation textuelle, bulletin, cluster sémantique…) :
      marque simplement comme 'merged' pour la sortir de la liste « à regarder ».
      C'est l'utilisateur qui actionne le conseil hors du Phare.

    `auto=True` quand l'appel vient de l'auto-merge du scheduler (trace
    auto_merged en base pour distinguer des validations humaines).
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
            "status": "merged", "auto_merged": auto,
            "merged_at": datetime.now().isoformat(),
            # Publié → on efface toute vieille étiquette d'échec d'une tentative
            # auto antérieure (sinon la carte reste affichée « échec » alors
            # qu'elle est en ligne — vu le 18/06 sur Lagriffe).
            "apply_state": "done", "apply_error": "",
        })
        return {"ok": True, "kind": "note_only"}
    site = repo.get_site(action["site_id"])
    if not site:
        return {"ok": False, "error": "site introuvable"}
    pr_number = int(pr_url.rstrip("/").split("/")[-1])
    if not force:
        v = git_pipeline.verify_pr(site=site, pr_number=pr_number,
                                    branch=action.get("branch", ""))
        blockers = [b for b in ((v.get("checks") or {}).get("blockers") or [])
                    if "Netlify non configuré" not in b
                    and "PSI indisponible" not in b]
        # Modif invisible (titre, méta, données structurées, alt, sitemap) :
        # le « diff visuel » est un faux positif — même règle que la publication
        # automatique. Page cassée (4xx) et vitesse restent, elles, bloquantes.
        from . import executor
        if executor._is_metadata_only(action):
            blockers = [b for b in blockers if "diff visuel" not in b]
        if blockers:
            return {"ok": False, "checks": v.get("checks") or {},
                    "decision": "hold"}
    ok = git_pipeline.merge_pr(site["repo_github"], pr_number,
                                commit_title=action.get("title", ""))
    if ok:
        repo.update_action(action_id, {"status": "merged", "auto_merged": auto,
                                        "merged_at": datetime.now().isoformat(),
                                        # Publié → effacer toute vieille étiquette
                                        # d'échec (cf. note ci-dessus).
                                        "apply_state": "done", "apply_error": ""})
    return {"ok": ok}


def auto_merge_verified(*, max_merges: int = 3,
                        min_age_minutes: int = 45) -> dict:
    """Publie tout seul les PRs en attente qui passent TOUTES les vérifs.

    C'est la brique qui transforme le Phare de « propose et attend » en
    « agit » : les patches vérifiés (Lighthouse, diff visuel, 4xx/5xx via
    verify_pr) sont mergés sans intervention, le reste reste dans le bac
    de validation humaine.

    Garde-fous :
      - opt-in : phare_config.auto_merge_enabled (défaut False) ;
      - fenêtre de veto : on ne touche pas une PR plus jeune que
        min_age_minutes (Jordan est notifié à l'ouverture → il peut
        rejeter avant le passage) ;
      - max_merges par passage : limite le rayon d'impact d'un cycle ;
      - jamais de force : verdict « hold » → la PR reste en preview ;
      - traçabilité : auto_merged=True en base + notification push ;
      - filet aval : rollback_watch surveille le trafic 14 j post-merge.
    """
    cfg = repo.get_config()
    if not cfg.get("auto_merge_enabled", False):
        return {"ok": True, "skipped": "auto_merge_disabled"}

    pending = repo.list_actions(status="preview", limit=50)
    merged: list[dict] = []
    held: list[dict] = []
    now = datetime.now()
    for action in pending:
        if len(merged) >= max_merges:
            break
        if not (action.get("github_pr_url") or ""):
            # Recommandation textuelle : décision humaine, pas d'auto-merge.
            continue
        if _targets_home(action):
            # L'accueil (la vitrine) ne se publie JAMAIS tout seul.
            held.append({"action_id": action["id"],
                         "title": action.get("title", ""),
                         "site_id": action.get("site_id", ""),
                         "decision": "accueil protégé"})
            continue
        # Fenêtre de veto
        try:
            created = datetime.fromisoformat(
                str(action.get("created_at") or "").replace("Z", "+00:00"))
            age_min = (now - created.replace(tzinfo=None)).total_seconds() / 60.0
            if age_min < min_age_minutes:
                continue
        except Exception:
            pass
        r = merge_action(action["id"], force=False, auto=True)
        entry = {"action_id": action["id"], "title": action.get("title", ""),
                 "site_id": action.get("site_id", "")}
        if r.get("ok"):
            merged.append(entry)
            try:
                from . import notifications
                site = repo.get_site(action.get("site_id", "")) or {}
                notifications.notify_auto_merged(site=site, action=action)
            except Exception as exc:
                logger.debug("notify_auto_merged: %s", exc)
        else:
            entry["decision"] = r.get("decision") or r.get("error") or "hold"
            held.append(entry)

    return {"ok": True, "merged": merged, "held": held,
            "pending_seen": len(pending)}


# Familles que le robot peut appliquer SEUL en sécurité : métadonnées, <head>,
# liens — jamais le contenu visible ni le design. On exclut volontairement les
# cartes « famille inconnue » (le filet optimiste de classify_for_apply) :
# elles peuvent échouer ou demander un humain → pas d'auto-application.
_AUTO_SAFE_AGENTS = ("sitemap_builder", "image_seo", "redirect_fixer",
                     "schema_architect")
_AUTO_SAFE_FAMILIES = {"title", "meta", "canonical", "noindex", "h1",
                       "schema", "alt", "sitemap"}


# La page d'accueil (la vitrine) reste TOUJOURS la décision de Jordan : ni
# l'auto-application ni l'auto-publication n'y touchent. On la repère par le
# chemin "/" seul, OU par les mots (accueil / home) quand AUCUNE autre page
# n'est visée. (Vécu le 17/06 : un « Réécrire le titre de la home » sans
# chemin explicite avait franchi le garde-fou qui ne regardait que "/".)
_HOME_HINTS = ("accueil", "homepage", "home page", "la home")


def _targets_home(action: dict) -> bool:
    """La carte vise-t-elle la page d'accueil ?"""
    from . import dedup
    text = f"{action.get('title') or ''}\n{action.get('detail_md') or ''}"
    paths = dedup.extract_paths(text)
    if paths == {"/"}:
        return True
    # Titre dont le chemin visé est l'accueil NU (« Optim on-page / », « Audit de
    # / ») : le « / » seul n'est pas vu comme un chemin par extract_paths. On le
    # repère ici — sinon une optim d'accueil échappe à la protection ET décroche
    # un faux bouton vert (vu le 19/06 sur « Optim on-page / », capture Jordan).
    title_s = (action.get("title") or "").strip()
    if title_s == "/" or title_s.endswith(" /") or title_s.endswith("\t/"):
        return True
    low = text.lower()
    return any(h in low for h in _HOME_HINTS) and not (paths - {"/"})


def _is_auto_safe(action: dict) -> bool:
    """Le robot peut-il appliquer cette carte SANS demander à Jordan ?"""
    if _targets_home(action):
        return False
    agent = (action.get("agent") or "").lower()
    if agent in _AUTO_SAFE_AGENTS:
        return True
    from . import plain_language
    fams = plain_language._families_of(action)
    return bool(fams) and fams.issubset(_AUTO_SAFE_FAMILIES)


def auto_apply_safe(*, max_apply: int = 8, app_state=None) -> dict:
    """« Le robot agit seul » : met en file les corrections SÛRES en attente
    (toutes sites), sans attendre le clic de Jordan. process_apply_queue les
    prépare, vérifie et publie ensuite — le reste attend une décision humaine.

    Trois interrupteurs (phare_config, tous défaut False) :
      - auto_merge_enabled       : le robot agit seul sur TOUTES les familles
                                   sûres (titre, méta, h1, données structurées,
                                   alt, plan du site…) ;
      - auto_apply_schema        : seulement les étiquettes invisibles (données
                                   structurées) ;
      - auto_apply_image_alts    : seulement le texte descriptif des images.
    Les deux derniers laissent Jordan activer le plus sûr SANS ouvrir la vanne
    globale.

    Garde-fous :
      - familles connues sûres uniquement (jamais le contenu/le design) ;
      - plafond par passage ; une carte déjà en file/préparée n'est jamais reprise ;
      - chaque modif passe par les vérifs de l'Exécuteur + reste annulable
        (rollback_watch surveille le trafic 14 j).
    """
    cfg = repo.get_config()
    global_on = bool(cfg.get("auto_merge_enabled", False))
    schema_on = bool(cfg.get("auto_apply_schema", False))
    alts_on = bool(cfg.get("auto_apply_image_alts", False))
    if not (global_on or schema_on or alts_on):
        return {"ok": True, "skipped": "disabled"}
    granular: set[str] = set()
    if schema_on:
        granular.add("schema")
    if alts_on:
        granular.add("alt")
    from . import plain_language
    drafts = repo.list_actions(status="draft", limit=200)
    enqueued: list[dict] = []
    sites_cache: dict[str, dict] = {}
    for a in drafts:
        if len(enqueued) >= max_apply:
            break
        if (a.get("apply_state") or ""):          # déjà en file / préparée / échec
            continue
        if not _is_auto_safe(a):
            continue
        # Mode granulaire (vanne globale coupée) : on n'applique QUE les familles
        # explicitement autorisées, et UNIQUEMENT si TOUTE la carte tient dans
        # ces familles (une carte « titre + données structurées » ne passe pas
        # en mode « schema seul » — elle changerait aussi le titre).
        if not global_on:
            agent_low = (a.get("agent") or "").lower()
            fams = set(plain_language._families_of(a))
            if agent_low == "image_seo":
                fams.add("alt")
            elif agent_low == "schema_architect":
                fams.add("schema")
            if not (fams and fams.issubset(granular)):
                continue
        sid = a.get("site_id") or ""
        site = sites_cache.get(sid)
        if site is None:
            site = repo.get_site(sid) or {}
            sites_cache[sid] = site
        if not (site.get("repo_github") or "").strip():
            continue
        verdict = plain_language.classify_for_apply(a, site)
        if not (verdict.get("can") and verdict.get("mode") == "code"):
            continue
        if repo.update_action(a["id"], {
                "apply_state": "queued",
                "apply_requested_at": datetime.now().isoformat()}):
            enqueued.append({"id": a["id"], "title": a.get("title", ""),
                             "site_id": sid})
    if enqueued:
        logger.info("phare auto_apply: %d corrections mises en file", len(enqueued))
    return {"ok": True, "enqueued": enqueued, "drafts_seen": len(drafts)}


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
