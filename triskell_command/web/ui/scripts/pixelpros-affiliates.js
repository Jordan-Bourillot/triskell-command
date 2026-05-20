/* Vue Pixel Pros · Affiliés — backoffice du programme d'affiliation.
 *
 * 3 zones :
 *   1. Cartes synthétiques (compteurs : actifs / ventes pending / à verser / déjà versé)
 *   2. Bloc "Paiements du mois" → liste des affiliés à payer ce mois-ci (>= 50 €)
 *   3. Tableau des affiliés (cherchable) avec détail au clic
 *
 * Endpoints :
 *   App.api.pixelpros_affiliates_list({ status?, limit? })
 *   App.api.pixelpros_affiliate_get({ id })
 *   App.api.pixelpros_affiliate_set_status({ id, status })
 *   App.api.pixelpros_affiliate_sales_list({ status? })
 *   App.api.pixelpros_affiliate_mark_sales_paid({ ids, batch_ref })
 *   App.api.pixelpros_affiliate_cancel_sale({ id, reason })
 *   App.api.pixelpros_affiliate_prepare_payouts()
 *   App.api.pixelpros_affiliate_promote_pending({ min_age_days? })
 */

const PixelProsAffiliates = {
  state: {
    affiliates: [],
    counts: { active: 0, pending: 0, paused: 0, banned: 0 },
    payouts: [],
    payouts_total_cents: 0,
    sales: [],
    selectedId: null,
    detail: null,
    search: '',
    loading: false,
  },

  async render(container) {
    this._root = container;
    container.innerHTML = `
      <section class="animate-slide-up">
        <div class="mb-6 flex items-end justify-between flex-wrap gap-3">
          <div>
            <div class="hero-kicker mb-2" style="color:#facc15;">PIXEL PROS · AFFILIÉS</div>
            <h1 class="hero-title mb-2" style="font-size: 34px;">Programme d'affiliation.</h1>
            <p class="hero-subtitle">10 % de commission sur 12 mois. Suivi des ventes, paiements à préparer, gestion des comptes.</p>
          </div>
          <div class="flex items-center gap-2">
            <button id="ppa-promote" class="btn btn-secondary" title="Passe en 'versable' les commissions pending de plus de 30 jours">
              ⏰ Lib&eacute;rer commissions ≥30j
            </button>
            <button id="ppa-refresh" class="btn btn-secondary">↻ Rafraîchir</button>
          </div>
        </div>

        <div id="ppa-stats" class="ppa-stats mb-6"></div>
        <div id="ppa-payouts" class="mb-7"></div>
        <div id="ppa-list-wrap"></div>
        <div id="ppa-detail-overlay" class="pp-detail-overlay" hidden></div>
        <aside id="ppa-detail" class="pp-detail-panel" hidden></aside>
      </section>
    `;
    this._injectStyles();

    document.getElementById('ppa-refresh').onclick = () => this.refresh();
    document.getElementById('ppa-promote').onclick = () => this._promotePending();
    document.getElementById('ppa-detail-overlay').onclick = () => this._closeDetail();

    await this.refresh();
  },

  async refresh() {
    this.state.loading = true;
    this._renderStats();
    this._renderPayouts();
    this._renderList();

    try {
      const [listRes, payoutsRes] = await Promise.all([
        App.api._call('pixelpros_affiliates_list', { limit: 500 }),
        App.api._call('pixelpros_affiliate_prepare_payouts', {}),
      ]);
      if (listRes && listRes.ok) {
        this.state.affiliates = listRes.affiliates || [];
        this.state.counts = listRes.counts || this.state.counts;
      }
      if (payoutsRes && payoutsRes.ok) {
        this.state.payouts = payoutsRes.payouts || [];
        this.state.payouts_total_cents = payoutsRes.total_cents || 0;
      }
    } catch (err) {
      console.error('[PixelProsAffiliates] refresh', err);
    } finally {
      this.state.loading = false;
      this._renderStats();
      this._renderPayouts();
      this._renderList();
    }
  },

  // ─────────────────────────────────────────────────────────────────────
  // Compteurs
  // ─────────────────────────────────────────────────────────────────────
  _renderStats() {
    const c = this.state.counts || {};
    const totalActive = c.active || 0;
    const payoutsTotal = ((this.state.payouts_total_cents || 0) / 100).toLocaleString('fr-FR', {
      minimumFractionDigits: 2, maximumFractionDigits: 2,
    });
    const payoutsCount = (this.state.payouts || []).length;

    document.getElementById('ppa-stats').innerHTML = `
      <div class="ppa-stat">
        <div class="ppa-stat-label">AFFILIÉS ACTIFS</div>
        <div class="ppa-stat-value">${totalActive}</div>
        <div class="ppa-stat-sub">${c.pending || 0} pending · ${c.paused || 0} en pause</div>
      </div>
      <div class="ppa-stat is-money">
        <div class="ppa-stat-label">À VERSER CE MOIS-CI</div>
        <div class="ppa-stat-value">${payoutsTotal} €</div>
        <div class="ppa-stat-sub">${payoutsCount} affilié(s) éligible(s) (≥50 €)</div>
      </div>
      <div class="ppa-stat">
        <div class="ppa-stat-label">VENTES TOTAL</div>
        <div class="ppa-stat-value" id="ppa-stat-sales">—</div>
        <div class="ppa-stat-sub">depuis le lancement</div>
      </div>
    `;
    // Calcul lazy des ventes total
    if (!this._salesTotalFetched) {
      this._salesTotalFetched = true;
      App.api._call('pixelpros_affiliate_sales_list', { limit: 1000 }).then(res => {
        if (res && res.ok) {
          this.state.sales = res.sales || [];
          const el = document.getElementById('ppa-stat-sales');
          if (el) el.textContent = String(this.state.sales.length);
        }
      });
    }
  },

  // ─────────────────────────────────────────────────────────────────────
  // Paiements à préparer
  // ─────────────────────────────────────────────────────────────────────
  _renderPayouts() {
    const el = document.getElementById('ppa-payouts');
    if (!el) return;
    const payouts = this.state.payouts || [];

    if (!payouts.length) {
      el.innerHTML = `
        <div class="ppa-empty-card">
          <div class="ppa-empty-icon">💰</div>
          <h3>Aucun paiement à préparer</h3>
          <p>Aucun affilié n'a accumulé 50 € de commissions versables ce mois-ci. Reviens à la fin du mois.</p>
        </div>
      `;
      return;
    }

    const rows = payouts.map(p => {
      const total = (p.total_cents / 100).toLocaleString('fr-FR', {
        minimumFractionDigits: 2, maximumFractionDigits: 2
      });
      const methodLabel = p.payout_method === 'paypal' ? 'PayPal' : 'Virement';
      const target = p.payout_method === 'paypal'
        ? (p.paypal_email || '—')
        : (p.iban ? `${p.account_holder || ''} · ${this._maskIban(p.iban)}` : '—');
      return `
        <tr data-payout-aff="${p.affiliate_id}">
          <td>
            <strong>${this._esc(p.firstname || '')} ${this._esc(p.lastname || '')}</strong>
            <div class="ppa-cell-sub">${this._esc(p.email || '')}</div>
          </td>
          <td><span class="ppa-badge ${p.payout_method === 'paypal' ? 'is-paypal' : 'is-virement'}">${methodLabel}</span></td>
          <td class="ppa-cell-mono">${this._esc(target)}</td>
          <td class="ppa-cell-money">${total} €</td>
          <td>
            <button class="btn btn-primary btn-sm" data-mark-paid="${p.affiliate_id}">Marquer payé</button>
          </td>
        </tr>
      `;
    }).join('');

    el.innerHTML = `
      <div class="ppa-payouts-card">
        <div class="ppa-payouts-head">
          <div>
            <h2>💰 Paiements à préparer</h2>
            <p>Commissions versables (>30 j), groupées par affilié. Seuil 50 €.</p>
          </div>
          <button id="ppa-export-csv" class="btn btn-secondary">Exporter CSV</button>
        </div>
        <div class="ppa-table-wrap">
          <table class="ppa-table">
            <thead>
              <tr>
                <th>Affilié</th>
                <th>Méthode</th>
                <th>Destinataire</th>
                <th>Montant</th>
                <th></th>
              </tr>
            </thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
      </div>
    `;

    el.querySelectorAll('[data-mark-paid]').forEach(btn => {
      btn.onclick = () => this._markAffiliatePaid(btn.getAttribute('data-mark-paid'));
    });
    document.getElementById('ppa-export-csv').onclick = () => this._exportPayoutsCSV();
  },

  async _markAffiliatePaid(affId) {
    const p = (this.state.payouts || []).find(x => x.affiliate_id === affId);
    if (!p) return;
    const total = (p.total_cents / 100).toLocaleString('fr-FR', {
      minimumFractionDigits: 2, maximumFractionDigits: 2
    });
    if (!confirm(`Marquer ${total} € comme versés à ${p.firstname} ${p.lastname} ?\n\nÇa va clore ${p.sale_ids.length} commission(s).`)) return;
    const ref = prompt('Référence du virement (optionnel, ex : "Virement SEPA mai 2026")');
    try {
      const res = await App.api._call('pixelpros_affiliate_mark_sales_paid', {
        ids: p.sale_ids,
        batch_ref: ref || '',
      });
      if (res && res.ok) {
        await this.refresh();
        App.toast && App.toast.success(res.message || 'Versement enregistré.');
      } else {
        alert((res && res.error) || 'Erreur lors de l\'enregistrement.');
      }
    } catch (err) {
      alert(err.message || 'Erreur réseau.');
    }
  },

  _exportPayoutsCSV() {
    const payouts = this.state.payouts || [];
    if (!payouts.length) return;
    const header = ['Prenom', 'Nom', 'Email', 'Methode', 'IBAN', 'BIC', 'Titulaire', 'PayPal', 'Montant_EUR', 'Nb_ventes'];
    const rows = payouts.map(p => [
      p.firstname || '', p.lastname || '', p.email || '',
      p.payout_method || '',
      p.iban || '', p.bic || '', p.account_holder || '',
      p.paypal_email || '',
      (p.total_cents / 100).toFixed(2).replace('.', ','),
      String(p.sale_ids.length),
    ]);
    const csv = [header, ...rows].map(r => r.map(v => {
      const s = String(v ?? '');
      return s.includes(';') || s.includes('"') ? `"${s.replace(/"/g, '""')}"` : s;
    }).join(';')).join('\r\n');
    const blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `paiements_affilies_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  },

  // ─────────────────────────────────────────────────────────────────────
  // Liste des affiliés
  // ─────────────────────────────────────────────────────────────────────
  _renderList() {
    const wrap = document.getElementById('ppa-list-wrap');
    if (!wrap) return;

    const search = (this.state.search || '').toLowerCase();
    const filtered = (this.state.affiliates || []).filter(a => {
      if (!search) return true;
      return [a.firstname, a.lastname, a.email, a.ref_code]
        .filter(Boolean).join(' ').toLowerCase().includes(search);
    });

    if (this.state.loading && !this.state.affiliates.length) {
      wrap.innerHTML = '<div class="ppa-empty-card"><p>Chargement…</p></div>';
      return;
    }

    if (!this.state.affiliates.length) {
      wrap.innerHTML = `
        <div class="ppa-empty-card">
          <div class="ppa-empty-icon">🚀</div>
          <h3>Aucun affilié inscrit pour l'instant</h3>
          <p>La page <code>pixel-pros.fr/affiliation.html</code> est en ligne et prête à recevoir des inscriptions.</p>
        </div>
      `;
      return;
    }

    const rows = filtered.map(a => {
      const statusBadge = ({
        active: '<span class="ppa-badge is-ok">Actif</span>',
        pending: '<span class="ppa-badge is-pending">Pending</span>',
        paused: '<span class="ppa-badge is-paused">En pause</span>',
        banned: '<span class="ppa-badge is-banned">Banni</span>',
      })[a.status] || `<span class="ppa-badge">${a.status}</span>`;
      const date = this._fmtDate(a.created_at);
      return `
        <tr data-aff-id="${a.id}" class="ppa-row-clickable">
          <td>
            <strong>${this._esc(a.firstname || '')} ${this._esc(a.lastname || '')}</strong>
            <div class="ppa-cell-sub">${this._esc(a.email || '')}</div>
          </td>
          <td><code class="ppa-code">${this._esc(a.ref_code || '')}</code></td>
          <td>${statusBadge}</td>
          <td>${a.payout_method === 'paypal' ? 'PayPal' : 'Virement'}</td>
          <td class="ppa-cell-sub">${date}</td>
        </tr>
      `;
    }).join('');

    wrap.innerHTML = `
      <div class="ppa-payouts-card">
        <div class="ppa-payouts-head">
          <div>
            <h2>👥 Tous les affiliés</h2>
            <p>${filtered.length} affilié(s) listé(s). Clique sur une ligne pour voir le détail.</p>
          </div>
          <input id="ppa-search" type="search" value="${this._esc(this.state.search || '')}"
                 placeholder="Rechercher (nom, email, code)"
                 style="padding:9px 14px; border-radius:8px; background:var(--surface, #0f172a); border:1px solid var(--border, #1e293b); color:#cbd5e1; font-size:13px; width:240px;" />
        </div>
        <div class="ppa-table-wrap">
          <table class="ppa-table">
            <thead>
              <tr>
                <th>Affilié</th>
                <th>Code</th>
                <th>Status</th>
                <th>Paiement</th>
                <th>Inscrit le</th>
              </tr>
            </thead>
            <tbody>${rows || '<tr><td colspan="5" class="ppa-empty-mini">Aucun résultat.</td></tr>'}</tbody>
          </table>
        </div>
      </div>
    `;

    const searchInput = document.getElementById('ppa-search');
    if (searchInput) {
      searchInput.oninput = (e) => {
        this.state.search = e.target.value;
        this._renderList();
      };
    }

    wrap.querySelectorAll('[data-aff-id]').forEach(tr => {
      tr.onclick = () => this._openDetail(tr.getAttribute('data-aff-id'));
    });
  },

  // ─────────────────────────────────────────────────────────────────────
  // Détail d'un affilié (panneau slide-in)
  // ─────────────────────────────────────────────────────────────────────
  async _openDetail(affId) {
    this.state.selectedId = affId;
    const overlay = document.getElementById('ppa-detail-overlay');
    const panel = document.getElementById('ppa-detail');
    overlay.hidden = false;
    panel.hidden = false;
    panel.innerHTML = '<div class="p-6">Chargement…</div>';

    try {
      const res = await App.api._call('pixelpros_affiliate_get', { id: affId });
      if (res && res.ok) {
        this.state.detail = res;
        this._renderDetail(res);
      } else {
        panel.innerHTML = `<div class="p-6">Erreur : ${(res && res.error) || 'inconnue'}</div>`;
      }
    } catch (err) {
      panel.innerHTML = `<div class="p-6">Erreur réseau : ${this._esc(err.message)}</div>`;
    }
  },

  _renderDetail({ affiliate: a, stats: s, sales }) {
    const panel = document.getElementById('ppa-detail');
    if (!panel) return;
    const fullName = `${a.firstname || ''} ${a.lastname || ''}`.trim();
    const payoutInfo = a.payout_method === 'paypal'
      ? `PayPal · ${this._esc(a.paypal_email || '')}`
      : `Virement · ${this._esc(a.account_holder || '')} · ${this._maskIban(a.iban || '')}`;

    const salesRows = (sales || []).map(sale => {
      const cents = (sale.commission_cents / 100).toLocaleString('fr-FR', { minimumFractionDigits: 2 });
      const status = ({
        pending: '<span class="ppa-badge is-pending">Pending</span>',
        available: '<span class="ppa-badge is-ok">Versable</span>',
        paid: '<span class="ppa-badge is-paid">Versée</span>',
        cancelled: '<span class="ppa-badge is-banned">Annulée</span>',
      })[sale.payout_status] || sale.payout_status;
      const date = this._fmtDate(sale.created_at);
      return `
        <tr>
          <td>${date}</td>
          <td>${(sale.gross_amount_cents/100).toLocaleString('fr-FR', { minimumFractionDigits: 2 })} €</td>
          <td><strong>${cents} €</strong></td>
          <td>${status}</td>
          <td>
            ${sale.payout_status === 'pending' || sale.payout_status === 'available'
              ? `<button class="btn btn-sm btn-secondary" data-cancel-sale="${sale.id}">Annuler</button>` : ''}
          </td>
        </tr>
      `;
    }).join('');

    panel.innerHTML = `
      <div class="ppa-detail-head">
        <div>
          <div class="ppa-detail-name">${this._esc(fullName)}</div>
          <div class="ppa-detail-email">${this._esc(a.email || '')}</div>
        </div>
        <button class="ppa-detail-close" data-close-detail>✕</button>
      </div>

      <div class="ppa-detail-body">
        <div class="ppa-detail-stats">
          <div><div class="ppa-detail-stat-label">CLICS</div><div class="ppa-detail-stat-value">${s.clicks_total || 0}</div></div>
          <div><div class="ppa-detail-stat-label">VENTES</div><div class="ppa-detail-stat-value">${(s.sales_pending || 0) + (s.sales_available || 0) + (s.sales_paid || 0)}</div></div>
          <div><div class="ppa-detail-stat-label">À VERSER</div><div class="ppa-detail-stat-value">${((s.commission_pending_cents + s.commission_available_cents) / 100).toLocaleString('fr-FR', { minimumFractionDigits: 2 })} €</div></div>
          <div><div class="ppa-detail-stat-label">VERSÉ</div><div class="ppa-detail-stat-value">${(s.commission_paid_cents / 100).toLocaleString('fr-FR', { minimumFractionDigits: 2 })} €</div></div>
        </div>

        <div class="ppa-detail-section">
          <h3>Informations</h3>
          <div class="ppa-detail-grid">
            <div><span class="lbl">Code</span><code>${this._esc(a.ref_code || '')}</code></div>
            <div><span class="lbl">Status</span>${this._statusBadge(a.status)}</div>
            <div><span class="lbl">Paiement</span>${payoutInfo}</div>
            <div><span class="lbl">Inscrit le</span>${this._fmtDate(a.created_at)}</div>
            ${a.promotion_method ? `<div class="col-span-2"><span class="lbl">Promotion prévue</span>${this._esc(a.promotion_method)}</div>` : ''}
          </div>
        </div>

        <div class="ppa-detail-section">
          <h3>Actions</h3>
          <div class="flex gap-2 flex-wrap">
            ${a.status === 'active' ? '<button class="btn btn-secondary btn-sm" data-set-status="paused">Mettre en pause</button>' : ''}
            ${a.status === 'paused' ? '<button class="btn btn-primary btn-sm" data-set-status="active">Réactiver</button>' : ''}
            ${a.status !== 'banned' ? '<button class="btn btn-secondary btn-sm" data-set-status="banned" style="color:#ef4444;">Bannir</button>' : ''}
            ${a.status === 'banned' ? '<button class="btn btn-primary btn-sm" data-set-status="active">Lever le bannissement</button>' : ''}
          </div>
        </div>

        <div class="ppa-detail-section">
          <h3>Historique des ventes (${(sales || []).length})</h3>
          <div class="ppa-table-wrap">
            <table class="ppa-table">
              <thead><tr><th>Date</th><th>Vente</th><th>Commission</th><th>Status</th><th></th></tr></thead>
              <tbody>${salesRows || '<tr><td colspan="5" class="ppa-empty-mini">Aucune vente pour l\'instant.</td></tr>'}</tbody>
            </table>
          </div>
        </div>
      </div>
    `;

    panel.querySelector('[data-close-detail]').onclick = () => this._closeDetail();
    panel.querySelectorAll('[data-set-status]').forEach(btn => {
      btn.onclick = () => this._setStatus(a.id, btn.getAttribute('data-set-status'));
    });
    panel.querySelectorAll('[data-cancel-sale]').forEach(btn => {
      btn.onclick = () => this._cancelSale(btn.getAttribute('data-cancel-sale'));
    });
  },

  async _setStatus(affId, status) {
    if (!confirm(`Passer le status de cet affilié en "${status}" ?`)) return;
    try {
      const res = await App.api._call('pixelpros_affiliate_set_status', { id: affId, status });
      if (res && res.ok) {
        await this.refresh();
        await this._openDetail(affId);
        App.toast && App.toast.success(res.message);
      } else {
        alert((res && res.error) || 'Erreur');
      }
    } catch (err) {
      alert(err.message);
    }
  },

  async _cancelSale(saleId) {
    const reason = prompt('Raison de l\'annulation (ex: "remboursement Stripe") :');
    if (reason === null) return;
    try {
      const res = await App.api._call('pixelpros_affiliate_cancel_sale', { id: saleId, reason });
      if (res && res.ok) {
        await this._openDetail(this.state.selectedId);
        App.toast && App.toast.success('Commission annulée.');
      } else {
        alert((res && res.error) || 'Erreur');
      }
    } catch (err) {
      alert(err.message);
    }
  },

  async _promotePending() {
    if (!confirm('Passer en "versable" toutes les commissions pending de plus de 30 jours ?')) return;
    try {
      const res = await App.api._call('pixelpros_affiliate_promote_pending', { min_age_days: 30 });
      if (res && res.ok) {
        await this.refresh();
        App.toast && App.toast.success(res.message);
      } else {
        alert((res && res.error) || 'Erreur');
      }
    } catch (err) {
      alert(err.message);
    }
  },

  _closeDetail() {
    const overlay = document.getElementById('ppa-detail-overlay');
    const panel = document.getElementById('ppa-detail');
    if (overlay) overlay.hidden = true;
    if (panel) panel.hidden = true;
    this.state.selectedId = null;
  },

  // ─────────────────────────────────────────────────────────────────────
  // Helpers
  // ─────────────────────────────────────────────────────────────────────
  _esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'
    }[c]));
  },
  _fmtDate(iso) {
    if (!iso) return '—';
    try {
      return new Date(iso).toLocaleDateString('fr-FR', {
        day: '2-digit', month: 'short', year: 'numeric'
      });
    } catch (_) { return String(iso).slice(0, 10); }
  },
  _maskIban(iban) {
    const s = String(iban || '').replace(/\s/g, '');
    if (s.length < 8) return s;
    return s.slice(0, 4) + '…' + s.slice(-4);
  },
  _statusBadge(s) {
    return ({
      active: '<span class="ppa-badge is-ok">Actif</span>',
      pending: '<span class="ppa-badge is-pending">Pending</span>',
      paused: '<span class="ppa-badge is-paused">En pause</span>',
      banned: '<span class="ppa-badge is-banned">Banni</span>',
    })[s] || `<span class="ppa-badge">${s}</span>`;
  },

  // ─────────────────────────────────────────────────────────────────────
  // CSS
  // ─────────────────────────────────────────────────────────────────────
  _injectStyles() {
    if (document.getElementById('ppa-styles')) return;
    const css = `
      .ppa-stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px; }
      .ppa-stat { background: var(--surface, #0f172a); border: 1px solid var(--border, #1e293b);
                  border-radius: 12px; padding: 18px 20px; }
      .ppa-stat.is-money { background: linear-gradient(135deg, #facc15 0%, #f59e0b 100%); border-color: #facc15; color: #0b0d1a; }
      .ppa-stat-label { font-size: 10px; font-weight: 700; letter-spacing: 0.05em; opacity: 0.7; margin-bottom: 8px; }
      .ppa-stat-value { font-size: 28px; font-weight: 800; line-height: 1; margin-bottom: 4px; }
      .ppa-stat-sub { font-size: 12px; opacity: 0.7; }

      .ppa-empty-card { background: var(--surface, #0f172a); border: 1px dashed var(--border, #1e293b);
                       border-radius: 12px; padding: 40px 28px; text-align: center; color: #94a3b8; }
      .ppa-empty-icon { font-size: 36px; margin-bottom: 12px; }
      .ppa-empty-card h3 { color: #e2e8f0; font-size: 17px; font-weight: 700; margin-bottom: 6px; }
      .ppa-empty-card p { font-size: 14px; line-height: 1.5; }

      .ppa-payouts-card { background: var(--surface, #0f172a); border: 1px solid var(--border, #1e293b);
                          border-radius: 12px; overflow: hidden; }
      .ppa-payouts-head { display: flex; justify-content: space-between; align-items: flex-end;
                          padding: 18px 20px; gap: 16px; flex-wrap: wrap; border-bottom: 1px solid var(--border, #1e293b); }
      .ppa-payouts-head h2 { font-size: 17px; font-weight: 700; color: #e2e8f0; margin: 0 0 4px; }
      .ppa-payouts-head p { font-size: 13px; color: #94a3b8; margin: 0; }

      .ppa-table-wrap { overflow-x: auto; }
      .ppa-table { width: 100%; border-collapse: collapse; font-size: 14px; }
      .ppa-table th { text-align: left; padding: 12px 16px; font-size: 11px; font-weight: 700;
                      letter-spacing: 0.05em; color: #94a3b8; border-bottom: 1px solid var(--border, #1e293b); }
      .ppa-table td { padding: 12px 16px; border-bottom: 1px solid var(--border, #1e293b); color: #cbd5e1; vertical-align: middle; }
      .ppa-table tr:last-child td { border-bottom: none; }
      .ppa-cell-sub { font-size: 12px; color: #64748b; margin-top: 2px; }
      .ppa-cell-mono { font-family: 'JetBrains Mono', monospace; font-size: 13px; }
      .ppa-cell-money { font-weight: 700; color: #facc15; }
      .ppa-empty-mini { padding: 20px; text-align: center; color: #64748b; }
      .ppa-row-clickable:hover { background: rgba(250, 204, 21, 0.05); cursor: pointer; }

      .ppa-code { background: rgba(250, 204, 21, 0.12); color: #facc15; padding: 3px 8px;
                  border-radius: 4px; font-family: 'JetBrains Mono', monospace; font-size: 12px; }

      .ppa-badge { display: inline-block; padding: 3px 10px; border-radius: 999px;
                   font-size: 11px; font-weight: 700; letter-spacing: 0.02em; }
      .ppa-badge.is-ok       { background: rgba(34, 197, 94, 0.15); color: #22c55e; }
      .ppa-badge.is-paid     { background: rgba(34, 197, 94, 0.25); color: #16a34a; }
      .ppa-badge.is-pending  { background: rgba(250, 204, 21, 0.15); color: #facc15; }
      .ppa-badge.is-paused   { background: rgba(148, 163, 184, 0.18); color: #94a3b8; }
      .ppa-badge.is-banned   { background: rgba(239, 68, 68, 0.15); color: #ef4444; }
      .ppa-badge.is-paypal   { background: rgba(14, 165, 233, 0.15); color: #0ea5e9; }
      .ppa-badge.is-virement { background: rgba(168, 85, 247, 0.15); color: #a855f7; }

      .btn-sm { padding: 6px 12px; font-size: 12px; }

      /* Détail (slide-in) */
      .ppa-detail-head { padding: 20px 24px; border-bottom: 1px solid var(--border, #1e293b);
                          display: flex; justify-content: space-between; align-items: center; }
      .ppa-detail-name { font-size: 20px; font-weight: 800; color: #e2e8f0; }
      .ppa-detail-email { font-size: 13px; color: #64748b; margin-top: 2px; }
      .ppa-detail-close { background: transparent; border: 1px solid var(--border, #1e293b);
                          color: #cbd5e1; width: 32px; height: 32px; border-radius: 8px; cursor: pointer; }
      .ppa-detail-close:hover { background: rgba(255,255,255,0.05); }
      .ppa-detail-body { padding: 20px 24px; overflow-y: auto; flex: 1; }
      .ppa-detail-stats { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; margin-bottom: 24px; }
      .ppa-detail-stat-label { font-size: 10px; font-weight: 700; color: #64748b; letter-spacing: 0.05em; }
      .ppa-detail-stat-value { font-size: 22px; font-weight: 800; color: #e2e8f0; margin-top: 4px; }
      .ppa-detail-section { margin-bottom: 28px; }
      .ppa-detail-section h3 { font-size: 13px; font-weight: 700; color: #facc15;
                                letter-spacing: 0.05em; margin-bottom: 12px;
                                padding-bottom: 8px; border-bottom: 1px solid var(--border, #1e293b); }
      .ppa-detail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; font-size: 13px; color: #cbd5e1; }
      .ppa-detail-grid .lbl { display: block; font-size: 11px; color: #64748b; margin-bottom: 4px; }
      .ppa-detail-grid .col-span-2 { grid-column: span 2; }
    `;
    const style = document.createElement('style');
    style.id = 'ppa-styles';
    style.textContent = css;
    document.head.appendChild(style);
  },
};
