/* Vue Pixel Pros — pipeline d'inscription / construction / livraison.
 *
 * Workflow plus court que Lagriffe/RankUs/WoW (pas de validation humaine) :
 *   draft → paid → building → live (ou failed)
 *
 * UX choisie : Kanban à 4 colonnes (+ section "Échecs" séparée).
 * Tout doit être lisible au premier coup d'œil :
 *  - Funnel synthétique en haut avec les compteurs et les flèches qui
 *    racontent le pipeline en une ligne.
 *  - 4 colonnes Kanban, une couleur dominante par statut, une icône
 *    par statut, les cartes qui glissent visuellement de gauche à droite.
 *  - Chaque carte : grosse pastille initiale colorée + nom commercial gros
 *    + formule achetée en badge + temps écoulé en relatif ("il y a 2 h").
 *  - Au clic → panneau de détail à droite (slide-in) avec timeline,
 *    données du formulaire et toutes les actions.
 *  - Les commandes "Payé" en attente depuis +6h sont marquées URGENT
 *    (bordure dorée animée) pour qu'on les voie tout de suite.
 *
 * Données via :
 *   App.api.pixelpros_list_intakes({ status?, limit? })
 *   App.api.pixelpros_get_intake({ id })
 *   App.api.pixelpros_dispatch_build({ id })
 *   App.api.pixelpros_mark_failed({ id, reason? })
 *   App.api.pixelpros_resend_paid_mail({ id })
 *   App.api.pixelpros_resend_live_mail({ id })
 *   App.api.pixelpros_pipeline_state()
 */

