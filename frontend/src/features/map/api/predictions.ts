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
 * Point lookups live here, and so does one manifest read: `fetchPredictionManifest`,
 * for a "last exported" freshness note on the habitat/HAB layer toggles —
 * nothing else in this file's shape needed the manifest, since the model's
 * full skill/drivers/caveats stay documented at /docs, hand-authored rather
 * than rendered live from this endpoint. Tile URLs are built inline in
 * `layers/layerRegistry.ts`, alongside the layer that uses them.
 */

import { API_BASE_URL } from '../../../utils/apiBase';

function url(path: string): URL {
  return API_BASE_URL ? new URL(path, API_BASE_URL) : new URL(path, window.location.origin);
}

export interface PredictionDriver {
  feature: string;
  label: string;
  value: number | null;
  contribution: number;
  direction: 'increases' | 'decreases';
}

export interface HabitatPoint {
  species: string;
  month: number;
  suitability: number | null;
  outside_coverage: boolean;
  value_label: string;
  /** Top SHAP drivers for this cell, strongest first. Null when the export
   * predates this field, the manifest's feature-name lookup is missing, or
   * the cell has no suitability value (land / outside coverage). */
  drivers: PredictionDriver[] | null;
}

export interface HabPoint {
  horizon_days: number;
  date: string;
  risk: number | null;
  outside_coverage: boolean;
  value_label: string;
  /** Top SHAP drivers for this cell, strongest first. Null when the export
   * predates this field, the manifest's feature-name lookup is missing, or
   * the cell has no risk value (land / outside coverage). */
  drivers: PredictionDriver[] | null;
}

/** Only the fields a freshness note needs — the manifest also carries full
 * per-product metrics/holdout/drivers/SHAP config, deliberately untyped
 * here since nothing in the frontend reads them (they're hand-authored at
 * /docs instead; see this file's header comment). */
export interface PredictionManifest {
  generated: string;
  products: Record<string, { title: string }>;
}

export async function fetchPredictionManifest(signal?: AbortSignal): Promise<PredictionManifest> {
  const response = await fetch(url('/api/predictions/manifest'), { signal });
  if (!response.ok) throw new Error(`Prediction manifest lookup failed (${response.status})`);
  return response.json();
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
