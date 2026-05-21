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
  cachedMessages: [],

  init() {
    const fab = document.getElementById('thomas-fab');
    const dlg = document.getElementById('thomas-dialog');
    const closeBtn = document.getElementById('thomas-dialog-close');
    const input = document.getElementById('thomas-input');
    const sendBtn = document.getElementById('thomas-send');

    if (!fab || !dlg) return;

    fab.addEventListener('click', () => this.openDialog());
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

    // F11 pour ouvrir le chat
    window.addEventListener('keydown', (e) => {
      if (e.key === 'F11') {
        e.preventDefault();
        this.openDialog();
      }
      if (e.key === 'Escape' && this.open) {
        this.closeDialog();
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
    let tries = 0;
    while (tries < 240) {
      if (window.App && window.App.api && window.App.api.messages_other_user) break;
      await new Promise(r => setTimeout(r, 250));
      tries++;
    }
    if (!window.App || !window.App.api) {
      console.warn('Thomas: App.api pas encore disponible — réessai dans 10s');
      setTimeout(() => this.bootstrap(), 10000);
      return;
    }

    // Récupère mon user_id pour bien aligner les bulles
    try {
      const me = await App.api.messages_me();
      if (me && me.ok && me.user_id) this.myUserId = me.user_id;
    } catch (e) {}

    // Vérifie qu'il y a un autre user (Thomas) dans la base
    try {
      const res = await App.api.messages_other_user();
      const other = res && res.ok ? res.other : null;
      if (!other) {
        // Solo : on cache le FAB
        document.getElementById('thomas-fab').classList.add('hidden');
        return;
      }
      // Affiche le FAB et personnalise le nom
      document.getElementById('thomas-fab').classList.remove('hidden');
      const name = other.display_name || 'Thomas';
      document.getElementById('thomas-dialog-name').textContent = name;
      document.getElementById('thomas-dialog-avatar').textContent =
        (name[0] || 'T').toUpperCase();
      const fab = document.getElementById('thomas-fab');
      fab.title = `Chat avec ${name} · F11`;
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
    if (!window.App || !App.api) return;
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
    if (!window.App || !App.api) return;
    try {
      const res = await App.api.messages_list({ limit: 100 });
      const msgs = (res && res.ok ? res.messages : []) || [];
      // Évite re-render si pas de changement (compare par dernier id)
      const lastA = this.cachedMessages.length
        ? this.cachedMessages[this.cachedMessages.length - 1].id : null;
      const lastB = msgs.length ? msgs[msgs.length - 1].id : null;
      if (lastA === lastB && this.cachedMessages.length === msgs.length) return;
      this.cachedMessages = msgs;
      this.renderMessages(msgs);
    } catch (e) { /* silencieux */ }
  },

  renderMessages(msgs) {
    const el = document.getElementById('thomas-messages');
    if (!el) return;

    // Identifie "moi" : on déduit du premier message dont je suis sender
    // (sinon fallback : on met les sent à droite via une heuristique simple).
    // Idéalement App.api devrait exposer le user_id ; ici on regarde
    // simplement si "moi" est connu via une heuristique.
    if (!this.myUserId && msgs.length) {
      // On regarde le premier user qui apparaît comme sender — pas idéal,
      // mais on n'a pas mieux côté front. En pratique, l'API renvoie
      // sender/recipient et on alterne droit/gauche sur cette base.
    }

    const html = msgs.map(m => {
      // Heuristique : on regarde sender vs recipient. Si on a déjà identifié
      // le user qui a envoyé en premier dans la session courante, on inverse
      // selon. Sinon, on alterne droite/gauche basé sur sender_id stable.
      const isFromMe = this._isFromMe(m);
      const align = isFromMe ? 'justify-end' : 'justify-start';
      const bubble = isFromMe
        ? 'bg-accent text-white rounded-br-sm'
        : 'bg-surface-elevated text-text rounded-bl-sm';
      const time = this._fmtTime(m.created_at);
      const body = this._escape(m.body || '');
      return `
        <div class="flex ${align}">
          <div class="max-w-[75%] px-3 py-2 rounded-2xl ${bubble}">
            <div class="text-sm whitespace-pre-wrap break-words">${body}</div>
            <div class="text-[10px] opacity-70 mt-1 text-right">${time}</div>
          </div>
        </div>`;
    }).join('');

    el.innerHTML = html || `
      <div class="text-center text-text-muted text-xs py-8">
        Aucun message pour l'instant. Envoie le premier ! 👋
      </div>`;
    // Scroll en bas
    el.scrollTop = el.scrollHeight;
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
    if (!body) return;

    sendBtn.disabled = true;
    try {
      const res = await App.api.messages_send({ body });
      if (res && res.ok && res.message) {
        // Cache mon user_id pour bien aligner les bulles
        this.myUserId = res.message.sender_id;
        input.value = '';
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
    if (!window.App || !App.api) return;
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
