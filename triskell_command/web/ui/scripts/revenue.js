/* Revenue — vue agrégée des revenus de toutes les sources.
 *
 * Agrège :
 *   - Paiements Stripe (depuis stripe_poller)
 *   - Activations AppSumo (depuis netlify_functions)
 *   - Paiements manuels (cartes clients avec amount_cents et paid_at)
 *
 * Affiche :
 *   - MRR du mois en cours vs mois précédent (% évolution)
 *   - Total encaissé mois en cours / 7 jours / 30 jours
 *   - Top clients en valeur (mois en cours)
 *   - Répartition par produit / source
 *   - Prévisions (intakes en cours × taux de conversion observé)
 *
 * Pas de tableau brut de toutes les transactions — on reste sur des
 * insights actionnables.
 */

const Revenue = {
  async render(container) {
    container.innerHTML = `
      <section class="animate-slide-up">
        <div class="mb-6 sm:mb-8 flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
          <div class="min-w-0 flex-1">
            <div class="hero-kicker mb-2">REVENUS</div>
            <h1 class="hero-title hero-title--md mb-2 sm:mb-3">Tes encaissements, tout regroupé.</h1>
            <p class="hero-subtitle">Stripe + AppSumo + paiements manuels, en une seule vue. Tu vois où tu en es, où tu vas.</p>
          </div>
          <div class="flex flex-wrap gap-2">
            <button id="rev-refresh" class="btn btn-secondary">Rafraîchir</button>
          </div>
        </div>
        <div id="rev-content" class="space-y-6 sm:space-y-10"></div>
      </section>
    `;
    document.getElementById('rev-refresh').onclick = () => this.refresh();
    await this.refresh();
  },

  async refresh() {
    const slot = document.getElementById('rev-content');
    if (!slot) return;
    if (!App.api) {
      slot.innerHTML = this._preview();
      return;
    }
    slot.innerHTML = '<div class="text-center py-12 text-text-muted">Chargement…</div>';
    let data;
    try {
      data = await App.api.revenue_overview();
    } catch (e) {
      console.error('[Revenue] chargement', e);
      slot.innerHTML = `
        <div class="card p-10 text-center">
          <div class="text-3xl mb-3">⚠️</div>
          <h2 class="text-xl font-semibold mb-2">Impossible de charger tes revenus</h2>
          <p class="text-text-secondary mb-6">Le serveur n'a pas répondu. Vérifie ta connexion, puis réessaie.</p>
          <button class="btn btn-primary" onclick="Revenue.refresh()">Réessayer</button>
        </div>
      `;
      return;
    }
    if (!data || !data.ok) {
      if (data && data.error) console.warn('[Revenue] connexion', data.error);
      slot.innerHTML = `
        <div class="card p-10 text-center">
          <div class="text-3xl mb-3">🔌</div>
          <h2 class="text-xl font-semibold mb-2">Connexion à la base partagée requise</h2>
          <p class="text-text-muted mb-6">Connecte l'app à la base partagée pour voir tes encaissements.</p>
          <button class="btn btn-primary" onclick="App.show('config', {tab:'account'})">Aller dans Réglages</button>
        </div>
      `;
      return;
    }

    // Rien encaissé nulle part → état vide PÉDAGOGIQUE plutôt que des zéros partout
    const cur = data.current_month || {};
    const prev = data.previous_month || {};
    const nothingYet = !(cur.total_cents || prev.total_cents
      || (data.last_30_days || {}).total_cents || (data.last_7_days || {}).total_cents
      || (data.top_clients_month || []).length);
    if (nothingYet) {
      slot.innerHTML = `
        <div class="card p-10 text-center">
          <div class="text-3xl mb-3">💶</div>
          <h2 class="text-xl font-semibold mb-2">Pas encore d'encaissement enregistré</h2>
          <p class="text-text-muted max-w-xl mx-auto">
            Les chiffres de cet écran viennent de tes ventes (Stripe, AppSumo, paiements manuels).
            Lance une prospection ou enregistre une vente, et tout s'affichera ici tout seul.
          </p>
        </div>
      `;
      return;
    }

    slot.innerHTML =
      this._renderHero(data) +
      this._renderKpis(data) +
      this._renderTopClients(data) +
      this._renderBreakdown(data) +
      this._renderForecast(data);
    this._bindTopClients(slot);
  },

  // Les lignes du top clients ouvrent le fichier clients (clic ou Entrée)
  _bindTopClients(slot) {
    slot.querySelectorAll('[data-goto-clients]').forEach(row => {
      const go = () => App.show('clients_master');
      row.onclick = go;
      row.onkeydown = (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); }
      };
    });
  },

  _renderHero(d) {
    const cur = d.current_month || {};
    const prev = d.previous_month || {};
    // Mois précédent à 0 € : un « → 0 % » serait trompeur → on dit « nouveau »
    let evolHtml = '';
    let accent = 'success';
    let evolSub = '';
    if (prev.total_cents > 0) {
      const evolPct = Math.round(((cur.total_cents - prev.total_cents) / prev.total_cents) * 100);
      const evolClass = evolPct > 0 ? 'text-success-text' : evolPct < 0 ? 'text-danger-text' : 'text-text-muted';
      const evolIcon = evolPct > 0 ? '↑' : evolPct < 0 ? '↓' : '→';
      evolHtml = `<div class="text-base ${evolClass} font-semibold">${evolIcon} ${Math.abs(evolPct)}% vs ${prev.label || 'mois précédent'}</div>`;
      accent = evolPct >= 0 ? 'success' : 'warning';
      evolSub = ` — ${this._fmtEuro(cur.total_cents - prev.total_cents)} d'évolution`;
    } else if ((cur.total_cents || 0) > 0) {
      evolHtml = `<div class="text-base text-success-text font-semibold">nouveau (+${this._fmtEuro(cur.total_cents)}) — rien d'encaissé le mois précédent</div>`;
    }
    return `
      <div class="card-hero p-6 sm:p-10" data-accent="${accent}">
        <div class="hero-kicker text-success-text mb-2">${(cur.label || 'Mois en cours').toUpperCase()}</div>
        <div class="flex items-baseline gap-4 flex-wrap">
          <div class="font-display text-3xl sm:text-5xl font-bold">${this._fmtEuro(cur.total_cents)}</div>
          ${evolHtml}
        </div>
        <p class="text-text-secondary text-sm mt-3 max-w-xl">
          ${cur.transactions_count || 0} transactions ce mois${evolSub}.
        </p>
        <p class="text-text-muted text-xs mt-2 max-w-xl" style="text-wrap: pretty">
          Ces montants = ce que tes clients ont payé (Stripe, AppSumo et ventes
          saisies à la main), avant déduction des frais bancaires.
        </p>
      </div>
    `;
  },

  _renderKpis(d) {
    const cur = d.current_month || {};
    const last7 = d.last_7_days || {};
    const last30 = d.last_30_days || {};
    return `
      <div>
        <div class="section-label">Encaissements récents</div>
        <div class="grid grid-cols-1 sm:grid-cols-3 gap-3 sm:gap-5">
          ${this._stat({label: 'Mois en cours', value: this._fmtEuro(cur.total_cents),
                        delta: `${cur.transactions_count || 0} ventes`})}
          ${this._stat({label: '7 derniers jours', value: this._fmtEuro(last7.total_cents),
                        delta: `${last7.transactions_count || 0} ventes`})}
          ${this._stat({label: '30 derniers jours', value: this._fmtEuro(last30.total_cents),
                        delta: `${last30.transactions_count || 0} ventes`})}
        </div>
      </div>
    `;
  },

  _renderTopClients(d) {
    const top = d.top_clients_month || [];
    if (top.length === 0) return '';
    return `
      <div>
        <div class="section-label">Top clients du mois</div>
        <div class="card overflow-hidden">
          <div class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead>
              <tr style="background: hsl(var(--bg)); border-bottom: 1px solid hsl(var(--border));">
                <th class="text-left px-5 py-3 font-semibold text-text-muted text-xs tracking-widest">CLIENT</th>
                <th class="text-left px-5 py-3 font-semibold text-text-muted text-xs tracking-widest">PRODUIT</th>
                <th class="text-right px-5 py-3 font-semibold text-text-muted text-xs tracking-widest">MONTANT</th>
                <th class="text-right px-5 py-3 font-semibold text-text-muted text-xs tracking-widest">SOURCE</th>
              </tr>
            </thead>
            <tbody>
              ${top.slice(0, 10).map(c => `
                <tr class="border-b border-border last:border-0 cursor-pointer hover:bg-bg transition-colors"
                    data-goto-clients role="button" tabindex="0"
                    title="Voir sa fiche dans le fichier clients">
                  <td class="px-5 py-3 font-semibold">${this._esc(c.client_name || c.client_email || '—')}</td>
                  <td class="px-5 py-3 text-text-muted">${this._esc(c.product || '—')}</td>
                  <td class="px-5 py-3 text-right font-semibold">${this._fmtEuro(c.amount_cents)}</td>
                  <td class="px-5 py-3 text-right text-text-muted text-xs">${this._sourceLabel(c.source)}</td>
                </tr>
              `).join('')}
            </tbody>
          </table>
          </div>
        </div>
      </div>
    `;
  },

  _renderBreakdown(d) {
    const bySrc = d.by_source_month || {};
    const byProd = d.by_product_month || {};
    return `
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div>
          <div class="section-label">Par source</div>
          <div class="card p-5">
            ${this._renderBars(bySrc, (k) => this._sourceLabel(k))}
          </div>
        </div>
        <div>
          <div class="section-label">Par produit</div>
          <div class="card p-5">
            ${this._renderBars(byProd, (k) => k || 'Autre')}
          </div>
        </div>
      </div>
    `;
  },

  _renderBars(data, labelFn) {
    const entries = Object.entries(data || {}).sort((a, b) => (b[1] || 0) - (a[1] || 0));
    if (entries.length === 0) {
      return '<div class="text-sm text-text-muted">Aucune donnée pour ce mois.</div>';
    }
    const max = Math.max(...entries.map(e => e[1] || 0));
    return entries.map(([key, val]) => {
      const pct = max > 0 ? (val / max) * 100 : 0;
      return `
        <div class="mb-3 last:mb-0">
          <div class="flex justify-between text-sm mb-1">
            <span>${this._esc(labelFn(key))}</span>
            <span class="font-semibold text-text">${this._fmtEuro(val)}</span>
          </div>
          <div class="h-2 rounded-full bg-bg overflow-hidden">
            <div class="h-full rounded-full bg-accent" style="width: ${pct}%; transition: width 600ms;"></div>
          </div>
        </div>
      `;
    }).join('');
  },

  _renderForecast(d) {
    const fc = d.forecast || null;
    if (!fc) return '';
    return `
      <div>
        <div class="section-label">Prévision fin de mois</div>
        <div class="card p-6 flex items-start gap-4">
          <div class="text-3xl">🔮</div>
          <div class="flex-1">
            <div class="font-display text-2xl font-bold mb-1">${this._fmtEuro(fc.projected_month_cents)}</div>
            <p class="text-sm text-text-muted">
              Basée sur ${fc.pipeline_count || 0} demandes en cours × taux de transformation observé (${fc.conversion_rate_pct || 0}%) + encaissements déjà reçus.
              Marge ${fc.confidence_low_cents ? `entre ${this._fmtEuro(fc.confidence_low_cents)} et ${this._fmtEuro(fc.confidence_high_cents)}` : '—'}.
            </p>
          </div>
        </div>
      </div>
    `;
  },

  _preview() {
    return `
      <div class="card p-10 text-center text-text-muted">
        Mode aperçu — les vrais chiffres s'afficheront quand l'app sera connectée au serveur.
      </div>
    `;
  },

  _stat({label, value, delta}) {
    return `
      <div class="card p-5">
        <div class="text-[11px] font-bold tracking-widest text-text-muted mb-2">${label.toUpperCase()}</div>
        <div class="font-display text-2xl sm:text-3xl font-bold mb-1">${value}</div>
        ${delta ? `<div class="text-xs text-text-muted">${delta}</div>` : ''}
      </div>
    `;
  },

  _fmtEuro(cents) {
    if (!cents) return '0 €';
    const euros = cents / 100;
    if (euros >= 1000) return `${euros.toLocaleString('fr-FR', { maximumFractionDigits: 0 })} €`;
    return `${euros.toLocaleString('fr-FR', { maximumFractionDigits: 2 })} €`;
  },

  _sourceLabel(s) {
    return ({
      'stripe':   'Stripe',
      'appsumo':  'AppSumo',
      'manual':   'Manuel',
      'other':    'Autre',
    })[s] || (s || 'Autre');
  },

  _esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;',
    }[c]));
  },
};
