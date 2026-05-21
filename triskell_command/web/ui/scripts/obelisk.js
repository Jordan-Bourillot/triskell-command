/* Obelisk — vue Triskell Command (prospection créateurs).
 *
 * Reprend les fonctions clés de l'app standalone Obelisk :
 *   - Onglet "Créateurs"    : liste paginée + filtres + actions CRM
 *   - Onglet "Recherche"    : lance une recherche (poll job en arrière-plan)
 *   - Onglet "Réglages"     : clés API, IA, catalogue d'offres
 *
 * Backend : api.obelisk_* (cf. integrations/obelisk/repo.py + runner.py).
 * Données : table partagée `prospects` Supabase.
 */

const Obelisk = {
  state: {
    tab: 'creators',
    filters: { platform: '', status: '', min_score: 0, q: '', has_email: '', country: '', job_id: '' },
    jobFilterInfo: null,    // {id, niche, created_at, status} pour afficher la puce
    page: 0,
    pageSize: 50,
    rows: [],
    total: 0,
    stats: null,
    selected: null,         // prospect en cours dans le drawer
    config: null,
    jobId: null,
    jobPoll: null,
  },

  PLATFORMS: [
    { id: 'linkedin',  label: 'LinkedIn',  source: 'phantombuster' },
    { id: 'instagram', label: 'Instagram', source: 'phantombuster' },
    { id: 'tiktok',    label: 'TikTok',    source: 'phantombuster' },
    { id: 'youtube',   label: 'YouTube' },
    { id: 'twitch',    label: 'Twitch' },
    { id: 'reddit',    label: 'Reddit' },
    { id: 'bluesky',   label: 'Bluesky' },
    { id: 'mastodon',  label: 'Mastodon' },
    { id: 'podcasts',  label: 'Apple Podcasts' },
    { id: 'dailymotion', label: 'Dailymotion' },
    { id: 'kick',      label: 'Kick' },
    { id: 'github',    label: 'GitHub' },
  ],

  STATUS_LABELS: {
    new: 'Nouveau', qualified: 'Qualifié', contacted: 'Contacté',
    replied: 'A répondu', refused: 'Refusé', won: 'Gagné', lost: 'Perdu',
  },
  STATUS_COLORS: {
    new: 'text-text-muted bg-bg',
    qualified: 'text-info bg-info/10',
    contacted: 'text-warning bg-warning/10',
    replied: 'text-accent bg-accent/10',
    refused: 'text-danger bg-danger/10',
    won: 'text-success bg-success/15',
    lost: 'text-text-muted bg-text-muted/10',
  },

  async _api(method, payload) {
    if (!App.api) return null;
    const fn = App.api['obelisk_' + method];
    if (typeof fn !== 'function') return null;
    try { return await fn(payload || {}); }
    catch (e) { console.warn('obelisk.' + method, e); return null; }
  },

  // ---------- Notifications : badge sidebar + données pour cockpit ----------
  _SEEN_KEY: 'obelisk-last-seen',

  _lastSeen() {
    try { return localStorage.getItem(this._SEEN_KEY) || ''; }
    catch (e) { return ''; }
  },

  _markAllSeenNow() {
    try {
      const now = new Date().toISOString().slice(0, 19);
      localStorage.setItem(this._SEEN_KEY, now);
    } catch (e) {}
    this._updateNavBadge(0);
  },

  _updateNavBadge(count) {
    const badge = document.getElementById('nav-obelisk-badge');
    if (!badge) return;
    if (count > 0) {
      badge.textContent = String(count);
      badge.hidden = false;
    } else {
      badge.hidden = true;
      badge.textContent = '';
    }
  },

  async checkNotifs() {
    if (!App.api) return { count: 0, jobs: [] };
    let data = null;
    try {
      data = await App.api.obelisk_unseen_done_jobs({ since: this._lastSeen() });
    } catch (e) { return { count: 0, jobs: [] }; }
    if (!data || !data.ok) return { count: 0, jobs: [] };
    this._updateNavBadge(data.count || 0);
    return { count: data.count || 0, jobs: data.jobs || [] };
  },

  _startNotifPolling() {
    if (this._notifPollTimer) return;
    // Premier tick rapide, ensuite toutes les 60 s
    this.checkNotifs();
    this._notifPollTimer = setInterval(() => this.checkNotifs(), 60_000);
  },

  async render(container) {
    this._root = container;
    // Quand l'utilisateur entre dans la vue Obelisk, on considère qu'il
    // a "vu" toutes les recherches en attente → reset du badge.
    this._markAllSeenNow();
    container.innerHTML = `
      <section class="animate-slide-up">
        <header class="ob-header">
          <div class="ob-header-text">
            <div class="hero-kicker">OBELISK</div>
            <h1 class="ob-title">Trouve les créateurs vierges de ta niche</h1>
          </div>
          <div class="ob-header-actions">
            <div id="ob-stats-inline" class="ob-stats-inline"></div>
            <button id="ob-refresh" class="ob-icon-btn" title="Rafraîchir" aria-label="Rafraîchir">↻</button>
          </div>
        </header>

        <nav class="ob-tabs">
          <button data-ob-tab="creators" class="ob-tab is-active">Créateurs</button>
          <button data-ob-tab="search"   class="ob-tab">Nouvelle recherche</button>
          <button data-ob-tab="settings" class="ob-tab">Réglages</button>
        </nav>

        <div id="ob-content"></div>
      </section>
    `;
    this._injectStyles();
    document.getElementById('ob-refresh').onclick = () => this.refresh();
    this._root.querySelectorAll('[data-ob-tab]').forEach(b => {
      b.addEventListener('click', () => this.switchTab(b.dataset.obTab));
    });
    await this.refresh();
  },

  _injectStyles() {
    if (document.getElementById('ob-styles')) return;
    const s = document.createElement('style');
    s.id = 'ob-styles';
    s.textContent = `
      /* Header compact */
      .ob-header {
        display: flex; align-items: flex-start; justify-content: space-between;
        gap: 24px; margin-bottom: 18px; flex-wrap: wrap;
      }
      .ob-header-text { flex: 1; min-width: 0; }
      .ob-title {
        font-size: 26px; font-weight: 700; line-height: 1.15; letter-spacing: -.01em;
        color: hsl(var(--text)); margin-top: 6px;
        font-family: var(--font-display, inherit);
      }
      .ob-header-actions {
        display: flex; align-items: center; gap: 14px;
      }
      .ob-stats-inline {
        display: flex; align-items: center; gap: 18px;
      }
      .ob-stats-inline .stat {
        display: flex; flex-direction: column; align-items: flex-end; line-height: 1;
      }
      .ob-stats-inline .stat .v {
        font-size: 18px; font-weight: 700; color: hsl(var(--text));
        font-variant-numeric: tabular-nums;
      }
      .ob-stats-inline .stat .l {
        font-size: 9.5px; letter-spacing: .12em; text-transform: uppercase;
        color: hsl(var(--text-muted)); font-weight: 600; margin-top: 3px;
      }
      .ob-icon-btn {
        width: 32px; height: 32px; border-radius: 8px;
        background: hsl(var(--card)); border: 1px solid hsl(var(--border));
        color: hsl(var(--text-muted)); font-size: 16px; line-height: 1;
        display: inline-flex; align-items: center; justify-content: center;
        cursor: pointer; transition: all 140ms;
      }
      .ob-icon-btn:hover { color: hsl(var(--text)); border-color: hsl(var(--text-muted) / .5); }

      /* Tabs */
      .ob-tabs {
        display: flex; gap: 4px; margin-bottom: 22px;
        border-bottom: 1px solid hsl(var(--border));
      }
      .ob-tab {
        padding: 10px 18px; font-size: 13px; font-weight: 600;
        color: hsl(var(--text-muted)); background: none; border: none;
        border-bottom: 2px solid transparent;
        transition: color 160ms, border-color 160ms;
        cursor: pointer;
      }
      .ob-tab:hover { color: hsl(var(--text)); }
      .ob-tab.is-active { color: hsl(var(--accent)); border-bottom-color: hsl(var(--accent)); }

      /* Empty state hero (zéro créateur) */
      .ob-empty-hero {
        display: flex; flex-direction: column; align-items: center; justify-content: center;
        padding: 70px 24px; text-align: center;
        background: linear-gradient(180deg, hsl(var(--card)), hsl(var(--card) / .4));
        border: 1px dashed hsl(var(--border)); border-radius: 16px;
      }
      .ob-empty-hero .icon {
        width: 56px; height: 56px; border-radius: 14px;
        background: hsl(var(--accent) / .12); color: hsl(var(--accent));
        display: inline-flex; align-items: center; justify-content: center;
        font-size: 28px; margin-bottom: 18px;
      }
      .ob-empty-hero h2 {
        font-size: 22px; font-weight: 700; color: hsl(var(--text)); margin-bottom: 8px;
      }
      .ob-empty-hero p {
        font-size: 14px; color: hsl(var(--text-muted)); max-width: 520px; line-height: 1.55;
        margin-bottom: 22px;
      }
      .ob-empty-hero .ob-platforms-tease {
        display: flex; flex-wrap: wrap; justify-content: center; gap: 6px;
        margin-top: 18px; max-width: 520px;
      }
      .ob-empty-hero .ob-platforms-tease span {
        font-size: 11px; color: hsl(var(--text-muted));
        padding: 3px 9px; border-radius: 999px;
        background: hsl(var(--bg)); border: 1px solid hsl(var(--border));
      }

      /* Filtres : barre légère, sans cadre lourd */
      .ob-filters {
        display: flex; flex-wrap: wrap; gap: 8px; align-items: center;
        margin-bottom: 14px;
      }
      .ob-search {
        flex: 1; min-width: 240px; position: relative;
      }
      .ob-search input {
        width: 100%; padding: 10px 14px 10px 38px; border-radius: 10px;
        background: hsl(var(--card)); color: hsl(var(--text));
        border: 1px solid hsl(var(--border)); font-size: 13.5px;
      }
      .ob-search::before {
        content: ""; position: absolute; left: 14px; top: 50%;
        width: 14px; height: 14px; transform: translateY(-50%);
        background: hsl(var(--text-muted));
        -webkit-mask: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2.5' stroke-linecap='round'><circle cx='11' cy='11' r='7'/><path d='m20 20-3-3'/></svg>") center/contain no-repeat;
                mask: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2.5' stroke-linecap='round'><circle cx='11' cy='11' r='7'/><path d='m20 20-3-3'/></svg>") center/contain no-repeat;
      }
      .ob-filters select, .ob-filters .ob-num {
        padding: 9px 12px; border-radius: 10px;
        background: hsl(var(--card)); color: hsl(var(--text));
        border: 1px solid hsl(var(--border)); font-size: 13px;
      }
      .ob-filters input:focus, .ob-filters select:focus {
        outline: none; border-color: hsl(var(--accent));
        box-shadow: 0 0 0 3px hsl(var(--accent) / .14);
      }
      .ob-filters .ob-num { width: 110px; }

      /* Active filter chips (résumé) */
      .ob-active-filters {
        display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 12px;
        font-size: 12px; color: hsl(var(--text-muted));
      }
      .ob-active-filters .chip {
        display: inline-flex; align-items: center; gap: 6px;
        padding: 3px 4px 3px 10px; border-radius: 999px;
        background: hsl(var(--accent) / .1); color: hsl(var(--accent));
        font-weight: 600;
      }
      .ob-active-filters .chip.is-job {
        background: hsl(var(--warning) / .14); color: hsl(var(--warning));
        padding-right: 4px;
      }
      .ob-active-filters .chip.is-job button {
        background: hsl(var(--warning) / .2); color: hsl(var(--warning));
      }
      .ob-active-filters .chip button {
        width: 18px; height: 18px; border-radius: 50%;
        background: hsl(var(--accent) / .15); color: hsl(var(--accent));
        border: none; cursor: pointer; font-size: 11px; line-height: 1;
      }

      /* Recherches récentes : lignes cliquables */
      .ob-job-row {
        padding: 10px 4px; border-bottom: 1px solid hsl(var(--border) / .6);
        cursor: pointer; border-radius: 6px;
        transition: background 120ms, padding 120ms;
      }
      .ob-job-row:last-child { border-bottom: none; }
      .ob-job-row:hover {
        background: hsl(var(--accent) / .07);
        padding-left: 10px; padding-right: 10px;
      }
      .ob-job-row:hover .ob-job-row-arrow {
        color: hsl(var(--accent)); transform: translateX(2px);
      }
      .ob-job-row-top {
        display: flex; align-items: center; justify-content: space-between;
        gap: 8px;
      }
      .ob-job-row-niche {
        color: hsl(var(--text)); font-weight: 600; font-size: 12.5px;
        flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis;
        white-space: nowrap;
      }
      .ob-job-row-arrow {
        font-size: 16px; color: hsl(var(--text-muted));
        line-height: 1; transition: transform 120ms, color 120ms;
      }
      .ob-job-row-meta {
        display: flex; justify-content: space-between; align-items: center;
        margin-top: 3px; font-size: 11.5px;
      }
      .ob-active-filters .clear-all {
        font-size: 11.5px; color: hsl(var(--text-muted)); text-decoration: underline;
        background: none; border: none; cursor: pointer; padding: 0 6px;
      }

      /* Tableau */
      .ob-table-card {
        background: hsl(var(--card)); border: 1px solid hsl(var(--border));
        border-radius: 12px; overflow: hidden;
      }
      .ob-table { width: 100%; border-collapse: collapse; font-size: 13px; }
      .ob-table th {
        text-align: left; font-size: 10.5px; letter-spacing: .12em; text-transform: uppercase;
        font-weight: 700; color: hsl(var(--text-muted));
        padding: 12px 14px; border-bottom: 1px solid hsl(var(--border));
        background: hsl(var(--bg) / .4);
      }
      .ob-table td {
        padding: 12px 14px; border-bottom: 1px solid hsl(var(--border) / .6);
        vertical-align: middle;
      }
      .ob-table tr:last-child td { border-bottom: none; }
      .ob-table tr.is-clickable { cursor: pointer; transition: background 100ms; }
      .ob-table tr.is-clickable:hover { background: hsl(var(--accent) / .04); }
      .ob-pill {
        display: inline-block; padding: 3px 9px; border-radius: 999px;
        font-size: 10.5px; font-weight: 600;
        background: hsl(var(--accent) / .12); color: hsl(var(--accent));
      }
      .ob-score {
        display: inline-flex; align-items: center; gap: 8px;
        font-variant-numeric: tabular-nums; font-weight: 700;
      }
      .ob-score-bar {
        width: 36px; height: 4px; border-radius: 2px;
        background: hsl(var(--border)); overflow: hidden; position: relative;
      }
      .ob-score-bar::after {
        content: ""; position: absolute; inset: 0 auto 0 0;
        width: var(--w, 0%); background: currentColor; border-radius: 2px;
      }
      .ob-status-select {
        padding: 5px 26px 5px 10px; border-radius: 999px; font-size: 11.5px;
        background: hsl(var(--bg)); color: hsl(var(--text));
        border: 1px solid hsl(var(--border)); font-weight: 600;
        appearance: none;
        background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='10' height='10' viewBox='0 0 24 24' fill='none' stroke='%23888' stroke-width='3' stroke-linecap='round'><path d='m6 9 6 6 6-6'/></svg>");
        background-repeat: no-repeat;
        background-position: right 8px center;
      }
      .ob-pager {
        display: flex; align-items: center; justify-content: space-between;
        margin-top: 14px; font-size: 12px; color: hsl(var(--text-muted));
      }

      /* Drawer */
      .ob-drawer {
        position: fixed; top: 0; right: 0; bottom: 0; width: 100%; max-width: 520px;
        background: hsl(var(--card)); border-left: 1px solid hsl(var(--border));
        box-shadow: -10px 0 30px rgba(0,0,0,.15); z-index: 80;
        overflow-y: auto; padding: 22px 26px;
        transform: translateX(100%); transition: transform 200ms;
      }
      .ob-drawer.is-open { transform: translateX(0); }
      .ob-drawer-backdrop {
        position: fixed; inset: 0; background: rgba(0,0,0,.35); z-index: 79;
        opacity: 0; pointer-events: none; transition: opacity 160ms;
      }
      .ob-drawer-backdrop.is-open { opacity: 1; pointer-events: auto; }
      .ob-drawer .ob-stat {
        background: hsl(var(--bg)); border: 1px solid hsl(var(--border));
        border-radius: 10px; padding: 14px 16px;
      }
      .ob-drawer .ob-stat .label { font-size: 10.5px; letter-spacing: .14em; text-transform: uppercase; color: hsl(var(--text-muted)); font-weight: 700; }
      .ob-drawer .ob-stat .value { font-size: 24px; font-weight: 700; color: hsl(var(--text)); margin-top: 4px; line-height: 1; }

      /* Onglet Recherche */
      .ob-platform-grid {
        display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px;
      }
      .ob-platform-chip {
        display: flex; align-items: center; gap: 6px;
        padding: 8px 10px; border-radius: 8px; font-size: 12.5px;
        background: hsl(var(--bg)); border: 1px solid hsl(var(--border));
        cursor: pointer; user-select: none;
      }
      .ob-platform-chip.is-on {
        background: hsl(var(--accent) / .12); border-color: hsl(var(--accent));
        color: hsl(var(--accent)); font-weight: 600;
      }
      .ob-radio-grid {
        display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
        gap: 8px;
      }
      .ob-radio-chip {
        display: flex; align-items: center; gap: 8px;
        padding: 10px 12px; border-radius: 8px; font-size: 12.5px;
        background: hsl(var(--bg)); border: 1px solid hsl(var(--border));
        cursor: pointer; user-select: none; transition: all 160ms ease;
      }
      .ob-radio-chip:hover { background: hsl(var(--surface-elevated)); }
      .ob-radio-chip:has(input:checked) {
        background: hsl(var(--accent) / .12); border-color: hsl(var(--accent));
        color: hsl(var(--accent)); font-weight: 600;
      }
      .ob-radio-chip input[type="radio"] {
        accent-color: hsl(var(--accent));
        margin: 0;
      }
      .ob-toggle-row {
        display: flex; align-items: flex-start; gap: 10px;
        padding: 12px 14px; border-radius: 9px;
        background: hsl(var(--bg)); border: 1px solid hsl(var(--border));
        cursor: pointer;
      }
      .ob-toggle-row input[type="checkbox"] {
        margin-top: 2px;
        width: 16px; height: 16px;
        accent-color: hsl(var(--accent));
      }
      .ob-progress {
        background: hsl(var(--bg)); border: 1px solid hsl(var(--border));
        border-radius: 8px; padding: 12px; max-height: 360px; overflow-y: auto;
        font-family: ui-monospace, "SF Mono", Consolas, monospace; font-size: 11.5px;
        white-space: pre-wrap; color: hsl(var(--text-muted));
      }
      /* Barre d'action bulk (suppression sélection / filtrés / tout) */
      .ob-bulkbar {
        position: sticky; top: 0; z-index: 5;
        margin-bottom: 8px;
        background: hsl(var(--surface));
        border: 1px solid hsl(var(--border));
        border-radius: 10px;
        overflow: hidden;
      }
      .ob-bulkbar-inner {
        display: flex; align-items: center; gap: 10px;
        padding: 10px 14px; flex-wrap: wrap;
      }
      .ob-bulkbar-info {
        font-size: 13px; color: hsl(var(--text-secondary));
      }
      .ob-bulkbar-btn {
        font-size: 12.5px !important; padding: 7px 12px !important;
        white-space: nowrap;
      }
      .ob-bulkbar-danger {
        background: hsl(var(--danger)); color: white; border: 0;
      }
      .ob-bulkbar-danger:hover {
        background: hsl(var(--danger) / 0.85);
      }
      .ob-bulkbar-danger-soft {
        background: hsl(var(--danger) / 0.1); color: hsl(var(--danger));
        border: 1px solid hsl(var(--danger) / 0.4);
      }
      .ob-bulkbar-danger-soft:hover {
        background: hsl(var(--danger) / 0.18);
      }
      .ob-table tr.is-selected {
        background: hsl(var(--accent) / 0.08) !important;
      }
      .ob-table input[type="checkbox"] {
        accent-color: hsl(var(--accent));
        cursor: pointer;
      }

      @media (max-width: 720px) {
        .ob-title { font-size: 22px; }
        .ob-stats-inline { gap: 12px; }
        .ob-stats-inline .stat .v { font-size: 16px; }
      }
    `;
    document.head.appendChild(s);
  },

  async refresh() {
    await this._loadStats();
    await this.switchTab(this.state.tab);
  },

  async _loadStats() {
    const wrap = document.getElementById('ob-stats-inline');
    const res = await this._api('stats');
    const st = (res && res.ok && res.stats) ? res.stats : { total: 0, with_email: 0, qualified: 0, contacted: 0, won: 0 };
    this.state.stats = st;
    if (!wrap) return;
    // Si zéro partout, on cache les stats — l'empty hero portera tout le poids.
    if (!st.total) { wrap.innerHTML = ''; return; }
    wrap.innerHTML = `
      ${this._statInline('Total', st.total)}
      ${this._statInline('Emails', st.with_email)}
      ${this._statInline('Qualifiés', st.qualified)}
      ${this._statInline('Contactés', st.contacted)}
      ${this._statInline('Gagnés', st.won)}
    `;
  },
  _statInline(label, value) {
    return `<div class="stat"><span class="v">${Number(value || 0).toLocaleString('fr-FR')}</span><span class="l">${this._esc(label)}</span></div>`;
  },

  async switchTab(name) {
    this.state.tab = name;
    this._root.querySelectorAll('[data-ob-tab]').forEach(b => b.classList.toggle('is-active', b.dataset.obTab === name));
    if (name === 'creators') return this._renderCreators();
    if (name === 'search')   return this._renderSearch();
    if (name === 'settings') return this._renderSettings();
  },

  // -------------------------------------------------------------------
  // Onglet Créateurs : filtres + tableau paginé
  // -------------------------------------------------------------------
  _hasActiveFilters() {
    const f = this.state.filters;
    return !!(f.q || f.platform || f.status || f.has_email || f.min_score || f.country || f.job_id);
  },

  async _renderCreators() {
    const c = document.getElementById('ob-content');
    const totalAll = (this.state.stats && this.state.stats.total) || 0;

    // Si aucun créateur en base ET aucun filtre actif → grand empty hero
    if (totalAll === 0 && !this._hasActiveFilters()) {
      c.innerHTML = this._emptyHeroHtml();
      const cta = document.getElementById('ob-empty-cta');
      if (cta) cta.onclick = () => this.switchTab('search');
      return;
    }

    c.innerHTML = `
      <div class="ob-filters">
        <div class="ob-search">
          <input id="ob-f-q" placeholder="Rechercher un nom, un handle, un site…" value="${this._esc(this.state.filters.q)}">
        </div>
        <select id="ob-f-platform">
          <option value="">Toutes plateformes</option>
          ${this.PLATFORMS.map(p => `<option value="${p.id}" ${this.state.filters.platform === p.id ? 'selected' : ''}>${this._esc(p.label)}</option>`).join('')}
        </select>
        <select id="ob-f-status">
          <option value="">Tous statuts</option>
          ${Object.entries(this.STATUS_LABELS).map(([k, l]) => `<option value="${k}" ${this.state.filters.status === k ? 'selected' : ''}>${this._esc(l)}</option>`).join('')}
        </select>
        <select id="ob-f-email">
          <option value="">Email : tous</option>
          <option value="yes" ${this.state.filters.has_email === 'yes' ? 'selected' : ''}>Avec email</option>
          <option value="no" ${this.state.filters.has_email === 'no' ? 'selected' : ''}>Sans email</option>
        </select>
        <select id="ob-f-country">
          <option value="">Pays : tous</option>
          <option value="FR" ${this.state.filters.country === 'FR' ? 'selected' : ''}>🇫🇷 France uniquement</option>
          <option value="OTHERS" ${this.state.filters.country === 'OTHERS' ? 'selected' : ''}>🌍 Hors France</option>
        </select>
        <input id="ob-f-score" class="ob-num" type="number" min="0" max="100" placeholder="Score ≥" value="${this.state.filters.min_score || ''}">
      </div>

      <div id="ob-active-filters"></div>

      <div id="ob-table-wrap" class="ob-table-card"></div>
      <div id="ob-pager" class="ob-pager"></div>
    `;

    const applyFromInputs = () => {
      this.state.filters.q        = document.getElementById('ob-f-q').value;
      this.state.filters.platform = document.getElementById('ob-f-platform').value;
      this.state.filters.status   = document.getElementById('ob-f-status').value;
      this.state.filters.has_email= document.getElementById('ob-f-email').value;
      this.state.filters.country  = document.getElementById('ob-f-country').value;
      this.state.filters.min_score= parseInt(document.getElementById('ob-f-score').value, 10) || 0;
      this.state.page = 0;
      this._loadCreators();
    };

    // La recherche libre filtre après une courte pause (debounce)
    const qInput = document.getElementById('ob-f-q');
    let qTimer;
    qInput.addEventListener('input', () => {
      clearTimeout(qTimer);
      qTimer = setTimeout(applyFromInputs, 280);
    });
    // Les selects/score filtrent dès le change
    ['ob-f-platform', 'ob-f-status', 'ob-f-email', 'ob-f-country', 'ob-f-score'].forEach(id => {
      document.getElementById(id).addEventListener('change', applyFromInputs);
    });

    await this._loadCreators();
  },

  _emptyHeroHtml() {
    return `
      <div class="ob-empty-hero">
        <div class="icon">🔭</div>
        <h2>Ton CRM est vierge.</h2>
        <p>Décris ta cible (niche, secteur, mot-clé) et Obelisk balaie les plateformes
           pour repérer les créateurs non monétisés, enrichir leurs emails et te préparer les drafts.</p>
        <button id="ob-empty-cta" class="btn btn-primary" style="padding: 11px 22px; font-size: 14px;">
          Lancer ma première recherche
        </button>
        <div class="ob-platforms-tease">
          ${this.PLATFORMS.map(p => `<span>${this._esc(p.label)}</span>`).join('')}
        </div>
      </div>
    `;
  },

  _renderActiveFilters() {
    const wrap = document.getElementById('ob-active-filters');
    if (!wrap) return;
    const f = this.state.filters;
    const chips = [];
    if (f.job_id && this.state.jobFilterInfo) {
      const ji = this.state.jobFilterInfo;
      const when = ji.created_at ? new Date(ji.created_at).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' }) : '';
      const label = `Recherche : ${ji.niche || '(sans niche)'}${when ? ' · ' + when : ''}`;
      chips.push(['job_id', label, 'is-job']);
    }
    if (f.q)         chips.push(['q', `« ${f.q} »`]);
    if (f.platform)  chips.push(['platform', (this.PLATFORMS.find(p => p.id === f.platform) || {}).label || f.platform]);
    if (f.status)    chips.push(['status', this.STATUS_LABELS[f.status] || f.status]);
    if (f.has_email) chips.push(['has_email', f.has_email === 'yes' ? 'Avec email' : 'Sans email']);
    if (f.country)   chips.push(['country', f.country === 'FR' ? '🇫🇷 France' : f.country === 'OTHERS' ? '🌍 Hors France' : f.country]);
    if (f.min_score) chips.push(['min_score', `Score ≥ ${f.min_score}`]);
    if (chips.length === 0) { wrap.className = ''; wrap.innerHTML = ''; return; }
    wrap.className = 'ob-active-filters';
    wrap.innerHTML = chips.map(([k, l, extra]) =>
      `<span class="chip ${extra || ''}">${this._esc(l)}<button data-ob-rmf="${k}" aria-label="Retirer">×</button></span>`
    ).join('') + `<button class="clear-all" data-ob-clearall>Tout effacer</button>`;
    wrap.querySelectorAll('[data-ob-rmf]').forEach(b => {
      b.onclick = () => {
        const k = b.dataset.obRmf;
        this.state.filters[k] = (k === 'min_score') ? 0 : '';
        if (k === 'job_id') this.state.jobFilterInfo = null;
        this.state.page = 0;
        this._renderCreators();
      };
    });
    const clr = wrap.querySelector('[data-ob-clearall]');
    if (clr) clr.onclick = () => {
      this.state.filters = { platform: '', status: '', min_score: 0, q: '', has_email: '', country: '', job_id: '' };
      this.state.jobFilterInfo = null;
      this.state.page = 0;
      this._renderCreators();
    };
  },

  async _loadCreators() {
    this._renderActiveFilters();
    const wrap = document.getElementById('ob-table-wrap');
    if (!wrap) return;
    wrap.innerHTML = '<div style="padding: 36px; text-align: center; font-size: 13px; color: hsl(var(--text-muted));">Chargement…</div>';
    const offset = this.state.page * this.state.pageSize;
    const res = await this._api('list_creators', {
      ...this.state.filters,
      limit: this.state.pageSize,
      offset,
    });
    if (!res || !res.ok) {
      wrap.innerHTML = `<div style="padding: 24px; color: hsl(var(--danger)); font-size: 13px;">Erreur : ${this._esc(res && res.error || 'inconnu')}</div>`;
      return;
    }
    this.state.rows = res.rows || [];
    this.state.total = res.count || 0;

    if (this.state.rows.length === 0) {
      const ji = this.state.jobFilterInfo;
      const jobActive = this.state.filters.job_id && ji;
      let icon = '🔭';
      let title = 'Aucun créateur ne correspond.';
      let sub   = 'Élargis tes filtres ou lance une nouvelle recherche.';
      if (jobActive) {
        if (ji.status === 'running' || ji.status === 'pending') {
          icon = '⏳';
          title = 'La recherche est encore en cours.';
          sub   = 'Reviens dans une minute, ou consulte la progression dans l\'onglet « Nouvelle recherche ».';
        } else if (ji.status === 'failed') {
          icon = '⚠️';
          title = 'La recherche a échoué.';
          sub   = 'Aucun créateur n\'a été inséré. Ouvre l\'onglet « Nouvelle recherche » pour voir le détail.';
        } else {
          icon = '🪹';
          title = 'Cette recherche n\'a remonté aucun créateur.';
          sub   = 'Soit les plateformes n\'ont rien trouvé, soit tes filtres avancés ont tout écarté.';
        }
      }
      wrap.innerHTML = `
        <div style="padding: 56px 24px; text-align: center;">
          <div style="font-size: 32px; opacity: .5; margin-bottom: 12px;">${icon}</div>
          <div style="font-weight: 600; color: hsl(var(--text)); margin-bottom: 4px; font-size: 15px;">${this._esc(title)}</div>
          <div style="font-size: 13px; color: hsl(var(--text-muted)); max-width: 460px; margin: 0 auto;">${this._esc(sub)}</div>
        </div>`;
    } else {
      // Init de la sélection en mémoire si pas déjà fait
      if (!(this.state.selectedIds instanceof Set)) {
        this.state.selectedIds = new Set();
      }
      wrap.innerHTML = `
        <div id="ob-bulkbar" class="ob-bulkbar" hidden></div>
        <table class="ob-table">
          <thead><tr>
            <th style="width:40px;"><input type="checkbox" id="ob-select-all" title="Tout sélectionner (page)"></th>
            <th>Créateur</th><th>Plateforme</th><th>Abonnés</th><th>Email</th><th>Score</th><th>Ville</th><th>Statut</th>
          </tr></thead>
          <tbody>
            ${this.state.rows.map(p => this._rowHtml(p)).join('')}
          </tbody>
        </table>
      `;
      this._bindRowSelection();
      this._renderBulkbar();
      wrap.querySelectorAll('[data-ob-open]').forEach(tr => {
        tr.onclick = (ev) => {
          if (ev.target.closest('select, button, a, input[type="checkbox"]')) return;
          this.openCreator(tr.dataset.obOpen);
        };
      });
      wrap.querySelectorAll('[data-ob-status]').forEach(sel => {
        sel.onclick = (e) => e.stopPropagation();
        sel.onchange = () => this._quickStatus(sel.dataset.obStatus, sel.value);
      });
    }

    // Pager
    const pager = document.getElementById('ob-pager');
    const lastPage = Math.max(0, Math.ceil(this.state.total / this.state.pageSize) - 1);
    const start = this.state.total === 0 ? 0 : offset + 1;
    const end   = Math.min(offset + this.state.pageSize, this.state.total);
    pager.innerHTML = `
      <div>${start}–${end} sur ${Number(this.state.total).toLocaleString('fr-FR')}</div>
      <div style="display:flex; gap: 8px;">
        <button class="btn btn-ghost" ${this.state.page === 0 ? 'disabled' : ''} data-ob-prev>← Précédent</button>
        <button class="btn btn-ghost" ${this.state.page >= lastPage ? 'disabled' : ''} data-ob-next>Suivant →</button>
      </div>
    `;
    const prev = pager.querySelector('[data-ob-prev]');
    const next = pager.querySelector('[data-ob-next]');
    if (prev) prev.onclick = () => { this.state.page = Math.max(0, this.state.page - 1); this._loadCreators(); };
    if (next) next.onclick = () => { this.state.page = Math.min(lastPage, this.state.page + 1); this._loadCreators(); };
  },

  _rowHtml(p) {
    const platform = this._inferPlatform(p);
    const emails = Array.isArray(p.emails) ? p.emails : [];
    const score = Math.max(0, Math.min(100, p.score || 0));
    const scoreVar = score >= 70 ? '--success' : score >= 40 ? '--warning' : '--text-muted';
    const status = p.status || 'new';
    const sel = (this.state.selectedIds instanceof Set) && this.state.selectedIds.has(p.id);
    return `
      <tr class="is-clickable ${sel ? 'is-selected' : ''}" data-ob-open="${this._esc(p.id)}">
        <td style="width:40px;">
          <input type="checkbox" data-ob-select="${this._esc(p.id)}" ${sel ? 'checked' : ''}>
        </td>
        <td>
          <div style="font-weight: 600; color: hsl(var(--text));">${this._esc(p.name || p.handle || p.legal_name || '(sans nom)')}</div>
          ${p.handle ? `<div style="font-size: 11.5px; color: hsl(var(--text-muted)); margin-top: 2px;">@${this._esc(p.handle)}</div>` : ''}
        </td>
        <td>${platform ? `<span class="ob-pill">${this._esc(platform)}</span>` : '<span style="color: hsl(var(--text-muted));">—</span>'}</td>
        <td style="color: hsl(var(--text)); font-variant-numeric: tabular-nums; white-space: nowrap;">${this._fmtSubs(p.subscribers, p.subs_hidden)}</td>
        <td>${emails[0] ? `<a href="mailto:${this._esc(emails[0])}" style="color: hsl(var(--info));" onclick="event.stopPropagation()">${this._esc(emails[0])}</a>${emails.length > 1 ? ` <span style="color: hsl(var(--text-muted)); font-size: 11.5px;">+${emails.length - 1}</span>` : ''}` : '<span style="color: hsl(var(--text-muted));">—</span>'}</td>
        <td>
          <span class="ob-score" style="color: hsl(var(${scoreVar}));">
            ${score}
            <span class="ob-score-bar" style="--w: ${score}%;"></span>
          </span>
        </td>
        <td style="color: hsl(var(--text-muted));">${this._esc(p.city || '—')}</td>
        <td>
          <select class="ob-status-select" data-ob-status="${this._esc(p.id)}">
            ${Object.entries(this.STATUS_LABELS).map(([k, l]) => `<option value="${k}" ${status === k ? 'selected' : ''}>${this._esc(l)}</option>`).join('')}
          </select>
        </td>
      </tr>
    `;
  },

  // ---- Sélection multiple + suppression en masse ----
  _bindRowSelection() {
    const wrap = document.getElementById('ob-table-wrap');
    if (!wrap) return;
    const all = wrap.querySelector('#ob-select-all');
    if (all) {
      // Si tous les rows de la page sont déjà sélectionnés, coche-le
      const pageIds = this.state.rows.map(r => r.id).filter(Boolean);
      const allSelected = pageIds.length > 0 && pageIds.every(
        id => this.state.selectedIds.has(id));
      all.checked = allSelected;
      all.onchange = (e) => {
        e.stopPropagation();
        const checked = all.checked;
        pageIds.forEach(id => {
          if (checked) this.state.selectedIds.add(id);
          else this.state.selectedIds.delete(id);
        });
        // Re-render rapide pour mettre à jour les checkboxes + bulkbar
        wrap.querySelectorAll('[data-ob-select]').forEach(cb => {
          cb.checked = this.state.selectedIds.has(cb.dataset.obSelect);
          cb.closest('tr').classList.toggle('is-selected', cb.checked);
        });
        this._renderBulkbar();
      };
    }
    wrap.querySelectorAll('[data-ob-select]').forEach(cb => {
      cb.onclick = (e) => e.stopPropagation();
      cb.onchange = () => {
        const id = cb.dataset.obSelect;
        if (cb.checked) this.state.selectedIds.add(id);
        else this.state.selectedIds.delete(id);
        cb.closest('tr').classList.toggle('is-selected', cb.checked);
        if (all) {
          const pageIds = this.state.rows.map(r => r.id).filter(Boolean);
          all.checked = pageIds.every(i => this.state.selectedIds.has(i));
        }
        this._renderBulkbar();
      };
    });
  },

  _renderBulkbar() {
    const bar = document.getElementById('ob-bulkbar');
    if (!bar) return;
    const n = this.state.selectedIds ? this.state.selectedIds.size : 0;
    const total = this.state.total || 0;
    const hasFilters = Object.values(this.state.filters || {}).some(
      v => v !== '' && v !== 0);
    bar.hidden = false;
    bar.innerHTML = `
      <div class="ob-bulkbar-inner">
        <span class="ob-bulkbar-info">
          ${n > 0
            ? `<strong>${n}</strong> sélectionné${n > 1 ? 's' : ''}`
            : `<strong>${total}</strong> créateur${total > 1 ? 's' : ''} au total`}
        </span>
        <span style="flex:1;"></span>
        ${n > 0 ? `
          <button class="btn btn-secondary ob-bulkbar-btn" data-ob-bulk="clear">
            Tout désélectionner
          </button>
          <button class="btn ob-bulkbar-btn ob-bulkbar-danger" data-ob-bulk="delete-selected">
            🗑 Supprimer la sélection (${n})
          </button>
        ` : `
          ${hasFilters ? `
            <button class="btn btn-secondary ob-bulkbar-btn" data-ob-bulk="delete-filtered">
              Supprimer les résultats filtrés
            </button>` : ''}
          <button class="btn ob-bulkbar-btn ob-bulkbar-danger-soft" data-ob-bulk="delete-all">
            ⚠ Tout supprimer
          </button>
        `}
      </div>
    `;
    bar.querySelectorAll('[data-ob-bulk]').forEach(btn => {
      btn.onclick = () => this._handleBulkAction(btn.dataset.obBulk);
    });
  },

  async _handleBulkAction(action) {
    if (action === 'clear') {
      this.state.selectedIds = new Set();
      this._loadCreators();
      return;
    }
    if (action === 'delete-selected') {
      const ids = Array.from(this.state.selectedIds);
      if (ids.length === 0) return;
      if (!confirm(`Supprimer ${ids.length} créateur${ids.length > 1 ? 's' : ''} sélectionné${ids.length > 1 ? 's' : ''} ?\n\nCette action est définitive.`)) {
        return;
      }
      const r = await this._api('delete_creators_bulk', { ids });
      if (r && r.ok) {
        this.state.selectedIds = new Set();
        await this._loadStats();
        await this._loadCreators();
      } else {
        alert('Suppression échouée : ' + ((r && r.error) || 'erreur'));
      }
      return;
    }
    if (action === 'delete-filtered') {
      const f = this.state.filters || {};
      if (!confirm(`Supprimer TOUS les créateurs qui matchent les filtres actuels ?\n\nCette action est définitive.`)) {
        return;
      }
      const r = await this._api('delete_creators_filtered', f);
      if (r && r.ok) {
        alert(`${r.deleted || 0} créateur(s) supprimé(s).`);
        this.state.selectedIds = new Set();
        await this._loadStats();
        await this._loadCreators();
      } else {
        alert('Suppression échouée : ' + ((r && r.error) || 'erreur'));
      }
      return;
    }
    if (action === 'delete-all') {
      // Double confirmation pour cette action destructive
      const first = confirm('⚠ TOUT SUPPRIMER : tous tes créateurs Obelisk vont être effacés définitivement.\n\nContinuer ?');
      if (!first) return;
      const typed = prompt('Pour confirmer, tape « SUPPRIMER TOUT » exactement :');
      if ((typed || '').trim() !== 'SUPPRIMER TOUT') {
        alert('Confirmation incorrecte — rien supprimé.');
        return;
      }
      const r = await this._api('delete_all_creators', { confirm: 'DELETE_ALL' });
      if (r && r.ok) {
        alert(`${r.deleted || 0} créateur(s) supprimé(s).`);
        this.state.selectedIds = new Set();
        await this._loadStats();
        await this._loadCreators();
      } else {
        alert('Suppression échouée : ' + ((r && r.error) || 'erreur'));
      }
      return;
    }
  },

  _fmtSubs(n, hidden) {
    if (hidden) return '<span style="color: hsl(var(--text-muted));" title="Non public">?</span>';
    if (n === null || n === undefined || n === '') return '<span style="color: hsl(var(--text-muted));">—</span>';
    const v = Number(n);
    if (!Number.isFinite(v) || v < 0) return '<span style="color: hsl(var(--text-muted));">—</span>';
    if (v >= 1_000_000) return (v / 1_000_000).toFixed(v >= 10_000_000 ? 0 : 1).replace('.', ',') + ' M';
    if (v >= 1_000)     return (v / 1_000).toFixed(v >= 10_000 ? 0 : 1).replace('.', ',') + ' k';
    return String(v);
  },

  _inferPlatform(p) {
    const url = (p.platform_url || '').toLowerCase();
    if (url.includes('youtube.com'))   return 'YouTube';
    if (url.includes('twitch.tv'))     return 'Twitch';
    if (url.includes('reddit.com'))    return 'Reddit';
    if (url.includes('bsky.app'))      return 'Bluesky';
    if (url.includes('mastodon'))      return 'Mastodon';
    if (url.includes('podcasts.apple'))return 'Podcasts';
    if (url.includes('dailymotion'))   return 'Dailymotion';
    if (url.includes('kick.com'))      return 'Kick';
    if (url.includes('github.com'))    return 'GitHub';
    const srcs = Array.isArray(p.sources) ? p.sources : [];
    if (srcs.length) return srcs[0].name || '';
    return '';
  },

  async _quickStatus(id, status) {
    await this._api('update_creator', { id, fields: { status, last_contact_at: status === 'contacted' ? new Date().toISOString() : null } });
    await this._loadStats();
  },

  // -------------------------------------------------------------------
  // Drawer détails créateur
  // -------------------------------------------------------------------
  async openCreator(id) {
    const res = await this._api('get_creator', { id });
    if (!res || !res.ok) { alert('Impossible de charger ce créateur.'); return; }
    this.state.selected = res.prospect;
    this._renderDrawer();
  },

  closeDrawer() {
    const d = document.getElementById('ob-drawer');
    const b = document.getElementById('ob-drawer-backdrop');
    if (d) d.classList.remove('is-open');
    if (b) b.classList.remove('is-open');
    setTimeout(() => { if (d) d.remove(); if (b) b.remove(); }, 220);
    this.state.selected = null;
  },

  _renderDrawer() {
    const p = this.state.selected;
    if (!p) return;
    const old = document.getElementById('ob-drawer');
    const oldBd = document.getElementById('ob-drawer-backdrop');
    if (old) old.remove();
    if (oldBd) oldBd.remove();

    const bd = document.createElement('div');
    bd.id = 'ob-drawer-backdrop';
    bd.className = 'ob-drawer-backdrop';
    bd.onclick = () => this.closeDrawer();

    const d = document.createElement('div');
    d.id = 'ob-drawer';
    d.className = 'ob-drawer';
    const emails = Array.isArray(p.emails) ? p.emails : [];
    const phones = Array.isArray(p.phones) ? p.phones : [];
    const reasons = Array.isArray(p.monetization_reasons) ? p.monetization_reasons : [];
    const tags = Array.isArray(p.tags) ? p.tags : [];
    const sources = Array.isArray(p.sources) ? p.sources : [];

    d.innerHTML = `
      <div class="flex items-start justify-between mb-4">
        <div>
          <div class="hero-kicker mb-1">${this._esc(this._inferPlatform(p))}</div>
          <h2 class="text-2xl font-bold leading-tight">${this._esc(p.name || p.handle || '(sans nom)')}</h2>
          ${p.handle ? `<div class="text-sm text-text-muted">@${this._esc(p.handle)}</div>` : ''}
        </div>
        <button onclick="Obelisk.closeDrawer()" class="text-text-muted hover:text-text text-2xl leading-none">×</button>
      </div>

      <div class="grid grid-cols-2 gap-3 mb-5">
        <div class="ob-stat"><div class="label">Score</div><div class="value">${p.score || 0}</div></div>
        <div class="ob-stat"><div class="label">Abonnés</div><div class="value">${p.subscribers ? Number(p.subscribers).toLocaleString('fr-FR') : '—'}</div></div>
      </div>

      ${p.platform_url ? `<div class="mb-4">
        <div class="text-[10px] uppercase tracking-widest font-bold text-text-muted mb-1">Profil</div>
        <a href="${this._esc(p.platform_url)}" target="_blank" rel="noopener" class="text-info hover:underline text-sm break-all">${this._esc(p.platform_url)}</a>
      </div>` : ''}

      ${emails.length ? `<div class="mb-4">
        <div class="text-[10px] uppercase tracking-widest font-bold text-text-muted mb-1">Emails</div>
        ${emails.map(e => `<a href="mailto:${this._esc(e)}" class="block text-info hover:underline text-sm">${this._esc(e)}</a>`).join('')}
      </div>` : ''}

      ${phones.length ? `<div class="mb-4">
        <div class="text-[10px] uppercase tracking-widest font-bold text-text-muted mb-1">Téléphones</div>
        ${phones.map(t => `<div class="text-sm">${this._esc(t)}</div>`).join('')}
      </div>` : ''}

      ${p.website ? `<div class="mb-4">
        <div class="text-[10px] uppercase tracking-widest font-bold text-text-muted mb-1">Site</div>
        <a href="${this._esc(p.website)}" target="_blank" rel="noopener" class="text-info hover:underline text-sm break-all">${this._esc(p.website)}</a>
      </div>` : ''}

      ${(p.city || p.country) ? `<div class="mb-4">
        <div class="text-[10px] uppercase tracking-widest font-bold text-text-muted mb-1">Localisation</div>
        <div class="text-sm">${this._esc([p.city, p.postal_code, p.country].filter(Boolean).join(' · '))}</div>
      </div>` : ''}

      ${p.description ? `<div class="mb-4">
        <div class="text-[10px] uppercase tracking-widest font-bold text-text-muted mb-1">Description</div>
        <div class="text-sm leading-relaxed text-text-muted">${this._esc(p.description).slice(0, 600)}${p.description.length > 600 ? '…' : ''}</div>
      </div>` : ''}

      <div class="mb-4">
        <div class="text-[10px] uppercase tracking-widest font-bold text-text-muted mb-1">Monétisation</div>
        <div class="text-sm">${p.monetized ? `<span class="text-warning">Déjà monétisé</span>` : `<span class="text-success">Pas (encore) monétisé</span>`}</div>
        ${reasons.length ? `<div class="text-[11px] text-text-muted mt-1">${this._esc(reasons.join(' · '))}</div>` : ''}
      </div>

      ${sources.length ? `<div class="mb-4">
        <div class="text-[10px] uppercase tracking-widest font-bold text-text-muted mb-1">Sources</div>
        ${sources.map(s => `<div class="text-[11px] text-text-muted">${this._esc(s.name || '')} · ${this._esc(s.source_id || '')}</div>`).join('')}
      </div>` : ''}

      <div class="border-t border-border pt-4 mt-5">
        <div class="text-[10px] uppercase tracking-widest font-bold text-text-muted mb-2">Statut CRM</div>
        <select id="ob-d-status" class="ob-status-select w-full">
          ${Object.entries(this.STATUS_LABELS).map(([k, l]) => `<option value="${k}" ${(p.status || 'new') === k ? 'selected' : ''}>${this._esc(l)}</option>`).join('')}
        </select>

        <div class="text-[10px] uppercase tracking-widest font-bold text-text-muted mb-1 mt-4">Notes</div>
        <textarea id="ob-d-notes" rows="4" style="width:100%; padding:9px 12px; border-radius:7px; background: hsl(var(--bg)); color: hsl(var(--text)); border: 1px solid hsl(var(--border)); font-size: 13px; font-family: inherit;" placeholder="Notes internes (non envoyées au prospect)…">${this._esc(p.notes || '')}</textarea>

        <div class="flex gap-2 mt-4">
          ${emails[0] ? `<button onclick="Obelisk.compose('${this._esc(p.id)}')" class="btn btn-primary flex-1">Composer un mail</button>` : ''}
          <button id="ob-d-save" class="btn btn-secondary ${emails[0] ? '' : 'flex-1'}">Enregistrer</button>
        </div>

        <div class="mt-6 pt-4 border-t border-border">
          <button id="ob-d-delete" class="text-danger text-[11px] hover:underline">Supprimer ce créateur</button>
        </div>
      </div>
    `;

    document.body.appendChild(bd);
    document.body.appendChild(d);
    requestAnimationFrame(() => {
      bd.classList.add('is-open');
      d.classList.add('is-open');
    });

    document.getElementById('ob-d-save').onclick = async () => {
      const fields = {
        status: document.getElementById('ob-d-status').value,
        notes: document.getElementById('ob-d-notes').value,
      };
      const res = await this._api('update_creator', { id: p.id, fields });
      if (!res || !res.ok) { alert('Échec : ' + (res && res.error || 'inconnu')); return; }
      this._toast('Enregistré.');
      await this._loadCreators();
      await this._loadStats();
      this.closeDrawer();
    };
    document.getElementById('ob-d-delete').onclick = async () => {
      if (!confirm('Supprimer définitivement ce créateur ?')) return;
      const res = await this._api('delete_creator', { id: p.id });
      if (!res || !res.ok) { alert('Échec : ' + (res && res.error || 'inconnu')); return; }
      this._toast('Supprimé.');
      await this._loadCreators();
      await this._loadStats();
      this.closeDrawer();
    };
  },

  async compose(id) {
    const res = await this._api('get_creator', { id });
    if (!res || !res.ok) return;
    const p = res.prospect;
    const emails = Array.isArray(p.emails) ? p.emails : [];
    if (!emails[0]) { alert('Pas d\'email pour ce créateur.'); return; }
    // Marque automatiquement comme contacté
    await this._api('update_creator', { id, fields: { status: 'contacted', last_contact_at: new Date().toISOString() } });
    // Utilise le composer Mails si dispo, sinon mailto:
    if (typeof Mails !== 'undefined' && Mails._openComposer) {
      App.show('mails');
      setTimeout(() => Mails._openComposer({ to: emails[0], context: { obelisk_prospect_id: id, name: p.name } }), 200);
    } else if (App.api && App.api.compose_mail) {
      App.api.compose_mail({ to: emails[0] });
    } else {
      window.location.href = `mailto:${emails[0]}`;
    }
  },

  // -------------------------------------------------------------------
  // Onglet Recherche : lance + poll un job
  // -------------------------------------------------------------------
  async _renderSearch() {
    const c = document.getElementById('ob-content');
    // Charge la config user pour pré-remplir la liste de plateformes par défaut
    if (!this.state.config) {
      const r = await this._api('get_config');
      if (r && r.ok) this.state.config = r.config;
    }
    const cfg = this.state.config || {};
    // Défauts forcés à chaque ouverture du formulaire (Jordan veut toujours
    // partir d'une feuille blanche : YouTube seul + Tous monétisés/non).
    const defaultPlatforms = new Set(['youtube']);
    const monetMode = 'all';
    c.innerHTML = `
      <div class="grid grid-cols-1 lg:grid-cols-[1fr_360px] gap-5">
        <div class="bg-card border border-border rounded-xl p-6">
          <h3 class="text-lg font-bold mb-1">Nouvelle recherche</h3>
          <p class="text-sm text-text-muted mb-5">Décris ta cible. Obelisk balaie les plateformes activées (12 dispos, dont LinkedIn / Instagram / TikTok via PhantomBuster), enrichit les profils et stocke tout dans ton CRM.</p>

          <label class="block mb-4">
            <div class="text-[11px] font-bold uppercase tracking-widest text-text-muted mb-2">Niche(s) — séparées par virgules pour en lancer plusieurs</div>
            <input id="ob-s-niche" placeholder="ex : entrepreneur, coaching, growth, formation" value="${this._esc(cfg.niche || '')}" style="width:100%; padding:10px 14px; border-radius:8px; background: hsl(var(--bg)); color: hsl(var(--text)); border: 1px solid hsl(var(--border)); font-size: 14px;">
            <div class="text-[11px] text-text-muted mt-1">Une virgule = une recherche supplémentaire. Tout est fusionné dans un seul job, avec dédup automatique.</div>
          </label>

          <div class="block mb-4">
            <div class="text-[11px] font-bold uppercase tracking-widest text-text-muted mb-2">Plateformes</div>
            <div class="ob-platform-grid">
              ${this.PLATFORMS.map(p => `
                <label class="ob-platform-chip ${defaultPlatforms.has(p.id) ? 'is-on' : ''}">
                  <input type="checkbox" data-ob-plat="${p.id}" ${defaultPlatforms.has(p.id) ? 'checked' : ''} style="margin: 0;">
                  ${this._esc(p.label)}
                </label>
              `).join('')}
            </div>
          </div>

          <div class="block mb-4">
            <div class="text-[11px] font-bold uppercase tracking-widest text-text-muted mb-2">Cible — monétisation</div>
            <div class="ob-radio-grid">
              <label class="ob-radio-chip">
                <input type="radio" name="ob-monet" value="all" ${monetMode === 'all' ? 'checked' : ''}>
                Tous
              </label>
              <label class="ob-radio-chip">
                <input type="radio" name="ob-monet" value="unmonetized" ${monetMode === 'unmonetized' ? 'checked' : ''}>
                Pas encore monétisés
              </label>
              <label class="ob-radio-chip">
                <input type="radio" name="ob-monet" value="monetized" ${monetMode === 'monetized' ? 'checked' : ''}>
                Déjà monétisés (gros noms, vendeurs)
              </label>
            </div>
            <div class="text-[11px] text-text-muted mt-2">
              « Pas encore monétisés » = créateurs vierges à qui tu proposes d'aider à monétiser.<br/>
              « Déjà monétisés » = coachs, formateurs, growth, influenceurs établis à qui tu proposes du partenariat.
            </div>
          </div>

          <div class="grid grid-cols-2 gap-3 mb-4">
            <label class="block">
              <div class="text-[11px] font-bold uppercase tracking-widest text-text-muted mb-2">Audience minimum</div>
              <input id="ob-s-min-subs" type="number" min="0" placeholder="0 = pas de plancher" value="${cfg.min_subscribers || ''}" style="width:100%; padding:9px 12px; border-radius:7px; background: hsl(var(--bg)); color: hsl(var(--text)); border: 1px solid hsl(var(--border)); font-size: 13px;">
            </label>
            <label class="block">
              <div class="text-[11px] font-bold uppercase tracking-widest text-text-muted mb-2">Audience maximum</div>
              <input id="ob-s-max-subs" type="number" min="0" placeholder="0 = pas de plafond" value="${cfg.max_subscribers || ''}" style="width:100%; padding:9px 12px; border-radius:7px; background: hsl(var(--bg)); color: hsl(var(--text)); border: 1px solid hsl(var(--border)); font-size: 13px;">
            </label>
          </div>

          <div class="grid grid-cols-2 gap-3 mb-4">
            <label class="block">
              <div class="text-[11px] font-bold uppercase tracking-widest text-text-muted mb-2">Pays (code ISO)</div>
              <input id="ob-s-country" type="text" placeholder="ex : FR, US, EN" value="${this._esc(cfg.country || '')}" style="width:100%; padding:9px 12px; border-radius:7px; background: hsl(var(--bg)); color: hsl(var(--text)); border: 1px solid hsl(var(--border)); font-size: 13px;">
            </label>
            <label class="block">
              <div class="text-[11px] font-bold uppercase tracking-widest text-text-muted mb-2">Langue (code ISO)</div>
              <input id="ob-s-language" type="text" placeholder="ex : fr, en, es" value="${this._esc(cfg.language || '')}" style="width:100%; padding:9px 12px; border-radius:7px; background: hsl(var(--bg)); color: hsl(var(--text)); border: 1px solid hsl(var(--border)); font-size: 13px;">
            </label>
          </div>

          <div class="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-4">
            <label class="ob-toggle-row">
              <input id="ob-s-with-email" type="checkbox" ${cfg.only_with_email ? 'checked' : ''}>
              <div>
                <div class="font-semibold text-sm">Uniquement ceux avec un email</div>
                <div class="text-[11px] text-text-muted">Si décoché, tu auras aussi les profils sans email (à enrichir à la main après).</div>
              </div>
            </label>
            <label class="ob-toggle-row">
              <input id="ob-s-uncontacted" type="checkbox" ${cfg.only_uncontacted !== false ? 'checked' : ''}>
              <div>
                <div class="font-semibold text-sm">Uniquement les pas encore contactés</div>
                <div class="text-[11px] text-text-muted">Évite de retomber sur des prospects que tu as déjà sollicités.</div>
              </div>
            </label>
          </div>

          <label class="block mb-5">
            <div class="text-[11px] font-bold uppercase tracking-widest text-text-muted mb-2">Max par plateforme</div>
            <input id="ob-s-max" type="number" min="5" max="500" value="${cfg.max_per_platform || 30}" style="width: 120px; padding:9px 12px; border-radius:7px; background: hsl(var(--bg)); color: hsl(var(--text)); border: 1px solid hsl(var(--border)); font-size: 13px;">
          </label>

          <button id="ob-s-launch" class="btn btn-primary w-full" style="padding: 12px;">Lancer la recherche</button>

          <div id="ob-s-progress" class="mt-5"></div>
        </div>

        <div class="bg-card border border-border rounded-xl p-5">
          <h4 class="text-sm font-bold mb-3">Recherches récentes</h4>
          <div id="ob-s-jobs" class="text-[12px] text-text-muted">Chargement…</div>
        </div>
      </div>
    `;
    // Chip toggle visual
    c.querySelectorAll('[data-ob-plat]').forEach(cb => {
      cb.addEventListener('change', () => {
        cb.closest('.ob-platform-chip').classList.toggle('is-on', cb.checked);
      });
    });
    document.getElementById('ob-s-launch').onclick = () => this._launchSearch();
    this._loadRecentJobs();
  },

  async _loadRecentJobs() {
    const wrap = document.getElementById('ob-s-jobs');
    if (!wrap) return;
    const res = await this._api('list_jobs', { limit: 8 });
    const jobs = (res && res.jobs) || [];
    if (jobs.length === 0) { wrap.innerHTML = '<div class="text-[12px] text-text-muted">Aucune recherche pour l\'instant.</div>'; return; }
    this._lastJobs = jobs;
    wrap.innerHTML = jobs.map(j => {
      const found = (j.stats && j.stats.found) || 0;
      const statusColor = j.status === 'done' ? 'text-success' : j.status === 'failed' ? 'text-danger' : j.status === 'running' ? 'text-warning' : 'text-text-muted';
      const when = j.created_at ? new Date(j.created_at).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' }) : '';
      return `<div class="ob-job-row" data-ob-job="${this._esc(j.id)}" title="Voir les créateurs trouvés par cette recherche">
        <div class="ob-job-row-top">
          <div class="ob-job-row-niche">${this._esc(j.niche)}</div>
          <span class="ob-job-row-arrow">›</span>
        </div>
        <div class="ob-job-row-meta">
          <span class="${statusColor}">${this._esc(j.status)}${found ? ` · ${found} trouvés` : ''}</span>
          <span>${this._esc(when)}</span>
        </div>
      </div>`;
    }).join('');
    wrap.querySelectorAll('[data-ob-job]').forEach(row => {
      row.onclick = () => {
        const jid = row.dataset.obJob;
        const job = (this._lastJobs || []).find(x => x.id === jid);
        this._openJobResults(job || { id: jid });
      };
    });
  },

  _openJobResults(job) {
    if (!job || !job.id) return;
    this.state.filters.job_id = job.id;
    this.state.jobFilterInfo = {
      id:         job.id,
      niche:      job.niche || '',
      created_at: job.created_at || '',
      status:     job.status || '',
      found:      (job.stats && job.stats.found) || 0,
    };
    this.state.page = 0;
    this.switchTab('creators');
  },

  async _launchSearch() {
    const niche = document.getElementById('ob-s-niche').value.trim();
    const max   = parseInt(document.getElementById('ob-s-max').value, 10) || 30;
    const platforms = [];
    document.querySelectorAll('[data-ob-plat]:checked').forEach(cb => platforms.push(cb.dataset.obPlat));
    if (!niche)             { alert('Renseigne une niche.'); return; }
    if (!platforms.length)  { alert('Coche au moins une plateforme.'); return; }

    // Filtres avancés
    const monetEl = document.querySelector('input[name="ob-monet"]:checked');
    const monetMode = (monetEl && monetEl.value) || 'all';   // all | unmonetized | monetized
    const minSubs = parseInt(document.getElementById('ob-s-min-subs').value, 10) || 0;
    const maxSubs = parseInt(document.getElementById('ob-s-max-subs').value, 10) || 0;
    const country = document.getElementById('ob-s-country').value.trim();
    const language = document.getElementById('ob-s-language').value.trim();
    const onlyWithEmail = document.getElementById('ob-s-with-email').checked;
    const onlyUncontacted = document.getElementById('ob-s-uncontacted').checked;

    const filters = {
      monetized_mode:  monetMode,
      min_subscribers: minSubs,
      max_subscribers: maxSubs,
      country,
      language,
      only_with_email:  onlyWithEmail,
      only_uncontacted: onlyUncontacted,
    };

    const btn = document.getElementById('ob-s-launch');
    btn.disabled = true; btn.textContent = 'Démarrage…';
    const res = await this._api('start_search', {
      niche, platforms, max_per_platform: max, filters,
    });
    btn.disabled = false; btn.textContent = 'Lancer la recherche';
    if (!res || !res.ok) { alert('Échec : ' + (res && res.error || 'inconnu')); return; }
    this.state.jobId = res.job_id;
    this._pollJob();
  },

  _pollJob() {
    if (this.state.jobPoll) clearInterval(this.state.jobPoll);
    const wrap = document.getElementById('ob-s-progress');
    if (wrap) wrap.innerHTML = `<div class="text-[11px] uppercase font-bold tracking-widest text-text-muted mb-2">En cours…</div><pre class="ob-progress" id="ob-progress-pre">(démarrage)</pre>`;

    const tick = async () => {
      const r = await this._api('get_job', { job_id: this.state.jobId });
      if (!r || !r.ok) return;
      const job = r.job;
      const pre = document.getElementById('ob-progress-pre');
      if (pre) {
        const lines = Array.isArray(job.progress) ? job.progress : [];
        pre.textContent = lines.join('\n') || '(en attente…)';
        pre.scrollTop = pre.scrollHeight;
      }
      if (job.status === 'done' || job.status === 'failed') {
        clearInterval(this.state.jobPoll);
        this.state.jobPoll = null;
        this._loadStats();
        this._loadRecentJobs();
        const wrap2 = document.getElementById('ob-s-progress');
        if (wrap2) {
          const stats = job.stats || {};
          wrap2.insertAdjacentHTML('beforeend', `
            <div class="mt-3 p-3 rounded-lg ${job.status === 'done' ? 'bg-success/10 text-success border border-success/30' : 'bg-danger/10 text-danger border border-danger/30'}">
              ${job.status === 'done'
                ? `✓ Recherche terminée — ${stats.found || 0} trouvés, ${stats.enriched || 0} enrichis, ${stats.drafts || 0} drafts.`
                : `✗ Échec : ${this._esc(job.error || 'erreur inconnue')}`}
            </div>
          `);
        }
      }
    };
    tick();
    this.state.jobPoll = setInterval(tick, 2500);
  },

  // -------------------------------------------------------------------
  // Onglet Réglages : clés API, IA, catalogue d'offres
  // -------------------------------------------------------------------
  async _renderSettings() {
    const c = document.getElementById('ob-content');
    const r = await this._api('get_config');
    const cfg = (r && r.ok && r.config) || {};
    this.state.config = cfg;
    c.innerHTML = `
      <div class="bg-card border border-border rounded-xl p-6 max-w-3xl">
        <h3 class="text-lg font-bold mb-1">Réglages Obelisk</h3>
        <p class="text-sm text-text-muted mb-6">Clés API par plateforme, préférences IA, catalogue d'offres injecté dans les mails générés.</p>

        <div class="space-y-4">
          ${this._settingField('niche',              'Niche par défaut',        cfg.niche || '',         'text')}
          ${this._settingField('youtube_api_key',    'YouTube Data API v3 — clé', cfg.youtube_api_key || '', 'password')}
          ${this._settingField('twitch_client_id',   'Twitch — Client ID',      cfg.twitch_client_id || '', 'text')}
          ${this._settingField('twitch_client_secret','Twitch — Client Secret', cfg.twitch_client_secret || '', 'password')}
          ${this._settingField('github_token',       'GitHub — Personal Token (optionnel)', cfg.github_token || '', 'password')}
          ${this._settingField('ai_provider',        'IA — fournisseur',        cfg.ai_provider || 'google', 'text')}
          ${this._settingField('ai_model',           'IA — modèle',             cfg.ai_model || 'gemini-2.5-flash', 'text')}
          ${this._settingField('product_override',   'Forcer un produit pour cette session (laisser vide pour laisser l\'IA choisir)', cfg.product_override || '', 'text')}
          ${this._settingTextarea('catalog',         'Catalogue d\'offres (multi-lignes — injecté dans le contexte IA)', cfg.catalog || '')}
        </div>

        <div class="mt-6 pt-4 border-t border-border flex justify-end">
          <button id="ob-cfg-save" class="btn btn-primary">Enregistrer les réglages</button>
        </div>
      </div>
    `;
    document.getElementById('ob-cfg-save').onclick = () => this._saveSettings();
  },

  _settingField(key, label, value, type = 'text') {
    return `<label class="block">
      <div class="text-[11px] font-bold uppercase tracking-widest text-text-muted mb-1.5">${this._esc(label)}</div>
      <input data-ob-cfg="${this._esc(key)}" type="${type}" value="${this._esc(value)}" style="width:100%; padding:9px 12px; border-radius:7px; background: hsl(var(--bg)); color: hsl(var(--text)); border: 1px solid hsl(var(--border)); font-size: 13px;">
    </label>`;
  },
  _settingTextarea(key, label, value) {
    return `<label class="block">
      <div class="text-[11px] font-bold uppercase tracking-widest text-text-muted mb-1.5">${this._esc(label)}</div>
      <textarea data-ob-cfg="${this._esc(key)}" rows="6" style="width:100%; padding:9px 12px; border-radius:7px; background: hsl(var(--bg)); color: hsl(var(--text)); border: 1px solid hsl(var(--border)); font-size: 13px; font-family: inherit;">${this._esc(value)}</textarea>
    </label>`;
  },

  async _saveSettings() {
    const cfg = { ...(this.state.config || {}) };
    document.querySelectorAll('[data-ob-cfg]').forEach(el => {
      cfg[el.dataset.obCfg] = el.value;
    });
    const btn = document.getElementById('ob-cfg-save');
    btn.disabled = true; btn.textContent = 'Enregistrement…';
    const res = await this._api('save_config', { config: cfg });
    btn.disabled = false; btn.textContent = 'Enregistrer les réglages';
    if (!res || !res.ok) { alert('Échec : ' + (res && res.error || 'inconnu')); return; }
    this._toast('Réglages enregistrés.');
    this.state.config = cfg;
  },

  // -------------------------------------------------------------------
  // Utils
  // -------------------------------------------------------------------
  _esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  },
  _toast(msg) {
    let el = document.getElementById('ob-toast');
    if (!el) {
      el = document.createElement('div');
      el.id = 'ob-toast';
      el.style.cssText = 'position:fixed;bottom:20px;right:20px;background:hsl(var(--accent));color:white;padding:10px 16px;border-radius:8px;font-size:13px;font-weight:600;box-shadow:0 6px 24px rgba(0,0,0,.18);z-index:9999;opacity:0;transition:opacity 180ms;';
      document.body.appendChild(el);
    }
    el.textContent = msg;
    requestAnimationFrame(() => { el.style.opacity = '1'; });
    clearTimeout(this._toastTimer);
    this._toastTimer = setTimeout(() => { el.style.opacity = '0'; }, 2500);
  },
};

window.Obelisk = Obelisk;
