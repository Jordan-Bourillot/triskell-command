/* Le Chasseur — vue de découverte de PME via API officielle data.gouv.
 *
 * Pipeline visible côté UI :
 *   1. L'utilisateur choisit un secteur (preset OU code NAF OU mot-clé) +
 *      une zone (département / code postal / commune) + un volume cible.
 *   2. On lance une chasse en arrière-plan (`chasseur_start_hunt`).
 *   3. On poll l'état du job (`chasseur_get_hunt`) toutes les 2s : progression,
 *      stats, lignes de log.
 *   4. Quand c'est terminé, « Envoyer à l'Auto-pilote » verse les prospects
 *      dans la base commune « Tous les prospects » (l'Auto-pilote les prendra
 *      à son prochain passage). Un CSV, fabriqué CÔTÉ NAVIGATEUR, reste
 *      téléchargeable pour Le Convoi.
 */

const Chasseur = {
  state: {
    presets: [],            // [{id, label, naf}]
    hunts: [],              // index des chasses connues
    currentId: null,        // chasse ouverte (détail à droite)
    currentHunt: null,      // payload complet de la chasse
    pollTimer: null,
  },

  // Persistance "où j'en étais" — survit à un refresh complet de l'app.
  _LS_FORM: 'chasseur:form',
  _LS_CURRENT: 'chasseur:currentId',

  _saveForm() {
    try {
      const f = {
        preset:        document.getElementById('ch-preset')?.value || '',
        sectorCustom:  document.getElementById('ch-sector-custom')?.value || '',
        dept:          document.getElementById('ch-dept')?.value || '',
        cp:            document.getElementById('ch-cp')?.value || '',
        target:        document.getElementById('ch-target')?.value || '200',
        onlyEmail:     !!document.getElementById('ch-only-email')?.checked,
        mode:          document.getElementById('ch-mode')?.value || 'poor_sites',
      };
      localStorage.setItem(this._LS_FORM, JSON.stringify(f));
    } catch (e) {}
  },

  _readForm() {
    try { return JSON.parse(localStorage.getItem(this._LS_FORM) || 'null'); }
    catch (e) { return null; }
  },

  _applyForm() {
    const f = this._readForm();
    if (!f) return;
    const set = (id, val) => { const el = document.getElementById(id); if (el != null && val != null) el.value = val; };
    set('ch-preset', f.preset);
    set('ch-sector-custom', f.sectorCustom);
    set('ch-dept', f.dept);
    set('ch-cp', f.cp);
    set('ch-target', f.target);
    if (f.onlyEmail != null) {
      const el = document.getElementById('ch-only-email');
      if (el) el.checked = !!f.onlyEmail;
    }
    if (f.mode) {
      const modeEl = document.getElementById('ch-mode');
      if (modeEl) modeEl.value = f.mode;
      document.querySelectorAll('[data-mode]').forEach(b => {
        b.classList.toggle('ch-mode-active', b.dataset.mode === f.mode);
      });
    }
  },

  _bindFormPersist() {
    const root = document.getElementById('ch-form');
    if (!root) return;
    const save = () => this._saveForm();
    root.querySelectorAll('input, select').forEach(el => {
      el.addEventListener('input',  save);
      el.addEventListener('change', save);
    });
  },

  // Dép FR + Corse + DOM (les principaux). Suffit pour l'UI ; on accepte
  // aussi des inputs libres.
  DEPARTEMENTS: [
    "", "01", "02", "03", "04", "05", "06", "07", "08", "09", "10",
    "11", "12", "13", "14", "15", "16", "17", "18", "19", "21", "22",
    "23", "24", "25", "26", "27", "28", "29", "2A", "2B", "30", "31",
    "32", "33", "34", "35", "36", "37", "38", "39", "40", "41", "42",
    "43", "44", "45", "46", "47", "48", "49", "50", "51", "52", "53",
    "54", "55", "56", "57", "58", "59", "60", "61", "62", "63", "64",
    "65", "66", "67", "68", "69", "70", "71", "72", "73", "74", "75",
    "76", "77", "78", "79", "80", "81", "82", "83", "84", "85", "86",
    "87", "88", "89", "90", "91", "92", "93", "94", "95",
    "971", "972", "973", "974", "976",
  ],

  async _api(method, payload) {
    if (!App.api) return null;
    const fn = App.api['chasseur_' + method];
    if (typeof fn !== 'function') {
      console.warn('chasseur_' + method + ' indisponible');
      return null;
    }
    try { return await fn(payload || {}); }
    catch (e) { console.warn('chasseur.' + method, e); return null; }
  },

  async render(container) {
    this._root = container;
    container.innerHTML = `
      <section class="animate-slide-up">
        <header class="mb-6 sm:mb-8">
          <div class="hero-kicker mb-2" style="color: hsl(var(--accent));">LE CHASSEUR</div>
          <h1 class="hero-title hero-title--md mb-2 sm:mb-3">
            Va chercher les PME, ramène leurs mails publics.
          </h1>
          <p class="hero-subtitle">
            Choisis un secteur, une zone, un volume. Le Chasseur interroge la
            base officielle des entreprises (data.gouv), retrouve leur site,
            extrait les mails publiés sur leur page contact. À la fin, le bouton
            <b>« Ajouter à ma base de prospects »</b> verse la récolte dans
            <b>« Tous les prospects »</b>, prête pour l’envoi.
          </p>
        </header>
        <div class="mb-4 text-[12px] text-text-muted px-3 py-2 rounded-lg bg-accent/5 border border-accent/20" style="text-wrap: pretty">
          🧭 Outil avancé. Pour le parcours simple (recherche + envoi qui s'enchaînent
          tout seuls), passe par
          <button type="button" class="text-accent underline hover:no-underline" onclick="App.show('prospection')">Lancer une prospection</button>.
        </div>

        <div class="grid lg:grid-cols-[340px,1fr] gap-5">
          <!-- ============== Colonne gauche : nouvelle chasse + historique ============== -->
          <aside class="space-y-4">
            <div class="card p-4">
              <div class="text-[11px] font-bold tracking-widest text-text-muted mb-3">
                NOUVELLE CHASSE
              </div>
              <form id="ch-form" class="space-y-3">
                <div>
                  <label class="block text-xs font-semibold mb-1">Mode de chasse</label>
                  <div class="grid grid-cols-2 gap-1.5">
                    <button type="button" data-mode="poor_sites"
                            class="ch-mode-btn ch-mode-active text-xs font-semibold py-2 px-2 rounded-lg border transition-all text-left leading-tight">
                      <div class="font-bold mb-0.5">🎯 Sites pourris</div>
                      <div class="text-[11px] opacity-80">Cibles refonte</div>
                    </button>
                    <button type="button" data-mode="all"
                            class="ch-mode-btn text-xs font-semibold py-2 px-2 rounded-lg border transition-all text-left leading-tight">
                      <div class="font-bold mb-0.5">📬 Large</div>
                      <div class="text-[11px] opacity-80">Tout site avec mail</div>
                    </button>
                  </div>
                  <input type="hidden" id="ch-mode" value="poor_sites" />
                </div>
                <div>
                  <label class="block text-xs font-semibold mb-1">Secteur</label>
                  <select id="ch-preset" class="w-full input">
                    <option value="">— Choisis un secteur —</option>
                  </select>
                  <input id="ch-sector-custom" type="text" class="w-full input mt-2"
                         placeholder="… ou tape un code NAF (56.10A) / mot-clé" />
                </div>
                <div class="grid grid-cols-2 gap-2">
                  <div>
                    <label class="block text-xs font-semibold mb-1">Département</label>
                    <select id="ch-dept" class="w-full input">
                      ${this.DEPARTEMENTS.map(d => `<option value="${d}">${d || 'Toute la France'}</option>`).join('')}
                    </select>
                  </div>
                  <div>
                    <label class="block text-xs font-semibold mb-1">Code postal</label>
                    <input id="ch-cp" type="text" class="w-full input"
                           placeholder="ex 35000" maxlength="5" />
                  </div>
                </div>
                <div>
                  <label class="block text-xs font-semibold mb-1">Créées depuis (optionnel)</label>
                  <select id="ch-min-date" class="w-full input">
                    <option value="">Peu importe l'ancienneté</option>
                    <option value="6">6 derniers mois</option>
                    <option value="12">1 an</option>
                    <option value="24">2 ans</option>
                    <option value="36">3 ans</option>
                  </select>
                  <p class="text-[11px] text-text-muted mt-1">Les entreprises récentes ont souvent besoin d'un premier site.</p>
                </div>
                <div>
                  <label class="block text-xs font-semibold mb-1">Volume cible</label>
                  <select id="ch-target" class="w-full input">
                    <option value="50">50 prospects</option>
                    <option value="100">100 prospects</option>
                    <option value="200" selected>200 prospects</option>
                    <option value="500">500 prospects</option>
                    <option value="1000">1 000 prospects</option>
                  </select>
                </div>
                <label class="flex items-center gap-2 text-xs text-text-secondary">
                  <input id="ch-only-email" type="checkbox" checked />
                  Ne garder que les boîtes avec un mail trouvé
                </label>
                <button type="submit" class="btn btn-primary w-full">
                  <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M12 2l3 6 6 1-4.5 4 1 6L12 16l-5.5 3 1-6L3 9l6-1z"/></svg>
                  Lancer la chasse
                </button>
                <p class="text-[11px] text-text-muted leading-snug">
                  Compte ~1 à 3 min par tranche de 50 prospects. Tu peux
                  fermer cette fenêtre, ça tourne en fond.
                </p>
              </form>
            </div>

            <div class="card p-4">
              <div class="flex items-center justify-between mb-3">
                <div class="text-[11px] font-bold tracking-widest text-text-muted">
                  CHASSES PASSÉES
                </div>
                <button id="ch-refresh-list" class="text-xs text-accent hover:underline"
                        title="Rafraîchir la liste des chasses"
                        aria-label="Rafraîchir la liste des chasses">↻</button>
              </div>
              <div id="ch-hunts-list" class="space-y-1.5 max-h-[420px] overflow-y-auto"></div>
            </div>
          </aside>

          <!-- ============== Colonne droite : détail de la chasse active ============== -->
          <div id="ch-detail" class="min-h-[400px]">
            <div class="card p-10 text-center text-text-muted">
              <div class="text-5xl mb-3 opacity-70">🏹</div>
              <div class="text-base">Lance une chasse ou ouvre-en une dans la liste.</div>
            </div>
          </div>
        </div>
      </section>
    `;

    document.getElementById('ch-form').onsubmit = (e) => {
      e.preventDefault();
      this._launchHunt();
    };
    document.getElementById('ch-refresh-list').onclick = async () => {
      const ok = await this._loadHunts();
      if (!ok) this._toast('Impossible de rafraîchir la liste. Réessaie dans un instant.', 'danger');
    };

    // Bind les 2 boutons de mode (large / sites pourris)
    document.querySelectorAll('[data-mode]').forEach(btn => {
      btn.onclick = () => {
        document.querySelectorAll('[data-mode]').forEach(b => b.classList.remove('ch-mode-active'));
        btn.classList.add('ch-mode-active');
        document.getElementById('ch-mode').value = btn.dataset.mode;
        this._saveForm();
      };
    });

    // Styles spécifiques aux boutons de mode (actif vs inactif) + inputs
    // lisibles dans les 3 thèmes (clair / mid / sombre).
    if (!document.getElementById('ch-mode-styles')) {
      const s = document.createElement('style');
      s.id = 'ch-mode-styles';
      s.textContent = `
        .ch-mode-btn {
          background: transparent;
          border-color: hsl(var(--border-strong));
          color: hsl(var(--text-secondary));
          cursor: pointer;
        }
        .ch-mode-btn:hover { background: hsl(var(--bg)); }
        .ch-mode-btn.ch-mode-active {
          background: hsl(var(--accent) / 0.10);
          border-color: hsl(var(--accent));
          color: hsl(var(--accent));
        }
        /* Inputs / selects du formulaire Chasseur — contraste forcé pour
           que le texte reste lisible dans les 3 thèmes. */
        #ch-form .input,
        #ch-form input[type="text"],
        #ch-form select {
          width: 100%;
          padding: 8px 12px;
          background: hsl(var(--surface));
          color: hsl(var(--text));
          border: 1px solid hsl(var(--border-strong));
          border-radius: 8px;
          font-size: 13px;
          transition: border-color 160ms, box-shadow 160ms;
        }
        #ch-form select {
          appearance: none;
          background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%23888' stroke-width='2'><polyline points='6 9 12 15 18 9'/></svg>");
          background-repeat: no-repeat;
          background-position: right 10px center;
          padding-right: 32px;
        }
        #ch-form .input:focus,
        #ch-form input[type="text"]:focus,
        #ch-form select:focus {
          outline: none;
          border-color: hsl(var(--accent));
          box-shadow: 0 0 0 3px hsl(var(--accent) / 0.15);
        }
        #ch-form input::placeholder { color: hsl(var(--text-muted)); }
        #ch-form select option {
          background: hsl(var(--surface));
          color: hsl(var(--text));
        }

        /* ---------- Stepper (étapes de l'analyse) ---------- */
        .ch-stepper {
          position: relative;
          display: grid;
          grid-template-columns: 1fr 1fr 1fr;
          gap: 0;
          align-items: stretch;
          z-index: 0;
        }
        .ch-step {
          position: relative;
          display: flex;
          flex-direction: column;
          align-items: center;
          text-align: center;
          gap: 6px;
          padding: 4px 8px;
        }
        .ch-step-bullet { position: relative; z-index: 2; }
        .ch-step-bullet {
          flex: 0 0 22px;
          width: 22px;
          height: 22px;
          border-radius: 50%;
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 11px;
          font-weight: 700;
          border: 1.5px solid transparent;
          transition: all 200ms;
        }
        .ch-step-pending .ch-step-bullet {
          background: hsl(var(--bg));
          border-color: hsl(var(--border-strong));
          color: hsl(var(--text-muted));
        }
        .ch-step-active .ch-step-bullet {
          background: hsl(var(--accent) / 0.15);
          border-color: hsl(var(--accent));
          color: hsl(var(--accent));
          box-shadow: 0 0 0 4px hsl(var(--accent) / 0.10);
        }
        .ch-step-done .ch-step-bullet {
          background: hsl(var(--success));
          border-color: hsl(var(--success));
          color: white;
        }
        .ch-step-text { min-width: 0; max-width: 100%; }
        .ch-step-label {
          font-size: 11px;
          font-weight: 700;
          line-height: 1.15;
          color: hsl(var(--text));
        }
        .ch-step-pending .ch-step-label { color: hsl(var(--text-muted)); }
        .ch-step-active .ch-step-label { color: hsl(var(--accent)); }
        .ch-step-sub {
          font-size: 11px;
          color: hsl(var(--text-muted));
          line-height: 1.2;
          margin-top: 2px;
        }
        /* Barre de liaison : part du centre du bullet de cette colonne
           jusqu'au centre du bullet de la colonne suivante, en évitant
           le rond lui-même (margin de 14px de chaque côté). */
        .ch-step-link {
          position: absolute;
          top: 15px;
          left: 50%;
          right: -50%;
          height: 2px;
          background: hsl(var(--border-strong));
          z-index: 1;
          margin-left: 14px;
          margin-right: 14px;
        }
        .ch-step-link-done { background: hsl(var(--success)); }
        .ch-step-dot {
          width: 8px;
          height: 8px;
          border-radius: 50%;
          background: hsl(var(--accent));
          animation: ch-pulse-dot 1.2s ease-in-out infinite;
        }
        @keyframes ch-pulse-dot {
          0%, 100% { transform: scale(0.7); opacity: 0.6; }
          50%      { transform: scale(1.1); opacity: 1; }
        }

        /* ---------- Barre de progression animée (en cours) ---------- */
        .ch-progress-bar-running {
          background-image: linear-gradient(
            90deg,
            hsl(var(--accent)) 0%,
            hsl(var(--accent) / 0.55) 50%,
            hsl(var(--accent)) 100%
          );
          background-size: 200% 100%;
          animation: ch-progress-shimmer 1.6s linear infinite;
        }
        @keyframes ch-progress-shimmer {
          0%   { background-position: 200% 0; }
          100% { background-position: -200% 0; }
        }

        /* Petite pastille "vivante" à côté du libellé d'étape */
        .ch-live-dot {
          display: inline-block;
          width: 7px;
          height: 7px;
          border-radius: 50%;
          background: hsl(var(--accent));
          margin-right: 4px;
          vertical-align: middle;
          animation: ch-pulse-dot 1.2s ease-in-out infinite;
        }
      `;
      document.head.appendChild(s);
    }

    await this._loadPresets();
    // Restaure les valeurs du form après le chargement des presets
    // (sinon le <select preset> n'a pas encore ses options).
    this._applyForm();
    this._bindFormPersist();
    await this._loadHunts();
    // Restaure la chasse active depuis localStorage si state vide
    if (!this.state.currentId) {
      try { this.state.currentId = localStorage.getItem(this._LS_CURRENT) || null; }
      catch (e) {}
    }
    if (this.state.currentId) this._openHunt(this.state.currentId);
  },

  async _loadPresets() {
    const r = await this._api('presets');
    if (!r || !r.ok) return;
    this.state.presets = r.presets || [];
    const sel = document.getElementById('ch-preset');
    if (!sel) return;
    sel.innerHTML = '<option value="">— Choisis un secteur —</option>' +
      this.state.presets.map(p =>
        `<option value="${p.id}">${p.label} (${p.naf})</option>`
      ).join('');
  },

  async _loadHunts() {
    const r = await this._api('list_hunts', {limit: 30});
    if (!r || !r.ok) return false;
    this.state.hunts = r.hunts || [];
    this._renderHuntsList();
    return true;
  },

  _renderHuntsList() {
    const wrap = document.getElementById('ch-hunts-list');
    if (!wrap) return;
    if (!this.state.hunts.length) {
      wrap.innerHTML = `<div class="text-xs text-text-muted">Aucune chasse pour l'instant.</div>`;
      return;
    }
    wrap.innerHTML = this.state.hunts.map(h => {
      const isActive = h.id === this.state.currentId;
      const stats = h.stats || {};
      const retenus = stats.retenus ?? 0;
      const withMail = stats.avec_mail ?? 0;
      const statusBadge = this._statusBadge(h.status, h.running);
      return `
        <div class="ch-hunt-row group relative rounded-lg border transition-all
                    ${isActive
                      ? 'border-accent bg-accent/5'
                      : 'border-border hover:border-border-strong hover:bg-surface'}">
          <button data-hunt-id="${h.id}"
                  class="w-full text-left p-2.5 pr-9">
            <div class="flex items-center justify-between gap-2 mb-1">
              <div class="text-xs font-semibold truncate flex-1">${this._esc(h.label || 'Sans titre')}</div>
              ${statusBadge}
            </div>
            <div class="text-[11px] text-text-muted">
              ${retenus} retenus · ${withMail} avec mail
            </div>
          </button>
          <button data-del-hunt-id="${h.id}"
                  title="Supprimer cette chasse"
                  aria-label="Supprimer cette chasse"
                  class="ch-hunt-del absolute top-1.5 right-1.5 w-6 h-6 rounded-md
                         flex items-center justify-center text-text-muted
                         hover:bg-danger/15 hover:text-danger transition-all">
            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" stroke-width="2.2" viewBox="0 0 24 24">
              <polyline points="3 6 5 6 21 6"/>
              <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>
              <path d="M10 11v6M14 11v6"/>
              <path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/>
            </svg>
          </button>
        </div>
      `;
    }).join('');
    wrap.querySelectorAll('[data-hunt-id]').forEach(btn => {
      btn.onclick = () => this._openHunt(btn.dataset.huntId);
    });
    wrap.querySelectorAll('[data-del-hunt-id]').forEach(btn => {
      btn.onclick = (e) => {
        e.stopPropagation();
        this._deleteHuntById(btn.dataset.delHuntId);
      };
    });
  },

  async _deleteHuntById(huntId) {
    if (!huntId) return;
    // Détecte si la chasse tourne encore (liste ou détail ouvert)
    const inList = this.state.hunts.find(h => h.id === huntId);
    const inDetail = this.state.currentHunt && this.state.currentHunt.id === huntId
      ? this.state.currentHunt : null;
    const isRunning = !!((inList && inList.running) || (inDetail && inDetail.running));
    const ok = await Dialog.confirm(
      isRunning
        ? 'Cette chasse tourne encore — la supprimer arrêtera tout. Supprimer quand même ?'
        : 'Supprimer définitivement cette chasse ?',
      {title: 'Supprimer la chasse', okLabel: 'Supprimer', danger: true}
    );
    if (!ok) return;
    const r = await this._api('delete_hunt', {hunt_id: huntId});
    if (!r || !r.ok) {
      if (r && r.error) console.warn('chasseur.delete_hunt', r.error);
      this._toast('Suppression échouée. Réessaie dans un instant.', 'danger');
      return;
    }
    this._toast('Chasse supprimée.', 'success');
    if (this.state.currentId === huntId) {
      this.state.currentId = null;
      this.state.currentHunt = null;
      try { localStorage.removeItem(this._LS_CURRENT); } catch (e) {}
      this._stopPolling();
      const detail = document.getElementById('ch-detail');
      if (detail) {
        detail.innerHTML = `
          <div class="card p-10 text-center text-text-muted">
            <div class="text-5xl mb-3 opacity-70">🏹</div>
            <div class="text-base">Lance une chasse ou ouvre-en une dans la liste.</div>
          </div>
        `;
      }
    }
    await this._loadHunts();
  },

  _statusBadge(status, running) {
    const map = {
      'pending':   {label: 'En file',              color: 'bg-text-muted/15 text-text-muted'},
      'searching': {label: 'Recherche',            color: 'bg-warning/15 text-warning-text'},
      'enriching': {label: 'Recherche des emails', color: 'bg-accent/15 text-accent'},
      'done':      {label: 'Terminée',             color: 'bg-success/15 text-success-text'},
      'error':     {label: 'Erreur',               color: 'bg-danger/15 text-danger-text'},
    };
    const i = map[status] || {label: 'Statut inconnu', color: 'bg-text-muted/15 text-text-muted'};
    const pulse = running ? 'animate-pulse' : '';
    return `<span class="text-[11px] font-bold px-1.5 py-0.5 rounded whitespace-nowrap ${i.color} ${pulse}">${i.label}</span>`;
  },

  async _launchHunt() {
    const presetId = document.getElementById('ch-preset').value;
    const customSector = document.getElementById('ch-sector-custom').value.trim();
    const dept = document.getElementById('ch-dept').value.trim();
    const cp = document.getElementById('ch-cp').value.trim();
    const target = parseInt(document.getElementById('ch-target').value, 10) || 200;
    const withEmailOnly = document.getElementById('ch-only-email').checked;
    // Même défaut que le bouton actif au chargement (« Sites pourris »)
    const mode = document.getElementById('ch-mode')?.value || 'poor_sites';

    const sector = customSector || presetId;
    if (!sector && !dept && !cp) {
      this._toast('Choisis au moins un secteur ou une zone.', 'warn');
      return;
    }

    const zone = {};
    if (dept) zone.departement = dept;
    if (cp) zone.code_postal = cp;
    // « Créées depuis » : convertit N mois en date YYYY-MM-DD pour le registre.
    const minMonths = parseInt(document.getElementById('ch-min-date')?.value || '0', 10);
    if (minMonths > 0) {
      const dd = new Date();
      dd.setMonth(dd.getMonth() - minMonths);
      const pad2 = (n) => String(n).padStart(2, '0');
      zone.min_date_creation = `${dd.getFullYear()}-${pad2(dd.getMonth() + 1)}-${pad2(dd.getDate())}`;
    }

    // Anti double-clic : bouton gelé le temps de l'appel
    const submitBtn = document.querySelector('#ch-form button[type="submit"]');
    const submitHtml = submitBtn ? submitBtn.innerHTML : '';
    if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = 'Lancement…'; }
    const r = await this._api('start_hunt', {
      sector, zone, target, with_email_only: withEmailOnly, mode,
    });
    if (submitBtn) { submitBtn.disabled = false; submitBtn.innerHTML = submitHtml; }
    if (!r || !r.ok) {
      if (r && r.error) console.warn('chasseur.start_hunt', r.error);
      this._toast((r && r.error) || 'Erreur au lancement de la chasse. Réessaie dans un instant.', 'danger');
      return;
    }
    this._toast('Chasse lancée. Ça tourne en fond.', 'success');
    await this._loadHunts();
    this._openHunt(r.hunt_id);
  },

  async _openHunt(huntId) {
    this.state.currentId = huntId;
    try { localStorage.setItem(this._LS_CURRENT, huntId || ''); } catch (e) {}
    this._renderHuntsList();
    // Indicateur de chargement immédiat (sauf si cette chasse est déjà affichée)
    if (!this.state.currentHunt || this.state.currentHunt.id !== huntId) {
      this.state.currentHunt = null;
      const wrap = document.getElementById('ch-detail');
      if (wrap) {
        wrap.innerHTML = `
          <div class="card p-10 text-center text-text-muted">
            <div class="text-3xl mb-3 animate-pulse">⏳</div>
            <div class="text-base">Chargement de la chasse…</div>
          </div>
        `;
      }
    }
    this._pollFails = 0;
    await this._refreshDetail();
    // Inutile de continuer à interroger une chasse déjà finie
    const h = this.state.currentHunt;
    const finished = h && !h.running && (h.status === 'done' || h.status === 'error');
    if (!finished) this._startPolling();
  },

  _startPolling() {
    this._stopPolling();
    this._pollFails = 0;
    // Minuteur lié à la vue : nettoyé automatiquement quand on change d'écran
    this.state.pollTimer = App.viewInterval(() => {
      this._refreshDetail();
    }, 2000);
  },

  _stopPolling() {
    if (this.state.pollTimer) {
      clearInterval(this.state.pollTimer);
      this.state.pollTimer = null;
    }
  },

  async _refreshDetail() {
    if (!this.state.currentId) return;
    if (this._refreshBusy) return;   // pas de requêtes empilées si le serveur traîne
    this._refreshBusy = true;
    const huntId = this.state.currentId;
    const r = await this._api('get_hunt', {hunt_id: huntId});
    this._refreshBusy = false;
    // L'utilisateur a ouvert une autre chasse pendant la requête → on jette
    if (huntId !== this.state.currentId) return;
    if (!r || !r.ok) {
      // 3 échecs d'affilée (chasse supprimée, serveur injoignable…) → on
      // arrête de tourner en boucle et on explique.
      this._pollFails = (this._pollFails || 0) + 1;
      if (this._pollFails >= 3) {
        this._stopPolling();
        this._toast(
          'Impossible de suivre cette chasse (elle a peut-être été supprimée). ' +
          'Le suivi est arrêté — rouvre-la depuis la liste pour réessayer.',
          'warn'
        );
        if (!this.state.currentHunt) this._renderDetailError();
      }
      return;
    }
    this._pollFails = 0;
    this.state.currentHunt = r.hunt;
    this._renderDetail();
    // Si la chasse est terminée, on stoppe le poll
    if (!r.hunt.running && (r.hunt.status === 'done' || r.hunt.status === 'error')) {
      this._stopPolling();
      // Mise à jour de la liste pour refléter le statut final
      await this._loadHunts();
    }
  },

  // Carte d'erreur quand le détail n'a jamais pu se charger
  _renderDetailError() {
    const wrap = document.getElementById('ch-detail');
    if (!wrap) return;
    const huntId = this.state.currentId;
    wrap.innerHTML = `
      <div class="card p-10 text-center text-text-muted">
        <div class="text-3xl mb-3">⚠️</div>
        <div class="text-base mb-4">Impossible de charger cette chasse. Elle a peut-être été supprimée.</div>
        <button id="ch-retry-open" class="btn btn-secondary">Réessayer</button>
      </div>
    `;
    const btn = document.getElementById('ch-retry-open');
    if (btn) btn.onclick = () => this._openHunt(huntId);
  },

  _renderDetail() {
    const wrap = document.getElementById('ch-detail');
    if (!wrap) return;
    const h = this.state.currentHunt;
    if (!h) return;

    const stats = h.stats || {};
    const candidats = stats.candidats ?? 0;
    const traites = stats.traites ?? 0;
    const retenus = stats.retenus ?? 0;
    const withMail = stats.avec_mail ?? 0;
    const sitesPoor = stats.sites_poor ?? 0;
    const isRunning = h.running;
    const isDone = h.status === 'done';
    const mode = (h.filters && h.filters.mode) || 'all';
    const showQualityCol = mode === 'poor_sites';

    const prospects = h.prospects || [];

    // Le détail est re-rendu toutes les 2s pendant la chasse : on préserve
    // ce que l'utilisateur regarde (journal ouvert, position dans le tableau).
    const logOpen = !!document.getElementById('ch-log-details')?.open;
    const tableScroll = document.getElementById('ch-table-scroll')?.scrollTop || 0;
    const pushedAt = this._pushedAt(h.id);

    wrap.innerHTML = `
      <div class="card p-5 mb-4">
        <div class="flex items-start justify-between gap-3 mb-3">
          <div class="min-w-0 flex-1">
            <div class="text-xs text-text-muted mb-1">${this._fmtDate(h.created_at)}</div>
            <h2 class="text-lg font-bold truncate">${this._esc(h.label)}</h2>
          </div>
          <div class="flex items-center gap-2 flex-wrap justify-end">
            ${this._statusBadge(h.status, isRunning)}
            ${pushedAt ? `
              <span class="text-[11px] font-semibold text-success-text whitespace-nowrap"
                    title="Ces prospects sont déjà dans la base commune « Tous les prospects »${pushedAt.when ? ` (versés le ${pushedAt.when})` : ''}. Re-cliquer ne crée pas de doublon : les fiches identiques fusionnent.">
                ✓ Déjà dans ta base de prospects
              </span>` : ''}
            ${isDone && withMail > 0 ? `
              <button id="ch-push" class="btn btn-primary" title="Verse les prospects avec mail dans la base commune « Tous les prospects » : l’Auto-pilote les prendra au prochain passage pour rédiger et envoyer.">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M5 12l14-7-3 14-4-6-7-1z"/></svg>
                Ajouter à ma base de prospects
              </button>
              <button id="ch-export" class="btn btn-secondary" title="Télécharge un fichier CSV (à glisser dans Le Convoi, par exemple).">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                CSV
              </button>` : ''}
            <button id="ch-delete" class="btn btn-secondary text-xs">Supprimer</button>
          </div>
        </div>

        ${h.error ? `
          <div class="rounded-lg bg-danger/10 border border-danger/30 text-danger-text
                      text-sm p-3 mb-3">⚠️ ${this._esc(h.error)}</div>` : ''}

        <!-- Étapes de l'analyse -->
        ${this._renderStepper(h, mode, candidats, traites)}

        <!-- Barre de progression -->
        <div class="mb-3">
          <div class="flex justify-between items-center text-xs mb-1">
            <span class="${isRunning ? 'text-accent font-semibold' : 'text-text-muted'}">
              ${isRunning
                ? `<span class="ch-live-dot"></span> ${this._currentStepLabel(h, mode, candidats, traites)}`
                : (isDone ? '✅ Chasse terminée' : 'Progression')}
            </span>
            <span class="text-text-muted">${h.progress || 0}%</span>
          </div>
          <div class="h-2.5 rounded-full bg-bg overflow-hidden relative">
            <div class="h-full bg-accent transition-all ${isRunning ? 'ch-progress-bar-running' : ''}"
                 style="width: ${Math.max(h.progress || 0, isRunning ? 3 : 0)}%"></div>
          </div>
        </div>

        <!-- Stats compactes -->
        <div class="grid ${showQualityCol ? 'grid-cols-5' : 'grid-cols-4'} gap-2 text-center">
          ${this._statCell('Candidats',     candidats)}
          ${this._statCell('Traités',       traites)}
          ${this._statCell('Retenus',       retenus)}
          ${this._statCell('Avec mail',     withMail, 'success')}
          ${showQualityCol ? this._statCell('Sites pourris', sitesPoor, 'warning') : ''}
        </div>
        ${mode === 'poor_sites' ? `
          <div class="mt-3 text-[11px] text-text-muted leading-snug">
            🎯 Mode <b>Sites pourris</b> : on ne garde que les boîtes dont le
            site est visiblement obsolète, hébergé sur une plateforme gratuite,
            non sécurisé HTTPS, non mobile, ou clairement abandonné.
          </div>` : ''}
      </div>

      ${prospects.length ? `
        <div class="card p-0 overflow-hidden">
          <div class="px-4 py-3 border-b border-border text-xs font-semibold text-text-muted
                      flex items-center justify-between">
            <span>${prospects.length} prospect${prospects.length > 1 ? 's' : ''} —
                  les mails sont déjà dédoublonnés</span>
            ${isRunning ? `<span class="text-accent animate-pulse">Chasse en cours…</span>` : ''}
          </div>
          <div id="ch-table-scroll" class="overflow-x-auto max-h-[480px] overflow-y-auto">
            <table class="w-full text-sm">
              <thead class="bg-bg sticky top-0">
                <tr class="text-left text-[11px] uppercase tracking-wide text-text-muted">
                  <th class="px-3 py-2">Entreprise</th>
                  <th class="px-3 py-2">Email</th>
                  <th class="px-3 py-2">Ville</th>
                  <th class="px-3 py-2">Site</th>
                  ${showQualityCol ? '<th class="px-3 py-2">État du site</th>' : ''}
                </tr>
              </thead>
              <tbody>
                ${prospects.map(p => {
                  const reasons = p.site_quality_reasons || [];
                  const reasonsLabel = reasons.length
                    ? reasons.slice(0, 2).join(' · ') + (reasons.length > 2 ? '…' : '')
                    : (p.site_quality === 'ok' ? 'site correct' : '—');
                  return `
                  <tr class="border-t border-border">
                    <td class="px-3 py-2 font-medium truncate max-w-[260px]"
                        title="${this._esc(p.nom)}">${this._esc(p.nom)}</td>
                    <td class="px-3 py-2 ${p.email ? '' : 'text-text-muted italic'}">
                      ${p.email ? this._esc(p.email) : '—'}
                    </td>
                    <td class="px-3 py-2 text-text-secondary">
                      ${this._esc(p.ville)} ${p.code_postal ? `(${this._esc(p.code_postal)})` : ''}
                    </td>
                    <td class="px-3 py-2">
                      ${p.site_web ? `<a href="${this._esc(p.site_web)}" target="_blank" rel="noopener"
                                       class="text-accent hover:underline truncate inline-block max-w-[180px]">${this._esc(this._shortDomain(p.site_web))}</a>` : '<span class="text-text-muted">—</span>'}
                    </td>
                    ${showQualityCol ? `
                      <td class="px-3 py-2 text-[11px]"
                          title="${this._esc(reasons.join(' · '))}">
                        <span class="inline-block px-2 py-0.5 rounded
                                     bg-warning/10 text-warning-text font-semibold">${this._esc(reasonsLabel)}</span>
                      </td>` : ''}
                  </tr>
                `;}).join('')}
              </tbody>
            </table>
          </div>
        </div>
      ` : (isRunning ? `
        <div class="card p-10 text-center text-text-muted">
          <div class="text-base">${this._esc(h.log_tail?.[h.log_tail.length - 1] || 'Chasse en cours…')}</div>
        </div>
      ` : '')}

      ${h.log_tail && h.log_tail.length ? `
        <details id="ch-log-details" class="mt-4 text-xs text-text-muted" ${logOpen ? 'open' : ''}>
          <summary class="cursor-pointer hover:text-text-secondary">Journal de la chasse</summary>
          <pre class="mt-2 p-3 bg-bg rounded-lg overflow-x-auto text-[11px]
                      whitespace-pre-wrap leading-relaxed">${this._esc(h.log_tail.join('\n'))}</pre>
        </details>
      ` : ''}
    `;

    // Restaure la position de lecture dans le tableau après le re-render
    const tableEl = document.getElementById('ch-table-scroll');
    if (tableEl && tableScroll) tableEl.scrollTop = tableScroll;

    const exportBtn = document.getElementById('ch-export');
    if (exportBtn) exportBtn.onclick = () => this._exportCsv();
    const pushBtn = document.getElementById('ch-push');
    if (pushBtn) pushBtn.onclick = () => this._pushToAutopilot();
    const delBtn = document.getElementById('ch-delete');
    if (delBtn) delBtn.onclick = () => this._deleteHunt();
  },

  _statCell(label, value, tone) {
    const color = tone === 'success' ? 'text-success-text'
      : tone === 'warning' ? 'text-warning-text'
      : 'text-text';
    return `
      <div class="rounded-lg bg-bg p-2.5">
        <div class="text-[11px] uppercase tracking-wide text-text-muted">${label}</div>
        <div class="text-lg font-bold ${color}">${value}</div>
      </div>
    `;
  },

  /**
   * Stepper visuel — 3 phases du pipeline :
   *   1. Recherche des entreprises (data.gouv)
   *   2. Analyse des sites + extraction des mails
   *   3. Terminé
   * Selon le status et le mode, on met en évidence l'étape en cours.
   */
  _renderStepper(h, mode, candidats, traites) {
    const status = h.status;
    const isError = status === 'error';
    const isDone = status === 'done';

    // Détermine l'index de l'étape courante (0/1/2)
    let activeIdx = 0;
    if (status === 'searching' || status === 'pending') activeIdx = 0;
    else if (status === 'enriching') activeIdx = 1;
    else if (isDone) activeIdx = 2;

    const steps = [
      {label: 'Recherche entreprises', sub: 'Base data.gouv'},
      {label: 'Analyse des sites', sub: mode === 'poor_sites' ? 'Mails + qualité' : 'Mails publics'},
      {label: 'Terminé', sub: isDone ? 'Prospects prêts à envoyer' : 'En attente'},
    ];

    return `
      <div class="ch-stepper mb-4">
        ${steps.map((s, i) => {
          const done = i < activeIdx || (isDone && i <= activeIdx);
          const active = i === activeIdx && !isDone && !isError;
          const cls = isError
            ? 'ch-step-pending'
            : done ? 'ch-step-done'
            : active ? 'ch-step-active'
            : 'ch-step-pending';
          const icon = done
            ? `<svg class="w-3 h-3" fill="none" stroke="currentColor" stroke-width="3" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg>`
            : active
            ? `<span class="ch-step-dot"></span>`
            : `<span class="ch-step-num">${i + 1}</span>`;
          return `
            <div class="ch-step ${cls}">
              <div class="ch-step-bullet">${icon}</div>
              <div class="ch-step-text">
                <div class="ch-step-label">${s.label}</div>
                <div class="ch-step-sub">${s.sub}</div>
              </div>
              ${i < steps.length - 1 ? `<div class="ch-step-link ${done ? 'ch-step-link-done' : ''}"></div>` : ''}
            </div>
          `;
        }).join('')}
      </div>
    `;
  },

  /**
   * Phrase courte d'état pour la zone de progression : décrit ce que la
   * machine fait à l'instant t, avec compteurs vivants quand on les a.
   */
  _currentStepLabel(h, mode, candidats, traites) {
    const status = h.status;
    if (status === 'pending') return 'En attente du démarrage…';
    if (status === 'searching') {
      return candidats
        ? `Recherche des entreprises… ${candidats} trouvées`
        : 'Recherche des entreprises dans la base data.gouv…';
    }
    if (status === 'enriching') {
      if (candidats) {
        return `Analyse des sites — ${traites} / ${candidats}`;
      }
      return 'Analyse des sites et extraction des mails…';
    }
    return 'Travail en cours…';
  },

  async _pushToAutopilot() {
    if (!this.state.currentId) return;
    const h = this.state.currentHunt;
    const withMail = (h?.stats?.avec_mail) || 0;
    if (!withMail) {
      this._toast('Aucun prospect avec mail à envoyer.', 'warn');
      return;
    }
    const ok = await Dialog.confirm(
      `Ajouter ${withMail} prospect${withMail > 1 ? 's' : ''} dans ta base ` +
      `« Tous les prospects » ? L’Auto-pilote les prendra au prochain passage pour ` +
      `rédiger et envoyer les mails. Les fiches identiques fusionnent, pas de doublon.`,
      {title: 'Ajouter à ta base de prospects', okLabel: 'Ajouter', cancelLabel: 'Annuler'}
    );
    if (!ok) return;
    const btn = document.getElementById('ch-push');
    if (btn) { btn.disabled = true; btn.textContent = 'Envoi…'; }
    const r = await this._api('push_to_autopilot', {hunt_id: this.state.currentId});
    if (btn) btn.disabled = false;
    if (!r || !r.ok) {
      if (r && r.error) console.warn('chasseur.push_to_autopilot', r.error);
      this._toast((r && r.error) || 'Envoi impossible. Réessaie dans un instant.', 'danger');
      // Redraw pour réafficher le bouton normal
      this._renderDetail();
      return;
    }
    // Mémorise le versement pour afficher « ✓ Déjà envoyé » sur cette chasse
    this._markPushed(this.state.currentId);
    const where = r.backend === 'remote'
      ? 'la base commune « Tous les prospects »'
      : 'la base locale (mode hors-ligne)';
    const pushed = r.pushed || 0;
    const q = r.quality || null;
    const dropped = q ? Math.max(0, (q.total || 0) - (q.kept || 0)) : 0;
    this._toast(
      `${pushed} prospect${pushed > 1 ? 's' : ''} envoyé${pushed > 1 ? 's' : ''} vers ${where} — ` +
      `${r.created || 0} ${(r.created || 0) > 1 ? 'nouveaux' : 'nouveau'}, ` +
      `${r.merged || 0} fusionné${(r.merged || 0) > 1 ? 's' : ''}` +
      (dropped ? ` (${dropped} fiche${dropped > 1 ? 's' : ''} écartée${dropped > 1 ? 's' : ''} par le contrôle qualité)` : '') +
      `.`,
      'success'
    );
    this._renderDetail();
  },

  // ---- Mémoire front « cette chasse a déjà été versée » ----
  _LS_PUSHED: 'chasseur:pushed',

  _pushedMap() {
    try { return JSON.parse(localStorage.getItem(this._LS_PUSHED) || '{}') || {}; }
    catch (e) { return {}; }
  },

  // Renvoie null si jamais versée, sinon {when: 'date lisible' | ''}
  _pushedAt(huntId) {
    if (!huntId) return null;
    const iso = this._pushedMap()[huntId];
    if (!iso) return null;
    return {when: this._fmtDate(iso)};
  },

  _markPushed(huntId) {
    if (!huntId) return;
    try {
      const map = this._pushedMap();
      map[huntId] = new Date().toISOString();
      // On borne la mémoire aux 60 versements les plus récents
      const ids = Object.keys(map);
      if (ids.length > 60) {
        ids.sort((a, b) => String(map[a]).localeCompare(String(map[b])));
        ids.slice(0, ids.length - 60).forEach(k => { delete map[k]; });
      }
      localStorage.setItem(this._LS_PUSHED, JSON.stringify(map));
    } catch (e) {}
  },

  /**
   * Export CSV fabriqué CÔTÉ NAVIGATEUR à partir des prospects déjà chargés :
   * le fichier arrive directement dans les Téléchargements. (Avant, il était
   * écrit sur le serveur et restait irrécupérable depuis le site.)
   * Format : séparateur point-virgule + BOM UTF-8 → s'ouvre proprement dans Excel.
   */
  _exportCsv() {
    const h = this.state.currentHunt;
    const prospects = (h && h.prospects) || [];
    if (!prospects.length) {
      this._toast('Aucun prospect à exporter pour cette chasse.', 'warn');
      return;
    }

    const hasPhone = prospects.some(p => String(p.telephone || '').trim());
    const headers = ['Entreprise', 'Email'];
    if (hasPhone) headers.push('Téléphone');
    headers.push('Ville', 'Site', 'État du site');

    // Une valeur qui contient ; " ou un saut de ligne est mise entre guillemets
    const cell = (v) => {
      const s = String(v == null ? '' : v);
      return /[";\n\r]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
    };

    const lines = [headers.map(cell).join(';')];
    prospects.forEach(p => {
      const reasons = p.site_quality_reasons || [];
      const etatSite = reasons.length
        ? reasons.join(' · ')
        : (p.site_quality === 'ok' ? 'site correct' : (p.site_quality || ''));
      const row = [p.nom || '', p.email || ''];
      if (hasPhone) row.push(p.telephone || '');
      row.push(p.ville || '', p.site_web || '', etatSite);
      lines.push(row.map(cell).join(';'));
    });

    // Nom de fichier : chasse-<secteur>-<date>
    const sectorRaw = (h.filters && h.filters.sector_input) || h.label || 'prospects';
    const d0 = new Date(h.created_at || Date.now());
    const d = isNaN(d0.getTime()) ? new Date() : d0;
    const pad = (n) => String(n).padStart(2, '0');
    const dateStr = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
    const fname = `chasse-${this._slugify(sectorRaw)}-${dateStr}.csv`;

    // BOM UTF-8 en tête pour qu'Excel reconnaisse les accents
    const bom = String.fromCharCode(0xFEFF);
    const blob = new Blob([bom + lines.join('\r\n')], {type: 'text/csv;charset=utf-8'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = fname;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 4000);

    const n = prospects.length;
    this._toast(`CSV téléchargé — ${n} ligne${n > 1 ? 's' : ''}. Fichier : ${fname}`, 'success');
  },

  // « Boulangerie — 35 » → « boulangerie-35 » (pour les noms de fichiers)
  _slugify(s) {
    // NFD sépare les accents (é → e + accent), puis on retire les accents
    // (plage Unicode 0x0300-0x036F) avant de ne garder que lettres/chiffres.
    const accents = new RegExp('[' + String.fromCharCode(0x0300) + '-' + String.fromCharCode(0x036F) + ']', 'g');
    return String(s || '')
      .normalize('NFD').replace(accents, '')
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '')
      .slice(0, 40) || 'prospects';
  },

  async _deleteHunt() {
    if (!this.state.currentId) return;
    await this._deleteHuntById(this.state.currentId);
  },

  // ---- Helpers ----
  _esc(s) {
    if (s == null) return '';
    return String(s).replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
  },

  _shortDomain(url) {
    try {
      const u = new URL(url);
      return u.hostname.replace(/^www\./, '');
    } catch (e) { return url; }
  },

  _fmtDate(iso) {
    if (!iso) return '';
    try {
      const d = new Date(iso);
      return d.toLocaleString('fr-FR', {
        day: '2-digit', month: 'short',
        hour: '2-digit', minute: '2-digit',
      });
    } catch (e) { return iso; }
  },

  _toast(msg, tone) {
    // Relais vers le système commun de petits messages (Toast global).
    // Tons acceptés ici : 'success' | 'danger' (→ erreur) | 'warn' | 'info'.
    const type = tone === 'danger' ? 'error'
      : (tone === 'success' || tone === 'warn' || tone === 'info') ? tone
      : 'info';
    if (typeof Toast !== 'undefined' && Toast.show) {
      Toast.show(msg, {type});
    } else {
      console.log('[Chasseur]', type, msg);
    }
  },
};
