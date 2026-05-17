/* Vue Projets clients — kanban 4 colonnes */

const Clients = {
  COLUMNS: [
    { key: 'briefing',    label: 'Briefing' },
    { key: 'in_progress', label: 'En cours' },
    { key: 'delivered',   label: 'Livré' },
    { key: 'closed',      label: 'Clôturé' },
  ],

  async render(container) {
    container.innerHTML = `
      <section class="animate-slide-up">
        <div class="mb-6 sm:mb-8 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div class="flex items-start gap-3">
            <div class="min-w-0 flex-1">
              <div class="hero-kicker mb-2">CLIENTS</div>
              <h1 class="hero-title hero-title--md mb-2 sm:mb-3">Tes projets clients en cours.</h1>
              <p class="hero-subtitle">De la commande à la clôture. Tu fais avancer les cartes au fil du travail.</p>
            </div>
            ${Help.button('clients')}
          </div>
          <div class="flex flex-wrap gap-2 sm:gap-3">
            <button id="c-refresh" class="btn btn-secondary">Rafraîchir</button>
            <button id="c-new" class="btn btn-primary">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>
              Nouveau projet
            </button>
          </div>
        </div>
        <div id="c-board" class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-5 min-h-[60vh]"></div>
      </section>
    `;
    document.getElementById('c-refresh').onclick = () => this.refresh();
    document.getElementById('c-new').onclick = () => this._openNew();
    await this.refresh();
  },

  async refresh() {
    const board = document.getElementById('c-board');
    if (!App.api) {
      board.innerHTML = this.COLUMNS.map(col => this._column(col, [])).join('');
      return;
    }
    let data;
    try { data = await App.api.get_clients(); }
    catch (e) {
      board.innerHTML = `<div class="col-span-4 card p-6 text-danger">Erreur : ${e}</div>`;
      return;
    }
    if (!data || !data.ok) {
      board.innerHTML = `
        <div class="col-span-4 card p-10 text-center">
          <div class="text-3xl mb-3">🔌</div>
          <h2 class="text-xl font-semibold mb-2">Connexion requise</h2>
          <p class="text-text-secondary">Connecte-toi à la base partagée Triskell.</p>
        </div>
      `;
      return;
    }
    board.innerHTML = this.COLUMNS.map(col => this._column(col, data.groups[col.key] || [])).join('');
    this._bindCards();
  },

  _column(col, projects) {
    return `
      <div class="card flex flex-col" style="background: hsl(var(--surface) / 0.6);">
        <header class="px-5 pt-5 pb-3 flex items-center justify-between">
          <div class="text-[10px] font-bold tracking-widest text-text-muted">${col.label.toUpperCase()}</div>
          <div class="text-sm font-bold text-accent">${projects.length}</div>
        </header>
        <div class="flex-1 px-3 pb-3 space-y-2 overflow-y-auto">
          ${projects.length === 0
            ? `<div class="text-center py-8 text-text-muted text-sm">—</div>`
            : projects.map(p => this._card(p, col.key)).join('')}
        </div>
      </div>
    `;
  },

  _card(p, status) {
    const idx = this.COLUMNS.findIndex(c => c.key === status);
    const prev = idx > 0 ? this.COLUMNS[idx - 1].key : null;
    const next = idx < this.COLUMNS.length - 1 ? this.COLUMNS[idx + 1].key : null;
    const title = p.title || p.product_name || '(sans titre)';
    const meta = [p.client_name, p.client_company].filter(Boolean).join(' · ');
    const amt = p.amount_cents ? `${Math.round(p.amount_cents / 100)} €` : '';
    const due = p.due_date ? `<div class="text-[11px] text-warning mt-1">Échéance : ${p.due_date}</div>` : '';
    // Bouton "Livrer maintenant" : visible avant que la livraison soit faite,
    // et seulement si le client a un email (sinon le mail welcome ne partira pas)
    const canDeliver = !!p.client_email && (status === 'briefing' || status === 'in_progress');
    const deliverBtn = canDeliver ? `
      <button class="text-[11px] text-success hover:underline" data-deliver
              title="Envoie le mail de bienvenue + livrables (kit du produit)">
        Livrer
      </button>` : '';
    const timelineBtn = p.prospect_id ? `
      <button class="text-[11px] text-text-muted hover:text-accent" data-timeline="${p.prospect_id}"
              title="Voir tout son parcours">
        📋 Parcours
      </button>` : '';
    return `
      <article class="card p-3.5 cursor-pointer transition-all hover:translate-y-[-1px] hover:shadow-soft"
               data-id="${p.id}">
        <div class="font-semibold text-sm mb-1 leading-tight">${this._esc(title)}</div>
        ${meta ? `<div class="text-[11px] text-text-muted">${this._esc(meta)}</div>` : ''}
        ${amt ? `<div class="text-[11px] text-text-muted">${amt}</div>` : ''}
        ${due}
        <div class="flex items-center justify-between mt-3 pt-2 border-t border-border gap-1">
          ${prev ? `<button class="text-text-muted hover:text-accent text-sm w-6 h-6 rounded" data-mv="${prev}">‹</button>` : `<span class="w-6"></span>`}
          <div class="flex-1 flex items-center justify-center gap-3">
            <button class="text-[11px] text-accent hover:underline" data-edit>Édit</button>
            ${deliverBtn}
            ${timelineBtn}
          </div>
          ${next ? `<button class="text-white bg-accent hover:bg-accent-hover text-sm w-6 h-6 rounded" data-mv="${next}">›</button>` : `<span class="w-6"></span>`}
        </div>
      </article>
    `;
  },

  _bindCards() {
    document.querySelectorAll('article[data-id]').forEach(card => {
      const id = card.dataset.id;
      card.querySelectorAll('[data-mv]').forEach(btn => {
        btn.onclick = async (e) => {
          e.stopPropagation();
          if (!App.api) return;
          await App.api.client_transition({ id, status: btn.dataset.mv });
          await this.refresh();
        };
      });
      const editBtn = card.querySelector('[data-edit]');
      if (editBtn) editBtn.onclick = (e) => { e.stopPropagation(); this._openEdit(id); };
      const deliverBtn = card.querySelector('[data-deliver]');
      if (deliverBtn) deliverBtn.onclick = (e) => { e.stopPropagation(); this._deliverNow(id, deliverBtn); };
      const timelineBtn = card.querySelector('[data-timeline]');
      if (timelineBtn) timelineBtn.onclick = (e) => {
        e.stopPropagation();
        const pid = timelineBtn.dataset.timeline;
        if (pid) App.show('prospect_timeline', { id: pid });
      };
    });
  },

  async _deliverNow(id, btn) {
    if (!App.api) return;
    if (!confirm("Envoyer immédiatement le mail de bienvenue + accès livrables à ce client ?\n\n" +
                 "Le contenu vient du « kit de livraison » du produit (modifiable dans Réglages).\n" +
                 "Les relances de suivi (J+3, J+14…) seront ensuite programmées automatiquement.")) {
      return;
    }
    const original = btn.textContent;
    btn.textContent = 'Envoi…';
    btn.disabled = true;
    try {
      const r = await App.api.delivery_trigger_now({ client_project_id: id });
      if (r && r.ok) {
        btn.textContent = 'Livré ✓';
        setTimeout(() => this.refresh(), 1200);
      } else {
        const err = (r && r.error) || 'Erreur inconnue';
        alert('Livraison impossible : ' + err);
        btn.textContent = original;
        btn.disabled = false;
      }
    } catch (e) {
      alert('Erreur : ' + e);
      btn.textContent = original;
      btn.disabled = false;
    }
  },

  _openNew() { this._openDialog(null); },

  async _openEdit(id) {
    if (!App.api) return;
    // Pour la phase 2, on ouvre juste le dialog avec un projet vide ;
    // l'édition complète viendra en phase 3 (besoin de get_client(id))
    this._openDialog({ id });
  },

  _openDialog(existing) {
    const isNew = !existing;
    const overlay = document.createElement('div');
    overlay.className = 'fixed inset-0 z-[100] flex items-center justify-center p-6 transition-opacity duration-200';
    overlay.style.background = 'rgba(15,23,42,0.45)';
    overlay.style.backdropFilter = 'blur(6px)';
    overlay.innerHTML = `
      <div class="bg-surface rounded-3xl shadow-hero w-full max-w-xl overflow-hidden animate-slide-up"
           style="border: 1px solid hsl(var(--border));">
        <div class="px-7 pt-7 pb-3 border-b border-border">
          <div class="hero-kicker mb-1">PROJET CLIENT</div>
          <div class="font-display text-xl font-bold">${isNew ? 'Nouveau projet' : 'Édition'}</div>
        </div>
        <div class="px-7 py-6 space-y-3">
          <input id="cd-title" placeholder="Titre du projet (ex : Site Despiertos Shop)"
                 class="w-full px-4 py-2.5 text-sm rounded-xl bg-bg border border-border
                        focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent" />
          <input id="cd-name" placeholder="Nom du client"
                 class="w-full px-4 py-2.5 text-sm rounded-xl bg-bg border border-border
                        focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent" />
          <input id="cd-email" placeholder="Email du client"
                 class="w-full px-4 py-2.5 text-sm rounded-xl bg-bg border border-border
                        focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent" />
          <input id="cd-amount" placeholder="Montant (€)" type="number"
                 class="w-full px-4 py-2.5 text-sm rounded-xl bg-bg border border-border
                        focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent" />
          <select id="cd-product"
                  class="w-full px-4 py-2.5 text-sm rounded-xl bg-bg border border-border
                         focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent">
            <option value="eliks">Eliks Studio (Growth)</option>
            <option value="triskell-sites">Triskell Studio Sites</option>
            <option value="custom-dev">Dev custom</option>
            <option value="other">Autre</option>
          </select>
          <textarea id="cd-brief" placeholder="Brief / description"
                    class="w-full px-4 py-2.5 text-sm rounded-xl bg-bg border border-border
                           focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent
                           resize-y min-h-[100px]"></textarea>
        </div>
        <div class="px-7 py-4 border-t border-border flex justify-end gap-2">
          <button class="btn btn-secondary" id="cd-cancel">Annuler</button>
          <button class="btn btn-primary" id="cd-save">Enregistrer</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);
    overlay.querySelector('#cd-cancel').onclick = () => overlay.remove();
    overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });
    overlay.querySelector('#cd-save').onclick = async () => {
      if (!App.api) { overlay.remove(); return; }
      const payload = {
        title: overlay.querySelector('#cd-title').value.trim(),
        client_name: overlay.querySelector('#cd-name').value.trim(),
        client_email: overlay.querySelector('#cd-email').value.trim(),
        amount_cents: Math.round(parseFloat(overlay.querySelector('#cd-amount').value || '0') * 100),
        product_key: overlay.querySelector('#cd-product').value,
        product_name: overlay.querySelector('#cd-product').selectedOptions[0].text,
        brief: overlay.querySelector('#cd-brief').value.trim(),
        status: 'briefing',
      };
      try {
        if (isNew) await App.api.client_create(payload);
        else await App.api.client_update({ id: existing.id, patch: payload });
      } catch (e) { console.warn(e); }
      overlay.remove();
      await this.refresh();
    };
  },

  _esc(s) {
    return String(s || '').replace(/[&<>"']/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    }[c]));
  },
};
