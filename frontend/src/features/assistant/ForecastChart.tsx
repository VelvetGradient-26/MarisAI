/**
 * Renders a chat turn's `get_forecast_trend` tool result as a chart, right
 * below the answer text — not tucked inside the collapsed "N data calls"
 * disclosure panel, since a graph nobody sees by default undercuts the
 * point of asking the assistant to draw one.
 *
 * The charting internals below are a deliberate fork of
 * `features/dashboard/metric/components/SeriesChart.tsx`, not an import of
 * it. That component's own wrapper/reset-zoom-button JSX is hardcoded
 * Tailwind utility classes reading `--oid-*` custom properties, both of
 * which only exist where a dashboard page imports `tailwind.css` and wraps
 * itself in `.oid-root`. `AssistantPage.tsx` does neither — pages are
 * `React.lazy`-loaded per route (`app/App.tsx`), so that stylesheet is not
 * in this page's bundle — and per CLAUDE.md that scoping is deliberate, not
 * an oversight to route around. Everything except the final wrapper/button
 * JSX (uPlot setup, resize handling, the band/marker plugins, the palette)
 * is unchanged from `SeriesChart.tsx`; only the two Tailwind-coupled
 * surfaces were rewritten against this page's own `--chat-*` tokens.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import uPlot from 'uplot';
import 'uplot/dist/uPlot.min.css';
import { useThemeStore } from '../../store/themeStore';

interface ChartBand {
  lower: (number | null)[];
  upper: (number | null)[];
}

interface ChartSeries {
  label: string;
  values: (number | null)[];
  dashed?: boolean;
}

interface ChatSeriesChartProps {
  x: number[];
  series: ChartSeries[];
  band?: ChartBand;
  unit?: string;
  height?: number;
  forecastFrom?: number | null;
  onHover?: (index: number | null) => void;
}

function palette(isDark: boolean) {
  return isDark
    ? {
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

function bandPlugin(getBand: () => ChartBand | undefined, colour: string): uPlot.Plugin {
  return {
    hooks: {
      draw: (u: uPlot) => {
        const band = getBand();
        if (!band) return;

        const { ctx } = u;
        const [left, top, width, height] = [u.bbox.left, u.bbox.top, u.bbox.width, u.bbox.height];

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

function formatTick(value: number): string {
  const magnitude = Math.abs(value);
  if (magnitude >= 1000) return value.toFixed(0);
  if (magnitude >= 10) return value.toFixed(1);
  if (magnitude >= 1) return value.toFixed(2);
  return value.toFixed(3);
}

function ChatSeriesChart({
  x,
  series,
  band,
  unit,
  height = 220,
  forecastFrom,
  onHover,
}: ChatSeriesChartProps) {
  const isDark = useThemeStore((state) => state.dark);
  const colours = useMemo(() => palette(isDark), [isDark]);

  const containerRef = useRef<HTMLDivElement>(null);
  const plotRef = useRef<uPlot | null>(null);
  const [width, setWidth] = useState(0);

  const bandRef = useRef(band);
  bandRef.current = band;
  const forecastRef = useRef(forecastFrom);
  forecastRef.current = forecastFrom;
  const hoverRef = useRef(onHover);
  hoverRef.current = onHover;

  useEffect(() => {
    const element = containerRef.current;
    if (!element) return;

    const observer = new ResizeObserver((entries) => {
      const next = Math.floor(entries[0].contentRect.width);
      if (next > 0) setWidth(next);
    });
    observer.observe(element);
    setWidth(Math.floor(element.getBoundingClientRect().width));
    return () => observer.disconnect();
  }, []);

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
      legend: { show: false },
      cursor: {
        drag: { x: true, y: false, uni: 50 },
        points: { size: 6 },
      },
      scales: {
        x: { time: true },
        y: {
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
          size: 46,
          values: (_u, ticks) => ticks.map((tick) => formatTick(tick)),
          label: unit,
          labelSize: unit ? 18 : 0,
          labelFont: '10px Inter, system-ui, sans-serif',
        },
      ],
      series: [
        {},
        ...series.map((entry, index) => ({
          label: entry.label,
          stroke: index === 0 ? colours.stroke : colours.stroke2,
          width: 1.75,
          dash: entry.dashed ? ([5, 4] as [number, number]) : undefined,
          points: { show: false },
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

    const data: uPlot.AlignedData = [x, ...series.map((entry) => entry.values)] as uPlot.AlignedData;

    const plot = new uPlot(options, data, element);
    plotRef.current = plot;
    return () => {
      plot.destroy();
      plotRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signature, width, height, unit, colours]);

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
    <div className="chat-forecast-chart__canvas-wrap">
      <div ref={containerRef} style={{ minHeight: height }} />
      <button type="button" onClick={resetZoom} className="chat-forecast-chart__reset-zoom">
        Reset zoom
      </button>
    </div>
  );
}

/** The shape `_forecast_trend` (backend/services/chat/tools.py) returns. */
interface ForecastTrendResult {
  variable: string;
  label: string;
  unit: string;
  history: Array<{ t: string; v: number }>;
  points: Array<{
    horizon_days: number;
    target_time: string;
    prediction: number;
    interval_low: number;
    interval_high: number;
  }>;
}

