import { useEffect } from 'react';
import { fetchForecastGridCatalog } from '../api/forecastGrids';
import { forecastLayers } from '../layers/forecastLayers';
import type { MapManager } from '../managers/MapManager';

/**
 * Registers a forecast layer for every grid the backend has built.
 *
 * Runs once the map is ready and then never again: grids are rebuilt on a
 * 12-hour schedule, so re-polling would cost a request per interval to learn
 * something that changes twice a day, and a layer list that reshuffles under a
 * user mid-session is worse than one that is a few hours stale.
 *
 * A failure here is deliberately quiet. The forecast layers are additive — the
 * map is fully usable without them — so an unreachable catalog logs and leaves
 * the rest of the layer list alone rather than surfacing an error over a
 * working map.
 */
export function useForecastGridLayers(manager: MapManager | null, ready: boolean) {
  useEffect(() => {
    if (!manager || !ready) return;
    const layerManager = manager.getLayerManager();
    if (!layerManager) return;

    let cancelled = false;

    fetchForecastGridCatalog()
      .then((entries) => {
        if (cancelled) return;
        const descriptors = entries.flatMap(forecastLayers);
        descriptors.forEach((descriptor) => layerManager.register(descriptor));
        if (descriptors.length > 0) {
          console.info(
            `[forecast] registered ${descriptors.length} forecast layer(s) from ` +
              `${entries.length} grid(s)`
          );
        }
      })
      .catch((error) => {
        console.warn('[forecast] grid catalog unavailable, skipping forecast layers', error);
      });

    return () => {
      cancelled = true;
    };
  }, [manager, ready]);
}
