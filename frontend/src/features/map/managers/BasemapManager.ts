import type { Map as MapLibreMap } from 'maplibre-gl';
import { createEmitter } from '../../../lib/createEmitter';
import type { BasemapDefinition, BasemapId } from '../types';

const BASEMAP_SOURCE_ID = 'basemap-source';
export const BASEMAP_LAYER_ID = 'basemap-layer';

/** Prefix for the sources/layers a vector basemap brings with it. */
const VECTOR_PREFIX = 'basemap-v-';

/**
 * Basemaps are added/removed as their own sources+layers rather than
 * through map.setStyle() — a full style swap would wipe every layer
 * LayerManager has added. This is the direct fix for the ADR's own risk
 * #3 ("state duplication between React and MapLibre") as it applies to
 * basemap switching: overlays are simply never touched.
 *
 * `getInsertBeforeId` is supplied by MapManager (backed by
 * LayerManager.getBottomOverlayLayerId()) so a re-inserted basemap always
 * lands beneath whatever overlays are currently active, instead of on top
 * of them.
 *
 * A raster basemap is one source and one layer. A vector basemap is several
 * sources and a stack of ~20 style layers, all namespaced under
 * `VECTOR_PREFIX` so teardown can find every one of them — the whole reason
 * this class tracks what it added rather than assuming a fixed pair of ids.
 */
export class BasemapManager {
  private map: MapLibreMap;
  private registry = new Map<BasemapId, BasemapDefinition>();
  private currentId: BasemapId | null = null;
  private emitter = createEmitter<BasemapId>();
  private getInsertBeforeId: () => string | undefined;
  /** Exactly what the current basemap added, in insertion order. */
  private activeLayerIds: string[] = [];
  private activeSourceIds: string[] = [];

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

    this.teardown();

    if (def.kind === 'vector') this.addVector(def);
    else this.addRaster(def);

    this.currentId = id;
    this.emitter.emit(id);
  }

  private addRaster(def: Extract<BasemapDefinition, { kind: 'raster' }>) {
    // Cloned for the same reason as the vector path below.
    this.map.addSource(BASEMAP_SOURCE_ID, structuredClone(def.source));
    this.map.addLayer(
      {
        id: BASEMAP_LAYER_ID,
        type: 'raster',
        source: BASEMAP_SOURCE_ID,
        ...def.layerOptions,
      },
      this.getInsertBeforeId()
    );
    this.activeSourceIds = [BASEMAP_SOURCE_ID];
    this.activeLayerIds = [BASEMAP_LAYER_ID];
  }

  private addVector(def: Extract<BasemapDefinition, { kind: 'vector' }>) {
    for (const [key, source] of Object.entries(def.sources)) {
      const sourceId = `${VECTOR_PREFIX}${key}`;
      if (!this.map.getSource(sourceId)) {
        // Structured-clone the spec. These source objects are module-level
        // singletons shared by both vector basemaps *and* by every map
        // instance on the page (the /map view and the dashboard's embedded
        // panel run concurrently). MapLibre treats a spec it is handed as
        // its own to annotate — resolving a TileJSON `url` into `tiles`,
        // among other things — so passing the shared object risks one map
        // mutating state the other is still using.
        this.map.addSource(sourceId, structuredClone(source));
        this.activeSourceIds.push(sourceId);
      }
    }

    // Every layer goes before the same anchor, which preserves their
    // relative order: each new layer is inserted directly above the
    // previous one and the whole block stays beneath the data overlays.
    const before = this.getInsertBeforeId();
    for (const layer of def.layers) {
      const layerId = `${VECTOR_PREFIX}${layer.id}`;
      const resolved = {
        ...layer,
        id: layerId,
        ...('source' in layer && layer.source
          ? { source: `${VECTOR_PREFIX}${layer.source}` }
          : {}),
      } as typeof layer;

      this.map.addLayer(resolved, before);
      this.activeLayerIds.push(layerId);
    }
  }

  /** Remove whatever the previous basemap added — layers first, then sources. */
  private teardown() {
    for (const layerId of this.activeLayerIds) {
      if (this.map.getLayer(layerId)) this.map.removeLayer(layerId);
    }
    for (const sourceId of this.activeSourceIds) {
      // A source still referenced by a layer cannot be removed, so layers
      // must always go first — hence the two separate loops.
      if (this.map.getSource(sourceId)) this.map.removeSource(sourceId);
    }
    this.activeLayerIds = [];
    this.activeSourceIds = [];
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
    // Goes through the same teardown as a switch, so a vector basemap's
    // ~20 layers are cleaned up rather than just the raster pair.
    this.teardown();
    this.emitter.clear();
  }
}
