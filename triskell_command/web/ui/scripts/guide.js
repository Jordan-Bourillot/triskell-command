/* Le Guide — compagnon permanent de Triskell Command.
 *
 * Une barre discrète, toujours visible en bas de l'écran, qui répond en
 * continu aux trois questions qui perdent les gens :
 *   « Où suis-je ? »  ·  « Que vient-il de se passer ? »  ·  « Et maintenant ? »
 *
 * Principes :
 *  - UNE action recommandée à la fois, calculée sur l'état RÉEL de l'app
 *    (brouillons en attente, réponses à traiter, chasse en cours…),
 *    jamais un conseil générique.
 *  - Le Guide confirme ce qui vient d'être fait (il détecte les changements
 *    d'état : brouillon parti, prospects arrivés, chasse terminée…).
 *  - Il s'efface avec l'autonomie : accueil complet la première fois,
 *    conseils les premiers jours, simple fil d'état ensuite — et un mode
 *    réduit (pastille) pour ceux qui n'en veulent plus. Il ne disparaît
 *    jamais : il se fait juste plus petit.
 *  - Zéro clic nécessaire pour en profiter ; un seul clic pour le réduire.
 *
 * Aucune dépendance : il s'auto-branche sur App.show (sans le modifier
 * dans app.js) et se nourrit d'un seul endpoint léger (guide_snapshot).
 */

