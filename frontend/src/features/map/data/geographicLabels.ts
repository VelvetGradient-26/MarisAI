export const geographicLabels = {
  type: 'FeatureCollection',
  features: [
    continent('North America', -102, 48),
    continent('South America', -60, -17),
    continent('Europe', 18, 54),
    continent('Africa', 20, 5),
    continent('Asia', 90, 40),
    continent('Australia', 134, -25),
    continent('Antarctica', 20, -78),
    ocean('Pacific Ocean', -150, 3),
    ocean('Pacific Ocean', 160, -2),
    ocean('Atlantic Ocean', -33, 8),
    ocean('Indian Ocean', 77, -18),
    ocean('Southern Ocean', 20, -56),
    ocean('Arctic Ocean', 0, 78),
  ],
} as const;

function continent(name: string, lng: number, lat: number) {
  return pointFeature(name, 'continent', lng, lat);
}

function ocean(name: string, lng: number, lat: number) {
  return pointFeature(name, 'ocean', lng, lat);
}

function pointFeature(name: string, kind: 'continent' | 'ocean', lng: number, lat: number) {
  return {
    type: 'Feature',
    properties: { name, kind },
    geometry: {
      type: 'Point',
      coordinates: [lng, lat],
    },
  } as const;
}
