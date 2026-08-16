import type { HoveredEddy } from './hooks/useEddies';

const WIDTH = 254;
const OFFSET = 16;

/**
 * What one detected eddy is, on hover.
 *
 * Deliberately says what the ring *is not*: the radius is the equivalent
 * radius of the detected core, and the feature has no age because nothing here
 * is tracked between refreshes. Both are the kind of thing a reader otherwise
 * assumes in the generous direction.
 */
export function EddyTooltip({ hovered }: { hovered: HoveredEddy }) {
  const eddy = hovered.properties;
  const rotation =
    eddy.polarity === 'cyclonic'
      ? 'Cyclonic — turning with the planet'
      : 'Anticyclonic — turning against it';

  const rows: Array<{ label: string; value: string }> = [
    { label: 'Radius', value: `${Number(eddy.radius_km).toFixed(0)} km (equivalent)` },
    { label: 'Peak speed', value: `${Number(eddy.max_speed_ms).toFixed(2)} m/s` },
    { label: 'Mean speed', value: `${Number(eddy.mean_speed_ms).toFixed(2)} m/s` },
    { label: 'Vorticity', value: `${Number(eddy.vorticity_per_s).toExponential(2)} s⁻¹` },
    {
      label: 'Position',
      value: `${Number(eddy.latitude).toFixed(2)}°, ${Number(eddy.longitude).toFixed(2)}°`,
    },
  ];

  const flipX = hovered.x + WIDTH + OFFSET * 2 > window.innerWidth;
  const left = flipX ? hovered.x - WIDTH - OFFSET : hovered.x + OFFSET;
  const estimatedHeight = 118 + rows.length * 19;
  const top = Math.max(8, Math.min(hovered.y + OFFSET, window.innerHeight - estimatedHeight - 8));

  return (
    <div className="map-tooltip" style={{ left, top, width: WIDTH }} role="tooltip">
      <div className="map-tooltip__header">
        <span className="map-tooltip__name">Detected eddy</span>
        <span className="map-tooltip__type">{rotation}</span>
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
        Detection only — no age or track. The ring is the equivalent radius of the rotating
        core, not the feature’s outline.
      </p>
    </div>
  );
}
