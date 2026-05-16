-- ============================================================
-- Migration 20 — MULTI-TENANT (workspaces)
-- ============================================================
-- ⚠  CETTE MIGRATION TOUCHE TOUTES LES TABLES CLIENTS-FACING.
-- ⚠  Elle est destinée au mode SaaS (un workspace par client).
-- ⚠  À APPLIQUER D'ABORD SUR UN PROJET SUPABASE DE TEST,
-- ⚠  puis en prod APRÈS un backup complet.
--
-- Objectif :
--   - Introduire la notion de `workspace` (= un client du SaaS).
--   - Lier toutes les données métier à un workspace_id.
--   - Remplacer les policies RLS "tout user voit tout" par
--     des policies "user voit ce qui est dans SON workspace".
--   - Backfiller les données existantes (Jordan + Thomas) dans
--     un workspace "triskell-studio" par défaut.
--
-- Ordre logique :
--   1. Créer workspaces + workspace_members + helper SQL
--   2. Créer le workspace par défaut "triskell-studio"
--   3. Ajouter workspace_id sur chaque table métier
--   4. Backfill : tout = workspace par défaut
--   5. Rendre workspace_id NOT NULL
--   6. Remplacer les policies RLS
-- ============================================================


-- ─────────────────────────────────────────────────────────────
-- 1. Tables structurelles
-- ─────────────────────────────────────────────────────────────
create table if not exists public.workspaces (
  id          uuid primary key default gen_random_uuid(),
  slug        text not null unique,                  -- "triskell-studio", "acme-corp"
  name        text not null,
  created_at  timestamptz not null default now(),
  -- Plan d'abonnement courant (lié à la migration 21_subscriptions)
  plan        text not null default 'essential',     -- essential | essential+pro | essential+phare | ...
  -- Limites de quota (peuvent être surcharge par plan)
  max_users           int  default 1,
  max_campaigns_month int  default 50,
  max_emails_day      int  default 200,
  -- Owner = créateur initial du workspace (référence users.user_id existant)
  owner_user_id uuid references public.users(user_id) on delete set null,
  -- Statut : trialing | active | past_due | canceled
  status      text not null default 'trialing'
);

create table if not exists public.workspace_members (
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  user_id      uuid not null references public.users(user_id) on delete cascade,
  role         text not null default 'member',       -- owner | admin | member
  joined_at    timestamptz not null default now(),
  primary key (workspace_id, user_id)
);

-- Index pour la fonction current_workspace_id() (très chaude)
create index if not exists workspace_members_user_idx
  on public.workspace_members (user_id);


-- ─────────────────────────────────────────────────────────────
-- 2. Helper SQL : workspace courant pour le user authentifié
-- ─────────────────────────────────────────────────────────────
-- Renvoie le 1er workspace dont le user authentifié est membre.
-- (Un user peut être dans plusieurs workspaces ; pour l'instant
-- on prend le premier — le multi-workspaces avec switch viendra
-- en V2 via une colonne `current_workspace_id` sur public.users.)
create or replace function public.current_workspace_id()
returns uuid
language sql
stable
security definer
set search_path = public
as $$
  select wm.workspace_id
    from public.workspace_members wm
   where wm.user_id = auth.uid()
   order by wm.joined_at asc
   limit 1;
$$;

comment on function public.current_workspace_id() is
  'Renvoie le workspace_id du user authentifié (1er si membre de plusieurs). NULL si non authentifié ou sans workspace.';


-- ─────────────────────────────────────────────────────────────
-- 3. Workspace "triskell-studio" par défaut (Jordan + Thomas)
-- ─────────────────────────────────────────────────────────────
insert into public.workspaces (slug, name, plan, status)
values ('triskell-studio', 'Triskell Studio (interne)', 'essential+pro+phare', 'active')
on conflict (slug) do nothing;

-- Rattache Jordan + Thomas à ce workspace (les ids existent dans 03_seed.sql).
-- Note : public.users a une colonne `user_id` (pas `id`), pas de colonne email.
-- L'email vit dans auth.users — on fait la jointure pour distinguer owner/admin.
insert into public.workspace_members (workspace_id, user_id, role)
select w.id, u.user_id,
       case when au.email ilike 'jordan%' then 'owner' else 'admin' end
  from public.workspaces w
 cross join public.users u
  join auth.users au on au.id = u.user_id
 where w.slug = 'triskell-studio'
on conflict do nothing;


-- ─────────────────────────────────────────────────────────────
-- 4. Ajouter workspace_id sur toutes les tables métier
-- ─────────────────────────────────────────────────────────────
-- Pattern :
--   a. add column workspace_id uuid references workspaces(id)
--   b. backfill : workspace par défaut "triskell-studio"
--   c. alter column ... set not null
--   d. index sur workspace_id pour les requêtes scopées

do $$
declare
  v_default_id uuid;
  v_tables text[] := array[
    'prospects',
    'email_history',
    'prospect_drafts',
    'templates',
    'convoy_campaigns',
    'convoy_drafts',
    'send_log',
    'client_projects',
    'clients'
  ];
  v_t text;
