const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;

export interface ChatTurn {
  role: 'user' | 'assistant';
  content: string;
}

export interface ChatObservation {
  tool: string;
  arguments: Record<string, unknown>;
  result: unknown;
}

export interface ChatReply {
  answer: string;
  /**
   * Whether every figure in `answer` traces back to a tool result. The backend
   * annotates rather than discarding, so a false here is a real answer with
   * some numbers the model produced itself — the UI has to surface that rather
   * than quietly rendering it as though it were measured.
   */
  grounded: boolean;
  unsupported_numbers: string[];
  observations: ChatObservation[];
  sources: string[];
  truncated: boolean;
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
  return `Chat request failed with status ${response.status}`;
}

export async function sendChat(
  message: string,
  history: ChatTurn[],
  signal?: AbortSignal
): Promise<ChatReply> {
  const response = await fetch(url('/api/v1/chat'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    // The backend caps history at 20 turns and rejects more. Trimming here
    // keeps a long conversation working rather than failing validation once
    // the user passes the limit.
    body: JSON.stringify({ message, history: history.slice(-20) }),
    signal,
  });
  if (!response.ok) {
    throw new Error(await extractErrorMessage(response));
  }
  return (await response.json()) as ChatReply;
}
