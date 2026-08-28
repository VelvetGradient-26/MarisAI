import { create } from 'zustand';
import type { CursorCoordinates } from '../features/map/types';
import type { RouteResponse } from '../features/map/api/routing';

export type RoutePlanStatus = 'idle' | 'loading' | 'success' | 'error';

interface RouteStore {
  start: CursorCoordinates | null;
  end: CursorCoordinates | null;
  status: RoutePlanStatus;
  result: RouteResponse | null;
  error: string | null;
  setStart: (point: CursorCoordinates) => void;
  setEnd: (point: CursorCoordinates) => void;
  setLoading: () => void;
  setSuccess: (result: RouteResponse) => void;
  setError: (error: string) => void;
  clear: () => void;
}

/**
 * Two clicked points plus the planned route between them, kept outside
 * `mapStore` because `mapStore.selectedLocation` is a single "point of
 * interest" the whole app shares (dashboard included) — the route needs two
 * independently-set points that both derive from clicks on that same shared
 * value, one at a time, via `SelectedLocationPanel`'s "Set as start/
 * destination" buttons.
 */
export const useRouteStore = create<RouteStore>((set) => ({
  start: null,
  end: null,
  status: 'idle',
  result: null,
  error: null,
  setStart: (start) => set({ start, status: 'idle', result: null, error: null }),
  setEnd: (end) => set({ end, status: 'idle', result: null, error: null }),
  setLoading: () => set({ status: 'loading', error: null }),
  setSuccess: (result) => set({ status: 'success', result, error: null }),
  setError: (error) => set({ status: 'error', error, result: null }),
  clear: () => set({ start: null, end: null, status: 'idle', result: null, error: null }),
}));
