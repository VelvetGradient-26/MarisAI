import { useEffect, useState } from 'react';
import { useAppRouter } from '../app/routerContext';
import { unsubscribeWatch } from '../features/map/api/watch';
import { useThemeStore } from '../store/themeStore';
import './watch.css';

type Status = 'loading' | 'success' | 'error';

/** Reached from the unsubscribe link every alert email carries (sihtodo.md
 * item 8) — a signed token independent of `client_id`, so this works from
 * any device, not just the one that created the watch. */
export function UnsubscribeWatchPage() {
  const isDark = useThemeStore((s) => s.dark);
  const { searchParams } = useAppRouter();
  const token = searchParams.get('token') ?? '';
  const [status, setStatus] = useState<Status>('loading');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    document.title = 'Maris AI | Unsubscribe';
  }, []);

  useEffect(() => {
    if (!token) {
      setStatus('error');
      setError('This link is missing its unsubscribe token.');
      return;
    }
    const controller = new AbortController();
    unsubscribeWatch(token, controller.signal)
      .then(() => setStatus('success'))
      .catch((err) => {
        if (controller.signal.aborted) return;
        setStatus('error');
        setError(err instanceof Error ? err.message : 'Could not remove this watch.');
      });
    return () => controller.abort();
  }, [token]);

  return (
    <div className={`watch-page ${isDark ? '' : 'watch-page--light'}`}>
      <div className="watch-card">
        <h1>Unsubscribe from alerts</h1>
        {status === 'loading' && <p>Removing…</p>}
        {status === 'success' && <p className="watch-success">You won't get any more alerts for this location.</p>}
        {status === 'error' && (
          <p className="watch-error">{error ?? 'This unsubscribe link is invalid or has expired.'}</p>
        )}
      </div>
    </div>
  );
}
