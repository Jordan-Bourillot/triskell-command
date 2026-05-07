-- =====================================================================
-- Triskell Command — Migration 06d : Le Phare, modules pro (v0.6)
-- =====================================================================
-- À exécuter APRÈS 06_phare.sql, 06b_phare_seed_real.sql, 06c_phare_advanced.sql.
--
-- Ajoute les tables nécessaires aux modules pro :
--   - phare_outreach_campaigns / phare_outreach_messages
--   - phare_ab_tests / phare_ab_measurements
--   - phare_brand_mentions
--   - phare_gbp_status / phare_reviews
--   - phare_programmatic_templates / phare_programmatic_pages
--   - phare_cro_insights
--   - phare_algo_events
-- =====================================================================

create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------------
-- Outreach backlinks
-- ---------------------------------------------------------------------
create table if not exists public.phare_outreach_campaigns (
    id uuid primary key default gen_random_uuid(),
    site_id uuid not null references public.phare_sites(id) on delete cascade,
    name text not null,
    kind text not null,           -- broken_link / unlinked_mention / gap_concurrent / haro
    template_subject text not null,
    template_body text not null,  -- avec {variables}
    status text not null default 'active',
    created_at timestamptz not null default now()
);
create index if not exists idx_phare_outreach_camp_site on public.phare_outreach_campaigns (site_id);

create table if not exists public.phare_outreach_messages (
    id uuid primary key default gen_random_uuid(),
    campaign_id uuid not null references public.phare_outreach_campaigns(id) on delete cascade,
    site_id uuid not null references public.phare_sites(id) on delete cascade,
    target_domain text not null,
    target_email text default '',
    target_contact_name text default '',
    proposed_subject text not null,
    proposed_body text not null,
    variables jsonb not null default '{}'::jsonb,
    status text not null default 'draft',  -- draft / sent / replied_pos / replied_neg / no_reply
    sent_at timestamptz,
    reply_at timestamptz,
    reply_excerpt text default '',
    follow_up_count int default 0,
    next_follow_up_at timestamptz,
    created_at timestamptz not null default now()
);
create index if not exists idx_phare_outreach_msg_status on public.phare_outreach_messages (status);
create index if not exists idx_phare_outreach_msg_site on public.phare_outreach_messages (site_id);

-- ---------------------------------------------------------------------
-- A/B testing SEO
-- ---------------------------------------------------------------------
create table if not exists public.phare_ab_tests (
    id uuid primary key default gen_random_uuid(),
    site_id uuid not null references public.phare_sites(id) on delete cascade,
    name text not null,
    field_tested text not null,   -- title / meta_description / h1
    variant_a_value text not null,
    variant_b_value text not null,
    paths_lot_a jsonb not null default '[]'::jsonb,
    paths_lot_b jsonb not null default '[]'::jsonb,
    started_at timestamptz not null default now(),
    duration_days int default 21,
    ended_at timestamptz,
    winner text default '',       -- a / b / none
    final_decision_md text default '',
    status text not null default 'running'  -- running / done / aborted
);
create index if not exists idx_phare_ab_site on public.phare_ab_tests (site_id);

create table if not exists public.phare_ab_measurements (
    id uuid primary key default gen_random_uuid(),
    test_id uuid not null references public.phare_ab_tests(id) on delete cascade,
    measured_date date not null,
    lot_a_clicks int default 0,
    lot_a_impressions int default 0,
    lot_a_ctr numeric,
    lot_b_clicks int default 0,
    lot_b_impressions int default 0,
    lot_b_ctr numeric,
    created_at timestamptz not null default now(),
    unique (test_id, measured_date)
);

-- ---------------------------------------------------------------------
-- Brand monitoring
-- ---------------------------------------------------------------------
create table if not exists public.phare_brand_mentions (
    id uuid primary key default gen_random_uuid(),
    site_id uuid not null references public.phare_sites(id) on delete cascade,
    brand_term text not null,            -- "Triskell Studio" / "Pack Électricien Pro" / etc.
    source_url text not null,
    source_domain text not null,
    excerpt text default '',
    has_link boolean default false,
    sentiment text default 'neutral',    -- positive / neutral / negative
    discovered_at timestamptz not null default now(),
    action_id uuid references public.phare_actions(id) on delete set null,
    unique (site_id, source_url, brand_term)
);
create index if not exists idx_phare_brand_site on public.phare_brand_mentions (site_id, discovered_at desc);

-- ---------------------------------------------------------------------
-- Google Business Profile (Local SEO)
-- ---------------------------------------------------------------------
create table if not exists public.phare_gbp_status (
    id uuid primary key default gen_random_uuid(),
    site_id uuid not null references public.phare_sites(id) on delete cascade,
    place_id text not null,
    name text not null,
    address text default '',
    phone text default '',
    website text default '',
    rating numeric,
    reviews_count int default 0,
    photos_count int default 0,
    posts_last_30d int default 0,
    completeness_score int,             -- 0-100 (champs remplis / total)
    suggestions jsonb not null default '[]'::jsonb,
    checked_at timestamptz not null default now()
);
create index if not exists idx_phare_gbp_site on public.phare_gbp_status (site_id);

