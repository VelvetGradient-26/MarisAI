import { lazy, Suspense, useEffect, useRef, useState } from 'react';
import { useThemeStore } from '../../store/themeStore';

/**
 * The aurora wash behind the closing section.
 *
 * **Why this wrapper exists rather than rendering `<Aurora />` directly.**
 *
 * `Aurora` is a WebGL component: mounting it creates a GL context and starts a
 * `requestAnimationFrame` loop that runs for as long as it is mounted. This
 * page already owns a canvas — `HeroField` — at the top, and the closing
 * section is several viewports below it. Rendering both eagerly means two live
 * GL contexts and two render loops for a page where only one is ever on screen.
 *
 * So the component is code-split *and* gated on scroll: `ogl` is not in the
 * initial bundle, and the context is not created until the section is close to
 * view. Browsers also cap simultaneous GL contexts (and drop the oldest when
 * the cap is hit), which is a real way to lose the hero's canvas on a long
 * page.
 *
 * Visibility is measured from geometry with the observer as an extra trigger,
 * matching `useScrollReveal` and `AnalyticsGrid` — an `IntersectionObserver`
 * has twice failed to fire in this app. Here the failure is benign (no
 * backdrop) rather than wrong, but the cheap version is also the consistent
 * one.
 */
const Aurora = lazy(() => import('../../components/reactbits/Aurora/Aurora'));

/** Mount once the section is within this many viewport heights of the fold. */
const PRELOAD_MARGIN = 0.5;

export function ClosingBackdrop() {
  const dark = useThemeStore((s) => s.dark);
  const ref = useRef<HTMLDivElement>(null);
  const [near, setNear] = useState(false);

  useEffect(() => {
    if (near) return;
    const element = ref.current;
    if (!element) return;

    let done = false;
    const check = () => {
      if (done || !ref.current) return;
      const rect = ref.current.getBoundingClientRect();
      const viewport = window.innerHeight || 800;
      if (rect.top < viewport * (1 + PRELOAD_MARGIN) && rect.bottom > -viewport * PRELOAD_MARGIN) {
        done = true;
        setNear(true);
      }
    };

    check();
    window.addEventListener('scroll', check, { passive: true });
    window.addEventListener('resize', check);
    const observer =
      typeof IntersectionObserver !== 'undefined'
        ? new IntersectionObserver((entries) => entries.some((e) => e.isIntersecting) && check(), {
            rootMargin: `${Math.round(PRELOAD_MARGIN * 100)}% 0px`,
          })
        : null;
    observer?.observe(element);

    return () => {
      done = true;
      window.removeEventListener('scroll', check);
      window.removeEventListener('resize', check);
      observer?.disconnect();
    };
  }, [near]);

  // A shader that animates forever is exactly what "reduce motion" is asking
  // about. There is no finished state to resolve to here — the honest
  // resolution is no backdrop at all, which the section is designed to survive
  // (it has its own background).
  const reduce =
    typeof window !== 'undefined' &&
    window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true;

  return (
    <div className="lp-closing__backdrop" ref={ref} aria-hidden="true">
      {near && !reduce && (
        <Suspense fallback={null}>
          <Aurora
            // Cyan through teal — the shared accent and the dashboard's second
            // hue, so the wash belongs to this product rather than to the
            // component's demo. Light mode gets a paler pair, since the
            // section's ground is near-white there.
            colorStops={dark ? ['#0b3d54', '#4fd1ff', '#38e0d0'] : ['#bfe9f5', '#4fd1ff', '#7fe3d8']}
            amplitude={dark ? 0.9 : 0.6}
            blend={0.6}
          />
        </Suspense>
      )}
    </div>
  );
}
