import { createContext, useContext, useEffect, useState } from 'react';
import {
  ActionBarPrimitive,
  AttachmentPrimitive,
  AuiIf,
  BranchPickerPrimitive,
  ComposerPrimitive,
  MessagePrimitive,
  ThreadPrimitive,
  useAuiState,
} from '@assistant-ui/react';
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import {
  ArrowUp,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Copy,
  ImagePlus,
  Pencil,
  RefreshCw,
  ShieldCheck,
  Square,
  TriangleAlert,
  X,
} from 'lucide-react';
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

/**
 * The assistant's mark — two wave lines, drawn rather than an avatar image.
 * `currentColor` throughout, matching the app's "hand-roll a small inline SVG
 * over a new dependency" convention (Navbar's GithubIcon, ContactPage's
 * LinkedInIcon). It is the one deliberately branded shape on this page; every
 * other surface stays quiet around it.
 */
function AssistantMark() {
  return (
    <svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true" focusable="false">
      <path
        d="M2 9.5c1.5 0 1.5 2 3 2s1.5-2 3-2 1.5 2 3 2 1.5-2 3-2 1.5 2 3 2 1.5-2 3-2 1.5 2 3 2"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M2 14.5c1.5 0 1.5 2 3 2s1.5-2 3-2 1.5 2 3 2 1.5-2 3-2 1.5 2 3 2 1.5-2 3-2 1.5 2 3 2"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity="0.45"
      />
    </svg>
  );
}

/**
 * The Ocean Assistant, on assistant-ui.
 *
 * **What assistant-ui owns:** the thread — message list and ordering, run
 * status, cancellation, the composer state machine, viewport auto-scroll,
 * *and now the message-level affordances its default template ships*: copy,
 * regenerate and edit-and-resubmit, with a branch picker to move between the
 * versions each produces. Those are wired to real behaviour, not decoration —
 * `Reload`/`Edit`/`Copy` are `ActionBarPrimitive` actions against the live
 * runtime, and switching branches replays `useMarisChatRuntime`'s adapter
 * exactly as a fresh turn would.
 *
 * **What stays hand-rolled, deliberately:** everything below the answer text.
 * The grounding verdict, the data calls, the sources and the sidebar are
 * MarisAI concepts with no assistant-ui equivalent, and they are the reason
 * the page exists — an ocean answer you cannot trace is the failure mode the
 * whole backend is built to avoid. They are ported, not reimplemented.
 *
 * Styling is hand-rolled CSS (`pages/chat.css` + `assistant.css`) using the
 * app-wide `--ma-*` tokens, never assistant-ui's own `@assistant-ui/styles`
 * package — that package is deprecated, and its Tailwind-based components
 * would have pulled Tailwind into a second feature area outside
 * `features/dashboard/`. The primitives are headless; every visual choice
 * here, including the ones that now mirror assistant-ui's own default Thread
 * template (bubble-less assistant turns, an avatar mark, a hover action bar,
 * a circular composer send button), is this page's own CSS reading the
 * shared theme tokens, so it inverts for dark/light exactly like every other
 * page rather than carrying a second theming system.
 */
export function AssistantThread({ error }: { error: string | null }) {
  return (
    <ThreadPrimitive.Root className="chat-main">
      <header className="chat-header">
        <h1>
          <span className="chat-header__mark" aria-hidden="true">
            <AssistantMark />
          </span>
          Ocean Assistant
        </h1>
      </header>

      <div className="chat-log-wrap">
        <ThreadPrimitive.Viewport className="chat-log" autoScroll>
          <ThreadPrimitive.Empty>
            <motion.div
              className="chat-empty"
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, ease: EASE }}
            >
              <div className="chat-empty__mark" aria-hidden="true">
                <AssistantMark />
              </div>
              <p className="chat-empty__lead">Ask about conditions anywhere in the ocean.</p>

              {/* The same `<Composer>` the docked position below renders —
                  never both at once (`isEmpty` gates them oppositely), so
                  `layoutId` gives a real shared-element transition: this one
                  physically becomes the docked one the moment the first
                  message lands, rather than one fading while a second one
                  fades in somewhere else. */}
              <Composer variant="centered" />

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

        {/* Floats above the log, only when the reader has scrolled away from
            the latest message — assistant-ui's own visibility logic decides
            that, this just supplies the button. */}
        <ThreadPrimitive.ScrollToBottom className="chat-scroll-btn" aria-label="Scroll to latest message">
          <ChevronDown size={16} aria-hidden />
        </ThreadPrimitive.ScrollToBottom>
      </div>

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

      {/* The centered composer above is unmounted the instant the thread
          stops being empty (the user's own message landing is what flips
          `isEmpty`), so this one is never a second, competing input — it is
          the *only* composer once a conversation exists. */}
      <AuiIf condition={(s) => !s.thread.isEmpty}>
        <Composer variant="docked" />
      </AuiIf>

      <p className="chat-disclaimer">
        Alerts shown here are threshold rules computed over real fields, not issued marine
        warnings.
      </p>
    </ThreadPrimitive.Root>
  );
}

