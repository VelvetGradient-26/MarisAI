/** Canvas time-series chart, over uPlot.
 *
 * Recharts renders SVG — one DOM node per point — and is the right tool for
 * the small summary charts elsewhere in this dashboard. It is the wrong tool
 * here: the historical view can hold 20,000 points and must stay interactive
 * while zooming. uPlot draws to a canvas and handles that without dropping a
 * frame.
 *
 * Three things this wrapper exists to get right:
 *
 * 1. **Resize.** uPlot is imperative and sizes itself once at construction.
 *    A chart in a flex column whose height settles after mount keeps a stale
 *    size and renders in a sliver — the same trap `MapManager` documents for
 *    MapLibre. A `ResizeObserver` on the container is the fix, and it is not
 *    optional.
 * 2. **Theme.** uPlot takes colours as JS values, not CSS classes, so they are
 *    resolved from the theme store here rather than through `--oid-*`. Same
 *    reason `TrendChart` resolves its Recharts palette in JS.
 * 3. **Data identity.** Rebuilding the chart on every render would restart the
 *    zoom state. The instance is created once per structural change (series
 *    shape, theme) and fed new data through `setData` otherwise.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import uPlot from 'uplot';
import 'uplot/dist/uPlot.min.css';
import { useThemeStore } from '../../../../store/themeStore';
import { cn } from '../../lib/cn';

export interface ChartBand {
  /** Lower and upper bounds, aligned index-for-index with `x`. */
  lower: (number | null)[];
  upper: (number | null)[];
  label: string;
}

export interface ChartSeries {
  label: string;
  values: (number | null)[];
  color?: string;
  /** Dashed rendering, for a forecast continuing an observed line. */
  dashed?: boolean;
  width?: number;
}

export interface SeriesChartProps {
  /** Epoch **seconds**, strictly increasing. uPlot renders nothing otherwise. */
  x: number[];
  series: ChartSeries[];
  band?: ChartBand;
  unit?: string;
  height?: number;
  className?: string;
  /** Epoch second at which the forecast begins, drawn as a divider. */
  forecastFrom?: number | null;
  onHover?: (index: number | null) => void;
}

function palette(isDark: boolean) {
  return isDark
    ? {
        // uPlot draws to a canvas, so like TrendChart this is a hand-kept
        // mirror of the --oid-* dark set rather than a read of it.
        stroke: '#4fd1ff',
        stroke2: '#38e0d0',
        band: 'rgba(79,209,255,0.14)',
        grid: 'rgba(56,56,64,0.6)',
        axis: '#75757d',
        marker: 'rgba(154,154,162,0.5)',
      }
    : {
        stroke: '#0f766e',
        stroke2: '#0369a1',
        band: 'rgba(15,118,110,0.13)',
        grid: 'rgba(203,213,225,0.85)',
        axis: '#64798a',
        marker: 'rgba(100,116,139,0.5)',
      };
}

/**
 * Draws the confidence band as a filled region behind the lines.
 *
 * A uPlot plugin rather than two extra series with a fill: uPlot fills to the
 * axis, not between series, so the naive version paints the lower bound's
 * fill over the upper bound's and the band reads as a solid block from zero.
 */
function bandPlugin(getBand: () => ChartBand | undefined, colour: string): uPlot.Plugin {
  return {
    hooks: {
      draw: (u: uPlot) => {
        const band = getBand();
        if (!band) return;

        const { ctx } = u;
        const [left, top, width, height] = [
          u.bbox.left,
          u.bbox.top,
          u.bbox.width,
          u.bbox.height,
        ];

        ctx.save();
        ctx.beginPath();
        ctx.rect(left, top, width, height);
        ctx.clip();
        ctx.fillStyle = colour;

        ctx.beginPath();
        let started = false;
        const xs = u.data[0] as number[];

        for (let i = 0; i < xs.length; i += 1) {
          const upper = band.upper[i];
          if (upper == null || !Number.isFinite(upper)) continue;
          const px = u.valToPos(xs[i], 'x', true);
          const py = u.valToPos(upper, 'y', true);
          if (!started) {
            ctx.moveTo(px, py);
            started = true;
          } else {
            ctx.lineTo(px, py);
          }
        }
        // Back along the lower bound to close the ribbon.
        for (let i = xs.length - 1; i >= 0; i -= 1) {
          const lower = band.lower[i];
          if (lower == null || !Number.isFinite(lower)) continue;
          ctx.lineTo(u.valToPos(xs[i], 'x', true), u.valToPos(lower, 'y', true));
        }

        if (started) {
          ctx.closePath();
          ctx.fill();
        }
        ctx.restore();
      },
    },
  };
}

