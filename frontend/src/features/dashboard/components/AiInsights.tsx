/** AI insights over the selected point's live conditions.
 *
 * Reuses the existing `/api/insights/generate` path rather than adding a
 * second one: that endpoint is already authenticated, rate-limited and
 * input-bounded (see routers/insights.py), all of which a new endpoint would
 * have to re-earn.
 *
 * Generation is explicitly user-triggered. It costs LLM quota per call, so
 * firing it automatically on every poll or location change would bill the
 * project for insights nobody asked to read.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { Sparkles } from 'lucide-react';
import { fetchRealtimeOceanData } from '../../map/api/realtimeOcean';
import { generateOceanInsights } from '../../insights/api/generateInsights';
import { cn } from '../lib/cn';
import { Panel, PanelEmpty, PanelHeader } from './Panel';

type Status = 'idle' | 'loading' | 'success' | 'error';

/** The model returns prose or a bullet list; both become clean lines. */
function toLines(text: string): string[] {
  return text
    .split(/\r?\n/)
    .map((line) => line.replace(/^[\s*•-]+/, '').replace(/^\d+\.\s*/, '').trim())
    .filter(Boolean);
}

export function AiInsights({
  location,
}: {
  location: { latitude: number; longitude: number };
}) {
  const [status, setStatus] = useState<Status>('idle');
  const [lines, setLines] = useState<string[]>([]);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  // A generated summary describes the point it was generated for, so moving
  // the location invalidates it rather than leaving stale prose on screen.
  useEffect(() => {
    abortRef.current?.abort();
    setStatus('idle');
    setLines([]);
    setErrorMessage(null);
  }, [location.latitude, location.longitude]);

  useEffect(() => () => abortRef.current?.abort(), []);

  const generate = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setStatus('loading');
    setErrorMessage(null);

    try {
      const conditions = await fetchRealtimeOceanData(
        { lat: location.latitude, lng: location.longitude },
        controller.signal
      );
      const response = await generateOceanInsights(conditions, controller.signal);
      if (controller.signal.aborted) return;
      setLines(toLines(response.insights));
      setStatus('success');
    } catch (error: unknown) {
      if (controller.signal.aborted) return;
      setErrorMessage(error instanceof Error ? error.message : 'Failed to generate insights');
      setStatus('error');
    }
  }, [location.latitude, location.longitude]);

  return (
    <Panel className="flex h-full flex-col">
      <PanelHeader
        icon={<Sparkles size={15} />}
        title="AI insights"
        subtitle={`Conditions at ${location.latitude.toFixed(2)}°, ${location.longitude.toFixed(2)}°`}
        actions={
          <button
            type="button"
            onClick={() => void generate()}
            disabled={status === 'loading'}
            className={cn(
              'rounded-full px-3 py-1.5 text-[11px] font-medium transition-colors',
              'bg-[color:var(--oid-accent-wash)]',
              'text-[color:var(--oid-accent)]',
              'hover:bg-[color:var(--oid-accent-wash-strong)]',
              'disabled:opacity-50'
            )}
          >
            {status === 'loading'
              ? 'Analysing…'
              : status === 'success'
                ? 'Regenerate'
                : 'Generate'}
          </button>
        }
      />

      <div className="flex-1 p-4">
        {status === 'idle' && (
          <PanelEmpty
            title="No summary generated yet"
            reason={
              'Generates a natural-language reading of the live conditions at this point — temperature, waves, wind and currents.'
            }
            icon={<Sparkles size={20} />}
          />
        )}

        {status === 'loading' && (
          <ul className="space-y-2.5" aria-busy="true">
            {[0, 1, 2, 3].map((row) => (
              <li
                key={row}
                className="h-3.5 animate-[var(--animate-shimmer)] rounded bg-[color:var(--oid-track)]"
                style={{ width: `${92 - row * 11}%`, animationDelay: `${row * 130}ms` }}
              />
            ))}
          </ul>
        )}

        {status === 'error' && (
          <PanelEmpty
            title="Could not generate insights"
            reason={errorMessage}
            onRetry={() => void generate()}
          />
        )}

        <AnimatePresence>
          {status === 'success' && (
            <motion.ul
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="space-y-2.5"
            >
              {lines.map((line, index) => (
                <motion.li
                  key={index}
                  initial={{ opacity: 0, x: -6 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: index * 0.07, duration: 0.3 }}
                  className="flex gap-2.5 text-[12.5px] leading-relaxed text-[color:var(--oid-text)]"
                >
                  <span
                    aria-hidden="true"
                    className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-[color:var(--oid-accent-soft)]"
                  />
                  {line}
                </motion.li>
              ))}
            </motion.ul>
          )}
        </AnimatePresence>
      </div>

      <footer className="border-t border-[color:var(--oid-border)] px-4 py-2 text-[9.5px] leading-relaxed text-[color:var(--oid-text-ghost)]">
        Generated from live model conditions by a language model. Interpretive, not a
        forecast product, and not suitable for navigation.
      </footer>
    </Panel>
  );
}
