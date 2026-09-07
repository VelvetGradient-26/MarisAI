import { useCallback, useEffect, useRef, useState } from 'react';

export type PointFetchStatus = 'idle' | 'loading' | 'error' | 'success';

export interface PointFetchState<T> {
  status: PointFetchStatus;
  data: T | null;
  error: string | null;
  /** Call with a fresh fetcher closure — not fixed at the hook call site,
   * since a caller like literature search needs whatever query text is
   * current *at click time*, not whatever it was on mount. */
  run: (fetcher: (signal: AbortSignal) => Promise<T>) => void;
}

/**
 * The `idle/loading/error/success` skeleton `SelectedLocationPanel.tsx`'s
 * SST/wind/currents/OHC cards already duplicate four times over, extracted
 * for the four click-triggered point tools (risk/tide/argo/literature) —
 * none of those four correspond to a map layer the way SST etc. do, so
 * unlike those cards this fires on `run()`, never on a `useEffect` tied to
 * `selectedLocation` changing. Firing four extra live fetches (one of which
 * itself fans out to three upstreams) on every single map click would be
 * wasteful for data the reader may not have asked to see.
 */
export function usePointFetch<T>(): PointFetchState<T> {
  const [status, setStatus] = useState<PointFetchStatus>('idle');
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const inFlight = useRef<AbortController | null>(null);

  const run = useCallback((fetcher: (signal: AbortSignal) => Promise<T>) => {
    inFlight.current?.abort();
    const controller = new AbortController();
    inFlight.current = controller;
    setStatus('loading');
    setError(null);

    fetcher(controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return;
        setData(result);
        setStatus('success');
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setError(err instanceof Error ? err.message : 'Request failed');
        setStatus('error');
      });
  }, []);

  useEffect(() => () => inFlight.current?.abort(), []);

  return { status, data, error, run };
}
