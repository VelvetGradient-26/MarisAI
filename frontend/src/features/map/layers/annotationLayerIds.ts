import type { Map as MapLibreMap } from 'maplibre-gl';
import { PULSE_LAYER_ID, PIN_LAYER_ID } from './annotationLayerIdsShared';

export const annotationLayerIds = [PULSE_LAYER_ID, PIN_LAYER_ID] as const;

export function getFirstExistingAnnotationLayerId(map: MapLibreMap): string | undefined {
  return annotationLayerIds.find((id) => Boolean(map.getLayer(id)));
}
