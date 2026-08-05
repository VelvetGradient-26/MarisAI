/** Historical analysis: the full record, with zoom, overlays and export.
 *
 * This is the section that motivated bringing uPlot in. It routinely draws
 * several thousand points and must stay interactive while the user drags a
 * zoom window across a decade — Recharts, which mounts an SVG node per point,
 * cannot do that and is left to the small summary charts elsewhere.
 *
 * The moving average and trend line are computed here rather than server-side
 * on purpose: they are view state. Changing the window is a slider drag, and a
 * round trip per drag would make it feel broken.
 */

import { useMemo, useState } from 'react';
import { Activity, Download, ImageDown } from 'lucide-react';
import type { SectionProps } from '../sections';
import { useMetricSeries } from '../hooks/useMetricData';
import { SeriesChart } from '../components/SeriesChart';
import { Panel, PanelEmpty, PanelHeader, PanelSkeleton } from '../../components/Panel';
import { cn } from '../../lib/cn';

const RANGES = ['30d', '90d', '6mo', '1y', '5y', '10y'] as const;
const MA_WINDOWS = [0, 7, 30, 90] as const;

/** Trailing simple moving average. Nulls until the window is full, so the
 *  line never implies an average over data that does not exist. */
function movingAverage(values: (number | null)[], window: number): (number | null)[] {
  if (window <= 1) return values;
  const out: (number | null)[] = new Array(values.length).fill(null);
  let sum = 0;
  let count = 0;
  const queue: number[] = [];

  for (let i = 0; i < values.length; i += 1) {
    const value = values[i];
    if (value != null && Number.isFinite(value)) {
      queue.push(value);
      sum += value;
      count += 1;
    }
    while (queue.length > window) {
      sum -= queue.shift() as number;
      count -= 1;
    }
    if (queue.length === window) out[i] = sum / count;
  }
  return out;
}

/** Ordinary least-squares fit across the whole visible series. */
function trendLine(x: number[], y: (number | null)[]): (number | null)[] {
  const pairs = x
    .map((xi, i) => [xi, y[i]] as const)
    .filter((pair): pair is readonly [number, number] => pair[1] != null);
  if (pairs.length < 2) return y.map(() => null);

  const n = pairs.length;
  const meanX = pairs.reduce((acc, p) => acc + p[0], 0) / n;
  const meanY = pairs.reduce((acc, p) => acc + p[1], 0) / n;
  let numerator = 0;
  let denominator = 0;
  for (const [xi, yi] of pairs) {
    numerator += (xi - meanX) * (yi - meanY);
    denominator += (xi - meanX) ** 2;
  }
  if (denominator === 0) return y.map(() => null);
  const slope = numerator / denominator;
  return x.map((xi) => meanY + slope * (xi - meanX));
}

function downloadBlob(blob: Blob, filename: string) {
  const href = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = href;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(href);
}

