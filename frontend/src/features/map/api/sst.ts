import type { CursorCoordinates } from '../types';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;

export interface SstPointResponse {
  temperature_c: number | null;
  is_land_or_no_data: boolean;
  timestamp: string;
  source: string;
  depth_m: number;
}

export interface SstMetaResponse {
  timestamp: string;
  source: string;
  depth_m: number;
  unit: string;
  min: number;
  max: number;
}

function url(path: string): URL {
  return API_BASE_URL ? new URL(path, API_BASE_URL) : new URL(path, window.location.origin);
}

export async function fetchSstPoint(
  location: CursorCoordinates,
  signal?: AbortSignal
): Promise<SstPointResponse> {
  const u = url('/api/ocean/sst/point');
  u.searchParams.set('lat', String(location.lat));
  u.searchParams.set('lon', String(location.lng));

  const response = await fetch(u, { signal });
  if (!response.ok) {
    throw new Error(`SST point request failed with status ${response.status}`);
  }
  return (await response.json()) as SstPointResponse;
}

export async function fetchSstMeta(signal?: AbortSignal): Promise<SstMetaResponse> {
  const response = await fetch(url('/api/ocean/sst/meta'), { signal });
  if (!response.ok) {
    throw new Error(`SST meta request failed with status ${response.status}`);
  }
  return (await response.json()) as SstMetaResponse;
}
