/* Onboarding — modale au premier lancement.
 *
 * Affichée si `get_current_user().needs_onboarding == true`.
 * Demande prénom (obligatoire) + email pro (optionnel).
 * Sauve via save_user_identity() puis ferme la modale.
 *
 * App.init() appelle Onboarding.checkAndShow() au boot.
 */

const Onboarding = {
  shown: false,

  async checkAndShow() {
    if (!App.api || this.shown) return;
    let r;
    try { r = await App.api.get_current_user(); }
    catch (e) { return; }
    if (!r || !r.needs_onboarding) {
      // Stocke le user dans App pour que la sidebar puisse l'afficher
      App.currentUser = r || {};
      return;
    }
    this._show();
  },

  _show() {
    this.shown = true;
    const overlay = document.createElement('div');
    overlay.id = 'onboarding-overlay';
    overlay.className = 'fixed inset-0 z-[200] flex items-center justify-center p-6';
    overlay.style.background = 'rgba(15,23,42,0.65)';
    overlay.style.backdropFilter = 'blur(8px)';
    overlay.innerHTML = `
      <div class="bg-surface rounded-3xl shadow-hero w-full max-w-md
                  overflow-hidden animate-slide-up"
           style="border: 1px solid hsl(var(--border));">
        <div class="px-8 pt-8 pb-2 text-center">
          <div class="w-16 h-16 mx-auto mb-5 rounded-2xl
                      bg-gradient-to-br from-accent to-accent-glow
                      flex items-center justify-center text-3xl shadow-soft">
            👋
          </div>
          <div class="hero-kicker mb-2">BIENVENUE</div>
          <h2 class="font-display font-bold text-2xl mb-2 leading-tight">
            On commence par te connaître ?
          </h2>
          <p class="text-text-secondary text-sm leading-relaxed">
            L'app utilisera ton prénom pour personnaliser la Matinale et
            signer les mails que l'IA rédige pour toi.
          </p>
        </div>

        <div class="px-8 py-6 space-y-4">
          <div>
            <label class="block text-xs font-medium text-text-secondary mb-1.5">
              Ton prénom (ou prénom + nom)
            </label>
            <input type="text" id="ob-name" autofocus
                   placeholder="ex : Jordan, ou Jordan Bourillot"
                   class="w-full px-4 py-3 text-base rounded-xl bg-bg border border-border
                          focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent" />
          </div>
          <div>
            <label class="block text-xs font-medium text-text-secondary mb-1.5">
              Ton email pro (optionnel — sera l'expéditeur de tes mails)
            </label>
            <input type="email" id="ob-email"
                   placeholder="ex : jordan@triskell-studio.fr"
                   class="w-full px-4 py-3 text-base rounded-xl bg-bg border border-border
                          focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent" />
            <div class="text-[11px] text-text-muted mt-1">
              Tu pourras compléter le reste (mot de passe, IMAP) plus tard dans Réglages.
            </div>
          </div>
        </div>

        <div class="px-8 py-5 border-t border-border flex justify-end gap-2">
          <button class="btn btn-secondary" id="ob-skip">Plus tard</button>
          <button class="btn btn-primary" id="ob-save">C'est parti ✓</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);

    const nameInput = overlay.querySelector('#ob-name');
    const emailInput = overlay.querySelector('#ob-email');
    const skipBtn = overlay.querySelector('#ob-skip');
    const saveBtn = overlay.querySelector('#ob-save');

    setTimeout(() => nameInput.focus(), 100);

    // Entrée → submit
    nameInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') saveBtn.click();
    });
    emailInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') saveBtn.click();
    });

    skipBtn.onclick = () => {
      // Pose un nom neutre pour ne pas re-prompt à chaque lancement
      this._save('Toi', '', overlay);
    };

    saveBtn.onclick = async () => {
      const name = nameInput.value.trim();
      if (!name) {
        nameInput.style.borderColor = 'hsl(var(--danger))';
        nameInput.focus();
        return;
      }
      saveBtn.disabled = true; saveBtn.textContent = 'Enregistrement…';
      await this._save(name, emailInput.value.trim(), overlay);
    };
  },

  async _save(fullName, email, overlay) {
    if (!App.api) { overlay.remove(); return; }
    try {
      const r = await App.api.save_user_identity({
        full_name: fullName, email,
      });
      if (!r || !r.ok) {
        alert('Erreur : ' + ((r && r.error) || 'inconnue'));
        return;
      }
      // Recharge l'identité côté App + rafraîchit la vue
      const u = await App.api.get_current_user();
      App.currentUser = u || {};
      overlay.style.opacity = '0';
      overlay.style.transition = 'opacity 200ms';
      setTimeout(() => {
        overlay.remove();
        // Refresh la matinale pour afficher le nouveau prénom
        if (App.currentView === 'morning') App.show('morning');
        // Met à jour le bandeau sidebar
        if (typeof UserBadge !== 'undefined') UserBadge.refresh();
      }, 220);
    } catch (e) {
      alert('Erreur : ' + e);
    }
  },
};
