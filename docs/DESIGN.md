# Triskell Command — Design

> Document vivant. Source de vérité visuelle pour le cockpit interne.
> Mainteneur : Jordan. Dernière maj : 2026-05-07.

---

## 1. Ce qu'est Triskell Command

Un cockpit personnel pour deux opérateurs (Jordan + Thomas) qui pilotent un
studio entier depuis une fenêtre. Outil quotidien, plusieurs heures par jour.
Non commercialisé. La cible n'est pas "des prospects à convertir" mais
"nous-mêmes, dans cinq ans, encore en train de l'utiliser tous les matins".

Cette définition change tout. Un SaaS public optimise la conversion. Un
cockpit interne optimise la **fatigue** : la fatigue oculaire, la fatigue
décisionnelle, la fatigue de répétition. Tout le système design découle de
là.

## 2. Manifeste

**Sobre, dense, sans cérémonie.** Pas un produit qui se vend. Un instrument
qui s'utilise. La beauté vient de la justesse, pas de l'ornement.

**Hiérarchie avant esthétique.** Une vue est réussie quand un coup d'œil
suffit pour savoir quoi faire ensuite. Si la décoration brouille la
hiérarchie, la décoration saute.

**Densité maîtrisée.** Bloomberg sans la laideur. Linear sans la rareté.
On affiche beaucoup d'information, mais chaque pixel justifie sa présence
par une décision qu'il informe.

**Calme par défaut, énergie sur intervention.** Le cockpit ne crie pas.
Il chuchote. Quand quelque chose réclame attention (PR à valider, anomalie,
réponse entrante), l'énergie monte localement, jamais globalement.

**Rituel quotidien.** L'app a une boucle : Matinale au réveil, Drafts en
journée, Funnel/Dashboard en fin de semaine. Le design soutient ce rituel.
La Matinale est le moment où l'app cesse d'être un outil et devient un
compagnon de matin — chaleureuse, claire, courte.

**Microcopy comme signature.** Pas "Loading..." mais "Préparation en cours".
Pas "Empty state" mais "Rien ici pour l'instant — souffle". Pas "Settings"
mais "Réglages". Le vocabulaire breton-français-direct est le tatouage
discret du cockpit.

**Or comme sceau, pas comme couleur.** L'or signe (logo Table Ronde,
indicateur d'item actif, séparateur de section noble). Il ne remplit
jamais. La couleur primaire est l'indigo Triskell, fonctionnelle et neutre.

**Médium assumé.** CustomTkinter n'est pas le web. Pas de subpixel, pas
d'animations fluides, pas de SVG natif. On compose avec ce qui existe :
typographie nette, espacement généreux, couleur sémantique, hiérarchie
plate. Les compromis du médium deviennent des choix esthétiques.

## 3. État actuel — ce qui est déjà juste

Constat de l'existant (audit code, 2026-05-07) :

- **Système de tokens trois modes** (`theme.py`) : LIGHT Apple-clear, MID
  graphite chaud, DARK cockpit nuit. C'est rare, c'est juste, c'est gardé.
- **Échelle d'espacement base 4** + radius cohérents. Solide.
- **Typo Inter + Cinzel signature** : le bon couple. Inter pour le travail,
  Cinzel pour les rares moments de cérémonie (titres de section, hero).
- **Composants nommés** (`ViewHeader`, `Card`, `PrimaryButton`,
  `SecondaryButton`, `GoldButton`) avec contrats clairs. Filet accent 3px
  au-dessus du titre = signature visuelle réutilisée. Bien.
- **Sidebar sémantique** (LE MATIN / L'APP TRAVAILLE POUR TOI / À LA MAIN /
  LIVRAISON / CHIFFRES / VISIBILITÉ) avec sous-titres en français parlé,
  pas en jargon produit. C'est une force et elle doit être préservée.
- **Microcopy soigné** : "Compagnon", "On te suit pas à pas",
  "Rien ici pour l'instant". Le ton est cohérent.

Conclusion : il n'y a pas à refaire le système. Il y a à le **rendre
homogène** dans son application et à élever trois ou quatre points de
plafond visuel.

## 4. Diagnostic — ce qui plafonne

Cinq points, par gravité décroissante.

### 4.1 Workers invisibles

Six workers tournent en arrière-plan (SyncPoller, RepliesPoller,
ReplyResponder, DripRunner, PostSaleRunner, PhareScheduler). Leur état est
quasi-invisible dans l'UI. Pour un cockpit, c'est un défaut de
caractère : on ne sait jamais si les engrenages tournent.

