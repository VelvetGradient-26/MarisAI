import { useEffect } from 'react';
import Lenis from 'lenis';
// Lenis's own stylesheet, and it is not optional. The rule that matters here
// is `html.lenis, html.lenis body { height: auto }`, which relaxes this app's
// global `html, body, #root { height: 100% }`. That 100% exists for the
// full-bleed map, and relaxing it on a scrolling page is correct — but it is
// also exactly why this component must stay off the map route, where the
// height is load-bearing rather than incidental.
import 'lenis/dist/lenis.css';

/**
 * App-wide smooth scrolling, via Lenis.
 *
 * This is the one new dependency in this pass, and it earns its place because
 * it is the single largest change to how the whole product *feels* per line of
 * code: every scroll-driven thing already built here — the landing reveals, the
 * hero parallax, the scroll rail, the docs — reads as considered rather than as
 * a browser default, and none of them had to change to get it.
 *
 * Four things make this safe to run app-wide rather than only on the landing
 * page, and each one is a constraint rather than a preference:
 *
 * - **Lenis drives the real scroll position.** It is not a transformed
 *   container; `window.scrollY` remains true, so `useReveal`,
 *   `useScrollProgress`, `AnalyticsGrid`'s geometry measuring and framer's
 *   `useScroll` all keep working with no adapter. A transform-based smooth
 *   scroller would have silently broken every one of them, and the lazy-mount
 *   one is the failure that leaves a page blank.
 *
 * - **It is disabled on `/map`.** Wheel events there are the map's zoom, and
 *   MapLibre reads them itself. Smoothing a page that does not scroll would at
 *   best do nothing and at worst fight the camera for the gesture.
 *
 * - **It is disabled under reduced motion.** Easing a scroll is motion the user
 *   did not ask for and cannot opt out of by scrolling differently. Unlike an
 *   entrance animation there is no reduced version worth keeping — the honest
 *   degradation is the native scroll.
 *
 * - **It yields to any scroll container that is not the document.** The
 *   dashboard, the assistant thread and the docs sidebar all scroll internally;
 *   `prevent` returns true for anything inside an element marked
 *   `data-lenis-prevent`, which is Lenis's own opt-out and is applied where
 *   those components already manage their own overflow.
 *
 * `duration` and the easing are deliberately conservative. The default Lenis
 * feel (1.2s, a long tail) is recognisable as "a Lenis site", which is the
 * opposite of what a distinctive design wants; 0.9s with a standard expo-out
 * settles firmly enough that a short flick still feels like a flick.
 */
export function SmoothScroll({ enabled }: { enabled: boolean }) {
  useEffect(() => {
    if (!enabled) return;
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return;

    const lenis = new Lenis({
      duration: 0.9,
      easing: (t: number) => (t === 1 ? 1 : 1 - 2 ** (-10 * t)),
      // Touch devices already have momentum scrolling implemented by the OS,
      // and it is better than any JS reimplementation of it. Smoothing on top
      // of it produces a double-eased scroll that feels slippery.
      smoothWheel: true,
      syncTouch: false,
    });

    let frame = 0;
    const raf = (time: number) => {
      lenis.raf(time);
      frame = requestAnimationFrame(raf);
    };
    frame = requestAnimationFrame(raf);

    return () => {
      cancelAnimationFrame(frame);
      lenis.destroy();
    };
  }, [enabled]);

  return null;
}
