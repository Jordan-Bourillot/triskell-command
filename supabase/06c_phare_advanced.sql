-- =====================================================================
-- Triskell Command — Migration 06c : Le Phare, fonctions avancées
-- =====================================================================
-- À exécuter APRÈS 06_phare.sql et 06b_phare_seed_real.sql.
--
-- Ajoute les tables nécessaires aux fonctions avancées :
--   - phare_competitors          : concurrents directs par site
--   - phare_competitor_positions : positions des concurrents sur tes KW
--   - phare_serp_features        : featured snippets & PAA capturables
--   - phare_geo_mentions         : mentions dans LLM (ChatGPT/Perplexity)
--   - phare_image_audits         : alts manquants, formats, tailles
--   - phare_cannibalization      : 2+ pages sur même KW
--   - phare_zombies              : pages sans trafic ni backlink
--   - phare_content_refresh      : articles à rafraîchir
--   - phare_rollback_watch       : surveillance post-merge (14 jours)
--   - phare_sitemap_pings        : log des pings IndexNow
-- =====================================================================

create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------------
-- phare_competitors : concurrents directs déclarés ou détectés
-- ---------------------------------------------------------------------
create table if not exists public.phare_competitors (
    id uuid primary key default gen_random_uuid(),
    site_id uuid not null references public.phare_sites(id) on delete cascade,
    competitor_domain text not null,
    relevance_score int default 50,         -- 0-100
    discovered_via text default 'manual',   -- manual / serp_overlap / llm
    notes text default '',
    is_active boolean default true,
    created_at timestamptz not null default now(),
    unique (site_id, competitor_domain)
);
create index if not exists idx_phare_competitors_site on public.phare_competitors (site_id);

-- ---------------------------------------------------------------------
-- phare_competitor_positions : snapshot positions concurrents par KW
-- ---------------------------------------------------------------------
create table if not exists public.phare_competitor_positions (
    id uuid primary key default gen_random_uuid(),
    site_id uuid not null references public.phare_sites(id) on delete cascade,
    competitor_domain text not null,
    keyword text not null,
    position int,
    url text default '',
    snapshot_date date not null default current_date,
    created_at timestamptz not null default now()
);
create index if not exists idx_phare_compos_site_kw on public.phare_competitor_positions (site_id, keyword, snapshot_date desc);

-- ---------------------------------------------------------------------
-- phare_serp_features : featured snippets et PAA détectés en SERP
-- ---------------------------------------------------------------------
create table if not exists public.phare_serp_features (
    id uuid primary key default gen_random_uuid(),
    site_id uuid not null references public.phare_sites(id) on delete cascade,
    keyword text not null,
    feature_type text not null,             -- featured_snippet / paa / video / image_pack
    current_owner_domain text default '',
    current_owner_url text default '',
    captured_format text default '',        -- paragraph / list / table / faq
    we_can_capture boolean default false,
    proposed_content_md text default '',
    detected_at timestamptz not null default now(),
    action_id uuid references public.phare_actions(id) on delete set null
);
create index if not exists idx_phare_serp_site on public.phare_serp_features (site_id, feature_type);

-- ---------------------------------------------------------------------
-- phare_geo_mentions : suivi de la présence dans les LLM (AI Overview etc.)
-- ---------------------------------------------------------------------
create table if not exists public.phare_geo_mentions (
    id uuid primary key default gen_random_uuid(),
    site_id uuid not null references public.phare_sites(id) on delete cascade,
    surface text not null,                  -- chatgpt / perplexity / claude / google_ai_overview
    query text not null,
    mentioned boolean not null default false,
    mention_url text default '',
    mention_excerpt text default '',
    competitors_mentioned jsonb not null default '[]'::jsonb,
    checked_at timestamptz not null default now(),
    raw_response text default ''
);
create index if not exists idx_phare_geo_site on public.phare_geo_mentions (site_id, surface, checked_at desc);

-- ---------------------------------------------------------------------
-- phare_image_audits : audit images d'une page (alts, format, taille)
-- ---------------------------------------------------------------------
create table if not exists public.phare_image_audits (
    id uuid primary key default gen_random_uuid(),
    site_id uuid not null references public.phare_sites(id) on delete cascade,
    page_path text not null,
    image_src text not null,
    has_alt boolean default false,
    alt_text text default '',
    proposed_alt text default '',
    format text default '',                 -- jpg / png / webp / avif / svg
    size_kb int,
    is_lazy boolean default false,
    has_srcset boolean default false,
    issues jsonb not null default '[]'::jsonb,
    checked_at timestamptz not null default now()
);
create index if not exists idx_phare_imgaudit_site on public.phare_image_audits (site_id, page_path);

-- ---------------------------------------------------------------------
-- phare_cannibalization : plusieurs pages qui rankent sur le même KW
-- ---------------------------------------------------------------------
create table if not exists public.phare_cannibalization (
    id uuid primary key default gen_random_uuid(),
    site_id uuid not null references public.phare_sites(id) on delete cascade,
    keyword text not null,
    competing_paths jsonb not null default '[]'::jsonb,   -- [{path, position, clicks}]
    severity int default 50,                              -- 0-100
    proposed_action text default '',                      -- merge / redirect_301 / differentiate
    proposed_canonical_path text default '',
    detected_at timestamptz not null default now(),
    resolved_at timestamptz,
    action_id uuid references public.phare_actions(id) on delete set null
);
create index if not exists idx_phare_cannib_site on public.phare_cannibalization (site_id);

