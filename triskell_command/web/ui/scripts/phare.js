/* Le Phare — refonte 2026-05-17
 *
 * Philosophie : compréhensible en 30 secondes, utilisable en 1 minute par site.
 *
 * Trois vues seulement :
 *   - 'home'      → grille de cartes site (chacune = santé + chiffre clé + nb à regarder)
 *   - 'site'      → vue détail 1-minute (3 chiffres + à toi de jouer + ce qui a été fait)
 *   - 'coulisses' → vue cachée des 8 agents (qui bossent en arrière-plan)
 *
 * Plus d'onglet « À valider » séparé : les recos sont actionnables direct sur le site.
 * Plus d'onglet « Bulletins » séparé : le bulletin du jour s'affiche en haut du site.
 * Statuts simplifiés en 4 mots : « À regarder », « Appliqué », « Refusé », « Périmé ».
 */

const Phare = {
  view: 'home',
  selectedSite: null,
  filter: 'all',         // 'all' | 'internal' | 'external'
  _onboardKey: 'phare_onboarded_v1',
  _currentActions: {},   // map id → action (alimentée au render pour la modale d'aperçu)
  _homeSites: [],        // cache du dernier chargement (filtres sans re-fetch)
  _coulissesFrom: 'home',// d'où on est entré dans Coulisses (pour le bouton Retour)
  _navIntent: false,     // true = navigation interne via _go (état explicite)
  _selectedSiteName: '', // nom du site ouvert (libellés de Coulisses)

  async render(container) {
    // Entrée par le menu (sans navigation interne explicite) → toujours l'accueil.
    // Le re-clic sur « Le Phare » dans le menu rouvre donc la grille des sites.
    if (!this._navIntent) this.view = 'home';
    this._navIntent = false;
    if (this.view === 'site')      return this._renderSite(container);
    if (this.view === 'coulisses') return this._renderCoulisses(container);
    return this._renderHome(container);
  },

  _go(view, opts = {}) {
    if (view === 'coulisses') this._coulissesFrom = this.view; // mémorise l'origine
    this.view = view;
    if (opts.siteId) this.selectedSite = opts.siteId;
    this._navIntent = true;
    App.show('phare');
  },

  // ════════════════════════════════════════════════════════════════════
  //  VUE HOME — grille de cartes site (1 ligne, 1 site, 1 décision)
  // ════════════════════════════════════════════════════════════════════
  async _renderHome(container) {
    container.innerHTML = `
      <section class="phare-page animate-fade-in">
        <header class="phare-home-head">
          <div class="phare-home-head-left">
            <div class="phare-kicker">LE PHARE · SEO AUTONOME</div>
            <h1 class="phare-title">Tes sites.</h1>
            <p class="phare-subtitle">Les robots préparent des améliorations. Tu valides ou tu refuses. C'est tout.</p>
          </div>
          <div class="phare-home-head-right">
            <button class="btn btn-primary" data-act="add">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" style="margin-right:6px;vertical-align:-2px"><path d="M12 5v14M5 12h14"/></svg>
              Ajouter un site
            </button>
          </div>
        </header>

        <nav class="phare-filter" aria-label="Filtrer les sites">
          <button class="phare-filter-btn ${this.filter === 'all' ? 'is-active' : ''}" data-filter="all">Tous</button>
          <button class="phare-filter-btn ${this.filter === 'internal' ? 'is-active' : ''}" data-filter="internal">Nos sites</button>
          <button class="phare-filter-btn ${this.filter === 'external' ? 'is-active' : ''}" data-filter="external">Clients</button>
          <div class="phare-filter-spacer" aria-hidden="true"></div>
          <button class="phare-coulisses-btn" data-act="coulisses" title="Voir les robots qui surveillent tes sites">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3h0a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5h0a1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9v0a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/></svg>
            En coulisses
          </button>
        </nav>

        <div id="ph-home-grid">
          <div class="phare-loading">Chargement de tes sites…</div>
        </div>
      </section>
    `;

    container.querySelector('[data-act="add"]').onclick = () => this._openQuickAddDialog();
    container.querySelector('[data-act="coulisses"]').onclick = () => this._go('coulisses');
    // Filtrage local : on réutilise les sites déjà chargés, sans re-fetch ni flash
    container.querySelectorAll('[data-filter]').forEach(b => {
      b.onclick = () => {
        this.filter = b.dataset.filter;
        container.querySelectorAll('[data-filter]').forEach(x => x.classList.toggle('is-active', x === b));
        this._renderHomeGrid(this._homeSites || []);
      };
    });

    // Onboarding au premier lancement (après que le DOM soit posé)
    setTimeout(() => this._maybeShowOnboarding(), 100);

    if (!App.api) {
      this._homeSites = this._previewSites();
      this._renderHomeGrid(this._homeSites);
      return;
    }
    let data;
    try { data = await App.api.phare_home({}); }
    catch (e) {
      console.warn('[Phare] phare_home injoignable :', e);
      this._renderHomeError(container);
      return;
    }
    if (!data || !data.ok) {
      console.warn('[Phare] phare_home en erreur :', data);
      this._renderHomeError(container);
      return;
    }
    this._homeSites = data.sites || [];
    this._renderHomeGrid(this._homeSites);
  },

  // Bloc d'erreur de chargement de l'accueil, avec bouton Réessayer
  // (le détail technique part en console, jamais à l'écran).
  _renderHomeError(container) {
    const slot = document.getElementById('ph-home-grid');
    if (!slot) return;
    slot.innerHTML =
      `<div class="phare-empty"><div class="phare-empty-icon">⚠️</div>
       <h2>Connexion à la base impossible</h2>
       <p>Impossible de lire tes sites pour l'instant. Vérifie ta connexion internet, puis réessaie.</p>
       <div style="display:flex;gap:10px;justify-content:center;flex-wrap:wrap">
         <button class="btn btn-primary" data-retry>Réessayer</button>
         <button class="btn btn-secondary" onclick="App.show('config', {tab:'account'})">Aller dans Réglages</button>
       </div></div>`;
    slot.querySelector('[data-retry]').onclick = () => this._renderHome(container);
  },

  // Bloc d'erreur de chargement d'une fiche site, avec bouton Réessayer
  // (même esprit que l'accueil : message français, détail en console).
  _renderSiteError(container, message) {
    const slot = document.getElementById('ph-site-body');
    if (!slot) return;
    slot.innerHTML =
      `<div class="phare-empty"><div class="phare-empty-icon">⚠️</div>
       <h2>Connexion à la base impossible</h2>
       <p>${this._esc(message || "Impossible de charger ce site pour l'instant. Réessaie dans un instant.")}</p>
       <div style="display:flex;gap:10px;justify-content:center;flex-wrap:wrap">
         <button class="btn btn-primary" data-retry>Réessayer</button>
         <button class="btn btn-secondary" data-back-home>Retour à tes sites</button>
       </div></div>`;
    slot.querySelector('[data-retry]').onclick = () => this._renderSite(container);
    slot.querySelector('[data-back-home]').onclick = () => this._go('home');
  },

  _renderHomeGrid(sites) {
    const filtered = sites.filter(s => {
      if (this.filter === 'internal') return !s.is_external_client;
      if (this.filter === 'external') return !!s.is_external_client;
      return true;
    });
    const slot = document.getElementById('ph-home-grid');
    if (!slot) return;
    if (filtered.length === 0) {
      const label = this.filter === 'external' ? 'client' : 'site';
      slot.innerHTML = `
        <div class="phare-empty">
          <div class="phare-empty-icon">📭</div>
          <h2>Aucun ${label} pour l'instant</h2>
          <p>Ajoute un premier ${label} avec le bouton en haut à droite. Les robots commenceront à le surveiller dès la prochaine heure.</p>
        </div>`;
      return;
    }
    slot.innerHTML = `<div class="phare-cards-grid">${filtered.map(s => this._siteCard(s)).join('')}</div>`;
    slot.querySelectorAll('[data-open]').forEach(b => {
      b.onclick = () => this._go('site', { siteId: b.dataset.open });
    });
  },

  _siteCard(s) {
    const tone = s.health_tone || 'unknown';
    const dot = { ok: '🟢', warn: '🟠', bad: '🔴', unknown: '⚪' }[tone] || '⚪';
    const healthLabel = { ok: 'Santé bonne', warn: 'À surveiller', bad: 'Problèmes',
                          unknown: 'Pas encore d’audit' }[tone];
    const pending = s.pending_count || 0;
    const delta = s.delta_pct;
    const clicks = s.clicks_30d || 0;
    // Phrase situation : choisit la plus parlante
    let situation = '';
    if (clicks === 0 && pending === 0) {
      situation = 'Pas encore de données — les robots arrivent.';
    } else if (delta !== null && delta !== undefined && Math.abs(delta) >= 5) {
      const sign = delta > 0 ? '+' : '';
      const trend = delta > 0 ? 'visites en hausse' : 'visites en baisse';
      situation = `<strong>${sign}${delta}%</strong> de ${trend} ce mois-ci`;
    } else if (clicks > 0) {
      situation = `${this._fmt(clicks)} visites ce mois-ci`;
    } else {
      situation = healthLabel;
    }
    // Action attendue
    let action;
    if (pending > 0) {
      const word = pending === 1 ? 'proposition' : 'propositions';
      action = `<div class="phare-card-todo phare-card-todo--hot">
                  <strong>${pending}</strong> ${word} à regarder
                </div>`;
    } else {
      action = `<div class="phare-card-todo">✓ Rien à faire pour l'instant</div>`;
    }
    const bullet = s.has_bulletin
      ? `<span class="phare-card-bullet" title="Bulletin du jour disponible">📰 Bulletin du jour</span>` : '';
    return `
      <article class="phare-site-card phare-site-card--${tone}">
        <header class="phare-site-card-head">
          <div class="phare-site-card-dot" aria-hidden="true">${dot}</div>
          <div class="phare-site-card-name">
            <div class="phare-site-card-title">${this._esc(s.name || s.domain || '—')}</div>
            <div class="phare-site-card-domain">${this._esc(s.domain || '')}</div>
          </div>
          ${s.is_external_client ? `<span class="phare-site-card-tag">Client</span>` : ''}
        </header>
        <div class="phare-site-card-situation">${situation}</div>
        ${action}
        ${bullet}
        <footer class="phare-site-card-foot">
          <button class="btn btn-primary phare-site-card-open" data-open="${this._esc(s.id || '')}">
            Ouvrir
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" style="margin-left:6px"><path d="M5 12h14M12 5l7 7-7 7"/></svg>
          </button>
        </footer>
      </article>
    `;
  },

  // ════════════════════════════════════════════════════════════════════
  //  VUE SITE — 1-minute : 3 chiffres + à toi de jouer + ce qui a été fait
  // ════════════════════════════════════════════════════════════════════
  async _renderSite(container) {
    if (!this.selectedSite) { this._go('home'); return; }
    container.innerHTML = `
      <section class="phare-page animate-fade-in">
        ${this._backHeader()}
        <div id="ph-site-body"><div class="phare-loading">Chargement du site…</div></div>
      </section>
    `;
    container.querySelector('[data-act="back"]').onclick = () => this._go('home');
    if (!App.api) {
      document.getElementById('ph-site-body').innerHTML =
        `<div class="phare-empty"><div class="phare-empty-icon">🔌</div><h2>Mode aperçu</h2><p>Pas de données.</p></div>`;
      return;
    }
    let data;
    try { data = await App.api.phare_site_dashboard({ id: this.selectedSite }); }
    catch (e) {
      console.warn('[Phare] phare_site_dashboard injoignable :', e);
      this._renderSiteError(container, "Impossible de charger ce site pour l'instant. Vérifie ta connexion internet, puis réessaie.");
      return;
    }
    if (!data || !data.ok) {
      console.warn('[Phare] phare_site_dashboard en erreur :', data);
      this._renderSiteError(container, "Ce site n'a pas pu être lu pour l'instant. Réessaie dans un instant.");
      return;
    }
    const s = data.site || {};
    const kpis = data.kpis || {};
    const toReview = data.to_review || [];
    const advice = data.advice || [];
    const done = data.recently_done || [];
    const bull = data.bulletin || null;
    this._selectedSiteName = s.name || s.domain || '';

    // Indexer les propositions (pile + conseils) pour la modale d'aperçu
    this._currentActions = {};
    [...toReview, ...advice].forEach(a => { if (a && a.id) this._currentActions[a.id] = a; });

    document.getElementById('ph-site-body').innerHTML = `
      <header class="phare-site-hero">
        <div class="phare-site-hero-left">
          <div class="phare-kicker">SITE</div>
          <h1 class="phare-title">${this._esc(s.name || s.domain || '—')}</h1>
          <p class="phare-subtitle"><a href="https://${this._esc(s.domain || '')}" target="_blank" rel="noopener">${this._esc(s.domain || '')}</a></p>
        </div>
        <div class="phare-site-hero-right">
          <button class="btn btn-secondary" data-act="audit" title="Un grand contrôle complet du site : vitesse, balises, liens cassés">Lancer un audit</button>
          <button class="btn btn-secondary" data-act="edit">Réglages du site</button>
        </div>
      </header>

      <!-- 3 chiffres clés -->
      <div class="phare-kpis">
        ${this._kpi('Visites (30 j)', this._fmt(kpis.clicks_30d || 0),
                    kpis.delta_pct !== null && kpis.delta_pct !== undefined
                      ? `${kpis.delta_pct > 0 ? '+' : ''}${kpis.delta_pct}% vs 30 j avant`
                      : '—',
                    kpis.delta_pct > 0 ? 'good' : (kpis.delta_pct < 0 ? 'bad' : null))}
        ${this._kpi('Position moyenne', kpis.position_avg != null ? kpis.position_avg : '—',
                    kpis.position_avg != null && kpis.position_avg <= 10 ? 'Top 10 Google' : 'Sur Google', null)}
        ${this._kpi('Santé SEO', kpis.health != null ? `${kpis.health}/100` : '—',
                    { ok: 'Bon état', warn: 'À surveiller', bad: 'À soigner',
                      failed: 'Test Google bloqué — relance l’audit',
                      unknown: 'Pas encore audité' }[kpis.health_tone] || '—',
                    kpis.health_tone === 'ok' ? 'good'
                      : (kpis.health_tone === 'bad' || kpis.health_tone === 'failed' ? 'bad' : null))}
      </div>

      <!-- Bulletin du jour si présent -->
      ${bull ? this._bulletinCard(bull) : ''}

      <!-- À TOI DE JOUER -->
      <div class="phare-section">
        <header class="phare-section-head">
          <h2>À toi de jouer</h2>
          <span class="phare-section-sub">
            ${toReview.length === 0
              ? 'Rien en attente — tu peux respirer.'
              : `${toReview.length} proposition${toReview.length > 1 ? 's' : ''} des robots, à valider ou refuser.`}
          </span>
        </header>
        <div id="ph-todo-list">
          ${toReview.length === 0
            ? `<div class="phare-empty-inline">✓ Rien à valider pour l'instant. Les robots travaillent en arrière-plan.</div>`
            : toReview.map(a => this._actionCard(a, 'todo')).join('')}
        </div>
      </div>

      <!-- CONSEILS (à lire / à faire toi-même) — hors de la pile, repliable -->
      ${advice.length === 0 ? '' : `
      <div class="phare-section">
        <details>
          <summary style="cursor:pointer;">
            <strong style="font-size:1.05rem;">💡 Conseils (${advice.length})</strong>
            <span class="phare-section-sub" style="display:block;margin-top:4px;">À lire ou à faire toi-même — le robot ne peut pas s’en charger. Rien d’urgent, déplie si tu veux.</span>
          </summary>
          <div id="ph-advice-list" style="margin-top:12px;">
            ${advice.map(a => this._actionCard(a, 'todo')).join('')}
          </div>
        </details>
      </div>`}

      <!-- CE QUI A ÉTÉ FAIT -->
      <div class="phare-section">
        <header class="phare-section-head">
          <h2>Ce qui a été fait</h2>
          <span class="phare-section-sub">
            ${done.length === 0 ? 'Pas encore de modifications appliquées.'
                                 : `Les ${done.length} dernières modifications validées.`}
          </span>
        </header>
        <div id="ph-done-list">
          ${done.length === 0
            ? `<div class="phare-empty-inline">Quand tu valideras une proposition, elle apparaîtra ici.</div>`
            : done.map(a => this._actionCard(a, 'done')).join('')}
        </div>
      </div>

      <!-- EN COULISSES (repliable) -->
      <details class="phare-coulisses-details">
        <summary>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/></svg>
          En coulisses — qui surveille ce site ?
        </summary>
        <div class="phare-coulisses-mini">
          <p>Des robots Claude tournent en arrière-plan sur ton site, chacun avec sa spécialité.</p>
          <button class="btn btn-secondary btn-sm" data-act="coulisses">Voir les robots</button>
        </div>
      </details>
    `;

    const auditBtn = document.getElementById('ph-site-body').querySelector('[data-act="audit"]');
    auditBtn.onclick = async () => {
      auditBtn.disabled = true;
      const lbl = auditBtn.textContent;
      auditBtn.textContent = 'Lancement…';
      try {
        const res = await App.api.phare_run_audit({ id: this.selectedSite });
        if (res && res.ok) {
          Toast.success('Audit lancé — le résultat arrive dans quelques minutes.');
          auditBtn.textContent = 'Audit en cours…'; // reste désactivé : pas de double audit
          this._showAuditPendingNote();
          // L'écran se rafraîchit tout seul quand le résultat a eu le temps d'arriver
          // (minuteur auto-nettoyé si on quitte la vue).
          App.viewTimeout(() => {
            if (this.view === 'site') this._renderSite(document.getElementById('content'));
          }, 60000);
        } else {
          Toast.friendlyError(res && res.error, 'L’audit n’a pas pu être lancé. Réessaie dans un instant.');
          auditBtn.disabled = false; auditBtn.textContent = lbl;
        }
      } catch (e) {
        Toast.friendlyError(e);
        auditBtn.disabled = false; auditBtn.textContent = lbl;
      }
    };
    document.getElementById('ph-site-body').querySelector('[data-act="edit"]').onclick = () => {
      this._openSiteDialog({ site: s, externalOnly: !!s.is_external_client });
    };
    document.getElementById('ph-site-body').querySelector('[data-act="coulisses"]').onclick = () =>
      this._go('coulisses');
    // Wire OK / Non / Voir détail
    this._wireActionButtons(document.getElementById('ph-site-body'));
  },

  // Petit bandeau « audit en cours » sous l'en-tête du site, avec un bouton
  // Actualiser visible (en plus du rafraîchissement automatique programmé).
  _showAuditPendingNote() {
    const body = document.getElementById('ph-site-body');
    if (!body) return;
    let note = body.querySelector('#ph-audit-note');
    if (!note) {
      note = document.createElement('div');
      note.id = 'ph-audit-note';
      note.className = 'phare-empty-inline';
      note.style.cssText = 'display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin:12px 0';
      const hero = body.querySelector('.phare-site-hero');
      if (hero) hero.insertAdjacentElement('afterend', note);
      else body.prepend(note);
    }
    note.innerHTML = `
      <span>⏳ Audit en cours — le résultat arrive dans quelques minutes. L’écran se mettra à jour tout seul.</span>
      <button class="btn btn-secondary btn-sm" data-refresh>Actualiser</button>`;
    note.querySelector('[data-refresh]').onclick = () =>
      this._renderSite(document.getElementById('content'));
  },

  // ════════════════════════════════════════════════════════════════════
  //  Carte d'action (proposition) — affichage + boutons
  // ════════════════════════════════════════════════════════════════════
  _actionCard(a, mode) {
    const agentLabel = this._agentShortName(a.agent || '');
    const date = this._frDate(a.created_at);
    const impact = Math.max(0, Math.min(5, a.impact || 0));
    const impactDots = '●'.repeat(impact) + '○'.repeat(5 - impact);
    const summary = a.detail_md || a.summary || '';
    const summaryShort = summary.length > 240
      ? this._esc(summary.slice(0, 240)) + '…'
      : this._esc(summary);
    if (mode === 'done') {
      return `
        <article class="phare-action phare-action--done" data-aid="${this._esc(a.id || '')}">
          <div class="phare-action-head">
            <div class="phare-action-icon">✓</div>
            <div class="phare-action-body">
              <div class="phare-action-title">${this._esc(a.title || a.kind || '—')}</div>
              <div class="phare-action-meta">${this._esc(agentLabel)} · Appliqué le ${date || '—'}</div>
            </div>
            ${a.github_pr_url ? `<a class="phare-action-link" href="${this._esc(a.github_pr_url)}" target="_blank" rel="noopener">Voir la modif</a>` : ''}
            ${a.github_pr_url ? `<button class="btn btn-secondary btn-sm" data-revert="${this._esc(a.id || '')}"
                     title="Le robot fabrique la modification inverse et la publie — le site revient comme avant cette modif">↩ Annuler</button>` : ''}
            <button class="phare-action-archive" data-archive="${this._esc(a.id || '')}" title="Retirer de la liste" aria-label="Retirer de la liste">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m3 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/></svg>
            </button>
          </div>
        </article>`;
    }
    const isAuto = this._isAuto(a);                       // PR déjà prête à publier
    const apply = a.apply || {};
    const applyState = a.apply_state || '';
    // Si le robot a déjà regardé et conclu « à faire à la main », on ne
    // repropose pas « OK, fais-le » : retour aux boutons humains, avec
    // le bandeau 🛠️ qui explique pourquoi.
    const robotDeclined = applyState === 'manual';
    const canRobot = !isAuto && !!apply.can && !robotDeclined;
    const robotBusy = applyState === 'queued' || applyState === 'running';
    const simpleWhat = (a.simple_what || '').trim();
    const detailFull = a.detail_md || a.summary || '';

    let badge;
    if (isAuto) {
      badge = `<div class="phare-action-kind phare-action-kind--auto" title="Le robot a déjà préparé la modification. Si tu approuves, elle est publiée automatiquement sur ton site.">
           <span class="phare-action-kind-ico">🤖</span>
           <span class="phare-action-kind-lbl">Le robot publie pour toi</span>
         </div>`;
    } else if (canRobot) {
      badge = `<div class="phare-action-kind phare-action-kind--auto" title="Tu cliques, le robot modifie le site, vérifie et publie. Tu n'as rien d'autre à faire.">
           <span class="phare-action-kind-ico">🤖</span>
           <span class="phare-action-kind-lbl">Le robot peut le faire</span>
         </div>`;
    } else {
      badge = `<div class="phare-action-kind phare-action-kind--manual" title="${this._esc(apply.why || 'C’est un conseil à faire toi-même. Approuver ne déclenche rien — ça marque juste la proposition comme lue.')}">
           <span class="phare-action-kind-ico">👤</span>
           <span class="phare-action-kind-lbl">À toi de le faire</span>
         </div>`;
    }

    // Corps : l'explication simple d'abord, le détail technique replié
    const body = simpleWhat
      ? `<div class="phare-action-summary" style="font-size:13.5px;line-height:1.5">${this._esc(simpleWhat)}</div>
         ${detailFull ? `<details class="phare-action-tech" style="margin-top:6px">
           <summary style="cursor:pointer;font-size:12px;opacity:.65">Détail technique</summary>
           <div class="phare-action-summary" style="margin-top:6px">${this._esc(detailFull.slice(0, 700))}${detailFull.length > 700 ? '…' : ''}</div>
         </details>` : ''}`
      : (detailFull ? `<div class="phare-action-summary">${this._esc(detailFull.slice(0, 240))}${detailFull.length > 240 ? '…' : ''}</div>` : '');

    // Bandeaux d'état du robot (échec / à faire à la main)
    let stateNote = '';
    if (applyState === 'failed') {
      stateNote = `<div class="phare-empty-inline" style="margin-top:8px;border-left:3px solid #e5484d;display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap">
          <span>⚠️ ${this._esc(a.apply_error || 'Le robot n’a pas réussi.')}</span>
          <span style="display:flex;gap:8px">
            ${a.github_pr_url ? `<a class="phare-action-link" href="${this._esc(a.github_pr_url)}" target="_blank" rel="noopener">Voir la modif préparée</a>` : ''}
            <button class="btn btn-secondary btn-sm" data-apply-retry="${this._esc(a.id || '')}">Réessayer</button>
          </span>
        </div>`;
    } else if (applyState === 'manual') {
      stateNote = `<div class="phare-empty-inline" style="margin-top:8px;border-left:3px solid #f5a623">
          🛠️ Le robot a regardé : ${this._esc(a.apply_error || 'c’est à faire à la main.')}
        </div>`;
    }

    // Carte « robot au travail » : pas de boutons, suivi en direct
    if (robotBusy) {
      return `
      <article class="phare-action phare-action--todo is-auto" data-aid="${this._esc(a.id || '')}" data-apply-pending="${this._esc(a.id || '')}">
        ${badge}
        <div class="phare-action-head">
          <div class="phare-action-icon phare-action-icon--todo">${this._actionEmoji(a.agent)}</div>
          <div class="phare-action-body">
            <div class="phare-action-title">${this._esc(a.title || a.kind || '—')}</div>
            <div class="phare-action-meta">Proposition de ${this._esc(agentLabel)} · ${date || '—'}</div>
          </div>
        </div>
        ${body}
        <div class="phare-empty-inline" style="margin-top:8px" data-apply-note>⏳ Le robot s'en occupe — modification, vérifications, publication. Tu peux quitter la page, ça continue tout seul.</div>
      </article>`;
    }

    const approveLabel = isAuto
      ? `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" style="margin-right:6px;vertical-align:-2px"><path d="M5 3l14 9-14 9V3z"/></svg>Publier sur le site`
      : `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" style="margin-right:6px;vertical-align:-2px"><path d="M20 6L9 17l-5-5"/></svg>J'ai fait, suivant`;
    const mainButton = canRobot
      ? `<button class="btn btn-primary btn-auto" data-apply="${this._esc(a.id || '')}">
           <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" style="margin-right:6px;vertical-align:-2px"><path d="M5 3l14 9-14 9V3z"/></svg>OK, fais-le
         </button>`
      : `<button class="btn btn-primary ${isAuto ? 'btn-auto' : 'btn-manual'}" data-approve="${this._esc(a.id || '')}" data-approve-auto="${isAuto ? '1' : '0'}">
           ${approveLabel}
         </button>`;
    return `
      <article class="phare-action phare-action--todo ${isAuto || canRobot ? 'is-auto' : 'is-manual'}" data-aid="${this._esc(a.id || '')}">
        ${badge}
        <div class="phare-action-head">
          <div class="phare-action-icon phare-action-icon--todo">${this._actionEmoji(a.agent)}</div>
          <div class="phare-action-body">
            <div class="phare-action-title">${this._esc(a.title || a.kind || '—')}</div>
            <div class="phare-action-meta">
              Proposition de ${this._esc(agentLabel)} · ${date || '—'}
              ${impact ? `<span class="phare-action-impact" title="Impact estimé">${impactDots} <span style="font-size:11px">impact ${impact}/5</span></span>` : ''}
            </div>
          </div>
        </div>
        ${body}
        ${stateNote}
        <footer class="phare-action-foot">
          <button class="btn btn-secondary btn-reject" data-reject="${this._esc(a.id || '')}">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" style="margin-right:6px;vertical-align:-2px"><path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m3 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/></svg>
            Poubelle
          </button>
          ${isAuto ? `
          <button class="btn btn-secondary" data-preview="${this._esc(a.id || '')}">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" style="margin-right:6px;vertical-align:-2px"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
            Aperçu avant publication
          </button>` : ''}
          ${mainButton}
        </footer>
      </article>
    `;
  },

  // Retourne true si l'approbation déclenche une publication automatique
  // (modif technique préparée par un robot — PR GitHub à merger), false
  // si c'est juste une recommandation textuelle à appliquer à la main.
  _isAuto(a) {
    if (!a) return false;
    if (a.kind === 'recommandation') return false;
    if (a.github_pr_url) return true;
    // Par défaut : si pas explicitement marqué "recommandation", on considère
    // que c'est une modif automatique (anciens enregistrements sans kind).
    return a.kind === 'pr_modif' || !!a.github_pr_url;
  },

  _wireActionButtons(root) {
    root.querySelectorAll('[data-approve]').forEach(b => {
      b.onclick = () => this._approveAction(b.dataset.approve, b.dataset.approveAuto === '1', b);
    });
    root.querySelectorAll('[data-reject]').forEach(b => {
      b.onclick = () => this._rejectAction(b.dataset.reject, b);
    });
    root.querySelectorAll('[data-preview]').forEach(b => {
      b.onclick = () => {
        const id = b.dataset.preview;
        const action = this._currentActions[id];
        if (action) this._openPreviewDialog(action);
      };
    });
    root.querySelectorAll('[data-archive]').forEach(b => {
      b.onclick = () => this._archiveAction(b.dataset.archive, b);
    });
    // « ↩ Annuler » : le robot publie la modification inverse (revert).
    root.querySelectorAll('[data-revert]').forEach(b => {
      b.onclick = () => this._revertAction(b.dataset.revert, b);
    });
    // « OK, fais-le » : le robot fabrique et publie la modification
    root.querySelectorAll('[data-apply]').forEach(b => {
      b.onclick = () => this._applyAction(b.dataset.apply, b);
    });
    root.querySelectorAll('[data-apply-retry]').forEach(b => {
      b.onclick = () => this._applyRetry(b.dataset.applyRetry, b);
    });
    // Cartes déjà en cours au chargement de la page : on reprend le suivi
    root.querySelectorAll('[data-apply-pending]').forEach(el => {
      this._pollApply(el.dataset.applyPending);
    });
  },

  // ── « OK, fais-le » ─────────────────────────────────────────────────
  // Le clic met l'action en file côté serveur ; la carte passe en mode
  // « le robot s'en occupe » et un suivi léger met à jour l'issue
  // (publié / à faire à la main / échec) sans recharger la page.

  async _applyAction(id, btn) {
    // Garde-fou : « OK, fais-le » enclenche modification → vérifications →
    // publication sur le site en ligne, sans autre étape de validation.
    const siteName = this._selectedSiteName || '';
    const okGo = await Dialog.confirm(
      'Le robot va modifier '
      + (siteName ? `« ${siteName} »` : 'ton site')
      + ', vérifier que rien n’est cassé, puis publier tout seul — '
      + 'sans autre validation de ta part.\n\n'
      + 'Tu retrouveras le résultat dans « Ce qui a été fait ».',
      { title: 'Laisser le robot faire ?', danger: true,
        okLabel: 'OK, fais-le', cancelLabel: 'Annuler' });
    if (!okGo) return false;
    if (btn) { btn.disabled = true; btn.textContent = 'Je m’en occupe…'; }
    try {
      const res = await App.api.phare_apply_action({ id });
      if (!res || !res.ok) {
        Toast.friendlyError(res && res.error, 'Le robot n’a pas pu prendre la demande. Réessaie dans un instant.');
        if (btn) { btn.disabled = false; btn.innerHTML = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" style="margin-right:6px;vertical-align:-2px"><path d="M5 3l14 9-14 9V3z"/></svg>OK, fais-le`; }
        return false;
      }
      const msg = res.mode === 'server'
        ? 'C’est parti — le robot s’en occupe (2-3 minutes).'
        : (res.mode === 'github_actions'
            ? 'C’est parti — robot réveillé, ça se fait dans les minutes qui viennent.'
            : 'C’est noté — le robot passera dans l’heure. Tu peux quitter la page.');
      Toast.success(msg);
      this._setCardBusy(id);
      this._pollApply(id);
      return true;
    } catch (e) {
      Toast.friendlyError(e);
      if (btn) { btn.disabled = false; }
      return false;
    }
  },

  async _applyRetry(id, btn) {
    if (btn) { btn.disabled = true; btn.textContent = 'Relance…'; }
    try {
      const res = await App.api.phare_apply_retry({ id });
      if (!res || !res.ok) {
        Toast.friendlyError(res && res.error, 'La relance n’a pas pu partir. Réessaie dans un instant.');
        if (btn) { btn.disabled = false; btn.textContent = 'Réessayer'; }
        return false;
      }
      Toast.success('C’est reparti — le robot réessaie.');
      this._setCardBusy(id);
      this._pollApply(id);
      return true;
    } catch (e) {
      Toast.friendlyError(e);
      if (btn) { btn.disabled = false; btn.textContent = 'Réessayer'; }
      return false;
    }
  },

  // Remplace pied + bandeaux de la carte par la note « le robot s'en occupe »
  _setCardBusy(id) {
    const card = this._findCard(id);
    if (!card) return;
    card.classList.add('is-auto');
    card.querySelectorAll('.phare-action-foot, [data-apply-note], .phare-empty-inline').forEach(el => el.remove());
    const note = document.createElement('div');
    note.className = 'phare-empty-inline';
    note.style.marginTop = '8px';
    note.setAttribute('data-apply-note', '');
    note.textContent = '⏳ Le robot s’en occupe — modification, vérifications, publication. Tu peux quitter la page, ça continue tout seul.';
    card.appendChild(note);
  },

  _findCard(id) {
    let card = null;
    document.querySelectorAll('.phare-action[data-aid]').forEach(el => {
      if (el.dataset.aid === String(id)) card = el;
    });
    return card;
  },

  // Suivi léger : interroge le statut toutes les 10 s pendant ~6 min.
  // Au-delà (file pour le prochain passage horaire), on arrête poliment :
  // le travail continue côté serveur même page fermée.
  _pollApply(id, attempt = 0) {
    if (!App.api || typeof App.api.phare_action_status !== 'function') return;
    if (this.view !== 'site') return;
    App.viewTimeout(async () => {
      if (this.view !== 'site') return;
      let st = null;
      try { st = await App.api.phare_action_status({ id }); } catch (e) { st = null; }
      if (!st || !st.ok) {
        if (attempt < 36) this._pollApply(id, attempt + 1);
        return;
      }
      const state = st.apply_state || '';
      if (state === 'done' || st.status === 'merged') {
        Toast.success('✅ C’est fait — la modification est publiée. Le site se met à jour dans quelques minutes.');
        if (window.Guide && Guide.say) { try { Guide.say('✓ Modification publiée par le robot'); } catch (e) {} }
        this._removeActionCard(id);
        return;
      }
      if (state === 'failed' || state === 'manual') {
        this._showApplyOutcome(id, st);
        return;
      }
      if (attempt < 36) {
        this._pollApply(id, attempt + 1);
      } else {
        const card = this._findCard(id);
        const note = card && card.querySelector('[data-apply-note]');
        if (note) note.textContent = '⏳ Toujours en file — le robot passera dans l’heure. Tu peux quitter la page, ça continue tout seul.';
      }
    }, 10000);
  },

  // Met la carte à jour après un échec ou un verdict « à faire à la main »
  _showApplyOutcome(id, st) {
    const card = this._findCard(id);
    if (!card) return;
    card.querySelectorAll('[data-apply-note]').forEach(el => el.remove());
    const note = document.createElement('div');
    note.className = 'phare-empty-inline';
    note.style.marginTop = '8px';
    if ((st.apply_state || '') === 'manual') {
      note.style.borderLeft = '3px solid #f5a623';
      note.textContent = `🛠️ Le robot a regardé : ${st.apply_error || 'c’est à faire à la main.'}`;
      card.appendChild(note);
      // On remet les boutons habituels (J'ai fait / Poubelle) au prochain
      // rechargement de la vue ; en attendant la carte reste informative.
      return;
    }
    note.style.borderLeft = '3px solid #e5484d';
    note.innerHTML = `⚠️ ${this._esc(st.apply_error || 'Le robot n’a pas réussi.')}
      <span style="display:inline-flex;gap:8px;margin-left:8px">
        ${st.github_pr_url ? `<a class="phare-action-link" href="${this._esc(st.github_pr_url)}" target="_blank" rel="noopener">Voir la modif préparée</a>` : ''}
        <button class="btn btn-secondary btn-sm" data-apply-retry="${this._esc(id)}">Réessayer</button>
      </span>`;
    card.appendChild(note);
    const retryBtn = note.querySelector('[data-apply-retry]');
    if (retryBtn) retryBtn.onclick = () => this._applyRetry(id, retryBtn);
  },

  // ── Actions partagées cartes + modale d'aperçu ──────────────────────
  // Chaque action met la carte à jour LOCALEMENT (retrait en fondu) au lieu
  // de re-rendre toute la page : le scroll ne bouge plus.
  // Retourne true si l'action a abouti (la modale d'aperçu s'en sert).

  async _approveAction(id, isAuto, btn, opts = {}) {
    // Garde-fou publication réelle : « Publier sur le site » modifie le site
    // en ligne, pour de vrai. On le dit AVANT, avec le nom du site quand on
    // le connaît. opts.skipConfirm : true depuis l'aperçu (modif déjà vue).
    if (isAuto && !opts.skipConfirm) {
      const siteName = this._selectedSiteName || '';
      const okGo = await Dialog.confirm(
        (siteName
          ? `La modification préparée par le robot va être publiée pour de vrai sur « ${siteName} ».`
          : 'La modification préparée par le robot va être publiée pour de vrai sur ton site.')
        + '\n\nDes contrôles automatiques tournent avant la mise en ligne, '
        + 'et tu retrouveras la modification dans « Ce qui a été fait ».',
        { title: 'Publier sur le site ?', danger: true,
          okLabel: 'Publier', cancelLabel: 'Annuler' });
      if (!okGo) return false;
    }
    const prevHtml = btn ? btn.innerHTML : '';
    const setBusy = (on) => {
      if (!btn) return;
      btn.disabled = on;
      if (on) btn.textContent = isAuto ? 'Publication…' : 'Enregistrement…';
      else btn.innerHTML = prevHtml;
    };
    setBusy(true);
    try {
      const res = await App.api.phare_merge_action({ id, force: false });
      if (res && res.ok) {
        Toast.success(res.kind === 'note_only' ? 'Marquée comme faite — à toi de jouer' : 'Publié sur ton site');
        this._removeActionCard(id);
        return true;
      }
      // Si checks KO, propose "Publier quand même"
      if (res && res.decision && res.decision !== 'merge') {
        const goOn = await Dialog.confirm(
          'Les vérifications automatiques ne sont pas toutes vertes. Publier quand même ?',
          { title: 'Vérifications incomplètes', okLabel: 'Publier quand même', cancelLabel: 'Annuler', danger: true });
        if (!goOn) { setBusy(false); return false; }
        const r2 = await App.api.phare_merge_action({ id, force: true });
        if (r2 && r2.ok) {
          Toast.success('Publié sur ton site (malgré les vérifications)');
          this._removeActionCard(id);
          return true;
        }
        Toast.friendlyError(r2 && r2.error, 'La publication n’a pas abouti. Réessaie dans un instant.');
        setBusy(false);
        return false;
      }
      Toast.friendlyError(res && res.error, 'La publication n’a pas abouti. Réessaie dans un instant.');
      setBusy(false);
      return false;
    } catch (e) { Toast.friendlyError(e); setBusy(false); return false; }
  },

  async _rejectAction(id, btn) {
    const reason = prompt("Pourquoi refuser cette proposition ?\n(Tu peux laisser vide.)", "");
    if (reason === null) return false; // Annuler → on ne touche à rien
    const prevHtml = btn ? btn.innerHTML : '';
    const restore = () => { if (btn) { btn.disabled = false; btn.innerHTML = prevHtml; } };
    if (btn) { btn.disabled = true; btn.textContent = 'Refus…'; }
    try {
      const res = await App.api.phare_reject_action({ id, reason: reason || '' });
      if (res && res.ok) {
        Toast.success('Proposition mise à la poubelle');
        this._removeActionCard(id);
        return true;
      }
      Toast.friendlyError(res && res.error, 'Le refus n’a pas pu être enregistré. Réessaie dans un instant.');
      restore();
      return false;
    } catch (e) { Toast.friendlyError(e); restore(); return false; }
  },

  // « ↩ Annuler » une modification publiée : le serveur fabrique le commit
  // inverse et le publie (revert). Confirmation concrète avant (nom du
  // site), gestion claire du cas « le site a bougé depuis » (conflit).
  async _revertAction(id, btn) {
    const siteName = this._selectedSiteName || 'ton site';
    const okGo = await Dialog.confirm(
      `Le robot va publier la modification INVERSE sur « ${siteName} » : `
      + 'le site redevient comme avant cette modification.\n\n'
      + 'Le site en ligne se met à jour en 1 à 3 minutes.',
      { title: 'Annuler cette modification ?', danger: true,
        okLabel: 'Annuler la modification', cancelLabel: 'Laisser en place' });
    if (!okGo) return false;
    const prevHtml = btn ? btn.innerHTML : '';
    if (btn) { btn.disabled = true; btn.textContent = 'Annulation…'; }
    try {
      const res = await App.api.phare_revert_action({ id });
      if (res && res.ok) {
        Toast.success('Modification annulée — le site revient comme avant (1 à 3 min).');
        this._removeActionCard(id);
        return true;
      }
      if (res && res.conflict) {
        Toast.warn((res.error || 'Le site a été modifié depuis — annulation à faire à la main.'),
                   'Annulation impossible automatiquement');
      } else {
        Toast.friendlyError(res && res.error,
          'L’annulation n’a pas abouti. Réessaie dans un instant.');
      }
      if (btn) { btn.disabled = false; btn.innerHTML = prevHtml; }
      return false;
    } catch (e) {
      Toast.friendlyError(e, 'L’annulation n’a pas abouti.');
      if (btn) { btn.disabled = false; btn.innerHTML = prevHtml; }
      return false;
    }
  },

  async _archiveAction(id, btn) {
    const sure = await Dialog.confirm(
      'Retirer cette modification de la liste « Ce qui a été fait » ?\n(La modification reste appliquée sur ton site — on la cache juste de ta vue.)',
      { title: 'Retirer de la liste', okLabel: 'Retirer', cancelLabel: 'Annuler' });
    if (!sure) return false;
    if (btn) btn.disabled = true;
    try {
      const res = await App.api.phare_archive_action({ id });
      if (res && res.ok) {
        Toast.success('Retiré de la liste');
        this._removeActionCard(id);
        return true;
      }
      Toast.friendlyError(res && res.error, 'Impossible de retirer cette ligne pour l’instant.');
      if (btn) btn.disabled = false;
      return false;
    } catch (e) { Toast.friendlyError(e); if (btn) btn.disabled = false; return false; }
  },

  // Retire une carte de la page avec un petit fondu, puis remet à jour le
  // compteur de la section et le message « rien à faire » si besoin.
  _removeActionCard(id) {
    delete this._currentActions[id];
    let card = null;
    document.querySelectorAll('.phare-action[data-aid]').forEach(el => {
      if (el.dataset.aid === String(id)) card = el;
    });
    if (!card) return;
    const list = card.parentElement;
    card.style.transition = 'opacity .25s ease, transform .25s ease';
    card.style.opacity = '0';
    card.style.transform = 'translateY(-4px)';
    setTimeout(() => {
      card.remove();
      this._refreshSectionAfterRemoval(list);
    }, 260);
  },

  _refreshSectionAfterRemoval(list) {
    if (!list || !list.id) return;
    const remaining = list.querySelectorAll('.phare-action').length;
    const section = list.closest('.phare-section');
    const sub = section ? section.querySelector('.phare-section-sub') : null;
    if (list.id === 'ph-todo-list') {
      if (sub) sub.textContent = remaining === 0
        ? 'Rien en attente — tu peux respirer.'
        : `${remaining} proposition${remaining > 1 ? 's' : ''} des robots, à valider ou refuser.`;
      if (remaining === 0) {
        list.innerHTML = `<div class="phare-empty-inline">✓ Rien à valider pour l'instant. Les robots travaillent en arrière-plan.</div>`;
      }
    } else if (list.id === 'ph-done-list') {
      if (sub) sub.textContent = remaining === 0
        ? 'Pas encore de modifications appliquées.'
        : `Les ${remaining} dernières modifications validées.`;
      if (remaining === 0) {
        list.innerHTML = `<div class="phare-empty-inline">Quand tu valideras une proposition, elle apparaîtra ici.</div>`;
      }
    }
  },

  // ════════════════════════════════════════════════════════════════════
  //  MODAL — aperçu d'une proposition (détail complet + preview visuelle)
  // ════════════════════════════════════════════════════════════════════
  _openPreviewDialog(a) {
    const agentLabel = this._agentShortName(a.agent || '');
    const date = this._frDate(a.created_at);
    const impact = Math.max(0, Math.min(5, a.impact || 0));
    const impactDots = impact
      ? '●'.repeat(impact) + '○'.repeat(5 - impact)
      : '';
    const detail = a.detail_md || a.summary || '';
    const previewUrl = a.netlify_preview_url || '';
    const prUrl = a.github_pr_url || '';

    const dlg = document.createElement('div');
    dlg.className = 'phare-modal phare-preview-modal';
    dlg.innerHTML = `
      <div class="phare-modal-backdrop" data-close></div>
      <div class="phare-modal-card phare-preview-card">
        <header class="phare-modal-head">
          <div>
            <div class="phare-kicker mb-1">APERÇU DE LA PROPOSITION</div>
            <h2 class="text-xl font-semibold">${this._esc(a.title || a.kind || '—')}</h2>
            <div class="phare-action-meta" style="margin-top:6px">
              Proposition de ${this._esc(agentLabel)} · ${date || '—'}
              ${impactDots ? `<span class="phare-action-impact" title="Impact estimé">${impactDots} <span style="font-size:11px">impact ${impact}/5</span></span>` : ''}
            </div>
          </div>
          <button class="phare-modal-close" data-close aria-label="Fermer">×</button>
        </header>
        <div class="phare-modal-body">
          ${a.simple_what ? `<div class="phare-preview-detail" style="font-size:14px;line-height:1.55"><strong>En clair :</strong> ${this._esc(a.simple_what)}</div>` : ''}
          ${detail ? `<div class="phare-preview-detail">${this._mdToHtml(detail)}</div>` : ''}
          ${previewUrl ? `
            <div class="phare-preview-section">
              <div class="phare-preview-section-head">
                <h3>Aperçu visuel du site avec les changements</h3>
                <a class="phare-action-link" href="${this._esc(previewUrl)}" target="_blank" rel="noopener">Ouvrir en plein écran ↗</a>
              </div>
              <div class="phare-preview-iframe-wrap">
                <iframe class="phare-preview-iframe" src="${this._esc(previewUrl)}" loading="lazy" title="Aperçu du site"></iframe>
              </div>
              <p class="phare-preview-hint">Si l'aperçu ne s'affiche pas, clique sur « Ouvrir en plein écran ».</p>
            </div>
          ` : `
            <div class="phare-preview-section phare-preview-section--empty">
              <div class="phare-preview-empty-icon">${this._isAuto(a) ? '🤖' : '👤'}</div>
              ${this._isAuto(a) ? `
                <p><strong>Modification prête à publier (sans aperçu visuel).</strong></p>
                <p class="phare-preview-empty-sub">Si tu cliques sur « Publier sur le site », le robot pousse le changement sur ton site en live (avec contrôles automatiques avant).</p>
              ` : `
                <p><strong>👤 À toi de le faire — pas de publication automatique.</strong></p>
                <p class="phare-preview-empty-sub">C'est un conseil à appliquer toi-même. Cliquer sur « J'ai fait, suivant » <em>ne déclenche aucune action sur ton site</em> : ça marque juste la proposition comme lue pour qu'elle disparaisse de la liste.</p>
              `}
            </div>
          `}
          ${prUrl ? `
            <div class="phare-preview-section">
              <h3>Modifications de code</h3>
              <a class="phare-action-link" href="${this._esc(prUrl)}" target="_blank" rel="noopener">Voir le détail technique sur GitHub ↗</a>
            </div>
          ` : ''}
        </div>
        <footer class="phare-modal-foot">
          <button class="btn btn-secondary" data-close>Fermer</button>
          <button class="btn btn-secondary btn-reject" data-preview-reject="${this._esc(a.id || '')}">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" style="margin-right:6px;vertical-align:-2px"><path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m3 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/></svg>
            Poubelle
          </button>
          <button class="btn btn-primary ${this._isAuto(a) ? 'btn-auto' : 'btn-manual'}" data-preview-approve="${this._esc(a.id || '')}" data-approve-auto="${this._isAuto(a) ? '1' : '0'}">
            ${this._isAuto(a)
              ? `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" style="margin-right:6px;vertical-align:-2px"><path d="M5 3l14 9-14 9V3z"/></svg>Publier sur le site`
              : `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" style="margin-right:6px;vertical-align:-2px"><path d="M20 6L9 17l-5-5"/></svg>J'ai fait, suivant`}
          </button>
        </footer>
      </div>
    `;
    document.body.appendChild(dlg);
    // Fermer avec Échap — l'écouteur est retiré quelle que soit la façon de fermer
    const onKey = (e) => { if (e.key === 'Escape') close(); };
    const close = () => { document.removeEventListener('keydown', onKey); dlg.remove(); };
    document.addEventListener('keydown', onKey);
    dlg.querySelectorAll('[data-close]').forEach(el => el.onclick = close);
    // Publier / Poubelle : on appelle DIRECTEMENT les actions partagées
    // (plus de re-clic fragile sur les boutons de la carte derrière).
    const approveBtn = dlg.querySelector('[data-preview-approve]');
    const rejectBtn = dlg.querySelector('[data-preview-reject]');
    if (approveBtn) {
      approveBtn.onclick = async () => {
        // skipConfirm : l'aperçu vient d'être regardé, pas de double fenêtre.
        const ok = await this._approveAction(a.id, this._isAuto(a), approveBtn,
                                             { skipConfirm: true });
        if (ok) close();
      };
    }
    if (rejectBtn) {
      rejectBtn.onclick = async () => {
        const ok = await this._rejectAction(a.id, rejectBtn);
        if (ok) close();
      };
    }
  },

  // Markdown minimaliste : paragraphes + gras + retours à la ligne
  _mdToHtml(md) {
    const esc = this._esc(md);
    const withBold = esc.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    const paras = withBold.split(/\n{2,}/).map(p => `<p>${p.replace(/\n/g, '<br>')}</p>`).join('');
    return paras;
  },

  _bulletinCard(b) {
    const date = this._frDate(b.created_at);
    const summary = (b.detail_md || b.summary || '').slice(0, 320);
    return `
      <article class="phare-bulletin">
        <header class="phare-bulletin-head">
          <span class="phare-bulletin-icon">📰</span>
          <div>
            <div class="phare-bulletin-label">Bulletin du jour</div>
            <div class="phare-bulletin-title">${this._esc(b.title || 'Résumé de la journée')}</div>
          </div>
          <span class="phare-bulletin-date">${date}</span>
        </header>
        ${summary ? `<p class="phare-bulletin-body">${this._esc(summary)}${(b.detail_md || '').length > 320 ? '…' : ''}</p>` : ''}
      </article>
    `;
  },

  _kpi(label, value, sub, tone) {
    return `
      <div class="phare-kpi${tone ? ' phare-kpi--' + tone : ''}">
        <div class="phare-kpi-label">${this._esc(label)}</div>
        <div class="phare-kpi-value">${this._esc(String(value))}</div>
        <div class="phare-kpi-sub">${this._esc(sub)}</div>
      </div>
    `;
  },

  _backHeader() {
    return `
      <button class="phare-back" data-act="back">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M19 12H5M12 19l-7-7 7-7"/></svg>
        Tes sites
      </button>
    `;
  },

  // ════════════════════════════════════════════════════════════════════
  //  VUE COULISSES — les 8 robots (caché, accessible depuis En coulisses)
  // ════════════════════════════════════════════════════════════════════
  async _renderCoulisses(container) {
    container.innerHTML = `
      <section class="phare-page animate-fade-in">
        <button class="phare-back" data-act="back">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M19 12H5M12 19l-7-7 7-7"/></svg>
          Retour
        </button>
        <header class="phare-home-head">
          <div class="phare-home-head-left">
            <div class="phare-kicker">EN COULISSES</div>
            <h1 class="phare-title">Les robots.</h1>
            <p class="phare-subtitle">Chacun a sa spécialité. Ensemble, ils gardent tes sites au sommet, 24/7.</p>
          </div>
        </header>
        <div id="ph-automerge-panel"></div>
        <div id="ph-coulisses-grid"><div class="phare-loading">Chargement…</div></div>
      </section>
    `;
    // Retour : revient là d'où on est entré en Coulisses (accueil ou fiche site),
    // mémorisé dans _go() — plus de retour vers une fiche résiduelle.
    container.querySelector('[data-act="back"]').onclick = () =>
      this._go(this._coulissesFrom === 'site' && this.selectedSite ? 'site' : 'home');
    this._renderAutomergePanel();
    let agents = this._defaultAgents();
    if (App.api) {
      try {
        const res = await App.api.phare_agents_status();
        if (res && res.ok && Array.isArray(res.agents)) agents = res.agents;
      } catch (e) { /* fallback */ }
    }
    const grid = document.getElementById('ph-coulisses-grid');
    grid.innerHTML = `
      <div class="phare-agents-grid">
        ${agents.map(a => `
          <article class="phare-agent-card">
            <div class="phare-agent-head">
              <div class="phare-agent-emoji">${a.emoji || '🤖'}</div>
              <div class="phare-agent-name-block">
                <div class="phare-agent-name">${this._esc(a.label || a.name)}</div>
                <div class="phare-agent-tagline">${this._esc(a.tagline || '')}</div>
              </div>
            </div>
            <p class="phare-agent-desc">${this._esc(a.description || '')}</p>
            <div class="phare-agent-meta">
              <div><span class="lbl">Quand</span><span class="val">${this._esc(a.cadence || '—')}</span></div>
              <div><span class="lbl">Dernier passage</span><span class="val">${a.last_run_at ? this._relTime(a.last_run_at) : 'jamais'}</span></div>
            </div>
            <footer class="phare-agent-foot">
              ${a.name !== 'chef_orchestre'
                ? `<button class="btn btn-secondary btn-sm" data-run="${this._esc(a.name)}">Lancer maintenant</button>`
                : `<span class="phare-agent-note">Plan mensuel — 1er du mois 9h</span>`}
            </footer>
          </article>
        `).join('')}
      </div>
    `;
    grid.querySelectorAll('[data-run]').forEach(b => {
      b.onclick = async () => {
        // Périmètre réel : un site précis seulement si on vient de sa fiche,
        // sinon le robot passe sur tous les sites suivis.
        const onSite = (this._coulissesFrom === 'site' && this.selectedSite) ? this.selectedSite : null;
        const scope = onSite
          ? `sur le site « ${this._selectedSiteName || 'sélectionné'} »`
          : 'sur tous les sites suivis';
        const sure = await Dialog.confirm(
          `Lancer ce robot maintenant, ${scope} ?`,
          { title: 'Lancer maintenant', okLabel: 'Lancer', cancelLabel: 'Annuler' });
        if (!sure) return;
        b.disabled = true; const lbl = b.textContent; b.textContent = 'Lancement…';
        try {
          const payload = { agent: b.dataset.run };
          if (onSite) payload.site_id = onSite;
          const res = await App.api.phare_run_agent(payload);
          if (res && res.ok) Toast.success(`Mission lancée en arrière-plan ${scope}`);
          else Toast.friendlyError(res && res.error, 'La mission n’a pas pu être lancée. Réessaie dans un instant.');
        } catch (e) { Toast.friendlyError(e); }
        finally { b.disabled = false; b.textContent = lbl; }
      };
    });
  },

  // ════════════════════════════════════════════════════════════════════
  //  PANNEAU PUBLICATION AUTO — interrupteur auto-merge (vue Coulisses)
  // ════════════════════════════════════════════════════════════════════
  async _renderAutomergePanel() {
    const host = document.getElementById('ph-automerge-panel');
    if (!host || !App.api || typeof App.api.phare_automerge_get !== 'function') return;
    let enabled = false;
    try {
      const res = await App.api.phare_automerge_get();
      if (!res || !res.ok) return;          // base injoignable → pas de panneau
      enabled = !!res.enabled;
    } catch (e) { return; }

    const paint = (on, busy) => {
      host.innerHTML = `
        <div class="phare-automerge ${on ? 'is-on' : ''}">
          <div class="phare-automerge-text">
            <div class="phare-automerge-title">
              ${on ? '🟢' : '⚪'} Le robot agit seul (corrections sûres)
            </div>
            <p class="phare-automerge-desc">
              ${on
                ? 'Le robot applique ET publie tout seul les corrections sûres (titres de pages internes, descriptions, images, plan du site, redirections) — jamais ta page d’accueil, jamais le design. Au fil de l’eau, quelques-unes par heure au maximum. Tu es prévenu à chaque fois, et tout reste annulable (surveillance du trafic 14 jours).'
                : 'Aujourd’hui, chaque correction attend ton OK. Active pour que le robot applique ET publie tout seul les corrections sûres (titres de pages internes, descriptions, images, plan du site, redirections) — jamais ta page d’accueil, jamais le design. Il avance en douceur, te prévient à chaque fois, et tout est annulable.'}
            </p>
          </div>
          <button class="btn ${on ? 'btn-secondary' : 'btn-primary'}" data-act="toggle" ${busy ? 'disabled' : ''}>
            ${busy ? '…' : (on ? 'Couper' : 'Activer')}
          </button>
        </div>`;
      host.querySelector('[data-act="toggle"]').onclick = async () => {
        const next = !on;
        if (next) {
          const sure = await Dialog.confirm(
            'Le robot va APPLIQUER et PUBLIER tout seul les corrections sûres ' +
            '(titres de pages internes, descriptions, images, plan du site, ' +
            'redirections) — jamais ta page d’accueil, jamais le design.\n\n' +
            'Il avance en douceur (quelques-unes par heure au maximum), te ' +
            'prévient à chaque fois, et tout est annulable — si le trafic d’un ' +
            'site décroche dans les 14 jours, tu es alerté pour revenir en arrière.',
            { title: 'Laisser le robot agir seul ?', okLabel: 'Activer',
              cancelLabel: 'Annuler', danger: true });
          if (!sure) return;
        }
        paint(on, true);
        try {
          const r = await App.api.phare_automerge_set({ enabled: next });
          if (r && r.ok) {
            paint(!!r.enabled, false);
            Toast.success(r.enabled
              ? 'C’est parti — le robot agit seul sur les corrections sûres'
              : 'Robot autonome coupé — tout repasse par ton OK');
          } else {
            paint(on, false);
            Toast.friendlyError(r && r.error, 'Le réglage n’a pas pu être enregistré. Réessaie dans un instant.');
          }
        } catch (e) {
          paint(on, false);
          Toast.friendlyError(e);
        }
      };
    };
    paint(enabled, false);
  },

  // ════════════════════════════════════════════════════════════════════
  //  ONBOARDING — bulle au premier lancement
  // ════════════════════════════════════════════════════════════════════
  _maybeShowOnboarding() {
    try { if (localStorage.getItem(this._onboardKey)) return; } catch (e) { return; }
    const dlg = document.createElement('div');
    dlg.className = 'phare-onboard';
    dlg.innerHTML = `
      <div class="phare-onboard-backdrop"></div>
      <div class="phare-onboard-card">
        <div class="phare-onboard-emoji">💡</div>
        <h2>Bienvenue dans Le Phare</h2>
        <p class="phare-onboard-lead">Voici tes sites. Sur chacun, <strong>des robots Claude</strong> préparent des améliorations SEO pendant que tu dors.</p>
        <div class="phare-onboard-steplabel">Tu as juste deux choses à faire :</div>
        <div class="phare-onboard-steps">
          <div class="phare-onboard-step">
            <div class="phare-onboard-stepnum">1</div>
            <div class="phare-onboard-steptext"><strong>Clique sur un site</strong> pour voir ce que les robots te proposent.</div>
          </div>
          <div class="phare-onboard-step">
            <div class="phare-onboard-stepnum">2</div>
            <div class="phare-onboard-steptext">Pour chaque proposition : <strong>OK, applique</strong> ou <strong>Poubelle</strong>. C'est tout.</div>
          </div>
        </div>
        <p class="phare-onboard-foot">Pas besoin de comprendre le code ou le SEO — si ça te plaît, tu valides. Sinon, tu jettes.</p>
        <button class="btn btn-primary phare-onboard-cta" data-close>J'ai compris, montre-moi mes sites</button>
      </div>
    `;
    document.body.appendChild(dlg);
    dlg.querySelector('[data-close]').onclick = () => {
      try { localStorage.setItem(this._onboardKey, '1'); } catch (e) {}
      dlg.remove();
    };
  },

  // ════════════════════════════════════════════════════════════════════
  //  MODAL — ajout simplifié (juste l'URL, Claude remplit le reste)
  // ════════════════════════════════════════════════════════════════════
  _openQuickAddDialog() {
    const dlg = document.createElement('div');
    dlg.className = 'phare-modal';
    dlg.innerHTML = `
      <div class="phare-modal-backdrop" data-close></div>
      <div class="phare-modal-card" style="max-width:520px">
        <header class="phare-modal-head">
          <div>
            <div class="phare-kicker mb-1">NOUVEAU SITE</div>
            <h2 class="text-xl font-semibold">Ajouter un site</h2>
          </div>
          <button class="phare-modal-close" data-close aria-label="Fermer">×</button>
        </header>
        <div class="phare-modal-body" data-step="form">
          <p class="text-sm text-text-muted mb-4">
            Colle juste l'adresse du site. Claude analyse la page et remplit tout le reste : nom, pages à surveiller, secteur, configuration. Tu pourras ajuster après si besoin.
          </p>
          <form id="ph-quick-form" class="space-y-3">
            <div>
              <label class="text-xs font-semibold text-text-muted uppercase tracking-wider">URL du site *</label>
              <input type="text" name="phare_site_url" id="ph-quick-url"
                     placeholder="exemple : cabinet-dupont.fr"
                     class="phare-input phare-input--url"
                     autocomplete="off" autocorrect="off" autocapitalize="off"
                     spellcheck="false" required
                     data-1p-ignore data-lpignore="true" data-form-type="other">
            </div>
            <p class="text-xs text-text-muted" style="margin-top:4px">
              Tu peux écrire juste le domaine (<code>cabinet-dupont.fr</code>) ou l'URL complète (<code>https://cabinet-dupont.fr</code>).
            </p>
          </form>
        </div>
        <div class="phare-modal-body" data-step="loading" style="display:none;text-align:center;padding:32px 24px">
          <div class="phare-loading" style="font-size:15px;margin-bottom:8px">⏳ Claude analyse le site…</div>
          <div class="text-xs text-text-muted">Lecture de la page d'accueil, repérage du métier et des pages clés. Quelques secondes.</div>
        </div>
        <div class="phare-modal-body" data-step="done" style="display:none">
          <div data-summary></div>
        </div>
        <footer class="phare-modal-foot" data-foot="form">
          <button class="btn btn-secondary" data-close>Annuler</button>
          <button class="btn btn-primary" data-save>Créer le site</button>
        </footer>
        <footer class="phare-modal-foot" data-foot="done" style="display:none">
          <button class="btn btn-primary" data-close>Terminé</button>
        </footer>
      </div>
    `;
    document.body.appendChild(dlg);
    let busy = false;     // analyse en cours → fermeture et double envoi bloqués
    let created = false;  // site créé → on peut fermer sans garde de saisie
    const onKey = (e) => { if (e.key === 'Escape') close(); };
    const close = async (force = false) => {
      if (busy) return; // pas de fermeture pendant l'analyse
      if (!force && !created) {
        const typed = (dlg.querySelector('#ph-quick-url')?.value || '').trim();
        if (typed) {
          const sure = await Dialog.confirm(
            'Fermer sans ajouter le site ? L’adresse saisie sera perdue.',
            { title: 'Fermer la fenêtre', okLabel: 'Fermer', cancelLabel: 'Continuer', danger: true });
          if (!sure) return;
        }
      }
      document.removeEventListener('keydown', onKey);
      dlg.remove();
      // Si un site a été créé, on rafraîchit la grille quelle que soit la
      // façon de fermer (bouton Terminé, croix, fond, Échap).
      if (created && this.view === 'home') this._renderHome(document.getElementById('content'));
    };
    document.addEventListener('keydown', onKey);
    dlg.querySelectorAll('[data-close]').forEach(el => el.onclick = () => close());
    const showStep = (step) => {
      dlg.querySelectorAll('[data-step]').forEach(el => {
        el.style.display = el.dataset.step === step ? '' : 'none';
      });
      dlg.querySelectorAll('[data-foot]').forEach(el => {
        el.style.display = el.dataset.foot === (step === 'done' ? 'done' : 'form') ? '' : 'none';
      });
    };

    const saveBtn = dlg.querySelector('[data-save]');
    const setBusy = (on) => {
      busy = on;
      saveBtn.disabled = on;
      saveBtn.textContent = on ? 'Analyse en cours…' : 'Créer le site';
      // Annuler et la croix sont neutralisés pendant l'analyse
      dlg.querySelectorAll('button[data-close]').forEach(el => { el.disabled = on; });
    };

    // Entrée dans le champ = clic sur « Créer le site » (jamais de rechargement
    // de page par soumission implicite du formulaire).
    dlg.querySelector('#ph-quick-form').onsubmit = (e) => {
      e.preventDefault();
      if (!busy) saveBtn.click();
    };

    saveBtn.onclick = async () => {
      if (busy) return; // anti double création
      const url = (dlg.querySelector('#ph-quick-url')?.value || '').trim();
      if (!url) { Toast.error('Mets l’adresse du site.'); return; }
      setBusy(true);
      showStep('loading');
      let res;
      try { res = await App.api.phare_site_quick_add({ url }); }
      catch (e) { Toast.friendlyError(e); setBusy(false); showStep('form'); return; }
      if (!res || !res.ok) {
        Toast.friendlyError(res && res.error, 'Le site n’a pas pu être ajouté. Vérifie l’adresse, puis réessaie.');
        setBusy(false);
        showStep('form');
        return;
      }
      const site = res.site || {};
      const ac = res.autoconfig || {};
      const det = ac.detected || {};
      const paths = Array.isArray(site.key_paths) ? site.key_paths : ['/'];
      const summary = `
        <div style="text-align:center;margin-bottom:18px">
          <div style="font-size:36px;line-height:1">✨</div>
          <h3 style="font-size:18px;font-weight:600;margin-top:8px">${this._esc(site.name || site.domain)}</h3>
          <p class="text-xs text-text-muted">${this._esc(site.domain)}</p>
        </div>
        <div class="phare-summary-block">
          <div class="phare-summary-row">
            <span class="phare-summary-label">Type</span>
            <span>${site.is_external_client ? '🌐 Site client externe' : '🏠 Site Triskell'}</span>
          </div>
          <div class="phare-summary-row">
            <span class="phare-summary-label">Techno détectée</span>
            <span>${this._esc(site.stack || 'html')}</span>
          </div>
          ${site.notes ? `
          <div class="phare-summary-row">
            <span class="phare-summary-label">Note</span>
            <span>${this._esc(site.notes)}</span>
          </div>` : ''}
          <div class="phare-summary-row">
            <span class="phare-summary-label">Pages surveillées</span>
            <span>${paths.map(p => `<code style="background:hsl(var(--surface-elevated));border:1px solid hsl(var(--border));padding:1px 5px;border-radius:3px;margin-right:4px">${this._esc(p)}</code>`).join(' ')}</span>
          </div>
        </div>
        <p class="text-xs text-text-muted" style="margin-top:14px;text-align:center">
          ${ac.claude_used ? 'Claude a analysé la homepage.' : (ac.fetched ? 'Page lue (Claude non disponible — défauts utilisés).' : 'Page injoignable — défauts utilisés.')}
          Tu peux ajuster les détails depuis la fiche du site.
        </p>
      `;
      dlg.querySelector('[data-summary]').innerHTML = summary;
      created = true;
      setBusy(false);
      showStep('done');
      Toast.success('Site ajouté — les robots prennent le relais');
    };

    setTimeout(() => dlg.querySelector('#ph-quick-url')?.focus(), 50);
  },

  // ════════════════════════════════════════════════════════════════════
  //  MODAL — éditer un site existant (form complet, pour ajustements)
  // ════════════════════════════════════════════════════════════════════
  _openSiteDialog({ externalOnly = false, site = null } = {}) {
    const isEdit = !!(site && site.id);
    const s = site || {};
    const dlg = document.createElement('div');
    dlg.className = 'phare-modal';
    dlg.innerHTML = `
      <div class="phare-modal-backdrop" data-close></div>
      <div class="phare-modal-card">
        <header class="phare-modal-head">
          <div>
            <div class="phare-kicker mb-1">${isEdit ? 'RÉGLAGES DU SITE' : 'NOUVEAU SITE'}</div>
            <h2 class="text-xl font-semibold">${isEdit ? (s.name || 'Modifier le site') : 'Ajouter un site'}</h2>
          </div>
          <button class="phare-modal-close" data-close aria-label="Fermer">×</button>
        </header>
        <div class="phare-modal-body">
          <p class="text-sm text-text-muted mb-4">
            Remplis les infos du site. Les robots commenceront à le surveiller dès la prochaine heure.
          </p>
          <form id="ph-site-form" class="space-y-3">
            ${this._field('name', 'Nom du site', s.name || '', 'Ex : Cabinet Dupont', true)}
            ${this._field('domain', 'Domaine', s.domain || '', 'cabinet-dupont.fr', true)}
            ${this._field('priority', 'Priorité (0-100)', String(s.priority ?? 50), '50', false, 'number', 'min="0" max="100" step="1"')}
            ${this._textareaField('key_paths', 'Pages clés à surveiller (1 par ligne, 10 max)', (s.key_paths || ['/']).join('\n'), '/, /contact, /services…')}
            ${this._field('notes', 'Notes internes', s.notes || '', '(secteur, particularités…)', false)}
            <label class="flex items-center gap-2 pt-2">
              <input type="checkbox" name="is_external_client" ${(externalOnly || s.is_external_client) ? 'checked' : ''}>
              <span class="text-sm">Site d'un client externe</span>
            </label>
            <details style="border:1px solid hsl(var(--border));border-radius:8px;padding:10px 12px">
              <summary style="cursor:pointer;font-weight:600;font-size:13px">Réglages techniques (avancé)</summary>
              <p class="text-xs text-text-muted" style="margin:8px 0 0">Ces champs servent aux robots — n'y touche pas sans raison.</p>
              <div class="space-y-3" style="margin-top:10px">
                ${this._field('repo_github', 'Repo GitHub (owner/repo)', s.repo_github || '', 'Jordan-Bourillot/cabinet-dupont', false)}
                ${this._field('repo_branch_main', 'Branche de production', s.repo_branch_main || 'main', 'main', false)}
                ${this._field('netlify_site_id', 'Netlify site ID', s.netlify_site_id || '', '(uuid Netlify)', false)}
                ${this._selectField('stack', 'Techno', s.stack || 'html', ['astro','next','vite','html','autre'])}
              </div>
            </details>
          </form>
        </div>
        <footer class="phare-modal-foot">
          ${isEdit ? `<button class="btn btn-secondary" data-deactivate style="margin-right:auto;color:hsl(var(--danger-text))">Ne plus suivre ce site</button>` : ''}
          <button class="btn btn-secondary" data-close>Annuler</button>
          <button class="btn btn-primary" data-save>${isEdit ? 'Enregistrer' : 'Créer le site'}</button>
        </footer>
      </div>
    `;
    document.body.appendChild(dlg);
    const form = dlg.querySelector('#ph-site-form');
    // Garde anti-perte de saisie : si un champ a été modifié, on confirme
    // avant de fermer (croix, Annuler, clic sur le fond, Échap).
    let dirty = false;
    form.addEventListener('input', () => { dirty = true; });
    const onKey = (e) => { if (e.key === 'Escape') close(); };
    const close = async (force = false) => {
      if (!force && dirty) {
        const sure = await Dialog.confirm(
          'Fermer sans enregistrer ? Tes modifications seront perdues.',
          { title: 'Fermer la fenêtre', okLabel: 'Fermer sans enregistrer', cancelLabel: 'Continuer', danger: true });
        if (!sure) return;
      }
      document.removeEventListener('keydown', onKey);
      dlg.remove();
    };
    document.addEventListener('keydown', onKey);
    dlg.querySelectorAll('[data-close]').forEach(el => el.onclick = () => close());
    // Entrée dans un champ ne doit jamais recharger la page
    form.onsubmit = (e) => { e.preventDefault(); dlg.querySelector('[data-save]').click(); };

    dlg.querySelector('[data-save]').onclick = async () => {
      const saveBtn = dlg.querySelector('[data-save]');
      if (saveBtn.disabled) return;
      const fd = new FormData(form);
      // Priorité : bornée 0-100, 0 accepté (champ vide → 50)
      let priority = parseInt((fd.get('priority') ?? '').toString().trim(), 10);
      if (isNaN(priority)) priority = 50;
      priority = Math.max(0, Math.min(100, priority));
      const allPaths = (fd.get('key_paths') || '/').toString().split('\n').map(x => x.trim()).filter(Boolean);
      const payload = {
        id: s.id || undefined,
        name: (fd.get('name') || '').toString().trim(),
        domain: (fd.get('domain') || '').toString().trim().toLowerCase(),
        repo_github: (fd.get('repo_github') || '').toString().trim(),
        repo_branch_main: (fd.get('repo_branch_main') || 'main').toString().trim(),
        netlify_site_id: (fd.get('netlify_site_id') || '').toString().trim(),
        stack: (fd.get('stack') || 'html').toString().trim(),
        priority,
        key_paths: allPaths.slice(0, 10),
        notes: (fd.get('notes') || '').toString().trim(),
        is_external_client: form.querySelector('[name="is_external_client"]').checked,
        is_active: true,
      };
      if (!payload.name || !payload.domain) {
        Toast.error('Le nom et le domaine sont obligatoires.');
        return;
      }
      saveBtn.disabled = true;
      const lbl = saveBtn.textContent;
      saveBtn.textContent = 'Enregistrement…';
      try {
        const res = await App.api.phare_site_upsert(payload);
        if (!res || !res.ok) {
          Toast.friendlyError(res && res.error, 'Le site n’a pas pu être enregistré. Réessaie dans un instant.');
          saveBtn.disabled = false; saveBtn.textContent = lbl;
          return;
        }
        await close(true);
        Toast.success(isEdit ? 'Site mis à jour' : 'Site ajouté — les robots prennent le relais');
        if (allPaths.length > 10) {
          Toast.info(`Seules les 10 premières pages clés ont été gardées (${allPaths.length} saisies).`);
        }
        if (isEdit && this.view === 'site') this._renderSite(document.getElementById('content'));
        else this._renderHome(document.getElementById('content'));
      } catch (e) {
        Toast.friendlyError(e);
        saveBtn.disabled = false; saveBtn.textContent = lbl;
      }
    };

    // « Ne plus suivre ce site » : les robots arrêtent de le surveiller,
    // il disparaît de la liste (le site lui-même reste en ligne).
    const deactBtn = dlg.querySelector('[data-deactivate]');
    if (deactBtn) {
      deactBtn.onclick = async () => {
        const sure = await Dialog.confirm(
          `Ne plus suivre « ${s.name || s.domain || 'ce site'} » ?\n\nLes robots arrêtent de le surveiller et il disparaît de ta liste. Le site lui-même n'est pas touché — il reste en ligne.`,
          { title: 'Ne plus suivre ce site', okLabel: 'Ne plus suivre', cancelLabel: 'Annuler', danger: true });
        if (!sure) return;
        deactBtn.disabled = true;
        const prev = deactBtn.textContent;
        deactBtn.textContent = 'Retrait…';
        try {
          const res = await App.api.phare_site_deactivate({ id: s.id });
          if (res && res.ok) {
            await close(true);
            Toast.success('Site retiré du suivi — les robots ne s’en occupent plus');
            this.selectedSite = null;
            this._go('home');
            return;
          }
          Toast.friendlyError(res && res.error, 'Le site n’a pas pu être retiré du suivi. Réessaie dans un instant.');
          deactBtn.disabled = false; deactBtn.textContent = prev;
        } catch (e) {
          Toast.friendlyError(e);
          deactBtn.disabled = false; deactBtn.textContent = prev;
        }
      };
    }
    setTimeout(() => dlg.querySelector('input[name="name"]').focus(), 50);
  },

  _field(name, label, value, placeholder, required = false, type = 'text', extra = '') {
    return `
      <div>
        <label class="text-xs font-semibold text-text-muted uppercase tracking-wider">${this._esc(label)}${required ? ' *' : ''}</label>
        <input type="${type}" name="${this._esc(name)}" value="${this._esc(value)}"
               placeholder="${this._esc(placeholder)}"
               class="phare-input" ${required ? 'required' : ''} ${extra}>
      </div>`;
  },
  _selectField(name, label, value, options) {
    return `
      <div>
        <label class="text-xs font-semibold text-text-muted uppercase tracking-wider">${this._esc(label)}</label>
        <select name="${this._esc(name)}" class="phare-input">
          ${options.map(o => `<option value="${o}" ${o === value ? 'selected' : ''}>${o}</option>`).join('')}
        </select>
      </div>`;
  },
  _textareaField(name, label, value, placeholder) {
    return `
      <div>
        <label class="text-xs font-semibold text-text-muted uppercase tracking-wider">${this._esc(label)}</label>
        <textarea name="${this._esc(name)}" rows="3" placeholder="${this._esc(placeholder)}"
                  class="phare-input" style="font-family:ui-monospace,monospace;font-size:13px">${this._esc(value)}</textarea>
      </div>`;
  },

  // ════════════════════════════════════════════════════════════════════
  //  Helpers — emoji, libellés, fmt
  // ════════════════════════════════════════════════════════════════════
  _agentShortName(agent) {
    const m = {
      auditeur: "l'Auditeur",
      veilleur: 'le Veilleur',
      redacteur: 'le Rédacteur',
      optimiseur_onpage: "l'Optimiseur",
      tisseur: 'le Tisseur',
      chasseur_backlinks: 'le Chasseur de backlinks',
      analyste: "l'Analyste",
      chef_orchestre: "le Chef d'Orchestre",
    };
    return m[agent] || agent || 'un robot';
  },

  _actionEmoji(agent) {
    const m = {
      auditeur: '🔍', veilleur: '🎯', redacteur: '✍️',
      optimiseur_onpage: '⚡', tisseur: '🕸️',
      chasseur_backlinks: '🪝', analyste: '📊', chef_orchestre: '👑',
    };
    return m[agent] || '💡';
  },

  _defaultAgents() {
    return [
      { name: 'auditeur', label: "L'Auditeur Technique", emoji: '🔍',
        tagline: 'Détecte tout ce qui freine.',
        description: "Passe chaque site au peigne fin : pages lentes, balises manquantes, liens cassés. Note de santé sur 100.",
        cadence: 'Lundi 6h-22h, 1 site par heure' },
      { name: 'veilleur', label: 'Le Veilleur Mots-Clés', emoji: '🎯',
        tagline: 'Trouve les mots-clés qui payent.',
        description: "Analyse tes positions Google et la concurrence pour repérer les mots-clés à fort potentiel.",
        cadence: 'Lundi & jeudi 7h' },
      { name: 'redacteur', label: 'Le Rédacteur', emoji: '✍️',
        tagline: 'Écrit comme un humain. Mieux.',
        description: "Produit des articles SEO complets à partir des mots-clés trouvés par le Veilleur.",
        cadence: 'À la demande' },
      { name: 'optimiseur_onpage', label: "L'Optimiseur On-Page", emoji: '⚡',
        tagline: 'Affûte chaque page au scalpel.',
        description: "Réécrit titres, descriptions, balises et alts pour booster ton référencement.",
        cadence: 'Mar/Mer/Ven 10h' },
      { name: 'tisseur', label: 'Le Tisseur', emoji: '🕸️',
        tagline: 'Relie tous tes sites en cocon.',
        description: "Maillage interne + inter-sites Triskell. Détecte les pages orphelines.",
        cadence: 'Lundi 9h' },
      { name: 'chasseur_backlinks', label: 'Le Chasseur de Backlinks', emoji: '🪝',
        tagline: 'Va chercher les liens externes.',
        description: "Identifie les opportunités d'obtenir des liens depuis d'autres sites.",
        cadence: 'Mercredi 9h' },
      { name: 'analyste', label: "L'Analyste", emoji: '📊',
        tagline: 'Te dit la vérité chaque matin.',
        description: "Lit tes métriques et te dit ce qui monte, ce qui descend, et ce qu'il faut faire.",
        cadence: 'Tous les jours 8h' },
      { name: 'chef_orchestre', label: "Le Chef d'Orchestre", emoji: '👑',
        tagline: 'Le cerveau stratégique. Opus.',
        description: "Une fois par mois, le modèle Claude le plus puissant trace le plan du mois pour les 7 autres.",
        cadence: '1er du mois 9h' },
    ];
  },

  _previewSites() {
    return [
      { id: 'demo1', name: 'Pack Électricien', domain: 'pack-elec.triskell-studio.fr',
        is_external_client: false, health: 92, health_tone: 'ok', clicks_30d: 1840,
        delta_pct: 12, pending_count: 2, has_bulletin: true },
      { id: 'demo2', name: 'Studio PDF', domain: 'studio-pdf.triskell-studio.fr',
        is_external_client: false, health: 88, health_tone: 'ok', clicks_30d: 920,
        delta_pct: -3, pending_count: 0, has_bulletin: false },
      { id: 'demo3', name: 'Bobeez', domain: 'bobeez.triskell-studio.fr',
        is_external_client: false, health: 64, health_tone: 'warn', clicks_30d: 410,
        delta_pct: 8, pending_count: 5, has_bulletin: false },
    ];
  },

  _esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    }[c]));
  },
  _fmt(n) {
    if (n == null || n === '') return '—';
    const x = Number(n);
    if (isNaN(x)) return String(n);
    if (x >= 10000) return (x / 1000).toFixed(1).replace('.', ',') + ' k';
    return x.toLocaleString('fr-FR');
  },
  // Date ISO (« 2026-06-10 » ou horodatage complet) → format français lisible
  _frDate(iso) {
    if (!iso) return '';
    try {
      const d = new Date(iso);
      if (isNaN(d.getTime())) return String(iso).slice(0, 10);
      return d.toLocaleDateString('fr-FR', { day: 'numeric', month: 'long', year: 'numeric' });
    } catch (e) { return String(iso).slice(0, 10); }
  },
  _relTime(iso) {
    if (!iso) return 'jamais';
    try {
      const d = new Date(iso);
      const sec = Math.max(0, (Date.now() - d.getTime()) / 1000);
      if (sec < 60) return "à l’instant";
      if (sec < 3600) return `il y a ${Math.floor(sec/60)} min`;
      if (sec < 86400) return `il y a ${Math.floor(sec/3600)} h`;
      return `il y a ${Math.floor(sec/86400)} j`;
    } catch (e) { return iso; }
  },
};
