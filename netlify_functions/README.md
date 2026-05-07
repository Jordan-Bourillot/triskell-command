# Triskell Tracking — Netlify Functions

Deux endpoints HTTP publics à héberger sur Netlify pour brancher le tracking
d'ouvertures de mail et le webhook AppSumo à Triskell Command.

**Pourquoi un site séparé ?** Triskell Command tourne en local sur ta machine
(pywebview). Il ne peut pas recevoir de requêtes depuis internet. On délègue
ces 2 endpoints à un mini-site Netlify (gratuit, ~5 minutes à déployer une
fois pour toutes).

## Endpoints fournis

### 1. `track-pixel.js`
Sert un pixel transparent 1×1 + log l'ouverture dans Supabase.
URL finale : `https://<ton-site>.netlify.app/.netlify/functions/track-pixel`

### 2. `appsumo-webhook.js`
Reçoit les événements AppSumo (activation de license) et crée
automatiquement un `client_projects` row qui déclenchera la livraison
auto via le post_sale_runner.
URL finale : `https://<ton-site>.netlify.app/.netlify/functions/appsumo-webhook`

## Déploiement (~5 min)

1. **Crée un nouveau site Netlify dédié au tracking** (séparé de tes autres
   sites pour pouvoir le revoke individuellement).

2. **Déploie ce dossier** :
   - Soit drag-drop sur https://app.netlify.com/drop le dossier
     `netlify_functions/` complet
   - Soit push sur un repo Git connecté à Netlify (recommandé pour les
     mises à jour)

3. **Configure les variables d'environnement** dans
   *Site settings → Environment variables* :

   ```
   SUPABASE_URL          = https://xxxxxxxxxxxx.supabase.co
   SUPABASE_SERVICE_KEY  = eyJ... (clé service_role, PAS la anon)
   APPSUMO_SECRET        = (secret webhook AppSumo, optionnel mais recommandé)
   PRODUCT_KEY           = obelisk          (ou pack-electricien-pro, etc.)
   PRODUCT_NAME          = Obelisk          (nom affiché dans Triskell)
   ```

   La clé `SUPABASE_SERVICE_KEY` se trouve dans Supabase Dashboard →
   Settings → API → Project API keys → `service_role` (cliquer sur "Reveal").

4. **Récupère l'URL du site** (par défaut `https://something-random.netlify.app`,
   tu peux la renommer dans Site settings → Domain management).

5. **Configure dans Triskell Command** :
   - Réglages → *Tracking d'ouvertures* → URL pixel
   - Côté AppSumo Partner Portal → Webhook URL → l'URL du webhook AppSumo

## Test rapide

Une fois déployé, teste les 2 endpoints :

```bash
# Pixel : doit renvoyer un GIF transparent + 200 OK
curl -i "https://<ton-site>.netlify.app/.netlify/functions/track-pixel?id=test123"

# Webhook AppSumo : doit renvoyer 401 si pas de signature, 200 sinon
curl -X POST "https://<ton-site>.netlify.app/.netlify/functions/appsumo-webhook" \
  -H "Content-Type: application/json" \
  -d '{"event":"activate","license":{"activation_email":"test@test.com","customer_name":"Test","license_key":"TEST123","tier":"tier1"}}'
```

## Coûts

- Netlify Free tier : 125k requêtes/mois (largement assez pour les 2
  endpoints même avec ~10k mails/mois).
- Supabase Free tier : 500k rows/mois (largement assez aussi).

Total : **0 €** tant que tu restes sous ces volumes.

## Sécurité

- Les 2 endpoints sont publics par design (le pixel doit être chargé par
  les destinataires, le webhook par AppSumo).
- Le pixel utilise un ID non-devinable (`secrets.token_urlsafe(12)`).
- Le webhook AppSumo vérifie la signature HMAC-SHA256 si `APPSUMO_SECRET`
  est configuré.
- La clé `SUPABASE_SERVICE_KEY` est stockée uniquement dans les env vars
  Netlify (jamais dans le code). Ne la commit jamais ailleurs.
