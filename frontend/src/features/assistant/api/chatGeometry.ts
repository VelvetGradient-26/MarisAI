/**
 * Turns this turn's `observations` (the raw tool results the backend already
 * sends — see `runtime.ts`'s `TurnProvenance`) into one `FeatureCollection`
 * for `chatGeometryLayer()` (`features/map/layers/layerRegistry.ts`). Mirrors
 * `ForecastChart.tsx`'s own pattern: a runtime type-guard per tool result
 * plus a builder, no backend schema change.
 *
 * Only four tools produce anything drawable — `plan_safe_route`,
 * `plan_drift_trajectory`, `check_geofence`, `find_fishing_zones` — matched
 * against the exact shapes `backend/services/chat/tools.py` returns for
 * each. Every match this turn contributes its features (not just the last),
 * the same way `ForecastCharts` renders one chart per matching observation
 * rather than only the final one.
 */

import type { ChatObservation } from '../../map/api/chat';

type Feature = GeoJSON.Feature;

// --- plan_safe_route --------------------------------------------------

interface RouteWaypoint {
  latitude: number;
  longitude: number;
}

interface RouteResult {
  waypoints: RouteWaypoint[];
  hazard_level: string;
}

function isRouteResult(value: unknown): value is RouteResult {
  if (!value || typeof value !== 'object') return false;
  const candidate = value as Record<string, unknown>;
  return Array.isArray(candidate.waypoints) && typeof candidate.hazard_level === 'string';
}

function routeFeatures(result: RouteResult): Feature[] {
  const coordinates = result.waypoints.map((w) => [w.longitude, w.latitude]);
  if (coordinates.length === 0) return [];

  const features: Feature[] = [
    {
      type: 'Feature',
      geometry: { type: 'LineString', coordinates },
      properties: { tool: 'plan_safe_route', kind: 'route', hazard_level: result.hazard_level },
    },
    {
      type: 'Feature',
      geometry: { type: 'Point', coordinates: coordinates[0] },
      properties: { tool: 'plan_safe_route', kind: 'route_start' },
    },
  ];
  if (coordinates.length > 1) {
    features.push({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: coordinates[coordinates.length - 1] },
      properties: { tool: 'plan_safe_route', kind: 'route_end' },
    });
  }
  return features;
}

// --- plan_drift_trajectory ---------------------------------------------

interface DriftPoint {
  lat: number;
  lon: number;
}

interface DriftTrajectoryResult {
  start: { lat: number; lon: number };
  median_track: DriftPoint[];
}

function isDriftTrajectoryResult(value: unknown): value is DriftTrajectoryResult {
  if (!value || typeof value !== 'object') return false;
  const candidate = value as Record<string, unknown>;
  const start = candidate.start as Record<string, unknown> | undefined;
  return (
    Array.isArray(candidate.median_track) &&
    typeof start?.lat === 'number' &&
    typeof start?.lon === 'number'
  );
}

function driftTrajectoryFeatures(result: DriftTrajectoryResult): Feature[] {
  const features: Feature[] = [
    {
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [result.start.lon, result.start.lat] },
      properties: { tool: 'plan_drift_trajectory', kind: 'drift_start' },
    },
  ];
  if (result.median_track.length > 1) {
    features.push({
      type: 'Feature',
      geometry: {
        type: 'LineString',
        coordinates: result.median_track.map((p) => [p.lon, p.lat]),
      },
      // Only the median of the 100-member ensemble — see
      // `_drift_trajectory`'s own docstring for why the full spread never
      // reaches chat. Never draw this as if it were the one predicted path.
      properties: { tool: 'plan_drift_trajectory', kind: 'drift_median' },
    });
  }
  return features;
}

// --- check_geofence -------------------------------------------------------

interface ProtectedAreaEntry {
  name: string;
  bounds: { south: number; west: number; north: number; east: number };
}

interface GeofenceResult {
  india_sri_lanka_imbl: {
    near: boolean;
    nearest_point: { latitude: number; longitude: number };
  };
  nearby_protected_areas: ProtectedAreaEntry[];
}

