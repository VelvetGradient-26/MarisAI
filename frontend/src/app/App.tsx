import { lazy, Suspense, useEffect } from 'react';
import type { ReactNode } from 'react';
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import { ErrorBoundary } from '../components/ErrorBoundary';
import { Cursor, Grain, Preloader, ScrollRail, SmoothScroll } from '../components/craft';
import { Navbar } from '../components/Navbar';
import { RouteLoading } from '../components/RouteLoading';
import { Toaster } from '../components/Toaster';
import { DashboardPage } from '../pages/DashboardPage';
import { LandingPage } from '../pages/LandingPage';
import { NotFoundPage } from '../pages/NotFoundPage';
import { useThemeStore } from '../store/themeStore';
import { useAppRouter } from './routerContext';

const MapView = lazy(() =>
  import('../features/map/MapView').then((module) => ({ default: module.MapView }))
);
const DownloadPage = lazy(() =>
  import('../pages/DownloadPage').then((module) => ({ default: module.DownloadPage }))
);
const FeedbackPage = lazy(() =>
  import('../pages/FeedbackPage').then((module) => ({ default: module.FeedbackPage }))
);
const ContactPage = lazy(() =>
  import('../pages/ContactPage').then((module) => ({ default: module.ContactPage }))
);
const ConfirmWatchPage = lazy(() =>
  import('../pages/ConfirmWatchPage').then((module) => ({ default: module.ConfirmWatchPage }))
);
const UnsubscribeWatchPage = lazy(() =>
  import('../pages/UnsubscribeWatchPage').then((module) => ({ default: module.UnsubscribeWatchPage }))
);
const DocsPage = lazy(() =>
  import('../pages/docs/DocsPage').then((module) => ({ default: module.DocsPage }))
);
const ChatPage = lazy(() =>
  import('../pages/ChatPage').then((module) => ({ default: module.ChatPage }))
);
const ComparePage = lazy(() =>
  import('../pages/ComparePage').then((module) => ({ default: module.ComparePage }))
);
// Lazy for the same reason as the map: this route pulls in Recharts and,
// through its embedded map panel, MapLibre — neither belongs in the bundle
// served to someone landing on the home page.
const OceanIntelligenceDashboard = lazy(() =>
  import('../features/dashboard/OceanIntelligenceDashboard').then((module) => ({
    default: module.OceanIntelligenceDashboard,
  }))
);
// The per-variable intelligence page and its index. Split separately from the
// dashboard above: they carry uPlot, which the dashboard itself never loads.
const MetricIntelligencePage = lazy(() =>
  import('../features/dashboard/metric/MetricIntelligencePage').then((module) => ({
    default: module.MetricIntelligencePage,
  }))
);
const MetricsIndexPage = lazy(() =>
  import('../features/dashboard/metric/MetricsIndexPage').then((module) => ({
    default: module.MetricsIndexPage,
  }))
);
const ModelDossierPage = lazy(() =>
  import('../features/dashboard/metric/ModelDossierPage').then((module) => ({
    default: module.ModelDossierPage,
  }))
);
// The same "click a card, see the full record" treatment as ModelDossierPage,
// for the three other dashboard panels whose rows didn't link anywhere.
const StationDossierPage = lazy(() =>
  import('../features/dashboard/detail/StationDossierPage').then((module) => ({
    default: module.StationDossierPage,
  }))
);
const SatelliteDossierPage = lazy(() =>
  import('../features/dashboard/detail/SatelliteDossierPage').then((module) => ({
    default: module.SatelliteDossierPage,
  }))
);
const SourceDossierPage = lazy(() =>
  import('../features/dashboard/detail/SourceDossierPage').then((module) => ({
    default: module.SourceDossierPage,
  }))
);

