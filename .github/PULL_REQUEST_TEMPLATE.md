<!--
Template par défaut pour Triskell Command. Inspiré de docs/DESIGN.md
et docs/ux/03_ROADMAP.md (garde-fou §3.4).
-->

## Quoi

<!-- 1-3 phrases : ce que fait cette PR. Pas le « comment ». -->

## Pourquoi

<!-- Référence à un patch de PATCHES.md, un axe de DESIGN.md, ou
     une décision de docs/ux/. Si rien : décris le besoin utilisateur. -->

## Vérifications avant merge

### Si la PR touche une vue ou un widget UI

- [ ] L'app démarre sans erreur (`py -3.12 run.py`)
- [ ] Screenshot **DARK**
- [ ] Screenshot **MID**
- [ ] Screenshot **LIGHT**
- [ ] Empty state vérifié (vue affichée vide → message + CTA cohérents)
- [ ] Aucune nouvelle police codée en dur — utilisation de `tokens_v2.ttype`
- [ ] Aucun nouvel espacement codé en dur hors `T.SPACE_*`

### Si la PR touche un worker background ou un runner

- [ ] Le worker émet via `pulse_bus.report(...)` à chaque tick
- [ ] L'erreur passe en `state="error"` avec `error_message` non vide
- [ ] Le cycle est documenté (commentaire docstring)

### Si la PR touche le routing / la sidebar

- [ ] `VIEW_REGISTRY` dans `main.py` à jour
- [ ] Raccourci `Ctrl+N` à jour si applicable (cf. `_bind_shortcuts`)
- [ ] Comportement des FABs `Claude` / `Thomas` non régressé

### Toujours

- [ ] Aucun secret en clair dans le diff
- [ ] Aucun emoji ajouté en navigation ou en titre de vue (cf. DESIGN.md anti-checklist §7)
- [ ] Microcopy d'erreur sec (« SMTP a renvoyé 535 », pas « Le messager n'a pu rejoindre »)
