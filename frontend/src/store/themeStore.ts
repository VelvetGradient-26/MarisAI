import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface ThemeStore {
  dark: boolean;
  toggleTheme: () => void;
}

/** One shared dark/light preference, controlled from the navbar's toggle and
 * persisted to localStorage — mirrors store/timezoneStore.ts.
 *
 * Every route now responds to it. Two layers do the work: App.tsx stamps
 * `data-theme` on <html>, which drives the shared `--ma-*` tokens in
 * styles/tokens.css (and, through `color-scheme`, the browser's own scrollbars,
 * date pickers and select popups); pages additionally read this store to put a
 * `--light` class on their own root. The map was the last holdout — its chrome
 * is themed, while the basemap deliberately is not (see map.css).
 *
 * index.html reads this same localStorage key in an inline script so the first
 * paint is already correct. If the key or the default changes, change it there
 * too. */
export const useThemeStore = create<ThemeStore>()(
  persist(
    (set) => ({
      dark: true,
      toggleTheme: () => set((s) => ({ dark: !s.dark })),
    }),
    { name: 'marisai-theme' }
  )
);
