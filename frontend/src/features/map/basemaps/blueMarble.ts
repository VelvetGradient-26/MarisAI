import type { BasemapDefinition } from '../types';

/**
 * NASA GIBS "BlueMarble_NextGeneration" — a static (non-time-varying)
 * composite, so the REST path omits the date segment that daily GIBS
 * products require (see layerRegistry.ts for a time-varying example).
 * Verify against the current GetCapabilities document if this ever 404s:
 * https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/1.0.0/WMTSCapabilities.xml
 */
export const blueMarble: BasemapDefinition = {
  id: 'blueMarble',
  name: 'Blue Marble',
  attribution: 'NASA EOSDIS GIBS',
  source: {
    type: 'raster',
    tiles: [
      'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/BlueMarble_NextGeneration/default/GoogleMapsCompatible_Level8/{z}/{y}/{x}.jpeg',
    ],
    tileSize: 256,
    maxzoom: 8,
  },
};
