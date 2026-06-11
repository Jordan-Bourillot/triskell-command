/* DemoMode — mode démo pour générer des visuels promotionnels.
 *
 * 🚨 PRINCIPE DE SÉCURITÉ (liste BLANCHE depuis le 11/06/2026) :
 *   - En démo, PLUS RIEN ne part au serveur : ni lecture, ni écriture.
 *   - Un appel API a exactement trois destins :
 *       1. un faux existe (_fake) → données fictives crédibles ;
 *       2. il est dans NETWORK_ALLOWED (session + thème, rien de métier)
 *          → il passe au serveur ;
 *       3. TOUT LE RESTE est bloqué net ({ok:false, demo_blocked:true}).
 *   - Avant, c'était une liste NOIRE : toute méthode non reconnue partait
 *     au VRAI serveur — on pouvait envoyer de vrais mails en plein mode
 *     démo. Ne jamais revenir à ce fonctionnement.
 *   - Bandeau "MODE DÉMO" visible en haut, masquable temporairement (30 sec)
 *     pour la capture d'écran via un bouton "Masquer 30 sec". Une vigie le
 *     ré-injecte s'il disparaît (vue qui écrase le DOM, rechargement…).
 *
 * Activation : Réglages → "Mode démo" → bouton Activer.
 * Persisté en localStorage (clé `tc-demo-mode`).
 */
