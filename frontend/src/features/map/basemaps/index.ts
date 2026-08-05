import type { BasemapDefinition } from '../types';
import { abyss } from './abyss';
import { bathymetry } from './bathymetry';
import { esriSatellite } from './esri';
import { blueMarble } from './blueMarble';
import { darkMarine } from './darkMarine';

/**
 * Every basemap MapManager registers on init. Add a new module + one entry
 * here to introduce another basemap — nothing else needs to change.
 *
 * Ordered smoothest-first. The two vector styles render continuously at any
 * fractional zoom; the three raster ones below them are tile pyramids and
 * will always show a step as the camera crosses a zoom level, which is a
 * property of imagery rather than something left untuned.
 */
export const basemaps: BasemapDefinition[] = [
  abyss,
  bathymetry,
  esriSatellite,
  blueMarble,
  darkMarine,
];

export { abyss, bathymetry, esriSatellite, blueMarble, darkMarine };
