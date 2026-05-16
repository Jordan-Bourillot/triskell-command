# Quoi de neuf dans Triskell Command

Toutes les nouveautés récentes regroupées par thème, avec **comment y accéder** et **ce que ça fait**. Si tu cherches comment lancer une fonctionnalité, c'est ici.

---

## 🎛 Le Cockpit (ex-Matinale)

L'écran d'accueil s'appelle maintenant **Cockpit**. Il regroupe en un coup d'œil ce qui t'attend aujourd'hui.

**Boutons du header (en haut)** :
- **Rafraîchir** — recharge les chiffres en direct
- **Composer un mail** — propose 2 choix : nouveau mail OU prospection en direct
- **Brain** — ajoute une note rapide (raccourci `Ctrl+B`)
- **Allô Claude** — pose une question, Claude analyse l'état actuel et te donne la prochaine action concrète
- **Concentration** — bascule en mode focus (voir plus bas)

**Clic sur le logo "Triskell Command"** en haut de la sidebar = retour au Cockpit depuis n'importe où.

---

## 🔍 Recherche globale (`Cmd+K` ou `Ctrl+K`)

Depuis n'importe où dans l'app, tape `Cmd+K`. Une palette s'ouvre et te laisse chercher dans :
- Toutes les vues navigables
- Tes clients (kanban projets)
- Tes mails récents (100 derniers)
- Tes brouillons à valider
- Tes notes Brain
- Tes modèles d'emails et signatures

