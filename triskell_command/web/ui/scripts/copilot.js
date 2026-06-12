/* Le Copilote — volet de discussion écrit, ouvrable depuis TOUS les écrans.
 *
 * Étape 1 de la vision « copilote omniprésent » (10/06/2026) :
 *  - une seule présence : ce volet est la porte d’entrée de l’assistant
 *    (le bouton « Allô Claude » du Cockpit, Ctrl+Espace et la barre-guide
 *    mènent tous ici) ;
 *  - il répond MOT À MOT (route /api/copilot_stream, secours « bloc » via
 *    copilot_send pour les navigateurs qui ne savent pas streamer et le
 *    mode desktop) ;
 *  - le fil est PERSISTÉ côté serveur : on ferme, on rouvre, il est là ;
 *  - il AGIT (mêmes pouvoirs que le vocal : lancer une prospection,
 *    Auto-pilote, abandonner une mission, ouvrir un écran) ;
 *  - le mode vocal 📞 existant reste accessible d’ici, et ses tours sont
 *    reversés au fil écrit à la fin de l’appel : UNE seule conversation.
 *
 * Aucune dépendance dure : si quelque chose manque (App, Claude…), le
 * volet dégrade proprement. Il ne casse JAMAIS l’app.
 */

const Copilot = {
  _open: false,
  _busy: false,
  _loaded: false,
  _mounted: false,

  // ---------------------------------------------------------------- open/close
  open() {
    this._mount();
    const panel = document.getElementById('copilot-panel');
    if (!panel) return;
    this._open = true;
    panel.classList.add('cop-visible');
    // Grand écran : la discussion se met EN COLONNE à côté du contenu
    // (l'app se pousse, on continue à travailler en parlant).
    document.body.classList.add('cop-open');
    this.setBadge(false);
    if (this._memoryOpen) this.toggleMemory();   // toujours rouvrir sur le fil
    if (this._journalOpen) this.toggleJournal();
    if (!this._loaded) {
      this._loadThread();
    } else {
      this._consumePendingAdvice();
      this._renderQuickChips();
    }
    // Focus différé : laisse l’animation d’ouverture se finir
    setTimeout(() => {
      const input = document.getElementById('copilot-input');
      if (input && window.matchMedia('(min-width: 641px)').matches) input.focus();
    }, 180);
  },

  close() {
    const panel = document.getElementById('copilot-panel');
    if (panel) panel.classList.remove('cop-visible');
    document.body.classList.remove('cop-open');
    this._open = false;
    this._stopDictation();
  },

  toggle() {
    if (this._open) this.close();
    else this.open();
  },

  /** Question posée depuis l'extérieur (la zone « Dis-moi ce que tu veux
   *  faire » de Perceval) : ouvre la colonne, attend que le fil soit
   *  chargé, puis envoie — sans jamais perdre la question. */
  askFromOutside(text) {
    const q = String(text == null ? '' : text).trim();
    if (!q) return;
    this.open();
    if (this._loaded && !this._busy) { this.send(q); return; }
    let tries = 0;
    const timer = setInterval(() => {
      tries += 1;
      if (this._loaded && !this._busy) {
        clearInterval(timer);
        this.send(q);
      } else if (tries > 80) { // ~8 s : le fil ne vient pas, on n'insiste pas
        clearInterval(timer);
      }
    }, 100);
  },

  isOpen() { return this._open; },

  /** Pastille « le copilote a quelque chose pour toi » (veille proactive). */
  setBadge(on) {
    document.querySelectorAll('.copilot-badge-dot').forEach((d) => {
      d.classList.toggle('hidden', !on);
    });
  },

  // ---------------------------------------------------------------- fil
  async _loadThread() {
    const box = document.getElementById('copilot-messages');
    if (!box) return;
    box.innerHTML = '<div class="cop-loading">…</div>';
    let data = null;
    try {
      if (typeof App !== 'undefined' && App.api && App.api.copilot_thread) {
        data = await App.api.copilot_thread({});
      }
    } catch (e) { /* fil indisponible : on repart à zéro visuellement */ }
    box.innerHTML = '';
    this._proposals = (data && data.proposals && typeof data.proposals === 'object')
      ? data.proposals : {};
    this._habits = (data && data.habits && typeof data.habits === 'object')
      ? data.habits : {};
    this._shortcuts = (data && Array.isArray(data.shortcuts)) ? data.shortcuts : [];
    const msgs = (data && data.ok && Array.isArray(data.messages)) ? data.messages : [];
    if (!msgs.length) {
      this._renderWelcome(box);
    } else {
      msgs.forEach((m) => this._appendBubble(m.role, m.content,
        { md: true, kind: m.kind, nav: m.nav, pid: m.pid, hid: m.hid }));
    }
    this._initiative = (data && data.initiative) || 'normal';
    this._trust = (data && data.trust) || null;
    this._loaded = true;
    this._scrollDown(true);
    this._consumePendingAdvice();
    this._renderQuickChips();
    // Le point du jour : si c’est l’heure (et qu’on a déjà fait
    // connaissance), il arrive tout seul, en streaming.
    if (msgs.length && data && data.briefing_due) this._runBriefing();
  },

  /** Le point du jour — généré par le serveur, streamé, persisté au fil. */
  async _runBriefing() {
    if (this._busy) return;
    this._busy = true;
    this._setComposerBusy(true);
    const bubble = this._appendBubble('assistant', '', { streaming: true });
    this._scrollDown(true);
    let finalEvt = null;
    let errorMsg = null;
    let gotAnything = false;
    try {
      const streamed = await this._streamInto(bubble, { briefing: true }, (evt) => {
        gotAnything = true;
        if (evt.type === 'done') finalEvt = evt;
        if (evt.type === 'error') errorMsg = evt.error || 'Erreur inconnue.';
      });
      if (!streamed && !gotAnything) {
        const r = await App.api.copilot_send({
          briefing: true,
          view: (typeof App !== 'undefined' && App.currentView) || '',
        });
        if (r && r.ok) finalEvt = { type: 'done', text: r.text };
        else errorMsg = (r && r.error) || null;
      }
    } catch (e) { /* le point du jour n’est jamais bloquant */ }
    if (finalEvt) {
      this._finishBubble(bubble, finalEvt);
    } else if (errorMsg) {
      this._errorBubble(bubble, errorMsg);
    } else {
      bubble.remove(); // rien à dire / pas de réseau : pas de bulle vide
    }
    this._busy = false;
    this._setComposerBusy(false);
    this._scrollDown();
  },

  /** Raccourcis au-dessus du champ : les boutons ⚡ de l'utilisateur
   *  (étape 5 — les plus utilisés d'abord) + le récap du soir. */
  _renderQuickChips() {
    const bar = document.getElementById('copilot-quick');
    if (!bar) return;
    bar.innerHTML = '';

    const shortcuts = (this._shortcuts || []).slice()
      .sort((a, b) => (b.runs || 0) - (a.runs || 0)
                      || String(b.last_run_at || '').localeCompare(String(a.last_run_at || '')))
      .slice(0, 6);
    shortcuts.forEach((sc) => {
      const b = document.createElement('button');
      b.className = 'cop-chip cop-chip-shortcut';
      b.textContent = '⚡ ' + sc.label + (sc.schedule_label ? ' 📅' : '');
      b.title = sc.schedule_label
        ? `Raccourci + rendez-vous (${sc.schedule_label})` : 'Raccourci';
      b.onclick = () => this._runShortcut(sc, b);
      bar.appendChild(b);
    });

    const h = new Date().getHours();
    if (h >= 17 || h < 4) {
      const b = document.createElement('button');
      b.className = 'cop-chip';
      b.textContent = '🌙 Récap du jour';
      b.onclick = () => this.send('Fais-moi le récap de ma journée : ce qui a été accompli, et ce qui reste pour demain.');
      bar.appendChild(b);
    }
    bar.style.display = bar.children.length ? 'flex' : 'none';
  },

  /** Clic sur un bouton ⚡ : question → envoyée au fil ; action → le
   *  serveur rejoue l'action STOCKÉE via le curseur de confiance. */
  async _runShortcut(sc, btn) {
    if (this._busy) return;
    if (sc.kind === 'question') {
      this.send(sc.question || sc.label);
      return;
    }
    if (btn) { btn.disabled = true; btn.style.opacity = '.6'; }
    let r = null;
    try {
      r = await App.api.copilot_shortcut_run({ id: sc.id });
    } catch (e) { /* rendu d’échec ci-dessous */ }
    if (btn) { btn.disabled = false; btn.style.opacity = ''; }
    const wel = document.querySelector('#copilot-messages .cop-welcome');
    if (wel) wel.remove();
    if (r && r.proposed && r.proposed.id) {
      if (!this._proposals) this._proposals = {};
      this._proposals[r.proposed.id] = r.proposed;
      this._appendProposalCard(r.proposed);
    } else if (r && r.ok && r.summary) {
      this._appendBubble('assistant', '⚡ ' + sc.label + ' : ' + r.summary,
        { md: true, kind: 'event' });
    } else if (r && !r.ok) {
      this._appendBubble('assistant',
        '⚡ ' + sc.label + ' : ' + (r.summary || 'ça n’a pas marché — réessaie.'),
        { md: true, kind: 'event' });
    }
    if (r && r.navigate) this._navigate(r.navigate);
    this._scrollDown(true);
  },

  _renderWelcome(box) {
    const name = (typeof App !== 'undefined' && App.currentUser
                  && App.currentUser.first_name) || 'toi';
    const el = document.createElement('div');
    el.className = 'cop-welcome';
    el.innerHTML = `
      <div class="cop-w-title">👋 Salut ${this._esc(name)}, moi c’est Perceval.</div>
      <div class="cop-w-body">
        Je suis ton copilote. Je vois ton app et ton business en direct,
        je réponds à tes questions, et je peux <b>agir pour toi</b>.
        On reprend toujours la discussion là où on l’a laissée — et je
        <b>retiens ce qui compte</b> (dis-moi « retiens que… », et le 📌
        en haut montre tout ce que je sais).
      </div>
      <div class="cop-w-chips">
        <button class="cop-chip" data-q="Où en est ma prospection ?">Où en est ma prospection ?</button>
        <button class="cop-chip" data-q="Combien de réponses cette semaine ?">Combien de réponses cette semaine ?</button>
        <button class="cop-chip" data-q="Qu’est-ce que je devrais faire en priorité là ?">Je fais quoi en priorité ?</button>
      </div>`;
    box.appendChild(el);
    el.querySelectorAll('.cop-chip').forEach((b) => {
      b.onclick = () => this.send(b.dataset.q);
    });
  },

  /** Affiche (et consomme) le conseil laissé par la veille proactive. */
  _consumePendingAdvice() {
    if (typeof Claude === 'undefined' || !Claude.pendingAdvice) return;
    const adv = Claude.pendingAdvice;
    Claude.pendingAdvice = null;
    try { Claude.setAttention(false); } catch (e) {}
    // Un conseil sans contenu n’existe pas (anti carte vide).
    if (!adv || !adv.ok || (!adv.headline && !adv.advice)) return;
    const box = document.getElementById('copilot-messages');
    if (!box) return;
    const el = document.createElement('div');
    el.className = 'cop-msg cop-assistant cop-advice';
    el.innerHTML = `
      <div class="cop-advice-kicker">💡 Pendant ton absence</div>
      ${adv.headline ? `<div class="cop-advice-headline">${this._esc(adv.headline)}</div>` : ''}
      ${adv.advice ? `<div>${this._md(adv.advice)}</div>` : ''}
      ${adv.suggested_view ? `
        <button class="cop-advice-go" data-view="${this._esc(adv.suggested_view)}">
          ${this._esc(adv.suggested_action_label || 'Y aller')} →
        </button>` : ''}`;
    box.appendChild(el);
    const go = el.querySelector('.cop-advice-go');
    if (go) go.onclick = () => this._navigate(go.dataset.view);
    this._scrollDown(true);
  },

  // ---------------------------------------------------------------- envoi
  async send(text) {
    const input = document.getElementById('copilot-input');
    text = String(text != null ? text : (input ? input.value : '')).trim();
    if (!text || this._busy) return;
    this._busy = true;
    this._setComposerBusy(true);
    if (input) { input.value = ''; this._growInput(); }
    this._stopDictation();

    // Si l’écran d’accueil est encore là, on le retire (la discussion démarre)
    const wel = document.querySelector('#copilot-messages .cop-welcome');
    if (wel) wel.remove();

    this._appendBubble('user', text, { md: false });
    const bubble = this._appendBubble('assistant', '', { streaming: true });
    this._scrollDown(true);

    let finalEvt = null;
    let errorMsg = null;
    let gotAnything = false;

    try {
      const streamed = await this._streamInto(bubble, { question: text }, (evt) => {
        gotAnything = true;
        if (evt.type === 'done') finalEvt = evt;
        if (evt.type === 'error') errorMsg = evt.error || 'Erreur inconnue.';
      });
      if (!streamed && !gotAnything) {
        // Le flux n’a pas pu s’établir → chemin de secours en bloc
        const r = await this._sendBlocking(text);
        if (r && r.ok) finalEvt = { type: 'done', text: r.text, navigate: r.navigate,
                                    action_done: r.action_done, sent_to_thomas: r.sent_to_thomas,
                                    proposed: r.proposed, guide: r.guide };
        else errorMsg = (r && r.error) || 'Je n’ai pas réussi à répondre. Réessaie.';
      }
    } catch (e) {
      if (!gotAnything) {
        try {
          const r = await this._sendBlocking(text);
          if (r && r.ok) finalEvt = { type: 'done', text: r.text, navigate: r.navigate,
                                      action_done: r.action_done, sent_to_thomas: r.sent_to_thomas,
                                      proposed: r.proposed, guide: r.guide };
          else errorMsg = (r && r.error) || 'Je n’ai pas réussi à répondre. Réessaie.';
        } catch (e2) {
          errorMsg = 'Le serveur ne répond pas. Réessaie dans un instant.';
        }
      } else if (!finalEvt) {
        errorMsg = 'La connexion a coupé en cours de réponse. Réessaie.';
      }
    }

    if (finalEvt) this._finishBubble(bubble, finalEvt);
    else this._errorBubble(bubble, errorMsg || 'Je n’ai pas réussi à répondre.');

    this._busy = false;
    this._setComposerBusy(false);
    this._scrollDown();
  },

  async _sendBlocking(text) {
    if (typeof App === 'undefined' || !App.api || !App.api.copilot_send) return null;
    return App.api.copilot_send({
      question: text,
      view: (typeof App !== 'undefined' && App.currentView) || '',
    });
  },

  /** Stream SSE → remplit la bulle au fil de l’eau.
   *  body = {question} ou {briefing:true} ; la vue courante est ajoutée ici.
   *  Renvoie true si le flux a démarré (HTTP ok + body lisible). */
  async _streamInto(bubble, body, onEvent) {
    if (typeof window.fetch !== 'function' || typeof TextDecoder === 'undefined') return false;
    // Mode démo : pas de flux direct — il contournerait l'interception et le
    // copilote pourrait AGIR en réel pendant une démonstration. On retombe
    // sur le secours « bloc » (copilot_send), que le mode démo bloque proprement.
    if (typeof DemoMode !== 'undefined' && DemoMode.isOn && DemoMode.isOn()) return false;
    let res = null;
    try {
      res = await fetch('/api/copilot_stream', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(Object.assign({
          view: (typeof App !== 'undefined' && App.currentView) || '',
        }, body)),
      });
    } catch (e) {
      return false; // réseau/file:// → secours bloc
    }
    if (!res || !res.ok || !res.body || !res.body.getReader) return false;

    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = '';
    let acc = '';
    const textEl = bubble.querySelector('.cop-text');

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let cut;
      while ((cut = buf.indexOf('\n\n')) !== -1) {
        const block = buf.slice(0, cut);
        buf = buf.slice(cut + 2);
        const line = block.split('\n').find((l) => l.startsWith('data:'));
        if (!line) continue;
        let evt = null;
        try { evt = JSON.parse(line.slice(5)); } catch (e) { continue; }
        if (!evt || !evt.type) continue;
        if (evt.type === 'delta' && evt.text) {
          acc += evt.text;
          if (textEl) textEl.textContent = acc;
          this._scrollDown();
        }
        if (onEvent) onEvent(evt);
      }
    }
    return true;
  },

  // ---------------------------------------------------------------- bulles
  _appendBubble(role, content, opts) {
    opts = opts || {};
    const box = document.getElementById('copilot-messages');
    if (!box) return document.createElement('div');
    // Message « proposition » → carte Confirmer/Annuler (état réel serveur)
    if (opts.kind === 'proposal' && opts.pid) {
      const prop = (this._proposals && this._proposals[opts.pid]) || null;
      return this._appendProposalCard(prop || { id: opts.pid, title: content,
                                                status: 'expired' });
    }
    // Message « habitude » → carte 💡 avec ses boutons (état réel serveur)
    if (opts.kind === 'habit' && opts.hid) {
      const habit = (this._habits && this._habits[opts.hid]) || null;
      return this._appendHabitCard(habit || { id: opts.hid, label: content,
                                              status: 'gone' });
    }
    const el = document.createElement('div');
    el.className = 'cop-msg ' + (role === 'user' ? 'cop-user' : 'cop-assistant');
    if (opts.kind === 'event') el.classList.add('cop-event');
    const inner = document.createElement('div');
    inner.className = 'cop-text';
    if (opts.streaming) {
      el.classList.add('cop-streaming');
      inner.textContent = '';
    } else if (opts.md && role === 'assistant') {
      inner.innerHTML = this._md(content);
    } else {
      inner.textContent = content;
    }
    el.appendChild(inner);
    // Message d'évènement avec destination → bouton « Y aller »
    if (opts.kind === 'event' && opts.nav) {
      const go = document.createElement('button');
      go.className = 'cop-event-go';
      go.textContent = 'Y aller →';
      go.onclick = () => this._navigate(opts.nav);
      el.appendChild(go);
    }
    box.appendChild(el);
    return el;
  },

  /** La carte « ✋ À confirmer » : l'action n'est PAS exécutée tant que
   *  l'utilisateur n'a pas cliqué Confirmer. L'état vient du serveur. */
  _appendProposalCard(prop) {
    const box = document.getElementById('copilot-messages');
    if (!box) return document.createElement('div');
    const el = document.createElement('div');
    el.className = 'cop-msg cop-assistant cop-proposal';
    el.dataset.pid = (prop && prop.id) || '';
    this._renderProposalInner(el, prop || {});
    box.appendChild(el);
    return el;
  },

  _renderProposalInner(el, prop) {
    const status = prop.status || 'pending';
    const pv = prop.preview || null;
    let html = '<div class="cop-prop-kicker">✋ À confirmer</div>';
    html += `<div class="cop-prop-title">${this._esc(prop.title || 'Action proposée')}</div>`;
    if (pv && (pv.to || pv.subject || pv.body)) {
      html += '<div class="cop-prop-mail">';
      if (pv.to) {
        const who = pv.to_name ? `${pv.to_name} — ${pv.to}` : pv.to;
        html += `<div class="cop-prop-line"><b>À :</b> ${this._esc(who)}</div>`;
      }
      if (pv.subject) {
        html += `<div class="cop-prop-line"><b>Objet :</b> ${this._esc(pv.subject)}</div>`;
      }
      if (pv.context) {
        html += `<div class="cop-prop-ctx">Il t’a écrit : « ${this._esc(pv.context)} »</div>`;
      }
      if (pv.body) {
        html += `<div class="cop-prop-body">${this._esc(pv.body)}</div>`;
      }
      html += '</div>';
    } else if (pv && pv.info) {
      html += `<div class="cop-prop-info">${this._esc(pv.info)}</div>`;
    }
    if (status === 'pending') {
      html += `
        <div class="cop-prop-actions">
          <button class="cop-prop-confirm">✓ Confirmer</button>
          <button class="cop-prop-dismiss">Annuler</button>
        </div>`;
    } else {
      const states = {
        done: '✅ Fait',
        failed: '⚠ Échec',
        dismissed: '✋ Annulée — rien n’est parti',
        expired: '⏰ Expirée — redemande-moi si besoin',
      };
      html += `<div class="cop-prop-state cop-prop-state-${this._esc(status)}">`
            + this._esc(states[status] || status);
      if (prop.result_summary) {
        html += `<span> · ${this._esc(prop.result_summary)}</span>`;
      }
      html += '</div>';
    }
    el.innerHTML = html;

    const confirm = el.querySelector('.cop-prop-confirm');
    const dismiss = el.querySelector('.cop-prop-dismiss');
    const lock = () => {
      if (confirm) { confirm.disabled = true; confirm.textContent = '…'; }
      if (dismiss) dismiss.disabled = true;
    };
    if (confirm) {
      confirm.onclick = async () => {
        lock();
        let r = null;
        try {
          r = await App.api.copilot_action_confirm({ id: el.dataset.pid });
        } catch (e) { /* rendu d’échec ci-dessous */ }
        const ok = !!(r && r.ok);
        const next = {
          ...prop,
          status: (r && r.status) || (ok ? 'done' : 'failed'),
          result_summary: (r && r.summary) || (ok ? '' : 'Le serveur n’a pas répondu — réessaie.'),
        };
        if (this._proposals) this._proposals[next.id] = next;
        this._renderProposalInner(el, next);
        if (r && r.navigate) this._navigate(r.navigate);
        if (ok && typeof Guide !== 'undefined' && Guide.say) {
          try { Guide.say('✓ Action confirmée — le copilote l’a faite.'); } catch (e) {}
        }
        this._scrollDown();
      };
    }
    if (dismiss) {
      dismiss.onclick = async () => {
        lock();
        let r = null;
        try {
          r = await App.api.copilot_action_dismiss({ id: el.dataset.pid });
        } catch (e) { /* au pire la carte restera */ }
        const next = { ...prop, status: (r && r.ok) ? 'dismissed' : 'pending',
                       result_summary: '' };
        if (this._proposals) this._proposals[next.id] = next;
        this._renderProposalInner(el, next);
      };
    }
  },

  /** La carte 💡 « une habitude ? » : il a remarqué une répétition et
   *  propose un raccourci. Une seule fois — refuser = silence définitif. */
  _appendHabitCard(habit) {
    const box = document.getElementById('copilot-messages');
    if (!box) return document.createElement('div');
    const el = document.createElement('div');
    el.className = 'cop-msg cop-assistant cop-habit';
    el.dataset.hid = (habit && habit.id) || '';
    this._renderHabitInner(el, habit || {});
    box.appendChild(el);
    return el;
  },

  _renderHabitInner(el, habit) {
    const status = habit.status || 'pending';
    const count = habit.count || 0;
    let html = '<div class="cop-habit-kicker">💡 Une habitude ?</div>';
    html += `<div class="cop-prop-title">${this._esc(habit.label || '')}</div>`;
    if (status === 'pending') {
      html += `<div class="cop-habit-sub">${count} fois ce mois-ci — je t’en fais un raccourci ?</div>`;
      html += '<div class="cop-prop-actions">';
      html += '<button class="cop-prop-confirm" data-mode="button">⚡ Oui, un bouton</button>';
      if (habit.schedule_suggestion && habit.schedule_label) {
        html += `<button class="cop-prop-confirm cop-habit-sched" data-mode="schedule">📅 Et ${this._esc(habit.schedule_label)}</button>`;
      }
      html += '<button class="cop-prop-dismiss">Non merci</button></div>';
    } else {
      const states = {
        accepted: '✅ Raccourci créé — il est au-dessus du champ',
        dismissed: '✋ Non merci — je n’en reparlerai plus',
        gone: '⏰ Suggestion expirée',
      };
      html += `<div class="cop-prop-state">${this._esc(states[status] || status)}</div>`;
    }
    el.innerHTML = html;

    const btns = Array.from(el.querySelectorAll('.cop-prop-confirm'));
    const dismiss = el.querySelector('.cop-prop-dismiss');
    const lock = () => {
      btns.forEach((b) => { b.disabled = true; });
      if (dismiss) dismiss.disabled = true;
    };
    btns.forEach((b) => {
      b.onclick = async () => {
        lock();
        let r = null;
        try {
          r = await App.api.copilot_habit_accept({
            id: el.dataset.hid,
            with_schedule: b.dataset.mode === 'schedule',
          });
        } catch (e) { /* rendu d’échec ci-dessous */ }
        if (r && r.ok) {
          if (r.shortcut) {
            this._shortcuts = (this._shortcuts || []).concat([r.shortcut]);
            this._renderQuickChips();
          }
          const next = { ...habit, status: 'accepted' };
          if (this._habits) this._habits[habit.id] = next;
          this._renderHabitInner(el, next);
          if (typeof Guide !== 'undefined' && Guide.say) {
            try { Guide.say('✓ Raccourci créé.'); } catch (e) {}
          }
        } else {
          this._renderHabitInner(el, { ...habit, status: 'gone' });
        }
      };
    });
    if (dismiss) {
      dismiss.onclick = async () => {
        lock();
        try { await App.api.copilot_habit_dismiss({ id: el.dataset.hid }); }
        catch (e) { /* au pire la carte restera */ }
        const next = { ...habit, status: 'dismissed' };
        if (this._habits) this._habits[habit.id] = next;
        this._renderHabitInner(el, next);
      };
    }
  },

  _finishBubble(bubble, evt) {
    bubble.classList.remove('cop-streaming');
    const textEl = bubble.querySelector('.cop-text');
    if (textEl) textEl.innerHTML = this._md(evt.text || '…');

    const tags = [];
    if (evt.action_done === true) tags.push('✓ Fait');
    if (evt.action_done === false) tags.push('⚠ Action refusée');
    if (evt.sent_to_thomas) tags.push('✉ Message posté à Thomas');
    if (evt.memorized) tags.push('📌 Noté dans mon carnet');
    if (evt.forgotten) tags.push('🗑 Oublié');
    if (tags.length) {
      const t = document.createElement('div');
      t.className = 'cop-tags';
      t.textContent = tags.join(' · ');
      bubble.appendChild(t);
    }

    // Le serveur a transformé l'action en proposition → la carte
    // Confirmer/Annuler suit la réponse, rien n'a été exécuté.
    if (evt.proposed && evt.proposed.id) {
      if (!this._proposals) this._proposals = {};
      this._proposals[evt.proposed.id] = evt.proposed;
      this._appendProposalCard(evt.proposed);
    }

    if (evt.navigate) this._navigate(evt.navigate);

    // Le doigt pointé : Perceval emmène et fait briller l'élément.
    if (evt.guide && typeof Perceval !== 'undefined' && Perceval.pointAt) {
      try { Perceval.pointAt(evt.guide); } catch (e) { /* jamais bloquant */ }
    }

    // Confirmation discrète dans la barre-guide, si elle est là
    if (evt.action_done === true && typeof Guide !== 'undefined' && Guide.say) {
      try { Guide.say('✓ Le copilote a lancé l’action.'); } catch (e) {}
    }
  },

  _errorBubble(bubble, msg) {
    bubble.classList.remove('cop-streaming');
    bubble.classList.add('cop-error');
    const textEl = bubble.querySelector('.cop-text');
    if (textEl) textEl.textContent = msg;
  },

  _navigate(view) {
    if (!view || typeof App === 'undefined' || !App.show) return;
    try { App.show(view); } catch (e) { return; }
    // Sur mobile le volet couvre tout l’écran : on le ferme pour montrer
    // la page demandée. Sur desktop il reste ouvert à côté.
    if (window.matchMedia('(max-width: 640px)').matches) this.close();
  },

  // ---------------------------------------------------------------- vocal
  /** Bascule vers le mode appel existant, en partant du même fil. */
  startCall() {
    if (typeof Claude === 'undefined' || !Claude.openCall) return;
    // Donne au vocal les derniers tours écrits comme mémoire de départ
    const turns = [];
    document.querySelectorAll('#copilot-messages .cop-msg').forEach((el) => {
      if (el.classList.contains('cop-advice') || el.classList.contains('cop-error')
          || el.classList.contains('cop-proposal')
          || el.classList.contains('cop-habit')) return;
      const role = el.classList.contains('cop-user') ? 'user' : 'assistant';
      const t = el.querySelector('.cop-text');
      const content = t ? (t.innerText || '').trim() : '';
      if (content) turns.push({ role, content });
    });
    this.close();
    Claude.openCall(turns.slice(-10));
  },

  /** Appelé par claude.js à la fin d’un appel lancé d’ici : reverse les
   *  tours vocaux dans le fil écrit, puis rouvre le volet. */
  async afterCall(newTurns) {
    if (Array.isArray(newTurns) && newTurns.length) {
      try {
        if (typeof App !== 'undefined' && App.api && App.api.copilot_append) {
          await App.api.copilot_append({ messages: newTurns.slice(-20) });
        }
      } catch (e) { /* le fil serveur rattrapera au prochain tour */ }
      this._loaded = false; // force le rechargement du fil à l’ouverture
    }
    this.open();
  },

  async clearThread() {
    if (this._busy) return;
    const msg = 'Repartir sur une discussion vierge ? Le fil sera effacé (le carnet 📌, lui, est conservé).';
    const okGo = (typeof Dialog !== 'undefined' && Dialog.confirm)
      ? await Dialog.confirm(msg, { title: 'Nouvelle discussion', okLabel: 'Effacer le fil', danger: true })
      : window.confirm(msg);
    if (!okGo) return;
    try {
      if (typeof App !== 'undefined' && App.api && App.api.copilot_clear) {
        await App.api.copilot_clear({});
      }
    } catch (e) { /* au pire le fil restera */ }
    const box = document.getElementById('copilot-messages');
    if (box) { box.innerHTML = ''; this._renderWelcome(box); }
  },

  // ---------------------------------------------------------------- carnet
  _memoryOpen: false,

  toggleMemory() {
    if (!this._memoryOpen && this._journalOpen) this.toggleJournal();
    this._memoryOpen = !this._memoryOpen;
    const mem = document.getElementById('copilot-memory');
    const msgs = document.getElementById('copilot-messages');
    const btn = document.getElementById('copilot-memory-btn');
    if (!mem || !msgs) return;
    mem.style.display = this._memoryOpen ? 'flex' : 'none';
    msgs.style.display = this._memoryOpen ? 'none' : 'flex';
    if (btn) btn.classList.toggle('cop-btn-active', this._memoryOpen);
    if (this._memoryOpen) this._loadMemory();
  },

  // ---------------------------------------------------------------- journal
  _journalOpen: false,

  toggleJournal() {
    if (!this._journalOpen && this._memoryOpen) this.toggleMemory();
    this._journalOpen = !this._journalOpen;
    const jr = document.getElementById('copilot-journal');
    const msgs = document.getElementById('copilot-messages');
    const btn = document.getElementById('copilot-journal-btn');
    if (!jr || !msgs) return;
    jr.style.display = this._journalOpen ? 'flex' : 'none';
    msgs.style.display = this._journalOpen ? 'none' : 'flex';
    if (btn) btn.classList.toggle('cop-btn-active', this._journalOpen);
    if (this._journalOpen) this._loadJournal();
  },

  async _loadJournal() {
    const jr = document.getElementById('copilot-journal');
    if (!jr) return;
    jr.innerHTML = '<div class="cop-loading">…</div>';
    let data = null;
    try {
      if (typeof App !== 'undefined' && App.api && App.api.copilot_journal) {
        data = await App.api.copilot_journal({ limit: 60 });
      }
    } catch (e) { /* affichage dégradé plus bas */ }
    const entries = (data && data.ok && Array.isArray(data.entries)) ? data.entries : [];
    jr.innerHTML = `
      <div class="cop-mem-head">
        <b>📜 Ce que j’ai fait pour toi</b>
        <span>${entries.length ? `${entries.length} action${entries.length > 1 ? 's' : ''} tracée${entries.length > 1 ? 's' : ''} — les plus récentes d’abord` : 'Chaque action que j’exécute (ou que tu confirmes/annules) sera tracée ici'}</span>
      </div>
      <div class="cop-j-list"></div>`;
    const list = jr.querySelector('.cop-j-list');
    if (!entries.length) {
      list.innerHTML = '<div class="cop-mem-empty">Rien pour l’instant. Demande-moi d’agir (« lance une prospection », « réponds à ce prospect »…) et tu retrouveras chaque acte ici, noir sur blanc.</div>';
      return;
    }
    const originLabels = {
      direct: 'fait seul (à l’écrit)',
      vocal: 'fait seul (à la voix)',
      confirme: 'confirmé par toi',
      annule: 'annulé par toi',
    };
    entries.forEach((e) => {
      const row = document.createElement('div');
      let icon = '•';
      let cls = '';
      if (e.origin === 'annule') { icon = '✋'; cls = 'cop-j-neutral'; }
      else if (e.ok === true) { icon = '✓'; cls = 'cop-j-ok'; }
      else if (e.ok === false) { icon = '✗'; cls = 'cop-j-ko'; }
      row.className = 'cop-j-entry ' + cls;
      const when = this._shortDate(e.at);
      row.innerHTML = `
        <span class="cop-j-icon">${icon}</span>
        <div class="cop-j-main">
          <div class="cop-j-label">${this._esc(e.label || '(action)')}</div>
          ${e.summary ? `<div class="cop-j-sum">${this._esc(e.summary)}</div>` : ''}
          <div class="cop-j-meta">${this._esc(when)} · ${this._esc(originLabels[e.origin] || e.origin || '')}</div>
        </div>`;
      list.appendChild(row);
    });
  },

  _shortDate(iso) {
    if (!iso) return '';
    try {
      const d = new Date(iso);
      if (isNaN(d.getTime())) return String(iso).slice(0, 16);
      const today = new Date();
      const sameDay = d.toDateString() === today.toDateString();
      const hm = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
      if (sameDay) return `aujourd’hui ${hm}`;
      return `${String(d.getDate()).padStart(2, '0')}/${String(d.getMonth() + 1).padStart(2, '0')} ${hm}`;
    } catch (e) { return String(iso).slice(0, 16); }
  },

  async _loadMemory() {
    const mem = document.getElementById('copilot-memory');
    if (!mem) return;
    mem.innerHTML = '<div class="cop-loading">…</div>';
    let data = null;
    try {
      if (typeof App !== 'undefined' && App.api && App.api.copilot_memory) {
        data = await App.api.copilot_memory({});
      }
    } catch (e) { /* affichage dégradé plus bas */ }
    const notes = (data && data.ok && Array.isArray(data.notes)) ? data.notes : [];
    mem.innerHTML = `
      <div class="cop-mem-head">
        <b>📌 Ce que je sais de toi</b>
        <span>${notes.length} note${notes.length > 1 ? 's' : ''} — je m’en sers à chaque réponse</span>
      </div>
      <div class="cop-mem-list"></div>
      <div class="cop-mem-add">
        <input id="copilot-mem-input" type="text" maxlength="300"
               placeholder="Ajouter une note à retenir…">
        <button id="copilot-mem-add-btn" title="Ajouter">＋</button>
      </div>
      <div class="cop-init">
        <b>🔔 Mon niveau d’initiative</b>
        <span>Quand je viens vers toi tout seul (réponse de prospect, chasse finie, rappels…)</span>
        <div class="cop-init-row" id="copilot-init-row">
          <button data-lvl="off" title="Je ne te signale plus rien">🔕 Coupé</button>
          <button data-lvl="discret" title="Messages dans le fil + pastille, jamais de notification téléphone">🤫 Discret</button>
          <button data-lvl="normal" title="Fil + pastille, et téléphone quand c’est chaud">🙂 Normal</button>
          <button data-lvl="bavard" title="Tout, même les petites nouvelles">📣 Bavard</button>
        </div>
      </div>
      <div class="cop-init cop-trust">
        <b>🔑 Ce que j’ai le droit de faire</b>
        <span>Famille par famille : je fais seul, je te demande d’abord, ou jamais</span>
        <div id="copilot-trust-rows"></div>
        <div class="cop-trust-note">✉️ Un mail ne part JAMAIS sans ton accord : pour les envois, « je fais seul » n’existe pas.</div>
      </div>
      <div class="cop-init cop-shortcuts">
        <b>⚡ Mes raccourcis</b>
        <span>Les boutons au-dessus du champ — et leurs rendez-vous (📅 = il prépare, tu confirmes)</span>
        <div id="copilot-sc-list"></div>
        <div class="cop-mem-add">
          <input id="copilot-sc-label" type="text" maxlength="40"
                 placeholder="Nom du bouton (ex : Le point chasse)">
        </div>
        <div class="cop-mem-add">
          <input id="copilot-sc-question" type="text" maxlength="200"
                 placeholder="La question qu’il me posera…">
          <button id="copilot-sc-add-btn" title="Créer le bouton">＋</button>
        </div>
        <div class="cop-trust-note">💬 Pour un raccourci qui AGIT (lancer une prospection…) ou un rendez-vous : demande-le-moi dans la discussion, je le fabrique.</div>
      </div>`;
    const list = mem.querySelector('.cop-mem-list');
    if (!notes.length) {
      list.innerHTML = '<div class="cop-mem-empty">Rien pour l’instant. Dis-moi tes préférences en discutant (« retiens que… ») ou ajoute une note ci-dessous.</div>';
    } else {
      notes.slice().reverse().forEach((n) => {
        const row = document.createElement('div');
        row.className = 'cop-mem-note';
        row.innerHTML = `<span>${this._esc(n.text)}</span>
          <button title="Supprimer cette note" data-id="${this._esc(n.id)}">🗑</button>`;
        row.querySelector('button').onclick = async (e) => {
          const id = e.currentTarget.dataset.id;
          try {
            const r = await App.api.copilot_memory_delete({ id });
            if (r && r.ok) row.remove();
          } catch (err) { /* la note restera visible */ }
        };
        list.appendChild(row);
      });
    }
    const addBtn = mem.querySelector('#copilot-mem-add-btn');
    const addInput = mem.querySelector('#copilot-mem-input');
    const doAdd = async () => {
      const text = (addInput.value || '').trim();
      if (!text) return;
      try {
        const r = await App.api.copilot_memory_add({ text });
        if (r && r.ok) { addInput.value = ''; this._loadMemory(); }
      } catch (e) { /* tant pis pour cette fois */ }
    };
    addBtn.onclick = doAdd;
    addInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); doAdd(); }
    });

    // Niveau d'initiative : charge l'état réel puis branche les boutons
    const row = mem.querySelector('#copilot-init-row');
    const paint = (lvl) => {
      row.querySelectorAll('button').forEach((b) => {
        b.classList.toggle('cop-init-on', b.dataset.lvl === lvl);
      });
    };
    paint(this._initiative || 'normal');

    // Curseur de confiance : 3 familles, 3 positions (les mails n'ont
    // jamais « je fais seul » — plafond tenu aussi côté serveur).
    const FAMILIES = [
      { key: 'prospection', label: 'Prospection & machines',
        desc: 'chasses, missions, Auto-pilote on/off', solo: true },
      { key: 'notes', label: 'Notes & fiches',
        desc: 'notes du Cerveau, fiches prospects', solo: true },
      { key: 'mails', label: 'Envois de mails',
        desc: 'brouillons, réponses, relances, convoi', solo: false },
    ];
    const LEVELS = [
      { key: 'solo', label: 'Je fais seul' },
      { key: 'ask', label: 'Je te demande' },
      { key: 'never', label: 'Jamais' },
    ];
    const trustBox = mem.querySelector('#copilot-trust-rows');
    const paintTrust = (trust) => {
      trust = trust || {};
      trustBox.innerHTML = '';
      FAMILIES.forEach((fam) => {
        const line = document.createElement('div');
        line.className = 'cop-trust-row';
        line.innerHTML = `
          <div class="cop-trust-id">
            <div class="cop-trust-label">${this._esc(fam.label)}</div>
            <div class="cop-trust-desc">${this._esc(fam.desc)}</div>
          </div>
          <div class="cop-init-row cop-trust-btns"></div>`;
        const btns = line.querySelector('.cop-trust-btns');
        LEVELS.forEach((lv) => {
          if (lv.key === 'solo' && !fam.solo) return;
          const b = document.createElement('button');
          b.textContent = lv.label;
          b.classList.toggle('cop-init-on', (trust[fam.key] || 'ask') === lv.key);
          b.onclick = async () => {
            try {
              const r = await App.api.copilot_prefs_set({ trust: { [fam.key]: lv.key } });
              if (r && r.ok) {
                this._trust = r.trust || this._trust;
                paintTrust(this._trust);
                if (typeof Guide !== 'undefined' && Guide.say) {
                  Guide.say(`✓ ${fam.label} : « ${lv.label.toLowerCase()} ».`);
                }
              }
            } catch (e) { /* réglage inchangé */ }
          };
          btns.appendChild(b);
        });
        trustBox.appendChild(line);
      });
    };
    paintTrust(this._trust);

    // Mes raccourcis : liste + pause + suppression + création (question)
    const scList = mem.querySelector('#copilot-sc-list');
    const paintShortcuts = (items) => {
      this._shortcuts = items || [];
      scList.innerHTML = '';
      if (!this._shortcuts.length) {
        scList.innerHTML = '<div class="cop-mem-empty">Aucun raccourci pour l’instant. Je t’en proposerai quand je remarquerai tes habitudes — ou crée le tien ci-dessous.</div>';
      }
      this._shortcuts.forEach((sc) => {
        const row = document.createElement('div');
        row.className = 'cop-mem-note cop-sc-row' + (sc.paused ? ' cop-sc-paused' : '');
        const sched = sc.schedule_label
          ? `<div class="cop-sc-when">📅 ${this._esc(sc.schedule_label)}${sc.paused ? ' — en pause' : ''}</div>` : '';
        row.innerHTML = `
          <span>⚡ ${this._esc(sc.label)}${sched}</span>
          ${sc.schedule_label ? `<button class="cop-sc-pause" title="${sc.paused ? 'Réveiller le rendez-vous' : 'Mettre le rendez-vous en pause'}">${sc.paused ? '▶' : '⏸'}</button>` : ''}
          <button class="cop-sc-del" title="Supprimer ce raccourci">🗑</button>`;
        const pauseBtn = row.querySelector('.cop-sc-pause');
        if (pauseBtn) {
          pauseBtn.onclick = async () => {
            try {
              const r = await App.api.copilot_shortcut_pause({ id: sc.id, paused: !sc.paused });
              if (r && r.ok) refreshShortcuts();
            } catch (e) { /* inchangé */ }
          };
        }
        row.querySelector('.cop-sc-del').onclick = async () => {
          try {
            const r = await App.api.copilot_shortcut_delete({ id: sc.id });
            if (r && r.ok) { row.remove(); refreshShortcuts(); }
          } catch (e) { /* le raccourci restera */ }
        };
        scList.appendChild(row);
      });
      this._renderQuickChips();
    };
    const refreshShortcuts = async () => {
      try {
        const r = await App.api.copilot_shortcuts({});
        if (r && r.ok) paintShortcuts(r.shortcuts || []);
      } catch (e) { /* on garde la liste connue */ }
    };
    paintShortcuts(this._shortcuts || []);
    refreshShortcuts();

    const scLabel = mem.querySelector('#copilot-sc-label');
    const scQuestion = mem.querySelector('#copilot-sc-question');
    const scAdd = mem.querySelector('#copilot-sc-add-btn');
    const doAddShortcut = async () => {
      const label = (scLabel.value || '').trim();
      const question = (scQuestion.value || '').trim();
      if (!label || !question) return;
      try {
        const r = await App.api.copilot_shortcut_create({ label, question });
        if (r && r.ok) {
          scLabel.value = ''; scQuestion.value = '';
          refreshShortcuts();
          if (typeof Guide !== 'undefined' && Guide.say) {
            try { Guide.say('✓ Raccourci créé.'); } catch (e) {}
          }
        } else if (r && r.error && typeof Toast !== 'undefined' && Toast.show) {
          try { Toast.show(r.error); } catch (e) {}
        }
      } catch (e) { /* tant pis pour cette fois */ }
    };
    scAdd.onclick = doAddShortcut;
    scQuestion.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); doAddShortcut(); }
    });

    try {
      const p = await App.api.copilot_prefs({});
      if (p && p.ok) {
        if (p.initiative) { this._initiative = p.initiative; paint(p.initiative); }
        if (p.trust) { this._trust = p.trust; paintTrust(p.trust); }
      }
    } catch (e) { /* on garde les valeurs connues */ }
    row.querySelectorAll('button').forEach((b) => {
      b.onclick = async () => {
        const lvl = b.dataset.lvl;
        try {
          const r = await App.api.copilot_prefs_set({ initiative: lvl });
          if (r && r.ok) {
            this._initiative = lvl;
            paint(lvl);
            if (typeof Guide !== 'undefined' && Guide.say) {
              const labels = { off: 'Initiative coupée', discret: 'Mode discret',
                               normal: 'Mode normal', bavard: 'Mode bavard' };
              Guide.say('✓ ' + (labels[lvl] || lvl) + '.');
            }
          }
        } catch (e) { /* réglage inchangé */ }
      };
    });
  },

  // ---------------------------------------------------------------- dictée
  _dictating: false,
  _rec: null,

  _toggleDictation() {
    if (this._dictating) { this._stopDictation(); return; }
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    const input = document.getElementById('copilot-input');
    const btn = document.getElementById('copilot-mic');
    if (!SR || !input) return;
    const rec = new SR();
    rec.lang = 'fr-FR';
    rec.continuous = true;
    rec.interimResults = true;
    this._rec = rec;
    this._dictating = true;
    if (btn) { btn.classList.add('cop-mic-on'); btn.textContent = '⏹'; }
    const base = input.value ? input.value + ' ' : '';
    let finalText = '';
    rec.onresult = (e) => {
      let interim = '';
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const t = e.results[i][0].transcript;
        if (e.results[i].isFinal) finalText += t;
        else interim += t;
      }
      input.value = (base + finalText + interim).trim();
      this._growInput();
    };
    rec.onerror = () => { try { rec.stop(); } catch (e) {} };
    rec.onend = () => {
      this._dictating = false;
      this._rec = null;
      if (btn) { btn.classList.remove('cop-mic-on'); btn.textContent = '🎤'; }
      if (input) input.focus();
    };
    try { rec.start(); } catch (e) { this._stopDictation(); }
  },

  _stopDictation() {
    if (this._rec) { try { this._rec.abort(); } catch (e) {} this._rec = null; }
    this._dictating = false;
    const btn = document.getElementById('copilot-mic');
    if (btn) { btn.classList.remove('cop-mic-on'); btn.textContent = '🎤'; }
  },

  // ---------------------------------------------------------------- montage
  _mount() {
    if (this._mounted) return;
    this._mounted = true;
    this._injectStyles();

    const panel = document.createElement('div');
    panel.id = 'copilot-panel';
    panel.innerHTML = `
      <div class="cop-head">
        <div class="cop-head-id">
          <span class="cop-head-orb" aria-hidden="true">
            <svg viewBox="0 0 140 152" style="display:block;width:100%;height:100%">
              <path d="M70,22 L70,12" fill="none" stroke="#534AB7" stroke-width="4" stroke-linecap="round"/>
              <path d="M70,2 L76,9 L70,16 L64,9 Z" fill="#7F77DD"/>
              <path d="M70,24 C94,24 108,29 110,34 C110,72 106,100 70,128 C34,100 30,72 30,34 C32,29 46,24 70,24 Z" fill="#3C3489" stroke="#7F77DD" stroke-width="5"/>
              <rect x="47" y="55" width="15" height="25" rx="7.5" fill="#EEEDFE"/>
              <rect x="78" y="55" width="15" height="25" rx="7.5" fill="#EEEDFE"/>
            </svg>
          </span>
          <div>
            <div class="cop-head-title">Perceval</div>
            <div class="cop-head-sub">ton copilote — il voit l’app en direct</div>
          </div>
        </div>
        <div class="cop-head-actions">
          <button id="copilot-memory-btn" title="Mon carnet + mes permissions">📌</button>
          <button id="copilot-journal-btn" title="Le journal : tout ce que j’ai fait pour toi">📜</button>
          <button id="copilot-call" title="Passer en vocal (conversation à la voix)">📞</button>
          <button id="copilot-new" title="Nouvelle discussion (efface le fil, garde le carnet)">⟲</button>
          <button id="copilot-close" title="Fermer">×</button>
        </div>
      </div>
      <div id="copilot-messages" class="cop-messages"></div>
      <div id="copilot-memory" class="cop-memory" style="display:none;"></div>
      <div id="copilot-journal" class="cop-memory" style="display:none;"></div>
      <div id="copilot-quick" class="cop-quick" style="display:none;"></div>
      <div class="cop-composer">
        <button id="copilot-mic" title="Dicter au lieu de taper">🎤</button>
        <textarea id="copilot-input" rows="1"
                  placeholder="Écris-moi… (Entrée pour envoyer)"></textarea>
        <button id="copilot-send" title="Envoyer">➤</button>
      </div>`;
    document.body.appendChild(panel);

    panel.querySelector('#copilot-close').onclick = () => this.close();
    panel.querySelector('#copilot-new').onclick = () => this.clearThread();
    panel.querySelector('#copilot-call').onclick = () => this.startCall();
    panel.querySelector('#copilot-send').onclick = () => this.send();
    panel.querySelector('#copilot-memory-btn').onclick = () => this.toggleMemory();
    panel.querySelector('#copilot-journal-btn').onclick = () => this.toggleJournal();

    const mic = panel.querySelector('#copilot-mic');
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) { mic.disabled = true; mic.title = 'Dictée non supportée par ce navigateur'; }
    else mic.onclick = () => this._toggleDictation();

    const input = panel.querySelector('#copilot-input');
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        this.send();
      }
      if (e.key === 'Escape') this.close();
    });
    input.addEventListener('input', () => this._growInput());
  },

  _growInput() {
    const input = document.getElementById('copilot-input');
    if (!input) return;
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 120) + 'px';
  },

  _setComposerBusy(busy) {
    const send = document.getElementById('copilot-send');
    if (send) { send.disabled = !!busy; send.textContent = busy ? '…' : '➤'; }
  },

  _scrollDown(force) {
    const box = document.getElementById('copilot-messages');
    if (!box) return;
    const nearBottom = (box.scrollHeight - box.scrollTop - box.clientHeight) < 140;
    if (force || nearBottom) box.scrollTop = box.scrollHeight;
  },

  // ---------------------------------------------------------------- rendu texte
  _esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
  },

  /** Markdown très léger et sûr : tout est échappé d’abord. */
  _md(text) {
    let h = this._esc(text);
    h = h.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
                  '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
    h = h.replace(/\*\*([^*\n]+)\*\*/g, '<b>$1</b>');
    h = h.replace(/`([^`\n]+)`/g, '<code>$1</code>');
    h = h.replace(/^[-*] (.*)$/gm, '<span class="cop-li">•&nbsp;$1</span>');
    h = h.replace(/\n/g, '<br>');
    return h;
  },

  // ---------------------------------------------------------------- styles
  _injectStyles() {
    if (document.getElementById('copilot-styles')) return;
    const s = document.createElement('style');
    s.id = 'copilot-styles';
    s.textContent = `
      #copilot-panel {
        position: fixed; z-index: 70;
        right: 18px; bottom: calc(14px + env(safe-area-inset-bottom, 0px));
        width: min(420px, calc(100vw - 24px));
        height: min(640px, calc(100vh - 80px));
        display: none; flex-direction: column; overflow: hidden;
        background: hsl(var(--surface-elevated, var(--surface)));
        border: 1px solid hsl(var(--border-strong));
        border-radius: 20px;
        box-shadow: 0 18px 60px rgba(15,23,42,.30);
        opacity: 0; transform: translateY(14px);
        transition: opacity .18s ease-out, transform .18s ease-out;
      }
      #copilot-panel.cop-visible { display: flex; opacity: 1; transform: translateY(0); }
      @media (max-width: 640px) {
        #copilot-panel {
          inset: 0; width: 100%; height: 100%;
          border-radius: 0; border: 0;
        }
      }
      /* -- Grand écran : la discussion en COLONNE à côté du contenu.
            L'app se pousse à gauche, on travaille à deux, côte à côte. -- */
      #main { transition: margin-right .22s ease; }
      @media (min-width: 1200px) {
        body.cop-open #copilot-panel {
          top: 0; right: 0; bottom: 0;
          width: 420px; height: auto; max-height: none;
          border-radius: 0; border: 0;
          border-left: 1px solid hsl(var(--border-strong));
          box-shadow: -10px 0 32px rgba(15,23,42,.16);
        }
        body.cop-open #main { margin-right: 420px; }
        body.cop-open #tc-toast-host { right: 436px !important; }
        body.cop-open #thomas-fab { right: 444px; }
      }
      .cop-head {
        display: flex; align-items: center; justify-content: space-between;
        gap: 10px; padding: 12px 14px;
        border-bottom: 1px solid hsl(var(--border));
        background: hsl(var(--surface) / .6);
      }
      .cop-head-id { display: flex; align-items: center; gap: 10px; min-width: 0; }
      .cop-head-orb {
        width: 32px; height: 34px; flex-shrink: 0;
        filter: drop-shadow(0 2px 6px hsl(var(--accent) / .35));
      }
      .cop-head-title { font-weight: 800; font-size: 14px; color: hsl(var(--text)); line-height: 1.1; }
      .cop-head-sub { font-size: 11px; color: hsl(var(--text-muted)); }
      .cop-head-actions { display: flex; gap: 4px; }
      .cop-head-actions button {
        width: 32px; height: 32px; border-radius: 10px; border: 0;
        background: transparent; cursor: pointer; font-size: 15px;
        color: hsl(var(--text-secondary)); line-height: 1;
      }
      .cop-head-actions button:hover { background: hsl(var(--border) / .5); }
      #copilot-close { font-size: 20px; }
      .cop-messages {
        flex: 1; overflow-y: auto; padding: 14px;
        display: flex; flex-direction: column; gap: 10px;
        overscroll-behavior: contain;
      }
      .cop-loading { text-align: center; color: hsl(var(--text-muted)); padding: 30px 0; }
      .cop-msg {
        max-width: 86%; padding: 9px 13px; border-radius: 16px;
        font-size: 13.5px; line-height: 1.55; word-wrap: break-word;
        animation: copIn .18s ease-out;
      }
      .cop-user {
        align-self: flex-end;
        background: hsl(var(--accent)); color: #fff;
        border-bottom-right-radius: 6px;
        white-space: pre-wrap;
      }
      .cop-assistant {
        align-self: flex-start;
        background: hsl(var(--surface));
        border: 1px solid hsl(var(--border));
        color: hsl(var(--text-secondary));
        border-bottom-left-radius: 6px;
      }
      .cop-assistant .cop-text { white-space: pre-wrap; }
      .cop-assistant .cop-text a { color: hsl(var(--accent)); font-weight: 600; }
      .cop-assistant .cop-text code {
        background: hsl(var(--border) / .4); padding: 1px 5px;
        border-radius: 5px; font-size: 12px;
      }
      .cop-li { display: block; padding-left: 4px; }
      .cop-streaming .cop-text::after {
        content: '▍'; color: hsl(var(--accent));
        animation: copBlink 1s steps(2) infinite;
      }
      .cop-error {
        background: hsl(0 70% 97%); border-color: hsl(0 60% 85%);
        color: hsl(0 60% 40%);
      }
      .cop-tags {
        margin-top: 7px; padding-top: 7px;
        border-top: 1px dashed hsl(var(--border));
        font-size: 11px; font-weight: 700; color: hsl(var(--success, 150 60% 40%));
      }
      .cop-event {
        border-left: 3px solid hsl(var(--accent));
        background: hsl(var(--accent) / .06);
      }
      .cop-event-go {
        margin-top: 8px; border: 0; cursor: pointer; display: block;
        background: hsl(var(--accent)); color: #fff;
        font-size: 11.5px; font-weight: 700; padding: 5px 11px;
        border-radius: 999px;
      }
      .cop-init {
        margin-top: 14px; padding-top: 12px;
        border-top: 1px solid hsl(var(--border));
      }
      .cop-init b { display: block; font-size: 13px; color: hsl(var(--text)); }
      .cop-init > span { display: block; font-size: 11px;
                         color: hsl(var(--text-muted)); margin: 2px 0 8px; }
      .cop-init-row { display: flex; gap: 6px; flex-wrap: wrap; }
      .cop-init-row button {
        border: 1px solid hsl(var(--border)); cursor: pointer;
        background: hsl(var(--surface)); color: hsl(var(--text-secondary));
        font-size: 11.5px; font-weight: 600; padding: 6px 10px;
        border-radius: 999px;
      }
      .cop-init-row button:hover { border-color: hsl(var(--accent) / .5); }
      .cop-init-row button.cop-init-on {
        background: hsl(var(--accent)); border-color: hsl(var(--accent));
        color: #fff;
      }
      .cop-proposal {
        max-width: 96%; width: 96%;
        border-left: 3px solid hsl(35 92% 50%);
        background: hsl(35 92% 50% / .07);
      }
      .cop-prop-kicker {
        font-size: 10px; font-weight: 800; letter-spacing: .8px;
        text-transform: uppercase; color: hsl(35 80% 38%); margin-bottom: 4px;
      }
      .cop-prop-title { font-weight: 700; color: hsl(var(--text)); margin-bottom: 6px; }
      .cop-prop-mail {
        background: hsl(var(--surface));
        border: 1px solid hsl(var(--border));
        border-radius: 12px; padding: 9px 11px; margin: 4px 0 2px;
      }
      .cop-prop-line { font-size: 12px; margin-bottom: 3px; color: hsl(var(--text-secondary)); }
      .cop-prop-line b { color: hsl(var(--text)); }
      .cop-prop-ctx {
        font-size: 11.5px; font-style: italic; color: hsl(var(--text-muted));
        margin: 4px 0; padding: 4px 8px;
        border-left: 2px solid hsl(var(--border-strong));
      }
      .cop-prop-body {
        margin-top: 6px; padding-top: 6px;
        border-top: 1px dashed hsl(var(--border));
        font-size: 12.5px; line-height: 1.55; color: hsl(var(--text-secondary));
        white-space: pre-wrap; max-height: 200px; overflow-y: auto;
      }
      .cop-prop-info { font-size: 12.5px; color: hsl(var(--text-secondary)); margin: 2px 0; }
      .cop-prop-actions { display: flex; gap: 8px; margin-top: 9px; }
      .cop-prop-actions button {
        border: 0; cursor: pointer; font-size: 12px; font-weight: 700;
        padding: 7px 14px; border-radius: 999px;
      }
      .cop-prop-actions button:disabled { opacity: .55; cursor: default; }
      .cop-prop-confirm { background: hsl(var(--accent)); color: #fff; }
      .cop-prop-dismiss {
        background: transparent; color: hsl(var(--text-secondary));
        border: 1px solid hsl(var(--border-strong)) !important;
      }
      .cop-prop-state {
        margin-top: 8px; font-size: 12px; font-weight: 700;
        color: hsl(var(--text-secondary));
      }
      .cop-prop-state-done { color: hsl(150 60% 35%); }
      .cop-prop-state-failed { color: hsl(0 60% 45%); }
      .cop-prop-state span { font-weight: 500; }
      .cop-habit {
        max-width: 96%; width: 96%;
        border-left: 3px solid hsl(258 70% 58%);
        background: hsl(258 70% 58% / .06);
      }
      .cop-habit-kicker {
        font-size: 10px; font-weight: 800; letter-spacing: .8px;
        text-transform: uppercase; color: hsl(258 55% 48%); margin-bottom: 4px;
      }
      .cop-habit-sub {
        font-size: 12px; color: hsl(var(--text-secondary)); margin: 2px 0 4px;
      }
      .cop-habit .cop-prop-confirm { background: hsl(258 60% 52%); }
      .cop-habit .cop-habit-sched { background: hsl(258 45% 42%); }
      .cop-chip-shortcut {
        border-color: hsl(258 60% 52% / .4);
        background: hsl(258 60% 52% / .08); color: hsl(258 55% 48%);
      }
      .cop-chip-shortcut:hover { background: hsl(258 60% 52% / .16); }
      .cop-sc-row { align-items: center; }
      .cop-sc-row.cop-sc-paused { opacity: .6; }
      .cop-sc-when { font-size: 11px; color: hsl(var(--text-muted)); margin-top: 2px; }
      .cop-sc-pause {
        border: 0; background: transparent; cursor: pointer;
        font-size: 12px; opacity: .6; flex-shrink: 0; padding: 0 2px;
      }
      .cop-sc-pause:hover { opacity: 1; }
      .cop-j-list { flex: 1; overflow-y: auto; display: flex;
                    flex-direction: column; gap: 6px; }
      .cop-j-entry {
        display: flex; gap: 9px; align-items: flex-start;
        background: hsl(var(--surface));
        border: 1px solid hsl(var(--border));
        border-radius: 12px; padding: 8px 10px;
      }
      .cop-j-icon { font-size: 13px; font-weight: 800; flex-shrink: 0;
                    width: 16px; text-align: center; }
      .cop-j-ok .cop-j-icon { color: hsl(150 60% 35%); }
      .cop-j-ko .cop-j-icon { color: hsl(0 60% 45%); }
      .cop-j-neutral .cop-j-icon { color: hsl(var(--text-muted)); }
      .cop-j-main { flex: 1; min-width: 0; }
      .cop-j-label { font-size: 12.5px; font-weight: 700; color: hsl(var(--text)); }
      .cop-j-sum { font-size: 12px; color: hsl(var(--text-secondary));
                   line-height: 1.45; margin-top: 1px; word-wrap: break-word; }
      .cop-j-meta { font-size: 10.5px; color: hsl(var(--text-muted)); margin-top: 3px; }
      .cop-trust-row {
        display: flex; flex-direction: column; gap: 5px;
        padding: 8px 0; border-bottom: 1px dashed hsl(var(--border));
      }
      .cop-trust-row:last-child { border-bottom: 0; }
      .cop-trust-label { font-size: 12.5px; font-weight: 700; color: hsl(var(--text)); }
      .cop-trust-desc { font-size: 11px; color: hsl(var(--text-muted)); }
      .cop-trust-note {
        margin-top: 8px; font-size: 11px; line-height: 1.5;
        color: hsl(var(--text-muted));
        border: 1px dashed hsl(var(--border)); border-radius: 10px;
        padding: 7px 9px;
      }
      .cop-advice { border-left: 3px solid hsl(var(--accent)); }
      .cop-advice-kicker {
        font-size: 10px; font-weight: 800; letter-spacing: .8px;
        text-transform: uppercase; color: hsl(var(--accent)); margin-bottom: 4px;
      }
      .cop-advice-headline { font-weight: 700; color: hsl(var(--text)); margin-bottom: 4px; }
      .cop-advice-go {
        margin-top: 8px; border: 0; cursor: pointer;
        background: hsl(var(--accent)); color: #fff;
        font-size: 12px; font-weight: 700; padding: 6px 12px; border-radius: 999px;
      }
      .cop-welcome {
        background: hsl(var(--surface));
        border: 1px dashed hsl(var(--border-strong));
        border-radius: 16px; padding: 14px;
      }
      .cop-w-title { font-weight: 800; font-size: 14px; color: hsl(var(--text)); margin-bottom: 6px; }
      .cop-w-body { font-size: 12.5px; line-height: 1.55; color: hsl(var(--text-secondary)); margin-bottom: 10px; }
      .cop-w-chips { display: flex; flex-wrap: wrap; gap: 6px; }
      .cop-chip {
        border: 1px solid hsl(var(--accent) / .4); cursor: pointer;
        background: hsl(var(--accent) / .08); color: hsl(var(--accent));
        font-size: 11.5px; font-weight: 600; padding: 5px 10px; border-radius: 999px;
      }
      .cop-chip:hover { background: hsl(var(--accent) / .16); }
      .cop-quick {
        display: flex; gap: 6px; flex-wrap: wrap;
        padding: 6px 12px 0;
      }
      .cop-memory {
        flex: 1; display: flex; flex-direction: column; overflow-y: auto;
        padding: 14px;
      }
      .cop-mem-head { margin-bottom: 10px; flex-shrink: 0; }
      .cop-mem-head b { display: block; font-size: 14px; color: hsl(var(--text)); }
      .cop-mem-head span { font-size: 11.5px; color: hsl(var(--text-muted)); }
      .cop-mem-list { flex: 0 0 auto; max-height: 200px; overflow-y: auto;
                      display: flex; flex-direction: column; gap: 6px; }
      #copilot-journal .cop-j-list { flex: 1 1 auto; min-height: 0; }
      .cop-mem-note {
        display: flex; align-items: flex-start; gap: 8px;
        background: hsl(var(--surface));
        border: 1px solid hsl(var(--border));
        border-radius: 12px; padding: 8px 10px;
        font-size: 12.5px; line-height: 1.5; color: hsl(var(--text-secondary));
      }
      .cop-mem-note span { flex: 1; min-width: 0; word-wrap: break-word; }
      .cop-mem-note button {
        border: 0; background: transparent; cursor: pointer;
        font-size: 13px; opacity: .55; flex-shrink: 0; padding: 0 2px;
      }
      .cop-mem-note button:hover { opacity: 1; }
      .cop-mem-empty {
        font-size: 12.5px; color: hsl(var(--text-muted));
        border: 1px dashed hsl(var(--border)); border-radius: 12px;
        padding: 14px; line-height: 1.55;
      }
      .cop-mem-add { display: flex; gap: 8px; margin-top: 10px; }
      .cop-mem-add input {
        flex: 1; min-width: 0; padding: 8px 12px; font-size: 12.5px;
        border-radius: 12px; border: 1px solid hsl(var(--border));
        background: hsl(var(--surface)); color: hsl(var(--text));
        outline: none;
      }
      .cop-mem-add input:focus { border-color: hsl(var(--accent)); }
      .cop-mem-add button {
        width: 36px; height: 36px; flex-shrink: 0; border-radius: 12px;
        border: 1px solid hsl(var(--accent)); cursor: pointer;
        background: hsl(var(--accent)); color: #fff; font-size: 16px;
      }
      .cop-btn-active { background: hsl(var(--accent) / .15) !important;
                        color: hsl(var(--accent)) !important; }
      .cop-composer {
        display: flex; align-items: flex-end; gap: 8px;
        padding: 10px 12px calc(10px + env(safe-area-inset-bottom, 0px));
        border-top: 1px solid hsl(var(--border));
        background: hsl(var(--surface) / .6);
      }
      .cop-composer textarea {
        flex: 1; min-width: 0; resize: none; max-height: 120px;
        padding: 9px 12px; font-size: 13.5px; line-height: 1.45;
        border-radius: 14px; border: 1px solid hsl(var(--border));
        background: hsl(var(--surface)); color: hsl(var(--text));
        outline: none;
      }
      .cop-composer textarea:focus {
        border-color: hsl(var(--accent));
        box-shadow: 0 0 0 3px hsl(var(--accent) / .15);
      }
      .cop-composer button {
        width: 38px; height: 38px; flex-shrink: 0; border-radius: 12px;
        border: 1px solid hsl(var(--border)); cursor: pointer;
        background: hsl(var(--surface)); color: hsl(var(--text-secondary));
        font-size: 15px; line-height: 1;
      }
      .cop-composer button:hover { border-color: hsl(var(--accent) / .5); color: hsl(var(--accent)); }
      #copilot-send {
        background: hsl(var(--accent)); border-color: hsl(var(--accent)); color: #fff;
      }
      #copilot-send:disabled { opacity: .55; cursor: default; }
      #copilot-mic.cop-mic-on {
        background: #ef4444; border-color: #dc2626; color: #fff;
        animation: copMicPulse 1.2s ease-in-out infinite;
      }
      #copilot-mic:disabled { opacity: .4; cursor: not-allowed; }
      @keyframes copIn { from { opacity: 0; transform: translateY(5px); }
                         to { opacity: 1; transform: translateY(0); } }
      @keyframes copBlink { 50% { opacity: 0; } }
      @keyframes copMicPulse {
        0%, 100% { box-shadow: 0 0 0 0 rgba(239,68,68,.45); }
        50% { box-shadow: 0 0 0 8px rgba(239,68,68,0); }
      }
    `;
    document.head.appendChild(s);
  },
};
