/* Vue « Compléter les fiches » (L'Éclaireur) — retrouve les emails et
 * téléphones manquants des prospects existants ; peut aussi puiser dans
 * une source (Sirene, Google Maps, Obélisk) pour ajouter des fiches.
 * Pas d'envoi de mails ici — ça reste le job de l'Auto-pilote.
 * Partage la config avec l'Auto-pilote (autopilot_get/save_config) et
 * appelle autopilot_run avec stages=['search','enrich'].
 */

const Eclaireur = {
  cfg: null,
  pollTimer: null,
  logSeen: 0,
  _launching: false,   // verrou anti double-clic sur « Lancer la recherche »

  // Brouillon non sauvegardé persisté en local — permet de retrouver ses
  // modifs en cours même après refresh complet de l'app.
  _LS_DRAFT: 'eclaireur:draft',

  _saveDraft() {
    try {
      const values = {};
      document.querySelectorAll('#ec-form [data-key]').forEach(el => {
        const k = el.dataset.key;
        values[k] = (el.type === 'checkbox') ? !!el.checked : el.value;
      });
      // Horodaté : un vieux brouillon ne doit pas masquer la config serveur.
      localStorage.setItem(this._LS_DRAFT, JSON.stringify({ ts: Date.now(), values }));
    } catch (e) {}
  },

  _applyDraft() {
    let draft = null;
    try { draft = JSON.parse(localStorage.getItem(this._LS_DRAFT) || 'null'); }
    catch (e) {}
    if (!draft) return;
    // Ancien format (sans date) ou brouillon de plus de 7 jours → on jette,
    // pour ne pas réafficher de vieilles modifs par-dessus la vraie config.
    const MAX_AGE_MS = 7 * 24 * 3600 * 1000;
    if (!draft.ts || !draft.values || (Date.now() - draft.ts) > MAX_AGE_MS) {
      try { localStorage.removeItem(this._LS_DRAFT); } catch (e) {}
      return;
    }
    Object.entries(draft.values).forEach(([k, v]) => {
      const el = document.querySelector(`#ec-form [data-key="${k}"]`);
      if (!el) return;
      if (el.type === 'checkbox') el.checked = !!v;
      else el.value = (v == null ? '' : String(v));
    });
    this._bindShowWhen();  // réapplique l'affichage conditionnel selon la source
    // Si le brouillon contient un point de départ GPS, on déplie le bloc avancé.
    const adv = document.getElementById('ec-maps-advanced');
    if (adv) {
      const lat = (document.querySelector('[data-key="maps_lat"]') || {}).value || '';
      const lng = (document.querySelector('[data-key="maps_lng"]') || {}).value || '';
      if (lat || lng) adv.open = true;
    }
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
              <div class="hero-kicker mb-2">COMPLÉTER LES FICHES</div>
              <h1 class="hero-title hero-title--md mb-2 sm:mb-3">Retrouve les infos qui manquent.</h1>
              <p class="hero-subtitle">L’app repasse sur tes prospects et complète leurs fiches : email, téléphone, site web. Aucun mail n’est envoyé ici.</p>
            </div>
            ${typeof Help !== 'undefined' ? Help.button('eclaireur') : ''}
          </div>
          <div class="flex flex-wrap gap-2 sm:gap-3 mt-5 sm:mt-6">
            <button id="ec-save" class="btn btn-secondary">Enregistrer</button>
            <button id="ec-run"  class="btn btn-primary">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M21 21l-4.35-4.35"/><circle cx="11" cy="11" r="8"/></svg>
              Lancer la recherche
            </button>
            <button id="ec-stop" class="btn btn-secondary" hidden>⏹ Arrêter</button>
          </div>
          <div class="text-[11px] text-text-muted mt-2">
            « Enregistrer » garde ces réglages pour les prochaines fois, sans rien lancer.
            « Lancer la recherche » les enregistre aussi, puis démarre tout de suite.
          </div>
          <div class="mt-4 text-[12px] text-text-muted px-3 py-2 rounded-lg bg-accent/5 border border-accent/20" style="text-wrap: pretty">
            🧭 Outil avancé : il complète les fiches DÉJÀ dans ta base. Pour trouver
            de nouveaux prospects et enchaîner l'envoi, passe par
            <button type="button" class="text-accent underline hover:no-underline" onclick="App.show('prospection')">Lancer une prospection</button>.
          </div>
        </div>

        <div id="ec-form" class="space-y-8"></div>

        <div class="mt-10">
          <div class="section-label flex items-center gap-2">Journal de la recherche
            <span id="ec-running-badge" class="hidden text-[11px] font-semibold text-accent normal-case tracking-normal">
              <span class="inline-block w-3 h-3 rounded-full border-2 border-accent/40 border-t-accent animate-spin align-[-2px]"></span>
              recherche en cours — le journal avance tout seul
            </span>
          </div>
          <div id="ec-log" data-empty="1" aria-live="polite"
               class="card p-5 font-mono text-xs leading-relaxed
                      text-text-secondary whitespace-pre-wrap
                      min-h-[180px] max-h-[420px] overflow-y-auto">
            (en attente d’une recherche…)
          </div>
          <div id="ec-stats" class="mt-4 hidden"></div>
        </div>
      </section>
    `;

    document.getElementById('ec-save').onclick = () => this.save();
    document.getElementById('ec-run').onclick  = () => this.run();
    document.getElementById('ec-stop').onclick = () => this.stop();

    if (!App.api) {
      document.getElementById('ec-form').innerHTML = this._previewBanner();
      return;
    }

    let r;
    try { r = await App.api.autopilot_get_config(); }
    catch (e) { r = { ok: false, error: e }; }
    if (!r || !r.ok) {
      console.warn('[eclaireur] chargement config impossible :', r && r.error);
      document.getElementById('ec-form').innerHTML = `
        <div class="card p-6">
          <div class="font-semibold text-danger mb-1">Impossible de charger les réglages.</div>
          <div class="text-sm text-text-secondary mb-4">
            Vérifie ta connexion internet, puis réessaie.
          </div>
          <button id="ec-retry" class="btn btn-secondary">Réessayer</button>
        </div>`;
      const retry = document.getElementById('ec-retry');
      if (retry) retry.onclick = () => this.render(container);
      return;
    }
    this.cfg = r.config || {};
    this._renderForm();
    // Si on a un brouillon local RÉCENT, on l'applique par-dessus la
    // config serveur — sinon Jordan perd ses modifs en cours quand il
    // change de page. (Les brouillons de plus de 7 jours sont ignorés.)
    this._applyDraft();
    this._bindDraftPersist();

    // Le DOM du log vient d'être réinitialisé : on remet le compteur à 0
    // pour re-récupérer l'historique complet de la recherche en cours /
    // de la dernière recherche. Si une recherche tourne déjà, le bouton
    // Lancer passera en « En cours… » et Arrêter apparaîtra.
    this.logSeen = 0;
    this._refreshStatus();
  },

  // ------------------------------------------------------------------
  _renderForm() {
    const c = this.cfg;
    // Tranches d'effectif INSEE → libellés humains. Si la config contient un
    // code hors liste, on l'ajoute tel quel pour ne pas l'écraser en douce.
    const effectifs = [
      ['00', 'Sans salarié'],
      ['01', '1 à 2 salariés'],
      ['02', '3 à 5 salariés'],
      ['03', '6 à 9 salariés'],
      ['11', '10 à 19 salariés'],
      ['12', '20 à 49 salariés'],
      ['21', '50 salariés et plus'],
    ];
    const effVal = c.sirene_effectif || '00';
    if (!effectifs.some(([v]) => v === effVal)) effectifs.push([effVal, `Code ${effVal}`]);
    const hasGps = ((c.maps_lat ?? '') !== '' && c.maps_lat != null)
                || ((c.maps_lng ?? '') !== '' && c.maps_lng != null);
    document.getElementById('ec-form').innerHTML = `
      ${this._section('Où trouver les prospects ?',
        'Sirene = entreprises françaises (gratuit). Google Maps = commerces locaux ' +
        '(clé Google requise). Obélisk = créateurs/vendeurs déjà repérés sur les ' +
        'réseaux (déposés dans la base partagée Triskell). Aucune = pas de recherche auto.',
        `
        ${this._select('Base de données', 'source', c.source || 'sirene', [
          ['sirene',  'Sirene — entreprises françaises (gratuit)'],
          ['maps',    'Google Maps — commerces locaux (clé requise)'],
          ['obelisk', 'Obélisk — créateurs et vendeurs sur les réseaux'],
          ['none',    'Aucune (utilise mes prospects existants)'],
        ])}
        <div data-show-when="source=sirene" class="space-y-3 pt-2">
          ${this._input('Métier (code NAF, optionnel)', 'sirene_naf', c.sirene_naf || '',
            'ex : 43.21A pour électricien',
            { hint: 'Le code NAF est la « catégorie de métier » officielle des entreprises françaises. Laisse vide pour ne pas filtrer par métier.' })}
          ${this._input('Département',          'sirene_departement', c.sirene_departement || '',
            'ex : 35 pour Ille-et-Vilaine')}
          ${this._input('Code postal',          'sirene_code_postal', c.sirene_code_postal || '')}
          ${this._input('Mot-clé dans le nom',  'sirene_query', c.sirene_query || '')}
          ${this._select('Taille de l’entreprise', 'sirene_effectif', effVal, effectifs)}
          ${this._input('Créées depuis (AAAA-MM-JJ)', 'sirene_min_date_creation',
            c.sirene_min_date_creation || '',
            'vide = toutes ; ex : 2024-01-01 = uniquement les récentes')}
        </div>
        <div data-show-when="source=maps" class="space-y-3 pt-2">
          ${this._input('Recherche libre',      'maps_query', c.maps_query || '',
            'ex : « boulangerie Rennes »')}
          ${this._input('Rayon de recherche (mètres)', 'maps_radius_m',
            String(c.maps_radius_m ?? 50000), '', { type: 'number', min: 100 })}
          <details id="ec-maps-advanced" class="pt-1" ${hasGps ? 'open' : ''}>
            <summary class="text-sm font-medium text-text-secondary cursor-pointer">
              Point de départ (avancé)
            </summary>
            <div class="text-[11px] text-text-muted mt-1 mb-2">
              Coordonnées GPS du centre de la zone à fouiller. Dans la plupart
              des cas, laisse vide : la ville indiquée dans la recherche libre suffit.
            </div>
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
              ${this._input('Latitude',  'maps_lat', c.maps_lat ?? '', 'ex : 48.11',
                { inputmode: 'decimal' })}
              ${this._input('Longitude', 'maps_lng', c.maps_lng ?? '', 'ex : -1.68',
                { inputmode: 'decimal' })}
            </div>
          </details>
        </div>
        <div data-show-when="source=obelisk" class="space-y-3 pt-2">
          <div class="text-xs text-text-muted bg-bg/50 border border-border rounded-lg p-3">
            Obélisk a déjà déposé ses créateurs/vendeurs dans la base partagée.
            On les filtre ci-dessous, on complète leurs fiches (email/site), puis ils sont prêts.
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
              String(c.obelisk_min_subscribers || 0), '0 = pas de plancher',
              { type: 'number', min: 0 })}
            ${this._input('Audience maximum (abonnés)', 'obelisk_max_subscribers',
              String(c.obelisk_max_subscribers || 0), '0 = pas de plafond',
              { type: 'number', min: 0 })}
          </div>
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
            ${this._input('Pays (ex. FR)', 'obelisk_country', c.obelisk_country || '',
              'ex : FR — vide = tous')}
            ${this._input('Langue (ex. fr)', 'obelisk_language', c.obelisk_language || '',
              'ex : fr — vide = toutes')}
          </div>
          ${this._toggle('Uniquement ceux avec un email connu',
            'obelisk_only_with_email', !!c.obelisk_only_with_email,
            'Sinon, l’app essaiera de retrouver l’email à partir du site web.')}
          ${this._toggle('Uniquement ceux pas encore contactés',
            'obelisk_only_uncontacted', c.obelisk_only_uncontacted !== false,
            'Évite de recontacter quelqu’un déjà sollicité.')}
          ${this._toggle('Uniquement les profils détectés monétisés',
            'obelisk_monetized_only', !!c.obelisk_monetized_only,
            'Affiliés, sponsors, boutique en ligne… plus probable d’être réceptifs.')}
        </div>
        <div class="pt-2">
          ${this._input('Nombre max de prospects par recherche', 'search_max_results',
            String(c.search_max_results ?? 50), '', { type: 'number', min: 1 })}
        </div>
        `)}

      ${this._section('Recherche d’emails et téléphones',
        'L’app visite le site web de chaque prospect, en extrait email et téléphone, ' +
        'et vérifie que le site correspond bien à l’entreprise.',
        `
        ${this._toggle('Détecter automatiquement le site web quand il est inconnu',
          'enrich_with_footprint', c.enrich_with_footprint !== false,
          'Essaie nom-entreprise.fr, .com, etc.')}
        ${this._toggle('Ne traiter que les prospects sans email connu',
          'enrich_no_emails_only', c.enrich_no_emails_only !== false)}
        ${this._input('Nombre max de fiches à compléter par recherche', 'enrich_max',
          String(c.enrich_max ?? 100), '', { type: 'number', min: 1 })}
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
  // `base` = config serveur FRAÎCHE (rechargée juste avant l'appel) : on ne
  // fusionne nos champs que par-dessus elle, pour ne JAMAIS rétablir une
  // vieille copie des réglages de l'Auto-pilote (interrupteur compris).
  _gather(base) {
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
      ...(base || this.cfg || {}),
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
    const btn = document.getElementById('ec-save');
    btn.disabled = true; btn.textContent = 'Enregistrement…';
    try {
      // ⚠ On repart TOUJOURS de la config serveur la plus fraîche : cet écran
      // ne doit modifier QUE ses champs. Avant, il renvoyait la copie chargée
      // à l'ouverture de la page → il pouvait rétablir un vieil état de
      // l'Auto-pilote (l'éteindre ou le rallumer en douce).
      const cur = await App.api.autopilot_get_config();
      if (!cur || !cur.ok) throw new Error((cur && cur.error) || 'réglages illisibles');
      const config = this._gather(cur.config || {});
      const r = await App.api.autopilot_save_config({ config });
      if (r && r.ok) {
        this.cfg = config;
        // Brouillon = config serveur → on peut le purger.
        try { localStorage.removeItem(this._LS_DRAFT); } catch (e) {}
        btn.textContent = 'Enregistré ✓';
        Toast.success('Réglages enregistrés.');
      } else {
        btn.textContent = 'Erreur';
        Toast.error('Impossible d’enregistrer' + ((r && r.error) ? ' : ' + r.error : '.'));
      }
    } catch (e) {
      btn.textContent = 'Erreur';
      Toast.friendlyError(e, 'Impossible d’enregistrer les réglages.');
    }
    setTimeout(() => { btn.disabled = false; btn.textContent = 'Enregistrer'; }, 1600);
  },

  async run() {
    if (!App.api) return;
    if (this._launching) return;   // anti double-clic
    this._launching = true;
    this._setRunning(true);
    const logBox = document.getElementById('ec-log');
    if (logBox) { logBox.textContent = ''; delete logBox.dataset.empty; }
    document.getElementById('ec-stats').classList.add('hidden');
    this.logSeen = 0;
    try {
      // Même protection qu'Enregistrer : fusion de NOS champs dans la config
      // serveur fraîche (le lancement enregistre aussi la config côté serveur).
      const cur = await App.api.autopilot_get_config();
      if (!cur || !cur.ok) throw new Error((cur && cur.error) || 'réglages illisibles');
      const config = this._gather(cur.config || {});
      const r = await App.api.autopilot_run({ config, stages: ['search', 'enrich'] });
      if (!r || !r.ok) {
        const msg = this._friendlyRunError((r && r.error) || '');
        this._appendLog('✗ ' + msg);
        Toast.error(msg);
        this._setRunning(false);
        // Si le refus vient d'une recherche déjà en cours (lancée ailleurs),
        // on se resynchronise pour afficher le vrai état des boutons.
        this._refreshStatus();
        return;
      }
      this.cfg = config;
      try { localStorage.removeItem(this._LS_DRAFT); } catch (e) {}
      Toast.info('Recherche lancée — le journal défile en dessous.');
      this._startPolling();
    } catch (e) {
      this._appendLog('✗ Lancement impossible (souci de connexion ou de serveur).');
      Toast.friendlyError(e, 'Lancement impossible pour le moment.');
      this._setRunning(false);
    } finally {
      this._launching = false;
    }
  },

  // Demande l'arrêt de la recherche en cours (le serveur s'arrête en ~1 s).
  async stop() {
    if (!App.api) return;
    const btn = document.getElementById('ec-stop');
    if (btn) { btn.disabled = true; btn.textContent = 'Arrêt en cours…'; }
    try {
      const r = await App.api.autopilot_stop({});
      if (r && r.ok) {
        Toast.info('Arrêt demandé — la recherche s’arrête d’ici quelques secondes.');
        this._appendLog('⏹ Arrêt demandé…');
      } else {
        Toast.warn('Aucune recherche en cours — rien à arrêter.');
        this._setRunning(false);
      }
    } catch (e) {
      Toast.friendlyError(e, 'Impossible de demander l’arrêt.');
      if (btn) { btn.disabled = false; btn.textContent = '⏹ Arrêter'; }
    }
  },

  // Messages serveur connus → reformulés sans jargon.
  _friendlyRunError(raw) {
    if (/d[ée]j[àa] en cours/i.test(raw)) {
      return 'Une recherche tourne déjà — attends la fin ou clique sur Arrêter.';
    }
    if (/nocturne/i.test(raw)) {
      return 'Le passage automatique est en train de tourner — réessaie dans quelques minutes.';
    }
    return raw || 'Lancement impossible.';
  },

  _startPolling() {
    if (this.pollTimer) clearInterval(this.pollTimer);
    // App.viewInterval : minuteur auto-nettoyé quand on quitte la vue
    // (plus de boucle fantôme qui continue sur les autres écrans).
    this.pollTimer = App.viewInterval(() => this._refreshStatus(), 1500);
  },

  async _refreshStatus() {
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
      // Reflète l'état réel : utile aussi quand on ARRIVE sur l'écran alors
      // qu'une recherche tourne déjà (bouton « En cours… » + Arrêter visible).
      this._setRunning(true, !!r.stop_requested);
      if (!this.pollTimer) this._startPolling();
      return;
    }
    if (this.pollTimer) {
      clearInterval(this.pollTimer);
      this.pollTimer = null;
    }
    this._setRunning(false);
    if (r.stats) this._renderStats(r.stats);
    if (r.error) this._appendLog('✗ ' + r.error);
  },

  // État visuel des boutons Lancer / Arrêter.
  _setRunning(running, stopRequested = false) {
    const run = document.getElementById('ec-run');
    const stop = document.getElementById('ec-stop');
    if (run) {
      run.disabled = !!running;
      run.innerHTML = running
        ? `<span class="inline-block w-4 h-4 mr-2 rounded-full border-2 border-white/40 border-t-white animate-spin"></span>En cours…`
        : `
      <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M21 21l-4.35-4.35"/><circle cx="11" cy="11" r="8"/></svg>
      Lancer la recherche`;
    }
    if (stop) {
      stop.hidden = !running;
      stop.disabled = !!stopRequested;
      stop.textContent = stopRequested ? 'Arrêt en cours…' : '⏹ Arrêter';
    }
    // Badge « en cours » à côté du journal : c'est là que les yeux sont.
    const badge = document.getElementById('ec-running-badge');
    if (badge) badge.classList.toggle('hidden', !running);
  },

  _appendLog(line) {
    const box = document.getElementById('ec-log');
    if (!box) return;
    if (box.dataset.empty) { box.textContent = ''; delete box.dataset.empty; }
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
        ${this._kpi('Fiches complétées (email/tél)', s.enriched ?? 0, 'success')}
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
      <div class="mt-4">
        <button id="ec-see-prospects" class="btn btn-secondary">
          Voir les fiches dans « Tous les prospects » →
        </button>
      </div>
    `;
    const see = document.getElementById('ec-see-prospects');
    if (see) see.onclick = () => App.show('prospects_crm');
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

  // opts : { type, min, max, inputmode, hint } — hint = petite aide sous le champ.
  _input(label, key, value, placeholder = '', opts = {}) {
    const type = opts.type || 'text';
    const extra = [
      opts.min != null ? `min="${opts.min}"` : '',
      opts.max != null ? `max="${opts.max}"` : '',
      opts.inputmode ? `inputmode="${this._esc(opts.inputmode)}"` : '',
    ].filter(Boolean).join(' ');
    return `
      <label class="block">
        <div class="text-xs font-medium text-text-secondary mb-1.5">${this._esc(label)}</div>
        <input type="${type}" data-key="${key}" value="${this._esc(value)}"
               placeholder="${this._esc(placeholder)}" ${extra}
               class="w-full px-3 py-2 rounded-lg bg-bg border border-border
                      focus:border-accent focus:outline-none text-sm" />
        ${opts.hint ? `<div class="text-[11px] text-text-muted mt-1">${this._esc(opts.hint)}</div>` : ''}
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
          Cet écran a besoin de la connexion au serveur.
          Recharge la page dans un instant.
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
