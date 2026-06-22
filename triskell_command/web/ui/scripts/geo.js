/* Le GEO — Generative Engine Optimization
 *
 * Module unique : tu rends ton site (ou celui d'un client) visible des IA
 * génératives — ChatGPT, Claude, Gemini, Perplexity.
 *
 * Quatre onglets :
 *   1. Audit       — colle une URL, on l'analyse et on note sur 100
 *   2. Surveillance — tes sites suivis + questions posées aux IA + score
 *   3. Générateur  — l'IA rédige du contenu prêt à coller, pensé pour être cité
 *   4. Réputation  — ce que les IA racontent sur une marque
 */

const GEO = {
  view: 'home',           // 'home' | 'site' | 'advanced'
  tab: 'audit',           // utilisé seulement en mode 'advanced'
  _selectedSiteId: null,  // site ouvert (vue 'site')
  _busy: false,           // évite double-clic sur les boutons
  _pubBusy: false,        // une seule publication à la fois
  _internalNav: false,    // vrai quand on navigue à l'intérieur du module
  _cyclePolling: false,   // suivi « Tout faire maintenant » déjà en cours
  _apSites: [],           // sites connus (pour redessiner la carte auto-pilote)

  // ════════════════════════════════════════════════════════════════════
  // ENTRY POINT — un parcours unique : Home → Site → Analyse en 1 clic
  // ════════════════════════════════════════════════════════════════════
  async render(container) {
    this._container = container;
    // Arrivée par le menu (ou depuis un autre écran) : on repart toujours
    // de l'accueil simple. Sans ce reset, la vue/l'onglet précédents
    // restaient collés et rouvrir « Le GEO » tombait au milieu du module.
    if (!this._internalNav && App.previousView !== 'geo') {
      this.view = 'home';
      this.tab = 'audit';
      this._selectedSiteId = null;
    }
    this._internalNav = false;
    if (this.view === 'site')     return this._renderSimpleSite(container);
    if (this.view === 'advanced') return this._renderAdvanced(container);
    return this._renderSimpleHome(container);
  },

  _goto(view, opts = {}) {
    this.view = view;
    if (opts.siteId !== undefined) this._selectedSiteId = opts.siteId;
    this._internalNav = true;
    this.render(this._container);
    // Tient le Guide au courant (cette navigation ne passe pas par App.show)
    try { if (window.Guide && Guide.onViewChange) Guide.onViewChange('geo'); } catch (e) { /* jamais bloquant */ }
  },

  // Redessine la vue réellement affichée (accueil simple, fiche site ou
  // mode avancé). Indispensable après un ajout/une édition : avant, on
  // appelait toujours _renderBody() qui n'existe qu'en mode avancé → en
  // mode simple rien ne bougeait, et re-cliquer créait des doublons.
  _refreshCurrentView() {
    if (!this._container) return;
    if (this.view === 'home') return this._renderSimpleHome(this._container);
    if (this.view === 'site') return this._renderSimpleSite(this._container);
    return this._renderBody();
  },

  // ════════════════════════════════════════════════════════════════════
  // VUE 1 — HOME : liste des sites + auto-pilote + ajouter
  // ════════════════════════════════════════════════════════════════════
  async _renderSimpleHome(container) {
    container.innerHTML = `
      <section class="geo-page animate-fade-in">
        <header class="mb-6">
          <div class="hero-kicker mb-2">LE GEO · AGENCE</div>
          <h1 class="hero-title hero-title--md mb-2">Sois cité par les IA.</h1>
          <p class="hero-subtitle">
            Ajoute un site, clique « Analyser », tu reçois les améliorations à appliquer.
          </p>
        </header>
        <div id="geo-home-content">
          <div class="geo-loading">Chargement…</div>
        </div>
        <footer class="mt-12 text-center">
          <button id="geo-go-advanced" class="geo-back">⚙️ Outils avancés (audits manuels, rédaction de contenus, réputation…)</button>
        </footer>
      </section>
    `;
    document.getElementById('geo-go-advanced').onclick = () => this._goto('advanced');
    const loadFail = (title, detail) => {
      document.getElementById('geo-home-content').innerHTML =
        `<div class="geo-card geo-card--err"><h3>${this._esc(title)}</h3><p>${this._esc(detail)}</p>
         <button class="btn btn-secondary mt-3" id="geo-home-retry">Réessayer</button></div>`;
      document.getElementById('geo-home-retry').onclick = () => this._renderSimpleHome(container);
    };
    let r;
    try { r = await App.api.geo_state({}); }
    catch (e) {
      console.warn('[GEO] chargement :', e);
      loadFail('Connexion impossible', 'Vérifie ta connexion internet, puis réessaie.');
      return;
    }
    if (!r || !r.ok) {
      loadFail('Pas pu charger', (r && r.error) || 'Le serveur n’a pas répondu correctement. Réessaie dans un instant.');
      return;
    }
    // Charge auto-pilote en parallèle
    let ap = null;
    try {
      const ar = await App.api.geo_autopilot_settings({});
      if (ar && ar.ok) ap = ar.settings;
    } catch (e) { /* tolère */ }
    const sites = r.sites || [];
    this._apSites = sites;
    const providersInfo = r.providers_count > 0
      ? `<span class="geo-pill geo-pill--ok">${r.providers_count} IA branchée${r.providers_count > 1 ? 's' : ''} : ${r.providers.map(p => p.label).join(', ')}</span>`
      : `<span class="geo-pill geo-pill--warn">Aucune IA branchée — <a href="#" data-go-config>va dans Réglages</a></span>`;
    document.getElementById('geo-home-content').innerHTML = `
      <div class="geo-card">
        <div class="geo-row-between">
          <div>
            <h2 class="geo-card-title">Tes sites</h2>
            <p class="geo-card-sub">Clique sur un site pour l'analyser et appliquer les améliorations.</p>
          </div>
          <button id="geo-add-site" class="btn btn-primary">+ Ajouter un site</button>
        </div>
        <div class="geo-pills mt-3">${providersInfo}</div>
      </div>
      ${this._renderAutopilotCard(ap, sites)}
      <div id="geo-last-run"></div>
      <div class="geo-sites-grid mt-6">
        ${sites.length === 0
          ? `<div class="geo-empty"><div class="geo-empty-icon">🌐</div><h3>Aucun site pour l'instant</h3><p>Clique sur « Ajouter un site » pour démarrer.</p></div>`
          : sites.map(s => this._renderSiteCard(s)).join('')}
      </div>
    `;
    document.getElementById('geo-add-site').onclick = () => this._openSiteDialog(null);
    // NB : les cartes sortent de _renderSiteCard → attribut data-site-id
    // (l'ancien sélecteur [data-geo-site] ne matchait rien : clic mort).
    document.querySelectorAll('#geo-home-content [data-site-id]').forEach(card => {
      card.onclick = (e) => {
        if (e.target.closest('[data-del-site]')) return;
        this._goto('site', { siteId: card.dataset.siteId });
      };
      card.onkeydown = (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); card.click(); }
      };
    });
    document.querySelectorAll('[data-del-site]').forEach(b => {
      b.onclick = async (e) => {
        e.stopPropagation();
        const sid = b.dataset.delSite;
        const s = sites.find(x => x.id === sid);
        const ok = await Dialog.confirm(
          `Supprimer ${s ? s.name : 'ce site'} ? Les questions et l’historique seront effacés.`,
          { title: 'Supprimer le site', danger: true, okLabel: 'Supprimer', cancelLabel: 'Annuler' }
        );
        if (!ok) return;
        try {
          const rr = await App.api.geo_site_remove({ id: sid });
          if (rr && rr.ok) { Toast.success(`${s ? s.name : 'Le site'} a été supprimé.`); this._renderSimpleHome(container); }
          else Toast.error((rr && rr.error) || 'Suppression impossible.');
        } catch (e2) { Toast.friendlyError(e2, 'Suppression impossible.'); }
      };
    });
    this._wireAutopilot(ap);
    this._renderLastRun();
    const cfg = container.querySelector('[data-go-config]');
    if (cfg) cfg.onclick = (e) => { e.preventDefault(); App.show('config', { tab: 'ai' }); };
  },

  // Encart « ce que le robot a publié » : les pages écrites + mises en ligne
  // automatiquement par l'auto-pilote, avec les liens. Chargé à part pour ne
  // pas ralentir l'accueil. (Demande Jordan : voir d'un coup d'œil ce qui a
  // été fait, au lieu d'aller fouiller dans les Outils avancés.)
  async _renderLastRun() {
    const slot = document.getElementById('geo-last-run');
    if (!slot) return;
    let items = [];
    try {
      const r = await App.api.geo_generated_list({});
      if (r && r.ok) items = r.items || [];
    } catch (e) { return; }
    const href = (it) => {
      const p = (it.publications || [])[0];
      return (typeof p === 'string') ? p : (p && p.url) || '';
    };
    const domain = (u) => {
      try { return new URL(u).hostname.replace(/^www\./, ''); } catch (e) { return ''; }
    };
    const pub = items.filter(it => href(it))
                     .sort((a, b) => (b.ts || '').localeCompare(a.ts || ''));
    if (!pub.length) { slot.innerHTML = ''; return; }
    const lastDate = (pub[0].ts || '').slice(0, 10);
    const rows = pub.slice(0, 8).map(it => {
      const u = href(it);
      const site = (it.auto_source && it.auto_source.site_name) || domain(u);
      return `<li style="display:flex;gap:10px;align-items:baseline;padding:6px 0;`
           + `border-top:1px dashed hsl(var(--border));font-size:13.5px;">`
           + `<span style="font-weight:700;color:hsl(var(--text-muted));min-width:120px;">`
           + `${this._esc(site)}</span>`
           + `<a href="${this._esc(u)}" target="_blank" rel="noopener" `
           + `style="color:hsl(var(--accent));text-decoration:none;">`
           + `${this._esc(it.topic || '(sans titre)')} ↗</a></li>`;
    }).join('');
    const more = pub.length > 8
      ? `<p class="geo-card-sub mt-2">+ ${pub.length - 8} autre(s) — voir « Outils avancés ».</p>`
      : '';
    slot.innerHTML = `
      <div class="geo-card mt-6">
        <div class="geo-row-between">
          <h2 class="geo-card-title">🤖 Ce que le robot a publié</h2>
          <span class="geo-card-sub">${pub.length} page${pub.length > 1 ? 's' : ''} en ligne · dernier passage le ${this._esc(lastDate)}</span>
        </div>
        <ul style="list-style:none;margin:10px 0 0;padding:0;">${rows}</ul>
        ${more}
        <p class="geo-card-sub mt-2">Pages écrites et mises en ligne toutes seules. Être cité par les IA prend des semaines — normal que ce soit lent au début.</p>
      </div>`;
  },

  // ════════════════════════════════════════════════════════════════════
  // VUE 2 — SITE : un seul bouton « Analyser », résultat consolidé
  // ════════════════════════════════════════════════════════════════════
  async _renderSimpleSite(container) {
    container.innerHTML = `<section class="geo-page animate-fade-in" id="geo-site-area">
      <div class="geo-loading">Chargement…</div></section>`;
    const area = document.getElementById('geo-site-area');
    let site = null;
    try {
      const r = await App.api.geo_sites({});
      site = (r && r.ok ? (r.sites || []) : []).find(s => s.id === this._selectedSiteId);
    } catch (e) { /* tolère */ }
    if (!site) {
      area.innerHTML = `<button class="geo-back" id="back-home">← Mes sites</button>
        <div class="geo-card geo-card--err mt-3"><h3>Site introuvable</h3></div>`;
      document.getElementById('back-home').onclick = () => this._goto('home');
      return;
    }
    area.innerHTML = `
      <button class="geo-back" id="back-home">← Mes sites</button>
      <div class="geo-card mt-3">
        <div class="geo-row-between">
          <div>
            <div class="hero-kicker">SITE SUIVI</div>
            <h2 class="geo-card-title">${this._esc(site.name)}</h2>
            <p class="geo-card-sub">${this._esc(site.url)}</p>
          </div>
          <div class="geo-site-actions">
            <button id="geo-edit-site" class="btn btn-secondary">✎ Modifier</button>
            ${site.repo ? `<button id="geo-llms" class="btn btn-secondary"
              title="Met à jour le petit fichier qui dit aux IA quelles pages de ton site citer en priorité (llms.txt).">🤖 Plan pour les IA</button>` : ''}
            <button id="geo-del-site"  class="btn btn-secondary geo-btn-danger">🗑 Supprimer</button>
          </div>
        </div>
      </div>

      <div class="geo-bigcta mt-6">
        <button id="geo-run-full" class="btn btn-primary geo-bigcta-btn">
          🔍 Analyser ce site maintenant
        </button>
        <div class="geo-bigcta-sub">
          On lit ta page, on demande aux IA si elles te citent, et on te donne les améliorations à appliquer. Compte 30 secondes à 2 minutes.
        </div>
      </div>

      <div id="geo-full-result" class="mt-6"></div>
    `;
    document.getElementById('back-home').onclick = () => this._goto('home');
    document.getElementById('geo-edit-site').onclick = () => this._openSiteDialog(site);
    const llmsBtn = document.getElementById('geo-llms');
    if (llmsBtn) llmsBtn.onclick = async () => {
      const old = llmsBtn.textContent;
      llmsBtn.disabled = true; llmsBtn.textContent = 'Mise à jour…';
      try {
        const r = await App.api.geo_llms_publish({ site_id: site.id });
        if (r && r.ok && r.unchanged) Toast.success('Le plan pour les IA était déjà à jour.');
        else if (r && r.ok) Toast.success('Plan pour les IA mis à jour et mis en ligne. 🤖');
        else Toast.error((r && r.error) || 'Mise à jour impossible.');
      } catch (e) { Toast.friendlyError(e, 'Mise à jour impossible.'); }
      finally { llmsBtn.disabled = false; llmsBtn.textContent = old; }
    };
    document.getElementById('geo-del-site').onclick = async () => {
      const ok = await Dialog.confirm(
        `Supprimer ${site.name} ? Les questions et l’historique seront effacés.`,
        { title: 'Supprimer le site', danger: true, okLabel: 'Supprimer', cancelLabel: 'Annuler' }
      );
      if (!ok) return;
      try {
        const r = await App.api.geo_site_remove({ id: site.id });
        if (r && r.ok) { Toast.success(`${site.name} a été supprimé.`); this._goto('home'); }
        else Toast.error((r && r.error) || 'Suppression impossible.');
      } catch (e) { Toast.friendlyError(e, 'Suppression impossible.'); }
    };
    document.getElementById('geo-run-full').onclick = () => this._runFullAnalysis(site);
    // Résultats persistants : on réaffiche la dernière analyse enregistrée
    // au lieu de tout perdre à chaque visite de la fiche.
    this._loadLastAnalysis(site);
  },

  // Récupère la dernière analyse connue du site (audit IA + surveillance,
  // historiques serveur geo_audit_ai_history / geo_surveillance_history)
  // et l'affiche avec sa date.
  async _loadLastAnalysis(site) {
    const out = document.getElementById('geo-full-result');
    if (!out) return;
    out.innerHTML = `<div class="geo-loading">On regarde s’il y a déjà une analyse enregistrée…</div>`;
    let audit = null, surv = null;
    try {
      const [ar, sr] = await Promise.all([
        App.api.geo_audit_ai_history({ site_id: site.id }),
        App.api.geo_surveillance_history({ site_id: site.id }),
      ]);
      if (ar && ar.ok && (ar.audits || []).length) audit = ar.audits[0];
      if (sr && sr.ok && (sr.runs || []).length)   surv  = sr.runs[0];
    } catch (e) { console.warn('[GEO] dernière analyse :', e); }
    if (this._busy) return; // une analyse fraîche vient d'être lancée : on n'écrase pas
    if (!audit && !surv) { out.innerHTML = ''; return; }
    const lastTs = [audit && audit.ts, surv && surv.ts].filter(Boolean).sort().pop() || '';
    const btn = document.getElementById('geo-run-full');
    if (btn) btn.textContent = '🔍 Relancer l’analyse';
    out.innerHTML = `
      <p class="geo-card-sub mb-2">Dernière analyse : ${this._fmtDate(lastTs)} — clique le bouton ci-dessus pour la refaire.</p>
      ${this._renderFullResults(site, audit, surv, {})}
    `;
    this._wireFullResults(out, site, audit, surv);
  },

  async _runFullAnalysis(site) {
    if (this._busy) return;
    this._busy = true;
    const btn = document.getElementById('geo-run-full');
    const out = document.getElementById('geo-full-result');
    btn.disabled = true;
    btn.textContent = '⏳ Analyse en cours…';
    const stepEl = (txt) => out.innerHTML = `
      <div class="geo-card"><div class="geo-loading">${txt}</div></div>`;
    // Chaque étape garde SON erreur : un audit IA raté n'efface plus la
    // surveillance (et inversement), et on affiche quand même ce qui a marché.
    let audit = null, surv = null, auditErr = '', survErr = '';
    try {
      // Étape 1 : audit IA (lecture de la page + suggestions)
      stepEl('🤖 L’IA lit ta page (titre, contenu, structure)…');
      try {
        const r1 = await App.api.geo_audit_ai({ site_id: site.id });
        if (r1 && r1.ok) audit = r1.audit;
        else auditErr = (r1 && r1.error) || 'Audit IA impossible.';
      } catch (e) {
        console.warn('[GEO] audit IA :', e);
        auditErr = 'La connexion a été interrompue pendant l’audit IA. Réessaie.';
      }
      // Étape 2 : surveillance (uniquement si au moins une question)
      // On suggère des questions si vide
      stepEl('💬 On prépare les questions à poser aux IA…');
      try {
        const qs = await App.api.geo_questions({ site_id: site.id });
        if (qs && qs.ok && (qs.questions || []).length === 0) {
          await App.api.geo_suggest_questions({ site_id: site.id });
        }
      } catch (e) { /* tolère */ }
      stepEl('👁 On demande à chaque IA si ton site est cité…');
      try {
        const r2 = await App.api.geo_surveillance_run({ site_id: site.id });
        if (r2 && r2.ok) surv = r2.run;
        else survErr = (r2 && r2.error) || 'Surveillance impossible.';
      } catch (e) {
        console.warn('[GEO] surveillance :', e);
        survErr = 'La connexion a été interrompue pendant la surveillance. Réessaie.';
      }
    } finally {
      btn.disabled = false;
      btn.textContent = '🔍 Relancer l’analyse';
      this._busy = false;
    }
    out.innerHTML = this._renderFullResults(site, audit, surv, { auditErr, survErr });
    this._wireFullResults(out, site, audit, surv);
  },

  _renderFullResults(site, audit, surv, errs) {
    const { auditErr = '', survErr = '' } = errs || {};
    const parts = [];
    // Section 1 : présence dans les IA
    if (surv) {
      const cls = surv.score >= 60 ? 'ok' : surv.score >= 30 ? 'warn' : 'bad';
      const verdict = surv.score >= 60
        ? 'Bien présent dans les IA, garde la cadence.'
        : surv.score >= 30
        ? 'Présent par moments — il reste du potentiel.'
        : 'Les IA ne te citent quasiment pas. C\'est là que les améliorations vont faire la différence.';
      parts.push(`
        <section class="geo-card geo-card--result">
          <div class="hero-kicker">PRÉSENCE DANS LES IA</div>
          <div class="geo-score-row mt-3">
            <div class="geo-score geo-score--${cls === 'ok' ? 'success' : cls === 'warn' ? 'warning' : 'danger'}">
              <div class="geo-score-value">${surv.score}%</div>
              <div class="geo-score-max">${surv.cited}/${surv.total}</div>
            </div>
            <div class="geo-score-text">
              <div class="geo-score-verdict">${verdict}</div>
              <div class="geo-score-meta">Concrètement : ton site est ressorti <b>${surv.cited} fois sur ${surv.total} tests</b> (questions posées à ${(n => `${n} IA différente${n > 1 ? 's' : ''}`)(new Set((surv.results || []).map(x => x.provider).filter(Boolean)).size)}) · <a href="#" data-show-details>voir le détail</a></div>
            </div>
          </div>
          <div id="geo-surv-details" hidden class="mt-4">
            ${this._renderRunBody(surv)}
          </div>
        </section>
      `);
    } else if (survErr) {
      parts.push(`
        <section class="geo-card geo-card--err">
          <div class="hero-kicker">PRÉSENCE DANS LES IA</div>
          <h3 class="geo-card-title mt-1">La surveillance n'a pas pu se faire</h3>
          <p>${this._esc(survErr)}</p>
        </section>
      `);
    }
    // Section 2 : améliorations recommandées par l'IA
    if (audit && audit.findings && audit.findings.length) {
      const pendCount = audit.findings.filter(f => !f.applied_at).length;
      parts.push(`
        <section class="geo-card mt-5">
          <div class="hero-kicker">AMÉLIORATIONS À APPLIQUER</div>
          <h3 class="geo-card-title mt-1">${pendCount > 0
            ? `${pendCount} chose${pendCount > 1 ? 's' : ''} à corriger pour grimper`
            : 'Tout est appliqué ✓'}</h3>
          <p class="geo-card-sub">${this._esc(audit.verdict || '')}</p>
          <div class="geo-aifindings mt-4">
            ${audit.findings.map((f, idx) => `
              <div class="geo-aifinding ${f.applied_at ? 'geo-aifinding--done' : ''}" data-fid="${f.id}">
                <div class="geo-aifinding-head">
                  <div class="geo-aifinding-num">${f.applied_at ? '✓' : idx + 1}</div>
                  <div class="geo-aifinding-title">
                    <div class="geo-aifinding-titletxt">${this._esc(f.title)}</div>
                    <div class="geo-aifinding-problem">${this._esc(f.problem)}</div>
                  </div>
                </div>
                <div class="geo-aifinding-fix">
                  <div class="geo-aifinding-fixtitle">💡 ${this._esc(f.fix_title)}</div>
                  <div class="geo-aifinding-actions">
                    ${f.applied_at
                      ? `<span class="geo-aifinding-applied">✓ Appliquée le ${this._fmtDate(f.applied_at)}</span>`
                      : `<button class="btn btn-secondary geo-btn-mini" data-preview-finding="${f.id}">👁 Aperçu</button>
                         <button class="btn btn-primary geo-btn-mini" data-publish-finding="${f.id}">📤 Appliquer sur le site</button>`}
                  </div>
                </div>
              </div>
            `).join('')}
          </div>
        </section>
      `);
    } else if (audit) {
      parts.push(`<div class="geo-card mt-5">
        <h3 class="geo-card-title">Aucune amélioration majeure</h3>
        <p class="geo-card-sub">L'IA n'a pas trouvé de point critique à corriger pour le moment. ${this._esc(audit.verdict || '')}</p>
      </div>`);
    } else if (auditErr) {
      parts.push(`
        <section class="geo-card geo-card--err mt-5">
          <div class="hero-kicker">AMÉLIORATIONS À APPLIQUER</div>
          <h3 class="geo-card-title mt-1">L'audit IA n'a pas pu se faire</h3>
          <p>${this._esc(auditErr)}</p>
        </section>
      `);
    }
    return parts.join('');
  },

  _wireFullResults(out, site, audit, surv) {
    // Bouton "voir le détail" pour la section surveillance
    const det = out.querySelector('[data-show-details]');
    if (det) det.onclick = (e) => {
      e.preventDefault();
      const panel = document.getElementById('geo-surv-details');
      panel.hidden = !panel.hidden;
      det.textContent = panel.hidden ? 'voir le détail' : 'masquer le détail';
    };
    // Boutons Aperçu / Appliquer sur chaque finding
    if (audit) {
      const pubBtns = Array.from(out.querySelectorAll('[data-publish-finding]'));
      out.querySelectorAll('[data-preview-finding]').forEach(b => {
        b.onclick = () => {
          const f = audit.findings.find(x => x.id === b.dataset.previewFinding);
          if (!f) return;
          const cardBtn = pubBtns.find(x => x.dataset.publishFinding === f.id) || null;
          this._openFindingPreview({ ...audit, site_id: site.id }, f, cardBtn);
        };
      });
      pubBtns.forEach(b => {
        b.onclick = () => {
          const f = audit.findings.find(x => x.id === b.dataset.publishFinding);
          if (f) this._publishFinding({ ...audit, site_id: site.id }, f, b);
        };
      });
    }
  },

  _renderRunBody(run) {
    // Petit rendu compact des résultats de surveillance
    return (run.results || []).map(res => `
      <div class="geo-run-line">
        <div class="geo-run-line-head">
          <span class="geo-run-prov">${this._esc(res.provider || '')}</span>
          <span class="geo-run-cited ${res.cited ? 'is-cited' : 'is-not'}">${res.cited ? '✓ cité' : '✗ pas cité'}</span>
        </div>
        <div class="geo-run-q">« ${this._esc(res.question || '')} »</div>
        ${res.snippet ? `<div class="geo-run-snip">${this._esc(res.snippet)}</div>` : ''}
      </div>
    `).join('') || '<div class="geo-empty">Pas de détail.</div>';
  },

  // Branche les contrôles de la carte auto-pilote (mode simple ET mode
  // avancé : la carte est la même, le rafraîchissement suit la vue).
  _wireAutopilot(ap) {
    const apEnabled = document.getElementById('geo-ap-enabled');
    const apFreq    = document.getElementById('geo-ap-freq');
    const apAuto    = document.getElementById('geo-ap-autogen');
    const apPub     = document.getElementById('geo-ap-autopub');
    const apRunNow  = document.getElementById('geo-ap-run-now');
    const apRefresh = document.getElementById('geo-ap-refresh');
    const saveAp = async () => {
      const payload = {
        enabled:        !!apEnabled?.checked,
        frequency_days: parseInt(apFreq?.value || '14', 10),
        auto_generate:  !!apAuto?.checked,
        auto_publish:   !!apPub?.checked,
      };
      // On vérifie vraiment la réponse du serveur : en cas d'échec, on
      // redessine l'état réel (fini la case cochée pour rien).
      try {
        const rr = await App.api.geo_autopilot_settings_set(payload);
        if (rr && rr.ok) { this._refreshCurrentView(); return; }
        Toast.error((rr && rr.error) || 'Réglages non enregistrés. Réessaie.');
        this._refreshCurrentView();
      } catch (e) {
        Toast.friendlyError(e, 'Réglages non enregistrés. Réessaie.');
        this._refreshCurrentView();
      }
    };
    if (apEnabled) apEnabled.onchange = saveAp;
    if (apFreq)    apFreq.onchange    = saveAp;
    if (apAuto)    apAuto.onchange    = saveAp;
    if (apPub) {
      apPub.onchange = async () => {
        if (apPub.checked) {
          const linked = (this._apSites || []).filter(s => s && s.repo);
          const msg = linked.length === 0
            ? 'Aucun de tes sites n’est branché pour l’instant, donc rien ne partira en ligne tout de suite. L’option marchera dès que tu auras branché un site (clique dessus → ✎ Modifier → « Publication automatique »). Activer quand même ?'
            : `L’app mettra en ligne des pages écrites par l’IA, toute seule, sans te demander et sans relecture, sur : ${linked.map(s => s.name || s.url).join(', ')}. Activer ?`;
          const ok = await Dialog.confirm(
            msg,
            { title: 'Mise en ligne automatique', danger: true, okLabel: 'Activer', cancelLabel: 'Annuler' }
          );
          if (!ok) { apPub.checked = false; return; }
        }
        saveAp();
      };
    }
    if (apRefresh) apRefresh.onclick = () => this._refreshCurrentView();
    if (apRunNow) {
      apRunNow.onclick = async () => {
        apRunNow.disabled = true;
        apRunNow.textContent = '⏳ Lancement…';
        try {
          const rr = await App.api.geo_autopilot_run_now({});
          if (rr && rr.ok) {
            Toast.success('Cycle lancé. L’app travaille en arrière-plan — compte 5 à 10 minutes, l’écran se met à jour tout seul.');
            this._refreshCurrentView();
            this._startCyclePolling();
          } else {
            Toast.error((rr && rr.error) || 'Le cycle n’a pas pu démarrer.');
            apRunNow.disabled = false;
            apRunNow.textContent = '🚀 Tout faire maintenant';
          }
        } catch (e) {
          Toast.friendlyError(e, 'Le cycle n’a pas pu démarrer.');
          apRunNow.disabled = false;
          apRunNow.textContent = '🚀 Tout faire maintenant';
        }
      };
    }
    // Un cycle tourne déjà (lancé ici ou depuis un autre poste) → suivi auto
    if (ap && ap.running) this._startCyclePolling();
  },

  // Tant qu'un cycle « Tout faire maintenant » tourne, on redessine la
  // carte auto-pilote toutes les 20 s (mise à jour ciblée : le reste de
  // l'écran n'est pas touché). S'arrête tout seul à la fin du cycle, si la
  // carte quitte l'écran, ou au changement de vue (App.viewInterval).
  _startCyclePolling() {
    if (this._cyclePolling) return;
    this._cyclePolling = true;
    App.onViewCleanup(() => { this._cyclePolling = false; });
    const timer = App.viewInterval(async () => {
      if (!document.querySelector('.geo-ap-card')) {
        clearInterval(timer); this._cyclePolling = false; return;
      }
      let ap = null;
      try {
        const ar = await App.api.geo_autopilot_settings({});
        if (ar && ar.ok) ap = ar.settings;
      } catch (e) { return; } // souci réseau : on retentera au prochain passage
      if (!ap) return;
      const cur = document.querySelector('.geo-ap-card');
      if (!cur) { clearInterval(timer); this._cyclePolling = false; return; }
      const tmp = document.createElement('div');
      tmp.innerHTML = this._renderAutopilotCard(ap, this._apSites || []);
      cur.replaceWith(tmp.firstElementChild);
      this._wireAutopilot(ap);
      if (!ap.running) {
        clearInterval(timer);
        this._cyclePolling = false;
        Toast.success('Cycle terminé. Les résultats sont à jour.');
      }
    }, 20000);
  },

  // ════════════════════════════════════════════════════════════════════
  // VUE 3 — ADVANCED : ancien parcours 4 onglets (power users)
  // ════════════════════════════════════════════════════════════════════
  async _renderAdvanced(container) {
    container.innerHTML = `
      <section class="geo-page animate-fade-in">
        <header class="mb-6">
          <button class="geo-back" id="geo-back-simple">← Retour au mode simple</button>
          <div class="hero-kicker mb-2 mt-2">LE GEO · MODE AVANCÉ</div>
          <h1 class="hero-title hero-title--md mb-2">Outils détaillés</h1>
          <p class="hero-subtitle">Audits manuels, rédaction de contenus, réputation, gestion fine des questions.</p>
        </header>
        ${this._renderTabs()}
        <div id="geo-body" class="mt-6"></div>
      </section>
    `;
    document.getElementById('geo-back-simple').onclick = () => this._goto('home');
    container.querySelectorAll('[data-geo-tab]').forEach(b => {
      b.onclick = () => { this.tab = b.dataset.geoTab; this._renderAdvanced(container); };
    });
    await this._renderBody();
  },

  _renderTabs() {
    const tabs = [
      { id: 'audit',        label: 'Audit',        icon: '🔍', sub: 'Analyser une page' },
      { id: 'surveillance', label: 'Surveillance', icon: '👁️', sub: 'Suivre dans les IA' },
      { id: 'generator',    label: 'Générateur',   icon: '✍️', sub: 'Rédiger pour les IA' },
      { id: 'reputation',   label: 'Réputation',   icon: '⭐', sub: 'Ce qu\'elles disent' },
    ];
    return `
      <nav class="geo-tabs">
        ${tabs.map(t => `
          <button data-geo-tab="${t.id}"
                  class="geo-tab ${this.tab === t.id ? 'is-active' : ''}">
            <div class="geo-tab-icon">${t.icon}</div>
            <div class="geo-tab-text">
              <div class="geo-tab-label">${t.label}</div>
              <div class="geo-tab-sub">${t.sub}</div>
            </div>
          </button>
        `).join('')}
      </nav>
    `;
  },

  async _renderBody() {
    const body = document.getElementById('geo-body');
    if (!body) return;
    if (this.tab === 'audit')        return this._renderAudit(body);
    if (this.tab === 'surveillance') return this._renderSurveillance(body);
    if (this.tab === 'generator')    return this._renderGenerator(body);
    if (this.tab === 'reputation')   return this._renderReputation(body);
  },

  // ════════════════════════════════════════════════════════════════════
  // ONGLET 1 — AUDIT
  // ════════════════════════════════════════════════════════════════════
  async _renderAudit(body) {
    body.innerHTML = `
      <div class="geo-card">
        <h2 class="geo-card-title">Analyser une page</h2>
        <p class="geo-card-sub">Deux analyses : la <strong>technique</strong> (présence des bons éléments) et l'<strong>IA</strong> (lecture qualitative + propositions de blocs prêts à publier).</p>
        <div class="geo-form">
          <input id="geo-audit-url" type="url" placeholder="https://exemple.fr/ma-page (Entrée = audit IA)"
                 title="La touche Entrée lance l’audit IA" class="geo-input geo-input--big" autocomplete="off" />
          <button id="geo-audit-go" class="btn btn-secondary geo-btn-big">📊 Analyse technique</button>
          <button id="geo-audit-ai-go" class="btn btn-primary geo-btn-big">🤖 Audit IA + propositions</button>
        </div>
        <div id="geo-audit-msg" class="geo-msg"></div>
      </div>
      <div id="geo-audit-result" class="mt-6"></div>
    `;
    const input = document.getElementById('geo-audit-url');
    const btn = document.getElementById('geo-audit-go');
    const btnAi = document.getElementById('geo-audit-ai-go');
    const run = () => this._runAudit(input.value);
    const runAi = () => this._runAuditAi(input.value);
    btn.onclick = run;
    btnAi.onclick = runAi;
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') runAi(); });
    input.focus();
  },

  async _runAuditAi(url) {
    if (this._busy) return;
    const msg = document.getElementById('geo-audit-msg');
    const out = document.getElementById('geo-audit-result');
    const btn = document.getElementById('geo-audit-ai-go');
    url = (url || '').trim();
    if (!url) { msg.textContent = 'Colle d\'abord une adresse de page.'; msg.className = 'geo-msg geo-msg--warn'; return; }
    this._busy = true;
    btn.disabled = true;
    btn.textContent = '⏳ L\'IA analyse ta page…';
    msg.textContent = 'L\'IA lit la page (titre, contenu, structure) et rédige les améliorations.';
    msg.className = 'geo-msg';
    out.innerHTML = '';
    try {
      // Cherche si l'URL correspond à un site déjà enregistré (pour proposer la publi)
      let siteId = '';
      try {
        const sr = await App.api.geo_sites({});
        if (sr && sr.ok) {
          const m = (sr.sites || []).find(s => {
            const u = (s.url || '').replace(/\/+$/, '');
            const target = url.replace(/\/+$/, '');
            return u === target || target.startsWith(u);
          });
          if (m) siteId = m.id;
        }
      } catch (e) { /* tolère */ }
      const r = await App.api.geo_audit_ai({ url, site_id: siteId });
      if (!r || !r.ok) {
        msg.textContent = (r && r.error) || 'Erreur inconnue.';
        msg.className = 'geo-msg geo-msg--err';
        return;
      }
      msg.textContent = '';
      out.innerHTML = this._renderAuditAiResult(r.audit);
      this._wireAuditAi(out, r.audit);
    } catch (e) {
      console.warn('[GEO] audit IA :', e);
      msg.textContent = 'Connexion impossible pendant l’audit. Réessaie dans un instant.';
      msg.className = 'geo-msg geo-msg--err';
    } finally {
      this._busy = false;
      btn.disabled = false;
      btn.textContent = '🤖 Audit IA + propositions';
    }
  },

  _renderAuditAiResult(a) {
    const scoreColor = a.score_estimated >= 75 ? 'success'
                     : a.score_estimated >= 50 ? 'warning' : 'danger';
    return `
      <div class="geo-card geo-card--result">
        <div class="hero-kicker">AUDIT IA · ${this._esc(a.provider || '')}</div>
        <div class="geo-score-row mt-3">
          <div class="geo-score geo-score--${scoreColor}">
            <div class="geo-score-value">${a.score_estimated}</div>
            <div class="geo-score-max">/ 100</div>
          </div>
          <div class="geo-score-text">
            <div class="geo-score-verdict">${this._esc(a.verdict || 'Analyse terminée.')}</div>
            <div class="geo-score-url">${this._esc(a.url)}</div>
            <div class="geo-score-meta">${a.findings.length} amélioration${a.findings.length > 1 ? 's' : ''} proposée${a.findings.length > 1 ? 's' : ''}</div>
          </div>
        </div>
      </div>
      <div class="geo-aifindings mt-4">
        ${a.findings.map((f, idx) => `
          <div class="geo-aifinding" data-fid="${f.id}">
            <div class="geo-aifinding-head">
              <div class="geo-aifinding-num">${idx + 1}</div>
              <div class="geo-aifinding-title">
                <div class="geo-aifinding-titletxt">${this._esc(f.title)}</div>
                <div class="geo-aifinding-problem">${this._esc(f.problem)}</div>
              </div>
            </div>
            <div class="geo-aifinding-fix">
              <div class="geo-aifinding-fixtitle">💡 ${this._esc(f.fix_title)}</div>
              <div class="geo-aifinding-actions">
                <button class="btn btn-secondary geo-btn-mini" data-preview-finding="${f.id}">👁 Aperçu</button>
                <button class="btn btn-primary geo-btn-mini" data-publish-finding="${f.id}">📤 Publier sur le site</button>
              </div>
            </div>
          </div>
        `).join('')}
      </div>
    `;
  },

  _wireAuditAi(out, audit) {
    const pubBtns = Array.from(out.querySelectorAll('[data-publish-finding]'));
    out.querySelectorAll('[data-preview-finding]').forEach(b => {
      b.onclick = () => {
        const f = audit.findings.find(x => x.id === b.dataset.previewFinding);
        if (!f) return;
        const cardBtn = pubBtns.find(x => x.dataset.publishFinding === f.id) || null;
        this._openFindingPreview(audit, f, cardBtn);
      };
    });
    pubBtns.forEach(b => {
      b.onclick = () => {
        const f = audit.findings.find(x => x.id === b.dataset.publishFinding);
        if (f) this._publishFinding(audit, f, b);
      };
    });
  },

  _openFindingPreview(audit, finding, cardBtn) {
    const overlay = document.createElement('div');
    overlay.className = 'geo-modal-overlay';
    // Le bloc proposé par l'IA est affiché dans une iframe isolée
    // (sandbox vide : ni scripts, ni accès à la page) : son HTML ne touche
    // jamais le reste de l'app. Les couleurs fixes ci-dessous simulent la
    // future page publique (toujours claire), comme .geo-preview-card.
    const pageDoc = `<!doctype html><html lang="fr"><head><meta charset="utf-8"><style>
      body { font-family: -apple-system, system-ui, sans-serif; margin: 24px 28px;
             background: #fff; color: #1e293b; line-height: 1.65; }
      h1 { font-size: 28px; font-weight: 700; margin: 0 0 18px; color: #0f172a; }
      h2 { font-size: 21px; font-weight: 700; margin: 22px 0 10px; color: #0f172a; }
      h3 { font-size: 16px; font-weight: 700; margin: 18px 0 8px; color: #0f172a; }
      p, li { font-size: 14.5px; } ul, ol { padding-left: 24px; margin: 8px 0; }
      table { width: 100%; border-collapse: collapse; margin: 14px 0; font-size: 13.5px; }
      th, td { padding: 8px 12px; border: 1px solid #e2e8f0; text-align: left; }
      th { background: #f8fafc; font-weight: 700; }
      section { margin: 16px 0; padding: 14px; background: #f8fafc; border-radius: 8px; }
    </style></head><body><h1>${this._esc(finding.fix_title)}</h1>${finding.fix_html || ''}</body></html>`;
    overlay.innerHTML = `
      <div class="geo-modal geo-modal--xl">
        <h3 class="geo-modal-title">Aperçu du bloc à publier</h3>
        <p class="geo-modal-sub">Voilà à quoi va ressembler ce contenu une fois publié sur ton site.</p>
        <div class="geo-preview-card">
          <div class="geo-preview-label">PAGE QUI VA ÊTRE CRÉÉE</div>
          <iframe sandbox="" title="Aperçu de la page proposée"
                  style="display:block;width:100%;height:50vh;border:0"
                  srcdoc="${this._esc(pageDoc)}"></iframe>
        </div>
        <details class="geo-advanced mt-3">
          <summary class="geo-details-sum">Voir le code HTML brut</summary>
          <pre class="geo-gen-raw">${this._esc(finding.fix_html)}</pre>
        </details>
        <div id="geo-preview-msg" class="geo-msg"></div>
        <div class="geo-modal-actions">
          <button class="btn btn-secondary" id="geo-preview-close">Fermer</button>
          <button class="btn btn-primary" id="geo-preview-publish">📤 Publier maintenant</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);
    const close = () => { document.removeEventListener('keydown', onKey); overlay.remove(); };
    const onKey = (e) => {
      // Échap ne ferme l'aperçu que s'il est la fenêtre du dessus
      // (pas pendant une publication, ni sous la fenêtre de choix du site)
      const all = document.querySelectorAll('.geo-modal-overlay');
      if (e.key === 'Escape' && all[all.length - 1] === overlay
          && !this._pubBusy && !document.getElementById('tc-dialog-overlay')) close();
    };
    document.addEventListener('keydown', onKey);
    // Pendant une publication, l'aperçu reste ouvert (indicateur visible)
    overlay.onclick = (e) => { if (e.target === overlay && !this._pubBusy) close(); };
    const closeBtn = document.getElementById('geo-preview-close');
    const pubBtn   = document.getElementById('geo-preview-publish');
    closeBtn.onclick = () => { if (!this._pubBusy) close(); };
    pubBtn.onclick = async () => {
      if (this._pubBusy) return;
      const msg = document.getElementById('geo-preview-msg');
      pubBtn.disabled = true;
      closeBtn.disabled = true;
      pubBtn.textContent = '⏳ Publication en cours…';
      msg.textContent = 'Publication en cours — on prépare la page et on l’envoie sur ton site…';
      msg.className = 'geo-msg';
      const ok = await this._publishFinding(audit, finding, cardBtn || null,
                                            { skipConfirm: true });
      closeBtn.disabled = false;
      if (ok) { close(); }
      else {
        msg.textContent = '';
        pubBtn.disabled = false;
        pubBtn.textContent = '📤 Publier maintenant';
      }
    };
  },

  // Publie un bloc proposé par l'IA. Verrou _pubBusy : une seule
  // publication à la fois, impossible de re-cliquer pendant l'envoi.
  // Renvoie true si la publication a réussi.
  // opts.skipConfirm : true quand on arrive de l'aperçu (la modif vient
  // d'être vue) — sinon on confirme TOUJOURS avant de toucher au site.
  async _publishFinding(audit, finding, btn, opts = {}) {
    if (this._pubBusy) return false;
    const prevLabel = btn ? btn.textContent : '';
    if (btn) btn.disabled = true;
    if (!audit.site_id) {
      // Pas de site lié à l'audit → fenêtre de choix (plus de « tape le numéro »)
      const sid = await this._pickPublishSite();
      if (!sid) {
        if (btn) { btn.disabled = false; btn.textContent = prevLabel; }
        return false;
      }
      audit.site_id = sid;
    }
    // Garde-fou : un clic sur la carte publie pour de vrai sur le site.
    if (!opts.skipConfirm) {
      const okGo = await Dialog.confirm(
        'Ce bloc écrit par l’IA va être publié pour de vrai sur ton site '
        + '(visible en ligne d’ici 1 à 3 minutes).\n\n'
        + 'Astuce : le bouton « 👁 Aperçu » montre exactement ce qui change, '
        + 'avant d’envoyer.',
        { title: 'Publier sur le site ?', danger: true,
          okLabel: 'Publier', cancelLabel: 'Annuler' });
      if (!okGo) {
        if (btn) { btn.disabled = false; btn.textContent = prevLabel; }
        return false;
      }
    }
    if (this._pubBusy) { // une autre publication a démarré entre-temps
      if (btn) { btn.disabled = false; btn.textContent = prevLabel; }
      return false;
    }
    this._pubBusy = true;
    if (btn) btn.textContent = '⏳ Publication en cours…';
    try {
      const r = await App.api.geo_publish_finding({
        audit_id: audit.id, finding_id: finding.id, site_id: audit.site_id,
      });
      if (!r || !r.ok) {
        Toast.error((r && r.error) || 'La publication a échoué.');
        if (btn) { btn.disabled = false; btn.textContent = prevLabel; }
        return false;
      }
      if (btn) {
        btn.disabled = true;
        btn.textContent = '✓ Publié';
        btn.classList.remove('btn-primary');
        btn.classList.add('btn-secondary');
      }
      // Reflète tout de suite l'état serveur (compteur ✏️, fiche) sans
      // attendre un rechargement : la suggestion est appliquée.
      finding.applied_at = new Date().toISOString();
      Toast.success(`Le site se met à jour dans 1 à 3 minutes : ${r.url}`, 'Publié !');
      return true;
    } catch (e) {
      Toast.friendlyError(e, 'La publication a échoué. Réessaie dans un instant.');
      if (btn) { btn.disabled = false; btn.textContent = prevLabel; }
      return false;
    } finally {
      this._pubBusy = false;
    }
  },

  // Fenêtre de choix du site de publication (même présentation que la
  // fenêtre « Publier sur un site » du générateur). Résout l'id du site
  // choisi, ou null si on annule.
  async _pickPublishSite() {
    let sites = [];
    try {
      const r = await App.api.geo_sites({});
      if (r && r.ok) sites = (r.sites || []).filter(s => s.repo);
    } catch (e) { /* tolère */ }
    if (sites.length === 0) {
      Toast.warn('Aucun de tes sites n’est branché à la mise en ligne automatique. Ouvre ton site (ou ajoute-le), bouton ✎ Modifier → remplis la section « Publication automatique ».');
      return null;
    }
    return new Promise((resolve) => {
      const overlay = document.createElement('div');
      overlay.className = 'geo-modal-overlay';
      overlay.innerHTML = `
        <div class="geo-modal">
          <h3 class="geo-modal-title">Sur quel site publier ?</h3>
          <p class="geo-modal-sub">La page sera créée sur le site choisi, qui se mettra à jour tout seul.</p>
          <div class="geo-form-col">
            <label class="geo-label">Site cible</label>
            <select id="geo-pick-site" class="geo-input">
              ${sites.map(s => `<option value="${this._esc(s.id)}">${this._esc(s.name)} — ${this._esc(s.repo)}</option>`).join('')}
            </select>
          </div>
          <div class="geo-modal-actions">
            <button class="btn btn-secondary" id="geo-pick-cancel">Annuler</button>
            <button class="btn btn-primary" id="geo-pick-ok">Choisir ce site</button>
          </div>
        </div>
      `;
      document.body.appendChild(overlay);
      const done = (val) => { document.removeEventListener('keydown', onKey); overlay.remove(); resolve(val); };
      const onKey = (e) => { if (e.key === 'Escape') done(null); };
      document.addEventListener('keydown', onKey);
      overlay.onclick = (e) => { if (e.target === overlay) done(null); };
      document.getElementById('geo-pick-cancel').onclick = () => done(null);
      document.getElementById('geo-pick-ok').onclick = () =>
        done(document.getElementById('geo-pick-site').value || null);
    });
  },

  async _runAudit(url) {
    if (this._busy) return;
    const msg = document.getElementById('geo-audit-msg');
    const out = document.getElementById('geo-audit-result');
    const btn = document.getElementById('geo-audit-go');
    url = (url || '').trim();
    if (!url) { msg.textContent = 'Colle d\'abord une adresse de page.'; msg.className = 'geo-msg geo-msg--warn'; return; }
    this._busy = true;
    btn.disabled = true;
    btn.textContent = '⏳ Analyse en cours…';
    msg.textContent = 'On lit ta page et on calcule le score…';
    msg.className = 'geo-msg';
    out.innerHTML = '';
    try {
      const r = await App.api.geo_audit({ url });
      if (!r || !r.ok) {
        msg.textContent = (r && r.error) || 'Erreur inconnue.';
        msg.className = 'geo-msg geo-msg--err';
        return;
      }
      msg.textContent = '';
      out.innerHTML = this._renderAuditResult(r.audit);
    } catch (e) {
      console.warn('[GEO] analyse technique :', e);
      msg.textContent = 'Connexion impossible pendant l’analyse. Réessaie dans un instant.';
      msg.className = 'geo-msg geo-msg--err';
    } finally {
      this._busy = false;
      btn.disabled = false;
      btn.textContent = '📊 Analyse technique';
    }
  },

  _renderAuditResult(a) {
    const scoreColor = a.score >= 75 ? 'success' : a.score >= 50 ? 'warning' : 'danger';
    const verdict = a.score >= 75 ? 'Tes IA vont t\'adorer.'
                  : a.score >= 50 ? 'Ça peut encore beaucoup mieux faire.'
                  : 'Beaucoup de choses à corriger.';
    const groups = { ok: [], warn: [], fail: [] };
    (a.findings || []).forEach(f => (groups[f.status] || groups.warn).push(f));
    const section = (title, items, cls) => items.length === 0 ? '' : `
      <div class="geo-findings-group">
        <div class="geo-findings-head geo-findings-head--${cls}">${title} (${items.length})</div>
        ${items.map(f => `
          <div class="geo-finding geo-finding--${cls}">
            <div class="geo-finding-label">${this._esc(f.label)}</div>
            <div class="geo-finding-advice">${this._esc(f.advice)}</div>
          </div>
        `).join('')}
      </div>
    `;
    return `
      <div class="geo-card geo-card--result">
        <div class="geo-score-row">
          <div class="geo-score geo-score--${scoreColor}">
            <div class="geo-score-value">${a.score}</div>
            <div class="geo-score-max">/ 100</div>
          </div>
          <div class="geo-score-text">
            <div class="geo-score-verdict">${verdict}</div>
            <div class="geo-score-url">${this._esc(a.url)}</div>
            <div class="geo-score-meta">Audit du ${this._fmtDate(a.ts)} · ${(a.stats && a.stats.word_count) || 0} mots lus</div>
          </div>
        </div>
        <div class="geo-findings">
          ${section('À corriger', groups.fail, 'fail')}
          ${section('À améliorer', groups.warn, 'warn')}
          ${section('Bien joué', groups.ok, 'ok')}
        </div>
      </div>
    `;
  },

  // ════════════════════════════════════════════════════════════════════
  // ONGLET 2 — SURVEILLANCE
  // ════════════════════════════════════════════════════════════════════
  async _renderSurveillance(body) {
    body.innerHTML = `<div class="geo-loading">Chargement…</div>`;
    let r;
    try { r = await App.api.geo_state({}); }
    catch (e) { body.innerHTML = this._errBox('Connexion serveur impossible.'); return; }
    if (!r || !r.ok) { body.innerHTML = this._errBox(r && r.error); return; }

    // Si un site est ouvert, vue détail
    if (this._selectedSiteId) {
      const s = (r.sites || []).find(x => x.id === this._selectedSiteId);
      if (s) return this._renderSurveillanceSite(body, s);
      this._selectedSiteId = null;
    }

    const providersInfo = r.providers_count > 0
      ? `<span class="geo-pill geo-pill--ok">${r.providers_count} IA branchée${r.providers_count > 1 ? 's' : ''} : ${r.providers.map(p => p.label).join(', ')}</span>`
      : `<span class="geo-pill geo-pill--warn">Aucune IA branchée — <a href="#" data-go-config>va dans Réglages</a></span>`;

    // Charge les réglages auto-pilote en parallèle
    let ap = null;
    try {
      const ar = await App.api.geo_autopilot_settings({});
      if (ar && ar.ok) ap = ar.settings;
    } catch (e) { /* tolère */ }

    const sites = r.sites || [];
    this._apSites = sites;
    body.innerHTML = `
      <div class="geo-card">
        <div class="geo-row-between">
          <div>
            <h2 class="geo-card-title">Tes sites suivis</h2>
            <p class="geo-card-sub">Pour chaque site, tu listes les questions importantes. On les pose aux IA et on regarde si ton site est cité.</p>
          </div>
          <button id="geo-add-site" class="btn btn-primary">+ Ajouter un site</button>
        </div>
        <div class="geo-pills mt-3">${providersInfo}</div>
      </div>

      ${this._renderAutopilotCard(ap, sites)}

      <div id="geo-sites-grid" class="geo-sites-grid mt-6">
        ${sites.length === 0
          ? `<div class="geo-empty">
              <div class="geo-empty-icon">🛰️</div>
              <h3>Aucun site suivi</h3>
              <p>Ajoute un premier site pour commencer à mesurer ta présence dans les IA.</p>
              <button class="btn btn-primary mt-3" id="geo-add-site-2">+ Ajouter un site</button>
            </div>`
          : sites.map(s => this._renderSiteCard(s)).join('')}
      </div>
    `;
    const addHandler = () => this._openAddSiteDialog();
    document.getElementById('geo-add-site').onclick = addHandler;
    const add2 = document.getElementById('geo-add-site-2');
    if (add2) add2.onclick = addHandler;
    body.querySelectorAll('[data-site-id]').forEach(card => {
      card.onclick = (e) => {
        if (e.target.closest('[data-del-site]')) return;
        this._selectedSiteId = card.dataset.siteId;
        this._renderBody();
      };
      card.onkeydown = (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); card.click(); }
      };
    });
    body.querySelectorAll('[data-del-site]').forEach(btn => {
      btn.onclick = async (e) => {
        e.stopPropagation();
        const sid = btn.dataset.delSite;
        const s = sites.find(x => x.id === sid);
        if (!s) return;
        const ok = await Dialog.confirm(
          `Retirer ${s.name} de la surveillance ? L’historique sera supprimé.`,
          { title: 'Retirer le site', danger: true, okLabel: 'Retirer', cancelLabel: 'Annuler' }
        );
        if (!ok) return;
        try {
          const rr = await App.api.geo_site_remove({ id: sid });
          if (rr && rr.ok) { Toast.success(`${s.name} a été retiré.`); this._renderBody(); }
          else Toast.error((rr && rr.error) || 'Suppression impossible.');
        } catch (e2) { Toast.friendlyError(e2, 'Suppression impossible.'); }
      };
    });
    const cfg = body.querySelector('[data-go-config]');
    if (cfg) cfg.onclick = (e) => { e.preventDefault(); App.show('config', { tab: 'ai' }); };

    // -- Auto-pilote : mêmes contrôles que le mode simple --
    this._wireAutopilot(ap);
  },

  _renderAutopilotCard(ap, sites) {
    if (!ap) {
      return `<div class="geo-card mt-6 geo-ap-card">
        <h3 class="geo-card-title">⚡ Auto-pilote GEO</h3>
        <p class="geo-card-sub">Chargement…</p>
      </div>`;
    }
    const enabled = !!ap.enabled;
    const running = !!ap.running;
    const freq = ap.frequency_days || 14;
    const auto = !!ap.auto_generate;
    const pub  = !!ap.auto_publish;
    const last = ap.last_run_at;
    const summary = ap.last_run_summary || '';
    // -- État réel de la mise en ligne automatique : quels sites sont branchés ?
    const allSites = Array.isArray(sites) ? sites : [];
    const sitesCount = allSites.length;
    const linked = allSites.filter(s => s && s.repo);
    const linkedNames = linked.slice(0, 3).map(s => this._esc(s.name || s.url || 'site')).join(', ')
      + (linked.length > 3 ? `… (${linked.length} en tout)` : '');
    const pubAction = pub
      ? 'chaque page rédigée part en ligne toute seule, sans te demander.'
      : 'coche pour que chaque page rédigée parte en ligne toute seule.';
    let pubHelp = '';
    let pubHelpCls = '';
    if (!auto) {
      pubHelpCls = ' is-warn';
      pubHelp = '⚠ Sans effet pour l’instant : la case « Rédiger automatiquement » au-dessus est décochée, donc aucune page n’est créée.';
    } else if (sitesCount === 0) {
      pubHelp = 'Ajoute d’abord un site pour pouvoir t’en servir.';
    } else if (linked.length === 0) {
      pubHelpCls = ' is-warn';
      pubHelp = '⚠ Aucun de tes sites n’est encore branché : les pages rédigées resteront rangées dans l’app (mode avancé → onglet Générateur), à mettre en ligne toi-même. Pour brancher un site : clique dessus → ✎ Modifier → section « Publication automatique ».';
    } else if (linked.length < sitesCount) {
      pubHelpCls = ' is-ok';
      pubHelp = `✓ Prêt pour ${linkedNames} — ${pubAction} Les autres sites ne sont pas branchés : leurs pages resteront dans l’app (clique sur le site → ✎ Modifier → section « Publication automatique » pour les brancher).`;
    } else {
      pubHelpCls = ' is-ok';
      pubHelp = sitesCount === 1
        ? `✓ ${linkedNames} est branché : ${pubAction}`
        : `✓ Tes ${sitesCount} sites sont branchés : ${pubAction}`;
    }
    return `
      <div class="geo-card mt-6 geo-ap-card ${enabled ? 'is-on' : ''}">
        <div class="geo-row-between">
          <div>
            <div class="hero-kicker">⚡ AUTO-PILOTE GEO</div>
            <h3 class="geo-card-title">${enabled ? 'L\'app fait tout, toute seule' : 'Active l\'auto-pilote pour tout automatiser'}</h3>
            <p class="geo-card-sub">
              ${enabled
                ? `Toutes les <strong>${freq} jours</strong>, l'app relance la surveillance sur tous tes sites${auto ? ' et fait <strong>rédiger automatiquement</strong> par l\'IA une page pour chaque question où tu n\'es pas cité' : ''}. Tu n'as plus rien à faire.`
                : 'Une fois activé, l\'app surveille tes sites, refait le tour des IA à la fréquence choisie, et fait rédiger automatiquement des pages pour les questions où tu n\'es pas cité.'}
            </p>
          </div>
          <div class="geo-ap-actions">
            <label class="geo-toggle">
              <input type="checkbox" id="geo-ap-enabled" ${enabled ? 'checked' : ''}/>
              <span class="geo-toggle-slider"></span>
              <span class="geo-toggle-label">${enabled ? 'Actif' : 'Inactif'}</span>
            </label>
          </div>
        </div>
        <div class="geo-ap-grid mt-4">
          <label class="geo-ap-field">
            <span class="geo-label">Fréquence</span>
            <select id="geo-ap-freq" class="geo-input">
              <option value="7"  ${freq === 7  ? 'selected' : ''}>Tous les 7 jours</option>
              <option value="14" ${freq === 14 ? 'selected' : ''}>Tous les 14 jours</option>
              <option value="30" ${freq === 30 ? 'selected' : ''}>Tous les 30 jours</option>
            </select>
          </label>
          <div class="geo-ap-field">
            <span class="geo-label">Dernier passage</span>
            <div class="geo-ap-last">${last ? this._fmtDate(last) : '—'}</div>
          </div>
          <label class="geo-ap-field geo-ap-check">
            <input type="checkbox" id="geo-ap-autogen" ${auto ? 'checked' : ''}/>
            <span class="geo-ap-check-text">
              <span class="geo-ap-check-title">Rédiger automatiquement les pages manquantes</span>
              <small class="geo-ap-check-help">Pour chaque question où ton site n’est pas cité, l’IA écrit une page prête à publier (3 max par site à chaque passage).</small>
            </span>
          </label>
          <label class="geo-ap-field geo-ap-check">
            <input type="checkbox" id="geo-ap-autopub" ${pub ? 'checked' : ''}/>
            <span class="geo-ap-check-text">
              <span class="geo-ap-check-title">Mettre ces pages en ligne automatiquement</span>
              <small class="geo-ap-check-help${pubHelpCls}">${pubHelp}</small>
            </span>
          </label>
        </div>
        ${summary ? `<div class="geo-ap-summary mt-3">${this._esc(summary)}</div>` : ''}
        <div class="geo-ap-bottom mt-4">
          <button id="geo-ap-run-now" class="btn btn-primary" ${sitesCount === 0 || running ? 'disabled' : ''}
                  title="${sitesCount === 0 ? 'Ajoute un site d’abord' : (running ? 'Cycle en cours' : 'Lance un cycle tout de suite')}">
            ${running ? '⏳ Cycle en cours…' : '🚀 Tout faire maintenant'}
          </button>
          ${running ? `<button id="geo-ap-refresh" class="btn btn-secondary" title="Mettre à jour l’état du cycle tout de suite">🔄 Actualiser</button>` : ''}
          <span class="geo-ap-hint">${running
            ? 'L’app travaille en arrière-plan (l’écran se met à jour tout seul). Tu peux fermer cette page, ça continue.'
            : (enabled ? 'Tu peux aussi déclencher un cycle à la main si tu ne veux pas attendre.' : '')}</span>
        </div>
      </div>
    `;
  },

  _renderSiteCard(s) {
    const score = s.last_run_score;
    const hasRun = score !== null && score !== undefined;
    const scoreCls = !hasRun ? 'idle' : score >= 60 ? 'ok' : score >= 30 ? 'warn' : 'bad';
    const scoreTxt = !hasRun ? '—' : score + '%';
    const subText = !hasRun
      ? 'Pas encore de surveillance lancée'
      : `Citée par ${score}% des IA · ${this._fmtDate(s.last_run_ts)}`;
    const fixes = s.pending_fixes || 0;
    return `
      <div class="geo-site-card" data-site-id="${s.id}" role="button" tabindex="0"
           aria-label="Ouvrir ${this._esc(s.name)}">
        <div class="geo-site-head">
          <div class="geo-site-name">${this._esc(s.name)}</div>
          <button class="geo-icon-btn" data-del-site="${s.id}" title="Retirer ce site" aria-label="Retirer ce site">✕</button>
        </div>
        <div class="geo-site-url">${this._esc(s.url)}</div>
        <div class="geo-site-meta">
          <span class="geo-site-score geo-site-score--${scoreCls}">${scoreTxt}</span>
          <span class="geo-site-questions">${s.questions_count} question${s.questions_count > 1 ? 's' : ''}</span>
        </div>
        <div class="geo-site-sub">${subText}</div>
        ${fixes > 0 ? `<div class="geo-site-fixes" title="Des corrections proposées par l’audit IA attendent ton OK sur la fiche du site">✏️ ${fixes} amélioration${fixes > 1 ? 's' : ''} en attente</div>` : ''}
      </div>
    `;
  },

  async _renderSurveillanceSite(body, site) {
    // Charge questions + historique
    let qs = [], hist = [];
    try {
      const [qr, hr] = await Promise.all([
        App.api.geo_questions({ site_id: site.id }),
        App.api.geo_surveillance_history({ site_id: site.id }),
      ]);
      if (qr && qr.ok) qs = qr.questions || [];
      if (hr && hr.ok) hist = hr.runs || [];
    } catch (e) { /* tolère */ }

    body.innerHTML = `
      <button class="geo-back" id="geo-back">← Retour aux sites</button>
      <div class="geo-card mt-3">
        <div class="geo-row-between">
          <div>
            <div class="hero-kicker">SITE SURVEILLÉ</div>
            <h2 class="geo-card-title">${this._esc(site.name)}</h2>
            <p class="geo-card-sub">${this._esc(site.url)} <span class="geo-site-brand-inline">· marque suivie : <strong>${this._esc(site.brand)}</strong></span></p>
          </div>
          <div class="geo-site-actions">
            <button id="geo-edit-site" class="btn btn-secondary" title="Modifier le site">✎ Modifier</button>
            <button id="geo-del-site"  class="btn btn-secondary geo-btn-danger" title="Supprimer le site">🗑 Supprimer</button>
            <button id="geo-run-now" class="btn btn-primary"
                    ${qs.length === 0 ? 'disabled title="Ajoute au moins une question"' : ''}>
              🚀 Lancer la surveillance
            </button>
          </div>
        </div>
        <div id="geo-run-msg" class="geo-msg"></div>
      </div>

      <div class="geo-card mt-6">
        <div class="geo-row-between">
          <div>
            <h3 class="geo-card-title">Questions à poser aux IA</h3>
            <p class="geo-card-sub">Laisse l'IA te les proposer, ou tape les tiennes (ex : « meilleure agence web à Bordeaux »).</p>
          </div>
          <button id="geo-qsuggest" class="btn btn-secondary"
                  title="L'IA regarde ton site et propose les questions à surveiller">
            ✨ Suggérer avec l’IA
          </button>
        </div>
        <div id="geo-qsuggest-msg" class="geo-msg"></div>
        <div class="geo-form">
          <input id="geo-qadd" type="text" placeholder="Ajoute une question…"
                 class="geo-input" autocomplete="off" />
          <button id="geo-qadd-btn" class="btn btn-primary">Ajouter</button>
        </div>
        <div class="geo-questions mt-3">
          ${qs.length === 0
            ? '<div class="geo-q-empty">Aucune question pour l\'instant. Clique sur « ✨ Suggérer avec l\'IA » pour démarrer en deux secondes.</div>'
            : qs.map(q => `
              <div class="geo-question">
                <span class="geo-q-text">${this._esc(q.text)}</span>
                <button class="geo-icon-btn" data-del-q="${q.id}" title="Supprimer cette question" aria-label="Supprimer cette question">✕</button>
              </div>
            `).join('')}
        </div>
      </div>

      <div class="geo-card mt-6">
        <h3 class="geo-card-title">Historique des passages</h3>
        <p class="geo-card-sub">Le détail de chaque vague de questions posées aux IA.</p>
        ${hist.length === 0
          ? '<div class="geo-q-empty mt-3">Aucune surveillance lancée pour ce site.</div>'
          : `<div class="geo-runs">${hist.map(r => this._renderRunRow(r)).join('')}</div>`}
      </div>
    `;

    document.getElementById('geo-back').onclick = () => {
      this._selectedSiteId = null;
      this._renderBody();
    };
    document.getElementById('geo-run-now').onclick = () => this._runSurveillance(site);
    document.getElementById('geo-edit-site').onclick = () => this._openSiteDialog(site);
    document.getElementById('geo-del-site').onclick = async () => {
      const ok = await Dialog.confirm(
        `Supprimer définitivement ${site.name} ? Les questions et l’historique seront effacés.`,
        { title: 'Supprimer le site', danger: true, okLabel: 'Supprimer', cancelLabel: 'Annuler' }
      );
      if (!ok) return;
      try {
        const r = await App.api.geo_site_remove({ id: site.id });
        if (r && r.ok) {
          Toast.success(`${site.name} a été supprimé.`);
          this._selectedSiteId = null;
          this._renderBody();
        } else {
          Toast.error((r && r.error) || 'Suppression impossible.');
        }
      } catch (e) { Toast.friendlyError(e, 'Suppression impossible.'); }
    };
    const addBtn = document.getElementById('geo-qadd-btn');
    const addInp = document.getElementById('geo-qadd');
    const doAdd = async () => {
      const t = (addInp.value || '').trim();
      if (!t) return;
      addBtn.disabled = true;
      try {
        const r = await App.api.geo_question_add({ site_id: site.id, text: t });
        if (r && r.ok) { this._renderBody(); return; }
        Toast.error((r && r.error) || 'Question non ajoutée. Réessaie.');
      } catch (e) {
        Toast.friendlyError(e, 'Question non ajoutée. Réessaie.');
      } finally {
        addBtn.disabled = false;
      }
    };
    addBtn.onclick = doAdd;
    addInp.addEventListener('keydown', (e) => { if (e.key === 'Enter') doAdd(); });
    const suggestBtn = document.getElementById('geo-qsuggest');
    if (suggestBtn) suggestBtn.onclick = () => this._suggestQuestions(site);
    body.querySelectorAll('[data-del-q]').forEach(b => {
      b.onclick = async () => {
        try {
          const r = await App.api.geo_question_remove({ site_id: site.id, id: b.dataset.delQ });
          if (r && r.ok) this._renderBody();
          else Toast.error((r && r.error) || 'Suppression impossible.');
        } catch (e) { Toast.friendlyError(e, 'Suppression impossible.'); }
      };
    });
    // Expand/collapse de chaque run
    body.querySelectorAll('[data-toggle-run]').forEach(b => {
      b.onclick = () => {
        const card = b.closest('.geo-run');
        if (card) card.classList.toggle('is-open');
      };
    });
  },

  async _suggestQuestions(site) {
    if (this._busy) return;
    const btn = document.getElementById('geo-qsuggest');
    const msg = document.getElementById('geo-qsuggest-msg');
    this._busy = true;
    btn.disabled = true;
    btn.textContent = '⏳ L\'IA analyse ton site…';
    if (msg) { msg.textContent = 'On lit ta page et on demande à Claude de proposer 6-8 questions pertinentes.'; msg.className = 'geo-msg'; }
    try {
      const r = await App.api.geo_suggest_questions({ site_id: site.id });
      if (!r || !r.ok) {
        if (msg) { msg.textContent = (r && r.error) || 'Erreur'; msg.className = 'geo-msg geo-msg--err'; }
        return;
      }
      // Le re-render écrase la zone de message → on annonce en Toast,
      // qui survit au rafraîchissement de la vue.
      const skipTxt = r.skipped ? ` (${r.skipped} déjà présente${r.skipped > 1 ? 's' : ''} ignorée${r.skipped > 1 ? 's' : ''})` : '';
      Toast.success(`${r.count} question${r.count > 1 ? 's' : ''} ajoutée${r.count > 1 ? 's' : ''} par ${r.provider}${skipTxt}.`);
      this._renderBody();
    } catch (e) {
      console.warn('[GEO] suggestions :', e);
      if (msg) { msg.textContent = 'Connexion impossible pendant la suggestion. Réessaie.'; msg.className = 'geo-msg geo-msg--err'; }
    } finally {
      this._busy = false;
      if (btn) { btn.disabled = false; btn.textContent = '✨ Suggérer avec l’IA'; }
    }
  },

  async _runSurveillance(site) {
    if (this._busy) return;
    this._busy = true;
    const btn = document.getElementById('geo-run-now');
    const msg = document.getElementById('geo-run-msg');
    btn.disabled = true;
    btn.textContent = '⏳ En cours… (chaque question est posée à chaque IA)';
    msg.textContent = 'On interroge les IA configurées. Ça peut prendre quelques secondes par question.';
    msg.className = 'geo-msg';
    try {
      const r = await App.api.geo_surveillance_run({ site_id: site.id });
      if (!r || !r.ok) {
        msg.textContent = (r && r.error) || 'Erreur inconnue.';
        msg.className = 'geo-msg geo-msg--err';
      } else {
        msg.textContent = `Surveillance terminée : ${r.run.cited}/${r.run.total} citations (${r.run.score}%).`;
        msg.className = 'geo-msg geo-msg--ok';
        Toast.success(`Surveillance terminée : ${r.run.cited}/${r.run.total} citations (${r.run.score}%).`);
        this._renderBody(); // recharge la vue site
      }
    } catch (e) {
      console.warn('[GEO] surveillance :', e);
      msg.textContent = 'Connexion impossible pendant la surveillance. Réessaie dans un instant.';
      msg.className = 'geo-msg geo-msg--err';
    } finally {
      this._busy = false;
      btn.disabled = false;
      btn.textContent = '🚀 Lancer la surveillance';
    }
  },

  _renderRunRow(r) {
    const cls = r.score >= 60 ? 'ok' : r.score >= 30 ? 'warn' : 'bad';
    return `
      <div class="geo-run">
        <button class="geo-run-head" data-toggle-run>
          <div class="geo-run-when">${this._fmtDate(r.ts)}</div>
          <div class="geo-run-stat">${r.cited}/${r.total} citations</div>
          <div class="geo-run-score geo-run-score--${cls}">${r.score}%</div>
          <div class="geo-run-caret">▾</div>
        </button>
        <div class="geo-run-body">
          ${(r.results || []).map(x => `
            <div class="geo-run-line">
              <div class="geo-run-line-head">
                <span class="geo-run-prov">${this._esc(x.provider_label || x.provider)}</span>
                <span class="geo-run-cited ${x.cited ? 'is-cited' : 'is-not'}">${x.cited ? '✓ cité' : '✗ pas cité'}</span>
              </div>
              <div class="geo-run-q">« ${this._esc(x.question)} »</div>
              ${x.cited && x.snippet ? `<div class="geo-run-snip">${this._esc(x.snippet)}</div>` : ''}
              ${!x.cited && x.answer_preview ? `<div class="geo-run-preview">Extrait réponse IA : ${this._esc(x.answer_preview.slice(0, 200))}…</div>` : ''}
            </div>
          `).join('')}
        </div>
      </div>
    `;
  },

  _openAddSiteDialog() { this._openSiteDialog(null); },

  _openSiteDialog(existing) {
    // Si `existing` est fourni, on est en mode édition (préremplit, met à jour).
    // Sinon on ajoute un nouveau site.
    const isEdit = !!existing;
    const overlay = document.createElement('div');
    overlay.className = 'geo-modal-overlay';
    overlay.innerHTML = `
      <div class="geo-modal">
        <h3 class="geo-modal-title">${isEdit ? 'Modifier le site' : 'Ajouter un site'}</h3>
        <p class="geo-modal-sub">${isEdit ? 'Change ce que tu veux. Les questions et l\'historique restent.' : 'Donne l\'adresse du site à suivre. Tout le reste est optionnel.'}</p>
        <div class="geo-form-col">
          <label class="geo-label">Adresse du site</label>
          <input id="geo-newsite-url" type="url" class="geo-input"
                 placeholder="https://exemple.fr" value="${this._esc(existing?.url || '')}" />
          <label class="geo-label mt-3">Nom court (optionnel)</label>
          <input id="geo-newsite-name" type="text" class="geo-input"
                 placeholder="ex : Mon café à Lyon" value="${this._esc(existing?.name || '')}" />
          <label class="geo-label mt-3">Marque à surveiller (optionnel)</label>
          <input id="geo-newsite-brand" type="text" class="geo-input"
                 placeholder="ex : Café du Centre" value="${this._esc(existing?.brand || '')}" />
        </div>

        <details class="geo-advanced mt-4" ${existing?.repo ? 'open' : ''}>
          <summary class="geo-details-sum">⚙️ Publication automatique sur le site (GitHub)</summary>
          <div class="geo-form-col mt-2">
            <p class="geo-advanced-sub">C’est ici qu’on « branche » le site : une fois ces champs remplis, l’app peut créer les pages directement sur ton site, qui se met à jour tout seul. C’est ce qui permet la « mise en ligne automatique » de l’auto-pilote.</p>
            <label class="geo-label mt-2">Dépôt GitHub</label>
            <input id="geo-newsite-repo" type="text" class="geo-input"
                   placeholder="ex : Jordan-Bourillot/lagriffe-studio" value="${this._esc(existing?.repo || '')}" />
            <label class="geo-label mt-3">Dossier cible dans le dépôt</label>
            <input id="geo-newsite-folder" type="text" class="geo-input"
                   placeholder="geo/" value="${this._esc(existing?.target_folder || 'geo/')}" />
            <label class="geo-label mt-3">Branche (en général « main »)</label>
            <input id="geo-newsite-branch" type="text" class="geo-input"
                   placeholder="main" value="${this._esc(existing?.branch || 'main')}" />
            <label class="geo-label mt-3">Chemin du CSS du site (pour habillage)</label>
            <input id="geo-newsite-css" type="text" class="geo-input"
                   placeholder="style.css" value="${this._esc(existing?.css_path || 'style.css')}" />
            <label class="geo-label mt-3">Adresse publique du dossier (optionnel)</label>
            <input id="geo-newsite-pretty" type="text" class="geo-input"
                   placeholder="https://exemple.fr/geo" value="${this._esc(existing?.pretty_url_base || '')}" />
            <p class="geo-advanced-sub">Sert à afficher la bonne adresse sous chaque page. Laisse vide si tu ne sais pas.</p>
          </div>
        </details>
        <div id="geo-newsite-msg" class="geo-msg"></div>
        <div class="geo-modal-actions">
          <button class="btn btn-secondary" id="geo-newsite-cancel">Annuler</button>
          <button class="btn btn-primary" id="geo-newsite-ok">${isEdit ? 'Enregistrer' : 'Ajouter'}</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);
    // Photo des champs pour la garde « fermer sans perdre la saisie »
    const snapshot = () => JSON.stringify(['url', 'name', 'brand', 'repo', 'folder', 'branch', 'css', 'pretty']
      .map(k => (document.getElementById('geo-newsite-' + k)?.value || '').trim()));
    const initialSnap = snapshot();
    let saving = false;
    const close = () => { document.removeEventListener('keydown', onKey); overlay.remove(); };
    const requestClose = async () => {
      if (saving) return;
      if (snapshot() !== initialSnap) {
        const ok = await Dialog.confirm(
          'Fermer sans enregistrer ? Ce que tu as saisi sera perdu.',
          { title: isEdit ? 'Modification en cours' : 'Ajout en cours', danger: true, okLabel: 'Fermer', cancelLabel: 'Continuer la saisie' }
        );
        if (!ok) return;
      }
      close();
    };
    const onKey = (e) => {
      if (document.getElementById('tc-dialog-overlay')) return; // une confirmation est ouverte
      if (e.key === 'Escape') { e.preventDefault(); requestClose(); }
      else if (e.key === 'Enter' && e.target && e.target.tagName !== 'BUTTON' && e.target.tagName !== 'SUMMARY') {
        e.preventDefault();
        document.getElementById('geo-newsite-ok')?.click();
      }
    };
    document.addEventListener('keydown', onKey);
    overlay.onclick = (e) => { if (e.target === overlay) requestClose(); };
    document.getElementById('geo-newsite-cancel').onclick = requestClose;
    const okBtn = document.getElementById('geo-newsite-ok');
    okBtn.onclick = async () => {
      if (saving) return;
      const url = (document.getElementById('geo-newsite-url').value || '').trim();
      const name = (document.getElementById('geo-newsite-name').value || '').trim();
      const brand = (document.getElementById('geo-newsite-brand').value || '').trim();
      const repo = (document.getElementById('geo-newsite-repo')?.value || '').trim();
      const target_folder = (document.getElementById('geo-newsite-folder')?.value || '').trim();
      const branch = (document.getElementById('geo-newsite-branch')?.value || '').trim();
      const css_path = (document.getElementById('geo-newsite-css')?.value || '').trim();
      const pretty_url_base = (document.getElementById('geo-newsite-pretty')?.value || '').trim();
      const msg = document.getElementById('geo-newsite-msg');
      if (!url) { msg.textContent = 'L’adresse est obligatoire.'; msg.className = 'geo-msg geo-msg--warn'; return; }
      msg.textContent = isEdit ? 'Enregistrement…' : 'Ajout…';
      msg.className = 'geo-msg';
      const payload = { url, name, brand, repo, target_folder, branch, css_path, pretty_url_base };
      saving = true;
      okBtn.disabled = true;
      let r;
      try {
        if (isEdit) r = await App.api.geo_site_update({ id: existing.id, ...payload });
        else        r = await App.api.geo_site_add(payload);
      } catch (e) {
        console.warn('[GEO] enregistrement site :', e);
        r = { ok: false, error: 'Connexion impossible. Vérifie ta connexion et réessaie.' };
      }
      saving = false;
      okBtn.disabled = false;
      if (r && r.ok) {
        close();
        Toast.success(isEdit ? 'Site mis à jour.' : 'Site ajouté.');
        // Rafraîchit la vue réellement affichée (accueil simple, fiche site
        // ou mode avancé) : le site apparaît/se met à jour immédiatement.
        this._refreshCurrentView();
      } else {
        msg.textContent = (r && r.error) || 'Erreur';
        msg.className = 'geo-msg geo-msg--err';
      }
    };
    setTimeout(() => document.getElementById('geo-newsite-url').focus(), 60);
  },

  // ════════════════════════════════════════════════════════════════════
  // ONGLET 3 — GÉNÉRATEUR
  // ════════════════════════════════════════════════════════════════════
  async _renderGenerator(body) {
    body.innerHTML = `
      <div class="geo-card">
        <h2 class="geo-card-title">Rédiger un contenu que les IA citeront</h2>
        <p class="geo-card-sub">Donne le sujet, choisis le format. L'IA écrit en suivant les règles GEO : structure claire, chiffres, listes, pas de blabla marketing.</p>
        <div class="geo-form-col mt-4">
          <label class="geo-label">Sujet</label>
          <input id="geo-gen-topic" type="text" class="geo-input"
                 placeholder="ex : prix d'un site web pour artisan en 2026" />
          <label class="geo-label mt-3">Format</label>
          <div class="geo-kind-grid">
            ${[
              { id: 'faq',        label: 'FAQ',         sub: '5-7 questions/réponses' },
              { id: 'definition', label: 'Définition',  sub: 'Réponse directe en tête' },
              { id: 'guide',      label: 'Guide',       sub: 'Étape par étape' },
              { id: 'comparison', label: 'Comparatif',  sub: 'Tableau d\'options' },
            ].map((k, i) => `
              <label class="geo-kind">
                <input type="radio" name="geo-kind" value="${k.id}" ${i === 0 ? 'checked' : ''}/>
                <div class="geo-kind-card">
                  <div class="geo-kind-label">${k.label}</div>
                  <div class="geo-kind-sub">${k.sub}</div>
                </div>
              </label>
            `).join('')}
          </div>
          <button id="geo-gen-go" class="btn btn-primary geo-btn-big mt-4">✍️ Rédiger</button>
          <div id="geo-gen-msg" class="geo-msg"></div>
        </div>
      </div>

      <div id="geo-gen-output" class="mt-6"></div>

      <div class="geo-card mt-6">
        <h3 class="geo-card-title">Historique</h3>
        <div id="geo-gen-history">Chargement…</div>
      </div>
    `;

    document.getElementById('geo-gen-go').onclick = () => this._runGenerate();
    document.getElementById('geo-gen-topic').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') this._runGenerate();
    });
    this._loadGenHistory();
  },

  async _loadGenHistory() {
    const box = document.getElementById('geo-gen-history');
    if (!box) return;
    const loadFail = () => {
      box.innerHTML = `<div class="geo-q-empty">Impossible de charger l’historique.
        <button class="btn btn-secondary geo-btn-mini" id="geo-gen-history-retry">Réessayer</button></div>`;
      const rb = document.getElementById('geo-gen-history-retry');
      if (rb) rb.onclick = () => this._loadGenHistory();
    };
    try {
      const r = await App.api.geo_generated_list({});
      if (!r || !r.ok) { loadFail(); return; }
      if (!r.items || r.items.length === 0) {
        box.innerHTML = '<div class="geo-q-empty">Aucun contenu généré pour l\'instant.</div>';
        return;
      }
      box.innerHTML = r.items.map(it => {
        const pubs = it.publications || [];
        const pubBadge = pubs.length
          ? `<span class="geo-pub-badge">✓ publié sur ${pubs.length} site${pubs.length > 1 ? 's' : ''}</span>`
          : '';
        return `
        <div class="geo-history-row">
          <div class="geo-history-meta">
            <div class="geo-history-topic">${this._esc(it.topic)} ${pubBadge}</div>
            <div class="geo-history-sub">${this._kindLabel(it.kind)} · ${this._fmtDate(it.ts)} · ${this._esc(it.provider || '')}</div>
            ${pubs.map(p => `<div class="geo-pub-url"><a href="${this._esc(p.url)}" target="_blank" rel="noopener">↗ ${this._esc(p.url)}</a></div>`).join('')}
          </div>
          <div class="geo-history-actions">
            <button class="btn btn-secondary geo-btn-mini" data-show-gen="${it.id}">Voir</button>
            <button class="btn btn-primary geo-btn-mini" data-publish-gen="${it.id}">📤 Publier</button>
            <button class="btn btn-secondary geo-btn-mini" data-del-gen="${it.id}">Supprimer</button>
          </div>
        </div>`;
      }).join('');
      box.querySelectorAll('[data-publish-gen]').forEach(b => {
        b.onclick = () => {
          const it = r.items.find(x => x.id === b.dataset.publishGen);
          if (it) this._openPublishDialog(it);
        };
      });
      box.querySelectorAll('[data-show-gen]').forEach(b => {
        b.onclick = () => {
          const it = r.items.find(x => x.id === b.dataset.showGen);
          if (it) this._showGenerated(it);
        };
      });
      box.querySelectorAll('[data-del-gen]').forEach(b => {
        b.onclick = async () => {
          const it = r.items.find(x => x.id === b.dataset.delGen);
          const ok = await Dialog.confirm(
            `Supprimer « ${it ? it.topic : 'ce contenu'} » ? Le texte généré sera perdu.`,
            { title: 'Supprimer ce contenu', danger: true, okLabel: 'Supprimer', cancelLabel: 'Annuler' }
          );
          if (!ok) return;
          try {
            const rr = await App.api.geo_generated_remove({ id: b.dataset.delGen });
            if (rr && rr.ok) this._loadGenHistory();
            else Toast.error((rr && rr.error) || 'Suppression impossible.');
          } catch (e) { Toast.friendlyError(e, 'Suppression impossible.'); }
        };
      });
    } catch (e) {
      console.warn('[GEO] historique générateur :', e);
      loadFail();
    }
  },

  async _runGenerate() {
    if (this._busy) return;
    const topic = (document.getElementById('geo-gen-topic').value || '').trim();
    const kind = (document.querySelector('input[name="geo-kind"]:checked') || {}).value || 'faq';
    const msg = document.getElementById('geo-gen-msg');
    const btn = document.getElementById('geo-gen-go');
    const out = document.getElementById('geo-gen-output');
    if (!topic) { msg.textContent = 'Donne un sujet d\'abord.'; msg.className = 'geo-msg geo-msg--warn'; return; }
    this._busy = true;
    btn.disabled = true;
    btn.textContent = '⏳ L\'IA rédige…';
    msg.textContent = 'Patience, ça prend 10-30 secondes selon le format.';
    msg.className = 'geo-msg';
    out.innerHTML = '';
    try {
      const r = await App.api.geo_generate({ topic, kind });
      if (!r || !r.ok) {
        msg.textContent = (r && r.error) || 'Erreur';
        msg.className = 'geo-msg geo-msg--err';
        return;
      }
      msg.textContent = '';
      this._showGenerated(r.item);
      this._loadGenHistory();
    } catch (e) {
      console.warn('[GEO] rédaction :', e);
      msg.textContent = 'Connexion impossible pendant la rédaction. Réessaie dans un instant.';
      msg.className = 'geo-msg geo-msg--err';
    } finally {
      this._busy = false;
      btn.disabled = false;
      btn.textContent = '✍️ Rédiger';
    }
  },

  async _openPublishDialog(item) {
    // Charge la liste des sites pour proposer une cible
    let sites = [];
    try {
      const r = await App.api.geo_sites({});
      if (r && r.ok) sites = (r.sites || []).filter(s => s.repo);
    } catch (e) { /* tolère */ }
    if (sites.length === 0) {
      Toast.warn('Aucun site branché à la publication automatique (réglage avancé). Modifie un site et remplis sa section « Publication automatique ».');
      return;
    }
    const overlay = document.createElement('div');
    overlay.className = 'geo-modal-overlay';
    overlay.innerHTML = `
      <div class="geo-modal">
        <h3 class="geo-modal-title">Publier sur un site</h3>
        <p class="geo-modal-sub">Le contenu sera créé en page HTML dans le dossier choisi, et le site se mettra à jour tout seul.</p>
        <div class="geo-form-col">
          <label class="geo-label">Contenu à publier</label>
          <div class="geo-pub-topic">${this._esc(item.topic)}</div>
          <label class="geo-label mt-3">Site cible</label>
          <select id="geo-pub-target" class="geo-input">
            ${sites.map(s => `<option value="${s.id}">${this._esc(s.name)} — ${this._esc(s.repo)}</option>`).join('')}
          </select>
        </div>
        <div id="geo-pub-msg" class="geo-msg"></div>
        <div class="geo-modal-actions">
          <button class="btn btn-secondary" id="geo-pub-cancel">Annuler</button>
          <button class="btn btn-primary" id="geo-pub-ok">📤 Publier maintenant</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);
    let published = false; // pour rafraîchir le badge « publié » à la fermeture
    const close = () => {
      document.removeEventListener('keydown', onKey);
      overlay.remove();
      if (published) this._loadGenHistory();
    };
    const onKey = (e) => { if (e.key === 'Escape' && !this._pubBusy) close(); };
    document.addEventListener('keydown', onKey);
    // Pendant la publication, la fenêtre reste ouverte (indicateur visible)
    overlay.onclick = (e) => { if (e.target === overlay && !this._pubBusy) close(); };
    const cancelBtn = document.getElementById('geo-pub-cancel');
    cancelBtn.onclick = () => { if (!this._pubBusy) close(); };
    document.getElementById('geo-pub-ok').onclick = async () => {
      if (this._pubBusy) return; // verrou : une seule publication à la fois
      const sid = document.getElementById('geo-pub-target').value;
      const msg = document.getElementById('geo-pub-msg');
      const btn = document.getElementById('geo-pub-ok');
      this._pubBusy = true;
      btn.disabled = true;
      cancelBtn.disabled = true;
      btn.textContent = '⏳ Publication en cours…';
      msg.textContent = 'On prépare la page et on l’envoie sur ton site…';
      msg.className = 'geo-msg';
      try {
        const r = await App.api.geo_publish_content({ content_id: item.id, site_id: sid });
        if (!r || !r.ok) {
          Toast.error((r && r.error) || 'La publication a échoué.');
          msg.textContent = (r && r.error) || 'Erreur';
          msg.className = 'geo-msg geo-msg--err';
          btn.disabled = false;
          btn.textContent = '📤 Publier maintenant';
          return;
        }
        published = true;
        Toast.success(`Le site se met à jour dans 1 à 3 minutes : ${r.url}`, 'Publié !');
        msg.textContent = `✓ Publié à l'adresse : ${r.url}. Le site se met à jour dans 1-3 minutes.`;
        msg.className = 'geo-msg geo-msg--ok';
        btn.textContent = '✓ Fermer';
        btn.onclick = () => close();
        btn.disabled = false;
      } catch (e) {
        Toast.friendlyError(e, 'La publication a échoué. Réessaie dans un instant.');
        msg.textContent = 'La publication a échoué. Réessaie dans un instant.';
        msg.className = 'geo-msg geo-msg--err';
        btn.disabled = false;
        btn.textContent = '📤 Publier maintenant';
      } finally {
        this._pubBusy = false;
        cancelBtn.disabled = false;
      }
    };
  },

  _showGenerated(item) {
    const out = document.getElementById('geo-gen-output');
    if (!out) return;
    out.innerHTML = `
      <div class="geo-card geo-card--result">
        <div class="geo-row-between">
          <div>
            <div class="hero-kicker">${this._kindLabel(item.kind).toUpperCase()}</div>
            <h3 class="geo-card-title">${this._esc(item.topic)}</h3>
            <p class="geo-card-sub">Rédigé le ${this._fmtDate(item.ts)} par ${this._esc(item.provider || 'IA')}</p>
          </div>
          <button id="geo-copy" class="btn btn-secondary">📋 Copier</button>
        </div>
        <div class="geo-gen-content">${this._mdToHtml(item.content)}</div>
        <details class="mt-4">
          <summary class="geo-details-sum">Voir la version Markdown brute</summary>
          <pre class="geo-gen-raw">${this._esc(item.content)}</pre>
        </details>
      </div>
    `;
    document.getElementById('geo-copy').onclick = async () => {
      try {
        await navigator.clipboard.writeText(item.content);
        document.getElementById('geo-copy').textContent = '✓ Copié';
        setTimeout(() => {
          const b = document.getElementById('geo-copy');
          if (b) b.textContent = '📋 Copier';
        }, 1500);
      } catch (e) { Toast.error('Copie impossible.'); }
    };
  },

  // ════════════════════════════════════════════════════════════════════
  // ONGLET 4 — RÉPUTATION
  // ════════════════════════════════════════════════════════════════════
  async _renderReputation(body) {
    body.innerHTML = `
      <div class="geo-card">
        <h2 class="geo-card-title">Que disent les IA de ta marque ?</h2>
        <p class="geo-card-sub">On pose 5 questions ciblées à toutes les IA configurées (qui es-tu, réputation, avis, concurrents, fiabilité) et on calcule un score.</p>
        <div class="geo-form">
          <input id="geo-rep-brand" type="text" placeholder="Nom de la marque ou entreprise…"
                 class="geo-input geo-input--big" autocomplete="off" />
          <button id="geo-rep-go" class="btn btn-primary geo-btn-big">Vérifier</button>
        </div>
        <div id="geo-rep-msg" class="geo-msg"></div>
      </div>
      <div id="geo-rep-result" class="mt-6"></div>
      <div class="geo-card mt-6">
        <h3 class="geo-card-title">Historique</h3>
        <div id="geo-rep-history">Chargement…</div>
      </div>
    `;
    document.getElementById('geo-rep-go').onclick = () => this._runReputation();
    document.getElementById('geo-rep-brand').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') this._runReputation();
    });
    this._loadReputationHistory();
  },

  async _loadReputationHistory() {
    const box = document.getElementById('geo-rep-history');
    if (!box) return;
    const loadFail = () => {
      box.innerHTML = `<div class="geo-q-empty">Impossible de charger l’historique.
        <button class="btn btn-secondary geo-btn-mini" id="geo-rep-history-retry">Réessayer</button></div>`;
      const rb = document.getElementById('geo-rep-history-retry');
      if (rb) rb.onclick = () => this._loadReputationHistory();
    };
    try {
      const r = await App.api.geo_reputation_history({});
      if (!r || !r.ok) { loadFail(); return; }
      if (!r.runs || r.runs.length === 0) {
        box.innerHTML = '<div class="geo-q-empty">Aucune vérification de réputation pour l\'instant.</div>';
        return;
      }
      box.innerHTML = r.runs.map(run => {
        const cls = run.score >= 60 ? 'ok' : run.score >= 30 ? 'warn' : 'bad';
        return `
          <div class="geo-history-row">
            <div class="geo-history-meta">
              <div class="geo-history-topic">${this._esc(run.brand)}</div>
              <div class="geo-history-sub">${this._fmtDate(run.ts)} · ${run.known}/${run.total} réponses utiles · ${run.positive_hits}👍 / ${run.negative_hits}👎</div>
            </div>
            <div class="geo-history-actions">
              <span class="geo-rep-score geo-rep-score--${cls}">${run.score}/100</span>
              <button class="btn btn-secondary geo-btn-mini" data-show-rep="${run.id}">Détails</button>
            </div>
          </div>
        `;
      }).join('');
      box.querySelectorAll('[data-show-rep]').forEach(b => {
        b.onclick = () => {
          const run = r.runs.find(x => x.id === b.dataset.showRep);
          if (run) this._showReputation(run);
        };
      });
    } catch (e) {
      console.warn('[GEO] historique réputation :', e);
      loadFail();
    }
  },

  async _runReputation() {
    if (this._busy) return;
    const brand = (document.getElementById('geo-rep-brand').value || '').trim();
    const msg = document.getElementById('geo-rep-msg');
    const btn = document.getElementById('geo-rep-go');
    if (!brand) { msg.textContent = 'Tape un nom de marque.'; msg.className = 'geo-msg geo-msg--warn'; return; }
    this._busy = true;
    btn.disabled = true;
    btn.textContent = '⏳ Vérification…';
    msg.textContent = 'On pose 5 questions à chaque IA. Compte 30 secondes à 1 minute.';
    msg.className = 'geo-msg';
    try {
      const r = await App.api.geo_reputation_run({ brand });
      if (!r || !r.ok) {
        msg.textContent = (r && r.error) || 'Erreur';
        msg.className = 'geo-msg geo-msg--err';
        return;
      }
      msg.textContent = `Vérification terminée · score ${r.run.score}/100.`;
      msg.className = 'geo-msg geo-msg--ok';
      this._showReputation(r.run);
      this._loadReputationHistory();
    } catch (e) {
      console.warn('[GEO] réputation :', e);
      msg.textContent = 'Connexion impossible pendant la vérification. Réessaie dans un instant.';
      msg.className = 'geo-msg geo-msg--err';
    } finally {
      this._busy = false;
      btn.disabled = false;
      btn.textContent = 'Vérifier';
    }
  },

  _showReputation(run) {
    const out = document.getElementById('geo-rep-result');
    if (!out) return;
    const cls = run.score >= 60 ? 'success' : run.score >= 30 ? 'warning' : 'danger';
    const verdict = run.score >= 60 ? 'Bonne présence dans les IA.'
                  : run.score >= 30 ? 'Présence moyenne, à renforcer.'
                  : 'Faible présence ou perception négative.';
    out.innerHTML = `
      <div class="geo-card geo-card--result">
        <div class="geo-score-row">
          <div class="geo-score geo-score--${cls}">
            <div class="geo-score-value">${run.score}</div>
            <div class="geo-score-max">/ 100</div>
          </div>
          <div class="geo-score-text">
            <div class="geo-score-verdict">${verdict}</div>
            <div class="geo-score-url">${this._esc(run.brand)}</div>
            <div class="geo-score-meta">Vérifié le ${this._fmtDate(run.ts)} · ${run.known} réponse${run.known > 1 ? 's' : ''} utile${run.known > 1 ? 's' : ''} sur ${run.total} · ${run.positive_hits} mots positifs / ${run.negative_hits} mots négatifs</div>
          </div>
        </div>
        <div class="geo-rep-grid">
          ${(run.results || []).map(x => `
            <div class="geo-rep-card">
              <div class="geo-rep-card-head">
                <span class="geo-rep-prov">${this._esc(x.provider_label || x.provider)}</span>
                <span class="geo-rep-tags">
                  ${x.known ? '<span class="geo-rep-tag geo-rep-tag--ok">connue</span>' : '<span class="geo-rep-tag geo-rep-tag--bad">inconnue</span>'}
                  ${x.positive_hits ? `<span class="geo-rep-tag geo-rep-tag--ok">${x.positive_hits} avis positif${x.positive_hits > 1 ? 's' : ''}</span>` : ''}
                  ${x.negative_hits ? `<span class="geo-rep-tag geo-rep-tag--bad">${x.negative_hits} avis négatif${x.negative_hits > 1 ? 's' : ''}</span>` : ''}
                </span>
              </div>
              <div class="geo-rep-q">« ${this._esc(x.question)} »</div>
              <div class="geo-rep-answer">${this._esc((x.answer || '').slice(0, 600))}${(x.answer || '').length > 600 ? '…' : ''}</div>
            </div>
          `).join('')}
        </div>
      </div>
    `;
  },

  // ════════════════════════════════════════════════════════════════════
  // HELPERS
  // ════════════════════════════════════════════════════════════════════
  _errBox(msg) {
    return `<div class="geo-card geo-card--err">
      <div class="geo-empty-icon">⚠️</div>
      <h3>Une erreur est survenue</h3>
      <p>${this._esc(msg || 'Erreur inconnue.')}</p>
    </div>`;
  },

  _esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  },

  _fmtDate(iso) {
    if (!iso) return '';
    try {
      const d = new Date(iso);
      const days = ['dim', 'lun', 'mar', 'mer', 'jeu', 'ven', 'sam'];
      const pad = n => String(n).padStart(2, '0');
      return `${days[d.getDay()]} ${pad(d.getDate())}/${pad(d.getMonth() + 1)} ${pad(d.getHours())}h${pad(d.getMinutes())}`;
    } catch (e) { return iso; }
  },

  _kindLabel(k) {
    return { faq: 'FAQ', definition: 'Définition', guide: 'Guide pratique',
             comparison: 'Comparatif' }[k] || k;
  },

  // Mini convertisseur Markdown → HTML, suffisant pour le rendu généré
  // (titres, listes, gras, italique, code inline, tableaux simples)
  _mdToHtml(md) {
    if (!md) return '';
    const esc = this._esc.bind(this);
    let html = esc(md);

    // Tables markdown : on les capture en blocs puis on les transforme
    html = html.replace(
      /((?:^\|[^\n]+\|\n)(?:^\|[\s:|-]+\|\n)(?:^\|[^\n]+\|\n?)+)/gm,
      (block) => {
        const lines = block.trim().split('\n');
        if (lines.length < 2) return block;
        const head = lines[0].split('|').slice(1, -1).map(s => s.trim());
        const rows = lines.slice(2).map(l => l.split('|').slice(1, -1).map(s => s.trim()));
        return `<table class="geo-md-table"><thead><tr>${
          head.map(h => `<th>${h}</th>`).join('')
        }</tr></thead><tbody>${
          rows.map(r => `<tr>${r.map(c => `<td>${c}</td>`).join('')}</tr>`).join('')
        }</tbody></table>`;
      }
    );

    // Titres
    html = html.replace(/^### (.+)$/gm, '<h4>$1</h4>')
               .replace(/^## (.+)$/gm,  '<h3>$1</h3>')
               .replace(/^# (.+)$/gm,   '<h2>$1</h2>');
    // Listes
    html = html.replace(/(?:^- (.+)(?:\n|$))+/gm, (block) =>
      '<ul>' + block.trim().split('\n').map(l =>
        '<li>' + l.replace(/^- /, '') + '</li>'
      ).join('') + '</ul>'
    );
    html = html.replace(/(?:^(\d+)\. (.+)(?:\n|$))+/gm, (block) =>
      '<ol>' + block.trim().split('\n').map(l =>
        '<li>' + l.replace(/^\d+\. /, '') + '</li>'
      ).join('') + '</ol>'
    );
    // Gras / italique / code
    html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
               .replace(/\*([^*]+)\*/g,     '<em>$1</em>')
               .replace(/`([^`]+)`/g,       '<code>$1</code>');
    // Paragraphes (lignes restantes)
    html = html.split(/\n{2,}/).map(block => {
      if (/^<(h\d|ul|ol|table|pre|blockquote)/.test(block.trim())) return block;
      return '<p>' + block.replace(/\n/g, '<br/>') + '</p>';
    }).join('\n');
    return html;
  },
};
