import { useEffect, type ReactNode } from 'react';
import { AppRouter } from './router';
import { useAuthStore } from '../store/authStore';

/**
 * Wrap app-wide providers here as they're introduced (theme, query client,
 * auth). Kept as a single seam so App.tsx doesn't grow a provider pyramid
 * inline as the app picks up more cross-cutting concerns.
 */
export function AppProviders({ children }: { children: ReactNode }) {
  return (
    <AppRouter>
      <AuthBootstrap />
      {children}
    </AppRouter>
  );
}

/**
 * Resolves who's signed in, once, on boot. The session lives in an httpOnly
 * cookie the browser sends automatically, so the only way to learn the user's
 * identity is to ask the server — hence a fetch rather than a store rehydrate.
 *
 * Also drains the ?auth_error= that /api/v1/auth/callback redirects back with
 * when sign-in fails, stripping it from the URL so a reload doesn't resurrect
 * a stale message.
 */
function AuthBootstrap() {
  const fetchMe = useAuthStore((s) => s.fetchMe);
  const setError = useAuthStore((s) => s.setError);

  useEffect(() => {
    void fetchMe();

    const params = new URLSearchParams(window.location.search);
    const authError = params.get('auth_error');
    if (authError) {
      setError(authError);
      params.delete('auth_error');
      const query = params.toString();
      window.history.replaceState(
        null,
        '',
        window.location.pathname + (query ? `?${query}` : '')
      );
    }
  }, [fetchMe, setError]);

  return null;
}
