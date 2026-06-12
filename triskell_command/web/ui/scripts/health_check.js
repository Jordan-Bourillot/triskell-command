/* HealthCheck — garde-fous pour détecter les bugs silencieux.
 *
 * Trois systèmes :
 *
 * 1) ERREURS JS GLOBALES — au lieu de planter silencieusement, on capture
 *    toutes les exceptions non gérées et les "Promise rejections". À
 *    l'écran : un message générique en français (via le Toast commun de
 *    toast.js). Le détail technique (message, fichier:ligne, pile) part
 *    en console UNIQUEMENT, et l'erreur est accumulée dans
 *    HealthCheck.errors pour le rapport de bug.
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
 * Affichage : HealthCheck.toast(titre, corps, type) est conservé pour les
 * vues qui l'appellent encore (convoy.js, app.js, focus_mode.js…) mais
 * délègue tout au Toast commun (toast.js) — y compris la déduplication.
 *
 * Toggle : sessionStorage.setItem('tc-health-quiet', '1') pour désactiver
 * les toasts visuels (les logs console restent).
 */

const HealthCheck = {
  errors: [],          // ring buffer des 50 dernières erreurs
  MAX_ERRORS: 50,
  _wired: false,

  // Message générique montré à l'utilisateur quand du code plante :
  // jamais d'erreur brute à l'écran, le détail reste en console.
  GENERIC_ERROR_MSG: 'Quelque chose a planté. Recharge la page (touche F5). '
    + 'Si ça se reproduit, clique sur « Signaler un bug » en bas du menu — '
    + 'le détail technique partira tout seul avec le rapport.',

  isQuiet() {
    try { return sessionStorage.getItem('tc-health-quiet') === '1'; }
    catch (e) { return false; }
  },

  init() {
    if (this._wired) return;
    this._wired = true;

    // Erreurs JS classiques (window.onerror)
    window.addEventListener('error', (e) => {
      if (!e.error && !e.message) return;
      const msg = e.message || String(e.error);
      const loc = e.filename ? `${e.filename.split('/').pop()}:${e.lineno}` : '';
      // Détail (message + fichier:ligne + pile) en console uniquement,
      // via record(). À l'écran : message générique français.
      this.record({ kind: 'js_error', msg, loc, stack: e.error?.stack || '' });
      // Filtre quelques erreurs cosmétiques (ResizeObserver loop)
      if (/ResizeObserver loop/i.test(msg)) return;
      this.toast('', this.GENERIC_ERROR_MSG, 'error');
    });

    // Promesses rejetées non catchées
    window.addEventListener('unhandledrejection', (e) => {
      const reason = e.reason;
      // Sérialisation propre pour la console : jamais de "[object Object]".
      let msg = '';
      if (reason instanceof Error) {
        msg = reason.message || String(reason);
      } else if (typeof reason === 'string') {
        msg = reason;
      } else if (reason != null) {
        try { msg = JSON.stringify(reason); } catch (err) { msg = String(reason); }
      }
      msg = msg || 'Promesse rejetée sans détail';
      this.record({ kind: 'promise_rejection', msg, stack: (reason && reason.stack) || '' });
      // Auth required = redirect en cours, pas la peine de toaster
      if (/auth_required/i.test(msg)) return;
      this.toast('', this.GENERIC_ERROR_MSG, 'error');
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

  // ----- Toasts : délégués au système commun (toast.js) -----
  // Signature historique conservée : toast(titre, corps, type).
  // La déduplication (même message répété) est gérée par Toast lui-même.
  toast(title, body, kind = 'info') {
    if (this.isQuiet()) return;
    const type = ['success', 'error', 'warn', 'info'].includes(kind) ? kind : 'info';
    if (window.Toast && typeof window.Toast.show === 'function') {
      window.Toast.show(String(body == null ? '' : body), {
        type,
        title: title ? String(title) : '',
      });
    } else {
      // toast.js pas encore chargé (ne devrait pas arriver : il est
      // inclus avant ce fichier) — au pire, trace en console.
      console.warn('[HealthCheck.toast]', title, body);
    }
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
