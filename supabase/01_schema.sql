-- =====================================================================
-- Triskell Command — Schéma Supabase / Postgres
-- =====================================================================
-- À exécuter UNE FOIS dans le SQL Editor de Supabase, dans l'ordre :
--   1. 01_schema.sql   (ce fichier — tables + indices)
--   2. 02_rls.sql      (Row-Level Security : qui voit/écrit quoi)
--   3. 03_seed.sql     (création des 2 profils Jordan + Thomas)
--
-- Conventions :
--   - Tous les ID sont des UUID v4 (gen_random_uuid()).
--   - Les timestamps sont en TIMESTAMPTZ (avec timezone).
--   - Les listes / dicts complexes sont en JSONB (Postgres natif).
--   - Toutes les tables ont created_by / updated_by → user_id Supabase Auth.
-- =====================================================================

create extension if not exists "pgcrypto";   -- pour gen_random_uuid()


-- ---------------------------------------------------------------------
-- users : profils internes Triskell (Jordan + Thomas)
--   - user_id = id Supabase Auth (auth.users.id)
--   - display_name = "Jordan" / "Thomas" (affiché dans la status bar)
-- ---------------------------------------------------------------------
create table public.users (
    user_id uuid primary key references auth.users(id) on delete cascade,
    display_name text not null,
    color text default '#7C7FE9',
    created_at timestamptz not null default now()
);


-- ---------------------------------------------------------------------
-- shared_settings : clés API IA + SMTP partagés entre Jordan et Thomas
-- (Jordan a dit "clé commune" — donc valeurs en base, pas en local)
-- ---------------------------------------------------------------------
create table public.shared_settings (
    key text primary key,
    value jsonb not null default '{}'::jsonb,
    updated_by uuid references public.users(user_id),
    updated_at timestamptz not null default now()
);


-- ---------------------------------------------------------------------
-- prospects : CRM unifié (remplace ~/.triskell-prospect/prospects.json)
-- ---------------------------------------------------------------------
create table public.prospects (
    id uuid primary key default gen_random_uuid(),

    -- Identité
    name text default '',
    handle text default '',
    legal_name text default '',
    siren text default '',

    -- Contact (listes en JSONB pour rester compatible avec le code Python existant)
    emails jsonb not null default '[]'::jsonb,           -- list[str]
    phones jsonb not null default '[]'::jsonb,           -- list[str]
    website text default '',
    other_urls jsonb not null default '[]'::jsonb,
    address text default '',
    city text default '',
    postal_code text default '',
    country text default '',

    -- Activité
    industry text default '',
    naf_code text default '',
    description text default '',
    language text default '',

    -- Signal commercial
    monetized boolean not null default false,
    monetization_reasons jsonb not null default '[]'::jsonb,
    has_legal_mentions boolean not null default false,
    score int not null default 0,
    score_label text default '',
    subscribers bigint,
    platform_url text default '',

    -- CRM
    status text not null default 'new',                  -- new/qualified/contacted/replied/refused/won/lost
    tags jsonb not null default '[]'::jsonb,
    notes text default '',
    last_contact_at timestamptz,

    -- Provenance (liste de Source : {name, source_id, url, found_at})
    sources jsonb not null default '[]'::jsonb,

    -- Match keys (calculées côté client à partir de email/phone/website/source)
    -- On les stocke aussi en colonne pour les indices Postgres rapides.
    match_keys jsonb not null default '[]'::jsonb,

    -- Audit
    created_by uuid references public.users(user_id),
    updated_by uuid references public.users(user_id),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index idx_prospects_status on public.prospects (status);
create index idx_prospects_city on public.prospects (city);
-- GIN index sur les match_keys pour faire du dédoublonnage rapide
create index idx_prospects_match_keys on public.prospects using gin (match_keys jsonb_path_ops);
-- GIN aussi sur emails et phones pour chercher par contact
create index idx_prospects_emails on public.prospects using gin (emails jsonb_path_ops);


-- ---------------------------------------------------------------------
-- email_history : log d'envois (l'ancien Prospect.history, isolé pour
-- pouvoir requêter facilement "tous les mails envoyés ce mois-ci")
-- ---------------------------------------------------------------------
create table public.email_history (
    id uuid primary key default gen_random_uuid(),
    prospect_id uuid not null references public.prospects(id) on delete cascade,
    kind text not null,                                  -- email_sent / reply_received / draft_generated...
    ts timestamptz not null default now(),
    subject text default '',
    body text default '',
    template_key text default '',
    provider text default '',
    model text default '',
    message_id text default '',                          -- Message-ID SMTP
    extra jsonb not null default '{}'::jsonb,
    created_by uuid references public.users(user_id)
);