function isGeofenceResult(value: unknown): value is GeofenceResult {
  if (!value || typeof value !== 'object') return false;
  const candidate = value as Record<string, unknown>;
  const imbl = candidate.india_sri_lanka_imbl as Record<string, unknown> | undefined;
  return (
    typeof imbl?.near === 'boolean' &&
    typeof (imbl?.nearest_point as Record<string, unknown> | undefined)?.latitude === 'number' &&
    Array.isArray(candidate.nearby_protected_areas)
  );
}

/** Mirrors `useGeofenceStatus.ts`'s own `toGeoJson` exactly (MPA boxes as
 * real polygons, the IMBL distance only drawn when `near`) — the query
 * point isn't in the result itself, only in this call's own `arguments`
 * (every geofence-producing tool takes `PointArgs`). */
function geofenceFeatures(result: GeofenceResult, args: Record<string, unknown>): Feature[] {
  const features: Feature[] = [];

  for (const area of result.nearby_protected_areas) {
    const { south, west, north, east } = area.bounds;
    features.push({
      type: 'Feature',
      geometry: {
        type: 'Polygon',
        coordinates: [
          [
            [west, south],
            [east, south],
            [east, north],
            [west, north],
            [west, south],
          ],
        ],
      },
      properties: { tool: 'check_geofence', kind: 'protected_area', name: area.name },
    });
  }

  const queryLat = args.latitude;
  const queryLon = args.longitude;
  if (result.india_sri_lanka_imbl.near && typeof queryLat === 'number' && typeof queryLon === 'number') {
    const nearest = result.india_sri_lanka_imbl.nearest_point;
    features.push({
      type: 'Feature',
      geometry: {
        type: 'LineString',
        coordinates: [
          [queryLon, queryLat],
          [nearest.longitude, nearest.latitude],
        ],
      },
      properties: { tool: 'check_geofence', kind: 'imbl_distance' },
    });
  }

  return features;
}

// --- find_fishing_zones -----------------------------------------------

interface FishingZoneEntry {
  latitude: number;
  longitude: number;
  score?: number;
}

interface FishingZonesResult {
  zones: FishingZoneEntry[];
}

function isFishingZonesResult(value: unknown): value is FishingZonesResult {
  if (!value || typeof value !== 'object') return false;
  return Array.isArray((value as Record<string, unknown>).zones);
}

function fishingZonesFeatures(result: FishingZonesResult): Feature[] {
  return result.zones.map((zone) => ({
    type: 'Feature',
    geometry: { type: 'Point', coordinates: [zone.longitude, zone.latitude] },
    properties: { tool: 'find_fishing_zones', kind: 'fishing_zone', score: zone.score ?? null },
  }));
}

// --- Combined ---------------------------------------------------------

/**
 * Every drawable feature across this turn's geometry-producing tool calls,
 * or `null` when none of the four target tools were called (or none parsed
 * — a schema change on the backend degrades to "no map" rather than a
 * runtime error, the same contract `isForecastTrendResult` already keeps).
 */
export function buildChatGeometry(observations: ChatObservation[]): GeoJSON.FeatureCollection | null {
  const features: Feature[] = [];

  for (const observation of observations) {
    if (observation.tool === 'plan_safe_route' && isRouteResult(observation.result)) {
      features.push(...routeFeatures(observation.result));
    } else if (
      observation.tool === 'plan_drift_trajectory' &&
      isDriftTrajectoryResult(observation.result)
    ) {
      features.push(...driftTrajectoryFeatures(observation.result));
    } else if (observation.tool === 'check_geofence' && isGeofenceResult(observation.result)) {
      features.push(...geofenceFeatures(observation.result, observation.arguments ?? {}));
    } else if (
      observation.tool === 'find_fishing_zones' &&
      isFishingZonesResult(observation.result)
    ) {
      features.push(...fishingZonesFeatures(observation.result));
    }
  }

  return features.length > 0 ? { type: 'FeatureCollection', features } : null;
}
