import { createContext, useContext, useState } from 'react';
import {
  AuiIf,
  ComposerPrimitive,
  MessagePrimitive,
  ThreadPrimitive,
  useAuiState,
} from '@assistant-ui/react';
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import { ChevronDown, CornerDownLeft, ShieldCheck, TriangleAlert } from 'lucide-react';
import { Markdown } from '../../components/Markdown';
import ShinyText from '../../components/reactbits/ShinyText/ShinyText';
import type { ChatObservation } from '../map/api/chat';
import type { TurnProvenance } from './runtime';

const ProvenanceContext = createContext<Record<string, TurnProvenance>>({});
export const ProvenanceProvider = ProvenanceContext.Provider;

/** Provenance for the message currently in scope, if any is known yet. */
function useTurnProvenance(): TurnProvenance | undefined {
  const all = useContext(ProvenanceContext);
  const id = useAuiState((s) => s.message.id);
  return all[id];
}

const SUGGESTIONS = [
  'What are the current conditions at 10°N, 72°E?',
  'Forecast sea surface temperature there 7 days out',
  'How is the global ocean doing right now?',
  'Are there any active alerts?',
];

/* Motion is defined once and shared, so every surface on this page eases the
   same way. `useReducedMotion` collapses the distance rather than the opacity —
   a message that fades in without moving still reads as arriving, whereas one
   that neither moves nor fades just appears. */
const EASE = [0.22, 0.61, 0.36, 1] as const;

export function AssistantThread({ error }: { error: string | null }) {
  return (
    <ThreadPrimitive.Root className="chat-main">
      <header className="chat-header">
        <h1>Ocean Assistant</h1>
        <p>
          Answers come from live MarisAI data — forecasts, observations, bathymetry and model
          output. Every figure is traced back to the call that produced it.
        </p>
      </header>

      <ThreadPrimitive.Viewport className="chat-log" autoScroll>
        <ThreadPrimitive.Empty>
          <motion.div
            className="chat-empty"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, ease: EASE }}
          >
            <p className="chat-empty__lead">Ask about conditions anywhere in the ocean.</p>
            <div className="chat-suggestions">
              {SUGGESTIONS.map((suggestion, index) => (
                <motion.div
                  key={suggestion}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.45, delay: 0.06 * index, ease: EASE }}
                >
                  <ThreadPrimitive.Suggestion
                    className="chat-suggestion"
                    prompt={suggestion}
                    method="replace"
                    autoSend
                  >
                    {suggestion}
                  </ThreadPrimitive.Suggestion>
                </motion.div>
              ))}
            </div>
          </motion.div>
        </ThreadPrimitive.Empty>

        <ThreadPrimitive.Messages
          components={{ UserMessage, AssistantMessage }}
        />

        {/* Only while a run is in flight *and* nothing has streamed yet — once
            tokens arrive the answer itself is the progress indicator, and
            leaving this below it would claim the turn had not started. */}
        <ThreadPrimitive.If running>
          <RunIndicator />
        </ThreadPrimitive.If>
      </ThreadPrimitive.Viewport>

      <AnimatePresence>
        {error ? (
          <motion.p
            className="chat-error"
            role="alert"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            transition={{ duration: 0.3, ease: EASE }}
          >
            <TriangleAlert size={15} aria-hidden />
            {error}
          </motion.p>
        ) : null}
      </AnimatePresence>

      <Composer />

      <p className="chat-disclaimer">
        Alerts shown here are threshold rules computed over real fields, not issued marine
        warnings.
      </p>
    </ThreadPrimitive.Root>
  );
}

function Composer() {
  return (
    <ComposerPrimitive.Root className="chat-composer">
      <div className="chat-input-wrap">
        <ComposerPrimitive.Input
          className="chat-input"
          rows={1}
          autoFocus
          submitOnEnter
          placeholder="Ask about ocean conditions, forecasts or alerts…"
        />
      </div>

      {/* Send and Cancel occupy the same slot — a run can take tens of seconds
          and the composer is where a user looks to stop it.

          `AuiIf` rather than `ComposerPrimitive.If`: the latter only filters on
          `editing`/`dictation` and is deprecated in this version, so "is a run
          in flight" has to come off the thread state. */}
      <AuiIf condition={(s) => !s.thread.isRunning}>
        <ComposerPrimitive.Send className="chat-send">
          <CornerDownLeft size={16} aria-hidden />
          <span>Send</span>
        </ComposerPrimitive.Send>
      </AuiIf>
      <AuiIf condition={(s) => s.thread.isRunning}>
        <ComposerPrimitive.Cancel className="chat-send chat-send--cancel">
          <span>Stop</span>
        </ComposerPrimitive.Cancel>
      </AuiIf>
    </ComposerPrimitive.Root>
  );
}

