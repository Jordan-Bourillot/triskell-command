/* Vue Réponses — l'écran que Jordan ouvre après la Matinale */

const Replies = {
  filter: 'all',
  CATEGORIES: {
    all:          {label: 'Toutes',         color: ''},
    interested:   {label: 'Intéressé',      color: 'success'},
    not_now:      {label: 'Pas maintenant', color: 'warning'},
    no:           {label: 'Refus',          color: 'danger'},
    unsubscribe:  {label: 'Désinscription', color: 'danger'},
    unknown:      {label: 'À trier',        color: ''},
  },

  async render(container) {
    container.innerHTML = `
      <section class="animate-slide-up">
        <div class="mb-6 sm:mb-8">
          <div class="flex items-start justify-between gap-3">
            <div class="min-w-0 flex-1">
              <div class="hero-kicker mb-2">RÉPONSES</div>
              <h1 class="hero-title hero-title--md mb-2 sm:mb-3">Les prospects qui te répondent.</h1>
              <p class="hero-subtitle">Déjà triés, déjà classés. Pas besoin d'ouvrir ta boîte mail.</p>
            </div>
            ${Help.button('replies')}
          </div>
          <div class="flex flex-wrap gap-2 sm:gap-3 mt-5 sm:mt-6 items-center">
            <button id="r-poll" class="btn btn-primary">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M3 12a9 9 0 0114-7.4M21 12a9 9 0 01-14 7.4"/><path d="M21 4v5h-5M3 20v-5h5"/></svg>
              Vérifier maintenant
            </button>
            <button id="r-refresh" class="btn btn-secondary">Rafraîchir</button>
          </div>
        </div>

        <div id="r-filters" class="flex flex-wrap gap-2 mb-5 sm:mb-8"></div>
        <div id="r-list" class="space-y-3 sm:space-y-4"></div>
      </section>
    `;

    document.getElementById('r-refresh').onclick = () => this.refresh();
    document.getElementById('r-poll').onclick = () => this.pollNow();

    this._renderFilters();
    await this.refresh();
  },

  _renderFilters() {
    const wrap = document.getElementById('r-filters');
    if (!wrap) return;
    wrap.innerHTML = Object.entries(this.CATEGORIES).map(([key, info]) => `
      <button data-cat="${key}"
              class="chip ${this.filter === key ? 'active' : ''}"
              style="${this._chipStyle(this.filter === key)}">
        ${info.label}
      </button>
    `).join('');
    wrap.querySelectorAll('[data-cat]').forEach(btn => {
      btn.onclick = () => {
        this.filter = btn.dataset.cat;
        this._renderFilters();
        this.refresh();
      };
    });
  },

  _chipStyle(active) {
    if (active) {
      return `padding: 7px 14px; border-radius: 999px; font-size: 12.5px;
              font-weight: 600; background: hsl(var(--accent));
              color: white; border: 0; cursor: pointer;
              transition: all 160ms;`;
    }
    return `padding: 7px 14px; border-radius: 999px; font-size: 12.5px;
            font-weight: 500; background: transparent;
            color: hsl(var(--text-secondary));
            border: 1px solid hsl(var(--border-strong)); cursor: pointer;
            transition: all 160ms;`;
  },

  async refresh() {
    const list = document.getElementById('r-list');
    if (!App.api) {
      list.innerHTML = this._previewPlaceholder();
      return;
    }
    list.innerHTML = `<div class="text-center py-12 text-text-muted">Chargement…</div>`;
    let data;
    try {
      data = await App.api.get_replies({ category: this.filter });
    } catch (e) {
      list.innerHTML = `<div class="card p-6 text-danger">Erreur : ${e}</div>`;
      return;
    }
    if (!data || !data.ok) {
      list.innerHTML = `
        <div class="card p-6 sm:p-10 text-center">
          <div class="text-3xl mb-3">🔌</div>
          <h2 class="text-xl font-semibold mb-2">Connexion requise</h2>
          <p class="text-text-secondary mb-6">
            Connecte-toi à la base partagée Triskell pour voir les réponses.
          </p>
          <button class="btn btn-primary" onclick="App.show('config')">Aller dans Réglages</button>
        </div>
      `;
      return;
    }
    if (!data.rows || data.rows.length === 0) {
      list.innerHTML = `
        <div class="card p-6 sm:p-12 text-center">
          <div class="text-3xl sm:text-4xl mb-3">✓</div>
          <h2 class="text-xl font-semibold mb-2">Aucune réponse en attente</h2>
          <p class="text-text-secondary max-w-md mx-auto">
            L'app surveille ta boîte mail toutes les 5 minutes et déposera
            ici chaque réponse de prospect, déjà triée. Plus tu envoies,
            plus il y en aura.
          </p>
          <button class="btn btn-secondary mt-6" onclick="App.show('prospection')">Lancer une prospection</button>
        </div>
      `;
      return;
    }
    list.innerHTML = data.rows.map(r => this._card(r, data.prospects[r.prospect_id] || {})).join('');
    this._bindCardActions();
  },

  _card(row, prospect) {
    const extra = row.extra || {};
    const cls = (extra.classification || {});
    const cat = cls.category || 'unknown';
    const conf = cls.confidence || 0;
    const catInfo = this.CATEGORIES[cat] || this.CATEGORIES.unknown;
    const name = prospect.name || prospect.legal_name || '(prospect inconnu)';
    const email = (prospect.emails || [])[0] || extra.from || '';
    const ts = (row.ts || '').slice(0, 19).replace('T', ' ');
    const subject = row.subject || '(sans objet)';
    const body = (extra.body_excerpt || '').slice(0, 500);
    const sug = extra.suggested_reply || null;

    // Sujet de réponse (préfixe Re: si pas déjà présent)
    const replySubject = /^re\s*:/i.test(subject) ? subject : `Re: ${subject}`;
    // Teddy Mail externe retiré : le composer interne fait tout
    // (réponse, mise en forme HTML, pièces jointes, programmation).

    return `
      <article class="card p-4 sm:p-6">
        <header class="flex items-start justify-between mb-3 gap-3">
          <div class="min-w-0">
            <div class="font-semibold text-sm sm:text-base truncate">${this._esc(name)}</div>
            <div class="text-xs sm:text-sm text-text-muted break-all">${this._esc(email)} · ${ts}</div>
          </div>
          <div class="flex items-center gap-2 shrink-0">
            ${conf ? `<span class="text-xs text-text-muted hidden sm:inline">${Math.round(conf*100)}%</span>` : ''}
            <span class="text-[10px] font-bold tracking-widest px-2 py-1 rounded-full whitespace-nowrap
                         ${catInfo.color === 'success' ? 'bg-success/15 text-success' : ''}
                         ${catInfo.color === 'warning' ? 'bg-warning/15 text-warning' : ''}
                         ${catInfo.color === 'danger'  ? 'bg-danger/15 text-danger'  : ''}
                         ${!catInfo.color              ? 'bg-bg text-text-muted'     : ''}">
              ${catInfo.label.toUpperCase()}
            </span>
          </div>
        </header>
        <div class="font-semibold text-[15px] mb-2">${this._esc(subject)}</div>
        ${body ? `<p class="text-sm text-text-secondary leading-relaxed mb-4 whitespace-pre-line">${this._esc(body)}</p>` : ''}
        ${sug && (sug.status === 'pending' || sug.status === 'sent') ? this._suggested(row, sug) : ''}
        <footer class="flex flex-wrap items-center gap-2 mt-4 pt-4 border-t border-border">
          ${row.prospect_id ? `
            <button class="text-xs px-2.5 py-1.5 rounded-lg bg-bg text-text-secondary
                          border border-border hover:bg-surface-elevated transition-colors font-medium"
                    data-act="timeline" data-pid="${row.prospect_id}"
                    title="Voir tout son parcours sur une seule ligne du temps">
              📋 Voir tout son parcours
            </button>` : ''}
          ${cat === 'interested' && !extra.lead_converted_at ? `
            <button class="text-xs px-2.5 py-1.5 rounded-lg bg-success/10 text-success
                          border border-success/30 hover:bg-success/20 transition-colors font-medium"
                    data-act="convert" data-id="${row.id}"
                    title="Crée une carte projet client (statut Briefing) à partir de cette réponse">
              + Créer projet client
            </button>` : ''}
          ${extra.lead_converted_at ? `
            <span class="text-[11px] text-success px-2 py-1">✓ projet créé</span>` : ''}
          <div class="flex-1"></div>
          ${!sug ? `<button class="btn btn-primary" data-act="handle" data-id="${row.id}">Marquer traité</button>` : `<button class="btn btn-secondary" data-act="handle" data-id="${row.id}">Marquer traité</button>`}
        </footer>
      </article>
    `;
  },

  _suggested(row, sug) {
    const status = sug.status;
    const mode = sug.mode || 'manual';
    const modeLabel = (status === 'sent') ? 'envoyé' :
                      (mode === 'manual') ? 'validation manuelle' :
                      (mode === 'instant') ? 'envoi imminent' :
                      this._delayLabel(sug.send_after);
    const modeColor = (status === 'sent') ? 'text-success' :
                      (mode === 'manual') ? 'text-text-muted' : 'text-warning';

    return `
      <div class="rounded-xl p-4 mb-2"
           style="background: hsl(var(--surface-elevated)); border: 1px solid hsl(var(--border));">
        <div class="flex justify-between items-center mb-2">
          <span class="text-[10px] font-bold tracking-widest text-text-muted">RÉPONSE SUGGÉRÉE</span>
          <span class="text-[10px] font-bold tracking-widest ${modeColor}">${modeLabel.toUpperCase()}</span>
        </div>
        <div class="text-sm font-semibold mb-1">${this._esc(sug.subject || '')}</div>
        <p class="text-sm text-text-secondary whitespace-pre-line mb-3">${this._esc((sug.body || '').slice(0, 500))}${(sug.body || '').length > 500 ? '…' : ''}</p>
        ${status === 'pending' ? `
          <div class="flex gap-2">
            <button class="btn btn-secondary" data-act="cancel" data-id="${row.id}">Annuler</button>
            <button class="btn btn-primary" data-act="send" data-id="${row.id}">Envoyer maintenant</button>
          </div>
        ` : ''}
      </div>
    `;
  },

  _delayLabel(sendAfter) {
    if (!sendAfter) return 'auto';
    try {
      const target = new Date(sendAfter);
      const delta = (target - new Date()) / 1000;
      if (delta <= 0) return 'envoi imminent';
      const mins = Math.floor(delta / 60);
      return `auto dans ${mins} min`;
    } catch (e) { return 'auto'; }
  },

  _bindCardActions() {
    document.querySelectorAll('[data-act]').forEach(btn => {
      btn.onclick = async () => {
        const id = btn.dataset.id;
        const act = btn.dataset.act;
        if (act === 'timeline') {
          const pid = btn.dataset.pid;
          if (pid) App.show('prospect_timeline', { id: pid });
          return;
        }
        if (!App.api) return;
        try {
          if (act === 'handle')  await App.api.reply_mark_handled({ id });
          if (act === 'cancel')  await App.api.reply_cancel({ id });
          if (act === 'send') {
            await this._sendReplyDraft(id, false);
            return;
          }
          if (act === 'convert') {
            const original = btn.textContent;
            btn.textContent = 'Création…';
            btn.disabled = true;
            const r = await App.api.reply_convert_to_client({ id });
            if (r && r.ok) {
              btn.textContent = '✓ projet créé';
            } else {
              alert('Création projet impossible : ' + ((r && r.error) || 'erreur'));
              btn.textContent = original;
              btn.disabled = false;
              return;
            }
          }
          await this.refresh();
        } catch (e) { console.warn(e); }
      };
    });
  },

  /**
   * Envoie un brouillon de réponse. Si l'API renvoie des warnings (adresse
   * déjà contactée / déjà client), on affiche une alerte douce au-dessus
   * de la liste avec un bouton "Envoyer quand même".
   */
  async _sendReplyDraft(id, force) {
    try {
      const r = await App.api.reply_send_now({ id, force: !!force });
      if (r && r.ok) {
        this._clearWarningBanner();
        await this.refresh();
        return;
      }
      if (r && r.warnings && r.warnings.length) {
        this._showWarningBanner(r.warnings,
          () => this._sendReplyDraft(id, true));
        return;
      }
      alert('Envoi impossible : ' + ((r && r.error) || 'erreur'));
    } catch (e) {
      console.warn(e);
      alert('Envoi impossible : ' + e);
    }
  },

  _clearWarningBanner() {
    const old = document.getElementById('r-warn-banner');
    if (old) old.remove();
  },

  _showWarningBanner(warnings, onForce) {
    this._clearWarningBanner();
    const list = document.getElementById('r-list');
    if (!list) return;
    const esc = this._esc.bind(this);
    const msgs = (warnings || []).map(w => {
      const addr = w && w.email ? ` (${esc(w.email)})` : '';
      return `<li>${esc(w.message || '')}${addr}</li>`;
    }).join('');
    const banner = document.createElement('div');
    banner.id = 'r-warn-banner';
    banner.className = 'mb-3 p-3 rounded-lg border border-amber-400/40 bg-amber-50 dark:bg-amber-900/20 text-sm';
    banner.innerHTML = `
      <div class="font-semibold text-amber-700 dark:text-amber-300 mb-1">⚠ À vérifier avant d'envoyer</div>
      <ul class="list-disc list-inside text-amber-800 dark:text-amber-200 mb-2">${msgs}</ul>
      <div class="flex gap-2 justify-end">
        <button type="button" data-warn-act="cancel" class="btn btn-secondary btn-sm">Annuler</button>
        <button type="button" data-warn-act="force" class="btn btn-primary btn-sm">Envoyer quand même</button>
      </div>
    `;
    list.insertBefore(banner, list.firstChild);
    banner.scrollIntoView({ behavior: 'smooth', block: 'center' });
    banner.querySelector('[data-warn-act="cancel"]').onclick = () => this._clearWarningBanner();
    banner.querySelector('[data-warn-act="force"]').onclick = () => {
      this._clearWarningBanner();
      if (onForce) onForce();
    };
  },

  async pollNow() {
    if (!App.api) return;
    const list = document.getElementById('r-list');
    list.innerHTML = `<div class="text-center py-12 text-text-muted">Vérification de ta boîte mail…</div>`;
    try {
      await App.api.replies_poll_now();
      await this.refresh();
    } catch (e) { console.warn(e); }
  },

  _esc(s) {
    return String(s || '').replace(/[&<>"']/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    }[c]));
  },

  _previewPlaceholder() {
    return `
      <div class="card p-10 text-center">
        <div class="text-3xl mb-3">📭</div>
        <p class="text-text-secondary">
          Mode preview : connecte-toi à Supabase pour voir les vraies réponses.
        </p>
      </div>
    `;
  },
};
