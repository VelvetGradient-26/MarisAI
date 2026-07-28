import { VectorFieldParticleLayer } from './VectorFieldParticleLayer';
import { WIND_SPEED_COLOR_STOPS } from './colorRamp';
import { windFieldTextureUrl, fetchWindMeta } from '../api/wind';
import type { CustomVectorFieldLayer } from '../types';

/** The wind instantiation of the generic vector-field particle engine — the
 * only wind-specific code is this config (field texture URL, meta fetch,
 * color stops); everything else (advection, density, trails, blending)
 * lives in VectorFieldParticleLayer and is reused as-is by any future
 * vector field (currents, waves). */
export function createWindParticleLayer(id: string, initialOpacity: number): CustomVectorFieldLayer {
  return new VectorFieldParticleLayer(
    id,
    {
      fieldTextureUrl: windFieldTextureUrl(),
      fetchMeta: fetchWindMeta,
      colorStops: WIND_SPEED_COLOR_STOPS,
    },
    initialOpacity
  );
}