→ Il manque une **rangée de pulsation système** (footer ou top-bar)
qui montre en permanence : 6 cercles minuscules avec leur dernière
activité, état (idle/working/error), et tooltip détaillant le cycle
suivant. Pulsation lente quand idle, rotation discrète quand actif.

### 4.2 Densité maladroite sur les vues data-heavy

Le Phare (4 onglets internes + onglet Avancé + 9 cartes mission + boutons
CTR + listes de PRs + bulletins) frise la surcharge. Risque : l'opérateur
ne sait plus où regarder. Symptôme classique d'un cockpit qui a grandi
sans direction d'art.

→ Hiérarchie à trois niveaux à imposer dans toute vue dense :
1. **Une question** (le hero text : "Qu'est-ce que Le Phare a fait pour
   moi cette semaine ?")
2. **Trois chiffres maximum** (KPIs primaires)
3. **Le reste** (caché derrière un onglet, un disclosure, ou un drawer
   de droite — jamais à l'écran initial)

### 4.3 Iconographie hétérogène

Mix d'icônes maison (`icons.py`), emojis dans les labels de vues
(📊 📡 ✉ 🚀 ✅ 🔎), et probables résidus textuels (⧾, ⚔). Pour un
cockpit interne, **aucun emoji** dans la nav et les titres. Une seule
famille d'icônes, monochromes, ligne fine, taille fixe.

→ Décision : icônes Lucide (open-source, MIT, tracée à 1.5px) en PNG
pré-rendu pour CustomTkinter. Une icône = un fichier. Pas d'emojis.

### 4.4 Rituel matinal sous-exploité

La Matinale est la vue la plus stratégique (vue par défaut au boot, KPIs
J-1, file de travail, anomalies). C'est là que l'opérateur décide de sa
journée. Aujourd'hui c'est une vue parmi d'autres. Elle doit être traitée
comme **le moment fondateur de la journée** : composition différente,
typo plus généreuse, rythme musical plutôt que dense.

→ Refonte ciblée : la Matinale n'a pas de sidebar visible (elle peut
être collapsée), titre Cinzel plein air, trois sections rituelles
("Hier", "Aujourd'hui", "Cette semaine") séparées par des respirations
généreuses. Quand l'opérateur quitte la Matinale, la sidebar revient.

### 4.5 Or sur-utilisé sur les surfaces

L'or (gold / gold_soft) doit rester un **sceau**. Aujourd'hui il y a un
GoldButton, un indicateur or sur sidebar, un halo or sur le logo, un or
sur les screenshots du Lanceur. Trop. L'or se dévalue à chaque
répétition.

→ Règle : or sur **maximum trois éléments** par écran, jamais en
remplissage de bouton normal. Le `GoldButton` reste pour 1-2 actions
rituelles par session ("Adouber", "Valider la journée"), pas pour les
CTAs courants.

## 5. Plan d'élévation — 5 axes

L'objectif n'est pas un redesign frontal. C'est cinq mouvements ciblés qui
font passer le cockpit de "déjà bien fait" à "objet quotidien dont on est
fier".

### Axe A — Pulsation système

L'app a déjà une `widgets/status_bar.py` en haut qui sert d'**état de
configuration** (IA prête, mail OK, pilote activé) + KPIs cliquables
(drafts, prospects, envoyés). On la garde telle quelle. Elle répond à
la question "le cockpit est-il prêt à fonctionner ?".

À elle s'ajoute en bas une `widgets/worker_pulse.py` (28 px, fond
`bg_alt`) qui répond à une autre question : "**les engrenages tournent-ils
là, maintenant ?**" Composition :

- 6 LED workers (Sync · Mail · Resp · Drip · Post · Phar) avec pulsation
  lente quand idle, accent quand active, danger quand error
- Tooltip détaillé au survol (cycle + dernière activité + relative time)
- Zone centrale : dernier événement notable
- Droite : indicateur Supabase (online/local) + horloge

Les deux barres ne se marchent pas dessus : l'une est statique
(configuration), l'autre est dynamique (pulse).

Effet : l'opérateur voit en permanence que ça tourne. Confiance.

### Axe B — Iconographie unifiée

- Lucide icons (PNG 16/20/24, monochrome `text_secondary`)
- Tous les emojis retirés de la sidebar et des titres de vue
- Icons.py refactoré : un loader qui résolve un nom Lucide → fichier PNG
  + tinte selon le mode actif

### Axe C — Hiérarchie matinale

