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
    document.getElementById('ab-back').onclick = () => App.show('config');
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
      document.getElementById('ab-content').innerHTML =
        `<div class="card p-6 text-danger">${r && r.error || 'Erreur'}</div>`;
      return;
    }
    this.data = r;
    const camps = r.campaigns || [];
    if (camps.length === 0) {
      document.getElementById('ab-content').innerHTML = this._emptyState();
      return;
    }
    document.getElementById('ab-content').innerHTML =
      camps.map(c => this._campaignCard(c)).join('');
    this._bindCards();
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
        <div class="flex items-start justify-between mb-4">
          <div>
            <div class="hero-kicker mb-1">CAMPAGNE</div>
            <h2 class="font-display text-xl font-bold">${this._esc(c.name)}</h2>
            <div class="text-xs text-text-muted mt-1">${c.active ? '🟢 Active' : '⚪ En pause'} · ID : <code>${this._esc(c.id)}</code></div>
          </div>
          <button class="text-text-muted hover:text-danger" data-camp-del="${this._esc(c.id)}" title="Supprimer">×</button>
        </div>

        <div class="mb-4 p-3 rounded-lg ${winnerId ? 'bg-success/10 border border-success/30' : 'bg-bg border border-border'}">
          <div class="text-xs font-bold tracking-widest text-text-muted mb-1">VERDICT</div>
          <div class="text-sm">${this._esc(c.verdict || '—')}</div>
        </div>

        <div class="space-y-2">
          ${(c.variants || []).map(v => this._variantRow(v, winnerId === v.id)).join('')}
        </div>

        <div class="mt-4 text-xs text-text-muted">
          Pour utiliser cette campagne dans l'auto-pilote, référence l'ID
          <code class="bg-bg px-1.5 py-0.5 rounded">${this._esc(c.id)}</code>
          dans tes instructions IA (intégration auto à venir).
        </div>
      </div>
    `;
  },

  _variantRow(v, isWinner) {
    const sent = v.sent_count || 0;
    const reply = v.reply_count || 0;
    const rate = v.reply_rate || 0;
    const enough = v.enough_data;
    const tone = isWinner ? 'success' : (enough ? 'accent' : '');
    return `
      <div class="border ${isWinner ? 'border-success bg-success/5' : 'border-border'} rounded-xl p-3 flex items-center gap-4">
        <div class="text-xs font-bold tracking-widest w-10 ${isWinner ? 'text-success' : 'text-text-muted'}">
          ${this._esc(v.id || '')} ${isWinner ? '👑' : ''}
        </div>
        <div class="flex-1 text-sm">${this._esc(v.subject || '(sans sujet)')}</div>
        <div class="text-xs text-text-muted whitespace-nowrap">
          ${sent} envoyés · ${reply} réponses
        </div>
        <div class="text-sm font-semibold whitespace-nowrap ${tone === 'success' ? 'text-success' : (tone === 'accent' ? 'text-accent' : 'text-text-muted')}">
          ${rate}%
        </div>
      </div>
    `;
  },

  _bindCards() {
    document.querySelectorAll('[data-camp-del]').forEach(btn => {
      btn.onclick = async () => {
        const cid = btn.dataset.campDel;
        if (!confirm(`Supprimer la campagne « ${cid} » ? Toutes les statistiques seront perdues.`)) return;
        await App.api.ab_delete_campaign({ id: cid });
        this.refresh();
      };
    });
    const emptyNew = document.getElementById('ab-empty-new');
    if (emptyNew) emptyNew.onclick = () => this._openNew();
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
                 class="w-full px-4 py-2.5 text-sm rounded-xl bg-bg border border-border focus:outline-none focus:border-accent" />
          <div>
            <label class="text-xs text-text-muted block mb-2">Variantes de sujet (1 par ligne, 2 minimum) :</label>
            <textarea id="abn-variants" rows="6" placeholder="Une idée pour {company_name}&#10;{company_name} — 30 secondes ?&#10;Sujet variante 3"
                      class="w-full px-4 py-2.5 text-sm rounded-xl bg-bg border border-border focus:outline-none focus:border-accent font-mono leading-relaxed"></textarea>
          </div>
          <div class="text-xs text-text-muted">
            Variables disponibles dans tes sujets : <code>{company_name}</code>, <code>{name}</code>, <code>{city}</code>.
          </div>
        </div>
        <div class="px-7 py-4 border-t border-border flex justify-end gap-2">
          <button class="btn btn-secondary" id="abn-cancel">Annuler</button>
          <button class="btn btn-primary" id="abn-save">Créer la campagne</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);
    overlay.querySelector('#abn-cancel').onclick = () => overlay.remove();
    overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });
    overlay.querySelector('#abn-save').onclick = async () => {
      const name = overlay.querySelector('#abn-name').value.trim();
      const variants = overlay.querySelector('#abn-variants').value
        .split('\n').map(s => s.trim()).filter(Boolean);
      if (!name || variants.length < 2) {
        alert('Il faut un nom + au moins 2 variantes de sujet.');
        return;
      }
      const r = await App.api.ab_add_campaign({ name, variants });
      if (r && r.ok) {
        overlay.remove();
        this.refresh();
      } else {
        alert('Erreur : ' + ((r && r.error) || 'inconnue'));
      }
    };
  },

  _esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    }[c]));
  },
};
