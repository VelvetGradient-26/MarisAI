import { VectorFieldParticleLayer } from './VectorFieldParticleLayer';
import { CURRENT_SPEED_COLOR_STOPS } from './colorRamp';
import { currentsFieldTextureUrl, fetchCurrentsMeta } from '../api/currents';
import { forecastVectorFieldTextureUrl, fetchForecastVectorMeta } from '../api/forecastVectors';
import type { ForecastVectorMode } from '../api/forecastVectors';
import type { CustomVectorFieldLayer } from '../types';

/**
 * On-screen pixels/second per 1 m/s, times 360 — see the `u_visualSpeedScale`
 * comment in shaders.ts.
 *
 * **Not wind's 1800, and the difference is the whole reason that constant
 * became a uniform.** Surface currents run an order of magnitude slower than
 * wind: typical open ocean is 0.1-0.4 m/s against wind's 5-10. At 1800 a 0.3
 * m/s current advects ~1.5 px/s, which over a 3-second particle lifetime is
 * about 4 pixels — the layer would render as a still image with a faint
 * shimmer, and the animation is the entire point of drawing it this way.
 *
 * 12000 puts a typical 0.3 m/s flow at ~10 px/s (an unhurried drift, which is
 * honest — the ocean *is* unhurried) and the Gulf Stream's ~2 m/s at ~67 px/s,
 * so the western boundary currents visibly rip while the gyre interiors idle.
 * That contrast is the thing worth seeing, and a shared scale with wind would
 * flatten it to nothing.
 */
const CURRENTS_VISUAL_SPEED_SCALE = 12000;

/** The live-observation instantiation: Copernicus surface `uo`/`vo`, refreshed
 *  hourly alongside wind. */
export function createCurrentsParticleLayer(
  id: string,
  initialOpacity: number
): CustomVectorFieldLayer {
  return new VectorFieldParticleLayer(
    id,
    {
      fieldTextureUrl: currentsFieldTextureUrl(),
      fetchMeta: fetchCurrentsMeta,
      colorStops: CURRENT_SPEED_COLOR_STOPS,
      visualSpeedScale: CURRENTS_VISUAL_SPEED_SCALE,
    },
    initialOpacity
  );
}

/**
 * The forecast instantiation: the same engine, the same ramp and the same
 * speed scale, over a texture composed from the `current_u`/`current_v`
 * forecast grids instead of from an observation.
 *
 * Deliberately identical in every visual respect to the live layer. A forecast
 * flow that animated at a different pace or on a different colour scale could
 * not be compared against the live one, and comparison is the only thing
 * anyone wants from it — the layer name and its attribution carry the "this is
 * a model, not an observation" distinction, not the rendering.
 */
export function createForecastCurrentsParticleLayer(
  id: string,
  key: string,
  horizon: number,
  mode: ForecastVectorMode,
  initialOpacity: number
): CustomVectorFieldLayer {
  return new VectorFieldParticleLayer(
    id,
    {
      fieldTextureUrl: forecastVectorFieldTextureUrl(key, horizon, mode),
      fetchMeta: fetchForecastVectorMeta(key, horizon, mode),
      colorStops: CURRENT_SPEED_COLOR_STOPS,
      visualSpeedScale: CURRENTS_VISUAL_SPEED_SCALE,
    },
    initialOpacity
  );
}
