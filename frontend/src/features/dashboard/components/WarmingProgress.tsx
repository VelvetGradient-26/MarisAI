/** Progress indicator for a source whose first fetch is still running.
 *
 * The honest problem: the backend cannot report true progress. A Copernicus
 * zarr fetch gives no byte count or step count to read, so a bar claiming
 * "63%" would be fiction.
 *
 * What it does instead is animate against the *measured typical* duration for
 * that source and say so. The bar eases toward 90% over that estimate and
 * then holds — it never completes on its own, because completion is decided
 * by the next poll returning real data, not by a timer running out. A slow
 * fetch therefore shows a bar parked near the end rather than a full bar and
 * no data, which would be a lie.
 */

import { useEffect, useState } from 'react';
import { motion, useReducedMotion } from 'framer-motion';
import { Loader2 } from 'lucide-react';
import { cn } from '../lib/cn';

/** Where the bar stops advancing on its own. */
const CEILING = 0.9;

export function WarmingProgress({
  label,
  expectedSeconds,
  className,
}: {
  label: string;
  expectedSeconds: number | null;
  className?: string;
}) {
  const estimate = expectedSeconds && expectedSeconds > 0 ? expectedSeconds : 60;
  const reduceMotion = useReducedMotion();
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const startedAt = Date.now();
    const timer = window.setInterval(() => {
      setElapsed((Date.now() - startedAt) / 1000);
    }, 250);
    return () => window.clearInterval(timer);
  }, []);

  // Ease-out: quick early progress, asymptotic approach to the ceiling. Keeps
  // a fetch that overruns its estimate from ever appearing finished.
  const fraction = CEILING * (1 - Math.exp((-2.2 * elapsed) / estimate));
  const remaining = Math.max(0, estimate - elapsed);

  return (
    <div className={cn('flex flex-col gap-2 px-4 py-5', className)} role="status" aria-live="polite">
      <div className="flex items-center gap-2 text-[color:var(--oid-text-muted)]">
        <Loader2 size={13} className={reduceMotion ? undefined : 'animate-spin'} />
        <span className="text-[11.5px] font-medium">{label}</span>
      </div>

      <div
        className="h-1 w-full overflow-hidden rounded-full bg-[color:var(--oid-track)]"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        // Deliberately not reporting a value: this is an estimate, not a
        // measurement, so assistive tech gets the indeterminate contract.
        aria-valuetext={`Loading, about ${Math.ceil(remaining)} seconds remaining`}
      >
        <motion.div
          className="h-full rounded-full bg-gradient-to-r from-[color:var(--oid-accent)] to-[color:var(--oid-accent-soft)]"
          animate={{ width: `${fraction * 100}%` }}
          transition={{ duration: 0.4, ease: 'easeOut' }}
        />
      </div>

      <p className="text-[10px] leading-snug text-[color:var(--oid-text-faint)]">
        {remaining > 1
          ? `Fetching from the provider — usually about ${Math.ceil(remaining)}s more.`
          : 'Taking longer than usual. Still fetching; this panel fills in automatically.'}
      </p>
    </div>
  );
}
