-- ============================================================
-- 33_convoy_template_product.sql
--
-- Permet à une campagne Convoi de "piocher" dans une liste de
-- templates de prospection rédigés à la main pour un produit donné
-- (table triskell_email_templates, category='prospection').
--
-- Si template_product est vide → comportement actuel : l'IA génère
-- chaque mail from scratch à partir du brief + catalogue.
--
-- Si template_product = 'pixelpros' (par exemple) → l'IA pioche le
-- template de prospection le plus pertinent pour le prospect parmi
-- ceux de ce produit, remplit les placeholders et l'adapte légèrement.
--
-- Idempotent : peut être rejoué sans danger.
-- ============================================================

alter table public.convoy_campaigns
  add column if not exists template_product text not null default '';

comment on column public.convoy_campaigns.template_product is
  'Si non vide : id du produit (triskell_email_templates.product) dont les templates de prospection seront proposés à l''IA pour qu''elle pioche le plus pertinent par prospect. Vide = génération libre.';
