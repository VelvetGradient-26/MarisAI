/** Ocean Intelligence Dashboard.
 *
 * Layout intent: the KPI row answers "what is the ocean doing", the map and
 * live feed answer "where", the alerts panel answers "what needs attention",
 * and the analytics grid answers "what changed". Sections are independent
 * queries so a slow or unavailable source degrades one panel, never the page.
 *
 * The selected point is shared with the rest of the app through `mapStore`,
 * the same way the existing analytics page works, so choosing a location here
 * or on the map keeps both in agreement.
 */

import { Suspense, lazy, useEffect, useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import { BookOpen, Globe2, MapPin, Search } from 'lucide-react';
import { Link } from '../../app/router';
import { useAppRouter } from '../../app/routerContext';
import { useMapStore } from '../../store/mapStore';
import { useThemeStore } from '../../store/themeStore';
import { useTimezoneStore } from '../../store/timezoneStore';
import { formatClockDate, formatClockTime } from '../../utils/formatTime';
import { AiInsights } from './components/AiInsights';
import { AlertsPanel } from './components/AlertsPanel';
import { DashboardMap } from './components/DashboardMap';
import { DataQualityPanel } from './components/DataQualityPanel';
import { HealthPanel } from './components/HealthPanel';
import { KpiCard, KpiGrid } from './components/KpiCard';
import { LiveFeed } from './components/LiveFeed';
import { Panel, PanelEmpty, PanelSkeleton } from './components/Panel';
import { SatelliteTable } from './components/SatelliteTable';
import { useSummary } from './hooks/useDashboardData';
import { useForecastCatalog } from './metric/hooks/useMetricData';
import { cn } from './lib/cn';
import './styles/tailwind.css';

/** Arabian Sea — inside both ML model domains, so those panels have data. */
const DEFAULT_LOCATION = { latitude: 15, longitude: 65 };

/**
 * Split out because it carries the whole Recharts runtime (~250kB), and the
 * charts sit below the fold. The KPI row, map and alerts render without
 * waiting for it.
 */
const AnalyticsGrid = lazy(() =>
  import('./components/AnalyticsGrid').then((module) => ({ default: module.AnalyticsGrid }))
);

function readCoordinates(searchParams: URLSearchParams) {
  if (!searchParams.has('lat') || !searchParams.has('lon')) return null;
  const latitude = Number(searchParams.get('lat'));
  const longitude = Number(searchParams.get('lon'));
  if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) return null;
  if (latitude < -90 || latitude > 90 || longitude < -180 || longitude > 180) return null;
  return { latitude, longitude };
}

/**
 * Owns the ticking clock so the rest of the dashboard does not re-render with
 * it. This was not a micro-optimisation: with the interval on the dashboard
 * root, every second re-rendered the whole tree, and Recharts restarted its
 * entry animation on each pass — the shorter series never finished drawing
 * and rendered as empty axes with correct statistics above them.
 */
function LiveClock({ timezone }: { timezone: string }) {
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const interval = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(interval);
  }, []);

  return (
    <div className="text-right">
      <div className="font-mono text-[15px] leading-none text-[color:var(--oid-text)]">
        {formatClockTime(now, timezone)}
      </div>
      <div className="mt-1 text-[length:var(--oid-text-3xs)] text-[color:var(--oid-text-faint)]">
        {formatClockDate(now, timezone)} · {timezone}
      </div>
    </div>
  );
}

