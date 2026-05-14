-- ============================================================
-- Migration 09 — Table CLIENTS master (fiche client unifiée)
-- ============================================================
-- Pourquoi : aujourd'hui un client est éclaté entre prospects,
-- client_projects, wow_intakes, rankus_intakes, lagriffe_intakes,
-- invoices, email_history, Stripe customer. Impossible d'avoir
-- une vue 360° par requête simple.
--
-- Cette migration introduit une table `clients` master, ajoute
-- une FK `client_id` sur toutes les tables clients-related,
-- et un backfill rétroactif (création d'un client par email
-- unique trouvé dans toutes les sources).
-- ============================================================

-- ─────────────────────────────────────────────────────────────
-- 1. Table master `clients`
-- ─────────────────────────────────────────────────────────────
create table if not exists public.clients (
  id              uuid primary key default gen_random_uuid(),
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),

  -- Identité canonique (email = clé naturelle)
  email           text not null,
  first_name      text default '',
  last_name       text default '',
  phone           text default '',

  -- Pro
  is_pro          boolean default false,
  company_name    text default '',
  siret           text default '',
  vat_number      text default '',

  -- Adresse
  address_line1   text default '',
  address_line2   text default '',
  address_zip     text default '',
  address_city    text default '',
  address_country text default 'France',

  -- Source d'acquisition + tags
  sources         jsonb not null default '[]'::jsonb,
  tags            jsonb not null default '[]'::jsonb,
  status          text not null default 'lead',
  notes           text default '',

  -- Liens externes
  stripe_customer_id text default '',

  -- Timestamps métier
  first_contact_at  timestamptz,
  last_contact_at   timestamptz,
  first_paid_at     timestamptz,
  total_paid_cents  bigint not null default 0
);

-- Unicité de l'email (case-insensitive)
create unique index if not exists clients_email_lower_idx
  on public.clients (lower(email));

create index if not exists clients_status_idx on public.clients (status);
create index if not exists clients_stripe_idx on public.clients (stripe_customer_id);
create index if not exists clients_created_idx on public.clients (created_at desc);
create index if not exists clients_last_contact_idx on public.clients (last_contact_at desc nulls last);

-- ─────────────────────────────────────────────────────────────
-- 2. Fonction utilitaire updated_at (si pas déjà créée)
-- ─────────────────────────────────────────────────────────────
create or replace function public.set_clients_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at := now();
  return new;
end$$;

drop trigger if exists clients_updated_at on public.clients;
create trigger clients_updated_at
  before update on public.clients
  for each row execute function public.set_clients_updated_at();

