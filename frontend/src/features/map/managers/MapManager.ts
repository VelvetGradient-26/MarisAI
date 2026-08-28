import * as maplibregl from 'maplibre-gl';
import type { Map as MapLibreMap } from 'maplibre-gl';
import { BASEMAP_LAYER_ID, BasemapManager } from './BasemapManager';
import { ControlManager } from './ControlManager';
import { LayerManager } from '../layers/LayerManager';
import { basemaps } from '../basemaps';
import { OPENFREEMAP_GLYPHS } from '../basemaps/vectorSource';
import { layerRegistry } from '../layers/layerRegistry';
import { getFirstExistingAnnotationLayerId } from '../layers/annotationLayerIds';
import type { BasemapId, ProjectionMode } from '../types';

export interface MapManagerInitOptions {
  container: HTMLElement;
  center?: [number, number];
  zoom?: number;
  bearing?: number;
  pitch?: number;
  defaultBasemap?: BasemapId;
  /** Applied on `load` instead of DEFAULT_PROJECTION. Passed in at init
   * (rather than toggled afterwards) so a restored 2D preference never
   * flashes the globe and animates out of it on every mount. */
  projection?: ProjectionMode;
}

const DEFAULT_PROJECTION: ProjectionMode = 'globe';

/**
 * Owns the MapLibre instance and its lifecycle. Everything else — basemaps,
 * controls, layers — is a child manager wired up here. Components only ever
 * talk to MapManager (through useMapManager), never to maplibregl.Map or
 * the child managers' constructors directly.
 */
export class MapManager {
  private map: MapLibreMap | null = null;
  private basemapManager: BasemapManager | null = null;
  private controlManager: ControlManager | null = null;
  private resizeObserver: ResizeObserver | null = null;
  private layerManager: LayerManager | null = null;
  private projectionMode: ProjectionMode = DEFAULT_PROJECTION;

  init(options: MapManagerInitOptions): MapLibreMap {
    const {
      container,
      center = [0, 20],
      zoom = 2.2,
      bearing = 0,
      pitch = 0,
      defaultBasemap = 'abyss',
      projection = DEFAULT_PROJECTION,
    } = options;

    this.projectionMode = projection;

    // Empty style: MapManager/BasemapManager/LayerManager own every source
    // and layer explicitly, rather than inheriting an opaque preset style.
    // A local const (rather than assigning this.map first) keeps TypeScript's
    // non-null narrowing intact while wiring up the child managers below.
    const map = new maplibregl.Map({
      container,
      style: {
        version: 8,
        sources: {},
        layers: [],
        // Set once, at construction. Doing it per-basemap via setGlyphs()
        // was a race: setGlyphs triggers an asynchronous style reload, and
        // the sources/layers added immediately afterwards were intermittently
        // lost — the globe came up as an empty disc with no coastlines and no
        // marker. Both vector basemaps use this same endpoint, so there is
        // nothing to switch at runtime.
        glyphs: OPENFREEMAP_GLYPHS,
      },
      center,
      zoom,
      bearing,
      pitch,
      renderWorldCopies: false,
      attributionControl: { compact: true },
      // Needed for exportHighResImage()'s canvas.toBlob() capture — without
      // it the WebGL context is free to discard its backing buffer right
      // after compositing, and a screenshot taken any time after the
      // triggering `idle` event comes back blank on some browsers/GPUs.
      canvasContextAttributes: { preserveDrawingBuffer: true },
    });
    (window as unknown as { __debugMap?: unknown }).__debugMap = map;

    const layerManager = new LayerManager(map, () => getFirstExistingAnnotationLayerId(map));
    const basemapManager = new BasemapManager(map, () => getBasemapInsertBeforeId(map));
    const controlManager = new ControlManager(map);

    // register() on both managers only writes in-memory metadata (basemap
    // list, layer list) — safe to call immediately, before the style has
    // loaded, and needed so the control panel can list everything right
    // away instead of popping in after `load`.
    basemaps.forEach((def) => basemapManager.register(def));
    layerRegistry.forEach((descriptor) => layerManager.register(descriptor));

    // basemapManager.init() and layerManager.applyDefaults() call
    // map.addSource()/addLayer(), which MapLibre rejects with "Style is
    // not done loading" if called before the style has finished loading —
    // true even for the empty placeholder style above. `load` is the
    // earliest safe point. (ControlManager's controls are plain DOM
    // overlays, not style mutations, so they're unaffected and stay
    // synchronous above.)
    map.once('load', () => {
      map.setProjection({ type: projection });
      basemapManager.init(defaultBasemap);
      layerManager.applyDefaults();
    });

    /**
     * Re-measure whenever the *container* changes size.
     *
     * MapLibre's `trackResize` only listens to `window` resize events, so a
     * map whose container changes size on its own is never told. That is
     * exactly the dashboard's embedded panel: it is lazy-loaded into a flex
     * column whose height settles after the map is constructed (KPI cards
     * and charts mount above it), so the canvas kept a stale size and the
     * panel rendered blank until something forced a resize. The full-page
     * /map view never hit this because it is sized correctly from the start.
     */
    if (typeof ResizeObserver !== 'undefined') {
      this.resizeObserver = new ResizeObserver(() => map.resize());
      this.resizeObserver.observe(container);
    }

    this.map = map;
    this.layerManager = layerManager;
    this.basemapManager = basemapManager;
    this.controlManager = controlManager;

    return map;
  }

