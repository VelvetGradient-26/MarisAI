/**
 * A small map embedded below a chat turn's answer, drawing whatever route /
 * drift-trajectory / geofence / fishing-zone geometry that turn's tool calls
 * produced — see `api/chatGeometry.ts` for how the raw tool results become
 * a `FeatureCollection`, and `layerRegistry.ts`'s `chatGeometryLayer()` for
 * how it's painted.
 *
 * Deliberately does NOT reuse `features/map/Map.tsx` the way
 * `DashboardMap.tsx` reuses the full `MapView` ("the embedded map
 * overrides, it does not fork" — CLAUDE.md). Two reasons that convention
 * doesn't fit here:
 *  - `useMapManager` is written for exactly one instance app-wide (its own
 *    docstring says so) and wires every pan/zoom/click straight into the
 *    shared `mapStore`/`mapPreferencesStore` the real `/map` page reads back
 *    on its own next mount. A single conversation can carry several of these
 *    previews at once, each a self-contained illustration of one tool
 *    result — panning one must never silently relocate the real map's
 *    camera for later.
 *  - `Map.tsx` also mounts every live layer hook (vessels, eddies, cyclones,
 *    three detector-cell pollers, forecast layers) regardless of children —
 *    far more network activity than a static geometry preview needs, times
 *    however many of these are on screen at once.
 *
 * So this constructs its own `MapManager` directly — the same class
 * `useMapManager` wraps, and the same `layerRegistry`/`LayerManager`
 * mechanism every other layer already goes through, just without the
 * shared-store wiring. `chatGeometryLayer()` is the only layer this ever
 * `.add()`s.
 */

import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Maximize2 } from 'lucide-react';
import { Link } from '../../app/router';
import { MapManager } from '../map/managers/MapManager';
import type { ChatObservation } from '../map/api/chat';
import { buildChatGeometry } from './api/chatGeometry';

const CHAT_GEOMETRY_LAYER_ID = 'chat-geometry';
/** Same margin `features/dashboard/components/AnalyticsGrid.tsx`'s own
 * LazyMount uses — not shared code, this component has no dependency on
 * the dashboard's Tailwind-scoped tree. */
const PRELOAD_MARGIN_PX = 200;

/** Renders `children` once the placeholder is near the viewport, and keeps
 * them mounted afterward. Geometry-driven (`getBoundingClientRect`) with an
 * `IntersectionObserver` as a second trigger, not the only one — mirrors
 * `AnalyticsGrid.tsx`'s own `LazyMount`, whose docstring records that an
 * observer-only version once left every chart blank. */
