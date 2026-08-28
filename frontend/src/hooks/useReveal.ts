import { useEffect, useRef, useState } from 'react';
import { rafThrottle } from '../utils/rafThrottle';

/**
 * Reveal an element once it scrolls into view. App-wide.
 *
 * Promoted out of `pages/landing/useScrollReveal.ts`, which is where it was
 * written and where it stayed for four files while every other page had no
 * entrance at all. The landing hooks re-export from here rather than keeping a
 * copy — two implementations of this would drift, and the two properties below
 * are the ones that would quietly stop being true in the copy.
 *
 * **Geometry is measured directly; `IntersectionObserver` is only an extra
 * trigger.** Not belt-and-braces for its own sake: `AnalyticsGrid` hit exactly
 * this in production, where the observer was constructed and observing but
 * never fired a callback at all, leaving every chart unmounted. A page whose
 * sections never reveal is a blank page, which is a far worse failure than no
 * animation.
 *
 * **A reveal never flips back.** An entrance that replays every time you scroll
 * past is a distraction rather than a flourish.
 *
 * **Reduced motion resolves to "already revealed"**, not to a faster animation.
 * The content is the point; the movement is not.
 */

function prefersReducedMotion(): boolean {
  return (
    typeof window !== 'undefined' &&
    window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true
  );
}

export function useReveal<T extends HTMLElement>(rootMargin = 0.15) {
  const ref = useRef<T>(null);
  const [revealed, setRevealed] = useState(() => prefersReducedMotion());

  useEffect(() => {
    if (revealed) return;
    const element = ref.current;
    if (!element) return;

    let cancelled = false;
    const check = () => {
      if (cancelled) return;
      const rect = element.getBoundingClientRect();
      const viewport = window.innerHeight || 800;
      // Reveal once the element's top edge has risen above the trigger line.
      // A zero-height element (not laid out yet) is deliberately not counted.
      if (rect.height > 0 && rect.top < viewport * (1 - rootMargin)) {
        cancelled = true;
        setRevealed(true);
      }
    };

    const onScroll = rafThrottle(check);
    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('resize', onScroll, { passive: true });

    // Measure now, and again after layout settles — fonts and images shift
    // geometry after first paint, and a section already on screen at load must
    // not wait for a scroll that may never come.
    check();
    const settle = window.setTimeout(check, 120);

    let observer: IntersectionObserver | undefined;
    if ('IntersectionObserver' in window) {
      observer = new IntersectionObserver(
        (entries) => entries.some((entry) => entry.isIntersecting) && check(),
        { rootMargin: `0px 0px -${Math.round(rootMargin * 100)}% 0px` }
      );
      observer.observe(element);
    }

    return () => {
      cancelled = true;
      window.clearTimeout(settle);
      window.removeEventListener('scroll', onScroll);
      window.removeEventListener('resize', onScroll);
      observer?.disconnect();
    };
  }, [revealed, rootMargin]);

  return { ref, revealed };
}
