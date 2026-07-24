/**
 * Throttles a function to at most once per animation frame. Used for
 * high-frequency MapLibre events (mousemove, move) so they update Zustand
 * at most 60x/sec instead of on every fired event — avoiding the
 * re-render storm the ADR's own risk section warns about.
 */
export function rafThrottle<Args extends unknown[]>(fn: (...args: Args) => void) {
  let scheduled = false;
  let lastArgs: Args;

  const throttled = (...args: Args) => {
    lastArgs = args;
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(() => {
      scheduled = false;
      fn(...lastArgs);
    });
  };

  return throttled;
}
