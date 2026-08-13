import type { CursorCoordinates } from '../types';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;

export interface CurrentsPointResponse {
  speed_ms: number | null;
  /**
   * Oceanographic convention — the direction the water flows *toward*, which
   * is the opposite of wind's "from". Named in full rather than as a bare
   * `direction_deg` precisely because the two are 180 degrees apart and a
   * reader who assumes the wrong one gets a plausible, wrong answer.
   */
  direction_toward_deg: number | null;
  direction_compass: string | null;
  u_ms: number | null;
  v_ms: number | null;
  is_land_or_no_data: boolean;
  timestamp: string;
  source: string;
}

export interface CurrentsMetaResponse {
  timestamp: string;
  source: string;
  unit: string;
  speed_max_legend: number;
  u_min: number;
  u_max: number;
  v_min: number;
  v_max: number;
  lon_west: number;
  lon_east: number;
  lat_south: number;
  lat_north: number;
}

function url(path: string): URL {
  return API_BASE_URL ? new URL(path, API_BASE_URL) : new URL(path, window.location.origin);
}

export function currentsFieldTextureUrl(): string {
  return url('/api/tiles/currents/field.png').toString();
}

export async function fetchCurrentsPoint(
  location: CursorCoordinates,
  signal?: AbortSignal
): Promise<CurrentsPointResponse> {
  const target = url('/api/ocean/currents/point');
  target.searchParams.set('lat', String(location.lat));
  target.searchParams.set('lon', String(location.lng));

  const response = await fetch(target, { signal });
  if (!response.ok) {
    throw new Error(`Currents point request failed with status ${response.status}`);
  }
  return (await response.json()) as CurrentsPointResponse;
}

export async function fetchCurrentsMeta(signal?: AbortSignal): Promise<CurrentsMetaResponse> {
  const response = await fetch(url('/api/ocean/currents/meta'), { signal });
  if (!response.ok) {
    throw new Error(`Currents meta request failed with status ${response.status}`);
  }
  return (await response.json()) as CurrentsMetaResponse;
}
