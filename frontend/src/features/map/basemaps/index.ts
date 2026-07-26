import type { BasemapDefinition } from '../types';
import { esriSatellite } from './esri';
import { blueMarble } from './blueMarble';

/** Every basemap MapManager registers on init. Add a new module + one
 * entry here to introduce another basemap — nothing else needs to change. */
export const basemaps: BasemapDefinition[] = [esriSatellite, blueMarble];

export { esriSatellite, blueMarble };
