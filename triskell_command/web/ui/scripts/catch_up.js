/* CatchUp — "Depuis ta dernière visite, voici ce qui s'est passé".
 *
 * Au retour sur l'app après >1 heure d'absence (rechargement de page
 * OU simple retour sur l'onglet, via visibilitychange) :
 *   - Compte ce qui attend : réponses de prospects reçues depuis
 *     last_visit_at + brouillons en attente de validation.
 *   - Si au moins 1 élément : affiche une mini-modale discrète en
 *     haut à droite, fermable + cliquable vers la vue concernée.
 *   - Si rien de neuf : silence radio.
 *
 * Stocke last_visit_at en localStorage (posé au départ de l'onglet
 * et à chaque vérification).
 *
 * Désactivé en mode Concentration (FocusMode.isOn()).
 */

const CatchUp = {
  STORAGE_KEY: 'tc-last-visit-at',
  THRESHOLD_MS: 60 * 60 * 1000,   // 1h d'absence min pour déclencher

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
    if (h < 1) return 'depuis moins d’une heure';
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
      const n = news.new_mails_received;
      items.push({
        icon: '↙',
        label: `${n} réponse${n > 1 ? 's' : ''} de prospect${n > 1 ? 's' : ''} reçue${n > 1 ? 's' : ''}`,
        view: 'mails',
      });
    }
    if (news.drafts_pending > 0) {
      // Compte TOUS les brouillons en attente (pas filtrable par date de
      // façon fiable) → libellé "en attente", pas "nouveaux".
      const n = news.drafts_pending;
      items.push({
        icon: '✓',
        label: `${n} brouillon${n > 1 ? 's' : ''} en attente`,
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
        #catchup-toast .cu-row:focus-visible { background: hsl(var(--accent) / 0.08); outline: 2px solid hsl(var(--accent)); outline-offset: -2px; }
      </style>
      <div style="padding: 12px 14px 10px; border-bottom: 1px solid hsl(var(--border)); display:flex; align-items:flex-start; gap:8px;">
        <div style="flex:1;">
          <div style="font-size:11px; font-weight:700; letter-spacing:1.5px; color:hsl(var(--accent)); text-transform:uppercase; margin-bottom:2px;">DEPUIS TA DERNIÈRE VISITE</div>
          <div style="font-size:13px; color:hsl(var(--text)); font-weight:600;">${this._esc(news.since_human)}</div>
        </div>
        <button id="cu-close" title="Fermer" aria-label="Fermer" style="background:transparent; border:0; color:hsl(var(--text-muted)); font-size:18px; line-height:1; padding:0 4px; cursor:pointer;">×</button>
      </div>
      <div>
        ${items.map(it => `
          <div class="cu-row" role="button" tabindex="0" data-view="${this._esc(it.view)}" style="display:flex; align-items:center; gap:10px; padding:10px 14px; font-size:13px; color:hsl(var(--text));">
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
      const go = () => {
        const view = row.dataset.view;
        if (typeof App !== 'undefined' && App.show && view) App.show(view);
        close();
      };
      row.onclick = go;
      row.onkeydown = (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); }
      };
    });
    // Auto-dismiss après 45 sec si pas cliqué
    setTimeout(close, 45_000);
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

    // Déclenchement AUSSI au simple retour sur l'onglet (sans recharger) :
    // - on quitte l'onglet → on horodate le départ (la vraie "dernière visite") ;
    // - on revient → même vérification que run() (seuil 1 h, garde anti-doublon
    //   via le check #catchup-toast de _showToast).
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'hidden') {
        this._setLastVisit(Date.now());
      } else if (document.visibilityState === 'visible') {
        this.run();
      }
    });
  },
};

window.CatchUp = CatchUp;
window.addEventListener('DOMContentLoaded', () => CatchUp.init());
