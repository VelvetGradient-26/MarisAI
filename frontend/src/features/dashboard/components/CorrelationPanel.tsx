/** Pairwise variable correlation — `GET /api/dashboard/trends/correlation`,
 * unconsumed anywhere in the frontend before this.
 *
 * The backend returns per-pair Pearson r + significance, never the
 * underlying paired daily values (`services/correlation.py` discards them
 * once `r` is computed) — so this renders a small stat card per pair, not a
 * scatter chart. See `RelatedVariables.tsx`'s own comment, which already
 * flagged this exact endpoint as the missing piece for that page.
 */

import { useMemo, useState } from 'react';
import { Activity } from 'lucide-react';
import { Panel, PanelEmpty, PanelHeader, PanelSkeleton } from './Panel';
import { useCorrelation, useTrendsCatalog } from '../hooks/useDashboardData';
import { isCorrelationPairAvailable } from '../api/types';
import type { CorrelationPair } from '../api/types';
import { cn } from '../lib/cn';

const RANGE = '1y';
const MAX_VARIABLES = 4;

export function CorrelationPanel({
  latitude,
  longitude,
}: {
  latitude: number;
  longitude: number;
}) {
  const { data: catalog } = useTrendsCatalog();
  const available = useMemo(
    () => (catalog?.variables ?? []).filter((entry) => entry.available),
    [catalog]
  );

  // Defaults to the first three available catalog variables, so the panel
  // shows something real without requiring interaction first.
  const [selected, setSelected] = useState<string[]>([]);
  const activeKeys = selected.length >= 2 ? selected : available.slice(0, 3).map((v) => v.key);

  const { data, isPending, isError, error, refetch } = useCorrelation({
    variables: activeKeys,
    latitude,
    longitude,
    range: RANGE,
    enabled: activeKeys.length >= 2,
  });

  const toggle = (key: string) => {
    setSelected((current) => {
      const base = current.length >= 2 ? current : available.slice(0, 3).map((v) => v.key);
      if (base.includes(key)) return base.filter((k) => k !== key);
      if (base.length >= MAX_VARIABLES) return base;
      return [...base, key];
    });
  };

  return (
    <Panel>
      <PanelHeader
        icon={<Activity size={14} />}
        title="Correlation"
        subtitle="How two or more variables have moved together over the past year"
      />

      <div className="flex flex-wrap gap-1.5 border-b border-[color:var(--oid-border)] p-3.5">
        {available.map((variable) => {
          const isActive = activeKeys.includes(variable.key);
          return (
            <button
              key={variable.key}
              type="button"
              onClick={() => toggle(variable.key)}
              className={cn(
                'rounded-full border px-2.5 py-1 text-[length:var(--oid-text-2xs)] transition-colors',
                isActive
                  ? 'border-[color:var(--oid-accent)] bg-[color:var(--oid-accent-wash)] text-[color:var(--oid-accent)]'
                  : 'border-[color:var(--oid-border)] text-[color:var(--oid-text-faint)] hover:text-[color:var(--oid-text)]'
              )}
            >
              {variable.label}
            </button>
          );
        })}
      </div>

      {activeKeys.length < 2 && (
        <PanelEmpty title="Pick at least two variables" reason="Choose up to four above to compare." />
      )}

      {activeKeys.length >= 2 && isPending && <PanelSkeleton rows={3} />}

      {activeKeys.length >= 2 && isError && (
        <PanelEmpty
          title="Could not load correlation"
          reason={error instanceof Error ? error.message : undefined}
          onRetry={() => void refetch()}
        />
      )}

      {data && (
        <div className="p-3.5">
          {Object.keys(data.variables_unavailable).length > 0 && (
            <p className="mb-2.5 text-[length:var(--oid-text-2xs)] text-[color:var(--oid-text-faint)]">
              Not available at this point:{' '}
              {Object.entries(data.variables_unavailable)
                .map(([key, reason]) => `${key} (${reason})`)
                .join(', ')}
            </p>
          )}

          {data.pairs.length === 0 ? (
            <PanelEmpty title="No pairs to compare" />
          ) : (
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {data.pairs.map((pair) => (
                <CorrelationCard key={`${pair.variable_a}-${pair.variable_b}`} pair={pair} />
              ))}
            </div>
          )}

          <p className="mt-3 text-[length:var(--oid-text-3xs)] leading-relaxed text-[color:var(--oid-text-ghost)]">
            {data.note}
          </p>
        </div>
      )}
    </Panel>
  );
}

function CorrelationCard({ pair }: { pair: CorrelationPair }) {
  if (!isCorrelationPairAvailable(pair)) {
    return (
      <div className="rounded-lg border border-[color:var(--oid-border)] bg-[color:var(--oid-elevated)] p-2.5">
        <div className="text-[length:var(--oid-text-xs)] font-medium text-[color:var(--oid-text-strong)]">
          {pair.variable_a} × {pair.variable_b}
        </div>
        <div className="mt-1 text-[length:var(--oid-text-3xs)] text-[color:var(--oid-text-ghost)]">
          {pair.reason}
        </div>
      </div>
    );
  }

  const sign = pair.correlation_r > 0 ? '+' : '';

  return (
    <div className="rounded-lg border border-[color:var(--oid-border)] bg-[color:var(--oid-elevated)] p-2.5">
      <div className="text-[length:var(--oid-text-xs)] font-medium text-[color:var(--oid-text-strong)]">
        {pair.variable_a} × {pair.variable_b}
      </div>
      <div className="mt-1 flex items-baseline gap-1.5">
        <span className="text-[16px] font-semibold text-[color:var(--oid-text-strong)]">
          {sign}
          {pair.correlation_r.toFixed(2)}
        </span>
        <span className="text-[length:var(--oid-text-3xs)] text-[color:var(--oid-text-faint)]">
          {pair.strength}, {pair.direction}
        </span>
      </div>
      <div className="mt-0.5 text-[length:var(--oid-text-3xs)] text-[color:var(--oid-text-ghost)]">
        {pair.overlapping_days} overlapping days ·{' '}
        {pair.statistically_significant ? 'statistically significant' : 'not statistically significant'}
      </div>
    </div>
  );
}
