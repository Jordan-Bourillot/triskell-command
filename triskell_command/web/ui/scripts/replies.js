/* Vue Réponses — l'écran que Jordan ouvre après la Matinale */

const Replies = {
  filter: 'all',
  // Données du dernier chargement (toutes catégories confondues) : permet
  // les compteurs sur les filtres et le filtrage sans rappeler le serveur.
  _allRows: null,
  _prospects: null,
  _counts: null,
  CATEGORIES: {
    all:          {label: 'Toutes',         color: ''},
    interested:   {label: 'Intéressé',      color: 'success'},
    not_now:      {label: 'Pas maintenant', color: 'warning'},
    no:           {label: 'Refus',          color: 'danger'},
    unsubscribe:  {label: 'Désinscription', color: 'danger'},
    unknown:      {label: 'À trier',        color: '',
                   tip: 'Réponses que l’IA n’a pas su classer toutes seules'},
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
            ${typeof Help !== 'undefined' ? Help.button('replies') : ''}
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
    const counts = this._counts || {};
    wrap.innerHTML = Object.entries(this.CATEGORIES).map(([key, info]) => {
      const active = this.filter === key;
      const n = counts[key] || 0;
      const skin = active
        ? 'font-semibold bg-accent-strong text-white border border-transparent'
        : 'font-medium bg-transparent text-text-secondary border border-border-strong';
      return `
        <button data-cat="${key}"
                class="px-3.5 py-1.5 rounded-full text-xs cursor-pointer transition-all ${skin}"
                ${info.tip ? `title="${this._esc(info.tip)}"` : ''}>
          ${info.label}${n ? ` (${n})` : ''}
        </button>`;
    }).join('');
    wrap.querySelectorAll('[data-cat]').forEach(btn => {
      btn.onclick = () => {
        this.filter = btn.dataset.cat;
        this._renderFilters();
        this._renderList();
      };
    });
  },

  async refresh() {
    const list = document.getElementById('r-list');
    if (!list) return;
    if (!App.api) {
      list.innerHTML = this._previewPlaceholder();
      return;
    }
    list.innerHTML = `<div class="text-center py-12 text-text-muted">Chargement…</div>`;
    let data;
    try {
      // On charge TOUTES les catégories d'un coup : ça permet d'afficher
      // les compteurs sur les filtres et de filtrer sans nouvel appel.
      data = await App.api.get_replies({ category: 'all' });
    } catch (e) {
      console.warn('get_replies KO', e);
      Toast.friendlyError(e, 'Impossible de charger les réponses.');
      list.innerHTML = this._loadErrorBlock();
      return;
    }
    if (!data || !data.ok) {
      if (data && data.error && data.error !== 'not_connected') {
        console.warn('get_replies refus :', data.error);
        list.innerHTML = this._loadErrorBlock();
        return;
      }
      list.innerHTML = `
        <div class="card p-6 sm:p-10 text-center">
          <div class="text-3xl mb-3">🔌</div>
          <h2 class="text-xl font-semibold mb-2">Connexion requise</h2>
          <p class="text-text-secondary mb-6">
            Connecte-toi à la base partagée Triskell pour voir les réponses.
          </p>
          <button class="btn btn-primary" onclick="App.show('config', {tab:'mails'})">Aller dans Réglages</button>
        </div>
      `;
      return;
    }
    this._allRows = data.rows || [];
    this._prospects = data.prospects || {};
    // Compteurs par catégorie pour les filtres.
    const counts = { all: this._allRows.length };
    this._allRows.forEach(r => {
      const cat = (((r.extra || {}).classification) || {}).category || 'unknown';
      counts[cat] = (counts[cat] || 0) + 1;
    });
    this._counts = counts;
    this._renderFilters();
    this._renderList();
  },

  _loadErrorBlock() {
    return `
      <div class="card p-6 text-center">
        <p class="text-text-secondary mb-4">
          Impossible de charger les réponses. Vérifie ta connexion, puis réessaie.
        </p>
        <button class="btn btn-secondary" onclick="Replies.refresh()">Réessayer</button>
      </div>`;
  },

  // Affiche les cartes du filtre courant à partir des données déjà chargées.
  _renderList() {
    const list = document.getElementById('r-list');
    if (!list) return;
    const all = this._allRows || [];
    const prospects = this._prospects || {};
    const rows = this.filter === 'all'
      ? all
      : all.filter(r =>
          (((r.extra || {}).classification || {}).category || 'unknown') === this.filter);
    if (rows.length === 0) {
      if (this.filter !== 'all' && all.length > 0) {
        const info = this.CATEGORIES[this.filter] || {};
        list.innerHTML = `
          <div class="card p-6 sm:p-10 text-center">
            <div class="text-3xl mb-3">✓</div>
            <h2 class="text-lg font-semibold mb-2">Rien dans « ${this._esc(info.label || '')} » pour l’instant</h2>
            <p class="text-text-secondary">Les autres réponses t’attendent dans les autres filtres.</p>
            <button class="btn btn-secondary mt-5" data-show-all>Voir toutes les réponses</button>
          </div>`;
        const b = list.querySelector('[data-show-all]');
        if (b) b.onclick = () => {
          this.filter = 'all';
          this._renderFilters();
          this._renderList();
        };
        return;
      }
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
    list.innerHTML = rows.map(r => this._card(r, prospects[r.prospect_id] || {})).join('');
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
    const body = extra.body_excerpt || '';
    const sug = extra.suggested_reply || null;

    // Sujet de réponse (préfixe Re: si pas déjà présent) — sert au bouton
    // « Répondre » qui ouvre le composeur interne pré-rempli.
    const replySubject = /^re\s*:/i.test(subject) ? subject : `Re: ${subject}`;

    return `
      <article class="card p-4 sm:p-6">
        <header class="flex items-start justify-between mb-3 gap-3">
          <div class="min-w-0">
            <div class="font-semibold text-sm sm:text-base truncate">${this._esc(name)}</div>
            <div class="text-xs sm:text-sm text-text-muted break-all">${this._esc(email)} · ${ts}</div>
          </div>
          <div class="flex items-center gap-2 shrink-0">
            ${conf ? `<span class="text-xs text-text-muted hidden sm:inline"
                            title="Confiance de l’IA dans ce classement">${Math.round(conf*100)}%</span>` : ''}
            <span class="text-[11px] font-bold tracking-widest px-2 py-1 rounded-full whitespace-nowrap
                         ${catInfo.color === 'success' ? 'bg-success/15 text-success' : ''}
                         ${catInfo.color === 'warning' ? 'bg-warning/15 text-warning' : ''}
                         ${catInfo.color === 'danger'  ? 'bg-danger/15 text-danger'  : ''}
                         ${!catInfo.color              ? 'bg-bg text-text-muted'     : ''}">
              ${catInfo.label.toUpperCase()}
            </span>
          </div>
        </header>
        <div class="font-semibold text-[15px] mb-2">${this._esc(subject)}</div>
        ${body ? this._expandable(body, 'text-sm text-text-secondary leading-relaxed whitespace-pre-line', 'mb-4') : ''}
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
          <button class="btn btn-secondary" data-act="reply"
                  data-to="${this._esc(email)}" data-subj="${this._esc(replySubject)}"
                  ${email ? '' : 'disabled'}
                  title="${email
                    ? 'Écrire une réponse — ouvre le composeur de mails pré-rempli'
                    : 'Adresse mail introuvable pour ce prospect'}">
            ✉️ Répondre
          </button>
          ${!sug ? `<button class="btn btn-primary" data-act="handle" data-id="${row.id}">Marquer traité</button>` : `<button class="btn btn-secondary" data-act="handle" data-id="${row.id}">Marquer traité</button>`}
        </footer>
      </article>
    `;
  },

  // Texte long : montre les 500 premiers caractères + « Voir la suite » qui
  // déplie le texte complet (déjà présent dans la réponse du serveur).
  _expandable(text, pClass, wrapClass) {
    const full = String(text || '');
    if (full.length <= 500) {
      return `<div class="${wrapClass}"><p class="${pClass}">${this._esc(full)}</p></div>`;
    }
    const short = full.slice(0, 500);
    return `
      <div class="${wrapClass}" data-expandable>
        <p class="${pClass}"><span data-text-short>${this._esc(short)}…</span><span data-text-full class="hidden">${this._esc(full)}</span></p>
        <button type="button" data-expand
                class="text-xs font-medium text-accent-text hover:underline mt-1">
          Voir la suite
        </button>
      </div>`;
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
          <span class="text-[11px] font-bold tracking-widest text-text-muted">RÉPONSE SUGGÉRÉE</span>
          <span class="text-[11px] font-bold tracking-widest ${modeColor}">${modeLabel.toUpperCase()}</span>
        </div>
        <div class="text-sm font-semibold mb-1">${this._esc(sug.subject || '')}</div>
        ${this._expandable(sug.body || '', 'text-sm text-text-secondary whitespace-pre-line', 'mb-3')}
        ${status === 'pending' ? `
          <div class="flex gap-2">
            <button class="btn btn-secondary" data-act="cancel" data-id="${row.id}"
                    title="Abandonner cette suggestion : rien ne sera envoyé">Annuler</button>
            <button class="btn btn-primary" data-act="send" data-id="${row.id}"
                    title="Envoyer cette réponse tout de suite">Envoyer maintenant</button>
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
    // Boutons « Voir la suite » des textes tronqués.
    document.querySelectorAll('#r-list [data-expand]').forEach(b => {
      b.onclick = () => {
        const box = b.closest('[data-expandable]');
        if (!box) return;
        const s = box.querySelector('[data-text-short]');
        const f = box.querySelector('[data-text-full]');
        if (s) s.classList.add('hidden');
        if (f) f.classList.remove('hidden');
        b.remove();
      };
    });

    document.querySelectorAll('#r-list [data-act]').forEach(btn => {
      btn.onclick = async () => {
        const id = btn.dataset.id;
        const act = btn.dataset.act;
        if (act === 'timeline') {
          const pid = btn.dataset.pid;
          if (pid) App.show('prospect_timeline', { id: pid });
          return;
        }
        if (act === 'reply') {
          // Ouvre le composeur interne pré-rempli (destinataire + objet).
          // On passe par l'écran Mails, puis on ouvre la fenêtre d'écriture
          // une fois l'écran affiché.
          const to = btn.dataset.to || '';
          const subj = btn.dataset.subj || '';
          App.show('mails');
          App.viewTimeout(() => {
            if (typeof Mails !== 'undefined' && Mails._openComposer) {
              Mails._openComposer({
                prefilledTo: to,
                prefilledSubject: subj,
                title: 'Répondre',
              });
            }
          }, 250);
          return;
        }
        if (!App.api) {
          Toast.error('Fonction indisponible — rafraîchis la page.');
          return;
        }
        if (act === 'handle') {
          const ok = await Dialog.confirm(
            'Marquer cette réponse comme traitée ? Elle disparaîtra de cette liste.',
            { title: 'Marquer traité', okLabel: 'Marquer traité', cancelLabel: 'Annuler' }
          );
          if (!ok) return;
          const original = btn.textContent;
          btn.disabled = true;
          btn.textContent = 'Un instant…';
          try {
            await App.api.reply_mark_handled({ id });
            Toast.success('Réponse marquée traitée.');
            await this.refresh();
          } catch (e) {
            Toast.friendlyError(e, 'Impossible de marquer cette réponse.');
            btn.disabled = false;
            btn.textContent = original;
          }
          return;
        }
        if (act === 'cancel') {
          const ok = await Dialog.confirm(
            'Annuler cette réponse suggérée ? Elle ne sera pas envoyée.',
            { title: 'Annuler la suggestion', okLabel: 'Ne pas envoyer', cancelLabel: 'Garder' }
          );
          if (!ok) return;
          const original = btn.textContent;
          btn.disabled = true;
          btn.textContent = 'Annulation…';
          try {
            await App.api.reply_cancel({ id });
            Toast.success('Suggestion annulée — rien ne partira.');
            await this.refresh();
          } catch (e) {
            Toast.friendlyError(e, 'Annulation impossible pour le moment.');
            btn.disabled = false;
            btn.textContent = original;
          }
          return;
        }
        if (act === 'send') {
          await this._sendReplyDraft(id, false, btn);
          return;
        }
        if (act === 'convert') {
          const original = btn.textContent;
          btn.textContent = 'Création…';
          btn.disabled = true;
          let r;
          try { r = await App.api.reply_convert_to_client({ id }); }
          catch (e) {
            Toast.friendlyError(e, 'Création du projet impossible.');
            btn.textContent = original;
            btn.disabled = false;
            return;
          }
          if (r && r.ok) {
            btn.textContent = '✓ projet créé';
            Toast.success('Projet client créé.');
            await this.refresh();
          } else {
            Toast.error('Création du projet impossible : ' + ((r && r.error) || 'erreur inconnue'));
            btn.textContent = original;
            btn.disabled = false;
          }
        }
      };
    });
  },

  /**
   * Envoie un brouillon de réponse. Si l'API renvoie des avertissements
   * (adresse déjà contactée / déjà client), on affiche une alerte douce
   * au-dessus de la liste avec un bouton "Envoyer quand même".
   * Le bouton est désactivé pendant l'appel (anti double-envoi).
   */
  async _sendReplyDraft(id, force, btn) {
    const original = btn ? btn.textContent : '';
    if (btn) { btn.disabled = true; btn.textContent = 'Envoi…'; }
    const restore = () => {
      if (btn) { btn.disabled = false; btn.textContent = original || 'Envoyer maintenant'; }
    };
    try {
      const r = await App.api.reply_send_now({ id, force: !!force });
      if (r && r.ok) {
        this._clearWarningBanner();
        Toast.success('Réponse envoyée.');
        await this.refresh();
        return;
      }
      if (r && r.warnings && r.warnings.length) {
        restore();
        this._showWarningBanner(r.warnings,
          () => this._sendReplyDraft(id, true, btn));
        return;
      }
      restore();
      Toast.error('Envoi impossible : ' + ((r && r.error) || 'erreur inconnue'));
    } catch (e) {
      restore();
      Toast.friendlyError(e, 'Envoi impossible pour le moment.');
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
    banner.className = 'mb-3 p-3 rounded-lg border border-warning/40 bg-warning/10 text-sm';
    banner.innerHTML = `
      <div class="font-semibold text-warning-text mb-1">⚠ À vérifier avant d’envoyer</div>
      <ul class="list-disc list-inside text-text-secondary mb-2">${msgs}</ul>
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
    if (!App.api || !App.api.replies_poll_now) {
      Toast.error('Fonction indisponible — rafraîchis la page.');
      return;
    }
    // Bouton désactivé pendant la vérification (anti double-clic), et la
    // liste revient TOUJOURS à la fin — succès comme échec (avant, un échec
    // laissait l'écran bloqué sur « Vérification… » pour toujours).
    const btn = document.getElementById('r-poll');
    const originalHtml = btn ? btn.innerHTML : '';
    if (btn) { btn.disabled = true; btn.textContent = 'Vérification…'; }
    const list = document.getElementById('r-list');
    if (list) list.innerHTML = `<div class="text-center py-12 text-text-muted">Vérification de ta boîte mail…</div>`;
    try {
      const r = await App.api.replies_poll_now();
      if (r && r.error) {
        const reasons = {
          supabase_unavailable: 'la base est injoignable pour le moment',
          no_imap_account_configured: 'aucun compte mail n’est réglé (Réglages → Mails)',
        };
        console.warn('replies_poll_now refus :', r.error);
        Toast.error('Vérification impossible : ' + (reasons[r.error] || r.error));
      } else if (r) {
        const n = r.written || 0;
        if (n > 0) Toast.success(`${n} nouvelle(s) réponse(s) trouvée(s).`);
        else Toast.info('Boîte vérifiée — rien de nouveau.');
      }
    } catch (e) {
      Toast.friendlyError(e, 'La vérification de la boîte mail a échoué.');
    } finally {
      if (btn) { btn.disabled = false; btn.innerHTML = originalHtml; }
      await this.refresh();
    }
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
          Connecte-toi à la base pour voir les vraies réponses.
        </p>
      </div>
    `;
  },
};

// Expose la vue pour les autres écrans : le Cockpit pré-règle le filtre via
// window.Replies avant d'ouvrir cet écran (un `const` seul n'est pas visible
// sur window).
window.Replies = Replies;
