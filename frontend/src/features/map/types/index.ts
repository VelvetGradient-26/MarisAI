import type {
  RasterSourceSpecification,
  RasterLayerSpecification,
} from 'maplibre-gl';

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
