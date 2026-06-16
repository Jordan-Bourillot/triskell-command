/* Carnet des créateurs — vue claire en cartes.
   Liste (nom, statut, contact, démo, message, relance) + formulaire d'ajout/édition
   + encart « À relancer ». Données via App.api.creators_* (table contacted_creators,
   séparée des prospects). */
const Creators = {
  state: { rows: [], due: [], editing: null, q: '' },

  _api(method, payload) { return App.api['creators_' + method](payload || {}); },

  esc(t) { const d = document.createElement('div'); d.textContent = (t == null ? '' : String(t)); return d.innerHTML; },

  PLATFORMS: ['YouTube', 'Instagram', 'TikTok', 'Email', 'Facebook', 'Twitter/X', 'Autre'],

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
            <h1 style="font-size:24px;font-weight:700;margin:0;color:#1f2430">🎯 Créateurs</h1>
            <p style="font-size:13.5px;color:#8a8f9a;margin:5px 0 0">Ton carnet de prospection créateurs : la démo, le message prêt, et le suivi des relances.</p>
          </div>
          <button id="cr-add" style="background:#e11d6b;color:#fff;border:0;border-radius:10px;padding:10px 17px;font-size:14px;font-weight:600;cursor:pointer;white-space:nowrap">+ Ajouter un créateur</button>
        </div>
        <div id="cr-stats" style="display:flex;gap:10px;flex-wrap:wrap;margin:14px 0 2px"></div>
        <input id="cr-search" placeholder="🔎 Rechercher un créateur…" style="width:100%;border:1px solid #e2e2e6;border-radius:10px;padding:10px 13px;font-size:14px;margin:10px 0 18px;box-sizing:border-box">
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
    this.renderDue();
    this.renderGrid();
  },

  renderStats() {
    const host = document.getElementById('cr-stats');
    if (!host) return;
    const rows = this.state.rows;
    const contacted = rows.filter(c => c.contacted_at).length;
    const todo = rows.length - contacted;
    const due = this.state.due.length;
    const pill = (label, val, color) =>
      `<div style="background:#fff;border:1px solid #ececf0;border-radius:12px;padding:8px 15px"><span style="font-size:20px;font-weight:700;color:${color}">${val}</span> <span style="font-size:12.5px;color:#888">${label}</span></div>`;
    host.innerHTML =
      pill('créateurs', rows.length, '#1f2430') +
      pill('contactés', contacted, '#16a34a') +
      pill('à contacter', todo, '#d97706') +
      (due ? pill('à relancer', due, '#e11d6b') : '');
  },

  renderDue() {
    const host = document.getElementById('cr-due');
    if (!host) return;
    const due = this.state.due;
    if (!due.length) { host.innerHTML = ''; return; }
    host.innerHTML = `
      <div style="background:#fff4f8;border:1px solid #f4c4d8;border-radius:14px;padding:14px 16px;margin-bottom:18px">
        <div style="font-weight:700;color:#b81e5b;margin-bottom:8px">⏰ À relancer (${due.length})</div>
        ${due.map(c => `
          <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:7px 0;border-top:1px solid #f6dbe6">
            <b>${this.esc(c.name)}</b>
            <span style="font-size:12px;color:#888">${this.esc(c.platform || '')}</span>
            <span style="font-size:12px;color:#b81e5b">prévue le ${this.fmtDate(c.next_follow_up_at)}</span>
            <span style="flex:1"></span>
            <button data-act="done" data-id="${c.id}" style="font-size:12.5px;border:1px solid #cbd5e1;background:#fff;border-radius:8px;padding:5px 10px;cursor:pointer">Relancé ✓</button>
            <button data-act="snooze" data-id="${c.id}" style="font-size:12.5px;border:1px solid #cbd5e1;background:#fff;border-radius:8px;padding:5px 10px;cursor:pointer">+7 j</button>
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
      host.innerHTML = `<div style="text-align:center;color:#999;padding:50px 20px;border:1px dashed #ddd;border-radius:14px">
        Ton carnet est vide. Clique « + Ajouter un créateur » pour noter ton premier contact.</div>`;
      return;
    }
    let rows = this.state.rows;
    if (this.state.q) rows = rows.filter(c =>
      (c.name || '').toLowerCase().includes(this.state.q) || (c.notes || '').toLowerCase().includes(this.state.q));
    if (!rows.length) {
      host.innerHTML = `<div style="text-align:center;color:#999;padding:30px">Aucun créateur ne correspond à ta recherche.</div>`;
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
  },

  card(c) {
    const contacted = !!c.contacted_at;
    const bar = contacted ? '#16a34a' : '#d97706';
    const statut = contacted
      ? `<span style="background:#dcfce7;color:#15803d;font-size:11.5px;font-weight:600;padding:3px 9px;border-radius:999px">✅ Contacté le ${this.fmtDate(c.contacted_at)}</span>`
      : `<span style="background:#fef3c7;color:#b45309;font-size:11.5px;font-weight:600;padding:3px 9px;border-radius:999px">🟡 À contacter</span>`;
    const contact = c.handle
      ? (this.isEmail(c.handle)
        ? `<a href="mailto:${this.esc(c.handle)}" style="color:#e11d6b;text-decoration:none;font-weight:600">✉️ ${this.esc(c.handle)}</a>`
        : `<a href="${this.esc(c.handle)}" target="_blank" rel="noopener" style="color:#3b6cb7;text-decoration:none">${this.esc(c.platform || 'Lien')} ↗</a>`)
      : `<span style="color:#aaa">pas de contact noté</span>`;
    const relance = c.next_follow_up_at
      ? `<div style="font-size:12px;color:${this.isOverdue(c.next_follow_up_at) ? '#e11d6b' : '#888'};margin-top:6px">⏰ Relance le ${this.fmtDate(c.next_follow_up_at)}</div>` : '';
    const demo = c.demo_url
      ? `<a href="${this.esc(c.demo_url)}" target="_blank" rel="noopener" style="flex:1;text-align:center;background:#1f2430;color:#fff;text-decoration:none;font-size:13px;font-weight:600;padding:8px;border-radius:9px">▶ Démo</a>` : '';
    const copy = c.message
      ? `<button data-copy="${c.id}" style="flex:1;background:#fce7f0;color:#b81e5b;border:0;font-size:13px;font-weight:600;padding:8px;border-radius:9px;cursor:pointer">📋 Copier le message</button>` : '';
    return `
      <div style="background:#fff;border:1px solid #ececf0;border-radius:14px;overflow:hidden;display:flex;flex-direction:column;box-shadow:0 3px 12px rgba(0,0,0,.04)">
        <div style="height:4px;background:${bar}"></div>
        <div style="padding:15px 16px 15px;display:flex;flex-direction:column;gap:7px;flex:1">
          <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:8px">
            <div style="font-size:16.5px;font-weight:700;color:#1f2430;line-height:1.25">${this.esc(c.name)}</div>
            <button data-del="${c.id}" title="Supprimer" style="border:0;background:none;cursor:pointer;font-size:15px;color:#c9ccd2">🗑</button>
          </div>
          <div>${statut}</div>
          <div style="font-size:13px;word-break:break-word">${contact}</div>
          ${c.notes ? `<div style="font-size:12.5px;color:#777;line-height:1.5">${this.esc((c.notes || '').slice(0, 160))}${(c.notes || '').length > 160 ? '…' : ''}</div>` : ''}
          ${relance}
          <div style="flex:1"></div>
          <div style="display:flex;gap:8px;margin-top:10px">${demo}${copy}</div>
          <button data-edit="${c.id}" style="background:none;border:1px solid #e2e2e6;color:#555;font-size:12.5px;padding:7px;border-radius:9px;cursor:pointer;margin-top:2px">✎ Éditer / noter le contact</button>
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
    const fld = 'width:100%;border:1px solid #d6d6da;border-radius:9px;padding:9px 11px;font-size:14px;margin-top:4px;box-sizing:border-box';
    const lbl = 'font-size:12.5px;color:#666;font-weight:600';
    host.innerHTML = `
      <div style="background:#fff;border:1px solid #e6e6e8;border-radius:14px;padding:20px;margin-bottom:20px;box-shadow:0 8px 24px rgba(0,0,0,.06)">
        <div style="font-weight:700;margin-bottom:14px;font-size:15px">${c ? 'Modifier' : 'Ajouter'} un créateur</div>
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
        <div id="f-err" style="color:#e11d6b;font-size:13px;margin-top:10px;display:none"></div>
        <div style="display:flex;gap:10px;margin-top:16px;justify-content:flex-end">
          <button id="f-cancel" style="border:1px solid #d6d6da;background:#fff;border-radius:9px;padding:9px 16px;font-size:14px;cursor:pointer">Annuler</button>
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
