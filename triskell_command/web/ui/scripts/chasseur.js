/* Le Chasseur — vue de découverte de PME via API officielle data.gouv.
 *
 * Pipeline visible côté UI :
 *   1. L'utilisateur choisit un secteur (preset OU code NAF OU mot-clé) +
 *      une zone (département / code postal / commune) + un volume cible.
 *   2. On lance une chasse en arrière-plan (`chasseur_start_hunt`).
 *   3. On poll l'état du job (`chasseur_get_hunt`) toutes les 2s : progression,
 *      stats, lignes de log.
 *   4. Quand c'est terminé, l'utilisateur peut exporter en CSV importable
 *      directement dans Le Convoi.
 */

const Chasseur = {
  state: {
    presets: [],            // [{id, label, naf}]
    hunts: [],              // index des chasses connues
    currentId: null,        // chasse ouverte (détail à droite)
    currentHunt: null,      // payload complet de la chasse
    pollTimer: null,
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
            extrait les mails publiés sur leur page contact. Tu récupères
            ensuite un fichier prêt à glisser dans <b>Le Convoi</b>.
          </p>
        </header>

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
                    <button type="button" data-mode="all"
                            class="ch-mode-btn ch-mode-active text-xs font-semibold py-2 px-2 rounded-lg border transition-all text-left leading-tight">
                      <div class="font-bold mb-0.5">📬 Large</div>
                      <div class="text-[10px] opacity-80">Tout site avec mail</div>
                    </button>
                    <button type="button" data-mode="poor_sites"
                            class="ch-mode-btn text-xs font-semibold py-2 px-2 rounded-lg border transition-all text-left leading-tight">
                      <div class="font-bold mb-0.5">🎯 Sites pourris</div>
                      <div class="text-[10px] opacity-80">Cibles refonte</div>
                    </button>
                  </div>
                  <input type="hidden" id="ch-mode" value="all" />
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
                  Comptes ~1 à 3 min par tranche de 50 prospects. Tu peux
                  fermer cette fenêtre, ça tourne en fond.
                </p>
              </form>
            </div>

            <div class="card p-4">
              <div class="flex items-center justify-between mb-3">
                <div class="text-[11px] font-bold tracking-widest text-text-muted">
                  CHASSES PASSÉES
                </div>
                <button id="ch-refresh-list" class="text-xs text-accent hover:underline">↻</button>
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
    document.getElementById('ch-refresh-list').onclick = () => this._loadHunts();

    // Bind les 2 boutons de mode (large / sites pourris)
    document.querySelectorAll('[data-mode]').forEach(btn => {
      btn.onclick = () => {
        document.querySelectorAll('[data-mode]').forEach(b => b.classList.remove('ch-mode-active'));
        btn.classList.add('ch-mode-active');
        document.getElementById('ch-mode').value = btn.dataset.mode;
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
      `;
      document.head.appendChild(s);
    }

    await this._loadPresets();
    await this._loadHunts();
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
    if (!r || !r.ok) return;
    this.state.hunts = r.hunts || [];
    this._renderHuntsList();
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
        <button data-hunt-id="${h.id}"
                class="w-full text-left p-2.5 rounded-lg border transition-all
                       ${isActive
                         ? 'border-accent bg-accent/5'
                         : 'border-border hover:border-border-strong hover:bg-surface'}">
          <div class="flex items-center justify-between gap-2 mb-1">
            <div class="text-xs font-semibold truncate flex-1">${this._esc(h.label || 'Sans titre')}</div>
            ${statusBadge}
          </div>
          <div class="text-[10px] text-text-muted">
            ${retenus} retenus · ${withMail} avec mail
          </div>
        </button>
      `;
    }).join('');
    wrap.querySelectorAll('[data-hunt-id]').forEach(btn => {
      btn.onclick = () => this._openHunt(btn.dataset.huntId);
    });
  },

  _statusBadge(status, running) {
    const map = {
      'pending':   {label: 'En file', color: 'bg-text-muted/15 text-text-muted'},
      'searching': {label: 'Cherche', color: 'bg-warning/15 text-warning'},
      'enriching': {label: 'Mails',   color: 'bg-accent/15 text-accent'},
      'done':      {label: 'Fini',    color: 'bg-success/15 text-success'},
      'error':     {label: 'Erreur',  color: 'bg-danger/15 text-danger'},
    };
    const i = map[status] || {label: status || '?', color: 'bg-text-muted/15 text-text-muted'};
    const pulse = running ? 'animate-pulse' : '';
    return `<span class="text-[9px] font-bold px-1.5 py-0.5 rounded ${i.color} ${pulse}">${i.label}</span>`;
  },

  async _launchHunt() {
    const presetId = document.getElementById('ch-preset').value;
    const customSector = document.getElementById('ch-sector-custom').value.trim();
    const dept = document.getElementById('ch-dept').value.trim();
    const cp = document.getElementById('ch-cp').value.trim();
    const target = parseInt(document.getElementById('ch-target').value, 10) || 200;
    const withEmailOnly = document.getElementById('ch-only-email').checked;
    const mode = document.getElementById('ch-mode').value || 'all';

    const sector = customSector || presetId;
    if (!sector && !dept && !cp) {
      this._toast('Choisis au moins un secteur ou une zone.', 'danger');
      return;
    }

    const zone = {};
    if (dept) zone.departement = dept;
    if (cp) zone.code_postal = cp;

    const r = await this._api('start_hunt', {
      sector, zone, target, with_email_only: withEmailOnly, mode,
    });
    if (!r || !r.ok) {
      this._toast((r && r.error) || 'Erreur au lancement de la chasse', 'danger');
      return;
    }
    this._toast('Chasse lancée. Ça tourne en fond.', 'success');
    await this._loadHunts();
    this._openHunt(r.hunt_id);
  },

  async _openHunt(huntId) {
    this.state.currentId = huntId;
    this._renderHuntsList();
    await this._refreshDetail();
    this._startPolling();
  },

  _startPolling() {
    this._stopPolling();
    this.state.pollTimer = setInterval(() => {
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
    const r = await this._api('get_hunt', {hunt_id: this.state.currentId});
    if (!r || !r.ok) return;
    this.state.currentHunt = r.hunt;
    this._renderDetail();
    // Si la chasse est terminée, on stoppe le poll
    if (!r.hunt.running && (r.hunt.status === 'done' || r.hunt.status === 'error')) {
      this._stopPolling();
      // Mise à jour de la liste pour refléter le statut final
      await this._loadHunts();
    }
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

    wrap.innerHTML = `
      <div class="card p-5 mb-4">
        <div class="flex items-start justify-between gap-3 mb-3">
          <div class="min-w-0 flex-1">
            <div class="text-xs text-text-muted mb-1">${this._fmtDate(h.created_at)}</div>
            <h2 class="text-lg font-bold truncate">${this._esc(h.label)}</h2>
          </div>
          <div class="flex items-center gap-2">
            ${this._statusBadge(h.status, isRunning)}
            ${isDone && withMail > 0 ? `
              <button id="ch-push" class="btn btn-primary" title="Envoie tous les prospects à l'Auto-Pilote : il s'occupera d'enrichir + rédiger + envoyer la nuit.">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M5 12l14-7-3 14-4-6-7-1z"/></svg>
                Envoyer à l'Auto-Pilote
              </button>
              <button id="ch-export" class="btn btn-secondary" title="Télécharge un CSV à glisser dans Le Convoi.">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                CSV
              </button>` : ''}
            <button id="ch-delete" class="btn btn-secondary text-xs">Supprimer</button>
          </div>
        </div>

        ${h.error ? `
          <div class="rounded-lg bg-danger/10 border border-danger/30 text-danger
                      text-sm p-3 mb-3">⚠️ ${this._esc(h.error)}</div>` : ''}

        <!-- Barre de progression -->
        <div class="mb-3">
          <div class="flex justify-between text-xs text-text-muted mb-1">
            <span>Progression</span>
            <span>${h.progress || 0}%</span>
          </div>
          <div class="h-2 rounded-full bg-bg overflow-hidden">
            <div class="h-full bg-accent transition-all" style="width: ${h.progress || 0}%"></div>
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
          <div class="overflow-x-auto max-h-[480px] overflow-y-auto">
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
                                     bg-warning/10 text-warning font-semibold">${this._esc(reasonsLabel)}</span>
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
        <details class="mt-4 text-xs text-text-muted">
          <summary class="cursor-pointer hover:text-text-secondary">Journal de la chasse</summary>
          <pre class="mt-2 p-3 bg-bg rounded-lg overflow-x-auto text-[10.5px]
                      whitespace-pre-wrap leading-relaxed">${this._esc(h.log_tail.join('\n'))}</pre>
        </details>
      ` : ''}
    `;

    const exportBtn = document.getElementById('ch-export');
    if (exportBtn) exportBtn.onclick = () => this._exportCsv();
    const pushBtn = document.getElementById('ch-push');
    if (pushBtn) pushBtn.onclick = () => this._pushToAutopilot();
    const delBtn = document.getElementById('ch-delete');
    if (delBtn) delBtn.onclick = () => this._deleteHunt();
  },

  _statCell(label, value, tone) {
    const color = tone === 'success' ? 'text-success' : 'text-text';
    return `
      <div class="rounded-lg bg-bg p-2.5">
        <div class="text-[10px] uppercase tracking-wide text-text-muted">${label}</div>
        <div class="text-lg font-bold ${color}">${value}</div>
      </div>
    `;
  },

  async _pushToAutopilot() {
    if (!this.state.currentId) return;
    const h = this.state.currentHunt;
    const withMail = (h?.stats?.avec_mail) || 0;
    if (!withMail) {
      this._toast('Aucun prospect avec mail à envoyer.', 'danger');
      return;
    }
    const ok = confirm(
      `Envoyer ${withMail} prospect${withMail > 1 ? 's' : ''} à l'Auto-Pilote ?\n\n` +
      `L'Auto-Pilote viendra les ramasser la nuit pour rédiger et envoyer ` +
      `les mails automatiquement. Tu pourras suivre l'avancée dans l'onglet ` +
      `Auto-Pilote.`
    );
    if (!ok) return;
    const btn = document.getElementById('ch-push');
    if (btn) { btn.disabled = true; btn.textContent = 'Envoi…'; }
    const r = await this._api('push_to_autopilot', {hunt_id: this.state.currentId});
    if (btn) btn.disabled = false;
    if (!r || !r.ok) {
      this._toast((r && r.error) || 'Envoi impossible', 'danger');
      // Redraw pour réafficher le bouton normal
      this._renderDetail();
      return;
    }
    const where = r.backend === 'remote'
      ? "la base partagée (Auto-Pilote nocturne)"
      : "la base locale";
    this._toast(
      `${r.pushed} prospects envoyés vers ${where} — ` +
      `${r.created} nouveaux, ${r.merged} fusionnés.`,
      'success'
    );
    this._renderDetail();
  },

  async _exportCsv() {
    if (!this.state.currentId) return;
    const r = await this._api('export_csv', {hunt_id: this.state.currentId});
    if (!r || !r.ok) {
      this._toast((r && r.error) || 'Export impossible', 'danger');
      return;
    }
    this._toast(`CSV exporté — ${r.rows} lignes. Fichier : ${r.path}`, 'success');
    // Tente d'ouvrir le dossier d'export en local (desktop seulement)
    if (App.api && App.api.open_url) {
      try { await App.api.open_url({url: 'file:///' + r.path.replace(/\\/g, '/')}); }
      catch (e) {}
    }
  },

  async _deleteHunt() {
    if (!this.state.currentId) return;
    if (!confirm('Supprimer définitivement cette chasse ?')) return;
    const r = await this._api('delete_hunt', {hunt_id: this.state.currentId});
    if (!r || !r.ok) {
      this._toast('Suppression échouée', 'danger');
      return;
    }
    this.state.currentId = null;
    this.state.currentHunt = null;
    this._stopPolling();
    document.getElementById('ch-detail').innerHTML = `
      <div class="card p-10 text-center text-text-muted">
        <div class="text-5xl mb-3 opacity-70">🏹</div>
        <div class="text-base">Lance une chasse ou ouvre-en une dans la liste.</div>
      </div>
    `;
    await this._loadHunts();
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
    // Réutilise le toast global si dispo, sinon fallback alert
    if (typeof Toast !== 'undefined' && Toast.show) {
      Toast.show(msg, tone || 'info');
    } else {
      console.log('[Chasseur]', tone, msg);
    }
  },
};
