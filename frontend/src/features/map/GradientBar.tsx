import type { LayerLegend } from './types';

type GradientLegend = Extract<LayerLegend, { type: 'gradient' }>;

/** Renders the color ramp + min/max/unit for a `gradient`-type LayerLegend.
 * Shared by the inline legend in MapControls.tsx and the floating SstLegend,
 * so both stay visually identical without duplicating the gradient math. */
export function GradientBar({ legend }: { legend: GradientLegend }) {
  const gradient = `linear-gradient(to right, ${legend.stops
    .map((s) => `${s.color} ${(s.offset * 100).toFixed(1)}%`)
    .join(', ')})`;

  return (
    <div className="gradient-bar">
      <div className="gradient-bar__ramp" style={{ background: gradient }} />
      <div className="gradient-bar__ticks">
        <span>
          {legend.min}
          {legend.unit}
        </span>
        <span>
          {legend.max}
          {legend.unit}
        </span>
      </div>
    </div>
  );
}
