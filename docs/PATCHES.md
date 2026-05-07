# Patches design — Matinale & Le Phare

Compagnon de `DESIGN.md` (axes C et D du plan d'élévation). Ce document
ne propose **aucune réécriture complète**. Seulement des patches
chirurgicaux ciblés, à appliquer ou à ignorer un par un. La règle
"pas de big bang" du manifeste est respectée.

Pour chaque patch : zone du code, intention, avant/après, bénéfice.

---

## Matinale (`views/morning.py`)

Le diagnostic du `DESIGN.md` était partiellement faux : la matinale
est déjà très bien architecturée. Hero personnalisé, priorité unique
mise en avant, hier en 3 chiffres, aujourd'hui en 2, à corriger
conditionnel, Phare conditionnel. Tout cela est juste.

Ce qui peut être élevé :

### Patch M1 — KpiHero avec sparkline pour "Hier en chiffres"

**Zone** : `_yesterday_block()` (ligne ~237)
**Intention** : transformer les 3 `StatCard` en `KpiHero` (composant
ajouté dans `widgets/components_pro.py`) avec sparkline 7 jours pour
contextualiser le chiffre.

**Avant** :
```python
StatCard(grid, label="Mails envoyés", value=str(sent_y),
         delta=f"{digest['sent']['last_7d']} sur les 7 derniers jours",
         colors=c).grid(...)
```

**Après** :
```python
from ..widgets.components_pro import KpiHero
# digest doit fournir digest["sent"]["daily_last_7d"] : list[int] de
# 7 valeurs (lundi → dimanche). À ajouter dans morning_digest.py.
KpiHero(grid, colors=c,
        label="Mails envoyés",
        value=str(sent_y),
        delta_value=f"{digest['sent']['last_7d']} en 7 jours",
        delta_kind="up" if sent_y > digest['sent'].get('day_before', 0) else "neutral",
        sparkline=digest['sent']['daily_last_7d']
        ).grid(row=0, column=0, padx=(0, T.SPACE_MD), sticky="ew")
```

**Bénéfice** : le chiffre devient lisible **avec son contexte**. Un
"42" seul ne dit rien ; "42 + courbe en hausse depuis 4 jours" se lit
en moins d'une seconde et déclenche une décision.

**Coût** : ajouter `daily_last_7d` au dict `digest` dans
`integrations/morning_digest.py` (3 lignes). Pas d'autre dépendance.

---

### Patch M2 — Filet accent or au-dessus du hero greeting

**Zone** : `_hero()` (ligne ~127)
**Intention** : la Matinale est le rituel matinal. Lui donner sa
signature visuelle propre — un filet **or** (pas indigo) de 32 px de
large au-dessus de la salutation. C'est le seul endroit où l'or
remplit, par dérogation explicite.

**Avant** : pas de filet, juste `_date_phrase().upper()` directement.

**Après** :
```python
# Filet accent OR (signature de la Matinale uniquement)
bar = ctk.CTkFrame(wrap, fg_color=c.gold,
                   width=32, height=3, corner_radius=2)
bar.pack(anchor="w", pady=(0, T.SPACE_SM))
bar.pack_propagate(False)

# (existant) Petit label date discret
ctk.CTkLabel(wrap, text=_date_phrase().upper(), ...)
```

**Bénéfice** : la Matinale gagne un sceau qui la distingue des autres
vues (dont le filet est en `c.accent` indigo). Renforce le statut
"rituel" du moment matinal.

**Règle d'or** : ce filet or n'apparaît **nulle part ailleurs** dans
l'app. C'est exclusif à la Matinale. Si on le réutilise, l'effet meurt.

---

### Patch M3 — Phrase de transition contextuelle

**Zone** : `_hero()` (ligne ~151), juste après le greeting.
**Intention** : la phrase actuelle "Voilà ce qui t'attend aujourd'hui."
est bonne mais constante. La rendre contextuelle au state :

```python
def _transition_phrase(digest: dict) -> str:
    queue = digest.get("queue", {}) or {}
    if queue.get("replies_unhandled_interested", 0) > 0:
        return "Tu as une vraie occasion ce matin."
    if (queue.get("drafts_prospect_pending", 0) +
        queue.get("drafts_convoy_pending", 0)) > 0:
        return "Quelques validations rapides et tu débloques la journée."
    if queue.get("replies_unhandled_total", 0) > 0:
        return "Un peu de tri à faire avant d'attaquer."
    return "Aucune urgence. Le terrain est libre."
```

**Bénéfice** : l'app adresse l'utilisateur, pas son inbox. Texte qui
change selon le contexte = présence vivante. Coût : 8 lignes.

---

### Patch M4 — `tnum` (tabular nums) sur les KPIs

**Zone** : composants `StatCard` ou (si M1 appliqué) `KpiHero`.
**Intention** : forcer les chiffres à occuper la même largeur de
caractère (lignage vertical des "1 248", "47", "100 %"). C'est
exactement la différence qui fait paraître un dashboard pro.

**Comment** : Inter Tabular variant n'est pas natif dans CustomTkinter,
mais on peut tenter `font=("Inter Tabular", 36, "bold")` puis tester
si Tk le résout. Sinon, fallback sur `Inter` standard (pas bloquant).

**Bénéfice** : marginal mais visible quand on a 3 KPIs côte à côte.

---

## Le Phare (`views/phare.py`)

Le Phare est l'opposé de la Matinale : il a grandi très vite (5 onglets,
9+ cartes mission, scheduler, bulletin PDF) et la densité commence à
être maladroite. Trois patches structurels.

