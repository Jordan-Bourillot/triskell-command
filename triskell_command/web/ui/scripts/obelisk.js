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
    filters: { platform: '', status: '', min_score: 0, q: '', has_email: '' },
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

  async render(container) {
    this._root = container;
    container.innerHTML = `
      <section class="animate-slide-up">
        <div class="mb-6 flex items-end justify-between">
          <div>
            <div class="hero-kicker mb-2">OBELISK</div>
            <h1 class="hero-title mb-3" style="font-size: 36px;">Trouve les créateurs vierges de ta niche.</h1>
            <p class="hero-subtitle">12 plateformes scannées (dont LinkedIn / Instagram / TikTok via PhantomBuster), créateurs non monétisés détectés, emails enrichis, mails rédigés. Tu valides, tu envoies.</p>
          </div>
          <div class="flex gap-2">
            <button id="ob-refresh" class="btn btn-secondary">Rafraîchir</button>
          </div>
        </div>

        <div id="ob-stats" class="grid grid-cols-2 md:grid-cols-5 gap-3 mb-6"></div>

        <div class="flex gap-2 mb-6 border-b border-border">
          <button data-ob-tab="creators" class="ob-tab is-active">Créateurs</button>
          <button data-ob-tab="search"   class="ob-tab">Nouvelle recherche</button>
          <button data-ob-tab="settings" class="ob-tab">Réglages</button>
        </div>

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
      .ob-tab {
        padding: 10px 18px; font-size: 13px; font-weight: 600;
        color: hsl(var(--text-muted));
        border-bottom: 2px solid transparent;
        transition: color 160ms, border-color 160ms;
      }
      .ob-tab:hover { color: hsl(var(--text)); }
      .ob-tab.is-active { color: hsl(var(--accent)); border-bottom-color: hsl(var(--accent)); }
      .ob-stat {
        background: hsl(var(--card)); border: 1px solid hsl(var(--border));
        border-radius: 10px; padding: 14px 16px;
      }
      .ob-stat .label { font-size: 10.5px; letter-spacing: .14em; text-transform: uppercase; color: hsl(var(--text-muted)); font-weight: 700; }
      .ob-stat .value { font-size: 24px; font-weight: 700; color: hsl(var(--text)); margin-top: 4px; line-height: 1; }
      .ob-filters {
        display: flex; flex-wrap: wrap; gap: 8px; align-items: center;
        padding: 10px; background: hsl(var(--card));
        border: 1px solid hsl(var(--border)); border-radius: 10px;
        margin-bottom: 12px;
      }
      .ob-filters input, .ob-filters select {
        padding: 7px 10px; border-radius: 7px; background: hsl(var(--bg));
        color: hsl(var(--text)); border: 1px solid hsl(var(--border));
        font-size: 12.5px; min-width: 120px;
      }
      .ob-filters input:focus, .ob-filters select:focus {
        outline: none; border-color: hsl(var(--accent));
        box-shadow: 0 0 0 3px hsl(var(--accent) / .12);
      }
      .ob-table {
        width: 100%; border-collapse: collapse; font-size: 12.5px;
      }
      .ob-table th {
        text-align: left; font-size: 10.5px; letter-spacing: .12em; text-transform: uppercase;
        font-weight: 700; color: hsl(var(--text-muted));
        padding: 10px 12px; border-bottom: 1px solid hsl(var(--border));
      }
      .ob-table td {
        padding: 10px 12px; border-bottom: 1px solid hsl(var(--border));
        vertical-align: top;
      }
      .ob-table tr.is-clickable { cursor: pointer; transition: background 100ms; }
      .ob-table tr.is-clickable:hover { background: hsl(var(--bg)); }
      .ob-pill {
        display: inline-block; padding: 2px 8px; border-radius: 4px;
        font-size: 10.5px; font-weight: 600;
      }
      .ob-status-select {
        padding: 4px 8px; border-radius: 5px; font-size: 11.5px;
        background: hsl(var(--bg)); color: hsl(var(--text));
        border: 1px solid hsl(var(--border));
      }
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
      .ob-platform-grid {
        display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px;
      }
      .ob-platform-chip {
        display: flex; align-items: center; gap: 6px;
        padding: 8px 10px; border-radius: 7px; font-size: 12.5px;
        background: hsl(var(--bg)); border: 1px solid hsl(var(--border));
        cursor: pointer; user-select: none;
      }
      .ob-platform-chip.is-on {
        background: hsl(var(--accent) / .12); border-color: hsl(var(--accent));
        color: hsl(var(--accent)); font-weight: 600;
      }
      .ob-progress {
        background: hsl(var(--bg)); border: 1px solid hsl(var(--border));
        border-radius: 8px; padding: 12px; max-height: 360px; overflow-y: auto;
        font-family: ui-monospace, "SF Mono", Consolas, monospace; font-size: 11.5px;
        white-space: pre-wrap; color: hsl(var(--text-muted));
      }
    `;
    document.head.appendChild(s);
  },

  async refresh() {
    await this._loadStats();
    await this.switchTab(this.state.tab);
  },

  async _loadStats() {
    const wrap = document.getElementById('ob-stats');
    const res = await this._api('stats');
    const st = (res && res.ok && res.stats) ? res.stats : { total: 0, with_email: 0, qualified: 0, contacted: 0, won: 0 };
    this.state.stats = st;
    wrap.innerHTML = `
      ${this._statCard('Total', st.total)}
      ${this._statCard('Avec email', st.with_email)}
      ${this._statCard('Qualifiés', st.qualified)}
      ${this._statCard('Contactés', st.contacted)}
      ${this._statCard('Gagnés', st.won)}
    `;
  },
  _statCard(label, value) {
    return `<div class="ob-stat"><div class="label">${this._esc(label)}</div><div class="value">${Number(value || 0).toLocaleString('fr-FR')}</div></div>`;
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
  async _renderCreators() {
    const c = document.getElementById('ob-content');
    c.innerHTML = `
      <div class="ob-filters">
        <input id="ob-f-q" placeholder="Recherche libre (nom, handle, site, description)" value="${this._esc(this.state.filters.q)}" style="flex:1; min-width: 240px;">
        <select id="ob-f-platform">
          <option value="">Toutes plateformes</option>
          ${this.PLATFORMS.map(p => `<option value="${p.id}" ${this.state.filters.platform === p.id ? 'selected' : ''}>${this._esc(p.label)}</option>`).join('')}
        </select>
        <select id="ob-f-status">
          <option value="">Tous statuts</option>
          ${Object.entries(this.STATUS_LABELS).map(([k, l]) => `<option value="${k}" ${this.state.filters.status === k ? 'selected' : ''}>${this._esc(l)}</option>`).join('')}
        </select>
        <select id="ob-f-email">
          <option value="">Avec ou sans email</option>
          <option value="yes" ${this.state.filters.has_email === 'yes' ? 'selected' : ''}>Avec email</option>
          <option value="no" ${this.state.filters.has_email === 'no' ? 'selected' : ''}>Sans email</option>
        </select>
        <input id="ob-f-score" type="number" min="0" max="100" placeholder="Score min" value="${this.state.filters.min_score || ''}" style="width: 100px;">
        <button id="ob-f-apply" class="btn btn-primary" style="padding: 7px 14px; font-size: 12.5px;">Filtrer</button>
        <button id="ob-f-reset" class="btn btn-ghost" style="padding: 7px 14px; font-size: 12.5px;">Réinitialiser</button>
      </div>
      <div id="ob-table-wrap" class="bg-card border border-border rounded-xl overflow-hidden"></div>
      <div id="ob-pager" class="mt-3 flex items-center justify-between text-[12px] text-text-muted"></div>
    `;
    document.getElementById('ob-f-apply').onclick = () => {
      this.state.filters.q        = document.getElementById('ob-f-q').value;
      this.state.filters.platform = document.getElementById('ob-f-platform').value;
      this.state.filters.status   = document.getElementById('ob-f-status').value;
      this.state.filters.has_email= document.getElementById('ob-f-email').value;
      this.state.filters.min_score= parseInt(document.getElementById('ob-f-score').value, 10) || 0;
      this.state.page = 0;
      this._loadCreators();
    };
    document.getElementById('ob-f-reset').onclick = () => {
      this.state.filters = { platform: '', status: '', min_score: 0, q: '', has_email: '' };
      this.state.page = 0;
      this._renderCreators();
    };
    await this._loadCreators();
  },

  async _loadCreators() {
    const wrap = document.getElementById('ob-table-wrap');
    wrap.innerHTML = '<div class="p-6 text-center text-text-muted text-sm">Chargement…</div>';
    const offset = this.state.page * this.state.pageSize;
    const res = await this._api('list_creators', {
      ...this.state.filters,
      limit: this.state.pageSize,
      offset,
    });
    if (!res || !res.ok) {
      wrap.innerHTML = `<div class="p-6 text-danger text-sm">Erreur : ${this._esc(res && res.error || 'inconnu')}</div>`;
      return;
    }
    this.state.rows = res.rows || [];
    this.state.total = res.count || 0;

    if (this.state.rows.length === 0) {
      wrap.innerHTML = `<div class="p-10 text-center text-text-muted">
        <div class="text-3xl mb-3 opacity-50">🔭</div>
        <div class="font-semibold text-text mb-1">Aucun créateur ne correspond.</div>
        <div class="text-sm">Essaie d'élargir tes filtres, ou lance une nouvelle recherche.</div>
      </div>`;
    } else {
      wrap.innerHTML = `
        <table class="ob-table">
          <thead><tr>
            <th>Créateur</th><th>Plateforme</th><th>Email</th><th>Score</th><th>Ville</th><th>Statut</th>
          </tr></thead>
          <tbody>
            ${this.state.rows.map(p => this._rowHtml(p)).join('')}
          </tbody>
        </table>
      `;
      wrap.querySelectorAll('[data-ob-open]').forEach(tr => {
        tr.onclick = (ev) => {
          // Évite d'ouvrir le drawer quand on clique sur un select
          if (ev.target.closest('select, button, a')) return;
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
      <div class="flex gap-2">
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
    const score = p.score || 0;
    const scoreColor = score >= 70 ? 'text-success' : score >= 40 ? 'text-warning' : 'text-text-muted';
    const status = p.status || 'new';
    return `
      <tr class="is-clickable" data-ob-open="${this._esc(p.id)}">
        <td>
          <div class="font-semibold text-text">${this._esc(p.name || p.handle || p.legal_name || '(sans nom)')}</div>
          ${p.handle ? `<div class="text-[11px] text-text-muted">@${this._esc(p.handle)}</div>` : ''}
        </td>
        <td>${platform ? `<span class="ob-pill" style="background: hsl(var(--accent) / .1); color: hsl(var(--accent));">${this._esc(platform)}</span>` : '<span class="text-text-muted">—</span>'}</td>
        <td>${emails[0] ? `<a href="mailto:${this._esc(emails[0])}" class="text-info hover:underline" onclick="event.stopPropagation()">${this._esc(emails[0])}</a>${emails.length > 1 ? ` <span class="text-text-muted">+${emails.length - 1}</span>` : ''}` : '<span class="text-text-muted">—</span>'}</td>
        <td class="${scoreColor} font-semibold">${score}</td>
        <td>${this._esc(p.city || '')}</td>
        <td>
          <select class="ob-status-select" data-ob-status="${this._esc(p.id)}">
            ${Object.entries(this.STATUS_LABELS).map(([k, l]) => `<option value="${k}" ${status === k ? 'selected' : ''}>${this._esc(l)}</option>`).join('')}
          </select>
        </td>
      </tr>
    `;
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
    const defaultPlatforms = new Set(cfg.platforms || ['youtube', 'reddit']);

    c.innerHTML = `
      <div class="grid grid-cols-1 lg:grid-cols-[1fr_360px] gap-5">
        <div class="bg-card border border-border rounded-xl p-6">
          <h3 class="text-lg font-bold mb-1">Nouvelle recherche</h3>
          <p class="text-sm text-text-muted mb-5">Décris ta cible. Obelisk balaie les plateformes activées (12 dispos, dont LinkedIn / Instagram / TikTok via PhantomBuster), enrichit les profils et stocke tout dans ton CRM.</p>

          <label class="block mb-4">
            <div class="text-[11px] font-bold uppercase tracking-widest text-text-muted mb-2">Niche / mot-clé</div>
            <input id="ob-s-niche" placeholder="ex : électricien Bretagne, dev fullstack solo, podcast running…" value="${this._esc(cfg.niche || '')}" style="width:100%; padding:10px 14px; border-radius:8px; background: hsl(var(--bg)); color: hsl(var(--text)); border: 1px solid hsl(var(--border)); font-size: 14px;">
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

          <label class="block mb-5">
            <div class="text-[11px] font-bold uppercase tracking-widest text-text-muted mb-2">Max par plateforme</div>
            <input id="ob-s-max" type="number" min="5" max="100" value="${cfg.max_per_platform || 30}" style="width: 120px; padding:9px 12px; border-radius:7px; background: hsl(var(--bg)); color: hsl(var(--text)); border: 1px solid hsl(var(--border)); font-size: 13px;">
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
    const res = await this._api('list_jobs', { limit: 8 });
    const jobs = (res && res.jobs) || [];
    if (jobs.length === 0) { wrap.innerHTML = '<div class="text-[12px] text-text-muted">Aucune recherche pour l\'instant.</div>'; return; }
    wrap.innerHTML = jobs.map(j => {
      const found = (j.stats && j.stats.found) || 0;
      const statusColor = j.status === 'done' ? 'text-success' : j.status === 'failed' ? 'text-danger' : j.status === 'running' ? 'text-warning' : 'text-text-muted';
      const when = j.created_at ? new Date(j.created_at).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' }) : '';
      return `<div class="py-2 border-b border-border last:border-0">
        <div class="text-text font-semibold">${this._esc(j.niche)}</div>
        <div class="flex justify-between mt-1">
          <span class="${statusColor}">${this._esc(j.status)}${found ? ` · ${found} trouvés` : ''}</span>
          <span>${this._esc(when)}</span>
        </div>
      </div>`;
    }).join('');
  },

  async _launchSearch() {
    const niche = document.getElementById('ob-s-niche').value.trim();
    const max   = parseInt(document.getElementById('ob-s-max').value, 10) || 30;
    const platforms = [];
    document.querySelectorAll('[data-ob-plat]:checked').forEach(cb => platforms.push(cb.dataset.obPlat));
    if (!niche)             { alert('Renseigne une niche.'); return; }
    if (!platforms.length)  { alert('Coche au moins une plateforme.'); return; }

    const btn = document.getElementById('ob-s-launch');
    btn.disabled = true; btn.textContent = 'Démarrage…';
    const res = await this._api('start_search', { niche, platforms, max_per_platform: max });
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
