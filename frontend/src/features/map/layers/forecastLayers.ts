/**
 * Forecast map layers, built from the backend's grid catalog.
 *
 * Unlike everything in `layerRegistry.ts`, these are **not** known at module
 * load. A forecast layer exists only where a model has been trained and its
 * global grid built, and both are operator actions, so the descriptors are
 * generated from `/api/tiles/forecast/catalog` at runtime and registered with
 * `LayerManager.register()` — which is safe to call any time, since it only
 * writes in-memory metadata and emits.
 *
 * That is the difference from the habitat/bloom layers, whose species and
 * horizon lists are hand-maintained here: a newly trained variable becomes a
 * map layer with no edit to this file.
 *
 * They land in the `ocean` category deliberately. That group is exclusive, and
 * these are full-coverage colour fields exactly like SST — two of them drawn
 * on top of each other is noise, and the exclusive dropdown already expresses
 * "one, or none".
 */

import type { LayerLegend, RasterLayerDescriptor } from '../types';
import type { ForecastGridEntry, ForecastMode } from '../api/forecastGrids';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;

export function forecastLayerId(variable: string, horizon: number, mode: ForecastMode): string {
  return `forecast-${variable}-h${horizon}-${mode}`;
}

/**
 * Matches SST_COLORMAP_STOPS in backend/services/colormaps.py — the same nine
 * control points the observed SST layer uses, so a forecast and the
 * observation it is compared against read on one scale.
 */
const SST_STOPS = [
  { offset: 0, color: '#3B0F70' },
  { offset: 0.0541, color: '#1E3A8A' },
  { offset: 0.1892, color: '#1D4ED8' },
  { offset: 0.3243, color: '#06B6D4' },
  { offset: 0.4595, color: '#14B8A6' },
  { offset: 0.5946, color: '#22C55E' },
  { offset: 0.7297, color: '#EAB308' },
  { offset: 0.8649, color: '#F97316' },
  { offset: 1, color: '#DC2626' },
];

/** Matches SEQUENTIAL_STOPS in backend/services/colormaps.py (viridis). */
const SEQUENTIAL_STOPS = [
  { offset: 0, color: '#440154' },
  { offset: 0.25, color: '#3B528B' },
  { offset: 0.5, color: '#21918C' },
  { offset: 0.75, color: '#5EC962' },
  { offset: 1, color: '#FDE725' },
];

/** Matches DIVERGING_STOPS in backend/services/colormaps.py. Zero sits at the
 *  near-white centre, which is why the scale must stay symmetric. */
const DIVERGING_STOPS = [
  { offset: 0, color: '#053061' },
  { offset: 0.2, color: '#2166AC' },
  { offset: 0.375, color: '#67A9CF' },
  { offset: 0.475, color: '#D1E5F0' },
  { offset: 0.5, color: '#F7F7F7' },
  { offset: 0.525, color: '#FDDBC7' },
  { offset: 0.625, color: '#EF8A62' },
  { offset: 0.8, color: '#B2182B' },
  { offset: 1, color: '#67001F' },
];

/** The one variable colour-matched to an existing observation layer. Mirrors
 *  `_MATCHED_COLORMAPS` in backend/services/forecast_tiles.py. */
const MATCHED_SCALES: Record<string, { stops: typeof SST_STOPS; min: number; max: number }> = {
  sea_surface_temperature: { stops: SST_STOPS, min: -2, max: 35 },
};

function legendFor(entry: ForecastGridEntry, mode: ForecastMode): LayerLegend {
  if (mode === 'change') {
    return {
      type: 'gradient',
      unit: `${entry.unit} vs today`,
      min: -entry.change_scale,
      max: entry.change_scale,
      stops: DIVERGING_STOPS,
    };
  }

  const matched = MATCHED_SCALES[entry.variable];
  return {
    type: 'gradient',
    unit: entry.unit,
    min: matched ? matched.min : entry.display_min,
    max: matched ? matched.max : entry.display_max,
    stops: matched ? matched.stops : SEQUENTIAL_STOPS,
  };
}

function attributionFor(entry: ForecastGridEntry, horizon: number, mode: ForecastMode): string {
  const skill = entry.skill_scores ? ` Skill vs persistence: ${entry.skill_scores}.` : '';
  const missing =
    entry.missing_covariates.length > 0
      ? ` SCORED WITHOUT ${entry.missing_covariates.join(', ').toUpperCase()}: ` +
        `the model was trained with ${entry.missing_covariates.length === 1 ? 'this covariate' : 'these covariates'}, ` +
        `but no global gridded source exists for ${entry.missing_covariates.length === 1 ? 'it' : 'them'} ` +
        `(Open-Meteo is a point API), so every cell was scored without ${entry.missing_covariates.length === 1 ? 'it' : 'them'}. ` +
        `Accuracy is reduced relative to the point forecast at /dashboard.`
      : '';
  const what =
    mode === 'change'
      ? `Change from the latest observation to +${horizon} days`
      : `Predicted value at +${horizon} days`;

  return (
    `${what}. MODEL OUTPUT, not observation: ${entry.model ?? 'LightGBM'} trained by ` +
    `rolling-origin cross-validation on ${entry.sources.join('; ') || 'Copernicus Marine'}.` +
    `${skill} Grid is ${entry.resolution_deg}° (${entry.cells_scored.toLocaleString()} ocean cells), ` +
    `anchored on observations from ${entry.observation_date ?? 'an unknown date'}, ` +
    `built ${entry.generated_at ?? 'at an unknown time'}.${missing}`
  );
}

/** Every layer one grid entry produces: each trained horizon, in both modes. */
export function forecastLayers(entry: ForecastGridEntry): RasterLayerDescriptor[] {
  if (entry.error) return [];

  const modes: ForecastMode[] = ['absolute', 'change'];
  return entry.horizons.flatMap((horizon) =>
    modes.map((mode) => ({
      id: forecastLayerId(entry.variable, horizon, mode),
      name:
        mode === 'change'
          ? `${entry.label} Change +${horizon}d`
          : `${entry.label} Forecast +${horizon}d`,
      category: 'ocean' as const,
      type: 'raster' as const,
      attribution: attributionFor(entry, horizon, mode),
      defaultOpacity: 0.7,
      defaultVisible: false,
      rasterPaint: { contrast: 0.15, saturation: 0.2 },
      sources: [
        {
          type: 'raster' as const,
          tiles: [
            `${API_BASE_URL}/api/tiles/forecast/${entry.variable}/${horizon}/${mode}/{z}/{x}/{y}.png`,
          ],
          tileSize: 256,
          // The grid is 1°, far coarser than any observation layer here, so
          // there is nothing past this zoom but the GPU's own upsampling.
          maxzoom: 5,
        },
      ],
      legend: legendFor(entry, mode),
    }))
  );
}
