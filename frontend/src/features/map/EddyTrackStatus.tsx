import type { EddyTracksState } from './hooks/useEddyTracks';

/**
 * Small readout for the eddy-track layer — same reasoning as
 * `EddyDetectionStatus`, and the same "cold tracker vs. quiet ocean"
 * distinction, but for tracking state rather than a live detection: this
 * reads a background job's own in-process state
 * (`services/eddy_tracking.py`), which is `active_tracks: 0` both right
 * after a server restart and on a genuinely quiet ocean — real, reportable
 * answers either way, never substituted for.
 */
export function EddyTrackStatus({ state }: { state: EddyTracksState }) {
  const { active, tracks, loading, unavailableReason } = state;
  if (!active) return null;

  if (unavailableReason) {
    return (
      <div className="eddy-status eddy-status--unavailable">
        <span className="eddy-status__dot" />
        {unavailableReason}
      </div>
    );
  }

  if (!tracks) {
    return (
      <div className="eddy-status eddy-status--unavailable">
        <span className="eddy-status__dot" />
        Loading eddy tracks…
      </div>
    );
  }

  const shown = tracks.returned;
  const capped = tracks.matched > tracks.returned;
  const stamp = tracks.last_processed_timestamp
    ? tracks.last_processed_timestamp.slice(11, 16)
    : null;

  return (
    <div className="eddy-status">
      <span className="eddy-status__dot eddy-status__dot--live" />
      {shown === 0
        ? 'No eddy tracks in view'
        : `${shown.toLocaleString()} ${shown === 1 ? 'track' : 'tracks'}`}
      {capped && (
        <span className="eddy-status__note" title="Longest-established first; zoom in for the rest">
          of {tracks.matched.toLocaleString()}
        </span>
      )}
      <span className="eddy-status__note">
        {stamp ? `${stamp} UTC` : 'not yet processed'}
        {loading ? ' · refreshing' : ''}
      </span>
    </div>
  );
}
