/* Carnet des créateurs contactés — vue simple.
   Liste (Créateur · Réseau · Contacté le · Message · À relancer le), un
   formulaire d'ajout/édition, et un encart « À relancer ». Données via
   App.api.creators_* (table dédiée contacted_creators, séparée des prospects). */
const Creators = {
  state: { rows: [], due: [], editing: null },

  _api(method, payload) { return App.api['creators_' + method](payload || {}); },

  esc(t) { const d = document.createElement('div'); d.textContent = (t == null ? '' : String(t)); return d.innerHTML; },

  PLATFORMS: ['Instagram', 'TikTok', 'YouTube', 'Facebook', 'Autre'],

  fmtDate(v) {
    if (!v) return '';
    const s = String(v).slice(0, 10);
    const p = s.split('-');
    return p.length === 3 ? `${p[2]}/${p[1]}/${p[0]}` : s;
  },
  isOverdue(v) { if (!v) return false; return new Date(v).getTime() <= Date.now(); },

  async render(container) {
    container.innerHTML = `
      <section style="max-width:960px;margin:0 auto;padding:24px 20px">
        <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:4px">
          <h1 style="font-size:22px;font-weight:600">Créateurs contactés</h1>
          <button id="cr-add" style="background:#e11d6b;color:#fff;border:0;border-radius:10px;padding:9px 16px;font-size:14px;font-weight:600;cursor:pointer">+ Ajouter un créateur</button>
        </div>
        <p style="font-size:13.5px;color:#888;margin-bottom:20px">Ton carnet : les créateurs que tu as contactés (hors mail), et quand les relancer.</p>
        <div id="cr-due"></div>
        <div id="cr-form-host"></div>
        <div id="cr-list"></div>
      </section>`;
    container.querySelector('#cr-add').addEventListener('click', () => this.openForm(null));
    await this.refresh();
  },

  async refresh() {
    const [all, due] = await Promise.all([this._api('list', {}), this._api('list', { relance: true })]);
    this.state.rows = (all && all.rows) || [];
    this.state.due = (due && due.rows) || [];
    this.renderDue();
    this.renderList();
  },

  renderDue() {
    const host = document.getElementById('cr-due');
    if (!host) return;
    const due = this.state.due;
    if (!due.length) { host.innerHTML = ''; return; }
    host.innerHTML = `
      <div style="background:#fff4f8;border:1px solid #f4c4d8;border-radius:14px;padding:14px 16px;margin-bottom:20px">
        <div style="font-weight:600;color:#b81e5b;margin-bottom:10px">⏰ À relancer (${due.length})</div>
        ${due.map(c => `
          <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:8px 0;border-top:1px solid #f6dbe6">
            <b>${this.esc(c.name)}</b>
            <span style="font-size:12px;color:#888">${this.esc(c.platform || '')}</span>
            <span style="font-size:12px;color:#b81e5b">relance prévue le ${this.fmtDate(c.next_follow_up_at)}</span>
            <span style="flex:1"></span>
            <button data-act="done" data-id="${c.id}" style="font-size:12.5px;border:1px solid #cbd5e1;background:#fff;border-radius:8px;padding:5px 10px;cursor:pointer">Relancé (enlever)</button>
            <button data-act="snooze" data-id="${c.id}" style="font-size:12.5px;border:1px solid #cbd5e1;background:#fff;border-radius:8px;padding:5px 10px;cursor:pointer">Reporter +7j</button>
          </div>`).join('')}
      </div>`;
    host.querySelectorAll('button[data-act]').forEach(b => b.addEventListener('click', () => {
      const id = b.getAttribute('data-id'); const act = b.getAttribute('data-act');
      if (act === 'done') this.saveQuick(id, { next_follow_up_at: '' });
      else { const d = new Date(Date.now() + 7 * 864e5); this.saveQuick(id, { next_follow_up_at: d.toISOString().slice(0, 10) }); }
    }));
  },

  renderList() {
    const host = document.getElementById('cr-list');
    if (!host) return;
    const rows = this.state.rows;
    if (!rows.length) {
      host.innerHTML = `<div style="text-align:center;color:#999;padding:50px 20px;border:1px dashed #ddd;border-radius:14px">
        Ton carnet est vide. Clique « + Ajouter un créateur » pour noter ton premier contact.</div>`;
      return;
    }
    host.innerHTML = `
      <table style="width:100%;border-collapse:collapse;font-size:14px">
        <thead><tr style="text-align:left;color:#888;font-size:12px;text-transform:uppercase;letter-spacing:.04em">
          <th style="padding:8px 10px">Créateur</th><th style="padding:8px 10px">Réseau</th>
          <th style="padding:8px 10px">Contacté le</th><th style="padding:8px 10px">Message</th>
          <th style="padding:8px 10px">À relancer le</th><th></th></tr></thead>
        <tbody>
        ${rows.map(c => `
          <tr data-id="${c.id}" style="border-top:1px solid #eee;cursor:pointer">
            <td style="padding:10px"><b>${this.esc(c.name)}</b>${c.handle ? `<div style="font-size:12px;color:#999">${this.esc(c.handle)}</div>` : ''}</td>
            <td style="padding:10px">${this.esc(c.platform || '')}</td>
            <td style="padding:10px;white-space:nowrap">${this.fmtDate(c.contacted_at)}</td>
            <td style="padding:10px;max-width:280px;color:#666">${this.esc((c.message || '').slice(0, 90))}${(c.message || '').length > 90 ? '…' : ''}</td>
            <td style="padding:10px;white-space:nowrap;${this.isOverdue(c.next_follow_up_at) ? 'color:#e11d6b;font-weight:600' : ''}">${this.fmtDate(c.next_follow_up_at) || '—'}</td>
            <td style="padding:10px;text-align:right"><button data-del="${c.id}" title="Supprimer" style="border:0;background:none;color:#bbb;cursor:pointer;font-size:16px">🗑</button></td>
          </tr>`).join('')}
        </tbody>
      </table>`;
    host.querySelectorAll('tr[data-id]').forEach(tr => tr.addEventListener('click', e => {
      if (e.target.closest('button[data-del]')) return;
      const c = rows.find(x => x.id === tr.getAttribute('data-id'));
      if (c) this.openForm(c);
    }));
    host.querySelectorAll('button[data-del]').forEach(b => b.addEventListener('click', async e => {
      e.stopPropagation();
      if (!confirm('Supprimer ce créateur du carnet ?')) return;
      await this._api('delete', { id: b.getAttribute('data-del') });
      this.refresh();
    }));
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
        <div style="font-weight:600;margin-bottom:14px">${c ? 'Modifier' : 'Ajouter'} un créateur</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
          <div><label style="${lbl}">Nom du créateur *</label><input id="f-name" style="${fld}" value="${this.esc(v.name)}"></div>
          <div><label style="${lbl}">Réseau</label><select id="f-platform" style="${fld}">${opts}</select></div>
          <div><label style="${lbl}">Pseudo / lien</label><input id="f-handle" style="${fld}" value="${this.esc(v.handle)}" placeholder="@pseudo"></div>
          <div><label style="${lbl}">Contacté le</label><input id="f-contacted" type="date" style="${fld}" value="${(v.contacted_at || '').slice(0, 10)}"></div>
          <div style="grid-column:1/3"><label style="${lbl}">Message envoyé</label><textarea id="f-message" rows="3" style="${fld};resize:vertical">${this.esc(v.message)}</textarea></div>
          <div><label style="${lbl}">À relancer le</label><input id="f-followup" type="date" style="${fld}" value="${(v.next_follow_up_at || '').slice(0, 10)}"></div>
          <div><label style="${lbl}">Lien de la démo</label><input id="f-demo" style="${fld}" value="${this.esc(v.demo_url)}" placeholder="https://…"></div>
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
    if (!res || res.ok === false) { return this.formErr((res && res.error) || 'Échec de l\'enregistrement.'); }
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
