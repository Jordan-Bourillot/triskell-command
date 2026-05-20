-- =====================================================================
-- Triskell Command — Chat 1-à-1 : passage aux identifiants locaux
-- =====================================================================
-- Contexte : Jordan & Thomas partagent le même compte Supabase. Le chat
-- s'appuie donc sur l'identité LOCALE (cookie tc_session = 'jordan' /
-- 'thomas') et non plus sur un user_id Supabase. Le code Python lit
-- cette identité dans le cookie de session via web/auth.py.
--
-- Cette migration :
--   - purge les éventuels messages préexistants (le chat n'a jamais
--     vraiment marché → aucune donnée utile à préserver)
--   - retire les FK vers public.users sur messages et typing_status
--   - convertit les colonnes d'identifiant uuid → text
--   - reconstruit les index et le primary key
--
-- À exécuter UNE FOIS dans le SQL Editor de Supabase, après les
-- migrations 04_messages.sql et 05_typing.sql.
-- =====================================================================


-- Purge : aucune donnée à préserver
truncate table public.messages;
truncate table public.typing_status;


-- ─── messages : sender_id / recipient_id deviennent text ───
drop index if exists public.idx_messages_recipient_unread;
drop index if exists public.idx_messages_pair_created;

alter table public.messages drop constraint if exists messages_sender_id_fkey;
alter table public.messages drop constraint if exists messages_recipient_id_fkey;

alter table public.messages alter column sender_id type text;
alter table public.messages alter column recipient_id type text;

create index idx_messages_recipient_unread
    on public.messages (recipient_id, created_at desc)
    where read_at is null;
create index idx_messages_pair_created
    on public.messages (sender_id, recipient_id, created_at desc);


-- ─── typing_status : user_id devient text ───
alter table public.typing_status drop constraint if exists typing_status_user_id_fkey;
alter table public.typing_status drop constraint if exists typing_status_pkey;

alter table public.typing_status alter column user_id type text;
alter table public.typing_status add constraint typing_status_pkey primary key (user_id);
