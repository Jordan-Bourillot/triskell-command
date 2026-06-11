/* Sidebar — sections repliables
 *
 * Pour chaque section colorée de la barre latérale (COCKPIT, BOÎTE MAIL,
 * BOÎTE À IDÉES, etc.), on transforme le titre en bouton cliquable avec
 * une petite flèche. Clic = on replie ou on déploie la section.
 *
 * L'état est mémorisé en localStorage, donc le visiteur retrouve son
 * choix au rechargement de la page.
 */
(function () {
  'use strict';

  const STORAGE_KEY = 'sidebar:collapsedSections';

  function loadCollapsed() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return new Set();
      const arr = JSON.parse(raw);
      return new Set(Array.isArray(arr) ? arr : []);
    } catch (e) {
      return new Set();
    }
  }

  function saveCollapsed(set) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(Array.from(set)));
    } catch (e) { /* quota plein → on ignore */ }
  }

  function slugify(text) {
    return (text || '')
      .toString()
      .normalize('NFD')
      .replace(/[̀-ͯ]/g, '')
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '');
  }

  function makeChevron() {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('fill', 'none');
    svg.setAttribute('stroke', 'currentColor');
    svg.setAttribute('stroke-width', '2.5');
    svg.setAttribute('stroke-linecap', 'round');
    svg.setAttribute('stroke-linejoin', 'round');
    svg.setAttribute('aria-hidden', 'true');
    svg.classList.add('nav-section-chevron');
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
    path.setAttribute('points', '6 9 12 15 18 9');
    svg.appendChild(path);
    return svg;
  }

  function setup() {
    const sidebar = document.getElementById('sidebar');
    if (!sidebar) return;
    const nav = sidebar.querySelector('nav');
    if (!nav) return;

    const collapsed = loadCollapsed();

    // Chaque section est un <div> enfant direct de <nav>.
    Array.from(nav.children).forEach((section) => {
      if (!(section instanceof HTMLElement)) return;
      const title = section.querySelector(':scope > .tracking-widest');
      // Tout ce que la section contient doit se replier avec elle :
      // les boutons d'écran, mais AUSSI les groupes repliables internes
      // (ex. « Outils de recherche » dans PROSPECTION : tête + items).
      const items = Array.from(section.querySelectorAll(
        ':scope > .nav-item, :scope > .nav-group-head, :scope > .nav-group-items, :scope > .nav-hint-wrap'
      ));
      // Pas de titre OU pas d'items à replier → on laisse tel quel.
      if (!title || items.length === 0) return;

      const label = (title.textContent || '').trim();
      const slug = slugify(label);
      if (!slug) return;

      // On transforme le <div> titre en <button>, en gardant les classes
      // de couleur/typo Tailwind. On entoure le texte d'un <span> pour le
      // garder à gauche, la flèche tout à droite.
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = title.className + ' nav-section-toggle';
      btn.dataset.section = slug;
      btn.setAttribute('aria-controls', `nav-section-${slug}`);

      const txt = document.createElement('span');
      txt.textContent = label;
      btn.appendChild(txt);
      btn.appendChild(makeChevron());

      title.replaceWith(btn);

      // On regroupe tous les items dans un container masquable.
      const wrap = document.createElement('div');
      wrap.className = 'nav-section-items';
      wrap.id = `nav-section-${slug}`;
      items.forEach((it) => wrap.appendChild(it));
      // Ré-ancre le wrap juste après le bouton (au cas où il y aurait
      // d'autres enfants entre les items, on les laisse à leur place).
      btn.insertAdjacentElement('afterend', wrap);

      const apply = (isCollapsed) => {
        btn.setAttribute('aria-expanded', isCollapsed ? 'false' : 'true');
        wrap.hidden = isCollapsed;
      };

      apply(collapsed.has(slug));

      btn.addEventListener('click', () => {
        const nowCollapsed = btn.getAttribute('aria-expanded') === 'true';
        apply(nowCollapsed);
        if (nowCollapsed) collapsed.add(slug);
        else collapsed.delete(slug);
        saveCollapsed(collapsed);
      });

      // Navigation vers un écran de cette section alors qu'elle est
      // repliée (Guide, recherche globale, lanceur, Cockpit…) : on
      // déplie automatiquement pour montrer l'élément actif — même
      // mécanique que le groupe « Outils de recherche ».
      new MutationObserver(() => {
        if (wrap.hidden && wrap.querySelector('.nav-item.active')) {
          apply(false);
          collapsed.delete(slug);
          saveCollapsed(collapsed);
        }
      }).observe(wrap, {
        subtree: true,
        attributes: true,
        attributeFilter: ['class'],
      });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', setup);
  } else {
    setup();
  }
})();
