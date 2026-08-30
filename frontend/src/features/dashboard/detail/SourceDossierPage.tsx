/** One data source's detail — the click-through target from a Data Source
 * Status card, whose job is answering "what's cached, when it last
 * refreshed, and why" beyond the status light alone.
 *
 * Almost everything here was already computed by `services/dashboard/
 * health.py`'s per-provider probe and simply wasn't surfaced on the list
 * card (`notes`, `data_timestamp`, `error`) — the one genuinely new piece is
 * `recent_health`, a short in-process sparkline recorded into the same ring
 * buffer the KPI cards' own sparklines use (`services/dashboard/history.py`),
 * sampled opportunistically each time the health or detail endpoint is
 * called. A freshly started server has little or no history, and the panel
 * says so rather than drawing a flat line.
 */

import { useEffect } from 'react';
import { useAppRouter } from '../../../app/routerContext';
import { useThemeStore } from '../../../store/themeStore';
import type { ProviderHealth } from '../api/types';
import { useSourceDetail } from '../hooks/useDashboardData';
import { Breadcrumb } from '../components/Breadcrumb';
import { Panel, PanelEmpty, PanelHeader, PanelSkeleton } from '../components/Panel';
import { cn } from '../lib/cn';
import '../styles/tailwind.css';

const HEALTH_LABEL: Record<ProviderHealth, string> = {
  healthy: 'Healthy',
  degraded: 'Degraded',
  down: 'Down',
  unknown: 'Unknown',
};

const HEALTH_COLOR: Record<ProviderHealth, string> = {
  healthy: 'var(--color-emerald-400)',
  degraded: 'var(--color-alert-warning)',
  down: 'var(--color-alert-critical)',
  unknown: 'var(--oid-text-ghost)',
};

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div>
      <dt className="text-[length:var(--oid-text-4xs)] tracking-wide text-[color:var(--oid-text-ghost)] uppercase">{label}</dt>
      <dd className="text-[length:var(--oid-text-lg)] font-medium text-[color:var(--oid-text-strong)]">{value}</dd>
      {hint && <p className="mt-0.5 text-[length:var(--oid-text-3xs)] leading-tight text-[color:var(--oid-text-faint)]">{hint}</p>}
    </div>
  );
}

function scoreColor(value: number): string {
  if (value >= 0.85) return 'var(--color-emerald-400)';
  if (value >= 0.35) return 'var(--color-alert-warning)';
  return 'var(--color-alert-critical)';
}

function RecentHealth({ points }: { points: { t: string; v: number }[] }) {
  if (points.length === 0) {
    return (
      <p className="text-[length:var(--oid-text-xs)] text-[color:var(--oid-text-faint)]">
        Not enough history yet — this server has not been running long enough to plot a trend.
        Recorded roughly every 15 minutes while the dashboard is in use.
      </p>
    );
  }
  return (
    <div>
      <div className="flex h-8 items-end gap-[3px]">
        {points.map((point) => (
          <span
            key={point.t}
            title={`${new Date(point.t).toLocaleString()} — ${(point.v * 100).toFixed(0)}%`}
            className="flex-1 rounded-t-sm"
            style={{ height: `${Math.max(12, point.v * 100)}%`, backgroundColor: scoreColor(point.v) }}
          />
        ))}
      </div>
      <div className="mt-1.5 flex justify-between text-[length:var(--oid-text-4xs)] text-[color:var(--oid-text-ghost)]">
        <span>{new Date(points[0].t).toLocaleString()}</span>
        <span>{new Date(points[points.length - 1].t).toLocaleString()}</span>
      </div>
    </div>
  );
}

