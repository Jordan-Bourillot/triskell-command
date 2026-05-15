/* Vue Studio WoW — configuration de la factory pipeline_view.
 * Voir pipeline_view.js pour toute la logique.
 */

const Wow = makePipelineView({
  apiPrefix: 'wow',
  kicker:    'STUDIO WOW',
  title:     'Le pipeline WoW sous tes yeux.',
  subtitle:  'Chaque demande client, son étage dans le pipeline, et l\'historique pas à pas.',
  stages:        PIPELINE_BASE_STAGES,
  statusLabels:  PIPELINE_BASE_STATUS_LABELS,
  statusColors:  PIPELINE_BASE_STATUS_COLORS,
});
