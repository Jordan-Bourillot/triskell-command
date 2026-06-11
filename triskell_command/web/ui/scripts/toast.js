/* Toast + Dialog — le système COMMUN de retours utilisateur.
 * Créé lors de la refonte du 10/06/2026 (audit UX) : avant, plusieurs
 * écrans appelaient un objet `Toast` ou `App.toast` qui n'existait pas,
 * et tous leurs messages partaient dans le vide.
 *
 * API :
 *   Toast.show(message, {type, title, duration})
 *   Toast.success / Toast.error / Toast.warn / Toast.info (message, title?)
 *   Toast.friendlyError(err, fallback?)  → message français propre + détail en console
 *   Dialog.confirm(message, {title, okLabel, cancelLabel, danger}) → Promise<boolean>
 *
 * Compat (posée au DOMContentLoaded) :
 *   App.toast(message, opts) — appelable, avec .success/.error/.warn/.info/.show
 *   App.notify = App.toast
 */
(function () {
  'use strict';

  const TYPES = {
    success: { icon: '✓', live: 'polite',    color: 'var(--success-text)' },
    error:   { icon: '✗', live: 'assertive', color: 'var(--danger-text)' },
    warn:    { icon: '⚠', live: 'polite',    color: 'var(--warning-text)' },
    info:    { icon: 'ℹ', live: 'polite',    color: 'var(--info-text)' },
  };

  const STYLE = `
    #tc-toast-host {
      position: fixed;
      right: 16px;
      bottom: calc(16px + env(safe-area-inset-bottom, 0px));
      z-index: 900;
      display: flex;
      flex-direction: column;
      align-items: flex-end;
      gap: 8px;
      pointer-events: none;
      max-width: min(380px, calc(100vw - 24px));
    }
    .tc-toast {
      pointer-events: auto;
      display: flex;
      align-items: flex-start;
      gap: 10px;
      width: 100%;
      padding: 10px 10px 10px 12px;
      border-radius: 12px;
      background: hsl(var(--surface-elevated));
      color: hsl(var(--text));
      border: 1px solid hsl(var(--border-strong));
      border-left: 3px solid hsl(var(--tc-toast-color, var(--accent)));
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.18), 0 12px 32px rgba(0, 0, 0, 0.14);
      font-size: 12.5px;
      line-height: 1.45;
      animation: tcToastIn 200ms cubic-bezier(0.16, 1, 0.3, 1);
    }
    .tc-toast.is-leaving { opacity: 0; transform: translateY(6px); transition: opacity 180ms, transform 180ms; }
    .tc-toast-icon { flex: 0 0 auto; font-weight: 700; color: hsl(var(--tc-toast-color, var(--accent))); }
    .tc-toast-body { flex: 1 1 auto; min-width: 0; }
    .tc-toast-title { font-weight: 700; font-size: 13px; margin-bottom: 1px; }
    .tc-toast-msg { color: hsl(var(--text-secondary)); overflow-wrap: anywhere; }
    .tc-toast-count {
      flex: 0 0 auto; align-self: center;
      min-width: 20px; height: 20px; padding: 0 5px; border-radius: 999px;
      background: hsl(var(--tc-toast-color, var(--accent)) / 0.18);
      color: hsl(var(--tc-toast-color, var(--accent)));
      font-size: 11px; font-weight: 700;
      display: flex; align-items: center; justify-content: center;
    }
    .tc-toast-close {
      flex: 0 0 auto;
      width: 28px; height: 28px; margin: -4px -4px -4px 0;
      border-radius: 8px; border: 0; background: transparent;
      color: hsl(var(--text-muted));
      font-size: 16px; line-height: 1; cursor: pointer;
    }
    .tc-toast-close:hover { background: hsl(var(--text) / 0.08); color: hsl(var(--text)); }
    .tc-toast-close:focus-visible { outline: 2px solid hsl(var(--accent)); outline-offset: 1px; }
    @keyframes tcToastIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }

    #tc-dialog-overlay {
      position: fixed; inset: 0; z-index: 940;
      background: hsl(var(--bg) / 0.65);
      display: flex; align-items: center; justify-content: center;
      padding: 16px;
    }
    .tc-dialog {
      width: 100%; max-width: 400px;
      background: hsl(var(--surface-elevated));
      color: hsl(var(--text));
      border: 1px solid hsl(var(--border-strong));
      border-radius: 16px;
      box-shadow: 0 10px 40px rgba(0, 0, 0, 0.30);
      padding: 18px;
      animation: tcToastIn 180ms cubic-bezier(0.16, 1, 0.3, 1);
    }
    .tc-dialog-title { font-weight: 700; font-size: 15px; margin-bottom: 6px; }
    .tc-dialog-msg { font-size: 13px; color: hsl(var(--text-secondary)); line-height: 1.5; white-space: pre-line; }
    .tc-dialog-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }
    .tc-dialog-btn {
      border-radius: 10px; padding: 8px 14px; font-size: 13px; font-weight: 600;
      border: 1px solid hsl(var(--border-strong)); background: transparent; color: hsl(var(--text));
      cursor: pointer; min-height: 38px;
    }
    .tc-dialog-btn:hover { background: hsl(var(--text) / 0.06); }
    .tc-dialog-btn:focus-visible { outline: 2px solid hsl(var(--accent)); outline-offset: 1px; }
    .tc-dialog-btn--ok { background: hsl(var(--accent-strong)); border-color: transparent; color: #fff; }
    .tc-dialog-btn--ok:hover { background: hsl(var(--accent-strong-hover)); }
    .tc-dialog-btn--danger { background: hsl(var(--danger)); border-color: transparent; color: #fff; }
    .tc-dialog-btn--danger:hover { filter: brightness(0.92); }
    @media (prefers-reduced-motion: reduce) {
      .tc-toast, .tc-dialog { animation: none; }
    }
  `;

  let styleInjected = false;
  function ensureStyle() {
    if (styleInjected) return;
    const el = document.createElement('style');
    el.id = 'tc-toast-style';
    el.textContent = STYLE;
    document.head.appendChild(el);
    styleInjected = true;
  }

  const Toast = {
    _host: null,
    _recent: new Map(),   // message+type → { el, count, ts } pour dédupliquer

    _ensureHost() {
      ensureStyle();
      if (this._host && document.body.contains(this._host)) return this._host;
      const host = document.createElement('div');
      host.id = 'tc-toast-host';
      document.body.appendChild(host);
      this._host = host;
      return host;
    },

    show(message, opts = {}) {
      const type = TYPES[opts.type] ? opts.type : 'info';
      const conf = TYPES[type];
      const msg = String(message == null ? '' : message);
      const host = this._ensureHost();

      // Déduplication : même message + même type dans les 5 dernières secondes
      // → on incrémente un compteur au lieu d'empiler.
      const key = type + '|' + (opts.title || '') + '|' + msg;
      const now = Date.now();
      const prev = this._recent.get(key);
      if (prev && now - prev.ts < 5000 && document.body.contains(prev.el)) {
        prev.count += 1;
        prev.ts = now;
        let badge = prev.el.querySelector('.tc-toast-count');
        if (!badge) {
          badge = document.createElement('span');
          badge.className = 'tc-toast-count';
          prev.el.insertBefore(badge, prev.el.querySelector('.tc-toast-close'));
        }
        badge.textContent = '×' + prev.count;
        return prev.el;
      }

      const el = document.createElement('div');
      el.className = 'tc-toast';
      el.style.setProperty('--tc-toast-color', conf.color); // ex. var(--success-text)
      el.setAttribute('role', type === 'error' ? 'alert' : 'status');
      el.setAttribute('aria-live', conf.live);

      const icon = document.createElement('span');
      icon.className = 'tc-toast-icon';
      icon.textContent = conf.icon;
      icon.setAttribute('aria-hidden', 'true');

      const body = document.createElement('div');
      body.className = 'tc-toast-body';
      if (opts.title) {
        const t = document.createElement('div');
        t.className = 'tc-toast-title';
        t.textContent = String(opts.title);
        body.appendChild(t);
      }
      const m = document.createElement('div');
      m.className = 'tc-toast-msg';
      m.textContent = msg;
      body.appendChild(m);

      const close = document.createElement('button');
      close.type = 'button';
      close.className = 'tc-toast-close';
      close.setAttribute('aria-label', 'Fermer ce message');
      close.textContent = '×';

      el.appendChild(icon);
      el.appendChild(body);
      el.appendChild(close);
      host.appendChild(el);

      // Maximum 4 toasts affichés : on retire les plus anciens.
      const items = host.querySelectorAll('.tc-toast');
      if (items.length > 4) this._remove(items[0]);

      this._recent.set(key, { el, count: 1, ts: now });
      // Purge de la table de dédup (évite de grossir sans fin)
      if (this._recent.size > 30) {
        for (const [k, v] of this._recent) {
          if (now - v.ts > 10000) this._recent.delete(k);
        }
      }

      const duration = Number.isFinite(opts.duration)
        ? opts.duration
        : (type === 'error' ? 7000 : 4200);
      let timer = setTimeout(() => this._remove(el), duration);
      close.addEventListener('click', () => { clearTimeout(timer); this._remove(el); });
      // Survol = on laisse le temps de lire
      el.addEventListener('mouseenter', () => clearTimeout(timer));
      el.addEventListener('mouseleave', () => { timer = setTimeout(() => this._remove(el), 2200); });
      return el;
    },

    _remove(el) {
      if (!el || !el.parentNode) return;
      el.classList.add('is-leaving');
      setTimeout(() => { try { el.remove(); } catch (e) {} }, 200);
    },

    success(message, title) { return this.show(message, { type: 'success', title }); },
    error(message, title)   { return this.show(message, { type: 'error', title }); },
    warn(message, title)    { return this.show(message, { type: 'warn', title }); },
    info(message, title)    { return this.show(message, { type: 'info', title }); },

    /* Transforme une erreur technique en message français lisible.
     * Le détail brut part en console pour le débogage. */
    friendlyError(err, fallback) {
      const raw = err && (err.message || err.error) ? String(err.message || err.error) : String(err || '');
      let msg = fallback || 'Une erreur est survenue. Réessaie dans un instant.';
      if (/failed to fetch|networkerror|load failed|net::|ERR_INTERNET/i.test(raw)) {
        msg = 'Connexion impossible. Vérifie ta connexion internet, puis réessaie.';
      } else if (/auth_required|\b401\b/i.test(raw)) {
        msg = 'Ta session a expiré. Recharge la page pour te reconnecter.';
      } else if (/\b(timeout|timed out)\b/i.test(raw)) {
        msg = 'Le serveur met trop de temps à répondre. Réessaie dans un instant.';
      } else if (/\b(500|502|503|504)\b/.test(raw)) {
        msg = 'Le serveur a rencontré un problème. Réessaie dans un instant.';
      }
      console.warn('[Toast.friendlyError]', err);
      return this.error(msg);
    },
  };

  /* Dialog.confirm — remplaçant maison de window.confirm().
   * Stylé, thémé, fonctionne aussi quand le navigateur bloque les
   * fenêtres natives (Firefox). Retourne une promesse de booléen. */
  const Dialog = {
    confirm(message, opts = {}) {
      ensureStyle();
      return new Promise((resolve) => {
        const prevFocus = document.activeElement;
        const overlay = document.createElement('div');
        overlay.id = 'tc-dialog-overlay';
        overlay.setAttribute('role', 'dialog');
        overlay.setAttribute('aria-modal', 'true');

        const card = document.createElement('div');
        card.className = 'tc-dialog';

        if (opts.title) {
          const t = document.createElement('div');
          t.className = 'tc-dialog-title';
          t.textContent = String(opts.title);
          card.appendChild(t);
          overlay.setAttribute('aria-label', String(opts.title));
        }
        const m = document.createElement('div');
        m.className = 'tc-dialog-msg';
        m.textContent = String(message == null ? '' : message);
        card.appendChild(m);

        const actions = document.createElement('div');
        actions.className = 'tc-dialog-actions';
        const cancel = document.createElement('button');
        cancel.type = 'button';
        cancel.className = 'tc-dialog-btn';
        cancel.textContent = opts.cancelLabel || 'Annuler';
        const ok = document.createElement('button');
        ok.type = 'button';
        ok.className = 'tc-dialog-btn ' + (opts.danger ? 'tc-dialog-btn--danger' : 'tc-dialog-btn--ok');
        ok.textContent = opts.okLabel || 'Confirmer';
        actions.appendChild(cancel);
        actions.appendChild(ok);
        card.appendChild(actions);
        overlay.appendChild(card);
        document.body.appendChild(overlay);

        const done = (value) => {
          document.removeEventListener('keydown', onKey, true);
          try { overlay.remove(); } catch (e) {}
          if (prevFocus && prevFocus.focus) { try { prevFocus.focus(); } catch (e) {} }
          resolve(value);
        };
        const onKey = (e) => {
          if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); done(false); }
          if (e.key === 'Enter')  { e.preventDefault(); e.stopPropagation(); done(true); }
          if (e.key === 'Tab') {
            // Piège de focus minimal entre les 2 boutons
            e.preventDefault();
            (document.activeElement === ok ? cancel : ok).focus();
          }
        };
        document.addEventListener('keydown', onKey, true);
        cancel.addEventListener('click', () => done(false));
        ok.addEventListener('click', () => done(true));
        overlay.addEventListener('click', (e) => { if (e.target === overlay) done(false); });
        ok.focus();
      });
    },
  };

  window.Toast = Toast;
  window.Dialog = Dialog;

  // Compat : App.toast(...) appelable + méthodes, App.notify alias.
  const legacy = function (message, opts) { return Toast.show(message, opts); };
  legacy.show = (m, o) => Toast.show(m, o);
  legacy.success = (m, t) => Toast.success(m, t);
  legacy.error = (m, t) => Toast.error(m, t);
  legacy.warn = (m, t) => Toast.warn(m, t);
  legacy.info = (m, t) => Toast.info(m, t);
  function attachToApp() {
    try {
      if (typeof App !== 'undefined' && App) {
        App.toast = legacy;
        App.notify = legacy;
      }
    } catch (e) { /* App pas encore là — réessayé au DOMContentLoaded */ }
  }
  attachToApp();
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', attachToApp);
  }
})();
