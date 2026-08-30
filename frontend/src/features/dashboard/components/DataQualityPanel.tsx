/** Data quality observatory — what the platform holds, and how good it is.
 *
 * `HealthPanel` answers "is the feed up right now". This answers the question
 * underneath it: what the datasets *are* (resolution, cadence, coverage,
 * licence), how far each stage of the pipeline actually reaches, and how well
 * every trained model scores.
 *
 * Two presentation rules carried over from the backend, both load-bearing:
 *
 * - **A model's grade comes from its folds, not its headline.** The shipping
 *   bar is skill > 0 *and* at most one of five folds negative; six rejected
 *   horizons printed "beats persistence" on the aggregate alone. So the fold
 *   spread is rendered beside every skill score rather than tucked away, and
 *   the grade chip reads the same rule the backend graded on.
 * - **Never invent a confidence percentage.** The panel shows skill against
 *   persistence and the fold range, which are measured. A single "91%
 *   confident" figure would be a number nothing computed.
 */

import { useMemo, useState } from 'react';
import { Database } from 'lucide-react';
import { Link } from '../../../app/router';
import type { DatasetEntry, ModelEntry, ModelGrade } from '../api/types';
import { useDataQuality } from '../hooks/useDashboardData';
import { cn } from '../lib/cn';
import { Panel, PanelEmpty, PanelHeader, PanelSkeleton } from './Panel';

const GRADE_STYLES: Record<ModelGrade, { label: string; chip: string }> = {
  strong: {
    label: 'Strong',
    chip: 'text-[color:var(--color-emerald-400)] border-[color:var(--color-emerald-400)]',
  },
  good: {
    label: 'Good',
    chip: 'text-[color:var(--oid-accent)] border-[color:var(--oid-accent)]',
  },
  // Beats persistence on the mean while a minority of folds carry it — the
  // case the aggregate hides, so it is called out rather than blended in.
  fair: {
    label: 'Fold-limited',
    chip: 'text-[color:var(--color-alert-warning)] border-[color:var(--color-alert-warning)]',
  },
  poor: {
    label: 'Below persistence',
    chip: 'text-[color:var(--color-alert-critical)] border-[color:var(--color-alert-critical)]',
  },
  unknown: {
    label: 'Unscored',
    chip: 'text-[color:var(--oid-text-muted)] border-[color:var(--oid-border)]',
  },
};

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div>
      <dt className="text-[length:var(--oid-text-5xs)] tracking-wide text-[color:var(--oid-text-ghost)] uppercase">{label}</dt>
      <dd className="text-[length:var(--oid-text-lg)] font-medium text-[color:var(--oid-text-strong)]">{value}</dd>
      {hint && <p className="text-[length:var(--oid-text-4xs)] leading-tight text-[color:var(--oid-text-faint)]">{hint}</p>}
    </div>
  );
}

function DatasetRow({ dataset }: { dataset: DatasetEntry }) {
  const coverage = dataset.coverage_start
    ? `from ${dataset.coverage_start}`
    : dataset.time_varying
      ? 'no lower bound'
      : 'time-invariant';

  return (
    <li className="rounded-xl border border-[color:var(--oid-border)] bg-[color:var(--oid-elevated)] p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h4 className="truncate text-[length:var(--oid-text-base)] font-medium text-[color:var(--oid-text-strong)]">
            {dataset.source_label}
          </h4>
          <p className="mt-0.5 font-mono text-[length:var(--oid-text-4xs)] text-[color:var(--oid-text-faint)]">{dataset.key}</p>
        </div>
        <span className="shrink-0 text-[length:var(--oid-text-3xs)] text-[color:var(--oid-text-muted)]">
          {dataset.variable_count} var{dataset.variable_count === 1 ? '' : 's'}
        </span>
      </div>

      <dl className="mt-2.5 grid grid-cols-3 gap-2">
        <Stat label="Grid" value={`${dataset.grid_spacing_deg}°`} />
        <Stat label="Cadence" value={dataset.cadence} />
        <Stat label="Coverage" value={coverage} />
      </dl>

      <p className="mt-2 truncate text-[length:var(--oid-text-4xs)] text-[color:var(--oid-text-ghost)]" title={dataset.licence}>
        {dataset.licence}
      </p>

      {/* Most datasets are fetched per request and hold no warm copy. Saying
          so is very different from reporting them as down. */}
      {dataset.cache.health === 'not_cached' ? (
        <p className="mt-1.5 text-[length:var(--oid-text-4xs)] text-[color:var(--oid-text-faint)]">
          {dataset.cache.unavailable_reason}
        </p>
      ) : (
        <p className="mt-1.5 text-[length:var(--oid-text-4xs)] text-[color:var(--oid-text-faint)]">
          Live cache: {dataset.cache.health}
          {dataset.cache.unavailable_reason ? ` — ${dataset.cache.unavailable_reason}` : ''}
        </p>
      )}
    </li>
  );
}