### Patch P1 — Réduire les 4 KPIs Écosystème à 3

**Zone** : `_build_ecosystem()` (ligne ~215)
**Intention** : 4 KPIs côte à côte = surcharge cognitive. Le manifeste
recommande 3 max. Le KPI à fusionner : "Clics organiques 30j" et
"Impressions 30j" → un seul "Performance 30j" avec les deux infos
empilées (clic en grand, impressions en delta).

**Après** :
```python
kpis = ctk.CTkFrame(parent, fg_color="transparent")
kpis.pack(fill="x", pady=(0, T.SPACE_MD))
for i in range(3):                              # 4 → 3
    kpis.grid_columnconfigure(i, weight=1, uniform="phare_kpi")

KpiHero(kpis, colors=c,
        label="Sites surveillés",
        value=str(len(overview["sites"])),
        ).grid(row=0, column=0, sticky="nsew", padx=(0, T.SPACE_MD))

KpiHero(kpis, colors=c,
        label="Performance 30 j",
        value=_fmt_int(totals.get("organic_clicks_30d", 0)),
        delta_value=f"sur {_fmt_int(totals.get('impressions_30d', 0))} impressions",
        delta_kind="neutral",
        ).grid(row=0, column=1, sticky="nsew", padx=(0, T.SPACE_MD))

KpiHero(kpis, colors=c,
        label="Actions en attente",
        value=str(totals.get("actions_pending", 0)),
        accent=c.accent if totals.get("actions_pending", 0) else "",
        ).grid(row=0, column=2, sticky="nsew")
```

**Bénéfice** : un coup d'œil suffit pour savoir où on en est. Le
ratio impressions/clics reste lisible mais cesse d'occuper sa propre
colonne.

---

### Patch P2 — Onglet "Avancé" → DrawerRight

**Zone** : `TABS` (ligne ~75) + `_build_advanced()`
**Intention** : l'onglet "Avancé" contient des **outils ponctuels**
(CTR booster, Snippet hunt, GEO check, Cannibalisation, etc.). Ce
n'est pas une vue de pilotage régulier — ce sont des **boutons
rouges** qu'on actionne 1 fois par semaine. Les remplacer par un
drawer qui s'ouvre sur clic sur un bouton "Outils avancés" dans le
header.

