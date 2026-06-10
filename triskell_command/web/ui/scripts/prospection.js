/* Lancer une prospection — UNE commande pour TOUTE la chaîne.
 *
 * L'écran-chef de la section PROSPECTION : tu choisis une cible, tu
 * cliques Lancer, et la chaîne s'enchaîne toute seule :
 *   1. Cherche   (l'outil adapté part en chasse)
 *   2. Verse     (les trouvailles avec mail entrent dans la base, sans doublon)
 *   3. Rédige/Envoie (l'Auto-pilote prend le relais s'il est allumé)
 *   4. Réponses  (triées automatiquement)
 *
 * Les outils individuels (Obélisk, Chasseur…) restent disponibles pour
 * les usages pointus — cet écran est le chemin court du quotidien.
 */

const Prospection = {
  state: {
    source: 'pme',
    missions: [],
    autopilot: {},
    launching: false,
  },
  _pollTimer: null,

  async render(container) {
    this._root = container;
    container.innerHTML = `
      <section class="animate-slide-up max-w-5xl">
        <header class="mb-6 sm:mb-8">
          <div class="hero-kicker mb-2" style="color: hsl(var(--accent));">PROSPECTION</div>
          <h1 class="hero-title hero-title--md mb-2 sm:mb-3">Lance une prospection complète, en un clic.</h1>
          <p class="hero-subtitle">
            Tu choisis qui démarcher — l'app cherche, range tout dans ta base
            sans doublon, puis l'Auto-pilote écrit et envoie. Tu n'as plus
            qu'à valider les brouillons et lire les réponses.
          </p>
        </header>

        <div id="pr-autopilot-strip" class="mb-5"></div>

        <div class="card p-5 mb-8">
          <div class="text-[10px] font-bold tracking-widest text-text-muted mb-3">1 · QUI VEUX-TU DÉMARCHER ?</div>
          <div class="pr-tiles mb-4" id="pr-tiles">
            ${this._tile('pme', '🏢', 'PME françaises',
                         'Par métier et département (registre officiel)')}
            ${this._tile('local', '📍', 'Commerces locaux',
                         'Par métier et ville (Google Maps)')}
            ${this._tile('createurs', '🎥', 'Créateurs',
                         'Par niche (YouTube, Twitch…)')}
            <button type="button" class="pr-tile pr-tile-ghost" id="pr-tile-liste"
                    title="Tu as déjà un fichier de contacts (PDF, Excel, Word…) ? Le Convoi s'en occupe.">
              <div class="pr-tile-icon">📄</div>
              <div class="pr-tile-title">J'ai déjà une liste</div>
              <div class="pr-tile-sub">PDF, Excel… → Le Convoi</div>
            </button>
          </div>

          <div class="text-[10px] font-bold tracking-widest text-text-muted mb-3">2 · PRÉCISE TA CIBLE</div>
          <form id="pr-form" class="space-y-3">
            <div id="pr-fields"></div>
            <div class="flex items-center gap-3 pt-1">
              <button type="submit" id="pr-launch" class="btn btn-primary">
                🚀 Lancer la prospection
              </button>
              <span class="text-xs text-text-muted">
                La chaîne avance toute seule — tu peux fermer la page.
              </span>
            </div>
          </form>
        </div>

        <div class="section-label">Prospections en cours et récentes</div>
        <div id="pr-missions"><div class="text-center py-10 text-text-muted">Chargement…</div></div>
      </section>
    `;
    this._injectStyles();
    this._bindTiles();
    this._renderFields();
    document.getElementById('pr-form').onsubmit = (e) => {
      e.preventDefault();
      this._launch();
    };
    const listeBtn = document.getElementById('pr-tile-liste');
    if (listeBtn) listeBtn.onclick = () => App.show('convoy');

    await this._refresh();
    this._startPolling();
  },

  _tile(key, icon, title, sub) {
    return `
      <button type="button" class="pr-tile" data-source="${key}">
        <div class="pr-tile-icon">${icon}</div>
        <div class="pr-tile-title">${title}</div>
        <div class="pr-tile-sub">${sub}</div>
      </button>`;
  },

  _bindTiles() {
    document.querySelectorAll('#pr-tiles .pr-tile[data-source]').forEach(t => {
      t.onclick = () => {
        this.state.source = t.dataset.source;
        this._syncTiles();
        this._renderFields();
      };
    });
    this._syncTiles();
  },

  _syncTiles() {
    document.querySelectorAll('#pr-tiles .pr-tile[data-source]').forEach(t => {
      t.classList.toggle('pr-tile-active', t.dataset.source === this.state.source);
    });
  },

  _renderFields() {
    const wrap = document.getElementById('pr-fields');
    if (!wrap) return;
    const s = this.state.source;
    if (s === 'pme') {
      wrap.innerHTML = `
        <div class="grid sm:grid-cols-3 gap-3">
          ${this._input('metier', 'Métier ou code NAF', 'ex : plombier, restaurant, 43.22A')}
          ${this._input('departement', 'Département', 'ex : 71')}
          ${this._input('volume', 'Combien en chercher ?', '100', 'number')}
        </div>
        <label class="flex items-center gap-2 text-sm text-text-secondary cursor-pointer">
          <input type="checkbox" id="pr-f-sites_pourris" class="accent-current" />
          Seulement les boîtes au site vieillot ou absent (cibles refonte)
        </label>`;
    } else if (s === 'local') {
      wrap.innerHTML = `
        <div class="grid sm:grid-cols-3 gap-3">
          ${this._input('metier', 'Métier', 'ex : coiffeur, garage')}
          ${this._input('zone', 'Ville ou zone', 'ex : Chalon-sur-Saône')}
          ${this._input('volume', 'Combien en chercher ?', '60', 'number')}
        </div>
        <label class="flex items-center gap-2 text-sm text-text-secondary cursor-pointer">
          <input type="checkbox" id="pr-f-sans_site" class="accent-current" />
          Seulement ceux qui n'ont PAS de site (cibles création)
        </label>`;
    } else {
      wrap.innerHTML = `
        <div class="grid sm:grid-cols-2 gap-3">
          ${this._input('niche', 'Niche / thème', 'ex : fitness, cuisine, gaming')}
          ${this._input('volume', 'Combien par plateforme ?', '30', 'number')}
        </div>
        <div class="flex flex-wrap items-center gap-4 text-sm text-text-secondary">
          <span class="text-xs text-text-muted">Plateformes :</span>
          ${['youtube', 'twitch', 'dailymotion', 'kick'].map((p, i) => `
            <label class="flex items-center gap-1.5 cursor-pointer">
              <input type="checkbox" class="pr-platform accent-current"
                     value="${p}" ${i === 0 ? 'checked' : ''} />
              ${p.charAt(0).toUpperCase() + p.slice(1)}
            </label>`).join('')}
        </div>`;
    }
  },

  _input(id, label, placeholder, type = 'text') {
    return `
      <label class="block">
        <span class="block text-xs text-text-muted mb-1">${label}</span>
        <input id="pr-f-${id}" type="${type}" placeholder="${placeholder}"
               class="input w-full" ${type === 'number' ? 'min="5" max="500"' : ''} />
      </label>`;
  },

  _val(id) {
    const el = document.getElementById('pr-f-' + id);
    if (!el) return '';
    if (el.type === 'checkbox') return el.checked;
    return (el.value || '').trim();
  },

  async _launch() {
    if (this.state.launching) return;
    const s = this.state.source;
    const params = {};
    if (s === 'pme') {
      params.metier = this._val('metier');
      params.departement = this._val('departement');
      params.volume = parseInt(this._val('volume') || '100', 10);
      params.sites_pourris = this._val('sites_pourris');
      if (!params.metier && !params.departement) {
        return this._toast('Indique au moins un métier ou un département.', 'danger');
      }
    } else if (s === 'local') {
      params.metier = this._val('metier');
      params.zone = this._val('zone');
      params.volume = parseInt(this._val('volume') || '60', 10);
      params.sans_site = this._val('sans_site');
      if (!params.metier || !params.zone) {
        return this._toast('Indique un métier ET une ville.', 'danger');
      }
    } else {
      params.niche = this._val('niche');
      params.volume = parseInt(this._val('volume') || '30', 10);
      params.plateformes = [...document.querySelectorAll('.pr-platform:checked')]
        .map(c => c.value);
      if (!params.niche) return this._toast('Indique une niche.', 'danger');
      if (!params.plateformes.length) {
        return this._toast('Coche au moins une plateforme.', 'danger');
      }
    }
    this.state.launching = true;
    const btn = document.getElementById('pr-launch');
    if (btn) { btn.disabled = true; btn.textContent = 'Lancement…'; }
    let r = null;
    try {
      r = await App.api.prospection_start({ source: s, params });
    } catch (e) { r = { ok: false, error: String(e) }; }
    this.state.launching = false;
    if (btn) { btn.disabled = false; btn.textContent = '🚀 Lancer la prospection'; }
    if (!r || !r.ok) {
      return this._toast((r && r.error) || 'Lancement impossible', 'danger');
    }
    this._toast('Mission lancée — la chaîne avance toute seule.', 'success');
    await this._refresh();
  },

  async _refresh() {
    if (!App.api || typeof App.api.prospection_missions !== 'function') {
      const slot = document.getElementById('pr-missions');
      if (slot) slot.innerHTML = `
        <div class="card p-8 text-center text-text-muted">
          Mode aperçu — lance Triskell Command pour utiliser cet écran.
        </div>`;
      return;
    }
    let r = null;
    try { r = await App.api.prospection_missions({ limit: 12 }); }
    catch (e) { r = null; }
    if (!r || !r.ok) return;
    this.state.missions = r.missions || [];
    this.state.autopilot = r.autopilot || {};
    this._renderAutopilotStrip();
    this._renderMissions();
  },

  _renderAutopilotStrip() {
    const wrap = document.getElementById('pr-autopilot-strip');
    if (!wrap) return;
    const ap = this.state.autopilot || {};
    const on = !!ap.enabled;
    const sendAuto = (ap.send_mode || 'manual') === 'auto';
    wrap.innerHTML = `
      <div class="card p-3.5 flex flex-wrap items-center gap-3 ${on ? '' : 'border-l-4 border-l-warning'}">
        <span class="text-lg">${on ? '🟢' : '⚪'}</span>
        <div class="flex-1 min-w-[220px]">
          <div class="text-sm font-semibold">
            Auto-pilote ${on ? 'allumé' : 'éteint'}
            <span class="text-xs font-normal text-text-muted">
              — ${on
                  ? (sendAuto
                      ? `envoi automatique, max ${ap.daily_cap || '?'} mails/jour`
                      : 'il prépare des brouillons que tu valides')
                  : 'les prospects trouvés attendront dans la base'}
            </span>
          </div>
        </div>
        <button id="pr-ap-toggle" class="btn ${on ? 'btn-secondary' : 'btn-primary'} text-xs">
          ${on ? 'Éteindre' : 'Allumer l’Auto-pilote'}
        </button>
        <button class="btn btn-secondary text-xs" onclick="App.show('autopilot')">Réglages</button>
      </div>`;
    const t = document.getElementById('pr-ap-toggle');
    if (t) t.onclick = () => this._toggleAutopilot(!on);
  },

  async _toggleAutopilot(turnOn) {
    try {
      const r = await App.api.autopilot_get_config();
      if (!r || !r.ok) throw new Error((r && r.error) || 'config illisible');
      const cfg = r.config || {};
      cfg.enabled = !!turnOn;
      const s = await App.api.autopilot_save_config({ config: cfg });
      if (!s || !s.ok) throw new Error((s && s.error) || 'sauvegarde impossible');
      this._toast(turnOn
        ? 'Auto-pilote allumé — il prendra les prospects de la base.'
        : 'Auto-pilote éteint.', 'success');
    } catch (e) {
      this._toast('Impossible de changer l’Auto-pilote : ' + e.message, 'danger');
    }
    await this._refresh();
  },

  _renderMissions() {
    const wrap = document.getElementById('pr-missions');
    if (!wrap) return;
    const missions = this.state.missions || [];
    if (!missions.length) {
      wrap.innerHTML = `
        <div class="card p-8 text-center text-text-muted">
          Aucune prospection lancée pour l'instant.
          Choisis une cible ci-dessus et clique « Lancer ».
        </div>`;
      return;
    }
    wrap.innerHTML = missions.map(m => this._missionCard(m)).join('');
    wrap.querySelectorAll('[data-cancel-id]').forEach(b => {
      b.onclick = async () => {
        if (!confirm('Abandonner le suivi de cette prospection ?')) return;
        await App.api.prospection_mission_cancel({ id: b.dataset.cancelId });
        await this._refresh();
      };
    });
  },

  _missionCard(m) {
    const counts = m.counts || {};
    const status = m.status || '';
    const active = status === 'hunting' || status === 'handing';
    const badge = {
      hunting: ['En chasse…', 'text-accent'],
      handing: ['Versement…', 'text-accent'],
      handed: ['Chaîne lancée ✓', 'text-success'],
      error: ['En erreur', 'text-danger'],
      cancelled: ['Abandonnée', 'text-text-muted'],
    }[status] || [status, 'text-text-muted'];

    const step = (label, state, detail) => {
      const icon = state === 'done' ? '✅' : state === 'active' ? '🔄' :
                   state === 'error' ? '❌' : '◯';
      return `
        <div class="pr-step ${state === 'pending' ? 'opacity-50' : ''}">
          <span class="pr-step-icon">${icon}</span>
          <div>
            <div class="pr-step-label">${label}</div>
            ${detail ? `<div class="pr-step-detail">${detail}</div>` : ''}
          </div>
        </div>`;
    };

    const huntState = status === 'hunting' ? 'active'
      : status === 'error' && !counts.pushed ? 'error' : 'done';
    const huntDetail = status === 'hunting'
      ? `${m.progress || 0}% — ${counts.found || 0} trouvés (${counts.with_email || 0} avec mail)`
      : `${counts.found || 0} trouvés, ${counts.with_email || 0} avec mail`;

    const pushState = status === 'handed' ? 'done'
      : status === 'handing' ? 'active'
      : status === 'error' && counts.found ? 'error' : 'pending';
    const pushDetail = status === 'handed'
      ? (m.source === 'createurs'
          ? 'directement dans la base'
          : `${counts.pushed || 0} versés (${counts.created || 0} nouveaux, ${counts.merged || 0} fusionnés)`)
      : '';

    const ap = m.autopilot || {};
    const apState = status !== 'handed' ? 'pending' : (ap.kicked ? 'done' : 'pending');
    const apDetail = status === 'handed' ? (ap.note || '') : '';

    return `
      <article class="card p-4 mb-3">
        <div class="flex items-start justify-between gap-3 mb-3">
          <div class="min-w-0">
            <div class="text-xs text-text-muted">${this._fmtDate(m.created_at)}</div>
            <div class="font-semibold truncate">${this._esc(m.label || '(sans nom)')}</div>
          </div>
          <div class="flex items-center gap-2 shrink-0">
            <span class="text-xs font-semibold ${badge[1]}">${badge[0]}</span>
            ${active ? `<button class="btn btn-secondary text-xs" data-cancel-id="${this._esc(m.id)}">Abandonner</button>` : ''}
          </div>
        </div>
        ${m.error ? `<div class="text-xs text-danger mb-2">⚠ ${this._esc(m.error)}</div>` : ''}
        <div class="pr-chain">
          ${step('1 · Cherche', huntState, huntDetail)}
          ${step('2 · Verse dans la base', pushState, pushDetail)}
          ${step('3 · Rédige & envoie', apState, apDetail)}
          ${step('4 · Réponses',
                 status === 'handed' ? 'done' : 'pending',
                 status === 'handed' ? 'triées automatiquement (onglet Réponses)' : '')}
        </div>
      </article>`;
  },

  _startPolling() {
    if (this._pollTimer) clearInterval(this._pollTimer);
    this._pollTimer = setInterval(() => {
      if (App.currentView !== 'prospection') {
        clearInterval(this._pollTimer);
        this._pollTimer = null;
        return;
      }
      const hasActive = (this.state.missions || [])
        .some(m => m.status === 'hunting' || m.status === 'handing');
      if (hasActive) this._refresh();
    }, 5000);
  },

  _injectStyles() {
    if (document.getElementById('pr-styles')) return;
    const s = document.createElement('style');
    s.id = 'pr-styles';
    s.textContent = `
      .pr-tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 10px; }
      .pr-tile {
        text-align: left; padding: 14px; border-radius: 12px; cursor: pointer;
        border: 1.5px solid hsl(var(--border)); background: hsl(var(--bg) / .5);
        transition: all 140ms;
      }
      .pr-tile:hover { border-color: hsl(var(--accent) / .5); }
      .pr-tile-active {
        border-color: hsl(var(--accent));
        background: hsl(var(--accent) / .08);
        box-shadow: 0 0 0 1px hsl(var(--accent));
      }
      .pr-tile-ghost { border-style: dashed; opacity: .85; }
      .pr-tile-icon { font-size: 20px; margin-bottom: 6px; }
      .pr-tile-title { font-weight: 700; font-size: 13.5px; }
      .pr-tile-sub { font-size: 11px; color: hsl(var(--text-muted)); margin-top: 2px; }
      .pr-chain { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 8px; }
      .pr-step {
        display: flex; gap: 8px; align-items: flex-start;
        padding: 8px 10px; border-radius: 10px; background: hsl(var(--bg) / .55);
        border: 1px solid hsl(var(--border));
      }
      .pr-step-icon { font-size: 13px; margin-top: 1px; }
      .pr-step-label { font-size: 12px; font-weight: 600; }
      .pr-step-detail { font-size: 11px; color: hsl(var(--text-muted)); margin-top: 1px; }
      .input {
        background: hsl(var(--bg)); border: 1px solid hsl(var(--border-strong));
        border-radius: 9px; padding: 8px 10px; font-size: 13.5px;
        color: hsl(var(--text));
      }
      .input:focus { outline: 2px solid hsl(var(--accent) / .4); }
    `;
    document.head.appendChild(s);
  },

  _fmtDate(iso) {
    try {
      return new Date(iso).toLocaleString('fr-FR',
        { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
    } catch (e) { return iso || ''; }
  },

  _toast(msg, tone) {
    if (typeof App !== 'undefined' && App.toast) return App.toast(msg, tone);
    alert(msg);
  },

  _esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    }[c]));
  },
};
