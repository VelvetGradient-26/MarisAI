import { setWorkerUrl } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import { Map } from './Map';
import { MapControls } from './MapControls';
import { CoordinateDisplay } from './CoordinateDisplay';
import { SelectedLocationPanel } from './SelectedLocationPanel';
import './styles/map.css';

// Configure MapLibre only when the lazy map route is loaded. This must run
// before MapManager constructs the first map instance.
setWorkerUrl(workerUrl);

/** Public entry point for the map feature — this is what App.tsx renders. */
export function MapView() {
  return (
    <Map>
      <MapControls />
      <SelectedLocationPanel />
      <CoordinateDisplay />
    </Map>
  );
}
