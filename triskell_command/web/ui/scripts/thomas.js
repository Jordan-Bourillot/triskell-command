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
  // Participant virtuel : Claude poste dans le chat depuis le mode vocal
  // (Allo Claude). Couleur et nom hardcodés côté front — non éditables
  // par l'utilisateur, alignés avec auth.py (DEFAULT_CHAT_COLORS["claude"]).
  claudeUserId: 'claude',
  claudeColor: '#a855f7',
  claudeName: 'Allo Claude',
  cachedMessages: [],
  cachedById: {},             // {id → msg} pour résoudre les "répondre à"
  pendingAttachment: null,    // {url, name, type, size} entre upload et envoi
  pendingReplyTo: null,       // message auquel on est en train de répondre
  pendingEdit: null,          // message que l'on est en train de modifier
  // Enregistrement d'un message vocal (API MediaRecorder du navigateur)
  mediaRecorder: null,
  recordChunks: [],
  recordStream: null,
  recordTimerHandle: null,
  recordStartMs: 0,
  recordCancelled: false,
  recordMime: '',
  _recordExt: 'webm',
  isRecording: false,

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

    // Coller (Ctrl+V) : si le presse-papier contient une image, on la
    // traite comme une pièce jointe et on annule le paste texte. Sinon
    // (texte normal), on laisse le navigateur insérer le texte tout seul.
    input.addEventListener('paste', (e) => {
      const items = (e.clipboardData && e.clipboardData.items) || [];
      const imageFiles = [];
      for (const item of items) {
        if (item.kind === 'file' && item.type && item.type.startsWith('image/')) {
          const f = item.getAsFile();
          if (f) imageFiles.push(f);
        }
      }
      if (imageFiles.length === 0) {
        return;  // texte ou autre : comportement par défaut du textarea
      }
      e.preventDefault();
      // Renomme les images collées (qui s'appellent souvent "image.png" par
      // défaut) avec un timestamp pour éviter les conflits si on en colle
      // plusieurs à la suite.
      const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
      imageFiles.forEach((f, idx) => {
        const ext = (f.type.split('/')[1] || 'png').split('+')[0];
        const suffix = imageFiles.length > 1 ? `_${idx + 1}` : '';
        const renamed = new File([f], `pasted_${stamp}${suffix}.${ext}`, {
          type: f.type, lastModified: Date.now(),
        });
        this._uploadAttachment(renamed);
      });
    });

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

    // Bouton GIF : ouvre la modale de recherche Giphy
    const gifBtn = document.getElementById('thomas-gif-btn');
    if (gifBtn) gifBtn.addEventListener('click', () => this._openGifPicker());

    // Bouton emoji : ouvre le picker d'émojis à insérer dans le message
    const emojiBtn = document.getElementById('thomas-emoji-btn');
    if (emojiBtn) emojiBtn.addEventListener('click', () => this._openEmojiPicker(emojiBtn));

    // Micro : démarre l'enregistrement d'un message vocal. La barre
    // d'enregistrement (annuler / envoyer) prend la place du composer.
    const micBtn = document.getElementById('thomas-mic-btn');
    if (micBtn) micBtn.addEventListener('click', () => this._startRecording());
    const recCancelBtn = document.getElementById('thomas-rec-cancel');
    if (recCancelBtn) recCancelBtn.addEventListener('click', () => this._cancelRecording());
    const recSendBtn = document.getElementById('thomas-rec-send');
    if (recSendBtn) recSendBtn.addEventListener('click', () => this._stopRecordingAndSend());

    // Lightbox : clic sur fond ou bouton × ferme
    const lightbox = document.getElementById('thomas-lightbox');
    const lightboxClose = document.getElementById('thomas-lightbox-close');
    if (lightbox) {
      lightbox.addEventListener('click', (e) => {
        if (e.target === lightbox) this._closeLightbox();
      });
    }
    if (lightboxClose) lightboxClose.addEventListener('click', () => this._closeLightbox());

    // Bouton "retour" du téléphone (ou geste de retour PWA) : ferme le chat
    // au lieu de quitter l'application. À l'ouverture on pushe une entrée
    // d'historique, à la fermeture on la pop (ou popstate la consomme).
    window.addEventListener('popstate', () => {
      if (this.open) this._teardown();
    });

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
        // Enregistrement vocal en cours : Échap l'annule (sans fermer le chat).
        if (this.isRecording) {
          this._cancelRecording();
          return;
        }
        // Modification ou aperçu "répondre à" en cours : on annule
        // sans fermer le chat.
        if (this.open && this.pendingEdit) {
          this._clearEditMode();
          return;
        }
        if (this.open && this.pendingReplyTo) {
          this._clearReplyTo();
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
      const unread = await this.pollUnread();
      // App ouverte mais chat fermé : si j'ai reçu des messages, je préviens
      // l'expéditeur qu'ils sont arrivés sur mon poste → statut « distribué ».
      // (Un message non distribué est forcément non lu, donc inutile d'appeler
      // si je n'ai aucun non-lu.)
      if (unread > 0) {
        try { await App.api.messages_mark_delivered(); } catch (e) {}
      }
    }
  },

  async pollUnread() {
    if (typeof App === 'undefined' || !App.api) return 0;
    try {
      const res = await App.api.messages_count_unread();
      const n = res && res.ok ? (res.count || 0) : 0;
      this.updateBadge(n);
      return n;
    } catch (e) { return 0; }
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
    if (this.open) return;
    const dlg = document.getElementById('thomas-dialog');
    dlg.classList.remove('hidden');
    dlg.classList.add('flex');
    this.open = true;
    // Pousse une entrée d'historique : sur mobile/PWA, le bouton "retour"
    // ferme alors le chat au lieu de quitter l'application.
    try {
      if (!history.state || !history.state.thomasOpen) {
        history.pushState({ thomasOpen: true }, '');
      }
    } catch (e) {}
    await this.refreshMessages();
    try { await App.api.messages_mark_read(); } catch(e){}
    this.updateBadge(0);
    document.getElementById('thomas-input').focus();
    this.startPolling();
  },

  // Fermeture déclenchée par l'utilisateur (croix, clic sur fond, Escape).
  // On préfère passer par history.back() pour rester en phase avec la pile
  // d'historique — popstate consommera et appellera _teardown.
  closeDialog() {
    if (!this.open) return;
    if (history.state && history.state.thomasOpen) {
      history.back();
    } else {
      this._teardown();
    }
  },

  // Vraie fermeture (UI). Appelée soit par closeDialog → history.back → popstate,
  // soit directement par popstate quand l'utilisateur tape "retour".
  _teardown() {
    if (!this.open) return;
    // Si on ferme le chat en plein enregistrement, on coupe le micro.
    if (this.isRecording) this._cancelRecording();
    const dlg = document.getElementById('thomas-dialog');
    dlg.classList.add('hidden');
    dlg.classList.remove('flex');
    this.open = false;
    if (this.typingIdleTimeout) {
      clearTimeout(this.typingIdleTimeout);
      this.typingIdleTimeout = null;
    }
    try { App.api.messages_set_typing({ active: false }); } catch(e){}
    this._clearReplyTo();
    this._clearEditMode();
    this.startPolling();
  },

  async refreshMessages() {
    if (typeof App === 'undefined' || !App.api) return;
    try {
      const res = await App.api.messages_list({ limit: 100 });
      const msgs = (res && res.ok ? res.messages : []) || [];
      // Optim : on évite de re-render si rien n'a changé (même nb de
      // messages, mêmes IDs, mêmes réactions, mêmes éditions). Sinon
      // le 1er affichage resterait vide quand cache + msgs sont vides
      // au boot, donc on re-rend toujours au moins une fois.
      const el = document.getElementById('thomas-messages');
      const sigA = this._messagesSignature(this.cachedMessages);
      const sigB = this._messagesSignature(msgs);
      const alreadyRendered = el && el.innerHTML.trim().length > 0;
      if (sigA !== sigB || !alreadyRendered) {
        this.cachedMessages = msgs;
        this.renderMessages(msgs);
      }
      // Chat ouvert : tout message reçu encore non lu passe « lu »
      // immédiatement — sinon, en laissant le chat ouvert, l'expéditeur
      // verrait « distribué » alors qu'on a le message sous les yeux.
      if (this.open && this.myUserId) {
        const hasUnreadIncoming = msgs.some(
          m => m && m.recipient_id === this.myUserId && !m.read_at);
        if (hasUnreadIncoming) {
          try { await App.api.messages_mark_read(); } catch (e) {}
          this.updateBadge(0);
        }
      }
    } catch (e) { /* silencieux */ }
  },

  /** Signature légère utilisée pour détecter qu'un message a bougé
   *  (nouveau, édité, supprimé, ou réactions changées) — sans hasher
   *  tout le body. */
  _messagesSignature(arr) {
    if (!arr || !arr.length) return '0';
    const parts = [String(arr.length)];
    for (const m of arr) {
      parts.push(`${m.id}:${(m.reactions || []).length}:${m.edited_at || ''}:${m.deleted_at || ''}:${m.read_at || ''}:${m.delivered_at || ''}`);
    }
    return parts.join('|');
  },

  renderMessages(msgs) {
    const el = document.getElementById('thomas-messages');
    if (!el) return;

    // Index par id : sert à résoudre `reply_to_id` lors du rendu et à
    // retrouver l'original quand on clique sur une citation.
    this.cachedById = {};
    for (const m of msgs) {
      if (m && m.id) this.cachedById[m.id] = m;
    }

    const html = msgs.map(m => {
      const isFromMe = this._isFromMe(m);
      const isFromClaude = m.sender_id === this.claudeUserId;
      const isDeleted = !!m.deleted_at;
      const align = isFromMe ? 'justify-end' : 'justify-start';
      // Couleur de fond = couleur perso de l'expéditeur. Claude (mode vocal)
      // a sa propre couleur distincte des deux humains. Pour un message
      // supprimé, on neutralise avec un fond grisé discret.
      const bgColor = isDeleted ? '#3a3a44'
        : (isFromMe ? this.myColor
        : (isFromClaude ? this.claudeColor : this.otherColor));
      const corner = isFromMe ? 'rounded-br-sm' : 'rounded-bl-sm';
      // Label "Allo Claude" au-dessus des bulles postées par Claude, pour
      // que les deux humains distinguent un message du chat normal d'un
      // message dicté via le mode vocal.
      const claudeLabelHtml = isFromClaude
        ? `<div class="text-[10px] uppercase tracking-wider mb-0.5 opacity-80"
              style="color:${this._escape(this.claudeColor)};">${this._escape(this.claudeName)}</div>`
        : '';
      const time = this._fmtTime(m.created_at);
      // Si supprimé : on ignore body/attachment/reply/réactions et on
      // remplace par un placeholder italique.
      const bodyHtml = isDeleted
        ? `<div class="text-sm italic opacity-70">Message supprimé</div>`
        : (m.body
            ? `<div class="text-sm whitespace-pre-wrap break-words">${this._escape(m.body)}</div>`
            : '');
      const attachHtml = (!isDeleted && m.attachment_url)
        ? this._renderAttachment(m)
        : '';
      const quoteHtml = (!isDeleted && m.reply_to_id)
        ? this._renderQuotedParent(m.reply_to_id)
        : '';

      // Sur un message supprimé, on masque toutes les actions (répondre,
      // réagir, modifier, supprimer) — il n'y a plus rien à faire dessus.
      const replyBtn = isDeleted ? '' : `
        <button type="button" class="thomas-reply-btn" data-reply-id="${this._escape(m.id || '')}"
                title="Répondre" aria-label="Répondre à ce message">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
               stroke-linecap="round" stroke-linejoin="round">
            <polyline points="9 17 4 12 9 7"/>
            <path d="M20 18v-2a4 4 0 0 0-4-4H4"/>
          </svg>
        </button>`;

      const reactBtn = isDeleted ? '' : `
        <button type="button" class="thomas-react-btn" data-react-id="${this._escape(m.id || '')}"
                title="Réagir" aria-label="Réagir à ce message">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
               stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="10"/>
            <path d="M8 14s1.5 2 4 2 4-2 4-2"/>
            <line x1="9" y1="9" x2="9.01" y2="9"/>
            <line x1="15" y1="9" x2="15.01" y2="9"/>
          </svg>
        </button>`;

      // Bouton "Modifier" uniquement sur mes propres messages avec du
      // texte. (Pas de sens de modifier une pièce jointe seule ni un
      // message supprimé.)
      const canEdit = isFromMe && m.body && !isDeleted;
      const editBtn = canEdit ? `
        <button type="button" class="thomas-edit-btn" data-edit-id="${this._escape(m.id || '')}"
                title="Modifier" aria-label="Modifier ce message">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
               stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 20h9"/>
            <path d="M16.5 3.5a2.121 2.121 0 113 3L7 19l-4 1 1-4L16.5 3.5z"/>
          </svg>
        </button>` : '';

      // Bouton "Supprimer" — uniquement sur mes propres messages encore
      // actifs (un message supprimé ne propose plus la corbeille).
      const canDelete = isFromMe && !isDeleted;
      const deleteBtn = canDelete ? `
        <button type="button" class="thomas-delete-btn" data-delete-id="${this._escape(m.id || '')}"
                title="Supprimer" aria-label="Supprimer ce message">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
               stroke-linecap="round" stroke-linejoin="round">
            <polyline points="3 6 5 6 21 6"/>
            <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>
            <path d="M10 11v6M14 11v6"/>
            <path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/>
          </svg>
        </button>` : '';

      // Marque "(modifié)" affichée à côté de l'heure pour les messages
      // édités — mais pas s'ils sont supprimés.
      const editedTag = (m.edited_at && !isDeleted)
        ? `<span class="opacity-70" title="Modifié le ${this._escape(this._fmtTime(m.edited_at))}"> · modifié</span>`
        : '';

      // Pastilles de réactions rendues sous la bulle (groupées par emoji)
      // — masquées pour un message supprimé.
      const reactionsHtml = isDeleted ? '' : this._renderReactionChips(m);

      // Les boutons d'action (corbeille, modifier, réagir, répondre)
      // sont placés SOUS la bulle plutôt qu'à côté — comme ça la bulle
      // peut prendre toute la largeur disponible. Ils apparaissent au
      // survol de la rangée.
      const actionsHtml = isFromMe
        ? `<div class="thomas-actions">${deleteBtn}${editBtn}${reactBtn}${replyBtn}</div>`
        : `<div class="thomas-actions">${reactBtn}${replyBtn}</div>`;

      const wrapClass = isFromMe
        ? 'thomas-bubble-wrap thomas-bubble-wrap-mine'
        : 'thomas-bubble-wrap thomas-bubble-wrap-theirs';

      // Coches d'état (façon WhatsApp), uniquement sous MES bulles humaines
      // non supprimées : envoyé / distribué / lu.
      const statusTicks = (isFromMe && !isFromClaude && !isDeleted)
        ? this._renderStatusTicks(m) : '';

      const bubble = `
        <div class="${wrapClass}">
          ${claudeLabelHtml}
          <div class="max-w-[96%] sm:max-w-[94%] px-3 py-2 rounded-2xl ${corner} text-white"
               data-msg-id="${this._escape(m.id || '')}"
               style="background:${this._escape(bgColor)};">
            ${quoteHtml}
            ${attachHtml}
            ${bodyHtml}
            <div class="thomas-meta mt-1">
              <span class="text-[10px] opacity-70">${time}${editedTag}</span>${statusTicks}
            </div>
          </div>
          ${actionsHtml}
          ${reactionsHtml}
        </div>`;

      return `<div class="flex ${align} items-start thomas-msg-row">${bubble}</div>`;
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

    // Bind les boutons "Répondre" de chaque bulle
    el.querySelectorAll('.thomas-reply-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const id = btn.getAttribute('data-reply-id');
        const msg = this.cachedById[id];
        if (msg) this._setReplyTo(msg);
      });
    });

    // Bind les boutons "Modifier" sur mes messages
    el.querySelectorAll('.thomas-edit-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const id = btn.getAttribute('data-edit-id');
        const msg = this.cachedById[id];
        if (msg) this._setEditMode(msg);
      });
    });

    // Bind les boutons "Réagir" (smiley) → ouvre le picker emoji
    el.querySelectorAll('.thomas-react-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const id = btn.getAttribute('data-react-id');
        if (id) this._openReactionPicker(id, btn);
      });
    });

    // Bind les pastilles de réactions sous chaque bulle → toggle
    el.querySelectorAll('.thomas-reaction-chip').forEach(chip => {
      chip.addEventListener('click', (e) => {
        e.stopPropagation();
        const id = chip.getAttribute('data-msg-id');
        const emoji = chip.getAttribute('data-emoji');
        if (id && emoji) this._toggleReaction(id, emoji);
      });
    });

    // Bind les boutons "Supprimer" (corbeille) sur mes messages
    el.querySelectorAll('.thomas-delete-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const id = btn.getAttribute('data-delete-id');
        if (id) this._deleteMessage(id);
      });
    });

    // Bind les citations cliquables → scroll vers l'original
    el.querySelectorAll('[data-quote-target]').forEach(quote => {
      quote.addEventListener('click', (e) => {
        e.stopPropagation();
        this._scrollToMessage(quote.getAttribute('data-quote-target'));
      });
    });

    // Scroll en bas
    el.scrollTop = el.scrollHeight;
  },

  /** Rendu de la citation affichée en haut d'une bulle qui est une réponse. */
  _renderQuotedParent(parentId) {
    const parent = this.cachedById[parentId];
    let authorName, excerpt, accent, thumbHtml = '';
    if (parent) {
      const fromMe = this._isFromMe(parent);
      accent = fromMe ? this.myColor : this.otherColor;
      authorName = fromMe ? 'Toi' : (
        document.getElementById('thomas-dialog-name')?.textContent || 'Lui'
      );
      // Si le message d'origine a été supprimé entre-temps, on ne
      // restitue pas son contenu — on indique juste qu'il est parti.
      if (parent.deleted_at) {
        excerpt = 'Message supprimé';
      } else {
        excerpt = this._messageExcerpt(parent);
        // Aperçu image (façon WhatsApp) : si le message cité est une photo,
        // on montre une vignette à droite, pas seulement le texte "Photo".
        thumbHtml = this._quoteThumb(parent);
      }
    } else {
      // Message parent hors de la fenêtre chargée (>100 messages d'écart).
      accent = 'rgba(255,255,255,0.4)';
      authorName = '…';
      excerpt = 'Message original';
    }
    return `
      <div class="thomas-quote ${thumbHtml ? 'has-thumb' : ''}" data-quote-target="${this._escape(parentId)}"
           style="border-left-color:${this._escape(accent)};">
        <div class="thomas-quote-text">
          <div class="thomas-quote-author">${this._escape(authorName)}</div>
          <div class="thomas-quote-body">${this._escape(excerpt)}</div>
        </div>
        ${thumbHtml}
      </div>`;
  },

  /** Vignette de l'image d'un message cité (façon WhatsApp). Renvoie une
   *  chaîne vide si le message cité n'est pas une photo. On charge l'image
   *  d'origine et le CSS la réduit en petit carré. */
  _quoteThumb(msg) {
    if (!msg || !msg.attachment_url) return '';
    const type = String(msg.attachment_type || '').toLowerCase();
    if (!type.startsWith('image/')) return '';
    const url = this._escape(msg.attachment_url);
    return `<img class="thomas-quote-thumb" src="${url}" alt="" aria-hidden="true"/>`;
  },

  /** Confirme puis supprime (soft) un message à moi. */
  async _deleteMessage(messageId) {
    if (typeof App === 'undefined' || !App.api) return;
    const ok = window.confirm('Supprimer ce message ? Cette action est définitive.');
    if (!ok) return;
    try {
      const res = await App.api.messages_delete({ id: messageId });
      if (res && res.ok) {
        // Si on était en train de modifier/répondre à ce même message,
        // on quitte ces modes (ils n'ont plus de sens).
        if (this.pendingEdit && this.pendingEdit.id === messageId) this._clearEditMode();
        if (this.pendingReplyTo && this.pendingReplyTo.id === messageId) this._clearReplyTo();
        // Force un re-render
        this.cachedMessages = [];
        await this.refreshMessages();
      } else {
        console.warn('messages_delete:', res);
      }
    } catch (e) {
      console.warn('deleteMessage:', e);
    }
  },

  /** Texte court d'un message pour l'aperçu (citation, banner répondre). */
  _messageExcerpt(msg, max = 80) {
    if (!msg) return '';
    let txt = (msg.body || '').trim();
    if (!txt && msg.attachment_url) {
      const t = String(msg.attachment_type || '').toLowerCase();
      txt = t.startsWith('image/') ? '📎 Photo'
          : t.startsWith('audio/') ? '🎤 Message vocal'
          : '📎 Fichier';
    }
    if (txt.length > max) txt = txt.slice(0, max - 1) + '…';
    return txt;
  },

  /** Scroll vers une bulle existante + petit flash visuel. */
  _scrollToMessage(id) {
    const el = document.querySelector(`[data-msg-id="${CSS.escape(id)}"]`);
    if (!el) return;
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    el.classList.remove('thomas-msg-flash');
    void el.offsetWidth;  // force reflow pour relancer l'animation
    el.classList.add('thomas-msg-flash');
  },

  _setReplyTo(msg) {
    // "Répondre à" et "modifier" sont mutuellement exclusifs : si on
    // commence à répondre, on quitte le mode édition (et inversement).
    if (this.pendingEdit) this._clearEditMode();
    this.pendingReplyTo = msg;
    this._renderReplyPreview();
    const input = document.getElementById('thomas-input');
    if (input) input.focus();
  },

  _clearReplyTo() {
    this.pendingReplyTo = null;
    const el = document.getElementById('thomas-reply-preview');
    if (el) {
      el.classList.add('hidden');
      el.innerHTML = '';
    }
  },

  _renderReplyPreview() {
    const el = document.getElementById('thomas-reply-preview');
    if (!el || !this.pendingReplyTo) return;
    const m = this.pendingReplyTo;
    const fromMe = this._isFromMe(m);
    const accent = fromMe ? this.myColor : this.otherColor;
    const author = fromMe ? 'toi-même' : (
      document.getElementById('thomas-dialog-name')?.textContent || 'lui'
    );
    el.classList.remove('hidden');
    el.innerHTML = `
      <div class="thomas-reply-banner" style="border-left-color:${this._escape(accent)};">
        <svg class="w-4 h-4 shrink-0 text-text-muted" viewBox="0 0 24 24" fill="none"
             stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="9 17 4 12 9 7"/>
          <path d="M20 18v-2a4 4 0 0 0-4-4H4"/>
        </svg>
        <div class="flex-1 min-w-0">
          <div class="text-[11px] font-semibold text-text">Réponse à ${this._escape(author)}</div>
          <div class="text-xs text-text-muted truncate">${this._escape(this._messageExcerpt(m, 120))}</div>
        </div>
        ${this._quoteThumb(m)}
        <button id="thomas-reply-cancel" type="button"
                class="w-7 h-7 rounded-full text-text-muted hover:text-danger hover:bg-bg
                       transition-colors flex items-center justify-center text-lg leading-none">×</button>
      </div>`;
    const cancel = document.getElementById('thomas-reply-cancel');
    if (cancel) cancel.addEventListener('click', () => this._clearReplyTo());
  },

  _setEditMode(msg) {
    // Mutuellement exclusif avec "répondre à".
    if (this.pendingReplyTo) this._clearReplyTo();
    this.pendingEdit = msg;
    const input = document.getElementById('thomas-input');
    if (input) {
      input.value = msg.body || '';
      input.focus();
      // Place le curseur en fin de texte (plus naturel pour modifier).
      try { input.setSelectionRange(input.value.length, input.value.length); } catch (e) {}
    }
    this._renderEditPreview();
  },

  _clearEditMode() {
    const wasEditing = !!this.pendingEdit;
    this.pendingEdit = null;
    const el = document.getElementById('thomas-edit-preview');
    if (el) {
      el.classList.add('hidden');
      el.innerHTML = '';
    }
    // Si on annule sans sauvegarder, on vide le composer (sinon le texte
    // de l'ancien message resterait coincé dans le champ — déroutant).
    if (wasEditing) {
      const input = document.getElementById('thomas-input');
      if (input) input.value = '';
    }
  },

  _renderEditPreview() {
    const el = document.getElementById('thomas-edit-preview');
    if (!el || !this.pendingEdit) return;
    const m = this.pendingEdit;
    const accent = this.myColor;
    el.classList.remove('hidden');
    el.innerHTML = `
      <div class="thomas-reply-banner" style="border-left-color:${this._escape(accent)};">
        <svg class="w-4 h-4 shrink-0 text-text-muted" viewBox="0 0 24 24" fill="none"
             stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M12 20h9"/>
          <path d="M16.5 3.5a2.121 2.121 0 113 3L7 19l-4 1 1-4L16.5 3.5z"/>
        </svg>
        <div class="flex-1 min-w-0">
          <div class="text-[11px] font-semibold text-text">Modification du message</div>
          <div class="text-xs text-text-muted truncate">${this._escape(this._messageExcerpt(m, 120))}</div>
        </div>
        <button id="thomas-edit-cancel" type="button"
                class="w-7 h-7 rounded-full text-text-muted hover:text-danger hover:bg-bg
                       transition-colors flex items-center justify-center text-lg leading-none"
                title="Annuler la modification (Échap)">×</button>
      </div>`;
    const cancel = document.getElementById('thomas-edit-cancel');
    if (cancel) cancel.addEventListener('click', () => this._clearEditMode());
  },

  // ───────────────────────── Réactions emoji ─────────────────────────
  /** Emojis proposés dans le picker rapide. Couvre les usages courants
   *  (cœur, like, rire, surprise, tristesse, merci, feu, validé). */
  _quickEmojis: ['❤️', '👍', '😂', '😮', '😢', '🙏', '🔥', '✅'],

  /** Rendu des pastilles de réactions sous une bulle. Groupe par emoji,
   *  affiche le compteur et met en évidence celles où je suis dedans. */
  _renderReactionChips(m) {
    const list = Array.isArray(m.reactions) ? m.reactions : [];
    if (!list.length) return '';
    const byEmoji = {};
    for (const r of list) {
      if (!r || !r.emoji) continue;
      if (!byEmoji[r.emoji]) byEmoji[r.emoji] = { count: 0, mine: false };
      byEmoji[r.emoji].count += 1;
      if (r.user_id === this.myUserId) byEmoji[r.emoji].mine = true;
    }
    const chips = Object.keys(byEmoji).map(emoji => {
      const { count, mine } = byEmoji[emoji];
      return `
        <button type="button" class="thomas-reaction-chip ${mine ? 'is-mine' : ''}"
                data-msg-id="${this._escape(m.id || '')}"
                data-emoji="${this._escape(emoji)}"
                title="${mine ? 'Retirer ta réaction' : 'Ajouter ta réaction'}">
          <span class="thomas-reaction-emoji">${this._escape(emoji)}</span>
          <span class="thomas-reaction-count">${count}</span>
        </button>`;
    }).join('');
    return `<div class="thomas-reactions">${chips}</div>`;
  },

  /** Ouvre un petit picker emoji ancré sur le bouton "Réagir". */
  _openReactionPicker(messageId, anchorEl) {
    // Si déjà ouvert, on referme (toggle).
    const existing = document.getElementById('thomas-reaction-picker');
    if (existing) {
      existing.remove();
      return;
    }
    const picker = document.createElement('div');
    picker.id = 'thomas-reaction-picker';
    picker.className = 'thomas-reaction-picker';
    picker.innerHTML = this._quickEmojis.map(e => `
      <button type="button" class="thomas-reaction-pick" data-emoji="${this._escape(e)}"
              aria-label="Réagir avec ${this._escape(e)}">${this._escape(e)}</button>
    `).join('');
    document.body.appendChild(picker);

    // Positionnement : au-dessus du bouton si possible, sinon en-dessous.
    const rect = anchorEl.getBoundingClientRect();
    const pickRect = picker.getBoundingClientRect();
    const margin = 6;
    let top = rect.top - pickRect.height - margin;
    if (top < 8) top = rect.bottom + margin;
    let left = rect.left + (rect.width / 2) - (pickRect.width / 2);
    left = Math.max(8, Math.min(left, window.innerWidth - pickRect.width - 8));
    picker.style.top  = `${top}px`;
    picker.style.left = `${left}px`;

    const close = () => {
      picker.remove();
      document.removeEventListener('click', onDocClick, true);
      window.removeEventListener('keydown', onEsc, true);
    };
    const onDocClick = (e) => {
      if (!picker.contains(e.target)) close();
    };
    const onEsc = (e) => {
      if (e.key === 'Escape') { e.stopPropagation(); close(); }
    };
    // setTimeout pour ne pas attraper le clic qui vient d'ouvrir le picker.
    setTimeout(() => {
      document.addEventListener('click', onDocClick, true);
      window.addEventListener('keydown', onEsc, true);
    }, 0);

    picker.querySelectorAll('.thomas-reaction-pick').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        e.stopPropagation();
        const emoji = btn.getAttribute('data-emoji');
        close();
        if (emoji) await this._toggleReaction(messageId, emoji);
      });
    });
  },

  /** Appelle l'API toggle puis rafraîchit la liste. */
  async _toggleReaction(messageId, emoji) {
    if (typeof App === 'undefined' || !App.api) return;
    try {
      await App.api.messages_react({ id: messageId, emoji });
      // Force un re-render : on vide la signature pour bypasser le cache.
      this.cachedMessages = [];
      await this.refreshMessages();
    } catch (e) {
      console.warn('toggleReaction:', e);
    }
  },

  // ───────────────────────── Picker émoji (insertion message) ─────────────────────────
  /** Catégories d'émojis pour le picker (insertion dans le message en
   *  cours). Sélection volontairement courte pour rester lisible. */
  _emojiCategories: [
    { name: 'Smileys', emojis: ['😀','😃','😄','😁','😆','😅','🤣','😂','🙂','😉','😊','😇','🥰','😍','🤩','😘','😗','😚','😋','😜','🤪','😎','🤓','🥳','🤗','🤔','😐','😏','😒','🙄','😴','🤤','🥱','😪','😌','😔','😢','😭','😤','😠','😡','🤯','😱','😨','😰','😥','🤐','🤫','🤥','🤒','🤧','🥵','🥶'] },
    { name: 'Gestes', emojis: ['👍','👎','👌','🤌','🤏','✌️','🤞','🤟','🤘','🤙','👈','👉','👆','👇','☝️','✋','🤚','🖐️','🖖','👋','🤝','🙏','💪','🫶','🤲','👏','🙌','👐','🫰'] },
    { name: 'Cœurs', emojis: ['❤️','🧡','💛','💚','💙','💜','🖤','🤍','🤎','💔','❣️','💕','💞','💓','💗','💖','💘','💝','💟','💌'] },
    { name: 'Fête', emojis: ['🎉','🎊','🥳','🎂','🍰','🎈','🎁','🎀','🪅','🎆','🎇','✨','🌟','⭐','💫','🔥','💥','🏆','🥇','🎯','🎊'] },
    { name: 'Objets', emojis: ['💻','📱','⌨️','🖥️','🖱️','💾','📷','🎧','🔋','💡','🔧','🛠️','📌','📎','✂️','🔑','🔒','💰','💳','📅','📆','✅','❌','⚠️','❓','❗','💯','🆗','🆕'] },
    { name: 'Café', emojis: ['☕','🍵','🍺','🍻','🥂','🍷','🍸','🍹','🥤','🍔','🍟','🍕','🌭','🥪','🌮','🍣','🍜','🍱','🥗','🍩','🍪','🍫','🍿'] },
  ],

  _openEmojiPicker(anchorEl) {
    // Toggle : si déjà ouvert, on referme.
    const existing = document.getElementById('thomas-emoji-popover');
    if (existing) { this._closeEmojiPicker(); return; }

    const pop = document.createElement('div');
    pop.id = 'thomas-emoji-popover';
    pop.className = 'thomas-emoji-popover';
    const cats = this._emojiCategories;
    const tabs = cats.map((c, i) => `
      <button type="button" class="thomas-emoji-tab ${i === 0 ? 'is-active' : ''}"
              data-cat-index="${i}">${this._escape(c.name)}</button>`).join('');
    const grid = cats.map((c, i) => `
      <div class="thomas-emoji-grid ${i === 0 ? '' : 'hidden'}" data-cat-pane="${i}">
        ${c.emojis.map(e => `
          <button type="button" class="thomas-emoji-cell"
                  data-emoji="${this._escape(e)}"
                  aria-label="Insérer ${this._escape(e)}">${this._escape(e)}</button>`).join('')}
      </div>`).join('');
    pop.innerHTML = `
      <div class="thomas-emoji-tabs">${tabs}</div>
      <div class="thomas-emoji-panes">${grid}</div>`;
    document.body.appendChild(pop);

    // Positionnement : au-dessus du bouton (panel plus grand que reaction picker).
    const rect = anchorEl.getBoundingClientRect();
    const popRect = pop.getBoundingClientRect();
    const margin = 8;
    let top = rect.top - popRect.height - margin;
    if (top < 8) top = rect.bottom + margin;
    let left = rect.left + (rect.width / 2) - (popRect.width / 2);
    left = Math.max(8, Math.min(left, window.innerWidth - popRect.width - 8));
    pop.style.top = `${top}px`;
    pop.style.left = `${left}px`;

    const close = () => {
      pop.remove();
      document.removeEventListener('click', onDocClick, true);
      window.removeEventListener('keydown', onEsc, true);
    };
    const onDocClick = (e) => {
      if (!pop.contains(e.target) && e.target !== anchorEl) close();
    };
    const onEsc = (e) => {
      if (e.key === 'Escape') { e.stopPropagation(); close(); }
    };
    setTimeout(() => {
      document.addEventListener('click', onDocClick, true);
      window.addEventListener('keydown', onEsc, true);
    }, 0);

    // Bascule entre catégories
    pop.querySelectorAll('.thomas-emoji-tab').forEach(tab => {
      tab.addEventListener('click', (e) => {
        e.stopPropagation();
        const idx = tab.getAttribute('data-cat-index');
        pop.querySelectorAll('.thomas-emoji-tab').forEach(t =>
          t.classList.toggle('is-active', t === tab));
        pop.querySelectorAll('[data-cat-pane]').forEach(p =>
          p.classList.toggle('hidden', p.getAttribute('data-cat-pane') !== idx));
      });
    });

    // Clic sur un émoji → insertion dans l'input
    pop.querySelectorAll('.thomas-emoji-cell').forEach(cell => {
      cell.addEventListener('click', (e) => {
        e.stopPropagation();
        this._insertEmoji(cell.getAttribute('data-emoji') || '');
      });
    });
  },

  _closeEmojiPicker() {
    const pop = document.getElementById('thomas-emoji-popover');
    if (pop) pop.remove();
  },

  /** Insère l'émoji à la position du curseur (ou en fin de texte). */
  _insertEmoji(emoji) {
    const input = document.getElementById('thomas-input');
    if (!input || !emoji) return;
    const start = (typeof input.selectionStart === 'number') ? input.selectionStart : input.value.length;
    const end   = (typeof input.selectionEnd === 'number')   ? input.selectionEnd   : input.value.length;
    const before = input.value.slice(0, start);
    const after  = input.value.slice(end);
    input.value = before + emoji + after;
    const newPos = start + emoji.length;
    try { input.setSelectionRange(newPos, newPos); } catch (e) {}
    input.focus();
    this.notifyTyping();
  },

  // ───────────────────────── Picker GIF (Giphy) ─────────────────────────
  /** La recherche passe par /api/gif_search côté serveur — la clé Giphy
   *  est stockée dans la variable d'env GIPHY_API_KEY (Coolify) et ne
   *  quitte jamais le serveur. Plus de clé en dur dans le code. */
  _gifSearchTimer: null,

  _openGifPicker() {
    // Toggle : si déjà ouverte, on referme.
    const existing = document.getElementById('thomas-gif-overlay');
    if (existing) { this._closeGifPicker(); return; }

    const overlay = document.createElement('div');
    overlay.id = 'thomas-gif-overlay';
    overlay.className = 'thomas-gif-overlay';
    overlay.innerHTML = `
      <div class="thomas-gif-modal" role="dialog" aria-label="Choisir un GIF">
        <div class="thomas-gif-header">
          <input id="thomas-gif-search" type="text" autocomplete="off"
                 placeholder="Rechercher un GIF…"
                 class="thomas-gif-search-input"/>
          <button id="thomas-gif-close" type="button"
                  class="thomas-gif-close-btn" aria-label="Fermer">×</button>
        </div>
        <div id="thomas-gif-grid" class="thomas-gif-grid"></div>
        <div class="thomas-gif-attrib">Powered by GIPHY</div>
      </div>`;
    document.body.appendChild(overlay);

    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) this._closeGifPicker();
    });
    overlay.querySelector('#thomas-gif-close')
      .addEventListener('click', () => this._closeGifPicker());

    const search = overlay.querySelector('#thomas-gif-search');
    search.addEventListener('input', () => {
      const q = search.value.trim();
      if (this._gifSearchTimer) clearTimeout(this._gifSearchTimer);
      this._gifSearchTimer = setTimeout(() => this._searchGifs(q), 280);
    });
    search.focus();

    // Trending au démarrage
    this._searchGifs('');
  },

  _closeGifPicker() {
    if (this._gifSearchTimer) {
      clearTimeout(this._gifSearchTimer);
      this._gifSearchTimer = null;
    }
    const overlay = document.getElementById('thomas-gif-overlay');
    if (overlay) overlay.remove();
  },

  /** Charge les GIFs via le proxy serveur (qui détient la clé Giphy).
   *  Si query vide → trending. Sinon search. */
  async _searchGifs(query) {
    const grid = document.getElementById('thomas-gif-grid');
    if (!grid) return;
    grid.innerHTML = `<div class="thomas-gif-loading">Chargement…</div>`;

    if (typeof App === 'undefined' || !App.api) {
      grid.innerHTML = `<div class="thomas-gif-empty">Service indisponible.</div>`;
      return;
    }
    try {
      const res = await App.api.gif_search({ q: query, limit: 24 });
      if (!res || !res.ok) {
        const msg = (res && res.message) || 'Erreur de chargement.';
        grid.innerHTML = `<div class="thomas-gif-empty">${this._escape(msg)}</div>`;
        return;
      }
      const items = res.items || [];
      if (!items.length) {
        grid.innerHTML = `<div class="thomas-gif-empty">Aucun GIF trouvé.</div>`;
        return;
      }
      grid.innerHTML = items.map(g => `
        <button type="button" class="thomas-gif-thumb"
                data-gif-url="${this._escape(g.full_url || '')}"
                data-gif-name="${this._escape(g.title || g.id || 'gif')}">
          <img src="${this._escape(g.thumb_url || '')}"
               alt="${this._escape(g.title || 'GIF')}"
               loading="lazy"/>
        </button>`).join('');

      grid.querySelectorAll('.thomas-gif-thumb').forEach(btn => {
        btn.addEventListener('click', () => {
          this._sendGif({
            url:  btn.getAttribute('data-gif-url'),
            name: btn.getAttribute('data-gif-name') + '.gif',
          });
        });
      });
    } catch (e) {
      console.warn('searchGifs:', e);
      grid.innerHTML = `<div class="thomas-gif-empty">Erreur de chargement.</div>`;
    }
  },

  /** Envoie un GIF en tant que pièce jointe externe (URL Giphy directe).
   *  Réutilise le flux d'envoi existant : on pose pendingAttachment puis
   *  on appelle send() — comme pour une image uploadée. */
  async _sendGif(gif) {
    if (!gif || !gif.url) return;
    this.pendingAttachment = {
      url:  gif.url,
      name: gif.name || 'gif',
      type: 'image/gif',
      size: 0,
    };
    this._closeGifPicker();
    await this.send();
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
    // Message vocal : petit lecteur audio intégré dans la bulle.
    if (type.startsWith('audio/')) {
      return `
        <div class="thomas-voice">
          <div class="thomas-voice-label">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/>
              <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
              <line x1="12" y1="19" x2="12" y2="23"/>
              <line x1="8" y1="23" x2="16" y2="23"/>
            </svg>
            Message vocal
          </div>
          <audio controls preload="metadata" src="${url}" class="thomas-voice-audio">
            Lecture impossible sur ce navigateur.
          </audio>
        </div>`;
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

  /** Coches d'état sous mes propres bulles, façon WhatsApp :
   *   - envoyé    : 1 coche claire (le message est parti)
   *   - distribué : 2 coches claires (arrivé sur le poste de l'autre)
   *   - lu        : 2 coches bleues (l'autre a ouvert le chat)
   *  `delivered_at` n'existe que si la migration 44 est appliquée ; sans
   *  elle, un message lu reste cohérent (2 coches bleues) et un non-lu
   *  affiche 1 coche — dégradation propre vers « envoyé / lu ». */
  _renderStatusTicks(m) {
    const read = !!m.read_at;
    const delivered = read || !!m.delivered_at;
    const stroke = 'stroke="currentColor" stroke-width="1.7" fill="none" ' +
                   'stroke-linecap="round" stroke-linejoin="round"';
    const svg = delivered
      ? `<svg viewBox="0 0 20 12" aria-hidden="true">
           <path d="M1 6.5 l3.5 3.5 L11 2" ${stroke}/>
           <path d="M7 6.5 l3.5 3.5 L17 2" ${stroke}/>
         </svg>`
      : `<svg viewBox="0 0 20 12" aria-hidden="true">
           <path d="M4 6.5 l3.5 3.5 L14 2" ${stroke}/>
         </svg>`;
    const label = read ? 'Lu' : (delivered ? 'Distribué' : 'Envoyé');
    return `<span class="thomas-ticks${read ? ' is-read' : ''}" title="${label}">${svg}</span>`;
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

    // Mode édition : on ne crée pas un nouveau message, on modifie celui
    // qui est en cours d'édition. Pas de pièce jointe à ajouter ici (on
    // n'édite que le texte, pas l'attachement existant).
    if (this.pendingEdit && this.pendingEdit.id) {
      if (!body) return;  // body vide : on n'autorise pas d'effacer en édition
      sendBtn.disabled = true;
      try {
        const res = await App.api.messages_edit({ id: this.pendingEdit.id, body });
        if (res && res.ok && res.message) {
          input.value = '';
          this._clearEditMode();
          await this.refreshMessages();
        } else {
          console.warn('messages_edit:', res);
        }
      } catch (e) {
        console.warn('edit:', e);
      } finally {
        sendBtn.disabled = false;
        input.focus();
      }
      return;
    }

    if (!body && !attachment) return;  // ni texte ni pj → rien à envoyer

    sendBtn.disabled = true;
    try {
      const payload = { body };
      if (attachment) payload.attachment = attachment;
      if (this.pendingReplyTo && this.pendingReplyTo.id) {
        payload.reply_to_id = this.pendingReplyTo.id;
      }
      const res = await App.api.messages_send(payload);
      if (res && res.ok && res.message) {
        // Cache mon user_id pour bien aligner les bulles
        this.myUserId = res.message.sender_id;
        input.value = '';
        this._clearPendingAttachment();
        this._clearReplyTo();
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
    const lowerType = String(a.type || '').toLowerCase();
    const isImg = lowerType.startsWith('image/');
    const isAudio = lowerType.startsWith('audio/');
    const thumb = isImg
      ? `<img src="${this._escape(a.url)}" alt=""
             class="w-12 h-12 object-cover rounded shrink-0"/>`
      : isAudio
      ? `<div class="w-12 h-12 rounded bg-bg flex items-center justify-center shrink-0">
           <svg class="w-5 h-5 text-text-muted" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
             <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/>
             <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
             <line x1="12" y1="19" x2="12" y2="23"/>
             <line x1="8" y1="23" x2="16" y2="23"/>
           </svg>
         </div>`
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

  // ───────────────────────── Messages vocaux ─────────────────────────
  /** Choisit un format audio supporté par le navigateur, avec l'extension
   *  de fichier qui va avec. Opus/WebM partout, sauf Safari/iOS → mp4. */
  _pickAudioMime() {
    const candidates = [
      { mime: 'audio/webm;codecs=opus', ext: 'webm' },
      { mime: 'audio/webm',             ext: 'webm' },
      { mime: 'audio/ogg;codecs=opus',  ext: 'ogg'  },
      { mime: 'audio/mp4',              ext: 'm4a'  },
    ];
    const MR = window.MediaRecorder;
    for (const c of candidates) {
      if (MR && typeof MR.isTypeSupported === 'function' && MR.isTypeSupported(c.mime)) {
        return c;
      }
    }
    return { mime: '', ext: 'webm' };
  },

  /** Démarre l'enregistrement : demande le micro, lance MediaRecorder et
   *  bascule l'interface sur la barre d'enregistrement. */
  async _startRecording() {
    if (this.isRecording) return;
    // Garde-fou : micro indisponible (vieux navigateur, ou page non sécurisée).
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !window.MediaRecorder) {
      window.alert("Ton navigateur ne permet pas d'enregistrer un message vocal.");
      return;
    }
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (e) {
      window.alert("Impossible d'accéder au micro. Autorise le micro dans ton navigateur pour envoyer un message vocal.");
      return;
    }
    const picked = this._pickAudioMime();
    this.recordMime = picked.mime;
    this._recordExt = picked.ext;
    this.recordStream = stream;
    this.recordChunks = [];
    this.recordCancelled = false;
    let rec;
    try {
      rec = picked.mime
        ? new MediaRecorder(stream, { mimeType: picked.mime })
        : new MediaRecorder(stream);
    } catch (e) {
      rec = new MediaRecorder(stream);  // fallback : format par défaut du navigateur
    }
    this.mediaRecorder = rec;
    rec.addEventListener('dataavailable', (e) => {
      if (e.data && e.data.size > 0) this.recordChunks.push(e.data);
    });
    rec.addEventListener('stop', () => this._onRecordStop());
    rec.start();
    this.isRecording = true;
    this._showRecordingUI();
  },

  _showRecordingUI() {
    const composer = document.getElementById('thomas-composer');
    const bar = document.getElementById('thomas-recording-bar');
    if (composer) composer.classList.add('hidden');
    if (bar) {
      bar.classList.remove('hidden');
      bar.classList.add('flex');
    }
    this.recordStartMs = Date.now();
    this._updateRecordTimer();
    if (this.recordTimerHandle) clearInterval(this.recordTimerHandle);
    this.recordTimerHandle = setInterval(() => this._updateRecordTimer(), 250);
  },

  _hideRecordingUI() {
    const composer = document.getElementById('thomas-composer');
    const bar = document.getElementById('thomas-recording-bar');
    if (bar) {
      bar.classList.add('hidden');
      bar.classList.remove('flex');
    }
    if (composer) composer.classList.remove('hidden');
    if (this.recordTimerHandle) {
      clearInterval(this.recordTimerHandle);
      this.recordTimerHandle = null;
    }
  },

  _updateRecordTimer() {
    const el = document.getElementById('thomas-rec-timer');
    if (!el) return;
    const secs = Math.max(0, Math.floor((Date.now() - this.recordStartMs) / 1000));
    const mm = Math.floor(secs / 60);
    const ss = String(secs % 60).padStart(2, '0');
    el.textContent = `${mm}:${ss}`;
  },

  /** Coupe le flux micro : libère le matériel et fait disparaître l'icône
   *  "enregistrement" de l'onglet du navigateur. */
  _releaseStream() {
    if (this.recordStream) {
      try { this.recordStream.getTracks().forEach(t => t.stop()); } catch (e) {}
      this.recordStream = null;
    }
  },

  /** Annule : on jette l'enregistrement, rien n'est envoyé. */
  _cancelRecording() {
    if (!this.isRecording) return;
    this.recordCancelled = true;
    this.isRecording = false;
    try {
      if (this.mediaRecorder && this.mediaRecorder.state !== 'inactive') this.mediaRecorder.stop();
    } catch (e) {}
    this._releaseStream();
    this._hideRecordingUI();
  },

  /** Stoppe l'enregistrement et déclenche l'envoi (via l'event "stop"). */
  _stopRecordingAndSend() {
    if (!this.isRecording) return;
    this.recordCancelled = false;
    this.isRecording = false;
    try {
      if (this.mediaRecorder && this.mediaRecorder.state !== 'inactive') this.mediaRecorder.stop();
    } catch (e) {
      this._releaseStream();
      this._hideRecordingUI();
    }
    // La suite (assemblage + upload + envoi) se fait dans _onRecordStop.
  },

  /** Appelé quand MediaRecorder a fini : assemble le son, l'upload comme
   *  une pièce jointe, puis envoie le message. */
  async _onRecordStop() {
    this._releaseStream();
    this._hideRecordingUI();
    const cancelled = this.recordCancelled;
    const chunks = this.recordChunks || [];
    this.recordChunks = [];
    if (cancelled || !chunks.length) return;
    const type = this.recordMime ? this.recordMime.split(';')[0] : 'audio/webm';
    const blob = new Blob(chunks, { type });
    if (!blob.size) return;
    const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
    const file = new File([blob], `message_vocal_${stamp}.${this._recordExt || 'webm'}`, {
      type, lastModified: Date.now(),
    });
    // Réutilise le flux des pièces jointes : upload → pendingAttachment → envoi.
    await this._uploadAttachment(file);
    if (this.pendingAttachment) {
      await this.send();
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
