/* DemoFakeValidator — vérifie au boot que tous les fakes mode démo
 * respectent le format attendu par leur vue consommatrice, ET que le
 * mode démo est étanche (liste BLANCHE du 11/06/2026).
 *
 * 1) FORMAT : quand un fake est mal formé (champ manquant, mauvais type),
 *    la vue affiche vide / plante. C'est arrivé plusieurs fois. En mode
 *    démo, ce module audite TOUS les fakes au boot et logue les
 *    mismatches dans la console + HealthCheck.
 *
 * 2) COUVERTURE : depuis le passage en liste blanche, TOUT appel qui
 *    n'est ni un faux ni explicitement autorisé (session/thème) doit
 *    être bloqué net par DemoMode.intercept (handled:true). Ce module
 *    le PROUVE : il teste le blocage par défaut (méthode inconnue) et
 *    une liste de méthodes sensibles (envoi de mails, suppressions,
 *    publications, IA payante…) — voir SENSITIVE_METHODS.
 *
 * Comment ajouter une vérif de format : étendre SCHEMAS ci-dessous avec :
 *   method_name: {
 *     required: ['ok', 'foo', 'bar.baz'],   // chemins requis (dot notation)
 *     arrays:   { 'bar.items': ['id'] },     // chaque item d'array doit avoir .id
 *   }
 *
 * Ce module ne CASSE jamais l'app — il logue seulement. Il sert de
 * filet de sécurité pour détecter les régressions à temps.
 */

