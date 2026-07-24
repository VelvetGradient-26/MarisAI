import { useMapStore } from '../../store/mapStore';

export function CoordinateDisplay() {
  const cursor = useMapStore((s) => s.cursor);
  const zoom = useMapStore((s) => s.camera.zoom);

  return (
    <div className="coordinate-display">
      <span>{cursor ? `${cursor.lat.toFixed(4)}°, ${cursor.lng.toFixed(4)}°` : '—'}</span>
      <span className="zoom">z{zoom.toFixed(2)}</span>
    </div>
  );
}
