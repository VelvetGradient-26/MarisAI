/** A trained model's full dossier — everything needed to reproduce or audit
 * one (variable, horizon) forecasting artifact, one click from its card on
 * the Data Quality panel.
 *
 * Presentation only, same rule `services/metrics/story.py` and the data
 * quality panel already hold: every figure here is read straight from the
 * artifact's own `metadata.json`/`metrics.json` (via the existing
 * `GET /api/v1/forecast/models/{variable}/{horizon}` endpoint — the same one
 * `Explainability.tsx` already calls through `useModelDetail`), nothing is
 * computed for this page and nothing is invented to fill a gap.
 *
 * **The one gap that has to stay a gap.** The models this page describes are
 * scored against persistence only — no shipped forecasting-engine artifact
 * carries a stored climatology comparison (that baseline exists in
 * `forecasting/evaluator.py` and is used elsewhere, but `train_forecasting.py`
 * never calls it). Rather than omit the row or approximate one, the skill
 * panel states plainly that the comparison was not computed for this model —
 * the same "never substitute a number for missing data" rule the rest of the
 * dashboard holds, applied to an *absent* baseline rather than a stale cache.
 *
 * **The SHAP panel here is the model's global importance, not "drivers of
 * this forecast."** `Explainability.tsx` on the metric page needs a live
 * point to compute per-prediction SHAP; a model dossier has no point to
 * anchor to. `metrics.feature_importance` is a different, already-logged
 * number — mean |SHAP| across the validation rows, computed once at training
 * time by the same `ShapExplainer` (`forecasting/shap_explainer.py`) and
 * saved into the artifact rather than recomputed here.
 */

import { useEffect } from 'react';
import { ChevronRight } from 'lucide-react';
import { Link } from '../../../app/router';
import { useAppRouter } from '../../../app/routerContext';
import { useThemeStore } from '../../../store/themeStore';
import type { FeatureImportance } from './api/types';
import { useForecastCatalog, useModelDetail } from './hooks/useMetricData';
import { Panel, PanelEmpty, PanelHeader, PanelSkeleton } from '../components/Panel';
import { cn } from '../lib/cn';
import '../styles/tailwind.css';

function num(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function str(value: unknown): string | null {
  return typeof value === 'string' && value.length > 0 ? value : null;
}

function fmtSkill(value: number | null): string {
  if (value == null) return '—';
  return value > 0 ? `+${value.toFixed(3)}` : value.toFixed(3);
}

function fmtDate(value: unknown): string {
  const iso = str(value);
  if (!iso) return '—';
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toISOString().slice(0, 10);
}

function Breadcrumb({ variable, horizon }: { variable: string; horizon: number }) {
  const crumb = 'text-[color:var(--oid-text-faint)] no-underline hover:text-[color:var(--oid-accent)]';
  return (
    <nav aria-label="Breadcrumb" className="flex flex-wrap items-center gap-1.5 text-[11.5px]">
      <Link to="/" className={crumb}>
        Home
      </Link>
      <ChevronRight size={12} className="text-[color:var(--oid-text-ghost)]" />
      <Link to="/dashboard" className={crumb}>
        Dashboard
      </Link>
      <ChevronRight size={12} className="text-[color:var(--oid-text-ghost)]" />
      <span className="text-[color:var(--oid-text)]">
        {variable} · +{horizon}d
      </span>
    </nav>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div>
      <dt className="text-[9.5px] tracking-wide text-[color:var(--oid-text-ghost)] uppercase">{label}</dt>
      <dd className="text-[13px] font-medium text-[color:var(--oid-text-strong)]">{value}</dd>
      {hint && <p className="mt-0.5 text-[10px] leading-tight text-[color:var(--oid-text-faint)]">{hint}</p>}
    </div>
  );
}

function Chips({ items }: { items: string[] }) {
  if (items.length === 0) {
    return <p className="text-[11px] text-[color:var(--oid-text-faint)]">None recorded.</p>;
  }
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((item) => (
        <span
          key={item}
          className="rounded-md border border-[color:var(--oid-border)] bg-[color:var(--oid-elevated)] px-1.5 py-0.5 font-mono text-[10px] text-[color:var(--oid-text-muted)]"
        >
          {item}
        </span>
      ))}
    </div>
  );
}

