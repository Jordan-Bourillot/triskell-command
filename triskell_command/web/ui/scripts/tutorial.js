/* Tuto — visite guidée complète en HTML.
 * Modale stepper avec progress bar, clic « Aller voir » → ouvre la vue
 * (et mémorise l’étape : la prochaine ouverture propose de reprendre là).
 *
 * Couvre le parcours réel de l’app (refonte du 10/06/2026) :
 *   Lancer une prospection → base « Tous les prospects » → Auto-pilote
 *   (modèles du Catalogue + relecture IA) → brouillons → réponses triées →
 *   projets clients → livraison → relances → mesures.
 *
 * Pour l’aide ciblée par écran (mini-tuto), voir help.js (bouton « ? »
 * sur les écrans principaux).
 */

const Tutorial = {
  // Clé de mémorisation de l’étape (bouton « Aller voir » → reprise)
  STORE_KEY: 'tc-tuto-step',

  steps: [
    // ---- Bienvenue ----
    { icon: '✨', title: 'Bienvenue dans Triskell Command',
      lead: 'Ton tableau de bord pour piloter tout l’écosystème Triskell.',
      body: "En quelques minutes, tu vas voir comment l’app travaille pour " +
            "toi. Le fil rouge :\n\n" +
            "1. « Lancer une prospection » : des outils TROUVENT des contacts.\n" +
            "2. Tout atterrit dans UNE base commune : « Tous les prospects ».\n" +
            "3. L’Auto-pilote ÉCRIT et ENVOIE les mails (relus par une 2e IA).\n" +
            "4. Les RÉPONSES reviennent triées toutes seules.\n\n" +
            "💡 Conseil : sur les écrans principaux, clique le bouton « ? » " +
            "en haut à droite pour une aide ciblée.\n\n" +
            "Tu peux rouvrir cette visite à tout moment depuis Réglages → " +
            "Visite guidée — elle te proposera de reprendre où tu t’étais " +
            "arrêté." },

    // ---- Le Cockpit ----
    { icon: '🎛️', title: 'Le Cockpit — ton seul écran à ouvrir',
      lead: 'Tout en 5 minutes par jour.', goto: 'morning',
      body: "Tu y vois en un coup d’œil :\n" +
            "• La priorité du jour (calculée par l’app).\n" +
            "• Hier en chiffres : envoyés, réponses, intéressés.\n" +
            "• Les relances LinkedIn préparées par l’IA (3 clics).\n" +
            "• Les soucis éventuels.\n\n" +
            "C’est l’écran qui s’ouvre par défaut quand tu lances l’app. " +
            "La rampe « Lancer une prospection » t’emmène directement au " +
            "départ de la chaîne — justement, étape suivante." },

    // ---- Lancer une prospection ----
    { icon: '🚀', title: 'Lancer une prospection — une commande, toute la chaîne',
      lead: 'Tu choisis une cible, l’app enchaîne tout.', goto: 'prospection',
      body: "Premier onglet de la section PROSPECTION. Tu choisis une cible " +
            "(PME, commerces locaux ou créateurs), tu remplis 2-3 champs, " +
            "tu cliques « Lancer » — et l’app enchaîne toute seule :\n\n" +
            "1. Elle CHERCHE avec l’outil adapté : Le Chasseur pour les " +
            "PME, le Prospecteur Google pour les commerces locaux, Obélisk " +
            "pour les créateurs.\n" +
            "2. Les fiches avec un mail sont VERSÉES dans la base commune " +
            "« Tous les prospects » — sans doublon, jamais un client ni un " +
            "désinscrit, avec un contrôle qualité (« X/Y fiches gardées »).\n" +
            "3. Si l’Auto-pilote est allumé (interrupteur sur l’écran), il " +
            "prend le relais pour écrire et envoyer.\n" +
            "4. Les réponses reviennent triées automatiquement.\n\n" +
            "💡 Case « Faire un essai d’abord » : la recherche tourne pour " +
            "de vrai mais rien n’est enregistré — tu vois un rapport et tu " +
            "relances en réel si ça te plaît. (Pas disponible pour les " +
            "créateurs.)\n\n" +
            "Chaque mission s’affiche avec sa chaîne en 4 étapes et ses " +
            "compteurs en direct. Tu peux fermer la page : tout continue " +
            "côté serveur." },

    // ---- Tous les prospects ----
    { icon: '🗂️', title: 'Tous les prospects — la base commune',
      lead: 'Tout ce que les outils trouvent arrive ici.', goto: 'prospects_crm',
      body: "C’est LE point de passage obligé : chaque outil de recherche " +
            "y verse ses trouvailles, et l’Auto-pilote y pioche.\n\n" +
            "• Pas de doublon : les fiches identiques fusionnent.\n" +
            "• Jamais deux fiches avec le même mail.\n" +
            "• Jamais un prospect dont le mail est déjà un client.\n" +
            "• Un désinscrit ne revient jamais.\n\n" +
            "Tu peux aussi importer ta propre liste (bouton « Importer " +
            "fichier », Excel ou CSV) : elle passe par les mêmes garde-fous." },

    // ---- Auto-pilote ----
    { icon: '🤖', title: 'L’Auto-pilote — il écrit et il envoie',
      lead: 'Il pioche dans ta base, jamais ailleurs.',
      goto: 'autopilot',
      body: "L’Auto-pilote prend ses prospects UNIQUEMENT dans la base " +
            "« Tous les prospects ». Il ne cherche jamais sur internet et " +
            "ne complète jamais une fiche tout seul.\n\n" +
            "À chaque passage :\n" +
            "1. Il écarte ceux à ne pas recontacter (clients, désinscrits, " +
            "déjà contactés).\n" +
            "2. Il prend le modèle de mail du produit (Catalogue) et " +
            "l’utilise TEL QUEL — l’IA remplit juste les trous (prénom, " +
            "ville…), elle ne réécrit rien.\n" +
            "3. Une 2e IA relit chaque mail (interrupteur « Relecture IA : " +
            "Activée / Coupée ») ; en cas de doute → brouillon, pas d’envoi.\n" +
            "4. Il envoie, dans la limite de ton plafond par jour et de ta " +
            "plage horaire.\n\n" +
            "Coche « Passage automatique à… » et choisis l’heure : il " +
            "tourne tout seul chaque jour à cette heure-là. « Lancer " +
            "maintenant » fait exactement le même travail, tout de suite. " +
            "Chaque maillon a son interrupteur — et armer l’envoi " +
            "automatique demande toujours une confirmation explicite." },

    // ---- Modèles de mails ----
    { icon: '📝', title: 'Les modèles de mails',
      lead: 'Ce que reçoivent tes prospects, au mot près.',
      goto: 'mail_templates',
      body: "Menu MAILS → deux entrées :\n" +
            "• « Modèles · prospection » : les mails que l’Auto-pilote " +
            "envoie aux prospects — utilisés tels quels, l’IA remplit " +
            "juste les trous.\n" +
            "• « Modèles · après-achat » : les mails automatiques envoyés " +
            "à tes clients après une vente (bienvenue, livraison, relances " +
            "de suivi).\n\n" +
            "L’IA n’écrit librement un mail QUE si le produit poussé n’a " +
            "pas de modèle. Sinon, ton modèle pilote.\n\n" +
            "💡 Un modèle par produit actif du Catalogue : c’est ici que " +
            "tu contrôles exactement ce qui part." },

    // ---- Le Convoi ----
    { icon: '📦', title: 'Le Convoi — pour ta propre liste',
      lead: 'Tu fournis un fichier, l’app fait le reste.', goto: 'convoy',
      body: "Tu as déjà une liste de contacts ? Le Convoi est fait pour " +
            "ça :\n\n" +
            "1. Tu glisses ton fichier (PDF, Word, Excel, même une image) " +
            "— l’app en extrait les contacts.\n" +
            "2. Tu choisis l’offre et tu donnes tes consignes.\n" +
            "3. L’IA prépare un mail par personne.\n" +
            "4. Tu relis et tu valides.\n" +
            "5. Ça part au rythme que tu choisis (plafond par jour, heure " +
            "de départ)." },

    // ---- Brouillons ----
    { icon: '✓', title: 'Brouillons à valider',
      lead: 'Le sas de contrôle de tout ce qui est en attente.',
      goto: 'drafts',
      body: "Tous les mails préparés par l’app en mode validation " +
            "atterrissent ici : premiers contacts, relances, réponses, " +
            "suivi après-vente, recyclage de dormants.\n\n" +
            "• Tu corriges si besoin, puis « Approuver » : le mail part " +
            "après 5 secondes — le temps d’annuler d’un clic.\n" +
            "• « Tout envoyer » affiche le nombre exact de mails concernés " +
            "et envoie la série, avec un bouton « Arrêter » pendant " +
            "l’envoi." },

    // ---- Réponses ----
    { icon: '📬', title: 'Les réponses, triées toutes seules',
      lead: 'L’app surveille ta boîte mail toutes les 5 minutes.',
      goto: 'replies',
      body: "Quand un prospect répond :\n" +
            "1. L’app détecte la réponse et l’associe au bon prospect.\n" +
            "2. L’IA la classe : Intéressé · Pas maintenant · Refus · " +
            "Désinscription (et « À trier » quand elle hésite).\n" +
            "3. Pour les intéressés, l’IA prépare un brouillon de réponse.\n\n" +
            "Tu n’as plus à surveiller ta boîte mail toi-même." },

    // ---- Mode d'envoi ----
    { icon: '⚙️', title: 'Trois niveaux d’automatisation',
      lead: 'Validation manuelle · Auto après 30 min · Auto immédiat.',
      body: "Pour chaque type de réponse (Intéressé, Pas maintenant…), tu " +
            "décides :\n" +
            "• Validation manuelle : rien ne part sans ton clic.\n" +
            "• Auto après 30 min : si tu ne touches pas, ça part.\n" +
            "• Auto immédiat : ça part dès la détection.\n\n" +
            "💡 Pour démarrer : tout en manuel le temps de calibrer (50 " +
            "réponses), puis bascule au cas par cas." },

    // ---- Écrire un mail ----
    { icon: '✉️', title: 'Écrire un mail — la fenêtre d’écriture',
      lead: 'Un vrai client mail intégré, pas besoin d’app externe.',
      goto: 'mails',
      body: "Bouton « Nouveau mail » dans la vue Mails (ou Ctrl+Maj+M " +
            "depuis n’importe quel écran). Tu y trouves :\n" +
            "• Destinataires en pastilles colorées (Entrée pour valider) : " +
            "chaque adresse prise en compte se voit clairement.\n" +
            "• Champs Cc et Cci (révélés au clic sur « + Cc » / « + Cci »).\n" +
            "• Mise en forme riche : gras, italique, listes, liens, " +
            "titres, citations, avec aperçu du rendu réel.\n" +
            "• Bouton 🖼 pour insérer une image dans le corps, " +
            "glisser-déposer de fichiers (pièce jointe ou dans le corps).\n" +
            "• Brouillons gardés : tu fermes, tu reviens, tu reprends.\n" +
            "• Bouton « ⏱ Plus tard » : programme l’envoi (« Dans 1h », " +
            "« Demain 9h »…). Le mail part tout seul à l’heure dite et " +
            "reste annulable dans l’onglet Programmés.\n" +
            "• Signatures choisies automatiquement selon l’adresse " +
            "d’envoi.\n\n" +
            "La vue Mails range tout en 4 onglets : Boîte de réception " +
            "(les réponses liées à ta prospection), Réponses prospects, " +
            "Messages envoyés, Programmés." },

    // ---- Prospection en direct ----
    { icon: '⚡', title: 'Prospection en direct — site fait pour eux',
      lead: 'Tu colles l’adresse du site, Claude rédige le mail.',
      goto: 'mails',
      body: "Bouton « ⚡ Prospection en direct » à côté de « Nouveau " +
            "mail ». Le scénario : tu as réalisé un site pour une " +
            "célébrité ou une entreprise locale, tu veux leur envoyer un " +
            "mail pour le leur présenter.\n\n" +
            "1. Tu choisis le type de cible : Célébrité ou Entreprise.\n" +
            "2. Tu colles l’adresse du site que tu as fait pour eux.\n" +
            "3. Claude (15-40 sec) lit le contenu du site, en capture une " +
            "image, choisit parmi tes modèles enregistrés celui qui colle " +
            "le mieux et l’adapte avec des détails vus sur le site.\n" +
            "4. La fenêtre d’écriture s’ouvre pré-remplie : objet + corps " +
            "mis en forme (couleurs, blocs, boutons), avec l’aperçu du " +
            "site intégré et un lien cliquable.\n\n" +
            "Tu corriges si besoin et tu envoies (ou tu programmes plus " +
            "tard)." },

    // ---- Bascule auto vers projet client ----
    { icon: '🎯', title: 'Bascule auto « intéressé → projet client »',
      lead: 'Quand quelqu’un dit oui, une carte projet se crée toute seule.',
      body: "Configurable dans Réglages → Bascule auto :\n" +
            "• OFF : tu cliques manuellement « + Créer projet client » " +
            "dans la vue Réponses.\n" +
            "• Signal d’achat fort : ne bascule QUE si la réponse contient " +
            "« prix », « devis », « j’achète », etc. (recommandé).\n" +
            "• Tous les intéressés : ratisse large, à toi de filtrer après." },

    // ---- Clients (kanban) ----
    { icon: '📋', title: 'Clients — le tableau des projets en cours',
      lead: 'Briefing → En cours → Livré → Clôturé.', goto: 'clients',
      body: "Toutes les ventes (manuelles, Stripe, AppSumo, basculées des " +
            "réponses) atterrissent ici. Tu déplaces les cartes de colonne " +
            "en colonne avec les flèches ‹ ›.\n\n" +
            "💡 Bouton « ⚡ Livrer » sur chaque carte : envoie " +
            "immédiatement le mail de bienvenue + livrables du produit.\n\n" +
            "Cet écran n’est pas dans le menu : retrouve-le avec la " +
            "recherche (Ctrl+K) ou ce bouton « Aller voir »." },

    // ---- Stripe + AppSumo ----
    { icon: '💳', title: 'Paiements auto : Stripe + AppSumo',
      lead: 'Un paiement = une carte projet créée automatiquement.',
      body: "Triskell Command vérifie Stripe toutes les 5 min (réglable " +
            "dans Réglages → Stripe). À chaque paiement : carte projet " +
            "créée avec la date de paiement remplie → le kit de livraison " +
            "du produit part dans la foulée.\n\n" +
            "Pour AppSumo : demande à Claude d’activer le suivi (5 min, " +
            "gratuit). Chaque activation de licence crée alors un projet, " +
            "pareil." },

    // ---- Kits de livraison ----
    { icon: '🎁', title: 'Kits de livraison par produit',
      lead: 'Mail de bienvenue + accès + relances de suivi.', goto: 'delivery',
      body: "Un kit par produit (Pack Élec, Studio PDF, Obelisk…). Chaque " +
            "kit contient :\n" +
            "• Mail de bienvenue (sujet + corps avec variables " +
            "{client_name} etc.).\n" +
            "• Liste de livrables (adresses web, codes d’accès).\n" +
            "• Suivi automatique J+3 « ça va ? », J+14 astuce, J+30 " +
            "demande d’avis.\n\n" +
            "Modifiable à volonté avec aperçu en direct. Écran accessible " +
            "via la recherche (Ctrl+K) ou Réglages → Livraison." },

    // ---- Relances LinkedIn ----
    { icon: '🔗', title: 'Relances LinkedIn préparées par l’IA',
      lead: 'Quand le mail ne suffit pas.',
      body: "L’app détecte les prospects sans réponse après 5 jours et " +
            "génère pour chacun un message LinkedIn court personnalisé.\n\n" +
            "Tu les vois dans le Cockpit (bloc « LinkedIn — relances à " +
            "faire »). 3 clics par fiche : copier le message, ouvrir le " +
            "profil, marquer fait.\n\n" +
            "Si tu as Phantombuster (~70€/mois), le bouton « ⚡ Tout " +
            "envoyer » expédie tout d’un coup — limité en cadence " +
            "(~25/jour) pour ne pas te faire bloquer par LinkedIn." },

    // ---- Recyclage des dormants ----
    { icon: '♻️', title: 'Recyclage des « pas maintenant »',
      lead: 'Réveille les prospects qui dormaient.',
      body: "Quelqu’un t’a dit « pas dispo » il y a 3 mois ou plus ? L’app " +
            "le détecte automatiquement et lui rédige un mail de réveil " +
            "court (« on reprend là où on s’était arrêtés ? »).\n\n" +
            "Mode manuel (brouillon dans la file) ou auto (envoi direct). " +
            "Plafond prudent de 5 par jour pour préserver ta réputation " +
            "d’envoi." },

    // ---- Funnel ----
    { icon: '📈', title: 'Conversions — où ça marche, où ça coince',
      lead: 'Prospects → Envoyés → Réponses → Intéressés → Gagnés.',
      goto: 'funnel',
      body: "Vue à 5 étages, filtres par période (7j/30j/90j/tout) et par " +
            "type de cible. Tu vois ton taux de réponse, ton taux " +
            "d’intérêt et ton taux de gain en temps réel.\n\n" +
            "Le tableau « Quel modèle de mail fait répondre ? » compare " +
            "tes modèles entre eux : envois, réponses, intéressés, taux." },

    // ---- A/B Test ----
    { icon: '🧪', title: 'Tests A/B des sujets de mail',
      lead: 'Compare plusieurs variantes objectivement.',
      goto: 'abtest',
      body: "Crée une campagne avec 2 à 5 variantes de sujet. L’app " +
            "distribue équitablement les envois et mesure le taux de " +
            "réponse de chacune.\n\n" +
            "Au bout d’environ 30 envois par variante, un calcul " +
            "statistique fiable désigne le gagnant — seulement si l’écart " +
            "est net, pas au flair.\n\n" +
            "Écran accessible via la recherche (Ctrl+K) ou Réglages → " +
            "« Gérer mes tests »." },

    // ---- Suivi d'ouvertures ----
    { icon: '👁', title: 'Suivi d’ouvertures de mail',
      lead: 'Sache qui ouvre tes mails.',
      body: "Coche « Activer le suivi » dans Réglages : tes mails sortants " +
            "embarquent une minuscule image invisible qui signale chaque " +
            "ouverture.\n\n" +
            "La mise en route se fait une fois (demande à Claude " +
            "d’activer le suivi — 5 min, gratuit). Ensuite : statistiques " +
            "automatiques sur 7 et 30 jours." },

    // ---- Le Phare ----
    { icon: '🗼', title: 'Le Phare — ton agence SEO autonome',
      lead: 'Des agents IA veillent sur tes sites, heure par heure.',
      goto: 'phare',
      body: "Une équipe d’agents IA surveille tes sites Triskell et ceux " +
            "de tes clients SEO : audit technique, mots-clés, liens " +
            "entrants, pages rafraîchies, fiches Google de tes " +
            "établissements, bulletins quotidiens, rapports mensuels…\n\n" +
            "Tout tourne automatiquement. Chaque modification proposée " +
            "apparaît sur la fiche du site concerné : rien ne part en " +
            "ligne sans ton OK — sauf si tu allumes la publication " +
            "automatique dans « En coulisses » (quelques modifications " +
            "vérifiées par jour, avec veto possible le matin)." },

    // ---- Santé du système ----
    { icon: '💚', title: 'Santé du système',
      lead: 'Tous tes robots de fond en temps réel.',
      goto: 'health',
      body: "Pastilles vert/jaune/rouge pour chaque robot, dernière " +
            "exécution, compteurs, erreurs. Bloc délivrabilité (envois et " +
            "réponses sur 24h/7j) et bouton « Vérifier mon domaine " +
            "d’envoi ». Rafraîchi tout seul toutes les 15 sec.\n\n" +
            "Si quelque chose plante, c’est ici que tu le vois en premier " +
            "— et une alerte arrive aussi sur ton téléphone si un robot " +
            "reste muet trop longtemps." },

    // ---- Réglages ----
    { icon: '🎛️', title: 'Réglages — tout configurer une fois',
      lead: 'Compte 10-15 min la première fois.', goto: 'config',
      body: "1. Te connecter à la base partagée Triskell.\n" +
            "2. Renseigner ton compte mail (l’envoi et la réception).\n" +
            "3. Mettre tes clés IA (Anthropic, Google, OpenAI…).\n" +
            "4. Activer Stripe (pour les paiements auto).\n" +
            "5. (Optionnel) Phantombuster + suivi d’ouvertures.\n" +
            "6. Personnaliser tes kits de livraison par produit." },

    // ---- Mon profil personnel ----
    { icon: '👤', title: 'Ton profil personnel',
      lead: 'Photo, nom, email — séparé des Réglages app.',
      body: "Clic sur ton prénom + photo en bas du menu → fenêtre « Mon " +
            "profil personnel ». Tu y modifies :\n" +
            "• Ta photo de profil (PNG/JPG/WebP, 4 Mo max).\n" +
            "• Ton nom complet (le prénom apparaît en bas du menu).\n" +
            "• Ton email d’expéditeur par défaut.\n\n" +
            "Toi et Thomas avez chacun votre profil distinct, même en " +
            "partageant le même compte côté serveur.\n\n" +
            "💡 À ne pas confondre avec les Réglages app (juste en " +
            "dessous), qui gèrent comptes mail, clés IA, intégrations, etc." },

    // ---- Mode démo ----
    { icon: '🎬', title: 'Mode démo — pour les visuels promotionnels',
      lead: 'Une boîte qui tourne à plein régime, sans exposer tes vraies données.',
      goto: 'config',
      body: "Réglages → Système → « Activer le mode démo ». L’app se " +
            "recharge et :\n" +
            "• Tes vraies données sont masquées, remplacées par des " +
            "données fictives crédibles (clients, chiffre d’affaires, " +
            "mails échangés, projets remplis).\n" +
            "• Un bandeau « MODE DÉMO » s’affiche en haut, masquable " +
            "30 sec pour une capture d’écran propre.\n\n" +
            "Tu désactives, tes vraies données reviennent intactes. Idéal " +
            "pour des captures de promo ou pour montrer l’app à quelqu’un " +
            "sans exposer tes clients." },

    // ---- Outro ----
    { icon: '🎉', title: 'C’est tout pour la visite !',
      lead: 'La chaîne est bouclée de bout en bout.',
      body: "Le parcours complet : tu lances une prospection → la base " +
            "« Tous les prospects » se remplit → l’Auto-pilote écrit avec " +
            "tes modèles et envoie → les réponses reviennent triées → les " +
            "intéressés deviennent des projets clients → la livraison et " +
            "le suivi partent tout seuls — pendant que Le Phare et le GEO " +
            "veillent sur tes sites.\n\n" +
            "💡 Certains écrans pointus ne sont pas dans le menu (Projets " +
            "clients, Kits de livraison, Tests A/B…) : la recherche " +
            "(Ctrl+K) les retrouve en deux lettres.\n\n" +
            "💡 Et sur les écrans principaux, le bouton « ? » en haut à " +
            "droite ouvre l’aide de l’écran.\n\n" +
            "Bonne chasse." },
  ],

  index: 0,

  render(container) {
    const saved = this._savedStep();
    container.innerHTML = `
      <div class="text-center py-20">
        <div class="text-5xl mb-4">✨</div>
        <h2 class="hero-title mb-4" style="font-size: 32px;">Visite guidée</h2>
        <p class="text-text-secondary mb-6 max-w-md mx-auto">
          ${this.steps.length} étapes courtes — de la recherche de prospects
          jusqu’au suivi de tes clients.
        </p>
        <button class="btn btn-primary" onclick="Tutorial.open()">
          ${saved ? `Reprendre à l’étape ${saved}` : 'Lancer la visite'}
        </button>
      </div>
    `;
  },

  open() {
    this.index = 0;
    const overlay = this._buildOverlay();
    document.body.appendChild(overlay);
    const saved = this._savedStep();
    if (saved) this._renderResume(overlay, saved);
    else this._renderStep(overlay);
  },

  // ---- Mémoire de reprise (bouton « Aller voir » → on retient l'étape) ----
  _savedStep() {
    try {
      const n = parseInt(localStorage.getItem(this.STORE_KEY), 10);
      if (Number.isInteger(n) && n >= 1 && n < this.steps.length) return n;
    } catch (e) { /* stockage indisponible : pas de reprise, pas grave */ }
    return null;
  },

  _saveStep(i) {
    try { localStorage.setItem(this.STORE_KEY, String(i)); } catch (e) {}
  },

  _clearSaved() {
    try { localStorage.removeItem(this.STORE_KEY); } catch (e) {}
  },

  _buildOverlay() {
    const overlay = document.createElement('div');
    overlay.className = 'fixed inset-0 z-[100] flex items-center justify-center p-6';
    overlay.style.background = 'rgba(15,23,42,0.45)';
    overlay.style.backdropFilter = 'blur(6px)';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.setAttribute('aria-label', 'Visite guidée');
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

    // Fermeture propre : retire aussi l'écouteur Échap.
    const close = () => {
      document.removeEventListener('keydown', onEsc);
      overlay.remove();
    };
    overlay._tutoClose = close;

    // Échap / clic à côté → confirmation légère avant de fermer
    // (le bouton « Passer le tuto » reste une fermeture directe, voulue).
    let confirming = false;
    const requestClose = async () => {
      if (confirming) return;
      confirming = true;
      let ok = true;
      if (typeof Dialog !== 'undefined' && Dialog.confirm) {
        try {
          ok = await Dialog.confirm('Fermer la visite guidée ?', {
            title: 'Visite guidée',
            okLabel: 'Fermer',
            cancelLabel: 'Continuer la visite',
          });
        } catch (e) { ok = false; }
      }
      confirming = false;
      if (ok) close();
    };
    const onEsc = (e) => {
      if (e.key === 'Escape') { e.stopPropagation(); requestClose(); }
    };
    document.addEventListener('keydown', onEsc);
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) requestClose();
    });

    overlay.querySelector('#t-skip').onclick = () => close();
    overlay.querySelector('#t-prev').onclick = () => { this._prev(overlay); };
    overlay.querySelector('#t-next').onclick = () => { this._next(overlay); };
    return overlay;
  },

  // Écran de reprise : on était parti « voir » un écran en cours de visite.
  _renderResume(overlay, saved) {
    const step = this.steps[saved];
    const total = this.steps.length;
    overlay.querySelector('#t-counter').textContent = 'VISITE GUIDÉE';
    overlay.querySelector('#t-progress').style.width = `${(saved / total) * 100}%`;
    const body = overlay.querySelector('#t-body');
    body.innerHTML = `
      <div class="animate-fade-in text-center py-8">
        <div class="text-4xl mb-4">📍</div>
        <h2 class="font-display font-bold text-2xl mb-2 leading-tight">Reprendre la visite ?</h2>
        <p class="text-text-secondary mb-6">
          Tu t’étais arrêté à l’étape ${saved} — « ${this._esc(step.title)} ».
        </p>
        <div class="flex flex-col sm:flex-row gap-2 justify-center">
          <button class="btn btn-primary" id="t-resume">Reprendre à l’étape ${saved} →</button>
          <button class="btn btn-secondary" id="t-restart">Recommencer du début</button>
        </div>
      </div>
    `;
    body.querySelector('#t-resume').onclick = () => {
      this.index = saved;
      this._renderStep(overlay);
    };
    body.querySelector('#t-restart').onclick = () => {
      this._clearSaved();
      this.index = 0;
      this._renderStep(overlay);
    };
    const prev = overlay.querySelector('#t-prev');
    prev.disabled = true;
    prev.style.opacity = '0.4';
    overlay.querySelector('#t-next').textContent = 'Suivant ›';
  },

  _renderStep(overlay) {
    const step = this.steps[this.index];
    const total = this.steps.length;
    // Numérotation continue, calculée : l'accueil et la conclusion ne sont
    // pas numérotés, les étapes intermédiaires le sont d'après leur position.
    const isFirst = (this.index === 0);
    const isLast = (this.index === total - 1);
    const displayTitle = (!isFirst && !isLast)
      ? `${this.index}. ${step.title}`
      : step.title;
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
        <h2 class="font-display font-bold text-2xl mb-2 leading-tight">${this._esc(displayTitle)}</h2>
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
        // On mémorise l'étape : la prochaine ouverture proposera la reprise.
        this._saveStep(this.index);
        if (typeof App !== 'undefined' && App.show) App.show(step.goto);
        if (overlay._tutoClose) overlay._tutoClose(); else overlay.remove();
      };
    }
    overlay.querySelector('#t-prev').disabled = (this.index === 0);
    overlay.querySelector('#t-prev').style.opacity = (this.index === 0) ? '0.4' : '1';
    overlay.querySelector('#t-next').textContent = isLast ? 'Terminer ✓' : 'Suivant ›';
  },

  _next(overlay) {
    if (this.index >= this.steps.length - 1) {
      // Visite terminée : plus de reprise à proposer.
      this._clearSaved();
      if (overlay._tutoClose) overlay._tutoClose(); else overlay.remove();
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