function isForecastTrendResult(value: unknown): value is ForecastTrendResult {
  if (!value || typeof value !== 'object') return false;
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.variable === 'string' &&
    typeof candidate.unit === 'string' &&
    Array.isArray(candidate.history) &&
    Array.isArray(candidate.points)
  );
}

/**
 * Maps `_forecast_trend`'s response into the chart's props: one shared `x`
 * axis (history timestamps, then each horizon's target time), an "Observed"
 * series that stops after the last real reading, and a dashed "Forecast"
 * series that starts exactly there — so the two lines read as one
 * continuous path rather than a floating disconnected segment. Mirrors
 * `features/dashboard/metric/sections/ForecastSection.tsx`'s mapping
 * against the REST batch-forecast shape; this is the same logic against
 * the chat tool's own (differently-shaped, more compact) result.
 */
function buildChart(result: ForecastTrendResult) {
  const historyX = result.history.map((point) => Date.parse(point.t) / 1000);
  const historyY = result.history.map((point) => point.v);

  const points = [...result.points].sort(
    (a, b) => Date.parse(a.target_time) - Date.parse(b.target_time)
  );
  const pointsX = points.map((point) => Date.parse(point.target_time) / 1000);

  const x = [...historyX, ...pointsX];
  const lastObserved = historyY.at(-1) ?? null;

  const observed: (number | null)[] = [...historyY, ...points.map(() => null)];
  const predicted: (number | null)[] = [
    ...historyY.map((_, index) => (index === historyY.length - 1 ? lastObserved : null)),
    ...points.map((point) => point.prediction),
  ];
  const lower: (number | null)[] = [
    ...historyY.map((_, index) => (index === historyY.length - 1 ? lastObserved : null)),
    ...points.map((point) => point.interval_low),
  ];
  const upper: (number | null)[] = [
    ...historyY.map((_, index) => (index === historyY.length - 1 ? lastObserved : null)),
    ...points.map((point) => point.interval_high),
  ];

  return {
    x,
    observed,
    predicted,
    lower,
    upper,
    points,
    forecastFrom: historyX.at(-1) ?? null,
  };
}

export function ForecastChart({ result }: { result: unknown }) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  if (!isForecastTrendResult(result) || result.points.length === 0) return null;

  const chart = buildChart(result);
  const hovered = hoverIndex != null ? chart.x[hoverIndex] : null;
  const hoveredObserved = hoverIndex != null ? chart.observed[hoverIndex] : null;
  const hoveredPredicted = hoverIndex != null ? chart.predicted[hoverIndex] : null;
  const hoveredLower = hoverIndex != null ? chart.lower[hoverIndex] : null;
  const hoveredUpper = hoverIndex != null ? chart.upper[hoverIndex] : null;

  return (
    <div className="chat-forecast-chart">
      <div className="chat-forecast-chart__header">
        <span className="chat-forecast-chart__title">{result.label} — forecast trend</span>
        {hovered != null && (
          <span className="chat-forecast-chart__hover">
            {new Date(hovered * 1000).toISOString().slice(0, 10)} ·{' '}
            {hoveredObserved != null
              ? `${hoveredObserved.toFixed(2)} ${result.unit}`
              : hoveredPredicted != null
                ? `${hoveredPredicted.toFixed(2)} (${hoveredLower?.toFixed(2)}–${hoveredUpper?.toFixed(2)}) ${result.unit}`
                : '—'}
          </span>
        )}
      </div>

      <ChatSeriesChart
        x={chart.x}
        unit={result.unit}
        forecastFrom={chart.forecastFrom}
        onHover={setHoverIndex}
        band={{ lower: chart.lower, upper: chart.upper }}
        series={[
          { label: 'Observed', values: chart.observed },
          { label: 'Forecast', values: chart.predicted, dashed: true },
        ]}
      />

      <div className="chat-forecast-chart__legend">
        <span className="chat-forecast-chart__legend-item">
          <span className="chat-forecast-chart__swatch chat-forecast-chart__swatch--observed" />
          Observed
        </span>
        <span className="chat-forecast-chart__legend-item">
          <span className="chat-forecast-chart__swatch chat-forecast-chart__swatch--forecast" />
          Forecast
        </span>
        <span className="chat-forecast-chart__legend-item">
          <span className="chat-forecast-chart__swatch chat-forecast-chart__swatch--band" />
          Uncertainty interval
        </span>
      </div>

      <p className="chat-forecast-chart__note">
        Statistical forecast from a trained model, not an official marine warning — the shaded
        band is the model&apos;s own historical error at each horizon, not a guarantee.
      </p>
    </div>
  );
}
