import { useEffect } from 'react';
import type { GeoJSONSourceSpecification, Map as MapLibreMap } from 'maplibre-gl';
import type { MapManager } from '../managers/MapManager';
import { geographicLabels } from '../data/geographicLabels';
import {
  CONTINENT_GLOW_LAYER_ID,
  CONTINENT_LAYER_ID,
  OCEAN_GLOW_LAYER_ID,
  OCEAN_LAYER_ID,
} from '../layers/annotationLayerIdsShared';

const SOURCE_ID = 'geographic-labels-source';

export function useGeographicLabels(manager: MapManager | null, ready: boolean) {
  useEffect(() => {
    const map = manager?.getMap();
    if (!ready || !map) return;

    ensureLabelSource(map);
    ensureContinentGlowLayer(map);
    ensureContinentLayer(map);
    ensureOceanGlowLayer(map);
    ensureOceanLayer(map);

    return () => {
      if (map.getLayer(OCEAN_LAYER_ID)) map.removeLayer(OCEAN_LAYER_ID);
      if (map.getLayer(OCEAN_GLOW_LAYER_ID)) map.removeLayer(OCEAN_GLOW_LAYER_ID);
      if (map.getLayer(CONTINENT_LAYER_ID)) map.removeLayer(CONTINENT_LAYER_ID);
      if (map.getLayer(CONTINENT_GLOW_LAYER_ID)) map.removeLayer(CONTINENT_GLOW_LAYER_ID);
      if (map.getSource(SOURCE_ID)) map.removeSource(SOURCE_ID);
    };
  }, [manager, ready]);
}

function ensureLabelSource(map: MapLibreMap) {
  if (map.getSource(SOURCE_ID)) return;

  map.addSource(SOURCE_ID, {
    type: 'geojson',
    data: geographicLabels,
  } satisfies GeoJSONSourceSpecification);
}

function ensureContinentGlowLayer(map: MapLibreMap) {
  if (map.getLayer(CONTINENT_GLOW_LAYER_ID)) return;

  map.addLayer({
    id: CONTINENT_GLOW_LAYER_ID,
    type: 'symbol',
    source: SOURCE_ID,
    filter: ['==', ['get', 'kind'], 'continent'],
    layout: {
      'text-field': ['get', 'name'],
      'text-size': ['interpolate', ['linear'], ['zoom'], 1.5, 14, 3.5, 21, 6, 28],
      'text-letter-spacing': 0.2,
      'text-transform': 'uppercase',
      'text-allow-overlap': true,
      'text-ignore-placement': true,
      'text-max-width': 8,
    },
    paint: {
      'text-color': 'rgba(7, 14, 22, 0.92)',
      'text-opacity': 0.95,
      'text-halo-color': 'rgba(7, 14, 22, 0.92)',
      'text-halo-width': 3.4,
      'text-halo-blur': 1.3,
    },
  });
}

function ensureContinentLayer(map: MapLibreMap) {
  if (map.getLayer(CONTINENT_LAYER_ID)) return;

  map.addLayer({
    id: CONTINENT_LAYER_ID,
    type: 'symbol',
    source: SOURCE_ID,
    filter: ['==', ['get', 'kind'], 'continent'],
    layout: {
      'text-field': ['get', 'name'],
      'text-size': ['interpolate', ['linear'], ['zoom'], 1.5, 14, 3.5, 21, 6, 28],
      'text-letter-spacing': 0.2,
      'text-transform': 'uppercase',
      'text-allow-overlap': true,
      'text-ignore-placement': true,
      'text-max-width': 8,
    },
    paint: {
      'text-color': '#f7fbff',
      'text-opacity': 0.92,
      'text-halo-color': 'rgba(10, 20, 32, 0.94)',
      'text-halo-width': 1.4,
      'text-halo-blur': 0.4,
    },
  });
}

function ensureOceanGlowLayer(map: MapLibreMap) {
  if (map.getLayer(OCEAN_GLOW_LAYER_ID)) return;

  map.addLayer({
    id: OCEAN_GLOW_LAYER_ID,
    type: 'symbol',
    source: SOURCE_ID,
    filter: ['==', ['get', 'kind'], 'ocean'],
    layout: {
      'text-field': ['get', 'name'],
      'text-size': ['interpolate', ['linear'], ['zoom'], 1.5, 13, 3.5, 18, 6, 24],
      'text-letter-spacing': 0.12,
      'text-allow-overlap': true,
      'text-ignore-placement': true,
      'text-max-width': 10,
    },
    paint: {
      'text-color': 'rgba(8, 18, 28, 0.94)',
      'text-opacity': 0.92,
      'text-halo-color': 'rgba(8, 18, 28, 0.94)',
      'text-halo-width': 3,
      'text-halo-blur': 1.2,
    },
  });
}

function ensureOceanLayer(map: MapLibreMap) {
  if (map.getLayer(OCEAN_LAYER_ID)) return;

  map.addLayer({
    id: OCEAN_LAYER_ID,
    type: 'symbol',
    source: SOURCE_ID,
    filter: ['==', ['get', 'kind'], 'ocean'],
    layout: {
      'text-field': ['get', 'name'],
      'text-size': ['interpolate', ['linear'], ['zoom'], 1.5, 13, 3.5, 18, 6, 24],
      'text-letter-spacing': 0.12,
      'text-allow-overlap': true,
      'text-ignore-placement': true,
      'text-max-width': 10,
    },
    paint: {
      'text-color': '#d9f2ff',
      'text-opacity': 0.88,
      'text-halo-color': 'rgba(10, 20, 32, 0.94)',
      'text-halo-width': 1.2,
      'text-halo-blur': 0.5,
    },
  });
}
