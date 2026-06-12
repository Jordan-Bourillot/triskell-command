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

  // Empêche l'écran de s'éteindre pendant un appel (sinon le téléphone se
  // met en veille et coupe la communication).
  wakeLock: null,

  CALL_TIMEOUT_MS: 35000,     // sans réponse au-delà → on abandonne
  CONNECT_TIMEOUT_MS: 18000,  // « Connexion… » qui n'aboutit pas → on raccroche

  // --- chargement de la config (call_config) ---
  configRetryHandle: null,
  configRetryCount: 0,
  CONFIG_RETRY_MS: 30000,     // config injoignable → on retente toutes les 30 s
  CONFIG_RETRY_MAX: 10,       // … 10 essais maximum

  // Verrou anti-chevauchement du poll + toast « appel entrant » persistant.
  _polling: false,
  _incomingToastEl: null,
  _toastHostPrevZ: undefined,   // z-index d'origine de l'hôte des messages

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

    // Lecteurs d'écran : ces boutons n'ont qu'une icône, on pose un nom clair.
    const ariaLabels = {
      'call-hangup-btn':  'Raccrocher',
      'call-mute-btn':    'Couper le micro',
      'call-cam-btn':     'Couper la caméra',
      'call-accept-btn':  'Accepter l’appel',
      'call-decline-btn': 'Refuser l’appel',
    };
    for (const [id, label] of Object.entries(ariaLabels)) {
      const el = document.getElementById(id);
      if (!el) continue;
      el.setAttribute('aria-label', label);
      // Micro/caméra = boutons à 2 états (actif/coupé) → aria-pressed.
      if (id === 'call-mute-btn' || id === 'call-cam-btn') {
        el.setAttribute('aria-pressed', 'false');
      }
    }

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

    // Quand on revient sur la page (typiquement après avoir cliqué la
    // notification « X t'appelle »), on vérifie aussitôt s'il y a un appel
    // en attente — sans attendre le prochain tour de veille.
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') {
        this._poll();
        // Le navigateur lâche le « garde l'écran allumé » dès que l'onglet
        // passe en arrière-plan : on le reprend au retour si on est en appel.
        if (this.state !== 'idle') this._acquireWakeLock();
      }
    });
    window.addEventListener('focus', () => this._poll());

    // Charge la config (avec qui on parle + serveurs de mise en relation)
    // puis lance la veille des appels entrants.
    this._loadConfig().finally(() => this._startPoll());
  },

  _bind(id, fn) {
    const el = document.getElementById(id);
    if (el) el.addEventListener('click', fn);
  },

  async _loadConfig() {
    // 3 issues possibles : 'ok' (binôme connu), 'no-peer' (le serveur répond
    // mais personne à appeler — état normal, on n'insiste pas) et 'error'
    // (serveur injoignable → on reprogramme un essai automatique).
    let outcome = 'error';
    if (typeof App !== 'undefined' && App.api) {
      try {
        const res = await App.api.call_config();
        if (res && res.ok) {
          if (Array.isArray(res.ice_servers) && res.ice_servers.length) {
            this.iceServers = res.ice_servers;
          }
          this.peerId = res.peer_id || null;
          this.peerName = res.peer_name || (this.peerId ? this.peerId : '…');
          outcome = this.peerId ? 'ok' : 'no-peer';
        }
      } catch (e) { /* serveur injoignable → nouvelle tentative plus bas */ }
    }
    // Pas de binôme connu → boutons d'appel désactivés, avec un title qui
    // explique pourquoi (un bouton désactivé ne peut pas être cliqué).
    const usable = !!this.peerId;
    let offTitle = 'Appel indisponible';
    if (outcome === 'error') {
      offTitle = this.configRetryCount >= this.CONFIG_RETRY_MAX
        ? 'Appels indisponibles — recharge la page pour réessayer'
        : 'Appels indisponibles — nouvel essai automatique dans 30 secondes';
    }
    for (const id of ['thomas-call-audio', 'thomas-call-video']) {
      const b = document.getElementById(id);
      if (!b) continue;
      b.disabled = !usable;
      b.title = usable
        ? (id.endsWith('video') ? `Appel vidéo avec ${this.peerName}` : `Appel vocal avec ${this.peerName}`)
        : offTitle;
      b.setAttribute('aria-label', b.title);
    }
    if (outcome === 'ok') {
      // Config chargée : les boutons sont réactivés, on arrête de retenter.
      this.configRetryCount = 0;
      if (this.configRetryHandle) { clearTimeout(this.configRetryHandle); this.configRetryHandle = null; }
    } else if (outcome === 'error') {
      this._scheduleConfigRetry();
    }
    return usable;
  },

  // Config ratée au chargement → avant, les boutons d'appel restaient morts
  // pour toute la session. Désormais on retente tout seul (30 s, 10 essais max).
  _scheduleConfigRetry() {
    if (this.configRetryHandle) return;                         // déjà programmé
    if (this.configRetryCount >= this.CONFIG_RETRY_MAX) return; // on n'insiste plus
    this.configRetryCount += 1;
    this.configRetryHandle = setTimeout(() => {
      this.configRetryHandle = null;
      this._loadConfig();
    }, this.CONFIG_RETRY_MS);
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
    if (this._polling) return;   // garde anti-chevauchement (réseau lent)
    if (typeof App === 'undefined' || !App.api) return;
    this._polling = true;
    try {
      let res;
      try {
        res = await App.api.call_signal_poll();
      } catch (e) { return; }
      if (!res || !res.ok || !Array.isArray(res.signals)) return;
      for (const sig of res.signals) {
        try { await this._handleSignal(sig); } catch (e) { console.warn('call signal:', e); }
      }
    } finally {
      this._polling = false;
    }
  },

  async _handleSignal(sig) {
    switch (sig.kind) {
      case 'offer':   return this._onOffer(sig);
      case 'answer':  return this._onAnswer(sig);
      case 'hangup':  return this._onRemoteEnd('hangup');
      case 'cancel':  return this._onRemoteEnd('cancel');
      case 'decline': {
        // Un refus peut porter une raison (ex. micro bloqué côté receveur) :
        // on distingue pour ne pas afficher « Appel refusé » à tort.
        let reason = '';
        try { reason = (JSON.parse(sig.payload || '{}') || {}).reason || ''; } catch (e) {}
        return this._onRemoteEnd(reason === 'media-error' ? 'media-error' : 'decline');
      }
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
      // peerId absent = la config d'appel n'a pas pu être chargée (souvent
      // un souci de connexion au serveur) — on le dit, avec quoi faire.
      this._toast('Impossible de préparer l’appel : le serveur n’a pas '
        + 'répondu. Vérifie ta connexion internet et réessaie dans un '
        + 'instant. En attendant, le chat écrit fonctionne.', 'warn');
      return;
    }
    this.mode = mode === 'video' ? 'video' : 'audio';
    this.callId = this._newId();
    this.state = 'outgoing';
    this._startPoll();
    this._acquireWakeLock();

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
      this._toast('Impossible de lancer l’appel.', 'error');
      this._reset(true);
      return;
    }

    // Fenêtre d'appel + sonnerie « ça sonne ».
    this._showCall();
    this._setStatus(`Appel ${this.mode === 'video' ? 'vidéo' : 'vocal'}…`);
    this._setSub('Ça sonne…');
    this._ringback();
    // Pas de réponse au bout d'un moment → on abandonne proprement,
    // et on laisse une trace « appel manqué » dans le fil de discussion.
    this.callTimeoutHandle = setTimeout(() => {
      if (this.state === 'outgoing') {
        this._send('cancel');
        this._toast('Pas de réponse.');
        this._logMissedCall();
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
    this._acquireWakeLock();
    this._showIncoming();
    this._ring();
    // La sonnerie peut être muette (navigateur sans interaction préalable) :
    // on double d'un message persistant à l'écran.
    this._showIncomingToast();
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
      // Refus AVEC raison : l'appelant affichera « X n'a pas pu activer son
      // micro » au lieu de croire à un refus volontaire.
      this._send('decline', JSON.stringify({ reason: 'media-error' }));
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
      this._toast('La connexion a échoué.', 'error');
      this._reset(true);
      return;
    }

    this._hideIncoming();
    this._showCall();
    this._setStatus('Connexion…');
    this._setSub('');
    this.pendingOffer = null;
    // La liaison directe doit s'établir vite : au-delà, on raccroche
    // proprement au lieu de laisser « Connexion… » à l'écran pour toujours.
    this._armConnectTimeout();
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
      // L'autre a décroché : le minuteur « pas de réponse » laisse la place
      // au minuteur d'établissement de la connexion.
      this._armConnectTimeout();
    } catch (e) {
      console.warn('_onAnswer:', e);
      this._reset(true);
    }
  },

  // L'échange a abouti mais la liaison directe ne s'établit pas (réseau
  // restrictif, pare-feu…) : au-delà de ~18 s on raccroche proprement,
  // avec le même message des deux côtés (voir _onRemoteEnd).
  _armConnectTimeout() {
    if (this.callTimeoutHandle) clearTimeout(this.callTimeoutHandle);
    this.callTimeoutHandle = setTimeout(() => {
      if (this.state === 'connecting') {
        this._send('hangup');
        this._toast('Connexion impossible — réessaie.', 'error');
        this._reset(true);
      }
    }, this.CONNECT_TIMEOUT_MS);
  },

  _onRemoteEnd(reason) {
    if (this.state === 'idle') return;
    let msg = 'Appel terminé.';
    let type = 'info';
    if (reason === 'decline') {
      msg = 'Appel refusé.';
    } else if (reason === 'media-error') {
      msg = `${this.peerName} n’a pas pu activer son micro — appel annulé.`;
      type = 'warn';
    } else if (reason === 'busy') {
      msg = `${this.peerName} est déjà en ligne.`;
    } else if (reason === 'cancel' && this.state === 'incoming') {
      // L'appelant a raccroché avant qu'on décroche → appel manqué.
      msg = `Appel manqué de ${this.peerName}.`;
    } else if (this.state === 'connecting') {
      // « hangup » reçu pendant l'établissement = l'autre côté a constaté
      // l'échec de connexion → même message des deux côtés.
      msg = 'Connexion impossible — réessaie.';
      type = 'error';
    }
    this._toast(msg, type);
    this._reset(false);
  },

  // ------------------------------------------------------------------
  // Raccrocher / contrôles.
  // ------------------------------------------------------------------
  hangup() {
    if (this.state === 'idle') return;
    const wasOutgoing = this.state === 'outgoing';
    this._send(wasOutgoing ? 'cancel' : 'hangup');
    // Appel annulé avant que l'autre décroche = appel manqué pour lui :
    // on laisse une trace dans le fil de discussion.
    if (wasOutgoing) this._logMissedCall();
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
      btn.setAttribute('aria-label', btn.title);
      btn.setAttribute('aria-pressed', String(!on));   // pressé = micro coupé
      this._setSlash(btn, !on);
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
      btn.setAttribute('aria-label', btn.title);
      btn.setAttribute('aria-pressed', String(!on));   // pressé = caméra coupée
      this._setSlash(btn, !on);
    }
    const local = document.getElementById('call-local-video');
    if (local) local.style.visibility = on ? 'visible' : 'hidden';
  },

  // Barre oblique dessinée PAR-DESSUS l'icône existante du bouton quand le
  // micro / la caméra est coupé(e) : le simple changement de couleur ne se
  // voyait pas assez. Purement décoratif → ne casse jamais l'appel.
  _setSlash(btn, off) {
    try {
      const svg = btn.querySelector('svg');
      if (!svg) return;
      const line = svg.querySelector('.tri-call-slash');
      if (off && !line) {
        const l = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        l.setAttribute('class', 'tri-call-slash');
        l.setAttribute('x1', '3');  l.setAttribute('y1', '3');
        l.setAttribute('x2', '21'); l.setAttribute('y2', '21');
        l.setAttribute('stroke', 'currentColor');
        l.setAttribute('stroke-width', '2.4');
        l.setAttribute('stroke-linecap', 'round');
        svg.appendChild(l);
      } else if (!off && line) {
        line.remove();
      }
    } catch (e) { /* décoratif */ }
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
          // Caméra distante coupée / rétablie → bascule image ⇄ avatar
          // (sinon on reste sur la dernière image figée).
          if (t.kind === 'video') {
            t.onmute   = () => this._refreshVideoLayout();
            t.onunmute = () => this._refreshVideoLayout();
            t.onended  = () => this._refreshVideoLayout();
          }
        });
      const v = document.getElementById('call-remote-video');
      if (v) {
        if (v.srcObject !== this.remoteStream) v.srcObject = this.remoteStream;
        v.play().catch(() => {});   // force la lecture (le son surtout)
      }
      this._refreshVideoLayout();
    };
    pc.onconnectionstatechange = () => {
      const st = pc.connectionState;
      if (st === 'connected') this._onConnected();
      else if (st === 'failed' || st === 'closed') {
        if (this.state !== 'idle') { this._toast('Connexion perdue.', 'error'); this._reset(true); }
      } else if (st === 'disconnected') {
        // Souvent transitoire — on laisse une chance de se rétablir.
        setTimeout(() => {
          if (this.pc === pc && pc.connectionState === 'disconnected') {
            this._toast('Connexion perdue.', 'error'); this._reset(true);
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
      this._toast(this.mode === 'video'
        ? 'Ton micro et ta caméra sont bloqués — autorise-les dans le navigateur (icône à gauche de l’adresse).'
        : 'Ton micro est bloqué — autorise-le dans le navigateur (icône à gauche de l’adresse).', 'error');
    } else if (name === 'NotFoundError') {
      this._toast('Aucun micro ou caméra détecté.', 'error');
    } else {
      this._toast('Impossible d’accéder au micro/caméra.', 'error');
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
  async _reset(clearServer) {
    const id = this.callId;
    this._stopRing();
    this._stopRingback();
    this._stopTitleBlink();
    this._hideIncomingToast();
    this._releaseWakeLock();
    if (this.durationHandle) { clearInterval(this.durationHandle); this.durationHandle = null; }
    if (this.callTimeoutHandle) { clearTimeout(this.callTimeoutHandle); this.callTimeoutHandle = null; }
    if (this.pc) { try { this.pc.close(); } catch (e) {} this.pc = null; }
    if (this.localStream) { this.localStream.getTracks().forEach(t => t.stop()); this.localStream = null; }
    this.remoteStream = null;
    for (const vid of ['call-remote-video', 'call-local-video']) {
      const v = document.getElementById(vid);
      if (v) { try { v.srcObject = null; v.style.opacity = ''; } catch (e) {} }
    }
    this._hideCall();
    this._hideIncoming();
    // Boutons micro/caméra : retour à l'état « actif » (classe, barre
    // oblique, libellés) pour le prochain appel.
    const muteBtn = document.getElementById('call-mute-btn');
    if (muteBtn) {
      muteBtn.classList.remove('tri-call-off');
      muteBtn.title = 'Couper le micro';
      muteBtn.setAttribute('aria-label', muteBtn.title);
      muteBtn.setAttribute('aria-pressed', 'false');
      this._setSlash(muteBtn, false);
    }
    const camBtn = document.getElementById('call-cam-btn');
    if (camBtn) {
      camBtn.classList.remove('tri-call-off');
      camBtn.title = 'Couper la caméra';
      camBtn.setAttribute('aria-label', camBtn.title);
      camBtn.setAttribute('aria-pressed', 'false');
      this._setSlash(camBtn, false);
    }
    this.pendingOffer = null;
    this.state = 'idle';
    this.callId = null;
    this._startPoll();
    if (clearServer && id && typeof App !== 'undefined' && App.api) {
      try { await App.api.call_clear({ call_id: id }); }
      catch (e) { /* nettoyage best-effort, jamais bloquant */ }
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
    if (m) {
      m.classList.add('hidden');
      m.classList.remove('flex');
      m.style.zIndex = '';   // annule l'éventuel « premier plan » du clic toast
    }
    this._stopTitleBlink();
    this._hideIncomingToast();
  },

  // La sonnerie peut être muette tant que l'utilisateur n'a jamais cliqué
  // dans la page (règle des navigateurs) : en plus du titre d'onglet qui
  // clignote, on affiche un message persistant. Un clic dessus remet la
  // fenêtre d'appel au premier plan.
  _showIncomingToast() {
    this._hideIncomingToast();
    try {
      if (typeof Toast === 'undefined' || !Toast || typeof Toast.show !== 'function') return;
      const el = Toast.show(`📞 Appel entrant de ${this.peerName} — clique pour répondre`, {
        type: 'info',
        title: 'Appels',
        duration: this.CALL_TIMEOUT_MS + 4000,   // persiste tant que ça sonne
      });
      // Le temps de la sonnerie, les messages passent DEVANT les grandes
      // fenêtres (Phare, accueil…) qui, sinon, cacheraient l'alerte —
      // c'est précisément le cas où elle est utile. Remis en place après.
      const host = document.getElementById('tc-toast-host');
      if (host) {
        this._toastHostPrevZ = host.style.zIndex || '';
        host.style.zIndex = '10001';
      }
      if (el && el.addEventListener) {
        el.style.cursor = 'pointer';
        el.addEventListener('click', (ev) => {
          // La croix garde son rôle « fermer » habituel.
          if (ev.target && ev.target.closest && ev.target.closest('.tc-toast-close')) return;
          if (this.state === 'incoming') {
            this._showIncoming();
            // « Au premier plan » pour de vrai : passe devant les autres
            // fenêtres ouvertes (remis à zéro dans _hideIncoming).
            const m = document.getElementById('call-incoming');
            if (m) m.style.zIndex = '10000';
          }
          this._hideIncomingToast();
        });
      }
      this._incomingToastEl = el;
    } catch (e) { /* le toast ne doit jamais casser l'appel */ }
  },

  _hideIncomingToast() {
    const el = this._incomingToastEl;
    this._incomingToastEl = null;
    if (el) {
      try {
        if (typeof Toast !== 'undefined' && Toast && typeof Toast._remove === 'function') Toast._remove(el);
        else el.remove();
      } catch (e) {}
    }
    // Rend aux messages leur étage habituel.
    if (this._toastHostPrevZ !== undefined) {
      try {
        const host = document.getElementById('tc-toast-host');
        if (host) host.style.zIndex = this._toastHostPrevZ;
      } catch (e) {}
      this._toastHostPrevZ = undefined;
    }
  },

  // Y a-t-il une image distante réellement en train d'arriver ?
  // (caméra coupée en face → la piste vidéo passe « muted »)
  _remoteVideoAlive() {
    if (!this.remoteStream) return false;
    return this.remoteStream.getVideoTracks()
      .some(t => t.readyState === 'live' && !t.muted);
  },

  // En visio on montre la vidéo et on cache l'avatar (et inversement).
  // Si la caméra distante est coupée (ou que l'image n'arrive pas encore),
  // on masque l'image figée et on remontre l'avatar — le son continue.
  _refreshVideoLayout() {
    const ov = document.getElementById('call-overlay');
    if (!ov) return;
    const videoMode = this.mode === 'video';
    ov.classList.toggle('tri-call-video-mode', videoMode);
    const remoteAlive = this._remoteVideoAlive();
    const remote = document.getElementById('call-remote-video');
    if (remote) remote.style.opacity = (videoMode && !remoteAlive) ? '0' : '';
    const av = document.getElementById('call-avatar');
    if (av) av.style.display = (videoMode && remoteAlive) ? 'none' : '';
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
  // Garde l'écran allumé tant qu'un appel est en cours, pour que le
  // téléphone ne se mette pas en veille (ce qui couperait le micro et donc
  // l'appel). Le navigateur relâche ce verrou dès que l'onglet passe en
  // arrière-plan ; on le reprend au retour (voir visibilitychange).
  // ------------------------------------------------------------------
  async _acquireWakeLock() {
    try {
      if (!('wakeLock' in navigator) || this.wakeLock) return;
      this.wakeLock = await navigator.wakeLock.request('screen');
      this.wakeLock.addEventListener('release', () => { this.wakeLock = null; });
    } catch (e) { /* non supporté ou refusé : sans gravité */ }
  },

  _releaseWakeLock() {
    try {
      if (this.wakeLock) this.wakeLock.release();
    } catch (e) {}
    this.wakeLock = null;
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

  // Laisse une trace « appel manqué » dans le fil de discussion, pour que
  // l'autre voie qu'on a essayé de l'appeler (comme sur un téléphone).
  _logMissedCall() {
    try {
      if (typeof App === 'undefined' || !App.api) return;
      const d = new Date();
      const hh = String(d.getHours()).padStart(2, '0');
      const mn = String(d.getMinutes()).padStart(2, '0');
      const label = this.mode === 'video' ? 'vidéo' : 'vocal';
      const p = App.api.messages_send({ body: `📞 Appel manqué (${label}) — ${hh}:${mn}` });
      if (p && typeof p.catch === 'function') p.catch(() => {});
    } catch (e) { /* la trace est un bonus, jamais bloquante */ }
  },

  _toast(msg, type) {
    // Branché en direct sur le système commun de messages (toast.js), avec
    // le titre « Appels ». Avant : on cherchait App.toast/App.notify qui
    // n'existaient pas encore → TOUS les retours partaient en console
    // (refus, occupé, connexion perdue, micro refusé…). Plus jamais ça.
    try {
      if (typeof Toast !== 'undefined' && Toast && typeof Toast.show === 'function') {
        Toast.show(msg, { type: type || 'info', title: 'Appels' });
        return;
      }
      // Filet de secours si toast.js n'est pas chargé (alias posés par lui).
      if (typeof App !== 'undefined' && typeof App.toast === 'function') {
        App.toast(msg, { type: type || 'info', title: 'Appels' });
        return;
      }
    } catch (e) {}
    console.log('[appel]', msg);
  },
};

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => TriCall.init());
} else {
  TriCall.init();
}
