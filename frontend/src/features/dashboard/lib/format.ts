/** Display formatting for the dashboard.
 *
 * `formatAge` and `formatWhen` deliberately go through the app's timezone
 * store (`utils/formatTime.ts`) rather than a bare `toLocaleString()`, per the
 * project convention that all timestamp display honours the user's chosen
 * IANA zone.
 */

/** Relative age, e.g. "4m ago". Null becomes an em dash, never "NaN". */
export function formatAge(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return '—';
  if (seconds < 45) return 'just now';
  const minutes = seconds / 60;
  if (minutes < 60) return `${Math.round(minutes)}m ago`;
  const hours = minutes / 60;
  if (hours < 24) return `${Math.round(hours)}h ago`;
  const days = hours / 24;
  if (days < 30) return `${Math.round(days)}d ago`;
  const months = days / 30;
  if (months < 12) return `${Math.round(months)}mo ago`;
  return `${(days / 365).toFixed(1)}y ago`;
}

/** A measurement, with its unit, at sensible precision for its magnitude. */
export function formatValue(
  value: number | string | null | undefined,
  unit?: string | null,
  decimals?: number
): string {
  if (value == null) return '—';
  if (typeof value === 'string') return unit ? `${value} ${unit}` : value;
  if (!Number.isFinite(value)) return '—';

  const places =
    decimals ??
    // Small quantities (chlorophyll at 0.26 mg/m³) need decimals that a
    // count of heat-stress regions does not.
    (Math.abs(value) >= 1000 ? 0 : Math.abs(value) >= 100 ? 1 : Math.abs(value) >= 1 ? 2 : 3);

  const text = value.toLocaleString(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: places,
  });
  return unit ? `${text} ${unit}` : text;
}

export function formatCompactNumber(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—';
  return value.toLocaleString(undefined, { notation: 'compact', maximumFractionDigits: 1 });
}

/** Signed, for anomalies and deltas — the sign is the point. */
export function formatSigned(
  value: number | null | undefined,
  unit?: string | null,
  decimals = 2
): string {
  if (value == null || !Number.isFinite(value)) return '—';
  const sign = value > 0 ? '+' : '';
  return `${sign}${value.toFixed(decimals)}${unit ? ` ${unit}` : ''}`;
}

export function formatCoordinates(latitude: number, longitude: number): string {
  const ns = latitude >= 0 ? 'N' : 'S';
  const ew = longitude >= 0 ? 'E' : 'W';
  return `${Math.abs(latitude).toFixed(2)}°${ns}, ${Math.abs(longitude).toFixed(2)}°${ew}`;
}

/** Axis tick label. Hourly series need the hour; daily ones do not.
 *
 * `withYear` matters on the multi-year ranges: "4 Aug" appears ten times in a
 * 10-year series, so a tooltip without the year cannot say which one it is.
 */
export function formatAxisTime(
  iso: string,
  resolution: 'hourly' | 'daily',
  withYear = false
): string {
  const date = new Date(resolution === 'daily' ? `${iso}T00:00:00Z` : iso);
  if (Number.isNaN(date.getTime())) return iso;
  if (resolution === 'daily') {
    return date.toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
      ...(withYear ? { year: 'numeric' } : {}),
      timeZone: 'UTC',
    });
  }
  return date.toLocaleString(undefined, {
    ...(withYear ? { month: 'short', day: 'numeric' } : {}),
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'UTC',
  });
}

/** Ranges long enough that a date without its year is ambiguous. */
export function rangeNeedsYear(range: string): boolean {
  return range === '1y' || range === '5y' || range === '10y';
}

export const SEVERITY_STYLES = {
  critical: {
    label: 'Critical',
    text: 'text-[color:var(--color-alert-critical)]',
    border: 'border-[color:color-mix(in_oklab,var(--color-alert-critical)_45%,transparent)]',
    bg: 'bg-[color:color-mix(in_oklab,var(--color-alert-critical)_12%,transparent)]',
    dot: 'bg-[color:var(--color-alert-critical)]',
  },
  warning: {
    label: 'Warning',
    text: 'text-[color:var(--color-alert-warning)]',
    border: 'border-[color:color-mix(in_oklab,var(--color-alert-warning)_45%,transparent)]',
    bg: 'bg-[color:color-mix(in_oklab,var(--color-alert-warning)_12%,transparent)]',
    dot: 'bg-[color:var(--color-alert-warning)]',
  },
  advisory: {
    label: 'Advisory',
    text: 'text-[color:var(--color-alert-advisory)]',
    border: 'border-[color:color-mix(in_oklab,var(--color-alert-advisory)_40%,transparent)]',
    bg: 'bg-[color:color-mix(in_oklab,var(--color-alert-advisory)_10%,transparent)]',
    dot: 'bg-[color:var(--color-alert-advisory)]',
  },
} as const;

export const HEALTH_STYLES = {
  healthy: { label: 'Healthy', dot: 'bg-[color:var(--color-emerald-400)]', text: 'text-[color:var(--color-emerald-400)]' },
  degraded: { label: 'Degraded', dot: 'bg-[color:var(--color-alert-warning)]', text: 'text-[color:var(--color-alert-warning)]' },
  down: { label: 'Down', dot: 'bg-[color:var(--color-alert-critical)]', text: 'text-[color:var(--color-alert-critical)]' },
  unknown: {
    label: 'Unknown',
    dot: 'bg-[color:var(--oid-text-faint)]',
    text: 'text-[color:var(--oid-text-muted)]',
  },
} as const;
