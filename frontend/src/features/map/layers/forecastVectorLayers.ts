/**
 * Forecast particle layers, built from the backend's vector catalog.
 *
 * The vector counterpart to `forecastLayers.ts`, and the same runtime-
 * registration story: a forecast flow layer exists only where *both* component
 * models are trained and both grids built, so the descriptors are generated
 * from `/api/tiles/forecast/vector/catalog` and handed to
 * `LayerManager.register()` rather than being known at module load.
 *
 * They land in `flow`, alongside live wind and live currents, rather than in
 * the exclusive `ocean` group the scalar forecast rasters use. That is the
 * whole point of putting them here: `flow` is stackable, so a user can run the
 * live currents and the +7d forecast currents at once and watch where they
 * disagree. Two of these at the same time is legible in a way two full-coverage
 * colour fields never are.
 */

import { createForecastCurrentsParticleLayer } from '../vectorField/currentsLayer';
import { CURRENT_SPEED_COLOR_STOPS } from '../vectorField/colorRamp';
import type { CustomLayerDescriptor, LayerLegend } from '../types';
import type { ForecastVectorEntry, ForecastVectorMode } from '../api/forecastVectors';

export function forecastVectorLayerId(
  key: string,
  horizon: number,
  mode: ForecastVectorMode
): string {
  return `forecast-vector-${key}-h${horizon}-${mode}`;
}

/** Matches CURRENT_SPEED_COLOR_STOPS, as offsets on the legend's own 0..max
 *  domain. Derived from the stops rather than restated, so the two cannot
 *  drift the way the raster ramps in `forecastLayers.ts` can. */
function legendFor(entry: ForecastVectorEntry): LayerLegend {
  const max = entry.speed_max_legend;
  return {
    type: 'gradient',
    unit: entry.unit,
    min: 0,
    max,
    stops: CURRENT_SPEED_COLOR_STOPS.map((stop) => ({
      offset: max > 0 ? stop.value / max : 0,
      color: `rgb(${stop.color[0]},${stop.color[1]},${stop.color[2]})`,
    })),
  };
}

function attributionFor(
  entry: ForecastVectorEntry,
  horizon: number,
  mode: ForecastVectorMode
): string {
  if (mode === 'anchor') {
    return (
      `The observed flow the +${horizon}d forecast was anchored on, from ` +
      `${entry.observation_date ?? 'an unknown date'}. OBSERVATION, not model output — this is ` +
      `the ${entry.u_variable}/${entry.v_variable} grid's own starting state, provided so the ` +
      `forecast can be compared against what it started from. Grid is ${entry.resolution_deg}°.`
    );
  }

  const skill = entry.skill_scores ? ` Skill vs persistence: ${entry.skill_scores}.` : '';
  const missing =
    entry.missing_covariates && entry.missing_covariates.length > 0
      ? ` SCORED WITHOUT ${entry.missing_covariates.join(', ').toUpperCase()}: no global gridded ` +
        `source exists for ${entry.missing_covariates.length === 1 ? 'it' : 'them'}, so every ` +
        `cell was scored without ${entry.missing_covariates.length === 1 ? 'it' : 'them'}. ` +
        `Accuracy is reduced relative to the point forecast at /dashboard.`
      : '';

  return (
    `Predicted surface flow at +${horizon} days. MODEL OUTPUT, not observation: ` +
    `${entry.model ?? 'LightGBM'} trained by rolling-origin cross-validation on ` +
    `${(entry.sources ?? []).join('; ') || 'Copernicus Marine'}, with ${entry.u_variable} and ` +
    `${entry.v_variable} forecast as separate components and composed into a vector here.` +
    `${skill} Grid is ${entry.resolution_deg}°, anchored on observations from ` +
    `${entry.observation_date ?? 'an unknown date'}, built ` +
    `${entry.generated_at ?? 'at an unknown time'}. Particles flow toward the direction of ` +
    `travel (oceanographic convention).${missing}`
  );
}

/** Every layer one vector entry produces: each shared horizon's forecast, plus
 *  one anchor layer for the observed state they were all launched from. */
export function forecastVectorLayers(entry: ForecastVectorEntry): CustomLayerDescriptor[] {
  if (entry.error || entry.horizons.length === 0) return [];

  const layers: CustomLayerDescriptor[] = entry.horizons.map((horizon) => ({
    id: forecastVectorLayerId(entry.key, horizon, 'forecast'),
    name: `${entry.label} Forecast +${horizon}d`,
    category: 'flow' as const,
    type: 'custom' as const,
    attribution: attributionFor(entry, horizon, 'forecast'),
    defaultOpacity: 0.9,
    defaultVisible: false,
    createLayer: (id: string) =>
      createForecastCurrentsParticleLayer(id, entry.key, horizon, 'forecast', 0.9),
    legend: legendFor(entry),
  }));

  // One anchor layer, not one per horizon: `anchor` is the same observed field
  // whatever horizon was forecast from it, so a copy per horizon would be the
  // same texture under several names.
  const [firstHorizon] = entry.horizons;
  layers.push({
    id: forecastVectorLayerId(entry.key, firstHorizon, 'anchor'),
    name: `${entry.label} (forecast anchor)`,
    category: 'flow' as const,
    type: 'custom' as const,
    attribution: attributionFor(entry, firstHorizon, 'anchor'),
    defaultOpacity: 0.9,
    defaultVisible: false,
    createLayer: (id: string) =>
      createForecastCurrentsParticleLayer(id, entry.key, firstHorizon, 'anchor', 0.9),
    legend: legendFor(entry),
  });

  return layers;
}
