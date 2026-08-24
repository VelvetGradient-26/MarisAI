import { useMemo, useRef, useState } from 'react';
import { useLocalRuntime } from '@assistant-ui/react';
import type { ChatModelAdapter, ThreadMessage } from '@assistant-ui/react';
import { streamChat } from './api/stream';
import type { ChatStreamMeta } from './api/stream';
import type { ChatTurn } from '../map/api/chat';

/**
 * What a finished (or in-flight) assistant turn knows about its own provenance.
 *
 * `pending` is not cosmetic. Grounding is computed by the backend from the
 * *finished* text, so it does not exist until the terminal `meta` event —
 * which means there is a real window where the answer is on screen and
 * unverified. Rendering a "traced" affordance during that window would assert
 * a check that has not run, so the UI has to be able to say "not yet", and
 * this is the flag that lets it.
 */
export interface TurnProvenance {
  pending: boolean;
  tools: { tool: string; arguments: Record<string, unknown>; agent?: string | null }[];
  // The orchestrator's own delegation decisions, in the order they were made
  // — arrives before the specialist's tools do, since it is the reason the
  // specialist was asked, not something it produced.
  delegations: { agent: string; question: string }[];
  meta: ChatStreamMeta | null;
}

const EMPTY: TurnProvenance = { pending: true, tools: [], delegations: [], meta: null };

function textOf(message: ThreadMessage): string {
  return message.content
    .map((part) => (part.type === 'text' ? part.text : ''))
    .join('')
    .trim();
}

/**
 * Bridges MarisAI's SSE endpoint to assistant-ui's local runtime.
 *
 * assistant-ui owns the thread: message list, ordering, in-flight status,
 * cancellation, the composer's state machine. This adapter owns exactly one
 * thing — turning one user turn into streamed content — which is the split
 * that made adopting it worthwhile.
 *
 * **Provenance rides beside the thread, not inside it.** assistant-ui's message
 * model has no place for "which ocean data calls produced this sentence", and
 * inventing one would mean encoding it into the text. Instead each run writes
 * into a `Map` keyed by the run's assistant message id, and components read it
 * back with `useTurnProvenance`. The map is React state so that a `meta` event
 * arriving after the last token still re-renders the grounding banner.
 */
export function useMarisChatRuntime() {
  const [provenance, setProvenance] = useState<Record<string, TurnProvenance>>({});
  const [error, setError] = useState<string | null>(null);
  // Read inside `run` rather than captured in the closure: the session id is
  // assigned by the *first* reply, and a stale capture would start every later
  // turn a new conversation.
  const sessionRef = useRef<string | null>(null);

  const adapter = useMemo<ChatModelAdapter>(
    () => ({
      async *run({ messages, abortSignal, unstable_assistantMessageId }) {
        const id = unstable_assistantMessageId ?? 'pending';
        const question = textOf(messages[messages.length - 1]);

        // Everything before this turn, in the shape the backend expects. Only
        // used when no database is configured — otherwise the stored
        // transcript is the authority (see `services/chat/agent.py`).
        const history: ChatTurn[] = messages.slice(0, -1).map((message) => ({
          role: message.role === 'user' ? 'user' : 'assistant',
          content: textOf(message),
        }));

        setError(null);
        setProvenance((prior) => ({ ...prior, [id]: { ...EMPTY } }));

        let text = '';
        let tools: TurnProvenance['tools'] = [];
        let delegations: TurnProvenance['delegations'] = [];

        for await (const event of streamChat({
          message: question,
          history,
          sessionId: sessionRef.current,
          signal: abortSignal,
        })) {
          if (event.type === 'delta') {
            text += event.text;
            yield { content: [{ type: 'text', text }] };
          } else if (event.type === 'reset') {
            // The turn asked for a tool after emitting prose, so that prose was
            // preamble rather than the answer. Rare, but it has to be handled
            // or the answer arrives with a false start glued to the front.
            text = '';
            yield { content: [{ type: 'text', text }] };
          } else if (event.type === 'delegate') {
            delegations = [...delegations, { agent: event.agent, question: event.question }];
            setProvenance((prior) => ({
              ...prior,
              [id]: { ...(prior[id] ?? EMPTY), delegations },
            }));
            yield { content: [{ type: 'text', text }] };
          } else if (event.type === 'tool') {
            tools = [...tools, { tool: event.tool, arguments: event.arguments, agent: event.agent }];
            setProvenance((prior) => ({
              ...prior,
              [id]: { ...(prior[id] ?? EMPTY), tools },
            }));
            // Yielding the unchanged text keeps the run alive while the tool
            // panel updates, so the user sees data calls land during the long
            // silence before the first token.
            yield { content: [{ type: 'text', text }] };
          } else if (event.type === 'meta') {
            const { type: _type, ...meta } = event;
            if (meta.session_id) sessionRef.current = meta.session_id;
            setProvenance((prior) => ({
              ...prior,
              [id]: { pending: false, tools, delegations, meta },
            }));
            yield { content: [{ type: 'text', text: meta.answer }] };
          } else if (event.type === 'error') {
            throw new Error(event.message);
          }
        }
      },
    }),
    []
  );

  const runtime = useLocalRuntime(adapter);

  return {
    runtime,
    provenance,
    error,
    setError,
    sessionRef,
    resetProvenance: () => setProvenance({}),
  };
}
