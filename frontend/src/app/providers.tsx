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
 *
 * `gcTime` is the one that decides whether leaving a page costs anything.
 * React Query's default drops a query 5 minutes after its last observer
 * unmounts, and this router is a plain if/else on `pathname` — navigating to
 * /map unmounts every dashboard widget at once. Past that 5 minutes the whole
 * page refetches from scratch on return, and behind these endpoints that is
 * not a cheap round trip: a cold metric page costs ~30s of upstream history
 * fetching before a model runs. Holding the cache for the session means
 * returning to a page paints instantly from cache and revalidates behind the
 * already-visible numbers, instead of showing skeletons for half a minute.
 *
 * This is a *session* cache — it does not survive a reload, and it is not
 * meant to. The durable copy lives on the backend, which caches upstream
 * history on disk and pre-warms it on a schedule.
 */
const SESSION = 2 * 60 * 60 * 1000;

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
      staleTime: 30_000,
      gcTime: SESSION,
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
