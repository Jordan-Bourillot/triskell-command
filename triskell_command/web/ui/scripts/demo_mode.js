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
        || /_(save|delete|remove|send|set|create|add|upload|update|reset|migrate)$/.test(method)
        || method === 'mail_send'
        || method === 'mail_send_reply'
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
    // Matinale : KPIs gonflés + priorités fictives
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
    // Liste de mails fictifs
    mails_list(payload) {
      const kind = (payload && payload.kind) || 'all';
      const all = DemoMode._fakeMails();
      let filtered = all;
      if (kind === 'sent') filtered = all.filter(m => m.kind === 'email_sent');
      else if (kind === 'reply' || kind === 'inbound') filtered = all.filter(m => m.kind === 'reply_received');
      return { ok: true, mails: filtered.slice(0, (payload && payload.limit) || 50) };
    },
    // Signatures : on en montre 3 jolies
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
