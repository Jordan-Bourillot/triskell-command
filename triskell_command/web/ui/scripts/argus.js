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
          <aside id="argus-form" class="space-y-5 rounded-2xl border border-white/5 bg-card-soft p-5">
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
                <button id="argus-all" type="button" class="text-xs px-2 py-1 rounded bg-white/5 hover:bg-white/10">Tout</button>
                <button id="argus-none" type="button" class="text-xs px-2 py-1 rounded bg-white/5 hover:bg-white/10">Aucun</button>
              </div>
            </div>

            <div>
              <label for="argus-query" class="block text-xs font-semibold tracking-wider uppercase opacity-70 mb-1">
                Secteur / mot-clé
              </label>
              <input id="argus-query" type="text"
                     class="w-full px-3 py-2 rounded-lg bg-white/5 border border-white/10 focus:border-white/30 outline-none text-sm"
                     placeholder="plombier, boulangerie, agence immobilière…">
            </div>

            <div>
              <label for="argus-location" class="block text-xs font-semibold tracking-wider uppercase opacity-70 mb-1">
                Ville ou département
              </label>
              <input id="argus-location" type="text"
                     class="w-full px-3 py-2 rounded-lg bg-white/5 border border-white/10 focus:border-white/30 outline-none text-sm"
                     placeholder="Lyon, 75, Bordeaux…">
            </div>

            <div>
              <label for="argus-max" class="block text-xs font-semibold tracking-wider uppercase opacity-70 mb-1">
                Plafond d'emails par source
              </label>
              <input id="argus-max" type="number" min="1" max="5000" value="200"
                     class="w-full px-3 py-2 rounded-lg bg-white/5 border border-white/10 focus:border-white/30 outline-none text-sm">
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
                        class="w-full px-3 py-2 rounded-lg bg-white/5 border border-white/10 focus:border-white/30 outline-none text-sm font-mono"></textarea>
            </div>

            <div>
              <label class="block text-xs font-semibold tracking-wider uppercase opacity-70 mb-1">
                Fichier Excel précédent (emails à exclure)
              </label>
              <input id="argus-ref-file" type="file" accept=".xlsx"
                     class="text-xs file:mr-2 file:px-2 file:py-1 file:rounded file:border-0 file:bg-white/10 file:cursor-pointer">
              <div id="argus-ref-count" class="text-xs opacity-60 mt-1"></div>
            </div>

            <div class="flex flex-wrap gap-2 pt-2">
              <button id="argus-btn-start" class="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium">
                ▶ Lancer
              </button>
              <button id="argus-btn-pause" class="px-4 py-2 rounded-lg bg-white/10 hover:bg-white/15 text-sm font-medium" disabled>
                ⏸ Pause
              </button>
              <button id="argus-btn-stop" class="px-4 py-2 rounded-lg bg-red-700/80 hover:bg-red-600 text-white text-sm font-medium" disabled>
                ⏹ Stop
              </button>
            </div>

            <button id="argus-btn-export" class="w-full px-4 py-2 rounded-lg bg-amber-600 hover:bg-amber-500 text-white text-sm font-medium" disabled>
              ⬇ Télécharger Excel
            </button>

            <button id="argus-btn-push" class="w-full px-4 py-2 rounded-lg bg-fuchsia-600 hover:bg-fuchsia-500 text-white text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed" disabled>
              📥 Envoyer dans le fichier prospect
            </button>
            <p id="argus-push-feedback" class="text-[11px] leading-relaxed hidden"></p>

            <p class="text-[11px] opacity-50 leading-relaxed">
              Tous les mails affichés sont extraits du HTML de pages réellement
              visitées. Aucune adresse n'est devinée.
            </p>
          </aside>

          <!-- Colonne droite : progression + journal -->
          <div class="space-y-5 min-w-0">
            <div class="rounded-2xl border border-white/5 bg-card-soft p-5">
              <div class="flex items-center justify-between mb-4">
                <h2 class="text-sm font-semibold tracking-wide uppercase opacity-80">
                  Progression par source
                </h2>
                <div id="argus-counter" class="text-sm font-medium px-3 py-1 rounded-full bg-white/5">
                  <span id="argus-total">0</span> email(s) trouvé(s)
                </div>
              </div>
              <div id="argus-sources" class="space-y-2 text-sm">
                <div class="opacity-50 italic">Aucun scraping en cours.</div>
              </div>
            </div>

            <div class="rounded-2xl border border-white/5 bg-card-soft p-5">
              <h2 class="text-sm font-semibold tracking-wide uppercase opacity-80 mb-3">
                Journal d'activité
              </h2>
              <div id="argus-journal" class="bg-black/40 rounded-lg p-3 font-mono text-xs overflow-y-auto max-h-[420px] min-h-[200px] space-y-0.5">
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

    // Affiche l'état actuel + démarre le polling si un run tourne déjà.
    await this._refreshStatus();
    this._startPolling();
  },

  // ---- Actions ----

  async _start() {
    const sources = [...document.querySelectorAll('.argus-source:checked')].map(c => c.value);
    if (sources.length === 0) {
      alert('Sélectionne au moins une source.');
      return;
    }
    const payload = {
      sources,
      query: document.getElementById('argus-query').value,
      location: document.getElementById('argus-location').value,
      max_emails: parseInt(document.getElementById('argus-max').value || '200', 10),
      include_personal: document.getElementById('argus-include-personal').checked,
      test_mode: document.getElementById('argus-test-mode').checked,
      seed_urls: document.getElementById('argus-seed-urls').value || '',
    };

    // On vide l'affichage avant le run.
    document.getElementById('argus-sources').innerHTML =
      '<div class="opacity-50 italic">Démarrage…</div>';
    document.getElementById('argus-journal').innerHTML = '';
    document.getElementById('argus-total').textContent = '0';

    const res = await this._api('start', payload);
    if (!res || !res.ok) {
      alert('Impossible de démarrer : ' + (res?.error || 'erreur inconnue'));
      return;
    }
    this._setControls({ running: true, paused: false });
    this._startPolling();
  },

  async _togglePause() {
    const btn = document.getElementById('argus-btn-pause');
    const isPaused = btn.textContent.includes('Reprendre');
    const res = await this._api(isPaused ? 'resume' : 'pause');
    if (!res || !res.ok) return;
    btn.textContent = isPaused ? '⏸ Pause' : '▶ Reprendre';
  },

  async _stop() {
    if (!confirm('Arrêter le scraping en cours ?')) return;
    await this._api('stop');
  },

  async _export() {
    const res = await this._api('download_xlsx');
    if (!res || !res.ok) {
      alert('Export impossible : ' + (res?.error || 'rien à exporter'));
      return;
    }
    // Décode le base64 et déclenche un download navigateur.
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
    } catch (e) {
      alert('Erreur de téléchargement : ' + e.message);
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
      alert('Aucun email à envoyer.');
      return;
    }
    const msg =
      'Envoyer ' + total + ' email(s) collecté(s) par Argus dans le ' +
      'fichier prospect ?\n\n' +
      'Les emails déjà connus seront fusionnés (pas de doublons), ' +
      'les nouveaux seront créés avec le tag "argus".\n\n' +
      'Continuer ?';
    if (!confirm(msg)) return;

    const btn = document.getElementById('argus-btn-push');
    const feedback = document.getElementById('argus-push-feedback');
    if (btn) {
      btn.disabled = true;
      btn.textContent = '⏳ Envoi en cours…';
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
      btn.textContent = '📥 Envoyer dans le fichier prospect';
    }

    if (!res || !res.ok) {
      const err = res?.error || 'erreur inconnue';
      if (feedback) {
        feedback.classList.remove('hidden');
        feedback.className = 'text-[11px] leading-relaxed text-red-400';
        feedback.textContent = '❌ Envoi échoué : ' + err;
      } else {
        alert('Envoi échoué : ' + err);
      }
      return;
    }

    const created = res.created || 0;
    const merged = res.merged || 0;
    const skipped = res.skipped || 0;
    const pushed = res.pushed || 0;
    const parts = [];
    parts.push('✅ ' + pushed + ' email(s) envoyé(s)');
    parts.push(created + ' nouveau(x), ' + merged + ' déjà connu(s)');
    if (skipped > 0) parts.push(skipped + ' ignoré(s) (format invalide)');
    if (res.backend === 'local') parts.push('(stockage local, pas en ligne)');

    if (feedback) {
      feedback.classList.remove('hidden');
      feedback.className = 'text-[11px] leading-relaxed text-emerald-400';
      feedback.textContent = parts.join(' · ');
    } else {
      alert(parts.join('\n'));
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
        document.getElementById('argus-ref-count').textContent =
          `${res.count} email(s) exclus du prochain run.`;
      } else {
        alert('Lecture impossible : ' + (res?.error || ''));
      }
    } catch (e) {
      alert('Erreur upload : ' + e.message);
    }
  },

  // ---- Polling de l'état ----

  _startPolling() {
    if (this.state.statusPollTimer) clearInterval(this.state.statusPollTimer);
    this.state.statusPollTimer = setInterval(() => this._refreshStatus(), 2000);
  },

  _stopPolling() {
    if (this.state.statusPollTimer) {
      clearInterval(this.state.statusPollTimer);
      this.state.statusPollTimer = null;
    }
  },

  async _refreshStatus() {
    // Si la vue a changé entre-temps, on arrête.
    if (App.currentView !== 'argus') {
      this._stopPolling();
      return;
    }
    const s = await this._api('status', { log_tail: 200 });
    if (!s || !s.ok) return;

    document.getElementById('argus-total').textContent = s.total_emails || 0;
    this._lastTotalEmails = s.total_emails || 0;

    // Sources
    const sourcesEl = document.getElementById('argus-sources');
    if (sourcesEl) {
      const names = Object.keys(s.sources || {});
      if (names.length === 0) {
        sourcesEl.innerHTML =
          '<div class="opacity-50 italic">Aucun scraping en cours.</div>';
      } else {
        sourcesEl.innerHTML = names.map(name => this._renderSource(name, s.sources[name], s.params)).join('');
      }
    }

    // Journal
    const journalEl = document.getElementById('argus-journal');
    if (journalEl && Array.isArray(s.logs)) {
      const wasAtBottom =
        journalEl.scrollHeight - journalEl.scrollTop - journalEl.clientHeight < 50;
      journalEl.innerHTML = s.logs.map(l => this._renderLog(l)).join('');
      if (wasAtBottom) journalEl.scrollTop = journalEl.scrollHeight;
    }

    // Contrôles boutons
    this._setControls({
      running: !!s.is_running,
      paused: !!s.is_paused,
      hasEmails: (s.total_emails || 0) > 0,
    });

    // Quand le run se termine, on arrête le polling (on garde un dernier ping
    // d'aimable courtoisie au cas où).
    if (!s.is_running) {
      // Garde le polling actif jusqu'à 5s après la fin, le temps que l'UI
      // soit cohérente.
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
      pending: 'bg-white/10 text-white/70',
      running: 'bg-sky-500/20 text-sky-300',
      done:    'bg-emerald-500/20 text-emerald-300',
      error:   'bg-red-500/20 text-red-300',
      stopped: 'bg-amber-500/20 text-amber-300',
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
      <div class="rounded-lg border border-white/5 p-3">
        <div class="flex items-center justify-between gap-2 mb-1">
          <span class="font-medium">${labels[name] || name}</span>
          <span class="text-[10px] font-bold tracking-widest px-2 py-0.5 rounded ${colorClass}">${label}</span>
        </div>
        <div class="text-xs opacity-70 flex flex-wrap gap-x-3">
          <span>📄 ${sp.visited_pages || 0} pages</span>
          <span>📧 ${sp.found || 0} emails</span>
          ${sp.message ? `<span class="opacity-80 italic">— ${this._escape(sp.message)}</span>` : ''}
        </div>
        <div class="h-1 mt-2 bg-white/5 rounded-full overflow-hidden">
          <div class="h-full bg-gradient-to-r from-sky-500 to-blue-500" style="width:${pct}%"></div>
        </div>
      </div>
    `;
  },

  _renderLog(l) {
    const levelClass = {
      info: 'text-white/80',
      warn: 'text-amber-300',
      error: 'text-red-300',
      success: 'text-emerald-300',
    }[l.level] || 'text-white/80';
    const t = this._escape(l.time || '');
    const src = this._escape(l.source || '');
    const msg = this._escape(l.message || '');
    return `<div><span class="text-white/40">[${t}]</span> <span class="text-fuchsia-300">[${src}]</span> <span class="${levelClass}">${msg}</span></div>`;
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
