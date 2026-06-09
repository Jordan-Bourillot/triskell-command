/* Vue Conversions — funnel par segment / période */

const Funnel = {
  period: '30d',
  segment: 'all',
  PERIODS: { '7d': '7 jours', '30d': '30 jours', '90d': '90 jours', 'all': 'Tout' },
  SEGMENTS: { 'all': 'Tous', 'creators': 'Créateurs', 'b2b_local': 'B2B local' },
  STAGES: [
    { key: 'prospects',  label: 'Prospects' },
    { key: 'sent',       label: 'Envoyés' },
    { key: 'replies',    label: 'Réponses' },
    { key: 'interested', label: 'Intéressés' },
    { key: 'won',        label: 'Gagnés' },
  ],

  async render(container) {
    container.innerHTML = `
      <section class="animate-slide-up">
        <div class="mb-6 sm:mb-8">
          <div class="flex items-start justify-between gap-3">
            <div class="min-w-0 flex-1">
              <div class="hero-kicker mb-2">CONVERSIONS</div>
              <h1 class="hero-title hero-title--md mb-2 sm:mb-3">Tes taux de transformation.</h1>
              <p class="hero-subtitle">Tu vois en un coup d'œil ce qui marche et ce qui coince.</p>
            </div>
            ${Help.button('funnel')}
          </div>
        </div>

        <div id="f-filters" class="space-y-3 sm:space-y-4 mb-6 sm:mb-10"></div>
        <div id="f-content"></div>
      </section>
    `;
    this._renderFilters();
    await this.refresh();
  },

  _renderFilters() {
    const wrap = document.getElementById('f-filters');
    if (!wrap) return;
    wrap.innerHTML = `
      <div>
        <div class="text-[10px] font-bold tracking-widest text-text-muted mb-2">PÉRIODE</div>
        <div class="flex gap-2 flex-wrap" id="f-periods"></div>
      </div>
      <div>
        <div class="text-[10px] font-bold tracking-widest text-text-muted mb-2">TYPE DE PROSPECT</div>
        <div class="flex gap-2 flex-wrap" id="f-segments"></div>
      </div>
    `;
    const periods = document.getElementById('f-periods');
    Object.entries(this.PERIODS).forEach(([key, label]) => {
      const active = key === this.period;
      const btn = document.createElement('button');
      btn.textContent = label;
      btn.style.cssText = this._chipStyle(active);
      btn.onclick = () => { this.period = key; this._renderFilters(); this.refresh(); };
      periods.appendChild(btn);
    });
    const segs = document.getElementById('f-segments');
    Object.entries(this.SEGMENTS).forEach(([key, label]) => {
      const active = key === this.segment;
      const btn = document.createElement('button');
      btn.textContent = label;
      btn.style.cssText = this._chipStyle(active);
      btn.onclick = () => { this.segment = key; this._renderFilters(); this.refresh(); };
      segs.appendChild(btn);
    });
  },

  _chipStyle(active) {
    if (active) {
      return `padding: 7px 14px; border-radius: 999px; font-size: 12.5px;
              font-weight: 600; background: hsl(var(--accent));
              color: white; border: 0; cursor: pointer; transition: all 160ms;`;
    }
    return `padding: 7px 14px; border-radius: 999px; font-size: 12.5px;
            font-weight: 500; background: transparent;
            color: hsl(var(--text-secondary));
            border: 1px solid hsl(var(--border-strong)); cursor: pointer;
            transition: all 160ms;`;
  },

  async refresh() {
    const slot = document.getElementById('f-content');
    if (!App.api) {
      slot.innerHTML = this._preview();
      return;
    }
    slot.innerHTML = `<div class="text-center py-12 text-text-muted">Chargement…</div>`;
    let data;
    try {
      data = await App.api.get_funnel({ period: this.period, segment: this.segment });
    } catch (e) {
      slot.innerHTML = `<div class="card p-6 text-danger">Erreur : ${e}</div>`;
      return;
    }
    if (!data || !data.ok) {
      slot.innerHTML = `
        <div class="card p-10 text-center">
          <div class="text-3xl mb-3">🔌</div>
          <h2 class="text-xl font-semibold mb-2">Connexion requise</h2>
          <p class="text-text-secondary mb-6">Connecte-toi à la base partagée Triskell.</p>
          <button class="btn btn-primary" onclick="App.show('config')">Aller dans Réglages</button>
        </div>
      `;
      return;
    }
    slot.innerHTML = this._renderStages(data) +
                     `<div id="f-templates"></div>` +
                     this._renderBars('Types de réponses reçues', data.by_category, 'accent') +
                     this._renderBars('Où en sont tes prospects', data.by_status, 'accent-glow') +
                     this._renderBars('Produits les plus mis en avant', data.by_product, 'text-secondary');
    this._loadTemplatePerf();
  },

  // ---- Performance par modèle de mail (chargée à part : requête lourde) ----
  async _loadTemplatePerf() {
    const slot = document.getElementById('f-templates');
    if (!slot || !App.api || typeof App.api.funnel_by_template !== 'function') return;
    let r = null;
    try {
      r = await App.api.funnel_by_template({ period: this.period === 'all' ? 'all' : '90d' });
    } catch (e) { r = null; }
    if (!r || !r.ok || !(r.rows || []).length) {
      slot.innerHTML = '';
      return;
    }
    const rows = r.rows.slice(0, 12);
    slot.innerHTML = `
      <div class="mb-10">
        <div class="section-label">Quel modèle de mail fait répondre ? (90 derniers jours)</div>
        <div class="card p-0 overflow-hidden">
          <table class="w-full text-sm">
            <thead class="bg-bg">
              <tr class="text-left text-[11px] uppercase tracking-wide text-text-muted">
                <th class="px-4 py-2.5">Modèle</th>
                <th class="px-4 py-2.5 text-right">Envoyés</th>
                <th class="px-4 py-2.5 text-right">Réponses</th>
                <th class="px-4 py-2.5 text-right">Intéressés</th>
                <th class="px-4 py-2.5 text-right">Taux de réponse</th>
              </tr>
            </thead>
            <tbody>
              ${rows.map(t => `
                <tr class="border-t border-border">
                  <td class="px-4 py-2.5 font-medium truncate max-w-[280px]" title="${this._esc(t.template)}">${this._esc(t.template)}</td>
                  <td class="px-4 py-2.5 text-right tabular-nums">${t.sent}</td>
                  <td class="px-4 py-2.5 text-right tabular-nums">${t.replies}</td>
                  <td class="px-4 py-2.5 text-right tabular-nums ${t.interested > 0 ? 'text-success font-semibold' : ''}">${t.interested}</td>
                  <td class="px-4 py-2.5 text-right tabular-nums font-bold ${t.reply_rate >= 5 ? 'text-success' : ''}">${t.reply_rate}%</td>
                </tr>`).join('')}
            </tbody>
          </table>
          <div class="px-4 py-2.5 text-[11px] text-text-muted border-t border-border">
            Une réponse est créditée au dernier modèle envoyé à ce prospect.
            Moins de 20 envois par modèle = chiffres à prendre avec des pincettes.
          </div>
        </div>
      </div>`;
  },

  _renderStages(data) {
    const stages = data.stages || {};
    let prev = null;
    return `
      <div class="grid grid-cols-5 gap-4 mb-12">
        ${this.STAGES.map((s, i) => {
          const value = stages[s.key] || 0;
          let delta = '';
          if (prev !== null && prev > 0) {
            const pct = Math.round(100 * value / prev * 10) / 10;
            delta = `${pct}% du précédent`;
          } else if (i === 0) {
            delta = `sur ${this.PERIODS[this.period]}`;
          }
          const accent = (s.key === 'won' && prev > 0 && (value/prev) >= 0.05) ? 'success' :
                         (s.key === 'interested' && prev > 0 && (value/prev) >= 0.05) ? 'success' : '';
          prev = value;
          return `
            <div class="stat-card ${accent ? 'accent-' + accent : ''}">
              <div class="label">${s.label}</div>
              <div class="value">${value}</div>
              ${delta ? `<div class="delta">${delta}</div>` : ''}
            </div>
          `;
        }).join('')}
      </div>
    `;
  },

  _renderBars(title, data, color) {
    if (!data || Object.keys(data).length === 0) return '';
    const max = Math.max(...Object.values(data));
    const sorted = Object.entries(data).sort((a, b) => b[1] - a[1]);
    return `
      <div class="mb-10">
        <div class="section-label">${this._esc(title)}</div>
        <div class="card p-6 space-y-3">
          ${sorted.map(([k, v]) => {
            const pct = Math.max(2, Math.round(100 * v / max));
            return `
              <div class="flex items-center gap-4">
                <div class="w-44 text-sm text-text-secondary truncate">${this._esc(k)}</div>
                <div class="flex-1 h-2 rounded-full" style="background: hsl(var(--border));">
                  <div class="h-full rounded-full" style="width: ${pct}%; background: hsl(var(--${color === 'text-secondary' ? 'text-secondary' : color}));"></div>
                </div>
                <div class="w-12 text-right text-sm font-bold">${v}</div>
              </div>
            `;
          }).join('')}
        </div>
      </div>
    `;
  },

  _esc(s) {
    return String(s || '').replace(/[&<>"']/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    }[c]));
  },

  _preview() {
    const fake = {
      ok: true,
      stages: { prospects: 1240, sent: 312, replies: 28, interested: 8, won: 3 },
      by_category: { interested: 8, not_now: 6, no: 9, unsubscribe: 3, unknown: 2 },
      by_status: { new: 870, qualified: 180, contacted: 124, replied: 38, won: 3 },
      by_product: { 'obelisk': 84, 'pack-elec': 62, 'eliks': 41, 'studio-pdf': 24 },
    };
    return this._renderStages(fake) +
           this._renderBars('Types de réponses reçues', fake.by_category, 'accent') +
           this._renderBars('Où en sont tes prospects', fake.by_status, 'accent-glow') +
           this._renderBars('Produits les plus mis en avant', fake.by_product, 'text-secondary');
  },
};
