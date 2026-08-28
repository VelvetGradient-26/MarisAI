import { useEffect, useRef, useState } from 'react';
import { fetchSevereWeatherAlerts } from '../api/severeWeather';
import type { SevereWeatherResponse } from '../api/severeWeather';

/**
 * Matches `services/severe_weather.py`'s own 10-minute CAP-feed cache TTL —
 * polling faster would only re-request a cache that cannot have changed.
 */
const REFRESH_INTERVAL_MS = 10 * 60 * 1000;

export interface SevereWeatherAlertsState {
  payload: SevereWeatherResponse | null;
  loading: boolean;
  unavailableReason: string | null;
}

/**
 * Feeds the severe-weather alerts panel/badge.
 *
 * Unlike every map-layer hook in this feature, this has no MapManager
 * dependency at all: IMD's CAP feed carries no exposed per-alert geometry
 * (see `services/severe_weather.py` — the polygon/circle stay internal to
 * the backend's own `_Alert`), so there is nothing here for a GeoJSON layer
 * to draw. This is a panel/badge, not a map overlay — see sihtodo.md item 1.
 * Always polls once mounted, independent of any panel-open UI state, so a
 * collapsed badge still shows a live count.
 */
export function useSevereWeatherAlerts(): SevereWeatherAlertsState {
  const [payload, setPayload] = useState<SevereWeatherResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [unavailableReason, setUnavailableReason] = useState<string | null>(null);
  const inFlight = useRef<AbortController | null>(null);

  useEffect(() => {
    let disposed = false;
    let pollTimer: number | undefined;

    const load = async () => {
      inFlight.current?.abort();
      const controller = new AbortController();
      inFlight.current = controller;
      setLoading(true);

      try {
        const result = await fetchSevereWeatherAlerts(controller.signal);
        if (disposed || controller.signal.aborted) return;
        setPayload(result);
        setUnavailableReason(null);
      } catch (error) {
        if (disposed || controller.signal.aborted) return;
        setUnavailableReason(
          error instanceof Error ? error.message : 'Severe-weather alerts unavailable'
        );
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
  }, []);

  return { payload, loading, unavailableReason };
}
