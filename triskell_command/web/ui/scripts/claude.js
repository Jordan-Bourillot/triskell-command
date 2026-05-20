/* Claude — FAB + dialog Allô Claude
 *
 * Le FAB est dans index.html (animation tailwind 'breathe').
 * On gère ici l'attention (dot rouge + pulse rapide) et le dialog.
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
      background:#ef4444;
      border-color:#dc2626;
      color:#fff;
      animation: claude-mic-pulse 1.2s ease-in-out infinite;
    }
    .claude-mic-btn:disabled { opacity:.4; cursor:not-allowed; }
    @keyframes claude-mic-pulse {
      0%, 100% { box-shadow: 0 0 0 0 rgba(239,68,68,.45); }
      50% { box-shadow: 0 0 0 10px rgba(239,68,68,0); }
    }
    .claude-voice-hint {
      font-size: 11px; color: #ef4444; font-weight:600;
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
      background:#22c55e; border-color:#16a34a; color:#fff;
    }
  `;
  document.head.appendChild(s);
})();

const Claude = {
  isAttention: false,
  pendingAdvice: null,
  _recognition: null,
  _listening: false,

  setAttention(on) {
    this.isAttention = !!on;
    const fab = document.getElementById('claude-fab');
    const dot = document.getElementById('claude-fab-dot');
    const menuDot = document.getElementById('claude-menu-dot');
    if (on) {
      if (fab) {
        fab.classList.remove('animate-breathe');
        fab.classList.add('animate-pulse-fast');
      }
      if (dot) dot.classList.remove('hidden');
      if (menuDot) menuDot.classList.remove('hidden');
    } else {
      if (fab) {
        fab.classList.add('animate-breathe');
        fab.classList.remove('animate-pulse-fast');
      }
      if (dot) dot.classList.add('hidden');
      if (menuDot) menuDot.classList.add('hidden');
    }
  },

  async checkPending() {
    if (!App.api) return;
    try {
      const advice = await App.api.claude_consume_pending();
      if (advice && advice.ok) {
        this.pendingAdvice = advice;
        this.setAttention(true);
      }
    } catch (e) { /* silent */ }
  },

  async open() {
    this.setAttention(false);
    const overlay = this._buildOverlay();
    document.body.appendChild(overlay);
    overlay.querySelector('.modal-card').classList.add('animate-slide-up');

    // Charge le conseil (soit pré-rempli par la veille, soit nouvel appel)
    if (this.pendingAdvice) {
      this._renderAdvice(overlay, this.pendingAdvice);
      this.pendingAdvice = null;
    } else {
      this._renderLoading(overlay);
      if (App.api) {
        try {
          const advice = await App.api.claude_ask({});
          this._renderAdvice(overlay, advice);
        } catch (e) {
          this._renderError(overlay, String(e));
        }
      } else {
        // Mode preview
        setTimeout(() => this._renderAdvice(overlay, {
          ok: true,
          urgency: 'medium',
          headline: 'Tu as 2 prospects intéressés à recontacter aujourd\'hui',
          advice: "C'est ta priorité absolue. Ouvre la vue Réponses, lis ce qu'ils ont écrit, et envoie-leur le brouillon que l'app a préparé en l'adaptant si besoin. Pas plus de 2 heures avant de répondre — au-delà ils refroidissent.",
          suggested_view: 'replies',
          suggested_action_label: 'Voir les réponses',
        }), 600);
      }
    }
  },

  close(overlay) {
    if (!overlay) return;
    // Coupe la dictée et la synthèse vocale si elles tournent
    if (this._recognition) {
      try { this._recognition.stop(); } catch (e) {}
    }
    if (window.speechSynthesis && window.speechSynthesis.speaking) {
      try { window.speechSynthesis.cancel(); } catch (e) {}
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
          <button class="text-text-muted hover:text-text text-2xl leading-none w-8 h-8 shrink-0" id="claude-close">×</button>
        </div>

        <!-- Body -->
        <div id="claude-body" class="flex-1 overflow-y-auto px-5 py-5 sm:px-8 sm:py-8"></div>

        <!-- Footer (question libre) -->
        <div class="px-5 py-4 sm:px-8 sm:py-5 border-t border-border bg-surface-elevated/50">
          <div class="hero-kicker mb-2">OU POSE UNE QUESTION LIBRE</div>
          <div class="flex flex-col sm:flex-row gap-2 items-stretch">
            <button id="claude-mic-btn" type="button" class="claude-mic-btn"
                    title="Parler à Claude (dictée vocale)" aria-label="Dicter ma question">🎤</button>
            <input id="claude-question" type="text"
                   class="flex-1 min-w-0 px-4 py-2.5 text-sm rounded-xl bg-surface border border-border
                          focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent
                          text-text placeholder:text-text-muted"
                   placeholder="ex: comment booster mes réponses cette semaine ?" />
            <button id="claude-ask-free" class="btn btn-primary w-full sm:w-auto justify-center shrink-0">Demander</button>
          </div>
          <div id="claude-voice-hint" class="claude-voice-hint">🔴 J'écoute… (parle, ou clique sur ⏹ pour arrêter)</div>
        </div>
      </div>
    `;

    overlay.querySelector('#claude-close').onclick = () => this.close(overlay);
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) this.close(overlay);
    });
    overlay.querySelector('#claude-ask-free').onclick = async () => {
      const q = overlay.querySelector('#claude-question').value.trim();
      if (!q) return;
      this._renderLoading(overlay);
      if (App.api) {
        try {
          const advice = await App.api.claude_ask({ question: q });
          this._renderAdvice(overlay, advice);
        } catch (e) { this._renderError(overlay, String(e)); }
      }
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
    return overlay;
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
    rec.onerror = () => { try { rec.stop(); } catch (e) {} };
    rec.onend = () => {
      this._listening = false;
      this._recognition = null;
      micBtn.classList.remove('is-listening');
      micBtn.textContent = '🎤';
      micBtn.title = "Parler à Claude (dictée vocale)";
      hint.classList.remove('is-active');
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
      alert("Impossible de démarrer l'écoute. Vérifie que tu as autorisé le micro pour cette page.");
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
    // Essaye de choisir une voix française
    const voices = window.speechSynthesis.getVoices();
    const fr = voices.find(v => v.lang && v.lang.startsWith('fr'));
    if (fr) u.voice = fr;
    u.onend = () => {
      if (btn) {
        btn.classList.remove('is-speaking');
        btn.innerHTML = '🔊 Écouter';
      }
    };
    u.onerror = u.onend;
    if (btn) {
      btn.classList.add('is-speaking');
      btn.innerHTML = '⏹ Stop';
    }
    window.speechSynthesis.speak(u);
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
    body.innerHTML = `
      <div class="text-center py-8">
        <p class="text-danger font-semibold mb-2">Claude n'a pas pu répondre</p>
        <p class="text-sm text-text-muted">${err}</p>
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
    const u = advice.urgency || 'low';

    const speakable = [advice.headline, advice.advice].filter(Boolean).join('. ');
    const canSpeak = this._supportsVoiceOutput() && speakable;

    body.innerHTML = `
      <div class="animate-fade-in">
        <div class="flex items-center gap-2 mb-5">
          <span class="inline-block px-3 py-1 rounded-full text-[10px] font-bold tracking-widest
                       bg-bg ${colors[u]}">
            NIVEAU : ${labels[u].toUpperCase()}
          </span>
          ${canSpeak ? `<button id="claude-speak-btn" type="button" class="claude-speak-btn" title="Faire lire la réponse à voix haute">🔊 Écouter</button>` : ''}
        </div>
        ${advice.headline ? `<h3 class="font-sans text-2xl font-bold mb-4 leading-snug tracking-tight">${this._esc(advice.headline)}</h3>` : ''}
        ${advice.advice ? `<div class="text-text-secondary leading-relaxed whitespace-pre-line mb-6">${this._esc(advice.advice)}</div>` : ''}
        ${advice.suggested_view ? `
          <button class="btn btn-primary"
                  onclick="App.show('${advice.suggested_view}'); document.querySelector('.fixed.inset-0.z-\\[100\\]').remove();">
            ${this._esc(advice.suggested_action_label || 'Y aller')} →
          </button>
        ` : ''}
      </div>
    `;

    if (canSpeak) {
      const speakBtn = body.querySelector('#claude-speak-btn');
      if (speakBtn) speakBtn.onclick = () => this._toggleSpeak(speakable, speakBtn);
    }
  },

  _esc(s) {
    return String(s).replace(/[&<>"']/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    }[c]));
  },
};
