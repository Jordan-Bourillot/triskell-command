/* Chasseur Créateur — vue web pour aller chercher des créateurs de contenu
 * (YouTube / Instagram / Facebook) dans une niche, et récupérer leurs mails
 * publics.
 *
 * UX calquée sur le Chasseur PME (chasseur.js) :
 *   - Colonne gauche : formulaire + historique des chasses
 *   - Colonne droite : détail de la chasse active (stats, progression, table)
 *   - Poll de l'état toutes les 2 secondes pendant la chasse
 */

const ChasseurCreateurs = {
  state: {
    hunts: [],
    currentId: null,
    currentHunt: null,
    pollTimer: null,
  },

  _LS_FORM: 'chasseurc:form',
  _LS_CURRENT: 'chasseurc:currentId',

  _saveForm() {
    try {
      const f = {
        platform: document.getElementById('cc-platform')?.value || 'youtube',
        niche:    document.getElementById('cc-niche')?.value || '',
        min:      document.getElementById('cc-min')?.value || '10000',
        max:      document.getElementById('cc-max')?.value || '1000000',
        num:      document.getElementById('cc-num')?.value || '50',
        apikey:   document.getElementById('cc-apikey')?.value || '',
        iglogin:  document.getElementById('cc-iglogin')?.value || '',
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
    set('cc-platform', f.platform);
    set('cc-niche', f.niche);
    set('cc-min', f.min);
    set('cc-max', f.max);
    set('cc-num', f.num);
    set('cc-apikey', f.apikey);
    set('cc-iglogin', f.iglogin);
    this._togglePlatformFields();
  },

  _bindFormPersist() {
    const root = document.getElementById('cc-form');
    if (!root) return;
    const save = () => this._saveForm();
    root.querySelectorAll('input, select').forEach(el => {
      el.addEventListener('input', save);
      el.addEventListener('change', save);
    });
  },

  _togglePlatformFields() {
    const platform = document.getElementById('cc-platform')?.value || 'youtube';
    const yt = document.getElementById('cc-yt-fields');
    const ig = document.getElementById('cc-ig-fields');
    const fbInfo = document.getElementById('cc-fb-info');
    if (yt) yt.classList.toggle('hidden', platform !== 'youtube');
    if (ig) ig.classList.toggle('hidden', platform !== 'instagram');
    if (fbInfo) fbInfo.classList.toggle('hidden', platform !== 'facebook');
  },

  async _api(method, payload) {
    if (!App.api) return null;
    const fn = App.api['chasseur_createurs_' + method];
    if (typeof fn !== 'function') {
      console.warn('chasseur_createurs_' + method + ' indisponible');
      return null;
    }
    try { return await fn(payload || {}); }
    catch (e) { console.warn('chasseur_createurs.' + method, e); return null; }
  },

  async render(container) {
    this._root = container;
    container.innerHTML = `
      <section class="animate-slide-up">
        <header class="mb-6 sm:mb-8">
          <div class="hero-kicker mb-2" style="color: hsl(var(--accent));">CHASSEUR CRÉATEUR</div>
          <h1 class="hero-title hero-title--md mb-2 sm:mb-3">
            Trouve les créateurs YouTube, Instagram, Facebook — ramène leurs mails.
          </h1>
          <p class="hero-subtitle">
            Choisis une plateforme, une niche, une fourchette d'abonnés. L'app
            parcourt les chaînes, suit les liens de bio (linktree, beacons…),
            et extrait les adresses mail publiques. Tu récupères un CSV prêt
            à exploiter.
          </p>
        </header>

        <div class="grid lg:grid-cols-[360px,1fr] gap-5">
          <!-- Colonne gauche : formulaire + historique -->
          <aside class="space-y-4">
            <div class="card p-4">
              <div class="text-[11px] font-bold tracking-widest text-text-muted mb-3">
                NOUVELLE CHASSE
              </div>
              <form id="cc-form" class="space-y-3">
                <div>
                  <label class="block text-xs font-semibold mb-1">Plateforme</label>
                  <select id="cc-platform" class="w-full input">
                    <option value="youtube">📹 YouTube (recommandé)</option>
                    <option value="instagram">📷 Instagram</option>
                    <option value="facebook">📘 Facebook</option>
                  </select>
                </div>

                <div>
                  <label class="block text-xs font-semibold mb-1">Niche / mots-clés</label>
                  <input id="cc-niche" type="text" class="w-full input"
                         placeholder="ex : cuisine, gaming, fitness…" />
                </div>

                <div class="grid grid-cols-2 gap-2">
                  <div>
                    <label class="block text-xs font-semibold mb-1">Abonnés min</label>
                    <input id="cc-min" type="number" min="0" class="w-full input" value="10000" />
                  </div>
                  <div>
                    <label class="block text-xs font-semibold mb-1">Abonnés max</label>
                    <input id="cc-max" type="number" min="0" class="w-full input" value="1000000" />
                  </div>
                </div>

                <div>
                  <label class="block text-xs font-semibold mb-1">Combien de résultats</label>
                  <select id="cc-num" class="w-full input">
                    <option value="20">20</option>
                    <option value="50" selected>50</option>
                    <option value="100">100</option>
                    <option value="200">200</option>
                  </select>
                </div>

                <!-- Champs spécifiques YouTube -->
                <div id="cc-yt-fields">
                  <label class="block text-xs font-semibold mb-1">
                    Clé API YouTube
                    <span class="text-text-muted font-normal">(facultative)</span>
                  </label>
                  <input id="cc-apikey" type="text" class="w-full input"
                         placeholder="Laisse vide pour utiliser la clé par défaut" />
                  <p class="text-[10.5px] text-text-muted mt-1 leading-snug">
                    Si tu as ta propre clé Google Cloud, colle-la ici. Sinon
                    on utilise la clé partagée (quota limité partagé entre tous).
                  </p>
                </div>

                <!-- Champs spécifiques Instagram -->
                <div id="cc-ig-fields" class="hidden space-y-2">
                  <div>
                    <label class="block text-xs font-semibold mb-1">Login Instagram</label>
                    <input id="cc-iglogin" type="text" class="w-full input"
                           placeholder="ton@compte" autocomplete="off" />
                  </div>
                  <div>
                    <label class="block text-xs font-semibold mb-1">Mot de passe</label>
                    <input id="cc-igpwd" type="password" class="w-full input"
                           placeholder="••••••••" autocomplete="new-password" />
                  </div>
                  <p class="text-[10.5px] text-text-muted leading-snug">
                    ⚠️ Instagram bloque souvent les comptes utilisés pour
                    scraper. Utilise un compte secondaire dédié.
                  </p>
                </div>

                <!-- Disclaimer Facebook -->
                <div id="cc-fb-info" class="hidden text-[10.5px] text-warning bg-warning/10
                                              border border-warning/30 rounded-lg p-2 leading-snug">
                  ⚠️ Facebook bloque presque tout scraping non authentifié.
                  Les résultats peuvent être limités ou vides.
                </div>

                <button type="submit" class="btn btn-primary w-full">
                  <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M12 2l3 6 6 1-4.5 4 1 6L12 16l-5.5 3 1-6L3 9l6-1z"/></svg>
                  Lancer la chasse
                </button>
                <p class="text-[11px] text-text-muted leading-snug">
                  YouTube : ~10-20 sec par créateur. Tu peux fermer cette
                  fenêtre, ça tourne en fond.
                </p>
              </form>
            </div>

            <div class="card p-4">
              <div class="flex items-center justify-between mb-3">
                <div class="text-[11px] font-bold tracking-widest text-text-muted">
                  CHASSES PASSÉES
                </div>
                <button id="cc-refresh-list" class="text-xs text-accent hover:underline">↻</button>
              </div>
              <div id="cc-hunts-list" class="space-y-1.5 max-h-[420px] overflow-y-auto"></div>
            </div>
          </aside>

          <!-- Colonne droite : détail de la chasse active -->
          <div id="cc-detail" class="min-h-[400px]">
            <div class="card p-10 text-center text-text-muted">
              <div class="text-5xl mb-3 opacity-70">🎯</div>
              <div class="text-base">Lance une chasse ou ouvre-en une dans la liste.</div>
            </div>
          </div>
        </div>
      </section>
    `;

    // Bindings
    document.getElementById('cc-form').onsubmit = (e) => {
      e.preventDefault();
      this._launchHunt();
    };
    document.getElementById('cc-platform').onchange = () => {
      this._togglePlatformFields();
      this._saveForm();
    };
    document.getElementById('cc-refresh-list').onclick = () => this._loadHunts();

    // Styles spécifiques (réutilise les patterns de chasseur.js)
    if (!document.getElementById('cc-styles')) {
      const s = document.createElement('style');
      s.id = 'cc-styles';
      s.textContent = `
        #cc-form .input,
        #cc-form input[type="text"],
        #cc-form input[type="number"],
        #cc-form input[type="password"],
        #cc-form select {
          width: 100%;
          padding: 8px 12px;
          background: hsl(var(--surface));
          color: hsl(var(--text));
          border: 1px solid hsl(var(--border-strong));
          border-radius: 8px;
          font-size: 13px;
          transition: border-color 160ms, box-shadow 160ms;
        }
        #cc-form select {
          appearance: none;
          background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%23888' stroke-width='2'><polyline points='6 9 12 15 18 9'/></svg>");
          background-repeat: no-repeat;
          background-position: right 10px center;
          padding-right: 32px;
        }
        #cc-form .input:focus,
        #cc-form input:focus,
        #cc-form select:focus {
          outline: none;
          border-color: hsl(var(--accent));
          box-shadow: 0 0 0 3px hsl(var(--accent) / 0.15);
        }
        #cc-form input::placeholder { color: hsl(var(--text-muted)); }
        #cc-form select option {
          background: hsl(var(--surface));
          color: hsl(var(--text));
        }
        .cc-progress-bar-running {
          background-image: linear-gradient(
            90deg,
            hsl(var(--accent)) 0%,
            hsl(var(--accent) / 0.55) 50%,
            hsl(var(--accent)) 100%
          );
          background-size: 200% 100%;
          animation: cc-progress-shimmer 1.6s linear infinite;
        }
        @keyframes cc-progress-shimmer {
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
    const wrap = document.getElementById('cc-hunts-list');
    if (!wrap) return;
    if (!this.state.hunts.length) {
      wrap.innerHTML = `<div class="text-xs text-text-muted">Aucune chasse pour l'instant.</div>`;
      return;
    }
    wrap.innerHTML = this.state.hunts.map(h => {
      const isActive = h.id === this.state.currentId;
      const stats = h.stats || {};
      const retenus = stats.retenus ?? 0;
      const withMail = stats.avec_mail ?? 0;
      const statusBadge = this._statusBadge(h.status, h.running);
      return `
        <div class="cc-hunt-row group relative rounded-lg border transition-all
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
              ${retenus} retenus · ${withMail} avec mail
            </div>
          </button>
          <button data-del-hunt-id="${h.id}"
                  title="Supprimer cette chasse"
                  class="cc-hunt-del absolute top-1.5 right-1.5 w-6 h-6 rounded-md
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
    if (!confirm('Supprimer définitivement cette chasse ?')) return;
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
      const detail = document.getElementById('cc-detail');
      if (detail) {
        detail.innerHTML = `
          <div class="card p-10 text-center text-text-muted">
            <div class="text-5xl mb-3 opacity-70">🎯</div>
            <div class="text-base">Lance une chasse ou ouvre-en une dans la liste.</div>
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
    const platform = document.getElementById('cc-platform').value;
    const niche = document.getElementById('cc-niche').value.trim();
    const minSubs = parseInt(document.getElementById('cc-min').value, 10) || 0;
    const maxSubs = parseInt(document.getElementById('cc-max').value, 10) || 1_000_000;
    const num = parseInt(document.getElementById('cc-num').value, 10) || 50;

    if (!niche) {
      this._toast('Indique une niche ou un mot-clé.', 'danger');
      return;
    }
    if (maxSubs <= minSubs) {
      this._toast('Le max doit être supérieur au min.', 'danger');
      return;
    }

    const payload = {
      platform, niche, min_subs: minSubs, max_subs: maxSubs, num_results: num,
    };
    if (platform === 'youtube') {
      const k = document.getElementById('cc-apikey').value.trim();
      if (k) payload.youtube_api_key = k;
    } else if (platform === 'instagram') {
      const lo = document.getElementById('cc-iglogin').value.trim();
      const pw = document.getElementById('cc-igpwd')?.value || '';
      if (!lo || !pw) {
        this._toast('Login et mot de passe Instagram requis.', 'danger');
        return;
      }
      payload.instagram_login = lo;
      payload.instagram_password = pw;
    }

    const r = await this._api('start_hunt', payload);
    if (!r || !r.ok) {
      this._toast((r && r.error) || 'Erreur au lancement.', 'danger');
      return;
    }
    this._toast('Chasse lancée. Ça tourne en fond.', 'success');
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
    const wrap = document.getElementById('cc-detail');
    if (!wrap) return;
    const h = this.state.currentHunt;
    if (!h) return;
    const stats = h.stats || {};
    const candidats = stats.candidats ?? 0;
    const traites = stats.traites ?? 0;
    const retenus = stats.retenus ?? 0;
    const withMail = stats.avec_mail ?? 0;
    const isRunning = h.running;
    const isDone = h.status === 'done';
    const creators = h.creators || [];
    const platform = (h.filters && h.filters.platform) || 'youtube';
    const platformIcon = { youtube: '📹', instagram: '📷', facebook: '📘' }[platform] || '🎯';

    wrap.innerHTML = `
      <div class="card p-5 mb-4">
        <div class="flex items-start justify-between gap-3 mb-3">
          <div class="min-w-0 flex-1">
            <div class="text-xs text-text-muted mb-1">${this._fmtDate(h.created_at)}</div>
            <h2 class="text-lg font-bold truncate">${platformIcon} ${this._esc(h.label)}</h2>
          </div>
          <div class="flex items-center gap-2">
            ${this._statusBadge(h.status, isRunning)}
            ${isDone && creators.length > 0 ? `
              <button id="cc-export" class="btn btn-primary" title="Télécharger en CSV">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                Télécharger CSV
              </button>` : ''}
            <button id="cc-delete" class="btn btn-secondary text-xs">Supprimer</button>
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
                : (isDone ? '✅ Chasse terminée' : 'Progression')}
            </span>
            <span class="text-text-muted">${h.progress || 0}%</span>
          </div>
          <div class="h-2.5 rounded-full bg-bg overflow-hidden relative">
            <div class="h-full bg-accent transition-all ${isRunning ? 'cc-progress-bar-running' : ''}"
                 style="width: ${Math.max(h.progress || 0, isRunning ? 3 : 0)}%"></div>
          </div>
        </div>

        <!-- Stats compactes -->
        <div class="grid grid-cols-4 gap-2 text-center">
          ${this._statCell('Candidats', candidats)}
          ${this._statCell('Traités', traites)}
          ${this._statCell('Retenus', retenus)}
          ${this._statCell('Avec mail', withMail, 'success')}
        </div>
      </div>

      ${creators.length ? `
        <div class="card p-0 overflow-hidden">
          <div class="px-4 py-3 border-b border-border text-xs font-semibold text-text-muted
                      flex items-center justify-between">
            <span>${creators.length} créateur${creators.length > 1 ? 's' : ''}</span>
            ${isRunning ? `<span class="text-accent animate-pulse">Chasse en cours…</span>` : ''}
          </div>
          <div class="overflow-x-auto max-h-[520px] overflow-y-auto">
            <table class="w-full text-sm">
              <thead class="bg-bg sticky top-0">
                <tr class="text-left text-[11px] uppercase tracking-wide text-text-muted">
                  <th class="px-3 py-2">Créateur</th>
                  <th class="px-3 py-2">Abonnés</th>
                  <th class="px-3 py-2">Email</th>
                  <th class="px-3 py-2">Liens</th>
                </tr>
              </thead>
              <tbody>
                ${creators.map(c => `
                  <tr class="border-t border-border">
                    <td class="px-3 py-2 font-medium truncate max-w-[260px]" title="${this._esc(c.name)}">
                      <a href="${this._esc(c.url)}" target="_blank" rel="noopener"
                         class="hover:text-accent hover:underline">${this._esc(c.name)}</a>
                    </td>
                    <td class="px-3 py-2 text-text-secondary tabular-nums">
                      ${(c.subscribers || 0).toLocaleString('fr-FR')}
                    </td>
                    <td class="px-3 py-2 ${c.email ? '' : 'text-text-muted italic'}">
                      ${c.email ? `<a href="mailto:${this._esc(c.email)}" class="hover:text-accent hover:underline">${this._esc(c.email)}</a>` : '—'}
                      ${(c.emails_extra && c.emails_extra.length) ? `<div class="text-[10px] text-text-muted mt-0.5">+ ${c.emails_extra.length} autre${c.emails_extra.length > 1 ? 's' : ''}</div>` : ''}
                    </td>
                    <td class="px-3 py-2 text-[11px] text-text-muted">
                      ${(c.external_links && c.external_links.length) ? c.external_links.slice(0, 2).map(l =>
                        `<a href="${this._esc(l)}" target="_blank" rel="noopener" class="text-accent hover:underline block truncate max-w-[180px]">${this._esc(this._shortDomain(l))}</a>`
                      ).join('') : '—'}
                    </td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          </div>
        </div>
      ` : (isRunning ? `
        <div class="card p-10 text-center text-text-muted">
          <div class="text-base">${this._esc(h.log_tail?.[h.log_tail.length - 1] || 'Chasse en cours…')}</div>
        </div>
      ` : '')}

      ${h.log_tail && h.log_tail.length ? `
        <details class="mt-4 text-xs text-text-muted">
          <summary class="cursor-pointer hover:text-text-secondary">Journal de la chasse</summary>
          <pre class="mt-2 p-3 bg-bg rounded-lg overflow-x-auto text-[10.5px]
                      whitespace-pre-wrap leading-relaxed">${this._esc(h.log_tail.join('\n'))}</pre>
        </details>
      ` : ''}
    `;

    const exportBtn = document.getElementById('cc-export');
    if (exportBtn) exportBtn.onclick = () => this._exportCsv();
    const delBtn = document.getElementById('cc-delete');
    if (delBtn) delBtn.onclick = () => this._deleteHunt();
  },

  _statCell(label, value, tone) {
    const color = tone === 'success' ? 'text-success' : 'text-text';
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
        ? `Recherche des créateurs… ${candidats} trouvés`
        : 'Recherche des créateurs sur la plateforme…';
    }
    if (status === 'enriching') {
      if (candidats) return `Extraction des mails — ${traites} / ${candidats}`;
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
    // Déclenche un download côté navigateur
    try {
      const blob = new Blob([r.content], {type: 'text/csv;charset=utf-8'});
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = r.filename || `createurs_${this.state.currentId}.csv`;
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
      console.log('[ChasseurCreateurs]', tone, msg);
    }
  },
};
