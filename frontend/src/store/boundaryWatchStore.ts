import { create } from 'zustand';
import type { GeofenceResponse } from '../features/map/api/geofence';

export type BoundaryEventType = 'eez_crossing' | 'imbl_approach' | 'mpa_approach';

export interface BoundaryEvent {
  id: string;
  type: BoundaryEventType;
  message: string;
  at: string;
  latitude: number;
  longitude: number;
}

const MAX_EVENTS = 20;

interface BoundaryWatchStore {
  enabled: boolean;
  status: 'idle' | 'tracking' | 'error';
  unavailableReason: string | null;
  latest: GeofenceResponse | null;
  events: BoundaryEvent[];
  // Edge-trigger state for the "approaching" detectors — see
  // hooks/useBoundaryWatch.ts's evaluateBoundaryEvents. Lives here, not as
  // hook-local state, because the hook re-runs its effect on every enable
  // toggle and this must survive that.
  wasNearImbl: boolean;
  nearMpaNames: Set<string>;

  enable: () => void;
  disable: () => void;
  disableWithError: (reason: string) => void;
  setTransientWarning: (reason: string) => void;
  setLatest: (response: GeofenceResponse) => void;
  addEvents: (events: BoundaryEvent[]) => void;
  setWasNearImbl: (near: boolean) => void;
  setNearMpaNames: (names: Set<string>) => void;
}

/**
 * Live tracking session state — deliberately not persisted (no `persist`
 * middleware, unlike themeStore/timezoneStore). Tracking is a location-
 * permission-gated session, not a preference: it must default off on every
 * fresh page load rather than silently resume watching position.
 */
export const useBoundaryWatchStore = create<BoundaryWatchStore>((set) => ({
  enabled: false,
  status: 'idle',
  unavailableReason: null,
  latest: null,
  events: [],
  wasNearImbl: false,
  nearMpaNames: new Set(),

  enable: () => set({ enabled: true, status: 'tracking', unavailableReason: null }),
  disable: () =>
    set({
      enabled: false,
      status: 'idle',
      unavailableReason: null,
      wasNearImbl: false,
      nearMpaNames: new Set(),
    }),
  // Stops tracking *and* keeps the reason, in one atomic set. An earlier
  // version called a bare setter for the message followed by `disable()`
  // separately — `disable()` resets `unavailableReason` to null, so the two
  // calls raced and the error message was clobbered back to null before it
  // ever rendered (found by actually testing the permission-denied path,
  // not by inspection — the bug was invisible from reading either call
  // alone).
  disableWithError: (reason) =>
    set({
      enabled: false,
      status: 'error',
      unavailableReason: reason,
      wasNearImbl: false,
      nearMpaNames: new Set(),
    }),
  // Does not change `status` — a missed fix (timeout/position-unavailable)
  // is not the same as tracking having stopped; the badge should keep
  // reading "tracking" with a transient note, not flip to an error state.
  setTransientWarning: (reason) => set({ unavailableReason: reason }),
  setLatest: (response) => set({ latest: response, status: 'tracking', unavailableReason: null }),
  addEvents: (newEvents) =>
    set((s) => ({ events: [...newEvents, ...s.events].slice(0, MAX_EVENTS) })),
  setWasNearImbl: (near) => set({ wasNearImbl: near }),
  setNearMpaNames: (names) => set({ nearMpaNames: names }),
}));
