import type { VectorFieldMeta } from '../vectorField/VectorFieldParticleLayer';

const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL || window.location.origin;

/** Which half of the pair a layer draws: the prediction, or the observation it
 *  was launched from. Both are fields; `anchor` is what makes the forecast
 *  readable, since "is this different from today" is the only question a
 *  forecast flow map answers. */
export type ForecastVectorMode = 'forecast' | 'anchor';

export interface ForecastVectorEntry {
  key: string;
  label: string;
  unit: string;
  u_variable: string;
  v_variable: string;
  speed_max_legend: number;
  direction_convention: string;
  horizons: number[];
  resolution_deg?: number;
  observation_date?: string | null;
  generated_at?: string | null;
  model?: string;
  sources?: string[];
  skill_scores?: string;
  missing_covariates?: string[];
  /** Present when the pair cannot be served — a missing grid, or two grids
   *  that share no horizon. The entry is still returned so the reason can be
   *  logged rather than the layer silently not existing. */
  error?: string;
}

export type ForecastVectorMeta = VectorFieldMeta & {
  key: string;
  label: string;
  unit: string;
  horizon_days: number;
  mode: ForecastVectorMode;
  direction_convention: string;
  timestamp?: string | null;
  generated_at?: string | null;
  resolution_deg?: number;
  model?: string;
  source?: string;
};

function url(path: string): string {
  return new URL(path, API_BASE_URL).toString();
}

export function forecastVectorFieldTextureUrl(
  key: string,
  horizon: number,
  mode: ForecastVectorMode
): string {
  return url(`/api/tiles/forecast/vector/${key}/${horizon}/${mode}/field.png`);
}

export async function fetchForecastVectorCatalog(
  signal?: AbortSignal
): Promise<ForecastVectorEntry[]> {
  const response = await fetch(url('/api/tiles/forecast/vector/catalog'), { signal });
  if (!response.ok) {
    throw new Error(`Forecast vector catalog request failed with status ${response.status}`);
  }
  const body = (await response.json()) as { fields: ForecastVectorEntry[] };
  return body.fields ?? [];
}

export function fetchForecastVectorMeta(
  key: string,
  horizon: number,
  mode: ForecastVectorMode
): (signal?: AbortSignal) => Promise<ForecastVectorMeta> {
  return async (signal?: AbortSignal) => {
    const response = await fetch(
      url(`/api/tiles/forecast/vector/${key}/${horizon}/${mode}/meta`),
      { signal }
    );
    if (!response.ok) {
      throw new Error(`Forecast vector meta request failed with status ${response.status}`);
    }
    return (await response.json()) as ForecastVectorMeta;
  };
}
