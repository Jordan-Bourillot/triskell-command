/* Tuto — visite guidée complète en HTML.
 * Modale stepper avec progress bar, click "Aller voir" → ouvre la vue.
 *
 * Couvre TOUT le pipeline auto bout en bout :
 *   prospection (Sirene/Maps/Obelisk) → IA → envoi → tri IA des réponses →
 *   bascule projet → livraison auto via kits → relances → recyclage → mesures.
 *
 * Pour l'aide ciblée par écran (mini-tuto), voir help.js (bouton ? sur
 * chaque vue).
 */

const Tutorial = {
  steps: [
    // ---- 0. Bienvenue ----
    { icon: '✨', title: 'Bienvenue dans Triskell Command',
      lead: 'Ton tableau de bord pour piloter tout l\'écosystème Triskell.',
      body: "En 5 minutes, tu vas voir comment l'app travaille pour toi : de " +
            "la chasse au prospect jusqu'au mail de bienvenue post-paiement, " +
            "en passant par la rédaction IA, le tri des réponses, le suivi " +
            "client et la mesure des performances.\n\n" +
            "💡 Conseil : sur chaque écran, clique le bouton « ? » en haut " +
            "à droite pour voir un mini-tuto contextuel.\n\n" +
            "Tu peux rouvrir cette visite à tout moment depuis Réglages → " +
            "Visite guidée." },

    // ---- 1. La Matinale ----
    { icon: '☀️', title: '1. Le Matin — ton seul écran à ouvrir',
      lead: 'Tout en 5 minutes par jour.', goto: 'morning',
      body: "Tu y vois en un coup d'œil :\n" +
            "• La priorité du jour (calculée par l'app).\n" +
            "• Hier en chiffres : envoyés, réponses, intéressés.\n" +
            "• Les relances LinkedIn préparées par l'IA (3 clics).\n" +
            "• Les soucis éventuels.\n\n" +
            "C'est l'écran qui s'ouvre par défaut quand tu lances l'app." },

    // ---- 2. Auto-pilote ----
    { icon: '🚀', title: '2. Auto-pilote — décris ta cible une fois',
      lead: 'Recherche · enrichissement · IA · envoi · suivi.',
      goto: 'autopilot',
      body: "Tu choisis ta source : Sirene (entreprises FR, gratuit), Google " +
            "Maps (commerces locaux), ou Obelisk (créateurs/vendeurs déjà " +
            "scrapés sur 9 plateformes).\n\n" +
            "Tu remplis les filtres (NAF, département, plateforme…), tu " +
            "choisis le mode (validation ou auto), et l'IA prend le relais : " +
            "elle visite leur site, trouve l'email, rédige un mail unique " +
            "pour chacun, et envoie.\n\n" +
            "Coche « Auto-pilote programmé » : ça tourne tout seul vers 3h " +
            "du matin." },

    // ---- 3. Réponses IMAP ----
    { icon: '📬', title: '3. Tri auto des réponses entrantes',
      lead: "L'app surveille ta boîte mail toutes les 5 minutes.",
      goto: 'replies',
      body: "Quand un prospect répond :\n" +
            "1. L'app détecte la réponse et l'associe au bon prospect.\n" +
            "2. L'IA la classe en 5 catégories : intéressé · pas " +
            "maintenant · refus · désinscription · à trier.\n" +
            "3. Pour les intéressés, l'IA prépare un brouillon de réponse.\n\n" +
            "Tu n'as plus à surveiller ta boîte mail toi-même." },

    // ---- 4. Mode d'envoi ----
    { icon: '⚙️', title: '4. Trois niveaux d\'automatisation',
      lead: 'Validation manuelle · Auto J+30min · Auto immédiat.',
      body: "Pour chaque type de réponse (interested, not_now…), tu décides :\n" +
            "• Validation manuelle : rien ne part sans ton clic.\n" +
            "• Auto après 30 min : si tu ne touches pas, ça part.\n" +
            "• Auto immédiat : ça part dès la détection.\n\n" +
            "💡 Pour démarrer : tout en manuel le temps de calibrer (50 " +
            "réponses), puis bascule au cas par cas." },

    // ---- 5. Brouillons ----
    { icon: '✓', title: '5. Brouillons à valider',
      lead: 'Le sas de contrôle de tout ce qui est en attente.',
      goto: 'drafts',
      body: "Tous les mails préparés par l'app en mode validation atterrissent " +
            "ici : premiers contacts, relances, réponses, suivi après-vente, " +
            "recyclage de dormants. Tu corriges si besoin et tu approuves." },

    // ---- 5 bis. Composer mail moderne (mai 2026) ----
    { icon: '✉️', title: 'Le composer mail moderne',
      lead: 'Un vrai client mail intégré, pas besoin d\'app externe.',
      goto: 'mails',
      body: "Bouton « Nouveau mail » dans la vue Mails. Tu y trouves :\n" +
            "• Destinataires en pastilles colorées (avec Entrée pour valider). " +
            "Plus de doute, on voit clairement chaque adresse prise en compte.\n" +
            "• Champs Cc et Cci (révélés au clic sur « + Cc » / « + Cci »).\n" +
            "• Mode HTML enrichi par défaut : gras, italique, listes, liens, " +
            "titres, citations, coller du HTML brut, aperçu du rendu réel.\n" +
            "• Bouton 🖼 pour insérer une image directement dans le corps.\n" +
            "• Glisser-déposer un fichier → choix « En pièce jointe » ou " +
            "« Dans le corps du mail ».\n" +
            "• Clic sur une image insérée → la rendre cliquable (URL de redirection).\n" +
            "• Brouillons sauvegardés dans le navigateur : tu fermes, tu " +
            "reviens, un bandeau te propose de restaurer.\n" +
            "• Bouton « ⏱ Plus tard » : programme l'envoi à une date/heure " +
            "(raccourcis « Dans 1h », « Demain 9h », etc.). Le mail part tout " +
            "seul à l'heure dite, même si tu as fermé l'app.\n" +
            "• Signatures multi-comptes auto-sélectionnées selon l'expéditeur, " +
            "et bouton ✏ pour aller gérer les signatures dans Réglages." },

    // ---- 5 ter. Prospection en direct ----
    { icon: '⚡', title: 'Prospection en direct — site fait pour eux',
      lead: 'Tu colles l\'URL, Claude rédige le mail de présentation.',
      goto: 'mails',
      body: "Bouton « ⚡ Prospection en direct » à côté de « Nouveau mail ». " +
            "Le scénario : tu as réalisé un site (souvent un sous-domaine " +
            "Triskell) pour une célébrité ou une entreprise locale. Tu veux " +
            "leur envoyer un mail pour leur présenter ce site.\n\n" +
            "1. Tu choisis le type de cible : Célébrité ou Entreprise.\n" +
            "2. Tu colles l'URL du site que tu as fait pour eux.\n" +
            "3. Claude (15-40 sec) télécharge le contenu du site, capture " +
            "une image en 1280×720, lit tes modèles HTML enregistrés, choisit " +
            "celui qui colle le mieux et l'adapte avec des éléments précis " +
            "vus sur le site.\n" +
            "4. Le composer s'ouvre pré-rempli : objet + corps HTML qui " +
            "reprend la mise en forme de ton modèle (couleurs, blocs, " +
            "boutons), avec l'aperçu du site intégré et un lien cliquable.\n\n" +
            "Tu corriges si besoin et tu envoies (ou tu programmes plus tard)." },

    // ---- 6. Bascule auto vers projet client ----
    { icon: '🎯', title: '6. Bascule auto « intéressé → projet client »',
      lead: 'Quand quelqu\'un dit oui, une carte projet se crée toute seule.',
      body: "Configurable dans Réglages → Bascule auto :\n" +
            "• OFF : tu cliques manuellement « + Créer projet client » dans " +
            "la vue Réponses.\n" +
            "• Signal d'achat fort : ne bascule QUE si la réponse contient " +
            "« prix », « devis », « j'achète », etc. (recommandé).\n" +
            "• Tous les intéressés : ratisse large, à toi de filtrer après." },

    // ---- 7. Calendly ----
    { icon: '📅', title: '7. Calendly — propose un créneau en 1 clic',
      lead: 'Quand un prospect dit « ok on en parle ? ».',
      body: "Sur chaque carte de réponse intéressée : bouton « 📅 Proposer " +
            "créneau ». L'app crée un lien Calendly à usage unique et envoie " +
            "le mail au prospect avec ce lien.\n\n" +
            "Configure ton PAT Calendly + ton type de RDV par défaut dans " +
            "Réglages → Calendly." },

    // ---- 8. Clients (kanban) ----
    { icon: '📋', title: '8. Clients — kanban des projets en cours',
      lead: 'Briefing → En cours → Livré → Clôturé.', goto: 'clients',
      body: "Toutes les ventes (manuelles, Stripe, AppSumo, basculées des " +
            "réponses) atterrissent ici. Tu fais glisser les cartes de " +
            "colonne en colonne.\n\n" +
            "💡 Bouton « ⚡ Livrer » sur chaque carte : envoie immédiatement " +
            "le mail de bienvenue + livrables du produit." },

    // ---- 9. Stripe + AppSumo ----
    { icon: '💳', title: '9. Paiements auto : Stripe + AppSumo',
      lead: 'Un paiement = une carte projet créée automatiquement.',
      body: "Triskell Command interroge Stripe toutes les 5 min (config " +
            "dans Réglages → Stripe). À chaque paiement : carte projet créée " +
            "avec paid_at rempli → le kit de livraison du produit part dans " +
            "la foulée.\n\n" +
            "Pour AppSumo : déploie la mini Netlify Function fournie " +
            "(netlify_functions/, 5 min, gratuit). Elle reçoit les " +
            "activations de license et crée les projets pareil." },

    // ---- 10. Kits de livraison ----
    { icon: '🎁', title: '10. Kits de livraison par produit',
      lead: 'Mail bienvenue + accès + relances de suivi.', goto: 'delivery',
      body: "Un kit par produit (Pack Élec, Studio PDF, Obelisk…). Chaque kit " +
            "contient :\n" +
            "• Mail de bienvenue (sujet + corps avec variables {client_name} " +
            "etc.).\n" +
            "• Liste de livrables (URLs, codes d'accès).\n" +
            "• Suivi automatique J+3 « ça va ? », J+14 astuce, J+30 demande " +
            "d'avis.\n\n" +
            "Modifiable à volonté avec aperçu live." },

    // ---- 11. Relances LinkedIn (Phantombuster) ----
    { icon: '🔗', title: '11. Relances LinkedIn préparées par l\'IA',
      lead: 'Quand le mail ne suffit pas.',
      body: "L'app détecte les prospects sans réponse après 5 jours et " +
            "génère pour chacun un message LinkedIn court personnalisé.\n\n" +
            "Tu les vois dans la Matinale (bloc « LinkedIn — relances à " +
            "faire »). 3 clics par fiche : copier le message, ouvrir le " +
            "profil, marquer fait.\n\n" +
            "Si tu as Phantombuster (~70€/mois), bouton « ⚡ Tout envoyer » " +
            "balance tout d'un coup (rate-limité ~25/jour pour éviter le " +
            "ban LinkedIn)." },

    // ---- 12. Recyclage des dormants ----
    { icon: '♻️', title: '12. Recyclage des « pas maintenant »',
      lead: 'Réveille les prospects qui dormaient.',
      body: "Quelqu'un t'a dit « pas dispo » il y a 3+ mois ? L'app le détecte " +
            "automatiquement et lui rédige un mail de réveil court (« on " +
            "reprend là où on s'était arrêtés ? »).\n\n" +
            "Mode manuel (brouillon dans la file) ou auto (envoi direct). " +
            "Plafond conservateur 5/jour pour pas brûler ta délivrabilité." },

    // ---- 13. Funnel ----
    { icon: '📈', title: '13. Conversions — où ça marche, où ça coince',
      lead: 'Prospects → Envoyés → Réponses → Intéressés → Gagnés.',
      goto: 'funnel',
      body: "Vue à 5 étages, filtres période (7j/30j/90j/tout) et type " +
            "(créateurs/B2B local/tous). Tu vois ton taux de réponse, taux " +
            "d'intérêt, taux de gain en temps réel." },

    // ---- 14. A/B Test ----
    { icon: '🧪', title: '14. Tests A/B des sujets de mail',
      lead: 'Compare plusieurs variantes objectivement.',
      goto: 'abtest',
      body: "Crée une campagne avec 2 à 5 variantes de sujet. L'app distribue " +
            "équitablement les envois et mesure le taux de réponse de " +
            "chacune.\n\n" +
            "Au bout de ~30 envois par variante, l'app calcule un Z-test à " +
            "95% et désigne le gagnant si l'écart est statistiquement " +
            "significatif." },

    // ---- 15. Tracking d'ouvertures ----
    { icon: '👁', title: '15. Tracking d\'ouvertures de mail',
      lead: 'Un pixel transparent te dit qui ouvre.',
      body: "Coche « Activer le tracking » dans Réglages. Tous les mails " +
            "sortants incluront un pixel 1×1 invisible qui logue l'ouverture.\n\n" +
            "Demande de déployer une mini Netlify Function (5 min, gratuit, " +
            "doc dans netlify_functions/README.md). Stats automatiques 7j/30j." },

    // ---- 16. Le Phare ----
    { icon: '🗼', title: '16. Le Phare — agence SEO autonome',
      lead: '8 agents Claude qui surveillent tes 13 sites Triskell.',
      goto: 'phare',
      body: "Audit, mots-clés, backlinks, snippet hunter, refresh, GBP, " +
            "programmatic SEO, A/B test scientifique, monitoring de marque, " +
            "veille algo Google, bulletins PDF mensuels…\n\n" +
            "Tout tourne automatiquement. Tu valides les modifs proposées " +
            "dans le « Bac à PRs » avant push en prod." },

    // ---- 17. Santé du système ----
    { icon: '💚', title: '17. Santé du système',
      lead: 'Tes 10 outils autonomes en temps réel.',
      goto: 'health',
      body: "Pastilles vert/jaune/rouge pour chaque worker, dernière " +
            "exécution, compteurs, erreurs. Bloc délivrabilité (envois et " +
            "réponses 24h/7j). Refresh auto toutes les 15 sec.\n\n" +
            "Si quelque chose plante, c'est ici que tu vois en premier." },

    // ---- 18. Réglages ----
    { icon: '🎛️', title: '18. Pour tout configurer une fois',
      lead: 'Compte 10-15 min la première fois.', goto: 'config',
      body: "1. Te connecter à la base partagée Triskell.\n" +
            "2. Renseigner ton compte mail (SMTP + IMAP).\n" +
            "3. Mettre tes clés API IA (Anthropic, Google, OpenAI…).\n" +
            "4. Activer Stripe (pour les paiements auto).\n" +
            "5. Configurer Calendly (PAT + type de RDV).\n" +
            "6. (Optionnel) Phantombuster + tracking d'ouvertures.\n" +
            "7. Personnaliser tes kits de livraison par produit." },

    // ---- 18 bis. Mon profil personnel ----
    { icon: '👤', title: 'Ton profil personnel',
      lead: 'Photo, nom, email — séparé des Réglages app.',
      body: "Clic sur ton prénom + photo en bas de la sidebar → modale " +
            "« Mon profil personnel ». Tu y modifies :\n" +
            "• Ta photo de profil (PNG/JPG/WebP, 4 Mo max).\n" +
            "• Ton nom complet (le prénom apparaît en bas de sidebar).\n" +
            "• Ton email d'expéditeur par défaut.\n\n" +
            "Toi et Thomas avez chacun votre profil distinct (même quand " +
            "vous partagez le même compte Supabase côté serveur), grâce au " +
            "cookie de session.\n\n" +
            "💡 À ne pas confondre avec les Réglages app (juste en dessous), " +
            "qui gèrent comptes mail, clés API, intégrations, etc." },

    // ---- 18 ter. Mode démo ----
    { icon: '🎬', title: 'Mode démo — pour les visuels promotionnels',
      lead: 'Une boîte qui tourne à plein régime, sans toucher à tes vraies données.',
      goto: 'config',
      body: "Réglages → « Activer le mode démo ». L'app se recharge et :\n" +
            "• Toutes tes vraies données sont masquées et remplacées par " +
            "des données fictives crédibles : 214 clients actifs, 83 k€/mois, " +
            "60 mails échangés, pipelines remplis, KPIs gonflés.\n" +
            "• Aucune action n'est réelle : tu peux cliquer « Envoyer », " +
            "« Sauvegarder », tout ce que tu veux — rien ne part au serveur.\n" +
            "• Bandeau rouge/orange « MODE DÉMO » en haut, masquable 30 sec " +
            "pour une capture d'écran propre.\n\n" +
            "Tu désactives, tes vraies données reviennent intactes. Idéal " +
            "pour des screenshots de promo ou pour montrer l'app à quelqu'un " +
            "sans exposer tes clients." },

    // ---- 19. Outro ----
    { icon: '🎉', title: 'C\'est tout pour la visite !',
      lead: 'Le pipeline est désormais bouclé bout en bout.',
      body: "Tu as vu les modules autonomes qui tournent en arrière-plan " +
            "(prospection, tri des réponses, recyclage, livraisons, Phare SEO…) " +
            "+ les outils transverses (santé, A/B, tracking) + le composer " +
            "mail intégré avec prospection en direct.\n\n" +
            "Le scénario zéro-toi : Auto-pilote prospecte → IA rédige & " +
            "envoie → IMAP lit & classe → bascule projet auto → kit de " +
            "livraison part → suivis programmés → demande d'avis → " +
            "cross-sell → NPS → recyclage si dormant.\n\n" +
            "💡 N'oublie pas le bouton « ? » sur chaque écran pour les " +
            "détails contextuels, et le mode démo pour les screenshots.\n\n" +
            "Bonne chasse." },
  ],

  index: 0,

  render(container) {
    container.innerHTML = `
      <div class="text-center py-20">
        <div class="text-5xl mb-4">✨</div>
        <h2 class="hero-title mb-4" style="font-size: 32px;">Visite guidée</h2>
        <p class="text-text-secondary mb-6 max-w-md mx-auto">
          ${this.steps.length - 1} étapes pour découvrir tout le pipeline d'automatisation.
        </p>
        <button class="btn btn-primary" onclick="Tutorial.open()">Lancer la visite</button>
      </div>
    `;
  },

  open() {
    this.index = 0;
    const overlay = this._buildOverlay();
    document.body.appendChild(overlay);
    this._renderStep(overlay);
  },

  _buildOverlay() {
    const overlay = document.createElement('div');
    overlay.className = 'fixed inset-0 z-[100] flex items-center justify-center p-6';
    overlay.style.background = 'rgba(15,23,42,0.45)';
    overlay.style.backdropFilter = 'blur(6px)';
    overlay.innerHTML = `
      <div class="bg-surface rounded-3xl shadow-hero w-full max-w-2xl
                  overflow-hidden flex flex-col animate-slide-up"
           style="border: 1px solid hsl(var(--border)); max-height: 85vh;">
        <!-- Header -->
        <div class="px-8 pt-8 pb-4">
          <div class="hero-kicker mb-2" id="t-counter"></div>
          <div class="h-1 rounded-full" style="background: hsl(var(--border));">
            <div class="h-full rounded-full transition-all duration-300"
                 id="t-progress"
                 style="background: hsl(var(--accent)); width: 0%;"></div>
          </div>
        </div>
        <!-- Body -->
        <div class="px-8 py-6 overflow-y-auto flex-1" id="t-body"></div>
        <!-- Footer -->
        <div class="px-8 py-5 border-t border-border flex items-center justify-between">
          <button id="t-skip" class="btn btn-secondary">Passer le tuto</button>
          <div class="flex gap-2">
            <button id="t-prev" class="btn btn-secondary">‹ Précédent</button>
            <button id="t-next" class="btn btn-primary">Suivant ›</button>
          </div>
        </div>
      </div>
    `;
    overlay.querySelector('#t-skip').onclick = () => overlay.remove();
    overlay.querySelector('#t-prev').onclick = () => { this._prev(overlay); };
    overlay.querySelector('#t-next').onclick = () => { this._next(overlay); };
    return overlay;
  },

  _renderStep(overlay) {
    const step = this.steps[this.index];
    const total = this.steps.length;
    overlay.querySelector('#t-counter').textContent = `ÉTAPE ${this.index + 1} / ${total}`;
    overlay.querySelector('#t-progress').style.width = `${((this.index + 1) / total) * 100}%`;
    const body = overlay.querySelector('#t-body');
    body.innerHTML = `
      <div class="animate-fade-in">
        <div class="w-16 h-16 rounded-2xl mb-6
                    bg-gradient-to-br from-accent to-accent-glow
                    flex items-center justify-center text-3xl shadow-soft">
          ${step.icon}
        </div>
        <h2 class="font-display font-bold text-2xl mb-2 leading-tight">${this._esc(step.title)}</h2>
        ${step.lead ? `<div class="text-accent font-semibold text-base mb-4">${this._esc(step.lead)}</div>` : ''}
        <div class="text-text-secondary text-base leading-relaxed whitespace-pre-line">${this._esc(step.body)}</div>
        ${step.goto ? `
          <button class="btn btn-secondary mt-6" id="t-goto">
            Aller voir →
          </button>
        ` : ''}
      </div>
    `;
    if (step.goto) {
      const gotoBtn = overlay.querySelector('#t-goto');
      if (gotoBtn) gotoBtn.onclick = () => {
        App.show(step.goto);
        overlay.remove();
      };
    }
    overlay.querySelector('#t-prev').disabled = (this.index === 0);
    overlay.querySelector('#t-prev').style.opacity = (this.index === 0) ? '0.4' : '1';
    overlay.querySelector('#t-next').textContent = (this.index === total - 1) ? 'Terminer ✓' : 'Suivant ›';
  },

  _next(overlay) {
    if (this.index >= this.steps.length - 1) {
      overlay.remove();
      return;
    }
    this.index++;
    this._renderStep(overlay);
  },

  _prev(overlay) {
    if (this.index <= 0) return;
    this.index--;
    this._renderStep(overlay);
  },

  _esc(s) {
    return String(s || '').replace(/[&<>"']/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    }[c]));
  },
};
