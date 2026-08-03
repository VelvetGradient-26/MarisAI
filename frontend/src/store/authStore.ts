import { create } from 'zustand';
import { type AuthUser, fetchCurrentUser, logout as logoutRequest } from '../features/map/api/auth';

export type AuthStatus = 'loading' | 'authenticated' | 'anonymous';

interface AuthStore {
  user: AuthUser | null;
  status: AuthStatus;
  /** Populated when the backend bounced the browser back with ?auth_error=. */
  error: string | null;
  fetchMe: () => Promise<void>;
  logout: () => Promise<void>;
  setError: (error: string | null) => void;
}

/**
 * The signed-in user, mirrored from the server.
 *
 * Deliberately NOT wrapped in `persist` like themeStore/timezoneStore are: the
 * session itself lives in an httpOnly cookie that JavaScript cannot read, so a
 * localStorage copy of the user could only ever go stale — showing someone as
 * signed in after their cookie expired. The server is the single source of
 * truth, re-read via fetchMe() on every app boot.
 */
export const useAuthStore = create<AuthStore>()((set) => ({
  user: null,
  status: 'loading',
  error: null,

  fetchMe: async () => {
    try {
      const user = await fetchCurrentUser();
      set({ user, status: user ? 'authenticated' : 'anonymous' });
    } catch {
      // A network failure or a backend without Mongo configured is not a
      // signed-in state — degrade to anonymous rather than blocking the app.
      set({ user: null, status: 'anonymous' });
    }
  },

  logout: async () => {
    try {
      await logoutRequest();
    } finally {
      // Clear locally even if the request failed; the cookie may well be gone.
      set({ user: null, status: 'anonymous' });
    }
  },

  setError: (error) => set({ error }),
}));
