import type { EddiesState } from './hooks/useEddies';

/**
 * Small readout for the eddy layer: how many features are drawn, when the
 * field they came from was current, or why there is nothing.
 *
 * It exists for the same reason the vessel chip does, and more sharply: an
 * empty eddy layer is indistinguishable from an ocean with no eddies in it,
 * and this codebase's rule is that a missing number never gets substituted
 * for. "Detector warming up" and "no eddies in view" are different answers.
 */
export function EddyDetectionStatus({ state }: { state: EddiesState }) {
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
        Detecting eddies…
      </div>
    );
  }

  const shown = detection.returned;
  const capped = detection.matched > detection.returned;
  // The field's own timestep, not when the detector ran — the detector reads a
  // cache, so its own clock would overstate how current the ocean is.
  const stamp = detection.timestamp.slice(11, 16);

  return (
    <div className="eddy-status">
      <span className="eddy-status__dot eddy-status__dot--live" />
      {shown === 0
        ? 'No eddies detected in view'
        : `${shown.toLocaleString()} ${shown === 1 ? 'eddy' : 'eddies'}`}
      {capped && (
        <span className="eddy-status__note" title="Strongest first; zoom in for the rest">
          of {detection.matched.toLocaleString()}
        </span>
      )}
      <span className="eddy-status__note">
        {stamp} UTC{loading ? ' · refreshing' : ''}
      </span>
    </div>
  );
}
