/** The metric intelligence page.
 *
 * There is exactly one of these for all 32 variables, and it contains no
 * variable-specific logic — no name list, no switch, no per-variable branch.
 * It resolves the requested key against `/api/v1/forecast/catalog`, then walks
 * the section registry rendering every section whose requirement the variable
 * meets.
 *
 * That is the whole "future ready" property, and it is verifiable: a variable
 * added to `backend/forecasting/config/forecasting.yaml` and trained appears in
 * the catalog and gets a complete page with no change to this directory.
 */

import { Suspense, lazy, useEffect, useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import { AlertCircle, ChevronRight, Globe2, MapPin, Search } from 'lucide-react';
import { Link } from '../../../app/router';
import { useAppRouter } from '../../../app/routerContext';
import { useMapStore } from '../../../store/mapStore';
import { useThemeStore } from '../../../store/themeStore';
import { Panel, PanelEmpty, PanelSkeleton } from '../components/Panel';
import { cn } from '../lib/cn';
import { useForecastCatalog } from './hooks/useMetricData';
import { absenceReason, satisfies, type SectionDescriptor } from './sections';
import { MetricHero } from './sections/MetricHero';
import { KpiStrip } from './sections/KpiStrip';
import { OceanStory } from './sections/OceanStory';
import '../styles/tailwind.css';

/** Arabian Sea — inside the trained models' domain, so panels have data. */
const DEFAULT_LOCATION = { latitude: 15, longitude: 65 };

// The heavy sections carry uPlot and the model-detail queries, and all three
// sit below the fold. Splitting them keeps the hero and story interactive
// while they load.
const ForecastSection = lazy(() =>
  import('./sections/ForecastSection').then((m) => ({ default: m.ForecastSection }))
);
const HistoricalAnalysis = lazy(() =>
  import('./sections/HistoricalAnalysis').then((m) => ({ default: m.HistoricalAnalysis }))
);
const Explainability = lazy(() =>
  import('./sections/Explainability').then((m) => ({ default: m.Explainability }))
);
const RelatedVariables = lazy(() =>
  import('./sections/RelatedVariables').then((m) => ({ default: m.RelatedVariables }))
);
const Downloads = lazy(() =>
  import('./sections/Downloads').then((m) => ({ default: m.Downloads }))
);

const SECTIONS: SectionDescriptor[] = [
  { id: 'overview', title: 'Overview', requires: 'history', component: MetricHero, eager: true },
  { id: 'indicators', title: 'Indicators', requires: 'history', component: KpiStrip, eager: true },
  { id: 'story', title: 'Ocean Story', requires: 'history', component: OceanStory, eager: true },
  { id: 'forecast', title: 'Forecast', requires: 'forecast', component: ForecastSection, minHeight: 460 },
  { id: 'history', title: 'Historical', requires: 'history', component: HistoricalAnalysis, minHeight: 480 },
  { id: 'explain', title: 'Explainability', requires: 'explainability', component: Explainability, minHeight: 380 },
  { id: 'related', title: 'Related', requires: 'history', component: RelatedVariables, minHeight: 200 },
  { id: 'downloads', title: 'Downloads', requires: 'history', component: Downloads, minHeight: 160 },
];

/** How far outside the viewport a section counts as worth mounting. */
const PRELOAD_MARGIN_PX = 300;

/**
 * Mounts children once they approach the viewport.
 *
 * Measures geometry directly rather than trusting `IntersectionObserver`
 * alone — `AnalyticsGrid` documents why: in this app the observer was
 * constructed and observing but never fired a callback, leaving every chart
 * unmounted. The observer is kept as an extra trigger, not the mechanism.
 */
function LazySection({
  children,
  minHeight = 300,
}: {
  children: React.ReactNode;
  minHeight?: number;
}) {
  const [shown, setShown] = useState(false);
  const [node, setNode] = useState<HTMLDivElement | null>(null);

  useEffect(() => {
    if (shown || !node) return;
    let frame = 0;

    const near = () => {
      const rect = node.getBoundingClientRect();
      const height = window.innerHeight || document.documentElement.clientHeight;
      return rect.top < height + PRELOAD_MARGIN_PX && rect.bottom > -PRELOAD_MARGIN_PX;
    };

    const check = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        if (near()) setShown(true);
      });
    };

    check();
    window.addEventListener('scroll', check, { passive: true });
    window.addEventListener('resize', check);
    const observer = new IntersectionObserver(check, {
      rootMargin: `${PRELOAD_MARGIN_PX}px`,
    });
    observer.observe(node);

    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener('scroll', check);
      window.removeEventListener('resize', check);
      observer.disconnect();
    };
  }, [shown, node]);

  return (
    <div ref={setNode} style={shown ? undefined : { minHeight }}>
      {shown ? children : null}
    </div>
  );
}

