import { useEffect, useRef, useState } from 'react';
import { rafThrottle } from '../../utils/rafThrottle';

/**
 * Scroll-driven entrance and parallax primitives for the landing page.
 *
 * **Geometry is measured directly; `IntersectionObserver` is only an extra
 * trigger.** This is not belt-and-braces for its own sake — `AnalyticsGrid`
 * hit exactly this in production: the observer was constructed and observing
 * but never fired a callback at all, leaving every chart unmounted. A landing
 * page whose sections never reveal is a blank page, so the same defence
 * applies here (see CLAUDE.md, "Do not rely on IntersectionObserver alone").
 *
 * Everything here respects `prefers-reduced-motion`: reduced motion resolves
 * to "already revealed, no parallax" rather than to a degraded animation.
 */

function prefersReducedMotion(): boolean {
  return (
    typeof window !== 'undefined' &&
    window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true
  );
}

/**
 * Re-exported, not reimplemented. `useReveal` now lives in `hooks/useReveal.ts`
 * so pages other than this one can use it; keeping the name importable from
 * here means the landing page's own imports are unchanged and there is still
 * exactly one implementation.
 */
export { useReveal } from '../../hooks/useReveal';

/**
 * Normalised scroll progress across an element, from -1 (fully below the
 * viewport) through 0 (centred) to 1 (fully above). Drives parallax without
 * any element needing to know the page's total height.
 */
export function useScrollProgress<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [progress, setProgress] = useState(0);
  const reduced = prefersReducedMotion();

  useEffect(() => {
    if (reduced) return;
    const element = ref.current;
    if (!element) return;

    const update = rafThrottle(() => {
      const rect = element.getBoundingClientRect();
      const viewport = window.innerHeight || 800;
      const centre = rect.top + rect.height / 2;
      const offset = (viewport / 2 - centre) / (viewport / 2 + rect.height / 2);
      setProgress(Math.max(-1, Math.min(1, offset)));
    });

    window.addEventListener('scroll', update, { passive: true });
    window.addEventListener('resize', update, { passive: true });
    update();
    return () => {
      window.removeEventListener('scroll', update);
      window.removeEventListener('resize', update);
    };
  }, [reduced]);

  return { ref, progress: reduced ? 0 : progress };
}

/**
 * Counts from 0 to `value` once revealed.
 *
 * Uses an eased elapsed-time ramp rather than a fixed per-frame increment, so
 * the duration is the same on a 60 Hz and a 120 Hz display. Reduced motion
 * returns the final value immediately.
 */
export function useCountUp(value: number, active: boolean, duration = 1100) {
  const [current, setCurrent] = useState(() => (prefersReducedMotion() ? value : 0));

  useEffect(() => {
    if (!active || prefersReducedMotion()) {
      setCurrent(value);
      return;
    }
    let frame = 0;
    const started = performance.now();

    const tick = (now: number) => {
      const t = Math.min((now - started) / duration, 1);
      // easeOutExpo — fast start, long settle, which reads as "counting up
      // and landing" rather than a linear ticker.
      const eased = t === 1 ? 1 : 1 - 2 ** (-10 * t);
      setCurrent(value * eased);
      if (t < 1) frame = requestAnimationFrame(tick);
    };

    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [value, active, duration]);

  return current;
}
