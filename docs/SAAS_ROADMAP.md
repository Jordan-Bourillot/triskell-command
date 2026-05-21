# Triskell Command — Route vers le SaaS

**Mise à jour** : 2026-05-16
**Statut global** : socle technique posé, reste mise en route opérationnelle.

---

## Ce qui vient d'être livré (2026-05-16)

### 1. Catalogue central unique
- Module : `triskell_command/integrations/catalog_repo.py`
- Stocké dans `shared_settings.convoy_catalog` (Supabase) + miroir local
  `~/.triskell-command/catalog.json` + fallback `DEFAULTS`.
- La vue Le Convoi lit toujours le central, les sauvegardes vont dans le
  central. Plus de copies par campagne (un snapshot reste dans
  `camp.catalog` à fins de traçabilité).

### 2. Fichier client automatique
- À chaque envoi réussi du Convoi, `_upsert_client_from_draft` appelle
  `clients_master_repo.ensure_client` avec `source="convoy"`.
- Best-effort : si la fiche client est down, l'envoi continue.
- Idempotent : un client existant n'est jamais écrasé.

### 3. Démo vidéo (matériel)
- PDF de démo : `docs/demo_convoi/chantiers_mairie_lannion_mars_2026.pdf`
  (10 entreprises BTP fictives, 1 page, propre).
- Script vidéo : `docs/demo_convoi/SCRIPT_VIDEO.md` — 75 sec, voix off
  mot à mot, storyboard plan par plan.
- Reste à toi : tourner (Loom recommandé) → 30 min de boulot.

### 4. Landing publique
- `landing/index.html` + `landing/styles/main.css` + `landing/scripts/main.js`
- 3 thèmes (clair / intermédiaire / sombre), sélecteur visible header.
- Sections : hero, fonctionnalités, démo, tarifs, waitlist, FAQ, footer.
- Mentions légales Triskell Studio en dur.
- `landing/netlify.toml` prêt — déployable tel quel.
- Domaine cible : **triskell-command.fr** (à acheter chez IONOS).

### 5. Fondations multi-clients (SQL préparé, PAS appliqué)
- `supabase/20_multi_tenant.sql` — crée `workspaces` + `workspace_members`,
  ajoute `workspace_id` à toutes les tables métier, remplace les RLS
  "tout le monde voit tout" par des RLS scopées par workspace.
- ⚠ À tester d'abord sur un projet Supabase de test, puis appliquer en
  prod après backup complet.

### 6. Paiement Stripe (squelette)
- `supabase/21_saas_subscriptions.sql` — tables `saas_subscriptions` +
  `stripe_events`.
- `triskell_command/integrations/billing_saas/` : config, plans, checkout,
  portal, webhook.
- Routes FastAPI ajoutées :
  - `POST /api/billing/create_checkout` (authentifiée)
  - `POST /api/billing/portal` (authentifiée)
  - `POST /api/billing/webhook` (publique, signature vérifiée)
- ⚠ Le SDK `stripe` n'est pas dans `requirements.txt` — à ajouter quand
  on active vraiment.

---

## Ce qui reste à faire AVANT de pouvoir vendre

### A. Toi (action humaine)
| # | Tâche | Temps |
|---|---|---|
| 1 | Tourner la vidéo démo (suivre `SCRIPT_VIDEO.md`) | 30 min |
| 2 | Acheter `triskell-command.fr` chez IONOS | 5 min |
| 3 | Créer compte Stripe + produits (3 prix mensuels) | 30 min |
| 4 | Brancher Formspree sur la waitlist (remplacer `REPLACE_ME`) | 10 min |
| 5 | Choisir l'hébergement Supabase de **prod** (séparé du Supabase actuel partagé Jordan/Thomas) | 15 min |
| 6 | Déployer la landing sur Netlify (CLI authentifiée, JAMAIS drag-drop) | 10 min |

