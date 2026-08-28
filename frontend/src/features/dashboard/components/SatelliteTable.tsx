/** Recent satellite products from NASA GIBS.
 *
 * The `status` column is genuinely informative rather than always-green:
 * several tracked GIBS layers really are years stale upstream (AVHRR-OI stops
 * in 2020, OSCAR in 2024), and showing that is the point of the table.
 */

import { Satellite } from 'lucide-react';
import { useAppRouter } from '../../../app/routerContext';
import type { SatelliteProduct } from '../api/types';
import { useSatellites } from '../hooks/useDashboardData';
import { cn } from '../lib/cn';
import { Panel, PanelEmpty, PanelHeader, PanelSkeleton } from './Panel';

const STATUS_STYLES: Record<SatelliteProduct['status'], { label: string; className: string }> = {
  current: {
    label: 'Current',
    className:
      'text-[color:var(--color-emerald-400)] bg-[color:color-mix(in_oklab,var(--color-emerald-400)_12%,transparent)]',
  },
  delayed: {
    label: 'Delayed',
    className:
      'text-[color:var(--color-alert-warning)] bg-[color:color-mix(in_oklab,var(--color-alert-warning)_12%,transparent)]',
  },
  stale: {
    label: 'Stale',
    className:
      'text-[color:var(--color-alert-critical)] bg-[color:color-mix(in_oklab,var(--color-alert-critical)_12%,transparent)]',
  },
  unknown: { label: 'Unknown', className: 'text-[color:var(--oid-text-muted)] bg-[color:var(--oid-track)]' },
};

function formatAgeDays(days: number | null): string {
  if (days == null) return '—';
  if (days <= 0) return 'Today';
  if (days === 1) return '1 day';
  if (days < 60) return `${days} days`;
  if (days < 730) return `${Math.round(days / 30)} months`;
  return `${(days / 365).toFixed(1)} years`;
}

export function SatelliteTable() {
  const { data, isPending, isError, error, refetch } = useSatellites();
  const { navigate } = useAppRouter();

  function openProduct(layerId: string) {
    navigate(`/dashboard/satellite?layer=${encodeURIComponent(layerId)}`);
  }

  return (
    <Panel className="flex h-full flex-col">
      <PanelHeader
        icon={<Satellite size={15} />}
        title="Recent satellite products"
        subtitle={data ? `${data.products.length} tracked NASA GIBS layers` : 'NASA GIBS'}
      />

      {isPending && <PanelSkeleton rows={5} />}

      {isError && (
        <PanelEmpty
          title="Satellite listing unavailable"
          reason={error instanceof Error ? error.message : undefined}
          onRetry={() => void refetch()}
        />
      )}

      {data && (
        // Tables are the one thing guaranteed to overflow on a phone; it
        // scrolls inside its own container rather than widening the page.
        <div className="oid-scroll flex-1 overflow-auto">
          <table className="min-w-[640px] text-left">
            <thead className="sticky top-0 z-10 bg-[color:var(--oid-panel-strong)] backdrop-blur">
              <tr className="text-[9.5px] tracking-widest text-[color:var(--oid-text-faint)] uppercase">
                <th scope="col" className="px-3 py-2 font-semibold">Satellite</th>
                <th scope="col" className="px-3 py-2 font-semibold">Product</th>
                <th scope="col" className="px-3 py-2 font-semibold">Coverage</th>
                <th scope="col" className="px-3 py-2 font-semibold">Resolution</th>
                <th scope="col" className="px-3 py-2 font-semibold">Latest</th>
                <th scope="col" className="px-3 py-2 font-semibold">Status</th>
              </tr>
            </thead>
            <tbody>
              {data.products.map((product) => {
                const status = STATUS_STYLES[product.status];
                return (
                  <tr
                    key={product.layer_id}
                    role="button"
                    tabIndex={0}
                    aria-label={`Open ${product.title} detail`}
                    onClick={() => openProduct(product.layer_id)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault();
                        openProduct(product.layer_id);
                      }
                    }}
                    className="cursor-pointer border-t border-[color:var(--oid-border)] transition-colors hover:bg-[color:var(--oid-hover)]"
                  >
                    <td className="px-3 py-2 text-[11.5px] font-medium text-[color:var(--oid-text)]">
                      {product.satellite}
                    </td>
                    <td className="px-3 py-2 text-[11.5px] text-[color:var(--oid-text)]">{product.product}</td>
                    <td className="px-3 py-2 text-[11px] text-[color:var(--oid-text-faint)]">Global</td>
                    <td className="px-3 py-2 text-[11px] text-[color:var(--oid-text-muted)]">
                      {product.resolution ?? '—'}
                    </td>
                    <td className="px-3 py-2 text-[11px] text-[color:var(--oid-text-muted)]">
                      <span title={product.latest_date ?? undefined}>
                        {formatAgeDays(product.age_days)}
                      </span>
                    </td>
                    <td className="px-3 py-2">
                      <span
                        className={cn(
                          'inline-block rounded-full px-2 py-0.5 text-[10px] font-medium',
                          status.className
                        )}
                      >
                        {status.label}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {data && (
        <footer className="border-t border-[color:var(--oid-border)] px-3 py-2 text-[9.5px] text-[color:var(--oid-text-ghost)]">
          {data.meta.source} · a stale row reflects the upstream layer, not this dashboard
        </footer>
      )}
    </Panel>
  );
}
