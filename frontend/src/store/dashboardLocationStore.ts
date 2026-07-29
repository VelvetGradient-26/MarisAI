import { create } from 'zustand';

interface DashboardLocation {
  lat: number;
  lng: number;
}

interface DashboardLocationStore {
  location: DashboardLocation | null;
  setLocation: (location: DashboardLocation) => void;
}

/** The last coordinate viewed on the dashboard, kept in memory across route
 * changes. DashboardPage's own state resets to DEFAULT_LOCATION whenever the
 * URL has no `?lat=&lon=` (e.g. navigating there via the navbar's plain
 * "Analytics" link, which carries no query params) — this store lets it fall
 * back to whatever was last viewed instead, so typing in a new coordinate,
 * visiting the map, and coming back doesn't silently reset the view. */
export const useDashboardLocationStore = create<DashboardLocationStore>((set) => ({
  location: null,
  setLocation: (location) => set({ location }),
}));
