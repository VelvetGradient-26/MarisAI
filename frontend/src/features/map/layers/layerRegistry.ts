import type { LayerDescriptor, RasterLayerDescriptor } from '../types';
import { createWindParticleLayer } from '../vectorField/windLayer';

type LayerSource = RasterLayerDescriptor['sources'][number];

const GIBS_WMTS = 'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best';
const GIBS_WMS = 'https://gibs.earthdata.nasa.gov/wms/epsg3857/best/wms.cgi';
const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL || window.location.origin;

/**
 * WHY THE DARK WEDGES / SAWTOOTH APPEARED (background, for whatever's left)
 * --------------------------------------------------------------------------
 * Polar-orbiting satellites image a swath per orbit; if the swath is
 * narrower than the longitude spacing between consecutive orbits, gaps
 * appear between them — widest at the equator, closing toward the poles.
 * SST (GHRSST L4 MUR) is a gap-filled analysis product, not a raw swath, so
 * it never had this problem. Wind speed and air temperature did (SSMIS/AIRS
 * swaths are too narrow) — composite-stacking multiple days brought them to
 * ~99% coverage, but the result still looked patchy enough that they were
 * pulled from the registry entirely rather than shipped as a compromise.
 * Chlorophyll and cloud cover keep their fixes (5-day composite; VIIRS
 * instead of MODIS, whose 3060 km swath self-overlaps at the equator) since
 * both render as clean, honestly-labeled data.
 *
 * HONESTY NOTE
 * ------------
 * A composite is not a snapshot — chlorophyll's 5-day window means a given
 * pixel can be up to 4 days older than its neighbor. That's standard
 * practice (how NASA Worldview's rolling composites work) but it's stated
 * in the layer's `attribution`, and composites are never labeled "live".
 *
 * OPACITY CAVEAT
 * --------------
 * `raster-opacity` composites multiplicatively across stacked sources, so a
 * composite layer defaults to `defaultOpacity: 1` — dropping it re-draws
 * faint ghost seams at swath edges, which is expected, not a regression.
 */

/** UTC date `days` before now, as YYYY-MM-DD. */
function utcDaysAgo(days: number): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() - days);
  return d.toISOString().slice(0, 10);
}

/**
 * Dates for a composite, oldest first.
 *
 * Order matters: LayerManager.add() calls map.addLayer(layer, beforeId) once
 * per source against the *same* beforeId, and MapLibre inserts each new layer
 * immediately beneath beforeId — so source index 0 ends up at the bottom of
 * the stack and the last index on top. Oldest-first therefore puts the most
 * recent pass on top, which is what makes gap-filling work rather than
 * burying today's data under last week's.
 *
 * `lagDays` is the publication delay before a product's newest date exists at
 * all; requesting earlier than that returns empty tiles.
 */
function compositeDates(days: number, lagDays: number): string[] {
  return Array.from({ length: days }, (_, i) => utcDaysAgo(lagDays + days - 1 - i));
}

function gibsWmtsSource(
  layer: string,
  date: string,
  level: number,
  ext: 'png' | 'jpg' = 'png'
): LayerSource {
  return {
    type: 'raster',
    tiles: [
      `${GIBS_WMTS}/${layer}/default/${date}/GoogleMapsCompatible_Level${level}/{z}/{y}/{x}.${ext}`,
    ],
    tileSize: 256,
    maxzoom: level,
  };
}

/**
 * WMS request with MapLibre bbox templating. Used only for products GIBS
 * publishes as JPEG over WMTS (corrected reflectance), because WMS is the
 * only endpoint that will hand them back with a real alpha channel.
 *
 * Built by string concatenation on purpose — URLSearchParams percent-encodes
 * the braces in {bbox-epsg-3857} and MapLibre then fails to substitute it.
 *
 * 512px tiles rather than 256 to cut the request count fourfold; WMS is
 * computed per-request rather than served from a pre-cut tile cache, so it is
 * meaningfully slower than the WMTS layers around it.
 */
