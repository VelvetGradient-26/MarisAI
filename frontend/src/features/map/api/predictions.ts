/**
 * ML prediction API — habitat suitability and harmful-algal-bloom risk.
 *
 * These are **precomputed batch predictions**, not live inference. The models
 * run offline in `machine_learning/`; the backend serves the resulting grids.
 * Practically that means predictions exist only for the region, period and
 * species the export covered, which is why every response distinguishes
 * "outside the model's region" from "no value here" — the UI is expected to
 * state what exists rather than render nothing and let the user guess.
 *
 * Only point lookups live here. Tile URLs are built inline in
 * `layers/layerRegistry.ts`, alongside the layer that uses them, and the
 * export manifest is no longer read by the frontend at all — the model's
 * skill, drivers and caveats are documented at /docs.
 */

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;

function url(path: string): URL {
  return API_BASE_URL ? new URL(path, API_BASE_URL) : new URL(path, window.location.origin);
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
