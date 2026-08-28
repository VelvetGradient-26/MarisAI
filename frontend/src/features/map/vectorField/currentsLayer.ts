import { VectorFieldParticleLayer } from './VectorFieldParticleLayer';
import {
  CURRENT_SPEED_COLOR_STOPS,
  DRIFT_SPEED_COLOR_STOPS,
  STOKES_DRIFT_COLOR_STOPS,
} from './colorRamp';
import type { ColorStop } from './colorRamp';
import { driftFieldTextureUrl, fetchDriftMeta } from '../api/drift';
import { currentsFieldTextureUrl, fetchCurrentsMeta } from '../api/currents';
import {
  currentsDepthFieldTextureUrl,
  fetchCurrentsDepthMeta,
} from '../api/currentsDepth';
import { fetchStokesMeta, stokesFieldTextureUrl } from '../api/stokes';
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
 * The forecast instantiation: the same engine over a texture composed from a
 * pair of forecast grids instead of from an observation.
 *
 * **Each forecast field is drawn exactly like its live counterpart**, and that
 * is the whole rule here. A forecast flow that animated at a different pace or
 * on a different colour scale could not be compared against the live one, and
 * comparison is the only thing anyone wants from it — the layer name and its
 * attribution carry the "model, not observation" distinction, not the
 * rendering.
 *
 * Which is why the ramp and speed scale are *arguments* rather than currents'
 * constants, and this function is no longer named for currents. It was written
 * when `current_u`/`current_v` were the only trained pair, and when `wind_u`/
 * `wind_v` arrived it would have drawn forecast wind on the amber currents ramp
 * (whose domain tops out at 2 m/s, so every cell of an 8 m/s wind field renders
 * the same top colour) at currents' 12000 speed scale (which puts that wind at
 * ~265 px/s — a smear). Both failures animate convincingly, which is why the
 * visual identity now travels with the field.
 */
export function createForecastVectorParticleLayer(
  id: string,
  key: string,
  horizon: number,
  mode: ForecastVectorMode,
  initialOpacity: number,
  visual: { colorStops: ColorStop[]; visualSpeedScale?: number }
): CustomVectorFieldLayer {
  return new VectorFieldParticleLayer(
    id,
    {
      fieldTextureUrl: forecastVectorFieldTextureUrl(key, horizon, mode),
      fetchMeta: fetchForecastVectorMeta(key, horizon, mode),
      colorStops: visual.colorStops,
      visualSpeedScale: visual.visualSpeedScale,
    },
    initialOpacity
  );
}

/** The live currents' own visual identity, exported so a forecast currents
 *  layer is drawn from the same two values rather than from a copy of them. */
export const CURRENTS_VISUAL = {
  colorStops: CURRENT_SPEED_COLOR_STOPS,
  visualSpeedScale: CURRENTS_VISUAL_SPEED_SCALE,
} as const;

/**
 * Stokes drift — the wave-induced transport, on the same engine.
 *
 * Same visual speed scale as currents, deliberately. The two fields are drawn
 * to be read against each other (what carries a drifting object is their sum),
 * and a different pace would make "which one is moving the water here" a
 * question about the rendering rather than about the ocean.
 *
 * The ramp is what separates them: violet against currents' amber, both single
 * hue. See `colorRamp.ts`.
 */
export function createStokesParticleLayer(
  id: string,
  initialOpacity: number
): CustomVectorFieldLayer {
  return new VectorFieldParticleLayer(
    id,
    {
      fieldTextureUrl: stokesFieldTextureUrl(),
      fetchMeta: fetchStokesMeta,
      colorStops: STOKES_DRIFT_COLOR_STOPS,
      visualSpeedScale: CURRENTS_VISUAL_SPEED_SCALE,
    },
    initialOpacity
  );
}

/**
 * Currents at one depth level, from the daily depth-resolved product.
 *
 * Identical in every visual respect to the surface layer — same ramp, same
 * speed scale, same legend maximum — because the entire purpose of a depth
 * selector is comparing one level against another. A legend that rescaled per
 * level, or a ramp that changed with depth, would make that comparison
 * meaningless. What differs is stated in the layer's name and attribution: this
 * is a daily mean, where the surface layer is hourly.
 */
export function createCurrentsDepthParticleLayer(
  id: string,
  depthM: number,
  initialOpacity: number
): CustomVectorFieldLayer {
  return new VectorFieldParticleLayer(
    id,
    {
      fieldTextureUrl: currentsDepthFieldTextureUrl(depthM),
      fetchMeta: fetchCurrentsDepthMeta(depthM),
      colorStops: CURRENT_SPEED_COLOR_STOPS,
      visualSpeedScale: CURRENTS_VISUAL_SPEED_SCALE,
    },
    initialOpacity
  );
}

/**
 * The combined drift field — current + Stokes drift + wind leeway.
 *
 * Same engine, same visual speed scale as the three fields it sums, so it can be
 * switched against any of them and read at the same pace. What separates it is
 * the ramp: green, where currents are amber and Stokes drift violet. See
 * `colorRamp.ts` for why that is a hue rather than a second rainbow.
 *
 * `alpha` is baked into the texture URL rather than applied client-side, because
 * the sum happens where the three grids are — the browser never holds more than
 * one field. Changing the preset therefore means a new layer instance, which is
 * why `driftLayerId` keys on it: switching object type must download a new
 * texture, not reinterpret the current one.
 */
export function createDriftParticleLayer(
  id: string,
  alpha: number,
  initialOpacity: number
): CustomVectorFieldLayer {
  return new VectorFieldParticleLayer(
    id,
    {
      fieldTextureUrl: driftFieldTextureUrl(alpha),
      fetchMeta: fetchDriftMeta(alpha),
      colorStops: DRIFT_SPEED_COLOR_STOPS,
      visualSpeedScale: CURRENTS_VISUAL_SPEED_SCALE,
    },
    initialOpacity
  );
}
