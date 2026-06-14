/* Vue Auto-pilote — chef d'orchestre de la chaîne complète.
 *
 * Tableau de commande : 5 boîtes en chaîne (Cherche → Trie → Rédige → Relit
 * → Envoie). Les 3 derniers maillons (Rédige / Relit / Envoie) ont un
 * interrupteur Auto / Manuel ; les 2 premiers tournent toujours en auto.
 * Le formulaire détaillé (config IA, plafonds, signature) est en bas, replié.
 *
 * Les modes sont sauvegardés en localStorage (cache) ET en backend (source
 * de vérité partagée entre appareils + utilisée par le worker nocturne).
 */

const Autopilot = {
  cfg: null,           // dernière config chargée
  pollTimer: null,     // minuteur du suivi live (App.viewInterval)
  logSeen: 0,          // index dernière ligne lue
  _pollBusy: false,    // anti-chevauchement : une requête de statut à la fois
  _pollFails: 0,       // échecs de suivi d'affilée (on coupe le polling à 8)
  _dirty: false,       // des réglages différés ont changé sans Enregistrer

  _LS_DRAFT: 'autopilot:draft',
  _LS_STAGE_MODES: 'autopilot:stage_modes',

  // Les 5 maillons de la chaîne, dans l'ordre.
  _STAGES: [
    {
      key:    'search',
      n:      '1',
      title:  'Cherche',
      sources:'Fichier « Tous les prospects »',
      desc:   "Pioche uniquement dans tes prospects existants. L'autopilote n'ajoute jamais de nouveaux prospects — utilise Le Chasseur, le Prospecteur Google ou Obélisk pour ça.",
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
      modeHints: {
        auto:   "L'IA rédige un mail pour chaque prospect retenu.",
        manual: "Aucun mail ne sera généré : le passage s'arrêtera après le tri.",
      },
    },
    {
      key:    'review',
      n:      '4',
      title:  'Relit',
      sources:'2è IA · note sur 10',
      desc:   'Une 2è IA vérifie la qualité du mail.',
      defaultMode: 'manual',
      // Interrupteur renommé : Auto = relecture IA ACTIVÉE, Manuel = COUPÉE.
      // L'ancien « Auto / Manuel » laissait croire à une relecture humaine
      // alors que « Manuel » coupe purement la relecture.
      modeSwitchLabel: 'RELECTURE IA',
      modeLabels: { auto: 'Activée', manual: 'Coupée' },
      modeHints: {
        auto:   "Chaque mail est relu par une 2è IA avant l'étape suivante.",
        manual: 'Relecture coupée : les mails passent sans aucun contrôle.',
      },
    },
    {
      key:    'send',
      n:      '5',
      title:  'Envoie',
      sources:'ou met en brouillon si doute',
      desc:   "Envoie pour de vrai, ou met en brouillon si l'IA hésite.",
      defaultMode: 'manual',
      modeHints: {
        auto:   'Les mails partent tout seuls, sans validation.',
        manual: 'Chaque mail est mis en brouillon — rien ne part sans ton OK.',
      },
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

  // Réapplique le brouillon local (champs modifiés mais jamais enregistrés).
  // Renvoie true si un brouillon a été appliqué → le badge « modifications
  // non enregistrées » doit s'allumer (sinon ces valeurs semblent actées).
  _applyDraft() {
    let draft = null;
    try { draft = JSON.parse(localStorage.getItem(this._LS_DRAFT) || 'null'); }
    catch (e) {}
    if (!draft) return false;
    Object.entries(draft).forEach(([k, v]) => {
      const el = document.querySelector(`#ap-form [data-key="${k}"]`);
      if (!el) return;
      if (el.type === 'checkbox') el.checked = !!v;
      else el.value = (v == null ? '' : String(v));
    });
    return true;
  },

  _bindDraftPersist() {
    const root = document.getElementById('ap-form');
    if (!root) return;
    const save = () => { this._saveDraft(); this._setDirty(true); };
    root.querySelectorAll('input, select, textarea').forEach(el => {
      el.addEventListener('input',  save);
      el.addEventListener('change', save);
    });
  },

  // ------------------------------------------------------------------
  // Badge « modifications non enregistrées » : allumé dès qu'un champ
  // différé change (bandeau du haut, adresses expéditrices, formulaire
  // avancé), éteint après un Enregistrer réussi.
  _setDirty(on) {
    this._dirty = !!on;
    ['ap-dirty-badge', 'ap-dirty-badge-bottom'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.classList.toggle('hidden', !this._dirty);
    });
  },

  _bindControlPanelDirty() {
    ['nightly_target', 'enabled', 'nightly_hour'].forEach(k => {
      const el = document.querySelector(`[data-key="${k}"]`);
      if (!el) return;
      el.addEventListener('input',  () => this._setDirty(true));
      el.addEventListener('change', () => this._setDirty(true));
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
        </div>

        <!-- Bandeau "X brouillons à valider" : visible uniquement quand il
             y en a. Sert de raccourci direct vers la page Brouillons. -->
        <div id="ap-drafts-banner"
             class="hidden mb-6 rounded-2xl border border-accent/30 bg-accent/5
                    px-4 py-3 flex items-center justify-between gap-3 flex-wrap">
          <div class="flex items-center gap-3 min-w-0">
            <div class="w-9 h-9 rounded-full bg-accent/15 text-accent flex items-center
                        justify-center flex-shrink-0">
              <svg class="w-5 h-5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                <path d="M4 4h16v16H4z"/><polyline points="4 8 12 13 20 8"/>
              </svg>
            </div>
            <div class="min-w-0">
              <div class="font-semibold text-sm">
                <span id="ap-drafts-banner-count">0</span> brouillon(s) à valider
              </div>
              <div class="text-xs text-text-muted" style="text-wrap: pretty">
                Mails préparés en mode validation, en attente de ton OK.
              </div>
            </div>
          </div>
          <button id="ap-drafts-banner-open" class="btn btn-primary">
            Voir les brouillons →
          </button>
        </div>

        <!-- Bandeau d'erreur de lancement : bien visible en haut, en rouge.
             Avant, l'échec de « Lancer maintenant » finissait enterré dans
             le journal technique replié. -->
        <div id="ap-run-error" role="alert"
             class="hidden mb-4 px-4 py-3 rounded-xl border border-danger/40 bg-danger/10
                    text-sm font-semibold text-danger-text"
             style="text-wrap: pretty"></div>

        <!-- Tableau de commande : réglages + adresses + chaîne des 5 maillons -->
        <div id="ap-control-panel" class="mb-8"></div>

          <!-- Boutons d'action : déplacés ICI (à la fin) après le paramétrage.
               Désactivés tant que la vraie config n'est pas chargée, pour ne
               jamais réenregistrer des valeurs d'usine par accident. -->
          <div class="flex flex-wrap items-center gap-2 sm:gap-3 mb-8">
            <button id="ap-run"  class="btn btn-primary" disabled>
              <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><polygon points="5 3 19 12 5 21 5 3"/></svg>
              Lancer maintenant
            </button>
            <button id="ap-stop"
                    class="btn hidden bg-danger/15 text-danger-text border-danger/40 hover:bg-danger/25">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><rect x="6" y="6" width="12" height="12" rx="1"/></svg>
              Arrêter
            </button>
            <button id="ap-save" class="btn btn-secondary" disabled>Enregistrer les réglages</button>
            <button id="ap-wizard" class="btn btn-secondary" disabled
                    title="L'assistant pose 4 questions (volume, horaires, adresses, validation) et remplit tout proprement">
              🧭 Me guider
            </button>
            <span id="ap-dirty-badge" role="status"
                  class="hidden text-xs font-semibold text-warning-text">
              ● Modifications non enregistrées
            </span>
          </div>

          <!-- Réglages en deux étages repliés (décision Jordan 12/06 — mix) :
               « courants » (plafonds, horaires) et « experts » (IA, règles).
               #ap-form englobe les DEUX : les sélecteurs existants
               (#ap-form [data-key], brouillon local) continuent de tout voir. -->
          <div id="ap-form" class="mb-8 space-y-4"></div>
          <div class="-mt-4 mb-8 flex flex-wrap items-center gap-3">
            <button id="ap-save-bottom" class="btn btn-secondary" disabled>
              Enregistrer les réglages
            </button>
            <span id="ap-dirty-badge-bottom" role="status"
                  class="hidden text-xs font-semibold text-warning-text">
              ● Modifications non enregistrées
            </span>
          </div>

          <!-- Journal technique : replié par défaut, pour debug -->
          <details class="mt-8 card p-0 group">
            <summary class="cursor-pointer px-5 py-3 flex items-center justify-between gap-3
                            hover:bg-bg/40 rounded-2xl">
              <div>
                <div class="font-semibold text-sm">Détails techniques du passage</div>
                <div class="text-xs text-text-muted mt-0.5" style="text-wrap: pretty">
                  Journal brut avec l'heure de chaque action — utile pour comprendre un bug.
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
                (en attente d'un passage…)
              </div>
            </div>
          </details>
      </section>
    `;

    // Rend le tableau de commande tout de suite (depuis localStorage cache)
    document.getElementById('ap-control-panel').innerHTML = this._renderControlPanel();
    this._bindStageToggles();
    // En parallele : sync les modes depuis le backend (source de verite)
    this._syncStageModesFromAPI();
    // (_loadProducts retiré : le dropdown produit n'existe plus.
    // L'auto-pilote détecte les produits actifs du catalogue tout seul.)
    // Charge la liste des comptes mail pour le pool d'adresses expeditrices
    this._loadMailAccountsAndRender();
    // Charge produits actifs + modeles de prospection, et rend la carte
    // "Produits & modeles".
    this._loadActiveProductsAndTemplates();
    // Compteurs : appel asynchrone, met a jour quand l'API repond
    this._refreshPulse();
    // Combien de prospects dans la liste cible (étape 1 "Cherche")
    this._refreshTargetCount();
    // Badge « modifications non enregistrées » sur les champs du bandeau
    this._setDirty(false);
    this._bindControlPanelDirty();

    document.getElementById('ap-save').onclick = () => this.save();
    document.getElementById('ap-run').onclick  = () => this.run();
    document.getElementById('ap-stop').onclick = () => this.stop();
    const saveBottom = document.getElementById('ap-save-bottom');
    if (saveBottom) saveBottom.onclick = () => this.save();
    const wizardBtn = document.getElementById('ap-wizard');
    if (wizardBtn) wizardBtn.onclick = () => this._openWizard();

    // Bandeau "X brouillons à valider" : clic = ouvre la page Brouillons
    const draftsBtn = document.getElementById('ap-drafts-banner-open');
    if (draftsBtn) draftsBtn.onclick = () => App.show('drafts');
    // Au render initial : on affiche le bandeau si necessaire (tache de fond)
    this._refreshDraftsCount();

    if (!App.api) {
      document.getElementById('ap-form').innerHTML = this._previewBanner();
      // Boutons réactivés pour qu'un clic explique le mode aperçu (Toast)
      this._enableActionButtons();
      return;
    }

    // Charge la config
    let r;
    try { r = await App.api.autopilot_get_config(); }
    catch (e) { r = { ok: false, error: String(e) }; }
    if (!r || !r.ok) {
      console.error('[autopilot] chargement config :', (r && r.error) || 'réponse vide');
      document.getElementById('ap-form').innerHTML = `
        <div class="card p-6">
          <div class="font-semibold text-danger-text mb-1">
            Impossible de charger les réglages de l'auto-pilote.
          </div>
          <div class="text-sm text-text-muted mb-3" style="text-wrap: pretty">
            Les boutons restent désactivés pour ne pas écraser tes vrais
            réglages avec des valeurs d'usine. Vérifie la connexion, puis réessaie.
          </div>
          <button class="btn btn-secondary" onclick="App.show('autopilot')">Réessayer</button>
        </div>`;
      return;
    }
    this.cfg = r.config || {};
    // Le bandeau du haut a été rendu AVANT la config (valeurs d'usine) :
    // on le repasse aux vraies valeurs maintenant qu'on les connaît.
    this._applyConfigToControlPanel();
    // La vraie config est là : Lancer / Enregistrer deviennent utilisables.
    this._enableActionButtons();

    // Charge les signatures pour les afficher dans l'apercu sous le brief IA
    this.signatures = [];
    try {
      const sr = await App.api.signatures_list();
      if (sr && sr.ok) this.signatures = sr.signatures || [];
    } catch (e) {}

    this._renderForm();
    // Brouillon local (changements jamais enregistrés) : on le réaffiche
    // ET on allume le badge, sinon il passe pour de la config actée.
    if (this._applyDraft()) this._setDirty(true);
    this._bindDraftPersist();
    // Re-rend le pool d'adresses avec la config maintenant disponible
    // (si les comptes mail ont déjà été chargés en parallèle).
    if (Array.isArray(this.mailAccounts)) {
      this._renderSenderPool();
      this._refreshSenderSummary();
    }

    // Le DOM du log vient d'être réinitialisé : on remet le compteur à 0
    // pour re-récupérer l'historique complet du passage en cours / dernier.
    this.logSeen = 0;
    // Si un passage tourne déjà côté serveur (rechargement de l'écran),
    // reprend le suivi : bouton « Passage en cours… », Stop visible, log.
    this._refreshStatus(true);
  },

  // Patche les 3 champs du bandeau du haut avec la config fraîchement
  // chargée (case « Passage automatique », nombre de prospects, heure).
  // Le bandeau est rendu AVANT l'appel serveur : sans ce patch, il
  // affichait des valeurs d'usine qu'Enregistrer pouvait réécrire —
  // jusqu'à éteindre silencieusement le passage nocturne.
  _applyConfigToControlPanel() {
    const c = this.cfg || {};
    const setField = (key, val) => {
      const el = document.querySelector(`[data-key="${key}"]`);
      if (!el) return;
      if (el.type === 'checkbox') el.checked = !!val;
      else el.value = String(val);
    };
    setField('nightly_target', c.nightly_target ?? 50);
    setField('enabled',        !!c.enabled);
    setField('nightly_hour',   c.nightly_hour ?? 3);
  },

  _enableActionButtons() {
    ['ap-run', 'ap-save', 'ap-save-bottom', 'ap-wizard'].forEach(id => {
      const b = document.getElementById(id);
      if (b) b.disabled = false;
    });
  },

  // ------------------------------------------------------------------
  // Tableau de commande : 5 maillons en chaîne + réglages globaux
  // ------------------------------------------------------------------
  _renderControlPanel() {
    const c = this.cfg || {};
    const nightlyTarget = c.nightly_target ?? 50;
    const enabledNight  = !!c.enabled;
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
                     value="${nightlyTarget}" min="1" max="500" step="1"
                     class="w-24 px-3 py-2 rounded-lg bg-bg border border-border
                            focus:border-accent focus:outline-none text-xl font-bold text-center" />
              <span class="text-sm text-text-secondary" style="text-wrap: balance">
                prospects par passage
              </span>
            </div>
          </label>

          <div class="block">
            <div class="text-xs font-bold uppercase tracking-widest text-text-muted mb-2">
              Quels produits l'IA va vendre ?
            </div>
            <div id="ap-products-summary"
                 class="text-sm text-text px-3 py-2 rounded-lg bg-bg border border-border"
                 style="text-wrap: pretty">
              Chargement…
            </div>
            <div class="text-[11px] text-text-muted mt-1.5 leading-snug"
                 style="text-wrap: pretty">
              Les produits <b>actifs</b> de ton catalogue (juste en dessous). Pour
              ajouter, retirer ou désactiver un produit,
              <button type="button" class="text-accent underline hover:no-underline"
                      onclick="App.show('catalogue')">ouvre le Catalogue</button>.
            </div>
          </div>

          <!-- La case à cocher a son propre label (les textes cliquables
               cochent/décochent) ; le champ heure est SORTI du label pour
               être éditable sans déclencher la case. -->
          <div class="flex items-start gap-3 md:pt-7">
            <input type="checkbox" id="ap-enabled-night" data-key="enabled"
                   ${enabledNight ? 'checked' : ''}
                   class="mt-1 w-5 h-5 accent-accent flex-shrink-0 cursor-pointer" />
            <div class="min-w-0">
              <div class="text-sm font-semibold flex items-center gap-2 flex-wrap"
                   style="text-wrap: balance">
                <label for="ap-enabled-night" class="cursor-pointer">Passage automatique à</label>
                <input type="number" data-key="nightly_hour"
                       value="${nightlyHour}" min="0" max="23" step="1"
                       aria-label="Heure du passage automatique (0 à 23)"
                       class="w-20 px-3 py-1.5 rounded-md bg-bg border border-border
                              focus:border-accent focus:outline-none text-base font-bold text-center" />
                <label for="ap-enabled-night" class="cursor-pointer">h (Paris)</label>
              </div>
              <div class="text-xs text-text-muted mt-0.5" style="text-wrap: pretty">
                L'app bosse pendant que tu fais autre chose.
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Produits & modèles d'emails utilisés par l'autopilote.
           Une ligne par produit actif. Clic = déplie la liste des modèles
           de prospection avec une case à cocher par modèle. -->
      <div class="card p-5 mb-4">
        <div class="flex items-baseline justify-between mb-3 gap-3 flex-wrap">
          <div>
            <div class="text-xs font-bold uppercase tracking-widest text-text-muted mb-1">
              Produits & modèles
            </div>
            <div class="text-xs text-text-muted" style="text-wrap: pretty">
              Clique sur un produit pour choisir les modèles d'emails que
              l'autopilote a le droit d'utiliser pour lui. Décoche ceux que
              tu ne veux pas voir partir.
            </div>
          </div>
          <div id="ap-products-counter" class="text-xs text-text-muted whitespace-nowrap"></div>
        </div>
        <div id="ap-products-list" class="space-y-2">
          <div class="text-xs text-text-muted px-3 py-2">Chargement…</div>
        </div>
      </div>

      <!-- Adresses expéditrices : pool multi-comptes avec cap individuel / 24h -->
      <div class="card p-5 mb-4">
        <div class="flex items-baseline justify-between mb-3 gap-3 flex-wrap">
          <div>
            <div class="text-xs font-bold uppercase tracking-widest text-text-muted mb-1">
              Adresses expéditrices
            </div>
            <div class="text-xs text-text-muted" style="text-wrap: pretty">
              Coche les boîtes que l'autopilote a le droit d'utiliser et fixe un plafond
              par boîte sur les dernières 24h. À chaque envoi, l'app tire au hasard parmi
              les boîtes encore disponibles — une adresse qui envoie trop d'un coup finit
              classée en indésirable, répartir protège chacune.
              <b>Montée auto</b> : le plafond du jour démarre bas et grimpe tout seul
              semaine après semaine selon ce que la boîte a vraiment envoyé (et redescend
              en cas de rebonds) — le plafond saisi reste le maximum jamais dépassé.
            </div>
          </div>
          <div id="ap-sender-summary" class="text-xs text-text-muted whitespace-nowrap"></div>
        </div>
        <div id="ap-sender-list" class="space-y-2">
          <div class="text-xs text-text-muted px-3 py-2">Chargement…</div>
        </div>
      </div>

      <!-- Bandeau d'activité courante : phrase vivante pendant un run -->
      <div id="ap-current-activity"
           class="hidden mb-3 px-4 py-3 rounded-xl bg-accent/5 border border-accent/30
                  flex items-center gap-3">
        <span class="inline-block w-4 h-4 rounded-full border-2 border-accent/30
                     border-t-accent animate-spin flex-shrink-0"></span>
        <span id="ap-current-activity-text"
              class="text-sm text-text flex-1" aria-live="polite"
              style="text-wrap: pretty">…</span>
      </div>

      <!-- Barre de progression globale du passage.
           Cachée au repos, apparaît dès que "Lancer maintenant" démarre.
           Le pourcentage est calculé à partir de l'état des 5 maillons. -->
      <div id="ap-progress-wrap" class="hidden mb-4">
        <div class="flex items-baseline justify-between mb-1.5 gap-3 flex-wrap">
          <div class="text-xs font-bold uppercase tracking-widest text-text-muted">
            Avancement du passage
          </div>
          <div class="text-xs text-text-muted">
            <span id="ap-progress-step" class="text-text font-semibold">—</span>
            <span class="mx-1">·</span>
            <span id="ap-progress-pct" class="text-accent font-bold">0%</span>
          </div>
        </div>
        <div class="w-full h-2 rounded-full bg-bg border border-border overflow-hidden">
          <div id="ap-progress-bar"
               class="h-full bg-accent transition-all duration-500 ease-out"
               style="width: 0%"></div>
        </div>
      </div>

      <!-- Les 4 premiers maillons : recherche / tri / redaction / relecture -->
      <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        ${this._STAGES.slice(0, 4).map((stage, i) => this._renderStage(stage, i)).join('')}
      </div>

      <!-- Etape 5 "Envoie" : mise en valeur (grand bloc pleine largeur,
           compteurs detailles, temps estime, barre de progression dediee).
           C'est la seule etape qui touche au monde reel (mails qui partent
           ou pas), donc Jordan veut la voir vraiment clairement. -->
      ${this._renderSendStage(this._STAGES[4])}

      <!-- Résumé du dernier passage -->
      <div class="mt-4 text-center">
        <span id="ap-last-run-summary" class="text-xs text-text-muted"
              style="text-wrap: pretty">
          En attente de chiffres…
        </span>
      </div>

      <!-- Récap final : apparait quand un passage vient de finir -->
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
          ${stage.key === 'search' ? `
            <div id="ap-target-count"
                 class="mt-2 px-2.5 py-1.5 rounded-lg bg-accent/5 border border-accent/20
                        text-[11px] text-text-secondary"
                 style="text-wrap: pretty">
              <span class="text-text-muted">Chargement de la liste cible…</span>
            </div>
          ` : ''}
        </div>
        <div class="hidden ap-stage-live mt-1 flex-1">
          <div class="text-xs ap-stage-live-message" style="text-wrap: pretty">…</div>
          <div class="text-[11px] text-text-muted mt-1 ap-stage-live-count hidden"></div>
        </div>

        <!-- Interrupteur Auto / Manuel : uniquement sur les maillons ou
             l'utilisateur a vraiment un choix (Redige, Relit, Envoie).
             Cherche et Trie tournent toujours en automatique. -->
        ${(stage.key === 'search' || stage.key === 'sort') ? `
          <div class="mt-4 pt-3 border-t border-border text-[11px]
                      text-text-muted tracking-widest font-bold text-center">
            TOUJOURS AUTO
          </div>
        ` : `
          <div class="flex items-center justify-between gap-2 mt-4 pt-3 border-t border-border">
            <span class="text-[11px] font-bold tracking-widest text-text-muted">${this._esc(stage.modeSwitchLabel || 'MODE')}</span>
            <div class="flex gap-0.5 bg-bg rounded-lg p-0.5 border border-border" role="group">
              <button class="ap-stage-mode px-2.5 py-1 text-[11px] font-semibold rounded-md transition"
                      data-mode="auto"
                      data-label="${this._esc((stage.modeLabels && stage.modeLabels.auto) || 'Auto')}">${this._esc((stage.modeLabels && stage.modeLabels.auto) || 'Auto')}</button>
              <button class="ap-stage-mode px-2.5 py-1 text-[11px] font-semibold rounded-md transition"
                      data-mode="manual"
                      data-label="${this._esc((stage.modeLabels && stage.modeLabels.manual) || 'Manuel')}">${this._esc((stage.modeLabels && stage.modeLabels.manual) || 'Manuel')}</button>
            </div>
          </div>
          <!-- Une ligne d'explication selon le mode choisi (mise à jour au clic) -->
          <div class="ap-stage-mode-hint text-[11px] text-text-muted mt-2"
               style="text-wrap: pretty"></div>
          ${stage.key === 'review' ? `
            <!-- Avertissement permanent : relecture coupée + envoi auto armé -->
            <div class="ap-review-warning hidden mt-2 px-2.5 py-1.5 rounded-lg
                        bg-warning/10 border border-warning/40 text-[11px]
                        font-semibold text-warning-text" role="alert"
                 style="text-wrap: pretty">
              ⚠ Des mails peuvent partir sans aucune relecture — si l'IA se trompe (ton, contenu), le mail part quand même
            </div>` : ''}
        `}

        <!-- Compteur du dernier passage : ce que CE maillon a traité lors
             du dernier passage de l'auto-pilote (rempli par _refreshPulse). -->
        <div class="mt-2 text-center text-text-muted text-[11px]"
             style="text-wrap: pretty">
          <span class="ap-stage-counter font-mono text-text-secondary">—</span>
          <span class="ap-stage-counter-label"> au dernier passage</span>
        </div>
      </div>
    `;
  },

  // ------------------------------------------------------------------
  // Etape 5 "Envoie" : grand bloc pleine largeur avec compteurs detailles
  // (envoyes / total / restants), barre de progression dediee, temps
  // estime restant, et le compteur du dernier passage. Garde le
  // data-stage="send" pour que _applyStageState() pilote bandeau / icone.
  // ------------------------------------------------------------------
  _renderSendStage(stage) {
    const mode = this._getStageMode(stage);
    return `
      <div class="card p-5 sm:p-6 mt-4 relative overflow-hidden"
           data-stage="${stage.key}" data-send-card>
        <!-- Bandeau d'etat (8px en haut, double epaisseur vs 4px ailleurs) -->
        <div class="ap-stage-statusbar absolute top-0 left-0 right-0 h-2
                    bg-border transition-colors"></div>

        <div class="flex items-start gap-4 mb-4 mt-2">
          <!-- Numero plus gros que sur les 4 autres -->
          <div class="w-12 h-12 rounded-xl bg-accent/10 text-accent flex
                      items-center justify-center text-xl font-bold flex-shrink-0">
            ${stage.n}
          </div>
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-3 flex-wrap">
              <div class="font-bold text-xl sm:text-2xl">${this._esc(stage.title)}</div>
              <span class="ap-stage-state-icon flex-shrink-0"></span>
            </div>
            <div class="text-xs font-medium text-text-muted mt-1 uppercase tracking-wide">
              ${this._esc(stage.sources)}
            </div>
            <!-- Description par defaut OU message live -->
            <div class="text-sm text-text-secondary mt-2 ap-stage-desc"
                 style="text-wrap: pretty">
              ${this._esc(stage.desc)}
            </div>
            <div class="hidden ap-stage-live mt-2">
              <div class="text-sm ap-stage-live-message" style="text-wrap: pretty">…</div>
              <div class="text-xs text-text-muted mt-1 ap-stage-live-count hidden"></div>
            </div>
          </div>
          <!-- Interrupteur Auto / Manuel : LA commande unique du mode
               d'envoi (le réglage en double des Paramètres avancés a été
               supprimé — il pouvait dire l'inverse de l'interrupteur). -->
          <div class="flex flex-col items-end gap-1.5 flex-shrink-0">
            <div class="flex items-center gap-2">
              <span class="text-[11px] font-bold tracking-widest text-text-muted">MODE</span>
              <div class="flex gap-0.5 bg-bg rounded-lg p-0.5 border border-border" role="group">
                <button class="ap-stage-mode px-2.5 py-1 text-[11px] font-semibold rounded-md transition"
                        data-mode="auto" data-label="Auto">Auto</button>
                <button class="ap-stage-mode px-2.5 py-1 text-[11px] font-semibold rounded-md transition"
                        data-mode="manual" data-label="Manuel">Manuel</button>
              </div>
            </div>
          </div>
        </div>

        <!-- Une ligne d'explication de l'effet du mode choisi -->
        <div class="ap-stage-mode-hint text-xs text-text-secondary -mt-2 mb-1 sm:text-right"
             style="text-wrap: pretty"></div>

        <!-- Bloc compteurs detailles : visible pendant et apres un passage.
             Cache au repos (rien a montrer). -->
        <div id="ap-send-counters" class="hidden mt-4 pt-4 border-t border-border">
          <div class="grid grid-cols-2 sm:grid-cols-4 gap-3 sm:gap-4">
            <div class="text-center">
              <div class="text-[11px] font-bold uppercase tracking-widest text-text-muted">Envoyés</div>
              <div class="text-2xl sm:text-3xl font-bold text-success mt-1"
                   id="ap-send-count-sent">0</div>
            </div>
            <div class="text-center">
              <div class="text-[11px] font-bold uppercase tracking-widest text-text-muted">Brouillons</div>
              <div class="text-2xl sm:text-3xl font-bold text-warning mt-1"
                   id="ap-send-count-drafts">0</div>
            </div>
            <div class="text-center">
              <div class="text-[11px] font-bold uppercase tracking-widest text-text-muted">Restants</div>
              <div class="text-2xl sm:text-3xl font-bold text-accent mt-1"
                   id="ap-send-count-remaining">0</div>
            </div>
            <div class="text-center">
              <div class="text-[11px] font-bold uppercase tracking-widest text-text-muted"
                   id="ap-send-count-eta-label">Temps restant</div>
              <div class="text-2xl sm:text-3xl font-bold text-text mt-1"
                   id="ap-send-count-eta">—</div>
            </div>
          </div>
          <!-- Barre de progression dediee a l'etape 5 -->
          <div class="mt-4">
            <div class="flex items-center justify-between text-[11px]
                        text-text-muted mb-1.5 font-medium">
              <span id="ap-send-progress-label">0 / 0 traites</span>
              <span id="ap-send-progress-pct">0%</span>
            </div>
            <div class="h-2 rounded-full bg-bg overflow-hidden border border-border">
              <div id="ap-send-progress-bar"
                   class="h-full bg-accent transition-all duration-500 ease-out"
                   style="width: 0%"></div>
            </div>
          </div>
        </div>

        <!-- Compteur du dernier passage -->
        <div class="mt-4 text-center text-text-muted text-xs"
             style="text-wrap: pretty">
          <span class="ap-stage-counter font-mono text-text-secondary">—</span>
          <span class="ap-stage-counter-label"> au dernier passage</span>
        </div>
      </div>
    `;
  },

  // Met a jour les compteurs detailles de l'etape 5 a partir des stats du
  // run (transmises par _pollOnce via this._lastStats / this._lastStages).
  // Appele a chaque tick de polling pendant un run, et une fois en fin.
  _updateSendCounters(stats, stages, running) {
    const wrap = document.getElementById('ap-send-counters');
    if (!wrap) return;
    const s  = stats  || {};
    const st = stages || {};
    const sent      = parseInt(s.drafts_sent    || 0, 10);
    const pending   = parseInt(s.drafts_pending || 0, 10);
    // Total prevu = nb de prospects retenus par le tri (etape 2).
    const total = parseInt((st.sort && st.sort.count) || 0, 10)
               || (sent + pending);
    const done = sent + pending;
    const remaining = Math.max(0, total - done);
    const sendActive = st.send && (st.send.state === 'running'
                                  || st.send.state === 'done');
    if (!sendActive && total === 0) {
      wrap.classList.add('hidden');
      return;
    }
    wrap.classList.remove('hidden');

    document.getElementById('ap-send-count-sent').textContent      = String(sent);
    document.getElementById('ap-send-count-drafts').textContent    = String(pending);
    document.getElementById('ap-send-count-remaining').textContent = String(remaining);

    // Temps restant estime : (restants) * (delai entre envois + buffer SMTP).
    // Si pas de delai configure, on prend 8s par mail (envoi SMTP moyen).
    //
    // En mode Envoie=Manuel, on ne fait que poser des brouillons (pas
    // d'envoi SMTP), donc l'estimation basee sur send_delay_seconds n'a
    // pas de sens. On affiche "—" avec un libelle plus parlant.
    const sendStageDef = this._STAGES.find(s => s.key === 'send');
    const sendMode = sendStageDef ? this._getStageMode(sendStageDef) : 'auto';
    const isSendManual = sendMode === 'manual';
    let eta = '—';
    if (remaining > 0 && running && !isSendManual) {
      const delaySec = parseInt(
        (this.cfg && this.cfg.send_delay_seconds) || 0, 10
      ) || 0;
      // Borne basse fiable : delai configure + 8s SMTP, minimum 10s par
      // mail. Sans cette borne, un 1er envoi rapide laisse croire "0 s
      // restant" alors qu'il reste plein de mails a faire.
      const perMailSec = Math.max(10, delaySec + 8);
      const totalSec = remaining * perMailSec;
      eta = this._formatDuration(totalSec);
    } else if (!running && remaining === 0) {
      eta = 'fini';
    } else if (!running) {
      eta = '—';
    }
    document.getElementById('ap-send-count-eta').textContent = eta;
    // Adapte le libelle "Temps restant" en mode manuel (rien n'est envoye,
    // que des brouillons crees a la vitesse de l'IA).
    const etaLabelEl = document.getElementById('ap-send-count-eta-label');
    if (etaLabelEl) {
      etaLabelEl.textContent = isSendManual ? 'Envoi : manuel' : 'Temps restant';
    }

    // Barre de progression dediee
    const pct = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0;
    document.getElementById('ap-send-progress-bar').style.width = pct + '%';
    document.getElementById('ap-send-progress-pct').textContent = pct + '%';
    document.getElementById('ap-send-progress-label').textContent =
      `${done} / ${total} traités`;
  },

  // Formate une duree en secondes en chaine humaine ("2 min 30 s", "45 s").
  // Sous 10 s : "quelques secondes" pour eviter le faux "0 s" trompeur.
  _formatDuration(totalSec) {
    if (totalSec < 10) return 'quelques secondes';
    if (totalSec < 60) return `${Math.round(totalSec)} s`;
    const m = Math.floor(totalSec / 60);
    const s = Math.round(totalSec - m * 60);
    if (s === 0) return `${m} min`;
    return `${m} min ${s} s`;
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

    // Cas spécial étape 5 (Envoie) en mode manuel : si le run a posé des
    // brouillons à valider, on ne veut PAS d'un visuel "fini, tout va bien"
    // (vert + coche) — sinon Jordan croit que les mails sont partis. On
    // bascule sur un visuel "à valider" (orange + horloge).
    const stageDef = this._STAGES.find(s => s.key === stageKey);
    const stageMode = stageDef ? this._getStageMode(stageDef) : 'auto';
    const needsReview = (
      stageKey === 'send' &&
      state === 'done' &&
      stageMode === 'manual' &&
      count > 0 &&
      /brouillon/i.test(message)
    );

    // Bandeau de couleur en haut de carte
    const bar = el.querySelector('.ap-stage-statusbar');
    if (bar) {
      bar.classList.remove('bg-border', 'bg-accent', 'bg-success', 'bg-danger', 'bg-warning');
      let barCls = {
        idle:    'bg-border',
        running: 'bg-accent',
        done:    'bg-success',
        error:   'bg-danger',
      }[state] || 'bg-border';
      if (needsReview) barCls = 'bg-warning';
      bar.classList.add(barCls);
    }

    // Petit indicateur à côté du titre (spinner / check / croix / horloge).
    // Chaque icône porte un aria-label : l'état n'est pas que de la couleur.
    const icon = el.querySelector('.ap-stage-state-icon');
    if (icon) {
      let ariaLabel = '';
      if (state === 'running') {
        icon.innerHTML = `<span class="inline-block w-4 h-4 rounded-full
          border-2 border-accent/30 border-t-accent animate-spin"></span>`;
        ariaLabel = 'Étape en cours';
      } else if (needsReview) {
        // Horloge orange : "à valider", pas "fini".
        icon.innerHTML = `<svg class="w-5 h-5 text-warning" fill="none"
          stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24">
          <circle cx="12" cy="12" r="10"/>
          <polyline points="12 6 12 12 16 14"/></svg>`;
        ariaLabel = 'En attente de ta validation';
      } else if (state === 'done') {
        icon.innerHTML = `<svg class="w-5 h-5 text-success" fill="none"
          stroke="currentColor" stroke-width="3" viewBox="0 0 24 24">
          <polyline points="20 6 9 17 4 12"/></svg>`;
        ariaLabel = 'Étape terminée';
      } else if (state === 'error') {
        icon.innerHTML = `<svg class="w-5 h-5 text-danger" fill="none"
          stroke="currentColor" stroke-width="3" viewBox="0 0 24 24">
          <line x1="6" y1="6" x2="18" y2="18"/>
          <line x1="6" y1="18" x2="18" y2="6"/></svg>`;
        ariaLabel = 'Étape en erreur';
      } else {
        icon.innerHTML = '';
      }
      if (ariaLabel) {
        icon.setAttribute('role', 'img');
        icon.setAttribute('aria-label', ariaLabel);
        icon.setAttribute('title', ariaLabel);
      } else {
        icon.removeAttribute('role');
        icon.removeAttribute('aria-label');
        icon.removeAttribute('title');
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
      // En mode "à valider" on remplace le texte du compteur par un appel
      // à l'action clair, en orange. Sinon : on masque le compteur duplique
      // (le message juste au-dessus contient deja le chiffre, par ex.
      // "2 prospect(s) prets a recevoir un mail").
      if (cntEl) {
        cntEl.classList.remove('text-warning', 'font-semibold');
        cntEl.classList.add('hidden');
        if (needsReview) {
          // On affiche le nb POSE pendant le run par defaut, puis
          // _refreshDraftsCount() viendra patcher avec le nb REEL en
          // attente (un draft valide / supprime depuis la fin du run ne
          // doit plus compter ici, sinon Jordan voit "2 a valider" mais
          // n'en trouve qu'un dans l'onglet Brouillons).
          cntEl.textContent = `${count} brouillon(s) à valider`;
          cntEl.classList.add('text-warning', 'font-semibold', 'js-stage5-pending-label');
          cntEl.classList.remove('hidden');
        } else {
          cntEl.textContent = '';
          cntEl.classList.remove('js-stage5-pending-label');
        }
      }
    }
  },

  _resetStagesUI() {
    this._STAGES.forEach(s => this._applyStageState(s.key, { state: 'idle' }));
  },

  _bindStageToggles() {
    document.querySelectorAll('[data-stage]').forEach(stageEl => {
      const stageKey = stageEl.dataset.stage;
      const stage = this._STAGES.find(s => s.key === stageKey);
      if (!stage) return;
      // 1) Applique le style initial (selon état sauvegardé)
      this._styleStageButtons(stageEl, this._getStageMode(stage));
      // 2) Branche les clics : confirmation pour l'envoi auto, attente de
      //    la réponse serveur, retour arrière visuel + message si échec.
      stageEl.querySelectorAll('.ap-stage-mode').forEach(btn => {
        btn.onclick = async () => {
          const mode = btn.dataset.mode;
          const prev = this._getStageMode(stage);
          if (mode === prev || stageEl.dataset.modeBusy === '1') return;

          // Garde-fou envoi réel : passer « Envoie » en Auto, c'est armer
          // des envois sans validation → confirmation explicite, avec le
          // plan d'envoi CONCRET (volume max, adresses, plage horaire).
          if (stageKey === 'send' && mode === 'auto') {
            const okConfirm = await Dialog.confirm(
              'Les mails partiront tout seuls, sans validation.\n\n'
              + this._sendPlanText() + '\n\n'
              + 'Tu peux repasser en « Manuel » à tout moment.',
              { title: 'Activer l’envoi automatique', danger: true,
                okLabel: 'Oui, envoyer sans validation', cancelLabel: 'Annuler' });
            if (!okConfirm) return;
          }

          stageEl.dataset.modeBusy = '1';
          // UI optimiste, puis on attend la réponse du serveur.
          this._saveStageMode(stageKey, mode);
          this._styleStageButtons(stageEl, mode);
          const saved = await this._pushStageModeToAPI(stageKey, mode);
          if (!saved) {
            // Échec serveur : retour arrière visuel (le message d'erreur
            // est déjà affiché par _pushStageModeToAPI).
            this._saveStageMode(stageKey, prev);
            this._styleStageButtons(stageEl, prev);
          } else if (stageKey === 'send') {
            // L'interrupteur « Envoie » est LA commande du mode d'envoi :
            // on aligne la config du moteur (auto ↔ validation), sinon
            // l'UI peut dire « Auto » alors que tout part en brouillon.
            await this._syncSendModeConfig(mode);
          }
          delete stageEl.dataset.modeBusy;
        };
      });
    });
    this._updateReviewWarning();
  },

  // ------------------------------------------------------------------
  // Sync des modes Auto/Manuel avec le backend (etape 4).
  // Strategie : localStorage = cache instantane (UI fluide), backend =
  // source de verite partagee entre appareils + utilisee par le worker
  // nocturne. Au render : on affiche localStorage puis on fetch l'API en
  // parallele et on met a jour le visuel si different. Au clic : UI
  // optimiste, mais on ATTEND la reponse serveur (rollback si echec).
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
    this._updateReviewWarning();
  },

  // Enregistre le mode d'un maillon côté serveur. Renvoie true/false :
  // l'appelant fait le retour arrière visuel en cas d'échec.
  async _pushStageModeToAPI(stage, mode) {
    if (!App.api || !App.api.autopilot_set_stage_mode) return true; // aperçu : réglage local
    try {
      const r = await App.api.autopilot_set_stage_mode({ stage, mode });
      if (!r || !r.ok) throw new Error((r && r.error) || 'réglage refusé par le serveur');
      return true;
    } catch (e) {
      Toast.friendlyError(e, 'Impossible de changer ce réglage — il a été remis comme avant.');
      return false;
    }
  },

  // L'interrupteur « Envoie » pilote AUSSI le mode du moteur d'envoi
  // (champ `mode` de la config : 'auto' = envoi direct, 'validation' =
  // brouillons). C'était l'origine du double réglage contradictoire.
  async _syncSendModeConfig(stageMode) {
    const wanted = (stageMode === 'auto') ? 'auto' : 'validation';
    if (!this.cfg || !App.api || !App.api.autopilot_save_config) return;
    if (this.cfg.mode === wanted) return;
    const config = { ...this.cfg, mode: wanted };
    try {
      const r = await App.api.autopilot_save_config({ config });
      if (!r || !r.ok) throw new Error((r && r.error) || 'sauvegarde refusée');
      this.cfg = config;
    } catch (e) {
      Toast.friendlyError(e,
        "Le mode d'envoi n'a pas pu être enregistré — clique « Enregistrer les réglages » pour réessayer.");
    }
  },

  // ------------------------------------------------------------------
  // Produits actifs + modèles d'emails de prospection : charge depuis
  // l'API, croise les deux listes et rend la carte interactive. Chaque
  // produit actif devient une ligne dépliable ; chaque modèle de prosp.
  // est une checkbox qui pilote son champ `enabled` en base.
  async _loadActiveProductsAndTemplates() {
    const wrap = document.getElementById('ap-products-list');
    if (!wrap) return;
    if (!App.api || !App.api.catalog_get_full || !App.api.mail_templates_list) {
      wrap.innerHTML = `<div class="text-xs text-text-muted px-3 py-2">
        Liste des produits indisponible.</div>`;
      const summary = document.getElementById('ap-products-summary');
      if (summary) summary.textContent = 'Indisponible';
      return;
    }
    let cat, tpls;
    try {
      [cat, tpls] = await Promise.all([
        App.api.catalog_get_full(),
        App.api.mail_templates_list(),
      ]);
    } catch (e) {
      console.error('[autopilot] chargement catalogue/modèles :', e);
      this._renderProductsLoadError();
      return;
    }
    // Erreur serveur ≠ catalogue vide : sans cette distinction, un échec
    // de chargement s'affichait comme un faux « Aucun produit actif ».
    if (!cat || !cat.ok || !tpls || !tpls.ok) {
      console.error('[autopilot] catalogue/modèles refusés :',
        (cat && cat.error) || '', (tpls && tpls.error) || '');
      this._renderProductsLoadError();
      return;
    }
    const products = cat.products || [];
    const activeProducts = products.filter(p => p && p.is_active !== false);
    const tplProducts = (tpls && tpls.ok && tpls.products) ? tpls.products : {};

    // Pour chaque produit actif : tableau de modeles de prospection
    // (categorie='prospection'). On ignore les transactionnels (mails type
    // "site livre"), ce ne sont pas ceux que l'autopilote utilise.
    this.productsWithTemplates = activeProducts.map(prod => {
      const pid = prod.id;
      const bucket = tplProducts[pid] || { templates: [] };
      const prospection = (bucket.templates || []).filter(t =>
        (t.category || 'transactionnel') === 'prospection'
      );
      return {
        id:        pid,
        label:     prod.label || pid,
        templates: prospection,
      };
    });

    this._renderProductsList();
    this._refreshProductsSummary();
  },

  // État d'erreur de la carte « Produits & modèles » : message clair +
  // bouton Réessayer, et le résumé du bandeau ne reste plus « Chargement… ».
  _renderProductsLoadError() {
    const wrap = document.getElementById('ap-products-list');
    if (wrap) {
      wrap.innerHTML = `
        <div class="text-xs px-3 py-2 rounded-lg bg-danger/5 border border-danger/40"
             style="text-wrap: pretty">
          <span class="text-danger-text font-semibold">
            Impossible de charger le catalogue et les modèles.
          </span>
          <button type="button" id="ap-products-retry"
                  class="ml-2 text-accent underline hover:no-underline">Réessayer</button>
        </div>`;
      const retry = document.getElementById('ap-products-retry');
      if (retry) retry.onclick = () => {
        wrap.innerHTML = `<div class="text-xs text-text-muted px-3 py-2">Chargement…</div>`;
        const summary = document.getElementById('ap-products-summary');
        if (summary) summary.textContent = 'Chargement…';
        this._loadActiveProductsAndTemplates();
      };
    }
    const summary = document.getElementById('ap-products-summary');
    if (summary) {
      summary.innerHTML =
        `<span class="text-danger-text font-semibold">Erreur de chargement</span>`;
    }
  },

  _renderProductsList() {
    const wrap = document.getElementById('ap-products-list');
    if (!wrap) return;
    const items = this.productsWithTemplates || [];
    if (items.length === 0) {
      wrap.innerHTML = `
        <div class="text-xs text-text-muted px-3 py-2 rounded-lg bg-bg border border-border">
          Aucun produit actif dans le catalogue.
          <button type="button" class="text-accent underline hover:no-underline"
                  onclick="App.show('catalogue')">Ouvrir le Catalogue</button>
          pour en activer un.
        </div>`;
      return;
    }
    const rows = items.map(p => this._renderProductRow(p)).join('');
    wrap.innerHTML = rows;
    // Branche les clics de chaque entete (pour ouvrir/fermer)
    wrap.querySelectorAll('[data-ap-product-toggle]').forEach(btn => {
      btn.addEventListener('click', () => {
        const pid = btn.dataset.apProductToggle;
        this._toggleProductPanel(pid);
      });
    });
    // Branche les checkbox de chaque modele
    wrap.querySelectorAll('.ap-tpl-check').forEach(cb => {
      cb.addEventListener('change', () => {
        const pid = cb.dataset.product;
        const key = cb.dataset.tplKey;
        this._setTemplateEnabled(pid, key, cb.checked);
      });
    });
  },

  _renderProductRow(prod) {
    const total   = prod.templates.length;
    const enabled = prod.templates.filter(t => t.enabled !== false).length;
    const hasTpl  = total > 0;
    const warnNone = hasTpl && enabled === 0;
    const tplRows = prod.templates.map(t => {
      const isOn = t.enabled !== false;
      const label = this._esc(t.label || t.key || 'modèle sans nom');
      const subj  = this._esc(t.subject || '');
      const desc  = this._esc(t.description || '');
      const aud   = (t.audience === 'pro') ? 'Pros'
                  : (t.audience === 'creator') ? 'Créateurs' : '';
      return `
        <label class="flex items-start gap-3 p-3 rounded-lg bg-bg border border-border
                       hover:border-accent/40 transition-colors cursor-pointer">
          <input type="checkbox" class="ap-tpl-check mt-1 w-4 h-4 accent-accent flex-shrink-0"
                 ${isOn ? 'checked' : ''}
                 data-product="${this._esc(prod.id)}"
                 data-tpl-key="${this._esc(t.key)}">
          <div class="flex-1 min-w-0">
            <div class="text-sm font-semibold flex items-center gap-2 flex-wrap">
              <span class="truncate">${label}</span>
              ${aud ? `<span class="text-[11px] uppercase tracking-wider
                                    px-1.5 py-0.5 rounded bg-accent/10 text-accent">
                ${aud}</span>` : ''}
            </div>
            ${subj ? `<div class="text-xs text-text-secondary mt-0.5 truncate"
                            style="text-wrap: pretty">
                       <span class="text-text-muted">Sujet :</span> ${subj}
                     </div>` : ''}
            ${desc ? `<div class="text-[11px] text-text-muted mt-0.5"
                            style="text-wrap: pretty">${desc}</div>` : ''}
          </div>
        </label>`;
    }).join('');

    return `
      <div class="rounded-lg bg-bg border border-border overflow-hidden"
           data-ap-product="${this._esc(prod.id)}">
        <button type="button"
                class="w-full flex items-center gap-3 px-3 py-2.5 text-left
                       hover:bg-bg-secondary transition-colors"
                data-ap-product-toggle="${this._esc(prod.id)}">
          <span class="ap-product-chevron flex-shrink-0 text-text-muted transition-transform">
            <svg class="w-4 h-4" fill="none" stroke="currentColor"
                 stroke-width="2.5" viewBox="0 0 24 24">
              <polyline points="9 18 15 12 9 6"/>
            </svg>
          </span>
          <div class="flex-1 min-w-0">
            <div class="text-sm font-semibold truncate">${this._esc(prod.label)}</div>
            <div class="text-xs ${warnNone ? 'text-danger font-semibold' : 'text-text-muted'}">
              ${hasTpl
                ? `<span class="ap-product-counter">${enabled}</span>
                   sur ${total} modèle(s) actif(s)
                   ${warnNone ? ' — l’IA écrira librement' : ''}`
                : '<span>aucun modèle de prospection — l’IA écrira librement</span>'}
            </div>
          </div>
        </button>
        <div class="ap-product-panel hidden border-t border-border p-3 space-y-2">
          ${hasTpl ? tplRows : `
            <div class="text-xs text-text-muted px-3 py-2"
                 style="text-wrap: pretty">
              Ce produit n'a pas encore de modèle d'email de prospection.
              <button type="button" class="text-accent underline hover:no-underline"
                      onclick="App.show('mail_templates')">Ouvrir Modèles d'emails</button>
              pour en créer un.
            </div>`}
        </div>
      </div>`;
  },

  _toggleProductPanel(pid) {
    const root = document.querySelector(`[data-ap-product="${CSS.escape(pid)}"]`);
    if (!root) return;
    const panel = root.querySelector('.ap-product-panel');
    const chev  = root.querySelector('.ap-product-chevron');
    if (!panel) return;
    const opening = panel.classList.contains('hidden');
    panel.classList.toggle('hidden', !opening);
    if (chev) chev.style.transform = opening ? 'rotate(90deg)' : '';
  },

  async _setTemplateEnabled(productId, key, enabled) {
    if (!App.api || !App.api.mail_templates_save) return;
    // Optimistic : on met a jour la memoire locale + l'affichage tout de
    // suite, et on rollback si l'API renvoie une erreur.
    const prod = (this.productsWithTemplates || []).find(p => p.id === productId);
    if (prod) {
      const t = prod.templates.find(x => x.key === key);
      if (t) t.enabled = enabled;
    }
    this._refreshProductSummaryLine(productId);
    this._refreshProductsSummary();
    try {
      const r = await App.api.mail_templates_save({
        product: productId,
        key,
        fields: { enabled },
      });
      if (!r || !r.ok) throw new Error((r && r.error) || 'erreur');
    } catch (e) {
      // Retour arrière + message : avant, la case revenait en silence et
      // on croyait le choix enregistré.
      if (prod) {
        const t = prod.templates.find(x => x.key === key);
        if (t) t.enabled = !enabled;
      }
      this._renderProductsList();
      this._refreshProductsSummary();
      Toast.friendlyError(e,
        "Impossible d'enregistrer ce choix de modèle — la case a été remise comme avant.");
    }
  },

  // Met a jour juste la ligne de compteurs d'un produit (sans tout redessiner)
  _refreshProductSummaryLine(pid) {
    const prod = (this.productsWithTemplates || []).find(p => p.id === pid);
    if (!prod) return;
    const root = document.querySelector(`[data-ap-product="${CSS.escape(pid)}"]`);
    if (!root) return;
    const cnt = root.querySelector('.ap-product-counter');
    if (cnt) {
      const enabled = prod.templates.filter(t => t.enabled !== false).length;
      cnt.textContent = String(enabled);
    }
  },

  _refreshProductsSummary() {
    const items = this.productsWithTemplates || [];
    const nProducts = items.length;
    let totalEnabled = 0, totalAll = 0;
    items.forEach(p => {
      totalAll += p.templates.length;
      totalEnabled += p.templates.filter(t => t.enabled !== false).length;
    });
    const counter = document.getElementById('ap-products-counter');
    if (counter) {
      counter.textContent = nProducts === 0
        ? ''
        : `${nProducts} produit(s) actif(s) · ${totalEnabled} / ${totalAll} modèle(s) cochés`;
    }
    const summary = document.getElementById('ap-products-summary');
    if (summary) {
      if (nProducts === 0) {
        summary.innerHTML =
          `<span class="text-warning font-semibold">Aucun produit actif</span>`;
      } else {
        summary.innerHTML =
          `<b>${nProducts}</b> produit(s) actif(s) · <b>${totalEnabled}</b> modèle(s) cochés`;
      }
    }
  },

  // ------------------------------------------------------------------
  // Adresses expéditrices : charge la liste des comptes mail + rend les
  // checkboxes + cap par compte. À chaque mail, l'app tire au hasard parmi
  // les adresses cochées qui ont encore de la marge sur 24h glissantes.
  async _loadMailAccountsAndRender() {
    if (!App.api || !App.api.mail_accounts_list) {
      const wrap = document.getElementById('ap-sender-list');
      if (wrap) wrap.innerHTML =
        `<div class="text-xs text-text-muted px-3 py-2">Comptes mail indisponibles.</div>`;
      return;
    }
    try {
      const r = await App.api.mail_accounts_list();
      this.mailAccounts = (r && r.ok && Array.isArray(r.accounts)) ? r.accounts : [];
    } catch (e) {
      console.warn('[autopilot] comptes mail :', e);
      this.mailAccounts = [];
    }
    this._renderSenderPool();
    this._refreshSenderSummary();
    this._refreshPoolStatusFromServer();
  },

  _renderSenderPool() {
    const wrap = document.getElementById('ap-sender-list');
    if (!wrap) return;
    const accounts = this.mailAccounts || [];
    if (accounts.length === 0) {
      wrap.innerHTML = `
        <div class="text-xs text-text-muted px-3 py-2 rounded-lg bg-bg border border-border">
          Aucun compte mail configuré.
          <button type="button" class="text-accent underline hover:no-underline"
                  onclick="App.show('config', {tab:'mails'})">Ouvrir les Réglages</button>
          pour ajouter ton compte principal, ou un compte secondaire.
        </div>`;
      return;
    }
    // Map id → réglages déjà sauvegardés dans cfg.autopilot_sender_pool
    const saved = (this.cfg && Array.isArray(this.cfg.autopilot_sender_pool))
                ? this.cfg.autopilot_sender_pool : [];
    const capById = {};
    const rampById = {};
    const rampFloorById = {};
    for (const e of saved) {
      if (e && e.account_id) {
        capById[e.account_id] = parseInt(e.daily_cap, 10) || 0;
        rampById[e.account_id] = !!e.ramp;
        // Plancher de départ sur-mesure ; sinon on retombe sur l'ancien
        // preset (warm=25, sinon 10) pour les configs d'avant ce champ.
        rampFloorById[e.account_id] = parseInt(e.ramp_floor, 10)
          || (e.ramp_start === 'warm' ? 25 : 10);
      }
    }
    // Par défaut (rien de sauvegardé) : on coche "primary" avec un cap doux
    // (= daily_cap global de la config, sinon 30).
    const defaultCap = (this.cfg && parseInt(this.cfg.daily_cap, 10)) || 30;
    const nothingSaved = saved.length === 0;

    const rows = accounts.map(a => {
      const checked = nothingSaved
        ? (a.id === 'primary' || a.is_primary)
        : (capById[a.id] || 0) > 0;
      const cap = capById[a.id] || defaultCap;
      const rampOn = !!rampById[a.id];
      const rampFloor = rampFloorById[a.id] || 10;
      const fromEmail = this._esc(a.from_email || '');
      const fromName = a.from_name ? ` (${this._esc(a.from_name)})` : '';
      const lbl = this._esc(a.label || a.from_email || a.id);
      const aid = this._esc(a.id);
      return `
        <div class="p-3 rounded-lg bg-bg border border-border
                    hover:border-accent/40 transition-colors"
             data-account-id="${aid}">
          <label class="flex items-center gap-3 cursor-pointer">
            <input type="checkbox" class="ap-sp-check w-4 h-4 accent-accent flex-shrink-0"
                   ${checked ? 'checked' : ''}
                   data-account-id="${aid}">
            <div class="flex-1 min-w-0">
              <div class="text-sm font-semibold truncate">${lbl}</div>
              <div class="text-xs text-text-muted truncate">${fromEmail}${fromName}</div>
            </div>
            <div class="flex items-center gap-1.5 flex-shrink-0">
              <input type="number" class="ap-sp-cap w-16 px-2 py-1 rounded-md
                                          border border-border text-right text-sm
                                          focus:border-accent focus:outline-none"
                     style="background: hsl(var(--bg)); color: hsl(var(--text));"
                     min="1" max="1000" value="${cap}"
                     data-account-id="${aid}">
              <span class="text-xs text-text-muted">max / 24h</span>
            </div>
          </label>
          <div class="ap-sp-ramprow flex items-center gap-2 flex-wrap mt-2 pl-7
                      ${checked ? '' : 'opacity-50'}">
            <label class="flex items-center gap-1.5 text-xs cursor-pointer flex-shrink-0">
              <input type="checkbox" class="ap-sp-ramp w-3.5 h-3.5 accent-accent"
                     ${rampOn ? 'checked' : ''} ${checked ? '' : 'disabled'}
                     data-account-id="${aid}">
              <span>Montée auto</span>
            </label>
            <span class="ap-sp-rampwrap flex items-center gap-1.5 text-xs
                         ${rampOn ? '' : 'hidden'}">
              <span class="text-text-muted">démarrer à</span>
              <input type="number" class="ap-sp-rampfloor w-14 px-2 py-1 rounded-md
                                          border border-border text-right
                                          focus:border-accent focus:outline-none"
                     style="background: hsl(var(--bg)); color: hsl(var(--text));"
                     min="1" max="1000" value="${rampFloor}"
                     ${checked ? '' : 'disabled'} data-account-id="${aid}">
              <span class="text-text-muted">/jour, puis monte tout seul</span>
            </span>
            <span class="ap-sp-rampinfo text-xs text-text-muted" data-account-id="${aid}"></span>
          </div>
        </div>`;
    }).join('');
    wrap.innerHTML = rows;

    // Bind changes : résumé temps réel + badge « non enregistré »
    // (le pool n'est sauvegardé qu'au clic sur Enregistrer).
    wrap.querySelectorAll('.ap-sp-check').forEach(cb => {
      cb.addEventListener('change', () => {
        // Active/désactive la ligne « Montée auto » de cette boîte
        const row = wrap.querySelector(
          `div[data-account-id="${cb.dataset.accountId}"] .ap-sp-ramprow`);
        if (row) {
          row.classList.toggle('opacity-50', !cb.checked);
          row.querySelectorAll('input,select').forEach(el => {
            el.disabled = !cb.checked;
          });
        }
        this._refreshSenderSummary();
        this._setDirty(true);
      });
    });
    wrap.querySelectorAll('.ap-sp-cap').forEach(inp => {
      inp.addEventListener('input', () => {
        this._refreshSenderSummary();
        this._setDirty(true);
      });
    });
    wrap.querySelectorAll('.ap-sp-ramp').forEach(cb => {
      cb.addEventListener('change', () => {
        const row = cb.closest('.ap-sp-ramprow');
        const wrapEl = row && row.querySelector('.ap-sp-rampwrap');
        if (wrapEl) wrapEl.classList.toggle('hidden', !cb.checked);
        this._refreshSenderSummary();
        this._setDirty(true);
      });
    });
    wrap.querySelectorAll('.ap-sp-rampfloor').forEach(inp => {
      inp.addEventListener('input', () => this._setDirty(true));
    });
  },

  // Complète chaque boîte avec son état RÉEL côté serveur : plafond du
  // jour (montée auto appliquée), envois des dernières 24h, frein rebonds.
  async _refreshPoolStatusFromServer() {
    if (!App.api || !App.api.autopilot_sender_pool_status) return;
    let r = null;
    try { r = await App.api.autopilot_sender_pool_status(); }
    catch (e) { return; }
    if (!r || !r.ok || !Array.isArray(r.accounts)) return;
    r.accounts.forEach(acc => {
      const span = document.querySelector(
        `.ap-sp-rampinfo[data-account-id="${acc.account_id}"]`);
      if (!span) return;
      if (acc.ramp) {
        let txt = `→ aujourd'hui : ${acc.daily_cap} max · déjà partis : ${acc.sent_24h}`;
        if (acc.braked) txt += ' · ⚠ frein rebonds actif';
        span.textContent = txt;
        if (acc.braked) span.style.color = 'hsl(var(--warning))';
      } else if ((acc.sent_24h || 0) > 0) {
        span.textContent = `→ déjà partis : ${acc.sent_24h} / ${acc.daily_cap} sur 24h`;
      }
    });
  },

  _refreshSenderSummary() {
    const out = document.getElementById('ap-sender-summary');
    if (!out) return;
    const checks = document.querySelectorAll('.ap-sp-check');
    let nChecked = 0, totalCap = 0, nRamp = 0;
    checks.forEach(cb => {
      if (!cb.checked) return;
      nChecked += 1;
      const capInput = document.querySelector(
        `.ap-sp-cap[data-account-id="${cb.dataset.accountId}"]`
      );
      totalCap += parseInt((capInput && capInput.value) || 0, 10) || 0;
      const rampCb = document.querySelector(
        `.ap-sp-ramp[data-account-id="${cb.dataset.accountId}"]`
      );
      if (rampCb && rampCb.checked) nRamp += 1;
    });
    if (nChecked === 0) {
      out.innerHTML = '<span style="color: hsl(var(--danger));">⚠ Aucune adresse cochée — rien ne pourra être envoyé.</span>';
    } else {
      const rampTxt = nRamp > 0 ? ` · montée auto sur ${nRamp}` : '';
      out.textContent = `${nChecked} adresse(s) · jusqu'à ${totalCap} mails / 24h au total${rampTxt}`;
    }
  },

  _gatherSenderPool() {
    const pool = [];
    document.querySelectorAll('.ap-sp-check').forEach(cb => {
      if (!cb.checked) return;
      const id = cb.dataset.accountId;
      const capInput = document.querySelector(
        `.ap-sp-cap[data-account-id="${id}"]`
      );
      const cap = parseInt((capInput && capInput.value) || 0, 10) || 0;
      if (id && cap > 0) {
        const entry = { account_id: id, daily_cap: cap };
        // Montée auto : le plafond saisi devient un MAX, le plafond du
        // jour est calculé côté serveur sur l'historique réel de la boîte.
        const rampCb = document.querySelector(
          `.ap-sp-ramp[data-account-id="${id}"]`
        );
        if (rampCb && rampCb.checked) {
          entry.ramp = true;
          // Plancher de départ sur-mesure : la rampe démarre là et monte
          // tout seul vers le max (le plafond /24h ci-dessus).
          const floorInput = document.querySelector(
            `.ap-sp-rampfloor[data-account-id="${id}"]`
          );
          const floor = parseInt((floorInput && floorInput.value) || 0, 10) || 10;
          entry.ramp_floor = Math.min(floor, cap);
        }
        pool.push(entry);
      }
    });
    return pool;
  },

  // Décrit en clair ce qui va partir si l'envoi automatique est armé :
  // plafond réel (le plus petit des plafonds), adresses d'envoi cochées,
  // plage horaire. Lu depuis l'état AFFICHÉ (comme _gather) : c'est
  // exactement ce qui sera enregistré puis appliqué. Utilisé par les
  // confirmations « envoi auto » pour annoncer du concret (volume + adresses)
  // au lieu d'un « les mails partiront tout seuls » abstrait.
  _sendPlanText() {
    let pool = this._gatherSenderPool();
    if (!pool.length && !document.querySelector('.ap-sp-check')) {
      // Liste des boîtes pas encore rendue : on retombe sur la config sauvée.
      pool = (this.cfg && Array.isArray(this.cfg.autopilot_sender_pool))
        ? this.cfg.autopilot_sender_pool : [];
    }
    if (!pool.length) {
      return '⚠ Aucune adresse d’envoi n’est cochée : en l’état, rien ne '
        + 'peut partir. Coche au moins une adresse dans '
        + '« Adresses expéditrices ».';
    }
    const byId = {};
    (this.mailAccounts || []).forEach(a => { byId[a.id] = a; });
    const emails = pool
      .map(p => (byId[p.account_id] && byId[p.account_id].from_email) || '')
      .filter(Boolean);
    const readNum = (key, fallback) => {
      const el = document.querySelector(`[data-key="${key}"]`);
      const n = parseInt((el && el.value) || '', 10);
      if (Number.isFinite(n)) return n;
      const c = parseInt(this.cfg && this.cfg[key], 10);
      return Number.isFinite(c) ? c : fallback;
    };
    const globalCap = readNum('daily_cap', 40);
    const poolCap = pool.reduce((s, p) => s + (parseInt(p.daily_cap, 10) || 0), 0);
    const cap = poolCap > 0 ? Math.min(globalCap, poolCap) : globalCap;
    const h1 = readNum('send_hour_start', 8);
    const h2 = readNum('send_hour_end', 19);
    const fromTxt = emails.length === 1
      ? `depuis ${emails[0]}`
      : (emails.length > 1
          ? `depuis ${emails.length} adresses (${emails.join(', ')})`
          : `depuis ${pool.length} adresse(s) cochée(s)`);
    return `Concrètement : jusqu’à ${cap} mail${cap > 1 ? 's' : ''} sur 24 h, `
      + `envoyés entre ${h1} h et ${h2} h, ${fromTxt}, aux prospects de ta `
      + `base « Tous les prospects ».`;
  },

  // Met a jour le bandeau "X brouillons a valider" en haut de la page.
  // Appele au render + apres chaque run de l'autopilote (fin de _refreshStatus).
  //
  // Aligne aussi tous les compteurs de brouillons visibles sur le NB REEL :
  // la case "Brouillons à valider" du récap et le label orange "X
  // brouillon(s) à valider" sous l'étape 5. Sans ça, ces chiffres restent
  // figés sur la valeur du run (n_pending) — et divergent dès qu'un
  // brouillon est validé / rejeté / disparait pour autre raison.
  async _refreshDraftsCount() {
    if (!App.api || !App.api.get_drafts) return;
    let r;
    try { r = await App.api.get_drafts(); } catch (e) { return; }
    if (!r || !r.ok) return;
    const n = (r.rows || []).length;

    // 1) Bandeau "X brouillons a valider" en haut de la page autopilote :
    //    visible uniquement si n > 0.
    const banner = document.getElementById('ap-drafts-banner');
    const bCount = document.getElementById('ap-drafts-banner-count');
    if (banner && bCount) {
      bCount.textContent = String(n);
      banner.classList.toggle('hidden', n === 0);
    }

    // 2) Case "Brouillons à valider" du récap "Voici ce qui s'est passé".
    document.querySelectorAll('.js-drafts-pending-count').forEach(el => {
      el.textContent = String(n);
    });
    // Carte d'ambiance : accent si > 0, neutre sinon.
    document.querySelectorAll('[data-kpi-drafts-pending]').forEach(card => {
      card.classList.toggle('accent-accent', n > 0);
    });

    // 3) Label orange "X brouillon(s) à valider" sous l'etape 5 "Envoie".
    document.querySelectorAll('.js-stage5-pending-label').forEach(el => {
      el.textContent = `${n} brouillon(s) à valider`;
    });
  },


  // ------------------------------------------------------------------
  // Compteurs des 5 maillons : appelle autopilot_last_run_counts et met
  // a jour les spans .ap-stage-counter de chaque boite.
  async _refreshPulse() {
    // Compteurs des 5 maillons = ce que l'autopilote a fait à son DERNIER
    // passage. Avant on affichait "X / 24h toutes sources" — chiffres faux
    // et trompeurs sur la page Auto-pilote (incluaient Chasseur, Obélisk,
    // etc. + bugs côté tri/rédige). Maintenant on lit l'état du dernier
    // passage en mémoire (autopilot_last_run_counts).
    if (!App.api || !App.api.autopilot_last_run_counts) return;
    let r;
    try { r = await App.api.autopilot_last_run_counts(); }
    catch (e) { return; }
    if (!r || !r.ok) return;
    const LABEL_LAST_RUN = {
      search: ' trouvés au dernier passage',
      sort:   ' qualifiés au dernier passage',
      write:  ' brouillons rédigés au dernier passage',
      review: ' relus au dernier passage',
      send:   ' envoyés ou mis en brouillon au dernier passage',
    };
    this._STAGES.forEach(stage => {
      const stageEl = document.querySelector(`[data-stage="${stage.key}"]`);
      if (!stageEl) return;
      const counter = stageEl.querySelector('.ap-stage-counter');
      const label   = stageEl.querySelector('.ap-stage-counter-label');
      if (!counter) return;
      const n = r[stage.key];
      // null => "—" : ce maillon n'a pas tourné lors du dernier run
      counter.textContent = (typeof n === 'number') ? String(n) : '—';
      if (label && LABEL_LAST_RUN[stage.key]) {
        label.textContent = LABEL_LAST_RUN[stage.key];
      }
    });
    // Résumé textuel sous la chaîne des 5 cartes
    const sum = document.getElementById('ap-last-run-summary');
    if (sum) {
      if (!r.has_data) {
        sum.textContent =
          "L'autopilote n'a pas encore tourné depuis le dernier redémarrage du serveur.";
      } else {
        const s = r.search ?? 0;
        const w = r.write ?? 0;
        const e = r.send ?? 0;
        const tag = r.running ? '(en cours)' : '(terminé)';
        sum.textContent = `Dernier passage ${tag} : ${s} trouvés · ${w} rédigés · ${e} envoyés ou mis en brouillon.`;
      }
    }
  },

  // ------------------------------------------------------------------
  // Compteur "combien de prospects dans la liste cible" — affiché sur
  // la carte étape 1 (Cherche). Source = autopilot_target_count() qui
  // applique les mêmes filtres que le pipeline : status new/qualified
  // + au moins un email.
  async _refreshTargetCount() {
    const slot = document.getElementById('ap-target-count');
    if (!slot) return;
    if (!App.api || !App.api.autopilot_target_count) {
      slot.innerHTML = `<span class="text-text-muted">Compteur indisponible.</span>`;
      return;
    }
    let r;
    try { r = await App.api.autopilot_target_count(); }
    catch (e) {
      console.error('[autopilot] compteur cible :', e);
      slot.innerHTML = `<span class="text-danger-text">Impossible de charger la liste cible.</span>`;
      return;
    }
    if (!r || !r.ok) {
      console.error('[autopilot] compteur cible refusé :', (r && r.error) || 'réponse vide');
      slot.innerHTML = `<span class="text-danger-text">Impossible de charger la liste cible.</span>`;
      return;
    }
    const total = r.eligible_total || 0;
    const pickable = r.pickable || 0;
    const cap = r.nightly_target || 0;
    if (total === 0) {
      slot.innerHTML = `
        <span class="text-warning font-semibold">Liste cible vide.</span>
        <span class="text-text-muted">
          Aucun prospect avec mail dans « Tous les prospects ». Utilise
          <button type="button" class="text-accent underline hover:no-underline"
                  onclick="App.show('chasseur')">Le Chasseur</button>
          ou
          <button type="button" class="text-accent underline hover:no-underline"
                  onclick="App.show('obelisk')">Obélisk</button>
          pour en trouver.
        </span>`;
      return;
    }
    const capLine = (cap > 0 && cap < total)
      ? `<span class="text-text-muted"> · va en piocher </span>
         <span class="text-accent font-bold">${pickable.toLocaleString('fr-FR')}</span>
         <span class="text-text-muted"> à ce passage</span>`
      : `<span class="text-text-muted"> · tout sera traité à ce passage</span>`;
    slot.innerHTML = `
      <span class="text-text font-bold">${total.toLocaleString('fr-FR')}</span>
      <span class="text-text-muted"> prospect(s) prêt(s) à recevoir un mail</span>
      ${capLine}`;
  },

  // ------------------------------------------------------------------
  // Barre de progression globale d'un run.
  // Logique : 5 maillons d'égal poids (20% chacun). Pour le maillon en
  // cours, on lit son `count` (= déjà traité) face au total trouvé à
  // l'étape 2 (Trie) pour avoir un % intra-stage. Sinon 50% du stage.
  _updateProgress(stages, running) {
    const wrap = document.getElementById('ap-progress-wrap');
    const bar  = document.getElementById('ap-progress-bar');
    const pct  = document.getElementById('ap-progress-pct');
    const step = document.getElementById('ap-progress-step');
    if (!wrap || !bar || !pct || !step) return;

    // Hors run : on cache la barre (mais on garde la dernière valeur visible
    // un court instant pour montrer le résultat final).
    if (!running) {
      // Si tous les maillons sont idle => pas démarré, on cache.
      const anyActive = stages && Object.values(stages).some(s =>
        s && (s.state === 'running' || s.state === 'done' || s.state === 'error')
      );
      if (!anyActive) {
        wrap.classList.add('hidden');
        return;
      }
      // Sinon : run fini, on laisse la barre affichée à 100%.
      wrap.classList.remove('hidden');
    } else {
      wrap.classList.remove('hidden');
    }

    const order = ['search', 'sort', 'write', 'review', 'send'];
    const labels = {
      search: '1/5 · Cherche',
      sort:   '2/5 · Trie',
      write:  '3/5 · Rédige',
      review: '4/5 · Relit',
      send:   '5/5 · Envoie',
    };
    const totalAt = (stages && stages.sort && stages.sort.count) || 0;
    let done = 0;
    let currentKey = '';
    let currentRatio = 0;
    for (const k of order) {
      const s = (stages && stages[k]) || {};
      if (s.state === 'done') {
        done += 1;
        continue;
      }
      if (s.state === 'running') {
        currentKey = k;
        // % intra-stage si on connaît un total exploitable
        if (totalAt > 0 && k !== 'search' && k !== 'sort') {
          currentRatio = Math.min(1, (s.count || 0) / totalAt);
        } else {
          currentRatio = 0.5;
        }
        break;
      }
      if (s.state === 'error') {
        currentKey = k;
        currentRatio = 0;
        break;
      }
      // idle dans le flow → on s'arrête là
      currentKey = k;
      currentRatio = 0;
      break;
    }
    // Si tout est done, currentKey reste vide → 100%
    const stagesTotal = order.length;
    const ratio = (done + currentRatio) / stagesTotal;
    const pctNum = Math.max(0, Math.min(100, Math.round(ratio * 100)));
    bar.style.width = pctNum + '%';
    pct.textContent = pctNum + '%';
    step.textContent = labels[currentKey] || (done === stagesTotal ? 'Terminé' : '—');
    // Couleur de la barre : verte si run terminé, accent sinon, rouge sur erreur.
    bar.classList.remove('bg-accent', 'bg-success', 'bg-danger');
    const hasError = stages && Object.values(stages).some(s => s && s.state === 'error');
    if (hasError) {
      bar.classList.add('bg-danger');
    } else if (done === stagesTotal && !running) {
      bar.classList.add('bg-success');
    } else {
      bar.classList.add('bg-accent');
    }
  },

  _styleStageButtons(stageEl, mode) {
    stageEl.querySelectorAll('.ap-stage-mode').forEach(b => {
      const bMode = b.dataset.mode;
      const isActive = bMode === mode;
      const label = b.dataset.label || (bMode === 'auto' ? 'Auto' : 'Manuel');
      let cls = 'ap-stage-mode px-2.5 py-1 text-[11px] rounded-md transition ';
      if (isActive && bMode === 'auto') {
        cls += 'bg-success/20 text-success-text font-bold';
      } else if (isActive && bMode === 'manual') {
        cls += 'bg-warning/25 text-warning-text font-bold';
      } else {
        cls += 'font-semibold text-text-muted hover:text-text';
      }
      b.className = cls;
      // L'état actif ne repose pas que sur la couleur : ✓ + aria-pressed.
      b.textContent = (isActive ? '✓ ' : '') + label;
      b.setAttribute('aria-pressed', isActive ? 'true' : 'false');
    });
    this._updateModeHint(stageEl, mode);
    this._updateReviewWarning();
  },

  // Ligne d'explication sous l'interrupteur : dit en clair ce que le mode
  // choisi va faire (ex. Rédige en Manuel = aucun mail généré).
  _updateModeHint(stageEl, mode) {
    const hintEl = stageEl.querySelector('.ap-stage-mode-hint');
    if (!hintEl) return;
    const stage = this._STAGES.find(s => s.key === stageEl.dataset.stage);
    hintEl.textContent = (stage && stage.modeHints && stage.modeHints[mode]) || '';
  },

  // Avertissement permanent sur la carte « Relit » : si la relecture IA
  // est coupée ALORS QUE l'envoi automatique est armé, des mails peuvent
  // partir sans aucun contrôle. Visible tant que la combinaison persiste.
  _updateReviewWarning() {
    const warnEl = document.querySelector('[data-stage="review"] .ap-review-warning');
    if (!warnEl) return;
    const reviewStage = this._STAGES.find(s => s.key === 'review');
    const sendStage   = this._STAGES.find(s => s.key === 'send');
    const reviewOff = reviewStage && this._getStageMode(reviewStage) === 'manual';
    const sendAuto  = sendStage && this._getStageMode(sendStage) === 'auto';
    warnEl.classList.toggle('hidden', !(reviewOff && sendAuto));
  },

  // ------------------------------------------------------------------
  // NB : le réglage « Mode d'envoi » a été retiré d'ici. L'interrupteur
  // du maillon « Envoie » (tableau de commande) est la commande unique :
  // il pilote le champ `mode` de la config (voir _gather/_syncSendModeConfig).
  // Deux étages repliés (décision Jordan 12/06 — mix 3 étages + assistant) :
  // l'essentiel reste visible en haut de l'écran (chaîne, adresses), les
  // réglages COURANTS et EXPERTS vivent ici, chacun dans son tiroir.
  _foldSection(title, sub, inner) {
    return `
      <details class="card p-0 group">
        <summary class="cursor-pointer px-5 py-4 flex items-center justify-between gap-3 hover:bg-bg/40 rounded-2xl">
          <div>
            <div class="font-semibold text-sm">${title}</div>
            <div class="text-xs text-text-muted mt-0.5" style="text-wrap: pretty">${sub}</div>
          </div>
          <svg class="w-5 h-5 text-text-muted transition-transform group-open:rotate-180"
               fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
            <polyline points="6 9 12 15 18 9"/>
          </svg>
        </summary>
        <div class="px-5 pb-5 pt-2">${inner}</div>
      </details>`;
  },

  _renderForm() {
    const c = this.cfg;
    document.getElementById('ap-form').innerHTML = `
      ${this._foldSection('Réglages courants',
        "Plafond quotidien, espacement entre 2 envois, plage horaire — ce qu'on ajuste de temps en temps.",
        `
        ${this._inputNumber("Plafond total d'envois sur 24h",
          'daily_cap', String(c.daily_cap ?? 40), 1, 1000)}
        <div class="text-xs text-text-muted -mt-2 mb-3" style="text-wrap: pretty">
          Limite de sécurité globale. Si tu mets 40, l'auto-pilote n'enverra
          jamais plus de 40 mails dans une fenêtre de 24h, même si « Cherche-moi
          X par passage » (en haut) demande plus, et même si la somme des plafonds
          de tes adresses expéditrices (plus haut) dépasse ce chiffre. <b>C'est
          le plafond qui gagne sur tous les autres.</b>
        </div>
        ${this._inputNumber('Espacement entre 2 envois (en secondes)',
          'send_delay_seconds', String(c.send_delay_seconds ?? 0), 0, 3600)}
        <div class="text-xs text-text-muted -mt-2 mb-3" style="text-wrap: pretty">
          0 = pas d'attente (les mails partent à la chaîne). Mettre 30 à 60
          secondes pour étaler la cadence : une adresse qui envoie en rafale
          finit classée en indésirable par les boîtes mail. S'applique aussi
          au bouton « Tout envoyer » de la page Brouillons.
        </div>
        <div class="grid grid-cols-2 gap-3">
          ${this._inputNumber('Heure de début (0-23)', 'send_hour_start',
            String(c.send_hour_start ?? 8), 0, 23)}
          ${this._inputNumber('Heure de fin (1-24)', 'send_hour_end',
            String(c.send_hour_end ?? 19), 1, 24)}
        </div>
        <div class="text-xs text-text-muted mt-2" style="text-wrap: pretty">
          Par défaut : 8h-19h. Hors plage, les mails sont mis en brouillon —
          tu les valides quand tu reviens.
        </div>
        `)}

      ${this._foldSection('Réglages experts',
        "Service IA, règles d'écriture, instructions, signature — à ouvrir seulement si tu sais pourquoi.",
        `
        ${this._select('Service IA', 'ai_provider', c.ai_provider || 'anthropic', [
          ['anthropic', 'Anthropic Claude'],
          ['google',    'Google Gemini'],
          ['openai',    'OpenAI GPT'],
          ['mistral',   'Mistral'],
          ['xai',       'xAI Grok'],
        ])}
        ${this._input('Modèle IA', 'ai_model', c.ai_model || 'claude-sonnet-4-5',
          'ex : claude-sonnet-4-5 (Claude — recommandé)')}
        ${this._input("Règles d'écriture à appliquer (numéros séparés par virgules)",
          'ai_mega_prompts_csv', (c.ai_mega_prompts || ['01']).join(','),
          'ex : 01,06,13')}
        <div class="text-xs text-text-muted -mt-2 mb-3" style="text-wrap: pretty">
          Liste numérotée des règles de style que l'IA doit suivre (ton, structure,
          longueur, ce qu'il faut éviter). La règle 01 est la base universelle.
          Pour voir la liste complète des règles,
          <button type="button" class="text-accent underline hover:no-underline"
                  onclick="App.show('config', {tab:'ai'})">ouvre les Réglages</button>
          (section Règles d'écriture).
        </div>
        ${this._textarea("Mes instructions à l'IA", 'ai_template_brief',
          c.ai_template_brief || '', 6)}
        ${this._signaturePreview()}
        ${this._input('Mon prénom (pour la signature)', 'sender_mon_prenom',
          c.sender_mon_prenom || '')}
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
    // Le mode d'envoi est dérivé de l'interrupteur du maillon « Envoie »
    // (commande unique) : Auto → envoi direct, Manuel → brouillons.
    const sendStage = this._STAGES.find(s => s.key === 'send');
    const sendAuto = sendStage && this._getStageMode(sendStage) === 'auto';
    return {
      ...(this.cfg || {}),
      enabled: !!v('enabled'),
      mode:    sendAuto ? 'auto' : 'validation',
      ai_provider:        v('ai_provider') || 'anthropic',
      ai_model:           v('ai_model') || 'claude-sonnet-4-5',
      ai_mega_prompts:    v('ai_mega_prompts_csv').split(',').map(s => s.trim()).filter(Boolean),
      ai_template_brief:  v('ai_template_brief'),
      sender_mon_prenom:  v('sender_mon_prenom'),
      daily_cap:          numI('daily_cap', 40),
      send_delay_seconds: numI('send_delay_seconds', 0),
      nightly_target:     numI('nightly_target', 50),
      // Auto-pilote v2 etape 8 : plage horaire d'envoi (heure Paris)
      send_hour_start:    numI('send_hour_start', 8),
      send_hour_end:      numI('send_hour_end',   19),
      // Auto-pilote v2 : heure de declenchement du passage nocturne
      nightly_hour:       numI('nightly_hour', 3),
      // Pool d'adresses expeditrices avec cap individuel / 24h
      autopilot_sender_pool: this._gatherSenderPool(),
    };
  },

  // Bornes des champs numériques. Un champ hors limites = refus VISIBLE
  // (Toast + focus), plus de remplacement silencieux par la valeur d'usine.
  _NUM_RULES: [
    { key: 'nightly_target',     label: 'Prospects par passage',           min: 1, max: 500 },
    { key: 'nightly_hour',       label: 'Heure du passage automatique',    min: 0, max: 23 },
    { key: 'daily_cap',          label: "Plafond total d'envois sur 24h",  min: 1, max: 1000 },
    { key: 'send_delay_seconds', label: 'Espacement entre 2 envois',       min: 0, max: 3600 },
    { key: 'send_hour_start',    label: "Heure de début d'envoi",          min: 0, max: 23 },
    { key: 'send_hour_end',      label: "Heure de fin d'envoi",            min: 1, max: 24 },
  ],

  _validateNumericFields() {
    const problems = [];
    let firstBad = null;
    this._NUM_RULES.forEach(rule => {
      const el = document.querySelector(`[data-key="${rule.key}"]`);
      if (!el) return;
      const raw = String(el.value || '').trim();
      const n = Number(raw);
      const bad = raw === '' || !Number.isInteger(n) || n < rule.min || n > rule.max;
      el.classList.toggle('border-danger', bad);
      if (bad) {
        problems.push(`« ${rule.label} » doit être un nombre entier entre ${rule.min} et ${rule.max}.`);
        if (!firstBad) firstBad = el;
      }
    });
    if (problems.length) {
      const extra = problems.length > 1
        ? ` (+ ${problems.length - 1} autre(s) champ(s) à corriger)` : '';
      Toast.error(problems[0] + extra, 'Réglage invalide');
      if (firstBad) { try { firstBad.focus(); } catch (e) {} }
      return false;
    }
    return true;
  },

  // ---- Assistant « Me guider » (décision Jordan 12/06 — le mix) ----
  // 4 questions (volume, horaires, adresses, validation), puis l'assistant
  // remplit les VRAIS champs du formulaire et enregistre par le circuit
  // normal (save) : aucune écriture parallèle, aucun nouveau chemin de
  // données. L'envoi AUTO garde sa confirmation de sécurité habituelle.
  async _applySendMode(mode) {
    const stage = this._STAGES.find(s => s.key === 'send');
    if (!stage) return true;
    const prev = this._getStageMode(stage);
    if (mode === prev) return true;
    if (mode === 'auto') {
      const ok = await Dialog.confirm(
        'Les mails partiront tout seuls, sans validation.\n\n'
        + this._sendPlanText() + '\n\n'
        + 'Tu peux repasser en « Manuel » à tout moment.',
        { title: 'Activer l’envoi automatique', danger: true,
          okLabel: 'Oui, envoyer sans validation', cancelLabel: 'Rester en validation' });
      if (!ok) return false;
    }
    this._saveStageMode('send', mode);
    const stageEl = document.querySelector('[data-stage="send"]');
    if (stageEl) this._styleStageButtons(stageEl, mode);
    const saved = await this._pushStageModeToAPI('send', mode);
    if (!saved) {
      this._saveStageMode('send', prev);
      if (stageEl) this._styleStageButtons(stageEl, prev);
      return false;
    }
    await this._syncSendModeConfig(mode);
    return true;
  },

  _openWizard() {
    if (!App.api) { Toast.info('Mode aperçu : l’assistant est indisponible ici.'); return; }
    if (!this.cfg) { Toast.info('Les réglages ne sont pas encore chargés — réessaie dans un instant.'); return; }
    const c = this.cfg;
    const pool = Array.isArray(c.autopilot_sender_pool) ? c.autopilot_sender_pool : [];
    const capById = {};
    pool.forEach(e => { if (e && e.account_id) capById[e.account_id] = parseInt(e.daily_cap, 10) || 0; });
    const accounts = (this.mailAccounts || []).filter(a => a && a.from_email);
    const st = {
      step: 0,
      cap: parseInt(c.daily_cap, 10) || 40,
      h1: Number.isFinite(parseInt(c.send_hour_start, 10)) ? parseInt(c.send_hour_start, 10) : 8,
      h2: Number.isFinite(parseInt(c.send_hour_end, 10)) ? parseInt(c.send_hour_end, 10) : 19,
      accs: accounts.map(a => ({
        id: a.id, email: a.from_email,
        on: pool.length ? (capById[a.id] || 0) > 0 : (a.id === 'primary' || !!a.is_primary),
        cap: capById[a.id] || Math.min(30, parseInt(c.daily_cap, 10) || 30),
      })),
      auto: false, // recommandation : tout passe par tes brouillons
    };

    const overlay = document.createElement('div');
    overlay.className = 'fixed inset-0 z-[120] bg-black/40 flex items-center justify-center p-4';
    document.body.appendChild(overlay);
    const close = () => overlay.remove();

    const esc = (s) => this._esc(String(s == null ? '' : s));
    const stepBody = () => {
      if (st.step === 0) return `
        <p class="text-sm text-text-secondary mb-3" style="text-wrap: pretty">
          Combien de mails l'Auto-pilote a-t-il le droit d'envoyer
          <b>au maximum par 24 h</b>, toutes adresses confondues ?</p>
        <input type="number" min="1" max="1000" value="${st.cap}" data-wz="cap"
               class="w-32 px-3 py-2 rounded-lg bg-bg border border-border text-sm">
        <p class="text-xs text-text-muted mt-2" style="text-wrap: pretty">
          Repère : 20 à 40 par jour pour démarrer en douceur — assez pour
          obtenir des réponses, sans risquer d'être classé indésirable.</p>`;
      if (st.step === 1) return `
        <p class="text-sm text-text-secondary mb-3" style="text-wrap: pretty">
          Entre quelles heures les mails peuvent-ils partir ?
          (Hors plage, ils attendent en brouillon.)</p>
        <div class="flex items-center gap-3">
          <label class="text-sm">De <input type="number" min="0" max="23" value="${st.h1}" data-wz="h1"
                 class="w-20 px-3 py-2 rounded-lg bg-bg border border-border text-sm ml-1"> h</label>
          <label class="text-sm">à <input type="number" min="1" max="24" value="${st.h2}" data-wz="h2"
                 class="w-20 px-3 py-2 rounded-lg bg-bg border border-border text-sm ml-1"> h</label>
        </div>
        <p class="text-xs text-text-muted mt-2">Le classique : 8 h à 19 h — les heures où un pro lit ses mails.</p>`;
      if (st.step === 2) {
        if (!st.accs.length) return `
          <p class="text-sm text-text-secondary" style="text-wrap: pretty">
            Aucune adresse d'envoi configurée pour l'instant. L'assistant peut
            continuer, mais rien ne pourra partir tant qu'un compte mail n'est
            pas branché dans <b>Réglages → Mails</b>.</p>`;
        return `
          <p class="text-sm text-text-secondary mb-3" style="text-wrap: pretty">
            Depuis quelles adresses l'Auto-pilote peut-il envoyer, et combien
            de mails max par adresse sur 24 h ?</p>
          <div class="space-y-2">
            ${st.accs.map((a, i) => `
              <label class="flex items-center gap-3 p-2.5 rounded-lg bg-bg border border-border cursor-pointer">
                <input type="checkbox" class="w-4 h-4 accent-accent" data-wz-acc="${i}" ${a.on ? 'checked' : ''}>
                <span class="text-sm flex-1 truncate">${esc(a.email)}</span>
                <input type="number" min="1" max="1000" value="${a.cap}" data-wz-cap="${i}"
                       class="w-20 px-2 py-1 rounded-md bg-surface border border-border text-right text-sm">
                <span class="text-xs text-text-muted">/ 24h</span>
              </label>`).join('')}
          </div>
          <p class="text-xs text-text-muted mt-2" style="text-wrap: pretty">
            Répartir sur plusieurs adresses protège chacune (une adresse qui
            envoie trop d'un coup finit en indésirable).</p>`;
      }
      // step 3 : mode + récap
      const accOn = st.accs.filter(a => a.on);
      return `
        <p class="text-sm text-text-secondary mb-3" style="text-wrap: pretty">
          Dernière question : qui appuie sur le bouton d'envoi ?</p>
        <div class="space-y-2 mb-4">
          <label class="flex items-start gap-3 p-3 rounded-lg bg-bg border border-border cursor-pointer">
            <input type="radio" name="wz-mode" class="mt-0.5 accent-accent" data-wz-mode="validation" ${st.auto ? '' : 'checked'}>
            <span class="text-sm" style="text-wrap: pretty"><b>Je valide chaque mail</b> (recommandé) —
              l'IA prépare, les mails attendent ton OK dans « Brouillons à valider ».</span>
          </label>
          <label class="flex items-start gap-3 p-3 rounded-lg bg-bg border border-warning/45 cursor-pointer">
            <input type="radio" name="wz-mode" class="mt-0.5 accent-accent" data-wz-mode="auto" ${st.auto ? 'checked' : ''}>
            <span class="text-sm" style="text-wrap: pretty"><b>Envoi automatique</b> — les mails partent
              tout seuls, sans relecture par toi. À réserver à un système déjà rodé.</span>
          </label>
        </div>
        <div class="text-xs text-text-muted px-3 py-2 rounded-lg bg-accent/5 border border-accent/20" style="text-wrap: pretty">
          📋 Récap : jusqu'à <b>${st.cap} mails / 24 h</b>, entre <b>${st.h1} h et ${st.h2} h</b>,
          depuis <b>${accOn.length} adresse${accOn.length > 1 ? 's' : ''}</b>${accOn.length ? ` (${esc(accOn.map(a => a.email).join(', '))})` : ''},
          en mode <b>${st.auto ? 'envoi automatique' : 'validation par toi'}</b>.
        </div>`;
    };

    const readStep = () => {
      overlay.querySelectorAll('[data-wz]').forEach(el => {
        const k = el.dataset.wz;
        const n = parseInt(el.value, 10);
        if (Number.isFinite(n)) st[k] = n;
      });
      overlay.querySelectorAll('[data-wz-acc]').forEach(el => {
        const a = st.accs[parseInt(el.dataset.wzAcc, 10)];
        if (a) a.on = !!el.checked;
      });
      overlay.querySelectorAll('[data-wz-cap]').forEach(el => {
        const a = st.accs[parseInt(el.dataset.wzCap, 10)];
        const n = parseInt(el.value, 10);
        if (a && Number.isFinite(n) && n > 0) a.cap = n;
      });
      const mode = overlay.querySelector('[name="wz-mode"]:checked');
      if (mode) st.auto = mode.dataset.wzMode === 'auto';
    };

    const TITLES = ['Le volume', 'Les horaires', 'Les adresses', 'La validation'];
    const paint = () => {
      overlay.innerHTML = `
        <div class="bg-surface rounded-2xl shadow-lift border border-border w-full max-w-lg p-6">
          <div class="hero-kicker mb-1">ME GUIDER · ÉTAPE ${st.step + 1}/4 — ${TITLES[st.step].toUpperCase()}</div>
          <div class="mt-3">${stepBody()}</div>
          <div class="flex items-center justify-between mt-6">
            <button type="button" class="btn btn-secondary" data-wz-back ${st.step === 0 ? 'disabled' : ''}>← Retour</button>
            <div class="flex items-center gap-2">
              <button type="button" class="btn btn-secondary" data-wz-cancel>Annuler</button>
              <button type="button" class="btn btn-primary" data-wz-next>
                ${st.step === 3 ? '✓ Appliquer ces réglages' : 'Suivant →'}
              </button>
            </div>
          </div>
        </div>`;
      overlay.querySelector('[data-wz-cancel]').onclick = close;
      overlay.onclick = (e) => { if (e.target === overlay) close(); };
      const back = overlay.querySelector('[data-wz-back]');
      if (back) back.onclick = () => { readStep(); st.step = Math.max(0, st.step - 1); paint(); };
      overlay.querySelector('[data-wz-next]').onclick = async () => {
        readStep();
        if (st.step < 3) { st.step += 1; paint(); return; }
        await this._applyWizard(st, close);
      };
    };
    paint();
  },

  async _applyWizard(st, close) {
    // 1. Remplit les vrais champs du formulaire (mêmes data-key que save()).
    const setVal = (key, val) => {
      const el = document.querySelector(`[data-key="${key}"]`);
      if (el) el.value = String(val);
    };
    setVal('daily_cap', st.cap);
    setVal('send_hour_start', st.h1);
    setVal('send_hour_end', st.h2);
    // 2. Coche les adresses du pool (les cases du panneau principal).
    st.accs.forEach(a => {
      const cb = document.querySelector(`.ap-sp-check[data-account-id="${a.id}"]`);
      const cap = document.querySelector(`.ap-sp-cap[data-account-id="${a.id}"]`);
      if (cb) cb.checked = a.on;
      if (cap && a.cap > 0) cap.value = String(a.cap);
    });
    this._refreshSenderSummary();
    this._setDirty(true);
    // 3. Enregistre par le circuit normal, puis règle le mode d'envoi
    //    (avec sa confirmation de sécurité si AUTO).
    close();
    await this.save();
    const okMode = await this._applySendMode(st.auto ? 'auto' : 'manual');
    Toast.success(okMode
      ? '🧭 Réglages appliqués — l’Auto-pilote est prêt.'
      : '🧭 Réglages enregistrés. Le mode d’envoi n’a pas été changé.');
  },

  async save() {
    if (!App.api) {
      Toast.info('Mode aperçu : les réglages ne peuvent pas être enregistrés ici.');
      return;
    }
    if (!this.cfg) return; // config jamais chargée : on n'écrase rien
    if (!this._validateNumericFields()) return;
    const config = this._gather();

    // Garde-fou envoi réel : enregistrer la case « Passage automatique »
    // cochée AVEC l'envoi en Auto, c'est armer des envois sans validation.
    const willAuto = !!config.enabled && config.mode === 'auto';
    const wasAuto  = !!(this.cfg && this.cfg.enabled && this.cfg.mode === 'auto');
    if (willAuto && !wasAuto) {
      const okConfirm = await Dialog.confirm(
        'Le passage automatique est coché AVEC l’envoi en Auto : à l’heure '
        + 'programmée, les mails partiront tout seuls, sans validation.\n\n'
        + this._sendPlanText(),
        { title: 'Activer l’envoi automatique', danger: true,
          okLabel: 'Oui, envoyer sans validation', cancelLabel: 'Annuler' });
      if (!okConfirm) return; // Annuler = rien n'est enregistré
    }

    const btns = ['ap-save', 'ap-save-bottom']
      .map(id => document.getElementById(id)).filter(Boolean);
    btns.forEach(b => { b.disabled = true; b.textContent = 'Enregistrement…'; });
    let okSave = false;
    try {
      const r = await App.api.autopilot_save_config({ config });
      okSave = !!(r && r.ok);
      if (okSave) {
        this.cfg = config;
        try { localStorage.removeItem(this._LS_DRAFT); } catch (e) {}
        this._setDirty(false);
        Toast.success('Réglages enregistrés.');
      } else {
        Toast.friendlyError(new Error((r && r.error) || 'enregistrement refusé'),
          'Impossible d’enregistrer les réglages.');
      }
    } catch (e) {
      Toast.friendlyError(e, 'Impossible d’enregistrer les réglages.');
    }
    btns.forEach(b => {
      b.disabled = false;
      b.textContent = okSave ? 'Enregistré ✓' : 'Enregistrer les réglages';
    });
    if (okSave) {
      // Restaure le libellé COMPLET (avant : il devenait juste « Enregistrer »)
      App.viewTimeout(() => btns.forEach(b => {
        b.textContent = 'Enregistrer les réglages';
      }), 1600);
    }
  },

  async run() {
    if (!App.api) {
      Toast.info('Mode aperçu : impossible de lancer un passage ici.');
      return;
    }
    if (!this.cfg) return; // config jamais chargée : on ne lance rien
    if (!this._validateNumericFields()) return;

    // Confirmation AVANT de lancer : elle précise que les réglages affichés
    // sont aussi enregistrés (le lancement sauve toute la config), et elle
    // devient un garde-fou danger quand l'envoi est en Auto.
    const sendStage = this._STAGES.find(s => s.key === 'send');
    const sendAuto = sendStage && this._getStageMode(sendStage) === 'auto';
    const okConfirm = await Dialog.confirm(
      sendAuto
        ? 'Les mails partiront tout seuls, sans validation.\n\n'
          + this._sendPlanText() + '\n\n'
          + 'Les réglages affichés seront aussi enregistrés.'
        : 'Lancer un passage maintenant ? Les réglages affichés seront aussi '
          + 'enregistrés. L’IA prépare les mails et les pose dans '
          + '« Brouillons à valider » — rien ne part sans toi.',
      sendAuto
        ? { title: 'Lancer avec envoi automatique', danger: true,
            okLabel: 'Oui, lancer et envoyer', cancelLabel: 'Annuler' }
        : { title: 'Lancer un passage', okLabel: 'Lancer', cancelLabel: 'Annuler' });
    if (!okConfirm) return;

    this._hideRunError();
    const config = this._gather();
    const btn = document.getElementById('ap-run');
    btn.disabled = true;
    btn.innerHTML = `<span class="inline-block w-4 h-4 mr-2 rounded-full border-2 border-current border-t-transparent animate-spin"></span>Passage en cours…`;
    // Affiche le bouton "Arrêter" pendant le passage
    const stopBtn = document.getElementById('ap-stop');
    if (stopBtn) { stopBtn.classList.remove('hidden'); stopBtn.disabled = false; }
    document.getElementById('ap-log').textContent = '';
    // Reset visu temps reel : 5 boites en idle, recap cache, activite vide
    this._resetStagesUI();
    const recap = document.getElementById('ap-recap');
    if (recap) { recap.classList.add('hidden'); recap.innerHTML = ''; }
    const activityBox = document.getElementById('ap-current-activity');
    if (activityBox) activityBox.classList.add('hidden');
    // Reset barre de progression : affichée à 0 % et bien visible.
    const wrap = document.getElementById('ap-progress-wrap');
    const bar  = document.getElementById('ap-progress-bar');
    const pct  = document.getElementById('ap-progress-pct');
    const step = document.getElementById('ap-progress-step');
    if (wrap) wrap.classList.remove('hidden');
    if (bar)  { bar.style.width = '0%';
                bar.classList.remove('bg-success', 'bg-danger');
                bar.classList.add('bg-accent'); }
    if (pct)  pct.textContent = '0%';
    if (step) step.textContent = 'Démarrage…';
    this.logSeen = 0;
    try {
      const r = await App.api.autopilot_run({ config });
      if (!r || !r.ok) {
        this._failRunStart((r && r.error) || '');
        return;
      }
      // Le lancement a aussi enregistré la config envoyée.
      this.cfg = config;
      try { localStorage.removeItem(this._LS_DRAFT); } catch (e) {}
      this._setDirty(false);
      this._startPolling();
    } catch (e) {
      console.error('[autopilot] lancement :', e);
      this._failRunStart(String((e && e.message) || e || ''));
    }
  },

  // Échec de « Lancer maintenant » : bandeau d'erreur bien visible en haut
  // + barre « Démarrage… 0% » masquée. Avant : l'erreur finissait enterrée
  // dans le journal technique replié et la barre restait à 0 % pour la vie.
  _failRunStart(rawError) {
    const raw = String(rawError || '');
    let msg = 'Le lancement a échoué. Réessaie dans un instant.';
    if (/d[ée]j[àa] en cours|already/i.test(raw)) {
      msg = 'Le passage automatique est déjà en cours — attends la fin avant d’en relancer un.';
    } else if (/attends la fin|nocturne/i.test(raw)) {
      msg = 'Le passage nocturne est en cours — attends la fin avant d’en relancer un.';
    }
    if (raw) {
      this._appendLog('✗ ' + raw);
      console.error('[autopilot] lancement refusé :', raw);
    }
    this._showRunError(msg);
    const wrap = document.getElementById('ap-progress-wrap');
    if (wrap) wrap.classList.add('hidden');
    this._stopRun();
  },

  _showRunError(message) {
    const box = document.getElementById('ap-run-error');
    if (!box) return;
    box.textContent = '⚠ ' + message;
    box.classList.remove('hidden');
    try { box.scrollIntoView({ behavior: 'smooth', block: 'center' }); } catch (e) {}
  },

  _hideRunError() {
    const box = document.getElementById('ap-run-error');
    if (box) { box.classList.add('hidden'); box.textContent = ''; }
  },

  _startPolling() {
    if (this.pollTimer) clearInterval(this.pollTimer);
    this._pollFails = 0;
    // Minuteur lié à la vue : nettoyé automatiquement au changement d'écran.
    this.pollTimer = App.viewInterval(() => this._refreshStatus(false), 1500);
  },

  async _refreshStatus(silent) {
    if (!App.api) return;
    if (this._pollBusy) return; // anti-chevauchement : une requête à la fois
    this._pollBusy = true;
    let r;
    try { r = await App.api.autopilot_status({ since: this.logSeen }); }
    catch (e) { r = null; }
    finally { this._pollBusy = false; }
    if (!r || !r.ok) {
      // Serveur muet : au bout de ~12 s d'échecs d'affilée, on coupe le
      // polling et on prévient, au lieu de mouliner en silence pour toujours.
      this._pollFails = (this._pollFails || 0) + 1;
      if (this.pollTimer && this._pollFails >= 8) {
        clearInterval(this.pollTimer);
        this.pollTimer = null;
        this._showRunError('Connexion au serveur perdue pendant le passage — recharge l’écran pour reprendre le suivi.');
        this._stopRun();
      }
      return;
    }
    this._pollFails = 0;

    if (r.log && r.log.length) {
      r.log.forEach(line => this._appendLog(line));
      this.logSeen = r.log_len;
    }

    // Visu temps réel : applique l'état des 5 maillons + l'activité courante
    if (r.stages) {
      Object.entries(r.stages).forEach(([k, info]) => this._applyStageState(k, info));
    }
    // Barre de progression globale du run
    this._updateProgress(r.stages || {}, !!r.running);
    // Bloc detaille de l'etape 5 (compteurs envoyes/brouillons/restants
    // + temps estime + barre de progression dediee).
    this._updateSendCounters(r.stats || {}, r.stages || {}, !!r.running);
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
      // Passage en cours (lancé ici OU repris au chargement de l'écran) :
      // on continue à suivre.
      if (!this.pollTimer) this._startPolling();
      // Le bouton Stop doit être visible (cas du rechargement de la page
      // pendant un passage lancé précédemment)
      const stopBtn = document.getElementById('ap-stop');
      if (stopBtn && stopBtn.classList.contains('hidden')) {
        stopBtn.classList.remove('hidden');
      }
      const runBtn = document.getElementById('ap-run');
      if (runBtn && !runBtn.disabled) {
        runBtn.disabled = true;
        runBtn.innerHTML = `<span class="inline-block w-4 h-4 mr-2 rounded-full border-2 border-current border-t-transparent animate-spin"></span>Passage en cours…`;
      }
      // Rafraîchit les compteurs du bas (dernier passage) pendant le tick :
      // ça donne un effet "compteurs qui montent" pendant le passage.
      this._refreshPulse();
      return;
    }
    // Passage terminé : on coupe le polling.
    if (this.pollTimer) {
      clearInterval(this.pollTimer);
      this.pollTimer = null;
    }
    if (!silent) this._stopRun();
    // Récap final : remplace l'ancien bloc stats par une vue plus riche
    if (r.stats) this._renderRecap(r.stats, r.touched_prospects || [], r.error || '', r.stages || {});
    if (r.error) this._appendLog('✗ ' + r.error);
    // Passage terminé : mets à jour la pastille de l'onglet Brouillons
    // + fige les compteurs du bas sur les chiffres finaux.
    this._refreshDraftsCount();
    this._refreshPulse();
  },

  _stopRun() {
    const btn = document.getElementById('ap-run');
    if (!btn) return;
    btn.disabled = false;
    btn.innerHTML = `
      <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><polygon points="5 3 19 12 5 21 5 3"/></svg>
      Lancer maintenant`;
    const stopBtn = document.getElementById('ap-stop');
    if (stopBtn) {
      stopBtn.classList.add('hidden');
      stopBtn.disabled = false;
      stopBtn.innerHTML = `
        <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><rect x="6" y="6" width="12" height="12" rx="1"/></svg>
        Arrêter`;
    }
  },

  // Bouton Arrêter : demande au backend de stopper le passage en cours.
  async stop() {
    if (!App.api) return;
    const stopBtn = document.getElementById('ap-stop');
    if (stopBtn) {
      stopBtn.disabled = true;
      stopBtn.innerHTML = `<span class="inline-block w-4 h-4 mr-2 rounded-full border-2 border-current border-t-transparent animate-spin"></span>Arrêt…`;
    }
    try {
      const r = await App.api.autopilot_stop();
      if (!r || !r.ok) {
        this._appendLog((r && r.error) || 'Arrêt impossible.');
        Toast.friendlyError(new Error((r && r.error) || 'arrêt refusé'),
          'Impossible d’arrêter le passage.');
        if (stopBtn) { stopBtn.disabled = false; stopBtn.innerHTML = `
          <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><rect x="6" y="6" width="12" height="12" rx="1"/></svg>
          Arrêter`; }
      }
      // Sinon : le polling détectera running=false et appellera _stopRun()
    } catch (e) {
      this._appendLog('Erreur d’arrêt : ' + String(e));
      Toast.friendlyError(e, 'Impossible d’arrêter le passage.');
      if (stopBtn) { stopBtn.disabled = false; }
    }
  },

  _appendLog(line) {
    const box = document.getElementById('ap-log');
    if (!box) return;
    // Efface le texte d'attente (comparaison sur le texte épuré : le HTML
    // ajoute des espaces/retours à la ligne autour).
    if (box.textContent.trim() === '(en attente d’un passage…)'
        || box.textContent.trim() === "(en attente d'un passage…)") {
      box.textContent = '';
    }
    box.textContent += line + '\n';
    box.scrollTop = box.scrollHeight;
  },

  // ------------------------------------------------------------------
  // Récap final : grand bloc visuel sous le tableau de commande,
  // remplace l'ancien bloc stats minimaliste.
  // ------------------------------------------------------------------
  _renderRecap(stats, touched, errorTop, stages) {
    const wrap = document.getElementById('ap-recap');
    if (!wrap) return;
    const s = stats || {};
    const st = stages || {};
    const sent     = s.drafts_sent     || 0;
    const pending  = s.drafts_pending  || 0;
    // "Prospects ciblés" = prospects retenus par le tri pour ce run. Le
    // champ `searched` du backend ne compte que les NOUVEAUX prospects
    // créés (et l'autopilote n'en crée jamais — il pioche dans les
    // existants), donc on lit le count remonté par l'étape "Trie" et
    // on retombe en dernier ressort sur sent+pending (ceux qu'on a
    // vraiment touchés) puis sur `searched`.
    const sortCount = (st.sort && Number(st.sort.count)) || 0;
    const targeted = sortCount > 0
      ? sortCount
      : (sent + pending) || (s.searched || 0);
    const enriched = s.enriched        || 0;
    const errors   = s.errors || [];

    const sentList = touched.filter(p => p.action === 'sent');
    const draftList = touched.filter(p => p.action === 'draft');
    const skippedList = touched.filter(p => p.action === 'skipped');

    const nothingHappened = sent === 0 && pending === 0 && targeted === 0
      && enriched === 0;

    // Pastille d'humeur du récap : rouge si le passage a planté, orange si
    // des erreurs ponctuelles, verte seulement quand tout s'est bien passé.
    const hasFatal  = !!errorTop;
    const hasErrors = hasFatal || errors.length > 0;
    const toneCls = hasFatal  ? 'bg-danger/15 text-danger'
                  : hasErrors ? 'bg-warning/15 text-warning'
                  : 'bg-success/15 text-success';

    wrap.classList.remove('hidden');
    wrap.innerHTML = `
      <div class="card p-5">
        <div class="flex items-center gap-3 mb-4">
          <div class="w-10 h-10 rounded-full ${toneCls} flex items-center
                      justify-center flex-shrink-0">
            ${hasErrors ? `
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
              ${hasErrors
                ? 'Le passage a rencontré des erreurs — le détail est en bas de ce récap.'
                : nothingHappened
                  ? 'Rien à faire cette fois — la base est à jour ou les interrupteurs étaient en manuel.'
                  : 'Récap du passage qui vient de finir.'}
            </div>
          </div>
        </div>

        <div class="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-4">
          ${this._kpi('Prospects ciblés', targeted, targeted > 0 ? 'accent' : '')}
          ${this._kpi('Mails envoyés', sent, sent > 0 ? 'success' : '')}
          <!-- La case "Brouillons" reflete le nb REEL de brouillons en
               attente dans l'onglet Brouillons, pas le nb fige du run.
               _refreshDraftsCount() patche la classe js-drafts-pending-count
               apres chaque mise a jour pour rester aligne sur la realite
               (un draft valide / rejete / perdu disparait de ce compteur). -->
          <div class="stat-card ${pending > 0 ? 'accent-accent' : ''}"
               data-kpi-drafts-pending>
            <div class="label">Brouillons à valider</div>
            <div class="value js-drafts-pending-count">${pending}</div>
          </div>
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

  // Champ numérique avec bornes (validées aussi par _validateNumericFields
  // avant Enregistrer / Lancer : refus visible si hors limites).
  _inputNumber(label, key, value, min, max) {
    return `
      <label class="block">
        <div class="text-xs font-medium text-text-secondary mb-1.5">${this._esc(label)}</div>
        <input type="number" data-key="${key}" value="${this._esc(value)}"
               min="${min}" max="${max}" step="1"
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
          <div class="text-xs text-text-muted" style="text-wrap: pretty">
            Aucune signature configurée.
            <button type="button" class="text-accent underline hover:no-underline"
                    onclick="App.show('config', {tab:'mails'})">Ouvrir les Réglages</button>
            (section Signatures) pour en créer une — elle sera collée derrière
            « Cordialement, {prénom} » à chaque envoi.
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
            <div class="text-[11px] text-text-muted">${accs}</div>
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

  _previewBanner() {
    return `
      <div class="card p-8 text-center">
        <div class="text-3xl mb-3">⚙️</div>
        <h2 class="text-xl font-semibold mb-2">Mode aperçu</h2>
        <p class="text-text-secondary max-w-md mx-auto" style="text-wrap: pretty">
          Cet aperçu montre l'écran sans connexion au serveur. Ouvre
          l'application complète pour piloter l'auto-pilote.
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
