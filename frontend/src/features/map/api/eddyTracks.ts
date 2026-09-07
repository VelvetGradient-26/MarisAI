import { API_BASE_URL } from '../../../utils/apiBase';

/**
 * Frame-to-frame eddy identity — `services/eddy_tracking.py`, distinct from
 * the detection-only `/api/ocean/eddies` (`api/eddies.ts`). A track carries
 * an id, an age, and (with `include_path=true`) the position history that
 * makes it drawable as a path, none of which a bare detection has.
 */
export interface EddyTrackFix {
  timestamp: string;
  latitude: number;
  longitude: number;
  radius_km: number;
}

export interface EddyTrack {
  track_id: string;
  polarity: 'cyclonic' | 'anticyclonic';
  latitude: number;
  longitude: number;
  radius_km: number;
  area_km2: number;
  max_speed_ms: number;
  mean_speed_ms: number;
  hits: number;
  age_hours: number;
  first_seen: string;
  last_seen: string;
  /** Only present when fetched with `include_path=true` — the list endpoint
   * omits it by default (a few hundred tracks' full history would be most
   * of the payload for a view that usually just needs current position). */
  path?: EddyTrackFix[];
}

export interface EddyTracksResponse {
  last_processed_timestamp: string | null;
  active_tracks: number;
  matched: number;
  returned: number;
  gate_cells: number;
  max_misses: number;
  note: string;
  tracks: EddyTrack[];
}

function url(path: string): string {
  return `${API_BASE_URL}${path}`;
}

export interface EddyTrackBounds {
  south: number;
  west: number;
  north: number;
  east: number;
}

export async function fetchEddyTracks(
  bounds: EddyTrackBounds | null,
  limit: number,
  signal?: AbortSignal
): Promise<EddyTracksResponse> {
  const params = new URLSearchParams({ limit: String(limit), include_path: 'true' });
  if (bounds) {
    params.set('bbox', `${bounds.south},${bounds.west},${bounds.north},${bounds.east}`);
  }
  const response = await fetch(url(`/api/ocean/eddies/tracks?${params}`), { signal });
  if (!response.ok) {
    throw new Error(`Eddy track lookup unavailable (${response.status})`);
  }
  return (await response.json()) as EddyTracksResponse;
}

/**
 * One `LineString` per track's path plus one `Point` at its latest fix —
 * same `kind`-discriminated shape `driftTrajectoryLayer()`'s ensemble
 * already uses, so the layer registry entry can mirror that paint pattern
 * exactly rather than inventing a new one.
 *
 * Longitudes are left un-normalised past ±180, same reason `eddiesToGeoJson`
 * does: MapLibre wraps them itself, and clamping here would tear a path in
 * half at the antimeridian.
 */
export function eddyTracksToGeoJson(tracks: EddyTrack[]): GeoJSON.FeatureCollection {
  const features: GeoJSON.Feature[] = [];

  for (const track of tracks) {
    if (track.path && track.path.length > 1) {
      features.push({
        type: 'Feature',
        geometry: {
          type: 'LineString',
          coordinates: track.path.map((fix) => [fix.longitude, fix.latitude]),
        },
        properties: { ...track, kind: 'path' },
      });
    }
    features.push({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [track.longitude, track.latitude] },
      properties: { ...track, kind: 'latest' },
    });
  }

  return { type: 'FeatureCollection', features };
}
