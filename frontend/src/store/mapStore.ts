import { create } from 'zustand';
import type {
  CameraState,
  CursorCoordinates,
  BasemapId,
  RealtimeOceanResponse,
} from '../features/map/types';
import type { LayerState } from '../features/map/layers/LayerManager';

export type SelectedLocationDataStatus = 'idle' | 'loading' | 'success' | 'error';

interface MapStore {
  camera: CameraState;
  cursor: CursorCoordinates | null;
  selectedLocation: CursorCoordinates | null;
  pendingFocus: CursorCoordinates | null;
  selectedLocationData: RealtimeOceanResponse | null;
  selectedLocationDataStatus: SelectedLocationDataStatus;
  selectedLocationDataError: string | null;
  basemap: BasemapId | null;
  layers: Map<string, LayerState>;
  setCamera: (camera: CameraState) => void;
  setCursor: (cursor: CursorCoordinates) => void;
  setSelectedLocation: (location: CursorCoordinates | null) => void;
  focusSelectedLocation: (location: CursorCoordinates) => void;
  consumePendingFocus: () => void;
  setSelectedLocationDataLoading: () => void;
  setSelectedLocationDataSuccess: (data: RealtimeOceanResponse) => void;
  setSelectedLocationDataError: (error: string) => void;
  setBasemap: (id: BasemapId) => void;
  setLayerState: (layers: Map<string, LayerState>) => void;
}

const CLEARED_SELECTED_LOCATION_DATA = {
  selectedLocationData: null,
  selectedLocationDataStatus: 'idle' as const,
  selectedLocationDataError: null,
};

/**
 * Camera/cursor/basemap/layer state, synced one-way from MapLibre and the
 * managers via useMapManager. Nothing writes back into MapLibre from here
 * directly — components call manager methods (e.g. layerManager.toggle()),
 * which mutate the map and then emit back into this store. That one-way
 * flow is what keeps this from becoming the "state duplication" risk the
 * ADR flags: Zustand mirrors MapLibre, it never fights it for ownership.
 *
 * `selectedLocation` is the one exception to "mirrors MapLibre": it's the
 * app-wide point of interest, and both the map (a click) and the dashboard
 * (its coordinate form) choose it. Off-map writers use
 * `focusSelectedLocation`, which additionally queues `pendingFocus` — a
 * one-shot request for the map to move its camera there, consumed by
 * useSelectedLocationFocus once the map is mounted and ready. Keeping it a
 * queued request rather than a direct camera write is what preserves the
 * one-way rule while the map is unmounted (the map route is lazy, so the
 * dashboard usually has no MapLibre instance to talk to at all).
 */
export const useMapStore = create<MapStore>((set) => ({
  camera: { center: [0, 20], zoom: 2.2, bearing: 0, pitch: 0 },
  cursor: null,
  selectedLocation: null,
  pendingFocus: null,
  selectedLocationData: null,
  selectedLocationDataStatus: 'idle',
  selectedLocationDataError: null,
  basemap: null,
  layers: new Map(),
  setCamera: (camera) => set({ camera }),
  setCursor: (cursor) => set({ cursor }),
  setSelectedLocation: (selectedLocation) =>
    set({ selectedLocation, ...CLEARED_SELECTED_LOCATION_DATA }),
  focusSelectedLocation: (location) =>
    set((state) =>
      isSameCoordinate(state.selectedLocation, location)
        ? {}
        : {
            selectedLocation: location,
            pendingFocus: location,
            ...CLEARED_SELECTED_LOCATION_DATA,
          }
    ),
  consumePendingFocus: () => set({ pendingFocus: null }),
  setSelectedLocationDataLoading: () =>
    set({ selectedLocationDataStatus: 'loading', selectedLocationDataError: null }),
  setSelectedLocationDataSuccess: (selectedLocationData) =>
    set({
      selectedLocationData,
      selectedLocationDataStatus: 'success',
      selectedLocationDataError: null,
    }),
  setSelectedLocationDataError: (selectedLocationDataError) =>
    set({
      selectedLocationData: null,
      selectedLocationDataStatus: 'error',
      selectedLocationDataError,
    }),
  setBasemap: (basemap) => set({ basemap }),
  setLayerState: (layers) => set({ layers }),
}));

/** Coordinates round-trip through the URL as fixed-precision strings, so
 * compare at the ~1cm precision the dashboard writes rather than by
 * identity — otherwise returning to the dashboard from the map re-focuses
 * the camera on the point it's already showing. */
function isSameCoordinate(a: CursorCoordinates | null, b: CursorCoordinates) {
  if (!a) return false;
  return Math.abs(a.lat - b.lat) < 1e-6 && Math.abs(a.lng - b.lng) < 1e-6;
}
