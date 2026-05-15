/* Push notifications — Triskell Command web.
 *
 * Enregistre le Service Worker, propose un bouton "Activer notifs" dans
 * la sidebar (si supporté par le navigateur), et gère subscribe / test.
 *
 * Le bouton s'affiche seulement si :
 *   - Le navigateur supporte serviceWorker + PushManager
 *   - L'utilisateur n'a pas déjà refusé (Notification.permission !== 'denied')
 */

const Push = {
  registration: null,
  subscription: null,
  publicKey: null,

  isSupported() {
    return 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
  },

  async init() {
    if (!this.isSupported()) {
      console.info('Push : navigateur non supporté.');
      return;
    }
    // Enregistre le Service Worker (silencieux si déjà enregistré)
    try {
      this.registration = await navigator.serviceWorker.register('/sw.js', { scope: '/' });
    } catch (e) {
      console.warn('Push : impossible d\'enregistrer le Service Worker', e);
      return;
    }
    // Récupère la subscription existante (si déjà active depuis une session précédente)
    try {
      this.subscription = await this.registration.pushManager.getSubscription();
    } catch (e) {
      console.warn('Push : getSubscription a échoué', e);
    }
    // Récupère la clé publique VAPID du serveur (route publique)
    try {
      const r = await fetch('/api/push/public_key', { credentials: 'same-origin' });
      const j = await r.json();
      if (j && j.ok) this.publicKey = j.public_key;
    } catch (e) {
      console.info('Push : VAPID non configurée côté serveur', e);
    }
  },

  /** Demande la permission au navigateur et abonne aux push. */
  async enable() {
    if (!this.isSupported()) {
      alert('Ton navigateur ne supporte pas les notifications push.');
      return false;
    }
    if (!this.publicKey) {
      alert('Les notifications push ne sont pas configurées côté serveur (VAPID manquante).');
      return false;
    }
    if (!this.registration) {
      try { this.registration = await navigator.serviceWorker.register('/sw.js', { scope: '/' }); }
      catch { return false; }
    }
    // Permission utilisateur
    let perm = Notification.permission;
    if (perm === 'default') {
      perm = await Notification.requestPermission();
    }
    if (perm !== 'granted') {
      alert('Permission refusée. Tu peux la réactiver dans les paramètres du navigateur.');
      return false;
    }
    // Souscrit
    try {
      this.subscription = await this.registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: this._urlBase64ToUint8Array(this.publicKey),
      });
    } catch (e) {
      console.warn('Push : subscribe a échoué', e);
      alert('Échec de l\'abonnement push : ' + e.message);
      return false;
    }
    // Envoie la subscription au serveur
    try {
      const r = await fetch('/api/push/subscribe', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ subscription: this.subscription.toJSON() }),
      });
      const j = await r.json();
      if (!j.ok) throw new Error(j.error || 'erreur');
    } catch (e) {
      alert('Échec de l\'enregistrement côté serveur : ' + e.message);
      return false;
    }
    return true;
  },

  /** Désabonne (le serveur oubliera la subscription au prochain envoi). */
  async disable() {
    if (!this.subscription) return true;
    const endpoint = this.subscription.endpoint;
    try { await this.subscription.unsubscribe(); } catch {}
    try {
      await fetch('/api/push/unsubscribe', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ endpoint }),
      });
    } catch {}
    this.subscription = null;
    return true;
  },

  /** Demande au serveur d'envoyer une notif de test à toutes les subs du user. */
  async test() {
    try {
      const r = await fetch('/api/push/test', {
        method: 'POST',
        credentials: 'same-origin',
      });
      const j = await r.json();
      if (!j.ok) throw new Error(j.error || 'erreur');
      alert(`Test envoyé : ${j.sent} notif(s) reçue(s), ${j.failed} échec(s).`);
    } catch (e) {
      alert('Test échoué : ' + e.message);
    }
  },

  isEnabled() {
    return !!this.subscription;
  },

  _urlBase64ToUint8Array(base64) {
    const padding = '='.repeat((4 - base64.length % 4) % 4);
    const b64 = (base64 + padding).replace(/-/g, '+').replace(/_/g, '/');
    const raw = window.atob(b64);
    const out = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
    return out;
  },
};
