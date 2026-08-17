/** Client for `/api/v1/metrics/*` and `/api/v1/forecast/*`.
 *
 * Same shape as every other API client in this codebase (see
 * `features/dashboard/api/dashboard.ts` and `features/map/api/*`): a
 * `VITE_API_BASE_URL`-aware `url()` helper, `fetch`, and a thrown `Error`
 * carrying the backend's `detail`.
 *
 * Surfacing `detail` matters more here than usual. The backend answers an
 * untrained variable with "no trained model for 'chlorophyll_a' at horizon 7.
 * Train it with: ..." — replacing that with "Request failed" would throw away
 * the only actionable part.
 */

import type {
  BatchForecast,
  Forecast,
  ForecastCatalog,
  MetricSeries,
  MetricStatistics,
  ModelDetail,
  OceanStory,
} from './types';

import { API_BASE_URL } from '../../../../utils/apiBase';

function url(path: string): URL {
  return API_BASE_URL ? new URL(path, API_BASE_URL) : new URL(path, window.location.origin);
}

async function request<T>(target: URL, init?: RequestInit): Promise<T> {
  const response = await fetch(target, init);
  if (!response.ok) {
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

function point(target: URL, latitude: number, longitude: number): URL {
  target.searchParams.set('latitude', String(latitude));
  target.searchParams.set('longitude', String(longitude));
  return target;
}

// --- Metrics ---------------------------------------------------------------

export function fetchSeries(
  params: {
    variable: string;
    latitude: number;
    longitude: number;
    range?: string;
    maxPoints?: number;
  },
  signal?: AbortSignal
): Promise<MetricSeries> {
  const target = point(
    url(`/api/v1/metrics/${encodeURIComponent(params.variable)}/series`),
    params.latitude,
    params.longitude
  );
  if (params.range) target.searchParams.set('range', params.range);
  if (params.maxPoints) target.searchParams.set('max_points', String(params.maxPoints));
  return request<MetricSeries>(target, { signal });
}

export function fetchStatistics(
  params: { variable: string; latitude: number; longitude: number; range?: string },
  signal?: AbortSignal
): Promise<MetricStatistics> {
  const target = point(
    url(`/api/v1/metrics/${encodeURIComponent(params.variable)}/statistics`),
    params.latitude,
    params.longitude
  );
  if (params.range) target.searchParams.set('range', params.range);
  return request<MetricStatistics>(target, { signal });
}

export function fetchStory(
  params: {
    variable: string;
    latitude: number;
    longitude: number;
    range?: string;
    horizon?: number;
  },
  signal?: AbortSignal
): Promise<OceanStory> {
  const target = point(
    url(`/api/v1/metrics/${encodeURIComponent(params.variable)}/story`),
    params.latitude,
    params.longitude
  );
  if (params.range) target.searchParams.set('range', params.range);
  if (params.horizon) target.searchParams.set('horizon', String(params.horizon));
  return request<OceanStory>(target, { signal });
}

// --- Forecasting -----------------------------------------------------------

export function fetchCatalog(signal?: AbortSignal): Promise<ForecastCatalog> {
  return request<ForecastCatalog>(url('/api/v1/forecast/catalog'), { signal });
}

export function fetchForecast(
  params: {
    variable: string;
    latitude: number;
    longitude: number;
    horizon: number;
    historyWindow?: number;
  },
  signal?: AbortSignal
): Promise<Forecast> {
  return request<Forecast>(url('/api/v1/forecast'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    signal,
    body: JSON.stringify({
      variable: params.variable,
      latitude: params.latitude,
      longitude: params.longitude,
      forecast_horizon: params.horizon,
      history_window: params.historyWindow ?? 90,
    }),
  });
}

export function fetchBatchForecast(
  params: {
    variable: string;
    latitude: number;
    longitude: number;
    horizons: number[];
    historyWindow?: number;
  },
  signal?: AbortSignal
): Promise<BatchForecast> {
  return request<BatchForecast>(url('/api/v1/forecast/batch'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    signal,
    body: JSON.stringify({
      variable: params.variable,
      latitude: params.latitude,
      longitude: params.longitude,
      horizons: params.horizons,
      history_window: params.historyWindow ?? 90,
    }),
  });
}

export function fetchModelDetail(
  params: { variable: string; horizon: number },
  signal?: AbortSignal
): Promise<ModelDetail> {
  return request<ModelDetail>(
    url(`/api/v1/forecast/models/${encodeURIComponent(params.variable)}/${params.horizon}`),
    { signal }
  );
}
