/** Inline SVG sparkline for the KPI cards.
 *
 * Hand-rolled rather than a Recharts chart: these are ~40px tall, redraw on a
 * five-minute poll and appear six times on screen. A full chart runtime per
 * card would cost far more than the path it draws.
 *
 * Renders nothing but an explanatory caption below two points, because a
 * "trend" drawn through a single reading is a line the data does not support.
 */

import { useId } from 'react';
import { cn } from '../lib/cn';

export function Sparkline({
  points,
  className,
  width = 120,
  height = 34,
  positiveIsUp = true,
}: {
  points: { t: string; v: number }[];
  className?: string;
  width?: number;
  height?: number;
  /** Whether a rising line should read as the "good" colour. */
  positiveIsUp?: boolean;
}) {
  const gradientId = useId();

  if (points.length < 2) {
    return (
      <div
        className={cn(
          'flex items-center text-[10px] leading-tight text-[color:var(--oid-text-ghost)]',
          className
        )}
        style={{ width, height }}
      >
        Collecting history…
      </div>
    );
  }

  const values = points.map((point) => point.v);
  const min = Math.min(...values);
  const max = Math.max(...values);
  // A flat series would divide by zero; give it a nominal band so the line
  // renders through the middle instead of collapsing to the baseline.
  const span = max - min || Math.abs(max) * 0.02 || 1;

  const padding = 2;
  const stepX = (width - padding * 2) / (points.length - 1);
  const toY = (value: number) =>
    height - padding - ((value - min) / span) * (height - padding * 2);

  const line = values
    .map((value, index) => `${index === 0 ? 'M' : 'L'}${padding + index * stepX},${toY(value)}`)
    .join(' ');

  const area = `${line} L${padding + (values.length - 1) * stepX},${height} L${padding},${height} Z`;

  const rising = values[values.length - 1] >= values[0];
  const stroke =
    rising === positiveIsUp ? 'var(--oid-accent-soft)' : 'var(--oid-accent)';

  return (
    <svg
      className={className}
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      fill="none"
      role="img"
      aria-label={`Trend across ${points.length} recorded values, ${
        rising ? 'rising' : 'falling'
      } from ${values[0]} to ${values[values.length - 1]}`}
    >
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={stroke} stopOpacity="0.28" />
          <stop offset="100%" stopColor={stroke} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={area} fill={`url(#${gradientId})`} />
      <path
        d={line}
        stroke={stroke}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle
        cx={padding + (values.length - 1) * stepX}
        cy={toY(values[values.length - 1])}
        r="2.2"
        fill={stroke}
      />
    </svg>
  );
}