export function HistoricalAnalysis({ variable, latitude, longitude }: SectionProps) {
  const [range, setRange] = useState<string>('1y');
  const [maWindow, setMaWindow] = useState<number>(30);
  const [showTrend, setShowTrend] = useState(true);
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  const { data, isPending, isError, error, refetch } = useMetricSeries({
    variable: variable.key,
    latitude,
    longitude,
    range,
    maxPoints: 6000,
  });

  const chart = useMemo(() => {
    if (!data) return null;
    const x = data.points.map((point) => point.t);
    const y: (number | null)[] = data.points.map((point) => point.v);
    return {
      x,
      y,
      ma: maWindow > 0 ? movingAverage(y, maWindow) : null,
      trend: showTrend ? trendLine(x, y) : null,
    };
  }, [data, maWindow, showTrend]);

  const exportCsv = () => {
    if (!data) return;
    const rows = [
      `# ${data.label} (${data.unit}) at ${data.latitude}, ${data.longitude}`,
      `# ${data.start} to ${data.end}, ${data.resolution}`,
      `# ${data.observation_count} observations, ${data.rendered_count} plotted`,
      `# Source: ${data.sources.join('; ')}`,
      'time,value',
      ...data.points.map(
        (point) => `${new Date(point.t * 1000).toISOString()},${point.v}`
      ),
    ];
    downloadBlob(
      new Blob([rows.join('\n')], { type: 'text/csv;charset=utf-8' }),
      `marisai_${data.variable}_${range}.csv`
    );
  };

  const exportPng = () => {
    // uPlot draws to a canvas already in the DOM, so the export is a direct
    // read of what the user is looking at rather than a re-render.
    const canvas = document.querySelector<HTMLCanvasElement>(
      `#metric-history-${variable.key} canvas`
    );
    if (!canvas) return;
    canvas.toBlob((blob) => {
      if (blob) downloadBlob(blob, `marisai_${variable.key}_${range}.png`);
    });
  };

  const hovered =
    chart && hoverIndex != null && hoverIndex < chart.x.length
      ? {
          time: chart.x[hoverIndex],
          value: chart.y[hoverIndex],
          ma: chart.ma?.[hoverIndex] ?? null,
        }
      : null;

  return (
    <Panel>
      <PanelHeader
        icon={<Activity size={14} />}
        title="Historical Analysis"
        subtitle={
          data
            ? `${data.observation_count.toLocaleString()} observations${
                data.decimated
                  ? ` · drawn as ${data.rendered_count.toLocaleString()} points, peaks preserved`
                  : ''
              }`
            : 'Drag to zoom, double-click to reset'
        }
        actions={
          <>
            <button
              type="button"
              onClick={exportCsv}
              disabled={!data}
              className="rounded-md p-1 text-[color:var(--oid-text-faint)] transition-colors hover:text-[color:var(--oid-accent)] disabled:opacity-40"
              title="Export CSV"
            >
              <Download size={13} />
            </button>
            <button
              type="button"
              onClick={exportPng}
              disabled={!data}
              className="rounded-md p-1 text-[color:var(--oid-text-faint)] transition-colors hover:text-[color:var(--oid-accent)] disabled:opacity-40"
              title="Export PNG"
            >
              <ImageDown size={13} />
            </button>
          </>
        }
      />

      <div className="flex flex-wrap items-center gap-2 border-b border-[color:var(--oid-border)] px-4 py-2.5">
        <div className="flex flex-wrap gap-1">
          {RANGES.map((option) => (
            <button
              key={option}
              type="button"
              onClick={() => setRange(option)}
              className={cn(
                'rounded-full px-2.5 py-1 text-[10.5px] font-medium transition-colors',
                range === option
                  ? 'bg-[color:var(--oid-accent-wash-strong)] text-[color:var(--oid-accent)]'
                  : 'text-[color:var(--oid-text-faint)] hover:bg-[color:var(--oid-track)]'
              )}
            >
              {option}
            </button>
          ))}
        </div>

        <span className="mx-1 h-4 w-px bg-[color:var(--oid-border)]" />

        <span className="text-[10px] text-[color:var(--oid-text-ghost)]">Moving avg</span>
        {MA_WINDOWS.map((option) => (
          <button
            key={option}
            type="button"
            onClick={() => setMaWindow(option)}
            className={cn(
              'rounded-full px-2 py-1 text-[10.5px] transition-colors',
              maWindow === option
                ? 'bg-[color:var(--oid-accent-wash-strong)] text-[color:var(--oid-accent)]'
                : 'text-[color:var(--oid-text-faint)] hover:bg-[color:var(--oid-track)]'
            )}
          >
            {option === 0 ? 'off' : `${option}d`}
          </button>
        ))}

        <span className="mx-1 h-4 w-px bg-[color:var(--oid-border)]" />

        <label className="inline-flex cursor-pointer items-center gap-1.5 text-[10.5px] text-[color:var(--oid-text-faint)]">
          <input
            type="checkbox"
            checked={showTrend}
            onChange={(event) => setShowTrend(event.target.checked)}
            className="accent-[color:var(--oid-accent)]"
          />
          Trend line
        </label>

        {hovered?.value != null && (
          <span className="ml-auto font-mono text-[10.5px] text-[color:var(--oid-text-muted)]">
            {new Date(hovered.time * 1000).toISOString().slice(0, 10)} ·{' '}
            {hovered.value.toFixed(2)} {variable.unit}
            {hovered.ma != null && ` · MA ${hovered.ma.toFixed(2)}`}
          </span>
        )}
      </div>

      {isPending && <PanelSkeleton rows={4} />}

      {isError && (
        <PanelEmpty
          title="History unavailable"
          reason={error instanceof Error ? error.message : undefined}
          onRetry={() => void refetch()}
        />
      )}

      {chart && data && (
        <div className="p-4" id={`metric-history-${variable.key}`}>
          <SeriesChart
            x={chart.x}
            unit={variable.unit}
            height={340}
            onHover={setHoverIndex}
            series={[
              { label: variable.label, values: chart.y },
              ...(chart.ma ? [{ label: `${maWindow}d average`, values: chart.ma }] : []),
              ...(chart.trend
                ? [{ label: 'Trend', values: chart.trend, dashed: true, width: 1 }]
                : []),
            ]}
          />
          <p className="mt-2 text-[10px] text-[color:var(--oid-text-ghost)]">
            Drag horizontally to zoom · {data.sources.join(' · ')}
            {data.coverage_start && ` · record begins ${data.coverage_start}`}
          </p>
        </div>
      )}
    </Panel>
  );
}
