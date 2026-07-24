import type { ReactNode } from 'react';

/**
 * Wrap app-wide providers here as they're introduced (theme, query client,
 * auth). Kept as a single seam so App.tsx doesn't grow a provider pyramid
 * inline as the app picks up more cross-cutting concerns.
 */
export function AppProviders({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
