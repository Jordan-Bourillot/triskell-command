/* Vue Fichier clients — annuaire central 360° de tous les clients
   (table master `clients` agrégée depuis prospection, formulaires de sites,
   factures, mails envoyés, projets de livraison).
   Différent de `clients.js` qui gère le kanban des projets en cours. */

const ClientsMaster = {
  // `chip` = triplet HSL du thème (jamais de couleur en dur : lisible
  // dans les 3 thèmes). À utiliser via hsl(${chip}) ou hsl(${chip} / alpha).
  STATUSES: {
    // label = ce qui s'affiche (français normal) ; la clé stockée ne bouge pas.
    '':         { label: 'Tous',        chip: 'var(--text-muted)' },
    'lead':     { label: 'Contact',     chip: 'var(--text-muted)' },
    'prospect': { label: 'Prospect',    chip: 'var(--info-text)' },
    'client':   { label: 'Client',      chip: 'var(--success-text)' },
    'inactive': { label: 'Inactif',     chip: 'var(--warning-text)' },
    'churned':  { label: 'Parti',       chip: 'var(--danger-text)' },
  },

  EVENT_ICONS: {
    'Demande Lagriffe':    '🟢',
    'Demande RankUs':      '🟣',
    'Demande Studio WoW':  '⚫',
    'Facture':             '📄',
    'Email envoyé':        '✉️',
    'Projet livraison':    '📦',
  },

  // État de la vue
  _clients: [],
  _selectedId: null,
  _detail: null,
  _search: '',
  _status: '',
  _loading: false,

  async render(container) {
    container.innerHTML = `
      <section class="animate-slide-up">
        <div class="mb-6 sm:mb-8 flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
          <div class="min-w-0 flex-1">
            <div class="hero-kicker mb-2">FICHIER CLIENTS</div>
            <h1 class="hero-title hero-title--md mb-2 sm:mb-3">Tous tes clients en un seul endroit.</h1>
            <p class="hero-subtitle">
              Chaque personne qui passe par Triskell — prospect, client, contact d'un formulaire de site —
              regroupée ici, avec son historique complet.
            </p>
          </div>
          <div class="flex flex-wrap gap-2 sm:gap-3">
            <button id="cm-refresh" class="btn btn-secondary">Rafraîchir</button>
          </div>
        </div>

        <!-- Barre filtres -->
        <div class="mb-5 space-y-3">
          <div class="relative">
            <svg class="w-4 h-4 absolute left-3.5 top-1/2 -translate-y-1/2 text-text-muted pointer-events-none"
                 fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
              <circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/>
            </svg>
            <input id="cm-search" type="text" autocomplete="off"
                   placeholder="Rechercher par nom, prénom, email ou société…"
                   class="w-full pl-10 pr-4 py-2.5 text-sm rounded-xl bg-bg border border-border
                          focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent" />
          </div>
          <div class="flex flex-wrap gap-2" id="cm-status-chips"></div>
        </div>

        <!-- Layout 2 colonnes : liste / détail -->
        <div class="grid grid-cols-1 lg:grid-cols-[minmax(320px,420px)_1fr] gap-4 min-h-[60vh]">
          <!-- Colonne liste -->
          <div class="card flex flex-col overflow-hidden" style="background: hsl(var(--surface) / 0.6);">
            <header class="px-5 py-3 border-b border-border flex items-center justify-between">
              <div class="text-[11px] font-bold tracking-widest text-text-muted">
                CLIENTS <span id="cm-count" class="text-accent ml-1">·</span>
              </div>
            </header>
            <div id="cm-list" class="flex-1 overflow-y-auto"></div>
          </div>

          <!-- Colonne détail -->
          <div id="cm-detail" class="card flex flex-col overflow-hidden"
               style="background: hsl(var(--surface) / 0.6);"></div>
        </div>
      </section>
    `;

    // Wiring
    document.getElementById('cm-refresh').onclick = () => this.refresh();
    const searchEl = document.getElementById('cm-search');
    searchEl.value = this._search;
    searchEl.addEventListener('input', () => {
      this._search = searchEl.value;
      this._renderList(); // filtrage local instantané (pas de re-requête)
    });
    this._renderStatusChips();
    this._renderEmptyDetail();
    await this.refresh();
  },

  // ────────────────────────────────────────────────────────────────
  // Chips de filtre par statut
  // ────────────────────────────────────────────────────────────────
  _renderStatusChips() {
    const wrap = document.getElementById('cm-status-chips');
    if (!wrap) return;
    wrap.innerHTML = '';
    Object.entries(this.STATUSES).forEach(([key, meta]) => {
      const active = key === this._status;
      const btn = document.createElement('button');
      btn.textContent = meta.label;
      btn.style.cssText = this._chipStyle(active, meta.chip);
      btn.onclick = () => {
        this._status = key;
        this._renderStatusChips();
        this.refresh();
      };
      wrap.appendChild(btn);
    });
  },

  _chipStyle(active, color) {
    if (active) {
      return `padding: 6px 14px; border-radius: 999px; font-size: 12.5px;
              font-weight: 700; background: hsl(${color} / 0.16); color: hsl(${color});
              border: 1px solid hsl(${color} / 0.55); cursor: pointer; transition: all 160ms;`;
    }
    return `padding: 6px 14px; border-radius: 999px; font-size: 12.5px;
            font-weight: 500; background: transparent;
            color: hsl(var(--text-secondary));
            border: 1px solid hsl(var(--border-strong)); cursor: pointer;
            transition: all 160ms;`;
  },

  // ────────────────────────────────────────────────────────────────
  // Récupération + rendu de la liste
  // ────────────────────────────────────────────────────────────────
  async refresh() {
    const list = document.getElementById('cm-list');
    list.innerHTML = `<div class="p-8 text-center text-text-muted text-sm">Chargement…</div>`;
    if (!App.api) {
      list.innerHTML = this._errorBox('L’app n’est pas connectée au serveur.');
      return;
    }
    this._loading = true;
    let data;
    try {
      data = await App.api.get_clients_master({ status: this._status, limit: 500 });
    } catch (e) {
      console.error('[ClientsMaster] chargement', e);
      list.innerHTML = this._errorBox('Impossible de charger le fichier clients. Vérifie ta connexion, puis réessaie.');
      this._loading = false;
      return;
    }
    this._loading = false;
    if (!data || !data.ok) {
      if (data && data.error) console.warn('[ClientsMaster] chargement', data.error);
      list.innerHTML = this._errorBox('Connexion à la base partagée impossible. Réessaie dans un instant.');
      document.getElementById('cm-count').textContent = '·';
      return;
    }
    this._clients = data.clients || [];
    this._renderList();
  },

  _renderList() {
    const list = document.getElementById('cm-list');
    const s = this._search.trim().toLowerCase();
    const filtered = !s ? this._clients : this._clients.filter(c => {
      const hay = [
        c.email, c.full_name, c.company_name, c.phone,
        c.first_name, c.last_name,
      ].filter(Boolean).join(' ').toLowerCase();
      return hay.includes(s);
    });

    document.getElementById('cm-count').textContent = filtered.length;

    if (filtered.length === 0) {
      list.innerHTML = `
        <div class="p-10 text-center text-text-muted">
          <div class="text-3xl mb-3 opacity-60">∅</div>
          ${this._clients.length === 0 ? `
            <div class="text-sm font-semibold text-text mb-1">Aucune fiche pour l’instant.</div>
            <div class="text-sm">Les fiches arrivent ici toutes seules : prospects devenus clients,
            demandes envoyées depuis tes sites, factures, mails envoyés et projets livrés.</div>
          ` : `
            <div class="text-sm">Rien ne correspond à ta recherche.</div>
          `}
        </div>
      `;
      return;
    }

    // La liste est plafonnée à 500 fiches côté serveur : si on atteint ce
    // plafond, on le DIT (avant : coupure silencieuse, fiches "disparues").
    const capNote = this._clients.length >= 500 ? `
      <div class="px-4 py-3 text-[11px] text-text-muted text-center border-t border-border">
        500 premières fiches affichées — affine ta recherche ou filtre par statut pour voir les autres.
      </div>
    ` : '';

    list.innerHTML = filtered.map(c => this._listRow(c)).join('') + capNote;
    list.querySelectorAll('[data-cid]').forEach(row => {
      row.onclick = () => this._select(row.dataset.cid);
    });
    // Re-souligner la sélection courante (si toujours visible)
    if (this._selectedId) {
      const sel = list.querySelector(`[data-cid="${this._selectedId}"]`);
      if (sel) sel.classList.add('cm-row-selected');
    }
  },

  _listRow(c) {
    const name = (c.full_name && c.full_name.trim())
                  || c.email || '(sans nom)';
    const sub = c.company_name || c.email || '';
    const status = c.status || 'lead';
    const meta = this.STATUSES[status] || this.STATUSES['lead'];
    const last = c.last_contact_at
      ? this._fmtDate(c.last_contact_at) : 'Jamais';
    return `
      <button type="button" data-cid="${c.id}"
        class="cm-row w-full text-left px-4 py-3 border-b border-border
               hover:bg-bg transition-colors flex items-start gap-3">
        <div class="w-9 h-9 rounded-full flex items-center justify-center shrink-0
                    text-sm font-bold"
             style="background: hsl(${meta.chip} / 0.16); color: hsl(${meta.chip});">
          ${this._esc(this._initials(name))}
        </div>
        <div class="min-w-0 flex-1">
          <div class="flex items-baseline gap-2">
            <div class="font-semibold text-sm truncate">${this._esc(name)}</div>
            <span class="text-[11px] font-bold px-1.5 py-0.5 rounded shrink-0"
                  style="background: hsl(${meta.chip} / 0.13); color: hsl(${meta.chip});">
              ${meta.label.toUpperCase()}
            </span>
          </div>
          ${sub && sub !== name ? `
            <div class="text-[12px] text-text-muted truncate">${this._esc(sub)}</div>
          ` : ''}
          <div class="text-[11px] text-text-muted mt-0.5">Dernier contact : ${last}</div>
        </div>
      </button>
    `;
  },

  _errorBox(msg, retryJs) {
    return `
      <div class="p-8 text-center">
        <div class="text-3xl mb-3">🔌</div>
        <div class="text-sm text-danger-text mb-4">${this._esc(msg)}</div>
        <button class="btn btn-secondary" onclick="${this._esc(retryJs || 'ClientsMaster.refresh()')}">Réessayer</button>
      </div>
    `;
  },

  // ────────────────────────────────────────────────────────────────
  // Détail
  // ────────────────────────────────────────────────────────────────
  async _select(id) {
    this._selectedId = id;
    // Souligne la ligne sélectionnée
    document.querySelectorAll('.cm-row').forEach(r =>
      r.classList.toggle('cm-row-selected', r.dataset.cid === id)
    );
    const detail = document.getElementById('cm-detail');
    detail.innerHTML = `<div class="p-8 text-text-muted text-sm">Chargement de la fiche…</div>`;
    if (!App.api) return;
    const retryJs = `ClientsMaster._select('${String(id).replace(/[^a-zA-Z0-9_-]/g, '')}')`;
    let data;
    try { data = await App.api.get_client_master({ id }); }
    catch (e) {
      console.error('[ClientsMaster] fiche', e);
      detail.innerHTML = this._errorBox('Impossible de charger cette fiche. Réessaie dans un instant.', retryJs);
      return;
    }
    if (!data || !data.ok) {
      if (data && data.error) console.warn('[ClientsMaster] fiche', data.error);
      detail.innerHTML = this._errorBox('Fiche introuvable ou serveur indisponible.', retryJs);
      return;
    }
    this._detail = data;
    this._renderDetail();
  },

  _renderEmptyDetail() {
    const detail = document.getElementById('cm-detail');
    detail.innerHTML = `
      <div class="flex-1 flex flex-col items-center justify-center text-center p-10 text-text-muted">
        <div class="text-5xl mb-4 opacity-50">👤</div>
        <div class="font-semibold text-text mb-1">Sélectionne un client</div>
        <div class="text-sm max-w-xs">
          Clique sur un nom dans la liste pour voir sa fiche complète : coordonnées,
          historique des échanges, factures, demandes envoyées via tes formulaires.
        </div>
      </div>
    `;
  },

  _renderDetail() {
    const detail = document.getElementById('cm-detail');
    const c = this._detail.client;
    const timeline = this._detail.timeline || [];
    const name = (c.full_name && c.full_name.trim()) || c.email || '(sans nom)';
    const meta = this.STATUSES[c.status || 'lead'] || this.STATUSES['lead'];

    detail.innerHTML = `
      <!-- Header fiche -->
      <header class="px-6 py-5 border-b border-border flex items-start gap-4">
        <div class="w-14 h-14 rounded-full flex items-center justify-center shrink-0
                    text-lg font-bold"
             style="background: hsl(${meta.chip} / 0.16); color: hsl(${meta.chip});">
          ${this._esc(this._initials(name))}
        </div>
        <div class="min-w-0 flex-1">
          <div class="flex items-center gap-2 flex-wrap mb-1">
            <h2 class="font-display text-xl font-bold truncate">${this._esc(name)}</h2>
            <span class="text-[11px] font-bold px-2 py-0.5 rounded"
                  style="background: hsl(${meta.chip} / 0.13); color: hsl(${meta.chip});">
              ${meta.label.toUpperCase()}
            </span>
          </div>
          ${c.company_name ? `
            <div class="text-sm text-text-muted">${this._esc(c.company_name)}</div>
          ` : ''}
        </div>
        <button id="cm-edit" class="btn btn-secondary text-xs px-3 py-1.5">Éditer</button>
      </header>

      <div class="flex-1 overflow-y-auto p-6 space-y-6">
        <!-- Coordonnées -->
        <section>
          <h3 class="text-[11px] font-bold tracking-widest text-text-muted mb-3">COORDONNÉES</h3>
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
            ${this._emailField(c.email)}
            ${this._field('Téléphone', c.phone, c.phone ? 'tel:' + c.phone.replace(/\s/g, '') : null)}
            ${this._field('Prénom', c.first_name)}
            ${this._field('Nom', c.last_name)}
          </div>
        </section>

        <!-- Société (si pro) -->
        ${(c.is_pro || c.company_name || c.siret) ? `
        <section>
          <h3 class="text-[11px] font-bold tracking-widest text-text-muted mb-3">SOCIÉTÉ</h3>
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
            ${this._field('Entreprise', c.company_name)}
            ${this._field('SIRET', c.siret)}
            ${this._field('N° TVA', c.vat_number)}
          </div>
        </section>` : ''}

        <!-- Adresse -->
        ${(c.address_line1 || c.address_city) ? `
        <section>
          <h3 class="text-[11px] font-bold tracking-widest text-text-muted mb-3">ADRESSE</h3>
          <div class="text-sm leading-relaxed">
            ${c.address_line1 ? `<div>${this._esc(c.address_line1)}</div>` : ''}
            ${(c.address_zip || c.address_city) ? `
              <div>${this._esc((c.address_zip || '') + ' ' + (c.address_city || '')).trim()}</div>
            ` : ''}
            ${c.address_country && c.address_country !== 'France' ? `
              <div>${this._esc(c.address_country)}</div>
            ` : ''}
          </div>
        </section>` : ''}

        <!-- Stats -->
        <section>
          <h3 class="text-[11px] font-bold tracking-widest text-text-muted mb-3">ACTIVITÉ</h3>
          <div class="grid grid-cols-3 sm:grid-cols-6 gap-2">
            ${this._stat('Lagriffe', c.lagriffe_count)}
            ${this._stat('RankUs', c.rankus_count)}
            ${this._stat('WoW', c.wow_count)}
            ${this._stat('Factures', c.invoices_count)}
            ${this._stat('Mails', c.emails_sent_count)}
            ${this._stat('Projets', c.projects_count)}
          </div>
          ${c.total_paid_cents ? `
            <div class="mt-3 text-sm">
              <span class="text-text-muted">Total payé : </span>
              <span class="font-bold text-success-text">${Math.round(c.total_paid_cents / 100)} €</span>
            </div>
          ` : ''}
        </section>

        <!-- Tags -->
        <section>
          <h3 class="text-[11px] font-bold tracking-widest text-text-muted mb-3">TAGS</h3>
          <div class="flex flex-wrap gap-2 items-center" id="cm-tags">
            ${(c.tags && c.tags.length) ? c.tags.map(t => `
              <span class="text-[11px] font-semibold pl-2 pr-1 py-1 rounded-full
                           bg-accent/10 text-accent border border-accent/20
                           inline-flex items-center gap-1">
                ${this._esc(t)}
                <button type="button" data-rmtag="${this._esc(t)}"
                        class="w-4 h-4 rounded-full inline-flex items-center justify-center
                               hover:bg-accent/20 leading-none"
                        title="Retirer ce tag" aria-label="Retirer le tag ${this._esc(t)}">×</button>
              </span>
            `).join('') : '<span class="text-sm text-text-muted">Aucun tag</span>'}
            <button id="cm-add-tag" class="text-[11px] text-text-muted hover:text-accent underline">
              + Ajouter
            </button>
          </div>
        </section>

        <!-- Notes -->
        <section>
          <h3 class="text-[11px] font-bold tracking-widest text-text-muted mb-3">NOTES</h3>
          ${c.notes ? `
            <div class="text-sm whitespace-pre-wrap p-3 rounded-lg bg-bg border border-border">
              ${this._esc(c.notes)}
            </div>
          ` : `<div class="text-sm text-text-muted italic">Aucune note pour ce client.</div>`}
        </section>

        <!-- Timeline -->
        <section>
          <h3 class="text-[11px] font-bold tracking-widest text-text-muted mb-3">
            HISTORIQUE <span class="text-text-muted ml-1">(${timeline.length})</span>
          </h3>
          ${timeline.length === 0 ? `
            <div class="text-sm text-text-muted italic">Aucun événement enregistré.</div>
          ` : `
            <ol class="space-y-2">
              ${timeline.map(e => this._timelineRow(e)).join('')}
            </ol>
          `}
        </section>
      </div>
    `;

    detail.querySelector('#cm-edit').onclick = () => this._openEditDialog();
    detail.querySelector('#cm-add-tag').onclick = () => this._addTag();
    detail.querySelectorAll('[data-rmtag]').forEach(btn => {
      btn.onclick = () => this._removeTag(btn.dataset.rmtag);
    });
    const composeBtn = detail.querySelector('#cm-compose');
    if (composeBtn) composeBtn.onclick = () => {
      Mails._openComposer({ prefilledTo: c.email });
    };
  },

  // Champ Email du détail : lien mailto classique + « Écrire depuis l'app »
  // (ouvre le composeur interne avec l'adresse pré-remplie) quand Mails est là.
  _emailField(email) {
    const v = (email || '').toString().trim();
    if (!v) return this._field('Email', '');
    const canCompose = !!(App.api && window.Mails && typeof Mails._openComposer === 'function');
    return `
      <div>
        <div class="text-[11px] font-bold tracking-widest text-text-muted mb-1">EMAIL</div>
        <a href="mailto:${this._esc(v)}" class="text-sm text-accent hover:underline break-all">${this._esc(v)}</a>
        ${canCompose ? `
          <button id="cm-compose" class="block text-[11px] text-text-muted hover:text-accent underline mt-1">
            ✉️ Écrire depuis l’app
          </button>
        ` : ''}
      </div>
    `;
  },

  _field(label, value, href) {
    const v = (value || '').toString().trim();
    if (!v) {
      return `
        <div>
          <div class="text-[11px] font-bold tracking-widest text-text-muted mb-1">${this._esc(label)}</div>
          <div class="text-sm text-text-muted italic">—</div>
        </div>
      `;
    }
    const content = href
      ? `<a href="${href}" class="text-sm text-accent hover:underline">${this._esc(v)}</a>`
      : `<div class="text-sm">${this._esc(v)}</div>`;
    return `
      <div>
        <div class="text-[11px] font-bold tracking-widest text-text-muted mb-1">${this._esc(label)}</div>
        ${content}
      </div>
    `;
  },

  _stat(label, count) {
    const n = count || 0;
    const dim = n === 0 ? 'opacity-40' : '';
    return `
      <div class="text-center p-2 rounded-lg bg-bg border border-border ${dim}">
        <div class="font-bold text-lg leading-none">${n}</div>
        <div class="text-[11px] text-text-muted mt-1">${this._esc(label)}</div>
      </div>
    `;
  },

  _timelineRow(e) {
    const icon = this.EVENT_ICONS[e.type] || '•';
    const date = e.created_at ? this._fmtDate(e.created_at) : '';
    const label = e.label || e.status || '';
    return `
      <li class="flex items-start gap-3 text-sm">
        <span class="text-base leading-none mt-0.5">${icon}</span>
        <div class="min-w-0 flex-1">
          <div class="font-medium">${this._esc(e.type)}${label ? ' — ' + this._esc(label) : ''}</div>
          <div class="text-[11px] text-text-muted">${date}</div>
        </div>
      </li>
    `;
  },

  // ────────────────────────────────────────────────────────────────
  // Édition
  // ────────────────────────────────────────────────────────────────
  async _addTag() {
    const raw = prompt('Nouveau tag :');
    if (raw === null) return; // Annuler = on ne fait rien
    const tag = raw.trim();
    if (!tag || !this._selectedId) return;
    try {
      const r = await App.api.client_master_add_tag({ id: this._selectedId, tag });
      if (r && r.ok) {
        Toast.success(`Tag « ${tag} » ajouté.`);
        await this._select(this._selectedId);
      } else {
        Toast.friendlyError(r, 'Impossible d’ajouter ce tag.');
      }
    } catch (e) {
      Toast.friendlyError(e, 'Impossible d’ajouter ce tag.');
    }
  },

  async _removeTag(tag) {
    if (!tag || !this._selectedId) return;
    try {
      const r = await App.api.client_master_remove_tag({ id: this._selectedId, tag });
      if (r && r.ok) {
        Toast.success(`Tag « ${tag} » retiré.`);
        await this._select(this._selectedId);
      } else {
        Toast.friendlyError(r, 'Impossible de retirer ce tag.');
      }
    } catch (e) {
      Toast.friendlyError(e, 'Impossible de retirer ce tag.');
    }
  },

  _openEditDialog() {
    const c = this._detail.client;
    const overlay = document.createElement('div');
    overlay.className = 'fixed inset-0 z-[100] flex items-center justify-center p-6';
    overlay.style.background = 'hsl(var(--bg) / 0.55)';
    overlay.style.backdropFilter = 'blur(6px)';
    const field = (id, label, val, type = 'text') => `
      <label class="block">
        <div class="text-[11px] font-bold tracking-widest text-text-muted mb-1">${label}</div>
        <input id="${id}" type="${type}" value="${this._esc(val || '')}"
               class="w-full px-3 py-2 text-sm rounded-lg bg-bg border border-border
                      focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent" />
      </label>
    `;
    overlay.innerHTML = `
      <div class="bg-surface rounded-3xl shadow-hero w-full max-w-2xl overflow-hidden animate-slide-up"
           style="border: 1px solid hsl(var(--border)); max-height: 90vh; display: flex; flex-direction: column;">
        <header class="px-7 pt-6 pb-4 border-b border-border">
          <div class="hero-kicker mb-1">FICHE CLIENT</div>
          <div class="font-display text-xl font-bold">Éditer ${this._esc((c.full_name || c.email || '').trim())}</div>
        </header>
        <div class="px-7 py-5 overflow-y-auto space-y-5">
          <div>
            <div class="text-[11px] font-bold tracking-widest text-text-muted mb-2">STATUT</div>
            <select id="cmd-status"
                    class="w-full px-3 py-2 text-sm rounded-lg bg-bg border border-border
                           focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent">
              ${Object.entries(this.STATUSES).filter(([k]) => k).map(([k, m]) =>
                `<option value="${k}" ${k === (c.status || 'lead') ? 'selected' : ''}>${m.label}</option>`
              ).join('')}
            </select>
          </div>
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
            ${field('cmd-email', 'Email', c.email, 'email')}
            ${field('cmd-phone', 'Téléphone', c.phone, 'tel')}
            ${field('cmd-first', 'Prénom', c.first_name)}
            ${field('cmd-last', 'Nom', c.last_name)}
            ${field('cmd-company', 'Entreprise', c.company_name)}
            ${field('cmd-siret', 'SIRET', c.siret)}
            ${field('cmd-vat', 'N° TVA', c.vat_number)}
          </div>
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
            ${field('cmd-addr1', 'Adresse', c.address_line1)}
            ${field('cmd-addr2', 'Complément', c.address_line2)}
            ${field('cmd-zip', 'Code postal', c.address_zip)}
            ${field('cmd-city', 'Ville', c.address_city)}
            ${field('cmd-country', 'Pays', c.address_country || 'France')}
          </div>
          <label class="block">
            <div class="text-[11px] font-bold tracking-widest text-text-muted mb-1">NOTES</div>
            <textarea id="cmd-notes" rows="4"
                      class="w-full px-3 py-2 text-sm rounded-lg bg-bg border border-border
                             focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent
                             resize-y">${this._esc(c.notes || '')}</textarea>
          </label>
        </div>
        <footer class="px-7 py-4 border-t border-border flex justify-end gap-2 shrink-0">
          <button class="btn btn-secondary" id="cmd-cancel">Annuler</button>
          <button class="btn btn-primary" id="cmd-save">Enregistrer</button>
        </footer>
      </div>
    `;
    document.body.appendChild(overlay);

    // Photo des 14 champs à l'ouverture : avant de fermer (clic à côté /
    // Échap), on vérifie qu'aucune saisie ne serait perdue.
    const FIELD_IDS = ['#cmd-status', '#cmd-email', '#cmd-first', '#cmd-last',
      '#cmd-phone', '#cmd-company', '#cmd-siret', '#cmd-vat', '#cmd-addr1',
      '#cmd-addr2', '#cmd-zip', '#cmd-city', '#cmd-country', '#cmd-notes'];
    const snapshot = () => FIELD_IDS
      .map(sel => { const el = overlay.querySelector(sel); return el ? el.value : ''; })
      .join(' ');
    const initialSnapshot = snapshot();

    const close = () => {
      document.removeEventListener('keydown', onEsc);
      overlay.remove();
    };
    const requestClose = async () => {
      if (snapshot() !== initialSnapshot) {
        const ok = await Dialog.confirm(
          'Fermer sans enregistrer ? Tes modifications seront perdues.',
          { title: 'Fiche client', okLabel: 'Fermer', danger: true }
        );
        if (!ok) return;
      }
      close();
    };
    const onEsc = (e) => { if (e.key === 'Escape') requestClose(); };
    document.addEventListener('keydown', onEsc);
    // Si on change d'écran avec la modale ouverte, on la retire proprement
    App.onViewCleanup(() => { if (document.body.contains(overlay)) close(); });

    overlay.querySelector('#cmd-cancel').onclick = () => close();
    overlay.addEventListener('click', e => { if (e.target === overlay) requestClose(); });

    const saveBtn = overlay.querySelector('#cmd-save');
    saveBtn.onclick = async () => {
      // Email : envoyé seulement s'il a changé (le serveur contrôle le
      // format ET l'unicité — jamais deux fiches avec la même adresse).
      const emailVal = overlay.querySelector('#cmd-email').value.trim().toLowerCase();
      const oldEmail = (c.email || '').trim().toLowerCase();
      if (emailVal !== oldEmail) {
        if (!emailVal) {
          Toast.error('L’email ne peut pas rester vide.');
          return;
        }
        if (!/^\S+@\S+\.\S+$/.test(emailVal)) {
          Toast.error('Cette adresse email ne semble pas valide.');
          return;
        }
      }
      const patch = {
        first_name: overlay.querySelector('#cmd-first').value.trim(),
        last_name:  overlay.querySelector('#cmd-last').value.trim(),
        phone:      overlay.querySelector('#cmd-phone').value.trim(),
        company_name: overlay.querySelector('#cmd-company').value.trim(),
        siret:      overlay.querySelector('#cmd-siret').value.trim(),
        vat_number: overlay.querySelector('#cmd-vat').value.trim(),
        address_line1: overlay.querySelector('#cmd-addr1').value.trim(),
        address_line2: overlay.querySelector('#cmd-addr2').value.trim(),
        address_zip:   overlay.querySelector('#cmd-zip').value.trim(),
        address_city:  overlay.querySelector('#cmd-city').value.trim(),
        address_country: overlay.querySelector('#cmd-country').value.trim(),
        status: overlay.querySelector('#cmd-status').value,
        notes:  overlay.querySelector('#cmd-notes').value,
      };
      if (emailVal !== oldEmail) patch.email = emailVal;
      patch.is_pro = !!(patch.company_name || patch.siret);
      saveBtn.disabled = true;
      const saveLabel = saveBtn.textContent;
      saveBtn.textContent = 'Enregistrement…';
      const fail = (errOrRes) => {
        // Échec → la modale RESTE ouverte, la saisie est conservée.
        // Les refus métier du serveur (email déjà pris…) arrivent en
        // français clair → on les montre tels quels.
        if (errOrRes && errOrRes.user_message && errOrRes.error) {
          Toast.error(errOrRes.error, 'Fiche client');
        } else {
          Toast.friendlyError(errOrRes, 'Enregistrement impossible. Ta saisie est conservée, réessaie.');
        }
        saveBtn.disabled = false;
        saveBtn.textContent = saveLabel;
      };
      try {
        const r = await App.api.client_master_update({ id: c.id, patch });
        if (!r || !r.ok) { fail(r); return; }
        Toast.success('Fiche enregistrée.');
        close();
        await this.refresh();
        await this._select(c.id);
      } catch (e) {
        fail(e);
      }
    };
  },

  // ────────────────────────────────────────────────────────────────
  // Helpers
  // ────────────────────────────────────────────────────────────────
  _initials(name) {
    const parts = String(name || '').trim().split(/\s+/).filter(Boolean);
    if (parts.length === 0) return '?';
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
    return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
  },

  _fmtDate(iso) {
    if (!iso) return '—';
    try {
      const d = new Date(iso);
      const today = new Date();
      const sameDay = d.toDateString() === today.toDateString();
      const yest = new Date(today); yest.setDate(today.getDate() - 1);
      const sameYest = d.toDateString() === yest.toDateString();
      const hh = String(d.getHours()).padStart(2, '0');
      const mm = String(d.getMinutes()).padStart(2, '0');
      if (sameDay) return `aujourd’hui ${hh}h${mm}`;
      if (sameYest) return `hier ${hh}h${mm}`;
      return d.toLocaleDateString('fr-FR', { day: '2-digit', month: 'short', year: '2-digit' });
    } catch (_) { return iso.slice(0, 16); }
  },

  _esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    }[c]));
  },
};

// Petit style pour la ligne sélectionnée (injecté à la volée si pas déjà là)
(function() {
  if (document.getElementById('cm-styles')) return;
  const st = document.createElement('style');
  st.id = 'cm-styles';
  st.textContent = `
    .cm-row-selected { background: hsl(var(--bg)) !important; box-shadow: inset 3px 0 0 hsl(var(--accent)); }
  `;
  document.head.appendChild(st);
})();
