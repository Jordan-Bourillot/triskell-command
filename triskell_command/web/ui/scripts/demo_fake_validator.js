/* DemoFakeValidator — vérifie au boot que tous les fakes mode démo
 * respectent le format attendu par leur vue consommatrice.
 *
 * Quand un fake est mal formé (champ manquant, mauvais type), la vue
 * affiche vide / plante. C'est arrivé plusieurs fois. Désormais, en
 * mode démo, ce module audite TOUS les fakes au boot et log les
 * mismatches dans la console + HealthCheck.
 *
 * Comment ajouter une vérif : étendre SCHEMAS ci-dessous avec :
 *   method_name: {
 *     required: ['ok', 'foo', 'bar.baz'],   // chemins requis (dot notation)
 *     arrays:   ['bar.items[*].id'],         // chaque item d'array doit avoir .id
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
    phare_overview: {
      required: ['ok', 'sites_count', 'total_clicks_30d', 'avg_position_30d', 'pending_actions'],
    },
    phare_sites: {
      required: ['ok', 'sites'],
      arrays:   { 'sites': ['id', 'name', 'domain', 'clicks_30d', 'avg_position_30d'] },
    },
    phare_site: {
      required: ['ok', 'site', 'audit.score', 'keywords', 'actions'],
      arrays:   { 'keywords': ['keyword', 'position', 'search_volume'],
                  'actions':  ['title', 'kind', 'status'] },
    },
    phare_pending_actions: {
      required: ['ok', 'actions'],
      arrays:   { 'actions': ['id', 'title', 'kind', 'created_at', 'summary'] },
    },
    mails_list: {
      required: ['ok', 'mails'],
      arrays:   { 'mails': ['id', 'kind', 'ts', 'subject', 'extra'] },
    },
    mail_accounts_list: {
      required: ['ok', 'accounts'],
      arrays:   { 'accounts': ['id', 'from_email'] },
    },
    mail_templates_list: {
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
  },

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

  /** Lance l'audit + log. Renvoie le nombre de failures. */
  runAudit({ verbose = false } = {}) {
    const failures = this.auditAll();
    if (failures.length === 0) {
      if (verbose) console.log('[DemoFakeValidator] ✓ Tous les fakes sont valides.');
      return 0;
    }
    console.group(`[DemoFakeValidator] ⚠ ${failures.length} fake(s) avec un format invalide`);
    failures.forEach(f => {
      console.warn(`✗ ${f.method} :`, f.issues || f.msg || f);
      if (typeof HealthCheck !== 'undefined') {
        HealthCheck.record({
          kind: 'demo_fake_invalid',
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
