import type { BasemapDefinition } from '../types';
import { esriSatellite } from './esri';
import { blueMarble } from './blueMarble';
import { darkMarine } from './darkMarine';

/** Every basemap MapManager registers on init. Add a new module + one
 * entry here to introduce another basemap — nothing else needs to change. */
export const basemaps: BasemapDefinition[] = [esriSatellite, blueMarble, darkMarine];

export { esriSatellite, blueMarble, darkMarine };
