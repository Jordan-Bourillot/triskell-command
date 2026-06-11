/* Allô Claude — l'assistant conseil (modal + voix).
 *
 * S'ouvre via Ctrl+Espace, le bouton de la quickbar du Cockpit, ou le
 * volet copilote (copilot.js) qui est la porte d'entrée par défaut.
 * La veille proactive (checkPending, appelée toutes les 60 s par app.js)
 * affiche les conseils en toast et les garde pour la prochaine ouverture.
 * Deux modes voix : dictée (🎤) et conversation continue (📞).
 */

// Injecte les styles du bouton micro et de l'état "écoute"
(function injectClaudeVoiceStyles() {
  if (document.getElementById('claude-voice-styles')) return;
  const s = document.createElement('style');
  s.id = 'claude-voice-styles';
  s.textContent = `
    .claude-mic-btn {
      display:inline-flex; align-items:center; justify-content:center;
      width:42px; height:42px;
      border-radius:12px;
      background: hsl(var(--surface));
      border:1px solid hsl(var(--border));
      color: hsl(var(--text-secondary));
      cursor:pointer; flex-shrink:0;
      transition: background .15s, color .15s, border-color .15s, transform .1s;
      font-size:18px; line-height:1;
    }
    .claude-mic-btn:hover {
      background: hsl(var(--accent) / 0.12);
      border-color: hsl(var(--accent) / 0.4);
      color: hsl(var(--accent));
    }
    .claude-mic-btn:active { transform: translateY(1px); }
    .claude-mic-btn.is-listening {
      background: hsl(var(--danger));
      border-color: hsl(var(--danger));
      color:#fff;
      animation: claude-mic-pulse 1.2s ease-in-out infinite;
    }
    .claude-mic-btn:disabled { opacity:.4; cursor:not-allowed; }
    @keyframes claude-mic-pulse {
      0%, 100% { box-shadow: 0 0 0 0 hsl(var(--danger) / .45); }
      50% { box-shadow: 0 0 0 10px hsl(var(--danger) / 0); }
    }
    .claude-voice-hint {
      font-size: 11px; color: hsl(var(--danger-text)); font-weight:600;
      margin-top: 6px; display: none;
    }
    .claude-voice-hint.is-active { display:block; }
    .claude-speak-btn {
      display:inline-flex; align-items:center; gap:6px;
      padding:6px 12px; margin-left:8px;
      border-radius:8px;
      background: hsl(var(--surface));
      border:1px solid hsl(var(--border));
      color: hsl(var(--text-secondary));
      cursor:pointer; font-size:12px; font-weight:600;
      transition: background .15s, color .15s, border-color .15s;
    }
    .claude-speak-btn:hover {
      background: hsl(var(--accent) / 0.1);
      border-color: hsl(var(--accent) / 0.4);
      color: hsl(var(--accent));
    }
    .claude-speak-btn.is-speaking {
      background: hsl(var(--success)); border-color: hsl(var(--success)); color:#fff;
    }
    /* ─── Mode Conversation : écran d'appel téléphonique ─── */
    .claude-convo-screen {
      position:absolute; inset:0; z-index:5;
      background: linear-gradient(180deg,
        hsl(var(--surface)) 0%,
        hsl(var(--bg)) 100%);
      display:flex; flex-direction:column; align-items:center; justify-content:center;
      padding: 32px;
      gap: 24px;
      animation: claude-convo-fadein 200ms ease-out;
    }
    @keyframes claude-convo-fadein { from { opacity:0 } to { opacity:1 } }
    .claude-convo-orb {
      position: relative;
      width: 160px; height: 160px;
      border-radius: 50%;
      display: flex; align-items: center; justify-content: center;
    }
    .claude-convo-orb .orb-core {
      position: absolute; inset: 0;
      border-radius: 50%;
      background: radial-gradient(circle at 35% 35%,
        hsl(var(--accent)) 0%,
        hsl(var(--accent) / 0.6) 60%,
        hsl(var(--accent) / 0.3) 100%);
      box-shadow: 0 12px 40px hsl(var(--accent) / 0.4);
      transition: background 300ms, box-shadow 300ms;
    }
    .claude-convo-orb .orb-pulse {
      position: absolute; inset: 0;
      border-radius: 50%;
      border: 2px solid hsl(var(--accent) / 0.5);
      opacity: 0;
    }
    /* Dégradés à 3 nuances gardés en dur : couleurs SÉMANTIQUES d'état
       (rouge = j'enregistre, ambre = je réfléchis, vert = je parle) que
       les tokens mono-teinte ne savent pas reproduire. Halos en tokens. */
    .claude-convo-orb[data-state="listening"] .orb-core {
      background: radial-gradient(circle at 35% 35%, #ef4444 0%, #dc2626 60%, #991b1b 100%);
      box-shadow: 0 12px 50px hsl(var(--danger) / 0.5);
    }
    .claude-convo-orb[data-state="listening"] .orb-pulse {
      animation: claude-orb-pulse 1.4s ease-out infinite;
      border-color: hsl(var(--danger) / 0.6);
    }
    .claude-convo-orb[data-state="thinking"] .orb-core {
      background: radial-gradient(circle at 35% 35%, #fbbf24 0%, #f59e0b 60%, #b45309 100%);
      box-shadow: 0 12px 50px hsl(var(--warning) / 0.5);
      animation: claude-orb-breathe 1.4s ease-in-out infinite;
    }
    .claude-convo-orb[data-state="speaking"] .orb-core {
      background: radial-gradient(circle at 35% 35%, #22c55e 0%, #16a34a 60%, #14532d 100%);
      box-shadow: 0 12px 50px hsl(var(--success) / 0.5);
      animation: claude-orb-wave 0.6s ease-in-out infinite;
    }
    @keyframes claude-orb-pulse {
      0%   { opacity: 0.6; transform: scale(1); }
      100% { opacity: 0; transform: scale(1.5); }
    }
    @keyframes claude-orb-breathe {
      0%, 100% { transform: scale(1); }
      50%      { transform: scale(1.08); }
    }
    @keyframes claude-orb-wave {
      0%, 100% { transform: scale(1); }
      50%      { transform: scale(1.04); }
    }
    .claude-convo-status {
      font-size: 18px; font-weight: 700; letter-spacing: -0.3px;
      color: hsl(var(--text));
      text-align: center;
      min-height: 28px;
    }
    .claude-convo-transcript {
      max-width: 560px; width: 100%;
      min-height: 60px; max-height: 160px;
      overflow-y: auto;
      padding: 12px 16px;
      border-radius: 14px;
      background: hsl(var(--surface-elevated));
      border: 1px solid hsl(var(--border));
      font-size: 14px; line-height: 1.55;
      color: hsl(var(--text-secondary));
      text-align: center;
    }
    .claude-convo-transcript:empty::before {
      content: '…'; color: hsl(var(--text-muted));
    }
    .claude-convo-stop {
      display: inline-flex; align-items: center; gap: 8px;
      padding: 14px 28px;
      border-radius: 999px;
      background: hsl(var(--danger)); color: #fff;
      border: 0; cursor: pointer;
      font-size: 14px; font-weight: 700;
      letter-spacing: 0.5px;
      box-shadow: 0 6px 20px hsl(var(--danger) / 0.4);
      transition: transform 100ms, box-shadow 200ms;
    }
    .claude-convo-stop:hover { transform: translateY(-1px); box-shadow: 0 8px 24px hsl(var(--danger) / 0.55); }
    .claude-convo-stop:active { transform: translateY(0); }
  `;
  document.head.appendChild(s);
})();

