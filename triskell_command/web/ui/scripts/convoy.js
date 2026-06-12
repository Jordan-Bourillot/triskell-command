/* Vue « Importer une liste » (Le Convoi) — version web Apple-clear.
 *
 * Flux à 5 étapes, exactement comme la version desktop :
 *   1. Import   — drop / parcourir → extraction du texte
 *   2. Vérifier — tableau éditable des prospects extraits
 *   3. Composer — catalogue + brief IA → génération des mails
 *   4. Envoyer  — mode auto/validation + cap + délai + lancement
 *   5. Résultats— suivi des brouillons (approuver / rejeter / éditer)
 *
 * La persistance vit côté Python (convoy_runner — Supabase ou disque).
 * Cette vue ne fait que dialoguer avec App.api.convoy_*().
 */

const Convoy = {
  _LS_SELECTED: 'convoy:selected',
  campaigns: [],          // résumé des campagnes (gauche)
  selected:  null,        // campaign_id sélectionnée
  detail:    null,        // campagne complète (drafts inclus)
  raw:       null,        // dernier upload : {format, filename, text_preview, fast_path_prospects, ...}
  genPoll:   null,
  genSeen:   0,
  sendPoll:  null,
  sendSeen:  0,
  products:  null,        // catalogue central Triskell (chargé une fois)
  selectedProductIds: new Set(),  // ids cochés pour la campagne courante
  customOffers: [],       // offres ad-hoc spécifiques à la campagne courante
  mailAccounts: null,     // liste des comptes mail (principal + secondaires)
  _composeInitForCid: null,
  wizardStep: 1,          // étape active du wizard (1..5)
  _composeCache: null,    // saisie en cours étape 3 (brief, modèle) — anti-perte
  _sendCache: null,       // saisie en cours étape 5 (mode, plafonds…) — anti-perte
  _lastSendSummary: null, // {cid, s} : dernier bilan d'envoi, réinjecté au re-render
  _sendSummaryShown: false,
  _sendRunning: false,    // un envoi tourne côté serveur pour la campagne ouverte
  _genRunning: false,     // une génération IA tourne côté serveur
  _tableLimit: 100,       // nb de lignes affichées à l'étape 2 (paginé)

  // Auto-détecte l'étape la plus avancée selon l'état de la campagne.
  // Permet de revenir directement à l'étape "non terminée" si on rouvre
  // une campagne en cours.
  _autoDetectStep(c) {
    if (!c) return 1;
    const drafts = c.drafts || [];
    const hasSourceText = !!(c.source_file || (this.raw && this.raw.text_preview));
    const hasProspects  = drafts.length > 0;
    const hasBodies     = drafts.some(d => (d.body || '').trim().length > 0);
    const hasSent       = drafts.some(d => d.status === 'sent');
    const FINISHED = ['sent', 'failed', 'rejected', 'skipped_duplicate'];
    if (hasSent && drafts.every(d => FINISHED.includes(d.status))) {
      return 4;  // campagne terminée → on rouvre sur les résultats (aperçu)
    }
    if (hasBodies) return 4;       // mails générés → aperçu pour valider
    if (hasProspects) return 3;    // prospects extraits, manque le pitch
    if (hasSourceText) return 2;   // fichier uploadé, prospects à vérifier
    return 1;                      // rien encore : importer
  },

  WIZARD_STEPS: [
    { num: 1, key: 'import',  label: '1. Importer',       sub: 'Ta liste de prospects',     icon: '📂' },
    { num: 2, key: 'verify',  label: '2. Vérifier',       sub: 'Les contacts détectés',     icon: '✓' },
    { num: 3, key: 'pitch',   label: '3. Pitch & génération', sub: 'L\'offre et le brief IA',   icon: '🎯' },
    { num: 4, key: 'preview', label: '4. Aperçu des mails', sub: 'Voir avant d\'envoyer',     icon: '📧' },
    { num: 5, key: 'launch',  label: '5. Lancer l\'envoi', sub: 'Plafond, délai, GO',        icon: '🚀' },
  ],

  // Va à une étape du wizard (avec garde-fous logiques).
  // Avant de quitter l'étape courante, on photographie la saisie en cours
  // (brief, réglages d'envoi…) pour la ré-appliquer au prochain rendu :
  // plus aucune perte de texte en naviguant dans les étapes.
  async goToStep(step) {
    this._captureStepState();
    const s = Math.max(1, Math.min(5, step));
    // Étape 3 : on recharge le catalogue à chaque entrée (il a pu changer
    // depuis l'ouverture de la page — fini le cache de session périmé).
    // Si le rechargement échoue, on GARDE l'ancienne liste : sinon les
    // produits cochés disparaîtraient du prochain enregistrement.
    if (s === 3 && s !== this.wizardStep) {
      const prevProducts = this.products;
      const prevProspection = this.prospectionProducts;
      this.products = null;
      this.prospectionProducts = null;
      await this._loadProducts();
      await this._loadProspectionProducts(true);
      if ((!this.products || !this.products.length) && Array.isArray(prevProducts) && prevProducts.length) {
        this.products = prevProducts;
      }
      if ((!this.prospectionProducts || !this.prospectionProducts.length)
          && Array.isArray(prevProspection) && prevProspection.length) {
        this.prospectionProducts = prevProspection;
      }
    }
    this.wizardStep = s;
    this._renderDetail();
  },

  // Photographie les champs de l'étape affichée dans un cache mémoire.
  // Appelé avant tout changement d'étape ET avant tout re-render global.
  _captureStepState() {
    // Étape 3 — brief IA + modèle choisi (les coches produits / offres
    // sur mesure sont déjà suivies en direct dans selectedProductIds /
    // customOffers via leurs écouteurs).
    const brief = document.getElementById('cv-brief');
    const tpl   = document.getElementById('cv-template-product');
    if (brief || tpl) {
      this._composeCache = this._composeCache || {};
      if (brief) this._composeCache.brief = brief.value;
      if (tpl)   this._composeCache.template_product = tpl.value;
    }
    // Étape 4 — texte en cours d'édition dans les cartes brouillons :
    // recopié dans la copie locale pour survivre à un re-render
    // (il faudra toujours Enregistrer/Approuver pour le pousser au serveur).
    // Sauf pendant/juste après une génération : l'IA vient de réécrire les
    // brouillons, le DOM affiché est plus vieux que le serveur.
    if (!this._genRunning && !this._skipDraftCapture) {
      document.querySelectorAll('article[data-draft-card]').forEach(card => {
        const d = ((this.detail && this.detail.drafts) || [])
          .find(x => x.id === card.dataset.draftCard);
        if (!d) return;
        const subj = card.querySelector('input[data-subject]');
        const body = card.querySelector('textarea[data-body]');
        if (subj && !subj.disabled) d.subject = subj.value;
        if (body && !body.disabled) d.body = body.value;
      });
    }
    this._skipDraftCapture = false;
    // Étape 5 — mode, plafond, délai, planification + adresses cochées.
    const mode = document.getElementById('cv-mode');
    if (mode) {
      this._sendCache = this._sendCache || {};
      this._sendCache.mode  = mode.value;
      const cap   = document.getElementById('cv-cap');
      const delay = document.getElementById('cv-delay');
      const sched = document.getElementById('cv-sched');
      if (cap)   this._sendCache.daily_cap     = cap.value;
      if (delay) this._sendCache.delay_seconds = delay.value;
      if (sched) this._sendCache.schedule_at   = sched.value;
      const rows = [];
      document.querySelectorAll('.cv-sp-check').forEach(cb => {
        const id = cb.dataset.accountId;
        const capInput = document.querySelector(`.cv-sp-cap[data-account-id="${id}"]`);
        rows.push({ id, checked: cb.checked, cap: capInput ? capInput.value : '' });
      });
      if (rows.length) this._sendCache.senderRows = rows;
    }
  },

  // Rendu de la barre de progression visuelle + sous-titre clair sous
  // l'étape courante pour expliquer ce qui s'y passe (lever les doutes).
  _renderStepper() {
    const active = this.WIZARD_STEPS.find(s => s.num === this.wizardStep);
    return `
      <div class="cv-stepper">
        ${this.WIZARD_STEPS.map(st => {
          const done   = st.num < this.wizardStep;
          const isActive = st.num === this.wizardStep;
          const cls = isActive ? 'is-active' : (done ? 'is-done' : 'is-pending');
          return `
            <button data-cv-step="${st.num}" class="cv-step ${cls}"
                    title="${this._esc(st.sub || '')}">
              <span class="cv-step-num">${done ? '✓' : st.num}</span>
              <span class="cv-step-label">${this._esc(st.label.replace(/^\d+\.\s*/, ''))}</span>
            </button>
          `;
        }).join('')}
      </div>
      ${active ? `
        <div class="cv-step-hint">
          <span class="cv-step-hint-icon">${active.icon || ''}</span>
          <span><strong>${this._esc(active.label)}</strong> — ${this._esc(active.sub || '')}</span>
        </div>
      ` : ''}
    `;
  },

  _renderWizardNav(canPrev, canNext, nextLabel = 'Suivant') {
    return `
      <div class="cv-wizard-nav">
        ${canPrev
          ? `<button id="cv-wz-prev" class="btn btn-secondary">← Étape précédente</button>`
          : `<span></span>`}
        ${canNext
          ? `<button id="cv-wz-next" class="btn btn-primary cv-wz-next-cta">${this._esc(nextLabel)} →</button>`
          : `<span></span>`}
      </div>
    `;
  },

  _bindWizardNav() {
    const prev = document.getElementById('cv-wz-prev');
    if (prev) prev.onclick = () => this.goToStep(this.wizardStep - 1);
    const next = document.getElementById('cv-wz-next');
    if (next) next.onclick = () => this.goToStep(this.wizardStep + 1);
    // Stepper cliquable (sauter directement à une étape)
    document.querySelectorAll('[data-cv-step]').forEach(btn => {
      btn.onclick = () => this.goToStep(parseInt(btn.dataset.cvStep, 10));
    });
  },

  // ------------------------------------------------------------------
  async render(container) {
    container.innerHTML = `
      <section class="animate-slide-up">
        <div class="mb-6 sm:mb-8">
          <div class="flex items-start justify-between gap-3">
            <div class="min-w-0 flex-1">
              <div class="hero-kicker mb-2">LE CONVOI</div>
              <h1 class="hero-title hero-title--md mb-2 sm:mb-3">Le Convoi.</h1>
              <p class="hero-subtitle">
                Glisse un PDF, Word, Excel ou image avec tes contacts.
                L'app les extrait, adapte tes offres à chacun, et prépare les mails.
              </p>
              <p class="text-xs text-text-muted mt-2" style="text-wrap: pretty">
                🧭 Tu as déjà une liste ? C'est ici. Tu veux que l'app trouve
                elle-même les contacts ?
                <button type="button" class="text-accent underline hover:no-underline" onclick="App.show('prospection')">Lancer une prospection</button>.
              </p>
            </div>
            ${typeof Help !== 'undefined' ? Help.button('convoy') : ''}
          </div>
          <div class="flex flex-wrap gap-2 sm:gap-3 mt-5 sm:mt-6">
            <button id="cv-refresh" class="btn btn-secondary">Rafraîchir</button>
            <button id="cv-new" class="btn btn-primary">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
              Nouvelle campagne
            </button>
          </div>
        </div>

        <div class="grid grid-cols-1 lg:grid-cols-[280px_1fr] gap-4 sm:gap-6">
          <aside id="cv-left" class="card p-3 sm:p-4 lg:sticky lg:top-4 lg:self-start">
            <div class="section-label mb-2">Campagnes</div>
            <div id="cv-list" class="space-y-1.5"></div>
          </aside>
          <main id="cv-detail" class="space-y-6 min-w-0"></main>
        </div>
      </section>
    `;

    document.getElementById('cv-refresh').onclick = () => this.refreshAll();
    document.getElementById('cv-new').onclick     = () => this.newCampaign();

    if (!App.api) {
      document.getElementById('cv-detail').innerHTML = this._previewBanner();
      document.getElementById('cv-list').innerHTML   = `<div class="text-xs text-text-muted px-1.5 py-2">Mode aperçu.</div>`;
      return;
    }
    await this.refreshAll();
  },

  async refreshAll() {
    await this._loadMailAccounts();
    await this._loadList();
    // Restaure la campagne ouverte si state JS vide (refresh complet de l'app)
    if (!this.selected) {
      try { this.selected = localStorage.getItem(this._LS_SELECTED) || null; }
      catch (e) {}
    }
    // Si la campagne mémorisée a été supprimée entretemps, on l'ignore.
    if (this.selected && !this.campaigns.some(c => c.id === this.selected)) {
      this.selected = null;
      try { localStorage.removeItem(this._LS_SELECTED); } catch (e) {}
    }
    if (!this.selected && this.campaigns.length > 0) {
      await this.select(this.campaigns[0].id);
    } else if (this.selected) {
      await this.select(this.selected, /*reuseDetail=*/false);
    } else {
      this._renderEmpty();
    }
  },

  async _loadList() {
    let r;
    try { r = await App.api.convoy_list_campaigns(); }
    catch (e) { r = { ok: false, error: String(e) }; }
    this._listError = !(r && r.ok);
    if (this._listError) console.warn('[convoy] liste campagnes :', r && r.error);
    this.campaigns = (r && r.ok && r.campaigns) ? r.campaigns : [];
    this._renderList();
  },

  _renderList() {
    const wrap = document.getElementById('cv-list');
    if (!wrap) return;
    if (this._listError) {
      // Erreur de chargement ≠ liste vraiment vide : on le dit et on
      // propose de réessayer.
      wrap.innerHTML = `<div class="text-xs text-danger px-1.5 py-2">
        Impossible de charger les campagnes.
        <button id="cv-list-retry" class="underline underline-offset-2 ml-1">Réessayer</button>
      </div>`;
      const retry = document.getElementById('cv-list-retry');
      if (retry) retry.onclick = () => this._loadList();
      return;
    }
    if (this.campaigns.length === 0) {
      wrap.innerHTML = `<div class="text-xs text-text-muted px-1.5 py-2">
        Aucune campagne. Clique « Nouvelle campagne ».
      </div>`;
      return;
    }
    wrap.innerHTML = this.campaigns.map(c => {
      const active = (c.id === this.selected);
      const n = c.counts || {};
      const total = n.total || 0;
      const sent  = n.sent  || 0;
      const dot = sent > 0 ? '🟢' : (total > 0 ? '🟡' : '⚪');
      const dotTitle = sent > 0
        ? 'Des mails sont partis'
        : (total > 0 ? 'Contacts chargés, rien d’envoyé pour l’instant' : 'Campagne vide');
      return `
        <button data-cid="${this._esc(c.id)}"
                class="w-full text-left px-3 py-2.5 rounded-xl text-sm transition
                       ${active
                         ? 'bg-accent/10 border border-accent/40 text-text'
                         : 'hover:bg-bg border border-transparent text-text-secondary'}">
          <div class="flex items-center gap-2">
            <span class="text-xs" title="${this._esc(dotTitle)}">${dot}</span>
            <div class="min-w-0 flex-1">
              <div class="font-medium truncate">${this._esc(c.name)}</div>
              <div class="text-[11px] text-text-muted mt-0.5">
                ${total} contact${total > 1 ? 's' : ''} · ${sent} envoyé${sent > 1 ? 's' : ''}
              </div>
            </div>
          </div>
        </button>
      `;
    }).join('');
    wrap.querySelectorAll('button[data-cid]').forEach(btn => {
      btn.onclick = () => this.select(btn.dataset.cid);
    });
  },

  async select(cid, reuseDetail = false) {
    const changedCampaign = (cid !== this.selected);
    this.selected = cid;
    try { localStorage.setItem(this._LS_SELECTED, cid || ''); } catch (e) {}
    this._stopPollers();
    this._renderList();
    if (!reuseDetail) {
      this.raw = null;
      this.genSeen = 0;
      this.sendSeen = 0;
    }
    if (changedCampaign) {
      // Nouvelle campagne ouverte : on repart d'une saisie propre.
      this._composeCache = null;
      this._sendCache = null;
      this._newRows = [];
      this._tableLimit = 100;
      this._sendSummaryShown = false;
    }
    const target = document.getElementById('cv-detail');
    target.innerHTML = `<div class="card p-6 text-text-muted text-sm">Chargement…</div>`;
    let r;
    try { r = await App.api.convoy_get_campaign({ campaign_id: cid }); }
    catch (e) { r = { ok: false, error: String(e) }; }
    if (!r || !r.ok) {
      console.warn('[convoy] chargement campagne échoué :', r && r.error);
      target.innerHTML = `
        <div class="card p-6">
          <div class="text-sm text-danger mb-3">Impossible de charger cette campagne.</div>
          <button id="cv-retry-detail" class="btn btn-secondary">Réessayer</button>
        </div>`;
      const retry = document.getElementById('cv-retry-detail');
      if (retry) retry.onclick = () => this.select(cid, reuseDetail);
      return;
    }
    this.detail = r.campaign;
    await this._loadProducts();
    await this._loadProspectionProducts();
    this._initComposeState(this.detail);
    // Reprise : si un envoi / une génération tourne déjà côté serveur
    // (page rechargée, autre onglet…), on raccroche les wagons au lieu
    // de laisser croire que rien ne se passe (et d'autoriser un double
    // lancement).
    await this._checkRunning();
    this._renderDetail();
  },

  // Interroge le serveur : envoi ou génération en cours pour la campagne ?
  // Pose les drapeaux _sendRunning / _genRunning utilisés au rendu.
  async _checkRunning() {
    this._sendRunning = false;
    this._genRunning = false;
    if (!App.api || !this.detail) return;
    try {
      const s = await App.api.convoy_send_status({ campaign_id: this.detail.id, since: this.sendSeen || 0 });
      if (s && s.ok && s.running) this._sendRunning = true;
      // Bilan d'un envoi terminé pendant qu'on avait le dos tourné
      // (page rechargée…) : on le récupère pour l'afficher à l'étape 5.
      if (s && s.ok && !s.running && s.summary
          && (!this._lastSendSummary || this._lastSendSummary.cid !== this.detail.id)) {
        this._lastSendSummary = { cid: this.detail.id, s: s.summary };
        this._sendSummaryShown = true;
      }
    } catch (e) { /* hors-ligne : on retombera sur le comportement normal */ }
    try {
      const g = await App.api.convoy_generation_status({ campaign_id: this.detail.id, since: this.genSeen || 0 });
      if (g && g.ok && g.running) this._genRunning = true;
    } catch (e) {}
  },

  // ------------------------------------------------------------------
  //  Catalogue central : chargement + matching avec les offres campagne
  // ------------------------------------------------------------------
  async _loadProducts() {
    if (Array.isArray(this.products)) return;  // déjà chargé
    try {
      const r = await App.api.catalog_get_full();
      if (r && r.ok) {
        const disabled = new Set(r.disabled_ids || []);
        this.products = (r.products || []).filter(p => !disabled.has(p.id));
      } else {
        this.products = [];
      }
    } catch (e) {
      this.products = [];
    }
  },

  // Charge la liste des comptes mail (principal + secondaires).
  // Mis en cache pour éviter un appel à chaque re-render.
  async _loadMailAccounts(force = false) {
    if (!force && Array.isArray(this.mailAccounts)) return;
    if (!App.api || !App.api.mail_accounts_list) {
      this.mailAccounts = [];
      return;
    }
    try {
      const r = await App.api.mail_accounts_list();
      this.mailAccounts = (r && r.ok && Array.isArray(r.accounts)) ? r.accounts : [];
    } catch (e) {
      this.mailAccounts = [];
    }
  },

  // Charge les produits qui ont au moins un template de prospection
  // (alimente le sélecteur "Utiliser tes modèles" dans le wizard).
  async _loadProspectionProducts(force = false) {
    if (!force && Array.isArray(this.prospectionProducts)) return;
    if (!App.api || !App.api.convoy_list_prospection_products) {
      this.prospectionProducts = [];
      return;
    }
    try {
      const r = await App.api.convoy_list_prospection_products();
      this.prospectionProducts = (r && r.ok && Array.isArray(r.products)) ? r.products : [];
    } catch (e) {
      this.prospectionProducts = [];
    }
  },

  // Renvoie le compte mail correspondant à un id, ou null.
  _findAccount(id) {
    const aid = (id || 'primary').toString();
    const list = this.mailAccounts || [];
    return list.find(a => (a.id || '') === aid) || null;
  },

  // Libellé court d'un compte (« Nom — email@x »).
  _accountLabel(a) {
    if (!a) return '';
    const lbl = a.label || a.from_name || '';
    const mail = a.from_email || '';
    if (lbl && mail && lbl !== mail) return `${lbl} — ${mail}`;
    return mail || lbl || a.id;
  },

  _initComposeState(c) {
    // Reconstruit selectedProductIds + customOffers depuis c.catalog
    // Évite de re-init si on est sur la même campagne (préserve les
    // changements faits par l'utilisateur entre deux re-renders).
    if (this._composeInitForCid === (c && c.id)) return;
    this._composeInitForCid = c && c.id;
    this.selectedProductIds = new Set();
    this.customOffers = [];
    const products = this.products || [];
    const used = new Set();
    for (const offer of (c.catalog || [])) {
      const url = (offer.url || '').trim().toLowerCase();
      const name = (offer.name || '').trim().toLowerCase();
      let match = null;
      for (const p of products) {
        if (used.has(p.id)) continue;
        const pu = (p.buy_url || '').trim().toLowerCase();
        const pn = (p.name || '').trim().toLowerCase();
        if ((url && pu && url === pu) || (name && pn && name === pn)) {
          match = p; break;
        }
      }
      if (match) {
        this.selectedProductIds.add(match.id);
        used.add(match.id);
      } else if (offer.name || offer.url || offer.pitch) {
        this.customOffers.push({
          id: 'co_' + Math.random().toString(36).slice(2, 9),
          name: offer.name || '', pitch: offer.pitch || '',
          keywords: offer.keywords || '', url: offer.url || '',
        });
      }
    }
  },

  async newCampaign() {
    let r;
    try { r = await App.api.convoy_new_campaign({}); }
    catch (e) { r = { ok: false, error: String(e) }; }
    if (!r || !r.ok) {
      this._toast(r && r.error || 'Création impossible', 'danger');
      return;
    }
    await this._loadList();
    await this.select(r.campaign.id);
  },

  // ------------------------------------------------------------------
  //  Rendu détail — 5 étapes empilées
  // ------------------------------------------------------------------
  _renderEmpty() {
    document.getElementById('cv-detail').innerHTML = `
      <div class="card-hero p-10 sm:p-12 text-center" data-accent="accent">
        <div class="text-5xl mb-4 opacity-80">📂</div>
        <div class="hero-kicker text-accent mb-2">PREMIÈRE LISTE</div>
        <h2 class="text-2xl font-bold mb-3">Importe ton premier fichier.</h2>
        <p class="text-text-secondary max-w-md mx-auto mb-6">
          PDF, Word, Excel, image ou texte brut. L'app détecte les contacts,
          adapte tes offres et prépare des mails personnalisés.
        </p>
        <button class="btn btn-primary" onclick="Convoy.newCampaign()">
          Créer une campagne
        </button>
      </div>
    `;
  },

  _renderDetail() {
    const c = this.detail;
    const target = document.getElementById('cv-detail');
    const drafts = c.drafts || [];
    // Avant d'écraser le DOM : on photographie la saisie en cours
    // (brief, réglages…) pour la ré-appliquer juste après.
    this._captureStepState();
    // 1er rendu après ouverture : on auto-positionne sur la bonne étape
    if (this._lastRenderedCid !== c.id) {
      this.wizardStep = this._autoDetectStep(c);
      // Si quelque chose tourne déjà côté serveur, on atterrit directement
      // sur l'étape concernée pour montrer la progression.
      if (this._sendRunning)     this.wizardStep = 5;
      else if (this._genRunning) this.wizardStep = 3;
      this._lastRenderedCid = c.id;
    }
    const hasProspects = drafts.length > 0 || this.raw;
    const hasDrafts    = drafts.length > 0;

    // Sécurise l'étape : on n'autorise pas une étape qui n'a pas de données
    if (this.wizardStep >= 2 && !hasProspects) this.wizardStep = 1;
    if (this.wizardStep >= 4 && !hasDrafts) this.wizardStep = 3;

    // Ordre logique : 1.Importer → 2.Vérifier → 3.Pitch & génération
    //                 → 4.Aperçu des mails → 5.Lancer l'envoi.
    // (avant : envoi avant aperçu, ce qui était trompeur).
    const step = this.wizardStep;
    let stepHtml = '';
    if      (step === 1) stepHtml = this._stepImport(c);
    else if (step === 2) stepHtml = this._stepTable(c);
    else if (step === 3) stepHtml = this._stepCompose(c);
    else if (step === 4) stepHtml = this._stepResults(c);   // aperçu mails
    else if (step === 5) stepHtml = this._stepSend(c);      // lancer envoi

    const canPrev = step > 1;
    const canNext = (
      (step === 1 && hasProspects) ||
      (step === 2 && hasProspects) ||
      (step === 3 && hasDrafts) ||
      (step === 4 && hasDrafts)
    );
    const nextLabel = {
      1: 'Vérifier les contacts',
      2: 'Définir le pitch',
      3: 'Voir les mails générés',
      4: 'Préparer l’envoi',
    }[step] || 'Suivant';

    target.innerHTML = `
      ${this._headerCard(c)}
      ${this._renderStepper()}
      <div class="cv-wizard-step">${stepHtml}</div>
      ${step < 5 ? this._renderWizardNav(canPrev, canNext, nextLabel) : this._renderWizardNav(canPrev, false)}
    `;
    this._bindHeader();
    this._bindWizardNav();
    if      (step === 1) this._bindStepImport();
    else if (step === 2) this._bindStepTable();
    else if (step === 3) this._bindStepCompose();
    else if (step === 4) this._bindStepResults();
    else if (step === 5) this._bindStepSend();
  },

  // ---- Header ------------------------------------------------------
  _headerCard(c) {
    const fname = (c.source_file || '').split(/[\\/]/).pop() || '';
    const senderId = (c && c.sender_account_id) || 'primary';
    const senderAcc = this._findAccount(senderId);
    const senderHtml = senderAcc
      ? `<span title="Adresse expéditrice du convoi (modifiable à l'étape 5)">
           ✉ depuis <b>${this._esc(senderAcc.from_email || '')}</b>
         </span>`
      : '';
    return `
      <div class="card p-4 sm:p-6">
        <div class="flex flex-col sm:flex-row sm:items-center gap-3">
          <input id="cv-name" type="text" value="${this._esc(c.name)}"
                 class="flex-1 px-3 py-2 rounded-lg bg-bg border border-border
                        focus:border-accent focus:outline-none text-base font-semibold" />
          <div class="flex gap-2">
            <button id="cv-delete" class="btn btn-secondary text-danger">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-2 14a2 2 0 01-2 2H9a2 2 0 01-2-2L5 6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/></svg>
              Supprimer
            </button>
          </div>
        </div>
        <div class="text-xs text-text-muted mt-2 flex flex-wrap gap-x-3 gap-y-1">
          ${fname ? `<span>📄 ${this._esc(fname)}</span>` : ''}
          <span>créée le ${this._esc((c.created_at || '').slice(0, 16))}</span>
          ${senderHtml}
        </div>
      </div>
    `;
  },

  _bindHeader() {
    const name = document.getElementById('cv-name');
    if (name) {
      const save = async () => {
        const v = (name.value || '').trim();
        if (!v || v === this.detail.name) return;
        try {
          await App.api.convoy_rename_campaign({ campaign_id: this.detail.id, name: v });
          this.detail.name = v;
          await this._loadList();
        } catch (e) {
          Toast.friendlyError(e, 'Le nouveau nom n’a pas pu être enregistré.');
        }
      };
      name.addEventListener('blur', save);
      name.addEventListener('keydown', e => { if (e.key === 'Enter') name.blur(); });
    }
    const del = document.getElementById('cv-delete');
    if (del) del.onclick = async () => {
      const okGo = await Dialog.confirm(
        `La campagne « ${this.detail.name} » et tous ses brouillons vont être supprimés. C’est définitif.`,
        { title: 'Supprimer cette campagne ?', okLabel: 'Supprimer', danger: true },
      );
      if (!okGo) return;
      del.disabled = true;
      let r;
      try { r = await App.api.convoy_delete_campaign({ campaign_id: this.detail.id }); }
      catch (e) { r = { ok: false, error: String(e) }; }
      if (!r || !r.ok) {
        del.disabled = false;
        console.warn('[convoy] suppression campagne :', r && r.error);
        Toast.error('La suppression a échoué. Réessaie dans un instant.', 'Le Convoi');
        return;
      }
      Toast.success('Campagne supprimée.', 'Le Convoi');
      this.selected = null;
      try { localStorage.removeItem(this._LS_SELECTED); } catch (e) {}
      this.detail = null;
      this.raw = null;
      await this._loadList();
      if (this.campaigns.length > 0) await this.select(this.campaigns[0].id);
      else this._renderEmpty();
    };
  },

  // Fichier d'exemple : un petit CSV (BOM UTF-8 + point-virgule → s'ouvre
  // proprement dans Excel français) avec les colonnes que l'app sait lire.
  _downloadSampleFile() {
    const rows = [
      ['Raison sociale', 'Prénom', 'Email', 'Téléphone', 'Ville', 'Secteur'],
      ['Boulangerie Martin', 'Paul', 'contact@boulangerie-martin.fr', '02 99 00 00 00', 'Rennes', 'Boulangerie'],
      ['Garage Dupont', 'Julie', 'julie@garage-dupont.fr', '02 98 00 00 00', 'Brest', 'Garage automobile'],
      ['Cabinet Le Goff', 'Marc', 'accueil@cabinet-legoff.fr', '02 97 00 00 00', 'Vannes', 'Expertise comptable'],
    ];
    const csv = String.fromCharCode(0xFEFF)
      + rows.map(r => r.map(v => `"${v}"`).join(';')).join('\r\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'exemple-liste-convoi.csv';
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { try { URL.revokeObjectURL(a.href); a.remove(); } catch (e) {} }, 500);
  },

  // ---- Étape 1 : Import --------------------------------------------
  _stepImport(c) {
    const has = !!c.source_file;
    const fname = (c.source_file || '').split(/[\\/]/).pop() || '';
    const preview = this.raw && this.raw.text_preview;
    const warnings = (this.raw && this.raw.warnings) || [];
    return `
      ${this._sectionOpen('1. Importer la liste',
        'PDF, Word, Excel, CSV, image ou texte. L\'app détecte le format et extrait les contacts.')}
        <div id="cv-drop" role="button" tabindex="0"
             aria-label="Importer un fichier de contacts (cliquer ou déposer un fichier)"
             class="cv-drop rounded-2xl border-2 border-dashed border-border-strong
                    px-4 py-8 sm:py-10 text-center transition cursor-pointer
                    bg-bg hover:bg-accent/5 hover:border-accent">
          <div class="text-4xl mb-2 opacity-80">📂</div>
          <div class="font-medium text-base">
            ${has ? `📄 ${this._esc(fname)}` : 'Glisse un fichier ici'}
          </div>
          <div class="text-xs text-text-muted mt-1">
            ou clique pour parcourir · formats : PDF, DOCX, XLSX, CSV, TXT, image
          </div>
          <input id="cv-file" type="file" accept=".pdf,.docx,.xlsx,.xlsm,.csv,.tsv,.txt,.md,.png,.jpg,.jpeg,.bmp,.tif,.tiff,.webp"
                 class="hidden" />
        </div>
        <div class="text-[11px] text-text-muted mt-2 text-center">
          Pas sûr du format ?
          <button type="button" class="text-accent underline hover:no-underline"
                  onclick="Convoy._downloadSampleFile()">Télécharger un fichier d'exemple</button>
          (à remplir, puis à glisser ici).
        </div>

        ${preview ? `
          <div class="mt-4">
            <div class="text-xs font-medium text-text-secondary mb-1.5">Aperçu du texte extrait</div>
            <pre class="text-xs font-mono leading-relaxed p-3 rounded-lg bg-bg
                        border border-border max-h-40 overflow-auto whitespace-pre-wrap break-words">${this._esc((preview || '').slice(0, 4000))}${this.raw && this.raw.text_truncated ? '\n…' : ''}</pre>
          </div>
        ` : ''}

        ${warnings.length ? `
          <div class="mt-3 text-xs text-warning">
            ${warnings.map(w => `⚠ ${this._esc(w)}`).join('<br>')}
          </div>` : ''}

        ${this.raw && (this.raw.fast_path_prospects || []).length ? `
          <div class="flex flex-wrap gap-2 mt-4 items-center">
            <button id="cv-browse" class="btn btn-secondary">Parcourir…</button>
            <button id="cv-fastpath" class="btn btn-primary">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg>
              Valider ${this.raw.fast_path_prospects.length} contact${this.raw.fast_path_prospects.length > 1 ? 's' : ''} détecté${this.raw.fast_path_prospects.length > 1 ? 's' : ''}
            </button>
            ${has ? `<button id="cv-extract" class="text-xs text-text-muted hover:text-text underline underline-offset-2 ml-1"
              title="Lance l'IA pour relire le fichier (plus lent, à n'utiliser que si la détection automatique a manqué des contacts).">
              ou plutôt essayer l'IA
            </button>` : ''}
          </div>
        ` : `
          <div class="flex flex-wrap gap-2 mt-4">
            <button id="cv-browse" class="btn btn-secondary">Parcourir…</button>
            ${has ? `<button id="cv-extract" class="btn btn-primary">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><polygon points="5 3 19 12 5 21 5 3"/></svg>
              Extraire les contacts par IA
            </button>` : ''}
          </div>
        `}
      ${this._sectionClose()}
    `;
  },

  _bindStepImport() {
    const drop  = document.getElementById('cv-drop');
    const input = document.getElementById('cv-file');
    if (drop && input) {
      drop.onclick = () => input.click();
      drop.onkeydown = e => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); }
      };
      drop.ondragover = e => { e.preventDefault(); drop.classList.add('cv-drop--over'); };
      drop.ondragleave = () => drop.classList.remove('cv-drop--over');
      drop.ondrop = e => {
        e.preventDefault();
        drop.classList.remove('cv-drop--over');
        const f = e.dataTransfer.files && e.dataTransfer.files[0];
        if (f) this._uploadFile(f);
      };
      input.onchange = () => {
        const f = input.files && input.files[0];
        if (f) this._uploadFile(f);
      };
    }
    const browse = document.getElementById('cv-browse');
    if (browse) browse.onclick = () => input && input.click();
    const ex = document.getElementById('cv-extract');
    if (ex) ex.onclick = () => this._runExtractAi();
    const fp = document.getElementById('cv-fastpath');
    if (fp) fp.onclick = () => this._applyFastPath();
  },

  async _uploadFile(file) {
    // Garde-fou : au-delà de 20 Mo, l'envoi vers le serveur échoue ou
    // rame énormément — on refuse tout de suite avec un message clair.
    const MAX_BYTES = 20 * 1024 * 1024;
    if (file && file.size > MAX_BYTES) {
      const mo = (file.size / (1024 * 1024)).toFixed(1);
      this._toast(`Fichier trop lourd (${mo} Mo, maximum 20 Mo). Découpe-le ou enlève les images inutiles.`, 'danger');
      return;
    }
    const drop = document.getElementById('cv-drop');
    if (drop) drop.innerHTML = `<div class="text-sm text-text-secondary">Lecture du fichier…</div>`;
    let content_b64;
    try {
      content_b64 = await this._readBase64(file);
    } catch (e) {
      this._toast('Lecture impossible : ' + e, 'danger');
      this._renderDetail();
      return;
    }
    let r;
    try {
      r = await App.api.convoy_upload_and_parse({
        campaign_id: this.detail.id,
        filename: file.name,
        content_b64,
      });
    } catch (e) { r = { ok: false, error: String(e) }; }
    if (!r || !r.ok) {
      this._toast(r && r.error || 'Lecture impossible', 'danger');
      this.raw = null;
      this._renderDetail();
      return;
    }
    this.raw = r;
    // Recharge la campagne pour récupérer le source_file
    try {
      const c2 = await App.api.convoy_get_campaign({ campaign_id: this.detail.id });
      if (c2 && c2.ok) this.detail = c2.campaign;
    } catch (e) {}
    this._renderDetail();
    const n = (r.fast_path_prospects || []).length;
    if (n > 0) this._toast(`${n} contact${n > 1 ? 's' : ''} détecté${n > 1 ? 's' : ''} automatiquement.`, 'success');
    else       this._toast('Fichier lu. Clique « Extraire les contacts par IA ».', 'info');
  },

  _readBase64(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onerror = () => reject('lecture FileReader échouée');
      reader.onload = () => {
        const dataUrl = reader.result;
        // dataUrl = "data:<mime>;base64,<payload>"
        const i = dataUrl.indexOf(',');
        resolve(i >= 0 ? dataUrl.slice(i + 1) : dataUrl);
      };
      reader.readAsDataURL(file);
    });
  },

  async _applyFastPath() {
    const prospects = (this.raw && this.raw.fast_path_prospects) || [];
    if (prospects.length === 0) return;
    const btn = document.getElementById('cv-fastpath');
    if (btn) { btn.disabled = true; btn.textContent = 'Validation…'; }
    let r;
    try { r = await App.api.convoy_apply_fast_path({ campaign_id: this.detail.id, prospects }); }
    catch (e) { r = { ok: false, error: String(e) }; }
    if (!r || !r.ok) {
      if (btn) { btn.disabled = false; btn.textContent = `Valider ${prospects.length} contact${prospects.length > 1 ? 's' : ''}`; }
      this._toast(r && r.error || 'Application impossible', 'danger');
      return;
    }
    this.detail = r.campaign;
    this.raw = null;
    // Contacts en place → on emmène directement sur l'étape 2 (vérifier)
    this.wizardStep = 2;
    this._renderDetail();
    await this._loadList();
  },

  async _runExtractAi() {
    const btn = document.getElementById('cv-extract');
    const originalLabel = btn ? btn.innerHTML : '';
    if (btn) { btn.disabled = true; btn.innerHTML = `<span class="inline-block w-4 h-4 rounded-full border-2 border-white/40 border-t-white animate-spin"></span> Extraction IA…`; }
    let r;
    try { r = await App.api.convoy_extract_prospects_ai({ campaign_id: this.detail.id }); }
    catch (e) { r = { ok: false, error: String(e) }; }
    if (!r || !r.ok) {
      const raw = (r && r.error) || 'Extraction IA impossible';
      // Détection timeout/proxy : 502/504/timeout/Failed to fetch
      const isTimeout = /\b(502|504|timeout|timed out|Failed to fetch|aborted)\b/i.test(raw);
      const fastN = (this.raw && (this.raw.fast_path_prospects || []).length) || 0;
      let msg;
      if (isTimeout && fastN > 0) {
        msg = `L'IA a mis trop de temps. Utilise plutôt le bouton « Valider ${fastN} contacts détectés » — c'est plus rapide et ton fichier est déjà bien structuré.`;
      } else if (isTimeout) {
        msg = `L'IA a mis trop de temps à répondre. Réessaie, ou découpe ton fichier en morceaux plus petits.`;
      } else {
        msg = raw;
      }
      this._toast(msg, 'danger');
      if (btn) { btn.disabled = false; btn.innerHTML = originalLabel || 'Extraire les contacts par IA'; }
      return;
    }
    this.detail = r.campaign;
    this.raw = null;
    // Extraction réussie → on emmène directement sur l'étape 2 (vérifier)
    this.wizardStep = 2;
    this._renderDetail();
    await this._loadList();
    this._toast(`${(r.stats && r.stats.total) || 0} contact(s) extrait(s).`, 'success');
  },

  // ---- Étape 2 : Tableau -------------------------------------------
  _TABLE_COLS: [
    { k: 'raison_sociale', label: 'Entreprise',  w: 'w-44' },
    { k: 'prenom',         label: 'Prénom',      w: 'w-28' },
    { k: 'email',          label: 'Email',       w: 'w-56' },
    { k: 'telephone',      label: 'Téléphone',   w: 'w-32' },
    { k: 'ville',          label: 'Ville',       w: 'w-32' },
    { k: 'secteur',        label: 'Secteur',     w: 'w-40' },
  ],

  // Ajout / retrait de ligne : le serveur n'a pas d'ajout/suppression à
  // l'unité, on ré-applique donc la liste complète (même mécanisme que la
  // validation des contacts détectés). Ce remplacement repart de brouillons
  // vierges → on ne l'autorise QUE tant qu'aucun mail n'a été généré.
  _tableStructureLocked(drafts) {
    return (drafts || []).some(d =>
      (d.subject || d.body) || (d.status && d.status !== 'pending'));
  },

  _stepTable(c) {
    const drafts = c.drafts || [];
    if (drafts.length === 0 && !(this._newRows || []).length) {
      return `${this._sectionOpen('2. Vérifier les contacts', 'Aucun contact pour l’instant — importe un fichier à l’étape 1.')}
        <div class="text-sm text-text-muted">Importe un fichier puis clique « Extraire » pour faire apparaître le tableau.</div>
      ${this._sectionClose()}`;
    }
    // Stats : ok / warning / error
    let ok = 0, warn = 0, err = 0;
    for (const d of drafts) {
      const sev = this._severity(d.prospect || {});
      if (sev === 'ok') ok++;
      else if (sev === 'warning') warn++;
      else err++;
    }

    const cols = this._TABLE_COLS;
    const locked = this._tableStructureLocked(drafts);
    const lockTitle = 'Indisponible : des mails ont déjà été générés pour ces contacts. '
      + 'Pour modifier la liste, crée une nouvelle campagne.';
    const shown = drafts.slice(0, this._tableLimit);
    const hiddenCount = drafts.length - shown.length;
    const newRows = this._newRows || [];

    return `
      ${this._sectionOpen('2. Vérifier les contacts',
        'Édite ce qui doit l’être. Les lignes en rouge n’ont pas d’email et seront ignorées. Les jaunes partiront avec moins de contexte.')}
        <div class="grid grid-cols-3 gap-3 mb-4">
          ${this._kpi('Complets', ok, ok > 0 ? 'success' : '')}
          ${this._kpi('Incomplets', warn, warn > 0 ? 'warning' : '')}
          ${this._kpi('Sans email', err, err > 0 ? 'danger' : '')}
        </div>
        <div class="flex items-center justify-between mb-2">
          <button id="cv-add-contact" class="text-[11px] text-accent hover:underline"
                  ${locked ? `disabled title="${this._esc(lockTitle)}" style="opacity:.45;cursor:not-allowed;"` : ''}>
            + Ajouter un contact
          </button>
          <span id="cv-tbl-saved" class="text-[11px] text-success" aria-live="polite"></span>
        </div>
        <div class="overflow-x-auto rounded-xl border border-border">
          <table class="w-full text-xs">
            <thead class="bg-bg text-text-muted">
              <tr>
                ${cols.map(col => `<th class="px-3 py-2 text-left font-semibold ${col.w}">${col.label}</th>`).join('')}
                <th class="px-2 py-2 w-8"><span class="sr-only">Retirer</span></th>
              </tr>
            </thead>
            <tbody>
              ${shown.map(d => this._tableRow(d, cols, locked, lockTitle)).join('')}
              ${newRows.map(nr => this._tableNewRow(nr, cols)).join('')}
            </tbody>
          </table>
        </div>
        ${hiddenCount > 0 ? `
          <div class="text-center mt-3">
            <button id="cv-tbl-more" class="btn btn-secondary">
              Afficher les ${Math.min(100, hiddenCount)} contacts suivants (${hiddenCount} restants)
            </button>
          </div>` : ''}
      ${this._sectionClose()}
    `;
  },

  _tableRow(d, cols, locked, lockTitle) {
    const sev = this._severity(d.prospect || {});
    const bg = sev === 'error' ? 'bg-danger/5' : (sev === 'warning' ? 'bg-warning/5' : '');
    const who = (d.prospect || {}).email || (d.prospect || {}).raison_sociale || 'ce contact';
    return `
      <tr class="${bg} border-t border-border" data-draft-id="${this._esc(d.id)}">
        ${cols.map(col => `
          <td class="px-2 py-1">
            <input type="text" data-field="${col.k}"
                   value="${this._esc((d.prospect || {})[col.k] || '')}"
                   class="w-full bg-transparent px-1.5 py-1 rounded
                          border border-transparent hover:border-border
                          focus:border-accent focus:outline-none text-xs" />
          </td>
        `).join('')}
        <td class="px-2 py-1 text-center">
          <button data-row-remove="${this._esc(d.id)}"
                  title="${locked ? this._esc(lockTitle) : `Retirer ${this._esc(who)} de la liste`}"
                  aria-label="Retirer ${this._esc(who)} de la liste"
                  ${locked ? 'disabled style="opacity:.35;cursor:not-allowed;"' : ''}
                  class="text-text-muted hover:text-danger text-sm leading-none">🗑</button>
        </td>
      </tr>
    `;
  },

  // Ligne vide en cours d'ajout (pas encore connue du serveur)
  _tableNewRow(nr, cols) {
    return `
      <tr class="border-t border-accent/40 bg-accent/5" data-new-row="${this._esc(nr.key)}">
        ${cols.map(col => `
          <td class="px-2 py-1">
            <input type="text" data-field="${col.k}"
                   value="${this._esc(nr.prospect[col.k] || '')}"
                   placeholder="${col.k === 'email' ? 'email@exemple.fr' : ''}"
                   class="w-full bg-transparent px-1.5 py-1 rounded
                          border border-transparent hover:border-border
                          focus:border-accent focus:outline-none text-xs" />
          </td>
        `).join('')}
        <td class="px-2 py-1 text-center">
          <button data-new-remove="${this._esc(nr.key)}" title="Annuler cette ligne"
                  aria-label="Annuler cette ligne"
                  class="text-text-muted hover:text-danger text-sm leading-none">🗑</button>
        </td>
      </tr>
    `;
  },

  // Indicateur discret « ✓ enregistré » à côté du tableau
  _tableFlash(msg, isError) {
    const el = document.getElementById('cv-tbl-saved');
    if (!el) return;
    el.textContent = msg;
    el.classList.toggle('text-success', !isError);
    el.classList.toggle('text-danger', !!isError);
    clearTimeout(this._tblFlashTimer);
    this._tblFlashTimer = setTimeout(() => { el.textContent = ''; }, 2500);
  },

  _bindStepTable() {
    const drafts = (this.detail && this.detail.drafts) || [];
    const locked = this._tableStructureLocked(drafts);

    // --- Édition d'une ligne existante : sauvegarde au blur, avec retour
    //     visible (✓ enregistré / message d'erreur), plus de silence.
    document.querySelectorAll('tr[data-draft-id]').forEach(row => {
      const did = row.dataset.draftId;
      row.querySelectorAll('input[data-field]').forEach(inp => {
        inp.addEventListener('blur', async () => {
          const prospect = {};
          row.querySelectorAll('input[data-field]').forEach(x => {
            prospect[x.dataset.field] = x.value.trim();
          });
          // Copie locale mise à jour TOUT DE SUITE : même si un re-render
          // arrive pendant l'appel réseau, la saisie ne disparaît pas.
          const d = drafts.find(x => x.id === did);
          if (d) d.prospect = Object.assign({}, d.prospect, prospect);
          try {
            const r = await App.api.convoy_update_prospect({
              campaign_id: this.detail.id, draft_id: did, prospect,
            });
            if (!r || !r.ok) throw new Error((r && r.error) || 'enregistrement refusé');
            this._tableFlash('✓ enregistré');
          } catch (e) {
            console.warn('[convoy] sauvegarde contact :', e);
            this._tableFlash('✗ non enregistré', true);
            Toast.friendlyError(e, 'La modification du contact n’a pas pu être enregistrée.');
          }
          // Met à jour la couleur de la ligne selon la nouvelle sévérité
          const sev = this._severity(prospect);
          row.classList.remove('bg-danger/5', 'bg-warning/5');
          if (sev === 'error') row.classList.add('bg-danger/5');
          else if (sev === 'warning') row.classList.add('bg-warning/5');
        });
      });
    });

    // --- Pagination : afficher 100 lignes de plus
    const more = document.getElementById('cv-tbl-more');
    if (more) more.onclick = () => {
      this._tableLimit += 100;
      this._renderDetail();
    };

    // --- Ajouter un contact (ligne vide locale, envoyée dès qu'elle a du contenu)
    const add = document.getElementById('cv-add-contact');
    if (add && !locked) add.onclick = () => {
      this._newRows = this._newRows || [];
      this._newRows.push({ key: 'nr_' + Math.random().toString(36).slice(2, 9), prospect: {} });
      this._renderDetail();
      // Focus sur le premier champ de la nouvelle ligne
      const rows = document.querySelectorAll('tr[data-new-row]');
      const last = rows[rows.length - 1];
      const first = last && last.querySelector('input[data-field]');
      if (first) first.focus();
    };

    // --- Lignes en cours d'ajout : mémorise la frappe, pousse au blur
    document.querySelectorAll('tr[data-new-row]').forEach(row => {
      const key = row.dataset.newRow;
      const nr = (this._newRows || []).find(x => x.key === key);
      if (!nr) return;
      row.querySelectorAll('input[data-field]').forEach(inp => {
        inp.addEventListener('input', () => { nr.prospect[inp.dataset.field] = inp.value.trim(); });
        inp.addEventListener('blur', () => {
          // Dès que la ligne a au moins un champ rempli ET que le focus
          // sort du tableau, on pousse la liste complète au serveur.
          setTimeout(() => {
            const stillInside = row.contains(document.activeElement);
            const hasContent = Object.values(nr.prospect).some(v => v);
            const stillThere = (this._newRows || []).some(x => x.key === key);
            if (!stillInside && hasContent && stillThere) this._syncTableRows();
          }, 120);
        });
      });
    });
    document.querySelectorAll('[data-new-remove]').forEach(btn => {
      btn.onclick = () => {
        const key = btn.getAttribute('data-new-remove');
        this._newRows = (this._newRows || []).filter(x => x.key !== key);
        this._renderDetail();
      };
    });

    // --- Retirer une ligne existante
    document.querySelectorAll('[data-row-remove]').forEach(btn => {
      if (locked) return;  // bouton désactivé + title explicatif déjà posés
      btn.onclick = async () => {
        const did = btn.getAttribute('data-row-remove');
        const d = drafts.find(x => x.id === did);
        const who = d && ((d.prospect || {}).email || (d.prospect || {}).raison_sociale) || 'ce contact';
        const okGo = await Dialog.confirm(
          `Retirer ${who} de la liste ? Il ne recevra pas de mail de cette campagne.`,
          { title: 'Retirer ce contact ?', okLabel: 'Retirer', danger: true },
        );
        if (!okGo) return;
        btn.disabled = true;
        await this._syncTableRows(did);
      };
    });
  },

  // Reconstruit la liste complète des prospects (fiches existantes,
  // champs affichés mis à jour depuis le tableau, lignes ajoutées) et la
  // ré-applique côté serveur. `removeId` : draft à exclure (suppression).
  async _syncTableRows(removeId) {
    const drafts = (this.detail && this.detail.drafts) || [];
    const prospects = [];
    for (const d of drafts) {
      if (removeId && d.id === removeId) continue;
      // Champs non affichés (nom, site web, adresse…) conservés tels quels
      const merged = Object.assign({}, d.prospect || {});
      const row = document.querySelector(`tr[data-draft-id="${d.id}"]`);
      if (row) {
        row.querySelectorAll('input[data-field]').forEach(x => {
          merged[x.dataset.field] = x.value.trim();
        });
      }
      prospects.push(merged);
    }
    for (const nr of (this._newRows || [])) {
      if (Object.values(nr.prospect).some(v => v)) prospects.push(Object.assign({}, nr.prospect));
    }
    let r;
    try { r = await App.api.convoy_apply_fast_path({ campaign_id: this.detail.id, prospects }); }
    catch (e) { r = { ok: false, error: String(e) }; }
    if (!r || !r.ok) {
      console.warn('[convoy] mise à jour de la liste :', r && r.error);
      Toast.error('La liste n’a pas pu être mise à jour. Réessaie.', 'Le Convoi');
      this._renderDetail();
      return;
    }
    this.detail = r.campaign;
    this._newRows = [];
    this._renderDetail();
    await this._loadList();
    this._tableFlash(removeId ? '✓ contact retiré' : '✓ contact ajouté');
  },

  _severity(p) {
    const email = (p.email || '').trim();
    if (!email || !email.includes('@') || !email.split('@')[1].includes('.')) return 'error';
    if (!p.raison_sociale && !p.prenom && !p.nom) return 'warning';
    if (!p.secteur) return 'warning';
    return 'ok';
  },

  // ---- Étape 3 : Composer ------------------------------------------
  _stepCompose(c) {
    // S'assure que l'état est init (cas où _loadProducts a fini après le 1er render)
    this._initComposeState(c);
    const products = this.products || [];
    // Groupe par catégorie pour clarté visuelle
    const byCat = {};
    for (const p of products) {
      const k = p.category || 'autres';
      if (!byCat[k]) byCat[k] = [];
      byCat[k].push(p);
    }
    const selectedCount = this.selectedProductIds.size + this.customOffers.length;
    // La saisie en cours (non enregistrée) prime sur la valeur serveur :
    // on ne perd plus le brief en naviguant entre les étapes.
    const cache = this._composeCache || {};
    const briefValue = (cache.brief != null) ? cache.brief : (c.user_brief || '');
    const templateValue = (cache.template_product != null)
      ? cache.template_product : (c.template_product || '');
    return `
      ${this._sectionOpen('3. Pitch & génération',
        'Coche les offres à proposer dans cette campagne. L\'IA piochera dedans pour adapter le mail à chaque contact.')}
        <div class="flex items-center justify-between mb-3">
          <div class="text-xs font-medium text-text-secondary">
            Catalogue Triskell · <span id="cv-cat-count" class="text-accent font-semibold">${selectedCount}</span> offre${selectedCount > 1 ? 's' : ''} retenue${selectedCount > 1 ? 's' : ''}
          </div>
          <div class="flex gap-2">
            <button id="cv-cat-all"  class="text-[11px] text-text-muted hover:text-accent underline underline-offset-2">Tout cocher</button>
            <button id="cv-cat-none" class="text-[11px] text-text-muted hover:text-accent underline underline-offset-2">Tout décocher</button>
          </div>
        </div>

        ${products.length === 0 ? `
          <div class="text-xs text-text-muted italic mb-4 p-3 rounded-lg bg-bg border border-border">
            Aucun produit dans ton catalogue Triskell pour l'instant. Ajoute-les en bas en « Offres sur mesure », ou ouvre la page Catalogue dans l'écosystème.
          </div>
        ` : `
          <div class="space-y-4 mb-4">
            ${Object.entries(byCat).map(([cat, ps]) => `
              <div>
                <div class="text-[11px] font-bold tracking-widest text-text-muted mb-2 uppercase">${this._esc(this._categoryLabel(cat))}</div>
                <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
                  ${ps.map(p => this._productCard(p)).join('')}
                </div>
              </div>
            `).join('')}
          </div>
        `}

        <div class="border-t border-border pt-4 mb-4">
          <div class="flex items-center justify-between mb-2">
            <div class="text-[11px] font-bold tracking-widest text-text-muted uppercase">Offres sur mesure (juste pour cette campagne)</div>
            <button id="cv-add-offer" class="text-[11px] text-accent hover:underline">+ Ajouter une offre</button>
          </div>
          <div id="cv-custom-offers" class="space-y-2"></div>
        </div>

        <label class="block mb-3">
          <div class="text-xs font-medium text-text-secondary mb-1.5">Tes instructions à l'IA (ton, contexte, contraintes)</div>
          <textarea id="cv-brief" rows="5"
                    class="w-full px-3 py-2 rounded-lg bg-bg border border-border
                           focus:border-accent focus:outline-none text-sm leading-relaxed
                           resize-y">${this._esc(briefValue)}</textarea>
        </label>

        <!-- Sélecteur de templates de prospection (optionnel) -->
        <div class="cv-template-block mb-3">
          <div class="text-xs font-medium text-text-secondary mb-1.5">
            Utiliser tes modèles de mails (optionnel)
          </div>
          <select id="cv-template-product"
                  class="w-full px-3 py-2 rounded-lg bg-bg border border-border
                         focus:border-accent focus:outline-none text-sm">
            <option value="">Aucun — l'IA rédige librement à partir du brief</option>
            ${(this.prospectionProducts || []).map(p => `
              <option value="${this._esc(p.product)}"
                      ${templateValue === p.product ? 'selected' : ''}>
                ${this._esc(p.label)} (${p.count} modèle${p.count > 1 ? 's' : ''})
              </option>
            `).join('')}
            ${templateValue && !(this.prospectionProducts || []).some(p => p.product === templateValue) ? `
              <option value="${this._esc(templateValue)}" selected>${this._esc(templateValue)} (choix enregistré)</option>
            ` : ''}
          </select>
          <div id="cv-template-hint" class="text-[11px] text-text-muted mt-1.5">
            ${ templateValue
                ? `L'IA piochera dans tes modèles « ${this._esc(templateValue)} » et les adaptera légèrement à chaque prospect.`
                : `Choisis un produit pour faire piocher l'IA dans tes modèles écrits à la main (Modèles mails → Prospection).` }
          </div>
        </div>
        <div class="flex flex-wrap gap-2">
          <button id="cv-save-compose" class="btn btn-secondary">Enregistrer</button>
          <button id="cv-gen-test"     class="btn btn-secondary">Tester (5)</button>
          <button id="cv-gen-all"      class="btn btn-primary">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
            Générer tous les mails
          </button>
        </div>

        <!-- Bandeau de progression visible pendant la génération.
             Sans ça, après un clic sur « Tester (5) » on a l'impression
             que rien ne se passe (les boutons restent identiques et le
             journal en bas est facile à manquer). -->
        <div id="cv-gen-progress" class="cv-gen-progress hidden mt-4">
          <div class="cv-gen-progress-spinner"></div>
          <div class="cv-gen-progress-text">
            <div class="cv-gen-progress-title">Génération en cours…</div>
            <div class="cv-gen-progress-sub" id="cv-gen-progress-sub">
              L'IA rédige tes mails un par un. Tu seras redirigé vers
              l'aperçu dès que c'est fini.
            </div>
          </div>
        </div>

        <div id="cv-gen-log-wrap" class="mt-4 hidden">
          <div class="text-xs font-medium text-text-secondary mb-1.5">Journal de génération (détail)</div>
          <pre id="cv-gen-log"
               class="text-xs font-mono leading-relaxed p-3 rounded-lg bg-bg
                      border border-border max-h-48 overflow-auto whitespace-pre-wrap"></pre>
        </div>
      ${this._sectionClose()}
    `;
  },

  _bindStepCompose() {
    const save = document.getElementById('cv-save-compose');
    if (save) save.onclick = () => this._saveCompose();
    const gt = document.getElementById('cv-gen-test');
    if (gt) gt.onclick = () => this._generate(5);
    const ga = document.getElementById('cv-gen-all');
    if (ga) ga.onclick = () => this._generate(null);

    // Sélecteur "Utiliser tes modèles" — met à jour le hint dynamiquement
    const tpSel = document.getElementById('cv-template-product');
    const tpHint = document.getElementById('cv-template-hint');
    if (tpSel && tpHint) {
      tpSel.addEventListener('change', () => {
        const v = tpSel.value || '';
        if (v) {
          const found = (this.prospectionProducts || []).find(p => p.product === v);
          const label = found ? found.label : v;
          tpHint.textContent = `L'IA piochera dans tes modèles « ${label} » `
            + `(${found ? found.count : '?'} modèle${found && found.count > 1 ? 's' : ''}) `
            + `et les adaptera légèrement à chaque prospect.`;
        } else {
          tpHint.textContent = `Choisis un produit pour faire piocher l'IA dans tes modèles écrits à la main (Modèles mails → Prospection).`;
        }
      });
    }

    // Coches produits : update visuel + compteur + état interne
    document.querySelectorAll('.cv-product-check').forEach(cb => {
      cb.onchange = () => {
        const pid = cb.getAttribute('data-product-id');
        if (cb.checked) this.selectedProductIds.add(pid);
        else this.selectedProductIds.delete(pid);
        const card = cb.closest('.cv-product-card');
        if (card) {
          card.classList.toggle('border-accent', cb.checked);
          card.classList.toggle('bg-accent/5', cb.checked);
          card.classList.toggle('border-border', !cb.checked);
        }
        this._updateCatCount();
      };
    });
    const allBtn = document.getElementById('cv-cat-all');
    if (allBtn) allBtn.onclick = () => {
      document.querySelectorAll('.cv-product-check').forEach(cb => {
        if (!cb.checked) { cb.checked = true; cb.dispatchEvent(new Event('change')); }
      });
    };
    const noneBtn = document.getElementById('cv-cat-none');
    if (noneBtn) noneBtn.onclick = () => {
      document.querySelectorAll('.cv-product-check').forEach(cb => {
        if (cb.checked) { cb.checked = false; cb.dispatchEvent(new Event('change')); }
      });
    };

    // Offres sur mesure : ajout + rendu initial
    const addBtn = document.getElementById('cv-add-offer');
    if (addBtn) addBtn.onclick = () => {
      this.customOffers.push({
        id: 'co_' + Math.random().toString(36).slice(2, 9),
        name: '', pitch: '', keywords: '', url: '',
      });
      this._renderCustomOffers();
      this._updateCatCount();
    };
    this._renderCustomOffers();

    // Reprise : une génération tourne déjà (page rechargée pendant le
    // travail de l'IA) → on raffiche la progression, on désactive les
    // boutons et on raccroche le suivi. Évite le double lancement.
    if (this._genRunning) {
      const prog = document.getElementById('cv-gen-progress');
      const wrapLog = document.getElementById('cv-gen-log-wrap');
      if (prog) prog.classList.remove('hidden');
      if (wrapLog) wrapLog.classList.remove('hidden');
      const btTest = document.getElementById('cv-gen-test');
      const btAll  = document.getElementById('cv-gen-all');
      if (btTest) btTest.disabled = true;
      if (btAll)  { btAll.disabled = true; btAll.textContent = 'Génération en cours…'; }
      this._genRestoreBtns = () => {
        if (btTest) btTest.disabled = false;
        if (btAll)  { btAll.disabled = false; btAll.textContent = 'Générer tous les mails'; }
      };
      // Journal recréé vide par le rendu → on rejoue tout depuis le début.
      this.genSeen = 0;
      this._startGenPoll();
    }
  },

  _renderCustomOffers() {
    const wrap = document.getElementById('cv-custom-offers');
    if (!wrap) return;
    if (!this.customOffers.length) {
      wrap.innerHTML = `<div class="text-xs text-text-muted italic px-1">Aucune offre sur mesure. Clique « + Ajouter » si tu veux proposer un service qui n'est pas dans ton catalogue.</div>`;
      return;
    }
    wrap.innerHTML = this.customOffers.map(o => `
      <div class="grid grid-cols-1 sm:grid-cols-12 gap-2 items-center">
        <input class="sm:col-span-3 px-2 py-1.5 text-xs rounded-md bg-bg border border-border focus:border-accent focus:outline-none"
               placeholder="Nom de l'offre" data-co-id="${this._esc(o.id)}" data-co-field="name" value="${this._esc(o.name || '')}">
        <input class="sm:col-span-4 px-2 py-1.5 text-xs rounded-md bg-bg border border-border focus:border-accent focus:outline-none"
               placeholder="Pitch (1 phrase)" data-co-id="${this._esc(o.id)}" data-co-field="pitch" value="${this._esc(o.pitch || '')}">
        <input class="sm:col-span-2 px-2 py-1.5 text-xs rounded-md bg-bg border border-border focus:border-accent focus:outline-none"
               placeholder="mots-clés" data-co-id="${this._esc(o.id)}" data-co-field="keywords" value="${this._esc(o.keywords || '')}">
        <input class="sm:col-span-2 px-2 py-1.5 text-xs rounded-md bg-bg border border-border focus:border-accent focus:outline-none"
               placeholder="https://…" data-co-id="${this._esc(o.id)}" data-co-field="url" value="${this._esc(o.url || '')}">
        <button class="sm:col-span-1 justify-self-end sm:justify-self-auto text-danger hover:text-danger/80 text-xl leading-none font-bold"
                data-co-remove="${this._esc(o.id)}" title="Retirer cette offre" aria-label="Retirer cette offre">×</button>
      </div>
    `).join('');
    wrap.querySelectorAll('[data-co-id]').forEach(input => {
      input.oninput = () => {
        const id = input.getAttribute('data-co-id');
        const field = input.getAttribute('data-co-field');
        const offer = this.customOffers.find(o => o.id === id);
        if (offer) offer[field] = input.value;
      };
    });
    wrap.querySelectorAll('[data-co-remove]').forEach(btn => {
      btn.onclick = () => {
        const id = btn.getAttribute('data-co-remove');
        this.customOffers = this.customOffers.filter(o => o.id !== id);
        this._renderCustomOffers();
        this._updateCatCount();
      };
    });
  },

  _updateCatCount() {
    const el = document.getElementById('cv-cat-count');
    if (!el) return;
    const n = this.selectedProductIds.size + this.customOffers.filter(o => o.name || o.url || o.pitch).length;
    el.textContent = String(n);
  },

  _productCard(p) {
    const checked = this.selectedProductIds.has(p.id);
    const initial = (p.initial || (p.name || '?').charAt(0)).toUpperCase();
    const color = p.color || '#888';
    return `
      <label class="cv-product-card flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition hover:border-accent/60
                     ${checked ? 'border-accent bg-accent/5' : 'border-border'}">
        <input type="checkbox" data-product-id="${this._esc(p.id)}" ${checked ? 'checked' : ''}
               class="mt-1 cv-product-check w-4 h-4 accent-accent flex-shrink-0">
        <div class="w-8 h-8 rounded-md flex items-center justify-center text-white font-bold text-sm flex-shrink-0"
             style="background:${this._esc(color)}">${this._esc(initial)}</div>
        <div class="min-w-0 flex-1">
          <div class="text-sm font-semibold truncate">${this._esc(p.name || '')}</div>
          <div class="text-xs text-text-muted line-clamp-2 mt-0.5">${this._esc(p.tagline || p.sales_pitch || '')}</div>
        </div>
      </label>
    `;
  },

  _categoryLabel(cat) {
    const map = {
      sites: 'Sites web', creators: 'Créateurs', batiment: 'Bâtiment',
      apps: 'Applications', service: 'Services', autres: 'Autres',
    };
    return map[cat] || cat;
  },

  _gatherCompose() {
    const brief = (document.getElementById('cv-brief') || {}).value || '';
    const templateProduct = (document.getElementById('cv-template-product') || {}).value || '';
    const catalog = [];
    // Produits du catalogue central cochés
    for (const pid of this.selectedProductIds) {
      const p = (this.products || []).find(x => x.id === pid);
      if (!p) continue;
      catalog.push({
        name:     p.name || '',
        pitch:    p.tagline || p.sales_pitch || '',
        keywords: p.category || '',
        url:      p.buy_url || '',
      });
    }
    // Offres ad-hoc
    for (const o of (this.customOffers || [])) {
      if (!o.name && !o.url && !o.pitch) continue;
      catalog.push({
        name: o.name || '', pitch: o.pitch || '',
        keywords: o.keywords || '', url: o.url || '',
      });
    }
    return { user_brief: brief, catalog, template_product: templateProduct };
  },

  async _saveCompose() {
    const btn = document.getElementById('cv-save-compose');
    if (btn) { btn.disabled = true; btn.textContent = 'Enregistrement…'; }
    const { user_brief, catalog, template_product } = this._gatherCompose();
    try {
      await App.api.convoy_save_compose({
        campaign_id: this.detail.id, user_brief, catalog,
      });
      // template_product est sauvegardé via convoy_save_send_settings
      // (qui gère déjà tous les champs configurables de la campagne).
      if (typeof template_product === 'string') {
        await App.api.convoy_save_send_settings({
          campaign_id: this.detail.id, template_product,
        });
        this.detail.template_product = template_product;
      }
      if (btn) { btn.textContent = 'Enregistré ✓'; setTimeout(() => { btn.disabled = false; btn.textContent = 'Enregistrer'; }, 1500); }
      this.detail.user_brief = user_brief;
      this.detail.catalog = catalog;
      // La valeur serveur est à jour : le cache de saisie n'a plus lieu d'être.
      this._composeCache = null;
      return true;
    } catch (e) {
      if (btn) { btn.disabled = false; btn.textContent = 'Enregistrer'; }
      Toast.friendlyError(e, 'Le pitch n’a pas pu être enregistré.');
      return false;
    }
  },

  async _generate(limit) {
    const isTest = !!(limit && limit > 0);
    this._genIsTest = isTest;
    // On sauvegarde d'abord brief + catalogue ; si ça échoue, on ne lance
    // pas la génération (elle travaillerait sur l'ancien brief).
    const saved = await this._saveCompose();
    if (!saved) return;

    // Désactive les boutons pour éviter double-clic
    const btTest = document.getElementById('cv-gen-test');
    const btAll  = document.getElementById('cv-gen-all');
    const restoreBtTest = btTest ? btTest.textContent : '';
    const restoreBtAll  = btAll  ? btAll.textContent  : '';
    if (btTest) { btTest.disabled = true; btTest.textContent = isTest ? 'Génération…' : 'Tester (5)'; }
    if (btAll)  { btAll.disabled  = true; if (!isTest) btAll.textContent = 'Génération…'; }
    this._genRestoreBtns = () => {
      if (btTest) { btTest.disabled = false; btTest.textContent = restoreBtTest || 'Tester (5)'; }
      if (btAll)  { btAll.disabled  = false; btAll.textContent  = restoreBtAll  || 'Générer tous les mails'; }
    };

    // Affiche le bandeau de progression et masque le journal détaillé
    // (il reste accessible plus bas si on veut voir les détails).
    const prog = document.getElementById('cv-gen-progress');
    const sub  = document.getElementById('cv-gen-progress-sub');
    if (prog) prog.classList.remove('hidden');
    if (sub)  sub.textContent = isTest
      ? 'L\'IA rédige 5 mails test. Tu seras emmené sur l\'aperçu dès que c\'est prêt.'
      : 'L\'IA rédige tous tes mails un par un. Ça peut prendre quelques minutes.';

    const wrap = document.getElementById('cv-gen-log-wrap');
    const box  = document.getElementById('cv-gen-log');
    if (wrap) wrap.classList.remove('hidden');
    if (box)  box.textContent = '';
    this.genSeen = 0;

    let r;
    try {
      r = await App.api.convoy_generate_messages({
        campaign_id: this.detail.id,
        limit: limit || null,
        test_mode: isTest,
      });
    } catch (e) { r = { ok: false, error: String(e) }; }
    if (!r || !r.ok) {
      this._appendLog(box, r && r.error || 'Lancement impossible');
      this._toast(r && r.error || 'La génération n’a pas pu démarrer.', 'danger');
      if (prog) prog.classList.add('hidden');
      if (this._genRestoreBtns) this._genRestoreBtns();
      return;
    }
    this._genRunning = true;
    this._startGenPoll();
  },

  _startGenPoll() {
    if (this.genPoll) clearInterval(this.genPoll);
    // App.viewInterval : nettoyé automatiquement quand on quitte la vue
    // (plus de minuteur fantôme qui continue à interroger le serveur).
    this.genPoll = App.viewInterval
      ? App.viewInterval(() => this._pollGen(), 1500)
      : setInterval(() => this._pollGen(), 1500);
    this._pollGen();
  },

  async _pollGen() {
    if (!App.api) return;
    let r;
    try {
      r = await App.api.convoy_generation_status({
        campaign_id: this.detail.id, since: this.genSeen,
      });
    } catch (e) { return; }
    if (!r || !r.ok) return;
    const box = document.getElementById('cv-gen-log');
    (r.log || []).forEach(line => this._appendLog(box, line));
    this.genSeen = r.log_len;

    // Met à jour le sous-titre du bandeau de progression avec la
    // dernière ligne du journal (compteur du type "(3/5) OK").
    const sub = document.getElementById('cv-gen-progress-sub');
    if (sub && r.log && r.log.length) {
      const lastLine = r.log[r.log.length - 1] || '';
      // garde uniquement le message utile (après le timestamp)
      const m = lastLine.match(/\]\s*(.+)$/);
      if (m) sub.textContent = m[1];
    }

    if (!r.running) {
      clearInterval(this.genPoll); this.genPoll = null;
      this._genRunning = false;
      const prog = document.getElementById('cv-gen-progress');
      if (prog) prog.classList.add('hidden');
      if (this._genRestoreBtns) this._genRestoreBtns();
      if (r.error) this._toast('La génération s’est arrêtée sur une erreur. Regarde le journal en bas de l’étape 3.', 'danger');
      // Recharge la campagne pour rafraîchir les drafts (sujet/corps)
      try {
        const c2 = await App.api.convoy_get_campaign({ campaign_id: this.detail.id });
        if (c2 && c2.ok) {
          this.detail = c2.campaign;
          await this._loadList();
          // À la fin d'un TEST, on emmène directement Jordan voir ses
          // mails — sinon il ne sait pas où ils sont apparus.
          if (this._genIsTest) {
            this.wizardStep = 4;
          }
          // Le contenu vient d'être réécrit par l'IA : ne pas recopier le
          // vieux DOM par-dessus (voir _captureStepState).
          this._skipDraftCapture = true;
          this._renderDetail();
          // Scroll en haut pour qu'il voie les TEST en première ligne
          try { window.scrollTo({ top: 0, behavior: 'smooth' }); } catch (e) {}
        }
      } catch (e) {}
    }
  },

  // ---- Étape 5 : Envoi ---------------------------------------------
  // Convertit « YYYY-MM-DD HH:mm » (format serveur) ↔ « YYYY-MM-DDTHH:mm »
  // (format du champ datetime-local).
  _schedToInput(v)  { return String(v || '').trim().slice(0, 16).replace(' ', 'T'); },
  _schedToServer(v) { return String(v || '').trim().slice(0, 16).replace('T', ' '); },

  _stepSend(c) {
    const senderHtml = this._renderSenderSelect(c);
    // Saisie en cours (cache anti-perte) > valeur serveur
    const cache = this._sendCache || {};
    const modeValue  = (cache.mode != null) ? cache.mode : (c.mode || 'validation');
    const capValue   = (cache.daily_cap != null) ? cache.daily_cap : (c.daily_cap || 40);
    const delayValue = (cache.delay_seconds != null) ? cache.delay_seconds : (c.delay_seconds || 60);
    const schedValue = (cache.schedule_at != null)
      ? cache.schedule_at : this._schedToInput(c.schedule_at || '');
    // Bilan du dernier envoi : réinjecté tel quel s'il concerne CETTE
    // campagne — il ne disparaît plus au premier re-render.
    const sum = this._lastSendSummary;
    const summaryHtml = (sum && sum.cid === c.id) ? this._sendSummaryHtml(sum.s) : '';
    const running = !!this._sendRunning;
    return `
      ${this._sectionOpen('5. Mode d’envoi & lancement',
        'AUTO : tout part dès que tu lances. VALIDATION : tu approuves chaque mail un par un avant le départ.')}
        ${senderHtml}
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <label class="block">
            <div class="text-xs font-medium text-text-secondary mb-1.5">Mode</div>
            <select id="cv-mode"
                    class="w-full px-3 py-2 rounded-lg bg-bg border border-border
                           focus:border-accent focus:outline-none text-sm">
              <option value="validation" ${modeValue === 'validation' ? 'selected' : ''}>Validation manuelle (recommandé)</option>
              <option value="auto"       ${modeValue === 'auto'       ? 'selected' : ''}>Auto (envoi sans demander)</option>
            </select>
          </label>
          <label class="block">
            <div class="text-xs font-medium text-text-secondary mb-1.5">Plafond d'envois aujourd'hui</div>
            <input id="cv-cap" type="number" min="1" value="${this._esc(capValue)}"
                   class="w-full px-3 py-2 rounded-lg bg-bg border border-border
                          focus:border-accent focus:outline-none text-sm" />
            <div class="text-[11px] text-text-muted mt-1">
              Plafond de la campagne ; chaque adresse cochée plus haut a aussi son propre plafond quotidien.
            </div>
          </label>
          <label class="block">
            <div class="text-xs font-medium text-text-secondary mb-1.5">Délai entre 2 envois (secondes)</div>
            <input id="cv-delay" type="number" min="5" value="${this._esc(delayValue)}"
                   class="w-full px-3 py-2 rounded-lg bg-bg border border-border
                          focus:border-accent focus:outline-none text-sm" />
          </label>
          <label class="block">
            <div class="text-xs font-medium text-text-secondary mb-1.5">Démarrer à (vide = maintenant)</div>
            <input id="cv-sched" type="datetime-local" value="${this._esc(schedValue)}"
                   class="w-full px-3 py-2 rounded-lg bg-bg border border-border
                          focus:border-accent focus:outline-none text-sm" />
          </label>
        </div>
        <div class="flex flex-wrap gap-2 mt-4">
          <button id="cv-save-send" class="btn btn-secondary">Enregistrer</button>
          <button id="cv-start-send" class="btn btn-primary" ${running ? 'disabled' : ''}
                  ${running ? 'title="Un envoi est déjà en cours pour cette campagne."' : ''}>
            <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><polygon points="5 3 19 12 5 21 5 3"/></svg>
            ${running ? 'Envoi en cours…' : 'Lancer le convoi'}
          </button>
          <button id="cv-stop-send" class="btn btn-secondary text-danger ${running ? '' : 'hidden'}">
            ⏹ Arrêter
          </button>
        </div>

        ${summaryHtml}
        <div id="cv-send-log-wrap" class="mt-4 ${running ? '' : 'hidden'}">
          <div class="text-xs font-medium text-text-secondary mb-1.5">Journal d'envoi</div>
          <pre id="cv-send-log"
               class="text-xs font-mono leading-relaxed p-3 rounded-lg bg-bg
                      border border-border max-h-48 overflow-auto whitespace-pre-wrap"></pre>
        </div>
      ${this._sectionClose()}
    `;
  },

  _bindStepSend() {
    const save = document.getElementById('cv-save-send');
    if (save) save.onclick = () => this._saveSendSettings();
    const start = document.getElementById('cv-start-send');
    if (start) start.onclick = () => this._startSend();
    const stop  = document.getElementById('cv-stop-send');
    if (stop)  stop.onclick = () => this._stopSend();
    // Multi-adresses : on écoute les changements sur les checkboxes ET
    // les champs "cap" pour rafraîchir le récapitulatif en temps réel.
    document.querySelectorAll('.cv-sp-check').forEach(cb => {
      cb.addEventListener('change', () => this._refreshSenderPreview());
    });
    document.querySelectorAll('.cv-sp-cap').forEach(inp => {
      inp.addEventListener('input', () => this._refreshSenderPreview());
    });
    // Récap initial dès le rendu (sinon il reste vide au premier affichage)
    this._refreshSenderPreview();
    // Si la liste des comptes n'est pas encore chargée, on la charge
    // puis on re-rend cette étape pour afficher les vraies options.
    if (!Array.isArray(this.mailAccounts)) {
      this._loadMailAccounts().then(() => {
        if (this.wizardStep === 5) this._renderDetail();
      });
    }
    // Reprise : un envoi tourne déjà côté serveur (page rechargée, retour
    // sur l'étape…) → on raccroche le suivi du journal depuis le début
    // (le bloc journal vient d'être recréé vide). Le bouton Lancer est
    // déjà désactivé et le bouton Arrêter visible (posés au rendu).
    if (this._sendRunning) {
      this.sendSeen = 0;
      this._startSendPoll();
    }
  },

  // Sélecteur d'adresses expéditrices — multi-adresses avec cap par compte
  // sur fenêtre 24h glissantes. Au moment d'envoyer, le moteur tire au
  // hasard parmi les adresses cochées qui ont encore de la marge.
  _renderSenderSelect(c) {
    const accounts = this.mailAccounts || [];
    if (accounts.length === 0) {
      return `
        <div class="cv-sender-block">
          <div class="text-xs font-medium text-text-secondary mb-1.5">Adresses expéditrices</div>
          <div class="text-xs text-text-muted px-3 py-2 rounded-lg bg-bg border border-border">
            Aucun compte mail configuré. Va dans Réglages pour ajouter ton compte principal,
            ou un compte secondaire (ex : Lagriffe).
          </div>
        </div>`;
    }
    // Reconstruit la map id → cap déjà sauvegardée (sender_pool)
    const savedPool = Array.isArray(c && c.sender_pool) ? c.sender_pool : [];
    const capById = {};
    for (const entry of savedPool) {
      if (entry && entry.account_id) {
        capById[entry.account_id] = parseInt(entry.daily_cap, 10) || 0;
      }
    }
    // Si rien de sauvegardé, on coche le compte par défaut (sender_account_id)
    // avec un cap initial raisonnable (= daily_cap de la campagne ou 30).
    const fallbackId = (c && c.sender_account_id) || 'primary';
    const fallbackCap = (c && parseInt(c.daily_cap, 10)) || 30;
    if (savedPool.length === 0 && this._findAccount(fallbackId)) {
      capById[fallbackId] = fallbackCap;
    }
    // Saisie en cours non enregistrée (cache anti-perte) : prime sur le serveur
    const cachedRows = {};
    if (this._sendCache && Array.isArray(this._sendCache.senderRows)) {
      for (const row of this._sendCache.senderRows) cachedRows[row.id] = row;
    }

    const rows = accounts.map(a => {
      const cached = cachedRows[a.id];
      const checked = cached ? !!cached.checked : (capById[a.id] || 0) > 0;
      const cap = cached ? (parseInt(cached.cap, 10) || 30) : (capById[a.id] || 30);
      const fromEmail = this._esc(a.from_email || '');
      const fromName = a.from_name ? ` (${this._esc(a.from_name)})` : '';
      const lbl = this._esc(a.label || a.from_email || a.id);
      return `
        <label class="cv-sender-row" data-account-id="${this._esc(a.id)}"
               style="display:flex; align-items:center; gap:10px; padding:8px 10px;
                      border:1px solid hsl(var(--border)); border-radius:8px;
                      margin-bottom:6px; background: hsl(var(--bg));">
          <input type="checkbox" class="cv-sp-check" ${checked ? 'checked' : ''}
                 data-account-id="${this._esc(a.id)}">
          <div style="flex:1; min-width:0;">
            <div style="font-size:13px; font-weight:600;">${lbl}</div>
            <div style="font-size:11px; color: hsl(var(--text-muted));">${fromEmail}${fromName}</div>
          </div>
          <div style="display:flex; align-items:center; gap:4px;">
            <input type="number" class="cv-sp-cap" min="1" max="1000"
                   value="${cap}" data-account-id="${this._esc(a.id)}"
                   style="width:64px; padding:6px 8px; border-radius:6px;
                          background: hsl(var(--card)); color: hsl(var(--text));
                          border:1px solid hsl(var(--border)); font-size:12px;
                          text-align:right;">
            <span style="font-size:11px; color: hsl(var(--text-muted));">/ 24h</span>
          </div>
        </label>`;
    }).join('');

    return `
      <div class="cv-sender-block mb-3">
        <div class="text-xs font-medium text-text-secondary mb-1.5">
          Adresses expéditrices (les mails seront répartis au hasard entre celles cochées)
        </div>
        <div id="cv-sender-list">${rows}</div>
        <div id="cv-sender-summary" class="text-xs text-text-muted mt-2"></div>
      </div>
    `;
  },

  _refreshSenderPreview() {
    // Met à jour le récap : "X adresses cochées · jusqu'à Y mails / 24h"
    const summary = document.getElementById('cv-sender-summary');
    if (!summary) return;
    const checks = document.querySelectorAll('.cv-sp-check');
    let nChecked = 0, totalCap = 0;
    checks.forEach(cb => {
      if (!cb.checked) return;
      nChecked += 1;
      const capInput = document.querySelector(
        `.cv-sp-cap[data-account-id="${cb.dataset.accountId}"]`
      );
      totalCap += parseInt((capInput && capInput.value) || 0, 10) || 0;
    });
    if (nChecked === 0) {
      summary.innerHTML = '<span style="color:hsl(var(--danger-text));">⚠ Aucune adresse cochée — l’envoi ne pourra pas démarrer.</span>';
    } else {
      summary.textContent = `${nChecked} adresse(s) cochée(s) · jusqu'à ${totalCap} mails / 24h glissantes au total.`;
    }
  },

  // Récupère et VALIDE les réglages d'envoi. Renvoie null si une valeur
  // est invalide (avec message explicite) — plus de remplacement
  // silencieux d'un 0 ou d'un champ vide par 40/60.
  _gatherSendSettings() {
    // Récupère le sender_pool depuis les checkboxes + champs cap
    const pool = [];
    document.querySelectorAll('.cv-sp-check').forEach(cb => {
      if (!cb.checked) return;
      const id = cb.dataset.accountId;
      const capInput = document.querySelector(
        `.cv-sp-cap[data-account-id="${id}"]`
      );
      const cap = parseInt((capInput && capInput.value) || 0, 10) || 0;
      if (id && cap > 0) {
        pool.push({ account_id: id, daily_cap: cap });
      }
    });
    // Sender par défaut = premier coché (ou primary en fallback)
    const senderId = (pool[0] && pool[0].account_id) || 'primary';

    const capRaw = ((document.getElementById('cv-cap') || {}).value || '').trim();
    const cap = parseInt(capRaw, 10);
    if (!capRaw || isNaN(cap) || cap < 1) {
      this._toast('Le plafond d’envois doit être un nombre d’au moins 1.', 'danger');
      return null;
    }
    const delayRaw = ((document.getElementById('cv-delay') || {}).value || '').trim();
    const delay = parseInt(delayRaw, 10);
    if (!delayRaw || isNaN(delay) || delay < 5) {
      this._toast('Le délai entre 2 envois doit être d’au moins 5 secondes.', 'danger');
      return null;
    }
    return {
      campaign_id: this.detail.id,
      mode: (document.getElementById('cv-mode') || {}).value || 'validation',
      daily_cap: cap,
      delay_seconds: delay,
      schedule_at: this._schedToServer((document.getElementById('cv-sched') || {}).value || ''),
      sender_account_id: senderId,
      sender_pool: pool,
    };
  },

  async _saveSendSettings() {
    const settings = this._gatherSendSettings();
    if (!settings) return false;  // valeur invalide → message déjà affiché
    const btn = document.getElementById('cv-save-send');
    if (btn) { btn.disabled = true; btn.textContent = 'Enregistrement…'; }
    let r;
    try { r = await App.api.convoy_save_send_settings(settings); }
    catch (e) { r = { ok: false, error: String(e) }; }
    if (r && r.ok) {
      if (r.campaign) this.detail = r.campaign;
      // Valeurs serveur à jour → le cache de saisie n'a plus lieu d'être.
      this._sendCache = null;
      if (btn) { btn.textContent = 'Enregistré ✓'; setTimeout(() => { btn.disabled = false; btn.textContent = 'Enregistrer'; }, 1500); }
      return true;
    }
    if (btn) { btn.disabled = false; btn.textContent = 'Enregistrer'; }
    console.warn('[convoy] sauvegarde réglages :', r && r.error);
    this._toast('Les réglages d’envoi n’ont pas pu être enregistrés.', 'danger');
    return false;
  },

  async _startSend() {
    const start = document.getElementById('cv-start-send');
    if (start && start.disabled) return;  // déjà en cours
    const saved = await this._saveSendSettings();
    if (!saved) return;

    // Récapitulatif + confirmation avant le vrai départ (surtout en AUTO,
    // où tout part sans validation mail par mail).
    const c = this.detail || {};
    const drafts = c.drafts || [];
    const mode = c.mode || 'validation';
    const nApproved = drafts.filter(d => d.status === 'approved').length;
    const nPending  = drafts.filter(d => d.status === 'pending').length;
    const nReady = mode === 'auto' ? (nApproved + nPending) : nApproved;
    if (nReady === 0) {
      this._toast(mode === 'auto'
        ? 'Aucun mail à envoyer. Génère d’abord les mails à l’étape 3.'
        : 'Aucun mail approuvé. Approuve-les à l’étape 4, ou passe en mode auto.', 'danger');
      return;
    }
    const pool = Array.isArray(c.sender_pool) && c.sender_pool.length
      ? c.sender_pool.map(e => e.account_id)
      : [c.sender_account_id || 'primary'];
    const fromList = pool
      .map(id => { const a = this._findAccount(id); return a ? a.from_email : id; })
      .filter(Boolean).join(', ');
    const modeLabel = mode === 'auto' ? 'AUTOMATIQUE (tout part sans autre validation)' : 'validation';
    const okGo = await Dialog.confirm(
      `${nReady} mail${nReady > 1 ? 's' : ''} prêt${nReady > 1 ? 's' : ''} `
      + `vont partir en mode ${modeLabel}, depuis ${fromList || 'ton adresse principale'}. Lancer ?`,
      { title: 'Lancer le convoi ?', okLabel: 'Lancer', danger: mode === 'auto' },
    );
    if (!okGo) return;

    // Nouveau lancement = nouveau bilan : on réarme l'affichage de fin.
    this._sendSummaryShown = false;
    this._lastSendSummary = null;
    const oldBanner = document.getElementById('cv-end-banner');
    if (oldBanner) oldBanner.remove();

    if (start) { start.disabled = true; }
    const wrap = document.getElementById('cv-send-log-wrap');
    const box  = document.getElementById('cv-send-log');
    const stopBtn = document.getElementById('cv-stop-send');
    if (wrap) wrap.classList.remove('hidden');
    if (box)  box.textContent = '';
    this.sendSeen = 0;
    let r;
    try { r = await App.api.convoy_start_send({ campaign_id: this.detail.id }); }
    catch (e) { r = { ok: false, error: String(e) }; }
    if (!r || !r.ok) {
      this._appendLog(box, r && r.error || 'Démarrage impossible');
      this._toast(r && r.error || 'L’envoi n’a pas pu démarrer.', 'danger');
      if (start) { start.disabled = false; }
      return;
    }
    this._sendRunning = true;
    if (stopBtn) stopBtn.classList.remove('hidden');
    this._startSendPoll();
  },

  async _stopSend() {
    const stop = document.getElementById('cv-stop-send');
    if (stop) stop.disabled = true;
    try {
      await App.api.convoy_stop_send({ campaign_id: this.detail.id });
      this._toast('Demande d’arrêt envoyée — le convoi s’arrête après le mail en cours.', 'info');
    } catch (e) {
      if (stop) stop.disabled = false;
      Toast.friendlyError(e, 'La demande d’arrêt n’a pas pu partir.');
    }
  },

  _startSendPoll() {
    if (this.sendPoll) clearInterval(this.sendPoll);
    // App.viewInterval : auto-nettoyé quand on quitte la vue.
    this.sendPoll = App.viewInterval
      ? App.viewInterval(() => this._pollSend(), 1500)
      : setInterval(() => this._pollSend(), 1500);
    this._pollSend();
  },

  async _pollSend() {
    if (!App.api) return;
    let r;
    try {
      r = await App.api.convoy_send_status({
        campaign_id: this.detail.id, since: this.sendSeen,
      });
    } catch (e) { return; }
    if (!r || !r.ok) return;
    const box = document.getElementById('cv-send-log');
    (r.log || []).forEach(line => this._appendLog(box, line));
    this.sendSeen = r.log_len;
    if (!r.running) {
      clearInterval(this.sendPoll); this.sendPoll = null;
      this._sendRunning = false;
      const stopBtn = document.getElementById('cv-stop-send');
      if (stopBtn) stopBtn.classList.add('hidden');
      // Bandeau de fin : résumé clair, visible, qui dit ce qui s'est
      // passé sans avoir à lire le journal. Mémorisé dans
      // _lastSendSummary → _stepSend le réinjecte à CHAQUE re-render,
      // il ne disparaît plus.
      if (r.summary && !this._sendSummaryShown) {
        this._sendSummaryShown = true;
        this._renderSendSummary(r.summary);
      }
      try {
        const c2 = await App.api.convoy_get_campaign({ campaign_id: this.detail.id });
        if (c2 && c2.ok) {
          this.detail = c2.campaign;
          this._renderDetail();
          await this._loadList();
        }
      } catch (e) {}
    }
  },

  // Construit le HTML du bandeau de fin d'envoi (réutilisé par _stepSend
  // pour le ré-afficher après chaque re-render).
  _sendSummaryHtml(s) {
    if (!s) return '';
    // Choix d'humeur du bandeau : tout envoyé OK → vert,
    // au moins 1 échec → orange, stop manuel → bleu, rien envoyé → gris.
    let kind = 'success';
    let title = 'Convoi terminé';
    if (s.stopped_by_user) {
      kind = 'info';
      title = 'Convoi arrêté';
    } else if (s.failed > 0) {
      kind = 'warning';
      title = 'Convoi terminé avec des échecs';
    } else if (s.sent === 0) {
      kind = 'info';
      title = 'Convoi terminé — aucun envoi';
    }

    const mins = Math.floor((s.duration_s || 0) / 60);
    const secs = (s.duration_s || 0) % 60;
    const dur  = mins > 0 ? `${mins} min ${secs} s` : `${secs} s`;

    // Phrase humaine de récap, à la première personne du Convoi.
    let phrase;
    if (s.stopped_by_user) {
      phrase = `Tu m'as demandé d'arrêter. J'ai envoyé <b>${s.sent}</b> mail`
             + `${s.sent > 1 ? 's' : ''} sur les <b>${s.planned}</b> prévus.`;
    } else if (s.sent > 0 && s.failed === 0) {
      phrase = `J'ai bien envoyé tes <b>${s.sent}</b> mail`
             + `${s.sent > 1 ? 's' : ''} en <b>${dur}</b>. Tout est parti sans souci.`;
    } else if (s.sent > 0 && s.failed > 0) {
      phrase = `J'ai envoyé <b>${s.sent}</b> mail${s.sent > 1 ? 's' : ''} `
             + `et <b>${s.failed}</b> n'${s.failed > 1 ? 'ont' : 'a'} pas pu partir. `
             + `Durée totale : <b>${dur}</b>.`;
    } else if (s.failed > 0) {
      phrase = `Aucun mail n'a pu partir. <b>${s.failed}</b> tentative`
             + `${s.failed > 1 ? 's' : ''} en échec sur ${s.planned} prévue`
             + `${s.planned > 1 ? 's' : ''}.`;
    } else {
      phrase = `Il n'y avait rien à envoyer pour cette campagne.`;
    }

    // Détail compteurs : seulement les non-nuls pour rester propre.
    const bits = [];
    if (s.sent)     bits.push(`<span class="cv-summary-stat cv-summary-stat-ok">✓ ${s.sent} envoyé${s.sent > 1 ? 's' : ''}</span>`);
    if (s.failed)   bits.push(`<span class="cv-summary-stat cv-summary-stat-ko">✗ ${s.failed} échec${s.failed > 1 ? 's' : ''}</span>`);
    if (s.pending)  bits.push(`<span class="cv-summary-stat">… ${s.pending} en attente</span>`);
    if (s.rejected) bits.push(`<span class="cv-summary-stat">↷ ${s.rejected} rejeté${s.rejected > 1 ? 's' : ''}</span>`);

    return `
      <div class="cv-end-banner cv-end-banner-${kind} mb-4 mt-4"
           id="cv-end-banner">
        <div class="cv-end-banner-title">${title}</div>
        <div class="cv-end-banner-body">${phrase}</div>
        ${bits.length ? `<div class="cv-end-banner-stats">${bits.join('')}</div>` : ''}
      </div>
    `;
  },

  _renderSendSummary(s) {
    if (!s) return;
    // Mémorise le bilan AVEC l'id de campagne : _stepSend ne le réinjecte
    // que pour la bonne campagne (pas de bilan fantôme sur une autre).
    this._lastSendSummary = { cid: this.detail && this.detail.id, s };

    const html = this._sendSummaryHtml(s);
    // Insère le bandeau juste au-dessus du journal d'envoi.
    const wrap = document.getElementById('cv-send-log-wrap');
    if (!wrap) return;
    const old = document.getElementById('cv-end-banner');
    if (old) old.remove();
    wrap.insertAdjacentHTML('beforebegin', html);
    wrap.previousElementSibling.scrollIntoView({ behavior: 'smooth', block: 'center' });
  },

  // ---- Étape 4 : Aperçu & validation (brouillons / résultats) -------
  _stepResults(c) {
    const drafts = c.drafts || [];
    const counts = this._counts(drafts);

    // Tri : mails TEST tout en haut → pending non vide → à revoir (2e IA)
    // → approved → pending vide (pas encore générés) → sent → failed →
    // doublons ignorés → rejected. Permet à Jordan de retrouver
    // instantanément ses 5 tests sans scroller, et de voir d'abord ce
    // qui demande son attention (en attente PUIS à revoir).
    const order = { pending: 1, needs_review: 2, approved: 3, sent: 4,
                    failed: 5, skipped_duplicate: 6, rejected: 7 };
    const sorted = drafts.slice().sort((a, b) => {
      const ta = !!a.is_test, tb = !!b.is_test;
      if (ta !== tb) return ta ? -1 : 1;
      const ea = !(a.subject || a.body), eb = !(b.subject || b.body);
      // Parmi les pending : non-vides avant vides
      const sa = order[a.status] || 9;
      const sb = order[b.status] || 9;
      if (sa !== sb) return sa - sb;
      if (sa === 1 && ea !== eb) return ea ? 1 : -1;
      return 0;
    });

    const testCount = drafts.filter(d => d.is_test).length;
    const testBanner = testCount > 0 ? `
      <div class="cv-test-banner mb-4">
        <span class="cv-test-pill">TEST</span>
        Tu as <b>${testCount}</b> mail${testCount > 1 ? 's' : ''} test
        en haut de la liste. Vérifie-${testCount > 1 ? 'les' : 'le'},
        puis génère le reste si tu es satisfait.
      </div>
    ` : '';

    const approveAllBtn = counts.pending > 0 ? `
      <div class="flex justify-end mb-3">
        <button id="cv-approve-all" class="btn btn-secondary">
          ✓ Tout approuver (${counts.pending})
        </button>
      </div>
    ` : '';

    return `
      ${this._sectionOpen('4. Aperçu & validation',
        'Édite, approuve ou rejette chaque mail. Les envoyés sont marqués ✓.')}
        <div id="cv-kpis">${this._kpisHtml(counts)}</div>
        ${testBanner}
        ${approveAllBtn}
        <div class="space-y-3">
          ${sorted.map(d => this._draftCard(d)).join('')}
        </div>
      ${this._sectionClose()}
    `;
  },

  // Rangée de KPI de l'étape 4 — isolée pour pouvoir la rafraîchir seule
  // après une approbation (sans re-render complet qui ferait perdre le
  // scroll et la saisie).
  _kpisHtml(counts) {
    const kpis = [
      this._kpi('Total',      counts.total),
      this._kpi('En attente', counts.pending, counts.pending > 0 ? 'warning' : ''),
      this._kpi('À revoir',   counts.needs_review, counts.needs_review > 0 ? 'warning' : ''),
      this._kpi('Approuvés',  counts.approved, counts.approved > 0 ? 'accent' : ''),
      this._kpi('Envoyés',    counts.sent,    counts.sent > 0 ? 'success' : ''),
      this._kpi('Échecs',     counts.failed,  counts.failed > 0 ? 'danger' : ''),
      this._kpi('Rejetés',    counts.rejected),
    ];
    if (counts.skipped_duplicate > 0) {
      kpis.push(this._kpi('Doublons ignorés', counts.skipped_duplicate));
    }
    return `<div class="grid grid-cols-3 sm:grid-cols-4 gap-3 mb-5">${kpis.join('')}</div>`;
  },

  _counts(drafts) {
    const out = { total: drafts.length, pending: 0, approved: 0, sent: 0,
                  failed: 0, rejected: 0, needs_review: 0,
                  skipped_duplicate: 0 };
    for (const d of drafts) if (out[d.status] !== undefined) out[d.status]++;
    return out;
  },

  _draftCard(d) {
    const p = d.prospect || {};
    const recipient = p.raison_sociale || p.prenom || p.email || '(sans destinataire)';
    const badge = this._statusBadge(d.status);
    const empty = !d.subject && !d.body;
    // needs_review reste ÉDITABLE (c'est justement un mail à corriger) ;
    // failed est figé mais propose « Réessayer » dans le pied de carte.
    const locked = ['sent', 'failed', 'rejected', 'skipped_duplicate'].includes(d.status);
    const testBadge = d.is_test
      ? `<span class="cv-test-pill" title="Mail test généré via « Tester (5) »">TEST</span>`
      : '';
    // Adresse expéditrice utilisée pour CE draft :
    // - override produit (offer_mail_account_id) s'il existe
    // - sinon le compte de la campagne (sender_account_id)
    const camp = this.detail || {};
    const useId = (d.offer_mail_account_id || '').trim()
                || camp.sender_account_id
                || 'primary';
    const acc = this._findAccount(useId);
    const accFromEmail = acc ? (acc.from_email || '') : '';
    const senderInfo = accFromEmail
      ? `<span class="cv-draft-sender" title="${this._esc(useId === 'primary' ? 'compte principal' : 'compte ' + useId)}">✉ ${this._esc(accFromEmail)}</span>`
      : '';
    const cardCls = d.is_test ? 'card p-4 cv-draft-test' : 'card p-4';
    return `
      <article class="${cardCls}" data-draft-card="${this._esc(d.id)}">
        <header class="flex items-start justify-between gap-3 mb-2">
          <div class="min-w-0 flex-1">
            <div class="font-semibold text-sm truncate flex items-center gap-2">
              ${testBadge}
              <span class="truncate">${this._esc(recipient)}</span>
            </div>
            <div class="text-xs text-text-muted break-all flex flex-wrap gap-x-2 gap-y-0.5 mt-0.5">
              <span>${this._esc(p.email || '')}</span>
              ${p.ville ? `<span>· ${this._esc(p.ville)}</span>` : ''}
              ${d.offer_name ? `<span>· 🎯 ${this._esc(d.offer_name)}</span>` : ''}
              ${senderInfo ? `<span>· ${senderInfo}</span>` : ''}
            </div>
          </div>
          ${badge}
        </header>
        ${empty ? `
          <div class="text-xs text-text-muted italic py-3">
            (aucun message — clique « Générer tous les mails » à l'étape 3)
          </div>
        ` : `
          <label class="block mb-2">
            <div class="text-[11px] font-medium text-text-secondary mb-1">OBJET</div>
            <input type="text" data-subject value="${this._esc(d.subject || '')}"
                   ${locked ? 'disabled' : ''}
                   class="w-full px-3 py-1.5 rounded-lg bg-bg border border-border
                          focus:border-accent focus:outline-none text-sm font-semibold disabled:opacity-60" />
          </label>
          <label class="block mb-3">
            <div class="text-[11px] font-medium text-text-secondary mb-1">CORPS</div>
            <textarea data-body rows="6" ${locked ? 'disabled' : ''}
                      class="w-full px-3 py-2 rounded-lg bg-bg border border-border
                             focus:border-accent focus:outline-none text-sm leading-relaxed
                             resize-y disabled:opacity-60">${this._esc(d.body || '')}</textarea>
          </label>
        `}
        ${d.status === 'skipped_duplicate' ? `
          <div class="text-xs text-text-muted mb-2" title="${this._esc(d.error || '')}">
            Déjà contacté par le passé (ou déjà client) — ce mail a été ignoré pour ne pas spammer.
          </div>
        ` : (d.error ? `<div class="text-xs text-danger mb-2">⚠ ${this._esc(d.error)}</div>` : '')}
        ${this._draftCardFooter(d, empty)}
      </article>
    `;
  },

  // Pied de carte selon le statut du brouillon. Avant : tout statut non
  // « pending » affichait « ✓ approuvé » (faux pour à revoir / doublon).
  _draftCardFooter(d, empty) {
    const st = d.status;
    if (st === 'failed') {
      return `
        <footer class="flex flex-wrap gap-2 justify-end items-center pt-2 border-t border-border">
          <span class="text-xs text-text-muted self-center">L'envoi a échoué.</span>
          <button class="btn btn-secondary" data-act="retry"
                  title="Remet ce mail dans la file — il repartira au prochain lancement du convoi.">
            ↻ Réessayer
          </button>
        </footer>
      `;
    }
    if (empty || ['sent', 'rejected', 'skipped_duplicate'].includes(st)) return '';
    if (st === 'approved') {
      return `
        <footer class="flex flex-wrap gap-2 justify-end pt-2 border-t border-border">
          <button class="btn btn-secondary" data-act="save">Enregistrer</button>
          <button class="btn btn-secondary text-danger" data-act="reject">Rejeter</button>
          <span class="text-xs text-accent self-center">✓ approuvé — partira au prochain lancement</span>
        </footer>
      `;
    }
    // pending + needs_review : Enregistrer / Rejeter / Approuver actifs
    const hint = st === 'needs_review'
      ? `<span class="text-xs text-warning-text self-center mr-auto">Relis-le, corrige si besoin, puis approuve ou rejette.</span>`
      : '';
    return `
      <footer class="flex flex-wrap gap-2 justify-end pt-2 border-t border-border">
        ${hint}
        <button class="btn btn-secondary" data-act="save">Enregistrer</button>
        <button class="btn btn-secondary text-danger" data-act="reject">Rejeter</button>
        <button class="btn btn-primary" data-act="approve">Approuver</button>
      </footer>
    `;
  },

  _bindStepResults() {
    document.querySelectorAll('article[data-draft-card]').forEach(card => {
      this._bindDraftCard(card);
    });
    // « Tout approuver » : tous les mails en attente d'un coup
    const all = document.getElementById('cv-approve-all');
    if (all) all.onclick = async () => {
      const nPending = ((this.detail && this.detail.drafts) || [])
        .filter(d => d.status === 'pending').length;
      if (nPending === 0) return;
      const okGo = await Dialog.confirm(
        `Approuver les ${nPending} mail${nPending > 1 ? 's' : ''} en attente ? `
        + `Ils partiront au prochain lancement du convoi.`,
        { title: 'Tout approuver ?', okLabel: 'Tout approuver' },
      );
      if (!okGo) return;
      all.disabled = true;
      let r;
      try { r = await App.api.convoy_approve_all({ campaign_id: this.detail.id }); }
      catch (e) { r = { ok: false, error: String(e) }; }
      if (!r || !r.ok) {
        all.disabled = false;
        console.warn('[convoy] tout approuver :', r && r.error);
        this._toast('L’approbation groupée a échoué. Réessaie.', 'danger');
        return;
      }
      this._toast(`${r.approved || nPending} mail(s) approuvé(s).`, 'success');
      // Recharge la campagne (statuts changés en masse) puis re-render
      // en préservant la position de lecture.
      const y = window.scrollY;
      try {
        const c2 = await App.api.convoy_get_campaign({ campaign_id: this.detail.id });
        if (c2 && c2.ok) {
          this.detail = c2.campaign;
          this._renderDetail();
          try { window.scrollTo(0, y); } catch (e) {}
        }
      } catch (e) {}
      await this._loadList();
    };
  },

  // Remplace UNE carte de brouillon dans le DOM (et les KPI), sans
  // re-render complet : le scroll et les autres cartes ne bougent pas.
  _refreshDraftCard(did) {
    const d = ((this.detail && this.detail.drafts) || []).find(x => x.id === did);
    const card = document.querySelector(`article[data-draft-card="${did}"]`);
    if (!d || !card) return;
    const tpl = document.createElement('template');
    tpl.innerHTML = this._draftCard(d).trim();
    const fresh = tpl.content.firstElementChild;
    card.replaceWith(fresh);
    this._bindDraftCard(fresh);
    this._refreshKpis();
  },

  _refreshKpis() {
    const counts = this._counts((this.detail && this.detail.drafts) || []);
    const wrap = document.getElementById('cv-kpis');
    if (wrap) wrap.innerHTML = this._kpisHtml(counts);
    const all = document.getElementById('cv-approve-all');
    if (all) {
      if (counts.pending > 0) {
        all.textContent = `✓ Tout approuver (${counts.pending})`;
        all.disabled = false;
      } else {
        all.parentElement && all.parentElement.remove();
      }
    }
  },

  _bindDraftCard(card) {
    const did = card.dataset.draftCard;
    const subj = card.querySelector('input[data-subject]');
    const body = card.querySelector('textarea[data-body]');
    const drafts = (this.detail && this.detail.drafts) || [];
    const local = drafts.find(x => x.id === did);

    const saveEdits = async () => {
      if (!subj && !body) return true;
      try {
        const r = await App.api.convoy_update_draft({
          campaign_id: this.detail.id, draft_id: did,
          subject: subj ? subj.value : undefined,
          body:    body ? body.value : undefined,
        });
        if (!r || !r.ok) throw new Error((r && r.error) || 'enregistrement refusé');
        if (local) {
          if (subj) local.subject = subj.value;
          if (body) local.body = body.value;
        }
        return true;
      } catch (e) {
        console.warn('[convoy] sauvegarde brouillon :', e);
        Toast.friendlyError(e, 'Le mail n’a pas pu être enregistré.');
        return false;
      }
    };

    const save = card.querySelector('[data-act="save"]');
    if (save) save.onclick = async () => {
      save.disabled = true; save.textContent = '…';
      const ok = await saveEdits();
      save.textContent = ok ? 'Enregistré ✓' : 'Enregistrer';
      setTimeout(() => { save.disabled = false; save.textContent = 'Enregistrer'; }, ok ? 1500 : 0);
    };

    const reject = card.querySelector('[data-act="reject"]');
    if (reject) reject.onclick = async () => {
      const who = (local && local.prospect && (local.prospect.email || local.prospect.raison_sociale)) || 'ce destinataire';
      const okGo = await Dialog.confirm(
        `Rejeter le mail pour ${who} ? Il ne sera pas envoyé.`,
        { title: 'Rejeter ce mail ?', okLabel: 'Rejeter', danger: true },
      );
      if (!okGo) return;
      reject.disabled = true;
      try {
        const r = await App.api.convoy_reject_draft({ campaign_id: this.detail.id, draft_id: did });
        if (!r || !r.ok) throw new Error((r && r.error) || 'rejet refusé');
        if (local) local.status = 'rejected';
        this._refreshDraftCard(did);
        this._toast('Mail rejeté.', 'info');
      } catch (e) {
        reject.disabled = false;
        Toast.friendlyError(e, 'Le rejet a échoué.');
      }
    };

    const approve = card.querySelector('[data-act="approve"]');
    if (approve) approve.onclick = async () => {
      approve.disabled = true;
      const okSave = await saveEdits();
      if (!okSave) { approve.disabled = false; return; }
      try {
        const r = await App.api.convoy_approve_draft({ campaign_id: this.detail.id, draft_id: did });
        if (!r || !r.ok) throw new Error((r && r.error) || 'approbation refusée');
        if (local) local.status = 'approved';
        this._refreshDraftCard(did);
      } catch (e) {
        approve.disabled = false;
        Toast.friendlyError(e, 'L’approbation a échoué.');
      }
    };

    // « Réessayer » (mail en échec) : remet le mail dans la file — le
    // serveur n'a pas de retour à « en attente », on repasse donc par
    // l'approbation (statut approuvé = repartira au prochain lancement).
    const retry = card.querySelector('[data-act="retry"]');
    if (retry) retry.onclick = async () => {
      retry.disabled = true;
      try {
        const r = await App.api.convoy_approve_draft({ campaign_id: this.detail.id, draft_id: did });
        if (!r || !r.ok) throw new Error((r && r.error) || 'remise en file refusée');
        if (local) { local.status = 'approved'; local.error = ''; }
        this._refreshDraftCard(did);
        this._toast('Mail remis dans la file — il repartira au prochain lancement.', 'success');
      } catch (e) {
        retry.disabled = false;
        Toast.friendlyError(e, 'La remise en file a échoué.');
      }
    };
  },

  // ------------------------------------------------------------------
  //  Helpers
  // ------------------------------------------------------------------
  _stopPollers() {
    if (this.genPoll)  { clearInterval(this.genPoll);  this.genPoll  = null; }
    if (this.sendPoll) { clearInterval(this.sendPoll); this.sendPoll = null; }
  },

  _statusBadge(status) {
    const map = {
      pending:  { label: 'À valider',   cls: 'bg-warning/15 text-warning-text',
                  title: 'En attente de ton approbation' },
      approved: { label: 'Approuvé',    cls: 'bg-accent/15 text-accent',
                  title: 'Partira au prochain lancement du convoi' },
      sent:     { label: '✓ Envoyé',    cls: 'bg-success/15 text-success-text',
                  title: 'Mail parti' },
      failed:   { label: 'Échec',       cls: 'bg-danger/15 text-danger-text',
                  title: 'L’envoi a échoué — bouton Réessayer en bas de la carte' },
      rejected: { label: 'Rejeté',      cls: 'bg-text-muted/15 text-text-muted',
                  title: 'Tu as écarté ce mail, il ne partira pas' },
      needs_review:      { label: '⚠ À revoir', cls: 'bg-warning/15 text-warning-text',
                  title: 'La 2e IA a un doute sur ce mail — relis-le avant d’approuver' },
      skipped_duplicate: { label: 'Doublon ignoré', cls: 'bg-text-muted/15 text-text-muted',
                  title: 'Déjà contacté ou déjà client — non renvoyé' },
    };
    const m = map[status] || { label: status, cls: 'bg-text-muted/15 text-text-muted', title: '' };
    return `<span class="px-2 py-0.5 rounded-full text-[11px] font-semibold whitespace-nowrap ${m.cls}"
                  title="${this._esc(m.title || '')}">${m.label}</span>`;
  },

  _kpi(label, value, accent) {
    const cls = accent ? `accent-${accent}` : '';
    return `
      <div class="stat-card ${cls}">
        <div class="label">${this._esc(label)}</div>
        <div class="value">${this._esc(value)}</div>
      </div>
    `;
  },

  _sectionOpen(title, subtitle) {
    return `
      <section class="card p-5 sm:p-6">
        <div class="mb-4">
          <div class="font-semibold text-base">${this._esc(title)}</div>
          ${subtitle ? `<div class="text-sm text-text-muted mt-1">${this._esc(subtitle)}</div>` : ''}
        </div>
    `;
  },

  _sectionClose() {
    return `</section>`;
  },

  _appendLog(box, line) {
    if (!box) return;
    box.textContent += line + '\n';
    box.scrollTop = box.scrollHeight;
  },

  _toast(msg, kind = 'info') {
    // Système commun de messages (toujours chargé avant cette vue)
    if (typeof Toast !== 'undefined' && Toast.show) {
      const type = kind === 'danger' ? 'error' : kind;
      Toast.show(msg, { type, title: 'Le Convoi' });
      return;
    }
    if (typeof HealthCheck !== 'undefined' && HealthCheck.toast) {
      HealthCheck.toast('Le Convoi', msg, kind === 'danger' ? 'error' : kind);
      return;
    }
    // Filet minimal
    console.log(`[convoy:${kind}]`, msg);
  },

  _previewBanner() {
    return `
      <div class="card p-10 text-center">
        <div class="text-4xl mb-3">📂</div>
        <h2 class="text-xl font-semibold mb-2">Mode aperçu</h2>
        <p class="text-text-secondary max-w-md mx-auto">
          Connecte-toi pour importer et envoyer une liste.
        </p>
      </div>
    `;
  },

  _esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    }[c]));
  },
};
