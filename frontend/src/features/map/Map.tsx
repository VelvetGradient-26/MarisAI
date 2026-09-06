import type { ReactNode } from 'react';
import { useMapManager } from './hooks/useMapManager';
import { MapManagerContext } from './hooks/MapManagerContext';
import { useSelectedLocationRealtimeData } from './hooks/useSelectedLocationRealtimeData';
import { useSelectedLocationMarker } from './hooks/useSelectedLocationMarker';
import { useSelectedLocationFocus } from './hooks/useSelectedLocationFocus';
import { useClickDive } from './hooks/useClickDive';
import { useLiveVessels } from './hooks/useLiveVessels';
import { useEddies } from './hooks/useEddies';
import { useCyclones } from './hooks/useCyclones';
import { usePfzZones } from './hooks/usePfzZones';
import { useGeofenceStatus } from './hooks/useGeofenceStatus';
import { useEdnaCoverage } from './hooks/useEdnaCoverage';
import { useMapStore } from '../../store/mapStore';
import { useDetectorCells } from './hooks/useDetectorCells';
import {
  fetchHeatwaveCells,
  fetchUpwellingCells,
  heatwaveResponseToGeoJson,
  upwellingResponseToGeoJson,
} from './api/detectors';
import {
  fetchOceanHeatContentMapCells,
  oceanHeatContentResponseToGeoJson,
  OCEAN_HEAT_CONTENT_LAYER_ID,
} from './api/oceanHeatContent';
import { useForecastGridLayers } from './hooks/useForecastGridLayers';
import { useForecastVectorLayers } from './hooks/useForecastVectorLayers';
import { VesselTooltip } from './VesselTooltip';
import { VesselFeedStatus } from './VesselFeedStatus';
import { EddyTooltip } from './EddyTooltip';
import { EddyDetectionStatus } from './EddyDetectionStatus';
import { CycloneTooltip } from './CycloneTooltip';
import { CycloneStatus } from './CycloneStatus';
import { PfzTooltip } from './PfzTooltip';
import { EdnaTooltip } from './EdnaTooltip';
import { EdnaCoverageStatus } from './EdnaCoverageStatus';
import { MarineHeatwaveStatus, UpwellingStatus, OceanHeatContentStatus } from './DetectorCellStatus';

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
  const cyclones = useCyclones(manager, ready);
  const edna = useEdnaCoverage(manager, ready);
  // Click-triggered, unlike every other layer above: they read the shared
  // `selectedLocation` and are gated on their own layer toggle, mirroring how
  // `SelectedLocationPanel` already fetches SST/wind/currents at a click.
  const selectedLocation = useMapStore((s) => s.selectedLocation);
  const pfz = usePfzZones(manager, ready, selectedLocation);
  useGeofenceStatus(manager, ready, selectedLocation);
  // Both refresh on a timer rather than on pan: the payload is global and a few
  // thousand cells, so a bbox would make every pan a request for data already
  // in memory. The cadences match how fast each backend cache can change —
  // OISST is daily, the wind blend hourly.
  const heatwaves = useDetectorCells(manager, ready, {
    layerId: 'marine-heatwaves',
    fetcher: fetchHeatwaveCells,
    toGeoJson: heatwaveResponseToGeoJson,
    refreshIntervalMs: 6 * 60 * 60 * 1000,
    fallbackMessage: 'Marine heatwave detection unavailable',
  });
  const upwelling = useDetectorCells(manager, ready, {
    layerId: 'upwelling',
    fetcher: fetchUpwellingCells,
    toGeoJson: upwellingResponseToGeoJson,
    refreshIntervalMs: 30 * 60 * 1000,
    fallbackMessage: 'Upwelling detection unavailable',
  });
  // A scheduled offline build, not a live field (see the layer's own
  // attribution) — 6h matches the heatwave cadence above, not upwelling's.
  const oceanHeatContent = useDetectorCells(manager, ready, {
    layerId: OCEAN_HEAT_CONTENT_LAYER_ID,
    fetcher: fetchOceanHeatContentMapCells,
    toGeoJson: oceanHeatContentResponseToGeoJson,
    refreshIntervalMs: 6 * 60 * 60 * 1000,
    fallbackMessage: 'Ocean heat content unavailable',
  });
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
      {ready && <CycloneStatus state={cyclones} />}
      {ready && cyclones.hovered && <CycloneTooltip hovered={cyclones.hovered} />}
      {ready && pfz.hovered && <PfzTooltip hovered={pfz.hovered} />}
      {ready && <MarineHeatwaveStatus state={heatwaves} />}
      {ready && <UpwellingStatus state={upwelling} />}
      {ready && <OceanHeatContentStatus state={oceanHeatContent} />}
      {ready && <EdnaCoverageStatus state={edna} />}
      {ready && edna.hovered && <EdnaTooltip hovered={edna.hovered} />}
    </div>
  );
}
