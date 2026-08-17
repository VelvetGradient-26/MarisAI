import type { DetectorCellsState } from './hooks/useDetectorCells';
import type { HeatwaveResponse, UpwellingResponse } from './api/detectors';

/**
 * Readouts for the two cell detectors.
 *
 * They exist for the reason the eDNA chip does, and more sharply: **a blank
 * ocean is the most likely output of either layer, and it is a result.** No
 * marine heatwave anywhere in view is a finding; no upwelling-favourable coast
 * is a finding. Without a chip stating how much water was examined, a reader
 * arriving from the SST layer reads that blankness as a failed load, and the
 * one honest thing this layer had to say is the thing they miss.
 *
 * Reuses `.eddy-status` styling rather than growing a third near-identical
 * block — these are the same object in the same corner saying the same kind of
 * thing.
 */

export function MarineHeatwaveStatus({
  state,
}: {
  state: DetectorCellsState<HeatwaveResponse>;
}) {
  const { active, payload, unavailableReason } = state;
  if (!active) return null;

  if (unavailableReason) {
    return (
      <div className="eddy-status eddy-status--unavailable">
        <span className="eddy-status__dot" />
        {unavailableReason}
      </div>
    );
  }

  if (!payload) {
    return (
      <div className="eddy-status eddy-status--unavailable">
        <span className="eddy-status__dot" />
        Detecting marine heatwaves…
      </div>
    );
  }

  const { coverage, cells, baseline } = payload;
  // The field's own timestep, not when the detector ran.
  const stamp = payload.timestamp.slice(0, 10);
  // `heatwave_fraction` is deliberately null rather than 0 when no ocean fell
  // in the aggregate band, so the percentage is only rendered when it means
  // something.
  const percent =
    coverage.heatwave_fraction === null
      ? null
      : `${(coverage.heatwave_fraction * 100).toFixed(1)}%`;

  return (
    <div className="eddy-status">
      <span className="eddy-status__dot" />
      {cells.length === 0 ? (
        <span>
          No marine heatwave detected
          {coverage.ocean_cells > 0 && ` across ${coverage.ocean_cells.toLocaleString()} ocean cells`}
        </span>
      ) : (
        <span>
          {cells.length.toLocaleString()} cells in marine heatwave
          {percent && ` — ${percent} of ocean (60°S–60°N)`}
        </span>
      )}
      <span className="eddy-status__meta">
        {stamp} · vs {baseline.start}–{baseline.end} 90th percentile · not tracked
      </span>
    </div>
  );
}

export function UpwellingStatus({
  state,
}: {
  state: DetectorCellsState<UpwellingResponse>;
}) {
  const { active, payload, unavailableReason } = state;
  if (!active) return null;

  if (unavailableReason) {
    return (
      <div className="eddy-status eddy-status--unavailable">
        <span className="eddy-status__dot" />
        {unavailableReason}
      </div>
    );
  }

  if (!payload) {
    return (
      <div className="eddy-status eddy-status--unavailable">
        <span className="eddy-status__dot" />
        Computing upwelling index…
      </div>
    );
  }

  const { coverage } = payload;
  const stamp = payload.timestamp.slice(11, 16);

  if (coverage.coastal_cells === 0) {
    return (
      <div className="eddy-status eddy-status--unavailable">
        <span className="eddy-status__dot" />
        {coverage.unavailable_reason ?? 'No coastal cells with a defined index'}
      </div>
    );
  }

  return (
    <div className="eddy-status">
      <span className="eddy-status__dot" />
      <span>
        {(coverage.upwelling_favourable_cells ?? 0).toLocaleString()} of{' '}
        {coverage.coastal_cells.toLocaleString()} coastal cells upwelling-favourable
      </span>
      <span className="eddy-status__meta">
        {stamp} · wind-derived index, not observed upwelling
      </span>
    </div>
  );
}