function gibsWmsSource(layer: string, date: string, tileSize = 512): LayerSource {
  return {
    type: 'raster',
    tiles: [
      `${GIBS_WMS}?SERVICE=WMS&VERSION=1.1.1&REQUEST=GetMap` +
        `&LAYERS=${layer}&STYLES=&FORMAT=image/png&TRANSPARENT=true` +
        `&SRS=EPSG:3857&BBOX={bbox-epsg-3857}&WIDTH=${tileSize}&HEIGHT=${tileSize}` +
        `&TIME=${date}`,
    ],
    tileSize,
    maxzoom: 9,
  };
}

/**
 * Cross-product of {satellite passes} × {consecutive days}, ordered so the
 * newest day lands on top. Passes within one day (ascending/descending,
 * day/night overpass) are genuinely simultaneous coverage of the same date,
 * so their relative order is arbitrary.
 */
function gibsComposite(
  layers: string[],
  opts: { days: number; lagDays: number; level: number; ext?: 'png' | 'jpg' }
): LayerSource[] {
  return compositeDates(opts.days, opts.lagDays).flatMap((date) =>
    layers.map((layer) => gibsWmtsSource(layer, date, opts.level, opts.ext))
  );
}

/**
 * Every scientific/reference overlay the app knows about — a Windy-style
 * toggle list. This is the single place new datasets get added, not a new
 * component or manager method.
 *
 * Every entry with `implemented` unset (defaults true) points at a real,
 * verified public endpoint with no API key. `legend` values are read from
 * each provider's own published colormap/legend, not invented.
 *
 * Rows with no free public raster source at all stay honest `implemented:
 * false` placeholders naming a real candidate source, rather than faked data.
 */

/**
 * Species exposed as habitat layers, and the label shown in the panel.
 * Hand-listed rather than fetched from the manifest because `layerRegistry`
 * is a static module-level array the map builds from at startup — making it
 * async would push a network dependency into map initialisation for a list
 * that changes only when the model is retrained. The Model Insights page
 * reads the manifest and is the source of truth for what actually exists;
 * a species removed there simply renders transparent tiles here.
 */
const HABITAT_SPECIES: Array<{ key: string; label: string }> = [
  { key: 'yellowfin_tuna', label: 'Yellowfin Tuna' },
  { key: 'skipjack_tuna', label: 'Skipjack Tuna' },
  { key: 'bigeye_tuna', label: 'Bigeye Tuna' },
  { key: 'indian_mackerel', label: 'Indian Mackerel' },
  { key: 'oil_sardine', label: 'Oil Sardine' },
];

/**
 * The seasonal slice to show. The model is monthly and its export is one
 * full seasonal cycle, so the current calendar month is the most meaningful
 * default — it makes the map track the season rather than freezing on an
 * arbitrary month. It is a climatology, not a forecast for *this* year, and
 * every layer's attribution says so.
 */
function currentMonth(): number {
  return new Date().getUTCMonth() + 1;
}

const MONTH_NAMES = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

/**
 * Sequential single-hue ramp, matching SUITABILITY_STOPS in
 * backend/services/predictions.py. Kept in sync by hand — RGB tuples there
 * for numpy interpolation, CSS hex here for the legend bar; two
 * representations of the same five control points, same arrangement as SST.
 */
const SUITABILITY_STOPS = [
  { offset: 0, color: '#CDE2FB' },
  { offset: 0.25, color: '#86B6EF' },
  { offset: 0.5, color: '#3987E5' },
  { offset: 0.75, color: '#256ABF' },
  { offset: 1, color: '#0D366B' },
];

