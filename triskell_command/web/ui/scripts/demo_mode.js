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
    // ============ Matinale : KPIs gonflés + priorités fictives ============
    get_morning_digest() {
      return {
        ok: true,
        digest: {
          generated_at: new Date().toISOString(),
          greeting: 'Bonjour Jordan',
          weather_hint: 'Belle journée pour closer 🚀',
          kpis: {
            clients_actifs:      { value: 214, delta: '+12 ce mois', positive: true },
            mrr:                 { value: '83 240 €', delta: '+8.4%', positive: true },
            taux_conversion:     { value: '34%', delta: '+3 pts',  positive: true },
            mails_envoyes_mois:  { value: 1247, delta: '+156', positive: true },
            reponses_attente:    { value: 18,   delta: '+5 aujourd\'hui', positive: false },
            rdv_planifies:       { value: 9,    delta: 'cette semaine', positive: true },
          },
          priorities: [
            { id: 'p1', kind: 'reply', label: 'Répondre à Sophie Dupont (Cabinet Dupont & Co)', urgency: 'haute', meta: 'Devis 4 200 € en attente' },
            { id: 'p2', kind: 'rdv',   label: 'RDV signature avec Marc Lefèvre dans 1 h', urgency: 'haute', meta: 'Boulangerie Lefèvre — pack Sites + SEO' },
            { id: 'p3', kind: 'follow',label: 'Relance Atelier Missor (sans réponse depuis 5 j)', urgency: 'moyenne', meta: 'Pack 1 800 €' },
            { id: 'p4', kind: 'task',  label: 'Livrer la maquette Boulangerie Aubert avant 18 h', urgency: 'moyenne', meta: 'Deadline aujourd\'hui' },
            { id: 'p5', kind: 'info',  label: '4 nouveaux prospects qualifiés ajoutés par Le Phare', urgency: 'basse', meta: 'Voir Pipeline' },
          ],
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
    get_drafts() {
      const now = Date.now();
      const drafts = [];
      const prospects = [
        ['Sophie Dupont', 'Cabinet Dupont & Co', 'sophie@dupont-co.fr', 'Refonte site + SEO'],
        ['Marc Lefèvre', 'Boulangerie Lefèvre', 'marc@boulangerie-lefevre.fr', 'Pack Sites'],
        ['Camille Bernard', 'Atelier Missor', 'camille@missor.fr', 'Site vitrine + SEO'],
        ['Antoine Petit', 'Garage Auto Plus', 'antoine@autoplus.fr', 'Pack visibilité Maps'],
        ['Léa Durand', 'Pharmacie Centrale', 'lea@pharmacie-centrale.fr', 'Site + prise RDV'],
        ['Thomas Moreau', 'Studio Yoga Soleil', 'thomas@yogasoleil.fr', 'Refonte + booking'],
        ['Julie Lambert', 'Restaurant Le Bistrot', 'julie@bistrot.fr', 'Carte en ligne + SEO'],
        ['Nicolas Rousseau', 'Salon Élégance', 'nicolas@elegance-coiffure.fr', 'Pack Sites'],
        ['Manon Vincent', 'École Andante', 'manon@andante-musique.fr', 'Site école + paiement'],
        ['Pierre Fontaine', 'Cabinet vétérinaire Animo', 'pierre@animo-veto.fr', 'Site + prise RDV'],
        ['Émilie Dubois', 'Pâtisserie Sucré Salé', 'emilie@sucresale.fr', 'Catalogue en ligne'],
        ['Hugo Robin', 'Optique Vision', 'hugo@optique-vision.fr', 'Pack visibilité Maps + Sites'],
      ];
      for (let i = 0; i < prospects.length; i++) {
        const [name, company, email, project] = prospects[i];
        drafts.push({
          id: `draft-${i}`,
          created_at: new Date(now - i * 7200_000).toISOString(),
          prospect_name: name,
          prospect_email: email,
          prospect_company: company,
          subject: `Bonjour ${name.split(' ')[0]}, à propos de ${project}`,
          body_preview: `Bonjour ${name.split(' ')[0]}, suite à votre demande pour ${project.toLowerCase()}, voici une proposition adaptée à ${company}…`,
          score: 85 + (i % 10),
          status: 'pending',
        });
      }
      return { ok: true, drafts };
    },

    // ============ Réponses prospects ============
    get_replies(payload) {
      const cat = (payload && payload.category) || 'all';
      const all = DemoMode._fakeMails().filter(m => m.kind === 'reply_received');
      const out = all.map((m, i) => ({
        id: m.id,
        ts: m.ts,
        from: m.extra.from,
        sender_name: m.extra.sender_name,
        subject: m.subject,
        body_preview: m.body,
        category: ['interested', 'not_now', 'no', 'rdv', 'question'][i % 5],
        category_label: m.extra.classification,
        handled: i % 6 === 0,
      }));
      if (cat === 'all') return { ok: true, replies: out };
      return { ok: true, replies: out.filter(r => r.category === cat) };
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
    phare_overview() {
      return {
        ok: true,
        kpis: {
          sites_audites: 47,
          score_moyen: 84,
          actions_pending: 12,
          actions_fixed_mois: 38,
          impressions_mois: '124 580',
          clicks_mois: '8 320',
        },
        top_sites: [
          { url: 'triskell-studio.fr', score: 96, trend: '+2' },
          { url: 'lagriffe-studio.fr', score: 92, trend: '+5' },
          { url: 'boulangerie-lefevre.fr', score: 89, trend: '+8' },
          { url: 'cabinet-dupont.fr', score: 87, trend: '+1' },
        ],
      };
    },
    phare_sites() {
      const sites = [
        { url: 'triskell-studio.fr', score: 96, impressions: 12480, clicks: 932, position_avg: 8.2 },
        { url: 'lagriffe-studio.fr', score: 92, impressions: 8240, clicks: 612, position_avg: 9.4 },
        { url: 'rankus-studio.fr', score: 90, impressions: 6890, clicks: 428, position_avg: 11.1 },
        { url: 'boulangerie-lefevre.fr', score: 89, impressions: 4820, clicks: 380, position_avg: 4.8 },
        { url: 'cabinet-dupont.fr', score: 87, impressions: 3240, clicks: 295, position_avg: 6.3 },
        { url: 'pharmacie-centrale.fr', score: 85, impressions: 5180, clicks: 412, position_avg: 5.1 },
        { url: 'yoga-soleil.fr', score: 84, impressions: 2920, clicks: 218, position_avg: 7.8 },
        { url: 'atelier-missor.fr', score: 82, impressions: 1840, clicks: 142, position_avg: 12.4 },
      ];
      return { ok: true, sites };
    },
    phare_pending_actions() {
      return {
        ok: true,
        actions: [
          { id: 'a1', site: 'cabinet-dupont.fr', kind: 'meta_description', label: 'Ajouter meta description sur 3 pages', impact: 'haut', estimated_minutes: 8 },
          { id: 'a2', site: 'boulangerie-lefevre.fr', kind: 'alt_image', label: 'Ajouter alt sur 12 images du menu', impact: 'moyen', estimated_minutes: 15 },
          { id: 'a3', site: 'yoga-soleil.fr', kind: 'speed', label: 'Compresser 4 images du header (1.2 Mo → 280 Ko)', impact: 'haut', estimated_minutes: 5 },
          { id: 'a4', site: 'pharmacie-centrale.fr', kind: 'schema', label: 'Ajouter schema LocalBusiness', impact: 'haut', estimated_minutes: 12 },
          { id: 'a5', site: 'atelier-missor.fr', kind: 'broken_link', label: '2 liens cassés en footer', impact: 'moyen', estimated_minutes: 3 },
        ],
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

    // ============ Multichannel actions ============
    multichannel_get_actions() {
      return {
        ok: true,
        actions: [
          { id: 'mc1', kind: 'linkedin_invite', target: 'Sophie Dupont', label: 'Inviter en relation LinkedIn', context: 'A vu ton site 3 fois cette semaine', ready: true },
          { id: 'mc2', kind: 'instagram_dm', target: 'Boulangerie Lefèvre', label: 'DM Instagram pour reprendre contact', context: 'A liké tes 5 derniers posts', ready: true },
          { id: 'mc3', kind: 'phone_call', target: 'Marc Lefèvre', label: 'Appel de relance', context: 'A ouvert ton dernier mail 4 fois', ready: true },
          { id: 'mc4', kind: 'follow_up_mail', target: 'Atelier Missor', label: 'Relance mail (3e tentative)', context: 'Pas de réponse depuis 6 jours', ready: true },
        ],
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
      const url = (payload && payload.url) || 'https://demo.lagriffe-studio.fr';
      if (cat === 'celebrity') {
        return {
          ok: true,
          target_name: 'Doumbé',
          used_template: 'Approche créateur',
          subject: 'Cédric — un site que j\'ai pensé pour vous',
          body_html: '<p>Bonjour Cédric,</p>'
            + '<p>Suite à votre dernier post Instagram sur votre prochain projet, j\'ai imaginé à quoi pourrait ressembler votre univers sur le web. J\'ai pris quelques heures pour <strong>concevoir un site qui colle à votre ligne</strong> — ton brut, focus sur vos combats, calendrier propre.</p>'
            + '<p><img src="cid:prospect_preview" alt="Aperçu du site" style="max-width:100%;height:auto;display:block;border-radius:8px;border:1px solid #e5e7eb;"></p>'
            + `<p>Voici à quoi ça ressemble : <a href="${url}"><strong>Découvrir le site</strong></a>. Ouvrez quand vous avez 30 secondes, dites-moi ce que vous en pensez. Si ça vous parle, on bascule sur votre vrai domaine en quelques jours.</p>`,
          source_url: url, category: cat,
          screenshot_b64: '',
          screenshot_content_type: '',
        };
      }
      return {
        ok: true,
        target_name: 'Boulangerie Lefèvre',
        used_template: 'Approche commerce local',
        subject: 'Boulangerie Lefèvre — votre nouveau site, prêt à découvrir',
        body_html: '<p>Bonjour Marc,</p>'
          + '<p>J\'ai pris quelques heures pour vous <strong>concevoir un site qui met en valeur votre boulangerie</strong> : votre kouign-amann breton en page d\'accueil, vos horaires bien visibles, un bloc avis Google et la prise de commande en ligne pour les fêtes.</p>'
          + '<p><img src="cid:prospect_preview" alt="Aperçu du site" style="max-width:100%;height:auto;display:block;border-radius:8px;border:1px solid #e5e7eb;"></p>'
          + `<p>Voilà à quoi ça ressemble : <a href="${url}"><strong>Voir le site</strong></a>.</p>`
          + '<p>Si ça vous plaît, en 1 journée on bascule sur votre vrai domaine. Sinon, vous repartez avec les idées et c\'est cadeau.</p>',
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
