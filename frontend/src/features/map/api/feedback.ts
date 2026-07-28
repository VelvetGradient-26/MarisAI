const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;

export interface FeedbackRequest {
  name: string;
  email: string;
  message: string;
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
  return `Feedback request failed with status ${response.status}`;
}

export async function sendFeedback(request: FeedbackRequest, signal?: AbortSignal): Promise<void> {
  const response = await fetch(url('/api/v1/feedback'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
    signal,
  });
  if (!response.ok) {
    throw new Error(await extractErrorMessage(response));
  }
}