function LocationBar({
  location,
  onSubmit,
}: {
  location: { latitude: number; longitude: number };
  onSubmit: (latitude: number, longitude: number) => void;
}) {
  const [latitudeText, setLatitudeText] = useState(String(location.latitude));
  const [longitudeText, setLongitudeText] = useState(String(location.longitude));
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLatitudeText(String(Number(location.latitude.toFixed(6))));
    setLongitudeText(String(Number(location.longitude.toFixed(6))));
  }, [location.latitude, location.longitude]);

  return (
    <form
      className="flex flex-wrap items-center gap-2"
      onSubmit={(event) => {
        event.preventDefault();
        const latitude = Number(latitudeText);
        const longitude = Number(longitudeText);
        if (
          !Number.isFinite(latitude) ||
          !Number.isFinite(longitude) ||
          Math.abs(latitude) > 90 ||
          Math.abs(longitude) > 180
        ) {
          setError('Latitude −90 to 90, longitude −180 to 180.');
          return;
        }
        setError(null);
        onSubmit(latitude, longitude);
      }}
    >
      <div className="flex items-center gap-1.5 rounded-full border border-[color:var(--oid-border)] bg-[color:var(--oid-elevated)] px-3 py-1.5">
        <MapPin size={13} className="text-[color:var(--oid-accent)]" />
        <label className="sr-only" htmlFor="oid-lat">
          Latitude
        </label>
        <input
          id="oid-lat"
          value={latitudeText}
          onChange={(event) => setLatitudeText(event.target.value)}
          inputMode="decimal"
          className="w-16 bg-transparent text-[length:var(--oid-text-base)] text-[color:var(--oid-text)] outline-none"
          aria-label="Latitude"
        />
        <span className="text-[color:var(--oid-text-ghost)]">,</span>
        <label className="sr-only" htmlFor="oid-lon">
          Longitude
        </label>
        <input
          id="oid-lon"
          value={longitudeText}
          onChange={(event) => setLongitudeText(event.target.value)}
          inputMode="decimal"
          className="w-16 bg-transparent text-[length:var(--oid-text-base)] text-[color:var(--oid-text)] outline-none"
          aria-label="Longitude"
        />
      </div>

      <button
        type="submit"
        className={cn(
          'inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-[length:var(--oid-text-sm)] font-medium',
          'bg-[color:var(--oid-accent-wash)]',
          'text-[color:var(--oid-accent)] transition-colors',
          'hover:bg-[color:var(--oid-accent-wash-strong)]'
        )}
      >
        <Search size={12} />
        Update
      </button>

      {error && (
        <span role="alert" className="text-[length:var(--oid-text-xs)] text-[color:var(--color-alert-critical)]">
          {error}
        </span>
      )}
    </form>
  );
}

