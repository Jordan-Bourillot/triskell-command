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
  tab: 'audit',           // 'audit' | 'surveillance' | 'generator' | 'reputation'
  _state: null,           // état tableau de bord (cache)
  _selectedSiteId: null,  // dans Surveillance, site ouvert
  _busy: false,           // évite double-clic sur les boutons

  // ════════════════════════════════════════════════════════════════════
  // ENTRY POINT
  // ════════════════════════════════════════════════════════════════════
  async render(container) {
    container.innerHTML = `
      <section class="geo-page animate-fade-in">
        ${this._renderHeader()}
        ${this._renderTabs()}
        <div id="geo-body" class="mt-6"></div>
      </section>
    `;
    container.querySelectorAll('[data-geo-tab]').forEach(b => {
      b.onclick = () => { this.tab = b.dataset.geoTab; this.render(container); };
    });
    await this._renderBody();
  },

  _renderHeader() {
    return `
      <header class="mb-6">
        <div class="hero-kicker mb-2">LE GEO · AGENCE</div>
        <h1 class="hero-title hero-title--md mb-2">Sois cité par les IA.</h1>
        <p class="hero-subtitle">
          Comme le SEO, mais pour ChatGPT, Claude, Gemini et Perplexity.
          Analyse tes pages, surveille ce que les IA disent de toi, et rédige du contenu qu'elles adorent citer.
        </p>
      </header>
    `;
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
        <p class="geo-card-sub">Colle l'adresse d'une page. On regarde si elle est faite pour être citée par les IA, et on te dit ce qu'il faut corriger.</p>
        <div class="geo-form">
          <input id="geo-audit-url" type="url" placeholder="https://exemple.fr/ma-page"
                 class="geo-input geo-input--big" autocomplete="off" />
          <button id="geo-audit-go" class="btn btn-primary geo-btn-big">Analyser</button>
        </div>
        <div id="geo-audit-msg" class="geo-msg"></div>
      </div>
      <div id="geo-audit-result" class="mt-6"></div>
    `;
    const input = document.getElementById('geo-audit-url');
    const btn = document.getElementById('geo-audit-go');
    const run = () => this._runAudit(input.value);
    btn.onclick = run;
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') run(); });
    input.focus();
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
    btn.textContent = 'Analyse en cours…';
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
      msg.textContent = 'Erreur réseau : ' + (e && e.message || e);
      msg.className = 'geo-msg geo-msg--err';
    } finally {
      this._busy = false;
      btn.disabled = false;
      btn.textContent = 'Analyser';
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
    this._state = r;

    // Si un site est ouvert, vue détail
    if (this._selectedSiteId) {
      const s = (r.sites || []).find(x => x.id === this._selectedSiteId);
      if (s) return this._renderSurveillanceSite(body, s);
      this._selectedSiteId = null;
    }

    const providersInfo = r.providers_count > 0
      ? `<span class="geo-pill geo-pill--ok">${r.providers_count} IA configurée${r.providers_count > 1 ? 's' : ''} : ${r.providers.map(p => p.label).join(', ')}</span>`
      : `<span class="geo-pill geo-pill--warn">Aucune IA configurée — <a href="#" data-go-config>va dans Réglages</a></span>`;

    const sites = r.sites || [];
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
    });
    body.querySelectorAll('[data-del-site]').forEach(btn => {
      btn.onclick = async (e) => {
        e.stopPropagation();
        const sid = btn.dataset.delSite;
        const s = sites.find(x => x.id === sid);
        if (!s) return;
        if (!confirm(`Retirer ${s.name} de la surveillance ?\n\nL'historique sera supprimé.`)) return;
        const rr = await App.api.geo_site_remove({ id: sid });
        if (rr && rr.ok) this._renderBody();
        else alert((rr && rr.error) || 'Erreur');
      };
    });
    const cfg = body.querySelector('[data-go-config]');
    if (cfg) cfg.onclick = (e) => { e.preventDefault(); App.show('config'); };
  },

  _renderSiteCard(s) {
    const score = s.last_run_score;
    const hasRun = score !== null && score !== undefined;
    const scoreCls = !hasRun ? 'idle' : score >= 60 ? 'ok' : score >= 30 ? 'warn' : 'bad';
    const scoreTxt = !hasRun ? '—' : score + '%';
    const subText = !hasRun
      ? 'Pas encore de surveillance lancée'
      : `Citée par ${score}% des IA · ${this._fmtDate(s.last_run_ts)}`;
    return `
      <div class="geo-site-card" data-site-id="${s.id}">
        <div class="geo-site-head">
          <div class="geo-site-name">${this._esc(s.name)}</div>
          <button class="geo-icon-btn" data-del-site="${s.id}" title="Retirer">✕</button>
        </div>
        <div class="geo-site-url">${this._esc(s.url)}</div>
        <div class="geo-site-meta">
          <span class="geo-site-score geo-site-score--${scoreCls}">${scoreTxt}</span>
          <span class="geo-site-questions">${s.questions_count} question${s.questions_count > 1 ? 's' : ''}</span>
        </div>
        <div class="geo-site-sub">${subText}</div>
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
            <p class="geo-card-sub">${this._esc(site.url)}</p>
          </div>
          <button id="geo-run-now" class="btn btn-primary"
                  ${qs.length === 0 ? 'disabled title="Ajoute au moins une question"' : ''}>
            🚀 Lancer la surveillance maintenant
          </button>
        </div>
        <div id="geo-run-msg" class="geo-msg"></div>
      </div>

      <div class="geo-card mt-6">
        <h3 class="geo-card-title">Questions à poser aux IA</h3>
        <p class="geo-card-sub">Tape les questions que tes clients posent vraiment (ex : « meilleure agence web à Bordeaux »).</p>
        <div class="geo-form">
          <input id="geo-qadd" type="text" placeholder="Ajoute une question…"
                 class="geo-input" autocomplete="off" />
          <button id="geo-qadd-btn" class="btn btn-primary">Ajouter</button>
        </div>
        <div class="geo-questions mt-3">
          ${qs.length === 0
            ? '<div class="geo-q-empty">Aucune question pour l\'instant.</div>'
            : qs.map(q => `
              <div class="geo-question">
                <span class="geo-q-text">${this._esc(q.text)}</span>
                <button class="geo-icon-btn" data-del-q="${q.id}" title="Supprimer">✕</button>
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
    const addBtn = document.getElementById('geo-qadd-btn');
    const addInp = document.getElementById('geo-qadd');
    const doAdd = async () => {
      const t = (addInp.value || '').trim();
      if (!t) return;
      addBtn.disabled = true;
      const r = await App.api.geo_question_add({ site_id: site.id, text: t });
      addBtn.disabled = false;
      if (r && r.ok) this._renderBody();
      else alert((r && r.error) || 'Erreur');
    };
    addBtn.onclick = doAdd;
    addInp.addEventListener('keydown', (e) => { if (e.key === 'Enter') doAdd(); });
    body.querySelectorAll('[data-del-q]').forEach(b => {
      b.onclick = async () => {
        const r = await App.api.geo_question_remove({ site_id: site.id, id: b.dataset.delQ });
        if (r && r.ok) this._renderBody();
        else alert((r && r.error) || 'Erreur');
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
        this._renderBody(); // recharge la vue site
      }
    } catch (e) {
      msg.textContent = 'Erreur réseau : ' + (e && e.message || e);
      msg.className = 'geo-msg geo-msg--err';
    } finally {
      this._busy = false;
      btn.disabled = false;
      btn.textContent = '🚀 Lancer la surveillance maintenant';
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

  _openAddSiteDialog() {
    // Simple dialog modal inline
    const overlay = document.createElement('div');
    overlay.className = 'geo-modal-overlay';
    overlay.innerHTML = `
      <div class="geo-modal">
        <h3 class="geo-modal-title">Ajouter un site</h3>
        <p class="geo-modal-sub">Donne l'adresse du site à suivre. Tout le reste est optionnel.</p>
        <div class="geo-form-col">
          <label class="geo-label">Adresse du site</label>
          <input id="geo-newsite-url" type="url" class="geo-input"
                 placeholder="https://exemple.fr" />
          <label class="geo-label mt-3">Nom court (optionnel)</label>
          <input id="geo-newsite-name" type="text" class="geo-input"
                 placeholder="ex : Mon café à Lyon" />
          <label class="geo-label mt-3">Marque à surveiller (optionnel)</label>
          <input id="geo-newsite-brand" type="text" class="geo-input"
                 placeholder="ex : Café du Centre" />
        </div>
        <div id="geo-newsite-msg" class="geo-msg"></div>
        <div class="geo-modal-actions">
          <button class="btn btn-secondary" id="geo-newsite-cancel">Annuler</button>
          <button class="btn btn-primary" id="geo-newsite-ok">Ajouter</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);
    const close = () => overlay.remove();
    overlay.onclick = (e) => { if (e.target === overlay) close(); };
    document.getElementById('geo-newsite-cancel').onclick = close;
    document.getElementById('geo-newsite-ok').onclick = async () => {
      const url = (document.getElementById('geo-newsite-url').value || '').trim();
      const name = (document.getElementById('geo-newsite-name').value || '').trim();
      const brand = (document.getElementById('geo-newsite-brand').value || '').trim();
      const msg = document.getElementById('geo-newsite-msg');
      if (!url) { msg.textContent = 'L\'adresse est obligatoire.'; msg.className = 'geo-msg geo-msg--warn'; return; }
      msg.textContent = 'Ajout…';
      const r = await App.api.geo_site_add({ url, name, brand });
      if (r && r.ok) { close(); this._renderBody(); }
      else { msg.textContent = (r && r.error) || 'Erreur'; msg.className = 'geo-msg geo-msg--err'; }
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
    try {
      const r = await App.api.geo_generated_list({});
      if (!r || !r.ok) { box.innerHTML = '<div class="geo-q-empty">Erreur.</div>'; return; }
      if (!r.items || r.items.length === 0) {
        box.innerHTML = '<div class="geo-q-empty">Aucun contenu généré pour l\'instant.</div>';
        return;
      }
      box.innerHTML = r.items.map(it => `
        <div class="geo-history-row">
          <div class="geo-history-meta">
            <div class="geo-history-topic">${this._esc(it.topic)}</div>
            <div class="geo-history-sub">${this._kindLabel(it.kind)} · ${this._fmtDate(it.ts)} · ${this._esc(it.provider || '')}</div>
          </div>
          <div class="geo-history-actions">
            <button class="btn btn-secondary geo-btn-mini" data-show-gen="${it.id}">Voir</button>
            <button class="btn btn-secondary geo-btn-mini" data-del-gen="${it.id}">Supprimer</button>
          </div>
        </div>
      `).join('');
      box.querySelectorAll('[data-show-gen]').forEach(b => {
        b.onclick = () => {
          const it = r.items.find(x => x.id === b.dataset.showGen);
          if (it) this._showGenerated(it);
        };
      });
      box.querySelectorAll('[data-del-gen]').forEach(b => {
        b.onclick = async () => {
          if (!confirm('Supprimer ce contenu généré ?')) return;
          const rr = await App.api.geo_generated_remove({ id: b.dataset.delGen });
          if (rr && rr.ok) this._loadGenHistory();
        };
      });
    } catch (e) {
      box.innerHTML = '<div class="geo-q-empty">Erreur de chargement.</div>';
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
      msg.textContent = 'Erreur réseau : ' + (e && e.message || e);
      msg.className = 'geo-msg geo-msg--err';
    } finally {
      this._busy = false;
      btn.disabled = false;
      btn.textContent = '✍️ Rédiger';
    }
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
      } catch (e) { alert('Copie impossible.'); }
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
    try {
      const r = await App.api.geo_reputation_history({});
      if (!r || !r.ok || !r.runs || r.runs.length === 0) {
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
      box.innerHTML = '<div class="geo-q-empty">Erreur de chargement.</div>';
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
      msg.textContent = 'Erreur réseau : ' + (e && e.message || e);
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
            <div class="geo-score-meta">Vérifié le ${this._fmtDate(run.ts)} · ${run.known}/${run.total} IA t'ont reconnue · ${run.positive_hits} mots positifs / ${run.negative_hits} mots négatifs</div>
          </div>
        </div>
        <div class="geo-rep-grid">
          ${(run.results || []).map(x => `
            <div class="geo-rep-card">
              <div class="geo-rep-card-head">
                <span class="geo-rep-prov">${this._esc(x.provider_label || x.provider)}</span>
                <span class="geo-rep-tags">
                  ${x.known ? '<span class="geo-rep-tag geo-rep-tag--ok">connue</span>' : '<span class="geo-rep-tag geo-rep-tag--bad">inconnue</span>'}
                  ${x.positive_hits ? `<span class="geo-rep-tag geo-rep-tag--ok">+${x.positive_hits}👍</span>` : ''}
                  ${x.negative_hits ? `<span class="geo-rep-tag geo-rep-tag--bad">+${x.negative_hits}👎</span>` : ''}
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
