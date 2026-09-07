import type { HoveredEddyTrack } from './hooks/useEddyTracks';

const WIDTH = 254;
const OFFSET = 16;

/**
 * What one tracked eddy is, on hover — the age/identity half of the story
 * `EddyTooltip.tsx` explicitly says a bare detection doesn't have.
 */
export function EddyTrackTooltip({ hovered }: { hovered: HoveredEddyTrack }) {
  const track = hovered.properties;
  const rotation =
    track.polarity === 'cyclonic'
      ? 'Cyclonic — turning with the planet'
      : 'Anticyclonic — turning against it';

  const rows: Array<{ label: string; value: string }> = [
    { label: 'Track ID', value: track.track_id },
    { label: 'Age', value: `${track.age_hours.toFixed(0)} h (${track.hits} detections)` },
    { label: 'Radius', value: `${Number(track.radius_km).toFixed(0)} km (equivalent)` },
    { label: 'Mean speed', value: `${Number(track.mean_speed_ms).toFixed(2)} m/s` },
    { label: 'First seen', value: new Date(track.first_seen).toISOString().slice(0, 16).replace('T', ' ') },
  ];

  const flipX = hovered.x + WIDTH + OFFSET * 2 > window.innerWidth;
  const left = flipX ? hovered.x - WIDTH - OFFSET : hovered.x + OFFSET;
  const estimatedHeight = 118 + rows.length * 19;
  const top = Math.max(8, Math.min(hovered.y + OFFSET, window.innerHeight - estimatedHeight - 8));

  return (
    <div className="map-tooltip" style={{ left, top, width: WIDTH }} role="tooltip">
      <div className="map-tooltip__header">
        <span className="map-tooltip__name">Tracked eddy</span>
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
        {track.hits === 1
          ? 'Just detected — not yet confirmed by a second frame.'
          : 'Not validated against a published eddy atlas (AVISO+ META).'}
      </p>
    </div>
  );
}
