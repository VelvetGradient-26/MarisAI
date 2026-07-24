import type { BasemapDefinition } from '../types';

/** Standard OSM raster tiles. Fair-use only — do not point production
 * traffic at tile.openstreetmap.org; mirror or use a paid provider. */
export const streets: BasemapDefinition = {
  id: 'streets',
  name: 'Streets',
  attribution: '© OpenStreetMap contributors',
  source: {
    type: 'raster',
    tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
    tileSize: 256,
    maxzoom: 19,
  },
};