const DemoMode = {
  STORAGE_KEY: 'tc-demo-mode',
  HIDE_BANNER_UNTIL: 'tc-demo-hide-banner-until',

  // ----- État -----
  isOn() {
    try { return localStorage.getItem(this.STORAGE_KEY) === 'on'; }
    catch (e) { return false; }
  },
  setOn(on) {
    try {
      if (on) localStorage.setItem(this.STORAGE_KEY, 'on');
      else {
        localStorage.removeItem(this.STORAGE_KEY);
        sessionStorage.removeItem(this.HIDE_BANNER_UNTIL);
      }
    } catch (e) {}
    // Recharge pour ré-appliquer l'interception API + redessiner les vues
    setTimeout(() => location.reload(), 200);
  },

  // ----- Bannière -----
  ensureBanner() {
    if (!this.isOn()) {
      this._removeBanner();
      return;
    }
    // Bannière temporairement masquée pour screenshot ? La vigie
    // (_startBannerWatch) la fera revenir toute seule à l'expiration,
    // même si la page a été rechargée entre-temps.
    try {
      const until = parseInt(sessionStorage.getItem(this.HIDE_BANNER_UNTIL) || '0', 10);
      if (until && Date.now() < until) return;
    } catch (e) {}
    if (document.getElementById('demo-banner')) {
      this._fitBannerPadding();
      return;
    }

    const banner = document.createElement('div');
    banner.id = 'demo-banner';
    banner.style.cssText = `
      position: fixed; top: 0; left: 0; right: 0;
      z-index: 9999;
      background: linear-gradient(90deg, #ef4444 0%, #f97316 100%);
      color: white;
      padding: 7px 14px;
      font-size: 12.5px;
      font-weight: 600;
      letter-spacing: 0.3px;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 16px;
      box-shadow: 0 2px 8px rgba(239,68,68,0.35);
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    `;
    banner.innerHTML = `
      <span style="display:inline-flex; align-items:center; gap:8px;">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
          <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
        </svg>
        <strong style="font-weight:800; letter-spacing:1px;">MODE DÉMO</strong>
        — aucune action ne part au serveur ; certaines tuiles affichent des données d'exemple.
      </span>
      <button id="demo-hide-btn" type="button"
              style="background:rgba(255,255,255,0.2); color:white; border:1px solid rgba(255,255,255,0.4); border-radius:6px; padding:3px 10px; font-size:11px; font-weight:600; cursor:pointer;">
        Masquer 30 sec
      </button>
      <button id="demo-off-btn" type="button"
              style="background:rgba(0,0,0,0.25); color:white; border:1px solid rgba(255,255,255,0.4); border-radius:6px; padding:3px 10px; font-size:11px; font-weight:600; cursor:pointer;">
        Désactiver
      </button>
    `;
    document.body.insertBefore(banner, document.body.firstChild);
    this._fitBannerPadding();

    banner.querySelector('#demo-hide-btn').onclick = () => {
      try { sessionStorage.setItem(this.HIDE_BANNER_UNTIL, String(Date.now() + 30_000)); } catch (e) {}
      this._removeBanner();
      setTimeout(() => this.ensureBanner(), 30_000);
    };
    banner.querySelector('#demo-off-btn').onclick = () => this.setOn(false);
  },
  // Décale la page de la hauteur RÉELLE du bandeau (mesurée), au lieu d'un
  // 34px en dur qui se décalait dès que le texte passait sur deux lignes.
  _fitBannerPadding() {
    const b = document.getElementById('demo-banner');
    if (!b) return;
    const h = b.offsetHeight;
    if (h) document.body.style.paddingTop = h + 'px';
  },
  // Vigie du bandeau : toutes les 5 s, ré-injecte le bandeau s'il a disparu
  // (vue qui réécrit le haut de page, fin de capture…), ré-ajuste le décalage
  // si sa hauteur a changé, et le fait revenir à l'expiration de
  // « Masquer 30 sec » — y compris après un rechargement de la page
  // (ensureBanner relit l'horodatage à chaque passage).
  _startBannerWatch() {
    if (this._bannerWatch) return;
    this._bannerWatch = setInterval(() => {
      try {
        if (!this.isOn()) return;
        this.ensureBanner();
      } catch (e) { /* la vigie ne casse jamais l'app */ }
    }, 5000);
  },
  _removeBanner() {
    const b = document.getElementById('demo-banner');
    if (b) {
      b.remove();
      document.body.style.paddingTop = '';
    }
  },

  // ----- Interception API -----
  // 🚨 LISTE BLANCHE (11/06/2026). Trois destins possibles pour un appel :
  //   1. un faux (_fake) → données fictives, zéro réseau ;
  //   2. NETWORK_ALLOWED → passe au serveur (session + thème, rien de métier) ;
  //   3. tout le reste → BLOQUÉ ({ok:false, demo_blocked:true}).
  // Ne JAMAIS ré-introduire un « par défaut, ça passe au serveur ».

  // Message renvoyé pour tout appel bloqué (les vues l'affichent tel quel).
  BLOCKED_MESSAGE: 'Mode démo : cette action est désactivée. Désactive le mode démo (bandeau en haut) pour travailler en réel.',

  // Les SEULES méthodes autorisées à toucher le réseau en démo. Rien ici ne
  // lit ni n'écrit de données métier : état de session + thème, c'est tout.
  // (« me » et « avatar » partent en fetch direct sans passer par le Proxy
  //  d'app.js → hors de portée de cette interception, et inoffensifs.)
  NETWORK_ALLOWED: new Set([
    'auth_status',       // a un faux : le réseau ne sert que si le faux disparaît
    'get_current_user',  // idem
    'get_theme_mode',
    'set_theme_mode',
    'cycle_theme',
  ]),

  // Compat : health_check.js appelle encore isReadMethod() pour son
  // diagnostic « fake manquant ». Ne décide PLUS d'aucun passage réseau.
  isReadMethod(method) {
    return /^(get|is|list|fetch|check|me)_/.test(method)
        || /_(list|get|status|count|search|fetch|preview)$/.test(method)
        || ['boot', 'me', 'auth_status'].includes(method);
  },

  // Le refus standard du mode démo (objet neuf à chaque appel : personne
  // ne peut le muter pour les suivants).
  _blockedResult() {
    return { ok: false, demo_blocked: true, error: this.BLOCKED_MESSAGE };
  },

  /** Intercepte un appel API.
   *  Retourne { handled: true, result } si on prend la main,
   *  ou { handled: false } pour laisser passer au serveur (liste blanche). */
  intercept(method, payload) {
    if (!this.isOn()) return { handled: false };
    // 1) Un faux existe → données fictives. Un faux qui plante ne laisse
    //    JAMAIS filer l'appel au serveur : il bloque, et se signale en console.
    const fake = Object.prototype.hasOwnProperty.call(this._fake, method)
      ? this._fake[method] : null;
    if (typeof fake === 'function') {
      try { return { handled: true, result: this._fake[method](payload) }; }
      catch (e) {
        console.error('[DemoMode] faux en erreur → appel bloqué :', method, e);
        return { handled: true, result: this._blockedResult() };
      }
    }
    // 2) Liste blanche réseau stricte (session + thème uniquement)
    if (this.NETWORK_ALLOWED.has(method)) return { handled: false };
    // 3) Défaut : BLOQUÉ. Rien d'autre ne part au serveur en démo.
    return { handled: true, result: this._blockedResult() };
  },

  // ----- Données fictives (méthodes appelées par le frontend) -----
  _fake: {
    // ============ Matinale : digest avec gros chiffres ============
    // Format attendu par morning.js : sent / replies / queue / alerts
    get_morning_digest() {
      return {
        ok: true,
        sent: { yesterday: 89, today: 18, last_7d: 624 },
        replies: {
          yesterday_total: 21,
          yesterday_breakdown: { interested: 8, not_now: 6, no: 5, unsubscribe: 2 },
          today_total: 4,
          today_breakdown: { interested: 1, not_now: 2, no: 1 },
        },
        queue: {
          replies_unhandled_interested: 12,   // Priorité du jour = 12 intéressés (en vert)
          replies_unhandled_total: 18,
          drafts_prospect_pending: 8,
          drafts_convoy_pending: 3,
        },
        alerts: { convoy_failed_yesterday: 0, convoy_failed_today: 0 },
      };
    },

    // ============ Le Guide (barre du bas) ============
    // Format lu par guide.js et prospection.js : compteurs + missions + robots.
    // Chiffres alignés sur les autres faux (digest, funnel) pour rester cohérent.
    guide_snapshot() {
      const missions = (DemoMode._fake.prospection_missions().missions || [])
        .map(m => ({ id: m.id, status: m.status, progress: m.progress, counts: m.counts }));
      return {
        ok: true,
        drafts_pending: 8,
        replies_unhandled: 18,
        prospects_total: 4820,
        prospects_new: 3580,
        autopilot_enabled: true,
        workers: { healthy: 9, warning: 0, error: 0 },
        copilot_unseen: 0,
        missions,
      };
    },

    // ============ Lancer une prospection (écran tunnel) ============
    // Format lu par prospection.js : missions[] + autopilot.enabled.
    // Deux missions : une terminée (rapport qualité + aperçu), une en cours.
    prospection_missions() {
      const now = Date.now();
      return {
        ok: true,
        autopilot: { enabled: true },
        missions: [
          {
            id: 'demo-mission-2',
            label: 'Commerces locaux — coiffeur à Rennes',
            source: 'local',
            params: { metier: 'coiffeur', zone: 'Rennes', volume: 60 },
            status: 'hunting',
            dry_run: false,
            progress: 64,
            created_at: new Date(now - 25 * 60_000).toISOString(),
            counts: { found: 31, with_email: 19 },
            autopilot: {},
          },
          {
            id: 'demo-mission-1',
            label: 'PME — fleuriste dans le 35',
            source: 'pme',
            params: { metier: 'fleuriste', departement: '35', volume: 100 },
            status: 'handed',
            dry_run: false,
            progress: 100,
            created_at: new Date(now - 3 * 3600_000).toISOString(),
            counts: { found: 92, with_email: 67, pushed: 58, created: 51, merged: 7 },
            quality: {
              total: 67, kept: 58,
              dropped: { bad_email: 5, placeholder_name: 2, duplicate_in_batch: 2 },
            },
            autopilot: { kicked: true, note: 'Auto-pilote prévenu — il écrit aux nouvelles fiches.' },
            preview: [
              { nom: 'Fleuriste Pétale',    email: 'contact@petale.exemple.fr',        sort: 'nouvelle fiche' },
              { nom: 'Au Jardin de Rennes', email: 'bonjour@jardin-rennes.exemple.fr', sort: 'nouvelle fiche' },
              { nom: 'Rose & Lys',          email: 'hello@rose-lys.exemple.fr',        sort: 'fusionnée' },
            ],
          },
        ],
      };
    },

    // En démo, on ne lance RIEN : blocage assumé, avec un message sympa.
    prospection_start() {
      return {
        ok: false, demo_blocked: true,
        error: 'Mode démo : lance une vraie prospection hors démo 😉 (bandeau en haut → Désactiver).',
      };
    },
    // (prospection_mission_cancel n'a volontairement PAS de faux : le blocage
    //  par défaut s'en charge — plus jamais de faux succès sur une vraie mission.)

    // ============ Base prospects (écran « Tous les prospects ») ============
    obelisk_stats() {
      return { ok: true, stats: { total: 248, with_email: 187, qualified: 64, contacted: 112, won: 9 } };
    },
    obelisk_list_creators(payload) {
      const rows = [
        { id: 'ob-1', name: 'Maxime Cuisine', handle: 'maximecuisine', audience: 'creator',
          platform_url: 'https://www.youtube.com/@maximecuisine', industry: 'Cuisine',
          subscribers: 184000, emails: ['contact@maximecuisine.exemple.fr'], city: 'Lyon', status: 'qualified' },
        { id: 'ob-2', name: 'LeaPlaysFR', handle: 'leaplaysfr', audience: 'creator',
          platform_url: 'https://www.twitch.tv/leaplaysfr', industry: 'Gaming',
          subscribers: 42000, emails: ['pro@leaplays.exemple.fr'], city: 'Bordeaux', status: 'contacted' },
        { id: 'ob-3', name: 'Le Podcast du Potager', handle: 'podcastpotager', audience: 'creator',
          platform_url: 'https://podcasts.apple.com/fr/podcast/le-potager', industry: 'Jardinage',
          subscribers: 8600, emails: ['hello@potager.exemple.fr'], city: 'Angers', status: 'replied' },
        { id: 'ob-4', name: 'Nora Fitness', handle: 'norafit', audience: 'creator',
          platform_url: '', sources: [{ name: 'Instagram' }], industry: 'Fitness',
          subscribers: 96000, emails: ['collab@norafit.exemple.fr'], city: 'Marseille', status: 'new' },
        { id: 'ob-5', name: 'DevTom', handle: 'devtom', audience: 'creator',
          platform_url: 'https://github.com/devtom', industry: 'Développement',
          subscribers: 3100, emails: ['tom@devtom.exemple.fr'], city: 'Toulouse', status: 'new' },
        { id: 'ob-6', name: 'Crêperie du Port', legal_name: 'Crêperie du Port', audience: 'pro',
          platform_url: '', sources: [{ name: 'OpenStreetMap' }], industry: 'Restauration',
          subscribers: null, emails: ['contact@creperie-du-port.exemple.fr'], city: 'Saint-Malo', status: 'qualified' },
        { id: 'ob-7', name: 'Cabinet Kiné Ouest', legal_name: 'Cabinet Kiné Ouest', audience: 'pro',
          platform_url: '', sources: [{ name: 'OpenStreetMap' }], industry: 'Santé',
          subscribers: null, emails: ['accueil@kine-ouest.exemple.fr'], city: 'Brest', status: 'contacted' },
        { id: 'ob-8', name: 'Hôtel des Remparts', legal_name: 'Hôtel des Remparts', audience: 'pro',
          platform_url: '', sources: [{ name: 'Pages Jaunes' }], industry: 'Hôtellerie',
          subscribers: null, emails: ['reservation@remparts.exemple.fr'], city: 'Dinan', status: 'won' },
        { id: 'ob-9', name: 'Menuiserie Le Goff', legal_name: 'Menuiserie Le Goff', audience: 'pro',
          platform_url: '', sources: [{ name: 'Registre Sirene' }], industry: 'Artisanat',
          subscribers: null, emails: ['atelier@legoff-bois.exemple.fr'], city: 'Vannes', status: 'new' },
      ];
      const p = payload || {};
      let filtered = rows;
      if (p.audience) filtered = filtered.filter(r => r.audience === p.audience);
      if (p.q) {
        const q = String(p.q).toLowerCase();
        filtered = filtered.filter(r =>
          (r.name || '').toLowerCase().includes(q) || (r.handle || '').toLowerCase().includes(q));
      }
      const off = Number(p.offset) || 0;
      const lim = Number(p.limit) || 50;
      return { ok: true, rows: filtered.slice(off, off + lim), count: filtered.length };
    },

    // ============ Chaînes de fabrication (badges + panneau Cockpit) ============
    pipelines_activity() {
      const t = (min) => new Date(Date.now() - min * 60_000).toISOString();
      return {
        ok: true,
        pipelines: {
          lagriffe: { recent: [
            { name: 'Cabinet Dupont & Co', status: 'devis', at: t(40) },
            { name: 'Atelier Missor',      status: 'won',   at: t(160) },
          ] },
          rankus: { recent: [
            { name: 'Pharmacie Centrale', status: 'audit', at: t(90) },
          ] },
          wow: { recent: [
            { name: 'Studio Yoga Soleil', status: 'storyboard', at: t(200) },
          ] },
          pixelpros: { recent: [
            { name: 'Plombier Express', status: 'paid', at: t(15) },
            { name: 'Optique Vision',   status: 'live', at: t(300) },
          ] },
        },
      };
    },

    // ============ Mails ============
    mails_list(payload) {
      const kind = (payload && payload.kind) || 'all';
      const all = DemoMode._fakeMails();
      let filtered = all;
      if (kind === 'sent') filtered = all.filter(m => m.kind === 'email_sent');
      else if (kind === 'reply' || kind === 'inbound') filtered = all.filter(m => m.kind === 'reply_received');
      return { ok: true, mails: filtered.slice(0, (payload && payload.limit) || 50) };
    },

    // ============ Signatures (3 belles) ============
    signatures_list() {
      return {
        ok: true,
        signatures: [
          { id: 's1', name: 'Lagriffe Studio', body_html: '<p>Jordan Bourillot — Lagriffe Studio</p>', body_text: 'Jordan Bourillot — Lagriffe Studio', account_ids: [] },
          { id: 's2', name: 'Triskell Studio', body_html: '<p>Jordan Bourillot — Triskell Studio</p>', body_text: 'Jordan Bourillot — Triskell Studio', account_ids: [] },
          { id: 's3', name: 'RankUs Studio',   body_html: '<p>Jordan Bourillot — RankUs Studio</p>',   body_text: 'Jordan Bourillot — RankUs Studio', account_ids: [] },
        ],
      };
    },

    // ============ Comptes mail (3 adresses) ============
    mail_accounts_list() {
      return {
        ok: true,
        accounts: [
          { id: 'primary', label: 'Triskell Studio', from_email: 'contact@triskell-studio.fr', is_primary: true, _has_smtp_pwd: true, _has_imap_pwd: true },
          { id: 'lagriffe', label: 'Lagriffe Studio', from_email: 'contact@lagriffe-studio.fr', is_primary: false, _has_smtp_pwd: true, _has_imap_pwd: true },
          { id: 'rankus', label: 'RankUs Studio', from_email: 'contact@rankus-studio.fr', is_primary: false, _has_smtp_pwd: true, _has_imap_pwd: true },
        ],
      };
    },

    // ============ Modèles d'emails (6 templates) ============
    user_mail_templates_list() {
      return {
        ok: true,
        templates: [
          { id: 't1', name: 'Devis envoyé',          subject_default: 'Votre devis Lagriffe Studio', body_html: '<p>Bonjour,</p><p>Suite à notre échange, voici le devis pour votre projet…</p>' },
          { id: 't2', name: 'Suivi 1 mois après',    subject_default: 'On reste en contact ?', body_html: '<p>Bonjour,</p><p>Cela fait un mois que nous avons échangé…</p>' },
          { id: 't3', name: 'Bienvenue nouveau client', subject_default: 'Bienvenue chez Triskell !', body_html: '<p>Bonjour,</p><p>Votre projet démarre…</p>' },
          { id: 't4', name: 'Livraison site',        subject_default: 'Votre site est en ligne 🚀', body_html: '<p>Bonjour,</p><p>Votre site est livré et prêt à l\'emploi…</p>' },
          { id: 't5', name: 'Relance facture',       subject_default: 'Rappel — facture en attente', body_html: '<p>Bonjour,</p><p>Petit rappel pour la facture du mois dernier…</p>' },
          { id: 't6', name: 'Demande de témoignage', subject_default: 'Quelques mots sur notre collaboration ?', body_html: '<p>Bonjour,</p><p>Si tout se passe bien, un retour serait précieux…</p>' },
        ],
      };
    },

    // ============ Projets clients (kanban 4 colonnes, ~30 projets) ============
    get_clients() {
      const F = DemoMode._fakeProjects();
      return { ok: true, groups: F };
    },

    // ============ Brouillons à valider ============
    // Format attendu : { ok, rows: [{key, name, email, city, ts, provider, model, subject, body}, ...] }
    get_drafts() {
      const now = Date.now();
      const rows = [];
      const prospects = [
        ['Sophie Dupont',    'Cabinet Dupont & Co',       'sophie@dupont-co.fr',           'Paris',     'Refonte site + SEO'],
        ['Marc Lefèvre',     'Boulangerie Lefèvre',       'marc@boulangerie-lefevre.fr',   'Plérin',    'Pack Sites'],
        ['Camille Bernard',  'Atelier Missor',            'camille@missor.fr',             'Nantes',    'Site vitrine + SEO'],
        ['Antoine Petit',    'Garage Auto Plus',          'antoine@autoplus.fr',           'Rennes',    'Pack visibilité Maps'],
        ['Léa Durand',       'Pharmacie Centrale',        'lea@pharmacie-centrale.fr',     'Saint-Brieuc', 'Site + prise RDV'],
        ['Thomas Moreau',    'Studio Yoga Soleil',        'thomas@yogasoleil.fr',          'Brest',     'Refonte + booking'],
        ['Julie Lambert',    'Restaurant Le Bistrot',     'julie@bistrot.fr',              'Lannion',   'Carte en ligne + SEO'],
        ['Nicolas Rousseau', 'Salon Élégance',            'nicolas@elegance-coiffure.fr',  'Vannes',    'Pack Sites'],
        ['Manon Vincent',    'École Andante',             'manon@andante-musique.fr',      'Quimper',   'Site école + paiement'],
        ['Pierre Fontaine',  'Cabinet vétérinaire Animo', 'pierre@animo-veto.fr',          'Dinan',     'Site + prise RDV'],
        ['Émilie Dubois',    'Pâtisserie Sucré Salé',     'emilie@sucresale.fr',           'Lorient',   'Catalogue en ligne'],
        ['Hugo Robin',       'Optique Vision',            'hugo@optique-vision.fr',        'Pontivy',   'Pack visibilité Maps'],
      ];
      for (let i = 0; i < prospects.length; i++) {
        const [name, company, email, city, project] = prospects[i];
        const firstName = name.split(' ')[0];
        rows.push({
          key: `draft-${i}`,
          name: `${name} (${company})`,
          email,
          city,
          ts: new Date(now - i * 7200_000).toISOString(),
          provider: 'anthropic',
          model: 'claude-sonnet-4-5',
          subject: `${company} — votre projet ${project.toLowerCase()}`,
          body: `Bonjour ${firstName},\n\n`
              + `Je suis tombé sur ${company} en regardant les ${project.toLowerCase().includes('seo') ? 'avis Google de votre secteur à ' + city : 'commerces locaux de ' + city}. Votre activité m'a marqué par la qualité de vos services.\n\n`
              + `Chez Triskell Studio, nous accompagnons des structures comme la vôtre pour ${project.toLowerCase()}, avec un délai court et un budget calibré.\n\n`
              + `Si l'idée vous parle, 15 min en visio pour qu'on en discute ?\n\n`
              + `Bonne journée,\n`,
        });
      }
      return { ok: true, rows };
    },

    // ============ Réponses prospects ============
    // Format attendu : { ok, rows: [...], prospects: {[id]: {name, emails}} }
    get_replies(payload) {
      const filter = (payload && payload.category) || 'all';
      const cats = ['interested', 'not_now', 'no', 'unsubscribe', 'unknown'];
      const all = DemoMode._fakeMails().filter(m => m.kind === 'reply_received');
      const prospects = {};
      const rows = all.slice(0, 30).map((m, i) => {
        const cat = cats[i % cats.length];
        const pid = `prospect-${i}`;
        prospects[pid] = {
          name: m.extra.sender_name.split(' (')[0],
          legal_name: m.extra.sender_name.split('(')[1]?.replace(')', '') || '',
          emails: [m.extra.from],
        };
        return {
          id: m.id,
          ts: m.ts,
          subject: m.subject,
          prospect_id: pid,
          extra: {
            from: m.extra.from,
            body_excerpt: m.body,
            classification: { category: cat, confidence: 0.78 + (i % 20) / 100 },
            sender_name: m.extra.sender_name,
            // Pour les intéressés : suggestion de réponse pré-rédigée
            suggested_reply: cat === 'interested' ? {
              status: 'pending',
              subject: 'Re: ' + m.subject,
              body: 'Bonjour, ravi de votre retour. Voici le lien direct pour récupérer le produit…',
            } : null,
          },
        };
      });
      const filtered = filter === 'all' ? rows : rows.filter(r => r.extra.classification.category === filter);
      return { ok: true, rows: filtered, prospects };
    },

    // ============ Funnel (entonnoir de conversion) ============
    get_funnel(payload) {
      return {
        ok: true,
        period: (payload && payload.period) || '30d',
        stages: { prospects: 4820, sent: 1247, replies: 312, interested: 89, won: 28 },
        by_category: { interested: 89, not_now: 64, no: 95, unsubscribe: 18, unknown: 46 },
        by_status: { new: 3580, qualified: 720, contacted: 412, replied: 312, won: 28 },
        by_product: { 'lagriffe-sites': 41, 'rankus-seo': 28, 'wow-video': 12, 'pack-elec': 18 },
      };
    },

    // ============ Notes / Brain (idées en vrac) ============
    brain_list(payload) {
      const notes = [
        { id: 'n1', author: 'jordan', content: 'Tester un mailing samedi à 9h sur le segment Sophie & co.', category: 'idée', tags: ['mailing', 'test'], created_at: new Date(Date.now() - 86400_000).toISOString() },
        { id: 'n2', author: 'jordan', content: 'Penser à relancer Cabinet Dupont si pas de réponse vendredi.', category: 'todo', tags: ['relance'], remind_at: new Date(Date.now() + 86400_000 * 2).toISOString(), created_at: new Date(Date.now() - 172800_000).toISOString() },
        { id: 'n3', author: 'jordan', content: 'Nouvelle landing page Lagriffe : convertit 23% mieux que l\'ancienne.', category: 'win', tags: ['conversion', 'lagriffe'], created_at: new Date(Date.now() - 259200_000).toISOString() },
        { id: 'n4', author: 'jordan', content: 'Faire un cas client avec Boulangerie Lefèvre (+45% de commandes en ligne).', category: 'todo', tags: ['cas-client'], created_at: new Date(Date.now() - 345600_000).toISOString() },
        { id: 'n5', author: 'jordan', content: 'Étudier le pack "intelligence territoriale" pour les cabinets médicaux.', category: 'idée', tags: ['pack', 'santé'], created_at: new Date(Date.now() - 432000_000).toISOString() },
        { id: 'n6', author: 'jordan', content: 'Salon Élégance veut ajouter un module avis Google → vendre +', category: 'opp', tags: ['upsell'], created_at: new Date(Date.now() - 518400_000).toISOString() },
        { id: 'n7', author: 'jordan', content: 'Refondre l\'onboarding client : ajouter une checklist envoyée par mail jour 1.', category: 'todo', tags: ['onboarding'], created_at: new Date(Date.now() - 604800_000).toISOString() },
        { id: 'n8', author: 'jordan', content: 'Marc Lefèvre est super content : "votre équipe est top". Témoignage à demander.', category: 'win', tags: ['témoignage'], created_at: new Date(Date.now() - 691200_000).toISOString() },
      ];
      const status = (payload && payload.status) || 'all';
      if (status === 'all') return { ok: true, notes };
      return { ok: true, notes: notes.filter(n => n.category === status) };
    },

    // ============ Tracker (analytics sites + tracking d'ouverture mails) ============
    // Format attendu par config.js : sent_7d, opened_7d, open_rate_7d
    tracker_stats() {
      return {
        ok: true,
        // Tracking d'ouverture mails (config.js)
        sent_7d: 312,
        opened_7d: 134,
        open_rate_7d: 43.0,
        sent_30d: 1247,
        opened_30d: 528,
        open_rate_30d: 42.3,
        clicks_7d: 28,
        clicks_30d: 89,
        // Analytics sites (autre vue éventuelle)
        period_days: 30,
        visiteurs_uniques: 18420,
        pages_vues: 47830,
        taux_rebond: 38,
        temps_moyen_seconds: 142,
        conversions: 89,
      };
    },

    // ============ Multichannel actions (relances LinkedIn) ============
    // Format attendu par morning.js : prospect_name, prospect_city, prospect_industry, message
    multichannel_get_actions() {
      const items = [
        ['Sophie Dupont',    'Paris',         'Cabinet juridique',
         "Bonjour Sophie, j'ai vu votre cabinet à Paris — votre approche \"justice accessible\" résonne avec ce qu'on fait chez Triskell. Vous seriez ouverte à un échange de 15 min ?"],
        ['Marc Lefèvre',     'Plérin',        'Boulangerie artisanale',
         "Bonjour Marc, je suis passé devant votre boulangerie — votre vitrine est superbe. J'aide les commerces locaux à doubler leurs commandes en ligne. 15 min ?"],
        ['Camille Bernard',  'Nantes',        'Tatouage artistique',
         "Bonjour Camille, votre style néo-traditionnel est dingue. Je conçois des sites pour des artistes comme vous (cf. Atelier Missor). On en parle ?"],
        ['Antoine Petit',    'Rennes',        'Garage automobile',
         "Bonjour Antoine, j'ai vu votre garage sur Maps — top notes mais site daté. J'aide des garages à doubler leurs RDV. 15 min ?"],
        ['Léa Durand',       'Saint-Brieuc',  'Pharmacie',
         "Bonjour Léa, votre pharmacie a 4.8★ sur Google mais aucune prise de RDV en ligne. C'est exactement ce qu'on fait chez Triskell. On en parle ?"],
        ['Thomas Moreau',    'Brest',         'Studio yoga',
         "Bonjour Thomas, votre studio Yoga Soleil a une belle énergie sur Insta. Je conçois des sites qui convertissent vos abonnés en élèves. Intéressé ?"],
        ['Julie Lambert',    'Lannion',       'Restaurant',
         "Bonjour Julie, votre carte du Bistrot m'a fait saliver. J'aide les restos à booster leurs réservations en ligne. 15 min cette semaine ?"],
        ['Nicolas Rousseau', 'Vannes',        'Salon de coiffure',
         "Bonjour Nicolas, votre salon Élégance a un super bouche-à-oreille. Et si on traduisait ça en visibilité web ? 15 min pour vous montrer."],
      ];
      return {
        ok: true,
        actions: items.map((it, i) => ({
          id: `act-${i}`,
          prospect_name:     it[0],
          prospect_city:     it[1],
          prospect_industry: it[2],
          message:           it[3],
          search_url:        `https://www.google.com/search?q=${encodeURIComponent(it[0] + ' ' + it[1] + ' linkedin')}`,
          platform_url:      '',
        })),
      };
    },

    // ============ Santé système ============
    // Format attendu par health.js : summary + delivrabilité + workers (array)
    system_health() {
      return {
        ok: true,
        summary: { healthy: 9, warning: 0, error: 0 },
        "delivrabilité": {
          sent_24h: 18,
          sent_7d: 624,
          replies_7d: 89,
          reply_rate_7d: 14,
          smtp_configured: true,
          imap_configured: true,
        },
        workers: [
          { name: 'imap_replies',         label: 'Lecture des réponses IMAP', health: 'healthy', running: true, last_run_at: new Date(Date.now() - 60_000).toISOString(),  last_run_result: { processed: 4, errors: 0 }, last_error: '', extra: '4 nouvelles réponses traitées' },
          { name: 'auto_responder',       label: 'Réponse auto aux intéressés', health: 'healthy', running: true, last_run_at: new Date(Date.now() - 120_000).toISOString(), last_run_result: { processed: 4, errors: 0 }, last_error: '', extra: '1 brouillon préparé' },
          { name: 'drip',                 label: 'Relances drip', health: 'healthy', running: true, last_run_at: new Date(Date.now() - 240_000).toISOString(), last_run_result: { processed: 4, errors: 0 }, last_error: '', extra: '3 relances envoyées' },
          { name: 'post_sale',            label: 'Suivi après vente', health: 'healthy', running: true, last_run_at: new Date(Date.now() - 360_000).toISOString(), last_run_result: { processed: 4, errors: 0 }, last_error: '', extra: 'NPS J+30 envoyés (2)' },
          { name: 'lead_to_client',       label: 'Bascule prospects → clients', health: 'healthy', running: true, last_run_at: new Date(Date.now() - 480_000).toISOString(), last_run_result: { processed: 4, errors: 0 }, last_error: '', extra: '1 conversion détectée' },
          { name: 'multichannel_followup',label: 'Relances multi-canal LinkedIn', health: 'healthy', running: true, last_run_at: new Date(Date.now() - 600_000).toISOString(), last_run_result: { processed: 4, errors: 0 }, last_error: '', extra: '8 suggestions en file' },
          { name: 'dormant_recycler',     label: 'Recyclage des prospects dormants', health: 'healthy', running: true, last_run_at: new Date(Date.now() - 1800_000).toISOString(), last_run_result: { processed: 4, errors: 0 }, last_error: '', extra: '5/jour max respecté' },
          { name: 'stripe_poller',        label: 'Surveillance des paiements Stripe', health: 'healthy', running: true, last_run_at: new Date(Date.now() - 300_000).toISOString(), last_run_result: { processed: 4, errors: 0 }, last_error: '', extra: '2 paiements ce mois' },
          { name: 'scheduled_mails',      label: 'Envoi des mails programmés', health: 'healthy', running: true, last_run_at: new Date(Date.now() - 30_000).toISOString(), last_run_result: { processed: 4, errors: 0 }, last_error: '', extra: '3 mails en file pour demain' },
        ],
      };
    },

    // ============ Autopilot ============
    // Format attendu : config (objet libre), log (array de strings), stats (counters)
    autopilot_get_config() {
      return {
        ok: true,
        config: {
          mode: 'validation',
          source: 'sirene',
          naf_codes: ['56.10A', '47.24Z'],
          departments: ['22', '29', '35', '56'],
          max_per_day: 50,
          schedule_enabled: true,
          schedule_hour: 3,
        },
      };
    },
    autopilot_status() {
      const now = new Date();
      const t = (d) => d.toISOString().slice(11, 19);
      const log = [
        `[${t(now)}] ✓ 12 prospects qualifiés depuis Sirene`,
        `[${t(new Date(now - 60_000))}] ✓ Mail envoyé à Cabinet Dupont & Co (sophie@dupont-co.fr)`,
        `[${t(new Date(now - 180_000))}] ✓ Réponse classifiée "intéressé" — Boulangerie Lefèvre`,
        `[${t(new Date(now - 360_000))}] ✓ 8 nouveaux prospects scrapés (Maps · Plérin)`,
        `[${t(new Date(now - 600_000))}] ✓ Mail envoyé à Atelier Missor (camille@missor.fr)`,
        `[${t(new Date(now - 900_000))}] ✓ 5 prospects enrichis (email trouvé via clearbit)`,
        `[${t(new Date(now - 1500_000))}] ✓ Convoi terminé : 18 mails envoyés, 0 erreur`,
      ];
      return {
        ok: true,
        running: true,
        log,
        log_len: log.length,
        stats: {
          searched: 124,
          enriched: 87,
          drafts_sent: 18,
          drafts_pending: 3,
          replies_detected: 4,
          errors: [],
        },
      };
    },

    // ============ Timeline d'un prospect ============
    prospect_timeline(payload) {
      const id = (payload && payload.id) || 'demo';
      const now = Date.now();
      const t = (delta) => new Date(now - delta).toISOString();
      return {
        ok: true,
        prospect: {
          id, name: 'Boulangerie Lefèvre', email: 'contact@boulangerie-lefevre.fr',
          city: 'Plérin', country: 'France', industry: 'Boulangerie',
          website: 'https://boulangerie-lefevre.fr', status: 'replied',
          created_at: t(7 * 86400_000), source_name: 'Sirene',
        },
        events: [
          { ts: t(7*86400_000), type: 'prospect_added', icon: '🔍',
            title: 'Ajouté à ta base', subtitle: 'Source : Sirene' },
          { ts: t(6*86400_000), type: 'email_sent', icon: '✉',
            title: 'Mail envoyé', subject: 'Votre site, on en parle ?',
            body_excerpt: 'Bonjour, j\'ai vu que votre boulangerie n\'avait pas encore de site moderne…' },
          { ts: t(5*86400_000), type: 'email_opened', icon: '👁',
            title: 'Mail ouvert par le prospect',
            subject: 'Votre site, on en parle ?' },
          { ts: t(3*86400_000), type: 'reply_received', icon: '📨',
            title: 'Réponse reçue — Intéressé', category: 'interested',
            subject: 'Re: Votre site, on en parle ?',
            body_excerpt: 'Effectivement on y pense depuis un moment, vous proposez quoi exactement et à quel prix ?' },
          { ts: t(2.5*86400_000), type: 'lead_converted', icon: '🎯',
            title: 'Devenu projet client', subtitle: 'Lagriffe Studio',
            project_id: 'demo-proj-1' },
          { ts: t(1*86400_000), type: 'payment', icon: '💳',
            title: 'Paiement reçu', subtitle: '490.00 EUR' },
          { ts: t(0.9*86400_000), type: 'delivered', icon: '🎁',
            title: 'Kit de livraison envoyé', subtitle: 'Lagriffe Studio' },
        ],
        has_project: true,
      };
    },

    // ============ Setup status (cockpit checklist) ============
    setup_status() {
      const items = [
        { key: 'supabase', label: 'Base partagée connectée', status: 'ok',
          why: '', goto: { view: 'config', tab: 'account' } },
        { key: 'smtp', label: "Adresse mail d'envoi", status: 'ok',
          why: '', goto: { view: 'config', tab: 'mails' } },
        { key: 'imap', label: 'Lecture de la boîte mail', status: 'ok',
          why: '', goto: { view: 'config', tab: 'mails' } },
        { key: 'ai', label: "Service d'intelligence artificielle", status: 'ok',
          why: '', goto: { view: 'config', tab: 'ai' } },
        { key: 'stripe', label: 'Stripe — encaissement automatique', status: 'missing',
          why: "Sans clé Stripe, l'app ne voit pas les paiements et ne déclenche pas la livraison.",
          goto: { view: 'config', tab: 'integrations' } },
        { key: 'stripe_mapping', label: 'Lien Stripe ↔ kits de livraison', status: 'warn',
          why: "Sans ce lien, tous les paiements déclenchent le kit générique au lieu du bon kit produit.",
          goto: { view: 'config', tab: 'integrations' } },
      ];
      const sum = { ok: 0, warn: 0, missing: 0 };
      items.forEach(i => { sum[i.status]++; });
      return { ok: true, items, summary: sum };
    },

    // ============ Modes simples (cockpit) ============
    get_simple_modes() {
      const s = (this._demo_state ||= {});
      return {
        ok: true,
        prospection: s.prospection || 'validation',
        reponses:    s.reponses    || 'validation',
      };
    },
    set_simple_mode(payload) {
      const s = (this._demo_state ||= {});
      const kind = (payload && payload.kind) || '';
      const mode = (payload && payload.mode) || '';
      if (!['prospection', 'reponses'].includes(kind)) {
        return { ok: false, error: 'kind invalide' };
      }
      if (!['direct', 'validation'].includes(mode)) {
        return { ok: false, error: 'mode invalide' };
      }
      s[kind] = mode;
      return { ok: true };
    },

    // ============ Messages internes Jordan/Thomas ============
    messages_count_unread() { return { ok: true, count: 2 }; },
    messages_list() {
      const now = Date.now();
      return {
        ok: true,
        messages: [
          { id: 'm1', body: "J'ai bouclé la maquette pour Cabinet Dupont. Tu valides ?", created_at: new Date(now - 7200_000).toISOString(), sender_id: 'thomas' },
          { id: 'm2', body: "Top, c'est validé. Tu peux livrer.",                          created_at: new Date(now - 6600_000).toISOString(), sender_id: 'jordan' },
          { id: 'm3', body: "Marc Lefèvre vient de payer. Lance le kit ?",                 created_at: new Date(now - 1800_000).toISOString(), sender_id: 'thomas' },
          { id: 'm4', body: "Déjà parti. Bien joué !",                                     created_at: new Date(now - 1500_000).toISOString(), sender_id: 'jordan' },
          { id: 'm5', body: "RDV avec Atelier Missor dans 1h, je te tiens au courant.",    created_at: new Date(now - 600_000).toISOString(),  sender_id: 'thomas' },
        ],
      };
    },
    messages_me() { return { ok: true, user_id: 'jordan', display_name: 'Jordan' }; },
    messages_other_user() { return { ok: true, other: { user_id: 'thomas', display_name: 'Thomas' } }; },
    messages_peer_typing() { return { ok: true, typing: false }; },

    // ============ Allô Claude — conseil interactif ============
    claude_ask(payload) {
      const q = (payload && payload.question) || '';
      if (q) {
        return {
          ok: true, demo: true,
          urgency: 'medium',
          headline: 'Bonne piste — voici ce que je creuserais',
          advice: `Tu as posé : « ${q} »\n\nVu l'état actuel de ta boîte (12 prospects intéressés à recontacter, 18 mails envoyés aujourd'hui), je commencerais par les réponses positives — c'est là que se trouvent tes meilleures chances de conversion. Pour le reste, le pipeline tourne tout seul.`,
          suggested_view: 'replies',
          suggested_action_label: 'Voir les réponses',
        };
      }
      return {
        ok: true, demo: true,
        urgency: 'medium',
        headline: 'Tu as 12 prospects intéressés à recontacter aujourd\'hui',
        advice: "Ils ont répondu positivement à un de tes mails — c'est ta meilleure piste pour transformer. Ouvre la vue Réponses, lis ce qu'ils ont écrit, et envoie-leur le brouillon que l'app a préparé en l'adaptant si besoin.\n\nPas plus de 2 heures avant de répondre — au-delà, ils refroidissent.",
        suggested_view: 'replies',
        suggested_action_label: 'Voir les réponses',
      };
    },
    claude_consume_pending() {
      // Aucun conseil proactif en attente en mode démo
      return null;
    },

    // ============ Réglages / Configurations ============
    get_settings() {
      return {
        ok: true,
        theme: 'dark',
        ai: { api_keys: { anthropic: 'sk-ant-***-demo', google: 'AIza***-demo' } },
        outreach: { from_email: 'contact@triskell-studio.fr', from_name: 'Jordan Bourillot' },
      };
    },
    auth_status() {
      return { ok: true, connected: true, user_id: 'jordan', display_name: 'Jordan', email: 'contact@triskell-studio.fr' };
    },
    lead_to_client_get_config() {
      return { ok: true, config: { enabled: true, mode: 'strong_signals', last_run_at: new Date(Date.now() - 1800_000).toISOString() } };
    },
    stripe_get_config() {
      return { ok: true, config: { enabled: true, secret_key_set: true, last_run_at: new Date(Date.now() - 300_000).toISOString(), payments_count_30d: 14 } };
    },
    phantombuster_get_config() {
      return { ok: true, config: { enabled: false, api_key_set: false } };
    },
    tracker_get_config() {
      return { ok: true, config: { enabled: true, domain_set: true } };
    },

    // ============ Delivery Kits ============
    delivery_kits_list() {
      return {
        ok: true,
        kits: {
          'pack-elec': {
            product_name: 'Pack Électricien Pro',
            welcome: {
              subject: "Bienvenue chez Pack Électricien — voici tout ce qu'il vous faut",
              body: "Bonjour {client_name},\n\nMerci pour votre confiance. Vous trouverez ci-dessous l'accès complet à Pack Électricien Pro.\n\n{deliverables_list}\n\nÀ toute question, je suis là.\n\n{signature}",
            },
            follow_ups: [
              { days: 3,  subject: "Comment se passe la prise en main ?",  body: "Bonjour {client_name},\nPetit point 3 jours après votre achat — tout se passe bien ?" },
              { days: 14, subject: "Une astuce qui peut vous faire gagner du temps", body: "Bonjour {client_name},\nUne astuce que j'utilise tous les jours…" },
              { days: 30, subject: "Vous reviendriez ? (1 question)",      body: "Bonjour {client_name},\nSi vous aviez à recommander Pack Élec à un confrère, vous le feriez ?" },
            ],
          },
          'studio-pdf': {
            product_name: 'Studio PDF',
            welcome: {
              subject: "Studio PDF — vos templates sont prêts",
              body: "Bonjour {client_name},\n\nVoici l'accès à votre Studio PDF.\n\n{deliverables_list}\n\n{signature}",
            },
            follow_ups: [
              { days: 7,  subject: "Premier rapport généré ?",   body: "Bonjour {client_name}, tu as pu tester ton premier rapport ?" },
              { days: 30, subject: "Témoignage rapide ?",        body: "Si Studio PDF te plaît, 2 phrases comme témoignage me feraient très plaisir." },
            ],
          },
          'obelisk': {
            product_name: 'Obelisk',
            welcome: {
              subject: "Obelisk — bienvenue dans la prospection multi-plateformes",
              body: "Bonjour {client_name},\n\nVoici votre accès Obelisk.\n\n{deliverables_list}\n\n{signature}",
            },
            follow_ups: [
              { days: 5,  subject: "Premier scrape lancé ?",     body: "Tu as pu lancer ton premier scrape sur Obelisk ?" },
              { days: 30, subject: "Bilan du mois",              body: "Petit point un mois après — combien de prospects extraits ?" },
            ],
          },
        },
      };
    },
    delivery_kit_preview(payload) {
      const key = (payload && payload.product_key) || 'pack-elec';
      const all = DemoMode._fake.delivery_kits_list();
      const kit = (all.kits || {})[key];
      if (!kit) return { ok: false, error: 'Kit introuvable' };
      return { ok: true, welcome: kit.welcome, follow_ups: kit.follow_ups };
    },

    // ============ A/B Test ============
    ab_get_results() {
      const now = Date.now();
      return {
        ok: true,
        campaigns: [
          {
            id: 'ab1',
            name: "Premier contact froid — boulangeries",
            active: true,
            verdict: 'significant',
            winner_variant_id: 'v2',
            created_at: new Date(now - 14 * 86400_000).toISOString(),
            variants: [
              { id: 'v1', subject: "Une idée pour {company_name}",        sent_count: 142, reply_count: 8,  reply_rate: 5.6,  enough_data: true },
              { id: 'v2', subject: "{company_name} — 30 secondes ?",      sent_count: 138, reply_count: 18, reply_rate: 13.0, enough_data: true },
              { id: 'v3', subject: "Petit cadeau pour {company_name}",    sent_count: 140, reply_count: 6,  reply_rate: 4.3,  enough_data: true },
            ],
          },
          {
            id: 'ab2',
            name: "Relance — cabinets médicaux",
            active: true,
            verdict: 'not_enough_data',
            winner_variant_id: null,
            created_at: new Date(now - 5 * 86400_000).toISOString(),
            variants: [
              { id: 'v1', subject: "On garde le contact ?",               sent_count: 22, reply_count: 1, reply_rate: 4.5,  enough_data: false },
              { id: 'v2', subject: "Une mise à jour pour vous",           sent_count: 21, reply_count: 2, reply_rate: 9.5,  enough_data: false },
            ],
          },
        ],
      };
    },

    // ============ Apps catalog (Spotlight) ============
    get_apps_catalog() {
      return {
        ok: true,
        apps: [
          { id: 'lagriffe',  name: 'Lagriffe Studio', tagline: 'Sites web sur mesure',     category: 'Triskell', url: 'https://lagriffe-studio.fr' },
          { id: 'rankus',    name: 'RankUs Studio',   tagline: 'SEO autonome',             category: 'Triskell', url: 'https://rankus-studio.fr' },
          { id: 'wow',       name: 'Studio WoW',      tagline: 'Vidéos qui claquent',      category: 'Triskell', url: 'https://studio-wow.fr' },
          { id: 'antavirus', name: 'Le Druide',       tagline: 'Antivirus grand public',   category: 'Triskell', url: 'https://antavirus.fr' },
          { id: 'obelisk',   name: 'Obelisk',         tagline: 'Prospection multi-plateformes', category: 'Outils', url: '' },
          { id: 'pack-elec', name: 'Pack Électricien',tagline: 'Tout pour les électriciens',category: 'Outils', url: '' },
        ],
      };
    },

    // ============ Onboarding — déjà fait en démo ============
    get_current_user() {
      return { ok: true, needs_onboarding: false, first_name: 'Jordan', full_name: 'Jordan Bourillot', email: 'contact@triskell-studio.fr' };
    },
    get_user_name() {
      return 'Jordan';
    },

    // ============ Revenue overview ============
    revenue_overview() {
      // Mois en cours = mai 2026 (cf. memory currentDate)
      return {
        ok: true,
        current_month:  { label: 'mai 2026',   total_cents: 8324000, transactions_count: 14 },
        previous_month: { label: 'avril 2026', total_cents: 7682000, transactions_count: 12 },
        last_7_days:    { total_cents: 2140000, transactions_count: 4 },
        last_30_days:   { total_cents: 8120000, transactions_count: 14 },
        top_clients_month: [
          { client_name: 'Cabinet Dupont & Co',     client_email: 'sophie@dupont-co.fr',         product: 'Refonte complète',     amount_cents: 1450000, source: 'stripe' },
          { client_name: 'Hôtel Le Cèdre',          client_email: 'contact@hotel-le-cedre.fr',   product: 'Site + réservation',   amount_cents: 1380000, source: 'stripe' },
          { client_name: 'Boulangerie Lefèvre',     client_email: 'marc@boulangerie-lefevre.fr', product: 'Pack Sites + SEO',     amount_cents:  680000, source: 'stripe' },
          { client_name: 'Pharmacie Centrale',      client_email: 'lea@pharmacie-centrale.fr',   product: 'Site + prise RDV',     amount_cents:  620000, source: 'stripe' },
          { client_name: 'Studio Yoga Soleil',      client_email: 'thomas@yogasoleil.fr',        product: 'Refonte + booking',    amount_cents:  580000, source: 'stripe' },
          { client_name: 'Cabinet Médical Nord',    client_email: 'olivier@medical-nord.fr',     product: 'Site + prise RDV',     amount_cents:  520000, source: 'stripe' },
          { client_name: 'École Andante',           client_email: 'manon@andante-musique.fr',    product: 'Site + paiement',      amount_cents:  480000, source: 'stripe' },
          { client_name: 'Atelier Missor',          client_email: 'camille@missor.fr',           product: 'Site vitrine + SEO',   amount_cents:  450000, source: 'stripe' },
          { client_name: 'Pack Électricien (AppSumo)', client_email: 'electricien@example.com',  product: 'Pack Électricien Pro', amount_cents:  240000, source: 'appsumo' },
          { client_name: 'Studio PDF (paiement manuel)', client_email: 'studio@example.com',     product: 'Studio PDF',           amount_cents:  180000, source: 'manual' },
        ],
        by_source_month: {
          'stripe':   7480000,
          'appsumo':   480000,
          'manual':    364000,
        },
        by_product_month: {
          'Sites web':       4920000,
          'SEO (RankUs)':    1840000,
          'Vidéo (WoW)':      820000,
          'Pack Électricien': 480000,
          'Studio PDF':       264000,
        },
        forecast: {
          projected_month_cents:   12450000,
          confidence_low_cents:     9960000,
          confidence_high_cents:   14940000,
          pipeline_count:          13,
          conversion_rate_pct:     35,
        },
      };
    },

    // (tracker_stats déjà défini plus haut)

    // ============ Funnel / Pipeline (apiPrefix) ============

    // ============ Prospection en direct (démo) ============
    prospect_generate_mail(payload) {
      const cat = (payload && payload.category) || 'business';
      const sub = (payload && payload.subtype) || 'personalized';
      const url = (payload && payload.url) || 'https://demo.lagriffe-studio.fr';
      if (cat === 'business' && sub === 'template') {
        return {
          ok: true,
          target_name: 'Boulangerie Lefèvre',
          used_template: 'Démo générique boulangerie',
          subject: 'Une démo de site pensée pour les boulangeries comme la vôtre',
          body_html: '<p>Bonjour Marc,</p>'
            + '<p>Je vous écris parce que je viens de boucler un <strong>modèle de site spécialement pensé pour les boulangeries artisanales</strong>. Pas votre site personnalisé pour l\'instant — c\'est un modèle générique qui montre le style et les fonctionnalités possibles (catalogue produits, prise de commande pour les fêtes, mise en avant Avis Google, fiche Maps optimisée).</p>'
            + '<p><img src="cid:prospect_preview" alt="Aperçu du site modèle" style="max-width:100%;height:auto;display:block;border-radius:8px;border:1px solid #e5e7eb;"></p>'
            + `<p>Découvrez le modèle : <a href="${url}"><strong>Voir la démo</strong></a>.</p>`
            + '<p>Si l\'esprit vous plaît, je peux le <strong>personnaliser avec vos vraies infos</strong> (nom, photos, vos kouign-amann préférés, vos horaires) en 1 ou 2 jours. 15 min pour qu\'on en discute ?</p>',
          source_url: url, category: cat, subtype: sub,
          screenshot_b64: '', screenshot_content_type: '',
        };
      }
      if (cat === 'celebrity' && sub === 'sport') {
        return {
          ok: true,
          target_name: 'Cédric Doumbé',
          used_template: 'Approche sportif',
          subject: 'Cédric — un site pensé pour la suite de votre carrière',
          body_html: '<p>Bonjour Cédric,</p>'
            + '<p>J\'ai suivi votre dernier combat — la lecture du round 2 était impressionnante de sang-froid. J\'ai pris quelques heures pour <strong>concevoir un site qui reflète votre identité de combattant</strong> : palmarès en page d\'accueil, calendrier des prochains événements, espace partenaires et fan-zone.</p>'
            + '<p><img src="cid:prospect_preview" alt="Aperçu du site" style="max-width:100%;height:auto;display:block;border-radius:8px;border:1px solid #e5e7eb;"></p>'
            + `<p><a href="${url}"><strong>Découvrir le site</strong></a></p>`
            + '<p>Pas un site \"de boxeur générique\" — un outil au service de votre carrière. Ouvrez quand vous avez 30 secondes entre deux séances, dites-moi ce que vous en pensez.</p>',
          source_url: url, category: cat, subtype: sub,
          screenshot_b64: '', screenshot_content_type: '',
        };
      }
      if (cat === 'celebrity' && sub === 'influencer') {
        return {
          ok: true,
          target_name: 'Squeezie',
          used_template: 'Approche créateur de contenu',
          subject: 'Une vitrine web qui colle à ton univers',
          body_html: '<p>Salut Lucas,</p>'
            + '<p>J\'ai regardé ta dernière série Qui est l\'imposteur et le format Stories. J\'ai pris quelques heures pour <strong>imaginer une vitrine web qui colle à ton univers de contenu</strong> : tes derniers projets en page d\'accueil, lien direct vers tes plateformes, espace partenariats / brand deals et un coin newsletter pour ta communauté.</p>'
            + '<p><img src="cid:prospect_preview" alt="Aperçu du site" style="max-width:100%;height:auto;display:block;border-radius:8px;border:1px solid #e5e7eb;"></p>'
            + `<p><a href="${url}"><strong>Ouvrir la démo</strong></a></p>`
            + '<p>Pas un site \"de YouTubeur classique\" — quelque chose qui prolonge ton identité visuelle. Ouvre-le entre deux montages, dis-moi ce que tu en penses.</p>',
          source_url: url, category: cat, subtype: sub,
          screenshot_b64: '', screenshot_content_type: '',
        };
      }
      if (cat === 'celebrity') {
        // Fallback générique célébrité (si pas de subtype)
        return {
          ok: true,
          target_name: 'Doumbé',
          used_template: 'Approche créateur',
          subject: 'Cédric — un site que j\'ai pensé pour vous',
          body_html: '<p>Bonjour Cédric,</p>'
            + '<p>Suite à votre dernier post Instagram, j\'ai imaginé à quoi pourrait ressembler votre univers sur le web. J\'ai pris quelques heures pour <strong>concevoir un site qui colle à votre ligne</strong>.</p>'
            + '<p><img src="cid:prospect_preview" alt="Aperçu du site" style="max-width:100%;height:auto;display:block;border-radius:8px;border:1px solid #e5e7eb;"></p>'
            + `<p><a href="${url}"><strong>Découvrir le site</strong></a>. Dites-moi ce que vous en pensez.</p>`,
          source_url: url, category: cat,
          screenshot_b64: '', screenshot_content_type: '',
        };
      }
      return {
        ok: true,
        target_name: 'Boulangerie Lefèvre',
        used_template: 'Approche commerce local',
        subject: 'Boulangerie Lefèvre — une première ébauche pour vous',
        body_html: '<p>Bonjour Marc,</p>'
          + '<p>J\'ai commencé à ébaucher un site pour votre boulangerie en m\'appuyant sur ce que j\'ai trouvé en public — votre fiche Google, vos horaires, votre adresse à Plérin et quelques produits visibles sur vos réseaux. <strong>C\'est une première version</strong>, pas un site finalisé : il manque vos vraies photos, vos textes définitifs et les détails qu\'on caleraient ensemble.</p>'
          + '<p><img src="cid:prospect_preview" alt="Aperçu du site" style="max-width:100%;height:auto;display:block;border-radius:8px;border:1px solid #e5e7eb;"></p>'
          + `<p><a href="${url}"><strong>Voir l\'ébauche</strong></a></p>`
          + '<p>Si l\'idée vous plaît, on prend <strong>15 min en visio</strong> pour affiner ensemble (un brief court, j\'intègre vos vraies infos), et seulement après on bascule sur votre vrai domaine. Sinon, vous repartez avec les idées et c\'est cadeau.</p>',
        source_url: url, category: cat,
        screenshot_b64: '',
        screenshot_content_type: '',
      };
    },

    // ============ Funnel / Pipeline (apiPrefix) ============
    // Pour lagriffe / rankus / wow — chacun a un pipeline avec sa propre méthode.
    lagriffe_list_intakes() {
      return { ok: true, intakes: DemoMode._fakeIntakes('lagriffe') };
    },
    rankus_list_intakes() {
      return { ok: true, intakes: DemoMode._fakeIntakes('rankus') };
    },
    wow_list_intakes() {
      return { ok: true, intakes: DemoMode._fakeIntakes('wow') };
    },
  },

  // Génère ~30 projets clients répartis dans 4 colonnes (kanban)
  _fakeProjects() {
    if (this.__cachedProjects) return this.__cachedProjects;
    const buckets = { briefing: [], in_progress: [], delivered: [], closed: [] };
    const companies = [
      ['Boulangerie Lefèvre', 'Marc Lefèvre',     'marc@boulangerie-lefevre.fr', 'Site vitrine + SEO',  1800],
      ['Cabinet Dupont & Co', 'Sophie Dupont',    'sophie@dupont-co.fr',         'Refonte complète',    4200],
      ['Atelier Missor',      'Camille Bernard',  'camille@missor.fr',           'Site vitrine',         980],
      ['Garage Auto Plus',    'Antoine Petit',    'antoine@autoplus.fr',         'Pack Maps + Site',    1450],
      ['Pharmacie Centrale',  'Léa Durand',       'lea@pharmacie-centrale.fr',   'Site + prise RDV',    2800],
      ['Studio Yoga Soleil',  'Thomas Moreau',    'thomas@yogasoleil.fr',        'Refonte + booking',   3200],
      ['Restaurant Le Bistrot','Julie Lambert',   'julie@bistrot.fr',            'Carte en ligne',      1650],
      ['Salon Élégance',      'Nicolas Rousseau', 'nicolas@elegance.fr',         'Pack Sites',          1200],
      ['École Andante',       'Manon Vincent',    'manon@andante-musique.fr',    'Site + paiement',     2400],
      ['Cabinet Animo',       'Pierre Fontaine',  'pierre@animo-veto.fr',        'Site + RDV',          2100],
      ['Pâtisserie Sucré',    'Émilie Dubois',    'emilie@sucresale.fr',         'Catalogue',           1380],
      ['Optique Vision',      'Hugo Robin',       'hugo@optique-vision.fr',      'Pack Maps + Site',    1850],
      ['Plombier Express',    'Sarah Mercier',    'sarah@plombier-express.fr',   'Site + devis ligne',  1100],
      ['Fleuriste Pétale',    'Lucas Blanc',      'lucas@petale-fleurs.fr',      'Site vitrine',         890],
      ['Architecte Forme',    'Chloé Faure',      'chloe@architecte-forme.fr',   'Portfolio + blog',    2950],
      ['Café Litéraire',      'Maxime Garnier',   'maxime@cafe-litteraire.fr',   'Site + agenda',       1620],
      ['Yoga Bien-Être',      'Inès Lacroix',     'ines@yoga-bienetre.fr',       'Refonte',             1380],
      ['Cabinet Médical Nord','Olivier Roy',      'olivier@medical-nord.fr',     'Site + prise RDV',    3100],
      ['Auto-École Drive',    'Élise Marchand',   'elise@autoecole-drive.fr',    'Pack Maps',            980],
      ['Hôtel Le Cèdre',      'Vincent Carpentier','contact@hotel-le-cedre.fr',  'Site + réservation',  4800],
    ];
    const colKeys = ['briefing', 'in_progress', 'delivered', 'closed'];
    const due = (offsetDays) => {
      const d = new Date(Date.now() + offsetDays * 86400_000);
      return `${String(d.getDate()).padStart(2, '0')}/${String(d.getMonth() + 1).padStart(2, '0')}`;
    };
    companies.forEach((c, i) => {
      // Répartit : 5 briefing, 8 in_progress, 5 delivered, reste closed
      let col;
      if (i < 5) col = 'briefing';
      else if (i < 13) col = 'in_progress';
      else if (i < 17) col = 'delivered';
      else col = 'closed';
      buckets[col].push({
        id: `proj-${i}`,
        title: c[3],
        product_name: c[3],
        client_name: c[1],
        client_company: c[0],
        client_email: c[2],
        amount_cents: c[4] * 100,
        due_date: col === 'briefing' || col === 'in_progress' ? due(3 + (i % 10)) : null,
        status: col,
        created_at: new Date(Date.now() - (i + 1) * 86400_000 * 3).toISOString(),
      });
    });
    this.__cachedProjects = buckets;
    return buckets;
  },

  // Pipeline intakes (prospects qualifiés) pour Lagriffe/RankUs/WoW
  _fakeIntakes(brand) {
    const stages = {
      lagriffe: ['nouveau', 'qualified', 'devis', 'won', 'lost'],
      rankus:   ['audit', 'proposition', 'devis', 'won', 'lost'],
      wow:      ['brief', 'storyboard', 'tournage', 'livre', 'closed'],
    }[brand] || ['nouveau', 'qualified', 'devis', 'won', 'lost'];
    const intakes = [];
    const seedNames = [
      'Cabinet Dupont', 'Boulangerie Lefèvre', 'Atelier Missor', 'Garage Plus', 'Pharma Central',
      'Yoga Soleil', 'Bistrot Léa', 'Salon Élégance', 'École Andante', 'Cabinet Animo',
      'Sucré Salé', 'Optique Vision', 'Plombier Express', 'Fleuriste Pétale', 'Architecte Forme',
    ];
    for (let i = 0; i < 15; i++) {
      intakes.push({
        id: `${brand}-i-${i}`,
        company: seedNames[i],
        contact_name: ['Marc', 'Sophie', 'Léa', 'Julie', 'Nicolas'][i % 5] + ' ' + ['Dupont', 'Bernard', 'Lambert'][i % 3],
        email: `contact${i}@${seedNames[i].toLowerCase().replace(/[^a-z]/g, '')}.fr`,
        stage: stages[i % stages.length],
        amount: 800 + (i * 250),
        created_at: new Date(Date.now() - i * 86400_000).toISOString(),
        score: 70 + (i % 30),
      });
    }
    return intakes;
  },

  // Génère 60 mails fictifs (mémoïsé en session)
  _fakeMails() {
    if (this.__cachedMails) return this.__cachedMails;
    const firstnames = ['Sophie', 'Marc', 'Camille', 'Antoine', 'Léa', 'Thomas', 'Julie', 'Nicolas', 'Manon', 'Pierre', 'Émilie', 'Hugo', 'Sarah', 'Lucas', 'Chloé', 'Maxime'];
    const lastnames  = ['Dupont', 'Lefèvre', 'Bernard', 'Petit', 'Durand', 'Moreau', 'Lambert', 'Rousseau', 'Vincent', 'Fontaine', 'Dubois', 'Robin', 'Mercier', 'Blanc', 'Faure'];
    const companies  = ['Boulangerie Lefèvre', 'Cabinet Dupont & Co', 'Atelier Missor', 'Garage Auto Plus', 'Pharmacie Centrale', 'Studio Yoga Soleil', 'Restaurant Le Bistrot', 'Salon de coiffure Élégance', 'École de musique Andante', 'Cabinet vétérinaire Animo', 'Pâtisserie Sucré Salé', 'Optique Vision', 'Fleuriste Pétale', 'Plombier Express', 'Architecte Forme'];
    const subjects = [
      'Demande de devis pour refonte site',
      'Re: Proposition commerciale',
      'Question sur le pack SEO',
      'Validation maquette',
      'RDV de la semaine prochaine ?',
      'Facture août — paiement effectué',
      'Re: Suivi du projet',
      'Avis Google : 5 étoiles ⭐',
      'Question hébergement',
      'Renouvellement contrat',
      'Pouvez-vous me rappeler ?',
      'Photo manquante pour la page Équipe',
      'Re: Re: Le devis vous convient ?',
      'Témoignage client',
      'Migration depuis Wix',
    ];
    const previews = [
      'Bonjour Jordan, suite à notre échange de la semaine dernière, je suis très intéressé par votre proposition…',
      'Merci pour le rendez-vous, le projet me convient parfaitement. Quand est-ce qu\'on commence ?',
      'Petite question pratique avant de signer : est-ce que le pack inclut la maintenance la première année ?',
      'La maquette est top, j\'adore ! Juste un détail sur la couleur du header, sinon c\'est parfait.',
      'Bonjour, est-ce que vous seriez disponible jeudi 14 h pour faire un point sur l\'avancement ?',
      'J\'ai fait le virement ce matin, vous devriez le recevoir d\'ici demain.',
      'Tout fonctionne nickel, je viens de tester le formulaire et les emails arrivent bien.',
      'Très satisfait du résultat, je viens de laisser un avis Google. Bonne continuation !',
      'Combien de boîtes mail puis-je créer avec l\'hébergement inclus ?',
      'Je confirme le renouvellement pour un an supplémentaire, merci !',
    ];
    const now = Date.now();
    const out = [];
    for (let i = 0; i < 60; i++) {
      const f = firstnames[i % firstnames.length];
      const l = lastnames[(i * 3) % lastnames.length];
      const c = companies[i % companies.length];
      const isReply = i % 3 !== 0;
      const ts = new Date(now - i * 3600_000 * (1 + (i % 5))).toISOString();
      out.push({
        id: 'demo-' + i,
        kind: isReply ? 'reply_received' : 'email_sent',
        ts,
        subject: subjects[i % subjects.length],
        body: previews[i % previews.length],
        message_id: `<demo-${i}@triskell-studio.fr>`,
        extra: {
          from: `${f.toLowerCase()}.${l.toLowerCase()}@${c.toLowerCase().replace(/[^a-z]/g, '')}.fr`,
          to: 'contact@triskell-studio.fr',
          account_id: 'primary',
          sender_name: `${f} ${l} (${c})`,
          has_html: true,
          classification: isReply
            ? (i % 4 === 0 ? 'Prospect intéressé' : (i % 4 === 1 ? 'Client existant' : (i % 4 === 2 ? 'Demande de RDV' : 'Question rapide')))
            : 'Mail envoyé',
        },
      });
    }
    this.__cachedMails = out;
    return out;
  },
};

window.DemoMode = DemoMode;

// Affiche la bannière au boot si activé
window.addEventListener('DOMContentLoaded', () => {
  try { DemoMode.ensureBanner(); } catch (e) {}
  // Vigie : ré-injecte le bandeau s'il disparaît (vue qui réécrit le haut
  // de page, fin de « Masquer 30 sec », rechargement pendant le masquage).
  try { DemoMode._startBannerWatch(); } catch (e) {}
});
