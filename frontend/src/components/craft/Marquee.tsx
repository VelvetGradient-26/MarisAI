import type { ReactNode } from 'react';
import './craft.css';

/**
 * An infinite horizontal ticker.
 *
 * The content is rendered **twice** and the track translates by exactly -50%.
 * That is the whole trick, and getting it wrong is the classic bug: animating a
 * single copy to -100% leaves a viewport-wide gap before it wraps, which reads
 * as the ticker stalling once per cycle. Two copies and a half-width travel
 * means the second copy is exactly where the first started at the moment the
 * animation resets, so the loop has no seam.
 *
 * The duplicate is `aria-hidden`, so a screen reader hears the list once.
 *
 * `duration` scales with content length rather than being fixed — a ticker with
 * four items and one with twenty must move at the same *pixels per second* or
 * the long one appears to race. Callers pass the duration because only they
 * know how wide their items render; the default assumes roughly a screenful.
 *
 * Hovering pauses it, which is not decoration: the content here is readable
 * text, and text that cannot be stopped cannot be read by anyone who reads
 * slower than it moves.
 */
export function Marquee({
  children,
  durationSeconds = 40,
  className,
}: {
  children: ReactNode;
  durationSeconds?: number;
  className?: string;
}) {
  return (
    <div className={`craft-marquee ${className ?? ''}`}>
      <div
        className="craft-marquee__track"
        style={{ ['--marquee-duration' as string]: `${durationSeconds}s` }}
      >
        <div className="craft-marquee__group">{children}</div>
        <div className="craft-marquee__group" aria-hidden="true">
          {children}
        </div>
      </div>
    </div>
  );
}
