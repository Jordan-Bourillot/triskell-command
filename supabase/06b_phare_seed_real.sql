-- =====================================================================
-- Triskell Command — Migration 06b : Le Phare, mapping réel auto-détecté
-- =====================================================================
-- À exécuter APRÈS 06_phare.sql.
--
-- Ce fichier renseigne les vrais champs `repo_github`, `netlify_site_id`,
-- `stack` et `key_paths` pour les sites Triskell, détectés depuis les
-- `.git/config` et `.netlify/state.json` présents sur le poste de Jordan.
--
-- Auto-détection effectuée le 2026-05-06 (Le Phare livraison initiale).
-- =====================================================================

-- ---------------------------------------------------------------------
-- Apex / Table Ronde (catalogue principal — héberge AUSSI les sous-routes
-- AlphaBeast, AlphaCast, AlphaPitch, Obelisk, Teddy Mail, etc.)
-- ---------------------------------------------------------------------
update public.phare_sites set
    repo_github     = 'Jordan-Bourillot/triskell-site-officiel',
    netlify_site_id = 'a89769d6-bdba-49f7-b563-741e7a31be55',
    stack           = 'html',
    key_paths       = '["/"]'::jsonb,
    notes           = 'Site officiel triskell-studio.fr — vitrine + landings.'
where domain = 'triskell-studio.fr';

-- ---------------------------------------------------------------------
-- Pack Électricien Pro (CIBLE MVP — tunnel templateé)
-- ---------------------------------------------------------------------
update public.phare_sites set
    repo_github     = 'Jordan-Bourillot/pack-electricien-pro',
    netlify_site_id = '7c37740c-bf3d-4ce1-a4ee-d935ccf97f06',
    stack           = 'html',
    key_paths       = '["/", "/a-propos.html"]'::jsonb,
    notes           = 'CIBLE MVP. Tunnel Stripe rodé. ' ||
                      'Source : landing-pack/public/'
where domain = 'pack-elec.triskell-studio.fr';

-- ---------------------------------------------------------------------
-- Studio PDF
-- ---------------------------------------------------------------------
update public.phare_sites set
    repo_github     = 'Jordan-Bourillot/le-studio-pdf',
    netlify_site_id = '816f6588-75b2-4a97-bd38-56c964a214db',
    stack           = 'html',
    key_paths       = '["/"]'::jsonb,
    notes           = 'Source : landing/public/'
where domain = 'studio-pdf.triskell-studio.fr';

-- ---------------------------------------------------------------------
-- Suite des Héros (productivite.triskell-studio.fr)
-- ---------------------------------------------------------------------
update public.phare_sites set
    repo_github     = 'Jordan-Bourillot/suite-des-heros',
    netlify_site_id = 'f154d5c0-36fe-4430-b793-cfe15dfaf805',
    stack           = 'html',
    key_paths       = '["/"]'::jsonb,
    notes           = 'Source : landing-pack/public/'
where domain = 'productivite.triskell-studio.fr';

-- ---------------------------------------------------------------------
-- Bobeez
-- ---------------------------------------------------------------------
update public.phare_sites set
    repo_github     = 'Jordan-Bourillot/bobeez',
    netlify_site_id = '6885b3cd-daef-444c-ad42-2a8b7765f823',
    stack           = 'html',
    key_paths       = '["/"]'::jsonb,
    notes           = 'Source : landing/public/'
where domain = 'bobeez.triskell-studio.fr';

-- ---------------------------------------------------------------------
-- DéliNote
-- ---------------------------------------------------------------------
update public.phare_sites set
    repo_github     = 'Jordan-Bourillot/delinote',
    netlify_site_id = '9667bf9b-cd93-4e05-adcd-9725433f567a',
    stack           = 'html',
    key_paths       = '["/"]'::jsonb,
    notes           = 'Source : landing/public/'
where domain = 'delinote.triskell-studio.fr';

-- ---------------------------------------------------------------------
-- Outils Bâtiment (PWA, abonnement 9€/mois)
-- ---------------------------------------------------------------------
update public.phare_sites set
    repo_github     = '',                -- pas de .git/config détecté localement
    netlify_site_id = 'd48c059f-b03e-4f9d-8611-c46c7a040b8a',
    stack           = 'html',
    key_paths       = '["/"]'::jsonb,
    notes           = 'PWA, dossier `Triskell 3 - Outils Batiment/`. ' ||
                      'À renseigner repo_github si versionné sur GitHub.'
where domain = 'outils.triskell-studio.fr';

