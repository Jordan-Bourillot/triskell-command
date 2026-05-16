/* Vue Le Phare — agence SEO autonome multi-sites
 *
 * Architecture refondue 2026-05-16 :
 *   - 'hub'      → page d'accueil : phare géant + 3 cartes (NOS SITES / SITES CLIENTS / AGENTS SEO)
 *   - 'sites'    → nos sites Triskell (interne)
 *   - 'clients'  → sites clients externes
 *   - 'agents'   → les 8 agents SEO avec statut et "Lancer maintenant"
 *   - 'site'     → focus 1 site (audit, mots-clés, actions)
 *   - 'prs'      → modifications en attente de validation (clé interne, label "À valider" en UI)
 *   - 'reports'  → bulletins de l'Analyste
 *
 * Navigation : toujours via boutons clairs, jamais d'onglet caché.
 * Retour : bouton "← Le Phare" sur chaque sous-vue.
 */

const Phare = {
  view: 'hub',
  selectedSite: null,

  async render(container) {
    if (this.view === 'hub')     return this._renderHub(container);
    if (this.view === 'sites')   return this._renderSitesList(container, { externalOnly: false });
    if (this.view === 'clients') return this._renderSitesList(container, { externalOnly: true });
    if (this.view === 'agents')  return this._renderAgents(container);
    if (this.view === 'site')    return this._renderSiteDetail(container);
    if (this.view === 'prs')     return this._renderPRs(container);
    if (this.view === 'reports') return this._renderReports(container);
    return this._renderHub(container);
  },

  _go(view, opts = {}) {
    this.view = view;
    if (opts.siteId) this.selectedSite = opts.siteId;
    App.show('phare');
  },

  // ════════════════════════════════════════════════════════════════════
  //  VUE 0 — HUB (page d'accueil somptueuse)
  // ════════════════════════════════════════════════════════════════════
  async _renderHub(container) {
    container.innerHTML = `
      <section class="phare-hub animate-fade-in">
        <!-- Faisceau lumineux derrière (SVG décoratif) -->
        <div class="phare-beam" aria-hidden="true"></div>

        <!-- Colonne gauche : le phare en grand -->
        <div class="phare-tower">
          ${this._lighthouseSvg()}
          <div class="phare-tower-caption">
            <div class="phare-kicker">VISIBILITÉ</div>
            <h1 class="phare-title">Le Phare.</h1>
            <p class="phare-subtitle">Ton agence SEO autonome. Huit agents Claude qui veillent, optimisent et publient sur tes sites pendant que tu dors.</p>
          </div>
        </div>

        <!-- Colonne droite : 3 grosses cartes-boutons -->
        <div class="phare-cards">
          <button class="phare-card" data-go="sites">
            <div class="phare-card-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
                <path d="M3 21h18M5 21V8l7-5 7 5v13M9 21v-6h6v6M9 12h.01M15 12h.01"/>
              </svg>
            </div>
            <div class="phare-card-body">
              <div class="phare-card-title">Nos sites</div>
              <div class="phare-card-desc">Les sites Triskell internes : surveiller, auditer, optimiser.</div>
            </div>
            <div class="phare-card-arrow">→</div>
          </button>

          <button class="phare-card" data-go="clients">
            <div class="phare-card-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="9" cy="8" r="4"/><path d="M3 21v-1a6 6 0 0 1 12 0v1"/>
                <circle cx="17" cy="9" r="3"/><path d="M21 21v-.5a4.5 4.5 0 0 0-6-4.2"/>
              </svg>
            </div>
            <div class="phare-card-body">
              <div class="phare-card-title">Sites clients</div>
              <div class="phare-card-desc">Les sites externes qu'on accompagne. Rapport mensuel automatique.</div>
            </div>
            <div class="phare-card-arrow">→</div>
          </button>

          <button class="phare-card" data-go="agents">
            <div class="phare-card-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
                <path d="M12 2l2.4 4.8L20 8l-4 3.6L17 17l-5-2.6L7 17l1-5.4L4 8l5.6-1.2z"/>
              </svg>
            </div>
            <div class="phare-card-body">
              <div class="phare-card-title">Agents SEO</div>
              <div class="phare-card-desc">Les huit champions Claude. Voir leur statut, lancer une mission.</div>
            </div>
            <div class="phare-card-arrow">→</div>
          </button>

          <!-- Liens secondaires (À valider, Bulletins) — discrets sous les 3 grosses cartes -->
          <div class="phare-secondary">
            <button class="phare-link" data-go="prs">
              <span>À valider</span>
              <span class="phare-link-meta" id="ph-prs-count">—</span>
            </button>
            <button class="phare-link" data-go="reports">
              <span>Bulletins</span>
              <span class="phare-link-meta">de l'Analyste</span>
            </button>
          </div>
        </div>
      </section>
    `;
    // Wiring
    container.querySelectorAll('[data-go]').forEach(btn => {
      btn.onclick = () => this._go(btn.dataset.go);
    });
    // Compteur des modifs en attente de validation (chargement non-bloquant)
    this._loadPendingCount();
  },

  async _loadPendingCount() {
    if (!App.api) return;
    try {
      const data = await App.api.phare_pending_actions();
      const el = document.getElementById('ph-prs-count');
      if (!el) return;
      const n = (data && data.ok) ? (data.actions || []).length : 0;
      el.textContent = n === 0 ? 'rien à valider' : (n === 1 ? '1 modif en attente' : `${n} modifs en attente`);
      if (n > 0) el.style.color = 'hsl(var(--warning))';
    } catch (e) { /* silencieux */ }
  },

  _lighthouseSvg() {
    // Phare en style éditorial épuré : silhouette fine, line art doux,
    // un seul accent coloré (la lampe). Halo généreux mais cadré dans le viewBox.
    // S'adapte aux 3 thèmes via hsl(var(--text)) / var(--accent-glow).
    return `
      <svg class="phare-svg" viewBox="0 0 280 520" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
        <defs>
          <!-- Halo de lumière diffus, doux, généreux -->
          <radialGradient id="phareHalo" cx="50%" cy="50%" r="50%">
            <stop offset="0%"  stop-color="hsl(var(--accent-glow) / 0.40)"/>
            <stop offset="45%" stop-color="hsl(var(--accent) / 0.10)"/>
            <stop offset="100%" stop-color="hsl(var(--accent) / 0)"/>
          </radialGradient>
          <!-- Lampe : noyau chaud qui irradie -->
          <radialGradient id="phareLamp" cx="50%" cy="50%" r="50%">
            <stop offset="0%"  stop-color="hsl(var(--warning))"/>
            <stop offset="60%" stop-color="hsl(var(--warning) / 0.55)"/>
            <stop offset="100%" stop-color="hsl(var(--warning) / 0)"/>
          </radialGradient>
        </defs>

        <!-- Halo large, centré sur la lampe à y=200, contenu dans le viewBox -->
        <circle cx="140" cy="200" r="180" fill="url(#phareHalo)"/>

        <!-- Petite ligne d'horizon (suggestion de mer, très subtile) -->
        <line x1="20" y1="478" x2="260" y2="478"
              stroke="hsl(var(--text) / 0.10)" stroke-width="1"/>

        <!-- Socle minimaliste : trapèze fin -->
        <path d="M108 478 L172 478 L162 462 L118 462 Z"
              fill="hsl(var(--text) / 0.85)"/>

        <!-- Corps du phare : silhouette élancée (trapèze fin) -->
        <path d="M124 462 L116 250 L164 250 L156 462 Z"
              fill="hsl(var(--text) / 0.92)"/>

        <!-- Une seule bande accent, fine et désaturée (suggère le breton sans crier) -->
        <rect x="118" y="356" width="44" height="14"
              fill="hsl(var(--danger) / 0.72)"/>

        <!-- Plateforme : ligne fine -->
        <rect x="110" y="244" width="60" height="6" rx="1"
              fill="hsl(var(--text) / 0.88)"/>

        <!-- Lanterne : carré épuré, juste un trait + la lampe à l'intérieur -->
        <rect x="120" y="194" width="40" height="50" rx="2"
              fill="hsl(var(--bg))"
              stroke="hsl(var(--text) / 0.88)" stroke-width="1.8"/>

        <!-- Halo de la lampe (douceur) -->
        <circle cx="140" cy="216" r="26" fill="url(#phareLamp)" opacity="0.9"/>
        <!-- Noyau de la lampe -->
        <circle cx="140" cy="216" r="7"
                fill="hsl(var(--warning))"/>

        <!-- Toit : triangle minimaliste -->
        <path d="M112 194 L140 168 L168 194 Z"
              fill="hsl(var(--text) / 0.92)"/>

        <!-- Antenne ultra fine, terminée par un point -->
        <line x1="140" y1="168" x2="140" y2="146"
              stroke="hsl(var(--text) / 0.78)" stroke-width="1.4"
              stroke-linecap="round"/>
        <circle cx="140" cy="144" r="2.2" fill="hsl(var(--text) / 0.78)"/>
      </svg>
    `;
  },

  // ════════════════════════════════════════════════════════════════════
  //  Header commun : retour vers le hub + titre
  // ════════════════════════════════════════════════════════════════════
  _backHeader(kicker, title, subtitle, rightHtml = '') {
    return `
      <header class="mb-6 sm:mb-8">
        <button class="phare-back" onclick="Phare.view='hub'; App.show('phare');">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
            <path d="M19 12H5M12 19l-7-7 7-7"/>
          </svg>
          Le Phare
        </button>
        <div class="flex items-start justify-between gap-3 mt-3">
          <div class="min-w-0 flex-1">
            <div class="hero-kicker mb-2">${this._esc(kicker)}</div>
            <h1 class="hero-title hero-title--md mb-2">${this._esc(title)}</h1>
            ${subtitle ? `<p class="hero-subtitle">${this._esc(subtitle)}</p>` : ''}
          </div>
          ${rightHtml}
        </div>
      </header>
    `;
  },

  // ════════════════════════════════════════════════════════════════════
  //  VUE — Sites (interne) OU Clients (externe)
  // ════════════════════════════════════════════════════════════════════
  async _renderSitesList(container, { externalOnly }) {
    const kicker  = externalOnly ? 'AGENCE — SITES CLIENTS' : 'AGENCE — NOS SITES';
    const title   = externalOnly ? 'Sites clients.' : 'Nos sites Triskell.';
    const subt    = externalOnly
      ? "Les sites externes qu'on accompagne. Chaque client reçoit son rapport SEO."
      : "Les sites de l'écosystème Triskell. Audit, optimisation, maillage : tout en continu.";
    const addLabel = externalOnly ? 'Ajouter un client' : 'Ajouter un site';

    const right = `
      <button class="btn btn-primary" data-act="add">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" style="margin-right:6px;vertical-align:-2px">
          <path d="M12 5v14M5 12h14"/>
        </svg>
        ${addLabel}
      </button>
    `;

    container.innerHTML = `
      <section class="animate-slide-up">
        ${this._backHeader(kicker, title, subt, right)}
        <div id="ph-sites-list">
          <div class="text-center py-12 text-text-muted">Chargement…</div>
        </div>
      </section>
    `;
    container.querySelector('[data-act="add"]').onclick = () => this._openSiteDialog({ externalOnly });

    if (!App.api) {
      document.getElementById('ph-sites-list').innerHTML = this._previewSites(externalOnly);
      return;
    }

    let data;
    try { data = await App.api.phare_sites({ external_only: externalOnly }); }
    catch (e) {
      document.getElementById('ph-sites-list').innerHTML = `<div class="card p-6 text-danger">Erreur : ${this._esc(String(e))}</div>`;
      return;
    }
    if (!data || !data.ok) {
      document.getElementById('ph-sites-list').innerHTML = `
        <div class="card p-10 text-center">
          <div class="text-3xl mb-3">🔌</div>
          <h2 class="text-xl font-semibold mb-2">Connexion requise</h2>
          <p class="text-text-secondary mb-6">Le Phare lit ses chiffres dans la base partagée Triskell. Connecte-toi pour activer ce module.</p>
          <button class="btn btn-primary" onclick="App.show('config')">Aller dans Réglages</button>
        </div>`;
      return;
    }
    const list = (data.sites || []).filter(s =>
      externalOnly ? !!s.is_external_client : !s.is_external_client
    );
    this._renderSitesTable(document.getElementById('ph-sites-list'), list, { externalOnly });
  },

  _renderSitesTable(slot, list, { externalOnly }) {
    if (list.length === 0) {
      slot.innerHTML = `
        <div class="card p-10 text-center">
          <div class="text-3xl mb-3">📭</div>
          <h2 class="text-xl font-semibold mb-2">Aucun site pour l'instant</h2>
          <p class="text-text-secondary mb-6">
            ${externalOnly
              ? "Aucun site client enregistré. Clique sur « Ajouter un client » pour démarrer."
              : "Aucun site Triskell suivi. Clique sur « Ajouter un site » pour démarrer."}
          </p>
        </div>`;
      return;
    }
    slot.innerHTML = `
      <div class="card overflow-hidden">
        <table class="w-full text-sm">
          <thead>
            <tr style="background: hsl(var(--bg)); border-bottom: 1px solid hsl(var(--border));">
              <th class="text-left px-5 py-3 font-semibold text-text-muted text-xs tracking-widest">SITE</th>
              <th class="text-left px-5 py-3 font-semibold text-text-muted text-xs tracking-widest">DOMAINE</th>
              <th class="text-right px-5 py-3 font-semibold text-text-muted text-xs tracking-widest">PERF</th>
              <th class="text-right px-5 py-3 font-semibold text-text-muted text-xs tracking-widest">SEO</th>
              <th class="text-right px-5 py-3 font-semibold text-text-muted text-xs tracking-widest">CLICS 30J</th>
              <th class="text-right px-5 py-3 font-semibold text-text-muted text-xs tracking-widest">ACTIONS</th>
            </tr>
          </thead>
          <tbody>
            ${list.map(s => {
              const perf = this._scoreCell(s.lighthouse_perf);
              const seo  = this._scoreCell(s.lighthouse_seo);
              const clicks = this._fmt(s.clicks_30d ?? s.organic_clicks_30d);
              return `
                <tr class="border-b border-border last:border-0 hover:bg-bg/50 transition-colors">
                  <td class="px-5 py-4">
                    <div class="font-semibold">${this._esc(s.name || s.domain || '—')}</div>
                    ${s.stack ? `<div class="text-xs text-text-muted mt-0.5">${this._esc(s.stack)}</div>` : ''}
                  </td>
                  <td class="px-5 py-4 text-text-muted text-xs">${this._esc(s.domain || '')}</td>
                  <td class="px-5 py-4 text-right">${perf}</td>
                  <td class="px-5 py-4 text-right">${seo}</td>
                  <td class="px-5 py-4 text-right">${clicks}</td>
                  <td class="px-5 py-4 text-right">
                    <div class="inline-flex gap-2">
                      <button class="btn-mini" data-focus="${this._esc(s.id || '')}">Ouvrir</button>
                      <button class="btn-mini" data-edit="${this._esc(s.id || '')}">Éditer</button>
                      <button class="btn-mini btn-mini-danger" data-disable="${this._esc(s.id || '')}" data-name="${this._esc(s.name || '')}">Désactiver</button>
                    </div>
                  </td>
                </tr>
              `;
            }).join('')}
          </tbody>
        </table>
      </div>
    `;
    slot.querySelectorAll('[data-focus]').forEach(b => {
      b.onclick = () => this._go('site', { siteId: b.dataset.focus });
    });
    slot.querySelectorAll('[data-edit]').forEach(b => {
      b.onclick = async () => {
        const id = b.dataset.edit;
        const data = await App.api.phare_site({ id });
        if (data && data.ok) this._openSiteDialog({ externalOnly, site: data.site || { id } });
      };
    });
    slot.querySelectorAll('[data-disable]').forEach(b => {
      b.onclick = async () => {
        const id = b.dataset.disable;
        const name = b.dataset.name;
        if (!confirm(`Désactiver « ${name} » ?\n\nLes agents arrêteront de surveiller ce site. Tu pourras le réactiver plus tard.`)) return;
        try {
          await App.api.phare_site_deactivate({ id });
          this._toast('✓ Site désactivé');
          this._renderSitesList(document.getElementById('content'), { externalOnly });
        } catch (e) { this._toast('Erreur : ' + e, 'error'); }
      };
    });
  },

  _scoreCell(score) {
    if (score == null || score === '') return '<span class="text-text-muted">—</span>';
    const v = Number(score);
    if (isNaN(v)) return '<span class="text-text-muted">—</span>';
    let color = 'hsl(var(--danger))';
    if (v >= 90) color = 'hsl(var(--success))';
    else if (v >= 70) color = 'hsl(var(--text))';
    else if (v >= 50) color = 'hsl(var(--warning))';
    return `<span style="color:${color};font-weight:600">${v}</span>`;
  },

  // ════════════════════════════════════════════════════════════════════
  //  Modale d'ajout / édition de site
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
            <div class="hero-kicker mb-1">${externalOnly ? 'SITE CLIENT' : 'NOS SITES'}</div>
            <h2 class="text-xl font-semibold">${isEdit ? 'Modifier le site' : (externalOnly ? 'Ajouter un client' : 'Ajouter un site')}</h2>
          </div>
          <button class="phare-modal-close" data-close>×</button>
        </header>
        <div class="phare-modal-body">
          <p class="text-sm text-text-muted mb-4">
            Remplis les infos du site. Les huit agents commenceront à le surveiller dès la prochaine heure.
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
              <span class="text-sm">Site d'un client externe (active la fiche client + rapport mensuel)</span>
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
        key_paths: (fd.get('key_paths') || '/')
          .toString().split('\n').map(x => x.trim()).filter(Boolean).slice(0, 10),
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
        if (!res || !res.ok) {
          this._toast('Erreur : ' + (res?.error || 'inconnue'), 'error');
          return;
        }
        close();
        this._toast(isEdit ? '✓ Site mis à jour' : '✓ Site ajouté — les agents prennent le relais');
        this._renderSitesList(document.getElementById('content'), { externalOnly });
      } catch (e) { this._toast('Erreur : ' + e, 'error'); }
    };
    // Focus initial
    setTimeout(() => dlg.querySelector('input[name="name"]').focus(), 50);
  },

  _field(name, label, value, placeholder, required = false, type = 'text') {
    return `
      <div>
        <label class="text-xs font-semibold text-text-muted uppercase tracking-wider">${this._esc(label)}${required ? ' *' : ''}</label>
        <input type="${type}" name="${this._esc(name)}" value="${this._esc(value)}"
               placeholder="${this._esc(placeholder)}"
               class="phare-input" ${required ? 'required' : ''}>
      </div>
    `;
  },
  _selectField(name, label, value, options) {
    return `
      <div>
        <label class="text-xs font-semibold text-text-muted uppercase tracking-wider">${this._esc(label)}</label>
        <select name="${this._esc(name)}" class="phare-input">
          ${options.map(o => `<option value="${o}" ${o === value ? 'selected' : ''}>${o}</option>`).join('')}
        </select>
      </div>
    `;
  },
  _textareaField(name, label, value, placeholder) {
    return `
      <div>
        <label class="text-xs font-semibold text-text-muted uppercase tracking-wider">${this._esc(label)}</label>
        <textarea name="${this._esc(name)}" rows="3" placeholder="${this._esc(placeholder)}"
                  class="phare-input" style="font-family:ui-monospace,monospace;font-size:13px">${this._esc(value)}</textarea>
      </div>
    `;
  },

  // ════════════════════════════════════════════════════════════════════
  //  VUE — AGENTS SEO (8 champions)
  // ════════════════════════════════════════════════════════════════════
  async _renderAgents(container) {
    container.innerHTML = `
      <section class="animate-slide-up">
        ${this._backHeader('AGENCE — AGENTS SEO',
          'Les huit champions.',
          "Chacun a sa spécialité. Ensemble, ils gardent tes sites au sommet, 24/7.")}
        <div id="ph-agents-grid">
          <div class="text-center py-12 text-text-muted">Chargement…</div>
        </div>
      </section>
    `;
    let agents = this._defaultAgents();
    if (App.api) {
      try {
        const res = await App.api.phare_agents_status();
        if (res && res.ok && Array.isArray(res.agents)) agents = res.agents;
      } catch (e) { /* fallback sur defaults */ }
    }
    const grid = document.getElementById('ph-agents-grid');
    grid.innerHTML = `
      <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-2 gap-4">
        ${agents.map(a => `
          <article class="agent-card">
            <div class="agent-card-head">
              <div class="agent-card-emoji">${a.emoji || '🤖'}</div>
              <div class="flex-1 min-w-0">
                <div class="agent-card-name">${this._esc(a.label || a.name)}</div>
                <div class="agent-card-role">${this._esc(a.tagline || a.role || '')}</div>
              </div>
              <span class="agent-card-model">${this._esc(a.model_short || a.model || 'Sonnet 4.6')}</span>
            </div>
            <div class="agent-card-desc">${this._esc(a.description || '')}</div>
            <div class="agent-card-stats">
              <div><span class="lbl">Cadence</span><span class="val">${this._esc(a.cadence || '—')}</span></div>
              <div><span class="lbl">Dernier passage</span><span class="val">${a.last_run_at ? this._relTime(a.last_run_at) : 'jamais'}</span></div>
              <div><span class="lbl">Statut</span><span class="val">${this._agentStatus(a.status)}</span></div>
            </div>
            <div class="agent-card-foot">
              <button class="btn-mini" data-agent="${this._esc(a.name)}" data-act="explain">Voir ses missions</button>
              ${a.name !== 'chef_orchestre' ? `<button class="btn-mini btn-mini-primary" data-agent="${this._esc(a.name)}" data-act="run">Lancer maintenant</button>` : `<span class="agent-card-note">Plan mensuel — 1er du mois 9h</span>`}
            </div>
          </article>
        `).join('')}
      </div>
    `;
    grid.querySelectorAll('[data-act="explain"]').forEach(b => {
      b.onclick = () => this._showAgentDetail(b.dataset.agent, agents);
    });
    grid.querySelectorAll('[data-act="run"]').forEach(b => {
      b.onclick = async () => {
        if (!App.api) { this._toast('Mode preview — pas de lancement réel.', 'error'); return; }
        b.disabled = true; b.textContent = 'Lancement…';
        try {
          const res = await App.api.phare_run_agent({ agent: b.dataset.agent });
          if (res && res.ok) this._toast('✓ Mission lancée en arrière-plan');
          else this._toast('Erreur : ' + (res?.error || 'inconnue'), 'error');
        } catch (e) { this._toast('Erreur : ' + e, 'error'); }
        finally { b.disabled = false; b.textContent = 'Lancer maintenant'; }
      };
    });
  },

  _showAgentDetail(agentName, agents) {
    const a = agents.find(x => x.name === agentName);
    if (!a) return;
    const dlg = document.createElement('div');
    dlg.className = 'phare-modal';
    dlg.innerHTML = `
      <div class="phare-modal-backdrop" data-close></div>
      <div class="phare-modal-card">
        <header class="phare-modal-head">
          <div class="flex items-center gap-3">
            <div class="text-3xl">${a.emoji || '🤖'}</div>
            <div>
              <div class="hero-kicker mb-1">AGENT</div>
              <h2 class="text-xl font-semibold">${this._esc(a.label || a.name)}</h2>
            </div>
          </div>
          <button class="phare-modal-close" data-close>×</button>
        </header>
        <div class="phare-modal-body">
          <p class="text-sm mb-4">${this._esc(a.description || '')}</p>
          <div class="section-label">Missions</div>
          <ul class="text-sm space-y-1.5 mb-4">
            ${(a.missions || []).map(m => `<li>• ${this._esc(m)}</li>`).join('')}
          </ul>
          ${a.cadence ? `<div class="section-label">Cadence</div><p class="text-sm mb-2">${this._esc(a.cadence)}</p>` : ''}
          ${a.model ? `<div class="section-label">Modèle Claude</div><p class="text-sm">${this._esc(a.model)}</p>` : ''}
        </div>
        <footer class="phare-modal-foot">
          <button class="btn btn-secondary" data-close>Fermer</button>
        </footer>
      </div>
    `;
    document.body.appendChild(dlg);
    dlg.querySelectorAll('[data-close]').forEach(el => el.onclick = () => dlg.remove());
  },

  _agentStatus(s) {
    const map = {
      'idle':    '<span style="color:hsl(var(--text-muted))">Au repos</span>',
      'running': '<span style="color:hsl(var(--accent));font-weight:600">En mission</span>',
      'ok':      '<span style="color:hsl(var(--success));font-weight:600">Prêt</span>',
      'error':   '<span style="color:hsl(var(--danger));font-weight:600">Erreur</span>',
    };
    return map[s] || '<span style="color:hsl(var(--success));font-weight:600">Prêt</span>';
  },

  _defaultAgents() {
    return [
      { name: 'auditeur', label: "L'Auditeur Technique", emoji: '🔍',
        tagline: 'Détecte tout ce qui freine.',
        description: "Passe chaque site au peigne fin : pages lentes, balises manquantes, liens cassés, problèmes Core Web Vitals. Note de santé sur 100.",
        missions: ["Analyser le crawl + Lighthouse + PageSpeed", "Identifier les 5 problèmes critiques", "Lister les quick wins (effort < 30 min)"],
        cadence: 'Lundi 6h-22h, 1 site par heure',
        model: 'claude-sonnet-4-6', model_short: 'Sonnet 4.6', status: 'ok' },
      { name: 'veilleur', label: 'Le Veilleur Mots-Clés', emoji: '🎯',
        tagline: "Trouve les mots-clés qui payent.",
        description: "Analyse tes positions GSC + les SERP concurrents pour repérer les mots-clés à fort potentiel. Construit le cocon sémantique.",
        missions: ["10 mots-clés prioritaires (volume FR > 50)", "20 long-traîne en cluster", "Cocon sémantique (thème pivot + sous-thèmes)"],
        cadence: 'Lundi & jeudi 7h',
        model: 'claude-sonnet-4-6', model_short: 'Sonnet 4.6', status: 'ok' },
      { name: 'redacteur', label: 'Le Rédacteur', emoji: '✍️',
        tagline: 'Écrit comme un humain. Mieux.',
        description: "Produit des articles SEO complets (1000-1500 mots) à partir des briefs du Veilleur. Voix Triskell, anti-slop activé.",
        missions: ["Brief + article complet à partir d'un mot-clé", "Structure H1/H2/H3 propre", "Suggestions de maillage interne"],
        cadence: 'À la demande (déclenché par le Chef d\'Orchestre)',
        model: 'claude-sonnet-4-6', model_short: 'Sonnet 4.6', status: 'ok' },
      { name: 'optimiseur_onpage', label: "L'Optimiseur On-Page", emoji: '⚡',
        tagline: 'Affûte chaque page au scalpel.',
        description: "Réécrit titres, meta descriptions, Hn, alts et JSON-LD pour booster le SEO sans toucher au contenu. Soumet la modification en validation.",
        missions: ["Réécriture des balises (titre, méta, Hn, alt, JSON-LD)", "Score avant/après estimé", "Modif soumise + aperçu Netlify"],
        cadence: 'Mar/Mer/Ven 10h, 1 site par cycle',
        model: 'claude-sonnet-4-6', model_short: 'Sonnet 4.6', status: 'ok' },
      { name: 'tisseur', label: 'Le Tisseur', emoji: '🕸️',
        tagline: 'Relie tous tes sites en cocon.',
        description: "Maillage interne intra-site + inter-sites Triskell. Détecte les pages orphelines, propose les liens manquants.",
        missions: ["Liens internes manquants", "Liens inter-sites Triskell (cocon global)", "Pages orphelines à reconnecter"],
        cadence: 'Lundi 9h',
        model: 'claude-sonnet-4-6', model_short: 'Sonnet 4.6', status: 'ok' },
      { name: 'chasseur_backlinks', label: 'Le Chasseur Backlinks', emoji: '🪝',
        tagline: 'Va chercher les liens externes.',
        description: "Analyse le gap concurrentiel, repère les mentions non-liées, identifie les opportunités HARO. Score d'impact 0-100.",
        missions: ["Top 10 opportunités d'acquisition", "5 HARO/expert quotes envisageables", "5 mentions non-liées à transformer"],
        cadence: 'Mercredi 9h',
        model: 'claude-sonnet-4-6', model_short: 'Sonnet 4.6', status: 'ok' },
      { name: 'analyste', label: "L'Analyste", emoji: '📊',
        tagline: 'Te dit la vérité chaque matin.',
        description: "Lit tes métriques GSC sur 30 jours, repère les pages qui montent / descendent, chiffre le ROI des actions Phare.",
        missions: ["Bulletin quotidien 8h (top 3 sites)", "Pages qui décollent / décrochent", "Recommandation pour la semaine"],
        cadence: 'Tous les jours 8h',
        model: 'claude-sonnet-4-6', model_short: 'Sonnet 4.6', status: 'ok' },
      { name: 'chef_orchestre', label: "Le Chef d'Orchestre", emoji: '👑',
        tagline: 'Le cerveau stratégique. Opus.',
        description: "Une fois par mois, le modèle le plus puissant prend tout l'écosystème en main et trace le plan du mois pour les 7 autres.",
        missions: ["3 sites prioritaires du mois", "1 chantier transverse", "Briefs cadrés pour chaque agent", "Critères de succès chiffrés"],
        cadence: '1er du mois 9h',
        model: 'claude-opus-4-7', model_short: 'Opus 4.7', status: 'ok' },
    ];
  },

  // ════════════════════════════════════════════════════════════════════
  //  VUE — Détail site
  // ════════════════════════════════════════════════════════════════════
  async _renderSiteDetail(container) {
    if (!this.selectedSite) {
      container.innerHTML = `
        <section class="animate-slide-up">
          ${this._backHeader('SITE', 'Choisis un site', "Reviens à « Nos sites » et clique sur un site pour voir son détail.")}
          <button class="btn btn-secondary" onclick="Phare.view='sites'; App.show('phare');">← Nos sites</button>
        </section>
      `;
      return;
    }
    container.innerHTML = `
      <section class="animate-slide-up">
        ${this._backHeader('SITE', 'Chargement…', '')}
        <div id="ph-site-body"><div class="text-center py-12 text-text-muted">Chargement…</div></div>
      </section>
    `;
    if (!App.api) {
      document.getElementById('ph-site-body').innerHTML = `<div class="card p-6 text-text-muted">Mode preview.</div>`;
      return;
    }
    let data;
    try { data = await App.api.phare_site({ id: this.selectedSite }); }
    catch (e) {
      document.getElementById('ph-site-body').innerHTML = `<div class="card p-6 text-danger">Erreur : ${this._esc(String(e))}</div>`;
      return;
    }
    if (!data || !data.ok) {
      document.getElementById('ph-site-body').innerHTML = `<div class="card p-6 text-danger">${this._esc(data?.error || 'Erreur')}</div>`;
      return;
    }
    const s = data.site || {};
    const audit = data.audit || {};
    const kws = data.keywords || [];
    const acts = data.actions || [];

    // Met à jour le header avec le vrai nom
    container.querySelector('section').innerHTML = `
      ${this._backHeader('SITE', s.name || s.domain || '—', s.domain || '', `
        <button class="btn btn-primary" data-act="audit">Lancer un audit</button>
      `)}
      <div class="grid grid-cols-1 sm:grid-cols-3 gap-3 sm:gap-5 mb-6 sm:mb-10">
        ${this._stat({label: 'Score audit', value: audit.score != null ? audit.score : '—'})}
        ${this._stat({label: 'Mots-clés suivis', value: kws.length})}
        ${this._stat({label: 'Actions ouvertes', value: acts.length, accent: acts.length > 0 ? 'warning' : ''})}
      </div>

      <div class="section-label">Top mots-clés</div>
      <div class="card mb-10 overflow-hidden">
        ${kws.length === 0
          ? `<div class="text-center py-10 text-text-muted text-sm">Aucun mot-clé encore. Le Veilleur va passer lundi ou jeudi à 7h.</div>`
          : `<div class="divide-y divide-border">
              ${kws.slice(0, 10).map(k => `
                <div class="px-5 py-3 flex items-center justify-between text-sm">
                  <div class="flex-1 truncate font-semibold">${this._esc(k.keyword || k.query || '—')}</div>
                  <div class="text-text-muted text-xs ml-4">Position ${k.position != null ? Number(k.position).toFixed(1) : '—'} · ${this._fmt(k.search_volume || k.volume) || '—'}/mo</div>
                </div>
              `).join('')}
            </div>`}
      </div>

      <div class="section-label">Actions récentes</div>
      <div class="card overflow-hidden">
        ${acts.length === 0
          ? `<div class="text-center py-10 text-text-muted text-sm">Aucune action en cours.</div>`
          : `<div class="divide-y divide-border">
              ${acts.slice(0, 10).map(a => {
                const statusLabels = {
                  pending_review: 'à valider',
                  merged: 'publié',
                  rejected: 'refusé',
                  draft: 'brouillon',
                  preview: 'aperçu prêt',
                  expired: 'expiré',
                };
                const statusLabel = statusLabels[a.status] || a.status || 'inconnu';
                return `
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
                    ${this._esc(statusLabel)}
                  </span>
                </div>
              `;}).join('')}
            </div>`}
      </div>
    `;
    const auditBtn = container.querySelector('[data-act="audit"]');
    if (auditBtn) {
      auditBtn.onclick = async () => {
        try {
          await App.api.phare_run_audit({ id: this.selectedSite });
          this._toast('✓ Audit lancé en arrière-plan');
        } catch (e) { this._toast('Erreur : ' + e, 'error'); }
      };
    }
  },

  // ════════════════════════════════════════════════════════════════════
  //  VUE — Modifs à valider
  // ════════════════════════════════════════════════════════════════════
  async _renderPRs(container) {
    container.innerHTML = `
      <section class="animate-slide-up">
        ${this._backHeader('AGENCE — VALIDATION', 'À valider.', "Les modifications proposées par les agents qui attendent ton feu vert.")}
        <div id="ph-prs-body"><div class="text-center py-12 text-text-muted">Chargement…</div></div>
      </section>
    `;
    if (!App.api) {
      document.getElementById('ph-prs-body').innerHTML = `<div class="card p-6 text-text-muted">Mode preview.</div>`;
      return;
    }
    let data;
    try { data = await App.api.phare_pending_actions(); }
    catch (e) {
      document.getElementById('ph-prs-body').innerHTML = `<div class="card p-6 text-danger">Erreur : ${this._esc(String(e))}</div>`;
      return;
    }
    const slot = document.getElementById('ph-prs-body');
    if (!data || !data.ok) {
      slot.innerHTML = `<div class="card p-6 text-danger">${this._esc(data?.error || 'Erreur')}</div>`;
      return;
    }
    const acts = data.actions || [];
    if (acts.length === 0) {
      slot.innerHTML = `
        <div class="card p-6 sm:p-12 text-center">
          <div class="text-4xl mb-3">✓</div>
          <h2 class="text-xl font-semibold mb-2">Rien à valider</h2>
          <p class="text-text-secondary max-w-lg mx-auto">Tout est mergé ou en cours d'analyse. Les agents continuent leur ronde.</p>
        </div>`;
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
              <button class="btn btn-secondary" data-merge="${this._esc(a.id)}" data-force="false">Valider et publier</button>
              <button class="btn btn-primary" data-merge="${this._esc(a.id)}" data-force="true">Publier quand même</button>
            </footer>
          </article>
        `).join('')}
      </div>
    `;
    slot.querySelectorAll('[data-merge]').forEach(btn => {
      btn.onclick = async () => {
        try {
          await App.api.phare_merge_action({ id: btn.dataset.merge, force: btn.dataset.force === 'true' });
          this._renderPRs(container);
        } catch (e) { this._toast('Erreur : ' + e, 'error'); }
      };
    });
  },

  // ════════════════════════════════════════════════════════════════════
  //  VUE — Bulletins
  // ════════════════════════════════════════════════════════════════════
  async _renderReports(container) {
    container.innerHTML = `
      <section class="animate-slide-up">
        ${this._backHeader('AGENCE — BULLETINS', "Bulletins de l'Analyste.",
          "Les rapports hebdomadaires et le plan stratégique mensuel.")}
        <div class="card p-6 sm:p-12 text-center">
          <div class="text-4xl mb-3">📰</div>
          <h2 class="text-xl font-semibold mb-2">Pas encore de bulletin</h2>
          <p class="text-text-secondary max-w-lg mx-auto">
            L'Analyste produit son rapport tous les matins à 8h sur les 3 sites prioritaires.
            Le Chef d'Orchestre (Opus) trace le plan du mois le 1er à 9h.
          </p>
        </div>
      </section>
    `;
  },

  // ════════════════════════════════════════════════════════════════════
  //  Utils
  // ════════════════════════════════════════════════════════════════════
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

  _relTime(iso) {
    if (!iso) return 'jamais';
    try {
      const d = new Date(iso);
      const sec = Math.max(0, (Date.now() - d.getTime()) / 1000);
      if (sec < 60) return 'à l\'instant';
      if (sec < 3600) return `il y a ${Math.floor(sec/60)} min`;
      if (sec < 86400) return `il y a ${Math.floor(sec/3600)} h`;
      return `il y a ${Math.floor(sec/86400)} j`;
    } catch (e) { return iso; }
  },

  _toast(msg, kind = 'success') {
    const t = document.createElement('div');
    t.textContent = msg;
    const bg = kind === 'error' ? 'hsl(var(--danger))' : 'hsl(var(--success))';
    t.style.cssText = `position:fixed;bottom:32px;right:32px;background:${bg};color:white;padding:12px 20px;border-radius:12px;box-shadow:0 8px 24px rgba(0,0,0,0.18);z-index:9999;font-weight:600;font-size:14px;animation:fadeIn .2s ease-out`;
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 3500);
  },

  _previewSites(externalOnly) {
    const list = externalOnly
      ? [{ id: 'demo', name: '(Aucun client externe)', domain: 'exemple-client.fr', clicks_30d: 0 }]
      : [
        { id: '1', name: 'Pack Électricien', domain: 'pack-elec.triskell-studio.fr', clicks_30d: 1840, lighthouse_perf: 92, lighthouse_seo: 100, stack: 'astro' },
        { id: '2', name: 'Studio PDF', domain: 'studio-pdf.triskell-studio.fr', clicks_30d: 920, lighthouse_perf: 88, lighthouse_seo: 95, stack: 'next' },
        { id: '3', name: 'Bobeez', domain: 'bobeez.triskell-studio.fr', clicks_30d: 410, lighthouse_perf: 84, lighthouse_seo: 92, stack: 'astro' },
      ];
    const tmp = document.createElement('div');
    this._renderSitesTable(tmp, list, { externalOnly });
    return tmp.innerHTML;
  },
};
