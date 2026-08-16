const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;

/**
 * Where the ocean has been sampled for environmental DNA.
 *
 * Unlike every other layer on this map, this one is not a field. SST, currents
 * and the forecast grids are defined everywhere; this is defined almost
 * nowhere — about 1,500 geohash cells worldwide, covering 27,286 km² of a
 * 362-million-km² ocean. The empty planet is the finding, not a loading state,
 * which is why `EdnaCoverageStatus` always says how little is drawn.
 */
export interface EdnaCell {
  west: number;
  south: number;
  east: number;
  north: number;
  records: number;
  area_km2: number;
  records_per_1000_km2: number | null;
}

export interface EdnaCoverageResponse {
  precision: number;
  cell_lon_deg: number;
  cell_lat_deg: number;
  bbox: number[] | null;
  occupied_cells: number;
  records: number;
  sampled_area_km2: number;
  /** Null for a bbox request, which has no honest whole-ocean fraction. */
  sampled_fraction_of_ocean: number | null;
  ocean_area_km2: number;
  /**
   * The coverage figure to quote, always measured on the finest grid rather
   * than on whatever is being drawn.
   *
   * Cell size decides this number more than the data does — the same records
   * cover 23% of the ocean at precision 2 and 0.0075% at precision 5. Since the
   * map draws a coarser grid when zoomed out, reading the fraction off the
   * displayed level would put the most flattering number in the default view
   * and shrink it as the reader looked closer.
   */
  reference_coverage: {
    precision: number;
    occupied_cells: number;
    sampled_area_km2: number;
    sampled_fraction_of_ocean: number;
  } | null;
  scale: { type: string; min_records: number; max_records: number };
  detection_note: string;
  absence_note: string;
  counting_note: string;
  limits: string[];
  cells: EdnaCell[];
  source: string;
  source_url: string;
  computed_at: string;
}

function url(path: string): string {
  return `${API_BASE_URL}${path}`;
}

/**
 * Grid precision for a zoom level.
 *
 * The whole planet is 348 KB at the finest level, so there is deliberately no
 * viewport filtering here — the layer fetches globally and the backend caches
 * one payload per precision for 24 hours. Sending a bbox would make every pan a
 * new cache key for data that would fit in memory five times over.
 */
export function precisionForZoom(zoom: number): number {
  if (zoom < 2) return 2;
  if (zoom < 5) return 3;
  if (zoom < 8) return 4;
  return 5;
}

export async function fetchEdnaCoverage(
  precision: number,
  signal?: AbortSignal
): Promise<EdnaCoverageResponse> {
  const params = new URLSearchParams({ precision: String(precision) });
  const response = await fetch(url(`/api/ocean/edna/coverage?${params}`), { signal });
  if (!response.ok) {
    throw new Error(`eDNA coverage unavailable (${response.status})`);
  }
  return (await response.json()) as EdnaCoverageResponse;
}

/**
 * Cells as polygons, carrying `log_records` for the paint ramp.
 *
 * The logarithm is computed here rather than in a MapLibre expression so the
 * ramp's domain can be a fixed one — see `layerRegistry`'s `ednaCoverageLayer`
 * for why a fixed domain matters. Normalising against the response's own
 * maximum was the alternative and was rejected: the brightest colour would then
 * mean "the busiest cell in whatever is loaded", so the same cell would change
 * colour on zoom and the legend could not name a number at all.
 */
export function ednaCoverageToGeoJson(cells: EdnaCell[]): GeoJSON.FeatureCollection {
  return {
    type: 'FeatureCollection',
    features: cells.map((cell) => ({
      type: 'Feature',
      geometry: {
        type: 'Polygon',
        coordinates: [
          [
            [cell.west, cell.south],
            [cell.east, cell.south],
            [cell.east, cell.north],
            [cell.west, cell.north],
            [cell.west, cell.south],
          ],
        ],
      },
      properties: {
        ...cell,
        log_records: Math.log10(Math.max(cell.records, 1)),
      },
    })),
  };
}
