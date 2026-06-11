/* Triskell Apps Launcher — Spotlight des outils Triskell.
 *
 * Overlay plein écran avec :
 * - Backdrop blur fort
 * - Champ recherche live (autofocus) en haut
 * - Grille immersive de tuiles avec les vrais logos normalisés
 * - Filtre par catégorie
 * - Clic sur une tuile → ouvre la page web de l'outil dans un nouvel onglet
 *
 * Raccourci : Ctrl+O (ou Cmd+O sur Mac) depuis n'importe où — Ctrl+K est
 * réservé à la recherche globale. Échap pour fermer. Bouton « Outils »
 * en bas de la barre latérale.
 */

const Launcher = {
  apps: null,        // null = catalogue pas encore chargé
  loadError: false,  // échec du dernier chargement (bouton Réessayer)
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
    // Raccourci global Ctrl+O / Cmd+O (Ctrl+K appartient à la recherche globale)
    window.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && !e.shiftKey && !e.altKey
          && e.key.toLowerCase() === 'o') {
        e.preventDefault();
        this.toggle();
      }
      if (this.isOpen) {
        // Dans le champ de recherche, ←/→ servent à déplacer le curseur :
        // on ne les détourne pas. ↑/↓ restent pour la grille (saut de ligne).
        const ae = document.activeElement;
        const inField = !!(ae && ae.id === 'launcher-search');
        if (e.key === 'Escape') {
          e.preventDefault();
          this.close();
        }
        if (e.key === 'ArrowRight' && !inField) {
          e.preventDefault();
          this._move(1);
        }
        if (e.key === 'ArrowLeft' && !inField) {
          e.preventDefault();
          this._move(-1);
        }
        if (e.key === 'ArrowDown') {
          e.preventDefault();
          this._move(4); // une ligne de grille plus bas
        }
        if (e.key === 'ArrowUp') {
          e.preventDefault();
          this._move(-4); // une ligne de grille plus haut
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
    // L'overlay s'affiche TOUT DE SUITE (avec un indicateur de chargement),
    // l'appel réseau se fait après — sur connexion lente, Ctrl+O répond
    // donc instantanément au lieu de sembler mort.
    this.apps = null;       // null = chargement en cours
    this.loadError = false;
    this._render();
    await this._load();
  },

  async _load() {
    if (!App.api) {
      this.apps = this._previewCatalog();
      this.loadError = false;
      if (this.isOpen) this._renderGrid();
      return;
    }
    this.apps = null;
    this.loadError = false;
    try {
      const data = await App.api.get_apps_catalog();
      if (data && data.ok) {
        this.apps = data.apps || [];
      } else {
        if (data && data.error) console.warn('[launcher] catalogue :', data.error);
        this.loadError = true;
      }
    } catch (e) {
      console.warn('[launcher] catalogue :', e);
      this.loadError = true;
    }
    if (this.isOpen) this._renderGrid();
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
                        px-2 py-1 rounded-md border border-border">Échap</kbd>
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
          <div class="flex items-center gap-4">
            <span><kbd class="text-[10px] font-bold bg-bg px-1.5 py-0.5 rounded border border-border">Ctrl O</kbd> fermer</span>
            <span><kbd class="text-[10px] font-bold bg-bg px-1.5 py-0.5 rounded border border-border">Échap</kbd> fermer</span>
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

    // Chargement en cours (apps pas encore arrivées)
    if (this.apps === null && !this.loadError) {
      grid.innerHTML = `
        <div class="text-center py-16 text-text-muted">
          <span class="inline-block w-8 h-8 rounded-full border-[3px] border-accent/30 border-t-accent animate-spin mb-3"></span>
          <div class="text-sm">Chargement des outils…</div>
        </div>
      `;
      return;
    }

    // Échec de chargement : on le DIT (avant : faux « aucun outil »)
    if (this.loadError) {
      grid.innerHTML = `
        <div class="text-center py-16 text-text-muted">
          <div class="text-4xl mb-3 opacity-50">⚠</div>
          <div class="text-sm mb-4">Impossible de charger la liste des outils.</div>
          <button data-launcher-retry class="btn btn-secondary">Réessayer</button>
        </div>
      `;
      const retry = grid.querySelector('[data-launcher-retry]');
      if (retry) retry.onclick = () => { this._renderGridLoading(); this._load(); };
      return;
    }

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
    // Logo introuvable → lettre de secours (au lieu d'une icône cassée)
    grid.querySelectorAll('img[data-fallback-letter]').forEach(img => {
      img.onerror = () => {
        const span = document.createElement('span');
        span.className = 'w-14 h-14 rounded-xl shrink-0 inline-flex items-center '
                       + 'justify-center text-xl font-bold bg-accent/15 text-accent';
        span.textContent = img.dataset.fallbackLetter || '?';
        img.replaceWith(span);
      };
    });
    this._highlightSelected();
  },

  _renderGridLoading() {
    this.apps = null;
    this.loadError = false;
    this._renderGrid();
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
               data-fallback-letter="${this._esc(((a.name || '?').trim()[0] || '?').toUpperCase())}"
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
    let next = this.selectedIndex + delta;
    if (Math.abs(delta) === 1) {
      // ←/→ : on boucle d'un bout à l'autre
      next = (next + items.length) % items.length;
    } else {
      // ↑/↓ (saut de ligne) : on borne aux extrémités
      next = Math.max(0, Math.min(items.length - 1, next));
    }
    this.selectedIndex = next;
    this._highlightSelected();
    // Scroll into view si nécessaire
    const sel = document.querySelector(`[data-app-idx="${this.selectedIndex}"]`);
    if (sel) sel.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  },

  // La première page web disponible pour un outil du catalogue :
  // page d'achat, puis page du service, puis premier lien web de la fiche.
  _appUrl(a) {
    if (!a) return '';
    if (a.buy_url) return a.buy_url;
    if (a.service && a.service.url) return a.service.url;
    for (const l of (a.links || [])) {
      if (l && l.url && /^https?:\/\//i.test(l.url)) return l.url;
    }
    return '';
  },

  _activateSelected() {
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
    // Version web : on ouvre la page de l'outil DANS LE NAVIGATEUR de
    // l'utilisateur. (Avant : launch_app côté serveur → la page s'ouvrait
    // sur le serveur Linux, donc nulle part.)
    const url = this._appUrl(a);
    if (!url) {
      Toast.info('Cet outil n’a pas de page web.');
      return;
    }
    window.open(url, '_blank', 'noopener');
    this.close();
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
