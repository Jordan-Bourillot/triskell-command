-- =====================================================================
-- Triskell Command — Chat 1-à-1 : statut « distribué » des messages
-- =====================================================================
-- Objectif : afficher sous chaque message envoyé un état façon WhatsApp
--   - envoyé    : le message est parti (déjà connu : la ligne existe)
--   - distribué : le message est arrivé sur le poste de l'autre, même
--                 s'il n'a pas encore ouvert le chat   ← AJOUTÉ ICI
--   - lu        : l'autre a ouvert le chat (déjà connu : read_at)
--
-- On ajoute une colonne `delivered_at` (timestamp posé par le poste qui
-- REÇOIT le message, lors de son polling de fond) + un index partiel pour
-- retrouver vite les messages pas encore distribués.
--
-- Le code applicatif est tolérant : tant que cette migration n'est pas
-- appliquée, le chat affiche simplement « envoyé / lu » sans erreur.
--
-- À exécuter UNE FOIS dans le SQL Editor de Supabase, après 43_*.sql.
-- =====================================================================

alter table public.messages
    add column if not exists delivered_at timestamptz;

create index if not exists idx_messages_recipient_undelivered
    on public.messages (recipient_id, created_at desc)
    where delivered_at is null;
