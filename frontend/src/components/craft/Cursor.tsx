import { useEffect, useRef, useState } from 'react';
import './craft.css';

/**
 * A two-part pointer: a dot that tracks exactly, and a ring that trails.
 *
 * **Only the ring lags.** Lagging both is the usual version of this effect and
 * it is a usability regression dressed as polish — the thing you aim with stops
 * landing where you point, and the whole interface feels like it is running a
 * frame behind. Keeping the dot exact and letting the ring carry the inertia
 * gets the weight without paying for it.
 *
 * **It never applies unless the device actually has a pointer.** All three of
 * `(pointer: fine)`, `(hover: hover)` and "not reduced motion" must hold. A
 * hybrid laptop that reports coarse touch, or a user who asked for less
 * motion, gets the native cursor untouched and neither element mounted — which
 * is why `cursor: none` in craft.css hangs off a body class this component
 * sets, rather than being written statically. A stylesheet that hides the
 * native cursor before the script has decided is how a touch user ends up with
 * no pointer at all.
 *
 * **It is off on the map, and that is a usability call rather than a scoping
 * one.** MapLibre communicates through the cursor: `grab` while the camera can
 * be dragged, `grabbing` during a pan, and `crosshair` while `DrawableAreaMap`
 * is waiting for a box corner. Those are the affordances telling you what the
 * pointer will do next, and `cursor: none` erases all three in exchange for a
 * ring. On a page whose whole content is a direct-manipulation surface, that is
 * a bad trade — so `App.tsx` passes `enabled={false}` there.
 *
 * The state the CSS reads (`data-cursor`, `data-cursor-down`,
 * `data-cursor-out`) is written on `<body>` rather than on the cursor element
 * itself. That is deliberate: it makes the whole ladder of appearances one
 * declarative block in craft.css instead of a set of class toggles spread
 * through this file, and it means a page can style its own cursor state
 * (`body[data-cursor='link'] .my-thing`) without importing anything.
 */

/** Anything that should swell the ring. Kept as one selector so the hit test
 *  is a single `closest()` call per pointer move rather than a chain. */
const INTERACTIVE =
  'a, button, [role="button"], summary, label, select, input[type="checkbox"], input[type="radio"], input[type="range"], .craft-magnetic, [data-cursor-target]';

/** Anything that should hand back the native I-beam. */
const TEXT_ENTRY = 'input:not([type]), input[type="text"], input[type="search"], input[type="email"], input[type="number"], input[type="password"], input[type="url"], input[type="date"], textarea, [contenteditable="true"]';

/** How much of the remaining distance the ring closes each frame. Tuned by
 *  feel, but the constraint is real: below ~0.12 the ring visibly lands after
 *  the click it was following, and above ~0.3 there is no perceptible trail
 *  left to justify the element existing. */
const RING_FOLLOW = 0.18;

function isSupported(): boolean {
  if (typeof window === 'undefined' || !window.matchMedia) return false;
  return (
    window.matchMedia('(pointer: fine)').matches &&
    window.matchMedia('(hover: hover)').matches &&
    !window.matchMedia('(prefers-reduced-motion: reduce)').matches
  );
}

export function Cursor({ enabled: allowed = true }: { enabled?: boolean } = {}) {
  // Resolved in an effect rather than at first render: `matchMedia` is a
  // browser-only API and the initial value must not differ between the two.
  const [supported, setSupported] = useState(false);
  const enabled = supported && allowed;
  const dotRef = useRef<HTMLDivElement>(null);
  const ringRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setSupported(isSupported());
    const query = window.matchMedia('(prefers-reduced-motion: reduce)');
    const onChange = () => setSupported(isSupported());
    query.addEventListener('change', onChange);
    return () => query.removeEventListener('change', onChange);
  }, []);

  useEffect(() => {
    if (!enabled) return;
    const body = document.body;
    body.classList.add('craft-cursor-on');

    // Off-screen until the first real move, so the pair does not flash at the
    // top-left corner on load.
    let pointerX = -100;
    let pointerY = -100;
    let ringX = -100;
    let ringY = -100;
    let seen = false;
    let frame = 0;

    const onMove = (event: PointerEvent) => {
      pointerX = event.clientX;
      pointerY = event.clientY;
      if (!seen) {
        // First sighting teleports the ring rather than flying it in from the
        // corner over half a second.
        seen = true;
        ringX = pointerX;
        ringY = pointerY;
      }
      body.dataset.cursorOut = 'false';

      const target = event.target as Element | null;
      if (target?.closest?.(TEXT_ENTRY)) body.dataset.cursor = 'text';
      else if (target?.closest?.(INTERACTIVE)) body.dataset.cursor = 'link';
      else body.dataset.cursor = 'default';
    };

    const onDown = () => {
      body.dataset.cursorDown = 'true';
    };
    const onUp = () => {
      body.dataset.cursorDown = 'false';
    };
    // `pointerout` with a null `relatedTarget` is the reliable "left the
    // window" signal; `mouseleave` on document fires on iframes too.
    const onOut = (event: PointerEvent) => {
      if (!event.relatedTarget) body.dataset.cursorOut = 'true';
    };

    const tick = () => {
      ringX += (pointerX - ringX) * RING_FOLLOW;
      ringY += (pointerY - ringY) * RING_FOLLOW;
      const dot = dotRef.current;
      const ring = ringRef.current;
      if (dot) {
        dot.style.setProperty('--cx', `${pointerX}px`);
        dot.style.setProperty('--cy', `${pointerY}px`);
      }
      if (ring) {
        ring.style.setProperty('--cx', `${ringX}px`);
        ring.style.setProperty('--cy', `${ringY}px`);
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);

    window.addEventListener('pointermove', onMove, { passive: true });
    window.addEventListener('pointerdown', onDown, { passive: true });
    window.addEventListener('pointerup', onUp, { passive: true });
    window.addEventListener('pointerout', onOut, { passive: true });

    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerdown', onDown);
      window.removeEventListener('pointerup', onUp);
      window.removeEventListener('pointerout', onOut);
      body.classList.remove('craft-cursor-on');
      delete body.dataset.cursor;
      delete body.dataset.cursorDown;
      delete body.dataset.cursorOut;
    };
  }, [enabled]);

  if (!enabled) return null;

  return (
    <>
      <div ref={ringRef} className="craft-cursor" aria-hidden="true">
        <div className="craft-cursor__ring" />
      </div>
      <div ref={dotRef} className="craft-cursor" aria-hidden="true">
        <div className="craft-cursor__dot" />
      </div>
    </>
  );
}
