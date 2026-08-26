import { create } from 'zustand';
import type { PfzResponse } from '../features/map/api/pfz';
import type { GeofenceResponse } from '../features/map/api/geofence';

export interface PfzStatus {
  active: boolean;
  loading: boolean;
  unavailableReason: string | null;
  response: PfzResponse | null;
}

export interface GeofenceStatus {
  active: boolean;
  loading: boolean;
  unavailableReason: string | null;
  response: GeofenceResponse | null;
}

interface ToolsStore {
  pfz: PfzStatus;
  geofence: GeofenceStatus;
  setPfz: (status: PfzStatus) => void;
  setGeofence: (status: GeofenceStatus) => void;
}

const IDLE_PFZ: PfzStatus = { active: false, loading: false, unavailableReason: null, response: null };
const IDLE_GEOFENCE: GeofenceStatus = {
  active: false,
  loading: false,
  unavailableReason: null,
  response: null,
};

/**
 * One-way mirror of the `pfz-zones`/`geofence-status` map layers, same rule
 * `mapStore` follows for MapLibre: `usePfzZones`/`useGeofenceStatus` (called
 * from `Map.tsx`, alongside every other data-feed hook) own the fetch and the
 * `layerManager.setGeoJsonData` call, and write their result here; components
 * like `SelectedLocationPanel` only read it. Kept out of `mapStore` itself
 * because these two are click-triggered point queries, not layer/camera state
 * MapLibre itself reports.
 */
export const useToolsStore = create<ToolsStore>((set) => ({
  pfz: IDLE_PFZ,
  geofence: IDLE_GEOFENCE,
  setPfz: (pfz) => set({ pfz }),
  setGeofence: (geofence) => set({ geofence }),
}));
