/* Le Copilote — volet de discussion écrit, ouvrable depuis TOUS les écrans.
 *
 * Étape 1 de la vision « copilote omniprésent » (10/06/2026) :
 *  - une seule présence : ce volet est la porte d’entrée de l’assistant
 *    (le bouton « Allô Claude » du Cockpit, Ctrl+Espace et la barre-guide
 *    mènent tous ici) ;
 *  - il répond MOT À MOT (route /api/copilot_stream, secours « bloc » via
 *    copilot_send pour les navigateurs qui ne savent pas streamer et le
 *    mode desktop) ;
 *  - le fil est PERSISTÉ côté serveur : on ferme, on rouvre, il est là ;
 *  - il AGIT (mêmes pouvoirs que le vocal : lancer une prospection,
 *    Auto-pilote, abandonner une mission, ouvrir un écran) ;
 *  - le mode vocal 📞 existant reste accessible d’ici, et ses tours sont
 *    reversés au fil écrit à la fin de l’appel : UNE seule conversation.
 *
 * Aucune dépendance dure : si quelque chose manque (App, Claude…), le
 * volet dégrade proprement. Il ne casse JAMAIS l’app.
 */

const Copilot = {
  _open: false,
  _busy: false,
  _loaded: false,
  _mounted: false,

  // ---------------------------------------------------------------- open/close
  open() {
    this._mount();
    const panel = document.getElementById('copilot-panel');
    if (!panel) return;
    this._open = true;
    panel.classList.add('cop-visible');
    this.setBadge(false);
    if (!this._loaded) {
      this._loadThread();
    } else {
      this._consumePendingAdvice();
    }
    // Focus différé : laisse l’animation d’ouverture se finir
    setTimeout(() => {
      const input = document.getElementById('copilot-input');
      if (input && window.matchMedia('(min-width: 641px)').matches) input.focus();
    }, 180);
  },

  close() {
    const panel = document.getElementById('copilot-panel');
    if (panel) panel.classList.remove('cop-visible');
    this._open = false;
    this._stopDictation();
  },

  toggle() {
    if (this._open) this.close();
    else this.open();
  },

  isOpen() { return this._open; },

  /** Pastille « le copilote a quelque chose pour toi » (veille proactive). */
  setBadge(on) {
    document.querySelectorAll('.copilot-badge-dot').forEach((d) => {
      d.classList.toggle('hidden', !on);
    });
  },

  // ---------------------------------------------------------------- fil
  async _loadThread() {
    const box = document.getElementById('copilot-messages');
    if (!box) return;
    box.innerHTML = '<div class="cop-loading">…</div>';
    let data = null;
    try {
      if (typeof App !== 'undefined' && App.api && App.api.copilot_thread) {
        data = await App.api.copilot_thread({});
      }
    } catch (e) { /* fil indisponible : on repart à zéro visuellement */ }
    box.innerHTML = '';
    const msgs = (data && data.ok && Array.isArray(data.messages)) ? data.messages : [];
    if (!msgs.length) {
      this._renderWelcome(box);
    } else {
      msgs.forEach((m) => this._appendBubble(m.role, m.content, { md: true }));
    }
    this._loaded = true;
    this._scrollDown(true);
    this._consumePendingAdvice();
  },

  _renderWelcome(box) {
    const name = (typeof App !== 'undefined' && App.currentUser
                  && App.currentUser.first_name) || 'toi';
    const el = document.createElement('div');
    el.className = 'cop-welcome';
    el.innerHTML = `
      <div class="cop-w-title">👋 Salut ${this._esc(name)} !</div>
      <div class="cop-w-body">
        Je suis ton copilote. Je vois ton app et ton business en direct,
        je réponds à tes questions, et je peux <b>agir pour toi</b>.
        On reprend toujours la discussion là où on l’a laissée.
      </div>
      <div class="cop-w-chips">
        <button class="cop-chip" data-q="Où en est ma prospection ?">Où en est ma prospection ?</button>
        <button class="cop-chip" data-q="Combien de réponses cette semaine ?">Combien de réponses cette semaine ?</button>
        <button class="cop-chip" data-q="Qu’est-ce que je devrais faire en priorité là ?">Je fais quoi en priorité ?</button>
      </div>`;
    box.appendChild(el);
    el.querySelectorAll('.cop-chip').forEach((b) => {
      b.onclick = () => this.send(b.dataset.q);
    });
  },

  /** Affiche (et consomme) le conseil laissé par la veille proactive. */
  _consumePendingAdvice() {
    if (typeof Claude === 'undefined' || !Claude.pendingAdvice) return;
    const adv = Claude.pendingAdvice;
    Claude.pendingAdvice = null;
    try { Claude.setAttention(false); } catch (e) {}
    // Un conseil sans contenu n’existe pas (anti carte vide).
    if (!adv || !adv.ok || (!adv.headline && !adv.advice)) return;
    const box = document.getElementById('copilot-messages');
    if (!box) return;
    const el = document.createElement('div');
    el.className = 'cop-msg cop-assistant cop-advice';
    el.innerHTML = `
      <div class="cop-advice-kicker">💡 Pendant ton absence</div>
      ${adv.headline ? `<div class="cop-advice-headline">${this._esc(adv.headline)}</div>` : ''}
      ${adv.advice ? `<div>${this._md(adv.advice)}</div>` : ''}
      ${adv.suggested_view ? `
        <button class="cop-advice-go" data-view="${this._esc(adv.suggested_view)}">
          ${this._esc(adv.suggested_action_label || 'Y aller')} →
        </button>` : ''}`;
    box.appendChild(el);
    const go = el.querySelector('.cop-advice-go');
    if (go) go.onclick = () => this._navigate(go.dataset.view);
    this._scrollDown(true);
  },

  // ---------------------------------------------------------------- envoi
  async send(text) {
    const input = document.getElementById('copilot-input');
    text = String(text != null ? text : (input ? input.value : '')).trim();
    if (!text || this._busy) return;
    this._busy = true;
    this._setComposerBusy(true);
    if (input) { input.value = ''; this._growInput(); }
    this._stopDictation();

    // Si l’écran d’accueil est encore là, on le retire (la discussion démarre)
    const wel = document.querySelector('#copilot-messages .cop-welcome');
    if (wel) wel.remove();

    this._appendBubble('user', text, { md: false });
    const bubble = this._appendBubble('assistant', '', { streaming: true });
    this._scrollDown(true);

    let finalEvt = null;
    let errorMsg = null;
    let gotAnything = false;

    try {
      const streamed = await this._streamInto(bubble, text, (evt) => {
        gotAnything = true;
        if (evt.type === 'done') finalEvt = evt;
        if (evt.type === 'error') errorMsg = evt.error || 'Erreur inconnue.';
      });
      if (!streamed && !gotAnything) {
        // Le flux n’a pas pu s’établir → chemin de secours en bloc
        const r = await this._sendBlocking(text);
        if (r && r.ok) finalEvt = { type: 'done', text: r.text, navigate: r.navigate,
                                    action_done: r.action_done, sent_to_thomas: r.sent_to_thomas };
        else errorMsg = (r && r.error) || 'Je n’ai pas réussi à répondre. Réessaie.';
      }
    } catch (e) {
      if (!gotAnything) {
        try {
          const r = await this._sendBlocking(text);
          if (r && r.ok) finalEvt = { type: 'done', text: r.text, navigate: r.navigate,
                                      action_done: r.action_done, sent_to_thomas: r.sent_to_thomas };
          else errorMsg = (r && r.error) || 'Je n’ai pas réussi à répondre. Réessaie.';
        } catch (e2) {
          errorMsg = 'Le serveur ne répond pas. Réessaie dans un instant.';
        }
      } else if (!finalEvt) {
        errorMsg = 'La connexion a coupé en cours de réponse. Réessaie.';
      }
    }

    if (finalEvt) this._finishBubble(bubble, finalEvt);
    else this._errorBubble(bubble, errorMsg || 'Je n’ai pas réussi à répondre.');

    this._busy = false;
    this._setComposerBusy(false);
    this._scrollDown();
  },

  async _sendBlocking(text) {
    if (typeof App === 'undefined' || !App.api || !App.api.copilot_send) return null;
    return App.api.copilot_send({
      question: text,
      view: (typeof App !== 'undefined' && App.currentView) || '',
    });
  },

  /** Stream SSE → remplit la bulle au fil de l’eau.
   *  Renvoie true si le flux a démarré (HTTP ok + body lisible). */
  async _streamInto(bubble, text, onEvent) {
    if (typeof window.fetch !== 'function' || typeof TextDecoder === 'undefined') return false;
    let res = null;
    try {
      res = await fetch('/api/copilot_stream', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question: text,
          view: (typeof App !== 'undefined' && App.currentView) || '',
        }),
      });
    } catch (e) {
      return false; // réseau/file:// → secours bloc
    }
    if (!res || !res.ok || !res.body || !res.body.getReader) return false;

    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = '';
    let acc = '';
    const textEl = bubble.querySelector('.cop-text');

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let cut;
      while ((cut = buf.indexOf('\n\n')) !== -1) {
        const block = buf.slice(0, cut);
        buf = buf.slice(cut + 2);
        const line = block.split('\n').find((l) => l.startsWith('data:'));
        if (!line) continue;
        let evt = null;
        try { evt = JSON.parse(line.slice(5)); } catch (e) { continue; }
        if (!evt || !evt.type) continue;
        if (evt.type === 'delta' && evt.text) {
          acc += evt.text;
          if (textEl) textEl.textContent = acc;
          this._scrollDown();
        }
        if (onEvent) onEvent(evt);
      }
    }
    return true;
  },

  // ---------------------------------------------------------------- bulles
  _appendBubble(role, content, opts) {
    opts = opts || {};
    const box = document.getElementById('copilot-messages');
    if (!box) return document.createElement('div');
    const el = document.createElement('div');
    el.className = 'cop-msg ' + (role === 'user' ? 'cop-user' : 'cop-assistant');
    const inner = document.createElement('div');
    inner.className = 'cop-text';
    if (opts.streaming) {
      el.classList.add('cop-streaming');
      inner.textContent = '';
    } else if (opts.md && role === 'assistant') {
      inner.innerHTML = this._md(content);
    } else {
      inner.textContent = content;
    }
    el.appendChild(inner);
    box.appendChild(el);
    return el;
  },

  _finishBubble(bubble, evt) {
    bubble.classList.remove('cop-streaming');
    const textEl = bubble.querySelector('.cop-text');
    if (textEl) textEl.innerHTML = this._md(evt.text || '…');

    const tags = [];
    if (evt.action_done === true) tags.push('✓ Fait');
    if (evt.action_done === false) tags.push('⚠ Action refusée');
    if (evt.sent_to_thomas) tags.push('✉ Message posté à Thomas');
    if (tags.length) {
      const t = document.createElement('div');
      t.className = 'cop-tags';
      t.textContent = tags.join(' · ');
      bubble.appendChild(t);
    }

    if (evt.navigate) this._navigate(evt.navigate);

    // Confirmation discrète dans la barre-guide, si elle est là
    if (evt.action_done === true && typeof Guide !== 'undefined' && Guide.say) {
      try { Guide.say('✓ Le copilote a lancé l’action.'); } catch (e) {}
    }
  },

  _errorBubble(bubble, msg) {
    bubble.classList.remove('cop-streaming');
    bubble.classList.add('cop-error');
    const textEl = bubble.querySelector('.cop-text');
    if (textEl) textEl.textContent = msg;
  },

  _navigate(view) {
    if (!view || typeof App === 'undefined' || !App.show) return;
    try { App.show(view); } catch (e) { return; }
    // Sur mobile le volet couvre tout l’écran : on le ferme pour montrer
    // la page demandée. Sur desktop il reste ouvert à côté.
    if (window.matchMedia('(max-width: 640px)').matches) this.close();
  },

  // ---------------------------------------------------------------- vocal
  /** Bascule vers le mode appel existant, en partant du même fil. */
  startCall() {
    if (typeof Claude === 'undefined' || !Claude.openCall) return;
    // Donne au vocal les derniers tours écrits comme mémoire de départ
    const turns = [];
    document.querySelectorAll('#copilot-messages .cop-msg').forEach((el) => {
      if (el.classList.contains('cop-advice') || el.classList.contains('cop-error')) return;
      const role = el.classList.contains('cop-user') ? 'user' : 'assistant';
      const t = el.querySelector('.cop-text');
      const content = t ? (t.innerText || '').trim() : '';
      if (content) turns.push({ role, content });
    });
    this.close();
    Claude.openCall(turns.slice(-10));
  },

  /** Appelé par claude.js à la fin d’un appel lancé d’ici : reverse les
   *  tours vocaux dans le fil écrit, puis rouvre le volet. */
  async afterCall(newTurns) {
    if (Array.isArray(newTurns) && newTurns.length) {
      try {
        if (typeof App !== 'undefined' && App.api && App.api.copilot_append) {
          await App.api.copilot_append({ messages: newTurns.slice(-20) });
        }
      } catch (e) { /* le fil serveur rattrapera au prochain tour */ }
      this._loaded = false; // force le rechargement du fil à l’ouverture
    }
    this.open();
  },

  async clearThread() {
    if (this._busy) return;
    if (!window.confirm('Repartir sur une discussion vierge ? L’historique sera effacé.')) return;
    try {
      if (typeof App !== 'undefined' && App.api && App.api.copilot_clear) {
        await App.api.copilot_clear({});
      }
    } catch (e) { /* au pire le fil restera */ }
    const box = document.getElementById('copilot-messages');
    if (box) { box.innerHTML = ''; this._renderWelcome(box); }
  },

  // ---------------------------------------------------------------- dictée
  _dictating: false,
  _rec: null,

  _toggleDictation() {
    if (this._dictating) { this._stopDictation(); return; }
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    const input = document.getElementById('copilot-input');
    const btn = document.getElementById('copilot-mic');
    if (!SR || !input) return;
    const rec = new SR();
    rec.lang = 'fr-FR';
    rec.continuous = true;
    rec.interimResults = true;
    this._rec = rec;
    this._dictating = true;
    if (btn) { btn.classList.add('cop-mic-on'); btn.textContent = '⏹'; }
    const base = input.value ? input.value + ' ' : '';
    let finalText = '';
    rec.onresult = (e) => {
      let interim = '';
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const t = e.results[i][0].transcript;
        if (e.results[i].isFinal) finalText += t;
        else interim += t;
      }
      input.value = (base + finalText + interim).trim();
      this._growInput();
    };
    rec.onerror = () => { try { rec.stop(); } catch (e) {} };
    rec.onend = () => {
      this._dictating = false;
      this._rec = null;
      if (btn) { btn.classList.remove('cop-mic-on'); btn.textContent = '🎤'; }
      if (input) input.focus();
    };
    try { rec.start(); } catch (e) { this._stopDictation(); }
  },

  _stopDictation() {
    if (this._rec) { try { this._rec.abort(); } catch (e) {} this._rec = null; }
    this._dictating = false;
    const btn = document.getElementById('copilot-mic');
    if (btn) { btn.classList.remove('cop-mic-on'); btn.textContent = '🎤'; }
  },

  // ---------------------------------------------------------------- montage
  _mount() {
    if (this._mounted) return;
    this._mounted = true;
    this._injectStyles();

    const panel = document.createElement('div');
    panel.id = 'copilot-panel';
    panel.innerHTML = `
      <div class="cop-head">
        <div class="cop-head-id">
          <span class="cop-head-orb"></span>
          <div>
            <div class="cop-head-title">Claude</div>
            <div class="cop-head-sub">ton copilote — il voit l’app en direct</div>
          </div>
        </div>
        <div class="cop-head-actions">
          <button id="copilot-call" title="Passer en vocal (conversation à la voix)">📞</button>
          <button id="copilot-new" title="Nouvelle discussion (efface le fil)">⟲</button>
          <button id="copilot-close" title="Fermer">×</button>
        </div>
      </div>
      <div id="copilot-messages" class="cop-messages"></div>
      <div class="cop-composer">
        <button id="copilot-mic" title="Dicter au lieu de taper">🎤</button>
        <textarea id="copilot-input" rows="1"
                  placeholder="Écris-moi… (Entrée pour envoyer)"></textarea>
        <button id="copilot-send" title="Envoyer">➤</button>
      </div>`;
    document.body.appendChild(panel);

    panel.querySelector('#copilot-close').onclick = () => this.close();
    panel.querySelector('#copilot-new').onclick = () => this.clearThread();
    panel.querySelector('#copilot-call').onclick = () => this.startCall();
    panel.querySelector('#copilot-send').onclick = () => this.send();

    const mic = panel.querySelector('#copilot-mic');
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) { mic.disabled = true; mic.title = 'Dictée non supportée par ce navigateur'; }
    else mic.onclick = () => this._toggleDictation();

    const input = panel.querySelector('#copilot-input');
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        this.send();
      }
      if (e.key === 'Escape') this.close();
    });
    input.addEventListener('input', () => this._growInput());
  },

  _growInput() {
    const input = document.getElementById('copilot-input');
    if (!input) return;
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 120) + 'px';
  },

  _setComposerBusy(busy) {
    const send = document.getElementById('copilot-send');
    if (send) { send.disabled = !!busy; send.textContent = busy ? '…' : '➤'; }
  },

  _scrollDown(force) {
    const box = document.getElementById('copilot-messages');
    if (!box) return;
    const nearBottom = (box.scrollHeight - box.scrollTop - box.clientHeight) < 140;
    if (force || nearBottom) box.scrollTop = box.scrollHeight;
  },

  // ---------------------------------------------------------------- rendu texte
  _esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
  },

  /** Markdown très léger et sûr : tout est échappé d’abord. */
  _md(text) {
    let h = this._esc(text);
    h = h.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
                  '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
    h = h.replace(/\*\*([^*\n]+)\*\*/g, '<b>$1</b>');
    h = h.replace(/`([^`\n]+)`/g, '<code>$1</code>');
    h = h.replace(/^[-*] (.*)$/gm, '<span class="cop-li">•&nbsp;$1</span>');
    h = h.replace(/\n/g, '<br>');
    return h;
  },

  // ---------------------------------------------------------------- styles
  _injectStyles() {
    if (document.getElementById('copilot-styles')) return;
    const s = document.createElement('style');
    s.id = 'copilot-styles';
    s.textContent = `
      #copilot-panel {
        position: fixed; z-index: 70;
        right: 18px; bottom: calc(14px + env(safe-area-inset-bottom, 0px));
        width: min(420px, calc(100vw - 24px));
        height: min(640px, calc(100vh - 80px));
        display: none; flex-direction: column; overflow: hidden;
        background: hsl(var(--surface-elevated, var(--surface)));
        border: 1px solid hsl(var(--border-strong));
        border-radius: 20px;
        box-shadow: 0 18px 60px rgba(15,23,42,.30);
        opacity: 0; transform: translateY(14px);
        transition: opacity .18s ease-out, transform .18s ease-out;
      }
      #copilot-panel.cop-visible { display: flex; opacity: 1; transform: translateY(0); }
      @media (max-width: 640px) {
        #copilot-panel {
          inset: 0; width: 100%; height: 100%;
          border-radius: 0; border: 0;
        }
      }
      .cop-head {
        display: flex; align-items: center; justify-content: space-between;
        gap: 10px; padding: 12px 14px;
        border-bottom: 1px solid hsl(var(--border));
        background: hsl(var(--surface) / .6);
      }
      .cop-head-id { display: flex; align-items: center; gap: 10px; min-width: 0; }
      .cop-head-orb {
        width: 30px; height: 30px; border-radius: 50%; flex-shrink: 0;
        background: radial-gradient(circle at 35% 35%,
          hsl(var(--accent)) 0%, hsl(var(--accent) / .55) 65%, hsl(var(--accent) / .25) 100%);
        box-shadow: 0 4px 14px hsl(var(--accent) / .35);
      }
      .cop-head-title { font-weight: 800; font-size: 14px; color: hsl(var(--text)); line-height: 1.1; }
      .cop-head-sub { font-size: 11px; color: hsl(var(--text-muted)); }
      .cop-head-actions { display: flex; gap: 4px; }
      .cop-head-actions button {
        width: 32px; height: 32px; border-radius: 10px; border: 0;
        background: transparent; cursor: pointer; font-size: 15px;
        color: hsl(var(--text-secondary)); line-height: 1;
      }
      .cop-head-actions button:hover { background: hsl(var(--border) / .5); }
      #copilot-close { font-size: 20px; }
      .cop-messages {
        flex: 1; overflow-y: auto; padding: 14px;
        display: flex; flex-direction: column; gap: 10px;
        overscroll-behavior: contain;
      }
      .cop-loading { text-align: center; color: hsl(var(--text-muted)); padding: 30px 0; }
      .cop-msg {
        max-width: 86%; padding: 9px 13px; border-radius: 16px;
        font-size: 13.5px; line-height: 1.55; word-wrap: break-word;
        animation: copIn .18s ease-out;
      }
      .cop-user {
        align-self: flex-end;
        background: hsl(var(--accent)); color: #fff;
        border-bottom-right-radius: 6px;
        white-space: pre-wrap;
      }
      .cop-assistant {
        align-self: flex-start;
        background: hsl(var(--surface));
        border: 1px solid hsl(var(--border));
        color: hsl(var(--text-secondary));
        border-bottom-left-radius: 6px;
      }
      .cop-assistant .cop-text { white-space: pre-wrap; }
      .cop-assistant .cop-text a { color: hsl(var(--accent)); font-weight: 600; }
      .cop-assistant .cop-text code {
        background: hsl(var(--border) / .4); padding: 1px 5px;
        border-radius: 5px; font-size: 12px;
      }
      .cop-li { display: block; padding-left: 4px; }
      .cop-streaming .cop-text::after {
        content: '▍'; color: hsl(var(--accent));
        animation: copBlink 1s steps(2) infinite;
      }
      .cop-error {
        background: hsl(0 70% 97%); border-color: hsl(0 60% 85%);
        color: hsl(0 60% 40%);
      }
      .cop-tags {
        margin-top: 7px; padding-top: 7px;
        border-top: 1px dashed hsl(var(--border));
        font-size: 11px; font-weight: 700; color: hsl(var(--success, 150 60% 40%));
      }
      .cop-advice { border-left: 3px solid hsl(var(--accent)); }
      .cop-advice-kicker {
        font-size: 10px; font-weight: 800; letter-spacing: .8px;
        text-transform: uppercase; color: hsl(var(--accent)); margin-bottom: 4px;
      }
      .cop-advice-headline { font-weight: 700; color: hsl(var(--text)); margin-bottom: 4px; }
      .cop-advice-go {
        margin-top: 8px; border: 0; cursor: pointer;
        background: hsl(var(--accent)); color: #fff;
        font-size: 12px; font-weight: 700; padding: 6px 12px; border-radius: 999px;
      }
      .cop-welcome {
        background: hsl(var(--surface));
        border: 1px dashed hsl(var(--border-strong));
        border-radius: 16px; padding: 14px;
      }
      .cop-w-title { font-weight: 800; font-size: 14px; color: hsl(var(--text)); margin-bottom: 6px; }
      .cop-w-body { font-size: 12.5px; line-height: 1.55; color: hsl(var(--text-secondary)); margin-bottom: 10px; }
      .cop-w-chips { display: flex; flex-wrap: wrap; gap: 6px; }
      .cop-chip {
        border: 1px solid hsl(var(--accent) / .4); cursor: pointer;
        background: hsl(var(--accent) / .08); color: hsl(var(--accent));
        font-size: 11.5px; font-weight: 600; padding: 5px 10px; border-radius: 999px;
      }
      .cop-chip:hover { background: hsl(var(--accent) / .16); }
      .cop-composer {
        display: flex; align-items: flex-end; gap: 8px;
        padding: 10px 12px calc(10px + env(safe-area-inset-bottom, 0px));
        border-top: 1px solid hsl(var(--border));
        background: hsl(var(--surface) / .6);
      }
      .cop-composer textarea {
        flex: 1; min-width: 0; resize: none; max-height: 120px;
        padding: 9px 12px; font-size: 13.5px; line-height: 1.45;
        border-radius: 14px; border: 1px solid hsl(var(--border));
        background: hsl(var(--surface)); color: hsl(var(--text));
        outline: none;
      }
      .cop-composer textarea:focus {
        border-color: hsl(var(--accent));
        box-shadow: 0 0 0 3px hsl(var(--accent) / .15);
      }
      .cop-composer button {
        width: 38px; height: 38px; flex-shrink: 0; border-radius: 12px;
        border: 1px solid hsl(var(--border)); cursor: pointer;
        background: hsl(var(--surface)); color: hsl(var(--text-secondary));
        font-size: 15px; line-height: 1;
      }
      .cop-composer button:hover { border-color: hsl(var(--accent) / .5); color: hsl(var(--accent)); }
      #copilot-send {
        background: hsl(var(--accent)); border-color: hsl(var(--accent)); color: #fff;
      }
      #copilot-send:disabled { opacity: .55; cursor: default; }
      #copilot-mic.cop-mic-on {
        background: #ef4444; border-color: #dc2626; color: #fff;
        animation: copMicPulse 1.2s ease-in-out infinite;
      }
      #copilot-mic:disabled { opacity: .4; cursor: not-allowed; }
      @keyframes copIn { from { opacity: 0; transform: translateY(5px); }
                         to { opacity: 1; transform: translateY(0); } }
      @keyframes copBlink { 50% { opacity: 0; } }
      @keyframes copMicPulse {
        0%, 100% { box-shadow: 0 0 0 0 rgba(239,68,68,.45); }
        50% { box-shadow: 0 0 0 8px rgba(239,68,68,0); }
      }
    `;
    document.head.appendChild(s);
  },
};
