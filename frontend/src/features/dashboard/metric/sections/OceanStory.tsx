/** The Ocean Story — the narrative a reader meets before any chart.
 *
 * The badge is not decoration. The backend tells us whether the text was
 * phrased by a language model, rendered deterministically, or fell back after
 * the model produced a figure it was not given, and a reader is entitled to
 * know which of those they are reading. "Show the figures" opens the exact
 * block the narrative was allowed to draw from, so any sentence can be checked
 * against its source without leaving the page.
 */

import { useState } from 'react';
import { motion } from 'framer-motion';
import { ChevronDown, ShieldCheck, Sparkles, Table } from 'lucide-react';
import type { SectionProps } from '../sections';
import { useOceanStory } from '../hooks/useMetricData';
import { Panel, PanelEmpty, PanelHeader, PanelSkeleton } from '../../components/Panel';
import { cn } from '../../lib/cn';

const BADGES = {
  generated: {
    icon: Sparkles,
    label: 'AI-phrased',
    hint: 'A language model phrased figures computed by the server. It could not introduce a number of its own — any response containing one is rejected.',
    tone: 'accent' as const,
  },
  template: {
    icon: ShieldCheck,
    label: 'Computed',
    hint: 'Written directly from the statistics, with no language model involved.',
    tone: 'neutral' as const,
  },
  'template-after-verification-failed': {
    icon: ShieldCheck,
    label: 'Computed (AI output rejected)',
    hint: 'The language model produced a figure that was not in the supplied statistics, so its text was discarded and this was written directly from the data instead.',
    tone: 'warning' as const,
  },
};

export function OceanStory({ variable, latitude, longitude }: SectionProps) {
  const [showFacts, setShowFacts] = useState(false);
  const horizon = variable.trained_horizons.includes(7)
    ? 7
    : (variable.trained_horizons[0] ?? undefined);

  const { data, isPending, isError, error, refetch } = useOceanStory({
    variable: variable.key,
    latitude,
    longitude,
    horizon,
  });

  const badge = data ? BADGES[data.source] : null;
  const BadgeIcon = badge?.icon;

  return (
    <Panel>
      <PanelHeader
        icon={<Sparkles size={14} />}
        title="Ocean Story"
        subtitle={`What the record says about ${variable.label.toLowerCase()} at this point`}
        actions={
          badge && BadgeIcon ? (
            <span
              title={badge.hint}
              className={cn(
                'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[length:var(--oid-text-3xs)] font-medium',
                badge.tone === 'accent' &&
                  'bg-[color:var(--oid-accent-wash)] text-[color:var(--oid-accent)]',
                badge.tone === 'neutral' &&
                  'bg-[color:var(--oid-track)] text-[color:var(--oid-text-muted)]',
                badge.tone === 'warning' &&
                  'bg-[color:color-mix(in_oklab,var(--color-alert-warning)_16%,transparent)] text-[color:var(--color-alert-warning)]'
              )}
            >
              <BadgeIcon size={11} />
              {badge.label}
            </span>
          ) : null
        }
      />

      {isPending && <PanelSkeleton rows={3} />}

      {isError && (
        <PanelEmpty
          title="Summary unavailable"
          reason={error instanceof Error ? error.message : undefined}
          onRetry={() => void refetch()}
        />
      )}

      {data && (
        <div className="p-4">
          <motion.p
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.5 }}
            className="text-[14px] leading-relaxed text-[color:var(--oid-text)]"
          >
            {data.story}
          </motion.p>

          <button
            type="button"
            onClick={() => setShowFacts((open) => !open)}
            aria-expanded={showFacts}
            className={cn(
              'mt-3 inline-flex items-center gap-1.5 text-[length:var(--oid-text-xs)]',
              'text-[color:var(--oid-text-faint)] transition-colors',
              'hover:text-[color:var(--oid-accent)]'
            )}
          >
            <Table size={11} />
            {showFacts ? 'Hide' : 'Show'} the figures this was written from
            <ChevronDown
              size={11}
              className={cn('transition-transform', showFacts && 'rotate-180')}
            />
          </button>

          {showFacts && (
            <motion.pre
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              className={cn(
                'mt-2 overflow-x-auto rounded-lg border p-3',
                'border-[color:var(--oid-border)] bg-[color:var(--oid-elevated)]',
                'font-mono text-[length:var(--oid-text-2xs)] leading-relaxed text-[color:var(--oid-text-muted)]'
              )}
            >
              {data.facts}
            </motion.pre>
          )}
        </div>
      )}
    </Panel>
  );
}
