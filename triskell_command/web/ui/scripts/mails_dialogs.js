/* MailsDialogs — modales secondaires du module Mails extraites de mails.js.
 *
 * Ces 3 modales sont attachées à `Mails` après chargement (donc ce
 * fichier doit être inclus APRÈS scripts/mails.js dans index.html).
 *
 *   - Mails._showDraftRestoreBanner(overlay, draft, onRestore)
 *   - Mails._openScheduleDialog(onConfirm)
 *   - Mails._openImageLinkDialog(img)
 *
 * Les autres modales (composer, prospect flow, templates manager, html
 * preview, paste html) restent dans mails.js car elles partagent trop de
 * closures avec _openComposer.
 *
 * Bénéfice : mails.js perd ~280 lignes ; ces modales sont isolées et
 * faciles à modifier sans toucher au composer principal.
 */

(function attachMailsDialogs() {
  if (typeof Mails === 'undefined') {
    console.warn('[mails_dialogs] Mails non défini — charge mails.js avant ce fichier.');
    return;
  }

  /** Affiche un bandeau "Brouillon trouvé" en haut du composer.
   *  onRestore : callback appelée si l'utilisateur clique "Restaurer". */
  Mails._showDraftRestoreBanner = function(overlay, draft, onRestore) {
    const scrollContainer = overlay.querySelector('.flex-1.overflow-y-auto');
    if (!scrollContainer) return;
    const banner = document.createElement('div');
    banner.className = 'mb-3 p-3 rounded-xl border border-accent/40 bg-accent/10 flex items-start gap-3';
    const ago = (() => {
      const min = Math.floor((Date.now() - (draft.ts || Date.now())) / 60_000);
      if (min < 1) return 'à l\'instant';
      if (min < 60) return `il y a ${min} min`;
      const h = Math.floor(min / 60);
      if (h < 24) return `il y a ${h} h`;
      return `il y a ${Math.floor(h / 24)} j`;
    })();
    const preview = (draft.subject || draft.to || '(sans objet)').slice(0, 60);
    banner.innerHTML = `
      <svg class="w-5 h-5 text-accent shrink-0 mt-0.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
        <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/>
        <polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/>
      </svg>
      <div class="flex-1 min-w-0">
        <div class="text-sm font-semibold text-text">Brouillon trouvé (${ago})</div>
        <div class="text-xs text-text-muted truncate">${this._escape(preview)}</div>
      </div>
      <div class="flex items-center gap-2 shrink-0">
        <button type="button" data-draft-restore class="text-xs font-semibold text-accent hover:underline">Restaurer</button>
        <button type="button" data-draft-discard class="text-xs text-text-muted hover:text-danger">Ignorer</button>
      </div>
    `;
    scrollContainer.insertBefore(banner, scrollContainer.firstChild);
    banner.querySelector('[data-draft-restore]').onclick = () => {
      try { onRestore && onRestore(); } catch (e) { console.error('draft restore', e); }
      banner.remove();
    };
    banner.querySelector('[data-draft-discard]').onclick = () => {
      try { localStorage.removeItem('tc-mail-draft'); } catch (e) {}
      banner.remove();
    };
  };

  /** Modale "Envoyer plus tard" : choix date/heure + raccourcis rapides.
   *  Appelle onConfirm(scheduledAtISO, prettyDate) si l'utilisateur valide. */
  Mails._openScheduleDialog = function(onConfirm) {
    const pad = (n) => String(n).padStart(2, '0');
    const isoFromDate = (d) => `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
    const prettyFR = (d) => {
      const days = ['dimanche','lundi','mardi','mercredi','jeudi','vendredi','samedi'];
      const months = ['janv.','févr.','mars','avr.','mai','juin','juil.','août','sept.','oct.','nov.','déc.'];
      return `${days[d.getDay()]} ${d.getDate()} ${months[d.getMonth()]} à ${pad(d.getHours())}h${pad(d.getMinutes())}`;
    };

    const now = new Date();
    const in1h = new Date(now.getTime() + 60*60*1000);
    const tonight = new Date(now); tonight.setHours(18, 0, 0, 0);
    if (tonight <= now) tonight.setDate(tonight.getDate() + 1);
    const tomorrow9 = new Date(now); tomorrow9.setDate(tomorrow9.getDate() + 1); tomorrow9.setHours(9, 0, 0, 0);
    const nextMonday = new Date(now);
    const dow = nextMonday.getDay();
    const daysToMonday = ((1 - dow + 7) % 7) || 7;
    nextMonday.setDate(nextMonday.getDate() + daysToMonday);
    nextMonday.setHours(9, 0, 0, 0);

    const presets = [
      { label: 'Dans 1 heure',   date: in1h,        kicker: prettyFR(in1h) },
      { label: 'Ce soir 18 h',   date: tonight,     kicker: prettyFR(tonight) },
      { label: 'Demain 9 h',     date: tomorrow9,   kicker: prettyFR(tomorrow9) },
      { label: 'Lundi 9 h',      date: nextMonday,  kicker: prettyFR(nextMonday) },
    ];
    const defaultDt = isoFromDate(tomorrow9);

    const ov = document.createElement('div');
    ov.className = 'fixed inset-0 z-[230] flex items-center justify-center p-4';
    ov.style.background = 'rgba(15,23,42,0.75)';
    ov.style.backdropFilter = 'blur(8px)';
    ov.innerHTML = `
      <div class="bg-surface rounded-2xl shadow-hero w-full max-w-md border border-border animate-slide-up flex flex-col overflow-hidden">
        <div class="px-5 pt-4 pb-3 border-b border-border bg-surface-elevated">
          <div class="text-[10px] font-bold uppercase tracking-widest text-text-muted mb-0.5">PROGRAMMER L'ENVOI</div>
          <h3 class="text-base font-bold">Quand envoyer ce mail ?</h3>
          <p class="text-xs text-text-muted mt-1">Le mail partira automatiquement à l'heure choisie, même si tu fermes l'app.</p>
        </div>
        <div class="p-4 space-y-3">
          <div class="grid grid-cols-2 gap-2">
            ${presets.map((p, i) => `
              <button data-preset="${i}" type="button"
                      class="text-left px-3 py-2.5 rounded-xl border border-border hover:border-accent hover:bg-accent/5 transition-colors">
                <div class="text-sm font-semibold text-text">${p.label}</div>
                <div class="text-[10px] text-text-muted mt-0.5">${p.kicker}</div>
              </button>
            `).join('')}
          </div>
          <div class="pt-2 border-t border-border">
            <label class="block text-[11px] font-medium text-text-secondary mb-1 uppercase tracking-wider">Ou choisis une date / heure</label>
            <input id="sched-dt" type="datetime-local" value="${defaultDt}"
                   class="w-full px-3 py-2.5 text-sm rounded-lg bg-bg border border-border focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent"/>
            <div id="sched-preview" class="text-[11px] text-text-muted mt-1.5"></div>
          </div>
        </div>
        <div class="px-5 py-4 border-t border-border bg-surface-elevated flex items-center justify-end gap-2">
          <button id="sched-cancel" type="button" class="btn btn-secondary">Annuler</button>
          <button id="sched-confirm" type="button" class="btn btn-primary">
            <svg class="w-4 h-4 mr-1.5 inline" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
            Programmer
          </button>
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
    ov.querySelector('#sched-cancel').onclick = close;
    ov.addEventListener('click', (e) => { if (e.target === ov) close(); });

    const dtInput = ov.querySelector('#sched-dt');
    const previewEl = ov.querySelector('#sched-preview');
    const updatePreview = () => {
      try {
        const v = dtInput.value;
        if (!v) { previewEl.textContent = ''; return; }
        const d = new Date(v);
        if (isNaN(d.getTime())) { previewEl.textContent = ''; return; }
        if (d <= new Date()) {
          previewEl.textContent = '⚠ Cette date est passée. Choisis un moment dans le futur.';
          previewEl.className = 'text-[11px] text-danger mt-1.5';
        } else {
          previewEl.textContent = `→ ${prettyFR(d)}`;
          previewEl.className = 'text-[11px] text-success mt-1.5';
        }
      } catch (e) {}
    };
    dtInput.addEventListener('input', updatePreview);
    updatePreview();

    ov.querySelectorAll('[data-preset]').forEach(btn => {
      btn.onclick = () => {
        const idx = parseInt(btn.dataset.preset, 10);
        dtInput.value = isoFromDate(presets[idx].date);
        updatePreview();
      };
    });

    ov.querySelector('#sched-confirm').onclick = () => {
      const v = dtInput.value;
      if (!v) return;
      const d = new Date(v);
      if (isNaN(d.getTime()) || d <= new Date()) {
        previewEl.textContent = '⚠ Date invalide ou déjà passée.';
        previewEl.className = 'text-[11px] text-danger mt-1.5';
        return;
      }
      close();
      try { onConfirm(d.toISOString(), prettyFR(d)); }
      catch (e) { console.error('schedule onConfirm', e); }
    };
  };

  /** Ouvre une modale pour rendre une image cliquable (lien URL).
   *  Si elle est déjà entourée d'un <a>, pré-remplit l'URL existante. */
  Mails._openImageLinkDialog = function(img) {
    const existingLink = img.parentElement && img.parentElement.tagName === 'A'
      ? img.parentElement : null;
    const currentUrl = existingLink ? existingLink.getAttribute('href') || '' : '';

    const ov = document.createElement('div');
    ov.className = 'fixed inset-0 z-[230] flex items-center justify-center p-4';
    ov.style.background = 'rgba(15,23,42,0.75)';
    ov.style.backdropFilter = 'blur(8px)';
    ov.innerHTML = `
      <div class="bg-surface rounded-2xl shadow-hero w-full max-w-md border border-border animate-slide-up flex flex-col overflow-hidden">
        <div class="px-5 pt-4 pb-3 border-b border-border bg-surface-elevated">
          <div class="text-[10px] font-bold uppercase tracking-widest text-text-muted mb-0.5">IMAGE</div>
          <h3 class="text-base font-bold">${existingLink ? 'Modifier le lien' : 'Rendre l\'image cliquable'}</h3>
          <p class="text-xs text-text-muted mt-1">Quand le destinataire cliquera sur l'image, il sera redirigé vers l'URL ci-dessous.</p>
        </div>
        <div class="p-5 space-y-3">
          <div>
            <label class="block text-[11px] font-medium text-text-secondary mb-1 uppercase tracking-wider">URL de destination</label>
            <input id="img-link-url" type="url" value="${this._escape(currentUrl)}"
                   placeholder="https://triskell-studio.fr"
                   class="w-full px-3 py-2.5 text-sm rounded-lg bg-bg border border-border focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent"/>
            <div class="text-[10px] text-text-muted mt-1">Laisse vide et clique "Enregistrer" pour retirer le lien.</div>
          </div>
        </div>
        <div class="px-5 py-4 border-t border-border bg-surface-elevated flex items-center justify-between gap-2">
          ${existingLink
            ? '<button id="img-link-remove" type="button" class="text-xs text-danger hover:underline">Retirer le lien</button>'
            : '<div></div>'}
          <div class="flex items-center gap-2">
            <button id="img-link-cancel" type="button" class="btn btn-secondary">Annuler</button>
            <button id="img-link-save" type="button" class="btn btn-primary">Enregistrer</button>
          </div>
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

    ov.querySelector('#img-link-cancel').onclick = close;
    ov.addEventListener('click', (e) => { if (e.target === ov) close(); });

    const urlInput = ov.querySelector('#img-link-url');
    setTimeout(() => { urlInput.focus(); urlInput.select(); }, 50);
    urlInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        ov.querySelector('#img-link-save').click();
      }
    });

    const wrapImageInLink = (url) => {
      const a = document.createElement('a');
      a.setAttribute('href', url);
      a.setAttribute('target', '_blank');
      a.setAttribute('rel', 'noopener noreferrer');
      img.parentNode.insertBefore(a, img);
      a.appendChild(img);
    };
    const unwrapImageFromLink = () => {
      if (!existingLink) return;
      existingLink.parentNode.insertBefore(img, existingLink);
      existingLink.remove();
    };

    ov.querySelector('#img-link-save').onclick = () => {
      let url = urlInput.value.trim();
      if (!url) {
        unwrapImageFromLink();
        img.style.cursor = '';
        img.removeAttribute('title');
        close();
        return;
      }
      if (!/^[a-z][a-z0-9+.-]*:/i.test(url)) {
        url = 'https://' + url;
      }
      if (existingLink) {
        existingLink.setAttribute('href', url);
        existingLink.setAttribute('target', '_blank');
        existingLink.setAttribute('rel', 'noopener noreferrer');
      } else {
        wrapImageInLink(url);
      }
      img.title = `Lien vers ${url}`;
      close();
    };

    const removeBtn = ov.querySelector('#img-link-remove');
    if (removeBtn) {
      removeBtn.onclick = () => {
        unwrapImageFromLink();
        img.style.cursor = '';
        img.removeAttribute('title');
        close();
      };
    }
  };

})();
