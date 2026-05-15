/* UserBadge — bandeau "Connecté en tant que X" en bas de la sidebar.
 *
 * Lit App.currentUser (rempli par Onboarding.checkAndShow ou App.init,
 * puis surchargé par /api/me pour donner le bon prénom selon le cookie
 * de session — Jordan / Thomas — même quand le compte Supabase est
 * partagé).
 * Affiche soit la photo de profil (si uploadée via /api/avatar) soit
 * un avatar généré (initiales colorées). Clic sur la photo OU le nom =
 * ouvre la modale "Mon profil personnel" (différente des Réglages app,
 * qui se trouvent dans le bouton dédié juste en dessous).
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
      <button id="user-badge-row" type="button"
              class="w-full flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-bg transition-colors text-left"
              title="Mon profil personnel · clique pour modifier ton nom, ta photo, etc.">
        <span id="user-badge-avatar"
              class="relative w-7 h-7 rounded-full flex items-center justify-center
                     text-[10px] font-bold text-white shrink-0 overflow-hidden"
              style="background: ${color};">
          <span id="user-badge-initials" class="${avatarUrl ? 'hidden' : ''}">${this._esc(initials)}</span>
          ${avatarUrl ? `<img id="user-badge-img" src="${avatarUrl}" alt=""
                              class="absolute inset-0 w-full h-full object-cover"
                              onerror="this.style.display='none';document.getElementById('user-badge-initials').classList.remove('hidden');"/>` : ''}
        </span>
        <span class="flex-1 text-sm font-semibold truncate">${this._esc(firstName)}</span>
        <svg class="w-3.5 h-3.5 text-text-muted shrink-0" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
          <path d="M9 18l6-6-6-6"/>
        </svg>
      </button>
      <input type="file" id="user-badge-file" accept="image/png,image/jpeg,image/webp,image/gif" class="hidden"/>
    `;

    // Clic sur tout le bandeau (photo + prénom + chevron) ouvre la modale Profil
    document.getElementById('user-badge-row').onclick = () => this._openProfileModal({
      fullName, firstName, email, userId, avatarUrl, color, initials,
    });
    document.getElementById('user-badge-file').onchange = (e) => this._handleUpload(e);
  },

  /** Modale "Mon profil personnel" — différente des Réglages app. */
  _openProfileModal({ fullName, firstName, email, userId, avatarUrl, color, initials }) {
    // Évite les doubles ouvertures
    if (document.getElementById('profile-modal-overlay')) return;

    const overlay = document.createElement('div');
    overlay.id = 'profile-modal-overlay';
    overlay.className = 'fixed inset-0 z-[220] flex items-center justify-center p-4 sm:p-6';
    overlay.style.background = 'rgba(15,23,42,0.7)';
    overlay.style.backdropFilter = 'blur(8px)';

    const cacheBust = Date.now();
    const liveAvatarUrl = userId ? `/api/avatar/${encodeURIComponent(userId)}?v=${cacheBust}` : '';

    overlay.innerHTML = `
      <div class="bg-surface rounded-2xl shadow-hero w-full max-w-md border border-border animate-slide-up flex flex-col max-h-[88vh] overflow-hidden">
        <!-- Header -->
        <div class="px-6 pt-5 pb-4 flex items-start justify-between border-b border-border bg-surface-elevated">
          <div>
            <div class="text-[10px] font-bold uppercase tracking-widest text-text-muted mb-0.5">MON PROFIL</div>
            <h3 class="text-lg font-bold">Profil personnel</h3>
            <p class="text-xs text-text-muted mt-0.5">Ton nom et ta photo, visibles dans Triskell Command.<br>Pour les comptes mail / SMTP / clés API, utilise <span class="font-semibold text-text">Réglages</span> en bas de la sidebar.</p>
          </div>
          <button id="profile-close" class="w-8 h-8 rounded-lg flex items-center justify-center text-text-muted hover:text-text hover:bg-bg transition-colors text-xl leading-none shrink-0">×</button>
        </div>

        <!-- Form -->
        <div class="px-6 py-5 space-y-5 overflow-y-auto">
          <!-- Photo de profil -->
          <div class="flex items-center gap-4">
            <button id="profile-avatar-btn"
                    class="relative w-20 h-20 rounded-full flex items-center justify-center
                           text-2xl font-bold text-white shrink-0 overflow-hidden group cursor-pointer"
                    style="background: ${color};"
                    title="Cliquer pour changer la photo">
              <span id="profile-initials" class="${liveAvatarUrl ? 'hidden' : ''}">${this._esc(initials)}</span>
              ${liveAvatarUrl ? `<img id="profile-img" src="${liveAvatarUrl}" alt=""
                                      class="absolute inset-0 w-full h-full object-cover"
                                      onerror="this.style.display='none';document.getElementById('profile-initials').classList.remove('hidden');"/>` : ''}
              <span class="absolute inset-0 bg-black/55 opacity-0 group-hover:opacity-100 transition-opacity flex flex-col items-center justify-center gap-0.5 text-white">
                <svg class="w-5 h-5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                  <path d="M23 19a2 2 0 01-2 2H3a2 2 0 01-2-2V8a2 2 0 012-2h4l2-3h6l2 3h4a2 2 0 012 2z"/>
                  <circle cx="12" cy="13" r="4"/>
                </svg>
                <span class="text-[10px] font-semibold">Changer</span>
              </span>
            </button>
            <div class="flex-1 min-w-0">
              <div class="text-sm font-semibold text-text">Photo de profil</div>
              <div class="text-xs text-text-muted mt-0.5">PNG / JPG / WebP, 4 Mo max</div>
              <button id="profile-avatar-trigger" type="button"
                      class="mt-2 text-xs text-accent font-semibold hover:underline">
                Choisir une image…
              </button>
            </div>
            <input type="file" id="profile-avatar-file"
                   accept="image/png,image/jpeg,image/webp,image/gif" class="hidden"/>
          </div>

          <!-- Nom complet -->
          <div>
            <label class="block text-[11px] font-medium text-text-secondary mb-1 uppercase tracking-wider">Nom (affiché partout)</label>
            <input id="profile-fullname" type="text" value="${this._esc(fullName)}"
                   placeholder="Jordan Bourillot"
                   class="w-full px-3 py-2.5 text-sm rounded-lg bg-bg border border-border focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent"/>
            <div class="text-[10px] text-text-muted mt-1">Ton prénom (premier mot) apparaît en bas de la sidebar.</div>
          </div>

          <!-- Email -->
          <div>
            <label class="block text-[11px] font-medium text-text-secondary mb-1 uppercase tracking-wider">Email principal</label>
            <input id="profile-email" type="email" value="${this._esc(email)}"
                   placeholder="contact@triskell-studio.fr"
                   class="w-full px-3 py-2.5 text-sm rounded-lg bg-bg border border-border focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent"/>
            <div class="text-[10px] text-text-muted mt-1">Sert d'expéditeur par défaut pour tes mails.</div>
          </div>

          <div id="profile-status" class="text-xs text-text-muted min-h-[1.25rem]"></div>
        </div>

        <!-- Footer -->
        <div class="px-6 py-4 border-t border-border bg-surface-elevated flex items-center justify-end gap-2 shrink-0">
          <button id="profile-cancel" class="btn btn-secondary">Annuler</button>
          <button id="profile-save" class="btn btn-primary">
            <svg class="w-4 h-4 mr-1.5 inline" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24">
              <path d="M5 13l4 4L19 7"/>
            </svg>
            Enregistrer
          </button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);

    const close = () => overlay.remove();
    overlay.querySelector('#profile-close').onclick = close;
    overlay.querySelector('#profile-cancel').onclick = close;
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
    const escListener = (e) => { if (e.key === 'Escape') { close(); document.removeEventListener('keydown', escListener); } };
    document.addEventListener('keydown', escListener);

    // Photo : déclencheurs
    const fileInput = overlay.querySelector('#profile-avatar-file');
    overlay.querySelector('#profile-avatar-btn').onclick = () => fileInput.click();
    overlay.querySelector('#profile-avatar-trigger').onclick = () => fileInput.click();
    fileInput.onchange = async (e) => {
      const status = overlay.querySelector('#profile-status');
      status.textContent = 'Upload de la photo…';
      status.className = 'text-xs text-text-muted min-h-[1.25rem]';
      const ok = await this._handleUploadInModal(e, overlay);
      if (ok) {
        status.textContent = '✓ Photo mise à jour';
        status.className = 'text-xs text-success min-h-[1.25rem]';
      } else {
        status.textContent = '';
      }
    };

    // Enregistrer (nom + email)
    overlay.querySelector('#profile-save').onclick = async () => {
      const fullVal  = overlay.querySelector('#profile-fullname').value.trim();
      const emailVal = overlay.querySelector('#profile-email').value.trim();
      const status   = overlay.querySelector('#profile-status');
      if (!fullVal) {
        status.textContent = '✗ Le nom est obligatoire.';
        status.className = 'text-xs text-danger min-h-[1.25rem]';
        return;
      }
      if (emailVal && !emailVal.includes('@')) {
        status.textContent = '✗ Email invalide.';
        status.className = 'text-xs text-danger min-h-[1.25rem]';
        return;
      }
      const saveBtn = overlay.querySelector('#profile-save');
      saveBtn.disabled = true;
      saveBtn.innerHTML = 'Enregistrement…';
      try {
        const r = await App.api.save_user_identity({ full_name: fullVal, email: emailVal });
        if (r && r.ok) {
          // Met à jour le badge en local + côté App.currentUser
          App.currentUser = App.currentUser || {};
          App.currentUser.full_name  = fullVal;
          App.currentUser.first_name = fullVal.split(' ')[0] || '';
          App.currentUser.email      = emailVal;
          status.textContent = '✓ Profil enregistré.';
          status.className = 'text-xs text-success min-h-[1.25rem]';
          this.refresh();
          setTimeout(close, 800);
        } else {
          status.textContent = `✗ ${(r && r.error) || 'Erreur inconnue'}`;
          status.className = 'text-xs text-danger min-h-[1.25rem]';
          saveBtn.disabled = false;
          saveBtn.innerHTML = '<svg class="w-4 h-4 mr-1.5 inline" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><path d="M5 13l4 4L19 7"/></svg>Enregistrer';
        }
      } catch (e) {
        status.textContent = `✗ ${e.message || e}`;
        status.className = 'text-xs text-danger min-h-[1.25rem]';
        saveBtn.disabled = false;
        saveBtn.innerHTML = '<svg class="w-4 h-4 mr-1.5 inline" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><path d="M5 13l4 4L19 7"/></svg>Enregistrer';
      }
    };
  },

  /** Upload photo depuis la modale Profil. Renvoie true si succès. */
  async _handleUploadInModal(event, overlay) {
    const file = event.target.files && event.target.files[0];
    if (!file) return false;
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
        return false;
      }
      // Recharge la preview dans la modale + le badge sidebar
      const userId = await this._fetchUserId();
      if (userId) {
        const newUrl = `/api/avatar/${encodeURIComponent(userId)}?v=${Date.now()}`;
        const img = overlay.querySelector('#profile-img');
        const initials = overlay.querySelector('#profile-initials');
        if (img) {
          img.src = newUrl;
          img.classList.remove('hidden');
          if (initials) initials.classList.add('hidden');
        } else {
          // Pas d'<img> existant : on l'ajoute
          const btn = overlay.querySelector('#profile-avatar-btn');
          if (initials) initials.classList.add('hidden');
          const newImg = document.createElement('img');
          newImg.id = 'profile-img';
          newImg.src = newUrl;
          newImg.alt = '';
          newImg.className = 'absolute inset-0 w-full h-full object-cover';
          btn.appendChild(newImg);
        }
      }
      this.refresh();
      return true;
    } catch (e) {
      alert('Erreur réseau : ' + (e.message || e));
      return false;
    }
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