function readCoordinates(searchParams: URLSearchParams) {
  if (!searchParams.has('lat') || !searchParams.has('lon')) return null;
  const latitude = Number(searchParams.get('lat'));
  const longitude = Number(searchParams.get('lon'));
  if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) return null;
  if (Math.abs(latitude) > 90 || Math.abs(longitude) > 180) return null;
  return { latitude, longitude };
}

function Breadcrumb({ label }: { label: string }) {
  const crumb = 'text-[color:var(--oid-text-faint)] no-underline hover:text-[color:var(--oid-accent)]';
  return (
    <nav aria-label="Breadcrumb" className="flex items-center gap-1.5 text-[length:var(--oid-text-sm)]">
      <Link to="/" className={crumb}>
        Home
      </Link>
      <ChevronRight size={12} className="text-[color:var(--oid-text-ghost)]" />
      <Link to="/dashboard" className={crumb}>
        Dashboard
      </Link>
      <ChevronRight size={12} className="text-[color:var(--oid-text-ghost)]" />
      <span className="text-[color:var(--oid-text)]">{label}</span>
    </nav>
  );
}

export function MetricIntelligencePage({ variableKey }: { variableKey: string }) {
  const { searchParams, navigate } = useAppRouter();
  const isDark = useThemeStore((state) => state.dark);
  const sharedLocation = useMapStore((state) => state.selectedLocation);

  const { data: catalog, isPending, isError, error, refetch } = useForecastCatalog();

  const urlLocation = readCoordinates(searchParams);
  const location = useMemo(
    () =>
      urlLocation ??
      (sharedLocation
        ? { latitude: sharedLocation.lat, longitude: sharedLocation.lng }
        : DEFAULT_LOCATION),
    [urlLocation, sharedLocation]
  );

  const variable = catalog?.variables.find((entry) => entry.key === variableKey) ?? null;

  useEffect(() => {
    document.title = variable
      ? `${variable.label} | Maris AI`
      : 'Metric | Maris AI';
  }, [variable]);

  const visible = useMemo(
    () => (variable ? SECTIONS.filter((section) => satisfies(section.requires, variable)) : []),
    [variable]
  );

  const omitted = useMemo(() => {
    if (!variable) return [];
    return SECTIONS.filter((section) => !satisfies(section.requires, variable))
      .map((section) => ({ section, reason: absenceReason(section.requires, variable) }))
      .filter((item) => item.reason);
  }, [variable]);

  const shell = (children: React.ReactNode) => (
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
        {children}
      </main>
    </div>
  );

  if (isPending) {
    return shell(
      <Panel>
        <PanelSkeleton rows={5} />
      </Panel>
    );
  }

  if (isError) {
    return shell(
      <Panel>
        <PanelEmpty
          title="Could not load the metric catalog"
          reason={error instanceof Error ? error.message : undefined}
          onRetry={() => void refetch()}
        />
      </Panel>
    );
  }

  if (!variable) {
    return shell(
      <>
        <Breadcrumb label="Unknown metric" />
        <Panel className="mt-4">
          <PanelEmpty
            icon={<AlertCircle size={20} />}
            title={`No metric called “${variableKey}”`}
            reason={`This platform forecasts ${catalog?.variables.length ?? 0} variables. Browse them all from the metrics index.`}
          />
          <div className="px-5 pb-5 text-center">
            <Link
              to="/dashboard/metrics"
              className="text-[length:var(--oid-text-base)] text-[color:var(--oid-accent)] no-underline hover:underline"
            >
              See all metrics
            </Link>
          </div>
        </Panel>
      </>
    );
  }

  return shell(
    <>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <Breadcrumb label={variable.label} />
        <LocationControl
          location={location}
          onSubmit={(latitude, longitude) =>
            navigate(`/dashboard/${variable.key}?lat=${latitude}&lon=${longitude}`)
          }
        />
      </div>

      {/* In-page navigation. Anchors rather than a router, so the browser's own
          scrolling and back-button behaviour are preserved. */}
      <motion.nav
        initial={{ opacity: 0, y: -6 }}
        animate={{ opacity: 1, y: 0 }}
        className="mb-4 flex flex-wrap gap-1.5"
        aria-label="Sections"
      >
        {visible.map((section) => (
          <a
            key={section.id}
            href={`#${section.id}`}
            className={cn(
              'rounded-full border px-3 py-1 text-[length:var(--oid-text-xs)] no-underline transition-colors',
              'border-[color:var(--oid-border)] text-[color:var(--oid-text-faint)]',
              'hover:bg-[color:var(--oid-track)] hover:text-[color:var(--oid-accent)]'
            )}
          >
            {section.title}
          </a>
        ))}
      </motion.nav>

      <div className="space-y-4">
        {visible.map((section) => {
          const Component = section.component;
          const content = (
            <section id={section.id} aria-label={section.title} className="scroll-mt-20">
              <Component
                variable={variable}
                latitude={location.latitude}
                longitude={location.longitude}
              />
            </section>
          );

          if (section.eager) return <div key={section.id}>{content}</div>;

          return (
            <LazySection key={section.id} minHeight={section.minHeight}>
              <Suspense
                fallback={
                  <Panel>
                    <PanelSkeleton rows={4} />
                  </Panel>
                }
              >
                {content}
              </Suspense>
            </LazySection>
          );
        })}
      </div>

      {/* Sections that are absent say why, rather than leaving a silent gap. */}
      {omitted.length > 0 && (
        <Panel className="mt-4">
          <div className="p-4">
            <h2 className="text-[length:var(--oid-text-xs)] font-medium tracking-wide text-[color:var(--oid-text-muted)] uppercase">
              Not shown for this metric
            </h2>
            <ul className="mt-2 space-y-1.5">
              {omitted.map(({ section, reason }) => (
                <li key={section.id} className="text-[length:var(--oid-text-sm)] text-[color:var(--oid-text-faint)]">
                  <span className="text-[color:var(--oid-text)]">{section.title}</span> — {reason}
                </li>
              ))}
            </ul>
          </div>
        </Panel>
      )}

      <footer className="mt-6 text-[length:var(--oid-text-3xs)] leading-relaxed text-[color:var(--oid-text-ghost)]">
        Values are model and satellite-derived, from Copernicus Marine Service, Open-Meteo and
        GEBCO. Forecasts are statistical, validated by rolling-origin cross-validation, and are
        not official marine warnings or suitable for navigation.
      </footer>
    </>
  );
}

