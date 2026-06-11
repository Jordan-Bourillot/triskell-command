/* Vue Lagriffe Studio — configuration de la factory pipeline_view.
 * Lagriffe = offre Sites Triskell. Chaîne avec une étape de plus :
 *   final_ready_review (validation humaine du site final avant envoi mail).
 */

const Lagriffe = makePipelineView({
  apiPrefix: 'lagriffe',
  kicker:    'LAGRIFFE STUDIO',
  title:     'La chaîne de fabrication des sites sous tes yeux.',
  subtitle:  'Chaque demande de site, son étage dans la chaîne, et l’historique pas à pas.',

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
        const ok = await Dialog.confirm(
          `Valider le site final et envoyer le mail au client ?\n${fullName} · ${intake.company_name || ''}\n\nLe site passera en ligne et le client recevra son adresse définitive.`,
          { title: 'Valider le site final', okLabel: 'Valider et envoyer', cancelLabel: 'Annuler' }
        );
        if (!ok) return;
        setMsg('Envoi du mail final…');
        const r = await call('approve_final', { id: intake.id });
        if (r && r.ok) {
          setMsg(`OK : ${r.message || ''}`);
          Toast.success('Site validé — mail envoyé au client.');
          await reload();
        } else {
          setMsg('Échec de la validation.', true);
          Toast.friendlyError(r && r.error, `La validation n'a pas abouti — rien n'a été envoyé.`);
        }
      },
    }];
  },
});
