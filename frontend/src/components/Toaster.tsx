import { useEffect } from 'react';
import { Check, Loader2, TriangleAlert, X } from 'lucide-react';
import { useToastStore, type Toast } from '../store/toastStore';
import './toast.css';

/** How long a toast stays up, by tone.
 *
 *  `pending` never expires on its own — it is cleared by whatever it is
 *  reporting on, and a download can legitimately take 30s+.
 *  `error` never expires either: it carries a provider message the user may
 *  need to read twice or copy, and dismissing it is the only way to be sure
 *  they saw it. Only success is transient. */
const DURATIONS: Record<Toast['tone'], number | null> = {
  pending: null,
  success: 5000,
  error: null,
};

/**
 * Renders the toast region. Mounted once in App.tsx, outside the route
 * ErrorBoundary — a toast reporting that something failed must survive the
 * page that failed.
 */
export function Toaster() {
  const toasts = useToastStore((state) => state.toasts);

  if (toasts.length === 0) return null;

  return (
    <div className="toaster">
      {toasts.map((toast) => (
        <ToastRow key={toast.id} toast={toast} />
      ))}
    </div>
  );
}

/**
 * The bar under a pending toast.
 *
 * Two modes, and the distinction is the point. With a known fraction it fills
 * to it; with none it sweeps, which says "working, extent unknown" instead of
 * asserting a position. The download reports real stage progress, but there is
 * a genuine window at the start — between the request leaving the browser and
 * the server registering it — where nothing is known yet, and a bar that
 * started at a confident 5% would be making that number up.
 *
 * Never animates backwards: `progress` is clamped and the width transition is
 * one-directional in practice because the backend's fraction is monotonic.
 */
function ToastProgress({ value }: { value?: number }) {
  const determinate = typeof value === 'number' && Number.isFinite(value);
  const pct = determinate ? Math.min(100, Math.max(0, value * 100)) : 0;

  return (
    <div
      className={`toast__progress${determinate ? '' : ' toast__progress--indeterminate'}`}
      role="progressbar"
      aria-label="Download progress"
      // Omitting aria-valuenow is what marks a progressbar as indeterminate to
      // assistive tech; a 0 here would be read as "0 percent, and stuck".
      {...(determinate
        ? { 'aria-valuenow': Math.round(pct), 'aria-valuemin': 0, 'aria-valuemax': 100 }
        : {})}
    >
      <div
        className="toast__progress-fill"
        style={determinate ? { width: `${pct}%` } : undefined}
      />
    </div>
  );
}

function ToastRow({ toast }: { toast: Toast }) {
  const dismiss = useToastStore((state) => state.dismiss);

  useEffect(() => {
    const duration = DURATIONS[toast.tone];
    if (duration === null) return;
    const timer = window.setTimeout(() => dismiss(toast.id), duration);
    return () => window.clearTimeout(timer);
    // Keyed on tone as well: a `pending` toast that becomes `success` in place
    // needs its timer to start at that moment, not at mount.
  }, [toast.id, toast.tone, dismiss]);

  const Icon = toast.tone === 'success' ? Check : toast.tone === 'error' ? TriangleAlert : Loader2;

  return (
    <div
      className={`toast toast--${toast.tone}`}
      // Assertive for errors so a screen reader interrupts; polite otherwise,
      // because a success does not need to cut across what is being read.
      role={toast.tone === 'error' ? 'alert' : 'status'}
      aria-live={toast.tone === 'error' ? 'assertive' : 'polite'}
    >
      <Icon
        size={16}
        className={`toast__icon${toast.tone === 'pending' ? ' toast__icon--spin' : ''}`}
        aria-hidden="true"
      />
      <div className="toast__content">
        <p className="toast__title">{toast.title}</p>
        {toast.detail && <p className="toast__detail">{toast.detail}</p>}
        {toast.tone === 'pending' && <ToastProgress value={toast.progress} />}
      </div>
      <button
        type="button"
        className="toast__dismiss"
        onClick={() => dismiss(toast.id)}
        aria-label="Dismiss notification"
      >
        <X size={14} aria-hidden="true" />
      </button>
    </div>
  );
}
