/* UserBadge — bandeau "Connecté en tant que X" en bas de la sidebar.
 *
 * Lit App.currentUser (rempli par Onboarding.checkAndShow ou App.init),
 * affiche un avatar généré (initiales colorées) + nom complet.
 * Click sur le badge → ouvre Réglages.
 */

const UserBadge = {
  init() {
    this.refresh();
  },

  refresh() {
    const slot = document.getElementById('user-badge-slot');
    if (!slot) return;
    const u = App.currentUser || {};
    const fullName = u.full_name || '';
    const firstName = u.first_name || fullName.split(' ')[0] || '';
    const email = u.email || '';

    if (!fullName) {
      // Onboarding pas encore fait : on n'affiche rien (la modale s'occupe de tout)
      slot.innerHTML = '';
      return;
    }

    const initials = this._initials(fullName);
    const color = this._colorFor(fullName);

    slot.innerHTML = `
      <button id="user-badge-btn"
              class="w-full flex items-center gap-2 px-2 py-1.5 rounded-lg
                     hover:bg-bg transition-colors text-left group"
              title="Connecté en tant que ${this._esc(fullName)}${email ? ' (' + this._esc(email) + ')' : ''}\nCliquer pour ouvrir les Réglages">
        <div class="w-7 h-7 rounded-full flex items-center justify-center
                    text-[10px] font-bold text-white shrink-0"
             style="background: ${color};">
          ${this._esc(initials)}
        </div>
        <div class="flex-1 text-sm font-semibold truncate">${this._esc(firstName)}</div>
        <svg class="w-3.5 h-3.5 text-text-muted shrink-0 opacity-0 group-hover:opacity-100 transition-opacity" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
          <circle cx="12" cy="12" r="3"/>
          <path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 11-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 008.18 19a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 11-2.83-2.83l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H2a2 2 0 010-4h.09A1.65 1.65 0 003.6 8.18a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 112.83-2.83l.06.06a1.65 1.65 0 001.82.33H8a1.65 1.65 0 001-1.51V2a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 112.83 2.83l-.06.06a1.65 1.65 0 00-.33 1.82V8a1.65 1.65 0 001.51 1H22a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z"/>
        </svg>
      </button>
    `;

    document.getElementById('user-badge-btn').onclick = () => App.show('config');
  },

  _initials(fullName) {
    const parts = fullName.trim().split(/\s+/);
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
    return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
  },

  // Couleur de l'avatar dérivée déterministe du nom (hash → hue)
  _colorFor(name) {
    let hash = 0;
    for (let i = 0; i < name.length; i++) {
      hash = name.charCodeAt(i) + ((hash << 5) - hash);
    }
    const hue = Math.abs(hash) % 360;
    return `linear-gradient(135deg, hsl(${hue}, 65%, 50%), hsl(${(hue + 30) % 360}, 60%, 45%))`;
  },

  _esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    }[c]));
  },
};

window.addEventListener('DOMContentLoaded', () => UserBadge.init());
