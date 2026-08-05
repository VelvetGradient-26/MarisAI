/** Response shapes for `/api/dashboard/*`.
 *
 * These mirror `backend/services/dashboard/` exactly. The one contract worth
 * internalising: almost every item carries `available`, and when it is false
 * the value fields are null and `unavailable_reason` explains why. Nothing in
 * this dashboard substitutes a number for missing data, so components must
 * branch on `available` rather than falling back to `?? 0`.
 */

export interface KpiCard {
  key: string;
  label: string;
  value: number | string | null;
  unit: string | null;
  available: boolean;
  /**
   * Three-way, because "still fetching" and "failed" must not look alike.
   * On a cold start every Copernicus-backed card is `warming` for a minute
   * or so; rendering that as an error would be alarming and wrong.
   */
  status: 'ready' | 'warming' | 'unavailable';
  /** Typical first-fetch duration, for the progress indicator to animate against. */
  expected_warmup_seconds: number | null;
  source: string | null;
  observed_at: string | null;
  detail: string | null;
  /** How to read the figure — coverage, region, or the rule behind it. */
  scope: string | null;
  unavailable_reason: string | null;

  /** SST card only. */
  anomaly_c?: number | null;
  anomaly_baseline?: string | null;

  /** Ocean-state cards. */
  minimum?: number | null;
  maximum?: number | null;

  /** Heat-stress card. */
  ocean_fraction?: number;
  largest_regions?: HeatStressRegion[];

  /** Bleaching card. */
  max_dhw_c_weeks?: number;
  bleaching_likely_fraction?: number;
  alert_categories?: Record<string, { level: number; cells: number; fraction: number }>;

  /** Habitat card. */
  species?: string;
  species_label?: string;
  month?: number;
  roc_auc?: number | null;
  tss?: number | null;

  /**
   * Values observed since the server started — genuinely short or empty on a
   * cold start, which the card reports rather than drawing a flat line.
   */
  sparkline?: { t: string; v: number }[];
  trend?: {
    change: number;
    change_pct: number | null;
    direction: 'up' | 'down' | 'flat';
    window_start: string;
    window_end: string;
    points: number;
  } | null;
}

export interface HeatStressRegion {
  area_km2: number;
  cells: number;
  peak_hotspot_c: number;
  peak_anomaly_c: number | null;
  peak_dhw_c_weeks: number | null;
  peak_location: { latitude: number; longitude: number };
}

export interface SummaryResponse {
  cards: KpiCard[];
  available_count: number;
  history_note: string;
  generated_at: string;
}

export type AlertSeverity = 'critical' | 'warning' | 'advisory';

export interface OceanAlert {
  id: string;
  kind: string;
  title: string;
  severity: AlertSeverity;
  region: string;
  /** The rule that produced this alert — always shown, never decorative. */
  basis: string;
  observed_at: string | null;
  source: string;
  latitude: number | null;
  longitude: number | null;
  status: string;
  dhw_c_weeks?: number;
  alert_level?: number;
  area_km2?: number;
  peak_hotspot_c?: number;
  peak_wave_height_m?: number;
  p99_wave_height_m?: number;
  probability?: number;
  horizon_days?: number;
}

export interface AlertsResponse {
  alerts: OceanAlert[];
  counts: Record<AlertSeverity, number>;
  sources_unavailable: string[];
  generated_at: string;
  disclaimer: string;
}

export interface LiveEntry {
  kind: 'buoy' | 'satellite' | 'model';
  title: string;
  source: string;
  observed_at: string | null;
  age_seconds: number | null;
  available: boolean;
  unavailable_reason: string | null;

  station_id?: string;
  latitude?: number;
  longitude?: number;
  distance_km?: number | null;
  water_temperature_c?: number | null;
  wave_height_m?: number | null;
  wind_speed_ms?: number | null;
  wind_gust_ms?: number | null;
  pressure_hpa?: number | null;
  air_temperature_c?: number | null;
  relative_humidity_pct?: number | null;

  satellite?: string;
  product?: string;
  resolution?: string | null;
  cadence?: string | null;
  status?: string;
  coverage?: string;
  citation?: string;
  dataset?: string;
  depth_m?: number;
  fields?: string[];
}

export interface LiveResponse {
  entries: LiveEntry[];
  buoy_count: number;
  near: { latitude: number; longitude: number } | null;
  generated_at: string;
}

export interface SatelliteProduct {
  layer_id: string;
  satellite: string;
  product: string;
  title: string;
  latest_date: string | null;
  resolution: string | null;
  format: string | null;
  cadence: string | null;
  age_days: number | null;
  status: 'current' | 'delayed' | 'stale' | 'unknown';
}

export interface SatellitesResponse {
  products: SatelliteProduct[];
  meta: {
    source: string;
    source_url: string;
    fetched_at: string;
    product_count: number;
  };
}

export type ProviderHealth = 'healthy' | 'degraded' | 'down' | 'unknown';

export interface ProviderStatus {
  key: string;
  name: string;
  category: string;
  connected: boolean;
  health: ProviderHealth;
  latency_ms: number | null;
  /** When the cache last refreshed — what `health` is judged on. */
  last_sync: string | null;
  /**
   * The timestep the data describes, where that differs from the refresh
   * time. Informational: some products publish over a day behind real time,
   * and treating that as a connection problem is a false alarm.
   */
  data_timestamp?: string | null;
  records: number;
  notes: string | null;
  error: string | null;
}

export interface HealthResponse {
  providers: ProviderStatus[];
  summary: Record<ProviderHealth, number>;
  generated_at: string;
}

export interface TrendVariable {
  key: string;
  label: string;
  unit: string;
  available: boolean;
  unavailable_reason: string | null;
  coverage_start: string | null;
  /** Only these ranges have data — the UI must not offer the others. */
  supported_ranges: string[];
}

export interface TrendRange {
  label: string;
  days: number;
  resolution: 'hourly' | 'daily';
}

export interface TrendsCatalogResponse {
  variables: TrendVariable[];
  ranges: Record<string, TrendRange>;
}

export interface TrendPoint {
  t: string;
  v: number;
}

export interface TrendStatistics {
  count: number;
  min: number;
  max: number;
  mean: number;
  first: number;
  last: number;
  change: number;
  change_pct: number | null;
}

export interface TrendSeries {
  variable: string;
  label: string;
  unit: string;
  range: string;
  resolution: 'hourly' | 'daily';
  start: string;
  end: string;
  latitude: number;
  longitude: number;
  points: TrendPoint[];
  statistics: TrendStatistics | null;
  source: string;
  source_url: string;
  /** Present instead of data when this one series failed. */
  error?: string;
}

export interface MultiTrendsResponse {
  range: string;
  latitude: number;
  longitude: number;
  series: Record<string, TrendSeries>;
}
