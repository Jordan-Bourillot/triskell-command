/* Pipeline view factory — vue générique partagée par les 3 offres
 *  (Studio WoW, RankUs Studio, Lagriffe Studio).
 *
 * Usage :
 *   const Wow = makePipelineView({
 *     kicker: 'STUDIO WOW',
 *     title:  'La plomberie sous tes yeux.',
 *     subtitle: '...',
 *     apiPrefix: 'wow',           // → App.api.wow_list_intakes etc.
 *     stages: [...],              // étages affichés dans la Plomberie
 *     statusLabels: {...},        // libellés des status
 *     statusColors: {...},        // couleurs des status
 *     extraActions: (intake) => [...], // boutons spécifiques selon status (Lagriffe)
 *   });
 *
 * Tout le rendu est isolé dans une instance — chaque offre a son propre
 * state (intakes sélectionnés, onglet courant, polling) sans interférer.
 */

function makePipelineView(config) {
  const view = {
    config,
    state: {
      tab: 'plomberie',
      statusFilter: 'pending_validation',
      intakes: [],
      selectedId: null,
      pipeline: null,
      timeline: null,
      pollHandle: null,
    },

    // ------------------------------------------------------------------
    // API helper : appelle App.api[`${prefix}_${method}`](payload)
    // ------------------------------------------------------------------
    async _call(method, payload) {
      if (!App.api) return null;
      const fn = App.api[`${this.config.apiPrefix}_${method}`];
      if (typeof fn !== 'function') {
        console.warn(`API method ${this.config.apiPrefix}_${method} introuvable`);
        return null;
      }
      try { return await fn(payload); }
      catch (e) { console.warn(`${this.config.apiPrefix}.${method}:`, e); return null; }
    },

    // ------------------------------------------------------------------
    // Render principal
    // ------------------------------------------------------------------
    async render(container) {
      container.innerHTML = `
        <section class="animate-slide-up">
          <div class="mb-6 flex items-end justify-between">
            <div>
              <div class="hero-kicker mb-2">${this._escape(this.config.kicker)}</div>
              <h1 class="hero-title mb-3" style="font-size: 36px;">${this._escape(this.config.title)}</h1>
              <p class="hero-subtitle">${this._escape(this.config.subtitle)}</p>
            </div>
            <button id="pv-refresh-${this.config.apiPrefix}" class="btn btn-secondary">Rafraîchir</button>
          </div>

          <div class="flex gap-2 mb-6 border-b border-border">
            <button data-pv-tab="plomberie" class="pv-tab">Pipeline</button>
            <button data-pv-tab="dashboard" class="pv-tab">Demandes</button>
            <button data-pv-tab="logs"      class="pv-tab">Historique d'une demande</button>
          </div>

          <div id="pv-content-${this.config.apiPrefix}"></div>
        </section>
      `;
      this._injectStyles();

      const root = document.getElementById(`pv-content-${this.config.apiPrefix}`);
      this._root = root;

      // Bind
      root.parentElement.querySelectorAll('[data-pv-tab]').forEach(btn => {
        btn.addEventListener('click', () => this.switchTab(btn.dataset.pvTab));
      });
      document.getElementById(`pv-refresh-${this.config.apiPrefix}`).onclick = () => this.refresh();

      await this.switchTab(this.state.tab);
    },

    _injectStyles() {
      if (document.getElementById('pv-styles')) return;
      const s = document.createElement('style');
      s.id = 'pv-styles';
      s.textContent = `
        .pv-tab {
          padding: 10px 18px; font-size: 13px; font-weight: 600;
          color: hsl(var(--text-muted));
          border-bottom: 2px solid transparent;
          transition: color 160ms, border-color 160ms;
        }
        .pv-tab:hover { color: hsl(var(--text)); }
        .pv-tab.is-active {
          color: hsl(var(--accent));
          border-bottom-color: hsl(var(--accent));
        }
        .pv-pipe-stage { transition: transform 200ms, box-shadow 200ms; }
        .pv-pipe-stage:hover { transform: translateY(-2px); }
        .pv-pipe-stage.is-active { animation: pvPulseAccent 2s ease-in-out infinite; }
        .pv-pipe-stage.is-attention { animation: pvPulseAttention 1.4s ease-in-out infinite; }
        @keyframes pvPulseAccent {
          0%, 100% { box-shadow: 0 0 0 0 hsl(var(--accent) / 0.4); }
          50%      { box-shadow: 0 0 0 6px hsl(var(--accent) / 0); }
        }
        @keyframes pvPulseAttention {
          0%, 100% { box-shadow: 0 0 0 0 hsl(var(--warning) / 0.55); }
          50%      { box-shadow: 0 0 0 8px hsl(var(--warning) / 0); }
        }
        .pv-pipe-arrow {
          flex: 0 0 24px; height: 2px;
          background: hsl(var(--border-strong));
          position: relative; align-self: center;
        }
        .pv-pipe-arrow::after {
          content: ''; position: absolute; right: -1px; top: -4px;
          border: 5px solid transparent;
          border-left-color: hsl(var(--border-strong));
        }
        .pv-pipe-arrow.is-active { background: hsl(var(--accent)); }
        .pv-pipe-arrow.is-active::after { border-left-color: hsl(var(--accent)); }
        .pv-card-intake {
          cursor: pointer;
          transition: border-color 160ms, transform 160ms;
        }
        .pv-card-intake:hover { border-color: hsl(var(--accent)); }
        .pv-card-intake.is-selected {
          border-color: hsl(var(--accent));
          box-shadow: 0 0 0 1px hsl(var(--accent));
        }
        .pv-timeline-line {
          position: absolute; left: 11px; top: 24px; bottom: 0;
          width: 2px; background: hsl(var(--border));
        }
        /* Pipelines à 8 étapes (Lagriffe) : wrap autorisé jusqu'à 1100px,
           flèches visibles seulement quand tout tient sur une ligne. */
        .pv-flow-wide { flex-wrap: wrap; }
        .pv-arrow-wide { display: none; }
        @media (min-width: 1100px) {
          .pv-flow-wide { flex-wrap: nowrap; }
          .pv-arrow-wide { display: flex; }
        }
      `;
      document.head.appendChild(s);
    },

    async switchTab(tab) {
      this.state.tab = tab;
      this._root.parentElement.querySelectorAll('[data-pv-tab]').forEach(btn => {
        btn.classList.toggle('is-active', btn.dataset.pvTab === tab);
      });
      if (this.state.pollHandle && tab !== 'plomberie') {
        clearInterval(this.state.pollHandle);
        this.state.pollHandle = null;
      }
      if (tab === 'dashboard') return this._renderDashboard();
      if (tab === 'plomberie') return this._renderPlomberie();
      if (tab === 'logs')      return this._renderLogs();
    },

    async refresh() {
      if (this.state.tab === 'dashboard') return this._renderDashboard();
      if (this.state.tab === 'plomberie') return this._loadPipeline();
      if (this.state.tab === 'logs')      return this._renderLogs();
    },

    // ------------------------------------------------------------------
    // Onglet 1 : Demandes
    // ------------------------------------------------------------------
    async _renderDashboard() {
      this._root.innerHTML = `
        <div class="flex items-center gap-3 mb-4">
          <label class="text-xs text-text-muted">Filtrer :</label>
          <select id="pv-status-filter" class="px-3 py-1.5 rounded-lg bg-bg border border-border text-sm">
            ${Object.entries(this.config.statusLabels).map(([k, v]) =>
              `<option value="${k}" ${k === this.state.statusFilter ? 'selected' : ''}>${this._escape(v)}</option>`
            ).join('')}
            <option value="" ${!this.state.statusFilter ? 'selected' : ''}>— Tous —</option>
          </select>
          <span id="pv-list-status" class="text-xs text-text-muted ml-2"></span>
        </div>

        <div class="grid grid-cols-1 lg:grid-cols-3 gap-5">
          <div id="pv-list" class="lg:col-span-2 space-y-3"></div>
          <div id="pv-actions" class="lg:col-span-1"></div>
        </div>
      `;
      document.getElementById('pv-status-filter').onchange = (e) => {
        this.state.statusFilter = e.target.value;
        this.state.selectedId = null;
        this._loadIntakes();
      };
      await this._loadIntakes();
    },

    async _loadIntakes() {
      const listEl = document.getElementById('pv-list');
      const statusEl = document.getElementById('pv-list-status');
      if (!App.api) { listEl.innerHTML = this._noBackend(); return; }
      listEl.innerHTML = `<div class="card p-6 text-text-muted text-sm">Chargement…</div>`;
      const resp = await this._call('list_intakes', {
        status: this.state.statusFilter || '',
        limit: 100,
      });
      if (!resp || !resp.ok) {
        console.warn(`[pipeline-view] ${this.config.apiPrefix} list_intakes:`, resp && resp.error);
        listEl.innerHTML = `
          <div class="card p-6 text-center">
            <p class="text-sm text-danger mb-3">Impossible de charger les demandes.</p>
            <button id="pv-list-retry" class="btn btn-secondary">Réessayer</button>
          </div>
        `;
        const retry = document.getElementById('pv-list-retry');
        if (retry) retry.onclick = () => this._loadIntakes();
        return;
      }
      this.state.intakes = resp.intakes || [];
      const label = this.config.statusLabels[this.state.statusFilter] || 'tous statuts';
      statusEl.textContent = `${this.state.intakes.length} demande(s) · ${label}`;

      if (this.state.intakes.length === 0) {
        // Le filtre par défaut (« À valider ») peut donner une liste vide
        // alors que d'autres demandes existent → proposer d'élargir.
        const isFiltered = !!this.state.statusFilter;
        listEl.innerHTML = `
          <div class="card p-10 text-center">
            <div class="text-3xl mb-3 opacity-60">∅</div>
            <p class="text-text-muted">Aucune demande dans ce filtre.</p>
            ${isFiltered ? `<button id="pv-show-all" class="btn btn-secondary mt-4">Afficher tous les statuts</button>` : ''}
          </div>
        `;
        const showAll = document.getElementById('pv-show-all');
        if (showAll) showAll.onclick = () => {
          this.state.statusFilter = '';
          const filterSel = document.getElementById('pv-status-filter');
          if (filterSel) filterSel.value = '';
          this._loadIntakes();
        };
        this._renderActionsPane();
        return;
      }
      listEl.innerHTML = this.state.intakes.map(i => this._intakeCard(i)).join('');
      // Sélection LOCALE : on bascule juste les classes + le panneau d'actions,
      // sans re-fetch (avant : chaque clic rechargeait toute la liste → flash).
      const selectCard = (el) => {
        this.state.selectedId = el.dataset.intakeId;
        listEl.querySelectorAll('[data-intake-id]').forEach(other => {
          const isSel = other.dataset.intakeId === this.state.selectedId;
          other.classList.toggle('is-selected', isSel);
          other.setAttribute('aria-pressed', isSel ? 'true' : 'false');
          const wrap = other.querySelector('[data-pv-card-detail-wrap]');
          if (wrap) wrap.classList.toggle('hidden', !isSel);
        });
        this._renderActionsPane();
      };
      listEl.querySelectorAll('[data-intake-id]').forEach(el => {
        // Clic simple (ou Entrée/Espace) = sélection (panneau actions à droite)
        el.addEventListener('click', () => selectCard(el));
        el.addEventListener('keydown', (e) => {
          if (e.target !== el) return; // laisser vivre le bouton « Détail »
          if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); selectCard(el); }
        });
        // Bouton « Détail » visible sur la carte sélectionnée
        const detailBtn = el.querySelector('[data-pv-card-detail]');
        if (detailBtn) detailBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          const intake = this.state.intakes.find(i => i.id === el.dataset.intakeId);
          if (intake) this._openIntakeDetail(intake);
        });
        // Double-clic = raccourci bonus vers la modale détail
        el.addEventListener('dblclick', () => {
          const intake = this.state.intakes.find(i => i.id === el.dataset.intakeId);
          if (intake) this._openIntakeDetail(intake);
        });
      });
      this._renderActionsPane();
    },

    _intakeCard(intake) {
      const payload = intake.payload || {};
      const first = intake.client_first_name || '';
      const last = intake.client_last_name || '';
      const fullName = `${first} ${last}`.trim() || '(nom non fourni)';
      const company = intake.company_name || '(société non fournie)';
      const email = intake.client_email || '—';
      const isSel = intake.id === this.state.selectedId;
      const statusColor = this.config.statusColors[intake.status] || 'text-muted';
      const statusLabel = this.config.statusLabels[intake.status] || intake.status;

      const metaBits = [];
      if (payload.budget)    metaBits.push(`Budget : <b>${this._escape(payload.budget)}</b>`);
      if (payload.echeance)  metaBits.push(`Échéance : ${this._escape(payload.echeance)}`);
      if (payload.type_site) metaBits.push(`Site : ${this._escape(payload.type_site)}`);
      if (payload.ambiance)  metaBits.push(`Ambiance : ${this._escape(payload.ambiance)}`);

      const dom = payload.domain || {};
      let domLine = '';
      if (dom.option === 'deja' && dom.existing) {
        domLine = `Domaine existant : <b>${this._escape(dom.existing)}</b>`;
      } else if (dom.option === 'reserver' && dom.propositions && dom.propositions.length) {
        domLine = `À réserver : ${dom.propositions.map(p => this._escape(p)).join(', ')}`;
      }

      return `
        <div class="card pv-card-intake p-4 ${isSel ? 'is-selected' : ''}" data-intake-id="${this._escape(intake.id)}"
             role="button" tabindex="0" aria-pressed="${isSel ? 'true' : 'false'}">
          <div class="flex items-start justify-between gap-3 mb-2">
            <div class="flex-1 min-w-0">
              <div class="text-sm font-bold truncate">${this._escape(fullName)} · ${this._escape(company)}</div>
              <div class="text-[11px] text-text-muted truncate">${this._escape(email)} · ${this._fmtDate(intake.created_at)}</div>
            </div>
            <span class="text-[11px] font-bold uppercase px-2 py-1 rounded shrink-0"
                  style="background: hsl(var(--${statusColor}) / 0.15); color: hsl(var(--${statusColor}));">
              ${this._escape(statusLabel)}
            </span>
          </div>
          ${metaBits.length ? `<div class="text-[11px] text-text-secondary mb-1">${metaBits.join(' · ')}</div>` : ''}
          ${domLine ? `<div class="text-[11px] text-text-muted mb-2">${domLine}</div>` : ''}
          <div class="text-xs text-text leading-snug line-clamp-3">${this._escape(intake.description || '(pas de brief)')}</div>
          ${payload.nda_souhaite ? `<div class="text-[11px] mt-2 font-bold text-warning">NDA demandé avant premier échange</div>` : ''}
          <div data-pv-card-detail-wrap class="mt-3 ${isSel ? '' : 'hidden'}">
            <button type="button" class="btn btn-secondary text-xs" data-pv-card-detail>Détail</button>
          </div>
        </div>
      `;
    },

    _renderActionsPane() {
      const pane = document.getElementById('pv-actions');
      if (!pane) return;
      const sel = this.state.intakes.find(i => i.id === this.state.selectedId);
      if (!sel) {
        pane.innerHTML = `
          <div class="card p-5 text-sm text-text-muted">
            Sélectionne une demande à gauche pour voir les actions disponibles.
          </div>
        `;
        return;
      }
      const fullName = `${sel.client_first_name || ''} ${sel.client_last_name || ''}`.trim();
      const status = sel.status;

      const TERMINAL_STATUSES = ['rejected', 'failed', 'final_failed', 'live'];
      const canAbandon = !TERMINAL_STATUSES.includes(status);

      // Un SEUL bouton principal par panneau : l'action qui fait avancer la
      // demande. Tout le reste (détail, historique, refus) est secondaire.
      const buttons = [];
      if (status === 'pending_validation') {
        buttons.push({ id: 'pv-act-approve', label: `Approuver (≈15 € de frais d'IA)`, cls: 'btn-primary' });
      }
      if (status === 'approved') {
        buttons.push({ id: 'pv-act-dispatch', label: 'Forcer le lancement maintenant', cls: 'btn-primary' });
      }
      // Mêmes pouvoirs que le panneau d'attente du Pipeline : la finalisation
      // manuelle d'une demande payée (Lagriffe uniquement, cf. _stageActionsFor).
      if (status === 'paid' && this.config.apiPrefix === 'lagriffe') {
        buttons.push({ id: 'pv-act-finalize', label: 'Lancer la finalisation', cls: 'btn-primary' });
      }
      // Actions spécifiques à l'offre (ex: Lagriffe approve_final si final_ready_review)
      if (typeof this.config.extraActions === 'function') {
        this.config.extraActions(sel).forEach(a => buttons.push(a));
      }
      buttons.push({ id: 'pv-act-detail', label: 'Ouvrir le détail complet', cls: 'btn-secondary' });
      buttons.push({ id: 'pv-act-logs', label: `Voir l'historique de cette demande`, cls: 'btn-secondary' });

      // Bouton « Abandonner » — toujours visible sauf demandes déjà terminales.
      // Pour pending_validation on garde le mot « Refuser » (sens commercial),
      // pour les autres étapes c'est un retrait de la chaîne de fabrication.
      if (canAbandon) {
        buttons.push({
          id: 'pv-act-reject',
          label: status === 'pending_validation'
            ? 'Refuser cette demande'
            : 'Abandonner / Sortir de la chaîne',
          cls: 'btn-secondary',
          style: 'color: hsl(var(--danger)); border-color: hsl(var(--danger) / 0.45); margin-top: 8px;',
        });
      }

      pane.innerHTML = `
        <div class="card p-5">
          <div class="text-[11px] font-bold tracking-widest text-accent mb-1">DEMANDE SÉLECTIONNÉE</div>
          <div class="text-base font-bold mb-1">${this._escape(fullName)}</div>
          <div class="text-xs text-text-muted mb-4">${this._escape(sel.company_name || '')}</div>
          <div class="flex flex-col gap-2">
            ${buttons.map(b => `<button id="${b.id}" class="btn ${b.cls}"${b.style ? ` style="${b.style}"` : ''}>${this._escape(b.label)}</button>`).join('')}
          </div>
          <div id="pv-action-status" class="mt-3 text-xs text-text-muted"></div>
        </div>
      `;

      const setMsg = (msg, isError = false) => {
        const el = document.getElementById('pv-action-status');
        if (el) {
          el.textContent = msg;
          el.className = `mt-3 text-xs ${isError ? 'text-danger' : 'text-text-muted'}`;
        }
      };

      const approveBtn = document.getElementById('pv-act-approve');
      if (approveBtn) approveBtn.onclick = () => this._withBusy(approveBtn, async () => {
        if (!await this._confirmApprove(sel)) return;
        setMsg('Approbation…');
        const r = await this._call('approve_intake', { id: sel.id });
        if (!r || !r.ok) {
          setMsg(`Échec de l'approbation.`, true);
          Toast.friendlyError(r && r.error, `L'approbation n'a pas abouti — la demande n'a pas bougé.`);
          return;
        }
        setMsg('Approuvé. Déclenchement immédiat…');
        const d = await this._call('dispatch_now', { id: sel.id });
        if (d && d.ok) {
          setMsg(`Lancement OK : ${d.message || ''}`);
          Toast.success('Demande approuvée — fabrication lancée.');
        } else {
          setMsg('Approuvé. La fabrication reprendra sous 5 min.');
          Toast.success('Demande approuvée — la fabrication reprendra sous 5 min.');
        }
        await this._loadIntakes();
      });

      const rejectBtn = document.getElementById('pv-act-reject');
      if (rejectBtn) rejectBtn.onclick = () => this._withBusy(rejectBtn, async () => {
        const done = await this._rejectFlow(sel);
        if (done) {
          this.state.selectedId = null;
          await this._loadIntakes();
        }
      });

      const dispatchBtn = document.getElementById('pv-act-dispatch');
      if (dispatchBtn) dispatchBtn.onclick = () => this._withBusy(dispatchBtn, async () => {
        const okC = await Dialog.confirm(
          `Forcer le lancement immédiat ?\n${fullName} · ${sel.company_name || ''}`,
          { title: 'Lancer la fabrication', okLabel: 'Lancer', cancelLabel: 'Annuler' }
        );
        if (!okC) return;
        setMsg('Déclenchement…');
        const r = await this._call('dispatch_now', { id: sel.id });
        if (r && r.ok) {
          setMsg(`OK : ${r.message || ''}`);
          Toast.success('Fabrication lancée.');
          await this._loadIntakes();
        } else {
          setMsg('Échec du lancement.', true);
          Toast.friendlyError(r && r.error, `Le lancement n'a pas abouti.`);
        }
      });

      const finalizeBtn = document.getElementById('pv-act-finalize');
      if (finalizeBtn) finalizeBtn.onclick = () => this._withBusy(finalizeBtn, async () => {
        const okC = await Dialog.confirm(
          `Lancer la finalisation du site ?\n${fullName} · ${sel.company_name || ''}`,
          { title: 'Lancer la finalisation', okLabel: 'Lancer', cancelLabel: 'Annuler' }
        );
        if (!okC) return;
        setMsg('Finalisation…');
        const r = await this._call('finalize_now', { id: sel.id });
        if (r && r.ok) {
          setMsg(`OK : ${r.message || ''}`);
          Toast.success('Finalisation lancée.');
          await this._loadIntakes();
        } else {
          setMsg('Échec de la finalisation.', true);
          Toast.friendlyError(r && r.error, `La finalisation n'a pas abouti.`);
        }
      });

      // Bind les actions custom si elles ont fourni un onClick callback
      buttons.forEach(b => {
        if (b.onClick) {
          const el = document.getElementById(b.id);
          if (el) el.onclick = () => this._withBusy(el, () =>
            b.onClick({ intake: sel, setMsg, call: this._call.bind(this), reload: () => this._loadIntakes() }));
        }
      });

      const logsBtn = document.getElementById('pv-act-logs');
      if (logsBtn) logsBtn.onclick = () => this.switchTab('logs');

      const detailBtn = document.getElementById('pv-act-detail');
      if (detailBtn) detailBtn.onclick = () => this._openIntakeDetail(sel);
    },

    // ------------------------------------------------------------------
    // Modale détail complet d'une demande
    // ------------------------------------------------------------------
    _openIntakeDetail(intake) {
      const payload = intake.payload || {};
      const fullName = `${intake.client_first_name || ''} ${intake.client_last_name || ''}`.trim() || '(anonyme)';
      const statusColor = this.config.statusColors[intake.status] || 'text-muted';
      const statusLabel = this.config.statusLabels[intake.status] || intake.status;

      const overlay = document.createElement('div');
      overlay.className = 'fixed inset-0 z-[200] flex items-center justify-center p-4';
      overlay.style.background = 'hsl(var(--bg) / 0.7)';
      overlay.style.backdropFilter = 'blur(8px)';
      const dom = payload.domain || {};
      const domLine = dom.option === 'deja' && dom.existing
        ? `Domaine existant : <b>${this._escape(dom.existing)}</b>`
        : dom.option === 'reserver' && (dom.propositions || []).length
          ? `À réserver : ${(dom.propositions || []).map(p => this._escape(p)).join(', ')}`
          : '—';

      overlay.innerHTML = `
        <div class="bg-surface rounded-2xl shadow-hero w-full max-w-3xl h-[88vh] overflow-hidden border border-border animate-slide-up flex flex-col">
          <div class="px-6 pt-4 pb-3 flex items-center justify-between border-b border-border bg-surface-elevated">
            <div>
              <div class="hero-kicker mb-0.5">${this._escape(this.config.kicker)}</div>
              <h3 class="text-base font-bold">${this._escape(fullName)} · ${this._escape(intake.company_name || '')}</h3>
            </div>
            <div class="flex items-center gap-3">
              <span class="text-[11px] font-bold uppercase px-3 py-1.5 rounded"
                    style="background: hsl(var(--${statusColor}) / 0.15); color: hsl(var(--${statusColor}));">
                ${this._escape(statusLabel)}
              </span>
              <button id="pvd-close" title="Fermer" aria-label="Fermer" class="w-8 h-8 rounded-lg flex items-center justify-center text-text-muted hover:text-text hover:bg-bg text-xl leading-none">×</button>
            </div>
          </div>

          <div class="flex-1 overflow-y-auto px-6 py-5 space-y-5">
            <!-- Coordonnées -->
            <section>
              <div class="hero-kicker mb-2">COORDONNÉES</div>
              <div class="grid grid-cols-1 sm:grid-cols-2 gap-y-2 gap-x-6 text-sm">
                <div><span class="text-text-muted text-xs">Email :</span> ${this._escape(intake.client_email || '—')}</div>
                <div><span class="text-text-muted text-xs">Téléphone :</span> ${this._escape(intake.client_phone || '—')}</div>
                ${payload.fonction ? `<div><span class="text-text-muted text-xs">Fonction :</span> ${this._escape(payload.fonction)}</div>` : ''}
                ${payload.site_actuel ? `<div><span class="text-text-muted text-xs">Site actuel :</span> <a href="${this._escape(payload.site_actuel)}" target="_blank" class="text-accent underline">${this._escape(payload.site_actuel)}</a></div>` : ''}
              </div>
            </section>

            <!-- Qualification commerciale -->
            ${payload.budget || payload.echeance || payload.nature_client || payload.nature_projet ? `
              <section>
                <div class="hero-kicker mb-2">QUALIFICATION</div>
                <div class="grid grid-cols-1 sm:grid-cols-2 gap-y-2 gap-x-6 text-sm">
                  ${payload.budget ? `<div><span class="text-text-muted text-xs">Budget :</span> <b>${this._escape(payload.budget)}</b></div>` : ''}
                  ${payload.echeance ? `<div><span class="text-text-muted text-xs">Échéance :</span> ${this._escape(payload.echeance)}</div>` : ''}
                  ${payload.nature_client ? `<div><span class="text-text-muted text-xs">Nature client :</span> ${this._escape(payload.nature_client)}</div>` : ''}
                  ${payload.nature_projet ? `<div><span class="text-text-muted text-xs">Nature projet :</span> ${this._escape(payload.nature_projet)}</div>` : ''}
                </div>
                ${payload.nda_souhaite ? `<div class="mt-2 text-[11px] font-bold text-warning">⚠ NDA souhaité avant premier échange</div>` : ''}
              </section>` : ''}

            <!-- Préférences pipeline -->
            ${payload.type_site || payload.ambiance || dom.option ? `
              <section>
                <div class="hero-kicker mb-2">PRÉFÉRENCES SITE</div>
                <div class="space-y-1 text-sm">
                  ${payload.type_site ? `<div><span class="text-text-muted text-xs">Type :</span> ${this._escape(payload.type_site)}</div>` : ''}
                  ${payload.ambiance ? `<div><span class="text-text-muted text-xs">Ambiance :</span> ${this._escape(payload.ambiance)}</div>` : ''}
                  <div><span class="text-text-muted text-xs">Domaine :</span> ${domLine}</div>
                </div>
              </section>` : ''}

            <!-- Brief client -->
            <section>
              <div class="hero-kicker mb-2">BRIEF DU CLIENT</div>
              <div class="p-4 rounded-xl bg-bg border border-border text-sm whitespace-pre-wrap leading-relaxed">${this._escape(intake.description || payload.message || '(brief vide)')}</div>
            </section>

            <!-- Special request -->
            ${intake.special_request || payload.special_request ? `
              <section>
                <div class="hero-kicker mb-2">DEMANDE SPÉCIALE</div>
                <div class="p-3 rounded-lg bg-warning/8 border border-warning/30 text-sm whitespace-pre-wrap">${this._escape(intake.special_request || payload.special_request)}</div>
              </section>` : ''}

            <!-- Preview / livraison -->
            ${intake.mockup_url ? `
              <section>
                <div class="hero-kicker mb-2">LIVRABLE</div>
                <div class="text-sm space-y-1">
                  <div><span class="text-text-muted text-xs">URL preview :</span> <a href="${this._escape(intake.mockup_url)}" target="_blank" class="text-accent underline break-all">${this._escape(intake.mockup_url)}</a></div>
                  ${intake.mockup_generated_at ? `<div><span class="text-text-muted text-xs">Généré le :</span> ${this._fmtDate(intake.mockup_generated_at)}</div>` : ''}
                  ${intake.mockup_sent_at ? `<div><span class="text-text-muted text-xs">Envoyé au client :</span> ${this._fmtDate(intake.mockup_sent_at)}</div>` : ''}
                </div>
              </section>` : ''}

            <!-- Feedback / assets client (Lagriffe surtout) -->
            ${intake.client_feedback ? `
              <section>
                <div class="hero-kicker mb-2">RETOURS CLIENT</div>
                <div class="p-4 rounded-xl bg-bg border border-border text-sm whitespace-pre-wrap leading-relaxed">${this._escape(intake.client_feedback)}</div>
                ${intake.client_assets_url ? `<div class="text-xs mt-2"><span class="text-text-muted">Assets :</span> <a href="${this._escape(intake.client_assets_url)}" target="_blank" class="text-accent underline">${this._escape(intake.client_assets_url)}</a></div>` : ''}
              </section>` : ''}

            <!-- Erreur si présente -->
            ${intake.error_message ? `
              <section>
                <div class="hero-kicker mb-2" style="color: hsl(var(--danger));">ERREUR</div>
                <div class="p-3 rounded-lg bg-danger/8 border border-danger/30 text-sm text-danger">${this._escape(intake.error_message)}</div>
              </section>` : ''}

            <!-- Méta -->
            <section class="text-[11px] text-text-muted border-t border-border pt-3">
              <div>ID : <code>${this._escape(intake.id)}</code></div>
              <div>Reçu le : ${this._fmtDateLong(intake.created_at)}</div>
              ${intake.last_attempt_at ? `<div>Dernière tentative : ${this._fmtDateLong(intake.last_attempt_at)}</div>` : ''}
            </section>
          </div>

          <div class="px-6 py-3 border-t border-border bg-surface-elevated flex items-center justify-between gap-2">
            <button id="pvd-logs" class="text-xs text-text-muted hover:text-accent">→ Voir la chronologie</button>
            <div class="flex gap-2">
              ${!['rejected', 'failed', 'final_failed', 'live'].includes(intake.status) ? `
                <button id="pvd-abandon" class="btn btn-secondary"
                        style="color: hsl(var(--danger)); border-color: hsl(var(--danger) / 0.45);">
                  ${intake.status === 'pending_validation' ? 'Refuser' : 'Abandonner'}
                </button>` : ''}
              <button id="pvd-close-2" class="btn btn-secondary">Fermer</button>
            </div>
          </div>
        </div>
      `;
      document.body.appendChild(overlay);
      // L'écouteur Échap est retiré dans close() : quelle que soit la façon
      // de fermer (×, Fermer, clic à côté, Échap), il ne reste pas en vie.
      const onEsc = (e) => { if (e.key === 'Escape') close(); };
      const close = () => {
        document.removeEventListener('keydown', onEsc);
        overlay.remove();
      };
      document.addEventListener('keydown', onEsc);
      overlay.querySelector('#pvd-close').onclick = close;
      overlay.querySelector('#pvd-close-2').onclick = close;
      overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
      overlay.querySelector('#pvd-logs').onclick = () => {
        this.state.selectedId = intake.id;
        close();
        this.switchTab('logs');
      };
      const abandonBtn = overlay.querySelector('#pvd-abandon');
      if (abandonBtn) abandonBtn.onclick = () => this._withBusy(abandonBtn, async () => {
        const done = await this._rejectFlow(intake);
        if (done) {
          close();
          this.refresh();
        }
      });
    },

    _fmtDateLong(iso) {
      if (!iso) return '—';
      try {
        const d = new Date(iso);
        return d.toLocaleString('fr-FR', { dateStyle: 'medium', timeStyle: 'short' });
      } catch { return iso; }
    },

    // ------------------------------------------------------------------
    // Onglet 2 : Plomberie
    // ------------------------------------------------------------------
    async _renderPlomberie() {
      // Coupe un éventuel polling encore vivant (revisite de l'onglet,
      // re-render…) AVANT d'en relancer un — sinon ils s'empilent.
      if (this.state.pollHandle) {
        clearInterval(this.state.pollHandle);
        this.state.pollHandle = null;
      }
      this._root.innerHTML = `
        <div class="card p-6 mb-5">
          <div class="flex items-center justify-between mb-1">
            <div>
              <div class="hero-kicker mb-1">CHAÎNE DE FABRICATION</div>
              <h2 class="text-xl font-bold">Le parcours d'une demande, étage par étage.</h2>
            </div>
            <div class="text-[11px] text-text-muted" id="pv-pipe-clock">Mise à jour : —</div>
          </div>
          <p class="text-text-muted text-sm mb-3">
            🤖 <b>Auto</b> = la demande avance toute seule. ✋ <b>Manuel</b> = tu valides à la main.
            Bascule l'interrupteur sur les étapes où tu veux garder le contrôle.
          </p>
          <!-- Légende code couleur -->
          <div class="flex items-center gap-4 mb-5 text-[11px] text-text-muted flex-wrap">
            <div class="flex items-center gap-1.5">
              <span class="inline-block w-2.5 h-2.5 rounded-full" style="background: hsl(var(--text-muted) / 0.3);"></span>
              <span>vide</span>
            </div>
            <div class="flex items-center gap-1.5">
              <span class="inline-block w-2.5 h-2.5 rounded-full" style="background: hsl(var(--accent));"></span>
              <span>en cours (auto)</span>
            </div>
            <div class="flex items-center gap-1.5">
              <span class="inline-block w-2.5 h-2.5 rounded-full" style="background: hsl(var(--warning));"></span>
              <span class="font-semibold" style="color: hsl(var(--warning));">attend ton action</span>
            </div>
          </div>
          <div id="pv-pipe-flow" class="flex items-stretch gap-1.5 flex-wrap ${this.config.stages.length >= 8 ? 'pv-flow-wide' : 'md:flex-nowrap'}"></div>
          <div class="mt-6 grid grid-cols-1 sm:grid-cols-3 gap-3" id="pv-pipe-deadends"></div>
        </div>

        <!-- Panneau : demandes qui attendent ton action manuelle (visible si toggles actifs) -->
        <div id="pv-pipe-pending-actions" class="card p-5 mb-5" hidden>
          <div class="flex items-center justify-between mb-3">
            <div>
              <div class="hero-kicker mb-1" style="color: hsl(var(--warning));">EN ATTENTE DE TON ACTION</div>
              <h3 class="text-base font-bold">Demandes coincées sur une étape en mode manuel</h3>
            </div>
            <span id="pv-pipe-pending-count" class="text-xs text-text-muted"></span>
          </div>
          <div id="pv-pipe-pending-list" class="space-y-2"></div>
        </div>

        <div class="card p-5">
          <div class="hero-kicker mb-3">5 DERNIÈRES DEMANDES</div>
          <div id="pv-pipe-recent" class="space-y-2"></div>
        </div>
      `;
      await this._syncModesFromBackend();
      await this._loadPipeline();
      // Polling toutes les 30s (vue qui change rarement, on évite le flash visuel).
      // App.viewInterval = auto-nettoyé au changement de vue ; le handle local
      // sert au nettoyage quand on change d'ONGLET dans la même vue.
      // Le bouton "Rafraîchir" en header force un refresh immédiat si besoin.
      this.state.pollHandle = App.viewInterval(() => this._loadPipeline(true), 30000);
    },

    // ─── Préférences AUTO / MANUEL persistées en Supabase ─────────────────
    //  Source de vérité : table triskell_pipeline_settings (Supabase).
    //  Le backend Netlify (process-intakes, stripe-webhook) lit cette table
    //  et bloque l'avancement automatique si l'étape est en MANUEL.
    //  Cache localStorage pour un affichage immédiat même hors-ligne.
    _modesKey() { return `pv-modes-${this.config.apiPrefix}`; },
    _loadModes() {
      try {
        const raw = localStorage.getItem(this._modesKey());
        return raw ? JSON.parse(raw) : {};
      } catch { return {}; }
    },
    async _saveMode(stageKey, mode) {
      // 1. Optimistic update localStorage (UI réactive)
      const modes = this._loadModes();
      const previous = modes[stageKey]; // mémorisé pour le rollback si le serveur refuse
      modes[stageKey] = mode;
      try { localStorage.setItem(this._modesKey(), JSON.stringify(modes)); } catch {}
      if (this.state.pipeline) this._renderPipelineFlow(this.state.pipeline);
      // 2. Persistance backend (Triskell Command → Supabase via pipeline-settings-api Lagriffe)
      //    ⚠ Garde-fou : si le serveur refuse, l'UI ne doit JAMAIS mentir →
      //    on remet l'interrupteur comme avant (localStorage + affichage) et on prévient.
      if (!App.api || typeof App.api.pipeline_settings_write !== 'function') return;
      let r = null;
      try {
        r = await App.api.pipeline_settings_write({
          product: this.config.apiPrefix,
          stage: stageKey,
          mode,
        });
      } catch (e) {
        r = { ok: false, error: e };
      }
      if (!r || !r.ok) {
        console.warn(`[pipeline-view] persistance backend failed pour ${stageKey}=${mode}:`, r && r.error);
        const rollback = this._loadModes();
        if (previous === undefined) delete rollback[stageKey];
        else rollback[stageKey] = previous;
        try { localStorage.setItem(this._modesKey(), JSON.stringify(rollback)); } catch {}
        if (this.state.pipeline) this._renderPipelineFlow(this.state.pipeline);
        Toast.friendlyError(r && r.error,
          'Impossible d’enregistrer le réglage Auto/Manuel — l’interrupteur est revenu comme avant.');
      }
    },
    _isManual(stageKey) {
      const modes = this._loadModes();
      // Par défaut : final_ready_review est MANUEL (filet humain natif).
      // Le reste est AUTO sauf si l'utilisateur a basculé.
      if (modes[stageKey] !== undefined) return modes[stageKey] === 'manual';
      return stageKey === 'final_ready_review';
    },
    // Étapes où le toggle Auto/Manuel a du sens pour CE pipeline.
    // ⚠ Le déblocage manuel de l'étape « Payé » (finalize_now) n'existe que
    // côté Lagriffe : pour WoW et RankUs on ne propose PAS de bloquer cette
    // étape, sinon les demandes payées resteraient coincées sans issue.
    _toggleableStages() {
      const base = this.config.toggleableStages || ['approved', 'paid', 'final_ready_review'];
      const allowed = this.config.apiPrefix === 'lagriffe'
        ? base
        : base.filter(k => k !== 'paid');
      return new Set(allowed);
    },
    // Charge les settings depuis Supabase au démarrage, met à jour le cache localStorage.
    async _syncModesFromBackend() {
      if (!App.api || typeof App.api.pipeline_settings_read !== 'function') return;
      try {
        const r = await App.api.pipeline_settings_read({ product: this.config.apiPrefix });
        if (r && r.ok && r.settings) {
          const settings = { ...r.settings };
          // Auto-réparation : pour WoW/RankUs, l'étape « Payé » ne doit JAMAIS
          // rester en MANUEL (aucun déblocage manuel n'existe pour elles →
          // demandes payées coincées à vie). Si un ancien réglage traîne en
          // base, on le remet en AUTO — l'interrupteur n'est plus proposé.
          if (this.config.apiPrefix !== 'lagriffe' && settings.paid === 'manual') {
            settings.paid = 'auto';
            if (typeof App.api.pipeline_settings_write === 'function') {
              try {
                await App.api.pipeline_settings_write({
                  product: this.config.apiPrefix, stage: 'paid', mode: 'auto',
                });
              } catch (e) {
                console.warn('[pipeline-view] auto-réparation paid=auto échouée:', e);
              }
            }
          }
          try { localStorage.setItem(this._modesKey(), JSON.stringify(settings)); } catch {}
        }
      } catch (e) {
        console.warn('[pipeline-view] sync modes failed:', e);
      }
    },

    async _loadPipeline(silent = false) {
      if (!App.api) {
        const flow = document.getElementById('pv-pipe-flow');
        if (flow) flow.innerHTML = this._noBackend();
        return;
      }
      const r = await this._call('pipeline_state');
      if (!r || !r.ok) {
        console.warn(`[pipeline-view] ${this.config.apiPrefix} pipeline_state:`, r && r.error);
        // Premier chargement raté → état d'erreur explicite + bouton Réessayer
        // (avant : zone vide muette). En polling, on garde l'affichage actuel
        // (évite le flash "tous les compteurs à 0" sur une erreur passagère).
        if (!this.state.pipeline) {
          const flow = document.getElementById('pv-pipe-flow');
          if (flow) {
            flow.innerHTML = `
              <div class="card p-6 w-full text-center">
                <p class="text-sm text-danger mb-3">Impossible de charger l'état de la chaîne de fabrication.</p>
                <button id="pv-pipe-retry" class="btn btn-secondary">Réessayer</button>
              </div>
            `;
            const retry = document.getElementById('pv-pipe-retry');
            if (retry) retry.onclick = () => this._loadPipeline();
          }
        }
        return;
      }
      // Diff : si les données sont identiques à la dernière, on skip le
      // re-render complet (cas habituel en polling silencieux). Ça empêche
      // le clignotement et préserve les états visuels (hover, focus).
      const newSig = this._pipelineSignature(r);
      if (silent && newSig === this.state._lastPipelineSig) {
        return;
      }
      this.state._lastPipelineSig = newSig;
      this.state.pipeline = r;
      this._renderPipelineFlow(r);
      this._renderPipelineRecent(r.recent || []);
      const clock = document.getElementById('pv-pipe-clock');
      if (clock) clock.textContent = `Mise à jour : ${new Date().toLocaleTimeString('fr-FR')}`;
    },

    _pipelineSignature(r) {
      // Signature légère pour détecter un changement de pipeline sans
      // comparer toute la structure. Inclut counts + ids des 5 demandes
      // récentes + leur statut.
      const counts = r.counts || {};
      const recent = (r.recent || []).slice(0, 5)
        .map(d => `${d.id || d.email || '?'}:${d.status || '?'}`)
        .join('|');
      return JSON.stringify(counts) + '#' + recent;
    },

    _renderPipelineFlow(state) {
      const flow = document.getElementById('pv-pipe-flow');
      if (!flow) return;
      const counts = state.counts || {};
      // Étapes pour lesquelles un toggle Auto/Manuel a du sens
      // (avant chaque étape se trouve un automatisme backend qu'on peut
      // choisir de bloquer pour valider à la main). Filtré par pipeline
      // dans _toggleableStages (« paid » réservé à Lagriffe).
      const toggleable = this._toggleableStages();
      const html = [];
      this.config.stages.forEach((st, idx) => {
        const n = counts[st.key] || 0;
        const empty = n === 0;
        const isToggleable = toggleable.has(st.key);
        const isManual = isToggleable && this._isManual(st.key);
        const needsIntervention = !empty && isManual;
        // Couleur : gris (vide) · orange (manuel et non vide) · bleu (auto en cours)
        const color = empty ? 'text-muted'
                    : needsIntervention ? 'warning'
                    : 'accent';
        const borderColor = empty ? 'hsl(var(--border))'
                          : `hsl(var(--${color}))`;
        const stateClass = needsIntervention ? 'is-attention'
                         : (!empty ? 'is-active' : '');
        const counterClass = empty ? 'text-text-muted opacity-40'
                           : `text-${color}`;
        const toggleHtml = isToggleable ? `
          <button class="pv-mode-toggle mt-2 w-full text-[11px] font-bold uppercase tracking-wider px-2 py-1.5 rounded transition-colors"
                  data-pv-toggle="${this._escape(st.key)}"
                  data-pv-current="${isManual ? 'manual' : 'auto'}"
                  aria-pressed="${isManual ? 'true' : 'false'}"
                  style="border: 1px solid hsl(var(--${isManual ? 'warning' : 'accent'}) / 0.4);
                         background: hsl(var(--${isManual ? 'warning' : 'accent'}) / 0.08);
                         color: hsl(var(--${isManual ? 'warning' : 'accent'}));"
                  title="Cliquer pour basculer entre Auto et Manuel sur cette étape">
            ${isManual ? '✋ Manuel' : '🤖 Auto'}
          </button>` : '';
        // Mapping étape → clé template mail (4 mails clients du circuit).
        // ⚠ Ces mails sont ceux de LAGRIFFE (lagriffe_mail_templates_*) :
        // on n'affiche l'icône ✉️ que sur ce pipeline, sinon on laisserait
        // croire qu'on édite les mails WoW/RankUs alors qu'on toucherait
        // en silence ceux de Lagriffe.
        const STAGE_TO_MAIL_TEMPLATE = {
          pending_validation: 'brief_received',
          sent:               'preview_ready',
          paid:               'payment_confirmed',
          live:               'site_delivered',
        };
        const mailTplKey = this.config.apiPrefix === 'lagriffe'
          ? STAGE_TO_MAIL_TEMPLATE[st.key]
          : null;
        const mailIconHtml = mailTplKey ? `
          <button class="pv-mail-icon absolute top-2 right-2 text-[14px] leading-none p-1 rounded hover:bg-accent/10 transition-colors"
                  data-pv-mail-template="${this._escape(mailTplKey)}"
                  title="Éditer le mail envoyé à cette étape"
                  aria-label="Éditer le mail envoyé à cette étape"
                  style="color: hsl(var(--accent)); z-index: 2;">
            ✉️
          </button>` : '';
        html.push(`
          <div class="pv-pipe-stage card flex-1 basis-0 min-w-0 sm:min-w-[140px] md:min-w-0 p-2.5 ${stateClass} relative group"
               style="border-color: ${borderColor};${needsIntervention ? ' background: hsl(var(--warning) / 0.06);' : ''}"
               data-pv-stage-key="${this._escape(st.key)}">
            ${mailIconHtml}
            <div class="flex items-baseline justify-between mb-1 ${mailTplKey ? 'pr-6' : ''}">
              <div class="text-[11px] font-bold tracking-widest text-text-muted">ÉTAPE ${idx + 1}</div>
              <div class="text-2xl font-bold ${counterClass}">${n}</div>
            </div>
            <div class="text-sm font-semibold leading-tight">${this._escape(st.label)}</div>
            <div class="text-[11px] text-text-muted mt-1 leading-tight">${this._escape(st.sub || '')}</div>
            ${needsIntervention ? `
              <div class="text-[11px] font-bold uppercase tracking-widest mt-2 flex items-center gap-1" style="color: hsl(var(--warning));">
                <span>● Attend ton action</span>
              </div>` : ''}
            ${toggleHtml}
            ${(!empty && !isToggleable) ? `
              <div class="absolute bottom-2 right-2 text-[11px] font-semibold opacity-0 group-hover:opacity-100 transition-opacity"
                   style="color: hsl(var(--${color}));">
                Voir →
              </div>` : ''}
          </div>
        `);
        if (idx < this.config.stages.length - 1) {
          const flowActive = (counts[this.config.stages[idx + 1].key] || 0) > 0 || !empty;
          // Flèches cachées en wrap (mobile) pour éviter l'effet bizarre quand
          // une étape passe à la ligne. Visibles dès md (≥768px) — sauf pour
          // les pipelines à 8 étapes (Lagriffe) où le wrap reste autorisé
          // jusqu'à 1100px : les flèches n'apparaissent qu'à partir de là.
          const arrowVisibility = this.config.stages.length >= 8 ? 'pv-arrow-wide' : 'hidden md:flex';
          html.push(`<div class="pv-pipe-arrow ${arrowVisibility} ${flowActive ? 'is-active' : ''}"></div>`);
        }
      });
      flow.innerHTML = html.join('');

      // Bind des toggles Auto/Manuel
      flow.querySelectorAll('[data-pv-toggle]').forEach(btn => {
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          const key = btn.dataset.pvToggle;
          const current = btn.dataset.pvCurrent;
          const next = current === 'manual' ? 'auto' : 'manual';
          // _saveMode fait le re-render optimiste immédiat (localStorage),
          // puis vérifie la réponse serveur et REVIENT EN ARRIÈRE (UI +
          // localStorage + message) si l'enregistrement a échoué.
          this._saveMode(key, next);
        });
      });

      // Bind des icônes ✉️ : ouvre l'éditeur du mail correspondant à l'étape
      flow.querySelectorAll('[data-pv-mail-template]').forEach(btn => {
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          const tplKey = btn.dataset.pvMailTemplate;
          this._openMailTemplateEditor(tplKey);
        });
      });

      // Panneau "demandes en attente d'action" : combine toutes les demandes
      // sur les étapes actuellement en mode MANUEL.
      this._renderPendingActions(state);

      // Click sur une étape (hors clic sur le toggle) → bascule sur l'onglet Demandes filtré
      flow.querySelectorAll('[data-pv-stage-key]').forEach(el => {
        const status = el.dataset.pvStageKey;
        const n = counts[status] || 0;
        if (n === 0) {
          el.style.cursor = 'default';
          el.removeAttribute('title');
          el.removeAttribute('role');
          el.removeAttribute('tabindex');
          return;
        }
        el.style.cursor = 'pointer';
        el.title = 'Cliquer pour voir les demandes à cette étape';
        el.setAttribute('role', 'button');
        el.setAttribute('tabindex', '0');
        const go = () => {
          this.state.statusFilter = status;
          this.state.selectedId = null;
          this.switchTab('dashboard');
        };
        el.addEventListener('click', go);
        el.addEventListener('keydown', (e) => {
          if (e.target !== el) return; // ne pas intercepter le toggle / l'icône mail
          if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); }
        });
      });

      const dead = document.getElementById('pv-pipe-deadends');
      if (!dead) return;
      const deadStates = (this.config.deadEnds || [
        { key: 'rejected',     label: 'Refusés',                 color: 'text-muted' },
        { key: 'failed',       label: 'Échec preview',           color: 'danger' },
        { key: 'final_failed', label: 'Échec finalisation',      color: 'danger' },
      ]);
      dead.innerHTML = deadStates.map(d => {
        const n = counts[d.key] || 0;
        return `
          <div class="card p-3 flex items-center justify-between" style="opacity: ${n > 0 ? 1 : 0.4};">
            <div>
              <div class="text-[11px] font-bold tracking-widest text-text-muted">VOIE SANS ISSUE</div>
              <div class="text-sm font-semibold">${this._escape(d.label)}</div>
            </div>
            <div class="text-2xl font-bold" style="color: hsl(var(--${d.color}));">${n}</div>
          </div>
        `;
      }).join('');
    },

    // Panneau "En attente de ton action" : liste les demandes coincées
    // sur des étapes actuellement en mode MANUEL, avec actions directes.
    _renderPendingActions(state) {
      const panel = document.getElementById('pv-pipe-pending-actions');
      const list = document.getElementById('pv-pipe-pending-list');
      const countEl = document.getElementById('pv-pipe-pending-count');
      if (!panel || !list) return;

      const manualStages = [...this._toggleableStages()].filter(k => this._isManual(k));
      const counts = state.counts || {};
      const totalPending = manualStages.reduce((sum, k) => sum + (counts[k] || 0), 0);

      if (totalPending === 0) {
        panel.hidden = true;
        return;
      }
      panel.hidden = false;

      // Filtre dans state.recent les intakes sur étapes manuelles
      const recent = state.recent || [];
      const pending = recent.filter(i => manualStages.includes(i.status));
      countEl.textContent = pending.length >= totalPending
        ? `${totalPending} demande(s)`
        : `${totalPending} demande(s) au total — les ${pending.length} plus récentes ci-dessous`;

      if (pending.length === 0) {
        list.innerHTML = `
          <div class="text-sm text-text-muted py-3 text-center">
            ${totalPending} demande(s) en attente. Va voir l'onglet Demandes pour la liste complète et agir.
          </div>
          <button id="pv-pending-goto-dashboard" class="btn btn-secondary w-full">Aller voir toutes les demandes</button>
        `;
        const btn = document.getElementById('pv-pending-goto-dashboard');
        if (btn) btn.onclick = () => {
          this.state.statusFilter = manualStages[0];
          this.switchTab('dashboard');
        };
        return;
      }

      list.innerHTML = pending.map(i => {
        const fullName = `${i.client_first_name || ''} ${i.client_last_name || ''}`.trim() || '(anonyme)';
        const statusLabel = this.config.statusLabels[i.status] || i.status;
        const stageActions = this._stageActionsFor(i);
        return `
          <div class="flex items-center justify-between gap-3 py-3 px-3 rounded border border-warning/30 bg-warning/5">
            <div class="min-w-0 flex-1">
              <div class="text-sm font-bold truncate">${this._escape(fullName)} <span class="text-text-muted font-normal">· ${this._escape(i.company_name || '')}</span></div>
              <div class="text-[11px] text-text-muted">${this._escape(statusLabel)} · ${this._fmtDate(i.created_at)}</div>
            </div>
            <div class="flex gap-2 shrink-0">
              ${stageActions.map(a => `<button class="btn btn-${a.cls} text-xs" data-pv-pending-act="${this._escape(a.id)}" data-pv-intake="${this._escape(i.id)}">${this._escape(a.label)}</button>`).join('')}
            </div>
          </div>
        `;
      }).join('');

      // Bind les actions directes (bouton occupé pendant l'appel = anti double-clic)
      list.querySelectorAll('[data-pv-pending-act]').forEach(btn => {
        btn.addEventListener('click', () => {
          const intakeId = btn.dataset.pvIntake;
          const actId = btn.dataset.pvPendingAct;
          const intake = pending.find(i => i.id === intakeId);
          if (!intake) return;
          this._withBusy(btn, () => this._runQuickAction(actId, intake));
        });
      });
    },

    // Liste des actions disponibles directement depuis le panneau pending,
    // selon le statut de l'intake.
    _stageActionsFor(intake) {
      const acts = [];
      if (intake.status === 'pending_validation') {
        acts.push({ id: 'approve', label: 'Approuver', cls: 'primary' });
      }
      if (intake.status === 'approved') {
        acts.push({ id: 'dispatch', label: 'Lancer fabrication', cls: 'primary' });
      }
      // finalize_now n'existe que côté Lagriffe (cf. _toggleableStages) :
      // pour WoW/RankUs ce bouton appellerait un endpoint inexistant.
      if (intake.status === 'paid' && this.config.apiPrefix === 'lagriffe') {
        acts.push({ id: 'finalize', label: 'Lancer finalisation', cls: 'primary' });
      }
      if (intake.status === 'final_ready_review') {
        acts.push({ id: 'approve_final', label: 'Valider et envoyer', cls: 'primary' });
      }
      acts.push({ id: 'detail', label: 'Détail', cls: 'secondary' });
      // Abandon disponible partout sauf terminal
      if (!['rejected', 'failed', 'final_failed', 'live'].includes(intake.status)) {
        acts.push({
          id: 'reject',
          label: intake.status === 'pending_validation' ? 'Refuser' : 'Abandonner',
          cls: 'secondary',
        });
      }
      return acts;
    },

    // Anti double-clic : désactive le bouton le temps de l'action.
    // (Si un re-render a remplacé le bouton entre-temps, le `finally`
    // retombe sur un nœud détaché — sans effet, sans erreur.)
    async _withBusy(btn, fn) {
      if (!btn || btn.disabled) return;
      btn.disabled = true;
      try { await fn(); }
      finally { btn.disabled = false; }
    },

    // Confirmation d'approbation — LA MÊME fenêtre partout (panneau
    // d'attente du Pipeline ET onglet Demandes) : coût annoncé, pas de
    // chemin qui contourne l'avertissement.
    async _confirmApprove(intake) {
      const fullName = `${intake.client_first_name || ''} ${intake.client_last_name || ''}`.trim() || '(anonyme)';
      return Dialog.confirm(
        `Approuver et lancer la fabrication de l'aperçu pour :\n${fullName} · ${intake.company_name || ''}\n\nCoût ≈ 15 € de frais d'IA. Cette action est définitive.`,
        { title: 'Approuver cette demande', okLabel: 'Approuver (≈15 €)', cancelLabel: 'Annuler' }
      );
    },

    // Refus / abandon — flux unique pour les 3 endroits (panneau d'actions,
    // modale détail, panneau d'attente). Annuler dans la fenêtre du motif
    // annule VRAIMENT (avant : le refus partait quand même).
    // Renvoie true si la demande a bien été refusée/abandonnée.
    async _rejectFlow(intake) {
      const fullName = `${intake.client_first_name || ''} ${intake.client_last_name || ''}`.trim() || '(anonyme)';
      const isAbandon = intake.status !== 'pending_validation';
      const verb = isAbandon ? 'Abandonner' : 'Refuser';
      const warn = isAbandon
        ? `\n\nLa demande sortira de la chaîne de fabrication (statut « refusé »). Aucun mail ne part. Cette action est définitive.`
        : '';
      const okConfirm = await Dialog.confirm(
        `${verb} cette demande ?\n${fullName} · ${intake.company_name || ''}${warn}`,
        { title: `${verb} la demande`, okLabel: verb, cancelLabel: 'Annuler', danger: true }
      );
      if (!okConfirm) return false;
      const reason = prompt('Motif (laisser vide si aucun) :');
      if (reason === null) return false; // Annuler ici = on ne fait rien
      const r = await this._call('reject_intake', { id: intake.id, reason });
      if (r && r.ok) {
        Toast.success(isAbandon ? 'Demande abandonnée.' : 'Demande refusée.');
        return true;
      }
      Toast.friendlyError(r && r.error, `Le ${isAbandon ? 'retrait' : 'refus'} n'a pas abouti — la demande n'a pas bougé.`);
      return false;
    },

    async _runQuickAction(actId, intake) {
      const fullName = `${intake.client_first_name || ''} ${intake.client_last_name || ''}`.trim();
      if (actId === 'detail') return this._openIntakeDetail(intake);
      if (actId === 'reject') {
        const done = await this._rejectFlow(intake);
        if (done) await this._loadPipeline();
        return;
      }
      const labels = {
        approve: 'Approuver et lancer',
        dispatch: 'Lancer la fabrication',
        finalize: 'Lancer la finalisation',
        approve_final: 'Valider et envoyer le mail au client',
      };
      const successMsgs = {
        approve: 'Demande approuvée — fabrication lancée.',
        dispatch: 'Fabrication lancée.',
        finalize: 'Finalisation lancée.',
        approve_final: 'Site validé — mail envoyé au client.',
      };
      const methods = {
        approve: 'approve_intake',
        dispatch: 'dispatch_now',
        finalize: 'finalize_now',
        approve_final: 'approve_final',
      };
      // Approuver = même confirmation (avec le coût) que dans l'onglet Demandes.
      const okConfirm = actId === 'approve'
        ? await this._confirmApprove(intake)
        : await Dialog.confirm(
            `${labels[actId]} pour :\n${fullName} · ${intake.company_name || ''}`,
            { title: labels[actId], okLabel: 'Confirmer', cancelLabel: 'Annuler' }
          );
      if (!okConfirm) return;
      const r = await this._call(methods[actId], { id: intake.id });
      if (r && r.ok) {
        if (actId === 'approve') {
          // Enchaîne approve + dispatch — sans mentir si le déclenchement
          // immédiat échoue (le passage auto reprendra dans les 5 min).
          const d = await this._call('dispatch_now', { id: intake.id });
          Toast.success((d && d.ok)
            ? successMsgs.approve
            : 'Demande approuvée — la fabrication reprendra sous 5 min.');
        } else {
          Toast.success(successMsgs[actId]);
        }
      } else {
        Toast.friendlyError(r && r.error, `« ${labels[actId]} » n'a pas abouti.`);
      }
      await this._loadPipeline();
    },

    _renderPipelineRecent(recent) {
      const el = document.getElementById('pv-pipe-recent');
      if (!el) return;
      if (!recent.length) {
        el.innerHTML = `<div class="text-sm text-text-muted">Aucune demande récente.</div>`;
        return;
      }
      el.innerHTML = recent.map(i => {
        const fullName = `${i.client_first_name || ''} ${i.client_last_name || ''}`.trim() || '(anonyme)';
        const statusColor = this.config.statusColors[i.status] || 'text-muted';
        const statusLabel = this.config.statusLabels[i.status] || i.status;
        return `
          <div class="flex items-center justify-between gap-3 py-2 border-b border-border last:border-0 cursor-pointer hover:bg-bg rounded px-2"
               data-recent-id="${this._escape(i.id)}" role="button" tabindex="0"
               title="Voir l'historique de cette demande">
            <div class="min-w-0">
              <div class="text-sm font-semibold truncate">${this._escape(fullName)} · ${this._escape(i.company_name || '')}</div>
              <div class="text-[11px] text-text-muted">${this._fmtDate(i.created_at)}</div>
            </div>
            <span class="text-[11px] font-bold uppercase px-2 py-1 rounded shrink-0"
                  style="background: hsl(var(--${statusColor}) / 0.15); color: hsl(var(--${statusColor}));">
              ${this._escape(statusLabel)}
            </span>
          </div>
        `;
      }).join('');
      el.querySelectorAll('[data-recent-id]').forEach(row => {
        const go = () => {
          this.state.selectedId = row.dataset.recentId;
          this.switchTab('logs');
        };
        row.addEventListener('click', go);
        row.addEventListener('keydown', (e) => {
          if (e.target !== row) return;
          if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); }
        });
      });
    },

    // ------------------------------------------------------------------
    // Onglet 3 : Logs
    // ------------------------------------------------------------------
    async _renderLogs() {
      if (!this.state.selectedId) {
        this._root.innerHTML = `
          <div class="card p-10 text-center">
            <div class="text-3xl mb-3 opacity-60">→</div>
            <h2 class="text-xl font-bold mb-2">Aucune demande sélectionnée.</h2>
            <p class="text-text-muted mb-5">Va dans l'onglet <b>Demandes</b> ou <b>Pipeline</b>, clique sur une carte, puis reviens ici.</p>
            <button id="pv-go-dashboard" class="btn btn-primary">Aller voir les demandes</button>
          </div>
        `;
        document.getElementById('pv-go-dashboard').onclick = () => this.switchTab('dashboard');
        return;
      }

      this._root.innerHTML = `
        <div id="pv-logs-head" class="card p-5 mb-4"></div>
        <div class="card p-6">
          <div class="hero-kicker mb-4">CHRONOLOGIE</div>
          <div id="pv-logs-timeline" class="relative pl-8"></div>
        </div>
      `;

      if (!App.api) {
        document.getElementById('pv-logs-timeline').innerHTML = this._noBackend();
        return;
      }
      const r = await this._call('get_intake', { id: this.state.selectedId });
      if (!r || !r.ok) {
        console.warn(`[pipeline-view] ${this.config.apiPrefix} get_intake:`, r && r.error);
        document.getElementById('pv-logs-timeline').innerHTML = `
          <div class="text-sm text-danger mb-3">Impossible de charger l'historique de cette demande.</div>
          <button id="pv-logs-retry" class="btn btn-secondary">Réessayer</button>
        `;
        const retry = document.getElementById('pv-logs-retry');
        if (retry) retry.onclick = () => this._renderLogs();
        return;
      }
      this._renderLogsHead(r.intake);
      this._renderLogsTimeline(r.timeline || []);
    },

    _renderLogsHead(intake) {
      const head = document.getElementById('pv-logs-head');
      if (!head) return;
      const fullName = `${intake.client_first_name || ''} ${intake.client_last_name || ''}`.trim() || '(anonyme)';
      const statusColor = this.config.statusColors[intake.status] || 'text-muted';
      const statusLabel = this.config.statusLabels[intake.status] || intake.status;
      head.innerHTML = `
        <div class="flex items-start justify-between gap-4">
          <div>
            <div class="hero-kicker mb-1">DEMANDE</div>
            <div class="text-lg font-bold">${this._escape(fullName)} · ${this._escape(intake.company_name || '')}</div>
            <div class="text-xs text-text-muted">${this._escape(intake.client_email || '')}</div>
          </div>
          <div class="text-right">
            <span class="text-[11px] font-bold uppercase px-3 py-1.5 rounded"
                  style="background: hsl(var(--${statusColor}) / 0.15); color: hsl(var(--${statusColor}));">
              ${this._escape(statusLabel)}
            </span>
            ${intake.mockup_url ? `
              <div class="mt-2 text-[11px]">
                Preview : <a class="text-accent underline" href="${this._escape(intake.mockup_url)}" target="_blank">${this._escape(intake.mockup_url)}</a>
              </div>` : ''}
          </div>
        </div>
      `;
    },

    _renderLogsTimeline(events) {
      const wrap = document.getElementById('pv-logs-timeline');
      if (!wrap) return;
      if (!events.length) {
        wrap.innerHTML = `<div class="text-text-muted text-sm">Aucun événement horodaté pour le moment.</div>`;
        return;
      }
      const colors = {
        submitted: 'accent', attempt: 'warning', generated: 'success',
        sent: 'success', error: 'danger', current: 'gold',
      };
      wrap.innerHTML = `
        <div class="pv-timeline-line"></div>
        ${events.map((ev, idx) => {
          const c = colors[ev.kind] || 'text-muted';
          return `
            <div class="relative pb-5 last:pb-0">
              <div class="absolute -left-8 top-0 w-6 h-6 rounded-full flex items-center justify-center"
                   style="background: hsl(var(--${c})); color: hsl(var(--surface)); font-size: 11px; font-weight: bold;">
                ${idx + 1}
              </div>
              <div class="text-[11px] text-text-muted">${this._fmtDateLong(ev.ts)}</div>
              <div class="text-sm font-medium">${this._escape(ev.label || '')}</div>
            </div>
          `;
        }).join('')}
      `;
    },

    // ------------------------------------------------------------------
    // Helpers
    // ------------------------------------------------------------------
    _noBackend() {
      return `
        <div class="card p-8 text-center">
          <div class="text-3xl mb-3 opacity-60">⏻</div>
          <h2 class="text-lg font-bold mb-2">Connexion au serveur impossible.</h2>
          <p class="text-text-muted text-sm">Recharge la page pour réessayer.</p>
        </div>
      `;
    },

    _escape(s) {
      return String(s ?? '')
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    },

    // ─── Éditeur de templates de mail (icônes ✉️ — Lagriffe uniquement) ──
    async _openMailTemplateEditor(tplKey) {
      if (!App.api || typeof App.api.lagriffe_mail_templates_list !== 'function') {
        Toast.error('Connexion au serveur impossible — recharge la page.');
        return;
      }
      let templates = [];
      try {
        const r = await App.api.lagriffe_mail_templates_list();
        if (r && r.ok) templates = r.templates || [];
      } catch (e) {
        Toast.friendlyError(e, 'Impossible de charger ce mail.');
        return;
      }
      const tpl = templates.find(t => t.key === tplKey);
      if (!tpl) { Toast.error('Modèle de mail introuvable.'); return; }
      this._renderMailEditorModal(tpl);
    },

    _renderMailEditorModal(tpl) {
      const esc = this._escape.bind(this);
      const variables = (tpl.variables || []).map(v => `<code class="px-1.5 py-0.5 rounded bg-bg text-xs">${esc(v)}</code>`).join(' ');
      const dlg = document.createElement('div');
      dlg.className = 'pv-mail-modal';
      dlg.innerHTML = `
        <div class="pv-mail-modal-backdrop" data-close></div>
        <div class="pv-mail-modal-card">
          <header class="pv-mail-modal-head">
            <div>
              <div class="hero-kicker mb-1">MAIL CLIENT</div>
              <h2 class="text-xl font-semibold">${esc(tpl.label)}</h2>
              <div class="text-xs text-text-muted mt-1">${esc(tpl.trigger)}</div>
            </div>
            <button class="pv-mail-modal-close" data-close aria-label="Fermer">×</button>
          </header>
          <div class="pv-mail-modal-body">
            <div class="text-xs text-text-muted mb-3">
              Variables disponibles (remplacées automatiquement à l'envoi) : ${variables || '<em>aucune</em>'}
            </div>
            <form id="pv-mail-form" class="space-y-3">
              <div>
                <label class="text-xs font-semibold text-text-muted uppercase tracking-wider">Sujet *</label>
                <input type="text" name="subject" required value="${esc(tpl.subject || '')}" class="phare-input">
              </div>
              <div>
                <label class="text-xs font-semibold text-text-muted uppercase tracking-wider">Texte d'aperçu en boîte de réception</label>
                <input type="text" name="preheader" value="${esc(tpl.preheader || '')}" placeholder="Texte court qui apparaît dans la liste des mails" class="phare-input">
              </div>
              <div>
                <label class="text-xs font-semibold text-text-muted uppercase tracking-wider">Petit badge</label>
                <input type="text" name="eyebrow" value="${esc(tpl.eyebrow || '')}" placeholder="ex : Paiement validé" class="phare-input">
              </div>
              <div>
                <label class="text-xs font-semibold text-text-muted uppercase tracking-wider">Titre principal *</label>
                <textarea name="title" required rows="2" placeholder="Peut contenir &lt;br&gt; pour une césure" class="phare-input" style="font-family: ui-monospace, monospace; font-size: 13px;">${esc(tpl.title || '')}</textarea>
              </div>
              <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label class="text-xs font-semibold text-text-muted uppercase tracking-wider">Bouton — texte</label>
                  <input type="text" name="cta_label" value="${esc(tpl.cta_label || '')}" placeholder="Voir mon site →" class="phare-input">
                </div>
                <div>
                  <label class="text-xs font-semibold text-text-muted uppercase tracking-wider">Bouton — URL</label>
                  <input type="text" name="cta_url" value="${esc(tpl.cta_url || '')}" placeholder="{site_url} ou https://..." class="phare-input">
                </div>
              </div>
              <div class="text-xs text-text-muted pt-2">
                Le reste du contenu du mail (paragraphes, blocs colorés…) n'est pas modifiable ici pour l'instant. Tu peux régler les éléments les plus visibles : sujet, titre, badge, bouton.
                ${tpl.updated_at ? `<div class="mt-1">Dernière modif : ${esc(this._fmtDate(tpl.updated_at))}${tpl.updated_by ? ' par ' + esc(tpl.updated_by) : ''}</div>` : ''}
              </div>
            </form>
          </div>
          <footer class="pv-mail-modal-foot">
            <button class="btn btn-secondary" data-close>Annuler</button>
            <button class="btn btn-primary" data-save>Enregistrer</button>
          </footer>
        </div>
      `;
      document.body.appendChild(dlg);
      // Garde anti-perte de saisie : fermer avec du texte modifié demande
      // confirmation (Annuler, clic à côté). Enregistrer ferme directement.
      let dirty = false;
      dlg.querySelector('#pv-mail-form').addEventListener('input', () => { dirty = true; });
      const close = () => dlg.remove();
      const requestClose = async () => {
        if (dirty) {
          const okClose = await Dialog.confirm(
            'Tes modifications ne sont pas enregistrées et seront perdues. Fermer quand même ?',
            { title: 'Modifications non enregistrées', okLabel: 'Fermer sans enregistrer', cancelLabel: 'Rester', danger: true }
          );
          if (!okClose) return;
        }
        close();
      };
      dlg.querySelectorAll('[data-close]').forEach(el => el.onclick = requestClose);
      const saveBtn = dlg.querySelector('[data-save]');
      saveBtn.onclick = async () => {
        const fd = new FormData(dlg.querySelector('#pv-mail-form'));
        const payload = {
          key: tpl.key,
          subject:   (fd.get('subject') || '').toString().trim(),
          preheader: (fd.get('preheader') || '').toString().trim(),
          eyebrow:   (fd.get('eyebrow') || '').toString().trim(),
          title:     (fd.get('title') || '').toString().trim(),
          cta_label: (fd.get('cta_label') || '').toString().trim(),
          cta_url:   (fd.get('cta_url') || '').toString().trim(),
        };
        if (!payload.subject || !payload.title) {
          Toast.error('Sujet et titre sont obligatoires.');
          return;
        }
        saveBtn.disabled = true;
        try {
          const r = await App.api.lagriffe_mail_template_save(payload);
          if (r && r.ok) {
            Toast.success('Mail enregistré.');
            close();
          } else {
            Toast.friendlyError(r && r.error, `L'enregistrement du mail n'a pas abouti.`);
          }
        } catch (e) {
          Toast.friendlyError(e, `L'enregistrement du mail n'a pas abouti.`);
        } finally {
          saveBtn.disabled = false;
        }
      };
      setTimeout(() => dlg.querySelector('input[name="subject"]').focus(), 50);
    },

    // Délégué au système commun (toast.js) — signature conservée pour
    // les appels historiques de cette vue.
    _toast(msg, kind = 'success') {
      if (kind === 'error') Toast.error(msg);
      else Toast.success(msg);
    },

    _fmtDate(iso) {
      if (!iso) return '—';
      try {
        const d = new Date(iso);
        return d.toLocaleString('fr-FR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
      } catch { return iso.slice(0, 16); }
    },

    _fmtDateLong(iso) {
      if (!iso) return '—';
      try {
        const d = new Date(iso);
        return d.toLocaleString('fr-FR', { dateStyle: 'medium', timeStyle: 'short' });
      } catch { return iso; }
    },
  };

  return view;
}

