# Audit UX — Triskell Command v0.4

**Date** : 2026-05-08
**Auteur** : audit externe sur lecture de la codebase v0.4 (commit `6e80d2a`)
**Périmètre** : 14 vues, sidebar, status bar, worker pulse, FABs, design system v2.
**Lecture préalable** : `docs/DESIGN.md` (manifeste design 2026-05-07) et `docs/PATCHES.md` (7 patches Matinale/Phare). Ce document **complète** les deux ; il ne les répète pas.

---

## 1. Synthèse en une page

La v0.4 est un cockpit nettement plus mature que ce que la documentation grand public laisse penser. Six runners, deux FAB, trois thèmes, chat 1:1 avec notifs Windows, veille Claude proactive, pulse-bus pour observabilité asynchrone, design system v2 codé. Le manifeste design existe, les patches concrets aussi.

Le problème UX dominant n'est plus *« qu'est-ce qu'il manque ? »* mais *« pourquoi ce qui existe n'est pas adopté ? »* — `tokens_v2.py` est codé depuis le 7 mai mais seuls deux fichiers l'importent en dehors de lui-même. C'est le **gap d'adoption**, pas le gap de conception, qui plafonne aujourd'hui.

Trois autres points non couverts par DESIGN.md méritent attention :
- **Sidebar à 16 items**, organisée par mode d'exécution (« L'app travaille pour toi » vs « À la main ») au lieu de par mission utilisateur.
- **Pas de palette de commandes** type `Ctrl+K` malgré la profusion de vues et entités.
- **Status bar haute** inchangée depuis v0.1 : redondante par endroits avec WorkerPulse, et avec la zone hero des vues.

Ces trois points ne sont pas adressés dans le manifeste DESIGN.md actuel — c'est l'angle complémentaire de cet audit.

---

## 2. État d'adoption du design system v2

### 2.1 Le constat brut

`tokens_v2.py` (élévation, motion, density, ttype, z, widths, heights, borders) et `widgets/components_pro.py` (`KpiHero`, `LogRow`, `DrawerRight`, `Disclosure`) sont des fondations propres et bien pensées. Mais l'audit grep révèle une adoption confidentielle.

| Module | Importé par |
|---|---|
| `tokens_v2.py` | `components_pro.py`, `worker_pulse.py` (et lui-même) |
| `components_pro.py` | `views/phare.py` (uniquement `HeroQuestion`) |

→ **Aucune** des 13 autres vues (`morning`, `autopilot`, `convoy`, `drafts`, `replies`, `prospects`, `compose`, `templates`, `campaigns`, `publish`, `clients`, `funnel`, `dashboard`) n'utilise `tokens_v2`. Toutes codent encore en dur via `theme.py` + `widgets/components.py` (système v1).

### 2.2 Conséquences observables

- **Densité incohérente.** `tokens_v2.density_for("phare")` retourne COMPACT, mais `phare.py` ne l'utilise pas — il code ses paddings à la main. Idem pour Funnel, Dashboard, Prospects, Campaigns que `density_for()` classe en COMPACT.
- **Typographie incohérente.** `ttype.KPI_HERO`, `ttype.KPI_LARGE`, `ttype.LOG`, `ttype.SECTION_CAP` sont définis et excellents, mais réinventés en dur dans chaque vue (`(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_TINY, "bold")`).
- **Élévation non utilisée.** `surface_for(level)` propose 4 niveaux d'élévation propres ; aucune vue ne les invoque. La hiérarchie visuelle dépend de fragmentations locales.
- **Z-axis logique non utilisé.** `tokens_v2.z` propose `BASE/CONTENT/POPOVER/DRAWER/MODAL/TOAST/TOOLTIP` ; les modales et toasts existants n'y font pas référence.

### 2.3 Diagnostic

Les fondations v2 ont été livrées sans **migration coordonnée**. Le commit `267483c (feat(design): worker pulse + design system v1)` du 7 mai a posé les briques, mais les vues n'ont pas été migrées dans le même geste. Plus le temps passe, plus le coût de migration croît (chaque nouvelle vue qui code en theme.py augmente la dette).

**Recommandation** : voir [03_ROADMAP §3](03_ROADMAP.md), Sprint 1.

---

## 3. Forces non négociables (à préserver explicitement)

Tout audit qui propose des changements doit aussi nommer ce qu'il **ne touche pas**. Ces éléments sont des réussites identitaires de la v0.4 :