const Guide = {
  // ---------- état ----------
  snap: null,            // dernier instantané serveur
  prevSnap: null,
  view: null,
  eventMsg: null,        // confirmation éphémère ("✓ ...")
  eventTimer: null,
  pollTimer: null,
  _doneSeen: null,       // ids des missions terminées déjà confirmées
  collapsed: false,
  visits: 0,
  welcomed: false,

  LS: {
    collapsed: 'triskell.guide.collapsed',
    visits: 'triskell.guide.visits',
    lastDay: 'triskell.guide.lastday',
    welcomed: 'triskell.guide.welcomed',
  },

  // ---------- textes par écran : « tu es ici » + geste attendu ----------
  // Une ligne courte, concrète, dans la langue de tous les jours.
  VIEW_TEXTS: {
    morning:        { here: 'Ton tableau de bord du jour.' },
    prospection:    { here: 'Le point de départ : tout part d’ici.',
                      inview: 'Choisis une cible, remplis 2 champs, clique Lancer — je m’occupe du reste.' },
    prospects_crm:  { here: 'Ta base de prospects — tout atterrit ici, sans doublon.',
                      inview: 'Clique une ligne pour la fiche complète.' },
    obelisk:        { here: 'Recherche de créateurs (YouTube, Twitch…).',
                      inview: 'Lance une recherche par niche — les profils filent dans ta base.' },
    chasseur:       { here: 'Recherche de PME françaises par métier et zone.',
                      inview: 'À la fin : « Auto-Pilote » pour verser dans la base.' },
    chasseur_createurs: { here: 'Ancien outil créateurs — remplacé par Obélisk pour l’usage courant.',
                      inview: 'Pour un export Excel ponctuel uniquement. Sinon : Obélisk.' },
    prospecteur_google: { here: 'Recherche de commerces locaux via Google Maps.',
                      inview: 'À la fin : « Ajouter à mes prospects ».' },
    argus:          { here: 'Récupération de mails pros en masse (annuaires).' },
    eclaireur:      { here: 'Complète les fiches : retrouve les mails et téléphones manquants.' },
    autopilot:      { here: 'La machine qui écrit et envoie, depuis ta base.',
                      inview: 'Chaque maillon a son interrupteur Auto/Manuel.' },
    convoy:         { here: 'Campagne sur une liste que TU apportes (PDF, Excel…).',
                      inview: 'Suis les 5 étapes — je te tiens la porte à chacune.' },
    drafts:         { here: 'Les mails écrits par l’app, en attente de ton OK.',
                      inview: 'Lis → corrige si besoin → Approuver. L’envoi part aussitôt.' },
    replies:        { here: 'Les réponses des prospects, déjà triées.',
                      inview: 'Commence par les « Intéressé » — c’est là que ça se joue.' },
    mails:          { here: 'Ta boîte mail intégrée.' },
    funnel:         { here: 'Tes taux de transformation, étape par étape.' },
    revenue:        { here: 'Tes encaissements, toutes sources confondues.' },
    health:         { here: 'L’état de tes robots et de tes envois.' },
    catalogue:      { here: 'Ton catalogue de produits et d’offres.' },
    mail_templates: { here: 'Tes modèles de mails — l’app les remplit, ne les réécrit pas.' },
    config:         { here: 'Les réglages (comptes mail, clés, automatismes).' },
    clients:        { here: 'Tes projets clients en cours.' },
    clients_master: { here: 'Ton fichier clients (ceux qui ont déjà acheté).' },
    pixelpros:      { here: 'La chaîne de fabrication des sites Pixel Pros.' },
    phare:          { here: 'Le suivi SEO de tes sites.' },
    geo:            { here: 'Le GEO : faire citer tes sites par les IA (ChatGPT, Perplexity…).' },
    brain:          { here: 'Ta boîte à idées partagée avec Thomas.' },
    tutorial:       { here: 'La visite guidée complète.' },
    wow:            { here: 'Le suivi des demandes de sites Studio WoW, étape par étape.' },
    rankus:         { here: 'Le suivi des demandes SEO RankUs, étape par étape.' },
    lagriffe:       { here: 'Le suivi des demandes de sites Lagriffe, étape par étape.' },
    eliks:          { here: 'Eliks Studio — notre service de croissance sur les réseaux.' },
    delivery:       { here: 'Les kits envoyés automatiquement aux clients à la livraison.' },
    abtest:         { here: 'Tes tests A/B : deux versions d’un mail, la meilleure gagne.' },
    'pixelpros-affiliates': { here: 'Tes affiliés Pixel Pros et leurs commissions.' },
    prospect_timeline: { here: 'Toute l’histoire de ce prospect, dans l’ordre.' },
  },

  // ---------- init ----------
  init() {
    if (this._inited) return;
    this._inited = true;
    try {
      this.collapsed = localStorage.getItem(this.LS.collapsed) === '1';
      // Le niveau d'accompagnement compte des JOURS de visite distincts,
      // pas des rechargements de page (avant : 5 F5 = « habitué »).
      const today = new Date().toISOString().slice(0, 10);
      let visits = parseInt(localStorage.getItem(this.LS.visits) || '0', 10) || 0;
      if (localStorage.getItem(this.LS.lastDay) !== today) {
        visits += 1;
        localStorage.setItem(this.LS.visits, String(visits));
        localStorage.setItem(this.LS.lastDay, today);
      }
      this.visits = visits;
      this.welcomed = localStorage.getItem(this.LS.welcomed) === '1';
    } catch (e) { this.visits = 1; /* stockage indisponible : mode sans mémoire */ }

    this._injectStyles();
    this._mount();
    this.view = (typeof App !== 'undefined' && App.currentView) || 'morning';
    this._renderBar();

    // Premier instantané + polling (en pause quand l'onglet est caché)
    this._poll();
    this.pollTimer = setInterval(() => {
      if (!document.hidden) this._poll();
    }, 25000);
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden) this._poll();
    });

    // Accueil de la toute première fois — attend que les éventuelles
    // fenêtres de premier démarrage (onboarding) soient refermées.
    if (!this.welcomed && !this.collapsed) this._welcomeWhenClear(0);
  },

  onViewChange(viewId) {
    this.view = viewId;
    this._renderBar();
    this._poll(); // l'état a pu changer suite à une action
  },

  /** Confirmation instantanée depuis n'importe quel écran :
   *  Guide.say('✓ Mission lancée'). */
  say(msg, ms = 6000) {
    this.eventMsg = msg;
    this._renderBar();
    if (this.eventTimer) clearTimeout(this.eventTimer);
    this.eventTimer = setTimeout(() => {
      this.eventMsg = null;
      this._renderBar();
    }, ms);
  },

  // ---------- niveau d'accompagnement ----------
  // découverte : statut + action + conseil d'écran (les ~5 premières visites)
  // habitué    : statut + action
  // (réduit    : pastille — choix utilisateur, mémorisé)
  level() {
    return this.visits <= 5 ? 'decouverte' : 'habitue';
  },

  // ---------- instantané + détection de « ce qui vient de se passer » ----------
  async _poll() {
    if (typeof App === 'undefined' || !App.api ||
        typeof App.api.guide_snapshot !== 'function') return;
    let s = null;
    try { s = await App.api.guide_snapshot({}); } catch (e) { return; }
    if (!s || !s.ok) return;
    this.prevSnap = this.snap;
    this.snap = s;
    const evt = this._detectEvent(this.prevSnap, s);
    if (evt) this.say(evt);
    else this._renderBar();
  },

  _detectEvent(prev, cur) {
    if (!cur) return null;
    // Fins de chasse : le serveur renvoie les missions terminées des
    // 2 dernières heures (recent_done) — fiable même si une 2e chasse
    // tourne encore. Au premier instantané on NOTE sans annoncer (vieilles
    // fins). Si le champ n'existe pas (vieux serveur), repli défensif sur
    // la comparaison d'instantanés.
    if (Array.isArray(cur.recent_done)) {
      if (!this._doneSeen) {
        this._doneSeen = new Set(
          cur.recent_done.map(m => m && m.id).filter(Boolean));
      } else {
        for (const m of cur.recent_done) {
          if (!m || !m.id || this._doneSeen.has(m.id)) continue;
          this._doneSeen.add(m.id);
          if (m.status === 'error') {
            return `⚠ Une prospection s’est arrêtée en erreur — détails sur l’écran Prospection.`;
          }
          if (m.status === 'handed') {
            return (typeof m.pushed === 'number')
              ? `✓ Chasse terminée — ${m.pushed} prospect(s) versés dans ta base.`
              : '✓ Chasse terminée — les prospects sont dans ta base.';
          }
          // Statut inconnu ou abandon volontaire → pas de fausse fanfare.
        }
      }
    } else if (prev) {
      const prevActive = (prev.missions || []).filter(m => m.status === 'hunting' || m.status === 'handing');
      for (const pm of prevActive) {
        const now = (cur.missions || []).find(m => m.id === pm.id);
        if (now && now.status === 'handed') {
          const c = now.counts || {};
          return `✓ Chasse terminée — ${c.pushed || c.found || 0} prospect(s) versés dans ta base.`;
        }
        if (now && now.status === 'error') {
          return `⚠ Une prospection s’est arrêtée en erreur — détails sur l’écran Prospection.`;
        }
      }
    }
    if (!prev) return null;
    const d = (k) => (cur[k] == null || prev[k] == null) ? 0 : cur[k] - prev[k];
    // La baisse du compteur peut venir d'un envoi COMME d'un rejet → on
    // confirme le traitement, pas l'envoi.
    if (d('drafts_pending') < 0) return '✓ Brouillon traité.';
    if (d('replies_unhandled') < 0) return '✓ Réponse traitée. Au suivant !';
    if (d('prospects_total') > 0) return `✓ ${d('prospects_total')} prospect(s) de plus dans ta base.`;
    if (!prev.autopilot_enabled && cur.autopilot_enabled) {
      return '✓ Auto-pilote allumé — il va écrire aux prospects de la base.';
    }
    if (prev.autopilot_enabled && !cur.autopilot_enabled) {
      return 'Auto-pilote éteint. Les prospects attendent dans la base.';
    }
    return null;
  },

  // La base partagée est injoignable quand le serveur renvoie « je ne sais
  // pas » (null) sur TOUS les compteurs. Dans ce cas on ne recommande rien :
  // conseiller « lance une prospection » sur des chiffres absents serait faux.
  _dbDown() {
    const s = this.snap;
    return !!s && s.prospects_total == null && s.drafts_pending == null
        && s.replies_unhandled == null;
  },

  // ---------- LA recommandation : une seule, calculée, jamais générique ----------
  // Renvoie {label, view, why} — ou null (= rien d'urgent, statut suffit).
  _recommend() {
    const s = this.snap;
    if (!s) return null;
    if (this._dbDown()) return null;
    const w = s.workers || {};
    if ((w.error || 0) > 0) {
      return { label: 'Voir Santé', view: 'health',
               why: `${w.error} robot(s) arrêté(s)` };
    }
    if ((s.replies_unhandled || 0) > 0) {
      return { label: `Traiter ${s.replies_unhandled} réponse(s)`, view: 'replies',
               why: 'des prospects t’ont répondu' };
    }
    if ((s.drafts_pending || 0) > 0) {
      return { label: `Valider ${s.drafts_pending} brouillon(s)`, view: 'drafts',
               why: 'des mails attendent ton OK' };
    }
    const active = (s.missions || []).find(m => m.status === 'hunting' || m.status === 'handing');
    if (active) {
      return { label: 'Suivre la chasse', view: 'prospection',
               why: `${active.progress || 0}% — je te préviens à la fin`,
               soft: true };
    }
    if (!s.autopilot_enabled && (s.prospects_new || 0) > 0) {
      return { label: 'Allumer l’Auto-pilote', view: 'prospection',
               why: `${s.prospects_new} prospect(s) attendent qu’on leur écrive` };
    }
    if ((w.warning || 0) > 0) {
      return { label: 'Jeter un œil à Santé', view: 'health',
               why: `${w.warning} robot(s) à surveiller`, soft: true };
    }
    // Strict : si le compteur est inconnu (null), on ne conclut rien.
    if (s.prospects_new === 0) {
      return { label: 'Lancer une prospection', view: 'prospection',
               why: 'la machine est prête, il ne manque que des cibles' };
    }
    return null;
  },

  // ---------- rendu ----------
  _mount() {
    if (document.getElementById('guide-bar')) return;
    const el = document.createElement('div');
    el.id = 'guide-bar';
    document.body.appendChild(el);
    // Ancré au CONTENU (pas à la fenêtre) : jamais à cheval sur la barre
    // latérale, quelle que soit la taille d'écran ou son repli.
    this._position();
    window.addEventListener('resize', () => this._position());
    // Suit le repli de la sidebar SANS minuteur permanent : on observe la
    // taille de la zone de contenu (composant global, jamais démonté →
    // l'observateur vit aussi longtemps que la page).
    const content = document.getElementById('content');
    if (typeof ResizeObserver !== 'undefined' && content) {
      this._resizeObs = new ResizeObserver(() => this._position());
      this._resizeObs.observe(content);
    } else {
      // Très vieux navigateur : repli sur l'ancien minuteur.
      setInterval(() => this._position(), 2000);
    }
  },

  _position() {
    const el = document.getElementById('guide-bar');
    if (!el) return;
    const content = document.getElementById('content');
    if (!content) return;
    const r = content.getBoundingClientRect();
    if (r.width < 200) return;
    el.style.left = Math.round(r.left + r.width / 2) + 'px';
    el.style.maxWidth = Math.min(720, r.width - 24) + 'px';
  },

  _renderBar() {
    const el = document.getElementById('guide-bar');
    if (!el) return;

    if (this.collapsed) {
      const rec = this._recommend();
      const urgent = rec && !rec.soft;
      el.className = 'guide-collapsed' + (urgent ? ' guide-pulse' : '');
      el.innerHTML = `
        <button class="guide-dot" title="${urgent ? this._esc(rec.label) : 'Réafficher le guide'}"
                aria-label="Réafficher le guide">🧭${urgent ? '<span class="guide-dot-badge"></span>' : ''}</button>`;
      el.querySelector('.guide-dot').onclick = () => this._setCollapsed(false);
      return;
    }

    const vt = this.VIEW_TEXTS[this.view] || {};
    const here = vt.here || 'Triskell Command.';
    const rec = this._recommend();
    const lvl = this.level();

    // Zone du milieu : confirmation éphémère > base injoignable > statut
    let mid;
    if (this.eventMsg) {
      mid = `<span class="guide-event">${this._esc(this.eventMsg)}</span>`;
    } else if (this._dbDown()) {
      mid = `<span class="guide-status">Connexion à la base impossible — les chiffres reviennent dès qu’elle répond.</span>`;
    } else if (rec && rec.view === this.view && vt.inview) {
      mid = `<span class="guide-status">${this._esc(vt.inview)}</span>`;
    } else {
      mid = `<span class="guide-status">${this._esc(here)}</span>`;
    }

    // Chip d'action : seulement si elle mène AILLEURS (sur place, le texte suffit)
    let chip = '';
    if (rec && rec.view !== this.view) {
      chip = `
        <button class="guide-chip ${rec.soft ? 'guide-chip-soft' : ''}"
                data-go="${this._esc(rec.view)}"
                title="${this._esc(rec.why || '')}">
          ${this._esc(rec.label)} →
        </button>`;
    } else if (rec && rec.view === this.view && !this.eventMsg && rec.why) {
      chip = `<span class="guide-why">${this._esc(rec.why)}</span>`;
    }

    const tip = (lvl === 'decouverte' && vt.inview && (!rec || rec.view !== this.view))
      ? `<div class="guide-tipline">💡 ${this._esc(vt.inview)}</div>` : '';

    el.className = 'guide-open' + (lvl === 'decouverte' ? ' guide-deux-lignes' : '');
    el.innerHTML = `
      <div class="guide-row" role="status" aria-live="polite">
        <span class="guide-where" title="Tu es ici">🧭</span>
        ${mid}
        ${chip}
        <button class="guide-talk" title="Parler à Claude, ton copilote"
                aria-label="Parler au copilote">💬<span class="copilot-badge-dot hidden"></span></button>
        <button class="guide-min" title="Réduire le guide (il reste en pastille)"
                aria-label="Réduire le guide">▾</button>
      </div>
      ${tip}`;

    const go = el.querySelector('.guide-chip[data-go]');
    if (go) go.onclick = () => {
      const v = go.dataset.go;
      if (typeof App !== 'undefined' && App.show) App.show(v);
    };
    // Le copilote : un clic, depuis n'importe quel écran. La pastille
    // s'allume si la veille a un conseil OU si le guetteur a déposé des
    // messages depuis la dernière ouverture du volet (copilot_unseen).
    const talk = el.querySelector('.guide-talk');
    if (talk) {
      if (typeof Copilot !== 'undefined' && Copilot.toggle) {
        talk.onclick = () => Copilot.toggle();
        const unseen = (this.snap && this.snap.copilot_unseen) || 0;
        if (unseen > 0 ||
            (typeof Claude !== 'undefined' && Claude.isAttention)) {
          const d = talk.querySelector('.copilot-badge-dot');
          if (d) d.classList.remove('hidden');
        }
      } else {
        talk.style.display = 'none';
      }
    }
    el.querySelector('.guide-min').onclick = () => this._setCollapsed(true);
  },

  _setCollapsed(v) {
    this.collapsed = !!v;
    try { localStorage.setItem(this.LS.collapsed, v ? '1' : '0'); } catch (e) {}
    this._renderBar();
    if (!v) this._poll();
  },

  // ---------- accueil de la toute première fois ----------
  _welcomeWhenClear(tries) {
    // Si une fenêtre plein écran est VRAIMENT ouverte (onboarding, visite,
    // appel…), on attend. L'app garde plusieurs overlays cachés en
    // permanence dans la page → on ne compte que les visibles.
    const overlayOpen = [...document.querySelectorAll('.fixed.inset-0')]
      .some(o => !o.classList.contains('hidden')
              && getComputedStyle(o).display !== 'none');
    if (overlayOpen) {
      if (tries < 60) {
        return setTimeout(() => this._welcomeWhenClear(tries + 1), 2000);
      }
      // ~2 min d'attente : on n'impose RIEN par-dessus une fenêtre ouverte.
      // La carte retentera sa chance à la prochaine session.
      return;
    }
    if (this.welcomed) return;
    const el = document.getElementById('guide-bar');
    if (!el) return;
    const card = document.createElement('div');
    card.id = 'guide-welcome';
    card.innerHTML = `
      <div class="guide-w-title">👋 Bienvenue. Je suis ton guide.</div>
      <div class="guide-w-body">
        Je reste en bas de l’écran, tout le temps. Je te dis où tu es,
        ce qui vient de se passer, et <b>la prochaine action utile</b> —
        tu n’auras jamais à te demander « et maintenant ? ».
      </div>
      <div class="guide-w-actions">
        <button class="btn btn-primary text-xs" id="guide-w-go">C’est parti, guide-moi</button>
        <button class="btn btn-secondary text-xs" id="guide-w-tour">La visite complète d’abord</button>
      </div>`;
    document.body.appendChild(card);
    const close = () => {
      this.welcomed = true;
      try { localStorage.setItem(this.LS.welcomed, '1'); } catch (e) {}
      card.remove();
    };
    card.querySelector('#guide-w-go').onclick = () => {
      close();
      const rec = this._recommend();
      if (typeof App !== 'undefined' && App.show) {
        App.show(rec ? rec.view : 'prospection');
      }
    };
    card.querySelector('#guide-w-tour').onclick = () => {
      close();
      if (typeof Tutorial !== 'undefined' && Tutorial.open) {
        Tutorial.open();
      } else if (typeof Toast !== 'undefined') {
        Toast.info('La visite guidée n’est pas disponible pour le moment — je te guide en direct depuis cette barre.');
      }
    };
  },

  // ---------- styles ----------
  _injectStyles() {
    if (document.getElementById('guide-styles')) return;
    const s = document.createElement('style');
    s.id = 'guide-styles';
    s.textContent = `
      #guide-bar {
        position: fixed; z-index: 60;
        left: 50%; transform: translateX(-50%);
        bottom: calc(12px + env(safe-area-inset-bottom, 0px));
        width: max-content;
        max-width: min(720px, calc(100vw - 170px));
        display: flex; flex-direction: column; align-items: stretch;
        pointer-events: none;
      }
      #guide-bar > * { pointer-events: auto; }
      .guide-open .guide-row {
        display: flex; align-items: center; gap: 10px;
        padding: 9px 14px;
        background: hsl(var(--surface-elevated, var(--surface)) / .92);
        backdrop-filter: blur(10px);
        border: 1px solid hsl(var(--border-strong));
        border-radius: 999px;
        box-shadow: 0 4px 18px rgba(15,23,42,.14);
        font-size: 12.5px; color: hsl(var(--text-secondary));
        white-space: nowrap;
      }
      .guide-where { font-size: 14px; flex-shrink: 0; }
      .guide-status, .guide-event {
        overflow: hidden; text-overflow: ellipsis; min-width: 0;
      }
      .guide-event { color: hsl(var(--success)); font-weight: 600;
                     animation: guideFade .3s ease-out; }
      .guide-why { color: hsl(var(--text-muted)); font-size: 12px; flex-shrink: 0; }
      .guide-chip {
        flex-shrink: 0; border: 0; cursor: pointer;
        background: hsl(var(--accent)); color: #fff;
        font-size: 12px; font-weight: 700;
        padding: 5px 12px; border-radius: 999px;
        transition: transform .12s, box-shadow .12s;
      }
      .guide-chip:hover { transform: translateY(-1px);
                          box-shadow: 0 4px 12px hsl(var(--accent) / .4); }
      .guide-chip-soft { background: hsl(var(--accent) / .14);
                         color: hsl(var(--accent)); }
      .guide-min {
        flex-shrink: 0; border: 0; background: transparent; cursor: pointer;
        color: hsl(var(--text-muted)); font-size: 12px; padding: 2px 4px;
        border-radius: 6px;
      }
      .guide-min:hover { background: hsl(var(--border) / .5); }
      .guide-talk {
        position: relative; flex-shrink: 0; border: 0; cursor: pointer;
        background: hsl(var(--accent) / .12); color: hsl(var(--accent));
        font-size: 13px; line-height: 1; padding: 5px 9px;
        border-radius: 999px; transition: background .12s, transform .12s;
      }
      .guide-talk:hover { background: hsl(var(--accent) / .22); transform: translateY(-1px); }
      .guide-talk .copilot-badge-dot {
        position: absolute; top: -2px; right: -2px;
        width: 9px; height: 9px; border-radius: 50%;
        background: #ef4444; border: 2px solid hsl(var(--surface));
      }
      .guide-tipline {
        margin-top: 6px; text-align: center;
        font-size: 12px; color: hsl(var(--text-muted));
        background: hsl(var(--surface) / .85); backdrop-filter: blur(8px);
        border: 1px dashed hsl(var(--border));
        border-radius: 999px; padding: 5px 14px;
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
      }
      .guide-collapsed .guide-dot {
        position: relative; width: 34px; height: 34px; border-radius: 50%;
        border: 1px solid hsl(var(--border-strong));
        background: hsl(var(--surface-elevated, var(--surface)) / .95);
        box-shadow: 0 3px 10px rgba(15,23,42,.16);
        cursor: pointer; font-size: 15px; line-height: 1;
      }
      .guide-dot-badge {
        position: absolute; top: -2px; right: -2px;
        width: 10px; height: 10px; border-radius: 50%;
        background: hsl(var(--accent));
        border: 2px solid hsl(var(--surface));
      }
      .guide-pulse .guide-dot { animation: guidePulse 2.2s ease-in-out infinite; }
      #guide-welcome {
        position: fixed; z-index: 61;
        left: 50%; transform: translateX(-50%);
        bottom: calc(64px + env(safe-area-inset-bottom, 0px));
        width: min(440px, calc(100vw - 32px));
        background: hsl(var(--surface-elevated, var(--surface)));
        border: 1px solid hsl(var(--border-strong));
        border-radius: 16px; padding: 16px;
        box-shadow: 0 12px 40px rgba(15,23,42,.22);
        animation: guideRise .4s cubic-bezier(.16,1,.3,1);
      }
      .guide-w-title { font-weight: 800; font-size: 14.5px; margin-bottom: 6px;
                       color: hsl(var(--text)); }
      .guide-w-body { font-size: 12.5px; line-height: 1.55;
                      color: hsl(var(--text-secondary)); margin-bottom: 12px; }
      .guide-w-actions { display: flex; gap: 8px; flex-wrap: wrap; }
      @keyframes guideFade { from { opacity: 0; } to { opacity: 1; } }
      @keyframes guideRise { from { opacity: 0; transform: translate(-50%, 10px); }
                             to { opacity: 1; transform: translate(-50%, 0); } }
      @keyframes guidePulse {
        0%,100% { box-shadow: 0 3px 10px rgba(15,23,42,.16); }
        50% { box-shadow: 0 0 0 7px hsl(var(--accent) / .18); }
      }
      @media (max-width: 640px) {
        .guide-tipline { display: none; }
      }
    `;
    document.head.appendChild(s);
  },

  _esc(x) {
    return String(x == null ? '' : x).replace(/[&<>"']/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    }[c]));
  },
};

// ---------- auto-branchement (zéro modification d'app.js) ----------
(function () {
  'use strict';
  // Se greffe sur App.show pour suivre la navigation, sans en changer
  // le comportement.
  try {
    if (typeof App !== 'undefined' && typeof App.show === 'function'
        && !App.__guideWrapped) {
      const orig = App.show.bind(App);
      App.show = function (viewId, params) {
        const r = orig(viewId, params);
        try { Guide.onViewChange(viewId); } catch (e) { /* jamais bloquant */ }
        return r;
      };
      App.__guideWrapped = true;
    }
  } catch (e) { /* le Guide ne casse JAMAIS l'app */ }

  const boot = () => { try { Guide.init(); } catch (e) { console.warn('guide:', e); } };
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => setTimeout(boot, 400));
  } else {
    setTimeout(boot, 400);
  }
})();
