/* Catalogue — vue Triskell Command
 *
 * Hub central des produits de l'écosystème Triskell.
 *
 * Vue principale :
 *   - Grille des produits groupés par section (sites · outils du quotidien ·
 *     atelier des pros · services).
 *   - Click sur une tuile → fiche détaillée (logo, pitch, description longue,
 *     fonctionnalités clés, personas, prix, liens).
 *
 * API publique (utilisée depuis les composeurs mail) :
 *   - Catalogue.list()                  → array des produits chargés
 *   - Catalogue.byId(id)                → un produit
 *   - Catalogue.pickProduct(callback)   → ouvre un picker, callback(product|null)
 *   - Catalogue.snippetText(product)    → bloc texte prêt à coller dans un mail
 *   - Catalogue.snippetHtml(product)    → bloc HTML prêt à coller (composer riche)
 *
 * Source de données :
 *   - API.catalog_get_full : produits + bundles editables, fusion des defauts
 *     (apps.json + sites hardcodes serveur) avec les overrides Supabase.
 *   - Fallback : API.get_apps_catalog (ancien chemin) si catalog_get_full n'est
 *     pas dispo (rétrocompatibilité pendant le deploiement).
 */

const Catalogue = {
  _items: null,
  _loadPromise: null,
  _selectedId: '',

  // ---- Sites Triskell non listés dans apps.json ----
  SITES: [
    {
      id: 'lagriffe',
      name: 'Lagriffe Studio',
      tagline: 'Sites web premium pour artisans et indépendants.',
      description: "Lagriffe Studio crée des sites vitrines élégants pour artisans, " +
        "indépendants et petites entreprises. Design soigné, performance, SEO de base, " +
        "hébergement géré. Tarif unique sans abonnement.",
      sales_pitch: "Un site qui ressemble à ton métier, pas à un template Wix.",
      motto: "Pour les pros qui veulent un vrai site, pas un site bricolé.",
      category: 'sites',
      kind: 'service',
      buy_url: 'https://lagriffe-studio.fr',
      logo: null,
      color: '#d4af37',
      initial: 'L',
      features: [
        { title: 'Design sur-mesure', detail: "Pas de template figé. Chaque site est dessiné à partir de ton métier et de ton univers." },
        { title: 'SEO de base inclus', detail: "Structure propre, balises optimisées, pages locales — tu apparais dans Google sans surcoût." },
        { title: 'Hébergement géré', detail: "On s'occupe du domaine, du HTTPS, des sauvegardes. Tu n'as rien à toucher." },
      ],
    },
    {
      id: 'rankus',
      name: 'RankUs Studio',
      tagline: 'Agence SEO — on fait monter ton site dans Google.',
      description: "RankUs Studio est l'agence SEO de l'écosystème Triskell. " +
        "On audite ton site, on corrige les blocages techniques, on rédige du contenu " +
        "qui répond aux vraies recherches de tes clients, et on suit les positions " +
        "mois après mois.",
      sales_pitch: "Tu veux apparaître quand tes clients cherchent — on t'y emmène.",
      motto: "Pour qui en a marre de payer Google Ads pour exister.",
      category: 'sites',
      kind: 'service',
      buy_url: 'https://rankus.fr',
      logo: null,
      color: '#10b981',
      initial: 'R',
      features: [
        { title: 'Audit technique', detail: "On scanne ton site, on repère ce qui bloque (vitesse, balises, structure, mobile)." },
        { title: 'Contenu ciblé', detail: "On rédige les pages qui correspondent aux requêtes que tes clients tapent vraiment." },
        { title: 'Suivi mensuel', detail: "Tableau de bord clair des positions, du trafic et des conversions. Rien de magique, juste du résultat." },
      ],
    },
    {
      id: 'pixel-pros',
      name: 'Pixel Pros',
      tagline: 'Site pro livré en 24h, 24,90 €/mois.',
      description: "Pixel Pros casse les codes du site internet. Le client remplit un " +
        "formulaire de 20 minutes, paie 24,90 € HT/mois et reçoit son site en ligne sous 24h. " +
        "Pas de devis, pas d'aller-retour, pas d'engagement. Cible : coiffeurs, plombiers, " +
        "ostéos, artisans, restaurateurs — tous les pros qui veulent un site sans y passer 6 semaines.",
      sales_pitch: "Un site pro complet à 24,90 €/mois, livré en 24h après un formulaire de 20 min.",
      motto: "Le site pro accessible : 24h pour la livraison, 24,90 €/mois pour tout.",
      category: 'sites',
      kind: 'service',
      buy_url: 'https://pixel-pros.fr',
      logo: null,
      color: '#facc15',
      initial: 'P',
      features: [
        { title: 'Formulaire 20 min', detail: "Le client remplit ce qu'il veut sur son site, on s'occupe du reste." },
        { title: 'Livraison en 24h', detail: "Site en ligne le lendemain du paiement, sans devis ni aller-retour." },
        { title: 'Textes relus et SEO', detail: "Reformulation pro de tous les textes + optimisation Google dès la création, inclus." },
        { title: 'Sections optionnelles', detail: "Galerie, avis, prestations, zone d'intervention — le client active ce qui le concerne." },
        { title: 'Pack tout-en-un possible', detail: "Site + domaine + mail pro + SEO Google = 49,90 €/mois au lieu de 68,80 €." },
        { title: 'Sans engagement', detail: "Résiliable à tout moment, le client garde son contenu." },
      ],
    },
    {
      id: 'wow',
      name: 'Studio WoW',
      tagline: 'Sites haut de gamme avec effets immersifs.',
      description: "Studio WoW conçoit des sites premium pour marques et marques personnelles " +
        "qui veulent un effet « waouh » à l'arrivée. Animations, scroll cinématique, " +
        "typographie travaillée, performance maintenue.",
      sales_pitch: "Quand un site classique ne suffit pas à raconter qui tu es.",
      motto: "Pour les marques qui veulent marquer.",
      category: 'sites',
      kind: 'service',
      buy_url: 'https://studio-wow.fr',
      logo: null,
      color: '#C9A572',
      initial: 'W',
      features: [
        { title: 'Direction artistique', detail: "Univers visuel sur-mesure : typo, couleurs, photos, ambiance — tout est pensé pour ta marque." },
        { title: 'Effets immersifs', detail: "Animations subtiles, scroll cinématique, transitions soignées. Sans plomber la vitesse." },
        { title: 'Optimisé Apple-style', detail: "Performance, accessibilité, mobile parfait. On vise le niveau des sites des grandes marques." },
      ],
    },
  ],

  // ---- Mapping catégories pour groupement & libellés ----
  CATEGORY_LABELS: {
    sites:     'Sites Triskell',
    quotidien: 'Outils du quotidien',
    pro:       "Atelier des pros",
  },
  CATEGORY_ORDER: ['sites', 'pro', 'quotidien'],

  // ---- API publique ----
  async list() {
    if (this._items) return this._items;
    if (this._loadPromise) return this._loadPromise;
    this._loadPromise = this._load();
    return this._loadPromise;
  },

  async byId(id) {
    const items = await this.list();
    return items.find(it => it.id === id) || null;
  },

  // ---- Chargement & fusion sites + apps.json ----
  async _load() {
    let products = [];
    let bundles = [];
    let disabledIds = new Set();
    let usedFull = false;
    // 1. Essai sur le nouveau endpoint (produits + bundles editables)
    if (App && App.api && typeof App.api.catalog_get_full === 'function') {
      try {
        const data = await App.api.catalog_get_full();
        if (data && data.ok) {
          products = data.products || [];
          bundles  = data.bundles  || [];
          disabledIds = new Set(data.disabled_ids || []);
          usedFull = true;
        }
      } catch (e) { console.warn('catalogue: catalog_get_full failed', e); }
    }
    // 2. Fallback : ancien endpoint apps.json + sites hardcodes locaux
    if (!usedFull && App && App.api && typeof App.api.get_apps_catalog === 'function') {
      try {
        const data = await App.api.get_apps_catalog();
        if (data && data.ok) {
          products = [...(this.SITES || []), ...(data.apps || [])];
          disabledIds = new Set(data.disabled_ids || []);
        }
      } catch (e) { console.warn('catalogue: get_apps_catalog failed', e); }
    }
    // Normalise les produits pour garantir les champs utilises par la vue
    products = products.map(a => ({
      ...a,
      description: a.description || '',
      sales_pitch: a.sales_pitch || '',
      motto:       a.motto || '',
      features:    a.features || [],
      personas:    a.personas || [],
      links:       a.links || [],
      service:     a.service || {},
      plans:       a.plans || [],
      buy_url:     (a.service && a.service.url) || a.buy_url || '',
      is_active:   a.is_active !== false,
    }));
    bundles = bundles.map(b => ({
      ...b,
      product_ids: b.product_ids || [],
      is_active:   b.is_active !== false,
    }));
    this._items   = products;
    this._bundles = bundles;
    this._disabledIds = disabledIds;
    return this._items;
  },

  byBundleId(id) {
    return (this._bundles || []).find(b => b.id === id) || null;
  },

  // ---- Toggle actif/inactif d'un produit ----
  async _toggleActive(productId, makeActive) {
    if (!App || !App.api || typeof App.api.catalog_set_active !== 'function') return;
    // Optimistic update : on met à jour la mémoire avant la réponse serveur
    const it = (this._items || []).find(x => x.id === productId);
    if (it) it.is_active = makeActive;
    if (this._disabledIds) {
      if (makeActive) this._disabledIds.delete(productId);
      else this._disabledIds.add(productId);
    }
    this._renderGrid();
    try {
      const r = await App.api.catalog_set_active({ id: productId, active: makeActive });
      if (!r || !r.ok) {
        // Rollback en cas d'erreur
        if (it) it.is_active = !makeActive;
        if (this._disabledIds) {
          if (makeActive) this._disabledIds.add(productId);
          else this._disabledIds.delete(productId);
        }
        this._renderGrid();
      }
    } catch (e) {
      console.warn('catalog_set_active failed', e);
      if (it) it.is_active = !makeActive;
      this._renderGrid();
    }
  },

  // ---- Rendu principal de la vue Catalogue ----
  async render(container) {
    this._root = container;
    container.innerHTML = `
      <section class="animate-slide-up">
        <div class="mb-8">
          <div class="hero-kicker mb-2">CATALOGUE</div>
          <h1 class="hero-title mb-3" style="font-size: 36px;">L'écosystème Triskell.</h1>
          <p class="hero-subtitle">Tous les sites et outils de l'écosystème. Choisis-en un pour voir sa fiche, sa fonction précise et son lien public.</p>
        </div>

        <div id="catalogue-loading" class="text-text-muted text-sm py-6">Chargement…</div>
        <div id="catalogue-grid" class="hidden"></div>
        <div id="catalogue-detail-modal"></div>
      </section>
    `;

    await this.list();
    const loading = document.getElementById('catalogue-loading');
    const grid    = document.getElementById('catalogue-grid');
    if (loading) loading.classList.add('hidden');
    if (grid)    grid.classList.remove('hidden');
    this._renderGrid();
  },

  _renderGrid() {
    const grid = document.getElementById('catalogue-grid');
    if (!grid) return;

    // Section Packs (toujours en haut si il y en a, sinon juste le bouton créer)
    const bundles = this._bundles || [];
    const bundlesHtml = `
      <div class="mb-10">
        <div class="flex items-center justify-between mb-4">
          <h2 class="text-[11px] tracking-widest font-bold text-text-muted">PACKS &amp; OFFRES GROUPÉES</h2>
          <button id="catalog-create-bundle"
                  class="btn btn-secondary text-xs"
                  style="padding:6px 12px;">+ Créer un pack</button>
        </div>
        ${bundles.length
          ? `<div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
               ${bundles.map(b => this._bundleTile(b)).join('')}
             </div>`
          : `<p class="text-xs text-text-muted">Aucun pack créé. Clique sur « + Créer un pack » pour combiner plusieurs produits en une offre.</p>`
        }
      </div>
    `;

    // Groupe les produits par catégorie
    const groups = {};
    (this._items || []).forEach(it => {
      const cat = it.category || 'autre';
      (groups[cat] = groups[cat] || []).push(it);
    });

    const sections = this.CATEGORY_ORDER.map(cat => {
      const list = groups[cat];
      if (!list || !list.length) return '';
      const label = this.CATEGORY_LABELS[cat] || cat;
      return `
        <div class="mb-10">
          <div class="flex items-center justify-between mb-4">
            <h2 class="text-[11px] tracking-widest font-bold text-text-muted">${this._esc(label.toUpperCase())}</h2>
            <button data-add-in-cat="${this._esc(cat)}"
                    class="btn btn-secondary text-xs"
                    style="padding:6px 12px;">+ Ajouter un produit</button>
          </div>
          <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            ${list.map(it => this._tile(it)).join('')}
          </div>
        </div>
      `;
    }).join('');

    grid.innerHTML = bundlesHtml + sections;

    grid.querySelectorAll('[data-cat-id]').forEach(el => {
      el.onclick = () => this._openDetail(el.dataset.catId);
    });
    grid.querySelectorAll('[data-bundle-id]').forEach(el => {
      el.onclick = () => this._openBundleDetail(el.dataset.bundleId);
    });
    grid.querySelectorAll('[data-toggle-id]').forEach(btn => {
      btn.onclick = (e) => {
        e.stopPropagation();
        e.preventDefault();
        const id = btn.dataset.toggleId;
        const wasActive = btn.dataset.toggleActive === '1';
        this._toggleActive(id, !wasActive);
      };
    });
    const createBtn = document.getElementById('catalog-create-bundle');
    if (createBtn) createBtn.onclick = () => this._openBundleEdit(null);
    grid.querySelectorAll('[data-add-in-cat]').forEach(btn => {
      btn.onclick = () => this._openProductEdit(null, btn.dataset.addInCat || '');
    });
  },

  _bundleTile(b) {
    const visual = b.logo
      ? `<img src="${this._esc(b.logo)}" alt="" class="w-12 h-12 rounded-xl shrink-0" style="object-fit:contain;" />`
      : `<div class="w-12 h-12 rounded-xl shrink-0 flex items-center justify-center text-white font-bold text-lg"
              style="background:${this._esc(b.color || '#6366F1')};">${this._esc((b.name || 'P')[0])}</div>`;
    const countTxt = (b.product_ids || []).length + ' produit' + ((b.product_ids || []).length > 1 ? 's' : '');
    const priceBadge = b.price != null
      ? `<span class="px-2 py-0.5 rounded text-[10px] font-semibold bg-accent/15 text-accent">${b.price} €</span>`
      : `<span class="px-2 py-0.5 rounded text-[10px] font-semibold bg-warning/15 text-warning" style="background:rgba(217,119,6,0.15);color:#92400e;">PACK</span>`;
    const isActive = b.is_active !== false;
    return `
      <div style="position:relative;${isActive ? '' : 'opacity:0.45;'}">
        <button data-bundle-id="${this._esc(b.id)}"
                class="text-left bg-surface-elevated rounded-2xl p-4 w-full
                       border-2 border-accent/30 hover:border-accent
                       transition-all duration-200 hover:shadow-soft
                       focus:outline-none">
          <div class="flex items-start gap-3 mb-2 pr-10">
            ${visual}
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2 flex-wrap mb-0.5">
                <div class="font-semibold text-[15px] leading-tight">${this._esc(b.name || '')}</div>
                ${priceBadge}
              </div>
              <div class="text-[10px] text-text-muted">${countTxt}</div>
            </div>
          </div>
          <p class="text-xs text-text-secondary line-clamp-2 leading-snug">${this._esc(b.tagline || '')}</p>
        </button>
        <button data-toggle-id="${this._esc(b.id)}"
                data-toggle-active="${isActive ? '1' : '0'}"
                title="${isActive ? 'Désactiver ce pack' : 'Activer ce pack'}"
                style="position:absolute;top:10px;right:10px;width:36px;height:20px;border-radius:999px;border:none;cursor:pointer;
                       background:${isActive ? '#10b981' : '#9ca3af'};transition:background 0.15s ease;padding:0;">
          <span style="position:absolute;top:2px;left:${isActive ? '18px' : '2px'};width:16px;height:16px;border-radius:999px;background:#fff;transition:left 0.15s ease;box-shadow:0 1px 2px rgba(0,0,0,0.25);"></span>
        </button>
      </div>
    `;
  },

  _tile(it) {
    const visual = it.logo
      ? `<img src="${this._esc(it.logo)}" alt=""
              class="w-12 h-12 rounded-xl shrink-0"
              style="object-fit: contain;" />`
      : `<div class="w-12 h-12 rounded-xl shrink-0 flex items-center justify-center text-white font-bold text-lg"
              style="background: ${this._esc(it.color || '#6366F1')};">${this._esc(it.initial || (it.name || '?')[0])}</div>`;

    const badge = it.coming_soon
      ? `<span class="px-2 py-0.5 rounded text-[10px] font-semibold bg-text-muted/15 text-text-muted">Bientôt</span>`
      : (it.price != null
          ? `<span class="px-2 py-0.5 rounded text-[10px] font-semibold bg-accent/15 text-accent">${it.price} €</span>`
          : (it.price_from
              ? `<span class="px-2 py-0.5 rounded text-[10px] font-semibold bg-accent/15 text-accent">${this._esc(String(it.price_from))}</span>`
              : (it.kind === 'service'
                  ? `<span class="px-2 py-0.5 rounded text-[10px] font-semibold bg-success/15 text-success">Service</span>`
                  : '')));

    const isActive = it.is_active !== false;
    const toggleOn = isActive ? 'on' : 'off';
    const toggle = `
      <button data-toggle-id="${this._esc(it.id)}"
              data-toggle-active="${isActive ? '1' : '0'}"
              title="${isActive ? 'Cliquer pour désactiver' : 'Cliquer pour activer'} — un produit désactivé n'apparaît plus dans les mails ni dans la prospection IA"
              class="catalog-toggle catalog-toggle-${toggleOn}"
              style="position:absolute;top:10px;right:10px;width:36px;height:20px;border-radius:999px;border:none;cursor:pointer;
                     background:${isActive ? '#10b981' : '#9ca3af'};
                     transition:background 0.15s ease;
                     padding:0;">
        <span style="position:absolute;top:2px;left:${isActive ? '18px' : '2px'};
                     width:16px;height:16px;border-radius:999px;background:#fff;
                     transition:left 0.15s ease;
                     box-shadow:0 1px 2px rgba(0,0,0,0.25);"></span>
      </button>
    `;

    const dim = isActive ? '' : 'opacity:0.45;';

    return `
      <div style="position:relative;${dim}">
        <button data-cat-id="${this._esc(it.id)}"
                class="text-left bg-surface-elevated rounded-2xl p-4 w-full
                       border border-border hover:border-accent
                       transition-all duration-200 hover:shadow-soft
                       focus:outline-none">
          <div class="flex items-start gap-3 mb-2 pr-10">
            ${visual}
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2 flex-wrap mb-0.5">
                <div class="font-semibold text-[15px] leading-tight">${this._esc(it.name || '')}</div>
                ${badge}
              </div>
            </div>
          </div>
          <p class="text-xs text-text-secondary line-clamp-2 leading-snug">
            ${this._esc(it.tagline || '')}
          </p>
        </button>
        ${toggle}
      </div>
    `;
  },

  // ---- Fiche détaillée (modale) ----
  _openDetail(id) {
    const it = (this._items || []).find(x => x.id === id);
    if (!it) return;
    this._selectedId = id;

    const visual = it.logo
      ? `<img src="${this._esc(it.logo)}" alt=""
              class="w-20 h-20 rounded-2xl shrink-0"
              style="object-fit: contain;" />`
      : `<div class="w-20 h-20 rounded-2xl shrink-0 flex items-center justify-center text-white font-bold text-3xl"
              style="background: ${this._esc(it.color || '#6366F1')};">${this._esc(it.initial || (it.name || '?')[0])}</div>`;

    const priceLine = it.price != null
      ? `${it.price} €${it.price_original ? ` <span class="line-through text-text-muted">${it.price_original} €</span>` : ''}${it.price_note ? ` · <span class="text-text-muted">${this._esc(it.price_note)}</span>` : ''}`
      : (it.price_from
          ? `${this._esc(String(it.price_from))}${it.price_note ? ` · <span class="text-text-muted">${this._esc(it.price_note)}</span>` : ''}`
          : (it.kind === 'service' ? 'Service' : ''));

    const features = (it.features || []).map(f => {
      if (typeof f === 'string') return `<li>${this._esc(f)}</li>`;
      return `<li><strong>${this._esc(f.title || '')}</strong>${f.detail ? ` — ${this._esc(f.detail)}` : ''}</li>`;
    }).join('');

    const personas = (it.personas || []).slice(0, 4).map(p => `
      <div class="bg-bg rounded-xl p-3 border border-border">
        <div class="text-xl mb-1">${this._esc(p.icon || '👤')}</div>
        <div class="text-sm font-semibold mb-0.5">${this._esc(p.name || '')}</div>
        <div class="text-xs text-text-muted leading-snug">${this._esc(p.description || '')}</div>
      </div>
    `).join('');

    const links = (it.links || []).map(l =>
      `<a href="${this._esc(l.url)}" target="_blank" rel="noopener" class="text-accent text-sm hover:underline">${this._esc(l.label || l.url)}</a>`
    ).join(' · ');

    const url = it.buy_url || '';

    const html = `
      <div id="catalogue-detail-overlay"
           class="fixed inset-0 z-[200] flex items-start justify-center pt-[6vh] px-4 transition-opacity duration-200"
           style="background: rgba(15,23,42,0.55); backdrop-filter: blur(10px); opacity: 0;">
        <div class="catalogue-detail-card bg-surface rounded-3xl shadow-hero
                    w-full max-w-[820px] max-h-[88vh] overflow-y-auto
                    transition-transform duration-200"
             style="border: 1px solid hsl(var(--border)); transform: scale(0.96) translateY(8px);">

          <!-- Header -->
          <div class="px-7 pt-6 pb-5 border-b border-border flex items-start gap-5">
            ${visual}
            <div class="flex-1 min-w-0">
              <div class="hero-kicker mb-1">${this._esc((this.CATEGORY_LABELS[it.category] || '').toUpperCase())}</div>
              <h2 class="text-2xl font-bold leading-tight mb-1">${this._esc(it.name || '')}</h2>
              <p class="text-text-secondary text-sm">${this._esc(it.tagline || '')}</p>
            </div>
            <button id="catalogue-detail-close"
                    class="w-9 h-9 rounded-lg flex items-center justify-center
                           text-text-muted hover:text-text hover:bg-bg
                           transition-colors text-2xl leading-none shrink-0">×</button>
          </div>

          <!-- Body -->
          <div class="px-7 py-6 space-y-6">
            ${it.motto ? `
              <div class="text-sm italic text-text-secondary border-l-2 border-accent pl-4">
                « ${this._esc(it.motto)} »
              </div>` : ''}

            ${it.description ? `
              <div>
                <div class="text-[11px] tracking-widest font-bold text-text-muted mb-2">FONCTION</div>
                <p class="text-text leading-relaxed whitespace-pre-line">${this._esc(it.description)}</p>
              </div>` : ''}

            ${features ? `
              <div>
                <div class="text-[11px] tracking-widest font-bold text-text-muted mb-2">CE QUE ÇA FAIT</div>
                <ul class="space-y-2 text-sm text-text leading-relaxed list-disc pl-5">${features}</ul>
              </div>` : ''}

            ${personas ? `
              <div>
                <div class="text-[11px] tracking-widest font-bold text-text-muted mb-2">POUR QUI</div>
                <div class="grid grid-cols-2 md:grid-cols-4 gap-3">${personas}</div>
              </div>` : ''}

            ${priceLine ? `
              <div>
                <div class="text-[11px] tracking-widest font-bold text-text-muted mb-2">TARIF</div>
                <div class="text-sm">${priceLine}</div>
              </div>` : ''}

            ${links ? `
              <div>
                <div class="text-[11px] tracking-widest font-bold text-text-muted mb-2">LIENS</div>
                <div>${links}</div>
              </div>` : ''}
          </div>

          <!-- Footer -->
          <div class="px-7 py-4 border-t border-border bg-surface-elevated flex items-center justify-between flex-wrap gap-2 sticky bottom-0">
            <div class="flex gap-2">
              <button id="catalogue-detail-edit" class="btn btn-secondary">✎ Modifier</button>
              ${!it.is_builtin ? `<button id="catalogue-detail-delete" class="btn btn-secondary" style="color:#dc2626;">Supprimer</button>` : ''}
            </div>
            <div class="flex gap-2">
              <button id="catalogue-detail-copy" class="btn btn-secondary">Copier le pitch</button>
              ${url ? `<button id="catalogue-detail-open" class="btn btn-primary">Ouvrir le site</button>` : ''}
            </div>
          </div>
        </div>
      </div>
    `;

    const slot = document.getElementById('catalogue-detail-modal');
    if (!slot) return;
    slot.innerHTML = html;

    const ov = document.getElementById('catalogue-detail-overlay');
    const card = ov && ov.querySelector('.catalogue-detail-card');
    requestAnimationFrame(() => {
      if (ov) ov.style.opacity = '1';
      if (card) card.style.transform = 'scale(1) translateY(0)';
    });
    ov.addEventListener('click', (e) => { if (e.target === ov) this._closeDetail(); });
    document.getElementById('catalogue-detail-close').onclick = () => this._closeDetail();
    const openBtn = document.getElementById('catalogue-detail-open');
    if (openBtn) {
      openBtn.onclick = async () => {
        if (App && App.api && typeof App.api.open_url === 'function') {
          try { await App.api.open_url({ url }); return; } catch (e) {}
        }
        window.open(url, '_blank', 'noopener,noreferrer');
      };
    }
    document.getElementById('catalogue-detail-copy').onclick = async () => {
      try {
        await navigator.clipboard.writeText(this.snippetText(it));
        const btn = document.getElementById('catalogue-detail-copy');
        if (btn) { btn.textContent = 'Copié ✓'; setTimeout(() => { btn.textContent = 'Copier le pitch'; }, 1400); }
      } catch (e) { console.warn(e); }
    };
    const editBtn = document.getElementById('catalogue-detail-edit');
    if (editBtn) editBtn.onclick = () => this._openProductEdit(it.id, it.category || '');
    const delBtn = document.getElementById('catalogue-detail-delete');
    if (delBtn) delBtn.onclick = async () => {
      if (!confirm(`Supprimer définitivement "${it.name}" du catalogue ?`)) return;
      try {
        const r = await App.api.catalog_delete_product({ id: it.id });
        if (r && r.ok) {
          this._items = (this._items || []).filter(x => x.id !== it.id);
          this._closeDetail();
          this._renderGrid();
        } else {
          alert('Suppression impossible : ' + (r && r.error || 'erreur inconnue'));
        }
      } catch (e) { alert('Erreur : ' + e); }
    };
  },

  // ============================================================
  // EDITION D'UN PRODUIT (modale formulaire)
  // ============================================================
  _openProductEdit(productId, defaultCategory) {
    const isNew = !productId;
    const it = isNew
      ? { id: '', name: '', tagline: '', description: '', motto: '', sales_pitch: '',
          category: defaultCategory || 'pro', kind: 'service', price: null, price_original: null,
          price_from: '', price_note: '', buy_url: '', logo: '', color: '#6366F1',
          initial: '', keywords: '', prospect_pitch: '' }
      : ((this._items || []).find(x => x.id === productId) || null);
    if (!it) return;
    const cats = this.CATEGORY_ORDER;
    const html = `
      <div id="catalogue-detail-overlay"
           class="fixed inset-0 z-[210] flex items-start justify-center pt-[6vh] px-4 transition-opacity duration-200"
           style="background: rgba(15,23,42,0.55); backdrop-filter: blur(10px); opacity: 0;">
        <div class="catalogue-detail-card bg-surface rounded-3xl shadow-hero
                    w-full max-w-[760px] max-h-[88vh] overflow-y-auto
                    transition-transform duration-200"
             style="border: 1px solid hsl(var(--border)); transform: scale(0.96) translateY(8px);">
          <div class="px-7 pt-6 pb-4 border-b border-border flex items-start justify-between gap-4">
            <div>
              <div class="hero-kicker mb-1">${isNew ? 'NOUVEAU PRODUIT' : 'ÉDITION'}</div>
              <h2 class="text-2xl font-bold leading-tight">${isNew ? 'Créer un produit' : this._esc(it.name || '')}</h2>
            </div>
            <button id="cat-edit-close"
                    class="w-9 h-9 rounded-lg flex items-center justify-center text-text-muted hover:text-text hover:bg-bg transition-colors text-2xl leading-none shrink-0">×</button>
          </div>
          <form id="cat-edit-form" class="px-7 py-6 space-y-4">
            ${this._field('name', 'Nom du produit', it.name, { required: true, placeholder: 'Ex : Pack Électricien Pro' })}
            ${this._field('tagline', 'Phrase d’accroche (1 ligne)', it.tagline, { placeholder: 'Ex : Site web + outils métier pour électriciens' })}
            ${this._fieldArea('description', 'Description complète', it.description, { rows: 4, placeholder: 'Présente le produit, ses bénéfices, qui c’est pour…' })}
            ${this._fieldArea('motto', 'Devise (en italique sur la fiche)', it.motto, { rows: 2, placeholder: 'Ex : Pour les pros qui veulent un vrai site…' })}
            <div class="grid grid-cols-2 gap-3">
              ${this._fieldSelect('category', 'Section du catalogue', it.category, cats.map(c => ({ value: c, label: this.CATEGORY_LABELS[c] || c })))}
              ${this._fieldSelect('kind', 'Type', it.kind || 'service', [
                { value: 'service', label: 'Service (à vendre)' },
                { value: 'product', label: 'Produit (à vendre)' },
                { value: 'app',     label: 'Application (à vendre)' },
                { value: 'demo',    label: 'Démo métier (exemple à montrer dans les mails)' },
              ])}
            </div>
            <p class="text-[11px] text-text-muted -mt-2 mb-2">
              <strong>Démo métier</strong> = un exemple de site (ou autre) que tu présentes au prospect
              pour qu'il visualise ce que tu peux lui faire. L'IA inclut le lien dans le mail comme
              preuve visuelle adaptée à son métier, mais ne le vend pas comme produit.
            </p>
            <div class="grid grid-cols-3 gap-3">
              ${this._field('price', 'Prix (€)', it.price, { type: 'number', placeholder: '0' })}
              ${this._field('price_original', 'Prix barré (€)', it.price_original, { type: 'number', placeholder: 'optionnel' })}
              ${this._field('price_from', 'Texte « à partir de »', it.price_from, { placeholder: 'Ex : À partir de 49 €' })}
            </div>
            ${this._field('price_note', 'Note sur le tarif', it.price_note, { placeholder: 'Ex : par mois, paiement unique…' })}
            ${this._field('buy_url', 'Lien public du produit', it.buy_url, { placeholder: 'https://…' })}
            ${this._field('logo', 'URL de l’image / logo', it.logo, { placeholder: 'https://…/logo.png — laisse vide pour un avatar lettre' })}
            <div class="grid grid-cols-2 gap-3">
              ${this._field('color', 'Couleur fallback (si pas de logo)', it.color, { type: 'color' })}
              ${this._field('initial', 'Initiale fallback', it.initial, { maxlength: 2, placeholder: 'Ex : L' })}
            </div>
            <div class="border-t border-border pt-4 mt-2">
              <div class="flex items-center justify-between mb-3">
                <div class="text-[11px] tracking-widest font-bold text-text-muted">CE QUE ÇA FAIT (fonctionnalités)</div>
                <button type="button" id="cat-feat-add" class="text-xs text-accent hover:underline">+ Ajouter une ligne</button>
              </div>
              <div id="cat-feat-list" class="space-y-2"></div>
              <p class="text-[11px] text-text-muted mt-1">Affiché en liste à puces dans la fiche produit.</p>
            </div>
            <div class="border-t border-border pt-4 mt-2">
              <div class="text-[11px] tracking-widest font-bold text-text-muted mb-3">UTILISATION PAR L'IA EN PROSPECTION</div>
              ${this._field('keywords', 'Mots-clés (séparés par virgules)', it.keywords, { placeholder: 'Ex : électricien, artisan, BTP' })}
              ${this._fieldArea('prospect_pitch', 'Pitch court pour les mails de prospection', it.prospect_pitch, { rows: 3, placeholder: 'En 1-2 phrases : à qui s’adresse ce produit et pourquoi.' })}
              <p class="text-[11px] text-text-muted mt-1">Ces deux champs guident l'IA quand elle écrit des mails — c'est ce qu'elle « connaît » sur ton produit.</p>
            </div>
          </form>
          <div class="px-7 py-4 border-t border-border bg-surface-elevated flex items-center justify-end gap-2 sticky bottom-0">
            <button id="cat-edit-cancel" class="btn btn-secondary">Annuler</button>
            <button id="cat-edit-save" class="btn btn-primary">Enregistrer</button>
          </div>
        </div>
      </div>
    `;
    const slot = document.getElementById('catalogue-detail-modal');
    if (!slot) return;
    slot.innerHTML = html;
    const ov = document.getElementById('catalogue-detail-overlay');
    requestAnimationFrame(() => {
      if (ov) ov.style.opacity = '1';
      const card = ov && ov.querySelector('.catalogue-detail-card');
      if (card) card.style.transform = 'scale(1) translateY(0)';
    });
    document.getElementById('cat-edit-close').onclick = () => this._closeDetail();
    document.getElementById('cat-edit-cancel').onclick = () => this._closeDetail();
    ov.addEventListener('click', (e) => { if (e.target === ov) this._closeDetail(); });
    // --- Editeur de liste de fonctionnalités ---
    const featList = document.getElementById('cat-feat-list');
    const escHtml = (s) => this._esc(s);
    const addFeatureRow = (title, detail) => {
      const row = document.createElement('div');
      row.className = 'cat-feat-row flex gap-2 items-start';
      row.innerHTML = `
        <input type="text" placeholder="Titre (ex : SEO optimisé)" value="${escHtml(title || '')}"
               class="cat-feat-title px-3 py-2 rounded-lg border border-border bg-bg text-sm focus:outline-none focus:border-accent"
               style="flex:1 1 0; min-width:0;" />
        <input type="text" placeholder="Détail (1 phrase courte)" value="${escHtml(detail || '')}"
               class="cat-feat-detail px-3 py-2 rounded-lg border border-border bg-bg text-sm focus:outline-none focus:border-accent"
               style="flex:2 1 0; min-width:0;" />
        <button type="button" class="cat-feat-remove px-3 py-2 text-text-muted hover:text-red-500 text-lg leading-none" title="Retirer cette ligne">×</button>
      `;
      featList.appendChild(row);
      row.querySelector('.cat-feat-remove').onclick = () => row.remove();
    };
    (it.features || []).forEach(f => {
      if (typeof f === 'string') addFeatureRow(f, '');
      else addFeatureRow(f.title || '', f.detail || '');
    });
    if (!(it.features || []).length) addFeatureRow('', '');
    document.getElementById('cat-feat-add').onclick = () => addFeatureRow('', '');
    document.getElementById('cat-edit-save').onclick = async () => {
      const form = document.getElementById('cat-edit-form');
      const data = {};
      form.querySelectorAll('input[name], textarea[name], select[name]').forEach(el => { data[el.name] = el.value; });
      data.features = Array.from(form.querySelectorAll('.cat-feat-row')).map(r => ({
        title:  r.querySelector('.cat-feat-title').value.trim(),
        detail: r.querySelector('.cat-feat-detail').value.trim(),
      })).filter(f => f.title || f.detail);
      if (!isNew) data.id = it.id;
      const saveBtn = document.getElementById('cat-edit-save');
      saveBtn.disabled = true; saveBtn.textContent = 'Enregistrement…';
      try {
        const r = await App.api.catalog_save_product(data);
        if (r && r.ok) {
          this._items = null; this._loadPromise = null;
          await this.list();
          this._closeDetail();
          this._renderGrid();
        } else {
          alert('Sauvegarde impossible : ' + (r && r.error || 'erreur inconnue'));
          saveBtn.disabled = false; saveBtn.textContent = 'Enregistrer';
        }
      } catch (e) {
        alert('Erreur : ' + e);
        saveBtn.disabled = false; saveBtn.textContent = 'Enregistrer';
      }
    };
  },

  // ============================================================
  // FICHE D'UN PACK (lecture)
  // ============================================================
  _openBundleDetail(bundleId) {
    const b = this.byBundleId(bundleId);
    if (!b) return;
    const includedProducts = (b.product_ids || [])
      .map(pid => (this._items || []).find(x => x.id === pid))
      .filter(Boolean);
    const includedHtml = includedProducts.length
      ? includedProducts.map(p => `
          <div class="flex items-center gap-3 p-3 bg-bg rounded-xl border border-border">
            ${p.logo
              ? `<img src="${this._esc(p.logo)}" class="w-10 h-10 rounded-lg" style="object-fit:contain;" />`
              : `<div class="w-10 h-10 rounded-lg flex items-center justify-center text-white font-bold" style="background:${this._esc(p.color || '#6366F1')};">${this._esc((p.name || '?')[0])}</div>`}
            <div class="flex-1 min-w-0">
              <div class="text-sm font-semibold">${this._esc(p.name)}</div>
              <div class="text-xs text-text-muted line-clamp-1">${this._esc(p.tagline || '')}</div>
            </div>
          </div>`).join('')
      : '<p class="text-sm text-text-muted">Aucun produit dans ce pack. Modifie-le pour en ajouter.</p>';
    const priceLine = b.price != null
      ? `${b.price} €${b.price_note ? ` · <span class="text-text-muted">${this._esc(b.price_note)}</span>` : ''}`
      : (b.price_note ? `<span class="text-text-muted">${this._esc(b.price_note)}</span>` : '');
    const html = `
      <div id="catalogue-detail-overlay"
           class="fixed inset-0 z-[210] flex items-start justify-center pt-[6vh] px-4 transition-opacity duration-200"
           style="background: rgba(15,23,42,0.55); backdrop-filter: blur(10px); opacity: 0;">
        <div class="catalogue-detail-card bg-surface rounded-3xl shadow-hero w-full max-w-[720px] max-h-[88vh] overflow-y-auto transition-transform duration-200"
             style="border: 1px solid hsl(var(--border)); transform: scale(0.96) translateY(8px);">
          <div class="px-7 pt-6 pb-5 border-b border-border flex items-start justify-between gap-4">
            <div>
              <div class="hero-kicker mb-1">PACK</div>
              <h2 class="text-2xl font-bold leading-tight mb-1">${this._esc(b.name || '')}</h2>
              <p class="text-text-secondary text-sm">${this._esc(b.tagline || '')}</p>
            </div>
            <button id="cat-bundle-close" class="w-9 h-9 rounded-lg flex items-center justify-center text-text-muted hover:text-text hover:bg-bg transition-colors text-2xl leading-none shrink-0">×</button>
          </div>
          <div class="px-7 py-6 space-y-6">
            ${b.description ? `<p class="text-text leading-relaxed whitespace-pre-line">${this._esc(b.description)}</p>` : ''}
            <div>
              <div class="text-[11px] tracking-widest font-bold text-text-muted mb-3">CONTENU DU PACK</div>
              <div class="space-y-2">${includedHtml}</div>
            </div>
            ${priceLine ? `<div><div class="text-[11px] tracking-widest font-bold text-text-muted mb-2">TARIF</div><div class="text-sm">${priceLine}</div></div>` : ''}
          </div>
          <div class="px-7 py-4 border-t border-border bg-surface-elevated flex items-center justify-between gap-2 sticky bottom-0">
            <button id="cat-bundle-delete" class="btn btn-secondary" style="color:#dc2626;">Supprimer</button>
            <div class="flex gap-2">
              <button id="cat-bundle-edit" class="btn btn-secondary">✎ Modifier</button>
              ${b.buy_url ? `<button id="cat-bundle-open" class="btn btn-primary">Ouvrir le lien</button>` : ''}
            </div>
          </div>
        </div>
      </div>
    `;
    const slot = document.getElementById('catalogue-detail-modal');
    if (!slot) return;
    slot.innerHTML = html;
    const ov = document.getElementById('catalogue-detail-overlay');
    requestAnimationFrame(() => {
      if (ov) ov.style.opacity = '1';
      const card = ov && ov.querySelector('.catalogue-detail-card');
      if (card) card.style.transform = 'scale(1) translateY(0)';
    });
    ov.addEventListener('click', (e) => { if (e.target === ov) this._closeDetail(); });
    document.getElementById('cat-bundle-close').onclick = () => this._closeDetail();
    document.getElementById('cat-bundle-edit').onclick = () => this._openBundleEdit(b.id);
    document.getElementById('cat-bundle-delete').onclick = async () => {
      if (!confirm(`Supprimer le pack "${b.name}" ?`)) return;
      try {
        const r = await App.api.catalog_delete_bundle({ id: b.id });
        if (r && r.ok) {
          this._bundles = (this._bundles || []).filter(x => x.id !== b.id);
          this._closeDetail();
          this._renderGrid();
        } else { alert('Suppression impossible'); }
      } catch (e) { alert('Erreur : ' + e); }
    };
    const openBtn = document.getElementById('cat-bundle-open');
    if (openBtn) openBtn.onclick = () => window.open(b.buy_url, '_blank', 'noopener,noreferrer');
  },

  // ============================================================
  // EDITION D'UN PACK
  // ============================================================
  _openBundleEdit(bundleId) {
    const isNew = !bundleId;
    const b = isNew
      ? { id: '', name: '', tagline: '', description: '', price: null, price_note: '',
          buy_url: '', logo: '', color: '#6366F1', product_ids: [] }
      : (this.byBundleId(bundleId) || null);
    if (!b) return;
    const productOptions = (this._items || []).map(p => {
      const checked = (b.product_ids || []).includes(p.id) ? 'checked' : '';
      return `
        <label class="flex items-center gap-2 p-2 rounded-lg hover:bg-bg cursor-pointer">
          <input type="checkbox" name="product_ids" value="${this._esc(p.id)}" ${checked} class="w-4 h-4"/>
          ${p.logo
            ? `<img src="${this._esc(p.logo)}" class="w-7 h-7 rounded" style="object-fit:contain;" />`
            : `<div class="w-7 h-7 rounded flex items-center justify-center text-white text-xs font-bold" style="background:${this._esc(p.color || '#6366F1')};">${this._esc((p.name || '?')[0])}</div>`}
          <span class="text-sm">${this._esc(p.name)}</span>
        </label>
      `;
    }).join('');
    const html = `
      <div id="catalogue-detail-overlay"
           class="fixed inset-0 z-[210] flex items-start justify-center pt-[6vh] px-4 transition-opacity duration-200"
           style="background: rgba(15,23,42,0.55); backdrop-filter: blur(10px); opacity: 0;">
        <div class="catalogue-detail-card bg-surface rounded-3xl shadow-hero w-full max-w-[720px] max-h-[88vh] overflow-y-auto transition-transform duration-200"
             style="border: 1px solid hsl(var(--border)); transform: scale(0.96) translateY(8px);">
          <div class="px-7 pt-6 pb-4 border-b border-border flex items-start justify-between gap-4">
            <div>
              <div class="hero-kicker mb-1">${isNew ? 'NOUVEAU PACK' : 'ÉDITION DU PACK'}</div>
              <h2 class="text-2xl font-bold leading-tight">${isNew ? 'Créer un pack' : this._esc(b.name || '')}</h2>
            </div>
            <button id="cat-bedit-close" class="w-9 h-9 rounded-lg flex items-center justify-center text-text-muted hover:text-text hover:bg-bg transition-colors text-2xl leading-none shrink-0">×</button>
          </div>
          <form id="cat-bedit-form" class="px-7 py-6 space-y-4">
            ${this._field('name', 'Nom du pack', b.name, { required: true, placeholder: 'Ex : Pack lancement artisan' })}
            ${this._field('tagline', 'Phrase d’accroche', b.tagline, { placeholder: 'Ex : Site + SEO + outils métier' })}
            ${this._fieldArea('description', 'Description', b.description, { rows: 3, placeholder: 'Ce que contient le pack et pour qui' })}
            <div class="grid grid-cols-2 gap-3">
              ${this._field('price', 'Prix du pack (€)', b.price, { type: 'number' })}
              ${this._field('price_note', 'Note tarif', b.price_note, { placeholder: 'Ex : -20% vs séparé' })}
            </div>
            ${this._field('buy_url', 'Lien public du pack', b.buy_url, { placeholder: 'https://…' })}
            ${this._field('logo', 'URL de l’image', b.logo, { placeholder: 'https://…/pack.png — optionnel' })}
            ${this._field('color', 'Couleur fallback', b.color, { type: 'color' })}
            <div>
              <label class="block text-sm font-semibold mb-2">Produits inclus</label>
              <div class="grid grid-cols-1 sm:grid-cols-2 gap-1 max-h-[260px] overflow-y-auto p-2 border border-border rounded-xl">
                ${productOptions || '<p class="text-xs text-text-muted col-span-2 p-2">Aucun produit dans le catalogue. Crée d’abord des produits.</p>'}
              </div>
            </div>
          </form>
          <div class="px-7 py-4 border-t border-border bg-surface-elevated flex items-center justify-end gap-2 sticky bottom-0">
            <button id="cat-bedit-cancel" class="btn btn-secondary">Annuler</button>
            <button id="cat-bedit-save" class="btn btn-primary">Enregistrer</button>
          </div>
        </div>
      </div>
    `;
    const slot = document.getElementById('catalogue-detail-modal');
    if (!slot) return;
    slot.innerHTML = html;
    const ov = document.getElementById('catalogue-detail-overlay');
    requestAnimationFrame(() => {
      if (ov) ov.style.opacity = '1';
      const card = ov && ov.querySelector('.catalogue-detail-card');
      if (card) card.style.transform = 'scale(1) translateY(0)';
    });
    ov.addEventListener('click', (e) => { if (e.target === ov) this._closeDetail(); });
    document.getElementById('cat-bedit-close').onclick = () => this._closeDetail();
    document.getElementById('cat-bedit-cancel').onclick = () => this._closeDetail();
    document.getElementById('cat-bedit-save').onclick = async () => {
      const form = document.getElementById('cat-bedit-form');
      const data = {};
      form.querySelectorAll('input[type=text], input[type=number], input[type=color], textarea, input[type=url], input:not([type])').forEach(el => {
        if (el.name && el.name !== 'product_ids') data[el.name] = el.value;
      });
      data.product_ids = Array.from(form.querySelectorAll('input[name=product_ids]:checked')).map(c => c.value);
      if (!isNew) data.id = b.id;
      const btn = document.getElementById('cat-bedit-save');
      btn.disabled = true; btn.textContent = 'Enregistrement…';
      try {
        const r = await App.api.catalog_save_bundle(data);
        if (r && r.ok) {
          this._items = null; this._loadPromise = null;
          await this.list();
          this._closeDetail();
          this._renderGrid();
        } else {
          alert('Sauvegarde impossible : ' + (r && r.error || 'erreur inconnue'));
          btn.disabled = false; btn.textContent = 'Enregistrer';
        }
      } catch (e) {
        alert('Erreur : ' + e);
        btn.disabled = false; btn.textContent = 'Enregistrer';
      }
    };
  },

  // ============================================================
  // Helpers HTML formulaire
  // ============================================================
  _field(name, label, value, opts) {
    opts = opts || {};
    const v = value == null ? '' : value;
    const type = opts.type || 'text';
    return `
      <label class="block">
        <span class="block text-sm font-semibold mb-1">${label}${opts.required ? ' *' : ''}</span>
        <input name="${this._esc(name)}" type="${type}"
               value="${this._esc(String(v))}"
               ${opts.placeholder ? `placeholder="${this._esc(opts.placeholder)}"` : ''}
               ${opts.maxlength ? `maxlength="${opts.maxlength}"` : ''}
               ${opts.required ? 'required' : ''}
               class="w-full px-3 py-2 rounded-lg border border-border bg-bg text-text text-sm focus:outline-none focus:border-accent" />
      </label>
    `;
  },

  _fieldArea(name, label, value, opts) {
    opts = opts || {};
    const v = value == null ? '' : value;
    return `
      <label class="block">
        <span class="block text-sm font-semibold mb-1">${label}</span>
        <textarea name="${this._esc(name)}" rows="${opts.rows || 3}"
                  ${opts.placeholder ? `placeholder="${this._esc(opts.placeholder)}"` : ''}
                  class="w-full px-3 py-2 rounded-lg border border-border bg-bg text-text text-sm focus:outline-none focus:border-accent resize-y">${this._esc(String(v))}</textarea>
      </label>
    `;
  },

  _fieldSelect(name, label, value, options) {
    const opts = (options || []).map(o => `<option value="${this._esc(o.value)}" ${o.value === value ? 'selected' : ''}>${this._esc(o.label)}</option>`).join('');
    return `
      <label class="block">
        <span class="block text-sm font-semibold mb-1">${label}</span>
        <select name="${this._esc(name)}" class="w-full px-3 py-2 rounded-lg border border-border bg-bg text-text text-sm focus:outline-none focus:border-accent">
          ${opts}
        </select>
      </label>
    `;
  },

  _closeDetail() {
    const ov = document.getElementById('catalogue-detail-overlay');
    if (!ov) return;
    ov.style.opacity = '0';
    const card = ov.querySelector('.catalogue-detail-card');
    if (card) card.style.transform = 'scale(0.96) translateY(8px)';
    setTimeout(() => {
      const slot = document.getElementById('catalogue-detail-modal');
      if (slot) slot.innerHTML = '';
    }, 200);
  },

  // ===========================================================
  // PICKER — appelable depuis n'importe où (composeur mail, etc.)
  // ===========================================================
  /**
   * Ouvre un picker en overlay. callback(product) appelé quand l'utilisateur
   * choisit. callback(null) si annulé.
   */
  async pickProduct(callback) {
    await this.list();
    // Exclut les produits desactives du picker — ils ne doivent plus
    // apparaitre dans les mails que Jordan compose.
    const items = (this._items || []).filter(it => it.is_active !== false);

    let q = '';
    let cat = 'all';

    const ov = document.createElement('div');
    ov.id = 'catalogue-picker-overlay';
    ov.className = 'fixed inset-0 z-[220] flex items-start justify-center pt-[10vh] px-6 transition-opacity duration-200';
    ov.style.background = 'rgba(15,23,42,0.55)';
    ov.style.backdropFilter = 'blur(12px)';
    ov.style.opacity = '0';
    document.body.appendChild(ov);

    const close = (product) => {
      ov.style.opacity = '0';
      setTimeout(() => { ov.remove(); }, 180);
      if (typeof callback === 'function') callback(product || null);
    };

    const render = () => {
      const filtered = items.filter(it => {
        if (cat !== 'all' && it.category !== cat) return false;
        if (!q) return true;
        const needle = q.toLowerCase();
        return (it.name || '').toLowerCase().includes(needle)
            || (it.tagline || '').toLowerCase().includes(needle)
            || (it.id || '').toLowerCase().includes(needle);
      });

      const cats = ['all', ...this.CATEGORY_ORDER];
      const catButtons = cats.map(c => `
        <button data-pcat="${c}"
                class="px-3 py-1.5 rounded-lg text-[12px] font-semibold border transition-colors
                       ${cat === c ? 'border-accent text-accent bg-accent/10' : 'border-border text-text-muted hover:text-text'}">
          ${c === 'all' ? 'Tous' : this._esc(this.CATEGORY_LABELS[c] || c)}
        </button>
      `).join('');

      const tiles = filtered.map(it => {
        const visual = it.logo
          ? `<img src="${this._esc(it.logo)}" alt="" class="w-10 h-10 rounded-lg shrink-0" style="object-fit: contain;" />`
          : `<div class="w-10 h-10 rounded-lg shrink-0 flex items-center justify-center text-white font-bold"
                  style="background: ${this._esc(it.color || '#6366F1')};">${this._esc(it.initial || (it.name || '?')[0])}</div>`;
        return `
          <button data-pid="${this._esc(it.id)}"
                  class="text-left bg-surface-elevated rounded-xl p-3 border border-border
                         hover:border-accent transition-colors flex items-start gap-3">
            ${visual}
            <div class="flex-1 min-w-0">
              <div class="text-sm font-semibold leading-tight mb-0.5">${this._esc(it.name)}</div>
              <div class="text-xs text-text-muted line-clamp-2">${this._esc(it.tagline || '')}</div>
            </div>
          </button>
        `;
      }).join('');

      ov.innerHTML = `
        <div class="bg-surface rounded-3xl shadow-hero w-full max-w-[760px] max-h-[78vh]
                    flex flex-col overflow-hidden"
             style="border: 1px solid hsl(var(--border));">
          <div class="px-6 pt-5 pb-3 border-b border-border">
            <div class="flex items-center gap-3 mb-3">
              <svg class="w-5 h-5 text-text-muted shrink-0" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                <circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>
              </svg>
              <input id="catalogue-picker-search" type="text" autofocus
                     placeholder="Trouve un produit à insérer…"
                     class="flex-1 bg-transparent border-0 outline-none text-base"
                     value="${this._esc(q)}"/>
              <button id="catalogue-picker-close" class="text-text-muted hover:text-text text-2xl leading-none">×</button>
            </div>
            <div class="flex gap-2 flex-wrap">${catButtons}</div>
          </div>
          <div id="catalogue-picker-grid" class="flex-1 overflow-y-auto px-6 py-4 grid grid-cols-1 sm:grid-cols-2 gap-3">
            ${tiles || '<div class="text-text-muted text-sm py-8 text-center col-span-2">Aucun produit ne correspond.</div>'}
          </div>
        </div>
      `;

      requestAnimationFrame(() => { ov.style.opacity = '1'; });

      const input = document.getElementById('catalogue-picker-search');
      if (input) {
        input.focus();
        input.addEventListener('input', (e) => { q = e.target.value; render(); });
      }
      document.getElementById('catalogue-picker-close').onclick = () => close(null);
      ov.querySelectorAll('[data-pcat]').forEach(b => {
        b.onclick = () => { cat = b.dataset.pcat; render(); };
      });
      ov.querySelectorAll('[data-pid]').forEach(b => {
        b.onclick = () => {
          const product = items.find(x => x.id === b.dataset.pid);
          close(product || null);
        };
      });
    };

    render();
    ov.addEventListener('click', (e) => { if (e.target === ov) close(null); });
    document.addEventListener('keydown', function esc(e) {
      if (e.key === 'Escape') {
        document.removeEventListener('keydown', esc);
        close(null);
      }
    });
  },

  // ===========================================================
  // SNIPPETS — bloc texte/HTML prêt à coller dans un mail
  // ===========================================================
  snippetText(product) {
    if (!product) return '';
    const parts = [];
    parts.push(`👉 ${product.name}`);
    if (product.tagline) parts.push(product.tagline);
    if (product.buy_url) parts.push(product.buy_url);
    return parts.join('\n');
  },

  snippetHtml(product) {
    if (!product) return '';
    const name    = this._esc(product.name || '');
    const tagline = this._esc(product.tagline || '');
    const url     = this._esc(product.buy_url || '');
    const linkLabel = url ? this._esc(url.replace(/^https?:\/\//, '')) : '';
    return `
<div style="margin:14px 0;padding:14px 16px;border:1px solid #e5e7eb;border-radius:12px;background:#fafafa;font-family:Inter,Arial,sans-serif;">
  <div style="font-size:14px;font-weight:700;color:#111;margin-bottom:4px;">${name}</div>
  ${tagline ? `<div style="font-size:13px;color:#555;line-height:1.5;margin-bottom:8px;">${tagline}</div>` : ''}
  ${url ? `<a href="${url}" style="font-size:13px;color:#6366F1;text-decoration:none;font-weight:600;">${linkLabel} →</a>` : ''}
</div>`.trim();
  },

  // ---- utils ----
  _esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    }[c]));
  },
};
