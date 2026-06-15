-- ============================================================
-- Migration 51 — Suivi de prospection des créateurs (2026-06-15)
-- ============================================================
-- Objectif : suivre les créateurs (YouTubeurs, Instagrameurs…) qu'on
-- démarche surtout PAR RÉSEAUX SOCIAUX (pas par mail). On ajoute à la
-- table partagée `prospects` trois colonnes optionnelles :
--
--   - contact_channel    : par quel canal on a pris contact
--                          ('instagram' / 'tiktok' / 'youtube' /
--                          'facebook' / 'email' / 'autre'). Texte libre,
--                          défaut vide → aucune valeur imposée, rien ne
--                          casse pour les prospects existants.
--   - next_follow_up_at  : date de PROCHAINE RELANCE réglée à la main.
--                          Sert à la vue « à relancer ». NULL = pas de
--                          relance programmée.
--   - demo_url           : lien de la démo qu'on a construite pour ce
--                          créateur (ce qu'on lui montre). Défaut vide.
--
-- 100% ADDITIF : `add column if not exists` ne touche aucune donnée ni
-- aucun comportement existant. Le code applicatif est défensif (il lit
-- ces colonnes avec .get / try) : il tourne avec OU sans cette migration.
-- ============================================================

alter table public.prospects
  add column if not exists contact_channel text default '';

alter table public.prospects
  add column if not exists next_follow_up_at timestamptz;

alter table public.prospects
  add column if not exists demo_url text default '';

-- Index sur la date de prochaine relance : la vue « à relancer » filtre
-- sur next_follow_up_at <= maintenant. Index partiel (lignes non nulles
-- seulement) pour rester léger, dans le même esprit que les autres index
-- de la table (cf. 01_schema.sql).
create index if not exists idx_prospects_next_follow_up_at
  on public.prospects (next_follow_up_at)
  where next_follow_up_at is not null;
