import type { LayerSpecification } from 'maplibre-gl';
import type { VectorBasemapDefinition } from '../types';
import {
  FONT_BOLD,
  FONT_REGULAR,
  VECTOR_ATTRIBUTION,
  openMapTilesSource,
} from './vectorSource';

/**
 * "Abyss" — the default smooth basemap.
 *
 * Hand-written rather than adopting OpenFreeMap's own 111-layer style. That
 * style is built for street navigation: motorway casings, building
 * footprints, house numbers, transit. On an ocean platform every one of
 * those is noise that also costs draw calls, and none of it can be
 * recoloured to the app's palette without overriding it layer by layer
 * anyway. This is ~18 layers chosen for a marine view.
 *
 * Why this feels different from the raster basemaps: the tiles carry
 * geometry, not pictures. MapLibre re-tessellates and redraws on the GPU at
 * whatever fractional zoom the camera is at, so there is no "load the next
 * zoom level" step — the coastline stays razor sharp mid-pinch and labels
 * grow continuously instead of swapping between pre-rendered images.
 *
 * Palette matches the dashboard's deep-navy/cyan tokens so the map reads as
 * part of the product rather than an embedded third-party widget.
 */

/**
 * Palette. Land is deliberately *lighter* than ocean and the gap between
 * them is wide: the first pass used #04121f sea against #101f2b land, which
 * are only a few points apart in luminance and rendered as one flat mass
 * with coastlines floating on it. Continents have to read at a glance from
 * orbit, so the separation is exaggerated well beyond what a print map
 * would use.
 *
 * The coastline is the app's cyan accent, which is what gives the shoreline
 * its lit edge against the dark sea.
 */
const OCEAN_DEEP = '#030f1e';
const OCEAN_SHELF = '#0a2c47';
const LAND = '#1c2f3f';
const LAND_HIGH = '#263c4e';
const COASTLINE = '#4fd1ff';
const ICE = '#3d6b85';
const BOUNDARY = '#3c5a70';
const LABEL = '#a9c9dd';
const LABEL_HALO = '#020b16';

