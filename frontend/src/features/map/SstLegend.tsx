import { useEffect, useState } from 'react';
import { useMapStore } from '../../store/mapStore';
import { GradientBar } from './GradientBar';
import { fetchSstMeta } from './api/sst';
import type { SstMetaResponse } from './api/sst';
import { layerRegistry } from './layers/layerRegistry';

const META_REFRESH_MS = 5 * 60 * 1000;

const sstDescriptor = layerRegistry.find((d) => d.id === 'sst');
const sstGradientLegend =
  sstDescriptor?.legend?.type === 'gradient' ? sstDescriptor.legend : null;

/** Floating bottom-right legend for the SST layer — separate from the
 * collapsible MapControls panel so it's always visible while the layer is
 * on, per the "floating legend" requirement. Polls /sst/meta so the shown
 * timestamp keeps itself current without user action. */
export function SstLegend() {
  const active = useMapStore((s) => s.layers.get('sst')?.active ?? false);
  const [meta, setMeta] = useState<SstMetaResponse | null>(null);
  const [status, setStatus] = useState<'loading' | 'error' | 'success'>('loading');

  useEffect(() => {
    if (!active) return;

    let cancelled = false;
    const controller = new AbortController();

    const load = () => {
      fetchSstMeta(controller.signal)
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

  if (!active || !sstGradientLegend) return null;

  return (
    <div className="sst-legend">
      <div className="sst-legend__title">Sea Surface Temperature</div>
      <GradientBar legend={sstGradientLegend} />
      <div className="sst-legend__meta">
        {status === 'loading' && <span>Loading dataset info…</span>}
        {status === 'error' && <span className="sst-legend__error">SST data temporarily unavailable</span>}
        {status === 'success' && meta && (
          <>
            <span>Updated: {formatTimestamp(meta.timestamp)}</span>
            <span className="sst-legend__source">{meta.source}</span>
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
