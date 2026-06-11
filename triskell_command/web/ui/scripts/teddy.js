/* Teddy Mail bridge — pont JS depuis Triskell Command vers Teddy Mail.
 *
 * 3 entrées :
 *   Teddy.open()                           → lance l'app desktop (pywebview uniquement)
 *   Teddy.compose({to,subject,body,cc,bcc}) → fenêtre composition pré-remplie
 *                                            via mailto: (client mail défaut)
 *   Teddy.button(opts)                     → renvoie le HTML d'un bouton réutilisable
 *
 * En mode web (App.apiMode === 'http'), open()/compose() ne passent PAS par
 * le serveur (lancer un .exe / un mailto: sur le serveur Linux n'ouvrirait
 * rien chez l'utilisateur) : le mailto: est construit côté navigateur, et
 * open() explique que Teddy Mail est une application du PC.
 *
 * Roadmap : quand Teddy Mail v0.6 exposera un endpoint IPC (custom URL
 * scheme `teddy://compose?…` ou serveur HTTP local sur 127.0.0.1), on
 * remplacera le mailto: par un appel direct ici, sans rien changer dans
 * les vues qui consomment ce module.
 */

const Teddy = {
  // Petits messages : on délègue au système commun (toast.js) — plus de
  // mini-système de toasts maison (doublon, et sans aria).
  _toast(msg, kind = 'info') {
    if (typeof Toast !== 'undefined') {
      if (kind === 'error') Toast.error(msg);
      else Toast.info(msg);
      return;
    }
    console.info('[Teddy]', msg);
  },

  // ---- Lance Teddy Mail (app desktop) ----
  async open() {
    // En mode web (navigateur), Teddy Mail est une application du PC :
    // demander au serveur de la lancer n'ouvrirait rien ici.
    if (!App.api || App.apiMode === 'http') {
      this._toast('Teddy Mail est une application du PC — impossible de l’ouvrir depuis le site.', 'error');
      return false;
    }
    try {
      const r = await App.api.open_teddy_mail();
      if (r && r.ok) {
        this._toast('Teddy Mail s’ouvre…');
        return true;
      }
      this._toast(r && r.error ? r.error : 'Teddy Mail introuvable.', 'error');
      return false;
    } catch (e) {
      console.warn('Teddy.open:', e);
      this._toast('Impossible de lancer Teddy Mail.', 'error');
      return false;
    }
  },

  // ---- Composer un mail (mailto: → client mail par défaut) ----
  async compose({ to = '', subject = '', body = '', cc = '', bcc = '' } = {}) {
    // En mode web : le lien mailto: se construit CÔTÉ NAVIGATEUR — la fenêtre
    // de composition s'ouvre dans le client mail de l'appareil de l'utilisateur.
    // Pas de toast de succès ici : on ne peut pas savoir si un client mail
    // est bien installé (un « ouvert ! » serait un mensonge).
    if (!App.api || App.apiMode === 'http') {
      const url = this._buildMailto({ to, subject, body, cc, bcc });
      window.location.href = url;
      return true;
    }
    try {
      const r = await App.api.compose_mail({ to, subject, body, cc, bcc });
      if (r && r.ok) {
        this._toast('Composition ouverte dans ton client mail.');
        return true;
      }
      this._toast(r && r.error ? r.error : 'Impossible d’ouvrir la composition.', 'error');
      return false;
    } catch (e) {
      console.warn('Teddy.compose:', e);
      this._toast('Impossible d’ouvrir la fenêtre de composition.', 'error');
      return false;
    }
  },

  _buildMailto({ to, subject, body, cc, bcc }) {
    const enc = encodeURIComponent;
    let url = 'mailto:' + (to || '');
    const p = [];
    if (subject) p.push('subject=' + enc(subject));
    if (body)    p.push('body=' + enc(body));
    if (cc)      p.push('cc=' + enc(cc));
    if (bcc)     p.push('bcc=' + enc(bcc));
    if (p.length) url += '?' + p.join('&');
    return url;
  },

  // ---- Bouton réutilisable (HTML string) ----
  /**
   * @param {{label?: string, action?: 'open'|'compose', to?: string,
   *          subject?: string, body?: string, size?: 'sm'|'md', icon?: boolean}} opts
   */
  button(opts = {}) {
    const {
      label = 'Ouvrir dans Teddy Mail',
      action = 'open',
      to = '', subject = '', body = '',
      size = 'sm',
      icon = true,
    } = opts;

    const sizeCls = size === 'sm'
      ? 'text-xs px-2.5 py-1.5'
      : 'text-sm px-3.5 py-2';

    // Icône Teddy = petit ours stylisé (≃ 14px)
    const iconSvg = icon ? `
      <svg viewBox="0 0 24 24" class="w-3.5 h-3.5 shrink-0" fill="none" aria-hidden="true"
           stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="6.5" cy="6.5" r="2.5"/>
        <circle cx="17.5" cy="6.5" r="2.5"/>
        <path d="M4 14a8 8 0 0116 0v3a4 4 0 01-4 4H8a4 4 0 01-4-4v-3z"/>
        <circle cx="9" cy="14" r="0.8" fill="currentColor"/>
        <circle cx="15" cy="14" r="0.8" fill="currentColor"/>
      </svg>` : '';

    // On encode les paramètres dans data-* pour que le handler global les retrouve
    const enc = (s) => String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/"/g, '&quot;');

    return `
      <button type="button" class="teddy-btn inline-flex items-center gap-1.5 rounded-lg
                     bg-surface-elevated hover:bg-bg border border-border
                     hover:border-accent transition-colors font-medium
                     text-text-secondary hover:text-text ${sizeCls}"
              title="${enc(label)}" aria-label="${enc(label)}"
              data-teddy-action="${enc(action)}"
              data-teddy-to="${enc(to)}"
              data-teddy-subject="${enc(subject)}"
              data-teddy-body="${enc(body)}">
        ${iconSvg}
        <span>${enc(label)}</span>
      </button>
    `;
  },

  // ---- Délégation globale : un seul listener body pour tous les boutons ----
  init() {
    document.body.addEventListener('click', async (e) => {
      const btn = e.target.closest('.teddy-btn');
      if (!btn) return;
      e.preventDefault();
      e.stopPropagation();
      const action = btn.dataset.teddyAction || 'open';
      if (action === 'compose') {
        await this.compose({
          to:      btn.dataset.teddyTo || '',
          subject: btn.dataset.teddySubject || '',
          body:    btn.dataset.teddyBody || '',
        });
      } else {
        await this.open();
      }
    }, true);
  },
};

window.addEventListener('DOMContentLoaded', () => Teddy.init());