/** Every model card opens its full dossier — reproducibility detail that
 * does not fit a grid card (training points, feature list, CV folds, global
 * SHAP importance). Wrapping even an `available: false` card is deliberate:
 * that state means an artifact exists on disk but failed to read, and the
 * dossier's own error state (same `useModelDetail` query) reports the real
 * reason rather than this card repeating a truncated one. */
function ModelRow({ model }: { model: ModelEntry }) {
  const href = `/dashboard/model?variable=${encodeURIComponent(model.variable)}&horizon=${model.horizon}`;

  if (!model.available) {
    return (
      <li>
        <Link
          to={href}
          className="block rounded-lg border border-[color:var(--color-alert-critical)] p-2.5 no-underline transition-colors hover:bg-[color:var(--oid-elevated)]"
        >
          <p className="text-[length:var(--oid-text-xs)] font-medium text-[color:var(--oid-text-strong)]">
            {model.variable} · h{model.horizon}
          </p>
          <p className="mt-1 text-[length:var(--oid-text-4xs)] text-[color:var(--color-alert-critical)]">
            {model.unavailable_reason}
          </p>
        </Link>
      </li>
    );
  }

  const grade = GRADE_STYLES[model.grade ?? 'unknown'];
  const skill = model.skill_score;
  const spread =
    model.fold_skill_min != null && model.fold_skill_max != null
      ? `${model.fold_skill_min.toFixed(2)} … ${model.fold_skill_max.toFixed(2)}`
      : '—';

  return (
    <li>
      <Link
        to={href}
        className="group block rounded-lg border border-[color:var(--oid-border)] bg-[color:var(--oid-elevated)] p-2.5 no-underline transition-colors hover:border-[color:var(--oid-accent)]"
      >
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <p className="truncate text-[length:var(--oid-text-xs)] font-medium text-[color:var(--oid-text-strong)] group-hover:text-[color:var(--oid-accent)]">
              {model.label ?? model.variable}
            </p>
            <p className="text-[length:var(--oid-text-5xs)] text-[color:var(--oid-text-faint)]">
              +{model.horizon}d · {model.model_type ?? 'model'}
            </p>
          </div>
          <span
            className={cn(
              'shrink-0 rounded-full border px-1.5 py-0.5 text-[length:var(--oid-text-6xs)] font-medium',
              grade.chip
            )}
          >
            {grade.label}
          </span>
        </div>

        <dl className="mt-2 grid grid-cols-3 gap-1.5">
          <Stat
            label="Skill"
            value={skill != null ? (skill > 0 ? `+${skill.toFixed(3)}` : skill.toFixed(3)) : '—'}
            hint="vs persistence"
          />
          <Stat
            label="Folds"
            value={`${(model.n_folds ?? 0) - (model.negative_folds ?? 0)}/${model.n_folds ?? 0}`}
            hint="positive"
          />
          <Stat label="Range" value={spread} hint="fold skill" />
        </dl>

        {/* A global model that lost points has lost geography, not just rows. */}
        {(model.points_skipped ?? 0) > 0 && (
          <p className="mt-1.5 text-[length:var(--oid-text-4xs)] text-[color:var(--color-alert-warning)]">
            Trained on {model.points_used} points, {model.points_skipped} skipped — check coverage
            before trusting it away from the retained points.
          </p>
        )}
      </Link>
    </li>
  );
}

