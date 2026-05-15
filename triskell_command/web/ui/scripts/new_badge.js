/* NewBadge — petite pastille "NEW" rouge à côté des nouveautés UI.
 *
 * - Chaque badge a un id unique (clé localStorage).
 * - Clic sur la croix → marqué "vu" → ne s'affiche plus, jamais (sur ce navigateur).
 * - Si déjà dismiss, NewBadge.attach() ne fait rien (no-op silencieux).
 *
 * Usage :
 *   NewBadge.attach(elem, 'unique-id');                    // pastille en absolute, coin haut-droit
 *   NewBadge.attach(elem, 'unique-id', {inline: true});    // pastille insérée juste après l'élément
 */
const NewBadge = {
  _styleInjected: false,
  STORAGE_PREFIX: 'tc-new:',

  isDismissed(id) {
    try {
      return localStorage.getItem(this.STORAGE_PREFIX + id) === 'dismissed';
    } catch (e) { return false; }
  },

  dismiss(id) {
    try { localStorage.setItem(this.STORAGE_PREFIX + id, 'dismissed'); }
    catch (e) {}
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
        font-size: 8.5px;
        font-weight: 800;
        letter-spacing: 0.6px;
        background: #ef4444;
        color: white;
        text-transform: uppercase;
        line-height: 1.2;
        white-space: nowrap;
        box-shadow: 0 1px 3px rgba(239,68,68,0.4);
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
        color: rgba(255,255,255,0.85);
        font-size: 11px;
        line-height: 1;
        padding: 0 1px 0 2px;
        margin-left: 1px;
        cursor: pointer;
      }
      .new-badge button:hover { color: white; }
    `;
    document.head.appendChild(s);
  },

  /** Ajoute le badge si pas encore vu. Renvoie l'élément badge (ou null). */
  attach(targetEl, id, options = {}) {
    if (!targetEl || !id) return null;
    if (this.isDismissed(id)) return null;
    this._injectStyles();

    // Évite les doublons sur le même élément + id
    const existing = targetEl.querySelector
      ? targetEl.querySelector(`[data-new-badge="${id}"]`)
      : null;
    if (existing) return existing;

    const badge = document.createElement('span');
    badge.className = 'new-badge ' + (options.inline ? 'new-badge-inline' : 'new-badge-abs');
    badge.innerHTML = `<span>NEW</span><button type="button" title="Marquer comme vu">×</button>`;
    badge.dataset.newBadge = id;

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
