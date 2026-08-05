/** The metrics index — every forecastable variable, grouped by category.
 *
 * The only surface that reaches all 32. The dashboard's KPI cards cover a
 * handful, and three of those (heat-stress extent, bleaching risk, habitat
 * suitability) are derived indices rather than variables, so they have no
 * metric page to link to.
 *
 * Entirely catalog-driven: the categories, ordering and contents all come from
 * the backend, so a newly configured variable appears here the moment it is
 * trained without any change to this file.
 */

import { useEffect, useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import { ArrowRight, ChevronRight, Search } from 'lucide-react';
import { Link } from '../../../app/router';
import { useAppRouter } from '../../../app/routerContext';
import { useMapStore } from '../../../store/mapStore';
import { useThemeStore } from '../../../store/themeStore';
import type { CatalogVariable } from './api/types';
import { useForecastCatalog } from './hooks/useMetricData';
import { Panel, PanelEmpty, PanelSkeleton } from '../components/Panel';
import { cn } from '../lib/cn';
import '../styles/tailwind.css';

const DEFAULT_LOCATION = { latitude: 15, longitude: 65 };

function VariableCard({
  entry,
  query,
  index,
}: {
  entry: CatalogVariable;
  query: string;
  index: number;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: Math.min(index * 0.02, 0.2), duration: 0.35 }}
    >
      <Link to={`/dashboard/${entry.key}${query}`} className="block no-underline">
        <Panel className="group h-full transition-shadow hover:shadow-[var(--oid-shadow-raised)]">
          <span
            aria-hidden="true"
            className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-[color:var(--oid-accent)] to-transparent opacity-0 transition-opacity group-hover:opacity-90"
          />
          <div className="flex h-full flex-col gap-2 p-3.5">
            <div className="flex items-start justify-between gap-2">
              <h3 className="text-[13px] leading-snug font-medium text-[color:var(--oid-text-strong)]">
                {entry.label}
              </h3>
              <ArrowRight
                size={13}
                className="mt-0.5 shrink-0 text-[color:var(--oid-text-ghost)] transition-colors group-hover:text-[color:var(--oid-accent)]"
              />
            </div>

            <div className="flex flex-wrap items-center gap-1.5">
              <span className="rounded-full bg-[color:var(--oid-track)] px-1.5 py-0.5 text-[10px] text-[color:var(--oid-text-muted)]">
                {entry.unit}
              </span>
              {entry.trained_horizons.length > 0 ? (
                <span className="rounded-full bg-[color:var(--oid-accent-wash)] px-1.5 py-0.5 text-[10px] text-[color:var(--oid-accent)]">
                  forecast {entry.trained_horizons.map((h) => `${h}d`).join('/')}
                </span>
              ) : (
                <span
                  className="rounded-full bg-[color:var(--oid-track)] px-1.5 py-0.5 text-[10px] text-[color:var(--oid-text-ghost)]"
                  title={entry.unavailable_reason ?? undefined}
                >
                  history only
                </span>
              )}
            </div>
          </div>
        </Panel>
      </Link>
    </motion.div>
  );
}

export function MetricsIndexPage() {
  const { searchParams } = useAppRouter();
  const isDark = useThemeStore((state) => state.dark);
  const sharedLocation = useMapStore((state) => state.selectedLocation);
  const [filter, setFilter] = useState('');

  const { data, isPending, isError, error, refetch } = useForecastCatalog();

  useEffect(() => {
    document.title = 'All metrics | Maris AI';
  }, []);

  const location = useMemo(() => {
    const lat = Number(searchParams.get('lat'));
    const lon = Number(searchParams.get('lon'));
    if (Number.isFinite(lat) && Number.isFinite(lon) && searchParams.has('lat')) {
      return { latitude: lat, longitude: lon };
    }
    if (sharedLocation) return { latitude: sharedLocation.lat, longitude: sharedLocation.lng };
    return DEFAULT_LOCATION;
  }, [searchParams, sharedLocation]);

  const query = `?lat=${location.latitude}&lon=${location.longitude}`;

  const grouped = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    const groups = new Map<string, CatalogVariable[]>();
    for (const entry of data?.variables ?? []) {
      if (needle && !entry.label.toLowerCase().includes(needle)) continue;
      const list = groups.get(entry.category) ?? [];
      list.push(entry);
      groups.set(entry.category, list);
    }
    return [...groups.entries()];
  }, [data, filter]);

  const trainedCount = (data?.variables ?? []).filter(
    (entry) => entry.trained_horizons.length > 0
  ).length;

  return (
    <div
      className={cn(
        'oid-root min-h-screen bg-[image:var(--oid-page)]',
        !isDark && 'oid-root--light'
      )}
      data-theme={isDark ? 'dark' : 'light'}
    >
      <main
        className="mx-auto max-w-[1500px] px-3 pb-16 sm:px-5"
        style={{ paddingTop: 'calc(var(--navbar-h, 64px) + 16px)' }}
      >
        <nav aria-label="Breadcrumb" className="flex items-center gap-1.5 text-[11.5px]">
          <Link
            to="/dashboard"
            className="text-[color:var(--oid-text-faint)] no-underline hover:text-[color:var(--oid-accent)]"
          >
            Dashboard
          </Link>
          <ChevronRight size={12} className="text-[color:var(--oid-text-ghost)]" />
          <span className="text-[color:var(--oid-text)]">All metrics</span>
        </nav>

        <header className="mt-3 mb-5 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-[22px] leading-none font-semibold tracking-tight text-[color:var(--oid-text-strong)]">
              Ocean metrics
            </h1>
            <p className="mt-1.5 text-[11.5px] text-[color:var(--oid-text-faint)]">
              {data
                ? `${data.variables.length} variables, ${trainedCount} with a trained forecast. Every one has its own intelligence page.`
                : 'Loading the catalog…'}
            </p>
          </div>

          <label className="flex items-center gap-1.5 rounded-full border border-[color:var(--oid-border)] bg-[color:var(--oid-elevated)] px-3 py-1.5">
            <Search size={12} className="text-[color:var(--oid-text-ghost)]" />
            <input
              value={filter}
              onChange={(event) => setFilter(event.target.value)}
              placeholder="Filter metrics"
              aria-label="Filter metrics"
              className="w-40 bg-transparent text-[11.5px] text-[color:var(--oid-text)] outline-none placeholder:text-[color:var(--oid-text-ghost)]"
            />
          </label>
        </header>

        {isPending && (
          <Panel>
            <PanelSkeleton rows={5} />
          </Panel>
        )}

        {isError && (
          <Panel>
            <PanelEmpty
              title="Could not load the catalog"
              reason={error instanceof Error ? error.message : undefined}
              onRetry={() => void refetch()}
            />
          </Panel>
        )}

        {data && grouped.length === 0 && (
          <Panel>
            <PanelEmpty title="No metrics match that filter" reason={`Nothing named “${filter}”.`} />
          </Panel>
        )}

        <div className="space-y-6">
          {grouped.map(([category, entries]) => (
            <section key={category} aria-label={category}>
              <h2 className="mb-2.5 text-[11px] font-medium tracking-wide text-[color:var(--oid-text-muted)] uppercase">
                {category}
                <span className="ml-2 text-[color:var(--oid-text-ghost)]">{entries.length}</span>
              </h2>
              <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4">
                {entries.map((entry, index) => (
                  <VariableCard key={entry.key} entry={entry} query={query} index={index} />
                ))}
              </div>
            </section>
          ))}
        </div>
      </main>
    </div>
  );
}
