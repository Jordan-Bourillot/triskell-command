-- =====================================================================
-- TRISKELL COMMAND + LE PHARE — Migration complète (1 fichier)
-- =====================================================================
-- Généré automatiquement. À coller dans le SQL Editor de Supabase puis
-- cliquer Run UNE FOIS.
--
-- Contenu :
--   0. Drop des 2 tables vides du backend lanceur (users, licenses)
--   1. Schéma Triskell Command (01_schema)
--   2. Row-Level Security (02_rls)
--   3. Seed Jordan (03_seed adapté avec ton UUID Auth)
--   4. Tables client_projects + messages (04)
--   5. Tables email_events + typing (05)
--   6. Le Phare — schéma + seed 13 sites + RLS (06)
--   6b. Le Phare — mapping réel repos/netlify (06b)
--   6c. Le Phare — modules avancés (06c)
--   6d. Le Phare — modules pro v0.6 (06d)
-- =====================================================================

-- ----- 0. Drop des 2 tables vides du backend lanceur -----------------
-- (Aucune donnée à perdre, vérifié au préalable.)
drop table if exists public.licenses cascade;
drop table if exists public.users cascade;


-- ===== 01_schema.sql =====

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



-- ===== 02_rls.sql =====

-- =====================================================================
-- Triskell Command — Row-Level Security (RLS)
-- =====================================================================
-- Politique : "tout user authentifié voit tout, peut tout éditer."
-- (Décision Jordan : il bosse avec Thomas, ils partagent tout.)
--
-- Sécurité : un utilisateur NON authentifié n'a accès à RIEN. Donc même
-- si quelqu'un trouvait l'URL Supabase + l'anon key, il ne pourrait rien
-- lire / écrire sans login.
--
-- Si un jour on veut filtrer (ex: certains templates privés), on ajoutera
-- une colonne is_private + une condition USING (is_private = false OR
-- created_by = auth.uid()).
-- =====================================================================


-- 1. Activer RLS sur toutes les tables
alter table public.users              enable row level security;
alter table public.shared_settings    enable row level security;
alter table public.prospects          enable row level security;
alter table public.email_history      enable row level security;
alter table public.prospect_drafts    enable row level security;
alter table public.templates          enable row level security;
alter table public.convoy_campaigns   enable row level security;
alter table public.convoy_drafts      enable row level security;
alter table public.send_log           enable row level security;


-- 2. Helper macro : générer les 4 policies (SELECT/INSERT/UPDATE/DELETE)
--    pour un user authentifié qui voit/édite tout.
--    Postgres n'a pas de macros, on duplique mais clean.

-- ---- users -----------------------------------------------------------
create policy "auth read users" on public.users
    for select to authenticated using (true);
create policy "auth insert users" on public.users
    for insert to authenticated with check (true);
create policy "auth update users" on public.users
    for update to authenticated using (true) with check (true);

-- ---- shared_settings -------------------------------------------------
create policy "auth read shared_settings" on public.shared_settings
    for select to authenticated using (true);
create policy "auth insert shared_settings" on public.shared_settings
    for insert to authenticated with check (true);
create policy "auth update shared_settings" on public.shared_settings
    for update to authenticated using (true) with check (true);
create policy "auth delete shared_settings" on public.shared_settings
    for delete to authenticated using (true);

-- ---- prospects -------------------------------------------------------
create policy "auth read prospects" on public.prospects
    for select to authenticated using (true);
create policy "auth insert prospects" on public.prospects
    for insert to authenticated with check (true);
create policy "auth update prospects" on public.prospects
    for update to authenticated using (true) with check (true);
create policy "auth delete prospects" on public.prospects
    for delete to authenticated using (true);

-- ---- email_history ---------------------------------------------------
create policy "auth read email_history" on public.email_history
    for select to authenticated using (true);
create policy "auth insert email_history" on public.email_history
    for insert to authenticated with check (true);

-- ---- prospect_drafts -------------------------------------------------
create policy "auth read prospect_drafts" on public.prospect_drafts
    for select to authenticated using (true);
create policy "auth insert prospect_drafts" on public.prospect_drafts
    for insert to authenticated with check (true);
create policy "auth update prospect_drafts" on public.prospect_drafts
    for update to authenticated using (true) with check (true);
create policy "auth delete prospect_drafts" on public.prospect_drafts
    for delete to authenticated using (true);

-- ---- templates -------------------------------------------------------
create policy "auth read templates" on public.templates
    for select to authenticated using (true);
create policy "auth insert templates" on public.templates
    for insert to authenticated with check (true);
create policy "auth update templates" on public.templates
    for update to authenticated using (true) with check (true);
create policy "auth delete templates" on public.templates
    for delete to authenticated using (true);

-- ---- convoy_campaigns ------------------------------------------------
create policy "auth read convoy_campaigns" on public.convoy_campaigns
    for select to authenticated using (true);
create policy "auth insert convoy_campaigns" on public.convoy_campaigns
    for insert to authenticated with check (true);
create policy "auth update convoy_campaigns" on public.convoy_campaigns
    for update to authenticated using (true) with check (true);
create policy "auth delete convoy_campaigns" on public.convoy_campaigns
    for delete to authenticated using (true);

-- ---- convoy_drafts ---------------------------------------------------
create policy "auth read convoy_drafts" on public.convoy_drafts
    for select to authenticated using (true);
create policy "auth insert convoy_drafts" on public.convoy_drafts
    for insert to authenticated with check (true);
create policy "auth update convoy_drafts" on public.convoy_drafts
    for update to authenticated using (true) with check (true);
create policy "auth delete convoy_drafts" on public.convoy_drafts
    for delete to authenticated using (true);

-- ---- send_log --------------------------------------------------------
create policy "auth read send_log" on public.send_log
    for select to authenticated using (true);
create policy "auth insert send_log" on public.send_log
    for insert to authenticated with check (true);
create policy "auth update send_log" on public.send_log
    for update to authenticated using (true) with check (true);


-- 3. Realtime : activer la publication pour les tables qui doivent
--    pousser des notifications en temps réel quand un draft est validé,
--    qu'un prospect change de statut, etc.
alter publication supabase_realtime add table public.prospects;
alter publication supabase_realtime add table public.prospect_drafts;
alter publication supabase_realtime add table public.convoy_drafts;
alter publication supabase_realtime add table public.convoy_campaigns;
alter publication supabase_realtime add table public.shared_settings;



-- ===== 03_seed.sql (adapté avec UUID Jordan) =====

-- =====================================================================
-- Triskell Command — Seed initial (profils Jordan + Thomas)
-- =====================================================================
-- À exécuter APRÈS avoir créé les 2 comptes Supabase Auth via le dashboard
-- Supabase (Authentication → Users → Add user) :
--
--   1. Crée le compte Jordan : email = jordan@triskell-studio.fr
--      (ou ton email habituel)
--   2. Crée le compte Thomas : email = thomasbourillot@gmail.com
--   3. Récupère leurs UUID dans Authentication → Users
--   4. Remplace <JORDAN_UUID> et <THOMAS_UUID> ci-dessous
--   5. Lance ce SQL
--
-- Si tu te trompes : delete from public.users; et recommence.
-- =====================================================================


