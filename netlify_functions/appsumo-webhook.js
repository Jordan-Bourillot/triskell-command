/**
 * Netlify Function — Webhook AppSumo pour les ventes Obelisk (et autres).
 *
 * AppSumo POST sur cet endpoint à chaque événement de licence :
 *   activate    : nouveau code activé (= nouvelle vente)
 *   upgrade     : tier upgradé
 *   downgrade   : tier downgradé
 *   refund      : remboursé
 *
 * Doc AppSumo : https://api.licensing.appsumo.com/v2/docs
 *
 * Sur `activate` : crée un `client_projects` row dans Supabase avec
 *   paid_at = now(), product_key = product mappé, statut = "briefing".
 *   Le `post_sale_runner` détecte ensuite ce projet payé et déclenche
 *   automatiquement le kit de livraison du produit.
 *
 * Variables d'environnement requises :
 *   SUPABASE_URL          = https://xxx.supabase.co
 *   SUPABASE_SERVICE_KEY  = clé service_role
 *   APPSUMO_SECRET        = secret à valider (header X-Licensing-Signature)
 *   PRODUCT_KEY           = product_key Triskell par défaut (ex: "obelisk")
 *   PRODUCT_NAME          = nom affiché (ex: "Obelisk")
 *
 * Configuration côté AppSumo :
 *   1. Sumo-ling API webhook : https://<ton-site>.netlify.app/.netlify/functions/appsumo-webhook
 *   2. Récupère le secret webhook depuis AppSumo Partner Portal.
 */

const crypto = require('crypto');

exports.handler = async (event) => {
  if (event.httpMethod !== 'POST') {
    return { statusCode: 405, body: 'Method not allowed' };
  }

  const secret = process.env.APPSUMO_SECRET || '';
  const supabaseUrl = process.env.SUPABASE_URL || '';
  const supabaseKey = process.env.SUPABASE_SERVICE_KEY || '';
  const productKey  = process.env.PRODUCT_KEY  || 'obelisk';
  const productName = process.env.PRODUCT_NAME || 'Obelisk';

  if (!supabaseUrl || !supabaseKey) {
    console.error('SUPABASE_URL/SUPABASE_SERVICE_KEY not set');
    return { statusCode: 500, body: 'Server misconfigured' };
  }

  // Vérification de signature (HMAC-SHA256 sur le body brut)
  const sig = event.headers['x-licensing-signature']
            || event.headers['X-Licensing-Signature'] || '';
  if (secret) {
    const expected = crypto.createHmac('sha256', secret)
      .update(event.body || '')
      .digest('hex');
    if (!safeEqual(sig, expected)) {
      console.warn('Invalid AppSumo signature');
      return { statusCode: 401, body: 'Invalid signature' };
    }
  }

  let payload;
  try { payload = JSON.parse(event.body || '{}'); }
  catch (e) { return { statusCode: 400, body: 'Invalid JSON' }; }

  const eventType = payload.event || payload.action || '';
  const license   = payload.license || payload || {};

  // On ne traite QUE les activate (= nouveaux paiements). Les refund/upgrade
  // sont logués mais pas traités automatiquement (Jordan gère à la main).
  if (eventType !== 'activate' && eventType !== 'license.activated') {
    console.log(`AppSumo event ${eventType} ignored (not an activate)`);
    return { statusCode: 200, body: JSON.stringify({ received: true, action: 'ignored' }) };
  }

  const customerEmail = license.activation_email
                     || license.email
                     || license.customer_email
                     || '';
  const customerName  = license.customer_name
                     || `${license.first_name || ''} ${license.last_name || ''}`.trim()
                     || '';
  const licenseKey    = license.license_key || license.key || license.code || '';
  const tier          = license.tier || license.product_tier || '';

  if (!customerEmail) {
    return { statusCode: 400, body: 'Missing customer email' };
  }

  // Idempotence : on vérifie que cette license n'a pas déjà créé un projet
  if (licenseKey) {
    const exists = await query(
      supabaseUrl, supabaseKey,
      `client_projects?stripe_session_id=eq.appsumo:${encodeURIComponent(licenseKey)}&select=id&limit=1`,
    );
    if (exists && exists.length > 0) {
      return { statusCode: 200, body: JSON.stringify({ received: true, action: 'duplicate' }) };
    }
  }

  const projectPayload = {
    title:        `${productName} — ${customerName || customerEmail}`,
    client_name:  customerName,
    client_email: customerEmail,
    product_key:  productKey,
    product_name: productName,
    status:       'briefing',
    paid_at:      new Date().toISOString(),
    stripe_session_id: licenseKey ? `appsumo:${licenseKey}` : null,
    notes:        buildNotes(license, eventType, tier),
  };

  const inserted = await insert(supabaseUrl, supabaseKey,
    'client_projects', projectPayload);

  if (!inserted) {
    return { statusCode: 500, body: 'Failed to create project' };
  }

  return {
    statusCode: 200,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      received: true,
      action: 'created',
      project_id: inserted[0]?.id || null,
    }),
  };
};

function buildNotes(license, eventType, tier) {
  return [
    `Activation AppSumo automatique.`,
    `Event   : ${eventType}`,
    `Tier    : ${tier || '—'}`,
    `License : ${license.license_key || license.key || '—'}`,
    `Plan    : ${license.plan_id || license.product_id || '—'}`,
    `Pays    : ${license.country || '—'}`,
  ].join('\n');
}

async function insert(supabaseUrl, supabaseKey, table, payload) {
  try {
    const r = await fetch(`${supabaseUrl}/rest/v1/${table}`, {
      method: 'POST',
      headers: {
        'apikey': supabaseKey,
        'Authorization': `Bearer ${supabaseKey}`,
        'Content-Type': 'application/json',
        'Prefer': 'return=representation',
      },
      body: JSON.stringify(payload),
    });
    if (!r.ok) {
      console.error('Supabase insert failed:', r.status, await r.text());
      return null;
    }
    return await r.json();
  } catch (e) {
    console.error('Supabase insert error:', e);
    return null;
  }
}

async function query(supabaseUrl, supabaseKey, path) {
  try {
    const r = await fetch(`${supabaseUrl}/rest/v1/${path}`, {
      headers: {
        'apikey': supabaseKey,
        'Authorization': `Bearer ${supabaseKey}`,
      },
    });
    if (!r.ok) return null;
    return await r.json();
  } catch (e) {
    return null;
  }
}

function safeEqual(a, b) {
  if (typeof a !== 'string' || typeof b !== 'string') return false;
  if (a.length !== b.length) return false;
  let result = 0;
  for (let i = 0; i < a.length; i++) {
    result |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return result === 0;
}