function LazyMount({ children, minHeight }: { children: ReactNode; minHeight: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const [shown, setShown] = useState(false);

  useEffect(() => {
    if (shown) return;

    let frame = 0;
    let cancelled = false;

    const isNearViewport = () => {
      const element = ref.current;
      if (!element) return false;
      const rect = element.getBoundingClientRect();
      const height = window.innerHeight || document.documentElement.clientHeight;
      return rect.top < height + PRELOAD_MARGIN_PX && rect.bottom > -PRELOAD_MARGIN_PX;
    };

    const check = () => {
      if (cancelled) return;
      if (isNearViewport()) setShown(true);
    };

    const schedule = () => {
      if (frame) return;
      frame = window.requestAnimationFrame(() => {
        frame = 0;
        check();
      });
    };

    check();
    window.addEventListener('scroll', schedule, { passive: true });
    window.addEventListener('resize', schedule, { passive: true });

    let observer: IntersectionObserver | undefined;
    if (typeof IntersectionObserver !== 'undefined') {
      observer = new IntersectionObserver(
        (entries) => {
          if (entries.some((entry) => entry.isIntersecting)) setShown(true);
        },
        { rootMargin: `${PRELOAD_MARGIN_PX}px` }
      );
      if (ref.current) observer.observe(ref.current);
    }

    return () => {
      cancelled = true;
      if (frame) window.cancelAnimationFrame(frame);
      window.removeEventListener('scroll', schedule);
      window.removeEventListener('resize', schedule);
      observer?.disconnect();
    };
  }, [shown]);

  return (
    <div ref={ref} style={{ minHeight }}>
      {shown ? children : null}
    </div>
  );
}

function extendBounds(bounds: [number, number, number, number], coordinates: unknown): void {
  if (!Array.isArray(coordinates)) return;
  if (typeof coordinates[0] === 'number') {
    const [lon, lat] = coordinates as number[];
    bounds[0] = Math.min(bounds[0], lon);
    bounds[1] = Math.min(bounds[1], lat);
    bounds[2] = Math.max(bounds[2], lon);
    bounds[3] = Math.max(bounds[3], lat);
    return;
  }
  coordinates.forEach((entry) => extendBounds(bounds, entry));
}

/** Every coordinate this turn's geometry touches, as a fit-to-bounds box —
 * there's no fixed camera to fall back to the way the full map restores its
 * last position, so the preview has to frame itself from its own data. */
function boundsOf(collection: GeoJSON.FeatureCollection): [[number, number], [number, number]] | null {
  const bounds: [number, number, number, number] = [Infinity, Infinity, -Infinity, -Infinity];
  for (const feature of collection.features) {
    if (feature.geometry.type === 'GeometryCollection') continue;
    extendBounds(bounds, (feature.geometry as { coordinates: unknown }).coordinates);
  }
  if (!Number.isFinite(bounds[0])) return null;
  return [
    [bounds[0], bounds[1]],
    [bounds[2], bounds[3]],
  ];
}

function ChatMapCanvas({ features }: { features: GeoJSON.FeatureCollection }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const managerRef = useRef<MapManager | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!containerRef.current) return;

    const manager = new MapManager();
    managerRef.current = manager;
    const map = manager.init({
      container: containerRef.current,
      defaultBasemap: 'abyss',
      // A tiny static preview has no use for the 3D globe's own idle/raster
      // quirks (see docs/features/map-rendering.md) — flat mercator is
      // simpler to fit-to-bounds and cheaper to render at this size.
      projection: 'mercator',
    });
    map.once('load', () => setReady(true));

    return () => {
      manager.destroy();
      managerRef.current = null;
      setReady(false);
    };
  }, []);

  useEffect(() => {
    if (!ready) return;
    const manager = managerRef.current;
    const layerManager = manager?.getLayerManager();
    const map = manager?.getMap();
    if (!layerManager || !map) return;

    layerManager.add(CHAT_GEOMETRY_LAYER_ID);
    layerManager.setGeoJsonData(CHAT_GEOMETRY_LAYER_ID, features);

    const bounds = boundsOf(features);
    if (bounds) map.fitBounds(bounds, { padding: 32, maxZoom: 9, duration: 0 });
  }, [ready, features]);

  return <div ref={containerRef} className="chat-map-preview__canvas" />;
}

/**
 * Renders nothing when this turn's observations carry no drawable geometry
 * — the common case, most turns never call a geometry-producing tool at
 * all — so it's safe to mount unconditionally beside `ForecastCharts`.
 */
export function ChatMapPreview({ observations }: { observations: ChatObservation[] }) {
  const features = useMemo(() => buildChatGeometry(observations), [observations]);
  if (!features) return null;

  return (
    <LazyMount minHeight={252}>
      <div className="chat-map-preview">
        <div className="chat-map-preview__header">
          <span className="chat-map-preview__title">What the assistant found</span>
          <Link to="/map" className="chat-map-preview__open-link">
            <Maximize2 size={12} aria-hidden />
            Open full map
          </Link>
        </div>
        <ChatMapCanvas features={features} />
        <p className="chat-map-preview__note">
          A preview of this turn&apos;s own tool results, not a live planning tool.
        </p>
      </div>
    </LazyMount>
  );
}
