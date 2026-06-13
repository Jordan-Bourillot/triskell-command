/* Vue Pixel Pros — pipeline d'inscription / construction / livraison.
 *
 * Workflow plus court que Lagriffe/RankUs/WoW (pas de validation humaine) :
 *   draft → paid → building → live (ou failed)
 *
 * UX choisie : Kanban à 4 colonnes (+ section "Échecs" séparée).
 * Tout doit être lisible au premier coup d'œil :
 *  - Funnel synthétique en haut avec les compteurs et les flèches qui
 *    racontent le pipeline en une ligne.
 *  - 4 colonnes Kanban, une couleur dominante par statut, une icône
 *    par statut, les cartes qui glissent visuellement de gauche à droite.
 *  - Chaque carte : grosse pastille initiale colorée + nom commercial gros
 *    + formule achetée en badge + temps écoulé en relatif ("il y a 2 h").
 *  - Au clic → panneau de détail à droite (slide-in) avec timeline,
 *    données du formulaire et toutes les actions.
 *  - Les commandes "Payé" en attente depuis +6h sont marquées URGENT
 *    (bordure dorée animée) pour qu'on les voie tout de suite.
 *
 * Données via :
 *   App.api.pixelpros_list_intakes({ status?, limit? })
 *   App.api.pixelpros_get_intake({ id })
 *   App.api.pixelpros_dispatch_build({ id })
 *   App.api.pixelpros_mark_failed({ id, reason? })
 *   App.api.pixelpros_resend_paid_mail({ id })
 *   App.api.pixelpros_resend_live_mail({ id })
 *   App.api.pixelpros_pipeline_state()
 */

