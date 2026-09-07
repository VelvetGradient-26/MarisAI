import { useEffect, useState } from 'react';
import type { LiveVesselsState } from './hooks/useLiveVessels';
import { fetchVesselFeedStatus } from './api/vessels';
import type { VesselFeedStatusResponse } from './api/vessels';

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

  // A one-time fetch, not polled — `configured` never changes at runtime,
  // and `tracked_vessels`/`messages_seen` are a hover detail, not something
  // that needs to stay live-accurate to the second. Only fires once the
  // layer is actually on, matching every other fetch in this file's gate.
  const [feedStatus, setFeedStatus] = useState<VesselFeedStatusResponse | null>(null);
  useEffect(() => {
    if (!active) {
      setFeedStatus(null);
      return;
    }
    const controller = new AbortController();
    fetchVesselFeedStatus(controller.signal)
      .then(setFeedStatus)
      .catch(() => {
        /* silent — this only adds a hover detail and a not-configured vs
           offline distinction; the layer's own live counts stay correct
           without it. */
      });
    return () => controller.abort();
  }, [active]);

  // The layer being off is the only case with nothing to say. A connected
  // feed showing zero vessels is real information.
  if (!active) return null;

  const statusTitle =
    feedStatus &&
    `${feedStatus.tracked_vessels.toLocaleString()} vessels tracked, ${feedStatus.messages_seen.toLocaleString()} AIS messages seen this session`;

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
    // `configured === false` is a different fact than a feed that dropped —
    // one implies a server-side setup gap, the other a transient hiccup.
    return (
      <div className="vessel-feed-status vessel-feed-status--offline">
        <span className="vessel-feed-status__dot" />
        {feedStatus?.configured === false ? 'AIS feed not configured' : 'AIS feed offline'}
      </div>
    );
  }

  const thinned = totalInView > returned;

  return (
    <div className="vessel-feed-status" title={statusTitle || undefined}>
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
