/** Typed React Query hooks, one per dashboard section.
 *
 * Refresh cadences come from the dashboard spec and are matched to how fast
 * the underlying data can actually change — polling faster than the backend
 * refreshes its cache only burns requests re-reading an identical value:
 *
 *   alerts   30s   cheap, derived from cached grids, and the most urgent
 *   live     60s   NDBC rewrites its feed every ~10 min, buoys report hourly
 *   KPIs      5m   backed by 1-6 hourly model/satellite refreshes
 *   health    5m   status lights, not data
 *   charts   on demand — a range change is a user action, not a tick
 *
 * React Query supplies the abort signal, so a query that re-fires or unmounts
 * cancels the in-flight request rather than racing it.
 */

import { useQuery } from '@tanstack/react-query';
import {
  fetchAlerts,
  fetchDataQuality,
  fetchHealth,
  fetchLive,
  fetchSatellites,
  fetchSourceDetail,
  fetchStationDetail,
  fetchSummary,
  fetchTrend,
  fetchTrendsCatalog,
  fetchTrendsMulti,
} from '../api/dashboard';

const SECOND = 1000;
const MINUTE = 60 * SECOND;

export const REFRESH = {
  alerts: 30 * SECOND,
  live: MINUTE,
  summary: 5 * MINUTE,
  health: 5 * MINUTE,
  satellites: 15 * MINUTE,
  // Derived from files on disk — model artifacts and grid exports — which
  // change only when a training run or a grid build finishes. Polling this at
  // the health cadence would re-read an identical report 12 times an hour.
  dataQuality: 30 * MINUTE,
} as const;

export function useSummary() {
  return useQuery({
    queryKey: ['dashboard', 'summary'],
    queryFn: ({ signal }) => fetchSummary(signal),
    refetchInterval: REFRESH.summary,
    staleTime: REFRESH.summary / 2,
  });
}

export function useAlerts() {
  return useQuery({
    queryKey: ['dashboard', 'alerts'],
    queryFn: ({ signal }) => fetchAlerts(signal),
    refetchInterval: REFRESH.alerts,
    staleTime: REFRESH.alerts / 2,
  });
}

export function useHealth() {
  return useQuery({
    queryKey: ['dashboard', 'health'],
    queryFn: ({ signal }) => fetchHealth(signal),
    refetchInterval: REFRESH.health,
    staleTime: REFRESH.health / 2,
  });
}

export function useSourceDetail(key: string, options: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: ['dashboard', 'source', key],
    queryFn: ({ signal }) => fetchSourceDetail(key, signal),
    enabled: (options.enabled ?? true) && key.length > 0,
    // Same cadence as the list panel — a detail view of a live status is
    // stale exactly as fast as the status itself is.
    refetchInterval: REFRESH.health,
    staleTime: REFRESH.health / 2,
  });
}

export function useStationDetail(stationId: string, options: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: ['dashboard', 'station', stationId],
    queryFn: ({ signal }) => fetchStationDetail(stationId, signal),
    enabled: (options.enabled ?? true) && stationId.length > 0,
    refetchInterval: REFRESH.live,
    staleTime: REFRESH.live / 2,
  });
}

export function useDataQuality() {
  return useQuery({
    queryKey: ['dashboard', 'data-quality'],
    queryFn: ({ signal }) => fetchDataQuality(signal),
    refetchInterval: REFRESH.dataQuality,
    staleTime: REFRESH.dataQuality / 2,
  });
}

export function useSatellites() {
  return useQuery({
    queryKey: ['dashboard', 'satellites'],
    queryFn: ({ signal }) => fetchSatellites(signal),
    refetchInterval: REFRESH.satellites,
    staleTime: REFRESH.satellites / 2,
  });
}

export function useLive(location: { latitude: number; longitude: number } | null, limit = 6) {
  return useQuery({
    // The location is part of the key: moving the point is a different
    // question ("nearest buoys to here"), not a refresh of the old one.
    queryKey: ['dashboard', 'live', location?.latitude ?? null, location?.longitude ?? null, limit],
    queryFn: ({ signal }) =>
      fetchLive(
        {
          limit,
          latitude: location?.latitude,
          longitude: location?.longitude,
        },
        signal
      ),
    refetchInterval: REFRESH.live,
    staleTime: REFRESH.live / 2,
  });
}

export function useTrendsCatalog() {
  return useQuery({
    queryKey: ['dashboard', 'trends', 'catalog'],
    queryFn: ({ signal }) => fetchTrendsCatalog(signal),
    // Coverage windows move once a day at most.
    staleTime: 60 * MINUTE,
  });
}

export function useTrend(params: {
  variable: string;
  latitude: number;
  longitude: number;
  range: string;
  enabled?: boolean;
}) {
  const { variable, latitude, longitude, range, enabled = true } = params;
  return useQuery({
    queryKey: ['dashboard', 'trend', variable, latitude, longitude, range],
    queryFn: ({ signal }) => fetchTrend({ variable, latitude, longitude, range }, signal),
    enabled,
    // Charts are explicitly on-demand: no interval, and a generous stale time
    // so flipping between ranges re-reads the cache instead of the network.
    staleTime: 10 * MINUTE,
    // A 400 here means the range predates the product's coverage, which
    // retrying cannot fix.
    retry: false,
  });
}

export function useTrendsMulti(params: {
  variables: string[];
  latitude: number;
  longitude: number;
  range: string;
  enabled?: boolean;
}) {
  const { variables, latitude, longitude, range, enabled = true } = params;
  return useQuery({
    queryKey: ['dashboard', 'trends', variables.join(','), latitude, longitude, range],
    queryFn: ({ signal }) => fetchTrendsMulti({ variables, latitude, longitude, range }, signal),
    enabled: enabled && variables.length > 0,
    staleTime: 10 * MINUTE,
    retry: false,
  });
}
