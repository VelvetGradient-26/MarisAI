import { useEffect, useRef, useState } from 'react';
import type { MapLayerMouseEvent } from 'maplibre-gl';
import type { MapManager } from '../managers/MapManager';
import { useMapStore } from '../../../store/mapStore';

/** One cell's properties on hover, at the cursor position — same shape
 * `useEddies`' `HoveredEddy` returns, generic over the cell's own property
 * type since heatwave and upwelling cells carry different fields. */
export interface HoveredCell<P> {
  properties: P;
  x: number;
  y: number;
}

/**
 * Feeds a cell-based detector layer.
 *
 * Shared by marine heatwaves and coastal upwelling because the two differ only
 * in their endpoint and their colouring — both are global, sparse, refetched on
 * a timer rather than on pan, and both must distinguish "we looked and found
 * none" from "this did not load".
 *
 * No viewport filtering, deliberately, and for the same reason as the eDNA
 * layer: the whole global payload is a few thousand cells, so sending a bbox
 * would make every pan a new request for data that already fits in memory.
 */
export interface DetectorCellsState<T> {
  active: boolean;
  payload: T | null;
  loading: boolean;
  /**
   * Why there is nothing on the map, when there is nothing on the map. A cold
   * detector and an ocean with no heatwave in it are different answers and the
   * panel must not render them alike — the rule `useEddies` already follows.
   */
  unavailableReason: string | null;
}

export function useDetectorCells<T, P = Record<string, unknown>>(
  manager: MapManager | null,
  ready: boolean,
  options: {
    layerId: string;
    fetcher: (signal?: AbortSignal) => Promise<T>;
    toGeoJson: (payload: T) => GeoJSON.FeatureCollection;
    refreshIntervalMs: number;
    fallbackMessage: string;
    /** Opt-in hover, off by default (upwelling has no tooltip; heatwaves
     * does). Mirrors `useEddies`' own mousemove/mouseleave handling against
     * the layer's interactive sub-layers, kept optional here rather than
     * unconditional so a caller that never reads `hovered` pays nothing for
     * it. */
    interactive?: boolean;
  }
): DetectorCellsState<T> & { hovered: HoveredCell<P> | null } {
  const { layerId, fetcher, toGeoJson, refreshIntervalMs, fallbackMessage, interactive } = options;
  const active = useMapStore((s) => s.layers.get(layerId)?.active ?? false);
  const [payload, setPayload] = useState<T | null>(null);
  const [loading, setLoading] = useState(false);
  const [unavailableReason, setUnavailableReason] = useState<string | null>(null);
  const [hovered, setHovered] = useState<HoveredCell<P> | null>(null);

  const inFlight = useRef<AbortController | null>(null);

  useEffect(() => {
    const layerManager = manager?.getLayerManager();
    if (!ready || !layerManager || !active) {
      setPayload(null);
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
        const result = await fetcher(controller.signal);
        if (disposed || controller.signal.aborted) return;
        layerManager.setGeoJsonData(layerId, toGeoJson(result));
        setPayload(result);
        setUnavailableReason(null);
      } catch (error) {
        if (disposed || controller.signal.aborted) return;
        setUnavailableReason(error instanceof Error ? error.message : fallbackMessage);
      } finally {
        if (!disposed && !controller.signal.aborted) setLoading(false);
      }
    };

    void load();
    pollTimer = window.setInterval(load, refreshIntervalMs);

    return () => {
      disposed = true;
      inFlight.current?.abort();
      window.clearInterval(pollTimer);
    };
  }, [manager, ready, active, layerId, fetcher, toGeoJson, refreshIntervalMs, fallbackMessage]);

  // Hover, in its own effect for the same reason useEddies keeps it in one:
  // a data refresh must never detach the pointer handlers mid-hover.
  useEffect(() => {
    const map = manager?.getMap();
    const layerManager = manager?.getLayerManager();
    if (!interactive || !ready || !map || !layerManager || !active) return;

    const layerIds = layerManager.getInteractiveLayerIds(layerId);
    if (layerIds.length === 0) return;

    const onMove = (event: MapLayerMouseEvent) => {
      const feature = event.features?.[0];
      if (!feature) return;
      map.getCanvas().style.cursor = 'pointer';
      setHovered({
        properties: feature.properties as unknown as P,
        x: event.point.x,
        y: event.point.y,
      });
    };

    const onLeave = () => {
      map.getCanvas().style.cursor = '';
      setHovered(null);
    };

    for (const id of layerIds) {
      map.on('mousemove', id, onMove);
      map.on('mouseleave', id, onLeave);
    }
    // The map can move under a stationary cursor, and `mouseleave` only
    // fires on pointer motion — the same trap the vessel/eddy tooltips
    // already hit.
    map.on('movestart', onLeave);

    return () => {
      for (const id of layerIds) {
        map.off('mousemove', id, onMove);
        map.off('mouseleave', id, onLeave);
      }
      map.off('movestart', onLeave);
      map.getCanvas().style.cursor = '';
    };
  }, [manager, ready, active, layerId, interactive]);

  return { active, payload, loading, unavailableReason, hovered };
}
