import type { BasemapDefinition } from '../types';

/** CARTO's free Dark Matter raster tiles. Fair-use rate limits apply — for
 * production traffic, mirror these tiles or move to a paid CARTO plan. */
export const dark: BasemapDefinition = {
  id: 'dark',
  name: 'Dark',
  attribution: '© OpenStreetMap contributors © CARTO',
  source: {
    type: 'raster',
    tiles: ['https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png'],
    tileSize: 256,
    maxzoom: 20,
  },
};
