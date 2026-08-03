import type { LiveVesselsState } from './hooks/useLiveVessels';

/**
 * Small readout for the live vessel layer: how many are shown, and whether
 * the upstream feed is actually connected.
 *
 * Worth its own indicator because an empty vessel layer is ambiguous — it
 * could mean "no ships in this stretch of ocean" or "the feed is down", and
 * those deserve different reactions from the viewer. It renders nothing at
 * all when the layer is off.
 */
export function VesselFeedStatus({ state }: { state: LiveVesselsState }) {
  const { active, connected, totalInView, returned, loading } = state;

  // The layer being off is the only case with nothing to say. A connected
  // feed showing zero vessels is real information.
  if (!active) return null;

  // Still waiting on the first response — claiming "offline" here would be
  // wrong, since nothing has come back yet either way.
  if (loading && totalInView === 0 && !connected) {
    return (
      <div className="vessel-feed-status vessel-feed-status--offline">
        <span className="vessel-feed-status__dot" />
        Connecting to AIS feed…
      </div>
    );
  }

  if (!connected && totalInView === 0) {
    return (
      <div className="vessel-feed-status vessel-feed-status--offline">
        <span className="vessel-feed-status__dot" />
        AIS feed offline
      </div>
    );
  }

  const thinned = totalInView > returned;

  return (
    <div className="vessel-feed-status">
      <span className="vessel-feed-status__dot vessel-feed-status__dot--live" />
      {thinned
        ? `${returned.toLocaleString()} of ${totalInView.toLocaleString()} vessels`
        : `${totalInView.toLocaleString()} ${totalInView === 1 ? 'vessel' : 'vessels'}`}
      {thinned && (
        <span className="vessel-feed-status__note" title="Zoom in to see every vessel in view">
          zoom in for all
        </span>
      )}
    </div>
  );
}
