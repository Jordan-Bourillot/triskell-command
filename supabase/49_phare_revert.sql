-- 49 — Annulation d'une modification publiée par Le Phare (12/06/2026).
-- Le « vrai bouton Annuler » : trace de l'annulation sur l'action.
-- Le code marche SANS cette migration (le status passe à 'reverted' seul) ;
-- l'appliquer ajoute la date et le lien de la PR d'annulation.

alter table public.phare_actions
    add column if not exists reverted_at timestamptz,
    add column if not exists revert_pr_url text default '';

comment on column public.phare_actions.reverted_at
    is 'Date de l''annulation (bouton « Annuler » du Phare)';
comment on column public.phare_actions.revert_pr_url
    is 'PR GitHub du revert créé par l''annulation';
