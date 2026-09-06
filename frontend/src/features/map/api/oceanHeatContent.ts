import type { CursorCoordinates } from '../types';
import { fetchJson } from '../../../utils/apiBase';

/**
 * Ocean heat content, 0-N m of integrated water-column heat — a regional grid
 * built offline (`scripts/build_ocean_heat_content_grid.py`), not a live
 * field. See `backend/services/ocean_heat_content_field.py`'s own docstring
 * for why this is regional (55-95 degE, 5S-25N) rather than global.
 *
 * `cells` reuses the exact same shape as `detectors.ts`'s heatwave/upwelling
 * responses (`services/ocean_heat_content_field.py::cells` says so directly),
 * which is why this file mirrors `detectors.ts` rather than inventing a new
 * shape.
 */

export const OCEAN_HEAT_CONTENT_LAYER_ID = 'ocean-heat-content';

/** 0-700m — the reference depth used elsewhere in this codebase (dashboard
 *  charts, `ohc_key()`) as *the* ocean-heat-content number when only one is
 *  shown. It is also, empirically, the layer with the most spatial contrast
 *  in this region: a live probe of `/cells?depth_m=700` found values spread
 *  0.5-46 GJ/m^2 (10th-100th percentile 35-46), where the 50m and 100m layers
 *  are nearly flat across the same region (5.0-5.9 and 9.1-11.1
 *  respectively) — a map layer at 50m or 100m would render as almost one
 *  flat colour. The shallower layers are still the operationally relevant
 *  ones for cyclone intensification, marine heatwaves and mixed-layer
 *  biology (see `copernicus_series.py`'s own `OHC_LAYERS_M` comment) — that's
 *  why the point card below shows all four depths, not just this one.
 */
export const OCEAN_HEAT_CONTENT_MAP_DEPTH_M = 700;

export interface OceanHeatContentCell {
  west: number;
  south: number;
  east: number;
  north: number;
  value: number;
}

export interface OceanHeatContentCellsResponse {
  timestamp: string;
  built_at: string;
  source: string;
  region: { west: number; south: number; east: number; north: number };
  layers_m: number[];
  unit: string;
  note: string;
  layer_m: number;
  cells: OceanHeatContentCell[];
}

/**
 * Every layer at one point. The reference depth (700m) keeps its bare
 * `ocean_heat_content` key rather than `ocean_heat_content_700m` — matching
 * `ohc_key()`'s own stated reason: renaming it would break every stored
 * chart selection and dashboard reference for no gain.
 */
export interface OceanHeatContentPointResponse {
  available: boolean;
  unavailable_reason?: string;
  latitude?: number;
  longitude?: number;
  timestamp?: string;
  unit?: string;
  ocean_heat_content_50m?: number | null;
  ocean_heat_content_100m?: number | null;
  ocean_heat_content_200m?: number | null;
  ocean_heat_content?: number | null;
}

export async function fetchOceanHeatContentCells(
  depthM: number = OCEAN_HEAT_CONTENT_MAP_DEPTH_M,
  signal?: AbortSignal
): Promise<OceanHeatContentCellsResponse> {
  return fetchJson<OceanHeatContentCellsResponse>(
    `/api/ocean/ocean-heat-content/cells?depth_m=${depthM}`,
    { signal },
    (status) => `Ocean heat content unavailable (${status})`
  );
}

/** `useDetectorCells`'s `fetcher` option is called as `fetcher(signal)` —
 *  exactly one argument — so a two-argument function with a default can't be
 *  passed directly (the hook's `signal` would bind to `depthM`). This is the
 *  stable, module-level, single-argument function the hook actually needs. */
export async function fetchOceanHeatContentMapCells(
  signal?: AbortSignal
): Promise<OceanHeatContentCellsResponse> {
  return fetchOceanHeatContentCells(OCEAN_HEAT_CONTENT_MAP_DEPTH_M, signal);
}

export async function fetchOceanHeatContentPoint(
  location: CursorCoordinates,
  signal?: AbortSignal
): Promise<OceanHeatContentPointResponse> {
  const params = new URLSearchParams({
    lat: String(location.lat),
    lon: String(location.lng),
  });
  return fetchJson<OceanHeatContentPointResponse>(
    `/api/ocean/ocean-heat-content/point?${params.toString()}`,
    { signal },
    (status) => `Ocean heat content point request failed (${status})`
  );
}

/** Cell edges → a closed polygon ring. Mirrors `detectors.ts`'s `toPolygon` —
 *  the backend already sends edges, not centres, for the same coastline-
 *  alignment reason documented there. */
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

export function oceanHeatContentCellsToGeoJson(
  cells: OceanHeatContentCell[]
): GeoJSON.FeatureCollection {
  return {
    type: 'FeatureCollection',
    features: cells.map((cell) => ({
      type: 'Feature',
      geometry: toPolygon(cell),
      properties: { ...cell },
    })),
  };
}

/** Module-level, not a lambda at the call site — `useDetectorCells` lists
 *  this in its effect's dependency array, so an inline arrow would be a
 *  fresh identity every render and the effect would refetch in a loop. */
export function oceanHeatContentResponseToGeoJson(
  payload: OceanHeatContentCellsResponse
): GeoJSON.FeatureCollection {
  return oceanHeatContentCellsToGeoJson(payload.cells);
}
