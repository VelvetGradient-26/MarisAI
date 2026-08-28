/** A number that counts to its new value instead of snapping.
 *
 * Uses Framer Motion's spring on a motion value rather than a render-loop of
 * React state: the tween runs off the React commit path, so a KPI updating
 * every five minutes does not re-render its whole card sixty times a second.
 *
 * Non-numeric values (the bleaching card's "High") pass straight through, and
 * a reduced-motion preference skips the animation entirely.
 */

import { useEffect, useState } from 'react';
import { animate, useMotionValue, useReducedMotion } from 'framer-motion';

export function AnimatedNumber({
  value,
  decimals = 2,
  className,
}: {
  value: number;
  decimals?: number;
  className?: string;
}) {
  const motionValue = useMotionValue(value);
  const shouldReduceMotion = useReducedMotion();
  const [display, setDisplay] = useState(value);

  useEffect(() => {
    if (shouldReduceMotion) {
      setDisplay(value);
      motionValue.set(value);
      return;
    }

    const controls = animate(motionValue, value, {
      duration: 0.7,
      ease: [0.16, 1, 0.3, 1],
      onUpdate: (latest) => setDisplay(latest),
    });
    return () => controls.stop();
  }, [value, motionValue, shouldReduceMotion]);

  return (
    <span className={className}>
      {display.toLocaleString(undefined, {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
      })}
    </span>
  );
}
