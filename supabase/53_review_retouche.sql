-- Migration 53 : retouche unique de la 2e IA (avant/après note + type).
--
-- Demande de Jordan (17/06/2026). La 2e IA relectrice a maintenant le droit
-- de faire UNE petite retouche du mail, puis de RELIRE et RENOTER (une seule
-- fois). On garde la retouche seulement si elle améliore (ou égale) la note.
-- On stocke l'ancienne note, la nouvelle, et le type de retouche pour les
-- afficher dans « Brouillons à valider » (ex. « 8 → 9 · ✏️ retouché :
-- phrase reformulée »).
--
-- Même famille que la migration 45 (review_score / review_verdict /
-- review_comment). Le code marche SANS cette migration : l'enregistrement
-- des brouillons retombe automatiquement sur la version sans ces colonnes,
-- et l'écran affiche simplement la note unique comme avant.

alter table public.prospect_drafts
  add column if not exists review_score_before int;

alter table public.prospect_drafts
  add column if not exists review_score_after int;

alter table public.prospect_drafts
  add column if not exists review_modif_type text not null default '';

alter table public.prospect_drafts
  add column if not exists review_modif_applied boolean not null default false;
