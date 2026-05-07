/* Triskell Apps Launcher — Spotlight type Linear / Raycast / Cmd+K
 *
 * Overlay full-screen avec :
 * - Backdrop blur fort
 * - Champ recherche live (autofocus) en haut
 * - Grille immersive de tuiles avec les vrais logos normalisés
 * - Filtre par catégorie + statut
 * - Click sur une tuile → ouvre l'URL produit dans le navigateur par défaut
 *
 * Raccourci : Ctrl+K (ou Cmd+K sur Mac) depuis n'importe où.
 * Échap pour fermer.
 */

const Launcher = {
  apps: null,
  isOpen: false,
  query: '',
  category: 'all',  // all | quotidien | pro
  selectedIndex: 0, // pour navigation clavier

  CATEGORIES: {
    all:       'Tous',
    quotidien: 'Quotidien',
    pro:       'Atelier des pros',
  },

  // ---- Bootstrap ----
  init() {
    // Raccourci global Ctrl+K / Cmd+K
    window.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        this.toggle();
      }
      if (this.isOpen) {
        if (e.key === 'Escape') {
          e.preventDefault();
          this.close();
        }
        if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
          e.preventDefault();
          this._move(1);
        }
        if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
          e.preventDefault();
          this._move(-1);
        }
        if (e.key === 'Enter') {
          e.preventDefault();
          this._activateSelected();
        }
      }
    });
  },

  async toggle() {
    if (this.isOpen) this.close();
    else await this.open();
  },

  async open() {
    if (this.isOpen) return;
    this.isOpen = true;
    // Charge le catalogue (pas de cache → on récupère l'état frais)
    if (App.api) {
      try {
        const data = await App.api.get_apps_catalog();
        this.apps = (data && data.ok) ? data.apps : [];
      } catch (e) {
        this.apps = [];
      }
    } else {
      this.apps = this._previewCatalog();
    }
    this._render();
  },

  close() {
    if (!this.isOpen) return;
    this.isOpen = false;
    this.query = '';
    this.selectedIndex = 0;
    const ov = document.getElementById('launcher-overlay');
    if (ov) {
      ov.style.opacity = '0';
      ov.querySelector('.launcher-card').style.transform = 'scale(0.96) translateY(8px)';
      setTimeout(() => ov.remove(), 180);
    }
  },

  _filtered() {
    const q = this.query.trim().toLowerCase();
    return (this.apps || []).filter(a => {
      if (this.category !== 'all' && a.category !== this.category) return false;
      if (!q) return true;
      return (a.name || '').toLowerCase().includes(q)
          || (a.tagline || '').toLowerCase().includes(q)
          || (a.id || '').toLowerCase().includes(q);
    });
  },

  _render() {
    let ov = document.getElementById('launcher-overlay');
    if (!ov) {
      ov = document.createElement('div');
      ov.id = 'launcher-overlay';
      ov.className = 'fixed inset-0 z-[200] flex items-start justify-center pt-[10vh] px-6 transition-opacity duration-200';
      ov.style.background = 'rgba(15,23,42,0.55)';
      ov.style.backdropFilter = 'blur(14px)';
      ov.style.opacity = '0';
      document.body.appendChild(ov);
      ov.addEventListener('click', (e) => {
        if (e.target === ov) this.close();
      });
      requestAnimationFrame(() => { ov.style.opacity = '1'; });
    }
    const cats = Object.entries(this.CATEGORIES).map(([key, label]) => `
      <button data-cat="${key}"
              class="launcher-cat ${this.category === key ? 'active' : ''}">
        ${label}
      </button>
    `).join('');

    ov.innerHTML = `
      <div class="launcher-card bg-surface rounded-3xl shadow-hero
                  w-full max-w-[940px] max-h-[78vh] flex flex-col overflow-hidden
                  origin-top transition-transform duration-200"
           style="border: 1px solid hsl(var(--border)); transform: scale(0.96) translateY(8px);">
        <!-- Header recherche -->
        <div class="px-7 pt-6 pb-4 border-b border-border">
          <div class="flex items-center gap-3 mb-4">
            <svg class="w-5 h-5 text-text-muted shrink-0" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
              <circle cx="11" cy="11" r="8"/>
              <path d="m21 21-4.35-4.35"/>
            </svg>
            <input id="launcher-search" type="text"
                   placeholder="Cherche un outil Triskell…"
                   class="flex-1 bg-transparent border-0 outline-none text-lg
                          placeholder:text-text-muted text-text"
                   autocomplete="off" spellcheck="false" />
            <kbd class="text-[10px] font-bold text-text-muted bg-bg
                        px-2 py-1 rounded-md border border-border">ESC</kbd>
          </div>
          <div class="flex gap-2">${cats}</div>
        </div>

        <!-- Grille -->
        <div id="launcher-grid" class="flex-1 overflow-y-auto px-7 py-6"></div>

        <!-- Footer -->
        <div class="px-7 py-3 border-t border-border flex items-center justify-between text-xs text-text-muted">
          <div class="flex items-center gap-4">
            <span class="flex items-center gap-1"><kbd class="text-[10px] font-bold bg-bg px-1.5 py-0.5 rounded border border-border">↑↓</kbd> naviguer</span>
            <span class="flex items-center gap-1"><kbd class="text-[10px] font-bold bg-bg px-1.5 py-0.5 rounded border border-border">↵</kbd> ouvrir</span>
          </div>
          <div>
            <span><kbd class="text-[10px] font-bold bg-bg px-1.5 py-0.5 rounded border border-border">Ctrl K</kbd> rouvrir</span>
          </div>
        </div>
      </div>
    `;

    // Search bind
    const input = document.getElementById('launcher-search');
    input.addEventListener('input', (e) => {
      this.query = e.target.value;
      this.selectedIndex = 0;
      this._renderGrid();
    });
    setTimeout(() => input.focus(), 80);

    // Categories bind
    ov.querySelectorAll('[data-cat]').forEach(btn => {
      btn.onclick = () => {
        this.category = btn.dataset.cat;
        this.selectedIndex = 0;
        this._render();
      };
    });

    // Grille initiale
    this._renderGrid();

    // Animation d'entrée
    requestAnimationFrame(() => {
      ov.querySelector('.launcher-card').style.transform = 'scale(1) translateY(0)';
    });
  },

  _renderGrid() {
    const grid = document.getElementById('launcher-grid');
    if (!grid) return;
    const items = this._filtered();
    if (items.length === 0) {
      grid.innerHTML = `
        <div class="text-center py-16 text-text-muted">
          <div class="text-4xl mb-3 opacity-50">🔎</div>
          <div class="text-sm">Aucun outil ne correspond à « ${this._esc(this.query)} ».</div>
        </div>
      `;
      return;
    }
    grid.innerHTML = `
      <div class="grid grid-cols-3 md:grid-cols-4 gap-4">
        ${items.map((a, i) => this._tile(a, i)).join('')}
      </div>
    `;
    grid.querySelectorAll('[data-app-idx]').forEach(el => {
      const idx = parseInt(el.dataset.appIdx, 10);
      el.onclick = () => { this.selectedIndex = idx; this._activateSelected(); };
      el.onmouseenter = () => {
        this.selectedIndex = idx;
        this._highlightSelected();
      };
    });
    this._highlightSelected();
  },

  _tile(a, idx) {
    const badge = a.coming_soon
      ? `<span class="launcher-badge bg-text-muted/15 text-text-muted">Bientôt</span>`
      : a.installed
        ? `<span class="launcher-badge bg-success/15 text-success">Installé</span>`
        : (a.price != null
            ? `<span class="launcher-badge bg-accent/15 text-accent">${a.price} €</span>`
            : '');
    return `
      <button data-app-idx="${idx}"
              class="launcher-tile group relative text-left
                     bg-surface-elevated rounded-2xl p-5
                     border border-border hover:border-accent
                     transition-all duration-200
                     hover:scale-[1.03] hover:-translate-y-0.5 hover:shadow-soft
                     focus:outline-none">
        <div class="flex items-start gap-4 mb-3">
          <img src="${a.logo}" alt=""
               class="w-14 h-14 rounded-xl shrink-0"
               style="object-fit: contain;" />
          <div class="flex-1 min-w-0">
            <div class="font-semibold text-[15px] mb-0.5 leading-tight truncate">${this._esc(a.name)}</div>
            ${badge}
          </div>
        </div>
        <p class="text-xs text-text-secondary line-clamp-2 leading-snug min-h-[2.4em]">
          ${this._esc(a.tagline)}
        </p>
      </button>
    `;
  },

  _highlightSelected() {
    const tiles = document.querySelectorAll('[data-app-idx]');
    tiles.forEach((t, i) => {
      const idx = parseInt(t.dataset.appIdx, 10);
      if (idx === this.selectedIndex) {
        t.style.borderColor = 'hsl(var(--accent))';
        t.style.boxShadow = '0 0 0 3px hsl(var(--accent) / 0.18)';
      } else {
        t.style.borderColor = '';
        t.style.boxShadow = '';
      }
    });
  },

  _move(delta) {
    const items = this._filtered();
    if (items.length === 0) return;
    this.selectedIndex = (this.selectedIndex + delta + items.length) % items.length;
    this._highlightSelected();
    // Scroll into view si nécessaire
    const sel = document.querySelector(`[data-app-idx="${this.selectedIndex}"]`);
    if (sel) sel.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  },

  async _activateSelected() {
    const items = this._filtered();
    const a = items[this.selectedIndex];
    if (!a) return;
    if (a.coming_soon) {
      // Petit feedback : on shake la tuile
      const sel = document.querySelector(`[data-app-idx="${this.selectedIndex}"]`);
      if (sel) {
        sel.style.transition = 'transform 80ms ease-in-out';
        sel.style.transform = 'translateX(-4px)';
        setTimeout(() => { sel.style.transform = 'translateX(4px)'; }, 80);
        setTimeout(() => { sel.style.transform = ''; }, 160);
      }
      return;
    }
    if (App.api) {
      try {
        await App.api.launch_app({
          exe_path: a.exe_path || '',
          url:      a.buy_url  || '',
        });
      } catch (e) { console.warn(e); }
      this.close();
    } else if (a.buy_url) {
      // Mode preview standalone (pas de pywebview) : ouvre dans le navigateur
      window.open(a.buy_url, '_blank');
      this.close();
    }
  },

  _esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    }[c]));
  },

  _previewCatalog() {
    return [
      { id:'obelisk', name:'Obelisk', tagline:'Trouve les créateurs vierges de ta niche.', category:'pro', logo:'assets/apps/obelisk.png', price:129 },
      { id:'eliks', name:'Eliks Studio', tagline:'Service growth operator multi-réseaux.', category:'pro', logo:'assets/apps/eliks-studio.svg' },
      { id:'alphacast', name:'AlphaCast', tagline:'Publie une fois, atteins toutes tes audiences.', category:'pro', logo:'assets/apps/alphacast.png', coming_soon:true },
    ];
  },
};

// Init au chargement
window.addEventListener('DOMContentLoaded', () => Launcher.init());
