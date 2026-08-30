/** One hero KPI card.
 *
 * Two behaviours matter more than the styling:
 *
 *  1. `available: false` renders an explanation, never a zero. These are
 *     ocean measurements; a fabricated "0.00 mg/m³" would be a false reading,
 *     not a neutral placeholder.
 *  2. Every card exposes its `scope` — the coverage, region or rule behind
 *     the figure — through a tooltip and a visible footnote, because several
 *     of these numbers are regional or proxy-based and a bare value would
 *     overstate them.
 */

import { useState, type ReactNode } from 'react';
import { motion } from 'framer-motion';
import { ArrowDownRight, ArrowRight, ArrowUpRight, Info } from 'lucide-react';
import { Link } from '../../../app/router';
import type { KpiCard as KpiCardData } from '../api/types';
import { formatAge, formatSigned } from '../lib/format';
import { cn } from '../lib/cn';
import { AnimatedNumber } from './AnimatedNumber';
import { Sparkline } from './Sparkline';
import { Panel, PanelEmpty } from './Panel';
import { WarmingProgress } from './WarmingProgress';

function decimalsFor(value: number): number {
  // Counts must not grow a decimal point: the heat-stress card reports a
  // number of regions, and "31.0 regions" reads as a measurement.
  if (Number.isInteger(value)) return 0;
  const magnitude = Math.abs(value);
  if (magnitude >= 100) return 0;
  if (magnitude >= 10) return 1;
  if (magnitude >= 1) return 2;
  return 3;
}

function TrendBadge({ card }: { card: KpiCardData }) {
  const trend = card.trend;
  if (!trend) return null;

  const Icon =
    trend.direction === 'up' ? ArrowUpRight : trend.direction === 'down' ? ArrowDownRight : ArrowRight;

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[length:var(--oid-text-2xs)] font-medium',
        'bg-[color:var(--oid-track)] text-[color:var(--oid-text)]'
      )}
      title={`Change across ${trend.points} readings observed by this server`}
    >
      <Icon size={11} />
      {trend.change_pct != null
        ? `${trend.change_pct > 0 ? '+' : ''}${trend.change_pct.toFixed(1)}%`
        : formatSigned(trend.change, card.unit)}
    </span>
  );
}

