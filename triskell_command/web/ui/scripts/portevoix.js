// Porte-Voix — les clients suivis et leurs rapports mensuels.
// Tout se pilote ici : ajouter un client, tenir ses rubriques du mois,
// préparer son rapport (mesure incluse) et l'ouvrir/le télécharger.
// Le rapport n'est JAMAIS envoyé au client automatiquement.
const PorteVoix = {
  state: { clients: [], auto: false, mesures: {}, formOuvert: false, edite: null },

  esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  },

  // Nombre en écriture française (16.7 -> « 16,7 »)
  fmt(n) {
    if (n == null || isNaN(n)) return "—";
    return String(Math.round(Number(n) * 10) / 10).replace(".", ",");
  },

  dateFr(ts) {
    const t = String(ts || "");
    if (t.length < 10) return "";
    const mois = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
      "août", "septembre", "octobre", "novembre", "décembre"];
    const m = parseInt(t.slice(5, 7), 10);
    const j = parseInt(t.slice(8, 10), 10);
    if (!m || !j) return t.slice(0, 10);
    return `${j === 1 ? "1er" : j} ${mois[m - 1]} ${t.slice(0, 4)}`;
  },

  async render(container) {
    // Repart proprement : un formulaire resté « ouvert » d'une visite
    // précédente bloquerait la mise à jour automatique pour toujours.
    this.state.formOuvert = false;
    this.state.edite = null;
    container.innerHTML = `
      <section class="animate-slide-up" style="max-width:1000px;margin:0 auto">
        <div class="flex items-start justify-between gap-3 flex-wrap mb-4">
          <div>
            <h1 class="text-xl font-bold">📣 Porte-Voix</h1>
            <p class="text-sm" style="color:hsl(var(--text-muted))">
              Tes clients suivis, leur part de voix dans les réponses des IA,
              et leurs rapports mensuels.</p>
          </div>
          <button id="pv-ajouter" class="btn btn-primary">➕ Ajouter un client</button>
        </div>

        <div class="card p-4 mb-4" id="pv-auto-card"></div>
        <div id="pv-msg" class="text-sm mb-3" style="display:none"></div>
        <div id="pv-form-zone"></div>
        <div id="pv-clients"></div>
        <div id="pv-inactifs" class="mt-4"></div>
      </section>`;

    container.querySelector("#pv-ajouter").onclick = () => this.ouvrirForm(null);
    const zone = container.querySelector("#pv-clients");
    zone.addEventListener("click", (e) => this._clic(e));
    container.querySelector("#pv-inactifs").addEventListener("click", (e) => this._clic(e));
    container.querySelector("#pv-auto-card").addEventListener("click", (e) => this._clic(e));
    container.querySelector("#pv-form-zone").addEventListener("click", (e) => this._clic(e));
    // Marque les zones de texte modifiées : un rafraîchissement ne doit
    // JAMAIS effacer ce que Jordan a tapé et pas encore enregistré.
    zone.addEventListener("input", (e) => {
      if (e.target && e.target.tagName === "TEXTAREA") e.target.dataset.modifie = "1";
    });

    // Suivi des mesures en cours : on repasse toutes les 8 s tant qu'une
    // mesure tourne (sans écraser une saisie en cours).
    if (typeof App !== "undefined" && typeof App.viewInterval === "function") {
      App.viewInterval(() => {
        const active = Object.values(this.state.mesures || {})
          .some((m) => m && m.etat === "mesure");
        if (active && !this._saisieEnCours()) this.refresh(true);
      }, 8000);
    }
    await this.refresh();
  },

  _saisieEnCours() {
    if (this.state.formOuvert) return true;
    const a = document.activeElement;
    return !!(a && (a.tagName === "TEXTAREA" || a.tagName === "INPUT"));
  },

  msg(texte, erreur) {
    const el = document.getElementById("pv-msg");
    if (!el) return;
    el.style.display = "block";
    el.style.color = erreur ? "hsl(var(--danger-text))" : "hsl(var(--success-text))";
    el.textContent = texte;
    clearTimeout(this._msgTimer);
    this._msgTimer = setTimeout(() => { el.style.display = "none"; }, 6000);
  },

  async refresh(discret) {
    let r = null;
    try { r = await App.api.pdv_etat({}); }
    catch (e) { console.error("[PorteVoix]", e); }
    if (!r || !r.ok) {
      if (!discret) this.msg((r && r.error) || "Impossible de charger Porte-Voix.", true);
      return;
    }
    this.state.clients = r.clients || [];
    this.state.auto = !!r.auto;
    this.state.mesures = r.mesures_en_cours || {};
    this.paintAuto();
    this.paintClients();
  },

  // ------------------------------------------------------ interrupteur

  paintAuto() {
    const el = document.getElementById("pv-auto-card");
    if (!el) return;
    const on = this.state.auto;
    el.innerHTML = `
      <div class="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <div class="font-semibold">Rapport mensuel automatique</div>
          <div class="text-sm" style="color:hsl(var(--text-muted))">
            Chaque mois (à partir du 2), l’app mesure chaque client, prépare son
            rapport et t’envoie une notification pour le relire.
            <b>Rien ne part jamais chez le client tout seul.</b></div>
        </div>
        <button data-act="auto" class="btn ${on ? "btn-primary" : "btn-secondary"}">
          ${on ? "🟢 Allumé" : "⚪ Coupé"}</button>
      </div>`;
  },

  // ---------------------------------------------------------- clients

  paintClients() {
    const zone = document.getElementById("pv-clients");
    const zoneOff = document.getElementById("pv-inactifs");
    if (!zone || !zoneOff) return;
    const actifs = this.state.clients.filter((c) => c.actif !== false);
    const inactifs = this.state.clients.filter((c) => c.actif === false);

    // Brouillons non enregistrés des rubriques : sauvegardés avant de
    // redessiner, restaurés après (sinon un rafraîchissement les efface).
    const brouillons = {};
    zone.querySelectorAll("textarea[data-modifie='1']").forEach((t) => {
      brouillons[t.id] = t.value;
    });

    zone.innerHTML = actifs.length
      ? actifs.map((c) => this.carte(c)).join("")
      : `<div class="card p-6 text-center" style="color:hsl(var(--text-muted))">
           Aucun client suivi pour l’instant. Le premier abonné Porte-Voix
           s’ajoute avec le bouton « Ajouter un client ».</div>`;

    Object.entries(brouillons).forEach(([id, valeur]) => {
      const t = document.getElementById(id);
      if (t) { t.value = valeur; t.dataset.modifie = "1"; }
    });

    zoneOff.innerHTML = inactifs.length
      ? `<details><summary class="text-sm cursor-pointer" style="color:hsl(var(--text-muted))">
           Clients sortis du suivi (${inactifs.length})</summary>
           <div class="mt-2">${inactifs.map((c) => `
             <div class="card p-3 mb-2 flex items-center justify-between gap-3 flex-wrap">
               <div><b>${this.esc(c.entreprise)}</b>
                 <span class="text-sm" style="color:hsl(var(--text-muted))">
                   — ${this.esc(c.metier || "")}, ${this.esc((c.villes || []).join(", "))}</span></div>
               <button data-act="reactiver" data-id="${this.esc(c.id)}"
                       class="btn btn-secondary">Reprendre le suivi</button>
             </div>`).join("")}</div></details>`
      : "";
  },

  carte(c) {
    const m = this.state.mesures[c.id] || {};
    const dm = c.derniere_mesure || null;
    const badges = [
      c.metier ? `<span class="pv-badge">${this.esc(c.metier)}</span>` : "",
      (c.villes || []).length ? `<span class="pv-badge">📍 ${this.esc(c.villes.join(", "))}</span>` : "",
      c.palier ? `<span class="pv-badge">💶 ${this.esc(c.palier)}</span>` : "",
      c.entree_le ? `<span class="pv-badge">entré le ${this.esc(this.dateFr(c.entree_le))}</span>` : "",
    ].filter(Boolean).join(" ");

    let mesureHtml = "";
    if (m.etat === "mesure") {
      mesureHtml = `<div class="text-sm mt-1" style="color:hsl(var(--info-text))">
        ⏳ Mesure en cours (quelques minutes)… la page se met à jour toute seule.</div>`;
    } else if (m.etat === "erreur") {
      mesureHtml = `<div class="text-sm mt-1" style="color:hsl(var(--danger-text))">
        La dernière mesure a échoué : ${this.esc(m.message || "raison inconnue")}</div>`;
    }

    let partHtml = `<span class="text-sm" style="color:hsl(var(--text-muted))">
      Pas encore de mesure.</span>`;
    if (dm) {
      let evo = "";
      if (dm.delta != null) {
        const d = Number(dm.delta);
        const fleche = Math.abs(d) < 2 ? "→" : (d > 0 ? "↗" : "↘");
        const texte = Math.abs(d) < 2 ? "stable"
          : `${d > 0 ? "+" : "−"}${this.fmt(Math.abs(d))} pts`;
        evo = `<span class="text-sm font-semibold">${fleche} ${texte}</span>`;
      }
      partHtml = `
        <span class="text-2xl font-extrabold" style="letter-spacing:-0.02em">
          ${this.fmt(dm.part)}&nbsp;%</span> ${evo}
        <span class="text-sm" style="color:hsl(var(--text-muted))">
          mesuré le ${this.esc(this.dateFr(dm.ts))} (${dm.nb_releves} relevé${dm.nb_releves > 1 ? "s" : ""})</span>`;
    }

    const alerteRubriques = !c.rubriques_a_jour
      ? `<div class="text-sm mb-2" style="color:hsl(var(--warning-text))">
           ⚠ Rubriques du mois à compléter avant le prochain rapport : le client
           doit toujours voir le travail fait et le plan suivant.</div>`
      : "";

    const rapports = (c.rapports || []).slice().reverse().map((r) => `
      <div class="flex items-center justify-between gap-2 flex-wrap py-1"
           style="border-top:1px solid hsl(var(--border))">
        <span class="text-sm">📄 ${this.esc(r.mois || (r.archive_ts || "").slice(0, 7))}
          — ${this.fmt(r.part)}&nbsp;%
          ${r.alertes ? `<span style="color:hsl(var(--warning-text))">⚠ à compléter</span>` : ""}</span>
        <span>
          <button data-act="voir" data-id="${this.esc(r.id)}" class="btn btn-secondary btn-xs">Voir</button>
          <button data-act="telecharger" data-id="${this.esc(r.id)}" class="btn btn-secondary btn-xs">Télécharger</button>
        </span>
      </div>`).join("");

    return `
      <div class="card p-4 mb-4">
        <div class="flex items-start justify-between gap-3 flex-wrap">
          <div>
            <div class="text-lg font-bold">${this.esc(c.entreprise)}</div>
            <div class="mt-1">${badges}</div>
          </div>
          <div class="flex gap-2 flex-wrap">
            <button data-act="rapport" data-id="${this.esc(c.id)}" class="btn btn-primary"
              ${m.etat === "mesure" ? "disabled" : ""}>📊 Préparer le rapport</button>
            <button data-act="modifier" data-id="${this.esc(c.id)}" class="btn btn-secondary">Modifier</button>
            <button data-act="sortir" data-id="${this.esc(c.id)}" class="btn btn-secondary">Sortir du suivi</button>
          </div>
        </div>
        <div class="mt-3">${partHtml}</div>
        ${mesureHtml}
        <div class="mt-3 grid gap-3 sm:grid-cols-2">
          <div>
            <div class="text-sm font-semibold mb-1">Ce qui a été fait ce mois-ci</div>
            <textarea id="pv-fait-${this.esc(c.id)}" rows="3" class="pv-ta"
              placeholder="Une ligne par action (ex. Page « courtier à Rennes » publiée)">${this.esc((c.fait || []).join("\n"))}</textarea>
          </div>
          <div>
            <div class="text-sm font-semibold mb-1">Ce qui vient le mois prochain</div>
            <textarea id="pv-avenir-${this.esc(c.id)}" rows="3" class="pv-ta"
              placeholder="Une ligne par action prévue">${this.esc((c.avenir || []).join("\n"))}</textarea>
          </div>
        </div>
        ${alerteRubriques}
        <button data-act="rubriques" data-id="${this.esc(c.id)}" class="btn btn-secondary btn-xs">
          Enregistrer les rubriques</button>
        ${rapports ? `<div class="mt-3">${rapports}</div>` : ""}
      </div>`;
  },

  // --------------------------------------------------------- actions

  async _clic(e) {
    const b = e.target.closest("[data-act]");
    if (!b) return;
    const act = b.dataset.act;
    const id = b.dataset.id || "";
    if (act === "auto") return this.toggleAuto();
    if (act === "voir") return this.ouvrirRapport(id, false);
    if (act === "telecharger") return this.ouvrirRapport(id, true);
    if (act === "rapport") return this.lancerRapport(id);
    if (act === "rubriques") return this.sauverRubriques(id);
    if (act === "modifier") {
      const c = this.state.clients.find((x) => x.id === id);
      return this.ouvrirForm(c || null);
    }
    if (act === "sortir") return this.sortirDuSuivi(id);
    if (act === "reactiver") return this.reactiver(id);
    if (act === "form-annuler") return this.fermerForm();
    if (act === "form-sauver") return this.sauverForm();
  },

  async toggleAuto() {
    const r = await App.api.pdv_auto_set({ enabled: !this.state.auto });
    if (r && r.ok) {
      this.state.auto = !!r.enabled;
      this.paintAuto();
      this.msg(r.message || "Réglage enregistré.");
    } else {
      this.msg((r && r.error) || "Impossible de changer le réglage.", true);
    }
  },

  async lancerRapport(id) {
    const r = await App.api.pdv_rapport_lancer({ id });
    if (r && r.ok) {
      this.msg("C’est parti : mesure en cours, le rapport sera prêt dans quelques minutes.");
      await this.refresh(true);
    } else {
      this.msg((r && r.error) || "Impossible de lancer la mesure.", true);
    }
  },

  async ouvrirRapport(id, telecharger) {
    const r = await App.api.pdv_rapport_html({ id });
    if (!r || !r.ok) {
      this.msg((r && r.error) || "Rapport introuvable.", true);
      return;
    }
    const blob = new Blob([r.html], { type: "text/html" });
    const url = URL.createObjectURL(blob);
    if (telecharger) {
      const a = document.createElement("a");
      a.href = url;
      a.download = r.filename || "rapport.html";
      document.body.appendChild(a);
      a.click();
      a.remove();
    } else {
      window.open(url, "_blank", "noopener");
    }
  },

  _lignes(texte) {
    return String(texte || "").split("\n").map((l) => l.trim()).filter(Boolean);
  },

  async sauverRubriques(id) {
    const fait = this._lignes((document.getElementById(`pv-fait-${id}`) || {}).value);
    const avenir = this._lignes((document.getElementById(`pv-avenir-${id}`) || {}).value);
    const r = await App.api.pdv_client_save({ id, fait, avenir });
    if (r && r.ok) {
      // Enregistré côté serveur : ces zones ne sont plus des brouillons.
      [`pv-fait-${id}`, `pv-avenir-${id}`].forEach((tid) => {
        const t = document.getElementById(tid);
        if (t) delete t.dataset.modifie;
      });
      this.msg("Rubriques enregistrées : le prochain rapport les reprendra.");
      await this.refresh(true);
    } else {
      this.msg((r && r.error) || "Enregistrement impossible.", true);
    }
  },

  async sortirDuSuivi(id) {
    const c = this.state.clients.find((x) => x.id === id);
    const nom = c ? c.entreprise : "ce client";
    if (!window.confirm(`Sortir ${nom} du suivi ? Sa fiche et son historique sont conservés.`)) return;
    const r = await App.api.pdv_client_desactiver({ id });
    if (r && r.ok) { this.msg(`${nom} est sorti du suivi.`); await this.refresh(true); }
    else this.msg((r && r.error) || "Impossible de sortir ce client.", true);
  },

  async reactiver(id) {
    const r = await App.api.pdv_client_save({ id, actif: true });
    if (r && r.ok) { this.msg("Client repris dans le suivi."); await this.refresh(true); }
    else this.msg((r && r.error) || "Reprise impossible.", true);
  },

  // ------------------------------------------------------- formulaire

  ouvrirForm(client) {
    this.state.formOuvert = true;
    this.state.edite = client ? client.id : null;
    const zone = document.getElementById("pv-form-zone");
    if (!zone) return;
    const c = client || {};
    zone.innerHTML = `
      <div class="card p-4 mb-4" id="pv-form">
        <div class="font-semibold mb-3">${client ? "Modifier " + this.esc(c.entreprise) : "Nouveau client suivi"}</div>
        <div class="grid gap-3 sm:grid-cols-2">
          <div>
            <label class="text-sm font-semibold">Entreprise *</label>
            <input id="pvf-entreprise" class="pv-in" value="${this.esc(c.entreprise || "")}" placeholder="Cabinet Durand">
          </div>
          <div>
            <label class="text-sm font-semibold">Métier *</label>
            <input id="pvf-metier" class="pv-in" value="${this.esc(c.metier || "")}" placeholder="courtier en assurance">
          </div>
          <div>
            <label class="text-sm font-semibold">Ville(s) *</label>
            <input id="pvf-villes" class="pv-in" value="${this.esc((c.villes || []).join(", "))}"
                   placeholder="Rennes (plusieurs : sépare par des virgules)">
          </div>
          <div>
            <label class="text-sm font-semibold">Abonnement</label>
            <input id="pvf-palier" class="pv-in" value="${this.esc(c.palier || "")}" placeholder="ex. 179 €/mois">
          </div>
          <div class="sm:col-span-2">
            <label class="text-sm font-semibold">Concurrents à suivre (3 au maximum)</label>
            <input id="pvf-concurrents" class="pv-in" value="${this.esc((c.concurrents || []).join(", "))}"
                   placeholder="Le Goff Assurances, Cabinet Petit (séparés par des virgules)">
          </div>
          <div class="sm:col-span-2">
            <label class="text-sm font-semibold">Questions personnalisées (optionnel)</label>
            <textarea id="pvf-questions" rows="3" class="pv-ta"
              placeholder="Une question par ligne. Vide = les questions habituelles du métier.">${this.esc((c.questions || []).join("\n"))}</textarea>
          </div>
        </div>
        <div class="mt-3 flex gap-2">
          <button data-act="form-sauver" class="btn btn-primary">${client ? "Enregistrer" : "Ajouter ce client"}</button>
          <button data-act="form-annuler" class="btn btn-secondary">Annuler</button>
        </div>
      </div>`;
    zone.scrollIntoView({ behavior: "smooth", block: "start" });
  },

  fermerForm() {
    this.state.formOuvert = false;
    this.state.edite = null;
    const zone = document.getElementById("pv-form-zone");
    if (zone) zone.innerHTML = "";
  },

  _virgules(texte) {
    return String(texte || "").split(",").map((v) => v.trim()).filter(Boolean);
  },

  async sauverForm() {
    const v = (id) => (document.getElementById(id) || {}).value || "";
    const payload = {
      entreprise: v("pvf-entreprise").trim(),
      metier: v("pvf-metier").trim(),
      villes: this._virgules(v("pvf-villes")),
      concurrents: this._virgules(v("pvf-concurrents")),
      questions: this._lignes(v("pvf-questions")),
      palier: v("pvf-palier").trim(),
    };
    if (this.state.edite) payload.id = this.state.edite;
    const r = await App.api.pdv_client_save(payload);
    if (r && r.ok) {
      this.fermerForm();
      this.msg(payload.id ? "Fiche mise à jour." : `${payload.entreprise} est suivi. Lance sa première mesure quand tu veux.`);
      await this.refresh(true);
    } else {
      this.msg((r && r.error) || "Enregistrement impossible.", true);
    }
  },
};

// Petits styles propres à l'écran (jetons du thème uniquement).
(() => {
  const css = `
    .pv-badge { display:inline-block; font-size:12px; font-weight:600;
      padding:2px 9px; border-radius:999px; margin-right:4px;
      background:hsl(var(--accent) / 0.12); color:hsl(var(--text-secondary)); }
    .pv-in, .pv-ta { width:100%; border:1px solid hsl(var(--border));
      border-radius:9px; padding:8px 11px; box-sizing:border-box;
      background:hsl(var(--surface)); color:hsl(var(--text)); font-size:14px; }
    .pv-in:focus, .pv-ta:focus { outline:none; border-color:hsl(var(--accent)); }
    .btn-xs { font-size:12px; padding:4px 10px; }
  `;
  const style = document.createElement("style");
  style.textContent = css;
  document.head.appendChild(style);
})();
