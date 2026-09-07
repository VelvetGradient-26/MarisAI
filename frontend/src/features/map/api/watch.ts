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

/** One of this browser's own watches, per `GET /api/v1/watch` — deliberately
 * carries no email (the backend never returns it, even to its own creator,
 * so a caller can't enumerate addresses via this list). */
export interface MyWatch {
  id: string;
  label: string;
  latitude: number;
  longitude: number;
  radius_km: number;
  confirmed: boolean;
  created_at: string;
}

export async function fetchMyWatches(signal?: AbortSignal): Promise<MyWatch[]> {
  const target = url('/api/v1/watch');
  target.searchParams.set('client_id', clientId());
  const response = await fetch(target, { signal });
  if (!response.ok) {
    throw new Error(await extractErrorMessage(response));
  }
  const body = (await response.json()) as { watches: MyWatch[] };
  return body.watches;
}

/** Deletes one of this browser's own watches directly (no emailed token
 * needed, unlike `unsubscribeWatch`) — scoped by the same `client_id` the
 * list above is, so it can only ever remove a watch this browser created. */
export async function deleteWatch(watchId: string, signal?: AbortSignal): Promise<void> {
  const target = url(`/api/v1/watch/${encodeURIComponent(watchId)}`);
  target.searchParams.set('client_id', clientId());
  const response = await fetch(target, { method: 'DELETE', signal });
  if (!response.ok) {
    throw new Error(await extractErrorMessage(response));
  }
}