-- ---------------------------------------------------------------------
-- Eliks Studio (service growth operator)
-- ---------------------------------------------------------------------
update public.phare_sites set
    repo_github     = '',                -- pas de .git/config détecté
    netlify_site_id = 'f83a6764-12ab-4330-8cf5-b2949f24ec6a',
    stack           = 'html',
    key_paths       = '["/"]'::jsonb,
    notes           = 'Site service. À renseigner repo_github si applicable.'
where domain = 'eliks.triskell-studio.fr';

-- ---------------------------------------------------------------------
-- Obelisk (anciennement Le Dénicheur — repo "trove")
-- ---------------------------------------------------------------------
update public.phare_sites set
    repo_github     = 'Jordan-Bourillot/trove',
    netlify_site_id = 'dd180e21-519a-41b3-a6f5-21c2e6a30633',
    stack           = 'html',
    key_paths       = '["/"]'::jsonb,
    notes           = 'Repo "trove" (paths inchangés malgré rebrand Obelisk). ' ||
                      'Source : landing/public/'
where domain = 'obelisk.triskell-studio.fr';

-- ---------------------------------------------------------------------
-- Sites agence (sites.triskell-studio.fr — générateur de démo)
-- ---------------------------------------------------------------------
update public.phare_sites set
    repo_github     = '',
    netlify_site_id = '',                -- à compléter
    stack           = 'html',
    key_paths       = '["/"]'::jsonb,
    notes           = 'Générateur de démo personnalisée. À renseigner ' ||
                      'site_id Netlify et repo_github.'
where domain = 'sites.triskell-studio.fr';

-- ---------------------------------------------------------------------
-- AlphaBeast / AlphaCast / AlphaPitch
-- ---------------------------------------------------------------------
-- Découverte 2026-05-06 : ces 3 produits ne sont PAS sur des sous-domaines
-- séparés. Ils sont servis comme sous-routes du Lanceur (Table Ronde),
-- depuis `Triskell 0 - Lanceur/landing/{alphabeast,alphacast,alphapitch}/`.
--
-- → On désactive les entrées sous-domaine séparées (le Phare ne les
--   surveille pas) et on les couvre via le site `triskell-studio.fr` en
--   ajoutant leurs sous-routes aux `key_paths`.
--
-- Si plus tard Jordan crée de vrais sous-domaines, il suffira de :
--   update phare_sites set is_active = true,
--                          netlify_site_id = '...',
--                          repo_github = '...'
--   where domain = 'alphabeast.triskell-studio.fr';

update public.phare_sites set
    is_active = false,
    notes     = 'Servi en sous-route du Lanceur (Table Ronde) — pas de ' ||
                'sous-domaine séparé au 2026-05-06. Réactiver si DNS dédié.'
where domain in (
    'alphabeast.triskell-studio.fr',
    'alphacast.triskell-studio.fr',
    'alphapitch.triskell-studio.fr'
);

-- ---------------------------------------------------------------------
-- Lanceur Table Ronde — surveille la home + les pages produits
-- ---------------------------------------------------------------------
insert into public.phare_sites (
    name, domain, repo_github, netlify_site_id, stack, priority,
    key_paths, notes
) values (
    'Table Ronde (Lanceur catalogue)',
    'lanceur.triskell-studio.fr',
    'Jordan-Bourillot/triskell-table-ronde',
    'f21074d1-9cf1-46ca-93bd-88322f7ee4f4',
    'html', 88,
    '["/", "/alphabeast/", "/alphacast/", "/alphapitch/", "/bobeez/", "/delinote/", "/le-denicheur/", "/outils-pro/", "/pack-electricien-pro/", "/pirate-life-mail/", "/studio-pdf/", "/suite-des-heros/"]'::jsonb,
    'Catalogue principal qui héberge AUSSI les pages produit AlphaBeast, ' ||
    'AlphaCast, AlphaPitch en sous-routes. Vérifier le domaine réel.'
)
on conflict (domain) do update set
    repo_github     = excluded.repo_github,
    netlify_site_id = excluded.netlify_site_id,
    stack           = excluded.stack,
    priority        = excluded.priority,
    key_paths       = excluded.key_paths,
    notes           = excluded.notes,
    is_active       = true;

-- =====================================================================
-- Récap : ce qui reste à compléter manuellement par Jordan
-- =====================================================================
-- 1. `outils.triskell-studio.fr` : repo_github (si versionné)
-- 2. `eliks.triskell-studio.fr` : repo_github
-- 3. `sites.triskell-studio.fr` : repo_github + netlify_site_id
-- 4. Vérifier si `lanceur.triskell-studio.fr` est bien le bon hostname,
--    sinon ajuster (peut être l'apex `triskell-studio.fr` directement
--    selon la conf DNS Netlify)
-- =====================================================================
