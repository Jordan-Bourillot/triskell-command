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

  // Certains événements arrivent du serveur avec un nom technique :
  // on les traduit ici, côté écran (table de correspondance front).
  EVENT_TITLES: {
    cross_sell: 'Mail de vente complémentaire envoyé',
    nps:        'Demande d’avis client envoyée',
  },

  async render(container, params) {
    const id = (params && params.id) || '';
    this._currentId = id;

    container.innerHTML = `
      <section class="animate-slide-up max-w-3xl">
        <div class="mb-6">
          <button class="btn btn-secondary mb-4" onclick="App.show(App.previousView || 'replies')">← Retour</button>
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
          <p class="text-text-muted mb-4">Aucun prospect sélectionné.</p>
          <button class="btn btn-secondary" onclick="App.show('prospects_crm')">Voir tous mes prospects</button>
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
      Toast.friendlyError(e, 'Impossible de charger le parcours de ce prospect.');
      document.getElementById('pt-content').innerHTML = this._errorHtml();
      return;
    }
    if (!data || !data.ok) {
      // Détail technique en console, message simple à l'écran.
      console.warn('[parcours prospect]', data && data.error);
      const gone = data && data.error === 'prospect introuvable';
      document.getElementById('pt-content').innerHTML = this._errorHtml(
        gone ? 'Ce prospect n’existe plus dans la base (il a peut-être été supprimé).' : '',
        gone);
      return;
    }
    this._data = data;
    document.getElementById('pt-header').innerHTML = this._renderHeader(data.prospect, data.events.length);
    document.getElementById('pt-content').innerHTML = this._renderTimeline(data.events);
  },

  // État d'erreur en français, avec porte de sortie.
  _errorHtml(msg, noRetry) {
    return `
      <div class="card p-10 text-center">
        <p class="text-text-muted mb-4">${this._esc(msg || 'Impossible de charger le parcours de ce prospect. Vérifie ta connexion internet, puis réessaie.')}</p>
        ${noRetry
          ? `<button class="btn btn-secondary" onclick="App.show('prospects_crm')">Voir tous mes prospects</button>`
          : `<button class="btn btn-secondary" onclick="ProspectTimeline.retry()">Réessayer</button>`}
      </div>`;
  },

  retry() {
    App.show('prospect_timeline', { id: this._currentId });
  },

  _renderHeader(p, n) {
    const sub = [p.city, p.country, p.industry].filter(Boolean).join(' · ');
    const status = (p.status || '').toLowerCase();
    // Mêmes libellés que la base « Tous les prospects » (Refusé, pas Refus)
    const statusLabel = {
      new:        'Nouveau',
      qualified:  'Qualifié',
      contacted:  'Contacté',
      replied:    'A répondu',
      refused:    'Refusé',
      won:        'Gagné',
      lost:       'Perdu',
    }[status] || (p.status || '—');
    const wurl = this._safeUrl(p.website);
    return `
      <h1 class="hero-title mb-2" style="font-size: 32px;">${this._esc(p.name || '(sans nom)')}</h1>
      <div class="flex flex-wrap gap-x-4 gap-y-1 text-sm text-text-muted mb-3">
        ${p.email ? `<span>📧 <a href="mailto:${this._esc(p.email)}" class="hover:text-accent hover:underline">${this._esc(p.email)}</a></span>` : ''}
        ${p.website ? `<span>🌐 ${wurl
          ? `<a href="${this._esc(wurl)}" target="_blank" rel="noopener" class="hover:text-accent">${this._esc(p.website)}</a>`
          : this._esc(p.website)}</span>` : ''}
        ${sub ? `<span>${this._esc(sub)}</span>` : ''}
        ${p.source_name ? `<span>via ${this._esc(p.source_name)}</span>` : ''}
      </div>
      <div class="flex flex-wrap gap-2 items-center">
        <span class="text-[11px] font-bold tracking-widest text-text-muted">STATUT</span>
        <span class="text-xs px-2 py-1 rounded-full bg-surface-elevated border border-border">${this._esc(statusLabel)}</span>
        <span class="text-xs text-text-muted">· ${n} événement${n > 1 ? 's' : ''}</span>
      </div>
    `;
  },

  // N'accepte que les vraies adresses web (http/https).
  _safeUrl(u) {
    const s = String(u || '').trim();
    return /^https?:\/\//i.test(s) ? s : '';
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
    // Libellé français prioritaire sur le titre technique du serveur
    const title = this.EVENT_TITLES[e.type] || e.title || '';
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
            <span class="pt-event-title">${this._esc(title)}</span>
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
        <p class="text-text-muted">Le parcours ne peut pas s’afficher en mode aperçu.</p>
      </div>`;
  },

  // Helper public pour ouvrir la timeline depuis une autre vue
  openFor(prospectId) {
    App.show('prospect_timeline', { id: prospectId });
  },
};
