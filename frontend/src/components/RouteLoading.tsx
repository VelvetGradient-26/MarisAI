/**
 * The full-page fallback for a lazy route chunk.
 *
 * Promoted out of `App.tsx`, where the same `<div className="app-route-loading">`
 * was written nine times with nine different labels. That was fine while the
 * markup was one element; the ping mark needs four, and four elements copied
 * nine times is how a loading state ends up subtly different on one route.
 *
 * The styling and the reasoning behind the mark are in `index.css` — it is
 * entirely presentational, and the only thing this file decides is that the
 * label is required. It is required because "loading" alone is the least
 * useful thing a wait can say: the map chunk and the dashboard chunk take
 * visibly different amounts of time, and naming which one is in flight is the
 * difference between a pause and a mystery.
 */
export function RouteLoading({ label }: { label: string }) {
  return (
    <div className="app-route-loading" role="status" aria-live="polite">
      <div className="app-route-loading__ping" aria-hidden="true">
        <span className="app-route-loading__ring" />
        <span className="app-route-loading__ring" />
        <span className="app-route-loading__ring" />
      </div>
      {label}
    </div>
  );
}
