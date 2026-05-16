-- Migration 22 : éditeur de mails Lagriffe depuis Triskell Command web.
--
-- Stocke les 4 templates de mail envoyés aux clients pendant le pipeline
-- de fabrication d'un site Lagriffe :
--   - brief_received     : confirmation après soumission du brief
--   - preview_ready      : maquette générée, prête à personnaliser/payer
--   - payment_confirmed  : Stripe a confirmé le paiement
--   - site_delivered     : site final mis en ligne (livraison)
--
-- Les Netlify functions lisent ce template via service_role et tombent
-- en fallback sur les valeurs hardcodées si Supabase est indisponible
-- (résilience).
--
-- L'édition se fait depuis Triskell Command → Lagriffe → onglet Pipeline,
-- en cliquant sur l'icône ✉️ d'une étape qui envoie un mail.

create table if not exists public.lagriffe_mail_templates (
  id          uuid primary key default gen_random_uuid(),
  -- Clé logique de l'étape qui envoie ce mail. Une seule ligne par clé.
  template_key text unique not null check (template_key in (
    'brief_received',
    'preview_ready',
    'payment_confirmed',
    'site_delivered'
  )),
  -- Sujet du mail (peut contenir des emoji et {first_name} comme placeholder)
  subject      text not null,
  -- Aperçu en boîte de réception (texte plat, max ~120 chars)
  preheader    text default '',
  -- Petit badge en haut du mail (ex: "Configuration reçue")
  eyebrow      text default '',
  -- Titre principal du mail (peut contenir HTML simple : <br>)
  -- Variables disponibles : {first_name}
  title        text not null,
  -- Bouton d'action (label + URL). Vides = pas de bouton.
  cta_label    text default '',
  -- URL absolue ou placeholder ({customize_url}, {site_url}, etc.)
  cta_url      text default '',
  -- Méta édition
  updated_at   timestamptz default now(),
  updated_by   text default ''
);

-- Index pour lookup rapide par clé
create unique index if not exists idx_lagriffe_mail_templates_key
  on public.lagriffe_mail_templates(template_key);

-- RLS : seul un user authentifié peut lire/modifier
alter table public.lagriffe_mail_templates enable row level security;

drop policy if exists "templates_read_authenticated" on public.lagriffe_mail_templates;
create policy "templates_read_authenticated"
  on public.lagriffe_mail_templates
  for select to authenticated using (true);

drop policy if exists "templates_write_authenticated" on public.lagriffe_mail_templates;
create policy "templates_write_authenticated"
  on public.lagriffe_mail_templates
  for all to authenticated using (true) with check (true);

-- Seed initial : valeurs courantes extraites des Netlify functions Lagriffe
-- Les variables {first_name}, {customize_url}, {site_url}, {invoice_number}
-- sont remplacées au moment de l'envoi par chaque function.
insert into public.lagriffe_mail_templates (template_key, subject, preheader, eyebrow, title, cta_label, cta_url)
values
  (
    'brief_received',
    '📥 On a bien reçu votre demande, {first_name}',
    'On commence la fabrication de votre maquette dans les heures qui viennent.',
    'Configuration reçue',
    'Bien reçu,<br>{first_name}.',
    '',
    ''
  ),
  (
    'preview_ready',
    'Votre maquette Lagriffe est prête, {first_name}',
    'Votre maquette est en ligne. Cliquez pour la personnaliser et finaliser votre site.',
    'Aperçu de votre site',
    'Votre maquette est prête,<br>{first_name}.',
    'Personnaliser mon site →',
    '{customize_url}'
  ),
  (
    'payment_confirmed',
    'Bienvenue chez Lagriffe, {first_name}',
    'Paiement reçu. Votre site est en cours de fabrication finale.',
    'Paiement validé',
    'Bienvenue chez Lagriffe,<br>{first_name}.',
    '',
    ''
  ),
  (
    'site_delivered',
    'Votre site Lagriffe est en ligne, {first_name}',
    'Toutes vos pages, vos contenus, vos fonctionnalités. C''est en ligne.',
    'Mise en ligne',
    'Votre site est en ligne,<br>{first_name}.',
    'Voir mon site →',
    '{site_url}'
  )
on conflict (template_key) do nothing;

comment on table public.lagriffe_mail_templates is
  'Templates des 4 mails envoyés au client pendant le pipeline Lagriffe. ' ||
  'Édités depuis Triskell Command, lus par les Netlify functions au moment de l''envoi.';
