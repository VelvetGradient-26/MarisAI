import { useEffect } from 'react';
import { setWorkerUrl } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import { Map } from './Map';
import { MapControls } from './MapControls';
import { CoordinateDisplay } from './CoordinateDisplay';
import { SelectedLocationPanel } from './SelectedLocationPanel';
import { SstLegend } from './SstLegend';
import { WindLegend } from './WindLegend';
import { StoryMode } from './story/StoryMode';
import './styles/map.css';

// Configure MapLibre only when the lazy map route is loaded. This must run
// before MapManager constructs the first map instance.
setWorkerUrl(workerUrl);

/** Public entry point for the map feature — this is what App.tsx renders. */
export function MapView() {
  useEffect(() => {
    document.title = 'Maris AI | Ocean Map';
  }, []);

  return (
    <Map>
      <MapControls />
      <CoordinateDisplay />
      {/* One rail, not three independently-positioned overlays. The legends
          and the location panel both live on the right and both size
          themselves from their content, so as absolute siblings they drew
          straight over each other the moment either grew — measured at
          1440x749 with wind on and a location selected, the overlap was
          210px. Inside one flex column they cannot: the legends take the
          space they need from the top, the panel takes what is left. */}
      <div className="map-rail map-rail--right">
        <div className="legend-stack">
          <SstLegend />
          <WindLegend />
        </div>
        <SelectedLocationPanel />
      </div>
      {/* Last child so it stacks above the panels above — it is the only
          overlay that deliberately takes precedence over the others. */}
      <StoryMode />
    </Map>
  );
}