function LocationControl({
  location,
  onSubmit,
}: {
  location: { latitude: number; longitude: number };
  onSubmit: (latitude: number, longitude: number) => void;
}) {
  const [latitudeText, setLatitudeText] = useState(String(location.latitude));
  const [longitudeText, setLongitudeText] = useState(String(location.longitude));

  useEffect(() => {
    setLatitudeText(String(Number(location.latitude.toFixed(6))));
    setLongitudeText(String(Number(location.longitude.toFixed(6))));
  }, [location.latitude, location.longitude]);

  return (
    <form
      className="flex items-center gap-2"
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
          return;
        }
        onSubmit(latitude, longitude);
      }}
    >
      <div className="flex items-center gap-1.5 rounded-full border border-[color:var(--oid-border)] bg-[color:var(--oid-elevated)] px-3 py-1.5">
        <MapPin size={12} className="text-[color:var(--oid-accent)]" />
        <input
          value={latitudeText}
          onChange={(event) => setLatitudeText(event.target.value)}
          inputMode="decimal"
          aria-label="Latitude"
          className="w-14 bg-transparent text-[length:var(--oid-text-sm)] text-[color:var(--oid-text)] outline-none"
        />
        <span className="text-[color:var(--oid-text-ghost)]">,</span>
        <input
          value={longitudeText}
          onChange={(event) => setLongitudeText(event.target.value)}
          inputMode="decimal"
          aria-label="Longitude"
          className="w-14 bg-transparent text-[length:var(--oid-text-sm)] text-[color:var(--oid-text)] outline-none"
        />
      </div>
      <button
        type="submit"
        className="inline-flex items-center gap-1.5 rounded-full bg-[color:var(--oid-accent-wash)] px-3 py-1.5 text-[length:var(--oid-text-xs)] font-medium text-[color:var(--oid-accent)] transition-colors hover:bg-[color:var(--oid-accent-wash-strong)]"
      >
        <Search size={11} />
        Update
      </button>
      <Link
        to="/dashboard/metrics"
        title="All metrics"
        className="inline-flex items-center gap-1.5 rounded-full border border-[color:var(--oid-border)] px-3 py-1.5 text-[length:var(--oid-text-xs)] text-[color:var(--oid-text-faint)] no-underline transition-colors hover:text-[color:var(--oid-accent)]"
      >
        <Globe2 size={11} />
        All metrics
      </Link>
    </form>
  );
}
