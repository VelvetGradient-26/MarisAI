import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ChevronDown, CornerDownLeft, MessageSquarePlus, Trash2, TriangleAlert } from 'lucide-react';
import {
  deleteSession,
  listSessions,
  loadSession,
  sendChat,
} from '../features/map/api/chat';
import type {
  ChatObservation,
  ChatReply,
  ChatSessionSummary,
  ChatTurn,
} from '../features/map/api/chat';
import { Markdown } from '../components/Markdown';
import { useThemeStore } from '../store/themeStore';
import './chat.css';

interface Message extends ChatTurn {
  id: string;
  /** Present on assistant turns only — the provenance behind the text. */
  reply?: Pick<ChatReply, 'grounded' | 'unsupported_numbers' | 'observations' | 'sources'>;
}

const SUGGESTIONS = [
  'What are the current conditions at 10°N, 72°E?',
  'Forecast sea surface temperature there 7 days out',
  'How is the global ocean doing right now?',
  'Are there any active alerts?',
];

export function ChatPage() {
  const isDark = useThemeStore((s) => s.dark);
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessions, setSessions] = useState<ChatSessionSummary[]>([]);
  const [persistence, setPersistence] = useState(true);
  /**
   * The sidebar's three honest answers, kept apart.
   *
   * With only `sessions: []` to go on, the sidebar rendered "Your
   * conversations will appear here" from the first paint — before the listing
   * request had even been sent, and again if that request failed. Both are the
   * page stating as fact that you have no previous chats when it does not yet
   * know, which is the same failure the dashboard's `unavailable_reason`
   * contract exists to prevent. "Loading" and "could not load" are different
   * answers from "none", and only one of the three is ever true at a time.
   */
  const [sessionsStatus, setSessionsStatus] = useState<'loading' | 'ready' | 'error'>('loading');

  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    document.title = 'Maris AI | Assistant';
  }, []);

  const refreshSessions = useCallback(async () => {
    try {
      const payload = await listSessions();
      setSessions(payload.sessions);
      setPersistence(payload.persistence);
      setSessionsStatus('ready');
    } catch {
      // A failed listing must not break the chat itself — you can still ask a
      // question with no history in the sidebar. It must not be *silent*
      // either: the previous version swallowed this and left the sidebar
      // claiming there was nothing to show.
      setSessionsStatus('error');
    }
  }, []);

  useEffect(() => {
    void refreshSessions();
  }, [refreshSessions]);

  useEffect(() => {
    const node = listRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [messages, pending]);

  // Grow the box with its content instead of scrolling a two-line window.
  // Reset to `auto` first or scrollHeight only ever ratchets upward.
  useEffect(() => {
    const node = inputRef.current;
    if (!node) return;
    node.style.height = 'auto';
    node.style.height = `${Math.min(node.scrollHeight, 260)}px`;
  }, [draft]);

  const history = useMemo(
    () => messages.map(({ role, content }) => ({ role, content })),
    [messages]
  );

  async function submit(text: string) {
    const question = text.trim();
    if (!question || pending) return;

    setError(null);
    setDraft('');
    setPending(true);
    setMessages((prior) => [
      ...prior,
      { id: `u${Date.now()}`, role: 'user', content: question },
    ]);

    try {
      const reply = await sendChat(question, history, sessionId);
      setMessages((prior) => [
        ...prior,
        { id: `a${Date.now()}`, role: 'assistant', content: reply.answer, reply },
      ]);
      if (reply.session_id && reply.session_id !== sessionId) {
        setSessionId(reply.session_id);
      }
      void refreshSessions();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The assistant is unavailable.');
    } finally {
      setPending(false);
      inputRef.current?.focus();
    }
  }

  function startNew() {
    setSessionId(null);
    setMessages([]);
    setError(null);
    inputRef.current?.focus();
  }

  async function open(id: string) {
    if (id === sessionId) return;
    setError(null);
    try {
      const stored = await loadSession(id);
      setSessionId(id);
      setMessages(
        stored.map((message, index) => ({
          id: `s${id}-${index}`,
          role: message.role,
          content: message.content,
          reply:
            message.role === 'assistant'
              ? {
                  grounded: message.grounded,
                  unsupported_numbers: message.unsupported_numbers,
                  observations: message.observations,
                  sources: message.sources,
                }
              : undefined,
        }))
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not open that chat.');
    }
  }

  /* The only delete path. It used to be two: a mouse handler here, and a
     duplicate inside the row's `onKeyDown` that skipped both the `startNew()`
     below and this catch — so deleting the open chat with the keyboard left
     `sessionId` pointing at a row that no longer existed, and a failed delete
     was an unhandled rejection. The markup change below (a real sibling
     <button> instead of a nested `role="button"` span) is what makes one path
     possible: the browser supplies the keyboard behaviour. */
  async function remove(id: string) {
    try {
      await deleteSession(id);
      if (id === sessionId) startNew();
      void refreshSessions();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not delete that chat.');
    }
  }

  return (
    <div className={`chat-page${isDark ? '' : ' chat-page--light'}`}>
      <div className="chat-shell">
        <aside className="chat-sidebar">
          <button type="button" className="chat-new" onClick={startNew}>
            <MessageSquarePlus size={16} aria-hidden />
            <span>New chat</span>
          </button>

          <p className="chat-sidebar__label">
            {persistence ? 'Previous chats' : 'History unavailable'}
          </p>

          {!persistence ? (
            <p className="chat-sidebar__empty">
              No database is configured, so chats are not saved between visits.
            </p>
          ) : sessionsStatus === 'loading' ? (
            <ul className="chat-sessions" aria-busy="true">
              {[0, 1, 2].map((row) => (
                <li key={row} className="chat-session chat-session--placeholder">
                  <span className="ma-skeleton ma-skeleton--sub" style={{ width: `${8 - row}rem` }} />
                </li>
              ))}
            </ul>
          ) : sessionsStatus === 'error' ? (
            <p className="chat-sidebar__empty chat-sidebar__empty--error">
              Couldn't load your previous chats. They aren't lost — reload to try again.
            </p>
          ) : sessions.length === 0 ? (
            <p className="chat-sidebar__empty">Your conversations will appear here.</p>
          ) : (
            <ul className="chat-sessions">
              {sessions.map((entry) => (
                /* Two sibling buttons, not a button inside a button. Nesting
                   interactive content in a <button> is invalid HTML, and it is
                   why the delete needed a hand-rolled `role`/`tabIndex`/
                   `onKeyDown` in the first place — the reachable-by-keyboard
                   behaviour a real <button> gives for free. */
                <li key={entry.id} className="chat-session-row">
                  <button
                    type="button"
                    className={`chat-session${entry.id === sessionId ? ' is-active' : ''}`}
                    onClick={() => void open(entry.id)}
                  >
                    <span className="chat-session__title">{entry.title}</span>
                  </button>
                  <button
                    type="button"
                    className="chat-session__delete"
                    aria-label={`Delete chat: ${entry.title}`}
                    onClick={() => void remove(entry.id)}
                  >
                    <Trash2 size={13} aria-hidden />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </aside>

        <main className="chat-main">
          <header className="chat-header">
            <h1>Ocean Assistant</h1>
            <p>
              Answers come from live MarisAI data — forecasts, observations, bathymetry and
              model output. Every figure is traced back to the call that produced it.
            </p>
          </header>

          <div className="chat-log" ref={listRef} role="log" aria-live="polite">
            {messages.length === 0 && !pending ? (
              <div className="chat-empty">
                <p className="chat-empty__lead">Ask about conditions anywhere in the ocean.</p>
                <div className="chat-suggestions">
                  {SUGGESTIONS.map((suggestion) => (
                    <button
                      key={suggestion}
                      type="button"
                      className="chat-suggestion"
                      onClick={() => void submit(suggestion)}
                    >
                      {suggestion}
                    </button>
                  ))}
                </div>
              </div>
            ) : null}

            {messages.map((message) =>
              message.role === 'user' ? (
                <div key={message.id} className="chat-turn chat-turn--user">
                  <div className="chat-bubble chat-bubble--user">{message.content}</div>
                </div>
              ) : (
                <AssistantTurn key={message.id} message={message} />
              )
            )}

            {pending ? (
              <div className="chat-turn chat-turn--assistant">
                <div className="chat-bubble chat-bubble--assistant chat-thinking">
                  <span className="chat-dot" />
                  <span className="chat-dot" />
                  <span className="chat-dot" />
                  <span className="chat-thinking__label">Querying ocean data…</span>
                </div>
              </div>
            ) : null}
          </div>

          {error ? (
            <p className="chat-error" role="alert">
              <TriangleAlert size={15} aria-hidden />
              {error}
            </p>
          ) : null}

          <form
            className="chat-composer"
            onSubmit={(event) => {
              event.preventDefault();
              void submit(draft);
            }}
          >
            <div className={`chat-input-wrap${draft.length > 0 ? ' is-filled' : ''}`}>
              <textarea
                ref={inputRef}
                className="chat-input"
                value={draft}
                rows={1}
                placeholder="Ask about ocean conditions, forecasts or alerts…"
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' && !event.shiftKey) {
                    event.preventDefault();
                    void submit(draft);
                  }
                }}
                disabled={pending}
              />
            </div>
            <button
              type="submit"
              className="chat-send"
              disabled={pending || draft.trim().length === 0}
            >
              <CornerDownLeft size={16} aria-hidden />
              <span>Send</span>
            </button>
          </form>
          <p className="chat-disclaimer">
            Alerts shown here are threshold rules computed over real fields, not issued
            marine warnings.
          </p>
        </main>
      </div>
    </div>
  );
}

function AssistantTurn({ message }: { message: Message }) {
  const reply = message.reply;
  const [showData, setShowData] = useState(false);

  return (
    <div className="chat-turn chat-turn--assistant">
      <div className="chat-bubble chat-bubble--assistant">
        <div className="chat-answer">
          <Markdown text={message.content} />
        </div>

        {reply && !reply.grounded ? (
          <p className="chat-flag">
            <TriangleAlert size={14} aria-hidden />
            <span>
              {reply.unsupported_numbers.length === 1
                ? `The figure ${reply.unsupported_numbers[0]} could not be traced to a data source.`
                : `These figures could not be traced to a data source: ${reply.unsupported_numbers.join(', ')}.`}
            </span>
          </p>
        ) : null}

        {reply && reply.observations.length > 0 ? (
          <div className="chat-provenance">
            <button
              type="button"
              className={`chat-provenance__toggle${showData ? ' is-open' : ''}`}
              onClick={() => setShowData((open) => !open)}
              aria-expanded={showData}
            >
              <ChevronDown size={14} aria-hidden />
              {reply.observations.length === 1
                ? '1 data call'
                : `${reply.observations.length} data calls`}
            </button>
            {showData ? (
              <ul className="chat-calls">
                {reply.observations.map((observation, index) => (
                  <ObservationRow key={index} observation={observation} />
                ))}
              </ul>
            ) : null}
          </div>
        ) : null}

        {reply && reply.sources.length > 0 ? (
          <p className="chat-sources">{reply.sources.join(' · ')}</p>
        ) : null}
      </div>
    </div>
  );
}

function ObservationRow({ observation }: { observation: ChatObservation }) {
  const args = Object.entries(observation.arguments ?? {});
  return (
    <li className="chat-call">
      <code className="chat-call__name">{observation.tool}</code>
      {args.length > 0 ? (
        <span className="chat-call__args">
          {args.map(([key, value]) => `${key}=${String(value)}`).join(', ')}
        </span>
      ) : null}
      <pre className="chat-call__result">{JSON.stringify(observation.result, null, 2)}</pre>
    </li>
  );
}
