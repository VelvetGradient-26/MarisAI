import { useCallback, useEffect, useState } from 'react';
import { AssistantRuntimeProvider, fromThreadMessageLike } from '@assistant-ui/react';
import { AnimatePresence, motion } from 'framer-motion';
import { MessageSquarePlus, PanelLeftClose, PanelLeftOpen, Trash2 } from 'lucide-react';
import { deleteSession, listSessions, loadSession } from '../map/api/chat';
import type { ChatSessionSummary } from '../map/api/chat';
import { useThemeStore } from '../../store/themeStore';
import { AssistantThread, ProvenanceProvider } from './AssistantThread';
import { useMarisChatRuntime } from './runtime';
import type { TurnProvenance } from './runtime';
import '../../pages/chat.css';
import './assistant.css';

const EASE = [0.22, 0.61, 0.36, 1] as const;

/** Per-viewer convenience only (which side of the rail toggle they left it
 * on) — a `localStorage` read/write, not a Zustand store: the preference is
 * scoped to this one page, not the cross-page kind `store/themeStore.ts`'s
 * pattern exists for. */
const SIDEBAR_COLLAPSED_KEY = 'marisai-assistant-sidebar-collapsed';

function readSidebarCollapsed(): boolean {
  try {
    return localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === '1';
  } catch {
    return false;
  }
}

/**
 * The Ocean Assistant, on assistant-ui.
 *
 * **What assistant-ui owns:** the thread — message list and ordering, run
 * status, cancellation, the composer state machine, viewport auto-scroll.
 * That machinery was ~200 hand-rolled lines here before (scroll pinning, a
 * textarea that resizes itself, a `pending` flag threaded through five
 * handlers) and none of it was this page's actual subject.
 *
 * **What stays hand-rolled, deliberately:** everything below the answer text.
 * The grounding verdict, the data calls, the sources and this sidebar are
 * MarisAI concepts with no assistant-ui equivalent, and they are the reason
 * the page exists — an ocean answer you cannot trace is the failure mode the
 * whole backend is built to avoid. They are ported, not reimplemented.
 *
 * **Styling now mirrors assistant-ui's own default Thread template** —
 * bubble-less assistant turns with an avatar mark, a hover action bar
 * (copy/reload/edit) wired to real branch-switching behaviour, a
 * scroll-to-bottom button — while staying `pages/chat.css` +
 * `assistant.css`, on the app's `--ma-*` tokens, rather than adopting
 * `@assistant-ui/styles`. That package is deprecated and Tailwind-based;
 * pulling it in would confine Tailwind to `features/dashboard/` no longer.
 * The primitives are headless, so every visual choice — including the ones
 * that now match the template's own look — is this page's own CSS, which is
 * what makes it invert for dark/light like every other page instead of
 * carrying a second theming system. See AssistantThread.tsx for the detail.
 */
