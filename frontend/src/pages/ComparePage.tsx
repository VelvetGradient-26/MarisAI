import { useCallback, useEffect, useState } from 'react';
import { useThemeStore } from '../store/themeStore';
import {
  fetchComparison,
  isForecastRow,
  type CompareResponse,
  type CompareRow,
  type CompareSection,
  type ComparePoint,
} from '../features/map/api/compare';
import './compare.css';

/**
 * Compare two places.
 *
 * The dashboard answers "what is happening globally" and the point brief answers
 * "what is happening here". This is the third question — "how does here differ
 * from there" — which is where research use actually starts.
 *
 * Two things it deliberately does not do:
 *
 *   * **It does not rank.** There is no better point without a purpose, and a
 *     composite score over temperature, waves and habitat would be exactly the
 *     unvalidatable index this project has already declined to build once.
 *   * **It does not invent a delta.** Where the two sides are not numeric in the
 *     same unit, the values stand side by side with an empty delta column
 *     rather than a subtraction that would look authoritative and mean nothing.
 */

/** Kochi and Mangalore — two Indian coastal points inside every model's region,
 *  so a first load shows a populated comparison rather than an empty shell. */
const DEFAULT_A: ComparePoint = { lat: 9.9, lon: 75.9 };
const DEFAULT_B: ComparePoint = { lat: 12.9, lon: 74.6 };

export function ComparePage() {
  const isDark = useThemeStore((s) => s.dark);
  const [a, setA] = useState<ComparePoint>(DEFAULT_A);
  const [b, setB] = useState<ComparePoint>(DEFAULT_B);
  const [result, setResult] = useState<CompareResponse | null>(null);
  const [status, setStatus] = useState<'idle' | 'loading' | 'error'>('idle');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    document.title = 'Maris AI | Compare two places';
  }, []);

  const run = useCallback(
    async (pointA: ComparePoint, pointB: ComparePoint) => {
      setStatus('loading');
      setError(null);
      try {
        setResult(await fetchComparison(pointA, pointB));
        setStatus('idle');
      } catch (exc) {
        setError(exc instanceof Error ? exc.message : 'The comparison could not be built.');
        setStatus('error');
      }
    },
    []
  );

  useEffect(() => {
    void run(DEFAULT_A, DEFAULT_B);
  }, [run]);

  return (
    <div className={`compare-page ${isDark ? '' : 'compare-page--light'}`}>
      <main className="compare-shell">
        <header className="compare-header">
          <h1>Compare two places</h1>
          <p>
            Every field the point brief carries, at two coordinates, with the difference where
            one is defined. Deltas run <strong>B minus A</strong>. No ranking is offered —
            which point is “better” depends on what you are doing there.
          </p>
        </header>

        <form
          className="compare-inputs"
          onSubmit={(event) => {
            event.preventDefault();
            void run(a, b);
          }}
        >
          <PointFields label="Point A" point={a} onChange={setA} />
          <PointFields label="Point B" point={b} onChange={setB} />
          <button type="submit" className="compare-run" disabled={status === 'loading'}>
            {status === 'loading' ? 'Comparing…' : 'Compare'}
          </button>
        </form>

        {status === 'error' && <p className="compare-error">{error}</p>}

        {status === 'loading' && !result && (
          // `data-motion="essential"` is the documented opt-out in tokens.css:
          // an indeterminate spinner frozen by the reduced-motion rule reads as
          // *hung* rather than as calm, so it slows rather than stopping.
          <p className="compare-loading" data-motion="essential" role="status">
            Building both briefs — each fans out over several providers, so this
            takes a few seconds.
          </p>
        )}

        {result && (
          <>
            <div className="compare-legend">
              <span>
                <b>A</b> {formatCoord(result.a.latitude, result.a.longitude)}
              </span>
              <span>
                <b>B</b> {formatCoord(result.b.latitude, result.b.longitude)}
              </span>
            </div>
            {result.sections.map((section) => (
              <SectionTable key={section.key} section={section} />
            ))}
            <p className="compare-footnote">{result.note}</p>
          </>
        )}
      </main>
    </div>
  );
}

function PointFields({
  label,
  point,
  onChange,
}: {
  label: string;
  point: ComparePoint;
  onChange: (next: ComparePoint) => void;
}) {
  return (
    <fieldset className="compare-point">
      <legend>{label}</legend>
      <label>
        <span>Latitude</span>
        <input
          type="number"
          step="0.01"
          min={-90}
          max={90}
          value={point.lat}
          onChange={(event) => onChange({ ...point, lat: Number(event.target.value) })}
        />
      </label>
      <label>
        <span>Longitude</span>
        <input
          type="number"
          step="0.01"
          min={-180}
          max={180}
          value={point.lon}
          onChange={(event) => onChange({ ...point, lon: Number(event.target.value) })}
        />
      </label>
    </fieldset>
  );
}

