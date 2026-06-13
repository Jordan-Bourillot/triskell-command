/* Perceval — le coéquipier incarné de Triskell Command.
 *
 * Il remplace l'ancienne barre « Guide » : même intelligence (un seul
 * endpoint léger guide_snapshot, UNE action recommandée calculée sur
 * l'état réel, confirmations de ce qui vient de se passer), mais un
 * corps : un petit écu de chevalier qui vit en bas à droite de l'écran,
 * avec des humeurs visibles et une bulle de parole.
 *
 * Ses humeurs (data-mood sur le host) :
 *   sommeil   — rien à dire depuis un moment, il se repose
 *   observe   — état normal : il regarde, prêt à aider
 *   reflechit — il vient de changer d'écran avec toi, il regarde
 *   parle     — il a quelque chose à te dire (bulle fraîche)
 *   alerte    — un vrai pépin (robot en panne, base injoignable)
 *
 * Sa voix : optionnelle (bouton sur la bulle, mémorisé). Quand elle est
 * allumée, il dit à voix haute ses confirmations (✓/⚠) et le bonjour du
 * matin — jamais les statuts passifs (sinon il serait insupportable).
 *
 * Savoir-vivre : il ne répète pas deux fois la même phrase à voix haute,
 * ne parle pas par-dessus lui-même, et s'efface quand le volet de
 * discussion est ouvert.
 *
 * Compat : window.Guide pointe vers lui (Guide.say / Guide.onViewChange
 * sont utilisés par d'autres écrans). Il ne casse JAMAIS l'app.
 */

