# Triskell Command — État du projet

**Dernière mise à jour** : 2026-05-07
**Version courante** : v0.6 (Le Phare niveau agence pro — 8 modules supplémentaires)
**Versions précédentes** :
  - v0.5 — Le Phare niveau agence senior (11 modules avancés)
  - v0.4 — Le Phare MVP (8 agents, pipeline Git→Netlify, scheduler)
  - v0.3 — Matinale + IMAP + auto-réponses + drip + funnel + clients
**Mainteneurs** : Jordan + Thomas Bourillot (Triskell Studio)
**Périmètre** : outil interne, jamais commercialisé.

---

## Vision en 3 lignes

Triskell Command est l'app desktop **interne** de Jordan + Thomas : un cockpit
unique qui chapeaute les outils Triskell (prospection multi-sources, IA, envoi
mail, publication réseaux). Elle réutilise Triskell Core comme bibliothèque
partagée. **Backend Supabase** depuis v0.2 → CRM, drafts, campagnes Convoi
synchronisés entre les deux machines. Pas de tunnel de vente, pas de
licensing : usage interne strict.

## Backend partagé (v0.2 — 2026-05-05)

Architecture spoke-and-hub :
```
[Le Dénicheur Jordan]   [Le Dénicheur Thomas]
        │                       │
        └─────► Supabase ◄──────┘    ← CRM + drafts + Convoi partagés
                  ▲     ▲
[Triskell Command Jordan]  [Triskell Command Thomas]
```

Tables Supabase :
- `01_schema.sql` : users, shared_settings, prospects, email_history,
  prospect_drafts, templates, convoy_campaigns, convoy_drafts, send_log
- `02_rls.sql` : Row-Level Security (tout user authentifié voit/écrit)
- `03_seed.sql` : Jordan + Thomas en seed
- `04_client_projects.sql` (v0.3) : kanban Clients (services post-paiement)
- `05_email_events.sql` (v0.3) : tracking pixel/click — *infra prête, activation
  côté SMTP à faire avec test E2E* — voir `landing/TRACKING_SETUP.md` côté Obelisk

Clés Jordan a posées :
- `users` (Jordan + Thomas)
- `shared_settings` (clés API IA + SMTP communes — décision Jordan, +
  `imap_config`, `reply_responder`, `drip_runner`, `post_sale`,
  `morning_digest_recipients` ajoutés en v0.3)

RLS : tout user authentifié voit/écrit tout. Pas de filtre par owner —
décision Jordan : "on partage tout".

Sync : `triskell_command/integrations/sync_poll.py` poll toutes les 15-30s
les tables clés. Polling plutôt que Realtime websocket pour la robustesse
côté Tk.

Fallback local : tous les modules continuent à marcher sans Supabase
(fichiers JSON), basculent automatiquement quand l'utilisateur est loggé
(`get_crm()` factory + `_supabase_client()` dans convoy_runner).

---

## Architecture (v0.3)

