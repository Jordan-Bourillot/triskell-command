/* Vue Studio WoW — configuration de la factory pipeline_view.
 * Voir pipeline_view.js pour toute la logique.
 */

const Wow = makePipelineView({
  apiPrefix: 'wow',
  kicker:    'STUDIO WOW',
  title:     'La chaîne de fabrication WoW sous tes yeux.',
  subtitle:  'Chaque demande client, son étage dans la chaîne, et l’historique pas à pas.',
  stages:        PIPELINE_BASE_STAGES,
  statusLabels:  PIPELINE_BASE_STATUS_LABELS,
  statusColors:  PIPELINE_BASE_STATUS_COLORS,
});