export function App() {
  const { pathname } = useAppRouter();
  const dark = useThemeStore((s) => s.dark);

  // Stamp the theme on <html>, which is what drives the shared `--ma-*` tokens
  // in styles/tokens.css and, through `color-scheme`, the browser's own
  // widgets — scrollbars, date pickers, select popups. Pages keep their own
  // `--light` class too; this is the layer that covers everything outside a
  // page root, and everything rendered by the browser rather than by us.
  // index.html stamps the same attribute before first paint so there is no
  // flash of the wrong theme; this keeps it in sync afterwards.
  useEffect(() => {
    document.documentElement.dataset.theme = dark ? 'dark' : 'light';
  }, [dark]);

  const route = normalizePath(pathname);
  // The map is a single full-bleed viewport that owns the wheel gesture (it is
  // the camera's zoom), whose content is a live canvas, and which communicates
  // through the native cursor (grab / grabbing / crosshair). All four craft
  // surfaces below are therefore off there, each for its own stated reason —
  // see SmoothScroll, ScrollRail, Grain and Cursor. The preloader is the
  // exception: it precedes any route.
  const isMap = route === '/map';
  const scrolls = !isMap;

  useEffect(() => {
    // The map route needs `html, body, #root { height: 100% }` to be exactly
    // that; Lenis relaxes it to `auto` via the class it stamps on <html>, and
    // although the component removes the class on unmount, the stamp and the
    // route change land in the same commit. Clearing it here as well makes the
    // ordering irrelevant rather than lucky.
    if (!scrolls) document.documentElement.classList.remove('lenis', 'lenis-smooth');
  }, [scrolls]);

  return (
    <>
      {/* Mounted before anything else so the curtain is already painted when
          the first page renders behind it. */}
      <Preloader />
      <SmoothScroll enabled={scrolls} />
      <Navbar overlay={isMap} />
      {scrolls ? <ScrollRail /> : null}
      {/* Keyed on the route so a failure on one page clears when you navigate
          away, instead of latching for the rest of the session. The navbar
          sits outside so there is always a way out of a broken page. */}
      <ErrorBoundary resetKey={route}>
        <RouteTransition route={route}>{renderPage(route)}</RouteTransition>
      </ErrorBoundary>
      {scrolls ? <Grain /> : null}
      {/* Last, and outside the boundary. The cursor must survive a page crash —
          a broken page the pointer has vanished from is unrecoverable. */}
      <Cursor enabled={!isMap} />
      {/* Outside the boundary: a toast reporting that something failed has to
          outlive the page that failed. */}
      <Toaster />
    </>
  );
}

/**
 * Cross-fades between routes.
 *
 * **`/map` is deliberately excluded, and this is not a style choice.** The map
 * route owns a MapLibre instance built by `useMapManager`; wrapping it in a
 * keyed, animated element makes React unmount and remount it on every
 * navigation, which destroys and rebuilds the WebGL context, refetches the
 * basemap and drops the layer state that `mapPreferencesStore` exists to
 * preserve. It would also keep the outgoing page mounted during the exit
 * animation, so for those milliseconds there would be two live maps.
 *
 * Everything else is cheap to remount, so it animates.
 *
 * `mode="wait"` rather than a crossfade in place: these pages are full-height
 * and overlapping two of them mid-transition produces a scrollbar that jumps.
 */
function RouteTransition({ route, children }: { route: string; children: ReactNode }) {
  const reduce = useReducedMotion();

  if (route === '/map') return <>{children}</>;

  return (
    <AnimatePresence mode="wait" initial={false}>
      <motion.div
        key={route}
        initial={{ opacity: 0, y: reduce ? 0 : 8 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: reduce ? 0 : -6 }}
        transition={{ duration: 0.24, ease: [0.22, 0.61, 0.36, 1] }}
      >
        {children}
      </motion.div>
    </AnimatePresence>
  );
}

/** Collapses the trailing-slash variants onto one route, so `/download/` is
 *  the download page rather than a 404. `/` itself is preserved. */
function normalizePath(pathname: string): string {
  const trimmed = pathname.replace(/\/+$/, '');
  return trimmed === '' ? '/' : trimmed;
}

