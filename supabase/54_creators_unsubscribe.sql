-- Migration 54 — Désinscription des créateurs
--
-- Ajoute la colonne `unsubscribed_at` au carnet des créateurs (table
-- `contacted_creators`). Elle mémorise le moment où un créateur a cliqué
-- « se désabonner » dans un mail de prise de contact / relance.
--
-- Le code marche SANS cette colonne (mode dégradé propre : les en-têtes et le
-- pied de désinscription partent quand même, seul le blocage d'un re-contact
-- exige la colonne). L'appliquer rend la désinscription pleinement effective.
--
-- Même famille que le statut « unsubscribed » des prospects, mais dans le
-- carnet séparé des créateurs (pas de table `prospects`).

ALTER TABLE public.contacted_creators
    ADD COLUMN IF NOT EXISTS unsubscribed_at timestamptz;

COMMENT ON COLUMN public.contacted_creators.unsubscribed_at IS
    'Date/heure du clic « se désabonner » — créateur plus jamais recontacté.';
