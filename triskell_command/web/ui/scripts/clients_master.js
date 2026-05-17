/* Vue Fichier clients — annuaire central 360° de tous les clients
   (table master `clients` agrégée depuis prospection, formulaires de sites,
   factures, mails envoyés, projets de livraison).
   Différent de `clients.js` qui gère le kanban des projets en cours. */

const ClientsMaster = {
  STATUSES: {
    '':         { label: 'Tous',        chip: 'hsl(var(--text-muted))' },
    'lead':     { label: 'Lead',        chip: '#64748b' },
    'prospect': { label: 'Prospect',    chip: '#0ea5e9' },
    'client':   { label: 'Client',      chip: '#10b981' },
    'inactive': { label: 'Inactif',     chip: '#a16207' },
    'churned':  { label: 'Churn',       chip: '#dc2626' },
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
              <div class="text-[10px] font-bold tracking-widest text-text-muted">
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
              font-weight: 600; background: ${color}; color: white;
              border: 0; cursor: pointer; transition: all 160ms;`;
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
      list.innerHTML = this._errorBox('Pas de connexion à l’API.');
      return;
    }
    this._loading = true;
    let data;
    try {
      data = await App.api.get_clients_master({ status: this._status, limit: 500 });
    } catch (e) {
      list.innerHTML = this._errorBox('Erreur : ' + e);
      this._loading = false;
      return;
    }
    this._loading = false;
    if (!data || !data.ok) {
      list.innerHTML = this._errorBox(
        (data && data.error) || 'Connexion à la base partagée impossible.'
      );
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
          <div class="text-sm">${this._clients.length === 0
            ? 'Aucun client enregistré pour l’instant.'
            : 'Rien ne correspond à ta recherche.'}</div>
        </div>
      `;
      return;
    }

    list.innerHTML = filtered.map(c => this._listRow(c)).join('');
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
                    text-white text-sm font-bold"
             style="background: ${meta.chip};">
          ${this._esc(this._initials(name))}
        </div>
        <div class="min-w-0 flex-1">
          <div class="flex items-baseline gap-2">
            <div class="font-semibold text-sm truncate">${this._esc(name)}</div>
            <span class="text-[10px] font-bold px-1.5 py-0.5 rounded shrink-0"
                  style="background: ${meta.chip}22; color: ${meta.chip};">
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

  _errorBox(msg) {
    return `
      <div class="p-8 text-center">
        <div class="text-3xl mb-3">🔌</div>
        <div class="text-sm text-danger">${this._esc(msg)}</div>
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
    let data;
    try { data = await App.api.get_client_master({ id }); }
    catch (e) {
      detail.innerHTML = this._errorBox('Erreur : ' + e);
      return;
    }
    if (!data || !data.ok) {
      detail.innerHTML = this._errorBox((data && data.error) || 'Fiche introuvable.');
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
                    text-white text-lg font-bold"
             style="background: ${meta.chip};">
          ${this._esc(this._initials(name))}
        </div>
        <div class="min-w-0 flex-1">
          <div class="flex items-center gap-2 flex-wrap mb-1">
            <h2 class="font-display text-xl font-bold truncate">${this._esc(name)}</h2>
            <span class="text-[10px] font-bold px-2 py-0.5 rounded"
                  style="background: ${meta.chip}22; color: ${meta.chip};">
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
          <h3 class="text-[10px] font-bold tracking-widest text-text-muted mb-3">COORDONNÉES</h3>
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
            ${this._field('Email', c.email, 'mailto:' + c.email)}
            ${this._field('Téléphone', c.phone, c.phone ? 'tel:' + c.phone.replace(/\s/g, '') : null)}
            ${this._field('Prénom', c.first_name)}
            ${this._field('Nom', c.last_name)}
          </div>
        </section>

        <!-- Société (si pro) -->
        ${(c.is_pro || c.company_name || c.siret) ? `
        <section>
          <h3 class="text-[10px] font-bold tracking-widest text-text-muted mb-3">SOCIÉTÉ</h3>
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
            ${this._field('Entreprise', c.company_name)}
            ${this._field('SIRET', c.siret)}
            ${this._field('N° TVA', c.vat_number)}
          </div>
        </section>` : ''}

        <!-- Adresse -->
        ${(c.address_line1 || c.address_city) ? `
        <section>
          <h3 class="text-[10px] font-bold tracking-widest text-text-muted mb-3">ADRESSE</h3>
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
          <h3 class="text-[10px] font-bold tracking-widest text-text-muted mb-3">ACTIVITÉ</h3>
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
              <span class="font-bold text-success">${Math.round(c.total_paid_cents / 100)} €</span>
            </div>
          ` : ''}
        </section>

        <!-- Tags -->
        <section>
          <h3 class="text-[10px] font-bold tracking-widest text-text-muted mb-3">TAGS</h3>
          <div class="flex flex-wrap gap-2 items-center" id="cm-tags">
            ${(c.tags && c.tags.length) ? c.tags.map(t => `
              <span class="text-[11px] font-semibold px-2 py-1 rounded-full
                           bg-accent/10 text-accent border border-accent/20">
                ${this._esc(t)}
              </span>
            `).join('') : '<span class="text-sm text-text-muted">Aucun tag</span>'}
            <button id="cm-add-tag" class="text-[11px] text-text-muted hover:text-accent underline">
              + Ajouter
            </button>
          </div>
        </section>

        <!-- Notes -->
        <section>
          <h3 class="text-[10px] font-bold tracking-widest text-text-muted mb-3">NOTES</h3>
          ${c.notes ? `
            <div class="text-sm whitespace-pre-wrap p-3 rounded-lg bg-bg border border-border">
              ${this._esc(c.notes)}
            </div>
          ` : `<div class="text-sm text-text-muted italic">Aucune note pour ce client.</div>`}
        </section>

        <!-- Timeline -->
        <section>
          <h3 class="text-[10px] font-bold tracking-widest text-text-muted mb-3">
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
  },

  _field(label, value, href) {
    const v = (value || '').toString().trim();
    if (!v) {
      return `
        <div>
          <div class="text-[10px] font-bold tracking-widest text-text-muted mb-1">${this._esc(label)}</div>
          <div class="text-sm text-text-muted italic">—</div>
        </div>
      `;
    }
    const content = href
      ? `<a href="${href}" class="text-sm text-accent hover:underline">${this._esc(v)}</a>`
      : `<div class="text-sm">${this._esc(v)}</div>`;
    return `
      <div>
        <div class="text-[10px] font-bold tracking-widest text-text-muted mb-1">${this._esc(label)}</div>
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
        <div class="text-[10px] text-text-muted mt-1">${this._esc(label)}</div>
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
    const tag = (prompt('Nouveau tag :') || '').trim();
    if (!tag || !this._selectedId) return;
    try {
      await App.api.client_master_add_tag({ id: this._selectedId, tag });
      await this._select(this._selectedId);
    } catch (e) { alert('Erreur : ' + e); }
  },

  _openEditDialog() {
    const c = this._detail.client;
    const overlay = document.createElement('div');
    overlay.className = 'fixed inset-0 z-[100] flex items-center justify-center p-6';
    overlay.style.background = 'rgba(15,23,42,0.45)';
    overlay.style.backdropFilter = 'blur(6px)';
    const field = (id, label, val, type = 'text') => `
      <label class="block">
        <div class="text-[10px] font-bold tracking-widest text-text-muted mb-1">${label}</div>
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
            <div class="text-[10px] font-bold tracking-widest text-text-muted mb-2">STATUT</div>
            <select id="cmd-status"
                    class="w-full px-3 py-2 text-sm rounded-lg bg-bg border border-border
                           focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent">
              ${Object.entries(this.STATUSES).filter(([k]) => k).map(([k, m]) =>
                `<option value="${k}" ${k === (c.status || 'lead') ? 'selected' : ''}>${m.label}</option>`
              ).join('')}
            </select>
          </div>
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
            ${field('cmd-first', 'Prénom', c.first_name)}
            ${field('cmd-last', 'Nom', c.last_name)}
            ${field('cmd-phone', 'Téléphone', c.phone, 'tel')}
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
            <div class="text-[10px] font-bold tracking-widest text-text-muted mb-1">NOTES</div>
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
    const close = () => overlay.remove();
    overlay.querySelector('#cmd-cancel').onclick = close;
    overlay.addEventListener('click', e => { if (e.target === overlay) close(); });
    overlay.querySelector('#cmd-save').onclick = async () => {
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
      patch.is_pro = !!(patch.company_name || patch.siret);
      try {
        const r = await App.api.client_master_update({ id: c.id, patch });
        if (!r || !r.ok) {
          alert('Sauvegarde impossible : ' + ((r && r.error) || 'erreur inconnue'));
          return;
        }
        close();
        await this.refresh();
        await this._select(c.id);
      } catch (e) {
        alert('Erreur : ' + e);
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
