/** Client for `/api/dashboard/*`.
 *
 * Same shape as the other API clients in this codebase (`features/map/api/*`):
 * a `VITE_API_BASE_URL`-aware `url()` helper, `fetch`, and a thrown `Error`
 * carrying the backend's `detail` on a non-OK response.
 */

import type {
  AlertsResponse,
  DataQualityResponse,
  HealthResponse,
  LiveResponse,
  MultiTrendsResponse,
  SatellitesResponse,
  SourceDetail,
  StationDetailResponse,
  SummaryResponse,
  TrendSeries,
  TrendsCatalogResponse,
} from './types';

import { API_BASE_URL } from '../../../utils/apiBase';

function url(path: string): URL {
  return API_BASE_URL ? new URL(path, API_BASE_URL) : new URL(path, window.location.origin);
}

async function getJson<T>(target: URL, signal?: AbortSignal): Promise<T> {
  const response = await fetch(target, { signal });
  if (!response.ok) {
    // FastAPI puts the service's own message in `detail`; surfacing it is the
    // difference between "Request failed" and "SST only goes back to 2024".
    let detail: string | null = null;
    try {
      const body = (await response.json()) as { detail?: string };
      detail = body?.detail ?? null;
    } catch {
      detail = null;
    }
    throw new Error(detail ?? `Request failed with status ${response.status}`);
  }
  return (await response.json()) as T;
}

export function fetchSummary(signal?: AbortSignal): Promise<SummaryResponse> {
  return getJson<SummaryResponse>(url('/api/dashboard/summary'), signal);
}

export function fetchAlerts(signal?: AbortSignal): Promise<AlertsResponse> {
  return getJson<AlertsResponse>(url('/api/dashboard/alerts'), signal);
}

export function fetchDataQuality(signal?: AbortSignal): Promise<DataQualityResponse> {
  return getJson<DataQualityResponse>(url('/api/dashboard/data-quality'), signal);
}

export function fetchHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return getJson<HealthResponse>(url('/api/dashboard/health'), signal);
}

export function fetchSourceDetail(key: string, signal?: AbortSignal): Promise<SourceDetail> {
  return getJson<SourceDetail>(url(`/api/dashboard/sources/${encodeURIComponent(key)}`), signal);
}

export function fetchStationDetail(
  stationId: string,
  signal?: AbortSignal
): Promise<StationDetailResponse> {
  return getJson<StationDetailResponse>(
    url(`/api/dashboard/stations/${encodeURIComponent(stationId)}`),
    signal
  );
}

export function fetchSatellites(signal?: AbortSignal): Promise<SatellitesResponse> {
  return getJson<SatellitesResponse>(url('/api/dashboard/satellites'), signal);
}

export function fetchLive(
  options: { limit?: number; latitude?: number; longitude?: number } = {},
  signal?: AbortSignal
): Promise<LiveResponse> {
  const target = url('/api/dashboard/live');
  if (options.limit != null) target.searchParams.set('limit', String(options.limit));
  // The backend rejects a half-specified point, so both go or neither does.
  if (options.latitude != null && options.longitude != null) {
    target.searchParams.set('latitude', String(options.latitude));
    target.searchParams.set('longitude', String(options.longitude));
  }
  return getJson<LiveResponse>(target, signal);
}

export function fetchTrendsCatalog(signal?: AbortSignal): Promise<TrendsCatalogResponse> {
  return getJson<TrendsCatalogResponse>(url('/api/dashboard/trends/catalog'), signal);
}

export function fetchTrend(
  params: { variable: string; latitude: number; longitude: number; range: string },
  signal?: AbortSignal
): Promise<TrendSeries> {
  const target = url('/api/dashboard/trends');
  target.searchParams.set('variable', params.variable);
  target.searchParams.set('latitude', String(params.latitude));
  target.searchParams.set('longitude', String(params.longitude));
  target.searchParams.set('range', params.range);
  return getJson<TrendSeries>(target, signal);
}

export function fetchTrendsMulti(
  params: { variables: string[]; latitude: number; longitude: number; range: string },
  signal?: AbortSignal
): Promise<MultiTrendsResponse> {
  const target = url('/api/dashboard/trends/multi');
  target.searchParams.set('variables', params.variables.join(','));
  target.searchParams.set('latitude', String(params.latitude));
  target.searchParams.set('longitude', String(params.longitude));
  target.searchParams.set('range', params.range);
  return getJson<MultiTrendsResponse>(target, signal);
}
