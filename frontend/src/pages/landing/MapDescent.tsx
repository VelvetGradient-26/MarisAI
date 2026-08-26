import { useEffect, useRef, useState } from 'react';
import type { Map as MapLibreMap } from 'maplibre-gl';
import type { MapManager as MapManagerType } from '../../features/map/managers/MapManager';
import { Eyebrow } from './Eyebrow';
import { usePinnedProgress } from './useScrollReveal';
import './mapDescent.css';

/**
 * The signature move: scroll drives a real, live MapManager instance — the
 * same engine `/map` runs — from a whole-globe view down into a coastal box,
 * cross-fading on real overlay layers (SST, then surface currents, then
 * detected eddies) as it descends. Not a video and not a screenshot: a
 * genuinely mounted map reading the platform's own live tile/particle
 * endpoints, held still by a pinned section while scroll scrubs its camera.
 *
 * **Why not `useMapManager`.** That hook (features/map/hooks/useMapManager.ts)
 * writes every camera/basemap/layer change into the *global* `mapStore` —
 * the same store `/map` and the dashboard's embedded panel read on mount to
 * restore the visitor's last view. Wiring this decorative flythrough through
 * it would mean scrolling this section silently overwrites where `/map`
 * reopens next. So this constructs its own `MapManager` directly, exactly as
 * `useMapManager` does internally, but never touches `mapStore` or
 * `mapPreferencesStore` — this instance's camera is a page decoration, not
 * "the" map.
 *
 * **Why the manager class is dynamically imported.** `MapManager.ts`
 * statically imports `maplibre-gl`, which nothing else on this page needs.
 * Loading it eagerly would add the whole MapLibre bundle to every landing
 * pageview; `import()` here gives it its own chunk, fetched only once this
 * section is close enough to matter — the same gate `ClosingBackdrop` uses
 * for its WebGL aurora, for the same reason (a GL context is not free, and
 * browsers cap how many can be live at once).
 */

const CENTER: [number, number] = [63.5, 14.5]; // Arabian Sea — the platform's own flagship region (see CLAUDE.md, HAB/eddy detection)
const ZOOM_GLOBAL = 1.7;
const ZOOM_COASTAL = 5.1;
const PITCH_COASTAL = 32;

const CAMERA_END = 0.55; // fraction of the pinned span spent on the descent itself
const SST_IN: [number, number] = [0.28, 0.4];
const CURRENTS_IN: [number, number] = [0.5, 0.64];
const EDDIES_IN: [number, number] = [0.72, 0.86];

function easeInOutCubic(t: number): number {
  return t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2;
}

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

/** 0 outside [start, end], 1 inside, linear across the two edges. */
function bandOpacity(p: number, start: number, end: number): number {
  if (p <= start) return 0;
  if (p >= end) return 1;
  return (p - start) / (end - start);
}

const CAPTIONS: { label: string; range: [number, number] }[] = [
  { label: 'GLOBAL VIEW', range: [0, SST_IN[0]] },
  { label: 'SEA SURFACE TEMPERATURE — LIVE', range: [SST_IN[0], CURRENTS_IN[0]] },
  { label: 'SURFACE CURRENTS — LIVE', range: [CURRENTS_IN[0], EDDIES_IN[0]] },
  { label: 'EDDIES — DETECTED LIVE', range: [EDDIES_IN[0], 1] },
];