export function AssistantPage() {
  const isDark = useThemeStore((s) => s.dark);
  const { runtime, provenance, error, setError, sessionRef, resetProvenance } =
    useMarisChatRuntime();

  const [sessions, setSessions] = useState<ChatSessionSummary[]>([]);
  const [persistence, setPersistence] = useState(true);
  const [activeSession, setActiveSession] = useState<string | null>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(readSidebarCollapsed);

  useEffect(() => {
    try {
      localStorage.setItem(SIDEBAR_COLLAPSED_KEY, sidebarCollapsed ? '1' : '0');
    } catch {
      /* Private browsing, or storage disabled — the toggle still works for
         this visit, it just will not be remembered for the next one. */
    }
  }, [sidebarCollapsed]);

  /**
   * The sidebar's three honest answers, kept apart — carried over verbatim
   * from the page this replaces, because the reasoning is unchanged.
   *
   * With only `sessions: []` to go on, the sidebar rendered "Your
   * conversations will appear here" from the first paint — before the listing
   * request had been sent, and again if it failed. Both are the page stating
   * as fact that you have no previous chats when it does not yet know, which
   * is the same failure the dashboard's `unavailable_reason` contract exists
   * to prevent. "Loading" and "could not load" are different answers from
   * "none", and only one of the three is ever true at a time.
   */
  const [sessionsStatus, setSessionsStatus] = useState<'loading' | 'ready' | 'error'>('loading');

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
      // either.
      setSessionsStatus('error');
    }
  }, []);

  useEffect(() => {
    void refreshSessions();
  }, [refreshSessions]);

  // The thread is assistant-ui's, so switching conversations means replacing
  // its contents rather than swapping a local array.
  const startNew = useCallback(() => {
    runtime.threads.main.import({ messages: [] });
    sessionRef.current = null;
    setActiveSession(null);
    resetProvenance();
    setError(null);
  }, [runtime, sessionRef, resetProvenance, setError]);

  const open = useCallback(
    async (id: string) => {
      if (id === activeSession) return;
      setError(null);
      try {
        const stored = await loadSession(id);
        // `fromThreadMessageLike` rather than hand-building a `ThreadMessage`:
        // that type is a discriminated union whose assistant branch requires a
        // full metadata record, and constructing it by hand both fails to
        // narrow and would have to be corrected every time the shape moves.
        runtime.threads.main.import({
          messages: stored.map((message, index) => ({
            message: fromThreadMessageLike(
              {
                role: message.role === 'user' ? 'user' : 'assistant',
                content: [{ type: 'text', text: message.content }],
              },
              `${id}-${index}`,
              { type: 'complete', reason: 'stop' }
            ),
            parentId: null,
          })),
        });
        sessionRef.current = id;
        setActiveSession(id);
        resetProvenance();
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Could not open that chat.');
      }
    },
    [activeSession, runtime, sessionRef, resetProvenance, setError]
  );

  const remove = useCallback(
    async (id: string) => {
      try {
        await deleteSession(id);
        if (id === activeSession) startNew();
        void refreshSessions();
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Could not delete that chat.');
      }
    },
    [activeSession, startNew, refreshSessions, setError]
  );

  // A finished turn may have created a session server-side; pick it up so the
  // sidebar lists it without the user reloading.
  useEffect(() => {
    const finished = Object.values(provenance as Record<string, TurnProvenance>).some(
      (turn) => !turn.pending
    );
    if (!finished) return;
    if (sessionRef.current && sessionRef.current !== activeSession) {
      setActiveSession(sessionRef.current);
    }
    void refreshSessions();
  }, [provenance, activeSession, refreshSessions, sessionRef]);

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <ProvenanceProvider value={provenance}>
        <div className={`chat-page${isDark ? '' : ' chat-page--light'}`}>
          <div className={`chat-shell${sidebarCollapsed ? ' chat-shell--sidebar-collapsed' : ''}`}>
            <aside className={`chat-sidebar${sidebarCollapsed ? ' chat-sidebar--collapsed' : ''}`}>
              <div className="chat-sidebar__top">
                <button
                  type="button"
                  className="chat-sidebar__toggle"
                  onClick={() => setSidebarCollapsed((value) => !value)}
                  aria-label={sidebarCollapsed ? 'Show chat history' : 'Hide chat history'}
                  aria-expanded={!sidebarCollapsed}
                >
                  {sidebarCollapsed ? (
                    <PanelLeftOpen size={18} aria-hidden />
                  ) : (
                    <PanelLeftClose size={18} aria-hidden />
                  )}
                </button>
              </div>

              <button
                type="button"
                className="chat-new"
                onClick={startNew}
                aria-label="New chat"
                title="New chat"
              >
                <MessageSquarePlus size={16} aria-hidden />
                {sidebarCollapsed ? null : <span>New chat</span>}
              </button>

              <AnimatePresence initial={false}>
                {sidebarCollapsed ? null : (
                  <motion.div
                    key="sidebar-history"
                    className="chat-sidebar__history"
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    transition={{ duration: 0.15, ease: EASE }}
                  >
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
                            <span
                              className="ma-skeleton ma-skeleton--sub"
                              style={{ width: `${8 - row}rem` }}
                            />
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
                        <AnimatePresence initial={false}>
                          {sessions.map((entry) => (
                            /* Two sibling buttons, not a button inside a button —
                               nesting interactive content in a <button> is invalid
                               HTML, and is why the delete previously needed a
                               hand-rolled role/tabIndex/onKeyDown. */
                            <motion.li
                              key={entry.id}
                              className="chat-session-row"
                              layout
                              initial={{ opacity: 0, x: -10 }}
                              animate={{ opacity: 1, x: 0 }}
                              exit={{ opacity: 0, x: -10, height: 0 }}
                              transition={{ duration: 0.28, ease: EASE }}
                            >
                              <button
                                type="button"
                                className={`chat-session${entry.id === activeSession ? ' is-active' : ''}`}
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
                            </motion.li>
                          ))}
                        </AnimatePresence>
                      </ul>
                    )}
                  </motion.div>
                )}
              </AnimatePresence>
            </aside>

            <AssistantThread error={error} />
          </div>
        </div>
      </ProvenanceProvider>
    </AssistantRuntimeProvider>
  );
}
