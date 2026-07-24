import { create } from 'zustand';

interface UiStore {
  controlPanelOpen: boolean;
  toggleControlPanel: () => void;
}

/** UI chrome state that has nothing to do with the map itself, kept in its
 * own store so it doesn't grow into mapStore as the app gains more panels,
 * modals, and settings. */
export const useUiStore = create<UiStore>((set) => ({
  controlPanelOpen: true,
  toggleControlPanel: () => set((s) => ({ controlPanelOpen: !s.controlPanelOpen })),
}));
