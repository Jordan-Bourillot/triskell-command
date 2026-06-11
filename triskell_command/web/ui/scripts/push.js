/* Push notifications — Triskell Command web.
 *
 * Enregistre le Service Worker, propose un bouton "Activer notifs" dans
 * la sidebar (si supporté par le navigateur), et gère subscribe / test.
 *
 * Le bouton s'affiche seulement si :
 *   - Le navigateur supporte serviceWorker + PushManager
 *   - L'utilisateur n'a pas déjà refusé (Notification.permission !== 'denied')
 *
 * Si le navigateur ne sait pas faire (iPhone Safari sans installation),
 * on affiche une petite ligne d'aide à la place du bouton — plutôt que rien.
 */

const Push = {
  registration: null,
  subscription: null,
  publicKey: null,

  isSupported() {
    return 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
  },

  /** Texte d'aide quand le navigateur ne supporte pas les notifications
   *  (typiquement iPhone Safari tant que l'app n'est pas installée). */
  unsupportedHint() {
    return 'Les alertes sur téléphone nécessitent d’installer l’app : Partager → Sur l’écran d’accueil';
  },

  async init() {
    if (!this.isSupported()) {
      console.info('Push : navigateur non supporté.');
      this._showUnsupportedHint();
      return;
    }
    // État « Bloqué » : greffe un bouton « revérifier » sur l'encart rouge
    this._wrapRenderButton();
    // Enregistre le Service Worker (silencieux si déjà enregistré)
    try {
      this.registration = await navigator.serviceWorker.register('/sw.js', { scope: '/' });
    } catch (e) {
      console.warn('Push : impossible d’enregistrer le Service Worker', e);
      return;
    }
    // Récupère la subscription existante (si déjà active depuis une session précédente)
    try {
      this.subscription = await this.registration.pushManager.getSubscription();
    } catch (e) {
      console.warn('Push : getSubscription a échoué', e);
    }
    // Récupère la clé publique du serveur (route publique)
    await this._fetchPublicKey();
  },

  async _fetchPublicKey() {
    if (this.publicKey) return;
    try {
      const r = await fetch('/api/push/public_key', { credentials: 'same-origin' });
      const j = await r.json();
      if (j && j.ok) this.publicKey = j.public_key;
    } catch (e) {
      console.info('Push : clé serveur indisponible pour le moment', e);
    }
  },

  /** Navigateur incompatible : petite ligne d'aide sous le badge utilisateur,
   *  au même endroit où le bouton "Activer les notifications" serait apparu. */
  _showUnsupportedHint() {
    try {
      const slot = document.getElementById('user-badge-slot');
      if (!slot || !slot.parentNode) return;
      if (document.getElementById('push-unsupported-hint')) return;
      const row = document.createElement('div');
      row.id = 'push-unsupported-hint';
      row.className = 'mt-2';
      const box = document.createElement('div');
      box.className = 'w-full px-3 py-2 rounded-lg bg-bg border border-border text-[11px] text-text-muted leading-tight';
      box.textContent = '🔔 ' + this.unsupportedHint();
      row.appendChild(box);
      slot.parentNode.insertBefore(row, slot.nextSibling);
    } catch (e) { /* jamais bloquant */ }
  },

  /** L'encart « Notifs bloquées » est dessiné par App._renderPushButton sans
   *  bouton de sortie. On enveloppe ce rendu pour ajouter, à chaque fois,
   *  un bouton « J'ai débloqué — revérifier » (sans toucher app.js). */
  _wrapRenderButton() {
    try {
      if (typeof App === 'undefined' || typeof App._renderPushButton !== 'function') return;
      if (App._renderPushButton._pushRecheck) return;
      const original = App._renderPushButton.bind(App);
      const wrapped = function () {
        const out = original();
        try { Push._addRecheckButton(); } catch (e) { /* jamais bloquant */ }
        return out;
      };
      wrapped._pushRecheck = true;
      App._renderPushButton = wrapped;
    } catch (e) { /* jamais bloquant */ }
  },

  _addRecheckButton() {
    const row = document.getElementById('push-toggle-row');
    if (!row || row.querySelector('#push-recheck')) return;
    const blocked = (typeof Notification !== 'undefined' && Notification.permission === 'denied') && !this.isEnabled();
    if (!blocked) return;
    const btn = document.createElement('button');
    btn.id = 'push-recheck';
    btn.type = 'button';
    btn.className = 'mt-1.5 w-full text-[11px] px-2 py-1.5 rounded-lg border border-danger/40 text-danger hover:bg-danger/10 font-semibold';
    btn.textContent = 'J’ai débloqué — revérifier';
    btn.onclick = () => {
      if (window.App && typeof App._renderPushButton === 'function') App._renderPushButton();
    };
    row.appendChild(btn);
  },

  /** Demande la permission au navigateur et abonne aux push. */
  async enable() {
    if (!this.isSupported()) {
      Toast.warn(this.unsupportedHint());
      return false;
    }
    if (!this.publicKey) {
      // Le premier chargement a pu rater (réseau) : on retente une fois
      await this._fetchPublicKey();
    }
    if (!this.publicKey) {
      Toast.error('Le serveur n’est pas configuré pour les alertes — demande à Claude.');
      return false;
    }
    if (!this.registration) {
      try { this.registration = await navigator.serviceWorker.register('/sw.js', { scope: '/' }); }
      catch (e) {
        Toast.friendlyError(e, 'Impossible de préparer les alertes sur cet appareil.');
        return false;
      }
    }
    // Permission utilisateur
    let perm = Notification.permission;
    if (perm === 'default') {
      perm = await Notification.requestPermission();
    }
    if (perm !== 'granted') {
      Toast.warn('Permission refusée. Tu peux la réactiver dans les réglages du navigateur (icône cadenas dans la barre d’adresse).');
      return false;
    }
    // Souscrit
    try {
      this.subscription = await this.registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: this._urlBase64ToUint8Array(this.publicKey),
      });
    } catch (e) {
      Toast.friendlyError(e, 'Impossible d’activer les alertes sur cet appareil.');
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
      if (!j.ok) throw new Error(j.error || 'erreur serveur');
    } catch (e) {
      Toast.friendlyError(e, 'Le serveur n’a pas pu enregistrer cet appareil pour les alertes.');
      return false;
    }
    Toast.success('Alertes activées sur cet appareil.');
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
      if (!j.ok) throw new Error(j.error || 'erreur serveur');
      const sent = j.sent || 0;
      const failed = j.failed || 0;
      if (failed > 0) {
        Toast.warn(`${sent} alerte(s) envoyée(s), ${failed} en échec. Si rien n’arrive sur un appareil : désactive puis réactive les notifications dessus.`);
      } else if (sent > 0) {
        Toast.success(`${sent} alerte(s) envoyée(s) — elle devrait arriver dans quelques secondes.`);
      } else {
        Toast.info('Aucun appareil abonné aux alertes pour le moment.');
      }
    } catch (e) {
      Toast.friendlyError(e, 'Le test n’est pas parti.');
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
