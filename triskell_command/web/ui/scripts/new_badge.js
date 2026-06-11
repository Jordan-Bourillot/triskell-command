/* NewBadge — petite pastille "NEW" à côté des nouveautés UI.
 *
 * - Chaque badge a un id unique (clé localStorage).
 * - Clic sur la croix → marqué "vu" → ne s'affiche plus, jamais (sur ce navigateur).
 * - Expiration automatique : la 1re apparition est horodatée (localStorage) ;
 *   après 10 jours, la pastille disparaît d'elle-même, même sans clic.
 * - Si déjà dismiss / expiré, NewBadge.attach() ne fait rien (no-op silencieux).
 *
 * Usage :
 *   NewBadge.attach(elem, 'unique-id');                    // pastille en absolute, coin haut-droit
 *   NewBadge.attach(elem, 'unique-id', {inline: true});    // pastille insérée juste après l'élément
 */
const NewBadge = {
  _styleInjected: false,
  STORAGE_PREFIX: 'tc-new:',
  FIRST_SEEN_PREFIX: 'tc-new-seen:',
  MAX_AGE_MS: 10 * 24 * 60 * 60 * 1000, // 10 jours puis la pastille s'efface seule

  isDismissed(id) {
    try {
      return localStorage.getItem(this.STORAGE_PREFIX + id) === 'dismissed';
    } catch (e) { return false; }
  },

  dismiss(id) {
    try { localStorage.setItem(this.STORAGE_PREFIX + id, 'dismissed'); }
    catch (e) {}
  },

  /** Horodate la 1re apparition ; vrai si la pastille a dépassé 10 jours. */
  _isExpired(id) {
    try {
      const key = this.FIRST_SEEN_PREFIX + id;
      const firstSeen = parseInt(localStorage.getItem(key) || '0', 10);
      if (!firstSeen) {
        localStorage.setItem(key, String(Date.now()));
        return false;
      }
      return (Date.now() - firstSeen) > this.MAX_AGE_MS;
    } catch (e) { return false; }
  },

  _injectStyles() {
    if (this._styleInjected) return;
    this._styleInjected = true;
    const s = document.createElement('style');
    s.id = 'new-badge-styles';
    s.textContent = `
      .new-badge {
        display: inline-flex;
        align-items: center;
        gap: 2px;
        padding: 1px 4px 1px 5px;
        border-radius: 5px;
        font-size: 10px;
        font-weight: 800;
        letter-spacing: 0.6px;
        background: hsl(var(--danger));
        color: hsl(var(--on-accent));
        text-transform: uppercase;
        line-height: 1.2;
        white-space: nowrap;
        box-shadow: 0 1px 3px hsl(var(--danger) / 0.4);
        z-index: 5;
        pointer-events: auto;
      }
      .new-badge-abs {
        position: absolute;
        top: -6px;
        right: -8px;
      }
      .new-badge-inline {
        margin-left: 6px;
        vertical-align: middle;
      }
      .new-badge button {
        appearance: none;
        background: transparent;
        border: 0;
        color: hsl(var(--on-accent) / 0.85);
        font-size: 11px;
        line-height: 1;
        padding: 0 1px 0 2px;
        margin-left: 1px;
        cursor: pointer;
      }
      .new-badge button:hover { color: hsl(var(--on-accent)); }
      /* Variante verte discrète — pour les nouveautés récentes */
      .new-badge.is-green {
        background: hsl(var(--success));
        color: hsl(var(--on-success));
        font-size: 10px;
        padding: 1px 3px 1px 4px;
        letter-spacing: 0.4px;
        box-shadow: 0 1px 2px hsl(var(--success) / 0.3);
        opacity: 0.92;
      }
      .new-badge.is-green:hover { opacity: 1; }
      .new-badge.is-green button { color: hsl(var(--on-success) / 0.85); }
      .new-badge.is-green button:hover { color: hsl(var(--on-success)); }
      /* Variante rouge "gros" — pour signaler une nouveauté majeure dans la sidebar */
      .new-badge.is-red-big {
        font-size: 10.5px;
        font-weight: 800;
        padding: 2px 7px 2px 8px;
        letter-spacing: 0.8px;
        box-shadow: 0 2px 6px hsl(var(--danger) / 0.55);
        animation: newBadgePulse 1.8s ease-in-out infinite;
      }
      .new-badge.is-red-big button {
        font-size: 12px;
        padding-left: 4px;
      }
      @keyframes newBadgePulse {
        0%, 100% { box-shadow: 0 2px 6px hsl(var(--danger) / 0.55); transform: scale(1); }
        50%      { box-shadow: 0 2px 12px hsl(var(--danger) / 0.85); transform: scale(1.05); }
      }
    `;
    document.head.appendChild(s);
  },

  /** Ajoute le badge si pas encore vu ni expiré. Renvoie l'élément badge (ou null). */
  attach(targetEl, id, options = {}) {
    if (!targetEl || !id) return null;
    if (this.isDismissed(id)) return null;
    if (this._isExpired(id)) {
      // Pastille trop vieille : on la marque vue pour ne plus jamais la recalculer
      this.dismiss(id);
      return null;
    }
    this._injectStyles();

    // Évite les doublons sur le même élément + id
    const existing = targetEl.querySelector
      ? targetEl.querySelector(`[data-new-badge="${id}"]`)
      : null;
    if (existing) return existing;

    const badge = document.createElement('span');
    const variantCls = options.variant === 'green'   ? ' is-green'
                     : options.variant === 'red-big' ? ' is-red-big'
                     : '';
    badge.className = 'new-badge ' + (options.inline ? 'new-badge-inline' : 'new-badge-abs') + variantCls;
    badge.innerHTML = `<span>NEW</span><button type="button" title="Marquer comme vu" aria-label="Marquer comme vu">×</button>`;
    badge.dataset.newBadge = id;
    if (options.title) badge.title = options.title;

    if (options.inline) {
      if (targetEl.parentNode) {
        targetEl.parentNode.insertBefore(badge, targetEl.nextSibling);
      }
    } else {
      const cs = window.getComputedStyle(targetEl);
      if (cs.position === 'static') {
        targetEl.style.position = 'relative';
      }
      targetEl.appendChild(badge);
    }

    badge.querySelector('button').onclick = (e) => {
      e.stopPropagation();
      e.preventDefault();
      this.dismiss(id);
      badge.remove();
    };

    return badge;
  },
};

