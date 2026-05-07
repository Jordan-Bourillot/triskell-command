-- =====================================================================
-- Triskell Command — Chat 1-à-1 Jordan ↔ Thomas
-- =====================================================================
-- À exécuter UNE FOIS dans le SQL Editor de Supabase, après 01/02/03.
-- Crée la table `messages`, ses politiques RLS et l'ajoute au realtime.
-- =====================================================================


-- ---------------------------------------------------------------------
-- messages : un message court d'un user à un autre.
--   - Pas d'updated_at : un message envoyé n'est pas modifiable.
--   - read_at : passé à now() côté destinataire quand il ouvre le chat.
-- ---------------------------------------------------------------------
create table public.messages (
    id uuid primary key default gen_random_uuid(),
    sender_id uuid not null references public.users(user_id) on delete cascade,
    recipient_id uuid not null references public.users(user_id) on delete cascade,
    body text not null,
    created_at timestamptz not null default now(),
    read_at timestamptz
);

create index idx_messages_recipient_unread
    on public.messages (recipient_id, created_at desc)
    where read_at is null;

create index idx_messages_pair_created
    on public.messages (sender_id, recipient_id, created_at desc);


-- RLS : tout authentifié lit/écrit (cohérent avec les autres tables).
-- Lit/écrit, mais ne supprime pas (les messages restent en historique).
alter table public.messages enable row level security;

create policy "auth read messages" on public.messages
    for select to authenticated using (true);
create policy "auth insert messages" on public.messages
    for insert to authenticated with check (true);
create policy "auth update messages" on public.messages
    for update to authenticated using (true) with check (true);


-- Realtime : pour qu'un message envoyé par Jordan arrive vite chez Thomas
-- (même si on poll aussi côté client toutes les 10 s).
alter publication supabase_realtime add table public.messages;