const PixelPros = {
  state: {
    intakes: [],
    selectedId: null,
    detail: null,
    counts: null,
    loading: false,
    search: '',
  },

  // Colonnes Kanban : 4 statuts principaux dans l'ordre du flow.
  // Les échecs ont leur propre section en bas.
  COLUMNS: [
    { status: 'draft',    label: 'Formulaire reçu',     icon: '📝', accent: '#94a3b8', short: 'Formulaires' },
    { status: 'paid',     label: 'Payé · à construire', icon: '💳', accent: '#facc15', short: 'Payés' },
    { status: 'building', label: 'En construction',     icon: '🛠',  accent: '#818cf8', short: 'En cours' },
    { status: 'live',     label: 'En ligne',            icon: '✅', accent: '#22c55e', short: 'En ligne' },
  ],

  FORMULES: {
    base:        { label: 'Site seul',                 price: '24,90 €', color: '#94a3b8' },
    base_domain: { label: 'Site + domaine',            price: '33,90 €', color: '#0ea5e9' },
    base_seo:    { label: 'Site + SEO',                price: '59,80 €', color: '#a855f7' },
    base_all:    { label: 'Site + domaine + SEO',      price: '68,80 €', color: '#ec4899' },
    combo:       { label: 'Pack TOUT-EN-UN',           price: '49,90 €', color: '#facc15' },
  },

  URGENT_THRESHOLD_H: 6,   // un draft "paid" depuis +6h sans build = urgent

  async render(container) {
    this._root = container;
    container.innerHTML = `
      <section class="animate-slide-up">
        <div class="mb-6 flex items-end justify-between flex-wrap gap-3">
          <div>
            <div class="hero-kicker mb-2" style="color:#facc15;">PIXEL PROS · PIPELINE</div>
            <h1 class="hero-title mb-2" style="font-size: 34px;">Tes sites client en un coup d'œil.</h1>
            <p class="hero-subtitle">Du formulaire reçu jusqu'au site en ligne — clique sur une carte pour les détails et les actions.</p>
          </div>
          <div class="flex items-center gap-2">
            <input id="pp-search" type="search" placeholder="Rechercher (nom, email, slug)" style="padding:9px 14px; border-radius:8px; background:var(--surface, #0f172a); border:1px solid var(--border, #1e293b); color:#cbd5e1; font-size:13px; width:240px;" />
            <button id="pp-refresh" class="btn btn-secondary">↻ Rafraîchir</button>
          </div>
        </div>

        <!-- Funnel synthétique -->
        <div id="pp-funnel" class="mb-7"></div>

        <!-- Kanban -->
        <div id="pp-kanban" class="pp-kanban"></div>

        <!-- Section Échecs (apparaît seulement s'il y a des failed) -->
        <div id="pp-failures" class="mt-7"></div>

        <!-- Panneau de détail (slide-in à droite, vide par défaut) -->
        <div id="pp-detail-overlay" class="pp-detail-overlay" hidden></div>
        <aside id="pp-detail" class="pp-detail-panel" hidden></aside>
      </section>
    `;
    this._injectStyles();

    document.getElementById('pp-refresh').onclick = () => this.refresh();
    document.getElementById('pp-search').oninput = (e) => {
      this.state.search = e.target.value.toLowerCase().trim();
      this._renderKanban();
      this._renderFailures();
    };
    document.getElementById('pp-detail-overlay').onclick = () => this._closeDetail();

    await this.refresh();
  },

  _injectStyles() {
    if (document.getElementById('pp-styles')) return;
    const s = document.createElement('style');
    s.id = 'pp-styles';
    s.textContent = `
      /* === FUNNEL synthétique === */
      .pp-funnel { display:flex; align-items:stretch; gap:0; flex-wrap:wrap; background:var(--surface, #0f172a); border:1px solid var(--border, #1e293b); border-radius:14px; padding:14px; }
      .pp-funnel-step { flex:1; min-width:120px; padding:10px 14px; display:flex; flex-direction:column; align-items:center; gap:4px; position:relative; }
      .pp-funnel-icon { font-size:24px; line-height:1; margin-bottom:2px; }
      .pp-funnel-n { font-size:24px; font-weight:800; line-height:1; }
      .pp-funnel-l { font-size:10.5px; font-weight:700; letter-spacing:.06em; text-transform:uppercase; color:#94a3b8; margin-top:2px; }
      .pp-funnel-step.alert .pp-funnel-n { color:#facc15; }
      .pp-funnel-step.alert .pp-funnel-l { color:#facc15; }
      .pp-funnel-step.success .pp-funnel-n { color:#22c55e; }
      .pp-funnel-step.success .pp-funnel-l { color:#22c55e; }

      /* Marqueurs ✉️ entre étapes : mails envoyés automatiquement au client */
      .pp-funnel-gap { width:20px; display:flex; align-items:center; justify-content:center; color:#475569; font-size:22px; font-weight:300; }
      .pp-funnel-gap::after { content:'›'; }
      .pp-mail-marker {
        display:flex; flex-direction:column; align-items:center; gap:2px;
        padding:8px 10px; margin:0 4px;
        background: color-mix(in srgb, var(--mc) 12%, transparent);
        border: 1px dashed color-mix(in srgb, var(--mc) 55%, transparent);
        border-radius: 10px; cursor:pointer; min-width:90px;
        color:#cbd5e1; font: inherit;
        transition: background .15s, transform .15s, border-color .15s;
        position:relative;
      }
      .pp-mail-marker:hover {
        background: color-mix(in srgb, var(--mc) 22%, transparent);
        border-color: var(--mc);
        transform: translateY(-1px);
      }
      .pp-mail-marker .pp-mail-ico { font-size:18px; line-height:1; }
      .pp-mail-marker .pp-mail-lbl { font-size:10.5px; font-weight:800; letter-spacing:.04em; text-transform:uppercase; color: var(--mc); }
      .pp-mail-marker .pp-mail-edit { font-size:9.5px; color:#94a3b8; opacity:0; transition:opacity .15s; }
      .pp-mail-marker:hover .pp-mail-edit { opacity:1; }

      /* Champs de l'éditeur de mail */
      .pp-mail-input, .pp-mail-textarea {
        width:100%; padding:10px 12px; border-radius:8px;
        background:#0b1020; border:1px solid var(--border, #1e293b);
        color:#e2e8f0; font-size:13px; font-family: inherit; line-height:1.5;
        box-sizing:border-box;
      }
      .pp-mail-input:focus, .pp-mail-textarea:focus { outline:none; border-color:#facc15; }
      .pp-mail-textarea { resize:vertical; }
      .pp-mail-textarea-code { font-family: ui-monospace, 'SF Mono', Consolas, monospace; font-size:11.5px; }
      .pp-mail-preview { width:100%; min-height:340px; border-radius:8px; background:#fff; border:1px solid var(--border, #1e293b); margin-top:10px; }
      .pp-mail-vars { font-size:12px; color:#94a3b8; line-height:1.9; }
      .pp-mail-vars code { background:#020617; color:#facc15; padding:2px 6px; border-radius:4px; font-size:11px; margin-right:8px; }
      .pp-action-btn:disabled { opacity:0.4; cursor:not-allowed; }

      /* === KANBAN === */
      .pp-kanban { display:grid; grid-template-columns: repeat(4, minmax(220px, 1fr)); gap:14px; }
      @media (max-width: 1100px) { .pp-kanban { grid-template-columns: repeat(2, 1fr); } }
      @media (max-width: 640px)  { .pp-kanban { grid-template-columns: 1fr; } }

      .pp-col { background:var(--surface, #0f172a); border:1px solid var(--border, #1e293b); border-radius:14px; padding:14px; display:flex; flex-direction:column; gap:10px; min-height:200px; }
      .pp-col-head { display:flex; align-items:center; justify-content:space-between; padding-bottom:10px; border-bottom:2px solid var(--col-accent, #94a3b8); }
      .pp-col-title { display:flex; align-items:center; gap:8px; font-size:13px; font-weight:800; color:var(--col-accent, #94a3b8); text-transform:uppercase; letter-spacing:.04em; }
      .pp-col-title .ico { font-size:16px; }
      .pp-col-count { background:rgba(255,255,255,.06); color:#cbd5e1; padding:2px 10px; border-radius:999px; font-size:11px; font-weight:800; }
      .pp-col-body { display:flex; flex-direction:column; gap:8px; }
      .pp-col-empty { color:#64748b; font-size:12px; font-style:italic; text-align:center; padding:24px 8px; }

      /* === CARTE === */
      .pp-card { background:rgba(15, 23, 42, .6); border:1px solid var(--border, #1e293b); border-radius:10px; padding:11px; display:flex; align-items:center; gap:11px; cursor:pointer; transition:border-color .15s, transform .15s, background .15s; position:relative; }
      .pp-card:hover { border-color:var(--col-accent, #facc15); background:rgba(15, 23, 42, .9); transform:translateX(2px); }
      .pp-card.urgent { border-color:#facc15; box-shadow: 0 0 0 1px #facc15, 0 0 12px rgba(250,204,21,.3); animation: pp-pulse 2s ease-in-out infinite; }
      .pp-card.selected { border-color:#facc15; background:rgba(250,204,21,.05); }
      @keyframes pp-pulse { 0%, 100% { box-shadow: 0 0 0 1px #facc15, 0 0 12px rgba(250,204,21,.3); } 50% { box-shadow: 0 0 0 1px #facc15, 0 0 20px rgba(250,204,21,.6); } }

      .pp-avatar { width:38px; height:38px; border-radius:9px; display:flex; align-items:center; justify-content:center; font-weight:800; font-size:16px; color:#0f172a; flex-shrink:0; text-transform:uppercase; }
      .pp-card-body { flex:1; min-width:0; }
      .pp-card-name { font-weight:700; font-size:13.5px; color:#e2e8f0; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
      .pp-card-meta { font-size:11px; color:#94a3b8; margin-top:2px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
      .pp-card-badges { display:flex; align-items:center; gap:6px; margin-top:6px; flex-wrap:wrap; }
      .pp-formule-badge { padding:2px 7px; border-radius:6px; font-size:10px; font-weight:700; }
      .pp-card-time { font-size:10.5px; color:#64748b; }
      .pp-urgent-badge { background:#facc15; color:#0f172a; padding:1px 6px; border-radius:4px; font-size:9.5px; font-weight:800; letter-spacing:.04em; }

      /* Petit bouton corbeille en haut-droite de la carte, visible au survol.
         Permet de supprimer un formulaire sans avoir à ouvrir le détail. */
      .pp-card-trash { position:absolute; top:6px; right:6px; width:26px; height:26px; border-radius:6px; background:rgba(239,68,68,.15); color:#fca5a5; border:none; cursor:pointer; font-size:13px; display:flex; align-items:center; justify-content:center; opacity:0; transition:opacity .15s, background .15s; }
      .pp-card:hover .pp-card-trash { opacity:1; }
      .pp-card-trash:hover { background:#ef4444; color:#fff; }

      /* === SECTION ÉCHECS === */
      .pp-failures { background:rgba(239,68,68,.06); border:1px solid rgba(239,68,68,.25); border-radius:14px; padding:14px; }
      .pp-failures-title { display:flex; align-items:center; gap:8px; font-size:13px; font-weight:800; color:#ef4444; text-transform:uppercase; letter-spacing:.04em; margin-bottom:10px; }
      .pp-failures-grid { display:grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap:10px; }
      .pp-failures-empty { display:none; }

      /* === PANNEAU DE DÉTAIL (slide-in droite) === */
      .pp-detail-overlay { position:fixed; inset:0; background:rgba(0,0,0,.65); z-index:998; backdrop-filter: blur(3px); -webkit-backdrop-filter: blur(3px); animation: pp-fadein .2s ease; }
      /* Fond opaque solide, pas de var() qui pourrait être transparente. */
      .pp-detail-panel { position:fixed; top:0; right:0; bottom:0; width:min(960px, 95vw); background:#0b1020; border-left:1px solid #1e293b; z-index:999; overflow-y:auto; padding:24px; box-shadow:-12px 0 30px rgba(0,0,0,.5); animation: pp-slidein .25s cubic-bezier(.2,.7,.3,1); color:#e2e8f0; }
      @keyframes pp-fadein { from { opacity:0; } to { opacity:1; } }
      @keyframes pp-slidein { from { transform:translateX(100%); } to { transform:translateX(0); } }

      .pp-detail-close { position:absolute; top:14px; right:14px; width:36px; height:36px; border-radius:50%; background:rgba(148,163,184,.15); color:#cbd5e1; border:none; cursor:pointer; font-size:20px; display:flex; align-items:center; justify-content:center; }
      .pp-detail-close:hover { background:rgba(239,68,68,.2); color:#fff; }
      .pp-detail-head { display:flex; align-items:flex-start; gap:14px; margin-bottom:18px; padding-right:50px; }
      .pp-detail-head .pp-avatar { width:54px; height:54px; font-size:22px; border-radius:12px; }
      .pp-detail-name { font-size:22px; font-weight:800; color:#e2e8f0; line-height:1.2; }
      .pp-detail-sub { font-size:13px; color:#94a3b8; margin-top:4px; }
      .pp-detail-pill { display:inline-block; padding:3px 11px; border-radius:999px; font-size:11px; font-weight:700; letter-spacing:.02em; margin-top:8px; }

      .pp-detail-section { margin-bottom:20px; }
      .pp-detail-section-title { font-size:11px; font-weight:800; letter-spacing:.08em; color:#94a3b8; text-transform:uppercase; margin-bottom:10px; }

      .pp-actions { display:flex; flex-wrap:wrap; gap:8px; }
      .pp-action-btn { padding:9px 14px; border-radius:8px; font-size:13px; font-weight:700; cursor:pointer; border:1px solid transparent; }
      .pp-action-btn.primary { background:#facc15; color:#0f172a; }
      .pp-action-btn.secondary { background:rgba(148,163,184,.12); color:#cbd5e1; border-color:rgba(148,163,184,.25); }
      .pp-action-btn.danger { background:rgba(239,68,68,.12); color:#fca5a5; border-color:rgba(239,68,68,.3); }
      .pp-action-btn:hover { filter:brightness(1.12); }

      .pp-detail-link { color:#facc15; font-weight:700; text-decoration:underline; }
      .pp-detail-link:hover { color:#fde047; }

      .pp-error-box { background:rgba(239,68,68,.1); border:1px solid rgba(239,68,68,.3); border-radius:8px; padding:11px 14px; color:#fca5a5; font-size:13px; }

      .pp-timeline { border-left:2px solid var(--border, #1e293b); padding-left:14px; margin-left:6px; }
      .pp-timeline-event { padding:8px 0; }
      .pp-timeline-event .ts { font-size:11px; color:#64748b; font-variant-numeric:tabular-nums; margin-bottom:2px; }
      .pp-timeline-event .lbl { font-size:13px; color:#cbd5e1; }
      .pp-timeline-event.current .lbl { font-weight:700; color:#facc15; }

      .pp-data-toggle { background:rgba(148,163,184,.08); border:1px solid var(--border, #1e293b); border-radius:8px; padding:8px 12px; cursor:pointer; font-size:12px; color:#94a3b8; user-select:none; }
      .pp-data-toggle:hover { color:#cbd5e1; }
      .pp-data-pre { margin-top:10px; padding:12px; background:#020617; border-radius:8px; font-size:11px; color:#cbd5e1; overflow:auto; max-height:340px; }

      .pp-toast { position:fixed; bottom:30px; right:30px; padding:14px 18px; border-radius:10px; font-weight:700; font-size:13px; z-index:9999; box-shadow:0 6px 20px rgba(0,0,0,.4); animation: pp-toastin .2s ease; }
      .pp-toast.ok { background:#facc15; color:#0f172a; }
      .pp-toast.err { background:#ef4444; color:#fff; }
      @keyframes pp-toastin { from { opacity:0; transform:translateY(10px); } to { opacity:1; transform:translateY(0); } }
    `;
    document.head.appendChild(s);
  },

  async refresh() {
    this.state.loading = true;
    this._renderFunnel();
    this._renderKanban();
    const [stateRes, listRes] = await Promise.all([
      this._call('pixelpros_pipeline_state'),
      this._call('pixelpros_list_intakes', { limit: 200 }),
    ]);
    if (stateRes && stateRes.ok) this.state.counts = stateRes.counts || null;
    this.state.intakes = (listRes && listRes.ok) ? (listRes.intakes || []) : [];
    this.state.loading = false;

    this._renderFunnel();
    this._renderKanban();
    this._renderFailures();

    if (this.state.selectedId) {
      await this._loadDetail(this.state.selectedId);
    }
  },

  // ----- FUNNEL -----
  // On affiche un mini-marqueur ✉️ entre les étapes pour visualiser quand
  // un mail est envoyé au client. Au clic, ça ouvre l'éditeur du mail.
  //
  // Mails dans le pipeline Pixel Pros :
  //   draft → [✉️ paiement reçu] → paid → building → [✉️ site en ligne] → live
  MAILS_BETWEEN: {
    'draft→paid':     { kind: 'paid', label: 'Mail "paiement reçu"',  short: 'Paiement reçu',  color: '#facc15' },
    'building→live':  { kind: 'live', label: 'Mail "site en ligne"',  short: 'Site en ligne',  color: '#22c55e' },
  },

  _renderFunnel() {
    const el = document.getElementById('pp-funnel');
    if (!el) return;
    const c = this.state.counts || {};
    const steps = [
      { k: 'draft',    l: 'Formulaire',      ico: '📝', cls: '' },
      { k: 'paid',     l: 'À construire',    ico: '💳', cls: (c.paid||0) > 0 ? 'alert' : '' },
      { k: 'building', l: 'En construction', ico: '🛠',  cls: '' },
      { k: 'live',     l: 'En ligne',        ico: '✅', cls: (c.live||0) > 0 ? 'success' : '' },
    ];
    el.className = 'pp-funnel';

    const parts = [];
    steps.forEach((s, i) => {
      parts.push(`
        <div class="pp-funnel-step ${s.cls}">
          <span class="pp-funnel-icon">${s.ico}</span>
          <span class="pp-funnel-n">${c[s.k] || 0}</span>
          <span class="pp-funnel-l">${s.l}</span>
        </div>
      `);
      if (i < steps.length - 1) {
        const next = steps[i + 1];
        const transitionKey = `${s.k}→${next.k}`;
        const mail = this.MAILS_BETWEEN[transitionKey];
        if (mail) {
          parts.push(`
            <button class="pp-mail-marker" data-pp-mail="${mail.kind}"
                    style="--mc:${mail.color};"
                    title="Voir / modifier le mail « ${this._escape(mail.short)} »">
              <span class="pp-mail-ico">✉️</span>
              <span class="pp-mail-lbl">${this._escape(mail.short)}</span>
              <span class="pp-mail-edit">Modifier</span>
            </button>
          `);
        } else {
          parts.push('<div class="pp-funnel-gap"></div>');
        }
      }
    });
    el.innerHTML = parts.join('');

    // Bind des marqueurs ✉️
    el.querySelectorAll('[data-pp-mail]').forEach(btn => {
      btn.onclick = (e) => {
        e.stopPropagation();
        this._openMailEditor(btn.dataset.ppMail);
      };
    });
  },

  // ----- ÉDITEUR DE MAIL -----
  async _openMailEditor(kind) {
    if (!kind) return;
    // Overlay + panel
    let overlay = document.getElementById('pp-mail-overlay');
    let panel = document.getElementById('pp-mail-panel');
    if (!overlay) {
      overlay = document.createElement('div');
      overlay.id = 'pp-mail-overlay';
      overlay.className = 'pp-detail-overlay';
      overlay.onclick = () => this._closeMailEditor();
      document.body.appendChild(overlay);
    }
    if (!panel) {
      panel = document.createElement('aside');
      panel.id = 'pp-mail-panel';
      panel.className = 'pp-detail-panel';
      document.body.appendChild(panel);
    }
    overlay.hidden = false;
    panel.hidden = false;
    panel.innerHTML = `<div style="padding:60px 0; text-align:center; color:#94a3b8;">Chargement…</div>`;

    const res = await this._call('pixelpros_mail_template_get', { kind });
    if (!res || !res.ok) {
      panel.innerHTML = `<button class="pp-detail-close" data-pp-mail-close>×</button>
        <div class="pp-error-box">Erreur de chargement : ${this._escape(res?.error || 'inconnue')}</div>`;
      panel.querySelector('[data-pp-mail-close]').onclick = () => this._closeMailEditor();
      return;
    }
    this._renderMailEditor(kind, res.template);
  },

  _renderMailEditor(kind, tpl) {
    const panel = document.getElementById('pp-mail-panel');
    if (!panel) return;
    const mailMeta = kind === 'paid'
      ? { title: 'Mail "Paiement reçu"', sub: 'Envoyé automatiquement quand Stripe confirme le paiement (passage en statut "Payé").', accent: '#facc15' }
      : { title: 'Mail "Site en ligne"',  sub: 'Envoyé automatiquement quand le site est mis en ligne (passage en statut "En ligne").',  accent: '#22c55e' };

    const isCustom = !!tpl.is_custom;

    panel.innerHTML = `
      <button class="pp-detail-close" data-pp-mail-close>×</button>

      <div class="pp-detail-head">
        <div class="pp-avatar" style="background:${mailMeta.accent};">✉️</div>
        <div>
          <div class="pp-detail-name">${this._escape(mailMeta.title)}</div>
          <div class="pp-detail-sub">${this._escape(mailMeta.sub)}</div>
          <span class="pp-detail-pill" style="background:${mailMeta.accent}25; color:${mailMeta.accent};">
            ${isCustom ? '✏️ Modifié par toi' : '⚙️ Texte par défaut'}
          </span>
        </div>
      </div>

      <div class="pp-detail-section">
        <div class="pp-detail-section-title">Sujet du mail</div>
        <input id="pp-mail-subject" type="text" class="pp-mail-input" value="${this._escape(tpl.subject || '')}" />
      </div>

      <div class="pp-detail-section">
        <div class="pp-detail-section-title">Texte brut (clients sans HTML)</div>
        <textarea id="pp-mail-text" class="pp-mail-textarea" rows="10">${this._escape(tpl.body_text || '')}</textarea>
      </div>

      <div class="pp-detail-section">
        <div class="pp-detail-section-title">Version HTML (mise en forme jolie)</div>
        <textarea id="pp-mail-html" class="pp-mail-textarea pp-mail-textarea-code" rows="14">${this._escape(tpl.body_html || '')}</textarea>
        <details style="margin-top:10px;">
          <summary class="pp-data-toggle">👁 Aperçu du HTML</summary>
          <iframe id="pp-mail-preview" class="pp-mail-preview" sandbox=""></iframe>
        </details>
      </div>

      <div class="pp-detail-section">
        <div class="pp-detail-section-title">Variables disponibles (à coller dans le texte ou le HTML)</div>
        <div class="pp-mail-vars">
          <code>{firstname}</code> <span>prénom du client</span><br>
          <code>{business}</code> <span>nom de l'entreprise</span><br>
          <code>{business_paren}</code> <span>" (nom)" entre parenthèses, ou rien</span><br>
          <code>{business_space}</code> <span>" nom" avec espace devant, ou rien</span><br>
          <code>{site_url}</code> <span>URL du site (mail "en ligne" uniquement)</span>
        </div>
      </div>

      <div class="pp-detail-section">
        <div class="pp-actions">
          <button data-pp-mail-save class="pp-action-btn primary">💾 Enregistrer</button>
          <button data-pp-mail-reset class="pp-action-btn danger" ${isCustom ? '' : 'disabled'}>↺ Remettre par défaut</button>
        </div>
      </div>
    `;

    panel.querySelector('[data-pp-mail-close]').onclick = () => this._closeMailEditor();

    // Aperçu HTML live
    const htmlField = panel.querySelector('#pp-mail-html');
    const preview = panel.querySelector('#pp-mail-preview');
    const refreshPreview = () => {
      if (!preview) return;
      preview.srcdoc = htmlField.value || '<i>(vide)</i>';
    };
    htmlField.addEventListener('input', refreshPreview);
    refreshPreview();

    panel.querySelector('[data-pp-mail-save]').onclick = async () => {
      const subject = panel.querySelector('#pp-mail-subject').value.trim();
      const body_text = panel.querySelector('#pp-mail-text').value;
      const body_html = panel.querySelector('#pp-mail-html').value;
      if (!subject) { this._toast('Le sujet ne peut pas être vide', true); return; }
      const res = await this._call('pixelpros_mail_template_save', { kind, subject, body_text, body_html });
      this._toast(res?.ok ? `Sauvegardé : ${res.message || ''}` : `Échec : ${res?.error || res?.message || '?'}`, !res?.ok);
      if (res?.ok) this._openMailEditor(kind);  // recharge pour mettre à jour la pastille "Modifié"
    };

    panel.querySelector('[data-pp-mail-reset]').onclick = async () => {
      if (!confirm('Remettre le mail à sa version par défaut ? Tes modifications seront perdues.')) return;
      const res = await this._call('pixelpros_mail_template_reset', { kind });
      this._toast(res?.ok ? `Remis par défaut : ${res.message || ''}` : `Échec : ${res?.error || res?.message || '?'}`, !res?.ok);
      if (res?.ok) this._openMailEditor(kind);
    };
  },

  _closeMailEditor() {
    const overlay = document.getElementById('pp-mail-overlay');
    const panel = document.getElementById('pp-mail-panel');
    if (overlay) overlay.hidden = true;
    if (panel) { panel.hidden = true; panel.innerHTML = ''; }
  },

  // ----- KANBAN -----
  _renderKanban() {
    const el = document.getElementById('pp-kanban');
    if (!el) return;
    const groups = {};
    for (const col of this.COLUMNS) groups[col.status] = [];
    const filtered = this._filteredIntakes();
    for (const it of filtered) {
      if (groups[it.status]) groups[it.status].push(it);
    }

    el.innerHTML = this.COLUMNS.map(col => {
      const items = groups[col.status];
      return `
        <div class="pp-col" style="--col-accent:${col.accent};">
          <div class="pp-col-head">
            <div class="pp-col-title"><span class="ico">${col.icon}</span><span>${this._escape(col.short)}</span></div>
            <span class="pp-col-count">${items.length}</span>
          </div>
          <div class="pp-col-body">
            ${items.length === 0
              ? `<div class="pp-col-empty">${this.state.loading ? 'Chargement…' : 'Aucune commande ici.'}</div>`
              : items.map(it => this._renderCard(it, col.accent)).join('')}
          </div>
        </div>
      `;
    }).join('');

    this._bindCardActions(el);
  },

  // ----- ÉCHECS -----
  _renderFailures() {
    const el = document.getElementById('pp-failures');
    if (!el) return;
    const failures = this._filteredIntakes().filter(it => it.status === 'failed');
    if (!failures.length) { el.innerHTML = ''; return; }
    el.innerHTML = `
      <div class="pp-failures">
        <div class="pp-failures-title">⚠ Échecs (${failures.length}) — à relancer ou marquer en abandonné</div>
        <div class="pp-failures-grid">${failures.map(it => this._renderCard(it, '#ef4444')).join('')}</div>
      </div>
    `;
    this._bindCardActions(el);
  },

  _bindCardActions(root) {
    if (!root) return;
    // Clic sur la carte → ouvre le panneau de détail
    root.querySelectorAll('[data-pp-card]').forEach(card => {
      card.onclick = () => {
        this.state.selectedId = card.dataset.ppCard;
        this._loadDetail(this.state.selectedId);
      };
    });
    // Clic sur la corbeille → suppression directe sans ouvrir le détail
    root.querySelectorAll('[data-pp-trash]').forEach(btn => {
      btn.onclick = (e) => {
        e.stopPropagation();
        e.preventDefault();
        const id = btn.dataset.ppTrash;
        const intake = (this.state.intakes || []).find(it => it.id === id);
        if (!intake) return;
        this._doAction('delete', intake);
      };
    });
  },

  _filteredIntakes() {
    const q = this.state.search;
    if (!q) return this.state.intakes;
    return this.state.intakes.filter(it => {
      const data = it.data || {};
      const blob = [
        data.business_name, data['business-name'], data.email,
        it.slug, it.id, data.city, data.phone,
      ].filter(Boolean).join(' ').toLowerCase();
      return blob.includes(q);
    });
  },

  _renderCard(it, accent) {
    const data = it.data || {};
    const name = data.business_name || data['business-name'] || '(sans nom)';
    const email = data.email || it.contact_email || '—';
    const initial = name.trim().charAt(0).toUpperCase() || '?';
    const color = this._colorFromName(name);
    const option = it.option || data.option || '';
    const formule = this.FORMULES[option] || null;
    const isUrgent = it.status === 'paid' && this._hoursSince(it.updated_at || it.stripe_paid_at || it.created_at) > this.URGENT_THRESHOLD_H;
    const selected = this.state.selectedId === it.id ? 'selected' : '';
    return `
      <div class="pp-card ${isUrgent ? 'urgent' : ''} ${selected}" data-pp-card="${this._escape(it.id)}" style="--col-accent:${accent};">
        <button class="pp-card-trash" data-pp-trash="${this._escape(it.id)}" title="Supprimer ce formulaire" aria-label="Supprimer">🗑</button>
        <div class="pp-avatar" style="background:${color};">${this._escape(initial)}</div>
        <div class="pp-card-body">
          <div class="pp-card-name">${this._escape(name)}</div>
          <div class="pp-card-meta">${this._escape(email)}</div>
          <div class="pp-card-badges">
            ${formule ? `<span class="pp-formule-badge" style="background:${formule.color}20; color:${formule.color};">${this._escape(formule.label)}</span>` : ''}
            <span class="pp-card-time">${this._timeRelative(it.updated_at || it.created_at)}</span>
            ${isUrgent ? `<span class="pp-urgent-badge">URGENT</span>` : ''}
          </div>
        </div>
      </div>
    `;
  },

  // ----- PANNEAU DE DÉTAIL -----
  async _loadDetail(id) {
    document.getElementById('pp-detail-overlay').hidden = false;
    const panel = document.getElementById('pp-detail');
    panel.hidden = false;
    panel.innerHTML = `<div style="padding:60px 0; text-align:center; color:#94a3b8;">Chargement…</div>`;
    const res = await this._call('pixelpros_get_intake', { id });
    if (!res || !res.ok) {
      panel.innerHTML = `<button class="pp-detail-close" data-pp-close>×</button><div class="pp-error-box">Erreur de chargement : ${this._escape(res?.error || 'inconnue')}</div>`;
      panel.querySelector('[data-pp-close]').onclick = () => this._closeDetail();
      return;
    }
    this.state.detail = res;
    this._renderDetail();
    this._renderKanban(); // refresh la sélection visuelle
  },

  _closeDetail() {
    document.getElementById('pp-detail-overlay').hidden = true;
    const panel = document.getElementById('pp-detail');
    panel.hidden = true;
    panel.innerHTML = '';
    this.state.selectedId = null;
    this.state.detail = null;
    this._renderKanban();
  },

  _renderDetail() {
    const panel = document.getElementById('pp-detail');
    const { intake, timeline } = this.state.detail;
    const data = intake.data || {};
    const name = data.business_name || data['business-name'] || '(sans nom)';
    const email = data.email || '—';
    const phone = data.phone || '';
    const initial = name.trim().charAt(0).toUpperCase() || '?';
    const color = this._colorFromName(name);
    const col = this.COLUMNS.find(c => c.status === intake.status) ||
                { label: intake.status, accent: '#94a3b8', icon: '?' };
    const errMsg = data.error || (intake.data && intake.data.error);

    const actions = this._availableActions(intake);

    panel.innerHTML = `
      <button class="pp-detail-close" data-pp-close>×</button>

      <div class="pp-detail-head">
        <div class="pp-avatar" style="background:${color};">${this._escape(initial)}</div>
        <div>
          <div class="pp-detail-name">${this._escape(name)}</div>
          <div class="pp-detail-sub">${this._escape(email)}${phone ? ' · ' + this._escape(phone) : ''}</div>
          <span class="pp-detail-pill" style="background:${col.accent}25; color:${col.accent};">${col.icon} ${this._escape(col.label)}</span>
        </div>
      </div>

      ${errMsg ? `<div class="pp-detail-section"><div class="pp-error-box">⚠ ${this._escape(errMsg)}</div></div>` : ''}

      <div class="pp-detail-section">
        <div class="pp-detail-section-title">Actions</div>
        <div class="pp-actions">${actions.join('')}</div>
      </div>

      ${intake.site_url ? `
        <div class="pp-detail-section">
          <div class="pp-detail-section-title">Site en ligne</div>
          <a class="pp-detail-link" href="${this._escape(intake.site_url)}" target="_blank" rel="noopener">${this._escape(intake.site_url)} →</a>
        </div>` : ''}

      <div class="pp-detail-section">
        <div class="pp-detail-section-title">Chronologie</div>
        <div class="pp-timeline">
          ${(timeline || []).map(ev => `
            <div class="pp-timeline-event ${ev.kind === 'current' ? 'current' : ''}">
              <div class="ts">${this._fmtDate(ev.ts)}</div>
              <div class="lbl">${this._escape(ev.label)}</div>
            </div>
          `).join('')}
        </div>
      </div>

      ${intake.stripe_session_id ? `
        <div class="pp-detail-section">
          <div class="pp-detail-section-title">Stripe</div>
          <div style="font-size:12px; color:#94a3b8;">Session : <code style="color:#cbd5e1;">${this._escape(intake.stripe_session_id)}</code></div>
        </div>` : ''}

      <div class="pp-detail-section">
        <div class="pp-detail-section-title">Données du formulaire</div>
        <details>
          <summary class="pp-data-toggle">Voir le JSON brut (${Object.keys(data).length} champs)</summary>
          <pre class="pp-data-pre">${this._escape(JSON.stringify(data, null, 2))}</pre>
        </details>
      </div>
    `;

    panel.querySelector('[data-pp-close]').onclick = () => this._closeDetail();
    panel.querySelectorAll('[data-pp-action]').forEach(b => {
      b.onclick = () => this._doAction(b.dataset.ppAction, intake);
    });
  },

  _availableActions(intake) {
    const out = [];
    const st = intake.status;
    // Pour un formulaire pas (encore) payé : override manuel possible
    // pour tester, encaisser hors-Stripe ou faire un geste commercial.
    if (st === 'draft') {
      out.push(`<button data-pp-action="force_build" class="pp-action-btn primary">▶ Lancer la construction tout de suite</button>`);
      out.push(`<button data-pp-action="mark_paid_manual" class="pp-action-btn secondary">💳 Marquer comme payé (sans construire)</button>`);
    }
    if (st === 'paid' || st === 'failed' || st === 'building' || st === 'live') {
      const label = st === 'paid'   ? '▶ Lancer la construction'
                  : st === 'failed' ? '↻ Relancer la construction'
                  : st === 'live'   ? '↻ Reconstruire le site'
                  : '↻ Forcer une nouvelle tentative';
      out.push(`<button data-pp-action="dispatch" class="pp-action-btn primary">${label}</button>`);
    }
    if (st === 'building' || st === 'paid') {
      out.push(`<button data-pp-action="mark_failed" class="pp-action-btn danger">Marquer comme échec</button>`);
    }
    if (st !== 'draft') {
      out.push(`<button data-pp-action="resend_paid_mail" class="pp-action-btn secondary">📧 Renvoyer mail "paiement reçu"</button>`);
    }
    if (st === 'live') {
      out.push(`<button data-pp-action="resend_live_mail" class="pp-action-btn secondary">📧 Renvoyer mail "site en ligne"</button>`);
    }
    out.push(`<button data-pp-action="delete" class="pp-action-btn danger">🗑 Supprimer définitivement</button>`);
    return out;
  },

  async _doAction(action, intake) {
    const id = intake.id;
    let res = null;
    switch (action) {
      case 'mark_paid_manual': {
        const data = intake.data || {};
        const name = data.business_name || data['business-name'] || '(sans nom)';
        const ok = confirm(
          `Marquer ce formulaire comme payé manuellement ?\n\n` +
          `  ${name}\n\n` +
          `Le client passera dans la colonne "Payés". Aucun mail ne lui sera envoyé automatiquement — ` +
          `tu pourras le faire à la main depuis le panneau de détail si tu veux.`
        );
        if (!ok) return;
        res = await this._call('pixelpros_mark_paid_manual', { id });
        this._toast(res?.ok ? `Marqué comme payé : ${res.message || ''}` : `Échec : ${res?.error || res?.message || '?'}`, !res?.ok);
        break;
      }
      case 'force_build': {
        const data = intake.data || {};
        const name = data.business_name || data['business-name'] || '(sans nom)';
        const ok = confirm(
          `Construire le site MAINTENANT (sans attendre le paiement) ?\n\n` +
          `  ${name}\n\n` +
          `Le statut va passer en "Payé" puis "En construction". Le site sera en ligne dans 1-2 min.\n\n` +
          `À utiliser pour tester, encaisser hors-Stripe ou faire un geste commercial.`
        );
        if (!ok) return;
        // Étape 1 : marquer payé manuellement
        const r1 = await this._call('pixelpros_mark_paid_manual', { id });
        if (!r1 || !r1.ok) {
          this._toast(`Échec marquage payé : ${r1?.error || r1?.message || '?'}`, true);
          break;
        }
        // Étape 2 : lancer le build
        res = await this._call('pixelpros_dispatch_build', { id });
        this._toast(res?.ok ? `Build lancé : ${res.message || ''}` : `Échec build : ${res?.error || res?.message || '?'}`, !res?.ok);
        break;
      }
      case 'dispatch':
        res = await this._call('pixelpros_dispatch_build', { id });
        this._toast(res?.ok ? `Build lancé : ${res.message || ''}` : `Échec : ${res?.error || res?.message || '?'}`, !res?.ok);
        break;
      case 'mark_failed': {
        const reason = prompt('Raison de l\'échec (optionnel) :', '');
        if (reason === null) return;
        res = await this._call('pixelpros_mark_failed', { id, reason });
        this._toast(res?.ok ? 'Marqué comme échec' : `Échec : ${res?.error || '?'}`, !res?.ok);
        break;
      }
      case 'resend_paid_mail':
        res = await this._call('pixelpros_resend_paid_mail', { id });
        this._toast(res?.ok ? `Mail "paiement reçu" envoyé : ${res.message || ''}` : `Échec : ${res?.error || res?.message || '?'}`, !res?.ok);
        break;
      case 'resend_live_mail':
        res = await this._call('pixelpros_resend_live_mail', { id });
        this._toast(res?.ok ? `Mail "site en ligne" envoyé : ${res.message || ''}` : `Échec : ${res?.error || res?.message || '?'}`, !res?.ok);
        break;
      case 'delete': {
        const data = intake.data || {};
        const name = data.business_name || data['business-name'] || '(sans nom)';
        const status = intake.status || '?';
        const warn = status === 'live'
          ? `⚠ Ce formulaire est en statut "en ligne" (site déployé).\nLe supprimer perd l'historique mais NE FERME PAS le site en ligne (à faire séparément).\n\n`
          : '';
        const ok = confirm(`${warn}Supprimer définitivement ce formulaire ?\n\n  ${name}\n  Statut : ${status}\n\nCette action est irréversible.`);
        if (!ok) return;
        res = await this._call('pixelpros_delete_intake', { id });
        this._toast(res?.ok ? `Supprimé : ${res.message || ''}` : `Échec : ${res?.error || res?.message || '?'}`, !res?.ok);
        if (res?.ok) this._closeDetail();
        break;
      }
    }
    await this.refresh();
  },

  // ----- HELPERS -----
  async _call(method, payload) {
    if (!App || !App.api || typeof App.api[method] !== 'function') {
      console.warn(`pixelpros: API.${method} introuvable`);
      return { ok: false, error: 'API absente' };
    }
    try { return await App.api[method](payload); }
    catch (e) { console.warn('pixelpros._call', method, e); return { ok: false, error: String(e) }; }
  },

  _hoursSince(ts) {
    if (!ts) return 0;
    try {
      const d = new Date(ts);
      if (isNaN(d.getTime())) return 0;
      return (Date.now() - d.getTime()) / 36e5;
    } catch { return 0; }
  },

  _timeRelative(ts) {
    if (!ts) return '—';
    const h = this._hoursSince(ts);
    if (h < 1)   return `il y a ${Math.max(1, Math.round(h * 60))} min`;
    if (h < 24)  return `il y a ${Math.round(h)} h`;
    const d = Math.round(h / 24);
    if (d < 30) return `il y a ${d} j`;
    return this._fmtDate(ts);
  },

  _fmtDate(s) {
    if (!s) return '—';
    try {
      const d = new Date(s);
      if (isNaN(d.getTime())) return s;
      return d.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', year: '2-digit' }) +
             ' ' + d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
    } catch { return s; }
  },

  _colorFromName(name) {
    // Palette pastel cohérente, hash simple sur le nom.
    const palette = ['#facc15', '#22c55e', '#0ea5e9', '#a855f7', '#ec4899', '#f97316', '#14b8a6', '#f43f5e'];
    let h = 0;
    const s = String(name || '');
    for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
    return palette[Math.abs(h) % palette.length];
  },

  _escape(s) {
    return String(s ?? '').replace(/[&<>"']/g, ch => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[ch]));
  },

  _toast(msg, isError = false) {
    const t = document.createElement('div');
    t.textContent = msg;
    t.className = `pp-toast ${isError ? 'err' : 'ok'}`;
    document.body.appendChild(t);
    setTimeout(() => { t.style.opacity = '0'; t.style.transition = 'opacity .3s'; }, 2800);
    setTimeout(() => t.remove(), 3200);
  },
};
