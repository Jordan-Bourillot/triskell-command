# Parcours utilisateurs — Triskell Command v0.4

**Date** : 2026-05-08
**Périmètre** : 5 parcours qui couvrent ~80 % de l'usage quotidien Jordan + Thomas. Calibrés sur la v0.4 réelle (lecture de `morning.py`, `replies.py`, `phare.py`).

Chaque parcours suit la structure : **trigger → étapes → succès → friction critique**. La colonne « Aujourd'hui » décrit le réel observé en code, « Cible » décrit l'objectif de la refonte (cf. [01_NAVIGATION.md](01_NAVIGATION.md)).

---

## P1 — Démarrer la journée

### Aujourd'hui
✅ La Matinale est la vue par défaut (`main.py:189` → `default="morning"`). Salutation contextuelle (Bonjour/Bonsoir + prénom), date, **une seule priorité du jour** mise en avant (interesting > drafts > replies à trier > tout est calme). Hier en 3 chiffres, Aujourd'hui en 2, blocs « À corriger » et « Phare » conditionnels. C'est le modèle exemplaire de l'app.

**Friction réelle** : très peu. Une remarque seulement : le bouton `Demander conseil à Claude` dans le hero (`SecondaryButton "sparkle"`) duplique le FAB Claude flottant (F12, en bas à droite). Sur Matinale spécifiquement, l'utilisateur·rice a deux entrées Claude visibles à 5cm de distance. Soit on retire le bouton du hero, soit on le contextualise (« Demander conseil sur ta journée » avec passage du digest en prompt prefilled).

### Cible
Rien à refondre. Ce parcours est l'étalon que les autres doivent atteindre.

---

## P2 — Acquérir des prospects

### Aujourd'hui
🔴 **Trois entrées concurrentes** : Auto-pilote (Sirene+Maps), Importer une liste (PDF/Word/Excel/OCR), Chercher des prospects (recherche manuelle 9 plateformes). L'utilisatrice doit choisir l'écran avant de savoir quoi chercher.

Si elle veut « 20 paysagistes en Bretagne » : doit-elle aller dans Auto-pilote (Sirene par code NAF) ? Maps (par mot-clé + ville) ? Manuelle (Sirene direct) ? La sidebar ne le dit pas. C'est une charge cognitive frontale qu'on impose en début de tâche.

**Friction réelle** :
- 3 vues, 3 layouts, 3 jeux de filtres, 3 tableaux de résultats légèrement différents.
- Chaque vue a son propre routing post-recherche (envoi vers drafts ? vers compose ? vers le CRM Triskell Core ?).
- Le mode auto/manuel devient un changement de section dans la sidebar plutôt qu'un toggle dans une vue unifiée.

### Cible
Une seule vue **« Trouver des prospects »** avec **chips de source** en haut :

```
┌──────────────────────────────────────────────────────────┐
│ Trouver des prospects                                    │
│ [Sirene ◉] [Google Maps ○] [Réseaux ○] [Fichier ○]      │
├──────────────────────────────────────────────────────────┤
│ ZONE 1 — filtres adaptés à la source choisie             │
│   • Sirene : code NAF, département, taille effectif      │
│   • Maps : ville, rayon, mot-clé                         │
│   • Réseaux : niche, abonnés min/max, langue             │
│   • Fichier : drag & drop                                │
├──────────────────────────────────────────────────────────┤
│ ZONE 2 — résultats (tableau commun à toutes sources)     │
│   colonnes : Nom · Contact · Email · Secteur · Score     │
├──────────────────────────────────────────────────────────┤
│ ZONE 3 (sticky) — actions de masse                       │
│   [✉ Envoyer vers Communication] [💾 Sauver] [⚡ Boucle]│
└──────────────────────────────────────────────────────────┘
```

**Le toggle « Mode automatique »** en haut à droite remplace l'item sidebar. Il est désactivé par défaut, signal clair quand il est ON.

**Succès cible** : nouvel utilisateur trouve sa première liste de 20 prospects qualifiés en moins de 3 minutes peu importe la source. Une seule courbe d'apprentissage.

