/* Vue Pixel Pros · Affiliés — backoffice du programme d'affiliation.
 *
 * 3 zones :
 *   1. Cartes synthétiques (compteurs : actifs / ventes en attente / à verser / déjà versé)
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
    listError: false,     // échec du chargement de la liste → état d'erreur explicite
    payoutsError: false,  // échec du calcul des paiements → état d'erreur explicite
  },

  // Libellés français des statuts (utilisés partout : badges, confirmations…)
  STATUS_LABELS: {
    active: 'Actif',
    pending: 'En attente',
    paused: 'En pause',
    banned: 'Banni',
  },

  async render(container) {
    this._root = container;
    container.innerHTML = `
      <section class="animate-slide-up">
        <div class="mb-6 flex items-end justify-between flex-wrap gap-3">
          <div>
            <div class="hero-kicker mb-2">PIXEL PROS · AFFILIÉS</div>
            <h1 class="hero-title hero-title--md mb-2">Programme d'affiliation.</h1>
            <p class="hero-subtitle">20 % de commission sur 12 mois. Suivi des ventes, paiements à préparer, gestion des comptes.</p>
          </div>
          <div class="flex items-center gap-2">
            <button id="ppa-promote" class="btn btn-secondary" title="Une commission attend 30 jours avant d'être payable — le temps d'être sûr que le client ne se fait pas rembourser. Ce bouton rend payables celles qui ont passé ce délai.">
              ⏰ Libérer les commissions (30 j et +)
            </button>
            <button id="ppa-refresh" class="btn btn-secondary">↻ Rafraîchir</button>
          </div>
        </div>

        <div id="ppa-stats" class="ppa-stats mb-6"></div>
        <div id="ppa-payouts" class="mb-7"></div>
        <div id="ppa-list-wrap"></div>
        <div id="ppa-detail-overlay" class="pp-detail-overlay" hidden></div>
        <aside id="ppa-detail" class="pp-detail-panel" hidden role="dialog" aria-label="Fiche affilié"></aside>
      </section>
    `;
    this._injectStyles();

    document.getElementById('ppa-refresh').onclick = () => this.refresh();
    document.getElementById('ppa-promote').onclick = () => this._promotePending();
    document.getElementById('ppa-detail-overlay').onclick = () => this._closeDetail();
    // Si on quitte la vue avec le panneau ouvert, on retire l'écouteur Échap
    App.onViewCleanup(() => this._closeDetail());

    await this.refresh();
  },

  async refresh() {
    this.state.loading = true;
    // Le total des ventes est recalculé à CHAQUE rafraîchissement
    // (avant : figé pour toujours après le premier passage).
    this._salesTotalFetched = false;
    this._renderStats();
    this._renderPayouts();
    this._renderList();

    if (!App.api) {
      this.state.loading = false;
      this.state.listError = true;
      this.state.payoutsError = true;
      this._renderStats();
      this._renderPayouts();
      this._renderList();
      return;
    }

    // Chaque appel capture son échec au lieu de faire tomber l'autre.
    const safe = (p) => p.catch(err => ({ ok: false, _thrown: err }));
    const [listRes, payoutsRes] = await Promise.all([
      safe(App.api.pixelpros_affiliates_list({ limit: 500 })),
      safe(App.api.pixelpros_affiliate_prepare_payouts({})),
    ]);

    this.state.listError = !(listRes && listRes.ok);
    this.state.payoutsError = !(payoutsRes && payoutsRes.ok);

    if (!this.state.listError) {
      this.state.affiliates = listRes.affiliates || [];
      this.state.counts = listRes.counts || this.state.counts;
    }
    if (!this.state.payoutsError) {
      this.state.payouts = payoutsRes.payouts || [];
      this.state.payouts_total_cents = payoutsRes.total_cents || 0;
    }
    if (this.state.listError || this.state.payoutsError) {
      const bad = this.state.listError ? listRes : payoutsRes;
      console.error('[PixelProsAffiliates] refresh', bad && (bad._thrown || bad.error || bad));
      Toast.friendlyError(bad && (bad._thrown || bad), 'Impossible de charger les affiliés.');
    }

    this.state.loading = false;
    this._renderStats();
    this._renderPayouts();
    this._renderList();
  },

  // ─────────────────────────────────────────────────────────────────────
  // Compteurs
  // ─────────────────────────────────────────────────────────────────────
  _renderStats() {
    const el = document.getElementById('ppa-stats');
    if (!el) return;
    const c = this.state.counts || {};
    const freshLoading = this.state.loading && !this.state.affiliates.length && !this.state.listError;
    const totalActive = this.state.listError ? '—' : (freshLoading ? '…' : (c.active || 0));
    const activeSub = this.state.listError
      ? 'chargement impossible'
      : `${c.pending || 0} en attente · ${c.paused || 0} en pause`;
    const payoutsTotal = this.state.payoutsError ? '—' : (
      ((this.state.payouts_total_cents || 0) / 100).toLocaleString('fr-FR', {
        minimumFractionDigits: 2, maximumFractionDigits: 2,
      }) + ' €'
    );
    const payoutsCount = (this.state.payouts || []).length;
    const payoutsSub = this.state.payoutsError
      ? 'chargement impossible'
      : `${payoutsCount} affilié(s) éligible(s) (≥50 €)`;

    el.innerHTML = `
      <div class="ppa-stat">
        <div class="ppa-stat-label">AFFILIÉS ACTIFS</div>
        <div class="ppa-stat-value">${totalActive}</div>
        <div class="ppa-stat-sub">${activeSub}</div>
      </div>
      <div class="ppa-stat is-money">
        <div class="ppa-stat-label">À VERSER CE MOIS-CI</div>
        <div class="ppa-stat-value">${payoutsTotal}</div>
        <div class="ppa-stat-sub">${payoutsSub}</div>
      </div>
      <div class="ppa-stat">
        <div class="ppa-stat-label">VENTES TOTAL</div>
        <div class="ppa-stat-value" id="ppa-stat-sales">${this._salesCount != null ? this._salesCount : '—'}</div>
        <div class="ppa-stat-sub">depuis le lancement</div>
      </div>
    `;
    // Calcul à part des ventes total (requête plus lourde)
    if (!this._salesTotalFetched && App.api) {
      this._salesTotalFetched = true;
      App.api.pixelpros_affiliate_sales_list({ limit: 1000 }).then(res => {
        const slot = document.getElementById('ppa-stat-sales');
        if (res && res.ok) {
          this.state.sales = res.sales || [];
          this._salesCount = this.state.sales.length;
          if (slot) slot.textContent = String(this._salesCount);
        } else {
          this._salesCount = null;
          if (slot) {
            slot.textContent = '?';
            slot.title = 'Chargement impossible — clique sur Rafraîchir pour réessayer';
          }
          console.warn('[PixelProsAffiliates] ventes total', res && res.error);
        }
      }).catch(err => {
        this._salesCount = null;
        const slot = document.getElementById('ppa-stat-sales');
        if (slot) {
          slot.textContent = '?';
          slot.title = 'Chargement impossible — clique sur Rafraîchir pour réessayer';
        }
        console.warn('[PixelProsAffiliates] ventes total', err);
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

    if (this.state.payoutsError) {
      el.innerHTML = `
        <div class="ppa-error-card">
          <h3>Impossible de calculer les paiements à préparer</h3>
          <p>Le serveur n'a pas répondu. Réessaie dans un instant.</p>
          <button class="btn btn-secondary mt-3" data-retry-payouts>Réessayer</button>
        </div>
      `;
      const retry = el.querySelector('[data-retry-payouts]');
      if (retry) retry.onclick = () => this.refresh();
      return;
    }

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
            <p>Les commissions à payer maintenant : gagnées il y a plus de 30 jours
            (délai de sécurité anti-remboursement), groupées par affilié, dès que
            son total atteint 50 €.</p>
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
      btn.onclick = () => this._markAffiliatePaid(btn.getAttribute('data-mark-paid'), btn);
    });
    document.getElementById('ppa-export-csv').onclick = () => this._exportPayoutsCSV();
  },

  async _markAffiliatePaid(affId, btn) {
    const p = (this.state.payouts || []).find(x => x.affiliate_id === affId);
    if (!p) return;
    const total = (p.total_cents / 100).toLocaleString('fr-FR', {
      minimumFractionDigits: 2, maximumFractionDigits: 2
    });
    const ok = await Dialog.confirm(
      `Marquer ${total} € comme versés à ${p.firstname || ''} ${p.lastname || ''} ? Ça va clore ${p.sale_ids.length} commission(s).`,
      { title: 'Paiement affilié', okLabel: 'Marquer payé' }
    );
    if (!ok) return;
    const ref = prompt('Référence du virement (optionnel, ex : "Virement SEPA mai 2026")');
    if (ref === null) return; // Annuler = on ne fait rien
    if (btn) { btn.disabled = true; btn.textContent = 'Enregistrement…'; }
    try {
      const res = await App.api.pixelpros_affiliate_mark_sales_paid({
        ids: p.sale_ids,
        batch_ref: ref || '',
      });
      if (res && res.ok) {
        Toast.success(res.message || 'Versement enregistré.');
        await this.refresh();
      } else {
        Toast.friendlyError(res, 'Impossible d’enregistrer le versement.');
        if (btn) { btn.disabled = false; btn.textContent = 'Marquer payé'; }
      }
    } catch (err) {
      Toast.friendlyError(err, 'Impossible d’enregistrer le versement.');
      if (btn) { btn.disabled = false; btn.textContent = 'Marquer payé'; }
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

    // Échec de chargement → état d'erreur EXPLICITE (jamais un faux
    // "Aucun affilié" rassurant alors que le serveur n'a pas répondu).
    if (this.state.listError) {
      wrap.innerHTML = `
        <div class="ppa-error-card">
          <div class="ppa-empty-icon">⚠️</div>
          <h3>Impossible de charger les affiliés</h3>
          <p>Le serveur n'a pas répondu correctement. Vérifie ta connexion, puis réessaie.</p>
          <button id="ppa-retry" class="btn btn-primary mt-3">Réessayer</button>
        </div>
      `;
      const retry = document.getElementById('ppa-retry');
      if (retry) retry.onclick = () => this.refresh();
      return;
    }

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
          <p>La page Affiliation du site Pixel Pros est en ligne et prête à recevoir des inscriptions.</p>
        </div>
      `;
      return;
    }

    const rows = filtered.map(a => {
      const date = this._fmtDate(a.created_at);
      return `
        <tr data-aff-id="${this._esc(a.id)}" class="ppa-row-clickable" role="button" tabindex="0"
            title="Voir le détail de cet affilié">
          <td>
            <strong>${this._esc(a.firstname || '')} ${this._esc(a.lastname || '')}</strong>
            <div class="ppa-cell-sub">${this._esc(a.email || '')}</div>
          </td>
          <td><code class="ppa-code">${this._esc(a.ref_code || '')}</code></td>
          <td>${this._statusBadge(a.status)}</td>
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
                 style="padding:9px 14px; border-radius:8px; background:hsl(var(--bg)); border:1px solid hsl(var(--border)); color:hsl(var(--text)); font-size:13px; width:240px;" />
        </div>
        <div class="ppa-table-wrap">
          <table class="ppa-table">
            <thead>
              <tr>
                <th>Affilié</th>
                <th>Code</th>
                <th>Statut</th>
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
        // On rend la main au champ après le re-rendu (sinon le focus saute)
        const again = document.getElementById('ppa-search');
        if (again) {
          again.focus();
          again.setSelectionRange(again.value.length, again.value.length);
        }
      };
    }

    wrap.querySelectorAll('[data-aff-id]').forEach(tr => {
      const open = () => this._openDetail(tr.getAttribute('data-aff-id'));
      tr.onclick = open;
      tr.onkeydown = (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); }
      };
    });
  },

  // ─────────────────────────────────────────────────────────────────────
  // Détail d'un affilié (panneau slide-in)
  // ─────────────────────────────────────────────────────────────────────
  async _openDetail(affId) {
    this.state.selectedId = affId;
    const overlay = document.getElementById('ppa-detail-overlay');
    const panel = document.getElementById('ppa-detail');
    if (!overlay || !panel) return;
    overlay.hidden = false;
    panel.hidden = false;
    panel.innerHTML = '<div class="p-6">Chargement…</div>';

    // Échap ferme le panneau (écouteur retiré à la fermeture)
    if (!this._escHandler) {
      this._escHandler = (e) => { if (e.key === 'Escape') this._closeDetail(); };
      document.addEventListener('keydown', this._escHandler);
    }

    try {
      const res = await App.api.pixelpros_affiliate_get({ id: affId });
      if (res && res.ok) {
        this.state.detail = res;
        this._renderDetail(res);
      } else {
        this._renderDetailError(affId, (res && res.error) || 'réponse vide du serveur');
      }
    } catch (err) {
      this._renderDetailError(affId, err && err.message);
    }
  },

  _renderDetailError(affId, detail) {
    const panel = document.getElementById('ppa-detail');
    if (!panel) return;
    console.warn('[PixelProsAffiliates] détail', detail);
    panel.innerHTML = `
      <div class="p-6">
        <p class="mb-2" style="font-weight:700;">Impossible de charger cette fiche.</p>
        <p class="ppa-detail-email mb-4">${this._esc(detail || '')}</p>
        <div class="flex gap-2">
          <button class="btn btn-primary btn-sm" data-retry-detail>Réessayer</button>
          <button class="btn btn-secondary btn-sm" data-close-detail aria-label="Fermer la fiche">Fermer</button>
        </div>
      </div>
    `;
    const retry = panel.querySelector('[data-retry-detail]');
    if (retry) retry.onclick = () => this._openDetail(affId);
    const close = panel.querySelector('[data-close-detail]');
    if (close) close.onclick = () => this._closeDetail();
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
        pending: '<span class="ppa-badge is-pending">En attente</span>',
        available: '<span class="ppa-badge is-ok">Versable</span>',
        paid: '<span class="ppa-badge is-paid">Versée</span>',
        cancelled: '<span class="ppa-badge is-banned">Annulée</span>',
      })[sale.payout_status] || this._esc(sale.payout_status);
      const date = this._fmtDate(sale.created_at);
      return `
        <tr>
          <td>${date}</td>
          <td>${(sale.gross_amount_cents/100).toLocaleString('fr-FR', { minimumFractionDigits: 2 })} €</td>
          <td><strong>${cents} €</strong></td>
          <td>${status}</td>
          <td>
            ${sale.payout_status === 'pending' || sale.payout_status === 'available'
              ? `<button class="btn btn-sm btn-secondary" data-cancel-sale="${this._esc(sale.id)}">Annuler</button>` : ''}
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
        <button class="ppa-detail-close" data-close-detail aria-label="Fermer la fiche" title="Fermer (Échap)">✕</button>
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
            <div><span class="lbl">Statut</span>${this._statusBadge(a.status)}</div>
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
            ${a.status !== 'banned' ? '<button class="btn btn-secondary btn-sm ppa-btn-danger" data-set-status="banned">Bannir</button>' : ''}
            ${a.status === 'banned' ? '<button class="btn btn-primary btn-sm" data-set-status="active">Lever le bannissement</button>' : ''}
          </div>
        </div>

        <div class="ppa-detail-section">
          <h3>Historique des ventes (${(sales || []).length})</h3>
          <div class="ppa-table-wrap">
            <table class="ppa-table">
              <thead><tr><th>Date</th><th>Vente</th><th>Commission</th><th>Statut</th><th></th></tr></thead>
              <tbody>${salesRows || '<tr><td colspan="5" class="ppa-empty-mini">Aucune vente pour l’instant.</td></tr>'}</tbody>
            </table>
          </div>
        </div>
      </div>
    `;

    const closeBtn = panel.querySelector('[data-close-detail]');
    closeBtn.onclick = () => this._closeDetail();
    closeBtn.focus();
    panel.querySelectorAll('[data-set-status]').forEach(btn => {
      btn.onclick = () => this._setStatus(a.id, btn.getAttribute('data-set-status'), btn);
    });
    panel.querySelectorAll('[data-cancel-sale]').forEach(btn => {
      btn.onclick = () => this._cancelSale(btn.getAttribute('data-cancel-sale'), btn);
    });
  },

  async _setStatus(affId, status, btn) {
    const messages = {
      active: 'Réactiver cet affilié ? Ses commissions recommenceront à compter.',
      paused: 'Mettre cet affilié en pause ?',
      banned: 'Bannir cet affilié ? Il ne touchera plus de commissions.',
    };
    const okLabels = { active: 'Réactiver', paused: 'Mettre en pause', banned: 'Bannir' };
    const ok = await Dialog.confirm(messages[status] || 'Changer le statut de cet affilié ?', {
      title: 'Affiliés',
      okLabel: okLabels[status] || 'Confirmer',
      danger: status === 'banned',
    });
    if (!ok) return;
    if (btn) btn.disabled = true;
    try {
      const res = await App.api.pixelpros_affiliate_set_status({ id: affId, status });
      if (res && res.ok) {
        Toast.success(res.message || `Affilié ${(this.STATUS_LABELS[status] || status).toLowerCase()}.`);
        await this.refresh();
        await this._openDetail(affId);
      } else {
        Toast.friendlyError(res, 'Impossible de changer le statut.');
        if (btn) btn.disabled = false;
      }
    } catch (err) {
      Toast.friendlyError(err, 'Impossible de changer le statut.');
      if (btn) btn.disabled = false;
    }
  },

  async _cancelSale(saleId, btn) {
    const reason = prompt('Raison de l’annulation (ex : "remboursement du client") :');
    if (reason === null) return; // Annuler = on ne fait rien
    if (btn) btn.disabled = true;
    try {
      const res = await App.api.pixelpros_affiliate_cancel_sale({ id: saleId, reason });
      if (res && res.ok) {
        Toast.success('Commission annulée.');
        await this._openDetail(this.state.selectedId);
      } else {
        Toast.friendlyError(res, 'Impossible d’annuler cette commission.');
        if (btn) btn.disabled = false;
      }
    } catch (err) {
      Toast.friendlyError(err, 'Impossible d’annuler cette commission.');
      if (btn) btn.disabled = false;
    }
  },

  async _promotePending() {
    const ok = await Dialog.confirm(
      'Rendre payables toutes les commissions gagnées il y a plus de 30 jours ? '
      + '(Le délai de 30 jours protège contre les remboursements clients : '
      + 'on ne paie un parrain que sur des ventes confirmées.)',
      { title: 'Libérer les commissions', okLabel: 'Libérer', cancelLabel: 'Annuler' }
    );
    if (!ok) return;
    const btn = document.getElementById('ppa-promote');
    if (btn) btn.disabled = true;
    try {
      const res = await App.api.pixelpros_affiliate_promote_pending({ min_age_days: 30 });
      if (res && res.ok) {
        Toast.success(res.message || 'Commissions libérées.');
        await this.refresh();
      } else {
        Toast.friendlyError(res, 'Impossible de libérer les commissions.');
      }
    } catch (err) {
      Toast.friendlyError(err, 'Impossible de libérer les commissions.');
    } finally {
      if (btn) btn.disabled = false;
    }
  },

  _closeDetail() {
    const overlay = document.getElementById('ppa-detail-overlay');
    const panel = document.getElementById('ppa-detail');
    if (overlay) overlay.hidden = true;
    if (panel) panel.hidden = true;
    this.state.selectedId = null;
    if (this._escHandler) {
      document.removeEventListener('keydown', this._escHandler);
      this._escHandler = null;
    }
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
      pending: '<span class="ppa-badge is-pending">En attente</span>',
      paused: '<span class="ppa-badge is-paused">En pause</span>',
      banned: '<span class="ppa-badge is-banned">Banni</span>',
    })[s] || `<span class="ppa-badge">${this._esc(s)}</span>`;
  },

  // ─────────────────────────────────────────────────────────────────────
  // CSS — tout en tokens de thème (lisible dans les 3 thèmes)
  // ─────────────────────────────────────────────────────────────────────
  _injectStyles() {
    if (document.getElementById('ppa-styles')) return;
    const css = `
      .ppa-stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px; }
      .ppa-stat { background: hsl(var(--surface)); border: 1px solid hsl(var(--border));
                  border-radius: 12px; padding: 18px 20px; color: hsl(var(--text)); }
      .ppa-stat.is-money { background: hsl(var(--warning-text) / 0.12); border-color: hsl(var(--warning-text) / 0.45); }
      .ppa-stat-label { font-size: 11px; font-weight: 700; letter-spacing: 0.05em;
                        color: hsl(var(--text-muted)); margin-bottom: 8px; }
      .ppa-stat-value { font-size: 28px; font-weight: 800; line-height: 1; margin-bottom: 4px; }
      .ppa-stat-sub { font-size: 12px; color: hsl(var(--text-muted)); }

      .ppa-empty-card { background: hsl(var(--surface)); border: 1px dashed hsl(var(--border));
                       border-radius: 12px; padding: 40px 28px; text-align: center; color: hsl(var(--text-muted)); }
      .ppa-empty-icon { font-size: 36px; margin-bottom: 12px; }
      .ppa-empty-card h3 { color: hsl(var(--text)); font-size: 17px; font-weight: 700; margin-bottom: 6px; }
      .ppa-empty-card p { font-size: 14px; line-height: 1.5; }

      .ppa-error-card { background: hsl(var(--danger-text) / 0.07); border: 1px solid hsl(var(--danger-text) / 0.4);
                        border-radius: 12px; padding: 32px 28px; text-align: center; color: hsl(var(--text-secondary)); }
      .ppa-error-card h3 { color: hsl(var(--danger-text)); font-size: 17px; font-weight: 700; margin-bottom: 6px; }
      .ppa-error-card p { font-size: 14px; line-height: 1.5; }

      .ppa-payouts-card { background: hsl(var(--surface)); border: 1px solid hsl(var(--border));
                          border-radius: 12px; overflow: hidden; }
      .ppa-payouts-head { display: flex; justify-content: space-between; align-items: flex-end;
                          padding: 18px 20px; gap: 16px; flex-wrap: wrap; border-bottom: 1px solid hsl(var(--border)); }
      .ppa-payouts-head h2 { font-size: 17px; font-weight: 700; color: hsl(var(--text)); margin: 0 0 4px; }
      .ppa-payouts-head p { font-size: 13px; color: hsl(var(--text-muted)); margin: 0; }

      .ppa-table-wrap { overflow-x: auto; }
      .ppa-table { width: 100%; border-collapse: collapse; font-size: 14px; }
      .ppa-table th { text-align: left; padding: 12px 16px; font-size: 11px; font-weight: 700;
                      letter-spacing: 0.05em; color: hsl(var(--text-muted)); border-bottom: 1px solid hsl(var(--border)); }
      .ppa-table td { padding: 12px 16px; border-bottom: 1px solid hsl(var(--border));
                      color: hsl(var(--text-secondary)); vertical-align: middle; }
      .ppa-table tr:last-child td { border-bottom: none; }
      .ppa-cell-sub { font-size: 12px; color: hsl(var(--text-muted)); margin-top: 2px; }
      .ppa-cell-mono { font-family: 'JetBrains Mono', monospace; font-size: 13px; }
      .ppa-cell-money { font-weight: 700; color: hsl(var(--warning-text)); }
      .ppa-empty-mini { padding: 20px; text-align: center; color: hsl(var(--text-muted)); }
      .ppa-row-clickable:hover, .ppa-row-clickable:focus-visible { background: hsl(var(--warning-text) / 0.06); cursor: pointer; }
      .ppa-row-clickable:focus-visible { outline: 2px solid hsl(var(--accent)); outline-offset: -2px; }

      .ppa-code { background: hsl(var(--warning-text) / 0.12); color: hsl(var(--warning-text)); padding: 3px 8px;
                  border-radius: 4px; font-family: 'JetBrains Mono', monospace; font-size: 12px; }

      .ppa-badge { display: inline-block; padding: 3px 10px; border-radius: 999px;
                   font-size: 11px; font-weight: 700; letter-spacing: 0.02em; }
      .ppa-badge.is-ok       { background: hsl(var(--success-text) / 0.15); color: hsl(var(--success-text)); }
      .ppa-badge.is-paid     { background: hsl(var(--success-text) / 0.25); color: hsl(var(--success-text)); }
      .ppa-badge.is-pending  { background: hsl(var(--warning-text) / 0.15); color: hsl(var(--warning-text)); }
      .ppa-badge.is-paused   { background: hsl(var(--text-muted) / 0.18); color: hsl(var(--text-muted)); }
      .ppa-badge.is-banned   { background: hsl(var(--danger-text) / 0.15); color: hsl(var(--danger-text)); }
      .ppa-badge.is-paypal   { background: hsl(var(--info-text) / 0.15); color: hsl(var(--info-text)); }
      .ppa-badge.is-virement { background: hsl(var(--accent) / 0.15); color: hsl(var(--accent)); }

      .btn-sm { padding: 6px 12px; font-size: 12px; }
      .ppa-btn-danger { color: hsl(var(--danger-text)); }

      /* Panneau de détail (slide-in) — styles autonomes : avant, cette vue
         dépendait des styles injectés par l'écran Pixel Pros (jamais garantis).
         Scopés par id pour ne pas toucher le panneau de l'écran Pixel Pros. */
      #ppa-detail-overlay.pp-detail-overlay { position: fixed; inset: 0; background: hsl(var(--bg) / 0.6);
                          z-index: 998; backdrop-filter: blur(3px); -webkit-backdrop-filter: blur(3px);
                          animation: ppa-fadein .2s ease; }
      #ppa-detail.pp-detail-panel { position: fixed; top: 0; right: 0; bottom: 0; width: min(640px, 94vw);
                          background: hsl(var(--surface-elevated)); border-left: 1px solid hsl(var(--border));
                          z-index: 1000; overflow-y: auto; padding: 0; color: hsl(var(--text));
                          box-shadow: -12px 0 30px rgba(0, 0, 0, 0.35);
                          animation: ppa-slidein .25s cubic-bezier(.2,.7,.3,1);
                          display: flex; flex-direction: column; }
      @keyframes ppa-fadein { from { opacity: 0; } to { opacity: 1; } }
      @keyframes ppa-slidein { from { transform: translateX(100%); } to { transform: translateX(0); } }

      .ppa-detail-head { padding: 20px 24px; border-bottom: 1px solid hsl(var(--border));
                          display: flex; justify-content: space-between; align-items: center; }
      .ppa-detail-name { font-size: 20px; font-weight: 800; color: hsl(var(--text)); }
      .ppa-detail-email { font-size: 13px; color: hsl(var(--text-muted)); margin-top: 2px; }
      .ppa-detail-close { background: transparent; border: 1px solid hsl(var(--border));
                          color: hsl(var(--text-secondary)); width: 32px; height: 32px; border-radius: 8px; cursor: pointer; }
      .ppa-detail-close:hover { background: hsl(var(--text) / 0.08); }
      .ppa-detail-body { padding: 20px 24px; overflow-y: auto; flex: 1; }
      .ppa-detail-stats { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; margin-bottom: 24px; }
      .ppa-detail-stat-label { font-size: 11px; font-weight: 700; color: hsl(var(--text-muted)); letter-spacing: 0.05em; }
      .ppa-detail-stat-value { font-size: 22px; font-weight: 800; color: hsl(var(--text)); margin-top: 4px; }
      .ppa-detail-section { margin-bottom: 28px; }
      .ppa-detail-section h3 { font-size: 13px; font-weight: 700; color: hsl(var(--warning-text));
                                letter-spacing: 0.05em; margin-bottom: 12px;
                                padding-bottom: 8px; border-bottom: 1px solid hsl(var(--border)); }
      .ppa-detail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; font-size: 13px; color: hsl(var(--text-secondary)); }
      .ppa-detail-grid .lbl { display: block; font-size: 11px; color: hsl(var(--text-muted)); margin-bottom: 4px; }
      .ppa-detail-grid .col-span-2 { grid-column: span 2; }
    `;
    const style = document.createElement('style');
    style.id = 'ppa-styles';
    style.textContent = css;
    document.head.appendChild(style);
  },
};
