-- =====================================================================
-- Le Phare — credentials à coller dans phare_config
-- =====================================================================
-- À exécuter APRÈS 06_phare.sql, 06b_phare_seed_real.sql,
-- 06c_phare_advanced.sql et 06d_phare_pro.sql.
--
-- Remplis les <REMPLIR> ci-dessous puis colle TOUT le bloc dans le
-- SQL Editor Supabase et clique Run.
--
-- Ordre conseillé pour obtenir chaque token :
--   1. GitHub PAT (5 min, gratuit)
--   2. Netlify token (3 min, gratuit)
--   3. DataForSEO compte (10 min, payant ~30-60€/mois — peut être skippé
--      au début, l'agent Veilleur tournera juste sur GSC)
--   4. GSC service-account.json (15 min, gratuit, mais le plus chiant)
--
-- =====================================================================
-- 1. CREDENTIALS PRINCIPAUX (phare_config)
-- =====================================================================

update public.shared_settings
set value = value || jsonb_build_object(

    -- GitHub PAT (fine-grained recommandé)
    --   https://github.com/settings/tokens
    --   Scopes : Contents: Read & Write + Pull requests: Read & Write
    --   Repositories : tous les repos Triskell listés dans phare_sites
    'github_token',          '<REMPLIR_ghp_...>',

    -- Netlify Personal Access Token
    --   https://app.netlify.com/user/applications#personal-access-tokens
    'netlify_token',         '<REMPLIR_nfp_...>',

    -- DataForSEO (login + password de ton compte API)
    --   https://app.dataforseo.com (compte payant)
    --   Laisse vides si tu skip pour l'instant — le Veilleur fallback sur GSC
    'dataforseo_login',      '<REMPLIR_email_dataforseo>',
    'dataforseo_password',   '<REMPLIR_password_dataforseo>',

    -- GSC service-account.json — chemin LOCAL absolu sur ton poste
    --   Console Google Cloud → API & Services → Credentials → Create
    --   Service Account → key JSON → télécharge → place le fichier
    --   ex: C:/Users/jorda/.triskell-command/gsc-service-account.json
    --   Puis dans Search Console : ajoute l''email du SA comme user
    --   sur chaque property *.triskell-studio.fr
    'gsc_credentials_path',  '<REMPLIR_chemin_absolu_json>',

    -- PageSpeed API key (optionnel, quota anonyme suffit pour 13 sites)
    --   https://developers.google.com/speed/docs/insights/v5/get-started
    'pagespeed_api_key',     ''
)
where key = 'phare_config';


-- =====================================================================
-- 2. CREDENTIALS v0.6 (modules pro — Local SEO, CRO, Brand monitoring, GEO)
-- =====================================================================
-- Ces credentials sont OPTIONNELS au démarrage. Le Phare boot et tourne
-- sans, ils débloquent juste les modules pro avancés.

update public.shared_settings
set value = value || jsonb_build_object(

    -- Google Places API (pour Local SEO — Eliks Studio surtout)
    --   https://console.cloud.google.com → API Library → Places API
    'google_places_api_key', '',

    -- Microsoft Clarity (CRO — gratuit, pas de carte bancaire)
    --   https://clarity.microsoft.com → ton projet → Settings → Setup → API
    'clarity_project_id',    '',
    'clarity_api_token',     '',

    -- Google Custom Search (Brand Monitoring — fallback gratuit 100 req/j)
    --   https://programmablesearchengine.google.com
    'google_cse_api_key',    '',
    'google_cse_cx',         '',

    -- Mapping Google Business Profile : { "site_id": "place_id", ... }
    'gbp_place_ids',         '{}'::jsonb
)
where key = 'phare_config';


-- =====================================================================
-- 3. CLÉS IA (shared_settings.ai_keys)
-- =====================================================================
-- Anthropic est OBLIGATOIRE (les 8 agents Phare tournent dessus).
-- Perplexity et OpenAI sont optionnels (uniquement pour le module GEO
-- check : présence dans Perplexity / ChatGPT).

update public.shared_settings
set value = value || jsonb_build_object(
    'anthropic',  '<REMPLIR_clé_anthropic_sk-ant-...>',
    'perplexity', '',
    'openai',     ''
)
where key = 'ai_keys';


-- =====================================================================
-- 4. SITES À COMPLÉTER (3 sites où l'auto-détection a échoué)
-- =====================================================================
-- Décommente et remplis si tu veux que Le Phare surveille ces sites.
-- Sinon ils resteront marqués "is_active = true" mais sans pipeline Git.

-- update public.phare_sites set
--     repo_github = 'Jordan-Bourillot/<REMPLIR>'
-- where domain = 'outils.triskell-studio.fr';

-- update public.phare_sites set
--     repo_github = 'Jordan-Bourillot/<REMPLIR>'
-- where domain = 'eliks.triskell-studio.fr';

-- update public.phare_sites set
--     repo_github     = 'Jordan-Bourillot/<REMPLIR>',
--     netlify_site_id = '<REMPLIR>'
-- where domain = 'sites.triskell-studio.fr';


-- =====================================================================
-- VÉRIF FINALE — pour contrôler que tout est en place
-- =====================================================================
-- Décommente et lance pour vérifier :

-- select key,
--        case when value->>'github_token'    <> '' then 'OK' else 'KO' end as gh,
--        case when value->>'netlify_token'   <> '' then 'OK' else 'KO' end as netlify,
--        case when value->>'dataforseo_login'<> '' then 'OK' else 'skip' end as d4seo,
--        case when value->>'gsc_credentials_path' <> '' then 'OK' else 'KO' end as gsc
-- from public.shared_settings where key = 'phare_config';

-- select count(*) as nb_sites_pretes
-- from public.phare_sites
-- where is_active = true and repo_github <> '' and netlify_site_id <> '';
-- -- doit afficher 10 (sur 13, 3 sites sans repo)
