import { useEffect, useRef, useState } from 'react';
import type { MapManager } from '../managers/MapManager';
import { useMapStore } from '../../../store/mapStore';
import { useToolsStore } from '../../../store/toolsStore';
import { useToastStore } from '../../../store/toastStore';
import { fetchGeofence, fetchGeofenceBoundaries } from '../api/geofence';
import type { GeofenceResponse } from '../api/geofence';
import type { CursorCoordinates } from '../types';

export const GEOFENCE_LAYER_ID = 'geofence-status';

/**
 * Draws India's maritime boundaries whenever the layer is on — treaty and
 * median lines with each neighbour, the 200 NM outer limits and every
 * registered Marine Protected Area outline, styled like the basemap's country
 * borders — and, on top, what `check_geofence` found near the clicked point: each nearby
 * Marine Protected Area as its own real box (see the backend's `bounds`
 * field), plus a line to the nearest India-Sri Lanka IMBL point when the
 * query point is near it. The boundary lines come from their own static
 * endpoint, fetched once, rather than riding in every point-check response.
 *
 * Called from `Map.tsx` like every other data-feed hook; `SelectedLocationPanel`
 * reads the result from `useToolsStore` rather than calling this itself — see
 * `usePfzZones`'s docstring for why that split exists.
 */
export function useGeofenceStatus(
  manager: MapManager | null,
  ready: boolean,
  selectedLocation: CursorCoordinates | null
): void {
  const active = useMapStore((s) => s.layers.get(GEOFENCE_LAYER_ID)?.active ?? false);
  const setGeofence = useToolsStore((s) => s.setGeofence);
  const pushToast = useToastStore((s) => s.push);
  const inFlight = useRef<AbortController | null>(null);
  const [boundaries, setBoundaries] = useState<GeoJSON.Feature[]>([]);

  // The boundary lines are independent of any click: they draw as soon as the
  // layer is switched on, like a reference layer.
  useEffect(() => {
    if (!active || boundaries.length > 0) return;
    let cancelled = false;
    fetchGeofenceBoundaries()
      .then((collection) => {
        if (!cancelled) setBoundaries(collection.features);
      })
      .catch((error) => {
        if (cancelled) return;
        pushToast({
          tone: 'error',
          title: 'Maritime boundaries unavailable',
          detail: error instanceof Error ? error.message : 'Could not load boundary lines',
        });
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, boundaries.length]);

  // The click's own features, kept so the boundaries arriving (or the click
  // result arriving) can redraw both without re-running the point check —
  // re-running it would fire its toast a second time.
  const pointFeatures = useRef<GeoJSON.Feature[]>([]);
  const boundariesRef = useRef(boundaries);
  boundariesRef.current = boundaries;

  useEffect(() => {
    const layerManager = manager?.getLayerManager();
    if (!ready || !layerManager || !active) return;
    layerManager.setGeoJsonData(GEOFENCE_LAYER_ID, {
      type: 'FeatureCollection',
      features: [...boundaries, ...pointFeatures.current],
    });
  }, [manager, ready, active, boundaries]);

  useEffect(() => {
    const layerManager = manager?.getLayerManager();
    const draw = (features: GeoJSON.Feature[]) => {
      pointFeatures.current = features;
      layerManager?.setGeoJsonData(GEOFENCE_LAYER_ID, {
        type: 'FeatureCollection',
        features: [...boundariesRef.current, ...features],
      });
    };
    if (!ready || !layerManager || !active || !selectedLocation) {
      setGeofence({ active, loading: false, unavailableReason: null, response: null });
      draw([]);
      return;
    }
    // Boundaries stay on screen while the point check is in flight.
    draw([]);

    inFlight.current?.abort();
    const controller = new AbortController();
    inFlight.current = controller;
    setGeofence({ active, loading: true, unavailableReason: null, response: null });

    fetchGeofence(selectedLocation, controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return;
        draw(toGeoJson(result, selectedLocation).features);
        setGeofence({ active, loading: false, unavailableReason: null, response: result });
        const { title, detail } = summariseGeofence(result);
        pushToast({ tone: 'success', title, detail });
      })
      .catch((error) => {
        if (controller.signal.aborted) return;
        const reason = error instanceof Error ? error.message : 'Geofence check unavailable';
        setGeofence({ active, loading: false, unavailableReason: reason, response: null });
        pushToast({ tone: 'error', title: 'Geofence check failed', detail: reason });
      });

    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [manager, ready, active, selectedLocation]);
}

/**
 * The panel used to lay this out as a small table; the check is now reported
 * as a single toast instead (see this hook's fetch handler), so this collapses
 * the same fields into one title + a detail line rather than a table row per
 * field. Named things (a boundary crossing, a nearby MPA) lead; "nothing
 * nearby" is still reported, not silently skipped, since a snackbar that only
 * ever fires on bad news trains people to read silence as "checked and fine"
 * when it might just not have run yet.
 */
function summariseGeofence(result: GeofenceResponse): { title: string; detail: string } {
  const flags: string[] = [];

  if (result.india_eez.inside) {
    flags.push(
      result.india_eez.zone === 'andaman_and_nicobar'
        ? 'Inside India EEZ (Andaman & Nicobar)'
        : 'Inside India EEZ (mainland)'
    );
  }
  if (result.india_sri_lanka_imbl.near) {
    flags.push(`${result.india_sri_lanka_imbl.distance_km.toFixed(1)} km from the India-Sri Lanka IMBL`);
  }
  for (const area of result.nearby_protected_areas) {
    flags.push(area.inside ? `Inside ${area.name}` : `${area.distance_km.toFixed(1)} km from ${area.name}`);
  }

  if (flags.length === 0) {
    return {
      title: 'Geofence check: no boundary nearby',
      detail: 'Outside the India EEZ, clear of the IMBL and known Marine Protected Areas.',
    };
  }

  return { title: 'Geofence check', detail: flags.join(' · ') };
}

function toGeoJson(
  result: GeofenceResponse,
  point: CursorCoordinates
): GeoJSON.FeatureCollection {
  const features: GeoJSON.Feature[] = [];

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
      properties: { kind: 'protected_area', ...area },
    });
  }

  if (result.india_sri_lanka_imbl.near) {
    const nearest = result.india_sri_lanka_imbl.nearest_point;
    features.push({
      type: 'Feature',
      geometry: {
        type: 'LineString',
        coordinates: [
          [point.lng, point.lat],
          [nearest.longitude, nearest.latitude],
        ],
      },
      properties: { kind: 'imbl_distance', distance_km: result.india_sri_lanka_imbl.distance_km },
    });
  }

  return { type: 'FeatureCollection', features };
}
