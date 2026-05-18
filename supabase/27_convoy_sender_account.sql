-- ============================================================
-- 27_convoy_sender_account.sql
--
-- Ajoute la colonne sender_account_id sur convoy_campaigns pour
-- permettre de choisir l'adresse expéditrice de chaque convoi
-- (compte principal "primary" ou id d'un compte secondaire
-- stocké dans shared_settings.mail_accounts, ex : "lagriffe").
--
-- Idempotent : peut être rejoué sans danger.
-- ============================================================

alter table public.convoy_campaigns
  add column if not exists sender_account_id text not null default 'primary';

comment on column public.convoy_campaigns.sender_account_id is
  'Id du compte mail expéditeur : "primary" (compte principal) ou id d''un compte secondaire stocké dans shared_settings.mail_accounts.';

-- Override par draft : adresse liée à l'offre pitchée (pour qu'un mail
-- Lagriffe parte de contact@lagriffe-studio.fr, un RankUs depuis sa
-- boîte, etc.). Vide = pas d'override, on prend celui de la campagne.
alter table public.convoy_drafts
  add column if not exists offer_mail_account_id text not null default '';

comment on column public.convoy_drafts.offer_mail_account_id is
  'Override : compte mail à utiliser pour CE draft (lié à l''offre pitchée). Vide = on prend celui de la campagne (convoy_campaigns.sender_account_id).';

-- Mails générés via « Tester (5) » — bandeau + tri en haut de liste.
alter table public.convoy_drafts
  add column if not exists is_test boolean not null default false;

comment on column public.convoy_drafts.is_test is
  'True quand le draft a été généré via le bouton « Tester (5) ». Sert au tri (test en haut) et au badge visuel.';