/**
 * `variant` only ever changes *where* this renders, never how it behaves —
 * `AssistantThread` mounts exactly one of the two at a time, gated on
 * `thread.isEmpty`, so this is never rendered twice at once. `layoutId`
 * turns that mount/unmount pair into a single animated element as far as
 * framer-motion is concerned: the centered composer *becomes* the docked
 * one, sliding from the middle of the empty state down to the foot of the
 * page, the same shared-element technique the navbar's active-link
 * underline already uses (see `Navbar.tsx`).
 */
function Composer({ variant }: { variant: 'centered' | 'docked' }) {
  const reduce = useReducedMotion();
  return (
    <ComposerPrimitive.Root asChild>
      <motion.form
        layout={!reduce}
        layoutId={reduce ? undefined : 'chat-composer'}
        className={`chat-composer${variant === 'centered' ? ' chat-composer--centered' : ''}`}
        transition={{ duration: 0.5, ease: EASE }}
      >
        <ComposerAttachments />
        <div className="chat-input-wrap chat-input-wrap--has-attach">
          <ComposerPrimitive.AddAttachment className="chat-attach-btn" aria-label="Attach an image">
            <ImagePlus size={17} aria-hidden />
          </ComposerPrimitive.AddAttachment>

          <ComposerPrimitive.Input
            className="chat-input"
            rows={1}
            autoFocus
            submitOnEnter
            placeholder="Ask about ocean conditions, forecasts or alerts…"
          />

          {/* Send and Stop occupy the same slot — a run can take tens of
              seconds and the composer is where a user looks to stop it.
              `AuiIf` rather than `ComposerPrimitive.If`: the latter only
              filters on `editing`/`dictation` and is deprecated in this
              version, so "is a run in flight" has to come off the thread
              state. */}
          <AuiIf condition={(s) => !s.thread.isRunning}>
            <ComposerPrimitive.Send className="chat-send-btn" aria-label="Send message">
              <ArrowUp size={17} aria-hidden />
            </ComposerPrimitive.Send>
          </AuiIf>
          <AuiIf condition={(s) => s.thread.isRunning}>
            <ComposerPrimitive.Cancel className="chat-send-btn chat-send-btn--stop" aria-label="Stop generating">
              <Square size={12} aria-hidden fill="currentColor" />
            </ComposerPrimitive.Cancel>
          </AuiIf>
        </div>
      </motion.form>
    </ComposerPrimitive.Root>
  );
}

/**
 * Pending image attachments, previewed above the input before the turn is
 * sent. Renders nothing at all (not even an empty wrapper) with zero
 * attachments — gated on the composer's own attachment count rather than on
 * whether children exist, so an empty row never adds spacing above the input.
 */
function ComposerAttachments() {
  const hasAttachments = useAuiState((s) => s.composer.attachments.length > 0);
  if (!hasAttachments) return null;

  return (
    <div className="chat-attachments">
      <ComposerPrimitive.Attachments>
        {({ attachment }) => (
          <AttachmentPrimitive.Root className="chat-attachment">
            <ChatAttachmentThumb file={attachment.file} name={attachment.name} />
            <AttachmentPrimitive.Remove className="chat-attachment-remove" aria-label="Remove image">
              <X size={12} aria-hidden />
            </AttachmentPrimitive.Remove>
          </AttachmentPrimitive.Root>
        )}
      </ComposerPrimitive.Attachments>
    </div>
  );
}

/** An attachment's own thumbnail. `file` is only present on a *pending*
 * attachment (before send); a `CompleteAttachment` (already sent) has none,
 * which never happens here since sending clears the composer immediately —
 * kept as a fallback to the plain name rather than assumed. */
function ChatAttachmentThumb({ file, name }: { file?: File; name: string }) {
  const [url, setUrl] = useState<string | null>(null);

  useEffect(() => {
    if (!file) return;
    const objectUrl = URL.createObjectURL(file);
    setUrl(objectUrl);
    return () => URL.revokeObjectURL(objectUrl);
  }, [file]);

  if (!url) return <span className="chat-attachment-name">{name}</span>;
  return <img className="chat-attachment-thumb" src={url} alt="" />;
}

