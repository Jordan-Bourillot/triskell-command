/* SITES À REFAIRE — la liste, d'un coup d'œil.
 *
 * Montre les prospects dont le site mérite d'être refait, en deux niveaux :
 *   🔴 À refaire (sûr)  — repérés solidement (texte ou œil visuel)
 *   🟠 À vérifier       — l'œil hésite, un coup d'œil de Jordan tranche
 *
 * Chaque fiche : nom, métier·ville, motif, lien vers le site, mail.
 * En haut : l'interrupteur de « l'œil » (le robot qui passe la base) + sa
 * progression. Données : oeil_visuel_list / oeil_visuel_status / _set.
 */
const SitesARefaire = {
  _data: { sure: [], verify: [], counts: { sure: 0, verify: 0 } },
  _filter: '',

  esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => (
      { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  },

  async render(container) {
    container.innerHTML = `
      <section class="animate-slide-up">
        <div class="mb-6 flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
          <div class="min-w-0 flex-1">
            <div class="hero-kicker mb-2">PROSPECTION</div>
            <h1 class="hero-title hero-title--md mb-2">Les sites à refaire.</h1>
            <p class="hero-subtitle">Les prospects dont le site mérite clairement d'être refait — tes meilleurs clients potentiels.</p>
          </div>
          <button id="sar-refresh" class="btn btn-secondary">Rafraîchir</button>
        </div>
        <div id="sar-oeil" class="mb-5"></div>
        <input id="sar-search" type="text" placeholder="Filtrer (nom, métier, ville, site…)"
               class="w-full mb-5 px-4 py-2 rounded-lg border border-border bg-surface text-text" />
        <div id="sar-content"><div class="text-center py-12 text-text-muted">Chargement…</div></div>
      </section>`;
    document.getElementById('sar-refresh').onclick = () => this.refresh();
    const box = document.getElementById('sar-search');
    box.oninput = () => { this._filter = box.value.toLowerCase().trim(); this._paint(); };
    await this.refresh();
  },

  async refresh() {
    const slot = document.getElementById('sar-content');
    if (!App.api) { slot.innerHTML = '<div class="card p-8 text-center text-text-muted">Aperçu indisponible.</div>'; return; }
    slot.innerHTML = '<div class="text-center py-12 text-text-muted">Chargement de la base… (quelques secondes)</div>';
    try {
      const [list, status] = await Promise.all([
        App.api.oeil_visuel_list(),
        App.api.oeil_visuel_status().catch(() => ({})),
      ]);
      if (!list || !list.ok) throw new Error((list && list.error) || 'erreur');
      this._data = list;
      this._status = status || {};
      this._paintOeil();
      this._paint();
    } catch (e) {
      console.error('[SitesARefaire]', e);
      slot.innerHTML = `<div class="card p-8 text-center"><div class="text-3xl mb-3">⚠️</div>
        <div class="text-text-muted">Impossible de charger la liste.<br><span class="text-xs">${this.esc(e.message || e)}</span></div></div>`;
    }
  },

  _paintOeil() {
    const slot = document.getElementById('sar-oeil');
    if (!slot) return;
    const s = this._status || {};
    const on = !!s.enabled, running = !!s.running;
    const t = s.totals || {};
    const last = s.last_run_result || {};
    const remain = (last.remaining != null) ? last.remaining : null;
    slot.innerHTML = `
      <div class="card p-4 flex flex-col sm:flex-row sm:items-center gap-3">
        <div class="flex-1 min-w-0">
          <div class="font-semibold flex items-center gap-2">
            <span class="inline-block w-2 h-2 rounded-full ${running ? 'bg-emerald-500' : 'bg-gray-400'}"></span>
            « L'œil » — le robot qui repère les sites à refaire
          </div>
          <div class="text-sm text-text-muted mt-1">
            ${on ? 'Allumé' : 'Éteint'} · ${running ? 'en train de tourner' : 'au repos'}
            ${t.judged ? ` · ${t.judged} sites regardés cette session` : ''}
            ${remain != null ? ` · ${remain} restants à regarder` : ''}
          </div>
        </div>
        <button id="sar-oeil-toggle" class="btn ${on ? 'btn-secondary' : 'btn-primary'}">
          ${on ? 'Mettre en pause' : 'Allumer'}
        </button>
      </div>`;
    const btn = document.getElementById('sar-oeil-toggle');
    if (btn) btn.onclick = async () => {
      btn.disabled = true; btn.textContent = '…';
      try {
        await App.api.oeil_visuel_set({ enabled: !on });
        this._status = await App.api.oeil_visuel_status().catch(() => this._status);
        this._paintOeil();
      } catch (e) { btn.disabled = false; this._paintOeil(); }
    };
  },

  _match(it) {
    if (!this._filter) return true;
    return ((it.name || '') + ' ' + (it.metier || '') + ' ' + (it.ville || '') + ' ' +
            (it.website || '') + ' ' + (it.categories || []).join(' ')).toLowerCase()
            .includes(this._filter);
  },

  _card(it, tier) {
    const cats = (it.categories || []).map(c =>
      `<span class="text-[11px] px-2 py-0.5 rounded-full bg-surface-muted text-text-muted">${this.esc(c)}</span>`).join(' ');
    const sub = [it.metier, it.ville].filter(Boolean).map(x => this.esc(x)).join(' · ');
    const site = it.website
      ? `<a href="${this.esc(it.website)}" target="_blank" rel="noopener" class="text-info hover:underline break-all">${this.esc(it.website.replace(/^https?:\/\//, ''))}</a>`
      : '<span class="text-text-muted">—</span>';
    const ring = tier === 'sure' ? 'border-l-4 border-l-red-500' : 'border-l-4 border-l-amber-500';
    return `
      <div class="card p-4 ${ring}">
        <div class="font-semibold truncate">${this.esc(it.name) || '(sans nom)'}</div>
        ${sub ? `<div class="text-sm text-text-muted mb-1">${sub}</div>` : ''}
        <div class="flex flex-wrap gap-1 my-2">${cats}</div>
        ${it.reason ? `<div class="text-sm mb-2">${this.esc(it.reason)}</div>` : ''}
        <div class="text-sm flex flex-wrap items-center gap-x-4 gap-y-1">
          <span>🔗 ${site}</span>
          ${it.email ? `<span class="text-text-muted">✉️ ${this.esc(it.email)}</span>` : ''}
        </div>
      </div>`;
  },

  _section(title, items, tier) {
    const shown = items.filter(it => this._match(it));
    if (!items.length) return '';
    const head = `<div class="flex items-baseline gap-2 mb-3 mt-2">
        <h2 class="text-lg font-bold">${title}</h2>
        <span class="text-sm text-text-muted">${shown.length}${shown.length !== items.length ? ' / ' + items.length : ''}</span>
      </div>`;
    if (!shown.length) return head + '<div class="text-text-muted text-sm mb-6">Aucun résultat pour ce filtre.</div>';
    return head + `<div class="grid sm:grid-cols-2 gap-3 mb-8">${shown.map(it => this._card(it, tier)).join('')}</div>`;
  },

  _paint() {
    const slot = document.getElementById('sar-content');
    if (!slot) return;
    const d = this._data;
    if (!d.sure.length && !d.verify.length) {
      slot.innerHTML = `<div class="card p-10 text-center text-text-muted">
        <div class="text-3xl mb-3">🔭</div>
        Aucun site à refaire repéré pour l'instant.<br>
        <span class="text-sm">L'œil va en trouver au fur et à mesure qu'il passe la base.</span></div>`;
      return;
    }
    slot.innerHTML =
      this._section('🔴 À refaire — sûr', d.sure, 'sure') +
      this._section('🟠 À vérifier', d.verify, 'verify');
  },
};
