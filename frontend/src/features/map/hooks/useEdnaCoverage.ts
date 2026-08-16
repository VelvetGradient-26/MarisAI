import { useEffect, useRef, useState } from 'react';
import type { MapLayerMouseEvent } from 'maplibre-gl';
import type { MapManager } from '../managers/MapManager';
import { useMapStore } from '../../../store/mapStore';
import {
  ednaCoverageToGeoJson,
  fetchEdnaCoverage,
  precisionForZoom,
} from '../api/edna';
import type { EdnaCell, EdnaCoverageResponse } from '../api/edna';

export const EDNA_LAYER_ID = 'edna-coverage';

/**
 * There is no poll timer here, unlike the eddy and vessel layers.
 *
 * Those read fields that move — an hourly current refresh, AIS positions every
 * few seconds. This reads OBIS's published holdings, which change on a release
 * cadence of weeks, and the backend caches each precision for 24 hours anyway.
 * A repoll would re-render a payload that cannot have changed.
 */
const ZOOM_DEBOUNCE_MS = 300;

export interface HoveredEdnaCell {
  properties: EdnaCell;
  x: number;
  y: number;
}

export interface EdnaCoverageState {
  active: boolean;
  hovered: HoveredEdnaCell | null;
  coverage: EdnaCoverageResponse | null;
  loading: boolean;
  /**
   * Why there is nothing on the map. This layer needs it more than any other:
   * an empty eDNA layer is the *correct* rendering of almost the whole ocean,
   * so "we could not reach OBIS" and "nobody has sequenced this water" must
   * never look alike.
   */
  unavailableReason: string | null;
}

/**
 * Keeps the eDNA coverage layer fed and hoverable.
 *
 * Refetches on zoom rather than on pan, because the grid is fetched globally
 * and only its precision depends on the camera — see `precisionForZoom`.
 */
export function useEdnaCoverage(
  manager: MapManager | null,
  ready: boolean
): EdnaCoverageState {
  const active = useMapStore((s) => s.layers.get(EDNA_LAYER_ID)?.active ?? false);
  const [hovered, setHovered] = useState<HoveredEdnaCell | null>(null);
  const [coverage, setCoverage] = useState<EdnaCoverageResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [unavailableReason, setUnavailableReason] = useState<string | null>(null);

  const inFlight = useRef<AbortController | null>(null);
  const loadedPrecision = useRef<number | null>(null);

  useEffect(() => {
    const map = manager?.getMap();
    const layerManager = manager?.getLayerManager();
    if (!ready || !map || !layerManager || !active) {
      setHovered(null);
      setCoverage(null);
      setLoading(false);
      setUnavailableReason(null);
      loadedPrecision.current = null;
      return;
    }

    let disposed = false;
    let debounceTimer: number | undefined;

    const load = async () => {
      const precision = precisionForZoom(map.getZoom());
      if (precision === loadedPrecision.current) return;

      inFlight.current?.abort();
      const controller = new AbortController();
      inFlight.current = controller;
      setLoading(true);

      try {
        const payload = await fetchEdnaCoverage(precision, controller.signal);
        if (disposed || controller.signal.aborted) return;

        layerManager.setGeoJsonData(EDNA_LAYER_ID, ednaCoverageToGeoJson(payload.cells));
        // Only after a successful swap: a failed refetch must not make the
        // hook believe the finer grid is on screen.
        loadedPrecision.current = precision;
        setCoverage(payload);
        setUnavailableReason(null);
        setLoading(false);
      } catch (error) {
        if (disposed || controller.signal.aborted) return;
        setLoading(false);
        setUnavailableReason(
          error instanceof Error ? error.message : 'eDNA coverage unavailable'
        );
      }
    };

    const scheduleLoad = () => {
      window.clearTimeout(debounceTimer);
      debounceTimer = window.setTimeout(load, ZOOM_DEBOUNCE_MS);
    };

    void load();
    map.on('zoomend', scheduleLoad);

    return () => {
      disposed = true;
      inFlight.current?.abort();
      window.clearTimeout(debounceTimer);
      map.off('zoomend', scheduleLoad);
    };
  }, [manager, ready, active]);

  // Hover, in its own effect so a precision change never detaches the pointer
  // handlers mid-hover — the same split `useEddies` makes.
  useEffect(() => {
    const map = manager?.getMap();
    const layerManager = manager?.getLayerManager();
    if (!ready || !map || !layerManager || !active) return;

    const layerIds = layerManager.getInteractiveLayerIds(EDNA_LAYER_ID);
    if (layerIds.length === 0) return;

    const onMove = (event: MapLayerMouseEvent) => {
      const feature = event.features?.[0];
      if (!feature) return;
      map.getCanvas().style.cursor = 'pointer';
      setHovered({
        properties: feature.properties as unknown as EdnaCell,
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
    // The map can move under a stationary cursor and `mouseleave` only fires on
    // pointer motion — the trap the vessel and eddy tooltips both hit.
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

  return { active, hovered, coverage, loading, unavailableReason };
}
