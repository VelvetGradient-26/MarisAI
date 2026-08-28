import { useEffect, useRef, useState } from 'react';
import type { MapLayerMouseEvent } from 'maplibre-gl';
import type { MapManager } from '../managers/MapManager';
import { useMapStore } from '../../../store/mapStore';
import { eddiesToGeoJson, fetchEddies } from '../api/eddies';
import type { EddiesResponse, EddyFeatureProperties } from '../api/eddies';

export const EDDIES_LAYER_ID = 'eddies';

/** Cap per viewport. The global field carries ~2,000 detections at once; a
 *  screen full of ocean holds far fewer, and the backend returns the
 *  strongest first, so this only bites when zoomed all the way out. */
const EDDY_LIMIT = 400;

/**
 * Repoll cadence. The detector reads the surface-currents cache, which the
 * server refreshes hourly, so anything faster re-fetches a field that cannot
 * have changed — the opposite trade from the vessel layer, whose positions
 * move every few seconds.
 */
const REFRESH_INTERVAL_MS = 10 * 60 * 1000;

const VIEWPORT_DEBOUNCE_MS = 350;

export interface HoveredEddy {
  properties: EddyFeatureProperties;
  x: number;
  y: number;
}

export interface EddiesState {
  active: boolean;
  hovered: HoveredEddy | null;
  detection: EddiesResponse | null;
  loading: boolean;
  /**
   * Why there is nothing on the map, when there is nothing on the map. A cold
   * currents cache and an ocean with no eddies in view are different answers
   * and the panel must not render them alike.
   */
  unavailableReason: string | null;
}

/**
 * Keeps the eddy layer fed and hoverable.
 *
 * Same one-way flow as `useLiveVessels`: fetch for the current viewport, hand
 * the result to LayerManager, never touch `map.addLayer` here.
 */
export function useEddies(manager: MapManager | null, ready: boolean): EddiesState {
  const active = useMapStore((s) => s.layers.get(EDDIES_LAYER_ID)?.active ?? false);
  const [hovered, setHovered] = useState<HoveredEddy | null>(null);
  const [detection, setDetection] = useState<EddiesResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [unavailableReason, setUnavailableReason] = useState<string | null>(null);

  const inFlight = useRef<AbortController | null>(null);

  useEffect(() => {
    const map = manager?.getMap();
    const layerManager = manager?.getLayerManager();
    if (!ready || !map || !layerManager || !active) {
      setHovered(null);
      setDetection(null);
      setLoading(false);
      setUnavailableReason(null);
      return;
    }

    let disposed = false;
    let debounceTimer: number | undefined;
    let pollTimer: number | undefined;

    const load = async () => {
      inFlight.current?.abort();
      const controller = new AbortController();
      inFlight.current = controller;

      const bounds = map.getBounds();
      setLoading(true);

      try {
        const payload = await fetchEddies(
          {
            south: bounds.getSouth(),
            west: bounds.getWest(),
            north: bounds.getNorth(),
            east: bounds.getEast(),
          },
          EDDY_LIMIT,
          controller.signal
        );
        if (disposed || controller.signal.aborted) return;

        layerManager.setGeoJsonData(EDDIES_LAYER_ID, eddiesToGeoJson(payload.eddies));
        setDetection(payload);
        setUnavailableReason(null);
        setLoading(false);
      } catch (error) {
        if (disposed || controller.signal.aborted) return;
        setLoading(false);
        // Unlike the vessel layer, this says so: an empty eddy layer looks
        // exactly like an ocean with no eddies in it, and the difference is
        // the whole honesty rule this codebase holds.
        setUnavailableReason(
          error instanceof Error ? error.message : 'Eddy detection unavailable'
        );
      }
    };

    const scheduleLoad = () => {
      window.clearTimeout(debounceTimer);
      debounceTimer = window.setTimeout(load, VIEWPORT_DEBOUNCE_MS);
    };

    void load();
    pollTimer = window.setInterval(load, REFRESH_INTERVAL_MS);
    map.on('moveend', scheduleLoad);

    return () => {
      disposed = true;
      inFlight.current?.abort();
      window.clearTimeout(debounceTimer);
      window.clearInterval(pollTimer);
      map.off('moveend', scheduleLoad);
    };
  }, [manager, ready, active]);

  // Hover, in its own effect so a data refresh never detaches the pointer
  // handlers mid-hover.
  useEffect(() => {
    const map = manager?.getMap();
    const layerManager = manager?.getLayerManager();
    if (!ready || !map || !layerManager || !active) return;

    const layerIds = layerManager.getInteractiveLayerIds(EDDIES_LAYER_ID);
    if (layerIds.length === 0) return;

    const onMove = (event: MapLayerMouseEvent) => {
      const feature = event.features?.[0];
      if (!feature) return;
      map.getCanvas().style.cursor = 'pointer';
      setHovered({
        properties: feature.properties as unknown as EddyFeatureProperties,
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
    // The map can move under a stationary cursor, and `mouseleave` only fires
    // on pointer motion — the same trap the vessel tooltip already hit.
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
