/* FluxStudio — Studio d'images (génération par IA, modèle FLUX).
 *
 * Jordan décrit une image → FLUX la peint → elle s'affiche, se télécharge,
 * et s'archive dans une galerie. GRATUIT et sans clé : on passe par
 * Pollinations (même méthode que pour illustrer le livre). Backend :
 * endpoints flux_models / flux_generate / flux_history / flux_delete
 * (web/api.py → integrations/flux_studio.py).
 */

const FluxStudio = {
  _s: {
    styles: [],
    formats: [],
    style: '',
    format: '',
    busy: false,
    last: null,          // dernière image affichée {id, prompt, url, data_url…}
    history: [],
  },
  _timer: null,

  // ─────────────── Cycle de vie ───────────────
  async render(container) {
    this._injectStyles();
    this._clearTimer();
    container.innerHTML = `
      <section class="animate-slide-up">
        <div class="mb-6 sm:mb-8">
          <div class="hero-kicker mb-2">STUDIO D’IMAGES</div>
          <h1 class="hero-title hero-title--md mb-2 sm:mb-3">Décris une image, l’IA la crée.</h1>
          <p class="hero-subtitle">
            Visuels pour tes sites, tes pubs, tes démos — générés à la demande, gratuitement.
          </p>
        </div>
        <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div id="flux-form"></div>
          <div id="flux-result"></div>
        </div>
        <div id="flux-gallery" class="mt-8"></div>
      </section>
    `;

    // Charge la config (styles, formats)
    try {
      const cfg = await App.api.flux_models();
      if (cfg && cfg.ok) {
        this._s.styles = cfg.styles || [];
        this._s.formats = cfg.formats || [];
        this._s.style = cfg.default_style || (this._s.styles[0] || {}).id || '';
        this._s.format = cfg.default_format || (this._s.formats[0] || {}).id || '';
      }
    } catch (e) {
      console.warn('[FluxStudio] flux_models', e);
    }

    this._renderForm();
    this._renderResult();
    this._loadHistory();
  },

  // ─────────────── Formulaire ───────────────
  _renderForm() {
    const slot = document.getElementById('flux-form');
    if (!slot) return;
    const esc = this._esc;
    const examples = [
      'Photo lumineuse d’un artisan plombier souriant dans une cuisine moderne, lumière naturelle',
      'Devanture chaleureuse d’un fleuriste au coucher du soleil',
      'Bannière abstraite, dégradé violet et bleu, formes douces, style moderne épuré',
      'Salon de coiffure élégant et lumineux, ambiance accueillante',
    ];

    const styleBtns = this._s.styles.map(s => {
      const active = s.id === this._s.style;
      return `<button type="button" data-flux-style="${esc(s.id)}"
        class="flux-chip ${active ? 'flux-chip--on' : ''}">${esc(s.label)}</button>`;
    }).join('');

    const formatBtns = this._s.formats.map(f => {
      const active = f.id === this._s.format;
      return `<button type="button" data-flux-format="${esc(f.id)}"
        class="flux-chip ${active ? 'flux-chip--on' : ''}">${esc(f.label)}</button>`;
    }).join('');

    const exampleChips = examples.map(x =>
      `<button type="button" class="flux-example" data-flux-example="${esc(x)}">${esc(x)}</button>`
    ).join('');

    slot.innerHTML = `
      <div class="card p-5 sm:p-6">
        <label class="block text-sm font-semibold mb-2">Décris l’image que tu veux</label>
        <textarea id="flux-prompt" rows="4"
          class="w-full px-4 py-3 text-sm rounded-xl bg-bg border border-border
                 focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent resize-y"
          placeholder="Ex. : photo lumineuse d’un menuisier dans son atelier, copeaux de bois, lumière douce…"></textarea>

        <div class="text-[11px] text-text-muted mt-2 mb-1">Quelques idées pour démarrer :</div>
        <div class="flex flex-wrap gap-2 mb-4">${exampleChips}</div>

        <div class="mb-4">
          <div class="text-sm font-semibold mb-2">Style</div>
          <div class="flex flex-wrap gap-2">${styleBtns}</div>
        </div>

        <div class="mb-5">
          <div class="text-sm font-semibold mb-2">Format</div>
          <div class="flex flex-wrap gap-2">${formatBtns}</div>
        </div>

        <button id="flux-go" class="btn btn-primary w-full justify-center py-3 text-base">
          ✨ Générer l’image
        </button>
        <div class="text-[11px] text-text-muted text-center mt-2">
          Gratuit, sans limite. L’image apparaît en quelques secondes.
        </div>
      </div>
    `;

    // Bind
    slot.querySelectorAll('[data-flux-style]').forEach(b => {
      b.onclick = () => { this._s.style = b.dataset.fluxStyle; this._renderForm(); };
    });
    slot.querySelectorAll('[data-flux-format]').forEach(b => {
      b.onclick = () => { this._s.format = b.dataset.fluxFormat; this._renderForm(); };
    });
    slot.querySelectorAll('[data-flux-example]').forEach(b => {
      b.onclick = () => {
        const ta = document.getElementById('flux-prompt');
        if (ta) { ta.value = b.dataset.fluxExample; ta.focus(); }
      };
    });
    const go = document.getElementById('flux-go');
    if (go) go.onclick = () => this._generate();
    const ta = document.getElementById('flux-prompt');
    if (ta) ta.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') this._generate();
    });
  },

  // ─────────────── Génération ───────────────
  async _generate() {
    if (this._s.busy) return;
    const ta = document.getElementById('flux-prompt');
    const prompt = (ta ? ta.value : '').trim();
    if (!prompt) {
      if (window.Toast) Toast.error('Écris d’abord une description.');
      if (ta) ta.focus();
      return;
    }
    this._s.busy = true;
    const go = document.getElementById('flux-go');
    if (go) { go.disabled = true; go.classList.add('opacity-60'); }
    this._renderLoading();

    try {
      const res = await App.api.flux_generate({
        prompt, style: this._s.style, format: this._s.format,
      });
      if (res && res.ok && res.image) {
        this._s.last = res.image;
        this._renderResult();
        if (res.image.url) {
          this._s.history = [res.image, ...this._s.history.filter(h => h.id !== res.image.id)];
          this._renderGallery();
        }
        if (window.Toast) Toast.success('Image générée.');
      } else {
        this._renderError((res && res.error) || 'La génération a échoué.');
      }
    } catch (e) {
      console.warn('[FluxStudio] flux_generate', e);
      this._renderError('Impossible de joindre le serveur. Réessaie.');
    } finally {
      this._s.busy = false;
      this._clearTimer();
      const go2 = document.getElementById('flux-go');
      if (go2) { go2.disabled = false; go2.classList.remove('opacity-60'); }
    }
  },

  _renderLoading() {
    const slot = document.getElementById('flux-result');
    if (!slot) return;
    const started = Date.now();
    slot.innerHTML = `
      <div class="card p-6 flex flex-col items-center justify-center text-center min-h-[280px]">
        <div class="flux-spinner mb-4"></div>
        <div class="font-semibold mb-1">FLUX peint ton image…</div>
        <div class="text-sm text-text-muted">Ça prend en général quelques secondes.</div>
        <div id="flux-elapsed" class="text-xs text-text-muted mt-3">0 s</div>
      </div>
    `;
    this._clearTimer();
    this._timer = setInterval(() => {
      const el = document.getElementById('flux-elapsed');
      if (el) el.textContent = Math.round((Date.now() - started) / 1000) + ' s';
    }, 250);
  },

  _renderResult() {
    const slot = document.getElementById('flux-result');
    if (!slot) return;
    const img = this._s.last;
    if (!img) {
      slot.innerHTML = `
        <div class="card p-6 flex flex-col items-center justify-center text-center min-h-[280px] text-text-muted">
          <div class="text-4xl mb-3">🖼️</div>
          <div class="text-sm" style="text-wrap: pretty">Ton image apparaîtra ici. Décris-la à gauche, puis clique « Générer ».</div>
        </div>`;
      return;
    }
    const esc = this._esc;
    const src = img.data_url || img.url || '';
    slot.innerHTML = `
      <div class="card p-4 sm:p-5">
        <div class="flux-frame mb-3">
          <img src="${esc(src)}" alt="Image générée" class="w-full h-auto rounded-xl block" />
        </div>
        <div class="text-xs text-text-muted mb-3" style="text-wrap: pretty">
          « ${esc(img.prompt || '')} »
          ${img.style_label ? `<span class="opacity-70">· ${esc(img.style_label)}</span>` : ''}
        </div>
        <div class="flex flex-wrap gap-2">
          <button id="flux-dl" class="btn btn-primary">⬇️ Télécharger</button>
          <button id="flux-regen" class="btn btn-secondary">↻ Une autre version</button>
          ${img.url ? `<button id="flux-copy" class="btn btn-secondary">🔗 Copier le lien</button>` : ''}
        </div>
      </div>
    `;
    const dl = document.getElementById('flux-dl');
    if (dl) dl.onclick = () => this._download(img);
    const rg = document.getElementById('flux-regen');
    if (rg) rg.onclick = () => {
      const ta = document.getElementById('flux-prompt');
      if (ta) ta.value = img.prompt || '';
      this._generate();
    };
    const cp = document.getElementById('flux-copy');
    if (cp) cp.onclick = () => this._copy(img.url);
  },

  _renderError(msg) {
    const slot = document.getElementById('flux-result');
    if (!slot) return;
    slot.innerHTML = `
      <div class="card p-6 flex flex-col items-center justify-center text-center min-h-[280px]">
        <div class="text-3xl mb-3">⚠️</div>
        <div class="font-semibold mb-1">Ça n’a pas marché</div>
        <div class="text-sm text-text-muted mb-4" style="text-wrap: pretty">${this._esc(msg)}</div>
        <button id="flux-retry" class="btn btn-secondary">Réessayer</button>
      </div>`;
    const r = document.getElementById('flux-retry');
    if (r) r.onclick = () => this._generate();
  },

  // ─────────────── Galerie (historique) ───────────────
  async _loadHistory() {
    try {
      const res = await App.api.flux_history();
      this._s.history = (res && res.items) || [];
    } catch (e) {
      this._s.history = [];
    }
    this._renderGallery();
  },

  _renderGallery() {
    const slot = document.getElementById('flux-gallery');
    if (!slot) return;
    const items = this._s.history || [];
    if (!items.length) { slot.innerHTML = ''; return; }
    const esc = this._esc;
    slot.innerHTML = `
      <div class="text-sm font-semibold mb-3">Tes dernières images (${items.length})</div>
      <div class="flux-grid">
        ${items.map(it => `
          <figure class="flux-tile" data-flux-open="${esc(it.id)}" title="${esc(it.prompt || '')}">
            <img src="${esc(it.url || it.data_url || '')}" alt="${esc(it.prompt || '')}" loading="lazy" />
            <figcaption>${esc((it.prompt || '').slice(0, 70))}</figcaption>
            <button class="flux-tile-del" data-flux-del="${esc(it.id)}" title="Supprimer">×</button>
          </figure>
        `).join('')}
      </div>
    `;
    slot.querySelectorAll('[data-flux-open]').forEach(el => {
      el.addEventListener('click', (e) => {
        if (e.target.closest('[data-flux-del]')) return;
        const it = items.find(x => x.id === el.dataset.fluxOpen);
        if (it) { this._s.last = it; this._renderResult();
          document.getElementById('flux-result')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); }
      });
    });
    slot.querySelectorAll('[data-flux-del]').forEach(b => {
      b.addEventListener('click', (e) => { e.stopPropagation(); this._delete(b.dataset.fluxDel); });
    });
  },

  async _delete(id) {
    if (!id) return;
    try {
      const res = await App.api.flux_delete({ id });
      this._s.history = (res && res.items) || this._s.history.filter(h => h.id !== id);
      if (this._s.last && this._s.last.id === id) { this._s.last = null; this._renderResult(); }
      this._renderGallery();
      if (window.Toast) Toast.success('Image retirée.');
    } catch (e) {
      if (window.Toast) Toast.friendlyError(e, 'Impossible de retirer cette image.');
    }
  },

  // ─────────────── Téléchargement / copie ───────────────
  async _download(img) {
    const name = `image-${(img.id || 'flux')}.jpg`;
    try {
      let href = img.data_url;
      if (!href && img.url) {
        const r = await fetch(img.url);
        const blob = await r.blob();
        href = URL.createObjectURL(blob);
      }
      if (!href) throw new Error('no source');
      const a = document.createElement('a');
      a.href = href; a.download = name;
      document.body.appendChild(a); a.click(); a.remove();
      if (href.startsWith('blob:')) setTimeout(() => URL.revokeObjectURL(href), 4000);
    } catch (e) {
      if (img.url) window.open(img.url, '_blank');
      else if (window.Toast) Toast.error('Téléchargement impossible.');
    }
  },

  async _copy(url) {
    if (!url) return;
    try {
      await navigator.clipboard.writeText(url);
      if (window.Toast) Toast.success('Lien copié.');
    } catch (e) {
      if (window.Toast) Toast.error('Copie impossible.');
    }
  },

  // ─────────────── Utilitaires ───────────────
  _clearTimer() {
    if (this._timer) { clearInterval(this._timer); this._timer = null; }
  },

  _esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
  },

  _injectStyles() {
    if (document.getElementById('flux-studio-styles')) return;
    const st = document.createElement('style');
    st.id = 'flux-studio-styles';
    st.textContent = `
      .flux-chip {
        padding: 8px 14px; border-radius: 12px; font-size: 13px;
        background: hsl(var(--bg)); border: 1px solid hsl(var(--border));
        color: hsl(var(--text)); transition: all .15s; text-align: left;
      }
      .flux-chip:hover { border-color: hsl(var(--accent) / .5); }
      .flux-chip--on {
        border-color: hsl(var(--accent)); background: hsl(var(--accent) / .1);
        box-shadow: 0 0 0 1px hsl(var(--accent) / .4) inset;
      }
      .flux-example {
        font-size: 11px; padding: 5px 10px; border-radius: 999px;
        background: hsl(var(--surface-elevated)); border: 1px solid hsl(var(--border));
        color: hsl(var(--text-muted)); transition: all .15s; text-align: left;
        max-width: 100%;
      }
      .flux-example:hover { color: hsl(var(--text)); border-color: hsl(var(--accent) / .5); }
      .flux-frame {
        background: repeating-conic-gradient(hsl(var(--border) / .35) 0% 25%, transparent 0% 50%) 50% / 22px 22px;
        border-radius: 14px; overflow: hidden;
      }
      .flux-spinner {
        width: 42px; height: 42px; border-radius: 50%;
        border: 3px solid hsl(var(--border)); border-top-color: hsl(var(--accent));
        animation: flux-spin .8s linear infinite;
      }
      @keyframes flux-spin { to { transform: rotate(360deg); } }
      .flux-grid {
        display: grid; gap: 12px;
        grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
      }
      .flux-tile {
        position: relative; border-radius: 12px; overflow: hidden; cursor: pointer;
        border: 1px solid hsl(var(--border)); background: hsl(var(--bg)); margin: 0;
      }
      .flux-tile img { width: 100%; aspect-ratio: 1 / 1; object-fit: cover; display: block; }
      .flux-tile figcaption {
        position: absolute; left: 0; right: 0; bottom: 0; padding: 6px 8px;
        font-size: 10px; color: #fff; line-height: 1.3;
        background: linear-gradient(transparent, rgba(0,0,0,.78));
        opacity: 0; transition: opacity .15s;
      }
      .flux-tile:hover figcaption { opacity: 1; }
      .flux-tile-del {
        position: absolute; top: 6px; right: 6px; width: 24px; height: 24px;
        border-radius: 999px; background: rgba(0,0,0,.55); color: #fff;
        font-size: 16px; line-height: 1; opacity: 0; transition: opacity .15s;
      }
      .flux-tile:hover .flux-tile-del { opacity: 1; }
      .flux-tile-del:hover { background: hsl(var(--danger, 0 72% 51%)); }
    `;
    document.head.appendChild(st);
  },
};
