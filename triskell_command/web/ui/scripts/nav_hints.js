// Petites bulles d'aide à côté de chaque onglet de la sidebar.
// Un bouton "i" discret apparaît sur chaque .nav-item. Au clic, il ouvre
// une bulle qui résume en deux ou trois phrases ce que contient l'onglet.
// L'utilisateur peut éditer le texte de chaque bulle ; les modifs sont
// stockées dans localStorage et survivent au rafraîchissement.
(function () {
  'use strict';

  const STORAGE_KEY = 'triskell.nav_hints.overrides.v1';

  // Texte par défaut. Calé sur view_id. Pour la boîte mail, on distingue
  // les onglets via data-tab (inbound / sent / reply).
  const DEFAULT_HINTS = {
    morning: "Ton tableau de bord du jour. Tu y vois l’heure, la mission prioritaire, 4 grands chiffres clés sur 7 jours, les relances LinkedIn à faire et les alertes. Boutons rapides pour composer un mail, ouvrir Brain, appeler Claude ou lancer le mode Concentration.",
    'mails:inbound': "Boîte de réception : tous les mails entrants captés par l’app. Pour l’instant ce sont surtout les réponses de prospects (le reste arrivera plus tard).",
    'mails:sent': "Tous les mails envoyés depuis l’app : prospection, suivi après-vente, bienvenue client, notifications internes. Filtrable par adresse expéditrice.",
    'mails:reply': "Les réponses de prospects à tes mails de prospection, déjà rangées par l’IA (intéressé, pas maintenant, refus, désinscription, à trier). Tu réponds directement depuis la liste.",
    brain: "Boîte à idées partagée avec Thomas. Tu tapes une note, Claude la range automatiquement (catégorie, tags, rappel) et te re-pingue au bon moment dans l’app.",
    clients_master: "La liste de tes clients — uniquement les gens qui ont acheté au moins une fois chez Triskell. Chaque fiche montre son historique (factures, mails échangés, projets livrés).",
    autopilot: "Étape 2 — la machine qui ÉCRIT et ENVOIE les mails de prospection toute seule. Elle pioche UNIQUEMENT dans « Tous les prospects » (elle ne cherche jamais sur internet), utilise tes modèles de mails tels quels, fait relire par une 2e IA, et respecte un plafond par jour. Chaque maillon a son interrupteur Auto/Manuel.",
    convoy: "Étape 2 (variante) — pour envoyer une campagne sur une LISTE PRÉCISE : tu glisses un PDF, Word, Excel ou image avec les contacts, l’app les extrait, tu choisis l’offre, l’IA prépare un mail par personne, tu valides et tu lances l’envoi.",
    drafts: "Étape 3 — les mails préparés par l’app qui attendent ton feu vert. Tu peux corriger le texte directement, puis approuver ou rejeter en un clic. Inclut aussi un bouton pour vider les brouillons vides.",
    replies: "Étape 4 — les réponses de prospects, triées par l’IA en 5 catégories (intéressé, pas maintenant, refus, désinscription, à trier). Bouton « Vérifier maintenant » pour forcer un coup d’œil dans ta boîte mail sans attendre les 5 minutes habituelles.",
    prospects_crm: "LA base centrale. Tout ce que les outils de recherche trouvent (Obélisk, Chasseur, Chasseur Créateur, Prospecteur Google, Argus) atterrit ici, dédoublonné. C’est ici que l’Auto-pilote vient piocher pour écrire et envoyer. Filtres par plateforme, statut, présence d’email ; clic sur une ligne pour la fiche complète.",
    obelisk: "Étape 1 — trouver des CRÉATEURS (YouTube, Twitch, Instagram, TikTok…). Tu lances une recherche par niche, l’app récupère les profils et leurs mails en arrière-plan, et les range directement dans « Tous les prospects ».",
    chasseur: "Étape 1 — trouver des PME FRANÇAISES. Tu choisis un métier (préréglage ou code NAF), une zone (département ou code postal). L’app interroge le registre officiel (data.gouv), retrouve le site de chaque boîte et attrape le mail public. Ensuite : bouton « Auto-Pilote » pour tout pousser dans la base, ou export CSV pour Le Convoi.",
    chasseur_createurs: "Étape 1 — chasse PONCTUELLE de créateurs (YouTube, Instagram, Facebook) par niche et fourchette d’abonnés. À la fin : « Ajouter à mes prospects » pour pousser ceux qui ont un mail dans la base, ou export Excel/CSV.",
    prospecteur_google: "Étape 1 — trouver des COMMERCES LOCAUX via Google Maps (métier + ville). Pratique pour repérer ceux qui n’ont pas de site. À la fin : « Ajouter à mes prospects » ou export Excel/CSV.",
    argus: "Étape 1 — récupérer des MAILS PROS en masse par secteur et ville (Pages Jaunes, Europages, OpenStreetMap, sites web). À la fin : bouton pour pousser le butin dans « Tous les prospects », ou export Excel.",
    eclaireur: "Étape 1 bis — tu décris ta cible, l’app cherche des prospects ET complète leurs fiches (mails, téléphones). Aucun envoi de mail ici — c’est uniquement la phase recherche/enrichissement du pipeline.",
    clients: "Tes projets clients en cours, en kanban 4 colonnes : Briefing, En cours, Livré, Clôturé. Tu fais glisser les cartes, tu édites, tu déclenches la livraison automatique (mail de bienvenue + kit produit) quand un projet est prêt.",
    revenue: "Tous tes encaissements regroupés (Stripe + AppSumo + paiements manuels). Tu vois le total du mois en cours comparé au mois précédent, les 7 et 30 derniers jours, le top clients du mois, la répartition par produit et par source, et les prévisions.",
    funnel: "Ton entonnoir de conversion étape par étape : prospects, mails envoyés, réponses, intéressés, gagnés. Filtrable par période (7/30/90 jours ou tout) et par type de prospect (créateurs ou B2B local). Tu vois où ça coince.",
    phare: "Suivi SEO de tes sites (internes et clients). Chaque carte montre la santé du site, les visites du mois, et les améliorations préparées par les robots qui attendent ton feu vert. Tu valides ou tu refuses en un clic.",
    lagriffe: "Pipeline visuel des demandes de sites Lagriffe Studio, étape par étape jusqu’à la mise en ligne. Comprend une étape supplémentaire « À valider (final) » où tu donnes ton feu vert humain sur le site final avant l’envoi du mail au client.",
    rankus: "Pipeline visuel des demandes SEO RankUs Studio, étape par étape. Chaque demande montre son étage dans le pipeline et l’historique complet des actions menées.",
    wow: "Pipeline visuel des demandes Studio WoW, étape par étape. Chaque demande client montre son étage et l’historique pas à pas, de la prise de brief jusqu’à la mise en ligne.",
    pixelpros: "Kanban des sites Pixel Pros à 4 colonnes : formulaire reçu, payé à construire, en construction, en ligne. Clic sur une carte pour la fiche détaillée et les actions (relancer un mail, marquer en échec, déclencher la construction). Une commande payée qui traîne plus de 6h est marquée urgente.",
    'pixelpros-affiliates': "Backoffice du programme d’affiliation Pixel Pros (20 % sur 12 mois). Compteurs (actifs, ventes en attente, à verser, déjà versé), liste des affiliés à payer ce mois-ci (≥ 50 €), tableau cherchable de tous les affiliés avec fiche détaillée au clic.",
    catalogue: "Le catalogue central des produits de l’écosystème Triskell (sites, outils, services). Chaque tuile ouvre une fiche avec pitch, description longue, fonctionnalités, prix. C’est ce catalogue qui sert quand tu choisis une offre dans Le Convoi ou un composeur de mail.",
    mail_templates: "Éditeur de tous les modèles de mails automatiques (confirmations, relances, livraisons, prospection). Tu modifies sujet, expéditeur et corps HTML sans toucher au code. Si tu désactives un modèle, l’app retombe sur sa version par défaut, donc rien ne casse.",
    health: "État de tes outils automatiques et de la délivrabilité de tes envois. Carte par robot avec son dernier passage, alertes sur les mails bloqués ou bounces, taux de réponse sur 24h et 7 jours. Se rafraîchit tout seul toutes les 15 secondes.",
    tutorial: "Visite guidée complète de l’app sous forme de modale avec étapes et barre de progression. Te montre tout le parcours : prospection, rédaction IA, envoi, tri des réponses, suivi client, livraison auto, mesures. À ouvrir au premier lancement ou pour réviser.",
    config: "Tous les réglages, rangés par onglets : compte, apparence, mails (comptes et signatures), IA, intégrations (Stripe, Phantombuster, tracker), automatisations (passage prospect → client, livraison) et système (sauvegardes, mode démo, visite guidée).",
    eliks: "Notre service de croissance multi-réseaux. On prend en main les comptes Instagram, TikTok et LinkedIn d’un client pour les faire grossir (contenu, posts, interactions). C’est le « bras armé » côté présence en ligne.",
  };

  // ---- Persistance des modifs utilisateur ----
  function loadOverrides() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      return raw ? JSON.parse(raw) : {};
    } catch (_) { return {}; }
  }
  function saveOverrides(obj) {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(obj)); } catch (_) {}
  }
  function getHint(key) {
    const overrides = loadOverrides();
    if (Object.prototype.hasOwnProperty.call(overrides, key)) return overrides[key];
    return DEFAULT_HINTS[key];
  }
  function setHint(key, text) {
    const overrides = loadOverrides();
    if (text == null || text === DEFAULT_HINTS[key]) {
      delete overrides[key];
    } else {
      overrides[key] = text;
    }
    saveOverrides(overrides);
  }

  // ---- État du popover unique ----
  let popoverEl = null;
  let activeBtn = null;
  let activeKey = null;
  let editing = false;

  function hintKey(navBtn) {
    const view = navBtn.dataset.view;
    const tab = navBtn.dataset.tab;
    if (tab) {
      const composite = `${view}:${tab}`;
      if (DEFAULT_HINTS[composite]) return composite;
    }
    return view;
  }

  function closePopover() {
    if (popoverEl && popoverEl.parentNode) popoverEl.parentNode.removeChild(popoverEl);
    popoverEl = null;
    if (activeBtn) activeBtn.setAttribute('aria-expanded', 'false');
    activeBtn = null;
    activeKey = null;
    editing = false;
  }

  function repositionPopover() {
    if (!popoverEl || !activeBtn) return;
    const rect = activeBtn.getBoundingClientRect();
    // Force un layout pour mesurer la nouvelle taille
    popoverEl.style.left = '-9999px';
    popoverEl.style.top = '0px';
    const popRect = popoverEl.getBoundingClientRect();
    let left = rect.right + 10;
    let top = rect.top + rect.height / 2 - popRect.height / 2;
    popoverEl.classList.remove('nav-hint-popover--left');
    if (left + popRect.width > window.innerWidth - 8) {
      left = rect.left - popRect.width - 10;
      popoverEl.classList.add('nav-hint-popover--left');
    }
    const margin = 8;
    if (top < margin) top = margin;
    if (top + popRect.height > window.innerHeight - margin) {
      top = window.innerHeight - popRect.height - margin;
    }
    popoverEl.style.left = `${Math.round(left)}px`;
    popoverEl.style.top = `${Math.round(top)}px`;
  }

  // ---- Rendu : mode lecture ----
  function renderRead() {
    if (!popoverEl) return;
    editing = false;
    const text = getHint(activeKey);
    const isCustom = Object.prototype.hasOwnProperty.call(loadOverrides(), activeKey);
    popoverEl.innerHTML = `
      <div class="nav-hint-arrow" aria-hidden="true"></div>
      <p class="nav-hint-text"></p>
      <div class="nav-hint-actions">
        <button type="button" class="nav-hint-action" data-act="edit" title="Modifier ce texte" aria-label="Modifier ce texte">
          <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4z"/></svg>
          <span>Modifier</span>
        </button>
        ${isCustom ? `
        <button type="button" class="nav-hint-action nav-hint-action--ghost" data-act="reset" title="Revenir au texte d'origine">
          <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/></svg>
          <span>Défaut</span>
        </button>` : ''}
      </div>
    `;
    popoverEl.querySelector('.nav-hint-text').textContent = text;
    popoverEl.querySelector('[data-act="edit"]').addEventListener('click', (e) => {
      e.stopPropagation();
      renderEdit();
    });
    const resetBtn = popoverEl.querySelector('[data-act="reset"]');
    if (resetBtn) {
      resetBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        setHint(activeKey, null);
        renderRead();
        repositionPopover();
      });
    }
    repositionPopover();
  }

  // ---- Rendu : mode édition ----
  function renderEdit() {
    if (!popoverEl) return;
    editing = true;
    const text = getHint(activeKey);
    popoverEl.innerHTML = `
      <div class="nav-hint-arrow" aria-hidden="true"></div>
      <textarea class="nav-hint-textarea" rows="5" spellcheck="true"></textarea>
      <div class="nav-hint-actions">
        <button type="button" class="nav-hint-action nav-hint-action--ghost" data-act="cancel">Annuler</button>
        <button type="button" class="nav-hint-action nav-hint-action--primary" data-act="save">Enregistrer</button>
      </div>
    `;
    const ta = popoverEl.querySelector('.nav-hint-textarea');
    ta.value = text || '';
    setTimeout(() => { ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length); }, 0);
    ta.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        save();
      } else if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        renderRead();
      }
    });
    ta.addEventListener('click', (e) => e.stopPropagation());
    popoverEl.querySelector('[data-act="cancel"]').addEventListener('click', (e) => {
      e.stopPropagation();
      renderRead();
    });
    popoverEl.querySelector('[data-act="save"]').addEventListener('click', (e) => {
      e.stopPropagation();
      save();
    });
    function save() {
      const v = ta.value.trim();
      setHint(activeKey, v || null);
      renderRead();
      repositionPopover();
    }
    repositionPopover();
  }

  function openPopover(btn, key) {
    closePopover();
    popoverEl = document.createElement('div');
    popoverEl.className = 'nav-hint-popover';
    popoverEl.setAttribute('role', 'tooltip');
    popoverEl.addEventListener('click', (e) => e.stopPropagation());
    document.body.appendChild(popoverEl);
    activeBtn = btn;
    activeKey = key;
    btn.setAttribute('aria-expanded', 'true');
    renderRead();
  }

  function makeHintButton(navBtn, key) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'nav-hint-btn';
    btn.setAttribute('aria-label', "À quoi sert cet onglet ?");
    btn.setAttribute('aria-expanded', 'false');
    btn.setAttribute('title', "À quoi sert cet onglet ?");
    btn.innerHTML = `
      <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor"
           stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <circle cx="12" cy="12" r="9"/>
        <line x1="12" y1="11" x2="12" y2="16"/>
        <circle cx="12" cy="8" r="0.6" fill="currentColor"/>
      </svg>
    `;
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      e.preventDefault();
      if (activeBtn === btn) {
        closePopover();
      } else {
        openPopover(btn, key);
      }
    });
    btn.addEventListener('mousedown', (e) => e.stopPropagation());
    return btn;
  }

  function attachAll() {
    const items = document.querySelectorAll('.nav-item[data-view]');
    items.forEach((nav) => {
      if (nav.dataset.hintAttached === '1') return;
      const key = hintKey(nav);
      if (!DEFAULT_HINTS[key]) return;
      const btn = makeHintButton(nav, key);
      const badge = nav.querySelector('.nav-item-badge');
      if (badge) {
        nav.insertBefore(btn, badge);
      } else {
        nav.appendChild(btn);
      }
      nav.dataset.hintAttached = '1';
    });
  }

  // Fermer quand on clique ailleurs (sauf en édition pour éviter les pertes
  // accidentelles si l'utilisateur clique dans le textarea, qui stop déjà).
  document.addEventListener('click', (e) => {
    if (!popoverEl) return;
    if (e.target === activeBtn || (activeBtn && activeBtn.contains(e.target))) return;
    if (popoverEl.contains(e.target)) return;
    if (editing) return; // on garde la bulle ouverte pendant l'édition
    closePopover();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !editing) closePopover();
  });
  window.addEventListener('resize', () => { if (!editing) closePopover(); else repositionPopover(); });
  window.addEventListener('scroll', () => { if (!editing) closePopover(); }, true);

  function init() {
    attachAll();
    setTimeout(attachAll, 300);
    setTimeout(attachAll, 1200);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
