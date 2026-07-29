import { useEffect } from 'react';
import type { MapManager } from '../managers/MapManager';
import { useMapStore } from '../../../store/mapStore';

/** Zoom to move in to when the incoming coordinate is further out than this.
 * Close enough to read a single point's conditions, far enough to keep the
 * surrounding coastline/ocean context that makes the pin interpretable. */
const FOCUS_ZOOM = 5;

/**
 * Moves the camera onto a location chosen off-map (the dashboard's
 * coordinate form), then clears the request so it fires exactly once. The
 * map route is lazy, so the usual case is that this runs on mount: the
 * request was queued while no MapLibre instance existed. An already-mounted
 * map handles it live via the same effect.
 *
 * Only `pendingFocus` moves the camera — a plain `setSelectedLocation` (a
 * map click) never does, since the user is already looking at that point and
 * yanking the camera onto it would fight them.
 */
export function useSelectedLocationFocus(manager: MapManager | null, ready: boolean) {
  const pendingFocus = useMapStore((s) => s.pendingFocus);
  const consumePendingFocus = useMapStore((s) => s.consumePendingFocus);

  useEffect(() => {
    const map = manager?.getMap();
    if (!ready || !map || !pendingFocus) return;

    map.easeTo({
      center: [pendingFocus.lng, pendingFocus.lat],
      zoom: Math.max(map.getZoom(), FOCUS_ZOOM),
      duration: 900,
    });

    consumePendingFocus();
  }, [manager, ready, pendingFocus, consumePendingFocus]);
}
