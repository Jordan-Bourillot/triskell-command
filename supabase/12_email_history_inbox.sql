-- =============================================================================
-- Migration 12 : email_history — autoriser les mails entrants sans prospect
-- =============================================================================
-- Avant : email_history.prospect_id NOT NULL, donc chaque ligne devait être
--         liée à un prospect connu (utile pour reply_received uniquement).
--
-- Maintenant : on veut aussi logger les mails entrants généraux
--              (kind='inbox_received') qui ne matchent aucun prospect, pour
--              alimenter la vue Mails > Tous entrants.
--
-- Effet : les anciennes lignes (reply_received) restent inchangées. Les
--         nouvelles lignes inbox_received pourront avoir prospect_id NULL.
-- =============================================================================

ALTER TABLE email_history
  ALTER COLUMN prospect_id DROP NOT NULL;

-- (Optionnel) index pour accélérer le filtre par kind sur la vue Mails
CREATE INDEX IF NOT EXISTS email_history_kind_ts_idx
  ON email_history (kind, ts DESC);