// Constantes partagées (statuts communs aux 3 offres)
const PIPELINE_BASE_STATUS_LABELS = {
  pending_validation: 'À valider',
  approved: 'Approuvé · démarre sous 5 min',
  processing: 'Génération en cours',
  sent: 'Preview envoyée',
  paid: 'Payé · à finaliser',
  finalizing: 'Finalisation en cours',
  live: 'Site final en ligne',
  rejected: 'Refusé',
  failed: 'Échec preview',
  final_failed: 'Échec finalisation',
};

const PIPELINE_BASE_STATUS_COLORS = {
  pending_validation: 'warning',
  approved: 'accent',
  processing: 'accent',
  sent: 'success',
  paid: 'gold',
  finalizing: 'accent',
  live: 'success',
  rejected: 'text-muted',
  failed: 'danger',
  final_failed: 'danger',
};

const PIPELINE_BASE_STAGES = [
  { key: 'pending_validation', label: 'Brief reçu',           sub: 'En attente de validation humaine' },
  { key: 'approved',           label: 'Approuvé',             sub: 'Démarrage auto sous 5 min' },
  { key: 'processing',         label: `L'IA fabrique le site`, sub: 'Fabrication en cours' },
  { key: 'sent',               label: 'Preview envoyée',      sub: 'Client a reçu le mail' },
  { key: 'paid',               label: 'Payé',                 sub: 'Paiement confirmé' },
  { key: 'finalizing',         label: 'Finalisation',         sub: 'Toutes les pages, visuels' },
  { key: 'live',               label: 'En ligne',             sub: 'Site final livré' },
];

// Table de libellés français exposée pour les autres scripts (le panneau
// « mouvements » du Cockpit, pipelines_activity.js, l'utilise pour traduire
// les statuts bruts). Complétée avec les statuts hors socle commun.
window.PipelineView = window.PipelineView || {};
window.PipelineView.STATUS_LABELS_FR = {
  ...PIPELINE_BASE_STATUS_LABELS,
  final_ready_review: 'Final à valider',   // Lagriffe
  draft: 'Brouillon reçu',                 // Pixel Pros
  building: 'Fabrication en cours',        // Pixel Pros
};
