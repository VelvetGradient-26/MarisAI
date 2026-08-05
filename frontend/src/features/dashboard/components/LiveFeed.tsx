/** Live ocean feed — the freshest reading from each source.
 *
 * Buoy entries are real instrument observations and get the detailed
 * treatment (temperature, waves, wind, pressure, humidity); model and
 * satellite entries are product-freshness rows. The distinction is kept
 * visible because "a buoy measured 27.6°C twenty minutes ago" and "a model
 * published a grid" are different kinds of claim.
 */

import { AnimatePresence, motion } from 'framer-motion';
import { Activity, Radio, Satellite, Waves } from 'lucide-react';
import type { LiveEntry } from '../api/types';
import { useLive } from '../hooks/useDashboardData';
import { formatAge, formatValue } from '../lib/format';
import { cn } from '../lib/cn';
import { LiveDot, Panel, PanelEmpty, PanelHeader, PanelSkeleton } from './Panel';

function BuoyCard({ entry }: { entry: LiveEntry }) {
  const readings: { label: string; value: string }[] = [
    { label: 'Water', value: formatValue(entry.water_temperature_c, '°C', 1) },
    { label: 'Waves', value: formatValue(entry.wave_height_m, 'm', 1) },
    { label: 'Wind', value: formatValue(entry.wind_speed_ms, 'm/s', 1) },
    { label: 'Pressure', value: formatValue(entry.pressure_hpa, 'hPa', 1) },
    { label: 'Air', value: formatValue(entry.air_temperature_c, '°C', 1) },
    { label: 'Humidity', value: formatValue(entry.relative_humidity_pct, '%', 0) },
  ].filter((reading) => reading.value !== '—');

  return (
    <li>
      <article
        className={cn(
          'rounded-xl border border-[color:var(--oid-border)] p-3',
          'bg-[color:var(--oid-elevated)] transition-colors',
          'hover:border-[color:var(--oid-border-hover)]'
        )}
      >
        <header className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2">
            <Radio size={13} className="text-[color:var(--oid-accent-soft)]" />
            <span className="text-[12.5px] font-semibold text-[color:var(--oid-text-strong)]">{entry.title}</span>
          </div>
          <span className="shrink-0 text-[10px] text-[color:var(--oid-text-faint)]">
            {formatAge(entry.age_seconds)}
          </span>
        </header>

        <p className="mt-1 text-[10.5px] text-[color:var(--oid-text-faint)]">
          {entry.latitude != null && entry.longitude != null
            ? `${entry.latitude.toFixed(2)}°, ${entry.longitude.toFixed(2)}°`
            : 'Position unknown'}
          {entry.distance_km != null && ` · ${entry.distance_km.toFixed(0)} km away`}
        </p>

        {readings.length > 0 ? (
          <dl className="mt-2.5 grid grid-cols-3 gap-x-2 gap-y-2">
            {readings.map((reading) => (
              <div key={reading.label}>
                <dt className="text-[9.5px] tracking-wide text-[color:var(--oid-text-faint)] uppercase">
                  {reading.label}
                </dt>
                <dd className="text-[12px] font-medium text-[color:var(--oid-text)]">{reading.value}</dd>
              </div>
            ))}
          </dl>
        ) : (
          <p className="mt-2 text-[10.5px] text-[color:var(--oid-text-ghost)]">
            Station reported no usable measurements in this cycle.
          </p>
        )}
      </article>
    </li>
  );
}

function ProductRow({ entry }: { entry: LiveEntry }) {
  const Icon = entry.kind === 'satellite' ? Satellite : Waves;

  return (
    <li>
      <article
        className={cn(
          'flex items-start gap-2.5 rounded-xl border border-transparent px-3 py-2.5',
          'transition-colors hover:border-[color:var(--oid-border)]',
          !entry.available && 'opacity-70'
        )}
      >
        <Icon size={13} className="mt-0.5 shrink-0 text-[color:var(--oid-accent)]" />
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline justify-between gap-2">
            <h4 className="truncate text-[12px] font-medium text-[color:var(--oid-text)]">{entry.title}</h4>
            <span className="shrink-0 text-[10px] text-[color:var(--oid-text-faint)]">
              {entry.available ? formatAge(entry.age_seconds) : 'unavailable'}
            </span>
          </div>
          <p className="mt-0.5 truncate text-[10.5px] text-[color:var(--oid-text-faint)]">
            {entry.available
              ? [entry.coverage, entry.resolution, entry.cadence].filter(Boolean).join(' · ') ||
                entry.source
              : entry.unavailable_reason}
          </p>
        </div>
      </article>
    </li>
  );
}

export function LiveFeed({
  location,
}: {
  location: { latitude: number; longitude: number } | null;
}) {
  const { data, isPending, isError, error, isFetching, refetch } = useLive(location, 4);

  const buoys = data?.entries.filter((entry) => entry.kind === 'buoy' && entry.available) ?? [];
  const products = data?.entries.filter((entry) => entry.kind !== 'buoy') ?? [];
  const buoyUnavailable = data?.entries.find(
    (entry) => entry.kind === 'buoy' && !entry.available
  );

  return (
    <Panel className="flex h-full flex-col">
      <PanelHeader
        icon={<Activity size={15} />}
        title="Live ocean feed"
        subtitle={
          location
            ? `Nearest stations to ${location.latitude.toFixed(2)}°, ${location.longitude.toFixed(2)}°`
            : 'Most recently reporting stations'
        }
        actions={<LiveDot active={isFetching} />}
      />

      {isPending && <PanelSkeleton rows={4} />}

      {isError && (
        <PanelEmpty
          title="Live feed unavailable"
          reason={error instanceof Error ? error.message : undefined}
          onRetry={() => void refetch()}
        />
      )}

      {data && (
        <div className="oid-scroll flex-1 space-y-3 overflow-y-auto p-3">
          {buoys.length > 0 && (
            <ul className="space-y-2">
              <AnimatePresence initial={false}>
                {buoys.map((entry) => (
                  <motion.div
                    key={entry.station_id ?? entry.title}
                    layout
                    initial={{ opacity: 0, y: -6 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0 }}
                    transition={{ duration: 0.25 }}
                  >
                    <BuoyCard entry={entry} />
                  </motion.div>
                ))}
              </AnimatePresence>
            </ul>
          )}

          {buoys.length === 0 && buoyUnavailable && (
            <PanelEmpty
              title="No buoy observations"
              reason={buoyUnavailable.unavailable_reason}
              className="py-5"
            />
          )}

          {products.length > 0 && (
            <div>
              <h3 className="px-3 pb-1 text-[9.5px] font-semibold tracking-widest text-[color:var(--oid-text-ghost)] uppercase">
                Latest products
              </h3>
              <ul>
                {products.map((entry) => (
                  <ProductRow key={entry.title} entry={entry} />
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </Panel>
  );
}
