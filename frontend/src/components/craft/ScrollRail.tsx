import { motion, useScroll, useSpring } from 'framer-motion';
import './craft.css';

/**
 * A hairline across the top of the viewport showing progress through the
 * document.
 *
 * It draws *on* the navbar's bottom border rather than beside it (see the
 * z-index ladder in craft.css) — the alternative is two horizontal lines a
 * pixel apart, which looks like a rendering bug rather than a feature.
 *
 * **Sprung rather than linear.** `useScroll` reports the true position every
 * frame, and with a smooth-scrolled page underneath (see SmoothScroll) that is
 * already eased; a second spring on top is what keeps the rail from jittering
 * during a trackpad flick, where raw scroll deltas arrive unevenly. The spring
 * is stiff enough that it is never visibly behind the content.
 *
 * Callers decide when it applies. It is not rendered on `/map`, which has no
 * document scroll at all — a rail pinned at 0% forever is reporting something
 * untrue about a page that has nothing to report.
 */
export function ScrollRail() {
  const { scrollYProgress } = useScroll();
  const scaleX = useSpring(scrollYProgress, { stiffness: 260, damping: 40, restDelta: 0.001 });

  return (
    <motion.div
      className="craft-rail"
      style={{ scaleX }}
      aria-hidden="true"
      // The rail duplicates the scrollbar, which is already exposed to
      // assistive technology by the browser. Announcing it again as a
      // progressbar would be a second, redundant reading of the same fact.
    />
  );
}
