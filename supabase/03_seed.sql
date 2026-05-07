-- =====================================================================
-- Triskell Command — Seed initial (profils Jordan + Thomas)
-- =====================================================================
-- À exécuter APRÈS avoir créé les 2 comptes Supabase Auth via le dashboard
-- Supabase (Authentication → Users → Add user) :
--
--   1. Crée le compte Jordan : email = jordan@triskell-studio.fr
--      (ou ton email habituel)
--   2. Crée le compte Thomas : email = thomasbourillot@gmail.com
--   3. Récupère leurs UUID dans Authentication → Users
--   4. Remplace <JORDAN_UUID> et <THOMAS_UUID> ci-dessous
--   5. Lance ce SQL
--
-- Si tu te trompes : delete from public.users; et recommence.
-- =====================================================================


-- ⚠️ REMPLACE ces UUID par les vrais (visibles dans Supabase Auth → Users)
-- Tu peux aussi laisser ce fichier en l'état et le faire en 2 INSERT
-- séparés depuis le dashboard.
--
-- exemple : '00000000-0000-0000-0000-000000000001'

insert into public.users (user_id, display_name, color)
values
    ('<JORDAN_UUID>', 'Jordan', '#7C7FE9'),    -- indigo
    ('<THOMAS_UUID>', 'Thomas', '#D4B35A')     -- or
on conflict (user_id) do nothing;


-- Settings partagés vides (l'app les remplira au premier passage dans Réglages)
insert into public.shared_settings (key, value) values
    ('ai',       '{"selected_provider":"anthropic","selected_model":"claude-sonnet-4-5","api_keys":{}}'),
    ('outreach', '{"smtp_host":"","smtp_port":587,"smtp_user":"","smtp_password":"","from_email":"","from_name":"","imap_host":"","imap_port":993,"imap_user":"","imap_password":"","daily_cap":40,"follow_up_days":5,"signature":""}'),
    ('sources',  '{"youtube_api_key":"","twitch_client_id":"","twitch_client_secret":"","google_places_api_key":""}')
on conflict (key) do nothing;
