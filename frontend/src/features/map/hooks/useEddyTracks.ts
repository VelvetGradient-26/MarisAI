import { useEffect, useRef, useState } from 'react';
import type { MapLayerMouseEvent } from 'maplibre-gl';
import type { MapManager } from '../managers/MapManager';
import { useMapStore } from '../../../store/mapStore';
import { eddyTracksToGeoJson, fetchEddyTracks } from '../api/eddyTracks';
import type { EddyTrack, EddyTracksResponse } from '../api/eddyTracks';

export const EDDY_TRACKS_LAYER_ID = 'eddy-tracks';

/** Cap per viewport, same reasoning as `useEddies`' own `EDDY_LIMIT`: a
 *  screen full of ocean holds far fewer tracks than the global count, and
 *  the backend returns the oldest (most-established) first. Lower than
 *  detections' 400 since each track also carries up to 72 path fixes. */
const TRACK_LIMIT = 150;

/** Tracking state updates on the same hourly detection cadence
 *  `useEddies` polls at — no reason to poll this one faster. */
const REFRESH_INTERVAL_MS = 10 * 60 * 1000;

const VIEWPORT_DEBOUNCE_MS = 350;

export interface HoveredEddyTrack {
  properties: EddyTrack;
  x: number;
  y: number;
}

export interface EddyTracksState {
  active: boolean;
  hovered: HoveredEddyTrack | null;
  tracks: EddyTracksResponse | null;
  loading: boolean;
  unavailableReason: string | null;
}

/**
 * Keeps the eddy-track layer fed and hoverable — a separate hook from
 * `useEddies` deliberately, not a flag on it: this reads a different
 * endpoint (`/eddies/tracks`, not `/eddies`) with a different payload shape
 * (paths, not a bare snapshot), and the two layers stay independently
 * toggleable since detection and tracking answer different questions.
 */
export function useEddyTracks(manager: MapManager | null, ready: boolean): EddyTracksState {
  const active = useMapStore((s) => s.layers.get(EDDY_TRACKS_LAYER_ID)?.active ?? false);
  const [hovered, setHovered] = useState<HoveredEddyTrack | null>(null);
  const [tracks, setTracks] = useState<EddyTracksResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [unavailableReason, setUnavailableReason] = useState<string | null>(null);

  const inFlight = useRef<AbortController | null>(null);

  useEffect(() => {
    const map = manager?.getMap();
    const layerManager = manager?.getLayerManager();
    if (!ready || !map || !layerManager || !active) {
      setHovered(null);
      setTracks(null);
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
        const payload = await fetchEddyTracks(
          {
            south: bounds.getSouth(),
            west: bounds.getWest(),
            north: bounds.getNorth(),
            east: bounds.getEast(),
          },
          TRACK_LIMIT,
          controller.signal
        );
        if (disposed || controller.signal.aborted) return;

        layerManager.setGeoJsonData(EDDY_TRACKS_LAYER_ID, eddyTracksToGeoJson(payload.tracks));
        setTracks(payload);
        setUnavailableReason(null);
        setLoading(false);
      } catch (error) {
        if (disposed || controller.signal.aborted) return;
        setLoading(false);
        setUnavailableReason(
          error instanceof Error ? error.message : 'Eddy track detection unavailable'
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
  // handlers mid-hover — same reason `useEddies` keeps it separate.
  useEffect(() => {
    const map = manager?.getMap();
    const layerManager = manager?.getLayerManager();
    if (!ready || !map || !layerManager || !active) return;

    const layerIds = layerManager.getInteractiveLayerIds(EDDY_TRACKS_LAYER_ID);
    if (layerIds.length === 0) return;

    const onMove = (event: MapLayerMouseEvent) => {
      const feature = event.features?.[0];
      if (!feature) return;
      map.getCanvas().style.cursor = 'pointer';
      setHovered({
        properties: feature.properties as unknown as EddyTrack,
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

  return { active, hovered, tracks, loading, unavailableReason };
}
