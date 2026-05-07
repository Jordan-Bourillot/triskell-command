# Le Phare — module SEO autonome de Triskell Command

Outil SEO 100% IA multi-sites embarqué dans Triskell Command. Pilote 8 agents
Claude qui auditent, optimisent et enrichissent en continu tous les
sous-domaines `*.triskell-studio.fr`.

## Architecture

```
triskell_command/integrations/phare/
├── __init__.py        — exports + version
├── voice.py           — voix de marque Triskell + filtre anti-slop
├── repo.py            — DAO Supabase (tables phare_*)
├── crawler.py         — crawler web léger (requests + bs4)
├── pagespeed.py       — wrapper Google PageSpeed Insights
├── gsc.py             — wrapper Google Search Console (fallback gracieux)
├── dataforseo.py      — wrapper DataForSEO (fallback gracieux)
├── agents.py          — les 8 agents Claude
├── git_pipeline.py    — Git PR + Netlify preview + diff visuel
├── patcher.py         — convertit patches abstraits Optimiseur → patches fichier
├── orchestrator.py    — chef d'orchestre (run_audit, run_keywords, etc.)
├── scheduler.py       — daemon thread, cron logique
│
├── schema_architect.py — JSON-LD actif (Product/Article/FAQ/Org/LocalBiz)
├── ctr_hacker.py      — détecte high impressions / low CTR + réécrit
├── snippet_hunter.py  — featured snippets + People Also Ask capturables
├── geo_surveillant.py — mentions dans ChatGPT/Perplexity/AI Overview
├── cannibalization.py — détecte 2+ pages sur même KW (merge/redirect)
├── zombies.py         — pages sans trafic 6 mois (boost/redirect/del)
├── image_seo.py       — alts manquants, format, taille, lazy, srcset
├── refresh.py         — articles vieux qui décrochent (briefs refresh)
├── sitemap.py         — sitemap.xml + IndexNow (Bing/Yandex/Seznam)
├── competitors.py     — détection + suivi positions concurrents
├── rollback_watch.py  — auto-rollback si trafic baisse 14j post-merge
│
├── outreach.py        — démarchage backlinks via SMTP+IMAP, relances auto
├── ab_test.py         — A/B testing SEO scientifique (Mann-Whitney U)
├── brand_monitoring.py — surveillance des mentions Triskell sur le web
├── local_seo.py       — Google Business Profile (avis, complétude, posts)
├── programmatic.py    — pages calibrées en masse (SEO programmatique)
├── cro.py             — Microsoft Clarity (rage clicks, dead clicks, fixes)
├── algo_watch.py      — veille quotidienne de l'algo Google (RSS sources)
└── bulletin_pdf.py    — export PDF (ou HTML fallback) du bulletin mensuel
```

UI : `triskell_command/views/phare.py` (4 onglets dans Triskell Command).

## Les 8 agents

| Agent | Modèle | Rôle |
|---|---|---|
| `auditeur` | Sonnet 4.6 | Analyse crawl + Lighthouse + CWV |
| `veilleur` | Sonnet 4.6 | Stratégie mots-clés + cocon sémantique |
| `redacteur` | Sonnet 4.6 | Articles SEO complets |
| `optimiseur_onpage` | Sonnet 4.6 | Patches `<head>`/Hn/alt/JSON-LD |
| `tisseur` | Sonnet 4.6 | Maillage intra + inter-sites Triskell |
| `chasseur_backlinks` | Sonnet 4.6 | Opportunités backlinks (HARO, gap, mentions) |
| `analyste` | Sonnet 4.6 | Bulletin hebdo (clics, positions, ROI) |
| `chef_orchestre` | **Opus 4.7** | Plan stratégique mensuel (1×/mois) |

Chaque agent reçoit la voix Triskell en system prompt + un filtre anti-slop
(mots et structures bannis).

## Setup

### 1. Migrations Supabase (4 fichiers, dans l'ordre)

```sql
-- dans le SQL Editor Supabase
\i Triskell\ Command/supabase/06_phare.sql
\i Triskell\ Command/supabase/06b_phare_seed_real.sql
\i Triskell\ Command/supabase/06c_phare_advanced.sql
\i Triskell\ Command/supabase/06d_phare_pro.sql
```

- `06_phare.sql` : 8 tables core
- `06b_phare_seed_real.sql` : mapping réel des 13 sites (auto-détecté)
- `06c_phare_advanced.sql` : 10 tables (concurrents, snippets, GEO, images,
  cannibalisation, zombies, refresh, rollback, IndexNow)
- `06d_phare_pro.sql` : 11 tables (outreach, A/B test, brand monitoring,
  GBP, programmatic, CRO, algo watch)

- `06_phare.sql` : schéma complet (8 tables `phare_*` + RLS + seed minimal
  des 13 sites + entrée `shared_settings.phare_config`).
- `06b_phare_seed_real.sql` : auto-détection des `repo_github`,
  `netlify_site_id`, `stack` et `key_paths` réels depuis les `.git/config`
  et `.netlify/state.json` du poste de Jordan (Pack Élec, Studio PDF, Suite
  des Héros, Bobeez, DéliNote, Le Dénicheur/trove, Site officiel, Outils
  Bâtiment, Eliks, Lanceur Table Ronde). Désactive aussi les entrées
  `alphabeast/alphacast/alphapitch.triskell-studio.fr` qui sont en réalité
  servies en sous-routes du Lanceur, pas en sous-domaines séparés.

### 2. Configuration des credentials

