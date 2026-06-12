/* Vue Cockpit (anciennement "Matinale") — poste de contrôle Triskell.
 *
 * Hiérarchie :
 *   1. Bandeau de statut (date, heure live, voyants système)
 *   2. Quickbar (Composer, Brain, Allô Claude, Concentration)
 *   3. HERO — la mission du jour (priorité unique mise en avant)
 *   4. Grille KPIs (4 chiffres clés énormes + sparkline 7 jours)
 *   5. Bloc relances LinkedIn (si il y a des actions à faire)
 *   6. Bloc alertes (si quelque chose à corriger)
 *
 * Ambiance : war room / cockpit avionique. Tout doit être lisible
 * à 2 mètres et envoyer le signal "on est en chasse".
 */

const Morning = {
  _clockTimer: null,
  _refreshTimer: null,
  _refreshIntervalMs: 30000,

  async render(container) {
    // 1. Shell instantané (avant API)
    const greeting = App.greeting();
    const dateStr = App.formatDateFr();
    let userName = (App.currentUser && App.currentUser.first_name) || '';
    if (!userName && App.api) {
      try { userName = await App.api.get_user_name(); } catch (e) {}
    }

    // Couronne accrochée à la dernière lettre du prénom (BOSS DE L'UNIVERS)
    const nameWithCrown = userName
      ? `${userName.slice(0, -1)}<span class="boss-letter">${userName.slice(-1)}<svg class="boss-crown" viewBox="0 0 32 22" aria-hidden="true"><defs><linearGradient id="bossCrownGrad" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#fde68a"/><stop offset="50%" stop-color="#facc15"/><stop offset="100%" stop-color="#b45309"/></linearGradient></defs><path fill="url(#bossCrownGrad)" stroke="#8a5a00" stroke-width="0.8" stroke-linejoin="round" d="M3 19 L5 7 L11 12 L16 4 L21 12 L27 7 L29 19 Z"/><circle cx="5" cy="6" r="1.6" fill="#dc2626" stroke="#7c2d12" stroke-width="0.5"/><circle cx="16" cy="3" r="1.8" fill="#7c3aed" stroke="#4c1d95" stroke-width="0.5"/><circle cx="27" cy="6" r="1.6" fill="#0ea5e9" stroke="#075985" stroke-width="0.5"/><rect x="3" y="18.5" width="26" height="2" fill="url(#bossCrownGrad)" stroke="#8a5a00" stroke-width="0.5"/></svg></span>`
      : '';

    container.innerHTML = `
      <section class="cockpit-shell animate-slide-up max-w-[1280px]">

        <!-- Ambiance poste de pilotage : grille HUD discrète, halos
             couleur voyants (ambre / cyan / vert), ligne de scan et
             vignette périphérique pour donner la sensation d'être
             "dans" le poste de contrôle. -->
        <div class="cockpit-ambience" aria-hidden="true">
          <div class="cockpit-ambience-grid"></div>
          <div class="cockpit-ambience-glow cockpit-ambience-glow-amber"></div>
          <div class="cockpit-ambience-glow cockpit-ambience-glow-cyan"></div>
          <div class="cockpit-ambience-glow cockpit-ambience-glow-green"></div>
          <div class="cockpit-ambience-scan"></div>
          <div class="cockpit-ambience-vignette"></div>
        </div>

        <!-- Bandeau STATUT — voyants live -->
        <div class="cockpit-status-bar" id="m-statusbar">
          <span class="cockpit-led" id="m-led-system">SYSTÈME</span>
          <span class="cockpit-sep"></span>
          <span class="cockpit-date">${dateStr}</span>
          <span class="cockpit-sep"></span>
          <span class="cockpit-time" id="m-clock">--:--:--</span>
          <span style="flex:1"></span>
          ${Help.button('morning')}
        </div>

        <!-- Salutation discrète + citation du jour + quickbar.
             ≥1120px : titre à GAUCHE, citation à DROITE sur la même ligne
             (la citation se resserre, voir .cockpit-greeting dans main.css) ;
             en dessous, la citation repasse sous le titre.
             Seuil 1120 et pas 1280 : avec l'affichage Windows à 150 %,
             un écran 1920 ne fait "que" ~1276px aux yeux du site. -->
        <div class="cockpit-greeting mt-5 flex items-end justify-between gap-6 flex-wrap min-[1120px]:flex-nowrap">
          <h1 class="hero-title">${userName ? `${greeting} ${nameWithCrown}.` : `${greeting}.`}</h1>
          ${typeof DailyQuote !== 'undefined' ? DailyQuote.renderHTML() : ''}
        </div>
        <div class="cockpit-quickbar">
          <button id="m-refresh" class="btn btn-secondary" title="Rafraîchir les chiffres">
            <svg class="w-4 h-4 text-info" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M3 12a9 9 0 0114-7.4M21 12a9 9 0 01-14 7.4"/><path d="M21 4v5h-5M3 20v-5h5"/></svg>
            Rafraîchir
          </button>
          <button id="m-ecosysteme" class="btn btn-secondary" title="Vue d'ensemble de l'écosystème Triskell (interne)">
            <svg class="w-4 h-4 text-warning-text" fill="currentColor" viewBox="0 0 24 24">
              <path d="M12 2l2.4 6.4L21 9.3l-5 4.5L17.6 21 12 17.5 6.4 21 8 13.8 3 9.3l6.6-.9L12 2z"/>
            </svg>
            Écosystème
          </button>
          <button id="m-compose-mail" class="btn btn-secondary" title="Rédiger (Ctrl+Shift+M)">
            <svg class="w-4 h-4 text-warning-text" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24" stroke-linecap="round" stroke-linejoin="round">
              <path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 113 3L7 19l-4 1 1-4L16.5 3.5z"/>
            </svg>
            Rédiger
          </button>
          <button id="m-brain" class="btn btn-secondary" title="Brain — note rapide (Ctrl+B)">
            <svg class="w-4 h-4" style="color:#a855f7" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24" stroke-linecap="round" stroke-linejoin="round">
              <path d="M12 5a3 3 0 1 0-5.997.125 4 4 0 0 0-2.526 5.77 4 4 0 0 0 .556 6.588A4 4 0 1 0 12 18Z"/>
              <path d="M12 5a3 3 0 1 1 5.997.125 4 4 0 0 1 2.526 5.77 4 4 0 0 1-.556 6.588A4 4 0 1 1 12 18Z"/>
              <path d="M15 13a4.5 4.5 0 0 1-3-4 4.5 4.5 0 0 1-3 4"/>
            </svg>
            Brain
          </button>
          <button id="m-allo-claude" class="btn btn-secondary" title="Allô Claude">
            <svg class="w-4 h-4" style="color:#06b6d4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
              <path d="M21 12a8 8 0 0 1-11.7 7.1L4 20.5l1.4-5.3A8 8 0 1 1 21 12z"/>
              <path d="M12 8.5v3M12 12.5v3M8.5 12h3M12.5 12h3" stroke-width="1.6"/>
            </svg>
            Allô Claude
          </button>
          <button id="m-focus" class="btn btn-secondary" title="Mode Concentration">
            <svg class="w-4 h-4 text-danger-text" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>
            </svg>
            Concentration
          </button>
          <button id="m-music" class="btn btn-secondary" title="Lecteur de musique">
            <svg class="w-4 h-4" style="color:#ec4899" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24" stroke-linecap="round" stroke-linejoin="round">
              <path d="M9 18V5l12-2v13"/>
              <circle cx="6" cy="18" r="3"/>
              <circle cx="18" cy="16" r="3"/>
            </svg>
            Musique
          </button>
          <button id="m-chat-thomas" class="btn btn-secondary" title="Chat avec Thomas">
            <svg class="w-4 h-4 text-success-text" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
              <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/>
            </svg>
            Chat
            <span id="m-chat-thomas-badge"
                  class="ml-1.5 inline-flex items-center justify-center min-w-[18px] h-[18px] px-1
                         rounded-full bg-danger text-white text-[10px] font-bold leading-none hidden">0</span>
          </button>
        </div>

        <!-- Rampe de lancement prospection : UNE porte d'entrée claire.
             Les outils de recherche individuels (dont les 3 bêta) vivent
             dans le menu Prospection → Outils de recherche. -->
        <div class="cockpit-launch mt-5">
          <div class="text-[11px] font-bold tracking-widest text-text-muted mb-2">
            PROSPECTION
          </div>
          <div class="cl-row">
            <button id="m-prospection" class="btn btn-primary"
                    title="Une commande = toute la chaîne : recherche → base → rédaction → envoi">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24" stroke-linecap="round" stroke-linejoin="round">
                <path d="M5 12h14"/><path d="M13 6l6 6-6 6"/>
              </svg>
              Lancer une prospection
            </button>
            <button id="m-prospects" class="btn btn-secondary"
                    title="La base centrale : tout ce que les outils trouvent atterrit ici">
              Tous les prospects
            </button>
            <button id="m-drafts" class="btn btn-secondary"
                    title="Les mails écrits par l'app qui attendent ton OK">
              Brouillons à valider
            </button>
          </div>
        </div>

        <!-- Encadré "auto-pilote en cours" : visible UNIQUEMENT pendant un
             run. Polling toutes les 3s. Cliquable pour ouvrir la page complète. -->
        <div id="m-autopilot-live" class="mt-6 hidden"></div>

        <!-- Encadré "envoi en série depuis Brouillons" : visible UNIQUEMENT
             pendant qu'un envoi manuel tourne sur le serveur. -->
        <div id="m-drafts-batch-live" class="mt-6 hidden"></div>

        <div id="m-content" class="mt-6"></div>
      </section>
    `;

    // Bindings boutons quickbar
    // Rafraîchir = rafraîchissement DOUX : on recharge les chiffres et les
    // blocs de données sans reconstruire la quickbar ni l'horloge (avant :
    // re-render complet qui faisait clignoter tout l'écran).
    document.getElementById('m-refresh').onclick = () => {
      this._softRefresh();
      this._loadSetup();
      this._loadObeliskNotifs();
      this._loadModes();
      this._loadLinkedinActions();
    };
    // Rampe de lancement prospection
    const prospectionBtn = document.getElementById('m-prospection');
    if (prospectionBtn) prospectionBtn.onclick = () => App.show('prospection');
    const prospectsBtn = document.getElementById('m-prospects');
    if (prospectsBtn) prospectsBtn.onclick = () => App.show('prospects_crm');
    const draftsBtn = document.getElementById('m-drafts');
    if (draftsBtn) draftsBtn.onclick = () => App.show('drafts');

    // Ambiance poste de pilotage : grille HUD très fine en fond, halos
    // sobres aux couleurs des voyants d'un cockpit (ambre instrumentation,
    // cyan HUD, vert système OK), ligne de scan qui descend lentement,
    // vignette périphérique qui assombrit les bords. Tout est sobre et
    // pulse très lentement — l'idée est de SENTIR le poste, pas de voir
    // une boule disco. Injecté une seule fois.
    if (!document.getElementById('m-ambience-styles')) {
      const s = document.createElement('style');
      s.id = 'm-ambience-styles';
      s.textContent = `
        /* La section Cockpit est le repère de positionnement pour que
           toute l'ambiance soit contenue à l'intérieur. */
        .cockpit-shell {
          position: relative;
          overflow: hidden;
          isolation: isolate;
        }
        .cockpit-ambience {
          position: absolute;
          inset: 0;
          z-index: 0;
          pointer-events: none;
          overflow: hidden;
        }
        /* Tout le contenu du Cockpit passe au-dessus de l'ambiance */
        .cockpit-shell > *:not(.cockpit-ambience) { position: relative; z-index: 1; }

        /* --- Grille HUD : lignes très fines, atténuées vers les bords --- */
        .cockpit-ambience-grid {
          position: absolute;
          inset: 0;
          background-image:
            linear-gradient(to right, rgba(148,163,184,0.07) 1px, transparent 1px),
            linear-gradient(to bottom, rgba(148,163,184,0.07) 1px, transparent 1px);
          background-size: 64px 64px;
          -webkit-mask-image: radial-gradient(ellipse at center, black 30%, transparent 85%);
                  mask-image: radial-gradient(ellipse at center, black 30%, transparent 85%);
        }
        [data-theme="light"] .cockpit-ambience-grid {
          background-image:
            linear-gradient(to right, rgba(71,85,105,0.06) 1px, transparent 1px),
            linear-gradient(to bottom, rgba(71,85,105,0.06) 1px, transparent 1px);
        }
        [data-theme="mid"] .cockpit-ambience-grid {
          background-image:
            linear-gradient(to right, rgba(148,163,184,0.09) 1px, transparent 1px),
            linear-gradient(to bottom, rgba(148,163,184,0.09) 1px, transparent 1px);
        }

        /* --- Halos couleur voyants : ambre, cyan, vert OK --- */
        .cockpit-ambience-glow {
          position: absolute;
          width: 540px;
          height: 540px;
          border-radius: 50%;
          filter: blur(95px);
          opacity: 0.38;
          mix-blend-mode: screen;
          will-change: opacity;
        }
        /* Coin haut-gauche : ambre chaud, lumière d'instrumentation */
        .cockpit-ambience-glow-amber {
          background: radial-gradient(circle, #f59e0b 0%, rgba(245,158,11,0) 70%);
          top: -15%; left: -12%;
          animation: cockpit-pulse-slow 9s ease-in-out infinite;
        }
        /* Coin haut-droit : cyan glacial, écran HUD */
        .cockpit-ambience-glow-cyan {
          background: radial-gradient(circle, #38bdf8 0%, rgba(56,189,248,0) 70%);
          top: -18%; right: -14%;
          animation: cockpit-pulse-slow 11s ease-in-out infinite 1.5s;
        }
        /* Bas-centre : vert tendre, voyant système OK */
        .cockpit-ambience-glow-green {
          background: radial-gradient(circle, #10b981 0%, rgba(16,185,129,0) 70%);
          bottom: -22%; left: 30%;
          width: 640px; height: 640px;
          opacity: 0.28;
          animation: cockpit-pulse-slow 13s ease-in-out infinite 3s;
        }
        /* Thème clair : screen lave les couleurs. On bascule en multiply
           et on baisse fort l'opacité pour rester sobre. */
        [data-theme="light"] .cockpit-ambience-glow {
          mix-blend-mode: multiply;
          opacity: 0.12;
          filter: blur(80px);
        }
        [data-theme="light"] .cockpit-ambience-glow-green {
          opacity: 0.10;
        }
        [data-theme="mid"] .cockpit-ambience-glow {
          opacity: 0.25;
        }
        [data-theme="mid"] .cockpit-ambience-glow-green {
          opacity: 0.20;
        }

        /* --- Ligne de scan : barre fine cyan qui descend très lentement
               comme sur un écran de surveillance --- */
        .cockpit-ambience-scan {
          position: absolute;
          top: 0; left: 0; right: 0;
          height: 2px;
          background: linear-gradient(to bottom,
            transparent,
            rgba(56,189,248,0.22) 50%,
            transparent);
          filter: blur(1.2px);
          animation: cockpit-scan 16s linear infinite;
        }
        [data-theme="light"] .cockpit-ambience-scan {
          background: linear-gradient(to bottom,
            transparent,
            rgba(14,165,233,0.12) 50%,
            transparent);
        }

        /* --- Vignette : assombrit doucement les bords pour donner la
               sensation d'être "dans" le poste --- */
        .cockpit-ambience-vignette {
          position: absolute;
          inset: 0;
          background: radial-gradient(ellipse at center,
            transparent 55%,
            rgba(0,0,0,0.22) 100%);
        }
        [data-theme="light"] .cockpit-ambience-vignette {
          background: radial-gradient(ellipse at center,
            transparent 62%,
            rgba(15,23,42,0.06) 100%);
        }
        [data-theme="mid"] .cockpit-ambience-vignette {
          background: radial-gradient(ellipse at center,
            transparent 58%,
            rgba(0,0,0,0.14) 100%);
        }

        /* Pulsation très lente, presque imperceptible — battement du poste */
        @keyframes cockpit-pulse-slow {
          0%, 100% { opacity: var(--cockpit-glow-min, 0.32); }
          50%      { opacity: var(--cockpit-glow-max, 0.48); }
        }
        @keyframes cockpit-scan {
          0%   { transform: translateY(-10%); }
          100% { transform: translateY(120vh); }
        }

        /* Respect "réduire les animations" : on garde les lumières
           statiques pour l'ambiance, on coupe pulsation et scan. */
        @media (prefers-reduced-motion: reduce) {
          .cockpit-ambience-glow { animation: none; }
          .cockpit-ambience-scan { display: none; }
        }
      `;
      document.head.appendChild(s);
    }

    document.getElementById('m-brain').onclick = () => {
      if (typeof Brain !== 'undefined' && Brain._openNew) Brain._openNew();
    };
    document.getElementById('m-allo-claude').onclick = () => {
      if (typeof Claude !== 'undefined' && Claude.open) Claude.open();
    };
    document.getElementById('m-compose-mail').onclick = () => this._openComposeChoice();
    document.getElementById('m-ecosysteme').onclick = () => {
      // Version web : on ouvre simplement la page dans un nouvel onglet.
      window.open('https://triskell-ecosysteme.netlify.app', '_blank');
    };
    const focusBtn = document.getElementById('m-focus');
    if (focusBtn) {
      focusBtn.onclick = () => {
        if (typeof FocusMode === 'undefined') return;
        if (FocusMode.isOn()) FocusMode.showOverlay();
        else FocusMode.openStartDialog();
      };
      if (typeof FocusMode !== 'undefined' && FocusMode.bindButton) {
        FocusMode.bindButton(focusBtn);
      }
    }

    // Bouton "Musique" : déplie/replie le panneau du lecteur (le rond
    // flottant en bas-droite est masqué — voir music_player.js).
    const musicBtn = document.getElementById('m-music');
    if (musicBtn) {
      musicBtn.onclick = () => {
        if (typeof MusicPlayer !== 'undefined' && MusicPlayer._toggleExpanded) {
          MusicPlayer._toggleExpanded();
        }
      };
    }

    // Bouton "Chat" avec Thomas : ouvre la modale de chat. La pastille de
    // messages non-lus est gérée par thomas.js qui synchronise les deux
    // (l'ancien FAB flottant + ce nouveau bouton intégré).
    const chatBtn = document.getElementById('m-chat-thomas');
    if (chatBtn) {
      chatBtn.onclick = () => {
        if (typeof Thomas !== 'undefined' && Thomas.openDialog) {
          Thomas.openDialog();
        }
      };
    }

    // Pastilles "NEW"
    if (window.NewBadge) {
      const brainBtn = document.getElementById('m-brain');
      const alloBtn  = document.getElementById('m-allo-claude');
      const composeBtn = document.getElementById('m-compose-mail');
      if (brainBtn)   window.NewBadge.attach(brainBtn,   'cockpit-brain-v1');
      if (alloBtn)    window.NewBadge.attach(alloBtn,    'cockpit-allo-claude-v1');
      if (composeBtn) window.NewBadge.attach(composeBtn, 'cockpit-compose-choice-v1');
      if (focusBtn)   window.NewBadge.attach(focusBtn,   'cockpit-focus-v1');
    }

    // Démarre l'horloge live
    this._startClock();

    // Encadré "auto-pilote en cours" : poll en arrière-plan toutes les 3s
    // pour afficher/cacher le bandeau live en haut du Cockpit selon que
    // l'auto-pilote tourne ou pas.
    this._startAutopilotPoll();
    // Encadré "envoi en série en cours" : même logique, poll dédié pour le
    // bouton "Tout envoyer" depuis la page Brouillons.
    this._startDraftsBatchPoll();

    // 2. Charge le digest
    const slot = document.getElementById('m-content');
    if (!App.api) {
      slot.innerHTML = this._previewPlaceholder();
      return;
    }
    let digest = null;
    try { digest = await App.api.get_morning_digest(); } catch (e) {}

    if (!digest || !digest.ok) {
      this._setSystemLed('alert', 'BASE PARTAGÉE HORS LIGNE');
      slot.innerHTML = `
        <div class="cockpit-alert">
          <div class="cockpit-alert-icon">!</div>
          <div class="flex-1">
            <h3 class="text-base font-bold mb-1">Connexion à la base partagée requise</h3>
            <p class="text-sm text-text-secondary mb-4">
              Connecte-toi à la base partagée Triskell depuis les Réglages pour
              que ce poste de contrôle se remplisse en temps réel.
            </p>
            <button class="btn btn-primary" onclick="App.show('config', {tab:'account'})">Aller dans Réglages →</button>
          </div>
        </div>
      `;
      return;
    }

    // Met à jour le voyant système selon l'état
    const alerts = (digest.alerts && (digest.alerts.convoy_failed_today + digest.alerts.convoy_failed_yesterday)) || 0;
    if (alerts > 0) {
      this._setSystemLed('alert', `SYSTÈME · ${alerts} ALERTE${alerts > 1 ? 'S' : ''}`);
    } else {
      this._setSystemLed('ok', 'SYSTÈME · OPÉRATIONNEL');
    }

    slot.innerHTML = `<div id="m-setup-slot"></div>`
                   + this._renderHero(digest)
                   + `<div id="m-pipelines-slot"></div>`
                   + `<div id="m-obelisk-slot"></div>`
                   + this._renderKpiGrid(digest)
                   + `<div id="m-modes-slot"></div>`
                   + this._renderAlert(digest)
                   + `<div id="m-linkedin-slot"></div>`;

    this._loadSetup();
    this._loadPipelinesActivity();
    this._loadObeliskNotifs();
    this._loadModes();
    this._loadLinkedinActions();

    // Démarre le rafraîchissement automatique des chiffres
    this._startAutoRefresh();
  },

  // -------- Bloc SETUP — bilan des connexions à brancher --------
  async _loadSetup() {
    if (!App.api) return;
    const slot = document.getElementById('m-setup-slot');
    if (!slot) return;
    let data = null;
    try { data = await App.api.setup_status(); } catch (e) {}
    if (!data || !data.ok) return;
    const items = data.items || [];
    const sum = data.summary || {};
    const missing = sum.missing || 0;
    const warn = sum.warn || 0;
    if (missing === 0 && warn === 0) {
      slot.innerHTML = '';
      return;
    }
    slot.innerHTML = this._renderSetup(items, sum);
    this._bindSetup();
  },

  _renderSetup(items, sum) {
    const total = items.length;
    const ok = sum.ok || 0;
    const missing = sum.missing || 0;
    const warn = sum.warn || 0;
    const tone = missing > 0 ? 'danger' : 'warning';
    const headline = missing > 0
      ? (missing === 1
          ? '1 connexion à brancher pour que tout tourne tout seul'
          : `${missing} connexions à brancher pour que tout tourne tout seul`)
      : (warn === 1
          ? '1 réglage recommandé manquant'
          : `${warn} réglages recommandés manquants`);
    return `
      <div class="cockpit-setup" data-tone="${tone}">
        <div class="cockpit-setup-head">
          <div>
            <div class="cockpit-setup-kicker">CONFIGURATION</div>
            <h3 class="cockpit-setup-title">${headline}</h3>
            <div class="cockpit-setup-sub">${ok} / ${total} branché${total > 1 ? 's' : ''}</div>
          </div>
          <button class="cockpit-setup-toggle" type="button"
                  data-act="toggle"
                  aria-expanded="false"
                  title="Voir le détail">
            Voir le détail
          </button>
        </div>
        <ul class="cockpit-setup-list" hidden>
          ${items.map(it => this._setupItem(it)).join('')}
        </ul>
      </div>
    `;
  },

  _setupItem(it) {
    const icon = it.status === 'ok'   ? '✓'
               : it.status === 'warn' ? '!'
               :                        '✗';
    const statusLabel = it.status === 'ok'   ? 'OK'
                      : it.status === 'warn' ? 'À ajuster'
                      :                        'À brancher';
    const goto = (it.goto && it.goto.view) || 'config';
    const tab = (it.goto && it.goto.tab) || '';
    return `
      <li class="cockpit-setup-item" data-status="${it.status}">
        <span class="cockpit-setup-icon">${icon}</span>
        <div class="cockpit-setup-text">
          <div class="cockpit-setup-label">${it.label}</div>
          ${it.why ? `<div class="cockpit-setup-why">${it.why}</div>` : ''}
        </div>
        <span class="cockpit-setup-status">${statusLabel}</span>
        ${it.status !== 'ok'
          ? `<button class="btn btn-secondary cockpit-setup-cta"
                     type="button"
                     data-goto="${goto}"
                     data-tab="${tab}">Configurer →</button>`
          : ''}
      </li>
    `;
  },

  _bindSetup() {
    const slot = document.getElementById('m-setup-slot');
    if (!slot) return;
    const toggle = slot.querySelector('[data-act="toggle"]');
    const list = slot.querySelector('.cockpit-setup-list');
    if (toggle && list) {
      toggle.onclick = () => {
        const opened = !list.hasAttribute('hidden');
        if (opened) {
          list.setAttribute('hidden', '');
          toggle.setAttribute('aria-expanded', 'false');
          toggle.textContent = 'Voir le détail';
        } else {
          list.removeAttribute('hidden');
          toggle.setAttribute('aria-expanded', 'true');
          toggle.textContent = 'Replier';
        }
      };
    }
    slot.querySelectorAll('[data-goto]').forEach(btn => {
      btn.onclick = () => {
        const view = btn.dataset.goto || 'config';
        const tab = btn.dataset.tab || '';
        if (tab) {
          try { localStorage.setItem('cfg-active-tab', tab); } catch (e) {}
        }
        App.show(view);
      };
    });
  },

  // -------- Rafraîchissement automatique --------
  _startAutoRefresh() {
    if (this._refreshTimer) clearInterval(this._refreshTimer);
    this._refreshTimer = setInterval(() => this._softRefresh(), this._refreshIntervalMs);
    if (!this._visibilityBound) {
      this._visibilityBound = true;
      document.addEventListener('visibilitychange', () => {
        if (!document.hidden && document.getElementById('m-content')) {
          this._softRefresh();
        }
      });
    }
  },

  async _softRefresh() {
    const slot = document.getElementById('m-content');
    if (!slot) {
      // Vue détruite — on coupe le timer
      if (this._refreshTimer) { clearInterval(this._refreshTimer); this._refreshTimer = null; }
      return;
    }
    if (document.hidden) return; // onglet pas visible → on saute
    if (!App.api) return;

    let digest = null;
    try { digest = await App.api.get_morning_digest(); } catch (e) {}
    if (!digest || !digest.ok) return;

    // Voyant système
    const alerts = (digest.alerts && (digest.alerts.convoy_failed_today + digest.alerts.convoy_failed_yesterday)) || 0;
    if (alerts > 0) {
      this._setSystemLed('alert', `SYSTÈME · ${alerts} ALERTE${alerts > 1 ? 'S' : ''}`);
    } else {
      this._setSystemLed('ok', 'SYSTÈME · OPÉRATIONNEL');
    }

    // L'écran avait raté son premier chargement (carte « hors ligne ») et
    // la connexion est revenue : on reconstruit le contenu complet.
    if (!slot.querySelector('.cockpit-hero')) {
      slot.innerHTML = `<div id="m-setup-slot"></div>`
                     + this._renderHero(digest)
                     + `<div id="m-pipelines-slot"></div>`
                     + `<div id="m-obelisk-slot"></div>`
                     + this._renderKpiGrid(digest)
                     + `<div id="m-modes-slot"></div>`
                     + this._renderAlert(digest)
                     + `<div id="m-linkedin-slot"></div>`;
      this._loadSetup();
      this._loadPipelinesActivity();
      this._loadObeliskNotifs();
      this._loadModes();
      this._loadLinkedinActions();
      return;
    }

    // Reconstitue uniquement les blocs d'affichage (hero, KPI, alerte).
    // On ne touche pas aux modes ni au bloc LinkedIn (ils s'auto-rafraîchissent).
    const heroEl = slot.querySelector('.cockpit-hero');
    if (heroEl) {
      const tmp = document.createElement('div');
      tmp.innerHTML = this._renderHero(digest);
      const fresh = tmp.firstElementChild;
      if (fresh) heroEl.replaceWith(fresh);
    }
    const gridEl = slot.querySelector('.cockpit-grid');
    if (gridEl) {
      const tmp = document.createElement('div');
      tmp.innerHTML = this._renderKpiGrid(digest);
      const fresh = tmp.firstElementChild;
      if (fresh) gridEl.replaceWith(fresh);
    }

    // Alerte : peut apparaître / disparaître entre deux refresh.
    // On la place toujours juste avant le slot LinkedIn pour préserver l'ordre.
    const linkedinSlot = document.getElementById('m-linkedin-slot');
    const existingAlert = slot.querySelector('.cockpit-alert');
    const newAlertHTML = this._renderAlert(digest);
    if (newAlertHTML && newAlertHTML.trim()) {
      const tmp = document.createElement('div');
      tmp.innerHTML = newAlertHTML;
      const fresh = tmp.firstElementChild;
      if (fresh) {
        if (existingAlert) existingAlert.replaceWith(fresh);
        else if (linkedinSlot) linkedinSlot.parentNode.insertBefore(fresh, linkedinSlot);
      }
    } else if (existingAlert) {
      existingAlert.remove();
    }
  },

  // -------- Bloc PIPELINES — mouvements depuis la dernière visite --------
  async _loadPipelinesActivity() {
    const slot = document.getElementById('m-pipelines-slot');
    if (!slot) return;
    if (typeof PipelinesActivity === 'undefined') return;
    // Force un check immédiat pour avoir des données fraîches au load
    await PipelinesActivity.checkAll();
    PipelinesActivity.renderCockpitPanel(slot);
  },

  // -------- Bloc OBELISK — notifs de fin de recherche --------
  async _loadObeliskNotifs() {
    const slot = document.getElementById('m-obelisk-slot');
    if (!slot) return;
    if (typeof Obelisk === 'undefined' || !Obelisk.checkNotifs) return;
    const data = await Obelisk.checkNotifs();
    const count = data.count || 0;
    if (count === 0) { slot.innerHTML = ''; return; }
    const jobs = data.jobs || [];
    const headline = count === 1
      ? '1 nouvelle vague de prospection terminée'
      : `${count} nouvelles vagues de prospection terminées`;
    const itemsHtml = jobs.slice(0, 3).map(j => {
      const stats = j.stats || {};
      const found = (stats.found || 0) + (stats.phantom_inserted || 0);
      const platforms = (j.platforms || []).join(' · ') || '—';
      return `
        <li class="cockpit-obnotif-item">
          <div class="cockpit-obnotif-niche">${this._esc(j.niche || '(sans niche)')}</div>
          <div class="cockpit-obnotif-meta">
            <span>${found} profil${found > 1 ? 's' : ''}</span>
            <span>·</span>
            <span>${this._esc(platforms)}</span>
          </div>
        </li>
      `;
    }).join('');
    slot.innerHTML = `
      <div class="cockpit-obnotif">
        <div class="cockpit-obnotif-head">
          <div>
            <div class="cockpit-obnotif-kicker">PROSPECTION TERMINÉE</div>
            <h3 class="cockpit-obnotif-title">${headline}</h3>
          </div>
          <button class="btn btn-primary" onclick="App.show('obelisk')">
            Voir les profils →
          </button>
        </div>
        <ul class="cockpit-obnotif-list">${itemsHtml}</ul>
      </div>
    `;
  },

  _esc(s) {
    if (s == null) return '';
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
                     .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  },

  // -------- Bloc MODES — bascule envoi direct ↔ validation --------
  async _loadModes() {
    if (!App.api) return;
    const slot = document.getElementById('m-modes-slot');
    if (!slot) return;
    let modes = { prospection: 'validation', reponses: 'validation' };
    try {
      const r = await App.api.get_simple_modes();
      if (r && r.ok) modes = { prospection: r.prospection, reponses: r.reponses };
    } catch (e) {}
    slot.innerHTML = this._renderModes(modes);
    this._bindModes();
  },

  _renderModes(m) {
    return `
      <div class="cockpit-modes">
        <div class="cockpit-modes-head">
          <span class="cockpit-modes-title">RÉPONSES AUTO</span>
          <span class="cockpit-modes-sub">Bascule en 1 clic — l'app applique tout de suite</span>
        </div>
        <div class="cockpit-modes-grid">
          ${this._modeCard({
            kind: 'reponses',
            title: 'Réponses aux mails reçus',
            sub: 'Les réponses que l’IA prépare aux gens qui t’ont écrit',
            current: m.reponses,
          })}
        </div>
      </div>
    `;
  },

  _modeCard({ kind, title, sub, current }) {
    const isDirect = current === 'direct';
    const isOff = current === 'off';
    const isValid = !isDirect && !isOff;
    return `
      <div class="cockpit-mode-card" data-kind="${kind}" data-current="${current}">
        <div class="cockpit-mode-card-head">
          <span class="cockpit-mode-card-title">${title}</span>
          <span class="cockpit-mode-card-sub">${sub}</span>
        </div>
        <div class="cockpit-mode-switch cockpit-mode-switch-3" role="group" aria-label="Choisir un mode">
          <button type="button"
                  class="cockpit-mode-opt ${isOff ? 'active off' : ''}"
                  data-mode="off"
                  title="Le robot ne fait rien, tu réponds toi-même depuis ta boîte mail">
            <span class="cockpit-mode-opt-icon">⏸️</span>
            <span class="cockpit-mode-opt-label">Désactivé</span>
          </button>
          <button type="button"
                  class="cockpit-mode-opt ${isValid ? 'active' : ''}"
                  data-mode="validation"
                  title="L'app te montre les mails, tu valides avant envoi">
            <span class="cockpit-mode-opt-icon">✅</span>
            <span class="cockpit-mode-opt-label">Je valide</span>
          </button>
          <button type="button"
                  class="cockpit-mode-opt risky ${isDirect ? 'active danger' : ''}"
                  data-mode="direct"
                  title="L'IA envoie tout de suite, sans relecture par toi — à activer en connaissance de cause">
            <span class="cockpit-mode-opt-icon">⚡</span>
            <span class="cockpit-mode-opt-label">Envoi direct</span>
          </button>
        </div>
      </div>
    `;
  },

  _bindModes() {
    const slot = document.getElementById('m-modes-slot');
    if (!slot) return;
    slot.querySelectorAll('.cockpit-mode-card').forEach(card => {
      const kind = card.dataset.kind;
      card.querySelectorAll('.cockpit-mode-opt').forEach(btn => {
        btn.onclick = async () => {
          const target = btn.dataset.mode;
          if (card.dataset.current === target) return;
          if (target === 'direct') {
            const ok = await Dialog.confirm(
              'L’IA répondra toute seule aux mails reçus, sans te demander. '
              + 'Si une réponse est mal ajustée, elle partira quand même : '
              + 'personne ne relit avant l’envoi.\n\n'
              + 'Tu peux revenir à « Je valide » à tout moment.',
              { title: 'Passer en envoi direct ?', okLabel: 'Oui, envoi direct',
                cancelLabel: 'Annuler', danger: true });
            if (!ok) return;
          }
          card.querySelectorAll('.cockpit-mode-opt').forEach(b => {
            b.classList.remove('active', 'danger', 'off');
          });
          btn.classList.add('active');
          if (target === 'direct') btn.classList.add('danger');
          if (target === 'off') btn.classList.add('off');
          card.dataset.current = target;
          try {
            const r = await App.api.set_simple_mode({ kind, mode: target });
            if (!r || !r.ok) {
              if (r && r.error) console.warn('set_simple_mode:', r.error);
              Toast.error('La bascule n’a pas été prise en compte. Réessaie dans un instant.');
              this._loadModes();
            } else {
              Toast.success(target === 'direct'
                ? 'Envoi direct activé pour les réponses.'
                : target === 'off'
                  ? 'Réponses automatiques désactivées.'
                  : 'Les réponses repassent par ta validation.');
            }
          } catch (e) {
            Toast.friendlyError(e, 'La bascule n’a pas été prise en compte.');
            this._loadModes();
          }
        };
      });
    });
  },

  // -------- Horloge live (mise à jour seconde par seconde) --------
  _startClock() {
    const tick = () => {
      const el = document.getElementById('m-clock');
      if (!el) {
        if (this._clockTimer) clearInterval(this._clockTimer);
        return;
      }
      const d = new Date();
      const hh = String(d.getHours()).padStart(2, '0');
      const mm = String(d.getMinutes()).padStart(2, '0');
      const ss = String(d.getSeconds()).padStart(2, '0');
      el.textContent = `${hh}:${mm}:${ss}`;
    };
    tick();
    if (this._clockTimer) clearInterval(this._clockTimer);
    this._clockTimer = setInterval(tick, 1000);
  },

  // -------- Encadré "auto-pilote en cours" --------
  // Poll toutes les 3s tant qu'on est sur le Cockpit. Affiche un bandeau
  // en haut du contenu quand un run est en cours, le cache sinon.
  _startAutopilotPoll() {
    if (this._apPollTimer) clearInterval(this._apPollTimer);
    const tick = async () => {
      const slot = document.getElementById('m-autopilot-live');
      if (!slot) {
        // On a quitté le Cockpit : on arrête le poll
        if (this._apPollTimer) clearInterval(this._apPollTimer);
        this._apPollTimer = null;
        return;
      }
      if (!App.api || !App.api.autopilot_status) return;
      let r;
      try { r = await App.api.autopilot_status({ since: 0 }); }
      catch (e) { return; }
      if (!r || !r.ok) return;
      if (r.running) {
        slot.innerHTML = this._renderAutopilotLive(r);
        slot.classList.remove('hidden');
        // Click sur la carte → ouvre la page Auto-pilote (sauf clic exact
        // sur le bouton "Voir le détail", géré séparément)
        const card = slot.querySelector('[data-ap-card]');
        if (card) card.style.cursor = 'pointer';
        if (card) card.onclick = (ev) => {
          if (!(ev.target.closest('button'))) App.show('autopilot');
        };
        const btn = slot.querySelector('[data-ap-open]');
        if (btn) btn.onclick = () => App.show('autopilot');
      } else {
        slot.innerHTML = '';
        slot.classList.add('hidden');
      }
    };
    tick();
    this._apPollTimer = setInterval(tick, 3000);
  },

  _renderAutopilotLive(state) {
    const stages = state.stages || {};
    const order = ['search', 'sort', 'write', 'review', 'send'];
    const labels = {
      search: 'Cherche',
      sort:   'Trie',
      write:  'Rédige',
      review: 'Relit',
      send:   'Envoie',
    };
    // % d'avancement global : chaque maillon vaut 20 %. Pour celui en cours
    // on prend 50 % de son poids ; pour les terminés, 100 % de leur poids.
    let done = 0, currentRatio = 0, currentKey = '';
    for (const k of order) {
      const s = stages[k] || {};
      if (s.state === 'done') { done += 1; continue; }
      if (s.state === 'running') { currentKey = k; currentRatio = 0.5; break; }
      if (s.state === 'error') { currentKey = k; currentRatio = 0; break; }
      currentKey = k; currentRatio = 0; break;
    }
    const pct = Math.max(0, Math.min(100, Math.round(((done + currentRatio) / order.length) * 100)));
    // Chips pour les 5 maillons : couleur selon l'état
    const chips = order.map(k => {
      const s = stages[k] || {};
      const st = s.state || 'idle';
      const cnt = (typeof s.count === 'number' && s.count > 0) ? ` · ${s.count}` : '';
      let cls = 'text-text-muted bg-bg border-border';
      let icon = '';
      if (st === 'done') {
        cls = 'text-success bg-success/10 border-success/30';
        icon = '✓ ';
      } else if (st === 'running') {
        cls = 'text-accent bg-accent/10 border-accent/40';
        icon = '<span class="inline-block w-2 h-2 rounded-full bg-accent animate-pulse mr-1.5"></span>';
      } else if (st === 'error') {
        cls = 'text-danger bg-danger/10 border-danger/30';
        icon = '✗ ';
      }
      return `<span class="text-[11px] px-2 py-1 rounded-full border ${cls} inline-flex items-center">${icon}${labels[k]}${cnt}</span>`;
    }).join('');
    const activity = state.current_activity
      || (stages[currentKey] && stages[currentKey].message)
      || 'En cours…';
    return `
      <div class="card p-5 relative overflow-hidden" data-ap-card
           style="border-color: hsl(var(--accent) / 0.4);">
        <!-- Bandeau accent en haut, comme les cartes de l'écran Auto-pilote -->
        <div class="absolute top-0 left-0 right-0 h-1 bg-accent"></div>
        <div class="flex items-start gap-4 flex-wrap sm:flex-nowrap">
          <span class="inline-block w-9 h-9 rounded-full border-[3px] border-accent/30 border-t-accent animate-spin flex-shrink-0 mt-1"></span>
          <div class="flex-1 min-w-0">
            <div class="text-[11px] font-bold uppercase tracking-widest text-accent mb-1">
              L'auto-pilote tourne
            </div>
            <div class="text-sm text-text mb-3" style="text-wrap: pretty">${this._esc(activity)}</div>
            <div class="flex flex-wrap gap-2 mb-3">${chips}</div>
            <div class="flex items-center gap-3">
              <div class="flex-1 h-1.5 rounded-full bg-bg border border-border overflow-hidden">
                <div class="h-full bg-accent transition-all duration-500 ease-out" style="width: ${pct}%"></div>
              </div>
              <span class="text-xs font-bold text-accent">${pct}%</span>
            </div>
          </div>
          <button data-ap-open class="btn btn-secondary flex-shrink-0 self-start"
                  style="border-color: hsl(var(--accent) / 0.4); color: hsl(var(--accent));">
            Voir le détail →
          </button>
        </div>
      </div>
    `;
  },

  // -------- Encadré "envoi en série en cours" --------
  // Même approche que l'auto-pilote : un poll toutes les 3s tant qu'on est
  // sur le Cockpit, affiche un bandeau quand un envoi tourne, le cache sinon.
  _startDraftsBatchPoll() {
    if (this._dbPollTimer) clearInterval(this._dbPollTimer);
    const tick = async () => {
      const slot = document.getElementById('m-drafts-batch-live');
      if (!slot) {
        if (this._dbPollTimer) clearInterval(this._dbPollTimer);
        this._dbPollTimer = null;
        return;
      }
      if (!App.api || !App.api.drafts_send_all_status) return;
      let s;
      try { s = await App.api.drafts_send_all_status({}); }
      catch (e) { return; }
      if (!s || !s.ok) return;
      if (s.running) {
        slot.innerHTML = this._renderDraftsBatchLive(s);
        slot.classList.remove('hidden');
        const card = slot.querySelector('[data-db-card]');
        if (card) card.style.cursor = 'pointer';
        if (card) card.onclick = (ev) => {
          if (!(ev.target.closest('button'))) App.show('drafts');
        };
        const btn = slot.querySelector('[data-db-open]');
        if (btn) btn.onclick = (ev) => {
          ev.stopPropagation();
          App.show('drafts');
        };
        const stopBtn = slot.querySelector('[data-db-stop]');
        if (stopBtn) stopBtn.onclick = async (ev) => {
          ev.stopPropagation();
          if (this._dbStopRequested) return;
          if (!App.api.drafts_send_all_stop) return;
          const ok = await Dialog.confirm(
            'Les mails déjà partis le restent ; les suivants ne partiront pas.',
            { title: 'Arrêter l’envoi en série ?', okLabel: 'Arrêter',
              cancelLabel: 'Continuer l’envoi', danger: true });
          if (!ok) return;
          // L'état « arrêt en cours » survit aux re-rendus du poll : on le
          // garde dans un drapeau, relâché quand le serveur dit "fini".
          this._dbStopRequested = true;
          stopBtn.disabled = true;
          stopBtn.textContent = 'Arrêt en cours…';
          try {
            await App.api.drafts_send_all_stop({});
          } catch (e) {
            this._dbStopRequested = false;
            Toast.friendlyError(e, 'L’arrêt n’a pas été pris en compte.');
          }
        };
      } else {
        if (this._dbStopRequested) {
          this._dbStopRequested = false;
          Toast.success('Envoi en série arrêté.');
        }
        slot.innerHTML = '';
        slot.classList.add('hidden');
      }
    };
    tick();
    this._dbPollTimer = setInterval(tick, 3000);
  },

  _renderDraftsBatchLive(s) {
    const total = s.total || 0;
    const sent = s.sent || 0;
    const errors = s.errors || 0;
    const done = sent + errors;
    const remaining = Math.max(0, total - done);
    const pct = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0;
    const current = s.current_name || s.current_email || '';
    return `
      <div class="card p-5 relative overflow-hidden" data-db-card
           style="border-color: hsl(var(--accent) / 0.4);">
        <div class="absolute top-0 left-0 right-0 h-1 bg-accent"></div>
        <div class="flex items-start gap-4 flex-wrap sm:flex-nowrap">
          <span class="inline-block w-9 h-9 rounded-full border-[3px] border-accent/30 border-t-accent animate-spin flex-shrink-0 mt-1"></span>
          <div class="flex-1 min-w-0">
            <div class="text-[11px] font-bold uppercase tracking-widest text-accent mb-1">
              Envoi en série des brouillons
            </div>
            <div class="text-sm text-text mb-3" style="text-wrap: pretty">
              ${current
                ? `En cours : <strong>${this._esc(current)}</strong>`
                : 'Préparation…'}
            </div>
            <div class="grid grid-cols-2 sm:grid-cols-4 gap-3 sm:gap-4 mb-3">
              <div class="text-center">
                <div class="text-[10px] font-bold uppercase tracking-widest text-text-muted">Envoyés</div>
                <div class="text-2xl font-bold text-success mt-1">${sent}</div>
              </div>
              <div class="text-center">
                <div class="text-[10px] font-bold uppercase tracking-widest text-text-muted">Échecs</div>
                <div class="text-2xl font-bold text-danger mt-1">${errors}</div>
              </div>
              <div class="text-center">
                <div class="text-[10px] font-bold uppercase tracking-widest text-text-muted">Restants</div>
                <div class="text-2xl font-bold text-accent mt-1">${remaining}</div>
              </div>
              <div class="text-center">
                <div class="text-[10px] font-bold uppercase tracking-widest text-text-muted">Total</div>
                <div class="text-2xl font-bold text-text mt-1">${total}</div>
              </div>
            </div>
            <div class="flex items-center gap-3">
              <div class="flex-1 h-1.5 rounded-full bg-bg border border-border overflow-hidden">
                <div class="h-full bg-accent transition-all duration-500 ease-out" style="width: ${pct}%"></div>
              </div>
              <div class="text-xs text-text-muted font-mono w-12 text-right">${pct}%</div>
            </div>
          </div>
          <div class="flex flex-col gap-2 flex-shrink-0 self-start">
            <button data-db-open class="btn btn-secondary"
                    style="border-color: hsl(var(--accent) / 0.4); color: hsl(var(--accent));">
              Voir →
            </button>
            <button data-db-stop class="btn btn-secondary" ${this._dbStopRequested ? 'disabled' : ''}
                    style="border-color: hsl(var(--danger) / 0.5); color: hsl(var(--danger-text));">
              ${this._dbStopRequested ? 'Arrêt en cours…' : 'Arrêter'}
            </button>
          </div>
        </div>
      </div>
    `;
  },

  _setSystemLed(state, label) {
    const el = document.getElementById('m-led-system');
    if (!el) return;
    el.classList.remove('alert', 'warn');
    if (state === 'alert') el.classList.add('alert');
    else if (state === 'warn') el.classList.add('warn');
    el.textContent = label;
  },

  // -------- HERO : la mission du jour --------
  _renderHero(d) {
    const q = d.queue || {};
    const nInt = q.replies_unhandled_interested || 0;
    const nTotal = q.replies_unhandled_total || 0;
    const nDraftsP = q.drafts_prospect_pending || 0;
    const nDraftsC = q.drafts_convoy_pending || 0;
    const nDrafts = nDraftsP + nDraftsC;
    const nReview = q.drafts_convoy_needs_review || 0;

    let kicker, title, body, cta, target, state;
    if (nReview > 0) {
      kicker = '⚠ MAILS BLOQUÉS — À VÉRIFIER';
      title  = nReview === 1
        ? '1 mail bloqué (info manquante, ex. prénom)'
        : `${nReview} mails bloqués (infos manquantes, ex. prénom)`;
      body   = "Le système a refusé d'envoyer ces mails parce qu'il manquait des infos (genre prénom). Ouvre-les pour les compléter ou les supprimer.";
      cta    = 'Voir les mails bloqués →';
      target = 'drafts';
      state  = 'warn';
    } else if (nInt > 0) {
      kicker = 'EN CHASSE — PRIORITÉ MAXIMALE';
      title  = nInt === 1
        ? '1 prospect intéressé à recontacter'
        : `${nInt} prospects intéressés à recontacter`;
      body   = "Ils ont mordu. C'est ta meilleure piste pour transformer aujourd'hui — ne les laisse pas refroidir.";
      cta    = 'Voir leurs réponses →';
      target = 'replies';
      state  = 'success';
    } else if (nDrafts > 0) {
      kicker = 'À LANCER EN PREMIER';
      title  = nDrafts === 1
        ? '1 brouillon à valider'
        : `${nDrafts} brouillons à valider`;
      body   = "Des mails préparés par l'app attendent ton OK. Tu peux les approuver en lot.";
      cta    = 'Valider les brouillons →';
      target = 'drafts';
      state  = 'accent';
    } else if (nTotal > 0) {
      kicker = 'À TRIER';
      title  = nTotal === 1
        ? '1 réponse à examiner'
        : `${nTotal} réponses à examiner`;
      body   = "Pas maintenant, refus, désinscriptions — un coup d'œil rapide suffit pour les classer.";
      cta    = 'Voir les réponses →';
      target = 'replies';
      state  = 'warn';
    } else {
      kicker = 'TOUT EST À JOUR';
      title  = "Le terrain est dégagé.";
      body   = "Aucune réponse à traiter, aucun brouillon en attente. Lance une nouvelle vague — c'est le bon moment.";
      cta    = 'Lancer une prospection →';
      target = 'prospection';
      state  = 'accent';
    }

    return `
      <div class="cockpit-hero" data-state="${state}">
        <div class="cockpit-hero-text">
          <div class="cockpit-hero-kicker">${kicker}</div>
          <h2 class="cockpit-hero-title">${title}</h2>
          <p class="cockpit-hero-body">${body}</p>
        </div>
        <button class="btn btn-primary" onclick="App.show('${target}')">${cta}</button>
      </div>
    `;
  },

  // -------- Grille 4 KPIs principaux --------
  _renderKpiGrid(d) {
    const sentT = d.sent.today;
    const sentY = d.sent.yesterday;
    const sentW = d.sent.last_7d;
    const daily = d.sent.daily_last_7d || [];
    const repT  = d.replies.today_total;
    const repY  = d.replies.yesterday_total;
    const q = d.queue || {};
    const nInt = q.replies_unhandled_interested || 0;
    const nDrafts = (q.drafts_prospect_pending || 0) + (q.drafts_convoy_pending || 0);

    return `
      <div class="cockpit-grid">
        ${this._kpi({
          label: 'Envoyés aujourd’hui',
          value: sentT,
          tag: sentT > 0 ? 'LIVE' : null,
          delta: `<strong>${sentY}</strong> hier · <strong>${sentW}</strong> sur 7 jours`,
          spark: daily,
          onClick: `App.show('mails', { tab: 'sent' })`,
          hint: 'Voir les messages envoyés',
        })}
        ${this._kpi({
          label: 'Réponses aujourd’hui',
          value: repT,
          tag: repT > 0 ? 'LIVE' : null,
          delta: `<strong>${repY}</strong> hier · taux ${sentY ? Math.round(100*repY/sentY) : 0} %`,
          tone: repT > 0 ? 'success' : '',
          onClick: `if(window.Replies){Replies.filter='all';} App.show('replies')`,
          hint: 'Voir toutes les réponses',
        })}
        ${this._kpi({
          label: 'Intéressés en file',
          value: nInt,
          delta: nInt === 0 ? 'rien à relancer là tout de suite' : 'à recontacter — chaud',
          tone: nInt > 0 ? 'success' : '',
          onClick: `if(window.Replies){Replies.filter='interested';} App.show('replies')`,
          hint: 'Voir les prospects intéressés',
        })}
        ${this._kpi({
          label: 'Brouillons à valider',
          value: nDrafts,
          delta: nDrafts === 0 ? 'rien en attente' : 'prêts à approuver',
          tone: nDrafts > 0 ? 'accent' : '',
          onClick: `App.show('drafts')`,
          hint: 'Voir les brouillons',
        })}
      </div>
    `;
  },

  _kpi({ label, value, tag, delta, tone, spark, onClick, hint }) {
    const toneCls = tone ? `tone-${tone}` : '';
    const clickCls = onClick ? 'is-clickable' : '';
    const tagHtml = tag ? `<span class="cockpit-kpi-tag live">${tag}</span>` : '';
    const sparkHtml = (spark && spark.length) ? this._sparkline(spark) : '';
    const clickAttrs = onClick
      ? `role="button" tabindex="0" title="${hint || ''}" onclick="${onClick}" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();${onClick}}"`
      : '';
    return `
      <div class="cockpit-kpi ${toneCls} ${clickCls}" ${clickAttrs}>
        <div class="cockpit-kpi-head">
          <span class="cockpit-kpi-label">${label}</span>
          ${tagHtml}
        </div>
        <div class="cockpit-kpi-value">${value}</div>
        ${delta ? `<div class="cockpit-kpi-delta">${delta}</div>` : ''}
        ${sparkHtml}
        ${onClick ? `<span class="cockpit-kpi-arrow" aria-hidden="true">→</span>` : ''}
      </div>
    `;
  },

  _sparkline(values) {
    const max = Math.max(1, ...values);
    const bars = values.map((v, i) => {
      const h = Math.max(2, Math.round((v / max) * 28));
      const today = (i === values.length - 1) ? 'today' : '';
      return `<div class="cockpit-spark-bar ${today}" style="height:${h}px;" title="${v}"></div>`;
    }).join('');
    return `<div class="cockpit-spark">${bars}</div>`;
  },

  // -------- Bloc Alerte (conditionnel) --------
  _renderAlert(d) {
    const a = d.alerts || {};
    const fY = a.convoy_failed_yesterday || 0;
    const fT = a.convoy_failed_today || 0;
    const total = fY + fT;
    if (total === 0) return '';
    return `
      <div class="cockpit-alert">
        <div class="cockpit-alert-icon">!</div>
        <div class="flex-1">
          <h3 class="text-base font-bold mb-1">${total === 1 ? '1 mail non parti' : `${total} mails non partis`}</h3>
          <p class="text-sm text-text-secondary mb-3">
            Un problème de configuration mail ou de destinataire bloque la diffusion.
          </p>
          <button class="btn btn-secondary" onclick="App.show('convoy')">Voir dans Le Convoi →</button>
        </div>
      </div>
    `;
  },

  // -------- Bloc LinkedIn (chargé en différé) --------
  async _loadLinkedinActions() {
    if (!App.api) return;
    let actions = [];
    try {
      const r = await App.api.multichannel_get_actions();
      if (r && r.ok) actions = r.actions || [];
    } catch (e) {}
    const slot = document.getElementById('m-linkedin-slot');
    if (!slot) return;
    if (actions.length === 0) { slot.innerHTML = ''; return; }
    slot.innerHTML = `
      <div class="cockpit-orders">
        <div class="cockpit-orders-head">
          <div class="cockpit-orders-title">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><rect x="2" y="2" width="20" height="20" rx="5"/><line x1="8" y1="11" x2="8" y2="16"/><circle cx="8" cy="8" r="0.5"/><path d="M12 16v-3a3 3 0 016 0v3"/></svg>
            Ordres LinkedIn
            <span class="cockpit-orders-count">${actions.length}</span>
          </div>
          <button id="m-li-dispatch-all"
                  class="btn btn-primary"
                  style="font-size:12px;padding:7px 12px;">
            ⚡ Tout envoyer via Phantombuster
          </button>
        </div>
        <div class="cockpit-orders-body">
          <p class="text-sm text-text-muted mb-4">
            Ces prospects n'ont pas répondu à ton mail. L'IA a préparé un message
            LinkedIn court — 3 clics et c'est envoyé.
          </p>
          <div class="space-y-3" id="m-linkedin-list">
            ${actions.slice(0, 8).map(a => this._linkedinCard(a)).join('')}
          </div>
          ${actions.length > 8
            ? `<div class="text-xs text-text-muted mt-3">+ ${actions.length - 8} autres relances en file.</div>`
            : ''}
        </div>
      </div>
    `;
    this._bindLinkedinActions();
    this._bindDispatchAll();
  },

  _bindDispatchAll() {
    const btn = document.getElementById('m-li-dispatch-all');
    if (!btn) return;
    btn.onclick = async () => {
      if (!App.api) return;
      const ok = await Dialog.confirm(
        "Toutes les relances en attente partiront via Phantombuster, "
        + "à raison d’environ 25 par jour pour protéger ton compte LinkedIn.\n\n"
        + "Si Phantombuster n’est pas encore branché, passe d’abord par Réglages.",
        { title: 'Envoyer toutes les relances LinkedIn ?',
          okLabel: 'Tout envoyer', cancelLabel: 'Annuler' });
      if (!ok) return;
      btn.disabled = true; btn.textContent = 'Envoi…';
      try {
        const r = await App.api.multichannel_dispatch_phantombuster();
        if (r && r.ok) {
          btn.textContent = `✓ ${r.launched} envoyés`;
          Toast.success(`${r.launched} relance(s) confiée(s) à Phantombuster.`);
          if (r.note) Toast.info(r.note);
        } else {
          if (r && r.error) console.warn('dispatch phantombuster:', r.error);
          Toast.error('Les relances ne sont pas parties. Vérifie Phantombuster dans Réglages.');
          btn.disabled = false;
          btn.textContent = '⚡ Tout envoyer via Phantombuster';
        }
      } catch (e) {
        Toast.friendlyError(e, 'Les relances ne sont pas parties.');
        btn.disabled = false;
        btn.textContent = '⚡ Tout envoyer via Phantombuster';
      }
      setTimeout(() => this._loadLinkedinActions(), 1200);
    };
  },

  _linkedinCard(a) {
    const name = a.prospect_name || '(prospect)';
    const meta = [a.prospect_city, a.prospect_industry].filter(Boolean).join(' · ');
    return `
      <article class="border border-border rounded-xl p-4" data-act-id="${this._escAttr(a.id)}">
        <div class="flex items-start justify-between gap-3 mb-2">
          <div>
            <div class="font-semibold text-sm">${this._escHtml(name)}</div>
            ${meta ? `<div class="text-[11px] text-text-muted">${this._escHtml(meta)}</div>` : ''}
          </div>
          <button class="text-text-muted hover:text-danger text-xl leading-none px-1" data-li-discard
                  title="Supprimer cette suggestion">×</button>
        </div>
        <pre class="whitespace-pre-wrap font-sans text-sm text-text-secondary
                    bg-bg/50 border border-border rounded-lg p-3 mb-3 leading-relaxed">${this._escHtml(a.message || '')}</pre>
        <div class="flex flex-wrap gap-2">
          <button class="text-xs px-2.5 py-1.5 rounded-lg bg-accent/10 text-accent border border-accent/30 hover:bg-accent/20"
                  data-li-copy>📋 Copier le message</button>
          ${a.search_url ? `
          <a href="${this._escAttr(a.search_url)}" target="_blank"
             class="text-xs px-2.5 py-1.5 rounded-lg bg-surface-elevated border border-border hover:border-accent text-text-secondary hover:text-text">
            🔍 Trouver son LinkedIn
          </a>` : ''}
          ${a.platform_url ? `
            <a href="${this._escAttr(a.platform_url)}" target="_blank"
               class="text-xs px-2.5 py-1.5 rounded-lg bg-surface-elevated border border-border hover:border-accent text-text-secondary hover:text-text">
              ↗ Profil source
            </a>` : ''}
          <div class="flex-1"></div>
          <button class="text-xs px-2.5 py-1.5 rounded-lg bg-success/10 text-success border border-success/30 hover:bg-success/20"
                  data-li-done>✓ Fait</button>
        </div>
      </article>
    `;
  },

  _bindLinkedinActions() {
    document.querySelectorAll('[data-act-id]').forEach(card => {
      const id = card.dataset.actId;
      const copyBtn = card.querySelector('[data-li-copy]');
      const doneBtn = card.querySelector('[data-li-done]');
      const discardBtn = card.querySelector('[data-li-discard]');
      if (copyBtn) copyBtn.onclick = () => {
        const pre = card.querySelector('pre');
        const txt = (pre && pre.textContent) || '';
        navigator.clipboard.writeText(txt).then(() => {
          copyBtn.textContent = '✓ Copié';
          setTimeout(() => copyBtn.innerHTML = '📋 Copier le message', 1400);
        }).catch(() => {
          // Copie auto refusée par le navigateur : on sélectionne le texte
          // pour que Ctrl+C marche du premier coup.
          try {
            const range = document.createRange();
            range.selectNodeContents(pre);
            const sel = window.getSelection();
            sel.removeAllRanges();
            sel.addRange(range);
            Toast.info('Le message est sélectionné — fais Ctrl+C pour le copier.');
          } catch (e2) {
            Toast.error('Impossible de copier ce message.');
          }
        });
      };
      if (doneBtn) doneBtn.onclick = async () => {
        if (!App.api) return;
        doneBtn.disabled = true;
        try {
          await App.api.multichannel_mark_done({ id });
          card.style.opacity = '0';
          setTimeout(() => this._loadLinkedinActions(), 250);
        } catch (e) {
          doneBtn.disabled = false;
          Toast.friendlyError(e, 'Impossible de marquer cette relance comme faite.');
        }
      };
      if (discardBtn) discardBtn.onclick = async () => {
        if (!App.api) return;
        const ok = await Dialog.confirm(
          'Cette suggestion de relance disparaîtra de la liste.',
          { title: 'Supprimer cette suggestion ?', okLabel: 'Supprimer',
            cancelLabel: 'Garder', danger: true });
        if (!ok) return;
        discardBtn.disabled = true;
        try {
          await App.api.multichannel_discard({ id });
          card.style.opacity = '0';
          setTimeout(() => this._loadLinkedinActions(), 250);
        } catch (e) {
          discardBtn.disabled = false;
          Toast.friendlyError(e, 'Impossible de supprimer cette suggestion.');
        }
      };
    });
  },

  // -------- Compose choice modale (gardée intacte) --------
  _openComposeChoice() {
    const ov = document.createElement('div');
    ov.className = 'fixed inset-0 z-[210] flex items-center justify-center p-4';
    ov.style.background = 'rgba(15,23,42,0.78)';
    ov.style.backdropFilter = 'blur(10px)';
    ov.innerHTML = `
      <div class="bg-surface rounded-2xl shadow-hero w-full max-w-lg border border-border animate-slide-up overflow-hidden"
           role="dialog" aria-modal="true" aria-labelledby="cc-title">
        <div class="px-6 pt-5 pb-4 flex items-start justify-between border-b border-border bg-surface-elevated">
          <div>
            <div class="text-[11px] font-bold uppercase tracking-widest text-text-muted mb-0.5">COMPOSER UN MAIL</div>
            <h3 id="cc-title" class="text-lg font-bold">Que veux-tu écrire ?</h3>
            <p class="text-xs text-text-muted mt-1">Mail classique, ou présentation d'un site déjà réalisé pour la cible.</p>
          </div>
          <button id="cc-close" title="Fermer" aria-label="Fermer"
                  class="w-8 h-8 rounded-lg flex items-center justify-center text-text-muted hover:text-text hover:bg-bg text-xl leading-none shrink-0">×</button>
        </div>
        <div class="p-5 grid grid-cols-1 sm:grid-cols-2 gap-3">
          <button data-cc="new"
                  class="text-left p-5 rounded-2xl border-2 border-border hover:border-accent hover:bg-accent/5 transition-all">
            <div class="w-10 h-10 rounded-xl bg-accent/15 text-accent flex items-center justify-center mb-3">
              <svg class="w-5 h-5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 113 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>
            </div>
            <div class="text-base font-bold text-text">Nouveau mail</div>
            <div class="text-xs text-text-muted mt-1 leading-snug">Composer un mail vierge : tu écris tout, choisis ton expéditeur, tes pièces jointes, ta signature.</div>
          </button>
          <button data-cc="prospect"
                  class="text-left p-5 rounded-2xl border-2 border-border hover:border-accent transition-all relative overflow-hidden"
                  style="background: linear-gradient(135deg, hsl(var(--accent) / 0.08), rgba(232,93,44,0.08));">
            <div class="w-10 h-10 rounded-xl flex items-center justify-center mb-3 text-white shadow-soft"
                 style="background: linear-gradient(135deg, #7c6acc, #e85d2c);">
              <svg class="w-5 h-5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>
            </div>
            <div class="text-base font-bold text-text">Prospection en direct</div>
            <div class="text-xs text-text-muted mt-1 leading-snug">Tu colles l'URL d'un site que tu as fait pour une célébrité ou une entreprise — Claude rédige le mail de présentation.</div>
          </button>
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
    ov.querySelector('#cc-close').onclick = close;
    ov.addEventListener('click', (e) => { if (e.target === ov) close(); });

    // Bascule vers la messagerie puis ouvre le composeur quand il est
    // VRAIMENT prêt (avant : pari sur un délai fixe de 200 ms, qui ratait
    // sur connexion lente). On réessaie ~2 s max, puis on prévient.
    const goMails = (cb) => {
      close();
      const ready = () => typeof Mails !== 'undefined'
        && typeof Mails._openComposer === 'function'
        && !!document.querySelector('[data-mtab]');
      if (App.currentView === 'mails' && ready()) { cb(); return; }
      App.show('mails');
      const t0 = Date.now();
      const attempt = () => {
        if (ready()) { cb(); return; }
        if (Date.now() - t0 >= 2000) {
          Toast.error('La messagerie met du temps à s’ouvrir — réessaie dans un instant.');
          return;
        }
        App.viewTimeout(attempt, 120);
      };
      attempt();
    };
    ov.querySelector('[data-cc="new"]').onclick = () => goMails(() => Mails._openComposer({}));
    ov.querySelector('[data-cc="prospect"]').onclick = () => goMails(() => Mails._openProspectFlow());
  },

  // -------- Helpers --------
  _escHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>]/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;'
    }[c]));
  },
  _escAttr(s) {
    return String(s == null ? '' : s).replace(/["'&<>]/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    }[c]));
  },

  // -------- Mode preview (sans API Python) --------
  _previewPlaceholder() {
    const fakeDigest = {
      ok: true,
      sent: { yesterday: 47, today: 8, last_7d: 312, daily_last_7d: [42,38,55,47,61,42,8] },
      replies: {
        yesterday_total: 6,
        yesterday_breakdown: { interested: 2, not_now: 1, no: 2, unsubscribe: 1 },
        today_total: 1, today_breakdown: {}
      },
      queue: { replies_unhandled_interested: 2, replies_unhandled_total: 4,
                drafts_prospect_pending: 3, drafts_convoy_pending: 0 },
      alerts: { convoy_failed_yesterday: 0, convoy_failed_today: 0 },
    };
    return this._renderHero(fakeDigest)
         + this._renderKpiGrid(fakeDigest)
         + this._renderAlert(fakeDigest);
  },
};
