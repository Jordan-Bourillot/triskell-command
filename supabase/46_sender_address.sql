-- ============================================================
-- Migration 46 — Câblage modèle→adresse d'envoi (2026-06-11)
-- ============================================================
-- prospect_drafts.sender_address : l'adresse d'expéditeur EXIGÉE pour ce
-- brouillon, posée à sa création :
--   - brouillon de l'Auto-pilote → l'adresse « Expéditeur (adresse) » du
--     modèle de prospection utilisé (champ éditable dans Modèles mails) ;
--   - brouillon de relance (drip J+7/J+30) → l'adresse du mail initial
--     (une relance repart de la MÊME adresse que le premier mail).
-- À la validation, le mail part par le compte d'envoi correspondant —
-- JAMAIS par un autre. Compte introuvable → refus propre, rien n'est
-- envoyé.
--
-- Le code marche SANS cette colonne (insertion dégradée + filet : à la
-- validation, l'adresse est retrouvée via le modèle d'origine du
-- brouillon quand c'est non ambigu). Avec elle, l'exigence voyage
-- explicitement avec chaque brouillon.

alter table public.prospect_drafts
  add column if not exists sender_address text not null default '';
