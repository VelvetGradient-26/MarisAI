import { useCallback } from 'react';
import { useMapManagerContext } from './MapManagerContext';
import { useMapStore } from '../../../store/mapStore';
import { useDriftTrajectoryStore } from '../../../store/driftTrajectoryStore';
import { fetchDriftTrajectory } from '../api/driftTrajectory';
import type { DriftTrajectoryResponse } from '../api/driftTrajectory';

export const DRIFT_TRAJECTORY_LAYER_ID = 'drift-trajectory';

function toGeoJson(response: DriftTrajectoryResponse): GeoJSON.FeatureCollection {
  const features: GeoJSON.Feature[] = response.members.map((member) => ({
    type: 'Feature',
    geometry: { type: 'LineString', coordinates: member.track.map((p) => [p.lon, p.lat]) },
    properties: { kind: 'member' },
  }));
  features.push({
    type: 'Feature',
    geometry: {
      type: 'LineString',
      coordinates: response.median_track.map((p) => [p.lon, p.lat]),
    },
    properties: { kind: 'median' },
  });
  if (response.median_track.length > 0) {
    features.push({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [response.start.lon, response.start.lat] },
      properties: { role: 'start' },
    });
  }
  return { type: 'FeatureCollection', features };
}

/**
 * Plans a drift trajectory forecast from `mapStore.selectedLocation` and
 * draws the ensemble as the `drift-trajectory` line layer — same shape as
 * `useRoutePlanner`, minus a two-point picker: a trajectory has one start,
 * and it is always the point already selected on the map.
 */
export function useDriftTrajectoryPlanner() {
  const manager = useMapManagerContext();
  const selectedLocation = useMapStore((s) => s.selectedLocation);
  const preset = useDriftTrajectoryStore((s) => s.preset);
  const horizonHours = useDriftTrajectoryStore((s) => s.horizonHours);
  const status = useDriftTrajectoryStore((s) => s.status);
  const result = useDriftTrajectoryStore((s) => s.result);
  const error = useDriftTrajectoryStore((s) => s.error);
  const setPreset = useDriftTrajectoryStore((s) => s.setPreset);
  const setHorizonHours = useDriftTrajectoryStore((s) => s.setHorizonHours);
  const setLoading = useDriftTrajectoryStore((s) => s.setLoading);
  const setSuccess = useDriftTrajectoryStore((s) => s.setSuccess);
  const setError = useDriftTrajectoryStore((s) => s.setError);
  const clearStore = useDriftTrajectoryStore((s) => s.clear);

  const planTrajectory = useCallback(async () => {
    if (!selectedLocation) return;
    setLoading();
    try {
      const response = await fetchDriftTrajectory(selectedLocation, preset, horizonHours);
      const layerManager = manager?.getLayerManager();
      layerManager?.add(DRIFT_TRAJECTORY_LAYER_ID);
      layerManager?.setGeoJsonData(DRIFT_TRAJECTORY_LAYER_ID, toGeoJson(response));
      setSuccess(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Drift trajectory planning failed');
    }
  }, [manager, selectedLocation, preset, horizonHours, setLoading, setSuccess, setError]);

  const clear = useCallback(() => {
    manager?.getLayerManager()?.setGeoJsonData(DRIFT_TRAJECTORY_LAYER_ID, {
      type: 'FeatureCollection',
      features: [],
    });
    clearStore();
  }, [manager, clearStore]);

  return {
    preset,
    horizonHours,
    status,
    result,
    error,
    setPreset,
    setHorizonHours,
    planTrajectory,
    clear,
  };
}
