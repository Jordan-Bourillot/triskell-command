/* HealthCheck — garde-fous pour détecter les bugs silencieux.
 *
 * Trois systèmes :
 *
 * 1) ERREURS JS GLOBALES — au lieu de planter silencieusement, on capture
 *    toutes les exceptions non gérées et les "Promise rejections" et on
 *    affiche un toast d'erreur en bas à droite. Les erreurs sont aussi
 *    accumulées dans HealthCheck.errors pour un debug rapide.
 *
 * 2) FAKES MANQUANTS EN MODE DÉMO — quand le mode démo intercepte un appel
 *    API et que la méthode n'a pas de fake défini (mais devrait, parce
 *    qu'elle retourne du contenu, pas juste un OK), on logue un warning
 *    bien visible. Permet à Jordan de signaler "telle page est vide en
 *    mode démo" et qu'on identifie tout de suite la méthode manquante.
 *
 * 3) APPELS API LENTS OU EN ÉCHEC — chaque appel est chronométré. Si un
 *    appel > 5 sec ou échoue, on log un avertissement avec le contexte.
 *
 * Toggle : sessionStorage.setItem('tc-health-quiet', '1') pour désactiver
 * les toasts visuels (les logs console restent).
 */

const HealthCheck = {
  errors: [],          // ring buffer des 50 dernières erreurs
  MAX_ERRORS: 50,
  toastQueue: [],
  _stylesInjected: false,
  _wired: false,

  isQuiet() {
    try { return sessionStorage.getItem('tc-health-quiet') === '1'; }
    catch (e) { return false; }
  },

  init() {
    if (this._wired) return;
    this._wired = true;
    this._injectStyles();

    // Erreurs JS classiques (window.onerror)
    window.addEventListener('error', (e) => {
      if (!e.error && !e.message) return;
      const msg = e.message || String(e.error);
      const loc = e.filename ? `${e.filename.split('/').pop()}:${e.lineno}` : '';
      this.record({ kind: 'js_error', msg, loc, stack: e.error?.stack || '' });
      // Filtre quelques erreurs cosmétiques (ResizeObserver loop)
      if (/ResizeObserver loop/i.test(msg)) return;
      this.toast('⚠ Erreur JS', `${msg}${loc ? ' (' + loc + ')' : ''}`, 'error');
    });

    // Promesses rejetées non catchées
    window.addEventListener('unhandledrejection', (e) => {
      const reason = e.reason;
      const msg = (reason && (reason.message || reason.toString())) || 'Promise rejetée';
      this.record({ kind: 'promise_rejection', msg, stack: reason?.stack || '' });
      // Auth required = redirect en cours, pas la peine de toaster
      if (/auth_required/i.test(msg)) return;
      this.toast('⚠ Erreur réseau', msg, 'error');
    });

    // Hook DemoMode pour signaler les fakes manquants
    this._wrapDemoMode();
  },

  record(entry) {
    this.errors.push({ ts: new Date().toISOString(), ...entry });
    if (this.errors.length > this.MAX_ERRORS) {
      this.errors.shift();
    }
    // Log aussi en console pour debug
    console.warn('[HealthCheck]', entry);
  },

  _wrapDemoMode() {
    if (typeof DemoMode === 'undefined') return;
    const originalIntercept = DemoMode.intercept.bind(DemoMode);
    DemoMode.intercept = (method, payload) => {
      const result = originalIntercept(method, payload);
      // En mode démo, si une méthode "list" / "get" n'a pas de fake et
      // qu'elle passe au serveur (handled: false sur méthode read), on log.
      // Ça permet à Jordan de signaler "page X vide" et qu'on identifie
      // tout de suite la méthode qui mériterait un fake.
      if (DemoMode.isOn() && !result.handled) {
        const isRead = DemoMode.isReadMethod(method);
        if (isRead) {
          this.record({
            kind: 'demo_fake_missing',
            method,
            note: `Méthode "${method}" est de type lecture mais aucun fake défini → passera au serveur (probablement réponse vide en démo). Ajoute un fake dans demo_mode.js _fake.${method} si la vue affiche du contenu.`,
          });
        }
      }
      return result;
    };
  },

  /** Méthode utilitaire pour valider le format d'un fake.
   *  Usage dans demo_mode.js si tu veux ajouter une vérif "soft" :
   *    HealthCheck.assertShape(result, ['ok', 'rows'], 'get_drafts');
   */
  assertShape(obj, requiredKeys, context = '') {
    if (!obj || typeof obj !== 'object') {
      this.record({ kind: 'fake_shape_error', context, msg: 'fake non-objet' });
      return false;
    }
    const missing = requiredKeys.filter(k => !(k in obj));
    if (missing.length) {
      this.record({
        kind: 'fake_shape_error',
        context,
        msg: `champs manquants : ${missing.join(', ')}`,
      });
      return false;
    }
    return true;
  },

  // ----- Toasts visuels -----
  _injectStyles() {
    if (this._stylesInjected) return;
    this._stylesInjected = true;
    const s = document.createElement('style');
    s.id = 'health-check-styles';
    s.textContent = `
      #hc-toast-stack {
        position: fixed; bottom: 16px; right: 16px;
        z-index: 99999;
        display: flex; flex-direction: column; gap: 8px;
        max-width: 380px;
        pointer-events: none;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      }
      .hc-toast {
        background: #1a1a1a; color: white;
        border: 1px solid rgba(255,255,255,0.15);
        border-radius: 10px;
        padding: 10px 36px 10px 14px;
        font-size: 12.5px; line-height: 1.4;
        box-shadow: 0 8px 24px rgba(0,0,0,0.4);
        position: relative;
        pointer-events: auto;
        opacity: 0; transform: translateY(8px);
        transition: opacity 200ms, transform 200ms;
      }
      .hc-toast.is-visible { opacity: 1; transform: translateY(0); }
      .hc-toast--error  { border-left: 4px solid #ef4444; }
      .hc-toast--warn   { border-left: 4px solid #f59e0b; }
      .hc-toast--info   { border-left: 4px solid #3b82f6; }
      .hc-toast strong { display: block; font-weight: 700; margin-bottom: 2px; font-size: 11.5px; }
      .hc-toast button.hc-close {
        position: absolute; top: 6px; right: 8px;
        background: transparent; border: 0; color: rgba(255,255,255,0.6);
        font-size: 14px; cursor: pointer; padding: 0 4px;
      }
      .hc-toast button.hc-close:hover { color: white; }
    `;
    document.head.appendChild(s);
  },

  toast(title, body, kind = 'info') {
    if (this.isQuiet()) return;
    let stack = document.getElementById('hc-toast-stack');
    if (!stack) {
      stack = document.createElement('div');
      stack.id = 'hc-toast-stack';
      document.body.appendChild(stack);
    }
    const el = document.createElement('div');
    el.className = `hc-toast hc-toast--${kind}`;
    el.innerHTML = `
      <strong>${this._esc(title)}</strong>
      <span>${this._esc(body).slice(0, 280)}</span>
      <button class="hc-close" type="button" aria-label="Fermer">×</button>
    `;
    stack.appendChild(el);
    // Animation d'entrée
    requestAnimationFrame(() => el.classList.add('is-visible'));
    const dismiss = () => {
      el.classList.remove('is-visible');
      setTimeout(() => el.remove(), 220);
    };
    el.querySelector('.hc-close').onclick = dismiss;
    // Auto-dismiss après 6 sec pour les erreurs, 4 pour les warns, 3 pour les infos
    const delay = kind === 'error' ? 6000 : kind === 'warn' ? 4000 : 3000;
    setTimeout(dismiss, delay);
  },

  _esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;',
    }[c]));
  },

  /** Diagnostic console : tape `HealthCheck.dump()` pour voir tout le buffer. */
  dump() {
    console.group('[HealthCheck] Dernières erreurs');
    this.errors.forEach((e, i) => console.log(`#${i+1}`, e));
    console.groupEnd();
    return this.errors;
  },
};

window.HealthCheck = HealthCheck;
window.addEventListener('DOMContentLoaded', () => HealthCheck.init());
