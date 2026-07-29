/**
 * ML prediction API — habitat suitability and harmful-algal-bloom risk.
 *
 * These are **precomputed batch predictions**, not live inference. The models
 * run offline in `machine_learning/`; the backend serves the resulting grids.
 * Practically that means predictions exist only for the region, period and
 * species the export covered, which is why `manifest` carries explicit
 * coverage and caveat fields — the UI is expected to state what exists rather
 * than render empty tiles and let the user guess.
 */

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;

function url(path: string): URL {
  return API_BASE_URL ? new URL(path, API_BASE_URL) : new URL(path, window.location.origin);
}

/** Base for tile URL templates — MapLibre substitutes {z}/{x}/{y} itself. */
export const PREDICTIONS_TILE_BASE = `${API_BASE_URL || ''}/api/predictions`;

export interface SpeciesInfo {
  key: string;
  scientific_name: string;
  label: string;
}

export interface RegionBox {
  name: string;
  west: number;
  east: number;
  south: number;
  north: number;
}

export interface Driver {
  feature: string;
  importance: number;
}

export interface ReliabilityPoint {
  predicted: number;
  observed: number;
  n: number;
}

export interface HabitatProduct {
  title: string;
  subtitle: string;
  species: SpeciesInfo[];
  months: number[];
  year: number;
  region: RegionBox;
  training_window: [string, string];
  validation: string;
  /** Cross-validated skill per model tier, keyed by model name. */
  metrics: Record<string, Record<string, number>>;
  holdout: Array<{
    model: string;
    roc_auc: number;
    pr_auc: number;
    tss: number;
    boyce: number;
  }>;
  drivers: Driver[];
  value_label: string;
  caveats: string[];
}

export interface HabHorizon {
  horizon_days: number;
  pr_auc: number | null;
  persistence_pr_auc: number | null;
  /** Whether the model actually beat "it is blooming now, so it will be
   * blooming then". A model that does not is not worth shipping, so this is
   * surfaced rather than buried in a metrics table. */
  beats_baseline: boolean;
  roc_auc: number | null;
  brier: number | null;
  brier_uncalibrated: number | null;
  tss: number | null;
  reliability: ReliabilityPoint[];
  drivers: Driver[];
}

export interface HabProduct {
  title: string;
  subtitle: string;
  horizons: HabHorizon[];
  dates: string[];
  region: RegionBox;
  training_window: [string, string];
  validation: string;
  value_label: string;
  caveats: string[];
}

export interface PredictionManifest {
  generated: string;
  products: {
    habitat: HabitatProduct;
    hab: HabProduct;
  };
}

export interface HabitatPoint {
  species: string;
  month: number;
  suitability: number | null;
  outside_coverage: boolean;
  value_label: string;
}

export interface HabPoint {
  horizon_days: number;
  date: string;
  risk: number | null;
  outside_coverage: boolean;
  value_label: string;
}

export async function fetchPredictionManifest(
  signal?: AbortSignal
): Promise<PredictionManifest> {
  const response = await fetch(url('/api/predictions/manifest'), { signal });
  if (!response.ok) {
    // 503 is the expected shape when the offline export has not been run —
    // worth distinguishing so the page can say so instead of "network error".
    if (response.status === 503) {
      throw new Error(
        'Prediction exports are not available yet. Run the export step in machine_learning/.'
      );
    }
    throw new Error(`Failed to load prediction manifest (${response.status})`);
  }
  return response.json();
}

export function habitatTileUrl(species: string, month: number): string {
  return `${PREDICTIONS_TILE_BASE}/habitat/${species}/${month}/{z}/{x}/{y}.png`;
}

export function habTileUrl(horizon: number): string {
  return `${PREDICTIONS_TILE_BASE}/hab/${horizon}/{z}/{x}/{y}.png`;
}

export async function fetchHabitatPoint(
  species: string,
  month: number,
  latitude: number,
  longitude: number,
  signal?: AbortSignal
): Promise<HabitatPoint> {
  const u = url('/api/predictions/habitat/point');
  u.searchParams.set('species', species);
  u.searchParams.set('month', String(month));
  u.searchParams.set('latitude', String(latitude));
  u.searchParams.set('longitude', String(longitude));

  const response = await fetch(u, { signal });
  if (!response.ok) throw new Error(`Habitat prediction lookup failed (${response.status})`);
  return response.json();
}

export async function fetchHabPoint(
  horizon: number,
  latitude: number,
  longitude: number,
  date?: string,
  signal?: AbortSignal
): Promise<HabPoint> {
  const u = url('/api/predictions/hab/point');
  u.searchParams.set('horizon', String(horizon));
  u.searchParams.set('latitude', String(latitude));
  u.searchParams.set('longitude', String(longitude));
  if (date) u.searchParams.set('date', date);

  const response = await fetch(u, { signal });
  if (!response.ok) throw new Error(`Bloom risk lookup failed (${response.status})`);
  return response.json();
}
