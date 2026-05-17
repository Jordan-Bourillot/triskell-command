/* Mail Templates — éditeur de modèles mail (vue Triskell Command).
 *
 * Lit / écrit la table Supabase `triskell_email_templates` via l'API
 * `mail_templates_*`. Permet à Jordan d'éditer sujets, expéditeurs et
 * corps HTML de chaque mail transactionnel sans toucher au code.
 *
 * Si un template n'existe pas (ou est désactivé), la Netlify Function
 * appelante retombe automatiquement sur son fallback hardcodé — donc
 * désactiver un template ne casse rien.
 *
 * Catalogue des templates connus (par défaut, pour proposer la création
 * de nouveaux templates même quand la base est vide). Doit rester aligné
 * avec ce que les fonctions Netlify lisent réellement.
 */

const MailTemplates = {
  _state: {
    products: {},     // { lagriffe: { label, templates: [...] }, … }
    selected: null,   // { product, key } courant
    editing: null,    // copie de travail (jamais persistée tant qu'on clique pas Enregistrer)
    busy: false,
    catalog: null,    // fusion base + catalogue connu
  },

  // Catalogue de référence — pour que l'éditeur propose toujours les bons
  // templates même si la base est vide / partielle. À enrichir au fil des
  // refontes côté Netlify.
  KNOWN: [
    // Lagriffe
    { product: 'lagriffe', key: 'reminder_j2', label: 'Relance J+2 (rappel doux)',
      description: 'Envoyée 2 jours après l\'invitation à personnaliser, si le client n\'a rien fait.',
      placeholders: ['first_name', 'customize_url', 'mockup_url', 'company_name'] },
    { product: 'lagriffe', key: 'reminder_j5', label: 'Relance J+5 (on est là)',
      description: 'Envoyée à J+5, ton chaleureux, on propose de l\'aide.',
      placeholders: ['first_name', 'customize_url', 'mockup_url', 'company_name'] },
    { product: 'lagriffe', key: 'reminder_j10', label: 'Relance J+10 (dernière chance)',
      description: 'Envoyée à J+10, dernier rappel avant archivage à J+14.',
      placeholders: ['first_name', 'customize_url', 'mockup_url', 'company_name'] },
  ],

  // ---------- API ----------
  async _api(method, payload) {
    if (!App.api) return null;
    const fn = App.api['mail_templates_' + method];
    if (typeof fn !== 'function') return null;
    try { return await fn(payload || {}); }
    catch (e) { console.warn('mail_templates.' + method, e); return null; }
  },

  // ---------- Render ----------
  async render(container) {
    this._root = container;
    container.innerHTML = `
      <section class="animate-slide-up">
        <div class="mb-6 flex items-end justify-between">
          <div>
            <div class="hero-kicker mb-2">MODÈLES MAILS</div>
            <h1 class="hero-title mb-3" style="font-size: 36px;">Le ton de tes mails, en un clic.</h1>
            <p class="hero-subtitle">
              Chaque mail envoyé par tes sites (relances, bienvenues, finalisations) est éditable
              ici. Sujet, expéditeur, corps HTML — tu ajustes le ton sans toucher au code.
            </p>
          </div>
          <button id="mt-refresh" class="btn btn-secondary">Rafraîchir</button>
        </div>

        <div id="mt-banner" class="mb-4 text-[12px] text-text-muted"></div>

        <div class="grid grid-cols-1 lg:grid-cols-[320px_1fr] gap-4">
          <aside id="mt-list" class="bg-card border border-border rounded-xl p-3 overflow-y-auto" style="max-height: calc(100vh - 220px);"></aside>
          <main  id="mt-editor" class="bg-card border border-border rounded-xl p-6 min-h-[500px]"></main>
        </div>
      </section>
    `;
    this._injectStyles();
    document.getElementById('mt-refresh').onclick = () => this.refresh();
    await this.refresh();
  },

  _injectStyles() {
    if (document.getElementById('mt-styles')) return;
    const s = document.createElement('style');
    s.id = 'mt-styles';
    s.textContent = `
      .mt-product-h {
        font-size: 10px; letter-spacing: .14em; text-transform: uppercase;
        font-weight: 700; color: hsl(var(--text-muted));
        padding: 10px 8px 6px;
      }
      .mt-row {
        display: block; width: 100%; text-align: left;
        padding: 10px 12px; border-radius: 8px;
        font-size: 13px; line-height: 1.3;
        color: hsl(var(--text));
        transition: background 120ms, color 120ms;
      }
      .mt-row:hover { background: hsl(var(--bg)); }
      .mt-row.is-active { background: hsl(var(--accent) / .12); color: hsl(var(--accent)); font-weight: 600; }
      .mt-row .mt-row-sub { font-size: 11px; color: hsl(var(--text-muted)); margin-top: 2px; }
      .mt-row.is-active .mt-row-sub { color: hsl(var(--accent) / .75); }
      .mt-row .mt-pill {
        display: inline-block; padding: 1px 6px; border-radius: 4px; font-size: 9.5px;
        font-weight: 700; letter-spacing: .04em; text-transform: uppercase;
        background: hsl(var(--warning) / .15); color: hsl(var(--warning));
        margin-left: 6px; vertical-align: middle;
      }
      .mt-row .mt-pill-on { background: hsl(var(--success) / .15); color: hsl(var(--success)); }
      .mt-row .mt-pill-off { background: hsl(var(--text-muted) / .2); color: hsl(var(--text-muted)); }
      .mt-field { display: block; margin-bottom: 16px; }
      .mt-field > label {
        display: block; font-size: 11px; font-weight: 700;
        letter-spacing: .1em; text-transform: uppercase;
        color: hsl(var(--text-muted)); margin-bottom: 6px;
      }
      .mt-field input, .mt-field textarea, .mt-field select {
        width: 100%; padding: 9px 12px; border-radius: 7px;
        background: hsl(var(--bg)); color: hsl(var(--text));
        border: 1px solid hsl(var(--border));
        font-size: 13px; line-height: 1.5;
        font-family: inherit;
      }
      .mt-field textarea { resize: vertical; min-height: 240px; font-family: ui-monospace, "SF Mono", Consolas, monospace; font-size: 12.5px; }
      .mt-field input:focus, .mt-field textarea:focus, .mt-field select:focus {
        outline: none; border-color: hsl(var(--accent));
        box-shadow: 0 0 0 3px hsl(var(--accent) / .12);
      }
      .mt-placeholder-chip {
        display: inline-block; padding: 3px 8px; margin: 0 4px 4px 0;
        font-size: 11px; font-family: ui-monospace, "SF Mono", Consolas, monospace;
        background: hsl(var(--accent) / .1); color: hsl(var(--accent));
        border-radius: 4px; cursor: pointer; border: 1px dashed hsl(var(--accent) / .3);
        transition: background 120ms;
      }
      .mt-placeholder-chip:hover { background: hsl(var(--accent) / .2); }
      .mt-toolbar { display: flex; gap: 8px; align-items: center; margin-top: 16px; padding-top: 16px; border-top: 1px solid hsl(var(--border)); }
      .mt-toolbar .grow { flex: 1; }
      .mt-preview-frame {
        width: 100%; height: 520px; border: 1px solid hsl(var(--border));
        border-radius: 8px; background: white;
      }
      .mt-tabs { display: flex; gap: 4px; margin-bottom: 12px; border-bottom: 1px solid hsl(var(--border)); }
      .mt-tab {
        padding: 8px 14px; font-size: 12px; font-weight: 600;
        color: hsl(var(--text-muted)); border-bottom: 2px solid transparent;
        transition: color 120ms, border-color 120ms;
      }
      .mt-tab.is-active { color: hsl(var(--accent)); border-bottom-color: hsl(var(--accent)); }
    `;
    document.head.appendChild(s);
  },

  async refresh() {
    this._state.busy = true;
    const list = document.getElementById('mt-list');
    list.innerHTML = '<div class="p-4 text-[12px] text-text-muted">Chargement…</div>';
    const banner = document.getElementById('mt-banner');

    const res = await this._api('list');
    if (!res || !res.ok) {
      banner.innerHTML = `<span class="text-danger">Impossible de charger les templates : ${res && res.error ? res.error : 'erreur inconnue'}.</span>`;
      this._state.products = {};
    } else {
      this._state.products = res.products || {};
      banner.innerHTML = `Templates synchronisés avec Supabase. Les mails non listés utilisent encore leur version codée en dur — clique sur un template ci-contre pour l'éditer.`;
    }

    this._state.catalog = this._buildCatalog();
    this._renderList();

    // Auto-select : premier template, ou celui qui était déjà ouvert
    let target = this._state.selected;
    if (!target) {
      // priorité : premier "real" (en base), sinon premier "known"
      for (const p of Object.keys(this._state.catalog)) {
        const t = this._state.catalog[p].templates[0];
        if (t) { target = { product: p, key: t.key }; break; }
      }
    }
    if (target) this.openTemplate(target.product, target.key);
    else this._renderEmptyEditor();

    this._state.busy = false;
  },

  // Fusionne les templates en base avec ceux du catalogue connu, en
  // marquant ceux qui n'existent pas encore (statut "fallback hardcodé").
  _buildCatalog() {
    const out = {};
    // 1) Tous les produits connus, dans l'ordre fixe (lagriffe d'abord)
    const ORDER = ['lagriffe', 'rankus', 'wow', 'shared'];
    const LABELS = {
      lagriffe: 'Lagriffe Studio',
      rankus:   'RankUs Studio',
      wow:      'Studio WoW',
      shared:   'Triskell (transversal)',
    };
    for (const p of ORDER) {
      out[p] = { label: LABELS[p] || p, templates: [] };
    }
    // 2) Ajoute les templates depuis la base
    const dbKeys = new Set();
    for (const [p, info] of Object.entries(this._state.products || {})) {
      if (!out[p]) out[p] = { label: info.label || p, templates: [] };
      for (const t of info.templates || []) {
        dbKeys.add(`${p}::${t.key}`);
        out[p].templates.push({ ...t, _source: 'db' });
      }
    }
    // 3) Ajoute les templates "connus" pas encore créés en base
    for (const k of this.KNOWN) {
      if (!dbKeys.has(`${k.product}::${k.key}`)) {
        if (!out[k.product]) out[k.product] = { label: LABELS[k.product] || k.product, templates: [] };
        out[k.product].templates.push({
          product: k.product, key: k.key,
          subject: '(template par défaut — pas encore édité)',
          description: k.description, placeholders: k.placeholders,
          enabled: true, _source: 'fallback', _label: k.label,
        });
      }
    }
    return out;
  },

  _renderList() {
    const list = document.getElementById('mt-list');
    const cat = this._state.catalog;
    let html = '';
    for (const [p, info] of Object.entries(cat)) {
      if (!info.templates || info.templates.length === 0) continue;
      html += `<div class="mt-product-h">${this._esc(info.label)}</div>`;
      for (const t of info.templates) {
        const isActive = this._state.selected && this._state.selected.product === p && this._state.selected.key === t.key;
        const label = t._label || this._humanKey(t.key);
        let pill = '';
        if (t._source === 'fallback') {
          pill = '<span class="mt-pill">Code dur</span>';
        } else if (t.enabled === false) {
          pill = '<span class="mt-pill mt-pill-off">Off</span>';
        } else {
          pill = '<span class="mt-pill mt-pill-on">Édité</span>';
        }
        html += `
          <button class="mt-row ${isActive ? 'is-active' : ''}"
                  data-mt-open="${this._esc(p)}::${this._esc(t.key)}">
            <div>${this._esc(label)}${pill}</div>
            <div class="mt-row-sub">${this._esc(t.subject || '').slice(0, 80)}</div>
          </button>
        `;
      }
    }
    list.innerHTML = html || '<div class="p-4 text-[12px] text-text-muted">Aucun template pour l\'instant.</div>';
    list.querySelectorAll('[data-mt-open]').forEach(btn => {
      btn.onclick = () => {
        const [p, k] = btn.dataset.mtOpen.split('::');
        this.openTemplate(p, k);
      };
    });
  },

  // ---------- Open / edit ----------
  async openTemplate(product, key) {
    this._state.selected = { product, key };
    this._renderList();
    this._renderEditor({ loading: true });

    // Charge depuis la base
    const res = await this._api('get', { product, key });
    let tpl;
    if (res && res.ok && res.template) {
      tpl = res.template;
    } else {
      // Pas en base : template "à créer". Pré-rempli depuis le catalogue connu.
      const known = this.KNOWN.find(k => k.product === product && k.key === key) || {};
      tpl = {
        product, key,
        from_address: 'noreply@triskell-studio.fr',
        from_name: this._defaultFromName(product),
        subject: '',
        body_html: '',
        body_text: '',
        description: known.description || '',
        placeholders: known.placeholders || [],
        enabled: true,
        _isNew: true,
      };
    }
    this._state.editing = JSON.parse(JSON.stringify(tpl));
    this._renderEditor({});
  },

  _renderEmptyEditor() {
    const e = document.getElementById('mt-editor');
    e.innerHTML = `<div class="p-8 text-center text-text-muted text-sm">
      Sélectionne un modèle dans la colonne de gauche pour l'éditer.
    </div>`;
  },

  _renderEditor({ loading } = {}) {
    const e = document.getElementById('mt-editor');
    if (loading) {
      e.innerHTML = '<div class="p-8 text-center text-text-muted text-sm">Chargement du modèle…</div>';
      return;
    }
    const t = this._state.editing;
    if (!t) { this._renderEmptyEditor(); return; }

    const isNew = !!t._isNew;
    const placeholders = Array.isArray(t.placeholders) ? t.placeholders : [];
    const productLabel = (this._state.catalog[t.product] && this._state.catalog[t.product].label) || t.product;

    e.innerHTML = `
      <div class="mb-5 pb-4 border-b border-border">
        <div class="hero-kicker mb-1">${this._esc(productLabel)} · ${this._esc(t.key)}</div>
        <h2 class="text-xl font-bold">${this._esc(this._humanKey(t.key))}</h2>
        ${t.description ? `<p class="text-sm text-text-muted mt-2 leading-relaxed">${this._esc(t.description)}</p>` : ''}
        ${isNew ? '<div class="mt-3 text-[12px] text-warning bg-warning/10 border border-warning/30 rounded px-3 py-2">Ce modèle n\'a jamais été édité. Aujourd\'hui la fonction utilise sa version <strong>codée en dur</strong>. Modifie le sujet/corps ci-dessous puis enregistre pour reprendre la main.</div>' : ''}
      </div>

      <div class="mt-tabs">
        <button class="mt-tab is-active" data-mt-pane="edit">Édition</button>
        <button class="mt-tab" data-mt-pane="preview">Aperçu</button>
      </div>

      <div id="mt-pane-edit">
        <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
          <label class="mt-field">
            <label>Expéditeur (nom)</label>
            <input id="mt-from-name" value="${this._esc(t.from_name || '')}" placeholder="Lagriffe Studio">
          </label>
          <label class="mt-field">
            <label>Expéditeur (adresse)</label>
            <input id="mt-from-address" value="${this._esc(t.from_address || '')}" placeholder="noreply@triskell-studio.fr">
          </label>
        </div>

        <div class="mt-field">
          <label>Sujet du mail</label>
          <input id="mt-subject" value="${this._esc(t.subject || '')}" placeholder="Votre maquette Lagriffe Studio vous attend">
        </div>

        ${placeholders.length ? `
          <div class="mb-3">
            <div class="text-[11px] font-bold tracking-wider uppercase text-text-muted mb-2">Variables disponibles · clique pour insérer</div>
            <div>${placeholders.map(p => `<span class="mt-placeholder-chip" data-mt-insert="{{${this._esc(p)}}}">{{${this._esc(p)}}}</span>`).join('')}</div>
          </div>
        ` : ''}

        <div class="mt-field">
          <div class="flex items-center justify-between gap-2 flex-wrap mb-1">
            <label style="margin:0; padding:0;">Corps HTML</label>
            <button id="mt-insert-product" type="button"
                    class="px-2.5 py-1 rounded-lg text-[11px] font-semibold border border-border text-text-muted hover:border-accent hover:text-accent transition-colors"
                    title="Insérer un produit du Catalogue Triskell">
              + Produit du Catalogue
            </button>
          </div>
          <textarea id="mt-body-html" spellcheck="false" placeholder="<p>Bonjour {{first_name}},</p>…">${this._esc(t.body_html || '')}</textarea>
        </div>

        <div class="mt-field">
          <label>Corps texte (optionnel, fallback)</label>
          <textarea id="mt-body-text" spellcheck="false" style="min-height: 100px;" placeholder="Version texte brut, pour les clients mail qui ne lisent pas HTML.">${this._esc(t.body_text || '')}</textarea>
        </div>

        <div class="mt-field">
          <label style="display:flex; align-items:center; gap:8px; text-transform: none; letter-spacing: 0; font-size: 13px; color: hsl(var(--text)); font-weight: 500;">
            <input type="checkbox" id="mt-enabled" ${t.enabled !== false ? 'checked' : ''} style="width:auto;">
            <span>Modèle actif <span class="text-text-muted">— si décoché, la fonction Netlify retombe sur sa version codée en dur.</span></span>
          </label>
        </div>

        <div class="mt-toolbar">
          <div class="grow text-[11px] text-text-muted">
            ${t.updated_at ? `Dernière modif&nbsp;: ${this._formatDate(t.updated_at)}${t.updated_by ? ` par ${this._esc(t.updated_by)}` : ''}` : ''}
          </div>
          ${!isNew ? `<button id="mt-delete" class="btn btn-ghost text-danger">Supprimer</button>` : ''}
          <button id="mt-save" class="btn btn-primary">Enregistrer</button>
        </div>
      </div>

      <div id="mt-pane-preview" style="display:none;">
        <iframe id="mt-preview-iframe" class="mt-preview-frame" sandbox=""></iframe>
        <p class="text-[11px] text-text-muted mt-3">Les variables <code>{{…}}</code> sont remplacées par des valeurs d'exemple ci-dessus.</p>
      </div>
    `;

    // Binds
    e.querySelectorAll('[data-mt-pane]').forEach(b => b.onclick = () => this._switchPane(b.dataset.mtPane));
    e.querySelectorAll('[data-mt-insert]').forEach(c => c.onclick = () => this._insertPlaceholder(c.dataset.mtInsert));
    const prodBtn = document.getElementById('mt-insert-product');
    if (prodBtn && typeof Catalogue !== 'undefined') {
      prodBtn.onclick = () => {
        Catalogue.pickProduct((product) => {
          if (!product) return;
          this._insertPlaceholder(Catalogue.snippetHtml(product));
        });
      };
    }
    document.getElementById('mt-save').onclick = () => this.save();
    const delBtn = document.getElementById('mt-delete');
    if (delBtn) delBtn.onclick = () => this.deleteCurrent();
  },

  _switchPane(name) {
    document.querySelectorAll('[data-mt-pane]').forEach(b => b.classList.toggle('is-active', b.dataset.mtPane === name));
    document.getElementById('mt-pane-edit').style.display    = (name === 'edit')    ? '' : 'none';
    document.getElementById('mt-pane-preview').style.display = (name === 'preview') ? '' : 'none';
    if (name === 'preview') this._renderPreview();
  },

  _renderPreview() {
    const subject = (document.getElementById('mt-subject') || {}).value || '';
    const body    = (document.getElementById('mt-body-html') || {}).value || '';
    const sample = this._samplePlaceholders(this._state.editing);
    const subj = this._fillPlaceholders(subject, sample);
    const html = this._fillPlaceholders(body, sample);
    const iframe = document.getElementById('mt-preview-iframe');
    const doc = `<!doctype html><html><head><meta charset="utf-8"><title>${this._esc(subj)}</title><style>body{font-family:'Inter',-apple-system,sans-serif;margin:0;padding:24px;background:#FAFAF8;color:#0A0E0C;}</style></head><body>${html}</body></html>`;
    iframe.srcdoc = doc;
  },

  _insertPlaceholder(text) {
    const ta = document.getElementById('mt-body-html');
    if (!ta) return;
    const start = ta.selectionStart || 0;
    const end = ta.selectionEnd || 0;
    ta.value = ta.value.slice(0, start) + text + ta.value.slice(end);
    ta.focus();
    ta.selectionStart = ta.selectionEnd = start + text.length;
  },

  // ---------- Save / delete ----------
  async save() {
    const t = this._state.editing;
    if (!t) return;
    const fields = {
      from_name:    document.getElementById('mt-from-name').value.trim(),
      from_address: document.getElementById('mt-from-address').value.trim(),
      subject:      document.getElementById('mt-subject').value,
      body_html:    document.getElementById('mt-body-html').value,
      body_text:    document.getElementById('mt-body-text').value,
      enabled:      document.getElementById('mt-enabled').checked,
      placeholders: Array.isArray(t.placeholders) ? t.placeholders : [],
      description:  t.description || '',
    };
    if (!fields.subject) {
      alert('Le sujet du mail est obligatoire.');
      return;
    }
    if (!fields.from_address) {
      alert('L\'adresse d\'expéditeur est obligatoire.');
      return;
    }
    const btn = document.getElementById('mt-save');
    if (btn) { btn.disabled = true; btn.textContent = 'Enregistrement…'; }
    const res = await this._api('save', { product: t.product, key: t.key, fields });
    if (btn) { btn.disabled = false; btn.textContent = 'Enregistrer'; }
    if (!res || !res.ok) {
      alert('Échec de l\'enregistrement : ' + (res && res.error || 'erreur inconnue'));
      return;
    }
    // Toast léger
    this._toast('Modèle enregistré. Effet immédiat (cache 60 s max côté Netlify).');
    // Recharge la liste pour mettre à jour les pills "Édité"
    await this.refresh();
  },

  async deleteCurrent() {
    const t = this._state.editing;
    if (!t) return;
    if (!confirm('Supprimer ce modèle ? La fonction Netlify retombera sur sa version codée en dur.')) return;
    const res = await this._api('delete', { product: t.product, key: t.key });
    if (!res || !res.ok) {
      alert('Échec : ' + (res && res.error || 'erreur inconnue'));
      return;
    }
    this._toast('Modèle supprimé.');
    this._state.selected = null;
    this._state.editing = null;
    await this.refresh();
  },

  // ---------- Utils ----------
  _samplePlaceholders(t) {
    const samples = {
      first_name: 'Jordan',
      last_name: 'Bourillot',
      company_name: 'Atelier du Tertre',
      customize_url: 'https://lagriffe-studio.fr/personnaliser?id=xxx',
      mockup_url:    'https://maquette.exemple.fr',
      site_url:      'https://votre-site.fr',
      final_site_url:'https://votre-site.fr',
      amount:        '49',
      currency:      'EUR',
      email:         'client@exemple.fr',
    };
    return samples;
  },
  _fillPlaceholders(str, vars) {
    return String(str || '').replace(/\{\{\s*([a-zA-Z0-9_]+)\s*\}\}/g, (_, n) => (vars[n] !== undefined ? String(vars[n]) : `{{${n}}}`));
  },
  _defaultFromName(product) {
    return ({ lagriffe: 'Lagriffe Studio', rankus: 'RankUs Studio', wow: 'Studio WoW', shared: 'Triskell Studio' })[product] || 'Triskell Studio';
  },
  _humanKey(k) {
    return String(k || '')
      .replace(/_/g, ' ')
      .replace(/\bj(\d+)\b/g, 'J+$1')
      .replace(/\b\w/g, c => c.toUpperCase());
  },
  _formatDate(iso) {
    try {
      const d = new Date(iso);
      return d.toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' });
    } catch { return iso; }
  },
  _esc(s) {
    return String(s ?? '')
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  },
  _toast(msg) {
    let el = document.getElementById('mt-toast');
    if (!el) {
      el = document.createElement('div');
      el.id = 'mt-toast';
      el.style.cssText = 'position:fixed;bottom:20px;right:20px;background:hsl(var(--accent));color:white;padding:10px 16px;border-radius:8px;font-size:13px;font-weight:600;box-shadow:0 6px 24px rgba(0,0,0,.18);z-index:9999;opacity:0;transition:opacity 180ms;';
      document.body.appendChild(el);
    }
    el.textContent = msg;
    requestAnimationFrame(() => { el.style.opacity = '1'; });
    clearTimeout(this._toastTimer);
    this._toastTimer = setTimeout(() => { el.style.opacity = '0'; }, 2800);
  },
};

window.MailTemplates = MailTemplates;
