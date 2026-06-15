/* Créateurs — suivi de prospection des créateurs (YouTubeurs,
 * Instagrameurs…) qu'on démarche surtout PAR RÉSEAUX SOCIAUX (pas par
 * mail). Pour chaque créateur : le canal de contact, le message envoyé,
 * les dates, le statut, une DATE DE PROCHAINE RELANCE réglable à la main
 * + une vue « à relancer », et le lien de la démo qu'on lui a construite.
 *
 * Données : table partagée `prospects` (la même qu'Obélisk). L'UI ne
 * touche jamais Supabase : tout passe par App.api.creators_* (cf.
 * web/api.py → classe Api → méthodes creators_*).
 *
 * Pattern calqué sur chasseur_createurs.js (objet vue autonome + helper
 * _api) et obelisk.js (liste + drawer d'édition + statut).
 */

const Creators = {
  state: {
    rows: [],          // liste principale
    dueRows: [],       // bandeau « à relancer »
    total: 0,
    filters: { channel: '', status: '' },
    selected: null,    // créateur ouvert dans le drawer
    loading: false,
  },

  // Étiquettes FR des statuts (on RÉUTILISE les statuts anglais existants
  // côté base : new/qualified/contacted/replied/won/lost/refused — aucune
  // nouvelle valeur inventée, juste l'affichage en français).
  STATUS_LABELS: {
    new: 'Nouveau', qualified: 'Qualifié', contacted: 'Contacté',
    replied: 'A répondu', won: 'Signé', lost: 'Perdu', refused: 'Refusé',
  },
  STATUS_COLORS: {
    new:       'text-text-muted bg-text-muted/10',
    qualified: 'text-info bg-info/10',
    contacted: 'text-warning bg-warning/10',
    replied:   'text-accent bg-accent/10',
    won:       'text-success bg-success/15',
    lost:      'text-text-muted bg-text-muted/10',
    refused:   'text-danger bg-danger/10',
  },

  // Canaux de contact : valeur stockée (en base) → étiquette + icône.
  CHANNELS: [
    { v: 'instagram', label: 'Instagram', icon: '📷' },
    { v: 'tiktok',    label: 'TikTok',    icon: '🎵' },
    { v: 'youtube',   label: 'YouTube',   icon: '📹' },
    { v: 'facebook',  label: 'Facebook',  icon: '📘' },
    { v: 'email',     label: 'Email',     icon: '✉️' },
    { v: 'autre',     label: 'Autre',     icon: '💬' },
  ],

  // ---- Pont vers le backend : App.api.creators_<method> ----
  async _api(method, payload) {
    if (!App.api) return null;
    const fn = App.api['creators_' + method];
    if (typeof fn !== 'function') {
      console.warn('creators_' + method + ' indisponible');
      return null;
    }
    try { return await fn(payload || {}); }
    catch (e) {
      console.warn('creators.' + method, e);
      if (window.Toast && Toast.friendlyError) Toast.friendlyError(e);
      return null;
    }
  },

  // ====================================================================
  // Rendu principal
  // ====================================================================
  async render(container) {
    this._root = container;
    this._injectStyles();
    container.innerHTML = `
      <section class="animate-slide-up">
        <header class="cr-header">
          <div class="cr-header-text">
            <div class="hero-kicker" style="color: hsl(var(--accent));">CRÉATEURS</div>
            <h1 class="cr-title">Les créateurs que tu démarches, suivis un par un.</h1>
            <p class="text-xs text-text-muted mt-1" style="text-wrap: pretty">
              Contact par réseaux sociaux, message envoyé, prochaine relance, lien de la démo.
              Tout au même endroit pour ne plus en perdre un seul.
            </p>
          </div>
          <div class="cr-header-actions">
            <button id="cr-add" class="btn btn-primary">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
              Ajouter un créateur
            </button>
            <button id="cr-refresh" class="cr-icon-btn" title="Rafraîchir" aria-label="Rafraîchir">↻</button>
          </div>
        </header>

        <!-- Bandeau « À relancer » -->
        <div id="cr-due"></div>

        <!-- Filtres -->
        <div class="cr-filters">
          <select id="cr-f-channel" aria-label="Filtrer par canal">
            <option value="">Tous les canaux</option>
            ${this.CHANNELS.map(c => `<option value="${c.v}">${c.icon} ${this._esc(c.label)}</option>`).join('')}
          </select>
          <select id="cr-f-status" aria-label="Filtrer par statut">
            <option value="">Tous les statuts</option>
            ${Object.entries(this.STATUS_LABELS).map(([k, l]) => `<option value="${k}">${this._esc(l)}</option>`).join('')}
          </select>
        </div>

        <!-- Liste principale -->
        <div id="cr-list"></div>
      </section>
    `;

    document.getElementById('cr-add').onclick = () => this._openForm();
    document.getElementById('cr-refresh').onclick = () => this._loadAll();
    const fChan = document.getElementById('cr-f-channel');
    const fStat = document.getElementById('cr-f-status');
    fChan.value = this.state.filters.channel;
    fStat.value = this.state.filters.status;
    fChan.onchange = () => { this.state.filters.channel = fChan.value; this._loadList(); };
    fStat.onchange = () => { this.state.filters.status = fStat.value; this._loadList(); };

    await this._loadAll();
  },

  async _loadAll() {
    await Promise.all([this._loadDue(), this._loadList()]);
  },

  // -------------------------------------------------------------------
  // Bandeau « À relancer »
  // -------------------------------------------------------------------
  async _loadDue() {
    const slot = document.getElementById('cr-due');
    if (!slot) return;
    const r = await this._api('list', { relance: true, limit: 50 });
    if (!r || !r.ok) {
      // Pas bloquant : on n'affiche simplement pas le bandeau.
      this.state.dueRows = [];
      slot.innerHTML = '';
      return;
    }
    this.state.dueRows = r.rows || [];
    this._renderDue();
  },

  _renderDue() {
    const slot = document.getElementById('cr-due');
    if (!slot) return;
    const rows = this.state.dueRows || [];
    if (!rows.length) { slot.innerHTML = ''; return; }
    slot.innerHTML = `
      <div class="cr-due-card">
        <div class="cr-due-head">
          <span class="cr-due-bell">🔔</span>
          <b>${rows.length} créateur${rows.length > 1 ? 's' : ''} à relancer</b>
          <span class="cr-due-sub">prochaine relance dépassée, ou contactés depuis un moment sans suite</span>
        </div>
        <div class="cr-due-list">
          ${rows.map(c => this._dueRowHtml(c)).join('')}
        </div>
      </div>
    `;
    slot.querySelectorAll('[data-cr-open]').forEach(el => {
      el.onclick = () => this._openCreator(el.dataset.crOpen);
    });
    slot.querySelectorAll('[data-cr-done]').forEach(el => {
      el.onclick = (e) => { e.stopPropagation(); this._markRelanced(el.dataset.crDone); };
    });
    slot.querySelectorAll('[data-cr-snooze]').forEach(el => {
      el.onclick = (e) => { e.stopPropagation(); this._snooze(el.dataset.crSnooze); };
    });
  },

  _dueRowHtml(c) {
    const chan = this._channelMeta(c.contact_channel);
    const lastMsg = this._lastMessagePreview(c);
    return `
      <div class="cr-due-row" data-cr-open="${this._esc(c.id)}">
        <div class="cr-due-row-main">
          <div class="cr-due-row-name">${chan.icon} ${this._esc(c.name || c.handle || '(sans nom)')}</div>
          <div class="cr-due-row-meta">
            <span>${this._esc(chan.label)}</span>
            ${c.next_follow_up_at ? `<span class="cr-overdue">relance prévue le ${this._fmtDate(c.next_follow_up_at)}</span>`
                                  : `<span>contacté le ${this._fmtDate(c.last_contact_at) || '?'}</span>`}
          </div>
          ${lastMsg ? `<div class="cr-due-row-msg" title="${this._esc(lastMsg)}">« ${this._esc(lastMsg.slice(0, 90))}${lastMsg.length > 90 ? '…' : ''} »</div>` : ''}
        </div>
        <div class="cr-due-row-actions">
          <button class="btn btn-secondary cr-mini" data-cr-snooze="${this._esc(c.id)}" title="Reporter la relance à plus tard">Reporter</button>
          <button class="btn btn-primary cr-mini" data-cr-done="${this._esc(c.id)}" title="Marquer comme relancé (efface la date de relance)">Relancé</button>
        </div>
      </div>
    `;
  },

  // « Marquer relancé » : on enlève la date de relance (relance faite). On
  // ne change pas le statut : à l'utilisateur de le faire dans la fiche.
  async _markRelanced(id) {
    if (!id) return;
    const r = await this._api('save', { id, next_follow_up_at: '' });
    if (!r || !r.ok) { Toast.error((r && r.error) || 'Action impossible.'); return; }
    Toast.success('Marqué comme relancé.');
    await this._loadAll();
  },

  // « Reporter » : repousse la relance de +7 jours par défaut, via un petit
  // prompt de date pour rester souple.
  async _snooze(id) {
    if (!id) return;
    const def = this._isoDatePlusDays(7);
    const val = await this._promptDate('Reporter la relance à quelle date ?', def);
    if (val === null) return;  // annulé
    const r = await this._api('save', { id, next_follow_up_at: val ? this._dateToIso(val) : '' });
    if (!r || !r.ok) { Toast.error((r && r.error) || 'Report impossible.'); return; }
    Toast.success(val ? `Relance reportée au ${this._fmtDate(this._dateToIso(val))}.` : 'Relance retirée.');
    await this._loadAll();
  },

  // -------------------------------------------------------------------
  // Liste principale
  // -------------------------------------------------------------------
  async _loadList() {
    const wrap = document.getElementById('cr-list');
    if (wrap && !this.state.rows.length) {
      wrap.innerHTML = `<div class="cr-empty text-text-muted">Chargement…</div>`;
    }
    const r = await this._api('list', {
      channel: this.state.filters.channel,
      status: this.state.filters.status,
      limit: 200,
    });
    if (!r || !r.ok) {
      if (wrap) wrap.innerHTML = `
        <div class="cr-empty">
          <div class="text-3xl mb-2 opacity-70">⚠️</div>
          <div>Impossible de charger la liste. Vérifie ta connexion puis réessaie.</div>
          <button id="cr-retry" class="btn btn-secondary mt-3">Réessayer</button>
        </div>`;
      const rb = document.getElementById('cr-retry');
      if (rb) rb.onclick = () => this._loadList();
      return;
    }
    this.state.rows = r.rows || [];
    this.state.total = r.count || this.state.rows.length;
    this._renderList();
  },

  _renderList() {
    const wrap = document.getElementById('cr-list');
    if (!wrap) return;
    const rows = this.state.rows || [];
    const hasFilter = this.state.filters.channel || this.state.filters.status;

    if (!rows.length) {
      wrap.innerHTML = hasFilter ? `
        <div class="cr-empty">
          <div class="text-3xl mb-2 opacity-70">🔍</div>
          <div>Aucun créateur avec ces filtres.</div>
        </div>` : `
        <div class="cr-empty">
          <div class="text-4xl mb-3 opacity-70">🎬</div>
          <div class="text-base font-semibold mb-1">Aucun créateur suivi pour l'instant.</div>
          <div class="text-text-muted mb-4">Ajoute le premier créateur que tu démarches pour commencer à le suivre.</div>
          <button id="cr-empty-add" class="btn btn-primary">+ Ajouter un créateur</button>
        </div>`;
      const ea = document.getElementById('cr-empty-add');
      if (ea) ea.onclick = () => this._openForm();
      return;
    }

    wrap.innerHTML = `
      <div class="cr-table-card">
        <div class="cr-table-scroll">
          <table class="cr-table">
            <thead>
              <tr>
                <th>Créateur</th>
                <th>Canal</th>
                <th>Abonnés</th>
                <th>Statut</th>
                <th>Dernier contact</th>
                <th>Prochaine relance</th>
              </tr>
            </thead>
            <tbody>
              ${rows.map(c => this._listRowHtml(c)).join('')}
            </tbody>
          </table>
        </div>
      </div>
      <div class="cr-count">${rows.length} créateur${rows.length > 1 ? 's' : ''}${this.state.total > rows.length ? ` sur ${this.state.total}` : ''}</div>
    `;
    wrap.querySelectorAll('[data-cr-open]').forEach(tr => {
      tr.onclick = () => this._openCreator(tr.dataset.crOpen);
      tr.tabIndex = 0;
      tr.onkeydown = (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); this._openCreator(tr.dataset.crOpen); } };
    });
  },

  _listRowHtml(c) {
    const chan = this._channelMeta(c.contact_channel);
    const st = c.status || 'new';
    const overdue = this._isOverdue(c.next_follow_up_at);
    return `
      <tr class="cr-row" data-cr-open="${this._esc(c.id)}" role="button">
        <td class="cr-cell-name">
          <div class="cr-name">${this._esc(c.name || c.handle || '(sans nom)')}</div>
          ${c.handle ? `<div class="cr-handle">@${this._esc(c.handle)}</div>` : ''}
        </td>
        <td>${chan.icon} <span class="cr-chan-label">${this._esc(chan.label)}</span></td>
        <td class="tabular-nums">${c.subscribers ? Number(c.subscribers).toLocaleString('fr-FR') : '—'}</td>
        <td><span class="cr-pill ${this.STATUS_COLORS[st] || ''}">${this._esc(this.STATUS_LABELS[st] || st)}</span></td>
        <td class="cr-date">${this._fmtDate(c.last_contact_at) || '—'}</td>
        <td class="cr-date">
          ${c.next_follow_up_at
            ? `<span class="${overdue ? 'cr-overdue' : ''}">${overdue ? '⚠ ' : ''}${this._fmtDate(c.next_follow_up_at)}</span>`
            : '<span class="text-text-muted">—</span>'}
        </td>
      </tr>
    `;
  },

  // ====================================================================
  // Drawer : fiche d'édition + historique des messages
  // ====================================================================
  async _openCreator(id) {
    const res = await this._api('get', { id });
    if (!res || !res.ok) {
      if (res) Toast.friendlyError(res.error, 'Impossible de charger ce créateur.');
      return;
    }
    this.state.selected = res.prospect;
    this.state.selectedHistory = res.history || [];
    this._renderDrawer();
  },

  _closeDrawer() {
    this._removeDrawerEsc();
    const d = document.getElementById('cr-drawer');
    const b = document.getElementById('cr-drawer-backdrop');
    if (d) d.classList.remove('is-open');
    if (b) b.classList.remove('is-open');
    setTimeout(() => { if (d) d.remove(); if (b) b.remove(); }, 220);
    this.state.selected = null;
  },

  _removeDrawerEsc() {
    if (this._drawerEsc) {
      document.removeEventListener('keydown', this._drawerEsc);
      this._drawerEsc = null;
    }
  },

  _renderDrawer() {
    const p = this.state.selected;
    if (!p) return;
    const old = document.getElementById('cr-drawer');
    const oldBd = document.getElementById('cr-drawer-backdrop');
    if (old) old.remove();
    if (oldBd) oldBd.remove();

    const bd = document.createElement('div');
    bd.id = 'cr-drawer-backdrop';
    bd.className = 'cr-drawer-backdrop';
    bd.onclick = () => this._closeDrawer();

    const d = document.createElement('div');
    d.id = 'cr-drawer';
    d.className = 'cr-drawer';

    const chan = this._channelMeta(p.contact_channel);
    const purl = this._safeUrl(p.platform_url);
    const demo = this._safeUrl(p.demo_url);
    const history = (this.state.selectedHistory || []).filter(h =>
      (h.kind === 'outreach_sent') || (h.body && h.body.trim()));

    d.innerHTML = `
      <div class="flex items-start justify-between mb-4">
        <div class="min-w-0">
          <div class="hero-kicker mb-1">${chan.icon} ${this._esc(chan.label)}</div>
          <h2 class="text-2xl font-bold leading-tight">${this._esc(p.name || p.handle || '(sans nom)')}</h2>
          ${p.handle ? `<div class="text-sm text-text-muted">@${this._esc(p.handle)}</div>` : ''}
        </div>
        <button id="cr-d-close" class="text-text-muted hover:text-text text-2xl leading-none" title="Fermer" aria-label="Fermer la fiche">×</button>
      </div>

      <div class="grid grid-cols-2 gap-3 mb-5">
        <div class="cr-stat"><div class="label">Abonnés</div><div class="value">${p.subscribers ? Number(p.subscribers).toLocaleString('fr-FR') : '—'}</div></div>
        <div class="cr-stat"><div class="label">Dernier contact</div><div class="value cr-stat-date">${this._fmtDate(p.last_contact_at) || '—'}</div></div>
      </div>

      ${p.platform_url ? `<div class="mb-4">
        <div class="cr-label">Profil / lien</div>
        ${purl ? `<a href="${this._esc(purl)}" target="_blank" rel="noopener" class="text-info hover:underline text-sm break-all">${this._esc(p.platform_url)}</a>`
               : `<span class="text-sm break-all text-text-muted">${this._esc(p.platform_url)}</span>`}
      </div>` : ''}

      <div class="cr-edit">
        <div class="cr-label">Statut</div>
        <select id="cr-d-status" class="cr-input">
          ${Object.entries(this.STATUS_LABELS).map(([k, l]) => `<option value="${k}" ${(p.status || 'new') === k ? 'selected' : ''}>${this._esc(l)}</option>`).join('')}
        </select>

        <div class="cr-label mt-4">Canal de contact</div>
        <select id="cr-d-channel" class="cr-input">
          <option value="">— non précisé —</option>
          ${this.CHANNELS.map(c => `<option value="${c.v}" ${(p.contact_channel || '') === c.v ? 'selected' : ''}>${c.icon} ${this._esc(c.label)}</option>`).join('')}
        </select>

        <div class="cr-label mt-4">Prochaine relance</div>
        <input id="cr-d-nfu" type="date" class="cr-input" value="${this._esc(this._isoToDate(p.next_follow_up_at))}">
        <div class="cr-hint">Laisse vide si aucune relance à programmer.</div>

        <div class="cr-label mt-4">Lien de la démo</div>
        <input id="cr-d-demo" type="url" class="cr-input" placeholder="https://…" value="${this._esc(p.demo_url || '')}">
        ${demo ? `<a href="${this._esc(demo)}" target="_blank" rel="noopener" class="cr-hint text-info hover:underline">Ouvrir la démo ↗</a>` : ''}

        <div class="cr-label mt-4">Notes</div>
        <textarea id="cr-d-notes" rows="3" class="cr-input" placeholder="Notes internes…">${this._esc(p.notes || '')}</textarea>

        <div class="flex gap-2 mt-4">
          <button id="cr-d-save" class="btn btn-primary flex-1">Enregistrer</button>
        </div>
      </div>

      <!-- Historique des messages -->
      <div class="cr-history">
        <div class="cr-label flex items-center justify-between">
          <span>Messages envoyés</span>
          <button id="cr-d-newmsg" class="btn btn-secondary cr-mini">+ Nouveau message</button>
        </div>
        <div id="cr-d-msgform" class="cr-msgform" hidden>
          <textarea id="cr-d-msgbody" rows="3" class="cr-input" placeholder="Colle ici le message que tu as envoyé (DM, commentaire…)"></textarea>
          <div class="cr-msgform-row">
            <select id="cr-d-msgchan" class="cr-input cr-input-sm">
              ${this.CHANNELS.map(c => `<option value="${c.v}" ${(p.contact_channel || 'instagram') === c.v ? 'selected' : ''}>${c.icon} ${this._esc(c.label)}</option>`).join('')}
            </select>
            <button id="cr-d-msgsave" class="btn btn-primary cr-mini">Enregistrer le message</button>
          </div>
        </div>
        <div id="cr-d-msglist" class="cr-msglist">
          ${history.length ? history.map(h => this._historyRowHtml(h)).join('')
                           : `<div class="cr-hint">Aucun message enregistré pour l'instant.</div>`}
        </div>
      </div>

      <div class="mt-6 pt-4 border-t border-border">
        <button id="cr-d-delete" class="text-danger text-[11px] hover:underline">Supprimer ce créateur</button>
      </div>
    `;

    document.body.appendChild(bd);
    document.body.appendChild(d);
    requestAnimationFrame(() => { bd.classList.add('is-open'); d.classList.add('is-open'); });

    this._removeDrawerEsc();
    this._drawerEsc = (e) => { if (e.key === 'Escape') { e.preventDefault(); this._closeDrawer(); } };
    document.addEventListener('keydown', this._drawerEsc);
    App.onViewCleanup(() => this._closeDrawer());

    document.getElementById('cr-d-close').onclick = () => this._closeDrawer();

    // Enregistrer la fiche (statut, canal, relance, démo, notes)
    const saveBtn = document.getElementById('cr-d-save');
    saveBtn.onclick = async () => {
      const dateVal = document.getElementById('cr-d-nfu').value;
      const fields = {
        id: p.id,
        status: document.getElementById('cr-d-status').value,
        contact_channel: document.getElementById('cr-d-channel').value,
        next_follow_up_at: dateVal ? this._dateToIso(dateVal) : '',
        demo_url: document.getElementById('cr-d-demo').value,
        notes: document.getElementById('cr-d-notes').value,
      };
      saveBtn.disabled = true;
      const res = await this._api('save', fields);
      saveBtn.disabled = false;
      if (!res || !res.ok) { if (res) Toast.friendlyError(res.error, 'L\'enregistrement a échoué.'); return; }
      if (res.warning) Toast.warn(res.warning);
      Toast.success('Fiche enregistrée.');
      this._closeDrawer();
      await this._loadAll();
    };

    // Bascule du formulaire « nouveau message »
    const newMsgBtn = document.getElementById('cr-d-newmsg');
    newMsgBtn.onclick = () => {
      const form = document.getElementById('cr-d-msgform');
      if (form) { form.hidden = !form.hidden; if (!form.hidden) document.getElementById('cr-d-msgbody').focus(); }
    };

    // Enregistrer un nouveau message envoyé
    const msgSave = document.getElementById('cr-d-msgsave');
    if (msgSave) msgSave.onclick = async () => {
      const body = document.getElementById('cr-d-msgbody').value.trim();
      const channel = document.getElementById('cr-d-msgchan').value;
      if (!body) { Toast.warn('Écris le message avant d\'enregistrer.'); return; }
      msgSave.disabled = true;
      const res = await this._api('log_message', {
        id: p.id, message: body, channel,
        demo_url: document.getElementById('cr-d-demo').value.trim(),
      });
      msgSave.disabled = false;
      if (!res || !res.ok) { if (res) Toast.friendlyError(res.error, 'Enregistrement du message impossible.'); return; }
      if (res.warning) Toast.warn(res.warning);
      Toast.success('Message enregistré.');
      // Recharge la fiche pour montrer le message + le statut « Contacté ».
      await this._openCreator(p.id);
      this._loadAll();
    };

    // Supprimer
    const delBtn = document.getElementById('cr-d-delete');
    delBtn.onclick = async () => {
      const ok = await Dialog.confirm(
        `« ${p.name || p.handle || 'Ce créateur'} » sera supprimé définitivement.\n\nAucun retour en arrière possible.`,
        { title: 'Supprimer ce créateur', okLabel: 'Supprimer', cancelLabel: 'Annuler', danger: true });
      if (!ok) return;
      delBtn.disabled = true;
      const res = await this._api('delete', { id: p.id });
      delBtn.disabled = false;
      if (!res || !res.ok) { if (res) Toast.friendlyError(res.error, 'La suppression a échoué.'); return; }
      Toast.success('Créateur supprimé.');
      this._closeDrawer();
      await this._loadAll();
    };
  },

  _historyRowHtml(h) {
    const extra = h.extra || {};
    const chan = this._channelMeta(extra.channel || '');
    const body = h.body || '';
    return `
      <div class="cr-msg">
        <div class="cr-msg-head">
          <span>${chan.icon} ${this._esc(chan.label)}</span>
          <span class="cr-msg-date">${this._fmtDateTime(h.ts)}</span>
        </div>
        <div class="cr-msg-body">${this._esc(body)}</div>
      </div>
    `;
  },

  // ====================================================================
  // Formulaire « Ajouter un créateur » (création)
  // ====================================================================
  _openForm() {
    const old = document.getElementById('cr-drawer');
    const oldBd = document.getElementById('cr-drawer-backdrop');
    if (old) old.remove();
    if (oldBd) oldBd.remove();

    const bd = document.createElement('div');
    bd.id = 'cr-drawer-backdrop';
    bd.className = 'cr-drawer-backdrop';
    bd.onclick = () => this._closeDrawer();

    const d = document.createElement('div');
    d.id = 'cr-drawer';
    d.className = 'cr-drawer';
    d.innerHTML = `
      <div class="flex items-start justify-between mb-5">
        <h2 class="text-2xl font-bold leading-tight">Nouveau créateur</h2>
        <button id="cr-f-close" class="text-text-muted hover:text-text text-2xl leading-none" title="Fermer" aria-label="Fermer">×</button>
      </div>

      <div class="cr-edit">
        <div class="cr-label">Nom <span class="text-danger">*</span></div>
        <input id="cr-new-name" class="cr-input" placeholder="ex : Émilie crochet" autocomplete="off">

        <div class="cr-label mt-4">Réseau / canal de contact</div>
        <select id="cr-new-channel" class="cr-input">
          ${this.CHANNELS.map(c => `<option value="${c.v}" ${c.v === 'instagram' ? 'selected' : ''}>${c.icon} ${this._esc(c.label)}</option>`).join('')}
        </select>

        <div class="cr-label mt-4">Lien du profil ou @pseudo</div>
        <input id="cr-new-link" class="cr-input" placeholder="https://instagram.com/… ou @pseudo" autocomplete="off">

        <div class="grid grid-cols-2 gap-3">
          <div>
            <div class="cr-label mt-4">Abonnés <span class="text-text-muted font-normal">(optionnel)</span></div>
            <input id="cr-new-subs" type="number" min="0" class="cr-input" placeholder="ex : 25000">
          </div>
          <div>
            <div class="cr-label mt-4">Statut</div>
            <select id="cr-new-status" class="cr-input">
              ${Object.entries(this.STATUS_LABELS).map(([k, l]) => `<option value="${k}" ${k === 'new' ? 'selected' : ''}>${this._esc(l)}</option>`).join('')}
            </select>
          </div>
        </div>

        <div class="cr-label mt-4">Message envoyé <span class="text-text-muted font-normal">(optionnel)</span></div>
        <textarea id="cr-new-msg" rows="3" class="cr-input" placeholder="Le message que tu lui as envoyé. Si rempli, il est enregistré dans l'historique et le créateur passe en « Contacté »."></textarea>

        <div class="grid grid-cols-2 gap-3">
          <div>
            <div class="cr-label mt-4">Date de contact</div>
            <input id="cr-new-contact" type="date" class="cr-input">
          </div>
          <div>
            <div class="cr-label mt-4">Prochaine relance</div>
            <input id="cr-new-nfu" type="date" class="cr-input">
          </div>
        </div>

        <div class="cr-label mt-4">Lien de la démo <span class="text-text-muted font-normal">(optionnel)</span></div>
        <input id="cr-new-demo" type="url" class="cr-input" placeholder="https://… la démo que tu lui as construite">

        <div class="cr-label mt-4">Notes <span class="text-text-muted font-normal">(optionnel)</span></div>
        <textarea id="cr-new-notes" rows="2" class="cr-input" placeholder="Notes internes…"></textarea>

        <div class="flex gap-2 mt-5">
          <button id="cr-new-save" class="btn btn-primary flex-1">Ajouter le créateur</button>
          <button id="cr-new-cancel" class="btn btn-secondary">Annuler</button>
        </div>
      </div>
    `;

    document.body.appendChild(bd);
    document.body.appendChild(d);
    requestAnimationFrame(() => { bd.classList.add('is-open'); d.classList.add('is-open'); });

    this._removeDrawerEsc();
    this._drawerEsc = (e) => { if (e.key === 'Escape') { e.preventDefault(); this._closeDrawer(); } };
    document.addEventListener('keydown', this._drawerEsc);
    App.onViewCleanup(() => this._closeDrawer());

    document.getElementById('cr-f-close').onclick = () => this._closeDrawer();
    document.getElementById('cr-new-cancel').onclick = () => this._closeDrawer();
    // Pré-remplit la date de contact à aujourd'hui si un message est saisi.
    setTimeout(() => { const n = document.getElementById('cr-new-name'); if (n) n.focus(); }, 60);

    const saveBtn = document.getElementById('cr-new-save');
    saveBtn.onclick = async () => {
      const name = document.getElementById('cr-new-name').value.trim();
      if (!name) { Toast.warn('Le nom est obligatoire.'); return; }
      const link = document.getElementById('cr-new-link').value.trim();
      const isUrl = /^https?:\/\//i.test(link);
      const message = document.getElementById('cr-new-msg').value.trim();
      const contactDate = document.getElementById('cr-new-contact').value;
      const nfuDate = document.getElementById('cr-new-nfu').value;
      const subsRaw = document.getElementById('cr-new-subs').value;

      // Si un message est saisi et qu'aucune date de contact n'est donnée,
      // on considère « contacté aujourd'hui ».
      const lastContact = contactDate ? this._dateToIso(contactDate)
                        : (message ? new Date().toISOString() : '');

      const payload = {
        name,
        contact_channel: document.getElementById('cr-new-channel').value,
        handle: isUrl ? '' : link.replace(/^@/, ''),
        platform_url: isUrl ? link : '',
        subscribers: subsRaw ? parseInt(subsRaw, 10) : null,
        status: document.getElementById('cr-new-status').value,
        next_follow_up_at: nfuDate ? this._dateToIso(nfuDate) : '',
        demo_url: document.getElementById('cr-new-demo').value.trim(),
        last_contact_at: lastContact,
        notes: document.getElementById('cr-new-notes').value.trim(),
      };

      saveBtn.disabled = true;
      const res = await this._api('save', payload);
      if (!res || !res.ok) {
        saveBtn.disabled = false;
        if (res) Toast.friendlyError(res.error, 'Création impossible.');
        return;
      }
      const newId = res.prospect_id;
      // Si un message a été saisi, on l'enregistre dans l'historique.
      if (message && newId) {
        await this._api('log_message', {
          id: newId, message,
          channel: payload.contact_channel,
          demo_url: payload.demo_url,
        });
      }
      saveBtn.disabled = false;
      if (res.warning) Toast.warn(res.warning);
      Toast.success(res.action === 'exists' ? 'Ce créateur existait déjà — fiche ouverte.' : 'Créateur ajouté.');
      this._closeDrawer();
      await this._loadAll();
    };
  },

  // ====================================================================
  // Helpers
  // ====================================================================
  _channelMeta(v) {
    const found = this.CHANNELS.find(c => c.v === (v || '').toLowerCase());
    return found || { v: '', label: 'Non précisé', icon: '•' };
  },

  // Récupère un aperçu du dernier message envoyé, depuis les rows de la
  // liste (la liste n'embarque pas l'historique → on retombe sur les notes
  // si rien d'autre). Best-effort pour le bandeau « à relancer ».
  _lastMessagePreview(c) {
    if (c._last_message) return c._last_message;
    return '';
  },

  _safeUrl(u) {
    const s = String(u || '').trim();
    return /^https?:\/\//i.test(s) ? s : '';
  },

  _isOverdue(iso) {
    if (!iso) return false;
    try { return new Date(iso).getTime() <= Date.now(); }
    catch (e) { return false; }
  },

  _esc(s) {
    if (s == null) return '';
    return String(s).replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
  },

  _fmtDate(iso) {
    if (!iso) return '';
    try {
      return new Date(iso).toLocaleDateString('fr-FR', { day: '2-digit', month: 'short', year: '2-digit' });
    } catch (e) { return ''; }
  },

  _fmtDateTime(iso) {
    if (!iso) return '';
    try {
      return new Date(iso).toLocaleString('fr-FR', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
    } catch (e) { return iso; }
  },

  // <input type="date"> ⇄ ISO. La valeur d'un input date = "YYYY-MM-DD".
  _isoToDate(iso) {
    if (!iso) return '';
    try { return new Date(iso).toISOString().slice(0, 10); }
    catch (e) { return ''; }
  },
  _dateToIso(d) {
    // d = "YYYY-MM-DD" → ISO à midi (évite les surprises de fuseau qui
    // feraient reculer la date d'un jour).
    if (!d) return '';
    return new Date(d + 'T12:00:00').toISOString();
  },
  _isoDatePlusDays(n) {
    const d = new Date();
    d.setDate(d.getDate() + n);
    return d.toISOString().slice(0, 10);
  },

  // Petit prompt de date réutilisable via Dialog si dispo, sinon window.prompt.
  async _promptDate(question, defaultDate) {
    // Dialog.prompt n'est pas garanti partout → fallback prompt natif.
    if (window.Dialog && typeof Dialog.prompt === 'function') {
      try {
        const v = await Dialog.prompt(question, { defaultValue: defaultDate, type: 'date' });
        return v == null ? null : String(v);
      } catch (e) { /* retombe sur prompt natif */ }
    }
    const v = window.prompt(question + '\n(format AAAA-MM-JJ, vide = retirer la relance)', defaultDate || '');
    return v == null ? null : v.trim();
  },

  _injectStyles() {
    if (document.getElementById('cr-styles')) return;
    const s = document.createElement('style');
    s.id = 'cr-styles';
    s.textContent = `
      .cr-header { display:flex; align-items:flex-start; justify-content:space-between; gap:24px; margin-bottom:18px; flex-wrap:wrap; }
      .cr-header-text { flex:1; min-width:0; }
      .cr-title { font-size:26px; font-weight:700; line-height:1.15; letter-spacing:-.01em; color:hsl(var(--text)); margin-top:6px; font-family: var(--font-display, inherit); }
      .cr-header-actions { display:flex; align-items:center; gap:12px; }
      .cr-icon-btn { width:32px; height:32px; border-radius:8px; background:hsl(var(--card)); border:1px solid hsl(var(--border)); color:hsl(var(--text-muted)); font-size:16px; line-height:1; display:inline-flex; align-items:center; justify-content:center; cursor:pointer; transition:all 140ms; }
      .cr-icon-btn:hover { color:hsl(var(--text)); border-color:hsl(var(--text-muted) / .5); }

      /* Bandeau à relancer */
      .cr-due-card { margin:0 0 18px; padding:14px 16px; border-radius:12px; background:hsl(var(--warning) / .1); border:1px solid hsl(var(--warning) / .35); }
      .cr-due-head { display:flex; align-items:center; gap:8px; flex-wrap:wrap; margin-bottom:10px; }
      .cr-due-bell { font-size:18px; }
      .cr-due-sub { font-size:12px; color:hsl(var(--text-muted)); }
      .cr-due-list { display:flex; flex-direction:column; gap:8px; }
      .cr-due-row { display:flex; align-items:center; justify-content:space-between; gap:12px; padding:10px 12px; border-radius:9px; background:hsl(var(--card)); border:1px solid hsl(var(--border)); cursor:pointer; transition:border-color 120ms; }
      .cr-due-row:hover { border-color:hsl(var(--accent) / .55); }
      .cr-due-row-main { min-width:0; flex:1; }
      .cr-due-row-name { font-weight:600; font-size:13.5px; color:hsl(var(--text)); }
      .cr-due-row-meta { display:flex; gap:10px; flex-wrap:wrap; font-size:11.5px; color:hsl(var(--text-muted)); margin-top:2px; }
      .cr-due-row-msg { font-size:11.5px; color:hsl(var(--text-muted)); margin-top:4px; font-style:italic; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
      .cr-due-row-actions { display:flex; gap:6px; flex-shrink:0; }
      .cr-overdue { color:hsl(var(--danger)); font-weight:600; }
      .cr-mini { padding:5px 11px !important; font-size:12px !important; }

      /* Filtres */
      .cr-filters { display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin-bottom:14px; }
      .cr-filters select { padding:9px 12px; border-radius:10px; background:hsl(var(--card)); color:hsl(var(--text)); border:1px solid hsl(var(--border)); font-size:13px; }
      .cr-filters select:focus { outline:none; border-color:hsl(var(--accent)); box-shadow:0 0 0 3px hsl(var(--accent) / .14); }

      /* Tableau */
      .cr-table-card { background:hsl(var(--card)); border:1px solid hsl(var(--border)); border-radius:12px; overflow:hidden; }
      .cr-table-scroll { overflow-x:auto; -webkit-overflow-scrolling:touch; }
      .cr-table { width:100%; min-width:680px; border-collapse:collapse; font-size:13px; }
      .cr-table th { text-align:left; font-size:11px; letter-spacing:.1em; text-transform:uppercase; font-weight:700; color:hsl(var(--text-muted)); padding:12px 14px; border-bottom:1px solid hsl(var(--border)); background:hsl(var(--bg) / .4); }
      .cr-table td { padding:12px 14px; border-bottom:1px solid hsl(var(--border) / .6); vertical-align:middle; }
      .cr-table tr:last-child td { border-bottom:none; }
      .cr-row { cursor:pointer; transition:background 100ms; }
      .cr-row:hover { background:hsl(var(--accent) / .05); }
      .cr-row:focus-visible { outline:2px solid hsl(var(--accent)); outline-offset:-2px; }
      .cr-cell-name { max-width:240px; }
      .cr-name { font-weight:600; color:hsl(var(--text)); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
      .cr-handle { font-size:11.5px; color:hsl(var(--text-muted)); }
      .cr-chan-label { font-size:12.5px; }
      .cr-date { font-size:12.5px; color:hsl(var(--text-secondary)); white-space:nowrap; }
      .cr-pill { display:inline-block; padding:3px 9px; border-radius:999px; font-size:11px; font-weight:600; }
      .cr-count { margin-top:12px; font-size:12px; color:hsl(var(--text-muted)); }
      .cr-empty { padding:48px 24px; text-align:center; background:hsl(var(--card)); border:1px dashed hsl(var(--border)); border-radius:14px; }

      /* Drawer */
      .cr-drawer { position:fixed; top:0; right:0; bottom:0; width:100%; max-width:520px; background:hsl(var(--card)); border-left:1px solid hsl(var(--border)); box-shadow:-10px 0 30px rgba(0,0,0,.15); z-index:80; overflow-y:auto; padding:22px 26px; transform:translateX(100%); transition:transform 200ms; }
      .cr-drawer.is-open { transform:translateX(0); }
      .cr-drawer-backdrop { position:fixed; inset:0; background:hsl(var(--bg) / .6); z-index:79; opacity:0; pointer-events:none; transition:opacity 160ms; }
      .cr-drawer-backdrop.is-open { opacity:1; pointer-events:auto; }
      .cr-stat { background:hsl(var(--bg)); border:1px solid hsl(var(--border)); border-radius:10px; padding:12px 14px; }
      .cr-stat .label { font-size:11px; letter-spacing:.1em; text-transform:uppercase; color:hsl(var(--text-muted)); font-weight:700; }
      .cr-stat .value { font-size:22px; font-weight:700; color:hsl(var(--text)); margin-top:4px; line-height:1; }
      .cr-stat-date { font-size:15px !important; }
      .cr-label { font-size:11px; letter-spacing:.08em; text-transform:uppercase; font-weight:700; color:hsl(var(--text-muted)); margin-bottom:6px; }
      .cr-hint { font-size:11px; color:hsl(var(--text-muted)); margin-top:4px; display:block; }
      .cr-input { width:100%; padding:9px 12px; border-radius:8px; background:hsl(var(--bg)); color:hsl(var(--text)); border:1px solid hsl(var(--border)); font-size:13.5px; font-family:inherit; }
      .cr-input:focus { outline:none; border-color:hsl(var(--accent)); box-shadow:0 0 0 3px hsl(var(--accent) / .14); }
      textarea.cr-input { resize:vertical; }
      .cr-input-sm { font-size:12.5px; padding:7px 10px; }
      .cr-edit { display:block; }

      /* Historique */
      .cr-history { margin-top:22px; padding-top:18px; border-top:1px solid hsl(var(--border)); }
      .cr-msgform { margin:8px 0 12px; padding:12px; border-radius:10px; background:hsl(var(--bg)); border:1px solid hsl(var(--border)); }
      .cr-msgform-row { display:flex; gap:8px; margin-top:8px; align-items:center; }
      .cr-msgform-row select { flex:1; }
      .cr-msglist { display:flex; flex-direction:column; gap:8px; margin-top:10px; }
      .cr-msg { padding:10px 12px; border-radius:9px; background:hsl(var(--bg)); border:1px solid hsl(var(--border) / .7); }
      .cr-msg-head { display:flex; align-items:center; justify-content:space-between; font-size:11.5px; color:hsl(var(--text-muted)); margin-bottom:5px; }
      .cr-msg-date { font-variant-numeric:tabular-nums; }
      .cr-msg-body { font-size:13px; color:hsl(var(--text)); white-space:pre-wrap; line-height:1.45; }

      @media (max-width:720px) {
        .cr-title { font-size:22px; }
        .cr-due-row { flex-direction:column; align-items:stretch; }
        .cr-due-row-actions { justify-content:flex-end; }
      }
    `;
    document.head.appendChild(s);
  },
};
