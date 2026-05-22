/* Vue Brouillons à valider */

const Drafts = {
  async render(container) {
    container.innerHTML = `
      <section class="animate-slide-up">
        <div class="mb-6 sm:mb-8">
          <div class="flex items-start justify-between gap-3">
            <div class="min-w-0 flex-1">
              <div class="hero-kicker mb-2">BROUILLONS</div>
              <h1 class="hero-title hero-title--md mb-2 sm:mb-3">Les mails qui attendent ton OK.</h1>
              <p class="hero-subtitle">Préparés par l'app, en mode validation. Tu approuves ou tu rejettes en 1 clic.</p>
            </div>
            ${Help.button('drafts')}
          </div>
          <div class="flex flex-wrap gap-2 sm:gap-3 mt-5 sm:mt-6">
            <button id="d-refresh" class="btn btn-secondary">Rafraîchir</button>
            <button id="d-cleanup" class="btn btn-secondary" title="Supprime les brouillons en attente qui n'ont jamais reçu de contenu (coquilles vides)">Vider les coquilles vides</button>
            <button id="d-cleanup-broken" class="btn btn-secondary"
                    title="Supprime les brouillons où l'IA a refusé d'écrire (méta-blabla au lieu d'un mail).">
              Vider les cassés
            </button>
            <button id="d-wipe-all" class="btn btn-secondary"
                    style="border-color: hsl(var(--danger) / 0.5); color: hsl(var(--danger));"
                    title="Supprime TOUS les brouillons en attente (les bons comme les mauvais). Reset complet.">
              Tout vider
            </button>
          </div>
        </div>
        <div id="d-list" class="space-y-3 sm:space-y-4"></div>
      </section>
    `;
    document.getElementById('d-refresh').onclick = () => this.refresh();
    document.getElementById('d-cleanup').onclick = () => this._cleanup();
    document.getElementById('d-cleanup-broken').onclick = () => this._cleanupBroken();
    document.getElementById('d-wipe-all').onclick = () => this._wipeAll();
    await this.refresh();
  },

  async _cleanupBroken() {
    if (!App.api || !App.api.cleanup_broken_drafts) return;
    const ok = confirm(
      "Supprimer tous les brouillons où l'IA a refusé d'écrire "
      + "(« Je ne peux pas rédiger… », « PROBLÈME MAJEUR… ») ?\n\n"
      + "Les vrais brouillons ne sont pas touchés."
    );
    if (!ok) return;
    const btn = document.getElementById('d-cleanup-broken');
    if (btn) { btn.disabled = true; btn.textContent = 'Nettoyage…'; }
    let res;
    try { res = await App.api.cleanup_broken_drafts(); }
    catch (e) { alert('Erreur : ' + e); }
    finally {
      if (btn) { btn.disabled = false; btn.textContent = 'Vider les cassés'; }
    }
    if (res && res.ok) alert(`${res.total} brouillon(s) cassé(s) supprimé(s).`);
    else if (res) alert('Nettoyage partiel. Erreurs : ' + (res.errors || []).join(' ; '));
    await this.refresh();
  },

  async _wipeAll() {
    if (!App.api || !App.api.cleanup_all_pending_drafts) return;
    const ok = confirm(
      "ATTENTION : ça supprime TOUS les brouillons en attente "
      + "(les bons comme les mauvais).\n\nContinuer ?"
    );
    if (!ok) return;
    const btn = document.getElementById('d-wipe-all');
    if (btn) { btn.disabled = true; btn.textContent = 'Reset…'; }
    let res;
    try { res = await App.api.cleanup_all_pending_drafts(); }
    catch (e) { alert('Erreur : ' + e); }
    finally {
      if (btn) { btn.disabled = false; btn.textContent = 'Tout vider'; }
    }
    if (res && res.ok) alert(`${res.total} brouillon(s) supprimé(s).`);
    else if (res) alert('Reset partiel. Erreurs : ' + (res.errors || []).join(' ; '));
    await this.refresh();
  },

  async _cleanup() {
    if (!App.api) return;
    const ok = confirm(
      "Supprimer tous les brouillons en attente qui n’ont jamais reçu " +
      "de contenu (coquilles vides) ?\n\n" +
      "Les vrais brouillons (avec texte) ne sont pas touchés. " +
      "Les prospects ne sont pas supprimés non plus."
    );
    if (!ok) return;
    const btn = document.getElementById('d-cleanup');
    if (btn) { btn.disabled = true; btn.textContent = 'Nettoyage…'; }
    let res;
    try { res = await App.api.cleanup_empty_drafts({}); }
    catch (e) { alert('Erreur : ' + e); }
    finally {
      if (btn) { btn.disabled = false; btn.textContent = 'Vider les coquilles vides'; }
    }
    if (res && res.ok) {
      alert(`${res.total} coquille(s) vide(s) supprimée(s).`);
    } else if (res) {
      alert('Nettoyage partiel. Erreurs : ' + (res.errors || []).join(' ; '));
    }
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
        <div class="card p-6 sm:p-12 text-center">
          <div class="text-3xl sm:text-4xl mb-3">✓</div>
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
    const banner = data.truncated
      ? `<div class="card p-3 sm:p-4 mb-3 text-sm text-text-muted">
            On affiche les ${data.rows.length} brouillons les plus récents
            (limite ${data.limit_per_source || 200} par source).
            Approuve ou rejette pour faire descendre la file.
          </div>`
      : '';
    list.innerHTML = banner + data.rows.map((r, i) => this._card(r, i)).join('');
    this._bind(data.rows);
  },

  _card(r, idx) {
    const ts = (r.ts || '').slice(0, 16);
    const meta = [];
    if (r.email) meta.push(this._esc(r.email));
    if (r.city)  meta.push(this._esc(r.city));
    if (ts)      meta.push(ts);
    if (r.provider || r.model) {
      meta.push(`${this._esc(r.provider)}/${this._esc(r.model)}`);
    }
    let badge = '';
    if (r.source === 'convoy') {
      const camp = r.campaign_name || r.offer_name || 'Convoi';
      badge = `<span class="text-xs px-2 py-0.5 rounded-full bg-accent/15 text-accent">${this._esc(camp)}</span>`;
    } else if (r.kind && r.kind !== 'first_contact') {
      badge = `<span class="text-xs px-2 py-0.5 rounded-full bg-bg border border-border text-text-muted">${this._esc(r.kind)}</span>`;
    }
    const testBadge = r.is_test
      ? `<span class="text-xs px-2 py-0.5 rounded-full bg-warning/20 text-warning ml-1">test</span>`
      : '';
    return `
      <article class="card p-4 sm:p-7"
               data-idx="${idx}"
               data-id="${this._esc(r.id || r.key)}"
               data-source="${this._esc(r.source || '')}">
        <header class="flex items-start justify-between mb-3 sm:mb-4 gap-3">
          <div class="min-w-0">
            <div class="font-semibold text-base truncate">${this._esc(r.name)} ${badge}${testBadge}</div>
            <div class="text-xs sm:text-sm text-text-muted break-all">${meta.join(' · ')}</div>
          </div>
        </header>
        <div class="text-sm font-semibold text-accent mb-2 break-words">OBJET : ${this._esc(r.subject)}</div>
        <textarea data-body
                  class="w-full text-sm leading-relaxed p-3 sm:p-4 rounded-xl bg-bg
                         border border-border focus:outline-none
                         focus:ring-2 focus:ring-accent/30 focus:border-accent
                         resize-y min-h-[160px] sm:min-h-[180px] max-h-[400px]
                         text-text"
                  rows="8">${this._esc(r.body)}</textarea>
        <footer class="flex flex-col sm:flex-row sm:justify-end gap-2 mt-4 pt-4 border-t border-border">
          <button class="btn btn-secondary justify-center" data-act="reject">Rejeter</button>
          <button class="btn btn-primary justify-center" data-act="approve">${r.source === 'convoy' ? 'Approuver (mise en file)' : 'Approuver &amp; envoyer'}</button>
        </footer>
      </article>
    `;
  },

  _bind(rows) {
    document.querySelectorAll('article[data-idx]').forEach(card => {
      const idx = parseInt(card.dataset.idx, 10);
      const id = card.dataset.id;
      const source = card.dataset.source || '';
      const bodyEl = card.querySelector('[data-body]');
      const setBusy = (busy) => {
        card.querySelectorAll('button').forEach(b => b.disabled = busy);
        card.style.opacity = busy ? '0.6' : '1';
      };
      card.querySelector('[data-act="reject"]').onclick = async () => {
        if (!App.api) return;
        setBusy(true);
        try {
          const r = await App.api.draft_reject({ id, source, key: id });
          if (r && r.ok === false) alert('Rejet KO : ' + (r.error || '?'));
        } catch (e) { console.warn(e); }
        await this.refresh();
      };
      card.querySelector('[data-act="approve"]').onclick = async () => {
        if (!App.api) return;
        const body = bodyEl ? bodyEl.value : rows[idx].body;
        setBusy(true);
        try {
          const r = await App.api.draft_approve({ id, source, key: id, body });
          if (r && r.ok === false) alert('Envoi KO : ' + (r.error || '?'));
        } catch (e) { console.warn(e); }
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
