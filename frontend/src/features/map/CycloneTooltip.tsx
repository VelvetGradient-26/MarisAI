import type { HoveredCyclone } from './hooks/useCyclones';

const WIDTH = 254;
const OFFSET = 16;

/**
 * What one active cyclone is, on hover — mirrors `EddyTooltip`'s shape.
 *
 * States plainly that the position is a last reported fix, not a live track:
 * GDACS updates on the warning centre's own bulletin cadence (typically 6h),
 * so the marker can lag a fast-moving storm by hours.
 */
export function CycloneTooltip({ hovered }: { hovered: HoveredCyclone }) {
  const cyclone = hovered.properties;

  const rows: Array<{ label: string; value: string }> = [
    { label: 'Category', value: cyclone.category ?? 'Unknown' },
    {
      label: 'Max wind',
      value: cyclone.max_wind_kmh != null ? `${Number(cyclone.max_wind_kmh).toFixed(0)} km/h` : 'Unknown',
    },
    { label: 'Alert level', value: cyclone.alert_level ?? 'Unknown' },
    {
      label: 'Affected',
      value: cyclone.affected_countries.length > 0 ? cyclone.affected_countries.join(', ') : 'Not reported',
    },
    {
      label: 'Position',
      value: `${Number(cyclone.latitude).toFixed(2)}°, ${Number(cyclone.longitude).toFixed(2)}°`,
    },
  ];

  const flipX = hovered.x + WIDTH + OFFSET * 2 > window.innerWidth;
  const left = flipX ? hovered.x - WIDTH - OFFSET : hovered.x + OFFSET;
  const estimatedHeight = 118 + rows.length * 19;
  const top = Math.max(8, Math.min(hovered.y + OFFSET, window.innerHeight - estimatedHeight - 8));

  return (
    <div className="map-tooltip" style={{ left, top, width: WIDTH }} role="tooltip">
      <div className="map-tooltip__header">
        <span className="map-tooltip__name">{cyclone.name}</span>
        <span className="map-tooltip__type">Active tropical cyclone</span>
      </div>

      <dl className="map-tooltip__rows">
        {rows.map((row) => (
          <div key={row.label} className="map-tooltip__row">
            <dt>{row.label}</dt>
            <dd>{row.value}</dd>
          </div>
        ))}
      </dl>

      <p className="map-tooltip__pending">
        Last reported position only, from GDACS — not a live track or the storm's forecast cone.
      </p>
    </div>
  );
}
