/* MusicPlayer — petit lecteur de musique flottant.
 *
 * Comportement :
 * - Au boot, charge /audio/playlist.json (liste de morceaux).
 * - Le panneau s'ouvre via le bouton "Musique" du Cockpit (morning.js).
 * - Quand une musique JOUE et que le panneau est fermé : un mini-bouton
 *   rond ♪ apparaît en bas à gauche pour rouvrir le panneau de partout.
 * - Lecture / pause / précédent / suivant, barre cliquable (et au clavier
 *   ←/→ ±5 s) pour se déplacer dans le morceau.
 * - Volume réglable, persisté en localStorage.
 * - Dernière piste + position de lecture + état d'ouverture mémorisés
 *   entre sessions (position sauvée toutes les 10 s et à la pause).
 * - Morceau introuvable → message + passage auto au suivant (stop après
 *   un tour complet si tous les fichiers sont cassés).
 * - Si la playlist est vide → message d'aide, boutons désactivés.
 *
 * Ajout d'un morceau (dev) :
 *   1. Glisser le fichier MP3 dans /audio/
 *   2. Ajouter une entrée dans /audio/playlist.json :
 *      { "title": "...", "artist": "...", "file": "monfichier.mp3" }
 */

const MusicPlayer = {
  _stylesInjected: false,
  _audio: null,
  _playlist: [],
  _idx: 0,
  _volume: 0.5,
  _expanded: false,
  _ui: null,
  _miniFab: null,
  _savedPos: null,     // { pos, file } restauré du localStorage (consommé au 1er chargement)
  _resumePos: null,    // position à appliquer au prochain loadedmetadata
  _errSkips: 0,        // morceaux cassés enchaînés (anti boucle infinie)
  _wantsPlay: false,   // l'utilisateur veut que ça joue (pilote l'enchaînement après erreur)

  STORAGE: 'tc-music-player',

  async init() {
    this._injectStyles();
    this._loadState();
    await this._loadPlaylist();
    this._render();
    this._setupAudio();
    // Sauvegarde périodique de la position de lecture (toutes les 10 s quand ça joue)
    setInterval(() => {
      if (this._audio && !this._audio.paused) this._saveState();
    }, 10_000);
  },

  async _loadPlaylist() {
    try {
      const resp = await fetch('/audio/playlist.json?_=' + Date.now());
      const data = await resp.json();
      this._playlist = Array.isArray(data && data.tracks) ? data.tracks : [];
    } catch (e) {
      this._playlist = [];
    }
    // Garde-fou : si _idx pointe au-delà de la playlist (track supprimé)
    if (this._idx >= this._playlist.length) this._idx = 0;
  },

  _loadState() {
    try {
      const s = JSON.parse(localStorage.getItem(this.STORAGE) || '{}');
      this._idx = Number.isFinite(s.idx) ? s.idx : 0;
      this._volume = Number.isFinite(s.volume) ? s.volume : 0.5;
      this._expanded = !!s.expanded;
      // Position de lecture mémorisée (restaurée si on recharge la même piste)
      if (Number.isFinite(s.pos) && s.pos > 0 && s.posFile) {
        this._savedPos = { pos: s.pos, file: s.posFile };
      }
    } catch (e) {
      this._idx = 0; this._volume = 0.5; this._expanded = false;
    }
  },

  /** Position de lecture à persister (live si l'audio joue, sinon la
   *  dernière connue pas encore consommée). */
  _posSnapshot() {
    if (this._audio && this._audio.currentTime > 0 && this._playlist[this._idx]) {
      return { pos: Math.floor(this._audio.currentTime), posFile: this._playlist[this._idx].file || '' };
    }
    if (this._savedPos) return { pos: this._savedPos.pos, posFile: this._savedPos.file };
    return { pos: 0, posFile: '' };
  },

  _saveState(posOverride) {
    try {
      const p = posOverride || this._posSnapshot();
      localStorage.setItem(this.STORAGE, JSON.stringify({
        idx: this._idx,
        volume: this._volume,
        expanded: this._expanded,
        pos: p.pos,
        posFile: p.posFile,
      }));
    } catch (e) { /* ignore */ }
  },

  _esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    }[c]));
  },

  _currentTrack() {
    return this._playlist[this._idx] || null;
  },

  _currentTitle() {
    if (!this._playlist.length) return 'Aucune musique';
    return this._currentTrack()?.title || 'Sans titre';
  },

  _currentArtist() {
    return this._currentTrack()?.artist || '';
  },

  _fmtTime(s) {
    if (!isFinite(s) || s < 0) return '0:00';
    const m = Math.floor(s / 60);
    const sec = Math.floor(s % 60);
    return m + ':' + String(sec).padStart(2, '0');
  },

  _render() {
    const root = document.createElement('div');
    root.id = 'music-player';
    root.className = 'music-player' + (this._expanded ? ' is-expanded' : '');
    root.innerHTML = `
      <button class="music-player-toggle" title="Lecteur de musique" aria-label="Ouvrir le lecteur">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M9 18V5l12-2v13"/>
          <circle cx="6" cy="18" r="3"/>
          <circle cx="18" cy="16" r="3"/>
        </svg>
      </button>
      <div class="music-player-panel" role="region" aria-label="Lecteur de musique">
        <div class="music-player-header">
          <div class="music-player-track">
            <div class="music-player-title">${this._esc(this._currentTitle())}</div>
            <div class="music-player-artist">${this._esc(this._currentArtist())}</div>
          </div>
          <button class="mp-btn mp-close" title="Réduire" aria-label="Réduire">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="5" y1="12" x2="19" y2="12"/></svg>
          </button>
        </div>
        <div class="music-player-progress">
          <div class="music-player-progress-bar" role="slider" tabindex="0"
               aria-label="Position dans le morceau (flèches gauche/droite : 5 secondes)"
               aria-valuemin="0" aria-valuemax="100" aria-valuenow="0">
            <div class="music-player-progress-fill"></div>
          </div>
          <div class="music-player-times">
            <span class="time-current">0:00</span>
            <span class="time-total">—:—</span>
          </div>
        </div>
        <div class="music-player-controls">
          <button class="mp-btn mp-prev" title="Précédent" aria-label="Morceau précédent" ${this._playlist.length === 0 ? 'disabled' : ''}>
            <svg viewBox="0 0 24 24" fill="currentColor"><path d="M6 6h2v12H6zM9.5 12l8.5 6V6z"/></svg>
          </button>
          <button class="mp-btn mp-play" title="Lecture / pause" aria-label="Lecture ou pause" ${this._playlist.length === 0 ? 'disabled' : ''}>
            <svg class="mp-icon-play" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
            <svg class="mp-icon-pause hidden" viewBox="0 0 24 24" fill="currentColor"><path d="M6 4h4v16H6zm8 0h4v16h-4z"/></svg>
          </button>
          <button class="mp-btn mp-next" title="Suivant" aria-label="Morceau suivant" ${this._playlist.length === 0 ? 'disabled' : ''}>
            <svg viewBox="0 0 24 24" fill="currentColor"><path d="M16 6h2v12h-2zM6 18l8.5-6L6 6z"/></svg>
          </button>
          <div class="mp-volume">
            <svg viewBox="0 0 24 24" fill="currentColor"><path d="M3 9v6h4l5 5V4L7 9H3z"/></svg>
            <input type="range" min="0" max="100" value="${Math.round(this._volume * 100)}" class="mp-volume-slider" aria-label="Volume"/>
          </div>
        </div>
        ${this._playlist.length === 0 ? `
          <div class="music-player-empty">
            <p><strong>Aucune musique pour l'instant</strong> — demande à Claude d'ajouter tes morceaux.</p>
          </div>
        ` : ''}
      </div>
    `;
    document.body.appendChild(root);
    this._ui = root;

    // Mini-bouton flottant ♪ (bas-gauche) : visible UNIQUEMENT quand une
    // musique joue et que le panneau est fermé. Clic = rouvre le panneau.
    const fab = document.createElement('button');
    fab.id = 'music-mini-fab';
    fab.type = 'button';
    fab.title = 'Musique en cours — rouvrir le lecteur';
    fab.setAttribute('aria-label', 'Musique en cours — rouvrir le lecteur');
    fab.textContent = '♪';
    fab.onclick = () => this._toggleExpanded(true);
    document.body.appendChild(fab);
    this._miniFab = fab;
    this._updateMiniFab();

    // Bindings
    root.querySelector('.music-player-toggle').onclick = () => this._toggleExpanded();
    root.querySelector('.mp-close').onclick = () => this._toggleExpanded(false);
    root.querySelector('.mp-play').onclick = () => this._togglePlay();
    root.querySelector('.mp-prev').onclick = () => this._prev();
    root.querySelector('.mp-next').onclick = () => this._next();

    const volSlider = root.querySelector('.mp-volume-slider');
    volSlider.oninput = () => {
      this._volume = Math.max(0, Math.min(1, volSlider.value / 100));
      if (this._audio) this._audio.volume = this._volume;
      this._saveState();
    };

    // Seek : clic sur la barre, ou flèches ←/→ (±5 s) quand elle a le focus
    const bar = root.querySelector('.music-player-progress-bar');
    bar.onclick = (e) => {
      if (!this._audio || !this._audio.duration) return;
      const r = bar.getBoundingClientRect();
      const pct = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width));
      this._audio.currentTime = pct * this._audio.duration;
    };
    bar.onkeydown = (e) => {
      if (!this._audio || !this._audio.duration) return;
      if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
        e.preventDefault();
        const delta = e.key === 'ArrowLeft' ? -5 : 5;
        this._audio.currentTime = Math.max(0, Math.min(this._audio.duration, this._audio.currentTime + delta));
        this._updateProgress();
      }
    };
  },

  /** Affiche/masque le mini-bouton ♪ selon l'état (lecture + panneau fermé). */
  _updateMiniFab() {
    if (!this._miniFab) return;
    const playing = !!(this._audio && !this._audio.paused);
    this._miniFab.classList.toggle('is-visible', playing && !this._expanded);
  },

  _setupAudio() {
    if (this._playlist.length === 0) return;
    this._audio = new Audio();
    this._audio.preload = 'metadata';
    this._audio.volume = this._volume;
    this._audio.addEventListener('timeupdate', () => this._updateProgress());
    this._audio.addEventListener('loadedmetadata', () => {
      // Restauration de la position mémorisée (même piste uniquement)
      if (this._resumePos != null && isFinite(this._audio.duration)) {
        this._audio.currentTime = Math.min(this._resumePos, Math.max(0, this._audio.duration - 1));
        this._resumePos = null;
      }
      this._savedPos = null; // consommée : on repart sur la position live
      this._updateProgress();
    });
    this._audio.addEventListener('canplay', () => { this._errSkips = 0; });
    this._audio.addEventListener('error', () => this._onAudioError());
    this._audio.addEventListener('ended', () => this._next(true));
    this._audio.addEventListener('play', () => {
      this._wantsPlay = true;
      this._updatePlayButton();
    });
    this._audio.addEventListener('pause', () => {
      this._updatePlayButton();
      this._saveState(); // mémorise la position à la pause
    });
    this._loadTrack(this._idx, false);
  },

  /** Fichier audio cassé/introuvable : on prévient et on passe au suivant.
   *  Garde-fou : si TOUS les morceaux sont cassés, on s'arrête après un
   *  tour complet de la playlist (pas de boucle infinie). */
  _onAudioError() {
    if (!this._playlist.length) return;
    this._errSkips += 1;
    if (this._errSkips >= this._playlist.length) {
      this._errSkips = 0;
      this._wantsPlay = false;
      if (window.Toast) Toast.error('Aucun morceau ne peut être lu — les fichiers audio semblent manquants.');
      this._updatePlayButton();
      return;
    }
    if (window.Toast) Toast.warn('Morceau introuvable — passage au suivant.');
    this._next(this._wantsPlay);
  },

  _loadTrack(idx, autoplay) {
    if (!this._audio || !this._playlist[idx]) return;
    this._idx = idx;
    const track = this._playlist[idx];
    // Position mémorisée à restaurer ? (seulement si c'est la même piste)
    this._resumePos = (this._savedPos && this._savedPos.file === track.file && this._savedPos.pos > 3)
      ? this._savedPos.pos
      : null;
    this._audio.src = '/audio/' + encodeURIComponent(track.file || '');
    this._updateTrackInfo();
    // Position explicite (pas de lecture "live" pendant le changement de
    // piste, le temps affiché peut encore être celui de l'ancien morceau)
    this._saveState({ pos: this._resumePos || 0, posFile: track.file || '' });
    if (autoplay) {
      this._wantsPlay = true;
      const p = this._audio.play();
      if (p && p.catch) p.catch((err) => this._onPlayBlocked(err));
    }
  },

  /** play() refusé : si c'est l'anti-autoplay du navigateur, on guide
   *  discrètement. (Les fichiers cassés passent par le listener 'error'.) */
  _onPlayBlocked(err) {
    if (err && err.name === 'NotAllowedError' && window.Toast) {
      Toast.info('Clique lecture pour démarrer.');
    }
  },

  _togglePlay() {
    if (!this._audio || !this._playlist.length) return;
    if (this._audio.paused) {
      this._wantsPlay = true;
      const p = this._audio.play();
      if (p && p.catch) p.catch((err) => this._onPlayBlocked(err));
    } else {
      this._wantsPlay = false;
      this._audio.pause();
    }
  },

  _prev() {
    if (!this._playlist.length) return;
    let i = this._idx - 1;
    if (i < 0) i = this._playlist.length - 1;
    this._loadTrack(i, true);
  },

  _next(autoplay = true) {
    if (!this._playlist.length) return;
    let i = this._idx + 1;
    if (i >= this._playlist.length) i = 0;
    this._loadTrack(i, autoplay);
  },

  _toggleExpanded(state) {
    this._expanded = state === undefined ? !this._expanded : !!state;
    if (this._ui) this._ui.classList.toggle('is-expanded', this._expanded);
    this._updateMiniFab();
    this._saveState();
  },

  _updateProgress() {
    if (!this._audio || !this._ui) return;
    const fill = this._ui.querySelector('.music-player-progress-fill');
    const tCur = this._ui.querySelector('.time-current');
    const tTot = this._ui.querySelector('.time-total');
    const bar = this._ui.querySelector('.music-player-progress-bar');
    const dur = this._audio.duration || 0;
    const cur = this._audio.currentTime || 0;
    const pct = dur ? Math.round(cur / dur * 100) : 0;
    if (fill) fill.style.width = pct + '%';
    if (tCur) tCur.textContent = this._fmtTime(cur);
    if (tTot) tTot.textContent = this._fmtTime(dur);
    if (bar) {
      bar.setAttribute('aria-valuenow', String(pct));
      bar.setAttribute('aria-valuetext', `${this._fmtTime(cur)} sur ${this._fmtTime(dur)}`);
    }
  },

  _updateTrackInfo() {
    if (!this._ui) return;
    const title = this._ui.querySelector('.music-player-title');
    const artist = this._ui.querySelector('.music-player-artist');
    if (title) title.textContent = this._currentTitle();
    if (artist) artist.textContent = this._currentArtist();
  },

  _updatePlayButton() {
    this._updateMiniFab();
    if (!this._ui) return;
    const playIcon = this._ui.querySelector('.mp-icon-play');
    const pauseIcon = this._ui.querySelector('.mp-icon-pause');
    if (!playIcon || !pauseIcon) return;
    if (this._audio && !this._audio.paused) {
      playIcon.classList.add('hidden');
      pauseIcon.classList.remove('hidden');
    } else {
      playIcon.classList.remove('hidden');
      pauseIcon.classList.add('hidden');
    }
  },

  _injectStyles() {
    if (this._stylesInjected) return;
    this._stylesInjected = true;
    const s = document.createElement('style');
    s.id = 'music-player-styles';
    s.textContent = `
      .music-player {
        position: fixed;
        left: 16px;
        bottom: 16px;
        z-index: 55; /* au-dessus de la sidebar (z-50) pour rester visible sur mobile drawer */
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      }
      /* Desktop : ancré au-dessus du FAB Thomas (right:32 / bottom:116 / w:56)
         pour ne pas le masquer quand le panneau du lecteur s'ouvre. */
      @media (min-width: 768px) {
        .music-player { left: auto; right: 38px; bottom: 188px; }
      }
      @media (max-width: 767px) {
        .music-player { left: 12px; bottom: max(12px, env(safe-area-inset-bottom, 12px)); }
      }
      /* Le rond flottant est désactivé — c'est maintenant le bouton
         "Musique" de la barre du Cockpit qui ouvre le panneau (voir
         morning.js). On garde le markup pour la cohérence du JS mais
         on n'affiche jamais le toggle. */
      .music-player-toggle { display: none; }
      .music-player-panel {
        display: none;
        width: 320px;
        max-width: calc(100vw - 24px);
        padding: 16px;
        background: hsl(var(--surface-elevated));
        border: 1px solid hsl(var(--border));
        border-radius: 14px;
        box-shadow: 0 16px 40px rgba(0,0,0,0.22);
      }
      /* Mini-bouton flottant ♪ — visible seulement musique en cours + panneau fermé */
      #music-mini-fab {
        position: fixed;
        left: 16px;
        bottom: max(16px, env(safe-area-inset-bottom, 16px));
        z-index: 56;
        width: 44px; height: 44px;
        border-radius: 50%;
        border: 1px solid hsl(var(--border));
        background: hsl(var(--accent-strong));
        color: hsl(var(--on-accent));
        font-size: 19px;
        line-height: 1;
        display: none;
        align-items: center; justify-content: center;
        cursor: pointer;
        box-shadow: 0 8px 22px hsl(var(--accent-strong) / 0.35);
      }
      #music-mini-fab.is-visible { display: inline-flex; }
      #music-mini-fab:hover { background: hsl(var(--accent-strong-hover)); }
      #music-mini-fab:focus-visible { outline: 2px solid hsl(var(--accent)); outline-offset: 2px; }
      .music-player.is-expanded .music-player-panel { display: block; }
      .music-player-header {
        display: flex; align-items: flex-start; gap: 8px;
        margin-bottom: 14px;
      }
      .music-player-track { flex: 1; min-width: 0; }
      .music-player-title {
        font-size: 14px; font-weight: 700; color: hsl(var(--text));
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        line-height: 1.3;
      }
      .music-player-artist {
        font-size: 12px; color: hsl(var(--text-muted));
        margin-top: 2px;
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
      }
      .music-player-progress { margin-bottom: 14px; }
      .music-player-progress-bar {
        height: 5px; background: hsl(var(--bg));
        border-radius: 3px; cursor: pointer; overflow: hidden;
      }
      .music-player-progress-bar:focus-visible {
        outline: 2px solid hsl(var(--accent));
        outline-offset: 3px;
      }
      .music-player-progress-fill {
        height: 100%; background: hsl(var(--accent));
        width: 0%; transition: width 100ms linear; border-radius: 3px;
      }
      .music-player-times {
        display: flex; justify-content: space-between;
        font-size: 11px; color: hsl(var(--text-muted));
        margin-top: 5px; font-variant-numeric: tabular-nums;
      }
      .music-player-controls { display: flex; align-items: center; gap: 4px; }
      .mp-btn {
        width: 34px; height: 34px;
        border-radius: 8px; border: 0;
        background: transparent; color: hsl(var(--text));
        cursor: pointer;
        display: flex; align-items: center; justify-content: center;
        transition: background-color 100ms, color 100ms;
        padding: 0;
      }
      .mp-btn:hover:not(:disabled) { background: hsl(var(--accent) / 0.15); color: hsl(var(--accent)); }
      .mp-btn:disabled { opacity: 0.4; cursor: not-allowed; }
      .mp-btn svg { width: 16px; height: 16px; }
      .mp-play {
        background: hsl(var(--accent-strong)); color: hsl(var(--on-accent));
        width: 38px; height: 38px;
      }
      .mp-play:hover:not(:disabled) { background: hsl(var(--accent-strong-hover)); color: hsl(var(--on-accent)); }
      .mp-play svg.hidden { display: none; }
      .mp-volume {
        display: flex; align-items: center; gap: 5px;
        margin-left: auto;
      }
      .mp-volume > svg { width: 14px; height: 14px; color: hsl(var(--text-muted)); }
      .mp-volume-slider {
        width: 60px; height: 4px;
        -webkit-appearance: none; appearance: none;
        background: hsl(var(--bg)); border-radius: 2px;
        cursor: pointer;
      }
      .mp-volume-slider::-webkit-slider-thumb {
        -webkit-appearance: none; appearance: none;
        width: 12px; height: 12px;
        background: hsl(var(--accent));
        border-radius: 50%; cursor: pointer;
        border: 0;
      }
      .mp-volume-slider::-moz-range-thumb {
        width: 12px; height: 12px;
        background: hsl(var(--accent));
        border-radius: 50%; cursor: pointer;
        border: 0;
      }
      .music-player-empty {
        margin-top: 14px;
        padding: 12px;
        background: hsl(var(--bg));
        border-radius: 10px;
        font-size: 12px;
        color: hsl(var(--text));
        line-height: 1.45;
      }
      .music-player-empty p { margin: 0; }
    `;
    document.head.appendChild(s);
  },
};

window.addEventListener('DOMContentLoaded', () => MusicPlayer.init());
window.MusicPlayer = MusicPlayer;
