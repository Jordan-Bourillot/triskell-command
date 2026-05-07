-- =====================================================================
-- Triskell Command — Migration 08 : Le Phare, fiches clients externes
-- =====================================================================
-- À exécuter APRÈS 06_phare.sql.
--
-- Ajoute le support des clients externes pour Le Phare :
--   - flag `is_external_client` sur phare_sites pour distinguer les sites
--     internes Triskell des sites confiés par un client payant
--   - table `phare_clients` (1:1 avec phare_sites) avec coordonnées,
--     cadence d'envoi des rapports, dates de mission
-- =====================================================================

-- ---------------------------------------------------------------------
-- phare_sites : flag client externe
-- ---------------------------------------------------------------------
alter table public.phare_sites
    add column if not exists is_external_client boolean not null default false;

create index if not exists idx_phare_sites_external
    on public.phare_sites (is_external_client);

-- ---------------------------------------------------------------------
-- phare_clients : fiche client (un client = un site, contrainte unique
-- sur site_id pour garantir le 1:1)
-- ---------------------------------------------------------------------
create table if not exists public.phare_clients (
    id uuid primary key default gen_random_uuid(),
    site_id uuid not null unique
        references public.phare_sites(id) on delete cascade,

    -- Coordonnées
    contact_name text not null,             -- "Jean Dupont"
    contact_email text not null,            -- destinataire des rapports
    phone text default '',
    company text default '',
    billing_address text default '',        -- multi-ligne
    notes text default '',

    -- Cadence de livraison des rapports
    -- 'auto_mensuel' : cron 1er du mois → mail auto avec PDF + résumé HTML
    -- 'manuel'       : Jordan clique « Générer » → preview → « Envoyer »
    report_cadence text not null default 'manuel'
        check (report_cadence in ('auto_mensuel', 'manuel')),

    -- Dates clés
    mission_started_at date,
    last_report_sent_at timestamptz,
    last_report_pdf_path text default '',   -- dernier PDF généré (cache)

    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_phare_clients_site
    on public.phare_clients (site_id);
create index if not exists idx_phare_clients_cadence
    on public.phare_clients (report_cadence);

-- ---------------------------------------------------------------------
-- RLS (pattern Triskell Command : tout user authentifié)
-- ---------------------------------------------------------------------
alter table public.phare_clients enable row level security;

drop policy if exists phare_clients_authed on public.phare_clients;
create policy phare_clients_authed on public.phare_clients
    for all
    using (auth.uid() is not null)
    with check (auth.uid() is not null);
