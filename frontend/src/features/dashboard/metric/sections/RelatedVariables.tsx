/** Related variables.
 *
 * The relationships shown are the ones the *model* actually uses — a
 * variable's configured covariates, plus the others in its category. That is a
 * deliberately weaker claim than a correlation, and the copy says so: these
 * are inputs the forecast depends on, not a measured association. Computing
 * real correlations needs a backend endpoint that does not exist yet, and
 * labelling a covariate list as "correlated" would be inventing a statistic.
 */

import { ArrowRight, Network } from 'lucide-react';
import { Link } from '../../../../app/router';
import type { SectionProps } from '../sections';
import { useForecastCatalog } from '../hooks/useMetricData';
import { Panel, PanelHeader, PanelSkeleton } from '../../components/Panel';
import { cn } from '../../lib/cn';

export function RelatedVariables({ variable, latitude, longitude }: SectionProps) {
  const { data: catalog, isPending } = useForecastCatalog();

  if (isPending) {
    return (
      <Panel>
        <PanelSkeleton rows={2} />
      </Panel>
    );
  }

  const byKey = new Map((catalog?.variables ?? []).map((entry) => [entry.key, entry]));

  const covariates = variable.covariates
    .map((key) => byKey.get(key))
    .filter((entry): entry is NonNullable<typeof entry> => entry != null);

  const siblings = (catalog?.variables ?? []).filter(
    (entry) =>
      entry.category === variable.category &&
      entry.key !== variable.key &&
      !variable.covariates.includes(entry.key)
  );

  const query = `?lat=${latitude}&lon=${longitude}`;

  return (
    <Panel>
      <PanelHeader
        icon={<Network size={14} />}
        title="Related Variables"
        subtitle="Inputs this forecast depends on, and others in the same category"
      />
      <div className="space-y-4 p-4">
        {covariates.length > 0 && (
          <div>
            <h3 className="text-[length:var(--oid-text-xs)] font-medium tracking-wide text-[color:var(--oid-text-muted)] uppercase">
              Model inputs
            </h3>
            <div className="mt-2 flex flex-wrap gap-2">
              {covariates.map((entry) => (
                <Chip key={entry.key} entry={entry} query={query} emphasis />
              ))}
            </div>
          </div>
        )}

        {siblings.length > 0 && (
          <div>
            <h3 className="text-[length:var(--oid-text-xs)] font-medium tracking-wide text-[color:var(--oid-text-muted)] uppercase">
              Also in {variable.category}
            </h3>
            <div className="mt-2 flex flex-wrap gap-2">
              {siblings.map((entry) => (
                <Chip key={entry.key} entry={entry} query={query} />
              ))}
            </div>
          </div>
        )}

        <p className="text-[length:var(--oid-text-3xs)] leading-relaxed text-[color:var(--oid-text-ghost)]">
          Model inputs are the variables this forecast is fitted on. That is a statement about
          the model, not a measured correlation between the two fields.
        </p>
      </div>
    </Panel>
  );
}

function Chip({
  entry,
  query,
  emphasis,
}: {
  entry: { key: string; label: string; unit: string; available: boolean };
  query: string;
  emphasis?: boolean;
}) {
  return (
    <Link
      to={`/dashboard/${entry.key}${query}`}
      className={cn(
        'group inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5',
        'text-[length:var(--oid-text-sm)] no-underline transition-colors',
        'border-[color:var(--oid-border)]',
        emphasis
          ? 'bg-[color:var(--oid-accent-wash)] text-[color:var(--oid-accent)] hover:bg-[color:var(--oid-accent-wash-strong)]'
          : 'text-[color:var(--oid-text)] hover:bg-[color:var(--oid-track)]'
      )}
    >
      {entry.label}
      <span className="text-[length:var(--oid-text-3xs)] text-[color:var(--oid-text-ghost)]">{entry.unit}</span>
      <ArrowRight
        size={11}
        className="opacity-0 transition-opacity group-hover:opacity-100"
      />
    </Link>
  );
}
