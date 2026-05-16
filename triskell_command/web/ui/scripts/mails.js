/* Vue Mails — 3 onglets sur la table email_history.
 *
 *   1. Réponses prospects : entrants identifiés comme réponses à tes mails
 *      sortants (catégorisés par l'IA : intéressé / pas maintenant / refus / etc.)
 *   2. Tous entrants : limité aux réponses prospects pour l'instant — le
 *      worker IMAP ne loggue pas les autres mails. À étendre en phase 2.
 *   3. Tous sortants : tous les mails envoyés par l'app (prospection, suivi
 *      post-vente, kits de livraison, notifs internes).
 *
 * Pour l'instant, le filtre par compte n'est qu'informatif — le worker n'écrit
 * pas encore l'account_id sur chaque event.
 */

const Mails = {
  state: {
    tab: 'reply',         // 'reply' | 'inbound' | 'sent'
    accountFilter: '',    // id du compte (vide = tous)
    accounts: [],
    mails: [],
    lastKnownInboundId: null,  // pour la notif desktop
    notifPollHandle: null,
  },

  async render(container) {
    container.innerHTML = `
      <section class="animate-slide-up">
        <div class="mb-5 sm:mb-6 flex flex-col sm:flex-row sm:items-end sm:justify-between gap-3">
          <div class="min-w-0 flex-1">
            <div class="hero-kicker mb-2">MAILS</div>
            <h1 class="hero-title hero-title--md mb-2 sm:mb-3">Tous tes mails, un seul endroit.</h1>
            <p class="hero-subtitle">Réponses prospects, tous entrants, mails sortants — filtrables par adresse.</p>
          </div>
          <div class="flex flex-wrap gap-2">
            <button id="m-new" class="btn btn-primary">
              <svg class="w-4 h-4 mr-1.5 inline" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>
              Nouveau mail
            </button>
            <button id="m-prospect" class="btn btn-secondary"
                    style="background: linear-gradient(135deg, #7c6acc, #e85d2c); color: white; border: 0;"
                    title="Mail de prospection en direct — Claude analyse le site cible et adapte le modèle">
              <svg class="w-4 h-4 mr-1.5 inline" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>
              Prospection en direct
            </button>
            <button id="m-refresh" class="btn btn-secondary">Rafraîchir</button>
          </div>
        </div>

        <div class="flex gap-2 mb-4 border-b border-border">
          <button data-mtab="reply"   class="m-tab is-active">Réponses prospects</button>
          <button data-mtab="inbound" class="m-tab">Tous entrants</button>
          <button data-mtab="sent"    class="m-tab">Tous sortants</button>
        </div>

        <div class="flex items-center gap-3 mb-4 flex-wrap">
          <label class="text-xs text-text-muted">Compte :</label>
          <select id="m-account-filter" class="px-3 py-1.5 rounded-lg bg-bg border border-border text-sm">
            <option value="">— Tous —</option>
          </select>
          <div class="relative flex-1 min-w-[220px] max-w-md">
            <input id="m-search" type="search" placeholder="Rechercher un mail (sujet, expéditeur, contenu)…"
                   class="w-full pl-9 pr-3 py-1.5 rounded-lg bg-bg border border-border text-sm focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent"/>
            <svg class="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
              <circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
            </svg>
          </div>
          <span id="m-count" class="text-xs text-text-muted ml-auto"></span>
        </div>

        <div id="m-content"></div>
      </section>
    `;

    this._injectStyles();

    document.getElementById('m-refresh').onclick = () => this._load();
    document.getElementById('m-new').onclick = () => this._openComposer({});
    document.getElementById('m-prospect').onclick = () => this._openProspectFlow();
    document.querySelectorAll('[data-mtab]').forEach(btn => {
      btn.onclick = () => this._switchTab(btn.dataset.mtab);
    });
    document.getElementById('m-account-filter').onchange = (e) => {
      this.state.accountFilter = e.target.value;
      this._load();
    };
    // Recherche : filtre côté client (debounced)
    const searchInput = document.getElementById('m-search');
    let searchTimer = null;
    searchInput.addEventListener('input', (e) => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => {
        this.state.searchQuery = e.target.value.trim().toLowerCase();
        this._applySearch();
      }, 200);
    });

    await this._loadAccounts();
    await this._load();
  },

  _injectStyles() {
    if (document.getElementById('m-styles')) return;
    const s = document.createElement('style');
    s.id = 'm-styles';
    s.textContent = `
      .m-tab { padding: 10px 18px; font-size: 13px; font-weight: 600;
               color: hsl(var(--text-muted)); border-bottom: 2px solid transparent;
               transition: color 160ms, border-color 160ms; }
      .m-tab:hover { color: hsl(var(--text)); }
      .m-tab.is-active { color: hsl(var(--accent)); border-bottom-color: hsl(var(--accent)); }
    `;
    document.head.appendChild(s);
  },

  _switchTab(tab) {
    this.state.tab = tab;
    document.querySelectorAll('[data-mtab]').forEach(b => {
      b.classList.toggle('is-active', b.dataset.mtab === tab);
    });
    this._load();
  },

  async _loadAccounts() {
    await this._loadAccountsSilent();
    const sel = document.getElementById('m-account-filter');
    if (!sel) return;
    sel.innerHTML = `<option value="">— Tous —</option>` +
      this.state.accounts.map(a =>
        `<option value="${this._escape(a.id)}">${this._escape(a.label)} (${this._escape(a.from_email)})</option>`
      ).join('');
  },

  async _loadAccountsSilent() {
    if (!App.api) return;
    try {
      const r = await App.api.mail_accounts_list();
      if (r && r.ok) this.state.accounts = r.accounts || [];
    } catch (e) {}
  },

  async _load() {
    const root = document.getElementById('m-content');
    const countEl = document.getElementById('m-count');
    if (!App.api) {
      root.innerHTML = this._noBackend();
      return;
    }
    root.innerHTML = `<div class="card p-6 text-text-muted text-sm">Chargement…</div>`;

    // Note pour "Tous entrants"
    if (this.state.tab === 'inbound') {
      // Pour l'instant, on récupère reply_received et on prévient le user
      // que le worker IMAP ne loggue pas encore les autres entrants
    }

    const kindMap = { reply: 'reply', sent: 'sent', inbound: 'inbound' };
    const r = await App.api.mails_list({
      kind: kindMap[this.state.tab] || 'all',
      account_id: this.state.accountFilter || '',
      limit: 100,
    });
    if (!r || !r.ok) {
      root.innerHTML = `<div class="card p-6 text-danger">${(r && r.error) || 'Erreur API'}</div>`;
      return;
    }
    this.state.mails = r.mails || [];
    countEl.textContent = `${this.state.mails.length} mail(s)`;

    const limitedBanner = '';

    if (!this.state.mails.length) {
      root.innerHTML = limitedBanner + `
        <div class="card p-10 text-center">
          <div class="text-3xl mb-3 opacity-60">∅</div>
          <p class="text-text-muted">Aucun mail dans cette catégorie.</p>
        </div>
      `;
      return;
    }
    // Si une recherche est en cours, on délègue à _applySearch (qui filtre)
    if (this.state.searchQuery) {
      this._applySearch();
      return;
    }
    root.innerHTML = limitedBanner + `<div class="space-y-2">${this.state.mails.map(m => this._mailRow(m)).join('')}</div>`;
    // Bind clic = ouvre modale détail
    root.querySelectorAll('[data-mail-open]').forEach(el => {
      el.addEventListener('click', () => {
        const id = el.dataset.mailOpen;
        const mail = this.state.mails.find(m => String(m.id) === String(id));
        if (mail) this._openDetail(mail);
      });
    });
  },

  _mailRow(m) {
    const kind = m.kind || '';
    const isReply  = kind === 'reply_received';
    const isInbox  = kind === 'inbox_received';
    const isSent   = kind === 'email_sent';
    const tagColor = isReply ? 'success'
                  : isSent  ? 'accent'
                  : isInbox ? 'gold'
                  : 'text-muted';
    const tagLabel = isReply ? 'Réponse prospect'
                  : isSent  ? 'Envoyé'
                  : isInbox ? 'Entrant'
                  : kind;
    const fromAddr = (m.extra && m.extra.from) || '';
    const accountId = (m.extra && m.extra.account_id) || '';
    const ts = this._fmtDate(m.ts);
    const subject = m.subject || '(sans sujet)';
    const body = (m.body || '').slice(0, 200);
    const bodyExcerpt = body || (m.extra && m.extra.body_excerpt) || '';
    return `
      <div class="card p-4 cursor-pointer transition-all hover:border-accent" data-mail-open="${this._escape(m.id)}">
        <div class="flex items-start justify-between gap-3 mb-1">
          <div class="flex-1 min-w-0">
            <div class="text-sm font-semibold truncate">${this._escape(subject)}</div>
            ${(fromAddr || accountId) ? `<div class="text-[11px] text-text-muted truncate mt-0.5">
              ${fromAddr ? this._escape(fromAddr) : ''}${fromAddr && accountId ? ' · ' : ''}${accountId ? `boîte : ${this._escape(accountId)}` : ''}
            </div>` : ''}
          </div>
          <div class="flex items-center gap-2 shrink-0">
            <span class="text-[10px] font-bold uppercase px-2 py-1 rounded"
                  style="background: hsl(var(--${tagColor}) / 0.15); color: hsl(var(--${tagColor}));">
              ${tagLabel}
            </span>
            <span class="text-[11px] text-text-muted">${ts}</span>
          </div>
        </div>
        ${bodyExcerpt ? `<div class="text-xs text-text-secondary whitespace-pre-wrap line-clamp-3 mt-1">${this._escape(bodyExcerpt)}</div>` : ''}
      </div>
    `;
  },

  // ----------------------------------------------------------------------
  // Modale détail mail (style mail moderne)
  // ----------------------------------------------------------------------
  _openDetail(m) {
    const extra = m.extra || {};
    const subject = m.subject || '(sans sujet)';
    const fromAddr = extra.from || '';
    const fromInitial = (fromAddr[0] || '?').toUpperCase();
    const accountId = extra.account_id || '';
    const accountLabel = (this.state.accounts.find(a => a.id === accountId) || {}).label || accountId;
    const accountEmail = (this.state.accounts.find(a => a.id === accountId) || {}).from_email || '';
    const ts = this._fmtDateLong(m.ts);
    const body = extra.body_excerpt || m.body || '(corps vide)';
    const classification = extra.classification || null;
    const inReplyTo = extra.in_reply_to || '';
    const replySubject = subject.toLowerCase().startsWith('re:') ? subject : 'Re: ' + subject;

    const kindLabel = m.kind === 'reply_received' ? 'Réponse prospect'
                     : m.kind === 'inbox_received' ? 'Mail entrant'
                     : m.kind === 'email_sent' ? 'Mail envoyé' : m.kind;
    const kindColor = m.kind === 'reply_received' ? 'success'
                     : m.kind === 'email_sent' ? 'accent' : 'gold';

    const overlay = document.createElement('div');
    overlay.className = 'fixed inset-0 z-[200] flex items-center justify-center p-4 sm:p-6';
    overlay.style.background = 'rgba(15,23,42,0.7)';
    overlay.style.backdropFilter = 'blur(8px)';
    overlay.innerHTML = `
      <div class="bg-surface rounded-2xl shadow-hero w-full max-w-3xl h-[88vh] overflow-hidden border border-border animate-slide-up flex flex-col">

        <!-- ========== Top bar : badge + close ========== -->
        <div class="px-6 pt-4 pb-3 flex items-center justify-between border-b border-border bg-surface-elevated">
          <span class="text-[10px] font-bold uppercase tracking-widest px-2.5 py-1 rounded-full"
                style="background: hsl(var(--${kindColor}) / 0.15); color: hsl(var(--${kindColor}));">
            ${this._escape(kindLabel)}
          </span>
          <button id="md-close" class="w-8 h-8 rounded-lg flex items-center justify-center text-text-muted hover:text-text hover:bg-bg transition-colors text-xl leading-none">×</button>
        </div>

        <!-- ========== Zone scrollable : sujet + sender + body + composer ========== -->
        <div id="md-scroll" class="flex-1 overflow-y-auto">

          <!-- Sujet -->
          <div class="px-6 pt-5 pb-4">
            <h2 class="text-xl font-bold leading-snug text-text">${this._escape(subject)}</h2>
          </div>

          <!-- Sender card -->
          <div class="px-6 pb-4">
            <div class="flex items-start gap-3 p-4 rounded-xl bg-bg border border-border">
              <div class="w-11 h-11 rounded-full flex items-center justify-center text-white font-bold text-base shrink-0"
                   style="background: linear-gradient(135deg, hsl(var(--${kindColor})), hsl(var(--accent)));">
                ${this._escape(fromInitial)}
              </div>
              <div class="flex-1 min-w-0">
                <div class="flex items-baseline justify-between gap-3 flex-wrap">
                  <div class="text-sm font-semibold text-text truncate">${this._escape(fromAddr || '(expéditeur inconnu)')}</div>
                  <div class="text-[11px] text-text-muted shrink-0">${ts}</div>
                </div>
                <div class="text-xs text-text-muted mt-0.5">
                  → reçu sur <span class="font-medium text-text">${this._escape(accountLabel)}</span>${accountEmail ? ` <span class="opacity-70">(${this._escape(accountEmail)})</span>` : ''}
                </div>
                ${classification ? `<div class="text-[11px] mt-2"><span class="text-text-muted">Classification IA :</span> <span class="font-medium" style="color: hsl(var(--${kindColor}));">${this._escape(classification)}</span></div>` : ''}
              </div>
            </div>
          </div>

          <!-- Body du mail original -->
          <div class="px-6 pb-6">
            <div class="text-xs uppercase tracking-widest text-text-muted font-bold mb-2">CONTENU DU MAIL</div>
            <div class="rounded-xl bg-bg border border-border px-5 py-4">
              <pre class="text-sm text-text whitespace-pre-wrap font-sans leading-relaxed m-0">${this._escape(body)}</pre>
            </div>
          </div>

          <!-- Séparateur visuel -->
          <div class="px-6"><div class="border-t border-border"></div></div>

          <!-- Composer (toujours présent, mais condensé tant que pas activé) -->
          <div id="md-composer" class="px-6 py-5">
            <div id="md-composer-collapsed" class="">
              <button id="md-toggle-composer" class="w-full flex items-center justify-between gap-3 px-5 py-4 rounded-xl border border-dashed border-border hover:border-accent hover:bg-accent/5 transition-all group" ${fromAddr ? '' : 'disabled'}>
                <div class="flex items-center gap-3">
                  <div class="w-9 h-9 rounded-full bg-accent/15 text-accent flex items-center justify-center group-hover:bg-accent group-hover:text-white transition-colors">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><path d="M3 10h11M9 5l-5 5 5 5M21 19V5"/></svg>
                  </div>
                  <div class="text-left">
                    <div class="text-sm font-semibold text-text">Répondre</div>
                    <div class="text-[11px] text-text-muted">${fromAddr ? `Réponse à ${this._escape(fromAddr)} depuis ${this._escape(accountLabel)}` : 'Adresse expéditeur manquante'}</div>
                  </div>
                </div>
                <svg class="w-4 h-4 text-text-muted group-hover:text-accent transition-colors" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M9 18l6-6-6-6"/></svg>
              </button>
            </div>

            <div id="md-composer-form" class="hidden space-y-3">
              <div class="text-xs uppercase tracking-widest text-text-muted font-bold mb-2">VOTRE RÉPONSE</div>

              <!-- Depuis + À côte à côte -->
              <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label class="block text-[11px] font-medium text-text-secondary mb-1">Depuis quelle adresse</label>
                  <select id="md-cmp-from" class="w-full px-3 py-2.5 text-sm rounded-lg bg-bg border border-border focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent">
                    ${this.state.accounts.map(a =>
                      `<option value="${this._escape(a.id)}" ${a.id === accountId ? 'selected' : ''}>${this._escape(a.label)}</option>`
                    ).join('')}
                  </select>
                </div>
                <div>
                  <label class="block text-[11px] font-medium text-text-secondary mb-1">Destinataire</label>
                  <input id="md-cmp-to" type="email" value="${this._escape(fromAddr)}"
                         class="w-full px-3 py-2.5 text-sm rounded-lg bg-bg border border-border focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent"/>
                </div>
              </div>

              <div>
                <label class="block text-[11px] font-medium text-text-secondary mb-1">Objet</label>
                <input id="md-cmp-subject" type="text" value="${this._escape(replySubject)}"
                       class="w-full px-3 py-2.5 text-sm rounded-lg bg-bg border border-border focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent"/>
              </div>

              <div>
                <label class="block text-[11px] font-medium text-text-secondary mb-1">Message</label>
                <textarea id="md-cmp-body" rows="8"
                          class="w-full px-3 py-3 text-sm rounded-lg bg-bg border border-border focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent font-sans leading-relaxed resize-y"
                          placeholder="Tape ta réponse ici…&#10;&#10;Astuce : Ctrl+Entrée pour envoyer."></textarea>
              </div>

              <div class="flex items-center justify-between gap-3">
                <button id="md-cmp-cancel" class="text-xs text-text-muted hover:text-danger transition-colors">Annuler la réponse</button>
                <div id="md-cmp-status" class="text-xs text-text-muted text-right flex-1"></div>
              </div>
            </div>
          </div>
        </div>

        <!-- ========== Footer sticky : actions ========== -->
        <div id="md-footer" class="px-6 py-4 border-t border-border bg-surface-elevated flex items-center justify-end gap-2 shrink-0">
          <button id="md-ok" class="btn btn-secondary">Fermer</button>
          <button id="md-send" class="btn btn-primary hidden">
            <svg class="w-4 h-4 mr-1.5 inline" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><path d="M2 21l21-9-21-9v7l15 2-15 2z"/></svg>
            Envoyer la réponse
          </button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);

    const close = () => overlay.remove();
    const cmpForm  = overlay.querySelector('#md-composer-form');
    const cmpHint  = overlay.querySelector('#md-composer-collapsed');
    const toggleBtn = overlay.querySelector('#md-toggle-composer');
    const cancelBtn = overlay.querySelector('#md-cmp-cancel');
    const sendBtn = overlay.querySelector('#md-send');
    const okBtn   = overlay.querySelector('#md-ok');
    const scroll  = overlay.querySelector('#md-scroll');

    overlay.querySelector('#md-close').onclick = close;
    okBtn.onclick = close;
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });

    const escListener = (e) => { if (e.key === 'Escape') { close(); document.removeEventListener('keydown', escListener); } };
    document.addEventListener('keydown', escListener);

    // Bouton "Répondre ici" → ouvre le composer dédié (HTML supporté)
    toggleBtn.onclick = () => {
      close();
      this._openComposer({
        prefilledTo: fromAddr,
        prefilledSubject: replySubject,
        prefilledAccountId: accountId,
        inReplyTo: inReplyTo,
        title: 'Répondre',
      });
    };
    // Le composer inline n'est plus utilisé — on garde les references pour
    // compat (cancel button d'avant) mais on les masque
    if (cmpForm) cmpForm.classList.add('hidden');
    if (cmpHint) cmpHint.classList.remove('hidden');
    if (sendBtn) sendBtn.classList.add('hidden');
    if (cancelBtn) cancelBtn.onclick = () => { /* no-op */ };

    // Ctrl+Entrée pour envoyer
    overlay.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        e.preventDefault();
        if (!sendBtn.classList.contains('hidden')) sendBtn.click();
      }
    });

    sendBtn.onclick = async () => {
      const status = overlay.querySelector('#md-cmp-status');
      const account_id = overlay.querySelector('#md-cmp-from').value;
      const to = overlay.querySelector('#md-cmp-to').value.trim();
      const subj = overlay.querySelector('#md-cmp-subject').value.trim();
      const bodyVal = overlay.querySelector('#md-cmp-body').value;
      if (!to || !subj || !bodyVal.trim()) {
        status.textContent = '✗ Destinataire, sujet et message requis.';
        status.className = 'text-xs text-danger text-right flex-1';
        return;
      }
      sendBtn.disabled = true;
      sendBtn.innerHTML = '<svg class="w-4 h-4 mr-1.5 inline animate-spin" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M21 12a9 9 0 11-9-9"/></svg>Envoi…';
      status.textContent = '';
      try {
        const r = await App.api.mail_send_reply({
          account_id, to, subject: subj, body: bodyVal,
          in_reply_to: inReplyTo || '',
        });
        if (r && r.ok) {
          status.textContent = '✓ Envoyé !';
          status.className = 'text-xs text-success text-right flex-1';
          sendBtn.innerHTML = '✓ Envoyé';
          setTimeout(close, 1200);
        } else {
          status.textContent = `✗ ${(r && r.error) || 'Erreur inconnue'}`;
          status.className = 'text-xs text-danger text-right flex-1';
          sendBtn.disabled = false;
          sendBtn.innerHTML = '<svg class="w-4 h-4 mr-1.5 inline" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><path d="M2 21l21-9-21-9v7l15 2-15 2z"/></svg>Envoyer la réponse';
        }
      } catch (e) {
        status.textContent = `✗ ${e}`;
        status.className = 'text-xs text-danger text-right flex-1';
        sendBtn.disabled = false;
        sendBtn.innerHTML = '<svg class="w-4 h-4 mr-1.5 inline" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><path d="M2 21l21-9-21-9v7l15 2-15 2z"/></svg>Envoyer la réponse';
      }
    };
  },

  _fmtDateLong(iso) {
    if (!iso) return '—';
    try {
      const d = new Date(iso);
      return d.toLocaleString('fr-FR', { dateStyle: 'medium', timeStyle: 'short' });
    } catch { return iso; }
  },

  // ----------------------------------------------------------------------
  // Recherche côté client : filtre l'affichage sans recharger l'API
  // ----------------------------------------------------------------------
  _applySearch() {
    const q = (this.state.searchQuery || '').toLowerCase();
    const root = document.getElementById('m-content');
    const countEl = document.getElementById('m-count');
    if (!root) return;
    const all = this.state.mails || [];
    let visible = all;
    if (q) {
      visible = all.filter(m => {
        const extra = m.extra || {};
        const blob = [
          m.subject || '',
          m.body || '',
          extra.body_excerpt || '',
          extra.from || '',
          extra.to || '',
          extra.account_id || '',
          extra.classification || '',
        ].join(' ').toLowerCase();
        return blob.includes(q);
      });
    }
    countEl.textContent = q
      ? `${visible.length} / ${all.length} mail(s) (recherche : "${q}")`
      : `${all.length} mail(s)`;
    if (!visible.length) {
      root.innerHTML = `<div class="card p-10 text-center"><div class="text-3xl mb-3 opacity-60">∅</div><p class="text-text-muted">Aucun résultat pour "${this._escape(q)}".</p></div>`;
      return;
    }
    root.innerHTML = `<div class="space-y-2">${visible.map(m => this._mailRow(m)).join('')}</div>`;
    // Re-bind clic
    root.querySelectorAll('[data-mail-open]').forEach(el => {
      el.addEventListener('click', () => {
        const id = el.dataset.mailOpen;
        const mail = all.find(m => String(m.id) === String(id));
        if (mail) this._openDetail(mail);
      });
    });
  },

  // ----------------------------------------------------------------------
  // Notif desktop sur nouvel entrant (Web Notifications API)
  // ----------------------------------------------------------------------
  startDesktopNotifPolling() {
    if (this.state.notifPollHandle) return;  // déjà actif
    if (!('Notification' in window)) return; // navigateur ancien
    // Demande permission au 1er passage
    if (Notification.permission === 'default') {
      Notification.requestPermission().catch(() => {});
    }
    // Init le baseline (= mail le plus récent connu, pour ne pas notifier l'historique)
    this._initNotifBaseline();
    // Poll toutes les 60s
    this.state.notifPollHandle = setInterval(() => this._pollInbound(), 60_000);
  },

  async _initNotifBaseline() {
    if (!App.api) return;
    try {
      const r = await App.api.mails_list({ kind: 'inbound', limit: 1 });
      if (r && r.ok && r.mails && r.mails.length) {
        this.state.lastKnownInboundId = r.mails[0].id;
      }
    } catch (e) {}
  },

  async _pollInbound() {
    if (!App.api) return;
    if (Notification.permission !== 'granted') return;
    try {
      const r = await App.api.mails_list({ kind: 'inbound', limit: 10 });
      if (!r || !r.ok || !r.mails) return;
      const mails = r.mails;
      if (!mails.length) return;
      // Tous les mails plus récents que le dernier connu = nouveaux
      const lastKnown = this.state.lastKnownInboundId;
      const newOnes = [];
      for (const m of mails) {
        if (m.id === lastKnown) break;
        newOnes.push(m);
      }
      if (!newOnes.length) return;
      // Met à jour le baseline
      this.state.lastKnownInboundId = mails[0].id;
      // Affiche les notifs (max 3 d'un coup pour ne pas spammer)
      for (const m of newOnes.slice(0, 3)) {
        const extra = m.extra || {};
        const fromAddr = extra.from || '(inconnu)';
        const accountId = extra.account_id || '';
        const accountLabel = (this.state.accounts.find(a => a.id === accountId) || {}).label || accountId || '';
        const subject = m.subject || '(sans sujet)';
        const body = (extra.body_excerpt || m.body || '').slice(0, 100);
        const notif = new Notification(`📬 ${fromAddr}`, {
          body: `${subject}${accountLabel ? '\n→ ' + accountLabel : ''}${body ? '\n\n' + body : ''}`,
          icon: 'https://rmaafrrseafghptlsgdz.supabase.co/storage/v1/object/public/chat-images/triskell-logo.png',
          tag: `mail-${m.id}`,
        });
        notif.onclick = () => {
          window.focus();
          App.show('mails');
          setTimeout(() => this._openDetail(m), 200);
          notif.close();
        };
      }
    } catch (e) {}
  },

  // ----------------------------------------------------------------------
  // Mini modale "Coller du HTML brut" — textarea code + aperçu live à côté
  // ----------------------------------------------------------------------
  _openPasteHtmlDialog(htmlArea) {
    const overlay = document.createElement('div');
    overlay.className = 'fixed inset-0 z-[230] flex items-center justify-center p-4';
    overlay.style.background = 'rgba(15,23,42,0.7)';
    overlay.style.backdropFilter = 'blur(8px)';
    overlay.innerHTML = `
      <div class="bg-surface rounded-2xl shadow-hero w-full max-w-5xl h-[85vh] overflow-hidden border border-border animate-slide-up flex flex-col">
        <div class="px-6 pt-4 pb-3 flex items-center justify-between border-b border-border bg-surface-elevated">
          <div>
            <div class="hero-kicker mb-0.5">CODE HTML</div>
            <h3 class="text-base font-bold">Coller du HTML — avec aperçu en direct</h3>
          </div>
          <button id="ph-close" class="w-8 h-8 rounded-lg flex items-center justify-center text-text-muted hover:text-text hover:bg-bg transition-colors text-xl leading-none">×</button>
        </div>
        <div class="flex-1 grid grid-cols-1 md:grid-cols-2 gap-0 overflow-hidden">
          <!-- Code -->
          <div class="flex flex-col border-r border-border overflow-hidden">
            <div class="px-4 py-2 text-[10px] font-bold uppercase tracking-widest text-text-muted bg-bg border-b border-border">Code HTML</div>
            <textarea id="ph-input" placeholder='<p>Bonjour <strong>{prénom}</strong>,</p>...'
                      class="flex-1 px-3 py-3 text-xs bg-bg focus:outline-none font-mono leading-relaxed resize-none"></textarea>
          </div>
          <!-- Aperçu -->
          <div class="flex flex-col overflow-hidden">
            <div class="px-4 py-2 text-[10px] font-bold uppercase tracking-widest text-text-muted bg-bg border-b border-border flex items-center justify-between">
              <span>Aperçu (rendu mail)</span>
              <span id="ph-empty-hint" class="text-text-muted/60 normal-case font-normal tracking-normal">↪ tape du HTML pour voir le rendu</span>
            </div>
            <iframe id="ph-preview" sandbox="allow-same-origin"
                    class="flex-1 w-full bg-white border-0"></iframe>
          </div>
        </div>
        <div class="px-6 py-3 border-t border-border bg-surface-elevated flex items-center justify-between gap-2 shrink-0">
          <div class="text-[11px] text-text-muted">ⓘ Placeholders type <code>{prénom}</code> à remplacer à la main avant envoi.</div>
          <div class="flex gap-2">
            <button id="ph-cancel" class="btn btn-secondary">Annuler</button>
            <button id="ph-append" class="btn btn-secondary">Insérer à la fin</button>
            <button id="ph-replace" class="btn btn-primary">Remplacer le contenu</button>
          </div>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);
    const input   = overlay.querySelector('#ph-input');
    const iframe  = overlay.querySelector('#ph-preview');
    const hint    = overlay.querySelector('#ph-empty-hint');
    setTimeout(() => input.focus(), 50);
    const close = () => overlay.remove();
    overlay.querySelector('#ph-close').onclick = close;
    overlay.querySelector('#ph-cancel').onclick = close;

    // Update preview en temps réel (debounced)
    const renderPreview = () => {
      const html = input.value;
      if (!html.trim()) { hint.style.display = ''; iframe.srcdoc = ''; return; }
      hint.style.display = 'none';
      iframe.srcdoc = this._buildPreviewDoc(html);
    };
    let timer = null;
    input.addEventListener('input', () => {
      clearTimeout(timer);
      timer = setTimeout(renderPreview, 200);
    });

    overlay.querySelector('#ph-replace').onclick = () => {
      const html = input.value.trim();
      if (!html) { close(); return; }
      htmlArea.innerHTML = html;
      close();
      htmlArea.focus();
    };
    overlay.querySelector('#ph-append').onclick = () => {
      const html = input.value.trim();
      if (!html) { close(); return; }
      htmlArea.innerHTML = (htmlArea.innerHTML || '') + html;
      close();
      htmlArea.focus();
    };
  },

  // ----------------------------------------------------------------------
  // Modale Aperçu — rend le HTML actuel comme un client mail le verrait
  // ----------------------------------------------------------------------
  _openHtmlPreview(htmlContent, meta = {}) {
    const overlay = document.createElement('div');
    overlay.className = 'fixed inset-0 z-[230] flex items-center justify-center p-4';
    overlay.style.background = 'rgba(15,23,42,0.7)';
    overlay.style.backdropFilter = 'blur(8px)';
    const subject = meta.subject || '(sans sujet)';
    const from = meta.from || '';
    const to = meta.to || '(destinataire)';
    overlay.innerHTML = `
      <div class="bg-surface rounded-2xl shadow-hero w-full max-w-3xl h-[85vh] overflow-hidden border border-border animate-slide-up flex flex-col">
        <div class="px-6 pt-4 pb-3 flex items-center justify-between border-b border-border bg-surface-elevated">
          <div>
            <div class="hero-kicker mb-0.5">APERÇU MAIL</div>
            <h3 class="text-base font-bold">Ce que ton destinataire verra</h3>
          </div>
          <button id="hp-close" class="w-8 h-8 rounded-lg flex items-center justify-center text-text-muted hover:text-text hover:bg-bg text-xl leading-none">×</button>
        </div>
        <!-- En-têtes mail (façon client mail) -->
        <div class="px-6 py-3 border-b border-border bg-bg">
          <div class="text-base font-bold mb-2">${this._escape(subject)}</div>
          <div class="text-xs text-text-muted space-y-0.5">
            ${from ? `<div>De : <span class="text-text">${this._escape(from)}</span></div>` : ''}
            <div>À : <span class="text-text">${this._escape(to)}</span></div>
          </div>
        </div>
        <!-- Iframe rendu -->
        <iframe id="hp-frame" sandbox="allow-same-origin" class="flex-1 w-full bg-white border-0"></iframe>
        <div class="px-6 py-3 border-t border-border bg-surface-elevated flex items-center justify-between gap-2">
          <button id="hp-ok" class="btn btn-primary">Fermer l'aperçu</button>
          <div class="text-[11px] text-text-muted text-right">ⓘ Rendu isolé (sandbox). Les vrais clients mail (Gmail, Outlook…) peuvent légèrement différer.</div>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);
    overlay.querySelector('#hp-frame').srcdoc = this._buildPreviewDoc(htmlContent);
    const close = () => overlay.remove();
    overlay.querySelector('#hp-close').onclick = close;
    overlay.querySelector('#hp-ok').onclick = close;
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
    document.addEventListener('keydown', function esc(e) {
      if (e.key === 'Escape') { close(); document.removeEventListener('keydown', esc); }
    });
  },

  // Construit un document HTML auto-suffisant (avec styles "mail-friendly")
  // pour le rendre dans une iframe sandbox.
  _buildPreviewDoc(htmlContent) {
    const safeContent = String(htmlContent || '');
    return `<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8">
<style>
  body { margin: 0; padding: 24px;
         font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
         font-size: 14px; line-height: 1.55; color: #1a1a20;
         background: #ffffff; max-width: 680px; margin: 0 auto; }
  p { margin: 0 0 14px; }
  h1, h2, h3 { margin: 22px 0 10px; line-height: 1.25; color: #0f172a; }
  h1 { font-size: 24px; } h2 { font-size: 20px; } h3 { font-size: 17px; }
  ul, ol { margin: 0 0 14px; padding-left: 24px; }
  li { margin: 4px 0; }
  a { color: #5b5fd6; text-decoration: underline; }
  blockquote { margin: 14px 0; padding: 8px 16px; border-left: 3px solid #5b5fd6;
               background: #f7f7fb; color: #444; font-style: italic; }
  code { font-family: ui-monospace, Menlo, Consolas, monospace;
         background: #f1f1f5; padding: 1px 5px; border-radius: 4px; font-size: 13px; }
  img { max-width: 100%; height: auto; }
  hr { border: 0; border-top: 1px solid #e3e3e8; margin: 18px 0; }
</style>
</head><body>${safeContent}</body></html>`;
  },

  // ----------------------------------------------------------------------
  // Modale "Gérer mes templates" — liste + supprimer + renommer + aperçu
  // ----------------------------------------------------------------------
  async _openTemplatesManager() {
    const overlay = document.createElement('div');
    overlay.className = 'fixed inset-0 z-[220] flex items-center justify-center p-4 sm:p-6';
    overlay.style.background = 'rgba(15,23,42,0.7)';
    overlay.style.backdropFilter = 'blur(8px)';
    overlay.innerHTML = `
      <div class="bg-surface rounded-2xl shadow-hero w-full max-w-2xl h-[80vh] overflow-hidden border border-border animate-slide-up flex flex-col">
        <div class="px-6 pt-4 pb-3 flex items-center justify-between border-b border-border bg-surface-elevated">
          <div>
            <div class="hero-kicker mb-0.5">MODÈLES MAIL</div>
            <h3 class="text-base font-bold">Tes modèles HTML réutilisables</h3>
          </div>
          <button id="tm-close" class="w-8 h-8 rounded-lg flex items-center justify-center text-text-muted hover:text-text hover:bg-bg transition-colors text-xl leading-none">×</button>
        </div>
        <div id="tm-list" class="flex-1 overflow-y-auto p-4 space-y-2"></div>
        <div class="px-6 py-3 border-t border-border bg-surface-elevated text-[11px] text-text-muted">
          Pour créer un nouveau modèle : ouvre un mail dans le composer, écris ton HTML, clique sur "Modèles ▾ → Sauvegarder le contenu actuel comme modèle".
        </div>
      </div>
    `;
    document.body.appendChild(overlay);
    overlay.querySelector('#tm-close').onclick = () => overlay.remove();
    overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });

    const listEl = overlay.querySelector('#tm-list');
    const reload = async () => {
      listEl.innerHTML = '<div class="text-sm text-text-muted">Chargement…</div>';
      const r = await App.api.mail_templates_list();
      const tpls = (r && r.ok) ? (r.templates || []) : [];
      if (!tpls.length) {
        listEl.innerHTML = `
          <div class="text-center py-12 text-text-muted text-sm">
            Aucun modèle enregistré.
          </div>`;
        return;
      }
      listEl.innerHTML = tpls.map(t => `
        <div class="card p-4">
          <div class="flex items-start justify-between gap-3 mb-2">
            <div class="flex-1 min-w-0">
              <div class="text-sm font-bold text-text truncate">${this._escape(t.name)}</div>
              ${t.subject_default ? `<div class="text-[11px] text-text-muted truncate">Objet par défaut : ${this._escape(t.subject_default)}</div>` : ''}
            </div>
            <div class="flex gap-1 shrink-0">
              <button data-tm-rename="${this._escape(t.id)}" class="text-[11px] px-2 py-1 rounded hover:bg-bg text-text-muted hover:text-accent">Renommer</button>
              <button data-tm-remove="${this._escape(t.id)}" class="text-[11px] px-2 py-1 rounded hover:bg-bg text-text-muted hover:text-danger">Supprimer</button>
            </div>
          </div>
          <details class="text-xs">
            <summary class="cursor-pointer text-text-muted hover:text-text">Aperçu HTML</summary>
            <div class="mt-2 p-3 rounded-lg bg-bg border border-border max-h-48 overflow-y-auto">
              ${t.body_html || '<em class="text-text-muted">(vide)</em>'}
            </div>
          </details>
        </div>
      `).join('');
      // Bind renommer + supprimer
      listEl.querySelectorAll('[data-tm-remove]').forEach(btn => {
        btn.onclick = async () => {
          const tid = btn.dataset.tmRemove;
          const tpl = tpls.find(x => x.id === tid);
          if (!confirm(`Supprimer le modèle "${tpl && tpl.name}" ?`)) return;
          const r = await App.api.mail_template_remove({ id: tid });
          if (r && r.ok) reload();
          else alert('Échec : ' + (r && r.error || 'inconnu'));
        };
      });
      listEl.querySelectorAll('[data-tm-rename]').forEach(btn => {
        btn.onclick = async () => {
          const tid = btn.dataset.tmRename;
          const tpl = tpls.find(x => x.id === tid);
          const newName = prompt('Nouveau nom :', (tpl && tpl.name) || '');
          if (!newName || newName === (tpl && tpl.name)) return;
          const r = await App.api.mail_template_save({
            template: { ...tpl, name: newName }
          });
          if (r && r.ok) reload();
          else alert('Échec : ' + (r && r.error || 'inconnu'));
        };
      });
    };
    reload();
  },

  // ----------------------------------------------------------------------
  // Composer mail (nouveau OU réponse) — utilise le même endpoint mail_send
  // ----------------------------------------------------------------------
  // Options :
  //   { prefilledTo, prefilledSubject, prefilledAccountId, inReplyTo, title }
  async _openComposer(opts = {}) {
    // Charge les comptes si pas encore en cache (cas où le composer est
    // ouvert depuis la Matinale sans passer par la vue Mails).
    if (!this.state.accounts || !this.state.accounts.length) {
      await this._loadAccountsSilent();
    }
    const accounts = this.state.accounts || [];
    const defaultAccountId = opts.prefilledAccountId
      || (accounts.find(a => a.is_primary) || accounts[0] || {}).id
      || 'primary';
    const isReply = !!opts.inReplyTo;
    const title = opts.title || (isReply ? 'Répondre' : 'Nouveau mail');

    // Charge la liste de signatures + sélection auto selon le compte
    let signatures = [];
    if (App.api) {
      try {
        const r = await App.api.signatures_list();
        if (r && r.ok) signatures = r.signatures || [];
      } catch (e) {}
    }
    // Détermine la signature à utiliser par défaut pour le compte courant
    const pickSigForAccount = (accId) => {
      if (!signatures.length) return null;
      // 1) Signature explicitement attribuée au compte
      let s = signatures.find(s => (s.account_ids || []).includes(accId));
      // 2) Sinon signature "toutes adresses" (account_ids vide)
      if (!s) s = signatures.find(s => !(s.account_ids || []).length);
      // 3) Sinon la première
      return s || signatures[0] || null;
    };
    let currentSig = pickSigForAccount(defaultAccountId);
    let signature = currentSig?.body_text || '';
    let signatureHtml = currentSig?.body_html || '';

    const overlay = document.createElement('div');
    overlay.className = 'fixed inset-0 z-[210] flex items-center justify-center p-4 sm:p-6';
    overlay.style.background = 'rgba(15,23,42,0.7)';
    overlay.style.backdropFilter = 'blur(8px)';
    overlay.innerHTML = `
      <div class="bg-surface rounded-2xl shadow-hero w-full max-w-3xl h-[88vh] overflow-hidden border border-border animate-slide-up flex flex-col">
        <!-- Header -->
        <div class="px-6 pt-4 pb-3 flex items-center justify-between border-b border-border bg-surface-elevated">
          <div>
            <div class="hero-kicker mb-0.5">${this._escape(title.toUpperCase())}</div>
            <h3 class="text-base font-bold">${isReply ? 'Réponse à un mail' : 'Composer un mail'}</h3>
          </div>
          <button id="cmp-close" class="w-8 h-8 rounded-lg flex items-center justify-center text-text-muted hover:text-text hover:bg-bg transition-colors text-xl leading-none">×</button>
        </div>

        <!-- Form scrollable -->
        <div class="flex-1 overflow-y-auto px-6 py-5 space-y-3">
          <!-- Depuis + À -->
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label class="block text-[11px] font-medium text-text-secondary mb-1">Depuis quelle adresse</label>
              <select id="cmp-from" class="w-full px-3 py-2.5 text-sm rounded-lg bg-bg border border-border focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent text-ellipsis overflow-hidden whitespace-nowrap" style="text-overflow: ellipsis;">
                ${accounts.map(a =>
                  `<option value="${this._escape(a.id)}" ${a.id === defaultAccountId ? 'selected' : ''}>${this._escape(a.from_email)}${a.label && a.label !== a.from_email ? ' · ' + this._escape(a.label) : ''}</option>`
                ).join('')}
              </select>
            </div>
            <div>
              <div class="flex items-center justify-between mb-1 gap-2">
                <label class="block text-[11px] font-medium text-text-secondary">Destinataires</label>
                <div class="flex items-center gap-1 text-[10px] font-semibold">
                  <button id="cmp-toggle-cc" type="button" class="px-1.5 py-0.5 rounded text-text-muted hover:text-accent hover:bg-accent/10 transition-colors" title="Afficher le champ Cc">+ Cc</button>
                  <button id="cmp-toggle-bcc" type="button" class="px-1.5 py-0.5 rounded text-text-muted hover:text-accent hover:bg-accent/10 transition-colors" title="Afficher le champ Cci (copie cachée)">+ Cci</button>
                </div>
              </div>
              <div id="cmp-to-wrap" class="chips-input chips-input--to"
                   data-input-id="cmp-to-input"
                   data-placeholder="email@exemple.fr">
                <input id="cmp-to-input" type="text" autocomplete="off"
                       class="chips-text" placeholder="email@exemple.fr"/>
              </div>
            </div>
          </div>

          <!-- Cc / Cci (masqués par défaut) -->
          <div id="cmp-cc-row" class="hidden">
            <label class="block text-[11px] font-medium text-text-secondary mb-1">Cc <span class="text-text-muted font-normal">(copie visible)</span></label>
            <div id="cmp-cc-wrap" class="chips-input"
                 data-input-id="cmp-cc-input">
              <input id="cmp-cc-input" type="text" autocomplete="off"
                     class="chips-text" placeholder="email@exemple.fr"/>
            </div>
          </div>
          <div id="cmp-bcc-row" class="hidden">
            <label class="block text-[11px] font-medium text-text-secondary mb-1">Cci <span class="text-text-muted font-normal">(copie cachée — les autres destinataires ne la voient pas)</span></label>
            <div id="cmp-bcc-wrap" class="chips-input"
                 data-input-id="cmp-bcc-input">
              <input id="cmp-bcc-input" type="text" autocomplete="off"
                     class="chips-text" placeholder="email@exemple.fr"/>
            </div>
          </div>

          <!-- Sujet -->
          <div>
            <label class="block text-[11px] font-medium text-text-secondary mb-1">Objet</label>
            <input id="cmp-subject" type="text" value="${this._escape(opts.prefilledSubject || '')}" placeholder="Objet du mail"
                   class="w-full px-3 py-2.5 text-sm rounded-lg bg-bg border border-border focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent"/>
          </div>

          <!-- Toggle Texte / HTML + bouton Templates + Signature -->
          <div>
            <div class="flex items-center justify-between mb-1 gap-2 flex-wrap">
              <label class="block text-[11px] font-medium text-text-secondary">Message</label>
              <div class="flex items-center gap-2 text-[11px] flex-wrap">
                <!-- Dropdown signatures + bouton "gérer" -->
                <div class="flex items-center gap-1.5 shrink-0">
                  <button id="cmp-sig-edit" type="button"
                          title="Gérer mes signatures (ouvre les Réglages)"
                          class="w-6 h-6 rounded-md flex items-center justify-center text-text-muted hover:text-accent hover:bg-accent/10 transition-colors">
                    <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M20 14.66V20a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h5.34"/><polygon points="18 2 22 6 12 16 8 16 8 12 18 2"/></svg>
                  </button>
                  <select id="cmp-signature"
                          class="px-2.5 py-1 rounded-lg bg-bg border border-border font-semibold text-text"
                          style="min-width: 160px; max-width: 220px;">
                    <option value="">Sans signature</option>
                    ${signatures.map(s =>
                      `<option value="${this._escape(s.id)}" ${currentSig && s.id === currentSig.id ? 'selected' : ''}>${this._escape(s.name)}</option>`
                    ).join('')}
                  </select>
                </div>
                <!-- Dropdown templates -->
                <div class="relative">
                  <button id="cmp-tpl-trigger" class="px-2.5 py-1 rounded-lg font-semibold text-text-muted hover:bg-bg flex items-center gap-1">
                    <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                    Modèles ▾
                  </button>
                  <div id="cmp-tpl-menu" class="hidden absolute right-0 top-full mt-1 w-72 rounded-xl border border-border bg-surface shadow-lift z-30 max-h-80 overflow-y-auto">
                    <div id="cmp-tpl-list" class="py-1"></div>
                    <div class="border-t border-border py-1">
                      <button id="cmp-tpl-save" class="w-full px-4 py-2 text-left text-xs hover:bg-bg flex items-center gap-2 text-accent font-semibold">
                        <span>+</span> Sauvegarder le contenu actuel comme modèle
                      </button>
                      <button id="cmp-tpl-manage" class="w-full px-4 py-2 text-left text-xs hover:bg-bg flex items-center gap-2 text-text-muted">
                        <span>⚙</span> Gérer mes modèles…
                      </button>
                    </div>
                  </div>
                </div>
                <!-- Toggle Texte/HTML -->
                <button id="cmp-mode-text" class="px-2.5 py-1 rounded-lg font-semibold transition-colors bg-accent/15 text-accent">Texte</button>
                <button id="cmp-mode-html" class="px-2.5 py-1 rounded-lg font-semibold transition-colors text-text-muted hover:bg-bg">HTML enrichi</button>
              </div>
            </div>

            <!-- Mini barre d'outils HTML (cachée par défaut) -->
            <div id="cmp-toolbar" class="hidden flex items-center gap-1 mb-2 p-1.5 rounded-lg bg-bg border border-border">
              <button data-cmd="bold" title="Gras (Ctrl+B)" class="cmp-tb-btn font-bold">B</button>
              <button data-cmd="italic" title="Italique (Ctrl+I)" class="cmp-tb-btn italic">I</button>
              <button data-cmd="underline" title="Souligné (Ctrl+U)" class="cmp-tb-btn underline">U</button>
              <div class="w-px h-5 bg-border mx-1"></div>
              <button data-cmd="insertUnorderedList" title="Liste à puces" class="cmp-tb-btn">•</button>
              <button data-cmd="insertOrderedList" title="Liste numérotée" class="cmp-tb-btn">1.</button>
              <div class="w-px h-5 bg-border mx-1"></div>
              <button data-cmd="createLink" title="Lien" class="cmp-tb-btn">🔗</button>
              <button data-cmd="insert-image" title="Insérer une image dans le corps du mail" class="cmp-tb-btn">🖼</button>
              <button data-cmd="formatBlock-h2" title="Titre" class="cmp-tb-btn font-bold text-sm">H</button>
              <button data-cmd="formatBlock-blockquote" title="Citation" class="cmp-tb-btn">"</button>
              <div class="w-px h-5 bg-border mx-1"></div>
              <button data-cmd="paste-html" title="Coller du HTML brut" class="cmp-tb-btn font-mono">&lt;/&gt;</button>
              <button data-cmd="preview" title="Aperçu (rendu réel du mail)" class="cmp-tb-btn">👁 Aperçu</button>
              <button data-cmd="removeFormat" title="Effacer la mise en forme" class="cmp-tb-btn text-text-muted">×</button>
            </div>

            <!-- Editor texte simple -->
            <textarea id="cmp-body-text" rows="14" placeholder="Tape ton message ici…&#10;&#10;Astuce : Ctrl+Entrée pour envoyer."
                      class="w-full px-3 py-3 text-sm rounded-lg bg-bg border border-border focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent font-sans leading-relaxed resize-y"></textarea>

            <!-- Editor HTML (contenteditable) -->
            <div id="cmp-body-html" contenteditable="true"
                 class="hidden w-full min-h-[300px] px-4 py-3 text-sm rounded-lg bg-bg border border-border focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent font-sans leading-relaxed"
                 style="white-space: pre-wrap;"></div>
          </div>

          <!-- Pièces jointes -->
          <div id="cmp-attachments-section">
            <div class="flex items-center justify-between mb-2">
              <label class="text-[11px] font-medium text-text-secondary uppercase tracking-wider">Pièces jointes</label>
              <button id="cmp-add-attachment" type="button" class="text-[11px] text-accent font-semibold hover:underline flex items-center gap-1.5">
                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48"/></svg>
                Joindre un fichier
              </button>
            </div>
            <div id="cmp-attachments-list" class="space-y-1.5 text-xs"></div>
            <input id="cmp-attachment-input" type="file" multiple class="hidden">
            <div id="cmp-attachments-total" class="text-[10px] text-text-muted mt-1.5"></div>
          </div>

          <div id="cmp-status" class="text-xs text-text-muted"></div>
        </div>

        <!-- Footer sticky -->
        <div class="px-6 py-4 border-t border-border bg-surface-elevated flex items-center justify-between gap-2 shrink-0">
          <button id="cmp-cancel" class="btn btn-secondary">Annuler</button>
          <div class="flex items-center gap-2">
            <button id="cmp-draft" type="button" class="btn btn-secondary"
                    title="Enregistrer en brouillon pour reprendre plus tard">
              <svg class="w-4 h-4 mr-1.5 inline" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>
              Brouillon
            </button>
            <button id="cmp-schedule" type="button" class="btn btn-secondary"
                    title="Programmer l'envoi à une date/heure précise">
              <svg class="w-4 h-4 mr-1.5 inline" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
              Plus tard
            </button>
            <button id="cmp-send" class="btn btn-primary">
              <svg class="w-4 h-4 mr-1.5 inline" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><path d="M2 21l21-9-21-9v7l15 2-15 2z"/></svg>
              Envoyer
            </button>
          </div>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);

    // Pastilles "NEW" sur les nouveautés du composer (mai 2026).
    // Restent visibles jusqu'à ce que l'utilisateur clique la croix.
    if (window.NewBadge) {
      const imgBtn = overlay.querySelector('[data-cmd="insert-image"]');
      if (imgBtn) window.NewBadge.attach(imgBtn, 'mail-insert-image-v1');
      const attBtn = overlay.querySelector('#cmp-add-attachment');
      if (attBtn) window.NewBadge.attach(attBtn, 'mail-attachments-v1');
    }

    // Style pour les boutons toolbar (injecté une fois)
    if (!document.getElementById('cmp-toolbar-styles')) {
      const s = document.createElement('style');
      s.id = 'cmp-toolbar-styles';
      s.textContent = `
        .cmp-tb-btn { padding: 4px 9px; border-radius: 6px; font-size: 13px;
                      color: hsl(var(--text)); transition: background 120ms; }
        .cmp-tb-btn:hover { background: hsl(var(--accent) / 0.12);
                            color: hsl(var(--accent)); }
        #cmp-body-html:empty:before {
          content: 'Tape ton message ici…';
          color: hsl(var(--text-muted));
        }
        /* Images insérées : highlight au survol, indicateur si déjà liée */
        #cmp-body-html img {
          cursor: pointer;
          transition: outline 120ms, box-shadow 120ms;
        }
        #cmp-body-html img:hover {
          outline: 2px solid hsl(var(--accent));
          outline-offset: 2px;
        }
        #cmp-body-html a > img {
          box-shadow: 0 0 0 2px hsl(var(--accent) / 0.5);
        }
        #cmp-body-html a > img::after {
          content: '🔗';
        }
        /* Chips destinataires (To / Cc / Cci) */
        .chips-input {
          display: flex; flex-wrap: wrap; gap: 5px;
          padding: 5px 8px;
          border-radius: 8px;
          background: hsl(var(--bg));
          border: 1px solid hsl(var(--border));
          min-height: 40px;
          align-items: center;
          font-size: 13px;
          cursor: text;
          transition: border-color 120ms, box-shadow 120ms;
        }
        .chips-input:focus-within {
          border-color: hsl(var(--accent));
          box-shadow: 0 0 0 2px hsl(var(--accent) / 0.25);
        }
        .chips-input .chip {
          display: inline-flex; align-items: center; gap: 3px;
          padding: 2px 4px 2px 9px;
          border-radius: 5px;
          background: hsl(var(--accent) / 0.15);
          color: hsl(var(--accent));
          font-size: 12px; font-weight: 600;
          line-height: 1.3;
          max-width: 100%;
        }
        .chips-input .chip span {
          max-width: 280px;
          overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
        }
        .chips-input .chip.invalid {
          background: rgba(239, 68, 68, 0.15);
          color: #ef4444;
        }
        .chips-input .chip button {
          appearance: none;
          background: transparent;
          border: 0;
          color: inherit;
          opacity: 0.65;
          font-size: 14px;
          line-height: 1;
          padding: 0 4px;
          cursor: pointer;
        }
        .chips-input .chip button:hover { opacity: 1; }
        .chips-input .chips-text {
          flex: 1;
          min-width: 140px;
          background: transparent;
          border: 0;
          outline: 0;
          color: inherit;
          font-size: 13px;
          padding: 4px 0;
        }
      `;
      document.head.appendChild(s);
    }

    const close = () => overlay.remove();
    overlay.querySelector('#cmp-close').onclick = close;
    overlay.querySelector('#cmp-cancel').onclick = close;
    // Volontairement PAS de fermeture sur clic en dehors : Jordan a perdu
    // des mails ainsi. La modale ne se ferme que via × ou Annuler.
    // Idem pour Escape : on retire pour éviter une fermeture accidentelle.

    // ----------------------------------------------------------------------
    // Chips destinataires (To / Cc / Cci)
    // ----------------------------------------------------------------------
    const _isValidEmail = (s) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(s);

    const makeChips = (wrapEl) => {
      const inputEl = wrapEl.querySelector('.chips-text');
      let chips = [];
      const escape = (s) => this._escape(s);

      const renderChips = () => {
        [...wrapEl.querySelectorAll('.chip')].forEach(el => el.remove());
        chips.forEach((email, i) => {
          const valid = _isValidEmail(email);
          const chipEl = document.createElement('span');
          chipEl.className = 'chip' + (valid ? '' : ' invalid');
          chipEl.innerHTML = `<span title="${escape(email)}">${escape(email)}</span>` +
                             `<button type="button" data-i="${i}" title="Retirer">×</button>`;
          wrapEl.insertBefore(chipEl, inputEl);
          chipEl.querySelector('button').onclick = (e) => {
            e.preventDefault(); e.stopPropagation();
            chips.splice(i, 1);
            renderChips();
          };
        });
      };

      const tryCommit = () => {
        const raw = inputEl.value.trim().replace(/[,;]+$/, '').trim();
        if (!raw) return;
        // Permet de coller "a@x.fr, b@y.fr" et de splitter
        const parts = raw.split(/[\s,;]+/).filter(Boolean);
        parts.forEach(p => {
          if (!chips.some(c => c.toLowerCase() === p.toLowerCase())) {
            chips.push(p);
          }
        });
        inputEl.value = '';
        renderChips();
      };

      inputEl.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ',' || e.key === ';' || e.key === 'Tab') {
          if (inputEl.value.trim()) {
            e.preventDefault();
            tryCommit();
          }
        } else if (e.key === ' ' && _isValidEmail(inputEl.value.trim())) {
          // Espace après email valide → commit auto
          e.preventDefault();
          tryCommit();
        } else if (e.key === 'Backspace' && inputEl.value === '' && chips.length > 0) {
          chips.pop();
          renderChips();
        }
      });
      inputEl.addEventListener('blur', () => {
        if (inputEl.value.trim()) tryCommit();
      });
      // Coller : si plusieurs adresses, splitter
      inputEl.addEventListener('paste', (e) => {
        const text = (e.clipboardData || window.clipboardData).getData('text');
        if (text && /[,;\s]/.test(text)) {
          e.preventDefault();
          inputEl.value = text;
          tryCommit();
        }
      });
      // Click sur le wrap (hors chip / input) → focus input
      wrapEl.addEventListener('click', (e) => {
        if (e.target === wrapEl) inputEl.focus();
      });

      return {
        getValues: () => chips.slice(),
        setValues: (arr) => {
          chips = (arr || []).map(String).filter(Boolean);
          renderChips();
        },
        commitPending: () => tryCommit(),
        isEmpty: () => chips.length === 0 && !inputEl.value.trim(),
        anyInvalid: () => chips.some(c => !_isValidEmail(c)),
        focus: () => inputEl.focus(),
        wrapEl, inputEl,
      };
    };

    const chipsTo  = makeChips(overlay.querySelector('#cmp-to-wrap'));
    const chipsCc  = makeChips(overlay.querySelector('#cmp-cc-wrap'));
    const chipsBcc = makeChips(overlay.querySelector('#cmp-bcc-wrap'));

    // Pré-remplissage destinataire (ex : depuis "Répondre à X")
    if (opts.prefilledTo) {
      const parts = String(opts.prefilledTo).split(/[\s,;]+/).filter(Boolean);
      chipsTo.setValues(parts);
    }

    // Toggle des lignes Cc / Cci
    overlay.querySelector('#cmp-toggle-cc').onclick = () => {
      const row = overlay.querySelector('#cmp-cc-row');
      row.classList.remove('hidden');
      chipsCc.focus();
    };
    overlay.querySelector('#cmp-toggle-bcc').onclick = () => {
      const row = overlay.querySelector('#cmp-bcc-row');
      row.classList.remove('hidden');
      chipsBcc.focus();
    };

    // Gestion mode Texte / HTML
    let mode = 'text';
    const textBtn = overlay.querySelector('#cmp-mode-text');
    const htmlBtn = overlay.querySelector('#cmp-mode-html');
    const textArea = overlay.querySelector('#cmp-body-text');
    const htmlArea = overlay.querySelector('#cmp-body-html');
    const toolbar = overlay.querySelector('#cmp-toolbar');

    const setMode = (m) => {
      mode = m;
      if (m === 'text') {
        textBtn.className = 'px-2.5 py-1 rounded-lg font-semibold bg-accent/15 text-accent';
        htmlBtn.className = 'px-2.5 py-1 rounded-lg font-semibold text-text-muted hover:bg-bg';
        textArea.classList.remove('hidden');
        htmlArea.classList.add('hidden');
        toolbar.classList.add('hidden');
        // Si on revient en texte depuis HTML : convertit le HTML en texte basique
        if (htmlArea.innerHTML && !textArea.value) {
          textArea.value = htmlArea.innerText;
        }
      } else {
        textBtn.className = 'px-2.5 py-1 rounded-lg font-semibold text-text-muted hover:bg-bg';
        htmlBtn.className = 'px-2.5 py-1 rounded-lg font-semibold bg-accent/15 text-accent';
        textArea.classList.add('hidden');
        htmlArea.classList.remove('hidden');
        toolbar.classList.remove('hidden');
        // Si on passe en HTML avec du texte déjà : convertit en paragraphes
        if (textArea.value && !htmlArea.innerHTML) {
          htmlArea.innerHTML = textArea.value
            .split(/\n\n+/).map(p => `<p>${this._escape(p).replace(/\n/g, '<br>')}</p>`).join('');
        }
        htmlArea.focus();
      }
    };
    textBtn.onclick = () => setMode('text');
    htmlBtn.onclick = () => setMode('html');

    // ----------------------------------------------------------------------
    // Pièces jointes + images inline (CID)
    // ----------------------------------------------------------------------
    // Format d'une entrée : { filename, content_b64, content_type, size, inline, cid }
    const attachments = [];
    const MAX_TOTAL_BYTES = 22 * 1024 * 1024; // 22 Mo (la plupart des SMTP plafonnent à 25)

    const attListEl   = overlay.querySelector('#cmp-attachments-list');
    const attInputEl  = overlay.querySelector('#cmp-attachment-input');
    const attAddBtn   = overlay.querySelector('#cmp-add-attachment');
    const attTotalEl  = overlay.querySelector('#cmp-attachments-total');

    const fmtSize = (n) => {
      if (n == null) return '';
      if (n < 1024) return `${n} o`;
      if (n < 1024 * 1024) return `${Math.round(n / 1024)} Ko`;
      return `${(n / 1024 / 1024).toFixed(1)} Mo`;
    };

    const totalSize = () => attachments.reduce((s, a) => s + (a.size || 0), 0);

    const renderAttachments = () => {
      const visible = attachments.filter(a => !a.inline);
      if (!visible.length) {
        attListEl.innerHTML = '<div class="text-text-muted italic">Aucune pièce jointe pour l\'instant.</div>';
      } else {
        attListEl.innerHTML = visible.map((a) => {
          const realIdx = attachments.indexOf(a);
          return `<div class="flex items-center justify-between gap-2 px-3 py-2 rounded-lg bg-bg border border-border">
             <div class="flex items-center gap-2 min-w-0 flex-1">
               <span class="shrink-0">📄</span>
               <span class="truncate font-medium text-text">${this._escape(a.filename)}</span>
               <span class="text-text-muted shrink-0">${fmtSize(a.size)}</span>
             </div>
             <button data-att-rm="${realIdx}" type="button" title="Retirer cette pièce jointe"
                     class="text-text-muted hover:text-danger text-lg leading-none px-1">×</button>
           </div>`;
        }).join('');
        attListEl.querySelectorAll('[data-att-rm]').forEach(b => {
          b.onclick = () => {
            attachments.splice(Number(b.dataset.attRm), 1);
            renderAttachments();
          };
        });
      }
      const tot = totalSize();
      if (tot > 0) {
        const over = tot > MAX_TOTAL_BYTES;
        attTotalEl.textContent = `Total : ${fmtSize(tot)}${over ? ' — limite SMTP dépassée, retire des fichiers.' : ' / 22 Mo max recommandé'}`;
        attTotalEl.className = `text-[10px] mt-1.5 ${over ? 'text-danger font-semibold' : 'text-text-muted'}`;
      } else {
        attTotalEl.textContent = '';
      }
    };
    renderAttachments();

    const readFileAsBase64 = (file) => new Promise((resolve, reject) => {
      const r = new FileReader();
      r.onload = () => {
        const dataUrl = String(r.result || '');
        const idx = dataUrl.indexOf(',');
        resolve(idx >= 0 ? dataUrl.slice(idx + 1) : '');
      };
      r.onerror = () => reject(r.error || new Error('Lecture du fichier impossible'));
      r.readAsDataURL(file);
    });

    const addFiles = async (fileList) => {
      for (const file of Array.from(fileList || [])) {
        try {
          const b64 = await readFileAsBase64(file);
          attachments.push({
            filename: file.name,
            content_b64: b64,
            content_type: file.type || 'application/octet-stream',
            size: file.size,
            inline: false,
            cid: '',
          });
        } catch (e) {
          console.error('Pièce jointe KO :', file.name, e);
        }
      }
      renderAttachments();
    };

    attAddBtn.onclick = () => attInputEl.click();
    attInputEl.onchange = async () => {
      await addFiles(attInputEl.files);
      attInputEl.value = '';
    };

    // Insère une image (déjà lue côté JS) dans le corps en mode CID inline.
    // Utilisé par le bouton 🖼 toolbar ET par le drop d'image après choix
    // utilisateur "Dans le corps du mail".
    const insertImageFile = async (file) => {
      if (mode === 'text') setMode('html');
      try {
        const b64 = await readFileAsBase64(file);
        const cid = 'img_' + Math.random().toString(36).slice(2, 10) + '_' + Date.now().toString(36);
        attachments.push({
          filename: file.name || `image-${cid}.png`,
          content_b64: b64,
          content_type: file.type || 'image/png',
          size: file.size,
          inline: true,
          cid,
        });
        const dataUrl = `data:${file.type || 'image/png'};base64,${b64}`;
        htmlArea.focus();
        document.execCommand('insertHTML', false,
          `<img data-cid="${cid}" src="${dataUrl}" alt="${this._escape(file.name || 'image')}" style="max-width:100%; height:auto; display:block; margin:8px 0;">`);
        renderAttachments();
      } catch (e) {
        console.error('Insertion image KO :', e);
        alert('Impossible de lire cette image.');
      }
    };

    // Insertion d'image depuis le bouton toolbar 🖼 → ouvre un file picker
    const insertImageInBody = async () => {
      const picker = document.createElement('input');
      picker.type = 'file';
      picker.accept = 'image/*';
      picker.onchange = async () => {
        const file = picker.files && picker.files[0];
        if (!file) return;
        await insertImageFile(file);
      };
      picker.click();
    };

    // Petite modale qui demande comment ajouter une (ou plusieurs) image(s)
    // droppée(s) : dans le corps du mail OU en pièce jointe.
    const askImageMode = (images) => new Promise((resolve) => {
      const title = images.length === 1
        ? this._escape(images[0].name || 'image')
        : `${images.length} images`;
      const subtitle = images.length === 1
        ? 'Comment veux-tu ajouter cette image au mail ?'
        : `Comment veux-tu ajouter ces ${images.length} images au mail ?`;
      const ov = document.createElement('div');
      ov.className = 'fixed inset-0 z-[230] flex items-center justify-center p-4';
      ov.style.background = 'rgba(15,23,42,0.75)';
      ov.style.backdropFilter = 'blur(8px)';
      ov.innerHTML = `
        <div class="bg-surface rounded-2xl shadow-hero w-full max-w-sm border border-border animate-slide-up flex flex-col overflow-hidden">
          <div class="px-5 pt-4 pb-3 border-b border-border bg-surface-elevated">
            <div class="text-[10px] font-bold uppercase tracking-widest text-text-muted mb-0.5">IMAGE DÉPOSÉE</div>
            <h3 class="text-base font-bold leading-tight truncate">${title}</h3>
            <p class="text-xs text-text-muted mt-1">${subtitle}</p>
          </div>
          <div class="p-4 space-y-2">
            <button data-img-choice="inline"
                    class="w-full text-left px-4 py-3 rounded-xl border-2 border-accent bg-accent/10 hover:bg-accent/20 transition-colors">
              <div class="font-semibold text-text flex items-center gap-2">
                <svg class="w-4 h-4 text-accent shrink-0" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
                <span>Dans le corps du mail</span>
              </div>
              <div class="text-xs text-text-muted mt-1">L'image s'affiche directement dans le texte — recommandé pour les visuels.</div>
            </button>
            <button data-img-choice="attach"
                    class="w-full text-left px-4 py-3 rounded-xl border border-border hover:border-accent hover:bg-bg transition-colors">
              <div class="font-semibold text-text flex items-center gap-2">
                <svg class="w-4 h-4 text-text-muted shrink-0" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48"/></svg>
                <span>En pièce jointe</span>
              </div>
              <div class="text-xs text-text-muted mt-1">L'image est attachée au mail, le destinataire la télécharge.</div>
            </button>
          </div>
          <div class="px-5 pb-4 flex items-center justify-end">
            <button data-img-choice="cancel" class="text-xs text-text-muted hover:text-danger">Annuler</button>
          </div>
        </div>
      `;
      document.body.appendChild(ov);
      const finish = (choice) => {
        document.removeEventListener('keydown', escListener);
        ov.remove();
        resolve(choice);
      };
      const escListener = (e) => { if (e.key === 'Escape') finish('cancel'); };
      document.addEventListener('keydown', escListener);
      ov.addEventListener('click', (e) => {
        const btn = e.target.closest('[data-img-choice]');
        if (btn) finish(btn.dataset.imgChoice);
        else if (e.target === ov) finish('cancel');
      });
    });

    // Drag & drop sur la zone composer.
    // Images → on demande : corps du mail OU pièce jointe.
    // Autres fichiers → pièce jointe directement.
    overlay.addEventListener('dragover', (e) => {
      if (e.dataTransfer && Array.from(e.dataTransfer.types || []).includes('Files')) {
        e.preventDefault();
      }
    });
    overlay.addEventListener('drop', async (e) => {
      if (!e.dataTransfer || !e.dataTransfer.files || !e.dataTransfer.files.length) return;
      e.preventDefault();
      const files = Array.from(e.dataTransfer.files);
      const images = files.filter(f => f.type && f.type.startsWith('image/'));
      const others = files.filter(f => !f.type || !f.type.startsWith('image/'));
      if (others.length) await addFiles(others);
      if (images.length) {
        const choice = await askImageMode(images);
        if (choice === 'inline') {
          for (const img of images) {
            await insertImageFile(img);
          }
        } else if (choice === 'attach') {
          await addFiles(images);
        }
        // choice === 'cancel' → on ignore les images
      }
    });

    // Boutons toolbar HTML
    toolbar.querySelectorAll('[data-cmd]').forEach(btn => {
      btn.onclick = (e) => {
        e.preventDefault();
        const cmd = btn.dataset.cmd;
        htmlArea.focus();
        if (cmd === 'createLink') {
          const url = prompt('URL du lien :', 'https://');
          if (url) document.execCommand('createLink', false, url);
        } else if (cmd === 'insert-image') {
          insertImageInBody();
        } else if (cmd === 'paste-html') {
          this._openPasteHtmlDialog(htmlArea);
        } else if (cmd === 'preview') {
          const subj = (overlay.querySelector('#cmp-subject').value || '').trim();
          const fromSel = overlay.querySelector('#cmp-from');
          const fromLabel = fromSel.options[fromSel.selectedIndex]?.text || '';
          const to = chipsTo.getValues().join(', ');
          this._openHtmlPreview(htmlArea.innerHTML, { subject: subj, from: fromLabel, to });
        } else if (cmd.startsWith('formatBlock-')) {
          const tag = cmd.split('-')[1];
          document.execCommand('formatBlock', false, `<${tag}>`);
        } else {
          document.execCommand(cmd, false, null);
        }
      };
    });

    // Ctrl+Entrée pour envoyer
    overlay.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        e.preventDefault();
        overlay.querySelector('#cmp-send').click();
      }
    });

    // -------- Templates --------
    const tplTrigger = overlay.querySelector('#cmp-tpl-trigger');
    const tplMenu    = overlay.querySelector('#cmp-tpl-menu');
    const tplList    = overlay.querySelector('#cmp-tpl-list');
    const subjectInput = overlay.querySelector('#cmp-subject');

    const loadTemplates = async () => {
      tplList.innerHTML = '<div class="px-4 py-3 text-xs text-text-muted">Chargement…</div>';
      const r = await App.api.mail_templates_list();
      const tpls = (r && r.ok) ? (r.templates || []) : [];
      if (!tpls.length) {
        tplList.innerHTML = '<div class="px-4 py-3 text-xs text-text-muted">Aucun modèle encore. Sauvegarde ton contenu actuel ci-dessous.</div>';
        return;
      }
      tplList.innerHTML = tpls.map(t => `
        <button data-tpl-id="${this._escape(t.id)}" class="w-full px-4 py-2 text-left text-xs hover:bg-bg flex flex-col gap-0.5">
          <span class="font-semibold text-text truncate">${this._escape(t.name)}</span>
          ${t.subject_default ? `<span class="text-text-muted truncate">${this._escape(t.subject_default)}</span>` : ''}
        </button>
      `).join('');
      tplList.querySelectorAll('[data-tpl-id]').forEach(btn => {
        btn.onclick = () => {
          const tpl = tpls.find(x => x.id === btn.dataset.tplId);
          if (!tpl) return;
          // Insère le HTML : bascule en mode HTML et remplace le body
          setMode('html');
          htmlArea.innerHTML = tpl.body_html || '';
          // Pré-remplit le sujet si vide et template a un sujet par défaut
          if (tpl.subject_default && !subjectInput.value.trim()) {
            subjectInput.value = tpl.subject_default;
          }
          tplMenu.classList.add('hidden');
          htmlArea.focus();
        };
      });
    };

    tplTrigger.onclick = (e) => {
      e.stopPropagation();
      const wasHidden = tplMenu.classList.contains('hidden');
      tplMenu.classList.toggle('hidden');
      if (wasHidden) loadTemplates();
    };
    // Click ailleurs ferme le menu
    overlay.addEventListener('click', (e) => {
      if (!tplTrigger.contains(e.target) && !tplMenu.contains(e.target)) {
        tplMenu.classList.add('hidden');
      }
    });

    // Sauvegarder comme template
    overlay.querySelector('#cmp-tpl-save').onclick = async () => {
      // Récupère le contenu courant (HTML ou texte converti en HTML basique)
      let htmlContent = '';
      if (mode === 'html') {
        htmlContent = htmlArea.innerHTML.trim();
      } else {
        const txt = textArea.value;
        htmlContent = txt.split(/\n\n+/)
          .map(p => `<p>${this._escape(p).replace(/\n/g, '<br>')}</p>`).join('');
      }
      if (!htmlContent || htmlContent === '<p></p>') {
        alert('Le contenu est vide. Écris quelque chose avant de sauvegarder.');
        return;
      }
      const name = prompt('Nom du modèle (ex : "Devis envoyé", "Suivi 1 mois") :');
      if (!name) return;
      const useSubject = subjectInput.value.trim();
      const wantSubj = useSubject && confirm(`Sauvegarder aussi l'objet "${useSubject}" comme objet par défaut du modèle ?`);
      const r = await App.api.mail_template_save({
        template: { name, body_html: htmlContent, subject_default: wantSubj ? useSubject : '' }
      });
      if (r && r.ok) {
        tplMenu.classList.add('hidden');
        // Petite confirmation visuelle
        const status = overlay.querySelector('#cmp-status');
        status.textContent = `✓ Modèle "${name}" sauvegardé.`;
        status.className = 'text-xs text-success';
        setTimeout(() => { if (status.textContent.startsWith('✓ Modèle')) status.textContent = ''; }, 3000);
      } else {
        alert('Échec sauvegarde : ' + (r && r.error || 'inconnu'));
      }
    };

    // Gérer les templates
    overlay.querySelector('#cmp-tpl-manage').onclick = () => {
      tplMenu.classList.add('hidden');
      this._openTemplatesManager();
    };

    // ----- Gestion dynamique de la signature -----
    // Le body est conceptuellement [partie écrite par le user] + [marker] + [signature]
    // On marque la signature avec un commentaire HTML invisible pour pouvoir la
    // remplacer proprement quand le user change de signature.
    const SIG_MARK_HTML = '<div data-signature-block style="margin-top:1.5em;">';
    const SIG_MARK_HTML_END = '</div>';

    const applySignature = (sig) => {
      const sigText = sig?.body_text || '';
      const sigHtml = sig?.body_html || '';
      // -- Texte --
      // Stratégie : retire l'ancienne signature (après le dernier double-saut),
      // remet la nouvelle. Si l'utilisateur n'a rien écrit avant, on garde tel quel.
      const taVal = textArea.value;
      // On retire l'ancienne signature en se basant sur celle qui était en place :
      // si textArea finit par "\n\n{ancienne sig}", on la retire
      let body = taVal;
      if (signature && body.endsWith('\n\n' + signature)) {
        body = body.slice(0, -(signature.length + 2));
      } else if (signature && body.endsWith(signature)) {
        body = body.slice(0, -signature.length);
      }
      // Ajoute la nouvelle
      textArea.value = sigText ? (body || '') + (body && !body.endsWith('\n\n') ? '\n\n' : (body ? '\n' : '\n\n')) + sigText : body;
      // -- HTML --
      // On retire l'ancien bloc signature (marqué par data-signature-block) s'il existe
      let html = htmlArea.innerHTML;
      html = html.replace(/<div data-signature-block[\s\S]*?<\/div>\s*$/, '');
      if (sigHtml) {
        html = html + SIG_MARK_HTML + sigHtml + SIG_MARK_HTML_END;
      } else if (sigText) {
        const sigAsHtml = sigText.split(/\n\n+/)
          .map(p => `<p>${this._escape(p).replace(/\n/g, '<br>')}</p>`).join('');
        html = html + SIG_MARK_HTML + sigAsHtml + SIG_MARK_HTML_END;
      }
      htmlArea.innerHTML = html;
      // Mémorise pour le prochain swap
      signature = sigText;
      signatureHtml = sigHtml;
      currentSig = sig;
    };

    // Pré-remplissage initial avec la signature sélectionnée
    if (currentSig) {
      // applique sans wiper : textArea/htmlArea sont encore vides à ce stade
      if (signature) {
        textArea.value = '\n\n' + signature;
        setTimeout(() => textArea.setSelectionRange(0, 0), 100);
      }
      if (signatureHtml) {
        htmlArea.innerHTML = `<p><br></p><p><br></p>${SIG_MARK_HTML}${signatureHtml}${SIG_MARK_HTML_END}`;
      } else if (signature) {
        const sigAsHtml = signature.split(/\n\n+/)
          .map(p => `<p>${this._escape(p).replace(/\n/g, '<br>')}</p>`).join('');
        htmlArea.innerHTML = `<p><br></p><p><br></p>${SIG_MARK_HTML}${sigAsHtml}${SIG_MARK_HTML_END}`;
      }
    }

    // Pré-remplissage du corps HTML (workflow prospection en direct)
    if (opts.prefilledBodyHtml) {
      // Si signature présente, insère le body AVANT la signature
      const sigStart = htmlArea.innerHTML.indexOf(SIG_MARK_HTML);
      if (sigStart >= 0) {
        const sigBlock = htmlArea.innerHTML.slice(sigStart);
        htmlArea.innerHTML = opts.prefilledBodyHtml + '<p><br></p>' + sigBlock;
      } else {
        htmlArea.innerHTML = opts.prefilledBodyHtml;
      }
    }

    // Bind du dropdown signature : remplace dans le body
    const sigSelect = overlay.querySelector('#cmp-signature');
    if (sigSelect) {
      sigSelect.onchange = () => {
        const id = sigSelect.value;
        const sig = id ? signatures.find(s => s.id === id) : null;
        applySignature(sig);
      };
    }

    // Bind du dropdown compte expéditeur : auto-sélection de la signature
    const fromSel = overlay.querySelector('#cmp-from');
    if (fromSel) {
      fromSel.addEventListener('change', () => {
        const newSig = pickSigForAccount(fromSel.value);
        if (newSig?.id !== currentSig?.id) {
          if (sigSelect) sigSelect.value = newSig?.id || '';
          applySignature(newSig);
        }
      });
    }

    // Clic sur une image insérée dans le corps → modale pour la rendre
    // cliquable (ajouter / modifier / retirer une URL de destination).
    htmlArea.addEventListener('click', (e) => {
      const img = e.target.closest('img');
      if (img && htmlArea.contains(img)) {
        e.preventDefault();
        e.stopPropagation();
        this._openImageLinkDialog(img);
      }
    });

    // ----------------------------------------------------------------------
    // Brouillons (localStorage)
    // ----------------------------------------------------------------------
    // Permet de quitter le composer sans perdre ce qu'on a écrit. Stocké
    // dans le navigateur (pas synchronisé entre PC pour l'instant).
    // Limite : les pièces jointes ne sont PAS sauvegardées (trop lourd).
    const DRAFT_KEY = 'tc-mail-draft';

    const captureDraftState = () => {
      let body_html_val = '';
      if (mode === 'html') {
        const clone = htmlArea.cloneNode(true);
        body_html_val = clone.innerHTML;
      }
      return {
        to: chipsTo.getValues().join(', '),
        cc: chipsCc.getValues().join(', '),
        bcc: chipsBcc.getValues().join(', '),
        subject: overlay.querySelector('#cmp-subject').value,
        account_id: overlay.querySelector('#cmp-from').value,
        signature_id: overlay.querySelector('#cmp-signature').value,
        mode,
        body_text: textArea.value,
        body_html: body_html_val,
        ts: Date.now(),
      };
    };
    const isDraftMeaningful = (d) => {
      if ((d.to || '').trim()) return true;
      if ((d.subject || '').trim()) return true;
      const txt = (d.body_text || '').trim();
      if (txt && (!signature || txt !== signature)) return true;
      // Pour HTML : on retire les espaces et tags vides
      const compactHtml = (d.body_html || '').replace(/\s+/g, '');
      const sigCompact = (signatureHtml || '').replace(/\s+/g, '');
      // Si HTML contient autre chose que les <p><br></p> initiaux + la signature
      const stripped = compactHtml
        .replace(/<p><br><\/p>/g, '')
        .replace(/<divdata-signature-block[^>]*>.*?<\/div>/g, '')
        .replace(sigCompact, '');
      if (stripped.length > 0) return true;
      return false;
    };

    // Bouton "Brouillon" du footer
    const draftBtn = overlay.querySelector('#cmp-draft');
    if (draftBtn) {
      draftBtn.onclick = () => {
        const d = captureDraftState();
        if (!isDraftMeaningful(d)) {
          alert('Rien à enregistrer en brouillon — écris d\'abord ton mail.');
          return;
        }
        try {
          localStorage.setItem(DRAFT_KEY, JSON.stringify(d));
          const orig = draftBtn.innerHTML;
          draftBtn.innerHTML = '<svg class="w-4 h-4 mr-1.5 inline" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><path d="M5 13l4 4L19 7"/></svg>Brouillon enregistré';
          setTimeout(close, 700);
        } catch (e) {
          alert('Impossible d\'enregistrer le brouillon : ' + e.message);
        }
      };
    }

    // Annuler : si du contenu rédigé, propose Brouillon ou Perdre
    const cancelBtn = overlay.querySelector('#cmp-cancel');
    if (cancelBtn) {
      cancelBtn.onclick = () => {
        const d = captureDraftState();
        if (!isDraftMeaningful(d)) {
          close();
          return;
        }
        const choice = confirm(
          'Tu as commencé à rédiger un mail.\n\n' +
          'OK   → enregistrer en brouillon (tu pourras reprendre plus tard)\n' +
          'Annuler → perdre le contenu'
        );
        if (choice) {
          try { localStorage.setItem(DRAFT_KEY, JSON.stringify(d)); } catch (e) {}
          close();
        } else {
          if (confirm('Confirmer la perte de ce que tu as écrit ?')) close();
        }
      };
    }

    // Helper : construit le payload pour mail_send / mail_schedule
    // (utilisé par le bouton Envoyer ET le bouton Plus tard)
    const buildSendPayload = () => {
      // Commit toute saisie en attente dans les chips avant de récupérer
      chipsTo.commitPending(); chipsCc.commitPending(); chipsBcc.commitPending();
      const account_id = overlay.querySelector('#cmp-from').value;
      const toList = chipsTo.getValues();
      const ccList = chipsCc.getValues();
      const bccList = chipsBcc.getValues();
      const to = toList.join(', ');
      const subj = overlay.querySelector('#cmp-subject').value.trim();
      let body = '', body_html = '';
      if (mode === 'html') {
        const clone = htmlArea.cloneNode(true);
        clone.querySelectorAll('img[data-cid]').forEach(img => {
          const cid = img.getAttribute('data-cid');
          img.setAttribute('src', `cid:${cid}`);
          img.removeAttribute('data-cid');
        });
        body_html = clone.innerHTML.trim();
        body = htmlArea.innerText.trim();
      } else {
        body = textArea.value;
      }
      // Filtre attachments inline non référencées
      const referencedCids = new Set();
      (body_html.match(/cid:([a-zA-Z0-9_]+)/g) || []).forEach(m => {
        referencedCids.add(m.slice(4));
      });
      const cleanAttachments = attachments.filter(a => !a.inline || referencedCids.has(a.cid));
      return { account_id, to, ccList, bccList, subj, body, body_html, cleanAttachments };
    };

    // Bouton "Plus tard" → programme l'envoi à une date/heure choisie
    const scheduleBtn = overlay.querySelector('#cmp-schedule');
    if (scheduleBtn) {
      scheduleBtn.onclick = () => {
        const status = overlay.querySelector('#cmp-status');
        const p = buildSendPayload();
        if (!p.to || !p.subj || (!p.body.trim() && !p.body_html)) {
          status.textContent = '✗ Destinataire, objet et message requis avant de programmer.';
          status.className = 'text-xs text-danger';
          return;
        }
        const totBytes = p.cleanAttachments.reduce((s, a) => s + (a.size || 0), 0);
        if (totBytes > MAX_TOTAL_BYTES) {
          status.textContent = `✗ Pièces jointes trop lourdes (${fmtSize(totBytes)}). Max 22 Mo.`;
          status.className = 'text-xs text-danger';
          return;
        }
        this._openScheduleDialog(async (scheduledAtISO, prettyDate) => {
          scheduleBtn.disabled = true;
          scheduleBtn.innerHTML = 'Programmation…';
          try {
            const r = await App.api.mail_schedule({
              account_id: p.account_id,
              to: p.to,
              cc: p.ccList,
              bcc: p.bccList,
              subject: p.subj,
              body: p.body,
              body_html: p.body_html,
              in_reply_to: opts.inReplyTo || '',
              scheduled_at: scheduledAtISO,
              attachments: p.cleanAttachments.map(a => ({
                filename: a.filename, content_b64: a.content_b64,
                content_type: a.content_type,
                inline: !!a.inline, cid: a.cid || '',
              })),
            });
            if (r && r.ok) {
              status.textContent = `✓ Mail programmé pour ${prettyDate}`;
              status.className = 'text-xs text-success';
              try { localStorage.removeItem('tc-mail-draft'); } catch (e) {}
              setTimeout(close, 1200);
            } else {
              status.textContent = `✗ ${(r && r.error) || 'Erreur inconnue'}`;
              status.className = 'text-xs text-danger';
              scheduleBtn.disabled = false;
              scheduleBtn.innerHTML = '<svg class="w-4 h-4 mr-1.5 inline" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>Plus tard';
            }
          } catch (e) {
            status.textContent = `✗ ${e.message || e}`;
            status.className = 'text-xs text-danger';
            scheduleBtn.disabled = false;
            scheduleBtn.innerHTML = '<svg class="w-4 h-4 mr-1.5 inline" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>Plus tard';
          }
        });
      };
    }

    // Bouton "Gérer mes signatures" (icône crayon à côté du select)
    const sigEditBtn = overlay.querySelector('#cmp-sig-edit');
    if (sigEditBtn) {
      sigEditBtn.onclick = () => {
        const d = captureDraftState();
        if (isDraftMeaningful(d)) {
          try { localStorage.setItem(DRAFT_KEY, JSON.stringify(d)); } catch (e) {}
        }
        close();
        if (typeof App !== 'undefined' && App.show) {
          App.show('config');
          // Le rendu Config est async (fetch settings), on retente jusqu'à
          // ce que la liste signatures soit dans le DOM (max 2 sec).
          let tries = 20;
          const tryScroll = () => {
            const sigSection = document.getElementById('cfg-sig-list');
            if (sigSection) {
              sigSection.scrollIntoView({ behavior: 'smooth', block: 'center' });
              return;
            }
            if (--tries > 0) setTimeout(tryScroll, 100);
          };
          setTimeout(tryScroll, 100);
        }
      };
    }

    // Restauration brouillon à l'ouverture (si présent et < 30 jours)
    if (!opts.prefilledTo && !opts.prefilledSubject && !opts.inReplyTo) {
      try {
        const raw = localStorage.getItem(DRAFT_KEY);
        if (raw) {
          const d = JSON.parse(raw);
          if (d && d.ts && (Date.now() - d.ts < 30 * 24 * 3600 * 1000)) {
            this._showDraftRestoreBanner(overlay, d, () => {
              const splitAddrs = (s) => (s || '').split(/[\s,;]+/).filter(Boolean);
              chipsTo.setValues(splitAddrs(d.to));
              const ccArr = splitAddrs(d.cc);
              const bccArr = splitAddrs(d.bcc);
              if (ccArr.length) {
                chipsCc.setValues(ccArr);
                overlay.querySelector('#cmp-cc-row').classList.remove('hidden');
              }
              if (bccArr.length) {
                chipsBcc.setValues(bccArr);
                overlay.querySelector('#cmp-bcc-row').classList.remove('hidden');
              }
              overlay.querySelector('#cmp-subject').value = d.subject || '';
              if (d.account_id) {
                const fs = overlay.querySelector('#cmp-from');
                if (fs && [...fs.options].some(o => o.value === d.account_id)) fs.value = d.account_id;
              }
              if (d.signature_id !== undefined) {
                const ss = overlay.querySelector('#cmp-signature');
                if (ss && [...ss.options].some(o => o.value === d.signature_id)) ss.value = d.signature_id;
              }
              if (d.body_text) textArea.value = d.body_text;
              if (d.body_html) htmlArea.innerHTML = d.body_html;
              setMode(d.mode === 'text' ? 'text' : 'html');
            });
          }
        }
      } catch (e) {}
    }

    // Par défaut, on ouvre directement le mode HTML enrichi (plus pratique
    // pour insérer images / mise en forme). L'utilisateur peut basculer en
    // mode "Texte" via le toggle s'il préfère.
    setMode('html');

    // Focus initial
    setTimeout(() => {
      if (!opts.prefilledTo) chipsTo.focus();
      else if (!opts.prefilledSubject) overlay.querySelector('#cmp-subject').focus();
      else (mode === 'html' ? htmlArea : textArea).focus();
    }, 50);

    // Envoi
    const sendBtn = overlay.querySelector('#cmp-send');
    sendBtn.onclick = async () => {
      const status = overlay.querySelector('#cmp-status');
      // Commit toute saisie en attente dans les chips
      chipsTo.commitPending(); chipsCc.commitPending(); chipsBcc.commitPending();
      const account_id = overlay.querySelector('#cmp-from').value;
      const toList = chipsTo.getValues();
      const ccList = chipsCc.getValues();
      const bccList = chipsBcc.getValues();
      const to = toList.join(', ');
      const subj = overlay.querySelector('#cmp-subject').value.trim();
      let body = '', body_html = '';
      if (mode === 'html') {
        // Avant d'envoyer, convertit les <img data-cid="X" src="data:..."> en
        // <img src="cid:X"> pour que le backend les attache en multipart/related.
        // L'aperçu côté composer reste lisible (data-url), mais le mail envoyé
        // utilise des références CID propres.
        const clone = htmlArea.cloneNode(true);
        clone.querySelectorAll('img[data-cid]').forEach(img => {
          const cid = img.getAttribute('data-cid');
          img.setAttribute('src', `cid:${cid}`);
          img.removeAttribute('data-cid');
        });
        body_html = clone.innerHTML.trim();
        // Génère un fallback texte
        body = htmlArea.innerText.trim();
      } else {
        body = textArea.value;
      }
      if (!toList.length || !subj || (!body.trim() && !body_html)) {
        status.textContent = '✗ Au moins un destinataire, l\'objet et le message sont requis.';
        status.className = 'text-xs text-danger';
        return;
      }
      // Validation emails (To + Cc + Bcc)
      const allAddrs = [...toList, ...ccList, ...bccList];
      const badAddr = allAddrs.find(a => !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(a));
      if (badAddr) {
        status.textContent = `✗ Adresse invalide : ${badAddr}`;
        status.className = 'text-xs text-danger';
        return;
      }
      // Filtre les images inline qui ne sont plus référencées dans le body
      // (l'utilisateur a peut-être supprimé l'<img> sans qu'on s'en rende compte)
      const referencedCids = new Set();
      (body_html.match(/cid:([a-zA-Z0-9_]+)/g) || []).forEach(m => {
        referencedCids.add(m.slice(4));
      });
      const cleanAttachments = attachments.filter(a => !a.inline || referencedCids.has(a.cid));
      // Vérification taille totale
      const totBytes = cleanAttachments.reduce((s, a) => s + (a.size || 0), 0);
      if (totBytes > MAX_TOTAL_BYTES) {
        status.textContent = `✗ Pièces jointes trop lourdes (${fmtSize(totBytes)}). Limite : 22 Mo.`;
        status.className = 'text-xs text-danger';
        return;
      }
      sendBtn.disabled = true;
      sendBtn.innerHTML = '<svg class="w-4 h-4 mr-1.5 inline animate-spin" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M21 12a9 9 0 11-9-9"/></svg>Envoi…';
      status.textContent = '';
      try {
        const r = await App.api.mail_send({
          account_id, to, cc: ccList, bcc: bccList,
          subject: subj, body, body_html,
          in_reply_to: opts.inReplyTo || '',
          attachments: cleanAttachments.map(a => ({
            filename: a.filename,
            content_b64: a.content_b64,
            content_type: a.content_type,
            inline: !!a.inline,
            cid: a.cid || '',
          })),
        });
        if (r && r.ok) {
          status.textContent = '✓ Envoyé !';
          status.className = 'text-xs text-success';
          sendBtn.innerHTML = '✓ Envoyé';
          // Le brouillon n'a plus de raison d'être après envoi
          try { localStorage.removeItem('tc-mail-draft'); } catch (e) {}
          setTimeout(() => { close(); this._load(); }, 1200);
        } else {
          status.textContent = `✗ ${(r && r.error) || 'Erreur inconnue'}`;
          status.className = 'text-xs text-danger';
          sendBtn.disabled = false;
          sendBtn.innerHTML = '<svg class="w-4 h-4 mr-1.5 inline" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><path d="M2 21l21-9-21-9v7l15 2-15 2z"/></svg>Envoyer';
        }
      } catch (e) {
        status.textContent = `✗ ${e}`;
        status.className = 'text-xs text-danger';
        sendBtn.disabled = false;
        sendBtn.innerHTML = '<svg class="w-4 h-4 mr-1.5 inline" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><path d="M2 21l21-9-21-9v7l15 2-15 2z"/></svg>Envoyer';
      }
    };
  },

  /** Workflow Prospection en direct :
   *  1. Choix Célébrité / Entreprise
   *  2. Saisie URL du site cible
   *  3. Claude analyse + génère le mail
   *  4. Ouvre le composer pré-rempli */
  _openProspectFlow() {
    const ov = document.createElement('div');
    ov.className = 'fixed inset-0 z-[210] flex items-center justify-center p-4';
    ov.style.background = 'rgba(15,23,42,0.78)';
    ov.style.backdropFilter = 'blur(10px)';
    let step = 'category'; // 'category' | 'url' | 'loading'
    let chosenCategory = null;

    const render = () => {
      if (step === 'category') {
        ov.innerHTML = `
          <div class="bg-surface rounded-2xl shadow-hero w-full max-w-lg border border-border animate-slide-up overflow-hidden">
            <div class="px-6 pt-5 pb-4 flex items-start justify-between border-b border-border bg-surface-elevated">
              <div>
                <div class="text-[10px] font-bold uppercase tracking-widest text-text-muted mb-0.5">PROSPECTION EN DIRECT</div>
                <h3 class="text-lg font-bold">Quel type de cible ?</h3>
                <p class="text-xs text-text-muted mt-1">Claude adaptera le ton, les arguments et le modèle utilisé selon le type de personne ou d'entreprise.</p>
              </div>
              <button id="pf-close" class="w-8 h-8 rounded-lg flex items-center justify-center text-text-muted hover:text-text hover:bg-bg text-xl leading-none shrink-0">×</button>
            </div>
            <div class="p-5 grid grid-cols-2 gap-3">
              <button data-cat="celebrity"
                      class="text-left p-5 rounded-2xl border-2 border-border hover:border-accent hover:bg-accent/5 transition-all">
                <div class="text-3xl mb-2">⭐</div>
                <div class="text-base font-bold text-text">Célébrités</div>
                <div class="text-xs text-text-muted mt-1 leading-snug">Artistes, sportifs, créateurs, influenceurs. Ton respectueux et admirateur. Focus sur leur travail et leurs projets.</div>
              </button>
              <button data-cat="business"
                      class="text-left p-5 rounded-2xl border-2 border-border hover:border-accent hover:bg-accent/5 transition-all">
                <div class="text-3xl mb-2">🏢</div>
                <div class="text-base font-bold text-text">Autres (entreprises)</div>
                <div class="text-xs text-text-muted mt-1 leading-snug">Commerces, cabinets, restaurants, artisans. Ton commercial et concret. Focus sur leurs services et leur secteur.</div>
              </button>
            </div>
          </div>
        `;
        ov.querySelector('#pf-close').onclick = close;
        ov.querySelectorAll('[data-cat]').forEach(b => {
          b.onclick = () => {
            chosenCategory = b.dataset.cat;
            step = 'url';
            render();
          };
        });
      } else if (step === 'url') {
        const catLabel = chosenCategory === 'celebrity' ? 'Célébrité' : 'Entreprise';
        const catIcon = chosenCategory === 'celebrity' ? '⭐' : '🏢';
        ov.innerHTML = `
          <div class="bg-surface rounded-2xl shadow-hero w-full max-w-lg border border-border animate-slide-up overflow-hidden">
            <div class="px-6 pt-5 pb-4 flex items-start justify-between border-b border-border bg-surface-elevated">
              <div>
                <div class="text-[10px] font-bold uppercase tracking-widest text-text-muted mb-0.5">PROSPECTION ${catLabel.toUpperCase()}</div>
                <h3 class="text-lg font-bold">${catIcon} URL du site à analyser</h3>
                <p class="text-xs text-text-muted mt-1">Colle l'adresse du site officiel ou de la page web. Claude va l'analyser et générer un mail personnalisé.</p>
              </div>
              <button id="pf-close" class="w-8 h-8 rounded-lg flex items-center justify-center text-text-muted hover:text-text hover:bg-bg text-xl leading-none shrink-0">×</button>
            </div>
            <div class="p-5 space-y-3">
              <input id="pf-url" type="url" placeholder="https://www.exemple.com"
                     class="w-full px-3 py-3 text-sm rounded-lg bg-bg border border-border focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent"/>
              <div id="pf-url-error" class="text-xs text-danger min-h-[1rem]"></div>
            </div>
            <div class="px-5 py-4 border-t border-border bg-surface-elevated flex items-center justify-between gap-2">
              <button id="pf-back" class="text-xs text-text-muted hover:text-text">← Changer de catégorie</button>
              <div class="flex items-center gap-2">
                <button id="pf-cancel" class="btn btn-secondary">Annuler</button>
                <button id="pf-go" class="btn btn-primary">
                  <svg class="w-4 h-4 mr-1.5 inline" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>
                  Générer le mail
                </button>
              </div>
            </div>
          </div>
        `;
        ov.querySelector('#pf-close').onclick = close;
        ov.querySelector('#pf-cancel').onclick = close;
        ov.querySelector('#pf-back').onclick = () => { step = 'category'; render(); };
        const urlInput = ov.querySelector('#pf-url');
        setTimeout(() => urlInput.focus(), 50);
        urlInput.addEventListener('keydown', (e) => {
          if (e.key === 'Enter') { e.preventDefault(); ov.querySelector('#pf-go').click(); }
        });
        ov.querySelector('#pf-go').onclick = async () => {
          const errEl = ov.querySelector('#pf-url-error');
          let url = urlInput.value.trim();
          if (!url) { errEl.textContent = '✗ URL manquante.'; return; }
          // Auto-ajout https:// si absent
          if (!/^https?:\/\//i.test(url)) url = 'https://' + url;
          try { new URL(url); } catch { errEl.textContent = '✗ URL invalide.'; return; }
          errEl.textContent = '';
          step = 'loading';
          render();
          try {
            const r = await App.api.prospect_generate_mail({
              url, category: chosenCategory,
            });
            if (r && r.ok) {
              close();
              this._openComposer({
                prefilledSubject: r.subject || '',
                prefilledBodyHtml: r.body_html || '',
                title: `Prospection : ${r.target_name || url}`,
              });
            } else {
              step = 'url';
              render();
              setTimeout(() => {
                const e2 = ov.querySelector('#pf-url-error');
                if (e2) e2.textContent = `✗ ${(r && r.error) || 'Erreur lors de la génération.'}`;
                const u2 = ov.querySelector('#pf-url');
                if (u2) u2.value = url;
              }, 50);
            }
          } catch (e) {
            step = 'url';
            render();
            setTimeout(() => {
              const e2 = ov.querySelector('#pf-url-error');
              if (e2) e2.textContent = `✗ ${e.message || e}`;
              const u2 = ov.querySelector('#pf-url');
              if (u2) u2.value = url;
            }, 50);
          }
        };
      } else if (step === 'loading') {
        ov.innerHTML = `
          <div class="bg-surface rounded-2xl shadow-hero w-full max-w-lg border border-border animate-slide-up overflow-hidden">
            <div class="p-12 text-center">
              <div class="w-16 h-16 mx-auto mb-5 rounded-2xl flex items-center justify-center"
                   style="background: linear-gradient(135deg, #7c6acc, #e85d2c);">
                <svg class="w-8 h-8 text-white animate-spin" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                  <path d="M21 12a9 9 0 11-9-9"/>
                </svg>
              </div>
              <div class="text-base font-bold text-text mb-1">Claude analyse le site…</div>
              <div class="text-xs text-text-muted">Récupération du contenu, choix du modèle, personnalisation du mail. Compte 15-30 secondes.</div>
            </div>
          </div>
        `;
      }
    };

    const close = () => {
      document.removeEventListener('keydown', escListener);
      ov.remove();
    };
    const escListener = (e) => { if (e.key === 'Escape' && step !== 'loading') close(); };
    document.addEventListener('keydown', escListener);
    ov.addEventListener('click', (e) => { if (e.target === ov && step !== 'loading') close(); });

    render();
    document.body.appendChild(ov);
  },

  /** Affiche un bandeau "Brouillon trouvé" en haut du composer.
   *  onRestore : callback appelée si l'utilisateur clique "Restaurer". */
  _showDraftRestoreBanner(overlay, draft, onRestore) {
    const scrollContainer = overlay.querySelector('.flex-1.overflow-y-auto');
    if (!scrollContainer) return;
    const banner = document.createElement('div');
    banner.className = 'mb-3 p-3 rounded-xl border border-accent/40 bg-accent/10 flex items-start gap-3';
    const ago = (() => {
      const min = Math.floor((Date.now() - (draft.ts || Date.now())) / 60_000);
      if (min < 1) return 'à l\'instant';
      if (min < 60) return `il y a ${min} min`;
      const h = Math.floor(min / 60);
      if (h < 24) return `il y a ${h} h`;
      return `il y a ${Math.floor(h / 24)} j`;
    })();
    const preview = (draft.subject || draft.to || '(sans objet)').slice(0, 60);
    banner.innerHTML = `
      <svg class="w-5 h-5 text-accent shrink-0 mt-0.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
        <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/>
        <polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/>
      </svg>
      <div class="flex-1 min-w-0">
        <div class="text-sm font-semibold text-text">Brouillon trouvé (${ago})</div>
        <div class="text-xs text-text-muted truncate">${this._escape(preview)}</div>
      </div>
      <div class="flex items-center gap-2 shrink-0">
        <button type="button" data-draft-restore class="text-xs font-semibold text-accent hover:underline">Restaurer</button>
        <button type="button" data-draft-discard class="text-xs text-text-muted hover:text-danger">Ignorer</button>
      </div>
    `;
    scrollContainer.insertBefore(banner, scrollContainer.firstChild);
    banner.querySelector('[data-draft-restore]').onclick = () => {
      try { onRestore && onRestore(); } catch (e) { console.error('draft restore', e); }
      banner.remove();
    };
    banner.querySelector('[data-draft-discard]').onclick = () => {
      try { localStorage.removeItem('tc-mail-draft'); } catch (e) {}
      banner.remove();
    };
  },

  /** Modale "Envoyer plus tard" : choix date/heure + raccourcis rapides.
   *  Appelle onConfirm(scheduledAtISO, prettyDate) si l'utilisateur valide. */
  _openScheduleDialog(onConfirm) {
    // Helpers de date — toutes en heure locale
    const pad = (n) => String(n).padStart(2, '0');
    const isoFromDate = (d) => `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
    const prettyFR = (d) => {
      const days = ['dimanche','lundi','mardi','mercredi','jeudi','vendredi','samedi'];
      const months = ['janv.','févr.','mars','avr.','mai','juin','juil.','août','sept.','oct.','nov.','déc.'];
      return `${days[d.getDay()]} ${d.getDate()} ${months[d.getMonth()]} à ${pad(d.getHours())}h${pad(d.getMinutes())}`;
    };

    const now = new Date();
    // Raccourcis : Dans 1h / Ce soir 18h / Demain 9h / Lundi 9h
    const in1h = new Date(now.getTime() + 60*60*1000);
    const tonight = new Date(now); tonight.setHours(18, 0, 0, 0);
    if (tonight <= now) tonight.setDate(tonight.getDate() + 1);
    const tomorrow9 = new Date(now); tomorrow9.setDate(tomorrow9.getDate() + 1); tomorrow9.setHours(9, 0, 0, 0);
    // Lundi prochain à 9h : si on est lundi, on prend lundi prochain (J+7)
    const nextMonday = new Date(now);
    const dow = nextMonday.getDay(); // 0=dim, 1=lun
    const daysToMonday = ((1 - dow + 7) % 7) || 7;
    nextMonday.setDate(nextMonday.getDate() + daysToMonday);
    nextMonday.setHours(9, 0, 0, 0);

    const presets = [
      { label: 'Dans 1 heure',   date: in1h,        kicker: prettyFR(in1h) },
      { label: 'Ce soir 18 h',   date: tonight,     kicker: prettyFR(tonight) },
      { label: 'Demain 9 h',     date: tomorrow9,   kicker: prettyFR(tomorrow9) },
      { label: 'Lundi 9 h',      date: nextMonday,  kicker: prettyFR(nextMonday) },
    ];

    // Valeur initiale du datetime-local : "demain à 9h"
    const defaultDt = isoFromDate(tomorrow9);

    const ov = document.createElement('div');
    ov.className = 'fixed inset-0 z-[230] flex items-center justify-center p-4';
    ov.style.background = 'rgba(15,23,42,0.75)';
    ov.style.backdropFilter = 'blur(8px)';
    ov.innerHTML = `
      <div class="bg-surface rounded-2xl shadow-hero w-full max-w-md border border-border animate-slide-up flex flex-col overflow-hidden">
        <div class="px-5 pt-4 pb-3 border-b border-border bg-surface-elevated">
          <div class="text-[10px] font-bold uppercase tracking-widest text-text-muted mb-0.5">PROGRAMMER L'ENVOI</div>
          <h3 class="text-base font-bold">Quand envoyer ce mail ?</h3>
          <p class="text-xs text-text-muted mt-1">Le mail partira automatiquement à l'heure choisie, même si tu fermes l'app.</p>
        </div>
        <div class="p-4 space-y-3">
          <!-- Raccourcis -->
          <div class="grid grid-cols-2 gap-2">
            ${presets.map((p, i) => `
              <button data-preset="${i}" type="button"
                      class="text-left px-3 py-2.5 rounded-xl border border-border hover:border-accent hover:bg-accent/5 transition-colors">
                <div class="text-sm font-semibold text-text">${p.label}</div>
                <div class="text-[10px] text-text-muted mt-0.5">${p.kicker}</div>
              </button>
            `).join('')}
          </div>
          <!-- Sélecteur custom -->
          <div class="pt-2 border-t border-border">
            <label class="block text-[11px] font-medium text-text-secondary mb-1 uppercase tracking-wider">Ou choisis une date / heure</label>
            <input id="sched-dt" type="datetime-local" value="${defaultDt}"
                   class="w-full px-3 py-2.5 text-sm rounded-lg bg-bg border border-border focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent"/>
            <div id="sched-preview" class="text-[11px] text-text-muted mt-1.5"></div>
          </div>
        </div>
        <div class="px-5 py-4 border-t border-border bg-surface-elevated flex items-center justify-end gap-2">
          <button id="sched-cancel" type="button" class="btn btn-secondary">Annuler</button>
          <button id="sched-confirm" type="button" class="btn btn-primary">
            <svg class="w-4 h-4 mr-1.5 inline" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
            Programmer
          </button>
        </div>
      </div>
    `;
    document.body.appendChild(ov);

    const close = () => {
      document.removeEventListener('keydown', escListener);
      ov.remove();
    };
    const escListener = (e) => { if (e.key === 'Escape') close(); };
    document.addEventListener('keydown', escListener);
    ov.querySelector('#sched-cancel').onclick = close;
    ov.addEventListener('click', (e) => { if (e.target === ov) close(); });

    const dtInput = ov.querySelector('#sched-dt');
    const previewEl = ov.querySelector('#sched-preview');
    const updatePreview = () => {
      try {
        const v = dtInput.value;
        if (!v) { previewEl.textContent = ''; return; }
        const d = new Date(v);
        if (isNaN(d.getTime())) { previewEl.textContent = ''; return; }
        if (d <= new Date()) {
          previewEl.textContent = '⚠ Cette date est passée. Choisis un moment dans le futur.';
          previewEl.className = 'text-[11px] text-danger mt-1.5';
        } else {
          previewEl.textContent = `→ ${prettyFR(d)}`;
          previewEl.className = 'text-[11px] text-success mt-1.5';
        }
      } catch (e) {}
    };
    dtInput.addEventListener('input', updatePreview);
    updatePreview();

    // Raccourcis : pré-remplit le datetime-local
    ov.querySelectorAll('[data-preset]').forEach(btn => {
      btn.onclick = () => {
        const idx = parseInt(btn.dataset.preset, 10);
        dtInput.value = isoFromDate(presets[idx].date);
        updatePreview();
      };
    });

    ov.querySelector('#sched-confirm').onclick = () => {
      const v = dtInput.value;
      if (!v) return;
      const d = new Date(v);
      if (isNaN(d.getTime()) || d <= new Date()) {
        previewEl.textContent = '⚠ Date invalide ou déjà passée.';
        previewEl.className = 'text-[11px] text-danger mt-1.5';
        return;
      }
      close();
      try { onConfirm(d.toISOString(), prettyFR(d)); }
      catch (e) { console.error('schedule onConfirm', e); }
    };
  },

  /** Ouvre une modale pour rendre une image cliquable (lien URL).
   *  Si elle est déjà entourée d'un <a>, pré-remplit l'URL existante. */
  _openImageLinkDialog(img) {
    const existingLink = img.parentElement && img.parentElement.tagName === 'A'
      ? img.parentElement : null;
    const currentUrl = existingLink ? existingLink.getAttribute('href') || '' : '';

    const ov = document.createElement('div');
    ov.className = 'fixed inset-0 z-[230] flex items-center justify-center p-4';
    ov.style.background = 'rgba(15,23,42,0.75)';
    ov.style.backdropFilter = 'blur(8px)';
    ov.innerHTML = `
      <div class="bg-surface rounded-2xl shadow-hero w-full max-w-md border border-border animate-slide-up flex flex-col overflow-hidden">
        <div class="px-5 pt-4 pb-3 border-b border-border bg-surface-elevated">
          <div class="text-[10px] font-bold uppercase tracking-widest text-text-muted mb-0.5">IMAGE</div>
          <h3 class="text-base font-bold">${existingLink ? 'Modifier le lien' : 'Rendre l\'image cliquable'}</h3>
          <p class="text-xs text-text-muted mt-1">Quand le destinataire cliquera sur l'image, il sera redirigé vers l'URL ci-dessous.</p>
        </div>
        <div class="p-5 space-y-3">
          <div>
            <label class="block text-[11px] font-medium text-text-secondary mb-1 uppercase tracking-wider">URL de destination</label>
            <input id="img-link-url" type="url" value="${this._escape(currentUrl)}"
                   placeholder="https://triskell-studio.fr"
                   class="w-full px-3 py-2.5 text-sm rounded-lg bg-bg border border-border focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent"/>
            <div class="text-[10px] text-text-muted mt-1">Laisse vide et clique "Enregistrer" pour retirer le lien.</div>
          </div>
        </div>
        <div class="px-5 py-4 border-t border-border bg-surface-elevated flex items-center justify-between gap-2">
          ${existingLink
            ? '<button id="img-link-remove" type="button" class="text-xs text-danger hover:underline">Retirer le lien</button>'
            : '<div></div>'}
          <div class="flex items-center gap-2">
            <button id="img-link-cancel" type="button" class="btn btn-secondary">Annuler</button>
            <button id="img-link-save" type="button" class="btn btn-primary">Enregistrer</button>
          </div>
        </div>
      </div>
    `;
    document.body.appendChild(ov);

    const close = () => {
      document.removeEventListener('keydown', escListener);
      ov.remove();
    };
    const escListener = (e) => { if (e.key === 'Escape') close(); };
    document.addEventListener('keydown', escListener);

    ov.querySelector('#img-link-cancel').onclick = close;
    ov.addEventListener('click', (e) => { if (e.target === ov) close(); });

    const urlInput = ov.querySelector('#img-link-url');
    setTimeout(() => { urlInput.focus(); urlInput.select(); }, 50);
    urlInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        ov.querySelector('#img-link-save').click();
      }
    });

    const wrapImageInLink = (url) => {
      const a = document.createElement('a');
      a.setAttribute('href', url);
      a.setAttribute('target', '_blank');
      a.setAttribute('rel', 'noopener noreferrer');
      img.parentNode.insertBefore(a, img);
      a.appendChild(img);
    };
    const unwrapImageFromLink = () => {
      if (!existingLink) return;
      existingLink.parentNode.insertBefore(img, existingLink);
      existingLink.remove();
    };

    ov.querySelector('#img-link-save').onclick = () => {
      let url = urlInput.value.trim();
      if (!url) {
        // URL vide → retire le lien si présent
        unwrapImageFromLink();
        img.style.cursor = '';
        img.removeAttribute('title');
        close();
        return;
      }
      // Auto-ajout https:// si l'utilisateur n'a pas mis de protocole
      if (!/^[a-z][a-z0-9+.-]*:/i.test(url)) {
        url = 'https://' + url;
      }
      if (existingLink) {
        existingLink.setAttribute('href', url);
        existingLink.setAttribute('target', '_blank');
        existingLink.setAttribute('rel', 'noopener noreferrer');
      } else {
        wrapImageInLink(url);
      }
      img.title = `Lien vers ${url}`;
      close();
    };

    const removeBtn = ov.querySelector('#img-link-remove');
    if (removeBtn) {
      removeBtn.onclick = () => {
        unwrapImageFromLink();
        img.style.cursor = '';
        img.removeAttribute('title');
        close();
      };
    }
  },

  _noBackend() {
    return `
      <div class="card p-8 text-center">
        <div class="text-3xl mb-3 opacity-60">⏻</div>
        <h2 class="text-lg font-bold mb-2">Backend non disponible.</h2>
        <p class="text-text-muted text-sm">Lance Triskell Command via <code class="text-xs px-1.5 py-0.5 rounded bg-bg">python run_web.py</code>.</p>
      </div>
    `;
  },

  _escape(s) {
    return String(s ?? '')
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  },

  _fmtDate(iso) {
    if (!iso) return '—';
    try {
      const d = new Date(iso);
      return d.toLocaleString('fr-FR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
    } catch { return iso.slice(0, 16); }
  },
};
