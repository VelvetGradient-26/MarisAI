import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AppRouter } from './router';

/**
 * Shared across the app but currently used only by the dashboard, whose
 * widgets each poll on their own cadence (see features/dashboard/hooks).
 *
 * `retry: 1` rather than the default 3: these endpoints front slow upstreams,
 * and a widget that reports "unavailable" quickly is more useful than one
 * that spins through three backoffs before saying so. Refetch-on-focus is off
 * because every query already polls on a schedule chosen per widget — tabbing
 * back should not trigger a second, unscheduled round of requests.
 */
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
      staleTime: 30_000,
    },
  },
});

/**
 * Wrap app-wide providers here as they're introduced (theme, query client).
 * Kept as a single seam so App.tsx doesn't grow a provider pyramid inline as
 * the app picks up more cross-cutting concerns.
 *
 * The auth bootstrap that used to live here — a boot-time /auth/me call plus
 * ?auth_error= drainage — went with authentication. See docs/AUTH_REMOVAL.md.
 */
export function AppProviders({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>
      <AppRouter>{children}</AppRouter>
    </QueryClientProvider>
  );
}
