import type { SourceSpecification } from 'maplibre-gl';

/**
 * The shared vector-tile backing for the smooth basemaps.
 *
 * OpenFreeMap serves OpenMapTiles-schema vector tiles from OpenStreetMap
 * with no API key, no token and no request cap, which is why it is used here
 * rather than MapTiler or Carto's vector tiers (both keyed).
 *
 * Referenced by its TileJSON URL rather than a hardcoded tile template on
 * purpose: the template embeds a dated planet snapshot
 * (`/planet/20260726_080001_pt/{z}/{x}/{y}.pbf`) that rolls forward as they
 * republish. Pointing at the TileJSON lets MapLibre resolve the current
 * snapshot itself instead of pinning the map to a build that will eventually
 * be retired.
 */
export const OPENFREEMAP_TILEJSON = 'https://tiles.openfreemap.org/planet';

/** Fonts the label layers resolve against. */
export const OPENFREEMAP_GLYPHS = 'https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf';

/**
 * Only two weights are actually served. "Noto Sans Medium" 404s, and a
 * missing fontstack makes MapLibre drop the whole text layer silently, so
 * these are the only two names any style below may use.
 */
export const FONT_REGULAR = ['Noto Sans Regular'];
export const FONT_BOLD = ['Noto Sans Bold'];

export const VECTOR_ATTRIBUTION =
  '© OpenStreetMap contributors, © OpenFreeMap';

export const openMapTilesSource: SourceSpecification = {
  type: 'vector',
  url: OPENFREEMAP_TILEJSON,
  attribution: VECTOR_ATTRIBUTION,
};