### B. Code (chantiers techniques restants)
| # | Tâche | Estimation | Critique ? |
|---|---|---|---|
| 1 | Page d'inscription publique (création workspace + 1er user) | 2 j | OUI |
| 2 | Connexion paiement réel : flow inscription → checkout → activation | 1 j | OUI |
| 3 | Injecter `workspace_id` dans toutes les écritures de l'app (sinon les RLS refusent) | 3-5 j | OUI |
| 4 | Vue Réglages → "Mon abonnement" (factures, changement plan, résil) | 1 j | OUI |
| 5 | Gates côté UI : cacher Le Phare / Pro si le module n'est pas activé | 1 j | OUI |
| 6 | Mentions légales / CGU / CGV / Confidentialité (pages dédiées) | 1 j | OUI (légal) |
| 7 | Email transactionnel (bienvenue, paiement reçu, échec paiement) | 1 j | NON |
| 8 | Tests E2E du flow complet (inscription → paiement → utilisation) | 2 j | OUI |
| 9 | Documentation utilisateur (Aide en ligne) | 2 j | NON |
| 10 | Monitoring + alertes (erreurs Sentry, paiements ratés) | 1 j | NON |

**Total chemin critique : ~3 semaines de dev.**

---

## Schéma final (multi-tenant + SaaS)

```
┌────────────────────────────────────────────────────────────────┐
│                                                                │
│   triskell-command.fr     ←──   Landing publique               │
│   (Netlify, statique)            (3 thèmes, waitlist, pricing) │
│                                                                │
└──────────────────────────┬─────────────────────────────────────┘
                           │ "Commencer"
                           ▼
┌────────────────────────────────────────────────────────────────┐
│                                                                │
│   command.triskell-studio.fr  ←──   App SaaS multi-tenant      │
│   (FastAPI, hébergement à choisir)                             │
│                                                                │
│   ├── /signup          (création workspace + user)             │
│   ├── /api/billing/*   (checkout, portal, webhook Stripe)      │
│   ├── /app             (l'app, scopée par workspace_id)        │
│   └── /billing/success (retour Stripe après paiement)          │
│                                                                │
└──────────────┬─────────────────────────────────────────────────┘
               │
               ▼
┌────────────────────────────────────────────────────────────────┐
│                                                                │
│   Supabase PROD (séparée du Supabase interne Jordan/Thomas)   │
│   - workspaces, workspace_members                              │
│   - saas_subscriptions, stripe_events                          │
│   - prospects, convoy_campaigns, clients, etc. (scopés ws_id)  │
│   - RLS par current_workspace_id()                             │
│                                                                │
└────────────────────────────────────────────────────────────────┘
               ▲
               │ webhooks signés
               │
        ┌──────┴──────┐
        │   Stripe    │
        └─────────────┘
```

---

## Décisions structurantes prises

1. **Modèle "socle + modules"** : Essentiel 39 €/mois obligatoire, puis
   Pro (+49 €) et Le Phare (+149 €) en options à la carte.
2. **Pas de respect du `prefers-color-scheme`** côté landing : thème clair
   par défaut au tout premier visiteur (décision Jordan, règle générale
   tous sites).
3. **Stripe price IDs séparés par module** (pas de tiers complexes) — plus
   facile à mesurer et à changer.
4. **14 jours remboursés** plutôt que trial sans CB (rassure les sérieux
   sans attirer les profileurs).
5. **Hébergement Supabase prod SÉPARÉ** du Supabase actuel
   (Jordan + Thomas restent sur le workspace `triskell-studio` interne,
   les vrais clients SaaS sont sur une autre instance).

---

## Risques connus

- **RLS scopée par workspace** : si on oublie d'injecter `workspace_id`
  dans une seule écriture côté code, ça plante en silence. À tester
  exhaustivement.
- **Migration 20** : touche toutes les tables. Backup obligatoire avant.
- **Cap quotidien d'envoi** : à passer en limite par workspace pour
  éviter qu'un client monopolise le SMTP partagé.
- **Vie privée mails** : aujourd'hui les workers (replies_poller,
  drip_runner…) ne sont PAS scopés par workspace. À refactorer pour
  qu'un client X ne lise pas la boîte mail de client Y.