/** The composer swapped in for a user turn mid-edit — same shape as the
 * thread composer below it, scaled down, so editing reads as "the same
 * control, temporarily relocated" rather than a second UI. */
function EditComposer() {
  return (
    <ComposerPrimitive.Root className="chat-edit-composer">
      <ComposerPrimitive.Input className="chat-edit-input" autoFocus rows={1} submitOnEnter />
      <div className="chat-edit-actions">
        <ComposerPrimitive.Cancel className="chat-edit-btn chat-edit-btn--cancel">
          Cancel
        </ComposerPrimitive.Cancel>
        <ComposerPrimitive.Send className="chat-edit-btn chat-edit-btn--send">
          Save &amp; submit
        </ComposerPrimitive.Send>
      </div>
    </ComposerPrimitive.Root>
  );
}

/** "ocean_analytics" -> "Ocean Analytics", for the specialist label on a tool row. */
function agentLabel(agent: string | null | undefined): string | null {
  if (!agent) return null;
  return agent
    .split('_')
    .map((word) => word[0]?.toUpperCase() + word.slice(1))
    .join(' ');
}

function RunIndicator() {
  const provenance = useContext(ProvenanceContext);
  const running = Object.values(provenance).find((turn) => turn.pending);
  const delegations = running?.delegations ?? [];
  const calls = running?.tools ?? [];

  return (
    <motion.div
      className="chat-turn chat-turn--assistant"
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: EASE }}
    >
      <div className="chat-avatar chat-avatar--pulse" aria-hidden="true">
        <AssistantMark />
      </div>
      <div className="chat-col">
        <div className="chat-thinking">
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

        {/* Why each specialist was asked, in the order the orchestrator decided
            it — arrives before that specialist's own tool calls, since it is
            the reasoning step rather than a result. */}
        <AnimatePresence initial={false}>
          {delegations.map((delegation, index) => (
            <motion.div
              key={`${delegation.agent}-${index}`}
              className="chat-delegation"
              initial={{ opacity: 0, x: -8 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.3, ease: EASE }}
            >
              <span className="chat-delegation__agent">{agentLabel(delegation.agent)}</span>
              <span className="chat-delegation__question">{delegation.question}</span>
            </motion.div>
          ))}
        </AnimatePresence>

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
              {agentLabel(call.agent) ? (
                <span className="chat-livecall__agent">{agentLabel(call.agent)}</span>
              ) : null}
              <code>{call.tool}</code>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </motion.div>
  );
}

/** Copy (and Edit, for a user turn) both flip an icon on completion via the
 * `data-copied`/`data-*` attributes the primitives already set — see the
 * `.chat-action-icon` rule pair in assistant.css — rather than local state. */
function CopyIcon() {
  return (
    <>
      <Copy size={13} className="chat-action-icon chat-action-icon--idle" aria-hidden />
      <Check size={13} className="chat-action-icon chat-action-icon--done" aria-hidden />
    </>
  );
}

function BranchPicker({ label }: { label: string }) {
  return (
    <BranchPickerPrimitive.Root hideWhenSingleBranch className="chat-branch-picker">
      <BranchPickerPrimitive.Previous className="chat-branch-btn" aria-label={`Previous ${label}`}>
        <ChevronLeft size={13} aria-hidden />
      </BranchPickerPrimitive.Previous>
      <span className="chat-branch-count">
        <BranchPickerPrimitive.Number /> / <BranchPickerPrimitive.Count />
      </span>
      <BranchPickerPrimitive.Next className="chat-branch-btn" aria-label={`Next ${label}`}>
        <ChevronRight size={13} aria-hidden />
      </BranchPickerPrimitive.Next>
    </BranchPickerPrimitive.Root>
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
        <div className="chat-col chat-col--user">
          <AuiIf condition={(s) => !s.message.composer.isEditing}>
            <div className="chat-bubble chat-bubble--user">
              <UserMessageAttachments />
              <MessagePrimitive.Parts components={{ Text: PlainText }} />
            </div>
            <div className="chat-msg-controls chat-msg-controls--user">
              <BranchPicker label="version" />
              <ActionBarPrimitive.Root hideWhenRunning autohide="not-last" className="chat-action-bar">
                <ActionBarPrimitive.Copy className="chat-action-btn" aria-label="Copy message">
                  <CopyIcon />
                </ActionBarPrimitive.Copy>
                <ActionBarPrimitive.Edit className="chat-action-btn" aria-label="Edit message">
                  <Pencil size={13} aria-hidden />
                </ActionBarPrimitive.Edit>
              </ActionBarPrimitive.Root>
            </div>
          </AuiIf>
          {/* Swaps the bubble out for the composer while this turn is being
              edited, rather than editing it in place — the composer already
              knows how to grow, focus and submit-on-enter, and a second copy
              of that behaviour here would drift from it. */}
          <AuiIf condition={(s) => s.message.composer.isEditing}>
            <EditComposer />
          </AuiIf>
        </div>
      </motion.div>
    </MessagePrimitive.Root>
  );
}

