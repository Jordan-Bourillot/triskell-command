/* Catalogue — vue Triskell Command
 *
 * Une page sobre avec :
 *   - un titre + sous-titre
 *   - un menu déroulant qui liste TOUS les produits de l'écosystème Triskell
 *     (lus depuis le même catalogue que le launcher Ctrl+K : apps.json)
 *   - une fiche produit qui s'affiche en dessous quand on choisit un élément
 *     (logo, tagline, catégorie, prix/statut, bouton "Ouvrir le produit")
 *
 * Si l'API n'est pas dispo (preview), on retombe sur le même mini-catalogue
 * que Launcher._previewCatalog().
 */

const Catalogue = {
  apps: null,
  selectedId: '',

  CATEGORY_LABELS: {
    quotidien: 'Quotidien',
    pro:       'Atelier des pros',
  },

  PREVIEW: [
    { id:'obelisk',   name:'Obelisk',       tagline:'Trouve les créateurs vierges de ta niche.',  category:'pro',       logo:'assets/apps/obelisk.png',         price:129 },
    { id:'eliks',     name:'Eliks Studio',  tagline:'Service growth operator multi-réseaux.',     category:'pro',       logo:'assets/apps/eliks-studio.svg' },
    { id:'alphacast', name:'AlphaCast',     tagline:'Publie une fois, atteins toutes tes audiences.', category:'pro',   logo:'assets/apps/alphacast.png',       coming_soon:true },
  ],

  async render(container) {
    this._root = container;
    container.innerHTML = `
      <section class="animate-slide-up max-w-3xl">
        <div class="mb-8">
          <div class="hero-kicker mb-2">CATALOGUE</div>
          <h1 class="hero-title mb-3" style="font-size: 36px;">Tous les outils de l'écosystème Triskell.</h1>
          <p class="hero-subtitle">Choisis un produit dans la liste pour voir sa fiche et l'ouvrir.</p>
        </div>

        <div class="card p-6 mb-6">
          <label for="catalogue-select"
                 class="block text-[11px] font-bold tracking-widest text-text-muted mb-2">
            PRODUIT
          </label>
          <select id="catalogue-select"
                  class="w-full px-4 py-3 rounded-xl
                         bg-bg border border-border
                         text-text text-[15px]
                         focus:border-accent focus:outline-none
                         transition-colors cursor-pointer">
            <option value="">— Choisis un produit —</option>
          </select>
        </div>

        <div id="catalogue-detail"></div>
      </section>
    `;

    await this._loadApps();
    this._populateSelect();

    const sel = document.getElementById('catalogue-select');
    if (sel) {
      sel.addEventListener('change', (e) => {
        this.selectedId = e.target.value;
        this._renderDetail();
      });
    }
  },

  async _loadApps() {
    if (App && App.api && typeof App.api.get_apps_catalog === 'function') {
      try {
        const data = await App.api.get_apps_catalog();
        this.apps = (data && data.ok) ? (data.apps || []) : [];
        return;
      } catch (e) {
        console.warn('catalogue: get_apps_catalog failed', e);
      }
    }
    this.apps = this.PREVIEW;
  },

  _populateSelect() {
    const sel = document.getElementById('catalogue-select');
    if (!sel) return;
    const apps = (this.apps || []).slice().sort((a, b) => {
      return (a.name || '').localeCompare(b.name || '', 'fr');
    });
    const groups = {};
    apps.forEach(a => {
      const cat = a.category || 'autre';
      (groups[cat] = groups[cat] || []).push(a);
    });
    const order = ['quotidien', 'pro', 'autre'];
    let html = `<option value="">— Choisis un produit —</option>`;
    order.forEach(cat => {
      const list = groups[cat];
      if (!list || !list.length) return;
      const label = this.CATEGORY_LABELS[cat] || 'Autres';
      html += `<optgroup label="${this._esc(label)}">`;
      list.forEach(a => {
        const suffix = a.coming_soon ? ' (bientôt)' : '';
        html += `<option value="${this._esc(a.id)}">${this._esc(a.name)}${suffix}</option>`;
      });
      html += `</optgroup>`;
    });
    sel.innerHTML = html;
  },

  _renderDetail() {
    const box = document.getElementById('catalogue-detail');
    if (!box) return;
    if (!this.selectedId) { box.innerHTML = ''; return; }
    const app = (this.apps || []).find(a => a.id === this.selectedId);
    if (!app) { box.innerHTML = ''; return; }

    const badge = app.coming_soon
      ? `<span class="px-2.5 py-1 rounded-md text-[11px] font-semibold bg-text-muted/15 text-text-muted">Bientôt</span>`
      : app.installed
        ? `<span class="px-2.5 py-1 rounded-md text-[11px] font-semibold bg-success/15 text-success">Installé</span>`
        : (app.price != null
            ? `<span class="px-2.5 py-1 rounded-md text-[11px] font-semibold bg-accent/15 text-accent">${app.price} €</span>`
            : '');

    const catLabel = this.CATEGORY_LABELS[app.category] || '';
    const canOpen  = !app.coming_soon && (app.exe_path || app.buy_url);

    box.innerHTML = `
      <div class="card p-6 animate-fade-in">
        <div class="flex items-start gap-5 mb-5">
          <img src="${this._esc(app.logo)}" alt=""
               class="w-16 h-16 rounded-2xl shrink-0"
               style="object-fit: contain;" />
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-3 flex-wrap mb-1">
              <h2 class="text-xl font-bold leading-tight">${this._esc(app.name)}</h2>
              ${badge}
            </div>
            ${catLabel ? `<div class="text-[11px] tracking-widest font-bold text-text-muted">${this._esc(catLabel.toUpperCase())}</div>` : ''}
          </div>
        </div>

        <p class="text-text-secondary leading-relaxed mb-5">
          ${this._esc(app.tagline || '')}
        </p>

        <div class="flex flex-wrap gap-2">
          ${canOpen ? `
            <button id="catalogue-open" class="btn btn-primary">
              ${app.installed ? 'Ouvrir' : 'Découvrir'}
            </button>
          ` : ''}
        </div>
      </div>
    `;

    const openBtn = document.getElementById('catalogue-open');
    if (openBtn) {
      openBtn.addEventListener('click', async () => {
        if (App && App.api && typeof App.api.launch_app === 'function') {
          try {
            await App.api.launch_app({
              exe_path: app.exe_path || '',
              url:      app.buy_url  || '',
            });
            return;
          } catch (e) { console.warn('catalogue: launch_app failed', e); }
        }
        if (app.buy_url) window.open(app.buy_url, '_blank', 'noopener,noreferrer');
      });
    }
  },

  _esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    }[c]));
  },
};
