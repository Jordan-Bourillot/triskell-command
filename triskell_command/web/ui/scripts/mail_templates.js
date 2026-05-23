/* Mail Templates — éditeur de modèles mail (vue Triskell Command).
 *
 * Lit / écrit la table Supabase `triskell_email_templates` via l'API
 * `mail_templates_*`. Permet à Jordan d'éditer sujets, expéditeurs et
 * corps HTML de chaque mail transactionnel sans toucher au code.
 *
 * Si un template n'existe pas (ou est désactivé), la Netlify Function
 * appelante retombe automatiquement sur son fallback hardcodé — donc
 * désactiver un template ne casse rien.
 *
 * Catalogue des templates connus (par défaut, pour proposer la création
 * de nouveaux templates même quand la base est vide). Doit rester aligné
 * avec ce que les fonctions Netlify lisent réellement.
 */

const MailTemplates = {
  _state: {
    products: {},     // { lagriffe: { label, templates: [...] }, … } — brut depuis l'API
    selected: null,   // { product, key } courant
    editing: null,    // copie de travail (jamais persistée tant qu'on clique pas Enregistrer)
    busy: false,
    catalog: null,    // mode transactionnel : groupé par adresse mail
    catalogProspection: null, // mode prospection : groupé par produit du catalogue
    senderFilter: '', // adresse mail filtrée en mode transactionnel ('' = toutes)
    productFilter: '',// produit filtré en mode prospection ('' = tous)
    audienceFilter: 'all', // sous-filtre prospection : 'all' | 'creator' | 'pro'
    categoryMode: 'transactionnel', // 'transactionnel' | 'prospection'
    catalogueProducts: [], // produits du catalogue Triskell, chargés à la demande pour la prospection
  },

  // Produits "techniques" historiques (réservés aux mails transactionnels).
  // En mode Prospection, on les masque de la liste des produits sélectionnables —
  // un mail de démarchage se range sous un produit commercial du catalogue
  // (Pixel Pros, Lagriffe, RankUs…), pas sous "billing" ou "internal".
  PROSPECTION_EXCLUDED_PRODUCTS: new Set([
    'reply', 'drip', 'post_sale', 'billing', 'internal', 'shared',
    'delivery_pack_elec', 'delivery_studio_pdf', 'delivery_obelisk',
  ]),

  // Catalogue de référence — pour que l'éditeur propose toujours les bons
  // templates même si la base est vide / partielle. Chaque entrée déclare
  // son adresse expéditrice par défaut (utilisée pour grouper l'UI par mail)
  // et un drapeau `runtime` :
  //   'netlify'  → édition appliquée immédiatement (la Netlify Function lit
  //                la table `triskell_email_templates` à chaque envoi).
  //   'pipeline' → édition stockée en base mais runner Python lit encore son
  //                modèle codé en dur. On l'affiche pour préparer le terrain
  //                ; en attendant on l'indique clairement dans l'éditeur.
  KNOWN: [
    // ============ noreply@triskell-studio.fr — Lagriffe Studio (sites) ============
    { product: 'lagriffe', key: 'brief_received', label: 'Confirmation de brief reçu',
      description: 'Envoyé dès que le client soumet sa demande de site sur lagriffe-studio.fr.',
      placeholders: ['first_name'],
      from_address: 'noreply@triskell-studio.fr', from_name: 'Lagriffe Studio',
      runtime: 'netlify' },
    { product: 'lagriffe', key: 'preview_ready', label: 'Maquette prête à personnaliser',
      description: 'Envoyé quand la preview Netlify est déployée et que le client peut commencer la personnalisation.',
      placeholders: ['first_name', 'customize_url'],
      from_address: 'noreply@triskell-studio.fr', from_name: 'Lagriffe Studio',
      runtime: 'netlify' },
    { product: 'lagriffe', key: 'payment_confirmed', label: 'Confirmation de paiement',
      description: 'Envoyé après le webhook Stripe (paiement réussi).',
      placeholders: ['first_name'],
      from_address: 'noreply@triskell-studio.fr', from_name: 'Lagriffe Studio',
      runtime: 'netlify' },
    { product: 'lagriffe', key: 'site_delivered', label: 'Site final livré',
      description: 'Envoyé quand le site final passe en production.',
      placeholders: ['first_name', 'site_url'],
      from_address: 'noreply@triskell-studio.fr', from_name: 'Lagriffe Studio',
      runtime: 'netlify' },
    { product: 'lagriffe', key: 'reminder_j2', label: 'Relance J+2 (rappel doux)',
      description: 'Envoyée 2 jours après l\'invitation à personnaliser, si le client n\'a rien fait.',
      placeholders: ['first_name', 'customize_url', 'mockup_url', 'company_name'],
      from_address: 'noreply@triskell-studio.fr', from_name: 'Lagriffe Studio',
      runtime: 'netlify' },
    { product: 'lagriffe', key: 'reminder_j5', label: 'Relance J+5 (on est là)',
      description: 'Envoyée à J+5, ton chaleureux, on propose de l\'aide.',
      placeholders: ['first_name', 'customize_url', 'mockup_url', 'company_name'],
      from_address: 'noreply@triskell-studio.fr', from_name: 'Lagriffe Studio',
      runtime: 'netlify' },
    { product: 'lagriffe', key: 'reminder_j10', label: 'Relance J+10 (dernière chance)',
      description: 'Envoyée à J+10, dernier rappel avant archivage à J+14.',
      placeholders: ['first_name', 'customize_url', 'mockup_url', 'company_name'],
      from_address: 'noreply@triskell-studio.fr', from_name: 'Lagriffe Studio',
      runtime: 'netlify' },

    // ============ noreply@triskell-studio.fr — Studio WoW ============
    { product: 'wow', key: 'first_version_ready', label: 'Première version en ligne',
      description: 'Envoyé quand le site Studio WoW est déployé pour la première fois.',
      placeholders: ['first_name', 'site_url'],
      from_address: 'noreply@triskell-studio.fr', from_name: 'Studio WoW',
      runtime: 'netlify' },

    // ============ noreply@triskell-studio.fr — RankUs Studio (SEO) ============
    { product: 'rankus', key: 'welcome', label: 'Bienvenue suivi SEO',
      description: 'Envoyé quand le client active l\'addon SEO après livraison Lagriffe.',
      placeholders: ['first_name'],
      from_address: 'noreply@triskell-studio.fr', from_name: 'RankUs Studio',
      runtime: 'netlify' },

    // ============ rapports@rankus-studio.fr — Phare (rapports SEO mensuels) ============
    { product: 'phare', key: 'monthly_report', label: 'Rapport SEO mensuel',
      description: 'Envoyé chaque 1er du mois aux clients RankUs/Le Phare, avec le PDF du rapport en pièce jointe.',
      placeholders: ['client_name', 'month', 'year'],
      from_address: 'rapports@rankus-studio.fr', from_name: 'RankUs Studio',
      runtime: 'pipeline' },

    // ============ contact@triskell-studio.fr — Réponses IA aux prospects ============
    { product: 'reply', key: 'interested', label: 'Réponse IA — intéressé',
      description: 'Réponse auto envoyée quand un prospect dit être intéressé par un produit du catalogue.',
      placeholders: ['name', 'product_name', 'product_link', 'signature'],
      from_address: 'contact@triskell-studio.fr', from_name: 'Jordan Bourillot',
      runtime: 'pipeline' },
    { product: 'reply', key: 'not_now', label: 'Réponse IA — pas maintenant',
      description: 'Réponse polie quand le prospect dit que ce n\'est pas le bon moment.',
      placeholders: ['name', 'signature'],
      from_address: 'contact@triskell-studio.fr', from_name: 'Jordan Bourillot',
      runtime: 'pipeline' },
    { product: 'reply', key: 'no', label: 'Réponse IA — refus',
      description: 'Réponse courte et propre quand le prospect refuse.',
      placeholders: ['name', 'signature'],
      from_address: 'contact@triskell-studio.fr', from_name: 'Jordan Bourillot',
      runtime: 'pipeline' },
    { product: 'reply', key: 'unsubscribe', label: 'Réponse IA — désinscription',
      description: 'Confirmation de désinscription.',
      placeholders: ['name', 'signature'],
      from_address: 'contact@triskell-studio.fr', from_name: 'Jordan Bourillot',
      runtime: 'pipeline' },
    { product: 'reply', key: 'unknown', label: 'Réponse IA — intention floue',
      description: 'Quand l\'IA n\'arrive pas à classer la réponse, on envoie un message neutre.',
      placeholders: ['name', 'signature'],
      from_address: 'contact@triskell-studio.fr', from_name: 'Jordan Bourillot',
      runtime: 'pipeline' },

    // ============ contact@triskell-studio.fr — Relances drip (prospection) ============
    { product: 'drip', key: 'follow_up_7d', label: 'Drip J+7 — follow-up',
      description: 'Première relance prospect, 7 jours après le premier mail si pas de réponse.',
      placeholders: ['name', 'signature'],
      from_address: 'contact@triskell-studio.fr', from_name: 'Jordan Bourillot',
      runtime: 'pipeline' },
    { product: 'drip', key: 'follow_up_30d', label: 'Drip J+30 — dernier rappel',
      description: 'Relance finale, 30 jours après le premier mail.',
      placeholders: ['name', 'signature', 'soft_hook'],
      from_address: 'contact@triskell-studio.fr', from_name: 'Jordan Bourillot',
      runtime: 'pipeline' },

    // ============ contact@triskell-studio.fr — Post-vente (suivi client) ============
    { product: 'post_sale', key: 'welcome_at_paid', label: 'Bienvenue après achat',
      description: 'Envoyé automatiquement à l\'instant du paiement (paid_at).',
      placeholders: ['client_name', 'product_name', 'signature'],
      from_address: 'contact@triskell-studio.fr', from_name: 'Jordan Bourillot',
      runtime: 'pipeline' },
    { product: 'post_sale', key: 'cross_sell_30d', label: 'Cross-sell J+30',
      description: '30 jours après l\'achat, proposition d\'un produit complémentaire.',
      placeholders: ['client_name', 'product_name', 'next_product_name', 'next_product_link', 'signature'],
      from_address: 'contact@triskell-studio.fr', from_name: 'Jordan Bourillot',
      runtime: 'pipeline' },
    { product: 'post_sale', key: 'nps_90d', label: 'Sondage NPS J+90',
      description: '90 jours après l\'achat, demande de feedback (NPS).',
      placeholders: ['client_name', 'product_name', 'signature'],
      from_address: 'contact@triskell-studio.fr', from_name: 'Jordan Bourillot',
      runtime: 'pipeline' },

    // ============ contact@triskell-studio.fr — Livraisons produits Triskell ============
    { product: 'delivery_pack_elec', key: 'welcome', label: 'Pack Électricien Pro — Bienvenue',
      description: 'Mail de bienvenue envoyé après achat du Pack Électricien Pro.',
      placeholders: ['client_name', 'deliverables_list', 'signature'],
      from_address: 'contact@triskell-studio.fr', from_name: 'Triskell Studio',
      runtime: 'pipeline' },
    { product: 'delivery_pack_elec', key: 'followup_3d', label: 'Pack Électricien Pro — Suivi J+3',
      description: '3 jours après livraison : check qu\'on a tout bien reçu.',
      placeholders: ['client_name', 'signature'],
      from_address: 'contact@triskell-studio.fr', from_name: 'Triskell Studio',
      runtime: 'pipeline' },
    { product: 'delivery_pack_elec', key: 'followup_14d', label: 'Pack Électricien Pro — Astuce J+14',
      description: 'À J+14 : astuce d\'utilisation pour pousser l\'engagement.',
      placeholders: ['client_name', 'signature'],
      from_address: 'contact@triskell-studio.fr', from_name: 'Triskell Studio',
      runtime: 'pipeline' },
    { product: 'delivery_pack_elec', key: 'followup_30d', label: 'Pack Électricien Pro — Avis J+30',
      description: 'À J+30 : demande d\'avis / témoignage.',
      placeholders: ['client_name', 'signature'],
      from_address: 'contact@triskell-studio.fr', from_name: 'Triskell Studio',
      runtime: 'pipeline' },
    { product: 'delivery_studio_pdf', key: 'welcome', label: 'Studio PDF — Bienvenue',
      description: 'Mail de bienvenue après achat Studio PDF.',
      placeholders: ['client_name', 'deliverables_list', 'signature'],
      from_address: 'contact@triskell-studio.fr', from_name: 'Triskell Studio',
      runtime: 'pipeline' },
    { product: 'delivery_studio_pdf', key: 'followup_3d', label: 'Studio PDF — Premier essai J+3',
      description: '3 jours après : on demande si tout va bien avec l\'outil.',
      placeholders: ['client_name', 'signature'],
      from_address: 'contact@triskell-studio.fr', from_name: 'Triskell Studio',
      runtime: 'pipeline' },
    { product: 'delivery_studio_pdf', key: 'followup_30d', label: 'Studio PDF — Avis J+30',
      description: 'À J+30 : demande d\'avis client.',
      placeholders: ['client_name', 'signature'],
      from_address: 'contact@triskell-studio.fr', from_name: 'Triskell Studio',
      runtime: 'pipeline' },
    { product: 'delivery_obelisk', key: 'welcome', label: 'Obelisk — Bienvenue',
      description: 'Mail de bienvenue après achat Obelisk.',
      placeholders: ['client_name', 'deliverables_list', 'signature'],
      from_address: 'contact@triskell-studio.fr', from_name: 'Triskell Studio',
      runtime: 'pipeline' },

    // ============ Triskell interne (digest matinale, alertes Phare, factures) ============
    { product: 'internal', key: 'morning_digest', label: 'Triskell Matinale (digest 8h)',
      description: 'Email digest envoyé chaque matin à 8h, résumé des KPIs et alertes.',
      placeholders: [],
      from_address: 'jordan@triskell-studio.fr', from_name: 'Triskell Matinale',
      runtime: 'pipeline' },
    { product: 'internal', key: 'phare_analyst_report', label: 'Alerte Phare — rapport analyste',
      description: 'Notif interne quand un analyste Phare termine un rapport.',
      placeholders: ['title', 'body'],
      from_address: 'jordan@triskell-studio.fr', from_name: 'Le Phare',
      runtime: 'pipeline' },
    { product: 'internal', key: 'phare_validation_alert', label: 'Alerte Phare — validation onpage',
      description: 'Notif interne quand un changement onpage demande validation.',
      placeholders: ['title', 'body'],
      from_address: 'jordan@triskell-studio.fr', from_name: 'Le Phare',
      runtime: 'pipeline' },
    { product: 'internal', key: 'phare_reject_alert', label: 'Alerte Phare — merge rejeté',
      description: 'Notif interne quand un merge Phare est rejeté.',
      placeholders: ['title', 'body'],
      from_address: 'jordan@triskell-studio.fr', from_name: 'Le Phare',
      runtime: 'pipeline' },

    // ============ billing@triskell-studio.fr — Factures Stripe ============
    { product: 'billing', key: 'invoice_email', label: 'Facture Stripe émise',
      description: 'Mail envoyé au client après paiement Stripe réussi, avec PDF de la facture en pièce jointe.',
      placeholders: ['client_name', 'invoice_number', 'amount', 'currency'],
      from_address: 'billing@triskell-studio.fr', from_name: 'Triskell Studio (facturation)',
      runtime: 'pipeline' },
  ],

  // Libellés humains des regroupements par adresse mail. Les adresses
  // inconnues tombent sur un libellé générique.
  SENDER_LABELS: {
    'noreply@triskell-studio.fr':  'Sites Triskell (transactionnel)',
    'contact@triskell-studio.fr':  'Prospection & suivi client',
    'rapports@rankus-studio.fr':   'RankUs / Le Phare (rapports)',
    'jordan@triskell-studio.fr':   'Notifications internes',
    'billing@triskell-studio.fr':  'Facturation',
  },

  // Ordre d'affichage des regroupements (les adresses non listées suivent dans
  // l'ordre alphabétique).
  SENDER_ORDER: [
    'noreply@triskell-studio.fr',
    'contact@triskell-studio.fr',
    'rapports@rankus-studio.fr',
    'jordan@triskell-studio.fr',
    'billing@triskell-studio.fr',
  ],

  // ---------- API ----------
  async _api(method, payload) {
    if (!App.api) return null;
    const fn = App.api['mail_templates_' + method];
    if (typeof fn !== 'function') return null;
    try { return await fn(payload || {}); }
    catch (e) { console.warn('mail_templates.' + method, e); return null; }
  },

  // ---------- Render ----------
  async render(container, params) {
    this._root = container;
    // L'onglet (transactionnel / prospection) est piloté par la sidebar.
    const tab = params && params.tab;
    if (tab === 'transactionnel' || tab === 'prospection') {
      if (this._state.categoryMode !== tab) {
        this._state.selected = null;
        this._state.editing = null;
      }
      this._state.categoryMode = tab;
    }
    const isProsp = (this._state.categoryMode === 'prospection');
    const transacDisplay = isProsp ? 'none' : 'flex';
    const prospDisplay   = isProsp ? 'flex' : 'none';
    container.innerHTML = `
      <section class="animate-slide-up">
        <!-- En-tête épuré : titre court, pas de gros pavé d'intro -->
        <header class="mb-5 flex items-center justify-between gap-4 flex-wrap">
          <div>
            <h1 class="text-2xl font-bold leading-tight">Modèles de mails</h1>
            <p class="text-sm text-text-muted mt-1">Sujet, expéditeur, corps — tu modifies, ça s'applique tout de suite.</p>
          </div>
          <div class="flex items-center gap-2">
            <button id="mt-banner-help" class="btn btn-ghost text-[12px]" title="Comment ça marche ?">ⓘ Aide</button>
            <button id="mt-refresh" class="btn btn-secondary text-sm">↻ Rafraîchir</button>
          </div>
        </header>

        <!-- Banner d'aide masqué par défaut, affichable via le bouton ⓘ -->
        <div id="mt-banner" class="mb-4 text-[12px] text-text-muted px-3 py-2 rounded-lg bg-accent/5 border border-accent/20" style="display:none;"></div>

        <!-- Toolbar : filtre + compteur sur la même ligne, pas de label en double -->
        <div id="mt-toolbar-transac" class="flex items-center gap-2 mb-3 flex-wrap" style="display:${transacDisplay};">
          <select id="mt-sender-filter" class="px-3 py-1.5 rounded-lg bg-bg border border-border text-sm" aria-label="Filtrer par adresse">
            <option value="">— Toutes les adresses —</option>
          </select>
          <span id="mt-count" class="text-[11px] text-text-muted ml-auto"></span>
        </div>

        <div id="mt-toolbar-prosp" class="flex items-center gap-2 mb-3 flex-wrap" style="display:${prospDisplay};">
          <select id="mt-product-filter" class="px-3 py-1.5 rounded-lg bg-bg border border-border text-sm" aria-label="Filtrer par produit">
            <option value="">— Tous les produits —</option>
          </select>
          <div class="mt-aud-toggle" role="tablist" aria-label="Audience">
            <button class="mt-aud-btn is-active" data-mt-aud="all" role="tab">Tous</button>
            <button class="mt-aud-btn" data-mt-aud="creator" role="tab" title="Démarchage de créateurs / influenceurs (partenariats, codes promo, commissions)">Créateurs</button>
            <button class="mt-aud-btn" data-mt-aud="pro" role="tab" title="Démarchage B2B local (commerces, artisans, cabinets) — vente directe">Pros</button>
          </div>
          <button id="mt-new-prosp" class="btn btn-primary text-sm">+ Nouveau modèle</button>
          <span id="mt-count-prosp" class="text-[11px] text-text-muted ml-auto"></span>
        </div>

        <div class="grid grid-cols-1 lg:grid-cols-[300px_1fr] gap-4">
          <aside id="mt-list" class="bg-card border border-border rounded-xl p-2 overflow-y-auto" style="max-height: calc(100vh - 240px);"></aside>
          <main  id="mt-editor" class="bg-card border border-border rounded-xl p-5 min-h-[500px]"></main>
        </div>
      </section>
    `;
    this._injectStyles();
    // Toggle du panneau d'aide
    const helpBtn = document.getElementById('mt-banner-help');
    const banner  = document.getElementById('mt-banner');
    if (helpBtn && banner) {
      helpBtn.onclick = () => {
        banner.style.display = (banner.style.display === 'none') ? '' : 'none';
      };
    }
    document.getElementById('mt-refresh').onclick = () => this.refresh();
    document.getElementById('mt-sender-filter').onchange = (e) => {
      this._state.senderFilter = e.target.value;
      this._renderList();
    };
    document.getElementById('mt-product-filter').onchange = (e) => {
      this._state.productFilter = e.target.value;
      this._renderList();
    };
    document.getElementById('mt-new-prosp').onclick = () => this.openNewProspection();
    document.querySelectorAll('[data-mt-cat]').forEach(btn => {
      btn.onclick = () => this._switchCategory(btn.dataset.mtCat);
    });
    document.querySelectorAll('[data-mt-aud]').forEach(btn => {
      btn.onclick = () => this._switchAudience(btn.dataset.mtAud);
    });
    await this.refresh();
  },

  _switchCategory(mode) {
    if (mode !== 'transactionnel' && mode !== 'prospection') return;
    if (this._state.categoryMode === mode) return;
    this._state.categoryMode = mode;
    this._state.selected = null;
    this._state.editing = null;
    document.querySelectorAll('[data-mt-cat]').forEach(b => {
      b.classList.toggle('is-active', b.dataset.mtCat === mode);
    });
    document.getElementById('mt-toolbar-transac').style.display = (mode === 'transactionnel') ? '' : 'none';
    document.getElementById('mt-toolbar-prosp').style.display   = (mode === 'prospection')   ? '' : 'none';
    this._renderList();
    // Auto-select : premier template du mode courant
    const cat = (mode === 'prospection') ? this._state.catalogProspection : this._state.catalog;
    let target = null;
    for (const info of Object.values(cat || {})) {
      const t = (info.templates || [])[0];
      if (t) { target = { product: t.product, key: t.key }; break; }
    }
    if (target) this.openTemplate(target.product, target.key);
    else this._renderEmptyEditor();
  },

  _switchAudience(aud) {
    if (!['all', 'creator', 'pro'].includes(aud)) return;
    if (this._state.audienceFilter === aud) return;
    this._state.audienceFilter = aud;
    document.querySelectorAll('[data-mt-aud]').forEach(b => {
      b.classList.toggle('is-active', b.dataset.mtAud === aud);
    });
    this._renderList();
  },

  _injectStyles() {
    if (document.getElementById('mt-styles')) return;
    const s = document.createElement('style');
    s.id = 'mt-styles';
    s.textContent = `
      .mt-product-h {
        padding: 12px 8px 6px;
        border-top: 1px solid hsl(var(--border) / .5);
        margin-top: 4px;
      }
      .mt-product-h:first-child { border-top: none; margin-top: 0; }
      .mt-product-h .mt-addr {
        display: block; font-family: ui-monospace, "SF Mono", Consolas, monospace;
        font-size: 11.5px; font-weight: 700; color: hsl(var(--accent));
        letter-spacing: .01em; word-break: break-all;
      }
      .mt-product-h .mt-addr-sub {
        display: block; font-size: 9.5px; letter-spacing: .14em; text-transform: uppercase;
        color: hsl(var(--text-muted)); margin-top: 2px;
      }
      .mt-row .mt-pill-pipeline {
        background: hsl(var(--warning) / .15); color: hsl(var(--warning));
      }
      .mt-row {
        display: block; width: 100%; text-align: left;
        padding: 10px 12px; border-radius: 8px;
        font-size: 13px; line-height: 1.3;
        color: hsl(var(--text));
        transition: background 120ms, color 120ms;
      }
      .mt-row:hover { background: hsl(var(--bg)); }
      .mt-row.is-active { background: hsl(var(--accent) / .12); color: hsl(var(--accent)); font-weight: 600; }
      .mt-row .mt-row-sub { font-size: 11px; color: hsl(var(--text-muted)); margin-top: 2px; }
      .mt-row.is-active .mt-row-sub { color: hsl(var(--accent) / .75); }
      .mt-row .mt-pill {
        display: inline-block; padding: 1px 6px; border-radius: 4px; font-size: 9.5px;
        font-weight: 700; letter-spacing: .04em; text-transform: uppercase;
        background: hsl(var(--warning) / .15); color: hsl(var(--warning));
        margin-left: 6px; vertical-align: middle;
      }
      .mt-row .mt-pill-on { background: hsl(var(--success) / .15); color: hsl(var(--success)); }
      .mt-row .mt-pill-off { background: hsl(var(--text-muted) / .2); color: hsl(var(--text-muted)); }
      .mt-field { display: block; margin-bottom: 16px; }
      .mt-field > label {
        display: block; font-size: 11px; font-weight: 700;
        letter-spacing: .1em; text-transform: uppercase;
        color: hsl(var(--text-muted)); margin-bottom: 6px;
      }
      .mt-field input, .mt-field textarea, .mt-field select {
        width: 100%; padding: 9px 12px; border-radius: 7px;
        background: hsl(var(--bg)); color: hsl(var(--text));
        border: 1px solid hsl(var(--border));
        font-size: 13px; line-height: 1.5;
        font-family: inherit;
      }
      .mt-field textarea { resize: vertical; min-height: 240px; font-family: ui-monospace, "SF Mono", Consolas, monospace; font-size: 12.5px; }
      .mt-field input:focus, .mt-field textarea:focus, .mt-field select:focus {
        outline: none; border-color: hsl(var(--accent));
        box-shadow: 0 0 0 3px hsl(var(--accent) / .12);
      }
      .mt-placeholder-chip {
        display: inline-block; padding: 3px 8px; margin: 0 4px 4px 0;
        font-size: 11px; font-family: ui-monospace, "SF Mono", Consolas, monospace;
        background: hsl(var(--accent) / .1); color: hsl(var(--accent));
        border-radius: 4px; cursor: pointer; border: 1px dashed hsl(var(--accent) / .3);
        transition: background 120ms;
      }
      .mt-placeholder-chip:hover { background: hsl(var(--accent) / .2); }
      .mt-toolbar { display: flex; gap: 8px; align-items: center; margin-top: 16px; padding-top: 16px; border-top: 1px solid hsl(var(--border)); }
      .mt-toolbar .grow { flex: 1; }
      .mt-preview-frame {
        width: 100%; height: 520px; border: 1px solid hsl(var(--border));
        border-radius: 8px; background: white;
      }
      .mt-tabs { display: flex; gap: 4px; margin-bottom: 12px; border-bottom: 1px solid hsl(var(--border)); }
      .mt-tab {
        padding: 8px 14px; font-size: 12px; font-weight: 600;
        color: hsl(var(--text-muted)); border-bottom: 2px solid transparent;
        transition: color 120ms, border-color 120ms;
      }
      .mt-tab.is-active { color: hsl(var(--accent)); border-bottom-color: hsl(var(--accent)); }

      /* Toggle Transactionnel / Prospection */
      .mt-cat-toggle {
        display: inline-flex; gap: 4px;
        padding: 4px; border-radius: 12px;
        background: hsl(var(--bg));
        border: 1px solid hsl(var(--border));
      }
      .mt-cat-btn {
        display: flex; flex-direction: column; align-items: flex-start;
        padding: 8px 16px; border-radius: 8px;
        background: transparent; border: none; cursor: pointer;
        transition: background 140ms, color 140ms;
        text-align: left;
      }
      .mt-cat-btn:hover { background: hsl(var(--card)); }
      .mt-cat-btn.is-active {
        background: hsl(var(--accent) / .14);
        color: hsl(var(--accent));
      }
      .mt-cat-btn .mt-cat-title {
        font-size: 13px; font-weight: 700; color: inherit; line-height: 1.2;
      }
      .mt-cat-btn .mt-cat-ico { font-size: 15px; line-height: 1; }
      .mt-cat-btn .mt-cat-sub {
        font-size: 10.5px; color: hsl(var(--text-muted)); margin-top: 2px;
        font-weight: 500;
      }
      .mt-cat-btn.is-active .mt-cat-sub { color: hsl(var(--accent) / .75); }
      /* Boutons d'onglets compacts : icône + titre alignés en ligne */
      .mt-cat-btn { flex-direction: row !important; align-items: center !important; gap: 8px !important; padding: 7px 14px !important; }

      /* === Toggle Audience (sous-filtre prospection) === */
      .mt-aud-toggle {
        display: inline-flex;
        background: hsl(var(--bg));
        border: 1px solid hsl(var(--border));
        border-radius: 8px;
        padding: 2px;
      }
      .mt-aud-btn {
        background: transparent;
        border: 0;
        padding: 4px 12px;
        border-radius: 6px;
        font-size: 12px;
        font-weight: 600;
        color: hsl(var(--text-muted));
        cursor: pointer;
        transition: background .15s, color .15s;
      }
      .mt-aud-btn:hover { color: hsl(var(--text)); }
      .mt-aud-btn.is-active {
        background: hsl(var(--card));
        color: hsl(var(--text));
        box-shadow: 0 1px 2px hsl(0 0% 0% / .08);
      }

      /* === Pills audience dans la liste === */
      .mt-pill-aud-creator {
        background: hsl(265 70% 60% / .15);
        color: hsl(265 60% 50%);
      }
      .mt-pill-aud-pro {
        background: hsl(35 85% 55% / .18);
        color: hsl(28 80% 42%);
      }

      /* === Chips contextuelles (en haut de l'éditeur) === */
      .mt-chip {
        display: inline-flex; align-items: center; gap: 5px;
        padding: 3px 10px; border-radius: 999px;
        font-size: 11px; font-weight: 700; letter-spacing: .02em;
        border: 1px solid hsl(var(--border));
        background: hsl(var(--bg));
        color: hsl(var(--text-muted));
      }
      .mt-chip-prosp  { background: hsl(var(--accent) / .12); color: hsl(var(--accent)); border-color: hsl(var(--accent) / .3); }
      .mt-chip-auto   { background: hsl(var(--success) / .12); color: hsl(var(--success)); border-color: hsl(var(--success) / .3); }
      .mt-chip-target { font-family: ui-monospace, "SF Mono", Consolas, monospace; font-size: 10.5px; }

      /* === Bandeau d'avertissement compact === */
      .mt-warn {
        margin-top: 10px;
        padding: 8px 11px;
        background: hsl(var(--warning) / .1);
        border-left: 3px solid hsl(var(--warning));
        border-radius: 4px;
        font-size: 12px;
        color: hsl(var(--warning));
        line-height: 1.5;
      }

      /* === SUJET en grand (champ "hero") === */
      .mt-field-hero input {
        font-size: 16px !important;
        font-weight: 600;
        padding: 12px 14px !important;
      }

      /* === CORPS en grand textarea === */
      .mt-textarea-hero {
        min-height: 360px !important;
      }

      /* === Placeholders sur une ligne compacte au lieu d'un bloc === */
      .mt-placeholders-row {
        display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
        margin: -6px 0 12px;
        padding: 6px 10px;
        background: hsl(var(--bg));
        border-radius: 6px;
        border: 1px dashed hsl(var(--border));
      }
      .mt-placeholders-chips { display: flex; flex-wrap: wrap; gap: 4px; }
      .mt-placeholders-row .mt-placeholder-chip { margin: 0; }

      /* === Bloc "Réglages avancés" replié === */
      .mt-advanced {
        margin-top: 18px;
        border: 1px solid hsl(var(--border));
        border-radius: 10px;
        background: hsl(var(--bg) / .4);
      }
      .mt-advanced > summary {
        padding: 10px 14px;
        cursor: pointer;
        font-size: 12.5px;
        font-weight: 600;
        color: hsl(var(--text));
        list-style: none;
        user-select: none;
      }
      .mt-advanced > summary::-webkit-details-marker { display: none; }
      .mt-advanced > summary::before {
        content: '▸';
        display: inline-block;
        margin-right: 6px;
        transition: transform .15s;
        color: hsl(var(--text-muted));
      }
      .mt-advanced[open] > summary::before { transform: rotate(90deg); }
      .mt-advanced-body { padding: 6px 14px 14px; }

      /* === Checkbox inline avec label (modèle actif…) === */
      .mt-field-inline {
        display: flex; align-items: center; gap: 10px;
        margin-bottom: 14px; font-size: 13px;
      }
      .mt-field-inline input[type="checkbox"] { width: auto; margin: 0; }

      /* En mode prospection, l'entête de groupe affiche le nom du produit */
      .mt-prod-h {
        padding: 12px 8px 6px;
        border-top: 1px solid hsl(var(--border) / .5);
        margin-top: 4px;
      }
      .mt-prod-h:first-child { border-top: none; margin-top: 0; }
      .mt-prod-h .mt-prod-name {
        display: block; font-size: 12.5px; font-weight: 700;
        color: hsl(var(--accent)); letter-spacing: .01em;
      }
      .mt-prod-h .mt-prod-count {
        display: block; font-size: 9.5px; letter-spacing: .14em;
        text-transform: uppercase; color: hsl(var(--text-muted)); margin-top: 2px;
      }
    `;
    document.head.appendChild(s);
  },

  async refresh() {
    this._state.busy = true;
    const list = document.getElementById('mt-list');
    list.innerHTML = '<div class="p-4 text-[12px] text-text-muted">Chargement…</div>';
    const banner = document.getElementById('mt-banner');

    // Charge en parallèle : templates + catalogue produits (pour le mode prospection)
    const [res, prods] = await Promise.all([
      this._api('list'),
      this._loadCatalogueProducts(),
    ]);
    this._state.catalogueProducts = prods || [];

    if (!res || !res.ok) {
      banner.innerHTML = `<span class="text-danger">Impossible de charger les templates : ${res && res.error ? res.error : 'erreur inconnue'}.</span>`;
      this._state.products = {};
    } else {
      this._state.products = res.products || {};
      banner.innerHTML = `Templates synchronisés avec Supabase. Choisis dans la barre de gauche entre <strong>Transactionnel</strong> (mails auto envoyés par tes sites) et <strong>Prospection</strong> (mails de démarchage rangés par produit).`;
    }

    this._state.catalog = this._buildCatalog();
    this._state.catalogProspection = this._buildCatalogProspection();
    this._populateSenderFilter();
    this._populateProductFilter();
    this._renderList();

    // Auto-select : premier template du mode courant, ou celui qui était déjà ouvert
    let target = this._state.selected;
    if (!target) {
      const cat = (this._state.categoryMode === 'prospection')
        ? this._state.catalogProspection
        : this._state.catalog;
      for (const info of Object.values(cat || {})) {
        const t = (info.templates || [])[0];
        if (t) { target = { product: t.product, key: t.key }; break; }
      }
    }
    if (target) this.openTemplate(target.product, target.key);
    else this._renderEmptyEditor();

    this._state.busy = false;
  },

  // Charge la liste des produits du Catalogue Triskell (Pixel Pros, Lagriffe…).
  // Utilisée en mode Prospection pour proposer le bon ensemble de produits.
  async _loadCatalogueProducts() {
    if (typeof Catalogue === 'undefined' || typeof Catalogue.list !== 'function') return [];
    try {
      const items = await Catalogue.list();
      return Array.isArray(items) ? items : [];
    } catch (e) {
      console.warn('mail_templates: chargement catalogue produits raté', e);
      return [];
    }
  },

  // Fusionne base + catalogue connu, puis groupe par adresse mail expéditrice.
  // Sortie : { 'noreply@…': { label, address, templates: [...] }, … }
  _buildCatalog() {
    // 1) Index des templates connus par (product, key) pour récupérer
    //    leurs métadonnées (from_address par défaut, runtime, label…)
    const knownByKey = {};
    for (const k of this.KNOWN) {
      knownByKey[`${k.product}::${k.key}`] = k;
    }

    // 2) Liste complète des templates (base + connus pas encore en base) — uniquement transactionnels
    const all = [];
    const dbKeys = new Set();
    for (const [p, info] of Object.entries(this._state.products || {})) {
      for (const t of info.templates || []) {
        const id = `${p}::${t.key}`;
        dbKeys.add(id);
        // En mode transactionnel on ignore les lignes catégorisées 'prospection'
        if ((t.category || 'transactionnel') === 'prospection') continue;
        const meta = knownByKey[id] || {};
        all.push({
          ...t,
          product: p,
          _source: 'db',
          _label: meta.label,
          _runtime: meta.runtime || 'netlify',
          _placeholders: meta.placeholders || t.placeholders || [],
          _default_from_address: meta.from_address || '',
          _default_from_name: meta.from_name || '',
        });
      }
    }
    for (const k of this.KNOWN) {
      const id = `${k.product}::${k.key}`;
      if (dbKeys.has(id)) continue;
      all.push({
        product: k.product, key: k.key,
        from_address: k.from_address || '',
        from_name: k.from_name || '',
        subject: '(modèle par défaut — pas encore édité)',
        description: k.description,
        placeholders: k.placeholders || [],
        enabled: true,
        category: 'transactionnel',
        _source: 'fallback',
        _label: k.label,
        _runtime: k.runtime || 'netlify',
        _placeholders: k.placeholders || [],
        _default_from_address: k.from_address || '',
        _default_from_name: k.from_name || '',
      });
    }

    // 3) Groupage par adresse mail (utilise from_address de la base si
    //    présent, sinon la valeur par défaut du catalogue connu).
    const groups = {};
    for (const t of all) {
      const addr = (t.from_address || t._default_from_address || '(adresse non définie)').toLowerCase();
      if (!groups[addr]) {
        groups[addr] = {
          address: addr,
          label: this.SENDER_LABELS[addr] || addr,
          templates: [],
        };
      }
      groups[addr].templates.push(t);
    }

    // 4) Ordre : SENDER_ORDER d'abord, puis le reste alphabétique
    const ordered = {};
    for (const a of this.SENDER_ORDER) {
      if (groups[a]) { ordered[a] = groups[a]; delete groups[a]; }
    }
    for (const a of Object.keys(groups).sort()) {
      ordered[a] = groups[a];
    }
    return ordered;
  },

  _populateSenderFilter() {
    const sel = document.getElementById('mt-sender-filter');
    if (!sel) return;
    const current = this._state.senderFilter || '';
    const cat = this._state.catalog || {};
    const opts = ['<option value="">— Toutes les adresses —</option>'];
    for (const [addr, info] of Object.entries(cat)) {
      const cnt = (info.templates || []).length;
      if (!cnt) continue;
      const labelExtra = (info.label && info.label !== addr) ? ` — ${info.label}` : '';
      opts.push(`<option value="${this._esc(addr)}" ${addr === current ? 'selected' : ''}>${this._esc(addr)}${this._esc(labelExtra)} (${cnt})</option>`);
    }
    sel.innerHTML = opts.join('');
  },

  _populateProductFilter() {
    const sel = document.getElementById('mt-product-filter');
    if (!sel) return;
    const current = this._state.productFilter || '';
    const cat = this._state.catalogProspection || {};
    const opts = ['<option value="">— Tous les produits —</option>'];
    for (const [pid, info] of Object.entries(cat)) {
      const cnt = (info.templates || []).length;
      const label = info.label || pid;
      opts.push(`<option value="${this._esc(pid)}" ${pid === current ? 'selected' : ''}>${this._esc(label)} (${cnt})</option>`);
    }
    sel.innerHTML = opts.join('');
  },

  // Construit le groupement pour le mode Prospection : par produit du catalogue
  // (Pixel Pros, Lagriffe, RankUs…). On part de la liste des produits du
  // Catalogue Triskell pour que tous les produits soient visibles même sans
  // template encore créé. Les templates en base avec category='prospection'
  // sont rattachés à leur produit. Les produits "techniques" historiques
  // (billing, internal, drip…) sont masqués via PROSPECTION_EXCLUDED_PRODUCTS.
  _buildCatalogProspection() {
    const groups = {};

    // 1) Pré-remplit avec tous les produits du catalogue Triskell
    for (const p of this._state.catalogueProducts || []) {
      if (!p || !p.id) continue;
      if (this.PROSPECTION_EXCLUDED_PRODUCTS.has(p.id)) continue;
      groups[p.id] = {
        id: p.id,
        label: p.name || p.id,
        templates: [],
      };
    }

    // 2) Rattache les templates de prospection existants à leur produit
    for (const [pid, info] of Object.entries(this._state.products || {})) {
      for (const t of info.templates || []) {
        if ((t.category || 'transactionnel') !== 'prospection') continue;
        if (!groups[pid]) {
          // Produit pas dans le catalogue (créé à la main, ou catalogue pas encore chargé)
          groups[pid] = { id: pid, label: pid, templates: [] };
        }
        groups[pid].templates.push({
          ...t,
          product: pid,
          _source: 'db',
          _label: t.label || this._humanKey(t.key),
        });
      }
    }

    // 3) Ordre : produits avec templates d'abord (par nom), puis vides (par nom)
    const withTpl = [];
    const empty = [];
    for (const g of Object.values(groups)) {
      (g.templates.length > 0 ? withTpl : empty).push(g);
    }
    withTpl.sort((a, b) => a.label.localeCompare(b.label, 'fr'));
    empty.sort((a, b) => a.label.localeCompare(b.label, 'fr'));

    const ordered = {};
    for (const g of withTpl) ordered[g.id] = g;
    for (const g of empty)   ordered[g.id] = g;
    return ordered;
  },

  _updateCount(visible, total, countElId = 'mt-count') {
    const el = document.getElementById(countElId);
    if (!el) return;
    el.textContent = visible === total
      ? `${total} modèle${total > 1 ? 's' : ''}`
      : `${visible} sur ${total} modèle${total > 1 ? 's' : ''}`;
  },

  _renderList() {
    if (this._state.categoryMode === 'prospection') {
      this._renderListProspection();
    } else {
      this._renderListTransactionnel();
    }
  },

  _renderListTransactionnel() {
    const list = document.getElementById('mt-list');
    const cat = this._state.catalog;
    const filter = (this._state.senderFilter || '').toLowerCase();
    let html = '';
    let visibleCount = 0;
    let totalCount = 0;
    for (const [addr, info] of Object.entries(cat)) {
      if (!info.templates || info.templates.length === 0) continue;
      totalCount += info.templates.length;
      if (filter && addr !== filter) continue;
      const subLabel = (info.label && info.label !== addr) ? info.label : '';
      html += `
        <div class="mt-product-h">
          <span class="mt-addr">${this._esc(addr)}</span>
          ${subLabel ? `<span class="mt-addr-sub">${this._esc(subLabel)}</span>` : ''}
        </div>`;
      for (const t of info.templates) {
        visibleCount++;
        const isActive = this._state.selected
          && this._state.selected.product === t.product
          && this._state.selected.key === t.key;
        const label = t._label || this._humanKey(t.key);
        let pill = '';
        const isPipeline = t._runtime === 'pipeline';
        if (t._source === 'fallback') {
          pill = isPipeline
            ? '<span class="mt-pill mt-pill-pipeline" title="Modèle codé en dur dans le runner Python — édition pas encore branchée">Pipeline</span>'
            : '<span class="mt-pill">Par défaut</span>';
        } else if (t.enabled === false) {
          pill = '<span class="mt-pill mt-pill-off">Off</span>';
        } else {
          pill = isPipeline
            ? '<span class="mt-pill mt-pill-pipeline">Pipeline · édité</span>'
            : '<span class="mt-pill mt-pill-on">Édité</span>';
        }
        html += `
          <button class="mt-row ${isActive ? 'is-active' : ''}"
                  data-mt-open="${this._esc(t.product)}::${this._esc(t.key)}">
            <div>${this._esc(label)}${pill}</div>
            <div class="mt-row-sub">${this._esc(t.subject || '').slice(0, 80)}</div>
          </button>
        `;
      }
    }
    if (!visibleCount) {
      html = '<div class="p-4 text-[12px] text-text-muted">Aucun modèle ne correspond à ce filtre.</div>';
    }
    list.innerHTML = html;
    list.querySelectorAll('[data-mt-open]').forEach(btn => {
      btn.onclick = () => {
        const [p, k] = btn.dataset.mtOpen.split('::');
        this.openTemplate(p, k);
      };
    });
    this._updateCount(visibleCount, totalCount, 'mt-count');
  },

  _renderListProspection() {
    const list = document.getElementById('mt-list');
    const cat = this._state.catalogProspection || {};
    const filter = (this._state.productFilter || '').trim();
    const audFilter = this._state.audienceFilter || 'all';
    let html = '';
    let visibleCount = 0;
    let totalCount = 0;
    let visibleProducts = 0;
    for (const [pid, info] of Object.entries(cat)) {
      const tpls = info.templates || [];
      // Filtre audience : un template sans audience est compté comme 'creator'
      // (les 5 templates pixel-pros historiques migrés par la 34_).
      const filteredTpls = (audFilter === 'all')
        ? tpls
        : tpls.filter(t => (t.audience || 'creator') === audFilter);
      totalCount += filteredTpls.length;
      if (filter && pid !== filter) continue;
      if (filteredTpls.length === 0 && audFilter !== 'all') continue;
      visibleProducts++;
      html += `
        <div class="mt-prod-h">
          <span class="mt-prod-name">${this._esc(info.label || pid)}</span>
          <span class="mt-prod-count">${filteredTpls.length} modèle${filteredTpls.length > 1 ? 's' : ''}</span>
        </div>`;
      if (filteredTpls.length === 0) {
        html += `<div class="px-3 py-3 text-[12px] text-text-muted italic">
          Aucun mail de prospection. Clique sur <strong>+ Nouveau modèle</strong> pour en créer un.
        </div>`;
        continue;
      }
      for (const t of filteredTpls) {
        visibleCount++;
        const isActive = this._state.selected
          && this._state.selected.product === t.product
          && this._state.selected.key === t.key;
        const label = t._label || t.label || this._humanKey(t.key);
        const aud = t.audience || 'creator';
        const audPill = (aud === 'pro')
          ? '<span class="mt-pill mt-pill-aud-pro" title="Démarchage B2B local — vente directe">Pros</span>'
          : '<span class="mt-pill mt-pill-aud-creator" title="Démarchage créateur — partenariat">Créateurs</span>';
        const pill = (t.enabled === false)
          ? '<span class="mt-pill mt-pill-off">Off</span>'
          : '<span class="mt-pill mt-pill-on">Actif</span>';
        html += `
          <button class="mt-row ${isActive ? 'is-active' : ''}"
                  data-mt-open="${this._esc(t.product)}::${this._esc(t.key)}">
            <div>${this._esc(label)}${audPill}${pill}</div>
            <div class="mt-row-sub">${this._esc(t.subject || '').slice(0, 80)}</div>
          </button>
        `;
      }
    }
    if (visibleProducts === 0) {
      html = '<div class="p-4 text-[12px] text-text-muted">Aucun modèle ne correspond à ce filtre.</div>';
    }
    list.innerHTML = html;
    list.querySelectorAll('[data-mt-open]').forEach(btn => {
      btn.onclick = () => {
        const [p, k] = btn.dataset.mtOpen.split('::');
        this.openTemplate(p, k);
      };
    });
    this._updateCount(visibleCount, totalCount, 'mt-count-prosp');
  },

  // ---------- Open / edit ----------
  async openTemplate(product, key) {
    this._state.selected = { product, key };
    this._renderList();
    this._renderEditor({ loading: true });

    // Charge depuis la base
    const res = await this._api('get', { product, key });
    const known = this.KNOWN.find(k => k.product === product && k.key === key) || {};
    let tpl;
    if (res && res.ok && res.template) {
      tpl = {
        ...res.template,
        category: res.template.category || 'transactionnel',
        _runtime: known.runtime || 'netlify',
        _label: res.template.label || known.label,
      };
    } else {
      // Pas en base : template "à créer". Pré-rempli depuis le catalogue connu.
      // (Cas exclusivement transactionnel — un nouveau prospection passe par openNewProspection.)
      tpl = {
        product, key,
        from_address: known.from_address || 'noreply@triskell-studio.fr',
        from_name: known.from_name || this._defaultFromName(product),
        subject: '',
        body_html: '',
        body_text: '',
        description: known.description || '',
        placeholders: known.placeholders || [],
        enabled: true,
        category: 'transactionnel',
        label: '',
        _isNew: true,
        _runtime: known.runtime || 'netlify',
        _label: known.label,
      };
    }
    this._state.editing = JSON.parse(JSON.stringify(tpl));
    this._renderEditor({});
  },

  // Ouvre l'éditeur sur un nouveau template de prospection (vide).
  // Le produit sélectionné par défaut est celui du filtre courant, sinon
  // le premier produit du catalogue.
  openNewProspection() {
    const cat = this._state.catalogProspection || {};
    let pid = this._state.productFilter || '';
    if (!pid) {
      const firstId = Object.keys(cat)[0];
      pid = firstId || 'pixel-pros';
    }
    const prodInfo = cat[pid] || { id: pid, label: pid };
    // Génère une clé technique unique : prosp_<timestamp_court>
    const ts = Date.now().toString(36);
    const key = `prosp_${ts}`;
    const tpl = {
      product: pid,
      key,
      from_address: 'contact@triskell-studio.fr',
      from_name: 'Jordan Bourillot',
      subject: '',
      body_html: '',
      body_text: '',
      description: '',
      placeholders: ['name', 'first_name', 'signature'],
      enabled: true,
      category: 'prospection',
      label: '',
      _isNew: true,
      _runtime: 'manual',
      _label: `Nouveau modèle — ${prodInfo.label || pid}`,
      _productLabel: prodInfo.label || pid,
    };
    this._state.selected = { product: pid, key };
    this._state.editing = tpl;
    this._renderList();
    this._renderEditor({});
  },

  _renderEmptyEditor() {
    const e = document.getElementById('mt-editor');
    e.innerHTML = `<div class="p-8 text-center text-text-muted text-sm">
      Sélectionne un modèle dans la colonne de gauche pour l'éditer.
    </div>`;
  },

  _renderEditor({ loading } = {}) {
    const e = document.getElementById('mt-editor');
    if (loading) {
      e.innerHTML = '<div class="p-8 text-center text-text-muted text-sm">Chargement du modèle…</div>';
      return;
    }
    const t = this._state.editing;
    if (!t) { this._renderEmptyEditor(); return; }

    const isNew = !!t._isNew;
    const isProspection = (t.category === 'prospection');
    const placeholders = Array.isArray(t.placeholders) ? t.placeholders : [];
    const senderAddr = (t.from_address || '').trim() || '(adresse non définie)';
    const senderLabel = this.SENDER_LABELS[senderAddr.toLowerCase()] || '';
    const headerLabel = t._label || t.label || this._humanKey(t.key);
    const isPipeline = t._runtime === 'pipeline';

    // En prospection on affiche le produit du catalogue plutôt que l'adresse mail
    const cat = this._state.catalogProspection || {};
    const productLabel = (cat[t.product] && cat[t.product].label)
      || t._productLabel
      || t.product;

    // Petites pastilles contextuelles : type + cible. Concises, en haut.
    const typeChip = isProspection
      ? `<span class="mt-chip mt-chip-prosp" title="Mail de prospection — envoi manuel">📨 Prospection</span>`
      : `<span class="mt-chip mt-chip-auto" title="Mail transactionnel — envoyé automatiquement par tes sites">🤖 Auto</span>`;
    const targetChip = isProspection
      ? `<span class="mt-chip mt-chip-target">${this._esc(productLabel)}</span>`
      : `<span class="mt-chip mt-chip-target" title="${this._esc(senderLabel || '')}">${this._esc(senderAddr)}</span>`;

    // Bandeau d'avertissement : un seul, le plus pertinent
    let warnHtml = '';
    if (!isProspection && isPipeline) {
      warnHtml = `<div class="mt-warn">⚠ Modifications stockées en base, mais le runner Python lit encore son texte par défaut. Branchage à faire en phase suivante.</div>`;
    } else if (!isProspection && isNew) {
      warnHtml = `<div class="mt-warn">Modèle pas encore édité — la fonction Netlify utilise sa version par défaut. Modifie et enregistre pour reprendre la main.</div>`;
    }

    e.innerHTML = `
      <!-- En-tête minimal : titre + 2 chips. La description et la clé tech sont dépliables. -->
      <div class="mb-4 pb-3 border-b border-border">
        <div class="flex items-center gap-2 mb-2 flex-wrap">
          ${typeChip}
          ${targetChip}
        </div>
        <h2 class="text-lg font-bold leading-tight">${this._esc(headerLabel)}</h2>
        ${t.description ? `<p class="text-[12.5px] text-text-muted mt-1 leading-snug">${this._esc(t.description)}</p>` : ''}
        ${warnHtml}
      </div>

      <!-- Tabs Édition / Aperçu — par défaut on ouvre sur Aperçu pour
           que Jordan voie tout de suite à quoi ressemble le mail final ;
           si besoin d'éditer il bascule sur l'onglet ✎ Édition. -->
      <div class="mt-tabs">
        <button class="mt-tab" data-mt-pane="edit">✎ Édition</button>
        <button class="mt-tab is-active" data-mt-pane="preview">👁 Aperçu</button>
      </div>

      <div id="mt-pane-edit" style="display:none;">
        ${isProspection ? `
        <!-- CATÉGORIE DE PROSPECT CIBLÉE : à choisir manuellement.
             L'autopilote utilisera ensuite cette info pour piocher dans
             les bons modèles selon le type de prospect qu'il traite. -->
        <div class="mt-field">
          <label>Catégorie de prospect ciblée par ce modèle</label>
          <div class="flex flex-wrap gap-2 mt-1.5"
               data-mt-audience-current="${this._esc(t.audience || 'creator')}">
            <button type="button" class="mt-audsel-btn"
                    data-mt-audsel="creator">
              Créateurs / Influenceurs
            </button>
            <button type="button" class="mt-audsel-btn"
                    data-mt-audsel="pro">
              Pros / Entreprises
            </button>
          </div>
          <div class="text-[11px] text-text-muted mt-1.5"
               style="text-wrap: pretty">
            L'auto-pilote n'enverra ce modèle qu'aux prospects de cette catégorie.
          </div>
        </div>
        ` : ''}

        <!-- SUJET : grand, c'est ce que voit le destinataire en premier -->
        <div class="mt-field mt-field-hero">
          <label>Sujet du mail</label>
          <input id="mt-subject" value="${this._esc(t.subject || '')}" placeholder="${isProspection ? 'Une idée pour monétiser ton audience' : 'Votre maquette Lagriffe Studio vous attend'}">
        </div>

        ${placeholders.length ? `
          <div class="mt-placeholders-row">
            <span class="text-[10.5px] font-bold tracking-wider uppercase text-text-muted shrink-0">Insérer :</span>
            <div class="mt-placeholders-chips">${placeholders.map(p => `<span class="mt-placeholder-chip" data-mt-insert="{{${this._esc(p)}}}">{{${this._esc(p)}}}</span>`).join('')}</div>
          </div>
        ` : ''}

        <!-- CORPS HTML : dominant, le cœur de la page -->
        <div class="mt-field">
          <div class="flex items-center justify-between gap-2 flex-wrap mb-1">
            <label style="margin:0; padding:0;">Corps du mail (HTML)</label>
            <button id="mt-insert-product" type="button"
                    class="px-2.5 py-1 rounded-lg text-[11px] font-semibold border border-border text-text-muted hover:border-accent hover:text-accent transition-colors"
                    title="Insérer un produit du Catalogue Triskell">
              + Produit du Catalogue
            </button>
          </div>
          <textarea id="mt-body-html" class="mt-textarea-hero" spellcheck="false" placeholder="<p>Bonjour {{first_name}},</p>…">${this._esc(t.body_html || '')}</textarea>
        </div>

        <!-- Bloc replié : tout ce qui est secondaire (expéditeur, fallback texte, actif…) -->
        <details class="mt-advanced">
          <summary>⚙ Réglages avancés <span class="text-text-muted text-[11px]">— expéditeur, texte brut, activation…</span></summary>
          <div class="mt-advanced-body">
            ${isProspection ? `
              <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
                <label class="mt-field">
                  <label>Titre du modèle (interne)</label>
                  <input id="mt-label" value="${this._esc(t.label || '')}" placeholder="Mail 1 — commission classique">
                </label>
                <label class="mt-field">
                  <label>Produit</label>
                  <select id="mt-product-select">${this._renderProductOptions(t.product)}</select>
                </label>
              </div>
            ` : ''}

            <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
              <label class="mt-field">
                <label>Expéditeur (nom)</label>
                <input id="mt-from-name" value="${this._esc(t.from_name || '')}" placeholder="Lagriffe Studio">
              </label>
              <label class="mt-field">
                <label>Expéditeur (adresse)</label>
                <input id="mt-from-address" value="${this._esc(t.from_address || '')}" placeholder="noreply@triskell-studio.fr">
              </label>
            </div>

            <div class="mt-field">
              <label>Corps texte (fallback pour les clients mail sans HTML)</label>
              <textarea id="mt-body-text" spellcheck="false" style="min-height: 90px;" placeholder="Version texte brut, optionnelle.">${this._esc(t.body_text || '')}</textarea>
            </div>

            <label class="mt-field-inline">
              <input type="checkbox" id="mt-enabled" ${t.enabled !== false ? 'checked' : ''}>
              <span>Modèle actif <span class="text-text-muted text-[12px]">— si décoché, la fonction Netlify retombe sur sa version par défaut.</span></span>
            </label>

            <div class="text-[11px] text-text-muted pt-2 border-t border-border/50">
              Clé technique&nbsp;: <code>${this._esc(t.product)}::${this._esc(t.key)}</code>
            </div>
          </div>
        </details>

        <!-- Toolbar : enregistrer + supprimer + date de modif -->
        <div class="mt-toolbar">
          <div class="grow text-[11px] text-text-muted">
            ${t.updated_at ? `Dernière modif&nbsp;: ${this._formatDate(t.updated_at)}${t.updated_by ? ` par ${this._esc(t.updated_by)}` : ''}` : ''}
          </div>
          ${!isNew ? `<button id="mt-delete" class="btn btn-ghost text-danger">Supprimer</button>` : ''}
          <button id="mt-save" class="btn btn-primary">💾 Enregistrer</button>
        </div>
      </div>

      <div id="mt-pane-preview">
        <iframe id="mt-preview-iframe" class="mt-preview-frame" sandbox=""></iframe>
        <p class="text-[11px] text-text-muted mt-3">Les variables <code>{{…}}</code> sont remplacées par des valeurs d'exemple ci-dessus.</p>
      </div>
    `;

    // Binds
    e.querySelectorAll('[data-mt-pane]').forEach(b => b.onclick = () => this._switchPane(b.dataset.mtPane));
    e.querySelectorAll('[data-mt-insert]').forEach(c => c.onclick = () => this._insertPlaceholder(c.dataset.mtInsert));
    // Sélecteur catégorie de prospect (prospection uniquement) : 2 boutons
    // qui agissent comme des radios. La valeur courante est stockée sur le
    // parent via data-mt-audience-current — c'est ce que `save()` relira.
    e.querySelectorAll('.mt-audsel-btn').forEach(btn => {
      this._styleAudBtn(btn);
      btn.onclick = () => {
        const wrap = btn.closest('[data-mt-audience-current]');
        if (!wrap) return;
        wrap.dataset.mtAudienceCurrent = btn.dataset.mtAudsel;
        wrap.querySelectorAll('.mt-audsel-btn').forEach(b => this._styleAudBtn(b));
      };
    });
    const prodBtn = document.getElementById('mt-insert-product');
    if (prodBtn && typeof Catalogue !== 'undefined') {
      prodBtn.onclick = () => {
        Catalogue.pickProduct((product) => {
          if (!product) return;
          this._insertPlaceholder(Catalogue.snippetHtml(product));
        });
      };
    }
    document.getElementById('mt-save').onclick = () => this.save();
    const delBtn = document.getElementById('mt-delete');
    if (delBtn) delBtn.onclick = () => this.deleteCurrent();
    // L'onglet par défaut est "Aperçu" : on remplit l'iframe tout de suite
    // sinon elle s'affiche blanche tant qu'on n'a pas re-cliqué.
    this._renderPreview();
  },

  _switchPane(name) {
    document.querySelectorAll('[data-mt-pane]').forEach(b => b.classList.toggle('is-active', b.dataset.mtPane === name));
    document.getElementById('mt-pane-edit').style.display    = (name === 'edit')    ? '' : 'none';
    document.getElementById('mt-pane-preview').style.display = (name === 'preview') ? '' : 'none';
    if (name === 'preview') this._renderPreview();
  },

  // Applique le style "actif" ou "inactif" à un bouton du sélecteur catégorie
  // de prospect. La valeur courante est dans wrap.dataset.mtAudienceCurrent.
  // ATTENTION : on garde la classe `mt-audsel-btn` dans le className, sinon
  // au clic suivant le querySelectorAll('.mt-audsel-btn') ne retrouve plus les
  // boutons et la sélection visuelle ne se met plus à jour.
  _styleAudBtn(btn) {
    const wrap = btn.closest('[data-mt-audience-current]');
    if (!wrap) return;
    const active = btn.dataset.mtAudsel === wrap.dataset.mtAudienceCurrent;
    const base = 'mt-audsel-btn px-3 py-1.5 rounded-lg text-[12px] font-semibold border transition-colors';
    if (active) {
      btn.className = base + ' bg-accent text-white border-accent';
    } else {
      btn.className = base + ' bg-bg border-border text-text-muted hover:text-text hover:border-accent/50';
    }
  },

  _renderPreview() {
    const subject = (document.getElementById('mt-subject') || {}).value || '';
    const body    = (document.getElementById('mt-body-html') || {}).value || '';
    const sample = this._samplePlaceholders(this._state.editing);
    const subj = this._fillPlaceholders(subject, sample);
    const html = this._fillPlaceholders(body, sample);
    const iframe = document.getElementById('mt-preview-iframe');
    const doc = `<!doctype html><html><head><meta charset="utf-8"><title>${this._esc(subj)}</title><style>body{font-family:'Inter',-apple-system,sans-serif;margin:0;padding:24px;background:#FAFAF8;color:#0A0E0C;}</style></head><body>${html}</body></html>`;
    iframe.srcdoc = doc;
  },

  _renderProductOptions(currentProduct) {
    const cat = this._state.catalogProspection || {};
    const ids = Object.keys(cat);
    if (ids.length === 0) {
      // Fallback : au moins le produit courant
      return `<option value="${this._esc(currentProduct)}" selected>${this._esc(currentProduct)}</option>`;
    }
    return ids.map(pid => {
      const label = cat[pid].label || pid;
      const sel = (pid === currentProduct) ? 'selected' : '';
      return `<option value="${this._esc(pid)}" ${sel}>${this._esc(label)}</option>`;
    }).join('');
  },

  _insertPlaceholder(text) {
    const ta = document.getElementById('mt-body-html');
    if (!ta) return;
    const start = ta.selectionStart || 0;
    const end = ta.selectionEnd || 0;
    ta.value = ta.value.slice(0, start) + text + ta.value.slice(end);
    ta.focus();
    ta.selectionStart = ta.selectionEnd = start + text.length;
  },

  // ---------- Save / delete ----------
  async save() {
    const t = this._state.editing;
    if (!t) return;
    const isProspection = (t.category === 'prospection');

    const fields = {
      from_name:    document.getElementById('mt-from-name').value.trim(),
      from_address: document.getElementById('mt-from-address').value.trim(),
      subject:      document.getElementById('mt-subject').value,
      body_html:    document.getElementById('mt-body-html').value,
      body_text:    document.getElementById('mt-body-text').value,
      enabled:      document.getElementById('mt-enabled').checked,
      placeholders: Array.isArray(t.placeholders) ? t.placeholders : [],
      description:  t.description || '',
      category:     t.category || 'transactionnel',
    };
    if (isProspection) {
      const labelEl = document.getElementById('mt-label');
      fields.label = labelEl ? labelEl.value.trim() : (t.label || '');
      if (!fields.label) {
        alert('Le titre du modèle est obligatoire (ex. "Mail 1 — commission classique").');
        return;
      }
      // Catégorie de prospect choisie via le sélecteur. Si l'utilisateur n'a
      // pas vu / pas choisi, on conserve la valeur existante (par défaut
      // 'creator' pour les vieux modèles d'avant cette UI).
      const audWrap = document.querySelector('[data-mt-audience-current]');
      const audVal = audWrap
        ? (audWrap.dataset.mtAudienceCurrent || 'creator')
        : (t.audience || 'creator');
      fields.audience = (audVal === 'pro') ? 'pro' : 'creator';
    }
    if (!fields.subject) {
      alert('Le sujet du mail est obligatoire.');
      return;
    }
    if (!fields.from_address) {
      alert('L\'adresse d\'expéditeur est obligatoire.');
      return;
    }

    // En prospection, le produit peut être changé via le select.
    let targetProduct = t.product;
    if (isProspection) {
      const prodSel = document.getElementById('mt-product-select');
      if (prodSel && prodSel.value && prodSel.value !== t.product) {
        targetProduct = prodSel.value;
      }
    }

    const btn = document.getElementById('mt-save');
    if (btn) { btn.disabled = true; btn.textContent = 'Enregistrement…'; }

    // Si le produit a changé, on supprime l'ancien enregistrement (s'il existait)
    // puis on upsert sous le nouveau couple (product, key).
    if (isProspection && targetProduct !== t.product && !t._isNew) {
      await this._api('delete', { product: t.product, key: t.key });
    }

    const res = await this._api('save', { product: targetProduct, key: t.key, fields });
    if (btn) { btn.disabled = false; btn.textContent = 'Enregistrer'; }
    if (!res || !res.ok) {
      alert('Échec de l\'enregistrement : ' + (res && res.error || 'erreur inconnue'));
      return;
    }
    // Met à jour la sélection (utile si on a changé de produit ou créé un nouveau)
    this._state.selected = { product: targetProduct, key: t.key };
    this._toast(isProspection
      ? 'Modèle de prospection enregistré.'
      : 'Modèle enregistré. Effet immédiat (cache 60 s max côté Netlify).');
    await this.refresh();
  },

  async deleteCurrent() {
    const t = this._state.editing;
    if (!t) return;
    if (!confirm('Supprimer ce modèle ? La fonction Netlify retombera sur sa version codée en dur.')) return;
    const res = await this._api('delete', { product: t.product, key: t.key });
    if (!res || !res.ok) {
      alert('Échec : ' + (res && res.error || 'erreur inconnue'));
      return;
    }
    this._toast('Modèle supprimé.');
    this._state.selected = null;
    this._state.editing = null;
    await this.refresh();
  },

  // ---------- Utils ----------
  _samplePlaceholders(t) {
    const samples = {
      first_name: 'Jordan',
      last_name: 'Bourillot',
      company_name: 'Atelier du Tertre',
      customize_url: 'https://lagriffe-studio.fr/personnaliser?id=xxx',
      mockup_url:    'https://maquette.exemple.fr',
      site_url:      'https://votre-site.fr',
      final_site_url:'https://votre-site.fr',
      amount:        '49',
      currency:      'EUR',
      email:         'client@exemple.fr',
    };
    return samples;
  },
  _fillPlaceholders(str, vars) {
    return String(str || '').replace(/\{\{\s*([a-zA-Z0-9_]+)\s*\}\}/g, (_, n) => (vars[n] !== undefined ? String(vars[n]) : `{{${n}}}`));
  },
  _defaultFromName(product) {
    // Lookup d'abord dans le catalogue KNOWN (source de vérité unique),
    // fallback ensuite sur une table courte pour les produits Lagriffe-style.
    const k = (this.KNOWN || []).find(x => x.product === product);
    if (k && k.from_name) return k.from_name;
    return ({ lagriffe: 'Lagriffe Studio', rankus: 'RankUs Studio', wow: 'Studio WoW',
             shared: 'Triskell Studio' })[product] || 'Triskell Studio';
  },
  _humanKey(k) {
    return String(k || '')
      .replace(/_/g, ' ')
      .replace(/\bj(\d+)\b/g, 'J+$1')
      .replace(/\b\w/g, c => c.toUpperCase());
  },
  _formatDate(iso) {
    try {
      const d = new Date(iso);
      return d.toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' });
    } catch { return iso; }
  },
  _esc(s) {
    return String(s ?? '')
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  },
  _toast(msg) {
    let el = document.getElementById('mt-toast');
    if (!el) {
      el = document.createElement('div');
      el.id = 'mt-toast';
      el.style.cssText = 'position:fixed;bottom:20px;right:20px;background:hsl(var(--accent));color:white;padding:10px 16px;border-radius:8px;font-size:13px;font-weight:600;box-shadow:0 6px 24px rgba(0,0,0,.18);z-index:9999;opacity:0;transition:opacity 180ms;';
      document.body.appendChild(el);
    }
    el.textContent = msg;
    requestAnimationFrame(() => { el.style.opacity = '1'; });
    clearTimeout(this._toastTimer);
    this._toastTimer = setTimeout(() => { el.style.opacity = '0'; }, 2800);
  },
};

window.MailTemplates = MailTemplates;
