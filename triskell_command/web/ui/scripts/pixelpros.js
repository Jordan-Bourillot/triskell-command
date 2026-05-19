/* Vue Pixel Pros — pipeline d'inscription / construction / livraison.
 *
 * Workflow plus court que Lagriffe/RankUs/WoW (pas de validation humaine) :
 *   draft → paid → building → live (ou failed)
 *
 * Données venues de Supabase table pp_client_drafts via :
 *   App.api.pixelpros_list_intakes({ status?, limit? })
 *   App.api.pixelpros_get_intake({ id })
 *   App.api.pixelpros_dispatch_build({ id })
 *   App.api.pixelpros_mark_failed({ id, reason? })
 *   App.api.pixelpros_resend_paid_mail({ id })
 *   App.api.pixelpros_resend_live_mail({ id })
 *   App.api.pixelpros_pipeline_state()
 */

const PixelPros = {
  state: {
    statusFilter: '',          // '' = tous
    intakes: [],
    selectedId: null,
    detail: null,
    counts: null,
    loading: false,
  },

  STATUSES: [
    { key: '',         label: 'Tous',              color: 'text-muted' },
    { key: 'draft',    label: 'Formulaire reçu',   color: 'text-muted' },
    { key: 'paid',     label: 'Payé · à construire', color: 'gold' },
    { key: 'building', label: 'Construction en cours', color: 'accent' },
    { key: 'live',     label: 'En ligne',          color: 'success' },
    { key: 'failed',   label: 'Échec',             color: 'danger' },
  ],

  FORMULES: {
    base:        { label: 'Site seul',                 price: '24,90 €' },
    base_domain: { label: 'Site + domaine',            price: '33,90 €' },
    base_seo:    { label: 'Site + SEO',                price: '59,80 €' },
    base_all:    { label: 'Site + domaine + SEO',      price: '68,80 €' },
    combo:       { label: 'Pack TOUT-EN-UN',           price: '49,90 €' },
  },

  async render(container) {
    this._root = container;
    container.innerHTML = `
      <section class="animate-slide-up">
        <div class="mb-6 flex items-end justify-between flex-wrap gap-3">
          <div>
            <div class="hero-kicker mb-2" style="color:#facc15;">PIXEL PROS</div>
            <h1 class="hero-title mb-3" style="font-size: 36px;">Les sites client en cours.</h1>
            <p class="hero-subtitle">Chaque inscription, son statut, et un bouton pour relancer la construction si besoin.</p>
          </div>
          <button id="pp-refresh" class="btn btn-secondary">Rafraîchir</button>
        </div>

        <div id="pp-counts" class="mb-6"></div>

        <div class="flex gap-2 mb-4 flex-wrap" id="pp-filters"></div>

        <div id="pp-list" class="grid gap-3"></div>

        <div id="pp-detail" class="mt-8"></div>
      </section>
    `;
    this._injectStyles();
    document.getElementById('pp-refresh').onclick = () => this.refresh();
    this._renderFilters();
    await this.refresh();
  },

  _injectStyles() {
    if (document.getElementById('pp-styles')) return;
    const s = document.createElement('style');
    s.id = 'pp-styles';
    s.textContent = `
      .pp-pill { display:inline-flex; align-items:center; gap:6px; padding:2px 10px; border-radius:999px; font-size:11px; font-weight:700; letter-spacing:.02em; }
      .pp-pill.gold { background:rgba(250,204,21,.15); color:#facc15; }
      .pp-pill.success { background:rgba(34,197,94,.15); color:#22c55e; }
      .pp-pill.danger { background:rgba(239,68,68,.15); color:#ef4444; }
      .pp-pill.accent { background:rgba(99,102,241,.15); color:#818cf8; }
      .pp-pill.text-muted { background:rgba(148,163,184,.15); color:#94a3b8; }
      .pp-card { background:var(--surface, #0f172a); border:1px solid var(--border, #1e293b); border-radius:12px; padding:16px 18px; transition:border-color .15s; }
      .pp-card:hover { border-color:#facc15; }
      .pp-card.selected { border-color:#facc15; box-shadow: 0 0 0 1px #facc15; }
      .pp-count { display:inline-flex; flex-direction:column; align-items:center; padding:12px 18px; min-width:88px; border:1px solid var(--border, #1e293b); border-radius:10px; background:var(--surface, #0f172a); }
      .pp-count .n { font-size:22px; font-weight:800; line-height:1; }
      .pp-count .l { font-size:10px; font-weight:700; letter-spacing:.06em; text-transform:uppercase; color:#94a3b8; margin-top:6px; }
      .pp-filter-btn { padding:6px 12px; border-radius:999px; font-size:12px; font-weight:700; border:1px solid var(--border, #1e293b); background:transparent; color:#94a3b8; cursor:pointer; }
      .pp-filter-btn.active { background:#facc15; color:#0f172a; border-color:#facc15; }
      .pp-detail { background:var(--surface, #0f172a); border:1px solid var(--border, #1e293b); border-radius:12px; padding:22px; }
      .pp-action-btn { padding:8px 14px; border-radius:8px; font-size:13px; font-weight:700; cursor:pointer; border:none; }
      .pp-action-btn.primary { background:#facc15; color:#0f172a; }
      .pp-action-btn.secondary { background:rgba(148,163,184,.15); color:#cbd5e1; }
      .pp-action-btn.danger { background:rgba(239,68,68,.15); color:#ef4444; }
      .pp-action-btn:hover { filter:brightness(1.1); }
      .pp-action-btn:disabled { opacity:.5; cursor:not-allowed; }
      .pp-timeline-row { display:flex; gap:10px; padding:6px 0; font-size:12.5px; color:#cbd5e1; }
      .pp-timeline-row .ts { color:#64748b; min-width:130px; font-variant-numeric: tabular-nums; }
    `;
    document.head.appendChild(s);
  },

  _renderFilters() {
    const el = document.getElementById('pp-filters');
    el.innerHTML = this.STATUSES.map(s =>
      `<button class="pp-filter-btn ${this.state.statusFilter === s.key ? 'active' : ''}" data-st="${s.key}">${this._escape(s.label)}</button>`
    ).join('');
    el.querySelectorAll('[data-st]').forEach(b => {
      b.onclick = () => { this.state.statusFilter = b.dataset.st; this.refresh(); };
    });
  },

  async refresh() {
    this.state.loading = true;
    this._renderList();
    // pipeline state (compteurs) + liste filtrée
    const [stateRes, listRes] = await Promise.all([
      this._call('pixelpros_pipeline_state'),
      this._call('pixelpros_list_intakes', { status: this.state.statusFilter, limit: 100 }),
    ]);
    if (stateRes && stateRes.ok) {
      this.state.counts = stateRes.counts || null;
    }
    if (listRes && listRes.ok) {
      this.state.intakes = listRes.intakes || [];
    } else if (listRes && listRes.error) {
      this.state.intakes = [];
      console.warn('pixelpros: list_intakes', listRes.error);
    }
    this.state.loading = false;
    this._renderCounts();
    this._renderFilters();
    this._renderList();
    if (this.state.selectedId) {
      await this._loadDetail(this.state.selectedId);
    }
  },

  _renderCounts() {
    const el = document.getElementById('pp-counts');
    if (!el) return;
    const c = this.state.counts;
    if (!c) { el.innerHTML = ''; return; }
    const items = [
      { k: 'draft',    l: 'Formulaire' },
      { k: 'paid',     l: 'Payé' },
      { k: 'building', l: 'En constru.' },
      { k: 'live',     l: 'En ligne' },
      { k: 'failed',   l: 'Échec' },
    ];
    el.innerHTML = `<div class="flex gap-3 flex-wrap">${items.map(i =>
      `<div class="pp-count"><div class="n">${c[i.k] || 0}</div><div class="l">${i.l}</div></div>`
    ).join('')}</div>`;
  },

  _renderList() {
    const el = document.getElementById('pp-list');
    if (!el) return;
    if (this.state.loading) { el.innerHTML = `<div style="color:#94a3b8; padding:18px;">Chargement…</div>`; return; }
    if (!this.state.intakes.length) {
      el.innerHTML = `<div style="color:#94a3b8; padding:30px; text-align:center; border:1px dashed var(--border, #1e293b); border-radius:12px;">Aucune inscription pour ce filtre.</div>`;
      return;
    }
    el.innerHTML = this.state.intakes.map(it => this._renderCard(it)).join('');
    el.querySelectorAll('[data-pp-id]').forEach(card => {
      card.onclick = () => {
        this.state.selectedId = card.dataset.ppId;
        this._loadDetail(this.state.selectedId);
        el.querySelectorAll('.pp-card').forEach(c => c.classList.remove('selected'));
        card.classList.add('selected');
      };
    });
  },

  _renderCard(it) {
    const status = this.STATUSES.find(s => s.key === it.status) || { label: it.status || '?', color: 'text-muted' };
    const data = it.data || {};
    const businessName = data.business_name || data['business-name'] || '(sans nom)';
    const email = data.email || it.contact_email || '?';
    const created = this._fmtDate(it.created_at);
    const option = it.option || data.option || '';
    const formule = this.FORMULES[option] || { label: option || '—', price: '' };
    return `
      <div class="pp-card ${this.state.selectedId === it.id ? 'selected' : ''}" data-pp-id="${this._escape(it.id)}" style="cursor:pointer;">
        <div class="flex items-center justify-between gap-3 flex-wrap">
          <div style="min-width:0;">
            <div style="font-weight:700; font-size:15px; color:#e2e8f0;">${this._escape(businessName)}</div>
            <div style="font-size:12px; color:#94a3b8; margin-top:2px;">${this._escape(email)}</div>
          </div>
          <div class="flex items-center gap-3 flex-wrap">
            <span style="font-size:12px; color:#cbd5e1;">${this._escape(formule.label)} ${formule.price ? `· ${formule.price}` : ''}</span>
            <span class="pp-pill ${status.color}">${this._escape(status.label)}</span>
            <span style="font-size:11px; color:#64748b;">${created}</span>
          </div>
        </div>
      </div>
    `;
  },

  async _loadDetail(id) {
    const el = document.getElementById('pp-detail');
    if (!el) return;
    el.innerHTML = `<div style="color:#94a3b8; padding:18px;">Chargement…</div>`;
    const res = await this._call('pixelpros_get_intake', { id });
    if (!res || !res.ok) {
      el.innerHTML = `<div class="pp-detail" style="color:#ef4444;">Erreur de chargement : ${this._escape(res?.error || 'inconnue')}</div>`;
      return;
    }
    this.state.detail = res;
    this._renderDetail();
  },

  _renderDetail() {
    const el = document.getElementById('pp-detail');
    if (!el || !this.state.detail) return;
    const { intake, timeline } = this.state.detail;
    const data = intake.data || {};
    const businessName = data.business_name || data['business-name'] || '(sans nom)';
    const status = this.STATUSES.find(s => s.key === intake.status) || { label: intake.status, color: 'text-muted' };

    const actions = this._availableActions(intake);

    el.innerHTML = `
      <div class="pp-detail">
        <div class="flex items-start justify-between mb-4 flex-wrap gap-3">
          <div>
            <div style="font-weight:800; font-size:20px; color:#e2e8f0;">${this._escape(businessName)}</div>
            <div style="font-size:13px; color:#94a3b8; margin-top:4px;">${this._escape(data.email || '?')} · ${this._escape(data.phone || '')}</div>
          </div>
          <span class="pp-pill ${status.color}">${this._escape(status.label)}</span>
        </div>

        <div class="flex gap-2 flex-wrap mb-5">${actions.join('')}</div>

        ${intake.site_url ? `<div style="margin-bottom:14px;"><a href="${this._escape(intake.site_url)}" target="_blank" rel="noopener" style="color:#facc15; font-weight:700; text-decoration:underline;">→ Voir le site en ligne</a></div>` : ''}

        ${intake.stripe_session_id ? `<div style="margin-bottom:14px; font-size:12px; color:#94a3b8;">Stripe session : <code style="color:#cbd5e1;">${this._escape(intake.stripe_session_id)}</code></div>` : ''}

        ${(data.error || (intake.data && intake.data.error)) ? `<div style="margin-bottom:14px; padding:10px 14px; background:rgba(239,68,68,.1); border:1px solid rgba(239,68,68,.3); border-radius:8px; color:#fca5a5; font-size:13px;">⚠ ${this._escape(data.error || intake.data.error)}</div>` : ''}

        <details style="margin-bottom:18px;">
          <summary style="cursor:pointer; color:#94a3b8; font-size:13px; font-weight:600;">Voir les données du formulaire</summary>
          <pre style="margin-top:10px; padding:14px; background:#020617; border-radius:8px; font-size:11px; color:#cbd5e1; overflow:auto; max-height:400px;">${this._escape(JSON.stringify(data, null, 2))}</pre>
        </details>

        <div style="border-top:1px solid var(--border, #1e293b); padding-top:14px;">
          <div style="font-size:12px; font-weight:700; letter-spacing:.06em; color:#94a3b8; text-transform:uppercase; margin-bottom:8px;">Chronologie</div>
          ${(timeline || []).map(ev => `
            <div class="pp-timeline-row">
              <span class="ts">${this._fmtDate(ev.ts)}</span>
              <span>${this._escape(ev.label)}</span>
            </div>
          `).join('')}
        </div>
      </div>
    `;

    el.querySelectorAll('[data-pp-action]').forEach(b => {
      b.onclick = () => this._doAction(b.dataset.ppAction, intake);
    });
  },

  _availableActions(intake) {
    const actions = [];
    const st = intake.status;

    // Lancer / relancer le build (pour paid, failed, building OU live = debug)
    if (st === 'paid' || st === 'failed' || st === 'building' || st === 'live') {
      const label = st === 'paid' ? '▶ Lancer la construction'
                  : st === 'failed' ? '↻ Relancer la construction'
                  : st === 'live' ? '↻ Reconstruire (debug)'
                  : '↻ Relancer (forcer)';
      actions.push(`<button data-pp-action="dispatch" class="pp-action-btn primary">${label}</button>`);
    }

    // Marquer failed (pour débloquer)
    if (st === 'building' || st === 'paid') {
      actions.push(`<button data-pp-action="mark_failed" class="pp-action-btn danger">Marquer comme échec</button>`);
    }

    // Renvoi des mails
    if (st !== 'draft') {
      actions.push(`<button data-pp-action="resend_paid_mail" class="pp-action-btn secondary">Renvoyer mail "merci paiement"</button>`);
    }
    if (st === 'live') {
      actions.push(`<button data-pp-action="resend_live_mail" class="pp-action-btn secondary">Renvoyer mail "site en ligne"</button>`);
    }

    return actions;
  },

  async _doAction(action, intake) {
    const id = intake.id;
    let res = null;
    switch (action) {
      case 'dispatch':
        res = await this._call('pixelpros_dispatch_build', { id });
        if (res && res.ok) this._toast(`Build lancé : ${res.message || ''}`);
        else this._toast(`Échec : ${res?.error || res?.message || '?'}`, true);
        break;
      case 'mark_failed': {
        const reason = prompt('Raison de l\'échec (optionnel) :', '');
        if (reason === null) return;
        res = await this._call('pixelpros_mark_failed', { id, reason });
        if (res && res.ok) this._toast('Marqué comme échec');
        else this._toast(`Échec : ${res?.error || '?'}`, true);
        break;
      }
      case 'resend_paid_mail':
        res = await this._call('pixelpros_resend_paid_mail', { id });
        if (res && res.ok) this._toast('Mail "merci paiement" envoyé');
        else this._toast(`Échec : ${res?.error || '?'}`, true);
        break;
      case 'resend_live_mail':
        res = await this._call('pixelpros_resend_live_mail', { id });
        if (res && res.ok) this._toast('Mail "site en ligne" envoyé');
        else this._toast(`Échec : ${res?.error || '?'}`, true);
        break;
    }
    await this.refresh();
  },

  async _call(method, payload) {
    if (!App || !App.api || typeof App.api[method] !== 'function') {
      console.warn(`pixelpros: API.${method} introuvable`);
      return { ok: false, error: 'API absente' };
    }
    try { return await App.api[method](payload); }
    catch (e) { console.warn('pixelpros._call', method, e); return { ok: false, error: String(e) }; }
  },

  _fmtDate(s) {
    if (!s) return '—';
    try {
      const d = new Date(s);
      if (isNaN(d.getTime())) return s;
      return d.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', year: '2-digit' }) + ' ' +
             d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
    } catch { return s; }
  },

  _escape(s) {
    return String(s ?? '').replace(/[&<>"']/g, ch => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[ch]));
  },

  _toast(msg, isError = false) {
    const t = document.createElement('div');
    t.textContent = msg;
    t.style.cssText = `position:fixed; bottom:30px; right:30px; padding:14px 18px; border-radius:10px; font-weight:600; font-size:13px; z-index:9999; box-shadow:0 6px 20px rgba(0,0,0,.4); ${isError ? 'background:#ef4444; color:#fff;' : 'background:#facc15; color:#0f172a;'}`;
    document.body.appendChild(t);
    setTimeout(() => { t.style.opacity = '0'; t.style.transition = 'opacity .3s'; }, 2800);
    setTimeout(() => t.remove(), 3200);
  },
};
