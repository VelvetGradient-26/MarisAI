/** One analytics chart: range selector, hover detail, CSV and PNG export.
 *
 * Range buttons are driven by the backend's `supported_ranges` for that
 * variable rather than a fixed list. Coverage genuinely differs — wind reaches
 * back to 1940 through ERA5 while the marine model only carries SST from 2024
 * — so offering "10 Years" on every chart would mean most of them answering
 * with an error. Unsupported ranges render disabled with the reason.
 */

import { memo, useCallback, useMemo, useRef, useState } from 'react';
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { Download, ImageDown, Maximize2, TrendingDown, TrendingUp } from 'lucide-react';
import type { TrendRange, TrendVariable } from '../api/types';
import { Link } from '../../../app/router';
import { useThemeStore } from '../../../store/themeStore';
import { useTrend } from '../hooks/useDashboardData';
import { useForecastCatalog } from '../metric/hooks/useMetricData';
import { formatAxisTime, formatValue, rangeNeedsYear } from '../lib/format';
import { cn } from '../lib/cn';
import { Panel, PanelEmpty, PanelHeader, PanelSkeleton } from './Panel';

const RANGE_ORDER = ['24h', '7d', '30d', '6mo', '1y', '5y', '10y'];

/**
 * Trend keys that name the same field as a forecast-catalog variable under a
 * different label.
 *
 * The two catalogs were built for different jobs and grew their own
 * vocabularies: `trends` follows Open-Meteo's parameter names, the forecast
 * engine follows the download registry's. Rather than rename either — both are
 * load-bearing in their own API — the four that genuinely differ are mapped
 * here, and anything absent simply gets no link.
 *
 * `ocean_heat_content` is deliberately unmapped: it is derived by integrating
 * temperature over depth, not a variable with its own record to forecast.
 */
const METRIC_ALIASES: Record<string, string> = {
  wave_height: 'significant_wave_height',
  ocean_current_velocity: 'current_speed',
  sea_level_height_msl: 'sea_surface_height',
  wind_speed_10m: 'wind_speed',
  surface_pressure: 'pressure',
};

function downloadBlob(blob: Blob, filename: string) {
  const href = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = href;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(href);
}

/**
 * Memoised: a chart re-render restarts Recharts' entry animation, so an
 * unrelated parent update must not reach it. Its props are all stable —
 * `ranges` comes from the React Query cache, the rest are primitives.
 */
