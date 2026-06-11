-- ===========================================================================
-- 47_prospects_require_email.sql
-- Verrou « pas d'entrée sans adresse mail » (demande Jordan, 11/06/2026)
--
-- Politique : le fichier prospects ne contient QUE des fiches contactables
-- par mail. Une fiche sans aucune adresse ne sert à rien à l'Auto-pilote
-- (qui n'enrichit jamais) et pollue les compteurs. La base a été purgée le
-- 11/06/2026 (32 fiches sans mail supprimées, sauvegarde locale faite) ;
-- ce trigger empêche le retour du problème par N'IMPORTE QUEL chemin
-- (import fichier, outils de chasse, ajout manuel, code futur).
--
-- Même squelette que les verrous 39 (email unique) et 40 (collision client).
-- Le code applicatif reconnaît le message 'prospect_sans_email' pour
-- compter proprement les refus (cf. obelisk_import_file dans api.py).
--
-- Couvre INSERT et UPDATE de la colonne emails : une fiche existante ne
-- peut pas non plus être vidée de ses adresses (la politique est « aucun
-- prospect sans mail dans le fichier », pas seulement à l'entrée — pour
-- retirer une adresse morte d'une fiche, on supprime la fiche).
-- ===========================================================================

create or replace function public.check_prospect_has_email()
returns trigger
language plpgsql
security definer
set search_path = public
as $func$
begin
  if new.emails is null
     or jsonb_array_length(new.emails) = 0
     or not exists (
       select 1
       from jsonb_array_elements_text(new.emails) as e
       where trim(e) <> ''
     ) then
    raise exception
      'prospect_sans_email: un prospect doit avoir au moins une adresse mail pour entrer dans le fichier'
      using errcode = '23514';  -- check_violation
  end if;
  return new;
end;
$func$;

drop trigger if exists trg_prospects_require_email on public.prospects;

create trigger trg_prospects_require_email
  before insert or update of emails on public.prospects
  for each row
  execute function public.check_prospect_has_email();

-- ---------------------------------------------------------------------------
-- Test rapide (à exécuter manuellement pour valider) :
-- ---------------------------------------------------------------------------
-- 1) Doit échouer (errcode 23514) : insert sans aucun email
--    insert into public.prospects (name, emails, status)
--      values ('Test sans mail', '[]'::jsonb, 'new');
--
-- 2) Doit réussir : insert avec un email
--    insert into public.prospects (name, emails, status)
--      values ('Test avec mail', '["verrou-47-test@example.com"]'::jsonb, 'new');
--
-- 3) Cleanup
--    delete from public.prospects
--      where emails @> '["verrou-47-test@example.com"]'::jsonb;
