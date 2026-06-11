/* Vue RankUs Studio — configuration de la factory pipeline_view.
 * RankUs = marque qui vend le SEO, sites Triskell internes uniquement.
 * Chaîne identique à WoW (mêmes étapes, mêmes statuts).
 */

const Rankus = makePipelineView({
  apiPrefix: 'rankus',
  kicker:    'RANKUS STUDIO',
  title:     'La chaîne de fabrication SEO sous tes yeux.',
  subtitle:  'Chaque demande SEO, son étage dans la chaîne, et l’historique pas à pas.',
  stages:        PIPELINE_BASE_STAGES,
  statusLabels:  PIPELINE_BASE_STATUS_LABELS,
  statusColors:  PIPELINE_BASE_STATUS_COLORS,
});
