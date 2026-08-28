import { useRef } from 'react';
import { motion, useInView, useReducedMotion } from 'framer-motion';
import './craft.css';

/**
 * A heading whose words rise out of a clipping mask as it scrolls into view.
 *
 * **This is not a duplicate of the vendored `SplitText`,** and the difference
 * is what decides which to use:
 *
 * - `SplitText` (components/reactbits) splits to *characters* and animates
 *   opacity and offset per character. That is right for the two hero lines,
 *   where the text is short, enormous, and the effect is the subject.
 * - This splits to *words* and animates position behind a hard mask, with no
 *   opacity change at all. At paragraph width — a section heading is five to
 *   eight words on two or three lines — per-character opacity reads as a
 *   shimmer and the sentence becomes unreadable while it plays. A mask reveal
 *   stays legible the entire time because every glyph that is visible is fully
 *   visible.
 *
 * The masking mechanic is the same one the preloader wordmark uses, which is
 * why both live in craft.css: an `overflow: hidden` inline box per word, with
 * the word translated inside it. The subtlety is the box — a line box clips
 * descenders and diacritics exactly at the baseline, so `.craft-kinetic__word`
 * pads itself and pulls the margin back to make room without moving the text.
 * Without that, every `g`, `y` and `Å` in a heading is sliced.
 *
 * Reduced motion returns the text as a plain fragment and never renders the
 * wrapper elements at all — not a faster animation, and not a still one. The
 * split itself is a DOM change with real costs (selection breaks across word
 * boundaries, and some screen readers announce split text a word at a time),
 * so when the animation is off there is no reason to pay them.
 *
 * The reveal fires once. Replaying every time a heading scrolls back into view
 * is the same distraction `useReveal` documents and refuses.
 */
export function KineticText({
  text,
  className,
  /** Seconds between adjacent words. Short by default: past ~90ms a heading
   *  stops reading as one movement and starts reading as a list. */
  stagger = 0.045,
  /** Seconds before the first word moves. */
  delay = 0,
  as: Tag = 'span',
}: {
  text: string;
  className?: string;
  stagger?: number;
  delay?: number;
  as?: 'span' | 'h1' | 'h2' | 'h3';
}) {
  const reduce = useReducedMotion();
  const ref = useRef<HTMLElement>(null);
  // `once` matches useReveal's rule. `amount: 0.3` rather than the default so
  // a tall heading starts moving when a third of it is on screen, instead of
  // waiting for the whole block.
  const inView = useInView(ref, { once: true, amount: 0.3 });

  if (reduce) return <Tag className={className}>{text}</Tag>;

  const words = text.split(' ');

  return (
    <Tag className={className} ref={ref as never}>
      {/* The accessible copy. The visual words below are hidden from the
          accessibility tree, because a heading split into one element per word
          is announced as separate fragments by some screen readers — the same
          reason SplitText's own upstream keeps an unsplit copy. */}
      <span className="craft-kinetic__sr">{text}</span>
      <span className="craft-kinetic" aria-hidden="true">
        {words.map((word, index) => (
          <span key={`${word}-${index}`} className="craft-kinetic__word">
            <motion.span
              className="craft-kinetic__inner"
              initial={{ y: '108%' }}
              animate={inView ? { y: 0 } : { y: '108%' }}
              transition={{
                duration: 0.85,
                delay: delay + index * stagger,
                // A long, decelerating settle. The curve matters more than the
                // duration here: an ease that arrives abruptly reads as a
                // slide-in, and the whole point of a mask reveal is that the
                // word appears to have been there all along.
                ease: [0.16, 1, 0.3, 1],
              }}
            >
              {word}
              {/* The trailing space is inside the mask rather than between the
                  boxes, so the words stay a real sentence for line breaking —
                  a flex row of word boxes with gaps cannot wrap mid-heading. */}
              {index < words.length - 1 ? ' ' : ''}
            </motion.span>
          </span>
        ))}
      </span>
    </Tag>
  );
}
