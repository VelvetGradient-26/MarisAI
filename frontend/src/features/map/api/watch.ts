import { API_BASE_URL } from '../../../utils/apiBase';
import { clientId } from './chat';

export interface WatchRequest {
  email: string;
  label: string;
  latitude: number;
  longitude: number;
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
  return `Watch request failed with status ${response.status}`;
}

/** Opens an unconfirmed watch and triggers a confirmation email — reuses
 * the same per-browser `client_id` chat sessions use (`features/map/api/
 * chat.ts`), following CLAUDE.md's own rule to reuse it rather than invent
 * a second per-browser identifier. */
export async function subscribeWatch(request: WatchRequest, signal?: AbortSignal): Promise<void> {
  const response = await fetch(url('/api/v1/watch'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...request, client_id: clientId() }),
    signal,
  });
  if (!response.ok) {
    throw new Error(await extractErrorMessage(response));
  }
}

export async function confirmWatch(token: string, signal?: AbortSignal): Promise<void> {
  const target = url('/api/v1/watch/confirm');
  target.searchParams.set('token', token);
  const response = await fetch(target, { signal });
  if (!response.ok) {
    throw new Error(await extractErrorMessage(response));
  }
}

export async function unsubscribeWatch(token: string, signal?: AbortSignal): Promise<void> {
  const target = url('/api/v1/watch/unsubscribe');
  target.searchParams.set('token', token);
  const response = await fetch(target, { signal });
  if (!response.ok) {
    throw new Error(await extractErrorMessage(response));
  }
}
