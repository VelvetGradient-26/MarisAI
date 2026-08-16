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

import {
  createForecastVectorParticleLayer,
  CURRENTS_VISUAL,
} from '../vectorField/currentsLayer';
import { WIND_SPEED_COLOR_STOPS } from '../vectorField/colorRamp';
import type { ColorStop } from '../vectorField/colorRamp';
import type { CustomLayerDescriptor, LayerLegend } from '../types';
import type { ForecastVectorEntry, ForecastVectorMode } from '../api/forecastVectors';

/**
 * How each pair is drawn: the same ramp and pace as its *live* counterpart.
 *
 * A forecast field exists to be compared against the observation it was
 * launched from, so the two must be visually identical — any difference the eye
 * catches has to be the ocean's, not the renderer's. Keyed on the backend's
 * pair key, with currents' values imported rather than restated.
 *
 * This map is why `wind_u`/`wind_v` going live was not purely a training run.
 * Before it, every forecast pair was drawn as currents: an 8 m/s wind field on
 * a ramp whose domain ends at 2 m/s renders as one flat top colour, and at
 * currents' 12000 speed scale it advects ~265 px/s. Both look like a working
 * layer.
 */
const PAIR_VISUALS: Record<string, { colorStops: ColorStop[]; visualSpeedScale?: number }> = {
  currents: CURRENTS_VISUAL,
  // No `visualSpeedScale`: wind is the engine's 1800 default, which is what the
  // live wind layer uses by omitting it too.
  wind: { colorStops: WIND_SPEED_COLOR_STOPS },
};

/** Currents' identity is the fallback for a pair this file has not been taught
 *  yet — it is the conservative choice for another *ocean* field, and the
 *  legend still reads the entry's own unit and maximum. A new pair with a
 *  genuinely different scale (waves) should get an entry above rather than
 *  inherit this. */
function visualFor(key: string) {
  return PAIR_VISUALS[key] ?? CURRENTS_VISUAL;
}

export function forecastVectorLayerId(
  key: string,
  horizon: number,
  mode: ForecastVectorMode
): string {
  return `forecast-vector-${key}-h${horizon}-${mode}`;
}

/** The legend reads the *same* stops the particles are coloured by, as offsets
 *  on the legend's own 0..max domain. Derived from the stops rather than
 *  restated, so the two cannot drift the way the raster ramps in
 *  `forecastLayers.ts` can — and taken from `visualFor` rather than from
 *  currents, or a wind layer would be drawn on one ramp and explained by
 *  another. Offsets are clamped: a ramp whose top stop sits above the pair's
 *  legend maximum would otherwise emit an offset past 1. */
function legendFor(entry: ForecastVectorEntry): LayerLegend {
  const max = entry.speed_max_legend;
  return {
    type: 'gradient',
    unit: entry.unit,
    min: 0,
    max,
    stops: visualFor(entry.key).colorStops.map((stop) => ({
      offset: max > 0 ? Math.min(1, stop.value / max) : 0,
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
    `${entry.generated_at ?? 'at an unknown time'}. Particles always flow the way the field ` +
    `travels; this field is *named* for where it ` +
    `${entry.direction_convention === 'from' ? 'comes from (meteorological convention, so a ' +
      '"westerly" blows toward the east)' : 'travels toward (oceanographic convention)'}` +
    `.${missing}`
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
      createForecastVectorParticleLayer(id, entry.key, horizon, 'forecast', 0.9, visualFor(entry.key)),
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
      createForecastVectorParticleLayer(id, entry.key, firstHorizon, 'anchor', 0.9, visualFor(entry.key)),
    legend: legendFor(entry),
  });

  return layers;
}
