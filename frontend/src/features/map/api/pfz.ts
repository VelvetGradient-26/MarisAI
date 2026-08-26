import type { CursorCoordinates } from '../types';
import { API_BASE_URL } from '../../../utils/apiBase';

/**
 * Heuristic potential-fishing-zone screening — `GET /api/ocean/pfz`.
 *
 * A screening aid, not a validated PFZ advisory: see the backend's own
 * `services/pfz.py` docstring. Every zone is a candidate cell ranked by
 * chlorophyll-above-local-median plus an SST band, never a guarantee.
 */
export interface PfzZone {
  latitude: number;
  longitude: number;
  chlorophyll_mg_m3: number;
  sst_c: number;
  score: number;
  reasons: string[];
}

export interface PfzResponse {
  available: boolean;
  reason?: string;
  candidates_scanned?: number;
  zones?: PfzZone[];
  method?: string;
  sst_source?: string;
  chlorophyll_source?: string;
  chlorophyll_stale?: boolean;
  note?: string;
}

function url(path: string): URL {
  return API_BASE_URL ? new URL(path, API_BASE_URL) : new URL(path, window.location.origin);
}

export async function fetchPfz(
  location: CursorCoordinates,
  radiusKm: number,
  signal?: AbortSignal
): Promise<PfzResponse> {
  const u = url('/api/ocean/pfz');
  u.searchParams.set('lat', String(location.lat));
  u.searchParams.set('lon', String(location.lng));
  u.searchParams.set('radius_km', String(radiusKm));

  const response = await fetch(u, { signal });
  if (!response.ok) {
    throw new Error(`Fishing-zone screening failed with status ${response.status}`);
  }
  return (await response.json()) as PfzResponse;
}
