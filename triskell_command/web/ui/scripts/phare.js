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

  async render(container) {
    if (this.view === 'site')      return this._renderSite(container);
    if (this.view === 'coulisses') return this._renderCoulisses(container);
    return this._renderHome(container);
  },

  _go(view, opts = {}) {
    this.view = view;
    if (opts.siteId) this.selectedSite = opts.siteId;
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
          <button class="phare-filter-spacer" aria-hidden="true"></button>
          <button class="phare-coulisses-btn" data-act="coulisses" title="Voir les 8 robots qui surveillent tes sites">
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
    container.querySelectorAll('[data-filter]').forEach(b => {
      b.onclick = () => { this.filter = b.dataset.filter; this._renderHome(container); };
    });

    // Onboarding au premier lancement (après que le DOM soit posé)
    setTimeout(() => this._maybeShowOnboarding(), 100);

    if (!App.api) {
      this._renderHomeGrid(this._previewSites());
      return;
    }
    let data;
    try { data = await App.api.phare_home({}); }
    catch (e) {
      document.getElementById('ph-home-grid').innerHTML =
        `<div class="phare-empty"><div class="phare-empty-icon">⚠️</div>
         <h2>Connexion à la base impossible</h2>
         <p>Le Phare lit ses chiffres dans Supabase. Vérifie ta connexion ou tes réglages.</p>
         <button class="btn btn-secondary" onclick="App.show('config')">Aller dans Réglages</button></div>`;
      return;
    }
    if (!data || !data.ok) {
      document.getElementById('ph-home-grid').innerHTML =
        `<div class="phare-empty"><div class="phare-empty-icon">🔌</div>
         <h2>Le Phare n'est pas encore branché</h2>
         <p>${this._esc(data?.error || 'Impossible de lire les sites.')}</p></div>`;
      return;
    }
    this._renderHomeGrid(data.sites || []);
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
                          unknown: 'Pas encore d\'audit' }[tone];
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
      document.getElementById('ph-site-body').innerHTML =
        `<div class="phare-empty"><div class="phare-empty-icon">⚠️</div><h2>Erreur</h2><p>${this._esc(String(e))}</p></div>`;
      return;
    }
    if (!data || !data.ok) {
      document.getElementById('ph-site-body').innerHTML =
        `<div class="phare-empty"><div class="phare-empty-icon">⚠️</div><h2>Erreur</h2><p>${this._esc(data?.error || 'Site introuvable')}</p></div>`;
      return;
    }
    const s = data.site || {};
    const kpis = data.kpis || {};
    const toReview = data.to_review || [];
    const done = data.recently_done || [];
    const bull = data.bulletin || null;

    // Indexer les propositions pour la modale d'aperçu
    this._currentActions = {};
    toReview.forEach(a => { if (a && a.id) this._currentActions[a.id] = a; });

    document.getElementById('ph-site-body').innerHTML = `
      <header class="phare-site-hero">
        <div class="phare-site-hero-left">
          <div class="phare-kicker">SITE</div>
          <h1 class="phare-title">${this._esc(s.name || s.domain || '—')}</h1>
          <p class="phare-subtitle"><a href="https://${this._esc(s.domain || '')}" target="_blank" rel="noopener">${this._esc(s.domain || '')}</a></p>
        </div>
        <div class="phare-site-hero-right">
          <button class="btn btn-secondary" data-act="audit">Lancer un audit</button>
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
                      unknown: 'Pas encore audité' }[kpis.health_tone] || '—',
                    kpis.health_tone === 'ok' ? 'good' : (kpis.health_tone === 'bad' ? 'bad' : null))}
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

      <!-- CE QUI A ÉTÉ FAIT -->
      <div class="phare-section">
        <header class="phare-section-head">
          <h2>Ce qui a été fait</h2>
          <span class="phare-section-sub">
            ${done.length === 0 ? 'Pas encore de modifications appliquées.'
                                 : `Les ${done.length} dernières modifications validées.`}
          </span>
        </header>
        <div>
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
          <p>8 robots Claude tournent en arrière-plan sur ton site, chacun avec sa spécialité.</p>
          <button class="btn btn-secondary btn-sm" data-act="coulisses">Voir les 8 robots</button>
        </div>
      </details>
    `;

    document.getElementById('ph-site-body').querySelector('[data-act="audit"]').onclick = async () => {
      try {
        await App.api.phare_run_audit({ id: this.selectedSite });
        this._toast('✓ Audit lancé — le résultat apparaîtra dans quelques minutes');
      } catch (e) { this._toast('Erreur : ' + e, 'error'); }
    };
    document.getElementById('ph-site-body').querySelector('[data-act="edit"]').onclick = () => {
      this._openSiteDialog({ site: s, externalOnly: !!s.is_external_client });
    };
    document.getElementById('ph-site-body').querySelector('[data-act="coulisses"]').onclick = () =>
      this._go('coulisses');
    // Wire OK / Non / Voir détail
    this._wireActionButtons(document.getElementById('ph-site-body'));
  },

  // ════════════════════════════════════════════════════════════════════
  //  Carte d'action (proposition) — affichage + boutons
  // ════════════════════════════════════════════════════════════════════
  _actionCard(a, mode) {
    const agentLabel = this._agentShortName(a.agent || '');
    const date = (a.created_at || '').slice(0, 10);
    const impact = a.impact || 0;
    const impactDots = '●'.repeat(Math.max(0, Math.min(5, impact)))
                     + '○'.repeat(5 - Math.max(0, Math.min(5, impact)));
    const summary = a.detail_md || a.summary || '';
    const summaryShort = summary.length > 240
      ? this._esc(summary.slice(0, 240)) + '…'
      : this._esc(summary);
    if (mode === 'done') {
      return `
        <article class="phare-action phare-action--done">
          <div class="phare-action-head">
            <div class="phare-action-icon">✓</div>
            <div class="phare-action-body">
              <div class="phare-action-title">${this._esc(a.title || a.kind || '—')}</div>
              <div class="phare-action-meta">${this._esc(agentLabel)} · Appliqué le ${date || '—'}</div>
            </div>
            ${a.github_pr_url ? `<a class="phare-action-link" href="${this._esc(a.github_pr_url)}" target="_blank" rel="noopener">Voir la modif</a>` : ''}
            <button class="phare-action-archive" data-archive="${this._esc(a.id || '')}" title="Retirer de la liste" aria-label="Retirer de la liste">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m3 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/></svg>
            </button>
          </div>
        </article>`;
    }
    const isAuto = this._isAuto(a);
    const badge = isAuto
      ? `<div class="phare-action-kind phare-action-kind--auto" title="Le robot a déjà préparé la modification. Si tu approuves, elle est publiée automatiquement sur ton site.">
           <span class="phare-action-kind-ico">🤖</span>
           <span class="phare-action-kind-lbl">Le robot publie pour toi</span>
         </div>`
      : `<div class="phare-action-kind phare-action-kind--manual" title="C'est un conseil à faire toi-même. Approuver ne déclenche rien — ça marque juste la proposition comme lue.">
           <span class="phare-action-kind-ico">👤</span>
           <span class="phare-action-kind-lbl">À toi de le faire</span>
         </div>`;
    const approveLabel = isAuto
      ? `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" style="margin-right:6px;vertical-align:-2px"><path d="M5 3l14 9-14 9V3z"/></svg>Publier sur le site`
      : `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" style="margin-right:6px;vertical-align:-2px"><path d="M20 6L9 17l-5-5"/></svg>J'ai fait, suivant`;
    return `
      <article class="phare-action phare-action--todo ${isAuto ? 'is-auto' : 'is-manual'}" data-aid="${this._esc(a.id || '')}">
        ${badge}
        <div class="phare-action-head">
          <div class="phare-action-icon phare-action-icon--todo">${this._actionEmoji(a.agent)}</div>
          <div class="phare-action-body">
            <div class="phare-action-title">${this._esc(a.title || a.kind || '—')}</div>
            <div class="phare-action-meta">
              Proposition de ${this._esc(agentLabel)} · ${date || '—'}
              ${impact ? `<span class="phare-action-impact" title="Impact estimé">${impactDots}</span>` : ''}
            </div>
          </div>
        </div>
        ${summaryShort ? `<div class="phare-action-summary">${summaryShort}</div>` : ''}
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
          <button class="btn btn-primary ${isAuto ? 'btn-auto' : 'btn-manual'}" data-approve="${this._esc(a.id || '')}" data-approve-auto="${isAuto ? '1' : '0'}">
            ${approveLabel}
          </button>
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
    const approveHtmlAuto = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" style="margin-right:6px;vertical-align:-2px"><path d="M5 3l14 9-14 9V3z"/></svg>Publier sur le site';
    const approveHtmlManual = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" style="margin-right:6px;vertical-align:-2px"><path d="M20 6L9 17l-5-5"/></svg>J\'ai fait, suivant';
    const rejectHtml = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" style="margin-right:6px;vertical-align:-2px"><path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m3 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/></svg>Poubelle';
    root.querySelectorAll('[data-approve]').forEach(b => {
      b.onclick = async () => {
        const id = b.dataset.approve;
        const isAuto = b.dataset.approveAuto === '1';
        b.disabled = true; b.textContent = isAuto ? 'Publication…' : 'Enregistrement…';
        const restore = () => { b.disabled = false; b.innerHTML = isAuto ? approveHtmlAuto : approveHtmlManual; };
        try {
          const res = await App.api.phare_merge_action({ id, force: false });
          if (res && res.ok) {
            this._toast(res.kind === 'note_only' ? '✓ Marquée comme faite — à toi de jouer' : '✓ Publié sur ton site');
            this._renderSite(document.getElementById('content'));
            return;
          }
          // Si checks KO, propose "Publier quand même"
          if (res && res.decision && res.decision !== 'merge') {
            if (confirm("Les vérifications automatiques ne sont pas toutes vertes. Publier quand même ?")) {
              const r2 = await App.api.phare_merge_action({ id, force: true });
              if (r2 && r2.ok) { this._toast('✓ Publié (forcé)'); this._renderSite(document.getElementById('content')); return; }
              this._toast('Erreur : ' + (r2?.error || 'inconnue'), 'error');
              restore();
            } else { restore(); }
          } else {
            this._toast('Erreur : ' + (res?.error || 'inconnue'), 'error');
            restore();
          }
        } catch (e) { this._toast('Erreur : ' + e, 'error'); restore(); }
      };
    });
    root.querySelectorAll('[data-reject]').forEach(b => {
      b.onclick = async () => {
        const id = b.dataset.reject;
        const reason = prompt("Pourquoi refuser cette proposition ?\n(Tu peux laisser vide.)", "");
        if (reason === null) return; // annulé
        b.disabled = true; b.textContent = 'Refus…';
        const restore = () => { b.disabled = false; b.innerHTML = rejectHtml; };
        try {
          const res = await App.api.phare_reject_action({ id, reason: reason || '' });
          if (res && res.ok) {
            this._toast('Proposition mise à la poubelle');
            this._renderSite(document.getElementById('content'));
            return;
          }
          this._toast('Erreur : ' + (res?.error || 'inconnue'), 'error');
          restore();
        } catch (e) { this._toast('Erreur : ' + e, 'error'); restore(); }
      };
    });
    root.querySelectorAll('[data-preview]').forEach(b => {
      b.onclick = () => {
        const id = b.dataset.preview;
        const action = this._currentActions[id];
        if (action) this._openPreviewDialog(action);
      };
    });
    root.querySelectorAll('[data-archive]').forEach(b => {
      b.onclick = async () => {
        const id = b.dataset.archive;
        if (!confirm("Retirer cette modification de la liste « Ce qui a été fait » ?\n(La modification reste appliquée sur ton site — on la cache juste de ta vue.)")) return;
        b.disabled = true;
        try {
          const res = await App.api.phare_archive_action({ id });
          if (res && res.ok) {
            this._toast('Retiré de la liste');
            this._renderSite(document.getElementById('content'));
            return;
          }
          this._toast('Erreur : ' + (res?.error || 'inconnue'), 'error');
          b.disabled = false;
        } catch (e) { this._toast('Erreur : ' + e, 'error'); b.disabled = false; }
      };
    });
  },

  // ════════════════════════════════════════════════════════════════════
  //  MODAL — aperçu d'une proposition (détail complet + preview visuelle)
  // ════════════════════════════════════════════════════════════════════
  _openPreviewDialog(a) {
    const agentLabel = this._agentShortName(a.agent || '');
    const date = (a.created_at || '').slice(0, 10);
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
              ${impactDots ? `<span class="phare-action-impact" title="Impact estimé">${impactDots}</span>` : ''}
            </div>
          </div>
          <button class="phare-modal-close" data-close aria-label="Fermer">×</button>
        </header>
        <div class="phare-modal-body">
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
    const close = () => dlg.remove();
    dlg.querySelectorAll('[data-close]').forEach(el => el.onclick = close);
    // Relier OK / Poubelle de la modale aux mêmes handlers que les cartes
    const approveBtn = dlg.querySelector('[data-preview-approve]');
    const rejectBtn = dlg.querySelector('[data-preview-reject]');
    if (approveBtn) {
      approveBtn.onclick = () => {
        close();
        const cardBtn = document.querySelector(`[data-approve="${a.id}"]`);
        if (cardBtn) cardBtn.click();
      };
    }
    if (rejectBtn) {
      rejectBtn.onclick = () => {
        close();
        const cardBtn = document.querySelector(`[data-reject="${a.id}"]`);
        if (cardBtn) cardBtn.click();
      };
    }
    // Fermer avec Échap
    const onKey = (e) => { if (e.key === 'Escape') { close(); document.removeEventListener('keydown', onKey); } };
    document.addEventListener('keydown', onKey);
  },

  // Markdown minimaliste : paragraphes + gras + retours à la ligne
  _mdToHtml(md) {
    const esc = this._esc(md);
    const withBold = esc.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    const paras = withBold.split(/\n{2,}/).map(p => `<p>${p.replace(/\n/g, '<br>')}</p>`).join('');
    return paras;
  },

  _bulletinCard(b) {
    const date = (b.created_at || '').slice(0, 10);
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
            <h1 class="phare-title">Les 8 robots.</h1>
            <p class="phare-subtitle">Chacun a sa spécialité. Ensemble, ils gardent tes sites au sommet, 24/7.</p>
          </div>
        </header>
        <div id="ph-coulisses-grid"><div class="phare-loading">Chargement…</div></div>
      </section>
    `;
    container.querySelector('[data-act="back"]').onclick = () => this._go(this.selectedSite ? 'site' : 'home');
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
        b.disabled = true; const lbl = b.textContent; b.textContent = 'Lancement…';
        try {
          const payload = { agent: b.dataset.run };
          if (this.selectedSite) payload.site_id = this.selectedSite;
          const res = await App.api.phare_run_agent(payload);
          if (res && res.ok) this._toast('✓ Mission lancée en arrière-plan');
          else this._toast('Erreur : ' + (res?.error || 'inconnue'), 'error');
        } catch (e) { this._toast('Erreur : ' + e, 'error'); }
        finally { b.disabled = false; b.textContent = lbl; }
      };
    });
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
        <p class="phare-onboard-lead">Voici tes sites. Sur chacun, <strong>8 robots Claude</strong> préparent des améliorations SEO pendant que tu dors.</p>
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
    const close = () => dlg.remove();
    dlg.querySelectorAll('[data-close]').forEach(el => el.onclick = close);
    const showStep = (step) => {
      dlg.querySelectorAll('[data-step]').forEach(el => {
        el.style.display = el.dataset.step === step ? '' : 'none';
      });
      dlg.querySelectorAll('[data-foot]').forEach(el => {
        el.style.display = el.dataset.foot === (step === 'done' ? 'done' : 'form') ? '' : 'none';
      });
    };

    dlg.querySelector('[data-save]').onclick = async () => {
      const url = (dlg.querySelector('#ph-quick-url')?.value || '').trim();
      if (!url) { this._toast('Mets l’adresse du site.', 'error'); return; }
      showStep('loading');
      let res;
      try { res = await App.api.phare_site_quick_add({ url }); }
      catch (e) { this._toast('Erreur : ' + e, 'error'); showStep('form'); return; }
      if (!res || !res.ok) {
        this._toast('Erreur : ' + (res?.error || 'inconnue'), 'error');
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
            <span>${paths.map(p => `<code style="background:rgba(0,0,0,.06);padding:1px 5px;border-radius:3px;margin-right:4px">${this._esc(p)}</code>`).join(' ')}</span>
          </div>
        </div>
        <p class="text-xs text-text-muted" style="margin-top:14px;text-align:center">
          ${ac.claude_used ? 'Claude a analysé la homepage.' : (ac.fetched ? 'Page lue (Claude non disponible — défauts utilisés).' : 'Page injoignable — défauts utilisés.')}
          Tu peux ajuster les détails depuis la fiche du site.
        </p>
      `;
      dlg.querySelector('[data-summary]').innerHTML = summary;
      showStep('done');
      this._toast('✓ Site ajouté — les robots prennent le relais');
      dlg.querySelector('[data-foot="done"] [data-close]').onclick = () => {
        close();
        this._renderHome(document.getElementById('content'));
      };
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
            ${this._field('repo_github', 'Repo GitHub (owner/repo)', s.repo_github || '', 'Jordan-Bourillot/cabinet-dupont', false)}
            ${this._field('repo_branch_main', 'Branche de production', s.repo_branch_main || 'main', 'main', false)}
            ${this._field('netlify_site_id', 'Netlify site ID', s.netlify_site_id || '', '(uuid Netlify)', false)}
            ${this._selectField('stack', 'Techno', s.stack || 'html', ['astro','next','vite','html','autre'])}
            ${this._field('priority', 'Priorité (0-100)', String(s.priority ?? 50), '50', false, 'number')}
            ${this._textareaField('key_paths', 'Pages clés à surveiller (1 par ligne)', (s.key_paths || ['/']).join('\n'), '/, /contact, /services…')}
            ${this._field('notes', 'Notes internes', s.notes || '', '(secteur, particularités…)', false)}
            <label class="flex items-center gap-2 pt-2">
              <input type="checkbox" name="is_external_client" ${(externalOnly || s.is_external_client) ? 'checked' : ''}>
              <span class="text-sm">Site d'un client externe</span>
            </label>
          </form>
        </div>
        <footer class="phare-modal-foot">
          <button class="btn btn-secondary" data-close>Annuler</button>
          <button class="btn btn-primary" data-save>${isEdit ? 'Enregistrer' : 'Créer le site'}</button>
        </footer>
      </div>
    `;
    document.body.appendChild(dlg);
    const close = () => dlg.remove();
    dlg.querySelectorAll('[data-close]').forEach(el => el.onclick = close);
    dlg.querySelector('[data-save]').onclick = async () => {
      const form = dlg.querySelector('#ph-site-form');
      const fd = new FormData(form);
      const payload = {
        id: s.id || undefined,
        name: (fd.get('name') || '').toString().trim(),
        domain: (fd.get('domain') || '').toString().trim().toLowerCase(),
        repo_github: (fd.get('repo_github') || '').toString().trim(),
        repo_branch_main: (fd.get('repo_branch_main') || 'main').toString().trim(),
        netlify_site_id: (fd.get('netlify_site_id') || '').toString().trim(),
        stack: (fd.get('stack') || 'html').toString().trim(),
        priority: parseInt(fd.get('priority') || '50', 10) || 50,
        key_paths: (fd.get('key_paths') || '/').toString().split('\n').map(x => x.trim()).filter(Boolean).slice(0, 10),
        notes: (fd.get('notes') || '').toString().trim(),
        is_external_client: form.querySelector('[name="is_external_client"]').checked,
        is_active: true,
      };
      if (!payload.name || !payload.domain) {
        this._toast('Le nom et le domaine sont obligatoires.', 'error');
        return;
      }
      try {
        const res = await App.api.phare_site_upsert(payload);
        if (!res || !res.ok) { this._toast('Erreur : ' + (res?.error || 'inconnue'), 'error'); return; }
        close();
        this._toast(isEdit ? '✓ Site mis à jour' : '✓ Site ajouté — les robots prennent le relais');
        if (isEdit && this.view === 'site') this._renderSite(document.getElementById('content'));
        else this._renderHome(document.getElementById('content'));
      } catch (e) { this._toast('Erreur : ' + e, 'error'); }
    };
    setTimeout(() => dlg.querySelector('input[name="name"]').focus(), 50);
  },

  _field(name, label, value, placeholder, required = false, type = 'text') {
    return `
      <div>
        <label class="text-xs font-semibold text-text-muted uppercase tracking-wider">${this._esc(label)}${required ? ' *' : ''}</label>
        <input type="${type}" name="${this._esc(name)}" value="${this._esc(value)}"
               placeholder="${this._esc(placeholder)}"
               class="phare-input" ${required ? 'required' : ''}>
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
    if (x >= 10000) return (x / 1000).toFixed(1) + 'k';
    return x.toLocaleString('fr-FR');
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
  _toast(msg, kind = 'success') {
    const t = document.createElement('div');
    t.textContent = msg;
    const bg = kind === 'error' ? 'hsl(var(--danger))' : 'hsl(var(--success))';
    t.style.cssText = `position:fixed;bottom:32px;right:32px;background:${bg};color:white;padding:12px 20px;border-radius:12px;box-shadow:0 8px 24px rgba(0,0,0,0.18);z-index:9999;font-weight:600;font-size:14px`;
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 3500);
  },
};
