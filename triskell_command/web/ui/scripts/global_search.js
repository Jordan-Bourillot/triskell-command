/* GlobalSearch — palette de recherche Ctrl+K (Cmd+K sur Mac).
 *
 * Cherche en parallèle dans plusieurs sources :
 *   - Écrans de l'app (tout le menu, avec mots-clés)
 *   - Clients (projets)
 *   - Mails récents
 *   - Brouillons en attente
 *   - Notes de la Boîte à idées
 *   - Modèles de mails
 *   - Signatures
 *
 * Tout en cache côté front (chargé à la première ouverture, rafraîchi
 * toutes les 5 min). Ctrl+K ouvre, Échap ferme, flèches haut/bas
 * naviguent, Entrée valide.
 *
 * Au clic sur un résultat → bascule sur la bonne vue (avec le bon onglet
 * quand l'écran le permet : mails, modèles, réglages).
 */

const GlobalSearch = {
  _data: null,       // {items: [...], fetched_at: ts}
  _lastFetch: 0,
  CACHE_TTL_MS: 5 * 60 * 1000,

  // Liste statique des vues navigables (toujours dans les résultats).
  // Reflète le menu ACTUEL, avec des mots-clés (accentués et non accentués)
  // pour que « prospection », « modeles », « convoi »… tombent juste.
  STATIC_VIEWS: [
    { view: 'morning',     label: 'Cockpit', kind: 'view', icon: '🎛',
      keywords: 'accueil tableau de bord matinale' },
    // — Prospection, dans l'ordre du parcours —
    { view: 'prospection', label: 'Lancer une prospection', kind: 'view', icon: '🚀',
      keywords: 'prospection mission chasse cible pme commerces locaux createurs créateurs lancer' },
    { view: 'prospects_crm', label: 'Tous les prospects', kind: 'view', icon: '👥',
      keywords: 'base prospects contacts fiches crm sans doublon' },
    { view: 'drafts',      label: 'Brouillons à valider', kind: 'view', icon: '✓',
      keywords: 'brouillons mails en attente valider approuver' },
    { view: 'replies',     label: 'Réponses', kind: 'view', icon: '💬',
      keywords: 'reponses réponses prospects interesse intéressé refus tri' },
    { view: 'autopilot',   label: 'Auto-pilote', kind: 'view', icon: '🤖',
      keywords: 'auto pilote autopilote envoi automatique ecrit écrit envoie' },
    { view: 'convoy',      label: 'Le Convoi (listes)', kind: 'view', icon: '📦',
      keywords: 'convoi liste fichier import campagne excel pdf word' },
    { view: 'obelisk',     label: 'Obélisk', kind: 'view', icon: '🗿',
      keywords: 'obelisk obélisk denicheur dénicheur createurs créateurs youtube twitch instagram tiktok' },
    { view: 'chasseur',    label: 'Le Chasseur (PME françaises)', kind: 'view', icon: '🎯',
      keywords: 'chasseur pme entreprises francaises françaises metier métier departement département' },
    { view: 'prospecteur_google', label: 'Prospecteur Google (commerces locaux)', kind: 'view', icon: '📍',
      keywords: 'google maps commerces locaux ville metier métier sans site' },
    { view: 'argus',       label: 'Argus (mails pros en masse)', kind: 'view', icon: '🦅',
      keywords: 'argus annuaires pages jaunes europages mails en masse' },
    // Chasseur Créateur retiré du menu le 14/06/2026 (remplacé par Obélisk).
    // — Mails —
    { view: 'mails', action: 'compose', label: 'Rédiger un mail', kind: 'view', icon: '✏',
      keywords: 'rediger rédiger composer ecrire écrire nouveau mail message' },
    { view: 'mails', params: { tab: 'inbound' }, label: 'Boîte de réception', kind: 'view', icon: '📥',
      keywords: 'boite boîte reception réception mails recus reçus entrants' },
    { view: 'mails', params: { tab: 'sent' }, label: 'Messages envoyés', kind: 'view', icon: '📤',
      keywords: 'envoyes envoyés sortants historique mails' },
    { view: 'mails', params: { tab: 'reply' }, label: 'Réponses prospects (mails)', kind: 'view', icon: '↩',
      keywords: 'reponses réponses mails prospects' },
    { view: 'mails', params: { tab: 'scheduled' }, label: 'Mails programmés', kind: 'view', icon: '⏰',
      keywords: 'programmes programmés planifies planifiés envoi plus tard' },
    { view: 'mail_templates', params: { tab: 'transactionnel' }, label: 'Modèles · après-achat', kind: 'view', icon: '📄',
      keywords: 'modeles modèles mails transactionnel apres après achat confirmation livraison bienvenue suivi client' },
    { view: 'mail_templates', params: { tab: 'prospection' }, label: 'Modèles · prospection', kind: 'view', icon: '📄',
      keywords: 'modeles modèles mails prospection relance' },
    // — Clients & chiffres —
    { view: 'clients_master', label: 'Tous les clients', kind: 'view', icon: '🤝',
      keywords: 'clients acheteurs fichier historique' },
    { view: 'clients',     label: 'Projets clients', kind: 'view', icon: '📋',
      keywords: 'projets clients kanban briefing en cours livre livré' },
    { view: 'revenue',     label: 'Revenus', kind: 'view', icon: '💶',
      keywords: 'revenus encaissements argent chiffre affaires stripe paiements' },
    { view: 'funnel',      label: 'Conversions', kind: 'view', icon: '📈',
      keywords: 'conversions entonnoir taux transformation' },
    { view: 'pixelpros-affiliates', label: 'Affiliés Pixel Pros', kind: 'view', icon: '🪙',
      keywords: 'affilies affiliés commissions parrainage versements' },
    // — Sites & SEO —
    { view: 'pixelpros',   label: 'Pixel Pros · commandes', kind: 'view', icon: '⭐',
      keywords: 'pixel pros sites clients kanban construction commandes pipeline chaine chaîne fabrication' },
    { view: 'wow',         label: 'WoW · demandes', kind: 'view', icon: '🌊',
      keywords: 'wow studio demandes sites etapes étapes pipeline chaine chaîne fabrication' },
    { view: 'rankus',      label: 'RankUs · demandes', kind: 'view', icon: '📊',
      keywords: 'rankus seo demandes etapes étapes pipeline chaine chaîne fabrication' },
    { view: 'lagriffe',    label: 'Lagriffe · demandes', kind: 'view', icon: '🎨',
      keywords: 'lagriffe griffe studio demandes sites etapes étapes pipeline chaine chaîne fabrication' },
    { view: 'phare',       label: 'Le Phare (SEO)', kind: 'view', icon: '🗼',
      keywords: 'phare seo referencement référencement audits robots sites google' },
    { view: 'geo',         label: 'Le GEO · cité par les IA', kind: 'view', icon: '🌍',
      keywords: 'geo géo ia chatgpt perplexity cite cité visibilite visibilité' },
    // — Atelier —
    { view: 'catalogue',   label: 'Catalogue', kind: 'view', icon: '📚',
      keywords: 'catalogue produits offres prix fiches' },
    { view: 'brain',       label: 'Boîte à idées', kind: 'view', icon: '🧠',
      keywords: 'brain boite boîte idees idées notes rappels thomas' },
    { view: 'eliks',       label: 'Eliks Studio', kind: 'view', icon: '🌱',
      keywords: 'eliks croissance reseaux réseaux instagram tiktok linkedin' },
    // — Système & accès directs —
    { view: 'health',      label: 'Santé du système', kind: 'view', icon: '💚',
      keywords: 'sante santé robots etat état pannes envois' },
    { view: 'config',      label: 'Réglages', kind: 'view', icon: '⚙',
      keywords: 'reglages réglages parametres paramètres comptes cles clés options' },
    { view: 'tutorial',    label: 'Tutoriel (visite guidée)', kind: 'view', icon: '✨',
      keywords: 'tutoriel visite guidee guidée aide apprendre' },
    { view: 'delivery',    label: 'Kits de livraison', kind: 'view', icon: '🎁',
      keywords: 'kits livraison bienvenue client mail automatique' },
    { view: 'abtest',      label: 'Tests A/B', kind: 'view', icon: '🧪',
      keywords: 'test ab variantes mails comparer' },
  ],

  async _fetchData(force = false) {
    if (!force && this._data && (Date.now() - this._lastFetch) < this.CACHE_TTL_MS) {
      return this._data;
    }
    const items = [];

    // 1. Vues (toujours) — label + identifiant + mots-clés
    for (const v of this.STATIC_VIEWS) {
      items.push({
        ...v,
        searchable: `${v.label} ${v.view} ${v.keywords || ''}`.toLowerCase(),
      });
    }

    if (!App.api) {
      this._data = { items };
      this._lastFetch = Date.now();
      return this._data;
    }

    // 2-7. Sources serveur, chargées EN PARALLÈLE (avant : l'une après
    // l'autre — l'ouverture pouvait prendre plusieurs secondes). Chaque
    // source qui échoue est simplement ignorée.
    const sources = [
      // Clients (kanban projets)
      async () => {
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
      },
      // Mails récents
      async () => {
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
      },
      // Brouillons
      async () => {
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
      },
      // Notes de la Boîte à idées
      async () => {
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
      },
      // Modèles de mails
      async () => {
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
      },
      // Signatures → Réglages, onglet Mails directement
      async () => {
        const r = await App.api.signatures_list();
        if (r && r.ok && r.signatures) {
          (r.signatures || []).forEach(s => {
            items.push({
              kind: 'signature',
              icon: '✍',
              label: s.name || '(signature)',
              sublabel: 'Signature mail',
              view: 'config',
              params: { tab: 'mails' },
              searchable: `${s.name || ''} signature`.toLowerCase(),
            });
          });
        }
      },
    ];
    await Promise.all(sources.map(fn => fn().catch(() => {})));

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
          <span class="ml-auto" id="gs-status">Préparation…</span>
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
      // Préparation encore en cours : on garde l'indicateur de chargement
      // (taper pendant la préparation ne doit pas afficher un faux
      // « Aucun résultat »).
      if (!this._data) return;
      const q = input.value.trim().toLowerCase();
      const data = this._data;
      if (q === '') {
        // Top vues d'abord
        filtered = data.items.filter(i => i.kind === 'view').slice(0, 12);
      } else {
        filtered = data.items
          .filter(i => i.searchable && i.searchable.includes(q))
          .slice(0, 30);
      }
      status.textContent = `${filtered.length} résultat${filtered.length > 1 ? 's' : ''}`;
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
    // Pendant la préparation : indicateur DANS la zone de résultats
    // (avant : zone vide, on croyait la recherche cassée).
    if (this._data) {
      render();
    } else {
      status.textContent = 'Préparation…';
      results.innerHTML = `
        <div class="px-4 py-10 text-center text-text-muted text-sm">
          <span class="inline-block w-5 h-5 rounded-full border-2 border-accent/30 border-t-accent animate-spin align-middle mr-2"></span>
          Préparation de la recherche…
        </div>`;
    }
    this._fetchData().then(() => {
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
      if (item.action === 'compose') {
        // « Rédiger un mail » : on ouvre le composeur dès que la
        // messagerie est prête (réessais courts, ~2 s max).
        const t0 = Date.now();
        const attempt = () => {
          if (typeof Mails !== 'undefined'
              && typeof Mails._openComposer === 'function'
              && document.querySelector('[data-mtab]')) {
            Mails._openComposer({});
            return;
          }
          if (Date.now() - t0 < 2000) App.viewTimeout(attempt, 120);
        };
        App.viewTimeout(attempt, 120);
      }
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
