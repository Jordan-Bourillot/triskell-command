# Navigation — Triskell Command v0.4

**Date** : 2026-05-08
**Préfixe** : ce document complète `docs/DESIGN.md` qui ne couvre pas la sidebar ni l'IA. Il propose une refonte de la navigation et un nouveau type de surface (palette de commandes).

---

## 1. État actuel — récapitulatif

```
SIDEBAR v0.4 (16 items)

┌── LE MATIN ──────────────┐
│  • Matinale              │
├── L'APP TRAVAILLE POUR TOI ┤
│  • Auto-pilote           │
│  • Importer une liste    │
│  • Brouillons à valider  │
│  • Réponses des prospects│
├── À LA MAIN ─────────────┤
│  • Chercher des prospects│
│  • Écrire avec l'IA      │
│  • Modèles d'emails      │
│  • Envoyer des emails    │
│  • Publier sur les réseaux│
├── LIVRAISON ─────────────┤
│  • Projets clients       │
├── CHIFFRES ──────────────┤
│  • Conversions           │
│  • Tableau de bord       │
├── VISIBILITÉ ────────────┤
│  • Le Phare              │
└── (footer) ──────────────┘
   • Tuto
   • Aide
   • Réglages

+ FABs flottants : Claude (F12) + Thomas (F11)
+ Raccourcis Ctrl+1..9 sur 9 vues
```

**Forces** : sectioning verbalisé en français parlé, pas en jargon produit. C'est rare et précieux.

**Plafonds** :
1. **Découpage par mode d'exécution.** « L'app travaille pour toi » vs « À la main » oblige l'utilisatrice à connaître l'implémentation pour naviguer. Le job (« contacter des paysagistes ») est invariant à la voie auto/manuelle.
2. **Profil asymétrique.** *Visibilité* contient 1 item (Phare), *Livraison* aussi (Clients). Ces sections singletons signalent un découpage qui pourrait être plus dense ailleurs.
3. **Pas de palette de commandes.** Sidebar = seul moyen visible de naviguer.
4. **Raccourcis Ctrl+1..9** : excellente intention, mais l'ordre actuel (`morning, autopilot, convoy, drafts, replies, prospects, compose, templates, funnel`) est partiel (9 sur 14) et arbitraire.

---

## 2. Architecture cible

### 2.1 Refonte par mission (sidebar 16 → 11 items)

```
┌── ⌂ Aujourd'hui ─────────────┐    ← morning, point d'entrée par défaut
│                              │
├── ACQUISITION ───────────────┤
│  • Trouver des prospects     │    ← unifie autopilot + convoy + prospects
│  • Brouillons à valider      │    ← drafts (porte d'entrée du reste)
│                              │
├── COMMUNICATION ─────────────┤
│  • Écrire & envoyer          │    ← unifie compose + templates + campaigns
│  • Réponses entrantes        │    ← replies
│  • Réseaux sociaux           │    ← publish
│                              │
├── LIVRAISON ─────────────────┤
│  • Projets clients           │    ← clients
│                              │
├── MESURE ────────────────────┤
│  • Tunnel de conversion      │    ← funnel
│  • Tableau de bord           │    ← dashboard
│                              │
├── OPTIMISATION ──────────────┤
│  • Le Phare (SEO)            │    ← phare
│                              │
└── (footer) ──────────────────┘
   • Tuto · Aide · Réglages
```

**11 items principaux** au lieu de 16. Sections par **mission** au lieu de mode. Mode auto/manuel devient un onglet ou toggle **dans** "Trouver des prospects".

### 2.2 Justifications

**Fusion Acquisition** : `autopilot` (Sirene+Maps), `convoy` (fichier importé), `prospects` (recherche manuelle YT/Twitch/Reddit/9 plateformes selon ProspectsView) → un seul écran avec sélecteur de source en haut. Toutes ces vues répondent au même job *« obtenir une liste de prospects qualifiés »*. La source change les filtres, pas le squelette d'écran ni l'action de sortie (envoyer vers Communication).

