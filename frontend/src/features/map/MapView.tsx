import { Map } from './Map';
import { MapControls } from './MapControls';
import { CoordinateDisplay } from './CoordinateDisplay';
import { SelectedLocationPanel } from './SelectedLocationPanel';
import './styles/map.css';

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
