-- Migration 28 : ajout d'une catégorie sur les modèles de mails.
--
-- Contexte : la table `triskell_email_templates` (migration 26) ne contenait
-- que des mails *transactionnels* (confirmation de brief, paiement reçu,
-- livraison, relances post-vente, factures…), groupés à l'affichage par
-- adresse mail expéditrice. On veut maintenant pouvoir aussi y ranger des
-- modèles de *prospection* (mails de démarchage envoyés à la main, ex. aux
-- créateurs/influenceurs pour Pixel Pros), avec une organisation par produit.
--
-- Choix d'implémentation :
--   - une colonne `category` (text, default 'transactionnel') sépare les deux
--     univers ; la valeur 'prospection' est utilisée pour les mails libres.
--   - une colonne `label` (text, optionnelle) sert de titre lisible pour les
--     templates de prospection (les transactionnels gardent leur label dans
--     le catalogue KNOWN côté JS, indexé par (product, key)).
--   - les lignes existantes sont marquées 'transactionnel' explicitement.
--
-- Aucune contrainte CHECK sur `category` pour rester souple ; la discipline
-- est garantie côté UI (toggle Transactionnel | Prospection) et côté backend
-- (whitelist dans lagriffe/repo.py::mail_templates_save).

alter table public.triskell_email_templates
  add column if not exists category text not null default 'transactionnel';

alter table public.triskell_email_templates
  add column if not exists label text default '';

-- Marque explicitement les lignes existantes comme transactionnelles
-- (sécurité : si le default change un jour, les anciennes lignes restent
-- correctement catégorisées).
update public.triskell_email_templates
   set category = 'transactionnel'
 where category is null or category = '';

create index if not exists idx_triskell_email_templates_category
  on public.triskell_email_templates (category);

comment on column public.triskell_email_templates.category is
  'Catégorie du modèle : ''transactionnel'' (mails auto envoyés par le système, '
  'groupés à l''UI par adresse expéditrice) ou ''prospection'' (mails de démarchage '
  'rédigés à la main, groupés à l''UI par produit du catalogue).';

comment on column public.triskell_email_templates.label is
  'Titre lisible du modèle, affiché dans la colonne de gauche de l''écran Modèles Mails. '
  'Obligatoire pour les templates de prospection (qui n''ont pas de label codé dans le JS) ; '
  'optionnel pour les transactionnels (qui retombent sur KNOWN[key].label si vide).';
