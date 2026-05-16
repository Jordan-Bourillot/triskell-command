/* ShortcutsHelp — modale qui liste tous les raccourcis clavier de l'app.
 *
 * S'ouvre avec ? (sans modificateur) ou Shift+? quand aucun input n'a
 * le focus. Standard adopté par Linear, Notion, GitHub, etc.
 *
 * Les raccourcis listés ici sont les VRAIS bindings actifs dans l'app
 * (vérifiés case par case en lisant les addEventListener('keydown',...)
 * du codebase). Si tu ajoutes un raccourci, complète aussi ce fichier.
 */

const ShortcutsHelp = {
  SHORTCUTS: [
    {
      group: 'Navigation',
      items: [
        { keys: ['Ctrl', 'K'], mac: ['⌘', 'K'], desc: 'Recherche globale (vues, clients, mails, notes, …)' },
        { keys: ['Ctrl', 'B'], mac: ['⌘', 'B'], desc: 'Brain — nouvelle note rapide' },
        { keys: ['Ctrl', 'T'], mac: ['⌘', 'T'], desc: 'Cycler le thème (clair / intermédiaire / sombre)' },
      ],
    },
    {
      group: 'Mails',
      items: [
        { keys: ['Ctrl', 'Shift', 'M'], mac: ['⌘', '⇧', 'M'], desc: 'Composer un nouveau mail (depuis n\'importe quelle vue)' },
        { keys: ['Ctrl', 'Entrée'], mac: ['⌘', '↵'], desc: 'Envoyer le mail (dans le composer)' },
        { keys: ['Tab'], mac: ['Tab'], desc: 'Dans le champ destinataires : valider l\'adresse en pastille' },
        { keys: ['Entrée'], mac: ['↵'], desc: 'Dans le champ destinataires : valider l\'adresse en pastille' },
        { keys: ['Retour arrière'], mac: ['⌫'], desc: 'Dans le champ destinataires : retirer la dernière pastille' },
      ],
    },
    {
      group: 'Modales',
      items: [
        { keys: ['Échap'], mac: ['esc'], desc: 'Fermer la modale active (sauf composer mail — pour éviter de perdre du travail)' },
      ],
    },
    {
      group: 'Cette palette',
      items: [
        { keys: ['?'], mac: ['?'], desc: 'Ouvrir cette aide' },
      ],
    },
  ],

  isMac() {
    return /Mac|iPhone|iPad/i.test(navigator.platform || navigator.userAgent || '');
  },

  open() {
    if (document.getElementById('sh-overlay')) return;
    const mac = this.isMac();

    const ov = document.createElement('div');
    ov.id = 'sh-overlay';
    ov.className = 'fixed inset-0 z-[245] flex items-center justify-center p-4';
    ov.style.background = 'rgba(15,23,42,0.75)';
    ov.style.backdropFilter = 'blur(8px)';
    ov.innerHTML = `
      <div class="bg-surface rounded-2xl shadow-hero w-full max-w-2xl border border-border animate-slide-up overflow-hidden flex flex-col max-h-[85vh]">
        <div class="px-6 pt-5 pb-3 flex items-start justify-between border-b border-border bg-surface-elevated">
          <div>
            <div class="text-[10px] font-bold uppercase tracking-widest text-text-muted mb-0.5">RACCOURCIS CLAVIER</div>
            <h3 class="text-lg font-bold">Tout ce qui se fait au clavier</h3>
            <p class="text-xs text-text-muted mt-1">Appuie sur <kbd class="px-1 py-0.5 rounded bg-bg border border-border text-[10px]">?</kbd> n'importe où dans l'app pour rouvrir cette aide.</p>
          </div>
          <button id="sh-close" class="w-8 h-8 rounded-lg flex items-center justify-center text-text-muted hover:text-text hover:bg-bg text-xl leading-none shrink-0">×</button>
        </div>

        <div class="p-5 overflow-y-auto space-y-5">
          ${this.SHORTCUTS.map(g => `
            <div>
              <div class="text-[10px] font-bold uppercase tracking-widest text-accent mb-2">${this._esc(g.group)}</div>
              <div class="card">
                ${g.items.map((it, i) => `
                  <div class="flex items-center justify-between gap-4 px-4 py-3 ${i > 0 ? 'border-t border-border' : ''}">
                    <span class="text-sm text-text">${this._esc(it.desc)}</span>
                    <span class="flex items-center gap-1 shrink-0">
                      ${(mac ? it.mac : it.keys).map(k => `<kbd class="px-2 py-1 rounded bg-bg border border-border text-[11px] font-bold text-text">${this._esc(k)}</kbd>`).join('<span class="text-text-muted text-xs">+</span>')}
                    </span>
                  </div>
                `).join('')}
              </div>
            </div>
          `).join('')}
        </div>
      </div>
    `;
    document.body.appendChild(ov);
    const close = () => {
      document.removeEventListener('keydown', escListener);
      ov.remove();
    };
    const escListener = (e) => { if (e.key === 'Escape') close(); };
    document.addEventListener('keydown', escListener);
    ov.querySelector('#sh-close').onclick = close;
    ov.addEventListener('click', (e) => { if (e.target === ov) close(); });
  },

  _esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;',
    }[c]));
  },

  init() {
    document.addEventListener('keydown', (e) => {
      // Ouvrir avec ? — uniquement si on n'est pas dans un input/textarea
      if (e.key !== '?') return;
      // Ne pas intercepter si on tape dans un input/textarea/contenteditable
      const target = e.target;
      const tag = target && target.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || (target && target.isContentEditable)) {
        return;
      }
      e.preventDefault();
      this.open();
    });
  },
};

window.ShortcutsHelp = ShortcutsHelp;
window.addEventListener('DOMContentLoaded', () => ShortcutsHelp.init());
