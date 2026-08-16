import type {
  GeoJsonLayerDescriptor,
  LayerDescriptor,
  RasterLayerDescriptor,
} from '../types';
import { createWindParticleLayer } from '../vectorField/windLayer';
import {
  createCurrentsDepthParticleLayer,
  createCurrentsParticleLayer,
  createDriftParticleLayer,
  createStokesParticleLayer,
} from '../vectorField/currentsLayer';

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
 * that changes only when the model is retrained. The export manifest
 * (`/api/predictions/manifest`) remains the source of truth for what
 * actually exists; a species dropped from the export simply renders
 * transparent tiles here rather than failing.
 */
const HABITAT_SPECIES: Array<{ key: string; label: string }> = [
  { key: 'yellowfin_tuna', label: 'Yellowfin Tuna' },
  { key: 'skipjack_tuna', label: 'Skipjack Tuna' },
  { key: 'bigeye_tuna', label: 'Bigeye Tuna' },
  { key: 'indian_mackerel', label: 'Indian Mackerel' },
  { key: 'oil_sardine', label: 'Oil Sardine' },
];

/** Forecast leads the HAB export covers, in days. */
const HAB_HORIZONS = [3, 5, 7];

function habitatLayerId(speciesKey: string): string {
  return `habitat-${speciesKey.replace(/_/g, '-')}`;
}

/** The depth levels the backend offers, mirroring `DEPTH_LADDER` in
 *  `services/currents_depth.py`. Six rather than the product's fifty because
 *  each is an independent whole-globe fetch — see that module for why these. */
const CURRENTS_DEPTH_LEVELS = [50, 100, 200, 500, 1000];

function currentsDepthLayerId(depth: number): string {
  return `currents-${depth}m`;
}

/**
 * The combined drift field, one layer per drifting object.
 *
 * Mirrors `LEEWAY_PRESETS` in `services/drift.py`. Duplicated here rather than
 * fetched, and that is a narrower claim than it looks: the *layer list* has to
 * exist at module scope, because the registry is a static description the picker
 * renders before any request is made. The authoritative coefficients still come
 * from `/api/ocean/drift/presets`, and every number below travels to the backend
 * as `alpha` — so a revised coefficient changes the field this layer draws, and
 * only the label here would need catching up.
 *
 * Three, not five: the picker already carries four flow layers, and the useful
 * span is "water only" against "something with real freeboard". The middle
 * coefficients are reachable through the API for anyone who needs them.
 */
const DRIFT_PRESETS = [
  { key: 'water_only', alpha: 0, name: 'Drift — water only' },
  { key: 'person_in_water', alpha: 0.035, name: 'Drift — person in water' },
  { key: 'life_raft', alpha: 0.06, name: 'Drift — life raft (no drogue)' },
];

function driftLayerId(presetKey: string): string {
  return `drift-${presetKey.replace(/_/g, '-')}`;
}

