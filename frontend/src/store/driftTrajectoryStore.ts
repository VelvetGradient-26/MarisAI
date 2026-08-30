import { create } from 'zustand';
import type { DriftTrajectoryResponse } from '../features/map/api/driftTrajectory';

export type DriftTrajectoryPlanStatus = 'idle' | 'loading' | 'success' | 'error';

interface DriftTrajectoryStore {
  preset: string;
  horizonHours: number;
  status: DriftTrajectoryPlanStatus;
  result: DriftTrajectoryResponse | null;
  error: string | null;
  setPreset: (preset: string) => void;
  setHorizonHours: (hours: number) => void;
  setLoading: () => void;
  setSuccess: (result: DriftTrajectoryResponse) => void;
  setError: (error: string) => void;
  clear: () => void;
}

/**
 * The drift-trajectory planner's form state + last result. No "start point"
 * field, unlike `routeStore`'s two independent points — a trajectory has one
 * start, and it is always `mapStore.selectedLocation`, the point the panel is
 * already showing.
 */
export const useDriftTrajectoryStore = create<DriftTrajectoryStore>((set) => ({
  preset: 'life_raft',
  horizonHours: 48,
  status: 'idle',
  result: null,
  error: null,
  setPreset: (preset) => set({ preset, status: 'idle', result: null, error: null }),
  setHorizonHours: (horizonHours) => set({ horizonHours, status: 'idle', result: null, error: null }),
  setLoading: () => set({ status: 'loading', error: null }),
  setSuccess: (result) => set({ status: 'success', result, error: null }),
  setError: (error) => set({ status: 'error', error, result: null }),
  clear: () => set({ status: 'idle', result: null, error: null }),
}));
