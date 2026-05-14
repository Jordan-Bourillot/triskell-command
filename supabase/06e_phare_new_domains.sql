-- =====================================================================
-- Triskell Command — Migration 06e : Le Phare, bascule sur domaines apex .fr
-- =====================================================================
-- Demandé par Jordan le 2026-05-13.
--
-- Règle : les **sites canoniques sont les apex .fr**, pas les sous-domaines.
-- Les sous-domaines *.triskell-studio.fr historiques restent actifs le
-- temps de la bascule DNS, mais leur rôle final sera "redirection 301
-- vers l'apex .fr". Jordan branchera les redirections au fur et à mesure.
--
-- 7 sites canoniques apex .fr à monitorer (domaines IONOS confirmés
-- par capture Jordan le 2026-05-13) :
--   - lagriffe-studio.fr     (nouveau, repo triskell-site-officiel)
--   - studio-wow.fr          (nouveau, repo studio-wow)
--   - rankus-studio.fr       (nouveau, repo rankus-studio)
--   - artisia-studio.fr      (nouveau, repo artisia-studio)
--   - alphacast.fr           (nouveau, sort des sous-routes du Lanceur)
--   - delinote.fr            (canonique remplaçant delinote.triskell-studio.fr)
--   - eliks-studio.fr        (canonique remplaçant eliks.triskell-studio.fr)
--
-- NB : obelisk.fr cité initialement par Jordan mais ABSENT de la
-- liste IONOS — domaine non acheté. À reconfirmer avant de l'ajouter.
--
-- Cas particulier : studio-triskell.fr → redirection vers triskell-studio.fr
-- (l'apex Triskell reste triskell-studio.fr, pas l'inverse — confirmé Jordan).
--
-- Idempotent : `on conflict (domain) do nothing` côté INSERT.
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. Ajout des 7 sites canoniques apex .fr
-- ---------------------------------------------------------------------
insert into public.phare_sites (
    name, domain, repo_github, stack, priority, key_paths, notes
) values
    (
        'Lagriffe Studio',
        'lagriffe-studio.fr',
        'Jordan-Bourillot/triskell-site-officiel',
        'html', 85,
        '["/"]'::jsonb,
        'Marque "Sites" Triskell. Tunnel site, SEO 149€/mois HT en upsell. '
        'Branchement DNS depuis sites.triskell-studio.fr en cours.'
    ),
    (
        'Studio WoW',
        'studio-wow.fr',
        'Jordan-Bourillot/studio-wow',
        'html', 85,
        '["/"]'::jsonb,
        'Marque premium. Site Signature 990€ HT + 149€/mois, '
        'Site Excellence 1990€ HT + 199€/mois. SEO upsell 490 ou 990€/mois HT. '
        'Pipeline avec validation humaine obligatoire (coût ~15€/génération).'
    ),
    (
        'RankUs Studio',
        'rankus-studio.fr',
        'Jordan-Bourillot/rankus-studio',
        'html', 90,
        '["/"]'::jsonb,
        'Marque qui vend le SEO. 490€ HT one-shot + 49,97€ HT/mois ; '
        'SEO upsell 199 ou 399€/mois. Branchement DNS depuis '
        'rankus.triskell-studio.fr en cours.'
    ),
    (
        'Artisia Studio',
        'artisia-studio.fr',
        'Jordan-Bourillot/artisia-studio',
        'html', 70,
        '["/"]'::jsonb,
        'Site vitrine — outils numériques sur-mesure. Branchement DNS '
        'sur artisia-studio.fr en cours. Netlify_site_id à renseigner.'
    ),
    (
        'AlphaCast',
        'alphacast.fr',
        'Jordan-Bourillot/triskell-reseaux',
        'html', 75,
        '["/"]'::jsonb,
        'Publication multi-réseaux. Servi jusque-là en sous-route '
        '/alphacast/ du Lanceur Table Ronde — sort en site indépendant '
        'avec l''achat de l''apex .fr. Repo triskell-reseaux ("Sera '
        'AlphaCast en Phase 2 du rebrand"). Netlify_site_id à renseigner.'
    ),
    (
        'DéliNote',
        'delinote.fr',
        'Jordan-Bourillot/delinote',
        'html', 65,
        '["/"]'::jsonb,
        'App local-first note-taking. Domaine canonique apex .fr. '
        'Le sous-domaine delinote.triskell-studio.fr basculera en 301 '
        'vers cet apex quand Jordan branchera la redirection.'
    ),
    (
        'Eliks Studio',
        'eliks-studio.fr',
        'Jordan-Bourillot/eliks-studio',
        'html', 60,
        '["/"]'::jsonb,
        'Service growth operator. Domaine canonique apex .fr. '
        'Le sous-domaine eliks.triskell-studio.fr basculera en 301 '
        'vers cet apex quand Jordan branchera la redirection.'
    )
on conflict (domain) do nothing;

-- ---------------------------------------------------------------------
-- 2. Sous-domaines historiques : passage en statut "transitoire"
--    Ils restent actifs (Jordan ne veut pas les désactiver tant que la
--    redirection DNS n'est pas branchée), mais on dépriorise et on note
--    leur statut non-canonique pour que Le Phare ne traite plus leurs
--    audits comme prioritaires.
-- ---------------------------------------------------------------------
update public.phare_sites
   set priority = 30,
       notes = 'Sous-domaine historique non-canonique. Sera redirigé en '
            || '301 vers delinote.fr. En coexistence temporaire.'
 where domain = 'delinote.triskell-studio.fr';

update public.phare_sites
   set priority = 30,
       repo_github = 'Jordan-Bourillot/eliks-studio',
       notes = 'Sous-domaine historique non-canonique. Sera redirigé en '
            || '301 vers eliks-studio.fr. En coexistence temporaire.'
 where domain = 'eliks.triskell-studio.fr';

-- ---------------------------------------------------------------------
-- 3. Alias DNS conservé : studio-triskell.fr → triskell-studio.fr
--    (Jordan a confirmé : triskell-studio.fr reste l'apex canonique,
--     studio-triskell.fr est un domaine de redirection acheté en plus.)
-- ---------------------------------------------------------------------
update public.phare_sites
   set notes = trim(both ' ' from coalesce(notes, '') ||
               ' [Alias DNS : studio-triskell.fr → 301 vers cet apex.]')
 where domain = 'triskell-studio.fr'
   and notes not like '%studio-triskell.fr%';

-- =====================================================================
-- À compléter quand les redirections seront branchées
-- =====================================================================
-- 1. netlify_site_id pour les 7 nouveaux apex (un seul Netlify build par
--    site, qui sert à la fois l'apex .fr et l'ancien sous-domaine via
--    custom domains pendant la transition).
-- 2. Une fois la 301 active sur un sous-domaine, passer son
--    `is_active = false` pour stopper les audits doublons.
-- =====================================================================
