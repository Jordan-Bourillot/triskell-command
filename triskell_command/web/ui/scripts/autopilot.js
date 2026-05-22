/* Vue Auto-pilote — chef d'orchestre de la chaîne complète.
 *
 * Tableau de commande : 5 boîtes en chaîne (Cherche → Trie → Rédige → Relit
 * → Envoie), chacune avec un interrupteur Auto / Manuel. Le formulaire
 * détaillé (config IA, plafonds, signature) est en bas, replié.
 *
 * État actuel : visuel uniquement. Les interrupteurs sont sauvegardés
 * en localStorage mais pas encore branchés au backend (étape 4 du chantier).
 */

const Autopilot = {
  cfg: null,           // dernière config chargée
  pollTimer: null,     // setInterval du log live
  logSeen: 0,          // index dernière ligne lue

  _LS_DRAFT: 'autopilot:draft',
  _LS_STAGE_MODES: 'autopilot:stage_modes',

  // Les 5 maillons de la chaîne, dans l'ordre.
  _STAGES: [
    {
      key:    'search',
      n:      '1',
      title:  'Cherche',
      sources:'Chasseur · Éclaireur · Obelisk',
      desc:   'Va puiser dans tes sources de prospects.',
      defaultMode: 'auto',
    },
    {
      key:    'sort',
      n:      '2',
      title:  'Trie',
      sources:'Doublons · déjà contactés · clients',
      desc:   'Élimine ce qui ne doit pas être prospecté.',
      defaultMode: 'auto',
    },
    {
      key:    'write',
      n:      '3',
      title:  'Rédige',
      sources:'IA + bon modèle',
      desc:   "Choisit le bon modèle et adapte à chaque prospect.",
      defaultMode: 'auto',
    },
    {
      key:    'review',
      n:      '4',
      title:  'Relit',
      sources:'2è IA · note sur 10',
      desc:   'Une 2è IA vérifie la qualité du mail.',
      defaultMode: 'manual',
    },
    {
      key:    'send',
      n:      '5',
      title:  'Envoie',
      sources:'ou met en brouillon si doute',
      desc:   "Envoie pour de vrai, ou met en brouillon si l'IA hésite.",
      defaultMode: 'manual',
    },
  ],

  // ------------------------------------------------------------------
  // Persistance des modes Auto / Manuel par maillon (localStorage)
  _loadStageModes() {
    let modes = {};
    try { modes = JSON.parse(localStorage.getItem(this._LS_STAGE_MODES) || '{}'); }
    catch (e) {}
    return (modes && typeof modes === 'object') ? modes : {};
  },

  _saveStageMode(key, mode) {
    const modes = this._loadStageModes();
    modes[key] = mode;
    try { localStorage.setItem(this._LS_STAGE_MODES, JSON.stringify(modes)); }
    catch (e) {}
  },

  _getStageMode(stage) {
    const modes = this._loadStageModes();
    return modes[stage.key] || stage.defaultMode;
  },

  _saveDraft() {
    try {
      const draft = {};
      document.querySelectorAll('#ap-form [data-key]').forEach(el => {
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
      const el = document.querySelector(`#ap-form [data-key="${k}"]`);
      if (!el) return;
      if (el.type === 'checkbox') el.checked = !!v;
      else el.value = (v == null ? '' : String(v));
    });
  },

  _bindDraftPersist() {
    const root = document.getElementById('ap-form');
    if (!root) return;
    const save = () => this._saveDraft();
    root.querySelectorAll('input, select, textarea').forEach(el => {
      el.addEventListener('input',  save);
      el.addEventListener('change', save);
    });
  },

  async render(container) {
    container.innerHTML = `
      <section class="animate-slide-up max-w-6xl">
        <div class="mb-6 sm:mb-8">
          <div class="flex items-start justify-between gap-3">
            <div class="min-w-0 flex-1">
              <div class="hero-kicker mb-2">AUTO-PILOTE</div>
              <h1 class="hero-title hero-title--md mb-2 sm:mb-3"
                  style="text-wrap: balance">
                La chaîne complète, sous tes ordres.
              </h1>
              <p class="hero-subtitle" style="text-wrap: pretty">
                Cherche, trie, rédige, relit, envoie. Chaque maillon peut tourner
                tout seul ou te laisser la main.
              </p>
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

        <!-- Tableau de commande : chaîne des 5 maillons + réglages globaux -->
        <div id="ap-control-panel" class="mb-8"></div>

        <!-- Paramètres avancés : ancien formulaire, replié -->
        <details class="card p-0 mb-8 group">
          <summary class="cursor-pointer px-5 py-4 flex items-center justify-between gap-3 hover:bg-bg/40 rounded-2xl">
            <div>
              <div class="font-semibold text-sm">Paramètres avancés</div>
              <div class="text-xs text-text-muted mt-0.5" style="text-wrap: pretty">
                Service IA, modèle, signature, plafonds, délais de relance…
              </div>
            </div>
            <svg class="w-5 h-5 text-text-muted transition-transform group-open:rotate-180"
                 fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
              <polyline points="6 9 12 15 18 9"/>
            </svg>
          </summary>
          <div class="px-5 pb-5 pt-2">
            <div id="ap-form" class="space-y-8"></div>
          </div>
        </details>

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

    // Rend le tableau de commande tout de suite (depuis localStorage cache)
    document.getElementById('ap-control-panel').innerHTML = this._renderControlPanel();
    this._bindStageToggles();
    // En parallele : sync les modes depuis le backend (source de verite)
    this._syncStageModesFromAPI();
    // Charge la liste des produits dispo dans le select
    this._loadProducts();
    // Compteurs : appel asynchrone, met a jour quand l'API repond
    this._refreshPulse();

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
    this._applyDraft();
    this._bindDraftPersist();

    // Le DOM du log vient d'être réinitialisé : on remet le compteur à 0
    // pour re-récupérer l'historique complet du run en cours / dernier run.
    this.logSeen = 0;
    // Si un run est déjà en cours (rechargement de l'écran), reprend le log
    this._refreshStatus(true);
  },

  // ------------------------------------------------------------------
  // Tableau de commande : 5 maillons en chaîne + réglages globaux
  // ------------------------------------------------------------------
  _renderControlPanel() {
    const c = this.cfg || {};
    const nightlyTarget = c.nightly_target ?? 50;
    const enabledNight  = !!c.enabled;
    const product       = c.autopilot_product || '';
    const audience      = c.autopilot_audience || '';
    const nightlyHour   = (c.nightly_hour ?? 3);
    return `
      <!-- Bandeau de réglages globaux : combien + produit + horaire -->
      <div class="card p-5 mb-4">
        <div class="grid grid-cols-1 md:grid-cols-3 gap-5">
          <label class="block">
            <div class="text-xs font-bold uppercase tracking-widest text-text-muted mb-2">
              Cherche-moi
            </div>
            <div class="flex items-baseline gap-3">
              <input type="number" data-key="nightly_target"
                     value="${nightlyTarget}" min="1" max="500"
                     class="w-24 px-3 py-2 rounded-lg bg-bg border border-border
                            focus:border-accent focus:outline-none text-xl font-bold text-center" />
              <span class="text-sm text-text-secondary" style="text-wrap: balance">
                prospects / run
              </span>
            </div>
          </label>

          <label class="block">
            <div class="text-xs font-bold uppercase tracking-widest text-text-muted mb-2">
              Tu pousses quoi ?
            </div>
            <select id="ap-product-select" data-key="autopilot_product"
                    class="w-full px-3 py-2 rounded-lg bg-bg border border-border
                           focus:border-accent focus:outline-none text-sm">
              <option value="">— Laisse l'IA écrire toute seule —</option>
              ${product ? `<option value="${this._esc(product)}" selected>${this._esc(product)}</option>` : ''}
            </select>
            <select id="ap-audience-select" data-key="autopilot_audience"
                    class="w-full mt-2 px-3 py-2 rounded-lg bg-bg border border-border
                           focus:border-accent focus:outline-none text-xs ${product ? '' : 'hidden'}">
              <option value="" ${audience === '' ? 'selected' : ''}>Tout le monde</option>
              <option value="creator" ${audience === 'creator' ? 'selected' : ''}>Influenceurs / créateurs</option>
              <option value="pro" ${audience === 'pro' ? 'selected' : ''}>Pros (artisans, commerçants…)</option>
            </select>
            <div class="text-[11px] text-text-muted mt-1.5 leading-snug"
                 style="text-wrap: pretty">
              Choisis un produit : l'IA piochera dans tes <b>modèles d'emails</b>
              prêts pour ce produit. Sinon, elle invente chaque mail depuis zéro.
            </div>
          </label>

          <label class="flex items-start gap-3 cursor-pointer md:pt-7">
            <input type="checkbox" data-key="enabled" ${enabledNight ? 'checked' : ''}
                   class="mt-1 w-5 h-5 accent-accent flex-shrink-0" />
            <div class="min-w-0">
              <div class="text-sm font-semibold flex items-center gap-2 flex-wrap"
                   style="text-wrap: balance">
                <span>Pipeline auto à</span>
                <input type="number" data-key="nightly_hour"
                       value="${nightlyHour}" min="0" max="23"
                       onclick="event.preventDefault(); event.stopPropagation();"
                       class="w-14 px-2 py-0.5 rounded-md bg-bg border border-border
                              focus:border-accent focus:outline-none text-sm font-bold text-center" />
                <span>h du matin</span>
              </div>
              <div class="text-xs text-text-muted mt-0.5" style="text-wrap: pretty">
                Tu te lèves, ton Cockpit est plein. Heure Paris.
              </div>
            </div>
          </label>
        </div>
      </div>

      <!-- La chaîne des 5 maillons -->
      <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
        ${this._STAGES.map((stage, i) => this._renderStage(stage, i)).join('')}
      </div>

      <!-- Résumé de la dernière nuit (à brancher étape 3) -->
      <div class="mt-4 text-center">
        <span id="ap-last-run-summary" class="text-xs text-text-muted"
              style="text-wrap: pretty">
          Dernière nuit : pas encore branché — viendra à la prochaine étape.
        </span>
      </div>
    `;
  },

  _renderStage(stage, index) {
    const mode = this._getStageMode(stage);
    const isAuto = mode === 'auto';
    const isLast = index === this._STAGES.length - 1;
    return `
      <div class="card p-4 relative flex flex-col" data-stage="${stage.key}">
        <!-- Numéro + titre -->
        <div class="flex items-center gap-2 mb-2">
          <div class="w-7 h-7 rounded-lg bg-accent/10 text-accent flex items-center
                      justify-center text-sm font-bold flex-shrink-0">
            ${stage.n}
          </div>
          <div class="font-semibold text-base">${this._esc(stage.title)}</div>
          ${!isLast ? `
            <svg class="w-4 h-4 text-text-muted ml-auto hidden lg:block flex-shrink-0"
                 fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
              <polyline points="9 18 15 12 9 6"/>
            </svg>` : ''}
        </div>

        <!-- Sources / outils utilisés -->
        <div class="text-[11px] font-medium text-text-muted mb-2 uppercase tracking-wide"
             style="text-wrap: balance">
          ${this._esc(stage.sources)}
        </div>

        <!-- Description -->
        <div class="text-xs text-text-secondary flex-1" style="text-wrap: pretty">
          ${this._esc(stage.desc)}
        </div>

        <!-- Interrupteur Auto / Manuel -->
        <div class="flex items-center justify-between gap-2 mt-4 pt-3 border-t border-border">
          <span class="text-[10px] font-bold tracking-widest text-text-muted">MODE</span>
          <div class="flex gap-0.5 bg-bg rounded-lg p-0.5 border border-border">
            <button class="ap-stage-mode px-2.5 py-1 text-[11px] font-semibold rounded-md transition"
                    data-mode="auto">Auto</button>
            <button class="ap-stage-mode px-2.5 py-1 text-[11px] font-semibold rounded-md transition"
                    data-mode="manual">Manuel</button>
          </div>
        </div>

        <!-- Compteur -->
        <div class="mt-2 text-center text-text-muted text-[11px]">
          <span class="ap-stage-counter font-mono text-text-secondary">—</span>
          <span> cette nuit</span>
        </div>
      </div>
    `;
  },

  _bindStageToggles() {
    document.querySelectorAll('[data-stage]').forEach(stageEl => {
      const stageKey = stageEl.dataset.stage;
      // 1) Applique le style initial (selon état sauvegardé)
      const stage = this._STAGES.find(s => s.key === stageKey);
      const currentMode = stage ? this._getStageMode(stage) : 'auto';
      this._styleStageButtons(stageEl, currentMode);
      // 2) Branche les clicks
      stageEl.querySelectorAll('.ap-stage-mode').forEach(btn => {
        btn.onclick = () => {
          const mode = btn.dataset.mode;
          this._saveStageMode(stageKey, mode);
          this._styleStageButtons(stageEl, mode);
          this._pushStageModeToAPI(stageKey, mode);
        };
      });
    });
  },

  // ------------------------------------------------------------------
  // Sync des modes Auto/Manuel avec le backend (etape 4).
  // Strategie : localStorage = cache instantane (UI fluide), backend =
  // source de verite partagee entre appareils + utilisee par le runner
  // nocturne. Au render : on affiche localStorage puis on fetch l'API en
  // parallele et on met a jour le visuel si different. Au click : update
  // local + UI immediat + fire-and-forget API.
  async _syncStageModesFromAPI() {
    if (!App.api || !App.api.autopilot_get_stage_modes) return;
    let r;
    try { r = await App.api.autopilot_get_stage_modes(); }
    catch (e) { return; }
    if (!r || !r.ok || !r.modes) return;
    // Sauvegarde en local (cache)
    try {
      localStorage.setItem(this._LS_STAGE_MODES, JSON.stringify(r.modes));
    } catch (e) {}
    // Met a jour le visuel des boites deja rendues
    Object.entries(r.modes).forEach(([key, mode]) => {
      const stageEl = document.querySelector(`[data-stage="${key}"]`);
      if (stageEl) this._styleStageButtons(stageEl, mode);
    });
  },

  _pushStageModeToAPI(stage, mode) {
    if (!App.api || !App.api.autopilot_set_stage_mode) return;
    // Fire-and-forget : on n'attend pas la reponse (UI deja a jour)
    try {
      App.api.autopilot_set_stage_mode({ stage, mode }).catch(() => {});
    } catch (e) {}
  },

  // ------------------------------------------------------------------
  // Charge la liste des produits disponibles (table triskell_email_templates)
  // et peuple le <select> du bandeau. Etape 6 du chantier Auto-pilote v2.
  async _loadProducts() {
    if (!App.api || !App.api.autopilot_list_products) return;
    let r;
    try { r = await App.api.autopilot_list_products(); }
    catch (e) { return; }
    if (!r || !r.ok) return;
    const select = document.getElementById('ap-product-select');
    if (!select) return;
    const current = (this.cfg && this.cfg.autopilot_product) || '';
    const opts = [
      `<option value="">— Génération libre (IA from scratch) —</option>`,
    ];
    (r.products || []).forEach(p => {
      const sel = p.key === current ? 'selected' : '';
      opts.push(
        `<option value="${this._esc(p.key)}" ${sel}>${this._esc(p.label || p.key)}</option>`
      );
    });
    select.innerHTML = opts.join('');
    // Toggle visibilite du select audience selon presence d'un produit
    const audSel = document.getElementById('ap-audience-select');
    const updateAudVisibility = () => {
      if (!audSel) return;
      audSel.classList.toggle('hidden', !select.value);
    };
    updateAudVisibility();
    select.addEventListener('change', updateAudVisibility);
  },

  // ------------------------------------------------------------------
  // Compteurs des 5 maillons : appelle autopilot_pulse et met a jour
  // les spans .ap-stage-counter de chaque boite.
  async _refreshPulse() {
    if (!App.api || !App.api.autopilot_pulse) return;
    let r;
    try { r = await App.api.autopilot_pulse({ hours: 24 }); }
    catch (e) { return; }
    if (!r || !r.ok) return;
    this._STAGES.forEach(stage => {
      const stageEl = document.querySelector(`[data-stage="${stage.key}"]`);
      if (!stageEl) return;
      const counter = stageEl.querySelector('.ap-stage-counter');
      if (!counter) return;
      const n = r[stage.key];
      counter.textContent = (typeof n === 'number') ? String(n) : '—';
    });
    // Met aussi a jour le resume textuel sous la chaine
    const sum = document.getElementById('ap-last-run-summary');
    if (sum) {
      const s = r.search ?? 0;
      const w = r.write ?? 0;
      const e = r.send ?? 0;
      sum.textContent = `Dernieres 24h : ${s} prospects trouves · ${w} brouillons rediges · ${e} mails envoyes`;
    }
  },

  _styleStageButtons(stageEl, mode) {
    stageEl.querySelectorAll('.ap-stage-mode').forEach(b => {
      const bMode = b.dataset.mode;
      const isActive = bMode === mode;
      let cls = 'ap-stage-mode px-2.5 py-1 text-[11px] font-semibold rounded-md transition ';
      if (isActive && bMode === 'auto') {
        cls += 'bg-success text-white';
      } else if (isActive && bMode === 'manual') {
        cls += 'bg-warning/20 text-warning';
      } else {
        cls += 'text-text-muted hover:text-text';
      }
      b.className = cls;
    });
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

      ${this._section('Plage horaire d\'envoi',
        'Les mails ne partent qu\'entre ces deux heures (Paris). Hors plage, ' +
        'ils sont mis en brouillon en attendant la prochaine fenêtre.',
        `
        <div class="grid grid-cols-2 gap-3">
          ${this._input('Heure de début (0-23)', 'send_hour_start',
            String(c.send_hour_start ?? 8))}
          ${this._input('Heure de fin (1-24)', 'send_hour_end',
            String(c.send_hour_end ?? 19))}
        </div>
        <div class="text-xs text-text-muted mt-2" style="text-wrap: pretty">
          Par défaut : 8h-19h. Pour ne PAS envoyer la nuit même si l'autopilote
          tourne à 3h, garde ces bornes serrées : les mails seront générés mais
          mis en brouillon, et tu pourras les valider le matin.
        </div>
        `)}
    `;
  },

  // ------------------------------------------------------------------
  // Récupère uniquement les champs envoi+IA. On fusionne avec la config
  // existante pour préserver les champs recherche/enrichissement gérés
  // désormais par L'Éclaireur.
  _gather() {
    const v = (k) => {
      const el = document.querySelector(`[data-key="${k}"]`);
      if (!el) return '';
      if (el.type === 'checkbox') return !!el.checked;
      return el.value;
    };
    const numI = (k, d) => {
      const x = parseInt(v(k), 10);
      return Number.isFinite(x) ? x : d;
    };
    return {
      ...(this.cfg || {}),
      enabled: !!v('enabled'),
      mode:    v('mode') || 'validation',
      ai_provider:        v('ai_provider') || 'google',
      ai_model:           v('ai_model') || 'gemini-2.5-flash',
      ai_mega_prompts:    v('ai_mega_prompts_csv').split(',').map(s => s.trim()).filter(Boolean),
      ai_template_brief:  v('ai_template_brief'),
      sender_mon_prenom:  v('sender_mon_prenom'),
      daily_cap:          numI('daily_cap', 40),
      follow_up_days:     numI('follow_up_days', 5),
      // Auto-pilote v2 etape 6 : produit pousse + audience
      nightly_target:     numI('nightly_target', 50),
      autopilot_product:  v('autopilot_product') || '',
      autopilot_audience: v('autopilot_audience') || '',
      // Auto-pilote v2 etape 8 : plage horaire d'envoi (heure Paris)
      send_hour_start:    numI('send_hour_start', 8),
      send_hour_end:      numI('send_hour_end',   19),
      // Auto-pilote v2 : heure de declenchement du run nocturne
      nightly_hour:       numI('nightly_hour', 3),
    };
  },

  async save() {
    if (!App.api) return;
    const config = this._gather();
    const btn = document.getElementById('ap-save');
    btn.disabled = true; btn.textContent = 'Enregistrement…';
    try {
      const r = await App.api.autopilot_save_config({ config });
      if (r && r.ok) {
        this.cfg = config;
        try { localStorage.removeItem(this._LS_DRAFT); } catch (e) {}
      }
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
      const r = await App.api.autopilot_run({ config, stages: ['imap', 'send', 'follow_up'] });
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
