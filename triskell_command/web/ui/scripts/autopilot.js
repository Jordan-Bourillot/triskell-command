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
      desc:   "Pioche dans « Tous les prospects », le fichier global que ces 3 outils alimentent ensemble.",
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

        <!-- Journal technique : replié par défaut, pour debug -->
        <details class="mt-8 card p-0 group">
          <summary class="cursor-pointer px-5 py-3 flex items-center justify-between gap-3
                          hover:bg-bg/40 rounded-2xl">
            <div>
              <div class="font-semibold text-sm">Détails techniques du run</div>
              <div class="text-xs text-text-muted mt-0.5" style="text-wrap: pretty">
                Journal brut avec timestamps — utile pour comprendre un bug.
              </div>
            </div>
            <svg class="w-5 h-5 text-text-muted transition-transform group-open:rotate-180"
                 fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
              <polyline points="6 9 12 15 18 9"/>
            </svg>
          </summary>
          <div class="px-5 pb-5 pt-1">
            <div id="ap-log" class="font-mono text-xs leading-relaxed
                                    text-text-secondary whitespace-pre-wrap
                                    bg-bg/40 rounded-xl p-3
                                    min-h-[120px] max-h-[420px] overflow-y-auto">
              (en attente d'un run…)
            </div>
            <div id="ap-stats" class="mt-4 hidden"></div>
          </div>
        </details>
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

    // Migration des anciens defauts Gemini -> Claude.
    // Si la config porte EXACTEMENT les anciennes valeurs par defaut
    // (google + gemini-2.5-flash), on bascule sur Claude et on sauvegarde
    // en silence. Toute config personnalisee est conservee telle quelle.
    if (this.cfg.ai_provider === 'google'
        && (this.cfg.ai_model || '').trim() === 'gemini-2.5-flash') {
      this.cfg.ai_provider = 'anthropic';
      this.cfg.ai_model = 'claude-sonnet-4-5';
      try { App.api.autopilot_save_config({ config: this.cfg }); } catch (e) {}
    }

    // Charge les signatures pour les afficher dans l'apercu sous le brief IA
    this.signatures = [];
    try {
      const sr = await App.api.signatures_list();
      if (sr && sr.ok) this.signatures = sr.signatures || [];
    } catch (e) {}

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
              Quel produit l'IA va vendre ?
            </div>
            <select id="ap-product-select" data-key="autopilot_product"
                    class="w-full px-3 py-2 rounded-lg bg-bg border border-border
                           focus:border-accent focus:outline-none text-sm">
              <option value="">— Aucun : l'IA écrit chaque mail de zéro —</option>
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
              Si tu choisis un produit, l'IA piochera dans tes <b>modèles d'emails</b>
              déjà écrits pour ce produit (section « Modèles mails »).
              Sinon, elle invente chaque mail à partir de rien.
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
                       class="w-20 px-3 py-1.5 rounded-md bg-bg border border-border
                              focus:border-accent focus:outline-none text-base font-bold text-center" />
                <span>h (Paris)</span>
              </div>
              <div class="text-xs text-text-muted mt-0.5" style="text-wrap: pretty">
                L'app bosse pendant que tu fais autre chose.
              </div>
            </div>
          </label>
        </div>
      </div>

      <!-- Bandeau d'activité courante : phrase vivante pendant un run -->
      <div id="ap-current-activity"
           class="hidden mb-3 px-4 py-3 rounded-xl bg-accent/5 border border-accent/30
                  flex items-center gap-3">
        <span class="inline-block w-4 h-4 rounded-full border-2 border-accent/30
                     border-t-accent animate-spin flex-shrink-0"></span>
        <span id="ap-current-activity-text"
              class="text-sm text-text flex-1"
              style="text-wrap: pretty">…</span>
      </div>

      <!-- La chaîne des 5 maillons -->
      <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
        ${this._STAGES.map((stage, i) => this._renderStage(stage, i)).join('')}
      </div>

      <!-- Résumé du dernier run / 24h -->
      <div class="mt-4 text-center">
        <span id="ap-last-run-summary" class="text-xs text-text-muted"
              style="text-wrap: pretty">
          En attente de chiffres…
        </span>
      </div>

      <!-- Récap final : apparait quand un run vient de finir -->
      <div id="ap-recap" class="hidden mt-6"></div>
    `;
  },

  _renderStage(stage, index) {
    const mode = this._getStageMode(stage);
    const isAuto = mode === 'auto';
    const isLast = index === this._STAGES.length - 1;
    return `
      <div class="card p-4 relative flex flex-col overflow-hidden transition-colors"
           data-stage="${stage.key}">
        <!-- Bandeau d'état (4px en haut) : change de couleur selon idle/running/done/error -->
        <div class="ap-stage-statusbar absolute top-0 left-0 right-0 h-1
                    bg-border transition-colors"></div>

        <!-- Numéro + titre + petit indicateur d'état (spinner / check / croix) -->
        <div class="flex items-center gap-2 mb-2 mt-1">
          <div class="w-7 h-7 rounded-lg bg-accent/10 text-accent flex items-center
                      justify-center text-sm font-bold flex-shrink-0">
            ${stage.n}
          </div>
          <div class="font-semibold text-base flex-1">${this._esc(stage.title)}</div>
          <span class="ap-stage-state-icon flex-shrink-0"></span>
          ${!isLast ? `
            <svg class="w-4 h-4 text-text-muted hidden lg:block flex-shrink-0"
                 fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
              <polyline points="9 18 15 12 9 6"/>
            </svg>` : ''}
        </div>

        <!-- Sources / outils utilisés -->
        <div class="text-[11px] font-medium text-text-muted mb-2 uppercase tracking-wide"
             style="text-wrap: balance">
          ${this._esc(stage.sources)}
        </div>

        <!-- Description (par défaut) / Message live (pendant un run) -->
        <div class="text-xs text-text-secondary flex-1 ap-stage-desc"
             style="text-wrap: pretty">
          ${this._esc(stage.desc)}
        </div>
        <div class="hidden ap-stage-live mt-1 flex-1">
          <div class="text-xs ap-stage-live-message" style="text-wrap: pretty">…</div>
          <div class="text-[11px] text-text-muted mt-1 ap-stage-live-count"></div>
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

        <!-- Compteur dernier run (24h) -->
        <div class="mt-2 text-center text-text-muted text-[11px]">
          <span class="ap-stage-counter font-mono text-text-secondary">—</span>
          <span> au dernier run</span>
        </div>
      </div>
    `;
  },

  // ------------------------------------------------------------------
  // Visu temps réel : applique l'état d'un stage à sa carte
  // ------------------------------------------------------------------
  _applyStageState(stageKey, info) {
    const el = document.querySelector(`[data-stage="${stageKey}"]`);
    if (!el) return;
    const state    = (info && info.state) || 'idle';
    const message  = (info && info.message) || '';
    const count    = (info && info.count) || 0;

    // Bandeau de couleur en haut de carte
    const bar = el.querySelector('.ap-stage-statusbar');
    if (bar) {
      bar.classList.remove('bg-border', 'bg-accent', 'bg-success', 'bg-danger');
      bar.classList.add({
        idle:    'bg-border',
        running: 'bg-accent',
        done:    'bg-success',
        error:   'bg-danger',
      }[state] || 'bg-border');
    }

    // Petit indicateur à côté du titre (spinner / check / croix)
    const icon = el.querySelector('.ap-stage-state-icon');
    if (icon) {
      if (state === 'running') {
        icon.innerHTML = `<span class="inline-block w-4 h-4 rounded-full
          border-2 border-accent/30 border-t-accent animate-spin"></span>`;
      } else if (state === 'done') {
        icon.innerHTML = `<svg class="w-5 h-5 text-success" fill="none"
          stroke="currentColor" stroke-width="3" viewBox="0 0 24 24">
          <polyline points="20 6 9 17 4 12"/></svg>`;
      } else if (state === 'error') {
        icon.innerHTML = `<svg class="w-5 h-5 text-danger" fill="none"
          stroke="currentColor" stroke-width="3" viewBox="0 0 24 24">
          <line x1="6" y1="6" x2="18" y2="18"/>
          <line x1="6" y1="18" x2="18" y2="6"/></svg>`;
      } else {
        icon.innerHTML = '';
      }
    }

    // Description par défaut OU message live (alterné)
    const desc = el.querySelector('.ap-stage-desc');
    const live = el.querySelector('.ap-stage-live');
    if (state === 'idle') {
      desc?.classList.remove('hidden');
      live?.classList.add('hidden');
    } else {
      desc?.classList.add('hidden');
      live?.classList.remove('hidden');
      const msgEl = el.querySelector('.ap-stage-live-message');
      const cntEl = el.querySelector('.ap-stage-live-count');
      if (msgEl) msgEl.textContent = message || '…';
      if (cntEl) {
        if (state === 'done')      cntEl.textContent = `${count} au total`;
        else if (state === 'running' && count > 0) cntEl.textContent = `${count} déjà traité(s)`;
        else if (state === 'error') cntEl.textContent = 'Erreur';
        else                       cntEl.textContent = '';
      }
    }
  },

  _resetStagesUI() {
    this._STAGES.forEach(s => this._applyStageState(s.key, { state: 'idle' }));
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
        'VALIDATION : l\'app prépare un brouillon, tu valides chaque mail en 1 clic.',
        `
        ${this._select('Mode d\'envoi', 'mode', c.mode || 'validation', [
          ['validation', 'Validation manuelle (recommandé pour démarrer)'],
          ['auto',       'Auto (envoi sans demander)'],
        ])}
        `)}

      ${this._section('Rédaction des mails par l\'IA',
        'Pour chaque prospect, l\'IA reçoit son contexte (nom, ville, secteur, site web) ' +
        'et tes instructions, puis rédige un mail unique. Pas de copier-coller.',
        `
        ${this._select('Service IA', 'ai_provider', c.ai_provider || 'anthropic', [
          ['anthropic', 'Anthropic Claude'],
          ['google',    'Google Gemini'],
          ['openai',    'OpenAI GPT'],
          ['mistral',   'Mistral'],
          ['xai',       'xAI Grok'],
        ])}
        ${this._input('Modèle IA', 'ai_model', c.ai_model || 'claude-sonnet-4-5',
          'ex : claude-sonnet-4-5 (Claude) ou gemini-2.5-flash (gratuit)')}
        ${this._input('Règles d\'écriture (numéros séparés par virgules)',
          'ai_mega_prompts_csv', (c.ai_mega_prompts || ['01']).join(','),
          'ex : 01,06,13')}
        ${this._textarea('Mes instructions à l\'IA', 'ai_template_brief',
          c.ai_template_brief || '', 6)}
        ${this._signaturePreview()}
        ${this._input('Mon prénom (pour la signature)', 'sender_mon_prenom',
          c.sender_mon_prenom || '')}
        `)}

      ${this._section('Règles d\'envoi de tout l\'auto-pilote',
        'Plafonds et fenêtre horaire qui s\'appliquent à toute la chaîne ' +
        '(recherche, rédaction, envoi). Ces réglages sont globaux : ils valent ' +
        'pour chaque run, peu importe l\'heure ou le produit poussé.',
        `
        ${this._input('Plafond total d\'envois sur 24h',
          'daily_cap', String(c.daily_cap ?? 40))}
        ${this._input('Délai avant la relance d\'un prospect sans réponse (en jours)',
          'follow_up_days', String(c.follow_up_days ?? 5))}
        <div class="grid grid-cols-2 gap-3">
          ${this._input('Heure de début (0-23)', 'send_hour_start',
            String(c.send_hour_start ?? 8))}
          ${this._input('Heure de fin (1-24)', 'send_hour_end',
            String(c.send_hour_end ?? 19))}
        </div>
        <div class="text-xs text-text-muted mt-2" style="text-wrap: pretty">
          Par défaut : 8h-19h. Hors plage, les mails sont mis en brouillon —
          tu les valides quand tu reviens.
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
      ai_provider:        v('ai_provider') || 'anthropic',
      ai_model:           v('ai_model') || 'claude-sonnet-4-5',
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
    // Reset visu temps reel : 5 boites en idle, recap cache, activite vide
    this._resetStagesUI();
    const recap = document.getElementById('ap-recap');
    if (recap) { recap.classList.add('hidden'); recap.innerHTML = ''; }
    const activityBox = document.getElementById('ap-current-activity');
    if (activityBox) activityBox.classList.add('hidden');
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

    // Visu temps réel : applique l'état des 5 maillons + l'activité courante
    if (r.stages) {
      Object.entries(r.stages).forEach(([k, info]) => this._applyStageState(k, info));
    }
    const activityBox = document.getElementById('ap-current-activity');
    const activityTxt = document.getElementById('ap-current-activity-text');
    if (activityBox && activityTxt) {
      if (r.running && r.current_activity) {
        activityTxt.textContent = r.current_activity;
        activityBox.classList.remove('hidden');
      } else {
        activityBox.classList.add('hidden');
      }
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
    // Récap final : remplace l'ancien bloc stats par une vue plus riche
    if (r.stats) this._renderRecap(r.stats, r.touched_prospects || [], r.error || '');
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
    // Conserve l'ancien rendu KPI seul (utilisé nulle part en interne mais
    // gardé pour rétrocompat éventuelle).
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
    `;
  },

  // ------------------------------------------------------------------
  // Récap final : grand bloc visuel sous le tableau de commande,
  // remplace l'ancien bloc stats minimaliste.
  // ------------------------------------------------------------------
  _renderRecap(stats, touched, errorTop) {
    const wrap = document.getElementById('ap-recap');
    if (!wrap) return;
    const s = stats || {};
    const sent     = s.drafts_sent     || 0;
    const pending  = s.drafts_pending  || 0;
    const replies  = s.replies_detected || 0;
    const searched = s.searched        || 0;
    const enriched = s.enriched        || 0;
    const errors   = s.errors || [];

    const sentList = touched.filter(p => p.action === 'sent');
    const draftList = touched.filter(p => p.action === 'draft');
    const skippedList = touched.filter(p => p.action === 'skipped');

    const nothingHappened = sent === 0 && pending === 0 && searched === 0
      && enriched === 0 && replies === 0;

    wrap.classList.remove('hidden');
    wrap.innerHTML = `
      <div class="card p-5">
        <div class="flex items-center gap-3 mb-4">
          <div class="w-10 h-10 rounded-full bg-success/15 text-success flex items-center
                      justify-center flex-shrink-0">
            ${errors.length || errorTop ? `
              <svg class="w-6 h-6" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24">
                <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="13"/>
                <line x1="12" y1="16" x2="12" y2="16"/>
              </svg>` : `
              <svg class="w-6 h-6" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24">
                <polyline points="20 6 9 17 4 12"/>
              </svg>`}
          </div>
          <div>
            <div class="font-bold text-lg" style="text-wrap: balance">Voici ce qui s'est passé</div>
            <div class="text-xs text-text-muted mt-0.5" style="text-wrap: pretty">
              ${nothingHappened
                ? 'Rien à faire cette fois — la base est à jour ou les interrupteurs étaient en manuel.'
                : 'Récap du run qui vient de finir.'}
            </div>
          </div>
        </div>

        <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
          ${this._kpi('Prospects ajoutés', searched, searched > 0 ? 'accent' : '')}
          ${this._kpi('Mails envoyés', sent, sent > 0 ? 'success' : '')}
          ${this._kpi('Brouillons posés', pending, pending > 0 ? 'accent' : '')}
          ${this._kpi('Réponses reçues', replies, replies > 0 ? 'success' : '')}
        </div>

        ${sentList.length ? `
          <details class="mt-3 rounded-xl border border-border bg-bg/40 p-3" open>
            <summary class="cursor-pointer text-sm font-semibold text-success">
              ${sentList.length} prospect(s) contacté(s)
            </summary>
            <ul class="mt-2 space-y-1 text-xs text-text-secondary">
              ${sentList.map(p => `
                <li>• <span class="font-medium text-text">${this._esc(p.name)}</span>
                  ${p.reason ? `<span class="text-text-muted"> — ${this._esc(p.reason)}</span>` : ''}
                </li>`).join('')}
            </ul>
          </details>` : ''}

        ${draftList.length ? `
          <details class="mt-2 rounded-xl border border-border bg-bg/40 p-3">
            <summary class="cursor-pointer text-sm font-semibold text-accent">
              ${draftList.length} brouillon(s) à valider
            </summary>
            <ul class="mt-2 space-y-1 text-xs text-text-secondary">
              ${draftList.map(p => `
                <li>• <span class="font-medium text-text">${this._esc(p.name)}</span>
                  ${p.reason ? `<span class="text-text-muted"> — ${this._esc(p.reason)}</span>` : ''}
                </li>`).join('')}
            </ul>
          </details>` : ''}

        ${skippedList.length ? `
          <details class="mt-2 rounded-xl border border-border bg-bg/40 p-3">
            <summary class="cursor-pointer text-sm font-semibold text-text-muted">
              ${skippedList.length} prospect(s) écarté(s)
            </summary>
            <ul class="mt-2 space-y-1 text-xs text-text-secondary">
              ${skippedList.map(p => `
                <li>• <span class="font-medium text-text">${this._esc(p.name)}</span>
                  ${p.reason ? `<span class="text-text-muted"> — ${this._esc(p.reason)}</span>` : ''}
                </li>`).join('')}
            </ul>
          </details>` : ''}

        ${(errors.length || errorTop) ? `
          <details class="mt-3 rounded-xl border border-danger/40 bg-danger/5 p-3" open>
            <summary class="cursor-pointer text-sm font-semibold text-danger">
              ${errors.length + (errorTop ? 1 : 0)} erreur(s) — détail
            </summary>
            <ul class="mt-2 space-y-1 text-xs text-text-secondary">
              ${errorTop ? `<li>• ${this._esc(errorTop)}</li>` : ''}
              ${errors.map(e => `<li>• ${this._esc(e)}</li>`).join('')}
            </ul>
          </details>` : ''}
      </div>
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

  // Apercu de la signature qui sera ajoutee automatiquement a la fin
  // de chaque mail ecrit par l'IA. Si plusieurs signatures sont configurees
  // (une par boite expeditrice), on les liste toutes.
  _signaturePreview() {
    const sigs = (this.signatures || []).filter(s => (s.body_text || '').trim());
    if (!sigs.length) {
      return `
        <div class="rounded-lg border border-dashed border-border bg-bg/40 p-3">
          <div class="text-xs font-medium text-text-secondary mb-1">
            Signature ajoutée automatiquement à la fin du mail
          </div>
          <div class="text-xs text-text-muted">
            Aucune signature configurée. Va dans Réglages → Signatures pour en
            créer une — elle sera collée derrière « Cordialement, {prénom} »
            à chaque envoi.
          </div>
        </div>
      `;
    }
    const blocks = sigs.map(s => {
      const name = this._esc(s.name || 'Ma signature');
      const text = this._esc((s.body_text || '').trim());
      const accs = (s.account_ids || []).length
        ? `Boîte(s) : ${this._esc((s.account_ids || []).join(', '))}`
        : 'Toutes les boîtes (par défaut)';
      return `
        <div class="rounded-md bg-bg/60 border border-border px-3 py-2">
          <div class="flex items-center justify-between mb-1">
            <div class="text-xs font-semibold text-text">${name}</div>
            <div class="text-[10px] text-text-muted">${accs}</div>
          </div>
          <pre class="text-xs text-text-secondary whitespace-pre-wrap font-mono leading-relaxed m-0">${text}</pre>
        </div>
      `;
    }).join('');
    return `
      <div class="rounded-lg border border-dashed border-border bg-bg/40 p-3 space-y-2">
        <div class="text-xs font-medium text-text-secondary">
          Signature ajoutée automatiquement à la fin du mail
          <span class="text-text-muted font-normal">
            (l'IA s'arrête à « Cordialement, {prénom} », ceci est collé derrière)
          </span>
        </div>
        ${blocks}
      </div>
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
