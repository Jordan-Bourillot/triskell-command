/* Help — mini-tuto contextuel sous chaque vue.
 *
 * Usage côté vue :
 *   1. Inclure le bouton "?" dans le hero : Help.button('morning')
 *   2. Help.init() est appelé au DOMContentLoaded (binding global)
 *   3. Au clic → panneau latéral droit avec les tips de cette vue
 *
 * Pour ajouter une vue : ajouter une entrée dans Help.tips ci-dessous.
 * Pas de jargon, ton parlant, focus sur "qu'est-ce que je peux faire ici".
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
          p: "Tu y vois en 5 minutes ce qui s'est passé hier (mails envoyés, " +
             "réponses reçues), ce qui t'attend aujourd'hui (brouillons, " +
             "réponses à traiter), et les soucis éventuels."
        },
        {
          h: '🎯 Le bloc « Priorité du jour »',
          p: "L'app calcule automatiquement ce qui est le plus rentable à " +
             "traiter en premier. En général : prospects intéressés > " +
             "brouillons à valider > réponses à trier."
        },
        {
          h: '🔗 Le bloc LinkedIn',
          p: "Si l'IA a préparé des relances LinkedIn, elles apparaissent ici. " +
             "3 clics par fiche : copier le message, ouvrir le profil LinkedIn, " +
             "marquer fait. Si tu as Phantombuster, bouton « ⚡ Tout envoyer »."
        },
        {
          h: '⌨️ Raccourcis utiles',
          p: "F12 = ouvrir Allô Claude · Ctrl+T = changer de thème · " +
             "Ctrl+K = lanceur Spotlight des outils Triskell · " +
             "Ctrl+Shift+M = composer un nouveau mail."
        },
      ],
    },

    // ---------------- Auto-pilote ----------------
    autopilot: {
      title: 'Auto-pilote',
      lead: 'La chaîne complète, sous tes ordres.',
      sections: [
        {
          h: '🎯 Ce que fait l\'auto-pilote',
          p: "Il pioche dans tes prospects existants, élimine ceux à ne pas " +
             "recontacter, rédige un mail unique pour chacun avec l'IA, le " +
             "fait relire par une 2è IA, puis envoie (ou met en brouillon " +
             "si tu préfères valider à la main)."
        },
        {
          h: '⚠️ Il ne cherche PAS de nouveaux prospects',
          p: "L'auto-pilote travaille uniquement sur ta base existante. Pour " +
             "trouver de nouveaux contacts, utilise Le Chasseur (entreprises), " +
             "L'Éclaireur (sites web) ou Obélisk (créateurs sur 9 plateformes)."
        },
        {
          h: '🎛️ Les 5 maillons',
          p: "Cherche (pioche) → Trie (élimine doublons / déjà contactés / " +
             "clients) → Rédige (IA + bon modèle) → Relit (2è IA avec note " +
             "sur 10) → Envoie (ou met en brouillon). Les 3 derniers ont un " +
             "interrupteur Auto / Manuel."
        },
        {
          h: '✅ Auto vs Manuel sur chaque maillon',
          p: "Auto = ça part tout seul. Manuel sur « Rédige » = aucun mail " +
             "écrit. Manuel sur « Relit » = la 2è IA ne note rien. Manuel " +
             "sur « Envoie » = chaque mail est mis en brouillon pour que " +
             "tu valides toi-même dans la page Brouillons à valider."
        },
        {
          h: '🌙 Pipeline auto à heure fixe',
          p: "Coche « Pipeline auto » et choisis l'heure (3h par défaut, " +
             "heure de Paris). Le robot tourne tout seul à cette heure-là " +
             "chaque jour, même si tu n'es pas connecté. Tu te lèves, ton " +
             "cockpit est déjà rempli."
        },
        {
          h: '🛑 Bouton Arrêter',
          p: "Pendant un run (lancé à la main ou nocturne), le bouton rouge " +
             "« Arrêter » coupe la chaîne. Les mails déjà envoyés restent " +
             "envoyés ; le reste est abandonné."
        },
        {
          h: '📮 Brouillons à valider',
          p: "Quand l'auto-pilote met un mail en brouillon, il atterrit " +
             "dans la page « Brouillons à valider » (barre de gauche). Le " +
             "bandeau en haut de la page Auto-pilote te dit combien sont " +
             "en attente et te renvoie direct là-bas."
        },
      ],
    },

    // ---------------- Replies (À la main) ----------------
    replies: {
      title: 'À la main — Réponses entrantes',
      lead: 'Les prospects qui te répondent, déjà triés.',
      sections: [
        {
          h: '🎨 Les 5 catégories',
          p: "L'IA classe chaque réponse en : intéressé · pas maintenant · " +
             "refus · désinscription · à trier. Filtre avec les chips en haut."
        },
        {
          h: '✉️ Réponse suggérée',
          p: "L'IA prépare souvent un brouillon de réponse. Tu peux l'envoyer " +
             "tel quel, le modifier, l'annuler, ou attendre l'envoi auto " +
             "(selon ton mode dans Réglages)."
        },
        {
          h: '+ Créer projet client',
          p: "Bouton vert sur les « intéressé ». Crée une carte projet en " +
             "statut Briefing dans Clients (kanban). Si la bascule auto est " +
             "activée dans Réglages, ça se fait tout seul."
        },
        {
          h: '✉ Répondre directement',
          p: "Bouton « Répondre » sur chaque carte : ouvre le composer mail " +
             "intégré, déjà pré-rempli avec le destinataire et l'objet. " +
             "Tu peux mettre en forme (HTML), ajouter des pièces jointes, " +
             "programmer l'envoi plus tard ou enregistrer en brouillon."
        },
      ],
    },

    // ---------------- Drafts ----------------
    drafts: {
      title: 'Brouillons à valider',
      lead: 'Le sas de contrôle de tout ce que prépare l\'app.',
      sections: [
        {
          h: '📝 Ce qui atterrit ici',
          p: "Tous les mails préparés par l'app en mode validation : premiers " +
             "contacts (auto-pilote), relances, réponses aux entrants, suivi " +
             "après vente, recyclage de dormants. Tu corriges si besoin et " +
             "tu cliques « Approuver »."
        },
        {
          h: '✓ Approuver / ✗ Rejeter',
          p: "Approuver = envoi immédiat via SMTP. Rejeter = supprime le " +
             "brouillon (le prospect ne reçoit rien)."
        },
        {
          h: '✏️ Édition libre',
          p: "Tu peux modifier le sujet et le corps avant d'approuver. Les " +
             "modifs sont sauvées en local."
        },
      ],
    },

    // ---------------- Funnel ----------------
    funnel: {
      title: 'Conversions',
      lead: 'Tes taux de réponse, intérêt, et gain en un coup d\'œil.',
      sections: [
        {
          h: '5 étapes du tunnel',
          p: "Prospects → Envoyés → Réponses → Intéressés → Clients gagnés. " +
             "Tu vois où ça coince (taux qui chute) et où ça marche."
        },
        {
          h: 'Filtres période & type',
          p: "7 jours / 30 jours / 90 jours / tout. Type : créateurs (Obelisk) " +
             "/ B2B local (Sirene) / tous mélangés."
        },
        {
          h: 'Comparer plusieurs variantes',
          p: "Pour comparer plusieurs sujets de mail entre eux, va dans " +
             "Réglages → Test A/B des sujets."
        },
      ],
    },

    // ---------------- Clients ----------------
    clients: {
      title: 'Clients — Kanban',
      lead: 'De la commande à la clôture.',
      sections: [
        {
          h: '4 colonnes',
          p: "Briefing (pas encore commencé) · En cours · Livré · Clôturé. " +
             "Tu fais glisser les cartes en cliquant les flèches ‹ ›."
        },
        {
          h: '⚡ Bouton « Livrer »',
          p: "Sur les cartes Briefing/En cours qui ont un email client : " +
             "envoie immédiatement le kit de livraison du produit (mail " +
             "bienvenue + accès + relances de suivi). Le contenu vient de " +
             "Réglages → Éditer les kits."
        },
        {
          h: '💳 Cartes créées automatiquement',
          p: "Quand un paiement Stripe ou AppSumo arrive, ou quand un prospect " +
             "intéressé est basculé, une carte apparaît ici toute seule. " +
             "(Cf. Réglages → Stripe / Bascule auto)."
        },
        {
          h: '+ Nouveau projet manuel',
          p: "Pour un projet créé hors-tunnel (recommandation, contact direct, " +
             "etc.), bouton « + Nouveau projet » en haut à droite."
        },
      ],
    },

    // ---------------- Phare ----------------
    phare: {
      title: 'Le Phare — SEO autonome',
      lead: 'Une agence SEO qui tourne toute seule.',
      sections: [
        {
          h: '4 onglets internes',
          p: "Écosystème (vue de tous tes sites) · Site (un site précis) · " +
             "Bac à PRs (modifications proposées par l'IA, à valider) · " +
             "Bulletins (rapports mensuels PDF)."
        },
        {
          h: '🤖 8 agents MVP + 11 modules avancés',
          p: "Audit, mots-clés, backlinks, schema, snippet hunter, refresh, " +
             "GBP, programmatic SEO, CRO, A/B test scientifique, " +
             "monitoring de marque, veille algo Google… Tout tourne en " +
             "automatique."
        },
        {
          h: '✋ Tu valides avant push',
          p: "Aucune modif n'arrive en prod sans ton OK. Toutes les actions " +
             "passent par le « Bac à PRs »."
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
             "mail de bienvenue + livrables (URLs, codes d'accès) + relances " +
             "de suivi (J+3 « ça va ? », J+14 astuce, J+30 demande d'avis)."
        },
        {
          h: '🔧 Variables disponibles',
          p: "{client_name}, {product_name}, {deliverables_list}, {signature}. " +
             "Elles sont remplacées automatiquement dans les sujets et corps."
        },
        {
          h: '👁 Aperçu live',
          p: "Bouton « Rafraîchir l'aperçu » : voit exactement ce que recevra " +
             "le client, avec les variables substituées par un client de test."
        },
        {
          h: '📦 Kit générique (_default)',
          p: "Si un produit acheté n'a pas de kit dédié, c'est ce kit qui part. " +
             "Personnalise-le pour avoir un fallback propre."
        },
      ],
    },

    // ---------------- Health ----------------
    health: {
      title: 'Santé du système',
      lead: 'Tes 10 outils autonomes en temps réel.',
      sections: [
        {
          h: '🟢🟡🔴 Pastilles de santé',
          p: "Vert = tourne sans erreur · Jaune = tourne mais avec erreurs " +
             "récentes · Rouge = à l'arrêt. Refresh auto toutes les 15 sec."
        },
        {
          h: '📊 Délivrabilité',
          p: "Envois et réponses sur 24h et 7j, taux de réponse calculé. " +
             "Si SMTP/IMAP pas configuré, alerte affichée."
        },
        {
          h: '🔍 Détail des workers',
          p: "Chaque carte montre : statut (running/à l'arrêt), dernière " +
             "exécution (« il y a X min »), compteurs du dernier cycle, " +
             "et les erreurs s'il y en a."
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
          p: "Bouton « + Nouvelle campagne ». Donne un nom (ex : « Premier " +
             "contact froid ») + 2 à 5 variantes de sujet, une par ligne. " +
             "L'app distribue équitablement les envois."
        },
        {
          h: '📈 Verdict statistique',
          p: "Au bout de ~30 envois par variante, l'app calcule un Z-test des " +
             "proportions à 95%. Le gagnant (👑) n'est désigné que si " +
             "l'écart est statistiquement significatif (pas du flair)."
        },
        {
          h: '✏️ Variables dans les sujets',
          p: "Tu peux utiliser {company_name}, {name}, {city}. Elles sont " +
             "substituées au moment de l'envoi."
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
          p: "Clair, intermédiaire (graphite chaud), sombre. Tu peux aussi " +
             "cycler avec Ctrl+T."
        },
        {
          h: '🤖 Services IA',
          p: "Tes clés API (Anthropic, Google, OpenAI…). Stockées chiffrées " +
             "en local et dans la base partagée. Recommandé : Google Gemini " +
             "(gratuit jusqu'à 1500 req/jour)."
        },
        {
          h: '✉️ Compte mail',
          p: "Identifiants SMTP (envoi) + IMAP (réception). Pour Gmail, " +
             "génère un mot de passe d'application dans tes paramètres Google."
        },
        {
          h: '💳 Stripe + 🥭 AppSumo',
          p: "Active le polling Stripe pour que les paiements créent " +
             "automatiquement les projets clients. Pour AppSumo, déploie la " +
             "Netlify Function fournie (cf. netlify_functions/README.md)."
        },
        {
          h: '🔗 Phantombuster',
          p: "DM LinkedIn auto (~70€/mois) : clé API + ID du Phantom " +
             "« LinkedIn Message Sender »."
        },
        {
          h: '👁 Tracking d\'ouvertures',
          p: "Coche pour ajouter un pixel transparent dans tes mails. Demande " +
             "de déployer une Netlify Function (~5 min, gratuit)."
        },
        {
          h: '🚪 Bascule auto + Livraison',
          p: "Bascule = quand un intéressé devient projet client (3 modes). " +
             "Livraison = éditer les kits par produit (mail bienvenue + " +
             "livrables + suivis)."
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
              title="Mini-tuto de cette section">
        ?
      </button>
    `;
  },

  /** Affiche le panneau latéral pour la vue donnée. */
  show(viewId) {
    const tips = this.tips[viewId];
    if (!tips) return;

    // Ferme un panneau précédent s'il existe
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
                    title="Fermer (Échap)">×</button>
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

    // Bind close
    panel.querySelector('#help-close').onclick = () => this.close();
    panel.addEventListener('click', (e) => {
      if (e.target === panel) this.close();
    });
  },

  close() {
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
    // Échap = ferme
    window.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') this.close();
    });
  },

  _esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    }[c]));
  },
};

window.addEventListener('DOMContentLoaded', () => Help.init());
