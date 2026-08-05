import { useEffect, useMemo, useRef, useState } from 'react';
import { ChevronDown, CornerDownLeft, TriangleAlert } from 'lucide-react';
import { sendChat } from '../features/map/api/chat';
import type { ChatObservation, ChatReply, ChatTurn } from '../features/map/api/chat';
import { useThemeStore } from '../store/themeStore';
import './chat.css';

interface Message extends ChatTurn {
  id: string;
  /** Present on assistant turns only — the provenance behind the text. */
  reply?: ChatReply;
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

  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    document.title = 'Maris AI | Assistant';
  }, []);

  // Pin to the newest message. Depends on `pending` too so the thinking
  // indicator is scrolled into view, not just finished answers.
  useEffect(() => {
    const node = listRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [messages, pending]);

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

    const asked: Message = { id: `u${Date.now()}`, role: 'user', content: question };
    setMessages((prior) => [...prior, asked]);

    try {
      const reply = await sendChat(question, history);
      setMessages((prior) => [
        ...prior,
        { id: `a${Date.now()}`, role: 'assistant', content: reply.answer, reply },
      ]);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The assistant is unavailable.');
    } finally {
      setPending(false);
      inputRef.current?.focus();
    }
  }

  return (
    <div className={`chat-page${isDark ? '' : ' chat-page--light'}`}>
      <div className="chat-shell">
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
                    onClick={() => submit(suggestion)}
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
          <textarea
            ref={inputRef}
            className="chat-input"
            value={draft}
            rows={1}
            placeholder="Ask about ocean conditions, forecasts or alerts…"
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              // Enter sends, Shift+Enter breaks the line — the convention for
              // a chat box, where multi-line input is the exception.
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                void submit(draft);
              }
            }}
            disabled={pending}
          />
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
        <div className="chat-answer">{message.content}</div>

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
