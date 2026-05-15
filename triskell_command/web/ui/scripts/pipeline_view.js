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
            <button data-pv-tab="logs"      class="pv-tab">Logs d'une demande</button>
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
        listEl.innerHTML = `<div class="card p-6 text-danger">${(resp && resp.error) || 'Erreur API'}</div>`;
        return;
      }
      this.state.intakes = resp.intakes || [];
      const label = this.config.statusLabels[this.state.statusFilter] || 'tous statuts';
      statusEl.textContent = `${this.state.intakes.length} demande(s) · ${label}`;

      if (this.state.intakes.length === 0) {
        listEl.innerHTML = `
          <div class="card p-10 text-center">
            <div class="text-3xl mb-3 opacity-60">∅</div>
            <p class="text-text-muted">Aucune demande dans ce filtre.</p>
          </div>
        `;
        this._renderActionsPane();
        return;
      }
      listEl.innerHTML = this.state.intakes.map(i => this._intakeCard(i)).join('');
      listEl.querySelectorAll('[data-intake-id]').forEach(el => {
        // Clic simple = sélection (panneau actions à droite)
        el.addEventListener('click', () => {
          this.state.selectedId = el.dataset.intakeId;
          this._loadIntakes();
        });
        // Double-clic = ouvre la modale détail complète
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
        <div class="card pv-card-intake p-4 ${isSel ? 'is-selected' : ''}" data-intake-id="${intake.id}">
          <div class="flex items-start justify-between gap-3 mb-2">
            <div class="flex-1 min-w-0">
              <div class="text-sm font-bold truncate">${this._escape(fullName)} · ${this._escape(company)}</div>
              <div class="text-[11px] text-text-muted truncate">${this._escape(email)} · ${this._fmtDate(intake.created_at)}</div>
            </div>
            <span class="text-[10px] font-bold uppercase px-2 py-1 rounded shrink-0"
                  style="background: hsl(var(--${statusColor}) / 0.15); color: hsl(var(--${statusColor}));">
              ${this._escape(statusLabel)}
            </span>
          </div>
          ${metaBits.length ? `<div class="text-[11px] text-text-secondary mb-1">${metaBits.join(' · ')}</div>` : ''}
          ${domLine ? `<div class="text-[11px] text-text-muted mb-2">${domLine}</div>` : ''}
          <div class="text-xs text-text leading-snug line-clamp-3">${this._escape(intake.description || '(pas de brief)')}</div>
          ${payload.nda_souhaite ? `<div class="text-[10px] mt-2 font-bold text-warning">NDA demandé avant premier échange</div>` : ''}
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

      const buttons = [];
      if (status === 'pending_validation') {
        buttons.push({ id: 'pv-act-approve', label: 'Approuver (≈15 € en tokens)', cls: 'btn-primary' });
        buttons.push({ id: 'pv-act-reject',  label: 'Refuser',                     cls: 'btn-secondary' });
      }
      if (status === 'approved') {
        buttons.push({ id: 'pv-act-dispatch', label: 'Forcer le lancement maintenant', cls: 'btn-primary' });
      }
      // Actions spécifiques à l'offre (ex: Lagriffe approve_final si final_ready_review)
      if (typeof this.config.extraActions === 'function') {
        this.config.extraActions(sel).forEach(a => buttons.push(a));
      }
      buttons.push({ id: 'pv-act-detail', label: 'Ouvrir le détail complet', cls: 'btn-primary' });
      buttons.push({ id: 'pv-act-logs', label: 'Voir les logs de cette demande', cls: 'btn-secondary' });

      pane.innerHTML = `
        <div class="card p-5">
          <div class="text-[10px] font-bold tracking-widest text-accent mb-1">DEMANDE SÉLECTIONNÉE</div>
          <div class="text-base font-bold mb-1">${this._escape(fullName)}</div>
          <div class="text-xs text-text-muted mb-4">${this._escape(sel.company_name || '')}</div>
          <div class="flex flex-col gap-2">
            ${buttons.map(b => `<button id="${b.id}" class="btn ${b.cls}">${this._escape(b.label)}</button>`).join('')}
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
      if (approveBtn) approveBtn.onclick = async () => {
        if (!confirm(`Approuver et lancer la preview pour :\n\n${fullName} · ${sel.company_name}\n\nCoût ≈ 15 € HT. Non réversible.`)) return;
        setMsg('Approbation…');
        const r = await this._call('approve_intake', { id: sel.id });
        if (!r || !r.ok) { setMsg(`Échec : ${r && r.error || 'inconnu'}`, true); return; }
        setMsg('Approuvé. Déclenchement immédiat…');
        const d = await this._call('dispatch_now', { id: sel.id });
        if (d && d.ok) setMsg(`Lancement OK : ${d.message || ''}`);
        else setMsg(`Approuvé. Cron Netlify reprendra dans 5 min.`);
        await this._loadIntakes();
      };

      const rejectBtn = document.getElementById('pv-act-reject');
      if (rejectBtn) rejectBtn.onclick = async () => {
        const reason = prompt('Motif du refus (optionnel) :') ?? null;
        if (reason === null) return;
        setMsg('Refus…');
        const r = await this._call('reject_intake', { id: sel.id, reason });
        if (r && r.ok) { setMsg('Demande refusée.'); await this._loadIntakes(); }
        else setMsg(`Échec : ${r && r.error || 'inconnu'}`, true);
      };

      const dispatchBtn = document.getElementById('pv-act-dispatch');
      if (dispatchBtn) dispatchBtn.onclick = async () => {
        if (!confirm(`Forcer le lancement immédiat ?\n\n${fullName} · ${sel.company_name}`)) return;
        setMsg('Déclenchement…');
        const r = await this._call('dispatch_now', { id: sel.id });
        if (r && r.ok) { setMsg(`OK : ${r.message || ''}`); await this._loadIntakes(); }
        else setMsg(`Échec : ${r && r.error || 'inconnu'}`, true);
      };

      // Bind les actions custom si elles ont fourni un onClick callback
      buttons.forEach(b => {
        if (b.onClick) {
          const el = document.getElementById(b.id);
          if (el) el.onclick = () => b.onClick({ intake: sel, setMsg, call: this._call.bind(this), reload: () => this._loadIntakes() });
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
      overlay.style.background = 'rgba(15,23,42,0.7)';
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
              <span class="text-[10px] font-bold uppercase px-3 py-1.5 rounded"
                    style="background: hsl(var(--${statusColor}) / 0.15); color: hsl(var(--${statusColor}));">
                ${this._escape(statusLabel)}
              </span>
              <button id="pvd-close" class="w-8 h-8 rounded-lg flex items-center justify-center text-text-muted hover:text-text hover:bg-bg text-xl leading-none">×</button>
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
              <button id="pvd-close-2" class="btn btn-secondary">Fermer</button>
            </div>
          </div>
        </div>
      `;
      document.body.appendChild(overlay);
      const close = () => overlay.remove();
      overlay.querySelector('#pvd-close').onclick = close;
      overlay.querySelector('#pvd-close-2').onclick = close;
      overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
      overlay.querySelector('#pvd-logs').onclick = () => {
        this.state.selectedId = intake.id;
        close();
        this.switchTab('logs');
      };
      document.addEventListener('keydown', function esc(e) {
        if (e.key === 'Escape') { close(); document.removeEventListener('keydown', esc); }
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
      this._root.innerHTML = `
        <div class="card p-6 mb-5">
          <div class="flex items-center justify-between mb-1">
            <div>
              <div class="hero-kicker mb-1">PIPELINE</div>
              <h2 class="text-xl font-bold">Le parcours d'une demande, étage par étage.</h2>
            </div>
            <div class="text-[11px] text-text-muted" id="pv-pipe-clock">Mise à jour : —</div>
          </div>
          <p class="text-text-muted text-sm mb-3">Un étage clignote dès qu'au moins une demande s'y trouve. Clic sur une étape = voir les demandes correspondantes.</p>
          <!-- Légende code couleur -->
          <div class="flex items-center gap-4 mb-5 text-[11px] text-text-muted">
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
              <span class="font-semibold" style="color: hsl(var(--warning));">action requise</span>
            </div>
          </div>
          <div id="pv-pipe-flow" class="flex items-stretch gap-1 overflow-x-auto pb-2"></div>
          <div class="mt-6 grid grid-cols-3 gap-3" id="pv-pipe-deadends"></div>
        </div>

        <div class="card p-5">
          <div class="hero-kicker mb-3">5 DERNIÈRES DEMANDES</div>
          <div id="pv-pipe-recent" class="space-y-2"></div>
        </div>
      `;
      await this._loadPipeline();
      this.state.pollHandle = setInterval(() => this._loadPipeline(true), 5000);
    },

    async _loadPipeline(silent = false) {
      if (!App.api) {
        const flow = document.getElementById('pv-pipe-flow');
        if (flow) flow.innerHTML = this._noBackend();
        return;
      }
      const r = await this._call('pipeline_state');
      if (!r || !r.ok) return;
      this.state.pipeline = r;
      this._renderPipelineFlow(r);
      this._renderPipelineRecent(r.recent || []);
      const clock = document.getElementById('pv-pipe-clock');
      if (clock) clock.textContent = `Mise à jour : ${new Date().toLocaleTimeString('fr-FR')}`;
    },

    _renderPipelineFlow(state) {
      const flow = document.getElementById('pv-pipe-flow');
      if (!flow) return;
      const counts = state.counts || {};
      // Statuts qui nécessitent une intervention humaine
      const interventionSet = new Set(this.config.interventionStatuses || [
        'pending_validation', 'paid', 'final_ready_review',
      ]);
      const html = [];
      this.config.stages.forEach((st, idx) => {
        const n = counts[st.key] || 0;
        const empty = n === 0;
        const needsIntervention = !empty && interventionSet.has(st.key);
        // Couleur : gris (vide) · orange (action requise) · bleu (en cours auto)
        const color = empty ? 'text-muted'
                    : needsIntervention ? 'warning'
                    : 'accent';
        const borderColor = empty ? 'hsl(var(--border))'
                          : `hsl(var(--${color}))`;
        const stateClass = needsIntervention ? 'is-attention'
                         : (!empty ? 'is-active' : '');
        const counterClass = empty ? 'text-text-muted opacity-40'
                           : `text-${color}`;
        html.push(`
          <div class="pv-pipe-stage card flex-1 min-w-[160px] p-3 ${stateClass} relative group"
               style="border-color: ${borderColor};${needsIntervention ? ' background: hsl(var(--warning) / 0.06);' : ''}"
               data-pv-jump="${this._escape(st.key)}"
               title="Cliquer pour voir les demandes à cette étape">
            <div class="flex items-baseline justify-between mb-1">
              <div class="text-[9px] font-bold tracking-widest text-text-muted">ÉTAPE ${idx + 1}</div>
              <div class="text-2xl font-bold ${counterClass}">${n}</div>
            </div>
            <div class="text-sm font-semibold leading-tight">${this._escape(st.label)}</div>
            <div class="text-[11px] text-text-muted mt-1 leading-tight">${this._escape(st.sub || '')}</div>
            ${needsIntervention ? `
              <div class="text-[10px] font-bold uppercase tracking-widest mt-2 flex items-center gap-1" style="color: hsl(var(--warning));">
                <span>● Action requise</span>
              </div>` : ''}
            ${!empty ? `
              <div class="absolute bottom-2 right-2 text-[10px] font-semibold opacity-0 group-hover:opacity-100 transition-opacity"
                   style="color: hsl(var(--${color}));">
                Voir →
              </div>` : ''}
          </div>
        `);
        if (idx < this.config.stages.length - 1) {
          const flowActive = (counts[this.config.stages[idx + 1].key] || 0) > 0 || !empty;
          html.push(`<div class="pv-pipe-arrow ${flowActive ? 'is-active' : ''}"></div>`);
        }
      });
      flow.innerHTML = html.join('');

      // Click sur une étape → bascule sur l'onglet Demandes filtré sur ce statut
      flow.querySelectorAll('[data-pv-jump]').forEach(el => {
        const status = el.dataset.pvJump;
        const n = counts[status] || 0;
        if (n === 0) {
          el.style.cursor = 'default';
          el.removeAttribute('title');
          return;
        }
        el.style.cursor = 'pointer';
        el.addEventListener('click', () => {
          this.state.statusFilter = status;
          this.state.selectedId = null;
          this.switchTab('dashboard');
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
              <div class="text-[10px] font-bold tracking-widest text-text-muted">VOIE SANS ISSUE</div>
              <div class="text-sm font-semibold">${this._escape(d.label)}</div>
            </div>
            <div class="text-2xl font-bold" style="color: hsl(var(--${d.color}));">${n}</div>
          </div>
        `;
      }).join('');
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
               data-recent-id="${i.id}">
            <div class="min-w-0">
              <div class="text-sm font-semibold truncate">${this._escape(fullName)} · ${this._escape(i.company_name || '')}</div>
              <div class="text-[11px] text-text-muted">${this._fmtDate(i.created_at)}</div>
            </div>
            <span class="text-[10px] font-bold uppercase px-2 py-1 rounded shrink-0"
                  style="background: hsl(var(--${statusColor}) / 0.15); color: hsl(var(--${statusColor}));">
              ${this._escape(statusLabel)}
            </span>
          </div>
        `;
      }).join('');
      el.querySelectorAll('[data-recent-id]').forEach(row => {
        row.addEventListener('click', () => {
          this.state.selectedId = row.dataset.recentId;
          this.switchTab('logs');
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
            <p class="text-text-muted mb-5">Va dans l'onglet <b>Demandes</b> ou <b>Plomberie</b>, clique sur une carte, puis reviens ici.</p>
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
        document.getElementById('pv-logs-timeline').innerHTML =
          `<div class="text-danger">${(r && r.error) || 'Erreur API'}</div>`;
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
            <span class="text-[10px] font-bold uppercase px-3 py-1.5 rounded"
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
                   style="background: hsl(var(--${c})); color: white; font-size: 11px; font-weight: bold;">
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
          <h2 class="text-lg font-bold mb-2">Backend pywebview non disponible.</h2>
          <p class="text-text-muted text-sm">Lance Triskell Command via <code class="text-xs px-1.5 py-0.5 rounded bg-bg">python run_web.py</code> pour voir les vraies données.</p>
        </div>
      `;
    },

    _escape(s) {
      return String(s ?? '')
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
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
  approved: 'Approuvé · attente cron',
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
  { key: 'pending_validation', label: 'Brief reçu',         sub: 'En attente de validation humaine' },
  { key: 'approved',           label: 'Approuvé',           sub: 'Cron Netlify · 5 min max' },
  { key: 'processing',         label: 'Claude Code génère', sub: 'GitHub Actions en route' },
  { key: 'sent',               label: 'Preview envoyée',    sub: 'Client a reçu le mail' },
  { key: 'paid',               label: 'Payé',               sub: 'Stripe a confirmé' },
  { key: 'finalizing',         label: 'Finalisation',       sub: 'Toutes les pages, visuels' },
  { key: 'live',               label: 'En ligne',           sub: 'Site final livré' },
];
