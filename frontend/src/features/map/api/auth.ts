const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;

export interface AuthUser {
  id: string;
  email: string;
  name: string;
  picture: string;
}

function url(path: string): URL {
  return API_BASE_URL ? new URL(path, API_BASE_URL) : new URL(path, window.location.origin);
}

async function extractErrorMessage(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: unknown };
    if (typeof payload.detail === 'string') return payload.detail;
  } catch {
    // Response body wasn't JSON — fall through to the generic message below.
  }
  return `Auth request failed with status ${response.status}`;
}

/** Full-page navigation target, not a fetch: the OAuth flow is a chain of
 * browser redirects through Google and back, which XHR can't follow. */
export function loginUrl(): string {
  return url('/api/v1/auth/login').toString();
}

/** Resolves to null when nobody is signed in. A 401 here is the expected
 * anonymous answer, not a failure — only real errors throw. */
export async function fetchCurrentUser(signal?: AbortSignal): Promise<AuthUser | null> {
  const response = await fetch(url('/api/v1/auth/me'), {
    credentials: 'include',
    signal,
  });
  if (response.status === 401) return null;
  if (!response.ok) throw new Error(await extractErrorMessage(response));
  return (await response.json()) as AuthUser;
}

export async function logout(signal?: AbortSignal): Promise<void> {
  const response = await fetch(url('/api/v1/auth/logout'), {
    method: 'POST',
    credentials: 'include',
    signal,
  });
  if (!response.ok) throw new Error(await extractErrorMessage(response));
}
