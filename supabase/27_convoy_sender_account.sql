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
