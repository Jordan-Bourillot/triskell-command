/* DemoMode — mode démo pour générer des visuels promotionnels.
 *
 * Quand activé :
 *   - Aucun appel "destructif" (envoi mail, save, delete) ne part au serveur ;
 *     l'API retourne un faux succès silencieux.
 *   - Certaines listes (Matinale, mails reçus, etc.) sont surchargées avec des
 *     données fictives crédibles, pour que les screenshots montrent une boîte
 *     qui tourne à plein régime.
 *   - Bandeau "MODE DÉMO" visible en haut, masquable temporairement (30 sec)
 *     pour la capture d'écran via un bouton "Masquer 30 sec".
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
    // Bannière temporairement masquée pour screenshot ?
    try {
      const until = parseInt(sessionStorage.getItem(this.HIDE_BANNER_UNTIL) || '0', 10);
      if (until && Date.now() < until) return;
    } catch (e) {}
    if (document.getElementById('demo-banner')) return;

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
        — aucune action n'est réelle, les données affichées sont fictives.
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
    document.body.style.paddingTop = '34px';

    banner.querySelector('#demo-hide-btn').onclick = () => {
      try { sessionStorage.setItem(this.HIDE_BANNER_UNTIL, String(Date.now() + 30_000)); } catch (e) {}
      this._removeBanner();
      setTimeout(() => this.ensureBanner(), 30_000);
    };
    banner.querySelector('#demo-off-btn').onclick = () => this.setOn(false);
  },
  _removeBanner() {
    const b = document.getElementById('demo-banner');
    if (b) {
      b.remove();
      document.body.style.paddingTop = '';
    }
  },

  // ----- Interception API -----
  // Méthodes "read" qui passent toujours au serveur (jamais bloquées)
  isReadMethod(method) {
    return /^(get|is|list|fetch|check|me)_/.test(method)
        || /_(list|get|status|count|search|fetch|preview)$/.test(method)
        || ['boot', 'me', 'auth_status'].includes(method);
  },
  // Méthodes "write" qu'on remplace par un faux succès silencieux
  isWriteMethod(method) {
    if (!method) return false;
    return /^(save|delete|remove|set|create|add|push|migrate|reset|sync|seed)_/.test(method)
        || /_(save|delete|remove|send|set|create|add|upload|update|reset|migrate|schedule|cancel)$/.test(method)
        || method === 'mail_send'
        || method === 'mail_send_reply'
        || method === 'mail_schedule'
        || method === 'mail_scheduled_cancel'
        || method.includes('_send_')
        || ['avatar_upload', 'push_subscribe', 'push_test', 'push_unsubscribe',
            'claude_ask', 'claude_consume_pending'].includes(method);
  },

  /** Intercepte un appel API.
   *  Retourne { handled: true, result } si on prend la main,
   *  ou { handled: false } pour laisser passer au serveur. */
  intercept(method, payload) {
    if (!this.isOn()) return { handled: false };
    // Whitelist explicite read → toujours laisser passer
    if (this.isReadMethod(method) && !this._fake[method]) {
      return { handled: false };
    }
    // Données fictives pour méthodes "list" ciblées
    if (this._fake[method]) {
      try { return { handled: true, result: this._fake[method](payload) }; }
      catch (e) { console.warn('demo fake error', method, e); return { handled: false }; }
    }
    // Write → faux succès silencieux
    if (this.isWriteMethod(method)) {
      return { handled: true, result: { ok: true, demo: true, message_id: 'demo-' + this._rid() } };
    }
    return { handled: false };
  },
  _rid() { return Math.random().toString(36).slice(2, 12); },

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
    mail_templates_list() {
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
              body: 'Bonjour, ravi de votre retour. Voici un créneau Calendly...',
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

    // ============ Phare SEO ============
    // Format attendu : {ok, sites_count, total_clicks_30d, avg_position_30d, pending_actions}
    phare_overview() {
      return {
        ok: true,
        sites_count: 13,
        total_clicks_30d: 28420,
        avg_position_30d: 9.4,
        pending_actions: 6,
      };
    },
    // Format attendu : {ok, sites: [{id, name, domain, clicks_30d, avg_position_30d}]}
    phare_sites() {
      return {
        ok: true,
        sites: [
          { id: 's1',  name: 'Triskell Studio',     domain: 'triskell-studio.fr',          clicks_30d: 12480, avg_position_30d: 4.2 },
          { id: 's2',  name: 'Lagriffe Studio',     domain: 'lagriffe-studio.fr',          clicks_30d: 5240,  avg_position_30d: 6.1 },
          { id: 's3',  name: 'RankUs Studio',       domain: 'rankus-studio.fr',            clicks_30d: 3890,  avg_position_30d: 8.4 },
          { id: 's4',  name: 'Studio WoW',          domain: 'studio-wow.fr',               clicks_30d: 2120,  avg_position_30d: 11.2 },
          { id: 's5',  name: 'Le Druide Antavirus', domain: 'antavirus.fr',                clicks_30d: 1840,  avg_position_30d: 7.8 },
          { id: 's6',  name: 'Boulangerie Lefèvre', domain: 'boulangerie-lefevre.fr',      clicks_30d: 980,   avg_position_30d: 4.5 },
          { id: 's7',  name: 'Cabinet Dupont',      domain: 'cabinet-dupont.fr',           clicks_30d: 720,   avg_position_30d: 6.8 },
          { id: 's8',  name: 'Pharmacie Centrale',  domain: 'pharmacie-centrale.fr',       clicks_30d: 612,   avg_position_30d: 5.2 },
          { id: 's9',  name: 'Studio Yoga Soleil',  domain: 'yoga-soleil.fr',              clicks_30d: 410,   avg_position_30d: 8.1 },
          { id: 's10', name: 'Restaurant Le Bistrot',domain:'le-bistrot-vannes.fr',        clicks_30d: 380,   avg_position_30d: 7.4 },
          { id: 's11', name: 'Atelier Missor',      domain: 'atelier-missor.fr',           clicks_30d: 285,   avg_position_30d: 12.4 },
          { id: 's12', name: 'Pack Électricien',    domain: 'pack-elec.triskell-studio.fr',clicks_30d: 248,   avg_position_30d: 14.8 },
          { id: 's13', name: 'Studio PDF',          domain: 'le-studio-pdf.fr',            clicks_30d: 162,   avg_position_30d: 19.2 },
        ],
      };
    },
    // Format attendu : {ok, actions: [{id, title, kind, created_at, summary}]}
    phare_pending_actions() {
      const now = Date.now();
      return {
        ok: true,
        actions: [
          { id: 'a1', title: 'Ajouter meta description sur 3 pages — cabinet-dupont.fr', kind: 'meta_description', created_at: new Date(now - 3600_000).toISOString(),
            summary: "L'agent audit a détecté 3 pages sans meta description (impact CTR estimé +14%). PR prête : ajout de descriptions optimisées, 70-155 caractères, mots-clés ciblés." },
          { id: 'a2', title: 'Compresser 4 images header — yoga-soleil.fr', kind: 'speed', created_at: new Date(now - 7200_000).toISOString(),
            summary: "Le header pèse 1.2 Mo (4 photos non compressées). Compression sans perte visible → 280 Ko. Gain LCP estimé : -0.8s. PR : conversion WebP + redimensionnement." },
          { id: 'a3', title: 'Ajouter schema LocalBusiness — pharmacie-centrale.fr', kind: 'schema', created_at: new Date(now - 10800_000).toISOString(),
            summary: "Pas de structured data LocalBusiness détecté. Ajout JSON-LD avec horaires, coordonnées, geo, type Pharmacy. Visible dans Knowledge Panel Google sous 14 jours." },
          { id: 'a4', title: 'Réparer 2 liens cassés en footer — atelier-missor.fr', kind: 'broken_link', created_at: new Date(now - 14400_000).toISOString(),
            summary: "Liens vers /tarifs (404) et vers compte Insta supprimé. PR : retire les liens morts, redirige /tarifs vers /prestations." },
          { id: 'a5', title: 'Mots-clés long tail — boulangerie-lefevre.fr', kind: 'keywords', created_at: new Date(now - 21600_000).toISOString(),
            summary: "Opportunité détectée : \"kouign-amann frais Plérin\" (volume 90/mois, KD faible). PR : page dédiée + maillage interne depuis la page d'accueil." },
          { id: 'a6', title: 'Rafraîchir page \"Services\" — lagriffe-studio.fr', kind: 'refresh', created_at: new Date(now - 28800_000).toISOString(),
            summary: "Page non touchée depuis 6 mois, position 14 sur \"création site web Bretagne\". PR : refonte du contenu, ajout FAQ, témoignages clients, CTA visible." },
        ],
      };
    },
    // Format attendu pour l'onglet Site : page détaillée d'un site
    phare_site(payload) {
      const id = payload && payload.id;
      return {
        ok: true,
        site: {
          id, name: 'Site démo', domain: 'demo.fr',
          clicks_30d: 1840, avg_position_30d: 8.3,
          score: 87, impressions_30d: 24820,
          top_keywords: [
            { keyword: 'kouign-amann breton', position: 3, clicks: 142, search_volume: 480 },
            { keyword: 'boulangerie plérin',  position: 2, clicks: 89,  search_volume: 320 },
            { keyword: 'pain spéciaux 22',    position: 7, clicks: 41,  search_volume: 190 },
          ],
        },
      };
    },

    // ============ Tracker (analytics sites) ============
    tracker_stats() {
      return {
        ok: true,
        period_days: 30,
        visiteurs_uniques: 18420,
        pages_vues: 47830,
        taux_rebond: 38,
        temps_moyen_seconds: 142,
        conversions: 89,
        top_pages: [
          { path: '/contact', views: 6240, conversions: 42 },
          { path: '/services', views: 4820, conversions: 28 },
          { path: '/', views: 12450, conversions: 12 },
          { path: '/tarifs', views: 3120, conversions: 7 },
        ],
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
    system_health() {
      return {
        ok: true,
        services: {
          supabase:    { ok: true, latency_ms: 38 },
          smtp:        { ok: true, latency_ms: 142 },
          imap:        { ok: true, latency_ms: 218 },
          anthropic:   { ok: true, latency_ms: 412 },
          stripe:      { ok: true, latency_ms: 95 },
          google_sc:   { ok: true, latency_ms: 188 },
          calendly:    { ok: true, latency_ms: 76 },
        },
        uptime_pct: 99.97,
        last_check: new Date().toISOString(),
      };
    },

    // ============ Autopilot status ============
    autopilot_status() {
      return {
        ok: true,
        running: true,
        prospects_scrapes_today: 42,
        mails_envoyes_today: 18,
        reponses_today: 4,
        log: [
          { ts: new Date().toISOString(), level: 'info', msg: '✓ 12 prospects qualifiés depuis Sirene' },
          { ts: new Date(Date.now()-300_000).toISOString(), level: 'info', msg: '✓ Mail envoyé à Cabinet Dupont & Co' },
          { ts: new Date(Date.now()-600_000).toISOString(), level: 'info', msg: '✓ Réponse classifiée : "Intéressé" — Boulangerie Lefèvre' },
          { ts: new Date(Date.now()-1200_000).toISOString(), level: 'info', msg: '✓ 8 nouveaux prospects scrapés (Maps)' },
        ],
      };
    },

    // ============ Messages internes Jordan/Thomas ============
    messages_count_unread() { return { ok: true, count: 0 }; },
    messages_list() { return { ok: true, messages: [] }; },
    messages_me() { return { ok: true, user_id: 'jordan', display_name: 'Jordan' }; },

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
});