- **MorningView** (`views/morning.py`). Une seule priorité du jour mise en avant, blocs « À corriger » et « Phare » conditionnels qui n'apparaissent que s'ils ont du sens, microcopy chaleureuse contextuelle (« Tu as une vraie occasion ce matin », cf. PATCHES M3). Modèle à imiter pour les autres vues.
- **WorkerPulse** (`widgets/worker_pulse.py`). Pulsation système 6 LED + dernière activité + Supabase + horloge. Excellent geste de cockpit. Auto-decay active→idle après 4 s anti-race.
- **Trois thèmes** (light Apple-clear / mid graphite / dark cockpit nuit) avec cycle Ctrl+T. Rare et juste.
- **FABs Claude + Thomas** flottants par-dessus tout, indépendants des vues. Notifs Windows (FlashWindowEx + winsound). Toast cliquable in-app.
- **Microcopy revue** : « Préparation en cours » remplace « Allumage des chandelles ». Ton tenu.
- **Sectioning sidebar avec verbes parlés** (« L'APP TRAVAILLE POUR TOI ») plutôt que jargon produit. C'est une force, même si le découpage reste à challenger (cf. §4 et 01_NAVIGATION.md).
- **Pulse-bus** (`integrations/pulse_bus.py`) : abstraction propre pour l'observabilité asynchrone. Permet aux 6 runners de remonter leur état sans coupler à la UI.
- **Manifeste DESIGN.md** comme source de vérité écrite. Rare à ce niveau de précision dans un projet solo.

---

## 4. Plafonds non couverts par DESIGN.md

Le manifeste DESIGN.md identifie 5 plafonds (workers invisibles ✓ résolu, densité Phare, icons hétérogènes, rituel matinal sous-exploité, or sur-utilisé). Les 3 angles suivants n'y figurent pas et méritent d'être ajoutés.

### 4.1 Sidebar par mode d'exécution

La sidebar a 16 items en 6 sections + 3 footer. Deux sections regroupent par **mode d'exécution** : *L'APP TRAVAILLE POUR TOI* (autopilot, convoy, drafts, replies) vs *À LA MAIN* (prospects, compose, templates, campaigns, publish).

L'utilisatrice qui pense « je veux contacter des paysagistes ce matin » doit savoir d'avance si elle passera par le mode auto ou manuel pour choisir la bonne section. C'est un découpage qui force à connaître l'implémentation pour naviguer.

**Une alternative existe** : regrouper par mission (*Acquérir / Communiquer / Livrer / Mesurer / Optimiser*) avec le mode auto/manuel comme **option à l'intérieur** de chaque mission. Détaillé dans [01_NAVIGATION.md](01_NAVIGATION.md).

### 4.2 Pas de palette de commandes

Avec 14 vues, des dizaines de prospects, des campagnes, des drafts, des modèles, des sites Phare : l'unique navigation visible est la sidebar. Les raccourcis `Ctrl+1..9` existent mais sont mémoriels.

Une palette `Ctrl+K` qui fuzzy-matche **vues + actions globales + entités** (prospect précis, site Phare précis, campagne précise) ferait gagner secondes par secondes plusieurs fois par jour. Standard chez Linear, Raycast, Cmd+K Cloud. Coût d'implémentation Tk : modéré (Toplevel + filtre listbox). Bénéfice quotidien : élevé.

### 4.3 Status bar haute / WorkerPulse / Hero matinal — qui dit quoi ?

Trois zones d'information système coexistent :

| Zone | Contenu actuel | Question à laquelle elle répond |
|---|---|---|
| Status bar haute | IA ok / Mail ok / Pilote / N drafts / N prospects / N envoyés / profil | « Le cockpit est-il prêt ? » |
| Hero Matinale | Salut + prio du jour + Hier 3 KPIs + Aujourd'hui 2 KPIs | « Que dois-je faire aujourd'hui ? » |
| WorkerPulse bas | 6 LED workers + dernière activité + Supabase + horloge | « Les engrenages tournent-ils ? » |

C'est cohérent **en théorie** (cf. DESIGN.md axe A), mais en pratique la status bar haute affiche aussi les KPIs (« 3 brouillons à valider », « 1248 prospects », « 12 envoyés aujourd'hui »). Ces chiffres sont **redondants** avec la Matinale (qui les présente mieux) et **bruyants** quand on est dans n'importe quelle autre vue.

**Proposition** : la status bar haute n'affiche plus que la **configuration** (IA/Mail/Pilote + profil). Les KPIs migrent intégralement vers la Matinale. La status bar haute devient symétrique du WorkerPulse : statique en haut, dynamique en bas, aucune redondance avec les vues.

---

## 5. Audit vue par vue — état d'application des principes DESIGN.md

Légende : ✅ aligné · 🟡 partiel · 🔴 hors-doctrine · ⏳ pas évalué (lecture partielle).