```
Triskell Studio/
├── Triskell Core/                    ← lib partagée (sources, IA, CRM)
└── Triskell Command/                 ← cockpit interne CustomTkinter
    ├── supabase/
    │   ├── 01_schema.sql / 02_rls.sql / 03_seed.sql
    │   ├── 04_client_projects.sql    ← v0.3, kanban services
    │   └── 05_email_events.sql       ← v0.3, tracking pixel (infra)
    ├── scripts/
    │   └── install_morning_digest_task.ps1   ← v0.3, cron 8h Windows
    └── triskell_command/
        ├── main.py                   ← TriskellCommandApp + routing
        ├── theme.py
        ├── state.py
        ├── views/
        │   ├── morning.py            ← v0.3, vue par défaut au boot
        │   ├── autopilot.py
        │   ├── convoy.py
        │   ├── drafts.py
        │   ├── replies.py            ← v0.3, IMAP + classif IA + draft suggéré
        │   ├── prospects.py / compose.py / templates.py / campaigns.py
        │   ├── publish.py
        │   ├── clients.py            ← v0.3, kanban 4 colonnes
        │   ├── funnel.py             ← v0.3, conversion par segment/période
        │   ├── dashboard.py / config.py
        ├── integrations/
        │   ├── sync_poll.py          ← polling Supabase (étendu v0.3)
        │   ├── replies_poller.py     ← v0.3, IMAP + classif IA → email_history
        │   ├── reply_responder.py    ← v0.3, draft suggéré + worker auto-envoi
        │   ├── drip_runner.py        ← v0.3, relances J+7/J+30
        │   ├── morning_digest.py     ← v0.3, agrégateur KPIs
        │   ├── morning_mailer.py     ← v0.3, envoi mail digest 8h
        │   ├── funnel_metrics.py     ← v0.3, agrégats Funnel
        │   ├── clients_repo.py       ← v0.3, CRUD client_projects
        │   ├── post_sale_runner.py   ← v0.3, cross-sell J+30 + NPS J+90
        │   ├── alphacast.py / sales_tunnel.py / teddy_mail.py
        │   ├── convoy_parser.py / convoy_ai.py / convoy_runner.py
        └── widgets/
            ├── sidebar.py            ← nav 5 sections (MATIN, AUTO, OUTILS,
            │                            LIVRAISON, ANALYSE) + footer SYSTÈME
            │                            (Tuto / Aide / Réglages)
            ├── components.py         ← Card / Button / Pill / Toast
            ├── icons.py
            ├── tutorial_dialog.py         ← v0.3, visite guidée 12 étapes
            │                                  auto au 1er boot + 3 boutons
            ├── reply_edit_dialog.py       ← v0.3
            ├── reply_settings_dialog.py   ← v0.3, toggle modes par catégorie
            └── client_dialog.py           ← v0.3, créer/éditer projet client
```

---

## État courant — v0.3

### Vues livrées

| Vue | État | Source / fonction |
|---|---|---|
| 📊 Matinale | ✅ **v0.3** | Vue par défaut au boot ; KPIs J-1, file de travail, anomalies |
| 🚀 Auto-pilote | ✅ stable | Sirene / Google Maps |
| ✉ Le Convoi | ✅ livré 2026-05-05 | Fichier importé (PDF/Word/Excel/Image/Texte) |
| ✅ Drafts à valider | ✅ stable | drafts produits par Auto-pilote/Convoi/Drip |
| 📬 Réponses entrantes | ✅ **v0.3** | IMAP polling 5 min + classif IA + draft suggéré |
| 🔎 Prospects / 💬 Compose / 📄 Templates | ✅ stables | manuelles |
| ✉ Campaigns / 📡 Publish | ✅ stables | — |
| 🛠 Clients (kanban) | ✅ **v0.3** | Briefing → En cours → Livré → Clôturé |
| 📈 Funnel | ✅ **v0.3** | Prospects → Sent → Replies → Interested → Won, par segment/période |
| 📊 Dashboard | ✅ stable | — |
| 📡 Le Phare | ✅ **v0.4** | Agence SEO autonome multi-sites (4 onglets : Écosystème / Site / Bac à PRs / Bulletins). 8 agents Claude. Pipeline Git→Netlify→merge auto. |
| ⚙ Réglages | ✅ stable | — |

### Onboarding & tuto

- **Onboarding** existant (création compte Supabase + clés API) — `widgets/onboarding.py`.
- **Tuto v0.3** (nouveau) — `widgets/tutorial_dialog.py` : visite guidée
  12 étapes, s'affiche auto au 1er boot après onboarding (flag
  `ui.tutorial_v3_done` dans settings.json), réouvrable à tout moment via :
    - Sidebar SYSTÈME → Tuto
    - Vue Matinale → bouton "Revoir le tuto"
    - Vue Réglages → bouton "Revoir le tuto"
  Chaque étape a un bouton "Aller voir : la vue X" qui ouvre la vue concernée
  pour démo en contexte (la modale reste visible au-dessus).

