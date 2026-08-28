import type { HoveredEdnaCell } from './hooks/useEdnaCoverage';

const WIDTH = 262;
const OFFSET = 16;

/**
 * What one sampled cell is, on hover.
 *
 * The header says "detections", never "species" or "found", and the footer
 * spends its whole line on the thing a reader will otherwise assume: that a
 * coloured cell means the cell was surveyed. It means at least one water sample
 * from somewhere inside it was sequenced — which at these cell sizes can be a
 * single bottle standing in for thousands of square kilometres.
 */
export function EdnaTooltip({ hovered }: { hovered: HoveredEdnaCell }) {
  const cell = hovered.properties;
  const records = Number(cell.records);
  const area = Number(cell.area_km2);

  const rows: Array<{ label: string; value: string }> = [
    { label: 'Detections', value: records.toLocaleString() },
    { label: 'Cell area', value: `${area.toLocaleString()} km²` },
    {
      label: 'Extent',
      value: `${Number(cell.south).toFixed(2)}° to ${Number(cell.north).toFixed(2)}°, ${Number(
        cell.west
      ).toFixed(2)}° to ${Number(cell.east).toFixed(2)}°`,
    },
  ];

  const flipX = hovered.x + WIDTH + OFFSET * 2 > window.innerWidth;
  const left = flipX ? hovered.x - WIDTH - OFFSET : hovered.x + OFFSET;
  const estimatedHeight = 150 + rows.length * 19;
  const top = Math.max(8, Math.min(hovered.y + OFFSET, window.innerHeight - estimatedHeight - 8));

  return (
    <div className="map-tooltip" style={{ left, top, width: WIDTH }} role="tooltip">
      <div className="map-tooltip__header">
        <span className="map-tooltip__name">eDNA sampling</span>
        <span className="map-tooltip__type">Molecular records in this cell</span>
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
        Detections, not sightings or individuals — one deeply sequenced water sample yields
        thousands. A coloured cell means something in it was sampled, not that the cell was
        surveyed.
      </p>
    </div>
  );
}
