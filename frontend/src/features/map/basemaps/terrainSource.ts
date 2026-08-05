import type { RasterDEMSourceSpecification } from 'maplibre-gl';

/**
 * Elevation tiles — and, unusually, *depth* tiles.
 *
 * AWS Terrain Tiles (the former Mapzen set) encode height in the RGB
 * channels of a PNG. Two things make them the right choice here: no API key,
 * and the underlying compilation includes GEBCO/ETOPO bathymetry, so the
 * ocean floor carries real negative elevations rather than being clamped
 * flat at zero.
 *
 * Used only by the Bathymetry basemap's `hillshade` layer, which shades the
 * seafloor on a flat map. There is deliberately no 3D terrain in this app:
 * MapLibre drapes raster overlays onto the terrain mesh, and on a
 * bathymetric DEM that mesh is the seafloor — a sea-surface layer like SST
 * ended up kilometres below the camera and vanished.
 *
 * Terrarium encoding: height = (R * 256 + G + B / 256) - 32768 metres.
 * MapLibre decodes it natively given `encoding: 'terrarium'`.
 */
export const TERRAIN_DEM_SOURCE: RasterDEMSourceSpecification = {
  type: 'raster-dem',
  tiles: ['https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png'],
  encoding: 'terrarium',
  tileSize: 256,
  // The set is published to z15. Asking beyond that returns 404s, which
  // MapLibre surfaces as console noise on every pan.
  maxzoom: 15,
  attribution: 'Elevation © Mapzen / AWS Terrain Tiles, GEBCO, ETOPO1',
};