const layers: LayerSpecification[] = [
  /**
   * Land is the *background*, not a fill.
   *
   * OpenMapTiles has no land polygon at all — there is no "here is a
   * continent" geometry to draw. The schema assumes land is the canvas and
   * ships `water` polygons to cut the seas out of it. Building this the
   * intuitive way round (ocean background, land fill) renders a uniformly
   * blue planet with a few scattered forest patches, because `landcover`
   * only carries wood/grass/ice, never landmass.
   */
  {
    id: 'land',
    type: 'background',
    paint: { 'background-color': LAND },
  },
  // Vegetation and ice give the continents some internal variation so they
  // do not read as flat cut-outs.
  {
    id: 'landcover',
    type: 'fill',
    source: 'omt',
    'source-layer': 'landcover',
    filter: ['!=', ['get', 'subclass'], 'glacier'],
    paint: { 'fill-color': LAND_HIGH, 'fill-opacity': 0.45 },
  },
  {
    id: 'landcover-glacier',
    type: 'fill',
    source: 'omt',
    'source-layer': 'landcover',
    filter: ['==', ['get', 'subclass'], 'glacier'],
    paint: { 'fill-color': ICE, 'fill-opacity': 0.6 },
  },
  // The sea, cut out of the land above. `class` separates the open ocean
  // from lakes and rivers so inland water reads a shade lighter.
  {
    id: 'water',
    type: 'fill',
    source: 'omt',
    'source-layer': 'water',
    paint: {
      'fill-color': [
        'case',
        ['==', ['get', 'class'], 'ocean'],
        OCEAN_DEEP,
        OCEAN_SHELF,
      ],
    },
  },
  {
    id: 'waterway',
    type: 'line',
    source: 'omt',
    'source-layer': 'waterway',
    minzoom: 5,
    paint: {
      'line-color': OCEAN_SHELF,
      'line-width': ['interpolate', ['linear'], ['zoom'], 5, 0.4, 14, 2],
    },
  },
  /**
   * The coastline glow. Two stacked strokes — a wide, low-opacity halo and a
   * thin bright core — give the shore a lit edge against the dark sea. Width
   * interpolates with zoom so the line keeps a constant *visual* weight
   * while zooming rather than thickening into a slab.
   */
  {
    id: 'coastline-glow',
    type: 'line',
    source: 'omt',
    'source-layer': 'water',
    paint: {
      'line-color': COASTLINE,
      'line-opacity': 0.3,
      'line-width': ['interpolate', ['linear'], ['zoom'], 0, 1.5, 6, 4, 12, 8],
      'line-blur': ['interpolate', ['linear'], ['zoom'], 0, 1, 12, 6],
    },
  },
  {
    id: 'coastline',
    type: 'line',
    source: 'omt',
    'source-layer': 'water',
    paint: {
      'line-color': COASTLINE,
      'line-opacity': 0.85,
      'line-width': ['interpolate', ['linear'], ['zoom'], 0, 0.4, 6, 0.8, 14, 1.6],
    },
  },
  {
    id: 'boundary-country',
    type: 'line',
    source: 'omt',
    'source-layer': 'boundary',
    filter: ['<=', ['get', 'admin_level'], 2],
    paint: {
      'line-color': BOUNDARY,
      'line-opacity': 0.7,
      'line-width': ['interpolate', ['linear'], ['zoom'], 1, 0.4, 8, 1.2],
      'line-dasharray': [3, 2],
    },
  },
  // Roads only appear once you are genuinely looking at a place, and only
  // the major ones — a marine dashboard should not turn into a street map.
  {
    id: 'road-major',
    type: 'line',
    source: 'omt',
    'source-layer': 'transportation',
    filter: ['in', ['get', 'class'], ['literal', ['motorway', 'trunk', 'primary']]],
    minzoom: 9,
    paint: {
      'line-color': LAND_HIGH,
      'line-opacity': ['interpolate', ['linear'], ['zoom'], 9, 0, 12, 0.9],
      'line-width': ['interpolate', ['linear'], ['zoom'], 9, 0.5, 16, 3],
    },
  },
  {
    id: 'building',
    type: 'fill',
    source: 'omt',
    'source-layer': 'building',
    minzoom: 14,
    paint: {
      'fill-color': LAND_HIGH,
      'fill-opacity': ['interpolate', ['linear'], ['zoom'], 14, 0, 16, 0.6],
    },
  },
  /**
   * Ocean and sea names — the labels that matter most on this map. Wide
   * letter-spacing and the coastline colour make them read as water rather
   * than as places, without needing a second font weight.
   */
  {
    id: 'label-marine',
    type: 'symbol',
    source: 'omt',
    'source-layer': 'water_name',
    layout: {
      'text-field': ['coalesce', ['get', 'name:en'], ['get', 'name']],
      'text-font': FONT_REGULAR,
      'text-size': ['interpolate', ['linear'], ['zoom'], 2, 10, 8, 15],
      'text-letter-spacing': 0.18,
      'text-max-width': 8,
    },
    paint: {
      'text-color': COASTLINE,
      'text-halo-color': LABEL_HALO,
      'text-halo-width': 1.2,
      'text-opacity': 0.9,
    },
  },
  {
    id: 'label-country',
    type: 'symbol',
    source: 'omt',
    'source-layer': 'place',
    filter: ['==', ['get', 'class'], 'country'],
    layout: {
      'text-field': ['coalesce', ['get', 'name:en'], ['get', 'name']],
      'text-font': FONT_BOLD,
      'text-size': ['interpolate', ['linear'], ['zoom'], 1, 9, 6, 16],
      'text-letter-spacing': 0.12,
      'text-transform': 'uppercase',
      'text-max-width': 7,
    },
    paint: {
      'text-color': LABEL,
      'text-halo-color': LABEL_HALO,
      'text-halo-width': 1.4,
    },
  },
  {
    id: 'label-city',
    type: 'symbol',
    source: 'omt',
    'source-layer': 'place',
    filter: ['in', ['get', 'class'], ['literal', ['city', 'town']]],
    minzoom: 3,
    layout: {
      'text-field': ['coalesce', ['get', 'name:en'], ['get', 'name']],
      'text-font': FONT_REGULAR,
      'text-size': ['interpolate', ['linear'], ['zoom'], 3, 10, 10, 14],
      'text-max-width': 8,
      // Rank is OpenMapTiles' own importance ordering, so the biggest
      // places win when labels collide rather than whichever tile loaded.
      'symbol-sort-key': ['coalesce', ['get', 'rank'], 100],
    },
    paint: {
      'text-color': LABEL,
      'text-halo-color': LABEL_HALO,
      'text-halo-width': 1.2,
    },
  },
];

export const abyss: VectorBasemapDefinition = {
  kind: 'vector',
  id: 'abyss',
  name: 'Abyss',
  blurb: 'Smooth vector · deep navy',
  attribution: VECTOR_ATTRIBUTION,
  sources: { omt: openMapTilesSource },
  layers,
};
