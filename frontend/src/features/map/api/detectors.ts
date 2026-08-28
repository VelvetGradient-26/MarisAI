import { fetchJson } from '../../../utils/apiBase';

/**
 * The two cell-based detectors: marine heatwaves and coastal upwelling.
 *
 * Both return sparse rectangles rather than a full field, and both carry a
 * `coverage` block for the same reason the eDNA layer does — a blank map here
 * is a *result*, and without a stated denominator a reader arriving from SST
 * reads blankness as a failed load. Neither is a raster tile layer: the
 * interesting output is a few thousand cells, not 40,000, so GeoJSON is both
 * cheaper and clickable.
 */

export interface HeatwaveCell {
  west: number;
  south: number;
  east: number;
  north: number;
  category: 'moderate' | 'strong' | 'severe' | 'extreme';
  category_index: number;
  exceedance_c: number;
  run_days: number;
}

export interface HeatwaveResponse {
  timestamp: string;
  computed_at: string;
  method: string;
  min_duration_days: number;
  baseline: { start: number; end: number };
  window_days: number;
  categories: string[];
  coverage: {
    ocean_cells: number;
    cells_in_heatwave?: number;
    /** Null when no ocean fell inside the aggregate band — never 0. */
    heatwave_fraction: number | null;
    by_category?: Record<string, number>;
    latitude_band_deg?: [number, number];
    unavailable_reason?: string;
  };
  limits: string[];
  cells: HeatwaveCell[];
}

/**
 * How the water compares with the wind's claim, per cell.
 *
 * `sst_unavailable` is a fifth state rather than a falsy `corroborated`, and
 * that is the whole point of the field: a coast OISST does not cover is neither
 * confirmed nor refuted, and collapsing it into "not corroborated" would report
 * a gap in coverage as a finding about the ocean.
 */
export type UpwellingCorroboration =
  | 'confirmed_below_p10'
  | 'cool_anomaly'
  | 'wind_only'
  | 'not_applicable'
  | 'sst_unavailable';

export interface UpwellingCell {
  west: number;
  south: number;
  east: number;
  north: number;
  /** Positive is upwelling-favourable. The sign is the measurement. */
  index: number;
  favourable: boolean;
  confidence: number;
  /** Null where no SST covers the cell — never 0, which would mean average water. */
  sst_anomaly_c: number | null;
  corroboration: UpwellingCorroboration;
}

export interface UpwellingResponse {
  timestamp: string;
  computed_at: string;
  method: string;
  unit: string;
  sign_convention: string;
  coverage: {
    coastal_cells: number;
    upwelling_favourable_cells?: number;
    downwelling_favourable_cells?: number;
    favourable_fraction?: number;
    max_index?: number;
    unavailable_reason?: string;
  };
  /**
   * The SST half, deliberately outside `coverage`. `coverage` describes the
   * wind-derived index alone and stays readable without this block, because
   * "the wind is favourable" and "the wind is favourable and the water is cool
   * for the season" are different findings.
   */
  corroboration: {
    available: boolean;
    unavailable_reason?: string;
    source: string;
    cool_anomaly_threshold_c: number;
    states: UpwellingCorroboration[];
    /** The SST observation's own day, which lags the wind by a week or more. */
    sst_timestamp?: string;
    lag_hours?: number;
    baseline?: { start: number; end: number } | null;
    favourable_cells?: number;
    /** The denominator. Cells outside SST coverage are excluded, not refuted. */
    favourable_cells_with_sst?: number;
    corroborated_cells?: number;
    below_p10_cells?: number;
    corroborated_fraction?: number | null;
    /**
     * The base rate: the same cool fraction over *downwelling*-favourable
     * coasts, where cool water is not expected. Measured 2026-08-17 the two
     * were 19.9% and 17.2%, so the corroborated fraction alone reads as a
     * confirmed mechanism when it is a weak coincidence. Always render them
     * together.
     */
    control_cells?: number;
    control_cool_fraction?: number | null;
    note?: string;
  };
  limits: string[];
  cells: UpwellingCell[];
}

export async function fetchHeatwaveCells(signal?: AbortSignal): Promise<HeatwaveResponse> {
  return fetchJson<HeatwaveResponse>(
    '/api/ocean/heatwaves/cells',
    { signal },
    (status) => `Marine heatwave detection unavailable (${status})`
  );
}

export async function fetchUpwellingCells(signal?: AbortSignal): Promise<UpwellingResponse> {
  return fetchJson<UpwellingResponse>(
    '/api/ocean/upwelling/cells',
    { signal },
    (status) => `Upwelling detection unavailable (${status})`
  );
}

/**
 * Cells as rectangles.
 *
 * The backend already sends cell *edges* rather than centres — a polygon drawn
 * from centre to centre sits half a step off the basemap's coastline — so this
 * only has to close the ring.
 */
function toPolygon(cell: { west: number; south: number; east: number; north: number }) {
  return {
    type: 'Polygon' as const,
    coordinates: [
      [
        [cell.west, cell.south],
        [cell.east, cell.south],
        [cell.east, cell.north],
        [cell.west, cell.north],
        [cell.west, cell.south],
      ],
    ],
  };
}

export function heatwaveCellsToGeoJson(cells: HeatwaveCell[]): GeoJSON.FeatureCollection {
  return {
    type: 'FeatureCollection',
    features: cells.map((cell) => ({
      type: 'Feature',
      geometry: toPolygon(cell),
      properties: { ...cell },
    })),
  };
}

export function upwellingCellsToGeoJson(cells: UpwellingCell[]): GeoJSON.FeatureCollection {
  return {
    type: 'FeatureCollection',
    features: cells.map((cell) => ({
      type: 'Feature',
      geometry: toPolygon(cell),
      properties: { ...cell },
    })),
  };
}

/**
 * Payload-level converters.
 *
 * Module-level rather than lambdas at the call site, and that is not style:
 * `useDetectorCells` lists its converter in the effect's dependency array, so
 * an inline arrow would be a fresh identity on every render and the effect
 * would tear down and refetch in a loop.
 */
export function heatwaveResponseToGeoJson(payload: HeatwaveResponse): GeoJSON.FeatureCollection {
  return heatwaveCellsToGeoJson(payload.cells);
}

export function upwellingResponseToGeoJson(payload: UpwellingResponse): GeoJSON.FeatureCollection {
  return upwellingCellsToGeoJson(payload.cells);
}
