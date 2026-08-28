import type { CyclonesState } from './hooks/useCyclones';

/**
 * Small readout for the cyclone layer, mirroring `EddyDetectionStatus`: how
 * many storms are drawn worldwide, or why there are none — a quiet ocean and
 * a cold GDACS fetch are different answers.
 */
export function CycloneStatus({ state }: { state: CyclonesState }) {
  const { active, detection, loading, unavailableReason } = state;
  if (!active) return null;

  if (unavailableReason) {
    return (
      <div className="eddy-status eddy-status--unavailable">
        <span className="eddy-status__dot" />
        {unavailableReason}
      </div>
    );
  }

  if (!detection) {
    return (
      <div className="eddy-status eddy-status--unavailable">
        <span className="eddy-status__dot" />
        Loading active cyclones…
      </div>
    );
  }

  return (
    <div className="eddy-status">
      <span className="eddy-status__dot eddy-status__dot--live" />
      {detection.count === 0
        ? 'No active tropical cyclones worldwide'
        : `${detection.count} active tropical ${detection.count === 1 ? 'cyclone' : 'cyclones'} worldwide`}
      <span className="eddy-status__note">
        GDACS{loading ? ' · refreshing' : ''}
      </span>
    </div>
  );
}
