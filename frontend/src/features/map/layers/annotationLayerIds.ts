import type { Map as MapLibreMap } from 'maplibre-gl';
import {
  CONTINENT_GLOW_LAYER_ID,
  CONTINENT_LAYER_ID,
  OCEAN_GLOW_LAYER_ID,
  OCEAN_LAYER_ID,
  PULSE_LAYER_ID,
  PIN_LAYER_ID,
} from './annotationLayerIdsShared';

export const annotationLayerIds = [
  CONTINENT_GLOW_LAYER_ID,
  CONTINENT_LAYER_ID,
  OCEAN_GLOW_LAYER_ID,
  OCEAN_LAYER_ID,
  PULSE_LAYER_ID,
  PIN_LAYER_ID,
] as const;

export function getFirstExistingAnnotationLayerId(map: MapLibreMap): string | undefined {
  return annotationLayerIds.find((id) => Boolean(map.getLayer(id)));
}
