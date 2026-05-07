/* Vue Brouillons à valider */

const Drafts = {
  async render(container) {
    container.innerHTML = `
      <section class="animate-slide-up">
        <div class="mb-8">
          <div class="flex items-start justify-between gap-3">
            <div>
              <div class="hero-kicker mb-2">BROUILLONS</div>
              <h1 class="hero-title mb-3" style="font-size: 36px;">Les mails qui attendent ton OK.</h1>
              <p class="hero-subtitle">Préparés par l'app, en mode validation. Tu approuves ou tu rejettes en 1 clic.</p>
            </div>
            ${Help.button('drafts')}
          </div>
          <div class="flex gap-3 mt-6">
            <button id="d-refresh" class="btn btn-secondary">Rafraîchir</button>
          </div>
        </div>
        <div id="d-list" class="space-y-4"></div>
      </section>
    `;
    document.getElementById('d-refresh').onclick = () => this.refresh();
    await this.refresh();
  },

  async refresh() {
    const list = document.getElementById('d-list');
    if (!App.api) {
      list.innerHTML = this._preview();
      return;
    }
    list.innerHTML = `<div class="text-center py-12 text-text-muted">Chargement…</div>`;
    let data;
    try { data = await App.api.get_drafts(); }
    catch (e) {
      list.innerHTML = `<div class="card p-6 text-danger">Erreur : ${e}</div>`;
      return;
    }
    if (!data || !data.ok || !data.rows || data.rows.length === 0) {
      list.innerHTML = `
        <div class="card p-12 text-center">
          <div class="text-4xl mb-3">✓</div>
          <h2 class="text-xl font-semibold mb-2">Tu es à jour.</h2>
          <p class="text-text-secondary max-w-lg mx-auto">
            Aucun brouillon en attente. Quand l'auto-pilote ou les relances en
            prépareront en mode validation, ils atterriront ici.
          </p>
          <button class="btn btn-primary mt-6" onclick="App.show('autopilot')">Lancer une recherche</button>
        </div>
      `;
      return;
    }
    list.innerHTML = data.rows.map((r, i) => this._card(r, i)).join('');
    this._bind(data.rows);
  },

  _card(r, idx) {
    const ts = (r.ts || '').slice(0, 16);
    return `
      <article class="card p-7" data-idx="${idx}" data-key="${this._esc(r.key)}">
        <header class="flex items-start justify-between mb-4 gap-4">
          <div>
            <div class="font-semibold text-base">${this._esc(r.name)}</div>
            <div class="text-sm text-text-muted">${this._esc(r.email)} · ${this._esc(r.city)} · ${ts} · ${this._esc(r.provider)}/${this._esc(r.model)}</div>
          </div>
        </header>
        <div class="text-sm font-semibold text-accent mb-2">OBJET : ${this._esc(r.subject)}</div>
        <textarea data-body
                  class="w-full text-sm leading-relaxed p-4 rounded-xl bg-bg
                         border border-border focus:outline-none
                         focus:ring-2 focus:ring-accent/30 focus:border-accent
                         resize-y min-h-[180px] max-h-[400px]
                         text-text"
                  rows="8">${this._esc(r.body)}</textarea>
        <footer class="flex justify-end gap-2 mt-4 pt-4 border-t border-border">
          <button class="btn btn-secondary" data-act="reject">Rejeter</button>
          <button class="btn btn-primary" data-act="approve">Approuver & envoyer</button>
        </footer>
      </article>
    `;
  },

  _bind(rows) {
    document.querySelectorAll('article[data-idx]').forEach(card => {
      const idx = parseInt(card.dataset.idx, 10);
      const key = card.dataset.key;
      const bodyEl = card.querySelector('[data-body]');
      card.querySelector('[data-act="reject"]').onclick = async () => {
        if (!App.api) return;
        try { await App.api.draft_reject({ key }); }
        catch (e) { console.warn(e); }
        await this.refresh();
      };
      card.querySelector('[data-act="approve"]').onclick = async () => {
        if (!App.api) return;
        const body = bodyEl ? bodyEl.value : rows[idx].body;
        try { await App.api.draft_approve({ key, body }); }
        catch (e) { console.warn(e); }
        await this.refresh();
      };
    });
  },

  _esc(s) {
    return String(s || '').replace(/[&<>"']/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    }[c]));
  },

  _preview() {
    return `
      <div class="card p-12 text-center">
        <div class="text-4xl mb-3">✓</div>
        <h2 class="text-xl font-semibold mb-2">Mode preview</h2>
        <p class="text-text-secondary max-w-md mx-auto">
          Connecte-toi à Supabase pour voir les vrais brouillons.
        </p>
      </div>
    `;
  },
};
