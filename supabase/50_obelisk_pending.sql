-- ─────────────────────────────────────────────────────────────────────
-- Migration 50 : file d'attente Obélisk — « Relire avant d'ajouter »
-- ─────────────────────────────────────────────────────────────────────
-- Quand l'option « Relire avant d'ajouter » est cochée dans Obélisk, les
-- créateurs trouvés ne sont PAS versés direct dans `prospects` : ils
-- attendent ici jusqu'à validation (bouton « Tout ajouter ») ou rejet
-- (« Ignorer ») depuis l'écran Obélisk.
--
-- `prospect` = la fiche prête à insérer dans `prospects` (workspace déjà
-- appliqué). Valider = recopier dans `prospects` puis vider la file.
--
-- Table interne, alimentée/lue UNIQUEMENT côté serveur (clé service_role).
-- Sans cette table, le code marche quand même : l'option de validation est
-- désactivée par défaut, et tant qu'elle l'est, rien n'écrit ici.

create table if not exists public.obelisk_pending (
    id          uuid primary key default gen_random_uuid(),
    job_id      text,
    prospect    jsonb not null,
    created_at  timestamptz not null default now()
);

create index if not exists idx_obelisk_pending_job
    on public.obelisk_pending (job_id);
