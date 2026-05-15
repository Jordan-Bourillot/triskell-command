/* Vue Lagriffe Studio — configuration de la factory pipeline_view.
 * Lagriffe = offre Sites Triskell. Pipeline avec une étape de plus :
 *   final_ready_review (validation humaine du site final avant envoi mail).
 */

const Lagriffe = makePipelineView({
  apiPrefix: 'lagriffe',
  kicker:    'LAGRIFFE STUDIO',
  title:     'Le pipeline sites sous tes yeux.',
  subtitle:  'Chaque demande site, son étage dans le pipeline, et l\'historique pas à pas.',

  stages: [
    ...PIPELINE_BASE_STAGES.slice(0, 6),   // jusqu'à 'finalizing'
    { key: 'final_ready_review', label: 'À valider (final)', sub: 'Site final prêt, validation humaine avant envoi' },
    ...PIPELINE_BASE_STAGES.slice(6),       // 'live'
  ],

  statusLabels: {
    ...PIPELINE_BASE_STATUS_LABELS,
    final_ready_review: 'Final à valider',
  },

  statusColors: {
    ...PIPELINE_BASE_STATUS_COLORS,
    final_ready_review: 'warning',
  },

  // Action spécifique Lagriffe : valider le site final et déclencher le mail au client
  extraActions: (intake) => {
    if (intake.status !== 'final_ready_review') return [];
    return [{
      id: 'pv-act-approve-final',
      label: 'Valider le site final et envoyer le mail',
      cls: 'btn-primary',
      onClick: async ({ intake, setMsg, call, reload }) => {
        const fullName = `${intake.client_first_name || ''} ${intake.client_last_name || ''}`.trim();
        if (!confirm(`Valider le site final et envoyer le mail au client ?\n\n${fullName} · ${intake.company_name}\n\nLe status passera à 'live' et le client recevra l'URL définitive.`)) return;
        setMsg('Envoi du mail final…');
        const r = await call('approve_final', { id: intake.id });
        if (r && r.ok) { setMsg(`OK : ${r.message || ''}`); await reload(); }
        else setMsg(`Échec : ${r && r.error || 'inconnu'}`, true);
      },
    }];
  },
});
