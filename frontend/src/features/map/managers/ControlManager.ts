import * as maplibregl from 'maplibre-gl';
import type { Map as MapLibreMap, IControl, ControlPosition } from 'maplibre-gl';

export interface ControlManagerOptions {
  navigation?: boolean;
  fullscreen?: boolean;
  scale?: boolean;
  geolocate?: boolean;
}

/**
 * Wraps MapLibre's built-in controls so nothing else in the app calls
 * map.addControl() directly — keeps every imperative MapLibre call behind
 * the manager layer (ADR Decision 3). The `controls/` folder alongside
 * this feature is reserved for bespoke controls later; built-ins live here.
 */
export class ControlManager {
  private map: MapLibreMap;
  private controls: IControl[] = [];

  constructor(map: MapLibreMap, options: ControlManagerOptions = {}) {
    this.map = map;
    const opts = { navigation: true, fullscreen: true, scale: true, geolocate: true, ...options };

    if (opts.navigation) {
      this.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'top-right');
    }
    if (opts.geolocate) {
      this.addControl(
        new maplibregl.GeolocateControl({
          positionOptions: { enableHighAccuracy: true },
          trackUserLocation: true,
        }),
        'top-right'
      );
    }
    if (opts.fullscreen) {
      this.addControl(new maplibregl.FullscreenControl(), 'top-right');
    }
    if (opts.scale) {
      this.addControl(new maplibregl.ScaleControl({ maxWidth: 120, unit: 'metric' }), 'bottom-left');
    }
  }

  private addControl(control: IControl, position: ControlPosition) {
    this.map.addControl(control, position);
    this.controls.push(control);
  }

  destroy() {
    for (const control of this.controls) {
      this.map.removeControl(control);
    }
    this.controls = [];
  }
}
