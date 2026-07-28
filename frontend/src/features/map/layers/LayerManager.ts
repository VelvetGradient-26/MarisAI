import type { Map as MapLibreMap } from 'maplibre-gl';
import { createEmitter } from '../../../lib/createEmitter';
import type { LayerDescriptor, LayerCategory, CustomVectorFieldLayer } from '../types';

/** Rendering bands, bottom to top — see types/index.ts for the caveat about
 * the ADR's ambiguous hierarchy diagram. */
const CATEGORY_ORDER: LayerCategory[] = ['ocean', 'flow', 'ai', 'reference'];

export interface LayerState {
  descriptor: LayerDescriptor;
  active: boolean;
  opacity: number;
}

/**
 * Config-driven registry: add/remove/toggle/setOpacity, all keyed by a
 * LayerDescriptor. Nothing outside this class calls map.addLayer() /
 * map.removeLayer() for a scientific or reference overlay — new datasets
 * (GIBS, NOAA, Copernicus, AI predictions) are new LayerDescriptor entries
 * in layerRegistry.ts, not new code paths.
 *
 * A descriptor may declare more than one source (see LayerDescriptor.sources)
 * — every method here fans out across all of them so a multi-source layer
 * still behaves as one toggle with one opacity.
 */
export class LayerManager {
  private map: MapLibreMap;
  private getFallbackBeforeId: () => string | undefined;
  private registry = new Map<string, LayerDescriptor>();
  private state = new Map<string, LayerState>();
  private customInstances = new Map<string, CustomVectorFieldLayer>();
  private emitter = createEmitter<Map<string, LayerState>>();

  constructor(map: MapLibreMap, getFallbackBeforeId: () => string | undefined = () => undefined) {
    this.map = map;
    this.getFallbackBeforeId = getFallbackBeforeId;
  }

  register(descriptor: LayerDescriptor) {
    this.registry.set(descriptor.id, descriptor);
    this.state.set(descriptor.id, {
      descriptor,
      active: false,
      opacity: descriptor.defaultOpacity ?? 1,
    });
    this.emit();
  }

  /**
   * Adds every registered layer whose descriptor set `defaultVisible`.
   * Split out from register() because it touches the map (addSource/
   * addLayer), which MapLibre only allows once the style has finished
   * loading — register() itself only writes to in-memory metadata, so it's
   * safe to call anytime, including before the map is ready. MapManager
   * calls this from the map's `load` handler.
   */
  applyDefaults() {
    for (const descriptor of this.registry.values()) {
      if (descriptor.defaultVisible) this.add(descriptor.id);
    }
  }

  add(id: string) {
    const descriptor = this.registry.get(id);
    const current = this.state.get(id);
    if (!descriptor || !current || current.active) return;

    if (descriptor.implemented === false) {
      console.warn(
        `[LayerManager] "${id}" is a registered placeholder with no real tile source yet — skipping.`
      );
      return;
    }

    const beforeId = this.beforeIdFor(descriptor.category);

    if (descriptor.type === 'custom') {
      const layerId = this.layerId(id, 0);
      if (!this.map.getLayer(layerId)) {
        const instance = descriptor.createLayer(layerId);
        instance.setOpacity(current.opacity);
        this.customInstances.set(id, instance);
        this.map.addLayer(instance, beforeId);
      }
    } else {
      descriptor.sources.forEach((source, index) => {
        const sourceId = this.sourceId(id, index);
        const layerId = this.layerId(id, index);

        if (!this.map.getSource(sourceId)) {
          this.map.addSource(sourceId, source);
        }
        if (!this.map.getLayer(layerId)) {
          const rasterPaint = descriptor.rasterPaint;
          this.map.addLayer(
            {
              id: layerId,
              type: 'raster',
              source: sourceId,
              paint: {
                'raster-opacity': current.opacity,
                ...(rasterPaint?.contrast !== undefined && { 'raster-contrast': rasterPaint.contrast }),
                ...(rasterPaint?.saturation !== undefined && {
                  'raster-saturation': rasterPaint.saturation,
                }),
              },
            },
            beforeId
          );
        }
      });
    }

    this.state.set(id, { ...current, active: true });
    this.emit();
  }

