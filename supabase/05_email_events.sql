-- =====================================================================
-- Triskell Command — Migration 05 : table email_events (tracking)
-- =====================================================================
-- Trace les ouvertures et clics sur les mails sortants. Alimentée par
-- une Netlify Function publique `tracking.js` (sur le domaine Triskell)
-- et lue par la vue Funnel + Matinale.
--
-- Pourquoi une table dédiée et pas extra dans email_history :
-- - Volumétrie : ouvertures = 5-10x les envois (clients qui ouvrent
--   plusieurs fois). En séparer permet d'ajouter un index ts sans gonfler
--   email_history.
-- - Sécurité : email_events est écrit par Netlify avec service_role key.
--   email_history reste écrit uniquement par les apps authentifiées.
-- =====================================================================

create table if not exists public.email_events (
    id uuid primary key default gen_random_uuid(),
    -- ID public utilisé dans les pixels/liens (token court non-deviné)
    token text unique not null,
    -- Lien vers email_history (si on a pu le résoudre)
    email_history_id uuid references public.email_history(id) on delete set null,
    prospect_id uuid references public.prospects(id) on delete set null,
    -- Type d'événement
    event_type text not null,                       -- open / click
    url text default '',                            -- URL cliquée (si click)
    ts timestamptz not null default now(),
    -- Contexte client
    user_agent text default '',
    ip_hash text default '',                        -- IP hashée (RGPD-friendly)
    -- Champs libres
    extra jsonb not null default '{}'::jsonb
);

create index if not exists idx_email_events_email_history on public.email_events (email_history_id);
create index if not exists idx_email_events_prospect on public.email_events (prospect_id);
create index if not exists idx_email_events_ts on public.email_events (ts desc);
create index if not exists idx_email_events_token on public.email_events (token);
create index if not exists idx_email_events_type on public.email_events (event_type);

-- RLS : lecture autorisée à tout user authentifié, écriture uniquement
-- par service_role (la Netlify Function utilise service_role).
alter table public.email_events enable row level security;

drop policy if exists email_events_authed_read on public.email_events;
create policy email_events_authed_read on public.email_events
    for select using (auth.uid() is not null);

-- Pas de policy d'INSERT pour les users authentifiés : seul service_role
-- (qui bypass RLS) peut écrire. Cohérent avec le fait qu'on ne veut pas
-- que la pixel-pollution puisse tomber dans le mauvais user.
