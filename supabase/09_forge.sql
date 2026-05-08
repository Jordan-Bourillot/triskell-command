-- =====================================================================
-- Triskell Command — Migration 09 : La Forge du Web
-- =====================================================================
-- À exécuter APRÈS les migrations Phare.
--
-- Tables :
--   forge_pending_briefs → demandes de site reçues par mail (intake Teddy)
--   forge_projects       → projets de création de site (workflow 14 étapes)
--
-- Pas de logique d'exécution ici — l'app autonome La Forge consommera
-- ces tables quand son moteur sera codé. En attendant, Triskell Command
-- les remplit via le bridge teddy_to_forge (poller IMAP filtré).
-- =====================================================================

create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------------
-- forge_pending_briefs : un mail "Demande de création de site" capté
-- par Teddy, parsé, et déposé ici en attente d'import dans un projet.
-- ---------------------------------------------------------------------
create table if not exists public.forge_pending_briefs (
    id uuid primary key default gen_random_uuid(),

    -- Origine du mail (site qui a envoyé)
    source text not null default 'site-request',   -- ex: 'rankus', 'eliks'
    received_at timestamptz not null default now(),

    -- Coordonnées client (extraites du mail)
    last_name text default '',                  -- Nom
    first_name text default '',                 -- Prénom
    email text default '',                      -- email du client
    phone text default '',                      -- téléphone
    address text default '',                    -- adresse postale (optionnel)

    -- Brief site (extrait du mail)
    description text default '',                -- description du site souhaité
    audience text default '',                   -- public visé
    tone text default '',                       -- ton souhaité

    -- Trace du mail original (pour audit / re-parsing)
    raw_email_subject text default '',
    raw_email_message_id text default '',
    raw_email_excerpt text default '',          -- 2000 premiers caractères

    -- Statut workflow d'import
    --   new       : tout juste reçu, pas encore importé
    --   imported  : converti en forge_project (project_id renseigné)
    --   rejected  : marqué comme spam / faux positif
    status text not null default 'new'
        check (status in ('new', 'imported', 'rejected')),

    project_id uuid,                            -- pointe sur forge_projects.id
    notes text default '',

    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_forge_briefs_status
    on public.forge_pending_briefs (status, received_at desc);
create index if not exists idx_forge_briefs_msgid
    on public.forge_pending_briefs (raw_email_message_id);

-- ---------------------------------------------------------------------
-- forge_projects : un projet de création de site, pilotable par les
-- 14 étapes de la spec La Forge v0.2 (cf. docs/spec-v0.2.md §3).
-- ---------------------------------------------------------------------
create table if not exists public.forge_projects (
    id uuid primary key default gen_random_uuid(),
    brief_id uuid references public.forge_pending_briefs(id) on delete set null,

    -- Coordonnées client (copiées au moment de l'import — la fiche client
    -- du brief est figée, le projet porte sa propre copie)
    client_last_name text default '',
    client_first_name text default '',
    client_email text default '',
    client_phone text default '',
    client_address text default '',

    -- Brief figé pour le projet
    site_description text default '',
    site_audience text default '',
    site_tone text default '',

    -- Workflow 14 étapes
    --   current_step : 0 = pas démarré, 1..14 = en cours, 15 = terminé
    --   steps_state  : { "1": {"status": "done", "ran_at": "...", "summary": "..."},
    --                    "2": {"status": "running"}, ... }
    current_step int not null default 0
        check (current_step between 0 and 15),
    steps_state jsonb not null default '{}'::jsonb,

    -- Mode d'exécution :
    --   true  → enchaîne les 14 étapes sans demander confirmation (cas import client)
    --   false → checkpoint à chaque étape
    auto_run boolean not null default true,

    -- Statut global du projet
    --   queued    : créé, en attente de l'exécuteur (La Forge v0.5)
    --   running   : un step est en cours
    --   done      : 14/14 OK, site déployé
    --   error     : un step a planté, last_error renseigné
    --   paused    : checkpoint manuel atteint (auto_run = false)
    --   cancelled : annulé par l'utilisateur
    status text not null default 'queued'
        check (status in ('queued', 'running', 'done', 'error',
                          'paused', 'cancelled')),
    last_error text default '',

    started_at timestamptz,
    completed_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_forge_projects_status
    on public.forge_projects (status, created_at desc);
create index if not exists idx_forge_projects_brief
    on public.forge_projects (brief_id);

-- ---------------------------------------------------------------------
-- RLS (pattern Triskell Command : tout user authentifié)
-- ---------------------------------------------------------------------
alter table public.forge_pending_briefs enable row level security;
alter table public.forge_projects       enable row level security;

do $$
declare
    t text;
begin
    foreach t in array array['forge_pending_briefs', 'forge_projects']
    loop
        execute format('drop policy if exists %I on public.%I;',
                       t || '_authed', t);
        execute format(
            'create policy %I on public.%I for all '
            'using (auth.uid() is not null) '
            'with check (auth.uid() is not null);',
            t || '_authed', t
        );
    end loop;
end$$;

-- ---------------------------------------------------------------------
-- shared_settings : configuration intake Teddy → Forge
-- ---------------------------------------------------------------------
-- Patterns utilisés par teddy_to_forge.py pour reconnaître un mail de
-- demande de site dans la boîte IMAP partagée. Le marker JSON
-- `[TRISKELL-INTAKE-V1] {...}` est le canal principal (déposé par les
-- netlify functions des sites Triskell). Le subject_prefix sert de
-- 2e filtre + bouton de tri humain.
insert into public.shared_settings (key, value) values
    ('forge_intake_config', '{
        "subject_prefix": "Demande de création de site",
        "marker_tag": "[TRISKELL-INTAKE-V1]",
        "enabled": true,
        "auto_create_project": true
    }'::jsonb)
on conflict (key) do nothing;
