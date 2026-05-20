/* DailyQuote — citation business du jour, affichée à droite de "Bonjour Jordan"
 *
 * Une seule citation par journée calendaire. Le choix est déterministe :
 * basé sur (année, jour de l'année), donc identique au refresh, change à minuit.
 *
 * Thèmes : business, argent, exécution, vente, long-terme, discipline.
 */

const DailyQuote = {
  _stylesInjected: false,

  quotes: [
    { t: "Ton client n'achète pas ce que tu vends. Il achète une meilleure version de lui-même.", a: "Seth Godin" },
    { t: "Le risque vient de ne pas savoir ce qu'on fait.", a: "Warren Buffett" },
    { t: "Les gens ne savent pas ce qu'ils veulent jusqu'à ce qu'on leur montre.", a: "Steve Jobs" },
    { t: "Construis quelque chose dont les gens veulent.", a: "Paul Graham" },
    { t: "Le marché paie pour résoudre des problèmes, pas pour ton temps.", a: "Naval Ravikant" },
    { t: "Tout ce qui se mesure s'améliore.", a: "Peter Drucker" },
    { t: "Sois cupide quand les autres ont peur, aie peur quand les autres sont cupides.", a: "Warren Buffett" },
    { t: "Si tu n'achètes pas du temps avec ton argent, tu travailles pour de l'argent.", a: "Naval Ravikant" },
    { t: "Le pauvre travaille pour l'argent. Le riche fait travailler l'argent.", a: "Robert Kiyosaki" },
    { t: "Plus tu en sais, moins tu spécules.", a: "Charlie Munger" },
    { t: "Le prix est ce que tu paies. La valeur est ce que tu reçois.", a: "Warren Buffett" },
    { t: "Tes revenus dépassent rarement ton développement personnel.", a: "Jim Rohn" },
    { t: "La discipline égale la liberté.", a: "Jocko Willink" },
    { t: "Sois le meilleur ou le moins cher. Jamais entre les deux.", a: "Jack Welch" },
    { t: "Soit tu construis ton rêve, soit quelqu'un te paiera pour construire le sien.", a: "Tony Gaskins" },
    { t: "L'excellence n'est pas un acte, c'est une habitude.", a: "Aristote" },
    { t: "L'intérêt composé est la huitième merveille du monde.", a: "Albert Einstein" },
    { t: "Tu n'as pas besoin d'avoir raison. Tu as juste besoin de ne pas avoir tort.", a: "Howard Marks" },
    { t: "Penser à long terme est l'avantage compétitif le plus rare.", a: "Jeff Bezos" },
    { t: "Tombe amoureux du problème, pas de la solution.", a: "Uri Levine" },
    { t: "Les meilleures idées viennent des problèmes que tu vis toi-même.", a: "Brian Chesky" },
    { t: "Si tu n'es pas gêné par ta première version, tu as lancé trop tard.", a: "Reid Hoffman" },
    { t: "Le plus grand risque, c'est de ne prendre aucun risque.", a: "Mark Zuckerberg" },
    { t: "Tu ne reçois pas ce que tu mérites. Tu reçois ce que tu négocies.", a: "Chester Karrass" },
    { t: "Tes clients mécontents sont ta plus grande source d'apprentissage.", a: "Bill Gates" },
    { t: "Vends à dix personnes qui t'adorent, pas à mille qui t'ignorent.", a: "Kevin Kelly" },
    { t: "Construis du capital, pas un salaire.", a: "Naval Ravikant" },
    { t: "Le talent, c'est avoir envie de faire quelque chose.", a: "Jacques Brel" },
    { t: "Le luxe, c'est le détail.", a: "Coco Chanel" },
    { t: "Ce qu'on fait chaque jour compte plus que ce qu'on fait de temps en temps.", a: "Gretchen Rubin" },
    { t: "L'astuce n'est pas de gagner. C'est de ne jamais perdre.", a: "Naval Ravikant" },
    { t: "Les bonnes entreprises surfent la vague. Les grandes la créent.", a: "Tony Robbins" },
    { t: "Tu n'as pas besoin de plus d'idées. Tu as besoin d'exécuter celles que tu as.", a: "James Clear" },
    { t: "Personne ne se souvient du second.", a: "Walter Hagen" },
    { t: "Les gens n'achètent pas un produit. Ils achètent une histoire.", a: "Donald Miller" },
    { t: "« Non » veut souvent dire « pas maintenant ».", a: "Tom Hopkins" },
    { t: "Ce que tu acceptes, tu l'amplifies.", a: "James Clear" },
    { t: "Concentre-toi sur la flèche, pas sur la cible.", a: "Bruce Lee" },
    { t: "Si tu rates les étoiles, tu atterriras peut-être sur la lune.", a: "Les Brown" },
    { t: "Ton meilleur investissement, c'est toujours toi-même.", a: "Warren Buffett" },
    { t: "Si tu n'apprends plus, tu meurs lentement.", a: "Mark Zuckerberg" },
    { t: "L'opportunité a toujours l'air de travail. C'est pour ça que la plupart la ratent.", a: "Thomas Edison" },
    { t: "Mieux vaut un produit imparfait lancé qu'un produit parfait jamais sorti.", a: "Reid Hoffman" },
    { t: "Ce qui te distingue n'est pas ce que tu sais — c'est ce que tu en fais.", a: "Anonyme" },
    { t: "L'argent est un mauvais maître mais un excellent serviteur.", a: "Francis Bacon" },
    { t: "Une stratégie sans exécution est une hallucination.", a: "Thomas Edison" },
    { t: "Préfère la lente progression à l'arrêt confortable.", a: "Anonyme" },
    { t: "Tu peux faire tout ce que tu veux. Pas tout en même temps.", a: "Oprah Winfrey" },
    { t: "Lance, mesure, apprends. Recommence.", a: "Eric Ries" },
    { t: "Quand tout le monde court, marche.", a: "Proverbe" },
    { t: "Un client gagné par le prix est perdu par le prix.", a: "Proverbe commercial" },
    { t: "Aucun vent n'est favorable à celui qui ne sait pas où il va.", a: "Sénèque" },
    { t: "L'expert n'a pas plus de bonnes idées que les autres — il en a juste écarté beaucoup de mauvaises.", a: "Charlie Munger" },
  ],

  /** Citation du jour — identique sur les 24h. */
  today() {
    const d = new Date();
    const startOfYear = new Date(d.getFullYear(), 0, 0);
    const dayOfYear = Math.floor((d - startOfYear) / 86_400_000);
    // Multiplicateur premier pour bien étaler la rotation
    const idx = ((dayOfYear * 31) + d.getFullYear()) % this.quotes.length;
    return this.quotes[idx >= 0 ? idx : 0];
  },

  _injectStyles() {
    if (this._stylesInjected) return;
    this._stylesInjected = true;
    const s = document.createElement('style');
    s.id = 'daily-quote-styles';
    s.textContent = `
      .daily-quote {
        position: relative;
        max-width: 400px;
        padding: 16px 22px 14px 24px;
        border-left: 2px solid hsl(var(--accent) / 0.5);
        background: linear-gradient(135deg,
          hsl(var(--surface-elevated) / 0.55),
          hsl(var(--surface-elevated) / 0.25));
        border-radius: 0 12px 12px 0;
        margin-left: auto;
        backdrop-filter: blur(6px);
      }
      .daily-quote-mark {
        position: absolute;
        top: -2px; left: 10px;
        font-family: Georgia, 'Times New Roman', serif;
        font-size: 46px;
        line-height: 1;
        color: hsl(var(--accent) / 0.32);
        font-weight: 700;
        pointer-events: none;
        user-select: none;
      }
      .daily-quote-text {
        font-family: 'Domaine Display', Georgia, 'Times New Roman', serif;
        font-size: 14.5px;
        font-style: italic;
        line-height: 1.5;
        color: hsl(var(--text));
        margin: 0 0 8px 0;
        text-wrap: pretty;
      }
      .daily-quote-author {
        display: block;
        font-style: normal;
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 2.5px;
        text-transform: uppercase;
        color: hsl(var(--text-muted));
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      }
      @media (max-width: 768px) {
        .daily-quote {
          max-width: 100%;
          margin-left: 0;
        }
      }
    `;
    document.head.appendChild(s);
  },

  /** Renvoie le bloc HTML prêt à insérer. */
  renderHTML() {
    this._injectStyles();
    const q = this.today();
    const esc = (s) => String(s).replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
    return `
      <aside class="daily-quote" aria-label="Citation du jour">
        <span class="daily-quote-mark" aria-hidden="true">&ldquo;</span>
        <p class="daily-quote-text">${esc(q.t)}</p>
        <cite class="daily-quote-author">— ${esc(q.a)}</cite>
      </aside>
    `;
  },
};

window.DailyQuote = DailyQuote;
