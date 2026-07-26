import { useEffect, useRef } from 'react';
import type { GeoJSONSource, Map as MapLibreMap } from 'maplibre-gl';
import type { MapManager } from '../managers/MapManager';
import { useMapStore } from '../../../store/mapStore';
<<<<<<< HEAD
import { PIN_LAYER_ID, PULSE_LAYER_ID } from '../layers/annotationLayerIdsShared';

const SOURCE_ID = 'selected-location-source';
=======

const SOURCE_ID = 'selected-location-source';
const PULSE_LAYER_ID = 'selected-location-pulse';
const PIN_LAYER_ID = 'selected-location-pin';
>>>>>>> feature/map-label
const PIN_IMAGE_ID = 'selected-location-pin-image';

export function useSelectedLocationMarker(manager: MapManager | null, ready: boolean) {
  const selectedLocation = useMapStore((s) => s.selectedLocation);
  const animationFrameRef = useRef<number | null>(null);

  useEffect(() => {
    const map = manager?.getMap();
    if (!ready || !map) return;

    let cancelled = false;

    void ensureMarkerInfrastructure(map).then(() => {
      if (cancelled) return;

      if (selectedLocation) {
        setMarkerData(map, selectedLocation.lng, selectedLocation.lat);
        setMarkerVisibility(map, 'visible');
      } else {
        clearMarkerData(map);
        setMarkerVisibility(map, 'none');
      }
    });

    return () => {
      cancelled = true;
    };
  }, [manager, ready, selectedLocation]);

  useEffect(() => {
    const map = manager?.getMap();
    if (!ready || !map) return;

    let cancelled = false;

    void ensureMarkerInfrastructure(map).then(() => {
      if (cancelled) return;

      const animate = () => {
        if (cancelled) return;

        if (map.getLayer(PULSE_LAYER_ID)) {
          const phase = (Math.sin(performance.now() / 350) + 1) / 2;
          map.setPaintProperty(PULSE_LAYER_ID, 'circle-radius', 10 + phase * 5);
          map.setPaintProperty(PULSE_LAYER_ID, 'circle-opacity', 0.22 - phase * 0.1);
        }

        animationFrameRef.current = requestAnimationFrame(animate);
      };

      animate();
    });

    return () => {
      cancelled = true;
      if (animationFrameRef.current != null) {
        cancelAnimationFrame(animationFrameRef.current);
        animationFrameRef.current = null;
      }
    };
  }, [manager, ready]);

  useEffect(() => {
    const map = manager?.getMap();

    return () => {
      if (animationFrameRef.current != null) {
        cancelAnimationFrame(animationFrameRef.current);
        animationFrameRef.current = null;
      }

      if (!map) return;
      if (map.getLayer(PIN_LAYER_ID)) map.removeLayer(PIN_LAYER_ID);
      if (map.getLayer(PULSE_LAYER_ID)) map.removeLayer(PULSE_LAYER_ID);
      if (map.getSource(SOURCE_ID)) map.removeSource(SOURCE_ID);
      if (map.hasImage(PIN_IMAGE_ID)) map.removeImage(PIN_IMAGE_ID);
    };
  }, [manager]);
}

async function ensureMarkerInfrastructure(map: MapLibreMap) {
  if (!map.hasImage(PIN_IMAGE_ID)) {
    map.addImage(PIN_IMAGE_ID, await createPinImage());
  }

  if (!map.getSource(SOURCE_ID)) {
    map.addSource(SOURCE_ID, {
      type: 'geojson',
      data: emptyFeatureCollection(),
    });
  }

  if (!map.getLayer(PULSE_LAYER_ID)) {
    map.addLayer({
      id: PULSE_LAYER_ID,
      type: 'circle',
      source: SOURCE_ID,
      layout: { visibility: 'none' },
      paint: {
        'circle-color': '#ef4444',
        'circle-opacity': 0.18,
        'circle-radius': 12,
        'circle-stroke-color': '#7f1d1d',
        'circle-stroke-width': 1,
      },
    });
  }

  if (!map.getLayer(PIN_LAYER_ID)) {
    map.addLayer({
      id: PIN_LAYER_ID,
      type: 'symbol',
      source: SOURCE_ID,
      layout: {
        visibility: 'none',
        'icon-image': PIN_IMAGE_ID,
        'icon-size': 0.7,
        'icon-anchor': 'bottom',
        'icon-allow-overlap': true,
      },
    });
  }
}

function setMarkerData(map: MapLibreMap, lng: number, lat: number) {
  const source = map.getSource(SOURCE_ID) as GeoJSONSource | undefined;
  source?.setData({
    type: 'FeatureCollection',
    features: [
      {
        type: 'Feature',
        geometry: {
          type: 'Point',
          coordinates: [lng, lat],
        },
        properties: {},
      },
    ],
  });
}

function clearMarkerData(map: MapLibreMap) {
  const source = map.getSource(SOURCE_ID) as GeoJSONSource | undefined;
  source?.setData(emptyFeatureCollection());
}

function setMarkerVisibility(map: MapLibreMap, visibility: 'visible' | 'none') {
  if (map.getLayer(PULSE_LAYER_ID)) map.setLayoutProperty(PULSE_LAYER_ID, 'visibility', visibility);
  if (map.getLayer(PIN_LAYER_ID)) map.setLayoutProperty(PIN_LAYER_ID, 'visibility', visibility);
}

function emptyFeatureCollection() {
  return {
    type: 'FeatureCollection' as const,
    features: [],
  };
}

function createPinImage(): Promise<ImageBitmap> {
  const svg = `
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
      <path
        d="M12 22s7-6.14 7-12a7 7 0 1 0-14 0c0 5.86 7 12 7 12Z"
        fill="#ef4444"
        stroke="#7f1d1d"
        stroke-width="1.5"
        stroke-linejoin="round"
      />
      <circle cx="12" cy="10" r="3.2" fill="#fee2e2" />
    </svg>
  `;

  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = async () => {
      try {
        resolve(await createImageBitmap(image));
      } catch (error) {
        reject(error);
      }
    };
    image.onerror = () => reject(new Error('Failed to load selected location pin image'));
    image.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
  });
}