### Workers background (démarrés au login Supabase)

| Worker | Cycle | Rôle |
|---|---|---|
| `SyncPoller` | 15-30 s | Polling Supabase (prospects, drafts, email_history…) |
| `RepliesPoller` (v0.3) | 5 min | Poll IMAP, classifie via IA, écrit `email_history.kind=reply_received` |
| `ReplyResponder` (v0.3) | 60 s | Envoie les drafts pending dont send_after est passé |
| `DripRunner` (v0.3) | 1 h | Génère relances J+7/J+30 sur envois sans réponse |
| `PostSaleRunner` (v0.3) | 1 h | Génère cross-sell J+30 + NPS J+90 sur clients livrés |
| `PhareScheduler` (v0.4) | 1 h | Audits hebdo, veille mots-clés, maillage, bulletins, plan stratégique mensuel |

Tous idempotents, best-effort, no-op si Supabase/SMTP/IA non configurés.

### Le Phare — détail (v0.4)

Module SEO autonome multi-sites livré 2026-05-06.

- **Schéma Supabase** : `supabase/06_phare.sql` (8 tables `phare_*` + RLS +
  seed des 13 sites Triskell).
- **Backend** : `triskell_command/integrations/phare/` (12 fichiers).
- **UI** : `triskell_command/views/phare.py` (4 onglets internes).
- **8 agents Claude** : auditeur, veilleur, redacteur, optimiseur_onpage,
  tisseur, chasseur_backlinks, analyste (Sonnet 4.6), chef_orchestre
  (Opus 4.7, mensuel uniquement).
- **Pipeline** : crawler interne → Lighthouse PSI → Auditeur → patches →
  Git PR sur branche `phare/auto-*` → preview Netlify → diff visuel +
  Lighthouse delta → merge auto si verts, sinon bac à PRs (validation
  1-clic).
- **Scheduler** : worker thread daemon (pattern aligné DripRunner), cron
  logique horaire (audit hebdo lundi, veille KW lundi+jeudi, bulletin
  quotidien 8h, plan stratégique 1er du mois 9h).
- **Garde-fous** : seuils Lighthouse perf et diff visuel par site
  (`phare_sites.perf_min_score`, `visual_diff_max_pct`), liste blanche
  fichiers modifiables par agent (`<head>`, Hn, alt, JSON-LD uniquement),
  rollback via "Rejeter" dans le bac.
- **Voix Triskell** + **filtre anti-slop** câblés en system prompt
  (`integrations/phare/voice.py`).
- **Doc** : `integrations/phare/README.md` + `.env.phare.example` à la
  racine de Command + roadmap dans `Triskell Studio/LE_PHARE_ROADMAP.md`.
- **Outillage CLI** : `scripts/phare_doctor.py` (diagnostic complet
  Supabase/credentials/réseau/Anthropic) + `scripts/phare_smoke_test.py`
  (14 tests offline sans credentials, validés 14/14 verts).
- **Auto-détection mapping** : `supabase/06b_phare_seed_real.sql` pré-remplit
  `repo_github`, `netlify_site_id`, `stack` et `key_paths` réels pour 10 des
  13 sites (extraits des `.git/config` et `.netlify/state.json` locaux), et
  désactive les entrées AlphaBeast/AlphaCast/AlphaPitch (servies en
  sous-routes du Lanceur, pas en sous-domaines séparés).
- **Branchement Matinale** : si Le Phare a >=1 PR à valider ou >=5 recos
  en attente, un bloc "Visibilité" apparaît dans la Matinale avec un CTA
  "Ouvrir Le Phare". Sinon rien (pattern non-anxiogène cohérent avec le
  reste de la Matinale).

### Le Phare v0.5 — Niveau agence senior (livré 2026-05-07)