/** A vertical rule marking where observation ends and forecast begins. */
function markerPlugin(getAt: () => number | null | undefined, colour: string): uPlot.Plugin {
  return {
    hooks: {
      draw: (u: uPlot) => {
        const at = getAt();
        if (at == null) return;
        const px = u.valToPos(at, 'x', true);
        if (!Number.isFinite(px)) return;

        const { ctx } = u;
        ctx.save();
        ctx.strokeStyle = colour;
        ctx.lineWidth = 1;
        ctx.setLineDash([4, 4]);
        ctx.beginPath();
        ctx.moveTo(px, u.bbox.top);
        ctx.lineTo(px, u.bbox.top + u.bbox.height);
        ctx.stroke();
        ctx.restore();
      },
    },
  };
}

export function SeriesChart({
  x,
  series,
  band,
  unit,
  height = 320,
  className,
  forecastFrom,
  onHover,
}: SeriesChartProps) {
  const isDark = useThemeStore((state) => state.dark);
  const colours = useMemo(() => palette(isDark), [isDark]);

  const containerRef = useRef<HTMLDivElement>(null);
  const plotRef = useRef<uPlot | null>(null);
  const [width, setWidth] = useState(0);

  // Read through refs inside the plugins so a data change does not require
  // rebuilding the chart (and losing the user's zoom).
  const bandRef = useRef(band);
  bandRef.current = band;
  const forecastRef = useRef(forecastFrom);
  forecastRef.current = forecastFrom;
  const hoverRef = useRef(onHover);
  hoverRef.current = onHover;

  useEffect(() => {
    const element = containerRef.current;
    if (!element) return;

    // uPlot sizes itself once. Without this the chart keeps whatever width the
    // container happened to have at mount — which in a lazily-mounted flex
    // column is frequently zero.
    const observer = new ResizeObserver((entries) => {
      const next = Math.floor(entries[0].contentRect.width);
      if (next > 0) setWidth(next);
    });
    observer.observe(element);
    setWidth(Math.floor(element.getBoundingClientRect().width));
    return () => observer.disconnect();
  }, []);

  // Structural signature: rebuild only when the *shape* changes, not the data.
  const signature = useMemo(
    () => `${isDark}|${series.map((s) => `${s.label}:${s.dashed ? 'd' : 's'}`).join(',')}`,
    [isDark, series]
  );

  useEffect(() => {
    const element = containerRef.current;
    if (!element || width === 0) return;

    const options: uPlot.Options = {
      width,
      height,
      // Legend and cursor cost a DOM update per move; the page renders its own
      // readout from `onHover` instead.
      legend: { show: false },
      cursor: {
        drag: { x: true, y: false, uni: 50 },
        points: { size: 6 },
      },
      scales: {
        x: { time: true },
        y: {
          // The band is drawn by a plugin, so uPlot cannot see it when
          // auto-ranging and would fit the axis to the series alone. With a
          // wide interval that put the entire band outside the visible range,
          // where it painted the whole plot area as a flat wash instead of
          // reading as a band. Widening the range to contain it is what makes
          // the uncertainty legible as uncertainty.
          range: (_u, min, max) => {
            const currentBand = bandRef.current;
            if (!currentBand) return uPlot.rangeNum(min, max, 0.1, true);

            let low = min;
            let high = max;
            for (const value of currentBand.lower) {
              if (value != null && Number.isFinite(value)) low = Math.min(low, value);
            }
            for (const value of currentBand.upper) {
              if (value != null && Number.isFinite(value)) high = Math.max(high, value);
            }
            return uPlot.rangeNum(low, high, 0.1, true);
          },
        },
      },
      axes: [
        {
          stroke: colours.axis,
          grid: { stroke: colours.grid, width: 1 },
          ticks: { stroke: colours.grid, width: 1 },
          font: '11px Inter, system-ui, sans-serif',
        },
        {
          stroke: colours.axis,
          grid: { stroke: colours.grid, width: 1 },
          ticks: { stroke: colours.grid, width: 1 },
          font: '11px Inter, system-ui, sans-serif',
          // Bare numbers, and enough room for them. Suffixing every gridline
          // with the unit both triples the label width — at `size: 52` that
          // clipped "27.50 degC" down to a visible "0 degC" on every tick, which
          // read as a broken axis — and repeats information that belongs once.
          // The unit is stated in the panel header and the hover readout.
          size: 46,
          values: (_u, ticks) => ticks.map((tick) => formatTick(tick)),
          // Stated once, rotated alongside the ticks, instead of on each one.
          label: unit,
          labelSize: unit ? 18 : 0,
          labelFont: '10px Inter, system-ui, sans-serif',
        },
      ],
      series: [
        {},
        ...series.map((entry, index) => ({
          label: entry.label,
          stroke: entry.color ?? (index === 0 ? colours.stroke : colours.stroke2),
          width: entry.width ?? 1.75,
          dash: entry.dashed ? [5, 4] : undefined,
          points: { show: false },
          // Skip gaps rather than bridging them: an interpolated line across a
          // provider outage would imply coverage that does not exist.
          spanGaps: false,
        })),
      ],
      plugins: [
        bandPlugin(() => bandRef.current, colours.band),
        markerPlugin(() => forecastRef.current, colours.marker),
        {
          hooks: {
            setCursor: (u: uPlot) => hoverRef.current?.(u.cursor.idx ?? null),
          },
        },
      ],
    };

    const data: uPlot.AlignedData = [
      x,
      ...series.map((entry) => entry.values),
    ] as uPlot.AlignedData;

    const plot = new uPlot(options, data, element);
    plotRef.current = plot;
    return () => {
      plot.destroy();
      plotRef.current = null;
    };
    // `x`/`series` data changes are pushed through the effect below instead.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signature, width, height, unit, colours]);

  // Data-only updates keep the instance (and therefore the zoom) alive.
  useEffect(() => {
    const plot = plotRef.current;
    if (!plot) return;
    plot.setData([x, ...series.map((entry) => entry.values)] as uPlot.AlignedData);
  }, [x, series]);

  const resetZoom = useCallback(() => {
    const plot = plotRef.current;
    if (!plot) return;
    plot.setScale('x', { min: x[0], max: x[x.length - 1] });
  }, [x]);

  return (
    <div className={cn('relative', className)}>
      <div ref={containerRef} className="w-full" style={{ minHeight: height }} />
      <button
        type="button"
        onClick={resetZoom}
        className={cn(
          'absolute top-1 right-1 rounded-md px-2 py-1 text-[length:var(--oid-text-3xs)]',
          'border border-[color:var(--oid-border)] bg-[color:var(--oid-elevated)]',
          'text-[color:var(--oid-text-faint)] transition-colors',
          'hover:text-[color:var(--oid-accent)]'
        )}
      >
        Reset zoom
      </button>
    </div>
  );
}

function formatTick(value: number): string {
  const magnitude = Math.abs(value);
  if (magnitude >= 1000) return value.toFixed(0);
  if (magnitude >= 10) return value.toFixed(1);
  if (magnitude >= 1) return value.toFixed(2);
  return value.toFixed(3);
}
