/**
 * Inline SVG artwork for the landing page.
 *
 * Two kinds live here, and the second is the point:
 *
 * * **Glyphs** for the four platform surfaces — line art that depicts what
 *   each surface actually does (a layer stack, a KPI row, a grid resolving
 *   into rows, a query fanning out to tools) rather than a generic icon.
 *
 * * **Method diagrams** for the research section. These draw the real
 *   validation strategies: rolling-origin splits with an embargo, and spatial
 *   block cross-validation. A claim like "never random K-fold" is abstract in
 *   a bullet list and obvious in a picture, and these are the two choices the
 *   pipelines' credibility rests on — so they are worth drawing properly.
 *
 * Everything is flat 2D, sized by `viewBox`, and coloured from CSS custom
 * properties so both themes work without a second copy.
 */

const STROKE = 'var(--lp-glyph-line)';
const ACCENT = 'var(--lp-accent)';
const MUTED = 'var(--lp-glyph-muted)';

// --------------------------------------------------------------------------
// Surface glyphs
// --------------------------------------------------------------------------

/** Stacked overlay planes over a coastline — the map's layer model. */
export function MapGlyph() {
  return (
    <svg viewBox="0 0 120 76" fill="none" className="lp-glyph__svg" aria-hidden="true">
      {[0, 1, 2].map((index) => (
        <rect
          key={index}
          x={14 + index * 8}
          y={44 - index * 14}
          width="78"
          height="26"
          rx="4"
          stroke={index === 2 ? ACCENT : STROKE}
          strokeWidth="1.25"
          fill="none"
          className="lp-glyph__layer"
          style={{ transitionDelay: `${index * 60}ms` }}
        />
      ))}
      <path
        d="M24 52 C 38 44, 46 58, 60 50 S 84 44, 96 52"
        stroke={ACCENT}
        strokeWidth="1.5"
        strokeLinecap="round"
      />
      <circle cx="72" cy="24" r="3" fill={ACCENT} />
    </svg>
  );
}