export function SourceDossierPage() {
  const { searchParams } = useAppRouter();
  const isDark = useThemeStore((state) => state.dark);

  const key = (searchParams.get('key') ?? '').trim();
  const { data, isPending, isError, error, refetch } = useSourceDetail(key);

  useEffect(() => {
    document.title = data ? `${data.name} | Maris AI` : 'Data source | Maris AI';
  }, [data]);

  return (
    <div
      className={cn('oid-root min-h-screen bg-[image:var(--oid-page)]', !isDark && 'oid-root--light')}
      data-theme={isDark ? 'dark' : 'light'}
    >
      <main
        className="mx-auto max-w-[900px] px-3 pb-16 sm:px-5"
        style={{ paddingTop: 'calc(var(--navbar-h, 64px) + 16px)' }}
      >
        <Breadcrumb current={data?.name ?? (key || '—')} />

        {!key ? (
          <Panel className="mt-4">
            <PanelEmpty
              title="No source specified"
              reason="This page needs a ?key= — open it from a card on the Data Source Status panel."
            />
          </Panel>
        ) : (
          <>
            <header className="mt-3 mb-5 flex flex-wrap items-center gap-3">
              <div>
                <h1 className="text-[22px] leading-none font-semibold tracking-tight text-[color:var(--oid-text-strong)]">
                  {data?.name ?? key}
                </h1>
                <p className="mt-1.5 text-[length:var(--oid-text-sm)] text-[color:var(--oid-text-faint)]">
                  {data?.category ?? 'Loading…'}
                </p>
              </div>
              {data && (
                <span
                  className="rounded-full border px-2 py-0.5 text-[length:var(--oid-text-2xs)] font-medium"
                  style={{ color: HEALTH_COLOR[data.health], borderColor: HEALTH_COLOR[data.health] }}
                >
                  {HEALTH_LABEL[data.health]}
                </span>
              )}
            </header>

            {isPending && (
              <Panel>
                <PanelSkeleton rows={5} />
              </Panel>
            )}

            {isError && (
              <Panel>
                <PanelEmpty
                  title="Source unavailable"
                  reason={error instanceof Error ? error.message : undefined}
                  onRetry={() => void refetch()}
                />
              </Panel>
            )}

            {data && (
              <div className="grid grid-cols-1 gap-4">
                <Panel>
                  <PanelHeader title="Status" subtitle="What's cached, when it last refreshed, and why" />
                  <div className="grid grid-cols-2 gap-4 p-4 sm:grid-cols-4">
                    <Stat label="Connected" value={data.connected ? 'Yes' : 'No'} />
                    <Stat label="Latency" value={data.latency_ms != null ? `${data.latency_ms} ms` : '—'} />
                    <Stat
                      label="Last sync"
                      value={data.last_sync ? new Date(data.last_sync).toUTCString() : '—'}
                    />
                    <Stat
                      label="Data timestamp"
                      value={data.data_timestamp ? new Date(data.data_timestamp).toUTCString() : '—'}
                      hint={data.data_timestamp ? 'The timestep this data describes' : undefined}
                    />
                    <Stat label="Records" value={data.records.toLocaleString()} />
                    <Stat
                      label="Expected cadence"
                      value={`~${Math.round((data.stale_after_s / 3600) * 10) / 10}h`}
                      hint="Before a missed cycle turns this amber"
                    />
                  </div>
                  <div className="border-t border-[color:var(--oid-border)] p-4">
                    <p className="text-[length:var(--oid-text-sm)] leading-relaxed text-[color:var(--oid-text)]">
                      {data.explanation}
                    </p>
                    {data.notes && (
                      <p className="mt-2 text-[length:var(--oid-text-xs)] leading-relaxed text-[color:var(--oid-text-faint)]">
                        {data.notes}
                      </p>
                    )}
                    {data.error && (
                      <p className="mt-2 text-[length:var(--oid-text-xs)] leading-relaxed text-[color:var(--color-alert-critical)]">
                        {data.error}
                      </p>
                    )}
                  </div>
                </Panel>

                <Panel>
                  <PanelHeader
                    title="Recent health"
                    subtitle="Sampled while the dashboard is in use — does not survive a server restart"
                  />
                  <div className="p-4">
                    <RecentHealth points={data.recent_health} />
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