const Claude = {
  isAttention: false,
  pendingAdvice: null,
  _recognition: null,
  _listening: false,
  _adviceCache: null,          // dernier conseil d'ouverture { advice, ts }
  ADVICE_CACHE_MS: 5 * 60 * 1000,

  setAttention(on) {
    this.isAttention = !!on;
    // Les anciennes pastilles (#claude-fab, #claude-fab-dot, #claude-menu-dot)
    // n'existent plus : l'attention vit sur la pastille du copilote
    // (bouton 💬 de la barre-guide).
    if (typeof Copilot !== 'undefined' && Copilot.setBadge) {
      try { Copilot.setBadge(this.isAttention && !Copilot.isOpen()); } catch (e) {}
    }
  },

  async checkPending() {
    if (!App.api) return;
    try {
      const advice = await App.api.claude_consume_pending();
      // Un vrai conseil a du CONTENU. (Les vieux serveurs renvoyaient
      // {ok:true} vide quand il n’y avait rien → pastille fantôme.)
      if (advice && advice.ok && (advice.headline || advice.advice)) {
        this.pendingAdvice = advice;
        this.setAttention(true);
        // Volet copilote déjà ouvert → le conseil s’affiche tout de suite
        if (typeof Copilot !== 'undefined' && Copilot.isOpen && Copilot.isOpen()) {
          try { Copilot._consumePendingAdvice(); return; } catch (e) {}
        }
        // Sinon, on le montre TOUT DE SUITE en toast : le serveur vient de
        // le consommer, sans ça il serait perdu. Il reste aussi en mémoire
        // (pendingAdvice) pour s’afficher en tête à la prochaine ouverture.
        if (typeof Toast !== 'undefined' && Toast.show) {
          const texte = [advice.headline, advice.advice].filter(Boolean).join(' — ');
          Toast.show(texte, { type: 'info', title: '💡 Allô Claude', duration: 12000 });
        }
      }
    } catch (e) { /* silencieux : la veille réessaiera dans 60 s */ }
  },

  async open() {
    // Depuis le 10/06/2026, la porte d’entrée de l’assistant est le volet
    // copilote (conversation écrite, persistante, avec les mêmes pouvoirs).
    // L’ancien dialog ne sert plus que de secours si copilot.js manque.
    if (typeof Copilot !== 'undefined' && Copilot.open) {
      Copilot.open();
      return;
    }
    this.setAttention(false);
    const overlay = this._buildOverlay();
    document.body.appendChild(overlay);
    overlay.querySelector('.modal-card').classList.add('animate-slide-up');

    // Charge le conseil : pré-rempli par la veille, sinon cache récent
    // (5 min — rouvrir le modal dans la foulée ne rappelle pas l'IA),
    // sinon nouvel appel.
    if (this.pendingAdvice) {
      this._renderAdvice(overlay, this.pendingAdvice);
      this.pendingAdvice = null;
    } else if (this._adviceCache &&
               (Date.now() - this._adviceCache.ts) < this.ADVICE_CACHE_MS) {
      this._renderAdvice(overlay, this._adviceCache.advice);
    } else {
      this._renderLoading(overlay);
      if (App.api) {
        try {
          const advice = await App.api.claude_ask({});
          if (advice && advice.ok) this._adviceCache = { advice, ts: Date.now() };
          this._renderAdvice(overlay, advice);
        } catch (e) {
          this._renderError(overlay, e);
        }
      } else {
        // Mode preview
        setTimeout(() => this._renderAdvice(overlay, {
          ok: true,
          urgency: 'medium',
          headline: 'Tu as 2 prospects intéressés à recontacter aujourd’hui',
          advice: "C'est ta priorité absolue. Ouvre la vue Réponses, lis ce qu'ils ont écrit, et envoie-leur le brouillon que l'app a préparé en l'adaptant si besoin. Pas plus de 2 heures avant de répondre — au-delà ils refroidissent.",
          suggested_view: 'replies',
          suggested_action_label: 'Voir les réponses',
        }), 600);
      }
    }
  },

  close(overlay) {
    if (!overlay) return;
    // Sort proprement du mode conversation si actif
    this._convoMode = false;
    // Coupe la dictée et la synthèse vocale (même en attente de lecture)
    if (this._recognition) {
      try { this._recognition.abort(); } catch (e) {}
      this._recognition = null;
    }
    if (window.speechSynthesis) {
      try { window.speechSynthesis.cancel(); } catch (e) {}
    }
    // Retire l'écouteur Échap posé à la construction du modal
    if (overlay._claudeOnKeydown) {
      document.removeEventListener('keydown', overlay._claudeOnKeydown);
      overlay._claudeOnKeydown = null;
    }
    overlay.style.opacity = '0';
    setTimeout(() => overlay.remove(), 200);
  },

  // ---- Modal builders ----
  _buildOverlay() {
    const overlay = document.createElement('div');
    // Mobile : full-screen (p-0). Desktop : centré avec marges (p-6).
    overlay.className = 'fixed inset-0 z-[100] flex items-stretch sm:items-center justify-center sm:p-6 transition-opacity duration-200';
    overlay.style.background = 'rgba(15,23,42,0.45)';
    overlay.style.backdropFilter = 'blur(6px)';

    overlay.innerHTML = `
      <div class="modal-card relative bg-surface sm:rounded-3xl shadow-hero
                  w-full sm:max-w-2xl h-full sm:h-auto sm:max-h-[85vh] overflow-hidden flex flex-col"
           role="dialog" aria-modal="true" aria-label="Allô Claude"
           style="border: 1px solid hsl(var(--border));">
        <!-- Header -->
        <div class="px-5 pt-5 pb-3 sm:px-8 sm:pt-8 sm:pb-4 flex items-center gap-3 sm:gap-4 border-b border-border">
          <div class="w-10 h-10 sm:w-12 sm:h-12 rounded-2xl bg-gradient-to-br from-accent to-accent-glow
                      flex items-center justify-center text-white shadow-soft shrink-0">
            <svg class="w-5 h-5 sm:w-6 sm:h-6" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                 stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
              <path d="M21 12a8 8 0 0 1-11.7 7.1L4 20.5l1.4-5.3A8 8 0 1 1 21 12z" fill="currentColor" fill-opacity="0.18"/>
              <path d="M21 12a8 8 0 0 1-11.7 7.1L4 20.5l1.4-5.3A8 8 0 1 1 21 12z"/>
              <path d="M12 8.5v3M12 12.5v3M8.5 12h3M12.5 12h3" stroke-width="1.6"/>
            </svg>
          </div>
          <div class="flex-1 min-w-0">
            <div class="hero-kicker mb-1">ALLÔ CLAUDE</div>
            <div class="font-sans text-base sm:text-xl font-bold leading-tight tracking-tight">Quelle est ma prochaine action&nbsp;?</div>
          </div>
          <button class="text-text-muted hover:text-text text-2xl leading-none w-8 h-8 shrink-0" id="claude-close"
                  title="Fermer" aria-label="Fermer la fenêtre Allô Claude">×</button>
        </div>

        <!-- Body -->
        <div id="claude-body" class="flex-1 overflow-y-auto px-5 py-5 sm:px-8 sm:py-8"></div>

        <!-- Footer (question libre) -->
        <div class="px-5 py-4 sm:px-8 sm:py-5 border-t border-border bg-surface-elevated/50">
          <div class="hero-kicker mb-2">OU POSE UNE QUESTION LIBRE</div>
          <div class="flex flex-col sm:flex-row gap-2 items-stretch">
            <button id="claude-mic-btn" type="button" class="claude-mic-btn"
                    title="Parler à Claude (dictée vocale)" aria-label="Dicter ma question">🎤</button>
            <button id="claude-convo-btn" type="button" class="claude-mic-btn"
                    title="Conversation vocale en continu" aria-label="Démarrer une conversation vocale"
                    style="font-size:16px;">📞</button>
            <input id="claude-question" type="text"
                   class="flex-1 min-w-0 px-4 py-2.5 text-sm rounded-xl bg-surface border border-border
                          focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent
                          text-text placeholder:text-text-muted"
                   placeholder="ex: comment booster mes réponses cette semaine ?" />
            <button id="claude-ask-free" class="btn btn-primary w-full sm:w-auto justify-center shrink-0">Demander</button>
          </div>
          <div id="claude-voice-hint" class="claude-voice-hint">🔴 J’écoute… (parle, puis clique sur ⏹ pour arrêter et envoyer)</div>
        </div>
      </div>
    `;

    overlay.querySelector('#claude-close').onclick = () => this.close(overlay);
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) this.close(overlay);
    });

    // Fermeture par Échap. En plein appel vocal, Échap raccroche d'abord ;
    // un 2e Échap ferme. L'écouteur est retiré dans close(), et en secours
    // au prochain changement de vue (App.onViewCleanup).
    const onKeydown = (e) => {
      if (e.key !== 'Escape') return;
      if (this._convoMode) this._stopConversation(overlay);
      else this.close(overlay);
    };
    document.addEventListener('keydown', onKeydown);
    overlay._claudeOnKeydown = onKeydown;
    if (typeof App !== 'undefined' && App.onViewCleanup) {
      App.onViewCleanup(() => {
        // Pas pendant un appel vocal : la navigation en cours d'appel est
        // voulue (l'assistant ouvre un écran pendant qu'il parle).
        if (!this._convoMode && document.body.contains(overlay)) this.close(overlay);
      });
    }

    // Historique du mode texte : 10 tours max, le temps de la session du
    // modal (même mécanique que le mode vocal).
    this._askHistory = [];
    overlay.querySelector('#claude-ask-free').onclick = async () => {
      const q = overlay.querySelector('#claude-question').value.trim();
      if (!q) return;
      if (!App.api) {
        this._renderError(overlay, 'La connexion au serveur n’est pas prête — recharge la page et réessaie.');
        return;
      }
      this._renderLoading(overlay);
      try {
        const advice = await App.api.claude_ask({ question: q, history: this._askHistory });
        if (advice && advice.ok) {
          const answer = [advice.headline, advice.advice].filter(Boolean).join('. ');
          this._askHistory.push({ role: 'user', content: q });
          if (answer) this._askHistory.push({ role: 'assistant', content: answer });
          if (this._askHistory.length > 10) this._askHistory = this._askHistory.slice(-10);
        }
        this._renderAdvice(overlay, advice);
      } catch (e) { this._renderError(overlay, e); }
    };
    overlay.querySelector('#claude-question').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') overlay.querySelector('#claude-ask-free').click();
    });

    // Bouton micro (dictée vocale)
    const micBtn = overlay.querySelector('#claude-mic-btn');
    if (micBtn) {
      if (!this._supportsVoiceInput()) {
        micBtn.disabled = true;
        micBtn.title = "Ton navigateur ne supporte pas la dictée vocale (utilise Chrome, Edge ou Safari)";
      } else {
        micBtn.onclick = () => this._toggleVoiceInput(overlay);
      }
    }

    // Bouton conversation vocale en continu (mode "appel")
    const convoBtn = overlay.querySelector('#claude-convo-btn');
    if (convoBtn) {
      if (!this._supportsVoiceInput() || !this._supportsVoiceOutput()) {
        convoBtn.disabled = true;
        convoBtn.title = "Ton navigateur ne supporte pas la voix dans les deux sens";
      } else {
        convoBtn.onclick = () => this._startConversation(overlay);
      }
    }
    return overlay;
  },

  // ---- Mode Conversation : boucle écoute → réponse vocale → écoute ----

  /** Ouvre DIRECTEMENT le mode appel (sans passer par la fiche-conseil).
   *  Appelé par le volet copilote ; seedHistory = derniers tours écrits,
   *  pour que la voix reprenne la même conversation. */
  openCall(seedHistory) {
    this.setAttention(false);
    const overlay = this._buildOverlay();
    document.body.appendChild(overlay);
    overlay.querySelector('.modal-card').classList.add('animate-slide-up');
    const body = overlay.querySelector('#claude-body');
    if (body) {
      body.innerHTML = '<div class="text-center py-12 text-text-muted text-sm">' +
        'Mode vocal — raccroche pour revenir à l’écrit.</div>';
    }
    this._fromCopilot = true;
    this._startConversation(overlay);
    // _startConversation vient de réinitialiser l’historique : on greffe
    // le fil écrit APRÈS, pour que Claude suive la même discussion.
    if (Array.isArray(seedHistory) && seedHistory.length) {
      this._convoHistory = seedHistory.slice(-10);
    }
    this._convoSeedLen = (this._convoHistory || []).length;
  },

  _startConversation(overlay) {
    if (this._convoMode) return;
    this._convoMode = true;
    this._convoHistory = []; // historique des tours pour donner du contexte à Claude
    // Stoppe toute écoute / lecture en cours d'un précédent mode
    if (this._recognition) { try { this._recognition.abort(); } catch (e) {} this._recognition = null; }
    if (window.speechSynthesis) { try { window.speechSynthesis.cancel(); } catch (e) {} }

    // Construit l'écran d'appel par-dessus le body+footer du modal
    const card = overlay.querySelector('.modal-card');
    if (!card) return;
    const screen = document.createElement('div');
    screen.className = 'claude-convo-screen';
    screen.id = 'claude-convo-screen';
    screen.innerHTML = `
      <div class="claude-convo-orb" data-state="idle">
        <div class="orb-core"></div>
        <div class="orb-pulse"></div>
      </div>
      <div class="claude-convo-status">Connexion…</div>
      <div class="claude-convo-transcript"></div>
      <button class="claude-convo-stop" type="button">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" style="transform: rotate(135deg)"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.13.96.37 1.9.72 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.91.35 1.85.59 2.81.72A2 2 0 0 1 22 16.92z"/></svg>
        Raccrocher
      </button>
    `;
    card.appendChild(screen);

    screen.querySelector('.claude-convo-stop').onclick = () => this._stopConversation(overlay);

    // Démarre la boucle après un court fade-in
    setTimeout(() => this._convoListen(overlay), 300);
  },

  _stopConversation(overlay) {
    this._convoMode = false;
    if (this._recognition) { try { this._recognition.abort(); } catch (e) {} this._recognition = null; }
    if (window.speechSynthesis) { try { window.speechSynthesis.cancel(); } catch (e) {} }
    const screen = overlay.querySelector('#claude-convo-screen');
    if (screen) screen.remove();
    // Appel lancé depuis le volet copilote : on reverse les tours vocaux
    // dans le fil écrit (une seule conversation) et on rouvre le volet.
    if (this._fromCopilot) {
      this._fromCopilot = false;
      const seed = this._convoSeedLen || 0;
      const turns = (this._convoHistory || []).slice(seed);
      this._convoSeedLen = 0;
      this.close(overlay);
      if (typeof Copilot !== 'undefined' && Copilot.afterCall) {
        try { Copilot.afterCall(turns); } catch (e) {}
      }
    }
  },

  _setConvoState(overlay, state, label) {
    const orb = overlay.querySelector('.claude-convo-orb');
    const status = overlay.querySelector('.claude-convo-status');
    if (orb) orb.setAttribute('data-state', state);
    if (status && label) status.textContent = label;
  },

  _setConvoTranscript(overlay, text) {
    const t = overlay.querySelector('.claude-convo-transcript');
    if (t) t.textContent = text || '';
  },

  _convoListen(overlay) {
    if (!this._convoMode) return;
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) { this._stopConversation(overlay); return; }

    this._setConvoState(overlay, 'listening', 'Je t’écoute…');
    this._micBlocked = false;

    const rec = new SR();
    rec.lang = 'fr-FR';
    rec.continuous = false;        // s'arrête tout seul après silence
    rec.interimResults = true;
    this._recognition = rec;

    let finalText = '';
    rec.onresult = (e) => {
      finalText = '';
      let interim = '';
      for (let i = 0; i < e.results.length; i++) {
        const t = e.results[i][0].transcript;
        if (e.results[i].isFinal) finalText += t;
        else interim += t;
      }
      this._setConvoTranscript(overlay, (finalText + interim).trim());
    };
    rec.onerror = (e) => {
      // 'no-speech' = silence prolongé, c'est normal en conversation.
      // Micro refusé ou introuvable, en revanche : on doit SORTIR de la
      // boucle, sinon « Je t'écoute… » tourne pour toujours en silence.
      const code = (e && e.error) || '';
      if (code === 'not-allowed' || code === 'audio-capture' || code === 'service-not-allowed') {
        this._micBlocked = true;
      }
      try { rec.stop(); } catch (err) {}
    };
    rec.onend = () => {
      this._recognition = null;
      const q = finalText.trim();
      if (!this._convoMode) return;
      if (this._micBlocked) {
        this._micBlocked = false;
        if (typeof Toast !== 'undefined' && Toast.warn) {
          Toast.warn('Ton micro est bloqué — autorise-le via l’icône caméra/micro de la barre d’adresse, puis relance l’appel.', 'Micro inaccessible');
        }
        this._stopConversation(overlay);
        return;
      }
      if (!q) {
        // Rien dit → on relance l'écoute après une courte pause
        setTimeout(() => this._convoListen(overlay), 400);
        return;
      }
      this._convoAsk(overlay, q);
    };

    try { rec.start(); }
    catch (e) {
      // Souvent un "already started" — on retente après un cycle
      setTimeout(() => this._convoMode && this._convoListen(overlay), 300);
    }
  },

  async _convoAsk(overlay, question) {
    if (!this._convoMode) return;
    this._setConvoState(overlay, 'thinking', 'Je réfléchis…');
    this._setConvoTranscript(overlay, '« ' + question + ' »');

    // Endpoint dédié à la conversation libre (texte brut, pas de format imposé,
    // historique passé pour que Claude suive le fil)
    let reply = null;
    try {
      reply = await App.api.claude_chat({
        question,
        history: this._convoHistory || [],
      });
    } catch (e) { /* swallow */ }

    if (!this._convoMode) return;

    let speakable = '';
    if (reply && reply.ok && reply.text) {
      speakable = reply.text;
      // L'assistant a pu AGIR (lancer une prospection, ouvrir un écran…) :
      // si le serveur renvoie une navigation, on l'exécute en arrière-plan
      // pendant qu'il parle — effet « il l'a fait pour moi ». Uniquement
      // vers une vue connue du routeur (liste blanche).
      if (reply.navigate && typeof App !== 'undefined' && App.show &&
          Array.isArray(App.KNOWN_VIEWS) && App.KNOWN_VIEWS.includes(reply.navigate)) {
        try { App.show(reply.navigate); } catch (e) { /* jamais bloquant */ }
      }
      // On nourrit l'historique pour les tours suivants
      this._convoHistory = this._convoHistory || [];
      this._convoHistory.push({ role: 'user',      content: question });
      this._convoHistory.push({ role: 'assistant', content: reply.text });
      // Borne à 20 tours pour pas exploser
      if (this._convoHistory.length > 20) {
        this._convoHistory = this._convoHistory.slice(-20);
      }
    } else {
      speakable = "Désolé, je n'ai pas pu te répondre cette fois. Réessaye ?";
    }

    this._convoSpeak(overlay, speakable);
  },

  _stripMarkdown(text) {
    return String(text || '')
      .replace(/```[\s\S]*?```/g, '')                 // blocs de code
      .replace(/`([^`]+)`/g, '$1')                    // inline code
      .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')        // liens [txt](url) → txt
      .replace(/[*_]{1,3}([^*_]+)[*_]{1,3}/g, '$1')   // gras / italique
      .replace(/^#{1,6}\s+/gm, '')                    // titres
      .replace(/^>\s+/gm, '')                         // citations
      .replace(/^[-*+]\s+/gm, '')                     // listes
      .replace(/\n{3,}/g, '\n\n');
  },

  _pickBestFrenchVoice() {
    const voices = window.speechSynthesis.getVoices();
    if (!voices || !voices.length) return null;
    const fr = voices.filter(v => v.lang && v.lang.toLowerCase().startsWith('fr'));
    if (!fr.length) return null;
    // Préfère par ordre : Google (Chrome) > voix Apple Premium > voix neuronales
    // Microsoft > voix par défaut. Évite "Hortense" (très robotique).
    const score = (v) => {
      const n = (v.name || '').toLowerCase();
      let s = 0;
      if (n.includes('google')) s += 100;          // Chrome's voice — la plus naturelle
      if (n.includes('amelie') || n.includes('amélie')) s += 80;  // macOS premium
      if (n.includes('thomas')) s += 75;            // macOS premium
      if (n.includes('audrey')) s += 70;            // macOS
      if (n.includes('paul')) s += 65;
      if (n.includes('neural') || n.includes('online')) s += 50;  // voix cloud Microsoft
      if (n.includes('natural')) s += 50;
      if (n.includes('denise')) s += 40;            // bonne Microsoft online
      if (n.includes('hortense')) s -= 50;          // robotique
      if (v.localService === false) s += 20;        // cloud > local en général
      if (v.default) s += 5;
      return s;
    };
    fr.sort((a, b) => score(b) - score(a));
    return fr[0];
  },

  /** Lance la lecture d'une phrase avec la meilleure voix française.
   *  Gère le cas (Chrome surtout) où getVoices() est vide au premier
   *  appel : la liste arrive plus tard via l'événement voiceschanged —
   *  on attend (1 s max), puis on parle. Utilisé par le mode conversation
   *  ET le bouton « Écouter » (même voix partout). */
  _speakUtterance(u) {
    if (!window.speechSynthesis) return;
    const speakNow = () => {
      const best = this._pickBestFrenchVoice();
      if (best) u.voice = best;
      window.speechSynthesis.speak(u);
    };
    const voices = window.speechSynthesis.getVoices();
    if (voices && voices.length) { speakNow(); return; }
    let done = false;
    const onVoices = () => {
      if (done) return;
      done = true;
      try { window.speechSynthesis.removeEventListener('voiceschanged', onVoices); } catch (e) {}
      speakNow();
    };
    try { window.speechSynthesis.addEventListener('voiceschanged', onVoices); } catch (e) {}
    // Filet : certains navigateurs n'émettent jamais voiceschanged →
    // on parle quand même avec la voix par défaut.
    setTimeout(onVoices, 1000);
  },

  _convoSpeak(overlay, text) {
    if (!this._convoMode) return;
    const clean = this._stripMarkdown(text);
    this._setConvoState(overlay, 'speaking', 'Je te réponds…');
    this._setConvoTranscript(overlay, clean);

    if (!window.speechSynthesis) {
      setTimeout(() => this._convoListen(overlay), 1500);
      return;
    }

    const u = new SpeechSynthesisUtterance(clean);
    u.lang = 'fr-FR';
    u.rate = 1.02;   // légèrement plus rapide que 1 → moins traînant
    u.pitch = 1.0;
    u.volume = 1.0;
    // Sécurité : si onend ne se déclenche jamais (bug Chrome), on relance après
    // un timeout proportionnel au texte (~0.06s par caractère + 1s de marge)
    const failSafe = setTimeout(() => {
      if (this._convoMode) this._convoListen(overlay);
    }, Math.max(3000, clean.length * 60 + 1500));
    u.onend = () => {
      clearTimeout(failSafe);
      if (this._convoMode) this._convoListen(overlay);
    };
    u.onerror = u.onend;
    this._speakUtterance(u);
  },

  _supportsVoiceInput() {
    return !!(window.SpeechRecognition || window.webkitSpeechRecognition);
  },

  _supportsVoiceOutput() {
    return !!window.speechSynthesis;
  },

  _toggleVoiceInput(overlay) {
    const input = overlay.querySelector('#claude-question');
    const micBtn = overlay.querySelector('#claude-mic-btn');
    const hint = overlay.querySelector('#claude-voice-hint');

    // Si déjà en écoute → on stoppe (et on déclenche le submit si du texte)
    if (this._listening && this._recognition) {
      try { this._recognition.stop(); } catch (e) {}
      return;
    }

    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) return;
    const rec = new SR();
    rec.lang = 'fr-FR';
    rec.continuous = true;        // on laisse Jordan parler longtemps
    rec.interimResults = true;    // remplit l'input au fur et à mesure

    this._recognition = rec;
    this._listening = true;
    micBtn.classList.add('is-listening');
    micBtn.textContent = '⏹';
    micBtn.title = "Arrêter l'écoute";
    hint.classList.add('is-active');
    input.value = '';

    let finalText = '';
    rec.onresult = (e) => {
      let interim = '';
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const t = e.results[i][0].transcript;
        if (e.results[i].isFinal) finalText += t;
        else interim += t;
      }
      input.value = (finalText + interim).trim();
    };
    let micBlocked = false;
    rec.onerror = (e) => {
      const code = (e && e.error) || '';
      if (code === 'not-allowed' || code === 'audio-capture' || code === 'service-not-allowed') {
        micBlocked = true;
      }
      try { rec.stop(); } catch (err) {}
    };
    rec.onend = () => {
      this._listening = false;
      this._recognition = null;
      micBtn.classList.remove('is-listening');
      micBtn.textContent = '🎤';
      micBtn.title = "Parler à Claude (dictée vocale)";
      hint.classList.remove('is-active');
      if (micBlocked) {
        if (typeof Toast !== 'undefined' && Toast.warn) {
          Toast.warn('Ton micro est bloqué — autorise-le via l’icône caméra/micro de la barre d’adresse.', 'Micro inaccessible');
        }
        return;
      }
      // Auto-submit si on a quelque chose
      if (input.value.trim()) {
        overlay.querySelector('#claude-ask-free').click();
      }
    };

    try {
      rec.start();
    } catch (e) {
      this._listening = false;
      this._recognition = null;
      micBtn.classList.remove('is-listening');
      micBtn.textContent = '🎤';
      hint.classList.remove('is-active');
      if (typeof Toast !== 'undefined' && Toast.warn) {
        Toast.warn('Impossible de démarrer l’écoute. Vérifie que tu as autorisé le micro pour cette page.', 'Micro inaccessible');
      }
    }
  },

  _toggleSpeak(text, btn) {
    if (!window.speechSynthesis) return;
    // Si déjà en train de parler → stop
    if (window.speechSynthesis.speaking) {
      window.speechSynthesis.cancel();
      if (btn) {
        btn.classList.remove('is-speaking');
        btn.innerHTML = '🔊 Écouter';
      }
      return;
    }
    const u = new SpeechSynthesisUtterance(text);
    u.lang = 'fr-FR';
    u.rate = 1.0;
    u.pitch = 1.0;
    u.onend = () => {
      if (btn) {
        btn.classList.remove('is-speaking');
        btn.innerHTML = '🔊 Écouter';
      }
    };
    u.onerror = u.onend;
    if (btn) {
      btn.classList.add('is-speaking');
      btn.innerHTML = '⏹ Arrêter';
    }
    // Même choix de voix que le mode conversation (+ liste de voix vide gérée)
    this._speakUtterance(u);
  },

  _renderLoading(overlay) {
    const body = overlay.querySelector('#claude-body');
    body.innerHTML = `
      <div class="text-center py-12">
        <div class="text-5xl text-accent mb-4 animate-pulse">…</div>
        <p class="text-text-secondary">Claude analyse l'état de ton app…</p>
      </div>
    `;
  },

  _renderError(overlay, err) {
    const body = overlay.querySelector('#claude-body');
    if (!body) return;
    const detail = this._esc(String((err && err.message) || err || ''));
    body.innerHTML = `
      <div class="text-center py-8">
        <p class="text-danger font-semibold mb-2">Claude n’a pas pu répondre</p>
        <p class="text-sm text-text-muted mb-4">Réessaie dans un instant. Si ça se reproduit, vérifie ta connexion internet.</p>
        ${detail ? `
          <details class="text-left max-w-md mx-auto">
            <summary class="text-[11px] text-text-muted cursor-pointer select-none">Détail technique</summary>
            <pre class="text-[11px] text-text-muted whitespace-pre-wrap break-words mt-2 p-3 rounded-lg bg-bg border border-border">${detail}</pre>
          </details>
        ` : ''}
      </div>
    `;
  },

  _renderAdvice(overlay, advice) {
    if (!advice || !advice.ok) {
      this._renderError(overlay, advice?.error || 'erreur inconnue');
      return;
    }
    const body = overlay.querySelector('#claude-body');
    const labels = { low: 'tranquille', medium: 'à faire dans la journée', high: 'urgent' };
    const colors = { low: 'text-text-muted', medium: 'text-warning', high: 'text-danger' };
    // Urgence inconnue du serveur → on retombe sur 'low' (anti-plantage)
    const u = labels[advice.urgency] ? advice.urgency : 'low';

    const speakable = [advice.headline, advice.advice].filter(Boolean).join('. ');
    const canSpeak = this._supportsVoiceOutput() && speakable;

    body.innerHTML = `
      <div class="animate-fade-in">
        <div class="flex items-center gap-2 mb-5">
          <span class="inline-block px-3 py-1 rounded-full text-[11px] font-bold tracking-widest
                       bg-bg ${colors[u]}">
            NIVEAU : ${labels[u].toUpperCase()}
          </span>
          ${canSpeak ? `<button id="claude-speak-btn" type="button" class="claude-speak-btn" title="Faire lire la réponse à voix haute">🔊 Écouter</button>` : ''}
        </div>
        ${advice.headline ? `<h3 class="font-sans text-2xl font-bold mb-4 leading-snug tracking-tight">${this._esc(advice.headline)}</h3>` : ''}
        ${advice.advice ? `<div class="text-text-secondary leading-relaxed whitespace-pre-line mb-6">${this._esc(advice.advice)}</div>` : ''}
        ${advice.suggested_view ? `
          <button id="claude-go-btn" class="btn btn-primary">
            ${this._esc(advice.suggested_action_label || 'Y aller')} →
          </button>
        ` : ''}
      </div>
    `;

    if (canSpeak) {
      const speakBtn = body.querySelector('#claude-speak-btn');
      if (speakBtn) speakBtn.onclick = () => this._toggleSpeak(speakable, speakBtn);
    }

    // « Y aller » : on ferme CE modal (référence directe, pas de chasse au
    // premier overlay z-100 du DOM), on coupe la voix, et on ne navigue que
    // vers une vue connue du routeur.
    const goBtn = body.querySelector('#claude-go-btn');
    if (goBtn) {
      goBtn.onclick = () => {
        const target = advice.suggested_view;
        if (window.speechSynthesis) {
          try { window.speechSynthesis.cancel(); } catch (e) {}
        }
        const known = typeof App !== 'undefined' && App.show &&
          Array.isArray(App.KNOWN_VIEWS) && App.KNOWN_VIEWS.includes(target);
        if (!known) {
          if (typeof Toast !== 'undefined' && Toast.warn) {
            Toast.warn('Cet écran n’existe pas (ou plus) dans l’app — ouvre-le depuis le menu de gauche.');
          }
          return;
        }
        this.close(overlay);
        App.show(target);
      };
    }
  },

  _esc(s) {
    return String(s).replace(/[&<>"']/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    }[c]));
  },
};
