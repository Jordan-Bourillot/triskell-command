-- =====================================================================
-- Triskell Command — Chat 1-à-1 : réactions emoji sur les messages
-- =====================================================================
-- Une réaction = (message, qui réagit, quel emoji). Un même user peut
-- mettre PLUSIEURS emojis différents sur le même message, mais pas deux
-- fois le même emoji (contrainte unique). La levée d'une réaction se
-- fait par DELETE de la ligne (toggle côté code).
--
-- user_id en text : cohérent avec migration 29_chat_local_users.sql
-- (jordan / thomas, pas des UUIDs Supabase).
--
-- À exécuter dans le SQL Editor de Supabase, après 36_chat_edit.sql.
-- =====================================================================


create table if not exists public.message_reactions (
    id uuid primary key default gen_random_uuid(),
    message_id uuid not null references public.messages(id) on delete cascade,
    user_id text not null,
    emoji text not null,
    created_at timestamptz not null default now(),
    unique (message_id, user_id, emoji)
);


create index if not exists idx_message_reactions_msg
    on public.message_reactions (message_id);


-- RLS : mêmes règles que `messages` (les 2 users authentifiés lisent
-- et écrivent tout — on est en architecture confiance interne 2-users).
alter table public.message_reactions enable row level security;

create policy "auth read reactions" on public.message_reactions
    for select to authenticated using (true);
create policy "auth insert reactions" on public.message_reactions
    for insert to authenticated with check (true);
create policy "auth delete reactions" on public.message_reactions
    for delete to authenticated using (true);


-- Realtime : pour que les réactions arrivent vite chez l'autre.
alter publication supabase_realtime add table public.message_reactions;