begin
  select id into v_default_id
    from public.workspaces
   where slug = 'triskell-studio';

  if v_default_id is null then
    raise exception 'Workspace par défaut introuvable. Étape 3 a échoué ?';
  end if;

  foreach v_t in array v_tables loop
    -- Skip si la table n'existe pas (selon ce qui a été migré jusqu'ici)
    if to_regclass('public.' || v_t) is null then
      raise notice 'Table public.% absente, skip.', v_t;
      continue;
    end if;

    -- 4a. add column (sans NOT NULL au début, pour pouvoir backfill)
    execute format('
      alter table public.%I
        add column if not exists workspace_id uuid
          references public.workspaces(id) on delete cascade',
      v_t);

    -- 4b. backfill : toutes les lignes orphelines → workspace par défaut
    execute format('update public.%I set workspace_id = %L where workspace_id is null',
                   v_t, v_default_id);

    -- 4c. NOT NULL (uniquement si on a bien pu remplir partout)
    execute format('alter table public.%I alter column workspace_id set not null', v_t);

    -- 4d. index pour les requêtes scopées (le RLS et l'app vont filtrer dessus)
    execute format('create index if not exists %I on public.%I (workspace_id)',
                   v_t || '_workspace_idx', v_t);
  end loop;
end $$;


-- ─────────────────────────────────────────────────────────────
-- 5. shared_settings : passer en `workspace_settings` (clé/valeur par workspace)
-- ─────────────────────────────────────────────────────────────
-- shared_settings était une table globale clé/valeur partagée par
-- TOUS les users. En multi-tenant, chaque workspace doit avoir ses
-- propres réglages (SMTP, catalogue d'offres, etc.).
do $$
begin
  if to_regclass('public.shared_settings') is null then
    raise notice 'Table public.shared_settings absente, skip section 5.';
    return;
  end if;

  alter table public.shared_settings
    add column if not exists workspace_id uuid
      references public.workspaces(id) on delete cascade;

  update public.shared_settings
     set workspace_id = (select id from public.workspaces where slug = 'triskell-studio')
   where workspace_id is null;

  alter table public.shared_settings alter column workspace_id set not null;

  -- L'unicité de la clé doit maintenant être PAR workspace
  alter table public.shared_settings
    drop constraint if exists shared_settings_pkey;
  alter table public.shared_settings
    drop constraint if exists shared_settings_key_key;
  alter table public.shared_settings
    add primary key (workspace_id, key);
end $$;


-- ─────────────────────────────────────────────────────────────
-- 6. Nouvelles policies RLS : "user voit ce qui est dans SON workspace"
-- ─────────────────────────────────────────────────────────────
-- On dropouille les anciennes policies "tout user authentifié voit tout"
-- (créées dans 02_rls.sql) et on les remplace par des policies scopées.

-- Helper macro : régénère les 4 policies (SELECT/INSERT/UPDATE/DELETE)
-- scopées par workspace pour une table donnée.

create or replace function public._install_workspace_rls(p_table text)
returns void
language plpgsql
as $$
declare
  v_p text;
begin
  -- Drop des policies existantes (toutes, par sécurité)
  for v_p in
    select pol.policyname
      from pg_policies pol
     where pol.schemaname = 'public' and pol.tablename = p_table
  loop
    execute format('drop policy if exists %I on public.%I', v_p, p_table);
  end loop;

  -- SELECT
  execute format('
    create policy "ws_select" on public.%I
      for select to authenticated
      using (workspace_id = public.current_workspace_id())', p_table);

  -- INSERT (l''app doit injecter workspace_id = current_workspace_id())
  execute format('
    create policy "ws_insert" on public.%I
      for insert to authenticated
      with check (workspace_id = public.current_workspace_id())', p_table);

  -- UPDATE
  execute format('
    create policy "ws_update" on public.%I
      for update to authenticated
      using (workspace_id = public.current_workspace_id())
      with check (workspace_id = public.current_workspace_id())', p_table);

  -- DELETE
  execute format('
    create policy "ws_delete" on public.%I
      for delete to authenticated
      using (workspace_id = public.current_workspace_id())', p_table);
end $$;

do $$
declare
  v_t text;
  v_tables text[] := array[
    'prospects',
    'email_history',
    'prospect_drafts',
    'templates',
    'convoy_campaigns',
    'convoy_drafts',
    'send_log',
    'client_projects',
    'clients',
    'shared_settings'
  ];
begin
  foreach v_t in array v_tables loop
    if to_regclass('public.' || v_t) is null then
      raise notice 'Table public.% absente, skip RLS.', v_t;
      continue;
    end if;
    perform public._install_workspace_rls(v_t);
  end loop;
end $$;


-- ─────────────────────────────────────────────────────────────
-- 7. workspaces + workspace_members : RLS de base
-- ─────────────────────────────────────────────────────────────
alter table public.workspaces        enable row level security;
alter table public.workspace_members enable row level security;

-- Un user voit son/ses workspace(s)
create policy "ws_self_select" on public.workspaces
  for select to authenticated
  using (id in (select workspace_id from public.workspace_members
                where user_id = auth.uid()));

-- Un user voit la liste de membres de son/ses workspace(s)
create policy "wsm_self_select" on public.workspace_members
  for select to authenticated
  using (workspace_id in (select workspace_id from public.workspace_members
                          where user_id = auth.uid()));


-- ─────────────────────────────────────────────────────────────
-- 8. CONTRÔLE FINAL — à exécuter manuellement après migration
-- ─────────────────────────────────────────────────────────────
-- select count(*) from public.workspaces;                -- attendu : >= 1
-- select count(*) from public.workspace_members;         -- attendu : >= 2
-- select count(*) from public.prospects where workspace_id is null;       -- attendu : 0
-- select count(*) from public.convoy_campaigns where workspace_id is null;-- attendu : 0
-- select policyname from pg_policies where tablename = 'prospects';       -- attendu : ws_select/insert/update/delete
