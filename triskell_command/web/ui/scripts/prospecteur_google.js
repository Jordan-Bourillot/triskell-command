/* Prospecteur Google Places — vue web pour trouver des entreprises locales
 * via Google Maps (un métier + une zone) puis récupérer les mails publics
 * en scrapant leurs sites.
 *
 * UX calquée sur le Chasseur Créateur (et le Chasseur PME) :
 *   - Colonne gauche : formulaire + historique des recherches
 *   - Colonne droite : détail de la chasse active (stats, progression, table)
 *   - Poll de l'état toutes les 2 secondes pendant la chasse
 */

const ProspecteurGoogle = {
  state: {
    hunts: [],
    currentId: null,
    currentHunt: null,
    pollTimer: null,
  },

  _LS_FORM: 'prospg:form',
  _LS_CURRENT: 'prospg:currentId',

  _saveForm() {
    try {
      const f = {
        metier:     document.getElementById('pg-metier')?.value || '',
        zone:       document.getElementById('pg-zone')?.value || '',
        num:        document.getElementById('pg-num')?.value || '60',
        onlyNoSite: !!document.getElementById('pg-only-nosite')?.checked,
        apikey:     document.getElementById('pg-apikey')?.value || '',
      };
      localStorage.setItem(this._LS_FORM, JSON.stringify(f));
    } catch (e) {}
  },

  _readForm() {
    try { return JSON.parse(localStorage.getItem(this._LS_FORM) || 'null'); }
    catch (e) { return null; }
  },

  _applyForm() {
    const f = this._readForm();
    if (!f) return;
    const set = (id, v) => { const el = document.getElementById(id); if (el != null && v != null) el.value = v; };
    set('pg-metier', f.metier);
    set('pg-zone', f.zone);
    set('pg-num', f.num);
    set('pg-apikey', f.apikey);
    if (f.onlyNoSite != null) {
      const el = document.getElementById('pg-only-nosite');
      if (el) el.checked = !!f.onlyNoSite;
    }
  },

  _bindFormPersist() {
    const root = document.getElementById('pg-form');
    if (!root) return;
    const save = () => this._saveForm();
    root.querySelectorAll('input, select').forEach(el => {
      el.addEventListener('input', save);
      el.addEventListener('change', save);
    });
  },

  async _api(method, payload) {
    if (!App.api) return null;
    const fn = App.api['prospecteur_google_' + method];
    if (typeof fn !== 'function') {
      console.warn('prospecteur_google_' + method + ' indisponible');
      return null;
    }
    try { return await fn(payload || {}); }
    catch (e) { console.warn('prospecteur_google.' + method, e); return null; }
  },

  async render(container) {
    this._root = container;
    container.innerHTML = `
      <section class="animate-slide-up">
        <header class="mb-6 sm:mb-8">
          <div class="hero-kicker mb-2" style="color: hsl(var(--accent));">PROSPECTEUR GOOGLE</div>
          <h1 class="hero-title hero-title--md mb-2 sm:mb-3">
            Trouve les entreprises sur Google Maps — repère celles sans site web.
          </h1>
          <p class="hero-subtitle">
            Choisis un métier (plombier, restaurant…) et une zone (Brest,
            Finistère…). L'app interroge Google Places, ramène les coordonnées
            de chaque boîte (nom, adresse, téléphone, site), et scrape leur
            site pour extraire les mails publics. Pratique pour repérer les
            entreprises locales sans site web : cibles idéales Triskell.
          </p>
        </header>

        <div class="grid lg:grid-cols-[360px,1fr] gap-5">
          <!-- Colonne gauche -->
          <aside class="space-y-4">
            <div class="card p-4">
              <div class="text-[11px] font-bold tracking-widest text-text-muted mb-3">
                NOUVELLE RECHERCHE
              </div>
              <form id="pg-form" class="space-y-3">
                <div>
                  <label class="block text-xs font-semibold mb-1">Métier / type d'entreprise</label>
                  <input id="pg-metier" type="text" class="w-full input"
                         placeholder="ex : plombier, restaurant, boulanger" />
                </div>

                <div>
                  <label class="block text-xs font-semibold mb-1">Zone géographique</label>
                  <input id="pg-zone" type="text" class="w-full input"
                         placeholder="ex : Brest, Finistère, Bretagne" />
                </div>

                <div>
                  <label class="block text-xs font-semibold mb-1">Nombre de résultats max</label>
                  <select id="pg-num" class="w-full input">
                    <option value="20">20</option>
                    <option value="40">40</option>
                    <option value="60" selected>60</option>
                    <option value="100">100</option>
                    <option value="200">200</option>
                  </select>
                </div>

                <label class="flex items-center gap-2 text-xs text-text-secondary">
                  <input id="pg-only-nosite" type="checkbox" />
                  Garder seulement les entreprises <b>sans site web</b>
                </label>

                <div>
                  <label class="block text-xs font-semibold mb-1">
                    Clé API Google Places
                    <span class="text-text-muted font-normal">(facultative)</span>
                  </label>
                  <input id="pg-apikey" type="text" class="w-full input"
                         placeholder="Laisse vide pour utiliser la clé par défaut" />
                </div>

                <button type="submit" class="btn btn-primary w-full">
                  <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg>
                  Lancer la recherche
                </button>
                <p class="text-[11px] text-text-muted leading-snug">
                  Compte ~3-5 sec par entreprise (Google + scraping du site).
                  Tu peux fermer la fenêtre, ça tourne en fond.
                </p>
              </form>
            </div>

            <div class="card p-4">
              <div class="flex items-center justify-between mb-3">
                <div class="text-[11px] font-bold tracking-widest text-text-muted">
                  RECHERCHES PASSÉES
                </div>
                <button id="pg-refresh-list" class="text-xs text-accent hover:underline">↻</button>
              </div>
              <div id="pg-hunts-list" class="space-y-1.5 max-h-[420px] overflow-y-auto"></div>
            </div>
          </aside>

          <!-- Colonne droite -->
          <div id="pg-detail" class="min-h-[400px]">
            <div class="card p-10 text-center text-text-muted">
              <div class="text-5xl mb-3 opacity-70">📍</div>
              <div class="text-base">Lance une recherche ou ouvre-en une dans la liste.</div>
            </div>
          </div>
        </div>
      </section>
    `;

    document.getElementById('pg-form').onsubmit = (e) => {
      e.preventDefault();
      this._launchHunt();
    };
    document.getElementById('pg-refresh-list').onclick = () => this._loadHunts();

    if (!document.getElementById('pg-styles')) {
      const s = document.createElement('style');
      s.id = 'pg-styles';
      s.textContent = `
        #pg-form .input,
        #pg-form input[type="text"],
        #pg-form input[type="number"],
        #pg-form select {
          width: 100%;
          padding: 8px 12px;
          background: hsl(var(--surface));
          color: hsl(var(--text));
          border: 1px solid hsl(var(--border-strong));
          border-radius: 8px;
          font-size: 13px;
          transition: border-color 160ms, box-shadow 160ms;
        }
        #pg-form select {
          appearance: none;
          background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%23888' stroke-width='2'><polyline points='6 9 12 15 18 9'/></svg>");
          background-repeat: no-repeat;
          background-position: right 10px center;
          padding-right: 32px;
        }
        #pg-form .input:focus,
        #pg-form input:focus,
        #pg-form select:focus {
          outline: none;
          border-color: hsl(var(--accent));
          box-shadow: 0 0 0 3px hsl(var(--accent) / 0.15);
        }
        #pg-form input::placeholder { color: hsl(var(--text-muted)); }
        #pg-form select option {
          background: hsl(var(--surface));
          color: hsl(var(--text));
        }
        .pg-progress-bar-running {
          background-image: linear-gradient(
            90deg,
            hsl(var(--accent)) 0%,
            hsl(var(--accent) / 0.55) 50%,
            hsl(var(--accent)) 100%
          );
          background-size: 200% 100%;
          animation: pg-progress-shimmer 1.6s linear infinite;
        }
        @keyframes pg-progress-shimmer {
          0%   { background-position: 200% 0; }
          100% { background-position: -200% 0; }
        }
      `;
      document.head.appendChild(s);
    }

    this._applyForm();
    this._bindFormPersist();
    await this._loadHunts();
    if (!this.state.currentId) {
      try { this.state.currentId = localStorage.getItem(this._LS_CURRENT) || null; }
      catch (e) {}
    }
    if (this.state.currentId) this._openHunt(this.state.currentId);
  },

  async _loadHunts() {
    const r = await this._api('list_hunts', {limit: 30});
    if (!r || !r.ok) return;
    this.state.hunts = r.hunts || [];
    this._renderHuntsList();
  },

  _renderHuntsList() {
    const wrap = document.getElementById('pg-hunts-list');
    if (!wrap) return;
    if (!this.state.hunts.length) {
      wrap.innerHTML = `<div class="text-xs text-text-muted">Aucune recherche pour l'instant.</div>`;
      return;
    }
    wrap.innerHTML = this.state.hunts.map(h => {
      const isActive = h.id === this.state.currentId;
      const stats = h.stats || {};
      const retenus = stats.retenus ?? 0;
      const sansSite = stats.sans_site ?? 0;
      const statusBadge = this._statusBadge(h.status, h.running);
      return `
        <div class="pg-hunt-row group relative rounded-lg border transition-all
                    ${isActive
                      ? 'border-accent bg-accent/5'
                      : 'border-border hover:border-border-strong hover:bg-surface'}">
          <button data-hunt-id="${h.id}"
                  class="w-full text-left p-2.5 pr-9">
            <div class="flex items-center justify-between gap-2 mb-1">
              <div class="text-xs font-semibold truncate flex-1">${this._esc(h.label || 'Sans titre')}</div>
              ${statusBadge}
            </div>
            <div class="text-[10px] text-text-muted">
              ${retenus} retenus · ${sansSite} sans site
            </div>
          </button>
          <button data-del-hunt-id="${h.id}"
                  title="Supprimer cette recherche"
                  class="pg-hunt-del absolute top-1.5 right-1.5 w-6 h-6 rounded-md
                         flex items-center justify-center text-text-muted
                         hover:bg-danger/15 hover:text-danger transition-all
                         opacity-0 group-hover:opacity-100 focus:opacity-100">
            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" stroke-width="2.2" viewBox="0 0 24 24">
              <polyline points="3 6 5 6 21 6"/>
              <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>
              <path d="M10 11v6M14 11v6"/>
              <path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/>
            </svg>
          </button>
        </div>
      `;
    }).join('');
    wrap.querySelectorAll('[data-hunt-id]').forEach(btn => {
      btn.onclick = () => this._openHunt(btn.dataset.huntId);
    });
    wrap.querySelectorAll('[data-del-hunt-id]').forEach(btn => {
      btn.onclick = (e) => {
        e.stopPropagation();
        this._deleteHuntById(btn.dataset.delHuntId);
      };
    });
  },

  async _deleteHuntById(huntId) {
    if (!huntId) return;
    if (!confirm('Supprimer définitivement cette recherche ?')) return;
    const r = await this._api('delete_hunt', {hunt_id: huntId});
    if (!r || !r.ok) {
      this._toast('Suppression échouée', 'danger');
      return;
    }
    if (this.state.currentId === huntId) {
      this.state.currentId = null;
      this.state.currentHunt = null;
      try { localStorage.removeItem(this._LS_CURRENT); } catch (e) {}
      this._stopPolling();
      const detail = document.getElementById('pg-detail');
      if (detail) {
        detail.innerHTML = `
          <div class="card p-10 text-center text-text-muted">
            <div class="text-5xl mb-3 opacity-70">📍</div>
            <div class="text-base">Lance une recherche ou ouvre-en une dans la liste.</div>
          </div>
        `;
      }
    }
    await this._loadHunts();
  },

  _statusBadge(status, running) {
    const map = {
      'pending':   {label: 'En file',  color: 'bg-text-muted/15 text-text-muted'},
      'searching': {label: 'Cherche',  color: 'bg-warning/15 text-warning'},
      'enriching': {label: 'Mails',    color: 'bg-accent/15 text-accent'},
      'done':      {label: 'Fini',     color: 'bg-success/15 text-success'},
      'error':     {label: 'Erreur',   color: 'bg-danger/15 text-danger'},
    };
    const i = map[status] || {label: status || '?', color: 'bg-text-muted/15 text-text-muted'};
    const pulse = running ? 'animate-pulse' : '';
    return `<span class="text-[9px] font-bold px-1.5 py-0.5 rounded ${i.color} ${pulse}">${i.label}</span>`;
  },

  async _launchHunt() {
    const metier = document.getElementById('pg-metier').value.trim();
    const zone = document.getElementById('pg-zone').value.trim();
    const num = parseInt(document.getElementById('pg-num').value, 10) || 60;
    const onlyNoSite = document.getElementById('pg-only-nosite').checked;
    const apiKey = document.getElementById('pg-apikey').value.trim();

    if (!metier) {
      this._toast('Indique un métier (plombier, restaurant…).', 'danger');
      return;
    }
    if (!zone) {
      this._toast('Indique une zone (Brest, Finistère…).', 'danger');
      return;
    }

    const payload = {
      metier, zone, num_results: num, only_no_site: onlyNoSite,
    };
    if (apiKey) payload.api_key = apiKey;

    const r = await this._api('start_hunt', payload);
    if (!r || !r.ok) {
      this._toast((r && r.error) || 'Erreur au lancement.', 'danger');
      return;
    }
    this._toast('Recherche lancée. Ça tourne en fond.', 'success');
    await this._loadHunts();
    this._openHunt(r.hunt_id);
  },

  async _openHunt(huntId) {
    this.state.currentId = huntId;
    try { localStorage.setItem(this._LS_CURRENT, huntId || ''); } catch (e) {}
    this._renderHuntsList();
    await this._refreshDetail();
    this._startPolling();
  },

  _startPolling() {
    this._stopPolling();
    this.state.pollTimer = setInterval(() => this._refreshDetail(), 2000);
  },

  _stopPolling() {
    if (this.state.pollTimer) {
      clearInterval(this.state.pollTimer);
      this.state.pollTimer = null;
    }
  },

  async _refreshDetail() {
    if (!this.state.currentId) return;
    const r = await this._api('get_hunt', {hunt_id: this.state.currentId});
    if (!r || !r.ok) return;
    this.state.currentHunt = r.hunt;
    this._renderDetail();
    if (!r.hunt.running && (r.hunt.status === 'done' || r.hunt.status === 'error')) {
      this._stopPolling();
      await this._loadHunts();
    }
  },

  _renderDetail() {
    const wrap = document.getElementById('pg-detail');
    if (!wrap) return;
    const h = this.state.currentHunt;
    if (!h) return;
    const stats = h.stats || {};
    const candidats = stats.candidats ?? 0;
    const traites = stats.traites ?? 0;
    const retenus = stats.retenus ?? 0;
    const withMail = stats.avec_mail ?? 0;
    const sansSite = stats.sans_site ?? 0;
    const isRunning = h.running;
    const isDone = h.status === 'done';
    const prospects = h.prospects || [];
    const onlyNoSite = !!(h.filters && h.filters.only_no_site);

    wrap.innerHTML = `
      <div class="card p-5 mb-4">
        <div class="flex items-start justify-between gap-3 mb-3">
          <div class="min-w-0 flex-1">
            <div class="text-xs text-text-muted mb-1">${this._fmtDate(h.created_at)}</div>
            <h2 class="text-lg font-bold truncate">📍 ${this._esc(h.label)}</h2>
          </div>
          <div class="flex items-center gap-2">
            ${this._statusBadge(h.status, isRunning)}
            ${isDone && prospects.length > 0 ? `
              <button id="pg-export" class="btn btn-primary" title="Télécharger en CSV">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                Télécharger CSV
              </button>` : ''}
            <button id="pg-delete" class="btn btn-secondary text-xs">Supprimer</button>
          </div>
        </div>

        ${h.error ? `
          <div class="rounded-lg bg-danger/10 border border-danger/30 text-danger
                      text-sm p-3 mb-3">⚠️ ${this._esc(h.error)}</div>` : ''}

        <!-- Barre de progression -->
        <div class="mb-3">
          <div class="flex justify-between items-center text-xs mb-1">
            <span class="${isRunning ? 'text-accent font-semibold' : 'text-text-muted'}">
              ${isRunning
                ? this._currentStepLabel(h, candidats, traites)
                : (isDone ? '✅ Recherche terminée' : 'Progression')}
            </span>
            <span class="text-text-muted">${h.progress || 0}%</span>
          </div>
          <div class="h-2.5 rounded-full bg-bg overflow-hidden relative">
            <div class="h-full bg-accent transition-all ${isRunning ? 'pg-progress-bar-running' : ''}"
                 style="width: ${Math.max(h.progress || 0, isRunning ? 3 : 0)}%"></div>
          </div>
        </div>

        <!-- Stats compactes -->
        <div class="grid grid-cols-5 gap-2 text-center">
          ${this._statCell('Candidats', candidats)}
          ${this._statCell('Traités', traites)}
          ${this._statCell('Retenus', retenus)}
          ${this._statCell('Avec mail', withMail, 'success')}
          ${this._statCell('Sans site', sansSite, 'warning')}
        </div>
        ${onlyNoSite ? `
          <div class="mt-3 text-[11px] text-text-muted leading-snug">
            🎯 Filtre actif : <b>uniquement les entreprises sans site web</b>.
          </div>` : ''}
      </div>

      ${prospects.length ? `
        <div class="card p-0 overflow-hidden">
          <div class="px-4 py-3 border-b border-border text-xs font-semibold text-text-muted
                      flex items-center justify-between">
            <span>${prospects.length} entreprise${prospects.length > 1 ? 's' : ''}</span>
            ${isRunning ? `<span class="text-accent animate-pulse">Recherche en cours…</span>` : ''}
          </div>
          <div class="overflow-x-auto max-h-[520px] overflow-y-auto">
            <table class="w-full text-sm">
              <thead class="bg-bg sticky top-0">
                <tr class="text-left text-[11px] uppercase tracking-wide text-text-muted">
                  <th class="px-3 py-2">Entreprise</th>
                  <th class="px-3 py-2">Téléphone</th>
                  <th class="px-3 py-2">Email</th>
                  <th class="px-3 py-2">Site</th>
                </tr>
              </thead>
              <tbody>
                ${prospects.map(p => `
                  <tr class="border-t border-border">
                    <td class="px-3 py-2 max-w-[280px]">
                      <div class="font-medium truncate" title="${this._esc(p.name)}">${this._esc(p.name)}</div>
                      <div class="text-[10.5px] text-text-muted truncate" title="${this._esc(p.address)}">${this._esc(p.address)}</div>
                    </td>
                    <td class="px-3 py-2 text-text-secondary tabular-nums whitespace-nowrap">
                      ${p.phone ? `<a href="tel:${this._esc(p.phone)}" class="hover:text-accent hover:underline">${this._esc(p.phone)}</a>` : '<span class="text-text-muted">—</span>'}
                    </td>
                    <td class="px-3 py-2 ${p.email ? '' : 'text-text-muted italic'}">
                      ${p.email ? `<a href="mailto:${this._esc(p.email)}" class="hover:text-accent hover:underline">${this._esc(p.email)}</a>` : '—'}
                      ${(p.emails_extra && p.emails_extra.length) ? `<div class="text-[10px] text-text-muted mt-0.5">+ ${p.emails_extra.length} autre${p.emails_extra.length > 1 ? 's' : ''}</div>` : ''}
                    </td>
                    <td class="px-3 py-2">
                      ${p.has_website
                        ? `<a href="${this._esc(p.website)}" target="_blank" rel="noopener"
                              class="text-accent hover:underline truncate inline-block max-w-[180px]">${this._esc(this._shortDomain(p.website))}</a>`
                        : `<span class="inline-block px-2 py-0.5 rounded bg-warning/10 text-warning text-[10.5px] font-semibold">pas de site</span>`}
                    </td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          </div>
        </div>
      ` : (isRunning ? `
        <div class="card p-10 text-center text-text-muted">
          <div class="text-base">${this._esc(h.log_tail?.[h.log_tail.length - 1] || 'Recherche en cours…')}</div>
        </div>
      ` : '')}

      ${h.log_tail && h.log_tail.length ? `
        <details class="mt-4 text-xs text-text-muted">
          <summary class="cursor-pointer hover:text-text-secondary">Journal de la recherche</summary>
          <pre class="mt-2 p-3 bg-bg rounded-lg overflow-x-auto text-[10.5px]
                      whitespace-pre-wrap leading-relaxed">${this._esc(h.log_tail.join('\n'))}</pre>
        </details>
      ` : ''}
    `;

    const exportBtn = document.getElementById('pg-export');
    if (exportBtn) exportBtn.onclick = () => this._exportCsv();
    const delBtn = document.getElementById('pg-delete');
    if (delBtn) delBtn.onclick = () => this._deleteHunt();
  },

  _statCell(label, value, tone) {
    const color = tone === 'success' ? 'text-success'
                : tone === 'warning' ? 'text-warning'
                : 'text-text';
    return `
      <div class="rounded-lg bg-bg p-2.5">
        <div class="text-[10px] uppercase tracking-wide text-text-muted">${label}</div>
        <div class="text-lg font-bold ${color}">${value}</div>
      </div>
    `;
  },

  _currentStepLabel(h, candidats, traites) {
    const status = h.status;
    if (status === 'pending') return 'En attente du démarrage…';
    if (status === 'searching') {
      return candidats
        ? `Recherche Google Places… ${candidats} entreprises trouvées`
        : 'Recherche dans Google Places…';
    }
    if (status === 'enriching') {
      if (candidats) return `Scraping des sites — ${traites} / ${candidats}`;
      return 'Extraction des mails…';
    }
    return 'Travail en cours…';
  },

  async _exportCsv() {
    if (!this.state.currentId) return;
    const r = await this._api('download_csv', {hunt_id: this.state.currentId});
    if (!r || !r.ok) {
      this._toast((r && r.error) || 'Export impossible', 'danger');
      return;
    }
    try {
      const blob = new Blob([r.content], {type: 'text/csv;charset=utf-8'});
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = r.filename || `prospects_google_${this.state.currentId}.csv`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      this._toast(`CSV exporté — ${r.rows} lignes`, 'success');
    } catch (e) {
      console.warn('CSV download:', e);
      this._toast('Téléchargement bloqué par le navigateur', 'danger');
    }
  },

  async _deleteHunt() {
    if (!this.state.currentId) return;
    await this._deleteHuntById(this.state.currentId);
  },

  // ---- Helpers ----
  _esc(s) {
    if (s == null) return '';
    return String(s).replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
  },

  _shortDomain(url) {
    try {
      const u = new URL(url);
      return u.hostname.replace(/^www\./, '');
    } catch (e) { return url; }
  },

  _fmtDate(iso) {
    if (!iso) return '';
    try {
      const d = new Date(iso);
      return d.toLocaleString('fr-FR', {
        day: '2-digit', month: 'short',
        hour: '2-digit', minute: '2-digit',
      });
    } catch (e) { return iso; }
  },

  _toast(msg, tone) {
    if (typeof Toast !== 'undefined' && Toast.show) {
      Toast.show(msg, tone || 'info');
    } else {
      console.log('[ProspecteurGoogle]', tone, msg);
    }
  },
};
