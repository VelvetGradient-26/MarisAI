const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;

/**
 * A per-browser identifier used to scope chat history.
 *
 * Not an account and not access control — authentication was removed from this
 * codebase, so there is no user to own a session. It keeps one browser's chats
 * separate from another's on a shared deployment; anyone who learned this value
 * could read the same history. `localStorage` rather than `sessionStorage`
 * precisely because it must outlive the tab.
 */
const CLIENT_KEY = 'maris.chat.clientId';

export function clientId(): string {
  let existing = localStorage.getItem(CLIENT_KEY);
  if (!existing) {
    existing =
      typeof crypto !== 'undefined' && 'randomUUID' in crypto
        ? crypto.randomUUID()
        : `c${Date.now()}${Math.random().toString(36).slice(2, 12)}`;
    localStorage.setItem(CLIENT_KEY, existing);
  }
  return existing;
}

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
  session_id: string | null;
}

export interface ChatSessionSummary {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface StoredMessage extends ChatTurn {
  observations: ChatObservation[];
  sources: string[];
  grounded: boolean;
  unsupported_numbers: string[];
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
  sessionId: string | null,
  signal?: AbortSignal
): Promise<ChatReply> {
  const response = await fetch(url('/api/v1/chat'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      message,
      client_id: clientId(),
      session_id: sessionId,
      // Only consulted when the backend has no database. When it does, the
      // stored transcript is the authority and this is ignored.
      history: history.slice(-20),
    }),
    signal,
  });
  if (!response.ok) {
    throw new Error(await extractErrorMessage(response));
  }
  return (await response.json()) as ChatReply;
}

export async function listSessions(
  signal?: AbortSignal
): Promise<{ sessions: ChatSessionSummary[]; persistence: boolean }> {
  const target = url('/api/v1/chat/sessions');
  target.searchParams.set('client_id', clientId());
  const response = await fetch(target, { signal });
  if (!response.ok) throw new Error(await extractErrorMessage(response));
  return (await response.json()) as { sessions: ChatSessionSummary[]; persistence: boolean };
}

export async function loadSession(
  sessionId: string,
  signal?: AbortSignal
): Promise<StoredMessage[]> {
  const target = url(`/api/v1/chat/sessions/${sessionId}`);
  target.searchParams.set('client_id', clientId());
  const response = await fetch(target, { signal });
  if (!response.ok) throw new Error(await extractErrorMessage(response));
  const payload = (await response.json()) as { messages: StoredMessage[] };
  return payload.messages;
}

export async function deleteSession(sessionId: string, signal?: AbortSignal): Promise<void> {
  const target = url(`/api/v1/chat/sessions/${sessionId}`);
  target.searchParams.set('client_id', clientId());
  const response = await fetch(target, { method: 'DELETE', signal });
  if (!response.ok) throw new Error(await extractErrorMessage(response));
}
