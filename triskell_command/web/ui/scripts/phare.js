/* Vue Le Phare — agence SEO autonome multi-sites
 *
 * 4 onglets internes :
 *   1. Écosystème  → KPI globaux + table des sites
 *   2. Site        → focus 1 site
 *   3. Bac à PRs   → actions en attente de validation
 *   4. Bulletins   → derniers rapports
 */

const Phare = {
  tab: 'eco',
  selectedSite: null,
  TABS: [
    { key: 'eco',     label: 'Écosystème' },
    { key: 'site',    label: 'Site' },
    { key: 'prs',     label: 'Bac à PRs' },
    { key: 'reports', label: 'Bulletins' },
  ],

  async render(container) {
    container.innerHTML = `
      <section class="animate-slide-up">
        <div class="mb-5 sm:mb-6">
          <div class="flex items-start justify-between gap-3">
            <div class="min-w-0 flex-1">
              <div class="hero-kicker mb-2">VISIBILITÉ — LE PHARE</div>
              <h1 class="hero-title hero-title--md mb-2 sm:mb-3">Ton agence SEO autonome.</h1>
              <p class="hero-subtitle">8 agents Claude qui surveillent, optimisent et publient sur tes 13 sites Triskell.</p>
            </div>
            ${Help.button('phare')}
          </div>
        </div>

        <!-- Onglets : scrollable horizontalement sur mobile -->
        <div class="flex gap-1 mb-6 sm:mb-8 border-b border-border overflow-x-auto -mx-1 px-1" id="ph-tabs"></div>

        <div id="ph-content"></div>
      </section>
    `;
    this._renderTabs();
    await this._renderTab();
  },

  _renderTabs() {
    const wrap = document.getElementById('ph-tabs');
    wrap.innerHTML = this.TABS.map(t => {
      const active = t.key === this.tab;
      return `
        <button data-tab="${t.key}"
                class="px-5 py-3 text-sm font-semibold border-b-2 transition-all"
                style="color: ${active ? 'hsl(var(--accent))' : 'hsl(var(--text-muted))'};
                       border-color: ${active ? 'hsl(var(--accent))' : 'transparent'};">
          ${t.label}
        </button>
      `;
    }).join('');
    wrap.querySelectorAll('[data-tab]').forEach(btn => {
      btn.onclick = () => {
        this.tab = btn.dataset.tab;
        this._renderTabs();
        this._renderTab();
      };
    });
  },

  async _renderTab() {
    const slot = document.getElementById('ph-content');
    if (this.tab === 'eco')     return this._renderEco(slot);
    if (this.tab === 'site')    return this._renderSite(slot);
    if (this.tab === 'prs')     return this._renderPRs(slot);
    if (this.tab === 'reports') return this._renderReports(slot);
  },

  // -------- Onglet 1 : Écosystème --------
  async _renderEco(slot) {
    if (!App.api) {
      slot.innerHTML = this._previewEco();
      return;
    }
    slot.innerHTML = `<div class="text-center py-12 text-text-muted">Chargement…</div>`;
    let overview, sites;
    try {
      [overview, sites] = await Promise.all([
        App.api.phare_overview(),
        App.api.phare_sites(),
      ]);
    } catch (e) {
      slot.innerHTML = `<div class="card p-6 text-danger">Erreur : ${e}</div>`;
      return;
    }

    if ((!overview || !overview.ok) && (!sites || !sites.ok)) {
      slot.innerHTML = `
        <div class="card p-10 text-center">
          <div class="text-3xl mb-3">🔌</div>
          <h2 class="text-xl font-semibold mb-2">Connexion requise</h2>
          <p class="text-text-secondary mb-6">
            Le Phare lit ses chiffres dans la base partagée Triskell.
            Connecte-toi pour activer ce module.
          </p>
          <button class="btn btn-primary" onclick="App.show('config')">Aller dans Réglages</button>
        </div>
      `;
      return;
    }

    const ov = (overview && overview.ok) ? overview : { sites_count: 0, total_clicks_30d: 0, avg_position_30d: 0, pending_actions: 0 };
    const list = (sites && sites.ok) ? (sites.sites || []) : [];

    slot.innerHTML = `
      <div class="grid grid-cols-2 sm:grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-5 mb-6 sm:mb-10">
        ${this._stat({label: 'Sites surveillés', value: ov.sites_count ?? list.length})}
        ${this._stat({label: 'Clics 30 jours',   value: this._fmt(ov.total_clicks_30d), accent: 'success'})}
        ${this._stat({label: 'Position moyenne', value: ov.avg_position_30d ? Number(ov.avg_position_30d).toFixed(1) : '—'})}
        ${this._stat({label: 'PRs en attente',   value: ov.pending_actions ?? 0, accent: ov.pending_actions > 0 ? 'warning' : ''})}
      </div>

      <div class="section-label">Tes sites</div>
      <div class="card overflow-hidden">
        ${list.length === 0 ? `
          <div class="text-center py-10 text-text-muted">
            Aucun site enregistré. Le seed initial se fait via supabase/06_phare.sql.
          </div>
        ` : `
          <table class="w-full text-sm">
            <thead>
              <tr style="background: hsl(var(--bg)); border-bottom: 1px solid hsl(var(--border));">
                <th class="text-left px-5 py-3 font-semibold text-text-muted text-xs tracking-widest">SITE</th>
                <th class="text-left px-5 py-3 font-semibold text-text-muted text-xs tracking-widest">DOMAINE</th>
                <th class="text-right px-5 py-3 font-semibold text-text-muted text-xs tracking-widest">CLICS 30J</th>
                <th class="text-right px-5 py-3 font-semibold text-text-muted text-xs tracking-widest">POSITION</th>
                <th class="text-right px-5 py-3 font-semibold text-text-muted text-xs tracking-widest">ACTIONS</th>
              </tr>
            </thead>
            <tbody>
              ${list.map(s => `
                <tr class="border-b border-border last:border-0 hover:bg-bg/50 cursor-pointer transition-colors"
                    data-site-id="${s.id || ''}">
                  <td class="px-5 py-4 font-semibold">${this._esc(s.name || s.domain || '—')}</td>
                  <td class="px-5 py-4 text-text-muted text-xs">${this._esc(s.domain || '')}</td>
                  <td class="px-5 py-4 text-right">${this._fmt(s.clicks_30d) || '—'}</td>
                  <td class="px-5 py-4 text-right">${s.avg_position_30d ? Number(s.avg_position_30d).toFixed(1) : '—'}</td>
                  <td class="px-5 py-4 text-right">
                    <button class="text-accent hover:underline text-xs font-semibold"
                            data-focus-site="${s.id || ''}">Voir →</button>
                  </td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        `}
      </div>
    `;
    slot.querySelectorAll('[data-focus-site]').forEach(btn => {
      btn.onclick = (e) => {
        e.stopPropagation();
        this.selectedSite = btn.dataset.focusSite;
        this.tab = 'site';
        this._renderTabs();
        this._renderTab();
      };
    });
    slot.querySelectorAll('tr[data-site-id]').forEach(tr => {
      tr.onclick = () => {
        this.selectedSite = tr.dataset.siteId;
        this.tab = 'site';
        this._renderTabs();
        this._renderTab();
      };
    });
  },

  // -------- Onglet 2 : Site --------
  async _renderSite(slot) {
    if (!this.selectedSite) {
      slot.innerHTML = `
        <div class="card p-10 text-center">
          <div class="text-3xl mb-3">📍</div>
          <h2 class="text-xl font-semibold mb-2">Choisis un site</h2>
          <p class="text-text-secondary mb-6">Reviens à l'onglet Écosystème et clique sur un site pour voir son détail.</p>
          <button class="btn btn-secondary" onclick="Phare.tab='eco'; Phare._renderTabs(); Phare._renderTab();">← Retour</button>
        </div>
      `;
      return;
    }
    if (!App.api) {
      slot.innerHTML = `<div class="card p-6 text-text-muted">Mode preview.</div>`;
      return;
    }
    slot.innerHTML = `<div class="text-center py-12 text-text-muted">Chargement…</div>`;
    let data;
    try { data = await App.api.phare_site({ id: this.selectedSite }); }
    catch (e) {
      slot.innerHTML = `<div class="card p-6 text-danger">Erreur : ${e}</div>`;
      return;
    }
    if (!data || !data.ok) {
      slot.innerHTML = `<div class="card p-6 text-danger">${data?.error || 'Erreur'}</div>`;
      return;
    }
    const s = data.site || {};
    const audit = data.audit || {};
    const kws = data.keywords || [];
    const acts = data.actions || [];
    slot.innerHTML = `
      <div class="card-hero p-8 mb-6">
        <div class="flex items-start justify-between gap-4">
          <div>
            <div class="hero-kicker text-accent mb-2">SITE</div>
            <h2 class="font-sans text-2xl font-bold mb-1 tracking-tight">${this._esc(s.name || s.domain || '—')}</h2>
            <div class="text-text-muted text-sm">${this._esc(s.domain || '')}</div>
          </div>
          <button class="btn btn-primary" data-act="audit">Lancer un audit</button>
        </div>
      </div>

      <div class="grid grid-cols-1 sm:grid-cols-3 gap-3 sm:gap-5 mb-6 sm:mb-10">
        ${this._stat({label: 'Score audit', value: audit.score != null ? audit.score : '—'})}
        ${this._stat({label: 'Mots-clés suivis', value: kws.length})}
        ${this._stat({label: 'Actions ouvertes', value: acts.length, accent: acts.length > 0 ? 'warning' : ''})}
      </div>

      <div class="section-label">Top mots-clés</div>
      <div class="card mb-10 overflow-hidden">
        ${kws.length === 0
          ? `<div class="text-center py-10 text-text-muted text-sm">Aucun mot-clé encore. Lance la veille mots-clés.</div>`
          : `<div class="divide-y divide-border">
              ${kws.slice(0, 10).map(k => `
                <div class="px-5 py-3 flex items-center justify-between text-sm">
                  <div class="flex-1 truncate font-semibold">${this._esc(k.keyword || k.query || '—')}</div>
                  <div class="text-text-muted text-xs ml-4">Position ${k.position != null ? Number(k.position).toFixed(1) : '—'} · ${this._fmt(k.search_volume) || '—'}/mo</div>
                </div>
              `).join('')}
            </div>`}
      </div>

      <div class="section-label">Actions récentes</div>
      <div class="card overflow-hidden">
        ${acts.length === 0
          ? `<div class="text-center py-10 text-text-muted text-sm">Aucune action en cours.</div>`
          : `<div class="divide-y divide-border">
              ${acts.slice(0, 10).map(a => `
                <div class="px-5 py-3 flex items-center justify-between text-sm">
                  <div class="flex-1">
                    <div class="font-semibold">${this._esc(a.title || a.kind || '—')}</div>
                    <div class="text-xs text-text-muted">${this._esc(a.kind || '')} · ${(a.created_at || '').slice(0,10)}</div>
                  </div>
                  <span class="text-xs px-2 py-1 rounded-full font-semibold
                              ${a.status === 'pending_review' ? 'bg-warning/15 text-warning' : ''}
                              ${a.status === 'merged' ? 'bg-success/15 text-success' : ''}
                              ${a.status === 'rejected' ? 'bg-danger/15 text-danger' : ''}
                              ${!['pending_review','merged','rejected'].includes(a.status) ? 'bg-bg text-text-muted' : ''}">
                    ${this._esc(a.status || 'inconnu')}
                  </span>
                </div>
              `).join('')}
            </div>`}
      </div>
    `;
    slot.querySelector('[data-act="audit"]').onclick = async () => {
      try {
        await App.api.phare_run_audit({ id: this.selectedSite });
        // Toast simple
        const t = document.createElement('div');
        t.textContent = '✓ Audit lancé en arrière-plan';
        t.className = 'fixed bottom-32 right-8 bg-success text-white px-4 py-2 rounded-xl shadow-lift z-50 animate-fade-in';
        document.body.appendChild(t);
        setTimeout(() => t.remove(), 4000);
      } catch (e) { console.warn(e); }
    };
  },

  // -------- Onglet 3 : Bac à PRs --------
  async _renderPRs(slot) {
    if (!App.api) { slot.innerHTML = `<div class="card p-6 text-text-muted">Mode preview.</div>`; return; }
    slot.innerHTML = `<div class="text-center py-12 text-text-muted">Chargement…</div>`;
    let data;
    try { data = await App.api.phare_pending_actions(); }
    catch (e) { slot.innerHTML = `<div class="card p-6 text-danger">Erreur : ${e}</div>`; return; }
    if (!data || !data.ok) {
      slot.innerHTML = `<div class="card p-6 text-danger">${data?.error || 'Erreur'}</div>`;
      return;
    }
    const acts = data.actions || [];
    if (acts.length === 0) {
      slot.innerHTML = `
        <div class="card p-6 sm:p-12 text-center">
          <div class="text-4xl mb-3">✓</div>
          <h2 class="text-xl font-semibold mb-2">Aucune PR en attente</h2>
          <p class="text-text-secondary max-w-lg mx-auto">
            Les agents Claude n'ont rien à te faire valider. Tout est déjà mergé ou en cours d'analyse.
          </p>
        </div>
      `;
      return;
    }
    slot.innerHTML = `
      <div class="space-y-4">
        ${acts.map(a => `
          <article class="card p-6">
            <header class="flex items-start justify-between gap-4 mb-3">
              <div>
                <div class="font-semibold text-base">${this._esc(a.title || a.kind || '—')}</div>
                <div class="text-xs text-text-muted">${this._esc(a.kind || '')} · ${(a.created_at || '').slice(0,16)}</div>
              </div>
              <span class="text-xs px-2.5 py-1 rounded-full bg-warning/15 text-warning font-semibold">à valider</span>
            </header>
            ${a.summary ? `<p class="text-sm text-text-secondary mb-4">${this._esc(a.summary)}</p>` : ''}
            <footer class="flex justify-end gap-2 pt-3 border-t border-border">
              <button class="btn btn-secondary" data-merge="${a.id}" data-force="false">Merger</button>
              <button class="btn btn-primary" data-merge="${a.id}" data-force="true">Forcer le merge</button>
            </footer>
          </article>
        `).join('')}
      </div>
    `;
    slot.querySelectorAll('[data-merge]').forEach(btn => {
      btn.onclick = async () => {
        try {
          await App.api.phare_merge_action({ id: btn.dataset.merge, force: btn.dataset.force === 'true' });
          await this._renderTab();
        } catch (e) { console.warn(e); }
      };
    });
  },

  // -------- Onglet 4 : Bulletins --------
  async _renderReports(slot) {
    slot.innerHTML = `
      <div class="card p-6 sm:p-12 text-center">
        <div class="text-4xl mb-3">📰</div>
        <h2 class="text-xl font-semibold mb-2">Bulletins de l'Analyste</h2>
        <p class="text-text-secondary max-w-lg mx-auto">
          Les rapports hebdomadaires et le plan stratégique mensuel apparaîtront ici
          dès que l'Analyste aura tourné. Le scheduler est actif toutes les heures.
        </p>
      </div>
    `;
  },

  _stat({label, value, delta, accent}) {
    const cls = accent ? `accent-${accent}` : '';
    return `
      <div class="stat-card ${cls}">
        <div class="label">${this._esc(label)}</div>
        <div class="value">${this._esc(String(value))}</div>
        ${delta ? `<div class="delta">${this._esc(delta)}</div>` : ''}
      </div>
    `;
  },

  _fmt(n) {
    if (n == null || n === '') return '—';
    const x = Number(n);
    if (isNaN(x)) return String(n);
    if (x >= 10000) return (x / 1000).toFixed(1) + 'k';
    return x.toLocaleString('fr-FR');
  },

  _esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    }[c]));
  },

  _previewEco() {
    const fake = { sites_count: 13, total_clicks_30d: 8420, avg_position_30d: 18.4, pending_actions: 3 };
    const list = [
      { id: '1', name: 'Pack Électricien', domain: 'pack-elec.triskell-studio.fr', clicks_30d: 1840, avg_position_30d: 12.3 },
      { id: '2', name: 'Studio PDF', domain: 'studio-pdf.triskell-studio.fr', clicks_30d: 920, avg_position_30d: 22.1 },
      { id: '3', name: 'Bobeez', domain: 'bobeez.triskell-studio.fr', clicks_30d: 410, avg_position_30d: 31.7 },
    ];
    return `
      <div class="grid grid-cols-2 sm:grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-5 mb-6 sm:mb-10">
        ${this._stat({label: 'Sites surveillés', value: fake.sites_count})}
        ${this._stat({label: 'Clics 30 jours', value: this._fmt(fake.total_clicks_30d), accent: 'success'})}
        ${this._stat({label: 'Position moyenne', value: fake.avg_position_30d.toFixed(1)})}
        ${this._stat({label: 'PRs en attente', value: fake.pending_actions, accent: 'warning'})}
      </div>
      <div class="section-label">Tes sites</div>
      <div class="card overflow-hidden">
        <table class="w-full text-sm">
          <tbody>
            ${list.map(s => `
              <tr class="border-b border-border last:border-0">
                <td class="px-5 py-4 font-semibold">${s.name}</td>
                <td class="px-5 py-4 text-text-muted text-xs">${s.domain}</td>
                <td class="px-5 py-4 text-right">${this._fmt(s.clicks_30d)}</td>
                <td class="px-5 py-4 text-right">${s.avg_position_30d.toFixed(1)}</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    `;
  },
};