/** Cool-to-hot semantic heat ramp; matches BLOOM_RISK_STOPS in the backend. */
const BLOOM_RISK_STOPS = [
  { offset: 0, color: '#DEEBF7' },
  { offset: 0.25, color: '#A1D99B' },
  { offset: 0.5, color: '#FED976' },
  { offset: 0.75, color: '#FD8D3C' },
  { offset: 1, color: '#BD0026' },
];

function habitatLayers(): RasterLayerDescriptor[] {
  const month = currentMonth();
  return HABITAT_SPECIES.map(({ key, label }) => ({
    id: `habitat-${key.replace(/_/g, '-')}`,
    name: `Habitat: ${label}`,
    category: 'ai' as const,
    type: 'raster' as const,
    attribution:
      `Maris AI habitat-suitability model (MaxEnt + Random Forest + LightGBM ensemble), ` +
      `${MONTH_NAMES[month - 1]} climatology. Trained on OBIS occurrence records 2000-2013 ` +
      `with Copernicus Marine environmental covariates, validated by spatial block ` +
      `cross-validation. MODEL OUTPUT, not observation: values are relative habitat ` +
      `suitability, not probability of catch, and the model is presence-only (no verified ` +
      `absences exist). Northern Indian Ocean only — elsewhere renders transparent.`,
    defaultOpacity: 0.75,
    defaultVisible: false,
    sources: [
      {
        type: 'raster' as const,
        tiles: [`${API_BASE_URL}/api/predictions/habitat/${key}/${month}/{z}/{x}/{y}.png`],
        tileSize: 256,
        // The model grid is 0.25 degrees; past this the GPU is just
        // upsampling, and a crisper-looking tile would imply precision the
        // model does not have.
        maxzoom: 7,
      },
    ],
    legend: {
      type: 'gradient' as const,
      unit: 'suitability',
      min: 0,
      max: 1,
      stops: SUITABILITY_STOPS,
    },
  }));
}

function bloomRiskLayers(): RasterLayerDescriptor[] {
  return [3, 5, 7].map((horizon) => ({
    id: `bloom-risk-t${horizon}`,
    name: `Bloom Risk (+${horizon}d)`,
    category: 'ai' as const,
    type: 'raster' as const,
    attribution:
      `Maris AI harmful-algal-bloom early warning, ${horizon}-day lead. LightGBM with ` +
      `isotonic calibration, so values read as probabilities. Validated by rolling-origin ` +
      `cross-validation with an embargo gap; beats a persistence baseline at every lead. ` +
      `WEAK LABEL: a "bloom" is model chlorophyll above the local seasonal 90th percentile ` +
      `— a proxy, not a verified bloom, and it says nothing about toxicity. Skill falls with ` +
      `lead time (at 80% recall the false-alarm rate is 0.55 at +3d but 0.80 at +7d). ` +
      `Arabian Sea only — elsewhere renders transparent.`,
    defaultOpacity: 0.75,
    defaultVisible: false,
    sources: [
      {
        type: 'raster' as const,
        tiles: [`${API_BASE_URL}/api/predictions/hab/${horizon}/{z}/{x}/{y}.png`],
        tileSize: 256,
        maxzoom: 7,
      },
    ],
    legend: {
      type: 'gradient' as const,
      unit: 'P(bloom)',
      min: 0,
      max: 1,
      stops: BLOOM_RISK_STOPS,
    },
  }));
}

