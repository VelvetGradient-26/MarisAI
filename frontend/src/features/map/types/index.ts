import type {
  RasterSourceSpecification,
  RasterLayerSpecification,
} from '@maplibre/maplibre-gl-style-spec';

export type BasemapId = 'satellite' | 'blueMarble' | 'dark' | 'streets';

export interface BasemapDefinition {
  id: BasemapId;
  name: string;
  attribution: string;
  source: RasterSourceSpecification;
  /** Optional paint/layout overrides beyond the default raster layer. */
  layerOptions?: Pick<RasterLayerSpecification, 'paint' | 'layout' | 'minzoom' | 'maxzoom'>;
}

/**
 * Rendering bands, bottom to top. Basemap always sits beneath all of these.
 * See README.md "Layer z-order" section — the ADR's own layer hierarchy
 * diagram is ambiguous about stacking direction, so this is a documented
 * assumption, not a settled decision.
 */
export type LayerCategory = 'ocean' | 'ai' | 'reference';

export interface LayerDescriptor {
  id: string;
  name: string;
  category: LayerCategory;
  type: 'raster'; // extend with 'geojson' | 'vector' when Phase 4+ needs them
  source: RasterSourceSpecification;
  defaultOpacity?: number;
  defaultVisible?: boolean;
  attribution?: string;
  /**
   * False marks a registered placeholder with no real tile source wired up
   * yet (e.g. ocean currents, AI predictions). It shows up in the layer
   * panel as disabled rather than silently failing to load tiles.
   */
  implemented?: boolean;
}

export interface CameraState {
  center: [number, number];
  zoom: number;
  bearing: number;
  pitch: number;
}

export interface CursorCoordinates {
  lng: number;
  lat: number;
}
