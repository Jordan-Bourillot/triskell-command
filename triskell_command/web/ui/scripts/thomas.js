/* Thomas — chat 1-à-1 Jordan ↔ Thomas (équivalent web du FAB Tk).
 *
 * Utilise les méthodes API Python `messages_*` exposées dans web/api.py :
 *   - messages_other_user, messages_list, messages_send,
 *     messages_mark_read, messages_count_unread,
 *     messages_set_typing, messages_peer_typing.
 *
 * Polling :
 *   - Liste + non-lus + peer_typing toutes les 5 secondes (en arrière-plan)
 *   - Toutes les 1.5 secondes quand la modale est ouverte
 *   - Côté envoi : set_typing(true) toutes les 2s max pendant la frappe
 */

const Thomas = {
  open: false,
  pollHandle: null,
  pollIntervalMs: 5000,       // arrière-plan
  pollIntervalOpenMs: 1500,   // modale ouverte
  lastTypingPing: 0,
  typingIdleTimeout: null,
  myUserId: null,
  myColor: '#7C7FE9',         // couleur de mes bulles (rechargée depuis l'API)
  otherColor: '#10b981',      // couleur des bulles de l'autre
  cachedMessages: [],
  pendingAttachment: null,    // {url, name, type, size} entre upload et envoi

  init() {
    const fab = document.getElementById('thomas-fab');
    const dlg = document.getElementById('thomas-dialog');
    const closeBtn = document.getElementById('thomas-dialog-close');
    const input = document.getElementById('thomas-input');
    const sendBtn = document.getElementById('thomas-send');

    if (!dlg) return;
    // Le FAB est désormais masqué globalement (le bouton "Chat" du Cockpit
    // est l'entrée standard) mais on garde le bind si l'élément existe.
    if (fab) fab.addEventListener('click', () => this.openDialog());
    closeBtn.addEventListener('click', () => this.closeDialog());

    // Fermer la modale en cliquant sur le fond noir (pas sur le panneau)
    dlg.addEventListener('click', (e) => {
      if (e.target === dlg) this.closeDialog();
    });

    // Envoyer message
    sendBtn.addEventListener('click', () => this.send());
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        this.send();
      }
    });
    input.addEventListener('input', () => this.notifyTyping());

    // Pièce jointe : trombone ouvre le picker de fichier
    const attachBtn = document.getElementById('thomas-attach-btn');
    const attachFile = document.getElementById('thomas-attach-file');
    if (attachBtn && attachFile) {
      attachBtn.addEventListener('click', () => attachFile.click());
      attachFile.addEventListener('change', (e) => {
        const f = e.target.files && e.target.files[0];
        if (f) this._uploadAttachment(f);
        attachFile.value = '';  // permet de re-choisir le même fichier
      });
    }

    // Sélecteur de couleur perso
    const colorBtn = document.getElementById('thomas-color-btn');
    if (colorBtn) colorBtn.addEventListener('click', () => this._openColorPicker());

    // Lightbox : clic sur fond ou bouton × ferme
    const lightbox = document.getElementById('thomas-lightbox');
    const lightboxClose = document.getElementById('thomas-lightbox-close');
    if (lightbox) {
      lightbox.addEventListener('click', (e) => {
        if (e.target === lightbox) this._closeLightbox();
      });
    }
    if (lightboxClose) lightboxClose.addEventListener('click', () => this._closeLightbox());

    // F11 pour ouvrir le chat
    window.addEventListener('keydown', (e) => {
      if (e.key === 'F11') {
        e.preventDefault();
        this.openDialog();
      }
      if (e.key === 'Escape') {
        // Lightbox ouvert : on ferme la lightbox d'abord
        const lb = document.getElementById('thomas-lightbox');
        if (lb && !lb.classList.contains('hidden')) {
          this._closeLightbox();
          return;
        }
        if (this.open) this.closeDialog();
      }
    });

    // Démarre le polling en arrière-plan une fois App.api dispo
    this.bootstrap();
  },

  async bootstrap() {
    // Attend que App.api soit prêt — plus tolérant qu'avant (60s au lieu
    // de 15s) car en mode HTTP le boot peut être lent (workers, vues
    // Supabase, etc.). Si on dépasse, on programme une réessai dans 10s
    // au lieu d'abandonner définitivement.
    // NOTE : on check `App` (const du scope global du script) et PAS
    // `window.App` car `const App = ...` dans app.js n'est PAS exposé
    // sur window (les const top-level d'un script classique restent dans
    // le script-scope). Avant ce fix, le check `!window.App` était
    // toujours vrai → bootstrap abandonnait toujours et le chat restait
    // muet.
    let tries = 0;
    while (tries < 240) {
      if (typeof App !== 'undefined' && App.api && App.api.messages_other_user) break;
      await new Promise(r => setTimeout(r, 250));
      tries++;
    }
    if (typeof App === 'undefined' || !App.api) {
      console.warn('Thomas: App.api pas encore disponible — réessai dans 10s');
      setTimeout(() => this.bootstrap(), 10000);
      return;
    }

    // Récupère mon user_id + ma couleur de chat
    try {
      const me = await App.api.messages_me();
      if (me && me.ok) {
        if (me.user_id) this.myUserId = me.user_id;
        if (me.color) this.myColor = me.color;
      }
    } catch (e) {}

    // Récupère le profil de l'autre user (nom + couleur)
    try {
      const res = await App.api.messages_other_user();
      const other = res && res.ok ? res.other : null;
      if (!other) {
        // Cas théorique impossible (jordan & thomas sont toujours opposés)
        // mais on reste défensif si la config future change.
        const fabEl = document.getElementById('thomas-fab');
        if (fabEl) fabEl.classList.add('hidden');
        return;
      }
      if (other.color) this.otherColor = other.color;
      const name = other.display_name || 'Thomas';
      document.getElementById('thomas-dialog-name').textContent = name;
      document.getElementById('thomas-dialog-avatar').textContent =
        (name[0] || 'T').toUpperCase();
      const fab = document.getElementById('thomas-fab');
      if (fab) {
        fab.classList.remove('hidden');
        fab.title = `Chat avec ${name} · F11`;
      }
    } catch (e) {
      console.warn('Thomas bootstrap:', e);
    }

    // Premier ping + polling continu
    await this.pollUnread();
    this.startPolling();
  },

  startPolling() {
    if (this.pollHandle) clearInterval(this.pollHandle);
    const ms = this.open ? this.pollIntervalOpenMs : this.pollIntervalMs;
    this.pollHandle = setInterval(() => this.tick(), ms);
  },

  async tick() {
    if (this.open) {
      await this.refreshMessages();
      await this.refreshPeerTyping();
    } else {
      await this.pollUnread();
    }
  },

  async pollUnread() {
    if (typeof App === 'undefined' || !App.api) return;
    try {
      const res = await App.api.messages_count_unread();
      this.updateBadge(res && res.ok ? (res.count || 0) : 0);
    } catch (e) {}
  },

  updateBadge(n) {
    // Met à jour les deux pastilles : l'ancienne du FAB (désormais caché)
    // et la nouvelle du bouton "Chat" intégré dans la barre du Cockpit.
    const targets = [
      document.getElementById('thomas-fab-badge'),
      document.getElementById('m-chat-thomas-badge'),
    ];
    for (const badge of targets) {
      if (!badge) continue;
      if (n > 0) {
        badge.textContent = n > 99 ? '99+' : String(n);
        badge.classList.remove('hidden');
      } else {
        badge.classList.add('hidden');
      }
    }
  },

  async openDialog() {
    const dlg = document.getElementById('thomas-dialog');
    dlg.classList.remove('hidden');
    dlg.classList.add('flex');
    this.open = true;
    await this.refreshMessages();
    try { await App.api.messages_mark_read(); } catch(e){}
    this.updateBadge(0);
    document.getElementById('thomas-input').focus();
    this.startPolling();
  },

  closeDialog() {
    const dlg = document.getElementById('thomas-dialog');
    dlg.classList.add('hidden');
    dlg.classList.remove('flex');
    this.open = false;
    // Stop le ping "is typing" si en cours
    if (this.typingIdleTimeout) {
      clearTimeout(this.typingIdleTimeout);
      this.typingIdleTimeout = null;
    }
    try { App.api.messages_set_typing({ active: false }); } catch(e){}
    this.startPolling();
  },

  async refreshMessages() {
    if (typeof App === 'undefined' || !App.api) return;
    try {
      const res = await App.api.messages_list({ limit: 100 });
      const msgs = (res && res.ok ? res.messages : []) || [];
      // Optim : on évite de re-render si on a DÉJÀ affiché ces mêmes
      // messages. Mais surtout : on rend toujours au moins une fois,
      // sinon le 1er affichage reste vide quand cachedMessages et
      // msgs sont tous les deux vides au boot.
      const el = document.getElementById('thomas-messages');
      const lastA = this.cachedMessages.length
        ? this.cachedMessages[this.cachedMessages.length - 1].id : null;
      const lastB = msgs.length ? msgs[msgs.length - 1].id : null;
      const noChange = lastA === lastB && this.cachedMessages.length === msgs.length;
      const alreadyRendered = el && el.innerHTML.trim().length > 0;
      if (noChange && alreadyRendered) return;
      this.cachedMessages = msgs;
      this.renderMessages(msgs);
    } catch (e) { /* silencieux */ }
  },

  renderMessages(msgs) {
    const el = document.getElementById('thomas-messages');
    if (!el) return;

    const html = msgs.map(m => {
      const isFromMe = this._isFromMe(m);
      const align = isFromMe ? 'justify-end' : 'justify-start';
      // Couleur de fond = couleur perso de l'expéditeur (moi ou l'autre).
      // Texte blanc systématiquement — toutes les couleurs de la palette
      // sont assez saturées pour garantir le contraste.
      const bgColor = isFromMe ? this.myColor : this.otherColor;
      const corner = isFromMe ? 'rounded-br-sm' : 'rounded-bl-sm';
      const time = this._fmtTime(m.created_at);
      const bodyHtml = m.body
        ? `<div class="text-sm whitespace-pre-wrap break-words">${this._escape(m.body)}</div>`
        : '';
      const attachHtml = m.attachment_url
        ? this._renderAttachment(m)
        : '';
      return `
        <div class="flex ${align}">
          <div class="max-w-[75%] px-3 py-2 rounded-2xl ${corner} text-white"
               style="background:${this._escape(bgColor)};">
            ${attachHtml}
            ${bodyHtml}
            <div class="text-[10px] opacity-70 mt-1 text-right">${time}</div>
          </div>
        </div>`;
    }).join('');

    el.innerHTML = html || `
      <div class="text-center text-text-muted text-xs py-8">
        Aucun message pour l'instant. Envoie le premier ! 👋
      </div>`;

    // Bind les clics sur les images de pièces jointes → ouvre la lightbox
    el.querySelectorAll('[data-lightbox]').forEach(img => {
      img.addEventListener('click', () => {
        this._openLightbox(img.getAttribute('data-lightbox'),
                          img.getAttribute('alt') || '');
      });
    });

    // Scroll en bas
    el.scrollTop = el.scrollHeight;
  },

  /** Rendu HTML d'une pièce jointe. Images : <img> clicable (lightbox).
   *  Autres : lien icône + nom + taille. */
  _renderAttachment(m) {
    const url  = this._escape(m.attachment_url || '');
    const name = this._escape(m.attachment_name || 'fichier');
    const type = String(m.attachment_type || '').toLowerCase();
    const size = m.attachment_size;
    const sizeStr = (size && size > 0)
      ? ` <span class="opacity-70">· ${this._fmtSize(size)}</span>`
      : '';
    if (type.startsWith('image/')) {
      return `
        <img src="${url}" alt="${name}" data-lightbox="${url}"
             class="block rounded-lg mb-1 max-w-full h-auto cursor-zoom-in
                    hover:opacity-90 transition-opacity"
             style="max-height:240px;"/>`;
    }
    return `
      <a href="${url}" target="_blank" rel="noopener"
         class="flex items-center gap-2 px-2 py-2 rounded-lg
                bg-black/15 hover:bg-black/25 transition-colors mb-1
                text-xs text-white no-underline">
        <svg class="w-4 h-4 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48"/>
        </svg>
        <span class="break-all">${name}${sizeStr}</span>
      </a>`;
  },

  _fmtSize(bytes) {
    if (bytes < 1024) return bytes + ' o';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' Ko';
    return (bytes / (1024 * 1024)).toFixed(1) + ' Mo';
  },

  _isFromMe(msg) {
    // On lookup la valeur en mémoire au premier appel — l'API messages_list
    // renvoie sender_id et recipient_id. On déduit "moi" en regardant
    // App.currentUser ou via un appel séparé. Pour le MVP, on cache
    // l'identifiant côté front la 1ère fois qu'on envoie un message.
    return msg.sender_id && msg.sender_id === this.myUserId;
  },

  _fmtTime(iso) {
    if (!iso) return '';
    try {
      const d = new Date(iso);
      const hh = String(d.getHours()).padStart(2, '0');
      const mm = String(d.getMinutes()).padStart(2, '0');
      return `${hh}:${mm}`;
    } catch (e) { return ''; }
  },

  _escape(s) {
    return String(s)
      .replaceAll('&', '&amp;').replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;').replaceAll('"', '&quot;');
  },

  async send() {
    const input = document.getElementById('thomas-input');
    const sendBtn = document.getElementById('thomas-send');
    const body = (input.value || '').trim();
    const attachment = this.pendingAttachment;
    if (!body && !attachment) return;  // ni texte ni pj → rien à envoyer

    sendBtn.disabled = true;
    try {
      const payload = { body };
      if (attachment) payload.attachment = attachment;
      const res = await App.api.messages_send(payload);
      if (res && res.ok && res.message) {
        // Cache mon user_id pour bien aligner les bulles
        this.myUserId = res.message.sender_id;
        input.value = '';
        this._clearPendingAttachment();
        await this.refreshMessages();
        try { await App.api.messages_set_typing({ active: false }); } catch(e){}
      } else {
        console.warn('messages_send:', res);
      }
    } catch (e) {
      console.warn('send:', e);
    } finally {
      sendBtn.disabled = false;
      input.focus();
    }
  },

  /** Upload d'un fichier vers /api/chat_attachment. Au succès, on garde le
   *  résultat en `pendingAttachment` et on affiche l'aperçu au-dessus du
   *  composer. L'envoi effectif (avec ou sans texte) se fait via send(). */
  async _uploadAttachment(file) {
    const previewEl = document.getElementById('thomas-attach-preview');
    if (!previewEl) return;
    // Aperçu temporaire pendant l'upload
    previewEl.classList.remove('hidden');
    previewEl.innerHTML = `
      <div class="flex items-center gap-2 px-2 py-2 text-xs text-text-muted">
        <svg class="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M21 12a9 9 0 11-6.219-8.56" stroke-linecap="round"/>
        </svg>
        Envoi de ${this._escape(file.name)}…
      </div>`;
    try {
      const fd = new FormData();
      fd.append('file', file);
      const r = await fetch('/api/chat_attachment', {
        method: 'POST',
        body: fd,
        credentials: 'same-origin',
      });
      const j = await r.json().catch(() => ({}));
      if (!r.ok || !j.ok) {
        previewEl.innerHTML = `
          <div class="text-xs text-danger px-2 py-2">
            ✗ ${this._escape(j.error || 'Échec de l’upload.')}
          </div>`;
        setTimeout(() => this._clearPendingAttachment(), 3500);
        return;
      }
      this.pendingAttachment = {
        url: j.url, name: j.name, type: j.type, size: j.size,
      };
      this._renderPendingAttachmentPreview();
    } catch (e) {
      previewEl.innerHTML = `
        <div class="text-xs text-danger px-2 py-2">✗ Erreur réseau : ${this._escape(e.message || e)}</div>`;
      setTimeout(() => this._clearPendingAttachment(), 3500);
    }
  },

  _renderPendingAttachmentPreview() {
    const previewEl = document.getElementById('thomas-attach-preview');
    if (!previewEl || !this.pendingAttachment) return;
    const a = this.pendingAttachment;
    const isImg = String(a.type || '').toLowerCase().startsWith('image/');
    const thumb = isImg
      ? `<img src="${this._escape(a.url)}" alt=""
             class="w-12 h-12 object-cover rounded shrink-0"/>`
      : `<div class="w-12 h-12 rounded bg-bg flex items-center justify-center shrink-0">
           <svg class="w-5 h-5 text-text-muted" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
             <path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48"/>
           </svg>
         </div>`;
    previewEl.innerHTML = `
      <div class="flex items-center gap-2 py-2">
        ${thumb}
        <div class="flex-1 min-w-0">
          <div class="text-xs font-semibold text-text truncate">${this._escape(a.name)}</div>
          <div class="text-[10px] text-text-muted">${this._fmtSize(a.size || 0)} · prêt à envoyer</div>
        </div>
        <button id="thomas-attach-cancel" type="button"
                class="w-7 h-7 rounded-full text-text-muted hover:text-danger hover:bg-bg
                       transition-colors flex items-center justify-center text-lg leading-none">×</button>
      </div>`;
    const cancel = document.getElementById('thomas-attach-cancel');
    if (cancel) cancel.addEventListener('click', () => this._clearPendingAttachment());
  },

  _clearPendingAttachment() {
    this.pendingAttachment = null;
    const previewEl = document.getElementById('thomas-attach-preview');
    if (previewEl) {
      previewEl.classList.add('hidden');
      previewEl.innerHTML = '';
    }
  },

  _openLightbox(url, alt) {
    const lb = document.getElementById('thomas-lightbox');
    const img = document.getElementById('thomas-lightbox-img');
    if (!lb || !img) return;
    img.src = url;
    img.alt = alt || '';
    lb.classList.remove('hidden');
    lb.classList.add('flex');
  },

  _closeLightbox() {
    const lb = document.getElementById('thomas-lightbox');
    const img = document.getElementById('thomas-lightbox-img');
    if (!lb) return;
    lb.classList.add('hidden');
    lb.classList.remove('flex');
    if (img) img.src = '';
  },

  async _openColorPicker() {
    // Charge la palette + couleur courante depuis l'API
    let palette = [];
    let current = this.myColor;
    try {
      const r = await App.api.messages_color_palette();
      if (r && r.ok) {
        palette = r.palette || [];
        current = r.current || current;
      }
    } catch (e) {}
    if (!palette.length) {
      palette = ['#7C7FE9', '#10b981', '#3b82f6', '#f59e0b',
                 '#ef4444', '#ec4899', '#06b6d4', '#a855f7'];
    }

    // Construit la modale palette
    const overlay = document.createElement('div');
    overlay.id = 'thomas-color-overlay';
    overlay.className = 'fixed inset-0 z-[80] bg-black/50 flex items-center justify-center p-4';
    overlay.innerHTML = `
      <div class="bg-surface w-full max-w-xs rounded-2xl border border-border shadow-hero p-5">
        <div class="text-sm font-semibold text-text mb-1">Couleur de mes bulles</div>
        <div class="text-[11px] text-text-muted mb-4">Choisis la couleur dans laquelle s'affichent les messages que tu envoies. ${this._escape(this.myUserId === 'thomas' ? 'Thomas' : 'Jordan')} a sa propre couleur de son côté.</div>
        <div class="grid grid-cols-4 gap-3 mb-4">
          ${palette.map(c => `
            <button type="button" data-color="${this._escape(c)}"
                    class="w-12 h-12 rounded-full transition-transform hover:scale-110
                           ${c.toLowerCase() === String(current).toLowerCase() ? 'ring-4 ring-white/40 scale-110' : 'ring-1 ring-border'}"
                    style="background:${this._escape(c)};"
                    title="${this._escape(c)}"></button>
          `).join('')}
        </div>
        <div class="flex justify-end gap-2">
          <button id="thomas-color-cancel" type="button"
                  class="px-3 py-1.5 rounded-lg text-xs text-text-muted hover:bg-bg transition-colors">
            Fermer
          </button>
        </div>
      </div>`;
    document.body.appendChild(overlay);

    const close = () => overlay.remove();
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
    overlay.querySelector('#thomas-color-cancel').onclick = close;
    overlay.querySelectorAll('button[data-color]').forEach(btn => {
      btn.addEventListener('click', async () => {
        const color = btn.getAttribute('data-color');
        try {
          const r = await App.api.messages_set_color({ color });
          if (r && r.ok) {
            this.myColor = r.color || color;
            // Re-rendu de la conversation avec la nouvelle couleur
            if (this.cachedMessages.length) this.renderMessages(this.cachedMessages);
          }
        } catch (e) {}
        close();
      });
    });
  },

  notifyTyping() {
    // Throttle : un appel set_typing(true) toutes les 2s max
    const now = Date.now();
    if (now - this.lastTypingPing > 2000) {
      this.lastTypingPing = now;
      try { App.api.messages_set_typing({ active: true }); } catch(e){}
    }
    // Auto-stop après 5s d'inactivité
    if (this.typingIdleTimeout) clearTimeout(this.typingIdleTimeout);
    this.typingIdleTimeout = setTimeout(() => {
      try { App.api.messages_set_typing({ active: false }); } catch(e){}
    }, 5000);
  },

  async refreshPeerTyping() {
    if (typeof App === 'undefined' || !App.api) return;
    try {
      const res = await App.api.messages_peer_typing();
      const typing = res && res.ok && res.typing;
      const el = document.getElementById('thomas-typing');
      if (el) el.classList.toggle('hidden', !typing);
    } catch (e) {}
  },
};

// Init au DOMContentLoaded (l'objet App est initialisé en premier dans app.js)
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => Thomas.init());
} else {
  Thomas.init();
}