export function OceanIntelligenceDashboard() {
  const { searchParams, navigate } = useAppRouter();
  const sharedLocation = useMapStore((state) => state.selectedLocation);
  const focusSelectedLocation = useMapStore((state) => state.focusSelectedLocation);
  const timezone = useTimezoneStore((state) => state.timezone);
  const isDark = useThemeStore((state) => state.dark);

  useEffect(() => {
    document.title = 'Maris AI | Ocean Intelligence';
  }, []);

  const urlLocation = readCoordinates(searchParams);
  const location = useMemo(
    () =>
      urlLocation ??
      (sharedLocation
        ? { latitude: sharedLocation.lat, longitude: sharedLocation.lng }
        : DEFAULT_LOCATION),
    [urlLocation, sharedLocation]
  );

  // Publish only an explicitly chosen point to the shared store — the default
  // was nobody's choice and should not drop a pin on the map.
  const urlLat = urlLocation?.latitude ?? null;
  const urlLon = urlLocation?.longitude ?? null;
  useEffect(() => {
    if (urlLat === null || urlLon === null) return;
    focusSelectedLocation({ lat: urlLat, lng: urlLon });
  }, [urlLat, urlLon, focusSelectedLocation]);

  const { data: summary, isPending, isError, error, refetch } = useSummary();
  const { data: catalog } = useForecastCatalog();

  const goTo = (latitude: number, longitude: number) => {
    navigate(`/dashboard?lat=${latitude}&lon=${longitude}`);
  };

  /**
   * A KPI card's metric page, when the card is a forecastable variable.
   *
   * Matched by exact key against the forecast catalog rather than by a
   * hand-written list, so a card whose key later becomes forecastable starts
   * linking on its own. Three of the six never will: heat-stress extent,
   * bleaching risk and habitat suitability are indices derived across a
   * region, not point variables, and they correctly resolve to undefined.
   */
  const metricLink = (cardKey: string): string | undefined => {
    const match = catalog?.variables.some((entry) => entry.key === cardKey);
    return match
      ? `/dashboard/${cardKey}?lat=${location.latitude}&lon=${location.longitude}`
      : undefined;
  };

  return (
    <div
      className={cn(
        'oid-root min-h-screen',
        // The page wash the glass panels read through. Both themes define it
        // as `--oid-page`, so this one class covers dark and light.
        'bg-[image:var(--oid-page)]',
        !isDark && 'oid-root--light'
      )}
      data-theme={isDark ? 'dark' : 'light'}
    >
      <main
        className="mx-auto max-w-[1800px] px-3 pb-10 sm:px-5"
        style={{ paddingTop: 'calc(var(--navbar-h, 64px) + 16px)' }}
      >
        <motion.header
          initial={{ opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
          className="mb-4 flex flex-wrap items-end justify-between gap-3"
        >
          <div>
            <div className="flex items-center gap-2">
              <Globe2 size={16} className="text-[color:var(--oid-accent)]" />
              <h1 className="text-[19px] leading-none font-semibold tracking-tight text-[color:var(--oid-text-strong)]">
                Ocean Intelligence
              </h1>
            </div>
            <p className="mt-1.5 text-[length:var(--oid-text-sm)] text-[color:var(--oid-text-faint)]">
              What the world’s oceans are doing right now, what changed, and what needs
              attention.{' '}
              <Link
                to="/docs?c=dash-overview"
                className="inline-flex items-center gap-1 text-[color:var(--oid-accent)] no-underline hover:underline"
              >
                <BookOpen size={11} />
                How to read this
              </Link>
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <LocationBar location={location} onSubmit={goTo} />
            <LiveClock timezone={timezone} />
          </div>
        </motion.header>

        {/* --- Section 1: hero KPIs --- */}
        <section aria-label="Key indicators" className="mb-4">
          {isPending && (
            <Panel>
              <PanelSkeleton rows={3} />
            </Panel>
          )}

          {isError && (
            <Panel>
              <PanelEmpty
                title="Indicators unavailable"
                reason={error instanceof Error ? error.message : undefined}
                onRetry={() => void refetch()}
              />
            </Panel>
          )}

          {summary && (
            <>
              <KpiGrid>
                {summary.cards.map((card, index) => (
                  <KpiCard
                    key={card.key}
                    card={card}
                    index={index}
                    to={metricLink(card.key)}
                  />
                ))}
              </KpiGrid>
              {summary.available_count < summary.cards.length && (
                <p className="mt-2 text-[length:var(--oid-text-2xs)] text-[color:var(--oid-text-ghost)]">
                  {summary.cards.length - summary.available_count} of {summary.cards.length}{' '}
                  indicators are waiting on a data source. Each card explains what it needs.
                </p>
              )}
            </>
          )}
        </section>

        {/* --- Sections 2 & 3: map centrepiece with the live feed alongside --- */}
        <section
          aria-label="Map and live feed"
          className="mb-4 grid grid-cols-1 gap-3 xl:grid-cols-[minmax(0,7fr)_minmax(320px,3fr)]"
        >
          <div className="min-h-[480px]">
            <DashboardMap />
          </div>
          <div className="max-h-[720px] min-h-[480px]">
            <LiveFeed location={location} />
          </div>
        </section>

        {/* --- Sections 5 & 6: insight and attention --- */}
        <section
          aria-label="Insights and alerts"
          className="mb-4 grid grid-cols-1 gap-3 lg:grid-cols-2"
        >
          <div className="min-h-[300px]">
            <AiInsights location={location} />
          </div>
          <div className="max-h-[520px] min-h-[300px]">
            <AlertsPanel onLocate={goTo} />
          </div>
        </section>

        {/* --- Section 4: historical analytics --- */}
        <div className="mb-4">
          <Suspense
            fallback={
              <Panel>
                <PanelSkeleton rows={4} />
              </Panel>
            }
          >
            <AnalyticsGrid latitude={location.latitude} longitude={location.longitude} />
          </Suspense>
        </div>

        {/* --- Sections 7 & 8: provenance --- */}
        <section
          aria-label="Satellite products and source health"
          className="grid grid-cols-1 gap-3 xl:grid-cols-2"
        >
          <div className="max-h-[460px] min-h-[300px]">
            <SatelliteTable />
          </div>
          <div className="max-h-[460px] min-h-[300px]">
            <HealthPanel />
          </div>
        </section>

        {/* --- Section 9: data quality ---
            Full width rather than a third column beside the two above: this
            one carries a dataset table and a 114-model grid, and squeezing it
            into a half-width panel is what made the model cards unreadable at
            the tablet breakpoint. */}
        <section aria-label="Data quality" className="mt-3">
          <div className="max-h-[560px] min-h-[360px]">
            <DataQualityPanel />
          </div>
        </section>

        <footer className="mt-6 text-[length:var(--oid-text-3xs)] leading-relaxed text-[color:var(--oid-text-ghost)]">
          Data from Copernicus Marine Service, NOAA Coral Reef Watch, NOAA NDBC, NASA GIBS and
          Open-Meteo, plus MarisAI’s own model exports. Derived alerts are threshold rules over
          model and satellite fields, not official marine warnings, and nothing here is suitable
          for navigation.
        </footer>
      </main>
    </div>
  );
}
