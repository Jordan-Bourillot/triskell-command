-- ============================================================
-- 32_convoy_sender_pool.sql
--
-- Multi-adresses pour le Convoi : chaque campagne peut désormais
-- envoyer en alternance depuis PLUSIEURS comptes mail, avec un cap
-- 24h glissantes propre à chaque adresse.
--
-- La colonne sender_account_id ajoutée par 27_convoy_sender_account
-- reste comme expéditeur "par défaut" / rétrocompat. Si sender_pool
-- est vide, le moteur d'envoi tombe sur l'ancien comportement
-- mono-adresse.
--
-- Format de sender_pool (jsonb array) :
--   [
--     { "account_id": "primary",  "daily_cap": 30 },
--     { "account_id": "lagriffe", "daily_cap": 20 },
--     ...
--   ]
--
-- Idempotent : peut être rejoué sans danger.
-- ============================================================

alter table public.convoy_campaigns
  add column if not exists sender_pool jsonb not null default '[]'::jsonb;

comment on column public.convoy_campaigns.sender_pool is
  'Pool d''adresses expéditrices avec cap 24h glissantes par adresse. Format : [{"account_id":"primary","daily_cap":30}, ...]. Vide = on retombe sur l''envoi mono-adresse via sender_account_id + daily_cap.';