export function KpiCard({
  card,
  index = 0,
  to,
}: {
  card: KpiCardData;
  index?: number;
  /**
   * Metric intelligence page for this card, when one exists.
   *
   * Only three of the six cards have one. Heat-stress extent, bleaching risk
   * and habitat suitability are derived indices computed across a region, not
   * variables with a point history to forecast — so they stay inert rather
   * than linking somewhere that would 404.
   */
  to?: string;
}) {
  const [showScope, setShowScope] = useState(false);

  if (!card.available) {
    // "Warming" and "unavailable" get visibly different treatments. On a cold
    // start the Copernicus-backed cards are simply mid-fetch for a minute or
    // so, and showing that as an error would misreport a healthy system.
    const isWarming = card.status === 'warming';
    return (
      <Panel className="min-h-[168px]">
        <div className="px-4 pt-3.5">
          <h3 className="text-[length:var(--oid-text-sm)] font-medium tracking-wide text-[color:var(--oid-text-muted)] uppercase">
            {card.label}
          </h3>
        </div>
        {isWarming ? (
          <WarmingProgress
            label="Loading live data"
            expectedSeconds={card.expected_warmup_seconds}
          />
        ) : (
          <PanelEmpty
            title="Source unavailable"
            reason={card.unavailable_reason}
            className="py-6"
          />
        )}
      </Panel>
    );
  }

  const numeric = typeof card.value === 'number' ? card.value : null;

  const body = (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: Math.min(index * 0.05, 0.3), duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
    >
      <Panel
        className={cn(
          'group min-h-[168px] transition-shadow duration-300',
          'hover:shadow-[var(--oid-shadow-raised)]'
        )}
      >
        {/* A hairline of accent along the top edge, brightening on hover. */}
        <span
          aria-hidden="true"
          className={cn(
            'absolute inset-x-0 top-0 h-px opacity-60 transition-opacity duration-300',
            'bg-gradient-to-r from-transparent via-[color:var(--oid-accent)] to-transparent',
            'group-hover:opacity-100'
          )}
        />

        <div className="flex h-full flex-col gap-3 p-4">
          <div className="flex items-start justify-between gap-2">
            <h3 className="text-[length:var(--oid-text-sm)] font-medium tracking-wide text-[color:var(--oid-text-muted)] uppercase">
              {card.label}
            </h3>
            {card.scope && (
              <button
                type="button"
                aria-label={`What ${card.label} covers`}
                aria-expanded={showScope}
                onClick={() => setShowScope((open) => !open)}
                className="shrink-0 text-[color:var(--oid-text-ghost)] transition-colors hover:text-[color:var(--oid-accent)]"
              >
                <Info size={13} />
              </button>
            )}
          </div>

          <div className="flex items-end justify-between gap-3">
            <div className="min-w-0">
              <div className="flex items-baseline gap-1.5">
                <span className="text-[30px] leading-none font-semibold tracking-tight text-[color:var(--oid-text-strong)]">
                  {numeric != null ? (
                    <AnimatedNumber value={numeric} decimals={decimalsFor(numeric)} />
                  ) : (
                    String(card.value ?? '—')
                  )}
                </span>
                {card.unit && (
                  <span className="text-[length:var(--oid-text-base)] font-medium text-[color:var(--oid-text-faint)]">{card.unit}</span>
                )}
              </div>

              <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                <TrendBadge card={card} />
                {card.anomaly_c != null && (
                  <span
                    className={cn(
                      'rounded-full px-1.5 py-0.5 text-[length:var(--oid-text-2xs)] font-medium',
                      card.anomaly_c > 0
                        ? 'bg-[color:color-mix(in_oklab,var(--color-alert-warning)_16%,transparent)] text-[color:var(--color-alert-warning)]'
                        : 'bg-[color:var(--oid-accent-wash)] text-[color:var(--oid-accent)]'
                    )}
                    title={card.anomaly_baseline ?? undefined}
                  >
                    {formatSigned(card.anomaly_c, '°C')} vs baseline
                  </span>
                )}
              </div>
            </div>

            <Sparkline
              points={card.sparkline ?? []}
              className="shrink-0"
              // A rising chlorophyll or SST line is not "good"; only the
              // neutral fields get the aqua treatment.
              positiveIsUp={card.key === 'habitat_suitability'}
            />
          </div>

          {card.detail && (
            <p className="text-[length:var(--oid-text-xs)] leading-snug text-[color:var(--oid-text-faint)]">{card.detail}</p>
          )}

          {showScope && card.scope && (
            <motion.p
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              className={cn(
                'rounded-lg border border-[color:var(--oid-border)] p-2',
                'bg-[color:var(--oid-elevated)] text-[length:var(--oid-text-2xs)] leading-relaxed text-[color:var(--oid-text-muted)]'
              )}
            >
              {card.scope}
            </motion.p>
          )}

          <footer className="mt-auto flex items-center justify-between gap-2 pt-1 text-[length:var(--oid-text-3xs)] text-[color:var(--oid-text-ghost)]">
            <span className="truncate" title={card.source ?? undefined}>
              {card.source ?? 'Unknown source'}
            </span>
            <span className="shrink-0">
              {card.observed_at ? formatAge(ageSeconds(card.observed_at)) : '—'}
            </span>
          </footer>

          {to && (
            <span
              aria-hidden="true"
              className={cn(
                'absolute right-3 bottom-3 inline-flex items-center gap-1 text-[length:var(--oid-text-3xs)]',
                'text-[color:var(--oid-accent)] opacity-0 transition-opacity',
                'group-hover:opacity-100'
              )}
            >
              Analyse <ArrowUpRight size={11} />
            </span>
          )}
        </div>
      </Panel>
    </motion.div>
  );

  // Wrapping rather than making the Panel itself an anchor: the scope button
  // inside is interactive, and nesting a button in an anchor is invalid and
  // breaks keyboard activation of both.
  return to ? (
    <Link to={to} className="block no-underline" aria-label={`Analyse ${card.label}`}>
      {body}
    </Link>
  ) : (
    body
  );
}

function ageSeconds(iso: string): number | null {
  const parsed = Date.parse(iso);
  if (Number.isNaN(parsed)) return null;
  return Math.max(0, (Date.now() - parsed) / 1000);
}

export function KpiGrid({ children }: { children: ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-6">
      {children}
    </div>
  );
}