window.NewBadge = NewBadge;

/* ─────────────────────────────────────────────────────────────
 * Registre auto-attaché : pastilles "NEW" pour les vraies
 * nouveautés en cours (refonte prospection du 10/06/2026).
 * Les pastilles s'effacent seules après 10 jours (voir NewBadge).
 *
 * Le DOM des vues étant dynamique (re-render à chaque navigation),
 * on ré-essaie d'attacher après chaque mutation majeure, debounce 150ms.
 * Chaque badge est dismissable via la croix, indépendamment des autres.
 * Quand tout est dismissé, on déconnecte l'observer.
 * ───────────────────────────────────────────────────────────── */
const NewFeaturesSinceYesterday = {
  features: [
    // Sidebar — "Lancer une prospection" : toute la chaîne en un clic
    { selector: '[data-view="prospection"]',
      id: 'prospection-launcher-v2',
      title: 'Nouveau : toute la chaîne en un clic' },
    // Sidebar — Mails : nouvel onglet Programmés
    { selector: '[data-view="mails"][data-tab="sent"]',
      id: 'mails-programmes-v1',
      title: 'Nouveau : onglet Programmés' },
  ],

  allDismissed() {
    return this.features.every(f => NewBadge.isDismissed(f.id));
  },

  tryAttachAll() {
    this.features.forEach(f => {
      const el = document.querySelector(f.selector);
      if (el) NewBadge.attach(el, f.id, {
        variant: f.variant || 'green',
        inline: !!f.inline,
        title: f.title || '',
      });
    });
  },

  init() {
    this.tryAttachAll();
    if (this.allDismissed()) return;
    let pending = null;
    const obs = new MutationObserver(() => {
      if (pending) return;
      pending = setTimeout(() => {
        pending = null;
        this.tryAttachAll();
        if (this.allDismissed()) obs.disconnect();
      }, 150);
    });
    obs.observe(document.body, { childList: true, subtree: true });
  },
};

window.addEventListener('DOMContentLoaded', () => NewFeaturesSinceYesterday.init());
window.NewFeaturesSinceYesterday = NewFeaturesSinceYesterday;
