import type { CursorCoordinates } from '../types';
import { API_BASE_URL } from '../../../utils/apiBase';

/**
 * Hazard-aware A* route planning — `GET /api/ocean/route`. See the backend's
 * `services/routing.py` for what the search grid does and does not model
 * (no vessel profile, wave hazard only, live GEBCO + Open-Meteo fetch).
 */
export interface RouteWaypoint {
  latitude: number;
  longitude: number;
  wave_height_m: number | null;
  wind_speed: number | null;
  wind_speed_unit: string | null;
}

export interface RouteResponse {
  distance_km: number;
  great_circle_km: number;
  waypoints: RouteWaypoint[];
  max_wave_height_m: number | null;
  hazard_level: 'calm' | 'caution' | 'hazardous' | 'unknown';
  search_grid_nodes: number;
  search_grid_spacing_deg: number;
  note: string;
}

function url(path: string): URL {
  return API_BASE_URL ? new URL(path, API_BASE_URL) : new URL(path, window.location.origin);
}

export async function fetchRoute(
  start: CursorCoordinates,
  end: CursorCoordinates,
  signal?: AbortSignal
): Promise<RouteResponse> {
  const u = url('/api/ocean/route');
  u.searchParams.set('start_lat', String(start.lat));
  u.searchParams.set('start_lon', String(start.lng));
  u.searchParams.set('end_lat', String(end.lat));
  u.searchParams.set('end_lon', String(end.lng));

  const response = await fetch(u, { signal });
  if (!response.ok) {
    let detail = '';
    try {
      detail = (await response.json())?.detail ?? '';
    } catch {
      // The error body isn't always JSON (e.g. a proxy timeout) — the plain
      // status is still a usable message either way.
    }
    throw new Error(detail || `Route planning failed with status ${response.status}`);
  }
  return (await response.json()) as RouteResponse;
}
