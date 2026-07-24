import type { BasemapDefinition } from '../types';
import { esriSatellite } from './esri';
import { blueMarble } from './blueMarble';
import { dark } from './dark';
import { streets } from './streets';

/** Every basemap MapManager registers on init. Add a new module + one
 * entry here to introduce another basemap — nothing else needs to change. */
export const basemaps: BasemapDefinition[] = [esriSatellite, blueMarble, dark, streets];

export { esriSatellite, blueMarble, dark, streets };
