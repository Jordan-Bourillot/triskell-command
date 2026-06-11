/* Vue Réglages — apparence, IA, mail, connexion base partagée */

const Config = {
  // Onglet demandé par le routeur (App.show('config', { tab: 'mails' })) :
  // prioritaire sur le dernier onglet mémorisé, consommé au premier affichage.
  _pendingTab: null,
  // Vrai si le chargement initial des réglages a échoué : l'auto-enregistrement
  // est alors suspendu pour ne pas écraser les vrais réglages avec du vide.
  _loadFailed: false,

  async render(container, params) {
    this._pendingTab = (params && params.tab) || null;
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
    // Arrivée par lien direct sur un onglet : on remonte en haut de page
    if (params && params.tab) {
      const main = document.getElementById('main');
      if (main) main.scrollTo({ top: 0 });
    }
  },

  async refresh() {
    let s = null;
    let l2c = null;
    let stripeCfg = null;
    let phantomCfg = null;
    let trackerCfg = null;
    let authStatus = null;
    this._loadFailed = false;
    if (App.api) {
      try { s = await App.api.get_settings(); }
      catch (e) {
        // Échec de chargement : champs vides → l'auto-enregistrement au blur
        // pourrait écraser les vrais réglages. On le coupe et on l'affiche.
        this._loadFailed = true;
        console.warn('get_settings a échoué :', e);
      }
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
        const r = await App.api.phantombuster_get_config();
        if (r && r.ok) phantomCfg = r.config;
      } catch (e) {}
      try {
        const r = await App.api.tracker_get_config();
        if (r && r.ok) trackerCfg = r.config;
      } catch (e) {}
    }
    const slot = document.getElementById('cfg-content');

    // Groupes d'onglets : chaque onglet regroupe plusieurs renderers existants.
    const groups = [
      { key: 'account',      label: 'Compte',         html: this._renderAuth(authStatus) },
      { key: 'appearance',   label: 'Apparence',      html: this._renderAppearance(s) },
      { key: 'mails',        label: 'Mails',          html: this._renderOutreach(s) + this._renderMailAccounts() + this._renderSignature() },
      { key: 'ai',           label: 'Intelligence Artificielle', html: this._renderAi(s) },
      { key: 'integrations', label: 'Intégrations',   html: this._renderStripe(stripeCfg) + this._renderPhantombuster(phantomCfg) + this._renderTracker(trackerCfg) },
      { key: 'automations',  label: 'Automatisations', html: this._renderLeadToClient(l2c) + this._renderDelivery() },
      { key: 'system',       label: 'Système',        html: this._renderBackups() + this._renderDemoMode() + this._renderTutorial() },
    ];

    // Onglet à ouvrir : 1) celui demandé par le routeur (deep-link),
    // 2) le dernier sélectionné, 3) le premier.
    let activeKey = null;
    if (this._pendingTab && groups.find(g => g.key === this._pendingTab)) {
      activeKey = this._pendingTab;
      try { localStorage.setItem('cfg-active-tab', activeKey); } catch (e) {}
    }
    this._pendingTab = null; // consommé — les refresh internes gardent l'onglet
    if (!activeKey) activeKey = localStorage.getItem('cfg-active-tab') || groups[0].key;
    if (!groups.find(g => g.key === activeKey)) activeKey = groups[0].key;

    const tabsHTML = groups.map(g =>
      `<button type="button" role="tab" aria-selected="${g.key === activeKey ? 'true' : 'false'}" data-cfg-tab="${g.key}" class="cfg-tab${g.key === activeKey ? ' active' : ''}">${g.label}</button>`
    ).join('');

    const panelsHTML = groups.map(g =>
      `<div data-cfg-panel="${g.key}" class="space-y-12${g.key === activeKey ? '' : ' hidden'}">${g.html}</div>`
    ).join('');

    // Bandeau d'erreur si les réglages n'ont pas pu être chargés
    const errorBanner = this._loadFailed ? `
      <div class="card p-4 mb-6 flex items-center justify-between gap-3"
           style="border-color: hsl(var(--danger) / 0.4); background: hsl(var(--danger) / 0.08);">
        <div>
          <div class="text-sm font-semibold text-danger-text mb-0.5">Impossible de charger tes réglages</div>
          <div class="text-xs text-text-muted">Pour ne pas écraser tes vrais réglages avec des champs vides,
          l'enregistrement automatique est suspendu sur cette page.</div>
        </div>
        <button id="cfg-retry-load" class="btn btn-secondary shrink-0">Réessayer</button>
      </div>` : '';

    slot.innerHTML = `
      ${errorBanner}
      <nav class="cfg-tabs" role="tablist" aria-label="Sections des réglages">${tabsHTML}</nav>
      <div class="cfg-panels">${panelsHTML}</div>
    `;

    const retryBtn = document.getElementById('cfg-retry-load');
    if (retryBtn) retryBtn.onclick = () => this.refresh();

    // Toggle d'onglet
    slot.querySelectorAll('[data-cfg-tab]').forEach(btn => {
      btn.addEventListener('click', () => {
        const k = btn.dataset.cfgTab;
        localStorage.setItem('cfg-active-tab', k);
        slot.querySelectorAll('[data-cfg-tab]').forEach(b => {
          const on = b.dataset.cfgTab === k;
          b.classList.toggle('active', on);
          b.setAttribute('aria-selected', on ? 'true' : 'false');
        });
        slot.querySelectorAll('[data-cfg-panel]').forEach(p => p.classList.toggle('hidden', p.dataset.cfgPanel !== k));
        // Scroll en haut du contenu Réglages (#main est le conteneur qui défile,
        // window.scrollTo ne faisait rien)
        const main = document.getElementById('main');
        if (main) main.scrollTo({ top: 0, behavior: 'smooth' });
      });
    });

    this._bind();
    this._bindPrimaryTest();
    this._bindAuth();
    this._bindMailAccounts();
    this._bindSignature();
    this._bindLeadToClient();
    this._bindStripe();
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
          Chaque semaine, l'app met de côté <b>sur le serveur Triskell</b> une copie
          de tes éléments importants : modèles de mails, signatures, comptes mail,
          notes de la Boîte à idées, projets clients, mails programmés et prospects.
          Les 12 dernières sauvegardes sont gardées (~3 mois d'historique).
          C'est un filet de secours en cas de pépin sur la base partagée ou de
          mauvaise manipulation — pour restaurer quelque chose, demande à Claude.
        </p>
        <div class="card p-6 space-y-4">
          <div class="flex items-center justify-between gap-3">
            <div>
              <div class="text-sm font-semibold">Sauvegardes disponibles</div>
              <div class="text-xs text-text-muted">Conservées sur le serveur Triskell.</div>
            </div>
            <button id="cfg-backup-now" class="btn btn-secondary text-sm">Faire une sauvegarde maintenant</button>
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
        list.innerHTML = '<div class="text-text-muted italic">Connexion au serveur indisponible.</div>';
        return;
      }
      try {
        const r = await App.api.backup_list();
        if (!r || !r.ok) throw new Error((r && r.error) || 'liste indisponible');
        if (!r.backups || r.backups.length === 0) {
          list.innerHTML = '<div class="text-text-muted italic">Aucune sauvegarde encore. La première sera faite dans 7 jours, ou tu peux la lancer maintenant.</div>';
          return;
        }
        list.innerHTML = `
          <table class="w-full">
            <thead>
              <tr class="text-text-muted text-[11px] uppercase tracking-widest">
                <th class="text-left py-2 font-semibold">Sauvegarde</th>
                <th class="text-left py-2 font-semibold">Date</th>
                <th class="text-right py-2 font-semibold">Taille</th>
                <th class="text-right py-2 font-semibold"></th>
              </tr>
            </thead>
            <tbody>
              ${r.backups.map(b => `
                <tr class="border-t border-border">
                  <td class="py-2 font-mono text-text">${this._esc(b.filename)}</td>
                  <td class="py-2 text-text-muted">${(b.ts || '').slice(0, 16).replace('T', ' ')}</td>
                  <td class="py-2 text-right text-text-muted">${Math.round(b.size_bytes / 1024)} Ko</td>
                  <td class="py-2 text-right whitespace-nowrap">
                    <button data-backup-preview="${this._esc(b.filename)}"
                            class="text-[11px] text-accent hover:underline">Voir le contenu</button>
                    <button data-backup-download="${this._esc(b.filename)}"
                            class="text-[11px] text-accent hover:underline ml-3"
                            title="Récupérer ce fichier de sauvegarde sur cet appareil">Télécharger</button>
                  </td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        `;
        list.querySelectorAll('[data-backup-preview]').forEach(pb => {
          pb.onclick = () => this._openBackupPreview(pb.dataset.backupPreview);
        });
        list.querySelectorAll('[data-backup-download]').forEach(db => {
          db.onclick = () => this._downloadBackup(db, db.dataset.backupDownload);
        });
      } catch (e) {
        console.warn('backup_list :', e);
        list.innerHTML = '<div class="text-danger">Impossible de charger la liste des sauvegardes. <button id="cfg-backup-reload" class="underline">Réessayer</button></div>';
        const rb = document.getElementById('cfg-backup-reload');
        if (rb) rb.onclick = reload;
      }
    };

    btn.onclick = async () => {
      if (!App.api) return;
      btn.disabled = true;
      btn.textContent = 'Sauvegarde en cours…';
      try {
        const r = await App.api.backup_run_now();
        if (r && r.ok) {
          btn.textContent = '✓ Sauvegarde créée';
          setTimeout(() => { btn.textContent = 'Faire une sauvegarde maintenant'; btn.disabled = false; }, 1500);
          reload();
        } else {
          btn.textContent = '✗ Échec';
          Toast.error((r && r.error) || 'La sauvegarde a échoué — réessaie dans un instant.');
          setTimeout(() => { btn.textContent = 'Faire une sauvegarde maintenant'; btn.disabled = false; }, 2500);
        }
      } catch (e) {
        btn.textContent = '✗ Échec';
        Toast.friendlyError(e, 'La sauvegarde a échoué — réessaie dans un instant.');
        setTimeout(() => { btn.textContent = 'Faire une sauvegarde maintenant'; btn.disabled = false; }, 3000);
      }
    };

    reload();
  },

  /** Modale « Voir le contenu » d'une sauvegarde (résumé renvoyé par le serveur). */
  async _openBackupPreview(filename) {
    if (!App.api || !filename) return;
    let r = null;
    try { r = await App.api.backup_preview({ filename }); }
    catch (e) { Toast.friendlyError(e, 'Impossible d’ouvrir cette sauvegarde.'); return; }
    if (!r || !r.ok || !r.summary) {
      Toast.error((r && r.error) || 'Impossible d’ouvrir cette sauvegarde.');
      return;
    }
    const sm = r.summary;
    const when = (sm.ts || '').slice(0, 16).replace('T', ' à ');
    const line = (label, val) => `
      <div class="flex items-center justify-between py-1.5 border-b border-border last:border-0">
        <span class="text-text-secondary">${label}</span>
        <span class="font-semibold">${val}</span>
      </div>`;
    const overlay = document.createElement('div');
    overlay.className = 'fixed inset-0 z-[220] flex items-center justify-center p-4';
    overlay.style.background = 'rgba(15,23,42,0.6)';
    overlay.style.backdropFilter = 'blur(6px)';
    overlay.innerHTML = `
      <div class="bg-surface rounded-2xl shadow-hero w-full max-w-md border border-border animate-slide-up overflow-hidden">
        <div class="px-6 pt-5 pb-3 border-b border-border flex items-start justify-between gap-3">
          <div>
            <div class="hero-kicker mb-1">SAUVEGARDE</div>
            <h3 class="text-base font-bold">${when ? `Faite le ${this._esc(when)}` : 'Contenu'}</h3>
          </div>
          <button id="bkp-close" title="Fermer" aria-label="Fermer"
                  class="w-8 h-8 rounded-lg flex items-center justify-center text-text-muted hover:text-text hover:bg-bg text-xl leading-none shrink-0">×</button>
        </div>
        <div class="px-6 py-4 text-sm">
          ${line('Modèles de mails', sm.templates_count ?? 0)}
          ${line('Signatures', sm.signatures_count ?? 0)}
          ${line('Comptes mail', sm.accounts_count ?? 0)}
          ${line('Notes de la Boîte à idées', sm.brain_notes_count ?? 0)}
          ${line('Mails programmés', sm.scheduled_mails_count ?? 0)}
          ${line('Réglages de l’app', sm.has_settings ? '✓ inclus' : '—')}
          ${line('Prénoms affichés', sm.has_display_names ? '✓ inclus' : '—')}
          <p class="text-[11px] text-text-muted mt-3 mb-0">
            Pour restaurer un de ces éléments, demande à Claude en précisant la date de la sauvegarde.
          </p>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);
    const close = () => { document.removeEventListener('keydown', esc); overlay.remove(); };
    const esc = (e) => { if (e.key === 'Escape') close(); };
    document.addEventListener('keydown', esc);
    overlay.querySelector('#bkp-close').onclick = close;
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
  },

  /** Télécharge un fichier de sauvegarde tel quel (JSON) sur l'appareil. */
  async _downloadBackup(btn, filename) {
    if (!App.api || !filename) return;
    const original = btn ? btn.textContent : '';
    if (btn) { btn.disabled = true; btn.textContent = 'Préparation…'; }
    try {
      const r = await App.api.backup_download({ filename });
      if (!r || !r.ok || !r.b64) {
        Toast.error((r && r.error) || 'Impossible de récupérer cette sauvegarde.');
        return;
      }
      const bin = atob(r.b64);
      const bytes = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
      const blob = new Blob([bytes], { type: r.mime || 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = r.filename || filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(() => URL.revokeObjectURL(url), 60000);
      Toast.success('La sauvegarde est téléchargée.');
    } catch (e) {
      Toast.friendlyError(e, 'Impossible de récupérer cette sauvegarde.');
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = original; }
    }
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
                   style="background: linear-gradient(135deg, hsl(var(--danger)), hsl(var(--warning)));">
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
                        style="background: linear-gradient(135deg, hsl(var(--danger)), hsl(var(--warning))); border: none;">
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
    // Si le module n’a pas pu être chargé, on l’explique au lieu de rester muet
    const moduleMissing = () =>
      Toast.error('Le mode démo n’a pas pu être chargé. Recharge la page (Ctrl+R) puis réessaie.');
    if (onBtn) onBtn.onclick = () => {
      if (typeof DemoMode !== 'undefined' && DemoMode.setOn) DemoMode.setOn(true);
      else moduleMissing();
    };
    if (offBtn) offBtn.onclick = () => {
      if (typeof DemoMode !== 'undefined' && DemoMode.setOn) DemoMode.setOn(false);
      else moduleMissing();
    };
  },

  _renderAuth(authStatus) {
    const connected = authStatus && authStatus.connected;
    const displayName = (authStatus && authStatus.display_name) || '';
    const reason = authStatus && authStatus.reason;
    if (connected) {
      return `
        <section>
          <div class="section-label">Connexion à la base partagée</div>
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
                <div class="text-xs text-text-muted">${this._escape(displayName) || 'Compte connecté'}</div>
              </div>
            </div>
            <button id="cfg-auth-signout" class="btn btn-secondary">Se déconnecter</button>
          </div>
        </section>
      `;
    }
    const reasonMsg = reason === 'supabase_not_configured'
      ? "La connexion à la base n’est pas configurée sur le serveur — demande à Claude."
      : "Aucune session active. Connecte-toi pour activer les pages qui en ont besoin.";
    return `
      <section>
        <div class="section-label">Connexion à la base partagée</div>
        <p class="text-sm text-text-muted mb-4">${reasonMsg}</p>
        <div class="card p-5 space-y-3">
          <div>
            <label for="cfg-auth-email" class="block text-xs font-medium text-text-secondary mb-1.5">Email</label>
            <input type="email" id="cfg-auth-email"
                   placeholder="jordan@triskell-studio.fr"
                   class="w-full px-3 py-2 text-sm rounded-lg bg-bg border border-border
                          focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent"/>
          </div>
          <div>
            <label for="cfg-auth-password" class="block text-xs font-medium text-text-secondary mb-1.5">Mot de passe</label>
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
    const emailEl = document.getElementById('cfg-auth-email');
    const pwdEl = document.getElementById('cfg-auth-password');

    const doSignIn = async () => {
      if (!App.api || !signinBtn) return;
      const email = emailEl ? emailEl.value.trim() : '';
      const password = pwdEl ? pwdEl.value : '';
      const status = document.getElementById('cfg-auth-status');
      if (!status) return;
      if (!email || !password) {
        status.textContent = 'Email et mot de passe requis.';
        status.className = 'text-xs text-danger';
        return;
      }
      signinBtn.disabled = true;
      status.textContent = 'Connexion…';
      status.className = 'text-xs text-text-muted';
      try {
        const r = await App.api.auth_sign_in({ email, password });
        if (r && r.ok) {
          status.textContent = 'Connecté. Rechargement…';
          status.className = 'text-xs text-success';
          setTimeout(() => this.refresh(), 600);
          return;
        }
        const raw = (r && r.error) || '';
        console.warn('auth_sign_in :', raw);
        status.textContent = /invalid|credential|password|grant/i.test(raw)
          ? '✗ Email ou mot de passe incorrect.'
          : '✗ Connexion impossible — réessaie dans un instant.';
        status.className = 'text-xs text-danger';
      } catch (e) {
        // Plus de « Connexion… » figé : on vide le statut et on explique
        status.textContent = '';
        status.className = 'text-xs text-text-muted';
        Toast.friendlyError(e, 'Connexion impossible — vérifie ta connexion internet et réessaie.');
      } finally {
        if (signinBtn) signinBtn.disabled = false;
      }
    };

    if (signinBtn) signinBtn.onclick = doSignIn;
    // Entrée dans le mot de passe (ou l’email) = se connecter
    [emailEl, pwdEl].forEach(el => {
      if (!el) return;
      el.addEventListener('keydown', (e) => { if (e.key === 'Enter') doSignIn(); });
    });

    const signoutBtn = document.getElementById('cfg-auth-signout');
    if (signoutBtn) signoutBtn.onclick = async () => {
      const ok = await Dialog.confirm(
        'Les pages Cockpit, Brouillons, Réponses, etc. ne fonctionneront plus tant que tu ne te reconnectes pas.',
        { title: 'Se déconnecter ?', okLabel: 'Se déconnecter', danger: true });
      if (!ok) return;
      try { await App.api.auth_sign_out(); }
      catch (e) { Toast.friendlyError(e, 'La déconnexion a échoué — réessaie.'); return; }
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
    let signatures = [], accounts = [], loadError = false;
    try {
      const sr = await App.api.signatures_list();
      if (sr && sr.ok) signatures = sr.signatures || [];
      else loadError = true;
      const ar = await App.api.mail_accounts_list();
      if (ar && ar.ok) accounts = ar.accounts || [];
    } catch (e) {
      console.warn('signatures_list :', e);
      loadError = true;
    }
    if (loadError) {
      // Erreur de chargement ≠ liste vide : on le dit et on propose de réessayer
      listEl.innerHTML = `<div class="text-sm text-danger">Impossible de charger tes signatures.
        <button id="cfg-sig-retry" class="underline">Réessayer</button></div>`;
      const rb = document.getElementById('cfg-sig-retry');
      if (rb) rb.onclick = () => this._refreshSignaturesList();
      return;
    }
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
        ? accIds.map(id => `<span class="text-[11px] px-2 py-0.5 rounded-full bg-accent/12 text-accent font-semibold">${this._escape(accLabel(id))}</span>`).join(' ')
        : `<span class="text-[11px] px-2 py-0.5 rounded-full bg-text-muted/10 text-text-muted">Toutes les adresses</span>`;
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
        const name = (sig && sig.name) || 'sans nom';
        const ok = await Dialog.confirm(`Supprimer la signature « ${name} » ?`,
          { title: 'Supprimer cette signature', okLabel: 'Supprimer', danger: true });
        if (!ok) return;
        try {
          const r = await App.api.signature_remove({ id });
          if (r && r.ok) { Toast.success('Signature supprimée.'); this._refreshSignaturesList(); }
          else Toast.error('La suppression a échoué : ' + ((r && r.error) || 'erreur inconnue'));
        } catch (e) { Toast.friendlyError(e, 'La suppression a échoué.'); }
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
          <button id="se-close" title="Fermer" aria-label="Fermer" class="w-8 h-8 rounded-lg flex items-center justify-center text-text-muted hover:text-text hover:bg-bg text-xl leading-none">×</button>
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
            <label class="block text-[11px] font-medium text-text-secondary mb-1">Adresses auxquelles cette signature est attribuée</label>
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
                  <div class="text-[11px] font-bold uppercase tracking-widest text-text-muted mb-1">Code HTML</div>
                  <textarea id="se-body-html" rows="10" placeholder='<p>Cordialement,<br><strong>Jordan</strong></p>'
                            class="flex-1 px-3 py-2 text-xs rounded-lg bg-bg border border-border focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent font-mono leading-relaxed resize-y" style="min-height: 200px;">${this._escape(existing?.body_html || '')}</textarea>
                </div>
                <div class="flex flex-col">
                  <div class="text-[11px] font-bold uppercase tracking-widest text-text-muted mb-1">Aperçu (rendu mail)</div>
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
    // Garde anti-perte de saisie : un clic à côté ou sur × / Annuler avec des
    // modifications en cours demande confirmation avant de tout jeter.
    let dirty = false;
    const requestClose = async () => {
      if (dirty) {
        const ok = await Dialog.confirm(
          'Cette signature a des modifications non enregistrées. Fermer quand même ?',
          { title: 'Modifications non enregistrées', okLabel: 'Fermer sans enregistrer', danger: true });
        if (!ok) return;
      }
      close();
    };
    overlay.querySelector('#se-close').onclick = requestClose;
    overlay.querySelector('#se-cancel').onclick = requestClose;
    overlay.addEventListener('click', (e) => { if (e.target === overlay) requestClose(); });

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

    // Suivi des modifications (pour la garde anti-perte de saisie)
    const markDirty = () => { dirty = true; };
    overlay.querySelector('#se-name').addEventListener('input', markDirty);
    textTa.addEventListener('input', markDirty);
    htmlTa.addEventListener('input', markDirty);
    overlay.querySelectorAll('.se-acc').forEach(c => c.addEventListener('change', markDirty));

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
      status.textContent = 'Enregistrement…';
      status.className = 'text-xs text-text-muted';
      try {
        const r = await App.api.signature_save({ signature: sigData });
        if (r && r.ok) {
          status.textContent = '✓ Enregistré.';
          status.className = 'text-xs text-success';
          dirty = false;
          setTimeout(() => { close(); this._refreshSignaturesList(); }, 600);
        } else {
          status.textContent = `✗ Enregistrement impossible : ${(r && r.error) || 'erreur inconnue'}`;
          status.className = 'text-xs text-danger';
        }
      } catch (e) {
        console.warn('signature_save :', e);
        status.textContent = '✗ Enregistrement impossible — vérifie ta connexion et réessaie.';
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
    catch (e) { console.warn('mail_accounts_list :', e); r = null; }
    if (!r || !r.ok) {
      if (r && r.error) console.warn('mail_accounts_list :', r.error);
      listEl.innerHTML = `<div class="text-xs text-danger">Impossible de charger les adresses.
        <button id="cfg-mail-accounts-retry" class="underline">Réessayer</button></div>`;
      const rb = document.getElementById('cfg-mail-accounts-retry');
      if (rb) rb.onclick = () => this._bindMailAccounts();
      return;
    }
    const accounts = r.accounts || [];
    if (!accounts.length) {
      listEl.innerHTML = `<div class="text-sm text-text-muted">Aucune adresse configurée.</div>`;
    } else {
      listEl.innerHTML = accounts.map(a => this._mailAccountRow(a)).join('');
    }
    // Bind suppression — on affiche l’adresse mail, pas l’identifiant interne
    listEl.querySelectorAll('[data-mail-remove]').forEach(btn => {
      btn.onclick = async () => {
        const aid = btn.dataset.mailRemove;
        const acc = accounts.find(x => x.id === aid);
        const mail = (acc && (acc.from_email || acc.label)) || aid;
        const ok = await Dialog.confirm(
          `Supprimer l’adresse « ${mail} » ? La boîte ne sera plus consultée et tu ne pourras plus envoyer depuis cette adresse.`,
          { title: 'Supprimer cette adresse', okLabel: 'Supprimer', danger: true });
        if (!ok) return;
        try {
          const resp = await App.api.mail_account_remove({ id: aid });
          if (resp && resp.ok) { Toast.success('Adresse supprimée.'); this._bindMailAccounts(); }
          else Toast.error('La suppression a échoué : ' + ((resp && resp.error) || 'erreur inconnue'));
        } catch (e) { Toast.friendlyError(e, 'La suppression a échoué.'); }
      };
    });
    // Bind modification — rouvre le formulaire pré-rempli
    listEl.querySelectorAll('[data-mail-edit]').forEach(btn => {
      btn.onclick = () => {
        const acc = accounts.find(x => x.id === btn.dataset.mailEdit);
        if (acc) this._openMailAccountForm(acc);
      };
    });
    // Bind test connexion (résultat traduit en français)
    listEl.querySelectorAll('[data-mail-test]').forEach(btn => {
      btn.onclick = async () => {
        const aid = btn.dataset.mailTest;
        const status = document.getElementById(`mail-test-${aid}`);
        if (!status) return;
        btn.disabled = true;
        status.textContent = 'Test en cours…';
        // Reset de la couleur (sinon le rouge d’un échec précédent reste)
        status.className = 'text-xs text-text-muted';
        try {
          const resp = await App.api.mail_account_test({ id: aid });
          const m = this._mailTestMessage(resp);
          status.textContent = m.text;
          status.className = `text-xs ${m.ok ? 'text-success' : 'text-danger'}`;
        } catch (e) {
          console.warn('mail_account_test :', e);
          status.textContent = '✗ Le test n’a pas pu être lancé — vérifie ta connexion et réessaie.';
          status.className = 'text-xs text-danger';
        } finally {
          btn.disabled = false;
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
              ${primary ? '<span class="text-[11px] font-bold uppercase px-1.5 py-0.5 rounded bg-accent/15 text-accent">Principal</span>' : ''}
              ${!pwdOk ? '<span class="text-[11px] font-bold uppercase px-1.5 py-0.5 rounded bg-warning/15 text-warning">Mot de passe manquant</span>' : ''}
            </div>
            <div class="text-xs text-text-muted truncate">${this._escape(a.from_email)}</div>
            <div class="text-[11px] text-text-muted mt-1">
              Envoi ${this._escape(a.smtp_host)}:${a.smtp_port} · Réception ${this._escape(a.imap_host)}:${a.imap_port}
            </div>
            <div id="mail-test-${this._escape(a.id)}" class="text-xs text-text-muted mt-2"></div>
          </div>
          <div class="flex flex-col gap-1.5">
            <button data-mail-test="${this._escape(a.id)}" class="btn btn-secondary text-xs px-3 py-1">Tester</button>
            ${primary ? '' : `<button data-mail-edit="${this._escape(a.id)}" class="btn btn-secondary text-xs px-3 py-1">Modifier</button>`}
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
          ${this._mailField('label',        'Nom affiché dans l’app',             existing?.label || '')}
          ${this._mailField('from_email',   'Adresse mail (envoi & réception)',   existing?.from_email || '', 'email')}
          ${this._mailField('from_name',    'Nom d’expéditeur (ex : Lagriffe Studio)', existing?.from_name || '')}
          <div class="grid grid-cols-2 gap-3">
            ${this._mailField('smtp_host',  'Serveur d’envoi (SMTP)',  existing?.smtp_host || 'smtp.ionos.fr')}
            ${this._mailField('smtp_port',  'Port SMTP',  existing?.smtp_port || 587, 'number')}
          </div>
          ${this._mailField('smtp_user',    'Identifiant SMTP (souvent l’adresse mail)',  existing?.smtp_user || existing?.from_email || '')}
          ${this._mailField('smtp_password', existing && existing._has_smtp_pwd ? 'Mot de passe SMTP (laisser vide pour garder l’actuel)' : 'Mot de passe SMTP', '', 'password')}
          <div class="grid grid-cols-2 gap-3">
            ${this._mailField('imap_host',  'Serveur de réception (IMAP)',  existing?.imap_host || 'imap.ionos.fr')}
            ${this._mailField('imap_port',  'Port IMAP',  existing?.imap_port || 993, 'number')}
          </div>
          ${this._mailField('imap_user',    'Identifiant IMAP (souvent l’adresse mail)',  existing?.imap_user || existing?.from_email || '')}
          ${this._mailField('imap_password', existing && existing._has_imap_pwd ? 'Mot de passe IMAP (laisser vide pour garder l’actuel)' : 'Mot de passe IMAP', '', 'password')}
          <input type="hidden" data-mail-field="id" value="${this._escape(existing?.id || '')}"/>
          <div id="mail-form-status" class="text-xs text-text-muted"></div>
        </div>
        <div class="px-6 py-4 border-t border-border flex items-center justify-between gap-2 flex-wrap">
          <button id="mail-form-test" class="btn btn-secondary">Tester avant d’enregistrer</button>
          <div class="flex gap-2">
            <button id="mail-form-cancel" class="btn btn-secondary">Annuler</button>
            <button id="mail-form-save"   class="btn btn-primary">Enregistrer</button>
          </div>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);
    const close = () => overlay.remove();
    document.getElementById('mail-form-cancel').onclick = close;

    // Rassemble les champs du formulaire en un compte. L’identifiant interne
    // n’est plus demandé : il est dérivé automatiquement de l’adresse mail.
    const gatherAcc = () => {
      const acc = {};
      ['id','label','from_email','from_name','smtp_host','smtp_user','smtp_password',
       'imap_host','imap_user','imap_password'].forEach(k => {
        const el = overlay.querySelector(`[data-mail-field="${k}"]`);
        acc[k] = el ? el.value.trim() : '';
      });
      acc.smtp_port = parseInt(overlay.querySelector('[data-mail-field="smtp_port"]').value, 10) || 587;
      acc.imap_port = parseInt(overlay.querySelector('[data-mail-field="imap_port"]').value, 10) || 993;
      if (!acc.id) acc.id = this._slugFromEmail(acc.from_email);
      return acc;
    };

    // Tester avant d'enregistrer — vrai test SMTP+IMAP sur les valeurs saisies.
    const testBtn = document.getElementById('mail-form-test');
    if (testBtn) testBtn.onclick = async () => {
      if (!App.api) return;
      const status = document.getElementById('mail-form-status');
      if (!status) return;
      const acc = gatherAcc();
      if (!acc.from_email || !acc.from_email.includes('@')) {
        status.textContent = 'Renseigne d’abord l’adresse mail.';
        status.className = 'text-xs text-danger';
        return;
      }
      // Les mots de passe déjà enregistrés ne redescendent jamais dans le
      // navigateur : si un champ mot de passe est laissé vide en modification,
      // le test porte sur la version déjà enregistrée du compte.
      const keepsPwd = existing && (
        (!acc.smtp_password && existing._has_smtp_pwd) ||
        (!acc.imap_password && existing._has_imap_pwd));
      testBtn.disabled = true;
      const oldTxt = testBtn.textContent;
      testBtn.textContent = 'Test en cours…';
      status.textContent = keepsPwd
        ? 'Test en cours (avec les réglages déjà enregistrés, mots de passe non ressaisis)…'
        : 'Test en cours…';
      status.className = 'text-xs text-text-muted';
      try {
        const r = await App.api.mail_account_test(keepsPwd ? { id: existing.id } : { account: acc });
        const m = this._mailTestMessage(r);
        status.textContent = m.text;
        status.className = `text-xs ${m.ok ? 'text-success' : 'text-danger'}`;
      } catch (e) {
        console.warn('mail_account_test (formulaire) :', e);
        status.textContent = '✗ Le test n’a pas pu être lancé — vérifie ta connexion et réessaie.';
        status.className = 'text-xs text-danger';
      } finally {
        testBtn.disabled = false;
        testBtn.textContent = oldTxt;
      }
    };

    const saveBtn = document.getElementById('mail-form-save');
    saveBtn.onclick = async () => {
      const acc = gatherAcc();
      const status = document.getElementById('mail-form-status');
      // Validation basique
      if (!acc.from_email || !acc.from_email.includes('@')) {
        status.textContent = 'Adresse mail invalide.';
        status.className = 'text-xs text-danger'; return;
      }
      if (!acc.id || !/^[a-z0-9_-]+$/.test(acc.id)) {
        status.textContent = 'Adresse mail invalide (impossible d’en déduire un identifiant).';
        status.className = 'text-xs text-danger'; return;
      }
      saveBtn.disabled = true;
      status.textContent = 'Enregistrement…';
      status.className = 'text-xs text-text-muted';
      try {
        const r = await App.api.mail_account_save({ account: acc });
        if (r && r.ok) {
          status.textContent = '✓ Enregistré.';
          status.className = 'text-xs text-success';
          setTimeout(() => { close(); this._bindMailAccounts(); }, 400);
        } else {
          status.textContent = `Enregistrement impossible : ${(r && r.error) || 'erreur inconnue'}`;
          status.className = 'text-xs text-danger';
          saveBtn.disabled = false;
        }
      } catch (e) {
        console.warn('mail_account_save :', e);
        status.textContent = 'Enregistrement impossible — vérifie ta connexion et réessaie.';
        status.className = 'text-xs text-danger';
        saveBtn.disabled = false;
      }
    };
  },

  /** Identifiant interne dérivé de l’adresse mail :
   *  minuscules, sans accents, tout le reste remplacé par des tirets. */
  _slugFromEmail(email) {
    return String(email || '')
      .toLowerCase()
      .normalize('NFD').replace(/[\u0300-\u036f]/g, '')
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '');
  },

  _mailField(name, label, value, type = 'text', readonly = false) {
    const safeVal = String(value ?? '').replace(/"/g, '&quot;');
    const fid = `cfg-mf-${name}`;
    return `
      <div>
        <label for="${fid}" class="block text-xs font-medium text-text-secondary mb-1">${this._escape(label)}</label>
        <input id="${fid}" data-mail-field="${name}" type="${type}" value="${safeVal}" ${readonly ? 'readonly' : ''}
               class="w-full px-3 py-2 text-sm rounded-lg bg-bg border border-border focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent ${readonly ? 'opacity-60' : ''}"/>
      </div>
    `;
  },

  _renderAppearance(s) {
    const cur = s ? s.appearance_mode : 'mid';
    const modes = [
      { key: 'light', label: 'Claire',        desc: 'Surfaces blanches, lumineux et épuré.' },
      { key: 'mid',   label: 'Intermédiaire', desc: 'Graphite chaud, équilibré et reposant.' },
      { key: 'dark',  label: 'Sombre',        desc: 'Ambiance nuit, pour la concentration.' },
    ];
    return `
      <section>
        <div class="section-label">Apparence</div>
        <p class="text-sm text-text-muted mb-4">
          Trois ambiances. Tu peux aussi en changer à tout moment avec Alt+T.
        </p>
        <div class="grid grid-cols-1 sm:grid-cols-3 gap-4">
          ${modes.map(m => {
            const active = m.key === cur;
            return `
              <button data-theme-mode="${m.key}"
                      class="card p-5 text-left transition-all hover:translate-y-[-1px]"
                      style="${active ? 'border-color: hsl(var(--accent)); border-width: 2px; background: hsl(var(--accent) / 0.06);' : ''}">
                <div class="text-[11px] font-bold tracking-widest mb-1
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
      { id: 'anthropic',  label: 'Anthropic (Claude)', recommended: false },
      { id: 'google',     label: 'Google (Gemini) — gratuit', recommended: true },
      { id: 'mistral',    label: 'Mistral — gratuit', recommended: true },
      { id: 'groq',       label: 'Groq (Llama / Meta AI) — gratuit', recommended: true },
      { id: 'deepseek',   label: 'DeepSeek — très bon marché', recommended: true },
      { id: 'perplexity', label: 'Perplexity (mode web) — payant', recommended: false },
      { id: 'openai',     label: 'OpenAI (GPT)',     recommended: false },
      { id: 'xai',        label: 'xAI (Grok)',       recommended: false },
    ];
    // Clés "Services Google" — utilisées par les outils bêta (Chasseur
    // Créateur, Prospecteur Google). Ces clés sont stockées dans le même
    // namespace que les clés IA pour réutiliser le même mécanisme de
    // sauvegarde côté serveur. Pré-remplies en dur si non configurées.
    const googleApis = [
      { id: 'youtube_data',  label: 'YouTube Data API — utilisée par le Chasseur Créateur', recommended: false },
      { id: 'google_places', label: 'Google Places API — utilisée par le Prospecteur Google', recommended: false },
    ];
    return `
      <section>
        <div class="section-label">Services IA</div>
        <p class="text-sm text-text-muted mb-4">
          Tes clés sont enregistrées dans ta base privée Triskell (partagée avec Thomas), jamais ailleurs.
          Bouton « Tester » pour vérifier que la clé fonctionne réellement.
        </p>
        <div class="card p-6 space-y-5">
          ${providers.map(p => {
            const has = !!keys[p.id];
            return `
              <div data-ai-row="${p.id}">
                <label class="block text-sm font-semibold mb-1">
                  ${this._esc(p.label)}
                  ${p.recommended ? '<span class="ml-2 text-[11px] bg-success/15 text-success px-2 py-0.5 rounded-full font-bold">RECOMMANDÉ</span>' : ''}
                </label>
                <div class="flex gap-2 items-stretch">
                  <input type="password"
                         data-save-path="ai.api_keys.${p.id}"
                         data-ai-key-input="${p.id}"
                         placeholder="${has ? '(clé enregistrée — tape pour remplacer)' : 'Clé API…'}"
                         class="flex-1 min-w-0 px-4 py-2.5 text-sm rounded-xl bg-bg border border-border
                                focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent" />
                  <button type="button"
                          data-ai-save="${p.id}"
                          class="px-4 py-2.5 text-sm font-semibold rounded-xl
                                 bg-accent text-white hover:opacity-90 transition-opacity
                                 disabled:opacity-50 disabled:cursor-not-allowed shrink-0">
                    Enregistrer
                  </button>
                  <button type="button"
                          data-ai-test="${p.id}"
                          class="px-4 py-2.5 text-sm font-semibold rounded-xl
                                 bg-surface-elevated text-text border border-border
                                 hover:bg-bg transition-colors
                                 disabled:opacity-50 disabled:cursor-not-allowed shrink-0">
                    Tester
                  </button>
                </div>
                <div data-ai-msg="${p.id}" class="text-xs mt-1.5 min-h-[18px] text-text-muted"></div>
              </div>
            `;
          }).join('')}
        </div>
      </section>

      <section class="mt-8">
        <div class="section-label">Services Google</div>
        <p class="text-sm text-text-muted mb-4">
          Clés utilisées par les outils bêta (Chasseur Créateur, Prospecteur
          Google). Si tu as ta propre clé Google Cloud, colle-la ici pour
          remplacer celle partagée par défaut.
        </p>
        <div class="card p-6 space-y-5">
          ${googleApis.map(p => {
            const has = !!keys[p.id];
            return `
              <div data-ai-row="${p.id}">
                <label class="block text-sm font-semibold mb-1">
                  ${this._esc(p.label)}
                </label>
                <div class="flex gap-2 items-stretch">
                  <input type="password"
                         data-save-path="ai.api_keys.${p.id}"
                         data-ai-key-input="${p.id}"
                         placeholder="${has ? '(clé enregistrée — tape pour remplacer)' : 'Clé API…'}"
                         class="flex-1 min-w-0 px-4 py-2.5 text-sm rounded-xl bg-bg border border-border
                                focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent" />
                  <button type="button"
                          data-ai-save="${p.id}"
                          class="px-4 py-2.5 text-sm font-semibold rounded-xl
                                 bg-accent text-white hover:opacity-90 transition-opacity
                                 disabled:opacity-50 disabled:cursor-not-allowed shrink-0">
                    Enregistrer
                  </button>
                </div>
                <div data-ai-msg="${p.id}" class="text-xs mt-1.5 min-h-[18px] text-text-muted"></div>
              </div>
            `;
          }).join('')}
        </div>
      </section>
    `;
  },

  _wireAiButtons() {
    // Bouton Enregistrer : sauve la clé tapée (si non vide)
    document.querySelectorAll('[data-ai-save]').forEach(btn => {
      btn.onclick = async () => {
        const pid = btn.dataset.aiSave;
        const input = document.querySelector(`[data-ai-key-input="${pid}"]`);
        const msg = document.querySelector(`[data-ai-msg="${pid}"]`);
        const v = (input?.value || '').trim();
        if (!v) {
          msg.textContent = '✗ Colle une clé d’abord.';
          msg.className = 'text-xs mt-1.5 min-h-[18px] text-danger';
          return;
        }
        btn.disabled = true;
        const oldTxt = btn.textContent;
        btn.textContent = '…';
        msg.textContent = 'Enregistrement…';
        msg.className = 'text-xs mt-1.5 min-h-[18px] text-text-muted';
        try {
          const r = await App.api.save_setting({
            path: ['ai', 'api_keys', pid], value: v,
          });
          if (r && r.ok !== false) {
            // Le rappel « Tester » n'a de sens que si la ligne a ce bouton
            const hasTest = !!document.querySelector(`[data-ai-test="${pid}"]`);
            msg.textContent = hasTest
              ? '✓ Clé enregistrée. Pense à tester avec le bouton « Tester ».'
              : '✓ Clé enregistrée.';
            msg.className = 'text-xs mt-1.5 min-h-[18px] text-success';
            input.value = '';
            input.placeholder = '(clé enregistrée — tape pour remplacer)';
          } else {
            console.warn('save_setting (clé IA) :', r && r.error);
            msg.textContent = '✗ Enregistrement impossible : ' + ((r && r.error) || 'erreur inconnue');
            msg.className = 'text-xs mt-1.5 min-h-[18px] text-danger';
          }
        } catch (e) {
          console.warn('save_setting (clé IA) :', e);
          msg.textContent = '✗ Enregistrement impossible — vérifie ta connexion et réessaie.';
          msg.className = 'text-xs mt-1.5 min-h-[18px] text-danger';
        } finally {
          btn.disabled = false;
          btn.textContent = oldTxt;
        }
      };
    });
    // Bouton Tester : vérifie que la clé répond. Si pas de clé tapée,
    // teste celle déjà sauvegardée.
    document.querySelectorAll('[data-ai-test]').forEach(btn => {
      btn.onclick = async () => {
        const pid = btn.dataset.aiTest;
        const input = document.querySelector(`[data-ai-key-input="${pid}"]`);
        const msg = document.querySelector(`[data-ai-msg="${pid}"]`);
        const v = (input?.value || '').trim();
        btn.disabled = true;
        const oldTxt = btn.textContent;
        btn.textContent = '⏳';
        msg.textContent = 'Test en cours (l’IA doit répondre)…';
        msg.className = 'text-xs mt-1.5 min-h-[18px] text-text-muted';
        try {
          const r = await App.api.test_ai_key({ provider: pid, key: v });
          if (r && r.ok) {
            msg.textContent = '✓ ' + (r.message || 'Clé valide.') +
              (r.sample ? ' Réponse de l’IA : « ' + r.sample + ' »' : '');
            msg.className = 'text-xs mt-1.5 min-h-[18px] text-success';
          } else {
            msg.textContent = '✗ ' + ((r && r.error) || 'Clé invalide ou IA injoignable.');
            msg.className = 'text-xs mt-1.5 min-h-[18px] text-danger';
          }
        } catch (e) {
          console.warn('test_ai_key :', e);
          msg.textContent = '✗ Le test n’a pas pu être lancé — vérifie ta connexion et réessaie.';
          msg.className = 'text-xs mt-1.5 min-h-[18px] text-danger';
        } finally {
          btn.disabled = false;
          btn.textContent = oldTxt;
        }
      };
    });
  },

  _renderOutreach(s) {
    const o = (s && s.outreach) || {};
    return `
      <section>
        <div class="section-label">Compte mail principal (envoi & réception)</div>
        <p class="text-sm text-text-muted mb-4">
          Identifiants de ton fournisseur (Gmail, IONOS, OVH…). Mot de passe
          d’application requis si Gmail. Chaque champ s’enregistre tout seul
          quand tu en sors.
        </p>
        <div class="card p-6 space-y-4">
          ${this._field('Adresse mail (envoi)', 'outreach.from_email', o.from_email, 'email')}
          ${this._field('Nom affiché', 'outreach.from_name', o.from_name)}
          <div class="grid grid-cols-2 gap-4">
            ${this._field('Serveur d’envoi (SMTP)', 'outreach.smtp_host', o.smtp_host, 'text', 'smtp.ionos.fr')}
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
            ${this._field('Plafond quotidien (mails/jour)', 'outreach.daily_cap', o.daily_cap, 'number', '40')}
            ${this._field('Délai relance (jours)', 'outreach.follow_up_days', o.follow_up_days, 'number', '5')}
          </div>
          <div class="pt-2 flex items-center gap-3 flex-wrap">
            <button type="button" id="cfg-primary-test" class="btn btn-secondary">Tester l’envoi et la réception</button>
            <span id="cfg-primary-test-status" role="status" class="text-xs text-text-muted"></span>
          </div>
        </div>
      </section>
    `;
  },

  /** Bouton « Tester l’envoi et la réception » du compte mail principal.
   *  Défensif : si la section n’est pas dans le DOM, on ne branche rien. */
  _bindPrimaryTest() {
    const btn = document.getElementById('cfg-primary-test');
    const status = document.getElementById('cfg-primary-test-status');
    if (!btn || !status) return;
    btn.onclick = async () => {
      if (!App.api) return;
      btn.disabled = true;
      const oldTxt = btn.textContent;
      btn.textContent = 'Test en cours…';
      status.textContent = 'Connexion à ta boîte mail…';
      // Reset de la couleur (sinon le rouge d’un échec précédent reste)
      status.className = 'text-xs text-text-muted';
      try {
        const r = await App.api.mail_account_test({ id: 'primary' });
        const m = this._mailTestMessage(r);
        status.textContent = m.text;
        status.className = `text-xs ${m.ok ? 'text-success' : 'text-danger'}`;
      } catch (e) {
        console.warn('mail_account_test (principal) :', e);
        status.textContent = '✗ Le test n’a pas pu être lancé — vérifie ta connexion et réessaie.';
        status.className = 'text-xs text-danger';
      } finally {
        btn.disabled = false;
        btn.textContent = oldTxt;
      }
    };
  },

  /** Transforme le résultat de mail_account_test ({ok, smtp, imap, error})
   *  en message français lisible. Le détail technique part en console. */
  _mailTestMessage(r) {
    if (r && r.ok) return { ok: true, text: '✓ Envoi et réception fonctionnent' };
    if (!r) return { ok: false, text: '✗ Pas de réponse du serveur — réessaie dans un instant.' };
    const raw = String(r.error || '');
    console.warn('Test compte mail — détail :', raw);
    if (/compte introuvable/i.test(raw)) {
      return { ok: false, text: '✗ Compte introuvable — enregistre d’abord les réglages du compte.' };
    }
    const sub = (tag) => {
      const m = raw.match(new RegExp(tag + ':\\s*([^·]+)', 'i'));
      return this._frenchMailError(m ? m[1] : raw);
    };
    if (r.smtp === true && r.imap === false) {
      return { ok: false, text: `✗ L’envoi fonctionne, mais pas la réception : ${sub('IMAP')}.` };
    }
    if (r.smtp === false && r.imap === true) {
      return { ok: false, text: `✗ La réception fonctionne, mais pas l’envoi : ${sub('SMTP')}.` };
    }
    if (r.smtp === false && r.imap === false) {
      return { ok: false, text: `✗ Envoi : ${sub('SMTP')} · Réception : ${sub('IMAP')}.` };
    }
    return { ok: false, text: `✗ ${this._frenchMailError(raw)}.` };
  },

  /** Traduit une erreur technique SMTP/IMAP en français simple. */
  _frenchMailError(raw) {
    const s = String(raw || '');
    if (/535|authent|auth.{0,12}(fail|error|denied)|login.{0,12}(fail|denied|invalid)|invalid credential|password|credentials/i.test(s)) {
      return 'identifiant ou mot de passe refusé';
    }
    if (/getaddrinfo|name or service|nodename|11001|gaierror|no address|not known|introuvable/i.test(s)) {
      return 'serveur introuvable (vérifie le nom du serveur)';
    }
    if (/timed?\s?out|timeout/i.test(s)) {
      return 'le serveur ne répond pas (délai dépassé)';
    }
    if (/refused|10061/i.test(s)) {
      return 'connexion refusée (vérifie le port)';
    }
    if (/ssl|tls|certificate/i.test(s)) {
      return 'problème de connexion sécurisée (vérifie le port et le serveur)';
    }
    return 'erreur de connexion (détail technique en console)';
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
                 placeholder="Identifiant Stripe (prod_… ou price_…)"
                 class="col-span-5 px-2 py-1.5 rounded-lg bg-bg border border-border text-sm focus:border-accent focus:outline-none" />
          <input type="text" data-map-key="${i}" value="${this._esc(prodKey)}"
                 placeholder="pack-electricien-pro"
                 class="col-span-4 px-2 py-1.5 rounded-lg bg-bg border border-border text-sm focus:border-accent focus:outline-none" />
          <input type="text" data-map-name="${i}" value="${this._esc(mapping[stripeId + '_name'] || '')}"
                 placeholder="Nom affiché"
                 class="col-span-2 px-2 py-1.5 rounded-lg bg-bg border border-border text-sm focus:border-accent focus:outline-none" />
          <button class="col-span-1 text-text-muted hover:text-danger text-lg leading-none" data-map-del="${i}" title="Supprimer cette ligne" aria-label="Supprimer cette ligne">×</button>
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
              <div class="text-sm font-medium">Vérifier les paiements automatiquement</div>
              <div class="text-xs text-text-muted">L’app consulte Stripe toutes les 5 minutes (réglable) pour repérer les nouveaux paiements.</div>
            </div>
          </label>

          <div>
            <label class="block text-xs font-medium text-text-secondary mb-1.5">
              Clé secrète Stripe ${c._has_key ? '<span class="text-success">(✓ enregistrée)</span>' : ''}
            </label>
            <input type="password" data-stripe-key="secret_key"
                   placeholder="${c._has_key ? '(clé enregistrée — tape pour remplacer)' : 'Colle ici ta clé secrète Stripe'}"
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
              L’identifiant du produit (il commence par prod_ ou price_) se trouve dans Stripe → Produits.
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

          <div class="flex gap-3 pt-2 flex-wrap">
            <button class="btn btn-primary" id="stripe-save">Enregistrer</button>
            <button class="btn btn-secondary" id="stripe-test">Enregistrer et lancer un vrai passage</button>
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
        if (r && r.ok) save.textContent = 'Enregistré ✓';
        else {
          save.textContent = 'Échec';
          Toast.error('Enregistrement impossible : ' + ((r && r.error) || 'erreur inconnue'));
        }
      } catch (e) {
        save.textContent = 'Échec';
        Toast.friendlyError(e, 'Enregistrement impossible — réessaie dans un instant.');
      }
      setTimeout(() => { save.disabled = false; save.textContent = 'Enregistrer'; }, 1600);
    };

    test.onclick = async () => {
      if (!App.api) return;
      const sure = await Dialog.confirm(
        'Ce n’est pas un essai à blanc : de vrais projets clients peuvent être créés. Continuer ?',
        { title: 'Lancer un vrai passage Stripe', okLabel: 'Lancer', danger: true });
      if (!sure) return;
      test.disabled = true; test.textContent = 'Passage en cours…';
      fb.textContent = '';
      try {
        await App.api.stripe_save_config({ config: gather() });
        const r = await App.api.stripe_run_now();
        if (r && r.ok && r.result) {
          const c = r.result;
          const msg = `${c.polled || 0} paiements consultés, ${c.new_payments || 0} nouveaux, ${c.projects_created || 0} projets créés` +
                      (c.errors ? `, ${c.errors} erreurs` : '');
          fb.textContent = msg;
          if (c.error) console.warn('stripe_run_now :', c.error);
          if (c.errors || c.error) Toast.warn(msg + ' — une erreur est survenue (détail en console).');
          else Toast.success(msg);
        } else {
          console.warn('stripe_run_now :', r && r.error);
          fb.textContent = 'Le passage a échoué.';
          Toast.error('Le passage a échoué : ' + ((r && r.error) || 'erreur inconnue'));
        }
      } catch (e) {
        fb.textContent = '';
        Toast.friendlyError(e, 'Le passage a échoué — réessaie dans un instant.');
      }
      test.disabled = false; test.textContent = 'Enregistrer et lancer un vrai passage';
    };

    if (addMap) addMap.onclick = () => {
      const wrap = document.getElementById('stripe-mapping');
      const idx = Date.now();
      const row = document.createElement('div');
      row.className = 'grid grid-cols-12 gap-2 items-center';
      row.dataset.mapRow = idx;
      row.innerHTML = `
        <input type="text" data-map-stripe="${idx}" placeholder="Identifiant Stripe (prod_… ou price_…)"
               class="col-span-5 px-2 py-1.5 rounded-lg bg-bg border border-border text-sm focus:border-accent focus:outline-none" />
        <input type="text" data-map-key="${idx}" placeholder="pack-electricien-pro"
               class="col-span-4 px-2 py-1.5 rounded-lg bg-bg border border-border text-sm focus:border-accent focus:outline-none" />
        <input type="text" data-map-name="${idx}" placeholder="Nom affiché"
               class="col-span-2 px-2 py-1.5 rounded-lg bg-bg border border-border text-sm focus:border-accent focus:outline-none" />
        <button class="col-span-1 text-text-muted hover:text-danger text-lg leading-none" data-map-del="${idx}" title="Supprimer cette ligne" aria-label="Supprimer cette ligne">×</button>
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

          <hr class="border-border my-2" />

          <div>
            <div class="text-sm font-semibold mb-1">Phantoms de découverte (LinkedIn / Instagram / TikTok)</div>
            <div class="text-[11px] text-text-muted mb-3">
              Pour qu'Obelisk puisse chercher des profils sur ces 3 plateformes,
              crée un Phantom de découverte côté Phantombuster (un par plateforme)
              et colle ici son ID. Tu peux laisser vide les plateformes que tu ne
              veux pas utiliser.
            </div>
            <div class="space-y-3">
              <div>
                <label class="block text-xs font-medium text-text-secondary mb-1.5">
                  Phantom « LinkedIn Search Export »
                </label>
                <input type="text" data-pb-key="discovery_phantoms.linkedin"
                       value="${this._esc((c.discovery_phantoms || {}).linkedin || '')}"
                       placeholder="ID du Phantom LinkedIn Search"
                       class="w-full px-3 py-2 rounded-lg bg-bg border border-border text-sm focus:border-accent focus:outline-none font-mono" />
              </div>
              <div>
                <label class="block text-xs font-medium text-text-secondary mb-1.5">
                  Phantom « Instagram Hashtag Collector »
                </label>
                <input type="text" data-pb-key="discovery_phantoms.instagram"
                       value="${this._esc((c.discovery_phantoms || {}).instagram || '')}"
                       placeholder="ID du Phantom Instagram Hashtag"
                       class="w-full px-3 py-2 rounded-lg bg-bg border border-border text-sm focus:border-accent focus:outline-none font-mono" />
              </div>
              <div>
                <label class="block text-xs font-medium text-text-secondary mb-1.5">
                  Phantom « TikTok Hashtag Scraper »
                </label>
                <input type="text" data-pb-key="discovery_phantoms.tiktok"
                       value="${this._esc((c.discovery_phantoms || {}).tiktok || '')}"
                       placeholder="ID du Phantom TikTok Hashtag"
                       class="w-full px-3 py-2 rounded-lg bg-bg border border-border text-sm focus:border-accent focus:outline-none font-mono" />
              </div>
            </div>
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
        discovery_phantoms: {
          linkedin:  v('discovery_phantoms.linkedin')  || '',
          instagram: v('discovery_phantoms.instagram') || '',
          tiktok:    v('discovery_phantoms.tiktok')    || '',
        },
      };
    };
    save.onclick = async () => {
      if (!App.api) return;
      save.disabled = true; save.textContent = 'Enregistrement…';
      try {
        const r = await App.api.phantombuster_save_config({ config: gather() });
        if (r && r.ok) save.textContent = 'Enregistré ✓';
        else {
          save.textContent = 'Échec';
          Toast.error('Enregistrement impossible : ' + ((r && r.error) || 'erreur inconnue'));
        }
      } catch (e) {
        save.textContent = 'Échec';
        Toast.friendlyError(e, 'Enregistrement impossible — réessaie dans un instant.');
      }
      setTimeout(() => { save.disabled = false; save.textContent = 'Enregistrer'; }, 1600);
    };
    test.onclick = async () => {
      if (!App.api) return;
      test.disabled = true; test.textContent = 'Vérification…';
      fb.textContent = '';
      try {
        await App.api.phantombuster_save_config({ config: gather() });
        const r = await App.api.phantombuster_test();
        if (r && r.ok) {
          fb.innerHTML = `<span class="text-success">✓ Connecté — ${r.agents_count || 0} Phantom(s) trouvé(s)</span>`;
        } else {
          console.warn('phantombuster_test :', r && r.error);
          fb.innerHTML = `<span class="text-danger">✗ Connexion impossible (clé refusée ou service injoignable — détail en console)</span>`;
        }
      } catch (e) {
        console.warn('phantombuster_test :', e);
        fb.textContent = '';
        Toast.friendlyError(e, 'La vérification a échoué — réessaie dans un instant.');
      }
      test.disabled = false; test.textContent = 'Vérifier la connexion';
    };
  },

  _renderTracker(cfg) {
    const c = cfg || { enabled: false, pixel_endpoint: '' };
    return `
      <section>
        <div class="section-label">Suivi des ouvertures de mail</div>
        <p class="text-sm text-text-muted mb-4">
          Glisse une image invisible dans tes mails pour savoir s’ils sont
          ouverts. Nécessite un petit compteur gratuit hébergé en ligne —
          demande à Claude de l’installer (~5 min).
        </p>
        <div class="card p-6 space-y-4">
          <label class="flex items-start gap-3 cursor-pointer">
            <input type="checkbox" data-trk-key="enabled" ${c.enabled?'checked':''}
                   class="mt-0.5 w-4 h-4 accent-accent" />
            <div>
              <div class="text-sm font-medium">Activer le suivi des ouvertures</div>
              <div class="text-xs text-text-muted">
                Tous les mails sortants incluront l’image invisible. Respecte la vie
                privée : aucune adresse ni aucun appareil enregistrés.
              </div>
            </div>
          </label>

          <div>
            <label class="block text-xs font-medium text-text-secondary mb-1.5">Adresse du compteur d’ouvertures</label>
            <input type="text" data-trk-key="pixel_endpoint" value="${this._esc(c.pixel_endpoint || '')}"
                   placeholder="https://…"
                   class="w-full px-3 py-2 rounded-lg bg-bg border border-border text-sm focus:border-accent focus:outline-none font-mono" />
            <div class="text-[11px] text-text-muted mt-1">
              L’adresse commence par https:// — c’est Claude qui te la donne à l’installation.
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
      const cfg = {
        enabled: !!document.querySelector('[data-trk-key="enabled"]').checked,
        pixel_endpoint: document.querySelector('[data-trk-key="pixel_endpoint"]').value.trim(),
      };
      // Validation simple avant d'enregistrer : l'adresse doit être en https://
      if (cfg.pixel_endpoint && !cfg.pixel_endpoint.startsWith('https://')) {
        Toast.error('L’adresse du compteur doit commencer par https://');
        return;
      }
      save.disabled = true; save.textContent = 'Enregistrement…';
      try {
        const r = await App.api.tracker_save_config({ config: cfg });
        if (r && r.ok) save.textContent = 'Enregistré ✓';
        else {
          save.textContent = 'Échec';
          Toast.error('Enregistrement impossible : ' + ((r && r.error) || 'erreur inconnue'));
        }
      } catch (e) {
        save.textContent = 'Échec';
        Toast.friendlyError(e, 'Enregistrement impossible — réessaie dans un instant.');
      }
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
              ${opt('strong', 'Seulement si signal d’achat fort (prix, devis, « j’achète »…) — recommandé', c.mode)}
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
                   data-initial="${c.min_confidence ?? 0.6}"
                   class="w-32 px-3 py-2 rounded-lg bg-bg border border-border text-sm focus:border-accent focus:outline-none" />
            <div class="text-[11px] text-text-muted mt-1">
              C’est le niveau de certitude exigé de l’IA, entre 0 et 1 :
              0.7 = elle doit être sûre à 70 % (prudent), 0.5 = sûre à 50 % (plus souple).
              En dessous du seuil, pas de bascule automatique. Par défaut : 0.6.
            </div>
          </div>

          <div class="flex gap-3 pt-2 flex-wrap">
            <button class="btn btn-primary" id="l2c-save">Enregistrer</button>
            <button class="btn btn-secondary" id="l2c-run">Enregistrer et lancer un vrai passage</button>
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

    // La case « Activer » et l'option « Jamais » disent la même chose :
    // on les garde synchronisées pour éviter un réglage contradictoire.
    const enabledEl = document.querySelector('[data-l2c-key="enabled"]');
    const modeEl    = document.querySelector('[data-l2c-key="mode"]');
    if (enabledEl && modeEl) {
      enabledEl.addEventListener('change', () => {
        if (!enabledEl.checked) modeEl.value = 'off';
        else if (modeEl.value === 'off') modeEl.value = 'strong';
      });
      modeEl.addEventListener('change', () => {
        enabledEl.checked = modeEl.value !== 'off';
      });
    }

    const gather = () => {
      const v = (k) => {
        const el = document.querySelector(`[data-l2c-key="${k}"]`);
        if (!el) return undefined;
        if (el.type === 'checkbox') return !!el.checked;
        return el.value;
      };
      // Seuil de confiance : borné entre 0 et 1 ; champ vide = on garde
      // la valeur déjà enregistrée (surtout pas 0, qui basculerait tout).
      let minConf;
      const mcEl = document.querySelector('[data-l2c-key="min_confidence"]');
      if (mcEl) {
        const parsed = parseFloat(mcEl.value);
        if ((mcEl.value || '').trim() === '' || isNaN(parsed)) {
          minConf = parseFloat(mcEl.dataset.initial);
          if (isNaN(minConf)) minConf = 0.6;
        } else {
          minConf = Math.min(1, Math.max(0, parsed));
        }
      }
      return {
        enabled: v('enabled'),
        mode:    v('mode'),
        default_product_key:  v('default_product_key'),
        default_product_name: v('default_product_name'),
        min_confidence:       minConf,
      };
    };
    save.onclick = async () => {
      if (!App.api) return;
      save.disabled = true; save.textContent = 'Enregistrement…';
      try {
        const r = await App.api.lead_to_client_save_config({ config: gather() });
        if (r && r.ok) save.textContent = 'Enregistré ✓';
        else {
          save.textContent = 'Échec';
          Toast.error('Enregistrement impossible : ' + ((r && r.error) || 'erreur inconnue'));
        }
      } catch (e) {
        save.textContent = 'Échec';
        Toast.friendlyError(e, 'Enregistrement impossible — réessaie dans un instant.');
      }
      setTimeout(() => { save.disabled = false; save.textContent = 'Enregistrer'; }, 1600);
    };
    run.onclick = async () => {
      if (!App.api) return;
      const sure = await Dialog.confirm(
        'Ce n’est pas un essai à blanc : de vrais projets clients peuvent être créés. Continuer ?',
        { title: 'Lancer un vrai passage', okLabel: 'Lancer', danger: true });
      if (!sure) return;
      run.disabled = true; run.textContent = 'Passage en cours…';
      fb.textContent = '';
      try {
        // Sauve la config avant le passage pour utiliser les nouveaux réglages
        await App.api.lead_to_client_save_config({ config: gather() });
        const r = await App.api.lead_to_client_run_now();
        if (r && r.ok && r.result) {
          const c = r.result;
          const msg = `${c.scanned || 0} réponses examinées, ${c.converted || 0} projets clients créés, ` +
                      `${c.weak_signal || 0} signaux trop faibles, ${c.skipped || 0} ignorées` +
                      (c.errors ? `, ${c.errors} erreurs` : '');
          fb.textContent = msg;
          if (c.errors) Toast.warn(msg);
          else Toast.success(msg);
        } else {
          console.warn('lead_to_client_run_now :', r && r.error);
          fb.textContent = 'Le passage a échoué.';
          Toast.error('Le passage a échoué : ' + ((r && r.error) || 'erreur inconnue'));
        }
      } catch (e) {
        fb.textContent = '';
        Toast.friendlyError(e, 'Le passage a échoué — réessaie dans un instant.');
      }
      run.disabled = false; run.textContent = 'Enregistrer et lancer un vrai passage';
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
            <div class="text-sm text-text-muted">Une visite pas à pas pour redécouvrir tout ce que l’app sait faire.</div>
          </div>
          <button class="btn btn-secondary" onclick="App.show('tutorial')">Lancer la visite</button>
        </div>
      </section>
    `;
  },

  _field(label, savePath, value, type = 'text', placeholder = '') {
    const masked = (type === 'password' && value && value.startsWith('•'));
    const fid = 'cfg-f-' + String(savePath).replace(/[^a-zA-Z0-9_-]+/g, '-');
    return `
      <div>
        <label for="${fid}" class="block text-sm font-semibold mb-1">${this._esc(label)}</label>
        <input id="${fid}" type="${type}"
               data-save-path="${savePath}"
               value="${masked ? '' : this._esc(value || '')}"
               placeholder="${this._esc(placeholder || (masked ? '••••••••' : ''))}"
               class="w-full px-4 py-2.5 text-sm rounded-xl bg-bg border border-border
                      focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent" />
      </div>
    `;
  },

  /** Petit « ✓ enregistré » éphémère sous un champ après un auto-enregistrement. */
  _flashSaved(input) {
    const holder = input && input.parentElement;
    if (!holder) return;
    let tick = holder.querySelector('.cfg-saved-tick');
    if (!tick) {
      tick = document.createElement('div');
      tick.className = 'cfg-saved-tick text-[11px] text-success mt-1';
      holder.appendChild(tick);
    }
    tick.textContent = '✓ enregistré';
    clearTimeout(tick._t);
    tick._t = setTimeout(() => tick.remove(), 1600);
  },

  _bind() {
    // Boutons thème
    document.querySelectorAll('[data-theme-mode]').forEach(btn => {
      btn.onclick = async () => {
        if (!App.api) return;
        const mode = btn.dataset.themeMode;
        try {
          const r = await App.api.set_theme_mode(mode);
          if (r && r.ok) {
            document.documentElement.setAttribute('data-theme', r.mode);
            await this.refresh();
          } else {
            Toast.error('Le changement de thème a échoué — réessaie.');
          }
        } catch (e) {
          Toast.friendlyError(e, 'Le changement de thème a échoué — réessaie.');
        }
      };
    });

    // Auto-save sur blur pour chaque champ — SAUF les inputs IA, qui ont
    // leur propre bouton Enregistrer (pour éviter de sauver une demi-clé)
    document.querySelectorAll('[data-save-path]').forEach(input => {
      if (input.hasAttribute('data-ai-key-input')) return;
      input.addEventListener('blur', async () => {
        if (!App.api) return;
        // Chargement raté = auto-enregistrement suspendu (comme promis par
        // le bandeau) : on n'écrit rien tant que les vrais réglages n'ont
        // pas pu être relus, pour ne pas les écraser avec du vide.
        if (this._loadFailed) return;
        const v = input.value;
        if (v === '' && input.type === 'password') return;  // ne pas écraser un mot de passe avec vide
        const path = input.dataset.savePath.split('.');
        let value = v;
        if (input.type === 'number') {
          value = v === '' ? null : parseInt(v, 10);
        }
        try {
          const r = await App.api.save_setting({ path, value });
          if (r && r.ok === false) {
            console.warn('save_setting :', r.error);
            Toast.error('Ce réglage n’a pas pu être enregistré — réessaie.');
            return;
          }
          this._flashSaved(input);
        } catch (e) {
          Toast.friendlyError(e, 'Ce réglage n’a pas pu être enregistré — réessaie.');
        }
      });
    });

    // Branche les boutons Enregistrer / Tester des clés IA
    this._wireAiButtons();
  },

  _esc(s) {
    return String(s || '').replace(/[&<>"']/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    }[c]));
  },
};
