import type { HoveredCell } from './hooks/useDetectorCells';
import type { HeatwaveCell } from './api/detectors';

const WIDTH = 254;
const OFFSET = 16;

/**
 * What one heatwave cell is, on hover. `services/heatwaves.py::cells`
 * already merges tracked onset/duration/intensity into every cell — this
 * is the first place the frontend actually reads that `tracked` field
 * rather than silently dropping it.
 *
 * `tracked` can be `null` (tracker never loaded) or `in_heatwave: false`
 * (a cold-start race — this snapshot says category > 0, the tracker hasn't
 * caught up yet) even though the cell is in this list at all; both are
 * shown as real, distinct states rather than silently falling back to the
 * snapshot's own censored `run_days`.
 */
export function HeatwaveTooltip({ hovered }: { hovered: HoveredCell<HeatwaveCell> }) {
  const cell = hovered.properties;
  const tracked = cell.tracked;

  const rows: Array<{ label: string; value: string }> = [
    { label: 'Category', value: `${cell.category} (+${cell.exceedance_c.toFixed(1)}°C)` },
  ];

  if (tracked?.in_heatwave) {
    rows.push({
      label: 'Day',
      value: `${tracked.run_days}${tracked.possibly_started_earlier ? '+' : ''} since ${tracked.onset_date}`,
    });
    if (tracked.peak_category) {
      rows.push({ label: 'Peak so far', value: tracked.peak_category });
    }
    if (tracked.cumulative_intensity_c_days != null) {
      rows.push({
        label: 'Cumulative intensity',
        value: `${tracked.cumulative_intensity_c_days.toFixed(1)} °C·days`,
      });
    }
  }

  const flipX = hovered.x + WIDTH + OFFSET * 2 > window.innerWidth;
  const left = flipX ? hovered.x - WIDTH - OFFSET : hovered.x + OFFSET;
  const estimatedHeight = 100 + rows.length * 19;
  const top = Math.max(8, Math.min(hovered.y + OFFSET, window.innerHeight - estimatedHeight - 8));

  return (
    <div className="map-tooltip" style={{ left, top, width: WIDTH }} role="tooltip">
      <div className="map-tooltip__header">
        <span className="map-tooltip__name">Marine heatwave</span>
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
        {tracked?.in_heatwave
          ? tracked.possibly_started_earlier
            ? 'Onset is when tracking itself started — this run may be older than that.'
            : 'Onset date and duration held across refreshes; the field above is only this snapshot.'
          : 'Not yet confirmed by the tracker — this snapshot alone shows heat here.'}
      </p>
    </div>
  );
}
