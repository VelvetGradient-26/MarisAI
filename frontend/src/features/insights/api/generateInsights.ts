import type { RealtimeOceanResponse } from '../../map/types';
import type { OceanInsightsResponse } from '../types';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;

export async function generateOceanInsights(
  data: RealtimeOceanResponse,
  signal?: AbortSignal
): Promise<OceanInsightsResponse> {
  const url = API_BASE_URL
    ? new URL('/api/insights/generate', API_BASE_URL)
    : new URL('/api/insights/generate', window.location.origin);

  let response: Response;

  try {
    response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      signal,
      body: JSON.stringify({
        current: data.current,
        units: data.units,
        location_context: data.location_context,
        requested: {
          latitude: data.requested.latitude,
          longitude: data.requested.longitude,
        },
      }),
    });
  } catch (error: unknown) {
    if (signal?.aborted) throw error;

    throw new Error(
      'Could not reach the backend API. Start the FastAPI server or set VITE_API_BASE_URL to a running backend.'
    );
  }

  if (!response.ok) {
    const detail = await readErrorDetail(response);
    throw new Error(detail || `Insight generation failed with status ${response.status}`);
  }

  return (await response.json()) as OceanInsightsResponse;
}

async function readErrorDetail(response: Response): Promise<string | null> {
  try {
    const payload = (await response.json()) as { detail?: string };
    return payload.detail ?? null;
  } catch {
    return null;
  }
}