-- ⚠️ REMPLACE ces UUID par les vrais (visibles dans Supabase Auth → Users)
-- Tu peux aussi laisser ce fichier en l'état et le faire en 2 INSERT
-- séparés depuis le dashboard.
--
-- exemple : '00000000-0000-0000-0000-000000000001'

insert into public.users (user_id, display_name, color)
values
    ('915dda89-fafa-4fd8-9f90-6613919d3b69', 'Jordan', '#7C7FE9')    -- indigo
    -- ('<THOMAS_UUID>', 'Thomas', '#D4B35A')   -- ajouter quand Thomas créera son compte     -- or
on conflict (user_id) do nothing;


-- Settings partagés vides (l'app les remplira au premier passage dans Réglages)
insert into public.shared_settings (key, value) values
    ('ai',       '{"selected_provider":"anthropic","selected_model":"claude-sonnet-4-5","api_keys":{}}'),
    ('outreach', '{"smtp_host":"","smtp_port":587,"smtp_user":"","smtp_password":"","from_email":"","from_name":"","imap_host":"","imap_port":993,"imap_user":"","imap_password":"","daily_cap":40,"follow_up_days":5,"signature":""}'),
    ('sources',  '{"youtube_api_key":"","twitch_client_id":"","twitch_client_secret":"","google_places_api_key":""}')
on conflict (key) do nothing;



-- ===== 04_client_projects.sql =====

-- =====================================================================
-- Triskell Command — Migration 04 : table client_projects
-- =====================================================================
-- À exécuter UNE FOIS dans le SQL Editor de Supabase, après 01..03.
--
-- Objectif : kanban interne pour piloter la livraison des services
-- (Eliks Studio, Triskell Studio sites agence) après paiement.
-- Pas de Notion / Linear / Trello : tout reste dans Triskell Command.
-- =====================================================================

create table if not exists public.client_projects (
    id uuid primary key default gen_random_uuid(),
    prospect_id uuid references public.prospects(id) on delete set null,

    -- Identification du projet
    title text not null default '',
    product_key text not null default '',     -- ex: "eliks", "triskell-sites"
    product_name text not null default '',    -- libre, ex: "Site Despiertos Shop"

    -- Workflow
    status text not null default 'briefing',  -- briefing / in_progress / delivered / closed
    priority text not null default 'normal',  -- low / normal / high
    due_date date,

    -- Données client
    client_name text default '',
    client_email text default '',
    client_company text default '',

    -- Brief & livraison
    brief text default '',
    deliverables jsonb not null default '[]'::jsonb,   -- list[{label, url, done}]
    notes text default '',

    -- Vente
    amount_cents int not null default 0,
    currency text not null default 'EUR',
    paid_at timestamptz,
    stripe_session_id text default '',

    -- Post-vente automatisé
    cross_sell_sent_at timestamptz,
    nps_sent_at timestamptz,
    nps_score int,                            -- 0-10, null si pas encore reçu

    -- Audit
    assigned_to uuid references public.users(user_id),  -- Jordan / Thomas
    created_by uuid references public.users(user_id),
    updated_by uuid references public.users(user_id),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_client_projects_status on public.client_projects (status);
create index if not exists idx_client_projects_due on public.client_projects (due_date);
create index if not exists idx_client_projects_product on public.client_projects (product_key);
create index if not exists idx_client_projects_paid_at on public.client_projects (paid_at desc);

-- updated_at auto
drop trigger if exists trg_client_projects_updated_at on public.client_projects;
create trigger trg_client_projects_updated_at
    before update on public.client_projects
    for each row execute procedure public.set_updated_at();

-- RLS : aligné sur la convention (tout user authentifié voit/écrit)
alter table public.client_projects enable row level security;
drop policy if exists client_projects_all_select on public.client_projects;
create policy client_projects_all_select on public.client_projects
    for select using (auth.uid() is not null);
drop policy if exists client_projects_all_write on public.client_projects;
create policy client_projects_all_write on public.client_projects
    for all using (auth.uid() is not null) with check (auth.uid() is not null);



-- ===== 04_messages.sql =====

-- =====================================================================
-- Triskell Command — Chat 1-à-1 Jordan ↔ Thomas
-- =====================================================================
-- À exécuter UNE FOIS dans le SQL Editor de Supabase, après 01/02/03.
-- Crée la table `messages`, ses politiques RLS et l'ajoute au realtime.
-- =====================================================================


-- ---------------------------------------------------------------------
-- messages : un message court d'un user à un autre.
--   - Pas d'updated_at : un message envoyé n'est pas modifiable.
--   - read_at : passé à now() côté destinataire quand il ouvre le chat.
-- ---------------------------------------------------------------------
create table public.messages (
    id uuid primary key default gen_random_uuid(),
    sender_id uuid not null references public.users(user_id) on delete cascade,
    recipient_id uuid not null references public.users(user_id) on delete cascade,
    body text not null,
    created_at timestamptz not null default now(),
    read_at timestamptz
);

create index idx_messages_recipient_unread
    on public.messages (recipient_id, created_at desc)
    where read_at is null;

create index idx_messages_pair_created
    on public.messages (sender_id, recipient_id, created_at desc);


-- RLS : tout authentifié lit/écrit (cohérent avec les autres tables).
-- Lit/écrit, mais ne supprime pas (les messages restent en historique).
alter table public.messages enable row level security;

create policy "auth read messages" on public.messages
    for select to authenticated using (true);
create policy "auth insert messages" on public.messages
    for insert to authenticated with check (true);
create policy "auth update messages" on public.messages
    for update to authenticated using (true) with check (true);


-- Realtime : pour qu'un message envoyé par Jordan arrive vite chez Thomas
-- (même si on poll aussi côté client toutes les 10 s).
alter publication supabase_realtime add table public.messages;



-- ===== 05_email_events.sql =====

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



-- ===== 05_typing.sql =====

-- =====================================================================
-- Triskell Command — Indicateur « X est en train d'écrire » (chat)
-- =====================================================================
-- À exécuter UNE FOIS dans le SQL Editor de Supabase, après 04_messages.sql.
--
-- Modèle : 1 ligne par user. À chaque frappe (throttle 2 s côté client),
-- on UPSERT `until_ts = now() + 5 s`. L'autre user lit `until_ts > now()`
-- → "il écrit".
-- =====================================================================


create table public.typing_status (
    user_id uuid primary key references public.users(user_id) on delete cascade,
    until_ts timestamptz not null default now()
);


-- RLS : tout authentifié lit/écrit (cohérent avec le reste).
alter table public.typing_status enable row level security;

create policy "auth read typing_status" on public.typing_status
    for select to authenticated using (true);
create policy "auth insert typing_status" on public.typing_status
    for insert to authenticated with check (true);
create policy "auth update typing_status" on public.typing_status
    for update to authenticated using (true) with check (true);


-- Pas besoin de realtime sur cette table — on poll côté dialog ouvert.



-- ===== 06_phare.sql =====

-- =====================================================================
-- Triskell Command — Migration 06 : Le Phare (SEO autonome multi-sites)
-- =====================================================================
-- Module SEO embarqué dans Command. 8 agents Claude pilotent l'optimisation
-- de tous les sous-domaines *.triskell-studio.fr.
--
-- Tables :
--   phare_sites          → catalogue des sites surveillés
--   phare_audits         → snapshots techniques (Lighthouse, CWV, indexation)
--   phare_keywords       → mots-clés suivis (volume, position, intent)
--   phare_pages          → inventaire des URLs crawlées (titles, metas, hn)
--   phare_actions        → travail des agents (PRs, modifs, statut)
--   phare_metrics        → KPIs quotidiens (clicks, impressions, conversions)
--   phare_backlinks      → profil backlinks (analyse + opportunités)
--   phare_content_briefs → briefs de contenus à rédiger
-- =====================================================================

create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------------
-- phare_sites : un sous-domaine Triskell surveillé
-- ---------------------------------------------------------------------
create table if not exists public.phare_sites (
    id uuid primary key default gen_random_uuid(),
    name text not null,                     -- "Pack Électricien Pro"
    domain text unique not null,            -- "pack-elec.triskell-studio.fr"
    repo_github text default '',            -- "Jordan-Bourillot/pack-electricien"
    repo_branch_main text default 'main',
    netlify_site_id text default '',
    stack text default '',                  -- "astro" / "next" / "html"
    voice_pack text default 'triskell',     -- profil de voix injecté dans le prompt agent
    priority int default 50,                -- 0-100, plus haut = plus prioritaire
    is_active boolean not null default true,
    -- Pages clés à surveiller en diff visuel (max 10 chemins relatifs)
    key_paths jsonb not null default '["/"]'::jsonb,
    -- Bornes garde-fou
    perf_min_score int default 70,          -- Lighthouse perf minimum acceptable
    visual_diff_max_pct numeric default 5.0,
    -- Metadata libre
    notes text default '',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_phare_sites_active on public.phare_sites (is_active);
create index if not exists idx_phare_sites_priority on public.phare_sites (priority desc);

-- ---------------------------------------------------------------------
-- phare_audits : un snapshot technique d'un site à un instant T
-- ---------------------------------------------------------------------
create table if not exists public.phare_audits (
    id uuid primary key default gen_random_uuid(),
    site_id uuid not null references public.phare_sites(id) on delete cascade,
    ran_at timestamptz not null default now(),
    -- Lighthouse (0-100)
    lighthouse_perf int,
    lighthouse_seo int,
    lighthouse_a11y int,
    lighthouse_bp int,
    -- Core Web Vitals (PageSpeed Insights, terrain)
    cwv_lcp numeric,
    cwv_inp numeric,
    cwv_cls numeric,
    -- Crawl
    pages_crawled int default 0,
    pages_indexable int default 0,
    broken_links int default 0,
    redirects_chain int default 0,
    -- Schema.org
    schema_score int,
    -- Erreurs notables (liste de strings)
    issues jsonb not null default '[]'::jsonb,
    -- Résumé Markdown généré par l'Auditeur
    summary_md text default '',
    created_at timestamptz not null default now()
);

create index if not exists idx_phare_audits_site on public.phare_audits (site_id, ran_at desc);

-- ---------------------------------------------------------------------
-- phare_keywords : mots-clés suivis par site
-- ---------------------------------------------------------------------
create table if not exists public.phare_keywords (
    id uuid primary key default gen_random_uuid(),
    site_id uuid not null references public.phare_sites(id) on delete cascade,
    keyword text not null,
    volume int default 0,
    difficulty int default 0,               -- 0-100
    intent text default 'informational',    -- informational/commercial/transactional/navigational
    target_url text default '',
    current_position int,
    best_position int,
    last_checked_at timestamptz,
    created_at timestamptz not null default now(),
    unique (site_id, keyword)
);

create index if not exists idx_phare_keywords_site on public.phare_keywords (site_id);
create index if not exists idx_phare_keywords_pos on public.phare_keywords (current_position);

-- ---------------------------------------------------------------------
-- phare_pages : inventaire des URLs (titres, metas, structure Hn)
-- ---------------------------------------------------------------------
create table if not exists public.phare_pages (
    id uuid primary key default gen_random_uuid(),
    site_id uuid not null references public.phare_sites(id) on delete cascade,
    url text not null,
    path text not null,                     -- "/produit/pack" (sans domaine)
    title text default '',
    meta_description text default '',
    h1 text default '',
    h_outline jsonb not null default '[]'::jsonb,    -- [{level: 2, text: "..."}]
    word_count int default 0,
    internal_links int default 0,
    schema_types jsonb not null default '[]'::jsonb, -- ["Product", "BreadcrumbList"]
    last_crawled_at timestamptz,
    -- Score d'optimisation (0-100) calculé par l'Optimiseur On-Page
    optim_score int,
    optim_notes text default '',
    created_at timestamptz not null default now(),
    unique (site_id, path)
);

create index if not exists idx_phare_pages_site on public.phare_pages (site_id);

-- ---------------------------------------------------------------------
-- phare_actions : travail des agents (PRs ouvertes, modifs, recommandations)
-- ---------------------------------------------------------------------
create table if not exists public.phare_actions (
    id uuid primary key default gen_random_uuid(),
    site_id uuid not null references public.phare_sites(id) on delete cascade,
    agent text not null,                    -- "auditeur" / "optimiseur_onpage" / etc.
    kind text not null,                     -- "pr_modif" / "recommandation" / "alerte"
    title text not null,
    detail_md text default '',
    -- PR-related
    branch text default '',
    github_pr_url text default '',
    netlify_preview_url text default '',
    -- Garde-fous
    lighthouse_diff jsonb default '{}'::jsonb,
    visual_diff_pct numeric,
    broken_links_added int default 0,
    -- Statut : draft → preview → checks_ok|checks_ko → merged|rejected|expired
    status text not null default 'draft',
    auto_merged boolean default false,
    -- Priorisation (impact 1-5, effort 1-5)
    impact int default 3,
    effort int default 3,
    -- Files touchés
    files_touched jsonb not null default '[]'::jsonb,
    -- Logs
    created_at timestamptz not null default now(),
    merged_at timestamptz,
    rejected_at timestamptz,
    rejected_reason text default ''
);

create index if not exists idx_phare_actions_site on public.phare_actions (site_id, created_at desc);
create index if not exists idx_phare_actions_status on public.phare_actions (status);

-- ---------------------------------------------------------------------
-- phare_metrics : KPIs quotidiens par site
-- ---------------------------------------------------------------------
create table if not exists public.phare_metrics (
    id uuid primary key default gen_random_uuid(),
    site_id uuid not null references public.phare_sites(id) on delete cascade,
    metric_date date not null,
    organic_clicks int default 0,
    impressions int default 0,
    avg_position numeric,
    avg_ctr numeric,
    top10_count int default 0,
    top3_count int default 0,
    indexed_pages int default 0,
    conversions_attributed int default 0,
    revenue_attributed numeric default 0,
    source text default 'gsc',              -- gsc / ga4 / manual
    created_at timestamptz not null default now(),
    unique (site_id, metric_date, source)
);

create index if not exists idx_phare_metrics_site on public.phare_metrics (site_id, metric_date desc);

-- ---------------------------------------------------------------------
-- phare_backlinks : profil backlinks + opportunités
-- ---------------------------------------------------------------------
create table if not exists public.phare_backlinks (
    id uuid primary key default gen_random_uuid(),
    site_id uuid not null references public.phare_sites(id) on delete cascade,
    source_domain text not null,
    source_url text default '',
    target_url text default '',
    anchor text default '',
    domain_rating int,                      -- DR Ahrefs-like
    is_dofollow boolean default true,
    -- Type : "existing" (déjà lié) / "opportunity" (à démarcher)
    kind text not null default 'existing',
    opportunity_score int,                  -- 0-100, calculé par Chasseur Backlinks
    notes text default '',
    discovered_at timestamptz not null default now(),
    last_seen_at timestamptz
);

create index if not exists idx_phare_backlinks_site on public.phare_backlinks (site_id);
create index if not exists idx_phare_backlinks_kind on public.phare_backlinks (kind);

-- ---------------------------------------------------------------------
-- phare_content_briefs : briefs d'articles produits par le Rédacteur
-- ---------------------------------------------------------------------
create table if not exists public.phare_content_briefs (
    id uuid primary key default gen_random_uuid(),
    site_id uuid not null references public.phare_sites(id) on delete cascade,
    cluster text default '',                -- thème du cocon
    target_keyword text not null,
    secondary_keywords jsonb not null default '[]'::jsonb,
    intent text default 'informational',
    target_url text default '',             -- URL prévue (slug)
    title_proposed text default '',
    outline_md text default '',
    word_target int default 1200,
    -- Statut : "draft" → "approved" → "published"
    status text not null default 'draft',
    drafted_md text default '',             -- contenu rédigé
    action_id uuid references public.phare_actions(id) on delete set null,
    created_at timestamptz not null default now(),
    published_at timestamptz
);

create index if not exists idx_phare_content_site on public.phare_content_briefs (site_id);

-- =====================================================================
-- RLS : tout user authentifié voit/écrit (pattern Triskell Command)
-- =====================================================================
alter table public.phare_sites enable row level security;
alter table public.phare_audits enable row level security;
alter table public.phare_keywords enable row level security;
alter table public.phare_pages enable row level security;
alter table public.phare_actions enable row level security;
alter table public.phare_metrics enable row level security;
alter table public.phare_backlinks enable row level security;
alter table public.phare_content_briefs enable row level security;

do $$
declare
    t text;
begin
    foreach t in array array[
        'phare_sites','phare_audits','phare_keywords','phare_pages',
        'phare_actions','phare_metrics','phare_backlinks','phare_content_briefs'
    ]
    loop
        execute format('drop policy if exists %I_rw on public.%I;', t || '_authed', t);
        execute format(
            'create policy %I on public.%I for all using (auth.uid() is not null) with check (auth.uid() is not null);',
            t || '_authed', t
        );
    end loop;
end$$;

-- =====================================================================
-- Seed initial : les 13 sites Triskell connus (idempotent via unique domain)
-- =====================================================================
insert into public.phare_sites (name, domain, stack, priority, key_paths, notes) values
    ('Triskell Studio (apex)',  'triskell-studio.fr',          'astro', 90, '["/"]'::jsonb, 'Landing principale + Table Ronde'),
    ('Pack Électricien Pro',    'pack-elec.triskell-studio.fr','astro', 95, '["/", "/produit"]'::jsonb, 'CIBLE MVP. Tunnel Stripe rodé.'),
    ('Studio PDF',              'studio-pdf.triskell-studio.fr','astro',80, '["/"]'::jsonb, ''),
    ('Suite des Héros',         'productivite.triskell-studio.fr','astro',75, '["/"]'::jsonb, ''),
    ('Bobeez',                  'bobeez.triskell-studio.fr',   'astro', 70, '["/"]'::jsonb, ''),
    ('DéliNote',                'delinote.triskell-studio.fr', 'astro', 65, '["/"]'::jsonb, ''),
    ('Outils Bâtiment',         'outils.triskell-studio.fr',   'astro', 70, '["/"]'::jsonb, 'PWA, abonnement 9€/mois'),
    ('Eliks Studio',            'eliks.triskell-studio.fr',    'astro', 60, '["/"]'::jsonb, 'Service growth operator'),
    ('Sites agence',            'sites.triskell-studio.fr',    'astro', 55, '["/"]'::jsonb, 'Générateur de démo'),
    ('Obelisk',                 'obelisk.triskell-studio.fr',  'next',  85, '["/"]'::jsonb, ''),
    ('AlphaBeast',              'alphabeast.triskell-studio.fr','astro',60, '["/"]'::jsonb, ''),
    ('AlphaCast',               'alphacast.triskell-studio.fr','astro', 60, '["/"]'::jsonb, 'Beta ouverte'),
    ('AlphaPitch',              'alphapitch.triskell-studio.fr','astro',60, '["/"]'::jsonb, '')
on conflict (domain) do nothing;

-- shared_settings : config Le Phare (DataForSEO + GSC + LLM préférés)
insert into public.shared_settings (key, value) values
    ('phare_config', '{
        "dataforseo_login": "",
        "dataforseo_password": "",
        "gsc_credentials_path": "",
        "github_token": "",
        "netlify_token": "",
        "anthropic_model_default": "claude-sonnet-4-6",
        "anthropic_model_strategy": "claude-opus-4-7",
        "auto_merge_enabled": true,
        "voice_pack_default": "triskell",
        "schedule_audit_cron": "0 6 * * 1",
        "schedule_keywords_cron": "0 7 * * 1,4",
        "schedule_redaction_cron": "0 8 * * *",
        "schedule_strategy_cron": "0 9 1 * *"
    }'::jsonb)
on conflict (key) do nothing;



-- ===== 06b_phare_seed_real.sql =====

-- =====================================================================
-- Triskell Command — Migration 06b : Le Phare, mapping réel auto-détecté
-- =====================================================================
-- À exécuter APRÈS 06_phare.sql.
--
-- Ce fichier renseigne les vrais champs `repo_github`, `netlify_site_id`,
-- `stack` et `key_paths` pour les sites Triskell, détectés depuis les
-- `.git/config` et `.netlify/state.json` présents sur le poste de Jordan.
--
-- Auto-détection effectuée le 2026-05-06 (Le Phare livraison initiale).
-- =====================================================================

-- ---------------------------------------------------------------------
-- Apex / Table Ronde (catalogue principal — héberge AUSSI les sous-routes
-- AlphaBeast, AlphaCast, AlphaPitch, Obelisk, Teddy Mail, etc.)
-- ---------------------------------------------------------------------
update public.phare_sites set
    repo_github     = 'Jordan-Bourillot/triskell-site-officiel',
    netlify_site_id = 'a89769d6-bdba-49f7-b563-741e7a31be55',
    stack           = 'html',
    key_paths       = '["/"]'::jsonb,
    notes           = 'Site officiel triskell-studio.fr — vitrine + landings.'
where domain = 'triskell-studio.fr';

-- ---------------------------------------------------------------------
-- Pack Électricien Pro (CIBLE MVP — tunnel templateé)
-- ---------------------------------------------------------------------
update public.phare_sites set
    repo_github     = 'Jordan-Bourillot/pack-electricien-pro',
    netlify_site_id = '7c37740c-bf3d-4ce1-a4ee-d935ccf97f06',
    stack           = 'html',
    key_paths       = '["/", "/a-propos.html"]'::jsonb,
    notes           = 'CIBLE MVP. Tunnel Stripe rodé. ' ||
                      'Source : landing-pack/public/'
where domain = 'pack-elec.triskell-studio.fr';

-- ---------------------------------------------------------------------
-- Studio PDF
-- ---------------------------------------------------------------------
update public.phare_sites set
    repo_github     = 'Jordan-Bourillot/le-studio-pdf',
    netlify_site_id = '816f6588-75b2-4a97-bd38-56c964a214db',
    stack           = 'html',
    key_paths       = '["/"]'::jsonb,
    notes           = 'Source : landing/public/'
where domain = 'studio-pdf.triskell-studio.fr';

-- ---------------------------------------------------------------------
-- Suite des Héros (productivite.triskell-studio.fr)
-- ---------------------------------------------------------------------
update public.phare_sites set
    repo_github     = 'Jordan-Bourillot/suite-des-heros',
    netlify_site_id = 'f154d5c0-36fe-4430-b793-cfe15dfaf805',
    stack           = 'html',
    key_paths       = '["/"]'::jsonb,
    notes           = 'Source : landing-pack/public/'
where domain = 'productivite.triskell-studio.fr';

-- ---------------------------------------------------------------------
-- Bobeez
-- ---------------------------------------------------------------------
update public.phare_sites set
    repo_github     = 'Jordan-Bourillot/bobeez',
    netlify_site_id = '6885b3cd-daef-444c-ad42-2a8b7765f823',
    stack           = 'html',
    key_paths       = '["/"]'::jsonb,
    notes           = 'Source : landing/public/'
where domain = 'bobeez.triskell-studio.fr';

-- ---------------------------------------------------------------------
-- DéliNote
-- ---------------------------------------------------------------------
update public.phare_sites set
    repo_github     = 'Jordan-Bourillot/delinote',
    netlify_site_id = '9667bf9b-cd93-4e05-adcd-9725433f567a',
    stack           = 'html',
    key_paths       = '["/"]'::jsonb,
    notes           = 'Source : landing/public/'
where domain = 'delinote.triskell-studio.fr';

-- ---------------------------------------------------------------------
-- Outils Bâtiment (PWA, abonnement 9€/mois)
-- ---------------------------------------------------------------------
update public.phare_sites set
    repo_github     = '',                -- pas de .git/config détecté localement
    netlify_site_id = 'd48c059f-b03e-4f9d-8611-c46c7a040b8a',
    stack           = 'html',
    key_paths       = '["/"]'::jsonb,
    notes           = 'PWA, dossier `Triskell 3 - Outils Batiment/`. ' ||
                      'À renseigner repo_github si versionné sur GitHub.'
where domain = 'outils.triskell-studio.fr';

-- ---------------------------------------------------------------------
-- Eliks Studio (service growth operator)
-- ---------------------------------------------------------------------
update public.phare_sites set
    repo_github     = '',                -- pas de .git/config détecté
    netlify_site_id = 'f83a6764-12ab-4330-8cf5-b2949f24ec6a',
    stack           = 'html',
    key_paths       = '["/"]'::jsonb,
    notes           = 'Site service. À renseigner repo_github si applicable.'
where domain = 'eliks.triskell-studio.fr';

-- ---------------------------------------------------------------------
-- Obelisk (anciennement Le Dénicheur — repo "trove")
-- ---------------------------------------------------------------------
update public.phare_sites set
    repo_github     = 'Jordan-Bourillot/trove',
    netlify_site_id = 'dd180e21-519a-41b3-a6f5-21c2e6a30633',
    stack           = 'html',
    key_paths       = '["/"]'::jsonb,
    notes           = 'Repo "trove" (paths inchangés malgré rebrand Obelisk). ' ||
                      'Source : landing/public/'
where domain = 'obelisk.triskell-studio.fr';

-- ---------------------------------------------------------------------
-- Sites agence (sites.triskell-studio.fr — générateur de démo)
-- ---------------------------------------------------------------------
update public.phare_sites set
    repo_github     = '',
    netlify_site_id = '',                -- à compléter
    stack           = 'html',
    key_paths       = '["/"]'::jsonb,
    notes           = 'Générateur de démo personnalisée. À renseigner ' ||
                      'site_id Netlify et repo_github.'
where domain = 'sites.triskell-studio.fr';

-- ---------------------------------------------------------------------
-- AlphaBeast / AlphaCast / AlphaPitch
-- ---------------------------------------------------------------------
-- Découverte 2026-05-06 : ces 3 produits ne sont PAS sur des sous-domaines
-- séparés. Ils sont servis comme sous-routes du Lanceur (Table Ronde),
-- depuis `Triskell 0 - Lanceur/landing/{alphabeast,alphacast,alphapitch}/`.
--
-- → On désactive les entrées sous-domaine séparées (le Phare ne les
--   surveille pas) et on les couvre via le site `triskell-studio.fr` en
--   ajoutant leurs sous-routes aux `key_paths`.
--
-- Si plus tard Jordan crée de vrais sous-domaines, il suffira de :
--   update phare_sites set is_active = true,
--                          netlify_site_id = '...',
--                          repo_github = '...'
--   where domain = 'alphabeast.triskell-studio.fr';

update public.phare_sites set
    is_active = false,
    notes     = 'Servi en sous-route du Lanceur (Table Ronde) — pas de ' ||
                'sous-domaine séparé au 2026-05-06. Réactiver si DNS dédié.'
where domain in (
    'alphabeast.triskell-studio.fr',
    'alphacast.triskell-studio.fr',
    'alphapitch.triskell-studio.fr'
);

-- ---------------------------------------------------------------------
-- Lanceur Table Ronde — surveille la home + les pages produits
-- ---------------------------------------------------------------------
insert into public.phare_sites (
    name, domain, repo_github, netlify_site_id, stack, priority,
    key_paths, notes
) values (
    'Table Ronde (Lanceur catalogue)',
    'lanceur.triskell-studio.fr',
    'Jordan-Bourillot/triskell-table-ronde',
    'f21074d1-9cf1-46ca-93bd-88322f7ee4f4',
    'html', 88,
    '["/", "/alphabeast/", "/alphacast/", "/alphapitch/", "/bobeez/", "/delinote/", "/le-denicheur/", "/outils-pro/", "/pack-electricien-pro/", "/pirate-life-mail/", "/studio-pdf/", "/suite-des-heros/"]'::jsonb,
    'Catalogue principal qui héberge AUSSI les pages produit AlphaBeast, ' ||
    'AlphaCast, AlphaPitch en sous-routes. Vérifier le domaine réel.'
)
on conflict (domain) do update set
    repo_github     = excluded.repo_github,
    netlify_site_id = excluded.netlify_site_id,
    stack           = excluded.stack,
    priority        = excluded.priority,
    key_paths       = excluded.key_paths,
    notes           = excluded.notes,
    is_active       = true;

-- =====================================================================
-- Récap : ce qui reste à compléter manuellement par Jordan
-- =====================================================================
-- 1. `outils.triskell-studio.fr` : repo_github (si versionné)
-- 2. `eliks.triskell-studio.fr` : repo_github
-- 3. `sites.triskell-studio.fr` : repo_github + netlify_site_id
-- 4. Vérifier si `lanceur.triskell-studio.fr` est bien le bon hostname,
--    sinon ajuster (peut être l'apex `triskell-studio.fr` directement
--    selon la conf DNS Netlify)
-- =====================================================================



-- ===== 06c_phare_advanced.sql =====

-- =====================================================================
-- Triskell Command — Migration 06c : Le Phare, fonctions avancées
-- =====================================================================
-- À exécuter APRÈS 06_phare.sql et 06b_phare_seed_real.sql.
--
-- Ajoute les tables nécessaires aux fonctions avancées :
--   - phare_competitors          : concurrents directs par site
--   - phare_competitor_positions : positions des concurrents sur tes KW
--   - phare_serp_features        : featured snippets & PAA capturables
--   - phare_geo_mentions         : mentions dans LLM (ChatGPT/Perplexity)
--   - phare_image_audits         : alts manquants, formats, tailles
--   - phare_cannibalization      : 2+ pages sur même KW
--   - phare_zombies              : pages sans trafic ni backlink
--   - phare_content_refresh      : articles à rafraîchir
--   - phare_rollback_watch       : surveillance post-merge (14 jours)
--   - phare_sitemap_pings        : log des pings IndexNow
-- =====================================================================

create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------------
-- phare_competitors : concurrents directs déclarés ou détectés
-- ---------------------------------------------------------------------
create table if not exists public.phare_competitors (
    id uuid primary key default gen_random_uuid(),
    site_id uuid not null references public.phare_sites(id) on delete cascade,
    competitor_domain text not null,
    relevance_score int default 50,         -- 0-100
    discovered_via text default 'manual',   -- manual / serp_overlap / llm
    notes text default '',
    is_active boolean default true,
    created_at timestamptz not null default now(),
    unique (site_id, competitor_domain)
);
create index if not exists idx_phare_competitors_site on public.phare_competitors (site_id);

-- ---------------------------------------------------------------------
-- phare_competitor_positions : snapshot positions concurrents par KW
-- ---------------------------------------------------------------------
create table if not exists public.phare_competitor_positions (
    id uuid primary key default gen_random_uuid(),
    site_id uuid not null references public.phare_sites(id) on delete cascade,
    competitor_domain text not null,
    keyword text not null,
    position int,
    url text default '',
    snapshot_date date not null default current_date,
    created_at timestamptz not null default now()
);
create index if not exists idx_phare_compos_site_kw on public.phare_competitor_positions (site_id, keyword, snapshot_date desc);

-- ---------------------------------------------------------------------
-- phare_serp_features : featured snippets et PAA détectés en SERP
-- ---------------------------------------------------------------------
create table if not exists public.phare_serp_features (
    id uuid primary key default gen_random_uuid(),
    site_id uuid not null references public.phare_sites(id) on delete cascade,
    keyword text not null,
    feature_type text not null,             -- featured_snippet / paa / video / image_pack
    current_owner_domain text default '',
    current_owner_url text default '',
    captured_format text default '',        -- paragraph / list / table / faq
    we_can_capture boolean default false,
    proposed_content_md text default '',
    detected_at timestamptz not null default now(),
    action_id uuid references public.phare_actions(id) on delete set null
);
create index if not exists idx_phare_serp_site on public.phare_serp_features (site_id, feature_type);

-- ---------------------------------------------------------------------
-- phare_geo_mentions : suivi de la présence dans les LLM (AI Overview etc.)
-- ---------------------------------------------------------------------
create table if not exists public.phare_geo_mentions (
    id uuid primary key default gen_random_uuid(),
    site_id uuid not null references public.phare_sites(id) on delete cascade,
    surface text not null,                  -- chatgpt / perplexity / claude / google_ai_overview
    query text not null,
    mentioned boolean not null default false,
    mention_url text default '',
    mention_excerpt text default '',
    competitors_mentioned jsonb not null default '[]'::jsonb,
    checked_at timestamptz not null default now(),
    raw_response text default ''
);
create index if not exists idx_phare_geo_site on public.phare_geo_mentions (site_id, surface, checked_at desc);

-- ---------------------------------------------------------------------
-- phare_image_audits : audit images d'une page (alts, format, taille)
-- ---------------------------------------------------------------------
create table if not exists public.phare_image_audits (
    id uuid primary key default gen_random_uuid(),
    site_id uuid not null references public.phare_sites(id) on delete cascade,
    page_path text not null,
    image_src text not null,
    has_alt boolean default false,
    alt_text text default '',
    proposed_alt text default '',
    format text default '',                 -- jpg / png / webp / avif / svg
    size_kb int,
    is_lazy boolean default false,
    has_srcset boolean default false,
    issues jsonb not null default '[]'::jsonb,
    checked_at timestamptz not null default now()
);
create index if not exists idx_phare_imgaudit_site on public.phare_image_audits (site_id, page_path);

-- ---------------------------------------------------------------------
-- phare_cannibalization : plusieurs pages qui rankent sur le même KW
-- ---------------------------------------------------------------------
create table if not exists public.phare_cannibalization (
    id uuid primary key default gen_random_uuid(),
    site_id uuid not null references public.phare_sites(id) on delete cascade,
    keyword text not null,
    competing_paths jsonb not null default '[]'::jsonb,   -- [{path, position, clicks}]
    severity int default 50,                              -- 0-100
    proposed_action text default '',                      -- merge / redirect_301 / differentiate
    proposed_canonical_path text default '',
    detected_at timestamptz not null default now(),
    resolved_at timestamptz,
    action_id uuid references public.phare_actions(id) on delete set null
);
create index if not exists idx_phare_cannib_site on public.phare_cannibalization (site_id);

-- ---------------------------------------------------------------------
-- phare_zombies : pages sans trafic, backlink ni conversion sur 6 mois
-- ---------------------------------------------------------------------
create table if not exists public.phare_zombies (
    id uuid primary key default gen_random_uuid(),
    site_id uuid not null references public.phare_sites(id) on delete cascade,
    page_path text not null,
    last_organic_click_at date,
    backlinks_count int default 0,
    word_count int default 0,
    proposed_action text default '',         -- boost / redirect / delete / noindex
    proposed_target_path text default '',    -- si redirect
    detected_at timestamptz not null default now(),
    resolved_at timestamptz,
    unique (site_id, page_path)
);
create index if not exists idx_phare_zombies_site on public.phare_zombies (site_id);

-- ---------------------------------------------------------------------
-- phare_content_refresh : articles à rafraîchir (perdent du terrain)
-- ---------------------------------------------------------------------
create table if not exists public.phare_content_refresh (
    id uuid primary key default gen_random_uuid(),
    site_id uuid not null references public.phare_sites(id) on delete cascade,
    page_path text not null,
    age_months int,
    clicks_now int default 0,
    clicks_peak int default 0,
    decline_pct numeric,
    proposed_changes_md text default '',
    refresh_score int,                       -- 0-100, plus haut = plus prioritaire
    detected_at timestamptz not null default now(),
    action_id uuid references public.phare_actions(id) on delete set null
);
create index if not exists idx_phare_refresh_site on public.phare_content_refresh (site_id);

-- ---------------------------------------------------------------------
-- phare_rollback_watch : surveille les PRs mergées pendant 14 jours
-- ---------------------------------------------------------------------
create table if not exists public.phare_rollback_watch (
    id uuid primary key default gen_random_uuid(),
    site_id uuid not null references public.phare_sites(id) on delete cascade,
    action_id uuid not null references public.phare_actions(id) on delete cascade,
    merged_at timestamptz not null,
    baseline_clicks_7d int default 0,
    measured_clicks_7d int,
    measured_at timestamptz,
    delta_pct numeric,
    decision text default 'watching',        -- watching / kept / rolled_back
    rollback_pr_url text default '',
    finalized_at timestamptz
);
create index if not exists idx_phare_rollback_site on public.phare_rollback_watch (site_id, decision);

-- ---------------------------------------------------------------------
-- phare_sitemap_pings : journal des pings IndexNow + sitemap.xml
-- ---------------------------------------------------------------------
create table if not exists public.phare_sitemap_pings (
    id uuid primary key default gen_random_uuid(),
    site_id uuid not null references public.phare_sites(id) on delete cascade,
    target text not null,                    -- bing / yandex / google
    urls_pinged jsonb not null default '[]'::jsonb,
    response_code int,
    response_body text default '',
    pinged_at timestamptz not null default now()
);
create index if not exists idx_phare_pings_site on public.phare_sitemap_pings (site_id, pinged_at desc);

-- =====================================================================
-- RLS : tout user authentifié voit/écrit (cohérent avec 06_phare.sql)
-- =====================================================================
alter table public.phare_competitors enable row level security;
alter table public.phare_competitor_positions enable row level security;
alter table public.phare_serp_features enable row level security;
alter table public.phare_geo_mentions enable row level security;
alter table public.phare_image_audits enable row level security;
alter table public.phare_cannibalization enable row level security;
alter table public.phare_zombies enable row level security;
alter table public.phare_content_refresh enable row level security;
alter table public.phare_rollback_watch enable row level security;
alter table public.phare_sitemap_pings enable row level security;

do $$
declare
    t text;
begin
    foreach t in array array[
        'phare_competitors', 'phare_competitor_positions',
        'phare_serp_features', 'phare_geo_mentions',
        'phare_image_audits', 'phare_cannibalization',
        'phare_zombies', 'phare_content_refresh',
        'phare_rollback_watch', 'phare_sitemap_pings'
    ]
    loop
        execute format('drop policy if exists %I_authed on public.%I;', t, t);
        execute format(
            'create policy %I on public.%I for all using (auth.uid() is not null) with check (auth.uid() is not null);',
            t || '_authed', t
        );
    end loop;
end$$;

-- =====================================================================
-- Étend phare_config avec les options des fonctions avancées
-- =====================================================================
update public.shared_settings
set value = value || jsonb_build_object(
    'indexnow_key',                '',
    'geo_check_surfaces',          '["chatgpt", "perplexity", "google_ai_overview"]'::jsonb,
    'rollback_watch_window_days',  14,
    'rollback_threshold_pct',      -15,
    'zombie_no_click_months',      6,
    'refresh_min_age_months',      12,
    'refresh_decline_threshold',   -25,
    'cannibalization_min_pages',   2,
    'image_max_size_kb',           200,
    'preferred_image_format',      'webp',
    'auto_apply_schema',           true,
    'auto_apply_image_alts',       true
)
where key = 'phare_config';



-- ===== 06d_phare_pro.sql =====

-- =====================================================================
-- Triskell Command — Migration 06d : Le Phare, modules pro (v0.6)
-- =====================================================================
-- À exécuter APRÈS 06_phare.sql, 06b_phare_seed_real.sql, 06c_phare_advanced.sql.
--
-- Ajoute les tables nécessaires aux modules pro :
--   - phare_outreach_campaigns / phare_outreach_messages
--   - phare_ab_tests / phare_ab_measurements
--   - phare_brand_mentions
--   - phare_gbp_status / phare_reviews
--   - phare_programmatic_templates / phare_programmatic_pages
--   - phare_cro_insights
--   - phare_algo_events
-- =====================================================================

create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------------
-- Outreach backlinks
-- ---------------------------------------------------------------------
create table if not exists public.phare_outreach_campaigns (
    id uuid primary key default gen_random_uuid(),
    site_id uuid not null references public.phare_sites(id) on delete cascade,
    name text not null,
    kind text not null,           -- broken_link / unlinked_mention / gap_concurrent / haro
    template_subject text not null,
    template_body text not null,  -- avec {variables}
    status text not null default 'active',
    created_at timestamptz not null default now()
);
create index if not exists idx_phare_outreach_camp_site on public.phare_outreach_campaigns (site_id);

create table if not exists public.phare_outreach_messages (
    id uuid primary key default gen_random_uuid(),
    campaign_id uuid not null references public.phare_outreach_campaigns(id) on delete cascade,
    site_id uuid not null references public.phare_sites(id) on delete cascade,
    target_domain text not null,
    target_email text default '',
    target_contact_name text default '',
    proposed_subject text not null,
    proposed_body text not null,
    variables jsonb not null default '{}'::jsonb,
    status text not null default 'draft',  -- draft / sent / replied_pos / replied_neg / no_reply
    sent_at timestamptz,
    reply_at timestamptz,
    reply_excerpt text default '',
    follow_up_count int default 0,
    next_follow_up_at timestamptz,
    created_at timestamptz not null default now()
);
create index if not exists idx_phare_outreach_msg_status on public.phare_outreach_messages (status);
create index if not exists idx_phare_outreach_msg_site on public.phare_outreach_messages (site_id);

-- ---------------------------------------------------------------------
-- A/B testing SEO
-- ---------------------------------------------------------------------
create table if not exists public.phare_ab_tests (
    id uuid primary key default gen_random_uuid(),
    site_id uuid not null references public.phare_sites(id) on delete cascade,
    name text not null,
    field_tested text not null,   -- title / meta_description / h1
    variant_a_value text not null,
    variant_b_value text not null,
    paths_lot_a jsonb not null default '[]'::jsonb,
    paths_lot_b jsonb not null default '[]'::jsonb,
    started_at timestamptz not null default now(),
    duration_days int default 21,
    ended_at timestamptz,
    winner text default '',       -- a / b / none
    final_decision_md text default '',
    status text not null default 'running'  -- running / done / aborted
);
create index if not exists idx_phare_ab_site on public.phare_ab_tests (site_id);

create table if not exists public.phare_ab_measurements (
    id uuid primary key default gen_random_uuid(),
    test_id uuid not null references public.phare_ab_tests(id) on delete cascade,
    measured_date date not null,
    lot_a_clicks int default 0,
    lot_a_impressions int default 0,
    lot_a_ctr numeric,
    lot_b_clicks int default 0,
    lot_b_impressions int default 0,
    lot_b_ctr numeric,
    created_at timestamptz not null default now(),
    unique (test_id, measured_date)
);

-- ---------------------------------------------------------------------
-- Brand monitoring
-- ---------------------------------------------------------------------
create table if not exists public.phare_brand_mentions (
    id uuid primary key default gen_random_uuid(),
    site_id uuid not null references public.phare_sites(id) on delete cascade,
    brand_term text not null,            -- "Triskell Studio" / "Pack Électricien Pro" / etc.
    source_url text not null,
    source_domain text not null,
    excerpt text default '',
    has_link boolean default false,
    sentiment text default 'neutral',    -- positive / neutral / negative
    discovered_at timestamptz not null default now(),
    action_id uuid references public.phare_actions(id) on delete set null,
    unique (site_id, source_url, brand_term)
);
create index if not exists idx_phare_brand_site on public.phare_brand_mentions (site_id, discovered_at desc);

-- ---------------------------------------------------------------------
-- Google Business Profile (Local SEO)
-- ---------------------------------------------------------------------
create table if not exists public.phare_gbp_status (
    id uuid primary key default gen_random_uuid(),
    site_id uuid not null references public.phare_sites(id) on delete cascade,
    place_id text not null,
    name text not null,
    address text default '',
    phone text default '',
    website text default '',
    rating numeric,
    reviews_count int default 0,
    photos_count int default 0,
    posts_last_30d int default 0,
    completeness_score int,             -- 0-100 (champs remplis / total)
    suggestions jsonb not null default '[]'::jsonb,
    checked_at timestamptz not null default now()
);
create index if not exists idx_phare_gbp_site on public.phare_gbp_status (site_id);

create table if not exists public.phare_reviews (
    id uuid primary key default gen_random_uuid(),
    site_id uuid not null references public.phare_sites(id) on delete cascade,
    place_id text not null,
    review_id text unique not null,
    author_name text default '',
    rating int,
    text_excerpt text default '',
    has_response boolean default false,
    proposed_response_md text default '',
    posted_at timestamptz,
    discovered_at timestamptz not null default now()
);
create index if not exists idx_phare_reviews_site on public.phare_reviews (site_id);

-- ---------------------------------------------------------------------
-- Programmatic SEO
-- ---------------------------------------------------------------------
create table if not exists public.phare_programmatic_templates (
    id uuid primary key default gen_random_uuid(),
    site_id uuid not null references public.phare_sites(id) on delete cascade,
    name text not null,                  -- "Tarif électricien par ville"
    url_pattern text not null,           -- /tarif-{slug_ville}.html
    title_pattern text not null,
    meta_pattern text not null,
    h1_pattern text not null,
    body_outline_md text not null,
    variables_source text not null,      -- "csv" / "supabase_table" / "external_api"
    variables_payload jsonb not null default '{}'::jsonb,
    quality_min_words int default 600,
    status text default 'draft',         -- draft / generating / done
    created_at timestamptz not null default now()
);
create index if not exists idx_phare_progtmpl_site on public.phare_programmatic_templates (site_id);

create table if not exists public.phare_programmatic_pages (
    id uuid primary key default gen_random_uuid(),
    template_id uuid not null references public.phare_programmatic_templates(id) on delete cascade,
    site_id uuid not null references public.phare_sites(id) on delete cascade,
    variables jsonb not null default '{}'::jsonb,
    generated_url text not null,
    generated_title text default '',
    generated_meta text default '',
    generated_body_md text default '',
    word_count int default 0,
    quality_score int,
    status text default 'draft',         -- draft / approved / pushed / live
    pushed_action_id uuid references public.phare_actions(id) on delete set null,
    created_at timestamptz not null default now()
);
create index if not exists idx_phare_progpages_site on public.phare_programmatic_pages (site_id, status);

-- ---------------------------------------------------------------------
-- CRO (Microsoft Clarity)
-- ---------------------------------------------------------------------
create table if not exists public.phare_cro_insights (
    id uuid primary key default gen_random_uuid(),
    site_id uuid not null references public.phare_sites(id) on delete cascade,
    page_path text not null,
    sessions int default 0,
    rage_clicks int default 0,
    dead_clicks int default 0,
    quick_backs int default 0,
    scroll_depth_avg numeric,
    conversion_rate numeric,
    issue_summary_md text default '',
    proposed_fixes_md text default '',
    detected_at timestamptz not null default now()
);
create index if not exists idx_phare_cro_site on public.phare_cro_insights (site_id);

-- ---------------------------------------------------------------------
-- Algo watch
-- ---------------------------------------------------------------------
create table if not exists public.phare_algo_events (
    id uuid primary key default gen_random_uuid(),
    source text not null,                -- search_engine_land / search_engine_roundtable / mozcast / semrush_sensor / google_search_liaison
    event_date date not null,
    headline text not null,
    summary_md text default '',
    severity text default 'info',        -- info / warning / critical
    source_url text default '',
    detected_at timestamptz not null default now(),
    acknowledged boolean default false
);
create index if not exists idx_phare_algo_date on public.phare_algo_events (event_date desc);

-- =====================================================================
-- RLS
-- =====================================================================
do $$
declare
    t text;
begin
    foreach t in array array[
        'phare_outreach_campaigns', 'phare_outreach_messages',
        'phare_ab_tests', 'phare_ab_measurements',
        'phare_brand_mentions',
        'phare_gbp_status', 'phare_reviews',
        'phare_programmatic_templates', 'phare_programmatic_pages',
        'phare_cro_insights',
        'phare_algo_events'
    ]
    loop
        execute format('alter table public.%I enable row level security;', t);
        execute format('drop policy if exists %I_authed on public.%I;', t, t);
        execute format(
            'create policy %I on public.%I for all using (auth.uid() is not null) with check (auth.uid() is not null);',
            t || '_authed', t
        );
    end loop;
end$$;

-- =====================================================================
-- Étend phare_config avec les options pro
-- =====================================================================
update public.shared_settings
set value = value || jsonb_build_object(
    'outreach_smtp_from',           '',
    'outreach_max_per_day',         10,
    'outreach_follow_up_days',      '[7, 14]'::jsonb,
    'outreach_auto_send',           false,
    'ab_test_min_duration_days',    14,
    'ab_test_min_impressions',      500,
    'brand_monitor_terms',          '["Triskell Studio", "Pack Électricien Pro", "Studio PDF", "Bobeez", "DéliNote", "AlphaBeast", "AlphaCast", "AlphaPitch", "Obelisk"]'::jsonb,
    'brand_monitor_search_engine',  'google',
    'gbp_place_ids',                '{}'::jsonb,
    'clarity_project_id',           '',
    'clarity_api_token',            '',
    'algo_watch_sources',           '["search_engine_land", "google_search_liaison", "mozcast"]'::jsonb,
    'bulletin_pdf_logo_path',       ''
)
where key = 'phare_config';



-- =====================================================================

-- FIN — toutes les tables sont créées, RLS activée, seed appliqué.

-- Vérification : dans Database → Tables, tu dois voir :

--   - users, shared_settings, prospects, email_history, prospect_drafts

--   - templates, convoy_campaigns, convoy_drafts, send_log

--   - client_projects, messages, email_events, typing_status

--   - phare_sites (avec 14 lignes), phare_audits, phare_keywords,

--     phare_pages, phare_actions, phare_metrics, phare_backlinks,

--     phare_content_briefs, + tables avancées des modules v0.5/v0.6

-- =====================================================================
