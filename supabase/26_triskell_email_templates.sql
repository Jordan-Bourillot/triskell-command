-- Migration 26 : table unifiée des modèles de mails (multi-produit, multi-expéditeur).
--
-- Étend l'ancienne logique `lagriffe_mail_templates` (migration 22) qui ne
-- gérait que les 4 mails Lagriffe + clé unique `template_key`. La nouvelle
-- table est volontairement plus généraliste : clé composite (product, key)
-- pour qu'un même `key` puisse exister sur plusieurs produits (ex. tous les
-- produits ont un `welcome`), et un champ libre `from_address` pour grouper
-- l'UI par adresse mail expéditrice plutôt que par produit.
--
-- Produits actuellement reconnus côté UI (cf. mail_templates.js → KNOWN) :
--   lagriffe, wow, rankus, phare, reply, drip, post_sale,
--   delivery_pack_elec, delivery_studio_pdf, delivery_obelisk,
--   internal, billing, shared
--
-- Pas de check constraint sur `product` : on veut pouvoir ajouter un nouveau
-- produit côté code sans migration SQL. La discipline est garantie par le
-- catalogue KNOWN dans le JS et la liste blanche `ALLOWED` dans
-- lagriffe/repo.py::mail_templates_save.
--
-- Lecture : par les Netlify functions (lookup par product+key, fallback
-- hardcodé si absent) et par Triskell Command → page Modèles mails.

create table if not exists public.triskell_email_templates (
  id            uuid primary key default gen_random_uuid(),
  product       text not null,
  key           text not null,
  from_address  text default '',
  from_name     text default '',
  subject       text not null default '',
  body_html     text default '',
  body_text     text default '',
  description   text default '',
  placeholders  jsonb default '[]'::jsonb,
  enabled       boolean default true,
  updated_at    timestamptz default now(),
  updated_by    text default '',
  unique (product, key)
);

create index if not exists idx_triskell_email_templates_product
  on public.triskell_email_templates (product);
create index if not exists idx_triskell_email_templates_from_address
  on public.triskell_email_templates (from_address);

-- RLS : authentifié uniquement
alter table public.triskell_email_templates enable row level security;

drop policy if exists "tet_read_authenticated" on public.triskell_email_templates;
create policy "tet_read_authenticated"
  on public.triskell_email_templates
  for select to authenticated using (true);

drop policy if exists "tet_write_authenticated" on public.triskell_email_templates;
create policy "tet_write_authenticated"
  on public.triskell_email_templates
  for all to authenticated using (true) with check (true);

comment on table public.triskell_email_templates is
  'Modèles de mails éditables depuis Triskell Command, groupés par (product, key). '
  'Les Netlify functions et runners Python lisent ici en priorité, avec fallback '
  'sur leurs valeurs codées en dur si la ligne est absente ou enabled=false.';
