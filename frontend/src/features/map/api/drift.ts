import type { CursorCoordinates } from '../types';
import type { CurrentsMetaResponse } from './currents';

import { API_BASE_URL } from '../../../utils/apiBase';

/**
 * The combined drift field — surface current + Stokes drift + wind leeway.
 *
 * Parameterised on a leeway coefficient because that coefficient belongs to the
 * *drifting object*, not to the ocean: a swamped hull and an undrogued life raft
 * in the same water take measurably different tracks. So there is no single
 * correct field to fetch, and the preset list comes from the backend rather than
 * being hardcoded here — the coefficients are a modelling choice the server
 * owns, and a client that baked in 0.035 for a person in the water would keep
 * asserting it after that value was revised.
 */
export interface LeewayPreset {
  key: string;
  label: string;
  alpha: number;
  note: string;
}

/** One term's contribution at a point, reported beside the total. The question
 *  a drift number always provokes is "which of the three put it there". */
export interface DriftTerm {
  speed_ms: number;
  u_ms: number;
  v_ms: number;
  weight: number;
  contribution_ms: number;
  timestamp?: string;
}

export interface DriftPointResponse {
  latitude: number;
  longitude: number;
  leeway_alpha: number;
  speed_ms: number | null;
  u_ms?: number;
  v_ms?: number;
  direction_toward_deg: number | null;
  direction_compass: string | null;
  is_land_or_no_data: boolean;
  terms: Record<string, DriftTerm>;
  source: string;
  note?: string;
  /** Present when a term was unavailable but the water terms still answered. */
  degraded_reason?: string;
  unavailable_reason?: string;
}

export interface DriftMetaResponse extends CurrentsMetaResponse {
  leeway_alpha: number;
  /** The three inputs' own timesteps. `timestamp` is the *oldest* of them: a
   *  composite is only as current as its stalest term, and reporting the
   *  freshest would overstate it by however far the wind blend lags. */
  component_timestamps: Record<string, string>;
}

function url(path: string): URL {
  return API_BASE_URL ? new URL(path, API_BASE_URL) : new URL(path, window.location.origin);
}

export function driftFieldTextureUrl(alpha: number): string {
  const target = url('/api/tiles/drift/field.png');
  target.searchParams.set('alpha', String(alpha));
  return target.toString();
}

export async function fetchLeewayPresets(signal?: AbortSignal): Promise<LeewayPreset[]> {
  const response = await fetch(url('/api/ocean/drift/presets'), { signal });
  if (!response.ok) {
    throw new Error(`Leeway preset request failed with status ${response.status}`);
  }
  const body = (await response.json()) as { presets: LeewayPreset[] };
  return body.presets;
}

export function fetchDriftMeta(alpha: number) {
  return async (signal?: AbortSignal): Promise<DriftMetaResponse> => {
    const target = url('/api/ocean/drift/meta');
    target.searchParams.set('alpha', String(alpha));
    const response = await fetch(target, { signal });
    if (!response.ok) {
      throw new Error(`Drift meta request failed with status ${response.status}`);
    }
    return (await response.json()) as DriftMetaResponse;
  };
}

export async function fetchDriftPoint(
  location: CursorCoordinates,
  alpha: number,
  signal?: AbortSignal
): Promise<DriftPointResponse> {
  const target = url('/api/ocean/drift/point');
  target.searchParams.set('lat', String(location.lat));
  target.searchParams.set('lon', String(location.lng));
  target.searchParams.set('alpha', String(alpha));

  const response = await fetch(target, { signal });
  if (!response.ok) {
    throw new Error(`Drift point request failed with status ${response.status}`);
  }
  return (await response.json()) as DriftPointResponse;
}
