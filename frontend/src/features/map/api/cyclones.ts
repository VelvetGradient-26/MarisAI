import { API_BASE_URL } from '../../../utils/apiBase';

/**
 * Active tropical cyclones from GDACS — `GET /api/ocean/cyclones`. Each
 * position is the storm's most recently reported fix, not a live track; see
 * `services/cyclones.py`.
 */
export interface Cyclone {
  name: string;
  latitude: number;
  longitude: number;
  alert_level: string | null;
  max_wind_kmh: number | null;
  category: string | null;
  affected_countries: string[];
  active_since: string | null;
  forecast_until: string | null;
  last_updated: string | null;
  source: string;
  report_url: string | null;
}

export interface CyclonesResponse {
  cyclones: Cyclone[];
  count: number;
  source: string;
  note: string;
}

function url(path: string): URL {
  return API_BASE_URL ? new URL(path, API_BASE_URL) : new URL(path, window.location.origin);
}

export async function fetchCyclones(signal?: AbortSignal): Promise<CyclonesResponse> {
  const response = await fetch(url('/api/ocean/cyclones'), { signal });
  if (!response.ok) {
    throw new Error(`Cyclone list unavailable (${response.status})`);
  }
  return (await response.json()) as CyclonesResponse;
}

/**
 * One point per storm's last reported fix. No bbox filtering: GDACS's whole
 * active list is a handful of storms worldwide, the same reasoning
 * `useDetectorCells` documents for heatwaves/upwelling.
 */
export function cyclonesToGeoJson(cyclones: Cyclone[]): GeoJSON.FeatureCollection {
  return {
    type: 'FeatureCollection',
    features: cyclones.map((cyclone) => ({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [cyclone.longitude, cyclone.latitude] },
      properties: { ...cyclone },
    })),
  };
}
