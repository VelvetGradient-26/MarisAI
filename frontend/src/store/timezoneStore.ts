import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface TimezoneStore {
  timezone: string;
  setTimezone: (timezone: string) => void;
}

const browserTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone;

/** A single global timezone preference every timestamp in the app reads
 * from (see utils/formatTime.ts) — persisted to localStorage so it survives
 * a reload. Defaults to the browser's own zone rather than UTC. */
export const useTimezoneStore = create<TimezoneStore>()(
  persist(
    (set) => ({
      timezone: browserTimezone,
      setTimezone: (timezone) => set({ timezone }),
    }),
    { name: 'marisai-timezone' }
  )
);
