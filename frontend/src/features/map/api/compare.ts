import { API_BASE_URL } from '../../../utils/apiBase';

/**
 * Two coordinates, aligned row by row.
 *
 * A view over the point brief rather than a second source for the same numbers,
 * which is why it lives under `/api/brief` on the server: same services, same
 * sections, same disclaimers. If these two ever disagreed about one coordinate,
 * the difference — the entire output of this feature — would be meaningless.
 */
export interface CompareDelta {
  value: number;
  unit: string;
  percent: number | null;
}

export interface CompareRow {
  label: string;
  a: string | null;
  b: string | null;
  /** Null when either side is not numeric, or when the units differ. A
   *  subtraction across mismatched units is the one output here that would be
   *  confidently wrong, so it is refused rather than approximated. */
  delta: CompareDelta | null;
  /** Set when only one point has this row. Kept rather than dropped: the
   *  asymmetry is often the most informative part of the comparison. */
  only_at: 'a' | 'b' | null;
}

export interface CompareForecastRow {
  label: string;
  unit: string;
  a_last_observed: number | null;
  b_last_observed: number | null;
  horizons: Record<string, { a: number | null; b: number | null; delta: number | null }>;
  only_at: 'a' | 'b' | null;
}

export interface CompareSection {
  key: string;
  title: string;
  available: boolean;
  a_available: boolean;
  b_available: boolean;
  a_unavailable_reason: string | null;
  b_unavailable_reason: string | null;
  note: string | null;
  rows: (CompareRow | CompareForecastRow)[];
}

export interface CompareResponse {
  a: { latitude: number; longitude: number };
  b: { latitude: number; longitude: number };
  generated_at: string;
  delta_direction: string;
  sections: CompareSection[];
  note: string;
}

export interface ComparePoint {
  lat: number;
  lon: number;
}

function url(path: string): URL {
  return API_BASE_URL ? new URL(path, API_BASE_URL) : new URL(path, window.location.origin);
}

export function isForecastRow(
  row: CompareRow | CompareForecastRow
): row is CompareForecastRow {
  return 'horizons' in row;
}

export async function fetchComparison(
  a: ComparePoint,
  b: ComparePoint,
  signal?: AbortSignal
): Promise<CompareResponse> {
  const target = url('/api/brief/compare');
  target.searchParams.set('lat_a', String(a.lat));
  target.searchParams.set('lon_a', String(a.lon));
  target.searchParams.set('lat_b', String(b.lat));
  target.searchParams.set('lon_b', String(b.lon));

  const response = await fetch(target, { signal });
  if (!response.ok) {
    const detail = await response
      .json()
      .then((body: { detail?: string }) => body.detail)
      .catch(() => undefined);
    throw new Error(detail ?? `Comparison request failed with status ${response.status}`);
  }
  return (await response.json()) as CompareResponse;
}