**Fusion Communication** : `compose` (rédacteur IA), `templates` (bibliothèque), `campaigns` (envoi en file) sont les trois moments d'un même cycle. Un cockpit 3 colonnes (modèles | brouillons | en vol) garde tout en un seul contexte. `drafts` reste à part dans Acquisition car c'est la porte d'entrée du cycle (validation des brouillons générés par auto-pilote).

**Une seule vue par section singleton** : *Livraison* (Clients) et *Optimisation* (Phare) restent en singletons assumés. Plus tard, si Livraison gagne une vue *Onboarding* et Optimisation gagne *A/B tests* ou *Analytics produit*, les sections justifieront leur taille.

**Drafts reste séparé** : techniquement c'est de la communication, mais c'est une **file d'attente d'action** distincte du cycle rédaction-envoi normal. Le maintenir dans Acquisition signale clairement « voici ce que l'auto-pilote a préparé et qui attend ton OK ».

### 2.3 Migration sans rupture

Aucune vue n'est supprimée. La refonte est principalement une **réorganisation de surface**.

| Vue actuelle | Devient |
|---|---|
| `morning` | `today` (renommé pour clarté universelle) |
| `autopilot` | onglet « Sirene + Maps » dans `acquisition` |
| `convoy` | onglet « Importer un fichier » dans `acquisition` |
| `prospects` | onglet « Recherche manuelle » dans `acquisition` |
| `drafts` | inchangé, déplacé en section Acquisition |
| `compose` | colonne « Édition » de `communication` |
| `templates` | colonne « Modèles » de `communication` |
| `campaigns` | colonne « Envois » de `communication` |
| `replies` | inchangé, dans Communication |
| `publish` | renommé en « Réseaux sociaux » dans Communication |
| `clients` | inchangé |
| `funnel` | inchangé, dans Mesure |
| `dashboard` | inchangé, dans Mesure |
| `phare` | inchangé, dans Optimisation |

Le routing (`VIEW_REGISTRY` dans `main.py:45`) ajoute `today`, `acquisition`, `communication` comme parents. Les vues actuelles restent **adressables** comme sous-vues (utile pour deep-link, raccourcis, palette Ctrl+K).

---

## 3. Palette de commandes (Ctrl+K)

### 3.1 Pourquoi

Avec 14 vues + 6 runners + N prospects + N campagnes + 13 sites Phare, la sidebar n'est plus assez. Une palette `Ctrl+K` qui fuzzy-matche **vues + actions globales + entités** est l'investissement UX qui paie le plus quand l'app grandit.

### 3.2 Contenu

Quatre catégories, dans cet ordre de pertinence :

1. **Vues** : « Aller à : Tableau de bord » → ouvre le dashboard.
2. **Actions globales** : « Lancer un audit Phare », « Composer un mail », « Importer une liste », « Activer le pilote », « Cycler le thème ».
3. **Entités** : « Prospect : SARL Dupont » → ouvre la fiche, « Site Phare : sites.triskell-studio.fr », « Campagne : convoi-paysagistes-mai ».
4. **Réglages directs** : « Réglages → Provider IA », « Réglages → SMTP IONOS ».

### 3.3 Implémentation Tk

Modale `Toplevel` plein écran semi-transparente, centrée, 600 px de large. Champ texte focus auto à l'ouverture. Listbox sous le champ avec fuzzy match (FuzzyWuzzy ou simple `in` lowercase).

```
Ctrl+K ouvre :
┌─────────────────────────────────────┐
│ 🔍  Tape une commande...            │
│─────────────────────────────────────│
│ ⏎  Aller à : Aujourd'hui            │
│ ⏎  Aller à : Le Phare               │
│ ⚡  Lancer cycle complet Phare       │
│ ⚡  Importer une liste de prospects │
│ 👤  Prospect : Boulangerie Dupont   │
│ 👤  Prospect : SARL Garagiste       │
│ ⚙  Réglages → Provider IA           │
│                                      │
│ Esc pour fermer · ↑↓ pour naviguer  │
└─────────────────────────────────────┘
```

