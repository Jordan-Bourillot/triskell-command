/* Service Worker — Triskell Command web
 *
 * - Activation immédiate (skipWaiting + clients.claim) pour que les
 *   nouvelles versions remplacent l'ancienne sans recharger.
 * - Reception des push notifications Web Push avec priorité visuelle.
 * - Bundling : si plusieurs notifs de même tag arrivent en peu de temps,
 *   on agrège en une seule "X événements".
 * - Click sur notif → focus la fenêtre + deep link vers la bonne vue.
 *
 * Pas de cache offline pour l'instant (l'app a besoin de l'API live).
 */

self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

// ---- Priorités ----
// Le serveur peut envoyer `priority` dans le payload :
//   'urgent'  → vibration forte + son si supporté + tag rouge "URGENT"
//   'normal'  → notif standard (défaut)
//   'low'     → silencieux (silent: true), accumule sans vibrer
//
// Bundling : si on reçoit 3+ notifs avec le même `tag_group` dans 5 min,
// on remplace par "X événements - {tag_group}".

const BUNDLE_WINDOW_MS = 5 * 60 * 1000;

async function handlePush(payload) {
  const priority = payload.priority || 'normal';
  const tagGroup = payload.tag_group || payload.tag || 'triskell-command';
  const dataUrl = (payload.data && payload.data.url) || payload.url || '/';

  // Récupère les notifs déjà affichées avec le même tagGroup
  let existing = [];
  try {
    existing = await self.registration.getNotifications({ tag: tagGroup });
  } catch (e) { /* ignore */ }

  // Si on a déjà 2+ notifs du même groupe → bundle
  if (existing.length >= 2) {
    const total = existing.length + 1;
    existing.forEach(n => n.close());
    await self.registration.showNotification(
      `${total} événements — ${humanGroup(tagGroup)}`,
      {
        body: payload.body || 'Plusieurs notifications regroupées. Ouvre Triskell Command.',
        icon: '/assets/icon-192.png',
        badge: '/assets/badge-96.png',
        tag: tagGroup,
        data: { url: dataUrl, bundled: true, count: total },
        vibrate: priority === 'urgent' ? [200, 80, 200, 80, 200] : [120, 60],
        renotify: false,
        silent: priority === 'low',
      }
    );
    try {
      self.navigator.setAppBadge && self.navigator.setAppBadge(total);
    } catch (e) { /* badge unsupported */ }
    return;
  }

  // Notif individuelle (priorités différenciées)
  const title = priority === 'urgent'
    ? `🔴 ${payload.title || 'Triskell Command'}`
    : (payload.title || 'Triskell Command');

  await self.registration.showNotification(title, {
    body: payload.body || 'Nouvelle activité',
    icon: payload.icon || '/assets/icon-192.png',
    badge: '/assets/badge-96.png',
    tag: tagGroup,
    data: { url: dataUrl, priority },
    vibrate: priority === 'urgent' ? [200, 80, 200, 80, 200]
           : priority === 'low'    ? []
           : [120, 60, 120],
    renotify: priority === 'urgent',
    silent: priority === 'low',
    requireInteraction: priority === 'urgent',  // reste affichée jusqu'au clic
    actions: payload.actions || [],
  });

  try {
    self.navigator.setAppBadge && self.navigator.setAppBadge(1);
  } catch (e) { /* ignore */ }
}

function humanGroup(tag) {
  return ({
    'replies':       'réponses prospects',
    'sales':         'paiements',
    'clients':       'projets clients',
    'call':          'appels',
    'system':        'système',
    'triskell-command': 'activité',
  })[tag] || tag;
}

self.addEventListener('push', (event) => {
  let payload = { title: 'Triskell Command', body: 'Nouvelle activité' };
  if (event.data) {
    try { payload = { ...payload, ...event.data.json() }; }
    catch { payload.body = event.data.text(); }
  }
  event.waitUntil(handlePush(payload));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  // Tente de clear le badge sur l'icône PWA si supporté
  try { self.navigator.clearAppBadge && self.navigator.clearAppBadge(); } catch {}
  const data = event.notification.data || {};
  const targetUrl = data.url || '/';

  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clients) => {
      for (const client of clients) {
        if ('focus' in client) {
          if (targetUrl !== '/' && targetUrl !== client.url) {
            try { client.navigate(targetUrl); } catch {}
          }
          return client.focus();
        }
      }
      return self.clients.openWindow(targetUrl);
    })
  );
});
