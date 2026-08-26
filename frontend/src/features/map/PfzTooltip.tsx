import type { HoveredPfzZone } from './hooks/usePfzZones';

const WIDTH = 254;
const OFFSET = 16;

const SCORE_LABEL: Record<number, string> = {
  2: 'Both chlorophyll and SST favourable',
  1: 'One of chlorophyll or SST favourable',
  0: 'Neither favourable',
};

/** What one candidate screening cell is, on hover — mirrors `EddyTooltip`. */
export function PfzTooltip({ hovered }: { hovered: HoveredPfzZone }) {
  const zone = hovered.properties;

  const rows: Array<{ label: string; value: string }> = [
    { label: 'Chlorophyll', value: `${Number(zone.chlorophyll_mg_m3).toFixed(3)} mg/m³` },
    { label: 'SST', value: `${Number(zone.sst_c).toFixed(1)} °C` },
    {
      label: 'Position',
      value: `${Number(zone.latitude).toFixed(2)}°, ${Number(zone.longitude).toFixed(2)}°`,
    },
  ];

  const flipX = hovered.x + WIDTH + OFFSET * 2 > window.innerWidth;
  const left = flipX ? hovered.x - WIDTH - OFFSET : hovered.x + OFFSET;
  const estimatedHeight = 118 + rows.length * 19;
  const top = Math.max(8, Math.min(hovered.y + OFFSET, window.innerHeight - estimatedHeight - 8));

  return (
    <div className="map-tooltip" style={{ left, top, width: WIDTH }} role="tooltip">
      <div className="map-tooltip__header">
        <span className="map-tooltip__name">Screening cell</span>
        <span className="map-tooltip__type">{SCORE_LABEL[zone.score] ?? 'Unknown'}</span>
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
        Heuristic screening, not a validated PFZ advisory — chlorophyll above the local
        median plus an SST band.
      </p>
    </div>
  );
}
