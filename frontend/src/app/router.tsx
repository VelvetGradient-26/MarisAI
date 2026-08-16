import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { ComponentPropsWithRef, MouseEvent, ReactNode } from 'react';
import { rafThrottle } from '../utils/rafThrottle';
import { RouterContext, useAppRouter } from './routerContext';

/**
 * Scroll positions, keyed by history entry rather than by URL.
 *
 * By entry, because the same URL can legitimately sit at several points in the
 * back stack at different depths — /docs is one route whose chapter lives in
 * the query string, and the metric pages are long enough that returning to the
 * wrong offset is the difference between "went back" and "lost my place".
 * Previously `navigate` scrolled to top unconditionally and `popstate` did
 * nothing, so Back always landed at the top of the previous page.
 *
 * Module-level rather than in a ref: it must survive AppRouter remounting. It
 * is deliberately not persisted — a fresh tab has no back stack to restore.
 */
const scrollPositions = new Map<string, number>();

/** Our own entry id, namespaced so it cannot collide with anything else that
 *  writes history state. */
interface EntryState {
  marisKey?: string;
}

function readEntryKey(): string {
  const state = window.history.state as EntryState | null;
  return state?.marisKey ?? 'entry-0';
}

let keyCounter = 0;
const nextEntryKey = () => `entry-${(keyCounter += 1)}`;

function readLocation() {
  return {
    pathname: window.location.pathname,
    search: window.location.search,
  };
}

export function AppRouter({ children }: { children: ReactNode }) {
  const [location, setLocation] = useState(readLocation);
  const entryKeyRef = useRef(readEntryKey());
  /**
   * Where the next commit should scroll to: `null` means "top" (a forward
   * navigation), a number means "restore this offset" (Back/Forward).
   */
  const restoreToRef = useRef<number | null>(null);

  // The browser's own restoration guesses against heights this SPA has not
  // rendered yet, and then fights the restore below. We do it ourselves.
  useEffect(() => {
    if (!('scrollRestoration' in window.history)) return;
    const previous = window.history.scrollRestoration;
    window.history.scrollRestoration = 'manual';
    return () => {
      window.history.scrollRestoration = previous;
    };
  }, []);

  // Record where the current entry is scrolled to as it happens: by the time
  // `popstate` fires the browser has already moved off that entry, so there is
  // no "about to leave" moment to save on.
  useEffect(() => {
    const record = rafThrottle(() => {
      scrollPositions.set(entryKeyRef.current, window.scrollY);
    });
    window.addEventListener('scroll', record, { passive: true });
    return () => window.removeEventListener('scroll', record);
  }, []);

  useEffect(() => {
    const handlePopState = () => {
      const key = readEntryKey();
      entryKeyRef.current = key;
      restoreToRef.current = scrollPositions.get(key) ?? 0;
      setLocation(readLocation());
    };
    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, []);

  // Runs after every route commit. A layout effect so a forward navigation is
  // already at the top on first paint rather than visibly jumping there.
  useLayoutEffect(() => {
    const target = restoreToRef.current;
    restoreToRef.current = null;

    if (target === null || target === 0) {
      window.scrollTo({ top: 0, behavior: 'auto' });
      return;
    }

    // The destination is usually a lazy chunk behind Suspense, so right now the
    // document can still be one viewport tall and `scrollTo` silently clamps to
    // 0. Retry across a few frames until the page is tall enough to hold the
    // offset, then stop rather than fighting a page that genuinely got shorter.
    let frame = 0;
    let attempts = 0;
    const settle = () => {
      window.scrollTo({ top: target, behavior: 'auto' });
      attempts += 1;
      if (Math.abs(window.scrollY - target) > 2 && attempts < 12) {
        frame = requestAnimationFrame(settle);
      }
    };
    settle();
    return () => cancelAnimationFrame(frame);
  }, [location]);

  const navigate = (to: string, options?: { replace?: boolean }) => {
    const url = new URL(to, window.location.origin);
    const next = `${url.pathname}${url.search}${url.hash}`;

    // Save the outgoing offset now: the scroll listener is throttled to a
    // frame, so the last movement before a click may not have been recorded.
    scrollPositions.set(entryKeyRef.current, window.scrollY);

    if (options?.replace) {
      // A replace re-points the *current* entry, so it keeps that entry's key
      // and its offset: replace canonicalises a URL, it does not move the user.
      window.history.replaceState({ marisKey: entryKeyRef.current }, '', next);
      restoreToRef.current = window.scrollY;
    } else {
      const key = nextEntryKey();
      entryKeyRef.current = key;
      window.history.pushState({ marisKey: key }, '', next);
      restoreToRef.current = null;
    }

    setLocation(readLocation());
  };

  return (
    <RouterContext.Provider
      value={{
        pathname: location.pathname,
        searchParams: new URLSearchParams(location.search),
        navigate,
      }}
    >
      {children}
    </RouterContext.Provider>
  );
}

export function Link({
  to,
  onClick,
  ...props
  // `ComponentPropsWithRef` rather than `AnchorHTMLAttributes` so a caller can
  // hand this a ref and have it land on the underlying `<a>`. In React 19 a
  // function component receives `ref` as an ordinary prop, so the existing
  // spread already forwards it — only the type was in the way. `useMagnetic`
  // is the first caller that needs it.
}: Omit<ComponentPropsWithRef<'a'>, 'href'> & { to: string }) {
  const { navigate } = useAppRouter();

  const handleClick = (event: MouseEvent<HTMLAnchorElement>) => {
    onClick?.(event);
    if (
      event.defaultPrevented ||
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey ||
      (props.target && props.target !== '_self')
    ) {
      return;
    }

    event.preventDefault();
    navigate(to);
  };

  return <a {...props} href={to} onClick={handleClick} />;
}
