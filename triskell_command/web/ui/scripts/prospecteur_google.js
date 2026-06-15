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
    pollFails: 0,
  },

  _LS_FORM: 'prospg:form',
  _LS_CURRENT: 'prospg:currentId',
  _LS_PUSHED: 'prospg:pushed',

  _saveForm() {
    try {
      const f = {
        metier:     document.getElementById('pg-metier')?.value || '',
        zone:       document.getElementById('pg-zone')?.value || '',
        pays:       document.getElementById('pg-pays')?.value || 'FR',
        num:        document.getElementById('pg-num')?.value || '60',
        onlyNoSite: !!document.getElementById('pg-only-nosite')?.checked,
        onlyRedo:   !!document.getElementById('pg-only-redo')?.checked,
        // Note : la clé API n'est volontairement PAS mémorisée dans le
        // navigateur (donnée sensible en clair).
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
    set('pg-pays', f.pays);
    set('pg-num', f.num);
    if (f.onlyNoSite != null) {
      const el = document.getElementById('pg-only-nosite');
      if (el) el.checked = !!f.onlyNoSite;
    }
    if (f.onlyRedo != null) {
      const el = document.getElementById('pg-only-redo');
      if (el) el.checked = !!f.onlyRedo;
    }
  },

  // ---- Mémoire « déjà versé » (côté navigateur) ----

  _pushedMap() {
    try { return JSON.parse(localStorage.getItem(this._LS_PUSHED) || '{}') || {}; }
    catch (e) { return {}; }
  },

  _pushedInfo(huntId) {
    return this._pushedMap()[huntId] || null;
  },

  _markPushed(huntId, quality) {
    try {
      const m = this._pushedMap();
      m[huntId] = { at: new Date().toISOString(), quality: quality || '' };
      localStorage.setItem(this._LS_PUSHED, JSON.stringify(m));
    } catch (e) {}
  },

  /* Transforme le rapport qualité du serveur en phrase française. */
  _qualityToText(q) {
    if (!q || !q.total) return '';
    const labels = {
      no_email: 'sans email',
      bad_email: 'email invalide/fabriqué',
      placeholder_name: 'nom fantôme (test/démo…)',
      duplicate_in_batch: 'doublon dans la fournée',
    };
    const dropped = q.dropped || {};
    const parts = [];
    Object.keys(dropped).forEach(k => {
      if (dropped[k]) parts.push(`${dropped[k]} ${labels[k] || k}`);
    });
    let txt = `🛡️ ${q.kept}/${q.total} fiches gardées`;
    if (parts.length) txt += ` — écartées : ${parts.join(', ')}`;
    return txt;
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
            Finistère…). L'app interroge Google Maps, ramène les coordonnées
            de chaque boîte (nom, adresse, téléphone, site), et lit leur
            site pour en extraire les mails publics. Pratique pour repérer les
            entreprises locales sans site web : cibles idéales Triskell.
          </p>
        </header>
        <div class="mb-4 text-[12px] text-text-muted px-3 py-2 rounded-lg bg-accent/5 border border-accent/20" style="text-wrap: pretty">
          🧭 Outil avancé. Pour le parcours simple (recherche + envoi qui s'enchaînent
          tout seuls), passe par
          <button type="button" class="text-accent underline hover:no-underline" onclick="App.show('prospection')">Lancer une prospection</button>.
        </div>

        <div class="grid lg:grid-cols-[360px,1fr] gap-5">
          <!-- Colonne gauche -->
          <aside class="space-y-4">
            <div class="card p-4">
              <div class="text-[11px] font-bold tracking-widest text-text-muted mb-3">
                NOUVELLE RECHERCHE
              </div>
              <form id="pg-form" class="space-y-3">
                <div>
                  <label for="pg-metier" class="block text-xs font-semibold mb-1">Métier / type d'entreprise</label>
                  <input id="pg-metier" type="text" class="w-full input"
                         placeholder="ex : plombier, restaurant, boulanger" />
                </div>

                <div>
                  <label for="pg-zone" class="block text-xs font-semibold mb-1">Zone géographique</label>
                  <input id="pg-zone" type="text" class="w-full input"
                         placeholder="ex : Brest, Finistère, Bretagne" />
                </div>

                <div>
                  <label for="pg-pays" class="block text-xs font-semibold mb-1">Pays / Langue</label>
                  <select id="pg-pays" class="w-full input">
                    <option value="FR" selected>🇫🇷 France</option>
                    <option value="BE">🇧🇪 Belgique</option>
                    <option value="CH">🇨🇭 Suisse</option>
                    <option value="CA">🇨🇦 Québec / Canada FR</option>
                    <option value="LU">🇱🇺 Luxembourg</option>
                    <option value="MC">🇲🇨 Monaco</option>
                    <option value="MA">🇲🇦 Maroc</option>
                    <option value="DZ">🇩🇿 Algérie</option>
                    <option value="TN">🇹🇳 Tunisie</option>
                    <option value="SN">🇸🇳 Sénégal</option>
                    <option value="CI">🇨🇮 Côte d'Ivoire</option>
                    <option value="ALL">🌍 Tous les francophones</option>
                  </select>
                </div>

                <div>
                  <label for="pg-num" class="block text-xs font-semibold mb-1">Nombre de résultats max</label>
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

                <label class="flex items-center gap-2 text-xs text-text-secondary">
                  <input id="pg-only-redo" type="checkbox" />
                  Garder seulement les <b>sites à refaire</b> 🔧 (pas de vrai site, bricolé ou vieux)
                </label>

                <div>
                  <label for="pg-apikey" class="block text-xs font-semibold mb-1">
                    Clé API Google Places
                    <span class="text-text-muted font-normal">(facultative)</span>
                  </label>
                  <input id="pg-apikey" type="text" class="w-full input"
                         placeholder="Laisse vide pour utiliser la clé enregistrée dans Réglages" />
                </div>

                <button type="submit" class="btn btn-primary w-full">
                  <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg>
                  Lancer la recherche
                </button>
                <p class="text-[11px] text-text-muted leading-snug">
                  Compte ~3-5 sec par entreprise (Google + lecture du site).
                  Tu peux fermer la fenêtre, ça tourne en fond.
                </p>
              </form>
            </div>

            <div class="card p-4">
              <div class="flex items-center justify-between mb-3">
                <div class="text-[11px] font-bold tracking-widest text-text-muted">
                  RECHERCHES PASSÉES
                </div>
                <button id="pg-refresh-list" class="text-xs text-accent hover:underline"
                        title="Rafraîchir la liste des recherches"
                        aria-label="Rafraîchir la liste des recherches">↻</button>
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
    document.getElementById('pg-refresh-list').onclick = async () => {
      const ok = await this._loadHunts();
      if (!ok) Toast.error('Impossible de recharger la liste des recherches. Réessaie dans un instant.');
    };

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
          /* Flèche dessinée en currentColor : suit la couleur du texte,
             lisible dans les 3 thèmes (pas de gris codé en dur). */
          background-image:
            linear-gradient(45deg, transparent 50%, currentColor 50%),
            linear-gradient(135deg, currentColor 50%, transparent 50%);
          background-position: calc(100% - 16px) 50%, calc(100% - 11px) 50%;
          background-size: 5px 5px, 5px 5px;
          background-repeat: no-repeat;
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
    if (!r || !r.ok) return false;
    this.state.hunts = r.hunts || [];
    this._renderHuntsList();
    return true;
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
      const statusBadge = this._statusBadge(h.status, h.running, h.error);
      const pushed = this._pushedInfo(h.id);
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
            <div class="text-[11px] text-text-muted">
              ${retenus} retenus · ${sansSite} sans site${pushed ? ' · <span class="text-success-text font-semibold">✓ versé</span>' : ''}
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
    const hunt = this.state.hunts.find(x => x.id === huntId)
      || (this.state.currentId === huntId ? this.state.currentHunt : null);
    const isRunning = !!(hunt && hunt.running);
    const ok = await Dialog.confirm(
      isRunning
        ? 'Cette recherche est EN COURS. La supprimer va l’arrêter et perdre les résultats déjà trouvés. Continuer ?'
        : 'Supprimer définitivement cette recherche et ses résultats ?',
      { title: 'Supprimer la recherche', okLabel: 'Supprimer', cancelLabel: 'Annuler', danger: true }
    );
    if (!ok) return;
    const r = await this._api('delete_hunt', {hunt_id: huntId});
    if (!r || !r.ok) {
      this._toast((r && r.error) || 'Suppression impossible. Réessaie dans un instant.', 'danger');
      return;
    }
    this._toast('Recherche supprimée.', 'success');
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

  _statusBadge(status, running, errMsg) {
    const map = {
      'pending':   {label: 'En file',  color: 'bg-text-muted/15 text-text-muted'},
      'searching': {label: 'Cherche',  color: 'bg-warning/15 text-warning-text'},
      'enriching': {label: 'Mails',    color: 'bg-accent/15 text-accent-text'},
      'done':      {label: 'Fini',     color: 'bg-success/15 text-success-text'},
      'error':     {label: 'Erreur',   color: 'bg-danger/15 text-danger-text'},
    };
    let i = map[status] || {label: status || '?', color: 'bg-text-muted/15 text-text-muted'};
    // Une recherche stoppée par un redémarrage serveur n'est pas une « erreur » :
    // on l'affiche « Interrompue » (les résultats déjà trouvés restent exploitables).
    if (status === 'error' && /interrompue/i.test(String(errMsg || ''))) {
      i = {label: 'Interrompue', color: 'bg-warning/15 text-warning-text'};
    }
    const pulse = running ? 'animate-pulse' : '';
    return `<span class="text-[11px] font-bold px-1.5 py-0.5 rounded ${i.color} ${pulse}">${i.label}</span>`;
  },

  async _launchHunt() {
    const metier = document.getElementById('pg-metier').value.trim();
    const zone = document.getElementById('pg-zone').value.trim();
    const pays = document.getElementById('pg-pays')?.value || 'FR';
    const num = parseInt(document.getElementById('pg-num').value, 10) || 60;
    const onlyNoSite = document.getElementById('pg-only-nosite').checked;
    const onlyRedo = !!document.getElementById('pg-only-redo')?.checked;
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
      metier, zone, pays, num_results: num, only_no_site: onlyNoSite,
      only_redo: onlyRedo,
    };
    if (apiKey) payload.api_key = apiKey;

    // Anti double-clic : un double lancement = double facturation Google Places.
    const launchBtn = document.querySelector('#pg-form button[type="submit"]');
    const prevHtml = launchBtn ? launchBtn.innerHTML : '';
    if (launchBtn) {
      launchBtn.disabled = true;
      launchBtn.innerHTML = '⏳ Lancement…';
    }
    const r = await this._api('start_hunt', payload);
    if (launchBtn) {
      launchBtn.disabled = false;
      launchBtn.innerHTML = prevHtml;
    }
    if (!r || !r.ok) {
      // Le serveur explique son refus en français (ex : clé Google Places
      // manquante dans Réglages) — on lui laisse la parole.
      if (r && r.error) this._toast(r.error, 'danger');
      else Toast.friendlyError(null, 'Lancement impossible : le serveur ne répond pas. Réessaie dans un instant.');
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
    this.state.pollFails = 0;
    // App.viewInterval : nettoyé automatiquement quand on quitte la vue.
    this.state.pollTimer = App.viewInterval(() => this._refreshDetail(), 2000);
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
    if (!r || !r.ok) {
      // 3 échecs d'affilée → on arrête de marteler le serveur et on explique.
      this.state.pollFails = (this.state.pollFails || 0) + 1;
      if (this.state.pollFails >= 3 && this.state.pollTimer) {
        this._stopPolling();
        Toast.warn('Le suivi en direct est suspendu : le serveur ne répond plus. Rouvre la recherche (ou clique ↻) pour réessayer.');
      }
      return;
    }
    this.state.pollFails = 0;
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

    // Le re-render arrive toutes les 2 s pendant la recherche : on mémorise
    // ce que l'utilisateur regarde (position du tableau, journal ouvert)
    // pour le restaurer après, sinon tout saute à chaque rafraîchissement.
    const prevScroller = wrap.querySelector('.pg-table-scroll');
    const prevScrollTop = prevScroller ? prevScroller.scrollTop : null;
    const prevScrollLeft = prevScroller ? prevScroller.scrollLeft : 0;
    const prevJournal = wrap.querySelector('#pg-journal');
    const journalWasOpen = prevJournal ? prevJournal.open : false;

    const stats = h.stats || {};
    const candidats = stats.candidats ?? 0;
    const traites = stats.traites ?? 0;
    const retenus = stats.retenus ?? 0;
    const withMail = stats.avec_mail ?? 0;
    const sansSite = stats.sans_site ?? 0;
    const isRunning = h.running;
    const isDone = h.status === 'done';
    const prospects = h.prospects || [];
    // Recherche interrompue (statut erreur) : si des résultats existent,
    // ils restent exploitables → exports et versement disponibles.
    const hasResults = !isRunning && prospects.length > 0;
    const onlyNoSite = !!(h.filters && h.filters.only_no_site);
    const pushed = this._pushedInfo(h.id);

    wrap.innerHTML = `
      <div class="card p-5 mb-4">
        <div class="flex items-start justify-between gap-3 mb-3">
          <div class="min-w-0 flex-1">
            <div class="text-xs text-text-muted mb-1">${this._fmtDate(h.created_at)}</div>
            <h2 class="text-lg font-bold truncate">📍 ${this._esc(h.label)}</h2>
          </div>
          <div class="flex items-center gap-2 flex-wrap justify-end">
            ${this._statusBadge(h.status, isRunning, h.error)}
            ${hasResults ? `
              ${withMail > 0 ? `
              <button id="pg-push" class="btn btn-primary"
                      title="Ajouter les entreprises avec mail à la base Tous les prospects (exploitable par l'Auto-pilote)">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><line x1="19" y1="8" x2="19" y2="14"/><line x1="22" y1="11" x2="16" y2="11"/></svg>
                Ajouter à ma base de prospects
              </button>` : ''}
              <button id="pg-export-xlsx" class="btn btn-secondary" title="Télécharger en Excel (.xlsx)">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="8" y1="13" x2="16" y2="13"/><line x1="8" y1="17" x2="16" y2="17"/></svg>
                Excel
              </button>
              <button id="pg-export" class="btn btn-secondary" title="Télécharger en CSV">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                CSV
              </button>` : ''}
            <button id="pg-delete" class="btn btn-secondary text-xs">Supprimer</button>
          </div>
        </div>

        ${pushed ? `
          <div class="text-[11px] text-success-text font-semibold mb-2 text-right">
            ✓ Déjà versé dans « Tous les prospects »${pushed.at ? ` (${this._fmtDate(pushed.at)})` : ''}${pushed.quality ? ` — ${this._esc(pushed.quality)}` : ''}
          </div>` : ''}

        ${h.error ? `
          <div class="rounded-lg bg-danger/10 border border-danger/30 text-danger-text
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

        <!-- Stats compactes (2 colonnes sur mobile, 5 sur grand écran) -->
        <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2 text-center">
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
          <div class="pg-table-scroll overflow-x-auto max-h-[520px] overflow-y-auto">
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
                      <div class="text-[11px] text-text-muted truncate" title="${this._esc(p.address)}">${this._esc(p.address)}</div>
                    </td>
                    <td class="px-3 py-2 text-text-secondary tabular-nums whitespace-nowrap">
                      ${p.phone ? `<a href="tel:${this._esc(p.phone)}" class="hover:text-accent hover:underline">${this._esc(p.phone)}</a>` : '<span class="text-text-muted">—</span>'}
                    </td>
                    <td class="px-3 py-2 ${p.email ? '' : 'text-text-muted italic'}">
                      ${p.email ? `<a href="mailto:${this._esc(p.email)}" class="hover:text-accent hover:underline">${this._esc(p.email)}</a>` : '—'}
                      ${(p.emails_extra && p.emails_extra.length) ? `<div class="text-[11px] text-text-muted mt-0.5">+ ${p.emails_extra.length} autre${p.emails_extra.length > 1 ? 's' : ''}</div>` : ''}
                    </td>
                    <td class="px-3 py-2">
                      ${p.has_website
                        ? `<a href="${this._esc(p.website)}" target="_blank" rel="noopener"
                              class="text-accent hover:underline truncate inline-block max-w-[180px]">${this._esc(this._shortDomain(p.website))}</a>`
                        : `<span class="inline-block px-2 py-0.5 rounded bg-warning/10 text-warning-text text-[11px] font-semibold">pas de site</span>`}
                    </td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          </div>
        </div>
      ` : ((isRunning || h.status === 'pending') ? `
        <div class="card p-10 text-center text-text-muted">
          <div class="text-base">${this._esc(h.log_tail?.[h.log_tail.length - 1] || 'Recherche en cours…')}</div>
        </div>
      ` : `
        <div class="card p-10 text-center text-text-muted">
          <div class="text-3xl mb-2 opacity-70">🪹</div>
          <div class="text-base">Rien trouvé. Essaie un autre métier, une autre zone, ou retire le filtre « sans site web ».</div>
        </div>
      `)}

      ${h.log_tail && h.log_tail.length ? `
        <details id="pg-journal" class="mt-4 text-xs text-text-muted">
          <summary class="cursor-pointer hover:text-text-secondary">Journal de la recherche</summary>
          <pre class="mt-2 p-3 bg-bg rounded-lg overflow-x-auto text-[11px]
                      whitespace-pre-wrap leading-relaxed">${this._esc(h.log_tail.join('\n'))}</pre>
        </details>
      ` : ''}
    `;

    // Restaure ce que l'utilisateur regardait avant le re-render.
    const scroller = wrap.querySelector('.pg-table-scroll');
    if (scroller && prevScrollTop != null) {
      scroller.scrollTop = prevScrollTop;
      scroller.scrollLeft = prevScrollLeft;
    }
    const journal = wrap.querySelector('#pg-journal');
    if (journal && journalWasOpen) journal.open = true;

    const exportBtn = document.getElementById('pg-export');
    if (exportBtn) exportBtn.onclick = () => this._exportCsv();
    const exportXlsxBtn = document.getElementById('pg-export-xlsx');
    if (exportXlsxBtn) exportXlsxBtn.onclick = () => this._exportXlsx();
    const pushBtn = document.getElementById('pg-push');
    if (pushBtn) pushBtn.onclick = () => this._pushToProspects();
    const delBtn = document.getElementById('pg-delete');
    if (delBtn) delBtn.onclick = () => this._deleteHunt();
  },

  _statCell(label, value, tone) {
    const color = tone === 'success' ? 'text-success-text'
                : tone === 'warning' ? 'text-warning-text'
                : 'text-text';
    return `
      <div class="rounded-lg bg-bg p-2.5">
        <div class="text-[11px] uppercase tracking-wide text-text-muted">${label}</div>
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
      if (candidats) return `Lecture des sites — ${traites} / ${candidats}`;
      return 'Extraction des mails…';
    }
    return 'Travail en cours…';
  },

  async _pushToProspects() {
    if (!this.state.currentId) return;
    const h = this.state.currentHunt;
    const withMail = (h?.stats?.avec_mail) || 0;
    if (!withMail) {
      this._toast('Aucune entreprise avec mail à ajouter.', 'danger');
      return;
    }
    const ok = await Dialog.confirm(
      `Ajouter ${withMail} entreprise${withMail > 1 ? 's' : ''} à « Tous les prospects » ? ` +
      `Les doublons sont fusionnés automatiquement, et l'Auto-pilote pourra leur écrire.`,
      { title: 'Ajouter à ta base de prospects', okLabel: 'Ajouter', cancelLabel: 'Annuler' }
    );
    if (!ok) return;
    const btn = document.getElementById('pg-push');
    if (btn) { btn.disabled = true; btn.textContent = 'Ajout…'; }
    const r = await this._api('push_to_prospects', {hunt_id: this.state.currentId});
    if (btn) btn.disabled = false;
    if (!r || !r.ok) {
      this._toast((r && r.error) || 'Ajout impossible. Réessaie dans un instant.', 'danger');
      this._renderDetail();
      return;
    }
    // Rapport du contrôle qualité renvoyé par le serveur
    // (« 🛡️ X/Y fiches gardées — écartées : … »).
    const qualityTxt = this._qualityToText(r.quality);
    this._markPushed(this.state.currentId, qualityTxt);
    this._toast(
      `${r.pushed} entreprise${r.pushed > 1 ? 's' : ''} ajoutée${r.pushed > 1 ? 's' : ''} ` +
      `à la base — ${r.created} nouvelle${r.created > 1 ? 's' : ''}, ` +
      `${r.merged} fusionnée${r.merged > 1 ? 's' : ''}.`,
      'success'
    );
    if (qualityTxt) Toast.info(qualityTxt, 'Contrôle qualité');
    this._renderDetail();
    this._renderHuntsList();
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

  async _exportXlsx() {
    if (!this.state.currentId) return;
    const r = await this._api('download_xlsx', {hunt_id: this.state.currentId});
    if (!r || !r.ok) {
      this._toast((r && r.error) || 'Export Excel impossible', 'danger');
      return;
    }
    try {
      const binary = atob(r.content_b64);
      const bytes = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
      const blob = new Blob([bytes], {
        type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = r.filename || `prospects_google_${this.state.currentId}.xlsx`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      this._toast(`Excel exporté — ${r.rows} lignes`, 'success');
    } catch (e) {
      console.warn('XLSX download:', e);
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
    // Mappe nos tons internes vers les types du Toast global
    // (avant : on passait une string à la place des options → tout muet).
    const type = tone === 'danger' ? 'error'
               : (tone === 'success' || tone === 'warn' || tone === 'info') ? tone
               : 'info';
    if (typeof Toast !== 'undefined' && Toast.show) {
      Toast.show(msg, { type });
    } else {
      console.log('[ProspecteurGoogle]', type, msg);
    }
  },
};