/** The image(s) a user turn was sent with, shown as small thumbnails above its
 * text — mirrors `ComposerAttachments`' preview, but reads the *sent* form
 * (`CompleteAttachment.content`, a data: URL) rather than a `File`, since a
 * historical message never has the original `File` object to hand. Renders
 * nothing for a text-only turn, or for a past turn resumed from a stored
 * session — the backend does not persist the image bytes (see
 * `agent._question_message`'s docstring), so a reloaded conversation shows
 * the question text only, honestly reflecting what was actually kept. */
function UserMessageAttachments() {
  return (
    <MessagePrimitive.Attachments>
      {({ attachment }) => {
        const part = attachment.content?.find((candidate) => candidate.type === 'image');
        if (!part || part.type !== 'image') return null;
        return (
          <div className="chat-attachments chat-attachments--sent">
            <img className="chat-attachment-thumb chat-attachment-thumb--sent" src={part.image} alt="" />
          </div>
        );
      }}
    </MessagePrimitive.Attachments>
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
        <div className="chat-avatar" aria-hidden="true">
          <AssistantMark />
        </div>
        {/* `layout` lets the column grow smoothly as tokens arrive instead of
            snapping taller line by line. */}
        <motion.div layout={!reduce} className="chat-col">
          <div className="chat-answer">
            <MessagePrimitive.Parts components={{ Text: MarkdownText }} />
          </div>
          <Provenance provenance={provenance} />
          {/* Gated on `pending` for the same reason Provenance is: while this
              branch is still streaming, `BranchPickerPrimitive` (unlike
              `ActionBarPrimitive.Root`'s own `hideWhenRunning`) has no
              running-state gate of its own, so a regenerate would otherwise
              show "2 / 2" beside an answer that has not arrived yet. */}
          {!provenance?.pending ? (
            <div className="chat-msg-controls">
              <ActionBarPrimitive.Root hideWhenRunning autohide="not-last" className="chat-action-bar">
                <ActionBarPrimitive.Copy className="chat-action-btn" aria-label="Copy answer">
                  <CopyIcon />
                </ActionBarPrimitive.Copy>
                <ActionBarPrimitive.Reload className="chat-action-btn" aria-label="Regenerate answer">
                  <RefreshCw size={13} aria-hidden />
                </ActionBarPrimitive.Reload>
              </ActionBarPrimitive.Root>
              <BranchPicker label="answer" />
            </div>
          ) : null}
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
        ) : meta.possible_false_refusal ? (
          <motion.p
            className="chat-flag"
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, ease: EASE }}
          >
            <TriangleAlert size={14} aria-hidden />
            <span>
              This reads like a refusal, but the assistant did retrieve data this turn — it
              may be worth asking again.
            </span>
          </motion.p>
        ) : meta.glossary_gaps.length > 0 ? (
          <motion.p
            className="chat-flag"
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, ease: EASE }}
          >
            <TriangleAlert size={14} aria-hidden />
            <span>
              {meta.glossary_gaps.length === 1
                ? `This answer may not have kept "${meta.glossary_gaps[0]}" in English — worth double-checking that part.`
                : `This answer may not have kept these terms in English: ${meta.glossary_gaps.join(', ')} — worth double-checking those parts.`}
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

      {/* The orchestrator's reasoning trace, always visible rather than
          folded into the collapsed data-call list below — it is *why* a
          specialist was asked, not one of the results it produced, and PS2
          asks for that reasoning to be demonstrable on its own. */}
      {meta.delegations.length > 0 ? (
        <ul className="chat-delegations">
          {meta.delegations.map((delegation, index) => (
            <li key={index} className="chat-delegation">
              <span className="chat-delegation__agent">{agentLabel(delegation.agent)}</span>
              <span className="chat-delegation__question">{delegation.question}</span>
            </li>
          ))}
        </ul>
      ) : null}

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
  const agent = agentLabel(observation.agent);
  return (
    <li className="chat-call">
      {agent ? <span className="chat-call__agent">{agent}</span> : null}
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
