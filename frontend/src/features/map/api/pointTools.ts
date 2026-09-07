/**
 * The four point tools that were previously reachable only by asking the
 * chat assistant: marine risk, tide-gauge, ARGO float profile, literature
 * search. Same local `url()` + `fetch` + thrown `Error` pattern every
 * `features/map/api/*.ts` file already uses — see `api/sst.ts`/`api/pfz.ts`.
 */

import { API_BASE_URL } from '../../../utils/apiBase';

function url(path: string): URL {
  return API_BASE_URL ? new URL(path, API_BASE_URL) : new URL(path, window.location.origin);
}

async function extractErrorMessage(response: Response, fallback: string): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: string | Array<{ msg?: string }> };
    if (typeof body?.detail === 'string') return body.detail;
    if (Array.isArray(body?.detail)) {
      const first = body.detail.find((entry) => entry?.msg);
      if (first?.msg) return first.msg;
    }
  } catch {
    /* body wasn't JSON — fall through to the generic message */
  }
  return fallback;
}

// --- Marine risk ------------------------------------------------------

export interface MarineRiskResponse {
  latitude: number;
  longitude: number;
  risk_level: 'low' | 'moderate' | 'high' | 'extreme';
  reasons: string[];
  checked: string[];
  could_not_verify: string[];
  note: string;
}

export async function fetchMarineRisk(
  lat: number,
  lon: number,
  signal?: AbortSignal
): Promise<MarineRiskResponse> {
  const u = url('/api/ocean/risk');
  u.searchParams.set('lat', String(lat));
  u.searchParams.set('lon', String(lon));
  const response = await fetch(u, { signal });
  if (!response.ok) {
    throw new Error(await extractErrorMessage(response, `Risk assessment failed (${response.status})`));
  }
  return response.json();
}

// --- Tide-gauge ---------------------------------------------------------

export type TideLevelResponse =
  | { available: false; reason: string; station?: string; distance_km?: number }
  | {
      available: true;
      station: string;
      station_code: string;
      distance_km: number;
      water_level_m: number;
      trend: 'rising' | 'falling' | 'steady' | 'unknown';
      last_reported: string;
      minutes_since_last_reading: number;
      stale: boolean;
      source: string;
      note: string;
    };

export async function fetchTideLevel(
  lat: number,
  lon: number,
  signal?: AbortSignal
): Promise<TideLevelResponse> {
  const u = url('/api/ocean/tide');
  u.searchParams.set('lat', String(lat));
  u.searchParams.set('lon', String(lon));
  const response = await fetch(u, { signal });
  if (!response.ok) {
    throw new Error(await extractErrorMessage(response, `Tide lookup failed (${response.status})`));
  }
  return response.json();
}

// --- ARGO float profile --------------------------------------------------

export interface ArgoLevel {
  pressure_dbar: number;
  depth_m: number;
  temperature_c: number | null;
  salinity_psu: number | null;
}

export type ArgoProfileResponse =
  | { available: false; unavailable_reason: string; radius_km: number; lookback_days: number }
  | {
      available: true;
      radius_km: number;
      lookback_days: number;
      profile: {
        profile_id: string;
        float_id: string;
        latitude: number;
        longitude: number;
        timestamp: string;
        distance_km: number;
        level_count: number;
        levels: ArgoLevel[];
      };
    };

export async function fetchArgoProfile(
  lat: number,
  lon: number,
  signal?: AbortSignal
): Promise<ArgoProfileResponse> {
  const u = url('/api/ocean/argo');
  u.searchParams.set('lat', String(lat));
  u.searchParams.set('lon', String(lon));
  const response = await fetch(u, { signal });
  if (!response.ok) {
    throw new Error(await extractErrorMessage(response, `ARGO lookup failed (${response.status})`));
  }
  return response.json();
}

// --- Literature search -----------------------------------------------

export interface LiteratureResult {
  title: string;
  authors: string[];
  journal: string | null;
  published: string | null;
  doi: string | null;
  url: string | null;
}

export interface LiteratureResponse {
  query: string;
  results: LiteratureResult[];
  result_count: number;
  source: string;
}

export async function fetchLiterature(
  query: string,
  signal?: AbortSignal
): Promise<LiteratureResponse> {
  const u = url('/api/ocean/literature');
  u.searchParams.set('q', query);
  const response = await fetch(u, { signal });
  if (!response.ok) {
    throw new Error(await extractErrorMessage(response, `Literature search failed (${response.status})`));
  }
  return response.json();
}