function renderPage(pathname: string) {
  if (pathname === '/map') {
    return (
      <Suspense fallback={<RouteLoading label="Loading ocean map…" />}>
        <MapView />
      </Suspense>
    );
  }
  if (pathname === '/download') {
    return (
      <Suspense fallback={<RouteLoading label="Loading downloader…" />}>
        <DownloadPage />
      </Suspense>
    );
  }
  if (pathname === '/docs') {
    return (
      <Suspense fallback={<RouteLoading label="Loading docs…" />}>
        <DocsPage />
      </Suspense>
    );
  }
  if (pathname === '/feedback') {
    return (
      <Suspense fallback={<RouteLoading label="Loading feedback form…" />}>
        <FeedbackPage />
      </Suspense>
    );
  }
  if (pathname === '/contact') {
    return (
      <Suspense fallback={<RouteLoading label="Loading…" />}>
        <ContactPage />
      </Suspense>
    );
  }
  if (pathname === '/confirm-watch') {
    return (
      <Suspense fallback={<RouteLoading label="Loading…" />}>
        <ConfirmWatchPage />
      </Suspense>
    );
  }
  if (pathname === '/unsubscribe-watch') {
    return (
      <Suspense fallback={<RouteLoading label="Loading…" />}>
        <UnsubscribeWatchPage />
      </Suspense>
    );
  }
  if (pathname === '/assistant') {
    return (
      <Suspense fallback={<RouteLoading label="Loading assistant…" />}>
        <ChatPage />
      </Suspense>
    );
  }
  if (pathname === '/compare') {
    return (
      <Suspense fallback={<RouteLoading label="Loading comparison…" />}>
        <ComparePage />
      </Suspense>
    );
  }
  if (pathname === '/dashboard') {
    return (
      <Suspense fallback={<RouteLoading label="Loading ocean intelligence…" />}>
        <OceanIntelligenceDashboard />
      </Suspense>
    );
  }
  if (pathname === '/dashboard/metrics') {
    return (
      <Suspense fallback={<RouteLoading label="Loading metrics…" />}>
        <MetricsIndexPage />
      </Suspense>
    );
  }
  // Reads ?variable=&horizon= from the query string rather than nested path
  // segments — the generic `/dashboard/<key>` branch below only ever matches
  // a single segment (`!variableKey.includes('/')`), so `/dashboard/model`
  // has to be its own exact match, checked before that prefix, or it would
  // itself be swallowed as variableKey="model".
  if (pathname === '/dashboard/model') {
    return (
      <Suspense fallback={<RouteLoading label="Loading model dossier…" />}>
        <ModelDossierPage />
      </Suspense>
    );
  }
  if (pathname === '/dashboard/station') {
    return (
      <Suspense fallback={<RouteLoading label="Loading station…" />}>
        <StationDossierPage />
      </Suspense>
    );
  }
  if (pathname === '/dashboard/satellite') {
    return (
      <Suspense fallback={<RouteLoading label="Loading satellite product…" />}>
        <SatelliteDossierPage />
      </Suspense>
    );
  }
  if (pathname === '/dashboard/source') {
    return (
      <Suspense fallback={<RouteLoading label="Loading data source…" />}>
        <SourceDossierPage />
      </Suspense>
    );
  }
  // The only parameterised route in this hand-rolled router. One page serves
  // every variable — it resolves the key against the forecast catalog rather
  // than against anything hardcoded here, so a newly trained variable becomes
  // reachable without touching this file.
  if (pathname.startsWith('/dashboard/')) {
    const variableKey = decodeURIComponent(pathname.slice('/dashboard/'.length)).replace(
      /\/+$/,
      ''
    );
    if (variableKey && !variableKey.includes('/')) {
      return (
        <Suspense fallback={<RouteLoading label="Loading metric…" />}>
          <MetricIntelligencePage variableKey={variableKey} />
        </Suspense>
      );
    }
  }
  // The original point-analytics view, kept on its own route: it answers a
  // narrower question (every metric at one coordinate) that the global
  // dashboard does not replace.
  if (pathname === '/analytics') return <DashboardPage />;
  if (pathname === '/') return <LandingPage />;
  // Anything else is genuinely not a route. This used to fall through to the
  // landing page, which made a stale or mistyped link look like a working one.
  return <NotFoundPage />;
}
