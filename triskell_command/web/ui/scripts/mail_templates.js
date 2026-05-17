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
    catalog: null,    // fusion base + catalogue connu, groupé par adresse mail
    senderFilter: '', // adresse mail filtrée ('' = toutes)
  },

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
  async render(container) {
    this._root = container;
    container.innerHTML = `
      <section class="animate-slide-up">
        <div class="mb-6 flex items-end justify-between">
          <div>
            <div class="hero-kicker mb-2">MODÈLES MAILS</div>
            <h1 class="hero-title mb-3" style="font-size: 36px;">Le ton de tes mails, en un clic.</h1>
            <p class="hero-subtitle">
              Chaque mail envoyé par tes sites (relances, bienvenues, finalisations) est éditable
              ici. Sujet, expéditeur, corps HTML — tu ajustes le ton sans toucher au code.
            </p>
          </div>
          <button id="mt-refresh" class="btn btn-secondary">Rafraîchir</button>
        </div>

        <div id="mt-banner" class="mb-4 text-[12px] text-text-muted"></div>

        <div class="flex items-center gap-3 mb-3 flex-wrap">
          <label class="text-xs text-text-muted">Filtrer par adresse&nbsp;:</label>
          <select id="mt-sender-filter" class="px-3 py-1.5 rounded-lg bg-bg border border-border text-sm">
            <option value="">— Toutes les adresses —</option>
          </select>
          <span id="mt-count" class="text-[11px] text-text-muted ml-auto"></span>
        </div>

        <div class="grid grid-cols-1 lg:grid-cols-[340px_1fr] gap-4">
          <aside id="mt-list" class="bg-card border border-border rounded-xl p-3 overflow-y-auto" style="max-height: calc(100vh - 260px);"></aside>
          <main  id="mt-editor" class="bg-card border border-border rounded-xl p-6 min-h-[500px]"></main>
        </div>
      </section>
    `;
    this._injectStyles();
    document.getElementById('mt-refresh').onclick = () => this.refresh();
    document.getElementById('mt-sender-filter').onchange = (e) => {
      this._state.senderFilter = e.target.value;
      this._renderList();
    };
    await this.refresh();
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
    `;
    document.head.appendChild(s);
  },

  async refresh() {
    this._state.busy = true;
    const list = document.getElementById('mt-list');
    list.innerHTML = '<div class="p-4 text-[12px] text-text-muted">Chargement…</div>';
    const banner = document.getElementById('mt-banner');

    const res = await this._api('list');
    if (!res || !res.ok) {
      banner.innerHTML = `<span class="text-danger">Impossible de charger les templates : ${res && res.error ? res.error : 'erreur inconnue'}.</span>`;
      this._state.products = {};
    } else {
      this._state.products = res.products || {};
      banner.innerHTML = `Templates synchronisés avec Supabase. Les mails non listés utilisent encore leur version codée en dur — clique sur un template ci-contre pour l'éditer.`;
    }

    this._state.catalog = this._buildCatalog();
    this._populateSenderFilter();
    this._renderList();

    // Auto-select : premier template, ou celui qui était déjà ouvert
    let target = this._state.selected;
    if (!target) {
      for (const info of Object.values(this._state.catalog)) {
        const t = (info.templates || [])[0];
        if (t) { target = { product: t.product, key: t.key }; break; }
      }
    }
    if (target) this.openTemplate(target.product, target.key);
    else this._renderEmptyEditor();

    this._state.busy = false;
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

    // 2) Liste complète des templates (base + connus pas encore en base)
    const all = [];
    const dbKeys = new Set();
    for (const [p, info] of Object.entries(this._state.products || {})) {
      for (const t of info.templates || []) {
        const id = `${p}::${t.key}`;
        dbKeys.add(id);
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

  _updateCount(visible, total) {
    const el = document.getElementById('mt-count');
    if (!el) return;
    el.textContent = visible === total
      ? `${total} modèle${total > 1 ? 's' : ''}`
      : `${visible} sur ${total} modèle${total > 1 ? 's' : ''}`;
  },

  _renderList() {
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
    this._updateCount(visibleCount, totalCount);
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
      tpl = { ...res.template, _runtime: known.runtime || 'netlify', _label: known.label };
    } else {
      // Pas en base : template "à créer". Pré-rempli depuis le catalogue connu.
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
        _isNew: true,
        _runtime: known.runtime || 'netlify',
        _label: known.label,
      };
    }
    this._state.editing = JSON.parse(JSON.stringify(tpl));
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
    const placeholders = Array.isArray(t.placeholders) ? t.placeholders : [];
    const senderAddr = (t.from_address || '').trim() || '(adresse non définie)';
    const senderLabel = this.SENDER_LABELS[senderAddr.toLowerCase()] || '';
    const headerLabel = t._label || this._humanKey(t.key);
    const isPipeline = t._runtime === 'pipeline';

    e.innerHTML = `
      <div class="mb-5 pb-4 border-b border-border">
        <div class="hero-kicker mb-1">${this._esc(senderAddr)}${senderLabel ? ` · ${this._esc(senderLabel)}` : ''}</div>
        <h2 class="text-xl font-bold">${this._esc(headerLabel)}</h2>
        <div class="text-[11px] text-text-muted mt-1">Clé technique&nbsp;: <code>${this._esc(t.product)}::${this._esc(t.key)}</code></div>
        ${t.description ? `<p class="text-sm text-text-muted mt-2 leading-relaxed">${this._esc(t.description)}</p>` : ''}
        ${isPipeline ? `
          <div class="mt-3 text-[12px] text-warning bg-warning/10 border border-warning/30 rounded px-3 py-2 leading-relaxed">
            <strong>⚠️ Modèle pipeline.</strong> Aujourd'hui le runner Python qui envoie ce mail
            (drip / post-vente / réponses IA / Phare / facturation) lit encore son texte
            <strong>codé en dur</strong>. Ton édition sera bien stockée en base mais elle
            ne s'appliquera <em>pas tant qu'on n'a pas branché le runner</em> sur la table
            <code>triskell_email_templates</code>. À faire en phase suivante.
          </div>` : ''}
        ${isNew && !isPipeline ? '<div class="mt-3 text-[12px] text-warning bg-warning/10 border border-warning/30 rounded px-3 py-2">Ce modèle n\'a jamais été édité. Aujourd\'hui la fonction Netlify utilise sa version <strong>par défaut codée en dur</strong>. Modifie le sujet/corps ci-dessous puis enregistre pour reprendre la main.</div>' : ''}
      </div>

      <div class="mt-tabs">
        <button class="mt-tab is-active" data-mt-pane="edit">Édition</button>
        <button class="mt-tab" data-mt-pane="preview">Aperçu</button>
      </div>

      <div id="mt-pane-edit">
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
          <label>Sujet du mail</label>
          <input id="mt-subject" value="${this._esc(t.subject || '')}" placeholder="Votre maquette Lagriffe Studio vous attend">
        </div>

        ${placeholders.length ? `
          <div class="mb-3">
            <div class="text-[11px] font-bold tracking-wider uppercase text-text-muted mb-2">Variables disponibles · clique pour insérer</div>
            <div>${placeholders.map(p => `<span class="mt-placeholder-chip" data-mt-insert="{{${this._esc(p)}}}">{{${this._esc(p)}}}</span>`).join('')}</div>
          </div>
        ` : ''}

        <div class="mt-field">
          <div class="flex items-center justify-between gap-2 flex-wrap mb-1">
            <label style="margin:0; padding:0;">Corps HTML</label>
            <button id="mt-insert-product" type="button"
                    class="px-2.5 py-1 rounded-lg text-[11px] font-semibold border border-border text-text-muted hover:border-accent hover:text-accent transition-colors"
                    title="Insérer un produit du Catalogue Triskell">
              + Produit du Catalogue
            </button>
          </div>
          <textarea id="mt-body-html" spellcheck="false" placeholder="<p>Bonjour {{first_name}},</p>…">${this._esc(t.body_html || '')}</textarea>
        </div>

        <div class="mt-field">
          <label>Corps texte (optionnel, fallback)</label>
          <textarea id="mt-body-text" spellcheck="false" style="min-height: 100px;" placeholder="Version texte brut, pour les clients mail qui ne lisent pas HTML.">${this._esc(t.body_text || '')}</textarea>
        </div>

        <div class="mt-field">
          <label style="display:flex; align-items:center; gap:8px; text-transform: none; letter-spacing: 0; font-size: 13px; color: hsl(var(--text)); font-weight: 500;">
            <input type="checkbox" id="mt-enabled" ${t.enabled !== false ? 'checked' : ''} style="width:auto;">
            <span>Modèle actif <span class="text-text-muted">— si décoché, la fonction Netlify retombe sur sa version codée en dur.</span></span>
          </label>
        </div>

        <div class="mt-toolbar">
          <div class="grow text-[11px] text-text-muted">
            ${t.updated_at ? `Dernière modif&nbsp;: ${this._formatDate(t.updated_at)}${t.updated_by ? ` par ${this._esc(t.updated_by)}` : ''}` : ''}
          </div>
          ${!isNew ? `<button id="mt-delete" class="btn btn-ghost text-danger">Supprimer</button>` : ''}
          <button id="mt-save" class="btn btn-primary">Enregistrer</button>
        </div>
      </div>

      <div id="mt-pane-preview" style="display:none;">
        <iframe id="mt-preview-iframe" class="mt-preview-frame" sandbox=""></iframe>
        <p class="text-[11px] text-text-muted mt-3">Les variables <code>{{…}}</code> sont remplacées par des valeurs d'exemple ci-dessus.</p>
      </div>
    `;

    // Binds
    e.querySelectorAll('[data-mt-pane]').forEach(b => b.onclick = () => this._switchPane(b.dataset.mtPane));
    e.querySelectorAll('[data-mt-insert]').forEach(c => c.onclick = () => this._insertPlaceholder(c.dataset.mtInsert));
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
  },

  _switchPane(name) {
    document.querySelectorAll('[data-mt-pane]').forEach(b => b.classList.toggle('is-active', b.dataset.mtPane === name));
    document.getElementById('mt-pane-edit').style.display    = (name === 'edit')    ? '' : 'none';
    document.getElementById('mt-pane-preview').style.display = (name === 'preview') ? '' : 'none';
    if (name === 'preview') this._renderPreview();
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
    const fields = {
      from_name:    document.getElementById('mt-from-name').value.trim(),
      from_address: document.getElementById('mt-from-address').value.trim(),
      subject:      document.getElementById('mt-subject').value,
      body_html:    document.getElementById('mt-body-html').value,
      body_text:    document.getElementById('mt-body-text').value,
      enabled:      document.getElementById('mt-enabled').checked,
      placeholders: Array.isArray(t.placeholders) ? t.placeholders : [],
      description:  t.description || '',
    };
    if (!fields.subject) {
      alert('Le sujet du mail est obligatoire.');
      return;
    }
    if (!fields.from_address) {
      alert('L\'adresse d\'expéditeur est obligatoire.');
      return;
    }
    const btn = document.getElementById('mt-save');
    if (btn) { btn.disabled = true; btn.textContent = 'Enregistrement…'; }
    const res = await this._api('save', { product: t.product, key: t.key, fields });
    if (btn) { btn.disabled = false; btn.textContent = 'Enregistrer'; }
    if (!res || !res.ok) {
      alert('Échec de l\'enregistrement : ' + (res && res.error || 'erreur inconnue'));
      return;
    }
    // Toast léger
    this._toast('Modèle enregistré. Effet immédiat (cache 60 s max côté Netlify).');
    // Recharge la liste pour mettre à jour les pills "Édité"
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
