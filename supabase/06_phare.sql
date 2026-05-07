-- =====================================================================
-- Triskell Command — Migration 06 : Le Phare (SEO autonome multi-sites)
-- =====================================================================
-- Module SEO embarqué dans Command. 8 agents Claude pilotent l'optimisation
-- de tous les sous-domaines *.triskell-studio.fr.
--
-- Tables :
--   phare_sites          → catalogue des sites surveillés
--   phare_audits         → snapshots techniques (Lighthouse, CWV, indexation)
--   phare_keywords       → mots-clés suivis (volume, position, intent)
--   phare_pages          → inventaire des URLs crawlées (titles, metas, hn)
--   phare_actions        → travail des agents (PRs, modifs, statut)
--   phare_metrics        → KPIs quotidiens (clicks, impressions, conversions)
--   phare_backlinks      → profil backlinks (analyse + opportunités)
--   phare_content_briefs → briefs de contenus à rédiger
-- =====================================================================

create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------------
-- phare_sites : un sous-domaine Triskell surveillé
-- ---------------------------------------------------------------------
create table if not exists public.phare_sites (
    id uuid primary key default gen_random_uuid(),
    name text not null,                     -- "Pack Électricien Pro"
    domain text unique not null,            -- "pack-elec.triskell-studio.fr"
    repo_github text default '',            -- "Jordan-Bourillot/pack-electricien"
    repo_branch_main text default 'main',
    netlify_site_id text default '',
    stack text default '',                  -- "astro" / "next" / "html"
    voice_pack text default 'triskell',     -- profil de voix injecté dans le prompt agent
    priority int default 50,                -- 0-100, plus haut = plus prioritaire
    is_active boolean not null default true,
    -- Pages clés à surveiller en diff visuel (max 10 chemins relatifs)
    key_paths jsonb not null default '["/"]'::jsonb,
    -- Bornes garde-fou
    perf_min_score int default 70,          -- Lighthouse perf minimum acceptable
    visual_diff_max_pct numeric default 5.0,
    -- Metadata libre
    notes text default '',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_phare_sites_active on public.phare_sites (is_active);
create index if not exists idx_phare_sites_priority on public.phare_sites (priority desc);

-- ---------------------------------------------------------------------
-- phare_audits : un snapshot technique d'un site à un instant T
-- ---------------------------------------------------------------------
create table if not exists public.phare_audits (
    id uuid primary key default gen_random_uuid(),
    site_id uuid not null references public.phare_sites(id) on delete cascade,
    ran_at timestamptz not null default now(),
    -- Lighthouse (0-100)
    lighthouse_perf int,
    lighthouse_seo int,
    lighthouse_a11y int,
    lighthouse_bp int,
    -- Core Web Vitals (PageSpeed Insights, terrain)
    cwv_lcp numeric,
    cwv_inp numeric,
    cwv_cls numeric,
    -- Crawl
    pages_crawled int default 0,
    pages_indexable int default 0,
    broken_links int default 0,
    redirects_chain int default 0,
    -- Schema.org
    schema_score int,
    -- Erreurs notables (liste de strings)
    issues jsonb not null default '[]'::jsonb,
    -- Résumé Markdown généré par l'Auditeur
    summary_md text default '',
    created_at timestamptz not null default now()
);

create index if not exists idx_phare_audits_site on public.phare_audits (site_id, ran_at desc);

-- ---------------------------------------------------------------------
-- phare_keywords : mots-clés suivis par site
-- ---------------------------------------------------------------------
create table if not exists public.phare_keywords (
    id uuid primary key default gen_random_uuid(),
    site_id uuid not null references public.phare_sites(id) on delete cascade,
    keyword text not null,
    volume int default 0,
    difficulty int default 0,               -- 0-100
    intent text default 'informational',    -- informational/commercial/transactional/navigational
    target_url text default '',
    current_position int,
    best_position int,
    last_checked_at timestamptz,
    created_at timestamptz not null default now(),
    unique (site_id, keyword)
);

create index if not exists idx_phare_keywords_site on public.phare_keywords (site_id);
create index if not exists idx_phare_keywords_pos on public.phare_keywords (current_position);

-- ---------------------------------------------------------------------
-- phare_pages : inventaire des URLs (titres, metas, structure Hn)
-- ---------------------------------------------------------------------
create table if not exists public.phare_pages (
    id uuid primary key default gen_random_uuid(),
    site_id uuid not null references public.phare_sites(id) on delete cascade,
    url text not null,
    path text not null,                     -- "/produit/pack" (sans domaine)
    title text default '',
    meta_description text default '',
    h1 text default '',
    h_outline jsonb not null default '[]'::jsonb,    -- [{level: 2, text: "..."}]
    word_count int default 0,
    internal_links int default 0,
    schema_types jsonb not null default '[]'::jsonb, -- ["Product", "BreadcrumbList"]
    last_crawled_at timestamptz,
    -- Score d'optimisation (0-100) calculé par l'Optimiseur On-Page
    optim_score int,
    optim_notes text default '',
    created_at timestamptz not null default now(),
    unique (site_id, path)
);

create index if not exists idx_phare_pages_site on public.phare_pages (site_id);

-- ---------------------------------------------------------------------
-- phare_actions : travail des agents (PRs ouvertes, modifs, recommandations)
-- ---------------------------------------------------------------------
create table if not exists public.phare_actions (
    id uuid primary key default gen_random_uuid(),
    site_id uuid not null references public.phare_sites(id) on delete cascade,
    agent text not null,                    -- "auditeur" / "optimiseur_onpage" / etc.
    kind text not null,                     -- "pr_modif" / "recommandation" / "alerte"
    title text not null,
    detail_md text default '',
    -- PR-related
    branch text default '',
    github_pr_url text default '',
    netlify_preview_url text default '',
    -- Garde-fous
    lighthouse_diff jsonb default '{}'::jsonb,
    visual_diff_pct numeric,
    broken_links_added int default 0,
    -- Statut : draft → preview → checks_ok|checks_ko → merged|rejected|expired
    status text not null default 'draft',
    auto_merged boolean default false,
    -- Priorisation (impact 1-5, effort 1-5)
    impact int default 3,
    effort int default 3,
    -- Files touchés
    files_touched jsonb not null default '[]'::jsonb,
    -- Logs
    created_at timestamptz not null default now(),
    merged_at timestamptz,
    rejected_at timestamptz,
    rejected_reason text default ''
);

create index if not exists idx_phare_actions_site on public.phare_actions (site_id, created_at desc);
create index if not exists idx_phare_actions_status on public.phare_actions (status);

-- ---------------------------------------------------------------------
-- phare_metrics : KPIs quotidiens par site
-- ---------------------------------------------------------------------
create table if not exists public.phare_metrics (
    id uuid primary key default gen_random_uuid(),
    site_id uuid not null references public.phare_sites(id) on delete cascade,
    metric_date date not null,
    organic_clicks int default 0,
    impressions int default 0,
    avg_position numeric,
    avg_ctr numeric,
    top10_count int default 0,
    top3_count int default 0,
    indexed_pages int default 0,
    conversions_attributed int default 0,
    revenue_attributed numeric default 0,
    source text default 'gsc',              -- gsc / ga4 / manual
    created_at timestamptz not null default now(),
    unique (site_id, metric_date, source)
);

create index if not exists idx_phare_metrics_site on public.phare_metrics (site_id, metric_date desc);

-- ---------------------------------------------------------------------
-- phare_backlinks : profil backlinks + opportunités
-- ---------------------------------------------------------------------
create table if not exists public.phare_backlinks (
    id uuid primary key default gen_random_uuid(),
    site_id uuid not null references public.phare_sites(id) on delete cascade,
    source_domain text not null,
    source_url text default '',
    target_url text default '',
    anchor text default '',
    domain_rating int,                      -- DR Ahrefs-like
    is_dofollow boolean default true,
    -- Type : "existing" (déjà lié) / "opportunity" (à démarcher)
    kind text not null default 'existing',
    opportunity_score int,                  -- 0-100, calculé par Chasseur Backlinks
    notes text default '',
    discovered_at timestamptz not null default now(),
    last_seen_at timestamptz
);

create index if not exists idx_phare_backlinks_site on public.phare_backlinks (site_id);
create index if not exists idx_phare_backlinks_kind on public.phare_backlinks (kind);

-- ---------------------------------------------------------------------
-- phare_content_briefs : briefs d'articles produits par le Rédacteur
-- ---------------------------------------------------------------------
create table if not exists public.phare_content_briefs (
    id uuid primary key default gen_random_uuid(),
    site_id uuid not null references public.phare_sites(id) on delete cascade,
    cluster text default '',                -- thème du cocon
    target_keyword text not null,
    secondary_keywords jsonb not null default '[]'::jsonb,
    intent text default 'informational',
    target_url text default '',             -- URL prévue (slug)
    title_proposed text default '',
    outline_md text default '',
    word_target int default 1200,
    -- Statut : "draft" → "approved" → "published"
    status text not null default 'draft',
    drafted_md text default '',             -- contenu rédigé
    action_id uuid references public.phare_actions(id) on delete set null,
    created_at timestamptz not null default now(),
    published_at timestamptz
);

create index if not exists idx_phare_content_site on public.phare_content_briefs (site_id);

-- =====================================================================
-- RLS : tout user authentifié voit/écrit (pattern Triskell Command)
-- =====================================================================
alter table public.phare_sites enable row level security;
alter table public.phare_audits enable row level security;
alter table public.phare_keywords enable row level security;
alter table public.phare_pages enable row level security;
alter table public.phare_actions enable row level security;
alter table public.phare_metrics enable row level security;
alter table public.phare_backlinks enable row level security;
alter table public.phare_content_briefs enable row level security;

do $$
declare
    t text;
begin
    foreach t in array array[
        'phare_sites','phare_audits','phare_keywords','phare_pages',
        'phare_actions','phare_metrics','phare_backlinks','phare_content_briefs'
    ]
    loop
        execute format('drop policy if exists %I_rw on public.%I;', t || '_authed', t);
        execute format(
            'create policy %I on public.%I for all using (auth.uid() is not null) with check (auth.uid() is not null);',
            t || '_authed', t
        );
    end loop;
end$$;

-- =====================================================================
-- Seed initial : les 13 sites Triskell connus (idempotent via unique domain)
-- =====================================================================
insert into public.phare_sites (name, domain, stack, priority, key_paths, notes) values
    ('Triskell Studio (apex)',  'triskell-studio.fr',          'astro', 90, '["/"]'::jsonb, 'Landing principale + Table Ronde'),
    ('Pack Électricien Pro',    'pack-elec.triskell-studio.fr','astro', 95, '["/", "/produit"]'::jsonb, 'CIBLE MVP. Tunnel Stripe rodé.'),
    ('Studio PDF',              'studio-pdf.triskell-studio.fr','astro',80, '["/"]'::jsonb, ''),
    ('Suite des Héros',         'productivite.triskell-studio.fr','astro',75, '["/"]'::jsonb, ''),
    ('Bobeez',                  'bobeez.triskell-studio.fr',   'astro', 70, '["/"]'::jsonb, ''),
    ('DéliNote',                'delinote.triskell-studio.fr', 'astro', 65, '["/"]'::jsonb, ''),
    ('Outils Bâtiment',         'outils.triskell-studio.fr',   'astro', 70, '["/"]'::jsonb, 'PWA, abonnement 9€/mois'),
    ('Eliks Studio',            'eliks.triskell-studio.fr',    'astro', 60, '["/"]'::jsonb, 'Service growth operator'),
    ('Sites agence',            'sites.triskell-studio.fr',    'astro', 55, '["/"]'::jsonb, 'Générateur de démo'),
    ('Obelisk',                 'obelisk.triskell-studio.fr',  'next',  85, '["/"]'::jsonb, ''),
    ('AlphaBeast',              'alphabeast.triskell-studio.fr','astro',60, '["/"]'::jsonb, ''),
    ('AlphaCast',               'alphacast.triskell-studio.fr','astro', 60, '["/"]'::jsonb, 'Beta ouverte'),
    ('AlphaPitch',              'alphapitch.triskell-studio.fr','astro',60, '["/"]'::jsonb, '')
on conflict (domain) do nothing;

-- shared_settings : config Le Phare (DataForSEO + GSC + LLM préférés)
insert into public.shared_settings (key, value) values
    ('phare_config', '{
        "dataforseo_login": "",
        "dataforseo_password": "",
        "gsc_credentials_path": "",
        "github_token": "",
        "netlify_token": "",
        "anthropic_model_default": "claude-sonnet-4-6",
        "anthropic_model_strategy": "claude-opus-4-7",
        "auto_merge_enabled": true,
        "voice_pack_default": "triskell",
        "schedule_audit_cron": "0 6 * * 1",
        "schedule_keywords_cron": "0 7 * * 1,4",
        "schedule_redaction_cron": "0 8 * * *",
        "schedule_strategy_cron": "0 9 1 * *"
    }'::jsonb)
on conflict (key) do nothing;
