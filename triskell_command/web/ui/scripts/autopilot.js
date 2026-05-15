/* Vue Auto-pilote — décris ta cible une fois, l'app fait tout.
 *
 * Branche le pipeline complet de Triskell Core (search → enrich → IA →
 * envoi → suivi) sur une UI web claire, sans jargon. Les libellés
 * parlent à un humain, pas à un dev.
 */

const Autopilot = {
  cfg: null,           // dernière config chargée
  pollTimer: null,     // setInterval du log live
  logSeen: 0,          // index dernière ligne lue

  async render(container) {
    container.innerHTML = `
      <section class="animate-slide-up max-w-4xl">
        <div class="mb-6 sm:mb-8">
          <div class="flex items-start justify-between gap-3">
            <div class="min-w-0 flex-1">
              <div class="hero-kicker mb-2">AUTO-PILOTE</div>
              <h1 class="hero-title hero-title--md mb-2 sm:mb-3">Décris ta cible une fois.</h1>
              <p class="hero-subtitle">L'app cherche, vérifie, rédige et envoie — pendant que tu fais autre chose.</p>
            </div>
            ${Help.button('autopilot')}
          </div>
          <div class="flex flex-wrap gap-2 sm:gap-3 mt-5 sm:mt-6">
            <button id="ap-save" class="btn btn-secondary">Enregistrer</button>
            <button id="ap-run"  class="btn btn-primary">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><polygon points="5 3 19 12 5 21 5 3"/></svg>
              Lancer maintenant
            </button>
          </div>
        </div>

        <div id="ap-form" class="space-y-8"></div>

        <div class="mt-10">
          <div class="section-label">Journal du run</div>
          <div id="ap-log" class="card p-5 font-mono text-xs leading-relaxed
                                  text-text-secondary whitespace-pre-wrap
                                  min-h-[180px] max-h-[420px] overflow-y-auto">
            (en attente d'un run…)
          </div>
          <div id="ap-stats" class="mt-4 hidden"></div>
        </div>
      </section>
    `;

    document.getElementById('ap-save').onclick = () => this.save();
    document.getElementById('ap-run').onclick  = () => this.run();

    if (!App.api) {
      document.getElementById('ap-form').innerHTML = this._previewBanner();
      return;
    }

    // Charge la config
    let r;
    try { r = await App.api.autopilot_get_config(); }
    catch (e) { r = { ok: false, error: String(e) }; }
    if (!r || !r.ok) {
      document.getElementById('ap-form').innerHTML = `
        <div class="card p-6 text-danger">
          Impossible de charger la config : ${this._esc(r && r.error || 'erreur')}
        </div>`;
      return;
    }
    this.cfg = r.config || {};
    this._renderForm();

    // Si un run est déjà en cours (rechargement de l'écran), reprend le log
    this._refreshStatus(true);
  },

  // ------------------------------------------------------------------
  _renderForm() {
    const c = this.cfg;
    document.getElementById('ap-form').innerHTML = `
      ${this._section('Mode d\'envoi',
        'AUTO : l\'IA envoie chaque mail sans demander. ' +
        'VALIDATION : l\'app prépare un brouillon, tu valides en 1 clic chaque matin.',
        `
        ${this._select('Mode d\'envoi', 'mode', c.mode || 'validation', [
          ['validation', 'Validation manuelle (recommandé pour démarrer)'],
          ['auto',       'Auto (envoi sans demander)'],
        ])}
        ${this._toggle('Auto-pilote programmé chaque nuit', 'enabled', !!c.enabled,
          'Si activé, le pipeline tourne tout seul vers 3h du matin.')}
        `)}

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
            On les filtre ci-dessous, on les enrichit (email/site), puis l'IA leur écrit.
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

      ${this._section('Rédaction des mails par l\'IA',
        'Pour chaque prospect, l\'IA reçoit son contexte (nom, ville, secteur, site web) ' +
        'et tes instructions, puis rédige un mail unique. Pas de copier-coller.',
        `
        ${this._select('Service IA', 'ai_provider', c.ai_provider || 'google', [
          ['google',    'Google Gemini'],
          ['anthropic', 'Anthropic Claude'],
          ['openai',    'OpenAI GPT'],
          ['mistral',   'Mistral'],
          ['xai',       'xAI Grok'],
        ])}
        ${this._input('Modèle IA', 'ai_model', c.ai_model || 'gemini-2.5-flash',
          'ex : gemini-2.5-flash (gratuit) ou claude-sonnet-4-5')}
        ${this._input('Règles d\'écriture (numéros séparés par virgules)',
          'ai_mega_prompts_csv', (c.ai_mega_prompts || ['01']).join(','),
          'ex : 01,06,13')}
        ${this._textarea('Mes instructions à l\'IA', 'ai_template_brief',
          c.ai_template_brief || '', 6)}
        ${this._input('Mon prénom (pour la signature)', 'sender_mon_prenom',
          c.sender_mon_prenom || '')}
        ${this._input('Plafond d\'envois par jour', 'daily_cap',
          String(c.daily_cap ?? 40))}
        ${this._input('Délai avant relance (en jours)', 'follow_up_days',
          String(c.follow_up_days ?? 5))}
        `)}
    `;
    this._bindShowWhen();
  },

  // ------------------------------------------------------------------
  // Bindings dynamiques (afficher/masquer selon source choisie)
  _bindShowWhen() {
    const apply = () => {
      const src = (document.querySelector('[data-key="source"]') || {}).value || '';
      document.querySelectorAll('[data-show-when]').forEach(el => {
        const cond = el.dataset.showWhen;  // ex: "source=sirene"
        const [k, v] = cond.split('=');
        el.style.display = (k === 'source' && v === src) ? '' : 'none';
      });
    };
    const sel = document.querySelector('[data-key="source"]');
    if (sel) sel.addEventListener('change', apply);
    apply();
  },

  // ------------------------------------------------------------------
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
      enabled: !!v('enabled'),
      mode:    v('mode') || 'validation',
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
      // Filtres Obelisk
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
      ai_provider:        v('ai_provider') || 'google',
      ai_model:           v('ai_model') || 'gemini-2.5-flash',
      ai_mega_prompts:    v('ai_mega_prompts_csv').split(',').map(s => s.trim()).filter(Boolean),
      ai_template_brief:  v('ai_template_brief'),
      sender_mon_prenom:  v('sender_mon_prenom'),
      daily_cap:          numI('daily_cap', 40),
      follow_up_days:     numI('follow_up_days', 5),
    };
  },

  async save() {
    if (!App.api) return;
    const config = this._gather();
    const btn = document.getElementById('ap-save');
    btn.disabled = true; btn.textContent = 'Enregistrement…';
    try {
      const r = await App.api.autopilot_save_config({ config });
      btn.textContent = (r && r.ok) ? 'Enregistré ✓' : 'Erreur';
    } catch (e) { btn.textContent = 'Erreur'; }
    setTimeout(() => { btn.disabled = false; btn.textContent = 'Enregistrer'; }, 1600);
  },

  async run() {
    if (!App.api) return;
    const config = this._gather();
    const btn = document.getElementById('ap-run');
    btn.disabled = true;
    btn.innerHTML = `<span class="inline-block w-4 h-4 mr-2 rounded-full border-2 border-white/40 border-t-white animate-spin"></span>En cours…`;
    document.getElementById('ap-log').textContent = '';
    document.getElementById('ap-stats').classList.add('hidden');
    this.logSeen = 0;
    try {
      const r = await App.api.autopilot_run({ config });
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
      // run en cours, on continue à poller
      if (!this.pollTimer) this._startPolling();
      return;
    }
    // run terminé
    if (this.pollTimer) {
      clearInterval(this.pollTimer);
      this.pollTimer = null;
    }
    if (!silent) this._stopRun();
    if (r.stats) this._renderStats(r.stats);
    if (r.error) this._appendLog('✗ ' + r.error);
  },

  _stopRun() {
    const btn = document.getElementById('ap-run');
    if (!btn) return;
    btn.disabled = false;
    btn.innerHTML = `
      <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><polygon points="5 3 19 12 5 21 5 3"/></svg>
      Lancer maintenant`;
  },

  _appendLog(line) {
    const box = document.getElementById('ap-log');
    if (!box) return;
    if (box.textContent === '(en attente d\'un run…)') box.textContent = '';
    box.textContent += line + '\n';
    box.scrollTop = box.scrollHeight;
  },

  _renderStats(s) {
    const wrap = document.getElementById('ap-stats');
    if (!wrap) return;
    wrap.classList.remove('hidden');
    wrap.innerHTML = `
      <div class="grid grid-cols-2 md:grid-cols-3 gap-4">
        ${this._kpi('Prospects trouvés', s.searched ?? 0)}
        ${this._kpi('Enrichis (email/tel)', s.enriched ?? 0)}
        ${this._kpi('Mails envoyés', s.drafts_sent ?? 0, 'success')}
        ${this._kpi('Brouillons à valider', s.drafts_pending ?? 0,
          (s.drafts_pending > 0) ? 'accent' : '')}
        ${this._kpi('Réponses détectées', s.replies_detected ?? 0,
          (s.replies_detected > 0) ? 'success' : '')}
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
  // Helpers de rendu (sections / inputs)
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

  _textarea(label, key, value, rows = 4) {
    return `
      <label class="block">
        <div class="text-xs font-medium text-text-secondary mb-1.5">${this._esc(label)}</div>
        <textarea data-key="${key}" rows="${rows}"
                  class="w-full px-3 py-2 rounded-lg bg-bg border border-border
                         focus:border-accent focus:outline-none text-sm font-mono leading-relaxed
                         resize-y">${this._esc(value)}</textarea>
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
        <div class="text-3xl mb-3">⚙️</div>
        <h2 class="text-xl font-semibold mb-2">Mode aperçu</h2>
        <p class="text-text-secondary max-w-md mx-auto">
          Lance Triskell Command via <code class="text-xs px-1.5 py-0.5 rounded bg-bg">py run_web.py</code>
          pour piloter l'auto-pilote.
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
