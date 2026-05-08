# UX Audit — Triskell Command v0.4

**Date** : 2026-05-08
**Périmètre** : audit externe de la v0.4 (commit `6e80d2a`).
**Lecture conseillée** : dans l'ordre numérique. ~25 minutes pour les 4 fichiers.

## Contenu

| Fichier | Objet | Quand le lire |
|---|---|---|
| [00_AUDIT.md](00_AUDIT.md) | Diagnostic v0.4 : forces préservées, plafond d'adoption design system, 3 angles non couverts par DESIGN.md, audit vue par vue, bugs latents. | Pour comprendre **où l'app plafonne aujourd'hui**. |
| [01_NAVIGATION.md](01_NAVIGATION.md) | Refonte sidebar 16→11 par mission, palette Ctrl+K, status bar repositionnée, FABs bornés. | Pour décider **comment naviguer mieux**. |
| [02_PARCOURS.md](02_PARCOURS.md) | 5 parcours utilisateurs (démarrer journée / acquérir / communiquer / Phare / mesurer). Aujourd'hui vs Cible + frictions critiques. | Pour valider **les flows complets**. |
| [03_ROADMAP.md](03_ROADMAP.md) | Matrice effort×valeur, 4 sprints d'1 semaine, garde-fous, risques, points reportés. | Pour décider **quoi faire en premier**. |

## Articulation avec l'existant

Cet audit **complète** sans dupliquer :

- **`docs/DESIGN.md`** (manifeste design 2026-05-07) — couvre tokens, manifeste, 5 axes d'élévation, anti-checklist, livraisons. Reste référence.
- **`docs/PATCHES.md`** — 7 patches chirurgicaux Matinale + Phare. Application opérationnelle de DESIGN.md axes C et D.

Trois compléments majeurs apportés par cet audit (à intégrer à DESIGN.md dans une prochaine itération si pertinent) :

1. **Plafond d'adoption** : `tokens_v2.py` et `components_pro.py` codés mais utilisés par 2 fichiers seulement sur 14+. Sans migration coordonnée, le design system v2 reste lettre morte.
2. **Sidebar par mode d'exécution** : *L'app travaille pour toi* vs *À la main* impose à l'utilisatrice de connaître l'implémentation. Refonte par mission proposée.
3. **Palette Ctrl+K absente** : standard moderne pour les apps cockpit, payant immédiatement avec 14 vues + entités multiples.

## Synthèse en 3 lignes

La v0.4 est largement plus mature que sa documentation publique le laisse penser. Le travail principal n'est pas d'inventer mais de **diffuser** : faire vivre le design system v2 partout, appliquer les patches PATCHES.md, ajouter palette Ctrl+K et refondre la sidebar par mission. Tout le reste découle.

## Notes de méthode

- Lecture incomplète assumée : 11 vues sur 14 n'ont pas été lues en profondeur (cf. [00_AUDIT §5](00_AUDIT.md)). À combler dans une session dédiée (cf. ROADMAP G1-G4).
- Parle de l'état **observé en code**, pas de l'état perçu en usage. Une session d'observation 1h avec Jordan complèterait l'audit côté ressenti.
- Métriques quantitatives non mesurées (cf. ROADMAP §3.5). Elles deviennent nécessaires dès Sprint 1.
