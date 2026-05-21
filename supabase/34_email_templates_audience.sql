-- Migration 34 : sous-catégorie « audience » pour les modèles de prospection.
--
-- Contexte : la catégorie 'prospection' (migration 28) regroupe maintenant
-- deux types de mails très différents :
--   - audience='creator' : démarchage de créateurs / influenceurs pour
--     partenariats, codes promo, commissions, revenue share. Cible historique.
--   - audience='pro'     : démarchage direct de PME/commerces locaux pour
--     leur vendre un site/service. Pitch radicalement différent (pas de
--     « parle de moi à ton audience » mais « voici ce que je fais pour vous »).
--
-- La distinction se fait via une nouvelle colonne `audience` (nullable côté
-- transactionnel, défaut 'creator' côté prospection pour ne rien casser).
-- L'UI Modèles Mails affichera un toggle Créateurs | Pros au sein de la
-- catégorie prospection ; le composeur de campagne filtrera par audience
-- avant de proposer un template.

alter table public.triskell_email_templates
  add column if not exists audience text default null;

-- Migre les 5 templates existants Pixel Pros (catégorie prospection) en
-- audience='creator', car ils ont tous été rédigés pour des créateurs.
update public.triskell_email_templates
   set audience = 'creator'
 where category = 'prospection'
   and (audience is null or audience = '');

create index if not exists idx_triskell_email_templates_audience
  on public.triskell_email_templates (audience)
  where audience is not null;

comment on column public.triskell_email_templates.audience is
  'Pour les templates de catégorie ''prospection'' uniquement : ''creator'' '
  '(démarchage influenceur, ton chaleureux, propositions de partenariat) '
  'ou ''pro'' (démarchage B2B local, ton pro, vente directe). NULL pour '
  'les templates transactionnels (non applicable).';
