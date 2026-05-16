/* Triskell Command — orchestrateur UI web
 * - Bootstrap pywebview (boot du backend Python)
 * - Routing simple entre vues (sidebar)
 * - Gestion du thème (3 modes)
 * - Helpers d'API
 */

const App = {
  api: null,
  currentView: 'morning',
  currentUser: {},   // {first_name, full_name, email} — rempli au boot

  // ---- Wait for API to be ready ----
  // Stratégie :
  // 1. Si on est dans pywebview (fenêtre native locale), attendre window.pywebview.api
  // 2. Sinon (navigateur Chrome/Firefox/mobile), utiliser un Proxy HTTP qui
  //    appelle POST /api/<method_name> sur le serveur FastAPI.
  // Détection : on attend un peu pywebview, sinon on bascule HTTP.
  // L'interface pour le reste du code est identique : App.api.method_name(payload).
  async waitForApi(timeoutMs = 1500) {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
      if (window.pywebview && window.pywebview.api) {
        this.api = window.pywebview.api;
        this.apiMode = 'pywebview';
        return true;
      }
      await new Promise(r => setTimeout(r, 80));
    }
    // Pas de pywebview détecté → mode HTTP
    this.api = this._buildHttpApiProxy();
    this.apiMode = 'http';
    console.info('Mode API : HTTP (FastAPI). pywebview non détecté.');
    return true;
  },

  // ---- Méthodes desktop-only : interception côté front en mode HTTP ----
  // Ces méthodes existent côté Api Python mais sont conçues pour pywebview
  // local (lancer un .exe, ouvrir un browser sur la machine). Sur le serveur
  // HTTP, les appeler ne ferait rien d'utile. On fait l'action côté navigateur
  // à la place (window.open, mailto:, etc.).
  _httpDesktopFallback(method, payload) {
    const p = payload || {};
    if (method === 'open_url') {
      if (p.url) window.open(p.url, '_blank', 'noopener,noreferrer');
      return { ok: true, client_action: 'open_url' };
    }
    if (method === 'compose_mail') {
      // Construit un mailto: et l'ouvre dans le client mail par défaut
      // du device de l'utilisateur (Gmail web, Apple Mail, etc.)
      const join = v => Array.isArray(v) ? v.filter(Boolean).join(',') : String(v || '');
      const params = [];
      if (p.subject) params.push('subject=' + encodeURIComponent(p.subject));
      if (p.body)    params.push('body=' + encodeURIComponent(p.body));
      if (p.cc)      params.push('cc=' + encodeURIComponent(join(p.cc)));
      if (p.bcc)     params.push('bcc=' + encodeURIComponent(join(p.bcc)));
      const url = `mailto:${join(p.to)}` + (params.length ? '?' + params.join('&') : '');
      window.location.href = url;
      return { ok: true, client_action: 'mailto' };
    }
    if (method === 'open_teddy_mail' || method === 'launch_app') {
      // Pas de Teddy Mail / .exe sur le serveur → si on a une URL, l'ouvrir.
      if (p.url) {
        window.open(p.url, '_blank', 'noopener,noreferrer');
        return { ok: true, client_action: 'open_url' };
      }
      return {
        ok: false,
        error: 'Cette action est disponible uniquement en mode desktop local. ' +
               'Lance Triskell Command sur ton PC pour ouvrir cette app.',
      };
    }
    return null; // pas un fallback → laisse passer l'appel HTTP normal
  },

  // ---- Proxy HTTP : App.api.foo(payload) → POST /api/foo body=payload ----
  _buildHttpApiProxy() {
    const desktopOnlyMethods = new Set([
      'open_url', 'compose_mail', 'open_teddy_mail', 'launch_app',
    ]);
    return new Proxy({}, {
      get: (_target, method) => {
        // Évite les pièges : si le code fait `if (App.api.foo)` ou JSON.stringify(App.api),
        // on doit renvoyer undefined pour les symboles spéciaux.
        if (typeof method !== 'string') return undefined;
        if (method === 'then' || method === 'toJSON') return undefined;
        // Méthodes desktop-only : court-circuit côté navigateur
        if (desktopOnlyMethods.has(method)) {
          return async (payload) => this._httpDesktopFallback(method, payload);
        }
        return async (payload) => {
          // Mode démo : intercepte avant tout appel réseau
          if (typeof DemoMode !== 'undefined' && DemoMode.isOn && DemoMode.isOn()) {
            const intercepted = DemoMode.intercept(method, payload);
            if (intercepted.handled) return intercepted.result;
          }
          const body = (payload === undefined || payload === null) ? null : JSON.stringify(payload);
          const t0 = performance.now();
          let r;
          try {
            r = await fetch(`/api/${method}`, {
              method: 'POST',
              headers: body ? { 'Content-Type': 'application/json' } : {},
              body,
              credentials: 'same-origin',
            });
          } catch (netErr) {
            // Erreur réseau brute (offline, CORS, DNS, etc.)
            if (typeof HealthCheck !== 'undefined') {
              HealthCheck.record({ kind: 'api_network', method, msg: String(netErr) });
              HealthCheck.toast('Réseau indisponible',
                `Impossible de joindre /api/${method}. Le serveur tourne ?`, 'error');
            }
            throw netErr;
          }
          const elapsed = Math.round(performance.now() - t0);
          // Session expirée ou pas connecté → rediriger vers le login
          if (r.status === 401) {
            if (!window.location.pathname.endsWith('/login.html')) {
              window.location.href = '/login.html';
            }
            throw new Error('auth_required');
          }
          if (!r.ok) {
            let detail = '';
            try { detail = JSON.stringify(await r.json()); } catch {}
            if (typeof HealthCheck !== 'undefined') {
              HealthCheck.record({ kind: 'api_http_error', method, status: r.status, detail, elapsed });
            }
            throw new Error(`API ${method} ${r.status} ${detail}`);
          }
          // Log les appels lents (>3 sec) pour anticiper les soucis de perf
          if (elapsed > 3000 && typeof HealthCheck !== 'undefined') {
            HealthCheck.record({ kind: 'api_slow', method, elapsed_ms: elapsed });
          }
          return r.json();
        };
      },
    });
  },

  async init() {
    const ready = await this.waitForApi();
    if (!ready) {
      console.warn('pywebview API non disponible — mode standalone (preview).');
    }

    // Applique le thème depuis settings
    await this.applyThemeFromSettings();

    // Démarre les workers backend
    if (this.api) {
      try { await this.api.boot(); } catch (e) { console.warn('boot:', e); }
    }

    // Onboarding au premier lancement (si needs_onboarding) + charge currentUser
    if (typeof Onboarding !== 'undefined') {
      try { await Onboarding.checkAndShow(); } catch (e) {}
    }
    // Override avec l'identité du cookie de session — permet à Jordan et
    // Thomas d'avoir chacun leur prénom affiché même quand ils partagent
    // le même compte Supabase côté serveur.
    try {
      const meRes = await fetch('/api/me', { credentials: 'same-origin' });
      if (meRes.ok) {
        const me = await meRes.json();
        if (me && me.connected && me.display_name) {
          this.currentUser = {
            ...(this.currentUser || {}),
            first_name: me.display_name,
            full_name: me.display_name,
          };
        }
      }
    } catch (e) { /* pas grave, on garde currentUser tel quel */ }
    // Met à jour le bandeau utilisateur
    if (typeof UserBadge !== 'undefined') UserBadge.refresh();

    // Bind sidebar
    document.querySelectorAll('[data-view]').forEach(btn => {
      btn.addEventListener('click', () => {
        this.show(btn.dataset.view);
        this.closeMobileSidebar(); // ferme le drawer après navigation (mobile)
      });
    });

    // Mobile drawer : burger ouvre, croix + overlay ferment
    const mobileToggle = document.getElementById('mobile-menu-toggle');
    if (mobileToggle) mobileToggle.addEventListener('click', () => this.openMobileSidebar());
    const mobileClose = document.getElementById('mobile-sidebar-close');
    if (mobileClose) mobileClose.addEventListener('click', () => this.closeMobileSidebar());
    const mobileOverlay = document.getElementById('mobile-sidebar-overlay');
    if (mobileOverlay) mobileOverlay.addEventListener('click', () => this.closeMobileSidebar());

    // Bind FAB Claude (rond + label cliquables) — visible desktop uniquement
    const fab = document.getElementById('claude-fab');
    if (fab) fab.addEventListener('click', () => Claude.open());
    const fabLabel = document.getElementById('claude-fab-label');
    if (fabLabel) fabLabel.addEventListener('click', () => Claude.open());
    // Bouton "Allô Claude" dans la sidebar (mobile + desktop)
    const claudeMenuBtn = document.getElementById('claude-menu-trigger');
    if (claudeMenuBtn) claudeMenuBtn.addEventListener('click', () => {
      Claude.open();
      this.closeMobileSidebar();
    });

    // Bind bouton "Outils Triskell" → launcher Spotlight
    const launcherBtn = document.getElementById('launcher-trigger');
    if (launcherBtn) launcherBtn.addEventListener('click', () => Launcher.open());

    // Bind bouton "Brain" → ouvre direct la modale nouvelle note
    const brainBtn = document.getElementById('brain-trigger');
    if (brainBtn) brainBtn.addEventListener('click', () => {
      if (typeof Brain !== 'undefined') Brain._openNew();
    });

    // Bind bouton "Écosystème" → carte mentale interne dans le navigateur
    const ecoBtn = document.getElementById('ecosysteme-trigger');
    if (ecoBtn) ecoBtn.addEventListener('click', async () => {
      const url = 'https://triskell-ecosysteme.netlify.app';
      try {
        if (this.api && this.api.open_url) {
          await this.api.open_url({ url });
        } else {
          window.open(url, '_blank');
        }
      } catch (e) {
        console.warn('open ecosysteme:', e);
        window.open(url, '_blank');
      }
    });

    // Raccourcis clavier
    window.addEventListener('keydown', (e) => {
      if (e.key === 'F12') { e.preventDefault(); Claude.open(); }
      if (e.ctrlKey && e.key === 't') { e.preventDefault(); this.cycleTheme(); }
      // Ctrl+B → ouvre direct la modale Brain "Nouvelle note"
      if (e.ctrlKey && !e.shiftKey && !e.altKey && e.key.toLowerCase() === 'b') {
        // N'interfère pas avec Ctrl+B des éditeurs (textarea/input en focus)
        const tag = (e.target && e.target.tagName) || '';
        if (tag !== 'INPUT' && tag !== 'TEXTAREA' && !e.target?.isContentEditable) {
          e.preventDefault();
          if (typeof Brain !== 'undefined') Brain._openNew();
        }
      }
      if (e.key === 'Escape') this.closeMobileSidebar();
      // Ctrl+Shift+M (ou Cmd+Shift+M sur Mac) → ouvre le composer Mails de Triskell Command
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === 'm') {
        e.preventDefault();
        if (typeof Mails !== 'undefined') {
          this.show('mails');
          setTimeout(() => Mails._openComposer({}), 200);
        } else if (typeof Teddy !== 'undefined') {
          Teddy.compose();
        }
      }
    });

    // Push notifications : enregistre le Service Worker silencieusement
    if (typeof Push !== 'undefined') {
      Push.init().then(() => this._renderPushButton()).catch(() => {});
    }

    // Lance la 1re vue
    this.show('morning');

    // Polling claude attention (la veille proactive)
    setInterval(() => Claude.checkPending(), 60_000);

    // Polling desktop notifications sur nouveaux mails entrants
    if (typeof Mails !== 'undefined' && Mails.startDesktopNotifPolling) {
      Mails.startDesktopNotifPolling();
    }
  },

  // ---- Push notifications : insère un bouton dans le footer sidebar ----
  _renderPushButton() {
    if (typeof Push === 'undefined' || !Push.isSupported()) return;
    const slot = document.getElementById('user-badge-slot');
    if (!slot) return;
    // Évite les doublons
    const existing = document.getElementById('push-toggle-row');
    if (existing) existing.remove();

    const isOn = Push.isEnabled();
    const denied = (typeof Notification !== 'undefined' && Notification.permission === 'denied');

    const row = document.createElement('div');
    row.id = 'push-toggle-row';
    row.className = 'mt-2';

    // 3 états visuels distincts pour qu'on voie clairement OFF / ON / BLOQUÉ
    if (denied && !isOn) {
      // BLOQUÉ par le navigateur — l'utilisateur doit aller dans les paramètres
      row.innerHTML = `
        <div class="w-full px-3 py-2 rounded-lg bg-danger/10 text-danger border border-danger/30 text-[11px] flex items-center gap-2">
          <svg class="w-3.5 h-3.5 shrink-0" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
            <path d="M18 8a6 6 0 00-12 0c0 7-3 9-3 9h18s-3-2-3-9"/>
            <line x1="3" y1="3" x2="21" y2="21"/>
          </svg>
          <div class="flex-1 leading-tight">
            <div class="font-semibold">Notifs bloquées</div>
            <div class="opacity-80">Débloque dans les réglages du navigateur (icône cadenas dans la barre d'adresse).</div>
          </div>
        </div>
      `;
    } else if (isOn) {
      // ACTIVÉES — vert success franc, état clairement positif
      row.innerHTML = `
        <div class="flex items-center gap-2">
          <button id="push-toggle"
                  class="flex-1 text-xs px-3 py-2 rounded-lg bg-success/15 text-success border border-success/40 hover:bg-success/25 font-semibold flex items-center justify-center gap-1.5"
                  title="Cliquer pour désactiver les notifications">
            <svg class="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 24 24">
              <path d="M12 22a2 2 0 002-2h-4a2 2 0 002 2zM18 16v-5a6 6 0 10-12 0v5l-2 2v1h16v-1l-2-2z"/>
            </svg>
            <span>Notifications activées</span>
          </button>
          <button id="push-test"
                  class="text-[11px] px-2.5 py-2 rounded-lg bg-bg text-text-muted border border-border hover:border-success hover:text-success"
                  title="Envoyer une notif de test">
            Test
          </button>
        </div>
      `;
    } else {
      // DÉSACTIVÉES — bouton clairement "appel à action" (accent vif), pas un grisaille
      row.innerHTML = `
        <button id="push-toggle"
                class="w-full text-xs px-3 py-2 rounded-lg bg-accent/10 text-accent border border-accent/40 hover:bg-accent hover:text-white font-semibold flex items-center justify-center gap-1.5 transition-colors"
                title="Cliquer pour activer les notifications">
          <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
            <path d="M18 8a6 6 0 00-12 0c0 7-3 9-3 9h18s-3-2-3-9"/>
            <line x1="3" y1="3" x2="21" y2="21"/>
          </svg>
          <span>Activer les notifications</span>
        </button>
      `;
    }

    slot.parentNode.insertBefore(row, slot.nextSibling);

    const toggleBtn = document.getElementById('push-toggle');
    if (toggleBtn) {
      toggleBtn.onclick = async () => {
        if (Push.isEnabled()) {
          await Push.disable();
        } else {
          await Push.enable();
        }
        this._renderPushButton();
      };
    }
    const testBtn = document.getElementById('push-test');
    if (testBtn) testBtn.onclick = () => Push.test();

    // Pastille "NEW" sur le bouton notifs (refonte 3 états : OFF / ON / Bloqué)
    if (window.NewBadge) {
      const target = toggleBtn || row.firstElementChild;
      if (target) window.NewBadge.attach(target, 'notifs-button-v1');
    }
  },

  // ---- Mobile sidebar drawer (visible <md uniquement) ----
  openMobileSidebar() {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('mobile-sidebar-overlay');
    if (!sidebar || !overlay) return;
    sidebar.classList.remove('-translate-x-full');
    sidebar.classList.add('translate-x-0');
    overlay.classList.remove('hidden');
    document.body.classList.add('overflow-hidden');
  },

  closeMobileSidebar() {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('mobile-sidebar-overlay');
    if (!sidebar || !overlay) return;
    // Sur desktop la sidebar est toujours visible (md:translate-x-0), pas besoin de toggle.
    sidebar.classList.add('-translate-x-full');
    sidebar.classList.remove('translate-x-0');
    overlay.classList.add('hidden');
    // Pas de unset overflow-hidden : le body est déjà overflow-hidden globalement
  },

  async applyThemeFromSettings() {
    let mode = 'mid';
    if (this.api) {
      try { mode = await this.api.get_theme_mode(); } catch (e) {}
    }
    document.documentElement.setAttribute('data-theme', mode);
  },

  async cycleTheme() {
    if (!this.api) return;
    try {
      const r = await this.api.cycle_theme();
      if (r && r.ok) {
        document.documentElement.setAttribute('data-theme', r.mode);
      }
    } catch (e) { console.warn(e); }
  },

  // ---- Routing entre vues ----
  show(viewId) {
    this.currentView = viewId;
    // Active state sidebar
    document.querySelectorAll('[data-view]').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.view === viewId);
    });
    // Render
    const target = document.getElementById('content');
    target.innerHTML = '';
    target.classList.add('animate-fade-in');
    setTimeout(() => target.classList.remove('animate-fade-in'), 320);

    switch (viewId) {
      case 'morning':   return Morning.render(target);
      case 'replies':   return Replies.render(target);
      case 'mails':     return Mails.render(target);
      case 'brain':     return Brain.render(target);
      case 'drafts':    return Drafts.render(target);
      case 'funnel':    return Funnel.render(target);
      case 'revenue':   return Revenue.render(target);
      case 'clients':   return Clients.render(target);
      case 'phare':     return Phare.render(target);
      case 'wow':       return Wow.render(target);
      case 'rankus':    return Rankus.render(target);
      case 'lagriffe':  return Lagriffe.render(target);
      case 'mail_templates': return MailTemplates.render(target);
      case 'obelisk':   return Obelisk.render(target);
      case 'config':    return Config.render(target);
      case 'tutorial':  return Tutorial.render(target);
      case 'autopilot': return Autopilot.render(target);
      case 'delivery':  return Delivery.render(target);
      case 'health':    return Health.render(target);
      case 'abtest':    return ABTest.render(target);
      default: return this._renderPlaceholder(target, viewId, "Cette vue arrive bientôt.");
    }
  },

  _renderPlaceholder(target, viewId, _msg) {
    const labels = {
      'autopilot':  { title: 'Auto-pilote',         icon: '🚀', desc: 'Décris ta cible une fois (secteur, région, mots-clés). L\'app cherche, enrichit, rédige, envoie.' },
      'convoy':     { title: 'Importer une liste',  icon: '📂', desc: 'Glisse un PDF, Word, Excel ou image avec ta liste de prospects. L\'app extrait les contacts et prépare les mails.' },
      'compose':    { title: 'Écrire avec l\'IA',   icon: '✍️', desc: 'Tape ta consigne, choisis ton assistant IA, l\'app rédige.' },
      'templates':  { title: 'Modèles d\'emails',   icon: '📄', desc: 'Tes modèles prêts à réutiliser. Duplique-les, édite-les, ou crée les tiens.' },
      'campaigns':  { title: 'Envoyer des emails',  icon: '✉️', desc: 'Lance une vague de mails à tes prospects qualifiés.' },
      'publish':    { title: 'Publier sur les réseaux', icon: '📡', desc: 'Pilote tes publications LinkedIn, X, Bluesky via AlphaCast.' },
      'prospects':  { title: 'Chercher des prospects', icon: '🔎', desc: 'Recherche manuelle dans la base partagée Triskell.' },
      'dashboard':  { title: 'Tableau de bord',     icon: '📊', desc: 'Vue d\'ensemble en temps réel de ton activité.' },
    };
    const info = labels[viewId] || { title: viewId, icon: '⏳', desc: 'Cette vue arrive bientôt.' };
    target.innerHTML = `
      <section class="animate-slide-up max-w-3xl">
        <div class="mb-8">
          <div class="hero-kicker mb-2">${info.title.toUpperCase()}</div>
          <h1 class="hero-title mb-3" style="font-size: 36px;">${info.title}.</h1>
          <p class="hero-subtitle">${info.desc}</p>
        </div>

        <div class="card-hero p-12 text-center" data-accent="accent">
          <div class="text-6xl mb-5 opacity-80">${info.icon}</div>
          <div class="hero-kicker text-accent mb-3">EN COURS DE MIGRATION</div>
          <h2 class="font-sans text-2xl font-bold mb-3 leading-snug">Cet écran est encore servi par l'ancienne version.</h2>
          <p class="text-text-secondary mb-6 max-w-lg mx-auto">
            Cette vue est entièrement fonctionnelle dans la version desktop classique
            (CustomTkinter). Sa version web Apple-clear arrive en Phase 3.
            En attendant, ouvre <code class="text-xs px-1.5 py-0.5 rounded bg-bg">python run.py</code>
            pour utiliser cet écran.
          </p>
          <button class="btn btn-secondary" onclick="App.show('morning')">← Retour au Cockpit</button>
        </div>
      </section>
    `;
  },

  // ---- Helpers ----
  formatDateFr() {
    const d = new Date();
    const days = ['dimanche','lundi','mardi','mercredi','jeudi','vendredi','samedi'];
    const months = ['janvier','février','mars','avril','mai','juin',
                    'juillet','août','septembre','octobre','novembre','décembre'];
    return `${days[d.getDay()]} ${d.getDate()} ${months[d.getMonth()]}`;
  },

  greeting() {
    const h = new Date().getHours();
    if (h < 6) return 'Bonne nuit';
    if (h < 12) return 'Bonjour';
    if (h < 18) return 'Bon après-midi';
    return 'Bonsoir';
  },
};

// pywebview signale la disponibilité de l'API via cet event
window.addEventListener('pywebviewready', () => App.init());

// Fallback : si l'event ne se déclenche pas (mode preview ou launch HTML
// direct), on tente quand même au DOMContentLoaded. waitForApi gère le cas.
window.addEventListener('DOMContentLoaded', () => {
  if (!App.api) App.init();
});
