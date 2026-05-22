/* CatchUp — "Depuis ta dernière visite, voici ce qui s'est passé".
 *
 * Au retour sur l'app après >1 heure d'absence :
 *   - Compte les éléments nouveaux depuis last_visit_at (mails reçus,
 *     paiements arrivés, brouillons IA en attente, prospects intéressés).
 *   - Si au moins 1 nouveauté : affiche une mini-modale discrète en
 *     haut à droite, fermable + cliquable vers la vue concernée.
 *   - Si rien de neuf : silence radio.
 *
 * Stocke last_visit_at en localStorage. Mis à jour à chaque visite.
 *
 * Désactivé en mode Concentration (FocusMode.isOn()).
 */

const CatchUp = {
  STORAGE_KEY: 'tc-last-visit-at',
  THRESHOLD_MS: 60 * 60 * 1000,   // 1h d'absence min pour déclencher
  SHOWN_KEY:    'tc-catchup-shown-for',

  _getLastVisit() {
    try { return parseInt(localStorage.getItem(this.STORAGE_KEY) || '0', 10); }
    catch (e) { return 0; }
  },

  _setLastVisit(ts) {
    try { localStorage.setItem(this.STORAGE_KEY, String(ts)); }
    catch (e) {}
  },

  /** Calcule ce qui est nouveau depuis last_visit_at. Best-effort,
   *  swallow errors si une API n'est pas dispo. */
  async _collectNews(sinceTs) {
    const news = {
      drafts_pending:     0,
      new_mails_received: 0,
      since_human:        this._humanDelta(sinceTs),
    };
    if (!App.api) return news;

    // Mails reçus depuis sinceTs
    try {
      const r = await App.api.mails_list({ kind: 'reply', limit: 100 });
      if (r && r.ok && Array.isArray(r.mails)) {
        news.new_mails_received = r.mails.filter(m => {
          try {
            const t = new Date(m.ts).getTime();
            return t > sinceTs;
          } catch (e) { return false; }
        }).length;
      }
    } catch (e) {}

    // Brouillons à valider
    try {
      const r = await App.api.get_drafts();
      if (r && r.ok && Array.isArray(r.rows)) {
        news.drafts_pending = r.rows.length;
      }
    } catch (e) {}

    return news;
  },

  _humanDelta(sinceTs) {
    const ms = Date.now() - sinceTs;
    const h = Math.floor(ms / 3600_000);
    if (h < 1) return 'depuis moins d\'une heure';
    if (h < 24) return `depuis ${h} h`;
    const d = Math.floor(h / 24);
    if (d === 1) return 'depuis hier';
    if (d < 7) return `depuis ${d} jours`;
    return `depuis plus d'une semaine`;
  },

  /** Affiche la mini-modale flottante "Catch up". */
  _showToast(news) {
    if (document.getElementById('catchup-toast')) return;
    const items = [];
    if (news.new_mails_received > 0) {
      items.push({
        icon: '↙',
        label: `${news.new_mails_received} nouveau${news.new_mails_received > 1 ? 'x' : ''} mail${news.new_mails_received > 1 ? 's' : ''} reçu${news.new_mails_received > 1 ? 's' : ''}`,
        view: 'mails',
      });
    }
    if (news.drafts_pending > 0) {
      items.push({
        icon: '✓',
        label: `${news.drafts_pending} brouillon${news.drafts_pending > 1 ? 's' : ''} à valider`,
        view: 'drafts',
      });
    }
    if (items.length === 0) return;

    const el = document.createElement('div');
    el.id = 'catchup-toast';
    el.style.cssText = `
      position: fixed; top: 16px; right: 16px;
      z-index: 9997;
      max-width: 380px;
      background: hsl(var(--surface));
      border: 1px solid hsl(var(--border));
      border-radius: 14px;
      box-shadow: 0 10px 30px rgba(0,0,0,0.35);
      overflow: hidden;
      animation: catchupSlideIn 280ms cubic-bezier(.2,.9,.3,1.2);
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    `;
    el.innerHTML = `
      <style>
        @keyframes catchupSlideIn { from { opacity: 0; transform: translateY(-12px); } to { opacity: 1; transform: translateY(0); } }
        #catchup-toast .cu-row { cursor: pointer; transition: background 120ms; }
        #catchup-toast .cu-row:hover { background: hsl(var(--accent) / 0.08); }
      </style>
      <div style="padding: 12px 14px 10px; border-bottom: 1px solid hsl(var(--border)); display:flex; align-items:flex-start; gap:8px;">
        <div style="flex:1;">
          <div style="font-size:10px; font-weight:700; letter-spacing:1.5px; color:hsl(var(--accent)); text-transform:uppercase; margin-bottom:2px;">DEPUIS TA DERNIÈRE VISITE</div>
          <div style="font-size:13px; color:hsl(var(--text)); font-weight:600;">${this._esc(news.since_human)}</div>
        </div>
        <button id="cu-close" style="background:transparent; border:0; color:hsl(var(--text-muted)); font-size:18px; line-height:1; padding:0 4px; cursor:pointer;">×</button>
      </div>
      <div>
        ${items.map(it => `
          <div class="cu-row" data-view="${this._esc(it.view)}" style="display:flex; align-items:center; gap:10px; padding:10px 14px; font-size:13px; color:hsl(var(--text));">
            <span style="font-size:18px;">${it.icon}</span>
            <span style="flex:1;">${this._esc(it.label)}</span>
            <svg style="width:14px; height:14px; color:hsl(var(--text-muted));" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M9 18l6-6-6-6"/></svg>
          </div>
        `).join('')}
      </div>
    `;
    document.body.appendChild(el);
    const close = () => {
      el.style.opacity = '0';
      el.style.transform = 'translateY(-12px)';
      el.style.transition = 'all 200ms';
      setTimeout(() => el.remove(), 220);
    };
    el.querySelector('#cu-close').onclick = (e) => { e.stopPropagation(); close(); };
    el.querySelectorAll('.cu-row').forEach(row => {
      row.onclick = () => {
        const view = row.dataset.view;
        if (typeof App !== 'undefined' && App.show && view) App.show(view);
        close();
      };
    });
    // Auto-dismiss après 25 sec si pas cliqué
    setTimeout(close, 25_000);
  },

  async run() {
    // Skip si focus mode actif
    if (typeof FocusMode !== 'undefined' && FocusMode.isOn && FocusMode.isOn()) {
      return;
    }
    const last = this._getLastVisit();
    const now = Date.now();
    // Première visite : juste enregistrer
    if (!last) {
      this._setLastVisit(now);
      return;
    }
    // Délai trop court : juste mettre à jour le timestamp, ne rien afficher
    if (now - last < this.THRESHOLD_MS) {
      this._setLastVisit(now);
      return;
    }
    try {
      const news = await this._collectNews(last);
      this._showToast(news);
    } catch (e) {
      console.warn('CatchUp.run error', e);
    }
    this._setLastVisit(now);
  },

  _esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;',
    }[c]));
  },

  init() {
    // Lancement décalé : on attend que App.api soit prêt + que les
    // autres modules d'init soient passés.
    setTimeout(() => this.run(), 2000);
  },
};

window.CatchUp = CatchUp;
window.addEventListener('DOMContentLoaded', () => CatchUp.init());
