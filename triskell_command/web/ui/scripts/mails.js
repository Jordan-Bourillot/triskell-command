/* Vue Mails — 3 onglets sur la table email_history.
 *
 *   1. Réponses prospects : entrants identifiés comme réponses à tes mails
 *      sortants (catégorisés par l'IA : intéressé / pas maintenant / refus / etc.)
 *   2. Tous entrants : limité aux réponses prospects pour l'instant — le
 *      worker IMAP ne loggue pas les autres mails. À étendre en phase 2.
 *   3. Tous sortants : tous les mails envoyés par l'app (prospection, suivi
 *      post-vente, kits de livraison, notifs internes).
 *
 * Pour l'instant, le filtre par compte n'est qu'informatif — le worker n'écrit
 * pas encore l'account_id sur chaque event.
 */

const Mails = {
  state: {
    tab: 'reply',         // 'reply' | 'inbound' | 'sent' | 'scheduled'
    accountFilter: '',    // id du compte (vide = tous)
    accounts: [],
    mails: [],
    // Sous-ensemble actuellement AFFICHÉ (résultats de recherche inclus).
    // C'est sur cette liste que travaillent "Tout sélectionner" et la barre
    // de sélection — jamais sur state.mails complet.
    visibleMails: [],
    // Texte de recherche en cours (vidé au changement d'onglet).
    searchQuery: '',
    // Nombre de mails demandés au serveur. L'endpoint ne sait pas paginer
    // par décalage, donc "Charger plus" augmente ce plafond (100 → 300 → 500).
    listLimit: 100,
    lastKnownInboundId: null,  // pour la notif desktop
    notifPollHandle: null,
    // Mails déjà ouverts (lus) : Set d'ids, persisté en localStorage.
    // Utilisé pour distinguer visuellement les mails non encore consultés.
    readIds: null,
    // Mails cochés pour suppression groupée : Set d'ids, vidé à chaque
    // changement d'onglet / rechargement.
    selectedIds: new Set(),
    // Onglet Boîte de réception : afficher les mails automatiques
    // (newsletters, notifs, rapports DMARC...). Caché par défaut, persisté
    // en localStorage. N'affecte que l'onglet 'inbound'.
    showAuto: null,
  },

  READ_STORAGE_KEY: 'triskell.mails.readIds',
  SHOW_AUTO_STORAGE_KEY: 'triskell.mails.showAuto',

  _loadShowAuto() {
    if (this.state.showAuto !== null) return this.state.showAuto;
    try {
      this.state.showAuto = localStorage.getItem(this.SHOW_AUTO_STORAGE_KEY) === '1';
    } catch (_) {
      this.state.showAuto = false;
    }
    return this.state.showAuto;
  },

  _setShowAuto(v) {
    this.state.showAuto = !!v;
    try { localStorage.setItem(this.SHOW_AUTO_STORAGE_KEY, v ? '1' : '0'); } catch (_) {}
  },

  _isAutoMail(m) {
    const s = (m && m.subject) || '';
    return s.startsWith('[AUTO]') || s.startsWith('[BOUNCE]');
  },

  _loadReadIds() {
    if (this.state.readIds) return this.state.readIds;
    try {
      const raw = localStorage.getItem(this.READ_STORAGE_KEY);
      const arr = raw ? JSON.parse(raw) : [];
      this.state.readIds = new Set(Array.isArray(arr) ? arr.map(String) : []);
    } catch (_) {
      this.state.readIds = new Set();
    }
    return this.state.readIds;
  },

  _saveReadIds() {
    try {
      // On plafonne à 5000 ids pour ne pas faire exploser localStorage,
      // en gardant les plus récents (ordre d'ajout via Array.from).
      const arr = Array.from(this.state.readIds || []);
      const trimmed = arr.length > 5000 ? arr.slice(arr.length - 5000) : arr;
      localStorage.setItem(this.READ_STORAGE_KEY, JSON.stringify(trimmed));
    } catch (_) {}
  },

  _markRead(id) {
    const set = this._loadReadIds();
    const sid = String(id);
    if (set.has(sid)) return;
    set.add(sid);
    this._saveReadIds();
    // Côté serveur aussi (partagé entre appareils) — en arrière-plan :
    // si l'appel rate, la mémoire locale couvre cet appareil en attendant.
    if (App.api && App.api.mail_mark_read) {
      App.api.mail_mark_read({ id: sid }).catch(() => {});
    }
  },

  // Lu si le serveur le dit (extra.read_at, partagé entre appareils)
  // OU si la mémoire locale de cet appareil le dit (héritage + secours).
  _isRead(id, mail) {
    if (mail && mail.extra && mail.extra.read_at) return true;
    return this._loadReadIds().has(String(id));
  },

  // ----------------------------------------------------------------------
  // Brouillons du composeur : LISTE de brouillons (clé 'tc-mail-drafts',
  // tableau {id, ts, to, subject, body_text, body_html, …}, max 10).
  // L'ancienne clé unique 'tc-mail-draft' est migrée automatiquement
  // en premier brouillon à la première lecture.
  // ----------------------------------------------------------------------
  DRAFTS_STORAGE_KEY: 'tc-mail-drafts',
  LEGACY_DRAFT_KEY: 'tc-mail-draft',
  DRAFTS_MAX: 10,
  DRAFT_MAX_AGE_MS: 30 * 24 * 3600 * 1000, // 30 jours

  _draftsLoad() {
    let list = [];
    try {
      const raw = localStorage.getItem(this.DRAFTS_STORAGE_KEY);
      const parsed = raw ? JSON.parse(raw) : [];
      if (Array.isArray(parsed)) list = parsed;
    } catch (_) { list = []; }
    // Migration : ancienne clé unique → premier brouillon de la liste.
    try {
      const legacyRaw = localStorage.getItem(this.LEGACY_DRAFT_KEY);
      if (legacyRaw) {
        const d = JSON.parse(legacyRaw);
        if (d && typeof d === 'object') {
          d.id = d.id || ('d-legacy-' + (d.ts || Date.now()));
          d.ts = d.ts || Date.now();
          if (!list.some(x => x && x.id === d.id)) list.unshift(d);
        }
        localStorage.removeItem(this.LEGACY_DRAFT_KEY);
        this._draftsPersist(list);
      }
    } catch (_) {
      try { localStorage.removeItem(this.LEGACY_DRAFT_KEY); } catch (_) {}
    }
    // Nettoyage : brouillons trop vieux (> 30 jours) ou malformés.
    const now = Date.now();
    const fresh = list.filter(d => d && d.id && (now - (d.ts || 0)) < this.DRAFT_MAX_AGE_MS);
    fresh.sort((a, b) => (b.ts || 0) - (a.ts || 0));
    if (fresh.length !== list.length) this._draftsPersist(fresh);
    return fresh;
  },

  _draftsPersist(list) {
    try {
      localStorage.setItem(this.DRAFTS_STORAGE_KEY,
        JSON.stringify((list || []).slice(0, this.DRAFTS_MAX)));
      return true;
    } catch (_) { return false; }
  },

  /** Ajoute ou met à jour UN brouillon (par id), sans toucher aux autres. */
  _draftUpsert(d) {
    if (!d || !d.id) return false;
    const list = this._draftsLoad();
    const i = list.findIndex(x => x.id === d.id);
    d.ts = Date.now();
    if (i >= 0) list[i] = d; else list.unshift(d);
    list.sort((a, b) => (b.ts || 0) - (a.ts || 0));
    return this._draftsPersist(list);
  },

  _draftRemove(id) {
    if (!id) return;
    this._draftsPersist(this._draftsLoad().filter(d => d.id !== id));
  },

  async render(container, params) {
    if (params && params.tab && ['inbound', 'reply', 'sent', 'scheduled'].includes(params.tab)) {
      this.state.tab = params.tab;
    }
    // Le champ de recherche repart vide à chaque affichage de la vue :
    // on aligne l'état (sinon un ancien filtre s'appliquerait en silence).
    this.state.searchQuery = '';
    container.innerHTML = `
      <section class="animate-slide-up">
        <div class="mb-5 sm:mb-6 flex flex-col sm:flex-row sm:items-end sm:justify-between gap-3">
          <div class="min-w-0 flex-1">
            <div class="hero-kicker mb-2">MAILS</div>
            <h1 class="hero-title hero-title--md mb-2 sm:mb-3">Tous tes mails, un seul endroit.</h1>
            <p class="hero-subtitle">Boîte de réception, réponses prospects, messages envoyés — filtrables par adresse.</p>
          </div>
          <div class="flex flex-wrap gap-2">
            <button id="m-new" class="btn btn-primary">
              <svg class="w-4 h-4 mr-1.5 inline" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>
              Nouveau mail
            </button>
            <button id="m-prospect" class="btn btn-secondary text-white"
                    style="background: linear-gradient(135deg, hsl(var(--accent-strong)), hsl(var(--accent))); border: 0;"
                    title="Mail de prospection en direct — Claude analyse le site cible et adapte le modèle">
              <svg class="w-4 h-4 mr-1.5 inline" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>
              Prospection en direct
            </button>
            <button id="m-refresh" class="btn btn-secondary">Rafraîchir</button>
          </div>
        </div>

        <div class="flex gap-2 mb-4 border-b border-border overflow-x-auto">
          <button data-mtab="inbound" class="m-tab ${this.state.tab === 'inbound' ? 'is-active' : ''}">Boîte de réception</button>
          <button data-mtab="reply"   class="m-tab ${this.state.tab === 'reply' ? 'is-active' : ''}">Réponses prospects</button>
          <button data-mtab="sent"    class="m-tab ${this.state.tab === 'sent' ? 'is-active' : ''}">Messages envoyés</button>
          <button data-mtab="scheduled" class="m-tab ${this.state.tab === 'scheduled' ? 'is-active' : ''}">Programmés</button>
        </div>

        <div class="flex items-center gap-3 mb-4 flex-wrap">
          <label id="m-account-label" class="text-xs text-text-muted">Compte :</label>
          <select id="m-account-filter" class="px-3 py-1.5 rounded-lg bg-bg border border-border text-sm"
                  title="Filtre indicatif : les mails les plus anciens n'ont pas l'information du compte et seront masqués par ce filtre.">
            <option value="">— Tous —</option>
          </select>
          <button id="m-toggle-auto" class="px-3 py-1.5 rounded-lg bg-bg border border-border text-xs hover:border-accent transition-colors"
                  style="display:none;" title="Notifications, newsletters, rapports DMARC, alertes sécurité…">
          </button>
          <div id="m-search-wrap" class="relative flex-1 min-w-[220px] max-w-md">
            <input id="m-search" type="search" placeholder="Rechercher un mail (sujet, expéditeur, contenu)…"
                   class="w-full pl-9 pr-3 py-1.5 rounded-lg bg-bg border border-border text-sm focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent"/>
            <svg class="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
              <circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
            </svg>
          </div>
          <span id="m-count" class="text-xs text-text-muted ml-auto"></span>
        </div>

        <div id="m-content"></div>
      </section>
    `;

    this._injectStyles();

    document.getElementById('m-refresh').onclick = () => this._load();
    document.getElementById('m-new').onclick = () => this._openComposer({});
    document.getElementById('m-prospect').onclick = () => this._openProspectFlow();

    // Pastille "NEW" sur le bouton Prospection en direct
    if (window.NewBadge) {
      const pBtn = document.getElementById('m-prospect');
      if (pBtn) window.NewBadge.attach(pBtn, 'mails-prospect-v1');
    }
    document.querySelectorAll('[data-mtab]').forEach(btn => {
      btn.onclick = () => this._switchTab(btn.dataset.mtab);
    });
    document.getElementById('m-account-filter').onchange = (e) => {
      this.state.accountFilter = e.target.value;
      this._load();
    };
    document.getElementById('m-toggle-auto').onclick = () => {
      this._setShowAuto(!this._loadShowAuto());
      this._load();
    };
    // Recherche : filtre côté client (debounced)
    const searchInput = document.getElementById('m-search');
    let searchTimer = null;
    searchInput.addEventListener('input', (e) => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => {
        this.state.searchQuery = e.target.value.trim().toLowerCase();
        this._applySearch();
      }, 200);
    });

    await this._loadAccounts();
    await this._load();
  },

  _injectStyles() {
    if (document.getElementById('m-styles')) return;
    const s = document.createElement('style');
    s.id = 'm-styles';
    s.textContent = `
      .m-tab { padding: 10px 18px; font-size: 13px; font-weight: 600;
               color: hsl(var(--text-muted)); border-bottom: 2px solid transparent;
               transition: color 160ms, border-color 160ms;
               flex-shrink: 0; white-space: nowrap; }
      .m-tab:hover { color: hsl(var(--text)); }
      .m-tab.is-active { color: hsl(var(--accent)); border-bottom-color: hsl(var(--accent)); }

      /* Mail non lu : bandeau accent à gauche + texte plus marqué.
         Mail lu : opacité légèrement réduite, plus discret. */
      .mail-row.is-unread { background: hsl(var(--accent) / 0.04); }
      .mail-row.is-unread .mail-row-from,
      .mail-row.is-unread .mail-row-subject { font-weight: 700; color: hsl(var(--text)); }
      .mail-row.is-unread::before {
        content: ''; position: absolute; left: 0; top: 8px; bottom: 8px;
        width: 3px; border-radius: 0 2px 2px 0; background: hsl(var(--accent));
      }
      .mail-row { position: relative; }
      .mail-row:focus-visible { outline: 2px solid hsl(var(--accent) / 0.5); outline-offset: -2px; }
      .mail-row.is-read .mail-row-from,
      .mail-row.is-read .mail-row-subject { color: hsl(var(--text-muted)); font-weight: 500; }
      .mail-row.is-read .mail-row-snippet { color: hsl(var(--text-muted) / 0.8); }

      /* Sélection multiple : ligne mise en surbrillance quand cochée. */
      .mail-row.is-selected { background: hsl(var(--accent) / 0.10) !important; }
      /* Cases à cocher discrètes : on remplace le rendu natif par une
         boîte custom à bordure douce, qui ne s'affirme qu'au survol ou
         une fois cochée. Évite l'effet "pavé blanc" sur fond sombre. */
      .mail-row-checkbox {
        appearance: none; -webkit-appearance: none; -moz-appearance: none;
        width: 15px; height: 15px; flex-shrink: 0; cursor: pointer;
        border: 1.5px solid hsl(var(--border));
        border-radius: 4px;
        background: transparent;
        opacity: 0.55;
        transition: opacity 120ms, border-color 120ms, background 120ms;
        position: relative;
        vertical-align: middle;
      }
      .mail-row:hover .mail-row-checkbox,
      .mail-row-checkbox:hover { opacity: 1; border-color: hsl(var(--accent) / 0.6); }
      /* La case "Tout sélectionner" est isolée dans la barre d'action,
         pas dans une mail-row : on la garde pleinement visible et avec
         une bordure plus marquée pour qu'elle saute aux yeux. */
      .m-bulkbar .mail-row-checkbox {
        opacity: 1;
        border-color: hsl(var(--accent) / 0.6);
        border-width: 2px;
      }
      .m-bulkbar .mail-row-checkbox:hover { border-color: hsl(var(--accent)); }
      .mail-row-checkbox:checked {
        opacity: 1;
        background: hsl(var(--accent));
        border-color: hsl(var(--accent));
      }
      .mail-row-checkbox:checked::after {
        content: ''; position: absolute;
        left: 3px; top: 0px; width: 5px; height: 9px;
        border: solid white;
        border-width: 0 2px 2px 0;
        transform: rotate(45deg);
      }
      .mail-row-checkbox:focus-visible {
        outline: 2px solid hsl(var(--accent) / 0.5);
        outline-offset: 1px;
      }

      /* Barre d'action de sélection (apparaît quand >0 cochés). */
      .m-bulkbar {
        display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
        padding: 10px 14px; margin-bottom: 10px;
        background: hsl(var(--accent) / 0.08);
        border: 1px solid hsl(var(--accent) / 0.25);
        border-radius: 10px;
        font-size: 13px;
      }
      .m-bulkbar-count { font-weight: 700; color: hsl(var(--accent)); }
      .m-bulkbar-spacer { flex: 1; }
      .m-bulkbar-btn {
        padding: 6px 12px; border-radius: 6px; font-size: 12px; font-weight: 600;
        transition: background 120ms, color 120ms;
      }
      .m-bulkbar-btn-secondary { color: hsl(var(--text)); background: hsl(var(--surface)); border: 1px solid hsl(var(--border)); }
      .m-bulkbar-btn-secondary:hover { background: hsl(var(--bg)); }
      .m-bulkbar-btn-danger { color: white; background: hsl(var(--danger)); }
      .m-bulkbar-btn-danger:hover { filter: brightness(1.08); }
      .m-bulkbar-btn-danger:disabled { opacity: 0.5; cursor: not-allowed; }
    `;
    document.head.appendChild(s);
  },

  _switchTab(tab) {
    this.state.tab = tab;
    this.state.selectedIds = new Set();
    // La recherche est propre à un onglet : on la réinitialise en changeant.
    this.state.searchQuery = '';
    const searchInput = document.getElementById('m-search');
    if (searchInput) searchInput.value = '';
    // On repart du plafond de base (le "Charger plus" est par onglet).
    this.state.listLimit = 100;
    document.querySelectorAll('[data-mtab]').forEach(b => {
      b.classList.toggle('is-active', b.dataset.mtab === tab);
    });
    this._load();
  },

  async _loadAccounts() {
    await this._loadAccountsSilent();
    const sel = document.getElementById('m-account-filter');
    if (!sel) return;
    sel.innerHTML = `<option value="">— Tous —</option>` +
      this.state.accounts.map(a =>
        `<option value="${this._escape(a.id)}">${this._escape(a.label)} (${this._escape(a.from_email)})</option>`
      ).join('');
  },

  async _loadAccountsSilent() {
    if (!App.api) return;
    try {
      const r = await App.api.mail_accounts_list();
      if (r && r.ok) this.state.accounts = r.accounts || [];
    } catch (e) {}
  },

  async _load() {
    const root = document.getElementById('m-content');
    const countEl = document.getElementById('m-count');
    if (!App.api) {
      root.innerHTML = this._noBackend();
      return;
    }
    root.innerHTML = `<div class="card p-6 text-text-muted text-sm">Chargement…</div>`;

    // Filtre compte / bascule notifs auto / recherche : sans objet sur
    // l'onglet "Programmés" (liste à part, côté serveur d'envoi).
    const isScheduledTab = this.state.tab === 'scheduled';
    const accountLabelEl = document.getElementById('m-account-label');
    const accountSelEl = document.getElementById('m-account-filter');
    const searchWrapEl = document.getElementById('m-search-wrap');
    if (accountLabelEl) accountLabelEl.style.display = isScheduledTab ? 'none' : '';
    if (accountSelEl) accountSelEl.style.display = isScheduledTab ? 'none' : '';
    if (searchWrapEl) searchWrapEl.style.display = isScheduledTab ? 'none' : '';
    if (isScheduledTab) {
      const tb = document.getElementById('m-toggle-auto');
      if (tb) tb.style.display = 'none';
      await this._loadScheduled(root, countEl);
      return;
    }

    const kindMap = { reply: 'reply', sent: 'sent', inbound: 'inbound' };
    let r = null;
    try {
      r = await App.api.mails_list({
        kind: kindMap[this.state.tab] || 'all',
        account_id: this.state.accountFilter || '',
        limit: this.state.listLimit || 100,
      });
    } catch (e) {
      console.error('[mails] mails_list', e);
      r = null;
    }
    if (!r || !r.ok) {
      if (r && r.error) console.error('[mails] mails_list :', r.error);
      root.innerHTML = `
        <div class="card p-8 text-center">
          <div class="text-3xl mb-3 opacity-60">⚠</div>
          <p class="text-sm text-text mb-1 font-semibold">Impossible de charger les mails.</p>
          <p class="text-xs text-text-muted mb-4">Vérifie ta connexion puis réessaie.</p>
          <button id="m-retry" class="btn btn-secondary">Réessayer</button>
        </div>`;
      const retryBtn = root.querySelector('#m-retry');
      if (retryBtn) retryBtn.onclick = () => this._load();
      return;
    }
    const allMails = r.mails || [];
    // Liste brute chargée (avant filtre notifs auto) : sert de base à la
    // pagination par décalage (« Charger plus » = page suivante serveur).
    this.state.rawMails = allMails;

    // Bouton bascule "afficher les mails auto" : visible uniquement sur
    // l'onglet Boîte de réception. Met à jour son label + filtre la liste.
    const toggleBtn = document.getElementById('m-toggle-auto');
    let hiddenAutoCount = 0;
    if (this.state.tab === 'inbound') {
      const showAuto = this._loadShowAuto();
      const autoMails = allMails.filter(m => this._isAutoMail(m));
      hiddenAutoCount = showAuto ? 0 : autoMails.length;
      this.state.mails = showAuto ? allMails : allMails.filter(m => !this._isAutoMail(m));
      if (toggleBtn) {
        toggleBtn.style.display = '';
        toggleBtn.textContent = showAuto
          ? `👁 Cacher les notifs auto (${autoMails.length})`
          : `👁‍🗨 Afficher les notifs auto${autoMails.length ? ` (${autoMails.length})` : ''}`;
      }
    } else {
      this.state.mails = allMails;
      if (toggleBtn) toggleBtn.style.display = 'none';
    }

    // Le serveur a-t-il probablement plus de mails que ce qui est chargé ?
    // (la pagination par décalage va chercher la suite — garde-fou à 1000)
    const limit = this.state.listLimit || 100;
    const maybeMore = allMails.length >= limit;
    this.state.hasMore = maybeMore && allMails.length < 1000;
    const recentNote = maybeMore ? ` — les ${allMails.length} plus récents` : '';

    countEl.textContent = (hiddenAutoCount > 0
      ? `${this.state.mails.length} mail(s) — ${hiddenAutoCount} notif(s) auto cachée(s)`
      : `${this.state.mails.length} mail(s)`) + recentNote;

    // Bandeau d'information sur la Boîte de réception : elle ne contient
    // que les réponses liées à la prospection, pas toute la boîte mail.
    const limitedBanner = this.state.tab === 'inbound'
      ? `<div class="mb-3 px-4 py-2.5 rounded-xl border border-border bg-bg text-[11px] text-text-muted">
           ℹ Cette boîte montre les réponses liées à ta prospection — pas toute ta boîte mail.
         </div>`
      : '';

    if (!this.state.mails.length) {
      let hint;
      if (hiddenAutoCount > 0) {
        hint = `<p class="text-text-muted">Aucun mail visible — ${hiddenAutoCount} notif(s) auto cachée(s). Clique sur "Afficher les notifs auto" pour les voir.</p>`;
      } else if (this.state.accountFilter) {
        hint = `<p class="text-text-muted">Aucun mail pour ce compte. Les mails les plus anciens n'ont pas l'information du compte : remets le filtre sur « — Tous — » pour tout voir.</p>`;
      } else if (this.state.tab === 'sent') {
        hint = `<p class="text-text-muted">Aucun mail envoyé pour l'instant. Écris-en un avec « Nouveau mail », ou lance une prospection.</p>`;
      } else if (!this.state.accounts.length) {
        hint = `<p class="text-text-muted">Aucun mail ici. Configure d'abord un compte mail dans les Réglages.</p>`;
      } else {
        hint = `<p class="text-text-muted">Aucun mail dans cette catégorie. Lance une prospection pour recevoir tes premières réponses.</p>`;
      }
      root.innerHTML = limitedBanner + `
        <div class="card p-10 text-center">
          <div class="text-3xl mb-3 opacity-60">∅</div>
          ${hint}
        </div>
      `;
      return;
    }
    this.state.limitedBanner = limitedBanner;
    // Si une recherche est en cours, on délègue à _applySearch (qui filtre)
    if (this.state.searchQuery) {
      this._applySearch();
      return;
    }
    this._renderListAndBulk(root, limitedBanner, this.state.mails);
  },

  // ----------------------------------------------------------------------
  // Onglet "Programmés" : les envois différés (bouton "Plus tard" du
  // composeur). Liste + annulation par ligne.
  // ----------------------------------------------------------------------
  async _loadScheduled(root, countEl) {
    let r = null;
    try {
      r = await App.api.mail_scheduled_list();
    } catch (e) {
      console.error('[mails] mail_scheduled_list', e);
      r = null;
    }
    if (!r || !r.ok) {
      if (r && r.error) console.error('[mails] mail_scheduled_list :', r.error);
      if (countEl) countEl.textContent = '';
      root.innerHTML = `
        <div class="card p-8 text-center">
          <div class="text-3xl mb-3 opacity-60">⚠</div>
          <p class="text-sm text-text mb-1 font-semibold">Impossible de charger les envois programmés.</p>
          <p class="text-xs text-text-muted mb-4">Vérifie ta connexion puis réessaie.</p>
          <button id="m-sched-retry" class="btn btn-secondary">Réessayer</button>
        </div>`;
      const retryBtn = root.querySelector('#m-sched-retry');
      if (retryBtn) retryBtn.onclick = () => this._load();
      return;
    }
    const items = r.mails || [];
    if (countEl) countEl.textContent = `${items.length} envoi(s) programmé(s)`;
    if (!items.length) {
      root.innerHTML = `
        <div class="card p-10 text-center">
          <div class="text-3xl mb-3 opacity-60">🕐</div>
          <p class="text-text-muted">Aucun envoi programmé. Dans « Nouveau mail », le bouton « Plus tard » permet de programmer un envoi à l'heure que tu veux.</p>
        </div>`;
      return;
    }
    root.innerHTML = `
      <div class="mb-3 px-4 py-2.5 rounded-xl border border-border bg-bg text-[11px] text-text-muted">
        ℹ Ces mails partiront automatiquement à l'heure prévue, même si tu fermes l'app. Tu peux encore les annuler.
      </div>
      <div class="space-y-2">
        ${items.map(it => {
          const when = this._fmtDateLong(it.scheduled_at);
          const to = it.to || '(destinataire inconnu)';
          const subject = it.subject || '(sans objet)';
          const preview = (it.body_preview || '').replace(/\s+/g, ' ').trim().slice(0, 120);
          const attCount = Number(it.attachments_count) || 0;
          return `
          <div class="card p-4 flex items-start gap-3 flex-wrap">
            <div class="w-9 h-9 rounded-full bg-accent/15 text-accent flex items-center justify-center shrink-0">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
            </div>
            <div class="flex-1 min-w-0">
              <div class="text-xs font-bold text-accent">Partira le ${this._escape(when)}</div>
              <div class="text-sm font-semibold text-text truncate mt-0.5">${this._escape(subject)}</div>
              <div class="text-xs text-text-muted truncate">À : ${this._escape(to)}${attCount ? ` · ${attCount} pièce(s) jointe(s)` : ''}</div>
              ${preview ? `<div class="text-[11px] text-text-muted/80 truncate mt-1">${this._escape(preview)}</div>` : ''}
            </div>
            <button data-sched-cancel="${this._escape(it.id)}" data-sched-to="${this._escape(to)}"
                    class="m-bulkbar-btn m-bulkbar-btn-secondary shrink-0"
                    title="Annuler cet envoi programmé" aria-label="Annuler cet envoi programmé">
              Annuler
            </button>
          </div>`;
        }).join('')}
      </div>`;
    root.querySelectorAll('[data-sched-cancel]').forEach(btn => {
      btn.onclick = async () => {
        const id = btn.dataset.schedCancel;
        const to = btn.dataset.schedTo || 'ce destinataire';
        const ok = await Dialog.confirm(
          `Annuler l'envoi programmé pour ${to} ? Le mail ne partira pas.`,
          { title: 'Annuler cet envoi', okLabel: "Annuler l'envoi", cancelLabel: 'Le garder', danger: true });
        if (!ok) return;
        btn.disabled = true;
        btn.textContent = 'Annulation…';
        try {
          const r2 = await App.api.mail_scheduled_cancel({ id });
          if (r2 && r2.ok) {
            Toast.success('Envoi annulé — le mail ne partira pas.');
            await this._load();
          } else {
            btn.disabled = false;
            btn.textContent = 'Annuler';
            Toast.error((r2 && r2.error) || 'Ce mail est peut-être déjà parti. Rafraîchis la liste.');
          }
        } catch (e) {
          btn.disabled = false;
          btn.textContent = 'Annuler';
          Toast.friendlyError(e, "Impossible d'annuler cet envoi pour le moment.");
        }
      };
    });
  },

  _renderListAndBulk(root, limitedBanner, mails) {
    const list = mails || this.state.mails || [];
    this.state.visibleMails = list;
    const loadMoreHtml = (this.state.hasMore && !this.state.searchQuery)
      ? `<div class="text-center mt-4">
           <button id="m-load-more" class="btn btn-secondary">Charger plus de mails</button>
         </div>`
      : '';
    root.innerHTML = (limitedBanner || '') + this._renderBulkBar() +
      `<div class="mail-list">${list.map(m => this._mailRow(m)).join('')}</div>` +
      loadMoreHtml;
    this._wireListEvents(root);
    const loadMoreBtn = root.querySelector('#m-load-more');
    if (loadMoreBtn) {
      loadMoreBtn.onclick = () => this._loadMore(loadMoreBtn);
    }
  },

  // Pagination réelle : va chercher les 100 mails SUIVANTS (décalage côté
  // serveur) et les ajoute à la liste — sans re-télécharger ce qui est là.
  async _loadMore(btn) {
    const kindMap = { reply: 'reply', sent: 'sent', inbound: 'inbound' };
    const pageSize = 100;
    const already = (this.state.rawMails || []).length;
    if (btn) { btn.disabled = true; btn.textContent = 'Chargement…'; }
    let r = null;
    try {
      r = await App.api.mails_list({
        kind: kindMap[this.state.tab] || 'all',
        account_id: this.state.accountFilter || '',
        limit: pageSize,
        offset: already,
      });
    } catch (e) {
      console.error('[mails] mails_list (page suivante)', e);
      r = null;
    }
    if (!r || !r.ok) {
      if (btn) { btn.disabled = false; btn.textContent = 'Charger plus de mails'; }
      Toast.friendlyError(r && r.error, 'Impossible de charger la suite. Réessaie dans un instant.');
      return;
    }
    const page = r.mails || [];
    this.state.rawMails = (this.state.rawMails || []).concat(page);
    // « Rafraîchir » et les retours d'action rechargent en UNE requête tout
    // ce qui est affiché : on aligne le plafond sur le volume chargé.
    this.state.listLimit = Math.min(Math.max(this.state.rawMails.length, 100), 1000);
    this.state.hasMore = page.length >= pageSize && this.state.rawMails.length < 1000;
    // Re-filtre (notifs auto sur la Boîte de réception) + re-render
    let hiddenAutoCount = 0;
    if (this.state.tab === 'inbound' && !this._loadShowAuto()) {
      hiddenAutoCount = this.state.rawMails.filter(m => this._isAutoMail(m)).length;
      this.state.mails = this.state.rawMails.filter(m => !this._isAutoMail(m));
    } else {
      this.state.mails = this.state.rawMails;
    }
    const countEl = document.getElementById('m-count');
    if (countEl) {
      const recentNote = this.state.hasMore ? ` — les ${this.state.rawMails.length} plus récents` : '';
      countEl.textContent = (hiddenAutoCount > 0
        ? `${this.state.mails.length} mail(s) — ${hiddenAutoCount} notif(s) auto cachée(s)`
        : `${this.state.mails.length} mail(s)`) + recentNote;
    }
    const root = document.getElementById('m-content');
    if (root) this._renderListAndBulk(root, this.state.limitedBanner || '', this.state.mails);
  },

  _renderBulkBar() {
    const selected = this.state.selectedIds || new Set();
    // La case "Tout sélectionner" porte sur les mails AFFICHÉS (recherche
    // incluse), jamais sur la liste complète.
    const visible = this.state.visibleMails || this.state.mails || [];
    const n = selected.size;
    const allSelected = visible.length > 0 &&
      visible.every(m => selected.has(String(m.id)));
    return `
      <div class="m-bulkbar">
        <label class="flex items-center gap-2 cursor-pointer">
          <input type="checkbox" id="m-bulk-all" class="mail-row-checkbox" ${allSelected ? 'checked' : ''}>
          <span class="text-xs text-text-muted">Tout sélectionner</span>
        </label>
        <span class="m-bulkbar-count">${n} mail${n > 1 ? 's' : ''} sélectionné${n > 1 ? 's' : ''}</span>
        <div class="m-bulkbar-spacer"></div>
        <button id="m-bulk-clear" class="m-bulkbar-btn m-bulkbar-btn-secondary" ${n ? '' : 'disabled style="display:none;"'}>Annuler la sélection</button>
        <button id="m-bulk-delete" class="m-bulkbar-btn m-bulkbar-btn-danger" ${n ? '' : 'disabled'}>
          🗑 Supprimer ${n > 0 ? `(${n})` : ''}
        </button>
      </div>
    `;
  },

  // ----------------------------------------------------------------------
  // Évènements de la liste : DÉLÉGATION. Un seul jeu d'écouteurs est posé
  // sur le conteneur #m-content (une fois par rendu de la vue) — il survit
  // aux innerHTML successifs. Avant, chaque rafraîchissement de la barre de
  // sélection ré-attachait des écouteurs sur les MÊMES lignes : croissance
  // exponentielle → des dizaines de fenêtres de détail empilées.
  // ----------------------------------------------------------------------
  _wireListEvents(root) {
    if (root.dataset.mailsWired === '1') return;
    root.dataset.mailsWired = '1';

    const openRow = (rowEl) => {
      const id = rowEl.dataset.mailOpen;
      const mail = (this.state.mails || []).find(m => String(m.id) === String(id));
      if (!mail) return;
      this._markRead(id);
      rowEl.classList.remove('is-unread');
      rowEl.classList.add('is-read');
      this._openDetail(mail);
    };

    root.addEventListener('click', async (e) => {
      // Boutons de la barre de sélection
      if (e.target.closest('#m-bulk-clear')) {
        this.state.selectedIds = new Set();
        root.querySelectorAll('[data-mail-check]').forEach(cb => { cb.checked = false; });
        root.querySelectorAll('[data-mail-open].is-selected').forEach(row => row.classList.remove('is-selected'));
        this._refreshBulkBar(root);
        return;
      }
      const delBtn = e.target.closest('#m-bulk-delete');
      if (delBtn) {
        const ids = Array.from(this.state.selectedIds || []);
        if (!ids.length || delBtn.disabled) return;
        const ok = await Dialog.confirm(
          `Supprimer ${ids.length} mail${ids.length > 1 ? 's' : ''} de l’historique ? Les messages déjà envoyés ou reçus ne sont pas rappelés, on efface juste la trace côté Triskell.`,
          { title: 'Supprimer la sélection', okLabel: 'Supprimer', cancelLabel: 'Annuler', danger: true });
        if (!ok) return;
        delBtn.disabled = true;
        delBtn.textContent = 'Suppression…';
        try {
          const r = await App.api.mails_delete({ ids });
          if (r && r.ok) {
            this.state.selectedIds = new Set();
            Toast.success(`${ids.length} mail${ids.length > 1 ? 's' : ''} supprimé${ids.length > 1 ? 's' : ''} de l’historique.`);
            await this._load();
          } else {
            this._refreshBulkBar(root); // ré-affiche la barre (bouton réactivé)
            console.error('[mails] mails_delete :', r && r.error);
            Toast.error('La suppression a échoué. Réessaie.');
          }
        } catch (err) {
          this._refreshBulkBar(root);
          Toast.friendlyError(err, 'La suppression a échoué. Réessaie.');
        }
        return;
      }
      // Clic sur une ligne = ouvre le détail (sauf clic sur la case à cocher)
      const row = e.target.closest('[data-mail-open]');
      if (row && !e.target.closest('.mail-row-checkbox-wrap')) openRow(row);
    });

    root.addEventListener('change', (e) => {
      // Case d'une ligne
      const cb = e.target.closest('[data-mail-check]');
      if (cb) {
        const id = String(cb.dataset.mailCheck);
        if (cb.checked) this.state.selectedIds.add(id);
        else this.state.selectedIds.delete(id);
        const row = cb.closest('[data-mail-open]');
        if (row) row.classList.toggle('is-selected', cb.checked);
        this._refreshBulkBar(root);
        return;
      }
      // "Tout sélectionner" : uniquement les mails AFFICHÉS (recherche
      // comprise), mise à jour ciblée des lignes — le filtre reste en place.
      const allBox = e.target.closest('#m-bulk-all');
      if (allBox) {
        const checked = allBox.checked;
        root.querySelectorAll('[data-mail-check]').forEach(boxEl => {
          const id = String(boxEl.dataset.mailCheck);
          boxEl.checked = checked;
          if (checked) this.state.selectedIds.add(id);
          else this.state.selectedIds.delete(id);
          const row = boxEl.closest('[data-mail-open]');
          if (row) row.classList.toggle('is-selected', checked);
        });
        this._refreshBulkBar(root);
      }
    });

    // Clavier : Entrée ou Espace sur une ligne focusée = ouvrir le détail
    root.addEventListener('keydown', (e) => {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      const row = e.target.closest && e.target.closest('[data-mail-open]');
      if (!row || e.target.closest('.mail-row-checkbox-wrap')) return;
      e.preventDefault();
      openRow(row);
    });
  },

  // Ne re-rend QUE la barre de sélection (les écouteurs délégués sur le
  // conteneur restent valides — aucun ré-attachement).
  _refreshBulkBar(root) {
    const bar = root.querySelector('.m-bulkbar');
    if (!bar) return;
    bar.outerHTML = this._renderBulkBar();
  },

  _mailRow(m) {
    const kind = m.kind || '';
    const isReply  = kind === 'reply_received';
    const isInbox  = kind === 'inbox_received';
    const isSent   = kind === 'email_sent';
    const dotColor = isReply ? 'success'
                  : isSent  ? 'accent'
                  : isInbox ? 'gold'
                  : 'text-muted';
    const dotTitle = isReply ? 'Réponse prospect'
                  : isSent  ? 'Mail envoyé'
                  : isInbox ? 'Mail entrant'
                  : kind;
    const fromAddr = (m.extra && m.extra.from) || '';
    const accountId = (m.extra && m.extra.account_id) || '';
    const ts = this._fmtDate(m.ts);
    const subject = m.subject || '(sans objet)';
    const body = (m.body || '').slice(0, 200);
    const bodyExcerpt = body || (m.extra && m.extra.body_excerpt) || '';
    // Affichage compact : expéditeur (ou destinataire si envoyé), sujet, snippet, date.
    const senderRaw = isSent
      ? ((m.extra && m.extra.to) || accountId || '')
      : (fromAddr || accountId || '');
    // Si format "Nom <email>", on prend le nom ; sinon on garde l'adresse.
    const senderMatch = senderRaw.match(/^([^<]+?)\s*<.+>$/);
    const senderName = senderMatch ? senderMatch[1].trim() : senderRaw;
    // Pour les mails envoyés : on affiche AUSSI l'adresse d'expédition
    // (le compte mail qui a envoyé), en sous-ligne discrète sous le
    // destinataire — utile quand on a plusieurs comptes mails.
    let sentFromEmail = '';
    if (isSent) {
      const accountFrom = (this.state.accounts.find(a => a.id === accountId) || {}).from_email || '';
      const fromMatch = fromAddr.match(/<([^>]+)>/);
      const fromEmailOnly = fromMatch ? fromMatch[1].trim() : fromAddr;
      sentFromEmail = (accountFrom || fromEmailOnly || '').trim();
    }
    const snippet = (bodyExcerpt || '').replace(/\s+/g, ' ').trim();
    const idStr = String(m.id);
    const isRead = this._isRead(idStr, m);
    const isSelected = this.state.selectedIds && this.state.selectedIds.has(idStr);
    const stateClass = `${isRead ? 'is-read' : 'is-unread'}${isSelected ? ' is-selected' : ''}`;
    const fromCellInner = sentFromEmail
      ? `
        <span class="mail-row-from-main">${this._escape(senderName || '—')}</span>
        <span class="mail-row-from-sub" title="${this._escape(sentFromEmail)}">depuis ${this._escape(sentFromEmail)}</span>`
      : this._escape(senderName || '—');
    const fromCellClass = sentFromEmail ? 'mail-row-from is-stacked' : 'mail-row-from';
    return `
      <div class="mail-row ${stateClass}" data-mail-open="${this._escape(m.id)}"
           role="button" tabindex="0" aria-label="Ouvrir le mail : ${this._escape(subject)}">
        <label class="mail-row-checkbox-wrap flex items-center" onclick="event.stopPropagation()">
          <input type="checkbox" class="mail-row-checkbox" data-mail-check="${this._escape(m.id)}" ${isSelected ? 'checked' : ''}>
        </label>
        <span class="mail-row-dot" style="background: hsl(var(--${dotColor}))" title="${dotTitle}"></span>
        <div class="${fromCellClass}" title="${this._escape(senderRaw)}">${fromCellInner}</div>
        <div class="mail-row-main">
          <span class="mail-row-subject">${this._escape(subject)}</span>
          ${snippet ? `<span class="mail-row-snippet"> — ${this._escape(snippet.slice(0, 160))}</span>` : ''}
        </div>
        <span class="mail-row-date">${ts}</span>
      </div>
    `;
  },

  // ----------------------------------------------------------------------
  // Modale détail mail (style mail moderne)
  // ----------------------------------------------------------------------
  _openDetail(m) {
    // Marque comme lu dès l'ouverture, quelle que soit la provenance
    // (clic ligne, deep-link Morning Digest, etc.)
    if (m && m.id != null) this._markRead(m.id);
    const extra = m.extra || {};
    const subject = m.subject || '(sans objet)';
    const fromAddr = extra.from || '';
    const toAddr = extra.to || '';
    const accountId = extra.account_id || '';
    const accountLabel = (this.state.accounts.find(a => a.id === accountId) || {}).label || accountId;
    const accountEmail = (this.state.accounts.find(a => a.id === accountId) || {}).from_email || '';
    const ts = this._fmtDateLong(m.ts);
    const isSent = m.kind === 'email_sent';
    // Mail ENVOYÉ : la personne à afficher en tête est le DESTINATAIRE,
    // pas l'expéditeur (qui est nous-même).
    const headAddr = isSent ? toAddr : fromAddr;
    const headInitial = (headAddr[0] || '?').toUpperCase();
    // On préfère toujours le HTML complet stocké dans extra (gras / couleurs
    // / liens / mise en page) — fallback sur le texte si absent (anciens
    // logs ou mails sans partie HTML). Vrai pour les envoyés ET les reçus.
    const body = extra.body_html
      ? extra.body_html
      : (extra.body_excerpt || m.body || '(corps vide)');
    const attachmentsMeta = Array.isArray(extra.attachments_meta)
      ? extra.attachments_meta.filter(a => a && !a.inline)
      : [];
    const classification = extra.classification || null;
    const inReplyTo = extra.in_reply_to || '';
    const replySubject = subject.toLowerCase().startsWith('re:') ? subject : 'Re: ' + subject;

    const kindLabel = m.kind === 'reply_received' ? 'Réponse prospect'
                     : m.kind === 'inbox_received' ? 'Mail entrant'
                     : m.kind === 'email_sent' ? 'Mail envoyé' : m.kind;
    const kindColor = m.kind === 'reply_received' ? 'success'
                     : m.kind === 'email_sent' ? 'accent' : 'gold';

    const overlay = document.createElement('div');
    overlay.className = 'fixed inset-0 z-[200] flex items-center justify-center p-4 sm:p-6';
    overlay.style.background = 'rgba(15,23,42,0.7)';
    overlay.style.backdropFilter = 'blur(8px)';
    overlay.innerHTML = `
      <div class="bg-surface rounded-2xl shadow-hero w-full max-w-3xl h-[88vh] overflow-hidden border border-border animate-slide-up flex flex-col">

        <!-- ========== Top bar : badge + close ========== -->
        <div class="px-6 pt-4 pb-3 flex items-center justify-between border-b border-border bg-surface-elevated">
          <span class="text-[11px] font-bold uppercase tracking-widest px-2.5 py-1 rounded-full"
                style="background: hsl(var(--${kindColor}) / 0.15); color: hsl(var(--${kindColor}));">
            ${this._escape(kindLabel)}
          </span>
          <button id="md-close" class="w-8 h-8 rounded-lg flex items-center justify-center text-text-muted hover:text-text hover:bg-bg transition-colors text-xl leading-none">×</button>
        </div>

        <!-- ========== Zone scrollable : sujet + sender + body + composer ========== -->
        <div id="md-scroll" class="flex-1 overflow-y-auto">

          <!-- Sujet -->
          <div class="px-6 pt-5 pb-4">
            <h2 class="text-xl font-bold leading-snug text-text">${this._escape(subject)}</h2>
          </div>

          <!-- Carte expéditeur (mail reçu) / destinataire (mail envoyé) -->
          <div class="px-6 pb-4">
            <div class="flex items-start gap-3 p-4 rounded-xl bg-bg border border-border">
              <div class="w-11 h-11 rounded-full flex items-center justify-center text-white font-bold text-base shrink-0"
                   style="background: linear-gradient(135deg, hsl(var(--${kindColor})), hsl(var(--accent)));">
                ${this._escape(headInitial)}
              </div>
              <div class="flex-1 min-w-0">
                <div class="flex items-baseline justify-between gap-3 flex-wrap">
                  <div class="text-sm font-semibold text-text truncate">${isSent
                    ? `À : ${this._escape(toAddr || '(destinataire inconnu)')}`
                    : this._escape(fromAddr || '(expéditeur inconnu)')}</div>
                  <div class="text-[11px] text-text-muted shrink-0">${ts}</div>
                </div>
                <div class="text-xs text-text-muted mt-0.5">
                  ${isSent
                    ? `envoyé depuis <span class="font-medium text-text">${this._escape(accountLabel)}</span>${accountEmail ? ` <span class="opacity-70">(${this._escape(accountEmail)})</span>` : ''}`
                    : `→ reçu sur <span class="font-medium text-text">${this._escape(accountLabel)}</span>${accountEmail ? ` <span class="opacity-70">(${this._escape(accountEmail)})</span>` : ''}`}
                </div>
                ${classification ? `<div class="text-[11px] mt-2"><span class="text-text-muted">Lecture IA :</span> <span class="font-medium" style="color: hsl(var(--${kindColor}));">${this._escape(this._classificationLabel(classification))}</span></div>` : ''}
              </div>
            </div>
          </div>

          <!-- Body du mail original -->
          <div class="px-6 pb-6">
            <div class="text-xs uppercase tracking-widest text-text-muted font-bold mb-2">CONTENU DU MAIL</div>
            ${this._renderMailBody(body)}
          </div>

          ${attachmentsMeta.length ? `
          <!-- Pièces jointes (mails envoyés) -->
          <div class="px-6 pb-6">
            <div class="text-xs uppercase tracking-widest text-text-muted font-bold mb-2">PIÈCES JOINTES (${attachmentsMeta.length})</div>
            <div class="space-y-1.5">
              ${attachmentsMeta.map(a => `
                <div class="flex items-center gap-2 px-3 py-2 rounded-lg bg-bg border border-border text-xs">
                  <span class="shrink-0">📎</span>
                  <span class="truncate font-medium text-text flex-1">${this._escape(a.filename || '(sans nom)')}</span>
                  <span class="text-text-muted shrink-0">${this._fmtSize(a.size)}</span>
                </div>
              `).join('')}
            </div>
            <div class="text-[11px] text-text-muted mt-2 italic">Le contenu binaire n'est pas archivé — seul le nom et la taille sont conservés.</div>
          </div>
          ` : ''}

          ${isSent ? '' : `
          <!-- Séparateur visuel -->
          <div class="px-6"><div class="border-t border-border"></div></div>

          <!-- Bouton Répondre (mails reçus uniquement) → ouvre le composeur -->
          <div id="md-composer" class="px-6 py-5">
            <button id="md-toggle-composer" class="w-full flex items-center justify-between gap-3 px-5 py-4 rounded-xl border border-dashed border-border hover:border-accent hover:bg-accent/5 transition-all group" ${fromAddr ? '' : 'disabled'}>
              <div class="flex items-center gap-3">
                <div class="w-9 h-9 rounded-full bg-accent/15 text-accent flex items-center justify-center group-hover:bg-accent group-hover:text-white transition-colors">
                  <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><path d="M3 10h11M9 5l-5 5 5 5M21 19V5"/></svg>
                </div>
                <div class="text-left">
                  <div class="text-sm font-semibold text-text">Répondre</div>
                  <div class="text-[11px] text-text-muted">${fromAddr ? `Réponse à ${this._escape(fromAddr)} depuis ${this._escape(accountLabel)}` : 'Adresse expéditeur manquante'}</div>
                </div>
              </div>
              <svg class="w-4 h-4 text-text-muted group-hover:text-accent transition-colors" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M9 18l6-6-6-6"/></svg>
            </button>
          </div>
          `}
        </div>

        <!-- ========== Footer sticky : actions ========== -->
        <div id="md-footer" class="px-6 py-4 border-t border-border bg-surface-elevated flex items-center justify-between gap-2 shrink-0">
          <button id="md-delete" class="text-xs text-text-muted hover:text-danger transition-colors" title="Supprimer ce mail de l'historique local">
            🗑 Supprimer de l'historique
          </button>
          <div class="flex items-center gap-2">
            <button id="md-ok" class="btn btn-secondary">Fermer</button>
          </div>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);

    // close() retire AUSSI l'écouteur Échap : sinon chaque ouverture de
    // détail fermée au bouton laissait un écouteur clavier orphelin.
    const close = () => {
      document.removeEventListener('keydown', escListener);
      overlay.remove();
    };
    const toggleBtn = overlay.querySelector('#md-toggle-composer');
    const okBtn = overlay.querySelector('#md-ok');

    overlay.querySelector('#md-close').onclick = close;
    okBtn.onclick = close;
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });

    // Bouton Supprimer — purge la trace locale dans l'historique, pour les
    // mails envoyés COMME reçus (même API que la corbeille groupée).
    // N'agit pas sur la boîte mail distante.
    const deleteBtn = overlay.querySelector('#md-delete');
    if (deleteBtn) {
      deleteBtn.onclick = async () => {
        const ok = await Dialog.confirm(
          isSent
            ? 'Supprimer ce mail de l’historique ? Le destinataire l’a déjà reçu — on efface juste la trace côté Triskell.'
            : 'Supprimer ce mail de l’historique ? Il reste dans ta vraie boîte mail — on efface juste la trace côté Triskell.',
          { title: 'Supprimer ce mail', okLabel: 'Supprimer', cancelLabel: 'Annuler', danger: true });
        if (!ok) return;
        deleteBtn.disabled = true;
        deleteBtn.textContent = 'Suppression…';
        try {
          const r = await App.api.mail_delete({ id: m.id });
          if (r && r.ok) {
            Toast.success('Mail supprimé de l’historique.');
            close();
            await this._load();
          } else {
            deleteBtn.disabled = false;
            deleteBtn.textContent = '🗑 Supprimer de l’historique';
            console.error('[mails] mail_delete :', r && r.error);
            Toast.error('La suppression a échoué. Réessaie.');
          }
        } catch (e) {
          deleteBtn.disabled = false;
          deleteBtn.textContent = '🗑 Supprimer de l’historique';
          Toast.friendlyError(e, 'La suppression a échoué. Réessaie.');
        }
      };
    }

    const escListener = (e) => { if (e.key === 'Escape') close(); };
    document.addEventListener('keydown', escListener);

    // Bouton "Répondre" (mails reçus) → ouvre le composeur dédié, avec la
    // citation du message d'origine pré-remplie quand le texte est dispo.
    if (toggleBtn) {
      toggleBtn.onclick = () => {
        close();
        this._openComposer({
          prefilledTo: fromAddr,
          prefilledSubject: replySubject,
          prefilledAccountId: accountId,
          inReplyTo: inReplyTo,
          prefilledBodyHtml: this._buildReplyQuoteHtml(m),
          title: 'Répondre',
        });
      };
    }
  },

  /** Construit la citation HTML du message d'origine pour une réponse :
   *  « Le <date>, <expéditeur> a écrit : » + texte préfixé « > ».
   *  Renvoie '' si aucun texte source n'est disponible. */
  _buildReplyQuoteHtml(m) {
    const extra = (m && m.extra) || {};
    const sourceText = (extra.body_excerpt || m.body || '').trim();
    if (!sourceText) return '';
    const who = extra.from || '(expéditeur inconnu)';
    const when = this._fmtDateLong(m.ts);
    const quotedLines = sourceText.split('\n')
      .map(l => `&gt; ${this._escape(l)}`).join('<br>');
    return `<p><br></p><p><br></p>` +
      `<p>Le ${this._escape(when)}, ${this._escape(who)} a écrit :</p>` +
      `<blockquote>${quotedLines}</blockquote>`;
  },

  /** Traduit la classification IA brute en français lisible. */
  _classificationLabel(c) {
    const key = String(c || '').trim().toLowerCase();
    const table = {
      'interested': 'Intéressé',
      'interesse': 'Intéressé',
      'not_interested': 'Pas intéressé',
      'not_now': 'Pas maintenant',
      'later': 'À recontacter plus tard',
      'refus': 'Refus',
      'refused': 'Refus',
      'rejection': 'Refus',
      'unsubscribe': 'Désinscription',
      'unsubscribed': 'Désinscription',
      'neutral': 'Neutre',
      'question': 'Question posée',
      'auto_reply': 'Réponse automatique',
      'out_of_office': 'Absent du bureau',
      'bounce': 'Adresse en erreur',
      'spam': 'Indésirable',
      'positive': 'Positif',
      'negative': 'Négatif',
      'other': 'Autre',
    };
    return table[key] || String(c || '');
  },

  _fmtDateLong(iso) {
    if (!iso) return '—';
    try {
      const d = new Date(iso);
      return d.toLocaleString('fr-FR', { dateStyle: 'medium', timeStyle: 'short' });
    } catch { return iso; }
  },

  /**
   * Affiche une bannière d'alerte non bloquante quand l'API renvoie un
   * payload {warnings: [...]} sur un envoi manuel (adresse déjà contactée
   * ou présente dans la base clients). L'utilisateur peut forcer ou annuler.
   *
   * @param {HTMLElement} statusEl  Le node où injecter la bannière (en
   *                                général le #cmp-status du composer)
   * @param {Array} warnings        La liste renvoyée par l'API
   * @param {Function} onForce      Callback appelé si "Envoyer quand même"
   * @param {Function} onCancel     Callback appelé si "Annuler"
   */
  _renderSendWarnings(statusEl, warnings, onForce, onCancel) {
    if (!statusEl) return;
    const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    }[c]));
    const msgs = (warnings || []).map(w => {
      const addr = w && w.email ? ` (${esc(w.email)})` : '';
      return `<li>${esc(w.message || '')}${addr}</li>`;
    }).join('');
    statusEl.className = '';
    statusEl.innerHTML = `
      <div class="mt-2 p-3 rounded-lg border text-sm"
           style="border-color: hsl(var(--warning) / 0.4); background: hsl(var(--warning) / 0.10);">
        <div class="font-semibold mb-1" style="color: hsl(var(--warning-text));">⚠ À vérifier avant d'envoyer</div>
        <ul class="list-disc list-inside mb-2" style="color: hsl(var(--warning-text));">${msgs}</ul>
        <div class="flex gap-2 justify-end">
          <button type="button" data-warn-act="cancel" class="btn btn-secondary btn-sm">Annuler</button>
          <button type="button" data-warn-act="force" class="btn btn-primary btn-sm">Envoyer quand même</button>
        </div>
      </div>
    `;
    const fBtn = statusEl.querySelector('[data-warn-act="force"]');
    const cBtn = statusEl.querySelector('[data-warn-act="cancel"]');
    if (fBtn) fBtn.onclick = () => { statusEl.innerHTML = ''; if (onForce) onForce(); };
    if (cBtn) cBtn.onclick = () => { statusEl.innerHTML = ''; if (onCancel) onCancel(); };
  },

  // ----------------------------------------------------------------------
  // Recherche côté client : filtre l'affichage sans recharger l'API
  // ----------------------------------------------------------------------
  _applySearch() {
    // Sans objet sur l'onglet Programmés (liste à part, pas de recherche).
    if (this.state.tab === 'scheduled') return;
    const q = (this.state.searchQuery || '').toLowerCase();
    const root = document.getElementById('m-content');
    const countEl = document.getElementById('m-count');
    if (!root) return;
    const all = this.state.mails || [];
    let visible = all;
    if (q) {
      visible = all.filter(m => {
        const extra = m.extra || {};
        const blob = [
          m.subject || '',
          m.body || '',
          extra.body_excerpt || '',
          extra.from || '',
          extra.to || '',
          extra.account_id || '',
          extra.classification || '',
        ].join(' ').toLowerCase();
        return blob.includes(q);
      });
    }
    countEl.textContent = q
      ? `${visible.length} / ${all.length} mail(s) (recherche : "${q}")`
      : `${all.length} mail(s)`;
    if (!visible.length) {
      this.state.visibleMails = [];
      root.innerHTML = `<div class="card p-10 text-center"><div class="text-3xl mb-3 opacity-60">∅</div><p class="text-text-muted">Aucun résultat pour "${this._escape(q)}".</p></div>`;
      return;
    }
    // Rendu via le chemin commun : la sélection et "Tout sélectionner"
    // travaillent sur CETTE liste filtrée (state.visibleMails), pas sur
    // state.mails complet — et le filtre reste affiché.
    this._renderListAndBulk(root, q ? '' : (this.state.limitedBanner || ''), visible);
  },

  // ----------------------------------------------------------------------
  // Notif desktop sur nouvel entrant (Web Notifications API)
  // ----------------------------------------------------------------------
  startDesktopNotifPolling() {
    if (this.state.notifPollHandle) return;  // déjà actif
    if (!('Notification' in window)) return; // navigateur ancien
    // Demande permission au 1er passage
    if (Notification.permission === 'default') {
      Notification.requestPermission().catch(() => {});
    }
    // Init le baseline (= mail le plus récent connu, pour ne pas notifier l'historique)
    this._initNotifBaseline();
    // Poll toutes les 60s
    this.state.notifPollHandle = setInterval(() => this._pollInbound(), 60_000);
  },

  async _initNotifBaseline() {
    if (!App.api) return;
    try {
      const r = await App.api.mails_list({ kind: 'inbound', limit: 1 });
      if (r && r.ok && r.mails && r.mails.length) {
        this.state.lastKnownInboundId = r.mails[0].id;
      }
    } catch (e) {}
  },

  async _pollInbound() {
    if (!App.api) return;
    if (Notification.permission !== 'granted') return;
    try {
      const r = await App.api.mails_list({ kind: 'inbound', limit: 10 });
      if (!r || !r.ok || !r.mails) return;
      const mails = r.mails;
      if (!mails.length) return;
      // Tous les mails plus récents que le dernier connu = nouveaux
      const lastKnown = this.state.lastKnownInboundId;
      const newOnes = [];
      for (const m of mails) {
        if (m.id === lastKnown) break;
        newOnes.push(m);
      }
      if (!newOnes.length) return;
      // Met à jour le baseline
      this.state.lastKnownInboundId = mails[0].id;
      // Affiche les notifs (max 3 d'un coup pour ne pas spammer)
      for (const m of newOnes.slice(0, 3)) {
        const extra = m.extra || {};
        const fromAddr = extra.from || '(inconnu)';
        const accountId = extra.account_id || '';
        const accountLabel = (this.state.accounts.find(a => a.id === accountId) || {}).label || accountId || '';
        const subject = m.subject || '(sans objet)';
        const body = (extra.body_excerpt || m.body || '').slice(0, 100);
        const notif = new Notification(`📬 ${fromAddr}`, {
          body: `${subject}${accountLabel ? '\n→ ' + accountLabel : ''}${body ? '\n\n' + body : ''}`,
          icon: 'https://rmaafrrseafghptlsgdz.supabase.co/storage/v1/object/public/chat-images/triskell-logo.png',
          tag: `mail-${m.id}`,
        });
        notif.onclick = () => {
          window.focus();
          App.show('mails');
          setTimeout(() => this._openDetail(m), 200);
          notif.close();
        };
      }
    } catch (e) {}
  },

  // ----------------------------------------------------------------------
  // Mini modale "Coller du HTML brut" — textarea code + aperçu live à côté
  // ----------------------------------------------------------------------
  _openPasteHtmlDialog(htmlArea) {
    const overlay = document.createElement('div');
    overlay.className = 'fixed inset-0 z-[230] flex items-center justify-center p-4';
    overlay.style.background = 'rgba(15,23,42,0.7)';
    overlay.style.backdropFilter = 'blur(8px)';
    overlay.innerHTML = `
      <div class="bg-surface rounded-2xl shadow-hero w-full max-w-5xl h-[85vh] overflow-hidden border border-border animate-slide-up flex flex-col">
        <div class="px-6 pt-4 pb-3 flex items-center justify-between border-b border-border bg-surface-elevated">
          <div>
            <div class="hero-kicker mb-0.5">CODE HTML</div>
            <h3 class="text-base font-bold">Coller du HTML — avec aperçu en direct</h3>
          </div>
          <button id="ph-close" class="w-8 h-8 rounded-lg flex items-center justify-center text-text-muted hover:text-text hover:bg-bg transition-colors text-xl leading-none">×</button>
        </div>
        <div class="flex-1 grid grid-cols-1 md:grid-cols-2 gap-0 overflow-hidden">
          <!-- Code -->
          <div class="flex flex-col border-r border-border overflow-hidden">
            <div class="px-4 py-2 text-[11px] font-bold uppercase tracking-widest text-text-muted bg-bg border-b border-border">Code HTML</div>
            <textarea id="ph-input" placeholder='<p>Bonjour <strong>{prénom}</strong>,</p>...'
                      class="flex-1 px-3 py-3 text-xs bg-bg focus:outline-none font-mono leading-relaxed resize-none"></textarea>
          </div>
          <!-- Aperçu -->
          <div class="flex flex-col overflow-hidden">
            <div class="px-4 py-2 text-[11px] font-bold uppercase tracking-widest text-text-muted bg-bg border-b border-border flex items-center justify-between">
              <span>Aperçu (rendu mail)</span>
              <span id="ph-empty-hint" class="text-text-muted/60 normal-case font-normal tracking-normal">↪ tape du HTML pour voir le rendu</span>
            </div>
            <iframe id="ph-preview" sandbox="allow-popups"
                    class="flex-1 w-full bg-white border-0"></iframe>
          </div>
        </div>
        <div class="px-6 py-3 border-t border-border bg-surface-elevated flex items-center justify-between gap-2 shrink-0">
          <div class="text-[11px] text-text-muted">ⓘ Placeholders type <code>{prénom}</code> à remplacer à la main avant envoi.</div>
          <div class="flex gap-2">
            <button id="ph-cancel" class="btn btn-secondary">Annuler</button>
            <button id="ph-append" class="btn btn-secondary">Insérer à la fin</button>
            <button id="ph-replace" class="btn btn-primary">Remplacer le contenu</button>
          </div>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);
    const input   = overlay.querySelector('#ph-input');
    const iframe  = overlay.querySelector('#ph-preview');
    const hint    = overlay.querySelector('#ph-empty-hint');
    setTimeout(() => input.focus(), 50);
    const close = () => overlay.remove();
    overlay.querySelector('#ph-close').onclick = close;
    overlay.querySelector('#ph-cancel').onclick = close;

    // Update preview en temps réel (debounced)
    const renderPreview = () => {
      const html = input.value;
      if (!html.trim()) { hint.style.display = ''; iframe.srcdoc = ''; return; }
      hint.style.display = 'none';
      iframe.srcdoc = this._buildPreviewDoc(html);
    };
    let timer = null;
    input.addEventListener('input', () => {
      clearTimeout(timer);
      timer = setTimeout(renderPreview, 200);
    });

    overlay.querySelector('#ph-replace').onclick = () => {
      const html = input.value.trim();
      if (!html) { close(); return; }
      htmlArea.innerHTML = html;
      close();
      htmlArea.focus();
    };
    overlay.querySelector('#ph-append').onclick = () => {
      const html = input.value.trim();
      if (!html) { close(); return; }
      htmlArea.innerHTML = (htmlArea.innerHTML || '') + html;
      close();
      htmlArea.focus();
    };
  },

  // ----------------------------------------------------------------------
  // Modale Aperçu — rend le HTML actuel comme un client mail le verrait
  // ----------------------------------------------------------------------
  _openHtmlPreview(htmlContent, meta = {}) {
    const overlay = document.createElement('div');
    overlay.className = 'fixed inset-0 z-[230] flex items-center justify-center p-4';
    overlay.style.background = 'rgba(15,23,42,0.7)';
    overlay.style.backdropFilter = 'blur(8px)';
    const subject = meta.subject || '(sans objet)';
    const from = meta.from || '';
    const to = meta.to || '(destinataire)';
    overlay.innerHTML = `
      <div class="bg-surface rounded-2xl shadow-hero w-full max-w-3xl h-[85vh] overflow-hidden border border-border animate-slide-up flex flex-col">
        <div class="px-6 pt-4 pb-3 flex items-center justify-between border-b border-border bg-surface-elevated">
          <div>
            <div class="hero-kicker mb-0.5">APERÇU MAIL</div>
            <h3 class="text-base font-bold">Ce que ton destinataire verra</h3>
          </div>
          <button id="hp-close" class="w-8 h-8 rounded-lg flex items-center justify-center text-text-muted hover:text-text hover:bg-bg text-xl leading-none">×</button>
        </div>
        <!-- En-têtes mail (façon client mail) -->
        <div class="px-6 py-3 border-b border-border bg-bg">
          <div class="text-base font-bold mb-2">${this._escape(subject)}</div>
          <div class="text-xs text-text-muted space-y-0.5">
            ${from ? `<div>De : <span class="text-text">${this._escape(from)}</span></div>` : ''}
            <div>À : <span class="text-text">${this._escape(to)}</span></div>
          </div>
        </div>
        <!-- Iframe rendu -->
        <iframe id="hp-frame" sandbox="allow-popups" class="flex-1 w-full bg-white border-0"></iframe>
        <div class="px-6 py-3 border-t border-border bg-surface-elevated flex items-center justify-between gap-2">
          <button id="hp-ok" class="btn btn-primary">Fermer l'aperçu</button>
          <div class="text-[11px] text-text-muted text-right">ⓘ Rendu isolé (sandbox). Les vrais clients mail (Gmail, Outlook…) peuvent légèrement différer.</div>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);
    overlay.querySelector('#hp-frame').srcdoc = this._buildPreviewDoc(htmlContent);
    const close = () => {
      document.removeEventListener('keydown', escListener);
      overlay.remove();
    };
    const escListener = (e) => { if (e.key === 'Escape') close(); };
    overlay.querySelector('#hp-close').onclick = close;
    overlay.querySelector('#hp-ok').onclick = close;
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
    document.addEventListener('keydown', escListener);
  },

  // Construit un document HTML auto-suffisant (avec styles "mail-friendly")
  // pour le rendre dans une iframe sandbox.
  _buildPreviewDoc(htmlContent) {
    const safeContent = String(htmlContent || '');
    return `<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8">
<style>
  body { margin: 0; padding: 24px;
         font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
         font-size: 14px; line-height: 1.55; color: #1a1a20;
         background: #ffffff; max-width: 680px; margin: 0 auto; }
  p { margin: 0 0 14px; }
  h1, h2, h3 { margin: 22px 0 10px; line-height: 1.25; color: #0f172a; }
  h1 { font-size: 24px; } h2 { font-size: 20px; } h3 { font-size: 17px; }
  ul, ol { margin: 0 0 14px; padding-left: 24px; }
  li { margin: 4px 0; }
  a { color: #5b5fd6; text-decoration: underline; }
  blockquote { margin: 14px 0; padding: 8px 16px; border-left: 3px solid #5b5fd6;
               background: #f7f7fb; color: #444; font-style: italic; }
  code { font-family: ui-monospace, Menlo, Consolas, monospace;
         background: #f1f1f5; padding: 1px 5px; border-radius: 4px; font-size: 13px; }
  img { max-width: 100%; height: auto; }
  hr { border: 0; border-top: 1px solid #e3e3e8; margin: 18px 0; }
</style>
</head><body>${safeContent}</body></html>`;
  },

  // ----------------------------------------------------------------------
  // Modale "Gérer mes templates" — liste + supprimer + renommer + aperçu
  // ----------------------------------------------------------------------
  async _openTemplatesManager() {
    const overlay = document.createElement('div');
    overlay.className = 'fixed inset-0 z-[220] flex items-center justify-center p-4 sm:p-6';
    overlay.style.background = 'rgba(15,23,42,0.7)';
    overlay.style.backdropFilter = 'blur(8px)';
    overlay.innerHTML = `
      <div class="bg-surface rounded-2xl shadow-hero w-full max-w-2xl h-[80vh] overflow-hidden border border-border animate-slide-up flex flex-col">
        <div class="px-6 pt-4 pb-3 flex items-center justify-between border-b border-border bg-surface-elevated">
          <div>
            <div class="hero-kicker mb-0.5">MODÈLES MAIL</div>
            <h3 class="text-base font-bold">Tes modèles HTML réutilisables</h3>
          </div>
          <button id="tm-close" class="w-8 h-8 rounded-lg flex items-center justify-center text-text-muted hover:text-text hover:bg-bg transition-colors text-xl leading-none">×</button>
        </div>
        <div id="tm-list" class="flex-1 overflow-y-auto p-4 space-y-2"></div>
        <div class="px-6 py-3 border-t border-border bg-surface-elevated text-[11px] text-text-muted">
          Pour créer un nouveau modèle : ouvre un mail dans le composer, écris ton HTML, clique sur "Modèles ▾ → Sauvegarder le contenu actuel comme modèle".
        </div>
      </div>
    `;
    document.body.appendChild(overlay);
    overlay.querySelector('#tm-close').onclick = () => overlay.remove();
    overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });

    const listEl = overlay.querySelector('#tm-list');
    const reload = async () => {
      listEl.innerHTML = '<div class="text-sm text-text-muted">Chargement…</div>';
      const r = await App.api.user_mail_templates_list();
      const tpls = (r && r.ok) ? (r.templates || []) : [];
      if (!tpls.length) {
        listEl.innerHTML = `
          <div class="text-center py-12 text-text-muted text-sm">
            Aucun modèle enregistré.
          </div>`;
        return;
      }
      listEl.innerHTML = tpls.map(t => `
        <div class="card p-4">
          <div class="flex items-start justify-between gap-3 mb-2">
            <div class="flex-1 min-w-0">
              <div class="text-sm font-bold text-text truncate">${this._escape(t.name)}</div>
              ${t.subject_default ? `<div class="text-[11px] text-text-muted truncate">Objet par défaut : ${this._escape(t.subject_default)}</div>` : ''}
            </div>
            <div class="flex gap-1 shrink-0">
              <button data-tm-rename="${this._escape(t.id)}" class="text-[11px] px-2 py-1 rounded hover:bg-bg text-text-muted hover:text-accent">Renommer</button>
              <button data-tm-remove="${this._escape(t.id)}" class="text-[11px] px-2 py-1 rounded hover:bg-bg text-text-muted hover:text-danger">Supprimer</button>
            </div>
          </div>
          <details class="text-xs">
            <summary class="cursor-pointer text-text-muted hover:text-text">Aperçu HTML</summary>
            <div class="mt-2 p-3 rounded-lg bg-bg border border-border max-h-48 overflow-y-auto">
              ${t.body_html || '<em class="text-text-muted">(vide)</em>'}
            </div>
          </details>
        </div>
      `).join('');
      // Bind renommer + supprimer
      listEl.querySelectorAll('[data-tm-remove]').forEach(btn => {
        btn.onclick = async () => {
          const tid = btn.dataset.tmRemove;
          const tpl = tpls.find(x => x.id === tid);
          const ok = await Dialog.confirm(
            `Supprimer le modèle "${(tpl && tpl.name) || ''}" ? Il ne sera plus proposé dans le composeur.`,
            { title: 'Supprimer ce modèle', okLabel: 'Supprimer', cancelLabel: 'Annuler', danger: true });
          if (!ok) return;
          try {
            const r = await App.api.user_mail_template_remove({ id: tid });
            if (r && r.ok) { Toast.success('Modèle supprimé.'); reload(); }
            else {
              console.error('[mails] user_mail_template_remove :', r && r.error);
              Toast.error('La suppression du modèle a échoué.');
            }
          } catch (e) {
            Toast.friendlyError(e, 'La suppression du modèle a échoué.');
          }
        };
      });
      listEl.querySelectorAll('[data-tm-rename]').forEach(btn => {
        btn.onclick = async () => {
          const tid = btn.dataset.tmRename;
          const tpl = tpls.find(x => x.id === tid);
          const newName = prompt('Nouveau nom :', (tpl && tpl.name) || '');
          if (!newName || newName === (tpl && tpl.name)) return; // null = annuler
          try {
            const r = await App.api.user_mail_template_save({
              template: { ...tpl, name: newName }
            });
            if (r && r.ok) { Toast.success('Modèle renommé.'); reload(); }
            else {
              console.error('[mails] user_mail_template_save :', r && r.error);
              Toast.error('Le renommage a échoué.');
            }
          } catch (e) {
            Toast.friendlyError(e, 'Le renommage a échoué.');
          }
        };
      });
    };
    reload();
  },

  // ----------------------------------------------------------------------
  // Composer mail (nouveau OU réponse) — utilise le même endpoint mail_send
  // ----------------------------------------------------------------------
  // Options :
  //   { prefilledTo, prefilledSubject, prefilledAccountId, inReplyTo, title }
  async _openComposer(opts = {}) {
    // Charge les comptes si pas encore en cache (cas où le composer est
    // ouvert depuis la Matinale sans passer par la vue Mails).
    if (!this.state.accounts || !this.state.accounts.length) {
      await this._loadAccountsSilent();
    }
    const accounts = this.state.accounts || [];
    const defaultAccountId = opts.prefilledAccountId
      || (accounts.find(a => a.is_primary) || accounts[0] || {}).id
      || 'primary';
    const isReply = !!opts.inReplyTo;
    const title = opts.title || (isReply ? 'Répondre' : 'Nouveau mail');

    // Charge la liste de signatures + sélection auto selon le compte
    let signatures = [];
    if (App.api) {
      try {
        const r = await App.api.signatures_list();
        if (r && r.ok) signatures = r.signatures || [];
      } catch (e) {}
    }
    // Liste filtrée des signatures visibles pour un compte donné.
    // Règle : une signature attribuée à un compte précis (account_ids non vide)
    // ne s'affiche QUE pour les comptes concernés. Une signature sans
    // account_ids est universelle (visible partout).
    const signaturesForAccount = (accId) => {
      return signatures.filter(s => {
        const ids = s.account_ids || [];
        return ids.length === 0 || ids.includes(accId);
      });
    };
    // Détermine la signature à utiliser par défaut pour le compte courant
    const pickSigForAccount = (accId) => {
      const visible = signaturesForAccount(accId);
      if (!visible.length) return null;
      // 1) Signature explicitement attribuée au compte
      let s = visible.find(s => (s.account_ids || []).includes(accId));
      // 2) Sinon signature "toutes adresses" (account_ids vide)
      if (!s) s = visible.find(s => !(s.account_ids || []).length);
      // 3) Sinon la première visible
      return s || visible[0] || null;
    };
    let currentSig = pickSigForAccount(defaultAccountId);
    let signature = currentSig?.body_text || '';
    let signatureHtml = currentSig?.body_html || '';

    const overlay = document.createElement('div');
    overlay.className = 'fixed inset-0 z-[210] flex items-center justify-center p-4 sm:p-6';
    overlay.style.background = 'rgba(15,23,42,0.7)';
    overlay.style.backdropFilter = 'blur(8px)';
    overlay.innerHTML = `
      <div class="bg-surface rounded-2xl shadow-hero w-full max-w-3xl h-[88vh] overflow-hidden border border-border animate-slide-up flex flex-col">
        <!-- Header -->
        <div class="px-6 pt-4 pb-3 flex items-center justify-between border-b border-border bg-surface-elevated">
          <div>
            <div class="hero-kicker mb-0.5">${this._escape(title.toUpperCase())}</div>
            <h3 class="text-base font-bold">${isReply ? 'Réponse à un mail' : 'Composer un mail'}</h3>
          </div>
          <button id="cmp-close" class="w-8 h-8 rounded-lg flex items-center justify-center text-text-muted hover:text-text hover:bg-bg transition-colors text-xl leading-none">×</button>
        </div>

        <!-- Form scrollable -->
        <div class="flex-1 overflow-y-auto px-6 py-5 space-y-3">
          <!-- Depuis + À -->
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label class="block text-[11px] font-medium text-text-secondary mb-1">Depuis quelle adresse</label>
              <select id="cmp-from" class="w-full px-3 py-2.5 text-sm rounded-lg bg-bg border border-border focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent text-ellipsis overflow-hidden whitespace-nowrap" style="text-overflow: ellipsis;">
                ${accounts.map(a =>
                  `<option value="${this._escape(a.id)}" ${a.id === defaultAccountId ? 'selected' : ''}>${this._escape(a.from_email)}${a.label && a.label !== a.from_email ? ' · ' + this._escape(a.label) : ''}</option>`
                ).join('')}
              </select>
            </div>
            <div>
              <div class="flex items-center justify-between mb-1 gap-2">
                <label class="block text-[11px] font-medium text-text-secondary">Destinataires</label>
                <div class="flex items-center gap-1 text-[11px] font-semibold">
                  <button id="cmp-toggle-cc" type="button" class="px-1.5 py-0.5 rounded text-text-muted hover:text-accent hover:bg-accent/10 transition-colors" title="Afficher ou masquer le champ Cc">+ Cc</button>
                  <button id="cmp-toggle-bcc" type="button" class="px-1.5 py-0.5 rounded text-text-muted hover:text-accent hover:bg-accent/10 transition-colors" title="Afficher ou masquer le champ Cci (copie cachée)">+ Cci</button>
                </div>
              </div>
              <div id="cmp-to-wrap" class="chips-input chips-input--to"
                   data-input-id="cmp-to-input"
                   data-placeholder="email@exemple.fr">
                <input id="cmp-to-input" type="text" autocomplete="off"
                       class="chips-text" placeholder="email@exemple.fr"/>
              </div>
            </div>
          </div>

          <!-- Cc / Cci (masqués par défaut) -->
          <div id="cmp-cc-row" class="hidden">
            <div class="flex items-center justify-between mb-1">
              <label class="block text-[11px] font-medium text-text-secondary">Cc <span class="text-text-muted font-normal">(copie visible)</span></label>
              <button id="cmp-cc-remove" type="button" class="text-text-muted hover:text-danger text-sm leading-none px-1" title="Retirer le champ Cc" aria-label="Retirer le champ Cc">×</button>
            </div>
            <div id="cmp-cc-wrap" class="chips-input"
                 data-input-id="cmp-cc-input">
              <input id="cmp-cc-input" type="text" autocomplete="off"
                     class="chips-text" placeholder="email@exemple.fr"/>
            </div>
          </div>
          <div id="cmp-bcc-row" class="hidden">
            <div class="flex items-center justify-between mb-1">
              <label class="block text-[11px] font-medium text-text-secondary">Cci <span class="text-text-muted font-normal">(copie cachée — les autres destinataires ne la voient pas)</span></label>
              <button id="cmp-bcc-remove" type="button" class="text-text-muted hover:text-danger text-sm leading-none px-1" title="Retirer le champ Cci" aria-label="Retirer le champ Cci">×</button>
            </div>
            <div id="cmp-bcc-wrap" class="chips-input"
                 data-input-id="cmp-bcc-input">
              <input id="cmp-bcc-input" type="text" autocomplete="off"
                     class="chips-text" placeholder="email@exemple.fr"/>
            </div>
          </div>

          <!-- Sujet -->
          <div>
            <label class="block text-[11px] font-medium text-text-secondary mb-1">Objet</label>
            <input id="cmp-subject" type="text" value="${this._escape(opts.prefilledSubject || '')}" placeholder="Objet du mail"
                   class="w-full px-3 py-2.5 text-sm rounded-lg bg-bg border border-border focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent"/>
          </div>

          <!-- Toggle Texte / HTML + bouton Templates + Signature -->
          <div>
            <div class="flex items-center justify-between mb-1 gap-2 flex-wrap">
              <label class="block text-[11px] font-medium text-text-secondary">Message</label>
              <div class="flex items-center gap-2 text-[11px] flex-wrap">
                <!-- Dropdown signatures + bouton "gérer" -->
                <div class="flex items-center gap-1.5 shrink-0">
                  <button id="cmp-sig-edit" type="button"
                          title="Gérer mes signatures (ouvre les Réglages)"
                          class="w-6 h-6 rounded-md flex items-center justify-center text-text-muted hover:text-accent hover:bg-accent/10 transition-colors">
                    <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M20 14.66V20a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h5.34"/><polygon points="18 2 22 6 12 16 8 16 8 12 18 2"/></svg>
                  </button>
                  <select id="cmp-signature"
                          class="px-2.5 py-1 rounded-lg bg-bg border border-border font-semibold text-text"
                          style="min-width: 160px; max-width: 220px;">
                    <option value="">Sans signature</option>
                    ${signaturesForAccount(defaultAccountId).map(s =>
                      `<option value="${this._escape(s.id)}" ${currentSig && s.id === currentSig.id ? 'selected' : ''}>${this._escape(s.name)}</option>`
                    ).join('')}
                  </select>
                </div>
                <!-- Bouton "Insérer un produit du catalogue" -->
                <button id="cmp-product-trigger" type="button"
                        title="Insérer un produit du Catalogue Triskell"
                        class="px-2.5 py-1 rounded-lg font-semibold text-text-muted hover:bg-bg flex items-center gap-1">
                  <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/></svg>
                  Produit
                </button>
                <!-- Dropdown templates -->
                <div class="relative">
                  <button id="cmp-tpl-trigger" class="px-2.5 py-1 rounded-lg font-semibold text-text-muted hover:bg-bg flex items-center gap-1">
                    <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                    Modèles ▾
                  </button>
                  <div id="cmp-tpl-menu" class="hidden absolute right-0 top-full mt-1 w-72 rounded-xl border border-border bg-surface shadow-lift z-30 max-h-80 overflow-y-auto">
                    <div id="cmp-tpl-list" class="py-1"></div>
                    <div class="border-t border-border py-1">
                      <button id="cmp-tpl-save" class="w-full px-4 py-2 text-left text-xs hover:bg-bg flex items-center gap-2 text-accent font-semibold">
                        <span>+</span> Sauvegarder le contenu actuel comme modèle
                      </button>
                      <button id="cmp-tpl-manage" class="w-full px-4 py-2 text-left text-xs hover:bg-bg flex items-center gap-2 text-text-muted">
                        <span>⚙</span> Gérer mes modèles…
                      </button>
                    </div>
                  </div>
                </div>
                <!-- Toggle Texte/HTML -->
                <button id="cmp-mode-text" class="px-2.5 py-1 rounded-lg font-semibold transition-colors bg-accent/15 text-accent">Texte</button>
                <button id="cmp-mode-html" class="px-2.5 py-1 rounded-lg font-semibold transition-colors text-text-muted hover:bg-bg">HTML enrichi</button>
                <!-- Bouton Aperçu (visible uniquement en mode HTML enrichi via JS) -->
                <button id="cmp-preview-top" type="button" class="hidden px-2.5 py-1 rounded-lg font-semibold transition-colors text-text-muted hover:bg-bg" title="Aperçu (rendu réel du mail)">👁 Aperçu</button>
                <!-- Toggle fond clair / sombre de la zone d'écriture (style Outlook) -->
                <button id="cmp-bg-toggle" type="button" class="rounded-lg font-semibold transition-colors text-text-muted hover:bg-bg flex items-center justify-center" style="width:32px;height:28px;" title="Basculer le fond de la zone d'écriture (clair / sombre)">
                  <span id="cmp-bg-toggle-icon" style="display:inline-block;width:16px;text-align:center;line-height:1;">☀</span>
                </button>
              </div>
            </div>

            <!-- Mini barre d'outils HTML (cachée par défaut) -->
            <div id="cmp-toolbar" class="hidden flex items-center flex-wrap gap-1 mb-2 p-1.5 rounded-lg bg-bg border border-border">
              <button data-cmd="bold" title="Gras (Ctrl+B)" class="cmp-tb-btn font-bold">B</button>
              <button data-cmd="italic" title="Italique (Ctrl+I)" class="cmp-tb-btn italic">I</button>
              <button data-cmd="underline" title="Souligné (Ctrl+U)" class="cmp-tb-btn underline">U</button>
              <div class="w-px h-5 bg-border mx-1"></div>
              <button data-cmd="text-color" title="Couleur du texte" class="cmp-tb-btn cmp-color-btn"><span>A</span><span class="cmp-color-bar" id="cmp-text-color-bar"></span></button>
              <input type="color" id="cmp-text-color-input" class="hidden" value="#1f1f1f">
              <button data-cmd="bg-color" title="Couleur d'arrière-plan" class="cmp-tb-btn cmp-color-btn cmp-color-bg"><span>A</span><span class="cmp-color-bar" id="cmp-bg-color-bar" style="background:#ffeb3b"></span></button>
              <input type="color" id="cmp-bg-color-input" class="hidden" value="#ffeb3b">
              <div class="w-px h-5 bg-border mx-1"></div>
              <button data-cmd="justifyLeft" title="Aligner à gauche" class="cmp-tb-btn">⇤</button>
              <button data-cmd="justifyCenter" title="Centrer" class="cmp-tb-btn">↔</button>
              <button data-cmd="justifyRight" title="Aligner à droite" class="cmp-tb-btn">⇥</button>
              <div class="w-px h-5 bg-border mx-1"></div>
              <button data-cmd="insertUnorderedList" title="Liste à puces" class="cmp-tb-btn">•</button>
              <button data-cmd="insertOrderedList" title="Liste numérotée" class="cmp-tb-btn">1.</button>
              <div class="w-px h-5 bg-border mx-1"></div>
              <button data-cmd="createLink" title="Lien" class="cmp-tb-btn">🔗</button>
              <button data-cmd="insert-image" title="Insérer une image dans le corps du mail" class="cmp-tb-btn">🖼</button>
              <button data-cmd="formatBlock-h2" title="Titre" class="cmp-tb-btn font-bold text-sm">H</button>
              <button data-cmd="formatBlock-blockquote" title="Citation" class="cmp-tb-btn">"</button>
              <div class="w-px h-5 bg-border mx-1"></div>
              <button data-cmd="paste-html" title="Coller du HTML brut" class="cmp-tb-btn font-mono">&lt;/&gt;</button>
              <button data-cmd="removeFormat" title="Effacer la mise en forme" class="cmp-tb-btn text-text-muted">×</button>
            </div>

            <!-- Editor texte simple -->
            <textarea id="cmp-body-text" rows="14" placeholder="Tape ton message ici…&#10;&#10;Astuce : Ctrl+Entrée pour envoyer."
                      class="cmp-editor-surface w-full px-3 py-3 text-sm rounded-lg border border-border focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent font-sans leading-relaxed resize-y"></textarea>

            <!-- Editor HTML (contenteditable) -->
            <div id="cmp-body-html" contenteditable="true"
                 class="cmp-editor-surface hidden w-full min-h-[300px] px-4 py-3 text-sm rounded-lg border border-border focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent font-sans leading-relaxed"
                 style="white-space: pre-wrap;"></div>
          </div>

          <!-- Pièces jointes -->
          <div id="cmp-attachments-section">
            <div class="flex items-center justify-between mb-2">
              <label class="text-[11px] font-medium text-text-secondary uppercase tracking-wider">Pièces jointes</label>
              <button id="cmp-add-attachment" type="button" class="text-[11px] text-accent font-semibold hover:underline flex items-center gap-1.5">
                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48"/></svg>
                Joindre un fichier
              </button>
            </div>
            <div id="cmp-attachments-list" class="space-y-1.5 text-xs"></div>
            <input id="cmp-attachment-input" type="file" multiple class="hidden">
            <div id="cmp-attachments-total" class="text-[11px] text-text-muted mt-1.5"></div>
          </div>

          <div id="cmp-status" class="text-xs text-text-muted"></div>
        </div>

        <!-- Footer sticky -->
        <div class="px-6 py-4 border-t border-border bg-surface-elevated flex items-center justify-between gap-2 shrink-0">
          <button id="cmp-cancel" class="btn btn-secondary">Annuler</button>
          <div class="flex items-center gap-2">
            <button id="cmp-draft" type="button" class="btn btn-secondary"
                    title="Enregistrer en brouillon pour reprendre plus tard">
              <svg class="w-4 h-4 mr-1.5 inline" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>
              Brouillon
            </button>
            <button id="cmp-schedule" type="button" class="btn btn-secondary"
                    title="Programmer l'envoi à une date/heure précise">
              <svg class="w-4 h-4 mr-1.5 inline" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
              Plus tard
            </button>
            <button id="cmp-send" class="btn btn-primary">
              <svg class="w-4 h-4 mr-1.5 inline" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><path d="M2 21l21-9-21-9v7l15 2-15 2z"/></svg>
              Envoyer
            </button>
          </div>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);

    // Pastilles "NEW" sur les nouveautés du composer (mai 2026).
    // Restent visibles jusqu'à ce que l'utilisateur clique la croix.
    if (window.NewBadge) {
      const imgBtn = overlay.querySelector('[data-cmd="insert-image"]');
      if (imgBtn) window.NewBadge.attach(imgBtn, 'mail-insert-image-v1');
      const attBtn = overlay.querySelector('#cmp-add-attachment');
      if (attBtn) window.NewBadge.attach(attBtn, 'mail-attachments-v1');
    }

    // Style pour les boutons toolbar (injecté une fois)
    if (!document.getElementById('cmp-toolbar-styles')) {
      const s = document.createElement('style');
      s.id = 'cmp-toolbar-styles';
      s.textContent = `
        /* Zone d'écriture du mail : fond blanc par défaut (toujours, peu importe
           le thème de l'app) — basculable en sombre via le bouton ☀ / ☾.
           Le choix est mémorisé dans localStorage. */
        .cmp-editor-surface {
          background: #ffffff !important;
          color: #1f1f1f !important;
        }
        .cmp-editor-surface::placeholder {
          color: #9aa0a6 !important;
        }
        .cmp-editor-surface.cmp-editor-dark {
          background: #1e1e1e !important;
          color: #e8e8e8 !important;
        }
        .cmp-editor-surface.cmp-editor-dark::placeholder {
          color: #8a8a8a !important;
        }
        #cmp-body-html.cmp-editor-surface:empty:before {
          color: #9aa0a6 !important;
        }
        #cmp-body-html.cmp-editor-surface.cmp-editor-dark:empty:before {
          color: #8a8a8a !important;
        }
        .cmp-tb-btn { padding: 4px 9px; border-radius: 6px; font-size: 13px;
                      color: hsl(var(--text)); transition: background 120ms; }
        .cmp-tb-btn:hover { background: hsl(var(--accent) / 0.12);
                            color: hsl(var(--accent)); }
        .cmp-color-btn { position: relative; padding-bottom: 8px; }
        .cmp-color-bar { position: absolute; bottom: 3px; left: 6px; right: 6px;
                         height: 3px; border-radius: 1px; background: #1f1f1f;
                         pointer-events: none; }
        #cmp-body-html:empty:before {
          content: 'Tape ton message ici…';
          color: hsl(var(--text-muted));
        }
        /* Rétablit le rendu visuel des blocs créés par la toolbar.
           !important : Tailwind preflight (ol, ul, menu { list-style:none })
           a tendance à reprendre la main selon l'ordre de chargement des
           feuilles de style — les puces disparaissaient et le bouton "•"
           semblait inerte alors que la <ul> était bien créée. */
        #cmp-body-html ul,
        #cmp-body-html ol {
          padding-left: 1.6em !important;
          margin: 0.5em 0 !important;
        }
        #cmp-body-html ul { list-style: disc outside !important; }
        #cmp-body-html ol { list-style: decimal outside !important; }
        #cmp-body-html ul ul { list-style: circle outside !important; }
        #cmp-body-html ul ul ul { list-style: square outside !important; }
        #cmp-body-html li {
          display: list-item !important;
          margin: 0.15em 0 !important;
        }
        #cmp-body-html h1,
        #cmp-body-html h2,
        #cmp-body-html h3 {
          font-weight: 700;
          line-height: 1.25;
          margin: 0.6em 0 0.3em;
          color: hsl(var(--text));
        }
        #cmp-body-html h1 { font-size: 1.6em; }
        #cmp-body-html h2 { font-size: 1.35em; }
        #cmp-body-html h3 { font-size: 1.15em; }
        #cmp-body-html blockquote {
          margin: 0.5em 0;
          padding: 0.3em 0 0.3em 0.9em;
          border-left: 3px solid hsl(var(--accent) / 0.6);
          color: hsl(var(--text-muted));
          font-style: italic;
        }
        #cmp-body-html p {
          margin: 0.25em 0;
        }
        #cmp-body-html a {
          color: hsl(var(--accent));
          text-decoration: underline;
        }
        /* Images insérées : highlight au survol, indicateur si déjà liée */
        #cmp-body-html img {
          cursor: pointer;
          transition: outline 120ms, box-shadow 120ms;
        }
        #cmp-body-html img:hover {
          outline: 2px solid hsl(var(--accent));
          outline-offset: 2px;
        }
        #cmp-body-html a > img {
          box-shadow: 0 0 0 2px hsl(var(--accent) / 0.5);
        }
        #cmp-body-html a > img::after {
          content: '🔗';
        }
        /* Chips destinataires (To / Cc / Cci) */
        .chips-input {
          display: flex; flex-wrap: wrap; gap: 5px;
          padding: 5px 8px;
          border-radius: 8px;
          background: hsl(var(--bg));
          border: 1px solid hsl(var(--border));
          min-height: 40px;
          align-items: center;
          font-size: 13px;
          cursor: text;
          transition: border-color 120ms, box-shadow 120ms;
        }
        .chips-input:focus-within {
          border-color: hsl(var(--accent));
          box-shadow: 0 0 0 2px hsl(var(--accent) / 0.25);
        }
        .chips-input .chip {
          display: inline-flex; align-items: center; gap: 3px;
          padding: 2px 4px 2px 9px;
          border-radius: 5px;
          background: hsl(var(--accent) / 0.15);
          color: hsl(var(--accent));
          font-size: 12px; font-weight: 600;
          line-height: 1.3;
          max-width: 100%;
        }
        .chips-input .chip span {
          max-width: min(280px, 60vw);
          overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
        }
        .chips-input .chip.invalid {
          background: hsl(var(--danger) / 0.15);
          color: hsl(var(--danger-text));
        }
        .chips-input .chip button {
          appearance: none;
          background: transparent;
          border: 0;
          color: inherit;
          opacity: 0.65;
          font-size: 14px;
          line-height: 1;
          padding: 0 4px;
          cursor: pointer;
        }
        .chips-input .chip button:hover { opacity: 1; }
        .chips-input .chips-text {
          flex: 1;
          min-width: 140px;
          background: transparent;
          border: 0;
          outline: 0;
          color: inherit;
          font-size: 13px;
          padding: 4px 0;
        }
        /* Dropdown autocomplétion du carnet d'adresses */
        .chips-autocomplete {
          position: absolute;
          left: 0; right: 0; top: calc(100% + 4px);
          max-height: 240px;
          overflow-y: auto;
          background: hsl(var(--surface-elevated));
          border: 1px solid hsl(var(--border));
          border-radius: 10px;
          box-shadow: 0 12px 32px rgba(0,0,0,0.20);
          z-index: 60;
          display: none;
          font-size: 13px;
          padding: 4px;
        }
        .chips-autocomplete[data-open="1"] { display: block; }
        .chips-ac-item {
          display: flex; align-items: center; justify-content: space-between;
          gap: 8px;
          padding: 7px 10px;
          border-radius: 7px;
          cursor: pointer;
          color: hsl(var(--text));
          transition: background-color 100ms;
        }
        .chips-ac-item:hover,
        .chips-ac-item.is-active {
          background: hsl(var(--accent) / 0.15);
          color: hsl(var(--accent));
        }
        .chips-ac-email { font-weight: 500; }
        .chips-ac-meta {
          font-size: 11px;
          color: hsl(var(--text-muted));
          font-variant-numeric: tabular-nums;
          flex-shrink: 0;
        }
        .chips-ac-empty {
          padding: 10px 12px;
          color: hsl(var(--text-muted));
          font-size: 12px;
          font-style: italic;
        }
      `;
      document.head.appendChild(s);
    }

    // Fermeture = JAMAIS de perte : le brouillon courant est sauvegardé
    // silencieusement (sauf après un envoi réussi, où il est supprimé).
    // autosaveDraftNow / autosaveTimer sont définis plus bas (ils ont besoin
    // de captureDraftState) — close() n'est appelée que par des évènements
    // utilisateur, donc toujours après l'initialisation complète.
    let suppressDraftSave = false;
    let autosaveDraftNow = () => {};
    let autosaveTimer = null;
    const close = () => {
      try { if (!suppressDraftSave) autosaveDraftNow(); } catch (_) {}
      if (autosaveTimer) { clearInterval(autosaveTimer); autosaveTimer = null; }
      overlay.remove();
    };
    overlay.querySelector('#cmp-close').onclick = close;
    overlay.querySelector('#cmp-cancel').onclick = close;
    // Volontairement PAS de fermeture sur clic en dehors : Jordan a perdu
    // des mails ainsi. La modale ne se ferme que via × ou Annuler.
    // Idem pour Escape : on retire pour éviter une fermeture accidentelle.
    // Changement de vue : on ferme proprement la modale (avec autosauvegarde)
    // au lieu de la laisser orpheline par-dessus le nouvel écran.
    if (typeof App !== 'undefined' && App.onViewCleanup) {
      App.onViewCleanup(() => {
        if (document.body.contains(overlay)) close();
      });
    }

    // ----------------------------------------------------------------------
    // Chips destinataires (To / Cc / Cci)
    // ----------------------------------------------------------------------
    const _isValidEmail = (s) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(s);

    const makeChips = (wrapEl) => {
      const inputEl = wrapEl.querySelector('.chips-text');
      let chips = [];
      const escape = (s) => this._escape(s);

      // --- Autocomplétion (carnet d'adresses) ---
      let acDropdown = null;
      let acSuggestions = [];
      let acIndex = -1;

      const ensureAcDropdown = () => {
        if (acDropdown) return acDropdown;
        if (getComputedStyle(wrapEl).position === 'static') {
          wrapEl.style.position = 'relative';
        }
        acDropdown = document.createElement('div');
        acDropdown.className = 'chips-autocomplete';
        acDropdown.setAttribute('role', 'listbox');
        wrapEl.appendChild(acDropdown);
        return acDropdown;
      };
      const hideAc = () => {
        if (acDropdown) acDropdown.removeAttribute('data-open');
        acSuggestions = [];
        acIndex = -1;
      };
      const renderAc = () => {
        if (!window.MailAddressBook) { hideAc(); return; }
        const q = inputEl.value.trim();
        const usedSet = new Set(chips.map(c => c.toLowerCase()));
        const all = window.MailAddressBook.search(q, 20);
        acSuggestions = all.filter(s => !usedSet.has(s.email)).slice(0, 6);
        if (acSuggestions.length === 0) { hideAc(); return; }
        if (acIndex >= acSuggestions.length) acIndex = acSuggestions.length - 1;
        const dd = ensureAcDropdown();
        dd.innerHTML = acSuggestions.map((s, i) => {
          const meta = s.count > 1 ? `${s.count} fois` : '';
          return `<div class="chips-ac-item${i === acIndex ? ' is-active' : ''}" data-idx="${i}" role="option">
            <span class="chips-ac-email">${escape(s.email)}</span>
            <span class="chips-ac-meta">${meta}</span>
          </div>`;
        }).join('');
        dd.setAttribute('data-open', '1');
        [...dd.querySelectorAll('.chips-ac-item')].forEach(el => {
          el.onmousedown = (e) => {
            e.preventDefault();
            selectAc(parseInt(el.dataset.idx, 10));
          };
          el.onmouseenter = () => {
            acIndex = parseInt(el.dataset.idx, 10);
            dd.querySelectorAll('.chips-ac-item').forEach((n, j) => {
              n.classList.toggle('is-active', j === acIndex);
            });
          };
        });
      };
      const selectAc = (i) => {
        if (i < 0 || i >= acSuggestions.length) return;
        inputEl.value = acSuggestions[i].email;
        hideAc();
        tryCommit();
        inputEl.focus();
      };

      const renderChips = () => {
        [...wrapEl.querySelectorAll('.chip')].forEach(el => el.remove());
        chips.forEach((email, i) => {
          const valid = _isValidEmail(email);
          const chipEl = document.createElement('span');
          chipEl.className = 'chip' + (valid ? '' : ' invalid');
          chipEl.innerHTML = `<span title="${escape(email)}">${escape(email)}</span>` +
                             `<button type="button" data-i="${i}" title="Retirer">×</button>`;
          wrapEl.insertBefore(chipEl, inputEl);
          chipEl.querySelector('button').onclick = (e) => {
            e.preventDefault(); e.stopPropagation();
            chips.splice(i, 1);
            renderChips();
          };
        });
      };

      const tryCommit = () => {
        const raw = inputEl.value.trim().replace(/[,;]+$/, '').trim();
        if (!raw) return;
        // Permet de coller "a@x.fr, b@y.fr" et de splitter
        const parts = raw.split(/[\s,;]+/).filter(Boolean);
        parts.forEach(p => {
          if (!chips.some(c => c.toLowerCase() === p.toLowerCase())) {
            chips.push(p);
          }
        });
        inputEl.value = '';
        renderChips();
      };

      inputEl.addEventListener('keydown', (e) => {
        // Si dropdown autocomplétion ouvert, prioritaire sur le commit
        const acOpen = acDropdown && acDropdown.getAttribute('data-open') === '1' && acSuggestions.length > 0;
        if (acOpen) {
          if (e.key === 'ArrowDown') {
            e.preventDefault();
            acIndex = Math.min((acIndex < 0 ? -1 : acIndex) + 1, acSuggestions.length - 1);
            renderAc();
            return;
          }
          if (e.key === 'ArrowUp') {
            e.preventDefault();
            acIndex = Math.max(acIndex - 1, 0);
            renderAc();
            return;
          }
          if (e.key === 'Enter' && acIndex >= 0) {
            e.preventDefault();
            selectAc(acIndex);
            return;
          }
          if (e.key === 'Escape') {
            e.preventDefault();
            hideAc();
            return;
          }
          if (e.key === 'Tab' && acIndex >= 0) {
            // Tab valide la suggestion sélectionnée puis commit (comportement Gmail)
            e.preventDefault();
            selectAc(acIndex);
            return;
          }
        }

        if (e.key === 'Enter' || e.key === ',' || e.key === ';' || e.key === 'Tab') {
          if (inputEl.value.trim()) {
            e.preventDefault();
            tryCommit();
          }
        } else if (e.key === ' ' && _isValidEmail(inputEl.value.trim())) {
          // Espace après email valide → commit auto
          e.preventDefault();
          tryCommit();
        } else if (e.key === 'Backspace' && inputEl.value === '' && chips.length > 0) {
          chips.pop();
          renderChips();
          hideAc();
        }
      });
      inputEl.addEventListener('input', () => { acIndex = -1; renderAc(); });
      inputEl.addEventListener('focus', renderAc);
      inputEl.addEventListener('blur', () => {
        // Petit délai pour permettre le clic (mousedown) sur une suggestion
        setTimeout(() => {
          if (inputEl.value.trim()) tryCommit();
          hideAc();
        }, 120);
      });
      // Coller : si plusieurs adresses, splitter
      inputEl.addEventListener('paste', (e) => {
        const text = (e.clipboardData || window.clipboardData).getData('text');
        if (text && /[,;\s]/.test(text)) {
          e.preventDefault();
          inputEl.value = text;
          tryCommit();
        }
      });
      // Click sur le wrap (hors chip / input) → focus input
      wrapEl.addEventListener('click', (e) => {
        if (e.target === wrapEl) inputEl.focus();
      });

      return {
        getValues: () => chips.slice(),
        setValues: (arr) => {
          chips = (arr || []).map(String).filter(Boolean);
          renderChips();
        },
        commitPending: () => tryCommit(),
        isEmpty: () => chips.length === 0 && !inputEl.value.trim(),
        anyInvalid: () => chips.some(c => !_isValidEmail(c)),
        focus: () => inputEl.focus(),
        wrapEl, inputEl,
      };
    };

    const chipsTo  = makeChips(overlay.querySelector('#cmp-to-wrap'));
    const chipsCc  = makeChips(overlay.querySelector('#cmp-cc-wrap'));
    const chipsBcc = makeChips(overlay.querySelector('#cmp-bcc-wrap'));

    // Pré-remplissage destinataire (ex : depuis "Répondre à X")
    if (opts.prefilledTo) {
      const parts = String(opts.prefilledTo).split(/[\s,;]+/).filter(Boolean);
      chipsTo.setValues(parts);
    }

    // Toggle des lignes Cc / Cci — montrer si caché, vider + cacher si visible
    const ccRow = overlay.querySelector('#cmp-cc-row');
    const bccRow = overlay.querySelector('#cmp-bcc-row');
    const hideCc = () => {
      chipsCc.setValues([]);
      ccRow.classList.add('hidden');
    };
    const hideBcc = () => {
      chipsBcc.setValues([]);
      bccRow.classList.add('hidden');
    };
    overlay.querySelector('#cmp-toggle-cc').onclick = () => {
      if (ccRow.classList.contains('hidden')) {
        ccRow.classList.remove('hidden');
        chipsCc.focus();
      } else {
        hideCc();
      }
    };
    overlay.querySelector('#cmp-toggle-bcc').onclick = () => {
      if (bccRow.classList.contains('hidden')) {
        bccRow.classList.remove('hidden');
        chipsBcc.focus();
      } else {
        hideBcc();
      }
    };
    overlay.querySelector('#cmp-cc-remove').onclick = hideCc;
    overlay.querySelector('#cmp-bcc-remove').onclick = hideBcc;

    // Gestion mode Texte / HTML
    let mode = 'text';
    const textBtn = overlay.querySelector('#cmp-mode-text');
    const htmlBtn = overlay.querySelector('#cmp-mode-html');
    const textArea = overlay.querySelector('#cmp-body-text');
    const htmlArea = overlay.querySelector('#cmp-body-html');
    const toolbar = overlay.querySelector('#cmp-toolbar');
    // Le texte a-t-il été modifié à la main depuis la dernière synchro ?
    // Sert à reconstruire le HTML quand on rebascule (sinon on enverrait
    // une version périmée du message).
    let textDirty = false;
    textArea.addEventListener('input', () => { textDirty = true; });

    const previewTopBtn = overlay.querySelector('#cmp-preview-top');
    const setMode = (m) => {
      mode = m;
      if (m === 'text') {
        textBtn.className = 'px-2.5 py-1 rounded-lg font-semibold bg-accent/15 text-accent';
        htmlBtn.className = 'px-2.5 py-1 rounded-lg font-semibold text-text-muted hover:bg-bg';
        textArea.classList.remove('hidden');
        htmlArea.classList.add('hidden');
        toolbar.classList.add('hidden');
        if (previewTopBtn) previewTopBtn.classList.add('hidden');
        // Si on revient en texte depuis HTML : convertit TOUJOURS le HTML en
        // texte basique (avant : seulement si la zone texte était vide, donc
        // on retombait sur une version périmée du message).
        if (htmlArea.innerHTML.trim()) {
          textArea.value = htmlArea.innerText;
          textDirty = false;
        }
      } else {
        textBtn.className = 'px-2.5 py-1 rounded-lg font-semibold text-text-muted hover:bg-bg';
        htmlBtn.className = 'px-2.5 py-1 rounded-lg font-semibold bg-accent/15 text-accent';
        textArea.classList.add('hidden');
        htmlArea.classList.remove('hidden');
        toolbar.classList.remove('hidden');
        if (previewTopBtn) previewTopBtn.classList.remove('hidden');
        // Si on passe en HTML avec du texte déjà : convertit en paragraphes.
        // Aussi quand le texte a été modifié à la main depuis la dernière
        // synchro (sinon l'envoi partirait avec l'ancien HTML), en
        // reconstruisant le bloc signature à part pour ne pas le perdre.
        if (textArea.value && (!htmlArea.innerHTML || textDirty)) {
          let raw = textArea.value;
          if (signature && raw.endsWith('\n\n' + signature)) {
            raw = raw.slice(0, -(signature.length + 2));
          } else if (signature && raw.endsWith(signature)) {
            raw = raw.slice(0, -signature.length);
          }
          const mainHtml = raw.split(/\n\n+/).filter(p => p.trim().length)
            .map(p => `<p>${this._escape(p).replace(/\n/g, '<br>')}</p>`).join('') || '<p><br></p>';
          let sigBlockHtml = '';
          if (signatureHtml) {
            sigBlockHtml = SIG_MARK_HTML + signatureHtml + SIG_MARK_HTML_END;
          } else if (signature) {
            const sigAsHtml = signature.split(/\n\n+/)
              .map(p => `<p>${this._escape(p).replace(/\n/g, '<br>')}</p>`).join('');
            sigBlockHtml = SIG_MARK_HTML + sigAsHtml + SIG_MARK_HTML_END;
          }
          htmlArea.innerHTML = mainHtml + sigBlockHtml;
          textDirty = false;
        }
        // Force Chrome à utiliser <p> pour les nouveaux paragraphes (Entrée),
        // sinon les boutons "liste" / "titre" / "citation" ne trouvent pas
        // de bloc à transformer.
        try { document.execCommand('defaultParagraphSeparator', false, 'p'); } catch (_) {}
        // Si la zone est vide : on amorce avec un paragraphe vide pour que
        // formatBlock / insertList aient un bloc cible dès le premier mot.
        if (!htmlArea.innerHTML.trim()) {
          htmlArea.innerHTML = '<p><br></p>';
        }
        htmlArea.focus();
        // Place le curseur dans le premier paragraphe (sinon il flotte hors bloc)
        try {
          const firstBlock = htmlArea.querySelector('p, div, h1, h2, h3, blockquote, li');
          if (firstBlock) {
            const range = document.createRange();
            range.selectNodeContents(firstBlock);
            range.collapse(false);
            const sel = window.getSelection();
            sel.removeAllRanges();
            sel.addRange(range);
          }
        } catch (_) {}
      }
    };
    textBtn.onclick = () => setMode('text');
    htmlBtn.onclick = () => setMode('html');

    // Toggle fond clair / sombre de la zone d'écriture (préférence persistée).
    // Inspiré d'Outlook : on lit toujours sur fond clair par défaut, mais on
    // peut basculer pour soulager les yeux la nuit. Indépendant du thème global.
    const bgToggleBtn  = overlay.querySelector('#cmp-bg-toggle');
    const bgToggleIcon = overlay.querySelector('#cmp-bg-toggle-icon');
    const BG_PREF_KEY  = 'triskell.composer.bgDark';
    const applyEditorBg = (dark) => {
      [textArea, htmlArea].forEach(el => el.classList.toggle('cmp-editor-dark', dark));
      bgToggleIcon.textContent = dark ? '☾' : '☀';
      bgToggleBtn.title = dark
        ? 'Fond actuel : sombre — cliquer pour passer en fond clair'
        : 'Fond actuel : clair — cliquer pour passer en fond sombre';
    };
    let bgDark = false;
    try { bgDark = localStorage.getItem(BG_PREF_KEY) === '1'; } catch (_) {}
    applyEditorBg(bgDark);
    bgToggleBtn.onclick = () => {
      bgDark = !bgDark;
      applyEditorBg(bgDark);
      try { localStorage.setItem(BG_PREF_KEY, bgDark ? '1' : '0'); } catch (_) {}
    };

    // ----------------------------------------------------------------------
    // Pièces jointes + images inline (CID)
    // ----------------------------------------------------------------------
    // Format d'une entrée : { filename, content_b64, content_type, size, inline, cid }
    const attachments = Array.isArray(opts.prefilledAttachments)
      ? opts.prefilledAttachments.map(a => ({ ...a }))
      : [];
    const MAX_TOTAL_BYTES = 22 * 1024 * 1024; // 22 Mo (la plupart des SMTP plafonnent à 25)

    const attListEl   = overlay.querySelector('#cmp-attachments-list');
    const attInputEl  = overlay.querySelector('#cmp-attachment-input');
    const attAddBtn   = overlay.querySelector('#cmp-add-attachment');
    const attTotalEl  = overlay.querySelector('#cmp-attachments-total');

    const fmtSize = (n) => {
      if (n == null) return '';
      if (n < 1024) return `${n} o`;
      if (n < 1024 * 1024) return `${Math.round(n / 1024)} Ko`;
      return `${(n / 1024 / 1024).toFixed(1)} Mo`;
    };

    const totalSize = () => attachments.reduce((s, a) => s + (a.size || 0), 0);

    const renderAttachments = () => {
      const visible = attachments.filter(a => !a.inline);
      if (!visible.length) {
        attListEl.innerHTML = '<div class="text-text-muted italic">Aucune pièce jointe pour l’instant.</div>';
      } else {
        attListEl.innerHTML = visible.map((a) => {
          const realIdx = attachments.indexOf(a);
          return `<div class="flex items-center justify-between gap-2 px-3 py-2 rounded-lg bg-bg border border-border">
             <div class="flex items-center gap-2 min-w-0 flex-1">
               <span class="shrink-0">📄</span>
               <span class="truncate font-medium text-text">${this._escape(a.filename)}</span>
               <span class="text-text-muted shrink-0">${fmtSize(a.size)}</span>
             </div>
             <button data-att-rm="${realIdx}" type="button" title="Retirer cette pièce jointe"
                     class="text-text-muted hover:text-danger text-lg leading-none px-1">×</button>
           </div>`;
        }).join('');
        attListEl.querySelectorAll('[data-att-rm]').forEach(b => {
          b.onclick = () => {
            attachments.splice(Number(b.dataset.attRm), 1);
            renderAttachments();
          };
        });
      }
      const tot = totalSize();
      if (tot > 0) {
        const over = tot > MAX_TOTAL_BYTES;
        attTotalEl.textContent = `Total : ${fmtSize(tot)}${over ? ' — limite SMTP dépassée, retire des fichiers.' : ' / 22 Mo max recommandé'}`;
        attTotalEl.className = `text-[11px] mt-1.5 ${over ? 'text-danger font-semibold' : 'text-text-muted'}`;
      } else {
        attTotalEl.textContent = '';
      }
    };
    renderAttachments();

    const readFileAsBase64 = (file) => new Promise((resolve, reject) => {
      const r = new FileReader();
      r.onload = () => {
        const dataUrl = String(r.result || '');
        const idx = dataUrl.indexOf(',');
        resolve(idx >= 0 ? dataUrl.slice(idx + 1) : '');
      };
      r.onerror = () => reject(r.error || new Error('Lecture du fichier impossible'));
      r.readAsDataURL(file);
    });

    const addFiles = async (fileList) => {
      for (const file of Array.from(fileList || [])) {
        try {
          const b64 = await readFileAsBase64(file);
          attachments.push({
            filename: file.name,
            content_b64: b64,
            content_type: file.type || 'application/octet-stream',
            size: file.size,
            inline: false,
            cid: '',
          });
        } catch (e) {
          console.error('Pièce jointe KO :', file.name, e);
        }
      }
      renderAttachments();
    };

    attAddBtn.onclick = () => attInputEl.click();
    attInputEl.onchange = async () => {
      await addFiles(attInputEl.files);
      attInputEl.value = '';
    };

    // Insère une image (déjà lue côté JS) dans le corps en mode CID inline.
    // Utilisé par le bouton 🖼 toolbar ET par le drop d'image après choix
    // utilisateur "Dans le corps du mail".
    const insertImageFile = async (file) => {
      if (mode === 'text') setMode('html');
      try {
        const b64 = await readFileAsBase64(file);
        const cid = 'img_' + Math.random().toString(36).slice(2, 10) + '_' + Date.now().toString(36);
        attachments.push({
          filename: file.name || `image-${cid}.png`,
          content_b64: b64,
          content_type: file.type || 'image/png',
          size: file.size,
          inline: true,
          cid,
        });
        const dataUrl = `data:${file.type || 'image/png'};base64,${b64}`;
        htmlArea.focus();
        document.execCommand('insertHTML', false,
          `<img data-cid="${cid}" src="${dataUrl}" alt="${this._escape(file.name || 'image')}" style="max-width:100%; height:auto; display:block; margin:8px 0;">`);
        renderAttachments();
      } catch (e) {
        console.error('Insertion image KO :', e);
        Toast.error('Impossible de lire cette image.');
      }
    };

    // Insertion d'image depuis le bouton toolbar 🖼 → ouvre un file picker
    const insertImageInBody = async () => {
      const picker = document.createElement('input');
      picker.type = 'file';
      picker.accept = 'image/*';
      picker.onchange = async () => {
        const file = picker.files && picker.files[0];
        if (!file) return;
        await insertImageFile(file);
      };
      picker.click();
    };

    // Petite modale qui demande comment ajouter une (ou plusieurs) image(s)
    // droppée(s) : dans le corps du mail OU en pièce jointe.
    const askImageMode = (images) => new Promise((resolve) => {
      const title = images.length === 1
        ? this._escape(images[0].name || 'image')
        : `${images.length} images`;
      const subtitle = images.length === 1
        ? 'Comment veux-tu ajouter cette image au mail ?'
        : `Comment veux-tu ajouter ces ${images.length} images au mail ?`;
      const ov = document.createElement('div');
      ov.className = 'fixed inset-0 z-[230] flex items-center justify-center p-4';
      ov.style.background = 'rgba(15,23,42,0.75)';
      ov.style.backdropFilter = 'blur(8px)';
      ov.innerHTML = `
        <div class="bg-surface rounded-2xl shadow-hero w-full max-w-sm border border-border animate-slide-up flex flex-col overflow-hidden">
          <div class="px-5 pt-4 pb-3 border-b border-border bg-surface-elevated">
            <div class="text-[10px] font-bold uppercase tracking-widest text-text-muted mb-0.5">IMAGE DÉPOSÉE</div>
            <h3 class="text-base font-bold leading-tight truncate">${title}</h3>
            <p class="text-xs text-text-muted mt-1">${subtitle}</p>
          </div>
          <div class="p-4 space-y-2">
            <button data-img-choice="inline"
                    class="w-full text-left px-4 py-3 rounded-xl border-2 border-accent bg-accent/10 hover:bg-accent/20 transition-colors">
              <div class="font-semibold text-text flex items-center gap-2">
                <svg class="w-4 h-4 text-accent shrink-0" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
                <span>Dans le corps du mail</span>
              </div>
              <div class="text-xs text-text-muted mt-1">L'image s'affiche directement dans le texte — recommandé pour les visuels.</div>
            </button>
            <button data-img-choice="attach"
                    class="w-full text-left px-4 py-3 rounded-xl border border-border hover:border-accent hover:bg-bg transition-colors">
              <div class="font-semibold text-text flex items-center gap-2">
                <svg class="w-4 h-4 text-text-muted shrink-0" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48"/></svg>
                <span>En pièce jointe</span>
              </div>
              <div class="text-xs text-text-muted mt-1">L'image est attachée au mail, le destinataire la télécharge.</div>
            </button>
          </div>
          <div class="px-5 pb-4 flex items-center justify-end">
            <button data-img-choice="cancel" class="text-xs text-text-muted hover:text-danger">Annuler</button>
          </div>
        </div>
      `;
      document.body.appendChild(ov);
      const finish = (choice) => {
        document.removeEventListener('keydown', escListener);
        ov.remove();
        resolve(choice);
      };
      const escListener = (e) => { if (e.key === 'Escape') finish('cancel'); };
      document.addEventListener('keydown', escListener);
      ov.addEventListener('click', (e) => {
        const btn = e.target.closest('[data-img-choice]');
        if (btn) finish(btn.dataset.imgChoice);
        else if (e.target === ov) finish('cancel');
      });
    });

    // Drag & drop sur la zone composer.
    // Images → on demande : corps du mail OU pièce jointe.
    // Autres fichiers → pièce jointe directement.
    overlay.addEventListener('dragover', (e) => {
      if (e.dataTransfer && Array.from(e.dataTransfer.types || []).includes('Files')) {
        e.preventDefault();
      }
    });
    overlay.addEventListener('drop', async (e) => {
      if (!e.dataTransfer || !e.dataTransfer.files || !e.dataTransfer.files.length) return;
      e.preventDefault();
      const files = Array.from(e.dataTransfer.files);
      const images = files.filter(f => f.type && f.type.startsWith('image/'));
      const others = files.filter(f => !f.type || !f.type.startsWith('image/'));
      if (others.length) await addFiles(others);
      if (images.length) {
        const choice = await askImageMode(images);
        if (choice === 'inline') {
          for (const img of images) {
            await insertImageFile(img);
          }
        } else if (choice === 'attach') {
          await addFiles(images);
        }
        // choice === 'cancel' → on ignore les images
      }
    });

    // Sauvegarde de la sélection (pour les pickers de couleur qui volent le focus)
    let savedRange = null;
    const saveSelection = () => {
      const sel = window.getSelection();
      if (sel.rangeCount > 0 && htmlArea.contains(sel.anchorNode)) {
        savedRange = sel.getRangeAt(0).cloneRange();
      }
    };
    const restoreSelection = () => {
      if (!savedRange) return;
      htmlArea.focus();
      const sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(savedRange);
    };
    htmlArea.addEventListener('mouseup', saveSelection);
    htmlArea.addEventListener('keyup', saveSelection);

    // Bouton Aperçu déplacé en haut (à côté de "Texte / HTML enrichi")
    if (previewTopBtn) {
      previewTopBtn.onclick = (e) => {
        e.preventDefault();
        const subj = (overlay.querySelector('#cmp-subject').value || '').trim();
        const fromSel = overlay.querySelector('#cmp-from');
        const fromLabel = fromSel.options[fromSel.selectedIndex]?.text || '';
        const to = chipsTo.getValues().join(', ');
        this._openHtmlPreview(htmlArea.innerHTML, { subject: subj, from: fromLabel, to });
      };
    }

    // Inputs couleur natifs : appliquent foreColor / hiliteColor sur la sélection sauvée
    const textColorInput = overlay.querySelector('#cmp-text-color-input');
    const bgColorInput   = overlay.querySelector('#cmp-bg-color-input');
    const textColorBar   = overlay.querySelector('#cmp-text-color-bar');
    const bgColorBar     = overlay.querySelector('#cmp-bg-color-bar');
    textColorInput.addEventListener('input', (e) => {
      restoreSelection();
      document.execCommand('foreColor', false, e.target.value);
      textColorBar.style.background = e.target.value;
    });
    bgColorInput.addEventListener('input', (e) => {
      restoreSelection();
      document.execCommand('hiliteColor', false, e.target.value);
      bgColorBar.style.background = e.target.value;
    });

    // Empêche les boutons de voler le focus à la zone de saisie
    // (sinon la sélection / position du curseur est perdue et formatBlock,
    //  insertUnorderedList, etc. ne s'appliquent plus correctement).
    toolbar.querySelectorAll('[data-cmd]').forEach(btn => {
      btn.addEventListener('mousedown', (e) => e.preventDefault());
    });

    // -- Helpers DOM pour les commandes "bloc" (listes, titre, citation) --
    // On n'utilise PAS document.execCommand('insertUnorderedList' / 'formatBlock')
    // parce que ces commandes sont dépréciées et leur comportement est instable
    // selon la version de Chromium (les boutons paraissent ne rien faire si
    // le contenu n'est pas dans un bloc supporté).
    const BLOCK_TAGS = new Set([
      'P', 'DIV', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'BLOCKQUOTE', 'LI', 'PRE'
    ]);
    const findBlock = (node) => {
      let n = node;
      while (n && n !== htmlArea) {
        if (n.nodeType === Node.ELEMENT_NODE && BLOCK_TAGS.has(n.tagName)) {
          return n;
        }
        n = n.parentNode;
      }
      return null;
    };
    const placeCursorAtEnd = (el) => {
      const r = document.createRange();
      r.selectNodeContents(el);
      r.collapse(false);
      const sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(r);
    };
    // Si la zone contient du texte brut ou des <br> hors paragraphe,
    // on re-emballe tout en <p> pour avoir des blocs identifiables.
    const normalizeBlocks = () => {
      const sel = window.getSelection();
      let caretText = '';
      if (sel.rangeCount && htmlArea.contains(sel.anchorNode)) {
        const pre = document.createRange();
        pre.selectNodeContents(htmlArea);
        pre.setEnd(sel.anchorNode, sel.anchorOffset);
        caretText = pre.toString();
      }
      const hasRawChild = Array.from(htmlArea.childNodes).some(n =>
        n.nodeType === Node.TEXT_NODE ||
        (n.nodeType === Node.ELEMENT_NODE && n.tagName === 'BR')
      );
      if (!hasRawChild) return;
      const html = htmlArea.innerHTML
        .replace(/<div[^>]*>/gi, '\n')
        .replace(/<\/div>/gi, '')
        .replace(/<br\s*\/?>/gi, '\n');
      const tmp = document.createElement('div');
      tmp.innerHTML = html;
      const lines = (tmp.innerText || '').split('\n');
      htmlArea.innerHTML = lines
        .map(l => `<p>${this._escape(l) || '<br>'}</p>`).join('');
      // Replace le curseur à la même position texte
      try {
        let remaining = caretText.length;
        const walker = document.createTreeWalker(htmlArea, NodeFilter.SHOW_TEXT);
        let node, placed = false;
        while ((node = walker.nextNode())) {
          if (remaining <= node.length) {
            const r = document.createRange();
            r.setStart(node, remaining);
            r.collapse(true);
            sel.removeAllRanges();
            sel.addRange(r);
            placed = true;
            break;
          }
          remaining -= node.length;
        }
        if (!placed) {
          const last = htmlArea.lastElementChild;
          if (last) placeCursorAtEnd(last);
        }
      } catch (_) {}
    };
    // Garantit qu'on a une sélection placée dans un bloc de htmlArea.
    // Si l'utilisateur a cliqué le bouton sans avoir posé le curseur dans
    // l'éditeur (ex : il vient de basculer en HTML enrichi puis clique
    // directement sur "•"), on place le curseur à la fin du dernier bloc
    // utile (en évitant la signature, qui est dans <div data-signature-block>).
    const ensureCaretInEditor = () => {
      htmlArea.focus();
      const sel = window.getSelection();
      const inEditor = sel.rangeCount && htmlArea.contains(sel.anchorNode)
                       && sel.anchorNode !== htmlArea;
      if (inEditor) return;
      // Aucune sélection utilisable : on cherche un bloc cible
      if (!htmlArea.firstElementChild) {
        htmlArea.innerHTML = '<p><br></p>';
      }
      // Préfère un bloc HORS de la signature
      const candidates = Array.from(
        htmlArea.querySelectorAll('p, div, h1, h2, h3, h4, blockquote, li')
      ).filter(el => !el.closest('[data-signature-block]'));
      const target = candidates[candidates.length - 1]
                  || htmlArea.querySelector('p, div, h1, h2, h3, h4, blockquote, li')
                  || htmlArea.firstElementChild;
      placeCursorAtEnd(target);
    };
    // Applique / bascule une liste (UL ou OL) sur le bloc courant
    const applyList = (listTag /* 'UL' ou 'OL' */) => {
      ensureCaretInEditor();
      normalizeBlocks();
      const sel = window.getSelection();
      if (!sel.rangeCount) { ensureCaretInEditor(); }
      let block = findBlock(sel.anchorNode);
      if (!block) {
        if (!htmlArea.firstElementChild) {
          htmlArea.innerHTML = '<p><br></p>';
        }
        block = htmlArea.querySelector('p, div, h1, h2, h3, h4, blockquote, li')
             || htmlArea.firstElementChild;
      }
      if (block.tagName === 'LI') {
        const list = block.parentNode;
        if (list && list.tagName === listTag) {
          // Toggle off : LI → P
          const p = document.createElement('p');
          p.innerHTML = block.innerHTML || '<br>';
          list.parentNode.insertBefore(p, list.nextSibling);
          list.removeChild(block);
          if (!list.children.length) list.parentNode.removeChild(list);
          placeCursorAtEnd(p);
        } else if (list) {
          // Bascule entre UL et OL : on change le tag de la liste
          const newList = document.createElement(listTag.toLowerCase());
          while (list.firstChild) newList.appendChild(list.firstChild);
          list.parentNode.replaceChild(newList, list);
          const newLi = Array.from(newList.children).find(li => li.tagName === 'LI');
          if (newLi) placeCursorAtEnd(newLi);
        }
        return;
      }
      // Wrap le bloc courant dans une nouvelle liste
      const list = document.createElement(listTag.toLowerCase());
      const li = document.createElement('li');
      li.innerHTML = block.innerHTML || '<br>';
      list.appendChild(li);
      block.parentNode.replaceChild(list, block);
      placeCursorAtEnd(li);
    };
    // Applique / bascule un tag de bloc (h2, blockquote, p…)
    const applyBlockTag = (tag /* 'h2', 'blockquote', 'p'… */) => {
      ensureCaretInEditor();
      normalizeBlocks();
      const sel = window.getSelection();
      if (!sel.rangeCount) { ensureCaretInEditor(); }
      let block = findBlock(sel.anchorNode);
      if (!block) {
        if (!htmlArea.firstElementChild) {
          htmlArea.innerHTML = '<p><br></p>';
        }
        block = htmlArea.querySelector('p, div, h1, h2, h3, h4, blockquote, li')
             || htmlArea.firstElementChild;
      }
      // Toggle : si déjà du bon tag → repasse en <p>
      if (block.tagName.toLowerCase() === tag.toLowerCase()) {
        const p = document.createElement('p');
        p.innerHTML = block.innerHTML || '<br>';
        block.parentNode.replaceChild(p, block);
        placeCursorAtEnd(p);
        return;
      }
      const newBlock = document.createElement(tag);
      newBlock.innerHTML = block.innerHTML || '<br>';
      if (block.tagName === 'LI') {
        // Sort l'item de la liste et le remplace par le nouveau bloc
        const list = block.parentNode;
        list.parentNode.insertBefore(newBlock, list.nextSibling);
        list.removeChild(block);
        if (!list.children.length) list.parentNode.removeChild(list);
      } else {
        block.parentNode.replaceChild(newBlock, block);
      }
      placeCursorAtEnd(newBlock);
    };

    // Boutons toolbar HTML
    toolbar.querySelectorAll('[data-cmd]').forEach(btn => {
      btn.onclick = (e) => {
        e.preventDefault();
        const cmd = btn.dataset.cmd;
        // Pour les pickers de couleur on sauve la sélection AVANT d'ouvrir
        if (cmd === 'text-color') {
          saveSelection();
          textColorInput.click();
          return;
        }
        if (cmd === 'bg-color') {
          saveSelection();
          bgColorInput.click();
          return;
        }
        htmlArea.focus();
        if (cmd === 'createLink') {
          const url = prompt('URL du lien :', 'https://');
          if (url) document.execCommand('createLink', false, url);
        } else if (cmd === 'insert-image') {
          insertImageInBody();
        } else if (cmd === 'paste-html') {
          this._openPasteHtmlDialog(htmlArea);
        } else if (cmd === 'preview') {
          const subj = (overlay.querySelector('#cmp-subject').value || '').trim();
          const fromSel = overlay.querySelector('#cmp-from');
          const fromLabel = fromSel.options[fromSel.selectedIndex]?.text || '';
          const to = chipsTo.getValues().join(', ');
          this._openHtmlPreview(htmlArea.innerHTML, { subject: subj, from: fromLabel, to });
        } else if (cmd === 'insertUnorderedList') {
          applyList('UL');
        } else if (cmd === 'insertOrderedList') {
          applyList('OL');
        } else if (cmd.startsWith('formatBlock-')) {
          const tag = cmd.split('-')[1];
          applyBlockTag(tag);
        } else {
          document.execCommand(cmd, false, null);
        }
      };
    });

    // Ctrl+Entrée pour envoyer
    overlay.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        e.preventDefault();
        overlay.querySelector('#cmp-send').click();
      }
    });

    // -------- Templates --------
    const tplTrigger = overlay.querySelector('#cmp-tpl-trigger');
    const tplMenu    = overlay.querySelector('#cmp-tpl-menu');
    const tplList    = overlay.querySelector('#cmp-tpl-list');
    const subjectInput = overlay.querySelector('#cmp-subject');

    // ---- Bouton "Produit" : insère un bloc Catalogue dans le mail ----
    const productBtn = overlay.querySelector('#cmp-product-trigger');
    if (productBtn && typeof Catalogue !== 'undefined') {
      productBtn.onclick = (e) => {
        e.preventDefault();
        Catalogue.pickProduct((product) => {
          if (!product) return;
          if (mode === 'html') {
            // Insère le bloc HTML à la position du curseur dans le contenteditable
            const html = Catalogue.snippetHtml(product);
            htmlArea.focus();
            try {
              const sel = window.getSelection();
              if (sel && sel.rangeCount && htmlArea.contains(sel.anchorNode)) {
                const range = sel.getRangeAt(0);
                range.deleteContents();
                const frag = range.createContextualFragment(html + '<p><br></p>');
                range.insertNode(frag);
                range.collapse(false);
              } else {
                htmlArea.insertAdjacentHTML('beforeend', html + '<p><br></p>');
              }
            } catch (err) {
              htmlArea.insertAdjacentHTML('beforeend', html);
            }
          } else {
            // Mode texte : injecte le snippet texte à la position du curseur
            const block = Catalogue.snippetText(product);
            const ta = textArea;
            const start = ta.selectionStart || 0;
            const end   = ta.selectionEnd || start;
            const before = ta.value.substring(0, start);
            const after  = ta.value.substring(end);
            const sep = (before && !before.endsWith('\n')) ? '\n\n' : '';
            const tail = (after && !after.startsWith('\n')) ? '\n\n' : '';
            ta.value = before + sep + block + tail + after;
            const pos = (before + sep + block + tail).length;
            ta.focus();
            ta.setSelectionRange(pos, pos);
          }
        });
      };
    }

    const loadTemplates = async () => {
      tplList.innerHTML = '<div class="px-4 py-3 text-xs text-text-muted">Chargement…</div>';
      const r = await App.api.user_mail_templates_list();
      const tpls = (r && r.ok) ? (r.templates || []) : [];
      if (!tpls.length) {
        tplList.innerHTML = '<div class="px-4 py-3 text-xs text-text-muted">Aucun modèle encore. Sauvegarde ton contenu actuel ci-dessous.</div>';
        return;
      }
      tplList.innerHTML = tpls.map(t => `
        <button data-tpl-id="${this._escape(t.id)}" class="w-full px-4 py-2 text-left text-xs hover:bg-bg flex flex-col gap-0.5">
          <span class="font-semibold text-text truncate">${this._escape(t.name)}</span>
          ${t.subject_default ? `<span class="text-text-muted truncate">${this._escape(t.subject_default)}</span>` : ''}
        </button>
      `).join('');
      tplList.querySelectorAll('[data-tpl-id]').forEach(btn => {
        btn.onclick = () => {
          const tpl = tpls.find(x => x.id === btn.dataset.tplId);
          if (!tpl) return;
          // Insère le HTML : bascule en mode HTML et remplace le body
          setMode('html');
          htmlArea.innerHTML = tpl.body_html || '';
          // Pré-remplit le sujet si vide et template a un sujet par défaut
          if (tpl.subject_default && !subjectInput.value.trim()) {
            subjectInput.value = tpl.subject_default;
          }
          tplMenu.classList.add('hidden');
          htmlArea.focus();
        };
      });
    };

    tplTrigger.onclick = (e) => {
      e.stopPropagation();
      const wasHidden = tplMenu.classList.contains('hidden');
      tplMenu.classList.toggle('hidden');
      if (wasHidden) loadTemplates();
    };
    // Click ailleurs ferme le menu
    overlay.addEventListener('click', (e) => {
      if (!tplTrigger.contains(e.target) && !tplMenu.contains(e.target)) {
        tplMenu.classList.add('hidden');
      }
    });

    // Sauvegarder comme template
    overlay.querySelector('#cmp-tpl-save').onclick = async () => {
      // Récupère le contenu courant (HTML ou texte converti en HTML basique)
      let htmlContent = '';
      if (mode === 'html') {
        htmlContent = htmlArea.innerHTML.trim();
      } else {
        const txt = textArea.value;
        htmlContent = txt.split(/\n\n+/)
          .map(p => `<p>${this._escape(p).replace(/\n/g, '<br>')}</p>`).join('');
      }
      if (!htmlContent || htmlContent === '<p></p>') {
        Toast.warn('Le contenu est vide. Écris quelque chose avant de sauvegarder.');
        return;
      }
      const name = prompt('Nom du modèle (ex : "Devis envoyé", "Suivi 1 mois") :');
      if (!name) return; // null = annuler
      const useSubject = subjectInput.value.trim();
      const wantSubj = useSubject && await Dialog.confirm(
        `Sauvegarder aussi l'objet "${useSubject}" comme objet par défaut du modèle ?`,
        { title: 'Objet du modèle', okLabel: "Oui, garder l'objet", cancelLabel: 'Non, sans objet' });
      try {
        const r = await App.api.user_mail_template_save({
          template: { name, body_html: htmlContent, subject_default: wantSubj ? useSubject : '' }
        });
        if (r && r.ok) {
          tplMenu.classList.add('hidden');
          // Petite confirmation visuelle
          const status = overlay.querySelector('#cmp-status');
          status.textContent = `✓ Modèle "${name}" sauvegardé.`;
          status.className = 'text-xs text-success';
          setTimeout(() => { if (status.textContent.startsWith('✓ Modèle')) status.textContent = ''; }, 3000);
        } else {
          console.error('[mails] user_mail_template_save :', r && r.error);
          Toast.error('La sauvegarde du modèle a échoué.');
        }
      } catch (e) {
        Toast.friendlyError(e, 'La sauvegarde du modèle a échoué.');
      }
    };

    // Gérer les templates
    overlay.querySelector('#cmp-tpl-manage').onclick = () => {
      tplMenu.classList.add('hidden');
      this._openTemplatesManager();
    };

    // ----- Gestion dynamique de la signature -----
    // Le body est conceptuellement [partie écrite par le user] + [marker] + [signature]
    // On marque la signature avec un commentaire HTML invisible pour pouvoir la
    // remplacer proprement quand le user change de signature.
    //
    // - contenteditable=false : la signature est un bloc figé. Pas d'édition
    //   inline dans le composeur — la gestion se fait depuis les Réglages.
    //   Évite aussi que la sélection du curseur "tombe" dans le bloc et
    //   colle le texte tapé dedans par erreur.
    // - spellcheck=false : sans ça, le correcteur du navigateur souligne en
    //   rouge tous les mots de marque (Triskell, Cofondateurs…), les URLs
    //   et les emails de la signature — l'affichage devient illisible.
    const SIG_MARK_HTML = '<div data-signature-block contenteditable="false" spellcheck="false" style="margin-top:1.5em; cursor:default; user-select:text;">';
    const SIG_MARK_HTML_END = '</div>';

    const applySignature = (sig) => {
      const sigText = sig?.body_text || '';
      const sigHtml = sig?.body_html || '';
      // -- Texte --
      // Stratégie : retire l'ancienne signature (après le dernier double-saut),
      // remet la nouvelle. Si l'utilisateur n'a rien écrit avant, on garde tel quel.
      const taVal = textArea.value;
      // On retire l'ancienne signature en se basant sur celle qui était en place :
      // si textArea finit par "\n\n{ancienne sig}", on la retire
      let body = taVal;
      if (signature && body.endsWith('\n\n' + signature)) {
        body = body.slice(0, -(signature.length + 2));
      } else if (signature && body.endsWith(signature)) {
        body = body.slice(0, -signature.length);
      }
      // Ajoute la nouvelle
      textArea.value = sigText ? (body || '') + (body && !body.endsWith('\n\n') ? '\n\n' : (body ? '\n' : '\n\n')) + sigText : body;
      // -- HTML --
      // On retire l'ancien bloc signature (marqué par data-signature-block) s'il existe
      let html = htmlArea.innerHTML;
      html = html.replace(/<div data-signature-block[\s\S]*?<\/div>\s*$/, '');
      if (sigHtml) {
        html = html + SIG_MARK_HTML + sigHtml + SIG_MARK_HTML_END;
      } else if (sigText) {
        const sigAsHtml = sigText.split(/\n\n+/)
          .map(p => `<p>${this._escape(p).replace(/\n/g, '<br>')}</p>`).join('');
        html = html + SIG_MARK_HTML + sigAsHtml + SIG_MARK_HTML_END;
      }
      htmlArea.innerHTML = html;
      // Mémorise pour le prochain swap
      signature = sigText;
      signatureHtml = sigHtml;
      currentSig = sig;
    };

    // Pré-remplissage initial avec la signature sélectionnée
    if (currentSig) {
      // applique sans wiper : textArea/htmlArea sont encore vides à ce stade
      if (signature) {
        textArea.value = '\n\n' + signature;
        setTimeout(() => textArea.setSelectionRange(0, 0), 100);
      }
      if (signatureHtml) {
        htmlArea.innerHTML = `<p><br></p><p><br></p>${SIG_MARK_HTML}${signatureHtml}${SIG_MARK_HTML_END}`;
      } else if (signature) {
        const sigAsHtml = signature.split(/\n\n+/)
          .map(p => `<p>${this._escape(p).replace(/\n/g, '<br>')}</p>`).join('');
        htmlArea.innerHTML = `<p><br></p><p><br></p>${SIG_MARK_HTML}${sigAsHtml}${SIG_MARK_HTML_END}`;
      }
    }

    // Pré-remplissage du corps HTML (workflow prospection en direct)
    if (opts.prefilledBodyHtml) {
      // Si signature présente, insère le body AVANT la signature
      const sigStart = htmlArea.innerHTML.indexOf(SIG_MARK_HTML);
      if (sigStart >= 0) {
        const sigBlock = htmlArea.innerHTML.slice(sigStart);
        htmlArea.innerHTML = opts.prefilledBodyHtml + '<p><br></p>' + sigBlock;
      } else {
        htmlArea.innerHTML = opts.prefilledBodyHtml;
      }
    }

    // Bind du dropdown signature : remplace dans le body
    const sigSelect = overlay.querySelector('#cmp-signature');
    if (sigSelect) {
      sigSelect.onchange = () => {
        const id = sigSelect.value;
        const sig = id ? signatures.find(s => s.id === id) : null;
        applySignature(sig);
      };
    }

    // Bind du dropdown compte expéditeur : on filtre les signatures visibles
    // pour ce compte et on auto-sélectionne la bonne signature.
    const fromSel = overlay.querySelector('#cmp-from');
    if (fromSel) {
      fromSel.addEventListener('change', () => {
        const accId = fromSel.value;
        const visible = signaturesForAccount(accId);
        const newSig = pickSigForAccount(accId);
        // Re-rend les options du dropdown signature pour ne montrer que celles
        // pertinentes pour le nouveau compte.
        if (sigSelect) {
          const opts = ['<option value="">Sans signature</option>'];
          visible.forEach(s => {
            const sel = (newSig && s.id === newSig.id) ? ' selected' : '';
            opts.push(`<option value="${this._escape(s.id)}"${sel}>${this._escape(s.name)}</option>`);
          });
          sigSelect.innerHTML = opts.join('');
        }
        // Applique la nouvelle signature dans le body si elle a changé.
        if ((newSig?.id || '') !== (currentSig?.id || '')) {
          applySignature(newSig);
        }
      });
    }

    // Clic sur une image insérée dans le corps → modale pour la rendre
    // cliquable (ajouter / modifier / retirer une URL de destination).
    htmlArea.addEventListener('click', (e) => {
      const img = e.target.closest('img');
      if (img && htmlArea.contains(img)) {
        e.preventDefault();
        e.stopPropagation();
        this._openImageLinkDialog(img);
      }
    });

    // ----------------------------------------------------------------------
    // Brouillons (localStorage, PLUSIEURS brouillons — voir _draftsLoad)
    // ----------------------------------------------------------------------
    // Permet de quitter le composer sans perdre ce qu'on a écrit. Stocké
    // dans le navigateur (pas synchronisé entre PC pour l'instant).
    // Chaque composeur travaille sur SON brouillon (id mémorisé ci-dessous) :
    // enregistrer n'écrase jamais les autres brouillons en attente.
    // Limite : les pièces jointes ne sont PAS sauvegardées (trop lourd).
    let currentDraftId = null;

    const captureDraftState = () => {
      let body_html_val = '';
      if (mode === 'html') {
        const clone = htmlArea.cloneNode(true);
        body_html_val = clone.innerHTML;
      }
      return {
        to: chipsTo.getValues().join(', '),
        cc: chipsCc.getValues().join(', '),
        bcc: chipsBcc.getValues().join(', '),
        subject: overlay.querySelector('#cmp-subject').value,
        account_id: overlay.querySelector('#cmp-from').value,
        signature_id: overlay.querySelector('#cmp-signature').value,
        mode,
        body_text: textArea.value,
        body_html: body_html_val,
        ts: Date.now(),
      };
    };
    const isDraftMeaningful = (d) => {
      if ((d.to || '').trim()) return true;
      if ((d.cc || '').trim() || (d.bcc || '').trim()) return true;
      if ((d.subject || '').trim()) return true;
      // Texte : on ignore la signature (présente par défaut dans un mail vierge)
      let txt = (d.body_text || '');
      if (signature) {
        if (txt.endsWith('\n\n' + signature)) txt = txt.slice(0, -(signature.length + 2));
        else if (txt.endsWith(signature)) txt = txt.slice(0, -signature.length);
      }
      if (txt.trim()) return true;
      // HTML : on retire le bloc signature via le DOM (fiable même si la
      // signature contient des <div> imbriqués — l'ancien ménage par regex
      // laissait des restes et créait des brouillons fantômes), puis on
      // regarde s'il reste du texte ou une image insérée.
      if (d.body_html) {
        const probe = document.createElement('div');
        probe.innerHTML = d.body_html;
        probe.querySelectorAll('[data-signature-block]').forEach(n => n.remove());
        if ((probe.textContent || '').trim()) return true;
        if (probe.querySelector('img')) return true;
      }
      return false;
    };

    // Empreinte du contenu : sert à ne PAS créer de brouillon quand on
    // ferme un composeur pré-rempli (réponse, prospection) sans avoir
    // rien tapé soi-même.
    const draftFingerprint = (d) =>
      [d.to, d.cc, d.bcc, d.subject, d.body_text, d.body_html].join('\u0001');
    let initialFingerprint = null; // posé en fin d'initialisation, plus bas

    // Sauvegarde silencieuse du brouillon courant (réutilisée par le bouton
    // Brouillon, l'auto-sauvegarde 20 s, la fermeture et la navigation).
    // Renvoie true si quelque chose a été enregistré.
    autosaveDraftNow = (force) => {
      const d = captureDraftState();
      if (!isDraftMeaningful(d)) return false;
      // Composeur pré-rempli (réponse, prospection…) fermé sans avoir rien
      // tapé : on ne crée PAS de brouillon fantôme. Dès qu'un brouillon
      // existe (bouton Brouillon ou reprise), on continue de le mettre à
      // jour. `force` = demande explicite de l'utilisateur (bouton).
      if (!force && !currentDraftId && initialFingerprint !== null &&
          draftFingerprint(d) === initialFingerprint) {
        return false;
      }
      if (!currentDraftId) {
        currentDraftId = 'd-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 7);
      }
      d.id = currentDraftId;
      return this._draftUpsert(d);
    };
    // Auto-sauvegarde toutes les 20 s tant que le composeur est ouvert :
    // plus aucune perte de texte, même en changeant de vue ou d'onglet.
    autosaveTimer = setInterval(() => {
      try { autosaveDraftNow(); } catch (_) {}
    }, 20_000);

    // Bouton "Brouillon" du footer
    const draftBtn = overlay.querySelector('#cmp-draft');
    if (draftBtn) {
      draftBtn.onclick = () => {
        const d = captureDraftState();
        if (!isDraftMeaningful(d)) {
          Toast.warn('Rien à enregistrer en brouillon — écris d’abord ton mail.');
          return;
        }
        if (autosaveDraftNow(true)) {
          draftBtn.innerHTML = '<svg class="w-4 h-4 mr-1.5 inline" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><path d="M5 13l4 4L19 7"/></svg>Brouillon enregistré';
          setTimeout(close, 700);
        } else {
          Toast.error('Impossible d’enregistrer le brouillon (stockage du navigateur plein ou bloqué).');
        }
      };
    }

    // Annuler : si du contenu rédigé, propose Brouillon ou Perdre
    const cancelBtn = overlay.querySelector('#cmp-cancel');
    if (cancelBtn) {
      cancelBtn.onclick = async () => {
        const d = captureDraftState();
        // Rien d'utile OU composeur pré-rempli jamais touché → fermeture simple.
        const untouched = !currentDraftId && initialFingerprint !== null &&
          draftFingerprint(d) === initialFingerprint;
        if (!isDraftMeaningful(d) || untouched) {
          suppressDraftSave = true;
          close();
          return;
        }
        const keep = await Dialog.confirm(
          'Tu as commencé à rédiger ce mail. Le garder en brouillon pour le reprendre plus tard ?',
          { title: 'Mail en cours', okLabel: 'Garder en brouillon', cancelLabel: 'Ne pas garder' });
        if (keep) {
          autosaveDraftNow(true);
          suppressDraftSave = true;
          Toast.success('Brouillon enregistré — tu le retrouveras en ouvrant « Nouveau mail ».');
          close();
          return;
        }
        const sure = await Dialog.confirm(
          'Vraiment supprimer ce que tu as écrit ? Il n’y aura pas de retour en arrière.',
          { title: 'Supprimer le texte', okLabel: 'Supprimer', cancelLabel: 'Revenir au mail', danger: true });
        if (sure) {
          if (currentDraftId) this._draftRemove(currentDraftId);
          suppressDraftSave = true;
          close();
        }
      };
    }

    // Helper : construit le payload pour mail_send / mail_schedule
    // (utilisé par le bouton Envoyer ET le bouton Plus tard)
    const buildSendPayload = () => {
      // Commit toute saisie en attente dans les chips avant de récupérer
      chipsTo.commitPending(); chipsCc.commitPending(); chipsBcc.commitPending();
      const account_id = overlay.querySelector('#cmp-from').value;
      const toList = chipsTo.getValues();
      const ccList = chipsCc.getValues();
      const bccList = chipsBcc.getValues();
      const to = toList.join(', ');
      const subj = overlay.querySelector('#cmp-subject').value.trim();
      let body = '', body_html = '';
      if (mode === 'html') {
        const clone = htmlArea.cloneNode(true);
        clone.querySelectorAll('img[data-cid]').forEach(img => {
          const cid = img.getAttribute('data-cid');
          img.setAttribute('src', `cid:${cid}`);
          img.removeAttribute('data-cid');
        });
        body_html = clone.innerHTML.trim();
        body = htmlArea.innerText.trim();
      } else {
        body = textArea.value;
      }
      // Filtre attachments inline non référencées
      const referencedCids = new Set();
      (body_html.match(/cid:([a-zA-Z0-9_]+)/g) || []).forEach(m => {
        referencedCids.add(m.slice(4));
      });
      const cleanAttachments = attachments.filter(a => !a.inline || referencedCids.has(a.cid));
      return { account_id, to, ccList, bccList, subj, body, body_html, cleanAttachments };
    };

    // Bouton "Plus tard" → programme l'envoi à une date/heure choisie
    const scheduleBtn = overlay.querySelector('#cmp-schedule');
    if (scheduleBtn) {
      scheduleBtn.onclick = () => {
        const status = overlay.querySelector('#cmp-status');
        const p = buildSendPayload();
        if (!p.to || !p.subj || (!p.body.trim() && !p.body_html)) {
          status.textContent = '✗ Destinataire, objet et message requis avant de programmer.';
          status.className = 'text-xs text-danger';
          return;
        }
        const totBytes = p.cleanAttachments.reduce((s, a) => s + (a.size || 0), 0);
        if (totBytes > MAX_TOTAL_BYTES) {
          status.textContent = `✗ Pièces jointes trop lourdes (${fmtSize(totBytes)}). Max 22 Mo.`;
          status.className = 'text-xs text-danger';
          return;
        }
        this._openScheduleDialog(async (scheduledAtISO, prettyDate) => {
          const schedBtnDefaultHTML = '<svg class="w-4 h-4 mr-1.5 inline" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>Plus tard';
          const resetSchedBtn = () => {
            scheduleBtn.disabled = false;
            scheduleBtn.innerHTML = schedBtnDefaultHTML;
          };
          const doSchedule = async (force) => {
            scheduleBtn.disabled = true;
            scheduleBtn.innerHTML = 'Programmation…';
            try {
              const r = await App.api.mail_schedule({
                account_id: p.account_id,
                to: p.to,
                cc: p.ccList,
                bcc: p.bccList,
                subject: p.subj,
                body: p.body,
                body_html: p.body_html,
                in_reply_to: opts.inReplyTo || '',
                scheduled_at: scheduledAtISO,
                force: !!force,
                attachments: p.cleanAttachments.map(a => ({
                  filename: a.filename, content_b64: a.content_b64,
                  content_type: a.content_type,
                  inline: !!a.inline, cid: a.cid || '',
                })),
              });
              if (r && r.ok) {
                if (window.MailAddressBook) {
                  window.MailAddressBook.record([].concat(p.to || [], p.ccList || [], p.bccList || []));
                }
                status.textContent = `✓ Mail programmé pour ${prettyDate}`;
                status.className = 'text-xs text-success';
                Toast.success(`Programmé pour ${prettyDate} — retrouve-le dans l'onglet Programmés.`);
                // Le brouillon n'a plus de raison d'être : l'envoi est planifié.
                if (currentDraftId) this._draftRemove(currentDraftId);
                suppressDraftSave = true;
                setTimeout(close, 1200);
              } else if (r && r.warnings && r.warnings.length) {
                resetSchedBtn();
                Mails._renderSendWarnings(status, r.warnings,
                  () => doSchedule(true), resetSchedBtn);
              } else {
                status.textContent = `✗ ${(r && r.error) || 'Erreur inconnue'}`;
                status.className = 'text-xs text-danger';
                resetSchedBtn();
              }
            } catch (e) {
              status.textContent = `✗ ${e.message || e}`;
              status.className = 'text-xs text-danger';
              resetSchedBtn();
            }
          };
          doSchedule(false);
        });
      };
    }

    // Bouton "Gérer mes signatures" (icône crayon à côté du select)
    const sigEditBtn = overlay.querySelector('#cmp-sig-edit');
    if (sigEditBtn) {
      sigEditBtn.onclick = () => {
        // close() sauvegarde déjà le brouillon courant silencieusement.
        close();
        if (typeof App !== 'undefined' && App.show) {
          App.show('config', { tab: 'mails' });
          // Le rendu Config est async (fetch settings), on retente jusqu'à
          // ce que la liste signatures soit dans le DOM (max 2 sec).
          let tries = 20;
          const tryScroll = () => {
            const sigSection = document.getElementById('cfg-sig-list');
            if (sigSection) {
              sigSection.scrollIntoView({ behavior: 'smooth', block: 'center' });
              return;
            }
            if (--tries > 0) setTimeout(tryScroll, 100);
          };
          setTimeout(tryScroll, 100);
        }
      };
    }

    // Brouillons en attente à l'ouverture d'un composeur vierge :
    // bandeau « N brouillon(s) en attente — Reprendre le dernier / Voir ».
    if (!opts.prefilledTo && !opts.prefilledSubject && !opts.inReplyTo && !opts.prefilledBodyHtml) {
      try {
        const drafts = this._draftsLoad(); // migre l'ancienne clé unique au passage
        if (drafts.length) {
          const restoreDraft = (d) => {
            const splitAddrs = (s) => (s || '').split(/[\s,;]+/).filter(Boolean);
            chipsTo.setValues(splitAddrs(d.to));
            const ccArr = splitAddrs(d.cc);
            const bccArr = splitAddrs(d.bcc);
            if (ccArr.length) {
              chipsCc.setValues(ccArr);
              overlay.querySelector('#cmp-cc-row').classList.remove('hidden');
            }
            if (bccArr.length) {
              chipsBcc.setValues(bccArr);
              overlay.querySelector('#cmp-bcc-row').classList.remove('hidden');
            }
            overlay.querySelector('#cmp-subject').value = d.subject || '';
            if (d.account_id) {
              const fs = overlay.querySelector('#cmp-from');
              if (fs && [...fs.options].some(o => o.value === d.account_id)) fs.value = d.account_id;
            }
            if (d.signature_id !== undefined) {
              const ss = overlay.querySelector('#cmp-signature');
              if (ss && [...ss.options].some(o => o.value === d.signature_id)) ss.value = d.signature_id;
            }
            if (d.body_text) textArea.value = d.body_text;
            if (d.body_html) htmlArea.innerHTML = d.body_html;
            setMode(d.mode === 'text' ? 'text' : 'html');
            // Les sauvegardes suivantes mettront à jour CE brouillon,
            // sans toucher aux autres.
            currentDraftId = d.id;
          };
          this._showDraftsBanner(overlay, drafts, restoreDraft);
        }
      } catch (e) { console.error('[mails] restauration brouillons', e); }
    }

    // Par défaut, on ouvre directement le mode HTML enrichi (plus pratique
    // pour insérer images / mise en forme). L'utilisateur peut basculer en
    // mode "Texte" via le toggle s'il préfère.
    setMode('html');

    // Empreinte de référence : l'état du composeur juste après ouverture
    // (pré-remplissages compris). Tant que rien n'a changé, pas de brouillon.
    initialFingerprint = draftFingerprint(captureDraftState());

    // Focus initial
    setTimeout(() => {
      if (!opts.prefilledTo) chipsTo.focus();
      else if (!opts.prefilledSubject) overlay.querySelector('#cmp-subject').focus();
      else (mode === 'html' ? htmlArea : textArea).focus();
    }, 50);

    // Envoi
    const sendBtn = overlay.querySelector('#cmp-send');
    sendBtn.onclick = async () => {
      const status = overlay.querySelector('#cmp-status');
      // Commit toute saisie en attente dans les chips
      chipsTo.commitPending(); chipsCc.commitPending(); chipsBcc.commitPending();
      const account_id = overlay.querySelector('#cmp-from').value;
      const toList = chipsTo.getValues();
      const ccList = chipsCc.getValues();
      const bccList = chipsBcc.getValues();
      const to = toList.join(', ');
      const subj = overlay.querySelector('#cmp-subject').value.trim();
      let body = '', body_html = '';
      if (mode === 'html') {
        // Avant d'envoyer, convertit les <img data-cid="X" src="data:..."> en
        // <img src="cid:X"> pour que le backend les attache en multipart/related.
        // L'aperçu côté composer reste lisible (data-url), mais le mail envoyé
        // utilise des références CID propres.
        const clone = htmlArea.cloneNode(true);
        clone.querySelectorAll('img[data-cid]').forEach(img => {
          const cid = img.getAttribute('data-cid');
          img.setAttribute('src', `cid:${cid}`);
          img.removeAttribute('data-cid');
        });
        body_html = clone.innerHTML.trim();
        // Génère un fallback texte
        body = htmlArea.innerText.trim();
      } else {
        body = textArea.value;
      }
      if (!toList.length || !subj || (!body.trim() && !body_html)) {
        status.textContent = '✗ Au moins un destinataire, l’objet et le message sont requis.';
        status.className = 'text-xs text-danger';
        return;
      }
      // Validation emails (To + Cc + Bcc)
      const allAddrs = [...toList, ...ccList, ...bccList];
      const badAddr = allAddrs.find(a => !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(a));
      if (badAddr) {
        status.textContent = `✗ Adresse invalide : ${badAddr}`;
        status.className = 'text-xs text-danger';
        return;
      }
      // Filtre les images inline qui ne sont plus référencées dans le body
      // (l'utilisateur a peut-être supprimé l'<img> sans qu'on s'en rende compte)
      const referencedCids = new Set();
      (body_html.match(/cid:([a-zA-Z0-9_]+)/g) || []).forEach(m => {
        referencedCids.add(m.slice(4));
      });
      const cleanAttachments = attachments.filter(a => !a.inline || referencedCids.has(a.cid));
      // Vérification taille totale
      const totBytes = cleanAttachments.reduce((s, a) => s + (a.size || 0), 0);
      if (totBytes > MAX_TOTAL_BYTES) {
        status.textContent = `✗ Pièces jointes trop lourdes (${fmtSize(totBytes)}). Limite : 22 Mo.`;
        status.className = 'text-xs text-danger';
        return;
      }
      const sendBtnDefaultHTML = '<svg class="w-4 h-4 mr-1.5 inline" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><path d="M2 21l21-9-21-9v7l15 2-15 2z"/></svg>Envoyer';
      const resetSendBtn = () => {
        sendBtn.disabled = false;
        sendBtn.innerHTML = sendBtnDefaultHTML;
      };
      const doSend = async (force) => {
        sendBtn.disabled = true;
        sendBtn.innerHTML = '<svg class="w-4 h-4 mr-1.5 inline animate-spin" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M21 12a9 9 0 11-9-9"/></svg>Envoi…';
        status.textContent = '';
        try {
          const r = await App.api.mail_send({
            account_id, to, cc: ccList, bcc: bccList,
            subject: subj, body, body_html,
            in_reply_to: opts.inReplyTo || '',
            force: !!force,
            attachments: cleanAttachments.map(a => ({
              filename: a.filename,
              content_b64: a.content_b64,
              content_type: a.content_type,
              inline: !!a.inline,
              cid: a.cid || '',
            })),
          });
          if (r && r.ok) {
            if (window.MailAddressBook) {
              window.MailAddressBook.record([].concat(to || [], ccList || [], bccList || []));
            }
            status.textContent = '✓ Envoyé !';
            status.className = 'text-xs text-success';
            sendBtn.innerHTML = '✓ Envoyé';
            // Le brouillon n'a plus de raison d'être après envoi
            if (currentDraftId) this._draftRemove(currentDraftId);
            suppressDraftSave = true;
            setTimeout(() => { close(); this._load(); }, 1200);
          } else if (r && r.warnings && r.warnings.length) {
            // Adresse déjà contactée et/ou présente en clients : on propose
            // de re-poster avec force=true (Envoyer quand même).
            resetSendBtn();
            Mails._renderSendWarnings(status, r.warnings,
              () => doSend(true), resetSendBtn);
          } else {
            status.textContent = `✗ ${(r && r.error) || 'Erreur inconnue'}`;
            status.className = 'text-xs text-danger';
            resetSendBtn();
          }
        } catch (e) {
          status.textContent = `✗ ${e}`;
          status.className = 'text-xs text-danger';
          resetSendBtn();
        }
      };
      doSend(false);
    };
  },

  /** Workflow Prospection en direct :
   *  1. Choix Célébrité / Entreprise
   *  2. Saisie URL du site cible
   *  3. Claude analyse + génère le mail
   *  4. Ouvre le composer pré-rempli */
  _openProspectFlow() {
    const ov = document.createElement('div');
    ov.className = 'fixed inset-0 z-[210] flex items-center justify-center p-4';
    ov.style.background = 'rgba(15,23,42,0.78)';
    ov.style.backdropFilter = 'blur(10px)';
    let step = 'category'; // 'category' | 'celebrityKind' | 'businessKind' | 'url' | 'loading'
    // Passe à true dès que la fenêtre est fermée : la génération côté
    // serveur continue, mais l'interface rend la main et ignore le résultat.
    let aborted = false;
    let chosenCategory = null;
    // Subtype :
    //  - business    → 'template' | 'personalized'
    //  - celebrity   → 'sport' | 'influencer'
    let chosenSubtype = null;

    const render = () => {
      if (step === 'category') {
        ov.innerHTML = `
          <div class="bg-surface rounded-2xl shadow-hero w-full max-w-lg border border-border animate-slide-up overflow-hidden">
            <div class="px-6 pt-5 pb-4 flex items-start justify-between border-b border-border bg-surface-elevated">
              <div>
                <div class="text-[10px] font-bold uppercase tracking-widest text-text-muted mb-0.5">PROSPECTION EN DIRECT</div>
                <h3 class="text-lg font-bold">À qui présentes-tu ton site ?</h3>
                <p class="text-xs text-text-muted mt-1">Tu vas envoyer un mail pour leur faire découvrir un site que tu as réalisé pour eux. Le ton du mail s'adapte selon la cible.</p>
              </div>
              <button id="pf-close" class="w-8 h-8 rounded-lg flex items-center justify-center text-text-muted hover:text-text hover:bg-bg text-xl leading-none shrink-0">×</button>
            </div>
            <div class="p-5 grid grid-cols-2 gap-3">
              <button data-cat="celebrity"
                      class="text-left p-5 rounded-2xl border-2 border-border hover:border-accent hover:bg-accent/5 transition-all">
                <div class="text-3xl mb-2">⭐</div>
                <div class="text-base font-bold text-text">Célébrités</div>
                <div class="text-xs text-text-muted mt-1 leading-snug">Artistes, sportifs, créateurs, influenceurs. Ton respectueux, on leur présente une démo créée pour eux.</div>
              </button>
              <button data-cat="business"
                      class="text-left p-5 rounded-2xl border-2 border-border hover:border-accent hover:bg-accent/5 transition-all">
                <div class="text-3xl mb-2">🏢</div>
                <div class="text-base font-bold text-text">Autres (entreprises)</div>
                <div class="text-xs text-text-muted mt-1 leading-snug">Commerces, cabinets, restaurants, artisans. Ton chaleureux et concret, on leur montre un site prêt à adopter.</div>
              </button>
            </div>
          </div>
        `;
        ov.querySelector('#pf-close').onclick = close;
        ov.querySelectorAll('[data-cat]').forEach(b => {
          b.onclick = () => {
            chosenCategory = b.dataset.cat;
            // Chaque catégorie a maintenant son étape intermédiaire
            step = chosenCategory === 'business' ? 'businessKind' : 'celebrityKind';
            render();
          };
        });
      } else if (step === 'celebrityKind') {
        ov.innerHTML = `
          <div class="bg-surface rounded-2xl shadow-hero w-full max-w-lg border border-border animate-slide-up overflow-hidden">
            <div class="px-6 pt-5 pb-4 flex items-start justify-between border-b border-border bg-surface-elevated">
              <div>
                <div class="text-[10px] font-bold uppercase tracking-widest text-text-muted mb-0.5">PROSPECTION CÉLÉBRITÉ</div>
                <h3 class="text-lg font-bold">⭐ Quel type de personnalité ?</h3>
                <p class="text-xs text-text-muted mt-1">Le ton, les angles et le modèle de mail utilisé changent selon le profil.</p>
              </div>
              <button id="pf-close" class="w-8 h-8 rounded-lg flex items-center justify-center text-text-muted hover:text-text hover:bg-bg text-xl leading-none shrink-0">×</button>
            </div>
            <div class="p-5 grid grid-cols-1 sm:grid-cols-2 gap-3">
              <button data-sub="sport"
                      class="text-left p-5 rounded-2xl border-2 border-border hover:border-accent hover:bg-accent/5 transition-all">
                <div class="text-3xl mb-2">🏆</div>
                <div class="text-base font-bold text-text">Sportif</div>
                <div class="text-xs text-text-muted mt-1 leading-snug">Boxeur, footballeur, MMA, cycliste, athlète, etc. Ton respectueux et concret — focus carrière, palmarès, prochains événements, sponsors.</div>
              </button>
              <button data-sub="influencer"
                      class="text-left p-5 rounded-2xl border-2 border-border hover:border-accent hover:bg-accent/5 transition-all">
                <div class="text-3xl mb-2">📱</div>
                <div class="text-base font-bold text-text">Influenceur / créateur</div>
                <div class="text-xs text-text-muted mt-1 leading-snug">YouTubeur, TikTokeur, Instagrameur, podcaster, streamer. Ton décontracté, focus sur l'univers de contenu, la communauté, les partenariats.</div>
              </button>
            </div>
            <div class="px-5 pb-4 flex items-center">
              <button id="pf-back" class="text-xs text-text-muted hover:text-text">← Changer de catégorie</button>
            </div>
          </div>
        `;
        ov.querySelector('#pf-close').onclick = close;
        ov.querySelector('#pf-back').onclick = () => { step = 'category'; render(); };
        ov.querySelectorAll('[data-sub]').forEach(b => {
          b.onclick = () => {
            chosenSubtype = b.dataset.sub;
            step = 'url';
            render();
          };
        });
      } else if (step === 'businessKind') {
        ov.innerHTML = `
          <div class="bg-surface rounded-2xl shadow-hero w-full max-w-lg border border-border animate-slide-up overflow-hidden">
            <div class="px-6 pt-5 pb-4 flex items-start justify-between border-b border-border bg-surface-elevated">
              <div>
                <div class="text-[10px] font-bold uppercase tracking-widest text-text-muted mb-0.5">PROSPECTION ENTREPRISE</div>
                <h3 class="text-lg font-bold">🏢 Quel type de site présentes-tu ?</h3>
                <p class="text-xs text-text-muted mt-1">Le ton du mail change selon que c'est un modèle générique ou un site déjà adapté pour eux.</p>
              </div>
              <button id="pf-close" class="w-8 h-8 rounded-lg flex items-center justify-center text-text-muted hover:text-text hover:bg-bg text-xl leading-none shrink-0">×</button>
            </div>
            <div class="p-5 grid grid-cols-1 sm:grid-cols-2 gap-3">
              <button data-sub="template"
                      class="text-left p-5 rounded-2xl border-2 border-border hover:border-accent hover:bg-accent/5 transition-all">
                <div class="text-3xl mb-2">📐</div>
                <div class="text-base font-bold text-text">Site modèle pour leur métier</div>
                <div class="text-xs text-text-muted mt-1 leading-snug">Une démo générique adaptée à leur secteur (ex : "site type pour une boulangerie"). Le mail invite à imaginer la version qu'on ferait pour eux.</div>
              </button>
              <button data-sub="personalized"
                      class="text-left p-5 rounded-2xl border-2 border-border hover:border-accent hover:bg-accent/5 transition-all">
                <div class="text-3xl mb-2">🎯</div>
                <div class="text-base font-bold text-text">Première personnalisation</div>
                <div class="text-xs text-text-muted mt-1 leading-snug">Tu as déjà intégré ce que tu as trouvé en public (nom, services, ville, ambiance). Le mail dit : "voici une première version, on affine ensemble sur un brief".</div>
              </button>
            </div>
            <div class="px-5 pb-4 flex items-center">
              <button id="pf-back" class="text-xs text-text-muted hover:text-text">← Changer de catégorie</button>
            </div>
          </div>
        `;
        ov.querySelector('#pf-close').onclick = close;
        ov.querySelector('#pf-back').onclick = () => { step = 'category'; render(); };
        ov.querySelectorAll('[data-sub]').forEach(b => {
          b.onclick = () => {
            chosenSubtype = b.dataset.sub;
            step = 'url';
            render();
          };
        });
      } else if (step === 'url') {
        const catLabel = chosenCategory === 'celebrity' ? 'Célébrité' : 'Entreprise';
        const catIcon = chosenCategory === 'celebrity' ? '⭐' : '🏢';
        let kicker = `PROSPECTION ${catLabel.toUpperCase()}`;
        let urlTitle = `${catIcon} URL du site que tu as réalisé`;
        let urlHint = "Colle l'adresse du site que tu as fait pour eux (souvent un sous-domaine de démo). Claude va l'analyser, capturer un aperçu et rédiger le mail de présentation.";
        if (chosenCategory === 'business' && chosenSubtype === 'template') {
          kicker = 'PROSPECTION ENTREPRISE · MODÈLE';
          urlTitle = '📐 URL du site modèle';
          urlHint = "Colle l'adresse de ton site modèle générique adapté à leur métier. Le mail expliquera que c'est un modèle qu'on peut personnaliser pour eux.";
        } else if (chosenCategory === 'business' && chosenSubtype === 'personalized') {
          kicker = 'PROSPECTION ENTREPRISE · 1ʳᵉ PERSONNALISATION';
          urlTitle = '🎯 URL du site déjà ébauché pour eux';
          urlHint = "Colle l'adresse du site où tu as déjà intégré les infos publiques que tu as trouvées (nom, services, ville). Le mail invitera à un brief pour finaliser les derniers détails.";
        } else if (chosenCategory === 'celebrity' && chosenSubtype === 'sport') {
          kicker = 'PROSPECTION CÉLÉBRITÉ · SPORTIF';
          urlTitle = '🏆 URL du site que tu as réalisé';
          urlHint = "Colle l'adresse du site que tu as conçu pour ce sportif. Claude utilisera un ton respectueux et orientera le mail autour de sa carrière et son palmarès.";
        } else if (chosenCategory === 'celebrity' && chosenSubtype === 'influencer') {
          kicker = 'PROSPECTION CÉLÉBRITÉ · INFLUENCEUR';
          urlTitle = '📱 URL du site que tu as réalisé';
          urlHint = "Colle l'adresse du site que tu as conçu pour ce créateur. Claude adoptera un ton décontracté et parlera de son univers de contenu et sa communauté.";
        }
        ov.innerHTML = `
          <div class="bg-surface rounded-2xl shadow-hero w-full max-w-lg border border-border animate-slide-up overflow-hidden">
            <div class="px-6 pt-5 pb-4 flex items-start justify-between border-b border-border bg-surface-elevated">
              <div>
                <div class="text-[10px] font-bold uppercase tracking-widest text-text-muted mb-0.5">${kicker}</div>
                <h3 class="text-lg font-bold">${urlTitle}</h3>
                <p class="text-xs text-text-muted mt-1">${urlHint}</p>
              </div>
              <button id="pf-close" class="w-8 h-8 rounded-lg flex items-center justify-center text-text-muted hover:text-text hover:bg-bg text-xl leading-none shrink-0">×</button>
            </div>
            <div class="p-5 space-y-3">
              <input id="pf-url" type="url" placeholder="https://www.exemple.com"
                     class="w-full px-3 py-3 text-sm rounded-lg bg-bg border border-border focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent"/>
              <div id="pf-url-error" class="text-xs text-danger min-h-[1rem]"></div>
            </div>
            <div class="px-5 py-4 border-t border-border bg-surface-elevated flex items-center justify-between gap-2">
              <button id="pf-back" class="text-xs text-text-muted hover:text-text">← Changer de catégorie</button>
              <div class="flex items-center gap-2">
                <button id="pf-cancel" class="btn btn-secondary">Annuler</button>
                <button id="pf-go" class="btn btn-primary">
                  <svg class="w-4 h-4 mr-1.5 inline" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>
                  Générer le mail
                </button>
              </div>
            </div>
          </div>
        `;
        ov.querySelector('#pf-close').onclick = close;
        ov.querySelector('#pf-cancel').onclick = close;
        ov.querySelector('#pf-back').onclick = () => {
          // Retour au sous-choix de la catégorie courante
          step = chosenCategory === 'business' ? 'businessKind' : 'celebrityKind';
          render();
        };
        const urlInput = ov.querySelector('#pf-url');
        setTimeout(() => urlInput.focus(), 50);
        urlInput.addEventListener('keydown', (e) => {
          if (e.key === 'Enter') { e.preventDefault(); ov.querySelector('#pf-go').click(); }
        });
        ov.querySelector('#pf-go').onclick = async () => {
          const errEl = ov.querySelector('#pf-url-error');
          let url = urlInput.value.trim();
          if (!url) { errEl.textContent = '✗ URL manquante.'; return; }
          // Auto-ajout https:// si absent
          if (!/^https?:\/\//i.test(url)) url = 'https://' + url;
          try { new URL(url); } catch { errEl.textContent = '✗ URL invalide.'; return; }
          errEl.textContent = '';
          step = 'loading';
          render();
          try {
            const r = await App.api.prospect_generate_mail({
              url,
              category: chosenCategory,
              subtype: chosenSubtype || '',
            });
            if (aborted) return; // l'utilisateur a annulé pendant la génération
            if (r && r.ok) {
              close();
              const prefilledAttachments = [];
              let bodyForComposer = r.body_html || '';
              if (r.screenshot_b64) {
                prefilledAttachments.push({
                  filename: `apercu-${(r.target_name || 'site').toLowerCase().replace(/[^a-z0-9]+/g, '-').slice(0, 40) || 'site'}.png`,
                  content_b64: r.screenshot_b64,
                  content_type: r.screenshot_content_type || 'image/png',
                  size: Math.floor((r.screenshot_b64.length || 0) * 0.75),
                  inline: true,
                  cid: 'prospect_preview',
                });
                // Remplace src="cid:..." par data:... pour que l'aperçu
                // s'affiche dans l'éditeur. Le composer reconvertit
                // automatiquement en cid: au moment de l'envoi.
                const dataUrl = `data:${r.screenshot_content_type || 'image/png'};base64,${r.screenshot_b64}`;
                bodyForComposer = bodyForComposer.replace(
                  /<img([^>]*?)src=["']cid:prospect_preview["']([^>]*?)>/gi,
                  `<img$1data-cid="prospect_preview" src="${dataUrl}"$2>`
                );
              }
              this._openComposer({
                prefilledSubject: r.subject || '',
                prefilledBodyHtml: bodyForComposer,
                prefilledAttachments,
                title: `Prospection : ${r.target_name || url}`,
              });
            } else {
              step = 'url';
              render();
              setTimeout(() => {
                const e2 = ov.querySelector('#pf-url-error');
                if (e2) e2.textContent = `✗ ${(r && r.error) || 'Erreur lors de la génération.'}`;
                const u2 = ov.querySelector('#pf-url');
                if (u2) u2.value = url;
              }, 50);
            }
          } catch (e) {
            if (aborted) return; // fenêtre déjà fermée par l'utilisateur
            step = 'url';
            render();
            setTimeout(() => {
              const e2 = ov.querySelector('#pf-url-error');
              if (e2) e2.textContent = `✗ ${e.message || e}`;
              const u2 = ov.querySelector('#pf-url');
              if (u2) u2.value = url;
            }, 50);
          }
        };
      } else if (step === 'loading') {
        ov.innerHTML = `
          <div class="bg-surface rounded-2xl shadow-hero w-full max-w-lg border border-border animate-slide-up overflow-hidden">
            <div class="p-12 text-center">
              <div class="w-16 h-16 mx-auto mb-5 rounded-2xl flex items-center justify-center"
                   style="background: linear-gradient(135deg, hsl(var(--accent-strong)), hsl(var(--accent)));">
                <svg class="w-8 h-8 text-white animate-spin" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                  <path d="M21 12a9 9 0 11-9-9"/>
                </svg>
              </div>
              <div class="text-base font-bold text-text mb-1">Claude analyse le site…</div>
              <div class="text-xs text-text-muted">Téléchargement du contenu, capture de l'aperçu, choix du modèle, rédaction du mail. Compte 15-40 secondes.</div>
              <button id="pf-loading-cancel" class="btn btn-secondary mt-6">Annuler</button>
              <div class="text-[11px] text-text-muted mt-2">Annuler ferme cette fenêtre — rien ne sera envoyé.</div>
            </div>
          </div>
        `;
        const cancelLoadingBtn = ov.querySelector('#pf-loading-cancel');
        if (cancelLoadingBtn) cancelLoadingBtn.onclick = close;
      }
    };

    const close = () => {
      aborted = true;
      document.removeEventListener('keydown', escListener);
      ov.remove();
    };
    // Échap ferme la fenêtre à toutes les étapes, génération comprise
    // (la génération côté serveur continue, mais l'interface rend la main).
    const escListener = (e) => { if (e.key === 'Escape') close(); };
    document.addEventListener('keydown', escListener);
    ov.addEventListener('click', (e) => { if (e.target === ov && step !== 'loading') close(); });

    render();
    document.body.appendChild(ov);
  },

  // _showDraftsBanner, _openDraftsListDialog, _openScheduleDialog, _openImageLinkDialog
  // ont été extraits dans scripts/mails_dialogs.js (chargé après mails.js
  // dans index.html). Ils sont attachés à Mails à l'init de cette modale.

  _noBackend() {
    return `
      <div class="card p-8 text-center">
        <div class="text-3xl mb-3 opacity-60">⏻</div>
        <h2 class="text-lg font-bold mb-2">Le serveur ne répond pas.</h2>
        <p class="text-text-muted text-sm">Patiente quelques secondes puis rafraîchis la page. Si ça persiste, redémarre Triskell Command.</p>
      </div>
    `;
  },

  _escape(s) {
    return String(s ?? '')
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  },

  // ----------------------------------------------------------------------
  // Rend le corps d'un mail : si HTML détecté → iframe sandbox (rendu réel,
  // sans exécuter de JS), sinon → bloc texte échappé (ancien comportement).
  // L'iframe s'auto-redimensionne après chargement pour afficher tout le contenu.
  // ----------------------------------------------------------------------
  _renderMailBody(body) {
    const text = String(body ?? '');
    const looksHtml = /<\s*(html|body|table|div|p|a\b|img|h[1-6]|span|br|ul|ol|style|head|meta)\b/i.test(text);
    if (!looksHtml) {
      return `<div class="rounded-xl bg-bg border border-border px-5 py-4">
        <pre class="text-sm text-text whitespace-pre-wrap font-sans leading-relaxed m-0">${this._escape(text)}</pre>
      </div>`;
    }
    // On prefixe le HTML par <base target="_blank"> pour que tous les
    // liens cliques s ouvrent dans un nouvel onglet plutot que dans
    // l iframe sandbox -- sinon les sites avec X-Frame-Options DENY
    // (Pixel Pros, beaucoup de sites pros) refusent de s afficher et
    // le user voit une page d erreur Firefox.
    const wrapped = `<base target="_blank">${text}`;
    // Échappe pour l'attribut srcdoc (& et " uniquement, les < > restent intacts)
    const srcdoc = wrapped.replace(/&/g, '&amp;').replace(/"/g, '&quot;');
    // sandbox="allow-popups" UNIQUEMENT (sécurité) :
    //  - allow-popups : autorise target="_blank" (sinon clics inertes)
    //  - PAS de allow-same-origin ni allow-popups-to-escape-sandbox : un mail
    //    malveillant ne doit avoir AUCUN accès à la page Triskell ni ouvrir
    //    d'onglet hors bac à sable. Conséquence : on ne peut plus lire la
    //    hauteur du contenu → hauteur fixe confortable (60vh) + ascenseur.
    return `<div class="rounded-xl bg-white border border-border overflow-hidden">
      <iframe class="w-full block"
              sandbox="allow-popups"
              srcdoc="${srcdoc}"
              style="border:0;height:60vh;min-height:300px;background:#fff;"></iframe>
    </div>`;
  },

  _fmtDate(iso) {
    if (!iso) return '—';
    try {
      const d = new Date(iso);
      // Année affichée seulement si différente de l'année en cours
      // (sinon "12/06 09:30" d'il y a deux ans semble tout récent).
      const opts = { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' };
      if (d.getFullYear() !== new Date().getFullYear()) opts.year = 'numeric';
      return d.toLocaleString('fr-FR', opts);
    } catch { return iso.slice(0, 16); }
  },

  _fmtSize(n) {
    const v = Number(n) || 0;
    if (!v) return '';
    if (v < 1024) return `${v} o`;
    if (v < 1024 * 1024) return `${Math.round(v / 1024)} Ko`;
    return `${(v / 1024 / 1024).toFixed(1)} Mo`;
  },
};
