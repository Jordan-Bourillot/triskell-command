-- =====================================================================
-- Triskell Command — Chat 1-à-1 : suppression "soft" d'un message
-- =====================================================================
-- On ne supprime PAS physiquement les lignes (audit + cohérence avec
-- les réactions et les réponses qui pointent dessus). À la place, on
-- pose un timestamp `deleted_at` ; côté UI, on remplace le contenu par
-- "Message supprimé" en gris.
--
-- À exécuter dans le SQL Editor de Supabase, après 37_chat_reactions.sql.
-- =====================================================================


alter table public.messages
    add column if not exists deleted_at timestamptz;
