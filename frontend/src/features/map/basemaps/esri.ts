import type { BasemapDefinition } from '../types';

/**
 * Esri's legacy (unauthenticated) World Imagery service. Free, no API key,
 * widely used by open-source GIS tools. Esri has been migrating toward a
 * keyed "basemap layer service" with higher resolution — if this endpoint
 * is ever retired, swap the tile URL for the keyed equivalent.
 */
export const esriSatellite: BasemapDefinition = {
  id: 'satellite',
  name: 'Satellite',
  attribution: 'Esri, Maxar, Earthstar Geographics',
  source: {
    type: 'raster',
    tiles: [
      'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    ],
    tileSize: 256,
    maxzoom: 19,
  },
};
