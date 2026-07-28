import type { BasemapDefinition } from '../types';

/**
 * Carto Dark Matter, no-labels variant — free, no API key, same "legacy
 * unauthenticated raster tiles" tier as esriSatellite. This is a
 * pre-rendered third-party tile set, not a custom style, so its ocean/land
 * colors are a close dark approximation rather than an exact match to any
 * specific hex values — a byte-exact match would need a custom vector-tile
 * style, which the codebase doesn't support yet (`LayerDescriptor.type` is
 * `'raster'`-only; vector layers are noted elsewhere as a later phase).
 *
 * `dark_nolabels` strips every label, including cities/ports — rather than
 * try to filter Carto's label tiles down to "major" places only (not
 * possible without vector data + a place-rank cutoff), place labels are left
 * to the existing `reference-labels` Esri overlay (layerRegistry.ts),
 * already registered and on by default.
 */
export const darkMarine: BasemapDefinition = {
  id: 'darkMarine',
  name: 'Dark Marine',
  attribution: '© OpenStreetMap contributors, © CARTO',
  source: {
    type: 'raster',
    tiles: [
      'https://a.basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}.png',
      'https://b.basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}.png',
      'https://c.basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}.png',
      'https://d.basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}.png',
    ],
    tileSize: 256,
    maxzoom: 19,
  },
};
