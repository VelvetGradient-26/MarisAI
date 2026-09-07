import { API_BASE_URL } from '../../../utils/apiBase';

function url(path: string): URL {
  return new URL(path, API_BASE_URL || window.location.origin);
}

/**
 * One vessel's live AIS state. Everything but `mmsi` is optional by design:
 * the backend strips nulls, so an absent key means "this vessel has not
 * broadcast that yet", which is different from a null value. Position and
 * motion arrive within seconds; identity and voyage details take up to ~6
 * minutes, so a vessel is routinely on the map before it has a ship type.
 */
export interface VesselProperties {
  mmsi: number;
  name?: string;
  /** Speed over ground, knots. */
  sog?: number;
  /** Course over ground, degrees true. */
  cog?: number;
  /** Where the bow points — differs from course when set by wind/current. */
  heading?: number;
  nav_status?: string;
  ship_type?: string;
  call_sign?: string;
  imo?: number;
  destination?: string;
  length_m?: number;
  beam_m?: number;
  draught_m?: number;
  /** AIS transmits no year, so this is a bare "DD MMM HH:MM". */
  eta?: string;
  last_report?: string;
}

export interface VesselCollection {
  type: 'FeatureCollection';
  features: Array<{
    type: 'Feature';
    geometry: { type: 'Point'; coordinates: [number, number] };
    properties: VesselProperties;
  }>;
  /** How many were actually in view, which can exceed `returned` — lets the
   * UI say "showing 1,500 of 4,200" instead of implying it shows everything. */
  total_in_view: number;
  returned: number;
  /** False when the upstream websocket is down or unconfigured. Not an
   * error: the response is a valid, empty collection. */
  connected: boolean;
}

/** The feed's own state, independent of any bbox — `connected` here is the
 * same flag `fetchVessels` already piggybacks per-request, but `configured`
 * (whether an AIS key exists at all) is new: without it, "not configured"
 * and "configured but briefly disconnected" render identically. */
export interface VesselFeedStatusResponse {
  connected: boolean;
  configured: boolean;
  tracked_vessels: number;
  messages_seen: number;
}

export async function fetchVesselFeedStatus(signal?: AbortSignal): Promise<VesselFeedStatusResponse> {
  const response = await fetch(url('/api/vessels/status'), { signal });
  if (!response.ok) throw new Error(`Vessel feed status lookup failed (${response.status})`);
  return response.json();
}

export async function fetchVessels(
  bounds: { west: number; south: number; east: number; north: number },
  limit: number,
  signal?: AbortSignal
): Promise<VesselCollection> {
  const u = url('/api/vessels');
  u.searchParams.set('west', String(bounds.west));
  u.searchParams.set('south', String(bounds.south));
  u.searchParams.set('east', String(bounds.east));
  u.searchParams.set('north', String(bounds.north));
  u.searchParams.set('limit', String(limit));

  const response = await fetch(u, { signal });
  if (!response.ok) throw new Error(`Vessel lookup failed (${response.status})`);
  return response.json();
}
