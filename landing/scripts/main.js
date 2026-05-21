/* ============================================================
   Triskell Command — landing publique
   - Sélecteur 3 thèmes (light / mid / dark)
   - Persistance localStorage
   - Au tout premier chargement : light par défaut (pas de
     respect du prefers-color-scheme OS, par décision produit).
   - Transition fluide entre thèmes (transition CSS sur les couleurs).
   ============================================================ */

(() => {
  const STORAGE_KEY = "triskell-command-theme";
  const VALID = ["light", "mid", "dark"];

  const root = document.body;
  const buttons = document.querySelectorAll("[data-theme-set]");

  function apply(theme) {
    if (!VALID.includes(theme)) theme = "light";
    root.setAttribute("data-theme", theme);
    buttons.forEach((b) => {
      b.classList.toggle("is-active", b.dataset.themeSet === theme);
    });
    try {
      localStorage.setItem(STORAGE_KEY, theme);
    } catch (e) {
      /* localStorage indisponible (mode privé) : on ignore */
    }
  }

  // 1. Charge le thème mémorisé. Si rien : light par défaut.
  let initial = "light";
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved && VALID.includes(saved)) initial = saved;
  } catch (e) { /* ignore */ }
  apply(initial);

  // 2. Branche les boutons
  buttons.forEach((b) => {
    b.addEventListener("click", () => apply(b.dataset.themeSet));
  });

  // 3. Smooth scroll pour les ancres internes
  document.querySelectorAll('a[href^="#"]').forEach((a) => {
    a.addEventListener("click", (e) => {
      const id = a.getAttribute("href").slice(1);
      if (!id) return;
      const target = document.getElementById(id);
      if (!target) return;
      e.preventDefault();
      target.scrollIntoView({ behavior: "smooth", block: "start" });
      history.replaceState(null, "", `#${id}`);
    });
  });

  // 4. Détecte un submit waitlist sans backend connecté → préviens proprement.
  const form = document.querySelector(".waitlist-form");
  if (form && form.action.includes("REPLACE_ME")) {
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      alert(
        "Liste d'attente pas encore branchée — on configure Formspree juste " +
        "avant la mise en ligne."
      );
    });
  }
})();
