/* Vue Santé du système — état des robots + délivrabilité.
 *
 * Affiche :
 *  - Bandeau récap : healthy / warning / error
 *  - Carte par robot avec son dernier passage (compteurs + erreurs)
 *  - Bloc délivrabilité : envois/réponses sur 24h et 7j, taux de réponse
 *  - Auto-refresh toutes les 15 s tant que la vue est ouverte
 *    (via App.viewInterval : coupé automatiquement en quittant la vue)
 */

const Health = {

  async render(container) {
    container.innerHTML = `
      <section class="animate-slide-up max-w-5xl">
        <div class="mb-8">
          <div class="flex items-start justify-between gap-3">
            <div>
              <div class="hero-kicker mb-2">SANTÉ DU SYSTÈME</div>
              <h1 class="hero-title mb-3" style="font-size: 36px;">Tout est-il en marche ?</h1>
              <p class="hero-subtitle"><span id="h-worker-count">Tes robots autonomes</span>, leur dernier passage, et la santé de tes envois.</p>
            </div>
            ${Help.button('health')}
          </div>
          <div class="flex gap-3 mt-6">
            <button id="h-refresh" class="btn btn-secondary">Rafraîchir</button>
            <span id="h-auto" class="text-xs text-text-muted self-center">⚡ Mise à jour auto toutes les 15 s</span>
          </div>
        </div>
        <div id="h-content"><div class="text-center py-16 text-text-muted">Chargement…</div></div>
      </section>
    `;
    document.getElementById('h-refresh').onclick = () => this.refresh();

    await this.refresh();

    // Auto-refresh : minuteur auto-nettoyé au changement de vue.
    // On saute le tour si une vérification DNS est en cours pour ne pas
    // écraser son état à l'écran.
    App.viewInterval(() => {
      if (!this._dnsChecking && !this._refreshing && !this._restarting
          && !this._repLoading) this.refresh();
    }, 15000);

    // Réputation des boîtes : analyse réseau (DNS + base), chargée une fois.
    this._loadReputation();
  },

  _refreshing: false,

  async refresh() {
    if (!App.api) {
      document.getElementById('h-content').innerHTML = `
        <div class="card p-10 text-center">
          <div class="text-3xl mb-3">⚙️</div>
          <p class="text-text-muted">Mode aperçu : lance Triskell Command pour voir l'état réel.</p>
        </div>`;
      return;
    }
    this._refreshing = true;
    let data, mailHealth;
    try {
      [data, mailHealth] = await Promise.all([
        App.api.system_health(),
        (App.api.mail_health ? App.api.mail_health() : Promise.resolve(null)),
      ]);
    } catch (e) {
      this._refreshing = false;
      console.warn('system_health:', e);
      this._renderLoadError();
      return;
    }
    this._refreshing = false;
    if (!data || !data.ok) {
      console.warn('system_health:', data && data.error);
      this._renderLoadError();
      return;
    }
    const workers = data.workers || [];
    // Compte dynamique dans le sous-titre (avant : « Tes 10 outils » en
    // dur, alors que le serveur en a plus)
    const countEl = document.getElementById('h-worker-count');
    if (countEl) countEl.textContent = `Tes ${workers.length} robots autonomes`;
    // Préserve les « Détail technique » ouverts à travers l'auto-refresh
    const openDetails = new Set(
      Array.from(document.querySelectorAll('#h-content details[open][data-w]'))
        .map(d => d.dataset.w)
    );
    document.getElementById('h-content').innerHTML =
      this._renderSummary(data.summary || {}) +
      this._renderMailSafety(mailHealth || {}) +
      this._renderReputation() +
      this._renderDeliverability(data['delivrabilité'] || {}) +
      this._renderDnsCard() +
      this._renderWorkers(workers);
    document.querySelectorAll('#h-content details[data-w]').forEach(d => {
      if (openDetails.has(d.dataset.w)) d.open = true;
    });
    this._bindDnsCard();
    this._bindRepCard();
    this._bindRestartButtons();
  },

  _renderLoadError() {
    const host = document.getElementById('h-content');
    if (!host) return;
    host.innerHTML = `
      <div class="card p-10 text-center">
        <p class="text-text font-semibold mb-1">Impossible de charger l'état du système.</p>
        <p class="text-text-muted text-sm mb-4">Vérifie ta connexion, puis réessaie — la page se met aussi à jour toute seule toutes les 15 s.</p>
        <button class="btn btn-primary" onclick="Health.refresh()">Réessayer</button>
      </div>`;
  },

  // ---- Tampons DNS (SPF / DKIM / DMARC / MX) ----
  // Vérification à la demande (pas à chaque refresh : c'est du DNS externe).
  _dnsResult: null,
  _dnsChecking: false,   // une vérif tourne → l'auto-refresh ne touche à rien

  // Traductions des contrôles (P5) : à l'écran, chaque tampon dit ce qu'il
  // FAIT et ce qu'on risque sans lui. Les conseils du serveur (advice,
  // déjà en français avec les chemins IONOS) restent affichés tels quels.
  _DNS_FR: {
    spf:   { name: 'Autorisation d’envoyer (SPF)',
             risk: 'sans elle, tes mails partent tout droit en indésirable' },
    dkim:  { name: 'Signature de tes mails (DKIM)',
             risk: 'sans elle, Gmail et Yahoo se méfient de tes envois' },
    dmarc: { name: 'Consigne en cas de doute (DMARC)',
             risk: 'sans elle, n’importe qui peut se faire passer pour ton adresse' },
    mx:    { name: 'Réception des réponses (MX)',
             risk: 'sans elle, les réponses de tes prospects n’arrivent jamais' },
  },

  _renderDnsCard() {
    const r = this._dnsResult;
    let body;
    if (this._dnsChecking) {
      body = `
        <p class="text-xs text-text-muted mb-3">Vérification en cours…</p>
        <button id="h-dns-check" class="btn btn-secondary text-xs" disabled>Vérification…</button>`;
    } else if (!r) {
      body = `
        <p class="text-xs text-text-muted mb-3">
          Les « tampons » qui prouvent aux boîtes mail (Gmail, Yahoo…)
          que tes envois sont légitimes. Sans eux, direction spam.
        </p>
        <button id="h-dns-check" class="btn btn-secondary text-xs">Vérifier mon domaine d'envoi</button>`;
    } else if (!r.ok) {
      // Le serveur renvoie parfois un message déjà en français et utile
      // (ex. « Aucun domaine : configure d'abord… ») — on le garde.
      // Le reste (exceptions brutes) devient un message générique.
      const friendly = /^Aucun domaine/.test(r.error || '')
        ? r.error
        : 'Vérification impossible pour le moment. Réessaie dans un instant.';
      body = `
        <div class="text-sm text-danger mb-3">${this._esc(friendly)}</div>
        <button id="h-dns-check" class="btn btn-secondary text-xs">Réessayer</button>`;
    } else {
      body = `
        <div class="text-xs text-text-muted mb-3">Domaine vérifié :
          <span class="font-semibold text-text">${this._esc(r.domain)}</span>
          — score ${this._esc(r.score)}</div>
        <div class="space-y-2 mb-3">
          ${(r.checks || []).map(c => {
            const fr = this._DNS_FR[String(c.id || '').toLowerCase()] || null;
            const name = fr ? fr.name : c.label;
            return `
            <div class="flex items-start gap-2 text-sm">
              <span>${c.ok ? '✅' : '❌'}</span>
              <div>
                <span class="font-semibold">${this._esc(name)}</span>
                <span class="text-text-muted"> — ${this._esc(c.detail)}</span>
                ${(!c.ok && fr) ? `<div class="text-xs text-danger-text mt-0.5">Risque : ${this._esc(fr.risk)}.</div>` : ''}
                ${c.advice ? `<div class="text-xs text-warning mt-0.5">→ Quoi faire : ${this._esc(c.advice)}</div>` : ''}
              </div>
            </div>`;
          }).join('')}
        </div>
        <button id="h-dns-check" class="btn btn-secondary text-xs">Re-vérifier</button>`;
    }
    return `
      <div class="mb-8">
        <div class="section-label">Tampons d'authentification (DNS)</div>
        <div class="card p-4">${body}</div>
      </div>`;
  },

  _bindDnsCard() {
    const btn = document.getElementById('h-dns-check');
    if (!btn) return;
    btn.onclick = async () => {
      btn.disabled = true;
      btn.textContent = 'Vérification…';
      this._dnsChecking = true; // l'auto-refresh saute son tour pendant ce temps
      try {
        this._dnsResult = await App.api.mail_dns_check({});
      } catch (e) {
        console.warn('mail_dns_check:', e);
        this._dnsResult = { ok: false, error: String(e) };
      } finally {
        this._dnsChecking = false;
      }
      await this.refresh();
    };
  },

  // ---- Réputation & chauffe RÉELLE des boîtes d'envoi ----
  // Chaque ligne est un FAIT mesuré (authentification du domaine, historique
  // d'envoi réel, rebonds, chauffe interne) — jamais une supposition sur le
  // nom de domaine. Analyse réseau (DNS + base) : chargée une seule fois, pas
  // à chaque rafraîchissement automatique.
  _repResult: null,
  _repLoading: false,

  async _loadReputation() {
    if (!App.api || !App.api.mail_reputation || this._repLoading) return;
    this._repLoading = true;
    const host = document.getElementById('h-rep');
    if (host) host.innerHTML =
      `<div class="card p-4 text-sm text-text-muted">Analyse des boîtes d'envoi en cours… ` +
      `(vérification des tampons d'authentification et de l'historique d'envoi réel)</div>`;
    try {
      this._repResult = await App.api.mail_reputation({ with_dns: true, with_age: true });
    } catch (e) {
      console.warn('mail_reputation:', e);
      this._repResult = { ok: false, error: String(e) };
    } finally {
      this._repLoading = false;
    }
    await this.refresh();
  },

  _renderReputation() {
    return `
      <div class="mb-8">
        <div class="flex items-center justify-between mb-2">
          <div class="section-label" style="margin:0">Réputation & chauffe de tes boîtes d'envoi</div>
          <button id="h-rep-refresh" class="text-xs text-accent underline"
                  ${this._repLoading ? 'disabled' : ''}>${this._repLoading ? 'Analyse…' : 'Réanalyser'}</button>
        </div>
        <div id="h-rep">${this._repInner()}</div>
      </div>`;
  },

  _repInner() {
    if (this._repLoading && !this._repResult) {
      return `<div class="card p-4 text-sm text-text-muted">Analyse des boîtes d'envoi en cours…</div>`;
    }
    const r = this._repResult;
    if (!r) return `<div class="card p-4 text-sm text-text-muted">Analyse à venir…</div>`;
    if (!r.ok) {
      return `<div class="card p-4 text-sm text-danger">Analyse impossible pour le moment.
        <button class="text-accent underline" onclick="Health._loadReputation()">Réessayer</button></div>`;
    }
    const boxes = r.boxes || [];
    if (!boxes.length) {
      return `<div class="card p-4 text-sm text-text-muted">Aucune boîte d'envoi configurée.
        Ajoute-en dans <button class="text-accent underline" onclick="App.show('config',{tab:'mails'})">Réglages</button>.</div>`;
    }
    const note = (r.history_ok === false)
      ? `<div class="text-xs text-warning mb-2">⚠ L'historique d'envoi n'a pas pu être lu — les volumes ci-dessous sont peut-être incomplets.</div>`
      : '';
    return note + boxes.map(b => this._repCard(b)).join('');
  },

  _repCard(b) {
    const tone = b.tone || 'muted';
    const cVar = { success: '--success', warning: '--warning',
                   danger: '--danger', muted: '--text-muted' }[tone] || '--text-muted';
    const m = b.metrics || {};
    const chips = [];
    chips.push(this._repChip('Envois réels (30 j)', m.sent_30d != null ? m.sent_30d : '—'));
    if (m.first_send_days_ago != null && m.sent_window) {
      chips.push(this._repChip('Envoie depuis', m.first_send_days_ago + ' j'));
    }
    if (m.warmup_age_days != null) {
      chips.push(this._repChip('Chauffe interne', 'J' + m.warmup_age_days + '/' + (m.warmup_goal_days || 28)));
    }
    chips.push(this._repChip('Rebonds (30 j)',
      (m.bounces_30d || 0) + ' (' + (m.bounce_rate_pct || 0) + '%)',
      b.bounce_alert ? 'danger' : ''));
    if (m.replies_30d) chips.push(this._repChip('Réponses (30 j)', m.replies_30d, 'success'));
    if (b.domain_age_days != null) {
      chips.push(this._repChip('Nom de domaine', 'créé il y a ' + this._repAge(b.domain_age_days)));
    }
    let auth = '';
    if (b.auth && b.auth.checks) {
      auth = `<div class="flex flex-wrap gap-x-4 gap-y-1 mt-2 text-xs">` +
        b.auth.checks.map(c => {
          const fr = this._DNS_FR[String(c.id || '').toLowerCase()];
          const name = fr ? fr.name : c.label;
          return `<span>${c.ok ? '✅' : '❌'} ${this._esc(name)}</span>`;
        }).join('') + `</div>`;
    } else if (b.auth_state === 'inconnu') {
      auth = `<div class="text-xs text-text-muted mt-2">Authentification du domaine : non vérifiée.</div>`;
    }
    return `
      <article class="card p-4 mb-3">
        <div class="flex items-start justify-between gap-3 mb-1">
          <div class="font-semibold text-sm break-all">${this._esc(b.name || b.email)}</div>
          <span class="inline-flex items-center gap-1.5 text-xs font-semibold shrink-0">
            <span class="w-2 h-2 rounded-full" style="background:hsl(var(${cVar}))"></span>
            <span style="color:hsl(var(${cVar}))">${this._esc(b.label || '')}</span>
          </span>
        </div>
        <div class="text-sm" style="text-wrap:pretty">${this._esc(b.summary || '')}</div>
        <div class="flex flex-wrap gap-x-4 gap-y-1 mt-2">${chips.join('')}</div>
        ${auth}
        ${b.advice ? `<div class="text-xs text-text-muted mt-2" style="text-wrap:pretty">→ ${this._esc(b.advice)}</div>` : ''}
      </article>`;
  },

  _repChip(label, value, tone) {
    const cVar = { success: '--success', warning: '--warning', danger: '--danger' }[tone];
    const valStyle = cVar ? ` style="color:hsl(var(${cVar}))"` : '';
    return `<span class="text-xs text-text-muted">${this._esc(label)} : ` +
           `<span class="font-semibold text-text"${valStyle}>${this._esc(String(value))}</span></span>`;
  },

  _repAge(days) {
    days = Number(days) || 0;
    if (days < 60) return days + ' j';
    if (days < 730) return Math.round(days / 30) + ' mois';
    return Math.round(days / 365) + ' an(s)';
  },

  _bindRepCard() {
    const btn = document.getElementById('h-rep-refresh');
    if (btn) btn.onclick = () => this._loadReputation();
  },

  _renderMailSafety(mh) {
    // Section dediee aux garde-fous mail : drafts bloques, prospects exclus
    // par le systeme de protection. Visible seulement si on a des chiffres
    // ou des alertes.
    const review = mh.needs_review_count || 0;
    const dup    = mh.skipped_duplicate_count || 0;
    const bounced = mh.bounced_count || 0;
    const unsub  = mh.unsubscribed_count || 0;
    const alerts = (mh.alerts || []).length;
    if (!review && !dup && !bounced && !unsub && !alerts) return '';
    // action : la carte devient un vrai bouton (clavier + lecteur d'écran)
    // avec un libellé « Voir » explicite.
    const blockCard = (label, value, tone, action) => `
      <div class="stat-card ${tone ? 'accent-' + tone : ''}"
           ${action ? `role="button" tabindex="0" style="cursor:pointer;"
             aria-label="${label} : voir le détail"
             onclick="${action}"
             onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();${action}}"` : ''}>
        <div class="label">${label}</div>
        <div class="value">${value}</div>
        ${action ? `<div class="text-[11px] text-accent font-semibold mt-1">Voir →</div>` : ''}
      </div>`;
    return `
      <div class="mb-8">
        <div class="section-label">Garde-fous mail</div>
        <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
          ${blockCard('Mails bloqués (à vérifier)', review,
                      review > 0 ? 'warning' : '',
                      review > 0 ? "App.show('drafts')" : '')}
          ${blockCard('Doublons évités (récents)', dup, dup > 0 ? '' : '')}
          ${blockCard('Adresses mortes', bounced,
                      bounced > 0 ? 'warning' : '')}
          ${blockCard('Désinscrits (STOP)', unsub, '')}
        </div>
        ${alerts ? `
          <div class="card p-4 mt-4 border-l-4 border-l-danger">
            <div class="text-sm font-semibold mb-1 text-danger">⚠ ${alerts} alerte${alerts>1?'s':''} mail</div>
            <div class="text-xs text-text-muted">
              ${(mh.alerts || []).map(a => this._esc(a.message ||
                `${a.account_id} : ${a.consecutive_errors} cycles d'échec consécutifs`)).join(' · ')}
            </div>
          </div>` : ''}
      </div>
    `;
  },

  _renderSummary(s) {
    const total = (s.healthy || 0) + (s.warning || 0) + (s.error || 0);
    const allGood = (s.error || 0) === 0 && (s.warning || 0) === 0;
    const tone = allGood ? 'success' : ((s.error || 0) > 0 ? 'danger' : 'warning');
    const msg = allGood
      ? `Tout va bien — ${total} robots tournent normalement.`
      : ((s.error || 0) > 0
          ? `${s.error} robot${s.error>1?'s':''} en erreur, à vérifier.`
          : `${s.warning} robot${s.warning>1?'s':''} en avertissement (pas grave, on garde un œil).`);
    return `
      <div class="card-hero p-8 mb-8" data-accent="${tone}">
        <div class="hero-kicker text-${tone === 'success' ? 'success' : tone === 'danger' ? 'danger' : 'warning'} mb-2">SANTÉ GLOBALE</div>
        <h2 class="font-display text-2xl font-bold mb-3">${msg}</h2>
        <div class="flex gap-6 mt-4">
          <div><span class="text-2xl font-bold text-success">${s.healthy || 0}</span>
               <span class="text-sm text-text-muted ml-1">en forme</span></div>
          <div><span class="text-2xl font-bold text-warning">${s.warning || 0}</span>
               <span class="text-sm text-text-muted ml-1">à surveiller</span></div>
          <div><span class="text-2xl font-bold text-danger">${s.error || 0}</span>
               <span class="text-sm text-text-muted ml-1">en erreur</span></div>
        </div>
      </div>
    `;
  },

  _renderDeliverability(d) {
    const rate = d.reply_rate_7d || 0;
    const sent7d = d.sent_7d || 0;
    // 0 envoi sur 7 jours → pas de taux à juger : neutre, pas orange.
    const rateColor = sent7d === 0 ? '' : (rate >= 5 ? 'success' : rate >= 1 ? '' : 'warning');
    const rateValue = sent7d === 0 ? '—' : `${rate}%`;
    return `
      <div class="mb-8">
        <div class="section-label">Délivrabilité de tes mails</div>
        <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
          ${this._stat('Envoyés (24h)', d.sent_24h || 0)}
          ${this._stat('Envoyés (7 jours)', sent7d)}
          ${this._stat('Réponses (7 jours)', d.replies_7d || 0,
            (d.replies_7d > 0) ? 'success' : '')}
          ${this._stat('Taux de réponse 7j', rateValue, rateColor)}
        </div>
        ${(!d.smtp_configured || !d.imap_configured) ? `
          <div class="card p-4 mt-4 border-l-4 border-l-warning">
            <div class="text-sm font-semibold mb-1">⚠ Configuration mail incomplète</div>
            <div class="text-xs text-text-muted">
              ${!d.smtp_configured ? 'L’envoi de mails n’est pas configuré. ' : ''}
              ${!d.imap_configured ? 'La lecture des réponses n’est pas configurée. ' : ''}
              Va dans <button class="text-accent underline" onclick="App.show('config', {tab:'mails'})">Réglages</button>
              pour compléter ton compte mail.
            </div>
          </div>` : ''}
      </div>
    `;
  },

  _stat(label, value, accent = '') {
    const cls = accent ? `accent-${accent}` : '';
    return `
      <div class="stat-card ${cls}">
        <div class="label">${label}</div>
        <div class="value">${value}</div>
      </div>
    `;
  },

  // ---- Libellés français des robots (par identifiant serveur) ----
  // Le serveur envoie des libellés avec du jargon (IMAP, drip, Polling…) :
  // on les traduit ici. Identifiant inconnu → libellé serveur tel quel.
  WORKER_LABELS_FR: {
    'replies_poller':         'Lecture de la boîte mail',
    'reply_responder':        'Réponses automatiques',
    'drip_runner':            'Relances espacées',
    'post_sale_runner':       'Suivi après-vente',
    'lead_to_client':         'Bascule intéressé → projet client',
    'multichannel_followup':  'Relances LinkedIn préparées',
    'dormant_recycler':       'Recyclage des prospects dormants',
    'stripe_poller':          'Surveillance des paiements',
    'claude_proactive':       'Veille proactive de Claude',
    'mission_runner':         'Chef de gare des prospections',
    'autopilot_runner':       'Passage automatique de l’Auto-pilote',
    'pixelpros.auto_builder': 'Construction automatique des sites payés',
    'phare_scheduler':        'Le Phare — surveillance SEO',
  },

  // ---- Compteurs du dernier passage : clés techniques → français ----
  COUNTER_LABELS_FR: {
    sent: 'envoyés', auto_sent: 'envoyés auto', skipped: 'ignorés',
    errors: 'erreurs', scanned: 'examinés', advanced: 'avancées',
    converted: 'convertis', weak_signal: 'signal trop faible',
    drafts_created: 'brouillons créés', drafts: 'brouillons',
    drafted: 'brouillons préparés', candidates: 'candidats',
    polled: 'paiements consultés', new_payments: 'nouveaux paiements',
    projects_created: 'projets créés', matched: 'reconnus',
    classified: 'classées', written: 'enregistrées',
    accounts_scanned: 'comptes lus', actions: 'actions',
    replies: 'réponses', new_replies: 'nouvelles réponses',
    checked: 'vérifiés', processed: 'traités', built: 'construits',
    stopped: 'arrêté', warnings: 'avertissements',
  },

  // Motifs de passage sauté (skipped_reason)
  SKIP_REASONS_FR: {
    server_active: 'une autre instance s’en occupe',
    disabled: 'désactivé volontairement',
  },

  // Erreurs serveur connues → phrase simple ; le détail brut reste
  // disponible dans le « Détail technique ».
  _workerErrorFr(raw) {
    const s = String(raw || '');
    if (/supabase_unavailable/i.test(s)) return 'La base partagée était injoignable au dernier passage.';
    if (/no_imap_account_configured/i.test(s)) return 'Aucun compte mail n’est configuré pour la lecture.';
    if (/secret_key invalide/i.test(s)) return 'La clé du système de paiement est invalide.';
    if (/clé IA .* manquante/i.test(s)) return 'Il manque une clé IA dans les réglages.';
    if (/aucun tick github/i.test(s)) return 'Le Phare ne donne plus signe de vie depuis plusieurs heures.';
    return 'Ce robot a rencontré un problème au dernier passage.';
  },

  _renderWorkers(workers) {
    return `
      <div>
        <div class="section-label">Robots autonomes</div>
        <div class="space-y-3">
          ${workers.map(w => this._workerCard(w)).join('')}
        </div>
      </div>
    `;
  },

  _workerCard(w) {
    const dot = w.health === 'healthy' ? 'bg-success'
              : w.health === 'warning' ? 'bg-warning'
              : 'bg-danger';
    const status = w.running ? 'En marche' : 'À l’arrêt';
    const lastRun = w.last_run_at
      ? this._humanTime(w.last_run_at)
      : 'Jamais lancé';
    const label = this.WORKER_LABELS_FR[w.name] || w.label || w.name || '';
    const result = w.last_run_result || {};
    // Compteurs : uniquement les valeurs simples (nombres / oui-non),
    // traduites en français. Les objets imbriqués restent en console.
    const counters = Object.entries(result)
      .filter(([k, v]) => !['error', 'errors', 'skipped_reason', 'log_tail'].includes(k)
                          && (typeof v === 'number' || typeof v === 'boolean'))
      .map(([k, v]) => {
        const lbl = this.COUNTER_LABELS_FR[k] || k.replace(/_/g, ' ');
        const val = typeof v === 'boolean' ? (v ? 'oui' : 'non') : v;
        return `<span class="text-text-muted mr-3">${this._esc(lbl)} : <span class="font-semibold text-text">${this._esc(String(val))}</span></span>`;
      })
      .join('');
    const skipReason = result.skipped_reason
      ? `<div class="text-[11px] text-text-muted mt-1">Passage sauté : ${this._esc(this.SKIP_REASONS_FR[result.skipped_reason] || result.skipped_reason)}.</div>`
      : '';
    // Erreurs : phrase simple en français + exception complète repliée.
    const rawError = result.error || w.error || '';
    const techDetail = (raw) => `
      <details class="mt-1" data-w="${this._esc(w.name || label)}">
        <summary class="text-[11px] text-text-muted cursor-pointer">Détail technique</summary>
        <div class="text-[11px] text-text-muted font-mono mt-1 break-all">${this._esc(raw)}</div>
      </details>`;
    const errors = rawError
      ? `<div class="text-xs text-danger mt-2">${this._esc(this._workerErrorFr(rawError))}</div>${techDetail(rawError)}`
      : (result.errors > 0
        ? `<div class="text-xs text-warning mt-2">${result.errors} erreur${result.errors > 1 ? 's' : ''} au dernier passage</div>`
        : '');
    // Robot à l'arrêt : bouton « Relancer » (sauf le Phare, qui tourne sur
    // GitHub et ne se relance pas d'ici). Le serveur ne relance que les
    // robots vraiment arrêtés — un robot qui tourne n'est jamais touché.
    // En PANNE : vrai bouton bien visible (le lien discret n'était jamais
    // vu — audit débutant) + marche à suivre en 3 temps.
    const inTrouble = (w.health === 'error' || !!rawError);
    const canRestart = !w.running && w.name && w.name !== 'phare_scheduler';
    const restartBtn = canRestart
      ? (inTrouble
          ? `<button class="btn btn-primary text-xs mt-2 mr-3" data-restart="${this._esc(w.name)}"
                     title="Redémarre ce robot sur le serveur">↻ Relancer ce robot</button>`
          : `<button class="text-xs text-accent underline mt-2 mr-4" data-restart="${this._esc(w.name)}"
                     title="Redémarre ce robot sur le serveur">Relancer</button>`)
      : '';
    // Robot en panne : on donne au moins une action (vérifier les réglages).
    const fixLink = inTrouble
      ? `<button class="text-xs text-accent underline mt-2" onclick="App.show('config')">Vérifier les réglages</button>`
      : '';
    const helpSteps = inTrouble
      ? `<div class="text-[11px] text-text-muted mt-2" style="text-wrap: pretty">
           Quoi faire : 1. « Relancer ce robot » · 2. s'il retombe en panne,
           « Vérifier les réglages » · 3. toujours rouge ? « Signaler un
           bug » (en bas du menu) — le détail technique part avec le rapport.
         </div>`
      : '';
    return `
      <article class="card p-4 flex items-start gap-4">
        <div class="w-2.5 h-2.5 rounded-full ${dot} mt-1.5 shrink-0
                    ${w.running ? 'animate-pulse' : ''}"></div>
        <div class="flex-1">
          <div class="flex items-baseline justify-between mb-1">
            <div class="font-semibold text-sm">${this._esc(label)}</div>
            <div class="text-[11px] text-text-muted">${status} · ${lastRun}</div>
          </div>
          ${counters ? `<div class="text-xs">${counters}</div>` : ''}
          ${skipReason}
          ${errors}
          ${restartBtn}${fixLink}
          ${helpSteps}
        </div>
      </article>
    `;
  },

  // ---- Relance d'un robot arrêté (bouton « Relancer ») ----
  _restarting: false,

  async _restartWorker(btn, name) {
    if (!App.api || !name || this._restarting) return;
    this._restarting = true;
    const original = btn ? btn.textContent : '';
    if (btn) { btn.disabled = true; btn.textContent = 'Relance…'; }
    try {
      const r = await App.api.worker_restart({ name });
      if (r && r.ok) {
        Toast.success(r.message || 'Robot relancé.');
      } else {
        Toast.error((r && r.error) || 'La relance a échoué — réessaie dans un instant.');
      }
    } catch (e) {
      Toast.friendlyError(e, 'La relance a échoué — réessaie dans un instant.');
    } finally {
      this._restarting = false;
      if (btn) { btn.disabled = false; btn.textContent = original; }
    }
    await this.refresh();
  },

  _bindRestartButtons() {
    document.querySelectorAll('#h-content [data-restart]').forEach(b => {
      b.onclick = () => this._restartWorker(b, b.dataset.restart);
    });
  },

  _humanTime(iso) {
    try {
      const d = new Date(iso);
      const diffSec = Math.floor((Date.now() - d.getTime()) / 1000);
      if (diffSec < 60)    return 'à l’instant';
      if (diffSec < 3600)  return `il y a ${Math.floor(diffSec / 60)} min`;
      if (diffSec < 86400) return `il y a ${Math.floor(diffSec / 3600)} h`;
      return `il y a ${Math.floor(diffSec / 86400)} j`;
    } catch (e) { return iso; }
  },

  _esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    }[c]));
  },
};
