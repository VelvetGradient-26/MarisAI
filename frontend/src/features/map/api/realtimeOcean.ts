import type { CursorCoordinates, RealtimeOceanResponse } from '../types';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;

export async function fetchRealtimeOceanData(
  location: CursorCoordinates,
  signal?: AbortSignal
): Promise<RealtimeOceanResponse> {
  const url = API_BASE_URL
    ? new URL('/api/ocean/realtime', API_BASE_URL)
    : new URL('/api/ocean/realtime', window.location.origin);
  url.searchParams.set('lat', String(location.lat));
  url.searchParams.set('lon', String(location.lng));

  let response: Response;

  try {
    response = await fetch(url, { signal });
  } catch (error: unknown) {
    if (signal?.aborted) throw error;

    throw new Error(
      'Could not reach the backend API. Start the FastAPI server or set VITE_API_BASE_URL to a running backend.'
    );
  }

  if (!response.ok) {
    const detail = await readErrorDetail(response);
    throw new Error(detail || `Realtime ocean request failed with status ${response.status}`);
  }

  return response.json() as Promise<RealtimeOceanResponse>;
}

async function readErrorDetail(response: Response): Promise<string | null> {
  try {
    const payload = (await response.json()) as { detail?: string };
    return payload.detail ?? null;
  } catch {
    return null;
  }
}