Tous les credentials sont stockés dans `shared_settings.phare_config` (JSON
en base). Rien en local. Modifiables depuis l'UI Triskell Command (Réglages →
Le Phare) ou directement par SQL :

```sql
update public.shared_settings
set value = value || jsonb_build_object(
    'github_token', 'ghp_xxxxx',
    'netlify_token', 'nfp_xxxxx',
    'dataforseo_login', 'jordan@triskell-studio.fr',
    'dataforseo_password', 'xxxxx',
    'gsc_credentials_path', 'C:/path/to/service-account.json',
    'pagespeed_api_key', 'xxxxx'
)
where key = 'phare_config';
```

Cf. `.env.example` à la racine de Triskell Command pour la liste exhaustive
des variables et où les obtenir.

### 3. Dépendances optionnelles

Pour activer Google Search Console (sinon ignoré gracieusement) :

```bash
pip install google-auth google-api-python-client
```

Le reste tourne avec les dépendances déjà dans `requirements.txt`
(`requests`, `beautifulsoup4`, `lxml`, `Pillow`, `supabase`).

### 4. Démarrage

Le scheduler démarre automatiquement quand l'utilisateur ouvre l'onglet
"Le Phare" dans Triskell Command (cf. `views/phare.py.on_show`).

Pour le lancer en standalone :

```python
from triskell_command.integrations.phare import scheduler
from triskell_command.state import AppState
scheduler.start_worker(AppState())
```

## Cron logique du scheduler

Le worker tourne toutes les heures. À chaque tick il lit l'heure et le jour
et déclenche les missions appropriées :

| Mission | Cadence |
|---|---|
| Audit technique | Lundi 6h-22h, 1 site/heure (max 1/jour/site) |
| Veille mots-clés | Lundi & jeudi 7h |
| Optimisation on-page | Mardi/mercredi/vendredi 10h, 1 site/cycle |
| Maillage (Tisseur) | Lundi 9h |
| Bulletin Analyste | Tous les jours 8h, top 3 sites |
| Plan stratégique (Opus) | 1er du mois 9h |
| **Veille algo Google** | Tous les jours 6h |
| **A/B test mesures** | Tous les jours 7h |
| **Brand monitoring** | Mardi 9h, 1 site |
| **Outreach drafts** | Mercredi 9h, 1 site |
| **Outreach follow-ups** | Tous les jours 10h |
| **Local SEO (GBP)** | Jeudi 9h, sites avec place_id |
| **CRO Clarity** | Vendredi 9h, 1 site |
| **Bulletin PDF mensuel** | 1er du mois 10h |

Modifiable dans `phare_config.schedule_*_cron` (lecture future, pour l'instant
c'est codé en dur dans `scheduler._tick`).

## Pipeline Git → PR → Netlify → merge auto

1. Un agent (Optimiseur On-Page typiquement) génère des patches HTML
2. `git_pipeline.apply_and_open_pr` clone le repo, crée branche
   `phare/auto-YYYYMMDD-HHMM-<slug>`, applique, commit, push, ouvre PR
3. Netlify build le preview deploy de la branche
4. `git_pipeline.verify_pr` vérifie : Lighthouse delta ≥ -2 pts,
   diff visuel < `site.visual_diff_max_pct` (défaut 5%), aucun 4xx/5xx
   nouveau sur les `key_paths`
5. Si toutes les checks passent → merge auto. Sinon → bac à PRs (l'humain
   valide ou rejette en 1 clic dans l'UI)

Sécurités :
- `phare_sites.perf_min_score` : seuil Lighthouse perf en dessous duquel
  on ne merge jamais (défaut 70)
- `phare_sites.visual_diff_max_pct` : seuil de diff visuel (défaut 5%)
- `phare_sites.key_paths` : chemins critiques surveillés en diff visuel
  (défaut `["/"]`)
- Toute action est tracée dans `phare_actions` avec status (`draft`,
  `preview`, `merged`, `rejected`, `expired`)

## Coûts mensuels (régime de croisière, 13 sites)

| Poste | Coût |
|---|---|
| Anthropic API (Sonnet + Opus mensuel) | 150-280 € |
| DataForSEO | 30-60 € |
| Reste (Supabase, Netlify, GSC, PSI, GitHub) | 0 € marginal |
| **Total** | **180-350 €/mois** |

## Outillage CLI

Deux scripts à la racine de `scripts/` :

### `phare_doctor.py` — diagnostic complet

```bash
py -3 scripts/phare_doctor.py
```

Vérifie en cascade : imports, Supabase, tables, credentials posés, mapping
des sites, outils externes (git + réseau triskell-studio.fr), test d'appel
Anthropic réel. Sort un résumé `PRET` / `PAS PRET` avec les actions
concrètes à faire pour passer au vert. Code retour 0/1.

### `phare_smoke_test.py` — tests offline (sans credentials)

```bash
py -3 scripts/phare_smoke_test.py
```

14 tests qui ne dépendent ni de Supabase ni d'Anthropic ni des tokens
externes : imports, voix Triskell + détection slop, crawler distant,
patcher (transformation des patches abstraits en patches fichier),
registre des 8 agents, structure de l'overview, scheduler, vue UI,
routing, sidebar, présence des fichiers SQL. Idéal pour valider après
une modif de code avant de pousser.

## Roadmap

Voir `Triskell Studio/LE_PHARE_ROADMAP.md` à la racine du dossier Triskell
Studio. Phases 0-4 livrées en code (session autonome 2026-05-06), V2.1 en
backlog (Playwright pour diff pixel, Bing Webmaster, export PDF, A/B test).
