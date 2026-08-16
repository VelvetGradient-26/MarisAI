import type { ReactNode } from 'react';
import { useMapManager } from './hooks/useMapManager';
import { MapManagerContext } from './hooks/MapManagerContext';
import { useSelectedLocationRealtimeData } from './hooks/useSelectedLocationRealtimeData';
import { useSelectedLocationMarker } from './hooks/useSelectedLocationMarker';
import { useSelectedLocationFocus } from './hooks/useSelectedLocationFocus';
import { useClickDive } from './hooks/useClickDive';
import { useLiveVessels } from './hooks/useLiveVessels';
import { useEddies } from './hooks/useEddies';
import { useEdnaCoverage } from './hooks/useEdnaCoverage';
import { useForecastGridLayers } from './hooks/useForecastGridLayers';
import { useForecastVectorLayers } from './hooks/useForecastVectorLayers';
import { VesselTooltip } from './VesselTooltip';
import { VesselFeedStatus } from './VesselFeedStatus';
import { EddyTooltip } from './EddyTooltip';
import { EddyDetectionStatus } from './EddyDetectionStatus';
import { EdnaTooltip } from './EdnaTooltip';
import { EdnaCoverageStatus } from './EdnaCoverageStatus';

interface MapProps {
  children?: ReactNode;
}

/**
 * Mounts the map container and owns the single MapManager instance for
 * this view. Children (MapControls, CoordinateDisplay, etc.) consume that
 * instance via MapManagerContext — they never create their own.
 */
export function Map({ children }: MapProps) {
  const { containerRef, manager, ready } = useMapManager('abyss');
  useSelectedLocationRealtimeData();
  useSelectedLocationMarker(manager, ready);
  useSelectedLocationFocus(manager, ready);
  // Clicking a point descends onto it, on both the flat map and the globe.
  // This replaces `useGlobeClickRecenter`, which rotated only; see the hook
  // for how it answers the "do not yank the camera" objection rather than
  // ignoring it.
  useClickDive(manager, ready);
  const vessels = useLiveVessels(manager, ready);
  const eddies = useEddies(manager, ready);
  const edna = useEdnaCoverage(manager, ready);
  // Registered at runtime rather than from `layerRegistry`: a forecast layer
  // exists only where a model has been trained and its grid built.
  useForecastGridLayers(manager, ready);
  useForecastVectorLayers(manager, ready);

  return (
    <div className="map-root">
      <div ref={containerRef} className="map-container" />
      {!ready && <div className="map-loading">Initializing map engine…</div>}
      {ready && <MapManagerContext.Provider value={manager}>{children}</MapManagerContext.Provider>}
      {/* Outside the context provider: both are driven by the hook above
          rather than by a child reaching for the manager itself. */}
      {ready && <VesselFeedStatus state={vessels} />}
      {ready && vessels.hovered && <VesselTooltip hovered={vessels.hovered} />}
      {ready && <EddyDetectionStatus state={eddies} />}
      {ready && eddies.hovered && <EddyTooltip hovered={eddies.hovered} />}
      {ready && <EdnaCoverageStatus state={edna} />}
      {ready && edna.hovered && <EdnaTooltip hovered={edna.hovered} />}
    </div>
  );
}