export const TrendChart = memo(function TrendChart({
  variable,
  ranges,
  latitude,
  longitude,
}: {
  variable: TrendVariable;
  ranges: Record<string, TrendRange>;
  latitude: number;
  longitude: number;
}) {
  // Recharts receives colours as props, not classes, so the theme has to be
  // resolved in JS here rather than through the --oid-* custom properties.
  const isDark = useThemeStore((state) => state.dark);
  const chart = isDark
    ? {
        // These mirror the --oid-* dark set in styles/tailwind.css by hand —
        // there is no way to read a custom property from a Recharts prop, so
        // retuning the palette there means retuning it here too or the chart
        // keeps painting the old navy inside a near-black panel.
        stroke: '#4fd1ff',
        grid: '#26262d',
        tick: '#75757d',
        tooltipBg: '#0e0e11',
        tooltipBorder: 'rgba(79,209,255,0.22)',
        tooltipText: '#e4e4e6',
        tooltipLabel: '#9a9aa2',
        exportBg: '#0e0e11',
      }
    : {
        stroke: '#0f766e',
        grid: '#cfdde6',
        tick: '#64798a',
        tooltipBg: '#ffffff',
        tooltipBorder: 'rgba(15,118,110,0.28)',
        tooltipText: '#0f2231',
        tooltipLabel: '#47616f',
        exportBg: '#ffffff',
      };

  const supported = variable.supported_ranges;
  const [range, setRange] = useState(() => supported.at(-1) ?? '7d');
  const chartRef = useRef<HTMLDivElement>(null);

  const { data, isPending, isError, error, refetch } = useTrend({
    variable: variable.key,
    latitude,
    longitude,
    range,
    enabled: variable.available && supported.includes(range),
  });

  /**
   * The x value must be the raw timestamp, not a formatted label.
   *
   * Labels like "4 Aug" repeat once per year, and Recharts treats a
   * categorical axis by value: with a 10-year daily series every hover
   * resolved to the *first* point sharing that label, so the crosshair
   * cycled through year one over and over and never reached the end.
   * Timestamps are unique, so each point addresses itself; the axis renders
   * the same text through `tickFormatter`.
   */
  const points = useMemo(() => data?.points ?? [], [data]);
  const resolution = data?.resolution ?? 'daily';
  // Tooltips on multi-year ranges must name the year; ticks stay terse.
  const tooltipWithYear = rangeNeedsYear(range);

  const exportCsv = useCallback(() => {
    if (!data) return;
    const rows = [
      `# ${data.label} (${data.unit}) at ${data.latitude}, ${data.longitude}`,
      `# ${data.start} to ${data.end}, ${data.resolution}`,
      `# Source: ${data.source}`,
      'time,value',
      ...data.points.map((point) => `${point.t},${point.v}`),
    ];
    downloadBlob(
      new Blob([rows.join('\n')], { type: 'text/csv;charset=utf-8' }),
      `marisai_${data.variable}_${data.range}.csv`
    );
  }, [data]);

  /**
   * PNG export rasterises the live SVG through a canvas. The SVG is cloned and
   * given an explicit background and inlined font size first: the chart's
   * colours come from CSS custom properties on an ancestor, which do not
   * survive serialisation, and a transparent PNG of pale strokes is unusable
   * on a light background.
   */
  const exportPng = useCallback(() => {
    const svg = chartRef.current?.querySelector('svg');
    if (!svg || !data) return;

    const clone = svg.cloneNode(true) as SVGSVGElement;
    const { width, height } = svg.getBoundingClientRect();
    clone.setAttribute('width', String(width));
    clone.setAttribute('height', String(height));

    const background = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
    background.setAttribute('width', '100%');
    background.setAttribute('height', '100%');
    background.setAttribute('fill', chart.exportBg);
    clone.insertBefore(background, clone.firstChild);

    const source = new XMLSerializer().serializeToString(clone);
    const image = new Image();
    image.onload = () => {
      const canvas = document.createElement('canvas');
      const scale = window.devicePixelRatio || 2;
      canvas.width = width * scale;
      canvas.height = height * scale;
      const context = canvas.getContext('2d');
      if (!context) return;
      context.scale(scale, scale);
      context.drawImage(image, 0, 0);
      canvas.toBlob((blob) => {
        if (blob) downloadBlob(blob, `marisai_${data.variable}_${data.range}.png`);
      }, 'image/png');
    };
    image.src = `data:image/svg+xml;base64,${window.btoa(unescape(encodeURIComponent(source)))}`;
  }, [data, chart.exportBg]);

  const stats = data?.statistics;
  const rising = stats ? stats.change > 0 : false;

  // Resolved against the live catalog, not assumed: a key that maps to nothing
  // trained simply renders no link rather than one that 404s.
  const { data: forecastCatalog } = useForecastCatalog();
  const candidateKey = METRIC_ALIASES[variable.key] ?? variable.key;
  const metricKey = forecastCatalog?.variables.some((entry) => entry.key === candidateKey)
    ? candidateKey
    : null;

  if (!variable.available) {
    return (
      <Panel className="flex min-h-[260px] flex-col">
        <PanelHeader title={variable.label} subtitle={variable.unit} />
        <PanelEmpty title="Not available as a time series" reason={variable.unavailable_reason} />
      </Panel>
    );
  }

  return (
    <Panel className="flex min-h-[260px] flex-col">
      <PanelHeader
        title={variable.label}
        subtitle={
          stats
            ? `${formatValue(stats.min, variable.unit)} – ${formatValue(stats.max, variable.unit)} · mean ${formatValue(stats.mean, variable.unit)}`
            : variable.unit
        }
        actions={
          <div className="flex items-center gap-1">
            {metricKey && (
              <Link
                to={`/dashboard/${metricKey}?lat=${latitude}&lon=${longitude}`}
                aria-label={`Open the ${variable.label} intelligence page`}
                title="Full analysis"
                className="rounded-md p-1.5 text-[color:var(--oid-text-faint)] no-underline transition-colors hover:bg-[color:var(--oid-track)] hover:text-[color:var(--oid-accent)]"
              >
                <Maximize2 size={13} />
              </Link>
            )}
            <button
              type="button"
              onClick={exportCsv}
              disabled={!data || points.length === 0}
              aria-label={`Export ${variable.label} as CSV`}
              className="rounded-md p-1.5 text-[color:var(--oid-text-faint)] transition-colors hover:bg-[color:var(--oid-track)] hover:text-[color:var(--oid-text)] disabled:opacity-40"
            >
              <Download size={13} />
            </button>
            <button
              type="button"
              onClick={exportPng}
              disabled={!data || points.length === 0}
              aria-label={`Export ${variable.label} as PNG`}
              className="rounded-md p-1.5 text-[color:var(--oid-text-faint)] transition-colors hover:bg-[color:var(--oid-track)] hover:text-[color:var(--oid-text)] disabled:opacity-40"
            >
              <ImageDown size={13} />
            </button>
          </div>
        }
      />

      <div
        className="flex flex-wrap gap-1 px-3 py-2"
        role="group"
        aria-label={`Time range for ${variable.label}`}
      >
        {RANGE_ORDER.filter((key) => ranges[key]).map((key) => {
          const isSupported = supported.includes(key);
          return (
            <button
              key={key}
              type="button"
              onClick={() => isSupported && setRange(key)}
              disabled={!isSupported}
              aria-pressed={range === key}
              title={
                isSupported
                  ? ranges[key].label
                  : `${variable.label} only goes back to ${variable.coverage_start ?? 'an unknown date'}`
              }
              className={cn(
                'rounded-full px-2.5 py-1 text-[10.5px] font-medium transition-colors',
                range === key
                  ? 'bg-[color:var(--oid-accent)] text-[color:var(--oid-accent-contrast)]'
                  : isSupported
                    ? 'text-[color:var(--oid-text-muted)] hover:bg-[color:var(--oid-track)] hover:text-[color:var(--oid-text)]'
                    : 'cursor-not-allowed text-[color:var(--oid-text-ghost)]'
              )}
            >
              {ranges[key].label}
            </button>
          );
        })}

        {stats && (
          <span
            className={cn(
              'ml-auto inline-flex items-center gap-1 text-[10.5px] font-medium',
              rising ? 'text-[color:var(--color-alert-warning)]' : 'text-[color:var(--oid-accent-soft)]'
            )}
          >
            {rising ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
            {stats.change > 0 ? '+' : ''}
            {stats.change.toFixed(2)} {variable.unit}
          </span>
        )}
      </div>

      {isPending && <PanelSkeleton rows={3} />}

      {isError && (
        <PanelEmpty
          title="Series unavailable"
          reason={error instanceof Error ? error.message : undefined}
          onRetry={() => void refetch()}
        />
      )}

      {data && points.length === 0 && (
        <PanelEmpty
          title="No data in this window"
          reason="The upstream model returned no values for this point and range. Try a different range or location."
        />
      )}

      {data && points.length > 0 && (
        <div ref={chartRef} className="min-h-[150px] flex-1 px-1 pb-2">
          <ResponsiveContainer width="100%" height="100%" minHeight={150}>
            <AreaChart data={points} margin={{ top: 6, right: 10, bottom: 0, left: -18 }}>
              <defs>
                <linearGradient id={`fill-${variable.key}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={chart.stroke} stopOpacity={0.32} />
                  <stop offset="100%" stopColor={chart.stroke} stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke={chart.grid} strokeDasharray="2 4" vertical={false} />
              <XAxis
                dataKey="t"
                tickFormatter={(value) => formatAxisTime(String(value), resolution)}
                tick={{ fill: chart.tick, fontSize: 10 }}
                tickLine={false}
                axisLine={false}
                minTickGap={28}
              />
              <YAxis
                tick={{ fill: chart.tick, fontSize: 10 }}
                tickLine={false}
                axisLine={false}
                width={46}
                domain={['auto', 'auto']}
              />
              <Tooltip
                contentStyle={{
                  background: chart.tooltipBg,
                  border: `1px solid ${chart.tooltipBorder}`,
                  borderRadius: 10,
                  fontSize: 11.5,
                  color: chart.tooltipText,
                }}
                labelStyle={{ color: chart.tooltipLabel, fontSize: 10.5 }}
                // The x value is now a raw timestamp, so the tooltip has to
                // format it the same way the axis does.
                labelFormatter={(value) => formatAxisTime(String(value), resolution, tooltipWithYear)}
                // Recharts types the value as possibly undefined and possibly
                // an array; formatValue already renders anything unusable as
                // an em dash rather than "NaN".
                formatter={(value) => [
                  formatValue(Array.isArray(value) ? value[0] : value, variable.unit),
                  variable.label,
                ]}
              />
              <Area
                type="monotone"
                dataKey="v"
                stroke={chart.stroke}
                strokeWidth={1.6}
                fill={`url(#fill-${variable.key})`}
                // A 10-year daily series is ~3,650 points; dots would be a
                // solid band and thousands of extra DOM nodes.
                dot={false}
                activeDot={{ r: 3, fill: chart.stroke }}
                // Entry animation off, deliberately. Recharts begins it before
                // ResponsiveContainer has settled its width, so it computed
                // against a near-zero width, advanced its clip rect to ~12px of
                // 646 and stalled there permanently — leaving correctly drawn
                // paths clipped down to invisibility, under a header showing
                // perfectly good statistics. Verified it was a stall and not a
                // re-render loop (the clip attribute stopped changing
                // entirely). A chart that always renders beats one that
                // sometimes animates.
                isAnimationActive={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}

      {data && (
        <footer className="border-t border-[color:var(--oid-border)] px-3 py-1.5 text-[9.5px] text-[color:var(--oid-text-ghost)]">
          {data.source} · {data.resolution} · {data.points.length.toLocaleString()} points
        </footer>
      )}
    </Panel>
  );
});
