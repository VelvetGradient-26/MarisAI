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
const PredictionsPage = lazy(() =>
  import('../pages/PredictionsPage').then((module) => ({ default: module.PredictionsPage }))
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
  if (pathname === '/predictions') {
    return (
      <Suspense fallback={<div className="app-route-loading">Loading model insights…</div>}>
        <PredictionsPage />
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
  if (pathname === '/dashboard') return <DashboardPage />;
  return <LandingPage />;
}
