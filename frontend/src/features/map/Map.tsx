import type { ReactNode } from 'react';
import { useMapManager } from './hooks/useMapManager';
import { MapManagerContext } from './hooks/MapManagerContext';
import { useSelectedLocationRealtimeData } from './hooks/useSelectedLocationRealtimeData';
import { useSelectedLocationMarker } from './hooks/useSelectedLocationMarker';
import { useSelectedLocationFocus } from './hooks/useSelectedLocationFocus';
import { useLiveVessels } from './hooks/useLiveVessels';
import { VesselTooltip } from './VesselTooltip';
import { VesselFeedStatus } from './VesselFeedStatus';

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
  useSelectedLocationRealtimeData();
  useSelectedLocationMarker(manager, ready);
  useSelectedLocationFocus(manager, ready);
  const vessels = useLiveVessels(manager, ready);

  return (
    <div className="map-root">
      <div ref={containerRef} className="map-container" />
      {!ready && <div className="map-loading">Initializing map engine…</div>}
      {ready && <MapManagerContext.Provider value={manager}>{children}</MapManagerContext.Provider>}
      {/* Outside the context provider: both are driven by the hook above
          rather than by a child reaching for the manager itself. */}
      {ready && <VesselFeedStatus state={vessels} />}
      {ready && vessels.hovered && <VesselTooltip hovered={vessels.hovered} />}
    </div>
  );
}
