-- ===========================================================================
-- 39_prospects_email_unique_guard.sql
-- Verrou anti-doublon sur les emails des prospects (Auto-pilote v2, etape 1.2)
--
-- Probleme : la colonne `prospects.emails` est un JSONB array, donc une simple
-- contrainte UNIQUE n'est pas applicable dessus. Resultat : sans verrou, deux
-- prospects pouvaient finir avec la meme adresse email, et l'Auto-pilote
-- risquait d'envoyer plusieurs mails a la meme personne.
--
-- Solution : un trigger BEFORE INSERT/UPDATE sur la colonne emails qui :
--   1. Pour chaque email du nouveau / modifie row,
--   2. Cherche un AUTRE prospect (id different) qui contient deja cet email
--      (compare lowercased + trime),
--   3. Si trouve, leve une exception avec errcode 23505 (unique_violation).
--
-- Effet pour le code applicatif : l'insertion brute via supabase-py va
-- planter si un email est deja present ailleurs. La fonction RemoteCRM.upsert
-- (qui fait deja un find-and-merge sur match_keys) reste compatible : si elle
-- trouve un doublon AVANT d'inserer, elle fait un UPDATE du prospect existant
-- au lieu d'un INSERT, et le trigger n'est pas un probleme (l'id reste le
-- meme, donc le `p.id is distinct from new.id` exclut le row courant).
--
-- Pre-requis : la base doit etre propre (zero doublon) avant l'install,
-- sinon les premiers UPDATE des doublons existants planteront. Verifie avec
-- scripts/dedupe_prospects.py.
-- ===========================================================================

create or replace function public.check_prospect_email_unique()
returns trigger
language plpgsql
security definer
set search_path = public
as $func$
declare
  conflict_id uuid;
  conflict_email text;
begin
  -- Cas trivial : pas d'emails, rien a verifier
  if new.emails is null or jsonb_array_length(new.emails) = 0 then
    return new;
  end if;

  -- Pour chaque email du nouveau row, on cherche s'il existe deja chez un
  -- autre prospect (matching lowercased + trime, insensible a la casse)
  select p.id, lower(trim(other_email))
  into conflict_id, conflict_email
  from public.prospects p
  cross join lateral jsonb_array_elements_text(p.emails) as other_email
  where p.id is distinct from new.id
    and lower(trim(other_email)) <> ''
    and lower(trim(other_email)) in (
      select lower(trim(my_email))
      from jsonb_array_elements_text(new.emails) as my_email
      where lower(trim(my_email)) <> ''
    )
  limit 1;

  if conflict_id is not null then
    raise exception
      'prospect_email_duplicate: email % deja present chez prospect %',
      conflict_email, conflict_id
      using errcode = '23505';  -- unique_violation
  end if;

  return new;
end;
$func$;

drop trigger if exists trg_prospects_check_email_unique on public.prospects;

create trigger trg_prospects_check_email_unique
  before insert or update of emails on public.prospects
  for each row
  execute function public.check_prospect_email_unique();

-- ---------------------------------------------------------------------------
-- Test rapide (a executer manuellement pour valider) :
-- ---------------------------------------------------------------------------
-- 1) Doit reussir : insert d'un email tout neuf
--    insert into public.prospects (emails, status)
--      values ('["unique-test-1@example.com"]'::jsonb, 'new');
--
-- 2) Doit echouer (errcode 23505) : insert d'un email deja present
--    insert into public.prospects (emails, status)
--      values ('["unique-test-1@example.com"]'::jsonb, 'new');
--
-- 3) Cleanup
--    delete from public.prospects where 'unique-test-1@example.com' = any(
--      select jsonb_array_elements_text(emails)
--    );
