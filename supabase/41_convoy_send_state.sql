-- ============================================================
-- 41_convoy_send_state.sql
--
-- Resilience du Convoi : etat d'envoi persiste + lock heartbeat
-- pour que les campagnes en cours d'envoi reprennent automatiquement
-- apres un redemarrage du serveur Coolify.
--
-- Probleme resolu : avant ce patch, le runner d'envoi tournait dans
-- un thread daemon dans le processus du serveur HTTP. Tout deploiement
-- du conteneur Coolify tuait le thread et la campagne restait bloquee
-- avec ses drafts "approved" pas envoyes.
--
-- Mecanique :
--   1. Quand un worker demarre, il passe send_state='running' et
--      pose son send_lock_token + send_lock_heartbeat_at.
--   2. Toutes les 30s, le worker renouvelle send_lock_heartbeat_at.
--   3. Au boot du serveur, on scan les campagnes avec
--      send_state='running' ET (heartbeat NULL OR vieux de > 2 min)
--      → on les considere abandonnees et on relance un worker dessus.
--   4. Le worker verifie avant chaque envoi que son token est toujours
--      celui en base (sinon, un autre worker a pris la main → abandon).
--   5. Quand la campagne termine, on passe send_state='done'.
--
-- Idempotent : peut etre rejoue sans danger.
-- ============================================================

alter table public.convoy_campaigns
  add column if not exists send_state text not null default 'idle';

alter table public.convoy_campaigns
  add column if not exists send_lock_token text;

alter table public.convoy_campaigns
  add column if not exists send_lock_heartbeat_at timestamptz;

alter table public.convoy_campaigns
  add column if not exists send_started_at timestamptz;

alter table public.convoy_campaigns
  add column if not exists send_finished_at timestamptz;

-- Garde-fou : send_state limite a 4 valeurs connues
do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'convoy_campaigns_send_state_check'
  ) then
    alter table public.convoy_campaigns
      add constraint convoy_campaigns_send_state_check
      check (send_state in ('idle', 'running', 'done', 'failed'));
  end if;
end$$;

-- Index pour la requete de reprise au boot
create index if not exists convoy_campaigns_send_state_idx
  on public.convoy_campaigns(send_state, send_lock_heartbeat_at);

comment on column public.convoy_campaigns.send_state is
  'Etat d''envoi : idle (pas d''envoi en cours) / running (worker actif) / done (envoi termine) / failed (echec definitif). Mis a jour par le runner.';
comment on column public.convoy_campaigns.send_lock_token is
  'UUID unique du worker qui detient actuellement le verrou d''envoi. Permet de detecter si un autre worker a pris la main (apres un redemarrage par ex).';
comment on column public.convoy_campaigns.send_lock_heartbeat_at is
  'Dernier "je suis vivant" du worker. Renouvele toutes les ~30s. Si > 2 min, le worker est considere mort et un autre peut prendre la main.';
