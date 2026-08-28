import { useUiStore } from '../../store/uiStore';
import { useBoundaryWatchStore, type BoundaryEvent } from '../../store/boundaryWatchStore';
import { useBoundaryWatch } from './hooks/useBoundaryWatch';

/**
 * "Notifications when approaching a maritime boundary" (sihtodo.md item 9),
 * from the device's own live position — see `useBoundaryWatch`'s docstring
 * for why this needed no new backend surface. Badge + panel, same convention
 * as `SevereWeatherPanel`: collapsed by default (most visits have nothing to
 * report), the badge alone still shows a live alert count.
 *
 * Unlike the severe-weather badge, the badge here is *only* the open/
 * collapse toggle — starting/stopping position tracking is its own button
 * inside the expanded body, since those are two different actions a user
 * makes at different times (opt in once, then just glance at the badge).
 */
export function BoundaryWatchPanel() {
  useBoundaryWatch();

  const open = useUiStore((s) => s.boundaryWatchPanelOpen);
  const toggleOpen = useUiStore((s) => s.toggleBoundaryWatchPanel);

  const enabled = useBoundaryWatchStore((s) => s.enabled);
  const status = useBoundaryWatchStore((s) => s.status);
  const unavailableReason = useBoundaryWatchStore((s) => s.unavailableReason);
  const events = useBoundaryWatchStore((s) => s.events);
  const enable = useBoundaryWatchStore((s) => s.enable);
  const disable = useBoundaryWatchStore((s) => s.disable);

  const badgeTone = status === 'error' ? 'error' : events.length > 0 ? 'alert' : 'quiet';

  return (
    <div className={`boundary-watch-panel ${open ? 'open' : 'collapsed'}`}>
      <button
        type="button"
        className={`boundary-watch-panel__badge boundary-watch-panel__badge--${badgeTone}`}
        onClick={toggleOpen}
        aria-expanded={open}
        aria-label={open ? 'Collapse boundary watch' : 'Expand boundary watch'}
      >
        <span className="boundary-watch-panel__badge-dot" />
        {!enabled && 'Boundary watch off'}
        {enabled && status === 'error' && 'Location error'}
        {enabled &&
          status !== 'error' &&
          (events.length === 0
            ? 'Tracking — no boundary alerts'
            : `${events.length} boundary ${events.length === 1 ? 'alert' : 'alerts'}`)}
      </button>

      {open && (
        <div className="boundary-watch-panel__body">
          <div className="boundary-watch-panel__header">
            <h4>Boundary Watch</h4>
            <span className="boundary-watch-panel__subtitle">
              Warns when your device's own position approaches or crosses India's EEZ, the
              India-Sri Lanka boundary, or a Marine Protected Area. Uses this browser's location,
              not a fleet-tracking feed.
            </span>
          </div>

          <button
            type="button"
            className="boundary-watch-panel__toggle-button"
            onClick={() => (enabled ? disable() : enable())}
          >
            {enabled ? 'Stop tracking' : 'Start tracking my position'}
          </button>

          {unavailableReason && (
            <p className="boundary-watch-panel__state boundary-watch-panel__state--error">
              {unavailableReason}
            </p>
          )}

          {enabled && !unavailableReason && events.length === 0 && (
            <p className="boundary-watch-panel__state">No boundary alerts yet.</p>
          )}

          {events.length > 0 && (
            <ul className="boundary-watch-panel__list">
              {events.map((event) => (
                <EventRow key={event.id} event={event} />
              ))}
            </ul>
          )}

          <div className="boundary-watch-panel__attribution">
            EEZ/boundary geometry is real (Marine Regions, the India-Sri Lanka treaty line);
            Marine Protected Areas are a hand-curated list, not a surveyed footprint. Not for
            actual navigation.
          </div>
        </div>
      )}
    </div>
  );
}

function EventRow({ event }: { event: BoundaryEvent }) {
  return (
    <li className={`boundary-watch-panel__alert boundary-watch-panel__alert--${event.type}`}>
      <span className="boundary-watch-panel__alert-message">{event.message}</span>
      <span className="boundary-watch-panel__alert-time">
        {new Date(event.at).toLocaleTimeString()}
      </span>
    </li>
  );
}
