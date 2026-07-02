/* TRI DES SITES À REFAIRE — l'œil de Jordan tranche.
 *
 * La machine ne sait pas juger « ça fait daté » de façon fiable. Ici, on
 * montre à Jordan UNE fiche à la fois avec une CAPTURE propre du site, et il
 * tranche en un clic : 🔴 à refaire / 🟢 non. La suivante est pré-capturée
 * pendant qu'il regarde, pour enchaîner vite.
 *
 * Pool = fiches que l'ancien œil avait flaguées puis relâchées par l'outil
 * objectif (« semble daté mais techniquement OK »).
 * Endpoints : oeil_tri_candidates / oeil_tri_capture / oeil_tri_decide.
 * Raccourcis clavier : R = à refaire, N = non, Espace = passer.
 */
const OeilTri = {
  _queue: [], _reste: 0, _cur: null, _next: null, _busy: false, _last: null,

  esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => (
      { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  },

  async render(container) {
    container.innerHTML = `
      <section class="animate-slide-up">
        <div class="mb-5">
          <div class="hero-kicker mb-2">PROSPECTION</div>
          <h1 class="hero-title hero-title--md mb-2">Tri des sites à refaire.</h1>
          <p class="hero-subtitle">La machine ne sait pas juger « ça fait daté ». Toi si. Regarde, et tranche en un clic.</p>
        </div>
        <div id="ot-progress" class="text-sm text-text-muted mb-3"></div>
        <div id="ot-card"><div class="text-center py-12 text-text-muted">Chargement…</div></div>
      </section>`;
    if (!App.api) {
      document.getElementById('ot-card').innerHTML =
        '<div class="card p-8 text-center text-text-muted">Indisponible.</div>';
      return;
    }
    this._onKey = (e) => {
      // Garde-fous : ne jamais agir si on a quitté l'écran (l'écouteur est
      // retiré par destroy(), mais ceinture ET bretelles), ni si Jordan
      // tape dans un champ de saisie ailleurs (sinon un « r »/« n » tapé
      // dans une recherche enregistrerait une décision en base).
      if (typeof App !== 'undefined' && App.currentView !== 'oeil_tri') return;
      const t = e.target;
      if (t && (t.isContentEditable ||
                /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName || ''))) return;
      if (this._busy) return;
      const k = (e.key || '').toLowerCase();
      if (k === 'backspace' && this._last) { e.preventDefault(); this.undo(); return; }
      if (!this._cur) return;
      if (k === 'r') { e.preventDefault(); this.decide('refaire'); }
      else if (k === 'n') { e.preventDefault(); this.decide('non'); }
      else if (k === ' ') { e.preventDefault(); this.showNext(); }
    };
    document.addEventListener('keydown', this._onKey);
    // Retire l'écouteur quand on quitte la vue (App exécute les cleanups
    // enregistrés au prochain changement d'écran).
    if (typeof App !== 'undefined' && typeof App.onViewCleanup === 'function') {
      App.onViewCleanup(() => this.destroy());
    }
    await this.loadBatch();
    this.showNext();
  },

  // Retire l'écouteur clavier global. Appelé via App.onViewCleanup.
  destroy() { if (this._onKey) document.removeEventListener('keydown', this._onKey); },

  async loadBatch() {
    try {
      const r = await App.api.oeil_tri_candidates({ limit: 20 });
      if (r && r.ok) { this._queue = r.candidates || []; this._reste = r.reste || this._queue.length; }
    } catch (e) { console.error('[OeilTri] load', e); }
  },

  _progress() {
    const el = document.getElementById('ot-progress');
    if (el) el.textContent = this._reste ? `~${this._reste} sites à trier` : '';
  },

  async showNext() {
    if (!this._queue.length) await this.loadBatch();
    this._progress();
    if (!this._queue.length) {
      document.getElementById('ot-card').innerHTML = `
        <div class="card p-10 text-center">
          <div class="text-4xl mb-3">🎉</div>
          <div class="font-semibold mb-1">Tout est trié !</div>
          <div class="text-text-muted text-sm">Plus aucun site en attente de ton avis.</div>
          ${this._last ? `<button id="ot-undo" class="mt-4 text-sm text-text-muted hover:text-text underline">↩ Annuler le dernier choix</button>` : ''}
        </div>`;
      this._cur = null;
      const u = document.getElementById('ot-undo');
      if (u) u.onclick = () => this.undo();
      return;
    }
    this._cur = this._queue.shift();
    this.paintCard(null);                 // squelette + « capture en cours »
    let cap;
    if (this._next && this._next.website === this._cur.website) {
      cap = await this._next.p.catch(() => null);   // pré-capture prête
    } else {
      cap = await App.api.oeil_tri_capture({ website: this._cur.website }).catch(() => null);
    }
    this._next = null;
    this.paintCard(cap || { ok: false, error: 'capture impossible' });
    this.prefetch();
  },

  prefetch() {
    const nxt = this._queue[0];
    if (!nxt || !App.api) return;
    this._next = { website: nxt.website, p: App.api.oeil_tri_capture({ website: nxt.website }) };
  },

  paintCard(cap) {
    const c = this._cur; if (!c) return;
    const sub = [c.metier, c.ville].filter(Boolean).map(x => this.esc(x)).join(' · ');
    const link = this.esc(c.website);
    let visual;
    if (cap == null) {
      visual = `<div class="py-16 text-center text-text-muted">📸 Capture en cours…</div>`;
    } else if (cap.ok && cap.image) {
      visual = `<img src="data:image/png;base64,${cap.image}" alt="aperçu du site"
                     class="w-full rounded-lg border border-border" />`;
    } else {
      // Capture auto impossible (site en JavaScript, images lentes, anti-robot).
      // Un aperçu dégradé tromperait → on montre le VRAI site en direct.
      visual = `
        <div class="px-3 py-2 text-center text-sm text-text-muted">
          📷 Aperçu auto indisponible — voici le site en direct :
          <a href="${link}" target="_blank" rel="noopener" class="text-info hover:underline">ouvrir dans un onglet ↗</a>
        </div>
        <iframe src="${link}" title="site en direct" loading="lazy"
                referrerpolicy="no-referrer" sandbox="allow-scripts allow-same-origin allow-popups"
                style="width:100%;height:520px;border:0;background:#fff"></iframe>`;
    }
    document.getElementById('ot-card').innerHTML = `
      <div class="card p-4 sm:p-6">
        <div class="flex items-baseline justify-between gap-3 mb-1">
          <div class="font-semibold text-lg truncate">${this.esc(c.name) || '(sans nom)'}</div>
        </div>
        ${sub ? `<div class="text-sm text-text-muted mb-1">${sub}</div>` : ''}
        <a href="${link}" target="_blank" rel="noopener" class="text-info hover:underline break-all text-sm">${this.esc(c.website.replace(/^https?:\/\//, ''))}</a>
        <div class="my-4 bg-surface-muted rounded-lg overflow-hidden">${visual}</div>
        <div class="grid grid-cols-3 gap-3">
          <button id="ot-yes" class="btn btn-primary py-3">🔴 À refaire <span class="opacity-60 text-xs">(R)</span></button>
          <button id="ot-no" class="btn btn-secondary py-3">🟢 Il est bien <span class="opacity-60 text-xs">(N)</span></button>
          <button id="ot-skip" class="btn btn-secondary py-3">⏭️ Passer <span class="opacity-60 text-xs">(Espace)</span></button>
        </div>
        ${this._last ? `<div class="mt-3 text-center">
          <button id="ot-undo" class="text-sm text-text-muted hover:text-text underline">↩ Annuler le dernier choix (${this.esc(this._last.fiche.name || 'fiche')})</button>
        </div>` : ''}
      </div>`;
    const y = document.getElementById('ot-yes'), n = document.getElementById('ot-no'), s = document.getElementById('ot-skip');
    if (y) y.onclick = () => this.decide('refaire');
    if (n) n.onclick = () => this.decide('non');
    if (s) s.onclick = () => this.showNext();
    const u = document.getElementById('ot-undo');
    if (u) u.onclick = () => this.undo();
  },

  async decide(verdict) {
    const c = this._cur;
    if (!c || this._busy) return;
    this._busy = true;
    try {
      await App.api.oeil_tri_decide({ website: c.website, verdict });
      this._last = { fiche: c, verdict };
      this._reste = Math.max(0, this._reste - 1);
    } catch (e) { console.error('[OeilTri] decide', e); }
    this._busy = false;
    this.showNext();
  },

  async undo() {
    if (!this._last || this._busy) return;
    this._busy = true;
    const fiche = this._last.fiche;
    try {
      const r = await App.api.oeil_tri_undo({ website: fiche.website });
      if (!r || !r.ok) throw new Error((r && r.error) || 'erreur');
      if (this._cur) this._queue.unshift(this._cur);  // garder la fiche en cours pour après
      this._queue.unshift(fiche);                      // remettre l'annulée en tête
      this._reste += 1;
      this._last = null;
      this._next = null;                               // la pré-capture ne correspond plus
    } catch (e) { console.error('[OeilTri] undo', e); }
    this._busy = false;
    this.showNext();
  },
};
