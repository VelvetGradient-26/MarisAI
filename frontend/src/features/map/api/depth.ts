import type { CursorCoordinates } from '../types';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;

export interface DepthResponse {
  elevation_m: number;
  depth_m: number | null;
  is_land: boolean;
}

export async function fetchDepth(
  location: CursorCoordinates,
  signal?: AbortSignal
): Promise<DepthResponse> {
  const url = API_BASE_URL
    ? new URL('/api/ocean/depth', API_BASE_URL)
    : new URL('/api/ocean/depth', window.location.origin);
  url.searchParams.set('lat', String(location.lat));
  url.searchParams.set('lon', String(location.lng));

  const response = await fetch(url, { signal });
  if (!response.ok) {
    throw new Error(`Depth request failed with status ${response.status}`);
  }

  return (await response.json()) as DepthResponse;
}
