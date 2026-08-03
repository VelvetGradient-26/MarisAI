import type { HoveredVessel } from './hooks/useLiveVessels';
import type { VesselProperties } from './api/vessels';

/** Tooltip size, used to flip it away from the viewport edge rather than
 * letting it clip. */
const WIDTH = 268;
const OFFSET = 16;

/**
 * Compass point for a bearing. AIS gives degrees, which is precise but slow
 * to read — "312° NW" is faster to parse at a glance than "312°" alone.
 */
function compass(degrees: number): string {
  const points = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
                  'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'];
  return points[Math.round(degrees / 22.5) % 16];
}

/** AIS speed is in knots; km/h alongside it saves the reader the conversion. */
function formatSpeed(knots: number): string {
  return `${knots.toFixed(1)} kn · ${(knots * 1.852).toFixed(1)} km/h`;
}

function formatBearing(degrees: number): string {
  return `${degrees.toFixed(0)}° ${compass(degrees)}`;
}

interface Row {
  label: string;
  value: string;
}

function buildRows(v: VesselProperties): Row[] {
  const rows: Row[] = [];

  // Motion first: it is what changes, and what the glow on the map is
  // showing. A vessel that is stopped says so rather than showing "0.0 kn".
  if (v.sog !== undefined) {
    rows.push({ label: 'Speed', value: v.sog < 0.2 ? 'Stopped' : formatSpeed(v.sog) });
  }
  if (v.cog !== undefined) rows.push({ label: 'Course', value: formatBearing(v.cog) });
  // Only worth showing when it differs from course — otherwise it is noise.
  if (v.heading !== undefined && (v.cog === undefined || Math.abs(v.heading - v.cog) > 5)) {
    rows.push({ label: 'Heading', value: formatBearing(v.heading) });
  }
  if (v.nav_status) rows.push({ label: 'Status', value: v.nav_status });

  if (v.destination) rows.push({ label: 'Destination', value: v.destination });
  if (v.eta) rows.push({ label: 'ETA', value: v.eta });

  rows.push({ label: 'MMSI', value: String(v.mmsi) });
  if (v.imo) rows.push({ label: 'IMO', value: String(v.imo) });
  if (v.call_sign) rows.push({ label: 'Call sign', value: v.call_sign });

  if (v.length_m && v.beam_m) {
    rows.push({ label: 'Size', value: `${v.length_m.toFixed(0)} × ${v.beam_m.toFixed(0)} m` });
  } else if (v.length_m) {
    rows.push({ label: 'Length', value: `${v.length_m.toFixed(0)} m` });
  }
  if (v.draught_m) rows.push({ label: 'Draught', value: `${v.draught_m.toFixed(1)} m` });

  return rows;
}

export function VesselTooltip({ hovered }: { hovered: HoveredVessel }) {
  const v = hovered.properties;
  const rows = buildRows(v);

  // Flip left / upward near the edges so the tooltip stays fully on screen.
  const flipX = hovered.x + WIDTH + OFFSET * 2 > window.innerWidth;
  const left = flipX ? hovered.x - WIDTH - OFFSET : hovered.x + OFFSET;
  const estimatedHeight = 96 + rows.length * 19;
  const top = Math.max(8, Math.min(hovered.y + OFFSET, window.innerHeight - estimatedHeight - 8));

  return (
    <div className="vessel-tooltip" style={{ left, top, width: WIDTH }} role="tooltip">
      <div className="vessel-tooltip__header">
        <span className="vessel-tooltip__name">{v.name ?? `MMSI ${v.mmsi}`}</span>
        {v.ship_type && <span className="vessel-tooltip__type">{v.ship_type}</span>}
      </div>

      <dl className="vessel-tooltip__rows">
        {rows.map((row) => (
          <div key={row.label} className="vessel-tooltip__row">
            <dt>{row.label}</dt>
            <dd>{row.value}</dd>
          </div>
        ))}
      </dl>

      {/* Static data lags position by up to ~6 minutes, so a vessel with no
          name yet is normal and worth explaining rather than looking broken. */}
      {!v.name && (
        <p className="vessel-tooltip__pending">
          Identity not broadcast yet — AIS static data follows position by up to ~6 min.
        </p>
      )}

      {v.last_report && (
        <p className="vessel-tooltip__footer">Last broadcast {v.last_report.slice(11, 19)} UTC</p>
      )}
    </div>
  );
}
