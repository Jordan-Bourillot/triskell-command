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

  async render(container) {
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
          <div class="flex gap-3 mt-6">
            <button id="d-back" class="btn btn-secondary">← Réglages</button>
            <button id="d-add"  class="btn btn-secondary">+ Nouveau produit</button>
            <button id="d-save" class="btn btn-primary">Enregistrer tout</button>
          </div>
        </div>

        <div id="d-content" class="grid grid-cols-12 gap-6"></div>
      </section>
    `;

    document.getElementById('d-back').onclick = () => App.show('config');
    document.getElementById('d-add').onclick  = () => this._addProduct();
    document.getElementById('d-save').onclick = () => this.save();

    if (!App.api) {
      document.getElementById('d-content').innerHTML = this._previewBanner();
      return;
    }

    let r;
    try { r = await App.api.delivery_kits_list(); }
    catch (e) { r = { ok: false, error: String(e) }; }
    if (!r || !r.ok) {
      document.getElementById('d-content').innerHTML = `
        <div class="col-span-12 card p-6 text-danger">
          Impossible de charger les kits : ${this._esc(r && r.error || 'erreur')}
        </div>`;
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
      <aside class="col-span-3">
        <div class="card p-3 sticky top-6">
          <div class="text-[10px] font-bold tracking-widest text-text-muted px-2 mb-2">PRODUITS</div>
          <nav class="space-y-1" id="d-nav">
            ${keys.map(k => this._navItem(k)).join('')}
          </nav>
        </div>
      </aside>
      <!-- Éditeur du kit sélectionné -->
      <main class="col-span-9 space-y-6" id="d-editor"></main>
    `;
    this._bindNav();
    this._renderEditor();
  },

  _navItem(key) {
    const kit = this.kits[key] || {};
    const name = key === '_default'
      ? 'Kit générique (fallback)'
      : (kit.product_name || key);
    const isActive = key === this.selectedKey;
    return `
      <button data-key="${this._esc(key)}"
              class="w-full text-left px-3 py-2 rounded-lg text-sm transition-colors
                     ${isActive
                        ? 'bg-accent text-white font-semibold'
                        : 'hover:bg-bg text-text-secondary'}">
        <div class="truncate">${this._esc(name)}</div>
        <div class="text-[10px] opacity-70 truncate">${this._esc(key)}</div>
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
          <button class="btn btn-secondary text-xs" id="d-preview">Rafraîchir l'aperçu</button>
        </div>
        <div id="d-preview-out" class="text-sm text-text-muted">
          Clique « Rafraîchir l'aperçu » pour voir le mail rendu avec un client de test.
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
        <button class="text-text-muted hover:text-danger px-2" data-del-deliv="${idx}" title="Supprimer">×</button>
      </div>
    `;
  },

  _followUpRow(fu, idx) {
    return `
      <div class="border border-border rounded-xl p-4 space-y-2" data-fu-row="${idx}">
        <div class="flex items-center justify-between mb-1">
          <div class="text-[11px] font-bold tracking-widest text-text-muted">RELANCE #${idx + 1}</div>
          <button class="text-text-muted hover:text-danger text-sm" data-del-fu="${idx}" title="Supprimer">×</button>
        </div>
        <div class="grid grid-cols-12 gap-2">
          <div class="col-span-2">
            <label class="text-xs text-text-muted">Délai (jours)</label>
            <input type="number" data-fu-days="${idx}" value="${fu.days ?? 3}"
                   class="w-full px-2 py-1.5 rounded-lg bg-bg border border-border text-sm focus:border-accent focus:outline-none" />
          </div>
          <div class="col-span-10">
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
        this._renderEditor();
      };
    });
    document.querySelectorAll('[data-del-fu]').forEach(b => {
      b.onclick = () => {
        this._captureEditor();
        const idx = parseInt(b.dataset.delFu, 10);
        (this.kits[this.selectedKey].follow_ups || []).splice(idx, 1);
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
    this._renderEditor();
  },

  _addFollowUp() {
    this._captureEditor();
    const k = this.kits[this.selectedKey];
    k.follow_ups = k.follow_ups || [];
    k.follow_ups.push({ days: 3, subject: '', body: '' });
    this._renderEditor();
  },

  _addProduct() {
    const slug = prompt(
      "Identifiant du produit (en minuscules, tirets, sans espace) :\n" +
      "Ex : « bobeez », « delinote », « teddy-mail »…"
    );
    if (!slug) return;
    const cleaned = slug.trim().toLowerCase().replace(/\s+/g, '-');
    if (!cleaned) return;
    if (this.kits[cleaned]) {
      alert('Un kit existe déjà pour ce produit.');
      return;
    }
    this._captureEditor();
    this.kits[cleaned] = {
      product_name: cleaned,
      welcome: {
        subject: 'Bienvenue dans ' + cleaned,
        body: 'Bonjour {client_name},\n\nMerci pour ton achat.\n\n{deliverables_list}\n\n{signature}',
        deliverables: [],
      },
      follow_ups: [],
    };
    this.selectedKey = cleaned;
    this._renderLayout();
  },

  _deleteCurrent() {
    if (this.selectedKey === '_default') return;
    if (!confirm("Supprimer le kit « " + this.selectedKey + " » ? Les clients de ce produit recevront le kit générique.")) return;
    delete this.kits[this.selectedKey];
    const keys = Object.keys(this.kits).filter(k => k !== '_default');
    this.selectedKey = keys[0] || '_default';
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
    if (get('product_name') !== '') k.product_name = get('product_name');
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
        days:    parseInt((document.querySelector(`[data-fu-days="${idx}"]`) || {}).value || '0', 10) || 0,
        subject: (document.querySelector(`[data-fu-subject="${idx}"]`) || {}).value || '',
        body:    (document.querySelector(`[data-fu-body="${idx}"]`) || {}).value || '',
      });
    });
    k.follow_ups = fus;
  },

  // ------------------------------------------------------------------
  async save() {
    if (!App.api) return;
    this._captureEditor();
    const btn = document.getElementById('d-save');
    btn.disabled = true; btn.textContent = 'Enregistrement…';
    try {
      const r = await App.api.delivery_kits_save({ kits: this.kits });
      btn.textContent = (r && r.ok) ? 'Enregistré ✓' : 'Erreur';
    } catch (e) { btn.textContent = 'Erreur'; }
    setTimeout(() => { btn.disabled = false; btn.textContent = 'Enregistrer tout'; }, 1600);
  },

  async _refreshPreview() {
    if (!App.api) return;
    this._captureEditor();
    // Sauve avant preview pour avoir le rendu côté serveur (même substitutions)
    await App.api.delivery_kits_save({ kits: this.kits });
    let r;
    try { r = await App.api.delivery_kit_preview({ product_key: this.selectedKey }); }
    catch (e) { r = { ok: false, error: String(e) }; }
    const out = document.getElementById('d-preview-out');
    if (!r || !r.ok) {
      out.innerHTML = `<div class="text-danger">Erreur preview : ${this._esc(r && r.error || 'erreur')}</div>`;
      return;
    }
    const w = r.welcome || {};
    const fus = r.follow_ups || [];
    out.innerHTML = `
      <div class="border border-border rounded-xl p-4 mb-4">
        <div class="text-[10px] font-bold tracking-widest text-text-muted mb-1">MAIL DE BIENVENUE</div>
        <div class="font-semibold text-sm mb-2">${this._esc(w.subject || '(sans objet)')}</div>
        <pre class="whitespace-pre-wrap font-mono text-xs leading-relaxed text-text-secondary">${this._esc(w.body || '')}</pre>
      </div>
      ${fus.map((fu, i) => `
        <div class="border border-border rounded-xl p-4 mb-3">
          <div class="text-[10px] font-bold tracking-widest text-text-muted mb-1">RELANCE J+${fu.days}</div>
          <div class="font-semibold text-sm mb-2">${this._esc(fu.subject || '(sans objet)')}</div>
          <pre class="whitespace-pre-wrap font-mono text-xs leading-relaxed text-text-secondary">${this._esc(fu.body || '')}</pre>
        </div>
      `).join('')}
    `;
  },

  _previewBanner() {
    return `
      <div class="col-span-12 card p-8 text-center">
        <div class="text-3xl mb-3">📦</div>
        <h2 class="text-xl font-semibold mb-2">Mode aperçu</h2>
        <p class="text-text-secondary max-w-md mx-auto">
          Lance Triskell Command via <code class="text-xs px-1.5 py-0.5 rounded bg-bg">py run_web.py</code>
          pour éditer les kits de livraison.
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
