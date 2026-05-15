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
            Ta session vers la base partagée Triskell. Indispensable pour Matinale,
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
      if (!confirm('Se déconnecter de Supabase ?\n\nLes pages Matinale, Brouillons, Réponses, etc. ne fonctionneront plus tant que tu ne te reconnectes pas.')) return;
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
        <div class="section-label">Ma signature mail</div>
        <p class="text-sm text-text-muted mb-4">
          Ajoutée automatiquement à la fin de chaque mail que tu envoies depuis Triskell Command.
          Tu peux choisir une version texte simple OU une version HTML enrichie (logo, couleurs, liens).
          Chaque utilisateur a sa propre signature, stockée localement sur ton PC.
        </p>
        <div class="card p-5 space-y-3">
          <div class="flex items-center gap-1 text-[11px]">
            <button id="sig-mode-text" class="px-3 py-1.5 rounded-lg font-semibold bg-accent/15 text-accent">Texte simple</button>
            <button id="sig-mode-html" class="px-3 py-1.5 rounded-lg font-semibold text-text-muted hover:bg-bg">HTML enrichi (avec aperçu)</button>
          </div>

          <!-- Mode texte simple -->
          <div id="sig-text-zone">
            <textarea id="cfg-signature" rows="5"
                      placeholder="ex :&#10;&#10;Jordan&#10;Triskell Studio · triskell-studio.fr&#10;06 12 34 56 78"
                      class="w-full px-3 py-2 text-sm rounded-lg bg-bg border border-border focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent font-sans leading-relaxed resize-y"></textarea>
          </div>

          <!-- Mode HTML : 2 colonnes (code + preview) -->
          <div id="sig-html-zone" class="hidden">
            <div class="grid grid-cols-1 md:grid-cols-2 gap-3" style="min-height: 240px;">
              <div class="flex flex-col">
                <div class="text-[10px] font-bold uppercase tracking-widest text-text-muted mb-1">Code HTML</div>
                <textarea id="cfg-signature-html" rows="10" placeholder='<p>Bonjour…</p><p>—<br><strong>Jordan</strong></p>'
                          class="flex-1 px-3 py-2 text-xs rounded-lg bg-bg border border-border focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent font-mono leading-relaxed resize-y" style="min-height: 200px;"></textarea>
              </div>
              <div class="flex flex-col">
                <div class="text-[10px] font-bold uppercase tracking-widest text-text-muted mb-1">Aperçu (rendu mail)</div>
                <iframe id="cfg-signature-preview" sandbox="allow-same-origin"
                        class="flex-1 w-full rounded-lg border border-border bg-white" style="min-height: 200px;"></iframe>
              </div>
            </div>
          </div>

          <div class="flex items-center gap-3">
            <button id="cfg-signature-save" class="btn btn-primary">Sauvegarder</button>
            <span id="cfg-signature-status" class="text-xs text-text-muted"></span>
          </div>
        </div>
      </section>
    `;
  },

  async _bindSignature() {
    if (!App.api) return;
    const ta       = document.getElementById('cfg-signature');
    const htmlTa   = document.getElementById('cfg-signature-html');
    const iframe   = document.getElementById('cfg-signature-preview');
    const textZone = document.getElementById('sig-text-zone');
    const htmlZone = document.getElementById('sig-html-zone');
    const tBtn     = document.getElementById('sig-mode-text');
    const hBtn     = document.getElementById('sig-mode-html');
    if (!ta || !htmlTa) return;

    // Charge l'existant
    try {
      const r = await App.api.signature_get();
      if (r && r.ok) {
        ta.value     = r.signature      || '';
        htmlTa.value = r.signature_html || '';
        if (htmlTa.value) this._renderSigPreview(iframe, htmlTa.value);
      }
    } catch (e) {}

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
        // Si HTML vide mais texte présent → propose une conversion basique
        if (!htmlTa.value.trim() && ta.value.trim()) {
          htmlTa.value = ta.value.split(/\n\n+/)
            .map(p => `<p>${this._escape(p).replace(/\n/g, '<br>')}</p>`).join('');
          this._renderSigPreview(iframe, htmlTa.value);
        }
      }
    };
    tBtn.onclick = () => setMode('text');
    hBtn.onclick = () => setMode('html');

    // Live preview sur saisie HTML
    let timer = null;
    htmlTa.addEventListener('input', () => {
      clearTimeout(timer);
      timer = setTimeout(() => this._renderSigPreview(iframe, htmlTa.value), 200);
    });

    const saveBtn = document.getElementById('cfg-signature-save');
    if (saveBtn) saveBtn.onclick = async () => {
      const status = document.getElementById('cfg-signature-status');
      status.textContent = 'Sauvegarde…';
      status.className = 'text-xs text-text-muted';
      const r = await App.api.signature_save({
        signature: ta.value,
        signature_html: htmlTa.value,
      });
      if (r && r.ok) {
        status.textContent = '✓ Sauvegardé. Sera ajoutée à tes prochains mails.';
        status.className = 'text-xs text-success';
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
                Si désactivé, les relances LinkedIn restent à envoyer manuellement (3 clics depuis la Matinale).
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
