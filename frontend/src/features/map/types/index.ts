import type {
  CustomLayerInterface,
  RasterSourceSpecification,
  RasterLayerSpecification,
} from 'maplibre-gl';

export type BasemapId = 'satellite' | 'blueMarble' | 'darkMarine';

/**
 * The two shapes the world can be drawn in. Both are MapLibre's own
 * `setProjection` type names, so they're passed straight through — see
 * `MapManager.setProjectionMode`.
 */
export type ProjectionMode = 'mercator' | 'globe';

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
 *
 * 'flow' sits above 'ocean' (particle layers render on top of scalar color
 * fields like SST) and beneath 'ai'/'reference' (labels/boundaries stay
 * legible on top of particles).
 */
export type LayerCategory = 'ocean' | 'flow' | 'ai' | 'reference';

/**
 * How to explain a layer's colors/symbols to the user. Values here are
 * sourced from the provider's own published colormap/legend (GIBS colormap
 * XML, WMS GetLegendGraphic) — not invented — so a "Cold/Mild/Hot" bucket
 * boundary is a real boundary in that provider's color scale, just labeled
 * for quick reading instead of showing the raw continuous ramp.
 */
export type LayerLegend =
  | {
      type: 'categories';
      unit: string;
      categories: Array<{ label: string; range: string; color: string }>;
    }
  | {
      /** Continuous color ramp — for real-valued scalar fields (SST,
       * chlorophyll, etc.) rather than the discrete buckets `categories`
       * implies. `stops` are CSS-gradient offsets (0-1) + hex color; `min`/
       * `max` are the scale's real-world endpoints in `unit`. */
      type: 'gradient';
      unit: string;
      min: number;
      max: number;
      stops: Array<{ offset: number; color: string }>;
    }
  | { type: 'image'; src: string; alt: string }
  | { type: 'swatch'; color: string; label: string }
  | { type: 'note'; text: string };

/**
 * A `CustomLayerInterface` implementation that also exposes an opacity knob —
 * custom WebGL layers have no `raster-opacity` paint property, so
 * `LayerManager` calls this directly instead. `setDensityTier`/
 * `setSpeedMultiplier` are optional: only vector-field particle layers (wind,
 * and later currents/waves) implement them, for the Task 13 sliders.
 */
export interface CustomVectorFieldLayer extends CustomLayerInterface {
  id: string;
  setOpacity(opacity: number): void;
  setDensityTier?(tier: 'world' | 'regional' | 'local' | 'auto'): void;
  setSpeedMultiplier?(multiplier: number): void;
}

interface LayerDescriptorBase {
  id: string;
  name: string;
  category: LayerCategory;
  defaultVisible?: boolean;
  attribution?: string;
  legend?: LayerLegend;
  /**
   * False marks a registered placeholder with no real tile source wired up
   * yet (e.g. ocean currents, AI predictions). It shows up in the layer
   * panel as disabled rather than silently failing to load tiles.
   */
  implemented?: boolean;
  /**
   * Hides the per-layer opacity slider in the control panel — for layers
   * whose opacity is a fixed design choice (e.g. reference labels tuned to
   * stay legible over any basemap) rather than a user-facing knob.
   */
  hideOpacitySlider?: boolean;
}

export interface RasterLayerDescriptor extends LayerDescriptorBase {
  type: 'raster';
  /**
   * Usually one raster source. A few real-data layers (e.g. wind speed)
   * genuinely need two — different satellite orbit passes that cover
   * different swaths of the globe on a given day — stacked together under
   * one toggle so the union of both passes' real coverage shows, instead of
   * either pass's gaps alone. Not a rendering trick: every source here is a
   * real, independently-fetched dataset.
   */
  sources: RasterSourceSpecification[];
  defaultOpacity?: number;
  /**
   * Optional GPU-side raster paint tweaks (MapLibre `raster-*` paint
   * properties), applied on top of `raster-opacity`. For layers whose tile
   * colors read dimmer than intended once blended over a dark basemap —
   * adjusts the display only, not the underlying data/colormap, so a
   * layer's legend still reflects the real color scale.
   */
  rasterPaint?: {
    /** MapLibre `raster-contrast`, range -1 to 1. */
    contrast?: number;
    /** MapLibre `raster-saturation`, range -1 to 1. */
    saturation?: number;
  };
}

/**
 * A layer that owns its own WebGL rendering (particle systems, and any
 * future custom-rendered layer) rather than a MapLibre raster/vector source.
 * `createLayer` is called once by LayerManager.add() with the synthetic
 * layer id it should register under.
 */
export interface CustomLayerDescriptor extends LayerDescriptorBase {
  type: 'custom';
  defaultOpacity?: number;
  createLayer: (id: string) => CustomVectorFieldLayer;
}

export type LayerDescriptor = RasterLayerDescriptor | CustomLayerDescriptor;

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

export interface RealtimeOceanConditions {
  time: string | null;
  sea_surface_temperature: number | null;
  wave_height: number | null;
  wave_direction: number | null;
  wave_period: number | null;
  ocean_current_velocity: number | null;
  ocean_current_direction: number | null;
  sea_level_height_msl: number | null;
  wind_speed: number | null;
  wind_direction: number | null;
  air_temperature: number | null;
  relative_humidity: number | null;
  surface_pressure: number | null;
  visibility: number | null;
  cloud_cover: number | null;
  precipitation: number | null;
}

export interface RealtimeOceanUnits {
  sea_surface_temperature: string | null;
  wave_height: string | null;
  wave_direction: string | null;
  wave_period: string | null;
  ocean_current_velocity: string | null;
  ocean_current_direction: string | null;
  sea_level_height_msl: string | null;
  wind_speed: string | null;
  wind_direction: string | null;
  air_temperature: string | null;
  relative_humidity: string | null;
  surface_pressure: string | null;
  visibility: string | null;
  cloud_cover: string | null;
  precipitation: string | null;
}

export interface RealtimeOceanResolvedPoint {
  latitude: number | null;
  longitude: number | null;
  timezone: string | null;
  timezone_abbreviation: string | null;
}

export interface NearestPort {
  name: string;
  country: string;
  distance_km: number;
}

export interface RealtimeOceanLocationContext {
  ocean_name: string | null;
  nearest_port: NearestPort | null;
  locality: string | null;
  continent: string | null;
}
export interface RealtimeOceanResponse {
  requested: {
    latitude: number;
    longitude: number;
  };
  resolved: {
    marine: RealtimeOceanResolvedPoint;
    weather: RealtimeOceanResolvedPoint;
  };
  location_context: RealtimeOceanLocationContext;
  fetched_at: string;
  current: RealtimeOceanConditions;
  units: RealtimeOceanUnits;
  attribution: {
    name: string;
    url: string;
    provider_name: string;
    provider_url: string;
  };
}
