import type { CursorCoordinates } from '../types';
import { API_BASE_URL } from '../../../utils/apiBase';

/**
 * A drift trajectory forecast — `GET /api/ocean/drift/trajectory`. Not the
 * live drift *field* `drift.ts` serves (a single-snapshot particle layer):
 * this is an ensemble of RK4-integrated tracks over 6-96h, the "where will
 * this object be" question TODO.md calls the trajectory half of the drift
 * feature. Kept as its own file rather than added to `drift.ts` because the
 * response shape is structurally different (an ensemble of tracks, not a
 * point/texture) — the same "same domain, different shape" split
 * `forecastVectors.ts` already draws alongside `currents.ts`/`wind.ts`.
 */
export interface TrajectoryPoint {
  lat: number;
  lon: number;
  hour: number;
}

export interface TrajectoryMember {
  track: TrajectoryPoint[];
  alpha_used: number;
}

export interface DriftTrajectoryResponse {
  start: { lat: number; lon: number; time: string };
  horizon_hours: number;
  n_members: number;
  leeway_alpha: number;
  median_track: TrajectoryPoint[];
  members: TrajectoryMember[];
  provenance: { current: string; stokes: string; wind_leeway: string };
  degraded_terms: string[];
  note: string;
}

function url(path: string): URL {
  return API_BASE_URL ? new URL(path, API_BASE_URL) : new URL(path, window.location.origin);
}

// Leeway presets are `drift.ts`'s (`fetchLeewayPresets`) — the same list the
// live drift field's layer picker already uses, not duplicated here.

export async function fetchDriftTrajectory(
  start: CursorCoordinates,
  preset: string,
  horizonHours: number,
  signal?: AbortSignal
): Promise<DriftTrajectoryResponse> {
  const target = url('/api/ocean/drift/trajectory');
  target.searchParams.set('lat', String(start.lat));
  target.searchParams.set('lon', String(start.lng));
  target.searchParams.set('preset', preset);
  target.searchParams.set('horizon_hours', String(horizonHours));

  const response = await fetch(target, { signal });
  if (!response.ok) {
    let detail = '';
    try {
      detail = (await response.json())?.detail ?? '';
    } catch {
      // The error body isn't always JSON (e.g. a proxy timeout) — the plain
      // status is still a usable message either way.
    }
    throw new Error(detail || `Drift trajectory request failed with status ${response.status}`);
  }
  return (await response.json()) as DriftTrajectoryResponse;
}
