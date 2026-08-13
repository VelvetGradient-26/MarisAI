import { useEffect } from 'react';
import { fetchForecastVectorCatalog } from '../api/forecastVectors';
import { forecastVectorLayers } from '../layers/forecastVectorLayers';
import type { MapManager } from '../managers/MapManager';

/**
 * Registers a particle layer for every forecast vector pair the backend can
 * serve.
 *
 * The vector twin of `useForecastGridLayers`, and separate from it on purpose:
 * a vector field needs *two* grids that share a horizon, so it appears and
 * disappears on different conditions than the scalar layers, and a single
 * failed fetch should not take out both sets.
 *
 * Same lifecycle as the scalar hook — runs once when the map is ready and then
 * never again (grids rebuild twice a day; a layer list that reshuffles under a
 * user mid-session is worse than one a few hours stale), and fails quietly,
 * because these layers are additive and the map is fully usable without them.
 */
export function useForecastVectorLayers(manager: MapManager | null, ready: boolean) {
  useEffect(() => {
    if (!manager || !ready) return;
    const layerManager = manager.getLayerManager();
    if (!layerManager) return;

    let cancelled = false;

    fetchForecastVectorCatalog()
      .then((entries) => {
        if (cancelled) return;

        // An entry carrying `error` is a pair the backend knows about but
        // cannot serve — a missing component grid, or two grids that share no
        // horizon. Logged rather than dropped silently: "the forecast currents
        // layer is missing" is a question someone will ask, and the answer is
        // usually "current_v was never built".
        entries
          .filter((entry) => entry.error)
          .forEach((entry) => {
            console.info(`[forecast] vector field "${entry.key}" unavailable: ${entry.error}`);
          });

        const descriptors = entries.flatMap(forecastVectorLayers);
        descriptors.forEach((descriptor) => layerManager.register(descriptor));
        if (descriptors.length > 0) {
          console.info(
            `[forecast] registered ${descriptors.length} forecast particle layer(s) from ` +
              `${entries.length} vector field(s)`
          );
        }
      })
      .catch((error) => {
        console.warn(
          '[forecast] vector catalog unavailable, skipping forecast particle layers',
          error
        );
      });

    return () => {
      cancelled = true;
    };
  }, [manager, ready]);
}
