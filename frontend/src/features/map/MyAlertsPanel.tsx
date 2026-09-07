import { useEffect, useState } from 'react';
import { useUiStore } from '../../store/uiStore';
import { useMyWatches } from './hooks/useMyWatches';
import type { MyWatch } from './api/watch';

/**
 * A list of this browser's own boundary-watch subscriptions — created via
 * "Watch This Location" in `SelectedLocationPanel.tsx`, but until this
 * panel there was no in-app way to see or remove one, only the emailed
 * confirm/unsubscribe links. Same badge+collapsible shape as
 * `SevereWeatherPanel`/`BoundaryWatchPanel`, and the same reasoning for why
 * it's a panel/badge rather than a map layer: a watch list isn't geometry
 * tied to the current view, it's several possibly-different locations at
 * once.
 */
export function MyAlertsPanel() {
  const open = useUiStore((s) => s.myAlertsPanelOpen);
  const toggle = useUiStore((s) => s.toggleMyAlertsPanel);
  const { watches, loading, unavailableReason, refresh, remove } = useMyWatches();

  // Refresh on open, not just on mount — catches a watch created via
  // "Watch This Location" earlier in the same session without needing a
  // poll (a watch list changes only in response to this browser's own
  // actions, never independently upstream).
  useEffect(() => {
    if (open) refresh();
  }, [open, refresh]);

  const count = watches.length;

  return (
    <div className={`my-alerts-panel ${open ? 'open' : 'collapsed'}`}>
      <button
        type="button"
        className="my-alerts-panel__badge"
        onClick={toggle}
        aria-expanded={open}
        aria-label={open ? 'Collapse my alerts' : 'Expand my alerts'}
      >
        <span className="my-alerts-panel__badge-dot" />
        {unavailableReason
          ? 'Alerts unavailable'
          : count === 0
            ? 'No saved alerts'
            : `${count} saved ${count === 1 ? 'alert' : 'alerts'}`}
        {loading && <span className="my-alerts-panel__badge-loading">·</span>}
      </button>

      {open && (
        <div className="my-alerts-panel__body">
          <div className="my-alerts-panel__header">
            <h4>My Alerts</h4>
            <span className="my-alerts-panel__subtitle">
              Boundary watches created from &quot;Watch This Location&quot; on the map.
            </span>
          </div>

          {unavailableReason && (
            <p className="my-alerts-panel__state my-alerts-panel__state--error">{unavailableReason}</p>
          )}

          {!unavailableReason && count === 0 && (
            <p className="my-alerts-panel__state">
              No watches yet. Click a point on the map and use &quot;Watch This Location&quot; to create one.
            </p>
          )}

          {!unavailableReason && count > 0 && (
            <ul className="my-alerts-panel__list">
              {watches.map((watch) => (
                <WatchRow key={watch.id} watch={watch} onRemove={remove} />
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function WatchRow({
  watch,
  onRemove,
}: {
  watch: MyWatch;
  onRemove: (watchId: string) => Promise<void>;
}) {
  const [removing, setRemoving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  return (
    <li className="my-alerts-panel__watch">
      <div className="my-alerts-panel__watch-head">
        <span className="my-alerts-panel__watch-label">{watch.label}</span>
        <span
          className={`my-alerts-panel__watch-status my-alerts-panel__watch-status--${watch.confirmed ? 'confirmed' : 'pending'}`}
        >
          {watch.confirmed ? 'confirmed' : 'pending'}
        </span>
      </div>
      <span className="my-alerts-panel__watch-meta">
        {watch.latitude.toFixed(2)}°, {watch.longitude.toFixed(2)}° · {watch.radius_km.toFixed(0)} km
        radius · created {new Date(watch.created_at).toISOString().slice(0, 10)}
      </span>
      <button
        type="button"
        className="my-alerts-panel__remove-button"
        disabled={removing}
        onClick={async () => {
          setRemoving(true);
          setError(null);
          try {
            await onRemove(watch.id);
          } catch (err) {
            setError(err instanceof Error ? err.message : 'Could not remove this watch.');
            setRemoving(false);
          }
        }}
      >
        {removing ? 'Removing…' : 'Remove'}
      </button>
      {error && <span className="my-alerts-panel__state--error">{error}</span>}
    </li>
  );
}
