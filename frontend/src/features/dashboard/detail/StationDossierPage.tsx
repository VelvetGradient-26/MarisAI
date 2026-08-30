/** One NDBC buoy's detail — the click-through target from a Live Ocean Feed
 * card, whose whole job is proving provenance: this is a real instrument
 * reporting real numbers, not a placeholder row.
 *
 * The identity/reading half is presentation of `services/ndbc.py`'s existing
 * per-observation shape, looked up by station id rather than filtered to the
 * nearest few. The `raw_feed` half is new: a short excerpt of the station's
 * own live NDBC text file, fetched on demand (not cached) — proof a reader
 * could independently verify by following the linked URL themselves.
 */

import { useEffect } from 'react';
import { useAppRouter } from '../../../app/routerContext';
import { useThemeStore } from '../../../store/themeStore';
import { useStationDetail } from '../hooks/useDashboardData';
import { Breadcrumb } from '../components/Breadcrumb';
import { Panel, PanelEmpty, PanelHeader, PanelSkeleton } from '../components/Panel';
import { cn } from '../lib/cn';
import '../styles/tailwind.css';

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div>
      <dt className="text-[length:var(--oid-text-4xs)] tracking-wide text-[color:var(--oid-text-ghost)] uppercase">{label}</dt>
      <dd className="text-[length:var(--oid-text-lg)] font-medium text-[color:var(--oid-text-strong)]">{value}</dd>
      {hint && <p className="mt-0.5 text-[length:var(--oid-text-3xs)] leading-tight text-[color:var(--oid-text-faint)]">{hint}</p>}
    </div>
  );
}

function fmt(value: number | null | undefined, unit: string, digits = 1): string {
  return value == null ? '—' : `${value.toFixed(digits)} ${unit}`;
}

export function StationDossierPage() {
  const { searchParams } = useAppRouter();
  const isDark = useThemeStore((state) => state.dark);

  const stationId = (searchParams.get('id') ?? '').trim();
  const { data, isPending, isError, error, refetch } = useStationDetail(stationId, {
    enabled: stationId.length > 0,
  });

  useEffect(() => {
    document.title = stationId
      ? `Station ${stationId} | Maris AI`
      : 'Station detail | Maris AI';
  }, [stationId]);

  const station = data?.station;

  return (
    <div
      className={cn('oid-root min-h-screen bg-[image:var(--oid-page)]', !isDark && 'oid-root--light')}
      data-theme={isDark ? 'dark' : 'light'}
    >
      <main
        className="mx-auto max-w-[900px] px-3 pb-16 sm:px-5"
        style={{ paddingTop: 'calc(var(--navbar-h, 64px) + 16px)' }}
      >
        <Breadcrumb current={stationId ? `Station ${stationId}` : '—'} />

        {!stationId ? (
          <Panel className="mt-4">
            <PanelEmpty
              title="No station specified"
              reason="This page needs a ?id= — open it from a card on the Live Ocean Feed panel."
            />
          </Panel>
        ) : (
          <>
            <header className="mt-3 mb-5">
              <h1 className="text-[22px] leading-none font-semibold tracking-tight text-[color:var(--oid-text-strong)]">
                NDBC Station {stationId}
              </h1>
              <p className="mt-1.5 text-[length:var(--oid-text-sm)] text-[color:var(--oid-text-faint)]">
                A real NOAA buoy — coordinates, its latest report, and an excerpt of its own live
                feed as proof.
              </p>
            </header>

            {isPending && (
              <Panel>
                <PanelSkeleton rows={5} />
              </Panel>
            )}

            {isError && (
              <Panel>
                <PanelEmpty
                  title="Station unavailable"
                  reason={error instanceof Error ? error.message : undefined}
                  onRetry={() => void refetch()}
                />
              </Panel>
            )}

            {station && (
              <div className="grid grid-cols-1 gap-4">
                <Panel>
                  <PanelHeader
                    title="Identity"
                    subtitle={station.is_fresh ? 'Reporting within the last 6 hours' : 'No recent report'}
                  />
                  <div className="grid grid-cols-2 gap-4 p-4 sm:grid-cols-4">
                    <Stat label="Station ID" value={station.station_id} />
                    <Stat
                      label="Coordinates"
                      value={`${station.latitude.toFixed(3)}, ${station.longitude.toFixed(3)}`}
                    />
                    <Stat label="Observed at" value={new Date(station.observed_at).toUTCString()} />
                    <Stat
                      label="Source"
                      value="NOAA NDBC"
                      hint="National Data Buoy Center"
                    />
                  </div>
                </Panel>

                <Panel>
                  <PanelHeader title="Latest reading" subtitle="Whatever this station's own sensors carry" />
                  <div className="grid grid-cols-2 gap-4 p-4 sm:grid-cols-4">
                    <Stat label="Water temperature" value={fmt(station.water_temperature_c, '°C')} />
                    <Stat label="Air temperature" value={fmt(station.air_temperature_c, '°C')} />
                    <Stat label="Wave height" value={fmt(station.wave_height_m, 'm')} />
                    <Stat
                      label="Dominant wave period"
                      value={fmt(station.dominant_wave_period_s, 's')}
                    />
                    <Stat label="Wind speed" value={fmt(station.wind_speed_ms, 'm/s')} />
                    <Stat label="Wind gust" value={fmt(station.wind_gust_ms, 'm/s')} />
                    <Stat
                      label="Wind direction"
                      value={fmt(station.wind_direction_deg, '°', 0)}
                    />
                    <Stat label="Pressure" value={fmt(station.pressure_hpa, 'hPa')} />
                    <Stat label="Dewpoint" value={fmt(station.dewpoint_c, '°C')} />
                    <Stat
                      label="Relative humidity"
                      value={fmt(station.relative_humidity_pct, '%', 0)}
                      hint="Derived from air temperature and dewpoint"
                    />
                    <Stat label="Visibility" value={fmt(station.visibility_nmi, 'nmi')} />
                  </div>
                </Panel>

                <Panel>
                  <PanelHeader
                    title="Live feed excerpt"
                    subtitle="Fetched from this station's own NDBC text feed, on demand"
                  />
                  <div className="p-4">
                    {data.raw_feed ? (
                      <>
                        <pre className="oid-scroll max-h-56 overflow-auto rounded-lg border border-[color:var(--oid-border)] bg-[color:var(--oid-elevated)] p-3 font-mono text-[length:var(--oid-text-2xs)] leading-relaxed text-[color:var(--oid-text-muted)]">
                          {data.raw_feed.lines.join('\n')}
                        </pre>
                        <p className="mt-2 text-[length:var(--oid-text-3xs)] text-[color:var(--oid-text-ghost)]">
                          {data.raw_feed.lines.length} of {data.raw_feed.total_lines} lines shown ·{' '}
                          <a
                            href={data.raw_feed.url}
                            target="_blank"
                            rel="noreferrer"
                            className="text-[color:var(--oid-accent)] no-underline hover:underline"
                          >
                            view the full feed at NDBC
                          </a>
                        </p>
                      </>
                    ) : (
                      <p className="text-[length:var(--oid-text-xs)] text-[color:var(--oid-text-faint)]">
                        {data.raw_feed_error ?? 'The live feed excerpt could not be fetched.'}
                      </p>
                    )}
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
