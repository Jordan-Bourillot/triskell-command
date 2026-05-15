/* UserBadge — bandeau "Connecté en tant que X" en bas de la sidebar.
 *
 * Lit App.currentUser (rempli par Onboarding.checkAndShow ou App.init,
 * puis surchargé par /api/me pour donner le bon prénom selon le cookie
 * de session — Jordan / Thomas — même quand le compte Supabase est
 * partagé).
 * Affiche soit la photo de profil (si uploadée via /api/avatar) soit
 * un avatar généré (initiales colorées). Clic sur la photo = upload,
 * clic sur le nom = ouvre Réglages.
 */

const UserBadge = {
  init() {
    this.refresh();
  },

  async _fetchUserId() {
    // Récupère le user_id du cookie (jordan/thomas) — sert à savoir
    // sous quel id stocker/lire l'avatar.
    try {
      const r = await fetch('/api/me', { credentials: 'same-origin' });
      if (!r.ok) return null;
      const j = await r.json();
      return (j && j.connected) ? (j.user_id || null) : null;
    } catch (e) { return null; }
  },

  async refresh() {
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

    const userId = await this._fetchUserId();
    const initials = this._initials(fullName);
    const color = this._colorFor(fullName);
    const cacheBust = Date.now();
    const avatarUrl = userId ? `/api/avatar/${encodeURIComponent(userId)}?v=${cacheBust}` : '';

    slot.innerHTML = `
      <div class="w-full flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-bg transition-colors">
        <button id="user-badge-avatar"
                class="relative w-7 h-7 rounded-full flex items-center justify-center
                       text-[10px] font-bold text-white shrink-0 overflow-hidden group/avatar cursor-pointer"
                style="background: ${color};"
                title="Cliquer pour changer la photo">
          <span id="user-badge-initials" class="${avatarUrl ? 'hidden' : ''}">${this._esc(initials)}</span>
          ${avatarUrl ? `<img id="user-badge-img" src="${avatarUrl}" alt=""
                              class="absolute inset-0 w-full h-full object-cover"
                              onerror="this.style.display='none';document.getElementById('user-badge-initials').classList.remove('hidden');"/>` : ''}
          <span class="absolute inset-0 bg-black/50 opacity-0 group-hover/avatar:opacity-100 transition-opacity flex items-center justify-center">
            <svg class="w-3 h-3 text-white" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
              <path d="M23 19a2 2 0 01-2 2H3a2 2 0 01-2-2V8a2 2 0 012-2h4l2-3h6l2 3h4a2 2 0 012 2z"/>
              <circle cx="12" cy="13" r="4"/>
            </svg>
          </span>
        </button>
        <button id="user-badge-name"
                class="flex-1 text-sm font-semibold truncate text-left group"
                title="Connecté en tant que ${this._esc(fullName)}${email ? ' (' + this._esc(email) + ')' : ''}\nCliquer pour ouvrir les Réglages">
          ${this._esc(firstName)}
        </button>
        <input type="file" id="user-badge-file" accept="image/png,image/jpeg,image/webp,image/gif" class="hidden"/>
      </div>
    `;

    document.getElementById('user-badge-name').onclick = () => App.show('config');
    document.getElementById('user-badge-avatar').onclick = () => {
      document.getElementById('user-badge-file').click();
    };
    document.getElementById('user-badge-file').onchange = (e) => this._handleUpload(e);
  },

  async _handleUpload(event) {
    const file = event.target.files && event.target.files[0];
    if (!file) return;
    const fd = new FormData();
    fd.append('file', file);
    try {
      const r = await fetch('/api/avatar', {
        method: 'POST',
        body: fd,
        credentials: 'same-origin',
      });
      const j = await r.json().catch(() => ({}));
      if (!r.ok || !j.ok) {
        alert(j.error || 'Échec de l\'upload de la photo.');
        return;
      }
      // Recharge le badge pour afficher la nouvelle photo
      this.refresh();
    } catch (e) {
      alert('Erreur réseau : ' + (e.message || e));
    }
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
