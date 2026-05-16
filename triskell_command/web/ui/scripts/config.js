/* Vue Réglages — apparence, IA, mail, connexion base partagée */

const Config = {
  async render(container) {
    container.innerHTML = `
      <section class="animate-slide-up">
        <div class="mb-10">
          <div class="flex items-start justify-between gap-3">
            <div>
              <div class="hero-kicker mb-2">RÉGLAGES</div>
              <h1 class="hero-title mb-3" style="font-size: 36px;">Configurer ton Triskell.</h1>
              <p class="hero-subtitle">Ton apparence, tes clés, ton compte mail, et ta connexion à la base partagée.</p>
            </div>
            ${Help.button('config')}
          </div>
        </div>

        <div id="cfg-content" class="space-y-12 max-w-3xl"></div>
      </section>
    `;
    await this.refresh();
  },

  async refresh() {
    let s = null;
    let l2c = null;
    let stripeCfg = null;
    let calendlyCfg = null;
    let phantomCfg = null;
    let trackerCfg = null;
    let authStatus = null;
    if (App.api) {
      try { s = await App.api.get_settings(); } catch (e) {}
      try { authStatus = await App.api.auth_status(); } catch (e) {}
      try {
        const r = await App.api.lead_to_client_get_config();
        if (r && r.ok) l2c = r.config;
      } catch (e) {}
      try {
        const r = await App.api.stripe_get_config();
        if (r && r.ok) stripeCfg = r.config;
      } catch (e) {}
      try {
        const r = await App.api.calendly_get_config();
        if (r && r.ok) calendlyCfg = r.config;
      } catch (e) {}
      try {
        const r = await App.api.phantombuster_get_config();
        if (r && r.ok) phantomCfg = r.config;
      } catch (e) {}
      try {
        const r = await App.api.tracker_get_config();
        if (r && r.ok) trackerCfg = r.config;
      } catch (e) {}
    }
    const slot = document.getElementById('cfg-content');
    slot.innerHTML = this._renderAuth(authStatus) +
                     this._renderDemoMode() +
                     this._renderBackups() +
                     this._renderAppearance(s) +
                     this._renderAi(s) +
                     this._renderOutreach(s) +
                     this._renderMailAccounts() +
                     this._renderSignature() +
                     this._renderStripe(stripeCfg) +
                     this._renderCalendly(calendlyCfg) +
                     this._renderPhantombuster(phantomCfg) +
                     this._renderTracker(trackerCfg) +
                     this._renderLeadToClient(l2c) +
                     this._renderDelivery() +
                     this._renderTutorial();
    this._bind();
    this._bindAuth();
    this._bindMailAccounts();
    this._bindSignature();
    this._bindLeadToClient();
    this._bindStripe();
    this._bindCalendly();
    this._bindPhantombuster();
    this._bindTracker();
    this._bindDemoMode();
    this._bindBackups();
  },

  _renderBackups() {
    return `
      <section>
        <div class="section-label">Sauvegardes automatiques</div>
        <p class="text-sm text-text-muted mb-4">
          L'app sauvegarde toutes les semaines tes données critiques
          (modèles d'emails, signatures, comptes mail, notes Brain, projets
          clients, mails programmés) dans un fichier local — au cas où la
          base partagée tomberait ou si tu fais une bourde. Les 12 derniers
          backups sont conservés (~3 mois d'historique).
        </p>
        <div class="card p-6 space-y-4">
          <div class="flex items-center justify-between gap-3">
            <div>
              <div class="text-sm font-semibold">Backups disponibles</div>
              <div class="text-xs text-text-muted">Stockés dans <code>~/.triskell-command/backups/</code></div>
            </div>
            <button id="cfg-backup-now" class="btn btn-secondary text-sm">Faire un backup maintenant</button>
          </div>
          <div id="cfg-backup-list" class="text-xs">
            <div class="text-text-muted italic">Chargement…</div>
          </div>
        </div>
      </section>
    `;
  },

  async _bindBackups() {
    const btn = document.getElementById('cfg-backup-now');
    const list = document.getElementById('cfg-backup-list');
    if (!btn || !list) return;

    const reload = async () => {
      if (!App.api) {
        list.innerHTML = '<div class="text-text-muted italic">API indisponible.</div>';
        return;
      }
      try {
        const r = await App.api.backup_list();
        if (!r || !r.ok || !r.backups || r.backups.length === 0) {
          list.innerHTML = '<div class="text-text-muted italic">Aucun backup encore. Le premier sera fait dans 7 jours, ou tu peux le forcer maintenant.</div>';
          return;
        }
        list.innerHTML = `
          <table class="w-full">
            <thead>
              <tr class="text-text-muted text-[10px] uppercase tracking-widest">
                <th class="text-left py-2 font-semibold">Fichier</th>
                <th class="text-left py-2 font-semibold">Date</th>
                <th class="text-right py-2 font-semibold">Taille</th>
              </tr>
            </thead>
            <tbody>
              ${r.backups.map(b => `
                <tr class="border-t border-border">
                  <td class="py-2 font-mono text-text">${this._esc(b.filename)}</td>
                  <td class="py-2 text-text-muted">${(b.ts || '').slice(0, 16).replace('T', ' ')}</td>
                  <td class="py-2 text-right text-text-muted">${Math.round(b.size_bytes / 1024)} Ko</td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        `;
      } catch (e) {
        list.innerHTML = `<div class="text-danger">Erreur : ${e.message || e}</div>`;
      }
    };

    btn.onclick = async () => {
      if (!App.api) return;
      btn.disabled = true;
      btn.textContent = 'Backup en cours…';
      try {
        const r = await App.api.backup_run_now();
        if (r && r.ok) {
          btn.textContent = '✓ Backup créé';
          setTimeout(() => { btn.textContent = 'Faire un backup maintenant'; btn.disabled = false; }, 1500);
          reload();
        } else {
          btn.textContent = '✗ Échec';
          setTimeout(() => { btn.textContent = 'Faire un backup maintenant'; btn.disabled = false; }, 2500);
        }
      } catch (e) {
        btn.textContent = `✗ ${e.message || e}`;
        setTimeout(() => { btn.textContent = 'Faire un backup maintenant'; btn.disabled = false; }, 3000);
      }
    };

    reload();
  },

  _renderDemoMode() {
    const isOn = (typeof DemoMode !== 'undefined' && DemoMode.isOn && DemoMode.isOn());
    return `
      <section>
        <div class="section-label">Mode démo</div>
        <p class="text-sm text-text-muted mb-4">
          Pour réaliser des visuels promotionnels.
          Quand il est activé, tu peux cliquer partout dans l'app, naviguer dans tous les onglets :
          rien n'est réel (pas d'envoi de mail, pas de modification en base, aucune action ne part au serveur).
          Les chiffres et stats sont remplacés par des données fictives crédibles, comme si la boîte tournait à plein régime.
        </p>
        <div class="card p-6">
          ${isOn ? `
            <div class="flex items-start gap-4">
              <div class="w-12 h-12 rounded-2xl flex items-center justify-center shrink-0"
                   style="background: linear-gradient(135deg, #ef4444, #f97316);">
                <svg class="w-6 h-6 text-white" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24">
                  <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
                </svg>
              </div>
              <div class="flex-1">
                <div class="font-bold text-base text-text mb-1">Mode démo activé</div>
                <div class="text-sm text-text-muted mb-3">
                  Aucune action n'est réelle. Toutes les vraies données reviendront dès que tu désactives.
                </div>
                <button id="demo-mode-off" class="btn btn-secondary">
                  Désactiver le mode démo
                </button>
              </div>
            </div>
          ` : `
            <div class="flex items-start gap-4">
              <div class="w-12 h-12 rounded-2xl bg-bg flex items-center justify-center shrink-0 border border-border">
                <svg class="w-6 h-6 text-text-muted" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                  <rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/>
                </svg>
              </div>
              <div class="flex-1">
                <div class="font-bold text-base text-text mb-1">Désactivé</div>
                <div class="text-sm text-text-muted mb-3">
                  En l'activant, tu pourras naviguer librement avec des données fictives, sans risque d'envoyer un vrai mail
                  ou de modifier ta base. Idéal pour des captures d'écran.
                </div>
                <button id="demo-mode-on"
                        class="btn btn-primary"
                        style="background: linear-gradient(135deg, #ef4444, #f97316); border: none;">
                  Activer le mode démo
                </button>
                <div class="text-[11px] text-text-muted mt-2">L'app se recharge automatiquement après activation.</div>
              </div>
            </div>
          `}
        </div>
      </section>
    `;
  },

  _bindDemoMode() {
    const onBtn  = document.getElementById('demo-mode-on');
    const offBtn = document.getElementById('demo-mode-off');
    if (onBtn) onBtn.onclick = () => {
      if (typeof DemoMode !== 'undefined') DemoMode.setOn(true);
    };
    if (offBtn) offBtn.onclick = () => {
      if (typeof DemoMode !== 'undefined') DemoMode.setOn(false);
    };
  },

  _renderAuth(authStatus) {
    const connected = authStatus && authStatus.connected;
    const displayName = (authStatus && authStatus.display_name) || '';
    const reason = authStatus && authStatus.reason;
    if (connected) {
      return `
        <section>
          <div class="section-label">Connexion Supabase</div>
          <p class="text-sm text-text-muted mb-4">
            Ta session vers la base partagée Triskell. Indispensable pour le Cockpit,
            Brouillons, Réponses, Projets clients, etc.
          </p>
          <div class="card p-5 flex items-center justify-between">
            <div class="flex items-center gap-3">
              <div class="w-10 h-10 rounded-full bg-success/15 text-success
                          flex items-center justify-center font-bold text-lg">✓</div>
              <div>
                <div class="text-sm font-semibold">Connecté</div>
                <div class="text-xs text-text-muted">${this._escape(displayName) || 'Compte Supabase actif'}</div>
              </div>
            </div>
            <button id="cfg-auth-signout" class="btn btn-secondary">Se déconnecter</button>
          </div>
        </section>
      `;
    }
    const reasonMsg = reason === 'supabase_not_configured'
      ? "Supabase n'est pas configuré (manque url/anon_key dans settings.json)."
      : "Aucune session active. Connecte-toi pour activer les pages qui en ont besoin.";
    return `
      <section>
        <div class="section-label">Connexion Supabase</div>
        <p class="text-sm text-text-muted mb-4">${reasonMsg}</p>
        <div class="card p-5 space-y-3">
          <div>
            <label class="block text-xs font-medium text-text-secondary mb-1.5">Email</label>
            <input type="email" id="cfg-auth-email"
                   placeholder="jordan@triskell-studio.fr"
                   class="w-full px-3 py-2 text-sm rounded-lg bg-bg border border-border
                          focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent"/>
          </div>
          <div>
            <label class="block text-xs font-medium text-text-secondary mb-1.5">Mot de passe</label>
            <input type="password" id="cfg-auth-password"
                   placeholder="••••••••"
                   class="w-full px-3 py-2 text-sm rounded-lg bg-bg border border-border
                          focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent"/>
          </div>
          <div class="flex items-center gap-3">
            <button id="cfg-auth-signin" class="btn btn-primary">Se connecter</button>
            <span id="cfg-auth-status" class="text-xs text-text-muted"></span>
          </div>
        </div>
      </section>
    `;
  },

  _bindAuth() {
    const signinBtn = document.getElementById('cfg-auth-signin');
    if (signinBtn) signinBtn.onclick = async () => {
      const email = document.getElementById('cfg-auth-email').value.trim();
      const password = document.getElementById('cfg-auth-password').value;
      const status = document.getElementById('cfg-auth-status');
      if (!email || !password) {
        status.textContent = 'Email et mot de passe requis.';
        status.className = 'text-xs text-danger';
        return;
      }
      status.textContent = 'Connexion…';
      status.className = 'text-xs text-text-muted';
      const r = await App.api.auth_sign_in({ email, password });
      if (r && r.ok) {
        status.textContent = 'Connecté. Rechargement…';
        status.className = 'text-xs text-success';
        setTimeout(() => this.refresh(), 600);
      } else {
        status.textContent = `Échec : ${(r && r.error) || 'inconnu'}`;
        status.className = 'text-xs text-danger';
      }
    };

    const signoutBtn = document.getElementById('cfg-auth-signout');
    if (signoutBtn) signoutBtn.onclick = async () => {
      if (!confirm('Se déconnecter de Supabase ?\n\nLes pages Cockpit, Brouillons, Réponses, etc. ne fonctionneront plus tant que tu ne te reconnectes pas.')) return;
      await App.api.auth_sign_out();
      this.refresh();
    };
  },

  _escape(s) {
    return String(s ?? '')
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  },

  // ----------------------------------------------------------------------
  // Section Signature mail (locale à ce PC, par utilisateur)
  // ----------------------------------------------------------------------
  _renderSignature() {
    return `
      <section>
        <div class="section-label">Mes signatures mail</div>
        <p class="text-sm text-text-muted mb-4">
          Crée plusieurs signatures et attribue-les à tes différentes adresses
          (ex : une pour Triskell Studio, une pour Lagriffe…). La bonne signature
          sera proposée automatiquement quand tu composes un mail.
        </p>
        <div id="cfg-sig-list" class="space-y-3 mb-4">
          <div class="text-sm text-text-muted">Chargement…</div>
        </div>
        <button id="cfg-sig-add" class="btn btn-primary">+ Nouvelle signature</button>
      </section>
    `;
  },

  async _bindSignature() {
    if (!App.api) return;
    await this._refreshSignaturesList();
    const addBtn = document.getElementById('cfg-sig-add');
    if (addBtn) addBtn.onclick = () => this._openSignatureEditor(null);
  },

  async _refreshSignaturesList() {
    const listEl = document.getElementById('cfg-sig-list');
    if (!listEl || !App.api) return;
    let signatures = [], accounts = [];
    try {
      const sr = await App.api.signatures_list();
      if (sr && sr.ok) signatures = sr.signatures || [];
      const ar = await App.api.mail_accounts_list();
      if (ar && ar.ok) accounts = ar.accounts || [];
    } catch (e) {}
    if (!signatures.length) {
      listEl.innerHTML = `<div class="text-sm text-text-muted">Aucune signature configurée.</div>`;
      return;
    }
    const accLabel = (id) => {
      const a = accounts.find(x => x.id === id);
      return a ? a.label || a.from_email || id : id;
    };
    listEl.innerHTML = signatures.map(s => {
      const accIds = s.account_ids || [];
      const accBadges = accIds.length
        ? accIds.map(id => `<span class="text-[10px] px-2 py-0.5 rounded-full bg-accent/12 text-accent font-semibold">${this._escape(accLabel(id))}</span>`).join(' ')
        : `<span class="text-[10px] px-2 py-0.5 rounded-full bg-text-muted/10 text-text-muted">Toutes les adresses</span>`;
      return `
        <div class="card p-4">
          <div class="flex items-start justify-between gap-3 mb-2">
            <div class="flex-1 min-w-0">
              <div class="text-sm font-bold truncate">${this._escape(s.name)}</div>
              <div class="flex flex-wrap gap-1 mt-1">${accBadges}</div>
            </div>
            <div class="flex gap-1 shrink-0">
              <button data-sig-edit="${this._escape(s.id)}" class="text-[11px] px-2 py-1 rounded hover:bg-bg text-text-muted hover:text-accent">Modifier</button>
              <button data-sig-rm="${this._escape(s.id)}" class="text-[11px] px-2 py-1 rounded hover:bg-bg text-text-muted hover:text-danger">Supprimer</button>
            </div>
          </div>
        </div>
      `;
    }).join('');
    // Bind actions
    listEl.querySelectorAll('[data-sig-edit]').forEach(b => {
      b.onclick = () => {
        const id = b.dataset.sigEdit;
        const sig = signatures.find(x => x.id === id);
        if (sig) this._openSignatureEditor(sig);
      };
    });
    listEl.querySelectorAll('[data-sig-rm]').forEach(b => {
      b.onclick = async () => {
        const id = b.dataset.sigRm;
        const sig = signatures.find(x => x.id === id);
        if (!confirm(`Supprimer la signature "${sig && sig.name}" ?`)) return;
        const r = await App.api.signature_remove({ id });
        if (r && r.ok) this._refreshSignaturesList();
        else alert('Échec : ' + ((r && r.error) || 'inconnu'));
      };
    });
  },

  async _openSignatureEditor(existing) {
    // Charge les comptes pour le multi-select
    let accounts = [];
    try {
      const r = await App.api.mail_accounts_list();
      if (r && r.ok) accounts = r.accounts || [];
    } catch (e) {}
    const sel = new Set((existing && existing.account_ids) || []);

    const overlay = document.createElement('div');
    overlay.className = 'fixed inset-0 z-[210] flex items-center justify-center p-4';
    overlay.style.background = 'rgba(15,23,42,0.7)';
    overlay.style.backdropFilter = 'blur(8px)';
    overlay.innerHTML = `
      <div class="bg-surface rounded-2xl shadow-hero w-full max-w-4xl h-[85vh] overflow-hidden border border-border animate-slide-up flex flex-col">
        <div class="px-6 pt-4 pb-3 flex items-center justify-between border-b border-border bg-surface-elevated">
          <div>
            <div class="hero-kicker mb-0.5">${existing ? 'MODIFIER' : 'NOUVELLE'}</div>
            <h3 class="text-base font-bold">Signature mail</h3>
          </div>
          <button id="se-close" class="w-8 h-8 rounded-lg flex items-center justify-center text-text-muted hover:text-text hover:bg-bg text-xl leading-none">×</button>
        </div>

        <div class="flex-1 overflow-y-auto px-6 py-5 space-y-4">
          <!-- Nom -->
          <div>
            <label class="block text-[11px] font-medium text-text-secondary mb-1">Nom de la signature</label>
            <input id="se-name" type="text" value="${this._escape(existing?.name || '')}" placeholder="ex : Triskell · officielle, Lagriffe · client, Court"
                   class="w-full px-3 py-2 text-sm rounded-lg bg-bg border border-border focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent"/>
          </div>

          <!-- Comptes attribués -->
          <div>
            <label class="block text-[11px] font-medium text-text-secondary mb-1">Adresses à laquelle cette signature est attribuée</label>
            <div class="text-[11px] text-text-muted mb-2">Si rien n'est coché, cette signature est disponible pour <b>toutes</b> les adresses (utile pour une signature par défaut).</div>
            <div class="flex flex-wrap gap-2">
              ${accounts.map(a => `
                <label class="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-full border border-border cursor-pointer hover:border-accent">
                  <input type="checkbox" value="${this._escape(a.id)}" ${sel.has(a.id) ? 'checked' : ''} class="se-acc"/>
                  <span>${this._escape(a.from_email || a.label)}</span>
                </label>
              `).join('')}
            </div>
          </div>

          <!-- Toggle Texte/HTML -->
          <div>
            <div class="flex items-center gap-1 text-[11px] mb-2">
              <button id="se-mode-text" class="px-3 py-1.5 rounded-lg font-semibold bg-accent/15 text-accent">Texte simple</button>
              <button id="se-mode-html" class="px-3 py-1.5 rounded-lg font-semibold text-text-muted hover:bg-bg">HTML enrichi</button>
            </div>

            <div id="se-text-zone">
              <textarea id="se-body-text" rows="6" placeholder="Jordan&#10;Triskell Studio · triskell-studio.fr&#10;06 12 34 56 78"
                        class="w-full px-3 py-2 text-sm rounded-lg bg-bg border border-border focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent font-sans leading-relaxed resize-y">${this._escape(existing?.body_text || '')}</textarea>
            </div>

            <div id="se-html-zone" class="hidden">
              <div class="grid grid-cols-1 md:grid-cols-2 gap-3" style="min-height: 240px;">
                <div class="flex flex-col">
                  <div class="text-[10px] font-bold uppercase tracking-widest text-text-muted mb-1">Code HTML</div>
                  <textarea id="se-body-html" rows="10" placeholder='<p>Cordialement,<br><strong>Jordan</strong></p>'
                            class="flex-1 px-3 py-2 text-xs rounded-lg bg-bg border border-border focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent font-mono leading-relaxed resize-y" style="min-height: 200px;">${this._escape(existing?.body_html || '')}</textarea>
                </div>
                <div class="flex flex-col">
                  <div class="text-[10px] font-bold uppercase tracking-widest text-text-muted mb-1">Aperçu (rendu mail)</div>
                  <iframe id="se-preview" sandbox="allow-same-origin"
                          class="flex-1 w-full rounded-lg border border-border bg-white" style="min-height: 200px;"></iframe>
                </div>
              </div>
            </div>
          </div>

          <div id="se-status" class="text-xs text-text-muted"></div>
        </div>

        <div class="px-6 py-3 border-t border-border bg-surface-elevated flex items-center justify-end gap-2">
          <button id="se-cancel" class="btn btn-secondary">Annuler</button>
          <button id="se-save" class="btn btn-primary">${existing ? 'Mettre à jour' : 'Créer'}</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);
    const close = () => overlay.remove();
    overlay.querySelector('#se-close').onclick = close;
    overlay.querySelector('#se-cancel').onclick = close;
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });

    const textTa = overlay.querySelector('#se-body-text');
    const htmlTa = overlay.querySelector('#se-body-html');
    const iframe = overlay.querySelector('#se-preview');
    const textZone = overlay.querySelector('#se-text-zone');
    const htmlZone = overlay.querySelector('#se-html-zone');
    const tBtn = overlay.querySelector('#se-mode-text');
    const hBtn = overlay.querySelector('#se-mode-html');

    if (htmlTa.value) this._renderSigPreview(iframe, htmlTa.value);

    const setMode = (m) => {
      if (m === 'text') {
        tBtn.className = 'px-3 py-1.5 rounded-lg font-semibold bg-accent/15 text-accent';
        hBtn.className = 'px-3 py-1.5 rounded-lg font-semibold text-text-muted hover:bg-bg';
        textZone.classList.remove('hidden');
        htmlZone.classList.add('hidden');
      } else {
        tBtn.className = 'px-3 py-1.5 rounded-lg font-semibold text-text-muted hover:bg-bg';
        hBtn.className = 'px-3 py-1.5 rounded-lg font-semibold bg-accent/15 text-accent';
        textZone.classList.add('hidden');
        htmlZone.classList.remove('hidden');
        if (!htmlTa.value.trim() && textTa.value.trim()) {
          htmlTa.value = textTa.value.split(/\n\n+/)
            .map(p => `<p>${this._escape(p).replace(/\n/g, '<br>')}</p>`).join('');
          this._renderSigPreview(iframe, htmlTa.value);
        }
      }
    };
    tBtn.onclick = () => setMode('text');
    hBtn.onclick = () => setMode('html');

    let timer = null;
    htmlTa.addEventListener('input', () => {
      clearTimeout(timer);
      timer = setTimeout(() => this._renderSigPreview(iframe, htmlTa.value), 200);
    });

    overlay.querySelector('#se-save').onclick = async () => {
      const status = overlay.querySelector('#se-status');
      const name = overlay.querySelector('#se-name').value.trim();
      if (!name) {
        status.textContent = '✗ Nom requis.';
        status.className = 'text-xs text-danger';
        return;
      }
      const account_ids = Array.from(overlay.querySelectorAll('.se-acc'))
        .filter(c => c.checked).map(c => c.value);
      const sigData = {
        id: existing?.id,
        name,
        body_text: textTa.value,
        body_html: htmlTa.value,
        account_ids,
      };
      status.textContent = 'Sauvegarde…';
      status.className = 'text-xs text-text-muted';
      const r = await App.api.signature_save({ signature: sigData });
      if (r && r.ok) {
        status.textContent = '✓ Sauvegardé.';
        status.className = 'text-xs text-success';
        setTimeout(() => { close(); this._refreshSignaturesList(); }, 600);
      } else {
        status.textContent = `✗ ${(r && r.error) || 'Erreur'}`;
        status.className = 'text-xs text-danger';
      }
    };
  },

  _renderSigPreview(iframe, html) {
    if (!iframe) return;
    if (!html.trim()) { iframe.srcdoc = ''; return; }
    iframe.srcdoc = `<!DOCTYPE html><html><head><meta charset="utf-8">
<style>body{margin:0;padding:14px;font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;font-size:14px;line-height:1.55;color:#1a1a20;background:#fff;}
p{margin:0 0 10px;}a{color:#5b5fd6;}img{max-width:100%;height:auto;}</style>
</head><body>${html}</body></html>`;
  },

  // ----------------------------------------------------------------------
  // Section Comptes mail secondaires
  // ----------------------------------------------------------------------
  _renderMailAccounts() {
    return `
      <section id="cfg-mail-accounts">
        <div class="section-label">Adresses mail secondaires</div>
        <p class="text-sm text-text-muted mb-4">
          En plus du compte principal (au-dessus), tu peux ajouter d'autres adresses
          (ex : <code class="text-xs">contact@lagriffe-studio.fr</code>,
          <code class="text-xs">contact@studio-wow.fr</code>) pour envoyer ou recevoir
          des mails depuis chacune.
        </p>
        <div id="cfg-mail-accounts-list" class="space-y-3 mb-4">
          <div class="text-sm text-text-muted">Chargement…</div>
        </div>
        <button id="cfg-mail-account-add" class="btn btn-primary">+ Ajouter une adresse</button>
      </section>
    `;
  },

  async _bindMailAccounts() {
    const listEl = document.getElementById('cfg-mail-accounts-list');
    if (!listEl) return;
    if (!App.api) {
      listEl.innerHTML = `<div class="text-xs text-text-muted">Backend non disponible.</div>`;
      return;
    }
    let r;
    try { r = await App.api.mail_accounts_list(); }
    catch (e) { r = null; }
    if (!r || !r.ok) {
      listEl.innerHTML = `<div class="text-xs text-danger">Erreur : ${(r && r.error) || 'inconnu'}</div>`;
      return;
    }
    const accounts = r.accounts || [];
    if (!accounts.length) {
      listEl.innerHTML = `<div class="text-sm text-text-muted">Aucune adresse configurée.</div>`;
    } else {
      listEl.innerHTML = accounts.map(a => this._mailAccountRow(a)).join('');
    }
    // Bind suppression
    listEl.querySelectorAll('[data-mail-remove]').forEach(btn => {
      btn.onclick = async () => {
        const aid = btn.dataset.mailRemove;
        if (!confirm(`Supprimer l'adresse "${aid}" ?\n\nLa boîte ne sera plus consultée et tu ne pourras plus envoyer depuis cette adresse.`)) return;
        const resp = await App.api.mail_account_remove({ id: aid });
        if (resp && resp.ok) this._bindMailAccounts();
        else alert(`Échec : ${resp && resp.error || 'inconnu'}`);
      };
    });
    // Bind test connexion
    listEl.querySelectorAll('[data-mail-test]').forEach(btn => {
      btn.onclick = async () => {
        const aid = btn.dataset.mailTest;
        const status = document.getElementById(`mail-test-${aid}`);
        status.textContent = 'Test en cours…';
        const resp = await App.api.mail_account_test({ id: aid });
        if (resp && resp.ok) {
          status.textContent = `✓ SMTP + IMAP OK`;
          status.className = 'text-xs text-success';
        } else {
          status.textContent = `✗ ${(resp && resp.error) || 'échec'}`;
          status.className = 'text-xs text-danger';
        }
      };
    });
    // Bind bouton ajouter
    const addBtn = document.getElementById('cfg-mail-account-add');
    if (addBtn) addBtn.onclick = () => this._openMailAccountForm();
  },

  _mailAccountRow(a) {
    const primary = a.is_primary;
    const pwdOk = a._has_smtp_pwd && a._has_imap_pwd;
    return `
      <div class="card p-4">
        <div class="flex items-start justify-between gap-3">
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-2 mb-1">
              <div class="text-sm font-bold truncate">${this._escape(a.label)}</div>
              ${primary ? '<span class="text-[9px] font-bold uppercase px-1.5 py-0.5 rounded bg-accent/15 text-accent">Principal</span>' : ''}
              ${!pwdOk ? '<span class="text-[9px] font-bold uppercase px-1.5 py-0.5 rounded bg-warning/15 text-warning">Mot de passe manquant</span>' : ''}
            </div>
            <div class="text-xs text-text-muted truncate">${this._escape(a.from_email)}</div>
            <div class="text-[11px] text-text-muted mt-1">
              SMTP ${this._escape(a.smtp_host)}:${a.smtp_port} · IMAP ${this._escape(a.imap_host)}:${a.imap_port}
            </div>
            <div id="mail-test-${this._escape(a.id)}" class="text-xs text-text-muted mt-2"></div>
          </div>
          <div class="flex flex-col gap-1.5">
            <button data-mail-test="${this._escape(a.id)}" class="btn btn-secondary text-xs px-3 py-1">Tester</button>
            ${primary ? '' : `<button data-mail-remove="${this._escape(a.id)}" class="btn btn-secondary text-xs px-3 py-1 text-danger">Supprimer</button>`}
          </div>
        </div>
      </div>
    `;
  },

  _openMailAccountForm(existing = null) {
    const overlay = document.createElement('div');
    overlay.className = 'fixed inset-0 z-[200] flex items-center justify-center p-6';
    overlay.style.background = 'rgba(15,23,42,0.6)';
    overlay.style.backdropFilter = 'blur(6px)';
    overlay.innerHTML = `
      <div class="bg-surface rounded-2xl shadow-hero w-full max-w-lg overflow-hidden border border-border animate-slide-up">
        <div class="px-6 pt-5 pb-3 border-b border-border">
          <div class="hero-kicker mb-1">${existing ? 'MODIFIER' : 'AJOUTER'}</div>
          <h3 class="text-lg font-bold">Adresse mail secondaire</h3>
        </div>
        <div class="px-6 py-5 space-y-3 max-h-[70vh] overflow-y-auto">
          ${this._mailField('id',           'Identifiant interne (ex: lagriffe)', existing?.id || '', 'text', existing != null)}
          ${this._mailField('label',        'Nom affiché',                        existing?.label || '')}
          ${this._mailField('from_email',   'Adresse mail (envoi & réception)',   existing?.from_email || '', 'email')}
          ${this._mailField('from_name',    'Signature expéditeur (ex: Lagriffe Studio)', existing?.from_name || '')}
          <div class="grid grid-cols-2 gap-3">
            ${this._mailField('smtp_host',  'SMTP host',  existing?.smtp_host || 'smtp.ionos.fr')}
            ${this._mailField('smtp_port',  'SMTP port',  existing?.smtp_port || 587, 'number')}
          </div>
          ${this._mailField('smtp_user',    'SMTP user (souvent = adresse mail)',  existing?.smtp_user || existing?.from_email || '')}
          ${this._mailField('smtp_password', existing && existing._has_smtp_pwd ? "SMTP mot de passe (laisser vide pour conserver l'actuel)" : 'SMTP mot de passe', '', 'password')}
          <div class="grid grid-cols-2 gap-3">
            ${this._mailField('imap_host',  'IMAP host',  existing?.imap_host || 'imap.ionos.fr')}
            ${this._mailField('imap_port',  'IMAP port',  existing?.imap_port || 993, 'number')}
          </div>
          ${this._mailField('imap_user',    'IMAP user (souvent = adresse mail)',  existing?.imap_user || existing?.from_email || '')}
          ${this._mailField('imap_password', existing && existing._has_imap_pwd ? "IMAP mot de passe (laisser vide pour conserver l'actuel)" : 'IMAP mot de passe', '', 'password')}
          <div id="mail-form-status" class="text-xs text-text-muted"></div>
        </div>
        <div class="px-6 py-4 border-t border-border flex justify-end gap-2">
          <button id="mail-form-cancel" class="btn btn-secondary">Annuler</button>
          <button id="mail-form-save"   class="btn btn-primary">Enregistrer</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);
    const close = () => overlay.remove();
    document.getElementById('mail-form-cancel').onclick = close;
    document.getElementById('mail-form-save').onclick = async () => {
      const acc = {};
      ['id','label','from_email','from_name','smtp_host','smtp_user','smtp_password',
       'imap_host','imap_user','imap_password'].forEach(k => {
        const el = overlay.querySelector(`[data-mail-field="${k}"]`);
        acc[k] = el ? el.value.trim() : '';
      });
      acc.smtp_port = parseInt(overlay.querySelector('[data-mail-field="smtp_port"]').value, 10) || 587;
      acc.imap_port = parseInt(overlay.querySelector('[data-mail-field="imap_port"]').value, 10) || 993;
      const status = document.getElementById('mail-form-status');
      // Validation basique
      if (!acc.id || !/^[a-z0-9_-]+$/.test(acc.id)) {
        status.textContent = 'Identifiant invalide (lettres minuscules, chiffres, - et _).';
        status.className = 'text-xs text-danger'; return;
      }
      if (!acc.from_email || !acc.from_email.includes('@')) {
        status.textContent = 'Adresse mail invalide.';
        status.className = 'text-xs text-danger'; return;
      }
      status.textContent = 'Enregistrement…';
      status.className = 'text-xs text-text-muted';
      const r = await App.api.mail_account_save({ account: acc });
      if (r && r.ok) {
        status.textContent = 'Enregistré.';
        status.className = 'text-xs text-success';
        setTimeout(() => { close(); this._bindMailAccounts(); }, 400);
      } else {
        status.textContent = `Échec : ${(r && r.error) || 'inconnu'}`;
        status.className = 'text-xs text-danger';
      }
    };
  },

  _mailField(name, label, value, type = 'text', readonly = false) {
    const safeVal = String(value ?? '').replace(/"/g, '&quot;');
    return `
      <div>
        <label class="block text-xs font-medium text-text-secondary mb-1">${this._escape(label)}</label>
        <input data-mail-field="${name}" type="${type}" value="${safeVal}" ${readonly ? 'readonly' : ''}
               class="w-full px-3 py-2 text-sm rounded-lg bg-bg border border-border focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent ${readonly ? 'opacity-60' : ''}"/>
      </div>
    `;
  },

  _renderAppearance(s) {
    const cur = s ? s.appearance_mode : 'mid';
    const modes = [
      { key: 'light', label: 'Claire',        desc: 'Surfaces blanches, ambiance Apple-light.' },
      { key: 'mid',   label: 'Intermédiaire', desc: 'Graphite chaud, sweet spot reposant.' },
      { key: 'dark',  label: 'Sombre',        desc: 'Cockpit nuit, pour la concentration.' },
    ];
    return `
      <section>
        <div class="section-label">Apparence</div>
        <p class="text-sm text-text-muted mb-4">
          Trois ambiances. Tu peux aussi cycler avec Ctrl+T.
        </p>
        <div class="grid grid-cols-3 gap-4">
          ${modes.map(m => {
            const active = m.key === cur;
            return `
              <button data-theme-mode="${m.key}"
                      class="card p-5 text-left transition-all hover:translate-y-[-1px]"
                      style="${active ? 'border-color: hsl(var(--accent)); border-width: 2px; background: hsl(var(--accent) / 0.06);' : ''}">
                <div class="text-[10px] font-bold tracking-widest mb-1
                            ${active ? 'text-accent' : 'text-text-muted'}">
                  ${m.label.toUpperCase()}
                </div>
                <div class="text-sm text-text-secondary mb-3">${m.desc}</div>
                <div class="text-[11px] font-semibold ${active ? 'text-accent' : 'text-text-muted'}">
                  ${active ? '✓ Actif' : 'Choisir →'}
                </div>
              </button>
            `;
          }).join('')}
        </div>
      </section>
    `;
  },

  _renderAi(s) {
    const ai = (s && s.ai) || { api_keys: {} };
    const keys = ai.api_keys || {};
    const providers = [
      { id: 'anthropic', label: 'Anthropic (Claude)', recommended: false },
      { id: 'google',    label: 'Google (Gemini) — gratuit', recommended: true },
      { id: 'openai',    label: 'OpenAI (GPT)',     recommended: false },
      { id: 'mistral',   label: 'Mistral',          recommended: false },
      { id: 'xai',       label: 'xAI (Grok)',       recommended: false },
    ];
    return `
      <section>
        <div class="section-label">Services IA</div>
        <p class="text-sm text-text-muted mb-4">
          Tes clés sont stockées localement et jamais envoyées hors de l'app.
        </p>
        <div class="card p-6 space-y-4">
          ${providers.map(p => {
            const has = !!keys[p.id];
            return `
              <div>
                <label class="block text-sm font-semibold mb-1">
                  ${this._esc(p.label)}
                  ${p.recommended ? '<span class="ml-2 text-[10px] bg-success/15 text-success px-2 py-0.5 rounded-full font-bold">RECOMMANDÉ</span>' : ''}
                </label>
                <input type="password"
                       data-save-path="ai.api_keys.${p.id}"
                       placeholder="${has ? '(clé enregistrée — tape pour remplacer)' : 'Clé API…'}"
                       class="w-full px-4 py-2.5 text-sm rounded-xl bg-bg border border-border
                              focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent" />
              </div>
            `;
          }).join('')}
        </div>
      </section>
    `;
  },

  _renderOutreach(s) {
    const o = (s && s.outreach) || {};
    return `
      <section>
        <div class="section-label">Compte mail (envoi & réception)</div>
        <p class="text-sm text-text-muted mb-4">
          Identifiants de ton fournisseur (Gmail, IONOS, OVH…). Mot de passe
          d'application requis si Gmail.
        </p>
        <div class="card p-6 space-y-4">
          ${this._field('Adresse mail (envoi)', 'outreach.from_email', o.from_email, 'email')}
          ${this._field('Nom affiché', 'outreach.from_name', o.from_name)}
          <div class="grid grid-cols-2 gap-4">
            ${this._field('Serveur d\'envoi (SMTP)', 'outreach.smtp_host', o.smtp_host, 'text', 'smtp.ionos.fr')}
            ${this._field('Port SMTP', 'outreach.smtp_port', o.smtp_port, 'number', '587')}
          </div>
          ${this._field('Identifiant SMTP', 'outreach.smtp_user', o.smtp_user)}
          ${this._field('Mot de passe SMTP', 'outreach.smtp_password', '', 'password', 'tape pour modifier')}
          <div class="grid grid-cols-2 gap-4">
            ${this._field('Serveur de réception (IMAP)', 'outreach.imap_host', o.imap_host, 'text', 'imap.ionos.fr')}
            ${this._field('Port IMAP', 'outreach.imap_port', o.imap_port, 'number', '993')}
          </div>
          ${this._field('Identifiant IMAP', 'outreach.imap_user', o.imap_user)}
          ${this._field('Mot de passe IMAP', 'outreach.imap_password', '', 'password', 'tape pour modifier')}
          <div class="grid grid-cols-2 gap-4">
            ${this._field('Plafond quotidien', 'outreach.daily_cap', o.daily_cap, 'number', '40')}
            ${this._field('Délai relance (jours)', 'outreach.follow_up_days', o.follow_up_days, 'number', '5')}
          </div>
        </div>
      </section>
    `;
  },

  _renderStripe(cfg) {
    const c = cfg || { enabled: false, secret_key: '', poll_minutes: 5,
                       product_mapping: {}, default_product_key: '_default',
                       default_product_name: 'Commande Stripe', _has_key: false };
    const mapping = c.product_mapping || {};
    const mappingRows = Object.entries(mapping)
      .filter(([k]) => !k.endsWith('_name'))
      .map(([stripeId, prodKey], i) => `
        <div class="grid grid-cols-12 gap-2 items-center" data-map-row="${i}">
          <input type="text" data-map-stripe="${i}" value="${this._esc(stripeId)}"
                 placeholder="prod_xxx ou price_xxx"
                 class="col-span-5 px-2 py-1.5 rounded-lg bg-bg border border-border text-sm focus:border-accent focus:outline-none" />
          <input type="text" data-map-key="${i}" value="${this._esc(prodKey)}"
                 placeholder="pack-electricien-pro"
                 class="col-span-4 px-2 py-1.5 rounded-lg bg-bg border border-border text-sm focus:border-accent focus:outline-none" />
          <input type="text" data-map-name="${i}" value="${this._esc(mapping[stripeId + '_name'] || '')}"
                 placeholder="Nom affiché"
                 class="col-span-2 px-2 py-1.5 rounded-lg bg-bg border border-border text-sm focus:border-accent focus:outline-none" />
          <button class="col-span-1 text-text-muted hover:text-danger text-lg leading-none" data-map-del="${i}" title="Supprimer">×</button>
        </div>
      `).join('');

    return `
      <section>
        <div class="section-label">Paiements Stripe → livraison auto</div>
        <p class="text-sm text-text-muted mb-4">
          Quand un client paie sur Stripe, l'app crée automatiquement une carte
          projet (statut Briefing, payée). Le mail de bienvenue + livrables du
          kit du produit partent immédiatement après.
        </p>
        <div class="card p-6 space-y-4">
          <label class="flex items-start gap-3 cursor-pointer">
            <input type="checkbox" data-stripe-key="enabled" ${c.enabled?'checked':''}
                   class="mt-0.5 w-4 h-4 accent-accent" />
            <div>
              <div class="text-sm font-medium">Activer le polling Stripe</div>
              <div class="text-xs text-text-muted">Vérifie les nouveaux paiements toutes les 5 minutes (configurable).</div>
            </div>
          </label>

          <div>
            <label class="block text-xs font-medium text-text-secondary mb-1.5">
              Clé secrète Stripe ${c._has_key ? '<span class="text-success">(✓ enregistrée)</span>' : ''}
            </label>
            <input type="password" data-stripe-key="secret_key"
                   placeholder="${c._has_key ? '(clé enregistrée — tape pour remplacer)' : 'sk_live_… ou sk_test_…'}"
                   class="w-full px-3 py-2 rounded-lg bg-bg border border-border text-sm focus:border-accent focus:outline-none font-mono" />
            <div class="text-[11px] text-text-muted mt-1">
              Trouvable dans Stripe Dashboard → Développeurs → Clés API. Stockée chiffrée dans la base partagée.
            </div>
          </div>

          <div class="grid grid-cols-2 gap-4">
            <div>
              <label class="block text-xs font-medium text-text-secondary mb-1.5">Fréquence (minutes)</label>
              <input type="number" min="1" max="60" data-stripe-key="poll_minutes" value="${c.poll_minutes || 5}"
                     class="w-32 px-3 py-2 rounded-lg bg-bg border border-border text-sm focus:border-accent focus:outline-none" />
            </div>
          </div>

          <div>
            <div class="flex items-center justify-between mb-2">
              <label class="text-xs font-bold tracking-widest text-text-muted">MAPPING PRODUITS STRIPE → KIT TRISKELL</label>
              <button class="text-[11px] text-accent hover:underline" id="stripe-add-map">+ Ajouter</button>
            </div>
            <div class="text-xs text-text-muted mb-3">
              Pour chaque produit Stripe, dis quel kit de livraison Triskell utiliser.
              Le « product_id » Stripe se trouve dans Stripe Dashboard → Produits.
            </div>
            <div id="stripe-mapping" class="space-y-2">
              ${mappingRows || '<div class="text-text-muted text-xs py-2">Aucun mapping. Sans mapping, tous les paiements utilisent le kit générique.</div>'}
            </div>
          </div>

          <div class="grid grid-cols-2 gap-4 pt-2">
            <div>
              <label class="block text-xs font-medium text-text-secondary mb-1.5">Kit par défaut (si non mappé)</label>
              <input type="text" data-stripe-key="default_product_key" value="${this._esc(c.default_product_key || '_default')}"
                     class="w-full px-3 py-2 rounded-lg bg-bg border border-border text-sm focus:border-accent focus:outline-none" />
            </div>
            <div>
              <label class="block text-xs font-medium text-text-secondary mb-1.5">Nom affiché par défaut</label>
              <input type="text" data-stripe-key="default_product_name" value="${this._esc(c.default_product_name || 'Commande Stripe')}"
                     class="w-full px-3 py-2 rounded-lg bg-bg border border-border text-sm focus:border-accent focus:outline-none" />
            </div>
          </div>

          <div class="flex gap-3 pt-2">
            <button class="btn btn-primary" id="stripe-save">Enregistrer</button>
            <button class="btn btn-secondary" id="stripe-test">Tester maintenant</button>
            <span id="stripe-feedback" class="text-xs text-text-muted self-center"></span>
          </div>
        </div>
      </section>
    `;
  },

  _bindStripe() {
    const save = document.getElementById('stripe-save');
    const test = document.getElementById('stripe-test');
    const fb   = document.getElementById('stripe-feedback');
    const addMap = document.getElementById('stripe-add-map');
    if (!save) return;

    const gather = () => {
      const v = (k) => {
        const el = document.querySelector(`[data-stripe-key="${k}"]`);
        if (!el) return undefined;
        if (el.type === 'checkbox') return !!el.checked;
        if (el.type === 'number')   return parseInt(el.value, 10) || 0;
        return el.value;
      };
      // Mapping
      const mapping = {};
      document.querySelectorAll('[data-map-row]').forEach(row => {
        const idx = row.dataset.mapRow;
        const sid = (document.querySelector(`[data-map-stripe="${idx}"]`) || {}).value || '';
        const pk  = (document.querySelector(`[data-map-key="${idx}"]`)    || {}).value || '';
        const nm  = (document.querySelector(`[data-map-name="${idx}"]`)   || {}).value || '';
        if (sid && pk) {
          mapping[sid] = pk;
          if (nm) mapping[sid + '_name'] = nm;
        }
      });
      return {
        enabled: v('enabled'),
        secret_key: v('secret_key'),  // si masquée (•), api.py garde l'existante
        poll_minutes: v('poll_minutes'),
        product_mapping: mapping,
        default_product_key:  v('default_product_key'),
        default_product_name: v('default_product_name'),
      };
    };

    save.onclick = async () => {
      if (!App.api) return;
      save.disabled = true; save.textContent = 'Enregistrement…';
      try {
        const r = await App.api.stripe_save_config({ config: gather() });
        save.textContent = (r && r.ok) ? 'Enregistré ✓' : 'Erreur';
      } catch (e) { save.textContent = 'Erreur'; }
      setTimeout(() => { save.disabled = false; save.textContent = 'Enregistrer'; }, 1600);
    };

    test.onclick = async () => {
      if (!App.api) return;
      test.disabled = true; test.textContent = 'Test en cours…';
      fb.textContent = '';
      try {
        await App.api.stripe_save_config({ config: gather() });
        const r = await App.api.stripe_run_now();
        if (r && r.ok && r.result) {
          const c = r.result;
          fb.textContent = `Polled: ${c.polled}, nouveaux: ${c.new_payments}, projets créés: ${c.projects_created}, erreurs: ${c.errors}` +
                            (c.error ? ` — ${c.error}` : '');
        } else {
          fb.textContent = 'Erreur : ' + ((r && r.error) || 'inconnu');
        }
      } catch (e) { fb.textContent = 'Erreur : ' + e; }
      test.disabled = false; test.textContent = 'Tester maintenant';
    };

    if (addMap) addMap.onclick = () => {
      const wrap = document.getElementById('stripe-mapping');
      const idx = Date.now();
      const row = document.createElement('div');
      row.className = 'grid grid-cols-12 gap-2 items-center';
      row.dataset.mapRow = idx;
      row.innerHTML = `
        <input type="text" data-map-stripe="${idx}" placeholder="prod_xxx ou price_xxx"
               class="col-span-5 px-2 py-1.5 rounded-lg bg-bg border border-border text-sm focus:border-accent focus:outline-none" />
        <input type="text" data-map-key="${idx}" placeholder="pack-electricien-pro"
               class="col-span-4 px-2 py-1.5 rounded-lg bg-bg border border-border text-sm focus:border-accent focus:outline-none" />
        <input type="text" data-map-name="${idx}" placeholder="Nom affiché"
               class="col-span-2 px-2 py-1.5 rounded-lg bg-bg border border-border text-sm focus:border-accent focus:outline-none" />
        <button class="col-span-1 text-text-muted hover:text-danger text-lg leading-none" data-map-del="${idx}">×</button>
      `;
      // Si placeholder text "Aucun mapping..." : on le supprime
      const placeholder = wrap.querySelector('div.text-text-muted');
      if (placeholder) placeholder.remove();
      wrap.appendChild(row);
      row.querySelector('[data-map-del]').onclick = () => row.remove();
    };

    // Bind delete sur les rows déjà rendues
    document.querySelectorAll('[data-map-del]').forEach(b => {
      b.onclick = () => {
        const row = b.closest('[data-map-row]');
        if (row) row.remove();
      };
    });
  },

  _renderCalendly(cfg) {
    const c = cfg || { enabled: false, personal_access_token: '',
                       default_event_type_uri: '', default_event_type_name: '',
                       _has_token: false };
    return `
      <section>
        <div class="section-label">Calendly — propose un créneau en 1 clic</div>
        <p class="text-sm text-text-muted mb-4">
          Quand un prospect dit « ok, on en parle ? », tu cliques « Proposer créneau »
          dans la vue Réponses et l'app envoie un mail avec un lien Calendly à usage unique.
        </p>
        <div class="card p-6 space-y-4">
          <div>
            <label class="block text-xs font-medium text-text-secondary mb-1.5">
              Personal Access Token Calendly
              ${c._has_token ? '<span class="text-success">(✓ enregistré)</span>' : ''}
            </label>
            <input type="password" data-cal-key="personal_access_token"
                   placeholder="${c._has_token ? '(token enregistré — tape pour remplacer)' : 'eyJ…'}"
                   class="w-full px-3 py-2 rounded-lg bg-bg border border-border text-sm focus:border-accent focus:outline-none font-mono" />
            <div class="text-[11px] text-text-muted mt-1">
              Génère-le dans Calendly → Integrations → API & Webhooks → Personal Access Tokens.
            </div>
          </div>

          <div>
            <label class="block text-xs font-medium text-text-secondary mb-1.5">Type de RDV par défaut</label>
            <div class="flex gap-2">
              <select id="cal-event-select" data-cal-key="default_event_type_uri"
                      class="flex-1 px-3 py-2 rounded-lg bg-bg border border-border text-sm focus:border-accent focus:outline-none">
                ${c.default_event_type_uri
                  ? `<option value="${this._esc(c.default_event_type_uri)}" selected>${this._esc(c.default_event_type_name || '(actuel)')}</option>`
                  : `<option value="">— Charge la liste ↓ —</option>`}
              </select>
              <button class="btn btn-secondary text-xs" id="cal-refresh-events">Charger mes types de RDV</button>
            </div>
          </div>

          <div class="flex gap-3 pt-2">
            <button class="btn btn-primary" id="cal-save">Enregistrer</button>
            <button class="btn btn-secondary" id="cal-test">Vérifier la connexion</button>
            <span id="cal-feedback" class="text-xs text-text-muted self-center"></span>
          </div>
        </div>
      </section>
    `;
  },

  _bindCalendly() {
    const save = document.getElementById('cal-save');
    const test = document.getElementById('cal-test');
    const refresh = document.getElementById('cal-refresh-events');
    const fb = document.getElementById('cal-feedback');
    const select = document.getElementById('cal-event-select');
    if (!save) return;

    const gather = () => {
      const tk = (document.querySelector('[data-cal-key="personal_access_token"]') || {}).value || '';
      const sel = document.querySelector('[data-cal-key="default_event_type_uri"]');
      const evtUri = sel ? sel.value : '';
      const evtName = sel && sel.selectedOptions[0] ? sel.selectedOptions[0].textContent : '';
      return {
        enabled: !!tk,
        personal_access_token: tk,
        default_event_type_uri: evtUri,
        default_event_type_name: evtName,
      };
    };

    save.onclick = async () => {
      if (!App.api) return;
      save.disabled = true; save.textContent = 'Enregistrement…';
      try {
        const r = await App.api.calendly_save_config({ config: gather() });
        save.textContent = (r && r.ok) ? 'Enregistré ✓' : 'Erreur';
      } catch (e) { save.textContent = 'Erreur'; }
      setTimeout(() => { save.disabled = false; save.textContent = 'Enregistrer'; }, 1600);
    };

    test.onclick = async () => {
      if (!App.api) return;
      test.disabled = true; test.textContent = '…';
      fb.textContent = '';
      try {
        await App.api.calendly_save_config({ config: gather() });
        const r = await App.api.calendly_test();
        if (r && r.ok) {
          fb.innerHTML = `<span class="text-success">✓ Connecté en tant que ${this._esc(r.user_name || r.user_email || '?')}</span>`;
        } else {
          fb.innerHTML = `<span class="text-danger">✗ ${this._esc(r && r.error || 'erreur')}</span>`;
        }
      } catch (e) { fb.textContent = 'Erreur : ' + e; }
      test.disabled = false; test.textContent = 'Vérifier la connexion';
    };

    if (refresh) refresh.onclick = async () => {
      if (!App.api) return;
      refresh.disabled = true; refresh.textContent = 'Chargement…';
      try {
        await App.api.calendly_save_config({ config: gather() });
        const r = await App.api.calendly_list_event_types();
        if (r && r.ok && r.event_types) {
          select.innerHTML = r.event_types.map(e =>
            `<option value="${this._esc(e.uri)}">${this._esc(e.name)} (${e.duration} min)</option>`
          ).join('');
          fb.innerHTML = `<span class="text-success">${r.event_types.length} type(s) de RDV chargé(s)</span>`;
        } else {
          fb.innerHTML = `<span class="text-danger">${this._esc(r && r.error || 'erreur')}</span>`;
        }
      } catch (e) { fb.textContent = 'Erreur : ' + e; }
      refresh.disabled = false; refresh.textContent = 'Charger mes types de RDV';
    };
  },

  _renderPhantombuster(cfg) {
    const c = cfg || { enabled: false, api_key: '', agent_id: '',
                       max_per_launch: 10, _has_key: false };
    return `
      <section>
        <div class="section-label">Phantombuster — DM LinkedIn auto</div>
        <p class="text-sm text-text-muted mb-4">
          Service tiers (~70 €/mois) qui envoie tes DM LinkedIn rate-limité
          (~25/jour) via ton compte. Triskell Command lui envoie la liste.
        </p>
        <div class="card p-6 space-y-4">
          <label class="flex items-start gap-3 cursor-pointer">
            <input type="checkbox" data-pb-key="enabled" ${c.enabled?'checked':''}
                   class="mt-0.5 w-4 h-4 accent-accent" />
            <div>
              <div class="text-sm font-medium">Activer l'envoi auto via Phantombuster</div>
              <div class="text-xs text-text-muted">
                Si désactivé, les relances LinkedIn restent à envoyer manuellement (3 clics depuis le Cockpit).
              </div>
            </div>
          </label>

          <div>
            <label class="block text-xs font-medium text-text-secondary mb-1.5">
              Clé API Phantombuster
              ${c._has_key ? '<span class="text-success">(✓ enregistrée)</span>' : ''}
            </label>
            <input type="password" data-pb-key="api_key"
                   placeholder="${c._has_key ? '(clé enregistrée — tape pour remplacer)' : 'Ta clé API'}"
                   class="w-full px-3 py-2 rounded-lg bg-bg border border-border text-sm focus:border-accent focus:outline-none font-mono" />
            <div class="text-[11px] text-text-muted mt-1">
              Trouvable dans Phantombuster → Settings → API key.
            </div>
          </div>

          <div>
            <label class="block text-xs font-medium text-text-secondary mb-1.5">ID du Phantom « LinkedIn Message Sender »</label>
            <input type="text" data-pb-key="agent_id" value="${this._esc(c.agent_id || '')}"
                   placeholder="ex : 1234567890123456"
                   class="w-full px-3 py-2 rounded-lg bg-bg border border-border text-sm focus:border-accent focus:outline-none font-mono" />
            <div class="text-[11px] text-text-muted mt-1">
              Crée un Phantom « LinkedIn Message Sender » sur Phantombuster, copie son ID depuis l'URL.
            </div>
          </div>

          <div>
            <label class="block text-xs font-medium text-text-secondary mb-1.5">Max DMs par lancement</label>
            <input type="number" min="1" max="50" data-pb-key="max_per_launch" value="${c.max_per_launch || 10}"
                   class="w-32 px-3 py-2 rounded-lg bg-bg border border-border text-sm focus:border-accent focus:outline-none" />
            <div class="text-[11px] text-text-muted mt-1">Phantombuster espace les envois (~25/jour côté LinkedIn).</div>
          </div>

          <div class="flex gap-3 pt-2">
            <button class="btn btn-primary" id="pb-save">Enregistrer</button>
            <button class="btn btn-secondary" id="pb-test">Vérifier la connexion</button>
            <span id="pb-feedback" class="text-xs text-text-muted self-center"></span>
          </div>
        </div>
      </section>
    `;
  },

  _bindPhantombuster() {
    const save = document.getElementById('pb-save');
    const test = document.getElementById('pb-test');
    const fb = document.getElementById('pb-feedback');
    if (!save) return;
    const gather = () => {
      const v = (k) => {
        const el = document.querySelector(`[data-pb-key="${k}"]`);
        if (!el) return undefined;
        if (el.type === 'checkbox') return !!el.checked;
        if (el.type === 'number') return parseInt(el.value, 10) || 0;
        return el.value;
      };
      return {
        enabled: v('enabled'),
        api_key: v('api_key'),
        agent_id: v('agent_id'),
        max_per_launch: v('max_per_launch'),
      };
    };
    save.onclick = async () => {
      if (!App.api) return;
      save.disabled = true; save.textContent = 'Enregistrement…';
      try {
        const r = await App.api.phantombuster_save_config({ config: gather() });
        save.textContent = (r && r.ok) ? 'Enregistré ✓' : 'Erreur';
      } catch (e) { save.textContent = 'Erreur'; }
      setTimeout(() => { save.disabled = false; save.textContent = 'Enregistrer'; }, 1600);
    };
    test.onclick = async () => {
      if (!App.api) return;
      test.disabled = true; test.textContent = '…';
      fb.textContent = '';
      try {
        await App.api.phantombuster_save_config({ config: gather() });
        const r = await App.api.phantombuster_test();
        if (r && r.ok) {
          fb.innerHTML = `<span class="text-success">✓ Connecté — ${r.agents_count || 0} Phantom(s) trouvé(s)</span>`;
        } else {
          fb.innerHTML = `<span class="text-danger">✗ ${this._esc(r && r.error || 'erreur')}</span>`;
        }
      } catch (e) { fb.textContent = 'Erreur : ' + e; }
      test.disabled = false; test.textContent = 'Vérifier la connexion';
    };
  },

  _renderTracker(cfg) {
    const c = cfg || { enabled: false, pixel_endpoint: '' };
    return `
      <section>
        <div class="section-label">Tracking d'ouvertures de mail</div>
        <p class="text-sm text-text-muted mb-4">
          Ajoute un pixel transparent 1×1 dans tes mails pour mesurer les
          ouvertures. Demande de déployer une mini-fonction Netlify gratuite
          (cf. <code>netlify_functions/README.md</code>, ~5 min).
        </p>
        <div class="card p-6 space-y-4">
          <label class="flex items-start gap-3 cursor-pointer">
            <input type="checkbox" data-trk-key="enabled" ${c.enabled?'checked':''}
                   class="mt-0.5 w-4 h-4 accent-accent" />
            <div>
              <div class="text-sm font-medium">Activer le tracking d'ouvertures</div>
              <div class="text-xs text-text-muted">
                Tous les mails sortants incluront un pixel invisible. RGPD-friendly (pas d'IP/UA logués).
              </div>
            </div>
          </label>

          <div>
            <label class="block text-xs font-medium text-text-secondary mb-1.5">URL de la Netlify Function</label>
            <input type="text" data-trk-key="pixel_endpoint" value="${this._esc(c.pixel_endpoint || '')}"
                   placeholder="https://triskell-track.netlify.app/.netlify/functions/track-pixel"
                   class="w-full px-3 py-2 rounded-lg bg-bg border border-border text-sm focus:border-accent focus:outline-none font-mono" />
            <div class="text-[11px] text-text-muted mt-1">
              Suis <code class="bg-bg px-1 rounded">netlify_functions/README.md</code> à la racine du projet
              pour déployer en 5 minutes (gratuit).
            </div>
          </div>

          <div class="flex gap-3 pt-2">
            <button class="btn btn-primary" id="trk-save">Enregistrer</button>
            <span id="trk-stats" class="text-xs text-text-muted self-center"></span>
          </div>
        </div>
      </section>
    `;
  },

  _bindTracker() {
    const save = document.getElementById('trk-save');
    const stats = document.getElementById('trk-stats');
    if (!save) return;
    save.onclick = async () => {
      if (!App.api) return;
      save.disabled = true; save.textContent = 'Enregistrement…';
      const cfg = {
        enabled: !!document.querySelector('[data-trk-key="enabled"]').checked,
        pixel_endpoint: document.querySelector('[data-trk-key="pixel_endpoint"]').value.trim(),
      };
      try {
        const r = await App.api.tracker_save_config({ config: cfg });
        save.textContent = (r && r.ok) ? 'Enregistré ✓' : 'Erreur';
      } catch (e) { save.textContent = 'Erreur'; }
      setTimeout(() => { save.disabled = false; save.textContent = 'Enregistrer'; }, 1600);
    };
    // Charge les stats si dispo
    if (App.api && stats) {
      App.api.tracker_stats().then(r => {
        if (r && r.ok && r.sent_7d > 0) {
          stats.textContent = `7j : ${r.opened_7d}/${r.sent_7d} ouverts (${r.open_rate_7d}%)`;
        }
      }).catch(() => {});
    }
  },

  _renderLeadToClient(cfg) {
    const c = cfg || { enabled: true, mode: 'strong',
                       default_product_key: 'custom-dev',
                       default_product_name: 'Service Triskell',
                       min_confidence: 0.6 };
    const opt = (v, l, sel) => `<option value="${v}" ${sel===v?'selected':''}>${l}</option>`;
    return `
      <section>
        <div class="section-label">Bascule auto des prospects intéressés</div>
        <p class="text-sm text-text-muted mb-4">
          Quand un prospect répond positivement à un de tes mails, l'app peut
          créer toute seule une carte projet client (statut « Briefing »).
        </p>
        <div class="card p-6 space-y-4">
          <label class="flex items-start gap-3 cursor-pointer">
            <input type="checkbox" data-l2c-key="enabled" ${c.enabled?'checked':''}
                   class="mt-0.5 w-4 h-4 accent-accent" />
            <div>
              <div class="text-sm font-medium">Activer la bascule auto</div>
              <div class="text-xs text-text-muted">Si désactivé, tu cliques manuellement « + Créer projet client » dans la vue Réponses.</div>
            </div>
          </label>

          <div>
            <label class="block text-xs font-medium text-text-secondary mb-1.5">Quand basculer ?</label>
            <select data-l2c-key="mode"
                    class="w-full px-3 py-2 rounded-lg bg-bg border border-border text-sm focus:border-accent focus:outline-none">
              ${opt('strong', 'Seulement si signal d\'achat fort (prix, devis, "j\'achète"…) — recommandé', c.mode)}
              ${opt('all',    'Tous les prospects classés intéressés (à toi de filtrer après)', c.mode)}
              ${opt('off',    'Jamais (bascule manuelle uniquement)', c.mode)}
            </select>
          </div>

          <div class="grid grid-cols-2 gap-4">
            <div>
              <label class="block text-xs font-medium text-text-secondary mb-1.5">Produit par défaut (identifiant)</label>
              <input type="text" data-l2c-key="default_product_key"
                     value="${this._esc(c.default_product_key || '')}"
                     placeholder="ex : custom-dev"
                     class="w-full px-3 py-2 rounded-lg bg-bg border border-border text-sm focus:border-accent focus:outline-none" />
              <div class="text-[11px] text-text-muted mt-1">Utilisé si on ne peut pas inférer le produit pitché.</div>
            </div>
            <div>
              <label class="block text-xs font-medium text-text-secondary mb-1.5">Produit par défaut (nom affiché)</label>
              <input type="text" data-l2c-key="default_product_name"
                     value="${this._esc(c.default_product_name || '')}"
                     placeholder="ex : Service Triskell"
                     class="w-full px-3 py-2 rounded-lg bg-bg border border-border text-sm focus:border-accent focus:outline-none" />
            </div>
          </div>

          <div>
            <label class="block text-xs font-medium text-text-secondary mb-1.5">Seuil de confiance minimal</label>
            <input type="number" min="0" max="1" step="0.05"
                   data-l2c-key="min_confidence" value="${c.min_confidence ?? 0.6}"
                   class="w-32 px-3 py-2 rounded-lg bg-bg border border-border text-sm focus:border-accent focus:outline-none" />
            <div class="text-[11px] text-text-muted mt-1">
              Entre 0 et 1. Les classifications IA en dessous sont ignorées (par défaut 0.6).
            </div>
          </div>

          <div class="flex gap-3 pt-2">
            <button class="btn btn-primary" id="l2c-save">Enregistrer</button>
            <button class="btn btn-secondary" id="l2c-run">Tester maintenant</button>
            <span id="l2c-feedback" class="text-xs text-text-muted self-center"></span>
          </div>
        </div>
      </section>
    `;
  },

  _bindLeadToClient() {
    const save = document.getElementById('l2c-save');
    const run  = document.getElementById('l2c-run');
    const fb   = document.getElementById('l2c-feedback');
    if (!save) return;
    const gather = () => {
      const v = (k) => {
        const el = document.querySelector(`[data-l2c-key="${k}"]`);
        if (!el) return undefined;
        if (el.type === 'checkbox') return !!el.checked;
        if (el.type === 'number')   return parseFloat(el.value) || 0;
        return el.value;
      };
      return {
        enabled: v('enabled'),
        mode:    v('mode'),
        default_product_key:  v('default_product_key'),
        default_product_name: v('default_product_name'),
        min_confidence:       v('min_confidence'),
      };
    };
    save.onclick = async () => {
      if (!App.api) return;
      save.disabled = true; save.textContent = 'Enregistrement…';
      try {
        const r = await App.api.lead_to_client_save_config({ config: gather() });
        save.textContent = (r && r.ok) ? 'Enregistré ✓' : 'Erreur';
      } catch (e) { save.textContent = 'Erreur'; }
      setTimeout(() => { save.disabled = false; save.textContent = 'Enregistrer'; }, 1600);
    };
    run.onclick = async () => {
      if (!App.api) return;
      run.disabled = true; run.textContent = 'Test en cours…';
      fb.textContent = '';
      try {
        // Sauve la config avant test pour utiliser les nouveaux réglages
        await App.api.lead_to_client_save_config({ config: gather() });
        const r = await App.api.lead_to_client_run_now();
        if (r && r.ok && r.result) {
          const c = r.result;
          fb.textContent = `Scan : ${c.scanned}, basculés : ${c.converted}, signal faible : ${c.weak_signal}, sautés : ${c.skipped}, erreurs : ${c.errors}`;
        } else {
          fb.textContent = 'Erreur : ' + ((r && r.error) || 'inconnu');
        }
      } catch (e) { fb.textContent = 'Erreur : ' + e; }
      run.disabled = false; run.textContent = 'Tester maintenant';
    };
  },

  _renderDelivery() {
    return `
      <section>
        <div class="section-label">Livraison automatique après vente</div>
        <div class="card p-6 flex items-center justify-between">
          <div>
            <div class="font-semibold mb-1">Kits de livraison par produit</div>
            <div class="text-sm text-text-muted max-w-lg">
              Mail de bienvenue, accès aux livrables, et suivis automatiques.
              Un kit par produit (Pack Élec, Studio PDF, Obelisk…). Modifiable à volonté.
            </div>
          </div>
          <button class="btn btn-primary" onclick="App.show('delivery')">Éditer les kits</button>
        </div>
      </section>

      <section>
        <div class="section-label">Santé du système</div>
        <div class="card p-6 flex items-center justify-between">
          <div>
            <div class="font-semibold mb-1">Tableau de bord en temps réel</div>
            <div class="text-sm text-text-muted max-w-lg">
              État des 10 outils autonomes, dernières exécutions, taux de réponse,
              alertes de configuration. Mise à jour auto toutes les 15 secondes.
            </div>
          </div>
          <button class="btn btn-secondary" onclick="App.show('health')">Voir l'état</button>
        </div>
      </section>

      <section>
        <div class="section-label">Test A/B des sujets de mail</div>
        <div class="card p-6 flex items-center justify-between">
          <div>
            <div class="font-semibold mb-1">Compare plusieurs sujets et trouve celui qui marche</div>
            <div class="text-sm text-text-muted max-w-lg">
              Tu proposes 2 à 5 variantes, l'app les distribue équitablement,
              mesure le taux de réponse et te dit laquelle gagne avec un verdict
              statistique fiable.
            </div>
          </div>
          <button class="btn btn-secondary" onclick="App.show('abtest')">Gérer mes tests</button>
        </div>
      </section>
    `;
  },

  _renderTutorial() {
    return `
      <section>
        <div class="section-label">Visite guidée</div>
        <div class="card p-6 flex items-center justify-between">
          <div>
            <div class="font-semibold mb-1">Revoir le tuto Triskell Command</div>
            <div class="text-sm text-text-muted">12 étapes pour découvrir tout le pipeline d'automatisation.</div>
          </div>
          <button class="btn btn-secondary" onclick="App.show('tutorial')">Lancer la visite</button>
        </div>
      </section>
    `;
  },

  _field(label, savePath, value, type = 'text', placeholder = '') {
    const masked = (type === 'password' && value && value.startsWith('•'));
    return `
      <div>
        <label class="block text-sm font-semibold mb-1">${this._esc(label)}</label>
        <input type="${type}"
               data-save-path="${savePath}"
               value="${masked ? '' : this._esc(value || '')}"
               placeholder="${this._esc(placeholder || (masked ? '••••••••' : ''))}"
               class="w-full px-4 py-2.5 text-sm rounded-xl bg-bg border border-border
                      focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent" />
      </div>
    `;
  },

  _bind() {
    // Boutons thème
    document.querySelectorAll('[data-theme-mode]').forEach(btn => {
      btn.onclick = async () => {
        if (!App.api) return;
        const mode = btn.dataset.themeMode;
        const r = await App.api.set_theme_mode(mode);
        if (r && r.ok) {
          document.documentElement.setAttribute('data-theme', r.mode);
          await this.refresh();
        }
      };
    });

    // Auto-save sur blur pour chaque champ
    document.querySelectorAll('[data-save-path]').forEach(input => {
      input.addEventListener('blur', async () => {
        if (!App.api) return;
        const v = input.value;
        if (v === '' && input.type === 'password') return;  // ne pas écraser un mot de passe avec vide
        const path = input.dataset.savePath.split('.');
        let value = v;
        if (input.type === 'number') {
          value = v === '' ? null : parseInt(v, 10);
        }
        try { await App.api.save_setting({ path, value }); }
        catch (e) { console.warn('save_setting:', e); }
      });
    });
  },

  _esc(s) {
    return String(s || '').replace(/[&<>"']/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    }[c]));
  },
};
