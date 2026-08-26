import { create } from 'zustand';

interface UiStore {
  controlPanelOpen: boolean;
  toggleControlPanel: () => void;
  selectedLocationPanelOpen: boolean;
  toggleSelectedLocationPanel: () => void;
  hazardsPanelOpen: boolean;
  toggleHazardsPanel: () => void;
}

/** UI chrome state that has nothing to do with the map itself, kept in its
 * own store so it doesn't grow into mapStore as the app gains more panels,
 * modals, and settings. */
export const useUiStore = create<UiStore>((set) => ({
  controlPanelOpen: true,
  toggleControlPanel: () => set((s) => ({ controlPanelOpen: !s.controlPanelOpen })),
  selectedLocationPanelOpen: true,
  toggleSelectedLocationPanel: () =>
    set((s) => ({ selectedLocationPanelOpen: !s.selectedLocationPanelOpen })),
  // Starts collapsed: unlike the location panel (opened by an explicit map
  // click), this appears unprompted on every visit, and most visits have
  // nothing to report — a badge with a count is enough until there is.
  hazardsPanelOpen: false,
  toggleHazardsPanel: () => set((s) => ({ hazardsPanelOpen: !s.hazardsPanelOpen })),
}));
