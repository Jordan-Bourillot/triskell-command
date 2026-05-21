-- =====================================================================
-- Triskell Command — Chat 1-à-1 : possibilité de "répondre" à un message
-- =====================================================================
-- Ajoute une colonne `reply_to_id` à la table `messages` : si un message
-- est une réponse à un autre, il référence l'ID du message parent. La
-- contrainte `on delete set null` évite de perdre la réponse si jamais
-- le parent est supprimé (cas théorique, on ne supprime pas en pratique).
--
-- À exécuter dans le SQL Editor de Supabase, après 30_chat_attachments_and_colors.sql.
-- =====================================================================


alter table public.messages
    add column if not exists reply_to_id uuid
    references public.messages(id) on delete set null;


-- Index partiel : seules les réponses portent la colonne, on ne stocke
-- l'index que sur ces lignes-là (la grande majorité des messages n'ont
-- pas de parent).
create index if not exists idx_messages_reply_to
    on public.messages (reply_to_id)
    where reply_to_id is not null;
