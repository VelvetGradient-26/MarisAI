import { useEffect, useRef, useState } from 'react';
import { useMapStore } from '../../store/mapStore';
import { fetchDepth } from './api/depth';
import type { DepthResponse } from './api/depth';

const DEPTH_DEBOUNCE_MS = 400;

export function CoordinateDisplay() {
  const cursor = useMapStore((s) => s.cursor);
  const zoom = useMapStore((s) => s.camera.zoom);
  const [depth, setDepth] = useState<DepthResponse | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!cursor) return;

    const timer = window.setTimeout(() => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      fetchDepth(cursor, controller.signal)
        .then((response) => setDepth(response))
        .catch(() => {
          if (!controller.signal.aborted) setDepth(null);
        });
    }, DEPTH_DEBOUNCE_MS);

    return () => window.clearTimeout(timer);
  }, [cursor]);

  return (
    <div className="coordinate-display">
      <span>{cursor ? `${cursor.lat.toFixed(4)}°, ${cursor.lng.toFixed(4)}°` : '—'}</span>
      <span className="depth">{formatDepth(depth)}</span>
      <span className="zoom">z{zoom.toFixed(2)}</span>
    </div>
  );
}

function formatDepth(depth: DepthResponse | null): string {
  if (!depth) return 'Depth —';
  if (depth.is_land) return `Land · ${Math.round(depth.elevation_m)} m elev.`;
  return `Depth ${Math.round(depth.depth_m ?? 0)} m`;
}