const DemoFakeValidator = {
  SCHEMAS: {
    get_morning_digest: {
      required: ['ok', 'sent.yesterday', 'sent.today', 'sent.last_7d',
                 'replies.yesterday_total', 'replies.today_total',
                 'replies.yesterday_breakdown',
                 'queue.replies_unhandled_interested', 'queue.replies_unhandled_total',
                 'queue.drafts_prospect_pending', 'queue.drafts_convoy_pending',
                 'alerts.convoy_failed_yesterday', 'alerts.convoy_failed_today'],
    },
    multichannel_get_actions: {
      required: ['ok', 'actions'],
      arrays:   { 'actions': ['id', 'prospect_name', 'message'] },
    },
    get_drafts: {
      required: ['ok', 'rows'],
      arrays:   { 'rows': ['key', 'name', 'email', 'ts', 'subject', 'body'] },
    },
    get_replies: {
      required: ['ok', 'rows', 'prospects'],
      arrays:   { 'rows': ['id', 'ts', 'subject', 'prospect_id', 'extra'] },
    },
    get_clients: {
      required: ['ok', 'groups'],
    },
    get_funnel: {
      required: ['ok', 'stages', 'by_category', 'by_status', 'by_product'],
    },
    brain_list: {
      required: ['ok', 'notes'],
      arrays:   { 'notes': ['id', 'author', 'content', 'category', 'created_at'] },
    },
    mails_list: {
      required: ['ok', 'mails'],
      arrays:   { 'mails': ['id', 'kind', 'ts', 'subject', 'extra'] },
    },
    mail_accounts_list: {
      required: ['ok', 'accounts'],
      arrays:   { 'accounts': ['id', 'from_email'] },
    },
    user_mail_templates_list: {
      required: ['ok', 'templates'],
      arrays:   { 'templates': ['id', 'name'] },
    },
    signatures_list: {
      required: ['ok', 'signatures'],
      arrays:   { 'signatures': ['id', 'name'] },
    },
    system_health: {
      required: ['ok', 'summary.healthy', 'workers'],
      arrays:   { 'workers': ['label', 'health', 'last_run_at'] },
    },
    autopilot_status: {
      required: ['ok', 'running', 'log', 'stats.searched'],
    },
    autopilot_get_config: {
      required: ['ok', 'config'],
    },
    ab_get_results: {
      required: ['ok', 'campaigns'],
      arrays:   { 'campaigns': ['id', 'name', 'variants'] },
    },
    delivery_kits_list: {
      required: ['ok', 'kits'],
    },
    get_apps_catalog: {
      required: ['ok', 'apps'],
      arrays:   { 'apps': ['id', 'name'] },
    },
    tracker_stats: {
      required: ['ok', 'sent_7d', 'opened_7d', 'open_rate_7d'],
    },
    claude_ask: {
      required: ['ok', 'urgency', 'headline', 'advice'],
    },
    messages_list: {
      required: ['ok', 'messages'],
    },
    messages_count_unread: {
      required: ['ok', 'count'],
    },
    messages_me: {
      required: ['ok', 'user_id', 'display_name'],
    },
    get_current_user: {
      required: ['ok'],
    },
    prospect_generate_mail: {
      required: ['ok', 'subject', 'body_html'],
    },
    revenue_overview: {
      required: ['ok', 'current_month.total_cents', 'previous_month.total_cents',
                 'last_7_days.total_cents', 'last_30_days.total_cents',
                 'top_clients_month', 'by_source_month', 'by_product_month', 'forecast'],
    },
    // --- Fakes ajoutés à la refonte du 11/06/2026 (liste blanche) ---
    guide_snapshot: {
      required: ['ok', 'drafts_pending', 'replies_unhandled', 'prospects_total',
                 'autopilot_enabled', 'workers.healthy', 'missions'],
    },
    prospection_missions: {
      required: ['ok', 'missions', 'autopilot.enabled'],
      arrays:   { 'missions': ['id', 'label', 'source', 'status', 'progress', 'created_at', 'counts'] },
    },
    obelisk_stats: {
      required: ['ok', 'stats.total', 'stats.with_email'],
    },
    obelisk_list_creators: {
      required: ['ok', 'rows', 'count'],
      arrays:   { 'rows': ['id', 'name', 'audience', 'emails', 'status'] },
    },
    pipelines_activity: {
      required: ['ok', 'pipelines'],
    },
    setup_status: {
      required: ['ok', 'items', 'summary'],
      arrays:   { 'items': ['key', 'label', 'status'] },
    },
    prospect_timeline: {
      required: ['ok', 'prospect', 'events'],
      arrays:   { 'events': ['ts', 'type', 'title'] },
    },
    messages_other_user: {
      required: ['ok', 'other'],
    },
  },

  // ------------------------------------------------------------------
  // COUVERTURE — méthodes SENSIBLES dont on prouve qu'elles ne passent
  // JAMAIS au travers du mode démo (handled:true = zéro appel réseau).
  // Si l'une d'elles finissait en NETWORK_ALLOWED ou que le blocage par
  // défaut sautait, l'audit du boot le crierait en console + HealthCheck.
  // ------------------------------------------------------------------
  SENSITIVE_METHODS: [
    'prospection_start',           // lancerait une vraie mission (vrais mails possibles)
    'autopilot_save_config',       // écraserait la vraie config d'envoi
    'obelisk_delete_all_creators', // viderait la vraie base de prospects
    'pixelpros_resend_paid_mail',  // renverrait un VRAI mail à un client
    'catalog_delete_product',      // supprimerait un vrai produit du catalogue
    'geo_publish_content',         // publierait pour de vrai en production
    'claude_chat',                 // IA payante + tags [ACTION] bien réels
    'copilot_send',                // idem côté copilote
  ],

  /** Lit un chemin "a.b.c" sur un objet. */
  _getPath(obj, path) {
    return path.split('.').reduce((o, k) => (o == null ? undefined : o[k]), obj);
  },

  /** Valide un fake renvoyé par DemoMode._fake[method](). */
  validate(method, result) {
    const schema = this.SCHEMAS[method];
    if (!schema) return { ok: true, skipped: true };
    const issues = [];

    // Vérifie les champs requis
    for (const path of schema.required || []) {
      const val = this._getPath(result, path);
      if (val === undefined || val === null) {
        issues.push(`Champ requis manquant : "${path}"`);
      }
    }

    // Vérifie chaque item d'array pour les schemas "arrays"
    for (const [arrayPath, requiredItemKeys] of Object.entries(schema.arrays || {})) {
      const arr = this._getPath(result, arrayPath);
      if (!Array.isArray(arr)) {
        issues.push(`"${arrayPath}" devrait être un array, reçu : ${typeof arr}`);
        continue;
      }
      if (arr.length === 0) continue;
      const first = arr[0];
      if (typeof first !== 'object' || first === null) {
        issues.push(`Premier item de "${arrayPath}" n'est pas un objet`);
        continue;
      }
      for (const key of requiredItemKeys) {
        if (!(key in first)) {
          issues.push(`Item de "${arrayPath}" : champ "${key}" manquant (vérifié sur le 1er élément)`);
        }
      }
    }

    return { ok: issues.length === 0, issues };
  },

  /** Audite TOUS les fakes définis dans DemoMode._fake. */
  auditAll() {
    if (typeof DemoMode === 'undefined' || !DemoMode._fake) return [];
    const failures = [];
    const methods = Object.keys(DemoMode._fake);
    for (const method of methods) {
      try {
        const fakeFn = DemoMode._fake[method];
        if (typeof fakeFn !== 'function') continue;
        // Appelle le fake avec un payload vide (la plupart des fakes l'acceptent)
        let result;
        try { result = fakeFn.call(DemoMode._fake, {}); }
        catch (e) {
          // Réessaie sans payload
          try { result = fakeFn.call(DemoMode._fake); }
          catch (e2) {
            failures.push({ method, kind: 'exec_error', msg: String(e) });
            continue;
          }
        }
        if (result == null) continue;  // certains fakes retournent null exprès (claude_consume_pending)
        const v = this.validate(method, result);
        if (!v.skipped && !v.ok) {
          failures.push({ method, kind: 'schema_mismatch', issues: v.issues });
        }
      } catch (e) {
        failures.push({ method, kind: 'audit_error', msg: String(e) });
      }
    }
    return failures;
  },

  /** Exécute fn avec le mode démo « forcé allumé » (simulation), puis
   *  restaure. Permet de prouver la couverture même hors mode démo,
   *  sans rien activer ni recharger. */
  _withDemoOn(fn) {
    const original = DemoMode.isOn;
    try {
      DemoMode.isOn = () => true;
      return fn();
    } finally {
      DemoMode.isOn = original;
    }
  },

  /** Prouve l'étanchéité du mode démo (liste blanche) :
   *  - une méthode INCONNUE doit être bloquée net (handled:true + ok:false) ;
   *  - chaque méthode SENSIBLE doit être interceptée (handled:true), que ce
   *    soit par un faux ou par le blocage par défaut — l'essentiel est que
   *    RIEN ne parte au serveur.
   *  Renvoie une liste de failures (vide = étanche). */
  auditCoverage() {
    if (typeof DemoMode === 'undefined' || typeof DemoMode.intercept !== 'function') {
      return [{ method: '(module)', kind: 'coverage_error', msg: 'DemoMode.intercept introuvable' }];
    }
    const failures = [];
    this._withDemoOn(() => {
      // 1) Le DÉFAUT : méthode inconnue → blocage net obligatoire.
      try {
        const r = DemoMode.intercept('xyz_test_inconnu', {});
        const blocked = !!(r && r.handled === true && r.result && r.result.ok === false);
        if (!blocked) {
          failures.push({
            method: 'xyz_test_inconnu', kind: 'default_not_blocking',
            msg: 'Le blocage par défaut ne tient plus : une méthode inconnue partirait au VRAI serveur en mode démo.',
          });
        }
      } catch (e) {
        failures.push({ method: 'xyz_test_inconnu', kind: 'coverage_error', msg: String(e) });
      }
      // 2) Les méthodes sensibles : interception obligatoire.
      for (const method of this.SENSITIVE_METHODS) {
        try {
          const r = DemoMode.intercept(method, {});
          if (!r || r.handled !== true) {
            failures.push({
              method, kind: 'sensitive_passthrough',
              msg: 'Cette méthode SENSIBLE partirait au VRAI serveur en mode démo (présente en NETWORK_ALLOWED ?).',
            });
          }
        } catch (e) {
          failures.push({ method, kind: 'coverage_error', msg: String(e) });
        }
      }
    });
    return failures;
  },

  /** Lance l'audit complet (formats + couverture) + log. Renvoie le nombre
   *  de failures. */
  runAudit({ verbose = false } = {}) {
    const schemaFailures = this.auditAll();
    const coverageFailures = this.auditCoverage();
    const failures = schemaFailures.concat(coverageFailures);
    if (coverageFailures.length === 0) {
      // La preuve d'étanchéité s'affiche toujours (c'est elle qui garantit
      // qu'aucune action réelle ne peut partir pendant une démo).
      console.log(`[DemoFakeValidator] ✓ Mode démo étanche : méthode inconnue bloquée par défaut + ${this.SENSITIVE_METHODS.length}/${this.SENSITIVE_METHODS.length} méthodes sensibles interceptées.`);
    }
    if (failures.length === 0) {
      if (verbose) console.log('[DemoFakeValidator] ✓ Tous les fakes sont valides.');
      return 0;
    }
    console.group(`[DemoFakeValidator] ⚠ ${failures.length} problème(s) détecté(s) (formats de fakes / étanchéité démo)`);
    failures.forEach(f => {
      console.warn(`✗ ${f.method} :`, f.issues || f.msg || f);
      if (typeof HealthCheck !== 'undefined') {
        HealthCheck.record({
          kind: (f.kind === 'default_not_blocking' || f.kind === 'sensitive_passthrough' || f.kind === 'coverage_error')
            ? 'demo_coverage_breach'
            : 'demo_fake_invalid',
          method: f.method,
          issues: f.issues || [f.msg || ''],
        });
      }
    });
    console.groupEnd();
    return failures.length;
  },
};

window.DemoFakeValidator = DemoFakeValidator;

// Audit auto au boot, MAIS uniquement si on est en mode démo (sinon
// pas la peine de bourriner). On lance l'audit aussi quand le mode
// démo est activé via la modale (handler externe peut appeler).
window.addEventListener('DOMContentLoaded', () => {
  setTimeout(() => {
    if (typeof DemoMode !== 'undefined' && DemoMode.isOn && DemoMode.isOn()) {
      DemoFakeValidator.runAudit({ verbose: false });
    }
  }, 600);   // attend que DemoMode soit prêt
});
