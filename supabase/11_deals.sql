-- =====================================================================
-- Triskell Command — Migration 11 : Deals (commandes Stripe + devis)
-- =====================================================================
-- Suit la chaîne post-paiement de l'écosystème Triskell :
--   formulaire → deal créé (status=pending) → checkout Stripe
--   → webhook → status=paid → facture émise → site fabriqué
--   → status=livre_actif (puis activation Phare si SEO).
-- =====================================================================

create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------------
-- deals : une commande (un acheteur, un site, optionnellement un SEO)
-- ---------------------------------------------------------------------
create table if not exists public.deals (
    id uuid primary key default gen_random_uuid(),

    -- Source du deal (quel site/produit Triskell)
    source text not null default 'rankus-studio',  -- "rankus-studio" | "pack-electricien" | etc.

    -- Coordonnées client
    contact_name text not null,
    contact_email text not null,
    contact_phone text default '',
    company_name text default '',
    sector text default '',
    brief text default '',

    -- Offre commandée
    site_offer text default '',          -- "starter" | "boutique" | "sur-mesure"
    with_seo boolean not null default false,
    amount_ttc_cents bigint not null default 0,

    -- Stripe
    stripe_checkout_session_id text default '',
    stripe_payment_intent_id text default '',
    stripe_subscription_id text default '',  -- pour le SEO mensuel

    -- Suivi
    -- pending          : créé en base, paiement non encore validé
    -- paid             : paiement validé, en attente de fabrication
    -- fabrication      : site en cours de fabrication
    -- livre_actif      : site livré, client actif
    -- annule           : annulé (avoir émis)
    status text not null default 'pending'
        check (status in ('pending', 'paid', 'fabrication', 'livre_actif', 'annule')),

    -- Liens
    site_url text default '',
    phare_site_id uuid,                   -- référence phare_sites si SEO actif
    invoice_id uuid,                      -- référence invoices après émission

    -- Idempotence : éviter de re-traiter un webhook Stripe déjà traité
    processed_session_ids jsonb not null default '[]'::jsonb,

    -- Métadonnées
    paid_at timestamptz,
    fabrication_started_at timestamptz,
    delivered_at timestamptz,

    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_deals_email on public.deals (contact_email);
create index if not exists idx_deals_status on public.deals (status);
create index if not exists idx_deals_source on public.deals (source);
create index if not exists idx_deals_stripe_session on public.deals (stripe_checkout_session_id);
create index if not exists idx_deals_created_at on public.deals (created_at desc);

-- Trigger updated_at
create or replace function public.deals_set_updated_at()
returns trigger language plpgsql as $$
begin new.updated_at := now(); return new; end;
$$;

drop trigger if exists trg_deals_updated_at on public.deals;
create trigger trg_deals_updated_at before update on public.deals
    for each row execute function public.deals_set_updated_at();

-- ---------------------------------------------------------------------
-- quote_requests : demandes de devis sur-mesure (pas de paiement direct)
-- ---------------------------------------------------------------------
create table if not exists public.quote_requests (
    id uuid primary key default gen_random_uuid(),
    source text not null default 'rankus-studio',
    contact_name text not null,
    contact_email text not null,
    contact_phone text default '',
    company_name text default '',
    sector text default '',
    brief text default '',
    with_seo boolean not null default false,
    -- pending : reçu, à traiter par Jordan
    -- replied : devis envoyé
    -- won     : converti en deal
    -- lost    : refus du client
    status text not null default 'pending'
        check (status in ('pending', 'replied', 'won', 'lost')),
    notes text default '',
    replied_at timestamptz,
    converted_deal_id uuid references public.deals(id),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_quote_requests_email on public.quote_requests (contact_email);
create index if not exists idx_quote_requests_status on public.quote_requests (status);

drop trigger if exists trg_quote_requests_updated_at on public.quote_requests;
create trigger trg_quote_requests_updated_at before update on public.quote_requests
    for each row execute function public.deals_set_updated_at();

-- ---------------------------------------------------------------------
-- RLS
-- ---------------------------------------------------------------------
alter table public.deals enable row level security;
alter table public.quote_requests enable row level security;

drop policy if exists deals_authed on public.deals;
create policy deals_authed on public.deals
    for all using (auth.uid() is not null)
    with check (auth.uid() is not null);

drop policy if exists quote_requests_authed on public.quote_requests;
create policy quote_requests_authed on public.quote_requests
    for all using (auth.uid() is not null)
    with check (auth.uid() is not null);

-- Fin migration 11
