/* Vue L'Éclaireur — décris ta cible, l'app va chercher les prospects.
 *
 * Outil de prospection : recherche + enrichissement (email/téléphone).
 * Pas d'envoi de mails ici — ça reste le job de l'Auto-pilote.
 * Partage la config avec l'Auto-pilote (autopilot_get/save_config) et
 * appelle autopilot_run avec stages=['search','enrich'].
 */

const Eclaireur = {
  cfg: null,
  pollTimer: null,
  logSeen: 0,

  // Brouillon non sauvegardé persisté en local — permet de retrouver ses
  // modifs en cours même après refresh complet de l'app.
  _LS_DRAFT: 'eclaireur:draft',

  _saveDraft() {
    try {
      const draft = {};
      document.querySelectorAll('#ec-form [data-key]').forEach(el => {
        const k = el.dataset.key;
        draft[k] = (el.type === 'checkbox') ? !!el.checked : el.value;
      });
      localStorage.setItem(this._LS_DRAFT, JSON.stringify(draft));
    } catch (e) {}
  },

  _applyDraft() {
    let draft = null;
    try { draft = JSON.parse(localStorage.getItem(this._LS_DRAFT) || 'null'); }
    catch (e) {}
    if (!draft) return;
    Object.entries(draft).forEach(([k, v]) => {
      const el = document.querySelector(`#ec-form [data-key="${k}"]`);
      if (!el) return;
      if (el.type === 'checkbox') el.checked = !!v;
      else el.value = (v == null ? '' : String(v));
    });
    this._bindShowWhen();  // réapplique l'affichage conditionnel selon la source
  },

  _bindDraftPersist() {
    const root = document.getElementById('ec-form');
    if (!root) return;
    const save = () => this._saveDraft();
    root.querySelectorAll('input, select, textarea').forEach(el => {
      el.addEventListener('input',  save);
      el.addEventListener('change', save);
    });
  },

  async render(container) {
    container.innerHTML = `
      <section class="animate-slide-up max-w-4xl">
        <div class="mb-6 sm:mb-8">
          <div class="flex items-start justify-between gap-3">
            <div class="min-w-0 flex-1">
              <div class="hero-kicker mb-2">L'ÉCLAIREUR</div>
              <h1 class="hero-title hero-title--md mb-2 sm:mb-3">Pars en reconnaissance.</h1>
              <p class="hero-subtitle">Décris ta cible — l'app va chercher les prospects et retrouver leurs emails et téléphones.</p>
            </div>
            ${typeof Help !== 'undefined' ? Help.button('eclaireur') : ''}
          </div>
          <div class="flex flex-wrap gap-2 sm:gap-3 mt-5 sm:mt-6">
            <button id="ec-save" class="btn btn-secondary">Enregistrer</button>
            <button id="ec-run"  class="btn btn-primary">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M21 21l-4.35-4.35"/><circle cx="11" cy="11" r="8"/></svg>
              Lancer la recherche
            </button>
          </div>
        </div>

        <div id="ec-form" class="space-y-8"></div>

        <div class="mt-10">
          <div class="section-label">Journal de la recherche</div>
          <div id="ec-log" class="card p-5 font-mono text-xs leading-relaxed
                                  text-text-secondary whitespace-pre-wrap
                                  min-h-[180px] max-h-[420px] overflow-y-auto">
            (en attente d'une recherche…)
          </div>
          <div id="ec-stats" class="mt-4 hidden"></div>
        </div>
      </section>
    `;

    document.getElementById('ec-save').onclick = () => this.save();
    document.getElementById('ec-run').onclick  = () => this.run();

    if (!App.api) {
      document.getElementById('ec-form').innerHTML = this._previewBanner();
      return;
    }

    let r;
    try { r = await App.api.autopilot_get_config(); }
    catch (e) { r = { ok: false, error: String(e) }; }
    if (!r || !r.ok) {
      document.getElementById('ec-form').innerHTML = `
        <div class="card p-6 text-danger">
          Impossible de charger la config : ${this._esc(r && r.error || 'erreur')}
        </div>`;
      return;
    }
    this.cfg = r.config || {};
    this._renderForm();
    // Si on a un brouillon local plus récent, on l'applique par-dessus la
    // config serveur — sinon Jordan perd ses modifs en cours quand il
    // change de page.
    this._applyDraft();
    this._bindDraftPersist();

    // Le DOM du log vient d'être réinitialisé : on remet le compteur à 0
    // pour re-récupérer l'historique complet du run en cours / dernier run.
    this.logSeen = 0;
    this._refreshStatus(true);
  },

  // ------------------------------------------------------------------
  _renderForm() {
    const c = this.cfg;
    document.getElementById('ec-form').innerHTML = `
      ${this._section('Où trouver les prospects ?',
        'Sirene = entreprises françaises (gratuit). Google Maps = commerces locaux ' +
        '(clé Google requise). Obelisk = créateurs/vendeurs déjà repérés sur les ' +
        'réseaux (déposés dans la base partagée Triskell). Aucune = pas de recherche auto.',
        `
        ${this._select('Base de données', 'source', c.source || 'sirene', [
          ['sirene',  'Sirene — entreprises françaises (gratuit)'],
          ['maps',    'Google Maps — commerces locaux (clé requise)'],
          ['obelisk', 'Obelisk — créateurs et vendeurs sur les réseaux'],
          ['none',    'Aucune (utilise mes prospects existants)'],
        ])}
        <div data-show-when="source=sirene" class="space-y-3 pt-2">
          ${this._input('Code activité (NAF)',  'sirene_naf', c.sirene_naf || '',
            'ex : 43.21A pour électricien')}
          ${this._input('Département',          'sirene_departement', c.sirene_departement || '',
            'ex : 35 pour Ille-et-Vilaine')}
          ${this._input('Code postal',          'sirene_code_postal', c.sirene_code_postal || '')}
          ${this._input('Mot-clé dans le nom',  'sirene_query', c.sirene_query || '')}
          ${this._input('Taille de l\'entreprise', 'sirene_effectif', c.sirene_effectif || '00',
            '00 = sans salarié, 01 = 1-2 salariés…')}
          ${this._input('Créées depuis (AAAA-MM-JJ)', 'sirene_min_date_creation',
            c.sirene_min_date_creation || '',
            'vide = toutes ; ex : 2024-01-01 = uniquement les récentes')}
        </div>
        <div data-show-when="source=maps" class="space-y-3 pt-2">
          ${this._input('Recherche libre',      'maps_query', c.maps_query || '',
            'ex : « boulangerie Rennes »')}
          ${this._input('Latitude',             'maps_lat', c.maps_lat ?? '')}
          ${this._input('Longitude',            'maps_lng', c.maps_lng ?? '')}
          ${this._input('Rayon (mètres)',       'maps_radius_m', String(c.maps_radius_m ?? 50000))}
        </div>
        <div data-show-when="source=obelisk" class="space-y-3 pt-2">
          <div class="text-xs text-text-muted bg-bg/50 border border-border rounded-lg p-3">
            Obelisk a déjà déposé ses créateurs/vendeurs dans la base partagée.
            On les filtre ci-dessous, on les enrichit (email/site), puis ils sont prêts.
          </div>
          ${this._select('Plateforme', 'obelisk_platform', c.obelisk_platform || '', [
            ['',          'Toutes les plateformes'],
            ['youtube',   'YouTube'],
            ['tiktok',    'TikTok'],
            ['instagram', 'Instagram'],
            ['twitch',    'Twitch'],
            ['reddit',    'Reddit'],
            ['bluesky',   'Bluesky'],
            ['mastodon',  'Mastodon'],
            ['kick',      'Kick'],
            ['github',    'GitHub'],
            ['dailymotion', 'Dailymotion'],
            ['apple_podcasts', 'Apple Podcasts'],
          ])}
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
            ${this._input('Audience minimum (abonnés)', 'obelisk_min_subscribers',
              String(c.obelisk_min_subscribers || 0), '0 = pas de plancher')}
            ${this._input('Audience maximum (abonnés)', 'obelisk_max_subscribers',
              String(c.obelisk_max_subscribers || 0), '0 = pas de plafond')}
          </div>
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
            ${this._input('Pays (code ISO)', 'obelisk_country', c.obelisk_country || '',
              'ex : FR')}
            ${this._input('Langue (code ISO)', 'obelisk_language', c.obelisk_language || '',
              'ex : fr')}
          </div>
          ${this._toggle('Uniquement ceux avec un email connu',
            'obelisk_only_with_email', !!c.obelisk_only_with_email,
            'Sinon, l\'enrichissement essaiera de trouver l\'email à partir du site web.')}
          ${this._toggle('Uniquement ceux pas encore contactés',
            'obelisk_only_uncontacted', c.obelisk_only_uncontacted !== false,
            'Évite de recontacter quelqu\'un déjà sollicité.')}
          ${this._toggle('Uniquement les profils détectés monétisés',
            'obelisk_monetized_only', !!c.obelisk_monetized_only,
            'Affiliés, sponsors, boutique en ligne… plus probable d\'être réceptifs.')}
        </div>
        <div class="pt-2">
          ${this._input('Nombre max de prospects par recherche', 'search_max_results',
            String(c.search_max_results ?? 50))}
        </div>
        `)}

      ${this._section('Recherche d\'emails et téléphones',
        'L\'app visite le site web de chaque prospect, en extrait email et téléphone, ' +
        'et vérifie que le site correspond bien à l\'entreprise.',
        `
        ${this._toggle('Détecter automatiquement le site web quand il est inconnu',
          'enrich_with_footprint', c.enrich_with_footprint !== false,
          'Essaie nom-entreprise.fr, .com, etc.')}
        ${this._toggle('Ne traiter que les prospects sans email connu',
          'enrich_no_emails_only', c.enrich_no_emails_only !== false)}
        ${this._input('Nombre max de prospects à enrichir par run', 'enrich_max',
          String(c.enrich_max ?? 100))}
        `)}
    `;
    this._bindShowWhen();
  },

  _bindShowWhen() {
    const apply = () => {
      const src = (document.querySelector('[data-key="source"]') || {}).value || '';
      document.querySelectorAll('[data-show-when]').forEach(el => {
        const cond = el.dataset.showWhen;
        const [k, v] = cond.split('=');
        el.style.display = (k === 'source' && v === src) ? '' : 'none';
      });
    };
    const sel = document.querySelector('[data-key="source"]');
    if (sel) sel.addEventListener('change', apply);
    apply();
  },

  // ------------------------------------------------------------------
  // Récupère uniquement les champs recherche+enrichissement de la config.
  // On fusionne avec la config existante pour ne PAS écraser les champs
  // qui appartiennent désormais à l'Auto-pilote (mode, IA, etc.).
  _gather() {
    const v = (k) => {
      const el = document.querySelector(`[data-key="${k}"]`);
      if (!el) return '';
      if (el.type === 'checkbox') return !!el.checked;
      return el.value;
    };
    const num = (k, d) => {
      const x = parseFloat(v(k));
      return Number.isFinite(x) ? x : d;
    };
    const numI = (k, d) => {
      const x = parseInt(v(k), 10);
      return Number.isFinite(x) ? x : d;
    };
    return {
      ...(this.cfg || {}),
      source:  v('source') || 'sirene',
      sirene_naf:               v('sirene_naf'),
      sirene_departement:       v('sirene_departement'),
      sirene_code_postal:       v('sirene_code_postal'),
      sirene_query:             v('sirene_query'),
      sirene_effectif:          v('sirene_effectif') || '00',
      sirene_min_date_creation: v('sirene_min_date_creation'),
      maps_query:    v('maps_query'),
      maps_lat:      v('maps_lat')  === '' ? null : num('maps_lat', null),
      maps_lng:      v('maps_lng')  === '' ? null : num('maps_lng', null),
      maps_radius_m: numI('maps_radius_m', 50000),
      search_max_results: numI('search_max_results', 50),
      obelisk_platform:        v('obelisk_platform') || '',
      obelisk_min_subscribers: numI('obelisk_min_subscribers', 0),
      obelisk_max_subscribers: numI('obelisk_max_subscribers', 0),
      obelisk_country:         v('obelisk_country') || '',
      obelisk_language:        v('obelisk_language') || '',
      obelisk_only_with_email:  !!v('obelisk_only_with_email'),
      obelisk_only_uncontacted: !!v('obelisk_only_uncontacted'),
      obelisk_monetized_only:   !!v('obelisk_monetized_only'),
      enrich_with_footprint:  !!v('enrich_with_footprint'),
      enrich_no_emails_only:  !!v('enrich_no_emails_only'),
      enrich_max:             numI('enrich_max', 100),
    };
  },

  async save() {
    if (!App.api) return;
    const config = this._gather();
    const btn = document.getElementById('ec-save');
    btn.disabled = true; btn.textContent = 'Enregistrement…';
    try {
      const r = await App.api.autopilot_save_config({ config });
      if (r && r.ok) {
        this.cfg = config;
        // Brouillon = config serveur → on peut le purger.
        try { localStorage.removeItem(this._LS_DRAFT); } catch (e) {}
      }
      btn.textContent = (r && r.ok) ? 'Enregistré ✓' : 'Erreur';
    } catch (e) { btn.textContent = 'Erreur'; }
    setTimeout(() => { btn.disabled = false; btn.textContent = 'Enregistrer'; }, 1600);
  },

  async run() {
    if (!App.api) return;
    const config = this._gather();
    const btn = document.getElementById('ec-run');
    btn.disabled = true;
    btn.innerHTML = `<span class="inline-block w-4 h-4 mr-2 rounded-full border-2 border-white/40 border-t-white animate-spin"></span>En cours…`;
    document.getElementById('ec-log').textContent = '';
    document.getElementById('ec-stats').classList.add('hidden');
    this.logSeen = 0;
    try {
      const r = await App.api.autopilot_run({ config, stages: ['search', 'enrich'] });
      if (!r || !r.ok) {
        this._appendLog((r && r.error) || 'Lancement impossible.');
        this._stopRun();
        return;
      }
      this._startPolling();
    } catch (e) {
      this._appendLog('Erreur : ' + String(e));
      this._stopRun();
    }
  },

  _startPolling() {
    if (this.pollTimer) clearInterval(this.pollTimer);
    this.pollTimer = setInterval(() => this._refreshStatus(false), 1500);
  },

  async _refreshStatus(silent) {
    if (!App.api) return;
    let r;
    try { r = await App.api.autopilot_status({ since: this.logSeen }); }
    catch (e) { return; }
    if (!r || !r.ok) return;

    if (r.log && r.log.length) {
      r.log.forEach(line => this._appendLog(line));
      this.logSeen = r.log_len;
    }
    if (r.running) {
      if (!this.pollTimer) this._startPolling();
      return;
    }
    if (this.pollTimer) {
      clearInterval(this.pollTimer);
      this.pollTimer = null;
    }
    if (!silent) this._stopRun();
    if (r.stats) this._renderStats(r.stats);
    if (r.error) this._appendLog('✗ ' + r.error);
  },

  _stopRun() {
    const btn = document.getElementById('ec-run');
    if (!btn) return;
    btn.disabled = false;
    btn.innerHTML = `
      <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M21 21l-4.35-4.35"/><circle cx="11" cy="11" r="8"/></svg>
      Lancer la recherche`;
  },

  _appendLog(line) {
    const box = document.getElementById('ec-log');
    if (!box) return;
    if (box.textContent === '(en attente d\'une recherche…)') box.textContent = '';
    box.textContent += line + '\n';
    box.scrollTop = box.scrollHeight;
  },

  _renderStats(s) {
    const wrap = document.getElementById('ec-stats');
    if (!wrap) return;
    wrap.classList.remove('hidden');
    wrap.innerHTML = `
      <div class="grid grid-cols-2 md:grid-cols-3 gap-4">
        ${this._kpi('Prospects trouvés', s.searched ?? 0, 'success')}
        ${this._kpi('Enrichis (email/tel)', s.enriched ?? 0, 'success')}
        ${this._kpi('Erreurs', (s.errors || []).length,
          ((s.errors || []).length > 0) ? 'danger' : '')}
      </div>
      ${(s.errors || []).length ? `
        <details class="card p-4 mt-3 text-xs">
          <summary class="cursor-pointer font-semibold text-danger">
            Voir le détail des erreurs
          </summary>
          <ul class="mt-2 space-y-1 text-text-secondary">
            ${s.errors.map(e => `<li>• ${this._esc(e)}</li>`).join('')}
          </ul>
        </details>` : ''}
    `;
  },

  _kpi(label, value, accent = '') {
    const cls = accent ? `accent-${accent}` : '';
    return `
      <div class="stat-card ${cls}">
        <div class="label">${label}</div>
        <div class="value">${value}</div>
      </div>
    `;
  },

  // ------------------------------------------------------------------
  _section(title, subtitle, body) {
    return `
      <div class="card p-6">
        <div class="font-semibold text-base mb-1">${this._esc(title)}</div>
        ${subtitle ? `<div class="text-sm text-text-muted mb-4">${this._esc(subtitle)}</div>` : ''}
        <div class="space-y-3">${body}</div>
      </div>
    `;
  },

  _input(label, key, value, placeholder = '') {
    return `
      <label class="block">
        <div class="text-xs font-medium text-text-secondary mb-1.5">${this._esc(label)}</div>
        <input type="text" data-key="${key}" value="${this._esc(value)}"
               placeholder="${this._esc(placeholder)}"
               class="w-full px-3 py-2 rounded-lg bg-bg border border-border
                      focus:border-accent focus:outline-none text-sm" />
      </label>
    `;
  },

  _select(label, key, value, options) {
    return `
      <label class="block">
        <div class="text-xs font-medium text-text-secondary mb-1.5">${this._esc(label)}</div>
        <select data-key="${key}"
                class="w-full px-3 py-2 rounded-lg bg-bg border border-border
                       focus:border-accent focus:outline-none text-sm">
          ${options.map(([v, l]) => `
            <option value="${this._esc(v)}" ${v === value ? 'selected' : ''}>${this._esc(l)}</option>
          `).join('')}
        </select>
      </label>
    `;
  },

  _toggle(label, key, value, hint = '') {
    return `
      <label class="flex items-start gap-3 cursor-pointer">
        <input type="checkbox" data-key="${key}" ${value ? 'checked' : ''}
               class="mt-0.5 w-4 h-4 accent-accent" />
        <div>
          <div class="text-sm font-medium">${this._esc(label)}</div>
          ${hint ? `<div class="text-xs text-text-muted mt-0.5">${this._esc(hint)}</div>` : ''}
        </div>
      </label>
    `;
  },

  _previewBanner() {
    return `
      <div class="card p-8 text-center">
        <div class="text-3xl mb-3">🔭</div>
        <h2 class="text-xl font-semibold mb-2">Mode aperçu</h2>
        <p class="text-text-secondary max-w-md mx-auto">
          Lance Triskell Command via <code class="text-xs px-1.5 py-0.5 rounded bg-bg">py run_web.py</code>
          pour utiliser L'Éclaireur.
        </p>
      </div>
    `;
  },

  _esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    }[c]));
  },
};
