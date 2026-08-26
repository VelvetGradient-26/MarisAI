/** One tracked GIBS satellite product's detail — the click-through target
 * from a Recent Satellite Products row.
 *
 * No new backend endpoint: `services/gibs.py` already returns the complete
 * per-product shape (`products()` in `useSatellites()`'s response), so this
 * page just looks the one requested layer up in that same list rather than
 * fetching a second time.
 *
 * The preview image is new, and deliberately not a WMTS tile: GIBS' tile
 * scheme needs the exact TileMatrixSet id per zoom level, which
 * `services/gibs.py` only ever used internally to derive the resolution
 * *label* and never persisted. NASA's Worldview Snapshots API
 * (`wvs.earthdata.nasa.gov`) instead renders one flat image for a layer,
 * date and bbox in a single request — no tile math, no backend proxy, just
 * an `<img src>` built from fields already on hand (`layer_id`, `latest_date`,
 * `format`). Public, unauthenticated, and the same NASA-published shape
 * Worldview's own UI uses.
 */

import { useEffect } from 'react';
import { ImageOff } from 'lucide-react';
import { useAppRouter } from '../../../app/routerContext';
import { useThemeStore } from '../../../store/themeStore';
import type { SatelliteProduct } from '../api/types';
import { useSatellites } from '../hooks/useDashboardData';
import { Breadcrumb } from '../components/Breadcrumb';
import { Panel, PanelEmpty, PanelHeader, PanelSkeleton } from '../components/Panel';
import { cn } from '../lib/cn';
import '../styles/tailwind.css';

const STATUS_LABEL: Record<SatelliteProduct['status'], string> = {
  current: 'Current',
  delayed: 'Delayed',
  stale: 'Stale',
  unknown: 'Unknown',
};

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div>
      <dt className="text-[9.5px] tracking-wide text-[color:var(--oid-text-ghost)] uppercase">{label}</dt>
      <dd className="text-[13px] font-medium text-[color:var(--oid-text-strong)]">{value}</dd>
      {hint && <p className="mt-0.5 text-[10px] leading-tight text-[color:var(--oid-text-faint)]">{hint}</p>}
    </div>
  );
}

/** A single global-extent render of one layer on its latest date. BBOX is
 * `south,west,north,east` per the API's own convention, not lon/lat. */
function snapshotUrl(product: SatelliteProduct): string | null {
  if (!product.latest_date) return null;
  const params = new URLSearchParams({
    REQUEST: 'GetSnapshot',
    TIME: product.latest_date,
    BBOX: '-90,-180,90,180',
    CRS: 'EPSG:4326',
    LAYERS: product.layer_id,
    FORMAT: product.format ?? 'image/jpeg',
    WIDTH: '640',
    HEIGHT: '320',
  });
  return `https://wvs.earthdata.nasa.gov/api/v1/snapshot?${params.toString()}`;
}

export function SatelliteDossierPage() {
  const { searchParams } = useAppRouter();
  const isDark = useThemeStore((state) => state.dark);

  const layerId = (searchParams.get('layer') ?? '').trim();
  const { data, isPending, isError, error, refetch } = useSatellites();
  const product = data?.products.find((entry) => entry.layer_id === layerId);

  useEffect(() => {
    document.title = product ? `${product.title} | Maris AI` : 'Satellite product | Maris AI';
  }, [product]);

  const preview = product ? snapshotUrl(product) : null;

  return (
    <div
      className={cn('oid-root min-h-screen bg-[image:var(--oid-page)]', !isDark && 'oid-root--light')}
      data-theme={isDark ? 'dark' : 'light'}
    >
      <main
        className="mx-auto max-w-[900px] px-3 pb-16 sm:px-5"
        style={{ paddingTop: 'calc(var(--navbar-h, 64px) + 16px)' }}
      >
        <Breadcrumb current={product?.title ?? (layerId || '—')} />

        {!layerId ? (
          <Panel className="mt-4">
            <PanelEmpty
              title="No product specified"
              reason="This page needs a ?layer= — open it from a row on the Recent Satellite Products panel."
            />
          </Panel>
        ) : (
          <>
            <header className="mt-3 mb-5">
              <h1 className="text-[22px] leading-none font-semibold tracking-tight text-[color:var(--oid-text-strong)]">
                {product?.title ?? layerId}
              </h1>
              <p className="mt-1.5 text-[11.5px] text-[color:var(--oid-text-faint)]">
                {product ? `${product.satellite} · ${product.product}` : 'Loading…'}
              </p>
            </header>

            {isPending && (
              <Panel>
                <PanelSkeleton rows={5} />
              </Panel>
            )}

            {isError && (
              <Panel>
                <PanelEmpty
                  title="Satellite catalog unavailable"
                  reason={error instanceof Error ? error.message : undefined}
                  onRetry={() => void refetch()}
                />
              </Panel>
            )}

            {data && !product && (
              <Panel>
                <PanelEmpty
                  title="Product not found"
                  reason={`${layerId} is not one of the currently tracked GIBS layers.`}
                />
              </Panel>
            )}

            {product && (
              <div className="grid grid-cols-1 gap-4">
                <Panel>
                  <PanelHeader
                    title="Preview"
                    subtitle={
                      product.latest_date
                        ? `Global render for ${product.latest_date}, via NASA Worldview Snapshots`
                        : 'No date available for a preview'
                    }
                  />
                  <div className="p-4">
                    {preview ? (
                      <img
                        src={preview}
                        alt={`${product.title} — global extent, ${product.latest_date}`}
                        className="w-full rounded-lg border border-[color:var(--oid-border)]"
                        onError={(event) => {
                          event.currentTarget.style.display = 'none';
                          const fallback = event.currentTarget.nextElementSibling as HTMLElement | null;
                          if (fallback) fallback.style.display = 'flex';
                        }}
                      />
                    ) : null}
                    <div
                      className="flex-col items-center justify-center gap-2 rounded-lg border border-[color:var(--oid-border)] bg-[color:var(--oid-elevated)] py-10 text-center"
                      style={{ display: preview ? 'none' : 'flex' }}
                    >
                      <ImageOff size={20} className="text-[color:var(--oid-text-faint)]" />
                      <p className="text-[11.5px] text-[color:var(--oid-text-faint)]">
                        Preview unavailable for this product.
                      </p>
                    </div>
                  </div>
                </Panel>

                <Panel>
                  <PanelHeader title="Source" subtitle="What services/gibs.py already tracks for this layer" />
                  <div className="grid grid-cols-2 gap-4 p-4 sm:grid-cols-3">
                    <Stat label="Satellite" value={product.satellite} />
                    <Stat label="Product" value={product.product} />
                    <Stat label="GIBS layer" value={product.layer_id} hint="WMTS layer identifier" />
                    <Stat label="Resolution" value={product.resolution ?? '—'} />
                    <Stat label="Cadence" value={product.cadence ?? '—'} />
                    <Stat label="Format" value={product.format ?? '—'} />
                    <Stat
                      label="Latest date"
                      value={product.latest_date ?? '—'}
                      hint={product.age_days != null ? `${product.age_days} day(s) ago` : undefined}
                    />
                    <Stat label="Status" value={STATUS_LABEL[product.status]} />
                    <Stat label="Coverage" value="Global" />
                  </div>
                </Panel>
              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
}
