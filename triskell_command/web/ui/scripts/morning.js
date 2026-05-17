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

        <!-- Salutation discrète + quickbar -->
        <div class="mt-5 flex items-end justify-between gap-3 flex-wrap">
          <h1 class="hero-title">${userName ? `${greeting} ${nameWithCrown}.` : `${greeting}.`}</h1>
        </div>
        <div class="cockpit-quickbar">
          <button id="m-refresh" class="btn btn-secondary" title="Rafraîchir les chiffres">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M3 12a9 9 0 0114-7.4M21 12a9 9 0 01-14 7.4"/><path d="M21 4v5h-5M3 20v-5h5"/></svg>
            Rafraîchir
          </button>
          <button id="m-compose-mail" class="btn btn-secondary" title="Composer (Ctrl+Shift+M)">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24" stroke-linecap="round" stroke-linejoin="round">
              <path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 113 3L7 19l-4 1 1-4L16.5 3.5z"/>
            </svg>
            Composer
          </button>
          <button id="m-brain" class="btn btn-secondary" title="Brain — note rapide (Ctrl+B)">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24" stroke-linecap="round" stroke-linejoin="round">
              <path d="M12 5a3 3 0 1 0-5.997.125 4 4 0 0 0-2.526 5.77 4 4 0 0 0 .556 6.588A4 4 0 1 0 12 18Z"/>
              <path d="M12 5a3 3 0 1 1 5.997.125 4 4 0 0 1 2.526 5.77 4 4 0 0 1-.556 6.588A4 4 0 1 1 12 18Z"/>
              <path d="M15 13a4.5 4.5 0 0 1-3-4 4.5 4.5 0 0 1-3 4"/>
            </svg>
            Brain
          </button>
          <button id="m-allo-claude" class="btn btn-primary"
                  style="background: linear-gradient(135deg, hsl(var(--accent)), hsl(var(--accent-glow))); border: 0;"
                  title="Allô Claude">
            <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
              <path d="M21 12a8 8 0 0 1-11.7 7.1L4 20.5l1.4-5.3A8 8 0 1 1 21 12z"/>
              <path d="M12 8.5v3M12 12.5v3M8.5 12h3M12.5 12h3" stroke-width="1.6"/>
            </svg>
            Allô Claude
          </button>
          <button id="m-focus" class="btn btn-secondary" title="Mode Concentration">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>
            </svg>
            Concentration
          </button>
        </div>

        <div id="m-content" class="mt-6"></div>
      </section>
    `;

    // Bindings boutons quickbar
    document.getElementById('m-refresh').onclick = () => this.render(container);
    document.getElementById('m-brain').onclick = () => {
      if (typeof Brain !== 'undefined' && Brain._openNew) Brain._openNew();
    };
    document.getElementById('m-allo-claude').onclick = () => Claude.open();
    document.getElementById('m-compose-mail').onclick = () => this._openComposeChoice();
    const focusBtn = document.getElementById('m-focus');
    if (focusBtn) {
      focusBtn.onclick = () => {
        if (typeof FocusMode === 'undefined') return;
        if (FocusMode.isOn()) FocusMode.showOverlay();
        else FocusMode.openStartDialog();
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
            <button class="btn btn-primary" onclick="App.show('config')">Aller dans Réglages →</button>
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

    slot.innerHTML = this._renderHero(digest)
                   + `<div id="m-modes-slot"></div>`
                   + this._renderKpiGrid(digest)
                   + this._renderAlert(digest)
                   + `<div id="m-linkedin-slot"></div>`;

    this._loadModes();
    this._loadLinkedinActions();

    // Démarre le rafraîchissement automatique des chiffres
    this._startAutoRefresh();
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
          <span class="cockpit-modes-title">TES 2 MODES</span>
          <span class="cockpit-modes-sub">Bascule en 1 clic — l'app applique tout de suite</span>
        </div>
        <div class="cockpit-modes-grid">
          ${this._modeCard({
            kind: 'prospection',
            title: 'Prospection',
            sub: 'Les mails que l’IA prépare pour les nouveaux contacts',
            current: m.prospection,
          })}
          ${this._modeCard({
            kind: 'reponses',
            title: 'Réponses',
            sub: 'Les réponses que l’IA prépare aux gens qui t’ont écrit',
            current: m.reponses,
          })}
        </div>
      </div>
    `;
  },

  _modeCard({ kind, title, sub, current }) {
    const isDirect = current === 'direct';
    return `
      <div class="cockpit-mode-card" data-kind="${kind}" data-current="${current}">
        <div class="cockpit-mode-card-head">
          <span class="cockpit-mode-card-title">${title}</span>
          <span class="cockpit-mode-card-sub">${sub}</span>
        </div>
        <div class="cockpit-mode-switch" role="group" aria-label="Choisir un mode">
          <button type="button"
                  class="cockpit-mode-opt ${isDirect ? 'active danger' : ''}"
                  data-mode="direct"
                  title="L'IA envoie tout de suite, sans demander">
            <span class="cockpit-mode-opt-icon">🚀</span>
            <span class="cockpit-mode-opt-label">Envoi direct</span>
          </button>
          <button type="button"
                  class="cockpit-mode-opt ${!isDirect ? 'active' : ''}"
                  data-mode="validation"
                  title="L'app te montre les mails, tu valides avant envoi">
            <span class="cockpit-mode-opt-icon">✋</span>
            <span class="cockpit-mode-opt-label">Je valide</span>
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
            const confirmMsg = kind === 'prospection'
              ? "Passer en envoi DIRECT pour la prospection ?\n\nL'IA enverra chaque mail sans te demander. Tu peux revenir à « Je valide » à tout moment."
              : "Passer en envoi DIRECT pour les réponses ?\n\nL'IA répondra toute seule aux mails reçus. Tu peux revenir à « Je valide » à tout moment.";
            if (!confirm(confirmMsg)) return;
          }
          card.querySelectorAll('.cockpit-mode-opt').forEach(b => {
            b.classList.remove('active', 'danger');
          });
          btn.classList.add('active');
          if (target === 'direct') btn.classList.add('danger');
          card.dataset.current = target;
          try {
            const r = await App.api.set_simple_mode({ kind, mode: target });
            if (!r || !r.ok) {
              alert("Bascule impossible : " + ((r && r.error) || 'erreur'));
              this._loadModes();
            }
          } catch (e) {
            alert("Bascule impossible : " + e);
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

    let kicker, title, body, cta, target, state;
    if (nInt > 0) {
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
      cta    = "Lancer l'auto-pilote →";
      target = 'autopilot';
      state  = 'accent';
    }

    return `
      <div class="cockpit-hero" data-state="${state}">
        <div class="cockpit-hero-kicker">${kicker}</div>
        <h2 class="cockpit-hero-title">${title}</h2>
        <p class="cockpit-hero-body">${body}</p>
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
          label: 'Envoyés aujourd\'hui',
          value: sentT,
          tag: sentT > 0 ? 'LIVE' : null,
          delta: `<strong>${sentY}</strong> hier · <strong>${sentW}</strong> sur 7 jours`,
          spark: daily,
        })}
        ${this._kpi({
          label: 'Réponses aujourd\'hui',
          value: repT,
          tag: repT > 0 ? 'LIVE' : null,
          delta: `<strong>${repY}</strong> hier · taux ${sentY ? Math.round(100*repY/sentY) : 0} %`,
          tone: repT > 0 ? 'success' : '',
        })}
        ${this._kpi({
          label: 'Intéressés en file',
          value: nInt,
          delta: nInt === 0 ? 'rien à relancer là tout de suite' : 'à recontacter — chaud',
          tone: nInt > 0 ? 'success' : '',
        })}
        ${this._kpi({
          label: 'Brouillons à valider',
          value: nDrafts,
          delta: nDrafts === 0 ? 'inbox vide' : 'prêts à approuver',
          tone: nDrafts > 0 ? 'accent' : '',
        })}
      </div>
    `;
  },

  _kpi({ label, value, tag, delta, tone, spark }) {
    const toneCls = tone ? `tone-${tone}` : '';
    const tagHtml = tag ? `<span class="cockpit-kpi-tag live">${tag}</span>` : '';
    const sparkHtml = (spark && spark.length) ? this._sparkline(spark) : '';
    return `
      <div class="cockpit-kpi ${toneCls}">
        <div class="cockpit-kpi-head">
          <span class="cockpit-kpi-label">${label}</span>
          ${tagHtml}
        </div>
        <div class="cockpit-kpi-value">${value}</div>
        ${delta ? `<div class="cockpit-kpi-delta">${delta}</div>` : ''}
        ${sparkHtml}
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
            Ouvre l'écran d'import pour voir le détail.
          </p>
          <button class="btn btn-secondary" onclick="App.show('convoy')">Voir le détail →</button>
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
      if (!confirm("Envoyer toutes les relances LinkedIn pending au Phantom configuré ?\n\n" +
                    "Phantombuster va les distribuer sur LinkedIn (rate-limité ~25/jour pour éviter le ban).\n" +
                    "Si tu n'as pas configuré Phantombuster, va dans Réglages d'abord.")) return;
      btn.disabled = true; btn.textContent = 'Envoi…';
      try {
        const r = await App.api.multichannel_dispatch_phantombuster();
        if (r && r.ok) {
          btn.textContent = `✓ ${r.launched} envoyés`;
          if (r.note) alert(r.note);
        } else {
          alert('Échec : ' + ((r && r.error) || 'erreur'));
          btn.disabled = false;
          btn.textContent = '⚡ Tout envoyer via Phantombuster';
        }
      } catch (e) {
        alert('Erreur : ' + e);
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
          <a href="${this._escAttr(a.search_url || '#')}" target="_blank"
             class="text-xs px-2.5 py-1.5 rounded-lg bg-surface-elevated border border-border hover:border-accent text-text-secondary hover:text-text">
            🔍 Trouver son LinkedIn
          </a>
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
        const txt = card.querySelector('pre').textContent || '';
        navigator.clipboard.writeText(txt).then(() => {
          copyBtn.textContent = '✓ Copié';
          setTimeout(() => copyBtn.innerHTML = '📋 Copier le message', 1400);
        }).catch(() => alert('Impossible de copier — fais Ctrl+C manuellement'));
      };
      if (doneBtn) doneBtn.onclick = async () => {
        if (!App.api) return;
        await App.api.multichannel_mark_done({ id });
        card.style.opacity = '0';
        setTimeout(() => this._loadLinkedinActions(), 250);
      };
      if (discardBtn) discardBtn.onclick = async () => {
        if (!App.api) return;
        await App.api.multichannel_discard({ id });
        card.style.opacity = '0';
        setTimeout(() => this._loadLinkedinActions(), 250);
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
      <div class="bg-surface rounded-2xl shadow-hero w-full max-w-lg border border-border animate-slide-up overflow-hidden">
        <div class="px-6 pt-5 pb-4 flex items-start justify-between border-b border-border bg-surface-elevated">
          <div>
            <div class="text-[10px] font-bold uppercase tracking-widest text-text-muted mb-0.5">COMPOSER UN MAIL</div>
            <h3 class="text-lg font-bold">Que veux-tu écrire ?</h3>
            <p class="text-xs text-text-muted mt-1">Mail classique, ou présentation d'un site déjà réalisé pour la cible.</p>
          </div>
          <button id="cc-close" class="w-8 h-8 rounded-lg flex items-center justify-center text-text-muted hover:text-text hover:bg-bg text-xl leading-none shrink-0">×</button>
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

    const goMails = (cb) => {
      close();
      if (App.currentView === 'mails') cb();
      else { App.show('mails'); setTimeout(cb, 200); }
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
