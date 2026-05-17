/* Catalogue — vue Triskell Command
 *
 * Page sobre avec un menu déroulant qui liste les 4 sites/offres
 * actuellement visibles dans le catalogue : Lagriffe, RankUs, WoW, Eliks.
 *
 * Quand on choisit un produit, sa fiche apparaît en dessous avec un
 * bouton "Ouvrir le site" qui pointe vers l'URL publique.
 */

const Catalogue = {
  selectedId: '',

  // Liste fixe — on n'affiche QUE ces 4 entrées pour le moment.
  ITEMS: [
    {
      id: 'lagriffe',
      name: 'Lagriffe Studio',
      tagline: 'Création de sites premium pour artisans et indépendants.',
      url: 'https://lagriffe-studio.fr',
      color: '#d4af37',
      initial: 'L',
    },
    {
      id: 'rankus',
      name: 'RankUs Studio',
      tagline: 'Agence SEO — on fait monter ton site dans Google.',
      url: 'https://rankus.fr',
      color: '#10b981',
      initial: 'R',
    },
    {
      id: 'wow',
      name: 'Studio WoW',
      tagline: 'Sites web haut de gamme avec effets immersifs.',
      url: 'https://studio-wow.fr',
      color: '#C9A572',
      initial: 'W',
    },
    {
      id: 'eliks',
      name: 'Eliks Studio',
      tagline: 'Growth Operator — on transforme tes réseaux en machine à ventes.',
      url: 'https://eliks.triskell-studio.fr',
      color: '#6366F1',
      initial: 'E',
      logo: 'assets/apps/eliks-studio.svg',
    },
  ],

  async render(container) {
    this._root = container;
    container.innerHTML = `
      <section class="animate-slide-up max-w-3xl">
        <div class="mb-8">
          <div class="hero-kicker mb-2">CATALOGUE</div>
          <h1 class="hero-title mb-3" style="font-size: 36px;">Les sites de l'écosystème Triskell.</h1>
          <p class="hero-subtitle">Choisis une marque dans la liste pour voir sa fiche et ouvrir son site.</p>
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
            ${this.ITEMS.map(it => `
              <option value="${this._esc(it.id)}">${this._esc(it.name)}</option>
            `).join('')}
          </select>
        </div>

        <div id="catalogue-detail"></div>
      </section>
    `;

    const sel = document.getElementById('catalogue-select');
    if (sel) {
      sel.addEventListener('change', (e) => {
        this.selectedId = e.target.value;
        this._renderDetail();
      });
    }
  },

  _renderDetail() {
    const box = document.getElementById('catalogue-detail');
    if (!box) return;
    if (!this.selectedId) { box.innerHTML = ''; return; }
    const it = this.ITEMS.find(x => x.id === this.selectedId);
    if (!it) { box.innerHTML = ''; return; }

    const visual = it.logo
      ? `<img src="${this._esc(it.logo)}" alt="" class="w-16 h-16 rounded-2xl shrink-0" style="object-fit: contain;" />`
      : `<div class="w-16 h-16 rounded-2xl shrink-0 flex items-center justify-center text-white font-bold text-2xl"
              style="background: ${this._esc(it.color)};">${this._esc(it.initial)}</div>`;

    box.innerHTML = `
      <div class="card p-6 animate-fade-in">
        <div class="flex items-start gap-5 mb-5">
          ${visual}
          <div class="flex-1 min-w-0">
            <h2 class="text-xl font-bold leading-tight mb-1">${this._esc(it.name)}</h2>
            <div class="text-[11px] tracking-widest font-bold text-text-muted">${this._esc(it.url.replace(/^https?:\/\//, ''))}</div>
          </div>
        </div>

        <p class="text-text-secondary leading-relaxed mb-5">
          ${this._esc(it.tagline)}
        </p>

        <div class="flex flex-wrap gap-2">
          <button id="catalogue-open" class="btn btn-primary">Ouvrir le site</button>
        </div>
      </div>
    `;

    const openBtn = document.getElementById('catalogue-open');
    if (openBtn) {
      openBtn.addEventListener('click', async () => {
        if (App && App.api && typeof App.api.open_url === 'function') {
          try {
            await App.api.open_url({ url: it.url });
            return;
          } catch (e) { console.warn('catalogue: open_url failed', e); }
        }
        window.open(it.url, '_blank', 'noopener,noreferrer');
      });
    }
  },

  _esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    }[c]));
  },
};
