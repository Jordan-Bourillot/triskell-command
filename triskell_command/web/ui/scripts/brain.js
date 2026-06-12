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
        <!-- HERO compact -->
        <div class="mb-5 flex items-end justify-between flex-wrap gap-3">
          <div class="min-w-0 flex-1">
            <div class="hero-kicker mb-1">BRAIN</div>
            <h1 class="hero-title hero-title--md mb-1">Vide ton cerveau ici.</h1>
            <p class="hero-subtitle">Décharge tes idées, Claude les classe, te rappelle au bon moment. Partagé avec Thomas.</p>
          </div>
          <div class="flex gap-2">
            <button id="b-new" class="btn btn-primary justify-center" title="Note avec image / options avancées">
              <svg class="w-4 h-4 mr-1.5 inline" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>
              Nouvelle note
            </button>
            <button id="b-refresh" class="btn btn-secondary justify-center" title="Rafraîchir">↻</button>
          </div>
        </div>

        <!-- QUICK-ADD inline (pour vider vite) -->
        <div class="card p-3 mb-5 b-quickadd">
          <textarea id="b-quick" rows="1" placeholder="Tape une idée ici et appuie sur Entrée — Claude la range tout seul…"
                    class="w-full px-2 py-1.5 text-sm bg-transparent border-0 focus:outline-none resize-none font-sans leading-relaxed"></textarea>
          <div class="flex items-center justify-between gap-2 mt-1 text-[11px] text-text-muted">
            <span id="b-quick-hint" title="Le classement (catégorie, priorité) est automatique. Pour un rappel : écris la date dans l'idée, il se crée tout seul.">Entrée = envoyer · Maj+Entrée = saut de ligne · 💡 écris la date (« vendredi », « le 20 ») pour créer un rappel</span>
            <span class="flex items-center gap-2">
              <span id="b-quick-status"></span>
              <button id="b-quick-send" class="btn btn-secondary text-xs" style="padding:4px 12px;">Envoyer</button>
            </span>
          </div>
        </div>

        <!-- STATS BAR -->
        <div id="b-stats" class="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-5"></div>

        <!-- PRIORITÉ + RAPPELS À VENIR (sections dynamiques) -->
        <div id="b-priority"></div>
        <div id="b-reminders"></div>

        <!-- TOUTES LES NOTES (filtres + liste) -->
        <div class="flex items-center justify-between flex-wrap gap-2 mb-3 mt-6">
          <h2 class="text-sm font-bold uppercase tracking-wider text-text-muted">Toutes les notes</h2>
          <div class="flex flex-wrap gap-2 items-center text-[11px]">
            <select id="b-author-filter" class="px-2 py-1 rounded-lg bg-bg border border-border" aria-label="Filtrer par auteur">
              <option value="">Tous auteurs</option>
              ${this._authorOptions()}
            </select>
            <select id="b-sort" class="px-2 py-1 rounded-lg bg-bg border border-border">
              <option value="date_desc">Récentes d'abord</option>
              <option value="date_asc">Anciennes d'abord</option>
              <option value="priority">Par priorité</option>
              <option value="cat">Par catégorie (A→Z)</option>
              <option value="tag">Par tag</option>
            </select>
          </div>
        </div>
        <div class="flex gap-2 text-[11px] mb-4 overflow-x-auto -mx-1 px-1">
          <button data-bfilter="open"     class="b-filter is-active whitespace-nowrap">À traiter</button>
          <button data-bfilter="done"     class="b-filter whitespace-nowrap">Fait</button>
          <button data-bfilter="archived" class="b-filter whitespace-nowrap">Archivé</button>
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
    document.getElementById('b-author-filter').onchange = (e) => {
      this.state.authorFilter = e.target.value;
      this._load();
    };
    document.getElementById('b-sort').onchange = (e) => {
      this.state.sortBy = e.target.value;
      this._load();
    };
    // Quick-add : Entrée = envoyer, Maj+Entrée = saut de ligne
    const quick = document.getElementById('b-quick');
    quick.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        this._quickSubmit();
      }
    });
    // Bouton Envoyer visible (indispensable sur mobile, où Entrée
    // fait un saut de ligne sur certains claviers)
    document.getElementById('b-quick-send').onclick = () => this._quickSubmit();
    // Auto-grow textarea
    quick.addEventListener('input', () => {
      quick.style.height = 'auto';
      quick.style.height = Math.min(quick.scrollHeight, 240) + 'px';
    });
    await this._load();
  },

  // Libellés du filtre auteurs : « Moi (<prénom>) » pour l'utilisateur
  // connecté (App.currentUser), au lieu d'un « Moi (Jordan) » figé qui
  // était faux sur le poste de Thomas.
  _authorOptions() {
    const first = ((App.currentUser || {}).first_name || '').trim();
    const meKey = first.toLowerCase();
    const cap = (s) => s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
    const authors = ['jordan', 'thomas'];
    // L'utilisateur connecté apparaît en premier
    if (authors.includes(meKey)) {
      authors.splice(authors.indexOf(meKey), 1);
      authors.unshift(meKey);
    }
    const selected = this.state.authorFilter || '';
    return authors.map(a => {
      const label = (a === meKey && first) ? `Moi (${cap(first)})` : cap(a);
      return `<option value="${a}" ${selected === a ? 'selected' : ''}>${this._escape(label)}</option>`;
    }).join('');
  },

  async _quickSubmit() {
    const ta = document.getElementById('b-quick');
    const status = document.getElementById('b-quick-status');
    const sendBtn = document.getElementById('b-quick-send');
    const content = (ta.value || '').trim();
    if (!content) return;
    ta.disabled = true;
    if (sendBtn) sendBtn.disabled = true;
    status.textContent = 'Claude analyse…';
    status.className = 'text-text-muted';
    try {
      const r = await App.api.brain_add({ content });
      if (r && r.ok) {
        ta.value = '';
        ta.style.height = 'auto';
        status.textContent = `✓ Ajouté · ${(r.note && r.note.category) || 'classé'}`;
        status.className = 'text-success';
        setTimeout(() => { status.textContent = ''; }, 1500);
        this._load();
      } else {
        status.textContent = '✗ Ajout impossible, réessaie';
        status.className = 'text-danger';
        console.warn('brain_add:', r && r.error);
      }
    } catch (e) {
      status.textContent = '✗ Ajout impossible, réessaie';
      status.className = 'text-danger';
      console.warn('brain_add:', e);
    } finally {
      ta.disabled = false;
      if (sendBtn) sendBtn.disabled = false;
      ta.focus();
    }
  },

  _applyAuthorAndSort(notes) {
    let out = notes.slice();
    if (this.state.authorFilter) {
      out = out.filter(n => (n.author || '').toLowerCase() === this.state.authorFilter);
    }
    const sort = this.state.sortBy || 'date_desc';
    const prio = (n) => (n.urgency || 0) * (n.importance || 0);
    if (sort === 'date_asc')  out.sort((a, b) => (a.created_at || '').localeCompare(b.created_at || ''));
    else if (sort === 'cat')  out.sort((a, b) => (a.category || 'zzz').localeCompare(b.category || 'zzz'));
    else if (sort === 'tag')  out.sort((a, b) => ((a.tags || [])[0] || 'zzz').localeCompare((b.tags || [])[0] || 'zzz'));
    else if (sort === 'priority') out.sort((a, b) => prio(b) - prio(a) || (b.created_at || '').localeCompare(a.created_at || ''));
    else                       out.sort((a, b) => (b.created_at || '').localeCompare(a.created_at || ''));
    return out;
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
      .b-author { font-size: 10px; font-weight: 700; padding: 1px 5px;
                  border-radius: 4px; text-transform: uppercase; letter-spacing: 0.05em; }
      .b-author.jordan { background: hsl(var(--accent) / 0.15); color: hsl(var(--accent)); }
      .b-author.thomas { background: hsl(var(--success) / 0.15); color: hsl(var(--success)); }
      .b-prio-pill { display: inline-flex; align-items: center; gap: 2px;
                     padding: 1px 5px; border-radius: 4px;
                     background: hsl(var(--bg)); border: 1px solid hsl(var(--border));
                     color: hsl(var(--text-muted)); font-weight: 600; }
      .b-prio-5 { border-left: 3px solid hsl(var(--danger, 0 84% 60%)); }
      .b-prio-4 { border-left: 3px solid hsl(var(--warning, 38 92% 50%)); }
      .b-prio-3 { border-left: 3px solid hsl(var(--accent)); }

      /* Quick-add inline */
      .b-quickadd { border: 1px solid hsl(var(--border)); transition: border-color 160ms, box-shadow 160ms; }
      .b-quickadd:focus-within { border-color: hsl(var(--accent)); box-shadow: 0 0 0 3px hsl(var(--accent) / 0.15); }

      /* Stats bar */
      .b-stat { padding: 12px 14px; border-radius: 12px; border: 1px solid hsl(var(--border));
                background: hsl(var(--surface)); }
      .b-stat-value { font-size: 22px; font-weight: 800; line-height: 1; color: hsl(var(--text)); }
      .b-stat-label { font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em;
                      color: hsl(var(--text-muted)); margin-top: 6px; }
      .b-stat.is-warn .b-stat-value { color: hsl(var(--warning, 38 92% 50%)); }
      .b-stat.is-warn { background: hsl(var(--warning, 38 92% 50%) / 0.06);
                        border-color: hsl(var(--warning, 38 92% 50%) / 0.25); }

      /* Rappels à venir */
      .b-remind-row { display: flex; align-items: center; gap: 12px; padding: 10px 14px;
                      border-bottom: 1px solid hsl(var(--border)); cursor: pointer; transition: background 120ms; }
      .b-remind-row:last-child { border-bottom: none; }
      .b-remind-row:hover { background: hsl(var(--bg)); }
      .b-remind-date { min-width: 56px; text-align: center; padding: 4px 6px; border-radius: 8px;
                       background: hsl(var(--accent) / 0.10); }
      .b-remind-date.is-past { background: hsl(var(--danger, 0 84% 60%) / 0.10); }
      .b-remind-day { font-size: 11px; font-weight: 700; color: hsl(var(--text)); line-height: 1.1; }
      .b-remind-time { font-size: 10px; color: hsl(var(--text-muted)); margin-top: 2px; }

      /* Catégorie header */
      .b-cat-tile { display: flex; align-items: center; gap: 8px; }
      .b-cat-dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
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
      const r = await App.api.brain_list({ status: filter, limit: 300 });
      if (!r || !r.ok) {
        console.warn('brain_list:', r && r.error);
        root.innerHTML = `
          <div class="card p-6 text-center">
            <p class="text-text font-semibold mb-1">Impossible de charger les notes.</p>
            <p class="text-text-muted text-sm mb-3">Réessaie dans un instant.</p>
            <button class="btn btn-secondary" onclick="Brain._load()">Réessayer</button>
          </div>`;
        return;
      }
      const allNotes = r.notes || [];
      // Sections de tête : uniquement sur le filtre "open" (à traiter)
      const showHead = filter === 'open' && !this.state.authorFilter;
      this._renderStats(allNotes, showHead);
      this._renderPriorityBlock(showHead ? allNotes : []);
      this._renderRemindersBlock(showHead ? allNotes : []);
      // Filtre auteur actif : on explique pourquoi les stats/rappels
      // ont disparu (avant, ils s'évaporaient sans un mot).
      if (filter === 'open' && this.state.authorFilter) {
        const statsEl = document.getElementById('b-stats');
        if (statsEl) {
          statsEl.innerHTML = `<div class="col-span-2 sm:col-span-4 text-[11px] text-text-muted py-1">Stats et rappels masqués pendant le filtrage par auteur.</div>`;
        }
      }

      const notes = this._applyAuthorAndSort(allNotes);
      if (filter === 'open' && !this.state.authorFilter
          && (!this.state.sortBy || this.state.sortBy === 'date_desc' || this.state.sortBy === 'cat')) {
        const byCat = {};
        for (const n of notes) {
          const k = n.category || 'Sans catégorie';
          (byCat[k] = byCat[k] || []).push(n);
        }
        this.state.groups = Object.entries(byCat)
          .map(([category, notes]) => ({ category, count: notes.length, notes }))
          .sort((a, b) => this.state.sortBy === 'cat'
                ? a.category.localeCompare(b.category)
                : b.count - a.count);
        this._renderGrouped();
      } else {
        this._renderFlat(notes);
      }
      // Plafond d'affichage : on le dit au lieu de tronquer en silence
      if (allNotes.length >= 300) {
        root.insertAdjacentHTML('beforeend',
          `<p class="text-[11px] text-text-muted text-center mt-4">300 notes max affichées — les plus anciennes ne sont pas listées ici.</p>`);
      }
    } catch (e) {
      console.warn('brain_list:', e);
      root.innerHTML = `
        <div class="card p-6 text-center">
          <p class="text-text font-semibold mb-1">Impossible de charger les notes.</p>
          <p class="text-text-muted text-sm mb-3">Vérifie ta connexion, puis réessaie.</p>
          <button class="btn btn-secondary" onclick="Brain._load()">Réessayer</button>
        </div>`;
    }
  },

  _renderStats(notes, show) {
    const el = document.getElementById('b-stats');
    if (!el) return;
    if (!show) { el.innerHTML = ''; return; }
    const total = notes.length;
    const urgentes = notes.filter(n => (n.urgency || 0) >= 4).length;
    const now = Date.now();
    const day = 24 * 3600 * 1000;
    const rappels = notes.filter(n => n.remind_at && !n.reminded_at).length;
    // « Sous 24h » : uniquement les rappels À VENIR (les passés gonflaient
    // le compteur pour rien)
    const aujourdhui = notes.filter(n => {
      if (!n.remind_at) return false;
      const t = new Date(n.remind_at).getTime();
      return t >= now && t <= now + day;
    }).length;
    const stat = (label, value, accent) => `
      <div class="b-stat ${accent || ''}">
        <div class="b-stat-value">${value}</div>
        <div class="b-stat-label">${label}</div>
      </div>`;
    el.innerHTML = stat('À traiter', total) +
                   stat('Urgentes', urgentes, urgentes > 0 ? 'is-warn' : '') +
                   stat('Rappels actifs', rappels) +
                   stat('Sous 24h', aujourdhui, aujourdhui > 0 ? 'is-warn' : '');
  },

  _renderPriorityBlock(notes) {
    const el = document.getElementById('b-priority');
    if (!el) return;
    const top = notes
      .filter(n => (n.urgency || 0) * (n.importance || 0) > 0)
      .sort((a, b) => ((b.urgency || 0) * (b.importance || 0))
                    - ((a.urgency || 0) * (a.importance || 0)))
      .slice(0, 3)
      .filter(n => (n.urgency || 0) >= 3);
    if (!top.length) { el.innerHTML = ''; return; }
    el.innerHTML = `
      <div class="mb-5">
        <div class="flex items-baseline justify-between mb-2">
          <h2 class="text-sm font-bold uppercase tracking-wider text-text-muted">🔥 À traiter en priorité</h2>
          <span class="text-[11px] text-text-muted">${top.length} note${top.length > 1 ? 's' : ''}</span>
        </div>
        <div class="grid grid-cols-1 sm:grid-cols-3 gap-2">
          ${top.map(n => this._renderNoteCard(n)).join('')}
        </div>
      </div>
    `;
    el.querySelectorAll('[data-bnote]').forEach(card => {
      const n = notes.find(x => x.id === card.dataset.bnote);
      if (!n) return;
      this._makeClickable(card, () => this._openDetail(n));
    });
  },

  _renderRemindersBlock(notes) {
    const el = document.getElementById('b-reminders');
    if (!el) return;
    const now = Date.now();
    const sevenDays = 7 * 24 * 3600 * 1000;
    const upcoming = notes
      .filter(n => n.remind_at && !n.reminded_at)
      .filter(n => {
        const t = new Date(n.remind_at).getTime();
        return t >= now - 24 * 3600 * 1000 && t <= now + sevenDays;
      })
      .sort((a, b) => new Date(a.remind_at) - new Date(b.remind_at))
      .slice(0, 5);
    if (!upcoming.length) { el.innerHTML = ''; return; }
    el.innerHTML = `
      <div class="mb-5">
        <div class="flex items-baseline justify-between mb-2">
          <h2 class="text-sm font-bold uppercase tracking-wider text-text-muted">⏰ Rappels à venir (7 jours)</h2>
          <span class="text-[11px] text-text-muted">${upcoming.length}</span>
        </div>
        <div class="card overflow-hidden">
          ${upcoming.map(n => {
            const t = new Date(n.remind_at);
            const past = t.getTime() < now;
            return `
              <div class="b-remind-row" data-bnote="${this._escape(n.id)}">
                <div class="b-remind-date ${past ? 'is-past' : ''}">
                  <div class="b-remind-day">${t.toLocaleDateString('fr-FR', { day: '2-digit', month: 'short' })}</div>
                  <div class="b-remind-time">${t.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })}</div>
                </div>
                <div class="flex-1 min-w-0">
                  <div class="text-sm leading-tight truncate">${this._escape(n.summary || n.content || '')}</div>
                  <div class="text-[11px] text-text-muted mt-0.5">
                    ${n.urgency ? `🔥 ${n.urgency}/5` : ''} ${n.category ? '· ' + this._escape(n.category) : ''}
                  </div>
                </div>
              </div>
            `;
          }).join('')}
        </div>
      </div>
    `;
    el.querySelectorAll('[data-bnote]').forEach(row => {
      const n = notes.find(x => x.id === row.dataset.bnote);
      if (!n) return;
      this._makeClickable(row, () => this._openDetail(n));
    });
  },

  _renderGrouped() {
    const root = document.getElementById('b-content');
    if (!this.state.groups.length) {
      root.innerHTML = `
        <div class="card p-6 sm:p-12 text-center">
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
          <div class="b-cat-tile">
            <span class="b-cat-dot" style="background:${this._catColor(g.category)}"></span>
            <span class="b-cat-header">${this._escape(g.category)}</span>
          </div>
          <div class="text-xs text-text-muted">${g.count} note${g.count > 1 ? 's' : ''}</div>
        </div>
        <div class="space-y-2">
          ${g.notes.map(n => this._renderNoteCard(n)).join('')}
        </div>
      </div>
    `).join('');
    this._bindCards(this.state.groups.flatMap(g => g.notes));
  },

  _renderFlat(notes) {
    const root = document.getElementById('b-content');
    if (!notes.length) {
      root.innerHTML = `<div class="card p-6 sm:p-12 text-center text-text-muted">Aucune note dans ce filtre.</div>`;
      return;
    }
    root.innerHTML = `<div class="space-y-2">${notes.map(n => this._renderNoteCard(n)).join('')}</div>`;
    this._bindCards(notes);
  },

  _renderNoteCard(n) {
    const author = (n.author || 'jordan').toLowerCase();
    const tags = (n.tags || []).slice(0, 4);
    const remind = n.remind_at ? this._fmtDate(n.remind_at) : '';
    const replyCount = (n.replies || []).length;
    const summaryOrContent = n.summary || (n.content || '').slice(0, 200);
    const atts = (n.attachments || []).slice(0, 4);
    const extra = (n.attachments || []).length - atts.length;
    const u = n.urgency, imp = n.importance;
    const prioClass = u >= 5 ? 'b-prio-5' : u === 4 ? 'b-prio-4' : u === 3 ? 'b-prio-3' : '';
    return `
      <div class="card b-note p-4 ${prioClass}" data-bnote="${this._escape(n.id)}">
        <div class="flex items-start justify-between gap-3 mb-2">
          <div class="flex-1 min-w-0">
            <div class="text-sm leading-relaxed text-text whitespace-pre-wrap">${this._escape(summaryOrContent)}</div>
            ${atts.length ? `
              <div class="flex gap-1.5 mt-2 flex-wrap">
                ${atts.map(u => `<img src="${this._escape(u)}" alt="" class="w-14 h-14 object-cover rounded-md border border-border" loading="lazy">`).join('')}
                ${extra > 0 ? `<div class="w-14 h-14 rounded-md border border-border flex items-center justify-center text-xs text-text-muted bg-bg">+${extra}</div>` : ''}
              </div>` : ''}
          </div>
          <div class="flex flex-col items-end gap-1 shrink-0">
            <span class="b-author ${author}">${this._escape(author)}</span>
            ${(u || imp) ? `<div class="flex gap-1 text-[10px]">
              ${u   ? `<span class="b-prio-pill" title="Urgence ${u}/5">🔥 ${u}</span>` : ''}
              ${imp ? `<span class="b-prio-pill" title="Importance ${imp}/5">⭐ ${imp}</span>` : ''}
            </div>` : ''}
          </div>
        </div>
        <div class="flex items-center gap-2 text-[11px] text-text-muted flex-wrap">
          ${tags.map(t => `<span class="b-tag">${this._escape(t)}</span>`).join('')}
          ${remind ? `<span>⏰ ${remind}</span>` : ''}
          ${replyCount > 0 ? `<span>💬 ${replyCount}</span>` : ''}
          ${(n.attachments || []).length ? `<span>📎 ${(n.attachments || []).length}</span>` : ''}
          ${n.assigned_to ? `<span>→ ${this._escape(n.assigned_to)}</span>` : ''}
          <span class="ml-auto">${this._fmtDate(n.created_at)}</span>
        </div>
      </div>
    `;
  },

  // ----------------------------------------------------------------------
  // Composer pièces jointes (réutilisé dans nouvelle note + édition)
  // ----------------------------------------------------------------------
  async _uploadFile(file) {
    if (!file) return null;
    if (!file.type || !file.type.startsWith('image/')) {
      Toast.warn('Seules les images sont acceptées pour le moment.');
      return null;
    }
    if (file.size > 10 * 1024 * 1024) {
      Toast.warn('Image trop lourde (10 Mo maximum).');
      return null;
    }
    const data = await new Promise((res, rej) => {
      const r = new FileReader();
      r.onload = () => res(String(r.result).split(',')[1] || '');
      r.onerror = () => rej(r.error);
      r.readAsDataURL(file);
    });
    const r = await App.api.brain_upload({
      data, filename: file.name || `paste-${Date.now()}.png`,
      content_type: file.type,
    });
    if (!r || !r.ok) {
      console.warn('brain_upload:', r && r.error);
      Toast.error('Envoi de l’image impossible. Réessaie dans un instant.');
      return null;
    }
    return r.url;
  },

  _attachmentsComposerHTML(idPrefix, opts) {
    const o = opts || {};
    return `
      <div class="mt-3" id="${idPrefix}-att">
        <div class="flex items-center gap-2 flex-wrap">
          <label class="text-xs text-text-muted hover:text-accent cursor-pointer inline-flex items-center gap-1 transition">
            📎 Ajouter une image
            <input type="file" accept="image/*" multiple id="${idPrefix}-file" class="hidden">
          </label>
          <span class="text-[11px] text-text-muted">Ou colle (Ctrl+V) / glisse dans la zone.</span>
        </div>
        <div id="${idPrefix}-previews" class="flex gap-2 mt-2 flex-wrap"></div>
        <label class="flex items-center gap-2 mt-2 text-xs text-text-muted cursor-pointer">
          <input type="checkbox" id="${idPrefix}-vision" class="w-3.5 h-3.5">
          Faire analyser les images par Claude (vision)
        </label>
        <div id="${idPrefix}-upload-status" class="text-[11px] text-text-muted mt-1"></div>
      </div>
    `;
  },

  _bindAttachmentsComposer(overlay, idPrefix, dropZone, initialUrls) {
    const state = { urls: [...(initialUrls || [])] };
    const previewsEl = overlay.querySelector(`#${idPrefix}-previews`);
    const statusEl   = overlay.querySelector(`#${idPrefix}-upload-status`);
    const fileInput  = overlay.querySelector(`#${idPrefix}-file`);
    const visionCb   = overlay.querySelector(`#${idPrefix}-vision`);

    const renderPreviews = () => {
      previewsEl.innerHTML = state.urls.map((u, i) => `
        <div class="relative group">
          <img src="${this._escape(u)}" alt="" class="w-16 h-16 object-cover rounded-md border border-border">
          <button type="button" data-rm="${i}" title="Retirer"
                  class="absolute -top-1.5 -right-1.5 w-5 h-5 rounded-full bg-danger text-white text-[11px] leading-none flex items-center justify-center opacity-0 group-hover:opacity-100 transition">×</button>
        </div>
      `).join('');
      previewsEl.querySelectorAll('[data-rm]').forEach(b => {
        b.onclick = () => {
          state.urls.splice(parseInt(b.dataset.rm, 10), 1);
          renderPreviews();
        };
      });
    };

    const handleFiles = async (files) => {
      const arr = Array.from(files || []);
      for (const f of arr) {
        statusEl.textContent = `Envoi de ${f.name}…`;
        try {
          const url = await this._uploadFile(f);
          if (url) { state.urls.push(url); renderPreviews(); }
        } catch (e) {
          Toast.friendlyError(e, 'Envoi de l’image impossible. Réessaie dans un instant.');
        }
      }
      statusEl.textContent = state.urls.length
        ? `${state.urls.length} image${state.urls.length > 1 ? 's' : ''} prête${state.urls.length > 1 ? 's' : ''}.`
        : '';
    };

    fileInput.onchange = (e) => handleFiles(e.target.files);

    // Paste sur la dropZone (ou le textarea passé en argument)
    if (dropZone) {
      dropZone.addEventListener('paste', (e) => {
        const items = (e.clipboardData && e.clipboardData.items) || [];
        const imgs = Array.from(items).filter(i => i.type && i.type.startsWith('image/'))
                                       .map(i => i.getAsFile()).filter(Boolean);
        if (imgs.length) { e.preventDefault(); handleFiles(imgs); }
      });
      // Drag & drop sur la dropZone
      dropZone.addEventListener('dragover', (e) => { e.preventDefault(); dropZone.classList.add('ring-2', 'ring-accent/40'); });
      dropZone.addEventListener('dragleave', () => dropZone.classList.remove('ring-2', 'ring-accent/40'));
      dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropZone.classList.remove('ring-2', 'ring-accent/40');
        const files = (e.dataTransfer && e.dataTransfer.files) || [];
        if (files.length) handleFiles(files);
      });
    }

    renderPreviews();
    return {
      getUrls: () => state.urls.slice(),
      getAnalyzeImages: () => !!(visionCb && visionCb.checked),
    };
  },

  // Lie les cartes du RENDU COURANT à leur note. On passe la liste
  // vraiment affichée (avant : recherche dans state.groups — vide pour
  // les filtres Fait/Archivé — puis re-fetch tronqué à 200 sans statut,
  // d'où des clics morts sur les notes anciennes).
  _bindCards(list) {
    const root = document.getElementById('b-content');
    if (!root) return;
    root.querySelectorAll('[data-bnote]').forEach(el => {
      const n = (list || []).find(x => x.id === el.dataset.bnote);
      if (!n) return;
      this._makeClickable(el, () => this._openDetail(n));
    });
  },

  // Rend un div cliquable accessible au clavier (Entrée / Espace)
  _makeClickable(el, fn) {
    el.onclick = fn;
    el.setAttribute('role', 'button');
    el.setAttribute('tabindex', '0');
    el.onkeydown = (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fn(); }
    };
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
                    placeholder="Ex: Demander à Thomas son retour sur la nouvelle landing. Lui répondre lundi.&#10;Ex: Idée produit : extension Chrome qui résume les vidéos YouTube."
                    class="w-full px-3 py-3 text-sm rounded-lg bg-bg border border-border focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent font-sans leading-relaxed resize-y transition"></textarea>
          ${this._attachmentsComposerHTML('bn')}
          <div id="bn-status" class="mt-2 text-xs text-text-muted">Ctrl+Entrée pour envoyer</div>
        </div>
        <div class="px-6 py-3 border-t border-border bg-surface-elevated flex justify-end gap-2">
          <button id="bn-cancel" class="btn btn-secondary">Annuler</button>
          <button id="bn-save"   class="btn btn-primary">Ajouter</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);
    // close() retire TOUJOURS l'écouteur Échap (avant : il fuyait si la
    // fenêtre se fermait autrement que par Échap)
    const close = () => {
      document.removeEventListener('keydown', escListener);
      overlay.remove();
    };
    // Garde anti-perte de saisie sur clic-dehors / Échap
    const isDirty = () => {
      const ta = overlay.querySelector('#bn-content');
      return !!((ta && ta.value.trim()) || composer.getUrls().length);
    };
    const closeGuarded = async () => {
      if (isDirty()) {
        const sure = await Dialog.confirm(
          'Ta note n’est pas enregistrée. Fermer quand même ?',
          { title: 'Note en cours', okLabel: 'Fermer sans garder', cancelLabel: 'Continuer la saisie', danger: true });
        if (!sure) return;
      }
      close();
    };
    overlay.querySelector('#bn-cancel').onclick = close;
    overlay.addEventListener('click', e => { if (e.target === overlay) closeGuarded(); });
    const escListener = (e) => {
      if (e.key === 'Escape') closeGuarded();
    };
    document.addEventListener('keydown', escListener);

    const textarea = overlay.querySelector('#bn-content');
    const composer = this._bindAttachmentsComposer(overlay, 'bn', textarea, []);

    const save = async () => {
      const content = overlay.querySelector('#bn-content').value.trim();
      const status = overlay.querySelector('#bn-status');
      const attachments = composer.getUrls();
      if (!content && !attachments.length) {
        status.textContent = '✗ Vide (texte ou image).'; status.className = 'mt-2 text-xs text-danger'; return;
      }
      const btn = overlay.querySelector('#bn-save');
      btn.disabled = true;
      status.textContent = 'Claude analyse…'; status.className = 'mt-2 text-xs text-text-muted';
      try {
        const r = await App.api.brain_add({
          content, attachments,
          analyze_images: composer.getAnalyzeImages(),
        });
        if (r && r.ok) {
          status.textContent = `✓ Ajouté · catégorie : ${(r.note && r.note.category) || 'auto'}`;
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
    // Mobile : full-screen (p-0), desktop : centré avec marges (p-4)
    overlay.className = 'fixed inset-0 z-[200] flex items-stretch sm:items-center justify-center sm:p-4';
    overlay.style.background = 'rgba(15,23,42,0.7)';
    overlay.style.backdropFilter = 'blur(8px)';
    const author = (n.author || 'jordan').toLowerCase();
    const replies = n.replies || [];
    overlay.innerHTML = `
      <div class="bg-surface sm:rounded-2xl shadow-hero w-full sm:max-w-xl h-full sm:h-auto sm:max-h-[85vh] overflow-hidden sm:border border-border animate-slide-up flex flex-col">
        <div class="px-4 sm:px-6 pt-4 pb-3 border-b border-border bg-surface-elevated flex items-center justify-between">
          <div class="flex items-center gap-2 flex-wrap">
            <span class="b-author ${author}">${this._escape(author)}</span>
            <span class="text-xs text-text-muted">${this._fmtDate(n.created_at)}</span>
            ${n.category ? `<span class="b-tag">${this._escape(n.category)}</span>` : ''}
          </div>
          <button id="bd-close" class="w-8 h-8 rounded-lg flex items-center justify-center text-text-muted hover:text-text hover:bg-bg text-xl leading-none shrink-0">×</button>
        </div>

        <div class="flex-1 overflow-y-auto px-4 sm:px-6 py-5 space-y-4">
          <!-- Note originale (avec édition inline) -->
          <div id="bd-note-block">
            <div id="bd-note-view" class="text-sm whitespace-pre-wrap leading-relaxed">${this._escape(n.content)}</div>
            ${(n.attachments || []).length ? `
              <div id="bd-attachments-view" class="grid grid-cols-2 gap-2 mt-3">
                ${(n.attachments || []).map(u => `
                  <img src="${this._escape(u)}" alt="" data-lightbox="${this._escape(u)}"
                       class="w-full h-32 object-cover rounded-lg border border-border cursor-zoom-in hover:opacity-90 transition" loading="lazy">
                `).join('')}
              </div>` : ''}
            <button id="bd-edit" class="text-xs text-text-muted hover:text-accent mt-2">✎ Modifier</button>
            <div id="bd-edit-zone" class="hidden">
              <textarea id="bd-edit-content" rows="5"
                        class="w-full px-3 py-2 text-sm rounded-lg bg-bg border border-border focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent resize-y transition">${this._escape(n.content)}</textarea>
              ${this._attachmentsComposerHTML('bd')}
              <div class="flex items-center gap-2 mt-2">
                <button id="bd-edit-save" class="btn btn-primary text-xs">Enregistrer</button>
                <button id="bd-edit-cancel" class="btn btn-secondary text-xs">Annuler</button>
                <span id="bd-edit-status" class="text-xs text-text-muted"></span>
              </div>
              <div class="text-[11px] text-text-muted mt-1">Claude relance l'analyse après sauvegarde.</div>
            </div>
          </div>

          ${(n.tags || []).length || n.remind_at || n.urgency || n.importance ? `
            <div class="flex items-center gap-2 text-[11px] text-text-muted flex-wrap">
              ${n.urgency    ? `<span class="b-prio-pill">🔥 ${n.urgency}/5 urgence</span>` : ''}
              ${n.importance ? `<span class="b-prio-pill">⭐ ${n.importance}/5 importance</span>` : ''}
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

        <div class="px-4 sm:px-6 py-3 border-t border-border bg-surface-elevated flex items-center justify-between gap-2">
          <button id="bd-delete" class="text-xs text-text-muted hover:text-danger">Supprimer</button>
          <div class="flex gap-2">
            ${n.status !== 'archived' ? `<button id="bd-archive" class="btn btn-secondary text-xs">Archiver</button>` : ''}
            ${n.status !== 'done'     ? `<button id="bd-done" class="btn btn-primary text-xs">✓ Marquer fait</button>` : `<button id="bd-reopen" class="btn btn-secondary text-xs">Rouvrir</button>`}
          </div>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);
    // close() retire TOUJOURS l'écouteur Échap
    const close = () => {
      document.removeEventListener('keydown', escListener);
      overlay.remove();
    };
    // Garde anti-perte de saisie : réponse en cours ou édition modifiée
    const isDirty = () => {
      const reply = overlay.querySelector('#bd-reply');
      if (reply && reply.value.trim()) return true;
      const zone = overlay.querySelector('#bd-edit-zone');
      if (zone && !zone.classList.contains('hidden')) {
        const area = overlay.querySelector('#bd-edit-content');
        const txtChanged = area && area.value.trim() !== (n.content || '').trim();
        const attChanged = JSON.stringify(editComposer.getUrls()) !== JSON.stringify(n.attachments || []);
        if (txtChanged || attChanged) return true;
      }
      return false;
    };
    const closeGuarded = async () => {
      if (isDirty()) {
        const sure = await Dialog.confirm(
          'Tu as du texte non envoyé dans cette note. Fermer quand même ?',
          { title: 'Saisie en cours', okLabel: 'Fermer sans garder', cancelLabel: 'Continuer la saisie', danger: true });
        if (!sure) return;
      }
      close();
    };
    const escListener = (e) => {
      if (e.key !== 'Escape') return;
      // Si la visionneuse d'image est ouverte, Échap ne ferme qu'elle
      if (document.getElementById('b-lightbox')) return;
      closeGuarded();
    };
    document.addEventListener('keydown', escListener);
    overlay.querySelector('#bd-close').onclick = close;
    overlay.addEventListener('click', e => { if (e.target === overlay) closeGuarded(); });

    const setStatus = async (status) => {
      try {
        const r = await App.api.brain_update({ id: n.id, status });
        if (r && r.ok) { close(); this._load(); }
        else {
          console.warn('brain_update:', r && r.error);
          Toast.error('Impossible de changer le statut de la note. Réessaie dans un instant.');
        }
      } catch (e) {
        Toast.friendlyError(e, 'Impossible de changer le statut de la note.');
      }
    };
    overlay.querySelector('#bd-archive')?.addEventListener('click', () => setStatus('archived'));
    overlay.querySelector('#bd-done')?.addEventListener('click', () => setStatus('done'));
    overlay.querySelector('#bd-reopen')?.addEventListener('click', () => setStatus('open'));
    overlay.querySelector('#bd-delete').onclick = async () => {
      const sure = await Dialog.confirm('Supprimer cette note ?',
        { title: 'Supprimer', okLabel: 'Supprimer', danger: true });
      if (!sure) return;
      try {
        const r = await App.api.brain_delete({ id: n.id });
        if (r && r.ok) { close(); this._load(); }
        else {
          console.warn('brain_delete:', r && r.error);
          Toast.error('Suppression impossible. Réessaie dans un instant.');
        }
      } catch (e) {
        Toast.friendlyError(e, 'Suppression impossible.');
      }
    };

    // ---- Lightbox plein écran sur les images attachées (vue lecture) ----
    overlay.querySelectorAll('[data-lightbox]').forEach(img => {
      img.onclick = (e) => { e.stopPropagation(); this._openLightbox(img.dataset.lightbox); };
    });

    // ---- Édition du contenu ----
    const editBtn    = overlay.querySelector('#bd-edit');
    const editZone   = overlay.querySelector('#bd-edit-zone');
    const noteView   = overlay.querySelector('#bd-note-view');
    const attView    = overlay.querySelector('#bd-attachments-view');
    const editArea   = overlay.querySelector('#bd-edit-content');
    const editSave   = overlay.querySelector('#bd-edit-save');
    const editCancel = overlay.querySelector('#bd-edit-cancel');
    const editStatus = overlay.querySelector('#bd-edit-status');
    const editComposer = this._bindAttachmentsComposer(overlay, 'bd', editArea, n.attachments || []);
    const showEdit = (on) => {
      editZone.classList.toggle('hidden', !on);
      noteView.classList.toggle('hidden', on);
      if (attView) attView.classList.toggle('hidden', on);
      editBtn.classList.toggle('hidden', on);
      if (on) { editArea.value = n.content || ''; editArea.focus(); }
    };
    editBtn.onclick = () => showEdit(true);
    editCancel.onclick = () => showEdit(false);
    editSave.onclick = async () => {
      const content = editArea.value.trim();
      const attachments = editComposer.getUrls();
      if (!content && !attachments.length) {
        editStatus.textContent = '✗ Vide (texte ou image).'; editStatus.className = 'text-xs text-danger'; return;
      }
      const unchanged = content === (n.content || '').trim()
                     && JSON.stringify(attachments) === JSON.stringify(n.attachments || []);
      if (unchanged) { showEdit(false); return; }
      editSave.disabled = true;
      editStatus.textContent = 'Claude ré-analyse…'; editStatus.className = 'text-xs text-text-muted';
      const r = await App.api.brain_edit({
        id: n.id, content, attachments,
        analyze_images: editComposer.getAnalyzeImages(),
      });
      if (r && r.ok) {
        editStatus.textContent = '✓ Enregistré';
        editStatus.className = 'text-xs text-success';
        setTimeout(() => { close(); this._load(); }, 600);
      } else {
        editStatus.textContent = '✗ ' + ((r && r.error) || 'erreur');
        editStatus.className = 'text-xs text-danger';
        editSave.disabled = false;
      }
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
      else {
        console.warn('brain_reply:', r && r.error);
        status.textContent = '✗ Envoi impossible, réessaie';
        replySend.disabled = false;
      }
    };
    replySend.onclick = sendReply;
    overlay.addEventListener('keydown', e => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); sendReply(); }
    });
  },

  // Couleur stable dérivée du nom de la catégorie (hash → teinte HSL)
  _catColor(name) {
    const s = String(name || '');
    let h = 0;
    for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) & 0xffffffff;
    const hue = Math.abs(h) % 360;
    return `hsl(${hue}, 70%, 55%)`;
  },

  // ----------------------------------------------------------------------
  // Lightbox image plein écran
  // ----------------------------------------------------------------------
  _openLightbox(url) {
    const lb = document.createElement('div');
    lb.id = 'b-lightbox'; // repéré par l'Échap de la modale détail
    lb.className = 'fixed inset-0 z-[300] flex items-center justify-center p-4 cursor-zoom-out';
    lb.style.background = 'rgba(0,0,0,0.92)';
    lb.innerHTML = `<img src="${this._escape(url)}" alt="" class="max-w-full max-h-full object-contain rounded-lg shadow-hero">`;
    const close = () => { lb.remove(); document.removeEventListener('keydown', esc); };
    const esc = (e) => { if (e.key === 'Escape') close(); };
    lb.onclick = close;
    document.addEventListener('keydown', esc);
    document.body.appendChild(lb);
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