function SectionTable({ section }: { section: CompareSection }) {
  // Sections stack down a long page and arrive together after one request, so
  // they reveal on scroll rather than all animating at once on load — which
  // would be a page-wide flourish nobody reads, and would fire before the
  // tables below the fold have been looked at. Driven by CSS
  // (`animation-timeline: view()`, see compare.css's `.compare-section.ma-reveal`
  // override) rather than `useReveal`'s JS/IntersectionObserver hook — no child
  // here needs a JS-only sub-animation, so there is nothing left for the hook
  // to do that the browser's own scroll-linked animation doesn't already cover.

  if (!section.available) {
    // Unavailable at both points. Which is itself an answer, and it says why —
    // the same rule the dashboard holds for every panel.
    return (
      <section className="compare-section compare-section--empty ma-reveal">
        <h2>{section.title}</h2>
        <p>{section.a_unavailable_reason ?? section.b_unavailable_reason ?? 'No data.'}</p>
      </section>
    );
  }

  return (
    <section className="compare-section ma-reveal">
      <h2>{section.title}</h2>
      <div className="compare-table-scroll">
        <table className="compare-table">
          <thead>
            <tr>
              <th scope="col">Field</th>
              <th scope="col">A</th>
              <th scope="col">B</th>
              <th scope="col">Δ (B − A)</th>
            </tr>
          </thead>
          <tbody>
            {section.rows.flatMap((row) =>
              isForecastRow(row)
                ? Object.entries(row.horizons).map(([horizon, values]) => (
                    <tr key={`${row.label}-${horizon}`}>
                      <th scope="row">
                        {row.label} <span className="compare-horizon">+{horizon.slice(1)}d</span>
                      </th>
                      <td>{formatNumber(values.a, row.unit)}</td>
                      <td>{formatNumber(values.b, row.unit)}</td>
                      <td className={deltaClass(values.delta)}>
                        {formatNumber(values.delta, row.unit, true)}
                      </td>
                    </tr>
                  ))
                : [<PlainRow key={row.label} row={row} />]
            )}
          </tbody>
        </table>
      </div>
      {section.note && <p className="compare-note">{section.note}</p>}
      {section.a_available !== section.b_available && (
        <p className="compare-note compare-note--asymmetry">
          {section.a_available ? 'Point B' : 'Point A'}:{' '}
          {section.a_available ? section.b_unavailable_reason : section.a_unavailable_reason}
        </p>
      )}
    </section>
  );
}

function PlainRow({ row }: { row: CompareRow }) {
  return (
    <tr>
      <th scope="row">{row.label}</th>
      <td>{row.a ?? <span className="compare-absent">—</span>}</td>
      <td>{row.b ?? <span className="compare-absent">—</span>}</td>
      <td className={deltaClass(row.delta?.value ?? null)}>
        {row.delta ? (
          <>
            {row.delta.value > 0 ? '+' : ''}
            {row.delta.value} {row.delta.unit}
            {row.delta.percent !== null && (
              <span className="compare-percent"> ({row.delta.percent > 0 ? '+' : ''}
                {row.delta.percent}%)</span>
            )}
          </>
        ) : (
          // No delta is a deliberate blank, not a missing feature: it means the
          // two sides are not comparable as numbers in one unit.
          <span className="compare-absent">—</span>
        )}
      </td>
    </tr>
  );
}

function deltaClass(value: number | null): string {
  if (value === null || value === 0) return 'compare-delta';
  return `compare-delta compare-delta--${value > 0 ? 'up' : 'down'}`;
}

function formatNumber(value: number | null, unit: string, signed = false): React.ReactNode {
  if (value === null || value === undefined) return <span className="compare-absent">—</span>;
  const sign = signed && value > 0 ? '+' : '';
  return `${sign}${Number(value.toFixed(3))}${unit ? ` ${unit}` : ''}`;
}

function formatCoord(lat: number, lon: number): string {
  return `${Math.abs(lat).toFixed(2)}°${lat >= 0 ? 'N' : 'S'}, ${Math.abs(lon).toFixed(2)}°${
    lon >= 0 ? 'E' : 'W'
  }`;
}

export default ComparePage;
