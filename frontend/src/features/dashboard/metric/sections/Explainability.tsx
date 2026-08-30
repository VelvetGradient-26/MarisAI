/** Explainability: what drove this forecast, and how good the model is.
 *
 * Two different questions, deliberately shown together because either alone
 * misleads. The SHAP bars say which features moved *this* prediction; the
 * evaluation panel says whether the model making it is worth listening to. A
 * confident attribution from a model that cannot beat persistence is a
 * decorated guess, and the skill score is what exposes that.
 */

import { useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import { Brain } from 'lucide-react';
import type { SectionProps } from '../sections';
import { isForecastError } from '../api/types';
import { useBatchForecast, useModelDetail } from '../hooks/useMetricData';
import { Panel, PanelEmpty, PanelHeader, PanelSkeleton } from '../../components/Panel';
import { cn } from '../../lib/cn';

function Metric({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: 'good' | 'bad';
}) {
  return (
    <div className="rounded-lg border border-[color:var(--oid-border)] bg-[color:var(--oid-elevated)] p-2.5">
      <div className="text-[length:var(--oid-text-3xs)] tracking-wide text-[color:var(--oid-text-ghost)] uppercase">
        {label}
      </div>
      <div
        className={cn(
          'mt-1 text-[15px] font-semibold text-[color:var(--oid-text-strong)]',
          tone === 'good' && 'text-[color:var(--color-emerald-400)]',
          tone === 'bad' && 'text-[color:var(--color-alert-warning)]'
        )}
      >
        {value}
      </div>
      {hint && (
        <div className="mt-0.5 text-[length:var(--oid-text-3xs)] text-[color:var(--oid-text-ghost)]">{hint}</div>
      )}
    </div>
  );
}

export function Explainability({ variable, latitude, longitude }: SectionProps) {
  const horizons = variable.trained_horizons;
  const [horizon, setHorizon] = useState(
    () => (horizons.includes(7) ? 7 : horizons[0]) ?? 7
  );

  const { data: batch } = useBatchForecast({
    variable: variable.key,
    latitude,
    longitude,
    horizons: [horizon],
  });
  const { data: model, isPending, isError, error, refetch } = useModelDetail({
    variable: variable.key,
    horizon,
  });

  const entry = batch?.forecasts?.[String(horizon)];
  const forecast = entry && !isForecastError(entry) ? entry : null;

  /** Local drivers, normalised to a share of total absolute contribution so
   *  the bars read as "how much of the movement" rather than raw SHAP units. */
  const drivers = useMemo(() => {
    if (!forecast?.top_features?.length) return [];
    const total = forecast.top_features.reduce(
      (acc, feature) => acc + Math.abs(feature.contribution),
      0
    );
    if (total === 0) return [];
    return forecast.top_features.map((feature) => ({
      ...feature,
      share: Math.abs(feature.contribution) / total,
    }));
  }, [forecast]);

  const evaluation = model?.metrics?.validation?.metrics;
  const skill = evaluation?.skill_score;

  return (
    <Panel>
      <PanelHeader
        icon={<Brain size={14} />}
        title="Explainability"
        subtitle="Which inputs moved this forecast, and how the model scores out of sample"
        actions={
          horizons.length > 1 ? (
            <div className="flex gap-1">
              {horizons.map((option) => (
                <button
                  key={option}
                  type="button"
                  onClick={() => setHorizon(option)}
                  className={cn(
                    'rounded-full px-2 py-0.5 text-[length:var(--oid-text-3xs)] transition-colors',
                    horizon === option
                      ? 'bg-[color:var(--oid-accent-wash-strong)] text-[color:var(--oid-accent)]'
                      : 'text-[color:var(--oid-text-faint)] hover:bg-[color:var(--oid-track)]'
                  )}
                >
                  {option}d
                </button>
              ))}
            </div>
          ) : null
        }
      />

      {isPending && <PanelSkeleton rows={4} />}

      {isError && (
        <PanelEmpty
          title="Model details unavailable"
          reason={error instanceof Error ? error.message : undefined}
          onRetry={() => void refetch()}
        />
      )}

      {model && (
        <div className="grid grid-cols-1 gap-4 p-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
          <div>
            <h3 className="text-[length:var(--oid-text-xs)] font-medium tracking-wide text-[color:var(--oid-text-muted)] uppercase">
              Drivers of this forecast
            </h3>

            {drivers.length === 0 ? (
              <p className="mt-3 text-[length:var(--oid-text-sm)] text-[color:var(--oid-text-faint)]">
                Attribution is not available for this prediction.
              </p>
            ) : (
              <ul className="mt-3 space-y-2.5">
                {drivers.map((driver, index) => (
                  <li key={driver.feature}>
                    <div className="flex items-baseline justify-between gap-2 text-[length:var(--oid-text-sm)]">
                      <span className="truncate text-[color:var(--oid-text)]" title={driver.feature}>
                        {driver.label}
                      </span>
                      <span
                        className={cn(
                          'shrink-0 font-mono text-[length:var(--oid-text-2xs)]',
                          driver.direction === 'increases'
                            ? 'text-[color:var(--color-alert-warning)]'
                            : 'text-[color:var(--oid-accent)]'
                        )}
                      >
                        {(driver.share * 100).toFixed(0)}%{' '}
                        {driver.direction === 'increases' ? '↑' : '↓'}
                      </span>
                    </div>
                    <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-[color:var(--oid-track)]">
                      <motion.div
                        initial={{ width: 0 }}
                        animate={{ width: `${driver.share * 100}%` }}
                        transition={{ delay: index * 0.06, duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
                        className={cn(
                          'h-full rounded-full',
                          driver.direction === 'increases'
                            ? 'bg-[color:var(--color-alert-warning)]'
                            : 'bg-[color:var(--oid-accent)]'
                        )}
                      />
                    </div>
                  </li>
                ))}
              </ul>
            )}

            <p className="mt-3 text-[length:var(--oid-text-3xs)] leading-relaxed text-[color:var(--oid-text-ghost)]">
              Shares are SHAP contributions to this specific prediction, normalised across the
              features shown. An arrow says which way that feature pushed the forecast, not
              whether it is good.
            </p>
          </div>

          <div>
            <h3 className="text-[length:var(--oid-text-xs)] font-medium tracking-wide text-[color:var(--oid-text-muted)] uppercase">
              Model performance
            </h3>
            <div className="mt-3 grid grid-cols-2 gap-2">
              <Metric
                label="MAE"
                value={fmt(evaluation?.mae, variable.unit)}
                hint="mean absolute error"
              />
              <Metric
                label="RMSE"
                value={fmt(evaluation?.rmse, variable.unit)}
                hint="root mean squared error"
              />
              <Metric label="R²" value={fmt(evaluation?.r2)} hint="variance explained" />
              <Metric
                label="Skill"
                value={
                  skill != null ? `${skill > 0 ? '+' : ''}${(skill * 100).toFixed(0)}%` : '—'
                }
                hint="vs persistence"
                tone={skill != null ? (skill > 0 ? 'good' : 'bad') : undefined}
              />
            </div>

            <dl className="mt-3 space-y-1 text-[length:var(--oid-text-2xs)] text-[color:var(--oid-text-ghost)]">
              <Row term="Model" value={String(model.metadata.model_type ?? '—')} />
              <Row term="Validation" value="rolling-origin CV" />
              <Row
                term="Training rows"
                value={(model.metadata.training_rows ?? 0).toLocaleString()}
              />
              <Row
                term="Locations"
                value={String(model.metadata.training_points?.length ?? '—')}
              />
              <Row
                term="Trained"
                value={
                  model.metadata.trained_at
                    ? new Date(model.metadata.trained_at).toISOString().slice(0, 10)
                    : '—'
                }
              />
            </dl>
          </div>
        </div>
      )}
    </Panel>
  );
}

function Row({ term, value }: { term: string; value: string }) {
  return (
    <div className="flex justify-between gap-2">
      <dt>{term}</dt>
      <dd className="truncate text-[color:var(--oid-text-muted)]">{value}</dd>
    </div>
  );
}

function fmt(value: number | null | undefined, unit?: string): string {
  if (value == null || !Number.isFinite(value)) return '—';
  return `${value.toFixed(3)}${unit ? ` ${unit}` : ''}`;
}
