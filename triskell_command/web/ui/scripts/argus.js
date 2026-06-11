/* Argus — vue web pour aspirer des mails d'entreprises françaises.
 *
 * Architecture :
 *   - Colonne gauche : formulaire (sources, mot-clé, ville, options) + boutons
 *   - Colonne droite : progression par source + journal d'activité
 *   - Poll de l'état toutes les 2 secondes pendant un run
 *
 * Backend : voir triskell_command/integrations/argus/ + méthodes argus_*
 * dans web/api.py. Un seul run actif à la fois (état global serveur).
 */

const Argus = {
  state: {
    statusPollTimer: null,
    referenceCount: 0,
    lastPaused: false,
    pollFails: 0,
  },

  _LS_FORM: 'argus:form',

  // ---- Persistance formulaire ----

  _saveForm() {
    try {
      const get = id => document.getElementById(id);
      const checkedSources = [...document.querySelectorAll('.argus-source:checked')]
        .map(c => c.value);
      const f = {
        sources: checkedSources,
        query: get('argus-query')?.value || '',
        location: get('argus-location')?.value || '',
        max_emails: get('argus-max')?.value || '200',
        include_personal: get('argus-include-personal')?.checked || false,
        test_mode: get('argus-test-mode')?.checked || false,
        seed_urls: get('argus-seed-urls')?.value || '',
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
    const set = (id, v) => { const el = document.getElementById(id); if (el != null && v != null) el.value = v; };
    set('argus-query', f.query);
    set('argus-location', f.location);
    set('argus-max', f.max_emails);
    set('argus-seed-urls', f.seed_urls);
    const incl = document.getElementById('argus-include-personal');
    if (incl) incl.checked = !!f.include_personal;
    const test = document.getElementById('argus-test-mode');
    if (test) test.checked = !!f.test_mode;
    if (Array.isArray(f.sources)) {
      document.querySelectorAll('.argus-source').forEach(c => {
        c.checked = f.sources.includes(c.value);
      });
    }
  },

  _bindFormPersist() {
    const root = document.getElementById('argus-form');
    if (!root) return;
    const save = () => this._saveForm();
    root.querySelectorAll('input, textarea, select').forEach(el => {
      el.addEventListener('input', save);
      el.addEventListener('change', save);
    });
  },

  // ---- Helper API ----

  async _api(method, payload) {
    if (!App.api) return null;
    const fn = App.api['argus_' + method];
    if (typeof fn !== 'function') {
      console.warn('argus_' + method + ' indisponible');
      return null;
    }
    try { return await fn(payload || {}); }
    catch (e) { console.warn('argus.' + method, e); return null; }
  },

  // ---- Render principal ----

  async render(container) {
    this._root = container;
    container.innerHTML = `
      <section class="animate-slide-up">
        <div class="mb-6 rounded-2xl border border-warning/30 bg-warning/10 p-4 text-sm leading-relaxed">
          <strong>⏸️ Argus est en pause.</strong>
          Ses sources (Pages Jaunes, Europages, recherche web) bloquent le
          serveur : aux derniers essais, il n'a quasiment rien ramené. Il a
          donc été retiré du menu le temps de le fiabiliser — le
          <strong>Prospecteur Google</strong> et <strong>Le Chasseur</strong>
          font le même travail en mieux. Cet écran reste ouvert pour tes
          essais ponctuels.
        </div>
        <header class="mb-6 sm:mb-8">
          <div class="hero-kicker mb-2" style="color: hsl(var(--accent));">ARGUS</div>
          <h1 class="hero-title hero-title--md mb-2 sm:mb-3">
            Ramène les mails d'entreprises françaises par secteur et ville.
          </h1>
          <p class="hero-subtitle">
            Choisis tes sources, un mot-clé (ex : <em>plombier</em>) et une ville
            (ex : <em>Lyon</em>). Argus parcourt Pages Jaunes, Europages,
            OpenStreetMap et la recherche web, puis visite les pages Contact
            des sites trouvés pour récolter les emails publics. Aucun email
            n'est inventé.
          </p>
        </header>

        <div class="grid gap-6 lg:grid-cols-[360px_1fr]">

          <!-- Colonne gauche : formulaire -->
          <aside id="argus-form" class="space-y-5 card p-5">
            <div>
              <label class="block text-xs font-semibold tracking-wider uppercase opacity-70 mb-2">
                Sources
              </label>
              <div class="grid gap-1.5">
                <label class="flex items-center gap-2 text-sm cursor-pointer">
                  <input type="checkbox" class="argus-source" value="pagesjaunes" checked>
                  Pages Jaunes
                </label>
                <label class="flex items-center gap-2 text-sm cursor-pointer">
                  <input type="checkbox" class="argus-source" value="europages" checked>
                  Europages
                </label>
                <label class="flex items-center gap-2 text-sm cursor-pointer">
                  <input type="checkbox" class="argus-source" value="openstreetmap" checked>
                  OpenStreetMap
                </label>
                <label class="flex items-center gap-2 text-sm cursor-pointer">
                  <input type="checkbox" class="argus-source" value="duckduckgo" checked>
                  Recherche web
                </label>
                <label class="flex items-center gap-2 text-sm cursor-pointer">
                  <input type="checkbox" class="argus-source" value="websites" checked>
                  Sites web découverts
                </label>
              </div>
              <div class="flex gap-2 mt-2">
                <button id="argus-all" type="button" class="text-xs px-2 py-1 rounded bg-text/5 hover:bg-text/10">Tout</button>
                <button id="argus-none" type="button" class="text-xs px-2 py-1 rounded bg-text/5 hover:bg-text/10">Aucun</button>
              </div>
            </div>

            <div>
              <label for="argus-query" class="block text-xs font-semibold tracking-wider uppercase opacity-70 mb-1">
                Secteur / mot-clé
              </label>
              <input id="argus-query" type="text"
                     class="w-full px-3 py-2 rounded-lg bg-surface border border-border-strong focus:border-accent outline-none text-sm"
                     placeholder="plombier, boulangerie, agence immobilière…">
            </div>

            <div>
              <label for="argus-location" class="block text-xs font-semibold tracking-wider uppercase opacity-70 mb-1">
                Ville ou département
              </label>
              <input id="argus-location" type="text"
                     class="w-full px-3 py-2 rounded-lg bg-surface border border-border-strong focus:border-accent outline-none text-sm"
                     placeholder="Lyon, 75, Bordeaux…">
            </div>

            <div>
              <label for="argus-max" class="block text-xs font-semibold tracking-wider uppercase opacity-70 mb-1">
                Plafond d'emails par source
              </label>
              <input id="argus-max" type="number" min="1" max="5000" value="200"
                     class="w-full px-3 py-2 rounded-lg bg-surface border border-border-strong focus:border-accent outline-none text-sm">
            </div>

            <div class="space-y-2">
              <label class="flex items-center gap-2 text-sm cursor-pointer">
                <input id="argus-include-personal" type="checkbox">
                <span>Inclure aussi les emails persos (gmail, yahoo…)</span>
              </label>
              <label class="flex items-center gap-2 text-sm cursor-pointer">
                <input id="argus-test-mode" type="checkbox">
                <span>Mode test rapide (10 emails max par source)</span>
              </label>
            </div>

            <div>
              <label for="argus-seed-urls" class="block text-xs font-semibold tracking-wider uppercase opacity-70 mb-1">
                Sites web supplémentaires (un par ligne, optionnel)
              </label>
              <textarea id="argus-seed-urls" rows="3"
                        class="w-full px-3 py-2 rounded-lg bg-surface border border-border-strong focus:border-accent outline-none text-sm font-mono"></textarea>
            </div>

            <div>
              <label for="argus-ref-file" class="block text-xs font-semibold tracking-wider uppercase opacity-70 mb-1">
                Fichier Excel précédent (emails à exclure)
              </label>
              <input id="argus-ref-file" type="file" accept=".xlsx"
                     class="text-xs file:mr-2 file:px-2 file:py-1 file:rounded file:border-0 file:bg-text/10 file:text-text file:cursor-pointer">
              <div id="argus-ref-count" class="text-xs text-text-muted mt-1">Aucune adresse exclue.</div>
            </div>

            <div class="flex flex-wrap gap-2 pt-2">
              <button id="argus-btn-start" class="px-4 py-2 rounded-lg bg-accent-strong hover:bg-[hsl(var(--accent-strong-hover))] text-white text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed">
                ▶ Lancer
              </button>
              <button id="argus-btn-pause" class="px-4 py-2 rounded-lg bg-text/10 hover:bg-text/15 text-text text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed" disabled>
                ⏸ Pause
              </button>
              <button id="argus-btn-stop" class="px-4 py-2 rounded-lg bg-danger/15 hover:bg-danger/25 text-danger-text border border-danger/30 text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed" disabled>
                ⏹ Stop
              </button>
            </div>

            <button id="argus-btn-export" class="w-full px-4 py-2 rounded-lg bg-warning/15 hover:bg-warning/25 text-warning-text border border-warning/30 text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed" disabled>
              ⬇ Télécharger Excel
            </button>

            <button id="argus-btn-push" class="w-full px-4 py-2 rounded-lg bg-accent-strong hover:bg-[hsl(var(--accent-strong-hover))] text-white text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed" disabled>
              📥 Ajouter à mes prospects
            </button>
            <p id="argus-push-feedback" class="text-[11px] leading-relaxed hidden"></p>

            <p class="text-[11px] text-text-muted leading-relaxed">
              Tous les mails affichés sont extraits de pages réellement
              visitées. Aucune adresse n'est devinée.
            </p>
          </aside>

          <!-- Colonne droite : progression + journal -->
          <div class="space-y-5 min-w-0">
            <div class="card p-5">
              <div class="flex items-center justify-between mb-4">
                <h2 class="text-sm font-semibold tracking-wide uppercase opacity-80">
                  Progression par source
                </h2>
                <div id="argus-counter" class="text-sm font-medium px-3 py-1 rounded-full bg-bg">
                  <span id="argus-total">0</span> <span id="argus-total-label">email trouvé</span>
                </div>
              </div>
              <div id="argus-sources" class="space-y-2 text-sm">
                <div class="text-text-muted italic">Aucune collecte en cours.</div>
              </div>
            </div>

            <div class="card p-5">
              <h2 class="text-sm font-semibold tracking-wide uppercase opacity-80 mb-3">
                Journal d'activité
              </h2>
              <div id="argus-journal" class="bg-bg border border-border rounded-lg p-3 font-mono text-xs overflow-y-auto max-h-[420px] min-h-[200px] space-y-0.5">
                <div class="text-text-muted italic">Le journal s'affichera ici pendant la collecte.</div>
              </div>
            </div>
          </div>

        </div>
      </section>
    `;

    // Bindings boutons globaux
    document.getElementById('argus-all').onclick = () => {
      document.querySelectorAll('.argus-source').forEach(c => c.checked = true);
      this._saveForm();
    };
    document.getElementById('argus-none').onclick = () => {
      document.querySelectorAll('.argus-source').forEach(c => c.checked = false);
      this._saveForm();
    };
    document.getElementById('argus-btn-start').onclick = () => this._start();
    document.getElementById('argus-btn-pause').onclick = () => this._togglePause();
    document.getElementById('argus-btn-stop').onclick = () => this._stop();
    document.getElementById('argus-btn-export').onclick = () => this._export();
    document.getElementById('argus-btn-push').onclick = () => this._pushToProspects();
    document.getElementById('argus-ref-file').onchange = (e) => this._uploadReference(e);

    this._applyForm();
    this._bindFormPersist();

    // Le DOM vient d'être recréé : on repart d'un compteur d'exclusions à 0
    // (le vrai compte revient avec le premier statut serveur).
    this.state.referenceCount = 0;
    // L'ancien minuteur a été nettoyé par App au changement de vue :
    // on oublie son identifiant pour que le polling puisse redémarrer.
    this.state.statusPollTimer = null;

    // Affiche l'état actuel ; _refreshStatus relance le polling tout seul
    // si une collecte tourne déjà (et l'arrête sinon).
    await this._refreshStatus();
  },

  // ---- Erreurs serveur (jamais de message technique brut à l'écran) ----

  _serverError(err, fallback) {
    const raw = err == null ? '' : String(err);
    const looksTechnical = !raw || raw.length > 180
      || /traceback|exception|errno|\.py\b|<class /i.test(raw);
    if (looksTechnical) {
      Toast.friendlyError(raw || new Error(fallback), fallback);
      return;
    }
    // Message serveur déjà en français : on le montre, en gommant le jargon.
    Toast.error(raw.replace(/scraping/gi, 'collecte'));
  },

  // ---- Actions ----

  async _start() {
    const sources = [...document.querySelectorAll('.argus-source:checked')].map(c => c.value);
    if (sources.length === 0) {
      Toast.error('Sélectionne au moins une source.');
      return;
    }
    const query = document.getElementById('argus-query').value.trim();
    if (!query) {
      Toast.error('Indique un secteur ou un mot-clé (ex : plombier) avant de lancer.');
      return;
    }
    const payload = {
      sources,
      query,
      location: document.getElementById('argus-location').value,
      max_emails: parseInt(document.getElementById('argus-max').value || '200', 10),
      include_personal: document.getElementById('argus-include-personal').checked,
      test_mode: document.getElementById('argus-test-mode').checked,
      seed_urls: document.getElementById('argus-seed-urls').value || '',
    };

    // Anti double-clic pendant l'appel serveur.
    const startBtn = document.getElementById('argus-btn-start');
    if (startBtn) startBtn.disabled = true;

    // On vide l'affichage avant la collecte.
    document.getElementById('argus-sources').innerHTML =
      '<div class="text-text-muted italic">Démarrage…</div>';
    document.getElementById('argus-journal').innerHTML = '';
    const totalEl = document.getElementById('argus-total');
    if (totalEl) totalEl.textContent = '0';

    const res = await this._api('start', payload);
    if (!res || !res.ok) {
      if (startBtn) startBtn.disabled = false;
      // On remet les zones vidées dans leur état de repos.
      document.getElementById('argus-sources').innerHTML =
        '<div class="text-text-muted italic">Aucune collecte en cours.</div>';
      document.getElementById('argus-journal').innerHTML =
        '<div class="text-text-muted italic">Le journal s’affichera ici pendant la collecte.</div>';
      this._serverError(res && res.error, 'Impossible de démarrer la collecte. Réessaie dans un instant.');
      return;
    }
    Toast.success('Collecte lancée. Ça tourne en fond.');
    this._setControls({ running: true, paused: false });
    this._startPolling();
  },

  async _togglePause() {
    // On se base sur le DERNIER état renvoyé par le serveur,
    // pas sur le texte du bouton (qui peut être désynchronisé).
    const isPaused = !!this.state.lastPaused;
    const res = await this._api(isPaused ? 'resume' : 'pause');
    if (!res || !res.ok) {
      this._serverError(res && res.error, isPaused
        ? 'Impossible de reprendre la collecte.'
        : 'Impossible de mettre la collecte en pause.');
      return;
    }
    this.state.lastPaused = !isPaused;
    const btn = document.getElementById('argus-btn-pause');
    if (btn) btn.textContent = this.state.lastPaused ? '▶ Reprendre' : '⏸ Pause';
    Toast.info(this.state.lastPaused ? 'Collecte mise en pause.' : 'Collecte reprise.');
  },

  async _stop() {
    const ok = await Dialog.confirm(
      'Arrêter la collecte en cours ? Les emails déjà trouvés restent disponibles.',
      { title: 'Arrêter la collecte', okLabel: 'Arrêter', cancelLabel: 'Continuer', danger: true }
    );
    if (!ok) return;
    const res = await this._api('stop');
    if (!res || !res.ok) {
      this._serverError(res && res.error, 'Impossible d’arrêter la collecte. Réessaie dans un instant.');
      return;
    }
    Toast.success('Collecte arrêtée. Les emails trouvés restent disponibles.');
  },

  async _export() {
    const res = await this._api('download_xlsx');
    if (!res || !res.ok) {
      this._serverError(res && res.error, 'Export impossible : rien à exporter pour l’instant.');
      return;
    }
    // Décode le base64 et déclenche un téléchargement navigateur.
    try {
      const bin = atob(res.content_b64);
      const bytes = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
      const blob = new Blob([bytes], {
        type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = res.filename || 'emails.xlsx';
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      Toast.success(`Excel exporté${res.rows ? ` — ${res.rows} ligne${res.rows > 1 ? 's' : ''}` : ''}.`);
    } catch (e) {
      console.warn('argus export:', e);
      Toast.error('Téléchargement bloqué par le navigateur.');
    }
  },

  /**
   * Pousse tous les emails collectés dans la base prospects partagée.
   * Anti-doublon géré côté serveur (upsert sur l'email) : un prospect
   * déjà connu sera enrichi, pas dupliqué.
   */
  async _pushToProspects() {
    const total = this._lastTotalEmails || 0;
    if (total === 0) {
      Toast.warn('Aucun email à ajouter pour l’instant.');
      return;
    }
    const ok = await Dialog.confirm(
      `Ajouter ${total} email${total > 1 ? 's' : ''} trouvé${total > 1 ? 's' : ''} par Argus ` +
      `à « Tous les prospects » ? Les adresses déjà connues seront fusionnées (pas de doublon).`,
      { title: 'Ajouter à mes prospects', okLabel: 'Ajouter', cancelLabel: 'Annuler' }
    );
    if (!ok) return;

    const btn = document.getElementById('argus-btn-push');
    const feedback = document.getElementById('argus-push-feedback');
    if (btn) {
      btn.disabled = true;
      btn.textContent = '⏳ Ajout en cours…';
    }
    if (feedback) {
      feedback.classList.add('hidden');
      feedback.textContent = '';
    }

    let res;
    try {
      res = await this._api('push_to_prospects');
    } catch (e) {
      res = { ok: false, error: String(e) };
    }

    if (btn) {
      btn.disabled = false;
      btn.textContent = '📥 Ajouter à mes prospects';
    }

    if (!res || !res.ok) {
      this._serverError(res && res.error, 'Ajout impossible. Réessaie dans un instant.');
      if (feedback) {
        feedback.classList.remove('hidden');
        feedback.className = 'text-[11px] leading-relaxed text-danger-text';
        feedback.textContent = '❌ Ajout échoué. Détail dans le petit message en haut à droite.';
      }
      return;
    }

    const created = res.created || 0;
    const merged = res.merged || 0;
    const skipped = res.skipped || 0;
    const pushed = res.pushed || 0;
    const parts = [];
    parts.push(`✅ ${pushed} email${pushed > 1 ? 's' : ''} ajouté${pushed > 1 ? 's' : ''}`);
    parts.push(`${created} ${created > 1 ? 'nouveaux' : 'nouveau'}, ${merged} déjà ${merged > 1 ? 'connus' : 'connu'}`);
    if (skipped > 0) parts.push(`${skipped} ignoré${skipped > 1 ? 's' : ''} (format invalide)`);
    if (res.backend === 'local') parts.push('(enregistrés sur cet ordinateur, pas en ligne)');

    Toast.success(parts.join(' · '));
    if (feedback) {
      feedback.classList.remove('hidden');
      feedback.className = 'text-[11px] leading-relaxed text-success-text';
      feedback.textContent = parts.join(' · ');
    }
  },

  async _uploadReference(ev) {
    const file = ev.target.files?.[0];
    if (!file) return;
    try {
      const buf = await file.arrayBuffer();
      let bin = '';
      const bytes = new Uint8Array(buf);
      for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
      const b64 = btoa(bin);
      const res = await this._api('set_reference', { content_b64: b64 });
      if (res && res.ok) {
        Toast.success(`${res.count} adresse${res.count > 1 ? 's' : ''} à exclure chargée${res.count > 1 ? 's' : ''}.`);
        this._renderRefCount(res.count);
      } else {
        this._serverError(res && res.error, 'Lecture du fichier impossible. Vérifie que c’est bien un fichier Excel (.xlsx).');
      }
    } catch (e) {
      console.warn('argus reference:', e);
      Toast.error('Lecture du fichier impossible. Vérifie que c’est bien un fichier Excel (.xlsx).');
    }
  },

  /* Affiche en permanence l'état des exclusions + bouton pour les retirer. */
  _renderRefCount(count) {
    const el = document.getElementById('argus-ref-count');
    if (!el) return;
    const n = Number(count) || 0;
    this.state.referenceCount = n;
    if (!n) {
      el.textContent = 'Aucune adresse exclue.';
      return;
    }
    el.innerHTML =
      `${n} adresse${n > 1 ? 's' : ''} exclue${n > 1 ? 's' : ''} de la prochaine collecte. ` +
      `<button id="argus-ref-clear" type="button" class="text-accent-text hover:underline">Retirer</button>`;
    const btn = el.querySelector('#argus-ref-clear');
    if (btn) btn.onclick = () => this._clearReference();
  },

  async _clearReference() {
    const res = await this._api('set_reference', { emails: [] });
    if (!res || !res.ok) {
      this._serverError(res && res.error, 'Impossible de retirer la liste d’exclusion.');
      return;
    }
    Toast.success('Liste d’exclusion retirée.');
    const input = document.getElementById('argus-ref-file');
    if (input) input.value = '';
    this._renderRefCount(0);
  },

  // ---- Polling de l'état ----

  _startPolling() {
    this._stopPolling();
    this.state.pollFails = 0;
    // App.viewInterval : nettoyé automatiquement quand on quitte la vue.
    this.state.statusPollTimer = App.viewInterval(() => this._refreshStatus(), 2000);
  },

  _stopPolling() {
    if (this.state.statusPollTimer) {
      clearInterval(this.state.statusPollTimer);
      this.state.statusPollTimer = null;
    }
  },

  async _refreshStatus() {
    // Si la vue a changé entre-temps, on arrête (double sécurité,
    // App.viewInterval nettoie déjà au changement de vue).
    if (App.currentView !== 'argus') {
      this._stopPolling();
      return;
    }
    const s = await this._api('status', { log_tail: 200 });
    if (!s || !s.ok) {
      // 3 échecs d'affilée → on arrête de marteler le serveur et on explique.
      this.state.pollFails = (this.state.pollFails || 0) + 1;
      if (this.state.pollFails >= 3 && this.state.statusPollTimer) {
        this._stopPolling();
        Toast.warn('Le suivi en direct est suspendu : le serveur ne répond plus. Reviens sur cet écran pour réessayer.');
      }
      return;
    }
    this.state.pollFails = 0;

    const totalEl = document.getElementById('argus-total');
    if (!totalEl) return; // la vue n'est plus affichée
    const total = s.total_emails || 0;
    totalEl.textContent = total;
    const totalLabel = document.getElementById('argus-total-label');
    if (totalLabel) totalLabel.textContent = total > 1 ? 'emails trouvés' : 'email trouvé';
    this._lastTotalEmails = total;
    this.state.lastPaused = !!s.is_paused;

    // Exclusions (état permanent, avec bouton « Retirer »)
    if (s.reference_count != null && Number(s.reference_count) !== this.state.referenceCount) {
      this._renderRefCount(s.reference_count);
    }

    // Sources
    const sourcesEl = document.getElementById('argus-sources');
    if (sourcesEl) {
      const names = Object.keys(s.sources || {});
      if (names.length === 0) {
        sourcesEl.innerHTML =
          '<div class="text-text-muted italic">Aucune collecte en cours.</div>';
      } else {
        sourcesEl.innerHTML = names.map(name => this._renderSource(name, s.sources[name], s.params)).join('');
      }
    }

    // Journal
    const journalEl = document.getElementById('argus-journal');
    if (journalEl && Array.isArray(s.logs)) {
      if (s.logs.length === 0) {
        journalEl.innerHTML =
          '<div class="text-text-muted italic">Le journal s’affichera ici pendant la collecte.</div>';
      } else {
        const wasAtBottom =
          journalEl.scrollHeight - journalEl.scrollTop - journalEl.clientHeight < 50;
        journalEl.innerHTML = s.logs.map(l => this._renderLog(l)).join('');
        if (wasAtBottom) journalEl.scrollTop = journalEl.scrollHeight;
      }
    }

    // Contrôles boutons
    this._setControls({
      running: !!s.is_running,
      paused: !!s.is_paused,
      hasEmails: total > 0,
    });

    // Le polling ne tourne que pendant une collecte : démarré si une
    // collecte est active, arrêté dès qu'elle est finie (l'état affiché
    // vient d'être mis à jour une dernière fois juste au-dessus).
    if (s.is_running && !this.state.statusPollTimer) {
      this._startPolling();
    } else if (!s.is_running && this.state.statusPollTimer) {
      this._stopPolling();
    }
  },

  _renderSource(name, sp, params) {
    const labels = {
      pagesjaunes: 'Pages Jaunes',
      europages: 'Europages',
      openstreetmap: 'OpenStreetMap',
      duckduckgo: 'Recherche web',
      websites: 'Sites web',
    };
    const statusColors = {
      pending: 'bg-text-muted/15 text-text-muted',
      running: 'bg-info/15 text-info-text',
      done:    'bg-success/15 text-success-text',
      error:   'bg-danger/15 text-danger-text',
      stopped: 'bg-warning/15 text-warning-text',
    };
    const statusLabel = {
      pending: 'EN ATTENTE',
      running: 'EN COURS',
      done: 'TERMINÉ',
      error: 'ERREUR',
      stopped: 'ARRÊTÉ',
    };
    const max = parseInt((params && params.max_emails) || 200, 10) || 200;
    const pct = Math.min(100, Math.round(((sp.found || 0) / max) * 100));
    const colorClass = statusColors[sp.status] || statusColors.pending;
    const label = statusLabel[sp.status] || sp.status;

    return `
      <div class="rounded-lg border border-border p-3">
        <div class="flex items-center justify-between gap-2 mb-1">
          <span class="font-medium">${labels[name] || name}</span>
          <span class="text-[11px] font-bold tracking-widest px-2 py-0.5 rounded ${colorClass}">${label}</span>
        </div>
        <div class="text-xs text-text-secondary flex flex-wrap gap-x-3">
          <span>📄 ${sp.visited_pages || 0} pages</span>
          <span>📧 ${sp.found || 0} emails</span>
          ${sp.message ? `<span class="text-text-muted italic">— ${this._escape(sp.message)}</span>` : ''}
        </div>
        <div class="h-1 mt-2 bg-bg rounded-full overflow-hidden">
          <div class="h-full bg-accent" style="width:${pct}%"></div>
        </div>
      </div>
    `;
  },

  _renderLog(l) {
    const levelClass = {
      info: 'text-text-secondary',
      warn: 'text-warning-text',
      error: 'text-danger-text',
      success: 'text-success-text',
    }[l.level] || 'text-text-secondary';
    const t = this._escape(l.time || '');
    const src = this._escape(l.source || '');
    const msg = this._escape(l.message || '');
    return `<div><span class="text-text-muted">[${t}]</span> <span class="text-accent-text">[${src}]</span> <span class="${levelClass}">${msg}</span></div>`;
  },

  _setControls({ running, paused, hasEmails }) {
    const start = document.getElementById('argus-btn-start');
    const pause = document.getElementById('argus-btn-pause');
    const stop = document.getElementById('argus-btn-stop');
    const exp = document.getElementById('argus-btn-export');
    const push = document.getElementById('argus-btn-push');
    if (start) start.disabled = !!running;
    if (pause) {
      pause.disabled = !running;
      pause.textContent = paused ? '▶ Reprendre' : '⏸ Pause';
    }
    if (stop) stop.disabled = !running;
    if (exp && hasEmails !== undefined) exp.disabled = !hasEmails;
    if (push && hasEmails !== undefined) push.disabled = !hasEmails;
  },

  _escape(s) {
    const d = document.createElement('div');
    d.textContent = s == null ? '' : String(s);
    return d.innerHTML;
  },
};
