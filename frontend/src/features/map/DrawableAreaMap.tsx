import { useEffect, useRef } from 'react';
import * as maplibregl from 'maplibre-gl';
import type { GeoJSONSource, Map as MapLibreMap, MapMouseEvent } from 'maplibre-gl';
import type { Feature, Polygon } from 'geojson';
import 'maplibre-gl/dist/maplibre-gl.css';
import { darkMarine } from './basemaps/darkMarine';

export interface DrawnBbox {
  west: number;
  south: number;
  east: number;
  north: number;
}

interface DrawableAreaMapProps {
  bbox: DrawnBbox | null;
  onDraw: (bbox: DrawnBbox) => void;
}

const DRAW_SOURCE_ID = 'download-draw-rect';

/**
 * A standalone MapLibre instance, deliberately not the full MapManager /
 * LayerManager machinery the main dashboard map uses — that's coupled to the
 * layer registry/store and is overkill for "let the user drag out a
 * rectangle." No drawing library is installed anywhere in this codebase
 * (mapbox-gl-draw / terra-draw etc.); an axis-aligned rectangle is simple
 * enough to hand-roll with plain mouse events, matching the rest of the
 * codebase's "hand-roll it" convention.
 */
export function DrawableAreaMap({ bbox, onDraw }: DrawableAreaMapProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const onDrawRef = useRef(onDraw);
  onDrawRef.current = onDraw;

  useEffect(() => {
    if (!containerRef.current) return undefined;

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: {
        version: 8,
        sources: { basemap: darkMarine.source },
        layers: [{ id: 'basemap', type: 'raster', source: 'basemap' }],
      },
      center: [75, 12],
      zoom: 2.5,
      renderWorldCopies: false,
      attributionControl: { compact: true },
    });
    mapRef.current = map;

    let drawStart: maplibregl.LngLat | null = null;

    // LngLatBounds(sw, ne) takes its two corners literally — it does NOT sort
    // them into (min, max), so passing (dragStart, currentPoint) straight
    // through breaks for any drag direction other than "started at the
    // southwest corner." Normalizing min/max ourselves handles every drag
    // direction (e.g. dragging from top-left to bottom-right, the common
    // case, otherwise produces an inverted north < south rectangle).
    function normalize(a: maplibregl.LngLat, b: maplibregl.LngLat): DrawnBbox {
      return {
        west: Math.min(a.lng, b.lng),
        east: Math.max(a.lng, b.lng),
        south: Math.min(a.lat, b.lat),
        north: Math.max(a.lat, b.lat),
      };
    }

    function rectGeoJson(rect: DrawnBbox): Feature<Polygon> {
      const { west, south, east, north } = rect;
      return {
        type: 'Feature',
        properties: {},
        geometry: {
          type: 'Polygon',
          coordinates: [
            [
              [west, south],
              [east, south],
              [east, north],
              [west, north],
              [west, south],
            ],
          ],
        },
      };
    }

    function setRect(rect: DrawnBbox) {
      const source = map.getSource(DRAW_SOURCE_ID) as GeoJSONSource | undefined;
      source?.setData(rectGeoJson(rect));
    }

    function onMouseDown(e: MapMouseEvent) {
      drawStart = e.lngLat;
      map.dragPan.disable();
      map.getCanvas().style.cursor = 'crosshair';
    }

    function onMouseMove(e: MapMouseEvent) {
      if (!drawStart) return;
      setRect(normalize(drawStart, e.lngLat));
    }

    function finishDraw(e: MapMouseEvent) {
      if (!drawStart) return;
      const rect = normalize(drawStart, e.lngLat);
      setRect(rect);
      drawStart = null;
      map.dragPan.enable();
      map.getCanvas().style.cursor = '';
      onDrawRef.current(rect);
    }

    map.once('load', () => {
      map.addSource(DRAW_SOURCE_ID, {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] },
      });
      map.addLayer({
        id: 'download-draw-rect-fill',
        type: 'fill',
        source: DRAW_SOURCE_ID,
        paint: { 'fill-color': '#4fd1ff', 'fill-opacity': 0.15 },
      });
      map.addLayer({
        id: 'download-draw-rect-outline',
        type: 'line',
        source: DRAW_SOURCE_ID,
        paint: { 'line-color': '#4fd1ff', 'line-width': 2 },
      });
    });

    map.on('mousedown', onMouseDown);
    map.on('mousemove', onMouseMove);
    map.on('mouseup', finishDraw);
    map.on('mouseout', () => {
      drawStart = null;
      map.dragPan.enable();
    });

    return () => {
      map.remove();
      mapRef.current = null;
    };
    // Runs once: onDraw is threaded through a ref so the map isn't torn down
    // and rebuilt on every parent re-render (e.g. every keystroke elsewhere
    // in the download form).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Keep the drawn-rectangle overlay in sync if the bbox is edited via the
  // typed number inputs instead of drawn — a two-way binding, not just draw-to-form.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const source = map.getSource(DRAW_SOURCE_ID) as GeoJSONSource | undefined;
    if (!source) return;
    if (!bbox) {
      source.setData({ type: 'FeatureCollection', features: [] });
      return;
    }
    source.setData({
      type: 'Feature',
      properties: {},
      geometry: {
        type: 'Polygon',
        coordinates: [
          [
            [bbox.west, bbox.south],
            [bbox.east, bbox.south],
            [bbox.east, bbox.north],
            [bbox.west, bbox.north],
            [bbox.west, bbox.south],
          ],
        ],
      },
    });
  }, [bbox]);

  return <div ref={containerRef} className="download-draw-map" />;
}
