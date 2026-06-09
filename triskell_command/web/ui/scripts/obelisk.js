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
    tab: 'search',
    filters: { platform: '', status: '', q: '', has_email: '', country: '', job_id: '', audience: '' },
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
    searchAudience: null,   // 'creator' | 'pro' (lazy-init depuis localStorage)
  },

  _AUDIENCE_KEY: 'obelisk-search-audience',
  _LIST_AUDIENCE_KEY: 'obelisk-list-audience',
  _LS_SEARCH_DRAFT: 'obelisk:search-draft',
  _LS_LIST_FILTERS: 'obelisk:list-filters',

  _saveSearchDraft() {
    try {
      const ids = ['ob-s-niche','ob-s-osm-area','ob-s-min-subs','ob-s-max-subs','ob-s-max'];
      const draft = {};
      ids.forEach(id => { const el = document.getElementById(id); if (el) draft[id] = el.value; });
      const wEmail = document.getElementById('ob-s-with-email');
      const uncontacted = document.getElementById('ob-s-uncontacted');
      if (wEmail) draft['ob-s-with-email'] = !!wEmail.checked;
      if (uncontacted) draft['ob-s-uncontacted'] = !!uncontacted.checked;
      const monet = document.querySelector('input[name="ob-monet"]:checked');
      if (monet) draft['ob-monet'] = monet.value;
      const plats = [];
      document.querySelectorAll('[data-ob-plat]:checked').forEach(cb => plats.push(cb.dataset.obPlat));
      draft['plats'] = plats;
      draft['_aud'] = this._getSearchAudience();
      localStorage.setItem(this._LS_SEARCH_DRAFT, JSON.stringify(draft));
    } catch (e) {}
  },

  _applySearchDraft() {
    let draft = null;
    try { draft = JSON.parse(localStorage.getItem(this._LS_SEARCH_DRAFT) || 'null'); }
    catch (e) {}
    if (!draft) return;
    // Brouillon d'une autre audience (créateur vs pro) → on l'ignore pour
    // ne pas mélanger les contextes.
    if (draft._aud && draft._aud !== this._getSearchAudience()) return;
    Object.entries(draft).forEach(([id, v]) => {
      if (id === 'plats' || id === '_aud' || id === 'ob-monet') return;
      const el = document.getElementById(id);
      if (!el) return;
      if (el.type === 'checkbox') el.checked = !!v;
      else el.value = (v == null ? '' : String(v));
    });
    if (draft['ob-monet']) {
      const r = document.querySelector(`input[name="ob-monet"][value="${draft['ob-monet']}"]`);
      if (r) r.checked = true;
    }
    if (Array.isArray(draft.plats)) {
      document.querySelectorAll('[data-ob-plat]').forEach(cb => {
        const on = draft.plats.includes(cb.dataset.obPlat);
        cb.checked = on;
        cb.closest('.ob-platform-chip')?.classList.toggle('is-on', on);
      });
    }
  },

  _bindSearchDraftPersist() {
    const root = document.getElementById('ob-content');
    if (!root) return;
    const save = () => this._saveSearchDraft();
    root.querySelectorAll('input, select, textarea').forEach(el => {
      el.addEventListener('input',  save);
      el.addEventListener('change', save);
    });
  },

  _saveListFilters() {
    try { localStorage.setItem(this._LS_LIST_FILTERS, JSON.stringify({
      filters: this.state.filters || {},
      page:    this.state.page    || 0,
      jobFilterInfo: this.state.jobFilterInfo || null,
    })); } catch (e) {}
  },

  _applyListFilters() {
    let v = null;
    try { v = JSON.parse(localStorage.getItem(this._LS_LIST_FILTERS) || 'null'); }
    catch (e) {}
    if (!v) return;
    if (v.filters) Object.assign(this.state.filters, v.filters);
    if (typeof v.page === 'number') this.state.page = v.page;
    if (v.jobFilterInfo) this.state.jobFilterInfo = v.jobFilterInfo;
  },

  _getListAudience() {
    // Renvoie le filtre d'audience persisté pour la liste des prospects.
    // '' = tous, 'creator', 'pro'.
    if (this.state.filters.audience !== '') return this.state.filters.audience;
    let v = '';
    try { v = localStorage.getItem(this._LIST_AUDIENCE_KEY) || ''; } catch (e) {}
    if (v !== 'creator' && v !== 'pro') v = '';
    this.state.filters.audience = v;
    return v;
  },

  _setListAudience(aud) {
    if (aud !== '' && aud !== 'creator' && aud !== 'pro') return;
    this.state.filters.audience = aud;
    try { localStorage.setItem(this._LIST_AUDIENCE_KEY, aud); } catch (e) {}
    this.state.page = 0;
    this._renderCreators();
  },

  _getSearchAudience() {
    if (this.state.searchAudience) return this.state.searchAudience;
    let v = null;
    try { v = localStorage.getItem(this._AUDIENCE_KEY); } catch (e) {}
    if (v !== 'creator' && v !== 'pro') v = 'creator';
    this.state.searchAudience = v;
    return v;
  },

  _setSearchAudience(aud) {
    if (aud !== 'creator' && aud !== 'pro') return;
    this.state.searchAudience = aud;
    try { localStorage.setItem(this._AUDIENCE_KEY, aud); } catch (e) {}
    this._renderSearch();
  },

  PLATFORMS: [
    // ── Créateurs & influenceurs ──
    { id: 'linkedin',  label: 'LinkedIn',  source: 'phantombuster', audience: 'creator' },
    { id: 'instagram', label: 'Instagram', source: 'phantombuster', audience: 'creator' },
    { id: 'tiktok',    label: 'TikTok',    source: 'phantombuster', audience: 'creator' },
    { id: 'youtube',   label: 'YouTube',                              audience: 'creator' },
    { id: 'twitch',    label: 'Twitch',                               audience: 'creator' },
    { id: 'reddit',    label: 'Reddit',                               audience: 'creator' },
    { id: 'bluesky',   label: 'Bluesky',                              audience: 'creator' },
    { id: 'mastodon',  label: 'Mastodon',                             audience: 'creator' },
    { id: 'podcasts',  label: 'Apple Podcasts', tip: '70-90% emails — mine d’or', audience: 'creator' },
    { id: 'dailymotion', label: 'Dailymotion',                        audience: 'creator' },
    { id: 'kick',      label: 'Kick',                                 audience: 'creator' },
    { id: 'github',    label: 'GitHub',                               audience: 'creator' },
    { id: 'pypi',      label: 'PyPI', tip: '70-90% emails — devs IA / outils / automatisation', audience: 'creator' },
    // ── Pros & entreprises ──
    { id: 'osm',       label: 'OpenStreetMap', tip: '100% emails (filtré) — restos, artisans, cabinets, hôtels', audience: 'pro' },
    { id: 'pubmed',    label: 'PubMed', tip: '60-80% emails — chercheurs, labos, biotech, santé', audience: 'pro' },
  ],

  AUDIENCE_LABELS: {
    creator: { title: 'Créateurs & influenceurs',
               hint: 'Audience, abonnés, partenariats, codes promo, commissions' },
    pro:     { title: 'Pros & entreprises',
               hint: 'Clients directs : commerces locaux, artisans, cabinets, chercheurs' },
  },

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
          <button data-ob-tab="search"   class="ob-tab is-active">Nouvelle recherche</button>
          <button data-ob-tab="settings" class="ob-tab">Réglages</button>
        </nav>

        <div id="ob-content"></div>
      </section>
    `;
    this._injectStyles();
    this._standalone = false;
    this.state.tab = 'search';
    document.getElementById('ob-refresh').onclick = () => this.refresh();
    this._root.querySelectorAll('[data-ob-tab]').forEach(b => {
      b.addEventListener('click', () => this.switchTab(b.dataset.obTab));
    });
    await this.refresh();
  },

  // Vue autonome "Tous les prospects" — utilisée par l'item sidebar
  // "Tous les prospects" sous PROSPECTION. Réutilise toute la machinerie
  // de l'onglet Créateurs, mais sans les onglets Obelisk (Nouvelle
  // recherche / Réglages restent dans la vue Obelisk).
  async renderCreatorsView(container) {
    this._root = container;
    this._standalone = true;
    this.state.tab = 'creators';
    container.innerHTML = `
      <section class="animate-slide-up">
        <header class="ob-header">
          <div class="ob-header-text">
            <div class="hero-kicker">PROSPECTION</div>
            <h1 class="ob-title">Tous tes prospects, peu importe leur source.</h1>
          </div>
          <div class="ob-header-actions">
            <div id="ob-stats-inline" class="ob-stats-inline"></div>
            <button id="ob-import-file" class="ob-import-btn" title="Importer une liste de prospects depuis un fichier Excel ou CSV">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
              Importer fichier
            </button>
            <button id="ob-refresh" class="ob-icon-btn" title="Rafraîchir" aria-label="Rafraîchir">↻</button>
          </div>
        </header>
        <div class="ob-flow-strip">
          <span class="ob-flow-step"><b>1 · Trouver</b> — Obélisk, Chasseur, Créateur, Google, Argus</span>
          <span class="ob-flow-arrow">→</span>
          <span class="ob-flow-step"><b>2 · Ici</b> — tout atterrit dans cette base, sans doublon</span>
          <span class="ob-flow-arrow">→</span>
          <span class="ob-flow-step"><b>3 · Écrire & envoyer</b> — Auto-pilote (ou Le Convoi pour une liste)</span>
          <span class="ob-flow-arrow">→</span>
          <span class="ob-flow-step"><b>4 · Réponses</b> — triées toutes seules</span>
        </div>
        <div id="ob-content"></div>
      </section>
    `;
    this._injectStyles();
    document.getElementById('ob-refresh').onclick = () => this.refresh();
    document.getElementById('ob-import-file').onclick = () => this._openImportFile();
    // Restaure les filtres de la liste si on revient sur la vue
    this._applyListFilters();
    await this._loadStats();
    await this._renderCreators();
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
      /* Bandeau "parcours" : rappelle en une ligne comment les outils
         s'enchaînent. Discret, ne vole pas la vedette à la liste. */
      .ob-flow-strip {
        display: flex; align-items: center; flex-wrap: wrap; gap: 6px 10px;
        padding: 8px 12px; margin-bottom: 14px;
        border: 1px dashed hsl(var(--border));
        border-radius: 10px;
        font-size: 11.5px; color: hsl(var(--text-muted));
        background: hsl(var(--bg) / .55);
      }
      .ob-flow-strip b { color: hsl(var(--text-secondary)); font-weight: 600; }
      .ob-flow-arrow { color: hsl(var(--accent)); font-weight: 700; }
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
      .ob-import-btn {
        display: inline-flex; align-items: center; gap: 7px;
        height: 32px; padding: 0 12px; border-radius: 8px;
        background: hsl(var(--card)); border: 1px solid hsl(var(--border));
        color: hsl(var(--text)); font-size: 12.5px; font-weight: 600;
        cursor: pointer; transition: all 140ms;
      }
      .ob-import-btn:hover {
        border-color: hsl(var(--accent) / .55);
        color: hsl(var(--accent));
        background: hsl(var(--accent) / .06);
      }
      .ob-import-btn[disabled] {
        opacity: .6; cursor: progress;
      }

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

      /* Liste prospects — toggle Tous / Créateurs / Pros */
      .ob-audience-toggle {
        display: inline-flex; gap: 2px; padding: 4px;
        margin-bottom: 14px;
        background: hsl(var(--bg));
        border: 1px solid hsl(var(--border));
        border-radius: 10px;
      }
      .ob-audience-pill {
        padding: 7px 16px; font-size: 13px; font-weight: 600;
        color: hsl(var(--text-muted));
        background: transparent; border: none; border-radius: 7px;
        cursor: pointer; transition: all 140ms ease;
      }
      .ob-audience-pill:hover { color: hsl(var(--text)); }
      .ob-audience-pill.is-on {
        background: hsl(var(--accent));
        color: white;
        box-shadow: 0 1px 4px hsl(var(--accent) / .35);
      }

      /* Onglet Recherche */
      .ob-audience-switch {
        display: grid; grid-template-columns: 1fr 1fr; gap: 10px;
        margin-bottom: 22px;
      }
      .ob-audience-card {
        display: flex; flex-direction: column; gap: 4px;
        padding: 14px 16px; border-radius: 12px; cursor: pointer;
        background: hsl(var(--bg)); border: 1.5px solid hsl(var(--border));
        text-align: left; transition: all 160ms ease;
      }
      .ob-audience-card:hover {
        border-color: hsl(var(--accent) / .6);
        background: hsl(var(--accent) / .04);
      }
      .ob-audience-card.is-on {
        background: hsl(var(--accent) / .12);
        border-color: hsl(var(--accent));
        box-shadow: 0 0 0 3px hsl(var(--accent) / .12);
      }
      .ob-audience-card-title {
        font-size: 14px; font-weight: 700; color: hsl(var(--text));
        display: flex; align-items: center; gap: 8px;
      }
      .ob-audience-card.is-on .ob-audience-card-title { color: hsl(var(--accent)); }
      .ob-audience-card-hint {
        font-size: 11.5px; color: hsl(var(--text-muted));
        line-height: 1.4;
      }
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
    return !!(f.q || f.platform || f.status || f.has_email || f.country || f.job_id);
  },

  async _renderCreators() {
    const c = document.getElementById('ob-content');
    const totalAll = (this.state.stats && this.state.stats.total) || 0;

    // Si aucun créateur en base ET aucun filtre actif → grand empty hero
    if (totalAll === 0 && !this._hasActiveFilters()) {
      c.innerHTML = this._emptyHeroHtml();
      const cta = document.getElementById('ob-empty-cta');
      if (cta) cta.onclick = () => {
        if (this._standalone) App.show('obelisk');
        else this.switchTab('search');
      };
      return;
    }

    // Persistance du toggle "Type" (Tous / Créateurs / Pros)
    const listAud = this._getListAudience();

    c.innerHTML = `
      <div class="ob-audience-toggle" role="tablist" aria-label="Type de prospect">
        ${[
          { v: '',        label: 'Tous',         icon: '' },
          { v: 'creator', label: 'Créateurs',    icon: '🎙️' },
          { v: 'pro',     label: 'Pros',         icon: '🏢' },
        ].map(o => `
          <button type="button" class="ob-audience-pill ${listAud === o.v ? 'is-on' : ''}"
                  role="tab" aria-selected="${listAud === o.v}"
                  data-ob-set-list-aud="${o.v}">
            ${o.icon ? o.icon + ' ' : ''}${this._esc(o.label)}
          </button>
        `).join('')}
      </div>

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
        <select id="ob-f-exported" title="Filtrer les prospects selon qu'ils ont déjà été inclus dans un export Excel/PDF">
          <option value="">Export : tous</option>
          <option value="no" ${this.state.filters.exported === 'no' ? 'selected' : ''}>Jamais exportés</option>
          <option value="yes" ${this.state.filters.exported === 'yes' ? 'selected' : ''}>Déjà exportés</option>
        </select>
        <select id="ob-f-contacted" title="Filtrer les prospects selon qu'on leur a déjà écrit un mail">
          <option value="">Contact : tous</option>
          <option value="no" ${this.state.filters.contacted === 'no' ? 'selected' : ''}>Jamais contactés</option>
          <option value="yes" ${this.state.filters.contacted === 'yes' ? 'selected' : ''}>Déjà contactés</option>
        </select>
        <select id="ob-f-sort" title="Ordre de tri de la liste">
          <option value="subs_desc" ${(!this.state.filters.sort_by || this.state.filters.sort_by === 'subs_desc' || this.state.filters.sort_by === 'score') ? 'selected' : ''}>Tri : Abonnés (+ → -)</option>
          <option value="subs_asc" ${this.state.filters.sort_by === 'subs_asc' ? 'selected' : ''}>Tri : Abonnés (- → +)</option>
        </select>
      </div>

      <div id="ob-active-filters"></div>

      <div class="ob-export-bar" style="display:flex; justify-content:flex-end; gap:8px; margin: 6px 0 10px;">
        <button id="ob-purge-nonfr" class="btn btn-ghost" title="Supprimer définitivement les prospects non-francophones"
                style="display:inline-flex; align-items:center; gap:6px; padding:7px 12px; font-size:12px; color:#c44; border-color:rgba(196,68,68,0.4);">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/></svg>
          Nettoyer non-francophones
        </button>
        <button id="ob-purge-guessed" class="btn btn-ghost" title="Supprimer définitivement les prospects dont tous les emails sont génériques (contact@, info@, hello@, …) — donc devinés à partir du domaine et jamais lus en vrai"
                style="display:inline-flex; align-items:center; gap:6px; padding:7px 12px; font-size:12px; color:#c44; border-color:rgba(196,68,68,0.4);">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/></svg>
          Supprimer mails devinés
        </button>
        <div style="display:inline-flex; align-items:center; gap:6px; padding:5px 10px 5px 10px; border:1px solid rgba(196,68,68,0.4); border-radius:8px; font-size:12px; color:#c44;">
          <span>Supprimer si &lt;</span>
          <input id="ob-purge-min-subs" type="number" min="1" placeholder="ex: 500"
                 title="Tous les prospects avec moins de cette valeur d'abonnés seront supprimés (les prospects sans nombre d'abonnés mesuré sont préservés)"
                 style="width:80px; padding:3px 6px; border:1px solid hsl(var(--border)); border-radius:6px; background:transparent; color:hsl(var(--text)); font-size:12px; text-align:center;"/>
          <span>abonnés</span>
          <button id="ob-purge-subs" type="button" title="Lance la suppression (avec preview + confirmation)"
                  style="margin-left:4px; padding:3px 8px; border:1px solid rgba(196,68,68,0.4); border-radius:6px; background:transparent; color:#c44; font-size:12px; cursor:pointer;">
            Go
          </button>
        </div>
        <div style="display:inline-flex; align-items:center; gap:6px; padding:6px 10px; border:1px solid hsl(var(--border)); border-radius:8px; font-size:12px; color:hsl(var(--text-muted));">
          <span>Combien :</span>
          <input id="ob-export-count" type="number" min="1" max="5000" placeholder="tous"
                 title="Nombre max de prospects à inclure dans l'export (laisse vide pour tout exporter)"
                 style="width:70px; padding:3px 6px; border:1px solid hsl(var(--border)); border-radius:6px; background:transparent; color:hsl(var(--text)); font-size:12px; text-align:center;"/>
        </div>
        <button id="ob-export-xlsx" class="btn btn-ghost" title="Télécharger la liste filtrée en Excel"
                style="display:inline-flex; align-items:center; gap:6px; padding:7px 12px; font-size:12px;">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="9" y1="15" x2="15" y2="15"/><line x1="9" y1="18" x2="15" y2="18"/></svg>
          Excel
        </button>
        <button id="ob-export-pdf" class="btn btn-ghost" title="Télécharger la liste filtrée en PDF"
                style="display:inline-flex; align-items:center; gap:6px; padding:7px 12px; font-size:12px;">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="12" y1="18" x2="12" y2="12"/><polyline points="9 15 12 12 15 15"/></svg>
          PDF
        </button>
      </div>

      <div id="ob-table-wrap" class="ob-table-card"></div>
      <div id="ob-pager" class="ob-pager"></div>
    `;

    const applyFromInputs = () => {
      this.state.filters.q        = document.getElementById('ob-f-q').value;
      this.state.filters.platform = document.getElementById('ob-f-platform').value;
      this.state.filters.status   = document.getElementById('ob-f-status').value;
      this.state.filters.has_email= document.getElementById('ob-f-email').value;
      this.state.filters.exported = document.getElementById('ob-f-exported').value;
      this.state.filters.contacted= document.getElementById('ob-f-contacted').value;
      this.state.filters.sort_by  = document.getElementById('ob-f-sort').value;
      // Le filtre "pays" reste dans state mais n'est plus exposé dans
      // l'UI (Obelisk est purement francophone maintenant, voir purge).
      this.state.page = 0;
      this._saveListFilters();
      this._loadCreators();
    };

    // Toggle "Type" (Tous / Créateurs / Pros) — recharge la liste filtrée
    c.querySelectorAll('[data-ob-set-list-aud]').forEach(btn => {
      btn.addEventListener('click', () => this._setListAudience(btn.dataset.obSetListAud));
    });

    // La recherche libre filtre après une courte pause (debounce)
    const qInput = document.getElementById('ob-f-q');
    let qTimer;
    qInput.addEventListener('input', () => {
      clearTimeout(qTimer);
      qTimer = setTimeout(applyFromInputs, 280);
    });
    // Les selects filtrent dès le change
    ['ob-f-platform', 'ob-f-status', 'ob-f-email', 'ob-f-exported',
     'ob-f-contacted', 'ob-f-sort'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.addEventListener('change', applyFromInputs);
    });

    // Boutons d'export Excel / PDF — utilisent les filtres en cours
    const btnXlsx = document.getElementById('ob-export-xlsx');
    const btnPdf  = document.getElementById('ob-export-pdf');
    if (btnXlsx) btnXlsx.addEventListener('click', () => this._exportList('xlsx'));
    if (btnPdf)  btnPdf .addEventListener('click', () => this._exportList('pdf'));

    // Bouton "Nettoyer non-francophones" (preview + confirmation)
    const btnPurge = document.getElementById('ob-purge-nonfr');
    if (btnPurge) btnPurge.addEventListener('click', () => this._purgeNonFrench());

    // Bouton "Supprimer mails devinés" (preview + confirmation)
    const btnPurgeGuessed = document.getElementById('ob-purge-guessed');
    if (btnPurgeGuessed) btnPurgeGuessed.addEventListener('click', () => this._purgeGuessedEmails());

    // Bouton "Supprimer si < X abonnés" (preview + confirmation)
    const btnPurgeSubs = document.getElementById('ob-purge-subs');
    if (btnPurgeSubs) btnPurgeSubs.addEventListener('click', () => this._purgeBelowSubs());

    await this._loadCreators();
  },

  // ── Purge des non-francophones (preview puis confirmation) ────────
  async _purgeNonFrench() {
    const btn = document.getElementById('ob-purge-nonfr');
    const originalLabel = btn ? btn.innerHTML : '';
    if (btn) { btn.disabled = true; btn.innerHTML = 'Scan…'; }
    try {
      // 1) Preview
      const audit = await this._api('audit_non_french');
      if (!audit || !audit.ok) {
        alert("Impossible de scanner la base : " + ((audit && audit.error) || 'erreur inconnue'));
        return;
      }
      const count = audit.non_fr_count || 0;
      const total = audit.total_scanned || 0;
      if (count === 0) {
        alert(`Aucun non-francophone détecté sur les ${total} prospects scannés. Rien à supprimer.`);
        return;
      }
      // Exemples lisibles
      const exLines = (audit.examples || []).map(e =>
        `  • ${e.name} ${e.country ? '('+e.country+') ' : ''}— ${e.reason}`
      ).join('\n');
      const msg =
        `Sur ${total} prospects scannés, ${count} ne sont PAS confirmés francophones.\n\n` +
        `Exemples :\n${exLines}\n\n` +
        `Veux-tu vraiment les SUPPRIMER définitivement de la base ?\n` +
        `(action irréversible)`;
      if (!window.confirm(msg)) {
        return;
      }
      // 2) Purge réelle
      if (btn) btn.innerHTML = `Suppression de ${count}…`;
      const res = await this._api('purge_non_french', { confirm: 'PURGE_NON_FR' });
      if (!res || !res.ok) {
        alert("Suppression échouée : " + ((res && res.error) || 'erreur inconnue'));
        return;
      }
      alert(`✅ ${res.deleted || 0} prospect(s) non-francophones supprimés.`);
      // Recharge la liste
      await this._loadCreators();
    } catch (err) {
      alert("Erreur : " + (err && err.message || err));
    } finally {
      if (btn) { btn.disabled = false; btn.innerHTML = originalLabel; }
    }
  },

  // ── Purge des prospects à mails uniquement génériques (devinés) ───
  async _purgeGuessedEmails() {
    const btn = document.getElementById('ob-purge-guessed');
    const originalLabel = btn ? btn.innerHTML : '';
    if (btn) { btn.disabled = true; btn.innerHTML = 'Scan…'; }
    try {
      // 1) Preview
      const audit = await this._api('audit_guessed_emails');
      if (!audit || !audit.ok) {
        alert("Impossible de scanner la base : " + ((audit && audit.error) || 'erreur inconnue'));
        return;
      }
      const count = audit.count || 0;
      const total = audit.total_scanned || 0;
      if (count === 0) {
        alert(`Aucun prospect avec uniquement des mails devinés sur les ${total} scannés. Rien à supprimer.`);
        return;
      }
      const exLines = (audit.examples || []).map(e =>
        `  • ${e.name} — ${e.email}`
      ).join('\n');
      const msg =
        `Sur ${total} prospects scannés, ${count} n'ont que des mails génériques (contact@, info@, hello@, …).\n` +
        `Ces mails ont été devinés à partir du domaine, ils n'ont jamais été lus en vrai.\n\n` +
        `Exemples :\n${exLines}\n\n` +
        `Veux-tu vraiment les SUPPRIMER définitivement de la base ?\n` +
        `(action irréversible)`;
      if (!window.confirm(msg)) return;
      // 2) Purge réelle
      if (btn) btn.innerHTML = `Suppression de ${count}…`;
      const res = await this._api('purge_guessed_emails', { confirm: 'PURGE_GUESSED' });
      if (!res || !res.ok) {
        alert("Suppression échouée : " + ((res && res.error) || 'erreur inconnue'));
        return;
      }
      alert(`✅ ${res.deleted || 0} prospect(s) à mails devinés supprimés.`);
      await this._loadCreators();
    } catch (err) {
      alert("Erreur : " + (err && err.message || err));
    } finally {
      if (btn) { btn.disabled = false; btn.innerHTML = originalLabel; }
    }
  },

  // ── Suppression des prospects en dessous d'un seuil d'abonnés ─────
  async _purgeBelowSubs() {
    const input = document.getElementById('ob-purge-min-subs');
    const btn = document.getElementById('ob-purge-subs');
    const threshold = input ? parseInt(input.value, 10) : 0;
    if (!threshold || threshold <= 0) {
      alert("Entre un nombre d'abonnés minimum (ex: 500).");
      input?.focus();
      return;
    }
    const originalLabel = btn ? btn.innerHTML : '';
    if (btn) { btn.disabled = true; btn.innerHTML = 'Scan…'; }
    try {
      // 1) Preview
      const pre = await this._api('purge_below_subs', { threshold });
      if (!pre || !pre.ok) {
        alert("Impossible de scanner : " + ((pre && pre.error) || 'erreur inconnue'));
        return;
      }
      const count = pre.count || 0;
      if (count === 0) {
        alert(`Aucun prospect avec moins de ${threshold.toLocaleString('fr-FR')} abonnés. Rien à supprimer.`);
        return;
      }
      const exLines = (pre.examples || []).map(e =>
        `  • ${e.name} — ${Number(e.subscribers || 0).toLocaleString('fr-FR')} abonnés`
      ).join('\n');
      const msg =
        `${count.toLocaleString('fr-FR')} prospects ont moins de ${threshold.toLocaleString('fr-FR')} abonnés.\n\n` +
        `Exemples :\n${exLines}\n\n` +
        `Confirmer la SUPPRESSION définitive de ces ${count} prospects ?\n` +
        `(action irréversible)`;
      if (!window.confirm(msg)) return;
      // 2) Suppression réelle
      if (btn) btn.innerHTML = `Suppression de ${count}…`;
      const res = await this._api('purge_below_subs', {
        threshold,
        confirm: 'PURGE_BELOW_SUBS',
      });
      if (!res || !res.ok) {
        alert("Suppression échouée : " + ((res && res.error) || 'erreur inconnue'));
        return;
      }
      alert(`✅ ${res.deleted || 0} prospect(s) supprimés.`);
      if (input) input.value = '';
      await this._loadCreators();
    } catch (err) {
      alert("Erreur : " + (err && err.message || err));
    } finally {
      if (btn) { btn.disabled = false; btn.innerHTML = originalLabel; }
    }
  },

  // ── Importer fichier (Excel / CSV) ───────────────────────────────
  _openImportFile() {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.xlsx,.xlsm,.xls,.csv,.tsv,.txt';
    input.style.display = 'none';
    document.body.appendChild(input);
    input.addEventListener('change', () => {
      const file = input.files && input.files[0];
      document.body.removeChild(input);
      if (file) this._runImportFile(file);
    });
    input.click();
  },

  async _runImportFile(file) {
    const btn = document.getElementById('ob-import-file');
    const original = btn ? btn.innerHTML : '';
    if (btn) {
      btn.disabled = true;
      btn.innerHTML = 'Lecture du fichier…';
    }
    try {
      // 20 Mo max côté front aussi
      if (file.size > 20 * 1024 * 1024) {
        alert("Fichier trop gros (max 20 Mo).");
        return;
      }
      const buf = await file.arrayBuffer();
      // Encode en base64 par paquets pour éviter de saturer la pile JS
      const bytes = new Uint8Array(buf);
      let binary = '';
      const chunk = 0x8000;
      for (let i = 0; i < bytes.length; i += chunk) {
        binary += String.fromCharCode.apply(
          null, bytes.subarray(i, i + chunk),
        );
      }
      const b64 = btoa(binary);
      if (btn) btn.innerHTML = 'Import en cours…';
      const res = await this._api('import_file', {
        filename: file.name,
        data:     b64,
      });
      if (!res || !res.ok) {
        alert("Import impossible : " +
              ((res && res.error) || 'erreur inconnue'));
        return;
      }
      const parts = [];
      parts.push(`✓ ${res.inserted} nouveau(x) prospect(s) ajouté(s).`);
      if (res.duplicates) parts.push(`${res.duplicates} déjà présent(s) (ignorés).`);
      if (res.skipped)    parts.push(`${res.skipped} ligne(s) vide(s) ou incomplètes.`);
      if (res.errors)     parts.push(`${res.errors} erreur(s) durant l'insertion.`);
      parts.push(`Total lu : ${res.total} ligne(s).`);
      alert(parts.join('\n'));
      // Recharge stats + liste
      await this._loadStats();
      if (typeof this._loadCreators === 'function') {
        await this._loadCreators();
      } else {
        await this.refresh();
      }
    } catch (err) {
      alert("Import en erreur : " + (err && err.message || err));
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = original;
      }
    }
  },

  // ── Export Excel / PDF (depuis les filtres en cours) ──────────────
  async _exportList(format) {
    const btn = document.getElementById(format === 'xlsx' ? 'ob-export-xlsx' : 'ob-export-pdf');
    const originalLabel = btn ? btn.innerHTML : '';
    if (btn) {
      btn.disabled = true;
      btn.innerHTML = format === 'xlsx' ? 'Excel…' : 'PDF…';
    }
    try {
      const f = this.state.filters || {};
      // Limite optionnelle saisie par l'utilisateur (vide = tous, capé
      // côté backend à 5000 pour éviter d'exploser la mémoire).
      const countInput = document.getElementById('ob-export-count');
      const rawCount = countInput && countInput.value ? countInput.value.trim() : '';
      const limit = rawCount ? Math.max(1, parseInt(rawCount, 10) || 0) : null;
      const payload = {
        format,
        platform:  f.platform  || '',
        status:    f.status    || '',
        city:      f.city      || '',
        q:         f.q         || '',
        has_email: f.has_email || '',
        country:   f.country   || '',
        job_id:    f.job_id    || '',
        audience:  f.audience  || '',
      };
      if (limit) payload.limit = limit;
      const res = await this._api('export', payload);
      if (!res || !res.ok) {
        alert("Export impossible : " + ((res && res.error) || 'erreur inconnue'));
        return;
      }
      // Décode le base64 et déclenche le download
      const bin = atob(res.b64);
      const bytes = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
      const blob = new Blob([bytes], { type: res.mime || 'application/octet-stream' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = res.filename || ('obelisk_export.' + format);
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (err) {
      alert("Export en erreur : " + (err && err.message || err));
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = originalLabel;
      }
    }
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
    if (chips.length === 0) { wrap.className = ''; wrap.innerHTML = ''; return; }
    wrap.className = 'ob-active-filters';
    wrap.innerHTML = chips.map(([k, l, extra]) =>
      `<span class="chip ${extra || ''}">${this._esc(l)}<button data-ob-rmf="${k}" aria-label="Retirer">×</button></span>`
    ).join('') + `<button class="clear-all" data-ob-clearall>Tout effacer</button>`;
    wrap.querySelectorAll('[data-ob-rmf]').forEach(b => {
      b.onclick = () => {
        const k = b.dataset.obRmf;
        this.state.filters[k] = '';
        if (k === 'job_id') this.state.jobFilterInfo = null;
        this.state.page = 0;
        this._saveListFilters();
        this._renderCreators();
      };
    });
    const clr = wrap.querySelector('[data-ob-clearall]');
    if (clr) clr.onclick = () => {
      this.state.filters = { platform: '', status: '', q: '', has_email: '', country: '', job_id: '', audience: '' };
      this.state.jobFilterInfo = null;
      this.state.page = 0;
      this._saveListFilters();
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
            <th>Créateur</th><th>Plateforme</th><th>Niche</th><th>Abonnés</th><th>Email</th><th>Ville</th><th>Statut</th>
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
    if (prev) prev.onclick = () => { this.state.page = Math.max(0, this.state.page - 1); this._saveListFilters(); this._loadCreators(); };
    if (next) next.onclick = () => { this.state.page = Math.min(lastPage, this.state.page + 1); this._saveListFilters(); this._loadCreators(); };
  },

  _rowHtml(p) {
    const platform = this._inferPlatform(p);
    const emails = Array.isArray(p.emails) ? p.emails : [];
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
        <td style="color: hsl(var(--text-muted)); font-size: 12px;">${p.industry ? this._esc(p.industry) : '—'}</td>
        <td style="color: hsl(var(--text)); font-variant-numeric: tabular-nums; white-space: nowrap;">${this._fmtSubs(p.subscribers, p.subs_hidden)}</td>
        <td>${emails[0] ? `<a href="mailto:${this._esc(emails[0])}" style="color: hsl(var(--info));" onclick="event.stopPropagation()">${this._esc(emails[0])}</a>${emails.length > 1 ? ` <span style="color: hsl(var(--text-muted)); font-size: 11.5px;">+${emails.length - 1}</span>` : ''}` : '<span style="color: hsl(var(--text-muted));">—</span>'}</td>
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
    const aud = this._getSearchAudience();
    const isPro = aud === 'pro';
    // Défauts forcés à chaque ouverture du formulaire (Jordan veut toujours
    // partir d'une feuille blanche). En mode créateur : YouTube seul. En mode
    // pro : OpenStreetMap seul (mine d'or 100% emails).
    const defaultPlatforms = isPro ? new Set(['osm']) : new Set(['youtube']);
    const monetMode = 'all';
    const platsOfAud = this.PLATFORMS.filter(p => p.audience === aud);
    const headTitle = isPro
      ? 'Nouvelle recherche — Pros & entreprises'
      : 'Nouvelle recherche — Créateurs & influenceurs';
    const headIntro = isPro
      ? 'Restos, artisans, cabinets, hôtels, chercheurs, labos… Obelisk balaie les annuaires publics, récupère les emails et stocke tout dans ton CRM.'
      : 'Audience, abonnés, codes promo, partenariats. Obelisk balaie les plateformes activées (YouTube, LinkedIn, Instagram, TikTok…), enrichit les profils et stocke tout dans ton CRM.';
    const nichePlaceholder = isPro
      ? 'ex : restaurant, plombier, ostéopathe, avocat, laboratoire santé'
      : 'ex : entrepreneur, coaching, growth, formation';
    c.innerHTML = `
      <div class="grid grid-cols-1 lg:grid-cols-[1fr_360px] gap-5">
        <div class="bg-card border border-border rounded-xl p-6">
          <div class="ob-audience-switch">
            ${['creator', 'pro'].map(a => {
              const meta = this.AUDIENCE_LABELS[a];
              const on = a === aud;
              const icon = a === 'creator' ? '🎙️' : '🏢';
              return `<button type="button" class="ob-audience-card ${on ? 'is-on' : ''}" data-ob-set-aud="${a}">
                <div class="ob-audience-card-title">${icon} ${this._esc(meta.title)}</div>
                <div class="ob-audience-card-hint">${this._esc(meta.hint)}</div>
              </button>`;
            }).join('')}
          </div>

          <h3 class="text-lg font-bold mb-1">${this._esc(headTitle)}</h3>
          <p class="text-sm text-text-muted mb-5">${this._esc(headIntro)}</p>

          <label class="block mb-4">
            <div class="text-[11px] font-bold uppercase tracking-widest text-text-muted mb-2">Niche(s) — séparées par virgules pour en lancer plusieurs</div>
            <input id="ob-s-niche" placeholder="${this._esc(nichePlaceholder)}" value="${this._esc(cfg.niche || '')}" style="width:100%; padding:10px 14px; border-radius:8px; background: hsl(var(--bg)); color: hsl(var(--text)); border: 1px solid hsl(var(--border)); font-size: 14px;">
            <div class="text-[11px] text-text-muted mt-1">Une virgule = une recherche supplémentaire. Tout est fusionné dans un seul job, avec dédup automatique.</div>
          </label>

          ${isPro ? `
          <label class="block mb-4">
            <div class="text-[11px] font-bold uppercase tracking-widest text-text-muted mb-2">Zone géographique</div>
            <input id="ob-s-osm-area" placeholder="ex : Rennes, Bretagne, Île-de-France, France" value="${this._esc(cfg.osm_area || 'France')}" style="width:100%; padding:10px 14px; border-radius:8px; background: hsl(var(--bg)); color: hsl(var(--text)); border: 1px solid hsl(var(--border)); font-size: 14px;">
            <div class="text-[11px] text-text-muted mt-1">Nom exact tel qu'il est sur OpenStreetMap (commune, département, région, pays). Plus la zone est petite, plus la recherche est rapide et ciblée.</div>
          </label>
          ` : ''}

          <div class="block mb-4">
            <div class="text-[11px] font-bold uppercase tracking-widest text-text-muted mb-2">Plateformes</div>
            <div class="ob-platform-grid">
              ${platsOfAud.map(p => `
                <label class="ob-platform-chip ${defaultPlatforms.has(p.id) ? 'is-on' : ''}" ${p.tip ? `title="${this._esc(p.tip)}"` : ''}>
                  <input type="checkbox" data-ob-plat="${p.id}" data-ob-aud="${aud}" ${defaultPlatforms.has(p.id) ? 'checked' : ''} style="margin: 0;">
                  ${this._esc(p.label)}
                </label>
              `).join('')}
            </div>
          </div>

          ${isPro ? '' : `
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
          `}

          <div class="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-4">
            <label class="ob-toggle-row">
              <input id="ob-s-with-email" type="checkbox" ${cfg.only_with_email !== false ? 'checked' : ''}>
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
    // Sélecteur d'audience (créateurs vs pros)
    c.querySelectorAll('[data-ob-set-aud]').forEach(btn => {
      btn.addEventListener('click', () => this._setSearchAudience(btn.dataset.obSetAud));
    });
    // Chip toggle visual
    c.querySelectorAll('[data-ob-plat]').forEach(cb => {
      cb.addEventListener('change', () => {
        cb.closest('.ob-platform-chip').classList.toggle('is-on', cb.checked);
      });
    });
    document.getElementById('ob-s-launch').onclick = () => this._launchSearch();
    // Restaure le brouillon de recherche en cours (saisies non lancées)
    this._applySearchDraft();
    this._bindSearchDraftPersist();
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
    App.show('prospects_crm');
  },

  async _launchSearch() {
    const niche = document.getElementById('ob-s-niche').value.trim();
    const max   = parseInt(document.getElementById('ob-s-max').value, 10) || 30;
    const platforms = [];
    document.querySelectorAll('[data-ob-plat]:checked').forEach(cb => platforms.push(cb.dataset.obPlat));
    if (!niche)             { alert('Renseigne une niche.'); return; }
    if (!platforms.length)  { alert('Coche au moins une plateforme.'); return; }

    // Filtres avancés — certains n'existent qu'en mode "créateur"
    const monetEl = document.querySelector('input[name="ob-monet"]:checked');
    const monetMode = (monetEl && monetEl.value) || 'all';   // all | unmonetized | monetized
    const minSubsEl = document.getElementById('ob-s-min-subs');
    const maxSubsEl = document.getElementById('ob-s-max-subs');
    const minSubs = minSubsEl ? (parseInt(minSubsEl.value, 10) || 0) : 0;
    const maxSubs = maxSubsEl ? (parseInt(maxSubsEl.value, 10) || 0) : 0;
    const onlyWithEmail = document.getElementById('ob-s-with-email').checked;
    const onlyUncontacted = document.getElementById('ob-s-uncontacted').checked;

    const osmAreaEl = document.getElementById('ob-s-osm-area');
    const osmArea = osmAreaEl ? osmAreaEl.value.trim() : '';

    const filters = {
      monetized_mode:  monetMode,
      min_subscribers: minSubs,
      max_subscribers: maxSubs,
      country:  '',
      language: 'fr',
      only_with_email:  onlyWithEmail,
      only_uncontacted: onlyUncontacted,
      osm_area:         osmArea,
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
