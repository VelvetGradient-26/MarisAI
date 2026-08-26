/** Data-source health.
 *
 * Reports each integration's cache state — the backend judges staleness
 * against that source's own refresh cadence, so a six-hourly satellite
 * product and a ten-minute buoy feed are not held to the same clock.
 */

import { ServerCog } from 'lucide-react';
import { Link } from '../../../app/router';
import type { ProviderStatus } from '../api/types';
import { useHealth } from '../hooks/useDashboardData';
import { formatAge, HEALTH_STYLES } from '../lib/format';
import { cn } from '../lib/cn';
import { LiveDot, Panel, PanelEmpty, PanelHeader, PanelSkeleton } from './Panel';

function ageSeconds(iso: string | null): number | null {
  if (!iso) return null;
  const parsed = Date.parse(iso);
  return Number.isNaN(parsed) ? null : Math.max(0, (Date.now() - parsed) / 1000);
}

function ProviderCard({ provider }: { provider: ProviderStatus }) {
  const style = HEALTH_STYLES[provider.health];

  return (
    <li>
      <Link
        to={`/dashboard/source?key=${encodeURIComponent(provider.key)}`}
        className={cn(
          'block rounded-xl border border-[color:var(--oid-border)] p-3 no-underline',
          'bg-[color:var(--oid-elevated)] transition-colors',
          'hover:border-[color:var(--oid-accent-wash-strong)]'
        )}
      >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h4 className="truncate text-[12px] font-medium text-[color:var(--oid-text-strong)]">{provider.name}</h4>
          <p className="mt-0.5 text-[9.5px] tracking-wide text-[color:var(--oid-text-faint)] uppercase">
            {provider.category}
          </p>
        </div>
        <span className="flex shrink-0 items-center gap-1.5">
          <span className={cn('h-1.5 w-1.5 rounded-full', style.dot)} />
          <span className={cn('text-[10px] font-medium', style.text)}>{style.label}</span>
        </span>
      </div>

      <dl className="mt-2.5 grid grid-cols-3 gap-2">
        <div>
          <dt className="text-[9px] tracking-wide text-[color:var(--oid-text-ghost)] uppercase">Latency</dt>
          <dd className="text-[11px] text-[color:var(--oid-text)]">
            {provider.latency_ms != null ? `${provider.latency_ms} ms` : '—'}
          </dd>
        </div>
        <div>
          <dt className="text-[9px] tracking-wide text-[color:var(--oid-text-ghost)] uppercase">Last sync</dt>
          <dd className="text-[11px] text-[color:var(--oid-text)]">
            {formatAge(ageSeconds(provider.last_sync))}
          </dd>
        </div>
        <div>
          <dt className="text-[9px] tracking-wide text-[color:var(--oid-text-ghost)] uppercase">Records</dt>
          <dd className="text-[11px] text-[color:var(--oid-text)]">
            {provider.records ? provider.records.toLocaleString() : '—'}
          </dd>
        </div>
      </dl>

      {provider.data_timestamp && (
        <p className="mt-2 text-[10px] text-[color:var(--oid-text-faint)]">
          Data timestep {formatAge(ageSeconds(provider.data_timestamp))} — products publish
          behind real time; this does not affect connection health.
        </p>
      )}

      {provider.error && (
        <p className="mt-2 text-[10px] text-[color:var(--color-alert-critical)]">
          {provider.error}
        </p>
      )}
      {!provider.error && provider.notes && (
        <p className="mt-2 text-[10px] leading-snug text-[color:var(--oid-text-ghost)]">{provider.notes}</p>
      )}
      </Link>
    </li>
  );
}

export function HealthPanel() {
  const { data, isPending, isError, error, isFetching, refetch } = useHealth();

  return (
    <Panel className="flex h-full flex-col">
      <PanelHeader
        icon={<ServerCog size={15} />}
        title="Data source status"
        subtitle={
          data
            ? `${data.summary.healthy} healthy · ${data.summary.degraded} degraded · ${data.summary.down} down`
            : 'Provider connections'
        }
        actions={<LiveDot active={isFetching} />}
      />

      {isPending && <PanelSkeleton rows={4} />}

      {isError && (
        <PanelEmpty
          title="Status unavailable"
          reason={error instanceof Error ? error.message : undefined}
          onRetry={() => void refetch()}
        />
      )}

      {data && (
        <ul className="oid-scroll grid flex-1 gap-2 overflow-y-auto p-3 sm:grid-cols-2">
          {data.providers.map((provider) => (
            <ProviderCard key={provider.key} provider={provider} />
          ))}
        </ul>
      )}
    </Panel>
  );
}