Refonte de `views/morning.py` :
- Header sans sidebar (mode focus optionnel)
- Cinzel plein air pour le greeting ("Bonjour Jordan." ou date Cinzel +
  date du jour en Inter)
- 3 sections rituelles : **Hier** (ce qui s'est passé) / **Aujourd'hui**
  (ce qui t'attend) / **Cette semaine** (ce qui se prépare)
- Anomalies en card rouge fine, jamais en alert intrusive

### Axe D — Densité du Phare

`views/phare.py` simplifié :
- Hero question : "Qu'a fait Le Phare cette semaine ?"
- 3 KPIs : Trafic delta · PRs en attente · Sites monitorés
- Onglet "Avancé" et missions ponctuelles passent dans un **drawer de
  droite** activé par bouton "Outils avancés" (caché par défaut)
- Le reste reste accessible mais cesse d'occuper l'écran initial

### Axe E — Composants pro manquants

Ajouts à `widgets/components.py` :
- `KpiCard` (chiffre primaire grand, libellé court, delta vs période,
  micro-sparkline si applicable)
- `LogRow` (entrée de log timestampée pour activity feed worker)
- `DrawerRight` (panneau coulissant droite, pour les outils avancés)
- `EmptyState` (illustration légère + microcopy + CTA)
- `Disclosure` (section repliable inline, pour densité maîtrisée)

## 6. Tokens à compléter

Le système a couleur + espacement + typo. Il manque :

- **Élévation** : 3 niveaux (`shadow_low`, `shadow_mid`, `shadow_high`)
  émulés via `bg_alt` / `panel` / `panel_elevated` + bordures plus ou
  moins marquées (CustomTkinter ne fait pas de vraie ombre).
- **Motion** : 3 durées (`motion_quick=80ms`, `motion_standard=160ms`,
  `motion_slow=320ms`) pour cohérence des transitions Tk (after()).
- **Tabular nums** : forcer `font="Inter Tabular"` ou `tnum` partout où
  on aligne des chiffres en colonne (KPIs, listes de prospects).
- **Densité** : `DENSITY_COMFORTABLE` (défaut) vs `DENSITY_COMPACT` (mode
  data-heavy, pour Phare/Funnel).

## 7. Anti-checklist (ce qu'on ne fera pas)

- Pas de **gradient** en surface principale (esthétique 2018 datée).
- Pas de **glassmorphism** (CustomTkinter ne fait pas le blur, et on
  n'en a pas besoin).
- Pas d'**emoji** en navigation, en titre ou en composant. (Sauf
  microcopy ironique très ponctuel et conscient — par exemple footer
  Bretagne.)
- Pas de **Cinzel** ailleurs que titre hero matinal et logo. C'est une
  signature, pas une typo de corps.
- Pas de **plus de 3 couleurs** vues simultanément à l'écran (hors
  signaux sémantiques success/warning/danger ponctuels).
- Pas de **shadow CSS-like** émulée par double bordure dégradée — ça
  rend mal en Tk. Préférer bordures nettes + bg_alt.
- Pas de **logo Triskell** sur chaque vue. Une fois en sidebar suffit.

## 8. Livraisons de cette itération (2026-05-07)

1. `docs/DESIGN.md` — manifeste + diagnostic + plan ✓
2. `tokens_v2.py` — élévation, motion, density, ttype, z, widths,
   heights, borders ✓
3. `widgets/worker_pulse.py` — pulsation système 6 workers (axe A) ✓
4. `widgets/icons_lucide.py` + `scripts/fetch_lucide_icons.py` —
   loader Lucide optionnel coexistant avec `icons.py` (axe B) ✓
5. `widgets/components_pro.py` — `KpiHero`, `LogRow`, `DrawerRight`,
   `Disclosure` (axe E) ✓
6. `docs/PATCHES.md` — patches chirurgicaux pour `morning.py` et
   `phare.py` (axes C et D), 7 patches indépendants à appliquer un
   par un ✓

**Choix volontaire** : pas de `morning_v2.py` ni `phare_v2.py`. Les
vues existantes sont déjà bien architecturées — refaire serait
régressif. À la place, les patches dans `PATCHES.md` proposent des
modifications ciblées avec avant/après et stratégie de rollout.

Chaque fichier livré vit en parallèle de l'existant. Aucun fichier
existant n'a été modifié. Pas de big bang. L'adoption peut se faire
fichier par fichier, patch par patch.

---

*« Un cockpit n'est pas une œuvre d'art. C'est l'œuvre d'un opérateur. »*
