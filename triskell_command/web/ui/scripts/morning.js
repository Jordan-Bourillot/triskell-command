/* Vue Matinale — Apple-clear.
 *
 * Hero hello + date, UNE priorité du jour mise en avant, 3 KPIs hier,
 * 2 KPIs aujourd'hui, et un bloc "À corriger" qui apparaît seulement
 * s'il y a vraiment quelque chose.
 */

const Morning = {
  async render(container) {
    // 1. Render shell instantané (hero) pour ne pas attendre l'API
    const greeting = App.greeting();
    const dateStr = App.formatDateFr();
    // Lit le prénom depuis App.currentUser (rempli au boot par Onboarding)
    // ou via API en fallback ; vide = on n'affiche pas de prénom
    let userName = (App.currentUser && App.currentUser.first_name) || '';
    if (!userName && App.api) {
      try { userName = await App.api.get_user_name(); } catch (e) {}
    }
    const greetingFull = userName ? `${greeting} ${userName}.` : `${greeting}.`;

    container.innerHTML = `
      <section class="animate-slide-up max-w-[1100px]">
        <!-- Hero -->
        <div class="mb-12">
          <div class="flex items-start justify-between gap-3">
            <div>
              <div class="hero-kicker mb-2">${dateStr.toUpperCase()}</div>
              <h1 class="hero-title mb-3">${greetingFull}</h1>
              <p class="hero-subtitle">Voilà ce qui t'attend aujourd'hui.</p>
            </div>
            ${Help.button('morning')}
          </div>
          <div class="flex flex-wrap gap-3 mt-6">
            <button id="m-refresh" class="btn btn-secondary">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M3 12a9 9 0 0114-7.4M21 12a9 9 0 01-14 7.4"/><path d="M21 4v5h-5M3 20v-5h5"/></svg>
              Rafraîchir
            </button>
            <button id="m-ask-claude" class="btn btn-secondary">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M12 2l1.5 4.5L18 8l-4.5 1.5L12 14l-1.5-4.5L6 8l4.5-1.5L12 2z"/></svg>
              Demander conseil à Claude
            </button>
            <button id="m-open-teddy" class="btn btn-secondary" title="Ouvre Teddy Mail">
              <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="6.5" cy="6.5" r="2.5"/>
                <circle cx="17.5" cy="6.5" r="2.5"/>
                <path d="M4 14a8 8 0 0116 0v3a4 4 0 01-4 4H8a4 4 0 01-4-4v-3z"/>
                <circle cx="9" cy="14" r="0.8" fill="currentColor"/>
                <circle cx="15" cy="14" r="0.8" fill="currentColor"/>
              </svg>
              Ouvrir Teddy Mail
            </button>
            <button id="m-compose-mail" class="btn btn-secondary" title="Composer (Ctrl+Shift+M)">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24" stroke-linecap="round" stroke-linejoin="round">
                <path d="M12 20h9"/>
                <path d="M16.5 3.5a2.121 2.121 0 113 3L7 19l-4 1 1-4L16.5 3.5z"/>
              </svg>
              Composer un mail
            </button>
          </div>
        </div>

        <div id="m-content" class="space-y-12"></div>
      </section>
    `;

    document.getElementById('m-refresh').onclick = () => this.render(container);
    document.getElementById('m-ask-claude').onclick = () => Claude.open();
    document.getElementById('m-open-teddy').onclick = () => Teddy.open();
    document.getElementById('m-compose-mail').onclick = () => Teddy.compose();

    // 2. Charge le digest et hydrate
    const slot = document.getElementById('m-content');
    if (!App.api) {
      slot.innerHTML = this._previewPlaceholder();
      return;
    }
    let digest = null;
    try { digest = await App.api.get_morning_digest(); } catch (e) {}

    if (!digest || !digest.ok) {
      slot.innerHTML = `
        <div class="card p-10 text-center">
          <div class="text-3xl mb-3">🔌</div>
          <h2 class="text-xl font-semibold mb-2">Connexion à la base partagée requise</h2>
          <p class="text-text-secondary mb-6 max-w-lg mx-auto">
            Connecte-toi à la base partagée Triskell depuis les Réglages
            pour que cette page se remplisse en temps réel.
          </p>
          <button class="btn btn-primary" onclick="App.show('config')">Aller dans Réglages</button>
        </div>
      `;
      return;
    }

    slot.innerHTML = this._renderPriority(digest)
                   + this._renderYesterday(digest)
                   + this._renderToday(digest)
                   + this._renderIssues(digest)
                   + `<div id="m-linkedin-slot"></div>`;

    // Bloc LinkedIn (chargé en différé pour ne pas bloquer la Matinale)
    this._loadLinkedinActions();
  },

  async _loadLinkedinActions() {
    if (!App.api) return;
    let actions = [];
    try {
      const r = await App.api.multichannel_get_actions();
      if (r && r.ok) actions = r.actions || [];
    } catch (e) {}
    const slot = document.getElementById('m-linkedin-slot');
    if (!slot) return;
    if (actions.length === 0) { slot.innerHTML = ''; return; }
    slot.innerHTML = `
      <div>
        <div class="section-label">LinkedIn — relances à faire (${actions.length})</div>
        <div class="card p-5">
          <div class="flex items-start justify-between gap-4 mb-4">
            <p class="text-sm text-text-muted">
              Ces prospects n'ont pas répondu à ton mail. L'IA a préparé un message
              LinkedIn court — 3 clics et c'est envoyé. Si tu as Phantombuster
              configuré, tu peux tout envoyer d'un coup.
            </p>
            <button id="m-li-dispatch-all"
                    class="text-xs px-3 py-1.5 rounded-lg bg-accent text-white hover:bg-accent-hover whitespace-nowrap">
              ⚡ Tout envoyer via Phantombuster
            </button>
          </div>
          <div class="space-y-3" id="m-linkedin-list">
            ${actions.slice(0, 8).map(a => this._linkedinCard(a)).join('')}
          </div>
          ${actions.length > 8
            ? `<div class="text-xs text-text-muted mt-3">+ ${actions.length - 8} autres relances en file.</div>`
            : ''}
        </div>
      </div>
    `;
    this._bindLinkedinActions();
    this._bindDispatchAll();
  },

  _bindDispatchAll() {
    const btn = document.getElementById('m-li-dispatch-all');
    if (!btn) return;
    btn.onclick = async () => {
      if (!App.api) return;
      if (!confirm("Envoyer toutes les relances LinkedIn pending au Phantom configuré ?\n\n" +
                    "Phantombuster va les distribuer sur LinkedIn (rate-limité ~25/jour pour éviter le ban).\n" +
                    "Si tu n'as pas configuré Phantombuster, va dans Réglages d'abord.")) return;
      btn.disabled = true; btn.textContent = 'Envoi…';
      try {
        const r = await App.api.multichannel_dispatch_phantombuster();
        if (r && r.ok) {
          btn.textContent = `✓ ${r.launched} envoyés`;
          if (r.note) alert(r.note);
        } else {
          alert('Échec : ' + ((r && r.error) || 'erreur'));
          btn.disabled = false;
          btn.textContent = '⚡ Tout envoyer via Phantombuster';
        }
      } catch (e) {
        alert('Erreur : ' + e);
        btn.disabled = false;
        btn.textContent = '⚡ Tout envoyer via Phantombuster';
      }
      setTimeout(() => this._loadLinkedinActions(), 1200);
    };
  },

  _linkedinCard(a) {
    const name = a.prospect_name || '(prospect)';
    const meta = [a.prospect_city, a.prospect_industry].filter(Boolean).join(' · ');
    return `
      <article class="border border-border rounded-xl p-4" data-act-id="${this._escAttr(a.id)}">
        <div class="flex items-start justify-between gap-3 mb-2">
          <div>
            <div class="font-semibold text-sm">${this._escHtml(name)}</div>
            ${meta ? `<div class="text-[11px] text-text-muted">${this._escHtml(meta)}</div>` : ''}
          </div>
          <button class="text-text-muted hover:text-danger text-xl leading-none px-1" data-li-discard
                  title="Supprimer cette suggestion">×</button>
        </div>
        <pre class="whitespace-pre-wrap font-sans text-sm text-text-secondary
                    bg-bg/50 border border-border rounded-lg p-3 mb-3 leading-relaxed">${this._escHtml(a.message || '')}</pre>
        <div class="flex flex-wrap gap-2">
          <button class="text-xs px-2.5 py-1.5 rounded-lg bg-accent/10 text-accent border border-accent/30 hover:bg-accent/20"
                  data-li-copy>📋 Copier le message</button>
          <a href="${this._escAttr(a.search_url || '#')}" target="_blank"
             class="text-xs px-2.5 py-1.5 rounded-lg bg-surface-elevated border border-border hover:border-accent text-text-secondary hover:text-text">
            🔍 Trouver son LinkedIn
          </a>
          ${a.platform_url ? `
            <a href="${this._escAttr(a.platform_url)}" target="_blank"
               class="text-xs px-2.5 py-1.5 rounded-lg bg-surface-elevated border border-border hover:border-accent text-text-secondary hover:text-text">
              ↗ Profil source
            </a>` : ''}
          <div class="flex-1"></div>
          <button class="text-xs px-2.5 py-1.5 rounded-lg bg-success/10 text-success border border-success/30 hover:bg-success/20"
                  data-li-done>✓ Fait</button>
        </div>
      </article>
    `;
  },

  _bindLinkedinActions() {
    document.querySelectorAll('[data-act-id]').forEach(card => {
      const id = card.dataset.actId;
      const copyBtn = card.querySelector('[data-li-copy]');
      const doneBtn = card.querySelector('[data-li-done]');
      const discardBtn = card.querySelector('[data-li-discard]');
      if (copyBtn) copyBtn.onclick = () => {
        const txt = card.querySelector('pre').textContent || '';
        navigator.clipboard.writeText(txt).then(() => {
          copyBtn.textContent = '✓ Copié';
          setTimeout(() => copyBtn.innerHTML = '📋 Copier le message', 1400);
        }).catch(() => alert('Impossible de copier — fais Ctrl+C manuellement'));
      };
      if (doneBtn) doneBtn.onclick = async () => {
        if (!App.api) return;
        await App.api.multichannel_mark_done({ id });
        card.style.opacity = '0';
        setTimeout(() => this._loadLinkedinActions(), 250);
      };
      if (discardBtn) discardBtn.onclick = async () => {
        if (!App.api) return;
        await App.api.multichannel_discard({ id });
        card.style.opacity = '0';
        setTimeout(() => this._loadLinkedinActions(), 250);
      };
    });
  },

  _escHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>]/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;'
    }[c]));
  },
  _escAttr(s) {
    return String(s == null ? '' : s).replace(/["'&<>]/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    }[c]));
  },

  // -------- Bloc 1 : priorité du jour (UNE seule) --------
  _renderPriority(d) {
    const q = d.queue || {};
    const nInt = q.replies_unhandled_interested || 0;
    const nTotal = q.replies_unhandled_total || 0;
    const nDraftsP = q.drafts_prospect_pending || 0;
    const nDraftsC = q.drafts_convoy_pending || 0;
    const nDrafts = nDraftsP + nDraftsC;

    let kicker, title, body, cta, target, accent;
    if (nInt > 0) {
      kicker = 'PRIORITÉ DU JOUR';
      title  = nInt === 1
        ? '1 prospect intéressé·e à recontacter'
        : `${nInt} prospects intéressés à recontacter`;
      body   = "Ils ont répondu positivement à un de tes mails. C'est ta meilleure piste pour transformer aujourd'hui.";
      cta    = 'Voir leurs réponses';
      target = 'replies';
      accent = 'success';
    } else if (nDrafts > 0) {
      kicker = 'À FAIRE EN PREMIER';
      title  = nDrafts === 1
        ? '1 brouillon à valider'
        : `${nDrafts} brouillons à valider`;
      body   = "Des mails préparés par l'app attendent ton OK. Tu peux les approuver en lot.";
      cta    = 'Valider les brouillons';
      target = 'drafts';
      accent = 'accent';
    } else if (nTotal > 0) {
      kicker = 'À TRIER';
      title  = nTotal === 1
        ? '1 réponse à examiner'
        : `${nTotal} réponses à examiner`;
      body   = "Pas maintenant, refus, désinscriptions — un coup d'œil rapide suffit pour les classer.";
      cta    = 'Voir les réponses';
      target = 'replies';
      accent = 'warning';
    } else {
      kicker = 'TOUT EST À JOUR';
      title  = "Rien ne t'attend ce matin.";
      body   = "Aucune réponse à traiter, aucun brouillon en attente. Bon moment pour lancer une nouvelle vague de prospection ou prendre un café.";
      cta    = "Lancer l'auto-pilote";
      target = 'autopilot';
      accent = 'accent';
    }

    return `
      <div class="card-hero p-12 mb-8" data-accent="${accent}">
        <div class="hero-kicker text-${accent === 'accent' ? 'accent' : accent} mb-3">${kicker}</div>
        <h2 class="font-display text-3xl font-bold mb-3 leading-tight">${title}</h2>
        <p class="text-text-secondary text-base mb-6 max-w-2xl">${body}</p>
        <button class="btn btn-primary" onclick="App.show('${target}')">${cta} →</button>
      </div>
    `;
  },

  // -------- Bloc 2 : Hier en chiffres (3 KPIs) --------
  _renderYesterday(d) {
    const sentY = d.sent.yesterday;
    const repY  = d.replies.yesterday_total;
    const breakdown = d.replies.yesterday_breakdown || {};
    const intY = breakdown.interested || 0;
    const last7 = d.sent.last_7d;

    return `
      <div>
        <div class="section-label">Hier en chiffres</div>
        <div class="grid grid-cols-3 gap-5">
          ${this._stat({label: 'Mails envoyés', value: sentY, delta: `${last7} sur les 7 derniers jours`})}
          ${this._stat({
            label: 'Réponses reçues',
            value: repY,
            delta: repY === 0 ? '—' : `${Math.round(100*repY/Math.max(sentY,1))} % des envoyés`,
          })}
          ${this._stat({
            label: 'Prospects intéressés',
            value: intY,
            delta: intY === 0 ? '—' : 'à recontacter',
            accent: intY > 0 ? 'success' : '',
          })}
        </div>
      </div>
    `;
  },

  // -------- Bloc 3 : Aujourd'hui (2 KPIs) --------
  _renderToday(d) {
    const sentT = d.sent.today;
    const repT  = d.replies.today_total;
    return `
      <div>
        <div class="section-label">Aujourd'hui</div>
        <div class="grid grid-cols-2 gap-5">
          ${this._stat({label: 'Envoyés depuis 00:00', value: sentT, delta: sentT === 0 ? '—' : "L'auto-pilote tourne"})}
          ${this._stat({label: 'Réponses depuis 00:00', value: repT, delta: repT === 0 ? '—' : 'À examiner', accent: repT > 0 ? 'success' : ''})}
        </div>
      </div>
    `;
  },

  // -------- Bloc 4 : À corriger (conditionnel) --------
  _renderIssues(d) {
    const a = d.alerts || {};
    const fY = a.convoy_failed_yesterday || 0;
    const fT = a.convoy_failed_today || 0;
    const total = fY + fT;
    if (total === 0) return '';
    return `
      <div>
        <div class="section-label" style="--filet-color: hsl(var(--danger));">À corriger</div>
        <div class="card p-6 border-l-4 border-l-danger">
          <div class="flex items-start gap-4">
            <div class="w-2 h-2 rounded-full bg-danger mt-2"></div>
            <div class="flex-1">
              <h3 class="font-semibold text-base mb-1">${total === 1 ? '1 mail non parti' : `${total} mails non partis`}</h3>
              <p class="text-text-secondary text-sm mb-4">
                Un problème de configuration mail ou de destinataire. Ouvre l'écran d'import pour voir le détail.
              </p>
              <button class="btn btn-secondary" onclick="App.show('convoy')">Voir le détail</button>
            </div>
          </div>
        </div>
      </div>
    `;
  },

  // -------- Helper stat card --------
  _stat({label, value, delta, accent}) {
    const cls = accent ? `accent-${accent}` : '';
    return `
      <div class="stat-card ${cls}">
        <div class="label">${label}</div>
        <div class="value">${value}</div>
        ${delta ? `<div class="delta">${delta}</div>` : ''}
      </div>
    `;
  },

  // -------- Mode preview (sans API Python) --------
  _previewPlaceholder() {
    // Donne un rendu visuel même sans pywebview connecté
    const fakeDigest = {
      ok: true,
      sent: { yesterday: 47, today: 8, last_7d: 312 },
      replies: {
        yesterday_total: 6,
        yesterday_breakdown: { interested: 2, not_now: 1, no: 2, unsubscribe: 1 },
        today_total: 1, today_breakdown: {}
      },
      queue: { replies_unhandled_interested: 2, replies_unhandled_total: 4,
                drafts_prospect_pending: 3, drafts_convoy_pending: 0 },
      alerts: { convoy_failed_yesterday: 0, convoy_failed_today: 0 },
    };
    return this._renderPriority(fakeDigest)
         + this._renderYesterday(fakeDigest)
         + this._renderToday(fakeDigest)
         + this._renderIssues(fakeDigest);
  },
};
