import { lazy, Suspense, useEffect } from 'react';
import type { ReactNode } from 'react';
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import { ErrorBoundary } from '../components/ErrorBoundary';
import { Navbar } from '../components/Navbar';
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

  return (
    <>
      <Navbar overlay={route === '/map'} />
      {/* Keyed on the route so a failure on one page clears when you navigate
          away, instead of latching for the rest of the session. The navbar
          sits outside so there is always a way out of a broken page. */}
      <ErrorBoundary resetKey={route}>
        <RouteTransition route={route}>{renderPage(route)}</RouteTransition>
      </ErrorBoundary>
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
      <Suspense fallback={<div className="app-route-loading">Loading ocean map…</div>}>
        <MapView />
      </Suspense>
    );
  }
  if (pathname === '/download') {
    return (
      <Suspense fallback={<div className="app-route-loading">Loading downloader…</div>}>
        <DownloadPage />
      </Suspense>
    );
  }
  if (pathname === '/docs') {
    return (
      <Suspense fallback={<div className="app-route-loading">Loading docs…</div>}>
        <DocsPage />
      </Suspense>
    );
  }
  if (pathname === '/feedback') {
    return (
      <Suspense fallback={<div className="app-route-loading">Loading feedback form…</div>}>
        <FeedbackPage />
      </Suspense>
    );
  }
  if (pathname === '/contact') {
    return (
      <Suspense fallback={<div className="app-route-loading">Loading…</div>}>
        <ContactPage />
      </Suspense>
    );
  }
  if (pathname === '/assistant') {
    return (
      <Suspense fallback={<div className="app-route-loading">Loading assistant…</div>}>
        <ChatPage />
      </Suspense>
    );
  }
  if (pathname === '/compare') {
    return (
      <Suspense fallback={<div className="app-route-loading">Loading comparison…</div>}>
        <ComparePage />
      </Suspense>
    );
  }
  if (pathname === '/dashboard') {
    return (
      <Suspense fallback={<div className="app-route-loading">Loading ocean intelligence…</div>}>
        <OceanIntelligenceDashboard />
      </Suspense>
    );
  }
  if (pathname === '/dashboard/metrics') {
    return (
      <Suspense fallback={<div className="app-route-loading">Loading metrics…</div>}>
        <MetricsIndexPage />
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
        <Suspense fallback={<div className="app-route-loading">Loading metric…</div>}>
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
