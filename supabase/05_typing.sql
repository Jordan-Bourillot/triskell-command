-- =====================================================================
-- Triskell Command — Indicateur « X est en train d'écrire » (chat)
-- =====================================================================
-- À exécuter UNE FOIS dans le SQL Editor de Supabase, après 04_messages.sql.
--
-- Modèle : 1 ligne par user. À chaque frappe (throttle 2 s côté client),
-- on UPSERT `until_ts = now() + 5 s`. L'autre user lit `until_ts > now()`
-- → "il écrit".
-- =====================================================================


create table public.typing_status (
    user_id uuid primary key references public.users(user_id) on delete cascade,
    until_ts timestamptz not null default now()
);


-- RLS : tout authentifié lit/écrit (cohérent avec le reste).
alter table public.typing_status enable row level security;

create policy "auth read typing_status" on public.typing_status
    for select to authenticated using (true);
create policy "auth insert typing_status" on public.typing_status
    for insert to authenticated with check (true);
create policy "auth update typing_status" on public.typing_status
    for update to authenticated using (true) with check (true);


-- Pas besoin de realtime sur cette table — on poll côté dialog ouvert.
