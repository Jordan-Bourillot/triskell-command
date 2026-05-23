/* Vue Brouillons à valider */

const Drafts = {
  async render(container) {
    container.innerHTML = `
      <section class="animate-slide-up">
        <div class="mb-6 sm:mb-8">
          <div class="flex items-start justify-between gap-3">
            <div class="min-w-0 flex-1">
              <div class="hero-kicker mb-2">BROUILLONS</div>
              <h1 class="hero-title hero-title--md mb-2 sm:mb-3">Les mails qui attendent ton OK.</h1>
              <p class="hero-subtitle">Préparés par l'app, en mode validation. Tu approuves ou tu rejettes en 1 clic.</p>
            </div>
            ${Help.button('drafts')}
          </div>
          <div class="flex flex-wrap gap-2 sm:gap-3 mt-5 sm:mt-6">
            <button id="d-refresh" class="btn btn-secondary">Rafraîchir</button>
            <button id="d-cleanup" class="btn btn-secondary" title="Supprime les brouillons en attente qui n'ont jamais reçu de contenu (coquilles vides)">Vider les coquilles vides</button>
            <button id="d-cleanup-broken" class="btn btn-secondary"
                    title="Supprime les brouillons où l'IA a refusé d'écrire (méta-blabla au lieu d'un mail).">
              Vider les cassés
            </button>
            <button id="d-wipe-all" class="btn btn-secondary"
                    style="border-color: hsl(var(--danger) / 0.5); color: hsl(var(--danger));"
                    title="Supprime TOUS les brouillons en attente (les bons comme les mauvais). Reset complet.">
              Tout vider
            </button>
          </div>
        </div>
        <div id="d-list" class="space-y-3 sm:space-y-4"></div>
      </section>
    `;
    document.getElementById('d-refresh').onclick = () => this.refresh();
    document.getElementById('d-cleanup').onclick = () => this._cleanup();
    document.getElementById('d-cleanup-broken').onclick = () => this._cleanupBroken();
    document.getElementById('d-wipe-all').onclick = () => this._wipeAll();
    await this.refresh();
  },

  async _cleanupBroken() {
    if (!App.api || !App.api.cleanup_broken_drafts) return;
    const ok = confirm(
      "Supprimer tous les brouillons où l'IA a refusé d'écrire "
      + "(« Je ne peux pas rédiger… », « PROBLÈME MAJEUR… ») ?\n\n"
      + "Les vrais brouillons ne sont pas touchés."
    );
    if (!ok) return;
    const btn = document.getElementById('d-cleanup-broken');
    if (btn) { btn.disabled = true; btn.textContent = 'Nettoyage…'; }
    let res;
    try { res = await App.api.cleanup_broken_drafts(); }
    catch (e) { alert('Erreur : ' + e); }
    finally {
      if (btn) { btn.disabled = false; btn.textContent = 'Vider les cassés'; }
    }
    if (res && res.ok) alert(`${res.total} brouillon(s) cassé(s) supprimé(s).`);
    else if (res) alert('Nettoyage partiel. Erreurs : ' + (res.errors || []).join(' ; '));
    await this.refresh();
  },

  async _wipeAll() {
    if (!App.api || !App.api.cleanup_all_pending_drafts) return;
    const ok = confirm(
      "ATTENTION : ça supprime TOUS les brouillons en attente "
      + "(les bons comme les mauvais).\n\nContinuer ?"
    );
    if (!ok) return;
    const btn = document.getElementById('d-wipe-all');
    if (btn) { btn.disabled = true; btn.textContent = 'Reset…'; }
    let res;
    try { res = await App.api.cleanup_all_pending_drafts(); }
    catch (e) { alert('Erreur : ' + e); }
    finally {
      if (btn) { btn.disabled = false; btn.textContent = 'Tout vider'; }
    }
    if (res && res.ok) alert(`${res.total} brouillon(s) supprimé(s).`);
    else if (res) alert('Reset partiel. Erreurs : ' + (res.errors || []).join(' ; '));
    await this.refresh();
  },

  async _cleanup() {
    if (!App.api) return;
    const ok = confirm(
      "Supprimer tous les brouillons en attente qui n’ont jamais reçu " +
      "de contenu (coquilles vides) ?\n\n" +
      "Les vrais brouillons (avec texte) ne sont pas touchés. " +
      "Les prospects ne sont pas supprimés non plus."
    );
    if (!ok) return;
    const btn = document.getElementById('d-cleanup');
    if (btn) { btn.disabled = true; btn.textContent = 'Nettoyage…'; }
    let res;
    try { res = await App.api.cleanup_empty_drafts({}); }
    catch (e) { alert('Erreur : ' + e); }
    finally {
      if (btn) { btn.disabled = false; btn.textContent = 'Vider les coquilles vides'; }
    }
    if (res && res.ok) {
      alert(`${res.total} coquille(s) vide(s) supprimée(s).`);
    } else if (res) {
      alert('Nettoyage partiel. Erreurs : ' + (res.errors || []).join(' ; '));
    }
    await this.refresh();
  },

  async refresh() {
    const list = document.getElementById('d-list');
    if (!App.api) {
      list.innerHTML = this._preview();
      return;
    }
    list.innerHTML = `<div class="text-center py-12 text-text-muted">Chargement…</div>`;
    let data;
    try { data = await App.api.get_drafts(); }
    catch (e) {
      list.innerHTML = `<div class="card p-6 text-danger">Erreur : ${e}</div>`;
      return;
    }
    if (!data || !data.ok || !data.rows || data.rows.length === 0) {
      list.innerHTML = `
        <div class="card p-6 sm:p-12 text-center">
          <div class="text-3xl sm:text-4xl mb-3">✓</div>
          <h2 class="text-xl font-semibold mb-2">Tu es à jour.</h2>
          <p class="text-text-secondary max-w-lg mx-auto">
            Aucun brouillon en attente. Quand l'auto-pilote ou les relances en
            prépareront en mode validation, ils atterriront ici.
          </p>
          <button class="btn btn-primary mt-6" onclick="App.show('autopilot')">Lancer une recherche</button>
        </div>
      `;
      return;
    }
    const banner = data.truncated
      ? `<div class="card p-3 sm:p-4 mb-3 text-sm text-text-muted">
            On affiche les ${data.rows.length} brouillons les plus récents
            (limite ${data.limit_per_source || 200} par source).
            Approuve ou rejette pour faire descendre la file.
          </div>`
      : '';
    list.innerHTML = banner + data.rows.map((r, i) => this._card(r, i)).join('');
    this._bind(data.rows);
  },

  _card(r, idx) {
    const ts = (r.ts || '').slice(0, 16);
    const meta = [];
    if (r.email) meta.push(this._esc(r.email));
    if (r.city)  meta.push(this._esc(r.city));
    if (ts)      meta.push(ts);
    if (r.provider || r.model) {
      meta.push(`${this._esc(r.provider)}/${this._esc(r.model)}`);
    }
    let badge = '';
    if (r.source === 'convoy') {
      const camp = r.campaign_name || r.offer_name || 'Convoi';
      badge = `<span class="text-xs px-2 py-0.5 rounded-full bg-accent/15 text-accent">${this._esc(camp)}</span>`;
    } else if (r.kind && r.kind !== 'first_contact') {
      badge = `<span class="text-xs px-2 py-0.5 rounded-full bg-bg border border-border text-text-muted">${this._esc(r.kind)}</span>`;
    }
    const testBadge = r.is_test
      ? `<span class="text-xs px-2 py-0.5 rounded-full bg-warning/20 text-warning ml-1">test</span>`
      : '';
    // Pastille catégorie : Pro / Créateur
    const audBadge = this._audienceBadge(r.audience);
    // Pastilles "trouvé via …" pour chaque source d'origine (globale)
    const srcBadges = this._sourceBadges(r.prospect_sources);
    // Provenance précise de l'email choisi pour ce brouillon
    const emailOriginLine = this._emailOriginLine(r.email, r.email_meta);
    // Bandeau "Note 2è IA" : visible si l'autopilote a fait passer le mail
    // par la 2e IA de relecture. Aide Jordan a trier en un coup d'oeil
    // les brouillons surs (vert >=7) vs douteux (orange 5-6, rouge <5).
    const reviewBanner = this._reviewBanner(r);
    const hasHtml = !!(r.body_html && String(r.body_html).trim());
    // srcdoc encode automatiquement les entites quand on le passe en attribut
    const htmlSrc = hasHtml
      ? String(r.body_html).replace(/"/g, '&quot;').replace(/'/g, '&#39;')
      : '';
    return `
      <article class="card p-4 sm:p-7"
               data-idx="${idx}"
               data-id="${this._esc(r.id || r.key)}"
               data-source="${this._esc(r.source || '')}">
        <header class="flex items-start justify-between mb-3 sm:mb-4 gap-3">
          <div class="min-w-0">
            <div class="font-semibold text-base truncate">${this._esc(r.name)} ${badge}${testBadge}</div>
            <div class="text-xs sm:text-sm text-text-muted break-all">${meta.join(' · ')}</div>
            ${(audBadge || srcBadges) ? `
              <div class="flex flex-wrap gap-1.5 mt-2">
                ${audBadge}
                ${srcBadges}
              </div>
            ` : ''}
            ${emailOriginLine}
          </div>
        </header>
        ${reviewBanner}
        <div class="text-sm font-semibold text-accent mb-2 break-words">OBJET : ${this._esc(r.subject)}</div>
        ${hasHtml ? `
          <div class="flex gap-2 mb-2 text-xs">
            <button class="d-toggle-view px-2 py-1 rounded-md bg-accent text-white"
                    data-mode="preview" data-idx="${idx}">Aperçu</button>
            <button class="d-toggle-view px-2 py-1 rounded-md bg-bg border border-border text-text-muted"
                    data-mode="source" data-idx="${idx}">Source / éditer</button>
          </div>
          <iframe data-preview sandbox=""
                  srcdoc="${htmlSrc}"
                  style="width:100%; min-height:300px; max-height:520px;
                         border:1px solid hsl(var(--border)); border-radius:12px;
                         background:white;"></iframe>
        ` : ''}
        <textarea data-body
                  class="w-full text-sm leading-relaxed p-3 sm:p-4 rounded-xl bg-bg
                         border border-border focus:outline-none
                         focus:ring-2 focus:ring-accent/30 focus:border-accent
                         resize-y min-h-[160px] sm:min-h-[180px] max-h-[400px]
                         text-text ${hasHtml ? 'hidden' : ''}"
                  rows="8">${this._esc(r.body)}</textarea>
        <footer class="flex flex-col sm:flex-row sm:justify-end gap-2 mt-4 pt-4 border-t border-border">
          <button class="btn btn-secondary justify-center" data-act="reject">Rejeter</button>
          <button class="btn btn-primary justify-center" data-act="approve">${r.source === 'convoy' ? 'Approuver (mise en file)' : 'Approuver &amp; envoyer'}</button>
        </footer>
      </article>
    `;
  },

  _bind(rows) {
    // Toggle Apercu HTML / Source texte pour chaque carte
    document.querySelectorAll('.d-toggle-view').forEach(btn => {
      btn.onclick = () => {
        const card = btn.closest('article[data-idx]');
        if (!card) return;
        const mode = btn.dataset.mode;
        const iframe = card.querySelector('iframe[data-preview]');
        const textarea = card.querySelector('textarea[data-body]');
        const buttons = card.querySelectorAll('.d-toggle-view');
        if (mode === 'preview') {
          if (iframe) iframe.classList.remove('hidden');
          if (textarea) textarea.classList.add('hidden');
        } else {
          if (iframe) iframe.classList.add('hidden');
          if (textarea) textarea.classList.remove('hidden');
        }
        // Met a jour le style actif/inactif des 2 boutons
        buttons.forEach(b => {
          const active = b.dataset.mode === mode;
          if (active) {
            b.className = 'd-toggle-view px-2 py-1 rounded-md bg-accent text-white';
          } else {
            b.className = 'd-toggle-view px-2 py-1 rounded-md bg-bg border border-border text-text-muted';
          }
        });
      };
    });

    document.querySelectorAll('article[data-idx]').forEach(card => {
      const idx = parseInt(card.dataset.idx, 10);
      const id = card.dataset.id;
      const source = card.dataset.source || '';
      const bodyEl = card.querySelector('[data-body]');
      const setBusy = (busy) => {
        card.querySelectorAll('button').forEach(b => b.disabled = busy);
        card.style.opacity = busy ? '0.6' : '1';
      };
      card.querySelector('[data-act="reject"]').onclick = async () => {
        if (!App.api) return;
        setBusy(true);
        try {
          const r = await App.api.draft_reject({ id, source, key: id });
          if (r && r.ok === false) alert('Rejet KO : ' + (r.error || '?'));
        } catch (e) { console.warn(e); }
        await this.refresh();
      };
      card.querySelector('[data-act="approve"]').onclick = async () => {
        if (!App.api) return;
        const body = bodyEl ? bodyEl.value : rows[idx].body;
        setBusy(true);
        try {
          const r = await App.api.draft_approve({ id, source, key: id, body });
          if (r && r.ok === false) alert('Envoi KO : ' + (r.error || '?'));
        } catch (e) { console.warn(e); }
        await this.refresh();
      };
    });
  },

  // Petite ligne d'info "Cet email vient de : …" sous les pastilles.
  // Précise pour chaque brouillon d'où vient exactement l'adresse choisie
  // (page mentions légales d'un site, bio YouTube, fiche Google Maps…).
  // Rend la bannière "Note 2è IA : X/10 — commentaire" pour un brouillon.
  // Couleur selon le score :
  //  - >= 7 : vert (mail juge sur)
  //  - 5-6  : orange (moyen, a relire)
  //  - < 5  : rouge (douteux, attention)
  // Renvoie '' si le brouillon n'a pas de review (ex: 2e IA desactivee).
  _reviewBanner(r) {
    if (!r || r.review_score == null) return '';
    const score = Math.max(0, Math.min(10, parseInt(r.review_score, 10) || 0));
    const comment = (r.review_comment || '').trim();
    let cls = 'bg-success/10 border-success/30 text-success';
    let label = 'OK';
    if (score < 5) {
      cls = 'bg-danger/10 border-danger/40 text-danger';
      label = 'Attention';
    } else if (score < 7) {
      cls = 'bg-warning/10 border-warning/40 text-warning';
      label = 'Moyen';
    }
    const commentPart = comment
      ? ` <span class="text-text-secondary font-normal">— ${this._esc(comment)}</span>`
      : '';
    return `
      <div class="mb-3 px-3 py-2 rounded-lg border text-xs sm:text-sm ${cls}"
           style="text-wrap: pretty">
        <span class="font-semibold">2è IA · ${label} · ${score}/10</span>${commentPart}
      </div>`;
  },

  _emailOriginLine(email, meta) {
    if (!email || !meta || typeof meta !== 'object') return '';
    // Préfère le `context` déjà rédigé pour humain, sinon traduit la source.
    const ctx = (meta.context || '').trim();
    const label = ctx || this._humanizeEmailSource(meta.source || '');
    if (!label) return '';
    const urlPart = meta.url
      ? ` <span class="text-text-muted/70">· ${this._esc(meta.url)}</span>`
      : '';
    return `
      <div class="text-[11px] text-text-muted mt-1.5 flex items-start gap-1.5"
           style="text-wrap: pretty">
        <svg class="w-3.5 h-3.5 mt-0.5 flex-shrink-0 text-accent/70"
             fill="none" stroke="currentColor" stroke-width="2"
             viewBox="0 0 24 24">
          <circle cx="12" cy="12" r="10"/>
          <line x1="12" y1="8" x2="12" y2="13"/>
          <line x1="12" y1="16" x2="12.01" y2="16"/>
        </svg>
        <span>
          <span class="text-text-secondary">Cet email vient de :</span>
          <span class="text-text">${this._esc(label)}</span>${urlPart}
        </span>
      </div>`;
  },

  // Traduit une source technique (sirene, web, obelisk_youtube…) en français.
  _humanizeEmailSource(source) {
    const s = String(source || '').toLowerCase();
    const direct = {
      web:           'page contact ou mentions légales du site officiel',
      web_inferred:  'adresse devinée à partir du domaine du site (non vérifiée)',
      sirene:        'annuaire d’entreprises SIRENE',
      maps:          'fiche Google Maps de l’établissement',
      file:          'fichier importé',
      linktree:      'hub de liens (Linktree, Beacons, etc.)',
      obelisk:       'profil créateur récupéré via Obélisk',
      phantombuster: 'profil social récupéré via PhantomBuster',
      chasseur:      'trouvé via Le Chasseur (entreprises)',
      bio:           'bio / description du profil',
    };
    if (direct[s]) return direct[s];
    if (s.startsWith('obelisk_')) {
      return `profil ${s.slice(8)} (récupéré via Obélisk)`;
    }
    if (s.startsWith('phantombuster_')) {
      return `profil ${s.slice(14)} (récupéré via PhantomBuster)`;
    }
    return s || '';
  },

  // Pastille "catégorie" : Pro / Entreprise vs Créateur / Influenceur
  _audienceBadge(audience) {
    const aud = (audience || '').toLowerCase();
    if (aud === 'creator') {
      return `<span class="text-xs px-2 py-0.5 rounded-full bg-purple-500/15 text-purple-300 border border-purple-500/30">Créateur / Influenceur</span>`;
    }
    if (aud === 'pro') {
      return `<span class="text-xs px-2 py-0.5 rounded-full bg-sky-500/15 text-sky-300 border border-sky-500/30">Pro / Entreprise</span>`;
    }
    return '';
  },

  // Pastilles "trouvé via X" — une par source d'origine du prospect
  _sourceBadges(sources) {
    if (!Array.isArray(sources) || sources.length === 0) return '';
    const labels = {
      sirene:     'SIRENE (entreprises)',
      maps:       'Google Maps',
      denicheur:  'Le Dénicheur',
      web:        'Site web',
      footprint:  'Empreinte web',
      linktree:   'Linktree',
      file:       'Import fichier',
      convoy:     'Import Convoi',
      obelisk:    'Obélisk',
      youtube:    'YouTube',
      twitch:     'Twitch',
      reddit:     'Reddit',
      bluesky:    'Bluesky',
      github:     'GitHub',
      tiktok:     'TikTok',
      instagram:  'Instagram',
      linkedin:   'LinkedIn',
      mastodon:   'Mastodon',
      dailymotion:'Dailymotion',
      kick:       'Kick',
      podcasts:   'Apple Podcasts',
      pypi:       'PyPI',
    };
    return sources.map(s => {
      const key = String(s || '').toLowerCase();
      const label = labels[key] || key;
      return `<span class="text-xs px-2 py-0.5 rounded-full bg-bg border border-border text-text-muted">via ${this._esc(label)}</span>`;
    }).join('');
  },

  _esc(s) {
    return String(s || '').replace(/[&<>"']/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    }[c]));
  },

  _preview() {
    return `
      <div class="card p-12 text-center">
        <div class="text-4xl mb-3">✓</div>
        <h2 class="text-xl font-semibold mb-2">Mode preview</h2>
        <p class="text-text-secondary max-w-md mx-auto">
          Connecte-toi à Supabase pour voir les vrais brouillons.
        </p>
      </div>
    `;
  },
};