const PixelPros = {
  state: {
    intakes: [],
    selectedId: null,
    detail: null,
    counts: null,
    loading: false,
    search: '',
    // Onglet actif : 'pipeline' (tunnel clients) ou 'stats' (fréquentation).
    tab: 'pipeline',
    // Mode auto/manuel pour les mails du pipeline (true = auto, défaut).
    // Sync depuis le backend au refresh.
    mailAuto: { paid: true, live: true },
  },

  // Colonnes Kanban, réparties en 2 groupes d'onglets :
  //  - group 'comm'     → onglet Contact (messages reçus + demandes de rappel)
  //  - group 'pipeline' → onglet Pipeline (le tunnel des sites : formulaire → en ligne)
  // Les échecs ont leur propre section en bas de l'onglet Pipeline.
  COLUMNS: [
    { status: 'contact',  label: 'Messages reçus',      icon: '✉️', accent: '#f59e0b', short: 'Messages',    group: 'comm' },
    { status: 'recall',   label: 'On vous rappelle',    icon: '☎️', accent: '#06b6d4', short: 'À rappeler',  group: 'comm' },
    { status: 'draft',            label: 'Commencé (pas payé)', icon: '📝', accent: '#94a3b8', short: 'Commencés',   group: 'pipeline' },
    { status: 'awaiting_content', label: 'Payé · à compléter',  icon: '⏳', accent: '#fb923c', short: 'À compléter', group: 'pipeline' },
    { status: 'paid',             label: 'Payé · à construire', icon: '💳', accent: '#facc15', short: 'À construire', group: 'pipeline' },
    { status: 'building', label: 'En construction',     icon: '🛠',  accent: '#818cf8', short: 'En cours',    group: 'pipeline' },
    { status: 'live',     label: 'En ligne',            icon: '✅', accent: '#22c55e', short: 'En ligne',     group: 'pipeline' },
  ],

  FORMULES: {
    base:        { label: 'Site seul',            price: '24,90 €/mois', color: '#94a3b8',
                   includes: ['Site web pro'] },
    base_domain: { label: 'Site + domaine',       price: '33,90 €/mois', color: '#0ea5e9',
                   includes: ['Site web pro', 'Nom de domaine + adresse mail pro'] },
    base_seo:    { label: 'Site + référencement', price: '59,80 €/mois', color: '#a855f7',
                   includes: ['Site web pro', 'Référencement Google + IA'] },
    base_all:    { label: 'Site + domaine + référencement', price: '68,80 €/mois', color: '#ec4899',
                   includes: ['Site web pro', 'Nom de domaine + adresse mail pro', 'Référencement Google + IA'] },
    combo:       { label: 'Pack TOUT-EN-UN',      price: '49,90 €/mois', color: '#facc15',
                   includes: ['Site web pro', 'Nom de domaine + adresse mail pro', 'Référencement Google + IA'] },
  },

  // Couleur dominante choisie par le client (valeur technique → libellé clair).
  COLOR_LABELS: {
    'electric-blue':   'Bleu électrique',
    'electric-yellow': 'Jaune solaire',
    'electric-green':  'Vert électrique',
    'warm-red':        'Rouge chaleur',
    'royal-purple':    'Violet royal',
    'warm-orange':     'Orange terre',
    'sober':           'Sobre / foncé',
    'surprise':        'Surprenez-moi',
  },

  // Réseaux sociaux : pour chacun, le client coche (social-X-on) et donne une URL (social-X-url).
  SOCIALS: [
    { key: 'instagram',   label: 'Instagram' },
    { key: 'facebook',    label: 'Facebook' },
    { key: 'linkedin',    label: 'LinkedIn' },
    { key: 'tiktok',      label: 'TikTok' },
    { key: 'youtube',     label: 'YouTube' },
    { key: 'whatsapp',    label: 'WhatsApp' },
    { key: 'tripadvisor', label: 'TripAdvisor' },
    { key: 'google',      label: 'Avis Google' },
  ],

  // Photos : les 4 « types » envoyés par le client, avec un max indicatif.
  PHOTO_GROUPS: [
    { kind: 'logo',       label: 'Logo',               max: 1  },
    { kind: 'hero-photo', label: 'Photo principale',   max: 3  },
    { kind: 'about-photo', label: 'Photo « à propos »', max: 2  },
    { kind: 'gallery',    label: 'Galerie',            max: 10 },
  ],

  // Rubriques du formulaire, dans l'ordre, avec les libellés humains.
  // key = case d'activation de la rubrique (null = rubrique toujours là).
  // fields = champs simples ; list = liste répétable (colonnes parallèles) ;
  // socials = bloc réseaux ; photoKind = type de photo rattaché à la rubrique.
  SECTIONS: [
    { key: null, title: 'Entreprise', icon: '🏢', fields: [
        { key: 'business-name', label: 'Nom de l’entreprise', type: 'text' },
        { key: 'business-type', label: 'Type d’activité',     type: 'text' },
        { key: 'tagline',       label: 'Phrase d’accroche',   type: 'text' },
        { key: 'city',          label: 'Ville',               type: 'text' },
        { key: 'zone',          label: 'Zone d’intervention', type: 'text' },
    ] },
    { key: null, title: 'Photo principale', icon: '🖼️', photoKind: 'hero-photo', fields: [
        { key: 'hero-headline', label: 'Grand titre sur la photo', type: 'long' },
    ] },
    { key: 'section-trust', title: 'Bandeau de confiance', icon: '📊',
      list: { addLabel: 'Ajouter un chiffre', cols: [
        { key: 'trust-num', label: 'Chiffre', type: 'text' },
        { key: 'trust-lbl', label: 'Texte',   type: 'text' },
      ] } },
    { key: 'section-about', title: 'À propos', icon: '👤', photoKind: 'about-photo', fields: [
        { key: 'about-title', label: 'Titre',                 type: 'text' },
        { key: 'about',       label: 'Texte de présentation', type: 'long' },
    ] },
    { key: 'section-services', title: 'Prestations', icon: '🧰',
      list: { addLabel: 'Ajouter une prestation', cols: [
        { key: 'service-name',  label: 'Nom',         type: 'text' },
        { key: 'service-desc',  label: 'Description', type: 'text' },
        { key: 'service-price', label: 'Prix',        type: 'text' },
      ] } },
    { key: 'section-gallery', title: 'Galerie photos', icon: '📸', photoKind: 'gallery' },
    { key: 'section-reviews', title: 'Avis clients', icon: '⭐',
      list: { addLabel: 'Ajouter un avis', cols: [
        { key: 'review-text',   label: 'Avis',   type: 'long' },
        { key: 'review-author', label: 'Auteur', type: 'text' },
      ] } },
    { key: 'section-zone', title: 'Où nous trouver', icon: '📍',
      fields: [
        { key: 'zone-text', label: 'Texte d’accroche',             type: 'long' },
        { key: 'zone-map',  label: 'Afficher la carte Google Maps', type: 'bool' },
      ],
      list: { addLabel: 'Ajouter une info pratique', cols: [
        { key: 'zone-key', label: 'Titre',  type: 'text' },
        { key: 'zone-val', label: 'Valeur', type: 'text' },
      ] } },
    { key: 'section-faq', title: 'Questions fréquentes', icon: '❓',
      list: { addLabel: 'Ajouter une question', cols: [
        { key: 'faq-q', label: 'Question', type: 'text' },
        { key: 'faq-a', label: 'Réponse',  type: 'long' },
      ] } },
    { key: null, title: 'Contact & horaires', icon: '☎️',
      fields: [
        { key: 'phone',             label: 'Téléphone',              type: 'text' },
        { key: 'email',             label: 'Adresse mail',           type: 'text' },
        { key: 'address',           label: 'Adresse',                type: 'text' },
        { key: 'contact-form',      label: 'Formulaire de contact',  type: 'bool' },
        { key: 'contact-phone-cta', label: 'Bouton « Appeler »',     type: 'bool' },
      ],
      list: { addLabel: 'Ajouter un horaire', cols: [
        { key: 'hours-day',  label: 'Jour(s)',  type: 'text' },
        { key: 'hours-time', label: 'Horaires', type: 'text' },
      ] } },
    { key: 'section-socials', title: 'Réseaux sociaux', icon: '🌐', socials: true },
    { key: 'section-style', title: 'Style visuel', icon: '🎨', photoKind: 'logo',
      fields: [
        { key: 'color', label: 'Couleur dominante',     type: 'color' },
        { key: 'extra', label: 'Demandes particulières', type: 'long' },
      ] },
    { key: null, title: 'Nom de domaine souhaité', icon: '🌍', onlyIf: 'domain-wanted', fields: [
        { key: 'domain-wanted', label: 'Domaine souhaité par le client', type: 'text' },
    ] },
  ],

  URGENT_THRESHOLD_H: 6,   // un draft "paid" depuis +6h sans build = urgent

  async render(container) {
    this._root = container;
    this._statsLoaded = false;   // les stats se chargent à la 1re ouverture de l'onglet
    container.innerHTML = `
      <section class="animate-slide-up">
        <div class="mb-6 flex items-end justify-between flex-wrap gap-3">
          <div>
            <div class="hero-kicker mb-2" style="color:hsl(var(--warning-text));">PIXEL PROS · PIPELINE</div>
            <h1 class="hero-title mb-2" style="font-size: 34px;">Tes sites client en un coup d'œil.</h1>
            <p class="hero-subtitle">Du formulaire reçu jusqu'au site en ligne — clique sur une carte pour les détails et les actions.</p>
          </div>
          <div class="flex items-center gap-2">
            <input id="pp-search" type="search" placeholder="Rechercher (nom, email, adresse du site)" />
            <button id="pp-refresh" class="btn btn-secondary">↻ Rafraîchir</button>
          </div>
        </div>

        <!-- ONGLETS : Pipeline (tunnel clients) / Contact (messages & rappels) / Statistiques -->
        <div class="pp-tabs" role="tablist">
          <button class="pp-tab" data-pp-tab="pipeline" role="tab">🚚 Pipeline</button>
          <button class="pp-tab" data-pp-tab="comm" role="tab">💬 Contact<span class="pp-tab-badge" id="pp-comm-badge" hidden></span></button>
          <button class="pp-tab" data-pp-tab="stats" role="tab">📊 Statistiques</button>
        </div>

        <!-- VUE PIPELINE : le tunnel des sites clients + les échecs -->
        <div id="pp-view-pipeline" class="pp-view">
          <!-- Construction automatique des sites payés (interrupteur) -->
          <div id="pp-autobuild"></div>
          <!-- Funnel synthétique -->
          <div id="pp-funnel" class="mb-7"></div>
          <!-- Kanban -->
          <div id="pp-kanban" class="pp-kanban"></div>
          <!-- Section Échecs (apparaît seulement s'il y a des fiches en échec) -->
          <div id="pp-failures" class="mt-7"></div>
          <!-- Mention discrète quand la liste atteint son plafond -->
          <div id="pp-limit-note" class="pp-limit-note" hidden>200 dernières commandes affichées</div>
        </div>

        <!-- VUE CONTACT : les gens qui ont écrit ou demandé à être rappelés -->
        <div id="pp-view-comm" class="pp-view" hidden>
          <p class="pp-comm-intro">Les personnes qui t'ont écrit ou demandé à être rappelées. Clique sur une carte pour lire le message et agir.</p>
          <div id="pp-comm-kanban" class="pp-kanban pp-kanban-comm"></div>
        </div>

        <!-- VUE STATISTIQUES : fréquentation du site vitrine -->
        <div id="pp-view-stats" class="pp-view" hidden>
          <div id="pp-stats"></div>
        </div>

        <!-- Panneau de détail : créé dans <body> par _ensureDetailEls() pour
             que son plein écran se cale sur la fenêtre entière, et non sur
             cette section animée (transform) qui le confinerait. -->
      </section>
    `;
    this._injectStyles();

    document.getElementById('pp-refresh').onclick = () => {
      // Le bouton rafraîchit la vue active : le pipeline, ou les stats.
      if (this.state.tab === 'stats') this._renderStats(this.state.statsPeriod);
      else this.refresh();
    };
    document.getElementById('pp-search').oninput = (e) => {
      this.state.search = e.target.value.toLowerCase().trim();
      this._renderKanban();
      this._renderFailures();
    };
    this._ensureDetailEls();

    // Échap ferme ce qui est ouvert (photo agrandie, fenêtre contact, éditeur
    // de mail, fiche de détail) — l'écouteur est retiré en quittant la vue.
    this._escHandler = (e) => { if (e.key === 'Escape') this._onEscape(); };
    document.addEventListener('keydown', this._escHandler);
    App.onViewCleanup(() => document.removeEventListener('keydown', this._escHandler));
    this._buildPoll = null;   // minuteur de suivi de fabrication (posé par _ensureAutoRefresh)

    // Onglets Pipeline / Statistiques — la préférence est retenue d'une fois sur l'autre.
    this._root.querySelectorAll('[data-pp-tab]').forEach(b => {
      b.onclick = () => this._setTab(b.dataset.ppTab);
    });
    let savedTab = 'pipeline';
    try { savedTab = localStorage.getItem('pp_tab') || 'pipeline'; } catch (e) {}
    this._setTab(savedTab);

    this._renderAutoBuildPanel();
    await this.refresh();
  },

  // Interrupteur « construction automatique » : quand il est sur AUTO, le
  // serveur lance le builder tout seul dès qu'un paiement arrive (scan
  // toutes les 5 min). OFF = comportement historique, Jordan clique.
  async _renderAutoBuildPanel() {
    const host = document.getElementById('pp-autobuild');
    if (!host || !App.api || typeof App.api.pixelpros_auto_build_get !== 'function') return;
    let enabled = false;
    try {
      const res = await App.api.pixelpros_auto_build_get();
      if (!res || !res.ok) return;
      enabled = !!res.enabled;
    } catch (e) { return; }

    const paint = (on, busy) => {
      host.innerHTML = `
        <div class="pp-autobuild ${on ? 'is-on' : ''}">
          <div>
            <div class="pp-autobuild-title">${on ? '🟢' : '⚪'} Construction automatique après paiement</div>
            <div class="pp-autobuild-desc">
              ${on
                ? 'Dès qu’un client paie, son site part en construction tout seul (vérification toutes les 5 min). Tu es prévenu au lancement et à la mise en ligne.'
                : 'Aujourd’hui, un site payé attend ton clic « Lancer la construction ». Active pour qu’il parte tout seul dès le paiement — tu restes prévenu à chaque étape.'}
            </div>
          </div>
          <button class="btn ${on ? 'btn-secondary' : 'btn-primary'}" data-act="pp-ab-toggle" ${busy ? 'disabled' : ''}>
            ${busy ? '…' : (on ? 'Couper' : 'Activer')}
          </button>
        </div>`;
      host.querySelector('[data-act="pp-ab-toggle"]').onclick = async () => {
        const next = !on;
        if (next) {
          const ok = await Dialog.confirm(
            'Dès qu’un paiement arrive, le site du client sera construit et mis ' +
            'en ligne sans action de ta part (2 constructions max en parallèle, ' +
            'une seule tentative automatique par commande).\n\n' +
            'Tu seras prévenu au lancement, à la mise en ligne, et si quelque ' +
            'chose échoue.',
            { title: 'Activer la construction automatique ?', okLabel: 'Activer',
              cancelLabel: 'Annuler', danger: true });
          if (!ok) return;
        }
        paint(on, true);
        try {
          const r = await App.api.pixelpros_auto_build_set({ enabled: next });
          if (r && r.ok) {
            paint(!!r.enabled, false);
            this._toast(r.enabled
              ? '🟢 Construction automatique activée'
              : 'Construction automatique coupée — tout repasse par ton clic');
          } else {
            paint(on, false);
            this._failToast('Le réglage n’a pas pu être enregistré.', r);
          }
        } catch (e) {
          paint(on, false);
          console.warn('pixelpros auto_build_set', e);
          this._toast('Le réglage n’a pas pu être enregistré — réessaie dans un instant.', true);
        }
      };
    };
    paint(enabled, false);
  },

  _injectStyles() {
    if (document.getElementById('pp-styles')) return;
    const s = document.createElement('style');
    s.id = 'pp-styles';
    s.textContent = `
      /* Champ de recherche du haut de page (largeur souple pour mobile) */
      #pp-search { padding:9px 14px; border-radius:8px; background:hsl(var(--surface)); border:1px solid hsl(var(--border)); color:hsl(var(--text)); font-size:13px; width:240px; max-width:100%; }
      /* Mention discrète sous le Kanban quand le plafond de 200 est atteint */
      .pp-limit-note { margin-top:12px; text-align:center; font-size:11px; color:hsl(var(--text-muted)); }
      /* État d'erreur de chargement (liste / stats) avec bouton Réessayer */
      .pp-load-error { display:flex; flex-direction:column; align-items:center; gap:10px; padding:28px 16px; text-align:center; background:hsl(var(--danger) / .06); border:1px solid hsl(var(--danger) / .25); border-radius:14px; color:hsl(var(--text-secondary)); font-size:13px; }
      /* Détail technique replié sous un message d'erreur humain */
      .pp-error-detail { margin-top:8px; }
      .pp-error-detail summary { cursor:pointer; font-size:12px; color:hsl(var(--text-muted)); }
      .pp-error-detail pre { margin:8px 0 0; padding:10px; background:hsl(var(--bg)); border-radius:8px; font-size:11px; color:hsl(var(--text-secondary)); overflow:auto; max-height:200px; white-space:pre-wrap; word-break:break-word; }

      /* === CONSTRUCTION AUTOMATIQUE (interrupteur) === */
      .pp-autobuild { display:flex; align-items:center; justify-content:space-between; gap:20px; padding:14px 18px; margin-bottom:18px; border:1px solid hsl(var(--border)); border-radius:12px; background:hsl(var(--surface)); }
      .pp-autobuild.is-on { border-color:hsl(var(--success) / .45); background:hsl(var(--success) / .06); }
      .pp-autobuild-title { font-weight:700; font-size:14px; margin-bottom:3px; color:hsl(var(--text)); }
      .pp-autobuild-desc { font-size:13px; color:hsl(var(--text-muted)); max-width:640px; }
      .pp-autobuild .btn { flex-shrink:0; }

      /* === ONGLETS Pipeline / Statistiques === */
      .pp-tabs { display:flex; gap:4px; margin-bottom:22px; border-bottom:1px solid hsl(var(--border)); }
      .pp-tab { appearance:none; -webkit-appearance:none; background:transparent; border:none; border-bottom:2px solid transparent; color:hsl(var(--text-muted)); font-size:14px; font-weight:800; padding:11px 18px; cursor:pointer; transition:color .15s, border-color .15s, background .15s; margin-bottom:-1px; border-radius:8px 8px 0 0; }
      .pp-tab:hover { color:hsl(var(--text)); background:hsl(var(--text-muted) / .06); }
      .pp-tab.is-active { color:hsl(var(--warning-text)); border-bottom-color:#facc15; }
      .pp-tab-badge { display:inline-flex; align-items:center; justify-content:center; min-width:18px; height:18px; padding:0 5px; margin-left:7px; border-radius:999px; background:#f59e0b; color:#0b0d1a; font-size:11px; font-weight:900; line-height:1; vertical-align:middle; }
      /* La pastille vide doit vraiment disparaître (hidden l'emporte sur le display ci-dessus) */
      .pp-tab-badge[hidden] { display:none !important; }
      .pp-view { animation: pp-fadein .2s ease; }
      .pp-comm-intro { color:hsl(var(--text-muted)); font-size:13.5px; line-height:1.5; margin:0 0 18px; }

      /* === FUNNEL synthétique === */
      .pp-funnel { display:flex; align-items:stretch; gap:0; flex-wrap:wrap; background:hsl(var(--surface)); border:1px solid hsl(var(--border)); border-radius:14px; padding:14px; }
      .pp-funnel-step { flex:1; min-width:120px; padding:10px 14px; display:flex; flex-direction:column; align-items:center; gap:4px; position:relative; }
      .pp-funnel-icon { font-size:24px; line-height:1; margin-bottom:2px; }
      .pp-funnel-n { font-size:24px; font-weight:800; line-height:1; }
      .pp-funnel-l { font-size:11px; font-weight:700; letter-spacing:.06em; text-transform:uppercase; color:hsl(var(--text-muted)); margin-top:2px; }
      .pp-funnel-step.alert .pp-funnel-n { color:hsl(var(--warning-text)); }
      .pp-funnel-step.alert .pp-funnel-l { color:hsl(var(--warning-text)); }
      .pp-funnel-step.success .pp-funnel-n { color:hsl(var(--success-text)); }
      .pp-funnel-step.success .pp-funnel-l { color:hsl(var(--success-text)); }

      /* Marqueurs ✉️ entre étapes : mails envoyés automatiquement au client */
      .pp-funnel-gap { width:20px; display:flex; align-items:center; justify-content:center; color:hsl(var(--text-muted) / .7); font-size:22px; font-weight:300; }
      .pp-funnel-gap::after { content:'›'; }
      .pp-mail-marker {
        display:flex; flex-direction:column; align-items:center; gap:2px;
        padding:8px 10px; margin:0 4px;
        background: color-mix(in srgb, var(--mc) 12%, transparent);
        border: 1px dashed color-mix(in srgb, var(--mc) 55%, transparent);
        border-radius: 10px; cursor:pointer; min-width:90px;
        color:hsl(var(--text-secondary)); font: inherit;
        transition: background .15s, transform .15s, border-color .15s;
        position:relative;
      }
      .pp-mail-marker:hover {
        background: color-mix(in srgb, var(--mc) 22%, transparent);
        border-color: var(--mc);
        transform: translateY(-1px);
      }
      .pp-mail-marker .pp-mail-ico { font-size:18px; line-height:1; }
      .pp-mail-marker .pp-mail-lbl { font-size:11px; font-weight:800; letter-spacing:.04em; text-transform:uppercase; color: var(--mc); }
      .pp-mail-marker .pp-mail-edit { font-size:11px; color:hsl(var(--text-muted)); opacity:0; transition:opacity .15s; }
      .pp-mail-marker:hover .pp-mail-edit { opacity:1; }

      /* Wrapper du marqueur mail + son toggle Auto/Manuel */
      .pp-mail-marker-wrap { display:flex; flex-direction:column; align-items:stretch; gap:6px; margin:0 4px; min-width:96px; }
      .pp-mail-marker-wrap .pp-mail-marker { margin:0; }
      .pp-mail-marker-wrap.is-manual .pp-mail-marker {
        opacity: 0.55;
        filter: grayscale(0.4);
      }
      .pp-mail-marker-wrap.is-manual .pp-mail-marker:hover {
        opacity: 1;
        filter: none;
      }
      .pp-mail-toggle {
        font: inherit;
        font-size: 11px; font-weight: 800;
        letter-spacing: .04em;
        padding: 4px 8px;
        border-radius: 6px;
        cursor: pointer;
        border: 1px solid transparent;
        transition: background .15s, border-color .15s, color .15s, transform .1s;
        text-align: center;
        line-height: 1.2;
      }
      .pp-mail-toggle.is-auto {
        background: hsl(var(--success) / .12);
        border-color: hsl(var(--success) / .35);
        color: hsl(var(--success-text));
      }
      .pp-mail-toggle.is-auto:hover {
        background: hsl(var(--success) / .22);
        border-color: hsl(var(--success) / .55);
      }
      .pp-mail-toggle.is-manual {
        background: hsl(var(--warning) / .14);
        border-color: hsl(var(--warning) / .4);
        color: hsl(var(--warning-text));
      }
      .pp-mail-toggle.is-manual:hover {
        background: hsl(var(--warning) / .24);
        border-color: hsl(var(--warning) / .6);
      }
      .pp-mail-toggle:active { transform: translateY(1px); }
      .pp-mail-toggle:disabled { opacity: .5; cursor: wait; }

      /* Édition du contact (mail / téléphone) depuis la fiche intake */
      .pp-detail-sub { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
      .pp-edit-contact-btn {
        background:hsl(var(--text-muted) / .12);
        border:1px solid hsl(var(--border));
        color:hsl(var(--text-muted));
        width:26px; height:26px;
        border-radius:6px;
        font-size:13px;
        cursor:pointer;
        display:inline-flex; align-items:center; justify-content:center;
        transition: background .15s, color .15s, border-color .15s;
      }
      .pp-edit-contact-btn:hover {
        background:hsl(var(--warning) / .18);
        border-color: hsl(var(--warning) / .5);
        color:hsl(var(--warning-text));
      }
      .pp-edit-overlay {
        position:fixed; inset:0; z-index:1100;
        background:hsl(var(--bg) / .6);
        backdrop-filter: blur(4px); -webkit-backdrop-filter: blur(4px);
        display:flex; align-items:center; justify-content:center;
        padding:20px;
        animation: pp-fadein .15s ease;
      }
      .pp-edit-dialog {
        background:hsl(var(--surface));
        border:1px solid hsl(var(--border));
        border-radius:14px;
        padding:24px;
        width:100%; max-width:420px;
        box-shadow: 0 20px 60px rgba(0,0,0,.5);
        animation: pp-slideup .2s ease;
      }
      @keyframes pp-slideup { from { transform:translateY(10px); opacity:0; } to { transform:translateY(0); opacity:1; } }
      .pp-edit-title { font-size:16px; font-weight:800; color:hsl(var(--text)); margin-bottom:16px; }
      .pp-edit-label { display:block; font-size:12px; font-weight:600; color:hsl(var(--text-muted)); margin-bottom:14px; }
      .pp-edit-hint { font-weight:400; color:hsl(var(--text-muted)); }
      .pp-edit-input {
        display:block; width:100%;
        margin-top:6px;
        padding:10px 12px;
        background:hsl(var(--bg));
        border:1px solid hsl(var(--border));
        border-radius:8px;
        color:hsl(var(--text));
        font-size:14px;
      }
      .pp-edit-input:focus { outline:none; border-color:hsl(var(--warning)); }
      .pp-edit-actions { display:flex; justify-content:flex-end; gap:8px; margin-top:18px; }

      /* Champs de l'éditeur de mail */
      .pp-mail-input, .pp-mail-textarea {
        width:100%; padding:10px 12px; border-radius:8px;
        background:hsl(var(--bg)); border:1px solid hsl(var(--border));
        color:hsl(var(--text)); font-size:13px; font-family: inherit; line-height:1.5;
        box-sizing:border-box;
      }
      .pp-mail-input:focus, .pp-mail-textarea:focus { outline:none; border-color:hsl(var(--warning)); }
      .pp-mail-textarea { resize:vertical; }
      .pp-mail-textarea-code { font-family: ui-monospace, 'SF Mono', Consolas, monospace; font-size:11.5px; }
      /* Fond blanc volontaire : les mails HTML sont conçus sur fond blanc, quel que soit le thème. */
      .pp-mail-preview { width:100%; min-height:340px; border-radius:8px; background:#fff; border:1px solid hsl(var(--border)); margin-top:10px; }
      .pp-mail-vars { font-size:12px; color:hsl(var(--text-muted)); line-height:1.9; }
      .pp-mail-vars code { background:hsl(var(--bg)); color:hsl(var(--warning-text)); padding:2px 6px; border-radius:4px; font-size:11px; margin-right:8px; }
      .pp-action-btn:disabled { opacity:0.4; cursor:not-allowed; }
      /* Sur mobile, 16px évite le zoom automatique d'iOS à la prise de focus */
      @media (max-width:640px) {
        #pp-search, .pp-mail-input, .pp-mail-textarea, .pp-edit-input { font-size:16px; }
      }

      /* === KANBAN === */
      .pp-kanban { display:grid; grid-template-columns: repeat(4, minmax(220px, 1fr)); gap:14px; }
      .pp-stats-head { display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:10px; margin-bottom:14px; }
      .pp-stats-title { font-size:16px; font-weight:800; color:hsl(var(--text)); margin:0; }
      .pp-stats-periods { display:flex; gap:6px; }
      .pp-stat-period { padding:6px 12px; border-radius:999px; border:1px solid hsl(var(--border)); background:transparent; color:hsl(var(--text-muted)); font-size:12.5px; font-weight:700; cursor:pointer; transition:all .15s; }
      .pp-stat-period:hover { color:hsl(var(--text)); }
      .pp-stat-period.is-active { background:#facc15; color:#0b0d1a; border-color:#facc15; }
      .pp-stats-grid { display:grid; grid-template-columns: repeat(5, 1fr); gap:12px; margin-bottom:16px; }
      @media (max-width:1100px){ .pp-stats-grid { grid-template-columns: repeat(3, 1fr); } }
      @media (max-width:640px){ .pp-stats-grid { grid-template-columns: repeat(2, 1fr); } }
      .pp-stat-card { background:hsl(var(--surface)); border:1px solid hsl(var(--border)); border-radius:12px; padding:16px 14px; text-align:center; }
      .pp-stat-ico { font-size:20px; margin-bottom:6px; }
      .pp-stat-val { font-size:26px; font-weight:900; color:hsl(var(--text)); line-height:1.1; }
      .pp-stat-lbl { font-size:11.5px; color:hsl(var(--text-muted)); margin-top:5px; font-weight:600; }
      .pp-stats-sub { font-size:12.5px; color:hsl(var(--text-muted)); margin:3px 0 0; }
      .pp-stat-top { background:hsl(var(--surface)); border:1px solid hsl(var(--border)); border-radius:12px; padding:14px 16px; }
      .pp-stat-top-head { display:flex; justify-content:space-between; align-items:baseline; margin-bottom:10px; }
      .pp-stat-top-title { font-size:13px; font-weight:800; color:hsl(var(--text)); }
      .pp-stat-top-coltitle { font-size:11px; font-weight:700; color:hsl(var(--text-muted)); text-transform:uppercase; letter-spacing:.04em; }
      .pp-stat-top-list { list-style:none; margin:0; padding:0; }
      .pp-stat-top-row { display:grid; grid-template-columns: minmax(140px,1.4fr) 2fr auto; align-items:center; gap:14px; padding:9px 0; border-bottom:1px solid hsl(var(--text-muted) / .1); }
      .pp-stat-top-row:last-child { border-bottom:none; }
      .pp-stat-top-info { display:flex; flex-direction:column; min-width:0; }
      .pp-stat-top-name { color:hsl(var(--text)); font-weight:700; font-size:13.5px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
      .pp-stat-top-path { color:hsl(var(--text-muted)); font-size:11px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
      .pp-stat-top-barwrap { background:hsl(var(--text-muted) / .12); border-radius:999px; height:8px; overflow:hidden; }
      .pp-stat-top-bar { height:100%; border-radius:999px; background:linear-gradient(90deg,#facc15,#f59e0b); }
      .pp-stat-top-views { color:hsl(var(--warning-text)); font-weight:800; font-size:13px; white-space:nowrap; min-width:62px; text-align:right; }
      .pp-stat-top-empty { color:hsl(var(--text-muted)); padding:8px 0; }
      @media (max-width:640px){ .pp-stat-top-row { grid-template-columns: 1fr auto; } .pp-stat-top-barwrap { display:none; } }
      .pp-stats-2col { display:grid; grid-template-columns: 1fr 1fr; gap:14px; margin-top:14px; }
      @media (max-width:900px){ .pp-stats-2col { grid-template-columns: 1fr; } }
      .pp-stat-device-bar { display:flex; height:14px; border-radius:999px; overflow:hidden; margin:8px 0 14px; background:hsl(var(--text-muted) / .12); }
      .pp-stat-device-mob { background:#38bdf8; }
      .pp-stat-device-ord { background:#a78bfa; }
      .pp-stat-device-legend { display:flex; flex-direction:column; gap:7px; font-size:13px; color:hsl(var(--text-secondary)); }
      .pp-stat-device-legend > span { display:flex; align-items:center; gap:8px; }
      .pp-dot { width:10px; height:10px; border-radius:50%; display:inline-block; }
      .pp-dot-mob { background:#38bdf8; }
      .pp-dot-ord { background:#a78bfa; }
      @media (max-width: 1100px) { .pp-kanban { grid-template-columns: repeat(2, 1fr); } }
      @media (max-width: 640px)  { .pp-kanban { grid-template-columns: 1fr; } }

      /* Contact : 2 colonnes (messages + rappels), pleine largeur sur petit écran. */
      .pp-kanban-comm { grid-template-columns: repeat(2, minmax(240px, 420px)); }
      @media (max-width: 640px) { .pp-kanban-comm { grid-template-columns: 1fr; } }

      .pp-col { background:hsl(var(--surface)); border:1px solid hsl(var(--border)); border-radius:14px; padding:14px; display:flex; flex-direction:column; gap:10px; min-height:200px; }
      .pp-col-head { display:flex; align-items:center; justify-content:space-between; padding-bottom:10px; border-bottom:2px solid var(--col-accent, hsl(var(--text-muted))); }
      .pp-col-title { display:flex; align-items:center; gap:8px; font-size:13px; font-weight:800; color:var(--col-accent, hsl(var(--text-muted))); text-transform:uppercase; letter-spacing:.04em; }
      .pp-col-title .ico { font-size:16px; }
      .pp-col-count { background:hsl(var(--text) / .06); color:hsl(var(--text-secondary)); padding:2px 10px; border-radius:999px; font-size:11px; font-weight:800; }
      .pp-col-body { display:flex; flex-direction:column; gap:8px; }
      .pp-col-empty { color:hsl(var(--text-muted)); font-size:12px; font-style:italic; text-align:center; padding:24px 8px; }

      /* === CARTE === */
      .pp-card { background:hsl(var(--surface-elevated)); border:1px solid hsl(var(--border)); border-radius:10px; padding:11px; display:flex; align-items:center; gap:11px; cursor:pointer; transition:border-color .15s, transform .15s, background .15s; position:relative; }
      .pp-card:hover { border-color:var(--col-accent, hsl(var(--warning))); background:hsl(var(--border) / .35); transform:translateX(2px); }
      .pp-card:focus-visible { outline:2px solid hsl(var(--accent)); outline-offset:2px; }
      .pp-card.urgent { border-color:#facc15; box-shadow: 0 0 0 1px #facc15, 0 0 12px rgba(250,204,21,.3); animation: pp-pulse 2s ease-in-out infinite; }
      .pp-card.selected { border-color:#facc15; background:hsl(var(--warning) / .05); }
      @keyframes pp-pulse { 0%, 100% { box-shadow: 0 0 0 1px #facc15, 0 0 12px rgba(250,204,21,.3); } 50% { box-shadow: 0 0 0 1px #facc15, 0 0 20px rgba(250,204,21,.6); } }

      /* Texte sombre volontaire : le fond de l'avatar est toujours une couleur
         pastel claire de la palette, dans les 3 thèmes. */
      .pp-avatar { width:38px; height:38px; border-radius:9px; display:flex; align-items:center; justify-content:center; font-weight:800; font-size:16px; color:#0f172a; flex-shrink:0; text-transform:uppercase; }
      .pp-card-body { flex:1; min-width:0; }
      .pp-card-name { font-weight:700; font-size:13.5px; color:hsl(var(--text)); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
      .pp-card-meta { font-size:11px; color:hsl(var(--text-muted)); margin-top:2px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
      .pp-card-badges { display:flex; align-items:center; gap:6px; margin-top:6px; flex-wrap:wrap; }
      .pp-formule-badge { padding:2px 7px; border-radius:6px; font-size:11px; font-weight:700; }
      .pp-card-time { font-size:11px; color:hsl(var(--text-muted)); }
      .pp-urgent-badge { background:#facc15; color:#0f172a; padding:1px 6px; border-radius:4px; font-size:11px; font-weight:800; letter-spacing:.04em; }

      /* Petit bouton corbeille en haut-droite de la carte, visible au survol.
         Permet de supprimer un formulaire sans avoir à ouvrir le détail. */
      .pp-card-trash { position:absolute; top:6px; right:6px; width:26px; height:26px; border-radius:6px; background:hsl(var(--danger) / .15); color:hsl(var(--danger-text)); border:none; cursor:pointer; font-size:13px; display:flex; align-items:center; justify-content:center; opacity:0; transition:opacity .15s, background .15s; }
      .pp-card:hover .pp-card-trash, .pp-card:focus-within .pp-card-trash { opacity:1; }
      .pp-card-trash:hover { background:hsl(var(--danger)); color:#fff; }

      /* === SECTION ÉCHECS === */
      .pp-failures { background:hsl(var(--danger) / .06); border:1px solid hsl(var(--danger) / .25); border-radius:14px; padding:14px; }
      .pp-failures-title { display:flex; align-items:center; gap:8px; font-size:13px; font-weight:800; color:hsl(var(--danger-text)); text-transform:uppercase; letter-spacing:.04em; margin-bottom:10px; }
      .pp-failures-grid { display:grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap:10px; }
      .pp-failures-empty { display:none; }

      /* === PANNEAU DE DÉTAIL (slide-in droite) === */
      .pp-detail-overlay { position:fixed; inset:0; background:hsl(var(--bg) / .65); z-index:998; backdrop-filter: blur(3px); -webkit-backdrop-filter: blur(3px); animation: pp-fadein .2s ease; }
      /* Fond opaque solide : les tokens HSL sont opaques, le panneau suit les 3 thèmes. */
      .pp-detail-panel { position:fixed; top:0; right:0; bottom:0; width:min(1120px, 94vw); background:hsl(var(--surface)); border-left:1px solid hsl(var(--border)); z-index:1000; overflow-y:auto; padding:24px; box-shadow:-12px 0 30px rgba(0,0,0,.5); animation: pp-slidein .25s cubic-bezier(.2,.7,.3,1); color:hsl(var(--text)); }
      @keyframes pp-fadein { from { opacity:0; } to { opacity:1; } }
      @keyframes pp-slidein { from { transform:translateX(100%); } to { transform:translateX(0); } }

      /* sticky + float : la croix reste visible quand on fait défiler la fiche */
      .pp-detail-close { position:sticky; top:0; float:right; z-index:10; width:36px; height:36px; border-radius:50%; background:hsl(var(--text-muted) / .15); color:hsl(var(--text-secondary)); border:none; cursor:pointer; font-size:20px; display:flex; align-items:center; justify-content:center; }
      .pp-detail-close:hover { background:hsl(var(--danger) / .2); color:hsl(var(--text)); }
      .pp-detail-head { display:flex; align-items:flex-start; gap:14px; margin-bottom:18px; padding-right:50px; }
      .pp-detail-head .pp-avatar { width:54px; height:54px; font-size:22px; border-radius:12px; }
      .pp-detail-name { font-size:22px; font-weight:800; color:hsl(var(--text)); line-height:1.2; }
      .pp-detail-sub { font-size:13px; color:hsl(var(--text-muted)); margin-top:4px; }
      .pp-detail-pill { display:inline-block; padding:3px 11px; border-radius:999px; font-size:11px; font-weight:700; letter-spacing:.02em; margin-top:8px; }

      .pp-detail-section { margin-bottom:20px; }
      .pp-detail-section-title { font-size:11px; font-weight:800; letter-spacing:.08em; color:hsl(var(--text-muted)); text-transform:uppercase; margin-bottom:10px; }

      .pp-actions { display:flex; flex-wrap:wrap; gap:8px; }
      .pp-action-btn { padding:9px 14px; border-radius:8px; font-size:13px; font-weight:700; cursor:pointer; border:1px solid transparent; }
      .pp-action-btn.primary { background:#facc15; color:#0f172a; }
      .pp-action-btn.secondary { background:hsl(var(--text-muted) / .12); color:hsl(var(--text-secondary)); border-color:hsl(var(--text-muted) / .25); }
      .pp-action-btn.danger { background:hsl(var(--danger) / .12); color:hsl(var(--danger-text)); border-color:hsl(var(--danger) / .3); }
      .pp-action-btn:hover { filter:brightness(1.12); }

      .pp-detail-link { color:hsl(var(--warning-text)); font-weight:700; text-decoration:underline; }
      .pp-detail-link:hover { color:hsl(var(--warning)); }

      .pp-error-box { background:hsl(var(--danger) / .1); border:1px solid hsl(var(--danger) / .3); border-radius:8px; padding:11px 14px; color:hsl(var(--danger-text)); font-size:13px; }

      .pp-timeline { border-left:2px solid hsl(var(--border)); padding-left:14px; margin-left:6px; }
      .pp-timeline-event { padding:8px 0; }
      .pp-timeline-event .ts { font-size:11px; color:hsl(var(--text-muted)); font-variant-numeric:tabular-nums; margin-bottom:2px; }
      .pp-timeline-event .lbl { font-size:13px; color:hsl(var(--text-secondary)); }
      .pp-timeline-event.current .lbl { font-weight:700; color:hsl(var(--warning-text)); }

      .pp-data-toggle { background:hsl(var(--text-muted) / .08); border:1px solid hsl(var(--border)); border-radius:8px; padding:8px 12px; cursor:pointer; font-size:12px; color:hsl(var(--text-muted)); user-select:none; }
      .pp-data-toggle:hover { color:hsl(var(--text-secondary)); }
      .pp-data-pre { margin-top:10px; padding:12px; background:hsl(var(--bg)); border-radius:8px; font-size:11px; color:hsl(var(--text-secondary)); overflow:auto; max-height:340px; }

      /* === BLOC PAIEMENT === */
      .pp-pay-status { display:flex; align-items:center; gap:12px; padding:12px 14px; border-radius:10px; margin-bottom:10px; }
      .pp-pay-status.ok { background:hsl(var(--success) / .1); border:1px solid hsl(var(--success) / .35); }
      .pp-pay-status.wait { background:hsl(var(--warning) / .08); border:1px solid hsl(var(--warning) / .3); }
      .pp-pay-ico { font-size:26px; line-height:1; }
      .pp-pay-status-main { font-size:15px; font-weight:800; color:hsl(var(--text)); }
      .pp-pay-status.ok .pp-pay-status-main { color:hsl(var(--success-text)); }
      .pp-pay-status.wait .pp-pay-status-main { color:hsl(var(--warning-text)); }
      .pp-pay-status-sub { font-size:12px; color:hsl(var(--text-muted)); margin-top:1px; }
      .pp-pay-formule { border:1px solid hsl(var(--border)); border-left:4px solid var(--fc, hsl(var(--text-muted))); border-radius:10px; padding:12px 14px; background:hsl(var(--text) / .02); }
      .pp-pay-formule-head { display:flex; align-items:baseline; justify-content:space-between; gap:10px; flex-wrap:wrap; }
      .pp-pay-formule-name { font-size:15px; font-weight:800; color:hsl(var(--text)); }
      .pp-pay-formule-price { font-size:15px; font-weight:800; color:var(--fc, hsl(var(--text-secondary))); white-space:nowrap; }
      .pp-pay-includes { list-style:none; margin:8px 0 0; padding:0; color:hsl(var(--text-secondary)); font-size:12.5px; line-height:1.8; }
      .pp-pay-includes li { position:relative; padding-left:20px; }
      .pp-pay-includes li::before { content:'✓'; position:absolute; left:2px; color:hsl(var(--success-text)); font-weight:800; }

      /* === RUBRIQUES DU FORMULAIRE === */
      .pp-form-hint { font-size:12px; color:hsl(var(--text-muted)); background:hsl(var(--text-muted) / .07); border:1px solid hsl(var(--border)); border-radius:8px; padding:8px 11px; margin-bottom:12px; line-height:1.5; }
      .pp-rub { border:1px solid hsl(var(--border)); border-radius:10px; margin-bottom:10px; overflow:hidden; }
      .pp-rub.off { opacity:.6; }
      .pp-rub-head { display:flex; align-items:center; justify-content:space-between; gap:10px; padding:10px 12px; background:hsl(var(--text-muted) / .05); border-bottom:1px solid hsl(var(--border)); }
      .pp-rub.off .pp-rub-head { border-bottom:none; }
      .pp-rub-title { font-size:13.5px; font-weight:800; color:hsl(var(--text)); }
      .pp-rub-toggle { font-size:11px; font-weight:700; padding:4px 9px; border-radius:999px; cursor:pointer; border:1px solid transparent; }
      .pp-rub-toggle.on { background:hsl(var(--success) / .12); border-color:hsl(var(--success) / .35); color:hsl(var(--success-text)); }
      .pp-rub-toggle.off { background:hsl(var(--text-muted) / .12); border-color:hsl(var(--text-muted) / .3); color:hsl(var(--text-muted)); }
      .pp-rub-toggle:hover { filter:brightness(1.15); }
      .pp-rub-body { padding:6px 12px 12px; }
      .pp-rub-off-note { padding:10px 12px; font-size:12px; color:hsl(var(--text-muted)); font-style:italic; }
      .pp-rub-photonote { font-size:11.5px; color:hsl(var(--text-muted)); margin-top:8px; }

      /* Champ « libellé : valeur » */
      .pp-field { display:flex; gap:12px; align-items:flex-start; padding:7px 0; border-bottom:1px dashed hsl(var(--text-muted) / .12); }
      .pp-field:last-child { border-bottom:none; }
      .pp-field-label { flex:0 0 38%; max-width:210px; font-size:12px; font-weight:700; color:hsl(var(--text-muted)); padding-top:2px; }
      .pp-field-val { flex:1; min-width:0; display:flex; align-items:flex-start; gap:8px; font-size:13.5px; color:hsl(var(--text)); }
      .pp-field-text { flex:1; word-break:break-word; }
      .pp-field-text.multiline { white-space:pre-wrap; }
      .pp-empty { color:hsl(var(--text-muted)); font-style:italic; font-size:12.5px; }
      .pp-bool { font-weight:700; }
      .pp-bool.on { color:hsl(var(--success-text)); }
      .pp-bool.off { color:hsl(var(--text-muted)); }
      .pp-mini-btn { flex-shrink:0; background:hsl(var(--text-muted) / .12); border:1px solid hsl(var(--border)); color:hsl(var(--text-muted)); border-radius:6px; padding:3px 8px; font-size:11.5px; cursor:pointer; }
      .pp-mini-btn:hover { background:hsl(var(--warning) / .16); border-color:hsl(var(--warning) / .45); color:hsl(var(--warning-text)); }
      .pp-mini-btn.danger:hover { background:hsl(var(--danger) / .18); border-color:hsl(var(--danger) / .45); color:hsl(var(--danger-text)); }
      .pp-field.editing { flex-direction:column; gap:6px; }
      .pp-field-edit { width:100%; }
      .pp-edit-row-actions { display:flex; gap:8px; margin-top:8px; }

      /* Listes (services, avis, horaires…) */
      .pp-list { margin-top:4px; }
      .pp-list-row { display:flex; flex-wrap:wrap; gap:6px 16px; padding:8px 10px; border:1px solid hsl(var(--border)); border-radius:8px; margin-bottom:6px; background:hsl(var(--text) / .015); }
      .pp-list-cell { display:flex; flex-direction:column; gap:1px; min-width:0; }
      .pp-list-cell-lbl { font-size:11px; font-weight:700; letter-spacing:.04em; text-transform:uppercase; color:hsl(var(--text-muted)); }
      .pp-list-cell-val { font-size:13px; color:hsl(var(--text)); word-break:break-word; }
      .pp-list-cell-val.multiline { white-space:pre-wrap; }
      .pp-list-edit-row { display:flex; gap:6px; align-items:flex-start; margin-bottom:6px; }
      .pp-list-edit-row > input, .pp-list-edit-row > textarea { flex:1; min-width:0; }
      .pp-list-edit-actions { display:flex; align-items:center; gap:8px; margin-top:8px; flex-wrap:wrap; }

      /* Réseaux sociaux (édition) */
      .pp-social-edit-row { display:flex; gap:10px; align-items:center; margin-bottom:7px; }
      .pp-social-check { flex:0 0 150px; display:flex; align-items:center; gap:7px; font-size:13px; color:hsl(var(--text-secondary)); cursor:pointer; }
      .pp-social-edit-row > input[type=text] { flex:1; min-width:0; }

      /* === PHOTOS === */
      .pp-photos { display:flex; flex-direction:column; gap:14px; }
      .pp-photo-group-head { display:flex; align-items:center; gap:8px; margin-bottom:7px; }
      .pp-photo-group-title { font-size:12.5px; font-weight:800; color:hsl(var(--text-secondary)); }
      .pp-photo-group-count { font-size:11px; color:hsl(var(--text-muted)); background:hsl(var(--text-muted) / .1); padding:1px 8px; border-radius:999px; }
      .pp-photo-grid { display:flex; flex-wrap:wrap; gap:10px; align-items:center; }
      .pp-photo-thumb { position:relative; width:96px; height:96px; border-radius:9px; overflow:hidden; border:1px solid hsl(var(--border)); background:hsl(var(--bg)); }
      .pp-photo-thumb img { width:100%; height:100%; object-fit:cover; cursor:zoom-in; display:block; }
      .pp-photo-acts { position:absolute; top:4px; right:4px; display:flex; gap:4px; opacity:0; transition:opacity .15s; }
      .pp-photo-thumb:hover .pp-photo-acts { opacity:1; }
      /* Pastilles posées SUR la photo : fond sombre fixe lisible sur n'importe quelle image */
      .pp-photo-act { width:24px; height:24px; border-radius:6px; border:none; cursor:pointer; font-size:12px; background:rgba(15,23,42,.85); color:#e2e8f0; display:flex; align-items:center; justify-content:center; }
      .pp-photo-act:hover { background:#facc15; color:#0f172a; }
      .pp-photo-act.danger:hover { background:hsl(var(--danger)); color:#fff; }
      .pp-photo-add { width:96px; height:96px; border-radius:9px; border:1.5px dashed hsl(var(--text-muted) / .4); background:hsl(var(--text-muted) / .05); color:hsl(var(--text-muted)); cursor:pointer; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:3px; font-size:20px; }
      .pp-photo-add span { font-size:11px; font-weight:700; }
      .pp-photo-add:hover { border-color:hsl(var(--warning)); color:hsl(var(--warning-text)); background:hsl(var(--warning) / .07); }
      .pp-photo-empty { font-size:12px; color:hsl(var(--text-muted)); font-style:italic; }

      /* Lightbox (photo agrandie) — fond noir fixe volontaire : une photo se regarde sur noir */
      .pp-lightbox { position:fixed; inset:0; z-index:2000; background:rgba(0,0,0,.85); display:flex; align-items:center; justify-content:center; padding:30px; cursor:zoom-out; animation:pp-fadein .15s ease; }
      .pp-lightbox img { max-width:92vw; max-height:92vh; border-radius:10px; box-shadow:0 20px 60px rgba(0,0,0,.6); }
      .pp-lightbox-close { position:fixed; top:18px; right:24px; width:42px; height:42px; border-radius:50%; border:none; background:rgba(255,255,255,.15); color:#fff; font-size:24px; cursor:pointer; }

      /* (Les petits messages passent par le système Toast commun — plus de toast maison ici.) */

      /* === FICHE MESSAGE / RAPPEL (épurée) === */
      .pp-msg-box { background:hsl(var(--text-muted) / .07); border:1px solid hsl(var(--border)); border-left:3px solid #f59e0b; border-radius:8px; padding:12px 14px; font-size:14px; line-height:1.6; color:hsl(var(--text)); white-space:pre-wrap; word-break:break-word; }
      .pp-msg-box.pp-msg-empty { color:hsl(var(--text-muted)); font-style:italic; border-left-color:hsl(var(--text-muted) / .6); }
      .pp-recall-box { display:flex; align-items:center; gap:14px; background:hsl(var(--info) / .08); border:1px solid hsl(var(--info) / .3); border-radius:12px; padding:14px 16px; }
      .pp-recall-ico { font-size:28px; line-height:1; }
      .pp-recall-lbl { font-size:12px; font-weight:700; color:hsl(var(--text-muted)); text-transform:uppercase; letter-spacing:.04em; margin-bottom:3px; }
      .pp-recall-num { font-size:24px; font-weight:800; color:hsl(var(--info-text)); text-decoration:none; letter-spacing:.02em; }
      .pp-recall-num:hover { text-decoration:underline; }
      .pp-recall-num-empty { color:hsl(var(--text-muted)); font-size:16px; font-style:italic; font-weight:600; }
      /* Les actions sous forme de lien (<a>) doivent ressembler aux boutons */
      a.pp-action-btn { display:inline-flex; align-items:center; gap:6px; text-decoration:none; }
    `;
    document.head.appendChild(s);
  },

  // Bascule entre la vue Pipeline (tunnel clients) et la vue Statistiques.
  // La préférence est mémorisée pour la prochaine visite.
  _setTab(tab) {
    if (!['pipeline', 'comm', 'stats'].includes(tab)) tab = 'pipeline';
    this.state.tab = tab;
    try { localStorage.setItem('pp_tab', tab); } catch (e) {}

    if (this._root) {
      this._root.querySelectorAll('[data-pp-tab]').forEach(b => {
        const active = b.dataset.ppTab === tab;
        b.classList.toggle('is-active', active);
        b.setAttribute('aria-selected', active ? 'true' : 'false');
      });
    }
    const vp = document.getElementById('pp-view-pipeline');
    const vc = document.getElementById('pp-view-comm');
    const vs = document.getElementById('pp-view-stats');
    if (vp) vp.hidden = (tab !== 'pipeline');
    if (vc) vc.hidden = (tab !== 'comm');
    if (vs) vs.hidden = (tab !== 'stats');

    // La recherche filtre les cartes (pipeline + communication) : inutile côté stats.
    const search = document.getElementById('pp-search');
    if (search) search.style.display = (tab === 'stats') ? 'none' : '';

    // Les stats ne se chargent qu'à la première ouverture de l'onglet.
    if (tab === 'stats' && !this._statsLoaded) {
      this._statsLoaded = true;
      this._renderStats();
    }
  },

  async refresh() {
    this.state.loading = true;
    this._renderFunnel();
    this._renderKanban();
    const [stateRes, listRes, autoRes] = await Promise.all([
      this._call('pixelpros_pipeline_state'),
      this._call('pixelpros_list_intakes', { limit: 200 }),
      this._call('pixelpros_mail_auto_get'),
    ]);
    // Échec de chargement → on le DIT (au lieu d'afficher de fausses colonnes vides).
    this.state.loadError = (listRes && listRes.ok) ? null : ((listRes && listRes.error) || 'inconnue');
    if (stateRes && stateRes.ok) this.state.counts = stateRes.counts || null;
    this.state.intakes = (listRes && listRes.ok) ? (listRes.intakes || []) : [];
    if ((!stateRes || !stateRes.ok) && listRes && listRes.ok) {
      // Compteurs serveur indisponibles → on recompte depuis la liste chargée
      // (mieux que des zéros mensongers dans le funnel).
      const counts = {};
      for (const it of this.state.intakes) counts[it.status] = (counts[it.status] || 0) + 1;
      this.state.counts = counts;
    }
    if (autoRes && autoRes.ok && autoRes.auto) {
      this.state.mailAuto = {
        paid: autoRes.auto.paid !== false,
        live: autoRes.auto.live !== false,
      };
    }
    this.state.loading = false;

    this._renderFunnel();
    this._renderKanban();
    this._renderFailures();

    // Mention discrète si la liste atteint son plafond d'affichage.
    const note = document.getElementById('pp-limit-note');
    if (note) note.hidden = (this.state.intakes.length < 200);

    // Suivi automatique tant qu'au moins un site se fabrique.
    this._ensureAutoRefresh();

    if (this.state.selectedId) {
      await this._loadDetail(this.state.selectedId);
    }
  },

  // Pendant qu'un site se fabrique, on re-liste toutes les 30 s pour voir le
  // passage en « En ligne » sans avoir à cliquer Rafraîchir. Le minuteur
  // s'arrête tout seul : au changement de vue (App.viewInterval) ou dès que
  // plus rien n'est en fabrication.
  _ensureAutoRefresh() {
    // Si on a quitté la vue pendant le chargement, on ne pose rien :
    // le minuteur appartiendrait à un écran fantôme.
    if (App.currentView !== 'pixelpros') return;
    const building = (this.state.intakes || []).some(it => it.status === 'building');
    if (building && !this._buildPoll) {
      this._buildPoll = App.viewInterval(() => {
        if (document.hidden) return;                          // onglet en arrière-plan
        if (this.state.edit || this.state.editRows) return;   // édition en cours : on n'écrase rien
        this.refresh();
      }, 30000);
      App.onViewCleanup(() => { this._buildPoll = null; });
    } else if (!building && this._buildPoll) {
      clearInterval(this._buildPoll);
      this._buildPoll = null;
    }
  },

  // ----- FUNNEL -----
  // On affiche un mini-marqueur ✉️ entre les étapes pour visualiser quand
  // un mail est envoyé au client. Au clic, ça ouvre l'éditeur du mail.
  //
  // Mails dans le pipeline Pixel Pros :
  //   draft → [✉️ paiement reçu] → paid → building → [✉️ site en ligne] → live
  MAILS_BETWEEN: {
    'draft→paid':     { kind: 'paid', label: 'Mail "paiement reçu"',  short: 'Paiement reçu',  color: '#facc15' },
    'building→live':  { kind: 'live', label: 'Mail "site en ligne"',  short: 'Site en ligne',  color: '#22c55e' },
  },

  _renderFunnel() {
    const el = document.getElementById('pp-funnel');
    if (!el) return;
    const c = this.state.counts || {};
    const steps = [
      { k: 'draft',    l: 'Formulaire',      ico: '📝', cls: '' },
      { k: 'paid',     l: 'À construire',    ico: '💳', cls: (c.paid||0) > 0 ? 'alert' : '' },
      { k: 'building', l: 'En construction', ico: '🛠',  cls: '' },
      { k: 'live',     l: 'En ligne',        ico: '✅', cls: (c.live||0) > 0 ? 'success' : '' },
    ];
    el.className = 'pp-funnel';

    const parts = [];
    steps.forEach((s, i) => {
      parts.push(`
        <div class="pp-funnel-step ${s.cls}">
          <span class="pp-funnel-icon">${s.ico}</span>
          <span class="pp-funnel-n">${c[s.k] || 0}</span>
          <span class="pp-funnel-l">${s.l}</span>
        </div>
      `);
      if (i < steps.length - 1) {
        const next = steps[i + 1];
        const transitionKey = `${s.k}→${next.k}`;
        const mail = this.MAILS_BETWEEN[transitionKey];
        if (mail) {
          const isAuto = (this.state.mailAuto || {})[mail.kind] !== false;
          const modeLabel = isAuto ? '🤖 Auto' : '✋ Manuel';
          const modeTitle = isAuto
            ? `Mode auto : le mail « ${mail.short} » part tout seul. Clique pour passer en manuel.`
            : `Mode manuel : tu déclenches le mail « ${mail.short} » à la main depuis la fiche du client. Clique pour repasser en auto.`;
          parts.push(`
            <div class="pp-mail-marker-wrap ${isAuto ? 'is-auto' : 'is-manual'}">
              <button class="pp-mail-marker" data-pp-mail="${mail.kind}"
                      style="--mc:${mail.color};"
                      title="Voir / modifier le mail « ${this._escape(mail.short)} »">
                <span class="pp-mail-ico">✉️</span>
                <span class="pp-mail-lbl">${this._escape(mail.short)}</span>
                <span class="pp-mail-edit">Modifier</span>
              </button>
              <button class="pp-mail-toggle ${isAuto ? 'is-auto' : 'is-manual'}"
                      data-pp-mail-toggle="${mail.kind}"
                      title="${this._escape(modeTitle)}">
                ${modeLabel}
              </button>
            </div>
          `);
        } else {
          parts.push('<div class="pp-funnel-gap"></div>');
        }
      }
    });
    el.innerHTML = parts.join('');

    // Bind des marqueurs ✉️
    el.querySelectorAll('[data-pp-mail]').forEach(btn => {
      btn.onclick = (e) => {
        e.stopPropagation();
        this._openMailEditor(btn.dataset.ppMail);
      };
    });

    // Bind des toggles Auto/Manuel
    el.querySelectorAll('[data-pp-mail-toggle]').forEach(btn => {
      btn.onclick = async (e) => {
        e.stopPropagation();
        const kind = btn.dataset.ppMailToggle;
        const current = (this.state.mailAuto || {})[kind] !== false;
        const next = !current;
        btn.disabled = true;
        btn.textContent = '…';
        const res = await this._call('pixelpros_mail_auto_set', { kind, auto: next });
        btn.disabled = false;
        if (res && res.ok) {
          this.state.mailAuto = { ...this.state.mailAuto, [kind]: res.auto !== false };
          this._toast(next
            ? `Mail « ${this.MAILS_BETWEEN[Object.keys(this.MAILS_BETWEEN).find(k => this.MAILS_BETWEEN[k].kind === kind)].short} » : envoi automatique activé`
            : `Mail « ${this.MAILS_BETWEEN[Object.keys(this.MAILS_BETWEEN).find(k => this.MAILS_BETWEEN[k].kind === kind)].short} » : à déclencher manuellement depuis la fiche client`);
          this._renderFunnel();
        } else {
          this._failToast('Le réglage n’a pas pu être enregistré.', res);
          this._renderFunnel();
        }
      };
    });
  },

  // ----- ÉDITEUR DE MAIL -----
  async _openMailEditor(kind) {
    if (!kind) return;
    // Overlay + panel
    let overlay = document.getElementById('pp-mail-overlay');
    let panel = document.getElementById('pp-mail-panel');
    if (!overlay) {
      overlay = document.createElement('div');
      overlay.id = 'pp-mail-overlay';
      overlay.className = 'pp-detail-overlay';
      overlay.onclick = () => this._closeMailEditor();
      document.body.appendChild(overlay);
    }
    if (!panel) {
      panel = document.createElement('aside');
      panel.id = 'pp-mail-panel';
      panel.className = 'pp-detail-panel';
      document.body.appendChild(panel);
    }
    overlay.hidden = false;
    panel.hidden = false;
    this._mailInitial = null;
    panel.innerHTML = `<div style="padding:60px 0; text-align:center; color:hsl(var(--text-muted));">Chargement…</div>`;

    const res = await this._call('pixelpros_mail_template_get', { kind });
    if (!res || !res.ok) {
      panel.innerHTML = `<button class="pp-detail-close" data-pp-mail-close title="Fermer" aria-label="Fermer">×</button>
        <div class="pp-error-box">⚠ Impossible de charger ce mail — réessaie dans un instant.
          <details class="pp-error-detail"><summary>Voir le détail technique</summary><pre>${this._escape(res?.error || 'inconnue')}</pre></details>
        </div>`;
      panel.querySelector('[data-pp-mail-close]').onclick = () => this._closeMailEditor();
      return;
    }
    this._renderMailEditor(kind, res.template);
  },

  _renderMailEditor(kind, tpl) {
    const panel = document.getElementById('pp-mail-panel');
    if (!panel) return;
    const mailMeta = kind === 'paid'
      ? { title: 'Mail "Paiement reçu"', sub: 'Envoyé automatiquement quand Stripe confirme le paiement (passage en statut "Payé").', accent: '#facc15' }
      : { title: 'Mail "Site en ligne"',  sub: 'Envoyé automatiquement quand le site est mis en ligne (passage en statut "En ligne").',  accent: '#22c55e' };

    const isCustom = !!tpl.is_custom;

    panel.innerHTML = `
      <button class="pp-detail-close" data-pp-mail-close title="Fermer" aria-label="Fermer">×</button>

      <div class="pp-detail-head">
        <div class="pp-avatar" style="background:${mailMeta.accent};">✉️</div>
        <div>
          <div class="pp-detail-name">${this._escape(mailMeta.title)}</div>
          <div class="pp-detail-sub">${this._escape(mailMeta.sub)}</div>
          <span class="pp-detail-pill" style="background:${mailMeta.accent}25; color:${mailMeta.accent};">
            ${isCustom ? '✏️ Modifié par toi' : '⚙️ Texte par défaut'}
          </span>
        </div>
      </div>

      <div class="pp-detail-section">
        <div class="pp-detail-section-title">Sujet du mail</div>
        <input id="pp-mail-subject" type="text" class="pp-mail-input" value="${this._escape(tpl.subject || '')}" />
      </div>

      <div class="pp-detail-section">
        <div class="pp-detail-section-title">Texte brut (clients sans HTML)</div>
        <textarea id="pp-mail-text" class="pp-mail-textarea" rows="10">${this._escape(tpl.body_text || '')}</textarea>
      </div>

      <div class="pp-detail-section">
        <div class="pp-detail-section-title">Version HTML (mise en forme jolie)</div>
        <textarea id="pp-mail-html" class="pp-mail-textarea pp-mail-textarea-code" rows="14">${this._escape(tpl.body_html || '')}</textarea>
        <details style="margin-top:10px;">
          <summary class="pp-data-toggle">👁 Aperçu du HTML</summary>
          <iframe id="pp-mail-preview" class="pp-mail-preview" sandbox=""></iframe>
        </details>
      </div>

      <div class="pp-detail-section">
        <div class="pp-detail-section-title">Variables disponibles (à coller dans le texte ou le HTML)</div>
        <div class="pp-mail-vars">
          <code>{firstname}</code> <span>prénom du client</span><br>
          <code>{business}</code> <span>nom de l'entreprise</span><br>
          <code>{business_paren}</code> <span>" (nom)" entre parenthèses, ou rien</span><br>
          <code>{business_space}</code> <span>" nom" avec espace devant, ou rien</span><br>
          <code>{site_url}</code> <span>URL du site (mail "en ligne" uniquement)</span>
        </div>
      </div>

      <div class="pp-detail-section">
        <div class="pp-actions">
          <button data-pp-mail-save class="pp-action-btn primary">💾 Enregistrer</button>
          <button data-pp-mail-reset class="pp-action-btn danger" ${isCustom ? '' : 'disabled'}>↺ Remettre par défaut</button>
        </div>
      </div>
    `;

    panel.querySelector('[data-pp-mail-close]').onclick = () => this._closeMailEditor();

    // Mémorise l'état initial : sert à détecter les modifications non
    // enregistrées avant de fermer (clic à côté / Échap).
    this._mailInitial = {
      subject: tpl.subject || '',
      text: tpl.body_text || '',
      html: tpl.body_html || '',
    };

    // Aperçu HTML live
    const htmlField = panel.querySelector('#pp-mail-html');
    const preview = panel.querySelector('#pp-mail-preview');
    const refreshPreview = () => {
      if (!preview) return;
      preview.srcdoc = htmlField.value || '<i>(vide)</i>';
    };
    htmlField.addEventListener('input', refreshPreview);
    refreshPreview();

    panel.querySelector('[data-pp-mail-save]').onclick = async (e) => {
      const saveBtn = e.currentTarget;
      const subject = panel.querySelector('#pp-mail-subject').value.trim();
      const body_text = panel.querySelector('#pp-mail-text').value;
      const body_html = panel.querySelector('#pp-mail-html').value;
      if (!subject) { this._toast('Le sujet ne peut pas être vide', true); return; }
      saveBtn.disabled = true;
      const res = await this._call('pixelpros_mail_template_save', { kind, subject, body_text, body_html });
      saveBtn.disabled = false;
      if (res?.ok) {
        this._toast(`Mail enregistré ✓ ${res.message || ''}`.trim());
        this._openMailEditor(kind);  // recharge pour mettre à jour la pastille "Modifié"
      } else {
        this._failToast('L’enregistrement du mail a échoué.', res);
      }
    };

    panel.querySelector('[data-pp-mail-reset]').onclick = async (e) => {
      const resetBtn = e.currentTarget;
      const ok = await Dialog.confirm(
        'Remettre le mail à sa version par défaut ? Tes modifications seront perdues.',
        { title: 'Remettre par défaut', okLabel: 'Remettre par défaut', danger: true });
      if (!ok) return;
      resetBtn.disabled = true;
      const res = await this._call('pixelpros_mail_template_reset', { kind });
      resetBtn.disabled = false;
      if (res?.ok) {
        this._toast('Mail remis à sa version par défaut ✓');
        this._openMailEditor(kind);
      } else {
        this._failToast('La remise par défaut a échoué.', res);
      }
    };
  },

  async _closeMailEditor() {
    const overlay = document.getElementById('pp-mail-overlay');
    const panel = document.getElementById('pp-mail-panel');
    // Garde anti-perte : si le mail a été modifié sans être enregistré,
    // on demande confirmation avant de jeter la saisie.
    if (panel && !panel.hidden && this._mailInitial) {
      const s = panel.querySelector('#pp-mail-subject');
      const t = panel.querySelector('#pp-mail-text');
      const h = panel.querySelector('#pp-mail-html');
      const dirty = s && t && h && (
        s.value !== this._mailInitial.subject ||
        t.value !== this._mailInitial.text ||
        h.value !== this._mailInitial.html);
      if (dirty) {
        const ok = await Dialog.confirm(
          'Tu as des modifications non enregistrées sur ce mail.\nFermer sans enregistrer ?',
          { title: 'Modifications non enregistrées', okLabel: 'Fermer sans enregistrer', danger: true });
        if (!ok) return;
      }
    }
    this._mailInitial = null;
    if (overlay) overlay.hidden = true;
    if (panel) { panel.hidden = true; panel.innerHTML = ''; }
  },

  // ----- KANBAN -----
  // Deux tableaux distincts, alimentés par les mêmes données :
  //  - Pipeline (#pp-kanban)      : colonnes du tunnel des sites.
  //  - Contact (#pp-comm-kanban) : messages reçus + demandes de rappel.
  _renderKanban() {
    const pipelineCols = this.COLUMNS.filter(c => c.group !== 'comm');
    const commCols     = this.COLUMNS.filter(c => c.group === 'comm');
    this._renderColumns('pp-kanban', pipelineCols, 'Aucune commande ici.');
    this._renderColumns('pp-comm-kanban', commCols, 'Personne pour le moment.');
    this._updateCommBadge();
  },

  // Rend un jeu de colonnes Kanban dans le conteneur demandé.
  _renderColumns(containerId, columns, emptyLabel) {
    const el = document.getElementById(containerId);
    if (!el) return;
    // Échec de chargement : un vrai message d'erreur + Réessayer, au lieu de
    // colonnes faussement vides (« Aucune commande ici »).
    if (this.state.loadError) {
      console.warn('pixelpros: échec de chargement de la liste —', this.state.loadError);
      el.innerHTML = `
        <div class="pp-load-error" style="grid-column:1 / -1;">
          <div>⚠️ Impossible de charger les commandes — vérifie ta connexion.</div>
          <button class="pp-action-btn secondary" data-pp-retry>↻ Réessayer</button>
        </div>`;
      const retry = el.querySelector('[data-pp-retry]');
      retry.onclick = () => { retry.disabled = true; this.refresh(); };
      return;
    }
    const groups = {};
    for (const col of columns) groups[col.status] = [];
    const filtered = this._filteredIntakes();
    const handledLegacy = this._handledIds();
    for (const it of filtered) {
      // Les fiches Contact marquées « Traité » sont rangées (masquées) :
      // marqueur serveur data.handled_at (partagé entre appareils) +
      // héritage de l'ancienne mémoire navigateur.
      if ((it.status === 'contact' || it.status === 'recall') &&
          (((it.data || {}).handled_at) || handledLegacy.has(it.id))) continue;
      if (groups[it.status]) groups[it.status].push(it);
    }

    el.innerHTML = columns.map(col => {
      const items = groups[col.status];
      return `
        <div class="pp-col" style="--col-accent:${col.accent};">
          <div class="pp-col-head">
            <div class="pp-col-title"><span class="ico">${col.icon}</span><span>${this._escape(col.short)}</span></div>
            <span class="pp-col-count">${items.length}</span>
          </div>
          <div class="pp-col-body">
            ${items.length === 0
              ? `<div class="pp-col-empty">${this.state.loading ? 'Chargement…' : this._escape(emptyLabel)}</div>`
              : items.map(it => this._renderCard(it, col.accent)).join('')}
          </div>
        </div>
      `;
    }).join('');

    this._bindCardActions(el);
  },

  // Pastille de compteur sur l'onglet Contact : nombre de messages /
  // rappels en attente (hors fiches déjà traitées), pour les repérer même
  // quand on est sur un autre onglet.
  _updateCommBadge() {
    const badge = document.getElementById('pp-comm-badge');
    if (!badge) return;
    const handledLegacy = this._handledIds();
    const n = (this.state.intakes || [])
      .filter(it => (it.status === 'contact' || it.status === 'recall')
                    && !((it.data || {}).handled_at)
                    && !handledLegacy.has(it.id)).length;
    if (n > 0) { badge.textContent = n; badge.hidden = false; }
    else { badge.hidden = true; }
  },

  // ----- STATISTIQUES -----
  async _renderStats(period) {
    period = period || this.state.statsPeriod || '30d';
    this.state.statsPeriod = period;
    const el = document.getElementById('pp-stats');
    if (!el) return;
    // État de chargement : remplace aussi les boutons de période → pas de
    // double-clic possible pendant l'appel.
    el.innerHTML = `<div style="padding:40px 0; text-align:center; color:hsl(var(--text-muted));">Chargement des statistiques…</div>`;
    const res = await this._call('pixelpros_analytics', { period });
    if (!res || !res.ok) {
      // Échec réseau : un vrai message + Réessayer, au lieu de faux zéros.
      console.warn('pixelpros: stats indisponibles —', res && res.error);
      el.innerHTML = `
        <div class="pp-load-error">
          <div>⚠️ Impossible de charger les statistiques — vérifie ta connexion.</div>
          <button class="pp-action-btn secondary" data-pp-stats-retry>↻ Réessayer</button>
        </div>`;
      const retry = el.querySelector('[data-pp-stats-retry]');
      retry.onclick = () => { retry.disabled = true; this._renderStats(period); };
      return;
    }
    const s = (res && res.stats) || {};
    const cap = (t) => t ? t.charAt(0).toUpperCase() + t.slice(1) : t;
    const fileOf = (path) => String(path || '').split('?')[0].split('/').pop().replace(/\.html$/i, '');
    const cleanPath = (path) => '/' + (String(path || '').split('?')[0].split('/').pop() || '');
    const prettyPage = (path) => {
      const f = fileOf(path);
      if (!f || f === 'index') return 'Accueil';
      const map = { 'configurer':'Formulaire de configuration', 'merci':'Remerciement (après paiement)', 'affiliation':'Programme affiliation', 'demo':'Démo générale', 'cgv':'CGV', 'mentions-legales':'Mentions légales', 'confidentialite':'Confidentialité', '404':'Page introuvable (404)' };
      if (map[f]) return map[f];
      if (f.indexOf('demo-') === 0) return 'Démo — ' + cap(f.slice(5).replace(/-/g, ' '));
      return 'Page ' + cap(f.replace(/-/g, ' '));
    };
    const fmtTime = (sec) => { sec = sec || 0; const m = Math.floor(sec / 60), r = sec % 60; return m ? (m + ' min ' + r + 's') : (r + 's'); };

    const cards = [
      { ico: '👤', val: s.visiteurs_uniques ?? 0, lbl: 'Visiteurs uniques', hint: 'personnes différentes venues sur le site' },
      { ico: '⏱️', val: fmtTime(s.temps_moyen_session_s), lbl: 'Temps moyen par visite', hint: 'temps passé sur le site en moyenne' },
      { ico: '📜', val: (s.scroll_moyen ?? 0) + ' %', lbl: 'Page lue en moyenne', hint: 'jusqu’où les gens descendent dans la page' },
      { ico: '📄', val: s.pages_vues ?? 0, lbl: 'Pages vues (total)', hint: 'nombre total de pages affichées' },
      { ico: '📝', val: s.formulaires_commences ?? 0, lbl: 'Formulaires commencés', hint: 'visiteurs qui ont commencé à remplir' },
    ];

    const tops = s.top_pages || [];
    const maxV = Math.max.apply(null, tops.map(p => p.vues).concat([1]));
    const topHtml = tops.length ? tops.map(p => {
      const pct = Math.round(p.vues / maxV * 100);
      return `<li class="pp-stat-top-row">
        <div class="pp-stat-top-info">
          <span class="pp-stat-top-name">${this._escape(prettyPage(p.page))}</span>
          <span class="pp-stat-top-path">${this._escape(cleanPath(p.page))}</span>
        </div>
        <div class="pp-stat-top-barwrap"><div class="pp-stat-top-bar" style="width:${pct}%"></div></div>
        <span class="pp-stat-top-views">${p.vues} vue${p.vues > 1 ? 's' : ''}</span>
      </li>`;
    }).join('') : '<li class="pp-stat-top-empty">Pas encore de données — les pages apparaîtront ici dès les premières visites.</li>';

    const srcs = s.sources || [];
    const maxS = Math.max.apply(null, srcs.map(x => x.visiteurs).concat([1]));
    const srcHtml = srcs.length ? srcs.map(x => {
      const pct = Math.round(x.visiteurs / maxS * 100);
      return `<li class="pp-stat-top-row"><div class="pp-stat-top-info"><span class="pp-stat-top-name">${this._escape(x.source)}</span></div><div class="pp-stat-top-barwrap"><div class="pp-stat-top-bar" style="width:${pct}%"></div></div><span class="pp-stat-top-views">${x.visiteurs}</span></li>`;
    }).join('') : '<li class="pp-stat-top-empty">Pas encore de données.</li>';
    const app = s.appareils || {};
    const mob = app.mobile || 0, ord = app.ordinateur || 0, totApp = mob + ord;
    const mobPct = totApp ? Math.round(mob / totApp * 100) : 0;
    const ordPct = totApp ? 100 - mobPct : 0;

    const periods = [['7d', '7 jours'], ['30d', '30 jours'], ['all', 'Tout']];
    el.innerHTML = `
      <div class="pp-stats-head">
        <div>
          <h3 class="pp-stats-title">📊 Fréquentation de pixel-pros.fr</h3>
          <p class="pp-stats-sub">Comment les visiteurs se comportent sur ton site.</p>
        </div>
        <div class="pp-stats-periods">
          ${periods.map(([k, lab]) => `<button class="pp-stat-period ${period === k ? 'is-active' : ''}" data-period="${k}">${lab}</button>`).join('')}
        </div>
      </div>
      <div class="pp-stats-grid">
        ${cards.map(c => `<div class="pp-stat-card" title="${c.hint}"><div class="pp-stat-ico">${c.ico}</div><div class="pp-stat-val">${c.val}</div><div class="pp-stat-lbl">${c.lbl}</div></div>`).join('')}
      </div>
      <div class="pp-stat-top">
        <div class="pp-stat-top-head"><span class="pp-stat-top-title">🔥 Pages les plus regardées</span><span class="pp-stat-top-coltitle">Nombre de vues</span></div>
        <ul class="pp-stat-top-list">${topHtml}</ul>
      </div>
      <div class="pp-stats-2col">
        <div class="pp-stat-top">
          <div class="pp-stat-top-head"><span class="pp-stat-top-title">🔗 D'où viennent les visiteurs</span><span class="pp-stat-top-coltitle">Visiteurs</span></div>
          <ul class="pp-stat-top-list">${srcHtml}</ul>
        </div>
        <div class="pp-stat-top">
          <div class="pp-stat-top-head"><span class="pp-stat-top-title">📱 Mobile / Ordinateur</span></div>
          ${totApp ? `<div class="pp-stat-device-bar"><div class="pp-stat-device-mob" style="width:${mobPct}%"></div><div class="pp-stat-device-ord" style="width:${ordPct}%"></div></div>
          <div class="pp-stat-device-legend"><span><span class="pp-dot pp-dot-mob"></span>Mobile · ${mob} (${mobPct} %)</span><span><span class="pp-dot pp-dot-ord"></span>Ordinateur · ${ord} (${ordPct} %)</span></div>` : '<div class="pp-stat-top-empty">Pas encore de données.</div>'}
        </div>
      </div>
    `;
    el.querySelectorAll('.pp-stat-period').forEach(b => { b.onclick = () => this._renderStats(b.dataset.period); });
  },

  _renderFailures() {
    const el = document.getElementById('pp-failures');
    if (!el) return;
    if (this.state.loadError) { el.innerHTML = ''; return; }
    const failures = this._filteredIntakes().filter(it => it.status === 'failed');
    if (!failures.length) { el.innerHTML = ''; return; }
    el.innerHTML = `
      <div class="pp-failures">
        <div class="pp-failures-title">⚠ Échecs (${failures.length}) — à relancer ou supprimer</div>
        <div class="pp-failures-grid">${failures.map(it => this._renderCard(it, '#ef4444')).join('')}</div>
      </div>
    `;
    this._bindCardActions(el);
  },

  _bindCardActions(root) {
    if (!root) return;
    // Clic (ou Entrée / Espace au clavier) sur la carte → panneau de détail
    root.querySelectorAll('[data-pp-card]').forEach(card => {
      const open = () => {
        this.state.selectedId = card.dataset.ppCard;
        this._loadDetail(this.state.selectedId);
      };
      card.onclick = open;
      card.onkeydown = (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); }
      };
    });
    // Clic sur la corbeille → suppression directe sans ouvrir le détail
    root.querySelectorAll('[data-pp-trash]').forEach(btn => {
      btn.onclick = (e) => {
        e.stopPropagation();
        e.preventDefault();
        const id = btn.dataset.ppTrash;
        const intake = (this.state.intakes || []).find(it => it.id === id);
        if (!intake) return;
        this._doAction('delete', intake, btn);
      };
    });
  },

  _filteredIntakes() {
    const q = this.state.search;
    if (!q) return this.state.intakes;
    return this.state.intakes.filter(it => {
      const data = it.data || {};
      const blob = [
        data.business_name, data['business-name'], data.email, it.email,
        it.slug, it.id, data.city, data.phone,
      ].filter(Boolean).join(' ').toLowerCase();
      return blob.includes(q);
    });
  },

  _renderCard(it, accent) {
    const data = it.data || {};
    const name = data.business_name || data['business-name'] || it.business_name || '(sans nom)';
    const email = data.email || it.email || '—';
    const isRecall = it.status === 'recall' || data.recall === true;
    const metaLine = isRecall ? ('☎ ' + (data.phone || 'numéro non fourni')) : email;
    const initial = name.trim().charAt(0).toUpperCase() || '?';
    const color = this._colorFromName(name);
    const option = it.selected_option || data.selected_option || it.option || '';
    const formule = this.FORMULES[option] || null;
    // L'urgence se mesure depuis le PAIEMENT (updated_at bouge à chaque retouche
    // de fiche, ce qui faisait disparaître l'alerte à tort).
    const isUrgent = it.status === 'paid' && this._hoursSince(it.stripe_paid_at || it.updated_at || it.created_at) > this.URGENT_THRESHOLD_H;
    const selected = this.state.selectedId === it.id ? 'selected' : '';
    return `
      <div class="pp-card ${isUrgent ? 'urgent' : ''} ${selected}" data-pp-card="${this._escape(it.id)}" style="--col-accent:${accent};" role="button" tabindex="0" aria-label="Ouvrir la fiche de ${this._escape(name)}">
        <button class="pp-card-trash" data-pp-trash="${this._escape(it.id)}" title="Supprimer ce formulaire" aria-label="Supprimer">🗑</button>
        <div class="pp-avatar" style="background:${color};">${this._escape(initial)}</div>
        <div class="pp-card-body">
          <div class="pp-card-name">${this._escape(name)}</div>
          <div class="pp-card-meta">${this._escape(metaLine)}</div>
          <div class="pp-card-badges">
            ${isRecall ? `<span class="pp-formule-badge" style="background:#06b6d420; color:#06b6d4;">☎ Rappel</span>` : (formule ? `<span class="pp-formule-badge" style="background:${formule.color}20; color:${formule.color};">${this._escape(formule.label)}</span>` : '')}
            <span class="pp-card-time">${this._timeRelative(it.updated_at || it.created_at)}</span>
            ${isUrgent ? `<span class="pp-urgent-badge">URGENT</span>` : ''}
          </div>
          ${it.status === 'failed' ? `
          <div class="text-[11px] mt-1" style="color:#ef4444; text-wrap: pretty;">
            ${data.error ? '⚠ ' + this._escape(String(data.error).slice(0, 120)) : '⚠ La fabrication a échoué'}
            — clic : voir le détail et « ↻ Relancer la construction »
          </div>` : ''}
        </div>
      </div>
    `;
  },

  // ----- PANNEAU DE DÉTAIL -----
  // Crée (une fois) l'overlay + le panneau de détail directement dans <body>.
  // Indispensable : en position:fixed, un parent animé par transform devient
  // le repère du plein écran et "rapetisse" le panneau. Dans <body>, il se
  // cale sur la fenêtre entière.
  _ensureDetailEls() {
    let overlay = document.getElementById('pp-detail-overlay');
    if (!overlay) {
      overlay = document.createElement('div');
      overlay.id = 'pp-detail-overlay';
      overlay.className = 'pp-detail-overlay';
      overlay.hidden = true;
      document.body.appendChild(overlay);
    } else if (overlay.parentElement !== document.body) {
      document.body.appendChild(overlay);
    }
    overlay.onclick = () => this._requestCloseDetail();

    let panel = document.getElementById('pp-detail');
    if (!panel) {
      panel = document.createElement('aside');
      panel.id = 'pp-detail';
      panel.className = 'pp-detail-panel';
      panel.hidden = true;
      document.body.appendChild(panel);
    } else if (panel.parentElement !== document.body) {
      document.body.appendChild(panel);
    }
  },

  async _loadDetail(id) {
    // On ne jette l'édition en cours QUE si on change de fiche : un simple
    // rechargement de la même fiche (toggle de rubrique, refresh) garde le
    // brouillon tapé (capturé par _captureEditBuffer).
    const sameIntake = !!(this.state.detail && this.state.detail.intake && this.state.detail.intake.id === id);
    if (!sameIntake) {
      this.state.edit = null;
      this.state.editRows = null;
    } else {
      this._captureEditBuffer();
    }
    this._ensureDetailEls();
    document.getElementById('pp-detail-overlay').hidden = false;
    const panel = document.getElementById('pp-detail');
    panel.hidden = false;
    if (!sameIntake) {
      panel.innerHTML = `<div style="padding:60px 0; text-align:center; color:hsl(var(--text-muted));">Chargement…</div>`;
    }
    const res = await this._call('pixelpros_get_intake', { id });
    if (!res || !res.ok) {
      panel.innerHTML = `<button class="pp-detail-close" data-pp-close title="Fermer" aria-label="Fermer">×</button>
        <div class="pp-error-box">⚠ Impossible de charger cette fiche — réessaie dans un instant.
          <details class="pp-error-detail"><summary>Voir le détail technique</summary><pre>${this._escape(res?.error || 'inconnue')}</pre></details>
        </div>
        <div style="margin-top:14px;"><button class="pp-action-btn secondary" data-pp-retry-detail>↻ Réessayer</button></div>`;
      panel.querySelector('[data-pp-close]').onclick = () => this._closeDetail();
      const retry = panel.querySelector('[data-pp-retry-detail]');
      retry.onclick = () => { retry.disabled = true; this._loadDetail(id); };
      return;
    }
    this.state.detail = res;
    this._renderDetail();
    this._renderKanban(); // refresh la sélection visuelle
  },

  // Fermeture demandée par l'utilisateur (croix, clic à côté, Échap) :
  // si une modification est en cours, on demande avant de la jeter.
  async _requestCloseDetail() {
    if (this.state.edit) {
      this._captureEditBuffer();
      const ok = await Dialog.confirm(
        'Tu as une modification en cours non enregistrée sur cette fiche.\nFermer quand même ?',
        { title: 'Modification en cours', okLabel: 'Fermer quand même', danger: true });
      if (!ok) return;
    }
    this._closeDetail();
  },

  _closeDetail() {
    document.getElementById('pp-detail-overlay').hidden = true;
    const panel = document.getElementById('pp-detail');
    panel.hidden = true;
    panel.innerHTML = '';
    this.state.selectedId = null;
    this.state.detail = null;
    this.state.edit = null;
    this.state.editRows = null;
    this._photoCtx = null;
    this._renderKanban();
  },

  // Avant un re-rendu de la fiche, range la saisie en cours dans l'état
  // (sinon le texte tapé serait perdu par le rafraîchissement).
  _captureEditBuffer() {
    const panel = document.getElementById('pp-detail');
    if (!panel || !this.state.edit) return;
    if (this.state.edit.kind === 'list' && this.state.editRows) {
      const sec = this.SECTIONS[this.state.edit.sectionIdx];
      if (sec && sec.list) this._syncListBuffer(panel, sec.list.cols.length);
    } else if (this.state.edit.kind === 'field') {
      const input = panel.querySelector('[data-pp-field-input]');
      if (input) this.state.edit.draft = input.value;
    } else if (this.state.edit.kind === 'socials') {
      const buf = {};
      this.SOCIALS.forEach(s => {
        const onEl = panel.querySelector('[data-pp-social-on="' + s.key + '"]');
        const urlEl = panel.querySelector('[data-pp-social-url="' + s.key + '"]');
        buf[s.key] = { on: !!(onEl && onEl.checked), url: urlEl ? urlEl.value : '' };
      });
      this.state.edit.draft = buf;
    }
  },

  _renderDetail() {
    const panel = document.getElementById('pp-detail');
    const { intake, timeline } = this.state.detail;
    const data = intake.data || {};
    const name = data.business_name || data['business-name'] || intake.business_name || '(sans nom)';
    const email = data.email || intake.email || '—';
    const phone = data.phone || '';
    const initial = (name.trim().charAt(0) || '?').toUpperCase();
    const color = this._colorFromName(name);
    const col = this._statusMeta(intake.status);
    // L'erreur de fabrication n'est pertinente que pour un échec en cours.
    // Si le site est reparti (en ligne / en construction / payé), on n'affiche
    // pas un vieux message d'un essai raté précédent : ce serait une fausse alerte.
    const errMsg = (intake.status === 'failed') ? data.error : '';
    const actions = this._availableActions(intake);

    // Un simple message de contact ou une demande de rappel n'a rien d'une
    // commande de site : pas de paiement, pas de formulaire à rallonge, pas de
    // photos. On lui dédie une fiche épurée (qui · son message · actions).
    const isRecall = intake.status === 'recall' || data.recall === true;
    const isSimpleMessage = intake.status === 'contact' || isRecall;

    // En-tête (avatar + identité + pastille de statut), commun aux 2 fiches.
    const headHtml = `
      <button class="pp-detail-close" data-pp-close title="Fermer" aria-label="Fermer">×</button>

      <div class="pp-detail-head">
        <div class="pp-avatar" style="background:${color};">${this._escape(initial)}</div>
        <div style="flex:1; min-width:0;">
          <div class="pp-detail-name">${this._escape(name)}</div>
          <div class="pp-detail-sub">
            <span>${this._escape(email)}${phone ? ' · ' + this._escape(phone) : ''}</span>
            <button class="pp-edit-contact-btn" data-pp-edit-contact title="Modifier le mail / téléphone">✏️</button>
          </div>
          <span class="pp-detail-pill" style="background:${col.accent}25; color:${col.accent};">${col.icon} ${this._escape(col.label)}</span>
        </div>
      </div>`;

    // Chronologie + données techniques brutes, communes aux 2 fiches.
    // Les libellés serveur sont techniques → traduits par _timelineLabel.
    const timelineHtml = `
      <div class="pp-detail-section">
        <div class="pp-detail-section-title">Chronologie</div>
        <div class="pp-timeline">
          ${(timeline || []).map(ev => `
            <div class="pp-timeline-event ${ev.kind === 'current' ? 'current' : ''}">
              <div class="ts">${this._fmtDate(ev.ts)}</div>
              <div class="lbl">${this._escape(this._timelineLabel(ev, intake))}</div>
            </div>
          `).join('')}
        </div>
      </div>`;

    const rawHtml = `
      <div class="pp-detail-section">
        <details>
          <summary class="pp-data-toggle">Voir les données techniques brutes (${Object.keys(data).length} champs)</summary>
          ${intake.stripe_session_id ? `<div style="font-size:12px; color:hsl(var(--text-muted)); margin:8px 0;">Référence Stripe : <code style="color:hsl(var(--text-secondary));">${this._escape(intake.stripe_session_id)}</code></div>` : ''}
          <pre class="pp-data-pre">${this._escape(JSON.stringify(data, null, 2))}</pre>
        </details>
      </div>`;

    // --- Fiche épurée : message de contact / demande de rappel ---
    if (isSimpleMessage) {
      const messageHtml = data.message
        ? `<div class="pp-detail-section">
             <div class="pp-detail-section-title">${isRecall ? 'Son message (facultatif)' : 'Message'}</div>
             <div class="pp-msg-box">${this._escape(data.message)}</div>
           </div>`
        : (isRecall
            ? ''
            : `<div class="pp-detail-section">
                 <div class="pp-msg-box pp-msg-empty">(Pas de message — juste ses coordonnées.)</div>
               </div>`);

      panel.innerHTML = `
        ${headHtml}
        ${isRecall ? this._recallBlock(phone) : ''}
        ${messageHtml}
        <div class="pp-detail-section">
          <div class="pp-detail-section-title">Actions</div>
          <div class="pp-actions">${this._simpleActions(intake, email, phone).join('')}</div>
        </div>
        ${timelineHtml}
        ${rawHtml}
      `;
      this._bindDetail(panel, intake);
      return;
    }

    // --- Fiche complète : commande de site ---
    panel.innerHTML = `
      ${headHtml}

      ${errMsg ? `<div class="pp-detail-section"><div class="pp-error-box">⚠ La fabrication du site a échoué.
        <details class="pp-error-detail"><summary>Voir le détail technique</summary><pre>${this._escape(errMsg)}</pre></details>
      </div></div>` : ''}

      ${data.message ? `
        <div class="pp-detail-section">
          <div class="pp-detail-section-title">Message</div>
          <div class="pp-msg-box">${this._escape(data.message)}</div>
        </div>` : ''}

      ${this._paymentBlock(intake)}

      <div class="pp-detail-section">
        <div class="pp-detail-section-title">Actions</div>
        <div class="pp-actions">${actions.join('')}</div>
      </div>

      ${intake.site_url ? `
        <div class="pp-detail-section">
          <div class="pp-detail-section-title">Site en ligne</div>
          <a class="pp-detail-link" href="${this._escape(intake.site_url)}" target="_blank" rel="noopener">${this._escape(intake.site_url)} →</a>
        </div>` : ''}

      ${this._formBlock(intake)}

      ${this._photosBlock(intake)}

      ${timelineHtml}

      ${rawHtml}

      <input type="file" id="pp-photo-file" accept="image/*" hidden />
    `;

    this._bindDetail(panel, intake);
  },

  // Encadré « à rappeler » : le numéro bien en évidence, cliquable.
  _recallBlock(phone) {
    const tel = phone ? String(phone).replace(/[^\d+]/g, '') : '';
    const shown = phone ? this._escape(phone) : 'numéro non fourni';
    const num = tel
      ? `<a class="pp-recall-num" href="tel:${this._escape(tel)}">${shown}</a>`
      : `<span class="pp-recall-num pp-recall-num-empty">${shown}</span>`;
    return `
      <div class="pp-detail-section">
        <div class="pp-recall-box">
          <span class="pp-recall-ico">☎️</span>
          <div>
            <div class="pp-recall-lbl">Souhaite être rappelé·e au</div>
            ${num}
          </div>
        </div>
      </div>`;
  },

  // Actions d'un simple message / rappel : répondre par mail, appeler,
  // ranger la fiche (traitée), supprimer.
  _simpleActions(intake, email, phone) {
    const out = [];
    const mail = (email && email !== '—') ? String(email).trim() : '';
    const tel = phone ? String(phone).replace(/[^\d+]/g, '') : '';
    if (mail) {
      out.push(`<button data-pp-action="reply_mail" class="pp-action-btn primary">✉️ Répondre par mail</button>`);
    }
    if (tel) {
      out.push(`<a class="pp-action-btn secondary" href="tel:${this._escape(tel)}">☎️ Appeler</a>`);
    }
    out.push(`<button data-pp-action="mark_handled" class="pp-action-btn secondary" title="Range la fiche : elle quitte l’onglet Contact, sans rien supprimer">✓ Traité</button>`);
    out.push(`<button data-pp-action="delete" class="pp-action-btn danger">🗑 Supprimer définitivement</button>`);
    return out;
  },

  // ----- BINDINGS du panneau de détail -----
  _bindDetail(panel, intake) {
    const id = intake.id;

    panel.querySelector('[data-pp-close]').onclick = () => this._requestCloseDetail();

    panel.querySelectorAll('[data-pp-action]').forEach(b => {
      b.onclick = () => this._doAction(b.dataset.ppAction, intake, b);
    });

    const editContact = panel.querySelector('[data-pp-edit-contact]');
    if (editContact) editContact.onclick = () => this._editContact(intake);

    // --- Champs simples ---
    panel.querySelectorAll('[data-pp-edit-field]').forEach(b => {
      b.onclick = () => { this.state.edit = { kind: 'field', key: b.dataset.ppEditField }; this._renderDetail(); };
    });
    panel.querySelectorAll('[data-pp-field-save]').forEach(b => {
      b.onclick = () => this._saveField(id, b.dataset.ppFieldSave);
    });
    panel.querySelectorAll('[data-pp-field-cancel]').forEach(b => {
      b.onclick = () => { this.state.edit = null; this._renderDetail(); };
    });
    panel.querySelectorAll('[data-pp-toggle-bool]').forEach(b => {
      b.onclick = () => this._toggleBool(id, b.dataset.ppToggleBool);
    });
    panel.querySelectorAll('[data-pp-toggle-section]').forEach(b => {
      b.onclick = () => this._toggleBool(id, b.dataset.ppToggleSection);
    });

    // --- Listes ---
    panel.querySelectorAll('[data-pp-edit-list]').forEach(b => {
      b.onclick = () => {
        const idx = parseInt(b.dataset.ppEditList, 10);
        const sec = this.SECTIONS[idx];
        this.state.edit = { kind: 'list', sectionIdx: idx };
        this.state.editRows = this._listRows(sec.list.cols, intake.data || {});
        this._renderDetail();
      };
    });
    panel.querySelectorAll('[data-pp-list-add]').forEach(b => {
      b.onclick = () => {
        const sec = this.SECTIONS[this.state.edit.sectionIdx];
        this._syncListBuffer(panel, sec.list.cols.length);
        this.state.editRows.push(sec.list.cols.map(() => ''));
        this._renderDetail();
      };
    });
    panel.querySelectorAll('[data-pp-list-del]').forEach(b => {
      b.onclick = () => {
        const sec = this.SECTIONS[this.state.edit.sectionIdx];
        this._syncListBuffer(panel, sec.list.cols.length);
        this.state.editRows.splice(parseInt(b.dataset.ppListDel, 10), 1);
        this._renderDetail();
      };
    });
    panel.querySelectorAll('[data-pp-list-save]').forEach(b => {
      b.onclick = () => this._saveList(id);
    });
    panel.querySelectorAll('[data-pp-list-cancel]').forEach(b => {
      b.onclick = () => { this.state.edit = null; this.state.editRows = null; this._renderDetail(); };
    });

    // --- Réseaux sociaux ---
    panel.querySelectorAll('[data-pp-edit-socials]').forEach(b => {
      b.onclick = () => { this.state.edit = { kind: 'socials' }; this._renderDetail(); };
    });
    panel.querySelectorAll('[data-pp-socials-save]').forEach(b => {
      b.onclick = () => this._saveSocials(id);
    });
    panel.querySelectorAll('[data-pp-socials-cancel]').forEach(b => {
      b.onclick = () => { this.state.edit = null; this._renderDetail(); };
    });

    // --- Photos ---
    const fileInput = panel.querySelector('#pp-photo-file');
    panel.querySelectorAll('[data-pp-photo-add]').forEach(b => {
      b.onclick = () => { this._photoCtx = { id, kind: b.dataset.ppPhotoAdd, replacePath: null }; if (fileInput) fileInput.click(); };
    });
    panel.querySelectorAll('[data-pp-photo-replace]').forEach(b => {
      b.onclick = () => { this._photoCtx = { id, kind: b.dataset.kind, replacePath: b.dataset.ppPhotoReplace }; if (fileInput) fileInput.click(); };
    });
    panel.querySelectorAll('[data-pp-photo-del]').forEach(b => {
      b.onclick = () => this._deletePhoto(id, b.dataset.ppPhotoDel);
    });
    panel.querySelectorAll('[data-pp-photo-zoom]').forEach(b => {
      b.onclick = () => this._zoomPhoto(b.dataset.ppPhotoZoom);
    });
    if (fileInput) {
      fileInput.onchange = (e) => {
        const f = e.target.files && e.target.files[0];
        if (f) this._onPhotoChosen(f);
      };
    }

    // Focus auto sur le champ en cours d'édition
    if (this.state.edit && this.state.edit.kind === 'field') {
      const focusEl = panel.querySelector('[data-pp-field-input]');
      if (focusEl) {
        focusEl.focus();
        try { if (focusEl.setSelectionRange) focusEl.setSelectionRange(focusEl.value.length, focusEl.value.length); } catch (e) {}
      }
    }
  },

  // ----- BLOC PAIEMENT -----
  _paymentBlock(intake) {
    const data = intake.data || {};
    const opt = intake.selected_option || data.selected_option || 'base';
    const f = this.FORMULES[opt] || null;
    const paid = !!intake.stripe_paid_at || ['paid', 'building', 'live'].indexOf(intake.status) !== -1;
    const paidWhen = intake.stripe_paid_at ? this._fmtDate(intake.stripe_paid_at) : '';
    const manual = paid && !intake.stripe_session_id;

    const status = paid
      ? `<div class="pp-pay-status ok">
           <span class="pp-pay-ico">✅</span>
           <div><div class="pp-pay-status-main">Paiement reçu</div>
           <div class="pp-pay-status-sub">${paidWhen ? 'Le ' + this._escape(paidWhen) : ''}${manual ? ' · validé manuellement' : ' · payé en ligne par carte'}</div></div>
         </div>`
      : `<div class="pp-pay-status wait">
           <span class="pp-pay-ico">⏳</span>
           <div><div class="pp-pay-status-main">Pas encore payé</div>
           <div class="pp-pay-status-sub">Le client a rempli le formulaire mais n’a pas réglé.</div></div>
         </div>`;

    const includes = (f && f.includes)
      ? `<ul class="pp-pay-includes">${f.includes.map(i => `<li>${this._escape(i)}</li>`).join('')}</ul>` : '';

    return `
      <div class="pp-detail-section">
        <div class="pp-detail-section-title">Paiement &amp; formule</div>
        ${status}
        <div class="pp-pay-formule" style="--fc:${f ? f.color : '#94a3b8'};">
          <div class="pp-pay-formule-head">
            <span class="pp-pay-formule-name">${f ? this._escape(f.label) : this._escape(opt)}</span>
            <span class="pp-pay-formule-price">${f ? this._escape(f.price) : ''}</span>
          </div>
          ${includes}
        </div>
      </div>`;
  },

  // ----- BLOC INFOS DU FORMULAIRE -----
  _formBlock(intake) {
    const data = intake.data || {};
    const sections = this.SECTIONS.map((sec, idx) => this._sectionHtml(sec, idx, data)).join('');
    // L'aide cite le VRAI libellé du bouton de fabrication pour ce statut
    // (« Reconstruire le site » n'existe que pour un site déjà en ligne).
    const st = intake.status;
    const buildBtnLabel = st === 'live' ? 'Reconstruire le site'
      : st === 'failed' ? 'Relancer la construction'
      : st === 'building' ? 'Forcer une nouvelle tentative'
      : st === 'draft' ? 'Lancer la construction tout de suite'
      : 'Lancer la construction';
    return `
      <div class="pp-detail-section">
        <div class="pp-detail-section-title">Tout ce que le client a rempli</div>
        <div class="pp-form-hint">✏️ Tu peux corriger chaque texte. C’est enregistré aussitôt — pour que ça passe sur le site en ligne, clique ensuite sur « ${this._escape(buildBtnLabel)} » plus haut.</div>
        ${sections}
      </div>`;
  },

  _sectionHtml(sec, idx, data) {
    if (sec.onlyIf) {
      const v = data[sec.onlyIf];
      if (v == null || String(v).trim() === '') return '';
    }
    const hasToggle = !!sec.key;
    const active = !hasToggle || data[sec.key] === 'on';

    const head = `
      <div class="pp-rub-head">
        <span class="pp-rub-title">${sec.icon} ${this._escape(sec.title)}</span>
        ${hasToggle ? `<button class="pp-rub-toggle ${active ? 'on' : 'off'}" data-pp-toggle-section="${sec.key}" title="${active ? 'Affichée sur le site — clique pour masquer' : 'Masquée — clique pour afficher'}">${active ? '👁 Affichée' : '🚫 Masquée'}</button>` : ''}
      </div>`;

    if (hasToggle && !active) {
      return `<div class="pp-rub off">${head}<div class="pp-rub-off-note">Rubrique non affichée sur le site du client.</div></div>`;
    }

    let body = '';
    if (sec.fields) body += sec.fields.map(f => this._fieldHtml(f, data)).join('');
    if (sec.list) body += this._listHtml(sec, idx, data);
    if (sec.socials) body += this._socialsHtml(data);
    if (sec.photoKind) body += `<div class="pp-rub-photonote">📷 Photos de cette rubrique : voir « Photos envoyées par le client » plus bas.</div>`;

    return `<div class="pp-rub">${head}<div class="pp-rub-body">${body}</div></div>`;
  },

  _fieldHtml(field, data) {
    const raw = data[field.key];
    const editing = this.state.edit && this.state.edit.kind === 'field' && this.state.edit.key === field.key;
    if (editing) return this._fieldEditor(field, raw);

    if (field.type === 'bool') {
      const on = raw === 'on' || raw === true;
      return `
        <div class="pp-field">
          <div class="pp-field-label">${this._escape(field.label)}</div>
          <div class="pp-field-val">
            <span class="pp-bool ${on ? 'on' : 'off'}">${on ? '✓ Oui' : 'Non'}</span>
            <button class="pp-mini-btn" data-pp-toggle-bool="${field.key}" title="Changer">${on ? 'Mettre Non' : 'Mettre Oui'}</button>
          </div>
        </div>`;
    }

    let display;
    if (field.type === 'color') {
      display = raw
        ? `<span class="pp-field-text">${this._escape(this.COLOR_LABELS[raw] || raw)}</span>`
        : '<span class="pp-empty">— vide</span>';
    } else {
      const v = (raw == null ? '' : String(raw)).trim();
      display = v
        ? `<span class="pp-field-text ${field.type === 'long' ? 'multiline' : ''}">${this._escape(v)}</span>`
        : '<span class="pp-empty">— vide</span>';
    }
    return `
      <div class="pp-field">
        <div class="pp-field-label">${this._escape(field.label)}</div>
        <div class="pp-field-val">
          ${display}
          <button class="pp-mini-btn" data-pp-edit-field="${field.key}" title="Modifier">✏️</button>
        </div>
      </div>`;
  },

  _fieldEditor(field, raw) {
    // Reprend le brouillon capturé si la fiche a été re-rendue en cours de frappe.
    const draft = (this.state.edit && this.state.edit.draft != null) ? this.state.edit.draft : null;
    const v = draft != null ? String(draft) : (raw == null ? '' : String(raw));
    let input;
    if (field.type === 'color') {
      const cur = draft != null ? draft : raw;
      const opts = Object.keys(this.COLOR_LABELS).map(k =>
        `<option value="${k}" ${k === cur ? 'selected' : ''}>${this._escape(this.COLOR_LABELS[k])}</option>`).join('');
      input = `<select class="pp-edit-input" data-pp-field-input>${opts}</select>`;
    } else if (field.type === 'long') {
      input = `<textarea class="pp-mail-textarea" rows="4" data-pp-field-input>${this._escape(v)}</textarea>`;
    } else {
      input = `<input type="text" class="pp-edit-input" value="${this._escape(v)}" data-pp-field-input />`;
    }
    return `
      <div class="pp-field editing">
        <div class="pp-field-label">${this._escape(field.label)}</div>
        <div class="pp-field-edit">
          ${input}
          <div class="pp-edit-row-actions">
            <button class="pp-action-btn primary" data-pp-field-save="${field.key}">Enregistrer</button>
            <button class="pp-action-btn secondary" data-pp-field-cancel>Annuler</button>
          </div>
        </div>
      </div>`;
  },

  // ----- LISTES (services, avis, horaires…) -----
  _listRows(cols, data) {
    const arrays = cols.map(c => {
      const v = data[c.key];
      if (Array.isArray(v)) return v;
      if (v == null || v === '') return [];
      return [v];
    });
    const n = arrays.reduce((m, a) => Math.max(m, a.length), 0);
    const rows = [];
    for (let i = 0; i < n; i++) {
      rows.push(cols.map((c, ci) => {
        const cell = arrays[ci][i];
        return cell == null ? '' : String(cell);
      }));
    }
    return rows;
  },

  _listHtml(sec, idx, data) {
    const cols = sec.list.cols;
    const editing = this.state.edit && this.state.edit.kind === 'list' && this.state.edit.sectionIdx === idx;

    if (editing) {
      const rows = this.state.editRows || [];
      const rowsHtml = rows.map((row, ri) => `
        <div class="pp-list-edit-row" data-row="${ri}">
          ${cols.map((c, ci) => c.type === 'long'
            ? `<textarea class="pp-mail-textarea" rows="2" data-pp-list-cell data-ci="${ci}" placeholder="${this._escape(c.label)}">${this._escape(row[ci] || '')}</textarea>`
            : `<input type="text" class="pp-edit-input" data-pp-list-cell data-ci="${ci}" placeholder="${this._escape(c.label)}" value="${this._escape(row[ci] || '')}" />`).join('')}
          <button class="pp-mini-btn danger" data-pp-list-del="${ri}" title="Retirer cette ligne">🗑</button>
        </div>`).join('');
      return `
        <div class="pp-list editing">
          ${rowsHtml || '<div class="pp-empty">Aucune ligne — ajoutes-en une.</div>'}
          <div class="pp-list-edit-actions">
            <button class="pp-mini-btn" data-pp-list-add>＋ ${this._escape(sec.list.addLabel || 'Ajouter')}</button>
            <div style="flex:1"></div>
            <button class="pp-action-btn primary" data-pp-list-save>Enregistrer la liste</button>
            <button class="pp-action-btn secondary" data-pp-list-cancel>Annuler</button>
          </div>
        </div>`;
    }

    const rows = this._listRows(cols, data).filter(r => r.some(c => c.trim() !== ''));
    const body = rows.length
      ? rows.map(row => `
          <div class="pp-list-row">
            ${cols.map((c, ci) => {
              const val = (row[ci] || '').trim();
              if (!val) return '';
              return `<div class="pp-list-cell"><span class="pp-list-cell-lbl">${this._escape(c.label)}</span><span class="pp-list-cell-val ${c.type === 'long' ? 'multiline' : ''}">${this._escape(val)}</span></div>`;
            }).join('')}
          </div>`).join('')
      : '<div class="pp-empty">Aucune entrée.</div>';
    return `
      <div class="pp-list">
        ${body}
        <button class="pp-mini-btn" data-pp-edit-list="${idx}" title="Modifier la liste">✏️ Modifier la liste</button>
      </div>`;
  },

  // ----- RÉSEAUX SOCIAUX -----
  _socialsHtml(data) {
    const editing = this.state.edit && this.state.edit.kind === 'socials';
    if (editing) {
      // Reprend le brouillon capturé si la fiche a été re-rendue en cours d'édition.
      const draft = (this.state.edit && this.state.edit.draft) || null;
      const rows = this.SOCIALS.map(s => {
        const on = draft ? !!(draft[s.key] && draft[s.key].on) : data['social-' + s.key + '-on'] === 'on';
        const url = draft ? ((draft[s.key] && draft[s.key].url) || '') : (data['social-' + s.key + '-url'] || '');
        return `
          <div class="pp-social-edit-row">
            <label class="pp-social-check"><input type="checkbox" data-pp-social-on="${s.key}" ${on ? 'checked' : ''} /> ${this._escape(s.label)}</label>
            <input type="text" class="pp-edit-input" data-pp-social-url="${s.key}" placeholder="Lien / numéro" value="${this._escape(url)}" />
          </div>`;
      }).join('');
      return `
        <div class="pp-socials editing">
          ${rows}
          <div class="pp-list-edit-actions">
            <div style="flex:1"></div>
            <button class="pp-action-btn primary" data-pp-socials-save>Enregistrer</button>
            <button class="pp-action-btn secondary" data-pp-socials-cancel>Annuler</button>
          </div>
        </div>`;
    }
    const active = this.SOCIALS.filter(s => data['social-' + s.key + '-on'] === 'on');
    const body = active.length
      ? active.map(s => {
          const url = (data['social-' + s.key + '-url'] || '').trim();
          return `<div class="pp-list-row"><div class="pp-list-cell"><span class="pp-list-cell-lbl">${this._escape(s.label)}</span><span class="pp-list-cell-val">${url ? this._escape(url) : '<span class="pp-empty">activé, sans lien</span>'}</span></div></div>`;
        }).join('')
      : '<div class="pp-empty">Aucun réseau activé.</div>';
    return `<div class="pp-socials">${body}<button class="pp-mini-btn" data-pp-edit-socials>✏️ Modifier les réseaux</button></div>`;
  },

  // ----- BLOC PHOTOS -----
  _photosBlock(intake) {
    const photos = Array.isArray(intake.photos) ? intake.photos : [];
    const groups = this.PHOTO_GROUPS.map(g => {
      const items = photos.filter(p => p && p.kind === g.kind);
      return this._photoGroupHtml(g, items);
    }).join('');
    return `
      <div class="pp-detail-section">
        <div class="pp-detail-section-title">Photos envoyées par le client (${photos.length})</div>
        <div class="pp-photos">${groups}</div>
      </div>`;
  },

  _photoGroupHtml(g, items) {
    const thumbs = items.map(p => `
      <div class="pp-photo-thumb">
        <img src="${this._escape(p.url)}" alt="${this._escape(p.original_name || g.label)}" loading="lazy" data-pp-photo-zoom="${this._escape(p.url)}" />
        <div class="pp-photo-acts">
          <button class="pp-photo-act" data-pp-photo-replace="${this._escape(p.path)}" data-kind="${this._escape(g.kind)}" title="Remplacer">🔁</button>
          <button class="pp-photo-act danger" data-pp-photo-del="${this._escape(p.path)}" title="Supprimer">🗑</button>
        </div>
      </div>`).join('');
    const canAdd = items.length < (g.max || 99);
    const addBtn = canAdd
      ? `<button class="pp-photo-add" data-pp-photo-add="${this._escape(g.kind)}" title="Ajouter une photo">＋<span>Ajouter</span></button>` : '';
    return `
      <div class="pp-photo-group">
        <div class="pp-photo-group-head">
          <span class="pp-photo-group-title">${this._escape(g.label)}</span>
          <span class="pp-photo-group-count">${items.length}${g.max ? ' / ' + g.max : ''}</span>
        </div>
        <div class="pp-photo-grid">
          ${thumbs}${addBtn}${items.length === 0 ? '<span class="pp-photo-empty">Aucune photo</span>' : ''}
        </div>
      </div>`;
  },

  // ----- SAUVEGARDES -----
  async _saveField(id, key) {
    const panel = document.getElementById('pp-detail');
    const input = panel.querySelector('[data-pp-field-input]');
    if (!input) return;
    const res = await this._call('pixelpros_update_data', { id, patch: { [key]: input.value } });
    if (res && res.ok) { this.state.edit = null; this._toast('Modifié ✓'); await this.refresh(); }
    else this._failToast('La modification n’a pas pu être enregistrée.', res);
  },

  async _toggleBool(id, key) {
    // Si une autre saisie est en cours dans la fiche, on la met de côté
    // d'abord : le refresh re-rend la fiche et la restituera telle quelle.
    this._captureEditBuffer();
    const data = (this.state.detail && this.state.detail.intake.data) || {};
    const on = data[key] === 'on';
    const patch = {};
    patch[key] = on ? null : 'on';
    const res = await this._call('pixelpros_update_data', { id, patch });
    if (res && res.ok) { this._toast(on ? 'Désactivé' : 'Activé'); await this.refresh(); }
    else this._failToast('Le changement n’a pas pu être enregistré.', res);
  },

  _syncListBuffer(panel, ncols) {
    if (!this.state.editRows) return;
    const rows = [];
    panel.querySelectorAll('.pp-list-edit-row').forEach(rowEl => {
      const cells = new Array(ncols).fill('');
      rowEl.querySelectorAll('[data-pp-list-cell]').forEach(cell => {
        const ci = parseInt(cell.dataset.ci, 10);
        if (!isNaN(ci)) cells[ci] = cell.value;
      });
      rows.push(cells);
    });
    this.state.editRows = rows;
  },

  async _saveList(id) {
    const panel = document.getElementById('pp-detail');
    const sec = this.SECTIONS[this.state.edit.sectionIdx];
    const cols = sec.list.cols;
    this._syncListBuffer(panel, cols.length);
    let rows = (this.state.editRows || []).filter(r => r.some(c => (c || '').trim() !== ''));
    const patch = {};
    cols.forEach((c, ci) => { patch[c.key] = rows.map(r => r[ci] || ''); });
    const res = await this._call('pixelpros_update_data', { id, patch });
    if (res && res.ok) { this.state.edit = null; this.state.editRows = null; this._toast('Liste enregistrée ✓'); await this.refresh(); }
    else this._failToast('La liste n’a pas pu être enregistrée.', res);
  },

  async _saveSocials(id) {
    const panel = document.getElementById('pp-detail');
    const patch = {};
    this.SOCIALS.forEach(s => {
      const onEl = panel.querySelector('[data-pp-social-on="' + s.key + '"]');
      const urlEl = panel.querySelector('[data-pp-social-url="' + s.key + '"]');
      patch['social-' + s.key + '-on'] = (onEl && onEl.checked) ? 'on' : null;
      patch['social-' + s.key + '-url'] = urlEl ? urlEl.value.trim() : '';
    });
    const res = await this._call('pixelpros_update_data', { id, patch });
    if (res && res.ok) { this.state.edit = null; this._toast('Réseaux enregistrés ✓'); await this.refresh(); }
    else this._failToast('Les réseaux n’ont pas pu être enregistrés.', res);
  },

  // ----- PHOTOS : upload / suppression / zoom -----
  async _onPhotoChosen(file) {
    const ctx = this._photoCtx;
    if (!ctx || !file) return;
    if (file.size > 10 * 1024 * 1024) { this._toast('Photo trop lourde (10 Mo maximum)', true); return; }
    if (typeof Toast !== 'undefined') Toast.info('Envoi de la photo…');
    let b64;
    try { b64 = await this._fileToDataUrl(file); }
    catch (e) { this._toast('Lecture du fichier impossible', true); return; }
    const res = await this._call('pixelpros_upload_photo', {
      id: ctx.id, kind: ctx.kind, filename: file.name, content_base64: b64,
    });
    if (!res || !res.ok) { this._failToast('La photo n’a pas pu être envoyée.', res); return; }
    if (ctx.replacePath) {
      // Remplacement : on vérifie que l'ancienne photo a bien été retirée,
      // sinon elle resterait en double sans qu'on le sache.
      const del = await this._call('pixelpros_delete_photo', { id: ctx.id, path: ctx.replacePath });
      if (del && del.ok) {
        this._toast('Photo remplacée ✓');
      } else {
        console.warn('pixelpros: suppression de l’ancienne photo échouée —', del);
        if (typeof Toast !== 'undefined') {
          Toast.warn('La nouvelle photo est en ligne, mais l’ancienne n’a pas pu être retirée — supprime-la à la main si tu la vois en double.');
        }
      }
    } else {
      this._toast('Photo ajoutée ✓');
    }
    this._photoCtx = null;
    await this.refresh();
  },

  _fileToDataUrl(file) {
    return new Promise((resolve, reject) => {
      const fr = new FileReader();
      fr.onload = () => resolve(fr.result);
      fr.onerror = () => reject(fr.error);
      fr.readAsDataURL(file);
    });
  },

  async _deletePhoto(id, path) {
    const ok = await Dialog.confirm('Supprimer définitivement cette photo ?',
      { title: 'Supprimer la photo', okLabel: 'Supprimer', danger: true });
    if (!ok) return;
    const res = await this._call('pixelpros_delete_photo', { id, path });
    if (res && res.ok) { this._toast('Photo supprimée'); await this.refresh(); }
    else this._failToast('La photo n’a pas pu être supprimée.', res);
  },

  _zoomPhoto(url) {
    const ov = document.createElement('div');
    ov.className = 'pp-lightbox';
    ov.innerHTML = `<img src="${this._escape(url)}" alt="" /><button class="pp-lightbox-close" aria-label="Fermer">×</button>`;
    ov.onclick = () => ov.remove();
    document.body.appendChild(ov);
  },

  // Mini-dialog pour modifier email/téléphone d'un intake.
  async _editContact(intake) {
    const data = intake.data || {};
    const currentEmail = data.email || '';
    const currentPhone = data.phone || '';

    const overlay = document.createElement('div');
    overlay.className = 'pp-edit-overlay';
    overlay.innerHTML = `
      <div class="pp-edit-dialog">
        <div class="pp-edit-title">Modifier le contact</div>
        <label class="pp-edit-label">Adresse mail
          <input type="email" id="pp-edit-email" class="pp-edit-input" value="${this._escape(currentEmail)}" placeholder="email@exemple.fr" />
        </label>
        <label class="pp-edit-label">Téléphone <span class="pp-edit-hint">(optionnel)</span>
          <input type="tel" id="pp-edit-phone" class="pp-edit-input" value="${this._escape(currentPhone)}" placeholder="06 12 34 56 78" />
        </label>
        <div class="pp-edit-actions">
          <button class="pp-action-btn secondary" data-pp-edit-cancel>Annuler</button>
          <button class="pp-action-btn primary" data-pp-edit-save>Enregistrer</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);

    const close = () => overlay.remove();
    // Fermeture par clic à côté (ou Échap, via _onEscape) : si quelque chose
    // a été modifié, on demande avant de jeter la saisie.
    const isDirty = () =>
      overlay.querySelector('#pp-edit-email').value.trim() !== String(currentEmail).trim() ||
      overlay.querySelector('#pp-edit-phone').value.trim() !== String(currentPhone).trim();
    const requestClose = async () => {
      if (isDirty()) {
        const ok = await Dialog.confirm('Abandonner les modifications du contact ?',
          { title: 'Modifications non enregistrées', okLabel: 'Abandonner', danger: true });
        if (!ok) return;
      }
      close();
    };
    overlay._ppRequestClose = requestClose;   // utilisé par la touche Échap
    overlay.onclick = (e) => { if (e.target === overlay) requestClose(); };
    overlay.querySelector('[data-pp-edit-cancel]').onclick = close;
    overlay.querySelector('#pp-edit-email').focus();

    overlay.querySelector('[data-pp-edit-save]').onclick = async () => {
      const newEmail = overlay.querySelector('#pp-edit-email').value.trim();
      const newPhone = overlay.querySelector('#pp-edit-phone').value.trim();
      if (newEmail && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(newEmail)) {
        this._toast('Adresse mail invalide', true);
        return;
      }
      // Vider l'adresse n'est presque jamais voulu : sans elle, plus aucun
      // mail ne peut partir vers ce client → confirmation explicite.
      if (!newEmail && String(currentEmail).trim()) {
        const sure = await Dialog.confirm(
          'Tu es en train d’EFFACER l’adresse email du client — confirmer ?\n\nSans adresse, plus aucun mail ne pourra lui être envoyé.',
          { title: 'Adresse email vide', okLabel: 'Effacer l’adresse', danger: true });
        if (!sure) return;
      }
      const saveBtn = overlay.querySelector('[data-pp-edit-save]');
      saveBtn.disabled = true;
      saveBtn.textContent = '…';
      const res = await this._call('pixelpros_update_contact', {
        id: intake.id,
        email: newEmail,
        phone: newPhone,
      });
      if (res && res.ok) {
        this._toast('Contact mis à jour');
        close();
        await this._loadDetail(intake.id);
        await this.refresh();
      } else {
        this._failToast('Le contact n’a pas pu être mis à jour.', res);
        saveBtn.disabled = false;
        saveBtn.textContent = 'Enregistrer';
      }
    };
  },

  _availableActions(intake) {
    const out = [];
    const st = intake.status;
    // Pour un formulaire pas (encore) payé : override manuel possible
    // pour tester, encaisser hors-Stripe ou faire un geste commercial.
    if (st === 'draft') {
      out.push(`<button data-pp-action="simulate_full_flow" class="pp-action-btn primary">▶ Tout déclencher comme un vrai paiement (mails + fabrication)</button>`);
      out.push(`<button data-pp-action="force_build" class="pp-action-btn secondary">▶ Lancer la construction tout de suite</button>`);
      out.push(`<button data-pp-action="mark_paid_manual" class="pp-action-btn secondary">💳 Marquer comme payé (sans construire)</button>`);
    }
    if (st === 'paid' || st === 'failed' || st === 'building' || st === 'live') {
      const label = st === 'paid'   ? '▶ Lancer la construction'
                  : st === 'failed' ? '↻ Relancer la construction'
                  : st === 'live'   ? '↻ Reconstruire le site'
                  : '↻ Forcer une nouvelle tentative';
      out.push(`<button data-pp-action="dispatch" class="pp-action-btn primary">${label}</button>`);
    }
    if (st === 'building' || st === 'paid') {
      out.push(`<button data-pp-action="mark_failed" class="pp-action-btn danger">Marquer comme échec</button>`);
    }
    if (st !== 'draft') {
      out.push(`<button data-pp-action="resend_paid_mail" class="pp-action-btn secondary">📧 Renvoyer mail "paiement reçu"</button>`);
    }
    if (st === 'live') {
      out.push(`<button data-pp-action="resend_live_mail" class="pp-action-btn secondary">📧 Renvoyer mail "site en ligne"</button>`);
    }
    out.push(`<button data-pp-action="delete" class="pp-action-btn danger">🗑 Supprimer définitivement</button>`);
    return out;
  },

  // Toutes les actions réelles passent ici. `btn` (facultatif) = le bouton
  // cliqué : désactivé pendant l'appel (anti double-clic), réactivé ensuite.
  async _doAction(action, intake, btn) {
    const id = intake.id;
    const data = intake.data || {};
    const name = data.business_name || data['business-name'] || intake.business_name || '(sans nom)';
    let res = null;
    if (btn) btn.disabled = true;
    try {
      switch (action) {
        case 'simulate_full_flow': {
          const email = data.email || intake.email || '—';
          const ok = await Dialog.confirm(
            `${name}\n${email}\n\n` +
            `Le client va recevoir le mail "paiement reçu" et le site va commencer à se fabriquer. ` +
            `Le mail "site en ligne" partira automatiquement quand le site sera prêt.\n\n` +
            `À utiliser pour : tester le parcours complet, encaisser hors-Stripe, faire un geste commercial.`,
            { title: 'Tout déclencher comme un vrai paiement ?', okLabel: 'Tout déclencher' });
          if (!ok) return;
          res = await this._call('pixelpros_simulate_full_flow', { id });
          if (res?.ok) {
            this._toast('🚀 Tout est lancé — le client reçoit le mail, le site se fabrique');
          } else {
            const detail = (res?.steps || []).filter(s => !s.ok).map(s => `${s.step}: ${s.message}`).join(' · ');
            console.warn('pixelpros simulate_full_flow', res);
            this._toast(`Lancé, mais un maillon a échoué : ${detail || 'détail technique dans la console'}`, true);
          }
          break;
        }
        case 'mark_paid_manual': {
          const ok = await Dialog.confirm(
            `${name}\n\n` +
            `Le client passera dans la colonne "Payés". Aucun mail ne lui sera envoyé automatiquement — ` +
            `tu pourras le faire à la main depuis le panneau de détail si tu veux.`,
            { title: 'Marquer comme payé manuellement ?', okLabel: 'Marquer payé' });
          if (!ok) return;
          res = await this._call('pixelpros_mark_paid_manual', { id });
          if (res?.ok) this._toast(`Marqué comme payé : ${res.message || ''}`.trim());
          else this._failToast('Le marquage « payé » a échoué.', res);
          break;
        }
        case 'force_build': {
          const ok = await Dialog.confirm(
            `${name}\n\n` +
            `Le statut va passer en "Payé" puis "En construction". Le site sera en ligne dans 1-2 min.\n\n` +
            `À utiliser pour tester, encaisser hors-Stripe ou faire un geste commercial.`,
            { title: 'Construire le site maintenant (sans attendre le paiement) ?', okLabel: 'Construire maintenant' });
          if (!ok) return;
          // Étape 1 : marquer payé manuellement
          const r1 = await this._call('pixelpros_mark_paid_manual', { id });
          if (!r1 || !r1.ok) {
            this._failToast('Le marquage « payé » a échoué — rien n’a été lancé.', r1);
            break;
          }
          // Étape 2 : lancer la fabrication
          res = await this._call('pixelpros_dispatch_build', { id });
          if (res?.ok) this._toast(`Fabrication lancée : ${res.message || ''}`.trim());
          else this._failToast('La fabrication n’a pas pu être lancée.', res);
          break;
        }
        case 'dispatch': {
          const isRebuild = intake.status === 'live';
          const ok = await Dialog.confirm(
            isRebuild
              ? `${name}\n\nLe site sera regénéré avec les infos actuelles de la fiche, puis remis en ligne (1-2 min).`
              : `${name}\n\nLe site sera fabriqué puis mis en ligne automatiquement (1-2 min).`,
            { title: isRebuild ? 'Reconstruire le site ?' : 'Lancer la construction ?',
              okLabel: isRebuild ? 'Reconstruire' : 'Lancer' });
          if (!ok) return;
          res = await this._call('pixelpros_dispatch_build', { id });
          if (res?.ok) this._toast(`Fabrication lancée : ${res.message || ''}`.trim());
          else this._failToast('La fabrication n’a pas pu être lancée.', res);
          break;
        }
        case 'mark_failed': {
          const reason = prompt('Raison de l’échec (optionnel) :', '');
          if (reason === null) return;   // Annuler = on ne fait rien
          res = await this._call('pixelpros_mark_failed', { id, reason });
          if (res?.ok) this._toast('Marqué comme échec');
          else this._failToast('Impossible de marquer en échec.', res);
          break;
        }
        case 'resend_paid_mail': {
          const ok = await Dialog.confirm('Renvoyer ce mail au client ?',
            { title: 'Renvoyer le mail "paiement reçu"', okLabel: 'Renvoyer' });
          if (!ok) return;
          res = await this._call('pixelpros_resend_paid_mail', { id });
          if (res?.ok) this._toast(`Mail "paiement reçu" renvoyé ✓ ${res.message || ''}`.trim());
          else this._failToast('Le mail n’a pas pu être envoyé.', res);
          break;
        }
        case 'resend_live_mail': {
          const ok = await Dialog.confirm('Renvoyer ce mail au client ?',
            { title: 'Renvoyer le mail "site en ligne"', okLabel: 'Renvoyer' });
          if (!ok) return;
          res = await this._call('pixelpros_resend_live_mail', { id });
          if (res?.ok) this._toast(`Mail "site en ligne" renvoyé ✓ ${res.message || ''}`.trim());
          else this._failToast('Le mail n’a pas pu être envoyé.', res);
          break;
        }
        case 'reply_mail': {
          const mail = (data.email || intake.email || '').trim();
          if (!mail) { this._toast('Pas d’adresse mail pour ce contact.', true); return; }
          if (typeof Mails === 'undefined' || !Mails._openComposer) {
            this._toast('Ouvre d’abord l’écran Mails, puis reviens cliquer Répondre.', true);
            return;
          }
          // La fiche du contact est posée très haut (z-index 1000) alors que la
          // fenêtre de rédaction est plus basse : sans ça, elle s'ouvrirait
          // derrière la fiche. On ferme donc la fiche avant d'ouvrir le mail.
          this._closeDetail();
          Mails._openComposer({
            prefilledTo: mail,
            prefilledSubject: 'Votre message – Pixel Pros',
            title: 'Répondre',
          });
          return;
        }
        case 'mark_handled': {
          // Rangement côté SERVEUR (partagé entre appareils) : la fiche
          // reste en base, elle quitte juste l'onglet Contact.
          res = await this._call('pixelpros_mark_contact_handled', { id });
          if (res?.ok) {
            this._toast('Fiche rangée — elle n’apparaît plus dans l’onglet Contact.');
            this._closeDetail();
          } else {
            this._failToast('Impossible de ranger cette fiche.', res);
          }
          break;
        }
        case 'delete': {
          const statusLabel = this._statusLabel(intake.status);
          const warn = intake.status === 'live'
            ? `⚠ Ce formulaire est en statut "En ligne" (site déployé).\nLe supprimer perd l'historique mais NE FERME PAS le site en ligne (à faire séparément).\n\n`
            : '';
          const ok = await Dialog.confirm(
            `${warn}${name}\nStatut : ${statusLabel}\n\nCette action est irréversible.`,
            { title: 'Supprimer définitivement ce formulaire ?', okLabel: 'Supprimer définitivement', danger: true });
          if (!ok) return;
          res = await this._call('pixelpros_delete_intake', { id });
          if (res?.ok) { this._toast(`Supprimé : ${res.message || ''}`.trim()); this._closeDetail(); }
          else this._failToast('La suppression a échoué.', res);
          break;
        }
      }
    } finally {
      if (btn) btn.disabled = false;
    }
    await this.refresh();
  },

  // ----- HELPERS -----
  async _call(method, payload) {
    if (!App || !App.api || typeof App.api[method] !== 'function') {
      console.warn(`pixelpros: API.${method} introuvable`);
      return { ok: false, error: 'API absente' };
    }
    try { return await App.api[method](payload); }
    catch (e) { console.warn('pixelpros._call', method, e); return { ok: false, error: String(e) }; }
  },

  // Libellés français des statuts (pastille de détail, confirmations…).
  // Couvre aussi « failed », qui n'a pas de colonne Kanban.
  _statusMeta(status) {
    const col = this.COLUMNS.find(c => c.status === status);
    if (col) return col;
    if (status === 'failed') return { status: 'failed', label: 'En échec', short: 'En échec', icon: '⚠', accent: '#ef4444' };
    return { status, label: status || 'inconnu', short: status || '?', icon: '•', accent: '#94a3b8' };
  },
  _statusLabel(status) { return this._statusMeta(status).label; },

  // La chronologie serveur parle technique (« draft », « Status courant »,
  // référence Stripe…) : table de correspondance vers du français clair.
  _timelineLabel(ev, intake) {
    switch (ev.kind) {
      case 'submitted': return 'Formulaire reçu';
      case 'paid':      return 'Paiement reçu';
      case 'built':     return 'Site en ligne' + (intake.site_url ? ' — ' + intake.site_url : '');
      case 'error': {
        let err = String((intake.data || {}).error || '').trim();
        if (err.length > 160) err = err.slice(0, 160) + '…';
        return 'Échec de fabrication' + (err ? ' : ' + err : '');
      }
      case 'current':
        if (intake.status === 'building') return 'Fabrication lancée';
        return 'Aujourd’hui : ' + this._statusLabel(intake.status);
      default:
        return ev.label || '';
    }
  },

  // ----- Fiches Contact « traitées » -----
  // Le marqueur vit côté serveur (data.handled_at — partagé entre appareils,
  // via pixelpros_mark_contact_handled). L'ancienne mémoire navigateur
  // (pp_handled_contacts) reste LUE pour ne pas faire réapparaître les
  // fiches rangées avant la bascule — on n'y écrit plus.
  HANDLED_KEY: 'pp_handled_contacts',
  _handledIds() {
    try { return new Set(JSON.parse(localStorage.getItem(this.HANDLED_KEY) || '[]')); }
    catch (e) { return new Set(); }
  },

  // Touche Échap : ferme la couche la plus « au-dessus » d'abord.
  // (Les boîtes Dialog.confirm gèrent leur propre Échap et ne laissent pas
  // l'événement arriver jusqu'ici.)
  _onEscape() {
    const lightbox = document.querySelector('.pp-lightbox');
    if (lightbox) { lightbox.remove(); return; }
    const editOverlay = document.querySelector('.pp-edit-overlay');
    if (editOverlay) {
      if (typeof editOverlay._ppRequestClose === 'function') editOverlay._ppRequestClose();
      else editOverlay.remove();
      return;
    }
    const mailPanel = document.getElementById('pp-mail-panel');
    if (mailPanel && !mailPanel.hidden) { this._closeMailEditor(); return; }
    const detail = document.getElementById('pp-detail');
    if (detail && !detail.hidden) { this._requestCloseDetail(); }
  },

  _hoursSince(ts) {
    if (!ts) return 0;
    try {
      const d = new Date(ts);
      if (isNaN(d.getTime())) return 0;
      return (Date.now() - d.getTime()) / 36e5;
    } catch { return 0; }
  },

  _timeRelative(ts) {
    if (!ts) return '—';
    const h = this._hoursSince(ts);
    if (h < 1)   return `il y a ${Math.max(1, Math.round(h * 60))} min`;
    if (h < 24)  return `il y a ${Math.round(h)} h`;
    const d = Math.round(h / 24);
    if (d < 30) return `il y a ${d} j`;
    return this._fmtDate(ts);
  },

  _fmtDate(s) {
    if (!s) return '—';
    try {
      const d = new Date(s);
      if (isNaN(d.getTime())) return s;
      return d.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', year: '2-digit' }) +
             ' ' + d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
    } catch { return s; }
  },

  _colorFromName(name) {
    // Palette pastel cohérente, hash simple sur le nom.
    const palette = ['#facc15', '#22c55e', '#0ea5e9', '#a855f7', '#ec4899', '#f97316', '#14b8a6', '#f43f5e'];
    let h = 0;
    const s = String(name || '');
    for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
    return palette[Math.abs(h) % palette.length];
  },

  _escape(s) {
    return String(s ?? '').replace(/[&<>"']/g, ch => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[ch]));
  },

  // Petits messages : délégués au système Toast commun (empilement propre,
  // thèmes, accessibilité gérés là-bas — plus de toast maison superposé).
  _toast(msg, isError = false) {
    if (typeof Toast !== 'undefined' && Toast) {
      if (isError) Toast.error(msg); else Toast.success(msg);
      return;
    }
    console.log('[pixelpros]', msg);
  },

  // Échec d'action : phrase humaine courte ; le détail technique part en
  // console (les messages serveur courts et français restent affichés).
  _failToast(human, res) {
    console.warn('[pixelpros]', human, res);
    const detail = res && (res.error || res.message);
    const showDetail = detail && String(detail).length <= 120 &&
      !/Traceback|Exception|Error\b|HTTP \d|at .*:\d/i.test(String(detail));
    this._toast(showDetail ? `${human} (${detail})` : human, true);
  },
};
