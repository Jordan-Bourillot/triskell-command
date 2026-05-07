"""Le Phare — outil SEO autonome multi-sites pour l'écosystème Triskell.

Module embarqué dans Triskell Command. Pilote 8 agents Claude qui auditent,
optimisent et enrichissent en continu tous les sous-domaines Triskell.

Sous-modules :
    voice        — voix de marque Triskell + filtre anti-slop
    repo         — DAO Supabase pour les tables phare_*
    sites        — CRUD des sites surveillés
    crawler      — crawler web léger (httpx + selectolax/bs4)
    pagespeed    — wrapper Google PageSpeed Insights
    gsc          — wrapper Google Search Console (fallback si non config)
    dataforseo   — wrapper DataForSEO (fallback si non config)
    agents       — les 8 agents (system prompts + appel LLM)
    git_pipeline — Git PR + Netlify preview + diff visuel
    orchestrator — chef d'orchestre qui dispatch
    scheduler    — daemon APScheduler

Usage minimal depuis Triskell Command :

    from triskell_command.integrations.phare import orchestrator, scheduler
    scheduler.start()
    overview = orchestrator.ecosystem_overview()
"""

from __future__ import annotations

__all__ = [
    "voice",
    "repo",
    "sites",
    "crawler",
    "pagespeed",
    "gsc",
    "dataforseo",
    "agents",
    "git_pipeline",
    "patcher",
    "orchestrator",
    "scheduler",
    # Modules avancés (v0.5)
    "schema_architect",
    "ctr_hacker",
    "snippet_hunter",
    "geo_surveillant",
    "cannibalization",
    "zombies",
    "image_seo",
    "refresh",
    "sitemap",
    "competitors",
    "rollback_watch",
    # Modules pro (v0.6)
    "outreach",
    "ab_test",
    "brand_monitoring",
    "local_seo",
    "programmatic",
    "cro",
    "algo_watch",
    "bulletin_pdf",
]

VERSION = "0.6.0"