export const layerRegistry: LayerDescriptor[] = [
  {
    id: 'reference-labels',
    name: 'Place Labels',
    category: 'reference',
    type: 'raster',
    attribution: 'Esri, Garmin, USGS, NPS',
    defaultVisible: true,
    defaultOpacity: 0.75,
    hideOpacitySlider: true,
    sources: [
      {
        type: 'raster',
        tiles: [
          'https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Reference_Overlay/MapServer/tile/{z}/{y}/{x}',
        ],
        tileSize: 256,
        maxzoom: 19,
      },
    ],
  },

  // --- Ocean / atmosphere conditions ---
  // SST is rendered server-side from Copernicus Marine (see
  // backend/services/copernicus_sst.py + backend/services/colormaps.py) —
  // real thetao (potential temperature) at ~0.494m depth, hourly source
  // resolution, cached in memory and rasterized into tiles on request. Not
  // NASA GIBS (that was the previous source; replaced per spec). maxzoom
  // capped at 8 like the other GIBS/GFW layers below: native data is ~9km
  // (1/12°) resolution, so deeper zoom tiles gain nothing beyond what
  // MapLibre's own GPU bilinear upsampling already provides past maxzoom.
  {
    id: 'sst',
    name: 'Sea Surface Temperature',
    category: 'ocean',
    type: 'raster',
    attribution:
      'Copernicus Marine Service — GLOBAL_ANALYSISFORECAST_PHY_001_024, thetao (sea water ' +
      'potential temperature) at 0.494m depth, hourly resolution.',
    defaultOpacity: 0.6,
    defaultVisible: false,
    // GPU-side vividness bump only (not a colormap change — the legend still
    // shows the true scale): tiles blended at 0.6 opacity over the Dark
    // Marine basemap were reading as dim/washed-out.
    rasterPaint: { contrast: 0.2, saturation: 0.25 },
    sources: [
      {
        type: 'raster',
        tiles: [`${API_BASE_URL}/api/tiles/sst/{z}/{x}/{y}.png`],
        tileSize: 256,
        maxzoom: 8,
      },
    ],
    legend: {
      type: 'gradient',
      unit: '°C',
      min: -2,
      max: 35,
      // Matches SST_COLORMAP_STOPS in backend/services/colormaps.py — kept in
      // sync by hand (RGB tuples there vs. CSS hex here; two representations
      // of the same 9 control points, not mechanically shared).
      stops: [
        { offset: 0, color: '#3B0F70' }, // -2C deep purple
        { offset: 0.0541, color: '#1E3A8A' }, // 0C dark blue
        { offset: 0.1892, color: '#1D4ED8' }, // 5C blue
        { offset: 0.3243, color: '#06B6D4' }, // 10C cyan
        { offset: 0.4595, color: '#14B8A6' }, // 15C turquoise
        { offset: 0.5946, color: '#22C55E' }, // 20C green
        { offset: 0.7297, color: '#EAB308' }, // 25C yellow
        { offset: 0.8649, color: '#F97316' }, // 30C orange
        { offset: 1, color: '#DC2626' }, // 35C red
      ],
    },
  },
  {
    id: 'chlorophyll',
    name: 'Chlorophyll-a',
    category: 'ocean',
    type: 'raster',
    attribution:
      'NASA EOSDIS GIBS / MODIS Aqua Ocean Color L2 — 5-day rolling composite, most recent ' +
      'observation per pixel. Remaining blank ocean is cloud, not an orbital gap: the sensor ' +
      'cannot see through cloud, so persistently overcast water has no valid retrieval at all.',
    defaultOpacity: 1,
    defaultVisible: false,
    sources: gibsComposite(['MODIS_Aqua_L2_Chlorophyll_A'], {
      days: 5,
      lagDays: 1,
      level: 7,
    }),
    legend: {
      type: 'categories',
      unit: 'mg/m³',
      categories: [
        { label: 'Low', range: '< 0.3', color: 'rgb(0,149,255)' },
        { label: 'Medium', range: '0.3–3', color: 'rgb(0,255,119)' },
        { label: 'High', range: '> 3', color: 'rgb(225,0,0)' },
      ],
    },
  },
  {
    id: 'cloud-cover',
    name: 'Cloud Cover',
    category: 'ocean',
    type: 'raster',
    // Two changes vs. the MODIS version: VIIRS's 3060 km swath self-overlaps
    // at the equator so there are no orbital gaps to fill, and the WMS PNG
    // request gives transparent no-data instead of JPEG's opaque black.
    attribution:
      'NASA EOSDIS GIBS / VIIRS NOAA-20 True Color (Daily) — the cloud-fraction data product ' +
      'renders as unusable noise, so real satellite imagery is used instead. Daylight ' +
      'reflectance, so whichever pole is in polar night has no imagery to show; that region is ' +
      'now transparent rather than black.',
    defaultOpacity: 0.55,
    defaultVisible: false,
    sources: [gibsWmsSource('VIIRS_NOAA20_CorrectedReflectance_TrueColor', utcDaysAgo(1))],
    legend: {
      type: 'note',
      text: 'Real satellite imagery — white/grey = cloud, blended over the basemap.',
    },
  },

  // --- Flow (animated GPU particle layers, render above ocean color fields
  // like SST so wind and SST can be viewed together — see
  // frontend/src/features/map/vectorField/ for the reusable engine and
  // backend/services/copernicus_wind.py for the real data behind it). Not
  // in the 'ocean' exclusive group: unlike SST/chlorophyll (full-coverage
  // "pick one" maps), wind is a stackable overlay meant to be shown
  // alongside a scalar field, which is the whole point of a Windy-style view.
  {
    id: 'wind',
    name: 'Wind',
    category: 'flow',
    type: 'custom',
    attribution:
      'Copernicus Marine Service — WIND_GLO_PHY_L4_NRT_012_004, gap-filled blend of ' +
      'scatterometer and model surface wind, hourly, 0.125°.',
    defaultOpacity: 0.9,
    defaultVisible: false,
    createLayer: (id) => createWindParticleLayer(id, 0.9),
    legend: {
      type: 'gradient',
      unit: 'm/s',
      min: 0,
      max: 25,
      // Matches WIND_SPEED_COLOR_STOPS in vectorField/colorRamp.ts.
      stops: [
        { offset: 0, color: '#1e3a8a' },
        { offset: 0.08, color: '#06b6d4' },
        { offset: 0.2, color: '#22c55e' },
        { offset: 0.32, color: '#eab308' },
        { offset: 0.48, color: '#f97316' },
        { offset: 0.72, color: '#dc2626' },
        { offset: 1, color: '#9333ea' },
      ],
    },
  },

  // --- Boundaries / reference (render above science data, alongside labels) ---
  {
    id: 'eez',
    name: 'Exclusive Economic Zones',
    category: 'reference',
    type: 'raster',
    attribution: 'Flanders Marine Institute (Marine Regions), VLIZ',
    defaultVisible: false,
    sources: [
      {
        type: 'raster',
        tiles: [
          'https://geo.vliz.be/geoserver/MarineRegions/wms?service=WMS&version=1.1.1&request=GetMap&layers=eez&styles=&format=image/png&transparent=true&srs=EPSG:3857&bbox={bbox-epsg-3857}&width=256&height=256',
        ],
        tileSize: 256,
        maxzoom: 14,
      },
    ],
    legend: {
      type: 'image',
      src: 'https://geo.vliz.be/geoserver/MarineRegions/wms?service=WMS&version=1.1.1&request=GetLegendGraphic&layer=eez&format=image/png',
      alt: 'EEZ boundary legend',
    },
  },
  {
    id: 'marine-protected-areas',
    name: 'Marine Protected Areas',
    category: 'reference',
    type: 'raster',
    attribution: 'UNEP-WCMC & IUCN, World Database on Protected Areas (WDPA)',
    defaultVisible: false,
    sources: [
      {
        type: 'raster',
        tiles: [
          'https://data-gis.unep-wcmc.org/server/rest/services/ProtectedSites/The_World_Database_of_Protected_Areas/MapServer/export?bbox={bbox-epsg-3857}&bboxSR=3857&imageSR=3857&size=256,256&format=png32&transparent=true&f=image&layers=show:0,1',
        ],
        tileSize: 256,
        maxzoom: 14,
      },
    ],
    legend: {
      type: 'swatch',
      color: 'rgb(219,124,111)',
      label: 'Protected area boundary',
    },
  },

  // --- Vessel traffic (Global Fishing Watch 4Wings API, proxied through our
  // backend so the GFW bearer token never reaches the browser — see
  // backend/services/gfw.py and backend/routers/tiles.py). Both are real
  // AIS/SAR-derived vessel density, not live per-ship markers: GFW's tile
  // API returns rendered heatmap PNGs, not point positions, so "AIS Ships"
  // here means AIS-reported vessel presence density, honestly labeled below
  // rather than presented as a live ship tracker it isn't.
  //
  // The color ramp is rescaled per zoom level server-side (services/gfw.py,
  // `_scaled_ramp`) — 4Wings sums presence into whatever area one tile pixel
  // covers, which shrinks ~4x per zoom level, so a ramp tuned for one zoom
  // saturates solid at every lower zoom without rescaling. Verified: at z=2
  // with an unscaled ramp, open mid-Pacific ocean hit 52% pixel coverage at
  // near-max alpha, visually identical to the Singapore Strait. defaultOpacity
  // is capped at 0.4 so the basemap stays legible underneath either layer.
  {
    id: 'shipping-routes',
    name: 'Shipping Routes',
    category: 'reference',
    type: 'raster',
    attribution:
      'Global Fishing Watch / Sentinel-1 SAR vessel detections, 30-day window (~60-day publication ' +
      'lag). Traces well-traveled corridors via radar-detected vessels, including ones not ' +
      'broadcasting AIS.',
    defaultOpacity: 0.4,
    defaultVisible: false,
    sources: [
      {
        type: 'raster',
        tiles: [`${API_BASE_URL}/api/tiles/gfw/sar-presence/{z}/{x}/{y}.png`],
        tileSize: 256,
        maxzoom: 8,
      },
    ],
    legend: {
      type: 'swatch',
      color: 'rgb(255,196,0)',
      label: 'SAR-detected vessel activity',
    },
  },
  {
    id: 'ais-ships',
    name: 'AIS Ships',
    category: 'reference',
    type: 'raster',
    attribution:
      'Global Fishing Watch / AIS vessel presence, 30-day window (~2-day publication lag). A ' +
      'density heatmap of AIS-broadcasting vessels, not live per-ship positions — GFW’s free tile ' +
      'API renders aggregate presence, not individual tracks.',
    defaultOpacity: 0.4,
    defaultVisible: false,
    sources: [
      {
        type: 'raster',
        tiles: [`${API_BASE_URL}/api/tiles/gfw/ais-presence/{z}/{x}/{y}.png`],
        tileSize: 256,
        maxzoom: 8,
      },
    ],
    legend: {
      type: 'swatch',
      color: 'rgb(34,211,238)',
      label: 'AIS vessel presence',
    },
  },
  // ------------------------------------------------------------------
  // AI predictions
  //
  // These differ from every other layer above in an important way: they are
  // MODEL OUTPUT, not observation. Nothing here was measured — it is what a
  // model trained on historical data infers. Three honesty constraints
  // follow, and each is implemented rather than just stated:
  //
  //  * Coverage is REGIONAL, not global. Habitat covers the northern Indian
  //    Ocean, bloom risk a smaller Arabian Sea box. Outside those, the tile
  //    endpoint returns transparent — the map shows nothing rather than
  //    extrapolating a model into water it never saw.
  //  * The suitability layers are a CLIMATOLOGICAL month from a 2000-2013
  //    model, not a live forecast, and the attribution says so.
  //  * Bloom risk is a WEAK label — chlorophyll above a local seasonal
  //    percentile is a proxy for a bloom, not a verified or toxic one.
  //
  // Full skill numbers, drivers and limitations live on the Model Insights
  // page (/predictions); the attribution strings here are the short version.
  ...habitatLayers(),
  ...bloomRiskLayers(),
];