create index idx_email_history_prospect on public.email_history (prospect_id);
create index idx_email_history_ts on public.email_history (ts desc);


-- ---------------------------------------------------------------------
-- prospect_drafts : les pending_drafts du Dénicheur (mode validation)
-- ---------------------------------------------------------------------
create table public.prospect_drafts (
    id uuid primary key default gen_random_uuid(),
    prospect_id uuid not null references public.prospects(id) on delete cascade,
    subject text default '',
    body text default '',
    template_key text default '',
    provider text default '',
    model text default '',
    kind text default 'first_contact',                   -- first_contact / follow_up...
    status text not null default 'pending',              -- pending/approved/sent/rejected
    created_by uuid references public.users(user_id),
    approved_by uuid references public.users(user_id),
    created_at timestamptz not null default now(),
    approved_at timestamptz,
    sent_at timestamptz
);

create index idx_prospect_drafts_status on public.prospect_drafts (status);
create index idx_prospect_drafts_prospect on public.prospect_drafts (prospect_id);


-- ---------------------------------------------------------------------
-- templates : modèles de mails (le templates.json user)
-- ---------------------------------------------------------------------
create table public.templates (
    key text primary key,
    channel text not null default 'email',
    subject text default '',
    body text not null,
    is_default boolean not null default false,           -- vrai = template livré par défaut, ne pas écraser
    created_by uuid references public.users(user_id),
    updated_by uuid references public.users(user_id),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);


-- ---------------------------------------------------------------------
-- convoy_campaigns : Le Convoi (remplace ~/.triskell-command/convoy/*.json)
-- ---------------------------------------------------------------------
create table public.convoy_campaigns (
    id uuid primary key default gen_random_uuid(),
    name text not null,
    source_file text default '',
    mode text not null default 'validation',             -- validation / auto
    user_brief text default '',
    catalog jsonb not null default '[]'::jsonb,
    daily_cap int not null default 40,
    delay_seconds int not null default 60,
    schedule_at timestamptz,
    sender_account_id text not null default 'primary',   -- id du compte mail expéditeur
                                                          -- ('primary' = compte principal,
                                                          -- sinon id d'un compte secondaire stocké
                                                          -- dans shared_settings.mail_accounts)
    raw_text text default '',                            -- texte brut extrait du fichier
    created_by uuid references public.users(user_id),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index idx_convoy_campaigns_created_at on public.convoy_campaigns (created_at desc);


-- ---------------------------------------------------------------------
-- convoy_drafts : drafts d'une campagne Convoi (les mails à envoyer)
-- ---------------------------------------------------------------------
create table public.convoy_drafts (
    id uuid primary key default gen_random_uuid(),
    campaign_id uuid not null references public.convoy_campaigns(id) on delete cascade,
    prospect jsonb not null default '{}'::jsonb,         -- snapshot des champs extraits
    subject text default '',
    body text default '',
    offer_name text default '',
    status text not null default 'pending',              -- pending/approved/sent/failed/rejected
    sent_at timestamptz,
    error text default '',
    message_id text default '',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index idx_convoy_drafts_campaign on public.convoy_drafts (campaign_id);
create index idx_convoy_drafts_status on public.convoy_drafts (status);


-- ---------------------------------------------------------------------
-- send_log : compteur quotidien d'envois (cap quotidien partagé)
-- ---------------------------------------------------------------------
create table public.send_log (
    day date primary key,
    count int not null default 0,
    last_send_at timestamptz
);


-- ---------------------------------------------------------------------
-- triggers : auto-update updated_at à chaque UPDATE
-- ---------------------------------------------------------------------
create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

create trigger trg_prospects_updated_at
    before update on public.prospects
    for each row execute procedure public.set_updated_at();

create trigger trg_templates_updated_at
    before update on public.templates
    for each row execute procedure public.set_updated_at();

create trigger trg_convoy_campaigns_updated_at
    before update on public.convoy_campaigns
    for each row execute procedure public.set_updated_at();

create trigger trg_convoy_drafts_updated_at
    before update on public.convoy_drafts
    for each row execute procedure public.set_updated_at();
