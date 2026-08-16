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
 * - **It yields to any scroll container that is not the document**, and it
 *   works this out by measurement rather than from a list. See
 *   `isOwnScroller` below — an earlier version of this file promised the same
 *   behaviour via Lenis's `data-lenis-prevent` attribute and then never
 *   applied the attribute anywhere, which silently broke the wheel inside
 *   every internal scroller in the app (the dashboard's alerts panel was where
 *   it was noticed). A rule that has to be remembered at each of a dozen call
 *   sites is a rule that will be forgotten at one of them.
 *
 * `duration` and the easing are deliberately conservative. The default Lenis
 * feel (1.2s, a long tail) is recognisable as "a Lenis site", which is the
 * opposite of what a distinctive design wants; 0.9s with a standard expo-out
 * settles firmly enough that a short flick still feels like a flick.
 */
/**
 * True when `node` is an element that scrolls *itself* — so the wheel belongs
 * to it, not to the document.
 *
 * Lenis calls this for each element the event travelled through, and returning
 * true hands the gesture back to the browser. Two conditions, and both are
 * needed:
 *
 * - **It must have somewhere to scroll.** `scrollHeight > clientHeight + 1`;
 *   the pixel of slack is because a sub-pixel layout can leave a fractional
 *   difference on a container that is not actually scrollable.
 * - **Its overflow must actually be a scroller.** `auto` or `scroll` only —
 *   `hidden` also overflows its box and is explicitly *not* meant to scroll,
 *   and `visible` content is what the document scroll is for. Without this
 *   test every long section on a page would claim the wheel.
 *
 * Also honours Lenis's own `data-lenis-prevent`, so an element can opt out
 * explicitly when the measurement cannot see the reason (a virtualised list
 * that is scrollable only once its rows exist, say).
 *
 * The measurement runs per wheel event on a handful of ancestors, and reads
 * `scrollHeight`/`getComputedStyle` — cheap enough at that rate, and it is the
 * only thing that makes this correct for components that have not been written
 * yet.
 */
function isOwnScroller(node: HTMLElement): boolean {
  if (node.hasAttribute('data-lenis-prevent')) return true;
  if (node.scrollHeight <= node.clientHeight + 1) return false;
  const overflowY = getComputedStyle(node).overflowY;
  return overflowY === 'auto' || overflowY === 'scroll';
}

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
      prevent: isOwnScroller,
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
