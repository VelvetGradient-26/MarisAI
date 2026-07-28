/**
 * Shared timezone-aware time formatting — every timestamp shown anywhere in
 * the app should go through one of these rather than a bare
 * `Date.prototype.toLocaleString()`/hardcoded `timeZone: 'UTC'`, so the
 * global timezone preference (see store/timezoneStore.ts) actually reaches
 * every display.
 */

function toValidDate(value: string | Date): Date | null {
  const date = typeof value === 'string' ? new Date(value) : value;
  return Number.isNaN(date.getTime()) ? null : date;
}

/** HH:MM:SS, 24-hour, in the given IANA timezone. */
export function formatClockTime(date: Date, timezone: string): string {
  return new Intl.DateTimeFormat('en-GB', {
    timeZone: timezone,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(date);
}

/** "MON DD, YYYY", uppercased, in the given IANA timezone. */
export function formatClockDate(date: Date, timezone: string): string {
  return new Intl.DateTimeFormat('en-US', {
    timeZone: timezone,
    month: 'short',
    day: '2-digit',
    year: 'numeric',
  })
    .format(date)
    .toUpperCase();
}

/** "HH:MM" — short form for inline "fetched at" / "updated" labels. */
export function formatShortTime(value: string, timezone: string): string {
  const date = toValidDate(value);
  if (!date) return value;
  return new Intl.DateTimeFormat('en-GB', {
    timeZone: timezone,
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date);
}

/** Full "Mon DD, YYYY, HH:MM ZONE" — replaces bare `toLocaleString()` calls. */
export function formatFullDateTime(value: string, timezone: string): string {
  const date = toValidDate(value);
  if (!date) return value;
  return new Intl.DateTimeFormat('en-US', {
    timeZone: timezone,
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    timeZoneName: 'short',
  }).format(date);
}

/** "YYYY-MM-DD HH:MM ZONE" — replaces the legends' hand-built ISO-slice +
 * hardcoded "UTC" label. */
export function formatCompactDateTime(value: string, timezone: string): string {
  const date = toValidDate(value);
  if (!date) return value;
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: timezone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    timeZoneName: 'short',
  }).formatToParts(date);

  const get = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((p) => p.type === type)?.value ?? '';
  const zoneName = get('timeZoneName');
  return `${get('year')}-${get('month')}-${get('day')} ${get('hour')}:${get('minute')} ${zoneName}`;
}