11 modules avancés ajoutés en plus du MVP v0.4 :

| Module | Rôle |
|---|---|
| `schema_architect` | Génère JSON-LD actif (Product, Article, FAQPage, Organization, LocalBusiness, BreadcrumbList) |
| `ctr_hacker` | Détecte high impressions / low CTR (vs courbe attendue par position) et réécrit title+meta |
| `snippet_hunter` | Capture les featured snippets et People Also Ask sur les KW où on est dans le top 10 |
| `geo_surveillant` | ⚰️ RETIRÉ du scheduler le 03/07/2026 (mesure fantôme : table `phare_geo_mentions` jamais lue) — la mesure « les IA me citent-elles ? » vit dans l'écran GEO, mesure unique |
| `cannibalization` | Détecte 2+ pages qui rankent sur le même KW, propose merge/redirect/différenciation |
| `zombies` | Pages sans clic depuis 6 mois, propose boost/redirect/delete/noindex |
| `image_seo` | Audit images (alt, format, taille, lazy, srcset), génération auto des alts manquants |
| `refresh` | Articles vieux qui décrochent (vs pic 12 mois), brief de rafraîchissement |
| `sitemap` | Sitemap.xml + ping IndexNow (Bing/Yandex/Seznam/Naver) |
| `competitors` | Auto-discovery des 5 concurrents directs + suivi positions hebdo + alerte si gain rapide |
| `rollback_watch` | Surveille chaque PR mergée pendant 14j, rollback auto si trafic chute >15% |

Ajouts au schéma Supabase : `06c_phare_advanced.sql` (10 tables nouvelles).

Ajouts UI :
- Nouvel onglet "Avancé" (sélecteur de site + grille de 9 cartes mission
  avec descriptions vulgarisées + bouton "Lancer")
- Bouton "CTR booster" ajouté dans la liste des missions du focus site

Ajouts scheduler (cron logique horaire) :
- Mardi 11h : CTR booster (1 site)
- Mercredi 11h : Snippet hunt (1 site)
- ~~Jeudi 11h : GEO check (1 site)~~ (retiré le 03/07/2026 — mesure fantôme, voir tableau des modules)
- Vendredi 11h : Cannibalisation + Zombies (1 site, en cascade)
- Samedi 9h : Image SEO (1 site)
- Dimanche 9h : Refresh content (1 site)
- Tous les jours 12h : Suivi concurrents (top 3 sites)
- Tous les jours 13h : Rollback check (toutes les watches dues)
- Lundi 14h : Sitemap + IndexNow (top 3 sites)

Smoke test étendu à 21 tests, validés 21/21 verts au 2026-05-07.

### Le Phare v0.6 — Niveau agence pro (livré 2026-05-07)

8 modules pro ajoutés en plus de v0.5 :

| Module | Rôle |
|---|---|
| `outreach` | Démarchage backlinks via SMTP, génération mails personnalisés par LLM (4 templates), envoi auto si activé, relances J+7/J+14, suivi des réponses |
| `ab_test` | A/B testing SEO scientifique (lots de pages), mesures GSC quotidiennes, test statistique Mann-Whitney U sans scipy, déclaration gagnant à p<0.05 |
| `brand_monitoring` | Scan hebdo des mentions Triskell sur le web (DataForSEO + Custom Search fallback), détection des mentions sans lien → opportunités outreach |
| `local_seo` | Google Business Profile via Places API : score de complétude, suggestions, avis nouveaux + réponses pré-rédigées par LLM |
| `programmatic` | Génération SEO programmatique : template + variables → N pages calibrées, qualité scorée, validation manuelle avant push Git massif |
| `cro` | Microsoft Clarity API (heatmaps, rage clicks, dead clicks, quick backs, scroll depth) → fixes UX concrets par LLM |
| `algo_watch` | Veille quotidienne algo Google : RSS Search Engine Land, Search Engine Roundtable, Mozcast, Search Liaison, résumé Claude Haiku, sévérité info/warning/critical |
| `bulletin_pdf` | Export mensuel PDF (reportlab) ou HTML fallback, mise en page Triskell, KPI + bulletins + plan stratégique |

