import { useUiStore } from '../../store/uiStore';
import { useSevereWeatherAlerts } from './hooks/useSevereWeatherAlerts';
import type { SevereWeatherAlert } from './api/severeWeather';

/**
 * IMD severe-weather alerts as a badge/panel, per sihtodo.md item 1 — this is
 * the platform's actual answer to "any lightning alerts in my area" (the
 * cyclone tracks are a separate, distinct concern; see the `cyclones` map
 * layer and `services/cyclones.py`'s own docstring on the split). No map
 * geometry is exposed for these alerts, so a panel/badge is the right surface
 * rather than a layer — see `useSevereWeatherAlerts`.
 */
export function SevereWeatherPanel() {
  const open = useUiStore((s) => s.hazardsPanelOpen);
  const toggle = useUiStore((s) => s.toggleHazardsPanel);
  const { payload, loading, unavailableReason } = useSevereWeatherAlerts();

  const count = payload?.count ?? 0;
  const highestSeverity = highestSeverityOf(payload?.alerts ?? []);

  return (
    <div className={`severe-weather-panel ${open ? 'open' : 'collapsed'}`}>
      <button
        type="button"
        className={`severe-weather-panel__badge severe-weather-panel__badge--${severityTone(highestSeverity)}`}
        onClick={toggle}
        aria-expanded={open}
        aria-label={open ? 'Collapse severe-weather alerts' : 'Expand severe-weather alerts'}
      >
        <span className="severe-weather-panel__badge-dot" />
        {unavailableReason
          ? 'Alerts unavailable'
          : count === 0
            ? 'No active severe-weather alerts'
            : `${count} severe-weather ${count === 1 ? 'alert' : 'alerts'}`}
        {loading && <span className="severe-weather-panel__badge-loading">·</span>}
      </button>

      {open && (
        <div className="severe-weather-panel__body">
          <div className="severe-weather-panel__header">
            <h4>IMD Severe Weather</h4>
            <span className="severe-weather-panel__subtitle">
              Nationwide (India) — heavy rain, heatwave, cold wave, thunderstorm/lightning.
              Not a cyclone-track bulletin.
            </span>
          </div>

          {unavailableReason && (
            <p className="severe-weather-panel__state severe-weather-panel__state--error">
              {unavailableReason}
            </p>
          )}

          {!unavailableReason && payload && count === 0 && (
            <p className="severe-weather-panel__state">
              No IMD alert is currently within its validity window, anywhere in India.
            </p>
          )}

          {!unavailableReason && payload && count > 0 && (
            <ul className="severe-weather-panel__list">
              {payload.alerts.map((alert, index) => (
                <AlertRow key={`${alert.event}-${index}`} alert={alert} />
              ))}
            </ul>
          )}

          {payload?.source && (
            <div className="severe-weather-panel__attribution">Source: {payload.source}</div>
          )}
        </div>
      )}
    </div>
  );
}

function AlertRow({ alert }: { alert: SevereWeatherAlert }) {
  return (
    <li className={`severe-weather-panel__alert severe-weather-panel__alert--${severityTone(alert.severity)}`}>
      <div className="severe-weather-panel__alert-head">
        <span className="severe-weather-panel__alert-event">{alert.event || 'Alert'}</span>
        <span className="severe-weather-panel__alert-severity">{alert.severity || 'Unknown'}</span>
      </div>
      {alert.headline && <p className="severe-weather-panel__alert-headline">{alert.headline}</p>}
      {alert.area && <p className="severe-weather-panel__alert-area">{alert.area}</p>}
      {alert.expires && (
        <span className="severe-weather-panel__alert-expires">
          Until {new Date(alert.expires).toLocaleString()}
        </span>
      )}
    </li>
  );
}

const SEVERITY_ORDER = ['Extreme', 'Severe', 'Moderate', 'Minor'];

function highestSeverityOf(alerts: SevereWeatherAlert[]): string | null {
  let best: string | null = null;
  let bestRank = SEVERITY_ORDER.length;
  for (const alert of alerts) {
    const rank = SEVERITY_ORDER.indexOf(alert.severity);
    if (rank !== -1 && rank < bestRank) {
      bestRank = rank;
      best = alert.severity;
    }
  }
  return best;
}

function severityTone(severity: string | null | undefined): 'extreme' | 'severe' | 'moderate' | 'minor' | 'quiet' {
  switch (severity) {
    case 'Extreme':
      return 'extreme';
    case 'Severe':
      return 'severe';
    case 'Moderate':
      return 'moderate';
    case 'Minor':
      return 'minor';
    default:
      return 'quiet';
  }
}
