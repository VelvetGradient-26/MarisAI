import type { CursorCoordinates } from '../types';
import { API_BASE_URL } from '../../../utils/apiBase';

/**
 * India EEZ / India-Sri Lanka IMBL / Marine Protected Area proximity —
 * `GET /api/ocean/geofence`. Pure local geometry on the backend (see
 * `services/geofencing.py`), so this call never fails on a cold cache.
 */
export interface GeofenceProtectedArea {
  name: string;
  state: string;
  inside: boolean;
  distance_km: number;
  /** A real box, not a simplification — every registered area is a
   * hand-drawn box around its published centre; see the backend docstring. */
  bounds: { south: number; west: number; north: number; east: number };
}

export interface GeofenceResponse {
  india_eez: {
    inside: boolean;
    zone: 'mainland' | 'andaman_and_nicobar' | null;
    coverage: string;
    source: string;
  };
  india_sri_lanka_imbl: {
    distance_km: number;
    near: boolean;
    proximity_threshold_km: number;
    source: string;
    nearest_point: { latitude: number; longitude: number };
  };
  nearby_protected_areas: GeofenceProtectedArea[];
  note: string;
}

function url(path: string): URL {
  return API_BASE_URL ? new URL(path, API_BASE_URL) : new URL(path, window.location.origin);
}

export async function fetchGeofence(
  location: CursorCoordinates,
  signal?: AbortSignal
): Promise<GeofenceResponse> {
  const u = url('/api/ocean/geofence');
  u.searchParams.set('lat', String(location.lat));
  u.searchParams.set('lon', String(location.lng));

  const response = await fetch(u, { signal });
  if (!response.ok) {
    throw new Error(`Geofence check failed with status ${response.status}`);
  }
  return (await response.json()) as GeofenceResponse;
}
