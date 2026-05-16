-- Brain : urgence (1-5) et importance (1-5) estimées par Claude.
-- À exécuter dans le SQL editor Supabase.

alter table public.command_voice_brain
    add column if not exists urgency    int,
    add column if not exists importance int;

-- Index pour le tri par "priorité" (urgency * importance) côté requêtes
create index if not exists idx_cv_brain_priority
    on public.command_voice_brain ((coalesce(urgency,0) * coalesce(importance,0)) desc)
    where status = 'open';
