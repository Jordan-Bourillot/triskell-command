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
                <label class="block text-[11px] font-medium text-text-secondary mb-1">Sujet</label>
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
            <div class="hero-kicker mb-0.5">TEMPLATES MAIL</div>
            <h3 class="text-base font-bold">Tes modèles HTML réutilisables</h3>
          </div>
          <button id="tm-close" class="w-8 h-8 rounded-lg flex items-center justify-center text-text-muted hover:text-text hover:bg-bg transition-colors text-xl leading-none">×</button>
        </div>
        <div id="tm-list" class="flex-1 overflow-y-auto p-4 space-y-2"></div>
        <div class="px-6 py-3 border-t border-border bg-surface-elevated text-[11px] text-text-muted">
          Pour créer un nouveau template : ouvre un mail dans le composer, écris ton HTML, clique sur "Templates ▾ → Sauvegarder le contenu actuel comme template".
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
            Aucun template enregistré.
          </div>`;
        return;
      }
      listEl.innerHTML = tpls.map(t => `
        <div class="card p-4">
          <div class="flex items-start justify-between gap-3 mb-2">
            <div class="flex-1 min-w-0">
              <div class="text-sm font-bold text-text truncate">${this._escape(t.name)}</div>
              ${t.subject_default ? `<div class="text-[11px] text-text-muted truncate">Sujet par défaut : ${this._escape(t.subject_default)}</div>` : ''}
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
          if (!confirm(`Supprimer le template "${tpl && tpl.name}" ?`)) return;
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
              <label class="block text-[11px] font-medium text-text-secondary mb-1">Destinataire</label>
              <input id="cmp-to" type="email" value="${this._escape(opts.prefilledTo || '')}" placeholder="email@exemple.fr"
                     class="w-full px-3 py-2.5 text-sm rounded-lg bg-bg border border-border focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent"/>
            </div>
          </div>

          <!-- Sujet -->
          <div>
            <label class="block text-[11px] font-medium text-text-secondary mb-1">Sujet</label>
            <input id="cmp-subject" type="text" value="${this._escape(opts.prefilledSubject || '')}" placeholder="Sujet du mail"
                   class="w-full px-3 py-2.5 text-sm rounded-lg bg-bg border border-border focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent"/>
          </div>

          <!-- Toggle Texte / HTML + bouton Templates + Signature -->
          <div>
            <div class="flex items-center justify-between mb-1 gap-2 flex-wrap">
              <label class="block text-[11px] font-medium text-text-secondary">Message</label>
              <div class="flex items-center gap-2 text-[11px] flex-wrap">
                <!-- Dropdown signatures -->
                <div class="flex items-center gap-1.5 shrink-0">
                  <svg class="w-3.5 h-3.5 text-text-muted shrink-0" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M20 14.66V20a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h5.34"/><polygon points="18 2 22 6 12 16 8 16 8 12 18 2"/></svg>
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
                    Templates ▾
                  </button>
                  <div id="cmp-tpl-menu" class="hidden absolute right-0 top-full mt-1 w-72 rounded-xl border border-border bg-surface shadow-lift z-30 max-h-80 overflow-y-auto">
                    <div id="cmp-tpl-list" class="py-1"></div>
                    <div class="border-t border-border py-1">
                      <button id="cmp-tpl-save" class="w-full px-4 py-2 text-left text-xs hover:bg-bg flex items-center gap-2 text-accent font-semibold">
                        <span>+</span> Sauvegarder le contenu actuel comme template
                      </button>
                      <button id="cmp-tpl-manage" class="w-full px-4 py-2 text-left text-xs hover:bg-bg flex items-center gap-2 text-text-muted">
                        <span>⚙</span> Gérer mes templates…
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

          <div id="cmp-status" class="text-xs text-text-muted"></div>
        </div>

        <!-- Footer sticky -->
        <div class="px-6 py-4 border-t border-border bg-surface-elevated flex items-center justify-end gap-2 shrink-0">
          <button id="cmp-cancel" class="btn btn-secondary">Annuler</button>
          <button id="cmp-send" class="btn btn-primary">
            <svg class="w-4 h-4 mr-1.5 inline" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><path d="M2 21l21-9-21-9v7l15 2-15 2z"/></svg>
            Envoyer
          </button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);

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
      `;
      document.head.appendChild(s);
    }

    const close = () => overlay.remove();
    overlay.querySelector('#cmp-close').onclick = close;
    overlay.querySelector('#cmp-cancel').onclick = close;
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
    const escListener = (e) => { if (e.key === 'Escape') { close(); document.removeEventListener('keydown', escListener); } };
    document.addEventListener('keydown', escListener);

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

    // Boutons toolbar HTML
    toolbar.querySelectorAll('[data-cmd]').forEach(btn => {
      btn.onclick = (e) => {
        e.preventDefault();
        const cmd = btn.dataset.cmd;
        htmlArea.focus();
        if (cmd === 'createLink') {
          const url = prompt('URL du lien :', 'https://');
          if (url) document.execCommand('createLink', false, url);
        } else if (cmd === 'paste-html') {
          this._openPasteHtmlDialog(htmlArea);
        } else if (cmd === 'preview') {
          const subj = (overlay.querySelector('#cmp-subject').value || '').trim();
          const fromSel = overlay.querySelector('#cmp-from');
          const fromLabel = fromSel.options[fromSel.selectedIndex]?.text || '';
          const to = (overlay.querySelector('#cmp-to').value || '').trim();
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
        tplList.innerHTML = '<div class="px-4 py-3 text-xs text-text-muted">Aucun template encore. Sauvegarde ton contenu actuel ci-dessous.</div>';
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
      const name = prompt('Nom du template (ex: "Devis envoyé", "Suivi 1 mois") :');
      if (!name) return;
      const useSubject = subjectInput.value.trim();
      const wantSubj = useSubject && confirm(`Sauvegarder aussi le sujet "${useSubject}" comme sujet par défaut du template ?`);
      const r = await App.api.mail_template_save({
        template: { name, body_html: htmlContent, subject_default: wantSubj ? useSubject : '' }
      });
      if (r && r.ok) {
        tplMenu.classList.add('hidden');
        // Petite confirmation visuelle
        const status = overlay.querySelector('#cmp-status');
        status.textContent = `✓ Template "${name}" sauvegardé.`;
        status.className = 'text-xs text-success';
        setTimeout(() => { if (status.textContent.startsWith('✓ Template')) status.textContent = ''; }, 3000);
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

    // Focus initial
    setTimeout(() => {
      if (!opts.prefilledTo) overlay.querySelector('#cmp-to').focus();
      else if (!opts.prefilledSubject) overlay.querySelector('#cmp-subject').focus();
      else textArea.focus();
    }, 50);

    // Envoi
    const sendBtn = overlay.querySelector('#cmp-send');
    sendBtn.onclick = async () => {
      const status = overlay.querySelector('#cmp-status');
      const account_id = overlay.querySelector('#cmp-from').value;
      const to = overlay.querySelector('#cmp-to').value.trim();
      const subj = overlay.querySelector('#cmp-subject').value.trim();
      let body = '', body_html = '';
      if (mode === 'html') {
        body_html = htmlArea.innerHTML.trim();
        // Génère un fallback texte
        body = htmlArea.innerText.trim();
      } else {
        body = textArea.value;
      }
      if (!to || !subj || (!body.trim() && !body_html)) {
        status.textContent = '✗ Destinataire, sujet et message requis.';
        status.className = 'text-xs text-danger';
        return;
      }
      sendBtn.disabled = true;
      sendBtn.innerHTML = '<svg class="w-4 h-4 mr-1.5 inline animate-spin" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M21 12a9 9 0 11-9-9"/></svg>Envoi…';
      status.textContent = '';
      try {
        const r = await App.api.mail_send({
          account_id, to, subject: subj, body, body_html,
          in_reply_to: opts.inReplyTo || '',
        });
        if (r && r.ok) {
          status.textContent = '✓ Envoyé !';
          status.className = 'text-xs text-success';
          sendBtn.innerHTML = '✓ Envoyé';
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