**Avant** : 5 onglets dont "Avancé" qui occupe 1/5 de l'attention.
**Après** : 4 onglets de pilotage régulier (Écosystème, Site,
Modifications en attente, Bulletins) + 1 bouton "Outils avancés" qui
ouvre un `DrawerRight` (composant `widgets/components_pro.py`).

**Squelette** :
```python
from ..widgets.components_pro import DrawerRight

# Dans build():
self._adv_drawer = DrawerRight(self, colors=c, width=420)
self._adv_drawer.add_title("Outils avancés du Phare")
# Construire le contenu une seule fois, pas à chaque ouverture
self._build_advanced(self._adv_drawer.content)

# Bouton header :
SecondaryButton(header.actions, colors=c, icon="settings",
                text="Outils avancés",
                command=self._adv_drawer.toggle
                ).pack(side="left", padx=(0, T.SPACE_SM))

# Retirer "advanced" de TABS et de _refresh_active_tab()
```

**Bénéfice** : la nav haute reprend un visage de pilotage régulier.
Les actions ponctuelles restent accessibles d'un clic mais cessent
de prendre l'écran principal. Le scheduler continue à tourner sans
qu'on aie à voir ses commandes manuelles.

---

### Patch P3 — "Hero question" en haut de chaque onglet

**Zone** : début de chaque `_build_*()` méthode
**Intention** : avant la grille de KPIs, poser **une seule question
en français** que l'onglet doit répondre. Donne un fil narratif au
cockpit data-heavy.

**Exemples** :
- Écosystème : *« Comment se portent les 13 sites de l'écosystème ? »*
- Site : *« Que se passe-t-il sur ce site ? »*
- Modifications en attente : *« Qu'est-ce qui attend mon validateur ? »*
- Bulletins : *« Qu'est-ce que Le Phare a appris ce mois-ci ? »*

**Implémentation** (composant à ajouter dans `components_pro.py`) :
```python
class HeroQuestion(ctk.CTkLabel):
    """Question narrative en haut de vue data-heavy."""
    def __init__(self, master, *, text: str, colors: T.ThemeColors):
        super().__init__(
            master, text=text,
            font=(T.FONT_FAMILY_DISPLAY, 22, "normal"),
            text_color=colors.text_secondary,
            anchor="w", justify="left",
        )
```

**Usage** :
```python
def _build_ecosystem(self, parent):
    HeroQuestion(parent, colors=self.colors,
        text="Comment se portent les sites de l'écosystème ?"
    ).pack(fill="x", pady=(T.SPACE_LG, T.SPACE_MD))
    # ... le reste comme avant
```

**Bénéfice** : transforme une vue technique en récit. L'utilisateur
sait ce qu'il vient chercher. Effet "j'ouvre une page de magazine pro",
pas "j'ouvre un Excel".

---

## Stratégie d'application

Aucun de ces patches n'est urgent. Les appliquer dans cet ordre minimise
le risque :

1. **Patch M2** (filet or matinale) — 5 lignes, zéro impact ailleurs.
2. **Patch M3** (phrase contextuelle) — 8 lignes, autonome.
3. **Patch P3** (HeroQuestion sur les onglets) — composant + 5 usages,
   décoratif.
4. **Patch M1** (KpiHero matinale) — demande étendre `morning_digest.py`,
   testable indépendamment.
5. **Patch P1** (KPIs Phare 4→3) — restructure une grille existante,
   risque modéré.
6. **Patch P2** (Avancé → Drawer) — patch structurel, demande tester
   le drawer sur Tk avant. Le plus impactant visuellement.

**Patch M4** (tnum) : à laisser pour quand on aura testé que Tk résout
correctement la variante.

Chaque patch peut être livré dans son propre commit pour que le
rollback soit propre si quelque chose surprend.