Schéma Supabase étendu : `06d_phare_pro.sql` (11 tables nouvelles).

Ajouts UI : 6 nouvelles cartes mission dans l'onglet "Avancé" (Démarchage
backlinks, Mentions Triskell, Fiche Google, CRO Clarity, Veille algo,
Bulletin PDF).

Ajouts scheduler (cron logique horaire) :
- Tous les jours 6h : Veille algo Google
- Tous les jours 7h : A/B test mesures
- Tous les jours 10h : Outreach follow-ups
- Mardi 9h : Brand monitoring (1 site)
- Mercredi 9h : Outreach drafts (1 site)
- Jeudi 9h : Local SEO (sites avec place_id)
- Vendredi 9h : CRO Clarity (1 site)
- 1er du mois 10h : Bulletin PDF du mois précédent

Smoke test étendu à **28 tests, validés 28/28 verts** au 2026-05-07.

Coût mensuel régime de croisière complet : **~200-365 €/mois** pour
13 sites (vs 20-40 k€/mois en agence externe équivalente).

Coût mensuel régime de croisière : 180-350 €/mois pour 13 sites
(vs 20-40 k€/mois en agence externe).

### Le Convoi — détail des features (v0.1)

- **Import** : PDF (pypdf), Word (python-docx ou XML pur), Excel (openpyxl),
  CSV/TSV (csv stdlib), images (pytesseract optionnel), texte brut.
  Dégradation gracieuse : si une dépendance manque, message d'erreur clair
  avec la commande pip pour l'installer.
- **Drag & drop** : actif si `tkinterdnd2` installé, sinon « Parcourir… ».
- **Extraction structurée** : pré-extraction regex (emails / téléphones /
  URLs) puis appel IA qui retourne un JSON `{"prospects": [...]}`.
  Champs : raison_sociale, prénom, nom, email, telephone, site_web, adresse,
  ville, code_postal, secteur, notes.
- **Tableau éditable** : chaque cellule modifiable, lignes en jaune si
  incomplètes, en rouge si email manquant.
- **Catalogue d'offres** : éditeur multi-ligne (1 offre par ligne, pipe `|`
  comme séparateur). Matching mots-clés → secteur du prospect → choix de
  l'offre la plus adaptée. Catalogue par défaut pré-rempli (Pack Élec /
  Triskell Studio sites / Le Dénicheur).
- **Génération message** : `convoy_ai.generate_message()` reprend le brief
  utilisateur + le contexte prospect + l'offre sélectionnée → IA → JSON
  `{"subject": "...", "body": "..."}`.
- **Modes d'envoi** : `validation` (drafts à valider un par un) ou `auto`
  (tout passe en `approved` en lot puis envoi).
- **Cap + délai** : `daily_cap` (par défaut depuis settings) + `delay_seconds`
  (mini 5s, défaut 60s) entre 2 envois.
- **Persistance** : 1 fichier JSON par campagne dans
  `~/.triskell-command/convoy/campaigns/`. `send_log.json` pour le quota
  quotidien (séparé du Dénicheur pour ne pas mélanger les compteurs).
- **Statuts drafts** : `pending` → `approved` → `sent` (ou `failed` /
  `rejected`).

---

## Configuration utilisateur (Jordan)

Fichier : `~/.triskell-command/settings.json` (généré par AppState au
premier lancement, voir `state.py:DEFAULT_SETTINGS`).

Sections : `appearance_mode`, `ai` (provider + clés), `outreach` (SMTP +
IMAP + cap), `sources` (YouTube/Twitch/Maps), `social` (Réseaux), `ui`.

Le Convoi lit les mêmes clés `ai` et `outreach` que les autres vues —
pas de config séparée à maintenir.

