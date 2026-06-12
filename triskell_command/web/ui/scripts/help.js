/* Help — mini-tuto contextuel sous chaque vue.
 *
 * Usage côté vue :
 *   1. Inclure le bouton "?" dans le hero : Help.button('morning')
 *   2. Help.init() est appelé au DOMContentLoaded (binding global)
 *   3. Au clic → panneau latéral droit avec les tips de cette vue
 *
 * Pour ajouter une vue : ajouter une entrée dans Help.tips ci-dessous.
 * Pas de jargon, ton parlant, focus sur "qu'est-ce que je peux faire ici".
 * Le bouton « ? » existe sur les écrans principaux (pas encore sur tous).
 */

const Help = {
  tips: {
    // ---------------- Cockpit ----------------
    morning: {
      title: 'Le Cockpit',
      lead: 'Ton seul écran à ouvrir le matin.',
      sections: [
        {
          h: '👋 Pourquoi cet écran ?',
          p: "Tu y vois en 5 minutes ce qui s’est passé hier (mails envoyés, " +
             "réponses reçues), ce qui t’attend aujourd’hui (brouillons, " +
             "réponses à traiter), et les soucis éventuels."
        },
        {
          h: '🎯 Le bloc « Priorité du jour »',
          p: "L’app calcule automatiquement ce qui est le plus rentable à " +
             "traiter en premier. En général : prospects intéressés > " +
             "brouillons à valider > réponses à trier."
        },
        {
          h: '🚀 La rampe « Lancer une prospection »',
          p: "Le départ de toute la chaîne : tu choisis une cible, l’app " +
             "cherche, verse dans la base et passe le relais à " +
             "l’Auto-pilote. Tout se suit depuis l’écran Prospection."
        },
        {
          h: '⌨️ Raccourcis utiles',
          p: "Ctrl+Espace = ouvrir ton copilote (il répond et il agit) · " +
             "Ctrl+K = recherche globale · Alt+T = changer de thème · " +
             "Ctrl+Maj+M = nouveau mail. Tape ? pour la liste complète."
        },
      ],
    },

    // ---------------- Lancer une prospection ----------------
    prospection: {
      title: 'Lancer une prospection',
      lead: 'Une commande = toute la chaîne.',
      sections: [
        {
          h: '🎯 Choisis ta cible',
          p: "PME (registre officiel des entreprises), commerces locaux " +
             "(Google Maps) ou créateurs (YouTube, Twitch…). Tu remplis " +
             "2-3 champs, tu cliques « Lancer » : l’app choisit l’outil " +
             "adapté et enchaîne tout."
        },
        {
          h: '🔗 La chaîne en 4 étapes',
          p: "① Chercher → ② Verser dans « Tous les prospects » (sans " +
             "doublon, jamais un client ni un désinscrit) → ③ Passer le " +
             "relais à l’Auto-pilote s’il est allumé → ④ Les réponses " +
             "reviennent triées. Chaque mission affiche ses compteurs en " +
             "direct, et tu peux fermer la page : tout continue."
        },
        {
          h: '🧪 L’essai d’abord',
          p: "Coche « Faire un essai d’abord » : la recherche tourne pour " +
             "de vrai mais rien n’est enregistré. Tu vois combien de " +
             "fiches seraient versées + un échantillon, puis tu relances " +
             "en réel si ça te plaît. (Pas disponible pour les créateurs.)"
        },
        {
          h: '🛡️ Contrôle qualité',
          p: "Chaque versement est filtré : adresses invalides, noms " +
             "fantômes et doublons sont écartés avant la base. Le rapport " +
             "« X/Y fiches gardées » s’affiche sur la mission."
        },
        {
          h: '📄 Tu as déjà une liste ?',
          p: "La tuile « J’ai déjà une liste » t’envoie vers Le Convoi : " +
             "tu fournis ton fichier, l’IA prépare un mail par contact."
        },
      ],
    },

    // ---------------- Tous les prospects ----------------
    prospects_crm: {
      title: 'Tous les prospects',
      lead: 'La base commune — le point de passage obligé.',
      sections: [
        {
          h: '🗂️ Tout arrive ici',
          p: "Chaque outil de recherche verse ses trouvailles dans cette " +
             "base. Les fiches identiques fusionnent : pas de doublon."
        },
        {
          h: '🔒 Les garde-fous',
          p: "Jamais deux fiches avec le même mail. Jamais un prospect " +
             "dont le mail est déjà un client. Un désinscrit ne revient " +
             "jamais, quoi qu’il arrive."
        },
        {
          h: '📥 Importer ta liste',
          p: "Bouton « Importer fichier » (Excel ou CSV) : ta liste passe " +
             "par les mêmes garde-fous et fusionne avec l’existant."
        },
        {
          h: '🤖 Là où pioche l’Auto-pilote',
          p: "L’Auto-pilote prend ses prospects UNIQUEMENT ici. Base vide " +
             "= rien n’est envoyé. Chaque fiche garde son historique " +
             "(« La vie de ce prospect »)."
        },
      ],
    },

    // ---------------- Auto-pilote ----------------
    autopilot: {
      title: 'Auto-pilote',
      lead: 'La chaîne complète, sous tes ordres.',
      sections: [
        {
          h: '🎯 Ce que fait l’auto-pilote',
          p: "Il pioche dans la base « Tous les prospects », élimine ceux " +
             "à ne pas recontacter, prépare un mail à partir du modèle du " +
             "produit (utilisé tel quel — l’IA remplit juste les trous), " +
             "le fait relire par une 2e IA, puis envoie ou met en " +
             "brouillon si tu préfères valider à la main."
        },
        {
          h: '⚠️ Il ne cherche PAS de nouveaux prospects',
          p: "Il travaille uniquement sur la base « Tous les prospects » : " +
             "il ne va jamais sur internet et ne complète jamais une " +
             "fiche. Pour trouver des contacts : « Lancer une " +
             "prospection » (ou Le Chasseur, le Prospecteur Google, " +
             "Obélisk). Pour les fiches incomplètes : « Compléter les " +
             "fiches » (retrouve les mails/téléphones manquants)."
        },
        {
          h: '🎛️ Les 5 maillons',
          p: "Cherche (pioche) → Trie (élimine doublons / déjà contactés " +
             "/ clients) → Rédige (remplit le bon modèle) → Relit (2e IA " +
             "avec note sur 10) → Envoie (ou met en brouillon). Chaque " +
             "maillon a son interrupteur."
        },
        {
          h: '✅ Les interrupteurs',
          p: "Auto = ça part tout seul. Manuel sur « Rédige » = aucun " +
             "mail écrit. Sur « Relit », l’interrupteur s’appelle " +
             "« Relecture IA : Activée / Coupée » — coupée, les mails " +
             "passent sans contrôle. Manuel sur « Envoie » = chaque mail " +
             "part en brouillon pour ta validation. Armer l’envoi " +
             "automatique demande toujours une confirmation explicite."
        },
        {
          h: '🌙 Passage automatique à heure fixe',
          p: "Coche « Passage automatique à… » et choisis l’heure (heure " +
             "de Paris) : le robot tourne tout seul chaque jour à cette " +
             "heure-là, même si tu n’es pas connecté. « Lancer " +
             "maintenant » fait exactement le même travail, tout de suite."
        },
        {
          h: '🛑 Bouton Arrêter',
          p: "Pendant un passage (lancé à la main ou programmé), le " +
             "bouton rouge « Arrêter » coupe la chaîne. Les mails déjà " +
             "envoyés restent envoyés ; le reste est abandonné."
        },
        {
          h: '📮 Brouillons à valider',
          p: "Quand l’auto-pilote met un mail en brouillon, il atterrit " +
             "dans la page « Brouillons à valider » (menu de gauche). Le " +
             "bandeau en haut te dit combien attendent et t’y emmène."
        },
      ],
    },

    // ---------------- Modèles de mails ----------------
    mail_templates: {
      title: 'Modèles de mails',
      lead: 'Ce que reçoivent tes prospects et tes clients, au mot près.',
      sections: [
        {
          h: '📨 Deux familles',
          p: "« Modèles · prospection » = les mails que l’Auto-pilote " +
             "envoie aux prospects, utilisés TELS QUELS (l’IA remplit " +
             "juste les trous : prénom, ville…). « Modèles · " +
             "après-achat » = les mails automatiques envoyés à tes " +
             "clients après une vente (bienvenue, livraison, relances " +
             "de suivi)."
        },
        {
          h: '🤖 Et si un produit n’a pas de modèle ?',
          p: "Alors seulement, l’IA rédige librement pour ce produit. Dès " +
             "qu’un modèle existe, c’est lui qui pilote — l’IA ne " +
             "réécrit rien."
        },
        {
          h: '🧩 Les variables',
          p: "Des trous comme {prenom} ou {ville}, remplis automatiquement " +
             "à l’envoi pour chaque destinataire. La liste des variables " +
             "disponibles est affichée à côté de l’éditeur."
        },
        {
          h: '👁 Aperçu',
          p: "L’onglet Aperçu montre le rendu réel du mail, variables " +
             "remplacées par un exemple, avant d’enregistrer."
        },
      ],
    },

    // ---------------- Le Convoi ----------------
    convoy: {
      title: 'Le Convoi',
      lead: 'Ta liste à toi, traitée aux petits oignons.',
      sections: [
        {
          h: '📄 1. Ton fichier',
          p: "Glisse un PDF, Word, Excel ou même une image : l’app en " +
             "extrait les contacts (noms, mails) et te montre la liste " +
             "pour vérification."
        },
        {
          h: '🎯 2. L’offre et le ton',
          p: "Tu choisis le produit du Catalogue et tu donnes tes " +
             "consignes en 2-3 phrases. L’IA prépare un mail par " +
             "personne, adapté à chacune."
        },
        {
          h: '✅ 3. Tu valides',
          p: "Chaque mail se relit et se corrige avant départ. Rien ne " +
             "part sans ton OK, sauf si tu choisis l’envoi automatique."
        },
        {
          h: '🚚 4. Ça part au rythme choisi',
          p: "Plafond par jour, heure de départ : l’envoi s’étale tout " +
             "seul et tu suis l’avancement en direct."
        },
      ],
    },

    // ---------------- Drafts ----------------
    drafts: {
      title: 'Brouillons à valider',
      lead: 'Le sas de contrôle de tout ce que prépare l’app.',
      sections: [
        {
          h: '📝 Ce qui atterrit ici',
          p: "Tous les mails préparés par l’app en mode validation : " +
             "premiers contacts (auto-pilote), relances, réponses aux " +
             "entrants, suivi après-vente, recyclage de dormants. Tu " +
             "corriges si besoin et tu approuves."
        },
        {
          h: '✓ Approuver / ✗ Rejeter',
          p: "Approuver = le mail part après 5 secondes — le temps " +
             "d’annuler d’un clic si tu changes d’avis. Rejeter = " +
             "supprime le brouillon (le prospect ne reçoit rien)."
        },
        {
          h: '📤 Tout envoyer',
          p: "Le bouton affiche le nombre exact de mails concernés, " +
             "envoie la série en montrant la progression, et un bouton " +
             "« Arrêter » stoppe ce qui n’est pas encore parti."
        },
        {
          h: '✏️ Édition libre',
          p: "Tu peux modifier le sujet et le corps avant d’approuver. " +
             "Les modifs sont sauvées."
        },
      ],
    },

    // ---------------- Replies (Réponses) ----------------
    replies: {
      title: 'Réponses entrantes',
      lead: 'Les prospects qui te répondent, déjà triés.',
      sections: [
        {
          h: '🎨 Les 5 catégories',
          p: "L’IA classe chaque réponse : Intéressé · Pas maintenant · " +
             "Refus · Désinscription · À trier (quand elle hésite). " +
             "Filtre avec les pastilles en haut."
        },
        {
          h: '✉️ Réponse suggérée',
          p: "L’IA prépare souvent un brouillon de réponse. Tu peux " +
             "l’envoyer tel quel, le modifier, l’annuler, ou attendre " +
             "l’envoi auto (selon ton mode dans Réglages)."
        },
        {
          h: '+ Créer projet client',
          p: "Bouton vert sur les « Intéressé ». Crée une carte projet en " +
             "statut Briefing dans Clients. Si la bascule auto est " +
             "activée dans Réglages, ça se fait tout seul."
        },
        {
          h: '✉ Répondre directement',
          p: "Bouton « Répondre » sur chaque carte : ouvre la fenêtre " +
             "d’écriture, déjà pré-remplie avec le destinataire et " +
             "l’objet. Mise en forme, pièces jointes, envoi programmé ou " +
             "brouillon — tout y est."
        },
      ],
    },

    // ---------------- Mails ----------------
    mails: {
      title: 'Mails',
      lead: 'Ta boîte, déjà filtrée sur ce qui compte.',
      sections: [
        {
          h: '📥 4 onglets',
          p: "Boîte de réception (les réponses liées à ta prospection) · " +
             "Réponses prospects · Messages envoyés · Programmés (les " +
             "envois différés, annulables tant qu’ils ne sont pas " +
             "partis). Filtrables par adresse d’envoi."
        },
        {
          h: '✍️ Nouveau mail',
          p: "Bouton « Nouveau mail » (ou Ctrl+Maj+M depuis n’importe " +
             "quel écran) : destinataires en pastilles, Cc/Cci, mise en " +
             "forme riche, images, pièces jointes, signatures choisies " +
             "selon l’adresse d’envoi."
        },
        {
          h: '⏱ Plus tard',
          p: "Programme l’envoi (« Dans 1h », « Demain 9h »…) : le mail " +
             "part tout seul à l’heure dite, même app fermée. Tu le " +
             "retrouves (et l’annules) dans l’onglet Programmés."
        },
        {
          h: '📝 Brouillons',
          p: "Tes textes en cours sont gardés : tu fermes, tu reviens, " +
             "un bandeau te propose de reprendre où tu en étais."
        },
        {
          h: '⚡ Prospection en direct',
          p: "Tu as fait un site pour quelqu’un ? Colle son adresse : " +
             "Claude lit le site, choisit ton meilleur modèle et prépare " +
             "le mail de présentation, aperçu du site inclus."
        },
      ],
    },

    // ---------------- Obélisk ----------------
    obelisk: {
      title: 'Obélisk',
      lead: 'Trouve des créateurs (et des pros) en ligne.',
      sections: [
        {
          h: '🔍 Nouvelle recherche',
          p: "Tu donnes une niche et des plateformes (YouTube, Twitch, " +
             "Instagram…), et deux modes au choix : Créateurs ou Pros. " +
             "La recherche tourne côté serveur — tu peux quitter l’écran."
        },
        {
          h: '📬 Direct dans la base',
          p: "Les fiches trouvées avec un mail filent dans « Tous les " +
             "prospects », dédoublonnées, après le filtre anti fausses " +
             "adresses. Rien à verser à la main."
        },
        {
          h: '🧹 Outils de tri',
          p: "Filtres par plateforme, statut, mail présent ou non… et " +
             "exports Excel/CSV si tu veux travailler la liste ailleurs."
        },
      ],
    },

    // ---------------- Le Chasseur ----------------
    chasseur: {
      title: 'Le Chasseur',
      lead: 'Des PME françaises depuis le registre officiel.',
      sections: [
        {
          h: '🎯 Métier + zone',
          p: "Tu choisis le métier et le département (ou code postal), tu " +
             "lances. Les fiches viennent du registre officiel des " +
             "entreprises françaises — du solide."
        },
        {
          h: '📬 Verser dans la base',
          p: "Sur une chasse terminée, le bouton « Auto-Pilote » pousse " +
             "les fiches avec mail dans « Tous les prospects » " +
             "(dédoublonnées, contrôle qualité inclus)."
        },
        {
          h: '📤 Ou exporter',
          p: "Export CSV/Excel si tu préfères récupérer la liste pour " +
             "autre chose."
        },
        {
          h: '💡 Le chemin court',
          p: "« Lancer une prospection » (en haut du menu) fait tout ça " +
             "en une seule commande : chasse + versement + relais à " +
             "l’Auto-pilote."
        },
      ],
    },

    // ---------------- Prospecteur Google ----------------
    prospecteur_google: {
      title: 'Prospecteur Google',
      lead: 'Les commerces locaux — surtout ceux SANS site.',
      sections: [
        {
          h: '📍 Métier + ville',
          p: "Il interroge Google Maps et liste les commerces du coin : " +
             "nom, adresse, téléphone, site s’il existe."
        },
        {
          h: '🚩 Sans site = bon prospect',
          p: "Il repère ceux qui n’ont pas de site web — exactement les " +
             "clients potentiels de Triskell. Le filtre est affiché " +
             "clairement dans les résultats."
        },
        {
          h: '📬 Ajouter à mes prospects',
          p: "Un clic et les fiches avec mail filent dans « Tous les " +
             "prospects ». Export Excel/CSV possible aussi."
        },
      ],
    },

    // ---------------- Compléter les fiches ----------------
    eclaireur: {
      title: 'Compléter les fiches',
      lead: 'Retrouve les mails et téléphones manquants.',
      sections: [
        {
          h: '🕵️ Son vrai métier',
          p: "Il reprend tes fiches existantes incomplètes et part " +
             "chercher ce qui leur manque : adresse mail, téléphone. " +
             "Il ne crée pas de nouveaux prospects."
        },
        {
          h: '🔕 Il n’envoie rien',
          p: "C’est de la recherche pure : aucun mail ne part d’ici. " +
             "L’envoi reste l’affaire de l’Auto-pilote, que tu pilotes " +
             "séparément."
        },
        {
          h: '📈 Le résultat',
          p: "Des fiches complétées dans « Tous les prospects », prêtes " +
             "à être utilisées par l’Auto-pilote au prochain passage."
        },
      ],
    },

    // ---------------- Catalogue ----------------
    catalogue: {
      title: 'Le Catalogue',
      lead: 'Tes offres — la matière première de la prospection.',
      sections: [
        {
          h: '🏷️ Produits actifs',
          p: "L’interrupteur sur chaque produit décide s’il est proposé " +
             "aux prospects. L’Auto-pilote ne pousse QUE les produits " +
             "actifs."
        },
        {
          h: '📨 Le lien avec les modèles',
          p: "Chaque produit actif a son modèle de mail (menu MAILS → " +
             "« Modèles · prospection »). Pas de modèle = l’IA rédige " +
             "librement pour ce produit ; sinon le modèle pilote."
        },
        {
          h: '📦 Les packs',
          p: "Tu peux grouper plusieurs produits en une seule offre, avec " +
             "son prix et sa fiche à elle."
        },
      ],
    },

    // ---------------- Funnel ----------------
    funnel: {
      title: 'Conversions',
      lead: 'Tes taux de réponse, intérêt, et gain en un coup d’œil.',
      sections: [
        {
          h: '5 étapes du tunnel',
          p: "Prospects → Envoyés → Réponses → Intéressés → Clients " +
             "gagnés. Tu vois où ça coince (taux qui chute) et où ça " +
             "marche."
        },
        {
          h: 'Filtres période & type',
          p: "7 jours / 30 jours / 90 jours / tout. Type de cible : " +
             "créateurs / entreprises locales / tous mélangés."
        },
        {
          h: 'Quel modèle de mail fait répondre ?',
          p: "Le tableau compare tes modèles entre eux : envois, " +
             "réponses, intéressés, taux. De quoi garder les " +
             "formulations qui marchent."
        },
        {
          h: 'Comparer plusieurs variantes',
          p: "Pour comparer plusieurs sujets de mail entre eux, passe par " +
             "Réglages → « Gérer mes tests » (ou la recherche Ctrl+K, " +
             "« Test A/B »)."
        },
      ],
    },

    // ---------------- Clients ----------------
    clients: {
      title: 'Clients — projets en cours',
      lead: 'De la commande à la clôture.',
      sections: [
        {
          h: '4 colonnes',
          p: "Briefing (pas encore commencé) · En cours · Livré · " +
             "Clôturé. Tu déplaces les cartes de colonne en colonne avec " +
             "les flèches ‹ › de chaque carte."
        },
        {
          h: '⚡ Bouton « Livrer »',
          p: "Sur les cartes Briefing/En cours qui ont un email client : " +
             "envoie immédiatement le kit de livraison du produit (mail " +
             "de bienvenue + accès + relances de suivi). Le contenu vient " +
             "de Réglages → Éditer les kits."
        },
        {
          h: '💳 Cartes créées automatiquement',
          p: "Quand un paiement Stripe ou AppSumo arrive, ou quand un " +
             "prospect intéressé est basculé, une carte apparaît ici " +
             "toute seule. (Cf. Réglages → Stripe / Bascule auto)."
        },
        {
          h: '+ Nouveau projet manuel',
          p: "Pour un projet créé hors-tunnel (recommandation, contact " +
             "direct, etc.), bouton « + Nouveau projet » en haut à droite."
        },
      ],
    },

    // ---------------- Phare ----------------
    phare: {
      title: 'Le Phare — SEO autonome',
      lead: 'Une agence SEO qui tourne toute seule.',
      sections: [
        {
          h: '🗺️ Comment ça se présente',
          p: "L’accueil montre tous tes sites suivis, avec leur note et " +
             "leurs alertes. Clique une carte pour ouvrir la fiche du " +
             "site (recommandations, actions, historique). « En " +
             "coulisses » regroupe les réglages des robots."
        },
        {
          h: '🤖 Une équipe d’agents IA',
          p: "Audit technique, mots-clés, liens entrants, pages " +
             "rafraîchies, fiches Google de tes établissements, bulletins " +
             "quotidiens, rapports mensuels… Tout tourne automatiquement, " +
             "heure par heure."
        },
        {
          h: '✋ Tu valides avant publication',
          p: "Chaque modification proposée apparaît sur la fiche du site " +
             "concerné : rien ne part en ligne sans ton OK. Tu peux aussi " +
             "allumer la publication automatique (En coulisses) — " +
             "quelques modifications vérifiées par jour, avec veto " +
             "possible le matin."
        },
      ],
    },

    // ---------------- GEO ----------------
    geo: {
      title: 'Le GEO',
      lead: 'Être cité par ChatGPT, Perplexity et les autres IA.',
      sections: [
        {
          h: '🌍 Le principe',
          p: "De plus en plus de gens demandent à une IA « qui peut me " +
             "faire un site ? ». Le GEO travaille pour que TES sites " +
             "ressortent dans ces réponses-là."
        },
        {
          h: '🔄 Le cycle',
          p: "Il pose des questions aux IA, mesure si tes sites sont " +
             "cités, génère du contenu qui aide à l’être, et peut " +
             "publier — avec ton accord."
        },
        {
          h: '🤖 Auto-pilote GEO',
          p: "Un interrupteur dans l’écran fait tourner le cycle tout " +
             "seul à intervalle régulier. Par défaut il est éteint : " +
             "c’est toi qui décides de l’allumer."
        },
      ],
    },

    // ---------------- Delivery ----------------
    delivery: {
      title: 'Kits de livraison',
      lead: 'Ce qui part au client juste après son achat.',
      sections: [
        {
          h: '🎁 Un kit par produit',
          p: "Pack Élec, Studio PDF, Obelisk, etc. Chaque kit contient : " +
             "mail de bienvenue + livrables (adresses web, codes d’accès) " +
             "+ relances de suivi (J+3 « ça va ? », J+14 astuce, J+30 " +
             "demande d’avis)."
        },
        {
          h: '🔧 Variables disponibles',
          p: "{client_name}, {product_name}, {deliverables_list}, " +
             "{signature}. Elles sont remplacées automatiquement dans les " +
             "sujets et les corps."
        },
        {
          h: '👁 Aperçu en direct',
          p: "Bouton « Rafraîchir l’aperçu » : tu vois exactement ce que " +
             "recevra le client, variables remplies avec un client de " +
             "test."
        },
        {
          h: '📦 Le kit générique',
          p: "Si un produit acheté n’a pas de kit dédié, c’est le kit " +
             "générique qui part. Personnalise-le pour qu’il fasse bonne " +
             "figure en toutes circonstances."
        },
      ],
    },

    // ---------------- Health ----------------
    health: {
      title: 'Santé du système',
      lead: 'Tes robots de fond en temps réel.',
      sections: [
        {
          h: '🟢🟡🔴 Pastilles de santé',
          p: "Vert = tourne sans erreur · Jaune = tourne mais avec des " +
             "erreurs récentes · Rouge = à l’arrêt. Rafraîchi tout seul " +
             "toutes les 15 sec."
        },
        {
          h: '📊 Délivrabilité',
          p: "Envois et réponses sur 24h et 7j, taux de réponse calculé. " +
             "Si ton compte mail (envoi/réception) n’est pas configuré, " +
             "une alerte s’affiche. Le bouton « Vérifier mon domaine " +
             "d’envoi » contrôle tes tampons d’expéditeur."
        },
        {
          h: '🔍 Détail des robots',
          p: "Chaque carte montre : l’état (en marche / à l’arrêt), la " +
             "dernière exécution (« il y a X min »), les compteurs du " +
             "dernier passage, et les erreurs s’il y en a."
        },
      ],
    },

    // ---------------- A/B Test ----------------
    abtest: {
      title: 'Test A/B des sujets',
      lead: 'Compare plusieurs variantes objectivement.',
      sections: [
        {
          h: '🧪 Comment créer un test',
          p: "Bouton « + Nouvelle campagne ». Donne un nom (ex : " +
             "« Premier contact froid ») + 2 à 5 variantes de sujet, une " +
             "par ligne. L’app distribue équitablement les envois."
        },
        {
          h: '📈 Verdict statistique',
          p: "Au bout d’environ 30 envois par variante, l’app fait un " +
             "calcul statistique fiable et ne désigne le gagnant (👑) " +
             "que si l’écart est net — pas du flair."
        },
        {
          h: '✏️ Variables dans les sujets',
          p: "Tu peux utiliser {company_name}, {name}, {city}. Elles sont " +
             "remplacées au moment de l’envoi."
        },
      ],
    },

    // ---------------- Config ----------------
    config: {
      title: 'Réglages',
      lead: 'Tout configurer une fois pour toutes.',
      sections: [
        {
          h: '🎨 Apparence (3 thèmes)',
          p: "Clair, intermédiaire (graphite chaud), sombre. Tu peux " +
             "aussi changer avec Alt+T."
        },
        {
          h: '🤖 Services IA',
          p: "Tes clés IA (Anthropic, Google, OpenAI…). Stockées " +
             "chiffrées. Recommandé : Google Gemini (gratuit pour un " +
             "usage courant)."
        },
        {
          h: '✉️ Compte mail',
          p: "Les identifiants pour l’envoi et la réception de tes " +
             "mails. Pour Gmail, génère un mot de passe d’application " +
             "dans tes paramètres Google."
        },
        {
          h: '💳 Stripe + 🥭 AppSumo',
          p: "Active la vérification automatique des paiements Stripe " +
             "pour que chaque paiement crée son projet client tout seul. " +
             "Pour AppSumo, demande à Claude d’activer le suivi (5 min, " +
             "gratuit)."
        },
        {
          h: '🔗 Phantombuster',
          p: "Le service payant (~70€/mois) qui envoie tes relances " +
             "LinkedIn à ta place. Tu colles les deux codes fournis par " +
             "Phantombuster dans les champs prévus — l’écran t’indique " +
             "où les trouver."
        },
        {
          h: '👁 Suivi d’ouvertures',
          p: "Coche pour savoir qui ouvre tes mails (une minuscule image " +
             "invisible le signale). La mise en route se fait une fois : " +
             "demande à Claude d’activer le suivi (5 min, gratuit)."
        },
        {
          h: '🚪 Bascule auto + Livraison',
          p: "Bascule = quand un intéressé devient projet client (3 " +
             "modes). Livraison = éditer les kits par produit (mail de " +
             "bienvenue + livrables + suivis)."
        },
        {
          h: '🎬 Mode démo',
          p: "Dans l’onglet Système : remplace tes vraies données par des " +
             "données fictives crédibles, pour les captures d’écran et " +
             "les démonstrations. Tu désactives, tout revient."
        },
      ],
    },
  },

  // ---------------- API publique ----------------
  /** Renvoie le HTML d'un bouton "?" à coller dans le hero d'une vue. */
  button(viewId) {
    if (!this.tips[viewId]) return '';
    return `
      <button class="help-trigger inline-flex items-center justify-center
                     w-7 h-7 rounded-full text-text-muted hover:text-accent
                     hover:bg-accent/10 transition-colors text-sm font-bold"
              data-help-view="${viewId}"
              aria-label="Aide de cet écran"
              title="Mini-tuto de cette section">
        ?
      </button>
    `;
  },

  /** Affiche le panneau latéral pour la vue donnée. */
  show(viewId) {
    const tips = this.tips[viewId];
    if (!tips) return;

    // Ferme un panneau précédent s'il existe (et son écouteur Échap)
    if (this._escListener) {
      window.removeEventListener('keydown', this._escListener);
      this._escListener = null;
    }
    const old = document.getElementById('help-panel');
    if (old) old.remove();

    const panel = document.createElement('div');
    panel.id = 'help-panel';
    panel.className = 'fixed inset-0 z-[150] flex justify-end';
    panel.style.background = 'rgba(15,23,42,0.30)';
    panel.style.backdropFilter = 'blur(2px)';
    panel.innerHTML = `
      <aside class="bg-surface w-full max-w-md h-full overflow-y-auto
                    shadow-hero animate-slide-up"
             role="dialog" aria-modal="true"
             aria-label="Aide : ${this._esc(tips.title)}"
             style="border-left: 1px solid hsl(var(--border));
                    transform: translateX(100%); animation: slideInRight 220ms ease-out forwards;">
        <header class="px-6 pt-6 pb-4 border-b border-border sticky top-0 bg-surface z-10">
          <div class="flex items-start justify-between gap-3 mb-2">
            <div>
              <div class="hero-kicker mb-1">MINI-TUTO</div>
              <h2 class="font-display text-xl font-bold leading-tight">${this._esc(tips.title)}</h2>
              ${tips.lead ? `<div class="text-accent text-sm mt-1">${this._esc(tips.lead)}</div>` : ''}
            </div>
            <button id="help-close" class="text-text-muted hover:text-text text-2xl leading-none px-2"
                    aria-label="Fermer l’aide" title="Fermer (Échap)">×</button>
          </div>
        </header>
        <div class="px-6 py-5 space-y-5">
          ${(tips.sections || []).map(s => `
            <section>
              <div class="text-sm font-semibold mb-1.5">${this._esc(s.h)}</div>
              <p class="text-sm text-text-secondary leading-relaxed">${this._esc(s.p)}</p>
            </section>
          `).join('')}

          <div class="pt-4 border-t border-border">
            <button class="btn btn-secondary w-full" onclick="Tutorial.open(); Help.close();">
              ✨ Voir la visite guidée complète
            </button>
          </div>
        </div>
      </aside>
    `;

    // Ajoute l'animation CSS si pas déjà présente
    if (!document.getElementById('help-anim-css')) {
      const style = document.createElement('style');
      style.id = 'help-anim-css';
      style.textContent = `
        @keyframes slideInRight {
          from { transform: translateX(100%); }
          to   { transform: translateX(0); }
        }
      `;
      document.head.appendChild(style);
    }

    document.body.appendChild(panel);

    // Échap = ferme — écouteur posé à l'ouverture, retiré à la fermeture
    // (avant, il restait actif en permanence sur toute l'app).
    this._escListener = (e) => {
      if (e.key === 'Escape') this.close();
    };
    window.addEventListener('keydown', this._escListener);

    // Bind close
    panel.querySelector('#help-close').onclick = () => this.close();
    panel.addEventListener('click', (e) => {
      if (e.target === panel) this.close();
    });
  },

  close() {
    // Toutes les fermetures (×, clic à côté, Échap, bouton visite guidée)
    // passent ici : l'écouteur Échap est toujours retiré.
    if (this._escListener) {
      window.removeEventListener('keydown', this._escListener);
      this._escListener = null;
    }
    const p = document.getElementById('help-panel');
    if (p) {
      p.style.opacity = '0';
      p.style.transition = 'opacity 180ms';
      setTimeout(() => p.remove(), 180);
    }
  },

  /** Bind global : tout clic sur .help-trigger ouvre le panneau. */
  init() {
    document.body.addEventListener('click', (e) => {
      const btn = e.target.closest('.help-trigger');
      if (btn) {
        e.preventDefault();
        e.stopPropagation();
        this.show(btn.dataset.helpView);
      }
    }, true);
  },

  _esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    }[c]));
  },
};

window.addEventListener('DOMContentLoaded', () => Help.init());
