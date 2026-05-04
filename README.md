# Triskell Command

**Outil interne unique** de Jordan / Triskell Studio.

App desktop qui pilote tout l'écosystème Triskell depuis une seule fenêtre :

- 🔎 **Trouver des prospects** — toutes sources (créateurs YT/Twitch/Reddit + entreprises FR Sirene + commerces Maps)
- 💬 **Rédiger avec l'IA** — méga-prompts + 5 providers (Anthropic, OpenAI, Google, Mistral, xAI)
- ✉ **Envoyer & suivre** — campagnes mail, relances, détection des réponses
- 📡 **Publier** — branche le service Réseaux quand il tourne en local
- 📊 **Tableau de bord** — KPIs

## Pour qui ?

**Uniquement pour Jordan.** Pas vendu, pas distribué. Outil de travail interne.

Les produits commerciaux (Le Dénicheur, Sales Tunnel, AlphaBeast, AlphaCast)
restent leurs propres apps, vendues séparément. Triskell Command est le **cockpit
qui les chapeaute en interne**.

## Stack

- Python 3.10+ (testé Python 3.12)
- CustomTkinter (cohérent avec Sales Tunnel et AlphaBeast)
- [`Triskell Core`](../Triskell%20Core/) — bibliothèque partagée pour la prospection et l'IA

## Lancement

```bash
cd "Triskell Command"
pip install -r requirements.txt
python run.py
```

## Données

```
~/.triskell-command/
├── settings.json     ← clés API + préférences UI
└── (le CRM est partagé avec Triskell Core dans ~/.triskell-prospect/)
```

## Architecture

```
triskell_command/
├── main.py          ← TriskellCommandApp
├── theme.py         ← palette Triskell (héritée du Sales Tunnel)
├── state.py         ← état global app + persistance
├── widgets/
│   ├── sidebar.py   ← barre de navigation 5 onglets
│   └── components.py← cards, boutons, chips
└── views/
    ├── prospects.py ← 🔎 Trouver
    ├── compose.py   ← 💬 Rédiger
    ├── campaigns.py ← ✉ Envoyer
    ├── publish.py   ← 📡 Publier
    ├── dashboard.py ← 📊 Tableau de bord
    └── config.py    ← ⚙ Config (clés API, SMTP, etc.)
```
