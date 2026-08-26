import { useCallback } from 'react';
import { useMapManagerContext } from './MapManagerContext';
import { useRouteStore } from '../../../store/routeStore';
import { fetchRoute } from '../api/routing';
import type { RouteResponse } from '../api/routing';

export const PLANNED_ROUTE_LAYER_ID = 'planned-route';

function toGeoJson(route: RouteResponse): GeoJSON.FeatureCollection {
  const coordinates = route.waypoints.map((w) => [w.longitude, w.latitude]);
  const features: GeoJSON.Feature[] = [
    {
      type: 'Feature',
      geometry: { type: 'LineString', coordinates },
      properties: { hazard_level: route.hazard_level },
    },
  ];
  if (coordinates.length > 0) {
    features.push({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: coordinates[0] },
      properties: { role: 'start' },
    });
    features.push({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: coordinates[coordinates.length - 1] },
      properties: { role: 'end' },
    });
  }
  return { type: 'FeatureCollection', features };
}

/**
 * Runs the A* route search between the two points `routeStore` holds and
 * draws the result as the `planned-route` line layer.
 *
 * The layer starts `defaultVisible: false` like every other overlay, so a
 * successful plan explicitly turns it on (`layerManager.add`) rather than
 * relying on the user having switched it on themselves beforehand — the
 * point of clicking "Plan route" is to see the result immediately.
 */
export function useRoutePlanner() {
  const manager = useMapManagerContext();
  const start = useRouteStore((s) => s.start);
  const end = useRouteStore((s) => s.end);
  const status = useRouteStore((s) => s.status);
  const result = useRouteStore((s) => s.result);
  const error = useRouteStore((s) => s.error);
  const setStart = useRouteStore((s) => s.setStart);
  const setEnd = useRouteStore((s) => s.setEnd);
  const setLoading = useRouteStore((s) => s.setLoading);
  const setSuccess = useRouteStore((s) => s.setSuccess);
  const setError = useRouteStore((s) => s.setError);
  const clearStore = useRouteStore((s) => s.clear);

  const planRoute = useCallback(async () => {
    if (!start || !end) return;
    setLoading();
    try {
      const route = await fetchRoute(start, end);
      const layerManager = manager?.getLayerManager();
      layerManager?.add(PLANNED_ROUTE_LAYER_ID);
      layerManager?.setGeoJsonData(PLANNED_ROUTE_LAYER_ID, toGeoJson(route));
      setSuccess(route);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Route planning failed');
    }
  }, [manager, start, end, setLoading, setSuccess, setError]);

  const clear = useCallback(() => {
    manager?.getLayerManager()?.setGeoJsonData(PLANNED_ROUTE_LAYER_ID, {
      type: 'FeatureCollection',
      features: [],
    });
    clearStore();
  }, [manager, clearStore]);

  return { start, end, status, result, error, setStart, setEnd, planRoute, clear };
}