const Perceval = {
  name: 'Perceval',

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
  met: false,            // a déjà rencontré Perceval (carte de présentation)
  voiceOn: false,
  mood: 'observe',
  _speaking: false,
  _lastSpoken: '',
  _lastSpokenAt: 0,
  _lastActivity: Date.now(),
  _thinkTimer: null,
  _idleTimer: null,
  _greeted: false,

  LS: {
    collapsed: 'triskell.guide.collapsed',   // clés partagées avec l'ancien
    visits: 'triskell.guide.visits',         // Guide : on hérite des choix
    lastDay: 'triskell.guide.lastday',
    met: 'triskell.perceval.met',
    voice: 'triskell.perceval.voice',
    greetDay: 'triskell.perceval.greetday',
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
      // pas des rechargements de page.
      const today = new Date().toISOString().slice(0, 10);
      let visits = parseInt(localStorage.getItem(this.LS.visits) || '0', 10) || 0;
      if (localStorage.getItem(this.LS.lastDay) !== today) {
        visits += 1;
        localStorage.setItem(this.LS.visits, String(visits));
        localStorage.setItem(this.LS.lastDay, today);
      }
      this.visits = visits;
      this.met = localStorage.getItem(this.LS.met) === '1';
      this.voiceOn = localStorage.getItem(this.LS.voice) === '1';
    } catch (e) { this.visits = 1; /* stockage indisponible : mode sans mémoire */ }

    this._injectStyles();
    this._mount();
    this.view = (typeof App !== 'undefined' && App.currentView) || 'morning';
    this._renderBubble();

    // Premier instantané + polling (en pause quand l'onglet est caché)
    this._poll();
    this.pollTimer = setInterval(() => {
      if (!document.hidden) this._poll();
    }, 25000);
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden) this._poll();
    });

    // Présentation de la toute première fois — attend que les éventuelles
    // fenêtres de premier démarrage soient refermées.
    if (!this.met && !this.collapsed) this._meetWhenClear(0);
    this._armIdle();
  },

  onViewChange(viewId) {
    this.view = viewId;
    this._wake();
    this._clearSpot(); // l'écran change : le doigt pointé n'a plus de cible
    // Il « regarde » ton nouvel écran un court instant.
    this._setMood('reflechit');
    if (this._thinkTimer) clearTimeout(this._thinkTimer);
    this._thinkTimer = setTimeout(() => this._refreshMood(), 900);
    this._trackWandering(viewId);
    this._maybeIntroduceView(viewId);
    this._renderBubble();
    this._poll(); // l'état a pu changer suite à une action
  },

  /** Confirmation instantanée depuis n'importe quel écran :
   *  Perceval.say('✓ Mission lancée')  (alias : Guide.say). */
  say(msg, ms = 6000, opts = {}) {
    this.eventMsg = msg;
    // opts.choices = [{label, view}] : des boutons sous le message — utilisé
    // par la main tendue (« tu cherches quelque chose ? ») pour proposer
    // des destinations cliquables au lieu d'une question ouverte.
    this.eventChoices = Array.isArray(opts.choices) ? opts.choices : null;
    this._wake();
    this._setMood('parle');
    this._renderBubble();
    if (this.eventTimer) clearTimeout(this.eventTimer);
    this.eventTimer = setTimeout(() => {
      this.eventMsg = null;
      this.eventChoices = null;
      this._refreshMood();
      this._renderBubble();
    }, ms);
    // À voix haute : les confirmations et alertes uniquement (jamais les
    // statuts passifs), ou sur demande explicite (opts.speak).
    const spoken = /^[✓⚠]/.test(String(msg || ''));
    if (opts.speak || spoken) this._speak(msg);
  },

  // ---------- niveau d'accompagnement ----------
  // découverte : statut + action + conseil d'écran (les ~5 premiers jours)
  // habitué    : statut + action
  // (réduit    : mini-Perceval — choix utilisateur, mémorisé)
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
    else { this._refreshMood(); this._renderBubble(); }
    // Bonjour du jour : une fois le premier instantané en main.
    this._maybeGreet();
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
    if (d('geo_pending_fixes') < 0) return '✓ Amélioration GEO appliquée — le site se met à jour.';
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
    if ((s.geo_pending_fixes || 0) > 0) {
      return { label: `Appliquer ${s.geo_pending_fixes} amélioration(s) GEO`,
               view: 'geo',
               why: 'des corrections attendent ton OK pour être citées par les IA',
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

  // ---------- le bonjour du jour ----------
  _maybeGreet() {
    if (this._greeted || !this.snap || this.collapsed) return;
    let today = '';
    try {
      today = new Date().toISOString().slice(0, 10);
      if (localStorage.getItem(this.LS.greetDay) === today) { this._greeted = true; return; }
    } catch (e) { /* sans stockage : on salue quand même, une fois par session */ }
    if (!this.met) return; // la carte de présentation passe d'abord
    this._greeted = true;
    try { localStorage.setItem(this.LS.greetDay, today); } catch (e) {}
    const txt = this._greetText();
    if (txt) this.say(txt, 12000, { speak: true });
  },

  _greetText() {
    const s = this.snap;
    if (!s || this._dbDown()) return null;
    const prenom = (typeof App !== 'undefined' && App.currentUser
                    && App.currentUser.first_name) || 'Jordan';
    const h = new Date().getHours();
    const hello = h >= 18 ? `Bonsoir ${prenom}.` : `Salut ${prenom}.`;
    const w = s.workers || {};
    let info;
    if ((w.error || 0) > 0) {
      info = `${w.error} robot(s) en panne — on regarde ça en premier ?`;
    } else if ((s.replies_unhandled || 0) > 0) {
      info = `${s.replies_unhandled} réponse(s) de prospects t’attendent — c’est le plus important.`;
    } else if ((s.drafts_pending || 0) > 0) {
      info = `${s.drafts_pending} mail(s) attendent ton OK pour partir.`;
    } else {
      const active = (s.missions || []).find(m => m.status === 'hunting' || m.status === 'handing');
      if (active) {
        info = `La chasse tourne (${active.progress || 0}%) — je te préviens à la fin.`;
      } else if ((s.geo_pending_fixes || 0) > 0) {
        info = `${s.geo_pending_fixes} amélioration(s) GEO attendent ton OK sur l’écran GEO.`;
      } else if (!s.autopilot_enabled && (s.prospects_new || 0) > 0) {
        info = `${s.prospects_new} prospect(s) attendent qu’on leur écrive.`;
      } else {
        info = 'Rien d’urgent : la machine tourne. Je suis là si besoin.';
      }
    }
    return `${hello} ${info}`;
  },

  // ---------- l'accueil des écrans inconnus (assistance de débutant) ----------
  // À la PREMIÈRE visite d'un écran d'action, il se présente : à quoi sert
  // l'écran, et l'invitation à lui parler. Une fois par écran, pour toujours.
  _maybeIntroduceView(viewId) {
    if (!this.met || this.collapsed || this.eventMsg) return;
    const vt = this.VIEW_TEXTS[viewId] || {};
    if (!vt.here || !vt.inview) return; // réservé aux écrans d'action
    let seen = {};
    try { seen = JSON.parse(localStorage.getItem('triskell.perceval.seenviews') || '{}'); } catch (e) {}
    if (seen[viewId]) return;
    seen[viewId] = 1;
    try { localStorage.setItem('triskell.perceval.seenviews', JSON.stringify(seen)); } catch (e) {}
    this.say(`Première fois ici ? ${vt.here} Dis-moi ce que tu veux faire — je peux le faire pour toi, ou te montrer.`, 9000);
  },

  // ---------- la main tendue quand on tourne en rond ----------
  // 4 écrans différents en moins de 25 s = il cherche quelque chose.
  // Savoir-vivre : 1 proposition par heure max ; ignorée 2 fois de suite
  // → silence pendant 7 jours.
  _trackWandering(viewId) {
    const now = Date.now();
    this._navLog = (this._navLog || []).filter(e => now - e.t < 25000);
    const last = this._navLog[this._navLog.length - 1];
    if (!last || last.v !== viewId) this._navLog.push({ v: viewId, t: now });
    const distinct = new Set(this._navLog.map(e => e.v));
    if (distinct.size < 4) return;
    this._navLog = [];
    try {
      const lastAt = parseInt(localStorage.getItem('triskell.perceval.wander.last') || '0', 10) || 0;
      if (now - lastAt < 3600 * 1000) return;
      let ignored = parseInt(localStorage.getItem('triskell.perceval.wander.ignored') || '0', 10) || 0;
      // La main tendue précédente n'a jamais été saisie → on le note.
      if (localStorage.getItem('triskell.perceval.wander.pending') === '1') {
        ignored += 1;
        localStorage.setItem('triskell.perceval.wander.ignored', String(ignored));
      }
      if (ignored >= 2) {
        const mutedAt = parseInt(localStorage.getItem('triskell.perceval.wander.muted') || '0', 10) || 0;
        if (!mutedAt) localStorage.setItem('triskell.perceval.wander.muted', String(now));
        if (now - (mutedAt || now) < 7 * 24 * 3600 * 1000) return;
        // 7 jours passés : on repart de zéro, il a droit à une nouvelle chance.
        localStorage.setItem('triskell.perceval.wander.ignored', '0');
        localStorage.removeItem('triskell.perceval.wander.muted');
      }
      localStorage.setItem('triskell.perceval.wander.last', String(now));
      localStorage.setItem('triskell.perceval.wander.pending', '1');
    } catch (e) { /* sans stockage, on propose quand même */ }
    this.say('Tu cherches quelque chose ? Dis-le-moi — ou choisis :', 16000, {
      choices: [
        { label: '🔎 Trouver des clients', view: 'prospection' },
        { label: '↩ Lire mes réponses',    view: 'replies' },
        { label: '📊 Voir mes chiffres',   view: 'funnel' },
      ],
    });
  },

  /** L'utilisateur a saisi la main tendue (il m'a parlé) : on oublie tout. */
  _wanderReward() {
    try {
      localStorage.setItem('triskell.perceval.wander.pending', '0');
      localStorage.setItem('triskell.perceval.wander.ignored', '0');
      localStorage.removeItem('triskell.perceval.wander.muted');
    } catch (e) {}
  },

  // ---------- pointer du doigt (guidage dans l'écran) ----------
  /** [GUIDE] du copilote : emmène sur l'écran si besoin, retrouve
   *  l'élément par son TEXTE VISIBLE, le fait briller avec la consigne
   *  à côté. Dégrade proprement : introuvable → il le dit en mots. */
  pointAt(g) {
    if (!g || !g.find) return;
    const wanted = String(g.view || '').trim();
    if (wanted && typeof App !== 'undefined' && App.show
        && App.currentView !== wanted) {
      try { App.show(wanted); } catch (e) { /* l'écran viendra, ou pas */ }
    }
    this._clearSpot();
    this._spotTry(String(g.find), String(g.note || ''), 0);
  },

  _spotTry(find, note, attempt) {
    const el = this._findByText(find);
    if (el) { this._spotlight(el, note); return; }
    if (attempt >= 8) { // ~3,6 s : l'écran est rendu, l'élément n'y est pas
      this.say(`Je n’ai pas retrouvé « ${find} » sur l’écran — il a peut-être changé de nom. Redemande-moi, ou décris-moi ce que tu vois.`, 8000);
      return;
    }
    this._spotTimer = setTimeout(() => this._spotTry(find, note, attempt + 1), 450);
  },

  _norm(s) {
    return String(s || '').toLowerCase()
      .normalize('NFD').replace(/[̀-ͯ]/g, '')
      .replace(/\s+/g, ' ').trim();
  },

  _findByText(find) {
    const target = this._norm(find);
    if (!target) return null;
    const sel = 'button, a, [role="button"], summary, label, th, [data-view], input[type="submit"]';
    const cands = document.querySelectorAll(sel);
    let best = null, bestLen = Infinity;
    for (const el of cands) {
      if (el.closest('#perceval-host') || el.closest('#copilot-panel')) continue;
      const r = el.getBoundingClientRect();
      if (r.width < 4 || r.height < 4) continue; // invisible ou replié
      const txt = this._norm(el.textContent || el.value);
      if (!txt || txt.length > 160) continue;
      if (txt === target) return el; // libellé exact → gagné
      if (txt.includes(target) && txt.length < bestLen) { best = el; bestLen = txt.length; }
    }
    return best;
  },

  _spotlight(el, note) {
    try { el.scrollIntoView({ block: 'center', behavior: 'smooth' }); } catch (e) {}
    el.classList.add('pv-spot');
    const tag = document.createElement('div');
    tag.id = 'pv-spot-note';
    tag.textContent = `👉 ${note || 'C’est ici.'}`;
    document.body.appendChild(tag);
    const place = () => {
      const r = el.getBoundingClientRect();
      tag.style.left = Math.max(8, Math.min(window.innerWidth - tag.offsetWidth - 8, r.left)) + 'px';
      tag.style.top = Math.max(8, r.top - tag.offsetHeight - 10) + 'px';
    };
    this._spotEl = el;
    this._spotPlace = place;
    setTimeout(place, 60);
    setTimeout(place, 420); // après le défilement doux
    window.addEventListener('scroll', place, { passive: true, capture: true });
    window.addEventListener('resize', place);
    // Un clic n'importe où (y compris sur la cible) éteint le projecteur.
    this._spotCleanup = () => this._clearSpot();
    setTimeout(() => document.addEventListener('click', this._spotCleanup,
      { once: true, capture: true }), 400);
    this._spotAutoOff = setTimeout(() => this._clearSpot(), 18000);
  },

  _clearSpot() {
    if (this._spotTimer) { clearTimeout(this._spotTimer); this._spotTimer = null; }
    if (this._spotAutoOff) { clearTimeout(this._spotAutoOff); this._spotAutoOff = null; }
    if (this._spotPlace) {
      window.removeEventListener('scroll', this._spotPlace, { capture: true });
      window.removeEventListener('resize', this._spotPlace);
      this._spotPlace = null;
    }
    if (this._spotCleanup) {
      document.removeEventListener('click', this._spotCleanup, { capture: true });
      this._spotCleanup = null;
    }
    if (this._spotEl) { this._spotEl.classList.remove('pv-spot'); this._spotEl = null; }
    const tag = document.getElementById('pv-spot-note');
    if (tag) tag.remove();
  },

  // ---------- la voix ----------
  _speak(text) {
    if (!this.voiceOn) return;
    try {
      if (!('speechSynthesis' in window)) return;
      const t = String(text == null ? '' : text)
        .replace(/[✓⚠👋🧭💬]/g, '').replace(/\s+/g, ' ').trim();
      if (!t) return;
      // Anti-bégaiement : jamais deux fois la même phrase en moins de 30 s.
      const now = Date.now();
      if (t === this._lastSpoken && (now - this._lastSpokenAt) < 30000) return;
      this._lastSpoken = t;
      this._lastSpokenAt = now;
      window.speechSynthesis.cancel(); // il ne parle pas par-dessus lui-même
      const u = new SpeechSynthesisUtterance(t);
      u.lang = 'fr-FR'; u.rate = 1.0; u.pitch = 0.9; // timbre posé
      u.onstart = () => { this._speaking = true; this._applyMood(); };
      u.onend = () => { this._speaking = false; this._refreshMood(); };
      u.onerror = () => { this._speaking = false; this._refreshMood(); };
      const start = () => {
        const v = this._pickFrVoice();
        if (v) u.voice = v;
        window.speechSynthesis.speak(u);
      };
      const voices = window.speechSynthesis.getVoices();
      if (voices && voices.length) start();
      else {
        window.speechSynthesis.onvoiceschanged = () => {
          window.speechSynthesis.onvoiceschanged = null;
          start();
        };
      }
    } catch (e) { /* la voix ne casse jamais rien */ }
  },

  _pickFrVoice() {
    try {
      const all = window.speechSynthesis.getVoices() || [];
      const fr = all.filter(v => (v.lang || '').toLowerCase().startsWith('fr'));
      if (!fr.length) return null;
      // Voix masculine si on en trouve une (Perceval), sinon la première.
      return fr.find(v => /paul|henri|nicolas|thomas|claude|guillaume|mathieu|male/i.test(v.name || ''))
          || fr.find(v => /fr-FR/i.test(v.lang || ''))
          || fr[0];
    } catch (e) { return null; }
  },

  _setVoice(on) {
    this.voiceOn = !!on;
    try { localStorage.setItem(this.LS.voice, on ? '1' : '0'); } catch (e) {}
    if (on) {
      // Confirmation immédiate : il se présente — meilleur test audio.
      this._lastSpoken = '';
      this._speak('Je suis là.');
    } else {
      try { window.speechSynthesis.cancel(); } catch (e) {}
      this._speaking = false;
    }
    this._renderBubble();
  },

  // ---------- humeurs ----------
  _wake() {
    this._lastActivity = Date.now();
    if (this.mood === 'sommeil') this._setMood('observe');
    this._armIdle();
  },

  _armIdle() {
    if (this._idleTimer) clearTimeout(this._idleTimer);
    this._idleTimer = setTimeout(() => this._refreshMood(), 5 * 60 * 1000 + 500);
  },

  _computeMood() {
    const s = this.snap;
    const w = (s && s.workers) || {};
    if (this._dbDown() || (w.error || 0) > 0) return 'alerte';
    if (this._speaking || this.eventMsg) return 'parle';
    const idleMs = Date.now() - this._lastActivity;
    const active = s && (s.missions || []).some(m => m.status === 'hunting' || m.status === 'handing');
    if (!active && idleMs > 5 * 60 * 1000) return 'sommeil';
    return 'observe';
  },

  _refreshMood() { this._setMood(this._computeMood()); },

  _setMood(m) {
    this.mood = m;
    this._applyMood();
  },

  _applyMood() {
    const host = document.getElementById('perceval-host');
    if (!host) return;
    host.dataset.mood = this.mood;
    host.dataset.speaking = this._speaking ? '1' : '0';
  },

  // ---------- montage ----------
  _mount() {
    if (document.getElementById('perceval-host')) return;
    const host = document.createElement('div');
    host.id = 'perceval-host';
    host.dataset.mood = this.mood;
    host.innerHTML = `
      <div id="pv-bubble" role="status" aria-live="polite"></div>
      <div id="pv-askbar">
        <form id="pv-ask" autocomplete="off">
          <input id="pv-ask-input" type="text" maxlength="600"
                 placeholder="Dis-moi ce que tu veux faire…"
                 aria-label="Écrire à ${this.name}"/>
          <button type="submit" title="Envoyer à ${this.name}" aria-label="Envoyer">➤</button>
        </form>
        <button id="pv-voice-btn" type="button" class="pv-tool-btn"
                aria-label="Voix de ${this.name}">🔇</button>
        <button id="pv-min-btn" type="button" class="pv-tool-btn"
                title="Réduire ${this.name} (il reste en petit)" aria-label="Réduire">▾</button>
      </div>
      <button id="pv-body" type="button"
              title="${this.name} — ton copilote"
              aria-label="${this.name}, ton copilote">
        ${this._svgBody()}
        <span id="pv-badge" class="hidden" aria-hidden="true"></span>
      </button>`;
    document.body.appendChild(host);
    document.getElementById('pv-voice-btn').onclick = () => this._setVoice(!this.voiceOn);
    document.getElementById('pv-min-btn').onclick = () => this._setCollapsed(true);
    document.getElementById('pv-body').onclick = () => {
      if (this.collapsed) { this._setCollapsed(false); return; }
      this._wanderReward();
      if (typeof Copilot !== 'undefined' && Copilot.toggle) Copilot.toggle();
      else this._setCollapsed(true);
    };
    // La zone « binôme » : on lui parle directement, sans rien ouvrir.
    // Le formulaire n'est JAMAIS re-rendu (la frappe en cours est sacrée).
    const ask = document.getElementById('pv-ask');
    if (typeof Copilot === 'undefined' || !Copilot.askFromOutside) {
      ask.style.display = 'none';
    } else {
      ask.onsubmit = (e) => {
        e.preventDefault();
        const inp = document.getElementById('pv-ask-input');
        const q = (inp.value || '').trim();
        if (!q) return;
        inp.value = '';
        this._wake();
        this._wanderReward();
        Copilot.askFromOutside(q);
      };
    }
  },

  // Le corps : l'écu validé avec Jordan — liseré, cimier, yeux lumineux,
  // onde vocale sur le plastron, triskell gravé ton sur ton.
  _svgBody() {
    return `
    <svg id="pv-svg" viewBox="20 0 104 152" aria-hidden="true">
      <g class="pv-float">
        <g class="pv-tilt">
          <path d="M70,22 L70,12" fill="none" stroke="#534AB7" stroke-width="3" stroke-linecap="round"/>
          <path d="M70,2 L75,9 L70,16 L65,9 Z" fill="#7F77DD"/>
          <path d="M70,24 C94,24 108,29 110,34 C110,72 106,100 70,128 C34,100 30,72 30,34 C32,29 46,24 70,24 Z"
                fill="#3C3489" stroke="#7F77DD" stroke-width="2"/>
          <g class="pv-eyes">
            <rect class="pv-eye" x="49" y="56" width="13" height="22" rx="6.5" fill="#EEEDFE"/>
            <rect class="pv-eye" x="78" y="56" width="13" height="22" rx="6.5" fill="#EEEDFE"/>
          </g>
          <g class="pv-eq">
            <rect class="pv-b1" x="56" y="88" width="3.5" height="14" rx="1.75" fill="#AFA9EC"/>
            <rect class="pv-b2" x="64" y="88" width="3.5" height="14" rx="1.75" fill="#AFA9EC"/>
            <rect class="pv-b3" x="72" y="88" width="3.5" height="14" rx="1.75" fill="#AFA9EC"/>
            <rect class="pv-b4" x="80" y="88" width="3.5" height="14" rx="1.75" fill="#AFA9EC"/>
          </g>
          <g class="pv-triskell" transform="translate(70,109) scale(0.85)">
            <circle r="1.6" fill="#534AB7"/>
            <path d="M0,-9 C6,-7 8,-1 4,3" fill="none" stroke="#534AB7" stroke-width="2.4" stroke-linecap="round"/>
            <path d="M0,-9 C6,-7 8,-1 4,3" fill="none" stroke="#534AB7" stroke-width="2.4" stroke-linecap="round" transform="rotate(120)"/>
            <path d="M0,-9 C6,-7 8,-1 4,3" fill="none" stroke="#534AB7" stroke-width="2.4" stroke-linecap="round" transform="rotate(240)"/>
          </g>
          <g class="pv-alert-badge">
            <circle cx="108" cy="32" r="9" fill="#EF9F27"/>
            <text x="108" y="36.5" text-anchor="middle" font-size="13" font-weight="700" fill="#412402">!</text>
          </g>
        </g>
        <g class="pv-dots">
          <circle class="pv-d1" cx="100" cy="34" r="2.5" fill="#7F77DD"/>
          <circle class="pv-d2" cx="109" cy="27" r="3" fill="#7F77DD"/>
          <circle class="pv-d3" cx="119" cy="19" r="3.5" fill="#7F77DD"/>
        </g>
      </g>
    </svg>`;
  },

  // ---------- rendu de la bulle ----------
  _renderBubble() {
    const host = document.getElementById('perceval-host');
    const bubble = document.getElementById('pv-bubble');
    if (!host || !bubble) return;
    this._applyMood();

    // Badge « le copilote a quelque chose pour toi »
    const badge = document.getElementById('pv-badge');
    if (badge) {
      const unseen = (this.snap && this.snap.copilot_unseen) || 0;
      const attn = (typeof Claude !== 'undefined' && Claude.isAttention);
      badge.classList.toggle('hidden', !(unseen > 0 || attn));
    }
    // Le bouton voix vit dans la barre (statique) : on rafraîchit son état.
    const vbtn = document.getElementById('pv-voice-btn');
    if (vbtn) {
      vbtn.textContent = this.voiceOn ? '🔊' : '🔇';
      vbtn.title = this.voiceOn ? 'Couper sa voix'
        : 'Activer sa voix — il lira ses messages à voix haute';
    }

    if (this.collapsed) {
      host.classList.add('pv-mini');
      bubble.classList.remove('pv-show');
      bubble.innerHTML = '';
      const body = document.getElementById('pv-body');
      if (body) body.title = `${this.name} — clique pour le réafficher`;
      return;
    }
    host.classList.remove('pv-mini');
    const body = document.getElementById('pv-body');
    if (body) body.title = `${this.name} — clique pour qu’on discute`;

    const vt = this.VIEW_TEXTS[this.view] || {};
    const rec = this._recommend();
    const lvl = this.level();

    // Contenu parlé : confirmation > base injoignable > conseil sur place
    let mid = '';
    if (this.eventMsg) {
      mid = `<div class="pv-event">${this._esc(this.eventMsg)}</div>`;
      if (Array.isArray(this.eventChoices) && this.eventChoices.length) {
        mid += `<div class="pv-actions">${this.eventChoices.map((c, i) =>
          `<button class="pv-chip" data-go-choice="${i}">${this._esc(c.label)} →</button>`).join('')}</div>`;
      }
    } else if (this._dbDown()) {
      mid = `<div class="pv-status">Connexion à la base impossible — les chiffres reviennent dès qu’elle répond.</div>`;
    } else if (rec && rec.view === this.view && vt.inview) {
      mid = `<div class="pv-status">${this._esc(vt.inview)}</div>`;
    }

    // Chip d'action : seulement si elle mène AILLEURS (sur place, le texte suffit)
    let chip = '';
    if (rec && rec.view !== this.view) {
      chip = `<div class="pv-actions">
        <button class="pv-chip ${rec.soft ? 'pv-chip-soft' : ''}"
                data-go="${this._esc(rec.view)}"
                title="${this._esc(rec.why || '')}">${this._esc(rec.label)} →</button>
      </div>`;
    } else if (rec && rec.view === this.view && !this.eventMsg && rec.why) {
      chip = `<div class="pv-why">${this._esc(rec.why)}</div>`;
    }

    const tip = (lvl === 'decouverte' && vt.inview && (!rec || rec.view !== this.view))
      ? `<div class="pv-tipline">💡 ${this._esc(vt.inview)}</div>` : '';

    // Rien à dire → pas de bulle : le perso et la barre suffisent.
    if (!mid && !chip && !tip) {
      bubble.classList.remove('pv-show');
      bubble.innerHTML = '';
      return;
    }
    bubble.classList.add('pv-show');
    bubble.innerHTML = `${mid}${chip}${tip}`;
    const go = bubble.querySelector('.pv-chip[data-go]');
    if (go) go.onclick = () => {
      const v = go.dataset.go;
      if (typeof App !== 'undefined' && App.show) App.show(v);
    };
    // Choix cliquables de la main tendue : cliquer = main saisie.
    bubble.querySelectorAll('[data-go-choice]').forEach(b => {
      b.onclick = () => {
        const c = (this.eventChoices || [])[parseInt(b.dataset.goChoice, 10)];
        if (!c) return;
        this._wanderReward();
        this.eventMsg = null;
        this.eventChoices = null;
        if (typeof App !== 'undefined' && App.show) App.show(c.view);
        this._refreshMood();
        this._renderBubble();
      };
    });
  },

  _setCollapsed(v) {
    this.collapsed = !!v;
    try { localStorage.setItem(this.LS.collapsed, v ? '1' : '0'); } catch (e) {}
    this._renderBubble();
    if (!v) this._poll();
  },

  // ---------- la rencontre (toute première fois) ----------
  _meetWhenClear(tries) {
    // Si une fenêtre plein écran est VRAIMENT ouverte (onboarding, visite,
    // appel…), on attend. L'app garde plusieurs overlays cachés en
    // permanence dans la page → on ne compte que les visibles.
    const overlayOpen = [...document.querySelectorAll('.fixed.inset-0')]
      .some(o => !o.classList.contains('hidden')
              && getComputedStyle(o).display !== 'none');
    if (overlayOpen) {
      if (tries < 60) {
        return setTimeout(() => this._meetWhenClear(tries + 1), 2000);
      }
      // ~2 min d'attente : on n'impose RIEN par-dessus une fenêtre ouverte.
      return;
    }
    if (this.met) return;
    const card = document.createElement('div');
    card.id = 'pv-meet';
    card.innerHTML = `
      <div class="pv-m-head">${this._svgBody()}</div>
      <div class="pv-m-title">Salut, moi c’est ${this.name}.</div>
      <div class="pv-m-body">
        Je travaille avec toi : je reste en bas de l’écran, je te dis
        ce qui vient de se passer et <b>le prochain geste utile</b>.
        Pour bien démarrer, suis la liste <b>« Premiers pas »</b> en haut
        du Cockpit — 4 étapes, dans l’ordre, et je t’accompagne.
        Clique sur moi quand tu veux qu’on discute. Et si tu actives ma
        voix (bouton 🔊), je te parle.
      </div>
      <div class="pv-m-actions">
        <button class="btn btn-primary text-xs" id="pv-m-go">Enchanté — au boulot</button>
        <button class="btn btn-secondary text-xs" id="pv-m-tour">La visite complète d’abord</button>
      </div>`;
    document.body.appendChild(card);
    const close = () => {
      this.met = true;
      try {
        localStorage.setItem(this.LS.met, '1');
        // Le bonjour du jour passera demain : aujourd'hui, on s'est rencontrés.
        localStorage.setItem(this.LS.greetDay, new Date().toISOString().slice(0, 10));
      } catch (e) {}
      this._greeted = true;
      card.remove();
    };
    card.querySelector('#pv-m-go').onclick = () => {
      close();
      // Premiers pas non terminés → on emmène au Cockpit, là où vit la
      // liste. Sinon, la recommandation habituelle.
      let fsDone = false;
      try { fsDone = localStorage.getItem('triskell.firststeps.done.v1') === '1'; } catch (e) {}
      if (typeof App !== 'undefined' && App.show) {
        if (!fsDone) { App.show('morning'); return; }
        const rec = this._recommend();
        App.show(rec ? rec.view : 'prospection');
      }
    };
    card.querySelector('#pv-m-tour').onclick = () => {
      close();
      if (typeof Tutorial !== 'undefined' && Tutorial.open) {
        Tutorial.open();
      } else if (typeof Toast !== 'undefined') {
        Toast.info('La visite guidée n’est pas disponible pour le moment — je te guide en direct.');
      }
    };
  },

  // ---------- styles ----------
  _injectStyles() {
    if (document.getElementById('perceval-styles')) return;
    const s = document.createElement('style');
    s.id = 'perceval-styles';
    s.textContent = `
      #perceval-host {
        position: fixed; z-index: 59;
        right: 18px;
        bottom: calc(14px + env(safe-area-inset-bottom, 0px));
        display: flex; flex-direction: column; align-items: flex-end;
        gap: 8px; pointer-events: none;
      }
      #perceval-host > * { pointer-events: auto; }

      /* -- le corps -- */
      #pv-body {
        position: relative; border: 0; background: transparent; padding: 0;
        cursor: pointer; line-height: 0;
        filter: drop-shadow(0 4px 10px rgba(15,23,42,.25));
        transition: transform .15s ease;
      }
      #pv-body:hover { transform: translateY(-2px) scale(1.04); }
      #pv-svg { width: 64px; height: 94px; display: block; }
      #perceval-host.pv-mini #pv-svg { width: 36px; height: 53px; }
      #pv-badge {
        position: absolute; top: 2px; left: 2px;
        width: 11px; height: 11px; border-radius: 50%;
        background: #ef4444; border: 2px solid hsl(var(--surface));
      }

      /* -- animations de vie (transform/opacity seulement : carte légère) -- */
      .pv-float { animation: pvFloat 4.5s ease-in-out infinite; }
      #perceval-host[data-mood="sommeil"] .pv-float { animation-duration: 8s; }
      .pv-eye {
        transform-box: fill-box; transform-origin: center;
        animation: pvBlink 5.5s infinite;
        transition: fill .3s, opacity .3s, transform .3s;
      }
      .pv-eyes { transform-box: fill-box; transform-origin: center;
                 transition: transform .3s; }
      .pv-tilt { transform-box: fill-box; transform-origin: center; }
      .pv-eq rect { transform-box: fill-box; transform-origin: center; }
      .pv-eq, .pv-dots, .pv-alert-badge { opacity: 0; transition: opacity .25s; }

      #perceval-host[data-mood="sommeil"] .pv-eye {
        animation: none; transform: scaleY(.16); opacity: .65;
      }
      #perceval-host[data-mood="observe"] .pv-eyes { animation: pvLook 7s ease-in-out infinite; }
      #perceval-host[data-mood="reflechit"] .pv-eyes { transform: translateY(-4px); }
      #perceval-host[data-mood="reflechit"] .pv-dots { opacity: 1; }
      #perceval-host[data-mood="reflechit"] .pv-d1 { animation: pvDot 1.4s ease-in-out infinite; }
      #perceval-host[data-mood="reflechit"] .pv-d2 { animation: pvDot 1.4s ease-in-out .25s infinite; }
      #perceval-host[data-mood="reflechit"] .pv-d3 { animation: pvDot 1.4s ease-in-out .5s infinite; }
      #perceval-host[data-mood="alerte"] .pv-eye { fill: #EF9F27; }
      #perceval-host[data-mood="alerte"] .pv-alert-badge { opacity: 1; }
      #perceval-host[data-mood="alerte"] .pv-tilt { animation: pvWiggle 1.6s ease-in-out infinite; }
      #perceval-host[data-speaking="1"] .pv-eq { opacity: 1; }
      #perceval-host[data-speaking="1"] .pv-b1 { animation: pvEq .5s ease-in-out infinite; }
      #perceval-host[data-speaking="1"] .pv-b2 { animation: pvEq .5s ease-in-out .12s infinite; }
      #perceval-host[data-speaking="1"] .pv-b3 { animation: pvEq .5s ease-in-out .24s infinite; }
      #perceval-host[data-speaking="1"] .pv-b4 { animation: pvEq .5s ease-in-out .36s infinite; }

      /* -- la barre : « dis-moi ce que tu veux faire » + voix + réduire -- */
      #pv-askbar { display: flex; align-items: center; gap: 6px; }
      #pv-ask {
        display: flex; align-items: center; gap: 4px;
        width: 240px; padding: 4px 4px 4px 12px;
        background: hsl(var(--surface-elevated, var(--surface)) / .94);
        backdrop-filter: blur(10px);
        border: 1px solid hsl(var(--border-strong));
        border-radius: 999px;
        box-shadow: 0 4px 14px rgba(15,23,42,.14);
      }
      #pv-ask:focus-within { border-color: hsl(var(--accent) / .6); }
      #pv-ask input {
        flex: 1; min-width: 0; border: 0; background: transparent;
        font-size: 12.5px; color: hsl(var(--text));
        outline: none; padding: 5px 0;
      }
      #pv-ask input::placeholder { color: hsl(var(--text-muted)); }
      #pv-ask button[type="submit"] {
        flex-shrink: 0; border: 0; cursor: pointer;
        width: 26px; height: 26px; border-radius: 50%;
        background: hsl(var(--accent)); color: #fff;
        font-size: 12px; line-height: 1;
      }
      #pv-ask button[type="submit"]:hover { transform: scale(1.06); }
      .pv-tool-btn {
        flex-shrink: 0; border: 1px solid hsl(var(--border-strong));
        width: 30px; height: 30px; border-radius: 50%;
        background: hsl(var(--surface-elevated, var(--surface)) / .94);
        backdrop-filter: blur(10px);
        cursor: pointer; font-size: 13px; line-height: 1;
        color: hsl(var(--text-secondary));
        box-shadow: 0 4px 14px rgba(15,23,42,.14);
      }
      .pv-tool-btn:hover { background: hsl(var(--border) / .6); }
      #perceval-host.pv-mini #pv-askbar { display: none; }
      @media (max-width: 640px) {
        #pv-askbar { display: none; }
      }

      /* -- la bulle : épisodique et compacte, ancrée au-dessus de la barre -- */
      #pv-bubble {
        display: none;
        max-width: min(330px, calc(100vw - 40px));
        background: hsl(var(--surface-elevated, var(--surface)) / .94);
        backdrop-filter: blur(10px);
        border: 1px solid hsl(var(--border-strong));
        border-radius: 14px; border-bottom-right-radius: 4px;
        padding: 10px 13px;
        box-shadow: 0 4px 18px rgba(15,23,42,.16);
        font-size: 12.5px; line-height: 1.5;
        color: hsl(var(--text-secondary));
        text-wrap: pretty;
        animation: pvRise .25s ease-out;
      }
      #pv-bubble.pv-show { display: block; }
      .pv-event { color: hsl(var(--success)); font-weight: 600;
                  animation: pvFade .3s ease-out; }
      .pv-actions { margin-top: 7px; }
      .pv-why { margin-top: 5px; color: hsl(var(--text-muted)); font-size: 12px; }
      .pv-chip {
        border: 0; cursor: pointer;
        background: hsl(var(--accent)); color: #fff;
        font-size: 12px; font-weight: 700;
        padding: 5px 12px; border-radius: 999px;
        transition: transform .12s, box-shadow .12s;
      }
      .pv-chip:hover { transform: translateY(-1px);
                       box-shadow: 0 4px 12px hsl(var(--accent) / .4); }
      .pv-chip-soft { background: hsl(var(--accent) / .14);
                      color: hsl(var(--accent)); }
      .pv-tipline {
        margin-top: 7px; padding-top: 7px;
        border-top: 1px dashed hsl(var(--border));
        font-size: 12px; color: hsl(var(--text-muted));
      }

      /* -- le doigt pointé (élément mis en lumière + consigne) -- */
      .pv-spot {
        outline: 3px solid hsl(var(--accent)) !important;
        outline-offset: 3px;
        border-radius: 8px;
        animation: pvSpotPulse 1.2s ease-in-out infinite;
      }
      #pv-spot-note {
        position: fixed; z-index: 62;
        background: hsl(var(--accent)); color: #fff;
        font-size: 12.5px; font-weight: 700;
        padding: 6px 12px; border-radius: 999px;
        box-shadow: 0 6px 20px hsl(var(--accent) / .45);
        pointer-events: none; white-space: nowrap;
        animation: pvFade .25s ease-out;
      }
      @keyframes pvSpotPulse {
        0%,100% { outline-color: hsl(var(--accent)); }
        50% { outline-color: hsl(var(--accent) / .3); }
      }

      /* -- carte de rencontre -- */
      #pv-meet {
        position: fixed; z-index: 61;
        right: 18px;
        bottom: calc(166px + env(safe-area-inset-bottom, 0px));
        width: min(430px, calc(100vw - 32px));
        background: hsl(var(--surface-elevated, var(--surface)));
        border: 1px solid hsl(var(--border-strong));
        border-radius: 16px; padding: 16px;
        box-shadow: 0 12px 40px rgba(15,23,42,.22);
        animation: pvMeetRise .4s cubic-bezier(.16,1,.3,1);
      }
      #pv-meet .pv-m-head { text-align: center; margin-bottom: 4px; }
      #pv-meet .pv-m-head svg { width: 64px; height: 69px; }
      .pv-m-title { font-weight: 800; font-size: 14.5px; margin-bottom: 6px;
                    color: hsl(var(--text)); }
      .pv-m-body { font-size: 12.5px; line-height: 1.55;
                   color: hsl(var(--text-secondary)); margin-bottom: 12px; }
      .pv-m-actions { display: flex; gap: 8px; flex-wrap: wrap; }

      /* -- cohabitation : Perceval prend le coin droit, Thomas se met
            à sa gauche (même ligne), les notifications passent au-dessus -- */
      #tc-toast-host { bottom: calc(160px + env(safe-area-inset-bottom, 0px)) !important; }
      #thomas-fab { right: 100px; }

      /* Quand le volet de discussion est ouvert, Perceval s'efface. */
      @supports selector(:has(*)) {
        body:has(#copilot-panel.cop-visible) #perceval-host {
          opacity: 0; pointer-events: none; transition: opacity .2s;
        }
      }

      @keyframes pvFloat { 0%,100% { transform: translateY(0); } 50% { transform: translateY(-4px); } }
      @keyframes pvBlink { 0%,93%,100% { transform: scaleY(1); } 96% { transform: scaleY(.12); } }
      @keyframes pvLook { 0%,18%,100% { transform: translateX(0); }
                          32%,50% { transform: translateX(4px); }
                          66%,84% { transform: translateX(-4px); } }
      @keyframes pvDot { 0%,100% { opacity: .2; } 50% { opacity: 1; } }
      @keyframes pvEq { 0%,100% { transform: scaleY(.25); } 50% { transform: scaleY(1); } }
      @keyframes pvWiggle { 0%,100% { transform: rotate(0); }
                            25% { transform: rotate(-1.8deg); }
                            75% { transform: rotate(1.8deg); } }
      @keyframes pvFade { from { opacity: 0; } to { opacity: 1; } }
      @keyframes pvRise { from { opacity: 0; transform: translateY(6px); }
                          to { opacity: 1; transform: translateY(0); } }
      @keyframes pvMeetRise { from { opacity: 0; transform: translateY(10px); }
                              to { opacity: 1; transform: translateY(0); } }

      @media (max-width: 640px) {
        #pv-svg { width: 50px; height: 73px; }
        .pv-tipline { display: none; }
      }
      @media (prefers-reduced-motion: reduce) {
        .pv-float, .pv-eye, .pv-eyes, .pv-tilt,
        #perceval-host[data-speaking="1"] .pv-eq rect { animation: none !important; }
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

// Compat : les autres écrans appellent Guide.say / Guide.onViewChange.
window.Guide = Perceval;

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
        try { Perceval.onViewChange(viewId); } catch (e) { /* jamais bloquant */ }
        return r;
      };
      App.__guideWrapped = true;
    }
  } catch (e) { /* Perceval ne casse JAMAIS l'app */ }

  const boot = () => { try { Perceval.init(); } catch (e) { console.warn('perceval:', e); } };
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => setTimeout(boot, 400));
  } else {
    setTimeout(boot, 400);
  }
})();
