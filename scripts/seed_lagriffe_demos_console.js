// SEED DES 21 DÉMOS MÉTIER LAGRIFFE — à exécuter dans la console JS
// (F12) sur ton app `command.triskell-studio.fr` quand tu es loggé.
//
// Comment l'utiliser :
//   1. Ouvre command.triskell-studio.fr (assure-toi d'être connecté).
//   2. F12 → onglet « Console ».
//   3. Copie-colle tout ce fichier dans la console.
//   4. Appuie sur Entrée. Les 21 démos s'ajoutent à ton catalogue.
//
// Idempotent : relancer ne crée pas de doublon (save_product upsert par id).

(async () => {
  const demos = [
    { name: "Démo brasserie — La Rose des Vents", url: "https://brasserie-la-rose-des-vents.netlify.app",
      keywords: "brasserie, bar à bières, microbrasserie, taverne, pub, débit de boissons, bar artisanal" },
    { name: "Démo services à la personne — Ingrid Services", url: "https://ingrid-services.fr",
      keywords: "ménage, services à la personne, aide à domicile, nettoyage, entretien maison, repassage, garde d'enfants" },
    { name: "Démo boutique vape — Vaporlux", url: "https://vaporlux.triskell-studio.fr",
      keywords: "vape, cigarette électronique, e-cigarette, vapoteur, e-liquide, CBD, boutique vape, vape shop" },
    { name: "Démo atelier sculpteur — Missor", url: "https://missor.triskell-studio.fr",
      keywords: "sculpteur, sculpture, fonderie, fondeur d'art, atelier d'art, bronze, statuaire, artisan d'art" },
    { name: "Démo influenceur / créateur — Anyme", url: "https://anyme.triskell-studio.fr",
      keywords: "influenceur, streamer, créateur de contenu, content creator, twitch, youtube, instagram, tiktok, personal branding" },
    { name: "Démo garagiste — Triskell", url: "https://garage.triskell-studio.fr",
      keywords: "garagiste, garage, mécanicien, mécanique auto, réparation automobile, carrosserie, entretien voiture, dépannage, automobile" },
    { name: "Démo paysagiste — Triskell", url: "https://paysagiste.triskell-studio.fr",
      keywords: "paysagiste, jardinier, espaces verts, aménagement paysager, jardin, entretien jardin, taille, élagage, terrasse, gazon" },
    { name: "Démo thérapeute / bien-être — Graphothérapeute", url: "https://graphotherapeute.triskell-studio.fr",
      keywords: "graphothérapeute, graphothérapie, yoga, professeur de yoga, orthophoniste, orthophonie, sophrologue, sophrologie, naturopathe, hypnothérapeute, médecine douce, bien-être, thérapeute, praticien, ostéopathe, réflexologue" },
    { name: "Démo boutique vape — Variante moderne", url: "https://vape.triskell-studio.fr",
      keywords: "vape, cigarette électronique, e-cigarette, vapoteur, e-liquide, CBD, boutique vape, vape shop" },
    { name: "Démo plombier — Triskell", url: "https://plombier.triskell-studio.fr",
      keywords: "plombier, plomberie, chauffagiste, dépannage plomberie, sanitaire, fuite d'eau, chauffage, installation sanitaire, robinetterie" },
    { name: "Démo peintre — Triskell", url: "https://peintre.triskell-studio.fr",
      keywords: "peintre, peinture, peintre en bâtiment, ravalement, papier peint, décoration murale, façade, peinture intérieure, peinture extérieure" },
    { name: "Démo plaquiste — Triskell", url: "https://plaquiste.triskell-studio.fr",
      keywords: "plaquiste, placo, cloisons, isolation, faux plafond, doublage, BA13, aménagement intérieur" },
    { name: "Démo maçon — Triskell", url: "https://macon.triskell-studio.fr",
      keywords: "maçon, maçonnerie, gros œuvre, construction, fondations, rénovation, BTP, entrepreneur, terrassement" },
    { name: "Démo carreleur — Triskell", url: "https://carreleur.triskell-studio.fr",
      keywords: "carreleur, carrelage, faïence, pose carrelage, salle de bain, sol, mosaïque, dallage" },
    { name: "Démo électricien — Triskell", url: "https://electricien.triskell-studio.fr",
      keywords: "électricien, électricité, installation électrique, dépannage électrique, tableau électrique, mise aux normes, courant fort, courant faible, domotique" },
    { name: "Démo boulangerie — Le Fournil de Goulven", url: "https://boulangerie.triskell-studio.fr",
      keywords: "boulanger, boulangerie, pain, viennoiserie, pâtisserie, baguette, artisan boulanger, fournil, pâtissier" },
    { name: "Démo restaurant — La Belle Époque", url: "https://restaurant.triskell-studio.fr",
      keywords: "restaurant, restaurateur, cuisine, brasserie, traiteur, bistrot, gastronomie, cuisine traditionnelle, menu, carte" },
    { name: "Démo salon de coiffure — Maison Lou", url: "https://salon-coiffure.triskell-studio.fr",
      keywords: "coiffeur, coiffeuse, salon de coiffure, coupe, coloration, balayage, mèches, brushing, soin capillaire" },
    { name: "Démo barbier — L'Atelier de Brieuc", url: "https://salons.triskell-studio.fr",
      keywords: "barbier, barber shop, barberie, rasage, taille de barbe, salon de barbier, soin homme, coupe homme" },
    { name: "Démo restaurant cubain — Clandestino", url: "https://clandestino.triskell-studio.fr",
      keywords: "restaurant cubain, cuisine latino, world food, bar à cocktails, restaurant à thème, tapas, ambiance, rhum, latino" },
    { name: "Démo tatoueur — Despiertos", url: "https://despiertos.triskell-studio.fr",
      keywords: "tatoueur, tatouage, tattoo, salon de tatouage, tattoo artist, piercing, body art, ink, atelier tatouage" },
  ];

  let ok = 0, fail = 0;
  console.log(`📥 Seed de ${demos.length} démos métier…`);
  for (const d of demos) {
    const payload = {
      name:           d.name,
      tagline:        "",
      kind:           "demo",
      category:       "sites",
      buy_url:        d.url,
      keywords:       d.keywords,
      prospect_pitch: "Démo prête à montrer aux prospects de ce métier : preuve visuelle directe de ce qu'on peut leur faire.",
    };
    try {
      const r = await App.api.catalog_save_product(payload);
      if (r && r.ok) {
        ok++;
        console.log(`  ✅ ${d.name}`);
      } else {
        fail++;
        console.warn(`  ❌ ${d.name}`, r);
      }
    } catch (e) {
      fail++;
      console.error(`  💥 ${d.name}`, e);
    }
  }
  console.log(`\nTerminé : ${ok} ajoutées, ${fail} échouées.`);
})();
