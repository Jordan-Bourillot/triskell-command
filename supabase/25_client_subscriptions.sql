-- ============================================================
-- Migration 25 — ABONNEMENTS CLIENTS (recurring Stripe)
-- ============================================================
-- À appliquer APRÈS les migrations 20_multi_tenant et 21_saas_subscriptions.
--
-- Objectif : permettre à Triskell de facturer ses CLIENTS FINAUX
-- (acheteurs de sites, SEO, contenu) en mode abonnement mensuel
-- Stripe — distinct des abonnements SaaS au produit Command lui-même.
--
-- Cas d'usage typique : un client RankUs SEO paie 490 €/mois pour
-- son référencement Google. Chaque mois, Stripe prélève sa carte,
-- on émet une facture FR conforme et on l'envoie automatiquement.
-- ============================================================


-- ─────────────────────────────────────────────────────────────
-- Table client_subscriptions
-- ─────────────────────────────────────────────────────────────
-- Une ligne = un abonnement récurrent d'un client à un service
-- (SEO, hébergement, support, etc.). Un client peut en avoir
-- plusieurs en parallèle (ex. SEO + hébergement).
-- ─────────────────────────────────────────────────────────────
create table if not exists public.client_subscriptions (
  id              uuid primary key default gen_random_uuid(),
  client_id       uuid not null references public.clients(id) on delete cascade,
  workspace_id    uuid references public.workspaces(id) on delete cascade,

  -- Description vue côté client (apparaît sur la facture)
  description     text not null default 'Abonnement mensuel',
  product_kind    text not null default 'seo',
                  -- "seo" | "hosting" | "support" | "site_lease" | "other"

  -- Tarification (en centimes EUR, snapshot figé au moment de la création)
  amount_monthly_cents int not null,
  currency        text not null default 'EUR',

  -- Identifiants Stripe (sources de vérité externes)
  stripe_customer_id      text,                   -- cus_XXX
  stripe_subscription_id  text unique,            -- sub_XXX
  stripe_price_id         text,                   -- price_XXX (créé à la volée)

  -- État du cycle (mirroir des évènements Stripe)
  status          text not null default 'incomplete',
                  -- incomplete | trialing | active | past_due | canceled
  current_period_start timestamptz,
  current_period_end   timestamptz,
  cancel_at_period_end boolean default false,

  -- Suivi
  started_at      timestamptz,                    -- 1er paiement réussi
  canceled_at     timestamptz,
  last_invoice_at timestamptz,
  last_invoice_id uuid,                           -- → public.invoices(id)

  -- Métadonnées libres (notes internes Jordan)
  notes           text default '',

  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create index if not exists client_sub_client_idx
  on public.client_subscriptions (client_id);
create index if not exists client_sub_status_idx
  on public.client_subscriptions (status);
create index if not exists client_sub_workspace_idx
  on public.client_subscriptions (workspace_id);


-- ─────────────────────────────────────────────────────────────
-- Trigger updated_at
-- ─────────────────────────────────────────────────────────────
create or replace function public.client_subscriptions_set_updated_at()
returns trigger language plpgsql as $$
begin new.updated_at := now(); return new; end$$;

drop trigger if exists trg_client_subscriptions_updated_at
  on public.client_subscriptions;
create trigger trg_client_subscriptions_updated_at
  before update on public.client_subscriptions
  for each row execute function public.client_subscriptions_set_updated_at();


-- ─────────────────────────────────────────────────────────────
-- Backfill workspace_id : tout va dans le workspace "triskell-studio"
-- ─────────────────────────────────────────────────────────────
update public.client_subscriptions
   set workspace_id = (select id from public.workspaces where slug = 'triskell-studio')
 where workspace_id is null;


-- ─────────────────────────────────────────────────────────────
-- RLS : un workspace ne voit QUE ses propres abonnements clients
-- ─────────────────────────────────────────────────────────────
alter table public.client_subscriptions enable row level security;

drop policy if exists "client_sub_ws_select" on public.client_subscriptions;
create policy "client_sub_ws_select" on public.client_subscriptions
  for select to authenticated
  using (workspace_id = public.current_workspace_id());

drop policy if exists "client_sub_ws_insert" on public.client_subscriptions;
create policy "client_sub_ws_insert" on public.client_subscriptions
  for insert to authenticated
  with check (workspace_id = public.current_workspace_id());

drop policy if exists "client_sub_ws_update" on public.client_subscriptions;
create policy "client_sub_ws_update" on public.client_subscriptions
  for update to authenticated
  using (workspace_id = public.current_workspace_id())
  with check (workspace_id = public.current_workspace_id());

drop policy if exists "client_sub_ws_delete" on public.client_subscriptions;
create policy "client_sub_ws_delete" on public.client_subscriptions
  for delete to authenticated
  using (workspace_id = public.current_workspace_id());


-- ─────────────────────────────────────────────────────────────
-- CONTRÔLE FINAL — à exécuter manuellement après migration
-- ─────────────────────────────────────────────────────────────
-- select count(*) from public.client_subscriptions;
-- select policyname from pg_policies where tablename = 'client_subscriptions';
