# Setup Supabase pour Triskell Command + Triskell Core

Ce dossier contient le SQL à exécuter pour préparer le backend partagé
entre Jordan et Thomas. Tout en 5 étapes (~10 min).

## Étape 1 — Créer le projet Supabase

Si tu n'as pas encore créé le projet :

1. Va sur https://supabase.com/dashboard
2. New project → région : **Frankfurt (eu-central-1)** (le plus proche de la France)
3. Nom : `triskell-shared`
4. Mot de passe DB : note-le quelque part (au cas où on en a besoin pour
   un dump direct Postgres — usage rare)
5. Plan : **Free** (largement suffisant pour 2 users)

## Étape 2 — Lancer le schéma

Dans le projet :

1. SQL Editor (icône SQL dans la sidebar gauche)
2. New query
3. Copie-colle le contenu de `01_schema.sql` → Run
4. Vérifie : Database → Tables → tu dois voir 9 tables (users,
   shared_settings, prospects, email_history, prospect_drafts, templates,
   convoy_campaigns, convoy_drafts, send_log)

5. New query → copie-colle `02_rls.sql` → Run
6. Vérifie : Database → Authentication → Policies → chaque table a
   3 ou 4 policies actives (select / insert / update / delete pour les
   utilisateurs `authenticated`)

## Étape 3 — Créer les 2 comptes

Dans le projet :

1. Authentication → Users → Add user → Send invitation OR Create user
2. Crée :
   - **Jordan** : email = ton email habituel (ex: `jordan@triskell-studio.fr`)
   - **Thomas** : email = `thomasbourillot@gmail.com`
3. Pour chacun : note le **UUID** affiché (colonne ID dans la liste).

## Étape 4 — Seed des profils

1. SQL Editor → ouvre `03_seed.sql`
2. Remplace `<JORDAN_UUID>` et `<THOMAS_UUID>` par les vrais IDs notés
3. Run
4. Vérifie : Database → Tables → users → tu dois voir 2 lignes (Jordan, Thomas).

## Étape 5 — Récupérer les credentials pour l'app

Dans le projet :

1. Settings → API
2. Note ces 2 valeurs (à mettre dans Triskell Command à son premier
   lancement, ou via variables d'environnement) :
   - **Project URL** : `https://xxxxx.supabase.co`
   - **anon public key** : la longue clé sous "Project API keys"
     (PAS le service_role, c'est dangereux si elle fuit)

3. Communique-les à Claude (ou copie-les dans
   `~/.triskell-command/settings.json` si l'app est déjà configurée pour
   les lire — le code de l'app le fera automatiquement au premier login).

## Vérification rapide

```bash
# Test de connexion depuis Python
pip install supabase
python -c "
from supabase import create_client
c = create_client('https://TONURL.supabase.co', 'TON_ANON_KEY')
print(c.table('users').select('*').execute().data)
"
```

Si tu vois `[]` (vide, normal avant login) ou la liste des 2 profils,
c'est gagné.

## En cas de pépin

- **Erreur "permission denied for table xxx"** : t'as oublié de lancer
  `02_rls.sql`, ou tu fais une requête sans token JWT (donc en tant
  qu'anonyme). Login d'abord avec `c.auth.sign_in_with_password({...})`.

- **"new row violates row-level security policy"** : pareil, faut être
  authentifié avant d'écrire.

- **Reset complet** : Settings → Database → "Reset database" (efface tout,
  recommence à zéro). Ou en SQL : `drop schema public cascade; create schema public;`
  puis relancer 01 → 02 → 03.