export function DataQualityPanel() {
  const { data, isPending, isError, error, refetch } = useDataQuality();
  const [tab, setTab] = useState<'datasets' | 'models'>('datasets');

  // Worst first: a fold-limited or below-persistence model is the reason to
  // open this panel, and burying it under a hundred strong ones hides it.
  const models = useMemo(() => {
    if (!data) return [];
    const order: Record<string, number> = { poor: 0, fair: 1, unknown: 2, good: 3, strong: 4 };
    return [...data.models].sort((a, b) => {
      const rank = (m: ModelEntry) => (m.available ? (order[m.grade ?? 'unknown'] ?? 5) : -1);
      return rank(a) - rank(b);
    });
  }, [data]);

  const coverage = data?.coverage;

  return (
    <Panel className="flex h-full flex-col">
      <PanelHeader
        icon={<Database size={15} />}
        title="Data quality"
        subtitle={
          coverage
            ? `${data.datasets.length} datasets · ${coverage.models_trained} models · ${coverage.variables_gridded} gridded`
            : 'Datasets, models and coverage'
        }
        actions={
          <div className="flex gap-1">
            {(['datasets', 'models'] as const).map((key) => (
              <button
                key={key}
                type="button"
                onClick={() => setTab(key)}
                className={cn(
                  'rounded-md px-2 py-1 text-[length:var(--oid-text-3xs)] capitalize transition-colors',
                  tab === key
                    ? 'bg-[color:var(--oid-accent-wash)] text-[color:var(--oid-accent)]'
                    : 'text-[color:var(--oid-text-muted)] hover:text-[color:var(--oid-text)]'
                )}
              >
                {key}
              </button>
            ))}
          </div>
        }
      />

      {isPending && <PanelSkeleton rows={4} />}

      {isError && (
        <PanelEmpty
          title="Quality report unavailable"
          reason={error instanceof Error ? error.message : undefined}
          onRetry={() => void refetch()}
        />
      )}

      {data && coverage && (
        <div className="flex min-h-0 flex-1 flex-col">
          <dl className="grid grid-cols-4 gap-2 border-b border-[color:var(--oid-border)] p-3">
            <Stat
              label="Served"
              value={`${coverage.variables_served}/${coverage.variables_total}`}
              hint="variables"
            />
            <Stat
              label="Trained"
              value={`${coverage.variables_trained}`}
              hint={`${coverage.models_trained} models`}
            />
            <Stat
              label="Gridded"
              value={`${coverage.variables_gridded}`}
              hint="on the map"
            />
            <Stat
              label="Awaiting build"
              value={`${coverage.trained_but_ungridded.length}`}
              hint="trained, not drawn"
            />
          </dl>

          {/* The two gaps that are pending work, kept apart from the one that
              is permanent — listing an Open-Meteo variable as an unbuilt grid
              would be a gap nobody can ever close. */}
          {tab === 'datasets' && coverage.trained_but_ungriddable.length > 0 && (
            <p className="border-b border-[color:var(--oid-border)] px-3 py-2 text-[length:var(--oid-text-4xs)] leading-snug text-[color:var(--oid-text-faint)]">
              {coverage.trained_but_ungriddable.length} trained variables can never be gridded —
              they come from a point API with no global field, so they are excluded from the
              build queue rather than counted as outstanding.
            </p>
          )}

          <div className="oid-scroll min-h-0 flex-1 overflow-y-auto p-3">
            {tab === 'datasets' ? (
              <ul className="grid gap-2 sm:grid-cols-2">
                {data.datasets.map((dataset) => (
                  <DatasetRow key={dataset.key} dataset={dataset} />
                ))}
              </ul>
            ) : (
              <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {models.map((model) => (
                  <ModelRow key={`${model.variable}-h${model.horizon}`} model={model} />
                ))}
              </ul>
            )}
          </div>

          <p className="border-t border-[color:var(--oid-border)] px-3 py-2 text-[length:var(--oid-text-4xs)] leading-snug text-[color:var(--oid-text-ghost)]">
            Skill is measured against persistence on rolling-origin validation. A model ships only
            if overall skill is positive <em>and</em> at most one of five folds is negative — the
            aggregate alone would pass models carried by a minority of folds.
          </p>
        </div>
      )}
    </Panel>
  );
}
