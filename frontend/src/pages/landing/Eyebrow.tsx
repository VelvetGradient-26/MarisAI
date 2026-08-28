import type { ReactNode } from 'react';

/**
 * A numbered eyebrow, shared by every landing-page chapter (including
 * `MapDescent`, which is why this lives in its own module rather than inside
 * `LandingPage.tsx`).
 *
 * The ordinal is passed rather than derived, because the chapters are
 * separate components rendered in a fixed order and an auto-incrementing
 * counter would mean either a context or an index prop threaded through
 * every one of them — more machinery than the literals it replaces. If a
 * chapter is reordered, renumber every `index` prop on the page; the numbers
 * are part of the copy.
 */
export function Eyebrow({ index, children }: { index: string; children: ReactNode }) {
  return (
    <p className="lp-eyebrow">
      <span className="lp-eyebrow__index" aria-hidden="true">
        {index}
      </span>
      {children}
    </p>
  );
}
