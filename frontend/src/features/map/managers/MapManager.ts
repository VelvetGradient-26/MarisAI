import * as maplibregl from 'maplibre-gl';
import type { Map as MapLibreMap } from 'maplibre-gl';
import { BasemapManager } from './BasemapManager';
import { ControlManager } from './ControlManager';
import { LayerManager } from '../layers/LayerManager';
import { basemaps } from '../basemaps';
import { layerRegistry } from '../layers/layerRegistry';
import type { BasemapId } from '../types';

export interface MapManagerInitOptions {
  container: HTMLElement;
  center?: [number, number];
  zoom?: number;
  defaultBasemap?: BasemapId;
}

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
  private layerManager: LayerManager | null = null;

  init(options: MapManagerInitOptions): MapLibreMap {
    const { container, center = [0, 20], zoom = 2.2, defaultBasemap = 'satellite' } = options;

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
        glyphs: 'https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf',
      },
      center,
      zoom,
      renderWorldCopies: false,
      attributionControl: { compact: true },
    });

    const layerManager = new LayerManager(map);
    const basemapManager = new BasemapManager(map, () => layerManager.getBottomOverlayLayerId());
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
      basemapManager.init(defaultBasemap);
      layerManager.applyDefaults();
    });

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

  destroy() {
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
