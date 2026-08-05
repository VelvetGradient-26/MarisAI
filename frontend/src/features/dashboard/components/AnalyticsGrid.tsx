/** The historical analytics section.
 *
 * Charts mount lazily as they scroll into view. Each one is an independent
 * network request against an upstream point API, so mounting all ten at once
 * would fire ten simultaneous requests for charts mostly below the fold.
 */

import { useEffect, useRef, useState, type ReactNode } from 'react';
import { LineChart } from 'lucide-react';
import { useTrendsCatalog } from '../hooks/useDashboardData';
import { Panel, PanelEmpty, PanelHeader, PanelSkeleton } from './Panel';
import { TrendChart } from './TrendChart';

/** How far outside the viewport a placeholder counts as "worth mounting". */
const PRELOAD_MARGIN_PX = 200;

/**
 * Renders children once the placeholder is near the viewport.
 *
 * Deliberately does NOT rely on IntersectionObserver alone. An earlier version
 * did, and every chart stayed blank: the observer was constructed and the
 * element observed, but no callback ever arrived — verified directly, an
 * element sitting plainly inside the viewport produced no entries at all.
 * Laziness is an optimisation; correctness is not, so the geometry is measured
 * directly and the observer is only an extra trigger on top.
 *
 * A `visibility` timer would be wasteful, so re-checks are driven by scroll and
 * resize, coalesced into an animation frame.
 */
function LazyMount({ children, minHeight = 260 }: { children: ReactNode; minHeight?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const [shown, setShown] = useState(false);

  useEffect(() => {
    if (shown) return;

    let frame = 0;
    let cancelled = false;

    const isNearViewport = () => {
      const element = ref.current;
      if (!element) return false;
      const rect = element.getBoundingClientRect();
      const height = window.innerHeight || document.documentElement.clientHeight;
      return rect.top < height + PRELOAD_MARGIN_PX && rect.bottom > -PRELOAD_MARGIN_PX;
    };

    const check = () => {
      if (cancelled) return;
      if (isNearViewport()) setShown(true);
    };

    const schedule = () => {
      if (frame) return;
      frame = window.requestAnimationFrame(() => {
        frame = 0;
        check();
      });
    };

    // Measure immediately: anything already on screen must not wait for an
    // event that may never come.
    check();

    window.addEventListener('scroll', schedule, { passive: true });
    window.addEventListener('resize', schedule, { passive: true });

    let observer: IntersectionObserver | undefined;
    if (typeof IntersectionObserver !== 'undefined') {
      observer = new IntersectionObserver(
        (entries) => {
          if (entries.some((entry) => entry.isIntersecting)) setShown(true);
        },
        { rootMargin: `${PRELOAD_MARGIN_PX}px` }
      );
      if (ref.current) observer.observe(ref.current);
    }

    return () => {
      cancelled = true;
      if (frame) window.cancelAnimationFrame(frame);
      window.removeEventListener('scroll', schedule);
      window.removeEventListener('resize', schedule);
      observer?.disconnect();
    };
  }, [shown]);

  return (
    <div ref={ref} style={{ minHeight }}>
      {shown ? children : null}
    </div>
  );
}

export function AnalyticsGrid({
  latitude,
  longitude,
}: {
  latitude: number;
  longitude: number;
}) {
  const { data, isPending, isError, error, refetch } = useTrendsCatalog();

  if (isPending) {
    return (
      <Panel>
        <PanelHeader icon={<LineChart size={15} />} title="Historical analytics" />
        <PanelSkeleton rows={4} />
      </Panel>
    );
  }

  if (isError || !data) {
    return (
      <Panel>
        <PanelHeader icon={<LineChart size={15} />} title="Historical analytics" />
        <PanelEmpty
          title="Chart catalog unavailable"
          reason={error instanceof Error ? error.message : undefined}
          onRetry={() => void refetch()}
        />
      </Panel>
    );
  }

  // Chartable variables first; the ones with no time-series source still
  // render, explaining themselves rather than silently disappearing.
  const variables = [...data.variables].sort(
    (a, b) => Number(b.available) - Number(a.available)
  );

  return (
    <section aria-label="Historical analytics">
      <header className="mb-3 flex items-baseline justify-between gap-3">
        <div>
          <h2 className="text-[13px] font-semibold tracking-wide text-[color:var(--oid-text-strong)] uppercase">
            Historical analytics
          </h2>
          <p className="mt-0.5 text-[11px] text-[color:var(--oid-text-faint)]">
            Point series at {latitude.toFixed(2)}°, {longitude.toFixed(2)}° · ranges reflect
            each product’s real coverage
          </p>
        </div>
      </header>

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2 2xl:grid-cols-3">
        {variables.map((variable) => (
          <LazyMount key={variable.key}>
            <TrendChart
              variable={variable}
              ranges={data.ranges}
              latitude={latitude}
              longitude={longitude}
            />
          </LazyMount>
        ))}
      </div>
    </section>
  );
}
