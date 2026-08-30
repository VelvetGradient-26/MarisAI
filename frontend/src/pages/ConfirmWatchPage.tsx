import { useEffect, useState } from 'react';
import { useAppRouter } from '../app/routerContext';
import { confirmWatch } from '../features/map/api/watch';
import { useThemeStore } from '../store/themeStore';
import './watch.css';

type Status = 'loading' | 'success' | 'error';

/** Reached from the confirm link in a watch's confirmation email — the
 * double-opt-in half of sihtodo.md item 8. Auto-fires on mount rather than
 * waiting for a form submit, since there is nothing for the visitor to fill
 * in; the token in the URL is the whole payload. */
export function ConfirmWatchPage() {
  const isDark = useThemeStore((s) => s.dark);
  const { searchParams } = useAppRouter();
  const token = searchParams.get('token') ?? '';
  const [status, setStatus] = useState<Status>('loading');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    document.title = 'Maris AI | Confirm Watch';
  }, []);

  useEffect(() => {
    if (!token) {
      setStatus('error');
      setError('This link is missing its confirmation token.');
      return;
    }
    const controller = new AbortController();
    confirmWatch(token, controller.signal)
      .then(() => setStatus('success'))
      .catch((err) => {
        if (controller.signal.aborted) return;
        setStatus('error');
        setError(err instanceof Error ? err.message : 'Could not confirm this watch.');
      });
    return () => controller.abort();
  }, [token]);

  return (
    <div className={`watch-page ${isDark ? '' : 'watch-page--light'}`}>
      <div className="watch-card">
        <h1>Confirm alert watch</h1>
        {status === 'loading' && <p>Confirming…</p>}
        {status === 'success' && (
          <p className="watch-success">
            Confirmed — you'll get an email if adverse weather, a cyclone, or harmful algal bloom
            risk appears at this location.
          </p>
        )}
        {status === 'error' && (
          <p className="watch-error">{error ?? 'This confirmation link is invalid or has expired.'}</p>
        )}
      </div>
    </div>
  );
}
