-- Migration 21 — Tables Obelisk (fusion dans Triskell Command)
--
-- La table `prospects` existe déjà depuis 01_schema.sql et reste partagée
-- entre Obelisk standalone et Triskell Command.
--
-- Ce qu'on ajoute ici :
--   - obelisk_user_config   : config par user (clés API, IA, catalogue d'offres)
--   - obelisk_search_jobs   : queue des recherches lancées depuis Command
--
-- À exécuter dans Supabase Dashboard → SQL Editor → Run.

-- ---------------------------------------------------------------------------
-- 1. Config user (clés API, préférences IA, catalogue d'offres)
-- ---------------------------------------------------------------------------
create table if not exists public.obelisk_user_config (
  user_email   text primary key,
  config       jsonb not null default '{}'::jsonb,
  updated_at   timestamptz not null default now()
);

create index if not exists idx_obelisk_user_config_updated
  on public.obelisk_user_config (updated_at desc);

-- ---------------------------------------------------------------------------
-- 2. Jobs de recherche lancés depuis Triskell Command
-- ---------------------------------------------------------------------------
create table if not exists public.obelisk_search_jobs (
  id                uuid primary key default gen_random_uuid(),
  user_email        text not null default '_default_',
  niche             text not null,
  platforms         jsonb not null default '["youtube"]'::jsonb,
  max_per_platform  int  not null default 30,

  status            text not null default 'pending',  -- pending | running | done | failed | cancelled
  progress          jsonb not null default '[]'::jsonb,   -- logs ligne par ligne
  stats             jsonb not null default '{}'::jsonb,   -- {found, enriched, drafts, sent, errors}
  error             text,

  created_at        timestamptz not null default now(),
  started_at        timestamptz,
  finished_at       timestamptz
);

create index if not exists idx_obelisk_jobs_user_created
  on public.obelisk_search_jobs (user_email, created_at desc);

create index if not exists idx_obelisk_jobs_status
  on public.obelisk_search_jobs (status)
  where status in ('pending', 'running');

-- ---------------------------------------------------------------------------
-- RLS (à activer si on expose ces tables au front Supabase directement —
-- pour l'instant on lit/écrit en service_role depuis le backend Python de
-- Triskell Command, donc on laisse RLS désactivée).
-- ---------------------------------------------------------------------------
alter table public.obelisk_user_config  enable row level security;
alter table public.obelisk_search_jobs  enable row level security;

-- Politique permissive (à durcir en mode multi-tenant) : un user voit ses
-- propres jobs et sa propre config. Le service_role bypass RLS par défaut.
drop policy if exists obelisk_cfg_own on public.obelisk_user_config;
create policy obelisk_cfg_own
  on public.obelisk_user_config for all
  using (auth.jwt() ->> 'email' = user_email or auth.role() = 'service_role')
  with check (auth.jwt() ->> 'email' = user_email or auth.role() = 'service_role');

drop policy if exists obelisk_jobs_own on public.obelisk_search_jobs;
create policy obelisk_jobs_own
  on public.obelisk_search_jobs for all
  using (auth.jwt() ->> 'email' = user_email or auth.role() = 'service_role')
  with check (auth.jwt() ->> 'email' = user_email or auth.role() = 'service_role');
