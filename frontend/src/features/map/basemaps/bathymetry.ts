import type { LayerSpecification } from 'maplibre-gl';
import type { VectorBasemapDefinition } from '../types';
import { TERRAIN_DEM_SOURCE } from './terrainSource';
import {
  FONT_BOLD,
  FONT_REGULAR,
  VECTOR_ATTRIBUTION,
  openMapTilesSource,
} from './vectorSource';

/**
 * "Bathymetry" — the same smooth vector geometry as Abyss, but with the
 * seafloor shaded.
 *
 * The interesting part is that the relief here is real. OpenMapTiles carries
 * no bathymetry at all, so the shading comes from the same Terrarium
 * elevation tiles that drive 3D terrain — and those encode depth below sea
 * level, not just height above it. Running a hillshade over them renders
 * trenches, ridges and the continental shelf break as visible structure even
 * with the map flat.
 *
 * That makes this the basemap to use when the shape of the ocean floor is
 * the thing you care about; Abyss is the cleaner backdrop for data overlays.
 */

// Same contrast reasoning as abyss.ts: land clearly lighter than sea.
const OCEAN_DEEP = '#04182c';
const OCEAN_MID = '#0a3a5e';
const LAND = '#1b3245';
const LAND_HIGH = '#264257';
const COASTLINE = '#4bd6ff';
const BOUNDARY = '#2b4f6b';
const LABEL = '#a8cfe4';
const LABEL_HALO = '#03192e';

const layers: LayerSpecification[] = [
  // Land is the background — OpenMapTiles ships no landmass polygon, only
  // water cut out of it. See abyss.ts for the full explanation.
  {
    id: 'land',
    type: 'background',
    paint: { 'background-color': LAND },
  },
  /**
   * Seafloor relief, and the reason this basemap exists.
   *
   * Sits above the land background and *below* the water fill, because the
   * water fill is deliberately translucent: the shading has to read through
   * the sea, otherwise the relief is hidden by the very ocean it describes.
   *
   * The highlight is a lighter blue rather than white so shallow shelves
   * read as water catching light, and overall contrast is kept low — this
   * is a backdrop, and a punchy hillshade competes with the SST and
   * chlorophyll layers that sit on top of it.
   */
  {
    id: 'seafloor-shade',
    type: 'hillshade',
    source: 'dem',
    paint: {
      'hillshade-exaggeration': 0.45,
      'hillshade-shadow-color': '#010d1a',
      'hillshade-highlight-color': OCEAN_MID,
      'hillshade-accent-color': '#0a3a5c',
      'hillshade-illumination-direction': 315,
    },
  },
  {
    id: 'landcover',
    type: 'fill',
    source: 'omt',
    'source-layer': 'landcover',
    paint: { 'fill-color': LAND_HIGH, 'fill-opacity': 0.35 },
  },
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
        OCEAN_MID,
      ],
      // Translucent on purpose: this is what lets the hillshade below show
      // the shape of the seafloor through the water.
      'fill-opacity': ['case', ['==', ['get', 'class'], 'ocean'], 0.62, 0.85],
    },
  },
  // Brighter than Abyss's: on a shaded seafloor the shoreline needs to be
  // the one unambiguous line.
  {
    id: 'coastline',
    type: 'line',
    source: 'omt',
    'source-layer': 'water',
    paint: {
      'line-color': COASTLINE,
      'line-opacity': 0.75,
      'line-width': ['interpolate', ['linear'], ['zoom'], 0, 0.5, 6, 1, 14, 2],
      'line-blur': 0.4,
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
      'line-opacity': 0.6,
      'line-width': ['interpolate', ['linear'], ['zoom'], 1, 0.4, 8, 1.1],
      'line-dasharray': [3, 2],
    },
  },
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
      'text-opacity': 0.85,
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
      'text-size': ['interpolate', ['linear'], ['zoom'], 1, 9, 6, 15],
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
];

export const bathymetry: VectorBasemapDefinition = {
  kind: 'vector',
  id: 'bathymetry',
  name: 'Bathymetry',
  blurb: 'Smooth vector · shaded seafloor',
  attribution: `${VECTOR_ATTRIBUTION}, elevation © Mapzen / AWS Terrain Tiles`,
  sources: { omt: openMapTilesSource, dem: TERRAIN_DEM_SOURCE },
  layers,
};
