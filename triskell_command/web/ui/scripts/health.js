/* Vue Santé du système — état des workers + délivrabilité.
 *
 * Affiche :
 *  - Bandeau récap : healthy / warning / error
 *  - Carte par worker avec son dernier run (counters + erreurs)
 *  - Bloc délivrabilité : envois/réponses sur 24h et 7j, taux de réponse
 *  - Auto-refresh toutes les 15 s tant que la vue est ouverte
 */

const Health = {
  refreshTimer: null,
  isOpen: false,

  async render(container) {
    this.isOpen = true;
    container.innerHTML = `
      <section class="animate-slide-up max-w-5xl">
        <div class="mb-8">
          <div class="flex items-start justify-between gap-3">
            <div>
              <div class="hero-kicker mb-2">SANTÉ DU SYSTÈME</div>
              <h1 class="hero-title mb-3" style="font-size: 36px;">Tout est-il en marche ?</h1>
              <p class="hero-subtitle">Tes 10 outils autonomes, leur dernière exécution, et la santé de tes envois.</p>
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

    // Auto-refresh
    if (this.refreshTimer) clearInterval(this.refreshTimer);
    this.refreshTimer = setInterval(() => {
      if (App.currentView === 'health' && this.isOpen) this.refresh();
      else this._stop();
    }, 15000);
  },

  _stop() {
    if (this.refreshTimer) {
      clearInterval(this.refreshTimer);
      this.refreshTimer = null;
    }
    this.isOpen = false;
  },

  async refresh() {
    if (!App.api) {
      document.getElementById('h-content').innerHTML = `
        <div class="card p-10 text-center">
          <div class="text-3xl mb-3">⚙️</div>
          <p class="text-text-muted">Mode aperçu : lance Triskell Command pour voir l'état réel.</p>
        </div>`;
      return;
    }
    let data, mailHealth;
    try {
      [data, mailHealth] = await Promise.all([
        App.api.system_health(),
        (App.api.mail_health ? App.api.mail_health() : Promise.resolve(null)),
      ]);
    } catch (e) {
      document.getElementById('h-content').innerHTML =
        `<div class="card p-6 text-danger">Erreur : ${e}</div>`;
      return;
    }
    if (!data || !data.ok) {
      document.getElementById('h-content').innerHTML =
        `<div class="card p-6 text-danger">${data && data.error || 'Erreur inconnue'}</div>`;
      return;
    }
    document.getElementById('h-content').innerHTML =
      this._renderSummary(data.summary || {}) +
      this._renderMailSafety(mailHealth || {}) +
      this._renderDeliverability(data['delivrabilité'] || {}) +
      this._renderDnsCard() +
      this._renderWorkers(data.workers || []);
    this._bindDnsCard();
  },

  // ---- Tampons DNS (SPF / DKIM / DMARC / MX) ----
  // Vérification à la demande (pas à chaque refresh : c'est du DNS externe).
  _dnsResult: null,

  _renderDnsCard() {
    const r = this._dnsResult;
    let body;
    if (!r) {
      body = `
        <p class="text-xs text-text-muted mb-3">
          Les trois « tampons » qui prouvent aux boîtes mail (Gmail, Yahoo…)
          que tes envois sont légitimes. Sans eux, direction spam.
        </p>
        <button id="h-dns-check" class="btn btn-secondary text-xs">Vérifier mon domaine d'envoi</button>`;
    } else if (!r.ok) {
      body = `
        <div class="text-sm text-danger mb-3">${this._esc(r.error || 'Vérification impossible')}</div>
        <button id="h-dns-check" class="btn btn-secondary text-xs">Réessayer</button>`;
    } else {
      body = `
        <div class="text-xs text-text-muted mb-3">Domaine vérifié :
          <span class="font-semibold text-text">${this._esc(r.domain)}</span>
          — score ${this._esc(r.score)}</div>
        <div class="space-y-2 mb-3">
          ${(r.checks || []).map(c => `
            <div class="flex items-start gap-2 text-sm">
              <span>${c.ok ? '✅' : '❌'}</span>
              <div>
                <span class="font-semibold">${this._esc(c.label)}</span>
                <span class="text-text-muted"> — ${this._esc(c.detail)}</span>
                ${c.advice ? `<div class="text-xs text-warning mt-0.5">→ ${this._esc(c.advice)}</div>` : ''}
              </div>
            </div>`).join('')}
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
      try {
        this._dnsResult = await App.api.mail_dns_check({});
      } catch (e) {
        this._dnsResult = { ok: false, error: String(e) };
      }
      await this.refresh();
    };
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
    const blockCard = (label, value, tone, action) => `
      <div class="stat-card ${tone ? 'accent-' + tone : ''}" ${action ? `style="cursor:pointer;" onclick="${action}"` : ''}>
        <div class="label">${label}</div>
        <div class="value">${value}</div>
      </div>`;
    return `
      <div class="mb-8">
        <div class="section-label">Garde-fous mail</div>
        <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
          ${blockCard('Mails bloqués (à vérifier)', review,
                      review > 0 ? 'warning' : '',
                      review > 0 ? "App.show('drafts')" : '')}
          ${blockCard('Doublons évités (récents)', dup, dup > 0 ? '' : '')}
          ${blockCard('Adresses mortes (bounced)', bounced,
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
      ? `Tout va bien — ${total} outils tournent normalement.`
      : ((s.error || 0) > 0
          ? `${s.error} outil${s.error>1?'s':''} en erreur, à vérifier.`
          : `${s.warning} outil${s.warning>1?'s':''} en avertissement (pas grave, on garde un œil).`);
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
    const rateColor = rate >= 5 ? 'success' : rate >= 1 ? '' : 'warning';
    return `
      <div class="mb-8">
        <div class="section-label">Délivrabilité de tes mails</div>
        <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
          ${this._stat('Envoyés (24h)', d.sent_24h || 0)}
          ${this._stat('Envoyés (7 jours)', d.sent_7d || 0)}
          ${this._stat('Réponses (7 jours)', d.replies_7d || 0,
            (d.replies_7d > 0) ? 'success' : '')}
          ${this._stat('Taux de réponse 7j', `${rate}%`, rateColor)}
        </div>
        ${(!d.smtp_configured || !d.imap_configured) ? `
          <div class="card p-4 mt-4 border-l-4 border-l-warning">
            <div class="text-sm font-semibold mb-1">⚠ Configuration mail incomplète</div>
            <div class="text-xs text-text-muted">
              ${!d.smtp_configured ? 'SMTP non configuré (envoi). ' : ''}
              ${!d.imap_configured ? 'IMAP non configuré (réception). ' : ''}
              Va dans <button class="text-accent underline" onclick="App.show('config')">Réglages</button>
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

  _renderWorkers(workers) {
    return `
      <div>
        <div class="section-label">Outils autonomes (workers)</div>
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
    const status = w.running ? 'En marche' : 'À l\'arrêt';
    const lastRun = w.last_run_at
      ? this._humanTime(w.last_run_at)
      : 'Jamais lancé';
    const result = w.last_run_result || {};
    const counters = Object.entries(result)
      .filter(([k]) => !['error', 'errors'].includes(k))
      .map(([k, v]) => `<span class="text-text-muted mr-3">${this._esc(k)}: <span class="font-semibold text-text">${this._esc(String(v))}</span></span>`)
      .join('');
    const errors = result.error
      ? `<div class="text-xs text-danger mt-2 font-mono">${this._esc(result.error)}</div>`
      : (result.errors > 0
        ? `<div class="text-xs text-warning mt-2">${result.errors} erreur(s) au dernier run</div>`
        : '');
    return `
      <article class="card p-4 flex items-start gap-4">
        <div class="w-2.5 h-2.5 rounded-full ${dot} mt-1.5 shrink-0
                    ${w.running ? 'animate-pulse' : ''}"></div>
        <div class="flex-1">
          <div class="flex items-baseline justify-between mb-1">
            <div class="font-semibold text-sm">${this._esc(w.label)}</div>
            <div class="text-[11px] text-text-muted">${status} · ${lastRun}</div>
          </div>
          ${counters ? `<div class="text-xs">${counters}</div>` : ''}
          ${errors}
          ${w.error ? `<div class="text-xs text-danger mt-2 font-mono">${this._esc(w.error)}</div>` : ''}
        </div>
      </article>
    `;
  },

  _humanTime(iso) {
    try {
      const d = new Date(iso);
      const diffSec = Math.floor((Date.now() - d.getTime()) / 1000);
      if (diffSec < 60)    return 'à l\'instant';
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
