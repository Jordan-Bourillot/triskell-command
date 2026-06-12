// Petites bulles d'aide à côté de chaque onglet de la sidebar.
// Un bouton "i" discret est posé PAR-DESSUS chaque .nav-item (en voisin
// positionné — pas imbriqué dans le <button> du menu, ce serait du HTML
// invalide). Au clic, il ouvre une bulle qui résume en deux ou trois
// phrases ce que contient l'onglet. L'utilisateur peut éditer le texte de
// chaque bulle ; les modifs sont stockées dans localStorage.
(function () {
  'use strict';

  const STORAGE_KEY = 'triskell.nav_hints.overrides.v1';

  // Texte par défaut. Calé sur view_id. Pour la boîte mail, on distingue
  // les onglets via data-tab (inbound / sent / reply).
  const DEFAULT_HINTS = {
    morning: "Ton tableau de bord du jour. Tu y vois l’heure, la mission prioritaire, 4 grands chiffres clés sur 7 jours, les relances LinkedIn à faire et les alertes. Boutons rapides pour rédiger un mail, prendre une note rapide, ouvrir Perceval (ton copilote, à l’écrit ou à la voix) ou lancer le mode Concentration.",
    mails: "Rédiger un mail : le composeur s’ouvre directement. Tu écris (ou tu pars d’un modèle), tu choisis l’adresse d’envoi, les pièces jointes et la signature, puis tu envoies tout de suite ou tu programmes pour plus tard.",
    'mails:inbound': "Boîte de réception : tous les mails entrants captés par l’app. Pour l’instant ce sont surtout les réponses de prospects (le reste arrivera plus tard).",
    'mails:sent': "Tous les mails envoyés depuis l’app : prospection, suivi après-vente, bienvenue client, notifications internes. Filtrable par adresse expéditrice.",
    'mail_templates:transactionnel': "Les mails automatiques envoyés à tes CLIENTS après un achat : bienvenue, accès aux livrables, relances de suivi (J+3, J+14…). Tu règles leur texte ici une fois pour toutes — l’app les envoie ensuite au bon moment, toute seule.",
    'mail_templates:prospection': "Les mails types que l’Auto-pilote envoie aux PROSPECTS pour les démarcher. Il les utilise tels quels : l’IA remplit juste les trous (prénom, entreprise…), elle ne réécrit rien. Le champ « Envoyé depuis » peut imposer l’adresse d’expédition d’un modèle.",
    brain: "Boîte à idées partagée avec Thomas. Tu tapes une note, Claude la range automatiquement (catégorie, tags, rappel) et te re-pingue au bon moment dans l’app.",
    clients_master: "La liste de tes clients — uniquement les gens qui ont acheté au moins une fois chez Triskell. Chaque fiche montre son historique (factures, mails échangés, projets livrés).",
    autopilot: "Étape 2 — la machine qui ÉCRIT et ENVOIE les mails de prospection toute seule. Elle pioche UNIQUEMENT dans « Tous les prospects » (elle ne cherche jamais sur internet), utilise tes modèles de mails tels quels, fait relire par une 2e IA, et respecte un plafond par jour. Chaque maillon a son interrupteur Auto/Manuel.",
    convoy: "Étape 2 (variante) — pour envoyer une campagne sur une LISTE PRÉCISE : tu glisses un PDF, Word, Excel ou image avec les contacts, l’app les extrait, tu choisis l’offre, l’IA prépare un mail par personne, tu valides et tu lances l’envoi.",
    drafts: "Étape 3 — les mails préparés par l’app qui attendent ton feu vert. Tu peux corriger le texte directement, puis approuver ou rejeter en un clic. Inclut aussi un bouton pour vider les brouillons vides.",
    replies: "Étape 4 — les réponses de prospects, triées par l’IA en 5 catégories (intéressé, pas maintenant, refus, désinscription, à trier). Bouton « Vérifier maintenant » pour forcer un coup d’œil dans ta boîte mail sans attendre les 5 minutes habituelles.",
    prospection: "LE chemin court : tu choisis qui démarcher (PME, commerces locaux ou créateurs), tu cliques Lancer, et TOUTE la chaîne s’enchaîne automatiquement — recherche, versement dans la base sans doublon, rédaction et envoi par l’Auto-pilote, réponses triées. Les outils en dessous restent là pour les usages pointus.",
    prospects_crm: "LA base centrale. Tout ce que les outils de recherche trouvent (Obélisk, Le Chasseur, Prospecteur Google…) atterrit ici, sans doublon : les fiches identiques fusionnent. C’est ici que l’Auto-pilote vient piocher pour écrire et envoyer. Filtres par plateforme, statut, présence d’email ; clic sur une ligne pour la fiche complète.",
    obelisk: "Étape 1 — trouver des CRÉATEURS (YouTube, Twitch, Instagram, TikTok…). Tu lances une recherche par niche, l’app récupère les profils et leurs mails en arrière-plan, et les range directement dans « Tous les prospects ».",
    chasseur: "Étape 1 — trouver des PME FRANÇAISES (petites et moyennes entreprises). Tu choisis un métier (préréglage ou code NAF, le code métier officiel), une zone (département ou code postal). L’app interroge le registre officiel (data.gouv), retrouve le site de chaque boîte et attrape le mail public. Ensuite : bouton « Auto-Pilote » pour tout pousser dans la base, ou export fichier (Excel/CSV) pour Le Convoi.",
    chasseur_createurs: "Étape 1 — chasse PONCTUELLE de créateurs (YouTube, Instagram, Facebook) par niche et fourchette d’abonnés. À la fin : « Ajouter à mes prospects » pour pousser ceux qui ont un mail dans la base, ou export Excel/CSV.",
    prospecteur_google: "Étape 1 — trouver des COMMERCES LOCAUX via Google Maps (métier + ville). Pratique pour repérer ceux qui n’ont pas de site. À la fin : « Ajouter à mes prospects » ou export Excel/CSV.",
    argus: "Étape 1 — récupérer des MAILS PROS en masse par secteur et ville (Pages Jaunes, Europages, OpenStreetMap, sites web). À la fin : bouton pour pousser le butin dans « Tous les prospects », ou export Excel.",
    eclaireur: "Complète les fiches de tes prospects : l’app visite leurs sites et retrouve les mails et téléphones qui manquent. Peut aussi chercher de nouveaux prospects. Aucun envoi de mail ici.",
    clients: "Tes projets clients en cours, dans un tableau à 4 colonnes : Briefing (on attend les infos), En cours (on travaille), Livré, Clôturé. Tu fais avancer les cartes, tu édites, tu déclenches la livraison (mail de bienvenue + kit produit) quand un projet est prêt.",
    revenue: "Tous tes encaissements regroupés (Stripe + AppSumo + paiements manuels). Tu vois le total du mois en cours comparé au mois précédent, les 7 et 30 derniers jours, le top clients du mois, la répartition par produit et par source, et les prévisions.",
    funnel: "Combien de prospects deviennent des clients, étape par étape : prospects en base, mails envoyés, réponses, intéressés, gagnés. Filtrable par période (7/30/90 jours ou tout) et par type de prospect. Tu vois tout de suite où ça coince.",
    phare: "La santé Google de tes sites et des sites clients (le SEO : être bien placé dans les résultats de recherche). Chaque carte montre l’état du site, ses visites du mois, et les améliorations préparées par les robots — qui attendent TON feu vert. Tu valides ou tu refuses en un clic.",
    geo: "Le GEO travaille à ce que les IA (ChatGPT, Perplexity…) citent tes sites dans leurs réponses — comme le référencement Google, mais pour les IA. Il pose des questions tests, surveille si tes sites ressortent, et prépare des contenus pour s’améliorer. Son auto-pilote s’allume depuis cet écran.",
    lagriffe: "Le suivi des demandes de sites Lagriffe Studio, étape par étape jusqu’à la mise en ligne. Comprend une étape « À valider (final) » où tu donnes ton feu vert humain sur le site fini avant l’envoi du mail au client.",
    rankus: "Le suivi des demandes RankUs Studio (référencement Google vendu aux clients), étape par étape. Chaque demande montre où elle en est et l’historique complet des actions menées.",
    wow: "Le suivi des demandes clients Studio WoW, étape par étape, de la prise de brief jusqu’à la mise en ligne. Chaque demande montre où elle en est et l’historique pas à pas.",
    pixelpros: "Le suivi des commandes de sites Pixel Pros, en 4 colonnes : formulaire reçu, payé à construire, en construction, en ligne. Clic sur une carte pour la fiche détaillée et les actions (relancer un mail, marquer en échec, déclencher la construction). Une commande payée qui traîne plus de 6h est marquée urgente.",
    'pixelpros-affiliates': "La gestion du programme de parrainage Pixel Pros : un affilié touche 20 % des ventes qu’il apporte, pendant 12 mois. Compteurs (actifs, ventes en attente, à verser, déjà versé), liste de qui payer ce mois-ci (≥ 50 €), et fiche détaillée de chaque affilié au clic.",
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
        <span class="nav-hint-kbdtip">Ctrl+Entrée pour enregistrer</span>
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
    // role=dialog (pas tooltip) : la bulle contient des boutons d'action.
    popoverEl.setAttribute('role', 'dialog');
    popoverEl.setAttribute('aria-label', 'À quoi sert cet onglet ?');
    popoverEl.addEventListener('click', (e) => e.stopPropagation());
    document.body.appendChild(popoverEl);
    activeBtn = btn;
    activeKey = key;
    btn.setAttribute('aria-expanded', 'true');
    renderRead();
  }

  function makeHintButton(navBtn, key) {
    // Un <span role="button"> et PAS un <button> : il vit en voisin de
    // l'onglet (un bouton dans un bouton est du HTML invalide qui casse
    // le focus clavier).
    const btn = document.createElement('span');
    btn.className = 'nav-hint-btn';
    btn.setAttribute('role', 'button');
    btn.setAttribute('tabindex', '0');
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
    const toggle = (e) => {
      e.stopPropagation();
      e.preventDefault();
      if (activeBtn === btn) {
        closePopover();
      } else {
        openPopover(btn, key);
      }
    };
    btn.addEventListener('click', toggle);
    btn.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') toggle(e);
    });
    btn.addEventListener('mousedown', (e) => e.stopPropagation());
    return btn;
  }

  // Styles propres au mode « voisin positionné » (main.css garde le reste).
  function injectStyles() {
    if (document.getElementById('nav-hints-styles')) return;
    const s = document.createElement('style');
    s.id = 'nav-hints-styles';
    s.textContent = `
      .nav-hint-wrap { position: relative; }
      /* On réserve la place du « i » à droite de l'onglet (24px + marge) */
      .nav-hint-wrap > .nav-item { width: 100%; padding-right: 38px; }
      .nav-hint-wrap > .nav-hint-btn {
        position: absolute;
        right: 8px;
        top: 50%;
        transform: translateY(-50%);
        margin-left: 0;
      }
      /* Le survol de l'onglet révèle le « i » (l'ancienne règle
         .nav-item:hover .nav-hint-btn ne matche plus un voisin). */
      .nav-hint-wrap:hover > .nav-hint-btn { opacity: 0.9; }
      .nav-hint-wrap > .nav-hint-btn:focus-visible {
        opacity: 1;
        outline: 2px solid hsl(var(--accent));
        outline-offset: 1px;
      }
      .nav-hint-kbdtip {
        margin-right: auto;
        align-self: center;
        font-size: 11px;
        color: hsl(var(--text-muted));
      }
    `;
    document.head.appendChild(s);
  }

  function attachAll() {
    const items = document.querySelectorAll('.nav-item[data-view]');
    items.forEach((nav) => {
      if (nav.dataset.hintAttached === '1') return;
      const key = hintKey(nav);
      if (!DEFAULT_HINTS[key]) return;
      if (!nav.parentNode) return;
      const btn = makeHintButton(nav, key);
      // L'onglet est enveloppé dans un conteneur relatif, et le « i » posé
      // par-dessus en voisin absolu. (sidebar_collapse.js connaît
      // .nav-hint-wrap et replie ces conteneurs avec leur section.)
      const wrap = document.createElement('div');
      wrap.className = 'nav-hint-wrap';
      nav.parentNode.insertBefore(wrap, nav);
      wrap.appendChild(nav);
      wrap.appendChild(btn);
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
    injectStyles();
    attachAll();
    // Accrochage par OBSERVATION du menu (avant : deux rendez-vous fixes à
    // 300 ms et 1,2 s — un onglet ajouté plus tard restait sans bulle).
    // attachAll est idempotent (drapeau hintAttached), donc l'observateur
    // peut le rappeler sans risque, y compris sur nos propres mutations.
    const sidebar = document.getElementById('sidebar') || document.body;
    let scheduled = false;
    const mo = new MutationObserver(() => {
      if (scheduled) return;
      scheduled = true;
      requestAnimationFrame(() => {
        scheduled = false;
        attachAll();
      });
    });
    mo.observe(sidebar, { childList: true, subtree: true });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