function bloomRiskLayerId(horizon: number): string {
  return `bloom-risk-t${horizon}`;
}

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
    id: habitatLayerId(key),
    name: `Habitat: ${label}`,
    category: 'ai' as const,
    type: 'raster' as const,
    attribution:
      `Maris AI habitat-suitability model (MaxEnt + Random Forest + LightGBM ensemble), ` +
      `${MONTH_NAMES[month - 1]} climatology. Trained on OBIS occurrence records 2000-2013 ` +
      `with Copernicus Marine environmental covariates, validated by spatial block ` +
      `cross-validation. SKILL: TSS 0.76-0.90 across five spatial folds of 397-791 points ` +
      `each; a single held-out block scores 0.79 on 885 points / 167 presences. The fold ` +
      `range is the more trustworthy signal — one block of that size carries a wide ` +
      `confidence interval, so a lone number would imply precision this does not have. ` +
      `MODEL OUTPUT, not observation: values are relative habitat ` +
      `suitability, not probability of catch, and the model is presence-only (no verified ` +
      `absences exist). Northern Indian Ocean only — elsewhere renders transparent.`,
    defaultOpacity: 0.75,
    defaultVisible: false,
    sources: [
      {
        type: 'raster' as const,
        tiles: [`${API_BASE_URL}/api/predictions/habitat/${key}/${month}/{z}/{x}/{y}.png`],
        tileSize: 256,
        // The model grid is 0.25 degrees; the backend already bilinearly
        // smooths each tile (matching the SST layer), so past this zoom the
        // GPU's own upsampling is the only thing adding further softness.
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

/**
 * The measured operating point of each lead, at the 80%-recall threshold the
 * model is tuned to. Stated per horizon rather than as one sentence covering
 * all three, because the difference between them is the whole decision: at +3d
 * roughly half of alerts are genuine, at +7d four in five are false.
 *
 * That is defensible for a screening tool — a missed bloom costs more than a
 * false alarm — but it has to be a decision the reader can see, not a horizon
 * that merely exists in a dropdown next to a much stronger one.
 */
const HAB_OPERATING_POINTS: Record<number, { precision: number; falseAlarm: number }> = {
  3: { precision: 0.449, falseAlarm: 0.551 },
  5: { precision: 0.28, falseAlarm: 0.72 },
  7: { precision: 0.202, falseAlarm: 0.798 },
};

function bloomRiskLayers(): RasterLayerDescriptor[] {
  return HAB_HORIZONS.map((horizon) => ({
    id: bloomRiskLayerId(horizon),
    name:
      horizon >= 7 ? `Bloom Risk (+${horizon}d, screening)` : `Bloom Risk (+${horizon}d)`,
    category: 'ai' as const,
    type: 'raster' as const,
    attribution:
      `Maris AI harmful-algal-bloom early warning, ${horizon}-day lead. LightGBM with ` +
      `isotonic calibration, so values read as probabilities. Validated by rolling-origin ` +
      `cross-validation with an embargo gap; beats a persistence baseline at every lead. ` +
      `WEAK LABEL: a "bloom" is model chlorophyll above the local seasonal 90th percentile ` +
      `— a proxy, not a verified bloom, and it says nothing about toxicity. ` +
      `OPERATING POINT at 80% recall: precision ${HAB_OPERATING_POINTS[horizon].precision}, ` +
      `false-alarm rate ${HAB_OPERATING_POINTS[horizon].falseAlarm} — ` +
      (horizon >= 7
        ? `four in five alerts at this lead are false. SCREENING ONLY: use it to decide where ` +
          `to look, not to decide that a bloom is happening; the +3d layer is the one that ` +
          `would survive contact with a coastal agency. `
        : `about ${Math.round((1 - HAB_OPERATING_POINTS[horizon].falseAlarm) * 100)} in 100 ` +
          `alerts at this lead are genuine. `) +
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

/**
 * Vessel colour by ship type, so a glance separates a tanker from a trawler.
 * `ship_type` arrives only with AIS static data (~6 min behind a vessel's
 * first position), so the fallback is not a rare case — it is every vessel
 * for its first few minutes, and reads as neutral grey rather than being
 * lumped in with a real category.
 */
const VESSEL_TYPE_COLORS: Array<[string, string]> = [
  ['Cargo', '#38bdf8'],
  ['Tanker', '#fb7185'],
  ['Passenger', '#4ade80'],
  ['Fishing', '#fbbf24'],
  ['Tug', '#c084fc'],
  ['Pilot vessel', '#c084fc'],
  ['High-speed craft', '#2dd4bf'],
  ['Sailing', '#a3e635'],
  ['Pleasure craft', '#a3e635'],
  ['Search and rescue', '#f472b6'],
];
const VESSEL_COLOR_FALLBACK = '#94a3b8';

const VESSEL_COLOR = [
  'match',
  ['coalesce', ['get', 'ship_type'], ''],
  ...VESSEL_TYPE_COLORS.flat(),
  VESSEL_COLOR_FALLBACK,
];

/**
 * Radius grows with zoom so vessels stay findable on a world view without
 * becoming blobs when you zoom into a harbour.
 */
const vesselRadius = (scale: number) => [
  'interpolate',
  ['linear'],
  ['zoom'],
  2, 1.6 * scale,
  5, 2.4 * scale,
  8, 3.6 * scale,
  12, 5.5 * scale,
];

/**
 * Live AIS vessels: three stacked circle layers rather than one.
 *
 * The glow is real overdraw, not a styling trick — a wide, heavily blurred,
 * low-opacity halo, a tighter mid halo, then a small crisp core with a dark
 * outline so the vessel still reads as a distinct point against its own
 * glow. One circle with `circle-blur` alone gives either a sharp dot or a
 * vague smudge, never both.
 *
 * Only the core is hit-tested (`interactiveLayerIndices`); hovering the
 * outer halo would trigger a popup from well outside the vessel.
 */
/**
 * Detected mesoscale eddies, drawn at their real size.
 *
 * Two colours and no ramp, because polarity is the only categorical thing a
 * detection carries: teal for cyclonic (rotating with the planet — cold-core
 * and upwelling in the northern hemisphere), amber for anticyclonic. Both
 * clear 3:1 against the Abyss basemap's near-black ocean, the same floor the
 * forecast ramps are held to.
 *
 * The ring is drawn at the eddy's *equivalent* radius rather than as a
 * fixed-pixel symbol: the size is a measurement, and a dot that stayed the
 * same at every zoom would assert something the detector never said. It is
 * round by construction — the equivalent radius of the region where rotation
 * beats strain — and is not the feature's real outline, which is why the
 * attribution says so and the centre dot is what gets hit-tested.
 */
const EDDY_COLOR = [
  'match',
  ['get', 'polarity'],
  'cyclonic',
  '#5eead4',
  'anticyclonic',
  '#fb923c',
  '#94a3b8',
];

function eddyLayer(): GeoJsonLayerDescriptor {
  return {
    id: 'eddies',
    name: 'Eddies (detected)',
    // 'flow', not 'ai': this is a diagnostic computed from the observed
    // current field, not model output. Filing it under "AI (Experimental)"
    // would label an observation as an inference, which is the one direction
    // this codebase never rounds in.
    category: 'flow',
    type: 'geojson',
    attribution:
      'Mesoscale eddies detected from the live Copernicus surface-current field by the ' +
      'Okubo-Weiss method (W < -0.2σ), which finds water where rotation beats strain. ' +
      'Detection only — features are not tracked between refreshes, so none of them has an ' +
      'age or a trajectory. The ring is the equivalent radius of the detected core, not the ' +
      'feature outline. The threshold is relative to the variance of the field, so this is a ' +
      'consistent detector rather than an eddy census; features smaller than the ~0.25° grid ' +
      'can resolve are absent rather than zero, the equatorial band within 5° is excluded ' +
      'because polarity has no meaning where the Coriolis parameter vanishes, and nearshore ' +
      'eddies are under-detected where the derivative meets the land mask.',
    defaultOpacity: 0.9,
    defaultVisible: false,
    interactiveLayerIndices: [2],
    paintLayers: (opacity: number) => [
      {
        type: 'fill',
        filter: ['==', ['geometry-type'], 'Polygon'],
        paint: { 'fill-color': EDDY_COLOR, 'fill-opacity': 0.12 * opacity },
      },
      {
        type: 'line',
        filter: ['==', ['geometry-type'], 'Polygon'],
        paint: {
          'line-color': EDDY_COLOR,
          'line-width': 1.4,
          'line-opacity': 0.85 * opacity,
        },
      },
      {
        type: 'circle',
        filter: ['==', ['geometry-type'], 'Point'],
        paint: {
          'circle-color': EDDY_COLOR,
          'circle-radius': 3,
          'circle-opacity': opacity,
          'circle-stroke-width': 0.6,
          'circle-stroke-color': 'rgba(2,12,27,0.85)',
          'circle-stroke-opacity': opacity,
        },
      },
    ],
    legend: {
      type: 'categories',
      unit: 'rotation',
      categories: [
        {
          label: 'Cyclonic',
          range: 'with the planet’s rotation',
          color: '#5eead4',
        },
        {
          label: 'Anticyclonic',
          range: 'against it',
          color: '#fb923c',
        },
      ],
    },
  };
}

/**
 * Where the ocean has been sampled for environmental DNA.
 *
 * THE EMPTY MAP IS THE DATA. Every other layer in this registry is a field —
 * SST, currents, the forecast grids — defined across the whole ocean. This one
 * is defined in about 1,500 geohash cells worldwide — 27,286 km2, well under
 * a hundredth of one percent of the ocean, and smaller than Belgium. A reader
 * arriving from the SST layer will read the blankness
 * as a failed load, so the status chip states the coverage rather than waiting
 * to be asked, and the attribution leads with it.
 *
 * THE RAMP IS LOGARITHMIC AND ITS DOMAIN IS FIXED. Occupied cells span more
 * than six orders of magnitude — 1 record in the quietest, 4,353,873 in the
 * busiest, which is the Australian Microbiome program's water off Sydney. On a
 * linear ramp the planet is black around one bright pixel. The domain is
 * hardcoded to 0-6.5 in log10 rather than normalised against whatever is
 * loaded, so a cell keeps its colour as you zoom and the legend below can name
 * real numbers; today's maximum sits just past the top stop and clamps.
 *
 * VIOLET, BECAUSE IT IS NOT A MEASUREMENT OF THE OCEAN. The physical layers
 * have spent the spectrum — wind's rainbow, currents' amber, the eddy pair's
 * teal and amber, the forecast ramps' viridis and diverging blues. This is
 * effort, not a property of the water, and it should not look like one. Every
 * stop clears 3:1 against the Abyss basemap's near-black ocean (the darkest,
 * #7c3aed, measures 3.38:1) — the same floor the forecast ramps are held to.
 */
const EDNA_COLOR = [
  'interpolate',
  ['linear'],
  ['get', 'log_records'],
  0,
  '#7c3aed',
  2,
  '#a855f7',
  4,
  '#d8b4fe',
  6.5,
  '#fce7f3',
];

function ednaCoverageLayer(): GeoJsonLayerDescriptor {
  return {
    id: 'edna-coverage',
    name: 'eDNA Sampling Coverage',
    // 'reference', not 'ocean' or 'ai': this is context about how the ocean was
    // observed, in the same sense as EEZ boundaries and vessel traffic. It is
    // not a field of the water and nothing here was modelled.
    category: 'reference',
    type: 'geojson',
    attribution:
      'Environmental-DNA sampling effort, from OBIS records carrying the Darwin Core ' +
      'DNADerivedData extension. THIS LAYER IS ALMOST ENTIRELY EMPTY AND THAT IS THE ' +
      'DATA: on the finest grid, molecular sampling of the world ocean covers about ' +
      '27,000 km² — under a hundredth of one percent of the sea surface, an area smaller ' +
      'than Belgium — and the blank areas are water nobody has sequenced. Coverage read ' +
      'off a coarser grid looks far larger only because each cell credits one water ' +
      'sample with everything around it. ' +
      'Colour is detections per cell on a LOGARITHMIC scale — the busiest cell holds ' +
      'millions and the quietest holds one. A detection is recovered genetic material, not ' +
      'a sighting: eDNA drifts on currents, degrades over hours to days, is amplified ' +
      'through primers that favour some taxa over others, and is named only where a ' +
      'reference sequence exists. Counts are taxon-detections rather than samples, so a ' +
      'microbial dataset returns thousands per bottle where a fish survey returns a ' +
      'handful, and the two are not comparable. Absence of colour means nobody sampled ' +
      'there — never that nothing lives there.',
    defaultOpacity: 0.85,
    defaultVisible: false,
    interactiveLayerIndices: [0],
    paintLayers: (opacity: number) => [
      {
        type: 'fill',
        paint: { 'fill-color': EDNA_COLOR, 'fill-opacity': 0.62 * opacity },
      },
      {
        // An outline, because at the finer precisions a cell is a few pixels
        // across at the zoom it appears at — a bare fill of a 0.04 deg cell is
        // invisible against a dark basemap, and this layer's whole job is to
        // show that a lone sample exists in an otherwise blank ocean.
        type: 'line',
        paint: {
          'line-color': EDNA_COLOR,
          'line-width': 0.8,
          'line-opacity': 0.9 * opacity,
        },
      },
    ],
    legend: {
      type: 'categories',
      unit: 'detections per cell (log scale)',
      categories: [
        { label: '1 – 100', range: 'a study passed through', color: '#7c3aed' },
        { label: '100 – 10k', range: 'repeat sampling', color: '#a855f7' },
        { label: '10k – 1M', range: 'a monitoring programme', color: '#d8b4fe' },
        { label: '1M+', range: 'a time-series station', color: '#fce7f3' },
      ],
    },
  };
}

function liveVesselLayer(): GeoJsonLayerDescriptor {
  return {
    id: 'live-vessels',
    name: 'Live Vessels (AIS)',
    category: 'reference',
    type: 'geojson',
    attribution:
      'Live AIS broadcasts via aisstream.io. Real vessel self-reports, received in near real ' +
      'time — position, speed and course update within seconds; identity, destination and ' +
      'dimensions arrive on a slower ~6-minute cycle, so a vessel can be on the map for some ' +
      'time before its name or type is known. AIS is self-reported and not universal: small ' +
      'craft may carry no transponder, and coverage away from shore depends on satellite ' +
      'reception. Absence of a vessel here is not evidence there is none.',
    defaultOpacity: 1,
    defaultVisible: false,
    hideOpacitySlider: false,
    interactiveLayerIndices: [2],
    paintLayers: (opacity: number) => [
      {
        type: 'circle',
        paint: {
          'circle-color': VESSEL_COLOR,
          'circle-radius': vesselRadius(3.4),
          'circle-blur': 1,
          'circle-opacity': 0.28 * opacity,
        },
      },
      {
        type: 'circle',
        paint: {
          'circle-color': VESSEL_COLOR,
          'circle-radius': vesselRadius(1.9),
          'circle-blur': 0.7,
          'circle-opacity': 0.45 * opacity,
        },
      },
      {
        type: 'circle',
        paint: {
          'circle-color': VESSEL_COLOR,
          'circle-radius': vesselRadius(1),
          'circle-opacity': opacity,
          'circle-stroke-width': 0.6,
          'circle-stroke-color': 'rgba(2,12,27,0.85)',
          'circle-stroke-opacity': opacity,
        },
      },
    ],
    legend: {
      type: 'categories',
      unit: 'vessel type',
      categories: [
        ...VESSEL_TYPE_COLORS.filter(([label]) =>
          ['Cargo', 'Tanker', 'Passenger', 'Fishing', 'Tug'].includes(label)
        ).map(([label, color]) => ({ label, range: '', color })),
        { label: 'Other / not yet reported', range: '', color: VESSEL_COLOR_FALLBACK },
      ],
    },
  };
}

/**
 * What a point lookup needs, per prediction layer id.
 *
 * Both prediction families ship as pre-coloured rasters, so a click on the
 * map has no value to read back out of the tile — the panel re-queries the
 * model at the clicked coordinate instead, and this says which model and
 * which slice to ask for. Built from the same arrays and id helpers as the
 * layers themselves so the two can't drift apart.
 */
export type PredictionPointSource =
  | { kind: 'habitat'; species: string; month: number; label: string }
  | { kind: 'hab'; horizon: number; label: string };

export const predictionPointSources: ReadonlyMap<string, PredictionPointSource> = new Map<
  string,
  PredictionPointSource
>([
  ...HABITAT_SPECIES.map(
    ({ key, label }): [string, PredictionPointSource] => [
      habitatLayerId(key),
      { kind: 'habitat', species: key, month: currentMonth(), label },
    ]
  ),
  ...HAB_HORIZONS.map(
    (horizon): [string, PredictionPointSource] => [
      bloomRiskLayerId(horizon),
      { kind: 'hab', horizon, label: `Bloom Risk (+${horizon}d)` },
    ]
  ),
]);

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
    // On by default. Previously every overlay was off except `reference-labels`,
    // so the map opened as a bare basemap and the platform's headline artifact
    // was hidden behind a panel a first-time viewer had no reason to open. SST
    // is the right default: full global coverage, immediately legible, and the
    // layer everything else is compared against.
    defaultVisible: true,
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
      'NASA EOSDIS GIBS / VIIRS NOAA-21 Ocean Color — 5-day rolling composite, most recent ' +
      'observation per pixel. Remaining blank ocean is cloud, not an orbital gap: the sensor ' +
      'cannot see through cloud, so persistently overcast water has no valid retrieval at all.',
    defaultOpacity: 1,
    defaultVisible: false,
    // VIIRS NOAA-21, not MODIS Aqua. Same reason the cloud-cover layer above
    // uses VIIRS: the 3060 km swath self-overlaps at the equator where MODIS's
    // 2330 km leaves gaps between orbits. Measured over the same 5-day window
    // on three z4 tiles, share of the tile carrying data:
    //
    //   tile      MODIS Aqua L2    VIIRS NOAA-21
    //   4/8/10        31.8%            73.2%
    //   4/9/10        21.2%            59.4%
    //   4/7/9         70.9%            96.7%
    //
    // MODIS left roughly two-thirds of the tropical Indian Ocean — the app's
    // home region — with no retrieval, and against the Abyss basemap's near
    // black ocean (#030f1e) those gaps read as a broken layer rather than as
    // missing data. Widening the MODIS window instead was measured and
    // rejected: 14 days only reached 45% on 4/8/10, for nearly triple the
    // tile requests, because the gaps there are persistent cloud rather than
    // orbital geometry.
    sources: gibsComposite(['VIIRS_NOAA21_Chlorophyll_a'], {
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
    // On by default alongside SST — wind is a stackable overlay, not part of
    // the exclusive `ocean` group, and the two together are the Windy-style
    // view this feature exists to provide. The motion is also what tells a
    // first-time viewer the map is live rather than a screenshot.
    defaultVisible: true,
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
  // Surface currents, on the same GPU particle engine as wind above — the only
  // currents-specific code is the field URL, the colour ramp and a visual
  // speed scale (see vectorField/currentsLayer.ts; currents run an order of
  // magnitude slower than wind and are invisible at wind's pace).
  //
  // Source is the *ocean physics* product — the same hourly dataset SST is
  // drawn from, `uo`/`vo` at ~0.494m — not the L4 wind blend. The two layers
  // answer different questions and routinely disagree in direction: wind
  // drives the surface, but the large-scale flow is set by rotation and
  // density, which is exactly why they are worth showing together.
  //
  // Off by default, unlike wind. Wind ships on because it plus SST is the
  // headline view; two particle systems running at once is a busier map than
  // a first-time viewer should be handed, and the layer costs a second global
  // texture download the moment it is switched on.
  {
    id: 'currents',
    name: 'Ocean Currents',
    category: 'flow',
    type: 'custom',
    attribution:
      'Copernicus Marine Service — GLOBAL_ANALYSISFORECAST_PHY_001_024, uo/vo (eastward and ' +
      'northward sea water velocity) at 0.494m depth, hourly, 0.083°. Particle direction is ' +
      'the direction the water flows toward (oceanographic convention) — the opposite of the ' +
      'wind layer, which is named for the direction wind blows from.',
    defaultOpacity: 0.9,
    defaultVisible: false,
    createLayer: (id) => createCurrentsParticleLayer(id, 0.9),
    legend: {
      type: 'gradient',
      unit: 'm/s',
      min: 0,
      max: 2,
      // Matches CURRENT_SPEED_COLOR_STOPS in vectorField/colorRamp.ts. Single
      // hue, dark to light — see that file for why it is not a second rainbow.
      stops: [
        { offset: 0, color: '#96601c' },
        { offset: 0.075, color: '#b87410' },
        { offset: 0.15, color: '#dc9418' },
        { offset: 0.3, color: '#f5b73c' },
        { offset: 0.5, color: '#ffd47a' },
        { offset: 0.75, color: '#ffeab8' },
        { offset: 1, color: '#fff6e0' },
      ],
    },
  },

  // Stokes drift — the wave-induced transport, beside the currents it is not.
  //
  // Worth its own layer rather than being summed into currents: what actually
  // carries a drifting hull, a slick or a larva is the *sum* of the two, and a
  // layer that only ever showed the sum could not answer which of them put it
  // there. They routinely disagree in direction, and in the trade-wind belts and
  // the Southern Ocean Stokes drift is a large fraction of the total — which the
  // currents layer alone does not show at all.
  {
    id: 'stokes-drift',
    name: 'Stokes Drift',
    category: 'flow',
    type: 'custom',
    attribution:
      'Copernicus Marine Service — GLOBAL_ANALYSISFORECAST_WAV_001_027, VSDX/VSDY (eastward ' +
      'and northward Stokes drift), 3-hourly, 0.083°. Wave-induced mass transport, NOT the ' +
      'current: a floating object moves with the sum of this and the ocean current layer. ' +
      'Direction is the direction the water is carried toward, matching the currents layer ' +
      'and opposite to the wind layer.',
    defaultOpacity: 0.9,
    defaultVisible: false,
    createLayer: (id) => createStokesParticleLayer(id, 0.9),
    legend: {
      type: 'gradient',
      unit: 'm/s',
      min: 0,
      max: 1,
      // Matches STOKES_DRIFT_COLOR_STOPS in vectorField/colorRamp.ts. Single
      // hue at ~269°, so it reads as a different *structure* from the amber
      // currents ramp rather than as a second palette to memorise.
      stops: [
        { offset: 0, color: '#7e4eb0' },
        { offset: 0.08, color: '#9260c6' },
        { offset: 0.15, color: '#a676d8' },
        { offset: 0.3, color: '#be94ea' },
        { offset: 0.5, color: '#d4b4f4' },
        { offset: 0.75, color: '#e8d4fa' },
        { offset: 1, color: '#f7f0ff' },
      ],
    },
  },

  // Currents below the surface, one layer per offered level.
  //
  // A different *product* from the surface layer, and necessarily so: the hourly
  // physics dataset carries one singleton surface level, so there is nothing
  // beneath it to draw. These come from the daily depth-resolved currents, which
  // is the trade the layer names — hourly at the surface, daily at depth.
  //
  // Six levels rather than the product's fifty: each is an independent
  // whole-globe fetch, and the interesting comparison is surface-against-depth,
  // not a continuous profile. The requested depth snaps to the nearest model
  // level and the meta reports which one answered (200 m resolves to 186.13 m).
  ...CURRENTS_DEPTH_LEVELS.map((depth) => ({
    id: currentsDepthLayerId(depth),
    name: `Currents at ${depth} m`,
    category: 'flow' as const,
    type: 'custom' as const,
    attribution:
      `Copernicus Marine Service — GLOBAL_ANALYSISFORECAST_PHY_001_024 daily depth-resolved ` +
      `currents (uo/vo), 0.083°, at the model level nearest ${depth} m. DAILY MEAN, unlike ` +
      `the hourly surface currents layer. Direction is the direction the water flows toward. ` +
      `A level that has not been opened before takes a few minutes to fetch the first time.`,
    defaultOpacity: 0.9,
    defaultVisible: false,
    createLayer: (id: string) => createCurrentsDepthParticleLayer(id, depth, 0.9),
    legend: {
      type: 'gradient' as const,
      unit: 'm/s',
      min: 0,
      max: 2,
      // Deliberately the surface layer's scale and ramp. Comparing one level
      // against another is the whole point of the control, and a legend that
      // rescaled per level would make that comparison meaningless.
      stops: [
        { offset: 0, color: '#96601c' },
        { offset: 0.075, color: '#b87410' },
        { offset: 0.15, color: '#dc9418' },
        { offset: 0.3, color: '#f5b73c' },
        { offset: 0.5, color: '#ffd47a' },
        { offset: 0.75, color: '#ffeab8' },
        { offset: 1, color: '#fff6e0' },
      ],
    },
  })),

  // The combined drift field — current + Stokes drift + wind leeway.
  //
  // The three fields above answer "what is the water doing"; this one answers
  // "where would something floating here end up going", which is the question
  // behind search and rescue, spill response and larval transport, and which
  // none of them answers alone. It exists as its own layer rather than
  // replacing them for the reason the Stokes layer already records: a layer
  // that only ever showed the sum could not say which term put the object
  // there, and the terms routinely disagree in direction.
  //
  // One layer per object, because the wind coefficient is a property of the
  // *object* rather than of the ocean — a swamped hull and an undrogued raft in
  // the same water take measurably different tracks. Switching object downloads
  // a different texture; the sum happens server-side.
  //
  // What this is NOT is a trajectory. Every particle advects against a single
  // snapshot, so it shows where the water is going now everywhere — not where
  // one object will be in 48 hours, which needs a time-indexed stack and an
  // uncertainty envelope. See TODO.md §7.
  ...DRIFT_PRESETS.map((preset) => ({
    id: driftLayerId(preset.key),
    name: preset.name,
    category: 'flow' as const,
    type: 'custom' as const,
    attribution:
      `Copernicus Marine Service — surface currents (uo/vo, hourly) + Stokes drift ` +
      `(VSDX/VSDY, 3-hourly) + ${(preset.alpha * 100).toFixed(1)}% of the L4 wind blend ` +
      `as leeway. INSTANTANEOUS DRIFT VELOCITY, not a trajectory: particles advect ` +
      `against one snapshot, so this is not a forecast of where an object will be. The ` +
      `leeway coefficient is approximate and carries no divergence angle — a real search ` +
      `plan needs an ensemble, not one vector. Direction is the direction the water ` +
      `carries toward.`,
    defaultOpacity: 0.9,
    defaultVisible: false,
    createLayer: (id: string) => createDriftParticleLayer(id, preset.alpha, 0.9),
    legend: {
      type: 'gradient' as const,
      unit: 'm/s',
      min: 0,
      // 2.5 rather than currents' 2.0: the terms add rather than averaging, so
      // a boundary current under a gale goes past where that ramp ends.
      max: 2.5,
      // Matches DRIFT_SPEED_COLOR_STOPS in vectorField/colorRamp.ts. Single hue
      // at 150°, the fourth *structure* rather than a fourth palette.
      stops: [
        { offset: 0, color: '#29ae6b' },
        { offset: 0.04, color: '#33cc80' },
        { offset: 0.1, color: '#60d299' },
        { offset: 0.2, color: '#8ed7b2' },
        { offset: 0.4, color: '#badecc' },
        { offset: 0.68, color: '#dceae3' },
        { offset: 1, color: '#f4f6f5' },
      ],
    },
  })),

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

  // --- Live vessel traffic ------------------------------------------
  // Replaces the two Global Fishing Watch 4Wings heatmap layers that used
  // to sit here (`shipping-routes` SAR presence and `ais-ships` AIS
  // presence). Those rendered aggregate 30-day density as PNGs, which by
  // construction has no per-vessel features to identify or hover — the
  // layer could show where ships generally go, but never which ship.
  // `live-vessels` below is individually-resolved AIS, so each point is a
  // named vessel you can interrogate. backend/services/gfw.py and its
  // /api/tiles/gfw route are left in place and now unused, so the density
  // view can be restored as its own layer if the wide-area context is
  // wanted back.

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
  // Full skill numbers, drivers and limitations live in the docs (/docs —
  // see the Results, Metrics and Limitations chapters); the attribution
  // strings here are the short version.
  ...habitatLayers(),
  ...bloomRiskLayers(),
  liveVesselLayer(),
  // Filed with the flow layers rather than with the AI ones — see the
  // descriptor. It sits here in source order only because it is the newest.
  eddyLayer(),
  // Filed with the reference layers: sampling effort is context about how the
  // ocean was observed, not a property of the water.
  ednaCoverageLayer(),
];
