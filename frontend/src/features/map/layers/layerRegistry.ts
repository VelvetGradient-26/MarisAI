import type { LayerDescriptor } from '../types';

/**
 * GIBS near-real-time products typically lag ~1 day; requesting "today"
 * for a daily composite often 404s or returns an empty tile. Falling back
 * to yesterday (UTC) is the safer default for a demo.
 */
function recentGibsDate(): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() - 1);
  return d.toISOString().slice(0, 10);
}

const GIBS_DATE = recentGibsDate();

/**
 * Every scientific/reference overlay the app knows about. This is the
 * single place Phase 4-6 datasets get added — a new entry here, not a new
 * component or manager method. Two entries below are real, verified GIBS
 * endpoints; two are honest placeholders (`implemented: false`) for data
 * that needs a different rendering approach than "raster tile," flagged
 * rather than faked.
 */
export const layerRegistry: LayerDescriptor[] = [
  {
    id: 'sst',
    name: 'Sea Surface Temperature',
    category: 'ocean',
    type: 'raster',
    attribution: 'NASA EOSDIS GIBS / GHRSST L4 MUR',
    defaultOpacity: 0.85,
    defaultVisible: false,
    source: {
      type: 'raster',
      tiles: [
        `https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/GHRSST_L4_MUR_Sea_Surface_Temperature/default/${GIBS_DATE}/GoogleMapsCompatible_Level7/{z}/{y}/{x}.png`,
      ],
      tileSize: 256,
      maxzoom: 7,
    },
  },
  {
    id: 'chlorophyll',
    name: 'Chlorophyll-a',
    category: 'ocean',
    type: 'raster',
    attribution: 'NASA EOSDIS GIBS / MODIS Aqua Ocean Color (L2)',
    defaultOpacity: 0.85,
    defaultVisible: false,
    source: {
      type: 'raster',
      tiles: [
        `https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/MODIS_Aqua_L2_Chlorophyll_A/default/${GIBS_DATE}/GoogleMapsCompatible_Level7/{z}/{y}/{x}.png`,
      ],
      tileSize: 256,
      maxzoom: 7,
    },
  },
  {
    id: 'currents',
    name: 'Ocean Currents',
    category: 'ocean',
    type: 'raster',
    attribution: 'Not wired — candidate source: OSCAR / HYCOM',
    implemented: false, // vector-field data; needs particle/arrow rendering, not a plain raster tile
    defaultVisible: false,
    source: { type: 'raster', tiles: [''], tileSize: 256 },
  },
  {
    id: 'ai-hazard-prediction',
    name: 'AI Hazard Prediction (demo)',
    category: 'ai',
    type: 'raster',
    attribution: 'Placeholder — point this at your model\u2019s output tiles in Phase 6',
    implemented: false,
    defaultVisible: false,
    source: { type: 'raster', tiles: [''], tileSize: 256 },
  },
];
