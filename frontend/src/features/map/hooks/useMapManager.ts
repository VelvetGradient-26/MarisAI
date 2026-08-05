import { useEffect, useRef, useState } from 'react';
import type { MapMouseEvent } from 'maplibre-gl';
import { MapManager } from '../managers/MapManager';
import { useMapStore } from '../../../store/mapStore';
import { useMapPreferencesStore } from '../../../store/mapPreferencesStore';
import { rafThrottle } from '../../../utils/rafThrottle';
import type { BasemapId } from '../types';

/**
 * The only place a MapManager gets constructed. Mount this once (in
 * Map.tsx) and share the returned `manager` via MapManagerContext — every
 * other map component reads from context/Zustand, it never calls this hook
 * itself, or you'd end up with multiple MapLibre instances.
 */
export function useMapManager(defaultBasemap: BasemapId = 'abyss') {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const managerRef = useRef<MapManager | null>(null);
  const [ready, setReady] = useState(false);

  const setCamera = useMapStore((s) => s.setCamera);
  const setCursor = useMapStore((s) => s.setCursor);
  const setSelectedLocation = useMapStore((s) => s.setSelectedLocation);
  const setBasemap = useMapStore((s) => s.setBasemap);
  const setLayerState = useMapStore((s) => s.setLayerState);

  useEffect(() => {
    if (!containerRef.current) return;

    const manager = new MapManager();
    managerRef.current = manager;

    // Read once, imperatively: this effect deliberately runs a single time
    // per mount, so these are restore-time seeds, not reactive inputs. The
    // camera is whatever the last-destroyed instance was showing (mapStore
    // mirrors every `move`), which is what makes a round-trip to another
    // route return to the same view instead of the world default.
    const { camera } = useMapStore.getState();
    const { projection } = useMapPreferencesStore.getState();

    const map = manager.init({
      container: containerRef.current,
      defaultBasemap,
      center: camera.center,
      zoom: camera.zoom,
      bearing: camera.bearing,
      pitch: camera.pitch,
      projection,
    });

    const syncCamera = rafThrottle(() => {
      const center = map.getCenter();
      setCamera({
        center: [center.lng, center.lat],
        zoom: map.getZoom(),
        bearing: map.getBearing(),
        pitch: map.getPitch(),
      });
    });

    const syncCursor = rafThrottle((e: MapMouseEvent) => {
      setCursor({ lng: e.lngLat.lng, lat: e.lngLat.lat });
    });

    const syncSelectedLocation = (e: MapMouseEvent) => {
      setSelectedLocation({ lng: e.lngLat.lng, lat: e.lngLat.lat });
    };

    map.on('load', () => {
      syncCamera();
      setReady(true);
    });
    map.on('move', syncCamera);
    map.on('mousemove', syncCursor);
    map.on('click', syncSelectedLocation);

    const unsubBasemap = manager.getBasemapManager()!.subscribe(setBasemap);
    const unsubLayers = manager.getLayerManager()!.subscribe(setLayerState);

    return () => {
      map.off('click', syncSelectedLocation);
      unsubBasemap();
      unsubLayers();
      manager.destroy();
      managerRef.current = null;
      setReady(false);
    };
    // Intentionally run once per mount — defaultBasemap is a mount-time
    // initial value, not a reactive prop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { containerRef, manager: managerRef.current, ready };
}
