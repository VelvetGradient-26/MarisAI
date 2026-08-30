import { useEffect, useRef } from 'react';
import { fetchGeofence } from '../api/geofence';
import type { GeofenceResponse } from '../api/geofence';
import {
  useBoundaryWatchStore,
  type BoundaryEvent,
  type BoundaryEventType,
} from '../../../store/boundaryWatchStore';

// A boat's proximity to a boundary doesn't meaningfully change faster than
// this, and it keeps the approach/crossing trend comparison meaningful
// rather than noisy tick-to-tick GPS jitter.
const THROTTLE_MS = 15_000;

const WATCH_OPTIONS: PositionOptions = {
  enableHighAccuracy: true,
  maximumAge: 10_000,
  timeout: 20_000,
};

function zoneLabel(zone: GeofenceResponse['india_eez']['zone']): string {
  if (zone === 'andaman_and_nicobar') return "India's EEZ (Andaman & Nicobar)";
  return "India's mainland EEZ";
}

/**
 * Pure detection of what changed between two consecutive geofence checks.
 * Kept standalone (no store/hook access) so the logic itself stays legible
 * on its own — this repo has no frontend test runner yet to exercise it
 * automatically (see the plan this shipped from), but a pure function is
 * still the right shape for whenever one exists.
 *
 * Edge-triggered, not level-triggered: "near" conditions fire once on the
 * false->true transition (via `wasNearImbl`/`nearMpaNames`, threaded through
 * rather than recomputed here) so lingering near a boundary does not spam an
 * event every 15s — only becoming near, or actually crossing, does.
 */
export function evaluateBoundaryEvents(
  previous: GeofenceResponse | null,
  current: GeofenceResponse,
  position: { latitude: number; longitude: number },
  wasNearImbl: boolean,
  nearMpaNames: Set<string>
): { events: BoundaryEvent[]; wasNearImbl: boolean; nearMpaNames: Set<string> } {
  const events: BoundaryEvent[] = [];
  const at = new Date().toISOString();

  const makeEvent = (type: BoundaryEventType, message: string): BoundaryEvent => ({
    id: `${type}-${at}-${Math.random().toString(36).slice(2, 8)}`,
    type,
    message,
    at,
    latitude: position.latitude,
    longitude: position.longitude,
  });

  if (previous !== null && previous.india_eez.inside !== current.india_eez.inside) {
    events.push(
      current.india_eez.inside
        ? makeEvent('eez_crossing', `Entered ${zoneLabel(current.india_eez.zone)}.`)
        : makeEvent(
            'eez_crossing',
            `Left ${zoneLabel(previous.india_eez.zone)} — now outside India's EEZ.`
          )
    );
  }

  const nowNearImbl = current.india_sri_lanka_imbl.near;
  if (nowNearImbl && !wasNearImbl) {
    events.push(
      makeEvent(
        'imbl_approach',
        `Approaching the India-Sri Lanka maritime boundary — ${current.india_sri_lanka_imbl.distance_km.toFixed(1)} km away.`
      )
    );
  }

  const nowNearMpaNames = new Set(
    current.nearby_protected_areas.map((area) => area.name)
  );
  for (const area of current.nearby_protected_areas) {
    if (!nearMpaNames.has(area.name)) {
      events.push(
        makeEvent(
          'mpa_approach',
          area.inside
            ? `Inside ${area.name}.`
            : `Approaching ${area.name} — ${area.distance_km.toFixed(1)} km away.`
        )
      );
    }
  }

  return { events, wasNearImbl: nowNearImbl, nearMpaNames: nowNearMpaNames };
}

/**
 * Tracks the device's own live position (`navigator.geolocation.
 * watchPosition`) and warns when it approaches or crosses a maritime
 * boundary/MPA — sihtodo.md item 9. No `MapManager` dependency: like
 * `useSevereWeatherAlerts`, this produces no map-layer geometry, so it is
 * called from inside its own panel component rather than from `Map.tsx`.
 *
 * Entirely client-side: the position never leaves the browser except as the
 * `lat`/`lon` query params `GET /api/ocean/geofence` already accepts for any
 * caller, and that endpoint is pure local geometry server-side (see
 * `services/geofencing.py`) — no new backend surface for this feature.
 */
export function useBoundaryWatch(): void {
  const enabled = useBoundaryWatchStore((s) => s.enabled);
  const setTransientWarning = useBoundaryWatchStore((s) => s.setTransientWarning);
  const setLatest = useBoundaryWatchStore((s) => s.setLatest);
  const addEvents = useBoundaryWatchStore((s) => s.addEvents);
  const setWasNearImbl = useBoundaryWatchStore((s) => s.setWasNearImbl);
  const setNearMpaNames = useBoundaryWatchStore((s) => s.setNearMpaNames);

  // Mutable refs, not store reads inside the callback: watchPosition's
  // callbacks are registered once per `enabled` toggle and must not close
  // over stale store values from the render that created them.
  const previousRef = useRef<GeofenceResponse | null>(null);
  const wasNearImblRef = useRef(false);
  const nearMpaNamesRef = useRef<Set<string>>(new Set());
  const lastCheckedAtRef = useRef(0);
  const inFlightRef = useRef(false);

  useEffect(() => {
    if (!enabled) return;

    if (!('geolocation' in navigator)) {
      useBoundaryWatchStore.getState().disableWithError(
        'Location services are not available in this browser.'
      );
      return;
    }

    previousRef.current = null;
    wasNearImblRef.current = false;
    nearMpaNamesRef.current = new Set();

    const onSuccess = (position: GeolocationPosition) => {
      const now = Date.now();
      if (inFlightRef.current || now - lastCheckedAtRef.current < THROTTLE_MS) return;
      lastCheckedAtRef.current = now;
      inFlightRef.current = true;

      const { latitude, longitude } = position.coords;
      fetchGeofence({ lat: latitude, lng: longitude })
        .then((current) => {
          const result = evaluateBoundaryEvents(
            previousRef.current,
            current,
            { latitude, longitude },
            wasNearImblRef.current,
            nearMpaNamesRef.current
          );
          previousRef.current = current;
          wasNearImblRef.current = result.wasNearImbl;
          nearMpaNamesRef.current = result.nearMpaNames;
          setWasNearImbl(result.wasNearImbl);
          setNearMpaNames(result.nearMpaNames);
          setLatest(current);
          if (result.events.length > 0) addEvents(result.events);
        })
        .catch((error: unknown) => {
          setTransientWarning(error instanceof Error ? error.message : 'Boundary check unavailable');
        })
        .finally(() => {
          inFlightRef.current = false;
        });
    };

    const onError = (error: GeolocationPositionError) => {
      if (error.code === error.PERMISSION_DENIED) {
        useBoundaryWatchStore.getState().disableWithError('Location permission denied.');
        return;
      }
      // POSITION_UNAVAILABLE / TIMEOUT: transient, keep watching rather than
      // stopping tracking over one missed fix.
      setTransientWarning('Location temporarily unavailable — still watching.');
    };

    const watchId = navigator.geolocation.watchPosition(onSuccess, onError, WATCH_OPTIONS);
    return () => navigator.geolocation.clearWatch(watchId);
  }, [enabled, setTransientWarning, setLatest, addEvents, setWasNearImbl, setNearMpaNames]);
}