function FoldTable({ folds }: { folds: Record<string, unknown>[] }) {
  if (folds.length === 0) {
    return <p className="text-[11px] text-[color:var(--oid-text-faint)]">No fold-level scores recorded.</p>;
  }
  return (
    <div className="oid-scroll overflow-x-auto">
      <table className="w-full min-w-[420px] border-collapse text-[11px]">
        <thead>
          <tr className="border-b border-[color:var(--oid-border)] text-left text-[9.5px] tracking-wide text-[color:var(--oid-text-ghost)] uppercase">
            <th className="py-1.5 pr-3 font-medium">Fold</th>
            <th className="py-1.5 pr-3 font-medium">Skill</th>
            <th className="py-1.5 pr-3 font-medium">RMSE</th>
            <th className="py-1.5 pr-3 font-medium">MAE</th>
            <th className="py-1.5 font-medium">Rows</th>
          </tr>
        </thead>
        <tbody>
          {folds.map((fold, index) => {
            const skill = num(fold.skill_score);
            return (
              <tr
                key={str(fold.fold) ?? index}
                className="border-b border-[color:var(--oid-border)] last:border-0"
              >
                <td className="py-1.5 pr-3 font-mono text-[10px] text-[color:var(--oid-text-muted)]">
                  {str(fold.fold) ?? `fold ${index + 1}`}
                </td>
                <td
                  className={cn(
                    'py-1.5 pr-3 font-medium',
                    skill != null && skill <= 0
                      ? 'text-[color:var(--color-alert-critical)]'
                      : 'text-[color:var(--oid-text-strong)]'
                  )}
                >
                  {fmtSkill(skill)}
                </td>
                <td className="py-1.5 pr-3 text-[color:var(--oid-text-muted)]">
                  {num(fold.rmse)?.toFixed(3) ?? '—'}
                </td>
                <td className="py-1.5 pr-3 text-[color:var(--oid-text-muted)]">
                  {num(fold.mae)?.toFixed(3) ?? '—'}
                </td>
                <td className="py-1.5 text-[color:var(--oid-text-muted)]">{num(fold.n) ?? '—'}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function ImportanceBars({ importance }: { importance: FeatureImportance[] }) {
  if (importance.length === 0) {
    return (
      <p className="text-[11px] text-[color:var(--oid-text-faint)]">
        No global importance ranking was stored for this model.
      </p>
    );
  }
  const max = Math.max(...importance.map((entry) => Math.abs(entry.importance)), 1e-9);
  return (
    <ul className="space-y-2">
      {importance.map((entry) => (
        <li key={entry.feature}>
          <div className="flex items-baseline justify-between gap-2 text-[11px]">
            <span className="truncate text-[color:var(--oid-text)]" title={entry.feature}>
              {entry.label}
            </span>
            <span className="shrink-0 font-mono text-[10px] text-[color:var(--oid-text-faint)]">
              {entry.importance.toFixed(4)}
            </span>
          </div>
          <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-[color:var(--oid-track)]">
            <div
              className="h-full rounded-full bg-[color:var(--oid-accent)]"
              style={{ width: `${(Math.abs(entry.importance) / max) * 100}%` }}
            />
          </div>
        </li>
      ))}
    </ul>
  );
}

export function ModelDossierPage() {
  const { searchParams } = useAppRouter();
  const isDark = useThemeStore((state) => state.dark);

  const variable = searchParams.get('variable') ?? '';
  const horizon = Number(searchParams.get('horizon'));
  const validRequest = variable.length > 0 && Number.isFinite(horizon);

  const { data: catalog } = useForecastCatalog();
  const catalogEntry = catalog?.variables.find((entry) => entry.key === variable);

  const {
    data: model,
    isPending,
    isError,
    error,
    refetch,
  } = useModelDetail({ variable, horizon, enabled: validRequest });

  useEffect(() => {
    document.title = validRequest
      ? `${catalogEntry?.label ?? variable} +${horizon}d model | Maris AI`
      : 'Model dossier | Maris AI';
  }, [validRequest, catalogEntry, variable, horizon]);

  const metadata = model?.metadata;
  const validation = model?.metrics.validation;
  const skill = num(validation?.metrics?.skill_score);
  const folds = (validation?.folds ?? []) as Record<string, unknown>[];
  const trainingPoints = Array.isArray(metadata?.training_points) ? metadata.training_points.map(String) : [];
  const skippedPoints = Array.isArray(metadata?.skipped_points) ? metadata.skipped_points.map(String) : [];
  const covariates = Array.isArray(metadata?.covariates) ? metadata.covariates.map(String) : [];

  return (
    <div
      className={cn('oid-root min-h-screen bg-[image:var(--oid-page)]', !isDark && 'oid-root--light')}
      data-theme={isDark ? 'dark' : 'light'}
    >
      <main
        className="mx-auto max-w-[1100px] px-3 pb-16 sm:px-5"
        style={{ paddingTop: 'calc(var(--navbar-h, 64px) + 16px)' }}
      >
        <Breadcrumb
          variable={catalogEntry?.label ?? (variable || '—')}
          horizon={Number.isFinite(horizon) ? horizon : 0}
        />

        {!validRequest ? (
          <Panel className="mt-4">
            <PanelEmpty
              title="No model specified"
              reason="This page needs a ?variable= and ?horizon= — open it from a card on the Data Quality panel."
            />
          </Panel>
        ) : (
          <>
            <header className="mt-3 mb-5">
              <h1 className="text-[22px] leading-none font-semibold tracking-tight text-[color:var(--oid-text-strong)]">
                {catalogEntry?.label ?? variable}
              </h1>
              <p className="mt-1.5 text-[11.5px] text-[color:var(--oid-text-faint)]">
                Forecast horizon +{horizon} days · full training and validation record for this artifact
              </p>
            </header>

            {isPending && (
              <Panel>
                <PanelSkeleton rows={6} />
              </Panel>
            )}

            {isError && (
              <Panel>
                <PanelEmpty
                  title="Model unavailable"
                  reason={error instanceof Error ? error.message : undefined}
                  onRetry={() => void refetch()}
                />
              </Panel>
            )}

            {model && (
              <div className="grid grid-cols-1 gap-4">
                <Panel>
                  <PanelHeader title="Training" subtitle="What produced this artifact" />
                  <div className="grid grid-cols-2 gap-4 p-4 sm:grid-cols-4">
                    <Stat label="Algorithm" value={str(metadata?.model_type) ?? '—'} />
                    <Stat
                      label="Target"
                      value={str(metadata?.target_mode) ?? '—'}
                      hint={
                        metadata?.target_mode === 'delta'
                          ? 'Predicts the change from the latest observation, not the absolute level.'
                          : metadata?.target_mode === 'level'
                            ? 'Predicts the absolute level directly.'
                            : undefined
                      }
                    />
                    <Stat label="Training rows" value={(metadata?.training_rows ?? 0).toLocaleString()} />
                    <Stat
                      label="Features"
                      value={String(model.feature_columns.length)}
                      hint={`${covariates.length} covariate${covariates.length === 1 ? '' : 's'}`}
                    />
                    <Stat
                      label="Data window"
                      value={`${fmtDate(metadata?.training_started)} → ${fmtDate(metadata?.training_ended)}`}
                    />
                    <Stat label="Trained on" value={fmtDate(metadata?.trained_at)} />
                    <Stat
                      label="Points used"
                      value={String(trainingPoints.length)}
                      hint={skippedPoints.length > 0 ? `${skippedPoints.length} skipped` : undefined}
                    />
                    <Stat label="Validation" value="rolling-origin CV" hint={`${folds.length} folds`} />
                  </div>
                  {(trainingPoints.length > 0 || covariates.length > 0) && (
                    <div className="grid grid-cols-1 gap-4 border-t border-[color:var(--oid-border)] p-4 sm:grid-cols-2">
                      {trainingPoints.length > 0 && (
                        <div>
                          <h3 className="mb-2 text-[10.5px] font-medium tracking-wide text-[color:var(--oid-text-muted)] uppercase">
                            Trained on
                          </h3>
                          <Chips items={trainingPoints} />
                        </div>
                      )}
                      {covariates.length > 0 && (
                        <div>
                          <h3 className="mb-2 text-[10.5px] font-medium tracking-wide text-[color:var(--oid-text-muted)] uppercase">
                            Covariates
                          </h3>
                          <Chips items={covariates} />
                        </div>
                      )}
                    </div>
                  )}
                </Panel>

                <Panel>
                  <PanelHeader title="Skill" subtitle="Out-of-sample, rolling-origin cross-validation" />
                  <div className="grid grid-cols-1 gap-4 p-4 sm:grid-cols-2">
                    <div>
                      <Stat
                        label="Skill vs persistence"
                        value={fmtSkill(skill)}
                        hint="Positive beats the naive 'tomorrow = today' baseline."
                      />
                      <p className="mt-3 text-[11px] leading-relaxed text-[color:var(--oid-text-faint)]">
                        <strong className="text-[color:var(--oid-text-muted)]">Skill vs climatology:</strong> not
                        computed for this model. The forecasting engine's models are only scored against
                        persistence — a day-of-year climatology baseline is not wired into this pipeline's
                        training run, so there is no number to show here rather than an approximated one.
                      </p>
                    </div>
                    <div>
                      <h3 className="mb-2 text-[10.5px] font-medium tracking-wide text-[color:var(--oid-text-muted)] uppercase">
                        Fold scores
                      </h3>
                      <FoldTable folds={folds} />
                    </div>
                  </div>
                </Panel>

                <Panel>
                  <PanelHeader
                    title="Global feature importance"
                    subtitle="Mean |SHAP| across the validation rows, computed once at training time"
                  />
                  <div className="p-4">
                    <ImportanceBars importance={model.metrics.feature_importance ?? []} />
                  </div>
                </Panel>

                <Panel>
                  <PanelHeader
                    title="Feature columns"
                    subtitle={`All ${model.feature_columns.length} inputs the trained model reads`}
                  />
                  <div className="max-h-64 overflow-y-auto p-4">
                    <Chips items={model.feature_columns} />
                  </div>
                </Panel>
              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
}
