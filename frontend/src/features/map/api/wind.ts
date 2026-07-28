import type { CursorCoordinates } from '../types';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;

export interface WindPointResponse {
  speed_ms: number | null;
  direction_from_deg: number | null;
  direction_compass: string | null;
  beaufort: { force: number; label: string } | null;
  is_land_or_no_data: boolean;
  timestamp: string;
  source: string;
}

export interface WindMetaResponse {
  timestamp: string;
  source: string;
  unit: string;
  speed_max_legend: number;
  u_min: number;
  u_max: number;
  v_min: number;
  v_max: number;
}

function url(path: string): URL {
  return API_BASE_URL ? new URL(path, API_BASE_URL) : new URL(path, window.location.origin);
}

export function windFieldTextureUrl(): string {
  return url('/api/tiles/wind/field.png').toString();
}

export async function fetchWindPoint(
  location: CursorCoordinates,
  signal?: AbortSignal
): Promise<WindPointResponse> {
  const u = url('/api/ocean/wind/point');
  u.searchParams.set('lat', String(location.lat));
  u.searchParams.set('lon', String(location.lng));

  const response = await fetch(u, { signal });
  if (!response.ok) {
    throw new Error(`Wind point request failed with status ${response.status}`);
  }
  return (await response.json()) as WindPointResponse;
}

export async function fetchWindMeta(signal?: AbortSignal): Promise<WindMetaResponse> {
  const response = await fetch(url('/api/ocean/wind/meta'), { signal });
  if (!response.ok) {
    throw new Error(`Wind meta request failed with status ${response.status}`);
  }
  return (await response.json()) as WindMetaResponse;
}
