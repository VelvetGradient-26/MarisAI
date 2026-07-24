import { create } from 'zustand';
import type { CameraState, CursorCoordinates, BasemapId } from '../features/map/types';
import type { LayerState } from '../features/map/layers/LayerManager';

interface MapStore {
  camera: CameraState;
  cursor: CursorCoordinates | null;
  basemap: BasemapId | null;
  layers: Map<string, LayerState>;
  setCamera: (camera: CameraState) => void;
  setCursor: (cursor: CursorCoordinates) => void;
  setBasemap: (id: BasemapId) => void;
  setLayerState: (layers: Map<string, LayerState>) => void;
}

/**
 * Camera/cursor/basemap/layer state, synced one-way from MapLibre and the
 * managers via useMapManager. Nothing writes back into MapLibre from here
 * directly — components call manager methods (e.g. layerManager.toggle()),
 * which mutate the map and then emit back into this store. That one-way
 * flow is what keeps this from becoming the "state duplication" risk the
 * ADR flags: Zustand mirrors MapLibre, it never fights it for ownership.
 */
export const useMapStore = create<MapStore>((set) => ({
  camera: { center: [0, 20], zoom: 2.2, bearing: 0, pitch: 0 },
  cursor: null,
  basemap: null,
  layers: new Map(),
  setCamera: (camera) => set({ camera }),
  setCursor: (cursor) => set({ cursor }),
  setBasemap: (basemap) => set({ basemap }),
  setLayerState: (layers) => set({ layers }),
}));
