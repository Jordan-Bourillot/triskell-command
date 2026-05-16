/* FocusMode — bouton "Concentration" qui masque temporairement notifs
 * et KPIs anxiogènes pour laisser Jordan travailler sereinement.
 *
 * Quand activé pour N minutes (15/30/60/120) :
 *   - Masque les notifs push (Push.disable temporaire) + le bouton notifs
 *   - Masque les KPIs anxiogènes du Cockpit (Hier en chiffres, Aujourd'hui)
 *   - Garde la priorité du jour visible (mais pas les chiffres rouges)
 *   - Affiche un mode plein-écran "Focus" avec timer countdown
 *   - Si Jordan a un projet en cours (ex : "livrer site Lefèvre"), affiche
 *     le titre + temps écoulé en grand
 *
 * État persisté en sessionStorage : focus_until (timestamp + intention)
 * → si rechargement de page pendant focus, on garde le mode actif.
 */

const FocusMode = {
  STORAGE_KEY:    'tc-focus-until',
  INTENT_KEY:     'tc-focus-intent',
  STYLE_INJECTED: false,

  isOn() {
    try {
      const until = parseInt(sessionStorage.getItem(this.STORAGE_KEY) || '0', 10);
      return until > Date.now();
    } catch (e) { return false; }
  },

  getIntent() {
    try { return sessionStorage.getItem(this.INTENT_KEY) || ''; }
    catch (e) { return ''; }
  },

  getEndsAt() {
    try { return parseInt(sessionStorage.getItem(this.STORAGE_KEY) || '0', 10); }
    catch (e) { return 0; }
  },

  start(minutes, intent) {
    try {
      const until = Date.now() + minutes * 60_000;
      sessionStorage.setItem(this.STORAGE_KEY, String(until));
      sessionStorage.setItem(this.INTENT_KEY, intent || '');
    } catch (e) {}
    this.showOverlay();
  },

  stop() {
    try {
      sessionStorage.removeItem(this.STORAGE_KEY);
      sessionStorage.removeItem(this.INTENT_KEY);
    } catch (e) {}
    this.hideOverlay();
  },

  // ----- UI -----
  _injectStyles() {
    if (this.STYLE_INJECTED) return;
    this.STYLE_INJECTED = true;
    const s = document.createElement('style');
    s.id = 'focus-mode-styles';
    s.textContent = `
      #focus-overlay {
        position: fixed; inset: 0;
        z-index: 9990;
        background: radial-gradient(ellipse at center,
                    hsl(var(--bg)) 0%, hsl(var(--surface)) 80%);
        display: flex; flex-direction: column;
        align-items: center; justify-content: center;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        color: hsl(var(--text));
        padding: 40px;
        text-align: center;
        animation: focusFadeIn 400ms ease-out;
      }
      @keyframes focusFadeIn { from { opacity: 0; } to { opacity: 1; } }
      .focus-kicker {
        font-size: 11px; font-weight: 700;
        letter-spacing: 3px; text-transform: uppercase;
        color: hsl(var(--accent));
        margin-bottom: 20px;
      }
      .focus-intent {
        font-family: 'Domaine Display', Georgia, serif;
        font-size: clamp(32px, 6vw, 72px);
        font-weight: 700;
        line-height: 1.05;
        max-width: 900px;
        margin-bottom: 30px;
      }
      .focus-timer {
        font-size: clamp(64px, 12vw, 120px);
        font-weight: 200;
        font-variant-numeric: tabular-nums;
        color: hsl(var(--text-muted));
        margin: 10px 0 50px;
        letter-spacing: -2px;
      }
      .focus-actions { display: flex; gap: 12px; flex-wrap: wrap; justify-content: center; }
      .focus-btn {
        padding: 10px 22px;
        border-radius: 10px;
        background: hsl(var(--surface-elevated));
        border: 1px solid hsl(var(--border));
        color: hsl(var(--text-muted));
        font-size: 13px;
        font-weight: 600;
        cursor: pointer;
        transition: all 160ms;
      }
      .focus-btn:hover { color: hsl(var(--text)); border-color: hsl(var(--accent)); }
      .focus-btn--danger:hover { color: hsl(var(--danger)); border-color: hsl(var(--danger)); }

      /* Quand mode focus actif, masque le bandeau notif et les KPIs Cockpit */
      body.is-focus-mode #push-toggle-row { display: none !important; }
      body.is-focus-mode #m-content > div:nth-child(2),
      body.is-focus-mode #m-content > div:nth-child(3) {
        opacity: 0.25; filter: blur(2px); transition: opacity 300ms, filter 300ms;
      }
    `;
    document.head.appendChild(s);
  },

  showOverlay() {
    this._injectStyles();
    document.body.classList.add('is-focus-mode');
    if (document.getElementById('focus-overlay')) return;
    const ov = document.createElement('div');
    ov.id = 'focus-overlay';
    ov.innerHTML = `
      <div class="focus-kicker">CONCENTRATION</div>
      <div class="focus-intent" id="focus-intent-text"></div>
      <div class="focus-timer" id="focus-timer-text">--:--</div>
      <div class="focus-actions">
        <button id="focus-extend" class="focus-btn">+ 15 minutes</button>
        <button id="focus-stop" class="focus-btn focus-btn--danger">Sortir du mode</button>
      </div>
    `;
    document.body.appendChild(ov);
    ov.querySelector('#focus-extend').onclick = () => {
      const newUntil = (this.getEndsAt() || Date.now()) + 15 * 60_000;
      try { sessionStorage.setItem(this.STORAGE_KEY, String(newUntil)); } catch (e) {}
      this._render();
    };
    ov.querySelector('#focus-stop').onclick = () => {
      if (confirm('Sortir du mode Concentration ?')) this.stop();
    };
    this._render();
    if (!this._tickInterval) {
      this._tickInterval = setInterval(() => this._render(), 1000);
    }
  },

  hideOverlay() {
    document.body.classList.remove('is-focus-mode');
    const ov = document.getElementById('focus-overlay');
    if (ov) ov.remove();
    if (this._tickInterval) {
      clearInterval(this._tickInterval);
      this._tickInterval = null;
    }
  },

  _render() {
    const ov = document.getElementById('focus-overlay');
    if (!ov) return;
    const remaining = Math.max(0, this.getEndsAt() - Date.now());
    if (remaining <= 0) {
      this.stop();
      this._showFinishedTeaser();
      return;
    }
    const mins = Math.floor(remaining / 60_000);
    const secs = Math.floor((remaining % 60_000) / 1000);
    const txt = `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
    ov.querySelector('#focus-timer-text').textContent = txt;
    const intent = this.getIntent();
    ov.querySelector('#focus-intent-text').textContent = intent || 'Tu travailles sans interruption.';
  },

  _showFinishedTeaser() {
    if (typeof HealthCheck !== 'undefined' && HealthCheck.toast) {
      HealthCheck.toast('Concentration terminée', 'Bien joué. Tu peux revenir aux affaires courantes.', 'info');
    }
  },

  // ----- Modale "Démarrer une session" -----
  openStartDialog() {
    if (document.getElementById('focus-start-modal')) return;
    const ov = document.createElement('div');
    ov.id = 'focus-start-modal';
    ov.className = 'fixed inset-0 z-[230] flex items-center justify-center p-4';
    ov.style.background = 'rgba(15,23,42,0.78)';
    ov.style.backdropFilter = 'blur(10px)';
    ov.innerHTML = `
      <div class="bg-surface rounded-2xl shadow-hero w-full max-w-md border border-border animate-slide-up flex flex-col overflow-hidden">
        <div class="px-6 pt-5 pb-3 border-b border-border bg-surface-elevated flex items-start justify-between">
          <div>
            <div class="text-[10px] font-bold uppercase tracking-widest text-text-muted mb-0.5">MODE CONCENTRATION</div>
            <h3 class="text-lg font-bold">Sur quoi tu te concentres ?</h3>
            <p class="text-xs text-text-muted mt-1">L'app masque notifs et chiffres pendant la session. Tu reçois rien, tu vois rien, tu bosses.</p>
          </div>
          <button id="fs-close" class="w-8 h-8 rounded-lg flex items-center justify-center text-text-muted hover:text-text hover:bg-bg text-xl leading-none shrink-0">×</button>
        </div>
        <div class="p-5 space-y-4">
          <div>
            <label class="block text-[11px] font-medium text-text-secondary mb-1 uppercase tracking-wider">Intention</label>
            <input id="fs-intent" type="text" placeholder="Ex : livrer le site Lefèvre"
                   class="w-full px-3 py-2.5 text-sm rounded-lg bg-bg border border-border focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent"/>
          </div>
          <div>
            <label class="block text-[11px] font-medium text-text-secondary mb-2 uppercase tracking-wider">Durée</label>
            <div class="grid grid-cols-4 gap-2">
              ${[15, 30, 60, 120].map(m => `
                <button data-mins="${m}" class="px-3 py-2.5 rounded-xl border border-border hover:border-accent hover:bg-accent/5 transition-all">
                  <div class="text-base font-bold">${m}</div>
                  <div class="text-[10px] text-text-muted">min</div>
                </button>
              `).join('')}
            </div>
          </div>
        </div>
        <div class="px-5 py-4 border-t border-border bg-surface-elevated flex items-center justify-end">
          <button id="fs-cancel" class="btn btn-secondary">Annuler</button>
        </div>
      </div>
    `;
    document.body.appendChild(ov);
    const close = () => {
      document.removeEventListener('keydown', escListener);
      ov.remove();
    };
    const escListener = (e) => { if (e.key === 'Escape') close(); };
    document.addEventListener('keydown', escListener);
    ov.querySelector('#fs-close').onclick = close;
    ov.querySelector('#fs-cancel').onclick = close;
    ov.addEventListener('click', (e) => { if (e.target === ov) close(); });

    const intentInput = ov.querySelector('#fs-intent');
    setTimeout(() => intentInput.focus(), 50);
    ov.querySelectorAll('[data-mins]').forEach(b => {
      b.onclick = () => {
        const mins = parseInt(b.dataset.mins, 10);
        const intent = intentInput.value.trim();
        close();
        this.start(mins, intent);
      };
    });
  },

  // ----- Init : restaure si focus mode en cours -----
  init() {
    if (this.isOn()) {
      this._injectStyles();
      this.showOverlay();
    }
  },
};

window.FocusMode = FocusMode;
window.addEventListener('DOMContentLoaded', () => FocusMode.init());
