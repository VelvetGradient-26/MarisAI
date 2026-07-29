import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { ProjectionMode } from '../features/map/types';

interface MapPreferencesStore {
  projection: ProjectionMode;
  setProjection: (projection: ProjectionMode) => void;
}

/** Map view preferences that must outlive the MapLibre instance. The map
 * route is lazy and its MapManager is destroyed on every navigation away, so
 * anything held only on the manager (as the projection mode was) silently
 * reverts to its default the moment the user visits another page. Persisted
 * to localStorage like themeStore/timezoneStore — a chosen 2D/3D view is a
 * user preference, not transient map state, so it belongs here rather than
 * in mapStore (which mirrors a live MapLibre instance). */
export const useMapPreferencesStore = create<MapPreferencesStore>()(
  persist(
    (set) => ({
      projection: 'globe',
      setProjection: (projection) => set({ projection }),
    }),
    { name: 'marisai-map-preferences' }
  )
);
