# Roadmap UX — Triskell Command v0.4 → v0.5

**Date** : 2026-05-08
**Méthode** : matrice effort × valeur. On livre les **S/M à forte valeur** d'abord. On respecte le principe DESIGN.md « pas de big bang ».
**Préfixe** : ce document s'articule autour de **3 axes** :

1. **Adoption du design system v2 existant** (le levier #1 — fondations codées mais pas diffusées).
2. **Compléments à DESIGN.md** (sidebar, palette Ctrl+K, status bar repositionnée).
3. **Application des patches déjà documentés** dans `docs/PATCHES.md`.

---

## 1. Matrice de priorisation

| # | Item | Effort | Valeur | Priorité |
|---|---|---|---|---|
| **A — Adoption design system** | | | | |
| A1 | Migration `tokens_v2.ttype` partout (titres, labels, KPIs) | M | Forte | **P0** |
| A2 | Migration `density_for(view_kind)` sur Phare/Funnel/Dashboard/Prospects/Campaigns | M | Forte | **P0** |
| A3 | Adoption `surface_for(level)` pour cartes empilées (Phare, Funnel) | S | Moyenne | **P1** |
| A4 | Adoption `tokens_v2.z` pour modales/toasts (cohérence z-index logique) | S | Faible | **P3** |
| **B — Patches DESIGN.md déjà documentés** | | | | |
| B1 | Patches Matinale M1-M7 (cf. `docs/PATCHES.md`) | M | Forte | **P0** |
| B2 | Patches Phare D1-D? (densité, drawer avancé, hero question) | L | Forte | **P1** |
| B3 | Pulse-bus dans Phare pour visibilité agents | M | Forte | **P0** |
| **C — Navigation et compléments** | | | | |
| C1 | Refonte sidebar 16 → 11 items (par mission) | M | Forte | **P1** |
| C2 | Palette de commandes Ctrl+K (vues + actions globales) | M | Forte | **P1** |
| C3 | Status bar haute épurée (config seule, KPIs migrés) | S | Moyenne | **P2** |
| C4 | Réordonnancement Ctrl+1..0 + ajout Ctrl+K | S | Moyenne | **P1** |
| **D — Fusions d'écrans** (gros levier, gros effort) | | | | |
| D1 | Écran unique « Trouver des prospects » multi-sources | L | Forte | **P2** |
| D2 | Écran unique « Écrire & envoyer » 3 colonnes | L | Forte | **P2** |
| D3 | Refonte Tableau de bord (3 questions / 3 graphes) | L | Moyenne | **P3** |
| **E — Quick wins exécutables tout de suite** | | | | |
| E1 | Retirer doublon « Demander conseil à Claude » de la Matinale | XS | Faible | **P0** |
| E2 | Renommer « Le Phare » sidebar : préciser « Le Phare — SEO » | XS | Faible | **P0** |
| E3 | Tooltip « Anthropic Claude Sonnet 4.6 » sur pill IA status bar | S | Faible | **P1** |
| E4 | Garde-fou : screenshots dark + mid + light obligatoires en PR | XS | Moyenne | **P0** |
| **F — Bugs latents repérés** (cf. 00_AUDIT §6) | | | | |
| F1 | Cache `I.get_icon` pour éviter ré-rasterisation hover sidebar | S | Faible | **P3** |
| F2 | Async `_count_prospects` pour ne pas bloquer status_bar.refresh | S | Moyenne | **P2** |
| F3 | Reset label `set_supabase_status(False)` sans label custom | XS | Faible | **P3** |
| F4 | Reconstruction des FABs dans toutes branches du cycle thème | S | Faible | **P3** |
| **G — Audit incomplets à finaliser** | | | | |
| G1 | Audit profond `autopilot.py`, `convoy.py`, `compose.py` | M | Moyenne | **P2** |
| G2 | Audit profond `dashboard.py`, `funnel.py`, `clients.py` | M | Moyenne | **P2** |
| G3 | Audit profond `templates.py`, `campaigns.py`, `publish.py` | M | Moyenne | **P2** |
| G4 | Audit `widgets/onboarding.py`, `tutorial_dialog.py` | S | Moyenne | **P2** |
| G5 | Audit accessibilité WCAG AA (contrastes 3 modes) | M | Moyenne | **P2** |

**Total P0 : 7 items.** Sprint 1 = ces 7 items. Aucun ne dépasse 1-2 jours d'effort. Aucun ne casse l'app existante.

---

## 2. Phasage en 4 sprints

### Sprint 1 — Adoption + quick wins (P0, ~1 semaine)

Priorité absolue : **mettre le design system v2 en circulation**. Tant que `tokens_v2` n'est pas adopté, chaque jour creuse la dette.

- **A1** — passe sur les 14 vues : remplacer `(T.FONT_FAMILY_FALLBACK, T.FONT_SIZE_BODY, "bold")` par `ttype.BODY_BOLD`, etc. Mécanique mais à faire avec rigueur. Bonus : compte combien de polices différentes coexistent **avant** la migration et publie le diff dans la PR (révèle souvent une dizaine de variantes à harmoniser).
- **A2** — Phare/Funnel/Dashboard/Prospects/Campaigns : `density = density_for(self.view_kind)` puis `padx=density.cell_padding_x`, etc. Économie visuelle immédiate.
- **B1** — Patches Matinale M1-M7 (KpiHero+sparkline, filet or, phrase contextuelle, tabular nums, cf. `docs/PATCHES.md`). DESIGN.md axe C résolu.
- **B3** — Pulse-bus dans Phare. Chaque agent émet `pulse_bus.report("phare", "active", text=...)`. Résout la friction la plus citée (silence pendant 60s). DESIGN.md axe A complété.
- **E1** — Retire le bouton « Demander conseil à Claude » du hero Matinale (FAB suffit).
- **E2** — « Le Phare » → « Le Phare — SEO » dans la sidebar.
- **E4** — Ajoute checklist PR template : screenshots dark/mid/light avant merge.

**Métrique succès** : grep `from ..tokens_v2` doit passer de 3 fichiers à au moins 12.

### Sprint 2 — Navigation et palette (P1, ~1 semaine)

- **B2** — Patches Phare DESIGN.md axe D (densité maîtrisée + drawer avancé + hero question).
- **C1** — Refonte sidebar par mission (cf. [01_NAVIGATION.md §2](01_NAVIGATION.md)). Garde rétro-compat des routes (les anciennes vues restent adressables).
- **C2** — Palette Ctrl+K v1 (vues + actions globales). Entités en v2.
- **C4** — Réordonnancement Ctrl+1..0 aligné sur la nouvelle nav.
- **A3** — Application `surface_for(level)` sur Phare/Funnel pour hiérarchie claire des cartes.
- **E3** — Tooltips détaillés sur status bar (provider IA, host SMTP).

**Métrique succès** : Jordan utilise Ctrl+K plus de 10 fois/jour après 1 semaine d'usage.

### Sprint 3 — Status bar repositionnée + fusions Acquisition (P2, ~1 semaine)

- **C3** — Status bar haute épurée. Les KPIs migrent vers une carte dédiée sur Aujourd'hui (« Tu as fait : ... »).
- **D1** — Écran unique « Trouver des prospects » avec sélecteur de source. Anciennes vues restent adressables comme sous-modes.
- **F2** — Async `_count_prospects` (évite le blocage UI au boot sur grosse base).
- **G1** — Audit profond `autopilot.py`, `convoy.py`, `compose.py` à appliquer en passant.

**Métrique succès** : parcours P2 (acquérir 20 prospects) chronométré → division par 2 du temps total.

### Sprint 4 — Fusions Communication + audits restants (P2-P3, ~1 semaine)

- **D2** — Écran unique « Écrire & envoyer » 3 colonnes (modèles | drafts | en vol).
- **G2-G3-G4** — Audits profonds des 9 vues restantes + onboarding + tutorial.
- **G5** — Audit accessibilité WCAG AA (contrastes sur les 3 modes).
- **F1, F3, F4** — Bugs latents (cache icons, reset label, FAB cycle thème).
- **D3** — Refonte tableau de bord (3 questions / 3 graphes) si bande passante.

**Métrique succès** : parcours P3 (rédiger + envoyer 17 mails) → division par 2 du temps total.

---

## 3. Décisions structurantes pour cette refonte

### 3.1 Pas de big bang

Reprend la décision DESIGN.md §8. Aucune vue n'est supprimée tant que sa remplaçante n'est pas livrée et testée. La fusion des vues d'acquisition (D1) et de communication (D2) garde les anciennes adressables comme sous-modes. La sidebar refondue (C1) ne casse aucun routing existant.

### 3.2 Migration design system avant fusion d'écrans

Les Sprints 1 et 2 (adoption + nav + Phare) précèdent les Sprints 3 et 4 (fusions). C'est volontaire : avant de refondre des écrans complexes (D1, D2), on s'assure que les fondations v2 sont vivantes. Sinon on construit une fusion sur du code legacy = double dette.

### 3.3 Pas de redesign frontal

DESIGN.md anti-checklist §7 reste en vigueur : pas de gradients, pas de glassmorphism, pas d'emojis en nav, pas de Cinzel hors hero matinal et logo, pas de plus de 3 couleurs simultanées (hors signaux sémantiques), pas de logo Triskell sur chaque vue.

### 3.4 Garde-fou screenshots multi-thèmes

Toute PR qui touche une vue doit fournir 3 screenshots (dark + mid + light). Si l'un casse, la PR est refusée. Implémentation : checklist obligatoire dans `.github/PULL_REQUEST_TEMPLATE.md` (à créer).

### 3.5 Métriques avant ressentis

Les 5 métriques de [00_AUDIT §7](00_AUDIT.md) (time-to-first-action, view switch rate, backtrack count, empty session rate, adoption tokens_v2) sont à instrumenter dès Sprint 1, en local-only et anonyme. Sans elles, on optimise au feeling. Avec elles, on peut prouver que la refonte aide vraiment.

---

## 4. Risques et garde-fous

**R1. Migration design system longue.** Si A1 prend plus de 3 jours, c'est un signal qu'il faut soit limiter à 5 vues prioritaires (Matinale + Phare + Funnel + Dashboard + Replies), soit créer un script de codemod automatique.

**R2. Sidebar refondue mal acceptée.** Si Jordan ou Thomas continue d'utiliser les anciens raccourcis Ctrl+1..9 par habitude, prévoir un flash visuel sur les nouveaux items pendant 1 semaine après refonte (« nouvelle place : Ctrl+5 désormais »).

**R3. Palette Ctrl+K oubliée.** Si après Sprint 2 elle n'est pas adoptée, ajouter un onboarding spécifique : modal au 1er boot post-refonte « Tu connais Ctrl+K ? Essaie ». Sinon le composant meurt en silence.

**R4. Pulse-bus dans Phare bavard.** Si chaque agent émet 10 events/seconde, le WorkerPulse peut clignoter en permanence. Throttle côté `pulse_bus.report()` (max 1 event/200ms par worker key).

**R5. Fusion écrans casse l'apprentissage.** Sprints 3-4 changent 2 fois 3 vues en 1 vue. Garde-fou : session de pair-programming/observation 1h avec Jordan après chaque fusion pour vérifier que le mental model reste accessible.

---

## 5. Points reportés explicitement (à challenger plus tard)

- **PostSaleRunner UX** : audit de l'expérience client recevant cross-sell J+30 / NPS J+90 (cf. [02_PARCOURS §note](02_PARCOURS.md)).
- **Web API** (`triskell_command/web/api.py`) : présent dans le tree, non audité. Surface utilisateur ? endpoints ?
- **Local users** (`triskell_command/local_users.py`) : module récent, rôle exact non audité.
- **Multi-utilisateur étendu** : si l'usage à 2 personnes (Jordan+Thomas) s'étoffe à plus, repenser la surface partagée. Actuellement le chat 1:1 + l'activité passive suffit.
- **PC2** : la mémoire indique un autre setup chez Jordan (`C:\Users\jorda\Triskell\`). Cet audit ne couvre que PC1 (OneDrive). À refaire si PC2 a divergé.

---

## 6. Synthèse en 1 paragraphe

La v0.4 est mature, le manifeste DESIGN.md est solide, les patches PATCHES.md sont prêts. Le travail principal n'est pas inventer mais **diffuser** : faire vivre le design system v2 dans les 14 vues, appliquer les 7 patches de la Matinale, mettre le pulse-bus dans Phare. Trois compléments à DESIGN.md méritent d'être ajoutés (refonte sidebar par mission, palette Ctrl+K, status bar épurée). Tout le reste découle.
