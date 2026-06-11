/* ShortcutsHelp — modale qui liste tous les raccourcis clavier de l'app.
 *
 * S'ouvre avec ? (sans modificateur) ou Shift+? quand aucun input n'a
 * le focus. Standard adopté par Linear, Notion, GitHub, etc.
 *
 * Les raccourcis listés ici sont les VRAIS bindings actifs dans l'app
 * (vérifiés le 11/06/2026 : app.js pour Ctrl+Espace / Alt+T / Ctrl+B /
 * Ctrl+Maj+M / Échap, global_search.js pour Ctrl+K, launcher.js pour le
 * lanceur d'outils, thomas.js pour Ctrl+J, mails.js pour la fenêtre
 * d'écriture). F11, F12 et Ctrl+T ont été supprimés (conflits
 * navigateur). Si tu ajoutes un raccourci, complète aussi ce fichier.
 */

const ShortcutsHelp = {
  SHORTCUTS: [
    {
      group: 'Navigation',
      items: [
        { keys: ['Ctrl', 'K'], mac: ['⌘', 'K'], desc: 'Recherche globale (écrans, clients, mails, notes, …)' },
        { keys: ['Ctrl', 'O'], mac: ['⌘', 'O'], desc: 'Lanceur d’outils Triskell (toutes les apps maison)' },
        { keys: ['Alt', 'T'], mac: ['⌥', 'T'], desc: 'Changer de thème (clair / intermédiaire / sombre)' },
      ],
    },
    {
      group: 'Assistant & équipe',
      items: [
        { keys: ['Ctrl', 'Espace'], mac: ['⌃', 'Espace'], desc: 'Ouvrir le copilote (l’assistant qui répond et agit)' },
        { keys: ['Ctrl', 'J'], mac: ['⌃', 'J'], desc: 'Ouvrir le chat avec Thomas' },
        { keys: ['Ctrl', 'B'], mac: ['⌃', 'B'], desc: 'Nouvelle note rapide (Boîte à idées)' },
      ],
    },
    {
      group: 'Mails',
      items: [
        { keys: ['Ctrl', 'Maj', 'M'], mac: ['⌘', '⇧', 'M'], desc: 'Nouveau mail (depuis n’importe quel écran)' },
        { keys: ['Ctrl', 'Entrée'], mac: ['⌘', '↵'], desc: 'Envoyer le mail (dans la fenêtre d’écriture)' },
        { keys: ['Entrée'], mac: ['↵'], desc: 'Dans le champ destinataires : valider l’adresse en pastille' },
        { keys: ['Tab'], mac: ['Tab'], desc: 'Dans le champ destinataires : valider l’adresse en pastille' },
        { keys: ['Retour arrière'], mac: ['⌫'], desc: 'Dans le champ destinataires : retirer la dernière pastille' },
      ],
    },
    {
      group: 'Fermer',
      items: [
        { keys: ['Échap'], mac: ['esc'], desc: 'Fermer la fenêtre ouverte, et le menu sur téléphone (sauf la fenêtre d’écriture de mail — pour ne pas perdre ton texte)' },
      ],
    },
    {
      group: 'Cette aide',
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
      <div class="bg-surface rounded-2xl shadow-hero w-full max-w-2xl border border-border animate-slide-up overflow-hidden flex flex-col max-h-[85vh]"
           role="dialog" aria-modal="true" aria-label="Raccourcis clavier">
        <div class="px-6 pt-5 pb-3 flex items-start justify-between border-b border-border bg-surface-elevated">
          <div>
            <div class="text-[11px] font-bold uppercase tracking-widest text-text-muted mb-0.5">RACCOURCIS CLAVIER</div>
            <h3 class="text-lg font-bold">Tout ce qui se fait au clavier</h3>
            <p class="text-xs text-text-muted mt-1">Astuce : tape <kbd class="px-1 py-0.5 rounded bg-bg border border-border text-[11px]">?</kbd> n'importe où pour rouvrir cette aide.</p>
          </div>
          <button id="sh-close" aria-label="Fermer" title="Fermer (Échap)"
                  class="w-8 h-8 rounded-lg flex items-center justify-center text-text-muted hover:text-text hover:bg-bg text-xl leading-none shrink-0">×</button>
        </div>

        <div class="p-5 overflow-y-auto space-y-5">
          ${this.SHORTCUTS.map(g => `
            <div>
              <div class="text-[11px] font-bold uppercase tracking-widest text-accent mb-2">${this._esc(g.group)}</div>
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
