/* Pipelines Activity — surveillance "il a bougé quoi depuis ta dernière visite"
 *
 * Pour chacun des 4 pipelines sites (Lagriffe, RankUs, WoW, Pixel Pros) :
 *   - on appelle App.api.pipelines_activity() toutes les 60 s (et au boot)
 *   - on compare chaque intake.at à la date "dernière visite" stockée en
 *     localStorage sous "pipeline-seen-<prefix>" (ISO 8601)
 *   - on met à jour la pastille rouge dans la sidebar (#nav-<prefix>-badge)
 *   - on expose getCockpitData() pour que le Cockpit affiche un résumé
 *
 * Quand l'utilisateur ouvre la vue d'un pipeline (App.show('pixelpros')),
 * on appelle markSeen('pixelpros') pour remettre le compteur à zéro.
 */

window.PipelinesActivity = {
  POLL_MS: 60_000,
  LIMIT: 20,
  PREFIXES: ['lagriffe', 'rankus', 'wow', 'pixelpros'],

  LABELS: {
    lagriffe:  'Lagriffe',
    rankus:    'RankUs',
    wow:       'WoW',
    pixelpros: 'Pixel Pros',
  },

  // Couleurs par pipeline via les tokens du thème (pas de hex en dur) :
  // elles suivent le mode clair/sombre automatiquement.
  COLORS: {
    lagriffe:  'hsl(var(--accent))',
    rankus:    'hsl(var(--success))',
    wow:       'hsl(var(--info))',
    pixelpros: 'hsl(var(--gold))',
  },

  _state: {},          // { prefix: {recent:[], unseenCount, latestUnseenAt} }
  _pollTimer: null,
  _bootDone: false,

  _seenKey(prefix) { return `pipeline-seen-${prefix}`; },

  _getSeen(prefix) {
    try { return localStorage.getItem(this._seenKey(prefix)) || ''; }
    catch (e) { return ''; }
  },

  _setSeen(prefix, isoOrNow) {
    try {
      const iso = isoOrNow || new Date().toISOString();
      localStorage.setItem(this._seenKey(prefix), iso);
    } catch (e) {}
  },

  // À appeler quand l'utilisateur entre dans une vue pipeline.
  markSeen(prefix) {
    if (!this.PREFIXES.includes(prefix)) return;
    this._setSeen(prefix);
    // Maj immédiate du badge + du panneau Cockpit s'il est visible
    const st = this._state[prefix];
    if (st) { st.unseenCount = 0; st.unseenItems = []; st.latestUnseenAt = ''; }
    this._renderBadge(prefix, 0);
    this._renderCockpitPanelIfMounted();
  },

  // Demande une vérification immédiate (utilisé après un changement
  // côté front qui pourrait générer un nouveau status).
  refresh() { return this.checkAll(); },

  async checkAll() {
    if (!window.App || !App.api || !App.api.pipelines_activity) return;
    let data = null;
    try { data = await App.api.pipelines_activity({ limit: this.LIMIT }); }
    catch (e) { console.warn('pipelines_activity:', e); return; }
    if (!data || !data.ok) return;

    const pipes = data.pipelines || {};

    // Premier passage : si aucune "dernière visite" n'est connue pour
    // un pipeline, on l'initialise à maintenant — on ne veut pas que
    // le tout premier chargement affiche 20 trucs comme "nouveaux".
    if (!this._bootDone) {
      for (const prefix of this.PREFIXES) {
        if (!this._getSeen(prefix)) this._setSeen(prefix);
      }
      this._bootDone = true;
    }

    for (const prefix of this.PREFIXES) {
      const block = pipes[prefix] || {};
      const recent = block.recent || [];
      // Si l'utilisateur a CETTE vue sous les yeux, tout est considéré vu :
      // on rafraîchit la "dernière visite" à chaque poll (avant, le badge
      // se remplissait pendant qu'il regardait l'écran concerné).
      if (window.App && App.currentView === prefix) this._setSeen(prefix);
      const seen = this._getSeen(prefix);
      const unseen = seen ? recent.filter(r => (r.at || '') > seen) : recent.slice();
      this._state[prefix] = {
        recent,
        unseenItems: unseen,
        unseenCount: unseen.length,
        latestUnseenAt: unseen[0] ? (unseen[0].at || '') : '',
      };
      this._renderBadge(prefix, unseen.length);
    }
    this._renderCockpitPanelIfMounted();
  },

  _renderBadge(prefix, count) {
    const badge = document.getElementById(`nav-${prefix}-badge`);
    if (!badge) return;
    if (count > 0) {
      badge.textContent = count > 99 ? '99+' : String(count);
      badge.hidden = false;
    } else {
      badge.hidden = true;
      badge.textContent = '';
    }
  },

  totalUnseen() {
    return this.PREFIXES.reduce((acc, p) => {
      const s = this._state[p];
      return acc + ((s && s.unseenCount) || 0);
    }, 0);
  },

  // Petit format de "il y a X" français
  _relTime(iso) {
    if (!iso) return '';
    const t = new Date(iso).getTime();
    if (Number.isNaN(t)) return '';
    const diff = Math.max(0, Date.now() - t);
    const m = Math.floor(diff / 60_000);
    if (m < 1)   return 'à l’instant';
    if (m < 60)  return `il y a ${m} min`;
    const h = Math.floor(m / 60);
    if (h < 24)  return `il y a ${h} h`;
    const d = Math.floor(h / 24);
    return `il y a ${d} j`;
  },

  _esc(s) {
    if (s == null) return '';
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
                    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  },

  // Statut brut (anglais) → libellé français. Réutilise la table exposée
  // par pipeline_view.js (window.PipelineView.STATUS_LABELS_FR).
  _statusLabel(prefix, status) {
    if (!status) return '';
    if (prefix === 'pixelpros' && status === 'paid') return 'Payé';
    const table = (window.PipelineView && window.PipelineView.STATUS_LABELS_FR) || {};
    return table[status] || status;
  },

  // ---------- Rendu du panneau Cockpit ----------
  renderCockpitPanel(slot) {
    if (!slot) return;
    const blocks = this.PREFIXES
      .map(p => ({ prefix: p, ...(this._state[p] || {}) }))
      .filter(b => (b.unseenCount || 0) > 0)
      // pipeline ayant bougé le plus récemment en haut
      .sort((a, b) => (b.latestUnseenAt || '').localeCompare(a.latestUnseenAt || ''));

    if (blocks.length === 0) { slot.innerHTML = ''; return; }

    const total = this.totalUnseen();
    const headline = total === 1
      ? '1 mouvement dans tes chaînes de fabrication depuis ta dernière visite'
      : `${total} mouvements dans tes chaînes de fabrication depuis ta dernière visite`;

    const blocksHtml = blocks.map(b => {
      const color = this.COLORS[b.prefix] || 'hsl(var(--accent))';
      const label = this.LABELS[b.prefix] || b.prefix;
      const items = (b.unseenItems || []).slice(0, 4).map(it => `
        <li class="cockpit-pa-row">
          <span class="cockpit-pa-dot" style="background:${color}"></span>
          <span class="cockpit-pa-name">${this._esc(it.name)}</span>
          <span class="cockpit-pa-status">${this._esc(this._statusLabel(b.prefix, it.status))}</span>
          <span class="cockpit-pa-when">${this._esc(this._relTime(it.at))}</span>
        </li>
      `).join('');
      const extra = b.unseenCount > 4
        ? `<li class="cockpit-pa-more">+ ${b.unseenCount - 4} autre${b.unseenCount - 4 > 1 ? 's' : ''}</li>`
        : '';
      return `
        <div class="cockpit-pa-block">
          <div class="cockpit-pa-head">
            <span class="cockpit-pa-pill" style="--pa-color:${color}">${label}</span>
            <span class="cockpit-pa-count">${b.unseenCount} mouvement${b.unseenCount > 1 ? 's' : ''}</span>
            <button class="cockpit-pa-open" data-prefix="${b.prefix}">Ouvrir →</button>
          </div>
          <ul class="cockpit-pa-list">${items}${extra}</ul>
        </div>
      `;
    }).join('');

    slot.innerHTML = `
      <div class="cockpit-pa-card">
        <div class="cockpit-pa-card-head">
          <div>
            <div class="cockpit-pa-kicker">CHAÎNES DE FABRICATION</div>
            <h3 class="cockpit-pa-title">${headline}</h3>
          </div>
        </div>
        <div class="cockpit-pa-blocks">${blocksHtml}</div>
      </div>
    `;
    this._injectStyles();
    slot.querySelectorAll('.cockpit-pa-open').forEach(btn => {
      btn.onclick = () => {
        const pfx = btn.dataset.prefix;
        if (window.App && App.show) App.show(pfx);
      };
    });
  },

  _renderCockpitPanelIfMounted() {
    const slot = document.getElementById('m-pipelines-slot');
    if (slot) this.renderCockpitPanel(slot);
  },

  _injectStyles() {
    if (document.getElementById('pa-styles')) return;
    const s = document.createElement('style');
    s.id = 'pa-styles';
    s.textContent = `
      .cockpit-pa-card {
        margin-top: 18px;
        padding: 18px 18px 16px;
        border-radius: 14px;
        background: hsl(var(--surface));
        border: 1px solid hsl(var(--border));
        /* même ombre que .card (main.css) — var(--shadow-soft) n'existe pas */
        box-shadow: 0 1px 2px rgba(15,23,42,0.04), 0 4px 12px rgba(15,23,42,0.04);
      }
      .cockpit-pa-card-head { display:flex; justify-content:space-between; align-items:flex-start; margin-bottom: 10px; gap:12px; flex-wrap:wrap; }
      .cockpit-pa-kicker { font-size: 11px; font-weight: 800; letter-spacing: 1.5px; color: hsl(var(--accent)); margin-bottom: 4px; }
      .cockpit-pa-title { font-size: 17px; font-weight: 700; color: hsl(var(--text)); line-height: 1.3; text-wrap: balance; }
      .cockpit-pa-blocks { display: grid; grid-template-columns: 1fr; gap: 10px; }
      @media (min-width: 900px) { .cockpit-pa-blocks { grid-template-columns: 1fr 1fr; } }
      .cockpit-pa-block { padding: 12px 14px; border-radius: 10px; background: hsl(var(--bg)); border: 1px solid hsl(var(--border)); }
      .cockpit-pa-head { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; flex-wrap: wrap; }
      .cockpit-pa-pill {
        display: inline-flex; align-items: center; padding: 3px 10px; border-radius: 999px;
        background: color-mix(in srgb, var(--pa-color) 18%, transparent);
        color: var(--pa-color); font-size: 11px; font-weight: 800; letter-spacing: 0.5px;
        border: 1px solid color-mix(in srgb, var(--pa-color) 40%, transparent);
      }
      .cockpit-pa-count { font-size: 11px; color: hsl(var(--text-muted)); font-weight: 600; }
      .cockpit-pa-open {
        margin-left: auto; font-size: 11px; font-weight: 700; color: hsl(var(--accent));
        padding: 4px 10px; border-radius: 6px; transition: background 160ms;
      }
      .cockpit-pa-open:hover { background: hsl(var(--accent) / 0.1); }
      .cockpit-pa-list { display: flex; flex-direction: column; gap: 6px; }
      .cockpit-pa-row {
        display: grid; grid-template-columns: 8px 1fr auto auto; gap: 8px;
        align-items: center; font-size: 12.5px; padding: 4px 0;
        border-top: 1px dashed hsl(var(--border));
      }
      .cockpit-pa-row:first-child { border-top: none; }
      .cockpit-pa-dot { width: 8px; height: 8px; border-radius: 50%; }
      .cockpit-pa-name { color: hsl(var(--text)); font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
      .cockpit-pa-status {
        font-size: 11px; font-weight: 700; padding: 2px 7px; border-radius: 999px;
        background: hsl(var(--surface-elevated)); color: hsl(var(--text-muted));
        text-transform: uppercase; letter-spacing: 0.4px;
      }
      .cockpit-pa-when { font-size: 11px; color: hsl(var(--text-muted)); }
      .cockpit-pa-more { font-size: 11px; color: hsl(var(--text-muted)); padding: 4px 0 0; font-style: italic; }
    `;
    document.head.appendChild(s);
  },

  // ---------- Boot ----------
  start() {
    if (this._pollTimer) return;
    const tick = () => this.checkAll();
    // 1er tick après que App.api soit prêt — au plus ~60 tentatives (18 s) :
    // si l'app ne démarre jamais (page de connexion, écran cassé…), on
    // abandonne au lieu de sonder pour toujours.
    let tries = 0;
    const wait = setInterval(() => {
      tries += 1;
      if (window.App && App.api) {
        clearInterval(wait);
        tick();
        this._pollTimer = setInterval(tick, this.POLL_MS);
      } else if (tries >= 60) {
        clearInterval(wait);
      }
    }, 300);
  },
};

document.addEventListener('DOMContentLoaded', () => {
  window.PipelinesActivity.start();
});