export function MapDescent() {
  const headRef = useRef<HTMLDivElement>(null);
  const captionRefs = useRef<(HTMLSpanElement | null)[]>([]);
  const mountedMap = useRef<{
    map: MapLibreMap;
    manager: MapManagerType;
    sstOn: boolean;
    currentsOn: boolean;
    eddiesOn: boolean;
  } | null>(null);
  const lastProgress = useRef(0);
  const [nearViewport, setNearViewport] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const update = (progress: number) => {
    lastProgress.current = progress;

    const cameraT = easeInOutCubic(Math.min(1, progress / CAMERA_END));
    const state = mountedMap.current;

    // The instructional heading has done its job once the descent is under
    // way — real seafloor-bright SST data fills the frame behind it from
    // here on, and no scrim strong enough to hold white-on-orange legible
    // would still read as "live data" underneath. It steps aside instead.
    if (headRef.current) {
      headRef.current.style.opacity = String(1 - bandOpacity(progress, 0, 0.12));
    }

    captionRefs.current.forEach((node, index) => {
      if (!node) return;
      const [start, end] = CAPTIONS[index].range;
      // `<=` on the end, not `<` — the last caption's range ends at exactly
      // 1, and reduced motion resolves progress to exactly 1 once, so a
      // strict `<` here left the final held frame with no caption showing.
      const inside = progress >= start && progress <= end;
      node.style.opacity = inside ? '1' : '0';
    });

    if (!state) return;
    const { map, manager } = state;

    map.jumpTo({
      center: CENTER,
      zoom: lerp(ZOOM_GLOBAL, ZOOM_COASTAL, cameraT),
      pitch: lerp(0, PITCH_COASTAL, cameraT),
      bearing: 0,
    });

    const layers = manager.getLayerManager();
    if (!layers) return;

    const sstT = bandOpacity(progress, SST_IN[0], SST_IN[1]);
    if (sstT > 0 && !state.sstOn) {
      layers.add('sst');
      state.sstOn = true;
    } else if (sstT <= 0 && state.sstOn) {
      layers.remove('sst');
      state.sstOn = false;
    }
    if (state.sstOn) layers.setOpacity('sst', sstT);

    const currentsT = bandOpacity(progress, CURRENTS_IN[0], CURRENTS_IN[1]);
    if (currentsT > 0 && !state.currentsOn) {
      layers.add('currents');
      state.currentsOn = true;
    } else if (currentsT <= 0 && state.currentsOn) {
      layers.remove('currents');
      state.currentsOn = false;
    }
    if (state.currentsOn) layers.setOpacity('currents', currentsT);

    const eddiesT = bandOpacity(progress, EDDIES_IN[0], EDDIES_IN[1]);
    if (eddiesT > 0 && !state.eddiesOn) {
      layers.add('eddies');
      state.eddiesOn = true;
    } else if (eddiesT <= 0 && state.eddiesOn) {
      layers.remove('eddies');
      state.eddiesOn = false;
    }
    if (state.eddiesOn) layers.setOpacity('eddies', eddiesT);
  };

  const { ref: wrapperRef, reduced } = usePinnedProgress<HTMLDivElement>(update);

  // Geometry-measured "near viewport" gate, matching ClosingBackdrop's Aurora
  // gate: an IntersectionObserver alone has already failed to fire in this
  // app (see AnalyticsGrid's history), so it is an extra trigger here, not
  // the only one.
  useEffect(() => {
    if (nearViewport) return;
    const element = wrapperRef.current;
    if (!element) return;
    let done = false;
    const check = () => {
      if (done || !wrapperRef.current) return;
      const rect = wrapperRef.current.getBoundingClientRect();
      const viewport = window.innerHeight || 800;
      if (rect.top < viewport * 1.5 && rect.bottom > -viewport * 0.5) {
        done = true;
        setNearViewport(true);
      }
    };
    check();
    window.addEventListener('scroll', check, { passive: true });
    window.addEventListener('resize', check);
    const observer =
      typeof IntersectionObserver !== 'undefined'
        ? new IntersectionObserver((entries) => entries.some((e) => e.isIntersecting) && check(), {
            rootMargin: '50% 0px',
          })
        : null;
    observer?.observe(element);
    return () => {
      done = true;
      window.removeEventListener('scroll', check);
      window.removeEventListener('resize', check);
      observer?.disconnect();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nearViewport]);

  useEffect(() => {
    if (!nearViewport || !containerRef.current) return;
    let destroyed = false;

    (async () => {
      const { MapManager } = await import('../../features/map/managers/MapManager');
      if (destroyed || !containerRef.current) return;

      const manager = new MapManager();
      const map = manager.init({
        container: containerRef.current,
        center: CENTER,
        zoom: ZOOM_GLOBAL,
        pitch: 0,
        bearing: 0,
        defaultBasemap: 'satellite',
        projection: 'globe',
      });

      // Decorative and scroll-driven only — no visitor interaction. A page
      // scroll must not fight a map drag underneath it, and there is nothing
      // here to click.
      map.dragPan.disable();
      map.dragRotate.disable();
      map.scrollZoom.disable();
      map.doubleClickZoom.disable();
      map.touchZoomRotate.disable();
      map.touchPitch.disable();
      map.keyboard.disable();
      map.boxZoom.disable();
      map.getCanvas().style.cursor = 'default';
      map.getCanvas().tabIndex = -1;

      map.once('load', () => {
        if (destroyed) return;
        // `LayerManager.applyDefaults()` already ran (it is wired to the
        // same `load` event, registered first, inside `manager.init()`) and
        // switched on `sst` and `wind` — right for the full `/map` view,
        // wrong here, where the whole point is that nothing but the basemap
        // is visible until the descent's own progress bands say otherwise.
        manager.getLayerManager()?.remove('sst');
        manager.getLayerManager()?.remove('wind');
        mountedMap.current = { map, manager, sstOn: false, currentsOn: false, eddiesOn: false };
        update(lastProgress.current);
      });
    })();

    return () => {
      destroyed = true;
      mountedMap.current?.manager.destroy();
      mountedMap.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nearViewport]);

  return (
    <section className={`lp-descent${reduced ? ' lp-descent--reduced' : ''}`} ref={wrapperRef}>
      <div className="lp-descent__stage">
        <div className="lp-descent__map" ref={containerRef} aria-hidden="true" />
        <div className="lp-descent__veil" aria-hidden="true" />
        <div className="lp-descent__frame">
          <div className="lp-descent__head" ref={headRef}>
            <Eyebrow index="02">Live descent</Eyebrow>
            <h2 className="lp-h2">Scroll to descend.</h2>
          </div>
          <div className="lp-descent__foot">
            <div className="lp-descent__caption" aria-hidden="true">
              {CAPTIONS.map((caption, index) => (
                <span
                  key={caption.label}
                  ref={(node) => {
                    captionRefs.current[index] = node;
                  }}
                  className="lp-descent__caption-line"
                  style={{ opacity: index === 0 ? 1 : 0 }}
                >
                  {caption.label}
                </span>
              ))}
            </div>
            <p className="lp-descent__note">
              A live MapManager instance — the same engine <code>/map</code> runs — not a
              recording.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
