-- Brain : pièces jointes (images) pour les notes.
-- À exécuter dans le SQL editor Supabase du projet command-voice/triskell.

-- 1) Colonne attachments sur la table existante
alter table public.command_voice_brain
    add column if not exists attachments text[] default '{}';

-- 2) Bucket Storage public 'brain-attachments'
insert into storage.buckets (id, name, public)
    values ('brain-attachments', 'brain-attachments', true)
    on conflict (id) do nothing;

-- 3) RLS Storage : tout utilisateur authentifié peut uploader/lire
--    (le bucket est public en lecture, on autorise l'upload aux authentifiés)
drop policy if exists "brain_attach_insert_auth" on storage.objects;
create policy "brain_attach_insert_auth" on storage.objects
    for insert to authenticated
    with check (bucket_id = 'brain-attachments');

drop policy if exists "brain_attach_read_all" on storage.objects;
create policy "brain_attach_read_all" on storage.objects
    for select to public
    using (bucket_id = 'brain-attachments');

drop policy if exists "brain_attach_delete_auth" on storage.objects;
create policy "brain_attach_delete_auth" on storage.objects
    for delete to authenticated
    using (bucket_id = 'brain-attachments');
