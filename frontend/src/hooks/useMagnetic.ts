import { useEffect, useRef } from 'react';

/**
 * Pulls an element a fraction of the way toward the pointer while the pointer
 * is near it.
 *
 * The effect is small and the restraint is the design: at `strength` above
 * ~0.4 a button visibly leaves its own layout box, which stops reading as
 * "this control is attracted to you" and starts reading as "this control is
 * dodging you". Clicking a target that moves away from the cursor is
 * genuinely worse than clicking a still one, so the pull is capped at
 * `maxPx` regardless of how far outside the element the pointer is.
 *
 * **The offset is written to `--mag-x`/`--mag-y`, never to `transform`.**
 * That is what lets a magnetic element keep whatever transform its own
 * stylesheet already gives it — a hover lift, a scale — and compose with the
 * magnet rather than being overwritten by it. The element's own rule must
 * therefore include the two variables in its transform; `.craft-magnetic` in
 * craft.css is the default for elements with no transform of their own.
 *
 * **Disabled on coarse pointers and under reduced motion.** On touch there is
 * no hover to track and the listener would never fire usefully; under reduced
 * motion the element simply sits still, which is a complete and correct
 * version of this control.
 *
 * The listener is on `window` rather than on the element, because the pull has
 * to begin *before* the pointer arrives — that anticipation is the entire
 * effect, and an element-scoped `pointermove` only fires once the pointer is
 * already inside.
 */
export function useMagnetic<T extends HTMLElement>({
  strength = 0.28,
  /**
   * How far outside the element's own box the pull reaches, in pixels.
   *
   * 60 rather than the 90 this started at, from a measurement: the landing
   * hero's two calls to action sit ~75px apart, so at 90 a pointer resting on
   * the primary button was also pulling the secondary one sideways. Two
   * controls leaning at once reads as the layout being unstable rather than as
   * either of them being attracted, which is the exact opposite of what the
   * effect is for. 60 keeps the anticipation and engages one control at a time.
   */
  radius = 60,
  maxPx = 14,
}: { strength?: number; radius?: number; maxPx?: number } = {}) {
  const ref = useRef<T>(null);

  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    if (typeof window === 'undefined' || !window.matchMedia) return;
    if (!window.matchMedia('(pointer: fine)').matches) return;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

    let engaged = false;
    let frame = 0;

    const apply = (x: number, y: number) => {
      element.style.setProperty('--mag-x', `${x}px`);
      element.style.setProperty('--mag-y', `${y}px`);
    };

    const release = () => {
      if (!engaged) return;
      engaged = false;
      // The return is the only part that is eased. The pull itself must not
      // be: the pointer is already a continuous input, so a transition on it
      // adds lag with nothing to smooth. The class is removed once the
      // transition has run so the next pull starts instantly again.
      element.classList.add('craft-magnetic--releasing');
      apply(0, 0);
      window.setTimeout(() => element.classList.remove('craft-magnetic--releasing'), 460);
    };

    const onMove = (event: PointerEvent) => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const rect = element.getBoundingClientRect();
        // Zero-sized means not laid out (or hidden) — measuring it would give
        // a centre at the origin and fling the element across the screen.
        if (rect.width === 0) return;

        const cx = rect.left + rect.width / 2;
        const cy = rect.top + rect.height / 2;
        // Distance from the element's *edge*, not its centre, so a wide button
        // and a small icon engage at the same visual proximity.
        const dx = Math.max(rect.left - event.clientX, 0, event.clientX - rect.right);
        const dy = Math.max(rect.top - event.clientY, 0, event.clientY - rect.bottom);

        if (Math.hypot(dx, dy) > radius) {
          release();
          return;
        }

        engaged = true;
        element.classList.remove('craft-magnetic--releasing');
        const px = (event.clientX - cx) * strength;
        const py = (event.clientY - cy) * strength;
        const distance = Math.hypot(px, py);
        const scale = distance > maxPx ? maxPx / distance : 1;
        apply(px * scale, py * scale);
      });
    };

    window.addEventListener('pointermove', onMove, { passive: true });
    // A pointer that leaves the window stops firing `pointermove`, so without
    // this the element stays stuck at its last offset.
    window.addEventListener('pointerleave', release, { passive: true });
    // And a click that navigates away unmounts mid-pull; the cleanup below
    // covers that, but a blur (tab switch) does not unmount anything.
    window.addEventListener('blur', release);

    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerleave', release);
      window.removeEventListener('blur', release);
    };
  }, [strength, radius, maxPx]);

  return ref;
}
