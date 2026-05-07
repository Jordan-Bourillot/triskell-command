# Triskell Command

**Outil interne unique** de Jordan / Triskell Studio.

App desktop qui pilote tout l'écosystème Triskell depuis une seule fenêtre :

- 🔎 **Trouver des prospects** — toutes sources (créateurs YT/Twitch/Reddit + entreprises FR Sirene + commerces Maps)
- ✉ **Le Convoi** — importe une liste externe (PDF/Word/Excel/image), détecte le secteur, adapte ton catalogue, envoie en auto ou validation
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
├── integrations/
│   ├── convoy_parser.py ← extraction fichiers (PDF, Word, Excel, OCR…)
│   ├── convoy_ai.py     ← structuration IA + génération messages
│   └── convoy_runner.py ← campagnes Convoi + file SMTP
└── views/
    ├── autopilot.py ← 🚀 Pipeline complet (depuis Sirene/Maps)
    ├── convoy.py    ← ✉ Le Convoi (depuis fichier importé)
    ├── drafts.py    ← ✅ À valider
    ├── prospects.py ← 🔎 Trouver
    ├── compose.py   ← 💬 Rédiger
    ├── templates.py ← 📄 Modèles
    ├── campaigns.py ← ✉ Envoyer
    ├── publish.py   ← 📡 Publier
    ├── dashboard.py ← 📊 Tableau de bord
    └── config.py    ← ⚙ Config (clés API, SMTP, etc.)
```

## Le Convoi

Module qui prend en entrée une liste de prospects fournie par l'utilisateur
(PDF, Word, Excel, CSV, image OCR ou texte brut) et qui :

1. **Extrait** le texte du fichier (avec dégradation gracieuse si openpyxl /
   python-docx / pypdf ne sont pas installés).
2. **Structure** par IA chaque ligne en prospect : raison sociale, contact,
   email, téléphone, adresse, secteur d'activité, etc. Tableau éditable
   avant envoi, avec signalement des lignes incomplètes.
3. **Adapte** automatiquement le catalogue d'offres au secteur de chaque
   prospect (matching mots-clés). Brief IA libre par campagne.
4. **Envoie** en mode AUTO (tout d'un coup après confirmation) ou en mode
   VALIDATION (un mail à la fois). Cap quotidien + délai entre envois.

Stockage : `~/.triskell-command/convoy/campaigns/<timestamp>_<slug>.json`.
Une campagne par fichier importé. Pas de réseau : tout reste local.
