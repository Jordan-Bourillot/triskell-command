-- ============================================================================
-- Migration 48 — Le Phare : bouton « OK, fais-le » + explications simples
-- (12/06/2026 — demande Jordan : plus de doublons, tout automatisable en un
--  clic, et des cartes compréhensibles sans jargon.)
--
-- Ajoute à phare_actions :
--   simple_md          : explication en français normal (écrite par les
--                        agents ou par l'Exécuteur) — affichée en avant
--                        sur la carte, le détail technique passe en replié.
--   apply_state        : file du bouton « OK, fais-le » :
--                        '' | queued | running | done | manual | failed
--   apply_error        : raison en français quand manual/failed.
--   apply_requested_at : horodatage du clic (sert aussi à détecter les
--                        traitements interrompus > 2 h).
--
-- Le code marche SANS cette migration (mode dégradé propre : les inserts
-- retentent sans ces colonnes, le bouton renvoie un message clair) — mais
-- le bouton « OK, fais-le » a besoin d'elle pour fonctionner.
-- À coller dans l'éditeur SQL Supabase.
-- ============================================================================

alter table public.phare_actions
    add column if not exists simple_md text default '',
    add column if not exists apply_state text not null default '',
    add column if not exists apply_error text default '',
    add column if not exists apply_requested_at timestamptz;

-- Le worker lit la file en boucle : index partiel, quasi gratuit.
create index if not exists idx_phare_actions_apply_queue
    on public.phare_actions (apply_requested_at)
    where apply_state in ('queued', 'running');

comment on column public.phare_actions.simple_md is
    'Explication sans jargon, affichée en avant sur la carte (agents/Exécuteur).';
comment on column public.phare_actions.apply_state is
    'File « OK, fais-le » : vide | queued | running | done | manual | failed.';
comment on column public.phare_actions.apply_error is
    'Raison en français quand apply_state = manual ou failed.';
comment on column public.phare_actions.apply_requested_at is
    'Horodatage du clic « OK, fais-le » (détection des traitements morts).';
