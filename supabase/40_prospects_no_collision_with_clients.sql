-- ===========================================================================
-- 40_prospects_no_collision_with_clients.sql
-- Empeche d'ajouter ou de modifier un prospect dont un email existe deja
-- dans la table `clients` (Auto-pilote v2, etape 1.3)
--
-- Pourquoi : on ne veut JAMAIS prospecter quelqu'un qui est deja client.
-- Une fois converti client, l'humain ne doit plus reapparaitre dans la base
-- prospects. Ce trigger pose le garde-fou cote BDD pour que TOUTES les
-- sources d'insertion (RemoteCRM, Obelisk, Le Chasseur, imports CSV, etc.)
-- soient protegees uniformement.
--
-- Effet pour le code applicatif : l'insert/update qui violerait la regle
-- recoit une exception avec errcode 23505 (unique_violation) dont le message
-- contient "client_email_collision". Le code appelant peut catcher
-- specifiquement ce cas pour faire un skip silencieux et logger.
-- ===========================================================================

create or replace function public.check_prospect_no_client_collision()
returns trigger
language plpgsql
security definer
set search_path = public
as $func$
declare
  conflict_email text;
begin
  -- Pas d'emails, rien a verifier
  if new.emails is null or jsonb_array_length(new.emails) = 0 then
    return new;
  end if;

  -- Pour chaque email du nouveau row, regarder s'il existe dans clients
  -- (compare lowercased, cohérent avec clients_email_lower_idx existant)
  select lower(trim(other_email))
  into conflict_email
  from jsonb_array_elements_text(new.emails) as other_email
  where lower(trim(other_email)) <> ''
    and exists (
      select 1
      from public.clients c
      where lower(c.email) = lower(trim(other_email))
    )
  limit 1;

  if conflict_email is not null then
    raise exception
      'client_email_collision: email % est deja un client, prospect refuse',
      conflict_email
      using errcode = '23505';
  end if;

  return new;
end;
$func$;

drop trigger if exists trg_prospects_check_no_client_collision on public.prospects;

create trigger trg_prospects_check_no_client_collision
  before insert or update of emails on public.prospects
  for each row
  execute function public.check_prospect_no_client_collision();
