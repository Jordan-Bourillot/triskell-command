/* Vue Brain — boîte à idées partagée Jordan/Thomas.
 *
 * Liste les notes "open" groupées par catégorie. Bouton "+ Nouvelle note"
 * pour ajouter (Claude analyse derrière : catégorie, tags, rappel).
 * Clic sur une note → modale détail (réponses, marquer fait, archiver, supprimer).
 *
 * Synchronisé avec command-voice mobile via la table Supabase
 * `command_voice_brain` (les notes mobiles apparaissent ici et inversement).
 */

const Brain = {
  state: {
    groups: [],
    showArchived: false,
    showDone: false,
  },

  async render(container) {
    container.innerHTML = `
      <section class="animate-slide-up">
        <div class="mb-6 flex items-end justify-between flex-wrap gap-3">
          <div>
            <div class="hero-kicker mb-2">BRAIN</div>
            <h1 class="hero-title mb-3" style="font-size: 36px;">Vide ton cerveau ici.</h1>
            <p class="hero-subtitle">Idées, tâches, infos en vrac. Claude classe et te rappelle au bon moment. Partagé avec Thomas.</p>
          </div>
          <div class="flex gap-2">
            <button id="b-new" class="btn btn-primary">
              <svg class="w-4 h-4 mr-1.5 inline" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>
              Nouvelle note
            </button>
            <button id="b-refresh" class="btn btn-secondary">Rafraîchir</button>
          </div>
        </div>

        <div class="flex gap-2 mb-5 text-[11px]">
          <button data-bfilter="open"     class="b-filter is-active">À traiter</button>
          <button data-bfilter="done"     class="b-filter">Fait</button>
          <button data-bfilter="archived" class="b-filter">Archivé</button>
        </div>

        <div id="b-content"></div>
      </section>
    `;
    this._injectStyles();
    document.getElementById('b-refresh').onclick = () => this._load();
    document.getElementById('b-new').onclick = () => this._openNew();
    document.querySelectorAll('[data-bfilter]').forEach(btn => {
      btn.onclick = () => this._switchFilter(btn.dataset.bfilter);
    });
    await this._load();
  },

  _injectStyles() {
    if (document.getElementById('b-styles')) return;
    const s = document.createElement('style');
    s.id = 'b-styles';
    s.textContent = `
      .b-filter { padding: 6px 14px; border-radius: 99px; font-weight: 600;
                  color: hsl(var(--text-muted));
                  border: 1px solid hsl(var(--border));
                  transition: all 160ms; }
      .b-filter:hover { color: hsl(var(--text)); border-color: hsl(var(--accent)); }
      .b-filter.is-active { color: white; background: hsl(var(--accent));
                            border-color: hsl(var(--accent)); }
      .b-cat-header { font-size: 11px; font-weight: 700; letter-spacing: 0.1em;
                      text-transform: uppercase; color: hsl(var(--text-muted)); }
      .b-note { transition: border-color 160ms, transform 160ms; cursor: pointer; }
      .b-note:hover { border-color: hsl(var(--accent)); transform: translateY(-1px); }
      .b-tag { display: inline-block; padding: 1px 7px; border-radius: 999px;
               font-size: 10px; font-weight: 600;
               background: hsl(var(--accent) / 0.12); color: hsl(var(--accent)); }
      .b-author { font-size: 9px; font-weight: 700; padding: 1px 5px;
                  border-radius: 4px; text-transform: uppercase; letter-spacing: 0.05em; }
      .b-author.jordan { background: hsl(var(--accent) / 0.15); color: hsl(var(--accent)); }
      .b-author.thomas { background: hsl(var(--success) / 0.15); color: hsl(var(--success)); }
    `;
    document.head.appendChild(s);
  },

  _switchFilter(f) {
    this.currentFilter = f;
    document.querySelectorAll('[data-bfilter]').forEach(b => {
      b.classList.toggle('is-active', b.dataset.bfilter === f);
    });
    this._load();
  },

  async _load() {
    const root = document.getElementById('b-content');
    if (!App.api) {
      root.innerHTML = `<div class="card p-6 text-text-muted">Backend indisponible.</div>`;
      return;
    }
    root.innerHTML = `<div class="card p-6 text-text-muted text-sm">Chargement…</div>`;
    const filter = this.currentFilter || 'open';
    try {
      if (filter === 'open') {
        const r = await App.api.brain_list_by_category();
        if (!r || !r.ok) {
          root.innerHTML = `<div class="card p-6 text-danger">${(r && r.error) || 'Erreur'}</div>`;
          return;
        }
        this.state.groups = r.groups || [];
        this._renderGrouped();
      } else {
        const r = await App.api.brain_list({ status: filter, limit: 100 });
        if (!r || !r.ok) {
          root.innerHTML = `<div class="card p-6 text-danger">${(r && r.error) || 'Erreur'}</div>`;
          return;
        }
        this._renderFlat(r.notes || []);
      }
    } catch (e) {
      root.innerHTML = `<div class="card p-6 text-danger">Erreur : ${e}</div>`;
    }
  },

  _renderGrouped() {
    const root = document.getElementById('b-content');
    if (!this.state.groups.length) {
      root.innerHTML = `
        <div class="card p-12 text-center">
          <div class="text-3xl mb-3 opacity-60">∅</div>
          <p class="text-text-muted">Aucune idée en cours.</p>
          <button class="btn btn-primary mt-4" onclick="Brain._openNew()">Lance-toi : ajoute ta première note</button>
        </div>
      `;
      return;
    }
    root.innerHTML = this.state.groups.map(g => `
      <div class="mb-6">
        <div class="flex items-baseline justify-between mb-3">
          <div class="b-cat-header">${this._escape(g.category)}</div>
          <div class="text-xs text-text-muted">${g.count} note${g.count > 1 ? 's' : ''}</div>
        </div>
        <div class="space-y-2">
          ${g.notes.map(n => this._renderNoteCard(n)).join('')}
        </div>
      </div>
    `).join('');
    this._bindCards();
  },

  _renderFlat(notes) {
    const root = document.getElementById('b-content');
    if (!notes.length) {
      root.innerHTML = `<div class="card p-12 text-center text-text-muted">Aucune note dans ce filtre.</div>`;
      return;
    }
    root.innerHTML = `<div class="space-y-2">${notes.map(n => this._renderNoteCard(n)).join('')}</div>`;
    this._bindCards();
  },

  _renderNoteCard(n) {
    const author = (n.author || 'jordan').toLowerCase();
    const tags = (n.tags || []).slice(0, 4);
    const remind = n.remind_at ? this._fmtDate(n.remind_at) : '';
    const replyCount = (n.replies || []).length;
    const summaryOrContent = n.summary || (n.content || '').slice(0, 200);
    return `
      <div class="card b-note p-4" data-bnote="${this._escape(n.id)}">
        <div class="flex items-start justify-between gap-3 mb-2">
          <div class="flex-1 min-w-0">
            <div class="text-sm leading-relaxed text-text whitespace-pre-wrap">${this._escape(summaryOrContent)}</div>
          </div>
          <span class="b-author ${author} shrink-0">${this._escape(author)}</span>
        </div>
        <div class="flex items-center gap-2 text-[11px] text-text-muted flex-wrap">
          ${tags.map(t => `<span class="b-tag">${this._escape(t)}</span>`).join('')}
          ${remind ? `<span>⏰ ${remind}</span>` : ''}
          ${replyCount > 0 ? `<span>💬 ${replyCount}</span>` : ''}
          ${n.assigned_to ? `<span>→ ${this._escape(n.assigned_to)}</span>` : ''}
          <span class="ml-auto">${this._fmtDate(n.created_at)}</span>
        </div>
      </div>
    `;
  },

  _bindCards() {
    document.querySelectorAll('[data-bnote]').forEach(el => {
      el.onclick = async () => {
        const id = el.dataset.bnote;
        const allNotes = this.state.groups.flatMap(g => g.notes);
        let n = allNotes.find(x => x.id === id);
        if (!n) {
          // re-fetch si pas en mémoire
          const r = await App.api.brain_list({ limit: 200 });
          if (r && r.ok) n = (r.notes || []).find(x => x.id === id);
        }
        if (n) this._openDetail(n);
      };
    });
  },

  // ----------------------------------------------------------------------
  // Modale "Nouvelle note"
  // ----------------------------------------------------------------------
  _openNew() {
    const overlay = document.createElement('div');
    overlay.className = 'fixed inset-0 z-[200] flex items-center justify-center p-4';
    overlay.style.background = 'rgba(15,23,42,0.7)';
    overlay.style.backdropFilter = 'blur(8px)';
    overlay.innerHTML = `
      <div class="bg-surface rounded-2xl shadow-hero w-full max-w-xl overflow-hidden border border-border animate-slide-up flex flex-col">
        <div class="px-6 pt-4 pb-3 border-b border-border bg-surface-elevated">
          <div class="hero-kicker mb-0.5">BRAIN</div>
          <h3 class="text-base font-bold">Nouvelle note</h3>
          <p class="text-xs text-text-muted mt-1">Tape ton idée, tâche, info. Claude classe automatiquement.</p>
        </div>
        <div class="px-6 py-5">
          <textarea id="bn-content" rows="6" autofocus
                    placeholder="Ex: Demander à Thomas si on garde Calendly. Lui répondre lundi.&#10;Ex: Idée produit : extension Chrome qui résume les vidéos YouTube."
                    class="w-full px-3 py-3 text-sm rounded-lg bg-bg border border-border focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent font-sans leading-relaxed resize-y"></textarea>
          <div id="bn-status" class="mt-2 text-xs text-text-muted">⌘+Entrée pour envoyer</div>
        </div>
        <div class="px-6 py-3 border-t border-border bg-surface-elevated flex justify-end gap-2">
          <button id="bn-cancel" class="btn btn-secondary">Annuler</button>
          <button id="bn-save"   class="btn btn-primary">Ajouter</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);
    const close = () => overlay.remove();
    overlay.querySelector('#bn-cancel').onclick = close;
    overlay.addEventListener('click', e => { if (e.target === overlay) close(); });
    const escListener = (e) => {
      if (e.key === 'Escape') { close(); document.removeEventListener('keydown', escListener); }
    };
    document.addEventListener('keydown', escListener);

    const save = async () => {
      const content = overlay.querySelector('#bn-content').value.trim();
      const status = overlay.querySelector('#bn-status');
      if (!content) {
        status.textContent = '✗ Vide.'; status.className = 'mt-2 text-xs text-danger'; return;
      }
      const btn = overlay.querySelector('#bn-save');
      btn.disabled = true;
      status.textContent = 'Claude analyse…'; status.className = 'mt-2 text-xs text-text-muted';
      try {
        const r = await App.api.brain_add({ content });
        if (r && r.ok) {
          status.textContent = `✓ Ajouté · catégorie : ${r.note.category || 'auto'}`;
          status.className = 'mt-2 text-xs text-success';
          setTimeout(() => { close(); this._load(); }, 800);
        } else {
          status.textContent = `✗ ${(r && r.error) || 'Erreur'}`;
          status.className = 'mt-2 text-xs text-danger';
          btn.disabled = false;
        }
      } catch (e) {
        status.textContent = `✗ ${e}`; status.className = 'mt-2 text-xs text-danger';
        btn.disabled = false;
      }
    };
    overlay.querySelector('#bn-save').onclick = save;
    overlay.addEventListener('keydown', e => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); save(); }
    });
  },

  // ----------------------------------------------------------------------
  // Modale détail note
  // ----------------------------------------------------------------------
  _openDetail(n) {
    const overlay = document.createElement('div');
    overlay.className = 'fixed inset-0 z-[200] flex items-center justify-center p-4';
    overlay.style.background = 'rgba(15,23,42,0.7)';
    overlay.style.backdropFilter = 'blur(8px)';
    const author = (n.author || 'jordan').toLowerCase();
    const replies = n.replies || [];
    overlay.innerHTML = `
      <div class="bg-surface rounded-2xl shadow-hero w-full max-w-xl max-h-[85vh] overflow-hidden border border-border animate-slide-up flex flex-col">
        <div class="px-6 pt-4 pb-3 border-b border-border bg-surface-elevated flex items-center justify-between">
          <div class="flex items-center gap-2 flex-wrap">
            <span class="b-author ${author}">${this._escape(author)}</span>
            <span class="text-xs text-text-muted">${this._fmtDate(n.created_at)}</span>
            ${n.category ? `<span class="b-tag">${this._escape(n.category)}</span>` : ''}
          </div>
          <button id="bd-close" class="w-8 h-8 rounded-lg flex items-center justify-center text-text-muted hover:text-text hover:bg-bg text-xl leading-none">×</button>
        </div>

        <div class="flex-1 overflow-y-auto px-6 py-5 space-y-4">
          <!-- Note originale -->
          <div class="text-sm whitespace-pre-wrap leading-relaxed">${this._escape(n.content)}</div>

          ${(n.tags || []).length || n.remind_at ? `
            <div class="flex items-center gap-2 text-[11px] text-text-muted flex-wrap">
              ${(n.tags || []).map(t => `<span class="b-tag">${this._escape(t)}</span>`).join('')}
              ${n.remind_at ? `<span>⏰ Rappel : ${this._fmtDate(n.remind_at)}</span>` : ''}
              ${n.assigned_to ? `<span>→ ${this._escape(n.assigned_to)}</span>` : ''}
            </div>` : ''}

          <!-- Réponses -->
          ${replies.length ? `
            <div class="border-t border-border pt-4 space-y-3">
              <div class="hero-kicker">RÉPONSES (${replies.length})</div>
              ${replies.map(r => `
                <div class="p-3 rounded-lg bg-bg border border-border">
                  <div class="flex items-center gap-2 mb-1">
                    <span class="b-author ${(r.author || '').toLowerCase()}">${this._escape(r.author || '')}</span>
                    <span class="text-[11px] text-text-muted">${this._fmtDate(r.created_at)}</span>
                  </div>
                  <div class="text-sm whitespace-pre-wrap">${this._escape(r.content || '')}</div>
                </div>
              `).join('')}
            </div>` : ''}

          <!-- Composer réponse -->
          <div class="border-t border-border pt-4">
            <div class="hero-kicker mb-2">RÉPONDRE</div>
            <textarea id="bd-reply" rows="3" placeholder="Ajoute une réponse… (Ctrl+Entrée pour envoyer)"
                      class="w-full px-3 py-2 text-sm rounded-lg bg-bg border border-border focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent resize-y"></textarea>
            <button id="bd-reply-send" class="btn btn-secondary mt-2 text-xs">Envoyer la réponse</button>
            <span id="bd-reply-status" class="text-xs text-text-muted ml-2"></span>
          </div>
        </div>

        <div class="px-6 py-3 border-t border-border bg-surface-elevated flex items-center justify-between gap-2">
          <button id="bd-delete" class="text-xs text-text-muted hover:text-danger">Supprimer</button>
          <div class="flex gap-2">
            ${n.status !== 'archived' ? `<button id="bd-archive" class="btn btn-secondary text-xs">Archiver</button>` : ''}
            ${n.status !== 'done'     ? `<button id="bd-done" class="btn btn-primary text-xs">✓ Marquer fait</button>` : `<button id="bd-reopen" class="btn btn-secondary text-xs">Rouvrir</button>`}
          </div>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);
    const close = () => overlay.remove();
    overlay.querySelector('#bd-close').onclick = close;
    overlay.addEventListener('click', e => { if (e.target === overlay) close(); });

    const setStatus = async (status) => {
      const r = await App.api.brain_update({ id: n.id, status });
      if (r && r.ok) { close(); this._load(); }
      else alert('Échec : ' + (r && r.error || 'inconnu'));
    };
    overlay.querySelector('#bd-archive')?.addEventListener('click', () => setStatus('archived'));
    overlay.querySelector('#bd-done')?.addEventListener('click', () => setStatus('done'));
    overlay.querySelector('#bd-reopen')?.addEventListener('click', () => setStatus('open'));
    overlay.querySelector('#bd-delete').onclick = async () => {
      if (!confirm('Supprimer cette note ?')) return;
      const r = await App.api.brain_delete({ id: n.id });
      if (r && r.ok) { close(); this._load(); }
      else alert('Échec : ' + (r && r.error || 'inconnu'));
    };

    const replySend = overlay.querySelector('#bd-reply-send');
    const sendReply = async () => {
      const content = overlay.querySelector('#bd-reply').value.trim();
      const status = overlay.querySelector('#bd-reply-status');
      if (!content) return;
      replySend.disabled = true;
      status.textContent = 'Envoi…';
      const r = await App.api.brain_reply({ id: n.id, content });
      if (r && r.ok) { close(); this._load(); }
      else { status.textContent = '✗ ' + (r && r.error || 'erreur'); replySend.disabled = false; }
    };
    replySend.onclick = sendReply;
    overlay.addEventListener('keydown', e => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); sendReply(); }
    });
  },

  // helpers
  _escape(s) {
    return String(s ?? '')
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  },
  _fmtDate(iso) {
    if (!iso) return '—';
    try {
      const d = new Date(iso);
      return d.toLocaleString('fr-FR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
    } catch { return iso.slice(0, 16); }
  },
};
