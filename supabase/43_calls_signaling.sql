-- =====================================================================
-- Triskell Command — Appels audio / vidéo (WebRTC) dans le chat 1-à-1
-- =====================================================================
-- Pour passer un appel en direct entre deux navigateurs, ils doivent
-- d'abord s'échanger quelques infos techniques de mise en relation
-- (offre / réponse WebRTC). Cette table sert de « boîte aux lettres »
-- éphémère : chaque navigateur y DÉPOSE des signaux destinés à l'autre,
-- qui les RELÈVE en pollant (comme l'indicateur « écrit… »).
--
-- Une fois la connexion média établie, l'audio/vidéo circule en direct
-- de PC à PC (peer-to-peer) — cette table ne transporte PAS le son ni
-- l'image, seulement la poignée de main initiale + le « raccroché ».
--
-- from_user / to_user en text ('jordan' / 'thomas') : cohérent avec la
-- migration 29_chat_local_users.sql (les deux partagent un compte).
--
-- À exécuter UNE FOIS dans le SQL Editor de Supabase, après 42_*.sql.
-- =====================================================================


create table if not exists public.call_signals (
    id          uuid primary key default gen_random_uuid(),
    call_id     text not null,            -- identifie une session d'appel
    from_user   text not null,            -- 'jordan' | 'thomas'
    to_user     text not null,            -- destinataire du signal
    kind        text not null,            -- offer|answer|hangup|decline|cancel|busy
    mode        text,                     -- 'audio' | 'video' (porté par l'offre)
    payload     text,                     -- SDP complet (JSON), gros = ok en text
    created_at  timestamptz not null default now(),
    consumed_at timestamptz               -- posé quand le destinataire l'a relevé
);


-- Index de la « boîte de réception » : on relit vite les signaux qui me
-- sont destinés et pas encore consommés, du plus ancien au plus récent.
create index if not exists idx_call_signals_inbox
    on public.call_signals (to_user, consumed_at, created_at);


-- RLS : mêmes règles que le reste du chat (les 2 users authentifiés
-- lisent et écrivent tout — architecture de confiance interne 2-users).
alter table public.call_signals enable row level security;

create policy "auth read call_signals" on public.call_signals
    for select to authenticated using (true);
create policy "auth insert call_signals" on public.call_signals
    for insert to authenticated with check (true);
create policy "auth update call_signals" on public.call_signals
    for update to authenticated using (true) with check (true);
create policy "auth delete call_signals" on public.call_signals
    for delete to authenticated using (true);