---

## Décisions structurantes prises

1. **Stack CustomTkinter (pas React)** — cohérent avec Sales Tunnel,
   AlphaBeast et le reste de l'écosystème desktop Triskell. Le Dénicheur
   utilise pywebview (HTML/JS) car c'était un héritage, mais Triskell
   Command standardise sur CustomTkinter.
2. **Vues lazy-instanciées** — les vues sont créées à la première
   activation, pas toutes au boot (cf. `main.py:_get_view`).
3. **Le Convoi vs Auto-pilote** — Auto-pilote pioche dans Sirene/Maps
   (sources publiques) ; Le Convoi traite une liste fournie par
   l'utilisateur (chantiers gagnés, leads tiers). Les deux écrivent dans
   des storages distincts pour ne pas se mélanger.
4. **Pas de CRM unifié pour Le Convoi** — chaque campagne est un fichier
   JSON autonome. Le Dénicheur a son propre CRM ; Triskell Core a aussi
   le sien. Le Convoi est volontairement plus léger pour rester
   lisible et débuggable manuellement.
5. **Dépendances optionnelles** pour l'extraction de fichiers : openpyxl,
   python-docx, pypdf, pytesseract, tkinterdnd2 — toutes optionnelles
   avec fallback gracieux. Permet de builder l'app sans tirer 100 Mo de
   deps si l'utilisateur ne charge que des CSV.

---

## Chantiers ouverts

### 🟢 Priorité 3 — Le Convoi : tests live

- Importer un PDF de chantiers réels et vérifier l'extraction.
- Tester le flow validation/envoi avec une liste de 5 prospects.
- Vérifier que le SMTP IONOS de Jordan envoie bien.

### 🟢 Priorité 4 — Le Convoi : enrichissements possibles

- **OCR** : intégrer Tesseract proprement (détection auto du chemin).
- **Drag & drop** : embarquer tkinterdnd2 dans le PyInstaller spec.
- **Templates Convoi** : permettre de sauver/charger un trio
  (catalogue + brief + paramètres d'envoi) pour réutilisation.
- **Sync vers le CRM Triskell Core** : remonter les prospects envoyés
  pour suivi des réponses IMAP.
- **Planification** : aujourd'hui le champ `schedule_at` est lu mais le
  scheduler n'est pas branché. À implémenter quand utile.

---

## Pièges connus / lessons learned

- **Imports lazy de Triskell Core** : on injecte le path au boot dans
  `main.py`. Ne pas importer `triskell_core.*` au top-level d'un module
  Triskell Command — ça casse en dev quand le path n'est pas encore en
  place. Toujours importer à l'intérieur des fonctions.
- **Encodage Windows** : `state.py` écrit en UTF-8 atomique (`.tmp` +
  replace). Reproduire ce pattern pour tout fichier user-facing.
- **CustomTkinter n'a pas de TableView** : pour Le Convoi, on a empilé
  des `CTkEntry` dans des `CTkFrame` pour simuler un tableau éditable.
  Si on a besoin d'un vrai data grid (tri, scroll horizontal),
  considérer `tksheet`.

---

## Comment reprendre cette session

```
1. Lis ce fichier en entier
2. Lis le PROJECT_STATE.md du Dénicheur pour comprendre le pipeline frère
3. Vérifie quelles dépendances sont installées :
   pip list | findstr -i "openpyxl docx pypdf tkinterdnd2"
4. Lance l'app : python run.py
5. Si tu touches Le Convoi : les fichiers à connaître sont
   triskell_command/views/convoy.py
   triskell_command/integrations/convoy_*.py
```

---

## Liens utiles

- Triskell Core : `../Triskell Core/`
- Le Dénicheur (référence pipeline frère) : `../Triskell 6 - Le Denicheur/`
- Catalogue produits Triskell : `../Triskell 0 - Lanceur/apps.json`
