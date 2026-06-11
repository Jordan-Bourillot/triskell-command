/* Vue RankUs Studio — configuration de la factory pipeline_view.
 * RankUs = marque qui vend le SEO, sites Triskell internes uniquement.
 * Chaîne identique à WoW (mêmes étapes, mêmes statuts), plus les
 * demandes venues du site public : contact (formulaire) et recall
 * (bouton « Être rappelé »).
 */

const Rankus = makePipelineView({
  apiPrefix: 'rankus',
  kicker:    'RANKUS STUDIO',
  title:     'La chaîne de fabrication SEO sous tes yeux.',
  subtitle:  'Chaque demande SEO, son étage dans la chaîne, et l’historique pas à pas.',
  stages:        PIPELINE_BASE_STAGES,

  statusLabels: {
    ...PIPELINE_BASE_STATUS_LABELS,
    contact: '✉️ Message reçu (site public)',
    recall:  '📞 À rappeler (site public)',
  },

  statusColors: {
    ...PIPELINE_BASE_STATUS_COLORS,
    contact: 'warning',
    recall:  'warning',
  },

  // Demandes venues du site public : marquer traité / remettre à traiter
  extraActions: (intake) => {
    if (intake.status !== 'contact' && intake.status !== 'recall') return [];
    const done = !!(intake.payload && intake.payload.handled_at);
    return [{
      id: 'pv-act-contact-handled',
      label: done ? 'Remettre à traiter' : 'Marquer traité ✓',
      cls: done ? 'btn-secondary' : 'btn-primary',
      onClick: async ({ intake, setMsg, call, reload }) => {
        const r = await call('mark_contact_handled', { id: intake.id, handled: !done });
        if (r && r.ok) {
          Toast.success(r.message || 'C’est noté.');
          await reload();
        } else {
          setMsg('Échec.', true);
          Toast.friendlyError(r && r.error, 'Impossible de mettre à jour cette demande.');
        }
      },
    }];
  },
});
