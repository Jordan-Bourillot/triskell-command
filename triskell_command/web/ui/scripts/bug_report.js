/* BugReport — bouton flottant pour signaler un bug avec contexte auto.
 *
 * Bouton discret en bas à droite (juste au-dessus du toast stack).
 * Au clic, ouvre une modale qui :
 *   - Affiche la vue où l'utilisateur était.
 *   - Affiche les 10 derniers appels API (depuis HealthCheck.errors).
 *   - Affiche les 5 dernières erreurs JS captées.
 *   - Affiche l'user agent + navigator info.
 *   - Permet à l'utilisateur d'ajouter un message libre.
 *
 * Au "Envoyer", on appelle App.api.bug_report({...}) qui logue côté
 * serveur (et qu'on peut transformer en mail/Supabase plus tard).
 * En attendant l'endpoint serveur, on peut aussi copier le rapport
 * dans le presse-papier — fallback robuste.
 */

const BugReport = {
  _wired: false,

  init() {
    if (this._wired) return;
    this._wired = true;
    this._injectStyles();
    this._injectButton();
  },

  _injectStyles() {
    if (document.getElementById('bug-report-styles')) return;
    const s = document.createElement('style');
    s.id = 'bug-report-styles';
    s.textContent = `
      #bug-report-fab {
        position: fixed; bottom: 16px; left: 16px;
        z-index: 99998;
        width: 36px; height: 36px;
        border-radius: 50%;
        background: hsl(var(--surface-elevated));
        border: 1px solid hsl(var(--border));
        color: hsl(var(--text-muted));
        display: flex; align-items: center; justify-content: center;
        cursor: pointer;
        opacity: 0.6;
        transition: opacity 160ms, transform 160ms;
        box-shadow: 0 2px 6px rgba(0,0,0,0.25);
      }
      #bug-report-fab:hover { opacity: 1; transform: scale(1.05); }
      #bug-report-fab svg { width: 18px; height: 18px; }
    `;
    document.head.appendChild(s);
  },

  _injectButton() {
    if (document.getElementById('bug-report-fab')) return;
    const btn = document.createElement('button');
    btn.id = 'bug-report-fab';
    btn.title = 'Signaler un bug';
    btn.setAttribute('aria-label', 'Signaler un bug');
    btn.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M12 2L3.5 8v8L12 22l8.5-6V8z"/>
      <line x1="12" y1="22" x2="12" y2="10"/>
      <line x1="3.5" y1="8" x2="12" y2="14"/>
      <line x1="20.5" y1="8" x2="12" y2="14"/>
    </svg>`;
    btn.onclick = () => this.open();
    document.body.appendChild(btn);
  },

  // ----- Collecte du contexte automatique -----
  _gatherContext() {
    const now = new Date();
    const ctx = {
      ts: now.toISOString(),
      url: window.location.href,
      view: (typeof App !== 'undefined' && App.currentView) || '(inconnue)',
      user_agent: navigator.userAgent,
      viewport: { w: window.innerWidth, h: window.innerHeight },
      online: navigator.onLine,
      demo_mode: (typeof DemoMode !== 'undefined' && DemoMode.isOn && DemoMode.isOn()),
      health_errors: [],
      health_api_issues: [],
    };
    if (typeof HealthCheck !== 'undefined' && HealthCheck.errors) {
      // Sépare erreurs JS et soucis API
      const all = HealthCheck.errors.slice(-20);
      ctx.health_errors = all.filter(e => /js_error|promise_rejection|fake_shape_error/.test(e.kind));
      ctx.health_api_issues = all.filter(e => /api_/.test(e.kind));
    }
    if (typeof App !== 'undefined' && App.currentUser) {
      ctx.user = {
        first_name: App.currentUser.first_name || '',
        email: App.currentUser.email || '',
      };
    }
    return ctx;
  },

  _formatReport(ctx, userMessage) {
    return [
      '=== Signalement bug Triskell Command ===',
      `Date : ${ctx.ts}`,
      `Vue active : ${ctx.view}`,
      `URL : ${ctx.url}`,
      `Utilisateur : ${ctx.user?.first_name || '(non identifié)'}`,
      `Mode démo : ${ctx.demo_mode ? 'OUI' : 'non'}`,
      `Navigateur : ${ctx.user_agent}`,
      `Viewport : ${ctx.viewport.w}×${ctx.viewport.h}`,
      `Connecté : ${ctx.online ? 'oui' : 'NON (hors-ligne)'}`,
      '',
      '--- Message de l\'utilisateur ---',
      userMessage || '(aucun)',
      '',
      `--- Erreurs JS récentes (${ctx.health_errors.length}) ---`,
      ctx.health_errors.length
        ? ctx.health_errors.map(e => `[${e.ts}] ${e.kind} : ${e.msg || ''}${e.loc ? ' @ ' + e.loc : ''}`).join('\n')
        : '(aucune)',
      '',
      `--- Soucis API récents (${ctx.health_api_issues.length}) ---`,
      ctx.health_api_issues.length
        ? ctx.health_api_issues.map(e => `[${e.ts}] ${e.kind} : ${e.method || ''} ${e.status || ''} ${e.elapsed_ms ? '(' + e.elapsed_ms + ' ms)' : ''}`).join('\n')
        : '(aucun)',
      '',
      '=== Fin du signalement ===',
    ].join('\n');
  },

  // ----- Modale -----
  open() {
    if (document.getElementById('bug-report-modal')) return;
    const ctx = this._gatherContext();

    const ov = document.createElement('div');
    ov.id = 'bug-report-modal';
    ov.className = 'fixed inset-0 z-[230] flex items-center justify-center p-4';
    ov.style.background = 'rgba(15,23,42,0.75)';
    ov.style.backdropFilter = 'blur(8px)';
    ov.innerHTML = `
      <div class="bg-surface rounded-2xl shadow-hero w-full max-w-2xl border border-border animate-slide-up flex flex-col overflow-hidden max-h-[88vh]">
        <div class="px-6 pt-5 pb-3 flex items-start justify-between border-b border-border bg-surface-elevated">
          <div>
            <div class="text-[10px] font-bold uppercase tracking-widest text-text-muted mb-0.5">SIGNALER UN BUG</div>
            <h3 class="text-lg font-bold">Que se passe-t-il ?</h3>
            <p class="text-xs text-text-muted mt-1">Décris ce qui ne va pas. Le contexte technique est joint automatiquement (vue, erreurs JS, état des appels API).</p>
          </div>
          <button id="br-close" class="w-8 h-8 rounded-lg flex items-center justify-center text-text-muted hover:text-text hover:bg-bg text-xl leading-none shrink-0">×</button>
        </div>

        <div class="p-5 overflow-y-auto space-y-4">
          <div>
            <label class="block text-[11px] font-medium text-text-secondary mb-1 uppercase tracking-wider">Ce qui ne va pas</label>
            <textarea id="br-msg" rows="5" placeholder="Ex : Quand je clique sur 'Composer un mail' depuis le Cockpit, la modale ne s'ouvre pas..."
                      class="w-full px-3 py-2.5 text-sm rounded-lg bg-bg border border-border focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent resize-y"></textarea>
          </div>

          <details class="text-xs">
            <summary class="cursor-pointer text-text-muted hover:text-text font-semibold">Voir le contexte technique qui sera envoyé</summary>
            <pre id="br-context" class="mt-2 p-3 rounded-lg bg-bg border border-border text-[11px] overflow-x-auto whitespace-pre-wrap max-h-64 overflow-y-auto"></pre>
          </details>

          <div id="br-status" class="text-xs min-h-[1rem]"></div>
        </div>

        <div class="px-5 py-4 border-t border-border bg-surface-elevated flex items-center justify-between gap-2">
          <button id="br-copy" type="button" class="text-xs text-text-muted hover:text-accent flex items-center gap-1.5">
            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
            Copier le rapport
          </button>
          <div class="flex items-center gap-2">
            <button id="br-cancel" class="btn btn-secondary">Annuler</button>
            <button id="br-send" class="btn btn-primary">Envoyer le rapport</button>
          </div>
        </div>
      </div>
    `;
    document.body.appendChild(ov);

    // Pré-remplit l'aperçu du contexte
    const msgInput = ov.querySelector('#br-msg');
    const ctxPreview = ov.querySelector('#br-context');
    const refreshPreview = () => {
      ctxPreview.textContent = this._formatReport(ctx, msgInput.value);
    };
    refreshPreview();
    msgInput.addEventListener('input', refreshPreview);
    setTimeout(() => msgInput.focus(), 50);

    const close = () => {
      document.removeEventListener('keydown', escListener);
      ov.remove();
    };
    const escListener = (e) => { if (e.key === 'Escape') close(); };
    document.addEventListener('keydown', escListener);
    ov.querySelector('#br-close').onclick = close;
    ov.querySelector('#br-cancel').onclick = close;
    ov.addEventListener('click', (e) => { if (e.target === ov) close(); });

    // Copier le rapport dans le presse-papier
    ov.querySelector('#br-copy').onclick = async () => {
      const text = this._formatReport(ctx, msgInput.value);
      try {
        await navigator.clipboard.writeText(text);
        const status = ov.querySelector('#br-status');
        status.textContent = '✓ Rapport copié dans le presse-papier — colle-le où tu veux';
        status.className = 'text-xs text-success min-h-[1rem]';
      } catch (e) {
        alert('Copie impossible. Sélectionne le texte ci-dessus manuellement.');
      }
    };

    // Envoi vers le serveur (best-effort)
    ov.querySelector('#br-send').onclick = async () => {
      const status = ov.querySelector('#br-status');
      const sendBtn = ov.querySelector('#br-send');
      const text = this._formatReport(ctx, msgInput.value);
      sendBtn.disabled = true;
      sendBtn.textContent = 'Envoi…';
      status.textContent = '';
      try {
        if (App.api && App.api.bug_report) {
          const r = await App.api.bug_report({
            message: msgInput.value,
            context: ctx,
            full_report: text,
          });
          if (r && r.ok) {
            status.textContent = '✓ Rapport envoyé. Merci !';
            status.className = 'text-xs text-success min-h-[1rem]';
            setTimeout(close, 1200);
            return;
          }
          throw new Error((r && r.error) || 'Erreur serveur');
        }
        // Fallback : si pas d'endpoint serveur, on copie + on rappelle à l'utilisateur
        await navigator.clipboard.writeText(text);
        status.textContent = '✓ Rapport copié dans le presse-papier (l\'endpoint serveur n\'est pas encore branché). Envoie-le à Jordan.';
        status.className = 'text-xs text-success min-h-[1rem]';
        setTimeout(close, 2500);
      } catch (e) {
        status.textContent = `✗ ${e.message || e}. Utilise "Copier le rapport" en bas à gauche.`;
        status.className = 'text-xs text-danger min-h-[1rem]';
        sendBtn.disabled = false;
        sendBtn.textContent = 'Envoyer le rapport';
      }
    };
  },
};

window.BugReport = BugReport;
window.addEventListener('DOMContentLoaded', () => BugReport.init());
