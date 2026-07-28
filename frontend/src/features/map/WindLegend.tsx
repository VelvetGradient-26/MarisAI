import { useEffect, useState } from 'react';
import { useMapStore } from '../../store/mapStore';
import { GradientBar } from './GradientBar';
import { fetchWindMeta } from './api/wind';
import type { WindMetaResponse } from './api/wind';
import { layerRegistry } from './layers/layerRegistry';

const META_REFRESH_MS = 5 * 60 * 1000;

const BEAUFORT_BANDS = [
  { force: 0, label: 'Calm' },
  { force: 3, label: 'Gentle' },
  { force: 6, label: 'Strong' },
  { force: 8, label: 'Gale' },
  { force: 10, label: 'Storm' },
  { force: 12, label: 'Hurricane' },
];

const windDescriptor = layerRegistry.find((d) => d.id === 'wind');
const windGradientLegend =
  windDescriptor?.legend?.type === 'gradient' ? windDescriptor.legend : null;

/** Floating legend for the wind particle layer — same pattern as
 * SstLegend.tsx (live-polled timestamp, gradient bar), plus a Beaufort
 * scale key since wind speed is more usefully read that way than as a raw
 * number for most users. Stacks with SstLegend via .legend-stack in
 * MapView.tsx rather than each hardcoding its own screen position, since
 * both can be active at once. */
export function WindLegend() {
  const active = useMapStore((s) => s.layers.get('wind')?.active ?? false);
  const [meta, setMeta] = useState<WindMetaResponse | null>(null);
  const [status, setStatus] = useState<'loading' | 'error' | 'success'>('loading');

  useEffect(() => {
    if (!active) return;

    let cancelled = false;
    const controller = new AbortController();

    const load = () => {
      fetchWindMeta(controller.signal)
        .then((response) => {
          if (cancelled) return;
          setMeta(response);
          setStatus('success');
        })
        .catch(() => {
          if (cancelled || controller.signal.aborted) return;
          setStatus('error');
        });
    };

    load();
    const interval = window.setInterval(load, META_REFRESH_MS);

    return () => {
      cancelled = true;
      controller.abort();
      window.clearInterval(interval);
    };
  }, [active]);

  if (!active || !windGradientLegend) return null;

  return (
    <div className="wind-legend">
      <div className="wind-legend__title">Wind</div>
      <GradientBar legend={windGradientLegend} />
      <div className="wind-legend__beaufort">
        {BEAUFORT_BANDS.map((band) => (
          <span key={band.force}>
            F{band.force} {band.label}
          </span>
        ))}
      </div>
      <div className="wind-legend__meta">
        {status === 'loading' && <span>Loading dataset info…</span>}
        {status === 'error' && (
          <span className="wind-legend__error">Wind data temporarily unavailable</span>
        )}
        {status === 'success' && meta && (
          <>
            <span>Updated: {formatTimestamp(meta.timestamp)}</span>
            <span className="wind-legend__source">{meta.source}</span>
          </>
        )}
      </div>
    </div>
  );
}

function formatTimestamp(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return `${date.toISOString().slice(0, 16).replace('T', ' ')} UTC`;
}
