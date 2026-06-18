/* Carnet des créateurs — vue en cartes, avec familles (vierge / physique /
   services-digital / marque) lues depuis le tag en tête des notes (🟢🔵🟠⚫).
   Filtres par famille + statut + démo + message. Données via App.api.creators_*.
   Couleurs : jetons de thème uniquement (lisible en clair / mid / sombre). */
const Creators = {
  state: { rows: [], due: [], editing: null, q: '', fam: '', plat: '' },

  _api(method, payload) { return App.api['creators_' + method](payload || {}); },

  esc(t) { const d = document.createElement('div'); d.textContent = (t == null ? '' : String(t)); return d.innerHTML; },

  PLATFORMS: ['YouTube', 'Instagram', 'TikTok', 'Email', 'Facebook', 'Twitter/X', 'Autre'],

  FAMILIES: {
    vierge:   { e: '🟢', label: 'Vierge',             color: '#16a34a' },
    physique: { e: '🔵', label: 'Produits physiques', color: '#2563eb' },
    digital:  { e: '🟠', label: 'Services / digital',  color: '#d97706' },
    marque:   { e: '⚫', label: 'Marque / hors-cible',  color: '#6b7280' },
  },

  famKey(c) {
    const n = (c.notes || '').slice(0, 6);
    if (n.includes('🟢')) return 'vierge';
    if (n.includes('🔵')) return 'physique';
    if (n.includes('🟠')) return 'digital';
    if (n.includes('⚫')) return 'marque';
    return '';
  },

  PLAT: {
    youtube:   { e: '▶️', label: 'YouTube',   color: '#ef4444' },
    tiktok:    { e: '🎵', label: 'TikTok',    color: '#0ea5b7' },
    instagram: { e: '📸', label: 'Instagram', color: '#d6249f' },
  },

  // Plateforme réelle du créateur. Le champ "platform" a parfois servi à noter
  // le canal de contact (ex "Email") sur les anciens → on recoupe lien + notes.
  platKey(c) {
    const h = (c.handle || '').toLowerCase(), p = (c.platform || '').toLowerCase(),
          n = (c.notes || '').toLowerCase(), m = (c.message || '').toLowerCase();
    if (p === 'tiktok' || h.includes('tiktok.com') || n.includes('cible tiktok')) return 'tiktok';
    if (h.includes('youtube.com') || n.includes('youtube') || n.includes('chaîne') || n.includes('chaine') || m.includes('youtubeur')) return 'youtube';
    if (p === 'instagram' || h.includes('instagram')) return 'instagram';
    return 'youtube';
  },

  fmtDate(v) {
    if (!v) return '';
    const s = String(v).slice(0, 10);
    const p = s.split('-');
    return p.length === 3 ? `${p[2]}/${p[1]}/${p[0]}` : s;
  },
  isOverdue(v) { if (!v) return false; return new Date(v).getTime() <= Date.now(); },
  isEmail(s) { return /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test((s || '').trim()); },

  async render(container) {
    container.innerHTML = `
      <section style="max-width:1080px;margin:22px auto;padding:0 18px">
        <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:4px">
          <div>
            <h1 style="font-size:24px;font-weight:700;margin:0;color:hsl(var(--text))">🎯 Créateurs</h1>
            <p style="font-size:13.5px;color:hsl(var(--text-muted));margin:5px 0 0">Ton carnet de prospection : famille, démo, message prêt, suivi des relances.</p>
          </div>
          <button id="cr-add" style="background:#e11d6b;color:#fff;border:0;border-radius:10px;padding:10px 17px;font-size:14px;font-weight:600;cursor:pointer;white-space:nowrap">+ Ajouter un créateur</button>
        </div>
        <div id="cr-stats" style="display:flex;gap:10px;flex-wrap:wrap;margin:14px 0 2px"></div>
        <input id="cr-search" placeholder="🔎 Rechercher un créateur…" style="width:100%;border:1px solid hsl(var(--border-strong));border-radius:10px;padding:10px 13px;font-size:14px;margin:10px 0 12px;box-sizing:border-box;background:hsl(var(--surface));color:hsl(var(--text));-webkit-text-fill-color:hsl(var(--text))">
        <div id="cr-filters" style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:18px"></div>
        <div id="cr-due"></div>
        <div id="cr-form-host"></div>
        <div id="cr-grid"></div>
      </section>`;
    container.querySelector('#cr-add').addEventListener('click', () => this.openForm(null));
    const s = container.querySelector('#cr-search');
    s.addEventListener('input', () => { this.state.q = s.value.toLowerCase(); this.renderGrid(); });
    await this.refresh();
  },

  async refresh() {
    const [all, due] = await Promise.all([this._api('list', {}), this._api('list', { relance: true })]);
    this.state.rows = (all && all.rows) || [];
    this.state.due = (due && due.rows) || [];
    this.renderStats();
    this.renderFilters();
    this.renderDue();
    this.renderGrid();
  },

  renderStats() {
    const host = document.getElementById('cr-stats');
    if (!host) return;
    const rows = this.state.rows;
    const contacted = rows.filter(c => c.contacted_at).length;
    const due = this.state.due.length;
    const pill = (label, val, color) =>
      `<div style="background:hsl(var(--surface-elevated));border:1px solid hsl(var(--border));border-radius:12px;padding:8px 15px"><span style="font-size:20px;font-weight:700;color:${color}">${val}</span> <span style="font-size:12.5px;color:hsl(var(--text-muted))">${label}</span></div>`;
    host.innerHTML =
      pill('créateurs', rows.length, 'hsl(var(--text))') +
      pill('contactés', contacted, 'hsl(var(--success-text))') +
      pill('à contacter', rows.length - contacted, 'hsl(var(--warning-text))') +
      (due ? pill('à relancer', due, 'hsl(var(--danger-text))') : '');
  },

  renderFilters() {
    const host = document.getElementById('cr-filters');
    if (!host) return;
    const rows = this.state.rows;
    const mkChip = (attr, k, label, active, color, emoji, n) =>
      `<button data-${attr}="${k}" style="border:1px solid ${active ? color : 'hsl(var(--border-strong))'};background:${active ? color : 'hsl(var(--surface))'};color:${active ? '#fff' : 'hsl(var(--text-secondary))'};border-radius:999px;padding:6px 13px;font-size:13px;font-weight:600;cursor:pointer">${emoji ? emoji + ' ' : ''}${label} (${n})</button>`;
    const pc = k => k === '' ? rows.length : rows.filter(c => this.platKey(c) === k).length;
    const platChip = (k, label) => { const pf = this.PLAT[k]; return mkChip('plat', k, label, this.state.plat === k, pf ? pf.color : 'hsl(var(--accent-strong))', pf ? pf.e : '', pc(k)); };
    const fc = k => k === '' ? rows.length : rows.filter(c => this.famKey(c) === k).length;
    const famChip = (k, label) => { const f = this.FAMILIES[k]; return mkChip('fam', k, label, this.state.fam === k, f ? f.color : 'hsl(var(--accent-strong))', f ? f.e : '', fc(k)); };
    const rowS = 'display:flex;gap:8px;flex-wrap:wrap;align-items:center';
    const lblS = 'font-size:11px;letter-spacing:.3px;text-transform:uppercase;color:hsl(var(--text-muted));font-weight:700;margin-right:2px;min-width:74px';
    host.style.flexDirection = 'column';
    host.style.alignItems = 'stretch';
    host.innerHTML =
      `<div style="${rowS};margin-bottom:9px"><span style="${lblS}">Plateforme</span>`
        + platChip('', 'Toutes') + platChip('youtube', 'YouTube') + platChip('tiktok', 'TikTok') + platChip('instagram', 'Instagram')
      + `</div>`
      + `<div style="${rowS}"><span style="${lblS}">Famille</span>`
        + famChip('', 'Tous') + famChip('vierge', 'Vierges') + famChip('physique', 'Physiques') + famChip('digital', 'Services') + (fc('marque') ? famChip('marque', 'Marques') : '')
      + `</div>`;
    host.querySelectorAll('[data-plat]').forEach(b => b.addEventListener('click', () => {
      this.state.plat = b.getAttribute('data-plat'); this.renderFilters(); this.renderGrid();
    }));
    host.querySelectorAll('[data-fam]').forEach(b => b.addEventListener('click', () => {
      this.state.fam = b.getAttribute('data-fam'); this.renderFilters(); this.renderGrid();
    }));
  },

  renderDue() {
    const host = document.getElementById('cr-due');
    if (!host) return;
    const due = this.state.due;
    if (!due.length) { host.innerHTML = ''; return; }
    host.innerHTML = `
      <div style="background:hsl(var(--danger) / 0.10);border:1px solid hsl(var(--danger) / 0.30);border-radius:14px;padding:14px 16px;margin-bottom:18px">
        <div style="font-weight:700;color:hsl(var(--danger-text));margin-bottom:8px">⏰ À relancer (${due.length})</div>
        ${due.map(c => `
          <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:7px 0;border-top:1px solid hsl(var(--border))">
            <b>${this.esc(c.name)}</b>
            <span style="font-size:12px;color:hsl(var(--text-muted))">${this.esc(c.platform || '')}</span>
            <span style="font-size:12px;color:hsl(var(--danger-text))">prévue le ${this.fmtDate(c.next_follow_up_at)}</span>
            <span style="flex:1"></span>
            <button data-act="done" data-id="${c.id}" style="font-size:12.5px;border:1px solid hsl(var(--border-strong));background:hsl(var(--surface));color:hsl(var(--text));border-radius:8px;padding:5px 10px;cursor:pointer">Relancé ✓</button>
            <button data-act="snooze" data-id="${c.id}" style="font-size:12.5px;border:1px solid hsl(var(--border-strong));background:hsl(var(--surface));color:hsl(var(--text));border-radius:8px;padding:5px 10px;cursor:pointer">+7 j</button>
          </div>`).join('')}
      </div>`;
    host.querySelectorAll('button[data-act]').forEach(b => b.addEventListener('click', () => {
      const id = b.getAttribute('data-id'); const act = b.getAttribute('data-act');
      if (act === 'done') this.saveQuick(id, { next_follow_up_at: '' });
      else { const d = new Date(Date.now() + 7 * 864e5); this.saveQuick(id, { next_follow_up_at: d.toISOString().slice(0, 10) }); }
    }));
  },

  renderGrid() {
    const host = document.getElementById('cr-grid');
    if (!host) return;
    if (!this.state.rows.length) {
      host.innerHTML = `<div style="text-align:center;color:hsl(var(--text-muted));padding:50px 20px;border:1px dashed hsl(var(--border));border-radius:14px">
        Ton carnet est vide. Clique « + Ajouter un créateur » pour noter ton premier contact.</div>`;
      return;
    }
    let rows = this.state.rows;
    if (this.state.plat) rows = rows.filter(c => this.platKey(c) === this.state.plat);
    if (this.state.fam) rows = rows.filter(c => this.famKey(c) === this.state.fam);
    if (this.state.q) rows = rows.filter(c =>
      (c.name || '').toLowerCase().includes(this.state.q) || (c.notes || '').toLowerCase().includes(this.state.q));
    if (!rows.length) {
      host.innerHTML = `<div style="text-align:center;color:hsl(var(--text-muted));padding:30px">Aucun créateur ne correspond à ce filtre.</div>`;
      return;
    }
    host.innerHTML = `<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:16px">${rows.map(c => this.card(c)).join('')}</div>`;
    host.querySelectorAll('[data-edit]').forEach(b => b.addEventListener('click', () => {
      const c = this.state.rows.find(x => x.id === b.getAttribute('data-edit')); if (c) this.openForm(c);
    }));
    host.querySelectorAll('[data-del]').forEach(b => b.addEventListener('click', async () => {
      if (!confirm('Supprimer ce créateur du carnet ?')) return;
      await this._api('delete', { id: b.getAttribute('data-del') });
      this.refresh();
    }));
    host.querySelectorAll('[data-copy]').forEach(b => b.addEventListener('click', () => {
      const c = this.state.rows.find(x => x.id === b.getAttribute('data-copy')); if (c) this.copyMsg(c.message, b);
    }));
    host.querySelectorAll('[data-queue]').forEach(b => b.addEventListener('click', async () => {
      const id = b.getAttribute('data-queue');
      const old = b.textContent; b.disabled = true; b.textContent = '⏳ Mise en file…';
      const res = await this._api('queue_draft', { id });
      if (res && res.ok && res.count) { b.textContent = '✓ Dans « Brouillons à valider »'; }
      else { b.textContent = old; b.disabled = false; alert((res && res.error) || 'Échec — adresse e-mail ou message manquant.'); }
    }));
  },

  card(c) {
    const contacted = !!c.contacted_at;
    const bar = contacted ? '#16a34a' : '#d97706';
    const fk = this.famKey(c);
    const fam = this.FAMILIES[fk];
    const pf = this.PLAT[this.platKey(c)];
    const platBadge = pf ? `<span style="background:${pf.color}1a;color:${pf.color};font-size:11px;font-weight:700;padding:2px 9px;border-radius:6px;white-space:nowrap">${pf.e} ${pf.label}</span>` : '';
    const famBadge = fam
      ? `<span style="background:${fam.color}1a;color:${fam.color};font-size:11px;font-weight:700;padding:2px 9px;border-radius:6px;white-space:nowrap">${fam.e} ${fam.label}</span>`
      : `<span style="background:hsl(var(--surface));color:hsl(var(--text-muted));font-size:11px;font-weight:600;padding:2px 9px;border-radius:6px">à classer</span>`;
    const statut = contacted
      ? `<span style="background:hsl(var(--success) / 0.15);color:hsl(var(--success-text));font-size:11.5px;font-weight:600;padding:3px 9px;border-radius:999px">✅ Contacté le ${this.fmtDate(c.contacted_at)}</span>`
      : `<span style="background:hsl(var(--warning) / 0.15);color:hsl(var(--warning-text));font-size:11.5px;font-weight:600;padding:3px 9px;border-radius:999px">🟡 À contacter</span>`;
    const contact = c.handle
      ? (this.isEmail(c.handle)
        ? `<a href="mailto:${this.esc(c.handle)}" style="color:hsl(var(--accent-text));text-decoration:none;font-weight:600">✉️ ${this.esc(c.handle)}</a>`
        : `<a href="${this.esc(c.handle)}" target="_blank" rel="noopener" style="color:hsl(var(--info-text));text-decoration:none">${this.esc(c.platform || 'Lien')} ↗</a>`)
      : `<span style="color:hsl(var(--text-muted))">pas de contact noté</span>`;
    const relance = c.next_follow_up_at
      ? `<div style="font-size:12px;color:${this.isOverdue(c.next_follow_up_at) ? 'hsl(var(--danger-text))' : 'hsl(var(--text-muted))'};margin-top:6px">⏰ Relance le ${this.fmtDate(c.next_follow_up_at)}</div>` : '';
    const demo = c.demo_url
      ? `<a href="${this.esc(c.demo_url)}" target="_blank" rel="noopener" style="flex:1;text-align:center;background:hsl(var(--accent-strong));color:#fff;text-decoration:none;font-size:13px;font-weight:600;padding:8px;border-radius:9px">▶ Démo</a>` : '';
    const copy = c.message
      ? `<button data-copy="${c.id}" style="flex:1;background:hsl(var(--danger) / 0.15);color:hsl(var(--danger-text));border:0;font-size:13px;font-weight:600;padding:8px;border-radius:9px;cursor:pointer">📋 Copier le message</button>` : '';
    const hasMail = this.isEmail(c.handle) || /[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}/.test(c.notes || '');
    const draft = (c.message && hasMail && !contacted)
      ? `<button data-queue="${c.id}" style="flex:1;background:hsl(var(--info) / 0.15);color:hsl(var(--info-text));border:0;font-size:13px;font-weight:600;padding:8px;border-radius:9px;cursor:pointer">📥 Mettre dans les brouillons</button>` : '';
    return `
      <div style="background:hsl(var(--surface-elevated));border:1px solid hsl(var(--border));border-radius:14px;overflow:hidden;display:flex;flex-direction:column;box-shadow:0 3px 12px rgba(0,0,0,.18)">
        <div style="height:4px;background:${bar}"></div>
        <div style="padding:14px 16px 15px;display:flex;flex-direction:column;gap:7px;flex:1">
          <div style="display:flex;align-items:center;justify-content:space-between;gap:8px">
            <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center">${platBadge}${famBadge}</div>
            <button data-del="${c.id}" title="Supprimer" style="border:0;background:none;cursor:pointer;font-size:15px;color:hsl(var(--text-muted))">🗑</button>
          </div>
          <div style="font-size:16.5px;font-weight:700;color:hsl(var(--text));line-height:1.25">${this.esc(c.name)}</div>
          <div>${statut}</div>
          <div style="font-size:13px;word-break:break-word">${contact}</div>
          ${c.notes ? `<div style="font-size:12.5px;color:hsl(var(--text-secondary));line-height:1.5">${this.esc((c.notes || '').slice(0, 170))}${(c.notes || '').length > 170 ? '…' : ''}</div>` : ''}
          ${relance}
          <div style="flex:1"></div>
          <div style="display:flex;gap:8px;margin-top:10px">${demo}${copy}</div>
          ${draft ? `<div style="display:flex;margin-top:8px">${draft}</div>` : ''}
          <button data-edit="${c.id}" style="background:none;border:1px solid hsl(var(--border-strong));color:hsl(var(--text-secondary));font-size:12.5px;padding:7px;border-radius:9px;cursor:pointer;margin-top:2px">✎ Éditer / noter le contact</button>
        </div>
      </div>`;
  },

  copyMsg(text, btn) {
    const done = () => { const old = btn.textContent; btn.textContent = '✓ Copié !'; setTimeout(() => { btn.textContent = old; }, 1800); };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text || '').then(done).catch(() => alert('Copie impossible — ouvre la fiche pour copier le message à la main.'));
    } else {
      alert('Copie impossible ici — ouvre la fiche pour copier le message.');
    }
  },

  openForm(c) {
    this.state.editing = c;
    const host = document.getElementById('cr-form-host');
    const v = c || {};
    const opts = this.PLATFORMS.map(p => `<option ${(v.platform || '') === p ? 'selected' : ''}>${p}</option>`).join('');
    const fld = 'width:100%;border:1px solid hsl(var(--border-strong));border-radius:9px;padding:9px 11px;font-size:14px;margin-top:4px;box-sizing:border-box;background:hsl(var(--surface));color:hsl(var(--text));-webkit-text-fill-color:hsl(var(--text))';
    const lbl = 'font-size:12.5px;color:hsl(var(--text-secondary));font-weight:600';
    host.innerHTML = `
      <div style="background:hsl(var(--surface-elevated));border:1px solid hsl(var(--border));border-radius:14px;padding:20px;margin-bottom:20px;color:hsl(var(--text));box-shadow:0 8px 24px rgba(0,0,0,.22)">
        <div style="font-weight:700;margin-bottom:6px;font-size:15px">${c ? 'Modifier' : 'Ajouter'} un créateur</div>
        <div style="font-size:12px;color:hsl(var(--text-muted));margin-bottom:14px">Astuce : commence les notes par 🟢 (vierge), 🔵 (produits physiques), 🟠 (services/digital) ou ⚫ (marque) pour le ranger en famille.</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
          <div><label style="${lbl}">Nom du créateur *</label><input id="f-name" style="${fld}" value="${this.esc(v.name)}"></div>
          <div><label style="${lbl}">Réseau</label><select id="f-platform" style="${fld}">${opts}</select></div>
          <div><label style="${lbl}">Contact (email ou lien)</label><input id="f-handle" style="${fld}" value="${this.esc(v.handle)}" placeholder="email@… ou https://…"></div>
          <div><label style="${lbl}">Lien de la démo</label><input id="f-demo" style="${fld}" value="${this.esc(v.demo_url)}" placeholder="https://…"></div>
          <div style="grid-column:1/3"><label style="${lbl}">Message (prêt à envoyer)</label><textarea id="f-message" rows="4" style="${fld};resize:vertical">${this.esc(v.message)}</textarea></div>
          <div><label style="${lbl}">Contacté le</label><input id="f-contacted" type="date" style="${fld}" value="${(v.contacted_at || '').slice(0, 10)}"></div>
          <div><label style="${lbl}">À relancer le</label><input id="f-followup" type="date" style="${fld}" value="${(v.next_follow_up_at || '').slice(0, 10)}"></div>
          <div style="grid-column:1/3"><label style="${lbl}">Notes</label><textarea id="f-notes" rows="2" style="${fld};resize:vertical">${this.esc(v.notes)}</textarea></div>
        </div>
        <div id="f-err" style="color:hsl(var(--danger-text));font-size:13px;margin-top:10px;display:none"></div>
        <div style="display:flex;gap:10px;margin-top:16px;justify-content:flex-end">
          <button id="f-cancel" style="border:1px solid hsl(var(--border-strong));background:hsl(var(--surface));color:hsl(var(--text));border-radius:9px;padding:9px 16px;font-size:14px;cursor:pointer">Annuler</button>
          <button id="f-save" style="background:#e11d6b;color:#fff;border:0;border-radius:9px;padding:9px 18px;font-size:14px;font-weight:600;cursor:pointer">Enregistrer</button>
        </div>
      </div>`;
    host.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    host.querySelector('#f-cancel').addEventListener('click', () => { host.innerHTML = ''; this.state.editing = null; });
    host.querySelector('#f-save').addEventListener('click', () => this.submit());
  },

  async submit() {
    const g = id => { const el = document.getElementById(id); return el ? el.value.trim() : ''; };
    const payload = {
      name: g('f-name'), platform: g('f-platform'), handle: g('f-handle'),
      contacted_at: g('f-contacted'), message: g('f-message'),
      next_follow_up_at: g('f-followup'), demo_url: g('f-demo'), notes: g('f-notes'),
    };
    if (this.state.editing) payload.id = this.state.editing.id;
    if (!payload.name) { return this.formErr('Le nom est obligatoire.'); }
    const res = await this._api('save', payload);
    if (!res || res.ok === false) { return this.formErr((res && res.error) || 'Échec de l’enregistrement.'); }
    document.getElementById('cr-form-host').innerHTML = '';
    this.state.editing = null;
    this.refresh();
  },

  formErr(msg) {
    const e = document.getElementById('f-err');
    if (e) { e.textContent = msg; e.style.display = 'block'; }
  },

  async saveQuick(id, fields) {
    await this._api('save', Object.assign({ id }, fields));
    this.refresh();
  },
};
