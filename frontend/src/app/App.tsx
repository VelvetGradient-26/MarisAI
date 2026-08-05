import { lazy, Suspense } from 'react';
import { Navbar } from '../components/Navbar';
import { DashboardPage } from '../pages/DashboardPage';
import { LandingPage } from '../pages/LandingPage';
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

  return (
    <>
      <Navbar overlay={pathname === '/map'} />
      {renderPage(pathname)}
    </>
  );
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
  return <LandingPage />;
}