  remove(id: string) {
    const current = this.state.get(id);
    if (!current || !current.active) return;

    if (current.descriptor.type === 'custom') {
      const layerId = this.layerId(id, 0);
      if (this.map.getLayer(layerId)) this.map.removeLayer(layerId);
      this.customInstances.delete(id);
    } else {
      current.descriptor.sources.forEach((_source, index) => {
        const layerId = this.layerId(id, index);
        const sourceId = this.sourceId(id, index);
        if (this.map.getLayer(layerId)) this.map.removeLayer(layerId);
        if (this.map.getSource(sourceId)) this.map.removeSource(sourceId);
      });
    }

    this.state.set(id, { ...current, active: false });
    this.emit();
  }

  toggle(id: string) {
    const current = this.state.get(id);
    if (!current) return;
    if (current.active) this.remove(id);
    else this.add(id);
  }

  /**
   * Switches to `id` within its own category, deactivating any other
   * active layer in that same category first — for groups presented as
   * mutually-exclusive "maps" (e.g. Ocean & Atmosphere) rather than
   * stackable overlays. Clicking the already-active one turns it off.
   */
  setExclusive(id: string) {
    const target = this.registry.get(id);
    const current = this.state.get(id);
    if (!target || !current) return;

    for (const [otherId, s] of this.state) {
      if (otherId !== id && s.active && s.descriptor.category === target.category) {
        this.remove(otherId);
      }
    }

    if (current.active) this.remove(id);
    else this.add(id);
  }

  setOpacity(id: string, opacity: number) {
    const current = this.state.get(id);
    if (!current) return;
    const clamped = Math.min(1, Math.max(0, opacity));

    if (current.active) {
      if (current.descriptor.type === 'custom') {
        this.customInstances.get(id)?.setOpacity(clamped);
      } else {
        current.descriptor.sources.forEach((_source, index) => {
          const layerId = this.layerId(id, index);
          if (this.map.getLayer(layerId)) {
            this.map.setPaintProperty(layerId, 'raster-opacity', clamped);
          }
        });
      }
    }
    this.state.set(id, { ...current, opacity: clamped });
    this.emit();
  }

  /** The live CustomVectorFieldLayer instance for an active custom layer, if
   * any — lets UI controls (density/speed sliders) reach its setters without
   * LayerManager needing to know what those setters mean. */
  getCustomLayerInstance(id: string): CustomVectorFieldLayer | undefined {
    return this.customInstances.get(id);
  }

  /**
   * Re-adds every currently-active layer. Not needed by the current
   * BasemapManager (it never calls map.setStyle()), but kept so that if
   * basemap switching ever moves to full style swaps instead of
   * source/layer add-remove, overlays don't silently vanish.
   */
  reapplyAll() {
    for (const [id, s] of this.state) {
      if (s.active) {
        this.state.set(id, { ...s, active: false });
        this.add(id);
      }
    }
  }

  /** Bottommost active overlay's layer id, if any. BasemapManager uses this
   * to keep the basemap layer beneath every overlay when it's swapped. */
  getBottomOverlayLayerId(): string | undefined {
    for (const [id, s] of this.state) {
      if (s.active) return this.layerId(id, 0);
    }
    return undefined;
  }

  getRegistered(): LayerDescriptor[] {
    return [...this.registry.values()];
  }

  getState(): Map<string, LayerState> {
    return new Map(this.state);
  }

  subscribe(listener: (state: Map<string, LayerState>) => void): () => void {
    return this.emitter.subscribe(listener);
  }

  destroy() {
    for (const id of [...this.state.keys()]) this.remove(id);
    this.emitter.clear();
  }

  /** Finds the first active layer whose category renders at or above
   * `category`, so the new layer can be inserted directly beneath it. */
  private beforeIdFor(category: LayerCategory): string | undefined {
    const startIndex = CATEGORY_ORDER.indexOf(category);
    for (const [id, s] of this.state) {
      if (!s.active) continue;
      const otherIndex = CATEGORY_ORDER.indexOf(s.descriptor.category);
      if (otherIndex >= startIndex) return this.layerId(id, 0);
    }
    return this.getFallbackBeforeId();
  }

  private sourceId(id: string, index: number) {
    return `layer-src-${id}-${index}`;
  }

  private layerId(id: string, index: number) {
    return `layer-${id}-${index}`;
  }

  private emit() {
    this.emitter.emit(this.getState());
  }
}
