import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface ThemeStore {
  dark: boolean;
  toggleTheme: () => void;
}

/** One shared dark/light preference, controlled from the navbar's toggle and
 * persisted to localStorage — mirrors store/timezoneStore.ts. Only Landing
 * and Dashboard currently render differently per theme; other pages simply
 * don't read from this store, so the toggle is a no-op there. */
export const useThemeStore = create<ThemeStore>()(
  persist(
    (set) => ({
      dark: true,
      toggleTheme: () => set((s) => ({ dark: !s.dark })),
    }),
    { name: 'marisai-theme' }
  )
);
