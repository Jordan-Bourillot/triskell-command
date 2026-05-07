/**
 * Netlify Function — Pixel tracker pour les ouvertures de mail Triskell.
 *
 * Reçoit GET /track-pixel?id=<tracking_id>&p=<prospect_id?>
 *  - Renvoie un GIF transparent 1x1 (43 bytes) + headers no-cache
 *  - En parallèle (async, sans bloquer la réponse) écrit dans Supabase
 *    la ligne `email_history` avec kind='email_opened'
 *
 * Variables d'environnement requises (à définir dans Netlify UI) :
 *   SUPABASE_URL          = https://xxx.supabase.co
 *   SUPABASE_SERVICE_KEY  = clé service_role (PAS la anon)
 *
 * Déploiement :
 *   1. Crée un nouveau projet Netlify dédié au tracking
 *      (séparé pour pouvoir le revoke individuellement).
 *   2. Pousse ce dossier `netlify_functions/` à la racine d'un repo Git,
 *      ou drag-drop sur netlify.app/drop.
 *   3. Configure les 2 env vars dans Site settings → Environment variables.
 *   4. Récupère l'URL : https://<ton-site>.netlify.app/.netlify/functions/track-pixel
 *   5. Colle dans Triskell Command → Réglages → Tracking d'ouvertures.
 *
 * Sécurité :
 *   - L'endpoint est public (les destinataires de mail le hit sans auth).
 *   - L'ID est non-devinable (token_urlsafe 12 bytes), donc pas de
 *     spam/pollution facile.
 *   - On ne stocke pas l'IP/UA en clair par défaut (RGPD-friendly).
 */

const TRANSPARENT_GIF = Buffer.from(
  'R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==',
  'base64',
);

exports.handler = async (event) => {
  const params = event.queryStringParameters || {};
  const tid = (params.id || '').slice(0, 64);
  const pid = (params.p || '').slice(0, 64);

  // Réponse immédiate (le pixel doit charger quoi qu'il arrive)
  const response = {
    statusCode: 200,
    headers: {
      'Content-Type': 'image/gif',
      'Cache-Control': 'no-store, no-cache, must-revalidate, max-age=0',
      'Pragma': 'no-cache',
      'Expires': '0',
      'Access-Control-Allow-Origin': '*',
    },
    body: TRANSPARENT_GIF.toString('base64'),
    isBase64Encoded: true,
  };

  // Log async (sans await pour ne pas ralentir la réponse pixel)
  if (tid) {
    logOpen(tid, pid).catch((e) => console.error('logOpen failed:', e));
  }

  return response;
};

async function logOpen(trackingId, prospectId) {
  const url = process.env.SUPABASE_URL;
  const key = process.env.SUPABASE_SERVICE_KEY;
  if (!url || !key) {
    console.warn('SUPABASE_URL or SUPABASE_SERVICE_KEY not set — skipping log');
    return;
  }
  const payload = {
    prospect_id: prospectId || null,
    kind: 'email_opened',
    ts: new Date().toISOString(),
    extra: {
      tracking_id: trackingId,
      // Pas d'IP/UA en clair pour rester RGPD-friendly
    },
  };
  const r = await fetch(`${url}/rest/v1/email_history`, {
    method: 'POST',
    headers: {
      'apikey': key,
      'Authorization': `Bearer ${key}`,
      'Content-Type': 'application/json',
      'Prefer': 'return=minimal',
    },
    body: JSON.stringify(payload),
  });
  if (!r.ok) {
    console.warn('Supabase insert failed:', r.status, await r.text());
  }
}
