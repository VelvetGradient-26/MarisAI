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
import { Markdown } from '../../../components/Markdown';
import { fetchRealtimeOceanData } from '../../map/api/realtimeOcean';
import { generateOceanInsights } from '../../insights/api/generateInsights';
import { cn } from '../lib/cn';
import { Panel, PanelEmpty, PanelHeader } from './Panel';

type Status = 'idle' | 'loading' | 'success' | 'error';

export function AiInsights({
  location,
}: {
  location: { latitude: number; longitude: number };
}) {
  const [status, setStatus] = useState<Status>('idle');
  const [insights, setInsights] = useState('');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  // A generated summary describes the point it was generated for, so moving
  // the location invalidates it rather than leaving stale prose on screen.
  useEffect(() => {
    abortRef.current?.abort();
    setStatus('idle');
    setInsights('');
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
      setInsights(response.insights);
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
              'rounded-full px-3 py-1.5 text-[length:var(--oid-text-xs)] font-medium transition-colors',
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
          // Text-shaped rather than block-shaped: ragged widths say "prose is
          // coming", where four equal bars say "a table is coming". The
          // channel treatment is the app's shared one — see `.oid-scanline`.
          <ul className="space-y-2.5" aria-busy="true">
            {[0, 1, 2, 3].map((row) => (
              <li
                key={row}
                className="oid-scanline h-3.5 rounded"
                style={{ width: `${92 - row * 11}%` }}
              >
                <span
                  className="oid-scanline__pass"
                  style={{ animationDelay: `${row * 160}ms` }}
                />
              </li>
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
            // **Rendered as Markdown, not as flattened lines.** This used to
            // split the response on newlines and strip a leading bullet from
            // each, which handled exactly one construct — the model also emits
            // `**bold**`, headings and nested lists, and every one of those
            // reached the panel as literal asterisks and hashes. The app
            // already owns a renderer for precisely this subset
            // (`components/Markdown`), built for the assistant's answers,
            // which have the same provenance: model prose over tool results.
            // It constructs React elements and never sets innerHTML, so
            // untrusted text cannot become markup.
            //
            // The per-line entrance went with it. It was staggering *source
            // lines*, which do not correspond to rendered blocks once lists
            // and paragraphs are real elements — a four-item list arrived as
            // one item. One fade on the whole block is honest about what it
            // is animating.
            <motion.div
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
              className="oid-md text-[length:var(--oid-text-md)] leading-relaxed text-[color:var(--oid-text)]"
            >
              <Markdown text={insights} />
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      <footer className="border-t border-[color:var(--oid-border)] px-4 py-2 text-[length:var(--oid-text-4xs)] leading-relaxed text-[color:var(--oid-text-ghost)]">
        Generated from live model conditions by a language model. Interpretive, not a
        forecast product, and not suitable for navigation.
      </footer>
    </Panel>
  );
}
