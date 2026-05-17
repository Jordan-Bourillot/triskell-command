/* Vue Timeline — "la vie de ce prospect" sur une seule ligne du temps.
 *
 * Affiche tout le parcours d'un prospect : ajout en base, mails envoyés,
 * ouvertures, réponses classifiées, bascule client, paiement, livraison,
 * post-vente. Une seule colonne, ronds d'événements avec icône, libellé
 * et corps optionnel (extrait).
 *
 * Appelée via App.show('prospect_timeline', { id: '<uuid>' }).
 * Bouton « Voir tout son parcours » disponible dans la vue Réponses et
 * la vue Clients (sur les cartes liées à un prospect).
 */

const ProspectTimeline = {
  _currentId: null,
  _data: null,

  async render(container, params) {
    const id = (params && params.id) || '';
    this._currentId = id;

    container.innerHTML = `
      <section class="animate-slide-up max-w-3xl">
        <div class="mb-6">
          <button class="btn btn-secondary mb-4" onclick="history.length > 1 ? history.back() : App.show('replies')">← Retour</button>
          <div class="hero-kicker mb-2">LA VIE DE CE PROSPECT</div>
          <div id="pt-header"></div>
        </div>
        <div id="pt-content">
          <div class="text-center py-16 text-text-muted">Chargement…</div>
        </div>
      </section>
    `;

    if (!id) {
      document.getElementById('pt-content').innerHTML = `
        <div class="card p-10 text-center">
          <p class="text-text-muted">Aucun prospect sélectionné.</p>
        </div>`;
      return;
    }
    if (!App.api) {
      document.getElementById('pt-content').innerHTML = this._preview();
      return;
    }

    let data;
    try { data = await App.api.prospect_timeline({ id }); }
    catch (e) {
      document.getElementById('pt-content').innerHTML =
        `<div class="card p-6 text-danger">Erreur : ${this._esc(String(e))}</div>`;
      return;
    }
    if (!data || !data.ok) {
      document.getElementById('pt-content').innerHTML = `
        <div class="card p-6 text-danger">
          ${this._esc((data && data.error) || 'erreur inconnue')}
        </div>`;
      return;
    }
    this._data = data;
    document.getElementById('pt-header').innerHTML = this._renderHeader(data.prospect, data.events.length);
    document.getElementById('pt-content').innerHTML = this._renderTimeline(data.events);
  },

  _renderHeader(p, n) {
    const sub = [p.city, p.country, p.industry].filter(Boolean).join(' · ');
    const status = (p.status || '').toLowerCase();
    const statusLabel = {
      new:        'Nouveau',
      qualified:  'Qualifié',
      contacted:  'Contacté',
      replied:    'A répondu',
      refused:    'Refus',
      won:        'Gagné',
      lost:       'Perdu',
    }[status] || (p.status || '—');
    return `
      <h1 class="hero-title mb-2" style="font-size: 32px;">${this._esc(p.name || '(sans nom)')}</h1>
      <div class="flex flex-wrap gap-x-4 gap-y-1 text-sm text-text-muted mb-3">
        ${p.email ? `<span>📧 ${this._esc(p.email)}</span>` : ''}
        ${p.website ? `<span>🌐 <a href="${this._esc(p.website)}" target="_blank" rel="noopener" class="hover:text-accent">${this._esc(p.website)}</a></span>` : ''}
        ${sub ? `<span>${this._esc(sub)}</span>` : ''}
        ${p.source_name ? `<span>via ${this._esc(p.source_name)}</span>` : ''}
      </div>
      <div class="flex flex-wrap gap-2 items-center">
        <span class="text-[10px] font-bold tracking-widest text-text-muted">STATUT</span>
        <span class="text-xs px-2 py-1 rounded-full bg-surface-elevated border border-border">${this._esc(statusLabel)}</span>
        <span class="text-xs text-text-muted">· ${n} événement${n > 1 ? 's' : ''}</span>
      </div>
    `;
  },

  _renderTimeline(events) {
    if (!events || events.length === 0) {
      return `
        <div class="card p-10 text-center">
          <p class="text-text-muted">Aucun événement enregistré pour ce prospect.</p>
        </div>`;
    }
    return `
      <ol class="pt-timeline">
        ${events.map(e => this._renderEvent(e)).join('')}
      </ol>
    `;
  },

  _renderEvent(e) {
    const ts = this._formatTs(e.ts);
    const tone = this._toneFor(e.type, e.category);
    const subject = e.subject ? `<div class="pt-event-subject">${this._esc(e.subject)}</div>` : '';
    const body = e.body_excerpt
      ? `<div class="pt-event-body">${this._esc(e.body_excerpt)}</div>`
      : '';
    const subtitle = e.subtitle
      ? `<div class="pt-event-subtitle">${this._esc(e.subtitle)}</div>`
      : '';
    return `
      <li class="pt-event" data-tone="${tone}">
        <div class="pt-event-dot">${e.icon || '•'}</div>
        <div class="pt-event-content">
          <div class="pt-event-head">
            <span class="pt-event-title">${this._esc(e.title || '')}</span>
            <span class="pt-event-ts">${ts}</span>
          </div>
          ${subtitle}
          ${subject}
          ${body}
        </div>
      </li>
    `;
  },

  _toneFor(type, category) {
    if (type === 'payment' || type === 'delivered') return 'success';
    if (type === 'reply_received') {
      if (category === 'interested') return 'success';
      if (category === 'no' || category === 'unsubscribe') return 'danger';
      if (category === 'not_now') return 'warning';
      return 'accent';
    }
    if (type === 'email_opened') return 'accent';
    if (type === 'lead_converted') return 'success';
    if (type === 'cross_sell' || type === 'nps') return 'accent';
    return 'neutral';
  },

  _formatTs(ts) {
    if (!ts) return '';
    try {
      const d = new Date(ts);
      if (isNaN(d.getTime())) return this._esc(ts);
      const today = new Date();
      const sameDay = d.toDateString() === today.toDateString();
      const dd = String(d.getDate()).padStart(2, '0');
      const mm = String(d.getMonth() + 1).padStart(2, '0');
      const yy = d.getFullYear();
      const hh = String(d.getHours()).padStart(2, '0');
      const mn = String(d.getMinutes()).padStart(2, '0');
      return sameDay ? `aujourd’hui ${hh}:${mn}` : `${dd}/${mm}/${yy} ${hh}:${mn}`;
    } catch (e) {
      return this._esc(ts);
    }
  },

  _esc(s) {
    if (s == null) return '';
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  },

  _preview() {
    return `
      <div class="card p-10 text-center">
        <div class="text-3xl mb-3">📋</div>
        <h2 class="text-xl font-semibold mb-2">Aperçu indisponible</h2>
        <p class="text-text-muted">Lance Triskell Command pour voir la vraie timeline.</p>
      </div>`;
  },

  // Helper public pour ouvrir la timeline depuis une autre vue
  openFor(prospectId) {
    App.show('prospect_timeline', { id: prospectId });
  },
};
