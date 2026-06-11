/* PROSPECTION — l'écran-tunnel guidé.
 *
 * Refonte UX 2026-06-10 : un seul écran qui prend l'utilisateur par la main
 * du tout premier instant jusqu'aux réponses. Trois principes :
 *
 *  1. UN TUNNEL VISIBLE — la frise « Trouver → Ranger → Envoyer → Répondre »
 *     en haut montre toujours où on en est dans le parcours.
 *  2. UN ASSISTANT QUI DICTE — une grande carte annonce, en langage humain,
 *     où on en est ET la prochaine action, avec LE bouton. Il parle dès
 *     l'écran vide ; il ne laisse jamais un « et maintenant ? ».
 *  3. UNE SEULE COULEUR D'ACTION À LA FOIS — la prochaine chose à faire est
 *     en couleur vive ; tout le reste reste calme. L'œil va droit au but.
 *
 * Toute la mécanique (lancement, test à blanc, suivi des missions,
 * garde-fous) est conservée — seule l'enveloppe est refaite.
 */

const Prospection = {
  state: {
    source: 'pme',
    missions: [],
    autopilot: {},
    snap: {},          // compteurs (brouillons, réponses, prospects) via guide_snapshot
    launching: false,
    missionLimit: 12,  // augmenté par « Voir les recherches plus anciennes »
  },
  // Mémoire locale : formulaire (localStorage) + essais déjà relancés (sessionStorage)
  _LS_FORM: 'prospection:form',
  _SS_DRY: 'prospection:essais-relances',

  async render(container) {
    this._root = container;
    this._injectStyles();
    container.innerHTML = `
      <section class="animate-slide-up pr-wrap">
        <header class="pr-head">
          <div class="hero-kicker">PROSPECTION</div>
          <h1 class="pr-title">Trouve des clients, sans te poser de questions.</h1>
        </header>

        <div id="pr-rail" class="pr-rail"></div>

        <div id="pr-assistant" class="pr-assistant-slot"></div>

        <div class="pr-card" id="pr-finder">
          <div class="pr-card-head">
            <span class="pr-step-num">1</span>
            <div>
              <div class="pr-card-title">Qui veux-tu démarcher ?</div>
              <div class="pr-card-sub">Choisis une cible, remplis deux champs, et c'est parti.</div>
            </div>
          </div>

          <div class="pr-tiles" id="pr-tiles">
            ${this._tile('pme', '🏢', 'PME françaises',
                         'Par métier et département')}
            ${this._tile('local', '📍', 'Commerces locaux',
                         'Par métier et ville')}
            ${this._tile('createurs', '🎥', 'Créateurs',
                         'YouTube, Twitch, par niche')}
            <button type="button" class="pr-tile pr-tile-ghost" id="pr-tile-liste"
                    title="Tu as déjà un fichier de contacts (PDF, Excel, Word…) ? Le Convoi s'en occupe.">
              <div class="pr-tile-icon">📄</div>
              <div class="pr-tile-title">J'ai déjà une liste</div>
              <div class="pr-tile-sub">PDF, Excel… → Le Convoi</div>
            </button>
          </div>

          <form id="pr-form" class="pr-form">
            <div id="pr-fields"></div>
            <label class="pr-dry" title="La recherche tourne pour de vrai, mais RIEN n'est enregistré et rien n'est envoyé. Tu obtiens un rapport : combien seraient ajoutés, la qualité des données, un échantillon.">
              <input type="checkbox" id="pr-f-dry" />
              <span>🧪 Faire un essai d'abord (rien n'est enregistré — juste un aperçu)</span>
            </label>
            <button type="submit" id="pr-launch" class="pr-launch">
              <span>🚀 Lancer la recherche</span>
            </button>
          </form>
        </div>

        <div id="pr-missions-block" class="pr-missions-block" hidden>
          <div class="pr-section-label">Ce qui se passe en ce moment</div>
          <div id="pr-missions"></div>
        </div>
      </section>
    `;
    // Restaure la dernière cible choisie + les champs saisis (mémoire locale,
    // comme Le Chasseur) — on ne perd plus sa saisie en changeant d'écran.
    const savedForm = this._readForm();
    if (savedForm && ['pme', 'local', 'createurs'].includes(savedForm.source)) {
      this.state.source = savedForm.source;
    }
    this._bindTiles();
    this._renderFields();
    const form = document.getElementById('pr-form');
    form.onsubmit = (e) => {
      e.preventDefault();
      this._launch();
    };
    // Mémorise la saisie au fil de l'eau (délégation : survit aux re-rendus
    // de #pr-fields quand on change de cible).
    form.addEventListener('input', () => this._saveForm());
    form.addEventListener('change', () => this._saveForm());
    const listeBtn = document.getElementById('pr-tile-liste');
    if (listeBtn) listeBtn.onclick = () => App.show('convoy');

    await this._refresh();
    this._startPolling();
  },

  // ───────────────────────── Cibles + champs ─────────────────────────
  _tile(key, icon, title, sub) {
    return `
      <button type="button" class="pr-tile" data-source="${key}">
        <div class="pr-tile-icon">${icon}</div>
        <div class="pr-tile-title">${title}</div>
        <div class="pr-tile-sub">${sub}</div>
      </button>`;
  },

  _bindTiles() {
    document.querySelectorAll('#pr-tiles .pr-tile[data-source]').forEach(t => {
      t.onclick = () => {
        this.state.source = t.dataset.source;
        this._syncTiles();
        this._renderFields();
        this._saveForm();   // mémorise aussi le changement de cible
      };
    });
    this._syncTiles();
  },

  _syncTiles() {
    document.querySelectorAll('#pr-tiles .pr-tile[data-source]').forEach(t => {
      t.classList.toggle('pr-tile-active', t.dataset.source === this.state.source);
    });
  },

  _renderFields() {
    const wrap = document.getElementById('pr-fields');
    if (!wrap) return;
    const s = this.state.source;
    if (s === 'pme') {
      wrap.innerHTML = `
        <div class="pr-grid-3">
          ${this._input('metier', 'Métier', 'ex : plombier, fleuriste')}
          ${this._input('departement', 'Département', 'ex : 71')}
          ${this._input('volume', 'Combien ?', '100', 'number')}
        </div>
        <label class="pr-opt">
          <input type="checkbox" id="pr-f-sites_pourris" />
          <span>Seulement les boîtes au site vieillot ou absent (idéal pour vendre une refonte)</span>
        </label>`;
    } else if (s === 'local') {
      wrap.innerHTML = `
        <div class="pr-grid-3">
          ${this._input('metier', 'Métier', 'ex : coiffeur, garage')}
          ${this._input('zone', 'Ville', 'ex : Rennes')}
          ${this._input('volume', 'Combien ?', '60', 'number')}
        </div>
        <label class="pr-opt">
          <input type="checkbox" id="pr-f-sans_site" />
          <span>Seulement ceux qui n'ont PAS de site (idéal pour vendre une création)</span>
        </label>`;
    } else {
      wrap.innerHTML = `
        <div class="pr-grid-2">
          ${this._input('niche', 'Niche / thème', 'ex : fitness, cuisine, gaming')}
          ${this._input('volume', 'Combien par plateforme ?', '30', 'number')}
        </div>
        <div class="pr-platforms">
          <span class="pr-opt-label">Plateformes :</span>
          ${['youtube', 'twitch', 'dailymotion', 'kick'].map((p, i) => `
            <label class="pr-chk">
              <input type="checkbox" class="pr-platform" value="${p}" ${i === 0 ? 'checked' : ''} />
              <span>${p.charAt(0).toUpperCase() + p.slice(1)}</span>
            </label>`).join('')}
        </div>
        <div class="pr-hint">Instagram, TikTok et les autres plateformes sont couvertes
          par Obélisk (menu « Outils de recherche »).</div>`;
    }
    this._applyForm();   // remet les valeurs mémorisées pour cette cible
    this._syncDry();     // l'essai à blanc n'existe pas pour les créateurs
  },

  // L'essai à blanc est refusé côté serveur pour les créateurs (l'outil
  // écrit dans la base pendant sa recherche) → on désactive la case et on
  // explique, plutôt que de laisser cliquer pour rien.
  _syncDry() {
    const box = document.getElementById('pr-f-dry');
    const label = box ? box.closest('.pr-dry') : null;
    if (!box || !label) return;
    const isCreators = this.state.source === 'createurs';
    box.disabled = isCreators;
    if (isCreators) box.checked = false;
    label.classList.toggle('pr-dry-off', isCreators);
    const span = label.querySelector('span');
    if (span) {
      span.textContent = isCreators
        ? '🧪 Essai indisponible pour les créateurs : cet outil enregistre pendant sa recherche. Mets un petit « Combien » pour tester.'
        : '🧪 Faire un essai d’abord (rien n’est enregistré — juste un aperçu)';
    }
    label.title = isCreators ? ''
      : 'La recherche tourne pour de vrai, mais RIEN n’est enregistré et rien n’est envoyé. Tu obtiens un rapport : combien seraient ajoutés, la qualité des données, un échantillon.';
  },

  // ─────────────── Mémoire locale du formulaire (comme Le Chasseur) ───────────────
  _readForm() {
    try { return JSON.parse(localStorage.getItem(this._LS_FORM) || 'null'); }
    catch (e) { return null; }
  },

  _saveForm() {
    try {
      const all = this._readForm() || {};
      const s = this.state.source;
      all.source = s;
      if (s === 'pme') {
        all.pme = { metier: this._val('metier'), departement: this._val('departement'),
                    volume: this._val('volume'), sites_pourris: this._val('sites_pourris') };
      } else if (s === 'local') {
        all.local = { metier: this._val('metier'), zone: this._val('zone'),
                      volume: this._val('volume'), sans_site: this._val('sans_site') };
      } else {
        all.createurs = { niche: this._val('niche'), volume: this._val('volume'),
                          plateformes: [...document.querySelectorAll('.pr-platform:checked')]
                            .map(c => c.value) };
      }
      localStorage.setItem(this._LS_FORM, JSON.stringify(all));
    } catch (e) {}
  },

  _applyForm() {
    const all = this._readForm();
    if (!all) return;
    const f = all[this.state.source];
    if (!f) return;
    const set = (id, val) => {
      const el = document.getElementById('pr-f-' + id);
      if (!el || val == null) return;
      if (el.type === 'checkbox') el.checked = !!val;
      else el.value = String(val);
    };
    if (this.state.source === 'pme') {
      set('metier', f.metier); set('departement', f.departement);
      set('volume', f.volume); set('sites_pourris', f.sites_pourris);
    } else if (this.state.source === 'local') {
      set('metier', f.metier); set('zone', f.zone);
      set('volume', f.volume); set('sans_site', f.sans_site);
    } else {
      set('niche', f.niche); set('volume', f.volume);
      if (Array.isArray(f.plateformes) && f.plateformes.length) {
        document.querySelectorAll('.pr-platform').forEach(c => {
          c.checked = f.plateformes.includes(c.value);
        });
      }
    }
  },

  // Essais à blanc déjà relancés en réel (mémoire de session) : l'assistant
  // arrête de proposer « Relancer pour de vrai » une fois que c'est fait.
  _dryConsumed() {
    try { return new Set(JSON.parse(sessionStorage.getItem(this._SS_DRY) || '[]')); }
    catch (e) { return new Set(); }
  },

  _markDryConsumed(id) {
    try {
      const s = this._dryConsumed();
      s.add(id);
      sessionStorage.setItem(this._SS_DRY, JSON.stringify([...s]));
    } catch (e) {}
  },

  _input(id, label, placeholder, type = 'text') {
    return `
      <label class="pr-field">
        <span class="pr-field-label">${label}</span>
        <input id="pr-f-${id}" type="${type}" placeholder="${placeholder}"
               class="pr-input" ${type === 'number' ? 'min="5" max="500"' : ''} />
      </label>`;
  },

  _val(id) {
    const el = document.getElementById('pr-f-' + id);
    if (!el) return '';
    if (el.type === 'checkbox') return el.checked;
    return (el.value || '').trim();
  },

  // ───────────────────────── Lancement ─────────────────────────
  async _launch() {
    if (this.state.launching) return;
    if (!App.api || typeof App.api.prospection_start !== 'function') {
      return Toast.info('Écran en mode aperçu — la connexion au serveur est requise pour lancer.');
    }
    const s = this.state.source;
    const params = {};
    if (s === 'pme') {
      params.metier = this._val('metier');
      params.departement = this._val('departement');
      params.volume = parseInt(this._val('volume') || '100', 10);
      params.sites_pourris = this._val('sites_pourris');
      if (!params.metier && !params.departement) {
        return Toast.warn('Indique au moins un métier ou un département.');
      }
    } else if (s === 'local') {
      params.metier = this._val('metier');
      params.zone = this._val('zone');
      params.volume = parseInt(this._val('volume') || '60', 10);
      params.sans_site = this._val('sans_site');
      if (!params.metier || !params.zone) {
        return Toast.warn('Indique un métier ET une ville.');
      }
    } else {
      params.niche = this._val('niche');
      params.volume = parseInt(this._val('volume') || '30', 10);
      params.plateformes = [...document.querySelectorAll('.pr-platform:checked')]
        .map(c => c.value);
      if (!params.niche) return Toast.warn('Indique une niche.');
      if (!params.plateformes.length) {
        return Toast.warn('Coche au moins une plateforme.');
      }
    }
    const dryBox = document.getElementById('pr-f-dry');
    const dryRun = !!(dryBox && dryBox.checked && !dryBox.disabled);
    this.state.launching = true;
    const btn = document.getElementById('pr-launch');
    if (btn) { btn.disabled = true; btn.querySelector('span').textContent = 'Lancement…'; }
    let r = null;
    let excToasted = false;
    try {
      r = await App.api.prospection_start({ source: s, params, dry_run: dryRun });
    } catch (e) {
      Toast.friendlyError(e, 'Lancement impossible pour le moment.');
      excToasted = true;
    }
    this.state.launching = false;
    if (btn) { btn.disabled = false; btn.querySelector('span').textContent = '🚀 Lancer la recherche'; }
    if (!r || !r.ok) {
      // r.error vient du serveur, déjà en français ; sinon message générique.
      if (!excToasted) Toast.error((r && r.error) || 'Lancement impossible pour le moment.');
      return;
    }
    // L'essai est lancé : on décoche la case pour que le prochain clic
    // parte en réel par défaut (et pas en essai par surprise).
    if (dryRun && dryBox) dryBox.checked = false;
    // Pas de surprise : si l'Auto-pilote est éteint, le dire AU MOMENT du
    // lancement (pas seulement en fin de chasse sur la carte de mission) —
    // sinon on croit que les mails vont partir alors que rien n'écrira.
    const apOn = !!(this.state.autopilot || {}).enabled;
    if (dryRun) {
      Toast.success('Essai lancé — je te montre l’aperçu dès que c’est prêt.');
    } else if (apOn) {
      Toast.success('C’est parti — la recherche tourne, je m’occupe de la suite.');
    } else {
      Toast.warn('Recherche lancée ! Mais l’Auto-pilote est éteint : les fiches '
        + 'trouvées attendront dans ta base sans recevoir de mail. '
        + 'Allume-le (carte en haut de l’écran) pour qu’il écrive.');
    }
    if (typeof Guide !== 'undefined' && Guide.say) {
      Guide.say('✓ Recherche lancée — je te préviens dès qu’elle a fini.');
    }
    await this._refresh();
    // Amène l'œil sur la mission qui démarre
    document.getElementById('pr-missions-block')
      ?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  },

  // ───────────────────────── État + rendu global ─────────────────────────
  async _refresh() {
    if (!App.api || typeof App.api.prospection_missions !== 'function') {
      this._renderAssistant({ kind: 'preview' });
      return;
    }
    const [mres, snap] = await Promise.all([
      App.api.prospection_missions({ limit: this.state.missionLimit || 12 }).catch(() => null),
      (App.api.guide_snapshot ? App.api.guide_snapshot({}).catch(() => null) : null),
    ]);
    if (mres && mres.ok) {
      this.state.missions = mres.missions || [];
      this.state.autopilot = mres.autopilot || {};
    }
    if (snap && snap.ok) this.state.snap = snap;

    // Une seule décision pour la frise ET l'assistant (jamais divergents).
    const rec = this._nextAction();
    this._renderRail(rec);
    this._renderAssistant(rec);
    this._renderMissions();
  },

  // Calcule où on en est dans le tunnel + LA prochaine action. Une seule.
  // Ordre de priorité = l'ordre naturel du parcours, le plus urgent gagne.
  // `finder: true` = l'action recommandée EST le formulaire de lancement
  // (sert à décider quel bouton reste « vif » à l'écran).
  _nextAction() {
    const snap = this.state.snap || {};
    const ap = this.state.autopilot || {};
    const missions = this.state.missions || [];
    const drafts = snap.drafts_pending || 0;
    const replies = snap.replies_unhandled || 0;
    const newProspects = snap.prospects_new || 0;
    const totalProspects = snap.prospects_total || 0;

    const activeMission = missions.find(m => m.status === 'hunting' || m.status === 'handing');
    const consumed = this._dryConsumed();
    const dryDone = missions.find(m => m.dry_run && m.status === 'handed' && !consumed.has(m.id));

    // 0 · La dernière recherche a planté → le dire AVANT tout le reste
    //     (sinon l'assistant affiche « Tout roule » au-dessus d'une panne).
    const last = missions[0];
    if (last && last.status === 'error') {
      return { step: 1, tone: 'err', icon: '⚠️',
        title: 'Ta dernière recherche a rencontré un souci',
        msg: (last.error ? `Détail : ${last.error}. ` : '') +
             'Rien d’autre n’a été touché. Ajuste les critères ci-dessous et relance.',
        btn: 'Modifier et relancer', finder: true, action: () => this._focusFinder() };
    }
    // 4 · Répondre — le plus précieux : quelqu'un a répondu
    if (replies > 0) {
      return { step: 4, tone: 'go', icon: '💬',
        title: `${replies} ${replies > 1 ? 'personnes t’ont' : 'personne t’a'} répondu !`,
        msg: 'C’est le moment qui compte. Va voir qui est intéressé.',
        btn: 'Voir les réponses', view: 'replies' };
    }
    // 3 · Envoyer — des mails attendent ton OK
    if (drafts > 0) {
      return { step: 3, tone: 'go', icon: '✉️',
        title: `${drafts} mail${drafts > 1 ? 's' : ''} ${drafts > 1 ? 'sont prêts' : 'est prêt'} à partir`,
        msg: 'L’app les a écrits. Relis-les vite fait et valide : ils partent aussitôt.',
        btn: 'Valider les mails', view: 'drafts' };
    }
    // 1 · Une recherche est en cours → rassurer, rien à faire
    if (activeMission) {
      const c = activeMission.counts || {};
      return { step: 1, tone: 'wait', icon: '⏳',
        title: 'Ta recherche est en cours…',
        msg: `${c.found || 0} trouvés pour l'instant${c.with_email ? `, dont ${c.with_email} avec un mail` : ''}. ` +
             'Tu peux fermer la page — je continue et je te préviens à la fin.',
        btn: null };
    }
    // 2bis · Un essai est terminé → inviter à passer au réel (une seule fois)
    if (dryDone) {
      const c = dryDone.counts || {};
      return { step: 2, tone: 'go', icon: '🧪',
        title: `Ton essai a trouvé ${c.would_push || 0} fiche${(c.would_push || 0) > 1 ? 's' : ''} exploitable${(c.would_push || 0) > 1 ? 's' : ''}`,
        msg: 'Rien n’a été enregistré. Si le résultat te plaît, relance pour de vrai.',
        btn: 'Relancer pour de vrai', action: () => this._relaunchDry(dryDone.id) };
    }
    // 3bis · Des prospects en base, mais l'Auto-pilote est éteint
    if (newProspects > 0 && !ap.enabled) {
      const perRun = ap.per_run || 0;
      return { step: 3, tone: 'go', icon: '🤖',
        title: `${newProspects} prospect${newProspects > 1 ? 's' : ''} ${newProspects > 1 ? 'attendent' : 'attend'} qu'on leur écrive`,
        msg: 'Allume l’Auto-pilote : il leur préparera des mails'
             + (perRun ? ` par petits paquets de ${perRun} par passage` : '')
             + ' (que tu valides avant l’envoi).',
        btn: 'Allumer l’Auto-pilote', action: () => this._toggleAutopilot(true) };
    }
    // Premier écran / base vide → accueil qui dit exactement quoi faire
    if (totalProspects === 0 && missions.length === 0) {
      return { step: 1, tone: 'start', icon: '👋',
        title: 'Bienvenue ! On va te trouver tes premiers clients.',
        msg: 'C’est simple : choisis qui tu veux démarcher juste en dessous, ' +
             'remplis deux petits champs, et clique sur le grand bouton. Je m’occupe de tout le reste.',
        btn: 'Choisir une cible', finder: true, action: () => this._focusFinder() };
    }
    // Tout est calme + Auto-pilote allumé → rassurer, proposer d'en relancer une
    if (ap.enabled) {
      if (!totalProspects) {
        // Base encore vide : ne pas dire « tout roule, tu as 0 prospect ».
        return { step: 1, tone: 'start', icon: '🧭',
          title: 'Ta base est encore vide.',
          msg: 'Lance une première recherche ci-dessous — je range tout sans doublon, et l’Auto-pilote prendra le relais.',
          btn: 'Choisir une cible', finder: true, action: () => this._focusFinder() };
      }
      const perRunOn = ap.per_run || 0;
      return { step: 1, tone: 'calm', icon: '✅',
        title: 'Tout roule. L’Auto-pilote travaille pour toi.',
        msg: `Tu as ${totalProspects} prospect${totalProspects > 1 ? 's' : ''} en base. ` +
             (perRunOn
               ? `L’Auto-pilote écrit ${perRunOn} mail${perRunOn > 1 ? 's' : ''} par passage `
                 + `(chaque nuit vers ${ap.hour || 3}h) et les dépose dans tes Brouillons. `
               : '') +
             'Quand tu veux en trouver d’autres, lance une nouvelle recherche ci-dessous.',
        btn: 'Lancer une recherche', finder: true, action: () => this._focusFinder() };
    }
    // Base remplie, autopilote éteint, rien d'urgent
    return { step: 1, tone: 'start', icon: '🧭',
      title: 'Prêt pour une nouvelle recherche ?',
      msg: 'Choisis une cible ci-dessous et lance — je range tout dans ta base sans doublon.',
      btn: 'Choisir une cible', finder: true, action: () => this._focusFinder() };
  },

  // ───────────────────────── La frise du tunnel ─────────────────────────
  _renderRail(rec) {
    const el = document.getElementById('pr-rail');
    if (!el) return;
    const cur = (rec || this._nextAction() || {}).step || 1;
    const steps = [
      { n: 1, label: 'Trouver', sub: 'des prospects' },
      { n: 2, label: 'Ranger', sub: 'dans ta base' },
      { n: 3, label: 'Envoyer', sub: 'les mails' },
      { n: 4, label: 'Répondre', sub: 'aux intéressés' },
    ];
    el.innerHTML = steps.map((s, i) => {
      const state = s.n < cur ? 'done' : s.n === cur ? 'cur' : 'todo';
      return `
        <div class="pr-rail-step pr-rail-${state}">
          <div class="pr-rail-dot">${s.n < cur ? '✓' : s.n}</div>
          <div class="pr-rail-txt">
            <div class="pr-rail-label">${s.label}</div>
            <div class="pr-rail-sub">${s.sub}</div>
          </div>
        </div>
        ${i < steps.length - 1 ? `<div class="pr-rail-link ${s.n < cur ? 'pr-rail-link-done' : ''}"></div>` : ''}`;
    }).join('');
  },

  // ───────────────────────── L'assistant ─────────────────────────
  _renderAssistant(rec) {
    const el = document.getElementById('pr-assistant');
    if (!el) return;
    if (rec && rec.kind === 'preview') {
      el.innerHTML = `<div class="pr-assistant pr-assistant-calm">
        <div class="pr-a-icon">🧭</div>
        <div class="pr-a-body"><div class="pr-a-title">Mode aperçu</div>
        <div class="pr-a-msg">Cet écran a besoin de la connexion au serveur. Recharge la page dans un instant.</div></div></div>`;
      return;
    }
    rec = rec || {};
    const tone = rec.tone || 'start';
    // UNE SEULE action vive à l'écran :
    //  - l'assistant recommande le formulaire (rec.finder) → le gros bouton
    //    Lancer est l'action vive, celui de l'assistant passe en discret ;
    //  - l'assistant porte un bouton ailleurs (valider, répondre, allumer,
    //    relancer un essai…) → SON bouton est vif, Lancer passe en calme ;
    //  - recherche en cours (pas de bouton, ton « wait ») → tout reste calme.
    this._setLaunchPrimary(rec.finder ? true : (!rec.btn && tone !== 'wait'));

    const btnHtml = rec.btn ? `
      <button class="pr-a-btn${rec.finder ? ' pr-a-btn-ghost' : ''}" id="pr-a-action">${this._esc(rec.btn)} →</button>` : '';
    el.innerHTML = `
      <div class="pr-assistant pr-assistant-${tone}">
        <div class="pr-a-icon">${rec.icon || '🧭'}</div>
        <div class="pr-a-body">
          <div class="pr-a-title">${this._esc(rec.title || '')}</div>
          <div class="pr-a-msg">${this._esc(rec.msg || '')}</div>
        </div>
        ${btnHtml}
      </div>`;
    const b = document.getElementById('pr-a-action');
    if (b) b.onclick = () => {
      if (typeof rec.action === 'function') rec.action();
      else if (rec.view) App.show(rec.view);
    };
  },

  _setLaunchPrimary(primary) {
    const btn = document.getElementById('pr-launch');
    if (btn) btn.classList.toggle('pr-launch-calm', !primary);
  },

  _focusFinder() {
    const f = document.getElementById('pr-finder');
    if (f) f.scrollIntoView({ behavior: 'smooth', block: 'start' });
    const firstTile = document.querySelector('#pr-tiles .pr-tile[data-source]');
    if (firstTile) {
      firstTile.classList.add('pr-tile-flash');
      setTimeout(() => firstTile.classList.remove('pr-tile-flash'), 1200);
    }
  },

  async _relaunchDry(missionId) {
    if (this.state.launching) return;   // verrou anti double-clic
    const m = (this.state.missions || []).find(x => x.id === missionId);
    if (!m) return;
    this.state.launching = true;
    // Fige les boutons qui mènent ici (carte de mission + assistant)
    const btns = [...document.querySelectorAll('[data-real-id]')]
      .filter(b => b.dataset.realId === missionId);
    const aBtn = document.getElementById('pr-a-action');
    if (aBtn) btns.push(aBtn);
    btns.forEach(b => { b.disabled = true; });
    let r = null;
    let excToasted = false;
    try {
      r = await App.api.prospection_start({
        source: m.source, params: m.params || {}, dry_run: false,
      });
    } catch (e) {
      Toast.friendlyError(e, 'Relance impossible pour le moment.');
      excToasted = true;
    }
    this.state.launching = false;
    if (!r || !r.ok) {
      btns.forEach(b => { b.disabled = false; });
      if (!excToasted) Toast.error((r && r.error) || 'Relance impossible pour le moment.');
      return;
    }
    // Essai consommé : l'assistant arrête de proposer cette relance en boucle.
    this._markDryConsumed(missionId);
    Toast.success('C’est parti pour de vrai — ta base va se remplir.');
    await this._refresh();
  },

  // ───────────────────────── Auto-pilote ─────────────────────────
  async _toggleAutopilot(turnOn) {
    // Garde-fou : on confirme si l'envoi est AUTOMATIQUE… et AUSSI quand le
    // mode est inconnu (réglage illisible) — dans le doute, on ne laisse pas
    // partir des mails tout seuls sans prévenir.
    const sendMode = (this.state.autopilot || {}).send_mode || '';
    if (turnOn && sendMode !== 'manual') {
      const ok = await Dialog.confirm(
        (sendMode === 'auto'
          ? 'L’envoi est réglé sur AUTOMATIQUE : en allumant l’Auto-pilote, des mails partiront tout seuls vers les prospects de ta base, sans validation manuelle.'
          : 'Impossible de vérifier le mode d’envoi à l’instant. S’il est réglé sur AUTOMATIQUE, des mails partiront tout seuls, sans validation manuelle.') +
        '\n\nPour garder la main, passe le maillon « Envoie » en Manuel dans les réglages de l’Auto-pilote.',
        { title: '⚠ Envoi automatique', okLabel: 'Allumer quand même',
          cancelLabel: 'Annuler', danger: true });
      if (!ok) return;
    }
    try {
      const r = await App.api.autopilot_get_config();
      if (!r || !r.ok) throw new Error((r && r.error) || 'réglages illisibles');
      const cfg = r.config || {};
      cfg.enabled = !!turnOn;
      const s = await App.api.autopilot_save_config({ config: cfg });
      if (!s || !s.ok) throw new Error((s && s.error) || 'enregistrement refusé');
      const apSnap = this.state.autopilot || {};
      const perRun = apSnap.per_run || 0;
      Toast.success(turnOn
        ? ('Auto-pilote allumé — il prépare les mails'
           + (perRun ? ` par paquets de ${perRun}` : '')
           + ', à valider dans Brouillons. Premier passage cette nuit vers '
           + `${apSnap.hour || 3}h — ou tout de suite avec « Lancer `
           + 'maintenant » (écran Auto-pilote).')
        : 'Auto-pilote éteint.');
    } catch (e) {
      Toast.friendlyError(e, 'Impossible de changer l’Auto-pilote pour le moment.');
    }
    await this._refresh();
  },

  // ───────────────────────── Missions ─────────────────────────
  _renderMissions() {
    const block = document.getElementById('pr-missions-block');
    const wrap = document.getElementById('pr-missions');
    if (!wrap || !block) return;
    const missions = this.state.missions || [];
    if (!missions.length) { block.hidden = true; return; }
    block.hidden = false;
    // Le rafraîchissement ne doit PAS refermer ce que Jordan est en train de
    // lire : on mémorise les aperçus ouverts avant de réécrire, on les rouvre après.
    const openIds = new Set(
      [...wrap.querySelectorAll('details[data-mission][open]')].map(d => d.dataset.mission));
    wrap.innerHTML = missions.map(m => this._missionCard(m)).join('')
      + (missions.length >= (this.state.missionLimit || 12) ? `
        <button type="button" class="pr-more-btn" id="pr-more">
          Voir les recherches plus anciennes
        </button>` : '');
    wrap.querySelectorAll('details[data-mission]').forEach(d => {
      if (openIds.has(d.dataset.mission)) d.open = true;
    });
    wrap.querySelectorAll('[data-cancel-id]').forEach(b => {
      b.onclick = async () => {
        const ok = await Dialog.confirm(
          'La recherche n’est pas arrêtée : elle continue côté serveur et ses ' +
          'fiches seront quand même versées dans ta base. Tu ne la verras ' +
          'simplement plus dans cette liste.',
          { title: 'Ne plus suivre cette recherche ?', okLabel: 'Ne plus suivre',
            cancelLabel: 'Continuer à suivre' });
        if (!ok) return;
        try {
          const r = await App.api.prospection_mission_cancel({ id: b.dataset.cancelId });
          if (!r || !r.ok) throw new Error((r && r.error) || 'refus du serveur');
          Toast.info('D’accord, je ne suis plus cette recherche. Elle continue en fond et versera ses fiches.');
        } catch (e) {
          Toast.friendlyError(e, 'Impossible de retirer cette recherche du suivi.');
        }
        await this._refresh();
      };
    });
    wrap.querySelectorAll('[data-real-id]').forEach(b => {
      b.onclick = () => this._relaunchDry(b.dataset.realId);
    });
    wrap.querySelectorAll('[data-open-view]').forEach(b => {
      b.onclick = () => App.show(b.dataset.openView);
    });
    const more = document.getElementById('pr-more');
    if (more) more.onclick = async () => {
      more.disabled = true;
      this.state.missionLimit = (this.state.missionLimit || 12) + 12;
      await this._refresh();
    };
  },

  _missionCard(m) {
    const counts = m.counts || {};
    const status = m.status || '';
    const dry = !!m.dry_run;
    const active = status === 'hunting' || status === 'handing';
    const badge = {
      hunting: ['En recherche…', 'pr-badge-go'],
      handing: [dry ? 'Aperçu en cours…' : 'Rangement…', 'pr-badge-go'],
      handed: [dry ? 'Essai terminé 🧪' : 'Terminé ✓', 'pr-badge-done'],
      error: ['Souci', 'pr-badge-err'],
      cancelled: ['Abandonnée', 'pr-badge-mute'],
    }[status] || [status, 'pr-badge-mute'];

    const step = (label, st, detail) => {
      const icon = st === 'done' ? '✅' : st === 'active' ? '🔄' : st === 'error' ? '❌' : '◯';
      return `
        <div class="pr-mstep ${st === 'pending' ? 'pr-mstep-todo' : ''}">
          <span class="pr-mstep-ic">${icon}</span>
          <div>
            <div class="pr-mstep-lb">${label}</div>
            ${detail ? `<div class="pr-mstep-dt">${detail}</div>` : ''}
          </div>
        </div>`;
    };

    const huntState = status === 'hunting' ? 'active'
      : status === 'error' && !counts.pushed ? 'error' : 'done';
    const huntDetail = status === 'hunting'
      ? `${m.progress || 0}% — ${counts.found || 0} trouvés (${counts.with_email || 0} avec mail)`
      : `${counts.found || 0} trouvés, ${counts.with_email || 0} avec mail`;

    const pushState = status === 'handed' ? 'done'
      : status === 'handing' ? 'active'
      : status === 'error' && counts.found ? 'error' : 'pending';
    const pushDetail = status !== 'handed' ? ''
      : dry
        ? `${counts.would_push || 0} seraient ajoutés (${counts.would_create || 0} nouveaux, ${counts.would_merge || 0} fusions) — rien d'enregistré`
      : (m.source === 'createurs'
          ? 'rangés dans la base'
          : `${counts.pushed || 0} rangés (${counts.created || 0} nouveaux, ${counts.merged || 0} fusionnés)`);

    const ap = m.autopilot || {};
    const apState = status !== 'handed' ? 'pending' : (ap.kicked ? 'done' : 'pending');
    const apDetail = status === 'handed' ? (ap.note || '') : '';

    // Lien vers l'outil qui a fait la chasse (détail complet des résultats)
    const tool = {
      pme:       ['chasseur', 'Le Chasseur'],
      local:     ['prospecteur_google', 'le Prospecteur Google'],
      createurs: ['obelisk', 'Obélisk'],
    }[m.source];
    const dryConsumed = dry && status === 'handed' && this._dryConsumed().has(m.id);

    return `
      <article class="pr-mission">
        <div class="pr-mission-head">
          <div class="min-w-0">
            <div class="pr-mission-date">${this._fmtDate(m.created_at)}</div>
            <div class="pr-mission-label">${this._esc(m.label || '(sans nom)')}</div>
          </div>
          <div class="pr-mission-right">
            <span class="pr-badge ${badge[1]}">${badge[0]}</span>
            ${active ? `<button class="pr-mini-btn" data-cancel-id="${this._esc(m.id)}">Ne plus suivre</button>` : ''}
          </div>
        </div>
        ${m.error ? `<div class="pr-mission-err">⚠ ${this._esc(m.error)}</div>` : ''}
        <div class="pr-mchain">
          ${step('1 · Trouve', huntState, huntDetail)}
          ${step(dry ? '2 · Rangement (simulé)' : '2 · Range dans la base', pushState, pushDetail)}
          ${step(dry ? '3 · Envoi (désactivé)' : '3 · Écrit & envoie', apState, apDetail)}
          ${step('4 · Réponses',
                 status === 'handed' && !dry ? 'done' : 'pending',
                 status === 'handed' && !dry ? 'triées automatiquement' : '')}
        </div>
        ${this._qualityLine(m)}
        ${this._previewBlock(m)}
        ${dry && status === 'handed' && !dryConsumed ? `
          <button class="pr-real-btn" data-real-id="${this._esc(m.id)}">
            ✅ Le résultat me plaît — relancer pour de vrai
          </button>` : ''}
        ${dryConsumed ? `<div class="pr-real-done">✓ Déjà relancée pour de vrai</div>` : ''}
        ${tool ? `
          <div class="pr-mission-foot">
            <button type="button" class="pr-link" data-open-view="${tool[0]}">
              Voir le détail dans ${tool[1]} →
            </button>
          </div>` : ''}
      </article>`;
  },

  _qualityLine(m) {
    const q = m.quality;
    if (!q || !q.total) return '';
    const d = q.dropped || {};
    const labels = { no_email: 'sans email', bad_email: 'email invalide',
                     placeholder_name: 'nom fantôme', duplicate_in_batch: 'doublon' };
    const parts = Object.entries(d).filter(([, n]) => n > 0)
      .map(([k, n]) => `${n} ${labels[k] || k}`);
    return `
      <div class="pr-quality">
        🛡️ <b>${q.kept}/${q.total} fiches gardées</b>${parts.length ? ' — écartées : ' + this._esc(parts.join(', ')) : ' — tout est propre'}
      </div>`;
  },

  _previewBlock(m) {
    const rows = m.preview || [];
    if (!rows.length) return '';
    // data-mission : permet de garder l'aperçu OUVERT à travers les
    // rafraîchissements (sinon le rapport se referme toutes les 8 s).
    return `
      <details class="pr-preview" data-mission="${this._esc(m.id)}">
        <summary>Voir l'aperçu (${rows.length} fiche${rows.length > 1 ? 's' : ''})</summary>
        <div class="pr-preview-list">
          ${rows.map(r => `
            <div class="pr-preview-row">
              <span class="pr-preview-name">${this._esc(r.nom || '(sans nom)')}</span>
              <span class="pr-preview-mail">${this._esc(r.email)}</span>
              <span class="pr-preview-sort ${r.sort === 'nouvelle fiche' ? 'is-new' : ''}">${this._esc(r.sort)}</span>
            </div>`).join('')}
        </div>
      </details>`;
  },

  // ───────────────────────── Polling ─────────────────────────
  // App.viewInterval = minuteur auto-nettoyé dès qu'on quitte la vue
  // (plus de boucle fantôme qui continue sur un autre écran).
  _startPolling() {
    let tick = 0;
    App.viewInterval(() => {
      tick += 1;
      const hasActive = (this.state.missions || [])
        .some(m => m.status === 'hunting' || m.status === 'handing');
      // Chasse en cours → toutes les 8 s. Sinon un passage sur trois suffit
      // (capter brouillons/réponses qui arrivent en fond, sans marteler le serveur).
      if (!hasActive && tick % 3 !== 0) return;
      this._refresh();
    }, 8000);
  },

  // ───────────────────────── Styles + helpers ─────────────────────────
  _injectStyles() {
    if (document.getElementById('pr-styles')) return;
    const s = document.createElement('style');
    s.id = 'pr-styles';
    s.textContent = `
      /* --on-accent : texte posé sur un fond accent plein. Blanc garanti
         lisible (≥ 6:1) par le contrat de --accent-strong (cf. tokens.css).
         Déclaré ici en token local faute de token global équivalent. */
      .pr-wrap { max-width: 760px; margin: 0 auto; --on-accent: 0 0% 100%; }
      .pr-head { margin-bottom: 18px; }
      .pr-title { font-family: var(--font-display, inherit); font-weight: 800;
        font-size: clamp(22px, 4vw, 30px); line-height: 1.15; margin-top: 6px;
        color: hsl(var(--text)); text-wrap: balance; }

      /* ─ Frise du tunnel ─ */
      .pr-rail { display: flex; align-items: center; gap: 4px; margin-bottom: 20px;
        overflow-x: auto; padding-bottom: 2px; }
      .pr-rail-step { display: flex; align-items: center; gap: 9px; flex-shrink: 0; }
      .pr-rail-dot { width: 30px; height: 30px; border-radius: 50%; flex-shrink: 0;
        display: grid; place-items: center; font-size: 13px; font-weight: 800;
        border: 2px solid hsl(var(--border-strong)); color: hsl(var(--text-muted));
        background: hsl(var(--surface)); transition: all .25s; }
      .pr-rail-label { font-size: 12.5px; font-weight: 700; color: hsl(var(--text-muted)); line-height: 1.1; }
      .pr-rail-sub { font-size: 11px; color: hsl(var(--text-muted)); opacity: .8; }
      .pr-rail-link { width: 22px; height: 2px; background: hsl(var(--border-strong)); flex-shrink: 0; }
      .pr-rail-link-done { background: hsl(var(--success)); }
      .pr-rail-cur .pr-rail-dot { border-color: hsl(var(--accent-strong));
        background: hsl(var(--accent-strong)); color: hsl(var(--on-accent));
        box-shadow: 0 0 0 4px hsl(var(--accent) / .15); }
      .pr-rail-cur .pr-rail-label { color: hsl(var(--text)); }
      .pr-rail-done .pr-rail-dot { border-color: hsl(var(--success));
        background: hsl(var(--success) / .12); color: hsl(var(--success)); }

      /* ─ Assistant ─ */
      .pr-assistant-slot { margin-bottom: 20px; }
      .pr-assistant { display: flex; align-items: center; gap: 14px;
        border-radius: 16px; padding: 18px 20px; border: 1px solid hsl(var(--border)); }
      .pr-a-icon { font-size: 26px; flex-shrink: 0; line-height: 1; }
      .pr-a-body { flex: 1; min-width: 0; }
      .pr-a-title { font-weight: 800; font-size: 15.5px; color: hsl(var(--text));
        margin-bottom: 3px; text-wrap: balance; }
      .pr-a-msg { font-size: 13px; line-height: 1.5; color: hsl(var(--text-secondary)); text-wrap: pretty; }
      .pr-a-btn { flex-shrink: 0; border: 0; cursor: pointer; white-space: nowrap;
        background: hsl(var(--accent-strong)); color: hsl(var(--on-accent)); font-weight: 700; font-size: 13.5px;
        padding: 11px 18px; border-radius: 11px; transition: transform .12s, box-shadow .12s, background .14s; }
      .pr-a-btn:hover { transform: translateY(-1px); background: hsl(var(--accent-strong-hover));
        box-shadow: 0 6px 18px hsl(var(--accent) / .4); }
      .pr-a-btn:disabled { opacity: .6; cursor: wait; transform: none; box-shadow: none; }
      /* Version discrète : quand l'action vive est le bouton Lancer du formulaire */
      .pr-a-btn-ghost { background: transparent; color: hsl(var(--accent-text));
        border: 1.5px solid hsl(var(--accent) / .5); }
      .pr-a-btn-ghost:hover { background: hsl(var(--accent) / .08); box-shadow: none; }
      /* Tons de l'assistant (la couleur sert le sens) */
      .pr-assistant-go    { background: hsl(var(--accent) / .08);  border-color: hsl(var(--accent) / .35); }
      .pr-assistant-start { background: hsl(var(--accent) / .06);  border-color: hsl(var(--accent) / .25); }
      .pr-assistant-wait  { background: hsl(var(--warning) / .08); border-color: hsl(var(--warning) / .3); }
      .pr-assistant-calm  { background: hsl(var(--success) / .07); border-color: hsl(var(--success) / .25); }
      .pr-assistant-err   { background: hsl(var(--danger) / .08);  border-color: hsl(var(--danger) / .35); }
      .pr-assistant-wait .pr-a-icon { animation: prPulse 1.8s ease-in-out infinite; }
      @keyframes prPulse { 0%,100% { opacity: 1; } 50% { opacity: .45; } }

      /* ─ Carte trouver ─ */
      .pr-card { background: hsl(var(--surface)); border: 1px solid hsl(var(--border));
        border-radius: 18px; padding: 22px; margin-bottom: 24px; box-shadow: var(--shadow-soft, none); }
      .pr-card-head { display: flex; align-items: flex-start; gap: 12px; margin-bottom: 16px; }
      .pr-step-num { width: 26px; height: 26px; border-radius: 50%; flex-shrink: 0;
        display: grid; place-items: center; font-weight: 800; font-size: 13px;
        background: hsl(var(--accent-strong)); color: hsl(var(--on-accent)); }
      .pr-card-title { font-weight: 800; font-size: 16px; color: hsl(var(--text)); }
      .pr-card-sub { font-size: 12.5px; color: hsl(var(--text-muted)); margin-top: 1px; }

      .pr-tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
        gap: 11px; margin-bottom: 18px; }
      .pr-tile { text-align: left; padding: 15px; border-radius: 14px; cursor: pointer;
        border: 1.5px solid hsl(var(--border)); background: hsl(var(--bg) / .5); transition: all .14s; }
      .pr-tile:hover { border-color: hsl(var(--accent) / .55); transform: translateY(-1px); }
      .pr-tile-active { border-color: hsl(var(--accent)); background: hsl(var(--accent) / .08);
        box-shadow: 0 0 0 1px hsl(var(--accent)); }
      .pr-tile-ghost { border-style: dashed; opacity: .9; }
      .pr-tile-flash { animation: prFlash 1.2s ease; }
      @keyframes prFlash { 0%,100% { box-shadow: 0 0 0 0 hsl(var(--accent)/0); }
        30% { box-shadow: 0 0 0 4px hsl(var(--accent) / .35); } }
      .pr-tile-icon { font-size: 22px; margin-bottom: 7px; }
      .pr-tile-title { font-weight: 700; font-size: 14px; color: hsl(var(--text)); }
      .pr-tile-sub { font-size: 11.5px; color: hsl(var(--text-muted)); margin-top: 2px; }

      .pr-form { display: flex; flex-direction: column; gap: 14px; }
      .pr-grid-3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 11px; }
      .pr-grid-2 { display: grid; grid-template-columns: 2fr 1fr; gap: 11px; }
      @media (max-width: 560px) { .pr-grid-3, .pr-grid-2 { grid-template-columns: 1fr; } }
      .pr-field { display: block; }
      .pr-field-label { display: block; font-size: 12px; font-weight: 600;
        color: hsl(var(--text-secondary)); margin-bottom: 5px; }
      .pr-input { width: 100%; background: hsl(var(--bg)); border: 1.5px solid hsl(var(--border-strong));
        border-radius: 11px; padding: 11px 13px; font-size: 14px; color: hsl(var(--text)); transition: border .14s; }
      .pr-input:focus { outline: none; border-color: hsl(var(--accent)); box-shadow: 0 0 0 3px hsl(var(--accent) / .15); }
      .pr-opt, .pr-dry, .pr-chk { display: flex; align-items: center; gap: 9px; cursor: pointer;
        font-size: 13px; color: hsl(var(--text-secondary)); }
      .pr-opt input, .pr-dry input, .pr-chk input { width: 17px; height: 17px; accent-color: hsl(var(--accent)); flex-shrink: 0; }
      .pr-dry { background: hsl(var(--bg) / .6); border: 1px dashed hsl(var(--border-strong));
        border-radius: 11px; padding: 11px 13px; }
      .pr-dry-off { opacity: .65; cursor: not-allowed; }
      .pr-dry-off input { cursor: not-allowed; }
      .pr-platforms { display: flex; flex-wrap: wrap; align-items: center; gap: 14px; }
      .pr-opt-label { font-size: 12px; color: hsl(var(--text-muted)); font-weight: 600; }
      .pr-hint { font-size: 11.5px; color: hsl(var(--text-muted)); }

      .pr-launch { width: 100%; border: 0; cursor: pointer; padding: 15px; border-radius: 13px;
        background: hsl(var(--accent-strong)); color: hsl(var(--on-accent)); font-weight: 800; font-size: 15.5px;
        transition: transform .12s, box-shadow .12s, background .14s; margin-top: 2px; }
      .pr-launch:hover { transform: translateY(-1px); background: hsl(var(--accent-strong-hover));
        box-shadow: 0 8px 22px hsl(var(--accent) / .4); }
      .pr-launch:disabled { opacity: .6; cursor: wait; }
      /* Quand l'action prioritaire est ailleurs : le bouton se calme */
      .pr-launch-calm { background: hsl(var(--surface)); color: hsl(var(--text-secondary));
        border: 1.5px solid hsl(var(--border-strong)); }
      .pr-launch-calm:hover { background: hsl(var(--surface)); box-shadow: none;
        border-color: hsl(var(--accent) / .5); color: hsl(var(--text)); }

      /* ─ Missions ─ */
      .pr-section-label { font-size: 11px; font-weight: 700; letter-spacing: .08em;
        text-transform: uppercase; color: hsl(var(--text-muted)); margin-bottom: 12px; }
      .pr-mission { background: hsl(var(--surface)); border: 1px solid hsl(var(--border));
        border-radius: 16px; padding: 17px; margin-bottom: 12px; }
      .pr-mission-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 13px; }
      .pr-mission-date { font-size: 11px; color: hsl(var(--text-muted)); }
      .pr-mission-label { font-weight: 700; font-size: 14px; color: hsl(var(--text)); }
      .pr-mission-right { display: flex; align-items: center; gap: 9px; flex-shrink: 0; }
      .pr-badge { font-size: 11.5px; font-weight: 700; padding: 4px 10px; border-radius: 999px; }
      .pr-badge-go { background: hsl(var(--accent) / .12); color: hsl(var(--accent)); }
      .pr-badge-done { background: hsl(var(--success) / .14); color: hsl(var(--success)); }
      .pr-badge-err { background: hsl(var(--danger) / .12); color: hsl(var(--danger)); }
      .pr-badge-mute { background: hsl(var(--border) / .6); color: hsl(var(--text-muted)); }
      .pr-mini-btn, .pr-real-btn { border: 1.5px solid hsl(var(--border-strong)); background: transparent;
        color: hsl(var(--text-secondary)); border-radius: 9px; padding: 6px 12px; font-size: 12px; cursor: pointer; }
      .pr-real-btn { margin-top: 13px; width: 100%; padding: 11px; font-weight: 700;
        border-color: hsl(var(--accent)); color: hsl(var(--accent-text)); }
      .pr-real-btn:hover { background: hsl(var(--accent) / .08); }
      .pr-real-btn:disabled { opacity: .6; cursor: wait; }
      .pr-real-done { margin-top: 13px; font-size: 12px; font-weight: 600;
        color: hsl(var(--success-text)); }
      .pr-mission-foot { margin-top: 9px; }
      .pr-link { border: 0; background: none; padding: 0; cursor: pointer;
        font-size: 11.5px; color: hsl(var(--accent-text)); }
      .pr-link:hover { text-decoration: underline; }
      .pr-more-btn { display: block; margin: 4px auto 0; border: 1.5px solid hsl(var(--border-strong));
        background: transparent; color: hsl(var(--text-secondary)); border-radius: 9px;
        padding: 7px 14px; font-size: 12px; cursor: pointer; }
      .pr-more-btn:hover { color: hsl(var(--text)); border-color: hsl(var(--accent) / .5); }
      .pr-more-btn:disabled { opacity: .6; cursor: wait; }
      .pr-mission-err { font-size: 12px; color: hsl(var(--danger-text)); margin-bottom: 10px; }
      .pr-mchain { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 9px; }
      .pr-mstep { display: flex; gap: 8px; align-items: flex-start; padding: 9px 11px;
        border-radius: 11px; background: hsl(var(--bg) / .55); border: 1px solid hsl(var(--border)); }
      .pr-mstep-todo { opacity: .5; }
      .pr-mstep-ic { font-size: 13px; margin-top: 1px; }
      .pr-mstep-lb { font-size: 12px; font-weight: 700; color: hsl(var(--text)); }
      .pr-mstep-dt { font-size: 11px; color: hsl(var(--text-muted)); margin-top: 1px; }
      .pr-quality { margin-top: 11px; font-size: 11.5px; color: hsl(var(--text-muted)); }
      .pr-quality b { color: hsl(var(--text-secondary)); }
      .pr-preview { margin-top: 9px; font-size: 12px; }
      .pr-preview summary { cursor: pointer; color: hsl(var(--text-muted)); }
      .pr-preview-list { margin-top: 7px; display: flex; flex-direction: column; gap: 5px; }
      .pr-preview-row { display: flex; align-items: center; gap: 9px; color: hsl(var(--text-secondary)); }
      .pr-preview-name { font-weight: 600; max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
      .pr-preview-mail { color: hsl(var(--text-muted)); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
      .pr-preview-sort { margin-left: auto; font-size: 11px; color: hsl(var(--text-muted)); flex-shrink: 0; }
      .pr-preview-sort.is-new { color: hsl(var(--success-text)); }
    `;
    document.head.appendChild(s);
  },

  _fmtDate(iso) {
    try {
      return new Date(iso).toLocaleString('fr-FR',
        { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
    } catch (e) { return iso || ''; }
  },

  _esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    }[c]));
  },
};
