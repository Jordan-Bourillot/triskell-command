/* FocusMode — bouton "Concentration" qui masque temporairement les
 * chiffres et alertes visuelles pour laisser Jordan travailler sereinement.
 * (Les notifications push du téléphone, elles, continuent d'arriver.)
 *
 * Quand activé pour N minutes (15/30/60/120) :
 *   - Masque le bandeau notifs + floute les KPIs anxiogènes du Cockpit
 *     (grille de chiffres + bandeau d'alerte) ; la priorité du jour reste visible
 *   - Affiche un écran plein-écran "Concentration" avec compte à rebours
 *   - "Continuer dans l'app" masque l'écran SANS arrêter la session :
 *     une pastille 🎯 discrète (haut-droite) permet de le ré-afficher,
 *     tout comme le bouton Concentration du Cockpit
 *
 * État persisté en sessionStorage : focus_until (timestamp + intention)
 * → si rechargement de page pendant focus, on garde le mode actif.
 */

const FocusMode = {
  STORAGE_KEY:    'tc-focus-until',
  INTENT_KEY:     'tc-focus-intent',
  STYLE_INJECTED: false,
  _button:        null,

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
    this._paintButton();
  },

  stop() {
    try {
      sessionStorage.removeItem(this.STORAGE_KEY);
      sessionStorage.removeItem(this.INTENT_KEY);
    } catch (e) {}
    this.hideOverlay();
    this._paintButton();
  },

  // ----- Bouton "Concentration" du Cockpit : état armé visible -----
  bindButton(btn) {
    if (!btn) return;
    this._button = btn;
    if (!btn.dataset.focusOriginal) {
      btn.dataset.focusOriginal = btn.innerHTML;
    }
    this._injectStyles();
    this._paintButton();
  },

  _paintButton() {
    let btn = this._button;
    if (!btn || !document.body.contains(btn)) {
      btn = document.getElementById('m-focus');
      if (btn) this._button = btn;
    }
    if (!btn) return;

    if (this.isOn()) {
      const remaining = Math.max(0, this.getEndsAt() - Date.now());
      const totalMins = Math.ceil(remaining / 60_000);
      const label = totalMins >= 60
        ? `${Math.floor(totalMins / 60)} h ${String(totalMins % 60).padStart(2, '0')}`
        : `${totalMins} min`;
      btn.classList.add('is-focus-active');
      btn.innerHTML = `
        <span class="focus-btn-dot" aria-hidden="true"></span>
        <span>Concentration</span>
        <span class="focus-btn-time">· ${label}</span>
      `;
      btn.title = `Concentration en cours — encore ${label}. Cliquer pour réafficher l’écran Concentration.`;
      btn.setAttribute('aria-pressed', 'true');
    } else {
      btn.classList.remove('is-focus-active');
      if (btn.dataset.focusOriginal) btn.innerHTML = btn.dataset.focusOriginal;
      btn.title = 'Mode Concentration';
      btn.setAttribute('aria-pressed', 'false');
    }
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

      /* Pastille flottante quand l'écran Concentration est masqué :
         rappelle la session en cours, clic = ré-affiche l'écran. */
      #focus-pill {
        position: fixed;
        top: 14px; right: 16px;
        z-index: 9991;
        display: inline-flex; align-items: center; gap: 6px;
        padding: 8px 14px;
        border-radius: 999px;
        background: hsl(var(--surface-elevated));
        border: 1px solid hsl(var(--accent) / 0.45);
        color: hsl(var(--text));
        font-size: 12px; font-weight: 700;
        font-variant-numeric: tabular-nums;
        cursor: pointer;
        box-shadow: 0 6px 18px hsl(var(--accent) / 0.18);
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      }
      #focus-pill:hover { border-color: hsl(var(--accent) / 0.8); }
      #focus-pill:focus-visible { outline: 2px solid hsl(var(--accent)); outline-offset: 2px; }

      /* Quand mode focus actif, masque le bandeau notif et floute les
         chiffres du Cockpit. Sélecteurs par CLASSE (pas par position
         nth-child, fragile) : si les blocs n'existent pas, rien ne casse. */
      body.is-focus-mode #push-toggle-row { display: none !important; }
      body.is-focus-mode #m-content .cockpit-grid,
      body.is-focus-mode #m-content .cockpit-alert {
        opacity: 0.25; filter: blur(2px); transition: opacity 300ms, filter 300ms;
        pointer-events: none;
      }

      /* Bouton "Concentration" — état armé (focus mode ON) */
      .btn.is-focus-active {
        background: hsl(var(--accent) / 0.14) !important;
        border-color: hsl(var(--accent) / 0.55) !important;
        color: hsl(var(--accent)) !important;
        box-shadow: 0 0 0 1px hsl(var(--accent) / 0.15), 0 4px 14px hsl(var(--accent) / 0.18);
      }
      .btn.is-focus-active:hover {
        background: hsl(var(--accent) / 0.22) !important;
        border-color: hsl(var(--accent) / 0.75) !important;
      }
      .btn.is-focus-active svg { color: hsl(var(--accent)); }
      .focus-btn-dot {
        display: inline-block;
        width: 9px; height: 9px;
        border-radius: 50%;
        background: hsl(var(--success));
        margin-right: 2px;
        box-shadow: 0 0 0 0 hsl(var(--success) / 0.6);
        animation: focus-btn-pulse 1.8s ease-in-out infinite;
        vertical-align: middle;
        position: relative;
        top: -1px;
      }
      @keyframes focus-btn-pulse {
        0%, 100% { box-shadow: 0 0 0 0 hsl(var(--success) / 0.55); }
        50%      { box-shadow: 0 0 0 7px hsl(var(--success) / 0); }
      }
      .focus-btn-time {
        font-variant-numeric: tabular-nums;
        font-weight: 600;
        opacity: 0.9;
        margin-left: 2px;
      }
    `;
    document.head.appendChild(s);
  },

  showOverlay() {
    this._injectStyles();
    document.body.classList.add('is-focus-mode');
    this._removePill();
    const existing = document.getElementById('focus-overlay');
    if (existing) {
      // L'écran avait été masqué par "Continuer dans l'app" → on le ré-affiche
      existing.style.display = '';
      this._render();
      return;
    }
    const ov = document.createElement('div');
    ov.id = 'focus-overlay';
    ov.innerHTML = `
      <div class="focus-kicker">CONCENTRATION</div>
      <div class="focus-intent" id="focus-intent-text"></div>
      <div class="focus-timer" id="focus-timer-text">--:--</div>
      <div class="focus-actions">
        <button id="focus-continue" class="focus-btn">Continuer dans l’app</button>
        <button id="focus-extend" class="focus-btn">+ 15 minutes</button>
        <button id="focus-stop" class="focus-btn focus-btn--danger">Sortir du mode</button>
      </div>
    `;
    document.body.appendChild(ov);
    // Masque l'écran SANS arrêter la session (pastille 🎯 pour le ré-afficher)
    ov.querySelector('#focus-continue').onclick = () => this.maskOverlay();
    ov.querySelector('#focus-extend').onclick = () => {
      const newUntil = (this.getEndsAt() || Date.now()) + 15 * 60_000;
      try { sessionStorage.setItem(this.STORAGE_KEY, String(newUntil)); } catch (e) {}
      this._render();
    };
    // Sortie directe ; confirmation seulement s'il reste plus de 10 minutes
    ov.querySelector('#focus-stop').onclick = async () => {
      const remaining = Math.max(0, this.getEndsAt() - Date.now());
      if (remaining > 10 * 60_000 && typeof Dialog !== 'undefined' && Dialog.confirm) {
        const confirmPromise = Dialog.confirm(
          `Il reste ${Math.ceil(remaining / 60_000)} min de concentration. Sortir quand même ?`,
          { title: 'Mode Concentration', okLabel: 'Sortir', cancelLabel: 'Continuer' }
        );
        // La boîte de confirmation vit normalement SOUS cet écran plein
        // (z-index 940 < 9990) : on la fait passer au-dessus, sinon elle
        // serait invisible et le bouton semblerait mort.
        const dlg = document.getElementById('tc-dialog-overlay');
        if (dlg) dlg.style.zIndex = '10001';
        const ok = await confirmPromise;
        if (!ok) return;
      }
      this.stop();
    };
    this._render();
    if (!this._tickInterval) {
      this._tickInterval = setInterval(() => this._render(), 1000);
    }
  },

  /** Masque l'écran Concentration sans arrêter la session :
   *  les chiffres restent floutés, et une pastille discrète en haut à
   *  droite permet de ré-afficher l'écran à tout moment. */
  maskOverlay() {
    const ov = document.getElementById('focus-overlay');
    if (ov) ov.style.display = 'none';
    this._showPill();
  },

  _showPill() {
    if (document.getElementById('focus-pill')) return;
    const pill = document.createElement('button');
    pill.id = 'focus-pill';
    pill.type = 'button';
    pill.title = 'Concentration en cours — cliquer pour ré-afficher l’écran';
    pill.setAttribute('aria-label', 'Ré-afficher l’écran Concentration');
    pill.innerHTML = '<span aria-hidden="true">🎯</span><span class="focus-pill-time">--</span>';
    pill.onclick = () => this.showOverlay();
    document.body.appendChild(pill);
    this._updatePill();
  },

  _removePill() {
    const pill = document.getElementById('focus-pill');
    if (pill) pill.remove();
  },

  _updatePill() {
    const t = document.querySelector('#focus-pill .focus-pill-time');
    if (!t) return;
    const remaining = Math.max(0, this.getEndsAt() - Date.now());
    const mins = Math.ceil(remaining / 60_000);
    t.textContent = mins >= 60
      ? `${Math.floor(mins / 60)} h ${String(mins % 60).padStart(2, '0')}`
      : `${mins} min`;
  },

  hideOverlay() {
    document.body.classList.remove('is-focus-mode');
    this._removePill();
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
    this._updatePill();
    this._paintButton();
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
    ov.style.background = 'hsl(var(--bg) / 0.78)';
    ov.style.backdropFilter = 'blur(10px)';
    ov.innerHTML = `
      <div class="bg-surface rounded-2xl shadow-hero w-full max-w-md border border-border animate-slide-up flex flex-col overflow-hidden">
        <div class="px-6 pt-5 pb-3 border-b border-border bg-surface-elevated flex items-start justify-between">
          <div>
            <div class="text-[11px] font-bold uppercase tracking-widest text-text-muted mb-0.5">MODE CONCENTRATION</div>
            <h3 class="text-lg font-bold">Sur quoi tu te concentres ?</h3>
            <p class="text-xs text-text-muted mt-1">Les chiffres et alertes visuelles sont masqués. Les notifications du téléphone continuent d'arriver.</p>
          </div>
          <button id="fs-close" title="Fermer" aria-label="Fermer" class="w-8 h-8 rounded-lg flex items-center justify-center text-text-muted hover:text-text hover:bg-bg text-xl leading-none shrink-0">×</button>
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
                  <div class="text-[11px] text-text-muted">min</div>
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
