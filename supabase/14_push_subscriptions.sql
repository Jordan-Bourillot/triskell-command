-- Web Push subscriptions pour Triskell Command web.
--
-- Stocke les abonnements push de Jordan et Thomas, par appareil (un user
-- peut avoir plusieurs subs : son tel, son PC perso, son PC bureau, etc.).
-- L'endpoint est unique (URL fournie par le navigateur).
--
-- À exécuter une fois dans Supabase SQL Editor.

create table if not exists triskell_command_push_subscriptions (
    id          uuid primary key default gen_random_uuid(),
    user_id     text not null,                       -- 'jordan' | 'thomas'
    endpoint    text unique not null,
    p256dh      text not null,
    auth_token  text not null,
    user_agent  text,                                -- optionnel, pour debug
    created_at  timestamptz not null default now(),
    last_used   timestamptz not null default now()
);

create index if not exists idx_triskell_command_push_user
    on triskell_command_push_subscriptions(user_id);

-- RLS désactivée : la table n'est accédée que par le serveur Python avec la
-- service_role_key, jamais en direct depuis le front.
alter table triskell_command_push_subscriptions enable row level security;

create policy "Service role full access"
    on triskell_command_push_subscriptions
    for all
    using (true)
    with check (true);
