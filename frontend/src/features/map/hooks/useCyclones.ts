import { useEffect, useRef, useState } from 'react';
import type { MapLayerMouseEvent } from 'maplibre-gl';
import type { MapManager } from '../managers/MapManager';
import { useMapStore } from '../../../store/mapStore';
import { cyclonesToGeoJson, fetchCyclones } from '../api/cyclones';
import type { Cyclone, CyclonesResponse } from '../api/cyclones';

export const CYCLONES_LAYER_ID = 'cyclones';

/**
 * Refetch cadence. `services/cyclones.py` caches GDACS's own list for 15
 * minutes server-side, so polling faster only re-requests a cache that
 * cannot have changed.
 */
const REFRESH_INTERVAL_MS = 15 * 60 * 1000;

export interface HoveredCyclone {
  properties: Cyclone;
  x: number;
  y: number;
}

export interface CyclonesState {
  active: boolean;
  hovered: HoveredCyclone | null;
  detection: CyclonesResponse | null;
  loading: boolean;
  unavailableReason: string | null;
}

/**
 * Feeds the cyclone marker layer and makes it hoverable.
 *
 * Global and polled on a timer rather than viewport-bboxed like `useEddies`:
 * GDACS's whole active-storm list worldwide is a handful of features, so
 * there is nothing a bbox would save here — the same reasoning
 * `useDetectorCells` already documents for the heatwave/upwelling layers.
 * Kept as its own hook rather than reusing `useDetectorCells` because a
 * storm benefits from the same per-feature hover tooltip `useEddies` has,
 * which that generic hook does not provide.
 */
export function useCyclones(manager: MapManager | null, ready: boolean): CyclonesState {
  const active = useMapStore((s) => s.layers.get(CYCLONES_LAYER_ID)?.active ?? false);
  const [hovered, setHovered] = useState<HoveredCyclone | null>(null);
  const [detection, setDetection] = useState<CyclonesResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [unavailableReason, setUnavailableReason] = useState<string | null>(null);

  const inFlight = useRef<AbortController | null>(null);

  useEffect(() => {
    const layerManager = manager?.getLayerManager();
    if (!ready || !layerManager || !active) {
      setHovered(null);
      setDetection(null);
      setLoading(false);
      setUnavailableReason(null);
      return;
    }

    let disposed = false;
    let pollTimer: number | undefined;

    const load = async () => {
      inFlight.current?.abort();
      const controller = new AbortController();
      inFlight.current = controller;
      setLoading(true);

      try {
        const payload = await fetchCyclones(controller.signal);
        if (disposed || controller.signal.aborted) return;
        layerManager.setGeoJsonData(CYCLONES_LAYER_ID, cyclonesToGeoJson(payload.cyclones));
        setDetection(payload);
        setUnavailableReason(null);
      } catch (error) {
        if (disposed || controller.signal.aborted) return;
        setUnavailableReason(error instanceof Error ? error.message : 'Cyclone list unavailable');
      } finally {
        if (!disposed && !controller.signal.aborted) setLoading(false);
      }
    };

    void load();
    pollTimer = window.setInterval(load, REFRESH_INTERVAL_MS);

    return () => {
      disposed = true;
      inFlight.current?.abort();
      window.clearInterval(pollTimer);
    };
  }, [manager, ready, active]);

  // Hover, in its own effect for the same reason `useEddies` splits it out:
  // a data refresh must never detach the pointer handlers mid-hover.
  useEffect(() => {
    const map = manager?.getMap();
    const layerManager = manager?.getLayerManager();
    if (!ready || !map || !layerManager || !active) return;

    const layerIds = layerManager.getInteractiveLayerIds(CYCLONES_LAYER_ID);
    if (layerIds.length === 0) return;

    const onMove = (event: MapLayerMouseEvent) => {
      const feature = event.features?.[0];
      if (!feature) return;
      map.getCanvas().style.cursor = 'pointer';
      setHovered({
        properties: feature.properties as unknown as Cyclone,
        x: event.point.x,
        y: event.point.y,
      });
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

  return { active, hovered, detection, loading, unavailableReason };
}
