import type {
  RasterSourceSpecification,
  RasterLayerSpecification,
} from '@maplibre/maplibre-gl-style-spec';

export type BasemapId = 'satellite' | 'blueMarble';

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

export interface RealtimeOceanConditions {
  time: string | null;
  sea_surface_temperature: number | null;
  wave_height: number | null;
  wave_direction: number | null;
  ocean_current_velocity: number | null;
  ocean_current_direction: number | null;
  wind_speed: number | null;
  air_temperature: number | null;
}

export interface RealtimeOceanUnits {
  sea_surface_temperature: string | null;
  wave_height: string | null;
  wave_direction: string | null;
  ocean_current_velocity: string | null;
  ocean_current_direction: string | null;
  wind_speed: string | null;
  air_temperature: string | null;
}

export interface RealtimeOceanResolvedPoint {
  latitude: number | null;
  longitude: number | null;
  timezone: string | null;
  timezone_abbreviation: string | null;
}

<<<<<<< HEAD
export interface RealtimeOceanLocationContext {
  ocean_name: string | null;
  country_name: string | null;
}

=======
>>>>>>> feature/map-label
export interface RealtimeOceanResponse {
  requested: {
    latitude: number;
    longitude: number;
  };
  resolved: {
    marine: RealtimeOceanResolvedPoint;
    weather: RealtimeOceanResolvedPoint;
  };
<<<<<<< HEAD
  location_context: RealtimeOceanLocationContext;
=======
>>>>>>> feature/map-label
  fetched_at: string;
  current: RealtimeOceanConditions;
  units: RealtimeOceanUnits;
}
