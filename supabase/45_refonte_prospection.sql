-- ============================================================
-- Migration 45 — Refonte prospection (2026-06-10)
-- ============================================================
-- 1. prospect_drafts : colonnes bonus pour les brouillons générés par
--    l'Auto-pilote via la base partagée — version HTML du mail + notes
--    de la 2e IA de relecture. Le code marche SANS ces colonnes
--    (insertion dégradée), mais avec elles le brouillon validé part
--    avec sa vraie mise en forme et l'avis de la 2e IA s'affiche.
-- 2. hunts_backup : copie de secours des chasses (Chasseur / Chasseur
--    Créateur / Prospecteur Google), poussée à la fin de chaque chasse.
--    La source de vérité reste les fichiers locaux du serveur ; cette
--    table n'est qu'un filet de sécurité + de la visibilité partagée.
-- ============================================================

-- 1. Colonnes bonus sur prospect_drafts
alter table public.prospect_drafts
  add column if not exists body_html text not null default '';
alter table public.prospect_drafts
  add column if not exists review_score int;
alter table public.prospect_drafts
  add column if not exists review_verdict text not null default '';
alter table public.prospect_drafts
  add column if not exists review_comment text not null default '';

-- 2. Copie de secours des chasses
create table if not exists public.hunts_backup (
  tool        text not null,            -- chasseur | chasseur_createurs | prospecteur_google
  hunt_id     text not null,
  label       text not null default '',
  status      text not null default '', -- done | error
  filters     jsonb not null default '{}'::jsonb,
  stats       jsonb not null default '{}'::jsonb,
  payload     jsonb not null default '{}'::jsonb,  -- la chasse complète (avec prospects)
  workspace_id uuid references public.workspaces(id) on delete cascade,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  primary key (tool, hunt_id)
);

alter table public.hunts_backup enable row level security;

-- Lecture pour les membres du workspace (ou lignes legacy sans workspace).
drop policy if exists hunts_backup_select on public.hunts_backup;
create policy hunts_backup_select on public.hunts_backup
  for select to authenticated
  using (workspace_id is null
         or workspace_id = public.current_workspace_id());

-- Écriture : réservée au serveur (service_role, qui bypasse RLS).
-- Pas de policy insert/update pour authenticated → un navigateur ne peut
-- pas écrire dedans, seul le serveur le fait.
