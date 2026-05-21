-- =====================================================================
-- Obelisk — Ajoute un timestamp d'export sur les prospects
-- =====================================================================
-- Permet de filtrer dans le CRM les prospects qu'on a déjà sortis dans
-- une liste Excel/PDF (pour préparer une vague de prospection), afin de
-- ne pas les ré-exporter sans le savoir.
--
-- La colonne `last_contact_at` existait déjà — on l'utilise pour le
-- filtre "déjà contacté par mail" côté UI, donc rien à ajouter pour ça.
-- =====================================================================

alter table public.prospects
    add column if not exists exported_at timestamptz;

create index if not exists idx_prospects_exported_at
    on public.prospects (exported_at desc nulls last);
