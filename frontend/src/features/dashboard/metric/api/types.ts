/** Response shapes for `/api/v1/metrics/*` and `/api/v1/forecast/*`.
 *
 * Mirrors the backend contracts exactly. The recurring pattern worth noticing
 * is `available` + `unavailable_reason` on individual statistics and catalog
 * entries: this platform never substitutes a number for missing data, so the
 * types make the absent case explicit rather than optional-and-hope.
 */

/** A single point. `t` is epoch **seconds** — uPlot takes a numeric x axis. */
export interface SeriesPoint {
  t: number;
  v: number;
}

export interface MetricSeries {
  variable: string;
  label: string;
  unit: string;
  latitude: number;
  longitude: number;
  resolution: string;
  start: string;
  end: string;
  points: SeriesPoint[];
  /** Observations the provider returned, before decimation. */
  observation_count: number;
  /** Points actually sent, after the min/max envelope. */
  rendered_count: number;
  decimated: boolean;
  coverage_start: string | null;
  sources: string[];
  quality: Record<string, unknown>;
}

export interface Statistic {
  key: string;
  label: string;
  value: number | null;
  unit: string;
  available: boolean;
  unavailable_reason: string | null;
  detail: string | null;
}

export interface MetricStatistics {
  variable: string;
  label: string;
  unit: string;
  category: string;
  latitude: number;
  longitude: number;
  start: string;
  end: string;
  observation_count: number;
  statistics: Statistic[];
  coverage_start: string | null;
  sources: string[];
  quality: Record<string, unknown>;
}

export interface OceanStory {
  variable: string;
  label: string;
  unit: string;
  story: string;
  /**
   * How the text was produced. `generated` means a language model phrased
   * server-computed figures; `template` means it was rendered deterministically;
   * `template-after-verification-failed` means the model produced a number it
   * was not given and its output was discarded. The UI badges these differently
   * because a reader deserves to know which they are reading.
   */
  source: 'generated' | 'template' | 'template-after-verification-failed';
  /** The exact block of figures the narrative was allowed to draw from. */
  facts: string;
  forecast_included: boolean;
  generated_at: string;
}

// --- Forecasting -----------------------------------------------------------

export interface ConfidenceInterval {
  lower: number;
  upper: number;
  confidence_level: number;
  method: string;
  n_residuals: number;
}

export interface FeatureContribution {
  feature: string;
  label: string;
  value: number | null;
  contribution: number;
  direction: 'increases' | 'decreases';
}

export interface Forecast {
  variable: string;
  label: string;
  unit: string;
  latitude: number;
  longitude: number;
  forecast_horizon: number;
  target_time: string;
  prediction: number;
  confidence_interval: ConfidenceInterval;
  trend: string;
  trend_delta: number;
  last_observed: number | null;
  last_observed_time: string | null;
  top_features: FeatureContribution[];
  top_feature_labels: string[];
  model: string;
  model_version: string;
  trained_at: string | null;
  evaluation: {
    MAE: number | null;
    RMSE: number | null;
    MAPE: number | null;
    R2: number | null;
    directional_accuracy: number | null;
    skill_score: number | null;
    validation: string;
    training_rows: number | null;
  };
  history: { t: string; v: number }[];
  data_quality: Record<string, unknown>;
  sources: string[];
  notes: string[];
}

export interface BatchForecast {
  variable: string;
  latitude: number;
  longitude: number;
  /** Keyed by horizon as a string. A horizon with no model carries `error`. */
  forecasts: Record<string, Forecast | { horizon: number; error: string }>;
}

export interface CatalogVariable {
  key: string;
  code: string;
  label: string;
  unit: string;
  category: string;
  covariates: string[];
  configured_horizons: number[];
  trained_horizons: number[];
  circular: boolean;
  log_transform: boolean;
  available: boolean;
  unavailable_reason: string | null;
}

export interface ForecastCatalog {
  variables: CatalogVariable[];
  supported_horizons: number[];
  default_horizons: number[];
  model: string;
  validation: string;
}

export interface FeatureImportance {
  feature: string;
  label: string;
  importance: number;
}

export interface ModelDetail {
  variable: string;
  horizon: number;
  metadata: Record<string, unknown> & {
    trained_at?: string;
    training_rows?: number;
    training_points?: string[];
    model_type?: string;
    target_mode?: string;
  };
  metrics: {
    validation?: {
      metrics?: Record<string, number | null>;
      folds?: Record<string, unknown>[];
      diagnostics?: Record<string, unknown>;
    };
    feature_importance?: FeatureImportance[];
    baseline?: { available: boolean; reason?: string; metrics?: Record<string, number> };
  };
  feature_columns: string[];
}

/** A forecast entry that carries an error rather than a prediction. */
export function isForecastError(
  entry: Forecast | { horizon: number; error: string }
): entry is { horizon: number; error: string } {
  return 'error' in entry;
}
