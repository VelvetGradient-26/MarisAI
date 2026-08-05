/** React Query hooks for the metric intelligence page.
 *
 * Cadences follow the rule `useDashboardData.ts` sets out: match them to how
 * fast the *backend cache* refreshes, not to how live a panel should feel.
 * Nothing here polls. Every one of these is either a user action (changing a
 * range) or a page load, and the underlying products update hourly at best —
 * a refetch interval would spend upstream quota re-reading identical numbers.
 *
 * The story is the exception worth noting: it costs a language-model call, and
 * the backend caches it for 15 minutes, so the client mirrors that rather than
 * re-requesting on every remount.
 */

import { useQuery } from '@tanstack/react-query';
import {
  fetchBatchForecast,
  fetchCatalog,
  fetchModelDetail,
  fetchSeries,
  fetchStatistics,
  fetchStory,
} from '../api/metrics';

const MINUTE = 60 * 1000;

interface Point {
  latitude: number;
  longitude: number;
}

/**
 * The catalog drives which sections a variable gets, so it is fetched once and
 * held. It only changes when a model is trained, which is an offline act.
 */
export function useForecastCatalog() {
  return useQuery({
    queryKey: ['forecast', 'catalog'],
    queryFn: ({ signal }) => fetchCatalog(signal),
    staleTime: 30 * MINUTE,
    gcTime: 60 * MINUTE,
  });
}

export function useMetricSeries(
  params: Point & { variable: string; range: string; maxPoints?: number; enabled?: boolean }
) {
  return useQuery({
    queryKey: [
      'metric',
      'series',
      params.variable,
      params.latitude,
      params.longitude,
      params.range,
      params.maxPoints ?? 4000,
    ],
    queryFn: ({ signal }) =>
      fetchSeries(
        {
          variable: params.variable,
          latitude: params.latitude,
          longitude: params.longitude,
          range: params.range,
          maxPoints: params.maxPoints,
        },
        signal
      ),
    enabled: params.enabled ?? true,
    staleTime: 10 * MINUTE,
  });
}

export function useMetricStatistics(
  params: Point & { variable: string; range: string; enabled?: boolean }
) {
  return useQuery({
    queryKey: [
      'metric',
      'statistics',
      params.variable,
      params.latitude,
      params.longitude,
      params.range,
    ],
    queryFn: ({ signal }) =>
      fetchStatistics(
        {
          variable: params.variable,
          latitude: params.latitude,
          longitude: params.longitude,
          range: params.range,
        },
        signal
      ),
    enabled: params.enabled ?? true,
    staleTime: 10 * MINUTE,
  });
}

export function useOceanStory(
  params: Point & { variable: string; range?: string; horizon?: number; enabled?: boolean }
) {
  return useQuery({
    queryKey: [
      'metric',
      'story',
      params.variable,
      params.latitude,
      params.longitude,
      params.range ?? '1y',
      params.horizon ?? 7,
    ],
    queryFn: ({ signal }) =>
      fetchStory(
        {
          variable: params.variable,
          latitude: params.latitude,
          longitude: params.longitude,
          range: params.range,
          horizon: params.horizon,
        },
        signal
      ),
    enabled: params.enabled ?? true,
    // Mirrors the backend's own 15-minute story cache.
    staleTime: 15 * MINUTE,
    // One failed language-model call should not become three.
    retry: false,
  });
}

export function useBatchForecast(
  params: Point & { variable: string; horizons: number[]; enabled?: boolean }
) {
  return useQuery({
    queryKey: [
      'forecast',
      'batch',
      params.variable,
      params.latitude,
      params.longitude,
      params.horizons.join(','),
    ],
    queryFn: ({ signal }) =>
      fetchBatchForecast(
        {
          variable: params.variable,
          latitude: params.latitude,
          longitude: params.longitude,
          horizons: params.horizons,
        },
        signal
      ),
    enabled: (params.enabled ?? true) && params.horizons.length > 0,
    staleTime: 10 * MINUTE,
  });
}

export function useModelDetail(params: {
  variable: string;
  horizon: number;
  enabled?: boolean;
}) {
  return useQuery({
    queryKey: ['forecast', 'model', params.variable, params.horizon],
    queryFn: ({ signal }) =>
      fetchModelDetail({ variable: params.variable, horizon: params.horizon }, signal),
    enabled: params.enabled ?? true,
    // A trained artifact only changes when someone retrains it offline.
    staleTime: 30 * MINUTE,
  });
}
