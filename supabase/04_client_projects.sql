-- =====================================================================
-- Triskell Command — Migration 04 : table client_projects
-- =====================================================================
-- À exécuter UNE FOIS dans le SQL Editor de Supabase, après 01..03.
--
-- Objectif : kanban interne pour piloter la livraison des services
-- (Eliks Studio, Triskell Studio sites agence) après paiement.
-- Pas de Notion / Linear / Trello : tout reste dans Triskell Command.
-- =====================================================================

create table if not exists public.client_projects (
    id uuid primary key default gen_random_uuid(),
    prospect_id uuid references public.prospects(id) on delete set null,

    -- Identification du projet
    title text not null default '',
    product_key text not null default '',     -- ex: "eliks", "triskell-sites"
    product_name text not null default '',    -- libre, ex: "Site Despiertos Shop"

    -- Workflow
    status text not null default 'briefing',  -- briefing / in_progress / delivered / closed
    priority text not null default 'normal',  -- low / normal / high
    due_date date,

    -- Données client
    client_name text default '',
    client_email text default '',
    client_company text default '',

    -- Brief & livraison
    brief text default '',
    deliverables jsonb not null default '[]'::jsonb,   -- list[{label, url, done}]
    notes text default '',

    -- Vente
    amount_cents int not null default 0,
    currency text not null default 'EUR',
    paid_at timestamptz,
    stripe_session_id text default '',

    -- Post-vente automatisé
    cross_sell_sent_at timestamptz,
    nps_sent_at timestamptz,
    nps_score int,                            -- 0-10, null si pas encore reçu

    -- Audit
    assigned_to uuid references public.users(user_id),  -- Jordan / Thomas
    created_by uuid references public.users(user_id),
    updated_by uuid references public.users(user_id),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_client_projects_status on public.client_projects (status);
create index if not exists idx_client_projects_due on public.client_projects (due_date);
create index if not exists idx_client_projects_product on public.client_projects (product_key);
create index if not exists idx_client_projects_paid_at on public.client_projects (paid_at desc);

-- updated_at auto
drop trigger if exists trg_client_projects_updated_at on public.client_projects;
create trigger trg_client_projects_updated_at
    before update on public.client_projects
    for each row execute procedure public.set_updated_at();

-- RLS : aligné sur la convention (tout user authentifié voit/écrit)
alter table public.client_projects enable row level security;
drop policy if exists client_projects_all_select on public.client_projects;
create policy client_projects_all_select on public.client_projects
    for select using (auth.uid() is not null);
drop policy if exists client_projects_all_write on public.client_projects;
create policy client_projects_all_write on public.client_projects
    for all using (auth.uid() is not null) with check (auth.uid() is not null);
