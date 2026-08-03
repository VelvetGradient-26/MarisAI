import { useCallback, useEffect, useState } from 'react';
import { MapPin, Trash2 } from 'lucide-react';
import { Link } from '../app/router';
import { useAppRouter } from '../app/routerContext';
import { useAuthStore } from '../store/authStore';
import { useThemeStore } from '../store/themeStore';
import { useTimezoneStore } from '../store/timezoneStore';
import { useMapStore } from '../store/mapStore';
import { formatCompactDateTime } from '../utils/formatTime';
import {
  type SavedLocation,
  deleteSavedLocation,
  fetchSavedLocations,
} from '../features/map/api/savedLocations';
import { type DownloadHistoryEntry, fetchDownloadHistory } from '../features/map/api/download';
import './account.css';

type Tab = 'saved' | 'history';
type LoadStatus = 'idle' | 'loading' | 'success' | 'error';

/**
 * The signed-in user's own data: saved map locations and past download
 * requests. Both lists are per-user and server-side, unlike the device-scoped
 * preference stores (theme/timezone/map projection).
 *
 * Which tab is showing lives in the URL (?tab=history) rather than component
 * state, so the navbar's account menu can link straight to either one.
 */
export function AccountPage() {
  const { searchParams, navigate } = useAppRouter();
  const dark = useThemeStore((s) => s.dark);
  const status = useAuthStore((s) => s.status);
  const user = useAuthStore((s) => s.user);

  const tab: Tab = searchParams.get('tab') === 'history' ? 'history' : 'saved';

  useEffect(() => {
    document.title = 'Maris AI | Account';
  }, []);

  // The page is only meaningful signed in, and every request it makes would
  // 401. Wait for 'loading' to resolve first so a reload doesn't bounce a
  // signed-in user out before /auth/me answers.
  useEffect(() => {
    if (status === 'anonymous') navigate('/', { replace: true });
  }, [status, navigate]);

  if (status !== 'authenticated' || !user) {
    return (
      <div className={`account-page ${dark ? '' : 'account-page--light'}`}>
        <div className="account-shell">
          <p className="account-empty">
            {status === 'loading' ? 'Loading your account…' : 'Redirecting…'}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className={`account-page ${dark ? '' : 'account-page--light'}`}>
      <div className="account-shell">
        <header className="account-header">
          <div>
            <h1>{user.name}</h1>
            <p>{user.email}</p>
          </div>
        </header>

        <nav className="account-tabs" aria-label="Account sections">
          <button
            type="button"
            className={tab === 'saved' ? 'is-active' : ''}
            onClick={() => navigate('/account')}
          >
            Saved locations
          </button>
          <button
            type="button"
            className={tab === 'history' ? 'is-active' : ''}
            onClick={() => navigate('/account?tab=history')}
          >
            Download history
          </button>
        </nav>

        {tab === 'saved' ? <SavedLocationsPanel /> : <DownloadHistoryPanel />}
      </div>
    </div>
  );
}

function SavedLocationsPanel() {
  const [locations, setLocations] = useState<SavedLocation[]>([]);
  const [status, setStatus] = useState<LoadStatus>('idle');
  const [error, setError] = useState<string | null>(null);
  const focusSelectedLocation = useMapStore((s) => s.focusSelectedLocation);
  const { navigate } = useAppRouter();

  useEffect(() => {
    const controller = new AbortController();
    setStatus('loading');
    fetchSavedLocations(controller.signal)
      .then((result) => {
        setLocations(result);
        setStatus('success');
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;
        setError(cause instanceof Error ? cause.message : 'Could not load saved locations');
        setStatus('error');
      });
    return () => controller.abort();
  }, []);

  const remove = useCallback(async (id: string) => {
    // Optimistic: the row disappears immediately and is restored if the
    // request fails, rather than leaving the list frozen mid-delete.
    const previous = locations;
    setLocations((current) => current.filter((location) => location.id !== id));
    try {
      await deleteSavedLocation(id);
    } catch (cause: unknown) {
      setLocations(previous);
      setError(cause instanceof Error ? cause.message : 'Could not delete that location');
    }
  }, [locations]);

  /** Queues the map camera move, then routes to the map — the same
   * pendingFocus path the dashboard uses (see store/mapStore.ts). */
  const openOnMap = (location: SavedLocation) => {
    focusSelectedLocation({ lng: location.lon, lat: location.lat });
    navigate('/map');
  };

  if (status === 'loading') return <p className="account-empty">Loading saved locations…</p>;
  if (status === 'error') return <p className="account-error">{error}</p>;

  if (locations.length === 0) {
    return (
      <p className="account-empty">
        No saved locations yet. Click anywhere on the <Link to="/map">map</Link> and save the
        point to keep it here.
      </p>
    );
  }

  return (
    <ul className="account-list">
      {locations.map((location) => (
        <li key={location.id} className="account-row">
          <button
            type="button"
            className="account-row__main"
            onClick={() => openOnMap(location)}
            title="Show on map"
          >
            <MapPin size={16} />
            <span className="account-row__label">{location.label}</span>
            <span className="account-row__meta">
              {location.lat.toFixed(3)}, {location.lon.toFixed(3)}
            </span>
          </button>
          <button
            type="button"
            className="account-row__delete"
            onClick={() => void remove(location.id)}
            aria-label={`Delete ${location.label}`}
            title="Delete"
          >
            <Trash2 size={15} />
          </button>
        </li>
      ))}
    </ul>
  );
}

function DownloadHistoryPanel() {
  const [entries, setEntries] = useState<DownloadHistoryEntry[]>([]);
  const [status, setStatus] = useState<LoadStatus>('idle');
  const [error, setError] = useState<string | null>(null);
  const timezone = useTimezoneStore((s) => s.timezone);

  useEffect(() => {
    const controller = new AbortController();
    setStatus('loading');
    fetchDownloadHistory(controller.signal)
      .then((result) => {
        setEntries(result);
        setStatus('success');
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;
        setError(cause instanceof Error ? cause.message : 'Could not load download history');
        setStatus('error');
      });
    return () => controller.abort();
  }, []);

  if (status === 'loading') return <p className="account-empty">Loading download history…</p>;
  if (status === 'error') return <p className="account-error">{error}</p>;

  if (entries.length === 0) {
    return (
      <p className="account-empty">
        No downloads yet. Export a dataset from the{' '}
        <Link to="/download">downloader</Link> and it'll be listed here.
      </p>
    );
  }

  return (
    <div className="account-table-wrap">
      <table className="account-table">
        <thead>
          <tr>
            <th>When</th>
            <th>Area</th>
            <th>Range</th>
            <th>Variables</th>
            <th>Format</th>
            <th>Size</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((entry) => (
            <tr key={entry.id} className={entry.status === 'failed' ? 'is-failed' : ''}>
              <td>{formatCompactDateTime(entry.requestedAt, timezone)}</td>
              <td>{describeArea(entry)}</td>
              <td>
                {entry.startDate} → {entry.endDate}
              </td>
              <td title={entry.variables.join(', ')}>
                {entry.variables.length === 1
                  ? entry.variables[0]
                  : `${entry.variables.length} variables`}
              </td>
              <td>{entry.format.toUpperCase()}</td>
              <td>
                {entry.status === 'failed' ? (
                  <span className="account-failed" title={entry.errorMessage ?? undefined}>
                    Failed
                  </span>
                ) : (
                  formatBytes(entry.sizeBytes)
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function describeArea(entry: DownloadHistoryEntry): string {
  const { area } = entry;
  if (area.type === 'point') return `${area.lat.toFixed(2)}, ${area.lon.toFixed(2)}`;
  return `${area.south.toFixed(1)}…${area.north.toFixed(1)}, ${area.west.toFixed(1)}…${area.east.toFixed(1)}`;
}

function formatBytes(bytes: number | null): string {
  if (bytes === null) return '—';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
