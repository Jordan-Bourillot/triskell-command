-- =====================================================================
-- Triskell Command — Chat 1-à-1 : pièces jointes + couleurs perso
-- =====================================================================
-- Étend la table messages pour qu'un message puisse porter une pièce
-- jointe (image, document, etc.). Les fichiers eux-mêmes sont stockés
-- localement sur le serveur HTTP (voir api.py, dossier
-- ~/.triskell-command/chat-attachments/), et la table ne garde que
-- l'URL de récupération.
--
-- Les couleurs personnelles (Jordan / Thomas) sont stockées côté
-- serveur dans un fichier local (~/.triskell-command/user_chat_colors.json),
-- pas en base — c'est une préférence personnelle, pas une donnée métier.
--
-- À exécuter dans le SQL Editor de Supabase, après 29_chat_local_users.sql.
-- =====================================================================


alter table public.messages add column if not exists attachment_url   text;
alter table public.messages add column if not exists attachment_name  text;
alter table public.messages add column if not exists attachment_type  text;  -- mime type (image/png, application/pdf, ...)
alter table public.messages add column if not exists attachment_size  integer;


-- Permet d'envoyer un message qui n'a QUE une pièce jointe (pas de texte).
-- Avant : `body text not null`. On relâche la contrainte.
alter table public.messages alter column body drop not null;


-- Garde-fou : un message doit avoir SOIT du texte SOIT une pièce jointe
-- (pas les deux à null). Sinon il n'a aucun sens.
alter table public.messages drop constraint if exists messages_body_or_attachment;
alter table public.messages add constraint messages_body_or_attachment
    check (
        (body is not null and length(trim(body)) > 0)
        or attachment_url is not null
    );
