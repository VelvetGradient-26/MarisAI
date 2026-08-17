import { useEffect, useRef, useState } from 'react';
import type { MapManager } from '../managers/MapManager';
import { useMapStore } from '../../../store/mapStore';

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

export function useDetectorCells<T>(
  manager: MapManager | null,
  ready: boolean,
  options: {
    layerId: string;
    fetcher: (signal?: AbortSignal) => Promise<T>;
    toGeoJson: (payload: T) => GeoJSON.FeatureCollection;
    refreshIntervalMs: number;
    fallbackMessage: string;
  }
): DetectorCellsState<T> {
  const { layerId, fetcher, toGeoJson, refreshIntervalMs, fallbackMessage } = options;
  const active = useMapStore((s) => s.layers.get(layerId)?.active ?? false);
  const [payload, setPayload] = useState<T | null>(null);
  const [loading, setLoading] = useState(false);
  const [unavailableReason, setUnavailableReason] = useState<string | null>(null);

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

  return { active, payload, loading, unavailableReason };
}
