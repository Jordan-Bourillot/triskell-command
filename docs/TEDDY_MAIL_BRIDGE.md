# Pont Triskell Command ↔ Teddy Mail

État : **v1 livrée le 2026-05-07.** Couvre les 3 niveaux d'intégration
demandés. Fonctionne avec Teddy Mail v0.5.1 (Tauri) sans aucune
modification de Teddy Mail. Une migration douce est prévue pour V0.6 (cf.
section Roadmap en bas).

## Ce qui est branché aujourd'hui

### 1. Lancement de l'app depuis n'importe où

- **Spotlight Ctrl+K** → tape "ted" → Entrée → Teddy Mail s'ouvre.
- **Matinale** → bouton « Ouvrir Teddy Mail » dans le hero.
- **Cartes Replies** → bouton « Ouvrir Teddy Mail » sur chaque réponse.
- **API JS** : `Teddy.open()` depuis n'importe quel script de la web UI.
- **API Python** : `App.api.open_teddy_mail()` depuis le front.

Mécanique : l'`exePath` de Teddy Mail est lu dans
`Triskell 0 - Lanceur/apps.json` (id `teddy-mail`), puis lancé via
`subprocess.Popen`. Aucun chemin hardcodé côté JS.

### 2. Composition pré-remplie depuis une réponse

Sur chaque carte de la vue Réponses, un bouton « Répondre via Teddy Mail »
ouvre la fenêtre de composition du **client mail défini par défaut**
sous Windows, pré-remplie avec :

- `to`      = l'email du prospect
- `subject` = `Re: <sujet original>` (sans doubler le `Re:` s'il est déjà là)
- `body`    = vide (à remplir librement)

Mécanique : `mailto:` URL → `os.startfile()` côté Windows → handler
système qui ouvre **Teddy Mail si Jordan l'a configuré comme client
mail par défaut** (Paramètres Windows → Apps par défaut → Mail).

Si Teddy Mail n'est pas le défaut, c'est le client défaut qui s'ouvre
(Outlook, Thunderbird…). Comportement standard, attendu.

### 3. Composition libre

- **Matinale** → bouton « Composer un mail ».
- **Raccourci global** → `Ctrl+Shift+M` depuis n'importe quelle vue.
- **API JS** : `Teddy.compose({to, subject, body, cc, bcc})`.
- **API Python** : `App.api.compose_mail({to, subject, body, cc, bcc})`.

## Architecture

```
[Vue Replies / Morning / …]      [Raccourci Ctrl+Shift+M]
            │                             │
            └──────────► Teddy.open()  ──┴───► App.api.open_teddy_mail()
                         Teddy.compose()      App.api.compose_mail()
                                              │
                            ┌─────────────────┴────────────────┐
                            ▼                                  ▼
                    subprocess.Popen                  os.startfile("mailto:…")
                    (teddy-mail-shell.exe)            (handler système Windows)
```

Le helper JS `web/ui/scripts/teddy.js` est **un point d'entrée unique** :
toutes les vues passent par lui. Migration vers IPC native sera
transparente pour les vues consommatrices.

## Pourquoi pas une intégration plus profonde aujourd'hui

État du Teddy Mail v0.5.1 (audit du repo `Prompts/pite_lafe_mail`) :

- C'est une app **Tauri** (Rust + frontend React).
- Les commandes IPC (`send_mail`, `search`, `mark_read`, …) existent
  mais sont **internes au webview** : pas exposées en CLI, pas exposées
  en HTTP, pas de custom URL scheme déclaré.
- Le backend mail (`teddy_mail_core`) compile en V0.5 mais n'est pas
  encore branché aux commandes IPC : `send_mail` retourne *« Mail sync
  not yet integrated — coming in V0.6 »*.

Conséquence pratique : **rien de plus puissant que `mailto:` n'est
faisable côté Command sans modifier Teddy Mail**.

## Roadmap : ce qu'on branchera quand Teddy Mail v0.6 sortira

V0.6 doit livrer les commandes IPC réelles (envoi IMAP/SMTP, lecture
Store, recherche). Pour ouvrir un canal **Command → Teddy**, deux
options non exclusives :

### Option A — Custom URL scheme (la plus simple)

Déclarer `teddy://` dans `tauri.conf.json` puis brancher un handler
dans le shell Rust :

```rust
// dans main.rs
.setup(|app| {
    app.deep_link().on_open_url(|event| {
        let urls = event.urls();
        // urls = ["teddy://compose?to=foo@bar.com&subject=Hello&body=..."]
        // → router vers la vue Compose pré-remplie
    });
    Ok(())
})
```

Côté Command, on remplace `os.startfile("mailto:…")` par
`os.startfile("teddy://compose?…")`. Aucune autre modification
nécessaire — `compose_mail()` et `Teddy.compose()` gardent la même
signature.

**Effort :** ~2h côté Teddy Mail (déclaration scheme + handler) + 5
lignes côté Command.

### Option B — Serveur HTTP local (plus puissant, plus engageant)

Teddy Mail expose un serveur sur `127.0.0.1:<port>` avec un endpoint
`POST /compose` (et plus tard `/threads/:id`, `/send`, etc.).
Authentification par token local stocké dans le keyring.

Permettrait à Command de :

- ouvrir Teddy Mail directement sur **un thread précis** (au lieu de
  juste lancer l'app) → bouton « Ouvrir ce fil dans Teddy »
- déléguer l'envoi des mails outreach à Teddy (mutualisation des
  comptes IMAP/SMTP, fini la double config)
- afficher dans Command des **infos extraites de Teddy** (compteurs
  unread, dernier sync, …)

**Effort :** ~1 jour côté Teddy Mail (serveur axum + auth + endpoints)
+ ~1 jour côté Command (client HTTP + nouveaux boutons).

### Recommandation

Faire **A** dès la V0.6 (gain immédiat, effort minime), puis **B** dans
la foulée si on veut vraiment unifier les comptes mail.

## Fichiers touchés (référence)

### Côté Triskell Command (web)

- `triskell_command/web/api.py` :
  `_resolve_teddy_exe()`, `open_teddy_mail()`, `compose_mail()`,
  `launch_app()` (déjà existant), `get_apps_catalog()` expose `exe_path`
- `triskell_command/web/ui/scripts/teddy.js` (nouveau) :
  `Teddy.open()`, `Teddy.compose()`, `Teddy.button(opts)`,
  délégation globale sur `.teddy-btn`
- `triskell_command/web/ui/scripts/replies.js` :
  boutons « Répondre via Teddy » + « Ouvrir Teddy » sur chaque carte
- `triskell_command/web/ui/scripts/morning.js` :
  boutons « Ouvrir Teddy Mail » + « Composer un mail » dans le hero
- `triskell_command/web/ui/scripts/app.js` :
  raccourci `Ctrl+Shift+M` → `Teddy.compose()`
- `triskell_command/web/ui/index.html` :
  inclusion `<script src="scripts/teddy.js"></script>`

### Côté catalogue Triskell

- `Triskell 0 - Lanceur/apps.json` :
  entrée `id: "teddy-mail"` (catégorie `quotidien`, tier `free`,
  `installed: true`, `exePath` vers `teddy-mail-shell.exe`)
- `Triskell Command/scripts/normalize_app_logos.py` :
  mapping `teddy-mail` → logo PNG normalisé 256×256 transparent
- `Triskell Command/scripts/add_teddy_mail_to_catalog.py` :
  script idempotent d'ajout au catalogue (déjà exécuté)
