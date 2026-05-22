/* GlobalSearch — palette de recherche Cmd+K / Ctrl+K.
 *
 * Cherche en parallèle dans plusieurs sources :
 *   - Vues (raccourcis vers chaque écran)
 *   - Clients (depuis get_clients)
 *   - Mails (depuis mails_list)
 *   - Brouillons (depuis get_drafts)
 *   - Réponses prospects (depuis get_replies)
 *   - Notes Brain (depuis brain_list)
 *   - Modèles d'emails
 *   - Signatures
 *   - Apps catalog (Triskell)
 *
 * Tout en cache côté front (lazy load à la première ouverture, refresh
 * toutes les 5 min). Cmd+K ouvre, Echap ferme, flèches haut/bas
 * naviguent, Entrée valide.
 *
 * Au clic sur un résultat → bascule sur la bonne vue (et idéalement
 * focus l'élément).
 */

const GlobalSearch = {
  _data: null,       // {items: [...], fetched_at: ts}
  _lastFetch: 0,
  CACHE_TTL_MS: 5 * 60 * 1000,

  // Liste statique des vues navigables (toujours dans les résultats)
  STATIC_VIEWS: [
    { view: 'morning',   label: 'Cockpit',                kind: 'view', icon: '🎛' },
    { view: 'mails',     label: 'Boîte de réception',       kind: 'view', icon: '✉', params: { tab: 'inbound' } },
    { view: 'mails',     label: 'Messages envoyés',         kind: 'view', icon: '📤', params: { tab: 'sent' } },
    { view: 'mails',     label: 'Réponses prospects (mails)', kind: 'view', icon: '↩', params: { tab: 'reply' } },
    { view: 'drafts',    label: 'Brouillons à valider',   kind: 'view', icon: '✓' },
    { view: 'replies',   label: 'Réponses prospects',     kind: 'view', icon: '💬' },
    { view: 'clients',   label: 'Projets clients',        kind: 'view', icon: '📋' },
    { view: 'brain',     label: 'Brain (boîte à idées)',  kind: 'view', icon: '🧠' },
    { view: 'funnel',    label: 'Conversions / Funnel',   kind: 'view', icon: '📈' },
    { view: 'phare',     label: 'Le Phare (SEO)',         kind: 'view', icon: '🗼' },
    { view: 'lagriffe',  label: 'Lagriffe · pipeline',    kind: 'view', icon: '🎨' },
    { view: 'rankus',    label: 'RankUs · pipeline',      kind: 'view', icon: '📊' },
    { view: 'wow',       label: 'WoW · pipeline',         kind: 'view', icon: '🎬' },
    { view: 'autopilot', label: 'Auto-pilote',            kind: 'view', icon: '🚀' },
    { view: 'delivery',  label: 'Kits de livraison',      kind: 'view', icon: '🎁' },
    { view: 'health',    label: 'Santé du système',       kind: 'view', icon: '💚' },
    { view: 'abtest',    label: 'Tests A/B',              kind: 'view', icon: '🧪' },
    { view: 'config',    label: 'Réglages',               kind: 'view', icon: '⚙' },
    { view: 'tutorial',  label: 'Visite guidée',          kind: 'view', icon: '✨' },
  ],

  async _fetchData(force = false) {
    if (!force && this._data && (Date.now() - this._lastFetch) < this.CACHE_TTL_MS) {
      return this._data;
    }
    const items = [];

    // 1. Vues (toujours)
    for (const v of this.STATIC_VIEWS) {
      items.push({
        ...v,
        searchable: `${v.label} ${v.view}`.toLowerCase(),
      });
    }

    if (!App.api) {
      this._data = { items };
      this._lastFetch = Date.now();
      return this._data;
    }

    // 2. Clients (kanban projects)
    try {
      const r = await App.api.get_clients();
      if (r && r.ok && r.groups) {
        Object.entries(r.groups).forEach(([status, list]) => {
          (list || []).forEach(p => {
            items.push({
              kind: 'client',
              icon: '📋',
              label: p.title || p.product_name || '(projet)',
              sublabel: `${p.client_name || ''} · ${p.client_company || ''} · ${status}`,
              view: 'clients',
              searchable: `${p.title || ''} ${p.client_name || ''} ${p.client_company || ''} ${p.client_email || ''}`.toLowerCase(),
            });
          });
        });
      }
    } catch (e) {}

    // 3. Mails récents
    try {
      const r = await App.api.mails_list({ kind: 'all', limit: 100 });
      if (r && r.ok && r.mails) {
        (r.mails || []).forEach(m => {
          const from = (m.extra && m.extra.from) || '';
          const senderName = (m.extra && m.extra.sender_name) || '';
          items.push({
            kind: 'mail',
            icon: m.kind === 'reply_received' ? '↙' : '↗',
            label: m.subject || '(sans objet)',
            sublabel: `${senderName || from} · ${(m.ts || '').slice(0, 10)}`,
            view: 'mails',
            searchable: `${m.subject || ''} ${from} ${senderName} ${(m.body || '').slice(0, 200)}`.toLowerCase(),
          });
        });
      }
    } catch (e) {}

    // 4. Brouillons
    try {
      const r = await App.api.get_drafts();
      if (r && r.ok && r.rows) {
        (r.rows || []).forEach(d => {
          items.push({
            kind: 'draft',
            icon: '✏',
            label: d.subject || '(sans objet)',
            sublabel: `Brouillon · ${d.name || ''} · ${d.email || ''}`,
            view: 'drafts',
            searchable: `${d.subject || ''} ${d.name || ''} ${d.email || ''} ${(d.body || '').slice(0, 200)}`.toLowerCase(),
          });
        });
      }
    } catch (e) {}

    // 5. Notes Brain
    try {
      const r = await App.api.brain_list({ status: 'all', limit: 200 });
      if (r && r.ok && r.notes) {
        (r.notes || []).forEach(n => {
          items.push({
            kind: 'brain',
            icon: '🧠',
            label: (n.summary || n.content || '').slice(0, 80),
            sublabel: `Note · ${n.category || ''} · ${(n.tags || []).join(', ')}`,
            view: 'brain',
            searchable: `${n.content || ''} ${(n.tags || []).join(' ')} ${n.category || ''}`.toLowerCase(),
          });
        });
      }
    } catch (e) {}

    // 6. Modèles d'emails
    try {
      const r = await App.api.user_mail_templates_list();
      if (r && r.ok && r.templates) {
        (r.templates || []).forEach(t => {
          items.push({
            kind: 'template',
            icon: '📄',
            label: t.name || '(modèle)',
            sublabel: `Modèle mail · ${t.subject_default || ''}`,
            view: 'mails',
            searchable: `${t.name || ''} ${t.subject_default || ''}`.toLowerCase(),
          });
        });
      }
    } catch (e) {}

    // 7. Signatures
    try {
      const r = await App.api.signatures_list();
      if (r && r.ok && r.signatures) {
        (r.signatures || []).forEach(s => {
          items.push({
            kind: 'signature',
            icon: '✍',
            label: s.name || '(signature)',
            sublabel: 'Signature mail',
            view: 'config',
            searchable: `${s.name || ''} signature`.toLowerCase(),
          });
        });
      }
    } catch (e) {}

    this._data = { items };
    this._lastFetch = Date.now();
    return this._data;
  },

  open() {
    if (document.getElementById('gs-overlay')) return;
    const ov = document.createElement('div');
    ov.id = 'gs-overlay';
    ov.className = 'fixed inset-0 z-[240] flex items-start justify-center px-4 pt-[15vh]';
    ov.style.background = 'rgba(15,23,42,0.6)';
    ov.style.backdropFilter = 'blur(8px)';
    ov.innerHTML = `
      <div class="bg-surface rounded-2xl shadow-hero w-full max-w-2xl border border-border overflow-hidden flex flex-col" style="max-height: 70vh;">
        <div class="px-4 pt-3.5 pb-3 border-b border-border flex items-center gap-2.5">
          <svg class="w-4 h-4 text-text-muted shrink-0" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
            <circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
          </svg>
          <input id="gs-input" type="text" autocomplete="off"
                 placeholder="Cherche un client, un mail, une note, une vue…"
                 class="flex-1 bg-transparent border-0 outline-none text-base text-text placeholder:text-text-muted" />
          <kbd class="text-[10px] font-bold text-text-muted bg-bg px-1.5 py-0.5 rounded border border-border">Échap</kbd>
        </div>
        <div id="gs-results" class="flex-1 overflow-y-auto px-2 py-2"></div>
        <div class="px-4 py-2.5 border-t border-border text-[10px] text-text-muted flex items-center gap-3 bg-bg/40">
          <span><kbd class="px-1 py-0.5 rounded bg-surface border border-border">↑↓</kbd> naviguer</span>
          <span><kbd class="px-1 py-0.5 rounded bg-surface border border-border">↵</kbd> ouvrir</span>
          <span class="ml-auto" id="gs-status">Indexation…</span>
        </div>
      </div>
    `;
    document.body.appendChild(ov);

    const input = ov.querySelector('#gs-input');
    const results = ov.querySelector('#gs-results');
    const status = ov.querySelector('#gs-status');
    let currentIdx = 0;
    let filtered = [];

    const close = () => {
      document.removeEventListener('keydown', escListener);
      ov.remove();
    };
    const escListener = (e) => {
      if (e.key === 'Escape') close();
    };
    document.addEventListener('keydown', escListener);
    ov.addEventListener('click', (e) => { if (e.target === ov) close(); });

    const render = () => {
      const q = input.value.trim().toLowerCase();
      const data = this._data || { items: [] };
      if (q === '') {
        // Top vues d'abord
        filtered = data.items.filter(i => i.kind === 'view').slice(0, 12);
      } else {
        filtered = data.items
          .filter(i => i.searchable && i.searchable.includes(q))
          .slice(0, 30);
      }
      if (filtered.length === 0) {
        results.innerHTML = '<div class="px-4 py-10 text-center text-text-muted text-sm">Aucun résultat</div>';
        return;
      }
      currentIdx = 0;
      results.innerHTML = filtered.map((it, i) => `
        <button data-idx="${i}" class="gs-row w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-left ${i === 0 ? 'is-active' : ''}">
          <span class="text-xl shrink-0">${it.icon || '·'}</span>
          <span class="flex-1 min-w-0">
            <span class="block text-sm font-semibold text-text truncate">${this._esc(it.label)}</span>
            ${it.sublabel ? `<span class="block text-[11px] text-text-muted truncate">${this._esc(it.sublabel)}</span>` : ''}
          </span>
          <span class="text-[10px] uppercase tracking-widest text-text-muted shrink-0">${this._kindLabel(it.kind)}</span>
        </button>
      `).join('');
      // Bind click
      results.querySelectorAll('[data-idx]').forEach(row => {
        row.onclick = () => {
          const idx = parseInt(row.dataset.idx, 10);
          this._go(filtered[idx], close);
        };
        row.onmouseenter = () => {
          results.querySelectorAll('.gs-row').forEach(r => r.classList.remove('is-active'));
          row.classList.add('is-active');
          currentIdx = parseInt(row.dataset.idx, 10);
        };
      });
    };

    input.addEventListener('input', render);
    input.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        currentIdx = Math.min(filtered.length - 1, currentIdx + 1);
        this._updateActive(results, currentIdx);
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        currentIdx = Math.max(0, currentIdx - 1);
        this._updateActive(results, currentIdx);
      } else if (e.key === 'Enter') {
        e.preventDefault();
        if (filtered[currentIdx]) this._go(filtered[currentIdx], close);
      }
    });

    setTimeout(() => input.focus(), 30);
    status.textContent = 'Chargement…';
    this._fetchData().then(() => {
      status.textContent = `${(this._data.items || []).length} éléments indexés`;
      render();
    });

    // Styles inline pour la palette
    if (!document.getElementById('gs-styles')) {
      const s = document.createElement('style');
      s.id = 'gs-styles';
      s.textContent = `
        .gs-row { background: transparent; border: 0; transition: background 120ms; }
        .gs-row.is-active { background: hsl(var(--accent) / 0.12); }
        .gs-row:hover { background: hsl(var(--accent) / 0.08); }
      `;
      document.head.appendChild(s);
    }
  },

  _updateActive(results, idx) {
    const rows = results.querySelectorAll('.gs-row');
    rows.forEach(r => r.classList.remove('is-active'));
    if (rows[idx]) {
      rows[idx].classList.add('is-active');
      rows[idx].scrollIntoView({ block: 'nearest' });
    }
  },

  _go(item, closeFn) {
    if (!item) return;
    if (typeof App !== 'undefined' && App.show && item.view) {
      App.show(item.view, item.params || null);
    }
    closeFn();
  },

  _kindLabel(kind) {
    return ({
      view:      'vue',
      client:    'client',
      mail:      'mail',
      draft:     'brouillon',
      brain:     'note',
      template:  'modèle',
      signature: 'signature',
    })[kind] || kind;
  },

  _esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;',
    }[c]));
  },

  init() {
    // Raccourci Cmd+K / Ctrl+K
    document.addEventListener('keydown', (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k' && !e.shiftKey && !e.altKey) {
        // Ne pas intercepter si déjà dans un input/textarea actif sans modifier
        // (mais Cmd+K est universellement reconnu comme recherche)
        e.preventDefault();
        this.open();
      }
    });
  },
};

window.GlobalSearch = GlobalSearch;
window.addEventListener('DOMContentLoaded', () => GlobalSearch.init());
