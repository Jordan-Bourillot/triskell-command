/* Service Worker — Triskell Command web
 *
 * - Activation immédiate (skipWaiting + clients.claim) pour que les
 *   nouvelles versions remplacent l'ancienne sans recharger.
 * - Reception des push notifications Web Push.
 * - Click sur notif → focus la fenêtre déjà ouverte ou ouvre une nouvelle.
 *
 * Pas de cache offline pour l'instant (l'app a besoin de l'API live de
 * toute façon, et un cache mal géré casserait les déploiements).
 */

self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('push', (event) => {
  let payload = { title: 'Triskell Command', body: 'Nouvelle activité' };
  if (event.data) {
    try { payload = { ...payload, ...event.data.json() }; }
    catch { payload.body = event.data.text(); }
  }
  event.waitUntil(
    self.registration.showNotification(payload.title, {
      body: payload.body,
      icon: '/assets/icon-192.png',
      badge: '/assets/badge-96.png',
      tag: payload.tag || 'triskell-command',
      data: payload.data || {},
      vibrate: [120, 60, 120],
      renotify: true,
    })
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  // Tente de clear le badge sur l'icône PWA si supporté
  try { self.navigator.clearAppBadge && self.navigator.clearAppBadge(); } catch {}
  const targetUrl = (event.notification.data && event.notification.data.url) || '/';
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clients) => {
      for (const client of clients) {
        if ('focus' in client) {
          if (targetUrl !== '/') {
            try { client.navigate(targetUrl); } catch {}
          }
          return client.focus();
        }
      }
      return self.clients.openWindow(targetUrl);
    })
  );
});
