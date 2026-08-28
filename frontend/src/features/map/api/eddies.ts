import { API_BASE_URL } from '../../../utils/apiBase';

/**
 * Mesoscale eddies detected in the live surface-current field.
 *
 * Detection only — nothing here is tracked between refreshes, so an eddy has
 * no age and no trajectory. That is a deliberate scope line rather than a
 * missing field: matching features frame to frame is its own problem, and a
 * track drawn from a matcher that flickers is an artefact presented as an
 * observation.
 */
export interface EddyFeatureProperties {
  latitude: number;
  longitude: number;
  polarity: 'cyclonic' | 'anticyclonic';
  radius_km: number;
  area_km2: number;
  vorticity_per_s: number;
  max_speed_ms: number;
  mean_speed_ms: number;
  cells: number;
}

export interface EddiesResponse {
  timestamp: string;
  computed_at: string;
  source: string;
  method: string;
  threshold: { okubo_weiss: number; sigma_w: number; factor: number };
  coverage: {
    grid_spacing_deg: number;
    min_resolvable_radius_km: number;
    max_radius_km: number;
    latitude_band_deg: [number, number];
  };
  detected: number;
  matched: number;
  returned: number;
  limits: string[];
  eddies: EddyFeatureProperties[];
}

function url(path: string): string {
  return `${API_BASE_URL}${path}`;
}

export interface EddyBounds {
  south: number;
  west: number;
  north: number;
  east: number;
}

export async function fetchEddies(
  bounds: EddyBounds | null,
  limit: number,
  signal?: AbortSignal
): Promise<EddiesResponse> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (bounds) {
    params.set('bbox', `${bounds.south},${bounds.west},${bounds.north},${bounds.east}`);
  }
  const response = await fetch(url(`/api/ocean/eddies?${params}`), { signal });
  if (!response.ok) {
    throw new Error(`Eddy detection unavailable (${response.status})`);
  }
  return (await response.json()) as EddiesResponse;
}

/** Vertices in a drawn eddy ring. 48 is smooth at the zooms an eddy is
 *  legible at, and 2,000 of them is still a small GeoJSON payload. */
const RING_VERTICES = 48;

const EARTH_RADIUS_KM = 6371;

/**
 * One eddy as a true-scale ring plus its centre.
 *
 * Drawn at its real size rather than as a fixed-pixel dot, because the size is
 * the measurement — a reader takes the circle as the feature's extent, and a
 * symbol that stays the same size at every zoom would be asserting something
 * the detector never said. The ring is the *equivalent* radius of the region
 * where rotation beats strain, which is round by construction and not the
 * feature's real outline; the tooltip says so.
 *
 * Longitudes are deliberately left un-normalised past ±180. MapLibre wraps
 * them itself, and clamping here is what would tear a ring in half on the
 * antimeridian.
 */
export function eddiesToGeoJson(eddies: EddyFeatureProperties[]): GeoJSON.FeatureCollection {
  const features: GeoJSON.Feature[] = [];

  for (const eddy of eddies) {
    const latRadius = (eddy.radius_km / EARTH_RADIUS_KM) * (180 / Math.PI);
    const lonRadius = latRadius / Math.max(Math.cos((eddy.latitude * Math.PI) / 180), 0.05);

    const ring: GeoJSON.Position[] = [];
    for (let i = 0; i <= RING_VERTICES; i += 1) {
      const angle = (i / RING_VERTICES) * 2 * Math.PI;
      ring.push([
        eddy.longitude + lonRadius * Math.cos(angle),
        eddy.latitude + latRadius * Math.sin(angle),
      ]);
    }

    features.push({
      type: 'Feature',
      geometry: { type: 'Polygon', coordinates: [ring] },
      properties: { ...eddy },
    });
    features.push({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [eddy.longitude, eddy.latitude] },
      properties: { ...eddy },
    });
  }

  return { type: 'FeatureCollection', features };
}
