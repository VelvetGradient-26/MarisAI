/**
 * Forecast map API — the forecasting engine's global grids.
 *
 * These are **precomputed grids**, not live inference. `forecasting/
 * grid_predictor.py` scores every ocean cell on a schedule and the backend
 * paints the result; a tile request never runs a model. Practically that means
 * a variable appears here only once someone has trained it *and* built its
 * grid, which is why the catalog is fetched rather than hardcoded — a newly
 * built grid becomes a map layer with no frontend edit.
 *
 * Tile URLs are built in `layers/forecastLayers.ts`, alongside the descriptors
 * that use them, matching how the prediction layers are arranged.
 */

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;

function url(path: string): URL {
  return API_BASE_URL ? new URL(path, API_BASE_URL) : new URL(path, window.location.origin);
}

export type ForecastMode = 'absolute' | 'change';

export interface ForecastGridEntry {
  variable: string;
  label: string;
  unit: string;
  horizons: number[];
  resolution_deg: number;
  generated_at: string | null;
  observation_date: string | null;
  trained_at: string | null;
  model: string | null;
  sources: string[];
  display_min: number;
  display_max: number;
  change_scale: number;
  skill_scores: string | null;
  cells_scored: number;
  /**
   * Covariates the model was trained on that have no global gridded source, so
   * the grid was scored without them. Surfaced in the layer's attribution
   * rather than dropped: LightGBM absorbs a missing feature silently, and a
   * degraded forecast that looks exactly as confident as a complete one is the
   * failure this field exists to prevent.
   */
  missing_covariates: string[];
  error?: string;
}

export async function fetchForecastGridCatalog(): Promise<ForecastGridEntry[]> {
  const response = await fetch(url('/api/tiles/forecast/catalog').toString());
  if (!response.ok) {
    throw new Error(`Forecast grid catalog failed: ${response.status}`);
  }
  const payload = (await response.json()) as { grids: ForecastGridEntry[] };
  return payload.grids ?? [];
}

export interface ForecastGridPoint {
  variable: string;
  label: string;
  unit: string;
  horizon_days: number;
  forecast: number | null;
  last_observed: number | null;
  change: number | null;
  observation_date: string | null;
  generated_at: string | null;
  resolution_deg: number;
}

export async function fetchForecastPoint(
  variable: string,
  horizon: number,
  latitude: number,
  longitude: number
): Promise<ForecastGridPoint> {
  const target = url('/api/tiles/forecast/point');
  target.searchParams.set('variable', variable);
  target.searchParams.set('horizon', String(horizon));
  target.searchParams.set('latitude', String(latitude));
  target.searchParams.set('longitude', String(longitude));

  const response = await fetch(target.toString());
  if (!response.ok) {
    throw new Error(`Forecast point failed: ${response.status}`);
  }
  return (await response.json()) as ForecastGridPoint;
}