Hook clavier : `<Control-k>` au niveau de `main.py:_bind_shortcuts`. Catalogue d'actions = un dict défini en module séparé `command_palette.py`.

### 3.4 Ordre raccourcis Ctrl+1..9

L'ordre actuel (`morning, autopilot, convoy, drafts, replies, prospects, compose, templates, funnel`) suit l'ordre sidebar v0.4. **Bug latent** : `funnel` est à la 9e place, et `phare` (probablement plus utilisé) n'a pas de raccourci.

**Proposition révisée alignée sur la nouvelle nav** :
- Ctrl+1 : Aujourd'hui
- Ctrl+2 : Trouver des prospects
- Ctrl+3 : Brouillons à valider
- Ctrl+4 : Écrire & envoyer
- Ctrl+5 : Réponses entrantes
- Ctrl+6 : Projets clients
- Ctrl+7 : Tableau de bord
- Ctrl+8 : Le Phare
- Ctrl+9 : Réglages
- Ctrl+0 : Tunnel
- Ctrl+K : Palette
- Ctrl+T : Cycle thème (déjà en place ✓)

---

## 4. Status bar haute — repositionnement

(Lien avec [00_AUDIT §4.3](00_AUDIT.md).)

La status bar haute actuelle mélange deux rôles : **état système** (IA/Mail/Pilote/profil) et **mini-tableau de bord** (drafts, prospects, envoyés). Avec WorkerPulse en bas et Matinale en hero d'accueil, les KPIs y sont redondants.

**Proposition** : la status bar haute n'affiche plus que :
- 3 dots de configuration (IA / Mail / Pilote) avec libellés et clic = config.
- Profil utilisateur à droite.
- Au centre, **rien**, ou le titre+date de la vue actuelle si on enlève le ViewHeader des vues. Pas les KPIs.

Cela libère ~30 px de hauteur visuelle et clarifie : la **status bar haute = config**, le **WorkerPulse bas = activité**, la **Matinale = ce que je dois faire**, les **vues = mon travail**. Quatre rôles, quatre zones, aucune redondance.

---

## 5. FABs Claude et Thomas — bornage

Les deux FABs sont une excellente trouvaille (toujours visibles, indépendants des vues, raccourcis F11/F12). Deux notes :

**5.1 Pas de troisième FAB.** L'écran a déjà 4 zones permanentes : sidebar gauche, status bar haute, vue centrale, WorkerPulse bas, FABs droite. Toute extension future doit passer par la palette de commandes ou un drawer, pas un nouveau FAB. Trois FABs deviendrait du bruit.

**5.2 Disposition adaptative.** Sur petites résolutions (laptop 13"), les 2 FABs en bas droite peuvent chevaucher le contenu de la vue. Tester `WINDOW_MIN_WIDTH=1140` (déjà défini) : à cette taille les 2 FABs prennent de l'espace utile. À voir si on rétrécit ou empile autrement.

---

## 6. Onboarding et tutorial

`OnboardingDialog` (1er boot, configuration des secrets) et `TutorialDialog` (visite guidée) existent déjà — bonne intention.

**À auditer** dans une session dédiée : `widgets/onboarding.py` et `widgets/tutorial_dialog.py` (non lus dans ce travail). Vérifier qu'après onboarding, les 3 réglages bloquants (clé IA + SMTP + Supabase) sont **tous** capturés, pas seulement deux. Vérifier que le tuto présente bien la palette Ctrl+K, le cycle thème Ctrl+T, et les FABs F11/F12 — ces fonctionnalités sont invisibles sans tuto.