/** A KPI row above a sparkline — the dashboard's shape. */
export function DashboardGlyph() {
  const bars = [16, 30, 22, 38];
  return (
    <svg viewBox="0 0 120 76" fill="none" className="lp-glyph__svg" aria-hidden="true">
      {bars.map((height, index) => (
        <rect
          key={index}
          x={16 + index * 24}
          y={40 - height}
          width="14"
          height={height}
          rx="3"
          fill={index === 3 ? ACCENT : MUTED}
          className="lp-glyph__bar"
          style={{ transitionDelay: `${index * 70}ms` }}
        />
      ))}
      <path
        d="M16 60 L34 54 L52 62 L70 48 L88 56 L104 46"
        stroke={STROKE}
        strokeWidth="1.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/** A gridded field resolving into tabular rows — the downloader's job. */
export function DownloadGlyph() {
  return (
    <svg viewBox="0 0 120 76" fill="none" className="lp-glyph__svg" aria-hidden="true">
      <g stroke={STROKE} strokeWidth="1">
        {[0, 1, 2, 3].map((row) =>
          [0, 1, 2, 3].map((col) => (
            <rect
              key={`${row}-${col}`}
              x={14 + col * 10}
              y={18 + row * 10}
              width="10"
              height="10"
              fill={(row + col) % 3 === 0 ? MUTED : 'none'}
            />
          )),
        )}
      </g>
      <path d="M60 38 L72 38" stroke={ACCENT} strokeWidth="1.4" strokeLinecap="round" />
      <path
        d="M69 34 L74 38 L69 42"
        stroke={ACCENT}
        strokeWidth="1.4"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
      <g className="lp-glyph__rows">
        {[0, 1, 2, 3].map((row) => (
          <rect
            key={row}
            x="80"
            y={22 + row * 9}
            width={row === 0 ? 26 : 22 - row * 2}
            height="4"
            rx="2"
            fill={row === 0 ? ACCENT : MUTED}
            style={{ transitionDelay: `${row * 60}ms` }}
          />
        ))}
      </g>
    </svg>
  );
}

/** One question fanning out to tool calls and back — the agent loop. */
export function AssistantGlyph() {
  return (
    <svg viewBox="0 0 120 76" fill="none" className="lp-glyph__svg" aria-hidden="true">
      <rect x="12" y="30" width="24" height="16" rx="5" stroke={ACCENT} strokeWidth="1.4" />
      <g stroke={STROKE} strokeWidth="1.1">
        <path d="M36 38 C 50 38, 52 20, 66 20" />
        <path d="M36 38 L66 38" />
        <path d="M36 38 C 50 38, 52 56, 66 56" />
      </g>
      {[20, 38, 56].map((y, index) => (
        <rect
          key={y}
          x="66"
          y={y - 6}
          width="30"
          height="12"
          rx="4"
          fill="none"
          stroke={MUTED}
          strokeWidth="1.1"
          className="lp-glyph__node"
          style={{ transitionDelay: `${index * 80}ms` }}
        />
      ))}
      <circle cx="101" cy="38" r="3" fill={ACCENT} />
    </svg>
  );
}

// --------------------------------------------------------------------------
// Method diagrams
// --------------------------------------------------------------------------

/**
 * Rolling-origin cross-validation with an embargo — the HAB pipeline's split.
 *
 * Each row is one fold. Training grows forward in time, a gap at least as long
 * as the forecast horizon is discarded, then the test window follows. The gap
 * is the part worth seeing: without it a training row within h days of the
 * test window shares its target period, and the model scores on information it
 * would not have had.
 */
export function RollingOriginDiagram() {
  const folds = [
    { train: 30, embargo: 8, test: 16 },
    { train: 44, embargo: 8, test: 16 },
    { train: 58, embargo: 8, test: 16 },
    { train: 72, embargo: 8, test: 16 },
  ];

  return (
    <figure className="lp-diagram">
      <svg viewBox="0 0 200 92" className="lp-diagram__svg" aria-hidden="true">
        {folds.map((fold, index) => {
          const y = 8 + index * 20;
          return (
            <g key={index} className="lp-diagram__fold" style={{ transitionDelay: `${index * 110}ms` }}>
              <rect x="4" y={y} width={fold.train * 1.6} height="10" rx="2" fill={MUTED} />
              <rect
                x={4 + fold.train * 1.6}
                y={y}
                width={fold.embargo * 1.6}
                height="10"
                rx="2"
                fill="none"
                stroke={STROKE}
                strokeWidth="0.9"
                strokeDasharray="2 2"
              />
              <rect
                x={4 + (fold.train + fold.embargo) * 1.6}
                y={y}
                width={fold.test * 1.6}
                height="10"
                rx="2"
                fill={ACCENT}
              />
            </g>
          );
        })}
        <line x1="4" y1="90" x2="196" y2="90" stroke={STROKE} strokeWidth="0.8" />
      </svg>
      <figcaption className="lp-diagram__legend">
        <span>
          <i className="lp-swatch lp-swatch--muted" /> train
        </span>
        <span>
          <i className="lp-swatch lp-swatch--dashed" /> embargo ≥ horizon
        </span>
        <span>
          <i className="lp-swatch lp-swatch--accent" /> test
        </span>
        <span className="lp-diagram__axis">time →</span>
      </figcaption>
    </figure>
  );
}

/**
 * Spatial block cross-validation — the habitat pipeline's split.
 *
 * Whole 3° blocks are held out, not scattered points. Occurrence records are
 * strongly spatially autocorrelated, so a random split leaves points from the
 * same survey transect on both sides and the model scores near-perfectly by
 * recognising its neighbours. Holding out contiguous blocks is what makes the
 * reported number mean "water it has never seen".
 */
export function SpatialBlockDiagram() {
  const columns = 8;
  const rows = 4;
  const heldOut = new Set([3, 9, 20, 26]);

  // Deterministic scatter: a fixed pattern keeps the diagram stable across
  // renders, where Math.random would make it flicker on every re-render.
  const points = Array.from({ length: 46 }, (_, index) => ({
    x: 6 + ((index * 37) % 188),
    y: 6 + ((index * 53) % 80),
  }));

  return (
    <figure className="lp-diagram">
      <svg viewBox="0 0 200 92" className="lp-diagram__svg" aria-hidden="true">
        {Array.from({ length: rows * columns }, (_, index) => {
          const column = index % columns;
          const row = Math.floor(index / columns);
          const held = heldOut.has(index);
          return (
            <rect
              key={index}
              x={4 + column * 24.2}
              y={4 + row * 21}
              width="23"
              height="20"
              rx="2"
              fill={held ? 'var(--lp-accent-soft)' : 'none'}
              stroke={held ? ACCENT : STROKE}
              strokeWidth={held ? 1.3 : 0.7}
              className="lp-diagram__block"
              style={{ transitionDelay: `${(index % 9) * 40}ms` }}
            />
          );
        })}
        {points.map((point, index) => (
          <circle key={index} cx={point.x} cy={point.y} r="1.5" fill={MUTED} />
        ))}
      </svg>
      <figcaption className="lp-diagram__legend">
        <span>
          <i className="lp-swatch lp-swatch--outline" /> training blocks
        </span>
        <span>
          <i className="lp-swatch lp-swatch--accent-soft" /> held out whole
        </span>
        <span className="lp-diagram__axis">3° grid</span>
      </figcaption>
    </figure>
  );
}
