import { lazy, Suspense } from 'react';
import { DashboardPage } from '../pages/DashboardPage';
import { LandingPage } from '../pages/LandingPage';
import { useAppRouter } from './routerContext';

const MapView = lazy(() =>
  import('../features/map/MapView').then((module) => ({ default: module.MapView }))
);

export function App() {
  const { pathname } = useAppRouter();

  if (pathname === '/map') {
    return (
      <Suspense fallback={<div className="app-route-loading">Loading ocean map…</div>}>
        <MapView />
      </Suspense>
    );
  }
  if (pathname === '/dashboard') return <DashboardPage />;
  return <LandingPage />;
}
