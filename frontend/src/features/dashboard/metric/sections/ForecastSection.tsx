/** Forecast: recent history, the predicted path, and its confidence band.
 *
 * The band is the point of the section. A forecast curve without one invites
 * the reader to treat a single number as fact, and for a chaotic system that
 * is not a stylistic complaint — "+0.4 °C in 30 days" and "+0.4, 95% interval
 * −1.2 to +2.0" support completely different decisions.
 *
 * Observed and forecast are drawn as two series so the forecast can be dashed
 * and the join marked, rather than one continuous line that quietly changes
 * meaning halfway along.
 */

import { useMemo, useState } from 'react';
import { LineChart } from 'lucide-react';
import type { SectionProps } from '../sections';
import { isForecastError } from '../api/types';
import { useBatchForecast } from '../hooks/useMetricData';
import { SeriesChart } from '../components/SeriesChart';
import { Panel, PanelEmpty, PanelHeader, PanelSkeleton } from '../../components/Panel';
import { cn } from '../../lib/cn';

const CHART_HEIGHT = 300;
const CHART_RESERVE = CHART_HEIGHT + 56;

export function ForecastSection({ variable, latitude, longitude }: SectionProps) {
  const horizons = variable.trained_horizons;
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  const { data, isPending, isError, error, refetch } = useBatchForecast({
    variable: variable.key,
    latitude,
    longitude,
    horizons,
  });

  const chart = useMemo(() => {
    if (!data) return null;

    const entries = horizons
      .map((horizon) => data.forecasts[String(horizon)])
      .filter((entry) => entry && !isForecastError(entry));
    if (entries.length === 0) return null;

    // Every horizon shares the same history, and the batch endpoint sends it
    // only on the first, so take it from whichever entry carries it.
    const withHistory = entries.find(
      (entry) => !isForecastError(entry) && entry.history.length > 0
    );
    const history =
      withHistory && !isForecastError(withHistory) ? withHistory.history : [];

    const historyX = history.map((point) => Date.parse(point.t) / 1000);
    const historyY = history.map((point) => point.v);

    const points = entries
      .filter((entry) => !isForecastError(entry))
      .map((entry) => ({
        t: Date.parse((entry as { target_time: string }).target_time) / 1000,
        entry: entry as Exclude<typeof entry, { error: string }>,
      }))
      .sort((a, b) => a.t - b.t);

    const x = [...historyX, ...points.map((p) => p.t)];

    // The forecast series starts with the last observation so the dashed line
    // joins the solid one instead of floating detached from it.
    const lastObserved = historyY.at(-1) ?? null;
    const observed: (number | null)[] = [...historyY, ...points.map(() => null)];
    const predicted: (number | null)[] = [
      ...historyY.map((_, index) => (index === historyY.length - 1 ? lastObserved : null)),
      ...points.map((p) => p.entry.prediction),
    ];

    const lower: (number | null)[] = [
      ...historyY.map((_, index) => (index === historyY.length - 1 ? lastObserved : null)),
      ...points.map((p) => p.entry.confidence_interval.lower),
    ];
    const upper: (number | null)[] = [
      ...historyY.map((_, index) => (index === historyY.length - 1 ? lastObserved : null)),
      ...points.map((p) => p.entry.confidence_interval.upper),
    ];

    return {
      x,
      observed,
      predicted,
      lower,
      upper,
      points,
      forecastFrom: historyX.at(-1) ?? null,
      evaluation: points[0]?.entry.evaluation,
    };
  }, [data, horizons]);

  const hovered =
    chart && hoverIndex != null
      ? {
          time: chart.x[hoverIndex],
          observed: chart.observed[hoverIndex],
          predicted: chart.predicted[hoverIndex],
          lower: chart.lower[hoverIndex],
          upper: chart.upper[hoverIndex],
        }
      : null;

  return (
    <Panel>
      <PanelHeader
        icon={<LineChart size={14} />}
        title="Forecast"
        subtitle={
          chart?.evaluation
            ? `LightGBM · rolling-origin validated · RMSE ${chart.evaluation.RMSE?.toFixed(3) ?? '—'} ${variable.unit}`
            : 'Predicted path with a 95% interval'
        }
        actions={
          <span className="text-[10px] text-[color:var(--oid-text-ghost)]">
            {horizons.map((h) => `${h}d`).join(' · ')}
          </span>
        }
      />

      {/* Reserved on the loading state only. "No model trained" is a permanent
          answer, not a gap where a chart will appear, so padding it to chart
          height would be reserving room for something that is never coming. */}
      {isPending && (
        <div className="oid-swap-in" style={{ minHeight: CHART_RESERVE }}>
          <PanelSkeleton rows={4} />
        </div>
      )}

      {isError && (
        <PanelEmpty
          className="oid-swap-in"
          title="Forecast unavailable"
          reason={error instanceof Error ? error.message : undefined}
          onRetry={() => void refetch()}
        />
      )}

      {data && !chart && (
        <PanelEmpty
          className="oid-swap-in"
          title="No forecast for this variable"
          reason={`No model has been trained for ${variable.label} yet.`}
        />
      )}

      {chart && (
        <div className="oid-swap-in p-4">
          <SeriesChart
            x={chart.x}
            unit={variable.unit}
            height={CHART_HEIGHT}
            forecastFrom={chart.forecastFrom}
            onHover={setHoverIndex}
            band={{ lower: chart.lower, upper: chart.upper, label: '95% interval' }}
            series={[
              { label: 'Observed', values: chart.observed },
              { label: 'Forecast', values: chart.predicted, dashed: true },
            ]}
          />

          <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-2 text-[11px]">
            <Legend swatchClass="bg-[color:var(--oid-accent)]" label="Observed" />
            <Legend swatchClass="bg-[color:var(--oid-accent-soft)]" label="Forecast" dashed />
            <Legend
              swatchClass="bg-[color:var(--oid-accent)] opacity-25"
              label="95% confidence interval"
            />
            {hovered?.time != null && (
              <span className="ml-auto font-mono text-[10.5px] text-[color:var(--oid-text-muted)]">
                {new Date(hovered.time * 1000).toISOString().slice(0, 10)} ·{' '}
                {hovered.observed != null
                  ? `${hovered.observed.toFixed(2)} ${variable.unit}`
                  : hovered.predicted != null
                    ? `${hovered.predicted.toFixed(2)} (${hovered.lower?.toFixed(2)}–${hovered.upper?.toFixed(2)}) ${variable.unit}`
                    : '—'}
              </span>
            )}
          </div>

          <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
            {chart.points.map(({ entry }) => (
              <div
                key={entry.forecast_horizon}
                className={cn(
                  'rounded-lg border p-2.5',
                  'border-[color:var(--oid-border)] bg-[color:var(--oid-elevated)]'
                )}
              >
                <div className="text-[10px] tracking-wide text-[color:var(--oid-text-ghost)] uppercase">
                  {entry.forecast_horizon} day{entry.forecast_horizon === 1 ? '' : 's'}
                </div>
                <div className="mt-1 text-[16px] font-semibold text-[color:var(--oid-text-strong)]">
                  {entry.prediction.toFixed(2)}
                  <span className="ml-1 text-[10px] font-medium text-[color:var(--oid-text-faint)]">
                    {variable.unit}
                  </span>
                </div>
                <div className="mt-0.5 text-[10px] text-[color:var(--oid-text-ghost)]">
                  {entry.confidence_interval.lower.toFixed(2)} –{' '}
                  {entry.confidence_interval.upper.toFixed(2)}
                </div>
              </div>
            ))}
          </div>

          <p className="mt-3 text-[10px] leading-relaxed text-[color:var(--oid-text-ghost)]">
            Intervals are bootstrapped from the model&apos;s out-of-sample residuals at each
            horizon, so they reflect error it actually made on data it had not seen. This is a
            statistical forecast, not an official marine warning, and is not suitable for
            navigation.
          </p>
        </div>
      )}
    </Panel>
  );
}

function Legend({
  swatchClass,
  label,
  dashed,
}: {
  swatchClass: string;
  label: string;
  dashed?: boolean;
}) {
  return (
    <span className="inline-flex items-center gap-1.5 text-[color:var(--oid-text-muted)]">
      <span
        className={cn('inline-block h-0.5 w-5 rounded-full', swatchClass)}
        style={dashed ? { backgroundImage: 'none', opacity: 0.85 } : undefined}
      />
      {label}
    </span>
  );
}
