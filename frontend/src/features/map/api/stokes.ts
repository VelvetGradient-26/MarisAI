import type { CursorCoordinates } from '../types';
import type { CurrentsMetaResponse, CurrentsPointResponse } from './currents';

import { API_BASE_URL } from '../../../utils/apiBase';

/**
 * Stokes drift shares the currents response shape exactly — same units, same
 * `direction_toward_deg` convention, same land sentinel — because it is the
 * same kind of quantity measured a different way. Reusing the types rather than
 * restating them keeps that true: if one grows a field the other gets it, and
 * the particle engine consumes both through one interface.
 */
export type StokesPointResponse = CurrentsPointResponse;
export type StokesMetaResponse = CurrentsMetaResponse;

function url(path: string): URL {
  return API_BASE_URL ? new URL(path, API_BASE_URL) : new URL(path, window.location.origin);
}

export function stokesFieldTextureUrl(): string {
  return url('/api/tiles/stokes/field.png').toString();
}

export async function fetchStokesPoint(
  location: CursorCoordinates,
  signal?: AbortSignal
): Promise<StokesPointResponse> {
  const target = url('/api/ocean/stokes/point');
  target.searchParams.set('lat', String(location.lat));
  target.searchParams.set('lon', String(location.lng));

  const response = await fetch(target, { signal });
  if (!response.ok) {
    throw new Error(`Stokes drift point request failed with status ${response.status}`);
  }
  return (await response.json()) as StokesPointResponse;
}

export async function fetchStokesMeta(signal?: AbortSignal): Promise<StokesMetaResponse> {
  const response = await fetch(url('/api/ocean/stokes/meta'), { signal });
  if (!response.ok) {
    throw new Error(`Stokes drift meta request failed with status ${response.status}`);
  }
  return (await response.json()) as StokesMetaResponse;
}
