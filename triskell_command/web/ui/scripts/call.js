/* Appel vocal & visio en direct entre Jordan et Thomas (WebRTC).
 *
 * Idée : le son et l'image circulent en DIRECT d'un navigateur à l'autre
 * (peer-to-peer). Avant de se connecter, les deux PC doivent juste
 * s'échanger une « offre » et une « réponse » techniques. Cet échange
 * passe par le serveur (endpoints call_signal_*), exactement comme le
 * reste du chat fonctionne en pollant Supabase.
 *
 * Choix d'implémentation : ICE « non-trickle ». On attend d'avoir
 * collecté tous les chemins réseau possibles AVANT d'envoyer l'offre /
 * réponse. Du coup la mise en relation tient en 2 messages (offre +
 * réponse) au lieu d'un flot continu — parfait pour un canal lent
 * (polling) et bien plus robuste.
 *
 * Le poll des appels tourne en permanence en arrière-plan (même chat
 * fermé) : on peut donc recevoir un appel sans avoir la fenêtre ouverte.
 */

const TriCall = {
  // --- état courant ---
  state: 'idle',          // idle | outgoing | incoming | connecting | connected
  pc: null,               // la connexion média WebRTC
  localStream: null,
  remoteStream: null,
  callId: null,
  mode: 'audio',          // 'audio' | 'video'
  peerId: null,           // 'jordan' | 'thomas'
  peerName: '…',
  iceServers: [{ urls: ['stun:stun.l.google.com:19302'] }],
  pendingOffer: null,     // {callId, mode, sdp} d'un appel entrant non décroché

  // --- minuteries ---
  pollHandle: null,
  pollIdleMs: 2500,       // au repos : on guette un appel entrant
  pollBusyMs: 1000,       // pendant une mise en relation : plus réactif
  ringHandle: null,
  ringbackHandle: null,
  durationHandle: null,
  callTimeoutHandle: null,
  titleBlinkHandle: null,
  connectedAt: 0,

  // --- audio (sonnerie) ---
  audioCtx: null,
  savedTitle: null,

  CALL_TIMEOUT_MS: 35000,  // sans réponse au-delà → on abandonne

  init() {
    // Boutons « appeler » dans l'en-tête du chat.
    const audioBtn = document.getElementById('thomas-call-audio');
    const videoBtn = document.getElementById('thomas-call-video');
    if (audioBtn) audioBtn.addEventListener('click', () => this.startCall('audio'));
    if (videoBtn) videoBtn.addEventListener('click', () => this.startCall('video'));

    // Boutons de la fenêtre d'appel.
    this._bind('call-hangup-btn', () => this.hangup());
    this._bind('call-mute-btn', () => this.toggleMic());
    this._bind('call-cam-btn', () => this.toggleCam());
    this._bind('call-accept-btn', () => this.acceptCall());
    this._bind('call-decline-btn', () => this.declineCall());

    // Débloque le son (sonnerie) au tout premier geste de l'utilisateur :
    // les navigateurs interdisent de jouer un son sans interaction.
    const unlock = () => {
      try {
        if (!this.audioCtx) {
          const Ctx = window.AudioContext || window.webkitAudioContext;
          if (Ctx) this.audioCtx = new Ctx();
        }
        if (this.audioCtx && this.audioCtx.state === 'suspended') {
          this.audioCtx.resume();
        }
      } catch (e) {}
    };
    document.addEventListener('click', unlock, { once: true });
    document.addEventListener('keydown', unlock, { once: true });

    // Charge la config (avec qui on parle + serveurs de mise en relation)
    // puis lance la veille des appels entrants.
    this._loadConfig().finally(() => this._startPoll());
  },

  _bind(id, fn) {
    const el = document.getElementById(id);
    if (el) el.addEventListener('click', fn);
  },

  async _loadConfig() {
    if (typeof App === 'undefined' || !App.api) return;
    try {
      const res = await App.api.call_config();
      if (res && res.ok) {
        if (Array.isArray(res.ice_servers) && res.ice_servers.length) {
          this.iceServers = res.ice_servers;
        }
        this.peerId = res.peer_id || null;
        this.peerName = res.peer_name || (this.peerId ? this.peerId : '…');
      }
    } catch (e) { /* on retentera au prochain appel */ }
    // Pas de binôme connu → boutons d'appel désactivés.
    const usable = !!this.peerId;
    for (const id of ['thomas-call-audio', 'thomas-call-video']) {
      const b = document.getElementById(id);
      if (b) {
        b.disabled = !usable;
        b.title = usable
          ? (id.endsWith('video') ? `Appel vidéo avec ${this.peerName}` : `Appel vocal avec ${this.peerName}`)
          : 'Appel indisponible';
      }
    }
  },

  // ------------------------------------------------------------------
  // Veille : on relève les signaux d'appel à intervalle régulier.
  // ------------------------------------------------------------------
  _startPoll() {
    if (this.pollHandle) clearInterval(this.pollHandle);
    const busy = this.state !== 'idle';
    const ms = busy ? this.pollBusyMs : this.pollIdleMs;
    this.pollHandle = setInterval(() => this._poll(), ms);
  },

  async _poll() {
    if (typeof App === 'undefined' || !App.api) return;
    let res;
    try {
      res = await App.api.call_signal_poll();
    } catch (e) { return; }
    if (!res || !res.ok || !Array.isArray(res.signals)) return;
    for (const sig of res.signals) {
      try { await this._handleSignal(sig); } catch (e) { console.warn('call signal:', e); }
    }
  },

  async _handleSignal(sig) {
    switch (sig.kind) {
      case 'offer':   return this._onOffer(sig);
      case 'answer':  return this._onAnswer(sig);
      case 'hangup':  return this._onRemoteEnd('hangup');
      case 'cancel':  return this._onRemoteEnd('cancel');
      case 'decline': return this._onRemoteEnd('decline');
      case 'busy':    return this._onRemoteEnd('busy');
    }
  },

  // ------------------------------------------------------------------
  // Appelant : je lance l'appel.
  // ------------------------------------------------------------------
  async startCall(mode) {
    if (this.state !== 'idle') return;
    await this._loadConfig();
    if (!this.peerId) {
      this._toast('Appel indisponible pour le moment.');
      return;
    }
    this.mode = mode === 'video' ? 'video' : 'audio';
    this.callId = this._newId();
    this.state = 'outgoing';
    this._startPoll();

    let stream;
    try {
      stream = await this._getMedia(this.mode);
    } catch (e) {
      this._mediaError(e);
      this._reset(false);
      return;
    }
    this.localStream = stream;

    try {
      this._buildPeer();
      stream.getTracks().forEach(t => this.pc.addTrack(t, stream));
      const offer = await this.pc.createOffer();
      await this.pc.setLocalDescription(offer);
      await this._waitIce(this.pc);
      const ok = await this._send('offer', JSON.stringify(this.pc.localDescription), this.mode);
      if (!ok) throw new Error('signal offer failed');
    } catch (e) {
      console.warn('startCall:', e);
      this._toast('Impossible de lancer l’appel.');
      this._reset(true);
      return;
    }

    // Fenêtre d'appel + sonnerie « ça sonne ».
    this._showCall();
    this._setStatus(`Appel ${this.mode === 'video' ? 'vidéo' : 'vocal'}…`);
    this._setSub('Ça sonne…');
    this._ringback();
    // Pas de réponse au bout d'un moment → on abandonne proprement.
    this.callTimeoutHandle = setTimeout(() => {
      if (this.state === 'outgoing') {
        this._send('cancel');
        this._toast('Pas de réponse.');
        this._reset(true);
      }
    }, this.CALL_TIMEOUT_MS);
  },

  // ------------------------------------------------------------------
  // Appelé : un appel arrive.
  // ------------------------------------------------------------------
  async _onOffer(sig) {
    // Déjà occupé (autre appel) → on signale « occupé » et on ignore.
    if (this.state !== 'idle') {
      if (sig.call_id !== this.callId) {
        this._sendTo(sig.call_id, 'busy');
      }
      return;
    }
    let sdp;
    try { sdp = JSON.parse(sig.payload); } catch (e) { return; }
    this.callId = sig.call_id;
    this.mode = sig.mode === 'video' ? 'video' : 'audio';
    this.pendingOffer = { callId: sig.call_id, mode: this.mode, sdp };
    if (sig.from_user) {
      this.peerId = sig.from_user;
      this.peerName = (sig.from_user === 'jordan') ? 'Jordan'
                    : (sig.from_user === 'thomas') ? 'Thomas'
                    : this.peerName;
    }
    this.state = 'incoming';
    this._startPoll();
    this._showIncoming();
    this._ring();
    // L'appelant abandonne après ~35 s ; on ferme la sonnerie un peu après
    // au cas où le « cancel » se perde.
    this.callTimeoutHandle = setTimeout(() => {
      if (this.state === 'incoming') this._reset(false);
    }, this.CALL_TIMEOUT_MS + 4000);
  },

  async acceptCall() {
    if (this.state !== 'incoming' || !this.pendingOffer) return;
    this._stopRing();
    const offer = this.pendingOffer;
    this.state = 'connecting';
    this._startPoll();

    let stream;
    try {
      stream = await this._getMedia(this.mode);
    } catch (e) {
      this._mediaError(e);
      this._send('decline');
      this._reset(false);
      return;
    }
    this.localStream = stream;

    try {
      this._buildPeer();
      stream.getTracks().forEach(t => this.pc.addTrack(t, stream));
      await this.pc.setRemoteDescription(new RTCSessionDescription(offer.sdp));
      const answer = await this.pc.createAnswer();
      await this.pc.setLocalDescription(answer);
      await this._waitIce(this.pc);
      await this._send('answer', JSON.stringify(this.pc.localDescription));
    } catch (e) {
      console.warn('acceptCall:', e);
      this._toast('La connexion a échoué.');
      this._reset(true);
      return;
    }

    this._hideIncoming();
    this._showCall();
    this._setStatus('Connexion…');
    this._setSub('');
    this.pendingOffer = null;
  },

  declineCall() {
    if (this.state !== 'incoming') return;
    this._send('decline');
    this._reset(false);
  },

  // ------------------------------------------------------------------
  // Appelant : la réponse de l'autre arrive.
  // ------------------------------------------------------------------
  async _onAnswer(sig) {
    if (this.state !== 'outgoing' && this.state !== 'connecting') return;
    if (sig.call_id !== this.callId || !this.pc) return;
    let sdp;
    try { sdp = JSON.parse(sig.payload); } catch (e) { return; }
    try {
      await this.pc.setRemoteDescription(new RTCSessionDescription(sdp));
      this._stopRingback();
      this.state = 'connecting';
      this._setStatus('Connexion…');
      this._setSub('');
    } catch (e) {
      console.warn('_onAnswer:', e);
      this._reset(true);
    }
  },

  _onRemoteEnd(reason) {
    if (this.state === 'idle') return;
    const msg = reason === 'decline' ? 'Appel refusé.'
              : reason === 'busy'    ? `${this.peerName} est déjà en ligne.`
              : 'Appel terminé.';
    this._toast(msg);
    this._reset(false);
  },

  // ------------------------------------------------------------------
  // Raccrocher / contrôles.
  // ------------------------------------------------------------------
  hangup() {
    if (this.state === 'idle') return;
    this._send(this.state === 'outgoing' ? 'cancel' : 'hangup');
    this._reset(true);
  },

  toggleMic() {
    if (!this.localStream) return;
    const tracks = this.localStream.getAudioTracks();
    if (!tracks.length) return;
    const on = !tracks[0].enabled;
    tracks.forEach(t => t.enabled = on);
    const btn = document.getElementById('call-mute-btn');
    if (btn) {
      btn.classList.toggle('tri-call-off', !on);
      btn.title = on ? 'Couper le micro' : 'Réactiver le micro';
    }
  },

  toggleCam() {
    if (!this.localStream) return;
    const tracks = this.localStream.getVideoTracks();
    if (!tracks.length) return;
    const on = !tracks[0].enabled;
    tracks.forEach(t => t.enabled = on);
    const btn = document.getElementById('call-cam-btn');
    if (btn) {
      btn.classList.toggle('tri-call-off', !on);
      btn.title = on ? 'Couper la caméra' : 'Réactiver la caméra';
    }
    const local = document.getElementById('call-local-video');
    if (local) local.style.visibility = on ? 'visible' : 'hidden';
  },

  // ------------------------------------------------------------------
  // WebRTC : construction de la connexion média.
  // ------------------------------------------------------------------
  _buildPeer() {
    const pc = new RTCPeerConnection({ iceServers: this.iceServers });
    this.remoteStream = new MediaStream();
    pc.ontrack = (ev) => {
      (ev.streams && ev.streams[0] ? ev.streams[0].getTracks() : [ev.track])
        .forEach(t => {
          if (!this.remoteStream.getTracks().includes(t)) this.remoteStream.addTrack(t);
        });
      const v = document.getElementById('call-remote-video');
      if (v) {
        if (v.srcObject !== this.remoteStream) v.srcObject = this.remoteStream;
        v.play().catch(() => {});   // force la lecture (le son surtout)
      }
    };
    pc.onconnectionstatechange = () => {
      const st = pc.connectionState;
      if (st === 'connected') this._onConnected();
      else if (st === 'failed' || st === 'closed') {
        if (this.state !== 'idle') { this._toast('Connexion perdue.'); this._reset(true); }
      } else if (st === 'disconnected') {
        // Souvent transitoire — on laisse une chance de se rétablir.
        setTimeout(() => {
          if (this.pc === pc && pc.connectionState === 'disconnected') {
            this._toast('Connexion perdue.'); this._reset(true);
          }
        }, 6000);
      }
    };
    this.pc = pc;
    const local = document.getElementById('call-local-video');
    if (local && this.localStream && this.mode === 'video') {
      local.srcObject = this.localStream;
      local.style.display = '';
    } else if (local) {
      local.style.display = 'none';
    }
  },

  _onConnected() {
    if (this.state === 'connected') return;
    this.state = 'connected';
    this._startPoll();
    this._stopRing();
    this._stopRingback();
    if (this.callTimeoutHandle) { clearTimeout(this.callTimeoutHandle); this.callTimeoutHandle = null; }
    this.connectedAt = Date.now();
    this._setSub('');
    this._tickDuration();
    if (this.durationHandle) clearInterval(this.durationHandle);
    this.durationHandle = setInterval(() => this._tickDuration(), 1000);
    // Affiche / masque l'avatar selon qu'on a une image distante ou non.
    this._refreshVideoLayout();
  },

  _tickDuration() {
    const s = Math.max(0, Math.floor((Date.now() - this.connectedAt) / 1000));
    const mm = String(Math.floor(s / 60)).padStart(2, '0');
    const ss = String(s % 60).padStart(2, '0');
    this._setStatus(`${mm}:${ss}`);
  },

  // Attend la fin de la collecte des chemins réseau (ICE) avant d'envoyer
  // l'offre/réponse. Plafonné pour ne pas bloquer si un réseau traîne.
  _waitIce(pc, timeoutMs = 2500) {
    return new Promise((resolve) => {
      if (pc.iceGatheringState === 'complete') return resolve();
      let done = false;
      const finish = () => {
        if (done) return; done = true;
        pc.removeEventListener('icegatheringstatechange', check);
        resolve();
      };
      const check = () => { if (pc.iceGatheringState === 'complete') finish(); };
      pc.addEventListener('icegatheringstatechange', check);
      setTimeout(finish, timeoutMs);
    });
  },

  async _getMedia(mode) {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      throw new Error('getUserMedia indisponible');
    }
    return navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      video: mode === 'video'
        ? { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: 'user' }
        : false,
    });
  },

  _mediaError(e) {
    const name = e && e.name ? e.name : '';
    if (name === 'NotAllowedError' || name === 'SecurityError') {
      this._toast('Micro/caméra refusés. Autorise-les dans le navigateur.');
    } else if (name === 'NotFoundError') {
      this._toast('Aucun micro ou caméra détecté.');
    } else {
      this._toast('Impossible d’accéder au micro/caméra.');
    }
  },

  // ------------------------------------------------------------------
  // Envoi des signaux au serveur.
  // ------------------------------------------------------------------
  async _send(kind, payload, mode) {
    return this._sendTo(this.callId, kind, payload, mode);
  },

  async _sendTo(callId, kind, payload, mode) {
    if (typeof App === 'undefined' || !App.api || !callId) return false;
    try {
      const res = await App.api.call_signal_send({
        call_id: callId, kind, payload: payload || null, mode: mode || null,
      });
      return !!(res && res.ok);
    } catch (e) { return false; }
  },

  // ------------------------------------------------------------------
  // Remise à zéro complète.
  // ------------------------------------------------------------------
  _reset(clearServer) {
    const id = this.callId;
    this._stopRing();
    this._stopRingback();
    this._stopTitleBlink();
    if (this.durationHandle) { clearInterval(this.durationHandle); this.durationHandle = null; }
    if (this.callTimeoutHandle) { clearTimeout(this.callTimeoutHandle); this.callTimeoutHandle = null; }
    if (this.pc) { try { this.pc.close(); } catch (e) {} this.pc = null; }
    if (this.localStream) { this.localStream.getTracks().forEach(t => t.stop()); this.localStream = null; }
    this.remoteStream = null;
    for (const vid of ['call-remote-video', 'call-local-video']) {
      const v = document.getElementById(vid);
      if (v) { try { v.srcObject = null; } catch (e) {} }
    }
    this._hideCall();
    this._hideIncoming();
    const muteBtn = document.getElementById('call-mute-btn');
    if (muteBtn) muteBtn.classList.remove('tri-call-off');
    const camBtn = document.getElementById('call-cam-btn');
    if (camBtn) camBtn.classList.remove('tri-call-off');
    this.pendingOffer = null;
    this.state = 'idle';
    this.callId = null;
    this._startPoll();
    if (clearServer && id && typeof App !== 'undefined' && App.api) {
      try { App.api.call_clear({ call_id: id }); } catch (e) {}
    }
  },

  // ------------------------------------------------------------------
  // UI — fenêtre d'appel.
  // ------------------------------------------------------------------
  _showCall() {
    const ov = document.getElementById('call-overlay');
    if (!ov) return;
    ov.classList.remove('hidden');
    ov.classList.add('flex');
    // Bouton caméra visible uniquement en visio.
    const camBtn = document.getElementById('call-cam-btn');
    if (camBtn) camBtn.style.display = this.mode === 'video' ? '' : 'none';
    const nameEl = document.getElementById('call-peer-name');
    if (nameEl) nameEl.textContent = this.peerName;
    const av = document.getElementById('call-avatar');
    if (av) av.textContent = (this.peerName || '?').trim().charAt(0).toUpperCase() || '?';
    this._refreshVideoLayout();
  },

  _hideCall() {
    const ov = document.getElementById('call-overlay');
    if (ov) { ov.classList.add('hidden'); ov.classList.remove('flex'); }
  },

  _showIncoming() {
    const m = document.getElementById('call-incoming');
    if (!m) return;
    m.classList.remove('hidden');
    m.classList.add('flex');
    const nameEl = document.getElementById('call-incoming-name');
    if (nameEl) nameEl.textContent = this.peerName;
    const modeEl = document.getElementById('call-incoming-mode');
    if (modeEl) modeEl.textContent = this.mode === 'video' ? 'Appel vidéo' : 'Appel vocal';
    const av = document.getElementById('call-incoming-avatar');
    if (av) av.textContent = (this.peerName || '?').trim().charAt(0).toUpperCase() || '?';
    this._startTitleBlink();
  },

  _hideIncoming() {
    const m = document.getElementById('call-incoming');
    if (m) { m.classList.add('hidden'); m.classList.remove('flex'); }
    this._stopTitleBlink();
  },

  // En visio on montre la vidéo et on cache l'avatar (et inversement).
  _refreshVideoLayout() {
    const ov = document.getElementById('call-overlay');
    if (!ov) return;
    const showVideo = this.mode === 'video';
    ov.classList.toggle('tri-call-video-mode', showVideo);
    const av = document.getElementById('call-avatar');
    if (av) av.style.display = showVideo ? 'none' : '';
    // La vidéo distante reste toujours dans le DOM (le son passe même en
    // vocal) ; c'est le CSS qui la rend visible ou non selon le mode.
  },

  _setStatus(txt) {
    const el = document.getElementById('call-status');
    if (el) el.textContent = txt;
  },
  _setSub(txt) {
    const el = document.getElementById('call-sub');
    if (el) el.textContent = txt || '';
  },

  // ------------------------------------------------------------------
  // Sons : sonnerie entrante + tonalité « ça sonne » (Web Audio, sans
  // fichier). Marche si l'utilisateur a déjà interagi avec la page.
  // ------------------------------------------------------------------
  _ensureAudio() {
    try {
      if (!this.audioCtx) {
        const Ctx = window.AudioContext || window.webkitAudioContext;
        if (Ctx) this.audioCtx = new Ctx();
      }
      if (this.audioCtx && this.audioCtx.state === 'suspended') this.audioCtx.resume();
    } catch (e) {}
    return this.audioCtx;
  },

  _beep(freq, durMs, gain) {
    const ctx = this.audioCtx;
    if (!ctx) return;
    try {
      const osc = ctx.createOscillator();
      const g = ctx.createGain();
      osc.type = 'sine';
      osc.frequency.value = freq;
      osc.connect(g); g.connect(ctx.destination);
      const t = ctx.currentTime;
      const peak = gain || 0.14;
      const dur = durMs / 1000;
      g.gain.setValueAtTime(0, t);
      g.gain.linearRampToValueAtTime(peak, t + 0.02);
      g.gain.setValueAtTime(peak, t + Math.max(0.03, dur - 0.04));
      g.gain.linearRampToValueAtTime(0, t + dur);
      osc.start(t);
      osc.stop(t + dur + 0.02);
    } catch (e) {}
  },

  _ring() {
    this._ensureAudio();
    const pattern = () => {
      this._beep(523, 380, 0.16);
      setTimeout(() => this._beep(659, 380, 0.16), 200);
      if (navigator.vibrate) { try { navigator.vibrate([400, 120, 400]); } catch (e) {} }
    };
    pattern();
    if (this.ringHandle) clearInterval(this.ringHandle);
    this.ringHandle = setInterval(pattern, 2200);
  },

  _stopRing() {
    if (this.ringHandle) { clearInterval(this.ringHandle); this.ringHandle = null; }
    if (navigator.vibrate) { try { navigator.vibrate(0); } catch (e) {} }
  },

  _ringback() {
    this._ensureAudio();
    const pattern = () => this._beep(440, 700, 0.08);
    pattern();
    if (this.ringbackHandle) clearInterval(this.ringbackHandle);
    this.ringbackHandle = setInterval(pattern, 3000);
  },

  _stopRingback() {
    if (this.ringbackHandle) { clearInterval(this.ringbackHandle); this.ringbackHandle = null; }
  },

  // Fait clignoter le titre de l'onglet pour un appel entrant (utile si la
  // fenêtre n'est pas au premier plan).
  _startTitleBlink() {
    if (this.titleBlinkHandle) return;
    this.savedTitle = document.title;
    let on = false;
    this.titleBlinkHandle = setInterval(() => {
      on = !on;
      document.title = on ? `📞 ${this.peerName} appelle…` : (this.savedTitle || 'Triskell Command');
    }, 800);
  },

  _stopTitleBlink() {
    if (this.titleBlinkHandle) { clearInterval(this.titleBlinkHandle); this.titleBlinkHandle = null; }
    if (this.savedTitle != null) { document.title = this.savedTitle; this.savedTitle = null; }
  },

  // ------------------------------------------------------------------
  // Petits utilitaires.
  // ------------------------------------------------------------------
  _newId() {
    try {
      if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    } catch (e) {}
    return 'c-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 10);
  },

  _toast(msg) {
    // Réutilise le toast global de l'app s'il existe, sinon fallback discret.
    try {
      if (typeof App !== 'undefined' && App.toast) return App.toast(msg);
      if (typeof App !== 'undefined' && App.notify) return App.notify(msg);
    } catch (e) {}
    console.log('[appel]', msg);
  },
};

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => TriCall.init());
} else {
  TriCall.init();
}