| Vue | ViewHeader | EmptyState | tokens_v2 | components_pro | Filet accent | Or limité | Densité conforme |
|---|---|---|---|---|---|---|---|
| morning | ✅ (custom hero) | ✅ | 🔴 | 🔴 | ✅ (or rituel) | ✅ | n/a (rituel) |
| autopilot | ⏳ | ⏳ | 🔴 | 🔴 | ⏳ | ⏳ | ⏳ |
| convoy | ⏳ | ⏳ | 🔴 | 🔴 | ⏳ | ⏳ | ⏳ |
| drafts | ⏳ | ⏳ | 🔴 | 🔴 | ⏳ | ⏳ | ⏳ |
| replies | ✅ | ⏳ | 🔴 | 🔴 | ✅ | ✅ | ⏳ |
| prospects | ⏳ | ⏳ | 🔴 | 🔴 | ⏳ | ⏳ | 🔴 (devrait être COMPACT) |
| compose | ⏳ | ⏳ | 🔴 | 🔴 | ⏳ | ⏳ | ⏳ |
| templates | ⏳ | ⏳ | 🔴 | 🔴 | ⏳ | ⏳ | ⏳ |
| campaigns | ⏳ | ⏳ | 🔴 | 🔴 | ⏳ | ⏳ | 🔴 (devrait être COMPACT) |
| publish | ⏳ | ⏳ | 🔴 | 🔴 | ⏳ | ⏳ | ⏳ |
| clients | ⏳ | ⏳ | 🔴 | 🔴 | ⏳ | ⏳ | ⏳ |
| funnel | ⏳ | ⏳ | 🔴 | 🔴 | ⏳ | ⏳ | 🔴 (devrait être COMPACT) |
| dashboard | ⏳ | ⏳ | 🔴 | 🔴 | ⏳ | ⏳ | 🔴 (devrait être COMPACT) |
| phare | ✅ (5 onglets) | ✅ | 🟡 (1 import HeroQuestion) | 🟡 (idem) | ✅ | ⏳ | 🔴 (1075 lignes, dense) |

**Lecture** : 11 vues sur 14 n'ont jamais été auditées en profondeur dans ce travail (lecture partielle). Mais les 3 audits réels (morning, replies, phare) confirment que **`tokens_v2` n'est pas adopté** dans aucune des vues hors phare/components_pro. C'est mécanique : si chaque vue est codée à la main avec `theme.py`, le design system v2 reste lettre morte.

---

## 6. Bugs UX latents repérés à la lecture

- **`status_bar.py:298`** : compte les prospects via `triskell_core.prospect.core.crm.CRM().all()`. Si la base grossit (1000+ prospects), c'est appelé à chaque `refresh()` synchrone — peut bloquer l'UI au lancement de l'app sur grosse base.
- **`main.py:189`** : `default="morning"` dans `app_state.get("active_view")` mais `default="autopilot"` dans la sidebar (`active_view` paramètre). Incohérence : la première fois sans state, l'app peut afficher autopilot avant de basculer sur morning.
- **`sidebar.py:157`** : `_refresh_icon()` appelle `I.get_icon()` à chaque hover. Pas de cache visible. Pour 14 items × 2 (hover/leave) × N renders = ré-rasterisation potentiellement coûteuse.
- **`worker_pulse.py:336`** : `set_supabase_status(online=False)` ne reset pas le label si une chaîne custom a été passée précédemment.
- **Cycle de thème Ctrl+T** : reconstruit les vues (`_views.clear()`) mais **ne reconstruit pas les FABs** dans toutes les branches. Possible état orphelin si un FAB avait `set_attention(True)`.

Ces points ne sont pas critiques mais méritent une note dans la roadmap.

---

## 7. Métriques cibles à instrumenter

Pour mesurer l'effet de toute future refonte sans tomber dans les vanity metrics, instrumenter en local-only (anonyme) :

- **Time-to-first-action** : ouverture app → premier clic sur une action métier (≠ navigation).
- **View switch rate** : changements de vue par session. Cible : diviser par 1.5 après l'unification Acquisition + Communication.
- **Backtrack count** : retours à la sidebar pendant qu'une tâche est en cours (signal de fragmentation).
- **Empty session rate** : sessions sans action métier (signal de friction d'entrée).
- **Adoption tokens_v2** : grep CI sur le nombre de fichiers important `tokens_v2`. Cible : 100 % des vues d'ici 2 sprints.

Sans ces métriques, on optimise au feeling. Ce n'est pas grave aujourd'hui (l'app sert deux personnes qui peuvent dire ce qui les fatigue), ça le devient si l'usage s'élargit.
