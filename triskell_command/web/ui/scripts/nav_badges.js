/* Pastilles « du nouveau / à traiter » sur les onglets du menu de gauche.
 *
 * Calqué sur pipelines_activity.js (qui gère déjà Lagriffe / RankUs / WoW /
 * Pixel Pros ; Obélisk a la sienne dans obelisk.js). Ici on couvre le RESTE,
 * à partir des compteurs déjà calculés par guide_snapshot :
 *   - Réponses (replies)            → nb de réponses non traitées
 *   - Boîte de réception (inbound)  → idem (les réponses arrivent là)
 *   - Brouillons (drafts)           → nb de brouillons à valider
 *   - Système / Santé (health)      → nb de robots en panne (pastille rouge)
 *   - GEO (geo)                     → un point quand l'auto-pilote a (re)travaillé
 *                                      depuis ta dernière visite
 *
 * Règle : la pastille apparaît quand il y a du neuf, et s'efface dès que tu
 * ouvres l'onglet (clic sur l'entrée de menu, ou si tu es déjà dessus).
 * Mémoire « déjà vu » : localStorage navbadge-seen-<view> (un nombre pour les
 * compteurs, un horodatage pour le point GEO).
 */
(function () {
  function num(x) {
    const n = parseInt(x, 10);
    return Number.isNaN(n) ? 0 : n;
  }

  window.NavBadges = {
    POLL_MS: 30000,

    // view = identifiant data-view de l'onglet ; kind = 'count' | 'alert' | 'dot'
    RULES: [
      { view: 'replies', kind: 'count', get: s => num(s.replies_unhandled) },
      { view: 'inbound', kind: 'count', get: s => num(s.replies_unhandled) },
      { view: 'drafts',  kind: 'count', get: s => num(s.drafts_pending) },
      { view: 'health',  kind: 'alert',
        get: s => num(s.workers && (num(s.workers.warning) + num(s.workers.error))) },
      { view: 'geo',     kind: 'dot',   get: s => s.geo_last_run_at || '' },
    ],

    _last: {},          // { view: signal courant }
    _styled: false,

    _seenKey(v) { return 'navbadge-seen-' + v; },
    _getSeen(v) { try { return localStorage.getItem(this._seenKey(v)) || ''; } catch (e) { return ''; } },
    _setSeen(v, val) { try { localStorage.setItem(this._seenKey(v), String(val)); } catch (e) {} },

    // À appeler quand l'utilisateur ouvre un onglet.
    markSeen(view) {
      const rule = this.RULES.find(r => r.view === view);
      if (!rule) return;
      if (view in this._last) this._setSeen(view, this._last[view]);
      this._renderOne(rule, this._last[view], true);
    },

    _isNew(rule, cur) {
      const seen = this._getSeen(rule.view);
      if (rule.kind === 'dot') {
        const ts = cur || '';
        return !!ts && ts > (seen || '');
      }
      const n = num(cur);
      const seenN = seen === '' ? -1 : parseInt(seen, 10);
      return n > 0 && n > (Number.isNaN(seenN) ? -1 : seenN);
    },

    _badgeEl(view) {
      const id = 'navbadge-' + view;
      let el = document.getElementById(id);
      if (el) return el;
      const btn = document.querySelector('[data-view="' + view + '"]');
      if (!btn) return null;
      el = document.createElement('span');
      el.id = id;
      el.className = 'nav-item-badge';
      el.hidden = true;
      btn.appendChild(el);
      return el;
    },

    _renderOne(rule, cur, forceHide) {
      const el = this._badgeEl(rule.view);
      if (!el) return;
      el.classList.toggle('nb-dot', rule.kind === 'dot');
      el.classList.toggle('nb-alert', rule.kind === 'alert');
      if (!forceHide && this._isNew(rule, cur)) {
        el.textContent = rule.kind === 'dot'
          ? '' : (num(cur) > 99 ? '99+' : String(num(cur)));
        el.hidden = false;
      } else {
        el.hidden = true;
        el.textContent = '';
      }
    },

    async checkAll() {
      if (!window.App || !App.api || !App.api.guide_snapshot) return;
      let snap = null;
      try { snap = await App.api.guide_snapshot(); }
      catch (e) { return; }
      if (!snap || typeof snap !== 'object') return;
      for (const rule of this.RULES) {
        const cur = rule.get(snap);
        this._last[rule.view] = cur;
        // Déjà sur cette vue → considéré vu (le badge ne se remplit pas pendant
        // qu'il la regarde).
        if (window.App && App.currentView === rule.view) this._setSeen(rule.view, cur);
        this._renderOne(rule, cur, false);
      }
    },

    _injectStyles() {
      if (this._styled) return;
      this._styled = true;
      const s = document.createElement('style');
      s.id = 'navbadge-styles';
      // Réutilise .nav-item-badge (main.css) ; deux variantes seulement.
      s.textContent =
        '.nav-item-badge.nb-dot{min-width:9px;width:9px;height:9px;padding:0;}' +
        '.nav-item-badge.nb-alert{background:hsl(var(--danger,0 72% 51%));}';
      document.head.appendChild(s);
    },

    _bindClicks() {
      document.querySelectorAll('[data-view]').forEach(btn => {
        btn.addEventListener('click', () => this.markSeen(btn.dataset.view));
      });
    },

    start() {
      this._injectStyles();
      this._bindClicks();
      let tries = 0;
      const tick = () => this.checkAll();
      const wait = setInterval(() => {
        tries += 1;
        if (window.App && App.api && App.api.guide_snapshot) {
          clearInterval(wait);
          tick();
          setInterval(tick, this.POLL_MS);
        } else if (tries >= 60) {
          clearInterval(wait);
        }
      }, 300);
    },
  };

  document.addEventListener('DOMContentLoaded', () => window.NavBadges.start());
})();
