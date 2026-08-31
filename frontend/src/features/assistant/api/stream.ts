/**
 * Client for `POST /api/v1/chat/stream` — the SSE half of the chat API.
 *
 * `EventSource` is not usable here: it can only issue GET requests, and the
 * turn carries a body (message, history, session, client id). So this is
 * `fetch` + a manual frame parser, which is the standard trade and also lets
 * the request be aborted properly.
 *
 * The non-streaming `sendChat` in `features/map/api/chat.ts` is untouched and
 * remains the fallback.
 */

import type { ChatDelegation, ChatObservation, ChatTurn } from '../../map/api/chat';
import { clientId } from '../../map/api/chat';

import { API_BASE_URL } from '../../../utils/apiBase';

function url(path: string): URL {
  return API_BASE_URL ? new URL(path, API_BASE_URL) : new URL(path, window.location.origin);
}

/** Terminal event. Carries everything the answer's provenance UI needs. */
export interface ChatStreamMeta {
  answer: string;
  grounded: boolean;
  unsupported_numbers: string[];
  // A refusal ("I couldn't get that") despite the ledger already holding
  // real tool results this turn. `grounded` cannot catch this — a refusal
  // states no numbers to check — so it rides as its own flag; see
  // `services/chat/agent.py::_false_refusal`.
  possible_false_refusal: boolean;
  // Glossary concepts (SST, chlorophyll, wave height, wind speed, cyclone,
  // PFZ, marine advisory) this turn's tool data touched that never appear in
  // English anywhere in a non-English answer — empty on any English answer,
  // since the backend check is script-gated. See
  // `services/chat/agent.py::_untranslated_glossary_terms`.
  glossary_gaps: string[];
  observations: ChatObservation[];
  sources: string[];
  delegations: ChatDelegation[];
  truncated: boolean;
  session_id: string | null;
}

export type ChatStreamEvent =
  | { type: 'delta'; text: string }
  | { type: 'reset' }
  // `agent` names which specialist made the call (ocean_analytics /
  // weather_safety / geospatial_risk / web_research) — absent for a tool the top-level
  // orchestrator called directly, which no longer happens in practice but
  // keeps this type honest about what the backend can send.
  | { type: 'tool'; tool: string; arguments: Record<string, unknown>; agent?: string | null }
  // The orchestrator's own reasoning, made visible: fires the moment it
  // decides to hand a sub-task to `agent`, before that specialist has run at
  // all — `question` is the sub-task in the orchestrator's own words.
  | { type: 'delegate'; agent: string; question: string }
  | ({ type: 'meta' } & ChatStreamMeta)
  | { type: 'error'; message: string };

export interface StreamChatArgs {
  message: string;
  history: ChatTurn[];
  sessionId: string | null;
  /** A `data:image/...;base64,...` URL attached to this turn, if any. */
  image?: string | null;
  signal?: AbortSignal;
}

export async function* streamChat({
  message,
  history,
  sessionId,
  image,
  signal,
}: StreamChatArgs): AsyncGenerator<ChatStreamEvent> {
  const response = await fetch(url('/api/v1/chat/stream').toString(), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    signal,
    body: JSON.stringify({
      message,
      history,
      session_id: sessionId,
      client_id: clientId(),
      image: image ?? null,
    }),
  });

  // A failure *before* the stream opens still has a real status code, so it is
  // reported as one. Once the body starts, the backend can only signal failure
  // with an in-stream `error` event — see the route's docstring.
  if (!response.ok || !response.body) {
    throw new Error(
      response.status === 503
        ? 'The assistant is unavailable right now.'
        : `The assistant failed to respond (${response.status}).`
    );
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // Frames are separated by a blank line. Anything after the last blank
      // line is a partial frame and stays in the buffer — a chunk boundary
      // lands mid-frame routinely, and parsing eagerly would drop text.
      const frames = buffer.split('\n\n');
      buffer = frames.pop() ?? '';

      for (const frame of frames) {
        const line = frame.split('\n').find((l) => l.startsWith('data: '));
        if (!line) continue;
        try {
          yield JSON.parse(line.slice(6)) as ChatStreamEvent;
        } catch {
          // A frame we cannot parse is a bug on one side or the other, but
          // dropping it is strictly better than aborting a turn that is
          // otherwise arriving fine.
        }
      }
    }
  } finally {
    // Releasing matters on the abort path: without it the connection is held
    // until GC, and the composer can start a new turn while the old one is
    // still draining.
    reader.releaseLock();
  }
}