-- ─────────────────────────────────────────────────────────────
-- 3. Fonction `ensure_client` : upsert idempotent
-- Renvoie l'UUID du client (créé ou existant). Met à jour les
-- champs vides avec les valeurs fournies (jamais d'écrasement
-- destructif d'une valeur existante).
-- ─────────────────────────────────────────────────────────────
create or replace function public.ensure_client(
  p_email text,
  p_first_name text default null,
  p_last_name text default null,
  p_phone text default null,
  p_company_name text default null,
  p_siret text default null,
  p_source text default null
) returns uuid
language plpgsql as $$
declare
  v_id uuid;
  v_email text := lower(trim(p_email));
begin
  if v_email is null or v_email = '' or position('@' in v_email) = 0 then
    raise exception 'ensure_client: email invalide (%)', p_email;
  end if;

  -- Existe déjà ?
  select id into v_id from public.clients where lower(email) = v_email limit 1;

  if v_id is null then
    insert into public.clients (
      email, first_name, last_name, phone, company_name, siret,
      is_pro, sources, first_contact_at, last_contact_at
    ) values (
      v_email,
      coalesce(p_first_name, ''),
      coalesce(p_last_name, ''),
      coalesce(p_phone, ''),
      coalesce(p_company_name, ''),
      coalesce(p_siret, ''),
      coalesce(p_company_name, '') <> '' or coalesce(p_siret, '') <> '',
      case when p_source is not null
           then jsonb_build_array(p_source)
           else '[]'::jsonb end,
      now(),
      now()
    )
    returning id into v_id;
  else
    -- Met à jour les champs vides UNIQUEMENT (jamais d'écrasement)
    update public.clients set
      first_name   = case when first_name = '' and p_first_name is not null then p_first_name else first_name end,
      last_name    = case when last_name = '' and p_last_name is not null then p_last_name else last_name end,
      phone        = case when phone = '' and p_phone is not null then p_phone else phone end,
      company_name = case when company_name = '' and p_company_name is not null then p_company_name else company_name end,
      siret        = case when siret = '' and p_siret is not null then p_siret else siret end,
      is_pro       = is_pro or (coalesce(p_company_name, '') <> '' or coalesce(p_siret, '') <> ''),
      sources      = case
                       when p_source is not null and not (sources @> jsonb_build_array(p_source))
                         then sources || jsonb_build_array(p_source)
                       else sources
                     end,
      last_contact_at = now()
    where id = v_id;
  end if;

  return v_id;
end$$;

-- ─────────────────────────────────────────────────────────────
-- 4. Ajout de `client_id` (FK) sur les tables existantes
-- ─────────────────────────────────────────────────────────────

-- prospects (lead acquis via prospection)
alter table public.prospects
  add column if not exists client_id uuid references public.clients(id) on delete set null;
create index if not exists prospects_client_id_idx on public.prospects (client_id);

-- client_projects (kanban livraison)
alter table public.client_projects
  add column if not exists client_id uuid references public.clients(id) on delete set null;
create index if not exists client_projects_client_id_idx on public.client_projects (client_id);

-- wow_intakes
alter table public.wow_intakes
  add column if not exists client_id uuid references public.clients(id) on delete set null;
create index if not exists wow_intakes_client_id_idx on public.wow_intakes (client_id);

-- rankus_intakes
alter table public.rankus_intakes
  add column if not exists client_id uuid references public.clients(id) on delete set null;
create index if not exists rankus_intakes_client_id_idx on public.rankus_intakes (client_id);

-- lagriffe_intakes
alter table public.lagriffe_intakes
  add column if not exists client_id uuid references public.clients(id) on delete set null;
create index if not exists lagriffe_intakes_client_id_idx on public.lagriffe_intakes (client_id);

-- invoices (facturation maison)
alter table public.invoices
  add column if not exists client_id uuid references public.clients(id) on delete set null;
create index if not exists invoices_client_id_idx on public.invoices (client_id);

-- email_history (emails sortants)
alter table public.email_history
  add column if not exists client_id uuid references public.clients(id) on delete set null;
create index if not exists email_history_client_id_idx on public.email_history (client_id);

-- ─────────────────────────────────────────────────────────────
-- 5. BACKFILL : crée un client pour chaque email unique trouvé
-- dans toutes les sources, puis rattache via FK.
-- ─────────────────────────────────────────────────────────────

-- 5.1 — Prospects (emails en jsonb array)
insert into public.clients (email, first_name, last_name, phone, company_name, sources, first_contact_at, last_contact_at)
select distinct on (lower(emails->>0))
  emails->>0,
  '',
  coalesce(name, ''),
  coalesce(phones->>0, ''),
  coalesce(legal_name, ''),
  jsonb_build_array('prospect'),
  coalesce(created_at, now()),
  coalesce(created_at, now())
from public.prospects
where emails->>0 is not null
  and position('@' in (emails->>0)) > 0
on conflict (email) do nothing;

update public.prospects p
set client_id = c.id
from public.clients c
where p.client_id is null
  and p.emails->>0 is not null
  and lower(c.email) = lower(p.emails->>0);

-- 5.2 — wow_intakes
insert into public.clients (email, first_name, last_name, phone, company_name, siret, vat_number, sources, first_contact_at, last_contact_at)
select distinct on (lower(client_email))
  lower(client_email),
  coalesce(client_first_name, ''),
  coalesce(client_last_name, ''),
  coalesce(client_phone, ''),
  coalesce(company_name, ''),
  coalesce(siret, ''),
  coalesce(vat_number, ''),
  jsonb_build_array('wow_intake'),
  coalesce(created_at, now()),
  coalesce(created_at, now())
from public.wow_intakes
where client_email is not null and position('@' in client_email) > 0
on conflict (email) do nothing;

update public.wow_intakes w
set client_id = c.id
from public.clients c
where w.client_id is null
  and w.client_email is not null
  and lower(c.email) = lower(w.client_email);

-- 5.3 — rankus_intakes
insert into public.clients (email, first_name, last_name, phone, company_name, siret, vat_number, sources, first_contact_at, last_contact_at)
select distinct on (lower(client_email))
  lower(client_email),
  coalesce(client_first_name, ''),
  coalesce(client_last_name, ''),
  coalesce(client_phone, ''),
  coalesce(company_name, ''),
  coalesce(siret, ''),
  coalesce(vat_number, ''),
  jsonb_build_array('rankus_intake'),
  coalesce(created_at, now()),
  coalesce(created_at, now())
from public.rankus_intakes
where client_email is not null and position('@' in client_email) > 0
on conflict (email) do nothing;

update public.rankus_intakes r
set client_id = c.id
from public.clients c
where r.client_id is null
  and r.client_email is not null
  and lower(c.email) = lower(r.client_email);

-- 5.4 — lagriffe_intakes
insert into public.clients (email, first_name, last_name, phone, company_name, siret, vat_number, sources, first_contact_at, last_contact_at)
select distinct on (lower(client_email))
  lower(client_email),
  coalesce(client_first_name, ''),
  coalesce(client_last_name, ''),
  coalesce(client_phone, ''),
  coalesce(company_name, ''),
  coalesce(siret, ''),
  coalesce(vat_number, ''),
  jsonb_build_array('lagriffe_intake'),
  coalesce(created_at, now()),
  coalesce(created_at, now())
from public.lagriffe_intakes
where client_email is not null and position('@' in client_email) > 0
on conflict (email) do nothing;

update public.lagriffe_intakes l
set client_id = c.id
from public.clients c
where l.client_id is null
  and l.client_email is not null
  and lower(c.email) = lower(l.client_email);

-- 5.5 — invoices (si la table existe avec une colonne client_email_snapshot)
do $$
begin
  if exists (select 1 from information_schema.columns where table_name = 'invoices' and column_name = 'client_email_snapshot') then
    -- Crée les clients depuis invoices
    insert into public.clients (email, first_name, last_name, company_name, address_line1, address_zip, address_city, sources, first_contact_at, last_contact_at, total_paid_cents, first_paid_at)
    select distinct on (lower(client_email_snapshot))
      lower(client_email_snapshot),
      '',
      coalesce(client_name_snapshot, ''),
      coalesce(client_company_snapshot, ''),
      coalesce(client_address_line1_snapshot, ''),
      coalesce(client_address_zip_snapshot, ''),
      coalesce(client_address_city_snapshot, ''),
      jsonb_build_array('invoice'),
      coalesce(created_at, now()),
      coalesce(created_at, now()),
      0,
      created_at
    from public.invoices
    where client_email_snapshot is not null and position('@' in client_email_snapshot) > 0
    on conflict (email) do nothing;

    update public.invoices i
    set client_id = c.id
    from public.clients c
    where i.client_id is null
      and i.client_email_snapshot is not null
      and lower(c.email) = lower(i.client_email_snapshot);
  end if;
end$$;

-- 5.6 — client_projects (déjà partiellement liés à prospects)
update public.client_projects cp
set client_id = c.id
from public.clients c
where cp.client_id is null
  and cp.client_email is not null and cp.client_email <> ''
  and lower(c.email) = lower(cp.client_email);

-- ─────────────────────────────────────────────────────────────
-- 6. VUE `clients_360` — agrégation complète par client
-- Permet à la fiche client de récupérer tout en une requête.
-- ─────────────────────────────────────────────────────────────
create or replace view public.clients_360 as
select
  c.id,
  c.created_at,
  c.updated_at,
  c.email,
  c.first_name,
  c.last_name,
  trim(c.first_name || ' ' || c.last_name) as full_name,
  c.phone,
  c.is_pro,
  c.company_name,
  c.siret,
  c.vat_number,
  c.address_line1,
  c.address_zip,
  c.address_city,
  c.address_country,
  c.sources,
  c.tags,
  c.status,
  c.notes,
  c.stripe_customer_id,
  c.first_contact_at,
  c.last_contact_at,
  c.first_paid_at,
  c.total_paid_cents,
  -- Compteurs agrégés
  (select count(*) from public.lagriffe_intakes where client_id = c.id) as lagriffe_count,
  (select count(*) from public.rankus_intakes where client_id = c.id) as rankus_count,
  (select count(*) from public.wow_intakes where client_id = c.id) as wow_count,
  (select count(*) from public.invoices where client_id = c.id) as invoices_count,
  (select count(*) from public.email_history where client_id = c.id) as emails_sent_count,
  (select count(*) from public.client_projects where client_id = c.id) as projects_count
from public.clients c;

-- ─────────────────────────────────────────────────────────────
-- 7. Bilan
-- ─────────────────────────────────────────────────────────────
do $$
declare
  v_count int;
begin
  select count(*) into v_count from public.clients;
  raise notice 'Migration 09 OK — % clients dans la table master après backfill.', v_count;
end$$;
