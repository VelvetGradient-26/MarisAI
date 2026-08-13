import type { CurrentsMetaResponse } from './currents';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;

/** One offered depth level, and whether it can be drawn right now.
 *
 *  `available` plus a reason rather than a silent omission: a level that is
 *  still fetching and a level whose fetch failed are different answers, and
 *  both differ from "this level does not exist". Same rule the dashboard holds
 *  for every KPI. */
export interface CurrentsDepthLevel {
  depth_m: number;
  label: string;
  available: boolean;
  unit: string;
  speed_max_legend: number;
  unavailable_reason?: string;
}

export interface CurrentsDepthMetaResponse extends CurrentsMetaResponse {
  /** The model level that actually answered, which is the nearest to what was
   *  requested — 200 m resolves to 186.13 m. Reported rather than rounded away. */
  depth_m: number;
  requested_depth_m: number;
  depth_ladder: number[];
}

function url(path: string): URL {
  return API_BASE_URL ? new URL(path, API_BASE_URL) : new URL(path, window.location.origin);
}

export function currentsDepthFieldTextureUrl(depthM: number): string {
  const target = url('/api/tiles/currents/depth/field.png');
  target.searchParams.set('depth_m', String(depthM));
  return target.toString();
}

export async function fetchCurrentsDepthCatalog(
  signal?: AbortSignal
): Promise<CurrentsDepthLevel[]> {
  const response = await fetch(url('/api/tiles/currents/depth/catalog'), { signal });
  if (!response.ok) {
    throw new Error(`Currents depth catalog request failed with status ${response.status}`);
  }
  const body = (await response.json()) as { levels: CurrentsDepthLevel[] };
  return body.levels;
}

export function fetchCurrentsDepthMeta(depthM: number) {
  return async (signal?: AbortSignal): Promise<CurrentsDepthMetaResponse> => {
    const target = url('/api/ocean/currents/depth/meta');
    target.searchParams.set('depth_m', String(depthM));
    const response = await fetch(target, { signal });
    if (!response.ok) {
      throw new Error(`Currents depth meta request failed with status ${response.status}`);
    }
    return (await response.json()) as CurrentsDepthMetaResponse;
  };
}
