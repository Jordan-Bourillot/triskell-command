// Petites bulles d'aide à côté de chaque onglet de la sidebar.
// Un bouton "i" discret apparaît sur chaque .nav-item. Au clic, il ouvre
// une bulle qui résume en deux ou trois phrases ce que contient l'onglet.
(function () {
  'use strict';

  // Le résumé est calé sur view_id. Pour la boîte mail, on distingue
  // les onglets via data-tab (inbound / sent / reply).
  const HINTS = {
    morning: "Ton tableau de bord du matin. Tu y vois l'essentiel : tes objectifs, l'humeur du business, ce qu'il y a à faire aujourd'hui.",
    'mails:inbound': "Tous les mails qui arrivent dans tes adresses Triskell. C'est ta boîte de réception unifiée, comme un seul Gmail pour toutes tes boîtes pro.",
    'mails:sent': "L'historique des mails que tu as envoyés. Pratique pour retrouver un échange avec un prospect ou vérifier qu'un message est bien parti.",
    'mails:reply': "Le tri des réponses reçues à tes campagnes de prospection. L'IA les classe par intention : intéressé, à relancer, refus, etc.",
    brain: "Ta boîte à idées personnelle. Tu y notes en vrac tes pensées, tes idées de site, tes phrases qui claquent, et l'app les retrouve quand tu en as besoin.",
    clients_master: "L'annuaire complet de tes contacts (prospects et clients). Une fiche par personne, avec tout l'historique en un coup d'œil.",
    autopilot: "L'app prospecte toute seule pendant que tu fais autre chose. Tu lui dis qui cibler, elle envoie les mails, gère les réponses et te prévient quand un humain doit prendre le relais.",
    convoy: "Pour importer une liste de prospects d'un coup (Excel, CSV…). L'app les nettoie, les enrichit et les prépare pour la prospection.",
    drafts: "Les mails que l'IA a préparés pour toi mais que tu dois valider avant envoi. Tu lis, tu corriges si besoin, tu envoies.",
    replies: "Toutes les réponses qui demandent que tu interviennes. C'est ta pile de \"à traiter\" pour rester réactif sans rien rater.",
    prospects_crm: "La liste complète de tes prospects en cours. Tu peux filtrer, segmenter, voir où chacun en est dans ton tunnel de vente.",
    obelisk: "Le moteur qui repère automatiquement de nouveaux prospects qui matchent ton ciblage. Il tourne en fond et te propose des fiches à valider.",
    chasseur: "L'outil pour partir à la pêche aux prospects toi-même. Tu cherches par secteur, ville, taille d'entreprise, et tu remplis ton vivier.",
    eclaireur: "Recherche fine sur un prospect précis : son site, ses réseaux, ce qui cloche chez lui. Idéal pour préparer une approche personnalisée.",
    clients: "Tes projets clients en cours. Pour chaque client, tu vois où on en est, ce qu'il reste à livrer, ce qu'il a payé.",
    revenue: "Tes revenus dans le temps. Mois par mois, par produit, par client : tu sais combien tu rentres et d'où ça vient.",
    funnel: "Ton tunnel de conversion en chiffres : combien de prospects contactés, combien ont répondu, combien sont devenus clients.",
    phare: "Ton agence SEO interne. Tu y suis le positionnement de tes sites sur Google et les actions à mener pour grimper dans les résultats.",
    lagriffe: "Le pipeline de fabrication des sites Lagriffe. Tu vois chaque commande étape par étape : briefing, production, livraison.",
    rankus: "Le pipeline RankUs (offre SEO). Suivi des audits, des optimisations, des livrables.",
    wow: "Le pipeline du Studio WoW. Chaque projet WoW de la commande à la mise en ligne, avec son statut.",
    pixelpros: "Le pipeline Pixel Pros, le service où le site se génère tout seul après paiement. Tu vois chaque site en cours de fabrication et son statut.",
    'pixelpros-affiliates': "Le programme d'affiliation Pixel Pros. Tu y suis les affiliés, leurs ventes et les commissions à reverser.",
    catalogue: "Le catalogue de tout ce que vend Triskell Studio : sites, services, abonnements. Tu gères les prix, les descriptions, les bundles.",
    mail_templates: "Tes modèles de mail réutilisables. Tu écris un mail une fois, tu le ranges ici, tu le réutilises à l'infini.",
    health: "L'état de santé de l'app : serveur, base de données, services externes. Si quelque chose cloche, c'est ici qu'on voit la lampe rouge.",
    tutorial: "Le tour guidé de l'app pour (re)découvrir ses fonctions. À montrer à quelqu'un qui débarque, ou à toi quand tu cherches une feature.",
    config: "Les réglages de l'app. Ton profil, tes adresses mail connectées, les préférences, les options avancées.",
  };

  let popoverEl = null;
  let activeBtn = null;

  function hintKey(navBtn) {
    const view = navBtn.dataset.view;
    const tab = navBtn.dataset.tab;
    if (tab) {
      const composite = `${view}:${tab}`;
      if (HINTS[composite]) return composite;
    }
    return view;
  }

  function closePopover() {
    if (popoverEl && popoverEl.parentNode) popoverEl.parentNode.removeChild(popoverEl);
    popoverEl = null;
    if (activeBtn) activeBtn.setAttribute('aria-expanded', 'false');
    activeBtn = null;
  }

  function openPopover(btn, text) {
    closePopover();
    popoverEl = document.createElement('div');
    popoverEl.className = 'nav-hint-popover';
    popoverEl.setAttribute('role', 'tooltip');
    popoverEl.innerHTML = `
      <div class="nav-hint-arrow" aria-hidden="true"></div>
      <p class="nav-hint-text"></p>
    `;
    popoverEl.querySelector('.nav-hint-text').textContent = text;
    document.body.appendChild(popoverEl);

    // Position : à droite du bouton, centré verticalement.
    const rect = btn.getBoundingClientRect();
    const popRect = popoverEl.getBoundingClientRect();
    let left = rect.right + 10;
    let top = rect.top + rect.height / 2 - popRect.height / 2;

    // Si on déborde à droite, on bascule à gauche du sidebar.
    if (left + popRect.width > window.innerWidth - 8) {
      left = rect.left - popRect.width - 10;
      popoverEl.classList.add('nav-hint-popover--left');
    }
    // Clamp vertical
    const margin = 8;
    if (top < margin) top = margin;
    if (top + popRect.height > window.innerHeight - margin) {
      top = window.innerHeight - popRect.height - margin;
    }
    popoverEl.style.left = `${Math.round(left)}px`;
    popoverEl.style.top = `${Math.round(top)}px`;

    activeBtn = btn;
    btn.setAttribute('aria-expanded', 'true');
  }

  function makeHintButton(navBtn, text) {
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
        openPopover(btn, text);
      }
    });
    // Empêche le hover/click du parent de déclencher la navigation.
    btn.addEventListener('mousedown', (e) => e.stopPropagation());
    return btn;
  }

  function attachAll() {
    const items = document.querySelectorAll('.nav-item[data-view]');
    items.forEach((nav) => {
      if (nav.dataset.hintAttached === '1') return;
      const key = hintKey(nav);
      const text = HINTS[key];
      if (!text) return;
      const btn = makeHintButton(nav, text);
      // Si l'item a un badge (.nav-item-badge), on insère avant le badge.
      const badge = nav.querySelector('.nav-item-badge');
      if (badge) {
        nav.insertBefore(btn, badge);
      } else {
        nav.appendChild(btn);
      }
      nav.dataset.hintAttached = '1';
    });
  }

  // Fermer la bulle quand on clique ailleurs / scroll / resize / Escape.
  document.addEventListener('click', (e) => {
    if (!popoverEl) return;
    if (e.target === activeBtn || (activeBtn && activeBtn.contains(e.target))) return;
    if (popoverEl.contains(e.target)) return;
    closePopover();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closePopover();
  });
  window.addEventListener('resize', closePopover);
  window.addEventListener('scroll', closePopover, true);

  // Premier branchement + ré-essai si la sidebar se construit après.
  function init() {
    attachAll();
    // Quelques retries pour les vues construites dynamiquement.
    setTimeout(attachAll, 300);
    setTimeout(attachAll, 1200);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
