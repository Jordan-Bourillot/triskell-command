-- ============================================================
-- Migration 21 — ABONNEMENTS SaaS (Stripe)
-- ============================================================
-- ⚠  À appliquer APRÈS la migration 20_multi_tenant.sql.
--
-- Objectif : permettre à chaque workspace de payer un abonnement
-- mensuel via Stripe, avec activation/désactivation de modules.
--
-- Différence avec la table `invoices` existante :
--   - `invoices` (migration 11_deals.sql) facture les CLIENTS de
--     Triskell Studio (= leurs propres clients finaux).
--   - `saas_subscriptions` (cette migration) gère l'abonnement
--     que CHAQUE WORKSPACE paie à Triskell Command lui-même
--     (= la facturation du SaaS).
--
-- Une seule subscription active par workspace.
-- ============================================================


create table if not exists public.saas_subscriptions (
  id              uuid primary key default gen_random_uuid(),
  workspace_id    uuid not null references public.workspaces(id) on delete cascade,

  -- Identifiants Stripe (sources de vérité externes)
  stripe_customer_id      text,                          -- cus_XXX
  stripe_subscription_id  text unique,                   -- sub_XXX
  stripe_price_id_base    text,                          -- price_XXX (Essentiel)

  -- État du cycle
  status          text not null default 'trialing',
                  -- trialing | active | past_due | canceled | incomplete
  current_period_start timestamptz,
  current_period_end   timestamptz,
  cancel_at_period_end boolean default false,

  -- Plan résolu (recalcul à chaque webhook)
  plan_code       text not null default 'essential',
                  -- essential | essential+pro | essential+phare | essential+pro+phare

  -- Modules activés (snapshot dérivé de plan_code, dénormalisé pour rapidité d'accès)
  has_essential   boolean not null default true,
  has_pro         boolean not null default false,
  has_phare       boolean not null default false,

  -- Tarification courante (snapshot, en centimes EUR)
  amount_monthly_cents int not null default 3900,

  -- Métadonnées
  trial_end       timestamptz,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create unique index if not exists saas_sub_one_per_workspace
  on public.saas_subscriptions (workspace_id);

create index if not exists saas_sub_status_idx
  on public.saas_subscriptions (status);


-- ─────────────────────────────────────────────────────────────
-- Journal des évènements Stripe reçus (debug + audit)
-- ─────────────────────────────────────────────────────────────
create table if not exists public.stripe_events (
  id          uuid primary key default gen_random_uuid(),
  workspace_id uuid references public.workspaces(id) on delete set null,
  event_id    text unique,                               -- evt_XXX (anti-replay)
  type        text not null,                             -- "customer.subscription.updated", etc.
  payload     jsonb not null,
  received_at timestamptz not null default now(),
  processed   boolean not null default false,
  error       text
);


-- ─────────────────────────────────────────────────────────────
-- RLS : un workspace ne voit QUE sa propre subscription
-- ─────────────────────────────────────────────────────────────
alter table public.saas_subscriptions enable row level security;
alter table public.stripe_events      enable row level security;

create policy "sub_self_select" on public.saas_subscriptions
  for select to authenticated
  using (workspace_id = public.current_workspace_id());

-- Pas d'INSERT/UPDATE/DELETE pour les users : seul le webhook
-- côté service_role peut modifier les subscriptions.
-- (Aucune policy = personne ne peut écrire en mode authenticated)

create policy "stripe_events_self_select" on public.stripe_events
  for select to authenticated
  using (workspace_id = public.current_workspace_id());


-- ─────────────────────────────────────────────────────────────
-- Helper : a-t-on accès à un module donné dans le workspace courant ?
-- ─────────────────────────────────────────────────────────────
create or replace function public.workspace_has_module(p_module text)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select case p_module
           when 'essential' then coalesce(s.has_essential, false)
           when 'pro'       then coalesce(s.has_pro, false)
           when 'phare'     then coalesce(s.has_phare, false)
           else false
         end
    from public.saas_subscriptions s
   where s.workspace_id = public.current_workspace_id()
     and s.status in ('trialing', 'active')
   limit 1;
$$;