-- ---------------------------------------------------------------------
-- phare_zombies : pages sans trafic, backlink ni conversion sur 6 mois
-- ---------------------------------------------------------------------
create table if not exists public.phare_zombies (
    id uuid primary key default gen_random_uuid(),
    site_id uuid not null references public.phare_sites(id) on delete cascade,
    page_path text not null,
    last_organic_click_at date,
    backlinks_count int default 0,
    word_count int default 0,
    proposed_action text default '',         -- boost / redirect / delete / noindex
    proposed_target_path text default '',    -- si redirect
    detected_at timestamptz not null default now(),
    resolved_at timestamptz,
    unique (site_id, page_path)
);
create index if not exists idx_phare_zombies_site on public.phare_zombies (site_id);

-- ---------------------------------------------------------------------
-- phare_content_refresh : articles à rafraîchir (perdent du terrain)
-- ---------------------------------------------------------------------
create table if not exists public.phare_content_refresh (
    id uuid primary key default gen_random_uuid(),
    site_id uuid not null references public.phare_sites(id) on delete cascade,
    page_path text not null,
    age_months int,
    clicks_now int default 0,
    clicks_peak int default 0,
    decline_pct numeric,
    proposed_changes_md text default '',
    refresh_score int,                       -- 0-100, plus haut = plus prioritaire
    detected_at timestamptz not null default now(),
    action_id uuid references public.phare_actions(id) on delete set null
);
create index if not exists idx_phare_refresh_site on public.phare_content_refresh (site_id);

-- ---------------------------------------------------------------------
-- phare_rollback_watch : surveille les PRs mergées pendant 14 jours
-- ---------------------------------------------------------------------
create table if not exists public.phare_rollback_watch (
    id uuid primary key default gen_random_uuid(),
    site_id uuid not null references public.phare_sites(id) on delete cascade,
    action_id uuid not null references public.phare_actions(id) on delete cascade,
    merged_at timestamptz not null,
    baseline_clicks_7d int default 0,
    measured_clicks_7d int,
    measured_at timestamptz,
    delta_pct numeric,
    decision text default 'watching',        -- watching / kept / rolled_back
    rollback_pr_url text default '',
    finalized_at timestamptz
);
create index if not exists idx_phare_rollback_site on public.phare_rollback_watch (site_id, decision);

-- ---------------------------------------------------------------------
-- phare_sitemap_pings : journal des pings IndexNow + sitemap.xml
-- ---------------------------------------------------------------------
create table if not exists public.phare_sitemap_pings (
    id uuid primary key default gen_random_uuid(),
    site_id uuid not null references public.phare_sites(id) on delete cascade,
    target text not null,                    -- bing / yandex / google
    urls_pinged jsonb not null default '[]'::jsonb,
    response_code int,
    response_body text default '',
    pinged_at timestamptz not null default now()
);
create index if not exists idx_phare_pings_site on public.phare_sitemap_pings (site_id, pinged_at desc);

-- =====================================================================
-- RLS : tout user authentifié voit/écrit (cohérent avec 06_phare.sql)
-- =====================================================================
alter table public.phare_competitors enable row level security;
alter table public.phare_competitor_positions enable row level security;
alter table public.phare_serp_features enable row level security;
alter table public.phare_geo_mentions enable row level security;
alter table public.phare_image_audits enable row level security;
alter table public.phare_cannibalization enable row level security;
alter table public.phare_zombies enable row level security;
alter table public.phare_content_refresh enable row level security;
alter table public.phare_rollback_watch enable row level security;
alter table public.phare_sitemap_pings enable row level security;

do $$
declare
    t text;
begin
    foreach t in array array[
        'phare_competitors', 'phare_competitor_positions',
        'phare_serp_features', 'phare_geo_mentions',
        'phare_image_audits', 'phare_cannibalization',
        'phare_zombies', 'phare_content_refresh',
        'phare_rollback_watch', 'phare_sitemap_pings'
    ]
    loop
        execute format('drop policy if exists %I_authed on public.%I;', t, t);
        execute format(
            'create policy %I on public.%I for all using (auth.uid() is not null) with check (auth.uid() is not null);',
            t || '_authed', t
        );
    end loop;
end$$;

-- =====================================================================
-- Étend phare_config avec les options des fonctions avancées
-- =====================================================================
update public.shared_settings
set value = value || jsonb_build_object(
    'indexnow_key',                '',
    'geo_check_surfaces',          '["chatgpt", "perplexity", "google_ai_overview"]'::jsonb,
    'rollback_watch_window_days',  14,
    'rollback_threshold_pct',      -15,
    'zombie_no_click_months',      6,
    'refresh_min_age_months',      12,
    'refresh_decline_threshold',   -25,
    'cannibalization_min_pages',   2,
    'image_max_size_kb',           200,
    'preferred_image_format',      'webp',
    'auto_apply_schema',           true,
    'auto_apply_image_alts',       true
)
where key = 'phare_config';
