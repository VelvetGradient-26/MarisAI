/** The hero: current value, trend, forecast, confidence, freshness.
 *
 * The five things a reader wants before they decide whether to scroll. Each is
 * sourced, not inferred: the current value and timestamp come from the record,
 * the forecast and its interval from a trained model, and "confidence" is a
 * plain-language rendering of that model's out-of-sample skill rather than a
 * word chosen for effect.
 */

import { motion } from 'framer-motion';
import { ArrowDownRight, ArrowRight, ArrowUpRight, Clock, Loader2 } from 'lucide-react';
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

/** A value that is still being computed.
 *
 * Deliberately a moving mark rather than an em dash or a placeholder number.
 * The hero's numbers can take ~30s to arrive on a cold point (the upstream
 * history fetch, not inference), and a static "—" for half a minute is
 * indistinguishable from "there is nothing here".
 */
function Pending({ width = 56, label }: { width?: number; label: string }) {
  return (
    <span
      className="inline-flex items-center gap-1.5 align-middle"
      role="status"
      aria-label={label}
    >
      <span
        aria-hidden="true"
        className="block h-[1.05em] animate-pulse rounded bg-[color:var(--oid-track)]"
        style={{ width }}
      />
      <Loader2
        size={13}
        aria-hidden="true"
        className="animate-spin text-[color:var(--oid-text-ghost)]"
      />
    </span>
  );
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
  const {
    data: stats,
    isPending: statsPending,
    isError: statsFailed,
  } = useMetricStatistics({
    variable: variable.key,
    latitude,
    longitude,
    range: '1y',
  });

  const horizon = variable.trained_horizons.includes(7)
    ? 7
    : (variable.trained_horizons[0] ?? null);

  const {
    data: batch,
    isPending: forecastPending,
    isError: forecastFailed,
  } = useBatchForecast({
    variable: variable.key,
    latitude,
    longitude,
    horizons: horizon ? [horizon] : [],
    enabled: horizon != null,
  });

  const entry = horizon != null ? batch?.forecasts?.[String(horizon)] : undefined;
  const forecast = entry && !isForecastError(entry) ? entry : null;

  // Why the forecast is absent, which is four different facts that used to
  // render as the single word "Not modelled" — including the two that are not
  // true. A cold point costs ~30s of upstream history fetching before any
  // model runs, so `pending` is the *common* case on first load, and a
  // restarted or unreachable backend produces `failed`. Stating either as
  // "not modelled" asserts something false about the platform.
  // `rejected` is the backend answering with a per-horizon error (it reached
  // the model and could not serve it); `failed` is not reaching the backend at
  // all. They read the same to a user but not to whoever is debugging.
  const forecastState: 'ready' | 'untrained' | 'pending' | 'failed' | 'rejected' = forecast
    ? 'ready'
    : horizon == null
      ? 'untrained'
      : forecastPending
        ? 'pending'
        : forecastFailed
          ? 'failed'
          : 'rejected';

  const forecastProblem =
    entry && isForecastError(entry)
      ? entry.error
      : forecastState === 'failed'
        ? 'could not reach the forecasting service'
        : null;

  const current = stats?.statistics.find((item) => item.key === 'current');
  // Only a served model can rate itself. While one is still being computed the
  // absence of a skill score is not "unrated" — it is not yet known.
  const confidence =
    forecastState === 'pending'
      ? { word: 'Computing', tone: 'unknown' as const, detail: 'awaiting model skill score' }
      : confidenceFrom(forecast?.evaluation.skill_score);

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
                  ) : statsPending ? (
                    <Pending width={120} label={`Loading current ${variable.label}`} />
                  ) : (
                    <span
                      className={cn(
                        'text-[20px]',
                        statsFailed && 'text-[color:var(--color-alert-warning)]'
                      )}
                    >
                      {statsFailed ? 'Unavailable' : '—'}
                    </span>
                  )}
                </span>
                <span className="text-[15px] font-medium text-[color:var(--oid-text-faint)]">
                  {variable.unit}
                </span>
              </div>
            </div>

            <Stat label="Trend">
              <span className="inline-flex items-center gap-1 text-[17px] font-medium">
                {forecastState === 'pending' ? (
                  <Pending label={`Loading ${variable.label} trend`} />
                ) : (
                  <>
                    <TrendIcon size={16} className="text-[color:var(--oid-accent)]" />
                    {forecast?.trend ?? '—'}
                  </>
                )}
              </span>
            </Stat>

            <Stat
              label={horizon ? `Forecast (${horizon}d)` : 'Forecast'}
              hint={
                forecastState === 'ready' && forecast
                  ? `${forecast.confidence_interval.lower.toFixed(2)} – ${forecast.confidence_interval.upper.toFixed(2)} ${variable.unit}`
                  : forecastState === 'pending'
                    ? 'fetching upstream history'
                    : (forecastProblem ?? variable.unavailable_reason ?? undefined)
              }
            >
              <span
                className={cn(
                  'text-[17px] font-medium',
                  (forecastState === 'failed' || forecastState === 'rejected') &&
                    'text-[color:var(--color-alert-warning)]'
                )}
              >
                {forecastState === 'ready' && forecast
                  ? `${forecast.trend_delta >= 0 ? '+' : ''}${forecast.trend_delta.toFixed(2)} ${variable.unit}`
                  : forecastState === 'pending'
                    ? <Pending label={`Computing ${variable.label} forecast`} />
                    : forecastState === 'untrained'
                      ? 'Not modelled'
                      : 'Unavailable'}
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
                {statsPending ? (
                  <Pending label="Loading last updated time" />
                ) : (
                  <>
                    <Clock size={14} className="text-[color:var(--oid-text-ghost)]" />
                    {current?.detail && stats ? formatAge(ageSeconds(stats.end)) : '—'}
                  </>
                )}
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
