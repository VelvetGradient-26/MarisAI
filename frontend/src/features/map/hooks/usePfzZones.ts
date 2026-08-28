import { useEffect, useRef, useState } from 'react';
import type { MapLayerMouseEvent } from 'maplibre-gl';
import type { MapManager } from '../managers/MapManager';
import { useMapStore } from '../../../store/mapStore';
import { useToolsStore } from '../../../store/toolsStore';
import { fetchPfz } from '../api/pfz';
import type { CursorCoordinates } from '../types';
import type { PfzZone } from '../api/pfz';

export const PFZ_LAYER_ID = 'pfz-zones';

/** Matches `FishingZoneArgs.radius_km`'s default in `services/chat/tools.py`. */
export const DEFAULT_PFZ_RADIUS_KM = 100;

export interface HoveredPfzZone {
  properties: PfzZone;
  x: number;
  y: number;
}

function toGeoJson(zones: PfzZone[]): GeoJSON.FeatureCollection {
  return {
    type: 'FeatureCollection',
    features: zones.map((zone) => ({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [zone.longitude, zone.latitude] },
      properties: { ...zone },
    })),
  };
}

/**
 * Feeds the `pfz-zones` marker layer from the clicked point, gated on the
 * layer's own toggle — same "layer active -> fetch at the selected point"
 * shape `SelectedLocationPanel` already uses for SST/wind/currents, so this
 * heuristic scan does not run on every click regardless of whether anyone
 * asked to see it.
 *
 * Called from `Map.tsx` alongside every other data-feed hook (it needs
 * `manager` directly, the way `useEddies` does) rather than from the panel
 * that displays its result — the hover tooltip this hook returns must render
 * at `.map-root`'s level for its pixel coordinates to line up, and `mapStore`
 * would be the wrong place for it to write to (see `useToolsStore`).
 */
export function usePfzZones(
  manager: MapManager | null,
  ready: boolean,
  selectedLocation: CursorCoordinates | null,
  radiusKm: number = DEFAULT_PFZ_RADIUS_KM
): { hovered: HoveredPfzZone | null } {
  const active = useMapStore((s) => s.layers.get(PFZ_LAYER_ID)?.active ?? false);
  const setPfz = useToolsStore((s) => s.setPfz);
  const [hovered, setHovered] = useState<HoveredPfzZone | null>(null);
  const inFlight = useRef<AbortController | null>(null);

  useEffect(() => {
    const layerManager = manager?.getLayerManager();
    if (!ready || !layerManager || !active || !selectedLocation) {
      setPfz({ active, loading: false, unavailableReason: null, response: null });
      layerManager?.setGeoJsonData(PFZ_LAYER_ID, { type: 'FeatureCollection', features: [] });
      return;
    }

    inFlight.current?.abort();
    const controller = new AbortController();
    inFlight.current = controller;
    setPfz({ active, loading: true, unavailableReason: null, response: null });

    fetchPfz(selectedLocation, radiusKm, controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return;
        layerManager.setGeoJsonData(PFZ_LAYER_ID, toGeoJson(result.zones ?? []));
        setPfz({
          active,
          loading: false,
          unavailableReason: result.available ? null : result.reason ?? 'Fishing-zone screening unavailable',
          response: result,
        });
      })
      .catch((error) => {
        if (controller.signal.aborted) return;
        setPfz({
          active,
          loading: false,
          unavailableReason: error instanceof Error ? error.message : 'Fishing-zone screening unavailable',
          response: null,
        });
      });

    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [manager, ready, active, selectedLocation, radiusKm]);

  // Hover, in its own effect for the reason `useEddies` already documents.
  useEffect(() => {
    const map = manager?.getMap();
    const layerManager = manager?.getLayerManager();
    if (!ready || !map || !layerManager || !active) return;

    const layerIds = layerManager.getInteractiveLayerIds(PFZ_LAYER_ID);
    if (layerIds.length === 0) return;

    const onMove = (event: MapLayerMouseEvent) => {
      const feature = event.features?.[0];
      if (!feature) return;
      map.getCanvas().style.cursor = 'pointer';
      setHovered({ properties: feature.properties as unknown as PfzZone, x: event.point.x, y: event.point.y });
    };
    const onLeave = () => {
      map.getCanvas().style.cursor = '';
      setHovered(null);
    };

    for (const layerId of layerIds) {
      map.on('mousemove', layerId, onMove);
      map.on('mouseleave', layerId, onLeave);
    }
    map.on('movestart', onLeave);

    return () => {
      for (const layerId of layerIds) {
        map.off('mousemove', layerId, onMove);
        map.off('mouseleave', layerId, onLeave);
      }
      map.off('movestart', onLeave);
      map.getCanvas().style.cursor = '';
    };
  }, [manager, ready, active]);

  return { hovered };
}
