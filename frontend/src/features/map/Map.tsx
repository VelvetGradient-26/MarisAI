import type { ReactNode } from 'react';
import { useMapManager } from './hooks/useMapManager';
import { MapManagerContext } from './hooks/MapManagerContext';
<<<<<<< HEAD
import { useGeographicLabels } from './hooks/useGeographicLabels';
=======
>>>>>>> feature/map-label
import { useSelectedLocationRealtimeData } from './hooks/useSelectedLocationRealtimeData';
import { useSelectedLocationMarker } from './hooks/useSelectedLocationMarker';

interface MapProps {
  children?: ReactNode;
}

/**
 * Mounts the map container and owns the single MapManager instance for
 * this view. Children (MapControls, CoordinateDisplay, etc.) consume that
 * instance via MapManagerContext — they never create their own.
 */
export function Map({ children }: MapProps) {
  const { containerRef, manager, ready } = useMapManager('satellite');
<<<<<<< HEAD
  useGeographicLabels(manager, ready);
=======
>>>>>>> feature/map-label
  useSelectedLocationRealtimeData();
  useSelectedLocationMarker(manager, ready);

  return (
    <div className="map-root">
      <div ref={containerRef} className="map-container" />
      {!ready && <div className="map-loading">Initializing map engine…</div>}
      {ready && <MapManagerContext.Provider value={manager}>{children}</MapManagerContext.Provider>}
    </div>
  );
}
