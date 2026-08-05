/** The hero: current value, trend, forecast, confidence, freshness.
 *
 * The five things a reader wants before they decide whether to scroll. Each is
 * sourced, not inferred: the current value and timestamp come from the record,
 * the forecast and its interval from a trained model, and "confidence" is a
 * plain-language rendering of that model's out-of-sample skill rather than a
 * word chosen for effect.
 */

import { motion } from 'framer-motion';
import { ArrowDownRight, ArrowRight, ArrowUpRight, Clock } from 'lucide-react';
import type { SectionProps } from '../sections';
import { useBatchForecast, useMetricStatistics } from '../hooks/useMetricData';
import { isForecastError } from '../api/types';
import { AnimatedNumber } from '../../components/AnimatedNumber';
import { Panel } from '../../components/Panel';
import { formatAge } from '../../lib/format';
import { cn } from '../../lib/cn';

/** Model skill translated into a word, with the number kept alongside it.
 *
 * The mapping is on `skill_score` — improvement over a persistence forecast —
 * because that, not R², is the number that says whether the model is worth
 * consulting. An R² of 0.99 on a smooth series is unremarkable; beating
 * "tomorrow looks like today" is not.
 */
function confidenceFrom(skill: number | null | undefined): {
  word: string;
  tone: 'strong' | 'fair' | 'weak' | 'unknown';
  detail: string;
} {
  if (skill == null || !Number.isFinite(skill)) {
    return { word: 'Unrated', tone: 'unknown', detail: 'no validated skill score' };
  }
  const pct = `${(skill * 100).toFixed(0)}% better than persistence`;
  if (skill >= 0.3) return { word: 'High', tone: 'strong', detail: pct };
  if (skill >= 0.1) return { word: 'Moderate', tone: 'fair', detail: pct };
  if (skill > 0) return { word: 'Low', tone: 'weak', detail: pct };
  return { word: 'Poor', tone: 'weak', detail: 'no better than persistence' };
}

function Stat({
  label,
  children,
  hint,
}: {
  label: string;
  children: React.ReactNode;
  hint?: string;
}) {
  return (
    <div className="min-w-0">
      <div className="text-[10px] font-medium tracking-wide text-[color:var(--oid-text-ghost)] uppercase">
        {label}
      </div>
      <div className="mt-1 text-[color:var(--oid-text-strong)]">{children}</div>
      {hint && (
        <div className="mt-0.5 truncate text-[10.5px] text-[color:var(--oid-text-ghost)]">
          {hint}
        </div>
      )}
    </div>
  );
}

export function MetricHero({ variable, latitude, longitude }: SectionProps) {
  const { data: stats } = useMetricStatistics({
    variable: variable.key,
    latitude,
    longitude,
    range: '1y',
  });

  const horizon = variable.trained_horizons.includes(7)
    ? 7
    : (variable.trained_horizons[0] ?? null);

  const { data: batch } = useBatchForecast({
    variable: variable.key,
    latitude,
    longitude,
    horizons: horizon ? [horizon] : [],
    enabled: horizon != null,
  });

  const entry = horizon != null ? batch?.forecasts?.[String(horizon)] : undefined;
  const forecast = entry && !isForecastError(entry) ? entry : null;

  const current = stats?.statistics.find((item) => item.key === 'current');
  const confidence = confidenceFrom(forecast?.evaluation.skill_score);

  const TrendIcon =
    forecast?.trend === 'Increasing'
      ? ArrowUpRight
      : forecast?.trend === 'Decreasing'
        ? ArrowDownRight
        : ArrowRight;

  return (
    <Panel className="overflow-visible">
      <span
        aria-hidden="true"
        className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-[color:var(--oid-accent)] to-transparent opacity-70"
      />
      <div className="p-5">
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.45, ease: [0.16, 1, 0.3, 1] }}
        >
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h1 className="text-[26px] leading-none font-semibold tracking-tight text-[color:var(--oid-text-strong)]">
              {variable.label}
            </h1>
            <span className="rounded-full bg-[color:var(--oid-track)] px-2 py-0.5 text-[10.5px] text-[color:var(--oid-text-muted)]">
              {variable.category}
            </span>
          </div>

          <div className="mt-4 flex flex-wrap items-end gap-x-10 gap-y-4">
            <div>
              <div className="text-[10px] font-medium tracking-wide text-[color:var(--oid-text-ghost)] uppercase">
                Current
              </div>
              <div className="mt-1 flex items-baseline gap-1.5">
                <span className="text-[44px] leading-none font-semibold tracking-tight text-[color:var(--oid-text-strong)]">
                  {current?.value != null ? (
                    <AnimatedNumber value={current.value} decimals={2} />
                  ) : (
                    '—'
                  )}
                </span>
                <span className="text-[15px] font-medium text-[color:var(--oid-text-faint)]">
                  {variable.unit}
                </span>
              </div>
            </div>

            <Stat label="Trend">
              <span className="inline-flex items-center gap-1 text-[17px] font-medium">
                <TrendIcon size={16} className="text-[color:var(--oid-accent)]" />
                {forecast?.trend ?? '—'}
              </span>
            </Stat>

            <Stat
              label={horizon ? `Forecast (${horizon}d)` : 'Forecast'}
              hint={
                forecast
                  ? `${forecast.confidence_interval.lower.toFixed(2)} – ${forecast.confidence_interval.upper.toFixed(2)} ${variable.unit}`
                  : undefined
              }
            >
              <span className="text-[17px] font-medium">
                {forecast
                  ? `${forecast.trend_delta >= 0 ? '+' : ''}${forecast.trend_delta.toFixed(2)} ${variable.unit}`
                  : 'Not modelled'}
              </span>
            </Stat>

            <Stat label="Confidence" hint={confidence.detail}>
              <span
                className={cn(
                  'text-[17px] font-medium',
                  confidence.tone === 'strong' && 'text-[color:var(--color-emerald-400)]',
                  confidence.tone === 'fair' && 'text-[color:var(--oid-accent)]',
                  confidence.tone === 'weak' && 'text-[color:var(--color-alert-warning)]'
                )}
              >
                {confidence.word}
              </span>
            </Stat>

            <Stat label="Last updated">
              <span className="inline-flex items-center gap-1.5 text-[17px] font-medium">
                <Clock size={14} className="text-[color:var(--oid-text-ghost)]" />
                {current?.detail && stats
                  ? formatAge(ageSeconds(stats.end))
                  : '—'}
              </span>
            </Stat>
          </div>

          {stats && (
            <p className="mt-4 text-[10.5px] text-[color:var(--oid-text-ghost)]">
              {stats.observation_count.toLocaleString()} observations ·{' '}
              {stats.latitude.toFixed(3)}, {stats.longitude.toFixed(3)} ·{' '}
              {stats.sources.join(' · ')}
            </p>
          )}
        </motion.div>
      </div>
    </Panel>
  );
}

function ageSeconds(isoDate: string): number | null {
  const parsed = Date.parse(`${isoDate}T00:00:00Z`);
  if (Number.isNaN(parsed)) return null;
  return Math.max(0, (Date.now() - parsed) / 1000);
}
