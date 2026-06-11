/* Vue Projets clients — kanban 4 colonnes */

const Clients = {
  COLUMNS: [
    { key: 'briefing',    label: 'Briefing' },
    { key: 'in_progress', label: 'En cours' },
    { key: 'delivered',   label: 'Livré' },
    { key: 'closed',      label: 'Clôturé' },
  ],

  // Liste de secours si le Catalogue ne répond pas (anciens choix en dur)
  FALLBACK_PRODUCTS: [
    { id: 'eliks',          name: 'Eliks Studio (Growth)' },
    { id: 'triskell-sites', name: 'Triskell Studio Sites' },
    { id: 'custom-dev',     name: 'Développement sur mesure' },
    { id: 'other',          name: 'Autre' },
  ],

  projects: [],     // tous les projets chargés — sert à pré-remplir l'édition
  _products: null,  // produits du catalogue (chargés une fois par visite)

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
      console.error('[Clients] chargement', e);
      board.innerHTML = `
        <div class="col-span-4 card p-10 text-center">
          <div class="text-3xl mb-3">⚠️</div>
          <h2 class="text-xl font-semibold mb-2">Impossible de charger tes projets</h2>
          <p class="text-text-secondary mb-6">Le serveur n'a pas répondu. Vérifie ta connexion, puis réessaie.</p>
          <button id="c-retry" class="btn btn-primary">Réessayer</button>
        </div>
      `;
      const retry = document.getElementById('c-retry');
      if (retry) retry.onclick = () => this.refresh();
      return;
    }
    if (!data || !data.ok) {
      if (data && data.error) console.warn('[Clients] connexion', data.error);
      board.innerHTML = `
        <div class="col-span-4 card p-10 text-center">
          <div class="text-3xl mb-3">🔌</div>
          <h2 class="text-xl font-semibold mb-2">Connexion requise</h2>
          <p class="text-text-secondary mb-6">Connecte-toi à la base partagée Triskell pour voir tes projets.</p>
          <button class="btn btn-primary" onclick="App.show('config', {tab:'account'})">Aller dans Réglages</button>
        </div>
      `;
      return;
    }
    // On garde tous les projets sous la main : c'est ce qui permet de
    // pré-remplir la fenêtre « Modifier » (avant : elle s'ouvrait vide
    // et Enregistrer écrasait la fiche).
    this.projects = Object.values(data.groups || {}).flat();
    board.innerHTML = this.COLUMNS.map(col => this._column(col, data.groups[col.key] || [])).join('');
    this._bindCards();
  },

  _column(col, projects) {
    return `
      <div class="card flex flex-col" style="background: hsl(var(--surface) / 0.6);">
        <header class="px-5 pt-5 pb-3 flex items-center justify-between">
          <div class="text-[11px] font-bold tracking-widest text-text-muted">${col.label.toUpperCase()}</div>
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
    const due = p.due_date ? `<div class="text-[11px] text-warning-text mt-1">Échéance : ${this._esc(p.due_date)}</div>` : '';
    // Bouton "Livrer maintenant" : visible avant que la livraison soit faite,
    // et seulement si le client a un email (sinon le mail de bienvenue ne partira pas)
    const canDeliver = !!p.client_email && (status === 'briefing' || status === 'in_progress');
    const deliverBtn = canDeliver ? `
      <button class="text-[11px] text-success-text hover:underline" data-deliver
              title="Envoie le mail de bienvenue + livrables (kit du produit)">
        Livrer
      </button>` : '';
    const timelineBtn = p.prospect_id ? `
      <button class="text-[11px] text-text-muted hover:text-accent" data-timeline="${p.prospect_id}"
              title="Voir tout son parcours">
        📋 Parcours
      </button>` : '';
    return `
      <article class="card p-3.5 transition-all hover:translate-y-[-1px] hover:shadow-soft"
               data-id="${p.id}">
        <div class="font-semibold text-sm mb-1 leading-tight">${this._esc(title)}</div>
        ${meta ? `<div class="text-[11px] text-text-muted">${this._esc(meta)}</div>` : ''}
        ${amt ? `<div class="text-[11px] text-text-muted">${amt}</div>` : ''}
        ${due}
        <div class="flex items-center justify-between mt-3 pt-2 border-t border-border gap-1">
          ${prev ? `<button class="text-text-muted hover:text-accent text-sm w-6 h-6 rounded" data-mv="${prev}"
                            title="Reculer d'une étape" aria-label="Reculer d'une étape">‹</button>` : `<span class="w-6"></span>`}
          <div class="flex-1 flex items-center justify-center gap-3">
            <button class="text-[11px] text-accent hover:underline" data-edit>Modifier</button>
            ${deliverBtn}
            ${timelineBtn}
            <button class="text-[11px] text-danger-text hover:underline" data-delete title="Supprimer définitivement">Supprimer</button>
          </div>
          ${next ? `<button class="text-sm w-6 h-6 rounded hover:brightness-110" data-mv="${next}"
                            style="background: hsl(var(--accent-strong)); color: hsl(var(--on-accent));"
                            title="Avancer d'une étape" aria-label="Avancer d'une étape">›</button>` : `<span class="w-6"></span>`}
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
          btn.disabled = true;
          try {
            const r = await App.api.client_transition({ id, status: btn.dataset.mv });
            if (!r || !r.ok) {
              Toast.friendlyError(r, 'Impossible de déplacer ce projet. Réessaie dans un instant.');
              btn.disabled = false;
              return;
            }
            await this.refresh();
          } catch (err) {
            Toast.friendlyError(err, 'Impossible de déplacer ce projet. Réessaie dans un instant.');
            btn.disabled = false;
          }
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
      const deleteBtn = card.querySelector('[data-delete]');
      if (deleteBtn) deleteBtn.onclick = async (e) => {
        e.stopPropagation();
        if (!App.api) return;
        const ok = await Dialog.confirm(
          'Supprimer définitivement ce projet ?\nCette action est irréversible.',
          { title: 'Projets clients', okLabel: 'Supprimer', danger: true }
        );
        if (!ok) return;
        deleteBtn.disabled = true;
        try {
          const r = await App.api.client_delete({ id });
          if (r && r.ok) {
            Toast.success('Projet supprimé.');
            await this.refresh();
          } else {
            Toast.friendlyError(r, 'Suppression impossible. Réessaie dans un instant.');
            deleteBtn.disabled = false;
          }
        } catch (err) {
          Toast.friendlyError(err, 'Suppression impossible. Réessaie dans un instant.');
          deleteBtn.disabled = false;
        }
      };
    });
  },

  async _deliverNow(id, btn) {
    if (!App.api) return;
    const ok = await Dialog.confirm(
      'Envoyer immédiatement le mail de bienvenue + accès livrables à ce client ?\n' +
      'Le contenu vient du « kit de livraison » du produit (modifiable dans Réglages).\n' +
      'Les relances de suivi (J+3, J+14…) seront ensuite programmées automatiquement.',
      { title: 'Livraison', okLabel: 'Envoyer' }
    );
    if (!ok) return;
    const original = btn.textContent;
    btn.textContent = 'Envoi…';
    btn.disabled = true;
    try {
      const r = await App.api.delivery_trigger_now({ client_project_id: id });
      if (r && r.ok) {
        btn.textContent = 'Livré ✓';
        Toast.success('Mail de bienvenue envoyé au client.');
        setTimeout(() => this.refresh(), 1200);
      } else {
        Toast.friendlyError(r, 'Livraison impossible. Réessaie dans un instant.');
        btn.textContent = original;
        btn.disabled = false;
      }
    } catch (e) {
      Toast.friendlyError(e, 'Livraison impossible. Réessaie dans un instant.');
      btn.textContent = original;
      btn.disabled = false;
    }
  },

  _openNew() { this._openDialog(null); },

  _openEdit(id) {
    if (!App.api) return;
    // On retrouve le projet dans la liste déjà chargée pour PRÉ-REMPLIR la
    // fenêtre (avant : elle s'ouvrait vide et Enregistrer écrasait la fiche).
    const project = (this.projects || []).find(p => String(p.id) === String(id));
    if (!project) {
      Toast.error('Projet introuvable. La liste va se recharger.');
      this.refresh();
      return;
    }
    this._openDialog(project);
  },

  // Produits proposés dans la fenêtre : ceux du Catalogue, avec la liste
  // de secours en dur si le Catalogue ne répond pas.
  async _loadProducts() {
    if (this._products && this._products.length) return this._products;
    if (App.api) {
      try {
        const r = await App.api.catalog_get_full();
        const products = (r && r.ok && Array.isArray(r.products)) ? r.products : [];
        const cleaned = products
          .filter(p => p && p.id)
          .map(p => ({ id: String(p.id), name: String(p.name || p.id) }));
        if (cleaned.length) {
          this._products = cleaned;
          return this._products;
        }
      } catch (e) {
        console.warn('[Clients] catalogue indisponible, liste de secours utilisée', e);
      }
    }
    this._products = this.FALLBACK_PRODUCTS.slice();
    return this._products;
  },

  async _openDialog(existing) {
    const isNew = !existing;
    const products = (await this._loadProducts()).slice();
    // En édition : si le produit actuel du projet n'est plus au catalogue,
    // on l'ajoute quand même pour ne pas le perdre en enregistrant.
    if (existing && existing.product_key &&
        !products.some(p => p.id === existing.product_key)) {
      products.push({
        id: String(existing.product_key),
        name: String(existing.product_name || existing.product_key),
      });
    }
    const selectedKey = (existing && existing.product_key) || (products[0] && products[0].id) || '';
    const amountValue = (existing && existing.amount_cents)
      ? String(existing.amount_cents / 100) : '';

    const overlay = document.createElement('div');
    overlay.className = 'fixed inset-0 z-[100] flex items-center justify-center p-6 transition-opacity duration-200';
    overlay.style.background = 'hsl(var(--bg) / 0.55)';
    overlay.style.backdropFilter = 'blur(6px)';
    overlay.innerHTML = `
      <div class="bg-surface rounded-3xl shadow-hero w-full max-w-xl overflow-hidden animate-slide-up"
           style="border: 1px solid hsl(var(--border));">
        <div class="px-7 pt-7 pb-3 border-b border-border">
          <div class="hero-kicker mb-1">PROJET CLIENT</div>
          <div class="font-display text-xl font-bold">${isNew ? 'Nouveau projet' : 'Modifier le projet'}</div>
        </div>
        <div class="px-7 py-6 space-y-3">
          <input id="cd-title" placeholder="Titre du projet (ex : Site Despiertos Shop)"
                 value="${this._esc((existing && existing.title) || '')}"
                 class="w-full px-4 py-2.5 text-sm rounded-xl bg-bg border border-border
                        focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent" />
          <input id="cd-name" placeholder="Nom du client"
                 value="${this._esc((existing && existing.client_name) || '')}"
                 class="w-full px-4 py-2.5 text-sm rounded-xl bg-bg border border-border
                        focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent" />
          <input id="cd-email" placeholder="Email du client"
                 value="${this._esc((existing && existing.client_email) || '')}"
                 class="w-full px-4 py-2.5 text-sm rounded-xl bg-bg border border-border
                        focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent" />
          <input id="cd-amount" placeholder="Montant (€)" type="number"
                 value="${this._esc(amountValue)}"
                 class="w-full px-4 py-2.5 text-sm rounded-xl bg-bg border border-border
                        focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent" />
          <select id="cd-product"
                  class="w-full px-4 py-2.5 text-sm rounded-xl bg-bg border border-border
                         focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent">
            ${products.map(p => `
              <option value="${this._esc(p.id)}" ${p.id === selectedKey ? 'selected' : ''}>${this._esc(p.name)}</option>
            `).join('')}
          </select>
          <textarea id="cd-brief" placeholder="Brief / description"
                    class="w-full px-4 py-2.5 text-sm rounded-xl bg-bg border border-border
                           focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent
                           resize-y min-h-[100px]">${this._esc((existing && existing.brief) || '')}</textarea>
        </div>
        <div class="px-7 py-4 border-t border-border flex justify-end gap-2">
          <button class="btn btn-secondary" id="cd-cancel">Annuler</button>
          <button class="btn btn-primary" id="cd-save">Enregistrer</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);

    // Photo des champs à l'ouverture : sert à détecter une saisie en cours
    // avant de fermer (clic à côté / Échap) pour ne JAMAIS perdre du texte.
    const snapshot = () => ['#cd-title', '#cd-name', '#cd-email', '#cd-amount', '#cd-product', '#cd-brief']
      .map(sel => { const el = overlay.querySelector(sel); return el ? el.value : ''; })
      .join(' ');
    const initialSnapshot = snapshot();

    const closeDialog = () => {
      document.removeEventListener('keydown', onEsc);
      overlay.remove();
    };
    const requestClose = async () => {
      if (snapshot() !== initialSnapshot) {
        const ok = await Dialog.confirm(
          'Fermer sans enregistrer ? Ta saisie sera perdue.',
          { title: 'Projet client', okLabel: 'Fermer', danger: true }
        );
        if (!ok) return;
      }
      closeDialog();
    };
    const onEsc = (e) => { if (e.key === 'Escape') requestClose(); };
    document.addEventListener('keydown', onEsc);
    // Si on change d'écran avec la fenêtre ouverte, on la retire proprement
    App.onViewCleanup(() => { if (document.body.contains(overlay)) closeDialog(); });

    overlay.querySelector('#cd-cancel').onclick = () => closeDialog();
    overlay.addEventListener('click', e => { if (e.target === overlay) requestClose(); });

    const saveBtn = overlay.querySelector('#cd-save');
    saveBtn.onclick = async () => {
      if (!App.api) { closeDialog(); return; }
      const val = (sel) => overlay.querySelector(sel).value.trim();
      const productSel = overlay.querySelector('#cd-product');
      const title = val('#cd-title');
      const clientName = val('#cd-name');

      // Validation minimale : il faut au moins un titre OU un nom de client
      if (!title && !clientName) {
        Toast.warn('Indique au moins un titre de projet ou un nom de client.');
        return;
      }

      // On n'envoie QUE les champs remplis. En édition, on ne touche JAMAIS
      // au statut (avant : Enregistrer renvoyait la carte en Briefing).
      const payload = {};
      if (title) payload.title = title;
      if (clientName) payload.client_name = clientName;
      if (val('#cd-email')) payload.client_email = val('#cd-email');
      const amountRaw = val('#cd-amount');
      if (amountRaw !== '') {
        const amount = parseFloat(amountRaw);
        if (!isNaN(amount)) payload.amount_cents = Math.round(amount * 100);
      }
      if (productSel && productSel.value) {
        payload.product_key = productSel.value;
        payload.product_name = productSel.selectedOptions[0]
          ? productSel.selectedOptions[0].text.trim() : productSel.value;
      }
      if (val('#cd-brief')) payload.brief = val('#cd-brief');

      saveBtn.disabled = true;
      const saveLabel = saveBtn.textContent;
      saveBtn.textContent = 'Enregistrement…';
      const fail = (errOrRes) => {
        // Échec → la fenêtre RESTE ouverte, la saisie est conservée
        Toast.friendlyError(errOrRes, 'Enregistrement impossible. Ta saisie est conservée, réessaie.');
        saveBtn.disabled = false;
        saveBtn.textContent = saveLabel;
      };
      try {
        let r;
        if (isNew) r = await App.api.client_create({ ...payload, status: 'briefing' });
        else r = await App.api.client_update({ id: existing.id, patch: payload });
        if (!r || !r.ok) { fail(r); return; }
        Toast.success(isNew ? 'Projet créé.' : 'Projet modifié.');
        closeDialog();
        await this.refresh();
      } catch (e) {
        fail(e);
      }
    };
  },

  _esc(s) {
    return String(s || '').replace(/[&<>"']/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    }[c]));
  },
};
