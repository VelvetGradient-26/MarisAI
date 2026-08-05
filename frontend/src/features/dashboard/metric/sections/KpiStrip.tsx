/** The statistics strip.
 *
 * Renders whatever the backend computed, in the order it sent — the frontend
 * has no list of statistic names, so adding one server-side needs no change
 * here.
 *
 * The behaviour that matters: a statistic with `available: false` renders its
 * reason, never a zero. "365-day change: needs 365 days of record; only 213
 * available" is a true and useful statement. "365-day change: 0.00" is a claim
 * that the ocean did not change, which is false.
 */

import { motion } from 'framer-motion';
import type { Statistic } from '../api/types';
import type { SectionProps } from '../sections';
import { useMetricStatistics } from '../hooks/useMetricData';
import { AnimatedNumber } from '../../components/AnimatedNumber';
import { Panel, PanelEmpty, PanelSkeleton } from '../../components/Panel';
import { cn } from '../../lib/cn';

function decimalsFor(value: number): number {
  const magnitude = Math.abs(value);
  if (magnitude >= 1000) return 0;
  if (magnitude >= 100) return 1;
  if (magnitude >= 1) return 2;
  return 3;
}

function StatCard({ statistic, index }: { statistic: Statistic; index: number }) {
  if (!statistic.available) {
    return (
      <Panel className="min-h-[104px]">
        <div className="flex h-full flex-col p-3">
          <div className="text-[10px] font-medium tracking-wide text-[color:var(--oid-text-ghost)] uppercase">
            {statistic.label}
          </div>
          <div className="mt-1.5 text-[15px] font-medium text-[color:var(--oid-text-ghost)]">
            Not available
          </div>
          <p className="mt-auto pt-1.5 text-[10px] leading-snug text-[color:var(--oid-text-ghost)]">
            {statistic.unavailable_reason}
          </p>
        </div>
      </Panel>
    );
  }

  const signed = statistic.key.startsWith('change_');

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: Math.min(index * 0.03, 0.24), duration: 0.35 }}
    >
      <Panel className="group min-h-[104px] transition-shadow hover:shadow-[var(--oid-shadow-raised)]">
        <div className="flex h-full flex-col p-3">
          <span className="text-[10px] font-medium tracking-wide text-[color:var(--oid-text-ghost)] uppercase">
            {statistic.label}
          </span>

          <div className="mt-1.5 flex items-baseline gap-1">
            <span
              className={cn(
                'text-[21px] leading-none font-semibold tracking-tight',
                signed && statistic.value != null && statistic.value > 0
                  ? 'text-[color:var(--color-alert-warning)]'
                  : signed && statistic.value != null && statistic.value < 0
                    ? 'text-[color:var(--oid-accent)]'
                    : 'text-[color:var(--oid-text-strong)]'
              )}
            >
              {statistic.value != null ? (
                <>
                  {signed && statistic.value > 0 ? '+' : ''}
                  <AnimatedNumber
                    value={statistic.value}
                    decimals={decimalsFor(statistic.value)}
                  />
                </>
              ) : (
                '—'
              )}
            </span>
            {statistic.unit && (
              <span className="text-[10.5px] text-[color:var(--oid-text-faint)]">
                {statistic.unit}
              </span>
            )}
          </div>

          {/* The qualifier is always shown, never hidden behind a toggle: a
              number without its window ("+1.20" over what?) is ambiguous, and
              the whole point of `detail` is to remove that ambiguity. */}
          {statistic.detail && (
            <p
              className="mt-auto truncate pt-1.5 text-[10px] text-[color:var(--oid-text-ghost)]"
              title={statistic.detail}
            >
              {statistic.detail}
            </p>
          )}
        </div>
      </Panel>
    </motion.div>
  );
}

export function KpiStrip({ variable, latitude, longitude }: SectionProps) {
  const { data, isPending, isError, error, refetch } = useMetricStatistics({
    variable: variable.key,
    latitude,
    longitude,
    range: '1y',
  });

  if (isPending) {
    return (
      <Panel>
        <PanelSkeleton rows={2} />
      </Panel>
    );
  }

  if (isError || !data) {
    return (
      <Panel>
        <PanelEmpty
          title="Statistics unavailable"
          reason={error instanceof Error ? error.message : undefined}
          onRetry={() => void refetch()}
        />
      </Panel>
    );
  }

  return (
    <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-4 2xl:grid-cols-6">
      {data.statistics.map((statistic, index) => (
        <StatCard key={statistic.key} statistic={statistic} index={index} />
      ))}
    </div>
  );
}
