import { useEffect, useState } from 'react';
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import './craft.css';

/**
 * The first-arrival curtain.
 *
 * **Once per session, not once per load.** That distinction is the whole
 * justification: a preloader on every navigation is a tax the visitor pays
 * repeatedly for a flourish they have already seen, while a preloader on the
 * first arrival is the one moment on a site where holding someone for a beat
 * is a gift. `sessionStorage` draws that line, and as a side effect a developer
 * reloading fifty times sees it once.
 *
 * **The counter is a real signal.** It tracks two things the first paint is
 * genuinely waiting on — `document.fonts.ready` (three Google families, and
 * the landing hero is set in one of them at 4rem, so a swap mid-reveal is very
 * visible) and the `load` event. There is no synthetic ramp behind it. This
 * project's dashboard rule is that a fabricated number is worse than a missing
 * one, and the front door is a strange place to make an exception: a progress
 * bar that is lying is still lying.
 *
 * The consequence is that on a warm cache the counter jumps almost immediately
 * to 100, and that is correct — the honest report of "nothing to wait for" is a
 * curtain that lifts at once. `MIN_MS` keeps the wordmark on screen long enough
 * to be read rather than to flash, which is a legibility floor rather than a
 * fake delay.
 *
 * Reduced motion skips it entirely. It is pure decoration in front of content
 * the user asked for; there is no reduced version worth keeping.
 */

const SESSION_KEY = 'marisai-curtain-seen';
/** Long enough for the wordmark to be read, short enough not to be a wait. */
const MIN_MS = 900;
const WORD = 'MARIS';

function alreadySeen(): boolean {
  try {
    return sessionStorage.getItem(SESSION_KEY) === '1';
  } catch {
    // Private browsing, or storage disabled. Showing the curtain is the safer
    // failure: it is a second of animation, not a broken page.
    return false;
  }
}

export function Preloader() {
  const reduce = useReducedMotion();
  const [open, setOpen] = useState(() => !alreadySeen());
  const [progress, setProgress] = useState(0);

  useEffect(() => {
    if (!open) return;
    if (reduce) {
      setOpen(false);
      return;
    }

    try {
      sessionStorage.setItem(SESSION_KEY, '1');
    } catch {
      /* see alreadySeen — storage being unavailable must not break the page */
    }

    // Two independent signals, each worth half the bar. Half is arbitrary as a
    // weighting, but the *events* are real: neither is a timer, and the bar
    // cannot reach 100 while either is outstanding.
    let fonts = false;
    let loaded = false;
    let settled = false;
    const started = performance.now();

    const advance = () => {
      const value = (fonts ? 50 : 0) + (loaded ? 50 : 0);
      setProgress(value);
      if (value < 100 || settled) return;
      settled = true;
      const held = performance.now() - started;
      window.setTimeout(() => setOpen(false), Math.max(0, MIN_MS - held));
    };

    if (document.fonts) {
      document.fonts.ready.then(() => {
        fonts = true;
        advance();
      });
    } else {
      // No Font Loading API. There is nothing to wait on, so this half is
      // already satisfied rather than permanently unknown.
      fonts = true;
    }

    if (document.readyState === 'complete') {
      loaded = true;
      advance();
    } else {
      window.addEventListener('load', () => {
        loaded = true;
        advance();
      });
    }

    // A hard ceiling, because a font request that never resolves must not hold
    // the page hostage. This is the one place a timer appears, and it is a
    // failure path rather than a progress model: it gives up on the signal, it
    // does not pretend the signal arrived.
    const bail = window.setTimeout(() => {
      fonts = true;
      loaded = true;
      advance();
    }, 4000);

    return () => window.clearTimeout(bail);
  }, [open, reduce]);

  return (
    <AnimatePresence>
      {open ? (
        <motion.div
          className="craft-preloader"
          // The curtain leaves *upward* and reveals the page beneath, rather
          // than fading. A fade cross-dissolves two images and reads as a
          // loading state ending; a wipe reads as something being uncovered,
          // which is what the hero underneath actually is.
          exit={{ y: '-100%' }}
          transition={{ duration: 0.9, ease: [0.76, 0, 0.24, 1] }}
        >
          <div className="craft-preloader__mark">
            <span className="craft-preloader__word">
              {WORD.split('').map((letter, index) => (
                <span key={`${letter}-${index}`} className="craft-preloader__letter">
                  <motion.span
                    initial={{ y: '110%' }}
                    animate={{ y: 0 }}
                    transition={{
                      duration: 0.7,
                      // Staggered per letter, and the stagger is short: past
                      // ~60ms a five-letter word stops reading as one gesture
                      // and starts reading as five separate ones.
                      delay: 0.08 + index * 0.05,
                      ease: [0.16, 1, 0.3, 1],
                    }}
                  >
                    {letter}
                  </motion.span>
                </span>
              ))}
            </span>
            <span className="craft-preloader__count">{String(progress).padStart(3, '0')}</span>
          </div>
          <motion.div
            className="craft-preloader__rule"
            initial={{ scaleX: 0 }}
            animate={{ scaleX: progress / 100 }}
            transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
            style={{ width: '100%' }}
          />
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}
