-- =====================================================================
-- Triskell Command — Chat 1-à-1 : modification d'un message envoyé
-- =====================================================================
-- Ajoute une colonne `edited_at` à la table `messages` : si l'expéditeur
-- modifie son message après envoi, on stocke la date de la modification.
-- On ne garde PAS l'historique du texte précédent (on écrase `body`) ;
-- on garde juste la trace "ce message a été édité" pour l'afficher
-- côté UI ("(modifié)" à côté de l'heure).
--
-- À exécuter dans le SQL Editor de Supabase, après 35_chat_reply_to.sql.
-- =====================================================================


alter table public.messages
    add column if not exists edited_at timestamptz;