Flèches `↑↓` pour naviguer, `Entrée` pour ouvrir, `Échap` pour fermer. Recherche fuzzy (peu importe l'ordre des mots).

---

## ✉ Composer mail moderne

Quand tu écris un mail, tu as maintenant :

- **Destinataires en pastilles colorées** : tape une adresse, valide avec `Tab`, `Entrée`, `,`, `;` ou espace après email valide → l'adresse devient une chip violette. Pastille rouge si invalide.
- **+ Cc / + Cci** : 2 boutons à droite du libellé pour révéler les lignes copies.
- **HTML enrichi par défaut** : gras, italique, listes, liens, titres, citations, coller HTML brut.
- **Bouton 🖼 dans la barre d'outils** : insère une image dans le corps du mail. Tu peux aussi glisser-déposer un fichier dans la fenêtre — choix "Dans le corps" ou "En pièce jointe".
- **Clic sur une image insérée** → modale pour la rendre cliquable (URL de redirection).
- **Pièces jointes** : section dédiée, limite 22 Mo total, drag&drop supporté.
- **Bouton Brouillon** : sauve l'état du mail dans le navigateur. Reviens plus tard, un bandeau te propose de restaurer.
- **Bouton ⏱ Plus tard** : programme l'envoi à une date/heure choisie (raccourcis "Dans 1h", "Ce soir 18h", "Demain 9h", "Lundi 9h" ou date libre). Le mail part automatiquement à l'heure dite, même si tu fermes l'app.
- **Icône crayon à côté de "Sans signature"** : ouvre Réglages pour gérer tes signatures (sauve le brouillon en cours avant de basculer).

**Plus de fermeture accidentelle** : la modale ne se ferme plus en cliquant à côté ou avec `Échap`. Seuls `×` et `Annuler` ferment. Si tu cliques Annuler avec du contenu rédigé, on te demande si tu veux enregistrer en brouillon avant.

---

## ⚡ Prospection en direct

Bouton **"Prospection en direct"** dans la vue Mails (et choix proposé quand tu cliques "Composer un mail" depuis le Cockpit).

Workflow :
1. Tu choisis **Célébrité** (→ Sportif ou Influenceur) ou **Entreprise** (→ Site modèle ou Première personnalisation).
2. Tu colles l'URL du site que tu as réalisé pour eux.
3. Claude (15-40 sec) :
   - télécharge le contenu du site
   - capture un aperçu en 1280×720
   - lit tes modèles HTML et choisit le plus adapté
   - rédige un mail personnalisé qui présente le site et cite des éléments précis
4. Le composer s'ouvre pré-rempli, l'aperçu du site est en pièce jointe inline.

Claude garde la **structure HTML de tes modèles** (couleurs, blocs, boutons) et ne remplace que le contenu textuel.

---

## 👤 Mon profil personnel

Clic sur ta photo / prénom en bas de la sidebar → modale **"Profil personnel"** (séparée des Réglages app).

Tu y modifies :
- Ta photo de profil
- Ton nom complet (le prénom apparaît en bas de sidebar)
- Ton email principal

Toi et Thomas avez chacun votre profil distinct (stocké par utilisateur, persistant).

---

## 🔔 Notifications push

Bouton dans la sidebar (sous le badge utilisateur) — 3 états visuels distincts :

- **Désactivées** : bouton coloré "Activer les notifications" (clair appel à action)
- **Activées** : bouton vert "Notifications activées" + bouton Test pour vérifier
- **Bloquées par le navigateur** : encart rouge expliquant comment débloquer

Les notifs reçues sont **priorisées** (urgent / normal / low) et **groupées** : si 3+ notifs similaires arrivent en 5 min, elles fusionnent en "X événements".

---

## 📋 Page Revenus

Nouvelle vue dans la sidebar (section **Chiffres**) → **Revenus**.

Tu y vois :
- **Total du mois en cours** avec évolution % vs mois précédent
- **Encaissements** sur 7 jours / 30 jours
- **Top clients** du mois (montant cumulé)
- **Répartitions** par source (Stripe / AppSumo / manuel) et par produit
- **Forecast fin de mois** (extrapolation avec marge de confiance)

Les paiements sont agrégés depuis Stripe, AppSumo et les projets clients manuels — aucune double comptabilisation.

---

## 🎬 Mode démo

Réglages → **"Activer le mode démo"**.

L'app se recharge et toutes tes données sont remplacées par des fakes crédibles (214 clients actifs, 83 240 €/mois, 12 prospects intéressés à recontacter, etc.). **Aucune action n'est réelle** — tu peux cliquer "Envoyer", "Sauvegarder", rien ne part au serveur.

Idéal pour des screenshots de promo. Bandeau rouge/orange "MODE DÉMO" en haut, avec bouton "Masquer 30 sec" pour une capture propre et "Désactiver" pour sortir.

---

## 🎯 Mode Concentration

Bouton **"Concentration"** dans le header Cockpit.

Modale "Sur quoi tu te concentres ?" : tu tapes ton intention (ex : "livrer le site Lefèvre") + tu choisis une durée (15/30/60/120 min). Pendant la session :
- Overlay plein écran avec ton intention en grand + timer countdown
- Notifs masquées
- KPIs anxiogènes du Cockpit floutés
- Bouton "+ 15 min" pour prolonger

Persiste si tu rafraîchis la page.

---

## 💾 Backups automatiques

Tous les 7 jours, l'app sauvegarde tes données critiques (modèles, signatures, comptes mail sans mdp, notes Brain, projets clients, mails programmés) dans `~/.triskell-command/backups/`.

Les 12 derniers backups sont conservés (~3 mois). Visible dans **Réglages → Sauvegardes automatiques**, avec un bouton "Faire un backup maintenant" si besoin.

---

## 🐛 Signaler un bug

Petit bouton triangulaire en bas à gauche de l'écran, partout dans l'app.

Au clic, une modale ouvre un champ libre + collecte automatiquement :
- La vue active
- L'URL
- Le navigateur
- Les erreurs JS récentes
- Les appels API en erreur récents

Tu peux soit envoyer (sauvegarde côté serveur) soit copier le rapport pour l'envoyer à la main.

---

## 🔁 Catch-up "Depuis ta dernière visite"

Quand tu reviens sur l'app après plus d'une heure d'absence, un petit toast s'affiche en haut à droite : "Depuis ta dernière visite, X nouveaux mails, Y prospects intéressés à recontacter, Z brouillons à valider".

Clic sur un item → bascule sur la vue. Auto-dismiss après 25 sec.

---

## ⌨ Raccourcis clavier

Appuie sur `?` n'importe où dans l'app pour afficher la liste complète des raccourcis :

| Raccourci | Action |
|-----------|--------|
| `Ctrl+K` | Recherche globale |
| `Ctrl+B` | Brain — note rapide |
| `Ctrl+T` | Cycler le thème |
| `Ctrl+Shift+M` | Composer un mail |
| `Ctrl+Entrée` | Envoyer le mail (dans composer) |
| `Tab` / `Entrée` | Valider une adresse en pastille |
| `Échap` | Fermer la modale active |

---

## 🛡 Garde-fous (visibles seulement si bug)

Plusieurs systèmes invisibles tournent en permanence pour anticiper les soucis :

- **HealthCheck** capte toutes les erreurs JS silencieuses et affiche un toast rouge en bas à droite. Pour debug : tape `HealthCheck.dump()` dans la console (F12).
- **Validateur fakes mode démo** : au boot en mode démo, vérifie que tous les fakes respectent leur schéma attendu. Log les anomalies dans la console.
- **Monitoring API** : les appels > 3 sec ou en erreur sont loggés avec contexte.

---

## 📍 Où trouver tout ça

- **Tuto guidé complet** : Réglages → Visite guidée. 23 étapes pour découvrir toute l'app.
- **Aide contextuelle** : bouton `?` en haut à droite de chaque vue (Cockpit, Mails, Réponses, etc.).
- **Ce fichier** : `docs/WHATS_NEW.md` — récap des dernières features.