function RunIndicator() {
  const provenance = useContext(ProvenanceContext);
  const running = Object.values(provenance).find((turn) => turn.pending);
  const calls = running?.tools ?? [];

  return (
    <motion.div
      className="chat-turn chat-turn--assistant"
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: EASE }}
    >
      <div className="chat-bubble chat-bubble--assistant chat-thinking">
        <span className="chat-dot" />
        <span className="chat-dot" />
        <span className="chat-dot" />
        <span className="chat-thinking__label">
          <ShinyText
            text={calls.length > 0 ? 'Reading ocean data…' : 'Querying ocean data…'}
            speed={2.4}
            color="var(--chat-muted, #9a9aa2)"
            shineColor="var(--chat-accent, #4fd1ff)"
          />
        </span>
      </div>

      {/* The tool calls as they land. This is the substance of the wait: a
          named data call is more reassuring than a spinner, and it is true. */}
      <AnimatePresence initial={false}>
        {calls.map((call, index) => (
          <motion.div
            key={`${call.tool}-${index}`}
            className="chat-livecall"
            initial={{ opacity: 0, x: -8 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.3, ease: EASE }}
          >
            <span className="chat-livecall__tick" aria-hidden />
            <code>{call.tool}</code>
          </motion.div>
        ))}
      </AnimatePresence>
    </motion.div>
  );
}

function UserMessage() {
  const reduce = useReducedMotion();
  return (
    <MessagePrimitive.Root asChild>
      <motion.div
        className="chat-turn chat-turn--user"
        initial={{ opacity: 0, y: reduce ? 0 : 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35, ease: EASE }}
      >
        <div className="chat-bubble chat-bubble--user">
          <MessagePrimitive.Parts components={{ Text: PlainText }} />
        </div>
      </motion.div>
    </MessagePrimitive.Root>
  );
}

function AssistantMessage() {
  const reduce = useReducedMotion();
  const provenance = useTurnProvenance();

  return (
    <MessagePrimitive.Root asChild>
      <motion.div
        className="chat-turn chat-turn--assistant"
        initial={{ opacity: 0, y: reduce ? 0 : 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35, ease: EASE }}
      >
        {/* `layout` lets the bubble grow smoothly as tokens arrive instead of
            snapping taller line by line. */}
        <motion.div layout={!reduce} className="chat-bubble chat-bubble--assistant">
          <div className="chat-answer">
            <MessagePrimitive.Parts components={{ Text: MarkdownText }} />
          </div>
          <Provenance provenance={provenance} />
        </motion.div>
      </motion.div>
    </MessagePrimitive.Root>
  );
}

function PlainText({ text }: { text: string }) {
  return <>{text}</>;
}

function MarkdownText({ text }: { text: string }) {
  return <Markdown text={text} />;
}

/**
 * The grounding verdict, the data calls behind it, and the sources.
 *
 * Nothing here renders while `pending`. That is the rule the backend's
 * streaming contract forces: `grounded` is computed from the finished text and
 * only arrives on the terminal `meta` event, so any badge shown earlier would
 * be asserting a check that has not run.
 */
function Provenance({ provenance }: { provenance: TurnProvenance | undefined }) {
  const [open, setOpen] = useState(false);
  const reduce = useReducedMotion();

  if (!provenance || provenance.pending || !provenance.meta) return null;
  const { meta } = provenance;

  return (
    <>
      <AnimatePresence>
        {!meta.grounded ? (
          <motion.p
            className="chat-flag"
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, ease: EASE }}
          >
            <TriangleAlert size={14} aria-hidden />
            <span>
              {meta.unsupported_numbers.length === 1
                ? `The figure ${meta.unsupported_numbers[0]} could not be traced to a data source.`
                : `These figures could not be traced to a data source: ${meta.unsupported_numbers.join(', ')}.`}
            </span>
          </motion.p>
        ) : meta.observations.length > 0 ? (
          <motion.p
            className="chat-traced"
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, delay: 0.1, ease: EASE }}
          >
            <ShieldCheck size={14} aria-hidden />
            <span>Every figure traced to a data call.</span>
          </motion.p>
        ) : null}
      </AnimatePresence>

      {meta.observations.length > 0 ? (
        <div className="chat-provenance">
          <button
            type="button"
            className={`chat-provenance__toggle${open ? ' is-open' : ''}`}
            onClick={() => setOpen((value) => !value)}
            aria-expanded={open}
          >
            <motion.span
              animate={{ rotate: open ? 0 : -90 }}
              transition={{ duration: 0.2, ease: EASE }}
              style={{ display: 'inline-flex' }}
            >
              <ChevronDown size={14} aria-hidden />
            </motion.span>
            {meta.observations.length === 1
              ? '1 data call'
              : `${meta.observations.length} data calls`}
          </button>

          <AnimatePresence initial={false}>
            {open ? (
              <motion.ul
                className="chat-calls"
                initial={reduce ? false : { height: 0, opacity: 0 }}
                animate={{ height: 'auto', opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                transition={{ duration: 0.28, ease: EASE }}
                style={{ overflow: 'hidden' }}
              >
                {meta.observations.map((observation, index) => (
                  <ObservationRow key={index} observation={observation} />
                ))}
              </motion.ul>
            ) : null}
          </AnimatePresence>
        </div>
      ) : null}

      {meta.sources.length > 0 ? (
        <p className="chat-sources">{meta.sources.join(' · ')}</p>
      ) : null}
    </>
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