---

## P3 — Communiquer avec des prospects

### Aujourd'hui
🟡 Cycle fragmenté en 4-5 vues : `compose` (rédiger) → `templates` (charger un modèle) → `drafts` (valider) → `campaigns` (planifier l'envoi) → `replies` (lire la réponse). Quand un draft est généré par auto-pilote, il atterrit dans drafts ; quand on l'écrit à la main, on passe par compose ; quand on veut un modèle, on va dans templates ; quand on envoie, on va dans campaigns.

**Friction réelle** : la rédaction et la validation sont **séparées en 2 vues distinctes**. Une fois le draft validé, il faut aller le voir partir dans Campaigns. Si on veut adapter un modèle à un secteur de prospect, il faut switcher modèle ↔ compose plusieurs fois. Charge mentale = 4 contextes ouverts.

### Cible
Un seul écran **« Écrire & envoyer »** en 3 colonnes redimensionnables :

```
┌─────────────────────────────────────────────────────────┐
│ Écrire & envoyer                                        │
├──────────┬──────────────────┬───────────────────────────┤
│ MODÈLES  │ BROUILLONS       │ EN VOL                    │
│ (gauche) │ (centre)         │ (droite)                  │
├──────────┼──────────────────┼───────────────────────────┤
│ • Pack   │ ┌──────────────┐│  3 envoyés / 12 prévus    │
│   Élec   │ │ M. Dupont    ││                           │
│ • Site   │ │ « Bonjour... ││  Prochain dans 1m         │
│   Stand  │ │              ││                           │
│ • Resto  │ │ [Régénérer]  ││  Campagne : convoi-mai    │
│ • ...    │ │ [✓ Approuver]││                           │
│          │ │ [✗ Rejeter]  ││  Cap : 50/jour            │
│          │ └──────────────┘│  Délai : 60s entre 2      │
│          │                  │                           │
│          │ ▾ M. Garagiste   │                           │
│          │ ▾ M. Boulangerie │                           │
└──────────┴──────────────────┴───────────────────────────┘
                                                    
[ Envoyer 17 brouillons approuvés → ]    (sticky bas)
```

**Drag d'un modèle vers la colonne centrale** crée un draft basé sur ce modèle. **Approuver** bascule vers la colonne droite avec planning. **Régénérer** appelle l'IA avec le contexte prospect.

Les anciennes vues `compose`, `templates`, `campaigns` deviennent des panels, accessibles aussi en plein écran via Ctrl+K (« Aller à : Modèles »).

**Succès cible** : Jordan génère 20 brouillons depuis un modèle, en valide 17, planifie l'envoi sur 2 jours en moins de 5 minutes — sans changer d'écran.

---

## P4 — Auditer et optimiser un site avec Le Phare

### Aujourd'hui
🟡 5 onglets internes (Écosystème / Site / Avancé / Modifications en attente / Bulletins) dans 1075 lignes de code. Le DESIGN.md axe D pointe déjà la densité à simplifier.

**Friction observée à la lecture de `phare.py`** :
- Onglet « Écosystème » charge KPI globaux + table 13 sites → potentiellement long.
- Lancement d'un cycle complet est en `threading.Thread` (`phare.py:17`) avec `_status_var` en bas pour le feedback. **Le pulse-bus existe** (`integrations/pulse_bus.py`) mais Phare ne l'utilise pas pour signaler la progression au WorkerPulse — il a son propre status_var local.
- Onglet Avancé sur la même page que les onglets normaux : violation du principe DESIGN axe D (« passe en drawer droit »).

### Cible
Application de DESIGN.md axe D + intégration pulse-bus :

1. **Hero question** au-dessus des onglets : *« Qu'a fait Le Phare cette semaine ? »* + 3 KPIs (Trafic delta, PRs en attente, Sites monitorés). Composant `HeroQuestion` déjà importé en `phare.py:34`.
2. **Onglet Avancé** déplacé en `DrawerRight` (composant `components_pro.DrawerRight` déjà codé) activé par bouton « Outils avancés » en haut à droite.
3. **Pulse-bus pendant audit** : chaque agent SEO (Auditeur Tech, Veilleur Mots-Clés, Rédacteur, Optimiseur On-Page, Tisseur, Chasseur Backlinks, Analyste, Chef d'Orchestre) émet `pulse_bus.report("phare", "active", text="Auditeur Tech : audit en cours")` → la LED PHAR du WorkerPulse passe à `active`, et le sous-texte central de WorkerPulse affiche la progression. **Plus jamais de silence de 60 s** quand un audit tourne.
4. **Vue de site individuel** garde sa densité actuelle, mais `phare.py` doit migrer vers `density_for("phare")` qui retourne COMPACT (`tokens_v2.py:138`). Économie de pixels significative.

**Succès cible** : Jordan lance un audit complet, voit chaque agent tourner via WorkerPulse, lit les recommandations au fur et à mesure dans la colonne dédiée, merge celles qui valent le coup — sans douter une seconde que l'app est figée.

---

## P5 — Mesurer ce qui marche (Tableau de bord + Funnel)

### Aujourd'hui
⏳ Vues `dashboard.py` et `funnel.py` non lues dans cet audit. À auditer en profondeur dans une session dédiée. Hypothèse de friction : vu la maturité du reste, ces deux vues sont probablement plus dense que nécessaire. `density_for("dashboard")` et `density_for("funnel")` retournent COMPACT mais probablement non appliqué (cf. [00_AUDIT §5](00_AUDIT.md)).

### Cible
Trois questions, trois graphes par vue :

**Tableau de bord** :
- *Combien j'ai contacté ?* → courbe d'envois sur la période + breakdown par source.
- *Combien ont répondu ?* → taux de réponse + par modèle utilisé (révèle quels modèles convertissent).
- *Combien j'ai gagné ?* → prospects en statut `won` + valeur estimée si renseignée.

**Tunnel de conversion (`funnel`)** :
- Étape par étape : Prospect → Contacté → Répondu → Intéressé → Client. Volume + taux de conversion entre étapes.
- Période ajustable, comparaison vs période précédente en delta.

**Friction à éliminer** : pas de KPI orphelin. Chaque chiffre attaché à une question business. Pas de pie chart sur 12 catégories. Comparaison vs période précédente affichée systématiquement (« +23 % vs 30 j précédents ») — c'est l'info qui compte, pas le chiffre brut.

---

## Anti-parcours — choses qui doivent disparaître du quotidien

Ce que la refonte doit rendre **impossible ou improbable** :

- ❌ Naviguer entre 4 vues pour un cycle complet d'envoi mail (P3).
- ❌ Choisir une source d'acquisition avant de savoir ce qu'on cherche (P2).
- ❌ Tomber sur un écran vide sans guidance (déjà bien géré, cf. EmptyState dans Matinale).
- ❌ Lancer un audit Phare et ne plus rien voir pendant 60 s (P4).
- ❌ Ré-démarrer une recherche parce qu'on a cliqué la sidebar et perdu les filtres (P2).
- ❌ Avoir 2 entrées Claude visibles à 5 cm sur la même vue (Matinale, friction mineure).
- ❌ Se demander « où voir si Thomas a envoyé un mail » — la carte « Activité partagée » sur Aujourd'hui résout ça, à condition que la sync messages alimente bien Aujourd'hui.

---

## Note sur l'automatisation post-vente

À la lecture de main.py, **PostSaleRunner** envoie cross-sell J+30 et NPS J+90 sur les clients livrés. C'est un parcours **automatique** (pas utilisateur) mais qui mérite vérification UX :

- Le client reçoit-il bien un mail signé Jordan, pas un robot anonyme ?
- L'utilisateur·rice peut-elle voir et auditer les envois post-vente avant qu'ils partent ?
- En cas de réponse à un cross-sell, où atterrit-elle ? (Probablement dans `replies` mais à confirmer.)

Ce parcours mérite son propre document d'audit dans une session dédiée si l'usage post-vente s'intensifie.
