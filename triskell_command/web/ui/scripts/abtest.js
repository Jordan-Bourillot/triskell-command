/* Vue Test A/B des sujets — comparer plusieurs variantes objectivement.
 *
 * Une "campagne" = un objectif (ex: "premier contact froid"). Plusieurs
 * variantes de sujet par campagne. L'app équilibre les envois et calcule
 * un verdict statistique au bout de N envois.
 */

const ABTest = {
  data: null,

  async render(container) {
    container.innerHTML = `
      <section class="animate-slide-up max-w-5xl">
        <div class="mb-8">
          <div class="flex items-start justify-between gap-3">
            <div>
              <div class="hero-kicker mb-2">TEST A/B SUJETS</div>
              <h1 class="hero-title mb-3" style="font-size: 36px;">Quel sujet fait le plus répondre ?</h1>
              <p class="hero-subtitle">Tu proposes plusieurs variantes, l'app les distribue équitablement et mesure le taux de réponse de chacune.</p>
            </div>
            ${Help.button('abtest')}
          </div>
          <div class="flex gap-3 mt-6">
            <button id="ab-back" class="btn btn-secondary">← Réglages</button>
            <button id="ab-new"  class="btn btn-primary">+ Nouvelle campagne</button>
          </div>
        </div>
        <div id="ab-content"><div class="text-center py-16 text-text-muted">Chargement…</div></div>
      </section>
    `;
    document.getElementById('ab-back').onclick = () => App.show('config', { tab: 'automations' });
    document.getElementById('ab-new').onclick  = () => this._openNew();
    await this.refresh();
  },

  async refresh() {
    if (!App.api) {
      document.getElementById('ab-content').innerHTML =
        `<div class="card p-10 text-center text-text-muted">Mode aperçu uniquement.</div>`;
      return;
    }
    let r;
    try { r = await App.api.ab_get_results(); }
    catch (e) { r = { ok: false, error: String(e) }; }
    if (!r || !r.ok) {
      console.warn('ab_get_results:', r && r.error);
      document.getElementById('ab-content').innerHTML = `
        <div class="card p-10 text-center">
          <p class="text-text font-semibold mb-1">Impossible de charger les tests.</p>
          <p class="text-text-muted text-sm mb-4">Vérifie ta connexion, puis réessaie.</p>
          <button class="btn btn-primary" onclick="ABTest.refresh()">Réessayer</button>
        </div>`;
      return;
    }
    this.data = r;
    const camps = r.campaigns || [];
    if (camps.length === 0) {
      document.getElementById('ab-content').innerHTML = this._emptyState();
      this._bindCards();
      return;
    }
    document.getElementById('ab-content').innerHTML =
      this._thresholdCard(r.config || {}) +
      camps.map(c => this._campaignCard(c)).join('');
    this._bindCards();
  },

  // ---- Réglage du seuil de verdict (min_sent_for_verdict) ----
  _thresholdCard(config) {
    const n = parseInt(config.min_sent_for_verdict, 10) || 30;
    return `
      <div class="card p-4 mb-6 flex items-center gap-3 flex-wrap">
        <label class="text-sm" for="ab-threshold">
          Verdict calculé à partir de
          <input id="ab-threshold" type="number" min="5" max="1000" value="${n}"
                 class="w-20 mx-1 px-2 py-1 text-sm rounded-lg bg-bg border border-border focus:outline-none focus:border-accent text-center" />
          envois par sujet.
        </label>
        <button id="ab-threshold-save" class="btn btn-secondary text-xs">Enregistrer le seuil</button>
        <span class="text-[11px] text-text-muted">En dessous, pas assez de données pour départager les sujets.</span>
      </div>
    `;
  },

  // Réécrit la config complète côté serveur (ab_save_config). On recharge
  // la version la plus fraîche juste avant d'écrire pour ne pas écraser
  // des compteurs d'envoi tombés entre-temps.
  async _saveFullConfig(mutate) {
    const r = await App.api.ab_get_results();
    if (!r || !r.ok || !r.config) {
      throw new Error((r && r.error) || 'réglage indisponible');
    }
    const config = r.config;
    mutate(config);
    const s = await App.api.ab_save_config({ config });
    if (!s || !s.ok) throw new Error((s && s.error) || 'enregistrement refusé');
  },

  _emptyState() {
    return `
      <div class="card-hero p-12 text-center" data-accent="accent">
        <div class="text-5xl mb-4 opacity-80">🧪</div>
        <h2 class="font-display text-2xl font-bold mb-3">Aucun test en cours.</h2>
        <p class="text-text-secondary mb-6 max-w-lg mx-auto">
          Crée ta première campagne avec 2 à 5 variantes de sujet.
          L'app distribuera les envois équitablement et te dira laquelle gagne.
        </p>
        <button class="btn btn-primary" id="ab-empty-new">+ Créer ma première campagne</button>
      </div>
    `;
  },

  _campaignCard(c) {
    const winnerId = c.winner_variant_id;
    return `
      <div class="card p-6 mb-6" data-camp-id="${this._esc(c.id)}">
        <div class="flex items-start justify-between mb-4 gap-3">
          <div>
            <div class="hero-kicker mb-1">CAMPAGNE</div>
            <h2 class="font-display text-xl font-bold" title="Référence interne : ${this._esc(c.id)}">${this._esc(c.name)}</h2>
            <div class="text-xs text-text-muted mt-1">${c.active ? '🟢 Active' : '⏸ En pause'}</div>
          </div>
          <div class="flex items-center gap-2 shrink-0">
            <button class="btn btn-secondary text-xs" data-camp-toggle="${this._esc(c.id)}" data-camp-active="${c.active ? '1' : '0'}">
              ${c.active ? 'Mettre en pause' : 'Reprendre'}
            </button>
            <button class="btn btn-secondary text-xs" data-camp-edit="${this._esc(c.id)}">Modifier</button>
            <button class="text-text-muted hover:text-danger text-xl leading-none px-1" data-camp-del="${this._esc(c.id)}"
                    title="Supprimer cette campagne" aria-label="Supprimer cette campagne">×</button>
          </div>
        </div>

        <div class="mb-4 p-3 rounded-lg ${winnerId ? 'bg-success/10 border border-success/30' : 'bg-bg border border-border'}">
          <div class="text-xs font-bold tracking-widest text-text-muted mb-1">VERDICT</div>
          <div class="text-sm">${this._esc(c.verdict || '—')}</div>
        </div>

        <div class="space-y-2">
          ${(c.variants || []).map((v, i) => this._variantRow(v, i, winnerId === v.id)).join('')}
        </div>

        <div class="mt-4 text-xs text-text-muted">
          Les sujets de ce test seront proposés automatiquement dans une prochaine mise à jour.
        </div>
      </div>
    `;
  },

  // Libellé lisible d'une variante : « Sujet A », « Sujet B »…
  _variantLabel(i) {
    return i < 26 ? `Sujet ${String.fromCharCode(65 + i)}` : `Sujet ${i + 1}`;
  },

  _variantRow(v, index, isWinner) {
    const sent = v.sent_count || 0;
    const reply = v.reply_count || 0;
    const rate = v.reply_rate || 0;
    const enough = v.enough_data;
    const tone = isWinner ? 'success' : (enough ? 'accent' : '');
    return `
      <div class="border ${isWinner ? 'border-success bg-success/5' : 'border-border'} rounded-xl p-3 flex items-center gap-4">
        <div class="text-xs font-bold tracking-widest w-16 shrink-0 ${isWinner ? 'text-success' : 'text-text-muted'}"
             title="Référence interne : ${this._esc(v.id || '')}">
          ${this._esc(this._variantLabel(index))} ${isWinner ? '👑' : ''}
        </div>
        <div class="flex-1 text-sm">${this._esc(v.subject || '(sans objet)')}</div>
        <div class="text-xs text-text-muted whitespace-nowrap">
          ${sent} envoyés · ${reply} réponses
        </div>
        <div class="text-sm font-semibold whitespace-nowrap ${tone === 'success' ? 'text-success' : (tone === 'accent' ? 'text-accent' : 'text-text-muted')}">
          ${rate}%
        </div>
      </div>
    `;
  },

  _campaignById(cid) {
    return ((this.data && this.data.campaigns) || []).find(c => c.id === cid) || null;
  },

  _bindCards() {
    // Suppression : confirmation avec le NOM (pas l'identifiant technique)
    // + vérification du résultat serveur.
    document.querySelectorAll('[data-camp-del]').forEach(btn => {
      btn.onclick = async () => {
        const cid = btn.dataset.campDel;
        const camp = this._campaignById(cid);
        const name = (camp && camp.name) || 'cette campagne';
        const sure = await Dialog.confirm(
          `Supprimer la campagne « ${name} » ? Toutes les statistiques seront perdues.`,
          { title: 'Supprimer ce test', okLabel: 'Supprimer', danger: true });
        if (!sure) return;
        btn.disabled = true;
        try {
          const r = await App.api.ab_delete_campaign({ id: cid });
          if (r && r.ok) Toast.success('Campagne supprimée.');
          else {
            console.warn('ab_delete_campaign:', r && r.error);
            Toast.error('Suppression impossible — la campagne n’a pas été retrouvée. Recharge la page.');
          }
        } catch (e) {
          Toast.friendlyError(e, 'Suppression impossible, réessaie.');
        }
        this.refresh();
      };
    });
    // Pause / Reprendre (écrit la config complète via ab_save_config)
    document.querySelectorAll('[data-camp-toggle]').forEach(btn => {
      btn.onclick = async () => {
        const cid = btn.dataset.campToggle;
        const wasActive = btn.dataset.campActive === '1';
        btn.disabled = true;
        try {
          await this._saveFullConfig(cfg => {
            const camp = (cfg.campaigns || []).find(c => c.id === cid);
            if (!camp) throw new Error('campagne introuvable');
            camp.active = !wasActive;
          });
          Toast.success(wasActive
            ? 'Campagne mise en pause — plus aucun envoi ne l’utilisera.'
            : 'Campagne relancée.');
        } catch (e) {
          Toast.friendlyError(e, 'Changement impossible pour le moment, réessaie.');
        }
        this.refresh();
      };
    });
    // Modifier : ajout de nouvelles variantes de sujet
    document.querySelectorAll('[data-camp-edit]').forEach(btn => {
      btn.onclick = () => this._openAddVariants(btn.dataset.campEdit);
    });
    // Seuil de verdict
    const thrBtn = document.getElementById('ab-threshold-save');
    if (thrBtn) thrBtn.onclick = async () => {
      const input = document.getElementById('ab-threshold');
      const n = parseInt(input && input.value, 10);
      if (!n || n < 5 || n > 1000) {
        Toast.warn('Choisis un seuil entre 5 et 1000 envois.');
        return;
      }
      thrBtn.disabled = true;
      try {
        await this._saveFullConfig(cfg => { cfg.min_sent_for_verdict = n; });
        Toast.success(`Seuil enregistré : verdict à partir de ${n} envois par sujet.`);
      } catch (e) {
        Toast.friendlyError(e, 'Enregistrement du seuil impossible, réessaie.');
      }
      this.refresh();
    };
    const emptyNew = document.getElementById('ab-empty-new');
    if (emptyNew) emptyNew.onclick = () => this._openNew();
  },

  // ---- Modale « Modifier » : ajouter des variantes à une campagne ----
  // (les sujets déjà mesurés ne sont pas modifiables : changer leur texte
  // fausserait les statistiques déjà accumulées)
  _openAddVariants(cid) {
    const camp = this._campaignById(cid);
    if (!camp) return;
    const overlay = document.createElement('div');
    overlay.className = 'fixed inset-0 z-[100] flex items-center justify-center p-6';
    overlay.style.background = 'rgba(15,23,42,0.45)';
    overlay.style.backdropFilter = 'blur(6px)';
    overlay.innerHTML = `
      <div class="bg-surface rounded-3xl shadow-hero w-full max-w-2xl overflow-hidden animate-slide-up"
           style="border: 1px solid hsl(var(--border));">
        <div class="px-7 pt-7 pb-3 border-b border-border">
          <div class="hero-kicker mb-1">MODIFIER LA CAMPAGNE</div>
          <div class="font-display text-xl font-bold">${this._esc(camp.name)}</div>
          <p class="text-xs text-text-muted mt-1">Ajoute de nouveaux sujets à tester. Les sujets existants ne sont pas modifiables : leurs statistiques sont déjà en cours de mesure.</p>
        </div>
        <div class="px-7 py-6 space-y-3">
          <label class="text-xs text-text-muted block" for="abe-variants">Nouveaux sujets (1 par ligne) :</label>
          <textarea id="abe-variants" rows="4" placeholder="Un nouveau sujet à tester…"
                    class="w-full px-4 py-2.5 text-sm rounded-xl bg-bg border border-border focus:outline-none focus:border-accent leading-relaxed"></textarea>
        </div>
        <div class="px-7 py-4 border-t border-border flex justify-end gap-2">
          <button class="btn btn-secondary" id="abe-cancel">Annuler</button>
          <button class="btn btn-primary" id="abe-save">Ajouter ces sujets</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);
    const close = () => {
      document.removeEventListener('keydown', escListener);
      overlay.remove();
    };
    const isDirty = () => !!(overlay.querySelector('#abe-variants').value.trim());
    const closeGuarded = async () => {
      if (isDirty()) {
        const sure = await Dialog.confirm(
          'Tes nouveaux sujets ne sont pas enregistrés. Fermer quand même ?',
          { title: 'Saisie en cours', okLabel: 'Fermer sans garder', cancelLabel: 'Continuer la saisie', danger: true });
        if (!sure) return;
      }
      close();
    };
    const escListener = (e) => { if (e.key === 'Escape') closeGuarded(); };
    document.addEventListener('keydown', escListener);
    overlay.querySelector('#abe-cancel').onclick = close;
    overlay.addEventListener('click', e => { if (e.target === overlay) closeGuarded(); });
    overlay.querySelector('#abe-save').onclick = async () => {
      const subjects = overlay.querySelector('#abe-variants').value
        .split('\n').map(s => s.trim()).filter(Boolean);
      if (!subjects.length) {
        Toast.warn('Écris au moins un nouveau sujet (1 par ligne).');
        return;
      }
      const saveBtn = overlay.querySelector('#abe-save');
      saveBtn.disabled = true;
      try {
        await this._saveFullConfig(cfg => {
          const target = (cfg.campaigns || []).find(c => c.id === cid);
          if (!target) throw new Error('campagne introuvable');
          target.variants = target.variants || [];
          // Prochain numéro interne : suite des v1, v2…
          let nextN = target.variants.reduce((m, v) => {
            const match = /^v(\d+)$/.exec(v.id || '');
            return match ? Math.max(m, parseInt(match[1], 10)) : m;
          }, target.variants.length);
          for (const s of subjects) {
            nextN += 1;
            target.variants.push({ id: `v${nextN}`, subject: s, sent_count: 0, reply_count: 0 });
          }
        });
        Toast.success(`${subjects.length} sujet${subjects.length > 1 ? 's' : ''} ajouté${subjects.length > 1 ? 's' : ''} à la campagne.`);
        close();
        this.refresh();
      } catch (e) {
        Toast.friendlyError(e, 'Ajout impossible pour le moment, réessaie.');
        saveBtn.disabled = false;
      }
    };
  },

  _openNew() {
    const overlay = document.createElement('div');
    overlay.className = 'fixed inset-0 z-[100] flex items-center justify-center p-6';
    overlay.style.background = 'rgba(15,23,42,0.45)';
    overlay.style.backdropFilter = 'blur(6px)';
    overlay.innerHTML = `
      <div class="bg-surface rounded-3xl shadow-hero w-full max-w-2xl overflow-hidden animate-slide-up"
           style="border: 1px solid hsl(var(--border));">
        <div class="px-7 pt-7 pb-3 border-b border-border">
          <div class="hero-kicker mb-1">NOUVELLE CAMPAGNE</div>
          <div class="font-display text-xl font-bold">Tester plusieurs sujets</div>
        </div>
        <div class="px-7 py-6 space-y-4">
          <input id="abn-name" placeholder="Nom de la campagne (ex : Premier contact froid)"
                 aria-label="Nom de la campagne"
                 class="w-full px-4 py-2.5 text-sm rounded-xl bg-bg border border-border focus:outline-none focus:border-accent" />
          <div>
            <label class="text-xs text-text-muted block mb-2" for="abn-variants">Sujets à comparer (1 par ligne, 2 minimum) :</label>
            <textarea id="abn-variants" rows="6" placeholder="Une idée pour {company_name}&#10;{company_name} — 30 secondes ?&#10;Un troisième sujet à tester"
                      class="w-full px-4 py-2.5 text-sm rounded-xl bg-bg border border-border focus:outline-none focus:border-accent font-mono leading-relaxed"></textarea>
          </div>
          <div class="text-xs text-text-muted">
            <div class="mb-1">Les parties entre accolades sont remplies automatiquement pour chaque prospect :
              <code>{company_name}</code> = nom de l'entreprise, <code>{name}</code> = prénom du contact, <code>{city}</code> = ville.</div>
            <div>Exemple : « Une idée pour {company_name} » devient « Une idée pour Boulangerie Martin ».</div>
          </div>
        </div>
        <div class="px-7 py-4 border-t border-border flex justify-end gap-2">
          <button class="btn btn-secondary" id="abn-cancel">Annuler</button>
          <button class="btn btn-primary" id="abn-save">Créer la campagne</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);
    const close = () => {
      document.removeEventListener('keydown', escListener);
      overlay.remove();
    };
    // Garde anti-perte de saisie sur clic-dehors / Échap
    const isDirty = () => !!(overlay.querySelector('#abn-name').value.trim()
                          || overlay.querySelector('#abn-variants').value.trim());
    const closeGuarded = async () => {
      if (isDirty()) {
        const sure = await Dialog.confirm(
          'Ta campagne n’est pas enregistrée. Fermer quand même ?',
          { title: 'Saisie en cours', okLabel: 'Fermer sans garder', cancelLabel: 'Continuer la saisie', danger: true });
        if (!sure) return;
      }
      close();
    };
    const escListener = (e) => { if (e.key === 'Escape') closeGuarded(); };
    document.addEventListener('keydown', escListener);
    overlay.querySelector('#abn-cancel').onclick = close;
    overlay.addEventListener('click', e => { if (e.target === overlay) closeGuarded(); });
    overlay.querySelector('#abn-save').onclick = async () => {
      const name = overlay.querySelector('#abn-name').value.trim();
      const variants = overlay.querySelector('#abn-variants').value
        .split('\n').map(s => s.trim()).filter(Boolean);
      if (!name || variants.length < 2) {
        Toast.warn('Il faut un nom et au moins 2 sujets (1 par ligne).');
        return;
      }
      const saveBtn = overlay.querySelector('#abn-save');
      saveBtn.disabled = true;
      try {
        const r = await App.api.ab_add_campaign({ name, variants });
        if (r && r.ok) {
          Toast.success('Campagne créée — les envois vont alterner entre tes sujets.');
          close();
          this.refresh();
        } else {
          console.warn('ab_add_campaign:', r && r.error);
          Toast.error('Création impossible : il faut un nom et au moins 2 sujets.');
          saveBtn.disabled = false;
        }
      } catch (e) {
        Toast.friendlyError(e, 'Création impossible pour le moment, réessaie.');
        saveBtn.disabled = false;
      }
    };
  },

  _esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    }[c]));
  },
};
