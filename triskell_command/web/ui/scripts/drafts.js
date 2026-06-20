/* Vue Brouillons à valider */

const Drafts = {
  async render(container) {
    // Label du bouton Retour : tente d'humaniser la vue precedente si elle
    // est connue, sinon retombe sur le cockpit (page d'accueil).
    const backTarget = App.previousView || 'morning';
    const backLabels = {
      morning:   'Retour au cockpit',
      autopilot: 'Retour à l’auto-pilote',
      mails:     'Retour aux mails',
      replies:   'Retour aux réponses',
      convoy:    'Retour au Convoi',
      health:    'Retour à la santé',
    };
    const backLabel = backLabels[backTarget] || 'Retour';
    container.innerHTML = `
      <section class="animate-slide-up">
        <div class="mb-4">
          <button id="d-back" class="btn btn-secondary btn-sm">← ${backLabel}</button>
        </div>
        <div class="mb-6 sm:mb-8">
          <div class="flex items-start justify-between gap-3">
            <div class="min-w-0 flex-1">
              <div class="hero-kicker mb-2">BROUILLONS</div>
              <h1 class="hero-title hero-title--md mb-2 sm:mb-3">Les mails qui attendent ton OK.</h1>
              <p class="hero-subtitle">Préparés par l'app, en mode validation. Tu approuves ou tu rejettes en 1 clic.</p>
            </div>
            ${typeof Help !== 'undefined' ? Help.button('drafts') : ''}
          </div>
          <div class="flex flex-wrap gap-2 sm:gap-3 mt-5 sm:mt-6">
            <button id="d-send-all" class="btn btn-primary hidden"
                    title="Envoie d’un coup tous les brouillons en attente, après confirmation.">
              Tout envoyer
            </button>
            <button id="d-fast" type="button" class="btn btn-secondary"
                    title="Vitesse d’envoi des brouillons un par un."></button>
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
        <div id="d-batch"></div>
        <div id="d-list" class="space-y-3 sm:space-y-4"></div>
      </section>
    `;
    const backBtn = document.getElementById('d-back');
    if (backBtn) backBtn.onclick = () => App.show(backTarget);
    document.getElementById('d-refresh').onclick = () => this.refresh();
    document.getElementById('d-cleanup').onclick = () => this._cleanup();
    document.getElementById('d-cleanup-broken').onclick = () => this._cleanupBroken();
    document.getElementById('d-wipe-all').onclick = () => this._wipeAll();
    document.getElementById('d-send-all').onclick = () => this._sendAll();
    const fastBtn = document.getElementById('d-fast');
    if (fastBtn) fastBtn.onclick = () => this._setFast(!this._isFast());
    this._renderFastBtn();
    // Nouvelle vue : l'éventuel minuteur de suivi d'un envoi groupé a été
    // nettoyé par App.show (viewInterval) — on oublie son ancien id.
    this._batchPollId = null;
    this._batchLocked = false;
    await this.refresh();
  },

  // --- Envoi rapide (1 clic) vs fenêtre de grâce (5 s pour annuler) ---
  // Réglage mémorisé dans le navigateur. Défaut = rapide, pour pouvoir
  // valider plusieurs brouillons à la suite sans attendre à chaque fois.
  _FAST_KEY: 'triskell.drafts.fastSend',
  _isFast() {
    try {
      const v = localStorage.getItem(this._FAST_KEY);
      return v === null ? true : v === '1';
    } catch (e) { return true; }
  },
  _setFast(on) {
    try { localStorage.setItem(this._FAST_KEY, on ? '1' : '0'); } catch (e) {}
    this._renderFastBtn();
    Toast.info(on
      ? 'Envoi rapide activé : les mails partent tout de suite.'
      : 'Envoi rapide coupé : 5 secondes pour annuler avant chaque envoi.');
  },
  _renderFastBtn() {
    const b = document.getElementById('d-fast');
    if (!b) return;
    const on = this._isFast();
    b.textContent = on ? '⚡ Envoi rapide : activé'
                       : '⏱ Envoi rapide : coupé';
    b.title = on
      ? 'Clic sur « Approuver & envoyer » = le mail part tout de suite. Clique ici pour remettre les 5 s pour annuler.'
      : 'Clic sur « Approuver & envoyer » = 5 s pour annuler avant l’envoi. Clique ici pour envoyer sans attendre.';
    b.style.borderColor = on ? 'hsl(var(--success) / 0.6)' : '';
    b.style.color = on ? 'hsl(var(--success-text))' : '';
  },

  // Carte « rien à valider » — extraite pour la réutiliser après le dernier
  // envoi sans recharger toute la liste depuis le serveur.
  _emptyStateHTML() {
    return `
        <div class="card p-6 sm:p-12 text-center">
          <div class="text-3xl sm:text-4xl mb-3">✓</div>
          <h2 class="text-xl font-semibold mb-2">Tu es à jour — rien à valider.</h2>
          <p class="text-text-secondary max-w-lg mx-auto">
            Quand l'Auto-pilote ou les relances prépareront des mails,
            ils attendront ton OK ici. Pour en avoir : lance une prospection,
            les mails arrivent tout seuls derrière.
          </p>
          <button class="btn btn-primary mt-6" onclick="App.show('prospection')">🚀 Lancer une prospection</button>
        </div>
      `;
  },

  // Après l'envoi/rejet d'UNE carte : met à jour les compteurs et l'état
  // « vide » EN PLACE, sans recharger la liste (fluide pour enchaîner).
  _afterRemoved() {
    const n = Math.max(0, (this._lastCount || 1) - 1);
    this._lastCount = n;
    const top = document.getElementById('d-send-all');
    const bottom = document.getElementById('d-send-all-bottom');
    const dropBottom = () => {
      if (!bottom) return;
      try { bottom.closest('div').remove(); } catch (e) { bottom.remove(); }
    };
    if (n <= 0) {
      if (top) top.classList.add('hidden');
      dropBottom();
      const list = document.getElementById('d-list');
      if (list) list.innerHTML = this._emptyStateHTML();
      try { this._syncBatchUI(); } catch (e) {}
      return;
    }
    if (top) { top.classList.remove('hidden'); top.textContent = `Tout envoyer (${n})`; }
    if (n > 1) { if (bottom) bottom.textContent = `Tout envoyer (${n})`; }
    else dropBottom();
  },

  async _cleanupBroken() {
    if (!App.api || !App.api.cleanup_broken_drafts) {
      Toast.error('Fonction indisponible — rafraîchis la page.');
      return;
    }
    const ok = await Dialog.confirm(
      'Supprimer tous les brouillons où l’IA a refusé d’écrire '
      + '(« Je ne peux pas rédiger… », « PROBLÈME MAJEUR… ») ? '
      + 'Les vrais brouillons ne sont pas touchés.',
      { title: 'Vider les cassés', okLabel: 'Supprimer',
        cancelLabel: 'Annuler', danger: true }
    );
    if (!ok) return;
    const btn = document.getElementById('d-cleanup-broken');
    if (btn) { btn.disabled = true; btn.textContent = 'Nettoyage…'; }
    let res;
    try { res = await App.api.cleanup_broken_drafts(); }
    catch (e) { Toast.friendlyError(e, 'Le nettoyage a échoué.'); }
    finally {
      if (btn) { btn.disabled = false; btn.textContent = 'Vider les cassés'; }
    }
    if (res && res.ok) Toast.success(`${res.total} brouillon(s) cassé(s) supprimé(s).`);
    else if (res) {
      console.warn('[drafts] nettoyage partiel', res.errors);
      Toast.warn('Nettoyage partiel — certains brouillons n’ont pas pu être supprimés.');
    }
    await this.refresh();
  },

  // Envoi groupe : approuve et envoie d'un coup TOUS les brouillons en
  // attente, via un worker cote serveur (on peut fermer la page sans
  // interrompre l'envoi). Confirmation avec le NOMBRE de mails avant de
  // partir, puis barre de progression + bouton Arreter ici meme. Respecte
  // l'espacement entre 2 envois configure dans les reglages autopilote
  // (send_delay_seconds) pour proteger la reputation des adresses.

  // Suivi de l'envoi groupé en cours (poll du statut serveur).
  _batchPollId: null,
  _batchPollFails: 0,
  _batchLocked: false,
  _lastCount: 0,

  async _sendAll() {
    if (!App.api || !App.api.get_drafts || !App.api.draft_approve) {
      Toast.error('Fonction indisponible — rafraîchis la page.');
      return;
    }
    if (!App.api.drafts_send_all_start) {
      Toast.error('Le serveur n’a pas encore la fonction « Tout envoyer en série ». Rafraîchis la page.');
      return;
    }
    const n = this._lastCount || 0;
    if (!n) {
      Toast.info('Aucun brouillon à envoyer.');
      return;
    }
    const ok = await Dialog.confirm(
      n > 1
        ? `Envoyer d’un coup les ${n} brouillons en attente ? Chaque mail part tel quel, sans relecture supplémentaire.`
        : 'Envoyer le brouillon en attente ?',
      {
        title: 'Tout envoyer',
        okLabel: `Confirmer l’envoi de ${n} mail${n > 1 ? 's' : ''}`,
        cancelLabel: 'Annuler',
      }
    );
    if (!ok) return;
    // On lance l'envoi côté serveur (worker thread) : ça permet au Cockpit
    // d'afficher un encadré live, et au navigateur de fermer la page sans
    // interrompre l'envoi.
    let startRes;
    try { startRes = await App.api.drafts_send_all_start({}); }
    catch (e) {
      Toast.friendlyError(e, 'Impossible de démarrer l’envoi groupé.');
      return;
    }
    if (!startRes || !startRes.ok) {
      Toast.error((startRes && startRes.error) || 'Démarrage refusé par le serveur.');
      await this._syncBatchUI();
      return;
    }
    Toast.info(`Envoi groupé démarré (${n} mails). Tu peux quitter la page, ça continue côté serveur.`);
    await this._syncBatchUI();
  },

  // Interroge le serveur : un envoi groupé tourne-t-il ? Si oui → barre de
  // progression + bouton Arrêter + cartes figées. Appelé après chaque
  // refresh pour retrouver un envoi déjà en cours (lancé ici, depuis le
  // Cockpit, ou avant un rechargement de page).
  async _syncBatchUI() {
    if (!App.api || !App.api.drafts_send_all_status) return;
    let s;
    try { s = await App.api.drafts_send_all_status({}); }
    catch (e) { console.warn('drafts_send_all_status KO', e); return; }
    if (s && s.running) {
      this._renderBatchBanner(s);
      this._setBatchLock(true);
      this._startBatchPolling();
    } else {
      this._removeBatchBanner();
      if (this._batchLocked) this._setBatchLock(false);
    }
  },

  _startBatchPolling() {
    if (this._batchPollId) return;
    this._batchPollFails = 0;
    this._batchPollId = App.viewInterval(async () => {
      let s;
      try {
        s = await App.api.drafts_send_all_status({});
        this._batchPollFails = 0;
      } catch (e) {
        this._batchPollFails += 1;
        if (this._batchPollFails >= 4) {
          this._stopBatchPolling();
          this._removeBatchBanner();
          this._setBatchLock(false);
          Toast.friendlyError(e, 'Impossible de suivre l’envoi groupé. Rafraîchis la page.');
        }
        return;
      }
      if (s && s.running) { this._renderBatchBanner(s); return; }
      // Terminé (ou arrêté) : bilan + retour à la normale.
      this._stopBatchPolling();
      this._removeBatchBanner();
      this._setBatchLock(false);
      this._batchSummaryToast(s);
      await this.refresh();
    }, 1500);
  },

  _stopBatchPolling() {
    if (this._batchPollId) {
      clearInterval(this._batchPollId);
      this._batchPollId = null;
    }
  },

  // Fige / libère l'écran pendant un envoi groupé : boutons "Tout envoyer"
  // et boutons des cartes désactivés (évite un double traitement).
  _setBatchLock(locked) {
    this._batchLocked = locked;
    ['d-send-all', 'd-send-all-bottom'].forEach(bid => {
      const b = document.getElementById(bid);
      if (b) b.disabled = locked;
    });
    document.querySelectorAll('#d-list article[data-idx]').forEach(card => {
      card.querySelectorAll('button').forEach(b => { b.disabled = locked; });
      card.style.opacity = locked ? '0.6' : '1';
    });
  },

  _renderBatchBanner(s) {
    const host = document.getElementById('d-batch');
    if (!host) return;
    const total = s.total || 0;
    const done = (s.sent || 0) + (s.errors || 0);
    const pct = total ? Math.min(100, Math.round((done / total) * 100)) : 0;
    let banner = host.querySelector('[data-batch-banner]');
    if (!banner) {
      host.innerHTML = `
        <div data-batch-banner class="card p-4 mb-4">
          <div class="flex items-center justify-between gap-3 mb-2">
            <div class="text-sm font-semibold">
              Envoi groupé en cours — <span data-batch-count>…</span>
            </div>
            <button data-batch-stop class="btn btn-secondary btn-sm"
                    style="border-color: hsl(var(--danger) / 0.5); color: hsl(var(--danger-text));"
                    title="Demande l’arrêt : le mail en cours part, les suivants restent en brouillon.">
              Arrêter
            </button>
          </div>
          <div class="h-2 rounded-full bg-bg border border-border overflow-hidden">
            <div data-batch-bar class="h-full rounded-full bg-accent-strong"
                 style="width:0%; transition: width 400ms;"></div>
          </div>
          <div data-batch-current class="text-xs text-text-muted mt-2"></div>
        </div>`;
      banner = host.querySelector('[data-batch-banner]');
      const stopBtn = host.querySelector('[data-batch-stop]');
      if (stopBtn) stopBtn.onclick = () => this._stopBatch(stopBtn);
    }
    const countEl = banner.querySelector('[data-batch-count]');
    if (countEl) countEl.textContent = total ? `${done}/${total}` : '…';
    const bar = banner.querySelector('[data-batch-bar]');
    if (bar) bar.style.width = pct + '%';
    const cur = banner.querySelector('[data-batch-current]');
    if (cur) {
      cur.textContent = s.stop_requested
        ? 'Arrêt demandé — le mail en cours se termine…'
        : (s.current_name ? `En cours : ${s.current_name}` : '');
    }
  },

  _removeBatchBanner() {
    const host = document.getElementById('d-batch');
    if (host) host.innerHTML = '';
  },

  async _stopBatch(stopBtn) {
    if (!App.api || !App.api.drafts_send_all_stop) {
      Toast.error('Fonction indisponible — rafraîchis la page.');
      return;
    }
    if (stopBtn) { stopBtn.disabled = true; stopBtn.textContent = 'Arrêt…'; }
    try {
      const r = await App.api.drafts_send_all_stop({});
      if (r && r.ok) {
        Toast.info('Arrêt demandé — le mail en cours se termine, puis ça s’arrête.');
      } else {
        Toast.error((r && r.error) || 'Arrêt impossible.');
        if (stopBtn) { stopBtn.disabled = false; stopBtn.textContent = 'Arrêter'; }
      }
    } catch (e) {
      Toast.friendlyError(e, 'Arrêt impossible pour le moment.');
      if (stopBtn) { stopBtn.disabled = false; stopBtn.textContent = 'Arrêter'; }
    }
  },

  // Petit bilan de fin d'envoi groupé (succès, échecs, arrêt manuel).
  _batchSummaryToast(s) {
    if (!s) return;
    const sent = s.sent || 0;
    const errors = s.errors || 0;
    if (errors > 0) {
      console.warn('[drafts] échecs envoi groupé', s.error_msgs || []);
      const first = (s.error_msgs || [])[0] || {};
      const hint = first.reason
        ? ` Premier échec : ${first.name || first.email || '?'} — ${first.reason}`
        : '';
      Toast.warn(`Envoi groupé terminé : ${sent} envoyé(s), ${errors} échec(s).${hint}`);
    } else if (s.stop_requested) {
      Toast.info(`Envoi arrêté — ${sent} mail(s) parti(s) avant l’arrêt.`);
    } else {
      Toast.success(`Envoi groupé terminé : ${sent} mail(s) envoyé(s) — tu peux les revoir dans Mails → Envoyés.`);
    }
  },

  async _wipeAll() {
    if (!App.api || !App.api.cleanup_all_pending_drafts) {
      Toast.error('Fonction indisponible — rafraîchis la page.');
      return;
    }
    const btn = document.getElementById('d-wipe-all');
    if (!btn) return;
    const ok = await Dialog.confirm(
      'Supprimer TOUS les brouillons en attente, les bons comme les mauvais ? '
      + 'C’est définitif (les prospects, eux, ne bougent pas).',
      { title: 'Tout vider', okLabel: 'Tout supprimer',
        cancelLabel: 'Annuler', danger: true }
    );
    if (!ok) return;
    btn.disabled = true;
    btn.textContent = 'Suppression…';
    let res;
    try { res = await App.api.cleanup_all_pending_drafts(); }
    catch (e) { Toast.friendlyError(e, 'La suppression a échoué.'); }
    finally {
      btn.disabled = false;
      btn.textContent = 'Tout vider';
    }
    if (res && res.ok) Toast.success(`${res.total} brouillon(s) supprimé(s).`);
    else if (res) {
      console.warn('[drafts] vidage partiel', res.errors);
      Toast.warn('Vidage partiel — certains brouillons n’ont pas pu être supprimés.');
    }
    await this.refresh();
  },

  async _cleanup() {
    if (!App.api || !App.api.cleanup_empty_drafts) {
      Toast.error('Fonction indisponible — rafraîchis la page.');
      return;
    }
    const ok = await Dialog.confirm(
      'Supprimer tous les brouillons en attente qui n’ont jamais reçu '
      + 'de contenu (coquilles vides) ? Les vrais brouillons (avec texte) '
      + 'ne sont pas touchés, les prospects non plus.',
      { title: 'Vider les coquilles vides', okLabel: 'Supprimer',
        cancelLabel: 'Annuler', danger: true }
    );
    if (!ok) return;
    const btn = document.getElementById('d-cleanup');
    if (btn) { btn.disabled = true; btn.textContent = 'Nettoyage…'; }
    let res;
    try { res = await App.api.cleanup_empty_drafts({}); }
    catch (e) { Toast.friendlyError(e, 'Le nettoyage a échoué.'); }
    finally {
      if (btn) { btn.disabled = false; btn.textContent = 'Vider les coquilles vides'; }
    }
    if (res && res.ok) {
      Toast.success(`${res.total} coquille(s) vide(s) supprimée(s).`);
    } else if (res) {
      console.warn('[drafts] nettoyage partiel', res.errors);
      Toast.warn('Nettoyage partiel — certaines coquilles n’ont pas pu être supprimées.');
    }
    await this.refresh();
  },

  async refresh() {
    const list = document.getElementById('d-list');
    if (!list) return;
    const sendAllTop = document.getElementById('d-send-all');
    if (!App.api) {
      list.innerHTML = this._preview();
      return;
    }
    list.innerHTML = `<div class="text-center py-12 text-text-muted">Chargement…</div>`;
    let data;
    try { data = await App.api.get_drafts(); }
    catch (e) {
      console.warn('get_drafts KO', e);
      Toast.friendlyError(e, 'Impossible de charger les brouillons.');
      this._lastCount = 0;
      if (sendAllTop) sendAllTop.classList.add('hidden');
      list.innerHTML = `
        <div class="card p-6 text-center">
          <p class="text-text-secondary mb-4">
            Impossible de charger les brouillons. Vérifie ta connexion, puis réessaie.
          </p>
          <button class="btn btn-secondary" onclick="Drafts.refresh()">Réessayer</button>
        </div>`;
      return;
    }
    if (!data || !data.ok || !data.rows || data.rows.length === 0) {
      // Liste vide → pas de bouton "Tout envoyer" (rien à envoyer).
      this._lastCount = 0;
      if (sendAllTop) sendAllTop.classList.add('hidden');
      list.innerHTML = this._emptyStateHTML();
      await this._syncBatchUI();
      return;
    }
    this._lastCount = data.rows.length;
    if (sendAllTop) {
      sendAllTop.classList.remove('hidden');
      sendAllTop.textContent = `Tout envoyer (${data.rows.length})`;
    }
    const banner = data.truncated
      ? `<div class="card p-3 sm:p-4 mb-3 text-sm text-text-muted">
            On affiche les ${data.rows.length} brouillons les plus récents
            (limite ${data.limit_per_source || 200} par source).
            Approuve ou rejette pour faire descendre la file.
          </div>`
      : '';
    // Bouton "Tout envoyer" duplique au pied de la liste : evite a Jordan
    // de remonter en haut quand il vient de tout relire en scrollant.
    const sendAllFooter = data.rows.length > 1
      ? `<div class="flex justify-end pt-4">
           <button id="d-send-all-bottom" class="btn btn-primary"
                   title="Envoie d’un coup tous les brouillons en attente, après confirmation.">
             Tout envoyer (${data.rows.length})
           </button>
         </div>`
      : '';
    // Alerte globale : si des brouillons n'ont pas pu être relus (correcteur
    // en panne, souvent plus de crédit), on le dit une fois, en clair, en tête
    // de liste — au lieu de laisser Jordan deviner devant des mails sans note.
    const nDown = data.rows.filter(r => r && r.review_verdict === 'engine_down').length;
    const engineBanner = nDown
      ? `<div class="card p-4 mb-4 border" style="border-color: hsl(var(--warning) / 0.5); background: hsl(var(--warning) / 0.08)">
           <div class="flex items-start gap-3">
             <span class="text-xl leading-none">⚙️</span>
             <div class="text-sm min-w-0">
               <div class="font-semibold text-warning mb-1">Le correcteur (2è IA) est en panne</div>
               <p class="text-text-secondary" style="text-wrap: pretty">
                 ${nDown} mail${nDown > 1 ? 's' : ''} ${nDown > 1 ? 'attendent' : 'attend'} ici parce
                 qu'aucune IA n'a pu ${nDown > 1 ? 'les' : 'le'} relire (le plus souvent : plus de crédit).
                 ${nDown > 1 ? 'Ils restent' : 'Il reste'} en brouillon par sécurité — rien n'est perdu.<br>
                 → Recharge tes crédits, ou ajoute une 2è IA dans <b>Réglages</b> : la relecture
                 basculera toute seule dessus la prochaine fois.
               </p>
             </div>
           </div>
         </div>`
      : '';
    list.innerHTML = engineBanner + banner
      + data.rows.map((r, i) => this._card(r, i)).join('')
      + sendAllFooter;
    this._bind(data.rows);
    const bottomBtn = document.getElementById('d-send-all-bottom');
    if (bottomBtn) bottomBtn.onclick = () => this._sendAll();
    // Un envoi groupé tourne peut-être déjà (Cockpit, rechargement…) :
    // on raccroche la barre de progression et on fige les cartes.
    await this._syncBatchUI();
  },

  _card(r, idx) {
    const ts = (r.ts || '').slice(0, 16);
    const meta = [];
    if (r.email) meta.push(this._esc(r.email));
    if (r.city)  meta.push(this._esc(r.city));
    if (ts)      meta.push(ts);
    const iaLabel = this._iaLabel(r.provider, r.model);
    if (iaLabel) meta.push(iaLabel);
    // Adresse d'expédition exigée par le modèle (câblage modèle→adresse) :
    // Jordan voit AVANT d'approuver depuis quelle boîte le mail partira.
    if (r.sender_address) meta.push('départ : ' + this._esc(r.sender_address));
    let badge = '';
    if (r.source === 'creator') {
      badge = `<span class="text-xs px-2 py-0.5 rounded-full bg-accent/15 text-accent">🎬 Créateur</span>`;
    } else if (r.source === 'convoy') {
      const camp = r.campaign_name || r.offer_name || 'Convoi';
      badge = `<span class="text-xs px-2 py-0.5 rounded-full bg-accent/15 text-accent">${this._esc(camp)}</span>`;
    } else if (r.kind && r.kind !== 'first_contact') {
      badge = `<span class="text-xs px-2 py-0.5 rounded-full bg-bg border border-border text-text-muted">${this._esc(this._kindLabel(r.kind))}</span>`;
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
    // On prefixe par <base target="_blank"> pour que tous les liens
    // cliques dans l apercu s ouvrent dans un nouvel onglet plutot
    // que dans l iframe sandbox (sinon les sites a X-Frame-Options
    // DENY type Pixel Pros affichent une erreur Firefox).
    const htmlSrc = hasHtml
      ? (`<base target="_blank">` + String(r.body_html))
          .replace(/"/g, '&quot;').replace(/'/g, '&#39;')
      : '';
    // Info-bulle du bouton Approuver : dit clairement ce qui va se passer.
    // Les deux libellés diffèrent parce que le devenir du mail diffère :
    // Convoi = il rejoint la file de sa campagne, ailleurs = envoi direct.
    const approveTitle = r.source === 'convoy'
      ? 'Approuver : le mail rejoint la file de sa campagne du Convoi et partira à son rythme (pas immédiatement)'
      : 'Approuver : le mail part après 5 secondes (le temps d’annuler)';
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
            ${this._relanceLine(r.relance)}
          </div>
        </header>
        ${reviewBanner}
        <div class="text-sm font-semibold text-accent mb-2 break-words">OBJET : ${this._esc(r.subject)}</div>
        ${hasHtml ? `
          <div class="flex gap-2 mb-2 text-xs">
            <button class="d-toggle-view px-2 py-1 rounded-md bg-accent-strong text-white"
                    data-mode="preview" data-idx="${idx}">Aperçu</button>
            <button class="d-toggle-view px-2 py-1 rounded-md bg-bg border border-border text-text-muted"
                    data-mode="source" data-idx="${idx}">Source / éditer</button>
          </div>
          <iframe data-preview
                  title="Aperçu du mail tel qu’il sera reçu"
                  sandbox="allow-popups allow-popups-to-escape-sandbox"
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
        <footer class="flex flex-col sm:flex-row sm:items-center gap-2 mt-4 pt-4 border-t border-border">
          ${r.prospect_id ? `
            <button class="btn btn-secondary btn-sm justify-center" data-act="timeline"
                    data-pid="${this._esc(r.prospect_id)}"
                    title="Voir tout son parcours sur une seule ligne du temps">
              📋 Voir tout son parcours
            </button>` : ''}
          <div class="flex-1 hidden sm:block"></div>
          <button class="btn btn-secondary justify-center" data-act="reject"
                  title="Rejeter ce brouillon">Rejeter</button>
          <button class="btn btn-primary justify-center" data-act="approve"
                  title="${approveTitle}">${r.source === 'convoy' ? 'Approuver (mise en file)' : 'Approuver &amp; envoyer'}</button>
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
            b.className = 'd-toggle-view px-2 py-1 rounded-md bg-accent-strong text-white';
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
      const rejectBtn   = card.querySelector('[data-act="reject"]');
      const approveBtn  = card.querySelector('[data-act="approve"]');
      const timelineBtn = card.querySelector('[data-act="timeline"]');
      if (timelineBtn) {
        timelineBtn.onclick = () =>
          App.show('prospect_timeline', { id: timelineBtn.dataset.pid });
      }
      // Envoi réel du brouillon (appelé après la fenêtre d'annulation).
      const doApprove = async () => {
        // On ne transmet le corps QUE s'il a vraiment été retouché :
        // un corps intact renvoyé quand même faisait perdre au serveur
        // la version HTML du mail (mise en forme + boutons) — le
        // prospect recevait du texte brut.
        const original = (rows[idx] || {}).body || '';
        const edited = bodyEl ? bodyEl.value : original;
        const payload = { id, source, key: id };
        if (edited.replace(/\r\n/g, '\n').trim()
            !== original.replace(/\r\n/g, '\n').trim()) {
          payload.body = edited;
        }
        setBusy(true);
        const originalLabel = approveBtn.textContent;
        approveBtn.textContent = 'Envoi…';
        let r;
        try {
          r = await App.api.draft_approve(payload);
        } catch (e) {
          console.error('draft_approve KO', e);
          Toast.friendlyError(e, 'Erreur réseau pendant l’envoi.');
          setBusy(false);
          approveBtn.textContent = originalLabel;
          return;
        }
        if (!r || r.ok === false) {
          const why = (r && r.error) || 'réponse vide du serveur';
          Toast.error('Envoi refusé : ' + why);
          setBusy(false);
          approveBtn.textContent = originalLabel;
          return;
        }
        // Pas de doute après le clic : à qui c'est parti, et où le revoir.
        const sentTo = ((rows[idx] || {}).email || '').trim();
        Toast.success(source === 'convoy'
          ? 'Brouillon approuvé — mis en file d’envoi (il part au rythme du Convoi).'
          : ('Mail envoyé' + (sentTo ? ` à ${sentTo}` : '') +
             ' ✓ — tu peux le revoir dans Mails → Envoyés.'));
        card.style.transition = 'opacity 200ms';
        card.style.opacity = '0';
        setTimeout(() => { try { card.remove(); } catch (e) {} }, 220);
        // Avant : refresh() complet → toute la liste se vidait en
        // « Chargement… » puis se reconstruisait (« la page se recharge »),
        // et un envoi lancé sur une autre carte sautait. Maintenant : on
        // enlève juste cette carte et on met à jour les compteurs en place.
        this._afterRemoved();
      };
      if (rejectBtn) {
        rejectBtn.addEventListener('click', async (ev) => {
          ev.preventDefault();
          ev.stopPropagation();
          if (!App.api || !App.api.draft_reject) {
            Toast.error('Fonction indisponible — rafraîchis la page.');
            return;
          }
          const okGo = await Dialog.confirm(
            'Rejeter ce brouillon ? Le mail ne partira pas et le brouillon disparaîtra.',
            { title: 'Rejeter ce brouillon', okLabel: 'Rejeter',
              cancelLabel: 'Garder', danger: true }
          );
          if (!okGo) return;
          setBusy(true);
          rejectBtn.textContent = 'Rejet…';
          let r;
          try {
            r = await App.api.draft_reject({ id, source, key: id });
          } catch (e) {
            console.error('draft_reject KO', e);
            Toast.friendlyError(e, 'Erreur réseau pendant le rejet.');
            setBusy(false);
            rejectBtn.textContent = 'Rejeter';
            return;
          }
          if (!r || r.ok === false) {
            const why = (r && (r.error || r.reason)) || 'réponse vide du serveur';
            Toast.error('Rejet refusé : ' + why);
            setBusy(false);
            rejectBtn.textContent = 'Rejeter';
            return;
          }
          Toast.success('Brouillon rejeté.');
          // OK : on cache la carte tout de suite (feedback immediat) puis
          // on refresh la liste depuis le serveur.
          card.style.transition = 'opacity 200ms';
          card.style.opacity = '0';
          setTimeout(() => { try { card.remove(); } catch (e) {} }, 220);
          this._afterRemoved();
        });
      }
      if (approveBtn) {
        approveBtn.addEventListener('click', (ev) => {
          ev.preventDefault();
          ev.stopPropagation();
          if (!App.api || !App.api.draft_approve) {
            Toast.error('Fonction indisponible — rafraîchis la page.');
            return;
          }
          if (source === 'convoy') {
            // Côté Convoi, approuver = simple mise en file (pas d'envoi
            // immédiat) → pas besoin de fenêtre d'annulation.
            doApprove();
            return;
          }
          // Envoi rapide (réglage par défaut) : le mail part tout de suite,
          // sans compte à rebours — pensé pour enchaîner plusieurs validations
          // sans attendre. Si Jordan a coupé l'envoi rapide, on garde la
          // fenêtre de grâce de 5 s pour pouvoir annuler.
          if (this._isFast()) {
            doApprove();
            return;
          }
          this._startGrace(card, doApprove);
        });
      }
    });
  },

  // Fenêtre de grâce avant envoi : remplace les boutons de la carte par
  // « Envoi dans X s… [Annuler] ». Annuler → retour à l'état normal ;
  // sinon l'envoi part tout seul à la fin du compte à rebours.
  _startGrace(card, onSend) {
    const footer = card.querySelector('footer');
    if (!footer || footer.querySelector('[data-grace]')) {
      return;
    }
    const visibleBtns = Array.from(footer.querySelectorAll('button'))
      .filter(b => !b.classList.contains('hidden'));
    visibleBtns.forEach(b => b.classList.add('hidden'));
    const box = document.createElement('div');
    box.setAttribute('data-grace', '1');
    box.className = 'flex items-center justify-end gap-3 w-full';
    box.innerHTML = `
      <span class="text-sm text-text-secondary">
        Envoi dans <strong data-grace-count>5</strong> s…
      </span>
      <button type="button" class="btn btn-secondary" data-grace-cancel>Annuler</button>`;
    footer.appendChild(box);
    let secs = 5;
    const countEl = box.querySelector('[data-grace-count]');
    const iv = setInterval(() => {
      secs -= 1;
      if (countEl && secs > 0) countEl.textContent = String(secs);
    }, 1000);
    const cleanup = () => {
      clearInterval(iv);
      try { box.remove(); } catch (e) {}
      visibleBtns.forEach(b => b.classList.remove('hidden'));
    };
    const to = setTimeout(() => {
      cleanup();
      // Si la liste a été rechargée entre-temps, la carte n'existe plus :
      // on n'envoie PAS dans le dos de l'utilisateur.
      if (!document.body.contains(card)) {
        Toast.info('La liste a changé — l’envoi en attente a été annulé.');
        return;
      }
      onSend();
    }, 5000);
    const cancelBtn = box.querySelector('[data-grace-cancel]');
    if (cancelBtn) cancelBtn.onclick = () => { clearTimeout(to); cleanup(); };
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
    if (!r) return '';
    // Panne du correcteur (plus de crédit / coupure) : on n'affiche PAS un
    // faux « 0/10 ». On explique la panne, sans rouge accusateur : ce n'est
    // pas le mail qui est mauvais, c'est la relecture qui n'a pas pu se faire.
    if (r.review_verdict === 'engine_down') {
      const why = (r.review_comment
        || 'Aucune IA disponible pour relire (plus de crédit ou coupure).').trim();
      return `
        <div class="mb-3 px-3 py-2 rounded-lg border text-xs sm:text-sm bg-warning/10 border-warning/40 text-warning"
             style="text-wrap: pretty">
          <span class="font-semibold">⚙️ 2è IA en panne — pas de note</span>
          <span class="text-text-secondary font-normal"> — ${this._esc(why)}</span>
        </div>`;
    }
    if (r.review_score == null) return '';
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
    // Retouche unique de la 2e IA (demande Jordan 17/06) : si elle a fait une
    // petite modif GARDEE, on montre l'ancienne ET la nouvelle note + le type
    // de retouche. Si elle a TESTE une modif mais qu'on l'a ecartee (elle
    // n'ameliorait pas), on le signale discretement (le mail d'origine reste).
    const before = (r.review_score_before == null) ? null
      : Math.max(0, Math.min(10, parseInt(r.review_score_before, 10) || 0));
    const after = (r.review_score_after == null) ? null
      : Math.max(0, Math.min(10, parseInt(r.review_score_after, 10) || 0));
    const applied = !!r.review_modif_applied;
    const modifType = (r.review_modif_type || '').trim();
    let scoreLabel = `${score}/10`;
    let editPart = '';
    if (applied) {
      if (before != null && after != null) scoreLabel = `${before} → ${after}/10`;
      editPart = ` <span class="font-semibold">· ✏️ retouché${modifType ? ' : ' + this._esc(modifType) : ''}</span>`;
    }
    const commentPart = comment
      ? ` <span class="text-text-secondary font-normal">— ${this._esc(comment)}</span>`
      : '';
    return `
      <div class="mb-3 px-3 py-2 rounded-lg border text-xs sm:text-sm ${cls}"
           style="text-wrap: pretty">
        <span class="font-semibold">2è IA · ${label} · ${scoreLabel}</span>${editPart}${commentPart}
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
      web_inferred:  'adresse devinée à partir du domaine du site — pas garantie : si elle est fausse, le mail reviendra et la fiche sera marquée, sans gravité',
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
  // (couleurs en tokens du thème : lisibles en clair comme en sombre)
  _audienceBadge(audience) {
    const aud = (audience || '').toLowerCase();
    if (aud === 'creator') {
      return `<span class="text-xs px-2 py-0.5 rounded-full bg-accent/15 text-accent-text border border-accent/30">Créateur / Influenceur</span>`;
    }
    if (aud === 'pro') {
      return `<span class="text-xs px-2 py-0.5 rounded-full bg-info/15 text-info-text border border-info/30">Pro / Entreprise</span>`;
    }
    return '';
  },

  // Ligne « 📅 1er contact le X · à envoyer aujourd'hui » pour les relances
  // (demande Jordan : voir d'un coup d'œil que le timing est bon).
  _relanceLine(rel) {
    if (!rel || !rel.first_contact) return '';
    const today = new Date().toISOString().slice(0, 10);
    const fmt = (d) => { const p = String(d).split('-'); return `${p[2]}/${p[1]}/${p[0]}`; };
    let when, cls;
    if (rel.due_date === today) { when = 'à envoyer aujourd’hui'; cls = 'text-accent font-semibold'; }
    else if (rel.due_date < today) { when = `à envoyer (en retard depuis le ${fmt(rel.due_date)})`; cls = 'text-warning font-semibold'; }
    else { when = `à envoyer le ${fmt(rel.due_date)}`; cls = 'text-text-muted'; }
    return `<div class="text-xs mt-1.5 ${cls}">📅 1er contact le ${fmt(rel.first_contact)} · ${when}</div>`;
  },

  // Traduit le type de brouillon (code technique) en français lisible.
  _kindLabel(kind) {
    const k = String(kind || '').toLowerCase();
    const labels = {
      follow_up_7d:    'Relance après 7 jours',
      follow_up_30d:   'Relance après 30 jours',
      dormant_recycle: 'Reprise de contact (prospect dormant)',
      welcome_at_paid: 'Mail de bienvenue client',
      cross_sell_30d:  'Offre complémentaire (30 jours)',
      nps_90d:         'Demande d’avis (90 jours)',
      convoy:          'Convoi',
      needs_review:    'À relire',
    };
    if (labels[k]) return labels[k];
    if (k.startsWith('delivery_followup_')) return 'Suivi après livraison';
    return k.replace(/_/g, ' ');
  },

  // Affiche l'IA qui a écrit le mail en clair (« IA : DeepSeek »), sans
  // jargon fournisseur/modèle. Inconnue → on n'affiche rien.
  _iaLabel(provider, model) {
    const hay = `${provider || ''} ${model || ''}`.toLowerCase();
    if (!hay.trim()) return '';
    const names = {
      deepseek: 'DeepSeek', anthropic: 'Claude', claude: 'Claude',
      openai: 'OpenAI', gpt: 'OpenAI', mistral: 'Mistral',
      gemini: 'Gemini', google: 'Gemini', groq: 'Groq', ollama: 'IA locale',
    };
    for (const key of Object.keys(names)) {
      if (hay.includes(key)) return `IA : ${names[key]}`;
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
          Connecte-toi à la base pour voir les vrais brouillons.
        </p>
      </div>
    `;
  },
};
