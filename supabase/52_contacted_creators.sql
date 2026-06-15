-- ---------------------------------------------------------------------------
-- Carnet des créateurs contactés — table DÉDIÉE, séparée du vivier de
-- prospection (public.prospects).
--
-- Pourquoi séparée : le vivier `prospects` est fait pour la prospection PAR
-- MAIL (il impose une adresse mail, déclenche relances mail, dédoublonnage…).
-- Ici on veut juste un carnet simple des créateurs qu'on démarche par réseaux
-- sociaux (Instagram, TikTok…), SANS mail, qui démarre VIDE et ne contient que
-- ce qu'on y ajoute à la main.
--
-- 100 % idempotent (if not exists) → rejouable sans risque.
-- ---------------------------------------------------------------------------

create table if not exists public.contacted_creators (
  id                uuid primary key default gen_random_uuid(),
  name              text not null,
  platform          text not null default '',   -- réseau : instagram / tiktok / youtube / facebook / autre
  handle            text default '',            -- @pseudo ou lien du profil
  contacted_at      timestamptz,                -- date du contact
  message           text default '',            -- le message envoyé
  next_follow_up_at timestamptz,                -- date de relance prévue (le rappel)
  demo_url          text default '',            -- lien de la démo construite pour ce créateur
  notes             text default '',
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);

create index if not exists idx_contacted_creators_followup
  on public.contacted_creators (next_follow_up_at)
  where next_follow_up_at is not null;
create index if not exists idx_contacted_creators_created
  on public.contacted_creators (created_at desc);

alter table public.contacted_creators enable row level security;
drop policy if exists contacted_creators_rw on public.contacted_creators;
create policy contacted_creators_rw on public.contacted_creators
  for all to authenticated, service_role
  using (true) with check (true);