create table if not exists public.phare_reviews (
    id uuid primary key default gen_random_uuid(),
    site_id uuid not null references public.phare_sites(id) on delete cascade,
    place_id text not null,
    review_id text unique not null,
    author_name text default '',
    rating int,
    text_excerpt text default '',
    has_response boolean default false,
    proposed_response_md text default '',
    posted_at timestamptz,
    discovered_at timestamptz not null default now()
);
create index if not exists idx_phare_reviews_site on public.phare_reviews (site_id);

-- ---------------------------------------------------------------------
-- Programmatic SEO
-- ---------------------------------------------------------------------
create table if not exists public.phare_programmatic_templates (
    id uuid primary key default gen_random_uuid(),
    site_id uuid not null references public.phare_sites(id) on delete cascade,
    name text not null,                  -- "Tarif électricien par ville"
    url_pattern text not null,           -- /tarif-{slug_ville}.html
    title_pattern text not null,
    meta_pattern text not null,
    h1_pattern text not null,
    body_outline_md text not null,
    variables_source text not null,      -- "csv" / "supabase_table" / "external_api"
    variables_payload jsonb not null default '{}'::jsonb,
    quality_min_words int default 600,
    status text default 'draft',         -- draft / generating / done
    created_at timestamptz not null default now()
);
create index if not exists idx_phare_progtmpl_site on public.phare_programmatic_templates (site_id);

create table if not exists public.phare_programmatic_pages (
    id uuid primary key default gen_random_uuid(),
    template_id uuid not null references public.phare_programmatic_templates(id) on delete cascade,
    site_id uuid not null references public.phare_sites(id) on delete cascade,
    variables jsonb not null default '{}'::jsonb,
    generated_url text not null,
    generated_title text default '',
    generated_meta text default '',
    generated_body_md text default '',
    word_count int default 0,
    quality_score int,
    status text default 'draft',         -- draft / approved / pushed / live
    pushed_action_id uuid references public.phare_actions(id) on delete set null,
    created_at timestamptz not null default now()
);
create index if not exists idx_phare_progpages_site on public.phare_programmatic_pages (site_id, status);

-- ---------------------------------------------------------------------
-- CRO (Microsoft Clarity)
-- ---------------------------------------------------------------------
create table if not exists public.phare_cro_insights (
    id uuid primary key default gen_random_uuid(),
    site_id uuid not null references public.phare_sites(id) on delete cascade,
    page_path text not null,
    sessions int default 0,
    rage_clicks int default 0,
    dead_clicks int default 0,
    quick_backs int default 0,
    scroll_depth_avg numeric,
    conversion_rate numeric,
    issue_summary_md text default '',
    proposed_fixes_md text default '',
    detected_at timestamptz not null default now()
);
create index if not exists idx_phare_cro_site on public.phare_cro_insights (site_id);

-- ---------------------------------------------------------------------
-- Algo watch
-- ---------------------------------------------------------------------
create table if not exists public.phare_algo_events (
    id uuid primary key default gen_random_uuid(),
    source text not null,                -- search_engine_land / search_engine_roundtable / mozcast / semrush_sensor / google_search_liaison
    event_date date not null,
    headline text not null,
    summary_md text default '',
    severity text default 'info',        -- info / warning / critical
    source_url text default '',
    detected_at timestamptz not null default now(),
    acknowledged boolean default false
);
create index if not exists idx_phare_algo_date on public.phare_algo_events (event_date desc);

-- =====================================================================
-- RLS
-- =====================================================================
do $$
declare
    t text;
begin
    foreach t in array array[
        'phare_outreach_campaigns', 'phare_outreach_messages',
        'phare_ab_tests', 'phare_ab_measurements',
        'phare_brand_mentions',
        'phare_gbp_status', 'phare_reviews',
        'phare_programmatic_templates', 'phare_programmatic_pages',
        'phare_cro_insights',
        'phare_algo_events'
    ]
    loop
        execute format('alter table public.%I enable row level security;', t);
        execute format('drop policy if exists %I_authed on public.%I;', t, t);
        execute format(
            'create policy %I on public.%I for all using (auth.uid() is not null) with check (auth.uid() is not null);',
            t || '_authed', t
        );
    end loop;
end$$;

-- =====================================================================
-- Étend phare_config avec les options pro
-- =====================================================================
update public.shared_settings
set value = value || jsonb_build_object(
    'outreach_smtp_from',           '',
    'outreach_max_per_day',         10,
    'outreach_follow_up_days',      '[7, 14]'::jsonb,
    'outreach_auto_send',           false,
    'ab_test_min_duration_days',    14,
    'ab_test_min_impressions',      500,
    'brand_monitor_terms',          '["Triskell Studio", "Pack Électricien Pro", "Studio PDF", "Bobeez", "DéliNote", "AlphaBeast", "AlphaCast", "AlphaPitch", "Obelisk"]'::jsonb,
    'brand_monitor_search_engine',  'google',
    'gbp_place_ids',                '{}'::jsonb,
    'clarity_project_id',           '',
    'clarity_api_token',            '',
    'algo_watch_sources',           '["search_engine_land", "google_search_liaison", "mozcast"]'::jsonb,
    'bulletin_pdf_logo_path',       ''
)
where key = 'phare_config';
