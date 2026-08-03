const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;

export interface SavedLocation {
  id: string;
  label: string;
  lat: number;
  lon: number;
  createdAt: string;
}

export interface SavedLocationRequest {
  label: string;
  lat: number;
  lon: number;
}

function url(path: string): URL {
  return API_BASE_URL ? new URL(path, API_BASE_URL) : new URL(path, window.location.origin);
}

async function extractErrorMessage(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: unknown };
    if (typeof payload.detail === 'string') return payload.detail;
    if (Array.isArray(payload.detail)) {
      return payload.detail
        .map((item) => (item as { msg?: string }).msg ?? '')
        .filter(Boolean)
        .join('; ');
    }
  } catch {
    // Response body wasn't JSON — fall through to the generic message below.
  }
  return `Saved-locations request failed with status ${response.status}`;
}

export async function fetchSavedLocations(signal?: AbortSignal): Promise<SavedLocation[]> {
  const response = await fetch(url('/api/v1/saved-locations'), {
    credentials: 'include',
    signal,
  });
  if (!response.ok) throw new Error(await extractErrorMessage(response));
  const payload = (await response.json()) as { locations: SavedLocation[] };
  return payload.locations;
}

export async function createSavedLocation(
  request: SavedLocationRequest,
  signal?: AbortSignal
): Promise<SavedLocation> {
  const response = await fetch(url('/api/v1/saved-locations'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
    credentials: 'include',
    signal,
  });
  if (!response.ok) throw new Error(await extractErrorMessage(response));
  return (await response.json()) as SavedLocation;
}

export async function deleteSavedLocation(id: string, signal?: AbortSignal): Promise<void> {
  const response = await fetch(url(`/api/v1/saved-locations/${id}`), {
    method: 'DELETE',
    credentials: 'include',
    signal,
  });
  if (!response.ok) throw new Error(await extractErrorMessage(response));
}
