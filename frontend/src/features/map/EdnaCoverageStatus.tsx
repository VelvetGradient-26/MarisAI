import type { EdnaCoverageState } from './hooks/useEdnaCoverage';

/**
 * How much of the ocean this layer is actually showing.
 *
 * The other two status chips on this map exist so a missing number is never
 * substituted for. This one goes further and states the coverage unprompted,
 * because the failure mode here is not a blank panel — it is a map that renders
 * perfectly and reads as "eDNA has barely been collected anywhere, so there
 * must be a loading problem". There is no loading problem. Roughly a thousand
 * cells is the entire molecular survey of the world ocean, and a reader who has
 * just come from the SST layer has no reason to expect that.
 */
export function EdnaCoverageStatus({ state }: { state: EdnaCoverageState }) {
  const { active, coverage, loading, unavailableReason } = state;
  if (!active) return null;

  if (unavailableReason) {
    return (
      <div className="edna-status edna-status--unavailable">
        <span className="edna-status__dot" />
        {unavailableReason}
      </div>
    );
  }

  if (!coverage) {
    return (
      <div className="edna-status edna-status--unavailable">
        <span className="edna-status__dot" />
        Loading eDNA sampling coverage…
      </div>
    );
  }

  // Always the finest-grid figure, never the drawn grid's — the drawn one rises
  // as the reader zooms out, which would put the most flattering number in the
  // default view. Omitted rather than approximated when the backend could not
  // measure it.
  const fraction = coverage.reference_coverage?.sampled_fraction_of_ocean ?? null;
  // A fraction this small is unreadable as a percentage with the usual one
  // decimal — 0.0017 renders as "0.0%", which says "none" where the truth is
  // "a sixth of one percent". Two significant figures keeps it a real number.
  const percentLabel =
    fraction === null
      ? null
      : fraction * 100 >= 1
        ? `${(fraction * 100).toFixed(1)}%`
        : `${(fraction * 100).toPrecision(2)}%`;

  return (
    <div className="edna-status">
      <span className="edna-status__dot edna-status__dot--live" />
      {coverage.occupied_cells.toLocaleString()} sampled{' '}
      {coverage.occupied_cells === 1 ? 'cell' : 'cells'}
      <span className="edna-status__note">
        {percentLabel ? `≈${percentLabel} of the ocean · ` : ''}
        {coverage.records.toLocaleString()} detections
        {loading ? ' · refreshing' : ''}
      </span>
    </div>
  );
}
