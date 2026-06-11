/* Vue Kits de livraison — éditeur des contenus envoyés après vente.
 *
 * Un kit par produit. Chaque kit contient :
 *  - Un mail de bienvenue (sujet, corps, livrables : URL+label)
 *  - Une série de relances de suivi (J+3, J+14, etc.)
 *
 * Variables disponibles dans subject/body : {client_name}, {product_name},
 * {deliverables_list}, {signature}.
 */

const Delivery = {
  kits: null,           // dict {product_key: kit}
  selectedKey: null,    // produit en cours d'édition
  _dirty: false,        // modifications non enregistrées ?

  // Vue de retour : celle d'où on vient si elle est connue (tuto, recherche…),
  // sinon les Réglages.
  _backTarget() {
    const prev = App.previousView;
    if (prev && prev !== 'delivery' && Array.isArray(App.KNOWN_VIEWS) && App.KNOWN_VIEWS.includes(prev)) {
      return prev;
    }
    return 'config';
  },

  async render(container) {
    const backTarget = this._backTarget();
    const backLabel = backTarget === 'config' ? '← Réglages' : '← Retour';
    container.innerHTML = `
      <section class="animate-slide-up max-w-6xl">
        <div class="mb-8">
          <div class="flex items-start justify-between gap-3">
            <div>
              <div class="hero-kicker mb-2">LIVRAISON AUTO</div>
              <h1 class="hero-title mb-3" style="font-size: 36px;">Tes kits de livraison.</h1>
              <p class="hero-subtitle">Ce qui part automatiquement à un client juste après son achat,
                pour chaque produit Triskell.</p>
            </div>
            ${Help.button('delivery')}
          </div>
          <div class="flex gap-3 mt-6 flex-wrap">
            <button id="d-back" class="btn btn-secondary">${this._esc(backLabel)}</button>
            <button id="d-add"  class="btn btn-secondary">+ Nouveau produit</button>
            <button id="d-save" class="btn btn-primary">Enregistrer tout</button>
          </div>
        </div>

        <div id="d-content" class="grid grid-cols-1 lg:grid-cols-12 gap-6"></div>
      </section>
    `;

    this._dirty = false;
    // Drapeau « modifications non enregistrées » : un seul écouteur délégué,
    // il survit aux re-rendus internes de l'éditeur.
    const content = document.getElementById('d-content');
    content.addEventListener('input', () => { this._dirty = true; });

    document.getElementById('d-back').onclick = async () => {
      if (this._dirty) {
        const ok = await Dialog.confirm(
          'Tes modifications ne sont pas enregistrées et seront perdues. Quitter quand même ?',
          { title: 'Modifications non enregistrées', okLabel: 'Quitter sans enregistrer', cancelLabel: 'Rester', danger: true }
        );
        if (!ok) return;
      }
      App.show(backTarget);
    };
    document.getElementById('d-add').onclick  = () => this._addProduct();
    document.getElementById('d-save').onclick = () => this.save();

    if (!App.api) {
      content.innerHTML = this._previewBanner();
      return;
    }

    let r;
    try { r = await App.api.delivery_kits_list(); }
    catch (e) { r = { ok: false, error: String(e) }; }
    if (!r || !r.ok) {
      console.warn('delivery_kits_list:', r && r.error);
      content.innerHTML = `
        <div class="col-span-full card p-8 text-center">
          <p class="text-sm text-danger mb-3">Impossible de charger les kits de livraison.</p>
          <button id="d-retry" class="btn btn-secondary">Réessayer</button>
        </div>`;
      const retry = document.getElementById('d-retry');
      if (retry) retry.onclick = () => this.render(container);
      return;
    }
    this.kits = r.kits || {};
    // Sélection initiale : 1er produit non _default
    const keys = Object.keys(this.kits).filter(k => k !== '_default');
    this.selectedKey = keys[0] || '_default';
    this._renderLayout();
  },

  // ------------------------------------------------------------------
  _renderLayout() {
    const content = document.getElementById('d-content');
    const keys = Object.keys(this.kits);
    content.innerHTML = `
      <!-- Sidebar produits -->
      <aside class="lg:col-span-3">
        <div class="card p-3 lg:sticky lg:top-6">
          <div class="text-[11px] font-bold tracking-widest text-text-muted px-2 mb-2">PRODUITS</div>
          <nav class="space-y-1" id="d-nav">
            ${keys.map(k => this._navItem(k)).join('')}
          </nav>
        </div>
      </aside>
      <!-- Éditeur du kit sélectionné -->
      <main class="lg:col-span-9 space-y-6" id="d-editor"></main>
    `;
    this._bindNav();
    this._renderEditor();
  },

  _navItem(key) {
    const kit = this.kits[key] || {};
    const name = key === '_default'
      ? 'Kit par défaut (si aucun kit dédié)'
      : (kit.product_name || key);
    const isActive = key === this.selectedKey;
    return `
      <button data-key="${this._esc(key)}"
              class="w-full text-left px-3 py-2 rounded-lg text-sm transition-colors
                     ${isActive
                        ? 'bg-accent-strong text-white font-semibold'
                        : 'hover:bg-bg text-text-secondary'}">
        <div class="truncate">${this._esc(name)}</div>
        <div class="text-[11px] opacity-70 truncate">${this._esc(key)}</div>
      </button>
    `;
  },

  _bindNav() {
    document.querySelectorAll('#d-nav [data-key]').forEach(btn => {
      btn.onclick = () => {
        // Sauve l'éditeur courant en mémoire avant de switcher
        this._captureEditor();
        this.selectedKey = btn.dataset.key;
        this._renderLayout();
      };
    });
  },

  // ------------------------------------------------------------------
  _renderEditor() {
    const editor = document.getElementById('d-editor');
    const k = this.kits[this.selectedKey];
    if (!k) {
      editor.innerHTML = `<div class="card p-6 text-text-muted">(aucun kit sélectionné)</div>`;
      return;
    }
    const welcome = k.welcome || {};
    const fus     = k.follow_ups || [];

    editor.innerHTML = `
      <!-- Identité du kit -->
      <div class="card p-6 space-y-3">
        <div class="text-xs font-bold tracking-widest text-text-muted">IDENTIFIANT DU PRODUIT</div>
        <div class="flex items-center gap-3">
          <code class="text-sm bg-bg px-3 py-2 rounded-lg flex-1 select-all">${this._esc(this.selectedKey)}</code>
          ${this.selectedKey !== '_default' ? `
            <button class="btn btn-secondary text-danger" id="d-delete">Supprimer ce kit</button>` : ''}
        </div>
        ${this._input('Nom affiché (ex : « Pack Électricien Pro »)',
          'product_name', welcome ? (k.product_name || '') : '')}
      </div>

      <!-- Mail de bienvenue -->
      <div class="card p-6">
        <div class="text-xs font-bold tracking-widest text-text-muted mb-3">
          MAIL DE BIENVENUE
        </div>
        <div class="text-sm text-text-muted mb-4">
          Envoyé immédiatement après l'achat. Variables disponibles :
          <code class="text-[11px] bg-bg px-1.5 py-0.5 rounded">{client_name}</code>
          <code class="text-[11px] bg-bg px-1.5 py-0.5 rounded">{product_name}</code>
          <code class="text-[11px] bg-bg px-1.5 py-0.5 rounded">{deliverables_list}</code>
          <code class="text-[11px] bg-bg px-1.5 py-0.5 rounded">{signature}</code>
        </div>
        ${this._input('Objet du mail', 'welcome_subject', welcome.subject || '')}
        ${this._textarea('Corps du mail', 'welcome_body', welcome.body || '', 10)}

        <div class="mt-5">
          <div class="flex items-center justify-between mb-2">
            <div class="text-xs font-bold tracking-widest text-text-muted">LIVRABLES</div>
            <button class="text-[11px] text-accent hover:underline" id="d-add-deliv">+ Ajouter</button>
          </div>
          <div class="text-xs text-text-muted mb-3">
            URLs de téléchargement, codes d'accès, liens de portail client. Affichés dans le mail
            à l'emplacement <code class="bg-bg px-1 rounded">{deliverables_list}</code>.
          </div>
          <div id="d-delivs" class="space-y-2">
            ${(welcome.deliverables || []).map((d, i) => this._deliverableRow(d, i)).join('')}
          </div>
        </div>
      </div>

      <!-- Suivis programmés -->
      <div class="card p-6">
        <div class="flex items-center justify-between mb-3">
          <div class="text-xs font-bold tracking-widest text-text-muted">
            RELANCES DE SUIVI APRÈS VENTE
          </div>
          <button class="text-[11px] text-accent hover:underline" id="d-add-fu">+ Ajouter une relance</button>
        </div>
        <div class="text-sm text-text-muted mb-4">
          Mails envoyés automatiquement quelques jours après la livraison
          (ex : J+3 « ça va ? », J+14 astuce, J+30 demande d'avis).
        </div>
        <div id="d-fus" class="space-y-4">
          ${fus.map((fu, i) => this._followUpRow(fu, i)).join('')}
          ${fus.length === 0 ? `<div class="text-text-muted text-sm py-3">Aucune relance — clique « Ajouter ».</div>` : ''}
        </div>
      </div>

      <!-- Aperçu live -->
      <div class="card p-6">
        <div class="flex items-center justify-between mb-3">
          <div class="text-xs font-bold tracking-widest text-text-muted">APERÇU</div>
          <button class="btn btn-secondary text-xs" id="d-preview">Enregistrer et prévisualiser</button>
        </div>
        <div id="d-preview-out" class="text-sm text-text-muted">
          Clique « Enregistrer et prévisualiser » pour voir le mail rendu avec un client de test
          (tes kits sont d'abord enregistrés, puis l'aperçu s'affiche).
        </div>
      </div>
    `;

    // Bind locaux
    const del = document.getElementById('d-delete');
    if (del) del.onclick = () => this._deleteCurrent();
    document.getElementById('d-add-deliv').onclick = () => this._addDeliverable();
    document.getElementById('d-add-fu').onclick    = () => this._addFollowUp();
    document.getElementById('d-preview').onclick   = () => this._refreshPreview();
    this._bindRowDeletes();
  },

  // ------------------------------------------------------------------
  // Helpers HTML
  _input(label, key, value, placeholder = '') {
    return `
      <label class="block">
        <div class="text-xs font-medium text-text-secondary mb-1.5">${this._esc(label)}</div>
        <input type="text" data-k="${key}" value="${this._esc(value)}"
               placeholder="${this._esc(placeholder)}"
               class="w-full px-3 py-2 rounded-lg bg-bg border border-border
                      focus:border-accent focus:outline-none text-sm" />
      </label>
    `;
  },

  _textarea(label, key, value, rows = 5) {
    return `
      <label class="block">
        <div class="text-xs font-medium text-text-secondary mb-1.5">${this._esc(label)}</div>
        <textarea data-k="${key}" rows="${rows}"
                  class="w-full px-3 py-2 rounded-lg bg-bg border border-border
                         focus:border-accent focus:outline-none text-sm font-mono leading-relaxed
                         resize-y">${this._esc(value)}</textarea>
      </label>
    `;
  },

  _deliverableRow(d, idx) {
    return `
      <div class="flex items-start gap-2" data-deliv-row="${idx}">
        <input type="text" data-deliv-label="${idx}" value="${this._esc(d.label || '')}"
               placeholder="Étiquette (ex : Télécharger le pack)"
               class="w-1/3 px-3 py-2 rounded-lg bg-bg border border-border text-sm focus:border-accent focus:outline-none" />
        <input type="text" data-deliv-url="${idx}" value="${this._esc(d.url || '')}"
               placeholder="URL ou texte (ex : https://...)"
               class="flex-1 px-3 py-2 rounded-lg bg-bg border border-border text-sm focus:border-accent focus:outline-none" />
        <button class="text-text-muted hover:text-danger px-2" data-del-deliv="${idx}" title="Supprimer ce livrable" aria-label="Supprimer ce livrable">×</button>
      </div>
    `;
  },

  _followUpRow(fu, idx) {
    return `
      <div class="border border-border rounded-xl p-4 space-y-2" data-fu-row="${idx}">
        <div class="flex items-center justify-between mb-1">
          <div class="text-[11px] font-bold tracking-widest text-text-muted">RELANCE #${idx + 1}</div>
          <button class="text-text-muted hover:text-danger text-sm" data-del-fu="${idx}" title="Supprimer cette relance" aria-label="Supprimer cette relance">×</button>
        </div>
        <div class="grid grid-cols-1 sm:grid-cols-12 gap-2">
          <div class="sm:col-span-2">
            <label class="text-xs text-text-muted">Délai (jours)</label>
            <input type="number" min="0" data-fu-days="${idx}" value="${fu.days ?? 3}"
                   class="w-full px-2 py-1.5 rounded-lg bg-bg border border-border text-sm focus:border-accent focus:outline-none" />
          </div>
          <div class="sm:col-span-10">
            <label class="text-xs text-text-muted">Objet</label>
            <input type="text" data-fu-subject="${idx}" value="${this._esc(fu.subject || '')}"
                   class="w-full px-2 py-1.5 rounded-lg bg-bg border border-border text-sm focus:border-accent focus:outline-none" />
          </div>
        </div>
        <label class="block">
          <div class="text-xs text-text-muted mb-1">Corps</div>
          <textarea data-fu-body="${idx}" rows="4"
                    class="w-full px-2 py-1.5 rounded-lg bg-bg border border-border text-sm font-mono leading-relaxed resize-y focus:border-accent focus:outline-none">${this._esc(fu.body || '')}</textarea>
        </label>
      </div>
    `;
  },

  _bindRowDeletes() {
    document.querySelectorAll('[data-del-deliv]').forEach(b => {
      b.onclick = () => {
        this._captureEditor();
        const idx = parseInt(b.dataset.delDeliv, 10);
        const w = this.kits[this.selectedKey].welcome || {};
        (w.deliverables || []).splice(idx, 1);
        this._dirty = true;
        this._renderEditor();
      };
    });
    document.querySelectorAll('[data-del-fu]').forEach(b => {
      b.onclick = () => {
        this._captureEditor();
        const idx = parseInt(b.dataset.delFu, 10);
        (this.kits[this.selectedKey].follow_ups || []).splice(idx, 1);
        this._dirty = true;
        this._renderEditor();
      };
    });
  },

  _addDeliverable() {
    this._captureEditor();
    const k = this.kits[this.selectedKey];
    k.welcome = k.welcome || {};
    k.welcome.deliverables = k.welcome.deliverables || [];
    k.welcome.deliverables.push({ label: '', url: '' });
    this._dirty = true;
    this._renderEditor();
  },

  _addFollowUp() {
    this._captureEditor();
    const k = this.kits[this.selectedKey];
    k.follow_ups = k.follow_ups || [];
    k.follow_ups.push({ days: 3, subject: '', body: '' });
    this._dirty = true;
    this._renderEditor();
  },

  // Création d'un produit : mini-fenêtre maison. On demande le NOM du
  // produit (langage normal) ; l'identifiant interne est fabriqué tout
  // seul (minuscules, sans accents, tirets) et montré en aperçu.
  _addProduct() {
    const slugify = (s) => String(s || '')
      .normalize('NFD').replace(/[\u0300-\u036f]/g, '')  // retire les accents
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '');

    const overlay = document.createElement('div');
    overlay.className = 'fixed inset-0 z-[200] flex items-center justify-center p-4';
    overlay.style.background = 'hsl(var(--bg) / 0.7)';
    overlay.style.backdropFilter = 'blur(6px)';
    overlay.innerHTML = `
      <div class="card p-6 w-full max-w-md animate-slide-up" role="dialog" aria-modal="true" aria-label="Nouveau produit">
        <h3 class="text-base font-bold mb-1">Nouveau produit</h3>
        <p class="text-xs text-text-muted mb-4">Donne le nom du produit — l'identifiant interne est créé automatiquement.</p>
        <label class="block mb-3">
          <div class="text-xs font-medium text-text-secondary mb-1.5">Nom du produit</div>
          <input id="d-new-name" type="text" placeholder="Ex : Pack Électricien Pro"
                 class="w-full px-3 py-2 rounded-lg bg-bg border border-border focus:border-accent focus:outline-none text-sm" />
        </label>
        <div class="text-[11px] text-text-muted mb-3">Identifiant :
          <code id="d-new-slug" class="bg-bg px-1.5 py-0.5 rounded">—</code>
        </div>
        <div id="d-new-err" class="text-[11px] text-danger mb-3" hidden></div>
        <div class="flex justify-end gap-2">
          <button id="d-new-cancel" class="btn btn-secondary">Annuler</button>
          <button id="d-new-ok" class="btn btn-primary">Créer le kit</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);

    const nameEl = overlay.querySelector('#d-new-name');
    const slugEl = overlay.querySelector('#d-new-slug');
    const errEl  = overlay.querySelector('#d-new-err');
    const showErr = (msg) => { errEl.textContent = msg; errEl.hidden = false; };

    const close = () => {
      document.removeEventListener('keydown', onEsc);
      overlay.remove();
    };
    // Échap / clic à côté : si du texte a été tapé, on confirme avant de jeter.
    const requestClose = async () => {
      if (nameEl.value.trim()) {
        const ok = await Dialog.confirm(
          'Abandonner la création de ce produit ?',
          { title: 'Nouveau produit', okLabel: 'Abandonner', cancelLabel: 'Continuer la saisie', danger: true }
        );
        if (!ok) return;
      }
      close();
    };
    const onEsc = (e) => { if (e.key === 'Escape') requestClose(); };
    document.addEventListener('keydown', onEsc);
    overlay.addEventListener('click', (e) => { if (e.target === overlay) requestClose(); });
    overlay.querySelector('#d-new-cancel').onclick = requestClose;

    nameEl.addEventListener('input', () => {
      slugEl.textContent = slugify(nameEl.value) || '—';
      errEl.hidden = true;
    });
    const create = () => {
      const name = nameEl.value.trim();
      const cleaned = slugify(name);
      if (!cleaned) { showErr('Donne un nom au produit.'); nameEl.focus(); return; }
      if (this.kits[cleaned]) { showErr('Un kit existe déjà pour ce produit.'); return; }
      this._captureEditor();
      this.kits[cleaned] = {
        product_name: name,
        welcome: {
          subject: 'Bienvenue dans ' + name,
          body: 'Bonjour {client_name},\n\nMerci pour ton achat.\n\n{deliverables_list}\n\n{signature}',
          deliverables: [],
        },
        follow_ups: [],
      };
      this.selectedKey = cleaned;
      this._dirty = true;
      close();
      this._renderLayout();
    };
    overlay.querySelector('#d-new-ok').onclick = create;
    nameEl.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); create(); } });
    setTimeout(() => nameEl.focus(), 50);
  },

  async _deleteCurrent() {
    if (this.selectedKey === '_default') return;
    const ok = await Dialog.confirm(
      `Supprimer le kit « ${this.selectedKey} » ?\nLes clients de ce produit recevront le kit par défaut.\n\nLa suppression sera effective après « Enregistrer tout ».`,
      { title: 'Supprimer ce kit', okLabel: 'Supprimer', cancelLabel: 'Annuler', danger: true }
    );
    if (!ok) return;
    delete this.kits[this.selectedKey];
    const keys = Object.keys(this.kits).filter(k => k !== '_default');
    this.selectedKey = keys[0] || '_default';
    this._dirty = true;
    this._renderLayout();
  },

  // ------------------------------------------------------------------
  // Capture les valeurs du formulaire dans this.kits[selectedKey]
  _captureEditor() {
    const k = this.kits[this.selectedKey];
    if (!k) return;
    const get = (key) => {
      const el = document.querySelector(`[data-k="${key}"]`);
      return el ? el.value : '';
    };
    // Le nom affiché doit pouvoir être VIDÉ (le menu retombe alors sur
    // l'identifiant) — on capture la valeur telle quelle si le champ existe.
    const nameEl = document.querySelector('[data-k="product_name"]');
    if (nameEl) k.product_name = nameEl.value.trim();
    k.welcome = k.welcome || {};
    if (document.querySelector('[data-k="welcome_subject"]')) {
      k.welcome.subject = get('welcome_subject');
    }
    if (document.querySelector('[data-k="welcome_body"]')) {
      k.welcome.body = get('welcome_body');
    }
    // Livrables
    const delivs = [];
    document.querySelectorAll('[data-deliv-row]').forEach(row => {
      const idx = row.dataset.delivRow;
      delivs.push({
        label: (document.querySelector(`[data-deliv-label="${idx}"]`) || {}).value || '',
        url:   (document.querySelector(`[data-deliv-url="${idx}"]`) || {}).value || '',
      });
    });
    k.welcome.deliverables = delivs;
    // Follow-ups
    const fus = [];
    document.querySelectorAll('[data-fu-row]').forEach(row => {
      const idx = row.dataset.fuRow;
      fus.push({
        // Jamais de délai négatif (l'input a min="0", on borne aussi ici)
        days:    Math.max(0, parseInt((document.querySelector(`[data-fu-days="${idx}"]`) || {}).value || '0', 10) || 0),
        subject: (document.querySelector(`[data-fu-subject="${idx}"]`) || {}).value || '',
        body:    (document.querySelector(`[data-fu-body="${idx}"]`) || {}).value || '',
      });
    });
    k.follow_ups = fus;
  },

  // ------------------------------------------------------------------
  // Enregistre tous les kits. Renvoie true/false (réutilisé par l'aperçu).
  // Échec → message d'erreur durable (Toast) avec la vraie raison en
  // console (avant : « Erreur » 1,6 seconde sans explication).
  async save() {
    if (!App.api) return false;
    this._captureEditor();
    const btn = document.getElementById('d-save');
    if (btn) { btn.disabled = true; btn.textContent = 'Enregistrement…'; }
    let ok = false;
    try {
      const r = await App.api.delivery_kits_save({ kits: this.kits });
      ok = !!(r && r.ok);
      if (ok) {
        this._dirty = false;
        Toast.success('Kits de livraison enregistrés.');
      } else {
        Toast.friendlyError(r && r.error, `L'enregistrement des kits n'a pas abouti — tes modifications ne sont PAS sauvées.`);
      }
    } catch (e) {
      Toast.friendlyError(e, `L'enregistrement des kits n'a pas abouti — tes modifications ne sont PAS sauvées.`);
    }
    if (btn) {
      btn.disabled = false;
      btn.textContent = ok ? 'Enregistré ✓' : 'Enregistrer tout';
      if (ok) setTimeout(() => { btn.textContent = 'Enregistrer tout'; }, 1600);
    }
    return ok;
  },

  async _refreshPreview() {
    if (!App.api) return;
    const previewBtn = document.getElementById('d-preview');
    if (previewBtn) previewBtn.disabled = true;
    try {
      // Le bouton s'appelle « Enregistrer et prévisualiser » : on enregistre
      // d'abord (rendu côté serveur, mêmes substitutions). Si l'enregistrement
      // échoue, on s'arrête là — save() a déjà prévenu.
      const saved = await this.save();
      if (!saved) return;
      let r;
      try { r = await App.api.delivery_kit_preview({ product_key: this.selectedKey }); }
      catch (e) { r = { ok: false, error: String(e) }; }
      const out = document.getElementById('d-preview-out');
      if (!out) return;
      if (!r || !r.ok) {
        console.warn('delivery_kit_preview:', r && r.error);
        out.innerHTML = `<div class="text-danger text-sm">Impossible de générer l'aperçu. Réessaie dans un instant.</div>`;
        return;
      }
      const w = r.welcome || {};
      const fus = r.follow_ups || [];
      out.innerHTML = `
        <div class="border border-border rounded-xl p-4 mb-4">
          <div class="text-[11px] font-bold tracking-widest text-text-muted mb-1">MAIL DE BIENVENUE</div>
          <div class="font-semibold text-sm mb-2">${this._esc(w.subject || '(sans objet)')}</div>
          <pre class="whitespace-pre-wrap font-mono text-xs leading-relaxed text-text-secondary">${this._esc(w.body || '')}</pre>
        </div>
        ${fus.map((fu, i) => `
          <div class="border border-border rounded-xl p-4 mb-3">
            <div class="text-[11px] font-bold tracking-widest text-text-muted mb-1">RELANCE J+${fu.days}</div>
            <div class="font-semibold text-sm mb-2">${this._esc(fu.subject || '(sans objet)')}</div>
            <pre class="whitespace-pre-wrap font-mono text-xs leading-relaxed text-text-secondary">${this._esc(fu.body || '')}</pre>
          </div>
        `).join('')}
      `;
    } finally {
      if (previewBtn) previewBtn.disabled = false;
    }
  },

  _previewBanner() {
    return `
      <div class="col-span-full card p-8 text-center">
        <div class="text-3xl mb-3">📦</div>
        <h2 class="text-xl font-semibold mb-2">Connexion au serveur impossible</h2>
        <p class="text-text-secondary max-w-md mx-auto">
          Recharge la page pour réessayer d'éditer les kits de livraison.
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
