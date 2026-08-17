const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;

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

function url(path: string): string {
  return `${API_BASE_URL}${path}`;
}

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

export interface UpwellingCell {
  west: number;
  south: number;
  east: number;
  north: number;
  /** Positive is upwelling-favourable. The sign is the measurement. */
  index: number;
  favourable: boolean;
  confidence: number;
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
  limits: string[];
  cells: UpwellingCell[];
}

export async function fetchHeatwaveCells(signal?: AbortSignal): Promise<HeatwaveResponse> {
  const response = await fetch(url('/api/ocean/heatwaves/cells'), { signal });
  if (!response.ok) {
    throw new Error(`Marine heatwave detection unavailable (${response.status})`);
  }
  return (await response.json()) as HeatwaveResponse;
}

export async function fetchUpwellingCells(signal?: AbortSignal): Promise<UpwellingResponse> {
  const response = await fetch(url('/api/ocean/upwelling/cells'), { signal });
  if (!response.ok) {
    throw new Error(`Upwelling detection unavailable (${response.status})`);
  }
  return (await response.json()) as UpwellingResponse;
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
