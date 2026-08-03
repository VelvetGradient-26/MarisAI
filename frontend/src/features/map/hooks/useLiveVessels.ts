import { useEffect, useRef, useState } from 'react';
import type { MapLayerMouseEvent } from 'maplibre-gl';
import type { MapManager } from '../managers/MapManager';
import { useMapStore } from '../../../store/mapStore';
import { fetchVessels } from '../api/vessels';
import type { VesselProperties } from '../api/vessels';

export const LIVE_VESSELS_LAYER_ID = 'live-vessels';

/** Matches the backend's own default cap. */
const VESSEL_LIMIT = 1500;

/**
 * How often to re-poll while the viewport sits still. AIS position reports
 * arrive every few seconds per vessel, but the visible change over that
 * span is a few pixels at typical zooms, so polling faster mostly burns
 * requests. Ten seconds keeps motion perceptible without churn.
 */
const REFRESH_INTERVAL_MS = 10_000;

/** Debounce on pan/zoom, so dragging across an ocean fires one request at
 * the end rather than one per animation frame. */
const VIEWPORT_DEBOUNCE_MS = 350;

export interface HoveredVessel {
  properties: VesselProperties;
  /** Screen position of the vessel, for placing the tooltip. */
  x: number;
  y: number;
}

export interface LiveVesselsState {
  /** Whether the vessel layer is switched on. Everything else is only
   * meaningful when this is true. */
  active: boolean;
  hovered: HoveredVessel | null;
  totalInView: number;
  returned: number;
  connected: boolean;
  loading: boolean;
}

/**
 * Keeps the live-vessel layer fed and hoverable.
 *
 * Data flows one way, matching how the rest of the map works: this fetches
 * for the current viewport and hands the result to LayerManager, which owns
 * the MapLibre source. Nothing here touches map.addLayer.
 */
export function useLiveVessels(manager: MapManager | null, ready: boolean): LiveVesselsState {
  const active = useMapStore((s) => s.layers.get(LIVE_VESSELS_LAYER_ID)?.active ?? false);
  const [hovered, setHovered] = useState<HoveredVessel | null>(null);
  const [meta, setMeta] = useState({
    totalInView: 0,
    returned: 0,
    connected: false,
    loading: false,
  });

  // Held in a ref so the polling effect can read the latest without
  // re-subscribing every time a fetch completes.
  const inFlight = useRef<AbortController | null>(null);

  useEffect(() => {
    const map = manager?.getMap();
    const layerManager = manager?.getLayerManager();
    if (!ready || !map || !layerManager || !active) {
      setHovered(null);
      setMeta({ totalInView: 0, returned: 0, connected: false, loading: false });
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
      setMeta((m) => ({ ...m, loading: true }));

      try {
        const collection = await fetchVessels(
          {
            west: bounds.getWest(),
            south: bounds.getSouth(),
            east: bounds.getEast(),
            north: bounds.getNorth(),
          },
          VESSEL_LIMIT,
          controller.signal
        );
        if (disposed || controller.signal.aborted) return;

        layerManager.setGeoJsonData(LIVE_VESSELS_LAYER_ID, collection as GeoJSON.FeatureCollection);
        setMeta({
          totalInView: collection.total_in_view,
          returned: collection.returned,
          connected: collection.connected,
          loading: false,
        });
      } catch {
        if (disposed || controller.signal.aborted) return;
        // A failed poll is not worth an error state: the previous frame of
        // vessels stays on the map and the next tick retries.
        setMeta((m) => ({ ...m, loading: false }));
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

  // Hover hit-testing, kept in its own effect so a data refresh never
  // detaches and reattaches the pointer handlers mid-hover.
  useEffect(() => {
    const map = manager?.getMap();
    const layerManager = manager?.getLayerManager();
    if (!ready || !map || !layerManager || !active) return;

    const layerIds = layerManager.getInteractiveLayerIds(LIVE_VESSELS_LAYER_ID);
    if (layerIds.length === 0) return;

    const onMove = (event: MapLayerMouseEvent) => {
      const feature = event.features?.[0];
      if (!feature) return;
      map.getCanvas().style.cursor = 'pointer';
      setHovered({
        properties: feature.properties as unknown as VesselProperties,
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
    // The map can move under a stationary cursor (zoom buttons, keyboard
    // pan, a programmatic flyTo), and `mouseleave` only fires on pointer
    // motion — without this the tooltip stays pinned to a vessel that is no
    // longer under the pointer, describing whatever is now somewhere else.
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

  return { active, hovered, ...meta };
}