  getMap(): MapLibreMap | null {
    return this.map;
  }

  getBasemapManager(): BasemapManager | null {
    return this.basemapManager;
  }

  getControlManager(): ControlManager | null {
    return this.controlManager;
  }

  getLayerManager(): LayerManager | null {
    return this.layerManager;
  }

  getProjectionMode(): ProjectionMode {
    return this.projectionMode;
  }

  /**
   * Switches between a flattened web-mercator map and the 3D globe.
   * MapLibre animates the transition itself, so there's nothing to ease
   * here. Note 'globe' is the adaptive projection — it renders as a real
   * sphere when zoomed out and eases back into mercator as you zoom in,
   * which is what makes it usable for close-up work rather than a novelty.
   */
  setProjectionMode(mode: ProjectionMode) {
    const map = this.map;
    if (!map || mode === this.projectionMode) return;
    this.projectionMode = mode;
    map.setProjection({ type: mode });
  }

  /**
   * Captures the current view (basemap + every active overlay, exactly as
   * shown) as a PNG at a true higher pixel density, not an upscale of the
   * on-screen canvas.
   *
   * `setPixelRatio` only changes the canvas's backing-store resolution, not
   * its CSS/layout size, so there is no visible resize/flash — MapLibre just
   * re-renders every layer (vector geometry, raster tiles) at the new pixel
   * density, fetching deeper raster tiles where the source's maxzoom allows
   * it. `targetLongEdge` is a floor on the longer edge, not an exact crop, so
   * the export keeps the on-screen framing/aspect ratio instead of
   * distorting it to hit an exact 3840x2160.
   *
   * Deliberately does not await `map.once('idle')` — measured live, `idle`
   * never fires and `map.loaded()` never returns true while in the globe
   * projection (the app's default), because globe's atmosphere/halo repaints
   * every frame regardless of whether tiles or camera are still moving. That
   * would hang this method forever for anyone who hadn't switched to 2D. A
   * short debounced poll on `areTilesLoaded()` plus a bounded timeout works
   * in both projections and can't hang the export.
   */
  async exportHighResImage(targetLongEdge = 3840): Promise<Blob> {
    const map = this.map;
    if (!map) throw new Error('Map not initialized');

    const canvas = map.getCanvas();
    const originalRatio = map.getPixelRatio();
    const cssLongEdge = Math.max(canvas.clientWidth, canvas.clientHeight);
    const scale = Math.max(originalRatio, targetLongEdge / cssLongEdge);

    map.setPixelRatio(scale);
    try {
      await waitForTilesSettled(map);
      // One more repaint so the just-settled tiles are actually composited
      // into the canvas before capture, not merely marked loaded.
      map.triggerRepaint();
      await new Promise<void>((resolve) => map.once('render', () => resolve()));
      const blob = await new Promise<Blob | null>((resolve) =>
        canvas.toBlob(resolve, 'image/png')
      );
      if (!blob) throw new Error('Canvas capture returned no data');
      return blob;
    } finally {
      map.setPixelRatio(originalRatio);
    }
  }

  destroy() {
    this.resizeObserver?.disconnect();
    this.resizeObserver = null;
    this.controlManager?.destroy();
    this.layerManager?.destroy();
    this.basemapManager?.destroy();
    this.map?.remove();
    this.map = null;
    this.basemapManager = null;
    this.controlManager = null;
    this.layerManager = null;
  }
}

/**
 * Polls `areTilesLoaded()` until it reports true and holds for one more
 * check (debounced, since a tile can finish loading and immediately queue a
 * dependent one), or gives up after `timeoutMs` — this is a best-effort
 * wait, not a guarantee, since a slow/failing tile source must not be able
 * to hang the export. See exportHighResImage's docstring for why `idle`
 * can't be used here.
 */
function waitForTilesSettled(map: MapLibreMap, timeoutMs = 8000, pollMs = 150): Promise<void> {
  return new Promise((resolve) => {
    const start = Date.now();
    let sawLoaded = false;
    const check = () => {
      const loaded = map.areTilesLoaded();
      if (loaded && sawLoaded) {
        resolve();
        return;
      }
      sawLoaded = loaded;
      if (Date.now() - start >= timeoutMs) {
        resolve();
        return;
      }
      setTimeout(check, pollMs);
    };
    check();
  });
}

function getBasemapInsertBeforeId(map: MapLibreMap): string | undefined {
  return map.getStyle().layers?.find((layer) => layer.id !== BASEMAP_LAYER_ID)?.id;
}
