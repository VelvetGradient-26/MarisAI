import { Component } from 'react';
import type { ErrorInfo, ReactNode } from 'react';

/**
 * Catches render errors so one broken component cannot white-screen the app.
 *
 * There was no boundary anywhere before this, which meant any throw during
 * render — a malformed API payload reaching a chart, a lazy chunk failing to
 * load on a flaky network — replaced the entire page with a blank document and
 * the only recovery was a manual reload.
 *
 * Two deliberate choices:
 *
 * * **It resets on navigation.** A boundary that latches means one bad page
 *   poisons the session; `resetKey` lets the caller re-mount the subtree when
 *   the route changes, so navigating away actually recovers.
 * * **It shows the error text.** Hiding the message behind "something went
 *   wrong" is friendlier to nobody here — this app is operated by the people
 *   who build it, and the message is the first thing anyone needs.
 */

interface ErrorBoundaryProps {
  children: ReactNode;
  /** Changing this value re-mounts the subtree and clears the error. */
  resetKey?: string;
  /** Human label for where the failure happened, e.g. "the map". */
  label?: string;
}

interface ErrorBoundaryState {
  error: Error | null;
  previousResetKey?: string;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): Partial<ErrorBoundaryState> {
    return { error };
  }

  static getDerivedStateFromProps(
    props: ErrorBoundaryProps,
    state: ErrorBoundaryState,
  ): Partial<ErrorBoundaryState> | null {
    if (props.resetKey !== state.previousResetKey) {
      return { error: null, previousResetKey: props.resetKey };
    }
    return null;
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Console rather than a reporting service: there is no error backend, and
    // swallowing this silently would be worse than a noisy log.
    console.error(`[ErrorBoundary${this.props.label ? ` · ${this.props.label}` : ''}]`, error, info.componentStack);
  }

  private reload = () => {
    window.location.reload();
  };

  private dismiss = () => {
    this.setState({ error: null });
  };

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;

    return (
      <div className="app-error" role="alert">
        <div className="app-error__panel">
          <p className="app-error__eyebrow">Something broke</p>
          <h1 className="app-error__title">
            {this.props.label ? `${this.props.label} failed to render.` : 'This view failed to render.'}
          </h1>
          <p className="app-error__body">
            The rest of the app is still running — navigating elsewhere should work.
          </p>
          <pre className="app-error__detail">{error.message || String(error)}</pre>
          <div className="app-error__actions">
            <button type="button" className="app-error__button" onClick={this.dismiss}>
              Try again
            </button>
            <button
              type="button"
              className="app-error__button app-error__button--ghost"
              onClick={this.reload}
            >
              Reload page
            </button>
          </div>
        </div>
      </div>
    );
  }
}
