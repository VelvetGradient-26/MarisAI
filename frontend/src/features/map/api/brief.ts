import type { CursorCoordinates } from '../types';

import { API_BASE_URL } from '../../../utils/apiBase';

function url(path: string): URL {
  return API_BASE_URL ? new URL(path, API_BASE_URL) : new URL(path, window.location.origin);
}

/**
 * Downloads the point brief for one coordinate.
 *
 * Same shape as `download.ts`'s exports — `.blob()` plus a filename parsed from
 * `Content-Disposition` — because it is the same job: the server has already
 * named the file, and re-deriving the name here is how the two drift apart.
 */
export async function downloadBriefPdf(
  location: CursorCoordinates,
  signal?: AbortSignal
): Promise<{ blob: Blob; filename: string }> {
  const target = url('/api/brief/pdf');
  target.searchParams.set('lat', String(location.lat));
  target.searchParams.set('lon', String(location.lng));

  const response = await fetch(target, { signal });
  if (!response.ok) {
    throw new Error(`Brief request failed with status ${response.status}`);
  }

  const disposition = response.headers.get('Content-Disposition') ?? '';
  const match = /filename="([^"]+)"/.exec(disposition);
  return {
    blob: await response.blob(),
    filename: match?.[1] ?? `marisai-brief-${location.lat.toFixed(3)}_${location.lng.toFixed(3)}.pdf`,
  };
}
