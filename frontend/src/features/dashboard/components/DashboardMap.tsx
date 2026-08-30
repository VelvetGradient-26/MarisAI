/** The dashboard's map panel.
 *
 * Reuses the real map feature rather than building a second one. That view
 * already owns the layer registry (SST, chlorophyll, wind particles, EEZ,
 * marine protected areas, habitat and bloom-risk model output, live vessels),
 * the legends, the opacity controls and the cursor coordinate readout — all
 * driven by the same MapManager. Rebuilding any of it here would fork the
 * layer registry, which is the single source of truth for overlays.
 *
 * Loaded lazily: MapLibre plus the vector-field engine is the heaviest bundle
 * in the app, and the dashboard should render its KPIs without waiting for it.
 */

import { Suspense, lazy } from 'react';
import { Layers, Maximize2 } from 'lucide-react';
import { Link } from '../../../app/router';
import { Panel, PanelHeader } from './Panel';
import '../styles/embedded-map.css';

const MapView = lazy(() =>
  import('../../map/MapView').then((module) => ({ default: module.MapView }))
);

function MapFallback() {
  return (
    <div className="flex h-full items-center justify-center bg-[color:var(--oid-elevated)]">
      <div className="flex flex-col items-center gap-2 text-[color:var(--oid-text-faint)]">
        <Layers size={20} className="animate-[var(--animate-shimmer)]" />
        <span className="text-[length:var(--oid-text-sm)]">Loading map engine…</span>
      </div>
    </div>
  );
}

export function DashboardMap() {
  return (
    <Panel className="flex h-full flex-col">
      <PanelHeader
        icon={<Layers size={15} />}
        title="Ocean map"
        subtitle="Toggle layers, adjust opacity and inspect any point"
        actions={
          <Link
            to="/map"
            className="inline-flex items-center gap-1.5 rounded-full border border-[color:var(--oid-border)] px-2.5 py-1 text-[length:var(--oid-text-2xs)] text-[color:var(--oid-text)] no-underline transition-colors hover:bg-[color:var(--oid-track)]"
          >
            <Maximize2 size={11} />
            Full map
          </Link>
        }
      />
      <div className="oid-map-embed relative min-h-[420px] flex-1 overflow-hidden">
        <Suspense fallback={<MapFallback />}>
          <MapView />
        </Suspense>
      </div>
    </Panel>
  );
}
