import { useCallback, useEffect, useRef, useState } from 'react';
import { deleteWatch, fetchMyWatches } from '../api/watch';
import type { MyWatch } from '../api/watch';

export interface MyWatchesState {
  watches: MyWatch[];
  loading: boolean;
  unavailableReason: string | null;
  refresh: () => void;
  remove: (watchId: string) => Promise<void>;
}

/**
 * Feeds the "My Alerts" panel — no MapManager dependency, same reasoning
 * `useSevereWeatherAlerts` gives for its own panel/badge: a list of watches
 * isn't geometry, so there's nothing here for a map layer to draw.
 *
 * Not polled, unlike severe-weather's 10-minute timer: a watch list only
 * ever changes in response to this browser's own actions (creating one via
 * "Watch This Location", removing one here), never independently upstream —
 * so this fetches once on mount and again whenever the caller asks
 * (`refresh`, called when the panel opens and after a successful remove).
 */
export function useMyWatches(): MyWatchesState {
  const [watches, setWatches] = useState<MyWatch[]>([]);
  const [loading, setLoading] = useState(false);
  const [unavailableReason, setUnavailableReason] = useState<string | null>(null);
  const inFlight = useRef<AbortController | null>(null);

  const load = useCallback(() => {
    inFlight.current?.abort();
    const controller = new AbortController();
    inFlight.current = controller;
    setLoading(true);

    fetchMyWatches(controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return;
        setWatches(result);
        setUnavailableReason(null);
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setUnavailableReason(error instanceof Error ? error.message : 'Alerts unavailable');
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
  }, []);

  useEffect(() => {
    load();
    return () => inFlight.current?.abort();
  }, [load]);

  const remove = useCallback(async (watchId: string) => {
    await deleteWatch(watchId);
    setWatches((current) => current.filter((watch) => watch.id !== watchId));
  }, []);

  return { watches, loading, unavailableReason, refresh: load, remove };
}
