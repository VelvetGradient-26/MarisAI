import { createContext, useContext } from 'react';
import type { MapManager } from '../managers/MapManager';

export const MapManagerContext = createContext<MapManager | null>(null);

export function useMapManagerContext(): MapManager | null {
  return useContext(MapManagerContext);
}
