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
    mailAccounts: [], // adresses d’envoi configurées (câblage modèle→adresse en prospection)
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
      description: 'Envoyé quand la maquette est en ligne et que le client peut commencer la personnalisation.',
      placeholders: ['first_name', 'customize_url'],
      from_address: 'noreply@triskell-studio.fr', from_name: 'Lagriffe Studio',
      runtime: 'netlify' },
    { product: 'lagriffe', key: 'payment_confirmed', label: 'Confirmation de paiement',
      description: 'Envoyé automatiquement juste après un paiement réussi.',
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
      description: 'Réponse auto envoyée quand un prospect dit être intéressé par un produit du catalogue. Ce texte sert de base : l’IA l’adapte légèrement au message reçu. Le sujet reste « Re: … » pour garder le fil.',
      placeholders: ['name', 'product_name', 'product_link', 'signature'],
      from_address: 'contact@triskell-studio.fr', from_name: 'Jordan Bourillot',
      runtime: 'live' },
    { product: 'reply', key: 'not_now', label: 'Réponse IA — pas maintenant',
      description: 'Réponse polie quand le prospect dit que ce n\'est pas le bon moment. Le sujet reste « Re: … » pour garder le fil.',
      placeholders: ['name', 'signature'],
      from_address: 'contact@triskell-studio.fr', from_name: 'Jordan Bourillot',
      runtime: 'live' },
    { product: 'reply', key: 'no', label: 'Réponse IA — refus',
      description: 'Réponse courte et propre quand le prospect refuse. Le sujet reste « Re: … » pour garder le fil.',
      placeholders: ['name', 'signature'],
      from_address: 'contact@triskell-studio.fr', from_name: 'Jordan Bourillot',
      runtime: 'live' },
    { product: 'reply', key: 'unsubscribe', label: 'Réponse IA — désinscription',
      description: 'Confirmation de désinscription. Le sujet reste « Re: … » pour garder le fil.',
      placeholders: ['name', 'signature'],
      from_address: 'contact@triskell-studio.fr', from_name: 'Jordan Bourillot',
      runtime: 'live' },
    { product: 'reply', key: 'unknown', label: 'Réponse IA — intention floue',
      description: 'Quand l\'IA n\'arrive pas à classer la réponse, on envoie un message neutre. Le sujet reste « Re: … » pour garder le fil.',
      placeholders: ['name', 'signature'],
      from_address: 'contact@triskell-studio.fr', from_name: 'Jordan Bourillot',
      runtime: 'live' },

    // ============ contact@triskell-studio.fr — Relances espacées (prospection) ============
    { product: 'drip', key: 'follow_up_7d', label: 'Relance J+7 (si pas de réponse)',
      description: 'Première relance prospect, 7 jours après le premier mail si pas de réponse.',
      placeholders: ['name', 'signature'],
      from_address: 'contact@triskell-studio.fr', from_name: 'Jordan Bourillot',
      runtime: 'live' },
    { product: 'drip', key: 'follow_up_30d', label: 'Relance J+30 — dernier rappel',
      description: 'Relance finale, 30 jours après le premier mail.',
      placeholders: ['name', 'signature', 'soft_hook'],
      from_address: 'contact@triskell-studio.fr', from_name: 'Jordan Bourillot',
      runtime: 'live' },

    // ============ contact@triskell-studio.fr — Post-vente (suivi client) ============
    { product: 'post_sale', key: 'welcome_at_paid', label: 'Bienvenue après achat',
      description: 'Envoyé automatiquement à l\'instant du paiement (paid_at).',
      placeholders: ['client_name', 'product_name', 'signature'],
      from_address: 'contact@triskell-studio.fr', from_name: 'Jordan Bourillot',
      runtime: 'pipeline' },
    { product: 'post_sale', key: 'cross_sell_30d', label: 'Proposition complémentaire J+30',
      description: '30 jours après l\'achat, proposition d\'un produit complémentaire.',
      placeholders: ['client_name', 'product_name', 'next_product_name', 'next_product_link', 'signature'],
      from_address: 'contact@triskell-studio.fr', from_name: 'Jordan Bourillot',
      runtime: 'live' },
    { product: 'post_sale', key: 'nps_90d', label: 'Sondage satisfaction J+90',
      description: '90 jours après l’achat, demande d’avis (note de satisfaction).',
      placeholders: ['client_name', 'product_name', 'signature'],
      from_address: 'contact@triskell-studio.fr', from_name: 'Jordan Bourillot',
      runtime: 'live' },

    // ============ contact@pixel-pros.fr — Pixel Pros (mails clients) ============
    { product: 'pixelpros', key: 'paid', label: 'Paiement reçu — décris ton activité',
      description: 'Envoyé juste après le paiement Stripe : invite le client à décrire son activité.',
      placeholders: ['firstname', 'business', 'complete_url'],
      from_address: 'contact@pixel-pros.fr', from_name: 'Pixel Pros',
      runtime: 'live' },
    { product: 'pixelpros', key: 'live', label: 'Ton site est en ligne',
      description: 'Envoyé quand le site du client est publié sur son adresse.',
      placeholders: ['firstname', 'business', 'site_url'],
      from_address: 'contact@pixel-pros.fr', from_name: 'Pixel Pros',
      runtime: 'live' },

    // ============ contact@triskell-studio.fr — Livraisons produits Triskell ============
    { product: 'delivery_pack_elec', key: 'welcome', label: 'Pack Électricien Pro — Bienvenue',
      description: 'Mail de bienvenue envoyé après achat du Pack Électricien Pro.',
      placeholders: ['client_name', 'deliverables_list', 'signature'],
      from_address: 'contact@triskell-studio.fr', from_name: 'Triskell Studio',
      runtime: 'pipeline' },
    { product: 'delivery_pack_elec', key: 'followup_3d', label: 'Pack Électricien Pro — Suivi J+3',
      description: '3 jours après livraison : on vérifie que tout est bien reçu.',
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

    // ============ Triskell interne (résumé du matin, alertes Phare, factures) ============
    { product: 'internal', key: 'morning_digest', label: 'Triskell Matinale (résumé de 8 h)',
      description: 'Envoyé chaque matin à 8 h : résumé des chiffres clés et des alertes.',
      placeholders: [],
      from_address: 'jordan@triskell-studio.fr', from_name: 'Triskell Matinale',
      runtime: 'pipeline' },
    { product: 'internal', key: 'phare_analyst_report', label: 'Alerte Phare — rapport analyste',
      description: 'Notification interne quand un analyste du Phare termine un rapport.',
      placeholders: ['title', 'body'],
      from_address: 'jordan@triskell-studio.fr', from_name: 'Le Phare',
      runtime: 'pipeline' },
    { product: 'internal', key: 'phare_validation_alert', label: 'Alerte Phare — validation de page',
      description: 'Notification interne quand un changement sur une page attend ta validation.',
      placeholders: ['title', 'body'],
      from_address: 'jordan@triskell-studio.fr', from_name: 'Le Phare',
      runtime: 'pipeline' },
    { product: 'internal', key: 'phare_reject_alert', label: 'Alerte Phare — modification refusée',
      description: 'Notification interne quand une modification du Phare est refusée.',
      placeholders: ['title', 'body'],
      from_address: 'jordan@triskell-studio.fr', from_name: 'Le Phare',
      runtime: 'pipeline' },

    // ============ billing@triskell-studio.fr — Factures Stripe ============
    { product: 'billing', key: 'invoice_email', label: 'Facture émise',
      description: 'Mail envoyé au client après un paiement réussi, avec la facture PDF en pièce jointe.',
      placeholders: ['client_name', 'invoice_number', 'amount', 'currency'],
      from_address: 'billing@triskell-studio.fr', from_name: 'Triskell Studio (facturation)',
      runtime: 'pipeline' },
  ],

  // Libellés humains des regroupements par adresse mail. Les adresses
  // inconnues tombent sur un libellé générique.
  SENDER_LABELS: {
    'noreply@triskell-studio.fr':  'Sites Triskell (mails automatiques)',
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
    // Garde anti-perte : si une édition était en cours (re-navigation vers
    // cette vue, changement d'onglet sidebar), on demande confirmation avant
    // de tout reconstruire. La copie de travail est synchronisée pendant la
    // frappe, donc la détection marche même si le routeur a déjà vidé le DOM.
    // Refus → on reste sur l'onglet courant et la saisie est ré-affichée.
    let keepEditing = false;
    if (this._root && this._state.editing && this._isDirty()) {
      const ok = await this._confirmDiscard();
      if (!ok) keepEditing = true;
    }
    this._root = container;
    // L'onglet (transactionnel / prospection) est piloté par la sidebar.
    const tab = params && params.tab;
    if (!keepEditing && (tab === 'transactionnel' || tab === 'prospection')) {
      if (this._state.categoryMode !== tab) {
        this._state.selected = null;
        this._state.editing = null;
        this._state.pristine = null;
      }
      this._state.categoryMode = tab;
    }
    this._state.keepEditing = keepEditing;
    const isProsp = (this._state.categoryMode === 'prospection');
    const transacDisplay = isProsp ? 'none' : 'flex';
    const prospDisplay   = isProsp ? 'flex' : 'none';
    const audSel = this._state.audienceFilter || 'all';
    container.innerHTML = `
      <section class="animate-slide-up">
        <!-- En-tête épuré : titre court, pas de gros pavé d'intro -->
        <header class="mb-3 flex items-center justify-between gap-4 flex-wrap">
          <div>
            <h1 class="text-2xl font-bold leading-tight">Modèles de mails</h1>
            <p class="text-sm text-text-muted mt-1">Sujet, expéditeur, corps — tout se règle ici, sans toucher au code.</p>
          </div>
          <div class="flex items-center gap-2">
            <button id="mt-banner-help" class="btn btn-secondary text-[12px]" title="Comment ça marche ?">ⓘ Aide</button>
            <button id="mt-refresh" class="btn btn-secondary text-sm">↻ Rafraîchir</button>
          </div>
        </header>

        <!-- Encadré de repérage : ce que cet écran pilote (et ce qu'il ne pilote pas) -->
        <div class="mb-3 text-[12px] leading-relaxed text-text-muted px-3 py-2 rounded-lg bg-accent/5 border border-accent/20">
          <strong>Après-achat</strong> = les mails automatiques envoyés à tes clients après une vente (bienvenue, livraison, relances de suivi) ·
          <strong>Prospection</strong> = les mails que l’Auto-pilote envoie tels quels aux prospects pour les démarcher.<br>
          Les modèles du composeur de mails et des autres outils se gèrent dans leurs écrans.
        </div>

        <!-- Banner d'aide masqué par défaut, affichable via le bouton ⓘ.
             Sert aussi de bandeau d'erreur VISIBLE quand le chargement échoue. -->
        <div id="mt-banner" class="mb-4 text-[12px] text-text-muted px-3 py-2 rounded-lg bg-accent/5 border border-accent/20" style="display:none;" aria-live="polite"></div>

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
            <button class="mt-aud-btn ${audSel === 'all' ? 'is-active' : ''}" data-mt-aud="all" role="tab" aria-selected="${audSel === 'all'}">Tous</button>
            <button class="mt-aud-btn ${audSel === 'creator' ? 'is-active' : ''}" data-mt-aud="creator" role="tab" aria-selected="${audSel === 'creator'}" title="Démarchage de créateurs / influenceurs (partenariats, codes promo, commissions)">Créateurs</button>
            <button class="mt-aud-btn ${audSel === 'pro' ? 'is-active' : ''}" data-mt-aud="pro" role="tab" aria-selected="${audSel === 'pro'}" title="Démarchage d’entreprises locales (commerces, artisans, cabinets) — vente directe">Pros</button>
          </div>
          <button id="mt-new-prosp" class="btn btn-primary text-sm">+ Nouveau modèle</button>
          <span id="mt-count-prosp" class="text-[11px] text-text-muted ml-auto"></span>
        </div>

        <div class="grid grid-cols-1 lg:grid-cols-[300px_1fr] gap-4">
          <aside id="mt-list" class="bg-surface-elevated border border-border rounded-xl p-2 overflow-y-auto" style="max-height: calc(100vh - 240px);"></aside>
          <main  id="mt-editor" class="bg-surface-elevated border border-border rounded-xl p-5 min-h-[500px]"></main>
        </div>
      </section>
    `;
    this._injectStyles();
    // Le bandeau contient l'aide STATIQUE dès le départ : cliquer sur ⓘ Aide
    // marche même si le chargement n'est pas terminé (ou a échoué).
    this._setBannerHelp();
    const helpBtn = document.getElementById('mt-banner-help');
    const banner  = document.getElementById('mt-banner');
    if (helpBtn && banner) {
      helpBtn.onclick = () => {
        banner.style.display = (banner.style.display === 'none') ? '' : 'none';
      };
    }
    document.getElementById('mt-refresh').onclick = async () => {
      if (!(await this._confirmDiscard())) return;
      this.refresh();
    };
    document.getElementById('mt-sender-filter').onchange = (e) => {
      this._state.senderFilter = e.target.value;
      this._renderList();
    };
    document.getElementById('mt-product-filter').onchange = (e) => {
      this._state.productFilter = e.target.value;
      this._renderList();
    };
    document.getElementById('mt-new-prosp').onclick = async () => {
      if (!(await this._confirmDiscard())) return;
      this.openNewProspection();
    };
    document.querySelectorAll('[data-mt-aud]').forEach(btn => {
      btn.onclick = () => this._switchAudience(btn.dataset.mtAud);
    });
    await this.refresh();
  },

  _switchAudience(aud) {
    if (!['all', 'creator', 'pro'].includes(aud)) return;
    if (this._state.audienceFilter === aud) return;
    this._state.audienceFilter = aud;
    document.querySelectorAll('[data-mt-aud]').forEach(b => {
      const active = b.dataset.mtAud === aud;
      b.classList.toggle('is-active', active);
      b.setAttribute('aria-selected', String(active));
    });
    this._renderList();
  },

  // ---------- Bandeau d'aide / d'erreur ----------
  // Texte d'aide statique : ne dépend PAS du chargement.
  _setBannerHelp() {
    const banner = document.getElementById('mt-banner');
    if (!banner) return;
    banner.classList.remove('mt-banner-error');
    banner.innerHTML = `<strong>Comment ça marche ?</strong>
      Chaque mail automatique a un modèle : sujet, expéditeur, corps.
      Tant que tu n’as rien enregistré, la version par défaut est utilisée ;
      enregistre ta version pour reprendre la main, décoche « Modèle actif » pour revenir en arrière.
      Les modèles de <strong>prospection</strong> sont envoyés tels quels par l’Auto-pilote —
      il remplit seulement les variables <code>{{…}}</code>, il ne réécrit rien.`;
  },

  // Bandeau d'erreur VISIBLE (échec de chargement) avec bouton Réessayer.
  _showBannerError(msg) {
    const banner = document.getElementById('mt-banner');
    if (!banner) return;
    banner.classList.add('mt-banner-error');
    banner.style.display = '';
    banner.innerHTML = `
      <span>⚠ ${this._esc(msg)}</span>
      <button id="mt-banner-retry" class="btn btn-secondary text-[12px]">Réessayer</button>`;
    const retry = document.getElementById('mt-banner-retry');
    if (retry) retry.onclick = () => this.refresh();
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
        display: block; font-size: 11px; letter-spacing: .12em; text-transform: uppercase;
        color: hsl(var(--text-muted)); margin-top: 2px;
      }
      /* Bandeau en mode erreur (échec de chargement) */
      #mt-banner.mt-banner-error {
        display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
        background: hsl(var(--danger) / .08);
        border-color: hsl(var(--danger) / .35);
        color: hsl(var(--danger-text));
        font-weight: 600;
      }
      .mt-row .mt-pill-pipeline {
        background: hsl(var(--warning) / .15); color: hsl(var(--warning-text));
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
        display: inline-block; padding: 1px 6px; border-radius: 4px; font-size: 11px;
        font-weight: 700; letter-spacing: .04em; text-transform: uppercase;
        background: hsl(var(--warning) / .15); color: hsl(var(--warning-text));
        margin-left: 6px; vertical-align: middle;
      }
      .mt-row .mt-pill-on { background: hsl(var(--success) / .15); color: hsl(var(--success-text)); }
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
        display: inline-flex; flex-direction: column; align-items: flex-start;
        padding: 3px 8px; margin: 0 4px 4px 0;
        font-size: 11px; font-family: ui-monospace, "SF Mono", Consolas, monospace;
        background: hsl(var(--accent) / .1); color: hsl(var(--accent));
        border-radius: 4px; cursor: pointer; border: 1px dashed hsl(var(--accent) / .3);
        transition: background 120ms;
      }
      .mt-placeholder-chip:hover { background: hsl(var(--accent) / .2); }
      /* Libellé humain sous chaque variable {{x}} */
      .mt-placeholder-chip .mt-ph-hint {
        font-size: 11px; font-family: inherit; font-weight: 500;
        color: hsl(var(--text-muted)); line-height: 1.2;
        font-family: 'Inter', -apple-system, sans-serif;
      }
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

      /* === Boutons « catégorie de prospect » dans l'éditeur === */
      .mt-audsel-btn {
        padding: 6px 12px; border-radius: 8px;
        font-size: 12px; font-weight: 600;
        background: hsl(var(--bg)); color: hsl(var(--text-muted));
        border: 1px solid hsl(var(--border));
        cursor: pointer; transition: background 120ms, color 120ms, border-color 120ms;
      }
      .mt-audsel-btn:hover { color: hsl(var(--text)); border-color: hsl(var(--accent) / .5); }
      .mt-audsel-btn.is-active {
        background: hsl(var(--accent-strong)); color: hsl(var(--on-accent));
        border-color: hsl(var(--accent-strong));
      }

      /* === Pills audience dans la liste === */
      .mt-pill-aud-creator {
        background: hsl(var(--info) / .15);
        color: hsl(var(--info-text));
      }
      .mt-pill-aud-pro {
        background: hsl(var(--warning) / .18);
        color: hsl(var(--warning-text));
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
      .mt-chip-auto   { background: hsl(var(--success) / .12); color: hsl(var(--success-text)); border-color: hsl(var(--success) / .3); }
      .mt-chip-target { font-family: ui-monospace, "SF Mono", Consolas, monospace; font-size: 11px; }

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
        display: block; font-size: 11px; letter-spacing: .12em;
        text-transform: uppercase; color: hsl(var(--text-muted)); margin-top: 2px;
      }
      /* Petit bouton « + » par produit (création directe sous ce produit) */
      .mt-prod-add {
        flex-shrink: 0;
        width: 22px; height: 22px; line-height: 1;
        border-radius: 6px; border: 1px solid hsl(var(--border));
        background: hsl(var(--bg)); color: hsl(var(--text-muted));
        font-size: 14px; font-weight: 700; cursor: pointer;
        transition: color 120ms, border-color 120ms;
      }
      .mt-prod-add:hover { color: hsl(var(--accent)); border-color: hsl(var(--accent) / .5); }
    `;
    document.head.appendChild(s);
  },

  async refresh() {
    this._state.busy = true;
    const list = document.getElementById('mt-list');
    if (list) list.innerHTML = '<div class="p-4 text-[12px] text-text-muted">Chargement…</div>';

    // Charge en parallèle : templates + catalogue produits (pour le mode
    // prospection) + adresses d'envoi (liste de choix du câblage
    // modèle→adresse).
    const [res, prods, accs] = await Promise.all([
      this._api('list'),
      this._loadCatalogueProducts(),
      this._loadMailAccounts(),
    ]);
    this._state.catalogueProducts = prods || [];
    this._state.mailAccounts = accs || [];

    if (!res || !res.ok) {
      // Échec de chargement : bandeau d'erreur VISIBLE + état d'erreur dans
      // la liste — surtout pas la liste de secours affichée comme si tout
      // allait bien (on risquerait d'éditer à l'aveugle).
      console.warn('mail_templates.list a échoué :', res && res.error);
      this._state.loadError = true;
      this._state.products = {};
      this._showLoadError();
      this._state.busy = false;
      return;
    }

    // Chargement OK : on remet le bandeau en mode aide (masqué).
    if (this._state.loadError) {
      this._state.loadError = false;
      this._setBannerHelp();
      const banner = document.getElementById('mt-banner');
      if (banner) banner.style.display = 'none';
    }
    this._state.products = res.products || {};

    this._state.catalog = this._buildCatalog();
    this._state.catalogProspection = this._buildCatalogProspection();
    this._populateSenderFilter();
    this._populateProductFilter();
    this._renderList();

    // Saisie reportée (l'utilisateur a refusé d'abandonner ses modifs) :
    // on ré-affiche sa copie de travail telle quelle, sans repasser par la base.
    if (this._state.keepEditing && this._state.editing) {
      this._state.keepEditing = false;
      this._state.selected = {
        product: this._state.editing.product,
        key: this._state.editing.key,
      };
      this._renderList();
      this._renderEditor({});
      this._state.busy = false;
      return;
    }
    this._state.keepEditing = false;

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

  // État d'erreur de chargement : bandeau + liste + éditeur neutralisés.
  _showLoadError() {
    this._showBannerError('Impossible de charger les modèles. Vérifie ta connexion puis réessaie.');
    const list = document.getElementById('mt-list');
    if (list) {
      list.innerHTML = `
        <div class="p-4 text-[12px]">
          <p class="text-danger font-semibold mb-2">⚠ Impossible de charger les modèles.</p>
          <p class="text-text-muted mb-3">Vérifie ta connexion, puis réessaie.</p>
          <button data-mt-retry class="btn btn-secondary text-[12px]">Réessayer</button>
        </div>`;
      const retry = list.querySelector('[data-mt-retry]');
      if (retry) retry.onclick = () => this.refresh();
    }
    const ed = document.getElementById('mt-editor');
    if (ed) {
      if (this._state.keepEditing && this._state.editing) {
        // Une saisie était en cours et l'utilisateur a refusé de l'abandonner :
        // on la ré-affiche telle quelle (l'enregistrement reste possible).
        this._state.keepEditing = false;
        this._renderEditor({});
      } else {
        ed.innerHTML = `<div class="p-8 text-center text-text-muted text-sm">
          Les modèles n’ont pas pu être chargés — rien à éditer pour l’instant.
        </div>`;
      }
    }
    this._updateCount(0, 0, this._state.categoryMode === 'prospection' ? 'mt-count-prosp' : 'mt-count');
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

  // Adresses d’envoi configurées (compte principal + secondaires). Sert de
  // liste de choix au champ « Envoyé depuis » des modèles de prospection.
  // En cas d’échec : liste vide, le champ reste saisissable à la main.
  async _loadMailAccounts() {
    try {
      if (!App.api || typeof App.api.mail_accounts_list !== 'function') return [];
      const res = await App.api.mail_accounts_list({});
      return (res && res.ok && Array.isArray(res.accounts)) ? res.accounts : [];
    } catch (e) {
      console.warn('mail_templates: chargement des adresses d’envoi raté', e);
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
    // En cas d'échec de chargement, la liste reste en état d'erreur
    // (pas question d'afficher des données de secours comme si tout allait bien).
    if (this._state.loadError) {
      this._showLoadError();
      return;
    }
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
        const label = t._label || t.label || this._humanKey(t.key);
        let pill = '';
        const isPipeline = t._runtime === 'pipeline';
        if (t._source === 'fallback') {
          pill = isPipeline
            ? '<span class="mt-pill mt-pill-pipeline" title="Ce mail part avec sa version par défaut — ta version sera branchée dans une prochaine mise à jour">Par défaut</span>'
            : '<span class="mt-pill" title="Pas encore personnalisé — la version par défaut est utilisée">Par défaut</span>';
        } else if (t.enabled === false) {
          pill = '<span class="mt-pill mt-pill-off" title="Modèle désactivé — la version par défaut est utilisée">Désactivé</span>';
        } else {
          pill = isPipeline
            ? '<span class="mt-pill mt-pill-pipeline" title="Ta version est enregistrée, mais pas encore branchée — la version par défaut part encore">Édité · en attente</span>'
            : '<span class="mt-pill mt-pill-on" title="Ta version est utilisée pour les envois">Édité</span>';
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
    this._bindListRows(list);
    this._updateCount(visibleCount, totalCount, 'mt-count');
  },

  // Clic sur une ligne de la liste : protégé par la garde « modifications
  // non enregistrées ». Re-cliquer la ligne déjà ouverte ne recharge rien
  // (ça écraserait la saisie en cours pour rien).
  _bindListRows(list) {
    list.querySelectorAll('[data-mt-open]').forEach(btn => {
      btn.onclick = async () => {
        const [p, k] = btn.dataset.mtOpen.split('::');
        const sel = this._state.selected;
        if (sel && sel.product === p && sel.key === k && this._state.editing) return;
        if (!(await this._confirmDiscard())) return;
        this.openTemplate(p, k);
      };
    });
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
      const prodLabel = info.label || pid;
      html += `
        <div class="mt-prod-h">
          <div class="flex items-center justify-between gap-2">
            <span class="mt-prod-name">${this._esc(prodLabel)}</span>
            <button class="mt-prod-add" data-mt-newprosp="${this._esc(pid)}"
                    title="Créer un modèle pour ${this._esc(prodLabel)}"
                    aria-label="Créer un modèle pour ${this._esc(prodLabel)}">+</button>
          </div>
          <span class="mt-prod-count">${filteredTpls.length} modèle${filteredTpls.length > 1 ? 's' : ''}</span>
        </div>`;
      if (filteredTpls.length === 0) {
        html += `<div class="px-3 py-3 text-[12px] text-text-muted italic">
          Aucun mail de prospection. Clique sur le <strong>+</strong> ci-dessus pour en créer un.
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
          ? '<span class="mt-pill mt-pill-off" title="Modèle désactivé — l’Auto-pilote ne l’utilise plus">Désactivé</span>'
          : '<span class="mt-pill mt-pill-on" title="Utilisé par l’Auto-pilote">Actif</span>';
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
    this._bindListRows(list);
    // Boutons « + » par produit : créent un modèle directement sous CE produit.
    list.querySelectorAll('[data-mt-newprosp]').forEach(btn => {
      btn.onclick = async (ev) => {
        ev.stopPropagation();
        if (!(await this._confirmDiscard())) return;
        this.openNewProspection(btn.dataset.mtNewprosp);
      };
    });
    this._updateCount(visibleCount, totalCount, 'mt-count-prosp');
  },

  // ---------- Open / edit ----------
  async openTemplate(product, key) {
    this._state.selected = { product, key };
    this._state.editing = null;
    this._state.pristine = null;
    this._renderList();
    this._renderEditor({ loading: true });

    // Jeton anti-course : si l'utilisateur clique vite sur plusieurs modèles,
    // seule la DERNIÈRE réponse a le droit de remplir l'éditeur.
    const seq = (this._state.openSeq = (this._state.openSeq || 0) + 1);

    // Charge depuis la base
    const res = await this._api('get', { product, key });
    if (seq !== this._state.openSeq) return; // une ouverture plus récente est partie

    const known = this.KNOWN.find(k => k.product === product && k.key === key) || {};
    // « Pas en base » (réponse propre du serveur) = vrai modèle à créer.
    // Tout le reste (réseau coupé, erreur serveur…) = ERREUR : on bloque
    // l'édition, sinon « Enregistrer » écraserait le vrai modèle avec du vide.
    const notInDb = !!(res && (
      (res.ok && !res.template) ||
      (!res.ok && /introuvable/i.test(String(res.error || '')))
    ));
    let tpl;
    if (res && res.ok && res.template) {
      tpl = {
        ...res.template,
        category: res.template.category || 'transactionnel',
        _runtime: known.runtime || 'netlify',
        _label: res.template.label || known.label,
        // Modèle par défaut pré-rempli (produit dont le texte vit en Python,
        // ex. Pixel Pros) : on le marque comme « fallback » pour que la
        // pastille dise « Par défaut » tant que Jordan n'a rien enregistré.
        _source: res.template._is_default ? 'fallback' : undefined,
      };
    } else if (notInDb) {
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
    } else {
      console.warn('mail_templates.get a échoué :', res && res.error);
      this._renderEditorError(product, key);
      return;
    }
    this._state.editing = JSON.parse(JSON.stringify(tpl));
    this._state.pristine = this._snapshotOf(this._state.editing);
    this._renderEditor({});
  },

  // Échec de chargement d'UN modèle : on bloque l'édition (pas de bascule
  // silencieuse sur un modèle vide) et on propose de réessayer.
  _renderEditorError(product, key) {
    const e = document.getElementById('mt-editor');
    if (!e) return;
    e.innerHTML = `
      <div class="p-8 text-center text-sm">
        <p class="font-semibold mb-1">Impossible de charger ce modèle.</p>
        <p class="text-text-muted text-[12px] mb-4">
          L’édition est bloquée pour ne pas écraser la version enregistrée.
          Vérifie ta connexion, puis réessaie.
        </p>
        <button id="mt-retry-get" class="btn btn-secondary">Réessayer</button>
      </div>`;
    const b = document.getElementById('mt-retry-get');
    if (b) b.onclick = () => this.openTemplate(product, key);
  },

  // Ouvre l'éditeur sur un nouveau template de prospection (vide).
  // `forcedPid` (bouton « + » d'un groupe produit) gagne ; sinon le produit
  // du filtre courant ; sinon le premier produit du catalogue.
  openNewProspection(forcedPid) {
    const cat = this._state.catalogProspection || {};
    let pid = forcedPid || this._state.productFilter || '';
    if (!pid) {
      const firstId = Object.keys(cat)[0];
      pid = firstId || 'pixel-pros';
    }
    const prodInfo = cat[pid] || { id: pid, label: pid };
    // Génère une clé interne unique : prosp_<timestamp_court>
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
      _runtime: 'autopilot',
      _label: `Nouveau modèle — ${prodInfo.label || pid}`,
      _productLabel: prodInfo.label || pid,
    };
    this._state.selected = { product: pid, key };
    this._state.editing = tpl;
    this._state.pristine = this._snapshotOf(tpl);
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

    // Adresses d’envoi configurées → liste de choix pour le câblage
    // modèle→adresse (champ « Envoyé depuis » des modèles de prospection).
    const senderChoices = (this._state.mailAccounts || [])
      .filter(a => a && a.from_email)
      .map(a => `<option value="${this._esc(a.from_email)}">${this._esc(a.label || a.from_email)}</option>`)
      .join('');

    // En prospection on affiche le produit du catalogue plutôt que l'adresse mail
    const cat = this._state.catalogProspection || {};
    const productLabel = (cat[t.product] && cat[t.product].label)
      || t._productLabel
      || t.product;

    // Petites pastilles contextuelles : type + cible. Concises, en haut.
    const typeChip = isProspection
      ? `<span class="mt-chip mt-chip-prosp" title="Ce modèle est envoyé tel quel par l’Auto-pilote — il remplit seulement les variables {{…}}, il ne réécrit rien">🤖 Utilisé par l’Auto-pilote — envoyé tel quel</span>`
      : `<span class="mt-chip mt-chip-auto" title="Mail automatique après achat — envoyé tout seul par tes sites au bon moment">🤖 Auto</span>`;
    const targetChip = isProspection
      ? `<span class="mt-chip mt-chip-target">${this._esc(productLabel)}</span>`
      : `<span class="mt-chip mt-chip-target" title="${this._esc(senderLabel || '')}">${this._esc(senderAddr)}</span>`;

    // Bandeau d'avertissement : un seul, le plus pertinent
    let warnHtml = '';
    if (!isProspection && isPipeline) {
      warnHtml = `<div class="mt-warn">⚠ Tes modifications sont bien enregistrées, mais ce mail part encore avec la version par défaut. Pas encore branché : ta version sera utilisée dans une prochaine mise à jour.</div>`;
    } else if (!isProspection && isNew) {
      warnHtml = `<div class="mt-warn">Modèle pas encore édité — la version par défaut est utilisée. Modifie et enregistre pour reprendre la main.</div>`;
    }

    // Nouveau modèle de prospection : le produit de rattachement est affiché
    // en clair sous le titre (pas seulement dans le bloc replié).
    const newProductLine = (isNew && isProspection)
      ? `<p class="text-[12px] mt-1">Sera rangé sous le produit&nbsp;: <strong>${this._esc(productLabel)}</strong> <span class="text-text-muted">(modifiable dans ⚙ Réglages avancés)</span></p>`
      : '';

    // Nouveau modèle ou corps vide → on ouvre sur l'édition (l'aperçu serait
    // une page blanche) ; sinon sur l'aperçu pour voir le mail final.
    const startPane = (isNew || !String(t.body_html || '').trim()) ? 'edit' : 'preview';

    e.innerHTML = `
      <!-- En-tête minimal : titre + 2 chips. La description et la clé tech sont dépliables. -->
      <div class="mb-4 pb-3 border-b border-border">
        <div class="flex items-center gap-2 mb-2 flex-wrap">
          ${typeChip}
          ${targetChip}
        </div>
        <h2 class="text-lg font-bold leading-tight">${this._esc(headerLabel)}</h2>
        ${newProductLine}
        ${t.description ? `<p class="text-[12.5px] text-text-muted mt-1 leading-snug">${this._esc(t.description)}</p>` : ''}
        ${warnHtml}
      </div>

      <!-- Tabs Édition / Aperçu — aperçu par défaut quand le mail a déjà un
           corps ; édition directe pour un modèle neuf ou vide. -->
      <div class="mt-tabs" role="tablist" aria-label="Édition ou aperçu du modèle">
        <button class="mt-tab ${startPane === 'edit' ? 'is-active' : ''}" data-mt-pane="edit" role="tab" aria-selected="${startPane === 'edit'}">✎ Édition</button>
        <button class="mt-tab ${startPane === 'preview' ? 'is-active' : ''}" data-mt-pane="preview" role="tab" aria-selected="${startPane === 'preview'}">👁 Aperçu</button>
      </div>

      <div id="mt-pane-edit" style="display:${startPane === 'edit' ? '' : 'none'};">
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
            <span class="text-[11px] font-bold tracking-wider uppercase text-text-muted shrink-0">Insérer :</span>
            <div class="mt-placeholders-chips">${placeholders.map(p => this._placeholderChip(p)).join('')}</div>
          </div>
        ` : ''}

        <!-- CORPS HTML : dominant, le cœur de la page.
             Le bouton « + Produit du Catalogue » n'apparaît que si l'écran
             Catalogue est chargé (sinon il serait mort). -->
        <div class="mt-field">
          <div class="flex items-center justify-between gap-2 flex-wrap mb-1">
            <label style="margin:0; padding:0;">Corps du mail (HTML)</label>
            ${(typeof Catalogue !== 'undefined' && typeof Catalogue.pickProduct === 'function') ? `
            <button id="mt-insert-product" type="button"
                    class="px-2.5 py-1 rounded-lg text-[11px] font-semibold border border-border text-text-muted hover:border-accent hover:text-accent transition-colors"
                    title="Insérer un produit du Catalogue Triskell">
              + Produit du Catalogue
            </button>` : ''}
          </div>
          <textarea id="mt-body-html" class="mt-textarea-hero" spellcheck="false" placeholder="<p>Bonjour {{first_name}},</p>…">${this._esc(t.body_html || '')}</textarea>
        </div>

        <!-- Bloc replié : tout ce qui est secondaire (expéditeur, fallback texte, actif…) -->
        <details class="mt-advanced">
          <summary>⚙ Réglages avancés <span class="text-text-muted text-[11px]">— expéditeur, texte brut, activation…</span></summary>
          <div class="mt-advanced-body">
            ${isProspection ? `
              <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
                <div class="mt-field">
                  <label for="mt-label">Titre du modèle (interne)</label>
                  <input id="mt-label" value="${this._esc(t.label || '')}" placeholder="Mail 1 — commission classique">
                </div>
                <div class="mt-field">
                  <label for="mt-product-select">Produit</label>
                  <select id="mt-product-select">${this._renderProductOptions(t._pendingProduct || t.product)}</select>
                </div>
              </div>
            ` : ''}

            ${isProspection ? `
              <div class="mt-field">
                <label for="mt-from-address">Envoyé depuis (adresse d’expéditeur)</label>
                <input id="mt-from-address" list="mt-sender-choices" value="${this._esc(t.from_address || '')}" placeholder="vide = n’importe quelle adresse du pool de l’Auto-pilote">
                <datalist id="mt-sender-choices">${senderChoices}</datalist>
                <div class="text-[11px] text-text-muted pt-1 leading-snug">
                  📮 L’Auto-pilote enverra ce modèle <strong>uniquement depuis cette adresse</strong> — si elle est indisponible
                  (absente de ses adresses d’envoi, ou plafond du jour atteint), le mail attend en brouillon au lieu de partir
                  d’une autre adresse. Le nom d’expéditeur affiché est celui du compte d’envoi.
                  Vide&nbsp;= l’Auto-pilote choisit librement parmi ses adresses.
                </div>
              </div>
            ` : `
            <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div class="mt-field">
                <label for="mt-from-name">Expéditeur (nom)</label>
                <input id="mt-from-name" value="${this._esc(t.from_name || '')}" placeholder="Lagriffe Studio">
              </div>
              <div class="mt-field">
                <label for="mt-from-address">Expéditeur (adresse)</label>
                <input id="mt-from-address" value="${this._esc(t.from_address || '')}" placeholder="noreply@triskell-studio.fr">
              </div>
            </div>
            `}

            <div class="mt-field">
              <label for="mt-body-text">Version texte (pour les boîtes mail qui n’affichent pas le HTML)</label>
              <textarea id="mt-body-text" spellcheck="false" style="min-height: 90px;" placeholder="Version texte brut, optionnelle.">${this._esc(t.body_text || '')}</textarea>
            </div>

            <label class="mt-field-inline">
              <input type="checkbox" id="mt-enabled" ${t.enabled !== false ? 'checked' : ''}>
              <span>Modèle actif <span class="text-text-muted text-[12px]">${isProspection
                ? '— décoché : l’Auto-pilote ne l’utilisera plus.'
                : '— décoché : la version par défaut est utilisée à la place.'}</span></span>
            </label>

            <div class="text-[11px] text-text-muted pt-2 border-t border-border/50">
              Référence interne&nbsp;: <code>${this._esc(t.product)}::${this._esc(t.key)}</code>
            </div>
          </div>
        </details>

        <!-- Toolbar : enregistrer + dupliquer + supprimer + date de modif -->
        <div class="mt-toolbar">
          <div class="grow text-[11px] text-text-muted">
            ${t.updated_at ? `Dernière modif&nbsp;: ${this._formatDate(t.updated_at)}${t.updated_by ? ` par ${this._esc(t.updated_by)}` : ''}` : ''}
          </div>
          ${!isNew ? `<button id="mt-duplicate" class="btn btn-secondary" title="Créer une copie de ce modèle, à enregistrer ensuite">📑 Dupliquer</button>` : ''}
          ${!isNew ? `<button id="mt-delete" class="btn btn-secondary text-danger">Supprimer</button>` : ''}
          <button id="mt-save" class="btn btn-primary">💾 Enregistrer</button>
        </div>
      </div>

      <div id="mt-pane-preview" style="display:${startPane === 'preview' ? '' : 'none'};">
        <iframe id="mt-preview-iframe" class="mt-preview-frame" sandbox="" title="Aperçu du mail avec des valeurs d’exemple"></iframe>
        <p class="text-[11px] text-text-muted mt-3">Aperçu avec des valeurs d’exemple à la place des variables <code>{{…}}</code>. Fond blanc = fond réel du mail.</p>
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
        this._syncEditingFromDom();
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
    const dupBtn = document.getElementById('mt-duplicate');
    if (dupBtn) dupBtn.onclick = () => this.duplicateCurrent();
    // Synchro en continu écran → copie de travail : indispensable pour la
    // garde « modifications non enregistrées », car le routeur vide le DOM
    // AVANT de re-rendre la vue (au moment du re-render, les champs ont
    // déjà disparu — seule la copie de travail fait foi).
    const liveSync = () => this._syncEditingFromDom();
    ['mt-subject', 'mt-body-html', 'mt-body-text', 'mt-from-name', 'mt-from-address', 'mt-label']
      .forEach(id => {
        const el = document.getElementById(id);
        if (el) el.addEventListener('input', liveSync);
      });
    const enabledEl = document.getElementById('mt-enabled');
    if (enabledEl) enabledEl.addEventListener('change', liveSync);
    const prodSelEl = document.getElementById('mt-product-select');
    if (prodSelEl) prodSelEl.addEventListener('change', liveSync);
    // Si on ouvre sur l'aperçu, on remplit l'iframe tout de suite
    // (sinon elle s'affiche blanche tant qu'on n'a pas re-cliqué).
    if (startPane === 'preview') this._renderPreview();
  },

  _switchPane(name) {
    document.querySelectorAll('[data-mt-pane]').forEach(b => {
      const active = b.dataset.mtPane === name;
      b.classList.toggle('is-active', active);
      b.setAttribute('aria-selected', String(active));
    });
    document.getElementById('mt-pane-edit').style.display    = (name === 'edit')    ? '' : 'none';
    document.getElementById('mt-pane-preview').style.display = (name === 'preview') ? '' : 'none';
    if (name === 'preview') this._renderPreview();
  },

  // Applique le style "actif" ou "inactif" à un bouton du sélecteur catégorie
  // de prospect. La valeur courante est dans wrap.dataset.mtAudienceCurrent.
  // Le style passe par les classes CSS .mt-audsel-btn (tokens du thème),
  // plus de couleur en dur.
  _styleAudBtn(btn) {
    const wrap = btn.closest('[data-mt-audience-current]');
    if (!wrap) return;
    const active = btn.dataset.mtAudsel === wrap.dataset.mtAudienceCurrent;
    btn.classList.toggle('is-active', active);
    btn.setAttribute('aria-pressed', String(active));
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
    // L'insertion ne déclenche pas d'événement input : on synchronise à la main.
    this._syncEditingFromDom();
  },

  // ---------- Save / delete / duplicate ----------
  // Garde-fou variables : accolades dépareillées ou variable inconnue = le
  // destinataire recevrait le code brut ({{prenom}} non rempli) dans son
  // mail. Retourne la liste des problèmes ; save() avertit sans bloquer.
  _placeholderProblems(fields) {
    const text = [fields.subject || '', fields.body_html || '',
                  fields.body_text || ''].join('\n');
    const problems = [];
    const opens = (text.match(/\{\{/g) || []).length;
    const closes = (text.match(/\}\}/g) || []).length;
    if (opens !== closes) {
      problems.push(`accolades dépareillées : ${opens} ouvertures «{{» pour ${closes} fermetures «}}»`);
    }
    const known = (fields.placeholders || []).map(p => String(p).toLowerCase());
    if (known.length) {
      const used = new Set();
      const reDouble = /\{\{\s*([a-z0-9_]+)\s*\}\}/gi;
      let m;
      while ((m = reDouble.exec(text))) used.add(m[1].toLowerCase());
      // Variables simples {x} (après-achat) : on retire d'abord les {{x}}.
      const single = text.replace(/\{\{[^}]*\}\}/g, '');
      const reSingle = /\{([a-z0-9_]+)\}/gi;
      while ((m = reSingle.exec(single))) used.add(m[1].toLowerCase());
      used.forEach(u => {
        if (!known.includes(u)) {
          problems.push(`« {${u}} » n’est pas une variable connue de ce modèle — elle partirait telle quelle, en code brut`);
        }
      });
    }
    return problems;
  },

  async save() {
    const t = this._state.editing;
    if (!t) return;
    const isProspection = (t.category === 'prospection');
    const isPipeline = t._runtime === 'pipeline';

    // En prospection le champ « nom d’expéditeur » n’est pas affiché (le
    // nom vient du compte d’envoi) : on préserve la valeur existante.
    const fromNameEl = document.getElementById('mt-from-name');
    const fields = {
      from_name:    fromNameEl ? fromNameEl.value.trim() : (t.from_name || ''),
      from_address: document.getElementById('mt-from-address').value.trim(),
      subject:      document.getElementById('mt-subject').value,
      body_html:    document.getElementById('mt-body-html').value,
      body_text:    document.getElementById('mt-body-text').value,
      enabled:      document.getElementById('mt-enabled').checked,
      placeholders: Array.isArray(t.placeholders) ? t.placeholders : [],
      description:  t.description || '',
      category:     t.category || 'transactionnel',
    };
    // Les copies de modèles transactionnels gardent leur titre « (copie) ».
    if (!isProspection && t.label) fields.label = t.label;
    if (isProspection) {
      const labelEl = document.getElementById('mt-label');
      fields.label = labelEl ? labelEl.value.trim() : (t.label || '');
      if (!fields.label) {
        Toast.error('Le titre du modèle est obligatoire (ex. « Mail 1 — commission classique »).');
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
      Toast.error('Le sujet du mail est obligatoire.');
      return;
    }
    if (!fields.from_address) {
      // Prospection : vide = pas d’exigence, l’Auto-pilote choisit dans
      // son pool d’adresses. Transactionnel : l’adresse reste obligatoire.
      if (!isProspection) {
        Toast.error('L’adresse d’expéditeur est obligatoire.');
        return;
      }
    } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(fields.from_address)) {
      // Contrôle simple du format d'adresse (un @ et un point après).
      Toast.error('L’adresse d’expéditeur n’a pas un format valide (ex. contact@triskell-studio.fr).');
      return;
    }
    // Un modèle de prospection ACTIF au corps vide partirait… vide.
    if (isProspection && fields.enabled && !fields.body_html.trim() && !fields.body_text.trim()) {
      Toast.error('Le corps du mail est vide — écris le contenu, ou décoche « Modèle actif » le temps de le finir.');
      return;
    }

    // Garde-fou variables (audit débutant) : avertit, ne bloque pas.
    const phProblems = this._placeholderProblems(fields);
    if (phProblems.length) {
      const okAnyway = await Dialog.confirm(
        'Vérifie tes variables avant d’enregistrer :\n\n— '
        + phProblems.join('\n— ')
        + '\n\nEn l’état, le destinataire risque de voir le code brut dans son mail.',
        { title: 'Variables à vérifier', danger: true,
          okLabel: 'Enregistrer quand même', cancelLabel: 'Corriger' });
      if (!okAnyway) return;
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

    // Si le produit a changé : on enregistre D'ABORD sous le nouveau couple
    // (product, key), et on ne supprime l'ancien QU'APRÈS un succès confirmé.
    // (Dans l'autre ordre, un échec d'enregistrement détruisait le modèle.)
    const movingProduct = isProspection && targetProduct !== t.product && !t._isNew;

    const res = await this._api('save', { product: targetProduct, key: t.key, fields });
    if (btn) { btn.disabled = false; btn.textContent = '💾 Enregistrer'; }
    if (!res || !res.ok) {
      console.warn('mail_templates.save a échoué :', res && res.error);
      Toast.friendlyError((res && res.error) || null, 'Échec de l’enregistrement — rien n’a été perdu, réessaie dans un instant.');
      return;
    }
    if (movingProduct) {
      const del = await this._api('delete', { product: t.product, key: t.key });
      if (!del || !del.ok) {
        console.warn('mail_templates.delete (déplacement) a échoué :', del && del.error);
        Toast.warn('Modèle enregistré sous le nouveau produit, mais l’ancienne copie n’a pas pu être retirée — supprime-la si tu la vois encore dans la liste.');
      }
    }
    // Met à jour la sélection (utile si on a changé de produit ou créé un nouveau)
    this._state.selected = { product: targetProduct, key: t.key };
    // Toast adapté à ce que le modèle pilote vraiment (pas de promesse
    // « effet immédiat » quand l'éditeur dit l'inverse).
    let okMsg;
    if (isProspection) {
      okMsg = 'Modèle enregistré — l’Auto-pilote l’utilisera à son prochain passage.';
    } else if (isPipeline) {
      okMsg = 'Modèle enregistré. Pas encore branché : la version par défaut reste utilisée pour l’instant.';
    } else {
      okMsg = 'Modèle enregistré — pris en compte pour les prochains envois.';
    }
    Toast.success(okMsg);
    await this.refresh();
  },

  async deleteCurrent() {
    const t = this._state.editing;
    if (!t) return;
    const msg = (t.category === 'prospection')
      ? 'Supprimer ce modèle ? Il disparaîtra pour l’Auto-pilote.'
      : 'Supprimer ce modèle ? Le mail repartira sur sa version par défaut.';
    const ok = await Dialog.confirm(msg, {
      title: 'Supprimer le modèle',
      okLabel: 'Supprimer',
      cancelLabel: 'Annuler',
      danger: true,
    });
    if (!ok) return;
    const btn = document.getElementById('mt-delete');
    if (btn) btn.disabled = true;
    const res = await this._api('delete', { product: t.product, key: t.key });
    if (!res || !res.ok) {
      if (btn) btn.disabled = false;
      console.warn('mail_templates.delete a échoué :', res && res.error);
      Toast.friendlyError((res && res.error) || null, 'Échec de la suppression — réessaie dans un instant.');
      return;
    }
    Toast.success('Modèle supprimé.');
    this._state.selected = null;
    this._state.editing = null;
    this._state.pristine = null;
    await this.refresh();
  },

  // Copie le modèle affiché (avec les modifs en cours d'écran) sous une
  // nouvelle clé « (copie) », et ouvre la copie en édition. Rien n'est
  // enregistré tant qu'on ne clique pas Enregistrer.
  duplicateCurrent() {
    const t = this._state.editing;
    if (!t) return;
    const f = this._collectDomFields() || {};
    const copy = JSON.parse(JSON.stringify(t));
    if (f.subject !== undefined) copy.subject = f.subject;
    if (f.body_html !== undefined) copy.body_html = f.body_html;
    if (f.body_text !== undefined) copy.body_text = f.body_text;
    if (f.from_name !== undefined) copy.from_name = f.from_name;
    if (f.from_address !== undefined) copy.from_address = f.from_address;
    if (f.enabled !== undefined) copy.enabled = f.enabled;
    if (f.label !== undefined) copy.label = f.label;
    if (f.audience !== undefined) copy.audience = f.audience;
    const ts = Date.now().toString(36);
    copy.key = (copy.category === 'prospection') ? `prosp_${ts}` : `${t.key}_copie_${ts}`;
    const baseLabel = copy.label || t._label || this._humanKey(t.key);
    copy.label = `${baseLabel} (copie)`;
    copy._label = copy.label;
    copy._isNew = true;
    delete copy.updated_at;
    delete copy.updated_by;
    delete copy._pendingProduct;
    this._state.selected = { product: copy.product, key: copy.key };
    this._state.editing = copy;
    // La copie n'existe pas encore en base : tant qu'elle n'est pas
    // enregistrée, on la traite comme « modifications non enregistrées ».
    this._state.pristine = this._snapshotOf({ product: copy.product, audience: copy.audience });
    this._renderList();
    this._renderEditor({});
    Toast.info('Copie créée — pense à l’enregistrer.');
  },

  // ---------- Garde « modifications non enregistrées » ----------
  // Photo de référence d'un modèle (prise au chargement) : sert à détecter
  // les modifications non enregistrées dans l'éditeur.
  _snapshotOf(t) {
    const x = t || {};
    return JSON.stringify({
      subject: x.subject || '',
      body_html: x.body_html || '',
      body_text: x.body_text || '',
      from_name: x.from_name || '',
      from_address: x.from_address || '',
      enabled: x.enabled !== false,
      label: x.label || '',
      audience: x.audience || 'creator',
      product: x._pendingProduct || x.product || '',
    });
  },

  // Relit les champs de l'éditeur dans le DOM (null si l'éditeur n'est pas affiché).
  _collectDomFields() {
    const get = (id) => document.getElementById(id);
    const subj = get('mt-subject');
    if (!subj) return null;
    const f = {
      subject: subj.value,
      body_html: (get('mt-body-html') || {}).value || '',
      body_text: (get('mt-body-text') || {}).value || '',
      from_name: (get('mt-from-name') || {}).value || '',
      from_address: (get('mt-from-address') || {}).value || '',
      enabled: get('mt-enabled') ? get('mt-enabled').checked : true,
    };
    const lbl = get('mt-label');
    if (lbl) f.label = lbl.value;
    const prodSel = get('mt-product-select');
    if (prodSel) f.product = prodSel.value;
    const audWrap = document.querySelector('[data-mt-audience-current]');
    if (audWrap) f.audience = audWrap.dataset.mtAudienceCurrent || 'creator';
    return f;
  },

  // Y a-t-il des modifications par rapport à la photo de référence ?
  // La copie de travail est synchronisée en continu pendant la frappe
  // (liveSync) : la détection marche donc même quand le routeur a déjà
  // vidé le DOM. Si l'éditeur est encore affiché, on resynchronise au cas où.
  _isDirty() {
    const t = this._state.editing;
    if (!t || !this._state.pristine) return false;
    this._syncEditingFromDom();
    return this._snapshotOf(t) !== this._state.pristine;
  },

  // true = on peut continuer (rien à perdre, ou abandon confirmé).
  async _confirmDiscard() {
    if (!this._isDirty()) return true;
    return await Dialog.confirm('Tu as des modifications non enregistrées — les abandonner ?', {
      title: 'Modifications non enregistrées',
      okLabel: 'Abandonner',
      cancelLabel: 'Continuer l’édition',
      danger: true,
    });
  },

  // Reporte la saisie de l'écran dans la copie de travail (pour survivre à
  // une reconstruction de la vue quand l'utilisateur refuse d'abandonner).
  _syncEditingFromDom() {
    const t = this._state.editing;
    const f = this._collectDomFields();
    if (!t || !f) return;
    t.subject = f.subject;
    t.body_html = f.body_html;
    t.body_text = f.body_text;
    t.from_name = f.from_name;
    t.from_address = f.from_address;
    t.enabled = f.enabled;
    if (f.label !== undefined) t.label = f.label;
    if (f.audience !== undefined) t.audience = f.audience;
    // Le produit choisi dans le select est gardé de côté : le vrai
    // déplacement ne se joue qu'à l'enregistrement. Revenir au produit
    // d'origine efface le « en attente ».
    if (f.product !== undefined) {
      if (f.product !== t.product) t._pendingProduct = f.product;
      else delete t._pendingProduct;
    }
  },

  // ---------- Utils ----------
  // Valeurs d'exemple pour l'aperçu : TOUTES les variables des modèles par
  // défaut doivent avoir une valeur, sinon l'aperçu affiche {{signature}} brut.
  _samplePlaceholders(t) {
    const samples = {
      first_name: 'Jordan',
      last_name: 'Bourillot',
      name: 'Jordan Bourillot',
      company_name: 'Atelier du Tertre',
      client_name: 'Atelier du Tertre',
      signature: 'Jordan — Triskell Studio',
      product_name: 'Pixel Pros',
      product_link: 'https://pixel-pros.fr',
      next_product_name: 'RankUs (suivi de visibilité Google)',
      next_product_link: 'https://rankus-studio.fr',
      customize_url: 'https://lagriffe-studio.fr/personnaliser?id=xxx',
      mockup_url:    'https://maquette.exemple.fr',
      site_url:      'https://votre-site.fr',
      final_site_url:'https://votre-site.fr',
      month:         'juin',
      year:          '2026',
      invoice_number:'F-2026-042',
      deliverables_list: 'Site vitrine + logo + fiche Google',
      soft_hook:     'une idée simple pour gagner des clients',
      title:         'Rapport prêt',
      body:          'Le rapport mensuel est disponible.',
      amount:        '49',
      currency:      'EUR',
      email:         'client@exemple.fr',
    };
    return samples;
  },

  // Libellés humains des variables {{x}} — affichés sous chaque puce et en
  // info-bulle, pour qu'on sache ce que chaque variable devient à l'envoi.
  PLACEHOLDER_HINTS: {
    first_name: 'le prénom du prospect',
    last_name: 'le nom de famille',
    name: 'le nom complet',
    company_name: 'le nom de l’entreprise',
    client_name: 'le nom du client',
    signature: 'ta signature',
    product_name: 'le nom du produit',
    product_link: 'le lien du produit',
    next_product_name: 'le produit complémentaire proposé',
    next_product_link: 'le lien du produit complémentaire',
    customize_url: 'le lien de personnalisation du site',
    mockup_url: 'le lien de la maquette',
    site_url: 'l’adresse du site',
    final_site_url: 'l’adresse du site final',
    month: 'le mois du rapport',
    year: 'l’année',
    invoice_number: 'le numéro de la facture',
    deliverables_list: 'la liste de ce qui est livré',
    soft_hook: 'la phrase d’accroche',
    title: 'le titre de l’alerte',
    body: 'le contenu de l’alerte',
    amount: 'le montant payé',
    currency: 'la devise (EUR…)',
    email: 'l’adresse mail du destinataire',
  },

  // Puce cliquable d'une variable : {{x}} + libellé humain en dessous.
  _placeholderChip(p) {
    const hint = this.PLACEHOLDER_HINTS[p] || '';
    const title = hint
      ? `{{${p}}} → ${hint}`
      : `Insère {{${p}}} dans le corps du mail`;
    return `<span class="mt-placeholder-chip" data-mt-insert="{{${this._esc(p)}}}" title="${this._esc(title)}">
      <code>{{${this._esc(p)}}}</code>${hint ? `<small class="mt-ph-hint">${this._esc(hint)}</small>` : ''}
    </span>`;
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
  // Noms français des clés connues (sinon « follow_up_30d » devenait
  // « Follow Up 30d », de l'anglais machiné).
  HUMAN_KEY_NAMES: {
    follow_up_7d:  'Relance après 7 jours',
    follow_up_30d: 'Relance après 30 jours',
    followup_3d:   'Suivi après 3 jours',
    followup_14d:  'Astuce après 14 jours',
    followup_30d:  'Avis après 30 jours',
    welcome: 'Mail de bienvenue',
    welcome_at_paid: 'Bienvenue après achat',
    cross_sell_30d: 'Proposition complémentaire après 30 jours',
    nps_90d: 'Sondage satisfaction après 90 jours',
    monthly_report: 'Rapport mensuel',
    invoice_email: 'Facture émise',
    morning_digest: 'Résumé du matin',
    brief_received: 'Brief reçu',
    preview_ready: 'Maquette prête',
    payment_confirmed: 'Paiement confirmé',
    site_delivered: 'Site livré',
    first_version_ready: 'Première version en ligne',
    interested: 'Réponse — intéressé',
    not_now: 'Réponse — pas maintenant',
    no: 'Réponse — refus',
    unsubscribe: 'Réponse — désinscription',
    unknown: 'Réponse — intention floue',
  },
  _humanKey(k) {
    const key = String(k || '');
    if (this.HUMAN_KEY_NAMES[key]) return this.HUMAN_KEY_NAMES[key];
    return key
      .replace(/_/g, ' ')
      .replace(/\bj(\d+)\b/g, 'J+$1')
      .replace(/\b(\d+)d\b/g, '$1 jours')
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
};

window.MailTemplates = MailTemplates;
