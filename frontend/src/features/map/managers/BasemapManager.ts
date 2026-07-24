import type { Map as MapLibreMap } from 'maplibre-gl';
import { createEmitter } from '../../../lib/createEmitter';
import type { BasemapDefinition, BasemapId } from '../types';

const BASEMAP_SOURCE_ID = 'basemap-source';
const BASEMAP_LAYER_ID = 'basemap-layer';

/**
 * Basemaps are added/removed as a single raster source+layer rather than
 * through map.setStyle() — a full style swap would wipe every layer
 * LayerManager has added. This is the direct fix for the ADR's own risk
 * #3 ("state duplication between React and MapLibre") as it applies to
 * basemap switching: overlays are simply never touched.
 *
 * `getInsertBeforeId` is supplied by MapManager (backed by
 * LayerManager.getBottomOverlayLayerId()) so a re-inserted basemap layer
 * always lands beneath whatever overlays are currently active, instead of
 * on top of them.
 */
export class BasemapManager {
  private map: MapLibreMap;
  private registry = new Map<BasemapId, BasemapDefinition>();
  private currentId: BasemapId | null = null;
  private emitter = createEmitter<BasemapId>();
  private getInsertBeforeId: () => string | undefined;

  constructor(map: MapLibreMap, getInsertBeforeId: () => string | undefined) {
    this.map = map;
    this.getInsertBeforeId = getInsertBeforeId;
  }

  register(def: BasemapDefinition) {
    this.registry.set(def.id, def);
  }

  init(defaultId: BasemapId) {
    this.switchTo(defaultId);
  }

  switchTo(id: BasemapId) {
    const def = this.registry.get(id);
    if (!def) {
      console.warn(`[BasemapManager] Unknown basemap "${id}"`);
      return;
    }

    if (this.map.getLayer(BASEMAP_LAYER_ID)) this.map.removeLayer(BASEMAP_LAYER_ID);
    if (this.map.getSource(BASEMAP_SOURCE_ID)) this.map.removeSource(BASEMAP_SOURCE_ID);

    this.map.addSource(BASEMAP_SOURCE_ID, def.source);
    this.map.addLayer(
      {
        id: BASEMAP_LAYER_ID,
        type: 'raster',
        source: BASEMAP_SOURCE_ID,
        ...def.layerOptions,
      },
      this.getInsertBeforeId()
    );

    this.currentId = id;
    this.emitter.emit(id);
  }

  getCurrent(): BasemapId | null {
    return this.currentId;
  }

  getAvailable(): BasemapDefinition[] {
    return [...this.registry.values()];
  }

  subscribe(listener: (id: BasemapId) => void): () => void {
    return this.emitter.subscribe(listener);
  }

  destroy() {
    if (this.map.getLayer(BASEMAP_LAYER_ID)) this.map.removeLayer(BASEMAP_LAYER_ID);
    if (this.map.getSource(BASEMAP_SOURCE_ID)) this.map.removeSource(BASEMAP_SOURCE_ID);
    this.emitter.clear();
  }
}
