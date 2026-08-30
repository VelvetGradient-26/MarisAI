import { useEffect, useMemo, useState } from 'react';
import { useMapStore } from '../../../store/mapStore';
import { fetchHabPoint, fetchHabitatPoint } from '../api/predictions';
import type { PredictionDriver } from '../api/predictions';
import { predictionPointSources } from '../layers/layerRegistry';
import type { PredictionPointSource } from '../layers/layerRegistry';

export interface PredictionPointResult {
  layerId: string;
  source: PredictionPointSource;
  status: 'loading' | 'success' | 'error';
  /** Suitability or bloom probability, both 0-1. Null means no value here. */
  value: number | null;
  /** Null value *because the model never covered this point*, rather than
   * because it covered it and found land / no data. Different sentences. */
  outsideCoverage: boolean;
  /** The model's own description of its units, e.g. "probability of bloom". */
  valueLabel: string | null;
  /** Target date of a bloom-risk value. The HAB export is a fixed historical
   * run, not a forecast issued today, so the layer's "+3d" name alone would
   * imply three days from now — the date says which +3d this actually is. */
  date: string | null;
  /** Null for habitat (no per-cell attribution built yet) and for any hab
   * point where the export predates this field or the cell has no value. */
  drivers: PredictionDriver[] | null;
}

/**
 * Point readouts for whichever prediction layers are currently switched on.
 *
 * Follows the same "layer active -> fetch the point value" shape the panel
 * already uses for SST and wind, but there are eight prediction layers and
 * any number can be on at once, so it loops rather than being written out
 * per layer. Each active layer gets one row, in registry order.
 */
export function useSelectedLocationPredictions(
  selectedLocation: { lat: number; lng: number } | null
): PredictionPointResult[] {
  const layers = useMapStore((s) => s.layers);
  const [results, setResults] = useState<PredictionPointResult[]>([]);

  // A stable key for "which prediction layers are on", so the effect re-runs
  // when that set changes but not on every unrelated layer tweak (opacity,
  // basemap swaps) that replaces the store's layer Map.
  const activeLayerIds = useMemo(() => {
    const ids: string[] = [];
    for (const layerId of predictionPointSources.keys()) {
      if (layers.get(layerId)?.active) ids.push(layerId);
    }
    return ids;
  }, [layers]);
  const activeKey = activeLayerIds.join(',');

  useEffect(() => {
    if (!selectedLocation || activeLayerIds.length === 0) {
      setResults([]);
      return;
    }

    const controller = new AbortController();
    const { lat, lng } = selectedLocation;

    const pending: PredictionPointResult[] = activeLayerIds.map((layerId) => ({
      layerId,
      // Non-null: activeLayerIds is built by iterating this same map.
      source: predictionPointSources.get(layerId)!,
      status: 'loading',
      value: null,
      outsideCoverage: false,
      valueLabel: null,
      date: null,
      drivers: null,
    }));
    setResults(pending);

    Promise.all(
      pending.map(async (row): Promise<PredictionPointResult> => {
        try {
          if (row.source.kind === 'habitat') {
            const point = await fetchHabitatPoint(
              row.source.species,
              row.source.month,
              lat,
              lng,
              controller.signal
            );
            return {
              ...row,
              status: 'success',
              value: point.suitability,
              outsideCoverage: point.outside_coverage,
              valueLabel: point.value_label,
              drivers: null,
            };
          }
          const point = await fetchHabPoint(
            row.source.horizon,
            lat,
            lng,
            undefined,
            controller.signal
          );
          return {
            ...row,
            status: 'success',
            value: point.risk,
            outsideCoverage: point.outside_coverage,
            valueLabel: point.value_label,
            date: point.date,
            // Guards a rolling-deploy window where the backend hasn't picked
            // up this field yet, even though the type claims it's present.
            drivers: point.drivers ?? null,
          };
        } catch {
          return { ...row, status: 'error' };
        }
      })
    ).then((settled) => {
      if (controller.signal.aborted) return;
      setResults(settled);
    });

    return () => controller.abort();
    // activeLayerIds is derived from activeKey; depending on the array itself
    // would re-fire on every store update that rebuilds the layer Map.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedLocation, activeKey]);

  return results;
}
